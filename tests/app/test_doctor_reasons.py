from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from unittest.mock import patch

import httplib2
import httpx
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from belegdock import cli, doctor
from belegdock.integrations import LexwareAdapter


def http_error(status: int, reason: str | None = None) -> HttpError:
    errors = [{"reason": reason}] if reason else []
    content = json.dumps({"error": {"code": status, "errors": errors}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), content)


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (httplib2.ServerNotFoundError("Unable to find the server"), "error", "connection"),
        (http_error(403, "accessNotConfigured"), "error", "service_error"),
        (http_error(403, "forbidden"), "error", "service_error"),
        (http_error(403, "rateLimitExceeded"), "error", "rate_limited"),
        (http_error(403, "dailyLimitExceeded"), "error", "rate_limited"),
        (http_error(403, "quotaExceeded"), "error", "rate_limited"),
        (http_error(403), "error", "service_error"),
        (http_error(401), "rejected", "http_401"),
        (http_error(403, "authError"), "rejected", "http_403_auth"),
        (RefreshError("invalid_grant"), "rejected", "refresh_rejected"),
        (RefreshError("temporarily unavailable", retryable=True), "error", "service_error"),
        (json.JSONDecodeError("Expecting value", "x", 0), "rejected", "invalid_credentials"),
        (ValueError("missing fields refresh_token"), "rejected", "invalid_credentials"),
    ],
)
def test_gmail_error_reason_codes(error, status, reason):
    result = doctor.classify_gmail_error(error)

    assert (result["status"], result["reason"]) == (status, reason)


def test_corrupt_gmail_secret_names_the_login_command():
    class Backend:
        def get_password(self, service, name):
            return {"gmail": "not-json", "lexware": "lexware-canary"}[name]

    def lexware_ok(request):
        return httpx.Response(200, json={"organizationId": "org"}, request=request)

    output, error = StringIO(), StringIO()
    with (
        patch.object(cli.accounts, "native_backend", return_value=Backend()),
        patch.object(cli, "lexware_client", return_value=LexwareAdapter(httpx.Client(transport=httpx.MockTransport(lexware_ok)))),
        redirect_stdout(output),
        redirect_stderr(error),
    ):
        exit_code = cli.main(["doctor", "--online"])

    assert exit_code == 1
    gmail_line = next(line for line in output.getvalue().splitlines() if "Gmail-Verbindung" in line)
    assert "belegdock login-gmail --client CLIENT_JSON" in gmail_line
    assert "not-json" not in output.getvalue() + error.getvalue()


def test_online_help_distinguishes_memory_from_credential_store():
    output = StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit):
        cli.main(["doctor", "--help"])

    help_text = " ".join(output.getvalue().split())
    assert "Arbeitsspeicher" in help_text
    assert "Anmeldedatenspeicher wird nicht geändert" in help_text
