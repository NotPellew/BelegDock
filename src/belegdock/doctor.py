import json
from collections.abc import Callable
from importlib import import_module
from typing import Any

from . import accounts
from .workflow import RemoteAuthError

SERVICES = ("gmail", "lexware")
GMAIL_AUTH_REASONS = {"autherror", "insufficientpermissions"}
LOGIN_COMMANDS = {
    "gmail": "belegdock login-gmail --client CLIENT_JSON",
    "lexware": "belegdock login-lexware",
}
STORE_ERRORS = {
    "store_unavailable": "Kein nativer Speicher des Betriebssystems verfügbar; es gibt keinen Klartext-Fallback",
}
SKIP_REASONS = {
    "store_unavailable": "Anmeldedatenspeicher nicht verfügbar",
    "missing": "keine Anmeldedaten gespeichert",
    "read_failed": "Anmeldedatenspeicher nicht lesbar",
}
ERROR_LABELS = {
    "connection": "Verbindungsfehler",
    "service_error": "Dienstfehler",
    "rate_limited": "Anfragelimit erreicht",
    "unexpected": "Unerwarteter Fehler",
}


def detect(
    *,
    online: bool,
    gmail_account: Callable[[], str],
    lexware_remote: Callable[[], Any],
) -> dict[str, Any]:
    store_available, store_error = accounts.check_credential_store()
    states = {
        name: accounts.secret_state(name) if store_available else "store_unavailable" for name in SERVICES
    }
    credentials = {name: {"present": _present(state), "state": state} for name, state in states.items()}
    result: dict[str, Any] = {
        "ok": all(state == "present" for state in states.values()),
        "store": {"available": store_available, "error": store_error},
        "credentials": credentials,
        "online": None,
    }
    if not online:
        return result

    probes = {"gmail": lambda: _probe_gmail(gmail_account), "lexware": lambda: _probe_lexware(lexware_remote)}
    result["online"] = {
        name: probes[name]() if states[name] == "present" else {"status": "skipped", "reason": states[name]}
        for name in SERVICES
    }
    result["ok"] = result["ok"] and all(item["status"] == "ok" for item in result["online"].values())
    return result


def _present(state: str) -> bool | None:
    if state == "read_failed":
        return None
    return state == "present"


def _probe_gmail(gmail_account: Callable[[], str]) -> dict[str, Any]:
    try:
        return {"status": "ok", "account": gmail_account()}
    except Exception as error:
        return classify_gmail_error(error)


def _probe_lexware(lexware_remote: Callable[[], Any]) -> dict[str, Any]:
    remote = None
    try:
        remote = lexware_remote()
        profile = remote.probe_profile()
        return {"status": "ok", "organizationId": profile.get("organizationId")}
    except Exception as error:
        return classify_lexware_error(error)
    finally:
        close = getattr(getattr(remote, "client", None), "close", None)
        if callable(close):
            close()


def _failure(status: str, reason: str, error: BaseException, http_status: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "reason": reason, "errorType": type(error).__name__}
    if http_status is not None:
        result["httpStatus"] = http_status
    return result


def _http_reasons(error: Any) -> set[str]:
    try:
        payload = json.loads(error.content)
        return {
            str(item.get("reason", "")).lower()
            for item in payload["error"]["errors"]
            if isinstance(item, dict)
        }
    except Exception:
        return set()


def classify_gmail_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, RemoteAuthError):
        return _failure("rejected", "auth_rejected", error, error.status_code)
    google_exceptions = import_module("google.auth.exceptions")
    if isinstance(error, google_exceptions.RefreshError):
        if getattr(error, "retryable", False):
            return _failure("error", "connection", error)
        return _failure("rejected", "refresh_rejected", error)
    if isinstance(error, google_exceptions.TransportError | OSError):
        return _failure("error", "connection", error)
    if isinstance(error, import_module("googleapiclient.errors").HttpError):
        status = getattr(error.resp, "status", None)
        status = int(status) if status is not None else None
        if status == 401:
            return _failure("rejected", "http_401", error, status)
        if status == 403:
            reasons = _http_reasons(error)
            if reasons & GMAIL_AUTH_REASONS and not any("limit" in item or "quota" in item for item in reasons):
                return _failure("rejected", "http_403_auth", error, status)
            return _failure("error", "rate_limited" if reasons else "service_error", error, status)
        return _failure("error", "service_error", error, status)
    return _failure("error", "unexpected", error)


def classify_lexware_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, RemoteAuthError):
        return _failure("rejected", "auth_rejected", error, error.status_code)
    if isinstance(error, import_module("httpx").TransportError | OSError):
        return _failure("error", "connection", error)
    return _failure("error", "unexpected", error)


def format_human(result: dict[str, Any]) -> str:
    lines = ["BelegDock-Diagnose:"]
    store = result.get("store", {})
    if store.get("available"):
        lines.append("  Anmeldedatenspeicher: Verfügbar")
    else:
        lines.append(f"  Anmeldedatenspeicher: Nicht verfügbar ({STORE_ERRORS['store_unavailable']})")

    names = {"gmail": "Gmail", "lexware": "Lexware"}
    credential_texts = {
        "present": "Gespeichert",
        "missing": "Nicht gespeichert",
        "read_failed": "Nicht lesbar (Anmeldedatenspeicher gesperrt oder Zugriff verweigert)",
        "store_unavailable": "Nicht verfügbar",
    }
    for name, label in names.items():
        state = result.get("credentials", {}).get(name, {}).get("state", "missing")
        lines.append(f"  {label}-Anmeldedaten: {credential_texts[state]}")

    online = result.get("online")
    if online is not None:
        for name, label in names.items():
            lines.append(f"  {label}-Verbindung: {_online_text(name, online.get(name, {}))}")
    return "\n".join(lines)


def _online_text(name: str, item: dict[str, Any]) -> str:
    status = item.get("status")
    if status == "ok":
        if name == "gmail":
            return f"Erfolgreich (verbunden als {item.get('account', '')})"
        return f"Erfolgreich (Organisation: {item.get('organizationId', '')})"
    if status == "rejected":
        return f"Abgelehnt; Anmeldung erneuern mit '{LOGIN_COMMANDS[name]}'"
    if status == "skipped":
        return f"Übersprungen ({SKIP_REASONS.get(str(item.get('reason')), 'keine Anmeldedaten')})"
    label = ERROR_LABELS.get(str(item.get("reason")), ERROR_LABELS["unexpected"])
    if item.get("httpStatus") is not None:
        label = f"{label}, HTTP {item['httpStatus']}"
    return f"Fehlgeschlagen ({label}; {item.get('errorType', 'Fehler')})"
