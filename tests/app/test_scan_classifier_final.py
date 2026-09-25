from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from unittest.mock import patch

from belegdock import cli
from belegdock.classification import CandidateClassification
from belegdock.integrations import GmailAdapter


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class HeaderGmailService:
    def users(self):
        return self

    def labels(self):
        class Labels:
            def list(self, **_kwargs):
                return Request({"labels": [{"id": "label", "name": "Invoices"}]})

        return Labels()

    def messages(self):
        return self

    def list(self, **_kwargs):
        return Request({"messages": [{"id": "message"}]})

    def get(self, **_kwargs):
        return Request(
            {
                "id": "message",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Rechnung PRIVATE-SUBJECT-MARKER"}
                    ],
                    "parts": [
                        {
                            "partId": "1",
                            "filename": "scan.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "attachment", "size": 4},
                        }
                    ],
                },
            }
        )


class ScanClassifierFinalTests(unittest.TestCase):
    def invoke_scan(self, gmail):
        output = StringIO()
        error = StringIO()
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cli, "gmail_client", return_value=("account", gmail)
        ), redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", temporary, "scan", "--label", "Invoices"])
        return status, output.getvalue(), error.getvalue()

    def test_credit_note_sender_phrases_are_recognized(self):
        from belegdock.classification import classify_candidate

        for sender in ("Credit Note <notes@example.test>", "Credit Notes <notes@example.test>"):
            with self.subTest(sender=sender):
                result = classify_candidate("statement.pdf", sender=sender)
                self.assertEqual(result.document_type, "credit_note")
                self.assertEqual(result.recommendation, "unclear")
                self.assertTrue(result.signals)

    def test_scan_uses_subject_for_weak_filename_and_rejects_invalid_identity(self):
        status, output, error = self.invoke_scan(GmailAdapter(HeaderGmailService()))
        item = json.loads(output)[0]
        self.assertEqual(status, 0, error)
        self.assertEqual(item["documentType"], "invoice")
        self.assertEqual(item["recommendation"], "likely")
        self.assertTrue(any("Betreff" in signal for signal in item["signals"]))
        self.assertNotIn("PRIVATE-SUBJECT-MARKER", output + error)

        class InvalidGmail:
            def candidates(self, _label):
                return [
                    {
                        "id": "",
                        "message_id": "message",
                        "part_id": "1",
                        "filename": "scan.pdf",
                        "size": 4,
                    }
                ]

            def candidate_classification(self, _candidate_id):
                return CandidateClassification("unknown", "unclear", ())

        status, output, error = self.invoke_scan(InvalidGmail())
        self.assertNotEqual(status, 0)
        self.assertEqual(output, "")
        self.assertNotIn("message", error)
        self.assertIn("fehlgeschlagen", error.lower())


if __name__ == "__main__":
    unittest.main()
