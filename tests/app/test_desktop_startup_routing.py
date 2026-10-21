import inspect
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from belegdock import cli, desktop
from setup_test_support import require, require_module


def fake_tkinter():
    module = types.ModuleType("tkinter")
    module.messagebox = Mock(name="messagebox")
    module.ttk = Mock(name="ttk")
    module.filedialog = Mock(name="filedialog")
    module.Tk = Mock(name="Tk")
    return module


class StartupHarness:
    def __init__(self, gmail="present", lexware="present", store=True, setup_result="root"):
        self.events = []
        self.setup = require_module("belegdock.setup")
        self.desktop_setup = require_module("belegdock.desktop_setup")
        self.state = require(self.setup, "SetupState")(
            store, gmail if store else "store_unavailable", lexware if store else "store_unavailable"
        )
        self.root = MagicMock(name="setup-root")
        self.application = MagicMock(name="application")
        self.run_setup = Mock(side_effect=self._run_setup)
        self.setup_result = self.root if setup_result == "root" else None
        self.gmail_client = Mock(side_effect=self._gmail)
        self.lexware_client = Mock(side_effect=self._lexware)
        self.create_application = Mock(side_effect=self._application)
        self.store = Mock(side_effect=self._store)

    def _run_setup(self, *args, **kwargs):
        self.events.append("setup")
        return self.setup_result

    def _gmail(self):
        self.events.append("gmail_client")
        return "tester@example.test", Mock(name="gmail")

    def _lexware(self):
        self.events.append("lexware_client")
        return Mock(name="lexware")

    def _application(self, *args, **kwargs):
        self.events.append("main")
        return self.application

    def _store(self, *args, **kwargs):
        self.events.append("store")
        return MagicMock(name="store")

    def patches(self):
        environment = {key: value for key, value in os.environ.items() if key != desktop.DESKTOP_SMOKE_ENV}
        return [
            patch.dict(sys.modules, {"tkinter": fake_tkinter()}),
            patch.dict(os.environ, environment, clear=True),
            patch.object(self.setup, "detect_state", return_value=self.state),
            patch.object(self.desktop_setup, "run_setup", self.run_setup),
            patch.object(cli, "gmail_client", self.gmail_client),
            patch.object(cli, "lexware_client", self.lexware_client),
            patch.object(desktop, "DesktopApplication", self.create_application),
            patch.object(desktop, "DesktopService", Mock()),
            patch.object(desktop, "Store", self.store),
        ]

    def run(self, entry="run_desktop"):
        messages = []
        from contextlib import ExitStack

        with ExitStack() as stack:
            for item in self.patches():
                stack.enter_context(item)
            if entry == "desktop_main":
                status = desktop.desktop_main(messages.append)
            else:
                status = desktop.run_desktop(None)
        return status, messages


class StartupRoutingTests(unittest.TestCase):
    def test_present_credentials_go_straight_to_the_main_view(self):
        harness = StartupHarness("present", "present")

        harness.run()

        harness.run_setup.assert_not_called()
        self.assertEqual(harness.events, ["store", "gmail_client", "lexware_client", "main"])
        self.assertIsNone(harness.create_application.call_args.kwargs.get("root"))
        harness.application.run.assert_called_once_with()

    def test_any_missing_or_unreadable_credential_runs_setup_before_the_main_view(self):
        for gmail, lexware in (
            ("missing", "missing"),
            ("missing", "present"),
            ("present", "missing"),
            ("read_failed", "present"),
            ("present", "read_failed"),
        ):
            with self.subTest(gmail=gmail, lexware=lexware):
                harness = StartupHarness(gmail, lexware)

                harness.run()

                harness.run_setup.assert_called_once()
                self.assertEqual(harness.run_setup.call_args.args[-1], harness.state)
                self.assertEqual(
                    harness.events, ["setup", "store", "gmail_client", "lexware_client", "main"]
                )
                self.assertIs(harness.create_application.call_args.kwargs["root"], harness.root)

    def test_closing_setup_exits_without_building_clients_or_the_main_view(self):
        harness = StartupHarness("missing", "missing", setup_result=None)

        status, messages = harness.run("desktop_main")

        self.assertEqual(harness.events, ["setup"])
        self.assertEqual((status, messages), (0, []))

    def test_unavailable_credential_store_reports_a_clear_message_without_a_window(self):
        harness = StartupHarness(store=False)

        status, messages = harness.run("desktop_main")

        self.assertEqual(status, 1)
        self.assertEqual(harness.events, [])
        self.assertEqual(len(messages), 1)
        self.assertIn("Anmeldedatenspeicher", messages[0])
        self.assertIn("Klartext", messages[0])
        self.assertNotIn("login-gmail", messages[0])

    def test_client_failure_after_setup_closes_the_window_and_keeps_the_generic_message(self):
        harness = StartupHarness("missing", "present")
        harness.gmail_client.side_effect = RuntimeError("secret-token-value /home/private")

        status, messages = harness.run("desktop_main")

        self.assertEqual(status, 1)
        harness.root.destroy.assert_called_once_with()
        harness.create_application.assert_not_called()
        self.assertEqual(messages, [desktop.DESKTOP_START_FAILED_MESSAGE])

    def test_application_reuses_the_existing_root_instead_of_creating_a_new_one(self):
        self.assertIn("root", inspect.signature(desktop.DesktopApplication.__init__).parameters)
        tk = MagicMock(name="tk")
        existing = MagicMock(name="existing-root")
        existing.winfo_width.return_value = 1200

        application = desktop.DesktopApplication(Mock(), tk, MagicMock(), Mock(), root=existing)

        tk.Tk.assert_not_called()
        self.assertIs(application.root, existing)


if __name__ == "__main__":
    unittest.main()
