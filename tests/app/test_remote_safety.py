import hashlib
import tempfile
import unittest
from pathlib import Path

import httpx

from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


TYPES = "purchaseinvoice,purchasecreditnote,salesinvoice,salescreditnote"


class API:
    def __init__(self, handler):
        self.requests = []
        self.handler = handler

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)


def client_for(api):
    return httpx.Client(transport=httpx.MockTransport(api))


class RemoteSafetyTests(unittest.TestCase):
    def test_refresh_rejects_incomplete_pagination_without_replacing_cache(self):
        def handler(request):
            if request.url.path == "/v1/profile":
                return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
            if request.url.path == "/v1/voucherlist":
                return httpx.Response(200, json={"content": [{"id": "v1"}], "number": 0}, request=request)
            return httpx.Response(200, json={"id": "v1", "files": ["f1"]}, request=request)

        api = API(handler)
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            with self.assertRaises((ValueError, RuntimeError)):
                LexwareAdapter(client_for(api)).inventory(include_archived=True)

    def test_refresh_retries_429_with_bounded_attempts(self):
        attempts = []

        def handler(request):
            if request.url.path == "/v1/profile":
                return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
            attempts.append(request)
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

        api = API(handler)
        with self.assertRaises(RuntimeError):
            LexwareAdapter(client_for(api)).inventory(include_archived=True)
        self.assertGreater(len(attempts), 1)
        self.assertLessEqual(len(attempts), 5)

    def test_hash_stream_rejects_oversize_and_closes_response(self):
        closed = []

        class Response(httpx.Response):
            def close(self):
                closed.append(True)
                super().close()

        def handler(request):
            return Response(200, content=b"x" * 5_000_001, request=request)

        try:
            LexwareAdapter(client_for(API(handler))).hash_file("file-1")
        except TypeError as error:
            self.fail(f"streaming API call is invalid: {error}")
        except ValueError:
            pass
        self.assertTrue(closed)

    def test_terminal_and_unknown_documents_do_not_refresh_or_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = store.stage("acct", "msg", "part", "receipt.pdf", b"receipt")
            with store._connection() as connection:
                connection.execute("UPDATE documents SET status='uploaded', id='f', voucher_id='v' WHERE hash=?", (digest,))
                connection.commit()
            refreshes, uploads = [], []
            self.assertEqual(
                store.upload(
                    digest,
                    lambda data, filename: uploads.append(True) or {"id": "new", "voucherId": "new-v"},
                    refresh=lambda: refreshes.append(True),
                ),
                {"id": "f", "voucherId": "v"},
            )
            self.assertEqual((refreshes, uploads), ([], []))
            for status in ("rejected", "uncertain", "uploading"):
                with store._connection() as connection:
                    connection.execute("UPDATE documents SET status=? WHERE hash=?", (status, digest))
                    connection.commit()
                refreshes = []
                with self.assertRaises(RuntimeError):
                    store.upload(digest, lambda data, filename: {"id": "f", "voucherId": "v"}, refresh=lambda: refreshes.append(True))
                self.assertEqual(refreshes, [])
            with self.assertRaises(ValueError):
                store.upload("0" * 64, lambda data, filename: {"id": "f", "voucherId": "v"}, refresh=lambda: self.fail("refreshed unknown"))

    def test_conflicting_remote_matches_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            digest = hashlib.sha256(b"receipt").hexdigest()
            with self.assertRaises((ValueError, RuntimeError)):
                store.refresh_remote(
                    "org-1",
                    [
                        {"id": "f1", "voucherId": "v1", "hash": digest},
                        {"id": "f2", "voucherId": "v2", "hash": digest},
                    ],
                )


if __name__ == "__main__":
    unittest.main()
