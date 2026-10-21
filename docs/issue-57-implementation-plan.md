# Implementation Plan — Issue #57: Automate GitHub Releases for Windows installer and package distributions

## 0. Current Baseline

- Branch: `feature/issue-57-releases` from `origin/main` (`f07be5e`).
- Passing baseline: 286 tests passed (`uv run pytest tests/app -q`).
- Replay verification: 44 frozen RED groups verified (`scripts/replay_red.py --verify`).
- Project version is `0.1.0.dev0` in `pyproject.toml` and `src/belegdock/__init__.py`; it is not bumped by this issue.

## 1. Problem and Desired Outcome

The Windows installer and package artifacts exist only as 90-day CI artifacts of `.github/workflows/windows-installer.yml`. Testers need a permanent download location. A new release workflow builds the installer, wheel and sdist from a release tag, verifies them with the existing artifact and smoke-install checks, and publishes them as GitHub Release assets with `artifact.json` and `SHA256SUMS.txt`.

## 2. Confirmed Design Decisions

1. Trigger: push of a tag matching `v*`, plus `workflow_dispatch` with a required `tag` input naming an existing tag; the build checks out that tag.
2. Fail closed: the tag without the leading `v` must equal the project version from `pyproject.toml`; a mismatch aborts before publication.
3. Prerelease: a PEP 440 pre-release or dev release (e.g. `0.1.0a1`, `0.1.0rc1`, `0.1.0.dev0`) is published as a GitHub prerelease, otherwise as a normal release. Releases are published, not drafts.
4. Assets: Windows setup exe, wheel, sdist, `artifact.json`, `SHA256SUMS.txt` in sha256sum format (`<hex>  <filename>` for every other asset).
5. Publication runs in a separate job that `needs` the build job and only after `build`, `check-artifact` and `smoke-install` pass. Only that job gets `contents: write` via `GITHUB_TOKEN`; other jobs keep `contents: read`. Publication uses `gh release create`; no third-party release actions. Actions stay pinned as in the existing workflows.
6. Out of scope: signing, PyPI, auto-update.

## 3. Acceptance Criteria to Test Mapping

Test file: `tests/app/test_release.py` (new; no existing test file changes).

| # | Criterion | Test |
| :- | :--- | :--- |
| 1 | Tag parsing strips `v`, rejects missing/empty prefix | `test_version_from_tag_*` |
| 2 | Tag/version mismatch fails closed | `test_validate_release_tag_rejects_mismatched_project_version`, `test_check_release_tag_subcommand_fails_closed_on_mismatch` |
| 3 | PEP 440 pre/dev versions are prereleases, finals are not | `test_is_prerelease_*` |
| 4 | `SHA256SUMS.txt` uses sha256sum format, sorted, excludes itself | `test_sha256sums_content_*`, `test_write_checksums_subcommand_writes_sha256sums_file` |
| 5 | `check-release-tag` subcommand reports version and prerelease flag | `test_check_release_tag_subcommand_reports_version_and_prerelease` |
| 6 | Workflow triggers, permissions, job dependency, pinned actions, `gh release create`, reused build checks | `test_release_workflow_*` |

## 4. Implementation Steps

1. Add stubs for the release helpers and subcommands in `packaging/build_windows.py`, create the tests, observe NotImplementedError/AssertionError failures (RED), commit plan and tests.
2. Implement pure helpers `version_from_tag`, `validate_release_tag`, `is_prerelease`, `sha256sums_content`, `write_sha256sums` and the `check-release-tag` / `write-checksums` subcommands in `packaging/build_windows.py`.
3. Add `.github/workflows/release.yml` with a Windows build job (checkout of the tag, `uv build`, Inno Setup installer build, `check-artifact`, `smoke-install`, artifact upload) and an Ubuntu publish job (`needs: build`, `contents: write`, checksum generation, `gh release create` with `--prerelease` when flagged).
4. Update the Windows-Installation section in `README.md`, `packaging/README-Windows.txt`, and the deployment view in `docs/arc42.md`.
5. Verify: `uv run pytest tests/app -q`, `uv run ruff check .`, `uv run mypy src`, `uv run python scripts/replay_red.py --verify`, workflow YAML parse, and a mutation check on the tag/version guard.

Recovery: if publishing fails after `gh release create` started, delete the partial release with `gh release delete <tag>` and re-run the workflow for the same tag.
