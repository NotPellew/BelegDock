import argparse
import base64
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
import hashlib
from importlib import import_module
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SENDER_SERVICE = "BelegDock-Pilot"
SENDER_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]
MAX_FILE_SIZE = 5_000_000
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PilotMailError(RuntimeError):
    pass


def native_backend() -> Any:
    try:
        if sys.platform == "linux":
            backend = import_module("keyring.backends.SecretService").Keyring()
        elif sys.platform == "win32":
            backend = import_module("keyring.backends.Windows").WinVaultKeyring()
        else:
            raise RuntimeError("unsupported")
        if backend.priority <= 0:
            raise RuntimeError("unavailable")
        return backend
    except Exception:
        raise PilotMailError("native OS credential store unavailable; no plaintext fallback") from None


def save_sender_credentials(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PilotMailError("sender credentials must not be empty")
    try:
        native_backend().set_password(SENDER_SERVICE, "authorized-user", value)
    except PilotMailError:
        raise
    except Exception:
        raise PilotMailError("could not save sender credentials in the native OS store") from None


def load_sender_credentials() -> str:
    try:
        value = native_backend().get_password(SENDER_SERVICE, "authorized-user")
    except Exception:
        raise PilotMailError("could not read sender credentials from the native OS store") from None
    if not isinstance(value, str) or not value:
        raise PilotMailError("sender is not connected; run the pilot mail login command")
    return value


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or RUN_ID_PATTERN.fullmatch(value) is None:
        raise PilotMailError("manifest run ID is invalid")
    return value


def _regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise PilotMailError(f"file is unavailable: {path.name}") from error
    if not stat.S_ISREG(info.st_mode):
        raise PilotMailError(f"file is not regular: {path.name}")


def _external_path(path: Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise PilotMailError("pilot output path must not be a symlink")
    resolved = raw.resolve()
    repository = REPO_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise PilotMailError("pilot output path must be outside the repository")
    return resolved


def _safe_filename(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise PilotMailError("manifest filename is invalid")
    if Path(value).suffix.lower() not in {".pdf", ".xml"}:
        raise PilotMailError("manifest contains an unsupported attachment format")
    return value


def _manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(path: Path) -> dict[str, Any]:
    manifest_path = _external_path(Path(path))
    _regular_file(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotMailError("pilot manifest is unavailable or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise PilotMailError("pilot manifest schema is invalid")
    run_id = _run_id(manifest.get("runId"))
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise PilotMailError("pilot manifest has no documents")
    batch = manifest_path.parent.resolve()
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for entry in documents:
        if not isinstance(entry, dict):
            raise PilotMailError("pilot manifest document entry is invalid")
        if set(entry) != {"file", "role", "expected", "size", "sha256"}:
            raise PilotMailError("pilot manifest document entry has unexpected fields")
        filename = _safe_filename(entry["file"])
        if filename in seen:
            raise PilotMailError("pilot manifest contains duplicate filenames")
        seen.add(filename)
        file_path = batch / filename
        if file_path.parent != batch or file_path.is_symlink():
            raise PilotMailError("pilot manifest attachment path is unsafe")
        _regular_file(file_path)
        try:
            data = file_path.read_bytes()
        except OSError as error:
            raise PilotMailError(f"manifest attachment cannot be read: {filename}") from error
        if len(data) > MAX_FILE_SIZE:
            raise PilotMailError(f"manifest attachment exceeds the {MAX_FILE_SIZE}-byte limit")
        if not isinstance(entry["size"], int) or isinstance(entry["size"], bool) or entry["size"] != len(data):
            raise PilotMailError("manifest attachment size does not match")
        if not isinstance(entry["sha256"], str) or HASH_PATTERN.fullmatch(entry["sha256"]) is None:
            raise PilotMailError("manifest attachment hash is invalid")
        if entry["sha256"] != hashlib.sha256(data).hexdigest():
            raise PilotMailError(f"manifest attachment hash mismatch: {filename}")
        role_expectations = {"accepted": "accept", "duplicate": "deduplicate", "rejected": "reject"}
        if entry["role"] not in role_expectations:
            raise PilotMailError("manifest attachment role is invalid")
        if entry["expected"] != role_expectations[entry["role"]]:
            raise PilotMailError("manifest attachment expectation does not match its role")
        validated.append(dict(entry))
    result = dict(manifest)
    result["runId"] = run_id
    result["documents"] = validated
    result["_batchDir"] = batch
    result["_manifestSha256"] = _manifest_sha256(manifest_path)
    return result


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": manifest["schemaVersion"],
        "runId": manifest["runId"],
        "documents": [
            {
                "file": entry["file"],
                "role": entry["role"],
                "expected": entry["expected"],
                "size": entry["size"],
                "sha256": entry["sha256"],
            }
            for entry in manifest["documents"]
        ],
        "manifestSha256": manifest["_manifestSha256"],
    }


def build_message(manifest: dict[str, Any], recipient: str, label: str) -> bytes:
    if not isinstance(recipient, str) or not recipient.strip():
        raise PilotMailError("test recipient is required")
    if not isinstance(label, str) or not label.strip():
        raise PilotMailError("test label is required")
    batch = manifest.get("_batchDir")
    if not isinstance(batch, Path):
        raise PilotMailError("validated manifest has no batch directory")
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = f"[BelegDock Pilot] {manifest['runId']}"
    message["X-BelegDock-Pilot-Label"] = label
    message.set_content(
        "Synthetic BelegDock pilot fixture batch. No production document is included."
    )
    for entry in manifest["documents"]:
        filename = entry["file"]
        data = (batch / filename).read_bytes()
        if filename.lower().endswith(".pdf"):
            maintype, subtype = "application", "pdf"
        else:
            maintype, subtype = "application", "xml"
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes(policy=policy.SMTP)


def _profile(service: Any) -> str:
    try:
        profile = service.users().getProfile(userId="me").execute()
    except Exception as error:
        raise PilotMailError("could not verify the pilot Gmail account") from error
    account = profile.get("emailAddress") if isinstance(profile, dict) else None
    if not isinstance(account, str) or not account:
        raise PilotMailError("pilot Gmail account response is invalid")
    return account


def _label_id(service: Any, label: str) -> str:
    try:
        labels_resource = service.users().labels
        if callable(labels_resource):
            body = labels_resource().list(userId="me").execute()
        else:
            body = {"labels": labels_resource}
    except Exception as error:
        raise PilotMailError("could not load the pilot Gmail label") from error
    entries = body.get("labels", []) if isinstance(body, dict) else []
    matches = [
        entry.get("id")
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == label
    ]
    if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0]:
        raise PilotMailError(f"pilot Gmail label was not found uniquely: {label}")
    return matches[0]


def _build_service() -> Any:
    try:
        info = json.loads(load_sender_credentials())
        credentials_module = import_module("google.oauth2.credentials")
        request_module = import_module("google.auth.transport.requests")
        discovery = import_module("googleapiclient.discovery")
    except PilotMailError:
        raise
    except Exception as error:
        raise PilotMailError("could not load pilot sender authentication") from error
    try:
        credentials = credentials_module.Credentials.from_authorized_user_info(info, SENDER_SCOPES)
        if not credentials.valid:
            credentials.refresh(request_module.Request())
            save_sender_credentials(credentials.to_json())
        return discovery.build("gmail", "v1", credentials=credentials, cache_discovery=False)
    except PilotMailError:
        raise
    except Exception as error:
        raise PilotMailError("could not build the pilot Gmail service") from error


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    resolved = _external_path(path)
    if resolved.exists():
        raise PilotMailError(f"delivery receipt already exists: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _replace_receipt(path: Path, receipt: dict[str, Any]) -> None:
    resolved = _external_path(path)
    resolved.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def send_batch(
    manifest_path: Path,
    *,
    expected_account: str,
    label: str,
    execute: bool,
    service: Any = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    manifest = read_manifest(Path(manifest_path))
    if not isinstance(expected_account, str) or not expected_account.strip():
        raise PilotMailError("expected pilot Gmail account is required")
    if not isinstance(label, str) or not label.strip():
        raise PilotMailError("pilot Gmail label is required")
    if not execute:
        return {
            "outcome": "dry_run",
            "runId": manifest["runId"],
            "attachments": [entry["file"] for entry in manifest["documents"]],
            "manifestSha256": manifest["_manifestSha256"],
        }
    if service is None:
        service = _build_service()
    account = _profile(service)
    if account.casefold() != expected_account.casefold():
        raise PilotMailError("connected Gmail account does not match the expected pilot account")
    label_id = _label_id(service, label)
    raw = build_message(manifest, expected_account, label)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    receipt_file = Path(receipt_path) if receipt_path is not None else Path(manifest_path).parent / "delivery-receipt.json"
    receipt: dict[str, Any] = {
        "outcome": "send_pending",
        "runId": manifest["runId"],
        "manifestSha256": manifest["_manifestSha256"],
        "label": label,
        "messageId": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_receipt(receipt_file, receipt)
    users = service.users()
    messages_resource = users.messages
    messages = messages_resource() if callable(messages_resource) else messages_resource
    try:
        result = messages.send(userId="me", raw=encoded).execute()
    except Exception as error:
        receipt["outcome"] = "send_uncertain"
        _replace_receipt(receipt_file, receipt)
        raise PilotMailError("Gmail send outcome is uncertain; do not retry") from error
    message_id = result.get("id") if isinstance(result, dict) else None
    if not isinstance(message_id, str) or not message_id:
        receipt["outcome"] = "send_uncertain"
        _replace_receipt(receipt_file, receipt)
        raise PilotMailError("Gmail send returned no message ID; do not retry")
    receipt["messageId"] = message_id
    try:
        messages.modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
    except Exception as error:
        receipt["outcome"] = "sent_unlabeled"
        _replace_receipt(receipt_file, receipt)
        raise PilotMailError("Gmail message was sent but label application failed; do not resend") from error
    receipt["outcome"] = "sent"
    _replace_receipt(receipt_file, receipt)
    return receipt


def login(client_path: Path, expected_account: str) -> dict[str, str]:
    client = _external_path(Path(client_path))
    _regular_file(client)
    try:
        flow_module = import_module("google_auth_oauthlib.flow")
        discovery = import_module("googleapiclient.discovery")
        flow = flow_module.InstalledAppFlow.from_client_secrets_file(str(client), SENDER_SCOPES)
        credentials = flow.run_local_server(port=0)
        service = discovery.build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
    except Exception as error:
        raise PilotMailError("pilot Gmail login failed") from error
    account = profile.get("emailAddress") if isinstance(profile, dict) else None
    if not isinstance(account, str) or not account:
        raise PilotMailError("pilot Gmail profile response is invalid")
    if account.casefold() != expected_account.casefold():
        raise PilotMailError("authorized Gmail account does not match the expected pilot account")
    save_sender_credentials(credentials.to_json())
    return {"account": account, "service": SENDER_SERVICE}


def inspect_manifest(manifest_path: Path) -> dict[str, Any]:
    return _public_manifest(read_manifest(Path(manifest_path)))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send synthetic BelegDock pilot fixtures to a test label.")
    commands = parser.add_subparsers(dest="command", required=True)
    login_parser = commands.add_parser("login")
    login_parser.add_argument("--client", required=True, type=Path)
    login_parser.add_argument("--expected-account", required=True)
    send_parser = commands.add_parser("send")
    send_parser.add_argument("--manifest", required=True, type=Path)
    send_parser.add_argument("--expected-account", required=True)
    send_parser.add_argument("--label", required=True)
    send_parser.add_argument("--execute", action="store_true")
    send_parser.add_argument("--receipt", type=Path)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "login":
            result = login(args.client, args.expected_account)
        elif args.command == "send":
            result = send_batch(
                args.manifest,
                expected_account=args.expected_account,
                label=args.label,
                execute=args.execute,
                receipt_path=args.receipt,
            )
        else:
            result = inspect_manifest(args.manifest)
    except (PilotMailError, OSError, ValueError) as error:
        print(f"pilot mail operation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
