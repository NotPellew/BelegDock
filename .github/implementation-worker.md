# Implementation worker

## Trigger and workflow

The GitHub-hosted `implementation-worker` starts when a human with write or
admin access adds `implementation:approved` to an open issue that still has
`triage:ready`. The scout's label alone never starts implementation. Set the
repository Actions variable `IMPLEMENTATION_WORKER_ENABLED` to `true` to enable
the trigger; set it to `false` to disable future runs. Remove the approval label
to stop a run before coding or publication, or cancel an active run from the
Actions page.

The worker uses the existing `OPENCODE_API_KEY` secret and the configured free
`opencode/space-bunny-free` model. It prepares new application tests, freezes a
test-only checkpoint, requires assertion-based RED evidence, implements only
under `src/`, `docs/`, or `README.md`, then runs the repository's Linux checks
and a separate read-only review session. The publisher rechecks that the issue
is open and retains both labels, then applies only the two validated commits
and opens a draft PR. The workflow never merges and does not modify issue labels
or comments.

## Publisher setup and permissions

The model jobs receive no GitHub write token. A preflight job checks that the
publisher App is configured before spending model calls. The publisher uses a
short-lived, repository-scoped GitHub App token to push a branch and open a
draft PR. Create an App with repository permissions `Contents: read and write` and
`Pull requests: read and write`, no event subscriptions, and install it only on
BelegDock. Put its App ID in the `IMPLEMENTATION_APP_ID` Actions variable and
its private key in the `IMPLEMENTATION_APP_PRIVATE_KEY` Actions secret. The
repo's default Actions token remains read-only and cannot create PRs.

Create the `implementation:approved` label before enabling the workflow. To
retry a failed or skipped run, remove and reapply the label after fixing the
cause. Evidence and patch artifacts are retained for 90 days.

## Limits

Each run uses a disposable GitHub-hosted Ubuntu runner. The OpenCode API key is
present only during OpenCode steps; the GitHub App key and token are present
only in preflight/publisher jobs. OpenCode receives the approved issue body and
repository code. The workflow rejects common credential formats in the issue
title/body and refuses checkouts containing symlinks or `.env` files. Keep
private document content and credentials out of issues and source files.

The pilot stops if implementation needs to edit existing tests, scripts, CI,
packaging, security configuration, or agent instructions. A review result other
than PASS stops publication and leaves evidence on the Actions run. The review
uses Space Bunny in a fresh session, not an independent model. Ubuntu checks
run before PR creation; the existing Windows CI remains responsible for
Windows verification on the draft PR.
