from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from belegdock import cli
from belegdock.workflow import Store


def exit_during_upload(root, digest):
    Store(Path(root)).upload(digest, lambda _data, _filename: os._exit(0))


class RecoverUploadIntegrityCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_corrupt_interrupted_upload_refuses_recovery(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        worker = multiprocessing.Process(target=exit_during_upload, args=(self.root, digest))
        worker.start()
        worker.join(10)
        self.assertEqual(worker.exitcode, 0)
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uploading")
        (self.root / "blobs" / digest).write_bytes(b"corrupt")

        status, output, error = self.invoke("recover-upload", digest)

        document = Store(self.root).list_documents()[0]
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(document["status"], "uploading")
        self.assertEqual(document["localIntegrity"], "corrupt")
        self.assertIn(
            "Local data is unavailable; restore state.sqlite3 and blobs from a consistent backup.",
            error,
        )


if __name__ == "__main__":
    unittest.main()
