import unittest
from unittest.mock import patch

from google.auth.exceptions import RefreshError

from belegdock import accounts, desktop, desktop_setup
from test_desktop_setup import SetupViewHarness
from test_setup_review import ExpiredStartupHarness


class ExpiredAfterSetupTests(unittest.TestCase):
    def test_expired_stored_gmail_found_after_lexware_setup_reopens_setup_marked_expired(self):
        harness = ExpiredStartupHarness([RefreshError("invalid_grant")], gmail="present", lexware="missing")
        with patch.object(accounts, "save_secret") as save:
            status, messages = harness.run("desktop_main")

        self.assertEqual((status, messages), (0, []))
        self.assertEqual(harness.run_setup.call_count, 2)
        expired = harness.run_setup.call_args_list[1].args[-1]
        self.assertEqual((expired.gmail, expired.lexware), ("expired", "present"))
        harness.root.destroy.assert_called_once_with()
        self.assertEqual(harness.events[-3:], ["gmail_client", "lexware_client", "main"])
        save.assert_not_called()

    def test_rejection_right_after_a_fresh_gmail_connect_does_not_reopen_setup(self):
        harness = ExpiredStartupHarness([RefreshError("invalid_grant")], gmail="missing", lexware="missing")

        status, messages = harness.run("desktop_main")

        self.assertEqual(status, 1)
        harness.run_setup.assert_called_once()
        self.assertEqual(messages, [desktop.DESKTOP_START_FAILED_MESSAGE])


class ConnectedStepInputTests(unittest.TestCase):
    def test_connect_without_a_client_file_keeps_a_stored_gmail_connection(self):
        harness = SetupViewHarness("present", "present")

        harness.view.connect_gmail()

        self.assertEqual(harness.view.gmail_state.status, "connected")
        self.assertIn("OAuth-Client-Datei", harness.view.gmail_status.get())
        self.assertTrue(harness.view.can_continue)

    def test_blank_key_keeps_a_stored_lexware_connection(self):
        harness = SetupViewHarness("present", "present")
        harness.view.lexware_key.set("   ")

        harness.view.submit_lexware()

        self.assertEqual(harness.view.lexware_state.status, "connected")
        self.assertIn("API-Schlüssel", harness.view.lexware_status.get())
        self.assertTrue(harness.view.can_continue)
        harness.services.validate_lexware.assert_not_called()


class WindowPlacementTests(unittest.TestCase):
    def test_height_leaves_room_for_taskbar_and_title_bar(self):
        self.assertLessEqual(desktop_setup.fit_height(2000, 768), 768 - 140)


if __name__ == "__main__":
    unittest.main()
