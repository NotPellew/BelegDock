import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import httplib2
from google_auth_oauthlib.flow import WSGITimeoutError
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import AccessDeniedError

from belegdock import accounts, cli
from belegdock.workflow import RemoteAuthError
from setup_test_support import require, require_module

READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN = '{"refresh_token":"synthetic-refresh-token"}'
LEXWARE_KEY = "synthetic-lexware-key-0123"


def setup_module_under_test():
    return require_module("belegdock.setup")


def http_error(status):
    content = json.dumps({"error": {"code": status, "errors": []}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), content)


class GmailHarness:
    def __init__(self):
        self.credentials = Mock()
        self.credentials.to_json.return_value = TOKEN
        self.flow_module = Mock()
        self.discovery = Mock()
        self.calls = []
        self.flow = self.flow_module.InstalledAppFlow.from_client_secrets_file.return_value
        self.flow.run_local_server.return_value = self.credentials
        profile = self.discovery.build.return_value.users.return_value.getProfile.return_value
        profile.execute.side_effect = self._profile
        self.importer = {
            "google_auth_oauthlib.flow": self.flow_module,
            "googleapiclient.discovery": self.discovery,
        }.__getitem__

    def _profile(self):
        self.calls.append("profile")
        return {"emailAddress": "tester@example.test"}

    @property
    def profile(self):
        return self.discovery.build.return_value.users.return_value.getProfile.return_value.execute


class GmailAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.module = setup_module_under_test()
        self.harness = GmailHarness()
        backend = patch.object(accounts, "native_backend", return_value=Mock())
        backend.start()
        self.addCleanup(backend.stop)
        self.save = Mock(side_effect=lambda *args: self.harness.calls.append("save"))
        saver = patch.object(accounts, "save_secret", self.save)
        saver.start()
        self.addCleanup(saver.stop)

    def guided(self, **options):
        authorize = require(self.module, "authorize_gmail_guided")
        return authorize(Path("client.json"), importer=self.harness.importer, **options)

    def test_guided_flow_is_bounded_readonly_and_does_not_save(self):
        result = self.guided(timeout_seconds=120)

        self.harness.flow_module.InstalledAppFlow.from_client_secrets_file.assert_called_once_with(
            "client.json", READONLY
        )
        options = self.harness.flow.run_local_server.call_args.kwargs
        self.harness.flow.run_local_server.assert_called_once()
        self.assertEqual((options["port"], options["timeout_seconds"]), (0, 120))
        self.assertEqual(result.account, "tester@example.test")
        self.assertEqual(result.token, TOKEN)
        self.save.assert_not_called()

    def test_authorization_repr_hides_the_token(self):
        result = self.guided(timeout_seconds=120)

        self.assertNotIn("synthetic-refresh-token", repr(result))

    def test_save_gmail_writes_only_the_gmail_secret(self):
        result = self.guided(timeout_seconds=120)

        require(self.module, "save_gmail")(result)

        self.save.assert_called_once_with("gmail", TOKEN)

    def test_save_failure_is_reported_as_store_error_without_secret(self):
        result = self.guided(timeout_seconds=120)
        self.save.side_effect = RuntimeError(TOKEN)

        with self.assertRaises(require(self.module, "SetupError")) as caught:
            require(self.module, "save_gmail")(result)

        self.assertEqual(caught.exception.code, "store")
        self.assertNotIn("synthetic-refresh-token", str(caught.exception))

    def test_failures_map_to_stable_codes_and_never_save(self):
        error_type = require(self.module, "SetupError")
        cases = [
            ("client_file", "client", FileNotFoundError("/home/private/client.json")),
            ("client_file", "client", PermissionError("/home/private/client.json")),
            ("client_file", "client", ValueError("Client secrets must be for a web or installed app.")),
            ("denied", "browser", AccessDeniedError()),
            ("timeout", "browser", WSGITimeoutError("waited")),
            ("network", "browser", ConnectionError("private-host")),
            ("unexpected", "browser", RuntimeError("private-detail")),
            ("network", "profile", OSError("private-host")),
            ("rejected", "profile", http_error(401)),
            ("rejected", "profile", http_error(403)),
            ("unexpected", "profile", RuntimeError("private-detail")),
        ]
        for code, stage, failure in cases:
            with self.subTest(code=code, stage=stage, failure=type(failure).__name__):
                self.harness = GmailHarness()
                targets = {
                    "client": self.harness.flow_module.InstalledAppFlow.from_client_secrets_file,
                    "browser": self.harness.flow.run_local_server,
                    "profile": self.harness.profile,
                }
                targets[stage].side_effect = failure

                with self.assertRaises(error_type) as caught:
                    self.guided(timeout_seconds=120)

                self.assertEqual(caught.exception.code, code)
                for private in ("private", "/home"):
                    self.assertNotIn(private, str(caught.exception))
        self.save.assert_not_called()

    def test_unavailable_store_fails_before_any_google_call(self):
        error_type = require(self.module, "SetupError")
        importer = Mock()
        with patch.object(accounts, "native_backend", side_effect=RuntimeError("no store")):
            with self.assertRaises(error_type) as caught:
                require(self.module, "authorize_gmail_guided")(
                    Path("client.json"), importer=importer, timeout_seconds=120
                )

        self.assertEqual(caught.exception.code, "store")
        importer.assert_not_called()

    def test_cli_path_keeps_unbounded_flow_raw_errors_and_saves_after_profile(self):
        connect = require(self.module, "connect_gmail")

        account = connect(Path("client.json"), importer=self.harness.importer)

        self.assertEqual(account, "tester@example.test")
        self.harness.flow.run_local_server.assert_called_once_with(port=0)
        self.assertEqual(self.harness.calls, ["profile", "save"])
        self.save.assert_called_once_with("gmail", TOKEN)

    def test_cli_path_does_not_save_when_profile_fails_and_raises_original_error(self):
        failure = OSError("profile unreachable")
        self.harness.profile.side_effect = failure

        with self.assertRaises(OSError) as caught:
            require(self.module, "connect_gmail")(Path("client.json"), importer=self.harness.importer)

        self.assertIs(caught.exception, failure)
        self.save.assert_not_called()

    def test_cli_connect_gmail_delegates_with_unchanged_scope(self):
        self.assertEqual(cli.SCOPES, READONLY)
        self.assertEqual(require(self.module, "SCOPES"), READONLY)
        modules = {
            "google_auth_oauthlib.flow": self.harness.flow_module,
            "googleapiclient.discovery": self.harness.discovery,
        }
        with patch.object(cli, "import_module", side_effect=modules.__getitem__):
            account = cli.connect_gmail(Path("client.json"))

        self.assertEqual(account, "tester@example.test")
        self.harness.flow.run_local_server.assert_called_once_with(port=0)
        self.save.assert_called_once_with("gmail", TOKEN)


class FakeLexware:
    def __init__(self, failure=None):
        self.client = Mock()
        self.probe_profile = Mock(side_effect=failure, return_value={"organizationId": "org-1"})


