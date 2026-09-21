from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryStateUnavailableCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def stage_uncertain_document(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(RuntimeError):
            Store(self.root).upload(
                digest,
                lambda _data, _filename: (_ for _ in ()).throw(ConnectionError("private provider response")),
            )
        return digest

    def test_document_status_marks_store_errors_as_unavailable(self):
        with patch.object(cli, "Store", side_effect=OSError("private state failure")):
            self.assertEqual(cli.document_status(self.root, "a" * 64), (None, False))

    def test_uncertain_upload_does_not_say_to_retry_when_status_lookup_fails(self):
        digest = self.stage_uncertain_document()

        with patch.object(cli, "lexware_client", return_value=Mock()), patch.object(
            cli, "document_status", return_value=(None, False)
        ):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertIn(f"Sendeergebnis für {digest} konnte nicht geprüft werden; nicht erneut senden.", error)
        self.assertNotIn("correct the problem and retry", error)


if __name__ == "__main__":
    unittest.main()
