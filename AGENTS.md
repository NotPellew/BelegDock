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

No verification script, CI workflow, or enforced test protection exists yet.
These are accepted requirements to implement and validate, not current guarantees.

- During implementation, tests, fixtures, snapshots, helpers, verification
  configuration/script, and the verification dependency lockfile are read-only.
  Enforcement must be outside the implementing agent's ability to change.
- A small verifier records issue, source/test revisions, protected-input hashes,
  command, expected test identifiers, environment, timestamp/order, and results.
- GREEN requires the expected tests to run and pass with the recorded inputs;
  missing/skipped tests or unapproved input changes cannot satisfy the gate.
- CI replays the intended failures against the pre-implementation code and checks
  the implementation plus the full suite on Windows and Linux. RED replay
  supplements the original execution record; it does not prove chronology alone.
- Keep detailed output in execution/CI artifacts and concise evidence in the PR.
  A trusted runner must produce evidence; do not accept self-authored results as
  proof. Keep artifact collection outside application code's control.
- Verify that unauthorized edits are blocked and altered/missing/skipped tests
  are rejected before claiming the protection works on a development host.

The package environment is not bootstrapped; no build, lint, or test command is
currently available. The proposed toolset is uv, pytest, Ruff, and one type checker.
Document exact working commands here when that setup is implemented.

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
