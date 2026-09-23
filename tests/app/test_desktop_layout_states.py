import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from belegdock import desktop


class Widget:
    def __init__(self):
        self.grid_calls = []

    def grid(self, **kwargs):
        self.grid_calls.append(kwargs)

    def columnconfigure(self, *_args, **_kwargs):
        pass


class DesktopLayoutAndActionStateTests(unittest.TestCase):
    def test_wide_and_narrow_layout_repositions_sections_without_reloading(self):
        self.assertTrue(hasattr(desktop.DesktopApplication, "_layout_sections"))
        if not hasattr(desktop.DesktopApplication, "_layout_sections"):
            return
        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.sections = Widget()
        app.choose_section = Widget()
        app.review_section = Widget()
        app.service = Mock()
        app._section_layout = None

        app._layout_sections(SimpleNamespace(width=1200))
        app._layout_sections(SimpleNamespace(width=700))

        self.assertEqual(app.choose_section.grid_calls[-2]["column"], 0)
        self.assertEqual(app.review_section.grid_calls[-2]["column"], 1)
        self.assertEqual(app.choose_section.grid_calls[-1]["row"], 1)
        self.assertEqual(app.review_section.grid_calls[-1]["row"], 2)
        app.service.labels.assert_not_called()
        app.service.candidates.assert_not_called()
        app.service.documents.assert_not_called()

    def test_action_states_keep_remote_outcomes_no_send(self):
        self.assertTrue(hasattr(desktop, "document_action_state"))
        if not hasattr(desktop, "document_action_state"):
            return
        self.assertEqual(
            desktop.document_action_state("staged", "ok"),
            (True, "Bereit zum Senden.", ""),
        )
        self.assertEqual(
            desktop.document_action_state("uploaded", "ok"),
            (False, "Gesendet", "Dieses Dokument wurde bereits an Lexware gesendet."),
        )
        self.assertEqual(
            desktop.document_action_state("uploaded", "ok", "already_present"),
            (False, "Bereits in Lexware vorhanden", "Kein Senden erforderlich."),
        )
        self.assertEqual(
            desktop.document_action_state("rejected", "ok")[0],
            False,
        )
        self.assertEqual(
            desktop.document_action_state("uncertain", "ok"),
            (
                False,
                "Unklar",
                "Ergebnis unklar; verwende die CLI-Befehle zur Wiederherstellung und Abstimmung.",
            ),
        )
        self.assertEqual(desktop.document_action_state("staged", "corrupt")[0], False)

    def test_clearing_selection_resets_action_region_and_disables_send(self):
        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.documents_view = Mock(selection=Mock(return_value=[]))
        app.detail_filename = Mock()
        app.detail_file_id = Mock()
        app.detail_voucher_id = Mock()
        app.action_status = Mock()
        app.action_guidance = Mock()
        app.upload_button = Mock()
        app._detail_row = "removed-row"

        app._show_document_detail()

        self.assertIsNone(app._detail_row)
        app.action_status.set.assert_called_once_with("Wähle ein Dokument zur Prüfung.")
        app.action_guidance.set.assert_called_once_with("")
        app.upload_button.state.assert_called_once_with(["disabled"])


if __name__ == "__main__":
    unittest.main()
