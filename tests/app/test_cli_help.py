import unittest
from contextlib import redirect_stdout
from io import StringIO

from belegdock.cli import main


class CliHelpQuickStartTests(unittest.TestCase):
    def help_text(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--help"])
        return status, output.getvalue()

    def test_help_shows_the_normal_sequence(self):
        status, output = self.help_text()

        self.assertEqual(status, 0)
        self.assertIn("quick start:", output)
        for line in (
            "belegdock login-gmail --client CLIENT_JSON",
            "belegdock login-lexware",
            "belegdock scan --label LABEL",
            "belegdock stage --label LABEL --select MESSAGE_ID:PART_ID",
            "belegdock documents",
            "belegdock refresh",
            "belegdock upload SHA256_HASH",
        ):
            self.assertIn(line, output)

    def test_help_shows_the_recovery_commands_for_uncertain_uploads(self):
        status, output = self.help_text()

        self.assertEqual(status, 0)
        self.assertIn("recovery after an interrupted upload:", output)
        self.assertIn("belegdock recover-upload SHA256_HASH", output)
        self.assertIn(
            "belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID",
            output,
        )


if __name__ == "__main__":
    unittest.main()
