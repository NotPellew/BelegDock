import re
import sys
from pathlib import Path

from . import __version__

PRODUCT_NAME = "BelegDock"
LICENSE_NAME = "Apache License 2.0"
LICENSE_URL = "https://github.com/NotPellew/BelegDock/blob/main/LICENSE"
PROJECT_URL = "https://github.com/NotPellew/BelegDock"
PRIVACY_NOTE = (
    "Datenschutz: Deine Daten bleiben lokal im Anwendungsdatenverzeichnis. "
    "BelegDock greift nur lesend auf Gmail zu und sendet Dokumente erst nach "
    "deiner ausdrücklichen Bestätigung an Lexware. Anmeldedaten werden "
    "ausschließlich im Anmeldedatenspeicher des Betriebssystems gespeichert."
)
REVISION_FILENAME = "build_revision.txt"
_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")


def _revision_candidates() -> list[Path]:
    candidates = [Path(__file__).parent / REVISION_FILENAME]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(str(frozen_root)) / "belegdock" / REVISION_FILENAME)
    return candidates


def _embedded_revision() -> str | None:
    for candidate in _revision_candidates():
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _REVISION_PATTERN.fullmatch(value):
            return value
    return None


def build_info() -> tuple[str, str | None]:
    revision = _embedded_revision()
    return (__version__, revision[:7] if revision else None)


def about_text(version: str | None = None, revision: str | None = None) -> str:
    current_version, current_revision = build_info()
    shown_version = version if version is not None else current_version
    shown_revision = revision if revision is not None else current_revision
    lines = [PRODUCT_NAME, f"Version {shown_version}"]
    if shown_revision:
        lines.append(f"Build-Revision: {shown_revision.strip()[:7]}")
    lines.append(f"Lizenz: {LICENSE_NAME} ({LICENSE_URL})")
    lines.append(f"Projekt: {PROJECT_URL}")
    lines.append(PRIVACY_NOTE)
    return "\n".join(lines)
