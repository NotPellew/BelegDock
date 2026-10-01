from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from belegdock import cli
from belegdock.workflow import Store


class EmptyScanAndIntegrityNamesCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_scan_empty_results_prints_json_array_and_stderr_explanation(self):
        adapter = Mock()
        adapter.candidates.return_value = []
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("scan", "--label", "Rechnungen")

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output), [])
        self.assertIn("Keine PDF- oder XML-Anhänge im Gmail-Label 'Rechnungen' gefunden.", error)

    def test_scan_non_empty_results_emits_no_stderr_explanation(self):
        adapter = Mock()
        adapter.candidates.return_value = [
            {
                "id": "msg1:part1",
                "message_id": "msg1",
                "part_id": "part1",
                "filename": "invoice.pdf",
                "size": 1024,
            }
        ]
        adapter.message_context.return_value = {"subject": "Rechnung", "sender": "test@example.com"}
        with patch.object(cli, "gmail_client", return_value=("test@example.com", adapter)):
            status, output, error = self.invoke("scan", "--label", "Rechnungen")

        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(output)), 1)
        self.assertEqual(error, "")

    def test_documents_missing_blob_names_affected_document(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "missing_invoice.pdf", b"pdf-data")
        (self.root / "blobs" / digest).unlink()

        status, output, error = self.invoke("documents")

        self.assertEqual(status, 1)
        documents = json.loads(output)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["localIntegrity"], "missing")
        self.assertIn("missing_invoice.pdf", error)
        self.assertIn(digest, error)
        self.assertIn("missing", error.lower())
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_documents_corrupt_blob_names_affected_document(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "corrupt_receipt.pdf", b"pdf-data")
        (self.root / "blobs" / digest).write_bytes(b"corrupted-bytes")

        status, output, error = self.invoke("documents")

        self.assertEqual(status, 1)
        documents = json.loads(output)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["localIntegrity"], "corrupt")
        self.assertIn("corrupt_receipt.pdf", error)
        self.assertIn(digest, error)
        self.assertIn("corrupt", error.lower())
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_documents_unreadable_blob_names_affected_document_safely(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "secret_doc.pdf", b"pdf-data")
        original_open = Path.open

        def denied(path, *args, **kwargs):
            if path == self.root / "blobs" / digest:
                raise PermissionError("/private/secret/system/error")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", denied):
            status, output, error = self.invoke("documents")

        self.assertEqual(status, 1)
        self.assertIn("secret_doc.pdf", error)
        self.assertIn(digest, error)
        self.assertIn("unreadable", error.lower())
        self.assertNotIn("/private/secret/system/error", error)
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_documents_multiple_damaged_blobs_caps_at_five_with_continuation(self):
        store = Store(self.root)
        digests = []
        for i in range(7):
            d = store.stage("acct", f"msg{i}", f"part{i}", f"doc_{i}.pdf", f"content-{i}".encode("utf-8"))
            (self.root / "blobs" / d).unlink()
            digests.append(d)

        status, output, error = self.invoke("documents")

        self.assertEqual(status, 1)
        self.assertIn("... und 2 weitere beschädigte Dokumente", error)
        for i in range(5):
            self.assertIn(f"doc_{i}.pdf", error)
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_upload_damaged_document_names_document_on_stderr(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "upload_fail.pdf", b"pdf-data")
        (self.root / "blobs" / digest).write_bytes(b"damaged")

        with patch.object(cli, "lexware_client", return_value=Mock()):
            status, output, error = self.invoke("upload", digest)

        self.assertEqual(status, 1)
        self.assertIn("upload_fail.pdf", error)
        self.assertIn(digest, error)
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_recover_upload_damaged_document_names_document_on_stderr(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "recover_fail.pdf", b"pdf-data")
        (self.root / "blobs" / digest).write_bytes(b"damaged")

        status, output, error = self.invoke("recover-upload", digest)

        self.assertEqual(status, 1)
        self.assertIn("recover_fail.pdf", error)
        self.assertIn(digest, error)
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )

    def test_reconcile_damaged_document_names_document_on_stderr(self):
        store = Store(self.root)
        digest = store.stage("acct", "msg", "part", "reconcile_fail.pdf", b"pdf-data")
        (self.root / "blobs" / digest).write_bytes(b"damaged")

        with patch.object(cli, "lexware_client", return_value=Mock()):
            status, output, error = self.invoke("reconcile", digest, "--file-id", "f1", "--voucher-id", "v1")

        self.assertEqual(status, 1)
        self.assertIn("reconcile_fail.pdf", error)
        self.assertIn(digest, error)
        self.assertIn(
            "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her.",
            error,
        )


if __name__ == "__main__":
    unittest.main()
