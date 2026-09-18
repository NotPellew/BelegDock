# BelegDock

A local CLI for explicitly selecting Gmail attachments and uploading them to
Lexware Office without changing the mailbox.

## Status

Early feasibility build, not a production release. Offline tests cover selection,
staging, duplicates and uncertain uploads. A live Gmail test staged two synthetic
PDFs without changing labels or original messages. One selected PDF reached
Lexware; local repeat-upload and server duplicate checks passed. XML has offline
coverage; its live upload remains unverified.
Python 3.12+; Windows and Linux application checks run in CI. The separate protected
developer launcher currently supports Linux only.

## Install and connect

From this checkout, install with `uv tool install .`, then run `belegdock --help`.
Keep account setup files and document data outside the repository.

1. Create a Google Cloud test project, enable Gmail API, and configure OAuth as
   External / Testing with your Gmail account listed as a test user. Create a
   Desktop app client and download its JSON outside this checkout.
2. Run `belegdock login-gmail --client /path/to/client.json` and approve the
   browser request. The only requested Gmail scope is `gmail.readonly`.
3. Create a [Lexware trial account](https://app.lexware.de/signup/app/trial) and
   generate a key in its [Public API settings](https://app.lexware.de/addons/public-api).
   Run `belegdock login-lexware` and enter it at the hidden prompt. Saving a key
   does not verify that Lexware accepts it.

Credentials use Windows Credential Manager or Linux Secret Service. An unavailable
store is an error; there is no plaintext fallback. Google OAuth client JSON is
setup material; refresh/access tokens are stored only in the OS credential store.
See [Google's setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python)
and [Lexware's API guide](https://developers.lexware.io/cookbooks/public-api/).

## Select and transfer

Use a dedicated label containing synthetic documents for the first experiment.
Commands produce JSON; copy a candidate ID from `scan`, then a hash from `stage`:

```sh
belegdock scan --label "Rechnung"
belegdock stage --label "Rechnung" --select "MESSAGE_ID:PART_ID"
belegdock documents
belegdock upload SHA256_HASH
```

Repeat `--select` for more attachments. Scanning does not upload; Gmail message responses may include inline attachment
bytes, but only explicitly selected attachments are staged. PDF/XML filenames identify candidates, not
verified invoices. The conservative size limit is 5,000,000 bytes per attachment.
Duplicate bytes share a blob while each source occurrence is retained.

Data defaults to the OS application-data directory (`BelegDock`), with
`state.sqlite3` and `blobs/`. Override it before the command, for example
`belegdock --data-dir /path/to/test-data documents`. Keep the entire directory for
recovery; back it up while no command is running. No files are automatically deleted.

A confirmed uploaded hash is not resent. `uploading` or `uncertain` means the
remote outcome needs manual investigation in Lexware; the CLI blocks another
attempt. A reconciliation command is not implemented yet. Do not reset the state
or delete staging to force a retry.

## Development

- [AGENTS.md](AGENTS.md): workflow, immutable tests, development commands and isolation.
- [Architecture](docs/arc42.md): scope, decisions, limits and remaining work.
- [Feature form](https://github.com/NotPellew/BelegDock/issues/new?template=feature.yml):
  refine work in an issue; keep delivery evidence in its PR.

Public Gmail onboarding, scheduling, GUI and document archiving remain deferred.
An open-source license must be selected before public distribution.
