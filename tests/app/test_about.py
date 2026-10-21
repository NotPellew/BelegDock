import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from belegdock import __version__
from belegdock.build_info import (
    LICENSE_URL,
    PROJECT_URL,
    about_text,
    build_info,
)
from belegdock.desktop import DesktopApplication

ROOT = Path(__file__).resolve().parents[2]


class BuildInfoTests(unittest.TestCase):
    def test_build_info_matches_package_version_without_revision_in_source(self):
        version, revision = build_info()

        self.assertEqual(version, __version__)
        self.assertIsNone(revision)

    def test_about_text_without_revision_omits_revision_line(self):
        text = about_text()

        self.assertIn("BelegDock", text)
        self.assertIn(__version__, text)
        self.assertIn("Apache License 2.0", text)
        self.assertIn(LICENSE_URL, text)
        self.assertIn(PROJECT_URL, text)
        self.assertNotIn("Build-Revision", text)
        self.assertNotIn("Revision:", text)

    def test_about_text_shows_privacy_note_without_machine_data(self):
        text = about_text()

        self.assertIn("lokal", text)
        self.assertIn("Anwendungsdatenverzeichnis", text)
        self.assertIn("Gmail", text)
        self.assertIn("nur lesend", text)
        self.assertIn("Lexware", text)
        self.assertIn("ausdrücklichen Bestätigung", text)
        self.assertIn("Anmeldedatenspeicher des Betriebssystems", text)
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn("state.sqlite3", text)

    def test_about_text_with_revision_shows_short_revision_only(self):
        text = about_text(version="1.2.3", revision="abcdef1234567890")

        self.assertIn("1.2.3", text)
        self.assertIn("abcdef1", text)
        self.assertNotIn("abcdef1234567890", text)


class AboutDialogTests(unittest.TestCase):
    def make_app(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.tk = Mock()
        app.ttk = Mock()
        app.messagebox = Mock()
        app.root = Mock()
        app._about_dialog = None
        return app

    def test_show_about_opens_dialog_with_about_text(self):
        app = self.make_app()

        app._show_about()

        app.tk.Toplevel.assert_called_once_with(app.root)
        label_texts = [
            call.kwargs.get("text", "")
            for call in app.ttk.Label.call_args_list
        ]
        self.assertTrue(any(__version__ in text for text in label_texts))
        self.assertTrue(any("Apache License 2.0" in text for text in label_texts))

    def test_show_about_url_buttons_open_project_and_license(self):
        app = self.make_app()

        app._show_about()

        commands = [
            call.kwargs.get("command")
            for call in app.ttk.Button.call_args_list
            if callable(call.kwargs.get("command"))
        ]
        self.assertTrue(commands)
        with patch("belegdock.desktop.webbrowser.open") as open_url:
            for command in commands:
                command()
        opened = [call.args[0] for call in open_url.call_args_list]
        self.assertIn(PROJECT_URL, opened)
        self.assertIn(LICENSE_URL, opened)

    def test_about_button_is_wired_in_build_source_layout(self):
        app = self.make_app()
        self.assertTrue(callable(getattr(app, "_show_about", None)))
        desktop_text = (ROOT / "src" / "belegdock" / "desktop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Über BelegDock", desktop_text)
        self.assertIn("about_button", desktop_text)


if __name__ == "__main__":
    unittest.main()
