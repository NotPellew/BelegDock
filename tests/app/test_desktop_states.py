import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from belegdock.desktop import DesktopApplication, DesktopService
from belegdock.workflow import DocumentRejected, Store


class FakeGmail:
    def __init__(self, data=b"invoice", filename="invoice.pdf"):
        self.data = data
        self.candidate = {
            "id": "message:part",
            "message_id": "message",
            "part_id": "part",
            "filename": filename,
            "size": len(data),
        }

    def candidates(self, _label):
        return [self.candidate]

    def fetch(self, _candidate):
        return self.data


class FakeRemote:
    def __init__(self, data=b"invoice"):
        self.data = data
        self.upload = Mock(return_value={"id": "file-new", "voucherId": "voucher-new"})
        self.verify_existing = Mock(return_value=data)
        self.inventory = Mock(return_value={"organizationId": "org", "files": []})
        self.hash_file = Mock(return_value="")


def make_service(remote=None):
    temporary = tempfile.TemporaryDirectory()
    store = Store(Path(temporary.name))
    gmail = FakeGmail()
    service = DesktopService(store, "account@example.test", gmail, remote or FakeRemote())
    digest = service.stage("Invoices", [gmail.candidate["id"]])[0]
    return temporary, service, digest


class DesktopStateTests(unittest.TestCase):
    def test_duplicate_remote_document_is_verified_and_not_uploaded_again(self):
        remote = FakeRemote()
        remote.inventory.return_value = {
            "organizationId": "org",
            "files": [{"id": "file-existing", "voucherId": "voucher-existing"}],
        }
        temporary, service, digest = make_service(remote)
        self.addCleanup(temporary.cleanup)
        remote.hash_file.return_value = digest

        result = service.upload(digest)
        repeated = service.upload(digest)

        self.assertEqual(result["status"], "already_present")
        self.assertEqual(repeated["id"], "file-existing")
        remote.upload.assert_not_called()

    def test_http_400_and_406_are_terminal_rejections(self):
        for status in (400, 406):
            with self.subTest(status=status):
                remote = FakeRemote()
                remote.upload.side_effect = DocumentRejected(status)
                temporary, service, digest = make_service(remote)
                self.addCleanup(temporary.cleanup)

                with self.assertRaises(DocumentRejected):
                    service.upload(digest)

                self.assertEqual(service.documents()[0]["status"], "rejected")
                self.assertEqual(service.documents()[0]["rejectionStatus"], status)

    def test_transport_failure_becomes_uncertain(self):
        remote = FakeRemote()
        remote.upload.side_effect = OSError("private transport details")
        temporary, service, digest = make_service(remote)
        self.addCleanup(temporary.cleanup)

        with self.assertRaises(RuntimeError):
            service.upload(digest)

        self.assertEqual(service.documents()[0]["status"], "uncertain")

    def test_uncertain_document_shows_cli_only_recovery_guidance(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.documents_view = FakeDocumentView(("invoice.pdf", 7, "uncertain", "", ""))
        app._document_hashes = {"row": "a" * 64}
        app.notice = Notice()
        app.messagebox = Mock()

        app._upload()

        self.assertIn("CLI", app.notice.value)
        self.assertIn("reconcil", app.notice.value.lower())
        app.service.upload.assert_not_called()
        app.messagebox.askyesno.assert_not_called()

    def test_confirmation_names_document_and_size(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock(upload=Mock(return_value={"id": "file", "voucherId": "voucher"}))
        app.documents_view = FakeDocumentView(("invoice.pdf", 7, "staged", "", ""))
        app._document_hashes = {"row": "a" * 64}
        app.notice = Notice()
        app.messagebox = Confirmation()
        app._load_documents = Mock()

        app._upload()

        self.assertIn("invoice.pdf", app.messagebox.prompt)
        self.assertIn("7", app.messagebox.prompt)

    def test_rejection_shows_corrective_guidance_not_uncertain_guidance(self):
        app = DesktopApplication.__new__(DesktopApplication)
        app.service = Mock()
        app.service.upload.side_effect = DocumentRejected(400)
        app.documents_view = FakeDocumentView(("invoice.pdf", 7, "staged", "", ""))
        app._document_hashes = {"row": "a" * 64}
        app.notice = Notice()
        app.messagebox = Confirmation()
        app._load_documents = Mock()

        app._upload()

        self.assertIn("correct the document", app.notice.value.lower())
        self.assertIn("stage new bytes", app.notice.value.lower())
        self.assertNotIn("uncertain", app.notice.value.lower())


class FakeDocumentView:
    def __init__(self, values):
        self.values = values

    def selection(self):
        return ["row"]

    def item(self, _row, _key):
        return self.values


class Notice:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class Confirmation:
    def __init__(self):
        self.prompt = ""

    def askyesno(self, _title, prompt):
        self.prompt = prompt
        return True


if __name__ == "__main__":
    unittest.main()
