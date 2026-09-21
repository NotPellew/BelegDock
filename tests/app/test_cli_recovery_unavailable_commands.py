from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryUnavailableCommandsCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def stage_uncertain_document(self):
        digest = Store(self.root).stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(RuntimeError):
            Store(self.root).upload(
                digest,
                lambda _data, _filename: (_ for _ in ()).throw(ConnectionError("private provider response")),
            )
        return digest

    def test_recovery_does_not_suggest_more_commands_when_state_lookup_fails(self):
        digest = self.stage_uncertain_document()

        with patch.object(cli, "document_status", return_value=(None, False)):
            status, output, error = self.invoke("recover-upload", digest)

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertIn(f"Recovery state could not be checked for {digest}; do not retry the upload.", error)
        self.assertNotIn("only an interrupted upload", error)

    def test_reconciliation_does_not_suggest_more_commands_when_state_lookup_fails(self):
        digest = self.stage_uncertain_document()
        remote = Mock()
        remote.verify_existing.return_value = b"other bytes"

        with patch.object(cli, "lexware_client", return_value=remote), patch.object(
            cli, "document_status", return_value=(None, False)
        ):
            status, output, error = self.invoke(
                "reconcile", digest, "--file-id", "file-1", "--voucher-id", "voucher-1"
            )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(Store(self.root).list_documents()[0]["status"], "uncertain")
        self.assertIn(f"Recovery state could not be checked for {digest}; do not retry the upload.", error)
        self.assertNotIn("only an uncertain upload", error)


if __name__ == "__main__":
    unittest.main()
