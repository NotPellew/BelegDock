# BelegDock architecture

An early CLI and Linux developer boundary are implemented. Offline verification
covers the transfer workflow. Live Gmail PDF retrieval/staging and mailbox
preservation passed; Lexware feasibility and public release remain separate gates. See README for current user commands.

## 1. Introduction and goals

Help users select document attachments from Gmail and transfer them to Lexware
Office locally, with control over what is uploaded. Priorities are mailbox
preservation, reliable recovery, clear results, and a small maintainable package.

## 2. Constraints

- Windows and Linux from the start; exact supported versions remain to be set.
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

Defer GUI, AI, OCR, invoice-link crawling, multiple accounts/providers, plugins,
full document management, and legal archive/compliance claims.

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

These are module responsibilities, not separate services or a plugin system.

## 6. Runtime view

1. Discover attachment candidates in the selected label without changing mail.
2. Stage selected bytes durably and compute their SHA-256 hashes.
3. Record document identity and every source occurrence.
4. Upload only explicitly selected documents and retain returned identifiers.
5. Distinguish confirmed success, failure, and an uncertain remote outcome.

The upload spike must establish recovery after an ambiguous result before
automatic retries are introduced. A local transaction cannot include an HTTP
upload or ordinary file write; recovery across these boundaries needs tests.

## 7. Deployment view

Start with an installable Python package. Standalone executables may follow.
Verify installation and the built CLI on Windows and Linux. User data, credentials,
and host-specific development permissions are separate from repository contents.
The package targets Python 3.12+; CI checks Python 3.12/3.14 on Ubuntu and Windows.

Developer isolation currently requires Linux and Bubblewrap; native Windows
fails explicitly. This limitation does not change the application's platform
targets. System runtimes and the checkout are exposed; the normal home directory
and host sockets are not. The session gets a temporary home and /tmp.

## 8. Crosscutting concepts

- SQLite holds processing state; ordinary files hold original attachment bytes.
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
| Python for the full proof | Small CLI experiments; no final GUI commitment | Complete workflow proven and a concrete limitation found |
| One package/process | Simple operation and testing | A demonstrated need for separate deployment |
| SQLite state plus files | Local transactions without a server; files remain accessible | Shared concurrent access or recovery evidence warrants change |
| Hash-based deduplication | Deterministic; changed bytes remain distinct | Proven need for invoice-level matching |
| Staging before retention | Proves reliable transfer before archive features | Upload/recovery works and retention policy is defined |
| OS credential store | Keeps secrets out of ordinary config | A supported environment needs an explicitly agreed alternative |
| GitHub issues and PRs | One feature specification and linked delivery evidence | Hosting requirements change |
| Protected tests and RED/GREEN records | Prevent silent test changes; requires host enforcement and CI | Verification exposes a gap |
| Bubblewrap for the initial Linux boundary | Small launcher using OS mounts; no new service | Windows implementation or runtime compatibility requires another backend |

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
  Native Windows isolation and persistent CLI authentication remain unverified.
  Desktop tasks are outside that boundary. Symlink-based checkout environments
  and linked worktrees are unsupported; avoid concurrent host edits.
- The initial Gmail adapter refuses malformed parts, including empty part IDs.
  Real account/provider edge cases remain to be established.
- Interrupted uploads remain uploading/uncertain and cannot be resent. Manual
  investigation is supported operationally; a reconciliation command is deferred.
  Windows flushes file bytes, while POSIX also flushes the containing directory.
  Power-loss durability and backup restoration need separate validation.
- Live Gmail PDF reading/staging and repeated-run deduplication passed with two
  synthetic messages. Labels and original message bytes remained unchanged.
  Attachment IDs varied between reads; use message/part IDs for occurrences.
  Prove live XML, Lexware upload/recovery and the combined workflow before
  investing in public Gmail onboarding.
- Before public release, establish Gmail distribution requirements and Lexware
  API/key usage terms for this application; select an open-source license.
- Define exact supported OS versions, cleanup policy,
  and backup/restore behavior before making related user-facing promises.
- Retain the original Project Guide temporarily. After checking migration and
  preserving its original content in Git history, delete it from the working
  tree so agents do not treat it as a competing specification.

## 12. Glossary

- **Candidate:** a PDF/XML attachment, not a verified invoice.
- **Occurrence:** one source-message attachment referencing a document.
- **Staging:** durable working storage for pending or uncertain transfers.
- **Retention:** keeping original attachment bytes after transfer; not a backup.
- **RED/GREEN:** the same established tests show missing behavior, then success.
