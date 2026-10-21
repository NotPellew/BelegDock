import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import httplib2
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from belegdock import accounts, cli, desktop
from belegdock.workflow import RemoteAuthError
from setup_test_support import require, require_module
from test_desktop_setup import SetupViewHarness
from test_desktop_startup_routing import StartupHarness
from test_setup_service import GmailHarness

ROOT = Path(__file__).resolve().parents[2]
TESTER_HINT = "Testnutzer"


def http_error(status):
    content = json.dumps({"error": {"code": status, "errors": []}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), content)


class ExpiredStartupHarness(StartupHarness):
    def __init__(self, failures, **options):
        super().__init__(**options)
        self.failures = list(failures)

    def _gmail(self):
        self.events.append("gmail_client")
        if self.failures:
            raise self.failures.pop(0)
        return "tester@example.test", Mock(name="gmail")


class ExpiredStartupTests(unittest.TestCase):
    def test_rejected_gmail_token_opens_setup_marked_expired_then_the_main_view(self):
        failures = [
            RefreshError("invalid_grant: Token has been expired or revoked."),
            http_error(401),
            RemoteAuthError(401),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                harness = ExpiredStartupHarness([failure])
                with patch.object(accounts, "save_secret") as save:
                    harness.run()

                self.assertEqual(
                    harness.events,
                    ["store", "gmail_client", "setup", "gmail_client", "lexware_client", "main"],
                )
                state = harness.run_setup.call_args.args[-1]
                self.assertEqual((state.store_available, state.gmail, state.lexware), (True, "expired", "present"))
                self.assertIs(harness.create_application.call_args.kwargs["root"], harness.root)
                save.assert_not_called()

    def test_closing_the_expired_setup_exits_without_the_main_view(self):
        harness = ExpiredStartupHarness([RefreshError("invalid_grant")], setup_result=None)

        status, messages = harness.run("desktop_main")

        self.assertEqual((status, messages), (0, []))
        harness.create_application.assert_not_called()

    def test_unrelated_gmail_failures_keep_the_generic_message_without_setup(self):
        harness = ExpiredStartupHarness([OSError("offline /home/private")])

        status, messages = harness.run("desktop_main")

        self.assertEqual(status, 1)
        harness.run_setup.assert_not_called()
        self.assertEqual(messages, [desktop.DESKTOP_START_FAILED_MESSAGE])

    def test_a_second_rejection_after_setup_closes_the_window_without_looping(self):
        harness = ExpiredStartupHarness([RefreshError("invalid_grant"), RefreshError("invalid_grant")])

        status, messages = harness.run("desktop_main")

        self.assertEqual(status, 1)
        harness.run_setup.assert_called_once()
        harness.root.destroy.assert_called_once_with()
        self.assertEqual(messages, [desktop.DESKTOP_START_FAILED_MESSAGE])

    def test_start_failure_message_has_no_terminal_instructions(self):
        for word in ("login-gmail", "login-lexware", "belegdock", "Terminal", "Befehl"):
            self.assertNotIn(word, desktop.DESKTOP_START_FAILED_MESSAGE)

    def test_expired_step_is_marked_and_lexware_stays_connected(self):
        harness = SetupViewHarness("expired", "present")

        self.assertEqual(harness.view.gmail_state.status, "error")
        self.assertIn("Gmail-Anmeldung abgelaufen", harness.view.gmail_status.get())
        self.assertIn("erneut verbinden", harness.view.gmail_status.get())
        self.assertEqual(harness.view.lexware_state.status, "connected")
        self.assertFalse(harness.view.can_continue)
        harness.connect_gmail()
        harness.dispatch.complete_next()
        self.assertTrue(harness.view.can_continue)


class TesterHintTests(unittest.TestCase):
    def test_hint_is_shown_while_connecting_after_timeout_and_after_cancel(self):
        harness = SetupViewHarness()
        harness.connect_gmail()
        self.assertIn(TESTER_HINT, harness.view.gmail_status.get())
        self.assertIn("Zugriff blockiert", harness.view.gmail_status.get())
        harness.view.cancel()
        self.assertIn(TESTER_HINT, harness.view.gmail_status.get())
        harness.dispatch.complete_next()
        harness.services.authorize_gmail.side_effect = harness.error("timeout")
        harness.view.connect_gmail()
        harness.dispatch.complete_next()
        self.assertIn(TESTER_HINT, harness.view.gmail_status.get())

    def test_google_warning_copy_matches_what_registered_test_users_see(self):
        desktop_setup = require_module("belegdock.desktop_setup")
        hint = require(desktop_setup, "GMAIL_HINT")
        self.assertIn("Diese App wurde nicht von Google überprüft", hint)
        self.assertIn("„Weiter“", hint)
        self.assertIn("„Erweitert“", hint)
        text = " ".join((ROOT / "packaging" / "README-Windows.txt").read_text(encoding="utf-8").split())
        self.assertIn("Diese App wurde nicht von Google überprüft", text)
        self.assertIn("„Weiter“", text)
        self.assertNotIn("Weiter zu", text)


class WindowSizingTests(unittest.TestCase):
    def test_height_fits_content_is_capped_to_the_screen_and_keeps_a_minimum(self):
        desktop_setup = require_module("belegdock.desktop_setup")
        fit = require(desktop_setup, "fit_height")
        minimum = desktop_setup.SETUP_MIN_SIZE[1]

        self.assertEqual(fit(800, 1080), 800)
        self.assertLess(fit(2000, 768), 768)
        self.assertGreater(fit(2000, 768), 500)
        self.assertEqual(fit(100, 1080), minimum)
        self.assertLessEqual(minimum, 400)

    def test_content_scrolls_while_the_footer_is_a_separate_fixed_area(self):
        harness = SetupViewHarness()

        self.assertTrue(harness.tk.Canvas.called)
        self.assertIsInstance(harness.view.preferred_height(), int)


class ProbeStateTests(unittest.TestCase):
    def test_setup_view_records_its_state_when_a_probe_dump_is_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "probe.jsonl"
            with patch.dict(os.environ, {"BELEGDOCK_SETUP_PROBE_DUMP": str(dump)}):
                SetupViewHarness("missing", "present")
            records = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(records[-1]["state"], "setup")
        self.assertNotIn("token", json.dumps(records))

    def test_without_the_variable_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BELEGDOCK_SETUP_PROBE_DUMP", None)
                SetupViewHarness()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_build_probe_waits_for_the_setup_record(self):
        text = (ROOT / "packaging" / "build_windows.py").read_text(encoding="utf-8")
        self.assertIn("BELEGDOCK_SETUP_PROBE_DUMP", text)
        self.assertIn('"setup"', text)
        self.assertIn("timeout=60", text)


class RetryOfConnectedStepTests(unittest.TestCase):
    def test_failed_retry_keeps_the_stored_connection_and_continue(self):
        for step in ("gmail", "lexware"):
            with self.subTest(step=step):
                harness = SetupViewHarness("present", "present")
                if step == "gmail":
                    harness.services.authorize_gmail.side_effect = harness.error("network")
                    harness.connect_gmail()
                    harness.dispatch.complete_next()
                    state, status = harness.view.gmail_state, harness.view.gmail_status
                else:
                    harness.services.validate_lexware.side_effect = harness.error("network")
                    harness.enter_key()
                    harness.dispatch.complete_next()
                    state, status = harness.view.lexware_state, harness.view.lexware_status

                self.assertEqual(state.status, "connected")
                self.assertIn("Internetverbindung", status.get())
                self.assertTrue(harness.view.can_continue)
                harness.services.save_gmail.assert_not_called()
                harness.services.save_lexware.assert_not_called()

    def test_cancelled_retry_restores_the_previous_connection(self):
        harness = SetupViewHarness("present", "present")
        harness.connect_gmail()
        harness.view.cancel()

        self.assertEqual(harness.view.gmail_state.status, "connected")
        self.assertTrue(harness.view.can_continue)
        harness.dispatch.complete_next()
        harness.services.save_gmail.assert_not_called()

    def test_successful_retry_replaces_the_account(self):
        harness = SetupViewHarness("present", "present")
        harness.connect_gmail()
        harness.dispatch.complete_next()

        self.assertIn("tester@example.test", harness.view.gmail_status.get())
        harness.services.save_gmail.assert_called_once()


class KeyRetentionTests(unittest.TestCase):
    def test_key_is_kept_for_transient_failures_and_cleared_for_rejection(self):
        cases = {"network": True, "unexpected": True, "store": True, "rejected": False}
        for code, kept in cases.items():
            with self.subTest(code=code):
                harness = SetupViewHarness()
                harness.services.validate_lexware.side_effect = harness.error(code)
                harness.enter_key("synthetic-key-1")

                harness.dispatch.complete_next()

                self.assertEqual(harness.view.lexware_key.get(), "synthetic-key-1" if kept else "")

    def test_raw_unexpected_errors_keep_the_key_but_never_show_it(self):
        harness = SetupViewHarness()
        harness.services.validate_lexware.side_effect = RuntimeError("Bearer synthetic-key-1")
        harness.enter_key("synthetic-key-1")

        harness.dispatch.complete_next()

        self.assertEqual(harness.view.lexware_key.get(), "synthetic-key-1")
        self.assertNotIn("synthetic-key-1", harness.view.lexware_status.get())


class CliStartErrorTests(unittest.TestCase):
    def test_terminal_desktop_prints_the_specific_store_message(self):
        message = desktop.CREDENTIAL_STORE_UNAVAILABLE_MESSAGE
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch(
            "belegdock.cli.run_desktop", side_effect=desktop.DesktopStartError(message)
        ):
            status = cli.main(["desktop"])

        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn(message, error.getvalue())
        self.assertNotIn("Desktop-Vorgang fehlgeschlagen", error.getvalue())


class GuidedFlowTextTests(unittest.TestCase):
    def test_guided_flow_prints_nothing_english_and_passes_a_german_success_page(self):
        module = require_module("belegdock.setup")
        harness = GmailHarness()
        with patch.object(accounts, "native_backend", return_value=Mock()):
            require(module, "authorize_gmail_guided")(
                Path("client.json"), importer=harness.importer, timeout_seconds=120
            )

        options = harness.flow.run_local_server.call_args.kwargs
        self.assertEqual(options["port"], 0)
        self.assertEqual(options["timeout_seconds"], 120)
        self.assertIsNone(options["authorization_prompt_message"])
        self.assertIn("Anmeldung abgeschlossen", options["success_message"])
        self.assertIn("BelegDock", options["success_message"])

    def test_cli_flow_is_unchanged(self):
        module = require_module("belegdock.setup")
        harness = GmailHarness()
        with patch.object(accounts, "native_backend", return_value=Mock()), patch.object(accounts, "save_secret"):
            module.connect_gmail(Path("client.json"), importer=harness.importer)

        harness.flow.run_local_server.assert_called_once_with(port=0)


if __name__ == "__main__":
    unittest.main()
