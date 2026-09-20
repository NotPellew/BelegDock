import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path

import httpx

from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


BOOKKEEPING_TYPES = ("purchaseinvoice", "purchasecreditnote", "salesinvoice", "salescreditnote")


class RemoteAPI:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        self.assert_request(request)
        if request.url.path == "/v1/profile":
            return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
        if request.url.path == "/v1/voucherlist":
            params = request.url.params
            voucher_type = params["voucherType"]
            archived = params["archived"]
            page = int(params["page"])
            if "purchaseinvoice" in voucher_type.split(",") and archived == "false" and page == 0:
                return httpx.Response(
                    200,
                    json={"content": [{"id": "v1"}], "last": False, "number": 0, "totalPages": 2, "totalElements": 2, "size": 1},
                    request=request,
                )
            if "purchaseinvoice" in voucher_type.split(",") and archived == "false" and page == 1:
                return httpx.Response(
                    200,
                    json={"content": [{"id": "v2"}], "last": True, "number": 1, "totalPages": 2, "totalElements": 2, "size": 1},
                    request=request,
                )
            if "purchaseinvoice" in voucher_type.split(",") and archived == "true" and page == 0:
                return httpx.Response(200, json={"content": [{"id": "v3"}], "last": True, "number": 0, "totalPages": 1, "totalElements": 1, "size": 1}, request=request)
            return httpx.Response(200, json={"content": [], "last": True, "number": 0, "totalPages": 1, "totalElements": 0, "size": 1}, request=request)
        if request.url.path.startswith("/v1/vouchers/"):
            voucher_id = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(
                200,
                json={"id": voucher_id, "type": "purchaseinvoice", "voucherStatus": "open", "archived": voucher_id == "v3", "updatedDate": "2026-09-20T00:00:00Z", "files": ["f-" + voucher_id[1:]]},
                request=request,
            )
        if request.url.path.startswith("/v1/files/"):
            file_id = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(200, content=b"receipt-" + file_id.encode(), request=request)
        return httpx.Response(404, request=request)

    @staticmethod
    def assert_request(request):
        if request.url.path == "/v1/voucherlist":
            assert request.method == "GET"
            assert set(request.url.params["voucherType"].split(",")) == set(BOOKKEEPING_TYPES)
            assert request.url.params["voucherStatus"] == "any"
            assert request.url.params["archived"] in ("false", "true")


class RemoteInventoryTests(unittest.TestCase):
    def test_inventory_uses_profile_voucherlist_details_and_both_archive_states(self):
        transport = RemoteAPI()
        client = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(client.close)

        self.assertTrue(callable(getattr(LexwareAdapter, "inventory", None)))
        result = LexwareAdapter(client).inventory(include_archived=True)

        self.assertEqual(result["organizationId"], "org-1")
        self.assertEqual({item["voucherId"] for item in result["files"]}, {"v1", "v2", "v3"})
        lists = [request for request in transport.requests if request.url.path == "/v1/voucherlist"]
        self.assertTrue(lists)
        requested_types = set(lists[0].url.params["voucherType"].split(","))
        self.assertEqual(requested_types, set(BOOKKEEPING_TYPES))
        self.assertEqual({request.url.params["page"] for request in lists if request.url.params["voucherType"] == lists[0].url.params["voucherType"]}, {"0", "1"})
        self.assertEqual({request.url.params["archived"] for request in lists}, {"false", "true"})
        self.assertEqual({request.url.path for request in transport.requests if request.url.path.startswith("/v1/vouchers/")}, {"/v1/vouchers/v1", "/v1/vouchers/v2", "/v1/vouchers/v3"})

    def test_hash_file_uses_httpx_streaming_path(self):
        data = b"remote bytes"
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=data, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        self.assertTrue(callable(getattr(LexwareAdapter, "hash_file", None)))
        result = LexwareAdapter(client).hash_file("file-1")

        self.assertEqual(result, hashlib.sha256(data).hexdigest())
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/v1/files/file-1")

    def test_store_binds_inventory_to_one_organization_and_classifies_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            self.assertTrue(callable(getattr(store, "refresh_remote", None)))
            store.refresh_remote("org-1", [{"id": "file-1", "voucherId": "voucher-1", "hash": digest}])

            self.assertEqual(store.remote_presence(digest), {"status": "already_present", "id": "file-1", "voucherId": "voucher-1"})
            with self.assertRaisesRegex(RuntimeError, "organization"):
                store.refresh_remote("org-2", [])

    def test_upload_refreshes_before_post_and_marks_new_origin_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            events = []
            refresh = lambda: events.append("refresh")
            uploader = lambda data, filename: events.append("post") or {"id": "file-2", "voucherId": "voucher-2"}
            self.assertIn("refresh", inspect.signature(store.upload).parameters)
            inspect.signature(store.upload).bind(digest, uploader, refresh=refresh)
            result = store.upload(
                digest,
                uploader,
                refresh=refresh,
            )

            self.assertEqual(events, ["refresh", "post"])
            self.assertEqual(result["status"], "accepted")
            self.assertEqual(result["origin"], "unknown")


if __name__ == "__main__":
    unittest.main()
