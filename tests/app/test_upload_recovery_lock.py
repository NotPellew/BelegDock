import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from belegdock.workflow import Store


def hold_upload(root, digest, entered, release):
    def uploader(data, filename):
        entered.set()
        release.wait(10)
        return {"id": "file-1", "voucherId": "voucher-1"}

    Store(Path(root)).upload(digest, uploader)


def exit_during_upload(root, digest):
    def uploader(data, filename):
        os._exit(0)

    Store(Path(root)).upload(digest, uploader)


class UploadRecoveryLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")

    def test_recovery_refuses_a_live_upload_owned_by_another_process(self):
        entered, release = multiprocessing.Event(), multiprocessing.Event()
        worker = multiprocessing.Process(target=hold_upload, args=(self.root, self.digest, entered, release))
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            try:
                Store(self.root).recover_upload(self.digest)
            except RuntimeError as error:
                message = str(error)
            except AttributeError:
                message = "not implemented"
            else:
                message = "recovery unexpectedly succeeded"
            self.assertRegex(message, "active|running")
            self.assertEqual(Store(self.root).list_documents()[0]["status"], "uploading")
        finally:
            release.set()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(10)

    def test_recovery_moves_only_a_crash_left_upload_to_uncertain(self):
        worker = multiprocessing.Process(target=exit_during_upload, args=(self.root, self.digest))
        worker.start()
        worker.join(10)
        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uploading")

        try:
            result = Store(self.root).recover_upload(self.digest)
        except AttributeError:
            result = {"status": "not implemented"}

        self.assertEqual(result, {"status": "uncertain"})
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
