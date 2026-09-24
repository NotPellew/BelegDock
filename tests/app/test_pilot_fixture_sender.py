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

from googleapiclient.errors import HttpError


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_mail.py"
GENERATOR_SCRIPT = ROOT / "scripts" / "generate_pilot_fixtures.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pilot_fixture_sender", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("pilot mail sender could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_generator():
    spec = importlib.util.spec_from_file_location("pilot_fixture_sender_generator", GENERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("pilot fixture generator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Messages:
    def __init__(self, label_error=None, send_error=None, label_result=None):
        self.label_error = label_error
        self.send_error = send_error
        self.label_result = label_result
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
        if self.label_result is not None:
            return Result(self.label_result)
        return Result({"id": kwargs["id"], "labelIds": ["Label_1"]})


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
        load_generator().generate_batch(batch, "pilot-001")
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
        self.assertEqual(
            result["attachments"],
            [
                "accepted-001.pdf",
                "duplicate-001.pdf",
                "rejected-001.xml",
                "accepted-002.xml",
            ],
        )

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
            self.assertEqual(len(attachments), 4)
            self.assertEqual(
                [attachment.get_filename() for attachment in attachments],
                [
                    "accepted-001.pdf",
                    "duplicate-001.pdf",
                    "rejected-001.xml",
                    "accepted-002.xml",
                ],
            )
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

    def test_label_failure_reports_unknown_state_without_resending(self):
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
            self.assertEqual(receipt["outcome"], "sent_label_unknown")
            self.assertEqual(receipt["remoteState"], "label_unknown")
            self.assertEqual(receipt["messageId"], "message-1")

    def test_read_manifest_rejects_unbound_synthetic_content(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = self.make_batch(Path(temporary))
            payload = b"%PDF-1.4\r\nsynthetic but not trusted\r\n%%EOF\r\n"
            (manifest_path.parent / "accepted-001.pdf").write_bytes(payload)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest["documents"]:
                if entry["file"] == "accepted-001.pdf":
                    entry["size"] = len(payload)
                    entry["sha256"] = hashlib.sha256(payload).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(module.PilotMailError):
                module.read_manifest(manifest_path)

    def test_mime_uses_bytes_validated_before_later_file_changes(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = self.make_batch(Path(temporary))
            manifest = module.read_manifest(manifest_path)
            accepted = manifest_path.parent / "accepted-001.pdf"
            original = accepted.read_bytes()
            accepted.write_bytes(b"changed after validation")
            raw = module.build_message(manifest, "pilot@example.test", "BelegDock-Pilot")
            message = BytesParser(policy=policy.default).parsebytes(raw)
            attachment = list(message.iter_attachments())[0]
            self.assertEqual(attachment.get_payload(decode=True), original)

    def test_definitive_send_rejection_is_recorded_without_retry(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            response = type("Response", (), {"status": 400, "reason": "Bad Request"})()
            messages = Messages(send_error=HttpError(resp=response, content=b"{}"))
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
            self.assertEqual(receipt["outcome"], "send_rejected")
            self.assertEqual(receipt["remoteState"], "not_sent")
            self.assertEqual(receipt["httpStatus"], 400)
    def test_malformed_label_response_is_unknown_without_resending(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages(label_result={"id": "message-1"})
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
            self.assertEqual(len(messages.modify_calls), 1)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["outcome"], "sent_label_unknown")
            self.assertEqual(receipt["messageId"], "message-1")

    def test_malformed_label_list_fails_before_sending(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages()
            service = Service(messages)
            service.user_resource.labels = None
            with self.assertRaises(module.PilotMailError):
                module.send_batch(
                    manifest,
                    expected_account="pilot@example.test",
                    label="BelegDock-Pilot",
                    execute=True,
                    service=service,
                )
            self.assertEqual(messages.send_calls, [])

    def test_post_send_receipt_failure_preserves_remote_state_in_error(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages()
            service = Service(messages)
            with patch.object(module.tempfile, "mkstemp", side_effect=OSError("no temporary space")):
                with self.assertRaisesRegex(module.PilotMailError, "message-1"):
                    module.send_batch(
                        manifest,
                        expected_account="pilot@example.test",
                        label="BelegDock-Pilot",
                        execute=True,
                        service=service,
                        receipt_path=Path(temporary) / "receipt.json",
                    )
            self.assertEqual(len(messages.send_calls), 1)
            self.assertEqual(len(messages.modify_calls), 1)

    def test_alternate_receipt_path_cannot_bypass_batch_claim(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_batch(Path(temporary))
            messages = Messages()
            service = Service(messages)
            first_receipt = Path(temporary) / "first-receipt.json"
            second_receipt = Path(temporary) / "second-receipt.json"
            module.send_batch(
                manifest,
                expected_account="pilot@example.test",
                label="BelegDock-Pilot",
                execute=True,
                service=service,
                receipt_path=first_receipt,
            )
            with self.assertRaises(module.PilotMailError):
                module.send_batch(
                    manifest,
                    expected_account="pilot@example.test",
                    label="BelegDock-Pilot",
                    execute=True,
                    service=service,
                    receipt_path=second_receipt,
                )
            self.assertEqual(len(messages.send_calls), 1)

    def test_receipt_claim_is_exclusive_and_updates_are_atomic(self):
        module = self.load_module()
        self.assertTrue(hasattr(module, "os"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            first = {"outcome": "send_pending", "messageId": None}
            second = {"outcome": "sent", "messageId": "message-1"}
            module._write_receipt(path, first)
            with self.assertRaises(module.PilotMailError):
                module._write_receipt(path, second)
            with patch.object(module.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(module.PilotMailError):
                    module._replace_receipt(path, second)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), first)
            module._replace_receipt(path, second)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), second)


if __name__ == "__main__":
    unittest.main()
