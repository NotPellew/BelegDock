# BelegDock

A planned local tool for selecting Gmail attachments and uploading them to
Lexware Office without changing the mailbox.

## Status

The project is in setup and feasibility testing. There is no installable
application yet. Windows and Linux are the initial targets; support is not yet
verified. The first public release should allow other users to connect their
own accounts.

## Intended use

1. Connect one Gmail account using the operating system's credential store.
2. Scan one selected label for PDF/XML attachment candidates.
3. Explicitly select documents for upload to Lexware Office.
4. Inspect the result and resolve any uncertain upload before retrying.

Commands run once; scheduling comes later. A candidate is not necessarily an
invoice. Reliable staging and upload come first, with optional retention of
original attachments afterward. No automatic deletion policy is agreed yet.

Installation, authentication, data locations, and recovery instructions will be
added as those behaviors become available. Do not use real documents as test
fixtures or put credentials in this repository.

## Development

- [AGENTS.md](AGENTS.md): contribution workflow, test protection, and checks.
- [Architecture](docs/arc42.md): scope, decisions, quality requirements, and risks.
- Use the [GitHub feature-request form](https://github.com/NotPellew/BelegDock/issues/new?template=feature.yml)
  to propose work. Refine the issue before implementation and link its pull request.

An open-source license must be selected before public distribution.
