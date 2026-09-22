# BelegDock architecture

An early CLI and Linux developer boundary are implemented. Offline verification
covers the transfer workflow. Live Gmail retrieval/staging and mailbox preservation
passed on Linux and native Windows. Lexware accepted plain PDF, ZUGFeRD PDF and
corrected standalone XML; local no-resend and plain-PDF server duplicate behavior
passed. A malformed XML was rejected. A live manual reconciliation of an
interrupted upload matched an operator-supplied remote file and voucher to the
staged bytes. Public release remains a separate gate. See README for current user
commands.

## 1. Introduction and goals

Help users select document attachments from Gmail and transfer them to Lexware
Office locally, with control over what is uploaded. Priorities are mailbox
preservation, reliable recovery, clear results, and a small maintainable package.

## 2. Constraints

- Windows and Linux from the start. The Windows pilot installer supports Windows
  10 22H2 (10.0.19045) and Windows 11, x64 only; arm64 and older Windows are
  unsupported. The CLI package itself remains Python 3.12+ on both platforms.
- One Gmail account and one selected label; PDF/XML candidates; explicit upload.
- One-shot CLI commands. No scheduling until restart/retry behavior is proven.
- Python through the complete proof of functionality; reconsider afterward only
  if evidence justifies a different language.
- Tests precede behavior and must be observed failing. Existing test changes
  require explicit prior user approval; details are in [AGENTS.md](../AGENTS.md).

## 3. Context and scope

The user runs BelegDock on their computer. Gmail supplies attachments. Lexware
receives only selected documents. An OS credential store holds credentials.
SQLite and document files live locally, outside the source repository.

The first public release must support other users connecting their own accounts.
Experiments use a test project/account and only the authentication needed to
establish feasibility. Public onboarding/verification work follows the complete
proof and precedes public release. The bounded experiment uses Gmail API with
gmail.readonly and a Desktop OAuth test client.

The desktop UI is a thin local tkinter/ttk view over the existing workflow. It
supports label selection, explicit staging, and one-document upload confirmation;
it does not poll, auto-retry, or reconcile uncertain uploads. AI, OCR, invoice-link
crawling, multiple accounts/providers, plugins, full document management, and
legal archive/compliance claims remain deferred.

## 4. Solution strategy

Use one installable package and process. Separate CLI, processing, persistence,
and integrations through focused modules. Use established mail/API libraries;
do not implement protocols manually. Add dependencies when needed.

## 5. Building block view

| Responsibility | Boundary |
| --- | --- |
| CLI | User choices, clear outcomes, exit status |
| Processing | Candidate selection and workflow decisions |
| Gmail integration | Read mail without changing it |
| Local persistence | Processing state, document bytes, source occurrences |
| Lexware integration | Upload and record/reconcile results |
| Desktop UI | Present local choices and state; delegate workflow decisions |

These are module responsibilities, not separate services or a plugin system.

## 6. Runtime view

1. Discover attachment candidates in the selected label without changing mail.
2. Stage selected bytes durably and compute their SHA-256 hashes.
3. Record document identity and every source occurrence.
4. Refresh the organization-bound remote inventory before upload; verify an
   existing file's current bytes and voucher link before associating it.
5. Upload only explicitly selected documents and retain returned identifiers.
6. Record documented HTTP 400/406 rejections separately from uncertain remote outcomes.
7. Reconcile an uncertain result only through explicit remote file and voucher reads.

The upload spike must establish recovery after an ambiguous result before
automatic retries are introduced. A local transaction cannot include an HTTP
upload or ordinary file write; recovery across these boundaries needs tests.

## 7. Deployment view

Start with an installable Python package; the Windows pilot additionally ships the
frozen distribution described below. Verify installation and the built CLI on
Windows and Linux. User data, credentials, and host-specific development
permissions are separate from repository contents. The package targets Python
3.12+; CI checks Python 3.12/3.14 on Ubuntu and Windows.

The Windows pilot also ships as a frozen PyInstaller onedir bundle inside a
per-user Inno Setup installer (`PrivilegesRequired=lowest`, `x64os`, Windows
10 22H2 or later) built from the built wheel. The installer adds the install
directory to the per-user PATH and creates a Start Menu shortcut; uninstalling
removes both without touching `%LOCALAPPDATA%\BelegDock`. The build runs only on
Windows from a neutral work root (`C:\belegdock-build`), installs the application
dependencies from the frozen `uv.lock` with `uv export` and `--require-hashes`,
and pins `pyinstaller` in `packaging/build_windows.py` so `pyproject.toml` and
`uv.lock` stay untouched. CI retains the setup executable and `artifact.json`
(sha256, size, wheel hash, resolved dependency versions, tool versions, git
revision) as a 90-day workflow artifact; there is no GitHub Release and no code
signing. The real window launch stays a manual native Windows check.

