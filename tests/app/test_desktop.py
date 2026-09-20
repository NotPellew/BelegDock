import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.desktop import DesktopService
from belegdock.workflow import Store


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.gmail = Mock()
        self.gmail.labels.return_value = ["Invoices", "Other"]
        self.gmail.candidates.return_value = [
            {
                "id": "message:1",
                "message_id": "message",
                "part_id": "1",
                "filename": "receipt.pdf",
                "size": 6,
            }
        ]
        self.gmail.fetch.return_value = b"receipt"
        self.remote = Mock()
        self.remote.inventory.return_value = {"organizationId": "org", "files": []}
        self.service = DesktopService(
            Store(self.root),
            account="account@example.test",
            gmail=self.gmail,
            remote=self.remote,
        )

    def test_candidates_are_filename_and_size_only(self):
        self.assertEqual(self.service.labels(), ["Invoices", "Other"])
        self.assertEqual(
            self.service.candidates("Invoices"),
            [{"id": "message:1", "filename": "receipt.pdf", "size": 6}],
        )

    def test_stage_requires_explicit_candidate_ids(self):
        digest = self.service.stage("Invoices", ["message:1"])[0]

        self.assertEqual(len(digest), 64)
        self.gmail.fetch.assert_called_once_with(self.gmail.candidates.return_value[0])
        self.remote.upload.assert_not_called()

    def test_upload_returns_ids_through_the_same_store_orchestration(self):
        digest = self.service.stage("Invoices", ["message:1"])[0]
        self.remote.upload.return_value = {"id": "file-1", "voucherId": "voucher-1"}

        result = self.service.upload(digest)

        self.assertEqual(result["id"], "file-1")
        self.assertEqual(result["voucherId"], "voucher-1")
        self.remote.inventory.assert_called_once()


class DesktopCommandTests(unittest.TestCase):
    def test_desktop_reports_missing_tkinter_without_importing_it_at_module_load(self):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch(
            "belegdock.cli.run_desktop", side_effect=RuntimeError("tkinter is unavailable")
        ):
            status = cli.main(["desktop"])

        self.assertNotEqual(status, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("desktop", error.getvalue().lower())
        self.assertNotIn("tkinter is unavailable", error.getvalue())


if __name__ == "__main__":
    unittest.main()
