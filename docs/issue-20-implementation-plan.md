# Implementation Plan — Issue #20: Explain empty scan results and name damaged documents on integrity failures

## 0. Current Baseline

- Clean branch `codex/issue-20-empty-scan-and-integrity-names` tracking `origin/main` (`5e723ad`).
- Passing baseline: **270 tests passed**.
- Replay verification: **44 frozen RED groups verified**.

---

## 1. Problem and Desired Outcome

1. When `belegdock scan --label <LABEL>` finds no matching PDF or XML candidate attachments, it writes `[]` to stdout and emits no information to stderr. The operator cannot determine whether the label has no messages, the messages have no attachments, or the attachments are unsupported types.
2. When `belegdock documents` detects local blob integrity failures (`localIntegrity != "ok"`), or when single-document operations (`upload`, `recover-upload`, `reconcile`) encounter a damaged blob (`LOCAL_INTEGRITY_FAILED`), the error message states generic restore advice (`Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. Wiederherstellung ist erforderlich.`) without naming which document(s) by filename or hash are damaged.

Desired outcome:
- An empty `scan` prints `[]` to stdout (valid JSON array, exit 0) and emits a single clear German note to stderr naming the label.
- A local integrity failure names the affected document filename(s), hash(es), and integrity status (`missing`, `corrupt`, `unreadable`), followed by the standard restore guidance.

---

## 2. Confirmed Design Decisions

1. **Empty `scan` result**:
   - Exit code: `0`.
   - Stdout: `[]\n` (valid JSON array, preserving pipability and automation).
   - Stderr: Exactly one informative line:
     `Keine PDF- oder XML-Anhänge im Gmail-Label '<LABEL>' gefunden.`
   - Non-empty scan: Emits nothing to stderr.
   - Suppressibility: No `--quiet` flag added; Unix convention holds (structured output on stdout, diagnostics on stderr).

2. **Naming damaged documents in `belegdock documents`**:
   - Exit code: `1`.
   - Stdout: Full JSON array as before, with `"localIntegrity"` on each item.
   - Stderr: Formats damaged documents followed by restore guidance:
     ```
     Lokale Dokumentintegrität fehlgeschlagen; folgende Dateien sind beschädigt oder fehlen:
       - <filename> (<hash>): <status-description>
     Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. Wiederherstellung ist erforderlich.
     ```
   - **Capping**: Lists up to 5 damaged documents. If more than 5 exist, appends:
     `  ... und N weitere beschädigte Dokumente.`
   - Preserves the exact restore guidance sentence for compatibility with existing tests.

3. **Naming damaged document in single-document commands (`upload`, `recover-upload`, `reconcile`)**:
   - Exit code: `1`.
   - When encountering `LOCAL_INTEGRITY_FAILED`:
     `Lokale Dokumentintegrität fehlgeschlagen für <filename> (<hash>): Blob ist <integrity>. Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. Wiederherstellung ist erforderlich.`

4. **Security & Privacy boundary**:
   - Never exposes full filesystem paths, stack traces, or document content on stderr.
   - For `unreadable` blobs caused by OS/filesystem permission errors, reports `unreadable` without leaking raw OS errno or private directory paths.

---

## 3. Acceptance Criteria to Test Mapping

| Acceptance Criterion | Test Name in `tests/app/test_cli_empty_scan_and_integrity_names.py` | Expected Failure (RED) |
| :--- | :--- | :--- |
| Empty `scan` outputs `[]` on stdout, exits 0, and emits label explanation on stderr | `test_scan_empty_results_prints_json_array_and_stderr_explanation` | `AssertionError` |
| Non-empty `scan` outputs candidates on stdout and emits nothing on stderr | `test_scan_non_empty_results_emits_no_stderr_explanation` | `AssertionError` |
| `documents` with missing blob names filename, hash, status on stderr and exits 1 | `test_documents_missing_blob_names_affected_document` | `AssertionError` |
| `documents` with corrupt blob names filename, hash, status on stderr and exits 1 | `test_documents_corrupt_blob_names_affected_document` | `AssertionError` |
| `documents` with unreadable blob names filename, hash, and masks OS errors | `test_documents_unreadable_blob_names_affected_document_safely` | `AssertionError` |
| `documents` with >5 damaged documents caps the stderr list at 5 with continuation | `test_documents_multiple_damaged_blobs_caps_at_five_with_continuation` | `AssertionError` |
| `upload` on damaged document names document filename, hash, status on stderr | `test_upload_damaged_document_names_document_on_stderr` | `AssertionError` |
| `recover-upload` on damaged document names document filename, hash, status | `test_recover_upload_damaged_document_names_document_on_stderr` | `AssertionError` |
| `reconcile` on damaged document names document filename, hash, status | `test_reconcile_damaged_document_names_document_on_stderr` | `AssertionError` |

---

## 4. Implementation Steps

1. **Test Preparation (RED)**:
   - Create new test file `tests/app/test_cli_empty_scan_and_integrity_names.py` covering all 9 criteria.
   - Record snapshot with `scripts/test_evidence.py snapshot`.
   - Run recorder with `--phase red` specifying all expected failing test IDs; verify `AssertionError` causes.
2. **Implementation (GREEN)**:
   - In `src/belegdock/cli.py`:
     - Update `document_status()` to return `(status, filename, integrity, True)` so single-document commands have the filename and integrity issue.
     - Add `format_damaged_documents_guidance(damaged: list[dict[str, Any]]) -> str` for listing up to 5 damaged documents.
     - In `main()`:
       - For `scan`: if `len(result) == 0`: print `f"Keine PDF- oder XML-Anhänge im Gmail-Label '{args.label}' gefunden."` to `sys.stderr`.
       - For `documents`: if any document has `localIntegrity != "ok"`, format and print damaged documents followed by restore guidance.
       - For `upload`, `recover-upload`, `reconcile`: if `status == LOCAL_INTEGRITY_FAILED`, format single-document integrity failure message with filename and hash.
3. **Verification (GREEN)**:
   - Run recorder with `--phase green` to verify all tests pass.
   - Run full suite: `uv run pytest tests/app -q` (279 passed).
   - Run `uv run ruff check .` and `uv run mypy src`.
   - Run `uv run scripts/replay_red.py --verify`.
4. **Documentation**:
   - Update `README.md` (`Auswählen und übertragen` section).
   - Update `docs/arc42.md` (§8 and §11).