Developer isolation currently requires Linux and Bubblewrap; native Windows
fails explicitly. This limitation does not change the application's platform
targets. System runtimes and the checkout are exposed; the normal home directory
and host sockets are not. The session gets a temporary home and /tmp.

## 8. Crosscutting concepts

- SQLite holds processing state; ordinary files hold original attachment bytes.
- The explicit `refresh` command reads `/v1/profile`, paginated `/v1/voucherlist`
  for all four bookkeeping types and both archive states, then reads voucher
  details and streams file hashes. A complete result atomically replaces the
  organization-bound cache; cached hashes are reused only when file metadata
  is unchanged. GET rate limits retry at most five times and files are bounded
  at 5,000,000 bytes.
- SHA-256 identifies byte-identical documents. Keep separate source occurrences;
  do not claim detection of semantically identical invoices with different bytes.
- Staging survives interruptions until an upload can be resolved. Optional
  retention of original attachments follows reliable staging/upload. No automatic
  deletion policy is agreed. Defer original-email (.eml) retention and search.
- Use the OS credential store and fail explicitly when unavailable. No silent
  plaintext fallback. Keep credentials, message bodies, and document contents out
  of logs and test fixtures.
- Treat filenames/content as untrusted. Define safe paths and size limits before
  accepting external attachments. Never execute attachments.
- The protected developer CLI mounts the checkout read-only at /workspace and
  permits writes only to src/, docs/, and README.md. It drops capabilities and
  prevents nested user namespaces. Refuse checkout symlinks, special files, and
  writable hardlinks so aliases cannot make established tests editable. The
  trusted host applies approved test changes between sessions. Network is off
  unless explicitly enabled; network-enabled sessions can reach host TCP services.

## 9. Architecture decisions

| Decision | Reason and consequence | Revisit trigger |
| --- | --- | --- |
| Python for the full proof | Small CLI and tkinter experiments | Complete workflow proven and a concrete limitation found |
| One package/process | Simple operation and testing | A demonstrated need for separate deployment |
| SQLite state plus files | Local transactions without a server; files remain accessible | Shared concurrent access or recovery evidence warrants change |
| Hash-based deduplication | Deterministic; changed bytes remain distinct | Proven need for invoice-level matching |
| Per-document upload lock | Distinguish a live local upload from a lock-free crash remnant | A portable locking limitation is found |
| Staging before retention | Proves reliable transfer before archive features | Upload/recovery works and retention policy is defined |
| OS credential store | Keeps secrets out of ordinary config | A supported environment needs an explicitly agreed alternative |
| GitHub issues and PRs | One feature specification and linked delivery evidence | Hosting requirements change |
| Protected tests and RED/GREEN records | Prevent silent test changes; requires host enforcement and CI | Verification exposes a gap |
| Bubblewrap for the initial Linux boundary | Small launcher using OS mounts; no new service | Windows implementation or runtime compatibility requires another backend |
| PyInstaller onedir plus per-user Inno Setup for the Windows pilot | Installs without admin or a source checkout; install path stays independent from user data | Runner/toolchain drift or a signing requirement appears |

## 10. Quality requirements

| Scenario | Required observation |
| --- | --- |
| Scan messages | Read/unread state, labels, and message contents remain unchanged |
| Same bytes in another message | One document identity, both source occurrences |
| Interrupt staging/upload | No silent loss or false completion; uncertain outcomes visible |
| Credential store unavailable | Clear failure without plaintext fallback |
| Unsafe filename or oversized input | No path escape; bounded processing and clear rejection |
| Install on either target OS | Built package and agreed CLI behavior pass checks |
| Attempt unapproved test edit | Edit blocked; missing/skipped/altered tests cannot report GREEN |

## 11. Risks and open work

- Package tooling, application CI and a local evidence recorder now exist. Linux
  isolation passed 14 tests and a bounded authenticated Luna execution probe.
  Native Windows developer isolation remains unverified; persistent CLI
  authentication and the live flow passed on native Windows.
  Desktop tasks are outside that boundary. Symlink-based checkout environments
  and linked worktrees are unsupported; avoid concurrent host edits.
