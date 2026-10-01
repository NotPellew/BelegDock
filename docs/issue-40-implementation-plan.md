# Implementation Plan — Issue #40: Cancellable progress and actionable recovery states for desktop operations

## 0. Current baseline (verified)

- Full suite: **251 tests, 246 passed, 5 failed**. The 5 failures are the frozen async-contract tests from checkpoint commit `df30838` ("test: checkpoint approved issue 40 async contract"), which modified 5 test files to require `_dispatch_operation` dispatch. They are the approved RED evidence for this issue and must go GREEN.
- `scripts/replay_red.py --verify` **currently fails** at `desktop_already_present: test differs from its approved checkpoint` — the 4 replayed files changed in `df30838` but `GROUPS` still points at the pre-async checkpoints. This desync must be repaired as part of delivery (details in §4.3).

---

## 1. Current architecture and where synchronous work blocks the Tk event loop

**Layering** (already matches the AGENTS.md widget-free-service rule):
- `src/belegdock/workflow.py` — `Store`: SQLite (`state.sqlite3`) + blob staging, the upload state machine (`staged → uploading → uploaded/rejected/uncertain`), per-digest upload lock, `recover-upload`/`reconcile`.
- `src/belegdock/integrations.py` — `GmailAdapter` (labels, paged candidates, fetch) and `LexwareAdapter` (upload POST, inventory GETs with 429 retry, `verify_existing`).
- `src/belegdock/service.py` — `refresh_remote_inventory` (thin wrapper).
- `src/belegdock/desktop.py` — `DesktopService` (widget-free facade over the above) and `DesktopApplication` (the Tk view).

**The problem:** every operation runs synchronously inside Tk callbacks in `DesktopApplication`:
- `__init__` → `_load_labels()` → `service.labels()` (Gmail API) → `_load_candidates()` → `service.candidates()` (paged Gmail API) — at startup, before `mainloop()`.
- `_label_changed` → `_load_candidates()` on every combobox selection.
- `_stage` button → `service.stage()` (Gmail fetch + per-attachment SQLite/blob writes).
- `_load_documents()` → `service.documents()` (SQLite + per-blob streaming SHA-256 integrity reads) — at startup, after staging, after upload.
- `_upload` → confirmation dialog → `service.upload()` (inventory refresh GETs, then the Lexware POST, then state transitions).

**Guards and gaps:** `DesktopService._flight` (non-blocking `Lock`) raises `RuntimeError` if a second operation starts — but that exception escapes into the Tk callback with a raw traceback. There is no worker thread, no `root.after` marshaling, no queue, no progress widget, no cancel button. `_safe_error(operation, error)` maps only 6 operation keys to generic German text; it does not distinguish local-storage / Gmail / auth / connectivity / rejection / uncertain categories. The only concurrency primitive in `src/` is `threading.Lock` in `desktop.py`.

**Frozen async contract (dictates the seam):** checkpoint `df30838` added `tests/app/async_dispatch_test_helper.py` (`ManualOperationDispatcher.__call__(operation, completed)`; `complete_next()` runs the thunk synchronously and calls `completed(result, error)`) and wired it into 5 tests via `app._dispatch_operation = dispatcher`. The contract:
- `_load_labels()` must **not** populate the combobox synchronously; after `complete_next()` it sets values, selects index 0, and calls `_load_candidates()` exactly once.
- `_load_candidates()` must **not** populate the tree synchronously; after `complete_next()` rows exist and `selection()` was never called.
- `_upload()` keeps validation + `messagebox.askyesno` synchronous, but `service.upload` must not be called synchronously; after `complete_next()` the notice shows the outcome (rejection text without "unklar"; already-present text with IDs).
- Tests build the app via `DesktopApplication.__new__` and set only the attributes they need — so every new lifecycle helper must use the existing `getattr(self, name, None)` defensive pattern (as `_set_action_region` and `_load_documents` already do), and boolean flags need class-level defaults so `__new__` instances see them.

---

## 2. Step-by-step implementation plan

### 2.1 Worker-thread dispatcher with event-loop marshaling (new, in `desktop.py`)

