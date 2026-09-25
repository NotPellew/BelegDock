import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


STATUSES = {
    "READY": ("triage:ready", "0e8a16", "Scout finds this issue ready for implementation"),
    "NEEDS-DECISION": ("triage:needs-decision", "fbca04", "A human decision is needed"),
    "BLOCKED": ("triage:blocked", "b60205", "A prerequisite is still open"),
    "STALE": ("triage:stale", "d4c5f9", "Current code may have changed this issue's premise"),
    "NEEDS-REFINEMENT": ("triage:needs-refinement", "f9d0c4", "Acceptance criteria need refinement"),
}
MANAGED_LABELS = {name for name, _, _ in STATUSES.values()}
MARKER = "<!-- BelegDock triage-scout v1: "
ISSUE_HEADING = re.compile(r"^## #([1-9]\d*) — ([^\n]+)$", re.MULTILINE)
REVISION = re.compile(r"^\*\*Checkout revision:\*\* `([0-9a-f]{40})`\s*$", re.MULTILINE)
SNAPSHOT = re.compile(r"^\*\*Issue snapshot:\*\* `\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ`\s*$", re.MULTILINE)
CLASSIFICATION = re.compile(r"^\*\*Classification: ([A-Z-]+)\.\*\*$", re.MULTILINE)
ACTION = re.compile(r"^\*\*Next human action:\*\* (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Entry:
    number: int
    title: str
    status: str
    action: str


def parse_report(report: str, manifest: list[dict], revision: str) -> list[Entry]:
    if len(report) > 1_000_000 or not SNAPSHOT.search(report):
        raise ValueError("Missing snapshot timestamp or oversized report")
    if not isinstance(manifest, list):
        raise ValueError("Invalid issue manifest")
    revisions = REVISION.findall(report)
    if revisions != [revision]:
        raise ValueError("Report revision does not match the checkout")
    expected = {}
    for issue in manifest:
        if not isinstance(issue, dict):
            raise ValueError("Invalid issue manifest")
        number, title = issue.get("number"), issue.get("title")
        if not isinstance(number, int) or number < 1 or not isinstance(title, str) or not title:
            raise ValueError("Invalid issue manifest")
        if number in expected:
            raise ValueError("Duplicate issue in manifest")
        expected[number] = title
    headings = list(ISSUE_HEADING.finditer(report))
    entries = []
    seen = set()
    for index, heading in enumerate(headings):
        number, title = int(heading.group(1)), heading.group(2)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(report)
        section = report[heading.end():end].split("\n## ", 1)[0]
        if number in seen or expected.get(number) != title:
            raise ValueError(f"Unexpected or duplicated issue #{number}")
        seen.add(number)
        statuses = CLASSIFICATION.findall(section)
        actions = ACTION.findall(section)
        if len(statuses) != 1 or statuses[0] not in STATUSES or len(actions) != 1:
            raise ValueError(f"Missing classification or human action for #{number}")
        action = actions[0].strip()
        if not action or len(action) > 800 or re.search(r"https?://|www\.|!\[|(?:sk-|ghp_|github_pat_)\S{8,}", action, re.IGNORECASE):
            raise ValueError(f"Invalid human action for #{number}")
        entries.append(Entry(number, title, statuses[0], action))
    if seen != set(expected):
        raise ValueError("Scout report does not cover every open issue")
    return entries


def safe_action(action: str) -> str:
    return "".join(character for character in action if character.isprintable()).replace("@", "＠").replace("<", "&lt;").replace(">", "&gt;")


def comment_body(entry: Entry, run_url: str) -> tuple[str, str]:
    action = safe_action(entry.action)
    fingerprint = hashlib.sha256(f"{entry.status}\n{action}".encode()).hexdigest()
    heading = "Decision or refinement needed" if entry.status in {"NEEDS-DECISION", "NEEDS-REFINEMENT"} else "Next human action"
    recent_runs = run_url.split("/actions/runs/", 1)[0] + "/actions/workflows/triage-scout.yml"
    body = (
        f"{MARKER}{fingerprint} -->\n"
        f"**Triage scout: {entry.status}** (tentative)\n\n"
        f"**{heading}:** {action}\n\n"
        f"Reply here with your decision or updated acceptance criteria. "
        f"[Evidence from this run]({run_url}) and [recent reports]({recent_runs}) are available in Actions. "
        f"The scout will update this comment if its recommendation changes."
    )
    return fingerprint, body


def publish(entries: list[Entry], api, repo: str, run_url: str) -> None:
    base = f"/repos/{repo}"
    existing = api("GET", f"{base}/labels?per_page=100")
    if not isinstance(existing, list) or len(existing) >= 100:
        raise ValueError("Could not read the complete repository label list")
    present = {label["name"] for label in existing}
    for name, color, description in STATUSES.values():
        if name not in present:
            api("POST", f"{base}/labels", {"name": name, "color": color, "description": description})
    for entry in entries:
        issue_base = f"{base}/issues/{entry.number}"
        current = api("GET", issue_base)
        if current["state"] != "open" or current["title"] != entry.title:
            print(f"Skipping issue #{entry.number}: state or title changed since snapshot")
            continue
        labels = {label["name"] for label in api("GET", f"{issue_base}/labels?per_page=100")}
        desired = STATUSES[entry.status][0]
        if desired not in labels:
            api("POST", f"{issue_base}/labels", {"labels": [desired]})
        for previous in sorted((labels & MANAGED_LABELS) - {desired}):
            api("DELETE", f"{issue_base}/labels/{previous}")
        comments = []
        for page in range(1, 21):
            batch = api("GET", f"{issue_base}/comments?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ValueError(f"Could not list comments for #{entry.number}")
            comments.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise ValueError(f"Too many comments on #{entry.number}")
        owned = [comment for comment in comments
                 if comment.get("user", {}).get("login") == "github-actions[bot]"
                 and comment.get("body", "").startswith(MARKER)]
        if len(owned) > 1:
            raise ValueError(f"Multiple scout comments on #{entry.number}")
        fingerprint, body = comment_body(entry, run_url)
        if not owned:
            api("POST", f"{issue_base}/comments", {"body": body})
        elif not owned[0]["body"].startswith(f"{MARKER}{fingerprint} -->"):
            api("PATCH", f"{base}/issues/comments/{owned[0]['id']}", {"body": body})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class GitHubApi:
    def __init__(self, token: str):
        self.token = token
        self.opener = build_opener(NoRedirect)

    def __call__(self, method: str, path: str, data=None):
        payload = None if data is None else json.dumps(data).encode()
        request = Request(
            "https://api.github.com" + path,
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "BelegDock-triage-scout",
            },
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ValueError("Oversized GitHub API response")
                return json.loads(raw) if raw else None
        except HTTPError as error:
            raise ValueError(f"GitHub API {method} {path} returned HTTP {error.code}") from None
        except URLError as error:
            raise ValueError(f"GitHub API {method} {path} could not be reached") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Invalid repository name")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("Invalid revision")
    if not re.fullmatch(rf"https://github\.com/{re.escape(args.repo)}/actions/runs/\d+", args.run_url):
        parser.error("Invalid workflow run URL")
    token = os.environ.get("GH_TOKEN")
    if not token:
        parser.error("GH_TOKEN is required")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        entries = parse_report(args.report.read_text(encoding="utf-8"), manifest, args.revision)
        publish(entries, GitHubApi(token), args.repo, args.run_url)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Triage publication stopped: {error}", file=sys.stderr)
        return 1
    print(f"Published triage for {len(entries)} snapshot issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
