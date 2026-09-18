import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from belegdock import cli


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.scope = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.credentials = Mock(valid=True, expired=False, refresh_token="synthetic-refresh")
        self.credentials.to_json.return_value = '{"refresh_token":"synthetic-refresh"}'
        self.flow_module = Mock()
        self.flow_module.InstalledAppFlow.from_client_secrets_file.return_value.run_local_server.return_value = self.credentials
        self.discovery = Mock()
        self.service = self.discovery.build.return_value
        self.service.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "test@example.invalid"}

    def test_connect_gmail_requests_only_readonly_scope_and_stores_in_keyring(self):
        modules = {"google_auth_oauthlib.flow": self.flow_module, "googleapiclient.discovery": self.discovery}
        with patch.object(cli, "import_module", side_effect=modules.__getitem__), patch.object(cli.accounts, "native_backend", return_value=Mock()), patch.object(cli.accounts, "save_secret") as save:
            result = cli.connect_gmail(Path("outside-client.json"))
        self.assertEqual(result, "test@example.invalid")
        self.flow_module.InstalledAppFlow.from_client_secrets_file.assert_called_once_with("outside-client.json", self.scope)
        save.assert_called_once_with("gmail", self.credentials.to_json.return_value)

    def test_gmail_client_loads_native_credentials_and_resolves_account(self):
        credentials_module = Mock()
        credentials_module.Credentials.from_authorized_user_info.return_value = self.credentials
        modules = {"google.oauth2.credentials": credentials_module, "googleapiclient.discovery": self.discovery}
        payload = '{"refresh_token":"synthetic-refresh"}'
        with patch.object(cli, "import_module", side_effect=modules.__getitem__), patch.object(cli.accounts, "load_secret", return_value=payload):
            result = cli.gmail_client()
        self.assertEqual(result[0], "test@example.invalid")
        credentials_module.Credentials.from_authorized_user_info.assert_called_once_with(json.loads(payload), self.scope)

    def test_connect_checks_store_before_browser_authorization(self):
        with patch.object(cli.accounts, "native_backend", side_effect=RuntimeError("credential store unavailable")), patch.object(cli, "import_module") as importer:
            with self.assertRaisesRegex(RuntimeError, "credential store"):
                cli.connect_gmail(Path("outside-client.json"))
        importer.assert_not_called()
