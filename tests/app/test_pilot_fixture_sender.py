import base64
import hashlib
import importlib.util
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_mail.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pilot_fixture_sender", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("pilot mail sender could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Messages:
    def __init__(self, label_error=None, send_error=None):
        self.label_error = label_error
        self.send_error = send_error
        self.send_calls = []
        self.modify_calls = []

    def send(self, **kwargs):
        self.send_calls.append(kwargs)
        if self.send_error:
            raise self.send_error
        return Result({"id": "message-1"})

    def modify(self, **kwargs):
        self.modify_calls.append(kwargs)
        if self.label_error:
            raise self.label_error
        return Result({"id": kwargs["id"]})


class Users:
    def __init__(self, messages, account="pilot@example.test", labels=None):
        self.messages = messages
        self.account = account
        self.labels = labels or [{"id": "Label_1", "name": "BelegDock-Pilot"}]

    def getProfile(self, **kwargs):
        return Result({"emailAddress": self.account})

    def labels(self):
        return self

    def list(self, **kwargs):
        return Result({"labels": self.labels})

    def messages(self):
        return self.messages


class Service:
    def __init__(self, messages, account="pilot@example.test", labels=None):
        self.messages = messages
        self.user_resource = Users(messages, account, labels)

    def users(self):
        return self.user_resource


class PilotFixtureSenderTests(unittest.TestCase):
    def load_module(self):
        return load_module()

    def make_batch(self, root):
        batch = root / "batch"
        batch.mkdir()
        payload = b"%PDF-1.7\nsynthetic pilot attachment\n%%EOF\n"
        (batch / "accepted-001.pdf").write_bytes(payload)
        manifest = {
            "schemaVersion": 1,
            "runId": "pilot-001",
            "documents": [
                {
                    "file": "accepted-001.pdf",
                    "role": "accepted",
                    "expected": "accept",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        (batch / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return batch / "manifest.json"

    def test_sender_uses_a_separate_service_and_scopes(self):
        module = self.load_module()
        self.assertEqual(module.SENDER_SERVICE, "BelegDock-Pilot")
        self.assertEqual(
            module.SENDER_SCOPES,
            [
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
        )

        class Backend:
            def __init__(self):
                self.calls = []

            def set_password(self, service, name, value):
                self.calls.append((service, name, value))

        backend = Backend()
        with patch.object(module, "native_backend", return_value=backend):
            module.save_sender_credentials("authorized-user")
        self.assertEqual(backend.calls[0][0], "BelegDock-Pilot")
        self.assertNotEqual(backend.calls[0][0], "BelegDock")

    def test_dry_run_does_not_require_or_call_gmail(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            result = module.send_batch(
                manifest,
                expected_account="pilot@example.test",
                label="BelegDock-Pilot",
                execute=False,
            )
        self.assertEqual(result["outcome"], "dry_run")
        self.assertEqual(result["attachments"], ["accepted-001.pdf"])

    def test_mime_message_contains_manifest_attachment_bytes(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = self.make_batch(Path(temporary))
            manifest = module.read_manifest(manifest_path)
            raw = module.build_message(manifest, "pilot@example.test", "BelegDock-Pilot")
            message = BytesParser(policy=policy.default).parsebytes(raw)
            attachments = list(message.iter_attachments())
            self.assertEqual(message["To"], "pilot@example.test")
            self.assertIn("pilot-001", message["Subject"])
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), "accepted-001.pdf")
            expected = (manifest_path.parent / "accepted-001.pdf").read_bytes()
            self.assertEqual(attachments[0].get_payload(decode=True), expected)

    def test_live_send_calls_profile_send_and_label_once(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages()
            service = Service(messages)
            receipt_path = Path(temporary) / "receipt.json"
            result = module.send_batch(
                manifest,
                expected_account="pilot@example.test",
                label="BelegDock-Pilot",
                execute=True,
                service=service,
                receipt_path=receipt_path,
            )
            self.assertEqual(result["outcome"], "sent")
            self.assertEqual(len(messages.send_calls), 1)
            self.assertEqual(len(messages.modify_calls), 1)
            self.assertEqual(messages.modify_calls[0]["id"], "message-1")
            self.assertEqual(messages.modify_calls[0]["body"], {"addLabelIds": ["Label_1"]})
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["outcome"], "sent")
            self.assertEqual(receipt["messageId"], "message-1")
            raw = base64.urlsafe_b64decode(messages.send_calls[0]["raw"] + "===")
            self.assertIn(b"accepted-001.pdf", raw)

    def test_unexpected_account_fails_before_sending(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages()
            service = Service(messages, account="other@example.test")
            with self.assertRaises(module.PilotMailError):
                module.send_batch(
                    manifest,
                    expected_account="pilot@example.test",
                    label="BelegDock-Pilot",
                    execute=True,
                    service=service,
                )
            self.assertEqual(messages.send_calls, [])

    def test_send_failure_is_uncertain_and_not_retried(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages(send_error=TimeoutError("connection lost"))
            service = Service(messages)
            receipt_path = Path(temporary) / "receipt.json"
            with self.assertRaises(module.PilotMailError):
                module.send_batch(
                    manifest,
                    expected_account="pilot@example.test",
                    label="BelegDock-Pilot",
                    execute=True,
                    service=service,
                    receipt_path=receipt_path,
                )
            self.assertEqual(len(messages.send_calls), 1)
            self.assertEqual(json.loads(receipt_path.read_text())["outcome"], "send_uncertain")

    def test_label_failure_reports_sent_unlabeled_without_resending(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages(label_error=RuntimeError("label update failed"))
            service = Service(messages)
            receipt_path = Path(temporary) / "receipt.json"
            with self.assertRaises(module.PilotMailError):
                module.send_batch(
                    manifest,
                    expected_account="pilot@example.test",
                    label="BelegDock-Pilot",
                    execute=True,
                    service=service,
                    receipt_path=receipt_path,
                )
            self.assertEqual(len(messages.send_calls), 1)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["outcome"], "sent_unlabeled")
            self.assertEqual(receipt["messageId"], "message-1")


if __name__ == "__main__":
    unittest.main()