Add `_TkWorkerDispatcher` (production default for `self._dispatch_operation`, set in `__init__` after `self.root` exists):
- `__call__(operation, completed)`: starts one **daemon** thread running the zero-arg thunk; on finish puts `(completed, result, error)` on a `queue.Queue`.
- `report(event)`: puts `(None, event, None)` on the same queue — the thread-safe progress channel (direct `root.after` from a worker is unsafe on Windows; the queue + pump is the safe pattern).
- A `root.after(20, self._pump)` loop drains the queue on the event loop: `completed is None` → `self._handle_operation_event(event)`; else `completed(result, error)`. The pump catches broad exceptions per event (print to stderr) so one bad completion can never kill the loop; `_schedule_pump` swallows `TclError` after destroy and stops.
- `close()` sets a closed flag (used by shutdown, §2.6).

`DesktopApplication.__init__` gains, before `_build()`: `self._dispatch_operation = _TkWorkerDispatcher(self.root, self._handle_operation_event)`, `self._cancel_event = threading.Event()`, and the close protocol `self.root.protocol("WM_DELETE_WINDOW", self._request_close)`. Class-level defaults `_operation_active = False`, `_uncancellable = False`, `_closed = False`, `_close_after_completion = False` so `__new__`-built test doubles keep working.

### 2.2 Async operation methods (rewrite of the five event handlers)

Each follows: guard `if self._operation_active: return` → `_begin_operation(text)` → `self._dispatch_operation(thunk, self._X_completed)`. All widget touches go through defensive helpers (`_set_text`, `_set_widget_state`, `_set_cancel_enabled`, `_set_actions_enabled`) that no-op when the attribute or its method is missing.

- `_load_labels()` → thunk `service.labels()`; `_labels_completed` populates the combobox, selects the first label, calls `_load_candidates()`. Discards the result if the cancel event was set (per the "in-flight request may finish, result discarded" decision).
- `_load_candidates()` → clears the tree synchronously, then thunk `service.candidates(label)`; `_candidates_completed` populates rows + notice.
- `_stage()` → thunk `service.stage(label, ids, progress=self._report_event, cancelled=self._cancel_event.is_set)`; `_stage_completed` handles `OperationCancelled` (counts from the exception), categorized errors, success notice, then `_reload_documents()`.
- `_upload()` → unchanged synchronous validation (selection/integrity/status) + confirmation; then thunk `service.upload(digest, cancelled=..., phase=self._report_event)`; `_upload_completed` handles `OperationCancelled` / `DocumentRejected` / categorized errors / success / already-present, then `_reload_documents()`, then deferred close if requested.
- **Document refresh without touching frozen tests:** keep `_load_documents(result=None)` as the synchronous worker (frozen tests call it directly; when `result` is passed it skips the fetch). Add `_reload_documents()` = `_begin_operation` + dispatch of `service.documents()`; `_documents_loaded` ends the operation and calls `self._load_documents(result)`. Runtime call sites (`__init__`, `_stage_completed`, `_upload_completed`) use `_reload_documents()`. This offloads document refresh with **zero existing-test changes**.

### 2.3 Service/workflow changes for progress and cancellation boundaries

- `workflow.py`: new `OperationCancelled(RuntimeError)` with `completed`/`total` attributes (raised by `Store.upload` and `DesktopService.stage`); new `UploadOutcomeUncertain(RuntimeError)` (subclass keeps `assertRaises(RuntimeError)` in `test_desktop_states` green) replacing the bare `RuntimeError("upload outcome is uncertain…")` in `Store.upload`.
- `Store.upload(..., *, cancelled=None, phase=None)`: check `cancelled()` after lock/row read, after `_read_staged`, and after refresh/verify — **before** any state mutation — raising `OperationCancelled` so the row stays `staged` (no partial row, no send). After the final check, call `phase("uploading")` immediately before the `BEGIN IMMEDIATE … status='uploading'` write: that is the visible, durable point of no return. The POST (`uploader(data, filename)`) then runs with no cancellation.
- `DesktopService.stage(..., *, progress=None, cancelled=None)`: check `cancelled()` **before** each attachment's fetch (an in-flight fetch finishes, its result is discarded); after each `store.stage` commit, `progress("progress", done, total)` — determinate by selected attachment count; completed attachments remain durable.
- `DesktopService.upload(..., *, cancelled=None, phase=None)`: pass-through to `Store.upload`.
- `integrations.py`: `GmailAdapter.candidates(..., *, cancelled=None)` checks the token between pages and between message gets (cooperative boundaries). `LexwareAdapter.upload` raises a new `RemoteAuthError(RuntimeError)` with `status_code` for 401/403 (500 and others stay `RuntimeError`, preserving `test_integrations.py:217`). `RemoteAuthError` lives in `workflow.py` next to `DocumentRejected` and is imported by `integrations.py` (no new module).

