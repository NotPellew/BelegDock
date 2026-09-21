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
from .desktop import DesktopUnavailableError, run_desktop
from .service import refresh_remote_inventory as _refresh_remote_inventory
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


def default_data_dir() -> Path:
    return Path(import_module("platformdirs").user_data_dir("BelegDock", appauthor=False))


def recover_upload_command(digest: str) -> str:
    return f"belegdock recover-upload {digest}"


def reconcile_command(digest: str) -> str:
    return f"belegdock reconcile {digest} --file-id FILE_ID --voucher-id VOUCHER_ID"


def valid_document_hash(digest: str) -> bool:
    try:
        Store._validate_digest(digest)
    except ValueError:
        return False
    return True


def document_status(data_dir: Path, digest: str) -> str | None:
    try:
        for document in Store(data_dir).list_documents():
            if document.get("hash") == digest:
                status = document.get("status")
                return status if isinstance(status, str) else None
    except Exception:
        return None
    return None


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
    commands.add_parser("desktop", help="Open the local desktop transfer interface")
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
    if args.command == "desktop":
        return run_desktop(args.data_dir)
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
    data_dir = args.data_dir or default_data_dir()
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
    return _refresh_remote_inventory(store, remote)


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
        if args.command != "desktop":
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
    except DesktopUnavailableError:
        print(
            "Desktop UI is unavailable; install Python Tk support and run 'belegdock desktop' again.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        if args.command == "stage":
            message = "Staging failed; check selection, connection, file size, and local storage."
        elif args.command == "upload":
            if not valid_document_hash(args.hash):
                message = "Invalid document hash; run 'belegdock documents' and copy a SHA-256 hash."
            else:
                status = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == "uncertain":
                    message = (
                        f"Upload outcome is uncertain for {args.hash}; do not retry. Inspect Lexware, then run "
                        f"'{reconcile_command(args.hash)}'."
                    )
                elif status == "uploading":
                    message = (
                        f"Upload is already active for {args.hash}; do not retry. If its process stopped before "
                        f"reporting an outcome, run '{recover_upload_command(args.hash)}'."
                    )
                else:
                    message = "Upload failed before sending the document; correct the problem and retry."
        elif args.command == "recover-upload":
            if not valid_document_hash(args.hash):
                message = "Invalid document hash; run 'belegdock documents' and copy a SHA-256 hash."
            else:
                status = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == "uncertain":
                    message = (
                        f"Recovery is not needed; the outcome for {args.hash} is already uncertain. Do not retry "
                        f"the upload. Inspect Lexware, then run '{reconcile_command(args.hash)}'."
                    )
                elif status == "uploading":
                    message = (
                        "Recovery failed; an active upload cannot be recovered. Wait for it to finish. If the "
                        f"process stopped before reporting an outcome, run '{recover_upload_command(args.hash)}'."
                    )
                else:
                    message = "Recovery did not start; only an interrupted upload can be recovered. Check documents."
        elif args.command == "reconcile":
            if not valid_document_hash(args.hash):
                message = "Invalid document hash; run 'belegdock documents' and copy a SHA-256 hash."
            else:
                status = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == "uncertain":
                    message = (
                        f"Reconciliation failed for {args.hash}; the document remains uncertain. Do not retry the "
                        f"upload. Inspect Lexware, then run '{reconcile_command(args.hash)}'."
                    )
                elif status == "staged":
                    message = (
                        f"Reconciliation did not start; the document is still staged. To send it explicitly, run "
                        f"'belegdock upload {args.hash}'."
                    )
                elif status == "uploading":
                    message = (
                        "Reconciliation cannot run while an upload is active. If the process stopped before "
                        f"reporting an outcome, run '{recover_upload_command(args.hash)}'."
                    )
                else:
                    message = "Reconciliation did not start; only an uncertain upload can be reconciled. Check documents."
        elif args.command.startswith("login"):
            message = "Connection failed; check the native credential store and account/client setup."
        elif args.command == "desktop":
            message = "Desktop operation failed; check Python Tk support and account setup."
        else:
            message = "Operation failed; check account connection, label, and local storage."
        print(message, file=sys.stderr)
        return 1
