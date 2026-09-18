# BelegDock

A local CLI for explicitly selecting Gmail attachments and uploading them to
Lexware Office without changing the mailbox.

## Status

Early feasibility build, not a production release. Offline tests cover selection,
staging, duplicates and uncertain uploads. Live Gmail-to-Lexware tests accepted
plain PDF, ZUGFeRD PDF and standalone XML without changing labels or original
messages. Local repeat-upload prevention passed for each format; a server duplicate
check also passed for the plain PDF. A malformed XML was rejected (406); its
corrected copy was accepted (202). Acceptance does not establish invoice validity
or completed bookkeeping. The same live flow passed on native Windows through the
built package, using Windows Credential Manager for both accounts.
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
belegdock scan --label "Rechnungen"
belegdock stage --label "Rechnungen" --select "MESSAGE_ID:PART_ID"
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
After upgrading an existing state directory, run `documents` once before starting
concurrent BelegDock commands. The local schema upgrade may refuse a concurrent
first start and makes no remote request.

A confirmed uploaded hash is not resent. A documented Lexware rejection (HTTP
400 or 406) is recorded as `rejected`; correct the document and stage its new
bytes. `uploading` and `uncertain` block another upload.

If a process ended during an upload, run `belegdock recover-upload SHA256_HASH`.
It changes only a local `uploading` record whose per-document operating-system
lock is no longer held to `uncertain`; it does not send a request or allow a retry.
Inspect Lexware first. When you have the matching document, run:

```sh
belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID
```

This downloads the remote file and voucher, requires the voucher to reference
the file, and records the IDs only when the downloaded bytes match the staged
hash. A failed reconciliation leaves the document `uncertain`. Do not reset the
state or delete staging to force a retry; retry after an uncertain upload remains
deferred because this narrow flow cannot prove remote absence.

For the user-run Windows package check, copy the current
`dist/belegdock-0.1.0.dev0-py3-none-any.whl` to Windows, then use PowerShell:

```powershell
$wheel = "$env:USERPROFILE\Downloads\belegdock-0.1.0.dev0-py3-none-any.whl"
$environment = "$env:LOCALAPPDATA\BelegDock-test-env"
$data = "$env:LOCALAPPDATA\BelegDock-test-data"
py -3.12 -m venv $environment
& "$environment\Scripts\python.exe" -m pip install $wheel
& "$environment\Scripts\python.exe" -m belegdock --help
& "$environment\Scripts\belegdock.exe" --data-dir $data documents
```

Then follow the connection, selection, and recovery instructions above for an
account test. Do not transfer credentials or local state through Git. The package
check above does not itself test Gmail or Lexware connectivity; a separate user-run
Windows test of the installed package passed with Windows Credential Manager, live
Gmail scan/staging, and Lexware upload and rejection handling.

## Development

- [AGENTS.md](AGENTS.md): workflow, immutable tests, development commands and isolation.
- [Architecture](docs/arc42.md): scope, decisions, limits and remaining work.
- [Feature form](https://github.com/NotPellew/BelegDock/issues/new?template=feature.yml):
  refine work in an issue; keep delivery evidence in its PR.

Public Gmail onboarding, scheduling, GUI and document archiving remain deferred.
An open-source license must be selected before public distribution.
