import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli


DIGEST = "a" * 64


class GermanCliFinalGuidanceTests(unittest.TestCase):
    def test_invalid_subcommand_does_not_expose_internal_argument_name(self):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch.object(cli, "dispatch") as dispatch:
            status = cli.main(["invalid-command"])

        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Argument Befehl", error.getvalue())
        self.assertNotIn("Argument command", error.getvalue())
        dispatch.assert_not_called()

    def invoke_recovery_failure(self, arguments, document_status):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch.object(
            cli, "dispatch", side_effect=RuntimeError("private failure")
        ), patch.object(cli, "document_status", return_value=document_status):
            status = cli.main(["--data-dir", "/tmp/belegdock-test-data", *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_recover_upload_fallback_prints_executable_documents_command(self):
        status, output, error = self.invoke_recovery_failure(
            ["recover-upload", DIGEST], ("staged", True)
        )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("Prüfe 'belegdock documents'.", error)

    def test_reconcile_fallback_prints_executable_documents_command(self):
        status, output, error = self.invoke_recovery_failure(
            ["reconcile", DIGEST, "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
            ("uploaded", True),
        )

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("Prüfe 'belegdock documents'.", error)


if __name__ == "__main__":
    unittest.main()
