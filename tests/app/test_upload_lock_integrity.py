import multiprocessing
from pathlib import Path
import tempfile
import unittest

from belegdock.workflow import Store


def hold_upload_with_lock_contents(root, digest, entered, release):
    def uploader(data, filename):
        entered.set()
        release.wait(10)
        return {"id": "file-1", "voucherId": "voucher-1"}

    Store(Path(root)).upload(digest, uploader)


class UploadLockIntegrityTests(unittest.TestCase):
    def test_contender_does_not_mutate_a_lock_held_by_an_active_upload(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        digest = Store(root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        lock_path = root / f".{digest}.upload.lock"
        lock_path.write_bytes(b"held-state")
        entered, release = multiprocessing.Event(), multiprocessing.Event()
        worker = multiprocessing.Process(
            target=hold_upload_with_lock_contents, args=(root, digest, entered, release)
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaisesRegex(RuntimeError, "active|running"):
                Store(root).recover_upload(digest)
        finally:
            release.set()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
        self.assertEqual(lock_path.read_bytes(), b"held-state")


if __name__ == "__main__":
    unittest.main()