### 2.4 Progress and busy UI (new widgets in `_build`)

A status strip below `self.sections` in the main frame: `operation_status` (`tk.StringVar`), `ttk.Progressbar` (indeterminate by default), and an "Abbrechen" cancel button that is **always visible but disabled when idle** (maintainer decision, §4.2). `_begin_operation` starts indeterminate progress, enables cancel, disables stage/upload buttons and the label combobox. `_handle_operation_event` switches to determinate on `("progress", done, total)` (updating the text from a per-operation template) and, on `("phase", "uploading")`, sets `_uncancellable = True`, disables cancel, and shows the uncancellable notice below. `_end_operation` resets everything. `_cancel_operation` sets the event, disables the button, shows the cancel-requested text. Label changes are ignored while an operation is active — no cancel-and-restart (maintainer decision, §4.2).

**Finalized German strings for the operation lifecycle (maintainer decision, §4.2):**

| State | String |
| --- | --- |
| Cancel button label | "Abbrechen" |
| Labels loading (indeterminate) | "Gmail-Labels werden geladen…" |
| Candidates loading (indeterminate) | "Anhänge werden geladen…" |
| Staging start (indeterminate) | "Ausgewählte Dateien werden vorbereiten…" |
| Staging progress (determinate) | "Vorbereiten %(done)d von %(total)d…" |
| Document refresh (indeterminate) | "Dokumente werden aktualisiert…" |
| Upload pre-POST (indeterminate) | "Lexware-Inventar wird geprüft…" |
| Upload POST (uncancellable) | "Senden läuft; Abbruch ist nicht möglich. Bei unklarem Ergebnis ist die CLI-Wiederherstellung erforderlich." |
| Cancel requested | "Abbruch wird angefordert…" |
| Close during cancellable operation | "Abbruch wird angefordert; die Oberfläche wird nach dem nächsten sicheren Punkt geschlossen." |
| Close during uncancellable operation | "Senden läuft; die Oberfläche wird nach dem Ergebnis geschlossen." |

### 2.5 German categorized failure/recovery messages

Replace `_safe_error` call sites with `failure_guidance(operation, error, digest=None)` in `desktop.py`, returning concise German text with the hash where applicable and a README reference. Detection order: `DocumentRejected` → rejection (existing text); `OperationCancelled` → cancellation; `LocalIntegrityError` → local storage; `UploadOutcomeUncertain` → uncertain + hash + CLI recovery + README; `TransferActiveError` → "anderer Vorgang aktiv, nicht erneut senden"; `status_code in (401, 403)` → auth (`login-gmail`/`login-lexware`); `isinstance(error, (OSError, httpx.HTTPError))` → connectivity; operation-scoped fallback (`labels`/`candidates`/`stage` → Gmail; `upload` → Lexware unreachable; `documents` → local storage). **Finalized strings (maintainer decision, §4.2):**
- Cancelled (generic): "Vorgang abgebrochen."
- Cancelled (staging): "Vorbereiten abgebrochen; %(done)d von %(total)d Dateien lokal gespeichert; nichts wurde an Lexware gesendet."
- Cancelled (upload): "Senden abgebrochen; das Dokument bleibt lokal vorbereitet und wurde nicht gesendet."
- Rejected: "Lexware hat das Dokument abgelehnt; korrigiere das Dokument und bereite die neuen Bytes vor."
- Local: "Lokaler Speicher ist nicht verfügbar; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. Siehe README.md."
- Gmail: "Gmail-Daten konnten nicht geladen werden; prüfe die Kontoverbindung und das Label."
- Auth: "Anmeldung fehlgeschlagen oder abgelaufen; melde das Konto mit „login-gmail“ bzw. „login-lexware“ erneut an."
- Connectivity: "Verbindung fehlgeschlagen; prüfe die Internetverbindung und versuche es erneut."
- Transfer active: "Ein anderer Vorgang ist aktiv für %(hash)s; warte, bis er beendet ist. Nicht erneut senden."
- Uncertain: "Sendeergebnis für %(hash)s unklar; nicht erneut senden. Verwende die CLI-Befehle zur Wiederherstellung und Abstimmung. Siehe README.md."
- Lexware unreachable (upload fallback): "Lexware ist nicht erreichbar; prüfe die Internetverbindung und versuche es erneut."
- Generic fallback: "Vorgang fehlgeschlagen; prüfe Kontoverbindung und lokalen Speicher. Siehe README.md."

