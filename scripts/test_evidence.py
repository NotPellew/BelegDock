import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import platform
import xml.etree.ElementTree as ET

ROOT_FILES = ("pyproject.toml", "uv.lock", "AGENTS.md")
ROOT_DIRS = ("tests", "scripts", ".github", "pilot_fixtures")


class EvidenceError(Exception):
    pass


def input_hashes(repo):
    paths = []
    for name in ROOT_FILES:
        path = repo / name
        if path.exists():
            paths.append(path)
    for name in ROOT_DIRS:
        directory = repo / name
        if directory.exists():
            if directory.is_symlink():
                raise EvidenceError(f"protected input is a symlink: {name}")
            paths.extend(path for path in directory.rglob("*")
                         if path.is_file() and "__pycache__" not in path.parts
                         and path.suffix not in (".pyc", ".pyo"))
    result = {}
    for path in sorted(paths):
        result[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def outside(path, repo):
    resolved = path.resolve()
    if resolved == repo or repo in resolved.parents:
        raise EvidenceError(f"output must be outside repo: {path}")
    return resolved


def collect(repo, python):
    result = subprocess.run([python, "-m", "pytest", "--collect-only", "-q"], cwd=repo,
                            text=True, capture_output=True)
    if result.returncode:
        raise EvidenceError(f"pytest collection failed: {result.stderr.strip()}")
    ids = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if "::" in value and not value.startswith(("<", "=")):
            ids.append(value)
    if not ids:
        raise EvidenceError("pytest collection produced no test IDs")
    return sorted(dict.fromkeys(ids))


def run_metadata(repo, command, started, finished, stdout, stderr, inputs):
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              text=True, capture_output=True).stdout.strip() or None
    sources = {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted((repo / "src").rglob("*"))
               if path.is_file() and "__pycache__" not in path.parts
               and path.suffix not in (".pyc", ".pyo")}
    source_hash = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    return {"command": command, "stdout": stdout, "stderr": stderr,
            "revision": revision, "source_hash": source_hash, "source_files": sources,
            "protected_inputs": inputs,
            "platform": platform.platform(), "python": sys.version,
            "started_at": started, "finished_at": finished}


def snapshot(args):
    repo = args.repo.resolve(strict=True)
    output = outside(args.output, repo)
    content = {"version": 1, "inputs": input_hashes(repo),
               "test_ids": collect(repo, args.python)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n")
    return 0


def testcase_id(case, expected):
    name = case.attrib.get("name", "")
    classname = case.attrib.get("classname", "")
    candidates = []
    for item in expected:
        parts = item.split("::")
        if parts[-1] != name:
            continue
        module = parts[0].replace("/", ".")
        if module.endswith(".py"):
            module = module[:-3]
        qualified = module + ("." + ".".join(parts[1:-1]) if len(parts) > 2 else "")
        if classname == qualified or classname.endswith("." + qualified):
            candidates.append(item)
    matches = candidates
    return matches[0] if len(matches) == 1 else None


def run_phase(args):
    repo = args.repo.resolve(strict=True)
    output = outside(args.output, repo)
    saved = json.loads(args.snapshot.resolve(strict=True).read_text())
    current_inputs = input_hashes(repo)
    if current_inputs != saved.get("inputs"):
        raise EvidenceError("protected input drift detected")
    expected = sorted(set(args.expected_failure))
    saved_ids = saved.get("test_ids", [])
    current_ids = collect(repo, args.python)
    if current_ids != sorted(saved_ids):
        raise EvidenceError("collected test IDs differ from snapshot")
    if args.phase == "red" and not expected:
        raise EvidenceError("RED requires at least one expected failure")
    if not set(expected).issubset(saved_ids):
        raise EvidenceError("expected test ID was not discovered")
    output.mkdir(parents=True, exist_ok=False)
    junit = output / "junit.xml"
    command = [args.python, "-m", "pytest", "-q", f"--junitxml={junit}"]
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command,
                            cwd=repo, text=True, capture_output=True)
    finished = datetime.now(timezone.utc).isoformat()
    if not junit.is_file():
        raise EvidenceError("pytest did not produce JUnit XML")
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError as error:
        raise EvidenceError(f"invalid JUnit XML: {error}") from error
    cases = root.findall(".//testcase")
    errors = [case for case in cases if case.find("error") is not None]
    skipped = [case for case in cases if case.find("skipped") is not None]
    failures = [case for case in cases if case.find("failure") is not None]
    if errors:
        raise EvidenceError("pytest reported collection or execution errors")
    if skipped:
        raise EvidenceError("pytest reported skipped tests")
    executed_ids = [testcase_id(case, current_ids) for case in cases]
    if any(item is None for item in executed_ids) or len(set(executed_ids)) != len(executed_ids):
        raise EvidenceError("JUnit tests could not be mapped uniquely to collected IDs")
    if sorted(executed_ids) != current_ids:
        raise EvidenceError("JUnit tests differ from collected test IDs")
    failed_ids = [testcase_id(case, current_ids) for case in failures]
    if any(item is None for item in failed_ids):
        raise EvidenceError("JUnit failure could not be mapped to a collected test ID")
    failed = sorted(failed_ids)
    if args.phase == "red":
        if failed != expected or result.returncode != 1:
            raise EvidenceError(f"RED failures were {failed}, expected {expected}")
        if any("assert" not in (case.find("failure").attrib.get("type", "") +
                                (case.find("failure").text or "")).lower()
               for case in failures):
            raise EvidenceError("RED failure was not assertion-related")
    elif failed or result.returncode:
        raise EvidenceError("GREEN pytest run did not pass cleanly")
    if input_hashes(repo) != current_inputs:
        raise EvidenceError("protected input drift detected during run")
    report = {"phase": args.phase, "status": "passed", "expected_failures": expected,
              "failed_tests": failed, "returncode": result.returncode,
              "metadata": run_metadata(repo, command, started, finished,
                                        result.stdout, result.stderr, current_inputs)}
    (output / "evidence.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


def make_parser():
    result = argparse.ArgumentParser(description="Record pytest evidence outside a checkout")
    sub = result.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--repo", required=True, type=Path)
    snap.add_argument("--output", required=True, type=Path)
    snap.add_argument("--python", default=sys.executable)
    run = sub.add_parser("run")
    run.add_argument("--repo", required=True, type=Path)
    run.add_argument("--snapshot", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--phase", required=True, choices=("red", "green"))
    run.add_argument("--expected-failure", action="append", default=[])
    run.add_argument("--python", default=sys.executable)
    return result


def main():
    try:
        args = make_parser().parse_args()
        return snapshot(args) if args.command == "snapshot" else run_phase(args)
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(f"evidence recorder failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
