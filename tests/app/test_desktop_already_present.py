import unittest
from unittest.mock import Mock

from belegdock.desktop import DesktopApplication


class DesktopAlreadyPresentTests(unittest.TestCase):
    def test_already_present_document_has_a_distinct_state(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.documents.return_value = [
            {
                "hash": "a" * 64,
                "filename": "invoice.pdf",
                "size": 7,
                "status": "uploaded",
                "origin": "already_present",
                "id": "file-existing",
                "voucherId": "voucher-existing",
                "localIntegrity": "ok",
            }
        ]
        app.documents_view = DocumentView()
        app._document_hashes = {}
        app.notice = Notice()

        app._load_documents()

        self.assertEqual(app.documents_view.values[0][2], "already present in Lexware")

    def test_already_present_result_says_no_upload_was_sent(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock(
            upload=Mock(
                return_value={
                    "id": "file-existing",
                    "voucherId": "voucher-existing",
                    "status": "already_present",
                }
            )
        )
        app.documents_view = DocumentView(("invoice.pdf", 7, "staged", "", ""))
        app._document_hashes = {"row": "a" * 64}
        app.notice = Notice()
        app.messagebox = Confirmation()
        app._load_documents = Mock()

        app._upload()

        self.assertIn("already present in lexware", app.notice.value.lower())
        self.assertIn("no upload was sent", app.notice.value.lower())
        self.assertIn("file-existing", app.notice.value)
        self.assertIn("voucher-existing", app.notice.value)


class DocumentView:
    def __init__(self, selected_values=None):
        self.values = []
        self.selected_values = selected_values

    def get_children(self):
        return ["row"] if self.values else []

    def delete(self, _row):
        self.values.clear()

    def insert(self, _parent, _position, values):
        self.values.append(values)
        return "row"

    def selection(self):
        return ["row"] if self.selected_values else []

    def item(self, _row, _key):
        return self.selected_values


class Notice:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class Confirmation:
    def askyesno(self, _title, _prompt):
        return True


if __name__ == "__main__":
    unittest.main()
