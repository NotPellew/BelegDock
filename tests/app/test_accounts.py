import unittest
from unittest.mock import Mock, patch

from belegdock import accounts


class AccountTests(unittest.TestCase):
    def test_store_and_load_use_native_backend(self):
        backend = Mock()
        backend.get_password.return_value = "synthetic-secret"
        with patch.object(accounts, "native_backend", return_value=backend):
            accounts.save_secret("lexware", "synthetic-secret")
            value = accounts.load_secret("lexware")
        backend.set_password.assert_called_once_with("BelegDock", "lexware", "synthetic-secret")
        backend.get_password.assert_called_once_with("BelegDock", "lexware")
        self.assertEqual(value, "synthetic-secret")

    def test_missing_credentials_fail_explicitly(self):
        backend = Mock()
        backend.get_password.return_value = None
        with patch.object(accounts, "native_backend", return_value=backend):
            with self.assertRaisesRegex(RuntimeError, "Connect"):
                accounts.load_secret("gmail")

    def test_backend_errors_do_not_expose_secrets(self):
        backend = Mock()
        backend.set_password.side_effect = RuntimeError("synthetic-private-value")
        with patch.object(accounts, "native_backend", return_value=backend):
            with self.assertRaises(RuntimeError) as caught:
                accounts.save_secret("lexware", "synthetic-private-value")
        self.assertNotIn("synthetic-private-value", str(caught.exception))

    def test_unsupported_platform_has_no_plaintext_fallback(self):
        with patch("sys.platform", "unsupported"):
            with self.assertRaisesRegex(RuntimeError, "credential store"):
                accounts.native_backend()

    def test_empty_secret_is_not_stored(self):
        backend = Mock()
        with patch.object(accounts, "native_backend", return_value=backend):
            with self.assertRaises(ValueError):
                accounts.save_secret("lexware", " ")
        backend.set_password.assert_not_called()