**String-conflict check (performed, no test changes):** the finalized strings were compared against every German assertion in `tests/app/`. The rejection string still satisfies `test_desktop_states.py` ("korrigiere das dokument", "neuen bytes", no "unklar"); the uncertain failure-path string is new (the asserted uncertain precheck string in `test_german_localization.py`/`test_desktop_layout_states.py` belongs to the unchanged `document_action_state`); the local string contains the phrase asserted by `test_desktop_integrity.py`; and no test asserts the old desktop `_safe_error` strings being replaced. **No conflicts; no test changes required.**

After cancellation, rejection, or uncertain outcomes the completion handlers call `_reload_documents()` and never re-dispatch `upload` — no automatic resend. On startup, `uploading`/`uncertain` rows keep the existing CLI-only guidance (`document_action_state` is unchanged) and the upload button stays disabled for them.

### 2.6 Shutdown safety

- `_request_close()`: if an operation is active and cancellable → set the cancel event (stop at next safe boundary), set `_close_after_completion`, show a notice, and destroy immediately — the daemon worker finishes the current atomic unit (per-attachment commit; blob writes are temp+rename) and is abandoned at process exit; SQLite connections are per-call in `Store._connection`, so no cross-thread connection sharing. If active and uncancellable (POST in flight) → set `_close_after_completion` and defer; `_upload_completed` closes after the outcome is recorded. If idle → close now.
- `_close()`: sets `_closed`, calls `dispatcher.close()`, destroys the root inside `try/except`. Every `_X_completed` and `_handle_operation_event` starts with `if self._closed: return`, and the pump stops after destroy — so completions after close are harmless no-ops.
- Closing during the pre-POST refresh: the in-flight refresh finishes, the cancel check fires before the `uploading` write, the row stays `staged`, the completion is queued to the dead pump and ignored. Closing during the POST: deferred until the outcome is recorded (uploaded/rejected/uncertain); a hard kill leaves `uploading`, which `recover-upload` already handles.

---

## 3. Tests

### 3.1 Deterministic fake-service tests (new file `tests/app/test_desktop_operations.py`, plus a small queue-based `ThreadedDispatcher` helper in the same file — thread + queue with a manual `pump()` and `record` support, no Tk needed)

Fake services with controlled `time.sleep` delays and call recording (patterns reused from `test_desktop_states.py`). Tests:
1. **Slow label load** — busy text visible during flight, combobox empty, populated only after completion; second `_load_labels()` during flight starts no second service call (no concurrent operation).
2. **Slow candidate load** — same busy/populate contract; tree not touched before completion.
3. **Determinate staging progress** — 3 attachments, fetch sleeps; progress events are exactly `("progress", 1..3, 3)`; UI text shows "x von 3".
4. **Staging cancellation between attachments** — cancel from inside the fake fetch after attachment 2; assert `OperationCancelled` path: notice shows "abgebrochen; 2 von 3", store holds exactly 2 staged documents, no partial row for the 3rd, documents reloaded, no upload dispatched.
5. **Upload cancel before the POST boundary** — fake `inventory` sleeps; cancel during refresh; assert the POST (`remote.upload`) is never called, the document stays `staged`, notice explains cancellation, documents reloaded, upload never re-dispatched.
6. **Cancel disabled after the POST begins** — fake `upload` sleeps; assert the `("phase", "uploading")` event disables the cancel button and shows the CLI-recovery text; the upload runs to its outcome and is recorded.
7. **Rejection vs. uncertain** — `DocumentRejected(400)` → corrective guidance, no "unklar"; `OSError` from the POST → store status `uncertain`, guidance with the hash, no resend.
8. **Failure categorization matrix** — parametrized fakes for local integrity, Gmail `ValueError`, 401 (`RemoteAuthError`), `OSError`, uncertain → assert the German category text and next step.
9. **Durable-state reload without resend** — pre-seed a document with `status='uploading'` via `Store` directly (simulating an interrupted upload); load documents; assert CLI-recovery guidance visible, upload button disabled, `service.upload` never dispatched.
10. **Shutdown safety** — `_request_close` during a cancellable operation sets the cancel event and closes without touching widgets from the worker; completion after close is a no-op; close during the uncancellable phase defers until the outcome is recorded.

