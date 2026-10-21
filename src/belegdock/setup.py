import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from . import accounts, doctor
from .integrations import LexwareAdapter

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_AUTH_TIMEOUT_SECONDS = 180
KEY_PATTERN = re.compile(r"[\x21-\x7e]+")
Importer = Callable[[str], Any]


class SetupError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GmailAuthorization:
    account: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class SetupState:
    store_available: bool
    gmail: str
    lexware: str

    @property
    def needs_setup(self) -> bool:
        return not (self.gmail == "present" and self.lexware == "present")


def _offline(*_arguments: Any) -> Any:
    raise RuntimeError("offline detection makes no remote calls")


def detect_state() -> SetupState:
    result = doctor.detect(online=False, gmail_account=_offline, lexware_remote=_offline)
    credentials = result["credentials"]
    return SetupState(
        store_available=bool(result["store"]["available"]),
        gmail=str(credentials["gmail"]["state"]),
        lexware=str(credentials["lexware"]["state"]),
    )


def startup_route(state: SetupState) -> str:
    if not state.store_available:
        return "store_unavailable"
    return "setup" if state.needs_setup else "main"


def _load_flow(client_path: Path, importer: Importer) -> Any:
    flow_module = importer("google_auth_oauthlib.flow")
    return flow_module.InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)


def _run_flow(flow: Any, timeout_seconds: int | None) -> Any:
    if timeout_seconds is None:
        return flow.run_local_server(port=0)
    return flow.run_local_server(port=0, timeout_seconds=timeout_seconds)


def _fetch_account(credentials: Any, importer: Importer) -> str:
    service = importer("googleapiclient.discovery").build(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )
    return str(service.users().getProfile(userId="me").execute()["emailAddress"])


def authorize_gmail(
    client_path: Path, *, importer: Importer, timeout_seconds: int | None = None
) -> GmailAuthorization:
    accounts.native_backend()
    credentials = _run_flow(_load_flow(client_path, importer), timeout_seconds)
    account = _fetch_account(credentials, importer)
    return GmailAuthorization(account, credentials.to_json())


def connect_gmail(client_path: Path, *, importer: Importer) -> str:
    authorization = authorize_gmail(client_path, importer=importer)
    accounts.save_secret("gmail", authorization.token)
    return authorization.account


def _require_store() -> None:
    try:
        accounts.native_backend()
    except Exception:
        raise SetupError("store") from None


def _classify_flow_error(error: Exception) -> str:
    oauth_errors = import_module("oauthlib.oauth2.rfc6749.errors")
    if isinstance(error, oauth_errors.AccessDeniedError):
        return "denied"
    if isinstance(error, oauth_errors.InvalidClientError):
        return "client_file"
    if isinstance(error, import_module("google_auth_oauthlib.flow").WSGITimeoutError):
        return "timeout"
    return _classify_transport_error(error)


def _classify_transport_error(error: Exception) -> str:
    if isinstance(error, OSError | import_module("httplib2").HttpLib2Error):
        return "network"
    return "unexpected"


def _classify_profile_error(error: Exception) -> str:
    status = getattr(getattr(error, "resp", None), "status", None)
    if isinstance(error, import_module("googleapiclient.errors").HttpError) and str(status) in {"401", "403"}:
        return "rejected"
    result = doctor.classify_gmail_error(error)
    if result["status"] == "rejected":
        return "rejected"
    if result["reason"] == "connection":
        return "network"
    return _classify_transport_error(error)


def authorize_gmail_guided(
    client_path: Path,
    *,
    importer: Importer = import_module,
    timeout_seconds: int | None = GMAIL_AUTH_TIMEOUT_SECONDS,
) -> GmailAuthorization:
    _require_store()
    try:
        flow = _load_flow(client_path, importer)
    except Exception:
        raise SetupError("client_file") from None
    try:
        credentials = _run_flow(flow, timeout_seconds)
    except Exception as error:
        raise SetupError(_classify_flow_error(error)) from None
    try:
        account = _fetch_account(credentials, importer)
        token = credentials.to_json()
    except Exception as error:
        raise SetupError(_classify_profile_error(error)) from None
    return GmailAuthorization(account, token)


def save_gmail(authorization: GmailAuthorization) -> None:
    try:
        accounts.save_secret("gmail", authorization.token)
    except Exception:
        raise SetupError("store") from None


def lexware_adapter(key: str) -> LexwareAdapter:
    client = import_module("httpx").Client(
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        follow_redirects=False,
    )
    return LexwareAdapter(client)


def _normalize_key(key: str) -> str:
    normalized = key.strip()
    if not KEY_PATTERN.fullmatch(normalized):
        raise SetupError("invalid_key")
    return normalized


def validate_lexware_key(key: str, *, client_factory: Callable[[str], Any] = lexware_adapter) -> None:
    normalized = _normalize_key(key)
    _require_store()
    adapter = None
    try:
        adapter = client_factory(normalized)
        adapter.probe_profile()
    except Exception as error:
        result = doctor.classify_lexware_error(error)
        if result["status"] == "rejected":
            raise SetupError("rejected") from None
        raise SetupError("network" if result["reason"] == "connection" else "unexpected") from None
    finally:
        close = getattr(getattr(adapter, "client", None), "close", None)
        if callable(close):
            close()


def save_lexware_key(key: str) -> None:
    normalized = _normalize_key(key)
    try:
        accounts.save_secret("lexware", normalized)
    except Exception:
        raise SetupError("store") from None
