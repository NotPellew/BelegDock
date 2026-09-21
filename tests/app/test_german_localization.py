import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli, desktop


class GermanLocalizationTests(unittest.TestCase):
    def test_desktop_copy_is_german_and_preserves_recovery_boundaries(self):
        self.assertEqual(
            desktop.PREPARE_HELPER,
            "Ausgewählte Dateien werden lokal gespeichert und nicht an Lexware gesendet.",
        )
        self.assertEqual(desktop.format_size(0), "0 Bytes")
        self.assertEqual(desktop.format_size(1536), "1,5 KiB")
        self.assertEqual(desktop.status_label("staged"), "Vorbereitet")
        self.assertEqual(desktop.status_label("uploaded"), "Gesendet")
        self.assertEqual(
            desktop.status_label("already_present"),
            "Bereits in Lexware vorhanden",
        )
        self.assertEqual(
            desktop.document_action_state("uncertain", "ok")[2],
            "Ergebnis unklar; verwende die CLI-Befehle zur Wiederherstellung und Abstimmung.",
        )

    def test_help_localizes_prose_but_preserves_commands_and_flags(self):
        output = StringIO()
        with redirect_stdout(output):
            status = cli.main(["--help"])

        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("Schnellstart:", text)
        self.assertIn("Wiederherstellung nach einem unterbrochenen Sendevorgang:", text)
        self.assertIn("belegdock stage --label LABEL --select MESSAGE_ID:PART_ID", text)
        self.assertIn("belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID", text)
        self.assertNotIn("quick start:", text)
        self.assertNotIn("early-stage", text)

    def test_desktop_unavailable_error_is_german(self):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch(
            "belegdock.cli.run_desktop",
            side_effect=desktop.DesktopUnavailableError("private import detail"),
        ):
            status = cli.main(["desktop"])

        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Desktop-Oberfläche ist nicht verfügbar", error.getvalue())
        self.assertNotIn("private import detail", error.getvalue())


if __name__ == "__main__":
    unittest.main()
