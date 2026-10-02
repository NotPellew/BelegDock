# Implementation Plan — Issue #24: Add --verbose to surface root-cause errors without changing default output

## 0. Current Baseline

- Branch: `codex/issue-24-verbose-errors` tracking `origin/main` (`64f8dbf`).
- Passing baseline: **279 tests passed** (`pytest tests/app`).
- Replay verification: **44 frozen RED groups verified** (`python scripts/replay_red.py --verify`).
- Code quality: Clean `ruff check .` and `mypy src`.

---

## 1. Problem and Desired Outcome

When any CLI command fails, `main()` in `src/belegdock/cli.py` catches `Exception` and replaces the underlying exception with a generic category message. The operator cannot distinguish between:
- A non-existent Gmail label (`ValueError: Gmail label was not found`)
- A missing account credential (`RuntimeError: Connect the account first using its login command.`)
- An HTTP connection or status failure (`httpx.ConnectError`, `RemoteAuthError`)
- A Lexware rate limit (`RuntimeError: Lexware request rate limited`)
- An unexpected filesystem error (`PermissionError`, `OSError`)

### Desired Outcome
- Operators can pass `-v` / `--verbose` on the command line or set the `BELEGDOCK_VERBOSE` environment variable to display safe root-cause error details (exception type and message) on stderr.
- Default output (when verbose is not enabled) remains strictly unchanged.
- Output never contains secrets, tokens, raw file contents, or sensitive stack traces.
- Stdout is unaffected (valid JSON on success, unchanged on failure).

---

## 2. Confirmed Design Decisions

1. **Activation Mechanism**:
   - Both CLI flag (`-v`, `--verbose`) and environment variable (`BELEGDOCK_VERBOSE`) are supported.
   - Global flag is accepted on the main parser.
   - `BELEGDOCK_VERBOSE` is active if set to `"1"`, `"true"`, or `"yes"` (case-insensitive).
   - If either the flag or the environment variable is active, verbose error output is enabled.

2. **Verbose Output Formatting on Stderr**:
   - Preserves the existing localized user-friendly message as the primary line.
   - Appends a single, safe diagnostic line:
     `Fehlerdetails: <ExceptionClassName>: <exception message>`
   - Example:
     ```
     Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher.
     Fehlerdetails: ValueError: Gmail label was not found
     ```

3. **No Raw Tracebacks**:
   - In accordance with BelegDock's safety and privacy rules, `--verbose` prints a single-line summary (`Fehlerdetails: <Type>: <Message>`), not a full Python traceback.
   - Full tracebacks expose local variables, machine paths, and runtime internals which could inadvertently leak sensitive fragments.

4. **Credential & Secret Redaction**:
   - Any secret loaded from the credential store or present in known sensitive patterns (e.g., Bearer tokens) is guaranteed to be redacted (`***`) if it were ever to appear in an exception string.
   - Tests explicitly verify that stored secret strings are never echoed in verbose output.

5. **Exit Code & Stdout Contract**:
   - Exit codes remain standard (`1` for general failure, `2` for syntax/argument errors).
   - Stdout remains untouched (no diagnostic messages on stdout).

---

## 3. Acceptance Criteria to Test Mapping

Test file to create: `tests/app/test_cli_verbose.py`

| # | Acceptance Criterion | Test Name | Expected Failure (RED) |
| :- | :--- | :--- | :--- |
| 1 | Without `--verbose`, stderr is unchanged on failure (generic message only) | `test_failure_without_verbose_prints_only_standard_message` | `AssertionError` |
| 2 | With `--verbose`, stderr prints standard message PLUS `Fehlerdetails: <Type>: <Msg>` | `test_failure_with_verbose_flag_prints_exception_details` | `AssertionError` |
| 3 | With `BELEGDOCK_VERBOSE=1`, stderr prints exception details without `--verbose` flag | `test_failure_with_verbose_env_var_prints_exception_details` | `AssertionError` |
| 4 | Short flag `-v` activates verbose error output | `test_failure_with_short_v_flag_prints_exception_details` | `AssertionError` |
| 5 | Output never echoes stored secret tokens | `test_verbose_output_never_exposes_stored_secrets` | `AssertionError` |
| 6 | Stdout remains valid JSON or empty on failure; exit code is unchanged | `test_verbose_failure_preserves_exit_code_and_stdout_contract` | `AssertionError` |
| 7 | Verbose details work across representative commands (`scan`, `refresh`, `stage`, `upload`) | `test_verbose_surfaces_root_causes_across_commands` | `AssertionError` |

---

## 4. Implementation Steps

1. **Test Suite Creation (RED Phase)**:
   - Create `tests/app/test_cli_verbose.py` covering the 7 test scenarios.
   - Record snapshot using `scripts/test_evidence.py snapshot`.
   - Run `scripts/test_evidence.py run --phase red` specifying all expected failing tests; confirm `AssertionError`.
2. **Implementation in `src/belegdock/cli.py` (GREEN Phase)**:
   - Add `-v` / `--verbose` to `make_parser()`.
   - Add helper function `is_verbose(args: argparse.Namespace) -> bool`.
   - Add helper function `format_verbose_exception(exc: BaseException) -> str`.
   - In `main()` exception handlers:
     When an exception is caught, print the standard localized message, and if `is_verbose(args)`: print `format_verbose_exception(exc)` to `sys.stderr`.
3. **Verification (GREEN Phase)**:
   - Run `scripts/test_evidence.py run --phase green`.
   - Run `uv run pytest tests/app -q` (all 279+ tests pass).
   - Run `uv run ruff check .` and `uv run mypy src`.
   - Run `uv run python scripts/replay_red.py --verify`.
4. **Documentation**:
   - Update `README.md` (`Auswählen und übertragen` section) describing `-v` / `--verbose` and `BELEGDOCK_VERBOSE`.
   - Update `docs/arc42.md` (§6 Runtime view, §8 Crosscutting concepts).
