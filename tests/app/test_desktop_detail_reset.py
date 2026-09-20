import unittest
from unittest.mock import Mock

from belegdock.desktop import DesktopApplication


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class DocumentView:
    def __init__(self):
        self.rows = ["old-row"]

    def get_children(self):
        return list(self.rows)

    def delete(self, row):
        self.rows.remove(row)

    def insert(self, _parent, _position, values):
        self.rows.append("new-row")
        self.values = values
        return "new-row"


class Notice:
    def set(self, _value):
        pass


class DesktopDetailResetTests(unittest.TestCase):
    def test_reload_clears_detail_values_for_removed_document(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.documents.side_effect = [
            [
                {
                    "hash": "a" * 64,
                    "filename": "invoice.pdf",
                    "size": 7,
                    "status": "uploaded",
                    "id": "file-old",
                    "voucherId": "voucher-old",
                    "localIntegrity": "ok",
                }
            ],
            [],
        ]
        app.documents_view = DocumentView()
        app._document_hashes = {}
        app.notice = Notice()
        app.detail_filename = Variable()
        app.detail_file_id = Variable("file-old")
        app.detail_voucher_id = Variable("voucher-old")
        app._detail_row = "old-row"

        app._load_documents()
        app._detail_row = "new-row"
        app.detail_filename.set("invoice.pdf")
        app._load_documents()

        self.assertIsNone(app._detail_row)
        self.assertEqual(app.detail_filename.get(), "Select a document to review.")
        self.assertEqual(app.detail_file_id.get(), "")
        self.assertEqual(app.detail_voucher_id.get(), "")


if __name__ == "__main__":
    unittest.main()
