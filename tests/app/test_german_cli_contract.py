import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli


DIGEST = "a" * 64


class GermanCliContractTests(unittest.TestCase):
    def capture_help(self, arguments):
        output = StringIO()
        with redirect_stdout(output):
            status = cli.main([*arguments, "--help"])
        return status, output.getvalue()

    def test_top_level_and_subcommand_help_are_german(self):
        for arguments in ([], ["stage"], ["desktop"]):
            with self.subTest(arguments=arguments):
                status, output = self.capture_help(arguments)

                self.assertEqual(status, 0)
                self.assertIn("Aufruf:", output)
                self.assertIn("Optionen:", output)
                self.assertIn("Diese Hilfe anzeigen und beenden", output)
                self.assertNotIn("usage:", output)
                self.assertNotIn("options:", output)
                self.assertNotIn("show this help message and exit", output)

    def invoke_failure(self, arguments, document_status):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch.object(
            cli, "dispatch", side_effect=RuntimeError("private failure")
        ), patch.object(cli, "document_status", return_value=document_status):
            status = cli.main(["--data-dir", "/tmp/belegdock-test-data", *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_recovery_guidance_is_german_and_preserves_commands(self):
        cases = (
            (["upload", DIGEST], ("uncertain", True), "Sendeergebnis"),
            (["recover-upload", DIGEST], ("uncertain", True), "Wiederherstellung"),
            (
                ["reconcile", DIGEST, "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
                ("uncertain", True),
                "Abstimmung",
            ),
        )

        for arguments, document_status, expected_word in cases:
            with self.subTest(arguments=arguments):
                status, output, error = self.invoke_failure(arguments, document_status)

                self.assertEqual(status, 1)
                self.assertEqual(output, "")
                self.assertIn(expected_word, error)
                self.assertIn("nicht erneut", error)
                self.assertNotIn("Upload outcome", error)
                self.assertNotIn("Recovery is not needed", error)
                self.assertNotIn("Reconciliation failed", error)

        self.assertIn(f"belegdock reconcile {DIGEST} --file-id FILE_ID --voucher-id VOUCHER_ID", error)


if __name__ == "__main__":
    unittest.main()