RED evidence for these (plus the 5 frozen async tests) is recorded with `scripts/test_evidence.py` before implementation and GREEN after, per AGENTS.md.

### 3.2 Native Windows Tk smoke check (frozen-installer smoke workflow; maintainer decision, §4.2)

The native check runs **inside the existing frozen-installer smoke workflow** (`packaging/build_windows.py smoke-install` in `.github/workflows/windows-installer.yml`) — **not** in `checks.yml`. This proves the visible states on the real frozen bundle (whose Tcl/Tk initialization the artifact check cannot prove) and needs no credentials.

Approach: a test-only env hook (e.g. `BELEGDOCK_DESKTOP_SMOKE=1` plus a state-dump path) read in `run_desktop`. Without the env var the behavior is unchanged (production path untouched). With it, `run_desktop` skips real credential loading and wires deterministic fake Gmail/Lexware services (small scripted delays) over a temp `Store`, then drives a scripted self-test and appends one JSON line per visible-state transition to the dump file. The smoke step launches the frozen GUI exe, waits for the dump to reach a terminal state, asserts the state sequence, closes the window, and asserts a clean exit.

Visible states covered (asserted via the dump): busy text during label load → populated combobox → candidate rows; determinate staging progress text ("Vorbereiten x von y…"); cancel button enabled → disabled at the upload boundary with the uncancellable notice; a staged document row after staging; wide/narrow layout switch on resize (existing `DESKTOP_LAYOUT_BREAKPOINT` behavior); clean destroy during a slow staging operation (no exception, staged attachments remain in the temp data dir).

An optional developer convenience (not CI-gated): a pytest variant `tests/app/test_desktop_native_tk.py` with `skipUnless(sys.platform == "win32")` that builds a real `DesktopApplication` with real `tk.Tk()` and the same fakes, driving the event loop via `root.update()` — useful on a local Windows desktop, but the CI gate is the installer smoke workflow above.

### 3.3 Existing tests that must change

**None — no existing test bytes change.** The recommended design keeps `_load_documents` synchronous (frozen tests call it directly) and adds `_reload_documents` for runtime call sites, so all 246 currently-passing tests stay passing and the 5 frozen async tests go GREEN. (The alternative — making `_load_documents` itself async — would require approval-gated changes to `test_desktop_already_present.py::test_already_present_document_has_a_distinct_state`, `test_desktop_detail_reset.py::test_reload_clears_detail_values_for_removed_document`, and `test_desktop_integrity.py::test_damaged_document_is_not_ready_or_uploadable_and_shows_restore_guidance`; not recommended.)

**Bookkeeping that does change:** `scripts/replay_red.py` `GROUPS`/`FOCUSED` must be repointed at checkpoint `df30838` with corrected metadata (no test bytes change — this is the required "GROUPS update" for the already-approved checkpoint):
- `desktop_already_present`: checkpoint `c13c26e…` → `df30838…`, count 2 → 1, `FOCUSED` → `{test_already_present_result_says_no_upload_was_sent}` (the distinct-state test passes at `df30838` and can no longer be focused).
- `desktop_states`: checkpoint `316a373…` → `df30838…`, count 2 → 1, `FOCUSED` → `{test_rejection_shows_corrective_guidance_not_uncertain_guidance}`.
- `scan_classification`: checkpoint `da035b9…` → `df30838…`, count 10 → 1, add `FOCUSED = {test_candidate_table_displays_type_and_recommendation_without_selecting}`.
- `scan_classification_review`: checkpoint `eb25ed2…` → `df30838…`, count 4 → 1, add `FOCUSED = {test_desktop_keeps_candidate_when_optional_classification_is_stale}`.

