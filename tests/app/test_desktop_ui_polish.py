import unittest

from belegdock import desktop


class DesktopUiPolishContractTests(unittest.TestCase):
    def test_file_sizes_are_human_readable(self):
        self.assertTrue(hasattr(desktop, "format_size"))
        if not hasattr(desktop, "format_size"):
            return
        self.assertEqual(desktop.format_size(0), "0 bytes")
        self.assertEqual(desktop.format_size(512), "512 bytes")
        self.assertEqual(desktop.format_size(1536), "1.5 KiB")
        self.assertEqual(desktop.format_size(5_000_000), "4.8 MiB")

    def test_status_codes_have_readable_labels(self):
        self.assertTrue(hasattr(desktop, "status_label"))
        if not hasattr(desktop, "status_label"):
            return
        self.assertEqual(desktop.status_label("staged"), "Staged")
        self.assertEqual(desktop.status_label("uploaded"), "Uploaded")
        self.assertEqual(desktop.status_label("uncertain"), "Uncertain")
        self.assertEqual(desktop.status_label("already_present"), "Already present in Lexware")

    def test_prepare_disclaimer_is_exposed_without_a_workflow_stepper(self):
        self.assertFalse(hasattr(desktop, "WORKFLOW_STEPS"))
        self.assertIn(
            "saves selected files locally and sends nothing to Lexware",
            getattr(desktop, "PREPARE_HELPER", ""),
        )

    def test_document_table_contract_is_compact_and_has_detail_actions(self):
        self.assertEqual(
            getattr(desktop, "DOCUMENT_TABLE_COLUMNS", ()),
            ("filename", "size", "status"),
        )
        self.assertTrue(hasattr(desktop.DesktopApplication, "_show_document_detail"))
        self.assertTrue(hasattr(desktop.DesktopApplication, "_copy_detail"))


if __name__ == "__main__":
    unittest.main()
