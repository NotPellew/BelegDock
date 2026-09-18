import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from belegdock.workflow import Store


def exit_during_reconciliation(root, digest):
    Store(Path(root)).reconcile(digest, "file-1", "voucher-1", lambda file_id, voucher_id: os._exit(0))


class ReconciliationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)
        self.digest = self.store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(RuntimeError):
            self.store.upload(self.digest, lambda data, filename: (_ for _ in ()).throw(ConnectionError("timeout")))

    def test_reconciliation_crash_leaves_the_document_uncertain(self):
        worker = multiprocessing.Process(target=exit_during_reconciliation, args=(self.root, self.digest))
        worker.start()
        worker.join(10)

        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")

    def test_invalid_hash_cannot_create_a_lock_outside_data_directory(self):
        (self.root / ".x").mkdir()
        escaped = self.root.parent / "escaped.upload.lock"
        escaped.unlink(missing_ok=True)

        with self.assertRaisesRegex(ValueError, "hash|digest"):
            self.store.upload("x/../../escaped", lambda data, filename: {"id": "file", "voucherId": "voucher"})

        self.assertFalse(escaped.exists())


if __name__ == "__main__":
    unittest.main()
