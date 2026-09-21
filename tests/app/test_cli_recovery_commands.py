from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryCommandCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def stage_document(self):
        return Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")

    def make_remote(self):
        remote = Mock()
        remote.inventory.return_value = {"organizationId": "org-1", "files": []}
        remote.hash_file.side_effect = AssertionError("an empty inventory must not hash files")
        return remote

    def test_uncertain_upload_prints_reconciliation_command_without_recovery(self):
        digest = self.stage_document()
        remote = self.make_remote()
        remote.upload.side_effect = ConnectionError("private provider response")

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertNotIn(f"belegdock recover-upload {digest}", error)
        self.assertIn(
            f"belegdock reconcile {digest} --file-id FILE_ID --voucher-id VOUCHER_ID", error
        )
        self.assertNotIn("private provider response", error)

    def test_failed_reconciliation_prints_the_hash_specific_command(self):
        digest = self.stage_document()
        store = Store(self.root)
        with self.assertRaises(RuntimeError):
            store.upload(digest, lambda _data, _filename: (_ for _ in ()).throw(ConnectionError()))
        remote = self.make_remote()
        remote.verify_existing.return_value = b"other bytes"

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke(
                "reconcile", digest, "--file-id", "file-1", "--voucher-id", "voucher-1"
            )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertIn(
            f"belegdock reconcile {digest} --file-id FILE_ID --voucher-id VOUCHER_ID", error
        )

    def test_live_upload_refuses_recovery_and_names_command_for_after_it_stops(self):
        digest = self.stage_document()
        store = Store(self.root)
        entered, release = threading.Event(), threading.Event()

        def upload():
            def uploader(_data, _filename):
                entered.set()
                release.wait(5)
                return {"id": "file-1", "voucherId": "voucher-1"}

            store.upload(digest, uploader)

        worker = threading.Thread(target=upload)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            status, output, error = self.invoke("recover-upload", digest)
        finally:
            release.set()
            worker.join(5)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertFalse(worker.is_alive())
        self.assertIn("aktives Senden", error)
        self.assertIn(f"belegdock recover-upload {digest}", error)


if __name__ == "__main__":
    unittest.main()
