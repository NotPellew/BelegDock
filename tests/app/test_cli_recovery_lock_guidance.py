from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


def hold_upload(root, digest, entered, release):
    def uploader(_data, _filename):
        raise AssertionError("the uploader must not run while the refresh blocks")

    def refresh():
        entered.set()
        release.wait(10)
        raise RuntimeError("lock holder released")

    try:
        Store(Path(root)).upload(digest, uploader, refresh=refresh)
    except RuntimeError:
        pass


class RecoveryLockGuidanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def hold_lock(self):
        entered, release = threading.Event(), threading.Event()
        worker = threading.Thread(target=hold_upload, args=(self.root, self.digest, entered, release))
        worker.start()
        self.assertTrue(entered.wait(10))
        self.addCleanup(release_lock, worker, release)

    def test_second_upload_reports_an_active_operation_and_does_not_retry(self):
        self.hold_lock()
        remote = Mock()

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke("upload", self.digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "staged")
        self.assertIn("active", error)
        self.assertIn("wait", error)
        self.assertNotIn("correct the problem and retry", error)
        self.assertNotIn(f"belegdock recover-upload {self.digest}", error)
        self.assertNotIn("belegdock reconcile", error)
        self.assertNotIn(f"belegdock upload {self.digest}", error)

    def test_recover_upload_reports_an_active_operation(self):
        self.hold_lock()

        status, output, error = self.invoke("recover-upload", self.digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "staged")
        self.assertIn("active", error)
        self.assertNotIn("only an interrupted upload", error)

    def test_reconcile_does_not_offer_an_explicit_upload(self):
        self.hold_lock()
        remote = Mock()

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke(
                "reconcile", self.digest, "--file-id", "file-1", "--voucher-id", "voucher-1"
            )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "staged")
        self.assertIn("wait", error)
        self.assertNotIn(f"belegdock upload {self.digest}", error)


def release_lock(worker, release):
    release.set()
    worker.join(10)
    if worker.is_alive():
        raise AssertionError("lock holder thread did not finish")


if __name__ == "__main__":
    unittest.main()
