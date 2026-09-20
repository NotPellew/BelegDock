import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from belegdock import cli
from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


TYPES = "purchaseinvoice,purchasecreditnote,salesinvoice,salescreditnote"


def response(request, body, status=200, content=None):
    return httpx.Response(status, json=body if content is None else None, content=content, request=request)


class ExtraIssue13Tests(unittest.TestCase):
    def test_cli_real_adapter_positive_match_associates_without_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root)
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            calls = []

            def handler(request):
                calls.append(request)
                if request.url.path == "/v1/profile":
                    return response(request, {"organizationId": "org-1"})
                if request.url.path == "/v1/voucherlist":
                    return response(request, {"content": [{"id": "v1"}], "last": True, "number": 0, "totalPages": 1, "totalElements": 1, "size": 1})
                if request.url.path == "/v1/vouchers/v1":
                    return response(request, {"id": "v1", "type": "purchaseinvoice", "files": ["f1"]})
                if request.url.path == "/v1/files/f1":
                    return response(request, {}, content=b"receipt")
                if request.url.path == "/v1/files" and request.method == "POST":
                    raise AssertionError("verified positive match must not POST")
                return httpx.Response(404, request=request)

            remote = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
            with patch.object(cli, "lexware_client", return_value=remote):
                status = cli.main(["--data-dir", str(root), "upload", digest])
            self.assertEqual(status, 0)
            self.assertEqual(store.list_documents()[0]["status"], "uploaded")
            self.assertEqual(store.list_documents()[0]["id"], "f1")
            self.assertEqual(store.list_documents()[0]["voucherId"], "v1")
            self.assertFalse(any(request.method == "POST" for request in calls))

    def test_failed_refresh_keeps_seeded_cache_unchanged(self):
        phase = [0]

        def handler(request):
            if request.url.path == "/v1/profile":
                return response(request, {"organizationId": "org-1"})
            if request.url.path == "/v1/voucherlist":
                if phase[0] == 0:
                    return response(request, {"content": [{"id": "v1"}], "last": True, "number": 0, "totalPages": 1, "totalElements": 1, "size": 1})
                return response(request, {"content": [{"id": {}}], "last": True, "number": 0, "totalPages": 1, "totalElements": 1, "size": 1})
            if request.url.path == "/v1/vouchers/v1":
                return response(request, {"id": "v1", "type": "purchaseinvoice", "files": ["f1"]})
            if request.url.path == "/v1/files/f1":
                return response(request, {}, content=b"receipt")
            return httpx.Response(404, request=request)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root)
            digest = hashlib.sha256(b"receipt").hexdigest()
            store.refresh_remote("org-1", [{"id": "f1", "voucherId": "v1", "hash": digest}])
            remote = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
            try:
                cli.refresh_remote_inventory(store, remote)
            except Exception as error:
                self.fail(f"initial refresh failed: {error}")
            phase[0] = 1
            with self.assertRaises((ValueError, RuntimeError)):
                cli.refresh_remote_inventory(store, remote)
            self.assertEqual(store.remote_presence(digest)["id"], "f1")

    def test_current_remote_bytes_mismatch_leaves_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            with self.assertRaisesRegex(RuntimeError, "match|voucher|file"):
                self.assertTrue(callable(getattr(store, "associate_remote", None)))
                store.associate_remote(digest, "f1", "v1", lambda file_id, voucher_id: b"changed")
            self.assertEqual(store.list_documents()[0]["status"], "staged")

    def test_current_voucher_link_mismatch_leaves_staged_and_skips_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root)
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            calls = []

            def handler(request):
                calls.append(request)
                if request.url.path == "/v1/profile":
                    return response(request, {"organizationId": "org-1"})
                if request.url.path == "/v1/voucherlist":
                    return response(request, {"content": [{"id": "v1"}], "last": True, "number": 0, "totalPages": 1, "totalElements": 1, "size": 1})
                if request.url.path == "/v1/vouchers/v1":
                    return response(request, {"id": "v1", "type": "purchaseinvoice", "files": ["other-file"]})
                if request.url.path == "/v1/files":
                    raise AssertionError("missing current voucher link must not POST")
                return httpx.Response(404, request=request)

            remote = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
            with patch.object(cli, "lexware_client", return_value=remote):
                status = cli.main(["--data-dir", str(root), "upload", digest])
            self.assertNotEqual(status, 0)
            self.assertTrue(any(request.url.path == "/v1/profile" for request in calls))
            self.assertTrue(any(request.url.path == "/v1/voucherlist" for request in calls))
            self.assertTrue(any(request.url.path == "/v1/vouchers/v1" for request in calls))
            self.assertEqual(store.list_documents()[0]["status"], "staged")
            self.assertFalse(any(request.method == "POST" for request in calls))

    def test_429_then_success_retries_without_unbounded_requests(self):
        attempts = []

        def handler(request):
            if request.url.path == "/v1/profile":
                return response(request, {"organizationId": "org-1"})
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            return response(request, {"content": [], "last": True, "number": 0, "totalPages": 1, "totalElements": 0, "size": 1})

        remote = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            remote.inventory(include_archived=False)
        except Exception as error:
            self.fail(f"429 retry path failed before retrying: {error}")
        self.assertEqual(len(attempts), 2)

    def test_exhausted_429_fails_without_replacing_seeded_cache(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path == "/v1/profile":
                return response(request, {"organizationId": "org-1"})
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = hashlib.sha256(b"receipt").hexdigest()
            store.refresh_remote("org-1", [{"id": "f1", "voucherId": "v1", "hash": digest}])
            remote = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
            with self.assertRaises(RuntimeError):
                cli.refresh_remote_inventory(store, remote)
            self.assertTrue(any(request.url.path == "/v1/profile" for request in calls))
            self.assertTrue(any(request.url.path == "/v1/voucherlist" for request in calls))
            self.assertEqual(store.remote_presence(digest)["id"], "f1")

    def test_oversize_stream_closes_response(self):
        closed = []

        class Response(httpx.Response):
            def close(self):
                closed.append(True)
                super().close()

        client = httpx.Client(transport=httpx.MockTransport(lambda request: Response(200, content=b"x" * 5_000_001, request=request)))
        try:
            try:
                LexwareAdapter(client).hash_file("f1")
            except TypeError as error:
                self.fail(f"streaming API call is invalid: {error}")
            except ValueError:
                pass
            self.assertTrue(closed)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
