import unittest
from unittest.mock import Mock

from belegdock.desktop import DesktopApplication


class DesktopIntegrityTests(unittest.TestCase):
    def test_damaged_document_is_not_ready_or_uploadable_and_shows_restore_guidance(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.documents.return_value = [
            {
                "hash": "a" * 64,
                "filename": "invoice.pdf",
                "size": 7,
                "status": "staged",
                "id": None,
                "voucherId": None,
                "localIntegrity": "corrupt",
            }
        ]
        app.documents_view = DocumentView()
        app._document_hashes = {}
        app.notice = Notice()
        app.messagebox = Mock()
        app._load_documents()

        self.assertNotEqual(app.documents_view.values[0][2], "staged")
        app._upload()

        self.assertIn("restore state.sqlite3 and blobs from a consistent backup", app.notice.value)
        self.assertNotIn("retry", app.notice.value.lower())
        app.service.upload.assert_not_called()


class DocumentView:
    def __init__(self):
        self.values = []

    def get_children(self):
        return ["row"] if self.values else []

    def delete(self, _row):
        self.values.clear()

    def insert(self, _parent, _position, values):
        self.values.append(values)
        return "row"

    def selection(self):
        return ["row"]

    def item(self, _row, _key):
        return self.values[0]


class Notice:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


if __name__ == "__main__":
    unittest.main()
