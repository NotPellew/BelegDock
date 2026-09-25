from contextlib import redirect_stderr, redirect_stdout
import importlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.desktop import DesktopApplication, DesktopService
from belegdock.integrations import GmailAdapter
from belegdock.workflow import Store


def classification_module():
    spec = importlib.util.find_spec("belegdock.classification")
    if spec is None:
        raise AssertionError("belegdock.classification is missing")
    return importlib.import_module("belegdock.classification")


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeGmailService:
    def __init__(self):
        self.label_requests = []
        self.message_requests = []
        self.message = {
            "id": "message",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Rechnung PRIVATE-SUBJECT-MARKER"},
                    {"name": "From", "value": "Billing <PRIVATE-SENDER-MARKER@example.test>"},
                    {"name": "Date", "value": "PRIVATE-DATE-MARKER"},
                ],
                "parts": [
                    {
                        "partId": "1",
                        "filename": "Rechnung_2026.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "attachment-1", "size": 4},
                    },
                    {
                        "partId": "2",
                        "filename": "scan.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "attachment-2", "size": 4},
                    },
                ],
            },
        }

    def users(self):
        return self

    def labels(self):
        service = self

        class Labels:
            def list(self, **kwargs):
                service.label_requests.append(kwargs)
                return Request({"labels": [{"id": "label", "name": "Invoices"}]})

        return Labels()

    def messages(self):
        return self

    def list(self, **kwargs):
        self.message_requests.append(kwargs)
        return Request({"messages": [{"id": "message"}]})

    def get(self, **kwargs):
        self.message_requests.append(kwargs)
        return Request(self.message)


class FakeCandidateTree:
    def __init__(self):
        self.rows = []
        self.selection_calls = 0

    def get_children(self):
        return tuple(row[0] for row in self.rows)

    def delete(self, row):
        self.rows = [item for item in self.rows if item[0] != row]

    def insert(self, _parent, _index, values):
        row = str(len(self.rows))
        self.rows.append((row, values))
        return row

    def selection(self):
        self.selection_calls += 1
        return []


class FixedRuleClassifierTests(unittest.TestCase):
    def test_filename_tokens_cover_german_and_english_document_types(self):
        module = classification_module()
        cases = (
            ("Rechnung_2026.pdf", "invoice"),
            ("Invoice_2026.pdf", "invoice"),
            ("Gutschrift_2026.pdf", "credit_note"),
            ("Credit_Note_2026.pdf", "credit_note"),
            ("Kassenbon.pdf", "receipt"),
            ("Receipt_2026.pdf", "receipt"),
        )

        for filename, expected_type in cases:
            with self.subTest(filename=filename):
                result = module.classify_candidate(filename)
                self.assertEqual(result.document_type, expected_type)
                self.assertEqual(result.recommendation, "likely")
                self.assertTrue(result.signals)
                self.assertEqual(
                    result.as_dict(),
                    {
                        "documentType": expected_type,
                        "recommendation": "likely",
                        "signals": list(result.signals),
                    },
                )

    def test_subject_and_sender_signals_are_advisory_and_fixed(self):
        module = classification_module()

        subject = module.classify_candidate(
            "scan.pdf", subject="Rechnung PRIVATE-SUBJECT-MARKER"
        )
        sender = module.classify_candidate(
            "scan.pdf", sender="Billing <PRIVATE-SENDER-MARKER@example.test>"
        )

        self.assertEqual((subject.document_type, subject.recommendation), ("invoice", "likely"))
        self.assertEqual((sender.document_type, sender.recommendation), ("invoice", "unclear"))
        rendered = " ".join((*subject.signals, *sender.signals))
        self.assertNotIn("PRIVATE-SUBJECT-MARKER", rendered)
        self.assertNotIn("PRIVATE-SENDER-MARKER", rendered)
        self.assertTrue(all(signal.endswith(".") for signal in subject.signals))

    def test_unknown_filename_and_token_substrings_stay_unclear(self):
        module = classification_module()

        for filename in ("scan.pdf", "dokument.xml", "invoicemail.pdf"):
            with self.subTest(filename=filename):
                result = module.classify_candidate(filename)
                self.assertEqual(result.document_type, "unknown")
                self.assertEqual(result.recommendation, "unclear")
                self.assertEqual(result.signals, ())

    def test_conflicting_document_tokens_are_explicitly_unclear(self):
        module = classification_module()

        result = module.classify_candidate("invoice-receipt.pdf")

        self.assertEqual(result.document_type, "unknown")
        self.assertEqual(result.recommendation, "unclear")
        self.assertEqual(len(result.signals), 2)

    def test_explicit_non_document_terms_are_unlikely(self):
        module = classification_module()

        result = module.classify_candidate("newsletter.pdf", subject="Datenschutz")

        self.assertEqual(result.document_type, "unknown")
        self.assertEqual(result.recommendation, "unlikely")
        self.assertTrue(result.signals)


class GmailClassificationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.gmail = GmailAdapter(FakeGmailService())

    def test_adapter_keeps_headers_transient_and_exposes_only_fixed_signals(self):
        candidates = self.gmail.candidates("Invoices")

        self.assertEqual([candidate["id"] for candidate in candidates], ["message:1", "message:2"])
        rendered_candidates = json.dumps(candidates)
        for marker in ("PRIVATE-SUBJECT-MARKER", "PRIVATE-SENDER-MARKER", "PRIVATE-DATE-MARKER"):
            self.assertNotIn(marker, rendered_candidates)
        getter = getattr(self.gmail, "candidate_classification", None)
        self.assertTrue(callable(getter), "GmailAdapter.candidate_classification is missing")
        if not callable(getter):
            return
        result = getter(candidates[0]["id"])
        self.assertEqual((result.document_type, result.recommendation), ("invoice", "likely"))
        self.assertNotIn("PRIVATE-SUBJECT-MARKER", " ".join(result.signals))
        self.assertNotIn("PRIVATE-SENDER-MARKER", " ".join(result.signals))
        self.assertNotIn("PRIVATE-DATE-MARKER", " ".join(result.signals))

    def invoke_scan(self, root):
        output = io.StringIO()
        error = io.StringIO()
        with patch.object(cli, "gmail_client", return_value=("account", self.gmail)), redirect_stdout(
            output
        ), redirect_stderr(error):
            status = cli.main(["--data-dir", str(root), "scan", "--label", "Invoices"])
        return status, output.getvalue(), error.getvalue()

    def test_scan_classifies_every_candidate_without_filtering_or_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status, output, error = self.invoke_scan(root)
            items = json.loads(output)

            self.assertEqual(status, 0, error)
            self.assertEqual([item["id"] for item in items], ["message:1", "message:2"])
            for item in items:
                self.assertTrue(
                    {"documentType", "recommendation", "signals"}.issubset(item),
                    item,
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_scan_does_not_print_or_persist_raw_header_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status, output, error = self.invoke_scan(root)
            items = json.loads(output)

            self.assertEqual(status, 0, error)
            self.assertIn("documentType", items[0])
            rendered = output + error
            for marker in ("PRIVATE-SUBJECT-MARKER", "PRIVATE-SENDER-MARKER", "PRIVATE-DATE-MARKER"):
                self.assertNotIn(marker, rendered)
            self.assertEqual(list(root.iterdir()), [])


class DesktopClassificationTests(unittest.TestCase):
    def test_service_uses_header_rules_without_expanding_safe_candidate_contract(self):
        module = classification_module()
        gmail = GmailAdapter(FakeGmailService())
        with tempfile.TemporaryDirectory() as temporary:
            service = DesktopService(
                Store(Path(temporary)),
                account="account@example.test",
                gmail=gmail,
                remote=Mock(),
            )
            candidates = service.candidates("Invoices")
            getter = getattr(service, "candidate_classification", None)
            self.assertTrue(callable(getter), "DesktopService.candidate_classification is missing")
            if not callable(getter):
                return
            result = getter(candidates[0])

            self.assertEqual(candidates[0].keys(), {"id", "filename", "size"})
            self.assertEqual((result.document_type, result.recommendation), ("invoice", "likely"))
            self.assertEqual(result.as_dict()["documentType"], "invoice")
            self.assertEqual(module.classify_candidate(candidates[0]).document_type, "invoice")

    def test_candidate_table_displays_type_and_recommendation_without_selecting(self):
        module = classification_module()
        result = module.CandidateClassification("invoice", "likely", ("Dateiname enthält einen Rechnung-Hinweis.",))
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.candidates.return_value = [
            {"id": "message:1", "filename": "Rechnung.pdf", "size": 4}
        ]
        app.service.candidate_classification.return_value = result
        app.candidates_view = FakeCandidateTree()
        app._candidate_ids = {}
        app.label = Mock()
        app.label.get.return_value = "Invoices"
        app.notice = Mock()

        app._load_candidates()

        self.assertEqual(
            app.candidates_view.rows,
            [("0", ("Rechnung.pdf", "Rechnung", "Wahrscheinlich", "4 Bytes"))],
        )
        self.assertEqual(app.candidates_view.selection_calls, 0)


if __name__ == "__main__":
    unittest.main()
