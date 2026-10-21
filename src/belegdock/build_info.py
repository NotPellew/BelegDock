import sys
from pathlib import Path

from . import __version__

PRODUCT_NAME = "BelegDock"
LICENSE_NAME = "Apache License 2.0"
LICENSE_URL = "https://github.com/NotPellew/BelegDock/blob/main/LICENSE"
PROJECT_URL = "https://github.com/NotPellew/BelegDock"
PRIVACY_NOTE = ""


def build_info() -> tuple[str, str | None]:
    raise NotImplementedError


def about_text(version: str | None = None, revision: str | None = None) -> str:
    raise NotImplementedError
