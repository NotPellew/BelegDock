import argparse
import getpass
import json
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

from . import __version__, accounts
from .integrations import GmailAdapter, LexwareAdapter
from .workflow import DocumentRejected, LocalIntegrityError, Store

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

QUICK_START = """quick start:
  belegdock login-gmail --client CLIENT_JSON
  belegdock login-lexware
  belegdock scan --label LABEL
  belegdock stage --label LABEL --select MESSAGE_ID:PART_ID
  belegdock documents
  belegdock refresh
  belegdock upload SHA256_HASH

recovery after an interrupted upload:
  belegdock recover-upload SHA256_HASH
  belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID
  An uncertain upload is never retried automatically."""


def build_gmail(credentials: Any) -> Any:
    return import_module("googleapiclient.discovery").build(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )


def connect_gmail(client_path: Path) -> str:
    accounts.native_backend()
    flow = import_module("google_auth_oauthlib.flow").InstalledAppFlow.from_client_secrets_file(
        str(client_path), SCOPES
    )
    credentials = flow.run_local_server(port=0)
    service = build_gmail(credentials)
    account = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    accounts.save_secret("gmail", credentials.to_json())
    return account


def gmail_client() -> tuple[str, GmailAdapter]:
    info = json.loads(accounts.load_secret("gmail"))
    credentials = import_module("google.oauth2.credentials").Credentials.from_authorized_user_info(
        info, SCOPES
    )
    if not credentials.valid:
        credentials.refresh(import_module("google.auth.transport.requests").Request())
        accounts.save_secret("gmail", credentials.to_json())
    service = build_gmail(credentials)
    account = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    return account, GmailAdapter(service)


def lexware_client() -> LexwareAdapter:
    client = import_module("httpx").Client(
        headers={"Authorization": "Bearer " + accounts.load_secret("lexware"), "Accept": "application/json"},
        follow_redirects=False,
    )
    return LexwareAdapter(client)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="belegdock",
        description="BelegDock early-stage CLI for local document transfer experiments.",
        epilog=QUICK_START,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="Override local staging and SQLite directory")
    commands = parser.add_subparsers(dest="command")
    login = commands.add_parser("login-gmail", help="Connect Gmail read-only through browser OAuth")
    login.add_argument("--client", type=Path, required=True, help="Desktop OAuth client JSON outside checkout")
    commands.add_parser("login-lexware", help="Store an API key using a hidden prompt")
    for name in ("scan", "stage"):
        command = commands.add_parser(name, help="List candidates" if name == "scan" else "Stage selected attachments")
        command.add_argument("--label", required=True)
        if name == "stage":
            command.add_argument("--select", action="append", required=True, help="Candidate ID from scan; repeat to select more")
    commands.add_parser("documents", help="List local documents and transfer states")
    commands.add_parser("refresh", help="Refresh the local Lexware file inventory")
    upload = commands.add_parser("upload", help="Explicitly upload one staged hash")
    upload.add_argument("hash")
    recover = commands.add_parser("recover-upload", help="Mark an interrupted local upload as uncertain")
    recover.add_argument("hash")
    reconcile = commands.add_parser("reconcile", help="Verify a known remote document before recording it")
    reconcile.add_argument("hash")
    reconcile.add_argument("--file-id", required=True)
    reconcile.add_argument("--voucher-id", required=True)
    return parser


def dispatch(args: argparse.Namespace) -> Any:
    if args.command == "login-gmail":
        return {"account": connect_gmail(args.client)}
    if args.command == "login-lexware":
        accounts.native_backend()
        accounts.save_secret("lexware", getpass.getpass("Lexware API key: "))
        return {"connected": "lexware"}
    if args.command in ("scan", "stage"):
        account, gmail = gmail_client()
        candidates = gmail.candidates(args.label)
        if args.command == "scan":
            return [{key: value for key, value in candidate.items() if key not in ("inline_data", "attachment_id")} for candidate in candidates]
        selected = set(args.select)
        if selected - {item["id"] for item in candidates}:
            raise ValueError("Unknown selection; scan the label again.")
    data_dir = args.data_dir or Path(import_module("platformdirs").user_data_dir("BelegDock", appauthor=False))
    store = Store(data_dir)
    if args.command == "documents":
        return store.list_documents()
    if args.command == "refresh":
        remote = lexware_client()
        try:
            return refresh_remote_inventory(store, remote)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    if args.command == "stage":
        return [store.stage(account, item["message_id"], item["part_id"], item["filename"], gmail.fetch(item))
                for item in candidates if item["id"] in selected]
    if args.command == "upload":
        remote = lexware_client()
        try:
            client = getattr(remote, "client", None)
            def refresh() -> dict[str, Any]:
                return refresh_remote_inventory(store, remote)
            verify = getattr(remote, "verify_existing", None)
            return store.upload(args.hash, remote.upload, refresh, verify=verify if callable(verify) else None)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    if args.command == "recover-upload":
        return store.recover_upload(args.hash)
    if args.command == "reconcile":
        remote = lexware_client()
        try:
            return store.reconcile(args.hash, args.file_id, args.voucher_id, remote.verify_existing)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    raise ValueError("Choose a command from --help.")


def refresh_remote_inventory(store: Store, remote: LexwareAdapter) -> dict[str, Any]:
    try:
        inventory = remote.inventory(include_archived=True, expected_organization_id=store.remote_organization())
        files = []
        for item in inventory["files"]:
            enriched = dict(item)
            cached = store.cached_remote_hash(inventory["organizationId"], item)
            enriched["hash"] = cached if cached is not None else remote.hash_file(item["id"])
            files.append(enriched)
        store.refresh_remote(inventory["organizationId"], files)
        return {"organizationId": inventory["organizationId"], "count": len(files)}
    except Exception:
        store.record_refresh_failure("remote_refresh_failed")
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    if args.command is None:
        parser.print_help()
        return 0
    try:
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=True))
        if args.command == "documents" and any(
            item.get("localIntegrity") != "ok" for item in result
        ):
            print(
                "Local document integrity failed; restore state.sqlite3 and blobs from a consistent backup.",
                file=sys.stderr,
            )
            return 1
        return 0
    except DocumentRejected as error:
        print(
            f"Upload rejected by Lexware (HTTP {error.status_code}); correct the document and stage new bytes.",
            file=sys.stderr,
        )
        return 1
    except LocalIntegrityError:
        print(
            "Local data is unavailable; restore state.sqlite3 and blobs from a consistent backup.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        if args.command == "stage":
            message = "Staging failed; check selection, connection, file size, and local storage."
        elif args.command == "upload":
            message = "Upload failed; inspect documents. Uncertain outcomes require manual reconciliation before retry."
        elif args.command == "recover-upload":
            message = "Recovery failed; an active upload cannot be recovered. Inspect documents before reconciliation."
        elif args.command == "reconcile":
            message = "Reconciliation failed; the document remains uncertain. Do not retry the upload."
        elif args.command.startswith("login"):
            message = "Connection failed; check the native credential store and account/client setup."
        else:
            message = "Operation failed; check account connection, label, and local storage."
        print(message, file=sys.stderr)
        return 1
