from contextlib import contextmanager
import unittest

from belegdock.integrations import LexwareAdapter


class Response:
    def __init__(self, status_code, body=None, content=b"", text="private remote data"):
        self.status_code = status_code
        self._body = body
        self.content = content
        self.text = text

    def json(self):
        return self._body

    def iter_bytes(self, chunk_size=65536):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @contextmanager
    def stream(self, method, *args, **kwargs):
        assert method == "GET"
        yield self.get(*args, **kwargs)

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


class ReconciliationAdapterTests(unittest.TestCase):
    def test_verification_reads_matching_file_and_voucher_relationship(self):
        client = Client(
            [
                Response(200, content=b"receipt"),
                Response(200, {"id": "voucher-1", "files": ["file-1"]}),
            ]
        )

        try:
            result = LexwareAdapter(client).verify_existing("file-1", "voucher-1")
        except AttributeError:
            result = b""

        self.assertEqual(result, b"receipt")
        self.assertEqual(
            [call[0][0] for call in client.calls],
            ["https://api.lexware.io/v1/files/file-1", "https://api.lexware.io/v1/vouchers/voucher-1"],
        )
        self.assertEqual([call[1]["timeout"] for call in client.calls], [30, 30])

    def test_verification_fails_closed_when_voucher_does_not_reference_file(self):
        client = Client(
            [
                Response(200, content=b"receipt"),
                Response(200, {"id": "voucher-1", "files": ["other-file"]}),
            ]
        )

        try:
            LexwareAdapter(client).verify_existing("file-1", "voucher-1")
        except RuntimeError as error:
            message = str(error)
        except AttributeError:
            message = "not implemented"
        else:
            message = "verification unexpectedly succeeded"

        self.assertRegex(message, "voucher.*file|file.*voucher")
        self.assertNotIn("private remote data", message)

    def test_verification_hides_remote_failure_text(self):
        client = Client([Response(500, text="private remote data")])

        try:
            LexwareAdapter(client).verify_existing("file-1", "voucher-1")
        except RuntimeError as error:
            message = str(error)
        except AttributeError:
            message = "not implemented"
        else:
            message = "verification unexpectedly succeeded"

        self.assertRegex(message, "file.*verification|verification.*file")
        self.assertNotIn("private remote data", message)


if __name__ == "__main__":
    unittest.main()
