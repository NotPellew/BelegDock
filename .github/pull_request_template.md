## Feature and result

Issue: #

Describe the user-visible change and any remaining limitations.

## Verification

| Check | Evidence |
| --- | --- |
| Passing baseline | Revision, command, result |
| RED before implementation | `scripts/test_evidence.py run --phase red` snapshot, command, intended failures, local artifact path |
| CI RED replay | `red-replay` `--verify` on the PR (test files match checkpoints). Full execute and `red-<os>-<py>` artifacts are nightly / `workflow_dispatch`, not attached to the PR |
| GREEN | Implementation revision, same tests, result, artifact |
| Protected inputs | Unchanged, or link to prior approval of the exact change |
| Windows / Linux | CI runs, built-package checks, anything not run |

For documentation-only work or a bounded spike, explain which checks apply.
Full logs belong in artifacts; keep this summary short and free of private data.

## Review and documentation

- [ ] Acceptance criteria and the complete diff reviewed.
- [ ] Findings repaired and verified, or explicitly accepted with rationale.
- [ ] README, AGENTS, and arc42 updated where affected; otherwise explain why.
- [ ] No unapproved test changes, unrelated changes, or sensitive data.
