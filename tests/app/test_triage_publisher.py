from collections import defaultdict
import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "publish_triage.py"
SPEC = importlib.util.spec_from_file_location("belegdock_publish_triage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
parse_report = MODULE.parse_report
publish = MODULE.publish


REVISION = "a" * 40
REPO = "NotPellew/BelegDock"
RUN_URL = "https://github.com/NotPellew/BelegDock/actions/runs/123"
MANIFEST = [
    {"number": 26, "title": "Classify scans"},
    {"number": 27, "title": "Add local model"},
]


def report(action: str = "Decide field names and rule precedence.") -> str:
    return f"""**Checkout revision:** `{REVISION}`
**Issue snapshot:** `2026-09-25T08:58:43Z`

# BelegDock issue triage report

## #26 — Classify scans

**Classification: NEEDS-DECISION.**

The JSON contract and rule precedence remain open (`src/belegdock/cli.py:224`).

**Dependencies:** None.

**Next human action:** {action}

## #27 — Add local model

**Classification: BLOCKED.**

The issue depends on #26, which is open (`docs/arc42.md:42`).

**Dependencies:** #26 — OPEN.

**Next human action:** Complete #26 before choosing a model.

## Snapshot limits

This is a static review.
"""


class FakeApi:
    def __init__(self):
        self.calls = []
        self.defined_labels = set()
        self.issue_labels = {26: {"enhancement", "triage:ready"}, 27: {"enhancement"}}
        self.issue_state = {26: "open", 27: "open"}
        self.comments = defaultdict(list)
        self.next_comment_id = 1

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, data))
        prefix = f"/repos/{REPO}"
        assert path.startswith(prefix)
        route = path[len(prefix):].split("?", 1)[0]
        if route == "/labels" and method == "GET":
            return [{"name": name} for name in self.defined_labels]
        if route == "/labels" and method == "POST":
            self.defined_labels.add(data["name"])
            return {"name": data["name"]}
        if route.startswith("/issues/comments/") and method == "PATCH":
            comment_id = int(route.rsplit("/", 1)[1])
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == comment_id:
                        comment["body"] = data["body"]
                        return comment
            raise AssertionError("Unknown comment")
        parts = route.strip("/").split("/")
        assert parts[0] == "issues"
        number = int(parts[1])
        if len(parts) == 2 and method == "GET":
            return {"state": self.issue_state[number], "title": MANIFEST[number - 26]["title"]}
        if parts[2] == "labels":
            if method == "GET":
                return [{"name": name} for name in self.issue_labels[number]]
            if method == "POST":
                self.issue_labels[number].update(data["labels"])
                return []
            if method == "DELETE":
                self.issue_labels[number].remove(parts[3])
                return None
        if parts[2] == "comments":
            if method == "GET":
                return self.comments[number]
            if method == "POST":
                comment = {"id": self.next_comment_id, "body": data["body"],
                           "user": {"login": "github-actions[bot]"}}
                self.next_comment_id += 1
                self.comments[number].append(comment)
                return comment
        raise AssertionError(f"Unexpected API call: {method} {path}")


def test_report_requires_exact_issue_coverage_and_revision() -> None:
    parsed = parse_report(report(), MANIFEST, REVISION)
    assert parsed is not None
    assert [entry.number for entry in parsed] == [26, 27]
    for invalid_report in (
        report().replace(REVISION, "b" * 40),
        report().replace("## #27 — Add local model", "## #28 — Add local model"),
        report().replace("**Next human action:** Complete #26 before choosing a model.", ""),
    ):
        try:
            parse_report(invalid_report, MANIFEST, REVISION)
        except ValueError:
            continue
        assert False, "Invalid or incomplete scout report was accepted"


def test_publish_manages_only_triage_labels_and_reuses_comments() -> None:
    api = FakeApi()
    entries = parse_report(report(), MANIFEST, REVISION)
    publish(entries, api, REPO, RUN_URL)

    assert api.issue_labels[26] == {"enhancement", "triage:needs-decision"}
    assert api.issue_labels[27] == {"enhancement", "triage:blocked"}
    assert len(api.comments[26]) == len(api.comments[27]) == 1
    assert "Decide field names and rule precedence." in api.comments[26][0]["body"]
    assert RUN_URL in api.comments[26][0]["body"]

    before = len([call for call in api.calls if call[0] in {"POST", "PATCH", "DELETE"}])
    publish(entries, api, REPO, RUN_URL + "-later")
    after = len([call for call in api.calls if call[0] in {"POST", "PATCH", "DELETE"}])
    assert after == before

    changed = parse_report(report("Decide the exact JSON field names."), MANIFEST, REVISION)
    publish(changed, api, REPO, RUN_URL)
    assert len(api.comments[26]) == 1
    assert "Decide the exact JSON field names." in api.comments[26][0]["body"]
    assert len(api.comments[27]) == 1


def test_publish_skips_issue_closed_since_snapshot() -> None:
    api = FakeApi()
    api.issue_state[27] = "closed"
    publish(parse_report(report(), MANIFEST, REVISION), api, REPO, RUN_URL)
    assert api.issue_labels[26] == {"enhancement", "triage:needs-decision"}
    assert api.issue_labels[27] == {"enhancement"}
    assert not api.comments[27]


def test_comment_cannot_ping_users_from_model_text() -> None:
    api = FakeApi()
    entries = parse_report(report("Ask @maintainer to approve <danger>."), MANIFEST, REVISION)
    publish(entries, api, REPO, RUN_URL)
    assert api.comments[26]
    body = api.comments[26][0]["body"]
    assert "@maintainer" not in body
    assert "<danger>" not in body


def test_publish_leaves_human_comments_untouched() -> None:
    api = FakeApi()
    api.comments[26].append({"id": 100, "body": "Human decision", "user": {"login": "NotPellew"}})
    publish(parse_report(report(), MANIFEST, REVISION), api, REPO, RUN_URL)
    assert api.comments[26][0]["body"] == "Human decision"
    assert len(api.comments[26]) == 2
