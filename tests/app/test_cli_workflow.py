from contextlib import redirect_stderr, redirect_stdout
import json
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.gmail = Mock()
        self.gmail.candidates.return_value = [
            {"id": "m:1", "message_id": "m", "part_id": "1", "filename": "one.pdf", "size": 4},
            {"id": "m:2", "message_id": "m", "part_id": "2", "filename": "two.xml", "size": 4},
        ]
        self.gmail.fetch.return_value = b"%PDF"

    def invoke(self, *arguments):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, out.getvalue(), err.getvalue()

    def test_scan_lists_candidates_without_staging_or_upload(self):
        with patch.object(cli, "gmail_client", return_value=("test-account", self.gmail)):
            status, output, error = self.invoke("scan", "--label", "Test")
        self.assertEqual(status, 0, error)
        self.assertEqual([item["id"] for item in json.loads(output)], ["m:1", "m:2"])
        self.gmail.fetch.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_stage_fetches_only_explicit_selection_then_upload_is_separate(self):
        remote = Mock()
        remote.upload.return_value = {"id": "file", "voucherId": "voucher"}
        with patch.object(cli, "gmail_client", return_value=("test-account", self.gmail)), patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke("stage", "--label", "Test", "--select", "m:1")
            self.assertEqual(status, 0, error)
            digest = json.loads(output)[0]
            self.gmail.fetch.assert_called_once_with(self.gmail.candidates.return_value[0])
            remote.upload.assert_not_called()
            status, output, error = self.invoke("upload", digest)
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output)["voucherId"], "voucher")
        remote.upload.assert_called_once_with(b"%PDF", "one.pdf")

    def test_unknown_selection_rejects_whole_request_before_fetch(self):
        with patch.object(cli, "gmail_client", return_value=("test-account", self.gmail)):
            status, output, error = self.invoke("stage", "--label", "Test", "--select", "m:1", "--select", "missing")
        self.assertNotEqual(status, 0)
        self.assertIn("selection", error.lower())
        self.gmail.fetch.assert_not_called()

    def test_documents_lists_local_state_without_connection(self):
        with patch.object(cli, "gmail_client", side_effect=AssertionError("no network")), patch.object(cli, "lexware_client", side_effect=AssertionError("no network")):
            status, output, error = self.invoke("documents")
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output), [])

    def test_service_error_hides_response_contents(self):
        self.gmail.candidates.side_effect = RuntimeError("private-document-content")
        with patch.object(cli, "gmail_client", return_value=("test-account", self.gmail)):
            status, output, error = self.invoke("scan", "--label", "Test")
        self.assertNotEqual(status, 0)
        self.assertNotIn("private-document-content", output + error)
        self.assertIn("failed", error.lower())
