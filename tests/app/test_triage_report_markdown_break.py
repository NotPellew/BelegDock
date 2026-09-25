import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "publish_triage.py"
SPEC = importlib.util.spec_from_file_location("belegdock_publish_triage_markdown_break", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
parse_report = MODULE.parse_report


def test_report_accepts_markdown_hard_break_after_classification() -> None:
    revision = "a" * 40
    title = "Add an application icon, version surface, and About screen"
    report = (
        f"**Checkout revision:** `{revision}`\n"
        "**Issue snapshot:** `2026-09-25T13:45:34Z`\n\n"
        f"## #43 — {title}\n"
        "**Classification: STALE.**  \n"
        "**Next human action:** Decide the remaining About screen scope.\n"
    )

    try:
        entries = parse_report(report, [{"number": 43, "title": title}], revision)
    except ValueError:
        entries = []

    assert [(entry.number, entry.status) for entry in entries] == [(43, "STALE")]