class LexwareKeyTests(unittest.TestCase):
    def setUp(self):
        self.module = setup_module_under_test()
        backend = patch.object(accounts, "native_backend", return_value=Mock())
        backend.start()
        self.addCleanup(backend.stop)
        self.save = Mock()
        saver = patch.object(accounts, "save_secret", self.save)
        saver.start()
        self.addCleanup(saver.stop)

    def validate(self, key, adapter=None):
        factory = Mock(return_value=adapter or FakeLexware())
        validate = require(self.module, "validate_lexware_key")
        return validate(key, client_factory=factory), factory

    def test_valid_key_makes_exactly_one_probe_closes_client_and_saves_nothing(self):
        adapter = FakeLexware()

        _, factory = self.validate(f"  {LEXWARE_KEY}\n", adapter)

        factory.assert_called_once_with(LEXWARE_KEY)
        adapter.probe_profile.assert_called_once_with()
        adapter.client.close.assert_called_once_with()
        self.save.assert_not_called()

    def test_failures_map_to_codes_after_one_probe_without_leaking_the_key(self):
        error_type = require(self.module, "SetupError")
        cases = [
            ("rejected", RemoteAuthError(401)),
            ("rejected", RemoteAuthError(403)),
            ("network", httpx.ConnectError(LEXWARE_KEY)),
            ("network", OSError(LEXWARE_KEY)),
            ("unexpected", RuntimeError(f"HTTP 500 {LEXWARE_KEY}")),
        ]
        for code, failure in cases:
            with self.subTest(code=code, failure=type(failure).__name__):
                adapter = FakeLexware(failure)
                with self.assertRaises(error_type) as caught:
                    self.validate(LEXWARE_KEY, adapter)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(LEXWARE_KEY, str(caught.exception))
                self.assertNotIn(LEXWARE_KEY, repr(caught.exception))
                adapter.probe_profile.assert_called_once_with()
                adapter.client.close.assert_called_once_with()
        self.save.assert_not_called()

    def test_malformed_keys_are_rejected_locally_without_a_request(self):
        error_type = require(self.module, "SetupError")
        for key in ("", "   ", "two words", "schlüssel", "line\nbreak"):
            with self.subTest(key=key):
                factory = Mock()
                with self.assertRaises(error_type) as caught:
                    require(self.module, "validate_lexware_key")(key, client_factory=factory)
                self.assertEqual(caught.exception.code, "invalid_key")
                factory.assert_not_called()

    def test_unavailable_store_is_reported_before_any_request(self):
        error_type = require(self.module, "SetupError")
        factory = Mock()
        with patch.object(accounts, "native_backend", side_effect=RuntimeError("no store")):
            with self.assertRaises(error_type) as caught:
                require(self.module, "validate_lexware_key")(LEXWARE_KEY, client_factory=factory)

        self.assertEqual(caught.exception.code, "store")
        factory.assert_not_called()

    def test_save_stores_the_trimmed_key_only_under_the_lexware_name(self):
        require(self.module, "save_lexware_key")(f" {LEXWARE_KEY} ")

        self.save.assert_called_once_with("lexware", LEXWARE_KEY)

    def test_save_failure_is_a_store_error_without_the_key(self):
        error_type = require(self.module, "SetupError")
        self.save.side_effect = RuntimeError(LEXWARE_KEY)

        with self.assertRaises(error_type) as caught:
            require(self.module, "save_lexware_key")(LEXWARE_KEY)

        self.assertEqual(caught.exception.code, "store")
        self.assertNotIn(LEXWARE_KEY, str(caught.exception))

    def test_default_adapter_sends_the_key_as_bearer_without_following_redirects(self):
        adapter = require(self.module, "lexware_adapter")(LEXWARE_KEY)
        self.addCleanup(adapter.client.close)

        self.assertEqual(adapter.client.headers["Authorization"], f"Bearer {LEXWARE_KEY}")
        self.assertFalse(adapter.client.follow_redirects)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.module = setup_module_under_test()

    def detect(self, store=True, **states):
        with (
            patch.object(accounts, "check_credential_store", return_value=(store, None)),
            patch.object(accounts, "secret_state", side_effect=lambda name: states[name]),
            patch.object(cli, "gmail_client", side_effect=AssertionError("network")),
            patch.object(cli, "lexware_client", side_effect=AssertionError("network")),
        ):
            return require(self.module, "detect_state")()

    def test_detection_reports_store_and_each_credential_offline(self):
        state = self.detect(gmail="present", lexware="missing")

        self.assertTrue(state.store_available)
        self.assertEqual((state.gmail, state.lexware), ("present", "missing"))

    def test_routing_distinguishes_store_setup_and_main(self):
        state_type = require(self.module, "SetupState")
        route = require(self.module, "startup_route")
        cases = [
            (state_type(False, "store_unavailable", "store_unavailable"), "store_unavailable"),
            (state_type(True, "missing", "missing"), "setup"),
            (state_type(True, "present", "missing"), "setup"),
            (state_type(True, "missing", "present"), "setup"),
            (state_type(True, "read_failed", "present"), "setup"),
            (state_type(True, "present", "read_failed"), "setup"),
            (state_type(True, "present", "present"), "main"),
        ]
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(route(state), expected)


if __name__ == "__main__":
    unittest.main()
