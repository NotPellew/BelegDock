from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import re
from unittest.mock import Mock, patch

import httplib2
import httpx
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from belegdock import accounts, cli
from belegdock.integrations import LexwareAdapter

GMAIL_SECRET = '{"refresh_token": "review-gmail-canary"}'
LEXWARE_SECRET = "review-lexware-canary"


def invoke_cli(*arguments: str) -> tuple[int, str, str]:
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        exit_code = cli.main(list(arguments))
    return exit_code, output.getvalue(), error.getvalue()


class Backend:
    def __init__(self, secrets: dict[str, str] | None = None, read_error: Exception | None = None):
        self.secrets = dict(secrets or {})
        self.read_error = read_error
        self.writes: list[tuple[str, str]] = []

    def get_password(self, service: str, name: str) -> str | None:
        if self.read_error is not None:
            raise self.read_error
        return self.secrets.get(name)

    def set_password(self, service: str, name: str, value: str) -> None:
        self.writes.append((name, value))
        self.secrets[name] = value


def full_backend() -> Backend:
    return Backend({"gmail": GMAIL_SECRET, "lexware": LEXWARE_SECRET})


def http_error(status: int, reason: str | None = None) -> HttpError:
    errors = [{"reason": reason}] if reason else []
    content = json.dumps({"error": {"code": status, "errors": errors}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), content)


def lexware_adapter(handler) -> LexwareAdapter:
    return LexwareAdapter(httpx.Client(transport=httpx.MockTransport(handler)))


def lexware_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"organizationId": "org-review"}, request=request)


def run_gmail_online(*, valid: bool = True, refresh_error: Exception | None = None, execute_error: Exception | None = None):
    credentials = Mock(valid=valid)
    credentials.to_json.return_value = GMAIL_SECRET
    if refresh_error is not None:
        credentials.refresh.side_effect = refresh_error
    credentials_module = Mock()
    credentials_module.Credentials.from_authorized_user_info.return_value = credentials
    modules = {"google.oauth2.credentials": credentials_module, "google.auth.transport.requests": Mock()}
    service = Mock()
    execute = service.users.return_value.getProfile.return_value.execute
    if execute_error is not None:
        execute.side_effect = execute_error
    else:
        execute.return_value = {"emailAddress": "review@example.invalid"}
    backend = full_backend()
    with (
        patch.object(cli.accounts, "native_backend", return_value=backend),
        patch.object(cli, "import_module", side_effect=modules.__getitem__),
        patch.object(cli, "build_gmail", return_value=service),
        patch.object(cli, "lexware_client", return_value=lexware_adapter(lexware_ok)),
    ):
        exit_code, output, error = invoke_cli("doctor", "--online", "--json")
    return exit_code, json.loads(output), output + error, backend, credentials


def test_gmail_transport_error_mentioning_auth_words_is_error_not_rejected():
    message = "Failed to reach oauth2.googleapis.com: 401 auth unauthorized 403"
    exit_code, data, _, _, _ = run_gmail_online(valid=False, refresh_error=TransportError(message))

    assert exit_code == 1
    assert data["online"]["gmail"]["status"] == "error"


def test_gmail_oserror_during_probe_is_error():
    exit_code, data, _, _, _ = run_gmail_online(execute_error=OSError("auth failure 401 on socket"))

    assert exit_code == 1
    assert data["online"]["gmail"]["status"] == "error"


def test_gmail_refresh_error_is_rejected_even_without_auth_words():
    _, data, _, _, _ = run_gmail_online(valid=False, refresh_error=RefreshError("Token has been expired or revoked."))

    assert data["online"]["gmail"]["status"] == "rejected"


def test_gmail_http_401_is_rejected():
    _, data, _, _, _ = run_gmail_online(execute_error=http_error(401))

    assert data["online"]["gmail"]["status"] == "rejected"


