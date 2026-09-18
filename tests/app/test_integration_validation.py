import unittest

from belegdock.integrations import GmailAdapter, LexwareAdapter


def response(value):
    class Response:
        def execute(self):
            return value

    return Response()


class MinimalGmailService:
    def __init__(self, part):
        self.part = part

    def users(self):
        return self

    def labels(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        if "labelIds" in kwargs:
            return response({"messages": [{"id": "message-1"}]})
        return response({"labels": [{"id": "label-1", "name": "Invoices"}]})

    def get(self, **kwargs):
        return response({"payload": self.part})


class MinimalLexwareClient:
    def __init__(self, body):
        self.body = body

    def post(self, *args, **kwargs):
        class Response:
            status_code = 202

            def json(inner_self):
                return self.body

        return Response()


class IntegrationValidationTests(unittest.TestCase):
    def test_gmail_rejects_document_part_without_retrievable_source(self):
        service = MinimalGmailService(
            {
                "partId": "1",
                "filename": "invoice.pdf",
                "body": {"size": 4},
            }
        )

        with self.assertRaises(ValueError):
            GmailAdapter(service).candidates("Invoices")

    def test_gmail_rejects_document_part_without_part_id(self):
        service = MinimalGmailService(
            {
                "partId": "",
                "filename": "invoice.xml",
                "body": {"attachmentId": "attachment-1", "size": 4},
            }
        )

        with self.assertRaises(ValueError):
            GmailAdapter(service).candidates("Invoices")

    def test_lexware_rejects_non_string_remote_ids(self):
        client = MinimalLexwareClient({"id": 123, "voucherId": "voucher-1"})

        with self.assertRaises(ValueError):
            LexwareAdapter(client).upload(b"data", "invoice.pdf")

    def test_lexware_success_returns_only_validated_remote_ids(self):
        client = MinimalLexwareClient(
            {"id": "file-1", "voucherId": "voucher-1", "unexpected": "document-content"}
        )

        result = LexwareAdapter(client).upload(b"data", "invoice.pdf")

        self.assertEqual(result, {"id": "file-1", "voucherId": "voucher-1"})


if __name__ == "__main__":
    unittest.main()
