from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from unittest.mock import Mock, patch

import httpx

from belegdock import cli
from belegdock.integrations import GmailAdapter, LexwareAdapter
from belegdock.workflow import RemoteAuthError


def invoke_cli(*arguments: str) -> tuple[int, str, str]:
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        exit_code = cli.main(list(arguments))
    return exit_code, output.getvalue(), error.getvalue()


class MockKeyringBackend:
    def __init__(self, secrets: dict[str, str] | None = None, available: bool = True):
        self.secrets = dict(secrets or {})
        self.available = available

    def get_password(self, service: str, name: str) -> str | None:
        if not self.available:
            raise RuntimeError("Native OS credential store unavailable; no plaintext fallback.")
        return self.secrets.get(name)

    def set_password(self, service: str, name: str, value: str) -> None:
        if not self.available:
            raise RuntimeError("Native OS credential store unavailable; no plaintext fallback.")
        self.secrets[name] = value


def test_doctor_offline_all_present():
    backend = MockKeyringBackend(
        secrets={
            "gmail": '{"refresh_token": "mock-gmail-token"}',
            "lexware": "mock-lexware-token",
        }
    )
    with (
        patch.object(cli.accounts, "native_backend", return_value=backend),
        patch.object(cli, "gmail_client", side_effect=AssertionError("offline must make no network calls")),
        patch.object(cli, "lexware_client", side_effect=AssertionError("offline must make no network calls")),
    ):
        exit_code, output, error = invoke_cli("doctor")

    assert exit_code == 0
    assert error == ""
    assert "BelegDock-Diagnose:" in output
    assert "Anmeldedatenspeicher: Verfügbar" in output
    assert "Gmail-Anmeldedaten: Gespeichert" in output
    assert "Lexware-Anmeldedaten: Gespeichert" in output
    assert "Gmail-Verbindung" not in output
    assert "Lexware-Verbindung" not in output


def test_doctor_offline_store_unavailable():
    with patch.object(
        cli.accounts,
        "native_backend",
        side_effect=RuntimeError("Native OS credential store unavailable; no plaintext fallback."),
    ):
        exit_code, output, error = invoke_cli("doctor")

    assert exit_code == 1
    assert "BelegDock-Diagnose:" in output
    assert "Anmeldedatenspeicher: Nicht verfügbar" in output
    assert "Gespeichert" not in output


def test_doctor_offline_secrets_missing():
    # Both missing
    backend_none = MockKeyringBackend(secrets={})
    with patch.object(cli.accounts, "native_backend", return_value=backend_none):
        exit_code, output, error = invoke_cli("doctor")

    assert exit_code == 1
    assert "BelegDock-Diagnose:" in output
    assert "Anmeldedatenspeicher: Verfügbar" in output
    assert "Gmail-Anmeldedaten: Nicht gespeichert" in output
    assert "Lexware-Anmeldedaten: Nicht gespeichert" in output

    # Only Gmail missing
    backend_lexware_only = MockKeyringBackend(secrets={"lexware": "token"})
    with patch.object(cli.accounts, "native_backend", return_value=backend_lexware_only):
        exit_code, output, error = invoke_cli("doctor")

    assert exit_code == 1
    assert "Gmail-Anmeldedaten: Nicht gespeichert" in output
    assert "Lexware-Anmeldedaten: Gespeichert" in output

    # Only Lexware missing
    backend_gmail_only = MockKeyringBackend(secrets={"gmail": '{"token": "test"}'})
    with patch.object(cli.accounts, "native_backend", return_value=backend_gmail_only):
        exit_code, output, error = invoke_cli("doctor")

    assert exit_code == 1
    assert "Gmail-Anmeldedaten: Gespeichert" in output
    assert "Lexware-Anmeldedaten: Nicht gespeichert" in output


