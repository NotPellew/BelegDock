# Implementation plan — Issue #38: guided first-run setup in the desktop app

Spec: GitHub issue #38. Baseline: branch `feature/issue-38-first-run-setup` from `50f0796`.

## Confirmed decisions

- Audience: non-technical Windows testers. Each receives the publisher's Google OAuth
  client JSON out of band (Google project in "Testing" mode, tester listed as test
  user). The JSON is read at connect time only; its path is never stored and only its
  file name is shown.
- Startup runs offline detection (`doctor.detect(online=False)`, no network).
  Store unavailable: German error, no window. Any credential `missing` or
  `read_failed`: setup screen in the same Tk root before the main view. Both
  `present`: main view directly. Setup is mandatory; closing the window exits.
- Existing startup failures keep `DESKTOP_START_FAILED_MESSAGE`.
- CLI `login-gmail`/`login-lexware` and their JSON/state contracts stay compatible.

## Design

- `src/belegdock/setup.py` (widget-free): `detect_state`, `startup_route`,
  `authorize_gmail` (raw exceptions, used by the CLI), `authorize_gmail_guided`
  (stable `SetupError` codes), `save_gmail`, `connect_gmail` (authorize + save, used by
  `cli.connect_gmail`), `validate_lexware_key` (exactly one `probe_profile`),
  `save_lexware_key`, `classify_*` helpers.
- `src/belegdock/desktop_setup.py` (Tk only): `SetupView`, `run_setup`, German text.
  Reuses `_TkWorkerDispatcher`. Workers only authorize/validate; the UI thread saves
  after checking the attempt is still current, so a cancelled attempt can never save.
- `desktop.run_desktop` routes by `startup_route`; `DesktopApplication` accepts an
  optional existing `root`.

## Persisted state and failure boundaries

| Boundary | Persisted state | Allowed guidance |
| --- | --- | --- |
| Gmail: before OAuth starts (no/invalid client file, store unavailable) | none | choose a valid client file / fix store; retry |
| Gmail: during browser flow (denied, timeout, cancel, network) | none | denial: tester must be registered by the publisher and accept read-only access; timeout/cancel: retry |
| Gmail: after token exchange, before save (`getProfile` fails, attempt abandoned) | none (token discarded) | retry; abandoned result silently dropped |
| Gmail: save succeeds | token in OS store | connected as account |
| Lexware: before probe (empty/malformed key, store unavailable) | none | enter key / fix store |
| Lexware: probe rejected (401/403) or network error | none | "Schlüssel abgelehnt" / retry |
| Lexware: after successful probe | key in OS store, Entry cleared | connected |

No setup step uploads, polls, or retries automatically.

## Acceptance criteria to tests

| Criterion | Test file |
| --- | --- |
| Gmail requests only readonly scope; saves only after `getProfile`; CLI keeps raw behaviour | `test_setup_service.py` |
| Gmail failures map to stable codes (client file, denied, timeout, network) with no save | `test_setup_service.py` |
| Lexware: exactly one probe; rejected/network codes; key never in errors; no save in validate | `test_setup_service.py` |
| Detection and routing (store unavailable, missing, read_failed, present) | `test_setup_service.py` |
| Setup view: initial states, connected skippable, file name only, masked entry, German guidance, cancel discards late result, Lexware save only after success, entry cleared, continue only when both connected | `test_desktop_setup.py` |
| `run_desktop` routing: skip setup when present, setup before clients/main view, abandon exits, store error message, no-leak | `test_desktop_startup_routing.py` |
| Packaging covers new dynamic imports | existing `test_windows_packaging.py` |

## Steps

1. Commit plan and new tests (`test: add tests for #38`); observe RED.
2. Implement, run unchanged tests (GREEN), full checks, mutation checks.
3. Native-Tk check with fakes; update README, `packaging/README-Windows.txt`, arc42.
