from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from belegdock import cli
from belegdock.workflow import Store


class UploadedUploadGuidanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_uploaded_document_does_not_offer_retry_after_client_setup_failure(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        store.upload(
            digest,
            lambda _data, _filename: {"id": "file-1", "voucherId": "voucher-1"},
        )

        with patch.object(cli, "lexware_client", side_effect=RuntimeError("private client failure")):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(store.list_documents(digest)[0]["status"], "uploaded")
        self.assertIn(
            f"Upload für {digest} ist bereits gespeichert; nicht erneut senden. Führe "+
            "'belegdock documents' aus, um den lokalen Zustand zu prüfen.",
            error,
        )
        self.assertNotIn("private client failure", error)


if __name__ == "__main__":
    unittest.main()
