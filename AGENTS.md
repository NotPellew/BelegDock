# Working on BelegDock

## Scope and sources

- Follow the user's explicit scope and authorization. Preserve unrelated work.
- Read README.md for product status and docs/arc42.md for accepted decisions.
- Keep machine-specific paths, launchers, and sandbox configuration outside this
  repository. Windows and Linux must both be verified.
- Inspect current files and Git state before changing them. A read-only request
  never authorizes edits, commits, pushes, or cleanup.
- Local commits at repository-defined or implementation checkpoints are
  permitted by default after the checkpoint's required validation. Other
  commits, pushes, releases, and cleanup require authorization for those
  actions. Before cleanup, check the exact target, clean state, and merged
  state; do not delete branches without explicit permission.

## Feature workflow

The GitHub issue is the feature specification; the linked PR holds implementation
evidence. Do not maintain duplicate feature specifications in docs/.

1. Refine the request: outcome, scope, exclusions, observable acceptance criteria,
   failure behavior, and decisions needed before coding.
2. Map acceptance criteria to tests and establish a passing existing baseline.
   For state-dependent recovery or failure guidance, enumerate persisted states
   and failure boundaries (before an operation begins, during local work, and
   after a remote call), then map each to allowed operator guidance.
   For UI or localization work, enumerate every visible entry point, including
   each subcommand's help output and every failure/recovery state, and map each
   item to a test or package smoke check.
3. Write each feature test before its corresponding behavior. Execute it against
   the code missing that behavior and observe the intended failure (RED).
4. Record the test snapshot and evidence before implementation. For every
   changed existing test, create the approved test-only checkpoint before source
   implementation, point replay metadata at that pre-implementation checkpoint,
   and retain the approval reference with the task or PR evidence.
5. Implement the smallest sufficient change. Run the unchanged tests (GREEN),
   then refactor with tests remaining green.
6. Review the complete relevant diff against the issue, including failure cases,
   usability, security, and unnecessary complexity.
   Complete any explicitly requested independent review before claiming the
   issue is done.
7. Treat reviewer findings as hypotheses: reproduce or otherwise verify them
   against current code, tests, or the governing contract before repair. For
   confirmed behavioral defects, add a reproducing test before repair. Repeat
   relevant verification. If repairs repeatedly stall, return to refinement.
8. Update affected documentation and verify the final package on both platforms.
   Report what passed, what was not run, and unresolved limitations.

Ready means the criteria are testable and implementation-blocking decisions are
resolved. Done means the criteria pass, review findings are resolved or explicitly
accepted, documentation matches behavior, and required checks have evidence.

Bounded spikes produce evidence and a decision; they do not require artificial
RED tests. Code retained from a spike must meet the normal feature gates.
Documentation-only changes use document validation rather than behavioral tests.

## Test changes require user approval

- Once a test exists, never modify it without the user's explicit prior approval
  of the proposed change. Present the exact diff and rationale first.
- This includes deletion, renaming, assertions, skips, expected failures,
  snapshots, and fixture/helper/configuration changes that alter verification.
- Permission to implement or repair a feature is not permission to change tests.
- New tests for an authorized feature may be created in the preparation step;
  existing tests remain protected. Freeze the new tests before implementation.
- After an approved change, record a replacement snapshot and reestablish the
  relevant RED/GREEN evidence. One approval does not authorize later edits.
- Missing dependencies, collection/import errors, and unrelated exceptions are
  not valid RED evidence. Inspect already-passing new tests before proceeding.

## Verification design and current limits

The Linux launcher scripts/protected_run.py enforces read-only repository access
except src/, docs/, and an existing README.md. Tests, configuration, scripts, Git
metadata, and agent instructions remain read-only. Missing isolation support and
native Windows fail closed. This desktop task is not retroactively protected.

