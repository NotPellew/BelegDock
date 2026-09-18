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


def save_secret(name: str, value: str) -> None:
    if not value.strip():
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
    if not isinstance(value, str) or not value:
        raise RuntimeError("Connect the account first using its login command.")
    return value