def test_doctor_online_probes_success():
    backend = MockKeyringBackend(
        secrets={
            "gmail": '{"refresh_token": "mock-gmail-token"}',
            "lexware": "mock-lexware-token",
        }
    )
    lexware_requests: list[httpx.Request] = []

    def lexware_handler(request: httpx.Request) -> httpx.Response:
        lexware_requests.append(request)
        if request.url.path == "/v1/profile":
            return httpx.Response(200, json={"organizationId": "org-doctor-test-456"}, request=request)
        raise AssertionError(f"Unexpected Lexware endpoint accessed during doctor probe: {request.url}")

    lexware_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_handler)))

    gmail_service = Mock()
    gmail_service.users().getProfile(userId="me").execute.return_value = {
        "emailAddress": "doctor-user@example.com"
    }
    gmail_adapter = GmailAdapter(gmail_service)

    with (
        patch.object(cli.accounts, "native_backend", return_value=backend),
        patch.object(cli, "gmail_client", return_value=("doctor-user@example.com", gmail_adapter)),
        patch.object(cli, "lexware_client", return_value=lexware_adapter),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online")

    assert exit_code == 0
    assert error == ""
    assert "BelegDock-Diagnose:" in output
    assert "Anmeldedatenspeicher: Verfügbar" in output
    assert "Gmail-Anmeldedaten: Gespeichert" in output
    assert "Lexware-Anmeldedaten: Gespeichert" in output
    assert "Gmail-Verbindung: Erfolgreich" in output
    assert "doctor-user@example.com" in output
    assert "Lexware-Verbindung: Erfolgreich" in output
    assert "org-doctor-test-456" in output

    assert len(lexware_requests) == 1
    assert lexware_requests[0].method == "GET"
    assert lexware_requests[0].url.path == "/v1/profile"


def test_doctor_online_credential_rejected():
    secret_lexware = "SECRET_CANARY_LEXWARE_REJECTED_KEY"
    backend = MockKeyringBackend(
        secrets={
            "gmail": '{"refresh_token": "mock-gmail-token"}',
            "lexware": secret_lexware,
        }
    )

    def lexware_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"}, request=request)

    lexware_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_handler)))

    with (
        patch.object(cli.accounts, "native_backend", return_value=backend),
        patch.object(cli, "gmail_client", return_value=("user@example.com", Mock())),
        patch.object(cli, "lexware_client", return_value=lexware_adapter),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online")

    assert exit_code == 1
    assert "Lexware-Verbindung: Abgelehnt" in output or "Lexware-Verbindung: Abgelehnt" in error
    assert secret_lexware not in output
    assert secret_lexware not in error

    # Gmail rejected case
    secret_gmail = "SECRET_CANARY_GMAIL_REJECTED_TOKEN"
    backend_gmail_bad = MockKeyringBackend(
        secrets={
            "gmail": f'{{"refresh_token": "{secret_gmail}"}}',
            "lexware": "mock-lexware-token",
        }
    )

    def lexware_ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"organizationId": "org-ok"}, request=request)

    lexware_ok_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_ok_handler)))

    with (
        patch.object(cli.accounts, "native_backend", return_value=backend_gmail_bad),
        patch.object(cli, "gmail_client", side_effect=RemoteAuthError(401)),
        patch.object(cli, "lexware_client", return_value=lexware_ok_adapter),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online")

    assert exit_code == 1
    assert "Gmail-Verbindung: Abgelehnt" in output or "Gmail-Verbindung: Abgelehnt" in error
    assert secret_gmail not in output
    assert secret_gmail not in error


def test_doctor_never_exposes_stored_secrets():
    canary_gmail = "ULTRA_SECRET_CANARY_GMAIL_9999"
    canary_lexware = "ULTRA_SECRET_CANARY_LEXWARE_8888"
    backend = MockKeyringBackend(
        secrets={
            "gmail": f'{{"token": "{canary_gmail}"}}',
            "lexware": canary_lexware,
        }
    )

    def lexware_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "Forbidden"}, request=request)

    lexware_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_handler)))

    scenarios = [
        ["doctor"],
        ["doctor", "--json"],
        ["doctor", "--online"],
        ["doctor", "--online", "--json"],
    ]

    for args in scenarios:
        with (
            patch.object(cli.accounts, "native_backend", return_value=backend),
            patch.object(cli, "gmail_client", side_effect=RemoteAuthError(401)),
            patch.object(cli, "lexware_client", return_value=lexware_adapter),
        ):
            exit_code, output, error = invoke_cli(*args)

        assert exit_code in (0, 1)
        assert canary_gmail not in output
        assert canary_gmail not in error
        assert canary_lexware not in output
        assert canary_lexware not in error