Then run `scripts/replay_red.py --verify` (must print "Verified 44 frozen RED groups") and a full `scripts/replay_red.py --output …` replay to regenerate evidence.

---

## 4. Risks, open questions, files

### 4.1 Risks
- **Tk thread-safety**: any widget touch from the worker crashes on Windows. Mitigation: single queue + pump, `_closed` guards, code review, native check.
- **Installer-smoke GUI launch**: the frozen GUI exe must create a window on the `windows-latest` runner during `smoke-install`. The step already launches `console desktop` there, so a desktop session exists, but the first run must confirm the exe's Tk initializes and the state dump appears; the hook must be inert without its env var (no production behavior change).
- **Pump/destroy race**: completions arriving after `root.destroy()` raise `TclError`. Mitigation: `_closed` flag, guarded `_schedule_pump`, per-event exception handling in the pump.
- **Cancel/POST race**: a click landing between the final cancel check and `phase("uploading")` is ignored — the conservative outcome (upload proceeds) is intended; the check ordering is the real guard, the button disable is cosmetic.
- **Ignored label change during flight** (maintainer decision): the combobox selection can change visually while an operation runs for the previous label; the operator might be confused why nothing happens. Mitigation: the combobox is disabled during operations, so the selection cannot actually change while busy.
- **SQLite from the worker**: connections are per-call and there is exactly one worker thread, so no cross-thread sharing; `BEGIN IMMEDIATE` with `timeout=30` covers the CLI's concurrent first-start edge.
- **Packaging**: new imports (`queue`, `threading`) are stdlib — no `pyproject.toml`/`uv.lock` impact; the installer test hook must be inert without its env var.

### 4.2 Resolved decisions (confirmed by the maintainer; no longer open)

1. **Label change while an operation is in flight: ignored** — no cancel-and-restart. The combobox is disabled during operations so the selection cannot change; `_label_changed` returns early while `_operation_active`.
2. **Cancel button always visible but disabled when idle** — no show/hide logic; state changes only.
3. **Cancellation is checked only at the two pre-POST upload boundaries** (after lock/row read and after refresh/verify, before any state mutation) — no checks inside `LexwareAdapter.inventory`'s pagination loop. An in-flight refresh finishes; its result is discarded if the cancel event was set.
4. **German strings finalized** — see the tables in §2.4 (operation lifecycle) and §2.5 (failure categories). A conflict check against all German assertions in `tests/app/` found no conflicts; no test changes result.
5. **Native Windows Tk smoke check runs inside the existing frozen-installer smoke workflow** (`packaging/build_windows.py smoke-install`) — not in `checks.yml`. See §3.2.

No open questions remain for the plan author. Per the test-change approval rule, if any future string adjustment conflicts with an existing test expectation, the conflict is flagged in this plan rather than changing tests.

### 4.3 Files expected to change
**Source:** `src/belegdock/desktop.py` (dispatcher, async operation methods, progress/cancel UI, categorized messages, shutdown protocol — the bulk); `src/belegdock/workflow.py` (`OperationCancelled`, `UploadOutcomeUncertain`, `RemoteAuthError`, `Store.upload` cancel/phase params); `src/belegdock/integrations.py` (`GmailAdapter.candidates` cancel checks, `LexwareAdapter.upload` 401/403 → `RemoteAuthError`); `src/belegdock/service.py` — no change.
**Tests (new):** `tests/app/test_desktop_operations.py`, `tests/app/test_desktop_native_tk.py`.
**Bookkeeping (remains in scope for implementation):** `scripts/replay_red.py` (GROUPS/FOCUSED repointed at `df30838`). This fix is required for CI to pass: `scripts/replay_red.py --verify` currently fails at `desktop_already_present` because the four replayed test files changed in `df30838` while their registered checkpoints still point at the pre-async revisions. No test bytes change — only the replay metadata is repointed at the already-approved checkpoint.
**Docs:** `README.md` (cancellation rules: cancel disabled after the POST begins; closing during upload defers to the outcome), `docs/arc42.md` (async desktop operations, cancellation boundaries, new exception types).
**No changes:** `pyproject.toml`, `uv.lock`, `src/belegdock/cli.py`, `src/belegdock/accounts.py`, `src/belegdock/classification.py`, all existing test files.