- The initial Gmail adapter refuses malformed parts, including empty part IDs.
  Real account/provider edge cases remain to be established.
- HTTP 400/406 responses from the files endpoint are documented local rejections;
  other HTTP errors, transport failures and malformed success responses remain
  uncertain. A rejected hash is never resent; corrected bytes are a new staged
  document. `recover-upload` can move only a lock-free `uploading` record to
  uncertain after a local process has ended. It first verifies staged bytes;
  damaged or unavailable bytes leave the record `uploading` with restore guidance.
  It does not prove a remote outcome or authorize a retry. `reconcile` reads the
  operator-supplied file and voucher, requires the voucher to reference that file,
  and compares downloaded bytes to
  the staged hash before recording IDs. It leaves failures uncertain. A remote
  absence search and retry after uncertainty remain deferred.
  The first start against an older state database must run alone to apply its local
  schema upgrade; a concurrent first start fails before any remote request.
  A missing or empty database in a nonempty data directory is treated as an
  incomplete restore and is not recreated. Local document listing checks bounded
  blob bytes and reports missing, corrupt, or unreadable blobs without changing
  transfer status or remote identifiers. An already uploaded document is not
  reported as successfully reusable when its local blob fails that check.
  Windows flushes file bytes, while POSIX also flushes the containing directory.
  Power-loss durability and backup restoration need separate validation.
- Live Gmail PDF reading/staging and repeated-run deduplication passed with two
  synthetic messages. Labels and original message bytes remained unchanged.
  Attachment IDs varied between reads; use message/part IDs for occurrences.
  The selected PDF reached Lexware (202); repeating locally made no new request,
  and a deliberate server repeat returned identical file/voucher IDs. A provided
  ZUGFeRD PDF containing factur-x.xml was also accepted (202), with no local resend.
  The standalone XML failed local syntax parsing and Lexware rejected it (406).
  Its corrected copy was accepted (202) through the renamed Rechnungen label;
  repeating the local upload made no request. All selected attachments retained
  their original bytes; Gmail remained unchanged. The same flow was repeated on
  native Windows through the built package: the CLI installed and ran, Windows
  Credential Manager supplied both credentials across processes, and Gmail
  scan/staging and Lexware upload/rejection outcomes matched.
  Acceptance does not prove invoice conformance or completed bookkeeping.
  A live manual reconciliation of an interrupted upload passed: the interrupted
  local process left the document uncertain, the operator-supplied remote file and
  voucher were downloaded, the voucher was confirmed to reference the file, the
  bytes matched the staged hash, and the IDs were recorded. A mismatched remote
  file and a repeated reconciliation both failed and left the document uncertain;
  Gmail and the remote records were unchanged.
- Before public release, establish Gmail distribution requirements and Lexware
  API/key usage terms for this application, including whether users may generate
  and store their own key in a local open-source client that never receives it
  (Apache-2.0 is selected).
- The Windows pilot installer is unsigned (SmartScreen warning) and ships no
  custom application icon. PyInstaller may embed build-machine source paths, so the
  build uses the neutral work root `C:\belegdock-build` and the artifact check
  scans for user-profile patterns; that reduces but does not prove the absence of
  embedded paths. The artifact check verifies the Tcl/Tk data directories
  (`_tcl_data`/`_tk_data`), the Tk extension, the certifi CA bundle and the frozen
  modules in both executables; it cannot prove that a Tk window initializes.
  Per-user PATH editing is the most fragile installer step and is
  asserted during the smoke installation, which waits for the asynchronous Inno
  uninstaller before checking removal. ARM64 and Windows versions before 10 22H2
  are unsupported and refused by `ArchitecturesAllowed=x64os`. PyInstaller support
  for the CI Python versions (3.12/3.14) must be rechecked when the pinned version
  or the toolchain changes. Freezing succeeds only on Windows; until a
  `windows-installer` run exists, the spec, the bundle layout and the Inno
  invocation are unverified.
- The cleanup policy and the backup/restore behavior still need a user-facing
  decision; the supported Windows versions are now fixed for the pilot installer.

## 12. Glossary

- **Candidate:** a PDF/XML attachment, not a verified invoice.
- **Occurrence:** one source-message attachment referencing a document.
- **Staging:** durable working storage for pending or uncertain transfers.
- **Retention:** keeping original attachment bytes after transfer; not a backup.
- **RED/GREEN:** the same established tests show missing behavior, then success.
