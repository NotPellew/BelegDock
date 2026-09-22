import unittest
from unittest.mock import patch

from belegdock import desktop


class DesktopLaunchTests(unittest.TestCase):
    def test_unavailable_tkinter_reports_german_guidance(self):
        desktop_main = getattr(desktop, "desktop_main", None)
        self.assertTrue(callable(desktop_main), "desktop.desktop_main is missing")
        messages = []
        with patch.object(
            desktop,
            "run_desktop",
            side_effect=desktop.DesktopUnavailableError("private-import-detail"),
        ):
            status = desktop_main(messages.append)
        self.assertEqual(status, 1)
        self.assertTrue(messages)
        self.assertIn("Desktop-Oberfläche ist nicht verfügbar", messages[-1])
        self.assertNotIn("private-import-detail", messages[-1])

    def test_generic_failure_reports_login_hint_without_exception_text(self):
        desktop_main = getattr(desktop, "desktop_main", None)
        self.assertTrue(callable(desktop_main), "desktop.desktop_main is missing")
        messages = []
        with patch.object(desktop, "run_desktop", side_effect=RuntimeError("secret-token-value")):
            status = desktop_main(messages.append)
        self.assertEqual(status, 1)
        self.assertTrue(messages)
        self.assertIn("login-gmail", messages[-1])
        self.assertIn("login-lexware", messages[-1])
        self.assertNotIn("secret-token-value", messages[-1])

    def test_success_reports_nothing_and_returns_zero(self):
        desktop_main = getattr(desktop, "desktop_main", None)
        self.assertTrue(callable(desktop_main), "desktop.desktop_main is missing")
        messages = []
        with patch.object(desktop, "run_desktop", return_value=None):
            status = desktop_main(messages.append)
        self.assertEqual(status, 0)
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
