import argparse
import base64
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
import importlib.util
from importlib import import_module
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SENDER_SERVICE = "BelegDock-Pilot"
SENDER_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class PilotMailError(RuntimeError):
    pass


def _load_generator() -> Any:
    path = _path_without_symlink_components(
        Path(__file__).with_name("generate_pilot_fixtures.py")
    )
    spec = importlib.util.spec_from_file_location("pilot_fixture_generator", path)
    if spec is None or spec.loader is None:
        raise PilotMailError("pilot fixture validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise PilotMailError("pilot fixture validator could not be loaded") from error
    return module


def _path_without_symlink_components(path: Path) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current /= part
        if current.is_symlink():
            raise PilotMailError(f"path must not contain symlink components: {path}")
    return raw


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


def _regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise PilotMailError(f"file is unavailable: {path.name}") from error
    if not stat.S_ISREG(info.st_mode):
        raise PilotMailError(f"file is not regular: {path.name}")


def _external_path(path: Path) -> Path:
    raw = _path_without_symlink_components(path)
    resolved = raw.resolve()
    repository = REPO_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise PilotMailError("pilot output path must be outside the repository")
    return resolved


def read_manifest(path: Path) -> dict[str, Any]:
    manifest_path = _external_path(Path(path))
    if manifest_path.name != "manifest.json":
        raise PilotMailError("pilot manifest filename is invalid")
    _regular_file(manifest_path)
    generator = _load_generator()
    try:
        validated, files = generator.validated_batch(manifest_path.parent)
    except Exception as error:
        raise PilotMailError("pilot manifest is not a generated synthetic fixture batch") from error
    result = {
        "schemaVersion": 1,
        "runId": validated["runId"],
        "templateVersion": validated["templateVersion"],
        "documents": validated["documents"],
    }
    result["_batchDir"] = manifest_path.parent.resolve()
    result["_manifestSha256"] = validated["manifestSha256"]
    result["_batchFiles"] = files
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
    batch_files = manifest.get("_batchFiles")
    if not isinstance(batch_files, dict):
        raise PilotMailError("validated manifest has no verified batch files")
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = f"[BelegDock Pilot] {manifest['runId']}"
    message["X-BelegDock-Pilot-Label"] = label
    message.set_content(
        "Synthetic BelegDock pilot fixture batch. No production document is included."
    )
    for entry in manifest["documents"]:
        filename = entry["file"]
        data = batch_files.get(filename)
        if not isinstance(data, bytes):
            raise PilotMailError(f"validated manifest has no bytes for {filename}")
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
    if not isinstance(entries, list):
        raise PilotMailError("pilot Gmail label response is invalid")
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


def _http_status(error: Exception) -> int | None:
    try:
        error_type = import_module("googleapiclient.errors").HttpError
    except Exception:
        return None
    if not isinstance(error, error_type):
        return None
    status = getattr(error.resp, "status", None)
    return status if isinstance(status, int) else None


def _receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _fsync_parent(path: Path) -> None:
    if sys.platform == "win32":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path.parent, flags)
    except OSError as error:
        raise PilotMailError("could not open delivery receipt directory") from error
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise PilotMailError("could not sync delivery receipt directory") from error
    finally:
        os.close(descriptor)


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    resolved = _external_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = _receipt_bytes(receipt)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(resolved, flags, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("receipt write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        _fsync_parent(resolved)
    except FileExistsError as error:
        raise PilotMailError(f"delivery receipt already exists: {resolved}") from error
    except OSError as error:
        if descriptor is not None:
            try:
                resolved.unlink()
            except OSError:
                pass
        raise PilotMailError("could not claim delivery receipt") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _remove_receipt_if_present(path: Path) -> None:
    try:
        _external_path(path).unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise PilotMailError("could not clean up unclaimed delivery receipt") from error


def _replace_receipt(path: Path, receipt: dict[str, Any]) -> None:
    resolved = _external_path(path)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{resolved.name}.", dir=resolved.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(_receipt_bytes(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        _fsync_parent(resolved)
    except (OSError, PilotMailError) as error:
        raise PilotMailError("could not update delivery receipt") from error
    finally:
        if descriptor != -1:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _persist_receipt(path: Path, receipt: dict[str, Any], context: str) -> None:
    try:
        _replace_receipt(path, receipt)
    except PilotMailError as error:
        message_id = receipt.get("messageId")
        suffix = f" Message ID: {message_id}." if isinstance(message_id, str) and message_id else ""
        raise PilotMailError(
            f"{context}; delivery receipt could not be persisted; do not retry.{suffix}"
        ) from error


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
        "remoteState": "pending",
        "runId": manifest["runId"],
        "manifestSha256": manifest["_manifestSha256"],
        "label": label,
        "messageId": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    claim_file = Path(manifest["_batchDir"]) / ".delivery-claim.json"
    if receipt_file.resolve() == claim_file.resolve():
        raise PilotMailError("delivery receipt cannot replace the canonical batch claim")
    _write_receipt(receipt_file, receipt)
    try:
        _write_receipt(
            claim_file,
            {
                "runId": manifest["runId"],
                "manifestSha256": manifest["_manifestSha256"],
                "claimedAt": receipt["timestamp"],
            },
        )
    except PilotMailError:
        _remove_receipt_if_present(receipt_file)
        raise
    users = service.users()
    messages_resource = users.messages
    messages = messages_resource() if callable(messages_resource) else messages_resource
    try:
        request = messages.send(userId="me", body={"raw": encoded})
    except Exception as error:
        receipt["outcome"] = "send_failed"
        receipt["remoteState"] = "not_sent"
        _persist_receipt(
            receipt_file,
            receipt,
            "Gmail send request could not be constructed; no message was sent",
        )
        raise PilotMailError(
            "Gmail send request could not be constructed; no message was sent"
        ) from error
    try:
        result = request.execute()
    except Exception as error:
        status = _http_status(error)
        if status is not None and 400 <= status < 500:
            receipt["outcome"] = "send_rejected"
            receipt["remoteState"] = "not_sent"
            receipt["httpStatus"] = status
            message = "Gmail rejected the message; do not retry"
        else:
            receipt["outcome"] = "send_uncertain"
            receipt["remoteState"] = "unknown"
            if status is not None:
                receipt["httpStatus"] = status
            message = "Gmail send outcome is uncertain; do not retry"
        _persist_receipt(receipt_file, receipt, message)
        raise PilotMailError(message) from error
    message_id = result.get("id") if isinstance(result, dict) else None
    if not isinstance(message_id, str) or not message_id:
        receipt["outcome"] = "send_uncertain"
        receipt["remoteState"] = "unknown"
        _persist_receipt(
            receipt_file,
            receipt,
            "Gmail send returned no message ID; do not retry",
        )
        raise PilotMailError("Gmail send returned no message ID; do not retry")
    receipt["messageId"] = message_id
    try:
        label_result = messages.modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        if (
            not isinstance(label_result, dict)
            or label_result.get("id") != message_id
            or not isinstance(label_result.get("labelIds"), list)
            or label_id not in label_result["labelIds"]
        ):
            raise ValueError("invalid label response")
    except Exception as error:
        receipt["outcome"] = "sent_label_unknown"
        receipt["remoteState"] = "label_unknown"
        status = _http_status(error)
        if status is not None:
            receipt["httpStatus"] = status
        _persist_receipt(
            receipt_file,
            receipt,
            "Gmail message was sent but label state is unknown; do not resend",
        )
        raise PilotMailError(
            "Gmail message was sent but label state is unknown; do not resend"
        ) from error
    receipt["outcome"] = "sent"
    receipt["remoteState"] = "labeled"
    _persist_receipt(
        receipt_file,
        receipt,
        "Gmail message was sent and labeled; do not retry",
    )
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