def test_gmail_http_403_rate_limit_is_error():
    for reason in ("rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"):
        exit_code, data, _, _, _ = run_gmail_online(execute_error=http_error(403, reason))

        assert exit_code == 1, reason
        assert data["online"]["gmail"]["status"] == "error", reason


def test_gmail_http_403_auth_reason_is_rejected():
    for reason in ("insufficientPermissions", "authError"):
        _, data, _, _, _ = run_gmail_online(execute_error=http_error(403, reason))

        assert data["online"]["gmail"]["status"] == "rejected", reason


def test_gmail_http_403_without_reason_is_error():
    _, data, _, _, _ = run_gmail_online(execute_error=http_error(403))

    assert data["online"]["gmail"]["status"] == "error"


def test_gmail_http_500_is_error():
    _, data, _, _, _ = run_gmail_online(execute_error=http_error(500, "backendError"))

    assert data["online"]["gmail"]["status"] == "error"


def test_gmail_online_success_through_real_client_path():
    exit_code, data, _, _, _ = run_gmail_online()

    assert exit_code == 0
    assert data["online"]["gmail"]["status"] == "ok"
    assert data["online"]["gmail"]["account"] == "review@example.invalid"


def test_online_doctor_does_not_refresh_into_the_credential_store():
    _, data, _, backend, credentials = run_gmail_online(valid=False)

    assert credentials.refresh.call_count == 1
    assert backend.writes == []
    assert credentials.to_json.call_count == 0
    assert data["online"]["gmail"]["status"] == "ok"


def test_lexware_transport_error_with_auth_words_is_error_not_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unauthorized forbidden 401 403", request=request)

    with (
        patch.object(cli.accounts, "native_backend", return_value=full_backend()),
        patch.object(cli, "gmail_client", return_value=("a@example.invalid", Mock())),
        patch.object(cli, "lexware_client", return_value=lexware_adapter(handler)),
    ):
        exit_code, output, _ = invoke_cli("doctor", "--online", "--json")

    assert exit_code == 1
    assert json.loads(output)["online"]["lexware"]["status"] == "error"


def test_lexware_rate_limit_is_error_and_auth_statuses_are_rejected():
    for status, expected in ((429, "error"), (500, "error"), (401, "rejected"), (403, "rejected")):
        with (
            patch.object(cli.accounts, "native_backend", return_value=full_backend()),
            patch.object(cli, "gmail_client", return_value=("a@example.invalid", Mock())),
            patch.object(
                cli,
                "lexware_client",
                return_value=lexware_adapter(lambda request, status=status: httpx.Response(status, request=request)),
            ),
        ):
            _, output, _ = invoke_cli("doctor", "--online", "--json")

        assert json.loads(output)["online"]["lexware"]["status"] == expected, status


def test_lexware_adapter_without_probe_profile_is_not_reported_ok():
    with (
        patch.object(cli.accounts, "native_backend", return_value=full_backend()),
        patch.object(cli, "gmail_client", return_value=("a@example.invalid", Mock())),
        patch.object(cli, "lexware_client", return_value=Mock(spec=[])),
    ):
        exit_code, output, _ = invoke_cli("doctor", "--online", "--json")

    data = json.loads(output)
    assert exit_code == 1
    assert data["online"]["lexware"]["status"] == "error"
    assert "unbekannt" not in output


def test_keyring_read_failure_is_distinct_from_missing():
    backend = Backend(read_error=RuntimeError("keyring is locked"))
    with patch.object(cli.accounts, "native_backend", return_value=backend):
        exit_code, output, _ = invoke_cli("doctor", "--json")
        _, human, _ = invoke_cli("doctor")

    data = json.loads(output)
    assert exit_code == 1
    assert data["store"]["available"] is True
    for name in ("gmail", "lexware"):
        assert data["credentials"][name].get("state") == "read_failed"
        assert data["credentials"][name]["present"] is not False
    assert "Nicht gespeichert" not in human
    assert "Nicht lesbar" in human


