from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryIntegrityGuidanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def corrupt_uncertain_document(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(RuntimeError):
            Store(self.root).upload(
                digest,
                lambda _data, _filename: (_ for _ in ()).throw(ConnectionError("private provider response")),
            )
        (self.root / "blobs" / digest).write_bytes(b"corrupt")
        return digest

    def assert_restore_guidance(self, digest, error):
        document = Store(self.root).list_documents()[0]
        self.assertEqual(document["status"], "uncertain")
        self.assertEqual(document["localIntegrity"], "corrupt")
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )
        self.assertNotIn(f"belegdock reconcile {digest}", error)

    def test_corrupt_uncertain_upload_prints_restore_guidance_not_reconciliation(self):
        digest = self.corrupt_uncertain_document()

        with patch.object(cli, "lexware_client", return_value=Mock()):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assert_restore_guidance(digest, error)

    def test_corrupt_uncertain_recovery_prints_restore_guidance_not_reconciliation(self):
        digest = self.corrupt_uncertain_document()

        status, output, error = self.invoke("recover-upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assert_restore_guidance(digest, error)


if __name__ == "__main__":
    unittest.main()
