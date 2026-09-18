import argparse
from collections.abc import Sequence
import getpass
from importlib import import_module
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__, accounts
from .integrations import GmailAdapter, LexwareAdapter
from .workflow import Store

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


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
    upload = commands.add_parser("upload", help="Explicitly upload one staged hash")
    upload.add_argument("hash")
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
    if args.command == "stage":
        return [store.stage(account, item["message_id"], item["part_id"], item["filename"], gmail.fetch(item))
                for item in candidates if item["id"] in selected]
    if args.command == "upload":
        remote = lexware_client()
        try:
            return store.upload(args.hash, remote.upload)
        finally:
            client = getattr(remote, "client", None)
            if client is not None:
                client.close()
    raise ValueError("Choose a command from --help.")


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
        return 0
    except Exception:
        if args.command == "stage":
            message = "Staging failed; check selection, connection, file size, and local storage."
        elif args.command == "upload":
            message = "Upload failed; inspect documents. Uncertain outcomes require manual reconciliation before retry."
        elif args.command.startswith("login"):
            message = "Connection failed; check the native credential store and account/client setup."
        else:
            message = "Operation failed; check account connection, label, and local storage."
        print(message, file=sys.stderr)
        return 1
