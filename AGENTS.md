# Working on BelegDock

## Scope and sources

- Follow the user's explicit scope and authorization. Preserve unrelated work.
- Read README.md for product status and docs/arc42.md for accepted decisions.
- PROJECT_GUIDE.md is a superseded brief retained temporarily. Do not use it as
  implementation guidance. Delete it after migration is checked and its original
  content is preserved in Git history.
- Keep machine-specific paths, launchers, and sandbox configuration outside this
  repository. Windows and Linux must both be verified.
- Inspect current files and Git state before changing them. A read-only request
  never authorizes edits, commits, pushes, or cleanup.
- Commit, push, release, and cleanup require authorization for those actions.
  Before cleanup, check the exact target, clean state, and merged state; do not
  delete branches without explicit permission.

## Feature workflow

The GitHub issue is the feature specification; the linked PR holds implementation
evidence. Do not maintain duplicate feature specifications in docs/.

1. Refine the request: outcome, scope, exclusions, observable acceptance criteria,
   failure behavior, and decisions needed before coding.
2. Map acceptance criteria to tests and establish a passing existing baseline.
3. Write each feature test before its corresponding behavior. Execute it against
   the code missing that behavior and observe the intended failure (RED).
4. Record the test snapshot and evidence before implementation. Use a test-only
   checkpoint commit when committing is authorized.
5. Implement the smallest sufficient change. Run the unchanged tests (GREEN),
   then refactor with tests remaining green.
6. Review the complete relevant diff against the issue, including failure cases,
   usability, security, and unnecessary complexity.
7. For behavioral defects, add a reproducing test before repair. Repeat relevant
   verification. If repairs repeatedly stall, return to refinement.
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
- Codex --help starts inside the boundary without a model call. A real agent
  session, its authentication, and nested sandbox compatibility are not verified.
  The launcher does not constrain other desktop tasks or host processes.

Issue #1 verified 14 Linux tests after observed RED failures, including a review
regression for a protected symlink targeting writable source. Test source remained
unchanged after creation. Native Windows enforcement remains pending.

The full evidence verifier and CI remain pending: record revisions, input hashes,
commands, test identifiers, environment, and results; reject missing/skipped tests
and unapproved input changes; replay RED and run GREEN on both target platforms.
Keep detailed reports outside the protected checkout and concise evidence in PRs.
The package environment is not bootstrapped. uv, pytest, Ruff, and a type checker
remain the proposed application toolset; no product build command exists yet.

## Implementation and documentation

- Keep one package/process, focused modules, and minimal dependencies. Extract
  abstractions from demonstrated needs; do not build a general workflow engine.
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
