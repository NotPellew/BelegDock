import base64
import unittest

from belegdock.integrations import GmailAdapter, LexwareAdapter


def request(value):
    class Request:
        def execute(self):
            return value

    return Request()


class FakeGmailService:
    def __init__(self):
        self.label_calls = []
        self.message_list_calls = []
        self.message_get_calls = []
        self.attachment_calls = []
        self.pages = [
            {"messages": [{"id": "m1"}], "nextPageToken": "page-2"},
            {"messages": [{"id": "m2"}]},
        ]
        self.message_data = {
            "m1": {
                "id": "m1",
                "payload": {
                    "parts": [
                        {
                            "partId": "0",
                            "mimeType": "multipart/mixed",
                            "parts": [
                                {
                                    "partId": "1",
                                    "filename": "invoice.pdf",
                                    "mimeType": "application/pdf",
                                    "body": {
                                        "attachmentId": "att-1",
                                        "size": 4,
                                    },
                                },
                                {
                                    "partId": "2",
                                    "filename": "readme.txt",
                                    "mimeType": "text/plain",
                                    "body": {"data": "bm8="},
                                },
                            ],
                        }
                    ]
                },
            },
            "m2": {
                "id": "m2",
                "payload": {
                    "parts": [
                        {
                            "partId": "3",
                            "filename": "receipt.xml",
                            "mimeType": "application/xml",
                            "body": {"data": base64.urlsafe_b64encode(b"<r/>").decode()},
                        },
                        {
                            "partId": "4",
                            "filename": "too-large.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "att-big", "size": 5_000_001},
                        },
                    ]
                },
            },
        }

    def users(self):
        return self

    def labels(self):
        owner = self

        class Labels:
            def list(self, **kwargs):
                owner.label_calls.append(kwargs)
                return request({"labels": [{"id": "LBL", "name": "Invoices"}]})

        return Labels()

    def messages(self):
        return self

    def attachments(self):
        return self

    def list(self, **kwargs):
        if "name" in kwargs:
            self.label_calls.append(kwargs)
            return request({"labels": [{"id": "LBL", "name": "Invoices"}]})
        self.message_list_calls.append(kwargs)
        page = self.pages[0] if kwargs.get("pageToken") is None else self.pages[1]
        return request(page)

    def get(self, **kwargs):
        if "format" in kwargs:
            self.message_get_calls.append(kwargs)
            return request(self.message_data[kwargs["id"]])
        self.attachment_calls.append(kwargs)
        return request({"size": 4, "data": base64.urlsafe_b64encode(b"%PDF").decode()})


class GmailAdapterTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeGmailService()
        self.adapter = GmailAdapter(self.service)

    def test_candidates_resolve_label_paginate_and_walk_nested_parts(self):
        candidates = self.adapter.candidates("Invoices")

        self.assertEqual(
            candidates,
            [
                {
                    "id": "m1:1",
                    "message_id": "m1",
                    "part_id": "1",
                    "filename": "invoice.pdf",
                    "size": 4,
                    "attachment_id": "att-1",
                },
                {
                    "id": "m2:3",
                    "message_id": "m2",
                    "part_id": "3",
                    "filename": "receipt.xml",
                    "size": 4,
                    "inline_data": base64.urlsafe_b64encode(b"<r/>").decode(),
                },
            ],
        )
        self.assertEqual(self.service.label_calls[0]["userId"], "me")
        self.assertEqual(self.service.message_list_calls[0]["labelIds"], ["LBL"])
        self.assertEqual(self.service.message_list_calls[1]["pageToken"], "page-2")
        self.assertEqual(self.service.attachment_calls, [])

    def test_unknown_label_fails_without_listing_messages(self):
        self.service.list = lambda **kwargs: request({"labels": []}) if "name" in kwargs else request({})

        with self.assertRaises(ValueError):
            self.adapter.candidates("Missing")

        self.assertEqual(self.service.message_list_calls, [])

    def test_fetch_external_attachment_and_inline_data(self):
        external = self.adapter.fetch({"message_id": "m1", "part_id": "1", "attachment_id": "att-1", "size": 4})
        inline = self.adapter.fetch(
            {
                "message_id": "m2",
                "part_id": "3",
                "inline_data": base64.urlsafe_b64encode(b"<r/>").decode(),
                "size": 4,
            }
        )

        self.assertEqual(external, b"%PDF")
        self.assertEqual(inline, b"<r/>")
        self.assertEqual(len(self.service.attachment_calls), 1)

    def test_fetch_rejects_size_mismatch_and_malformed_data(self):
        with self.assertRaises(ValueError):
            self.adapter.fetch({"message_id": "m1", "part_id": "1", "attachment_id": "att-1", "size": 5})
        with self.assertRaises(ValueError):
            self.adapter.fetch({"message_id": "m2", "part_id": "3", "inline_data": "%%%", "size": 1})


class FakeResponse:
    def __init__(self, status_code=202, body=None, text="server secret should not escape"):
        self.status_code = status_code
        self.body = body
        self.text = text

    def json(self):
        return self.body


class FakeLexwareClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class LexwareAdapterTests(unittest.TestCase):
    def test_upload_posts_voucher_multipart_and_returns_ids(self):
        client = FakeLexwareClient(FakeResponse(body={"id": "file-1", "voucherId": "voucher-1"}))

        result = LexwareAdapter(client).upload(b"%PDF", "invoice.pdf")

        self.assertEqual(result, {"id": "file-1", "voucherId": "voucher-1"})
        args, kwargs = client.calls[0]
        self.assertEqual(args, ("https://api.lexware.io/v1/files",))
        self.assertEqual(kwargs["data"], {"type": "voucher"})
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["files"]["file"], ("invoice.pdf", b"%PDF", "application/pdf"))

    def test_upload_rejects_bad_input_and_missing_ids(self):
        adapter = LexwareAdapter(FakeLexwareClient(FakeResponse(body={})))

        with self.assertRaises(ValueError):
            adapter.upload(b"data", "invoice.txt")
        with self.assertRaises(ValueError):
            adapter.upload(b"x" * 5_000_001, "invoice.pdf")
        with self.assertRaises(ValueError):
            adapter.upload(b"data", "invoice.pdf")

    def test_upload_rejects_server_failure_without_exposing_response_text(self):
        client = FakeLexwareClient(FakeResponse(status_code=500))

        with self.assertRaises(RuntimeError) as error:
            LexwareAdapter(client).upload(b"data", "invoice.pdf")

        self.assertNotIn("server secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
