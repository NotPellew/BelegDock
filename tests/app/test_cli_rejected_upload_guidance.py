from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from belegdock import cli
from belegdock.workflow import DocumentRejected, Store


class RejectedUploadGuidanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def rejected_document(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(DocumentRejected):
            store.upload(digest, lambda _data, _filename: (_ for _ in ()).throw(DocumentRejected(406)))
        return digest

    def test_rejected_document_does_not_offer_retry_after_client_setup_failure(self):
        digest = self.rejected_document()

        with patch.object(cli, "lexware_client", side_effect=RuntimeError("private client failure")):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "rejected")
        self.assertIn("Dokument wurde abgelehnt; korrigiere es und bereite neue Bytes vor.", error)
        self.assertNotIn("retry", error.lower())
        self.assertNotIn("private client failure", error)


if __name__ == "__main__":
    unittest.main()
