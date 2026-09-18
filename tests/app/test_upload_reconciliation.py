from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from belegdock import cli
from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


class Response:
    def __init__(self, status_code, body=None, content=b"", text="remote document content"):
        self.status_code = status_code
        self._body = body
        self.content = content
        self.text = text

    def json(self):
        return self._body


class Client:
    def __init__(self, post_response):
        self.post_response = post_response
        self.posts = []

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return self.post_response


class UploadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def uncertain_document(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        with self.assertRaises(RuntimeError):
            store.upload(digest, lambda data, filename: (_ for _ in ()).throw(ConnectionError("timeout")))
        return store, digest

    def test_documented_406_is_rejected_without_exposing_server_text(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        adapter = LexwareAdapter(Client(Response(406, text="secret remote document")))

        with self.assertRaises(RuntimeError) as error:
            store.upload(digest, adapter.upload)

        self.assertIn("406", str(error.exception))
        self.assertIn("rejected", str(error.exception).lower())
        self.assertNotIn("secret remote document", str(error.exception))
        document = store.list_documents()[0]
        self.assertEqual(document["status"], "rejected")
        self.assertEqual(document["rejectionStatus"], 406)

    def test_rejected_bytes_are_not_resent(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        adapter = LexwareAdapter(Client(Response(406)))
        with self.assertRaises(RuntimeError):
            store.upload(digest, adapter.upload)

        with self.assertRaisesRegex(RuntimeError, "rejected|correct"):
            store.upload(digest, lambda data, filename: {"id": "new-file", "voucherId": "new-voucher"})
        self.assertEqual(len(adapter.client.posts), 1)

    def test_reconciliation_requires_matching_remote_bytes_before_recording_ids(self):
        store, digest = self.uncertain_document()
        calls = []

        def verifier(file_id, voucher_id):
            calls.append((file_id, voucher_id))
            return b"receipt"

        try:
            result = store.reconcile(digest, "file-1", "voucher-1", verifier)
        except AttributeError:
            result = {"status": "not implemented"}

        self.assertEqual(result, {"id": "file-1", "voucherId": "voucher-1"})
        self.assertEqual(calls, [("file-1", "voucher-1")])
        self.assertEqual(store.list_documents()[0]["status"], "uploaded")

    def test_failed_reconciliation_leaves_document_uncertain(self):
        store, digest = self.uncertain_document()

        try:
            store.reconcile(digest, "file-1", "voucher-1", lambda file_id, voucher_id: b"other")
        except RuntimeError as error:
            message = str(error)
        except AttributeError:
            message = "not implemented"
        else:
            message = "reconciliation unexpectedly succeeded"

        self.assertRegex(message, "remote.*match|match.*remote")
        self.assertEqual(store.list_documents()[0]["status"], "uncertain")
        self.assertIsNone(store.list_documents()[0]["id"])

    def test_reconciliation_does_not_take_over_an_active_upload(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        entered, release = threading.Event(), threading.Event()

        def uploader(data, filename):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test did not release uploader")
            return {"id": "file-1", "voucherId": "voucher-1"}

        worker = threading.Thread(target=store.upload, args=(digest, uploader))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaisesRegex(RuntimeError, "uncertain|active"):
                Store(self.root).reconcile(digest, "file-1", "voucher-1", lambda file_id, voucher_id: b"receipt")
            self.assertEqual(Store(self.root).list_documents()[0]["status"], "uploading")
        finally:
            release.set()
            worker.join(5)

    def test_cli_reports_a_sanitized_documented_rejection(self):
        store = Store(self.root)
        digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
        remote = LexwareAdapter(Client(Response(406, text="secret remote document")))
        output, error = StringIO(), StringIO()

        with patch.object(cli, "lexware_client", return_value=remote), redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["--data-dir", str(self.root), "upload", digest])

        self.assertEqual(status, 1)
        self.assertIn("406", error.getvalue())
        self.assertIn("rejected", error.getvalue().lower())
        self.assertNotIn("secret remote document", output.getvalue() + error.getvalue())


if __name__ == "__main__":
    unittest.main()
