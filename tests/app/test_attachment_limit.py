import unittest
from unittest.mock import patch

from belegdock.integrations import GmailAdapter


class AttachmentLimitTests(unittest.TestCase):
    def test_oversized_encoding_is_rejected_before_decoding(self):
        adapter = GmailAdapter(None)
        candidate = {"size": 1, "inline_data": "A" * 6_666_672}
        with patch("belegdock.integrations.base64.b64decode", return_value=b"x") as decode:
            with self.assertRaises(ValueError):
                adapter.fetch(candidate)
        decode.assert_not_called()
