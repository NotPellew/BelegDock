import tempfile
import unittest
import hashlib
from unittest.mock import patch
from pathlib import Path

import httpx

from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


class ReviewRegressions(unittest.TestCase):
    def test_association_respects_active_same_digest_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            with store._upload_lock(digest) as acquired:
                self.assertTrue(acquired)
                with self.assertRaises(RuntimeError):
                    store.associate_remote(digest, "file", "voucher", lambda *_: b"receipt")

    def test_stream_hash_retries_bounded_rate_limit(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            return httpx.Response(200, content=b"receipt", request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertEqual(
            LexwareAdapter(client).hash_file("file-1"), hashlib.sha256(b"receipt").hexdigest()
        )
        self.assertEqual(len(attempts), 2)
        client.close()

    def test_positive_verification_rejects_oversize_stream(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/files/file-1":
                return httpx.Response(200, content=b"x" * 5_000_001, request=request)
            if request.url.path == "/v1/vouchers/voucher-1":
                return httpx.Response(200, json={"id": "voucher-1", "files": ["file-1"]}, request=request)
            return httpx.Response(404, request=request)

        with self.assertRaises(ValueError):
            LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler))).verify_existing("file-1", "voucher-1")

    def test_organization_mismatch_stops_before_inventory_reads(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path == "/v1/profile":
                return httpx.Response(200, json={"organizationId": "org-new"}, request=request)
            raise AssertionError("profile mismatch must stop before inventory reads")

        with self.assertRaises(RuntimeError):
            LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler))).inventory(expected_organization_id="org-old")
        self.assertEqual(requests, ["/v1/profile"])

    def test_rate_limit_without_header_uses_positive_bounded_delay(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            return httpx.Response(429, request=request)

        with patch("belegdock.integrations.time.sleep") as sleep:
            with self.assertRaises(RuntimeError):
                LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler))).inventory()
        self.assertTrue(any(call.args[0] > 0 for call in sleep.call_args_list))
        self.assertLessEqual(len(attempts), 5)

    def test_last_page_cannot_contradict_total_pages(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/profile":
                return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
            if request.url.path == "/v1/voucherlist" and request.url.params["page"] == "0":
                return httpx.Response(
                    200,
                    json={"content": [{"id": "v1"}], "last": True, "number": 0, "totalPages": 2},
                    request=request,
                )
            if request.url.path == "/v1/voucherlist":
                return httpx.Response(
                    200,
                    json={"content": [], "last": True, "number": 1, "totalPages": 2},
                    request=request,
                )
            if request.url.path == "/v1/vouchers/v1":
                return httpx.Response(200, json={"id": "v1", "files": []}, request=request)
            return httpx.Response(404, request=request)

        with self.assertRaises((ValueError, RuntimeError)):
            LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler))).inventory()

    def test_association_checks_state_before_remote_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            with store._connection() as connection:
                connection.execute(
                    "UPDATE documents SET status='uploaded', id='old-file', voucher_id='old-voucher' WHERE hash=?",
                    (digest,),
                )
                connection.commit()
            calls = []

            def verifier(file_id: str, voucher_id: str) -> bytes:
                calls.append((file_id, voucher_id))
                return b"receipt"

            with self.assertRaises(RuntimeError):
                store.associate_remote(digest, "new-file", "new-voucher", verifier)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
