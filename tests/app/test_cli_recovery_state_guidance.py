from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


def exit_during_upload(root, digest):
    Store(Path(root)).upload(digest, lambda _data, _filename: os._exit(0))


class RecoveryStateGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def interrupted_document(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        worker = multiprocessing.Process(target=exit_during_upload, args=(self.root, digest))
        worker.start()
        worker.join(10)
        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uploading")
        return digest

    def test_repeated_recovery_directs_an_uncertain_document_to_reconciliation(self):
        digest = self.interrupted_document()

        status, output, error = self.invoke("recover-upload", digest)
        self.assertEqual(status, 0, error)
        self.assertIn('"status": "uncertain"', output)

        status, output, error = self.invoke("recover-upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertNotIn("active upload", error)
        self.assertIn(
            f"belegdock reconcile {digest} --file-id FILE_ID --voucher-id VOUCHER_ID", error
        )

    def test_reconcile_staged_document_directs_an_explicit_upload(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        remote = Mock()

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke(
                "reconcile", digest, "--file-id", "file-1", "--voucher-id", "voucher-1"
            )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "staged")
        remote.verify_existing.assert_not_called()
        self.assertNotIn("remains uncertain", error)
        self.assertIn(f"belegdock upload {digest}", error)


if __name__ == "__main__":
    unittest.main()
