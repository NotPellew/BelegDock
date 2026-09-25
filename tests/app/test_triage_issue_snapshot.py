import json
import subprocess
import sys
from pathlib import Path


def test_triage_snapshot_keeps_complete_issue_bodies(tmp_path: Path) -> None:
    body = "Opening paragraph.\n" + ("Long acceptance criterion with spaces. " * 300) + "END-OF-ISSUE"
    issues = [
        {
            "number": 26,
            "title": "Classify scans",
            "body": body,
            "url": "https://github.com/NotPellew/BelegDock/issues/26",
            "updatedAt": "2026-09-25T08:00:00Z",
            "labels": [{"name": "feature"}],
        },
        {
            "number": 27,
            "title": "Add local model",
            "body": "Depends on #26.",
            "url": "https://github.com/NotPellew/BelegDock/issues/27",
            "updatedAt": "2026-09-25T08:01:00Z",
            "labels": [],
        },
    ]
    source = tmp_path / "issues.json"
    source.write_text(json.dumps(issues), encoding="utf-8")
    output = tmp_path / "issues"
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_triage_issues.py"

    result = subprocess.run(
        [sys.executable, str(script), str(source), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in output.glob("*.md")) == [
        "INDEX.md",
        "issue-26.md",
        "issue-27.md",
    ]
    index = (output / "INDEX.md").read_text(encoding="utf-8")
    assert "issue-26.md" in index and "issue-27.md" in index
    rendered = (output / "issue-26.md").read_text(encoding="utf-8")
    assert "## Body\n" in rendered
    rendered_body = rendered.split("## Body\n", 1)[1]
    assert rendered_body.replace("\n", "") == body.replace("\n", "")
    assert max(map(len, rendered_body.splitlines())) <= 160
