from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryGuidanceReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_failed_preflight_remains_staged_and_is_retryable(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        remote = Mock()
        remote.inventory.side_effect = ConnectionError("private remote error")

        with patch.object(cli, "lexware_client", return_value=remote):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "staged")
        remote.upload.assert_not_called()
        self.assertIn("vor der Übertragung", error)
        self.assertIn("erneut", error)
        self.assertNotIn("uncertain", error.lower())
        self.assertNotIn("recover-upload", error)
        self.assertNotIn("reconcile", error)
        self.assertNotIn("private remote error", error)

    def test_invalid_hash_never_reaches_recovery_command_output(self):
        invalid_hash = "\x1b[31mnot-a-hash"
        expected = "Ungültiger Dokument-Hash; führe 'belegdock documents' aus und kopiere einen SHA-256-Hash.\n"
        commands = (
            ("upload", invalid_hash),
            ("recover-upload", invalid_hash),
            ("reconcile", invalid_hash, "--file-id", "file-1", "--voucher-id", "voucher-1"),
        )

        for command in commands:
            with self.subTest(command=command[0]), patch.object(cli, "lexware_client", return_value=Mock()):
                status, output, error = self.invoke(*command)

            self.assertEqual(status, 1)
            self.assertEqual(output, "")
            self.assertEqual(error, expected)
            self.assertNotIn(invalid_hash, error)
            self.assertNotIn("\x1b", error)


if __name__ == "__main__":
    unittest.main()
