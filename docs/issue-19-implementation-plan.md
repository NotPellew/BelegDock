# Implementation Plan — Issue #19: Add a doctor command for credential presence and an opt-in connection check

## 0. Current Baseline

- Branch: `feature/issue-19-doctor-command` tracking `origin/main` (`f07be5e3d5f5317da2f0ab6221c669a0041ba37c`).
- Passing baseline: **286 tests passed** (`uv run pytest tests/app -q`).
- Replay verification: **44 frozen RED groups verified** (`uv run python scripts/replay_red.py --repo . --verify`).
- Evidence suite: **14 tests passed** (`uv run python -m unittest discover -s tests/evidence -v`).
- Code quality: Clean `uv run ruff check .` and `uv run mypy src`.

---

## 1. Problem and Desired Outcome

A saved Lexware API key is not validated at login, and there is no lightweight way to confirm that stored credentials are present and usable without running a full `refresh` inventory (which makes many paginated GET requests). Operators cannot quickly determine whether their accounts are still connected and may misattribute credential problems to network or label issues.

### Desired Outcome
- Operators can run `belegdock doctor` (offline by default) to verify:
  1. The native OS credential store is available (no plaintext fallback).
  2. Both required credentials (`gmail` and `lexware`) are present.
- Operators can pass `--online` to execute a single lightweight identity probe per service:
  1. Gmail: fetch profile via `users().getProfile(userId="me")`.
  2. Lexware: fetch profile via `GET https://api.lexware.io/v1/profile`.
- Output never contains secret tokens or credentials.
- Clear distinction between "store unavailable", "secret missing", and "service rejected credential".
- Supports `--json` for machine readability.
- Exits with 0 when all performed checks succeed, 1 when any check fails.

---

## 2. Confirmed Design Decisions

1. **CLI Surface & Options**:
   - Subcommand: `belegdock doctor`
   - Flags:
     - `--online`: Opt-in to live identity probes. Default is offline (zero network requests).
     - `--json`: Output structured JSON instead of human-readable text.
     - Inherits standard `-v` / `--verbose` and `--data-dir`.

2. **Offline Checks (Default)**:
   - Check credential store availability via `accounts.native_backend()`. If it raises, report store unavailable with failure status.
   - Check presence of `"gmail"` and `"lexware"` in the credential store (e.g., checking if non-empty string is stored) without leaking the secret value.
   - Does not perform any network calls.

3. **Online Identity Probes (`--online`)**:
   - Explicitly opt-in only.
   - At most 1 identity request per configured service:
     - Gmail: probe identity via user profile (`emailAddress`).
     - Lexware: probe identity via profile (`organizationId`).
   - If a service credential is missing, skip the online probe for that service and report missing credential.
   - Distinguishes authentication rejection (HTTP 401/403 or OAuth invalid grant) from connection errors.
   - Non-mutating: no file uploads, no voucher paging, no email downloads.

4. **Credential & Secret Redaction**:
   - Never print or serialize secret tokens, OAuth refresh tokens, or API keys in human text or JSON.
   - Tests assert that mock token values never appear in stdout or stderr.

5. **Exit Codes**:
   - Exit code `0`: All performed checks (store, credentials, and online probes if requested) passed.
   - Exit code `1`: One or more checks failed (store unavailable, secret missing, or probe rejected/failed).
   - Exit code `2`: CLI argument parsing error.

6. **Output Formatting**:
   - Human output (German, consistent with existing BelegDock commands):
     ```text
     BelegDock-Diagnose:
       Anmeldedatenspeicher: Verfügbar
       Gmail-Anmeldedaten: Gespeichert
       Lexware-Anmeldedaten: Gespeichert
       [wenn --online]:
       Gmail-Verbindung: Erfolgreich (verbunden als ...)
       Lexware-Verbindung: Erfolgreich (Organisation: ...)
     ```
   - JSON output (`--json`):
     ```json
     {
       "ok": true,
       "store": {"available": true, "error": null},
       "credentials": {
         "gmail": {"present": true},
         "lexware": {"present": true}
       },
       "online": {
         "gmail": {"status": "ok", "account": "..."},
         "lexware": {"status": "ok", "organizationId": "..."}
       }
     }
     ```

---

## 3. Acceptance Criteria to Test Mapping

Test file to create: `tests/app/test_doctor.py`

| # | Acceptance Criterion | Test Name | Expected Failure (RED) |
| :- | :--- | :--- | :--- |
| 1 | Offline doctor makes zero network calls and reports store & secrets ok when present | `test_doctor_offline_all_present` | `AssertionError` |
| 2 | Offline doctor reports error and exit code 1 when credential store is unavailable | `test_doctor_offline_store_unavailable` | `AssertionError` |
| 3 | Offline doctor reports missing secrets and exit code 1 when credentials missing | `test_doctor_offline_secrets_missing` | `AssertionError` |
| 4 | `doctor --online` performs single identity probe per service and reports success | `test_doctor_online_probes_success` | `AssertionError` |
| 5 | `doctor --online` reports credential rejection on HTTP 401/403 without echoing secret | `test_doctor_online_credential_rejected` | `AssertionError` |
| 6 | Stored secret material is never echoed in human or JSON output | `test_doctor_never_exposes_stored_secrets` | `AssertionError` |
| 7 | `doctor --json` returns structured JSON and correct exit codes | `test_doctor_json_output_and_exit_codes` | `AssertionError` |

---

## 4. Implementation Steps

1. **Test Suite Creation (RED Phase)**:
   - Create `tests/app/test_doctor.py` covering criteria 1 through 7.
   - Verify that tests fail cleanly with `AssertionError` (RED).
   - Commit: `git commit -m "test: add tests for doctor command (#19)"`.
2. **Implementation in `src/belegdock/` (GREEN Phase)**:
   - In `src/belegdock/accounts.py`: add helper `has_secret(name: str) -> bool` or `check_credential_store() -> tuple[bool, str | None]`.
   - In `src/belegdock/integrations.py`: ensure lightweight profile probes for Lexware and Gmail exist (e.g. `LexwareAdapter.probe_profile()`).
   - In `src/belegdock/cli.py`: add `doctor` parser subcommand with `--online` and `--json`, implement `run_doctor()`, and handle formatting and exit codes.
   - Verify `uv run pytest tests/app/test_doctor.py -q`.
   - Verify full test suite: `uv run pytest tests/app -q`, `uv run ruff check .`, `uv run mypy src`, `uv run python -m unittest discover -s tests/evidence -v`, `uv run python scripts/replay_red.py --repo . --verify`.
   - Commit: `git commit -m "feat: implement doctor command for credential and connection diagnostics (#19)"`.
3. **Documentation Updates**:
   - Update `README.md` (add `belegdock doctor` to command reference / diagnostics).
   - Update `docs/arc42.md` (§6 Runtime view, §8 Crosscutting concepts).
