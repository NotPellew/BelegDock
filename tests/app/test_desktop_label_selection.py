import unittest
from unittest.mock import Mock

from belegdock.desktop import DesktopApplication


class Variable:
    def __init__(self):
        self.value = ""

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class LabelBox:
    def __init__(self):
        self.values = ()
        self.selected_index = None

    def __setitem__(self, key, value):
        if key == "values":
            self.values = value

    def current(self, index):
        self.selected_index = index


class DesktopLabelSelectionTests(unittest.TestCase):
    def test_first_loaded_label_is_selected_in_the_visible_combobox(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.labels.return_value = ["Invoices", "Receipts"]
        app.label = Variable()
        app.label_box = LabelBox()
        app._load_candidates = Mock()

        app._load_labels()

        self.assertEqual(app.label_box.values, ("Invoices", "Receipts"))
        self.assertEqual(app.label_box.selected_index, 0)
        self.assertEqual(app.label.get(), "Invoices")
        app._load_candidates.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
