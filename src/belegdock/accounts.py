from importlib import import_module
import sys
from typing import Any


def native_backend() -> Any:
    try:
        if sys.platform == "linux":
            backend = import_module("keyring.backends.SecretService").Keyring()
        elif sys.platform == "win32":
            backend = import_module("keyring.backends.Windows").WinVaultKeyring()
        else:
            raise RuntimeError("unsupported")
        if backend.priority <= 0:
            raise RuntimeError("unavailable")
        return backend
    except Exception:
        raise RuntimeError("Native OS credential store unavailable; no plaintext fallback.") from None


def is_usable_secret(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def save_secret(name: str, value: str) -> None:
    if not is_usable_secret(value):
        raise ValueError("Credential must not be empty.")
    try:
        native_backend().set_password("BelegDock", name, value)
    except Exception:
        raise RuntimeError("Could not save credential in the native OS store.") from None


def load_secret(name: str) -> str:
    try:
        value = native_backend().get_password("BelegDock", name)
    except Exception:
        raise RuntimeError("Could not read the native OS credential store.") from None
    if not isinstance(value, str) or not is_usable_secret(value):
        raise RuntimeError("Connect the account first using its login command.")
    return value


def check_credential_store() -> tuple[bool, str | None]:
    try:
        native_backend()
        return True, None
    except Exception:
        return False, "Native OS credential store unavailable; no plaintext fallback."


def secret_state(name: str) -> str:
    try:
        backend = native_backend()
    except Exception:
        return "store_unavailable"
    try:
        value = backend.get_password("BelegDock", name)
    except Exception:
        return "read_failed"
    return "present" if is_usable_secret(value) else "missing"


def has_secret(name: str) -> bool:
    return secret_state(name) == "present"
