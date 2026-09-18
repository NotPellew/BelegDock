from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from belegdock.workflow import Store


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def test_windows_staging_does_not_open_directory_as_file(self):
        original_open = os.open

        def windows_open(path, flags, *args, **kwargs):
            if Path(path) == self.root / "blobs":
                raise PermissionError("Windows cannot open a directory as a file")
            return original_open(path, flags, *args, **kwargs)

        with patch("sys.platform", "win32"), patch("os.open", side_effect=windows_open):
            digest = self.store.stage("a", "m", "p", "file.pdf", b"bytes")
        self.assertEqual((self.root / "blobs" / digest).read_bytes(), b"bytes")

    def test_corrupt_existing_blob_cannot_be_reused_for_new_occurrence(self):
        digest = self.store.stage("a", "m", "p", "file.pdf", b"bytes")
        (self.root / "blobs" / digest).write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "integrity|hash|corrupt"):
            self.store.stage("a", "m2", "p", "file.pdf", b"bytes")
        self.assertEqual(len(self.store.occurrences(digest)), 1)

    def test_atomic_write_failure_does_not_record_document(self):
        with patch("os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.store.stage("a", "m", "p", "file.pdf", b"bytes")
        self.assertEqual(self.store.list_documents(), [])
        self.assertEqual(list((self.root / "blobs").iterdir()), [])

    def test_simultaneous_uploads_call_remote_only_once(self):
        digest = self.store.stage("a", "m", "p", "file.pdf", b"bytes")
        entered, release = threading.Event(), threading.Event()
        calls = []

        def uploader(data, filename):
            calls.append(data)
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test did not release uploader")
            return {"id": "file", "voucherId": "voucher"}

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.store.upload, digest, uploader)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(RuntimeError, "uncertain|reconcile"):
                    Store(self.root).upload(digest, uploader)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)["id"], "file")
        self.assertEqual(calls, [b"bytes"])
