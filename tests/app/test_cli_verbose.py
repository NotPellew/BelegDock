from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli


class VerboseCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments, env=None):
        output, error = StringIO(), StringIO()
        current_env = os.environ.copy()
        if env is not None:
            current_env.update(env)
        with patch.dict(os.environ, current_env, clear=True):
            with redirect_stdout(output), redirect_stderr(error):
                status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_failure_without_verbose_prints_only_standard_message(self):
        adapter = Mock()
        adapter.candidates.side_effect = ValueError("Gmail label was not found")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("scan", "--label", "Rechnungen")

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertEqual(
            error.strip(),
            "Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher.",
        )
        self.assertNotIn("Fehlerdetails", error)
        self.assertNotIn("Gmail label was not found", error)

    def test_failure_with_verbose_flag_prints_exception_details(self):
        adapter = Mock()
        adapter.candidates.side_effect = ValueError("Gmail label was not found")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("--verbose", "scan", "--label", "Rechnungen")

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn(
            "Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher.",
            error,
        )
        self.assertIn("Fehlerdetails: ValueError: Gmail label was not found", error)

    def test_failure_with_verbose_env_var_prints_exception_details(self):
        adapter = Mock()
        adapter.candidates.side_effect = ValueError("Gmail label was not found")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("scan", "--label", "Rechnungen", env={"BELEGDOCK_VERBOSE": "1"})

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn(
            "Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher.",
            error,
        )
        self.assertIn("Fehlerdetails: ValueError: Gmail label was not found", error)

    def test_failure_with_short_v_flag_prints_exception_details(self):
        adapter = Mock()
        adapter.candidates.side_effect = ValueError("Gmail label was not found")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("-v", "scan", "--label", "Rechnungen")

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn(
            "Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher.",
            error,
        )
        self.assertIn("Fehlerdetails: ValueError: Gmail label was not found", error)

    def test_verbose_output_never_exposes_stored_secrets(self):
        secret_token = "secret-token-xyz-98765"
        with patch.object(cli.accounts, "load_secret", return_value=secret_token):
            with patch.object(
                cli,
                "refresh_remote_inventory",
                side_effect=RuntimeError(f"Lexware request failed with Bearer {secret_token}"),
            ):
                status, output, error = self.invoke("--verbose", "refresh")

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertNotIn(secret_token, error)
        self.assertNotIn(secret_token, output)
        self.assertIn("***", error)
        self.assertIn("Fehlerdetails: RuntimeError:", error)

    def test_verbose_failure_preserves_exit_code_and_stdout_contract(self):
        adapter = Mock()
        adapter.candidates.side_effect = RuntimeError("network connection dropped")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("--verbose", "scan", "--label", "Rechnungen")

        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("Fehlerdetails: RuntimeError: network connection dropped", error)

    def test_verbose_surfaces_root_causes_across_commands(self):
        # Test refresh command failure
        with patch.object(cli, "lexware_client", return_value=Mock()), patch.object(
            cli,
            "refresh_remote_inventory",
            side_effect=RuntimeError("Lexware request rate limited"),
        ):
            status, output, error = self.invoke("--verbose", "refresh")
            self.assertEqual(status, 1)
            self.assertIn("Fehlerdetails: RuntimeError: Lexware request rate limited", error)

        # Test stage command failure
        adapter = Mock()
        adapter.candidates.return_value = [{"id": "msg1:part1", "message_id": "msg1", "part_id": "part1", "filename": "doc.pdf"}]
        adapter.fetch.side_effect = ValueError("attachment data is invalid")
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke(
                "--verbose", "stage", "--label", "Rechnungen", "--select", "msg1:part1"
            )
            self.assertEqual(status, 1)
            self.assertIn("Fehlerdetails: ValueError: attachment data is invalid", error)