def test_doctor_json_output_and_exit_codes():
    backend_all_ok = MockKeyringBackend(
        secrets={
            "gmail": '{"token": "g-tok"}',
            "lexware": "l-tok",
        }
    )

    # 1. Offline success
    with patch.object(cli.accounts, "native_backend", return_value=backend_all_ok):
        exit_code, output, error = invoke_cli("doctor", "--json")

    assert exit_code == 0
    assert error == ""
    data = json.loads(output)
    assert data["ok"] is True
    assert data["store"]["available"] is True
    assert data["store"]["error"] is None
    assert data["credentials"]["gmail"]["present"] is True
    assert data["credentials"]["lexware"]["present"] is True
    assert data.get("online") is None

    # 2. Offline store unavailable
    with patch.object(
        cli.accounts,
        "native_backend",
        side_effect=RuntimeError("Native OS credential store unavailable; no plaintext fallback."),
    ):
        exit_code, output, error = invoke_cli("doctor", "--json")

    assert exit_code == 1
    data = json.loads(output)
    assert data["ok"] is False
    assert data["store"]["available"] is False
    assert "unavailable" in data["store"]["error"].lower() or "nicht verfügbar" in data["store"]["error"].lower()
    assert data["credentials"]["gmail"]["present"] is False
    assert data["credentials"]["lexware"]["present"] is False

    # 3. Offline missing credentials
    backend_missing = MockKeyringBackend(secrets={"lexware": "l-tok"})
    with patch.object(cli.accounts, "native_backend", return_value=backend_missing):
        exit_code, output, error = invoke_cli("doctor", "--json")

    assert exit_code == 1
    data = json.loads(output)
    assert data["ok"] is False
    assert data["credentials"]["gmail"]["present"] is False
    assert data["credentials"]["lexware"]["present"] is True

    # 4. Online success
    def lexware_ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"organizationId": "org-json-789"}, request=request)

    lexware_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_ok_handler)))
    with (
        patch.object(cli.accounts, "native_backend", return_value=backend_all_ok),
        patch.object(cli, "gmail_client", return_value=("json-user@example.com", Mock())),
        patch.object(cli, "lexware_client", return_value=lexware_adapter),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online", "--json")

    assert exit_code == 0
    assert error == ""
    data = json.loads(output)
    assert data["ok"] is True
    assert data["online"]["gmail"]["status"] == "ok"
    assert data["online"]["gmail"]["account"] == "json-user@example.com"
    assert data["online"]["lexware"]["status"] == "ok"
    assert data["online"]["lexware"]["organizationId"] == "org-json-789"

    # 5. Online rejection
    def lexware_rejected_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"}, request=request)

    lexware_bad_adapter = LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_rejected_handler)))
    with (
        patch.object(cli.accounts, "native_backend", return_value=backend_all_ok),
        patch.object(cli, "gmail_client", return_value=("json-user@example.com", Mock())),
        patch.object(cli, "lexware_client", return_value=lexware_bad_adapter),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online", "--json")

    assert exit_code == 1
    data = json.loads(output)
    assert data["ok"] is False
    assert data["online"]["lexware"]["status"] == "rejected"
