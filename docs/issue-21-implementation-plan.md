# Implementation Plan — Issue #21: Add an offline status command that summarizes local transfer state

## 0. Current Baseline

- Clean branch `codex/issue-21-offline-status` tracking `origin/main` (`8d7f0f0`).
- Passing baseline: **251 tests passed**.
- Replay verification: **44 frozen RED groups verified**.

---

## 1. Problem and Desired Outcome

`belegdock documents` is the only offline view of local state. It prints a raw JSON array of every document keyed by 64-character hash and omits:
- The effective data directory in use.
- Counts grouped by transfer status (`staged`, `uploading`, `uncertain`, `uploaded`, `rejected`).
- Health, organization, and timestamp of the cached Lexware remote inventory.
- Actionable next steps for non-terminal documents.

`belegdock status` provides a read-only, human-readable summary by default and `--json` for automation. It performs zero network requests and does not modify state.

---

## 2. Confirmed Design Decisions

1. **Bare `belegdock` invocation**: Unchanged. Bare `belegdock` continues to print help and quick-start instructions.
2. **Uninitialized data directory**: When `--data-dir` points to a non-existent or empty directory without `state.sqlite3`, `belegdock status` exits 0, reporting 0 documents and uninitialized state without creating files on disk.
3. **Corrupt state**: Truncated/corrupt `state.sqlite3` raises `LocalIntegrityError` and exits 1 with standard restore guidance on stderr without a traceback.
4. **Damaged blob files**: If SQLite is healthy but staged blob files are missing or damaged, `status` reports the damaged document count in the summary with restore guidance and exits 0 so transfer state remains inspectable.
5. **Capped actionable commands**: For non-terminal documents (`uncertain`, `uploading`, `staged`), concrete CLI commands with hashes are displayed for up to 5 documents per status category, followed by a summary line (e.g. `... und N weitere vorbereitete Dokumente`) if more exist.

---

## 3. Acceptance Criteria to Test Mapping

| Acceptance Criterion | Test Name in `tests/app/test_cli_status.py` | Expected Failure (RED) |
| :--- | :--- | :--- |
| Uninitialized / fresh data directory exits 0, reports 0 documents, does not create files on disk | `test_status_uninitialized_directory_reports_empty_and_does_not_create_files` | `AssertionError` |
| Healthy state outputs human-readable summary with counts by status | `test_status_human_readable_output_with_various_document_states` | `AssertionError` |
| Recommended next commands displayed for `uncertain`, `uploading`, and `staged` | `test_status_recommends_next_commands_for_actionable_documents` | `AssertionError` |
| Actionable commands capped at 5 per category with continuation message | `test_status_caps_actionable_commands_at_five_per_status` | `AssertionError` |
| `--json` outputs structured JSON matching the summary schema | `test_status_json_output_contract` | `AssertionError` |
| Damaged blobs reported with warning count and restore advice while exiting 0 | `test_status_reports_damaged_blobs_and_exits_zero` | `AssertionError` |
| Corrupt SQLite database exits 1 with restore guidance on stderr | `test_status_corrupt_database_exits_one_with_restore_guidance` | `AssertionError` |
| Status command performs zero network requests | `test_status_makes_no_network_requests` | `AssertionError` |

---

## 4. Implementation Steps

1. **Tests**: Create new test file `tests/app/test_cli_status.py` covering all 8 criteria.
2. **RED Evidence**: Record snapshot with `scripts/test_evidence.py` and run against existing code to observe intended RED failures.
3. **Core Store Query**: Add `Store.status_summary()` in `src/belegdock/workflow.py`:
   - Read-only aggregation of `documents` grouped by `status`.
   - Inspection of `remote_state` table for `refresh_status`, `refreshed_at`, and `organization_id`.
   - Count of blob integrity issues.
   - List of non-terminal documents with hashes and filenames.
4. **CLI Integration**: Update `src/belegdock/cli.py`:
   - Add `status` parser with `--json` flag and German help.
   - Add `format_status_human` for localized output.
   - Handle uninitialized data directory check before `Store` instantiation to prevent directory creation.
   - Connect dispatch to `Store.status_summary()`.
5. **GREEN Evidence**: Run recorder to verify all tests pass.
6. **Documentation**: Update `README.md` and `docs/arc42.md`.