From a normal host terminal in the checkout:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/protected_run.py -- bash --noprofile --norc
```

Requirements: Linux, Python 3, and Bubblewrap with user namespaces and
--disable-userns support. A surrounding sandbox may prevent nested namespaces;
run the checks from the host terminal. A refused launch never falls back to
unprotected execution. The standard-library suite uses disposable checkouts.

- Inside the session the checkout is /workspace. Only edits to the writable
  areas persist. HOME and /tmp are isolated and discarded on exit; host account
  credentials, CLI profiles, and host sockets are not inherited.
- Networking is off. --network explicitly enables host networking, including
  host TCP services; enable it only for trusted CLI use. Do not connect tools
  that can perform host-side edits outside this boundary.
- Only system-installed runtimes are exposed. Checkout symlinks, special files,
  and writable hardlinks are refused. Symlink-based virtual environments and
  linked Git worktrees are not supported by this first launcher.
- Source and documentation directories are created if absent. Do not store test
  definitions, fixtures, or verification configuration in these writable areas.
- For an approved test change, exit the protected session, apply only the exact
  approved diff from the trusted host, reestablish RED evidence, then relaunch.
  Do not weaken the running session's protection. Avoid concurrent host edits.
- A bounded authenticated Luna probe executed a source write and was denied a
  protected-file write. Codex workspace-write fails inside the boundary because
  nested namespaces are blocked. Use Codex danger-full-access only inside this
  outer Bubblewrap boundary; the outer restrictions remain active. A temporary
  native login may be established inside the session with device authorization.
  This launcher does not constrain other desktop tasks or host processes.

Issue #1 verified 14 Linux tests after observed RED failures, including a review
regression for a protected symlink targeting writable source. Test source remained
unchanged after creation. Native Windows enforcement remains pending.

Development uses uv with an environment outside the checkout. For Linux:

```sh
export UV_PROJECT_ENVIRONMENT=/tmp/belegdock-dev
uv sync --locked
uv run pytest tests/app -q
uv run ruff check .
uv run mypy src
uv run python -m unittest discover -s tests/evidence -v
uv build --wheel
```

On Windows, set UV_PROJECT_ENVIRONMENT to an external directory in PowerShell
using `$env:UV_PROJECT_ENVIRONMENT`. Application CI uses Python 3.12 and 3.14 on
Ubuntu and Windows. The original Bubblewrap suite remains a separate Linux host
check, not a skipped Windows application test. The evidence fake-runner tests
currently require Linux; the real-runner tests use pytest.

`scripts/test_evidence.py` records snapshots and RED/GREEN reports outside the
checkout. Use the same Python interpreter with pytest installed for both phases:

```sh
python scripts/test_evidence.py snapshot --repo . --output /outside/snapshot.json
python scripts/test_evidence.py run --repo . --snapshot /outside/snapshot.json --output /outside/red --phase red --expected-failure 'tests/app/test_feature.py::test_behavior'
python scripts/test_evidence.py run --repo . --snapshot /outside/snapshot.json --output /outside/green --phase green
```

Supply every expected failing ID separately. The recorder rejects changed inputs,
missing/skipped tests, collection errors and unexpected failures. Each run needs a
new output directory. Inspect RED reasons: a matching failure alone does not prove
the right behavior is tested. CI also runs the recorder and retains its snapshot/JUnit/report artifacts.
Reports are execution evidence, not tamper-proof audit records or independent
proof of chronology; user review remains a separate check. Snapshot after approved test
changes and before implementation. Preserve the earlier snapshot and logs.
CI verifies frozen RED checkpoints with scripts/replay_red.py `--verify` on every
push and pull request (Ubuntu and Windows, Python 3.14); the full 126-test replay
executes nightly and on manual `workflow_dispatch` (Ubuntu/Windows × 3.12/3.14).
A group is admitted only for a `tests/app` file with a checkpoint commit whose
current bytes equal the checkpoint bytes; `--verify` enforces revision, byte
identity, and count on every event. Permitted failure markers (`AssertionError` /
`NotImplementedError`) are a human/execute rule via `validate_report`, not a
`--verify` check. A changed replayed test needs a new test-only checkpoint commit
and a `GROUPS` update; `--verify` fails until the reference is updated. Nightly
execution catches toolchain drift (Python/pytest/`uv.lock`) and regenerates
retained evidence.
Before declaring the feature complete, also run a full replay with
`scripts/replay_red.py --output ...`. `--verify` checks checkpoint identity and
test shape only; it does not prove that the archived tests still fail against the
archived pre-fix source. A replay checkpoint that already passes is invalid.
The replay validates historical snapshots, not chronology by itself. Review
regression RED remains in local logs. Preserve checkpoint commits when merging;
if approved tests change, establish replacement RED evidence before updating
replay references. Never weaken a test to keep an old replay passing.

Do not run these commands concurrently with source/configuration edits. The
protected shell can create a disposable virtual environment inside its /tmp;
external host environments are not mounted. Native Windows developer isolation
is still pending. Gmail browser authorization and OS credential storage run from
the ordinary user terminal, outside the credential-free developer boundary.

## Implementation and documentation

- Keep one package/process, focused modules, and minimal dependencies. Extract
  abstractions from demonstrated needs; do not build a general workflow engine.
- Treat temporary desktop UI as replaceable: keep Gmail/Lexware workflow
  operations in widget-free services and confine Tk layout and event handling to
  the desktop view. For UI changes, complement offline tests with a synthetic
  native-Tk check when available, covering label selection and wide/narrow layouts.
- Ordinary tests are offline, deterministic, credential-free, and use synthetic
  fixtures. Live Gmail/Lexware tests require explicit authorization and test data.
- Never log credentials or document contents. Treat external mail and filenames
  as untrusted input. Do not silently fall back to plaintext credential storage.
- Distinguish configuration validation from execution. Do not invoke live or
  paid models to validate configuration unless explicitly requested.
- Keep user instructions in README.md, development rules here, and architecture
  in docs/arc42.md. Keep prose short, concrete, and readable; link instead of
  duplicating. No narrative inline comments, documentation docstrings, or
  commented-out code. CLI help is user interface text.
