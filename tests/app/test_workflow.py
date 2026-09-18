import hashlib
import tempfile
import unittest
from pathlib import Path


class WorkflowStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="belegdock-workflow-test-")
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)

    def store(self):
        from belegdock.workflow import Store
        return Store(self.data_dir)

    def test_stage_persists_pdf_and_returns_sha256(self):
        data = b"%PDF-1.7 test\n"
        store = self.store()
        digest = store.stage("acct-a", "msg-1", "part-1", "receipt.pdf", data)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        document = store.list_documents()[0]
        self.assertEqual(document["hash"], digest)
        self.assertEqual(document["status"], "staged")
        self.assertEqual(document["size"], len(data))
        self.assertEqual((self.data_dir / "blobs" / digest).read_bytes(), data)

    def test_stage_accepts_xml_and_rejects_other_filename(self):
        store = self.store()
        store.stage("acct-a", "msg-1", "part-1", "receipt.XML", b"<invoice/>")
        with self.assertRaisesRegex(ValueError, "candidate|pdf|xml"):
            store.stage("acct-a", "msg-2", "part-1", "receipt.txt", b"text")

    def test_stage_enforces_five_million_byte_limit(self):
        store = self.store()
        store.stage("acct-a", "msg-1", "part-1", "limit.pdf", b"x" * 5_000_000)
        with self.assertRaisesRegex(ValueError, "size|5,?000,?000|limit"):
            store.stage("acct-a", "msg-2", "part-1", "too-large.pdf", b"x" * 5_000_001)

    def test_stage_uses_hash_path_and_rejects_path_traversal(self):
        store = self.store()
        data = b"safe"
        digest = store.stage("acct-a", "msg-1", "part-1", "../../escape.pdf", data)
        self.assertEqual((self.data_dir / "blobs" / digest).read_bytes(), data)
        self.assertFalse((self.data_dir.parent / "escape.pdf").exists())

    def test_stage_deduplicates_bytes_and_keeps_occurrences(self):
        store = self.store()
        data = b"same bytes"
        digest = store.stage("acct-a", "msg-1", "part-1", "one.pdf", data)
        self.assertEqual(
            store.stage("acct-b", "msg-2", "part-9", "two.xml", data), digest
        )
        self.assertEqual(len(store.list_documents()), 1)
        occurrences = store.occurrences(digest)
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(
            {(item["account"], item["message_id"], item["part_id"]) for item in occurrences},
            {("acct-a", "msg-1", "part-1"), ("acct-b", "msg-2", "part-9")},
        )

    def test_stage_rejects_same_occurrence_for_different_bytes(self):
        store = self.store()
        store.stage("acct-a", "msg-1", "part-1", "one.pdf", b"first")
        with self.assertRaisesRegex(ValueError, "occurrence|different|conflict"):
            store.stage("acct-a", "msg-1", "part-1", "one.pdf", b"second")

    def test_stage_survives_new_store_instance(self):
        data = b"persistent"
        first = self.store()
        digest = first.stage("acct-a", "msg-1", "part-1", "receipt.pdf", data)
        second = self.store()
        self.assertEqual(second.list_documents()[0]["hash"], digest)
        self.assertEqual(second.occurrences(digest)[0]["filename"], "receipt.pdf")

    def test_upload_records_ids_and_does_not_resend_uploaded_hash(self):
        store = self.store()
        digest = store.stage("acct-a", "msg-1", "part-1", "receipt.pdf", b"receipt")
        calls = []

        def uploader(data, filename):
            calls.append((data, filename))
            return {"id": "file-1", "voucherId": "voucher-1"}

        result = store.upload(digest, uploader)
        self.assertEqual(result["id"], "file-1")
        self.assertEqual(result["voucherId"], "voucher-1")
        self.assertEqual(store.list_documents()[0]["status"], "uploaded")
        self.assertEqual(store.upload(digest, uploader), result)
        self.assertEqual(calls, [(b"receipt", "receipt.pdf")])

    def test_upload_blocks_unknown_outcome_from_automatic_resend(self):
        store = self.store()
        digest = store.stage("acct-a", "msg-1", "part-1", "receipt.pdf", b"receipt")
        calls = []

        def uploader(data, filename):
            calls.append((data, filename))
            raise ConnectionError("timeout")

        with self.assertRaisesRegex(RuntimeError, "uncertain|reconcile|outcome"):
            store.upload(digest, uploader)
        self.assertEqual(store.list_documents()[0]["status"], "uncertain")
        with self.assertRaisesRegex(RuntimeError, "uncertain|reconcile|retry"):
            store.upload(digest, uploader)
        self.assertEqual(len(calls), 1)

    def test_upload_detects_tampered_staged_bytes(self):
        store = self.store()
        digest = store.stage("acct-a", "msg-1", "part-1", "receipt.pdf", b"receipt")
        (self.data_dir / "blobs" / digest).write_bytes(b"tampered")
        calls = []

        def uploader(data, filename):
            calls.append((data, filename))
            return {"id": "file-1", "voucherId": "voucher-1"}

        with self.assertRaisesRegex(RuntimeError, "integrity|hash|modified"):
            store.upload(digest, uploader)
        self.assertEqual(calls, [])

    def test_upload_rejects_unknown_document_hash(self):
        with self.assertRaisesRegex(ValueError, "unknown|document|hash"):
            self.store().upload("0" * 64, lambda data, filename: {})

    def test_upload_rejects_incomplete_remote_result(self):
        store = self.store()
        digest = store.stage("acct-a", "msg-1", "part-1", "receipt.pdf", b"receipt")
        with self.assertRaisesRegex(ValueError, "id|voucher"):
            store.upload(digest, lambda data, filename: {"id": "file-1"})
        self.assertEqual(store.list_documents()[0]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
