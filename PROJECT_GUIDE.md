# Project Guide — Local Mailbox → Archive → Lexware Office

## Goal

Explore a **local-first, open-source tool** that can watch an existing mailbox, identify invoice/document attachments, optionally archive them locally, and transfer selected documents to Lexware Office.

The project should stay deliberately small at first. The purpose of the first phase is to answer the main technical and product questions before choosing a final architecture.

---

## Core questions to answer

### 1. Mail access

Can a local application reliably read an existing mailbox without changing the user's mail?

Things to investigate:

- standard IMAP
- Gmail authentication
- Microsoft 365 authentication
- app passwords vs OAuth
- polling vs IMAP IDLE
- handling multiple folders/accounts
- tracking which messages were already processed

A good first experiment is a small CLI program that connects to one mailbox, finds PDF/XML attachments, and lists or saves them without marking messages as read.

Possible libraries:

- Python: `IMAPClient`
- TypeScript/Node: `ImapFlow`

Do not implement IMAP manually.

---

### 2. Local archive

Decide whether the app should keep:

- only the invoice/document
- the original email as `.eml`
- metadata
- hashes/checksums
- all of the above

Questions:

- Should originals be immutable?
- Should files live in normal folders or be managed entirely through a database?
- Is the archive merely a convenience/backup, or should it support search and history?
- Should Paperless-ngx be supported instead of building a larger archive layer?

The project should avoid claiming to be a legally authoritative or GoBD-compliant archive unless that is explicitly researched and implemented.

---

### 3. Duplicate detection

Possible levels:

- email identity
- file hash
- invoice metadata such as supplier + invoice number + amount

Questions:

- What should count as a duplicate?
- Should duplicates be silently ignored or shown for review?
- How should forwarded/renamed copies of the same invoice behave?

Start simple and deterministic.

---

### 4. Document selection

Not every PDF attachment is an invoice.

Possible approaches:

- folder-based rules
- sender allowlists
- filename/subject rules
- XRechnung/ZUGFeRD detection
- later: local classification or AI

Avoid duplicating invoice recognition that Lexware already provides unless there is a specific reason.

---

### 5. Lexware integration

Research and prototype:

- Public API authentication
- document upload
- what metadata can be supplied
- what state uploaded documents enter
- retry/error behavior
- duplicate-upload behavior
- API usage/licensing rules for an open-source local application

One open question to clarify with Lexware before public release:

> Can users generate their own API key and store it locally in an open-source desktop application, provided the developer never receives the key?

---

## Architecture — intentionally undecided

Several reasonable approaches exist.

### Option A — Python desktop app

Possible stack:

- Python
- IMAPClient
- SQLite
- keyring
- httpx
- PySide6 later

Advantages:

- fast to prototype
- strong mail/document ecosystem

Trade-offs:

- desktop packaging can require work

### Option B — TypeScript desktop app

Possible stack:

- Node/TypeScript
- ImapFlow
- SQLite
- Electron

Advantages:

- mature desktop/web tooling
- strong IMAP library

Trade-offs:

- heavier runtime

### Option C — Tauri / Rust

Advantages:

- small binaries
- strong native/security story

Trade-offs:

- more engineering effort for an initial hobby project

No final language/framework decision is required before the first technical spike.

---

## Suggested first spike

Build the smallest possible program that answers the IMAP question.

It should:

1. connect to one test mailbox;
2. read messages without modifying them;
3. find PDF/XML attachments;
4. save or list them;
5. remember what it has already seen;
6. run twice without reprocessing everything.

Then test:

- a new invoice attachment
- the same attachment forwarded again
- multiple attachments
- malformed or unusual email
- a connection failure

If this proves easy and reliable, move on to Lexware.

---

## Suggested second spike

Take one local PDF/XML file and upload it to a Lexware test account.

Questions to answer:

- What API call is needed?
- What identifier comes back?
- Can a failed upload be retried safely?
- What happens after an ambiguous network failure?
- Can the app determine whether a document was already uploaded?

---

## Product questions still open

Before deciding what the final application should be, investigate whether users care most about:

- existing-inbox scanning
- historical invoice import
- more than 20 senders
- local archiving
- duplicate detection
- invoice links in emails
- multiple mailboxes
- Paperless-ngx integration
- privacy/local-only processing
- easier setup than Zapier/Paperless-based solutions

The project does not need to be commercially unique if it is primarily an open-source portfolio project, but it should avoid rebuilding an existing solution without a clear usability or privacy benefit.

---

## Existing solutions worth comparing against

Relevant projects/products include:

- Lexware Office native Belegempfang
- Zapier Gmail → Lexware workflows
- Tailride
- GetMyInvoices
- Paperless-ngx
- `paperless-to-lexoffice`
- the archived `lexoffice-invoice-upload` project

The main question is not whether the workflow exists at all, but whether there is room for a **simple, local, open-source version with better control and UX**.

---

## Security questions

Before distributing binaries, decide how to handle:

- mailbox passwords
- OAuth tokens
- Lexware API keys
- local logs
- backups
- encrypted storage

Likely direction: use the operating system's credential store rather than plain-text config files.

---

## Things not to build yet

Unless the first experiments justify them, defer:

- OCR
- accounting predictions
- AI bookkeeping
- supplier portal automation
- full DMS features
- legal/compliance claims
- multiple accounting systems
- browser extensions
- complex workflow engines

---

## Near-term objective

Answer three questions first:

1. **Can local IMAP access be made reliable and simple enough?**
2. **Can documents be transferred to Lexware safely and repeatably?**
3. **Does local archiving + existing-inbox scanning add enough value to justify a polished app?**

Only after those are answered should the project settle on a final architecture, language, desktop framework, and feature set.