def test_missing_and_present_states_are_stable_codes():
    backend = Backend({"lexware": LEXWARE_SECRET})
    with patch.object(cli.accounts, "native_backend", return_value=backend):
        _, output, _ = invoke_cli("doctor", "--json")

    data = json.loads(output)
    assert data["credentials"]["gmail"].get("state") == "missing"
    assert data["credentials"]["gmail"]["present"] is False
    assert data["credentials"]["lexware"].get("state") == "present"
    assert data["credentials"]["lexware"]["present"] is True


def test_store_unavailable_names_the_store_for_credentials_and_skipped_probes():
    with patch.object(cli.accounts, "native_backend", side_effect=RuntimeError("x")):
        _, output, _ = invoke_cli("doctor", "--online", "--json")
        _, human, _ = invoke_cli("doctor", "--online")

    data = json.loads(output)
    for name in ("gmail", "lexware"):
        assert data["credentials"][name].get("state") == "store_unavailable"
        assert data["online"][name]["status"] == "skipped"
        assert data["online"][name].get("reason") == "store_unavailable"
    assert "Native OS" not in human
    assert "unavailable" not in human
    assert "Übersprungen (Anmeldedatenspeicher nicht verfügbar)" in human
    assert "keine Anmeldedaten" not in human


def test_missing_secret_skip_reason_names_missing_credentials():
    with patch.object(cli.accounts, "native_backend", return_value=Backend({"lexware": LEXWARE_SECRET})):
        with patch.object(cli, "lexware_client", return_value=lexware_adapter(lexware_ok)):
            _, output, _ = invoke_cli("doctor", "--online", "--json")

    data = json.loads(output)
    assert data["online"]["gmail"]["status"] == "skipped"
    assert data["online"]["gmail"].get("reason") == "missing"


def test_whitespace_only_secret_is_missing_for_both_has_secret_and_load_secret():
    backend = Backend({"gmail": "   \n", "lexware": ""})
    with patch.object(accounts, "native_backend", return_value=backend):
        presence = [accounts.has_secret("gmail"), accounts.has_secret("lexware")]
        raised = []
        for name in ("gmail", "lexware"):
            try:
                accounts.load_secret(name)
            except RuntimeError:
                raised.append(name)

    assert presence == [False, False]
    assert raised == ["gmail", "lexware"]


def test_rejected_lines_name_the_recovery_commands():
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with (
        patch.object(cli.accounts, "native_backend", return_value=full_backend()),
        patch.object(cli, "gmail_client", side_effect=cli.RemoteAuthError(401)),
        patch.object(cli, "lexware_client", return_value=lexware_adapter(rejected)),
    ):
        _, output, _ = invoke_cli("doctor", "--online")

    lines = {line.split(":")[0].strip(): line for line in output.splitlines()}
    assert "belegdock login-gmail --client CLIENT_JSON" in lines["Gmail-Verbindung"]
    assert "belegdock login-lexware" in lines["Lexware-Verbindung"]


def test_failure_lines_have_no_nested_parentheses():
    with (
        patch.object(cli.accounts, "native_backend", return_value=full_backend()),
        patch.object(cli, "gmail_client", side_effect=TransportError("down")),
        patch.object(cli, "lexware_client", return_value=lexware_adapter(lambda r: httpx.Response(500, request=r))),
    ):
        _, output, _ = invoke_cli("doctor", "--online")

    assert "Fehlgeschlagen" in output
    for line in output.splitlines():
        assert not re.search(r"\([^()]*\(", line), line


def test_help_and_quick_start_describe_the_offline_default_and_list_doctor():
    _, top_help, _ = invoke_cli("--help")
    _, doctor_help, _ = invoke_cli("doctor", "--help")

    assert "belegdock doctor" in top_help.split("Schnellstart:", 1)[1]
    assert "nur mit --online" in top_help
    assert "nur mit --online" in doctor_help
