from contextlib import redirect_stderr, redirect_stdout
import importlib
import importlib.util
import json
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.desktop import DesktopApplication, DesktopService
from belegdock.workflow import Store


def classification_module():
    spec = importlib.util.find_spec("belegdock.classification")
    if spec is None:
        raise AssertionError("belegdock.classification is missing")
    return importlib.import_module("belegdock.classification")


class CandidateTree:
    def __init__(self):
        self.rows = []

    def get_children(self):
        return tuple(row[0] for row in self.rows)

    def delete(self, row):
        self.rows = [item for item in self.rows if item[0] != row]

    def insert(self, _parent, _index, values):
        row = str(len(self.rows))
        self.rows.append((row, values))
        return row


class ScanClassifierReviewTests(unittest.TestCase):
    def test_scan_uses_an_explicit_public_candidate_allowlist(self):
        module = classification_module()

        class Gmail:
            def candidates(self, _label):
                return [
                    {
                        "id": "message:1",
                        "message_id": "message",
                        "part_id": "1",
                        "filename": "scan.pdf",
                        "size": 4,
                        "attachment_id": "PRIVATE-ATTACHMENT-ID",
                        "inline_data": "PRIVATE-INLINE-DATA",
                        "private_header": "PRIVATE-HEADER-CONTEXT",
                    }
                ]

            def candidate_classification(self, _candidate_id):
                return module.CandidateClassification("unknown", "unclear", ())

        output = StringIO()
        error = StringIO()
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cli, "gmail_client", return_value=("account", Gmail())
        ), redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", temporary, "scan", "--label", "Invoices"])

        self.assertEqual(status, 0, error.getvalue())
        self.assertEqual(
            list(json.loads(output.getvalue())[0]),
            [
                "id",
                "message_id",
                "part_id",
                "filename",
                "size",
                "documentType",
                "recommendation",
                "signals",
            ],
        )
        self.assertNotIn("PRIVATE-", output.getvalue() + error.getvalue())
        self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_credit_card_sender_is_not_treated_as_a_credit_note(self):
        module = classification_module()

        result = module.classify_candidate(
            "statement.pdf", sender="Credit Card Service <cards@example.test>"
        )

        self.assertEqual(result.document_type, "unknown")
        self.assertEqual(result.recommendation, "unclear")
        self.assertEqual(result.signals, ())

    def test_non_document_signal_is_accurate_for_all_fixed_terms(self):
        module = classification_module()

        result = module.classify_candidate("agb.pdf", subject="Datenschutz")

        self.assertEqual(result.document_type, "unknown")
        self.assertEqual(result.recommendation, "unlikely")
        self.assertEqual(
            result.signals,
            ("Hinweis auf Inhalte, die üblicherweise kein Beleg sind.",),
        )

    def test_desktop_keeps_candidate_when_optional_classification_is_stale(self):
        classification_module()

        class Gmail:
            def candidates(self, _label):
                return [
                    {
                        "id": "message:1",
                        "message_id": "message",
                        "part_id": "1",
                        "filename": "Rechnung.pdf",
                        "size": 4,
                    }
                ]

            def candidate_classification(self, _candidate_id):
                raise ValueError("PRIVATE-STALE-HEADER-CONTEXT")

        with tempfile.TemporaryDirectory() as temporary:
            service = DesktopService(
                Store(Path(temporary)),
                account="account@example.test",
                gmail=Gmail(),
                remote=Mock(),
            )
            app = DesktopApplication.__new__(DesktopApplication)
            app.service = service
            app.candidates_view = CandidateTree()
            app._candidate_ids = {}
            app.label = Mock()
            app.label.get.return_value = "Invoices"
            app.notice = Mock()

            try:
                app._load_candidates()
            except Exception as error:
                self.fail(f"optional classification escaped the safe UI boundary: {type(error).__name__}")

            self.assertEqual(
                app.candidates_view.rows,
                [("0", ("Rechnung.pdf", "Rechnung", "Wahrscheinlich", "4 Bytes"))],
            )
            self.assertNotIn("PRIVATE-STALE-HEADER-CONTEXT", app.notice.set.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
