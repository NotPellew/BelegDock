import argparse
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET


GROUPS = (
    ("bootstrap", "b4ffc7b", "test_cli_bootstrap.py", 2, {"AssertionError"}),
    ("accounts", "439ced7", "test_accounts.py", 5, {"AssertionError"}),
    ("integrations", "0c57455", "test_integrations.py", 7, {"AssertionError"}),
    ("workflow", "0c57455", "test_workflow.py", 12, {"NotImplementedError"}),
    ("commands", "a79ffc4", "test_cli_workflow.py", 5, {"AssertionError"}),
    ("login", "afc60ac", "test_login.py", 3, {"AssertionError", "NotImplementedError"}),
    ("integration_validation", "052c772", "test_integration_validation.py", 4, {"AssertionError"}),
    ("workflow_recovery", "2cb17cd", "test_workflow_recovery.py", 4, {"NotImplementedError"}),
)


def validate_report(path, expected_names, returncode, allowed):
    if returncode != 1 or not expected_names:
        raise ValueError("RED requires pytest exit 1 and expected tests")
    cases = ET.parse(path).getroot().findall(".//testcase")
    names = [case.attrib.get("classname", "") + "." + case.attrib.get("name", "") for case in cases]
    if len(names) != len(set(names)) or set(names) != set(expected_names):
        raise ValueError("Executed tests differ from the frozen test identities")
    for case in cases:
        failure = case.find("failure")
        if failure is None or case.find("skipped") is not None or case.find("error") is not None:
            raise ValueError("Every historical test must fail for its intended missing behavior")
        message = failure.attrib.get("message", "")
        if not any(message.startswith(marker) for marker in allowed):
            raise ValueError("Unexpected failure type; dependency/import errors are not RED")
    return sorted(names)


def identities(test_path, data):
    module = test_path[:-3].replace("/", ".")
    names, nodes = set(), set()
    for item in ast.parse(data).body:
        if isinstance(item, ast.ClassDef):
            for method in item.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                    names.add(f"{module}.{item.name}.{method.name}")
                    nodes.add(f"{test_path}::{item.name}::{method.name}")
    return names, nodes


def verify(repo):
    for name, checkpoint, filename, count, allowed in GROUPS:
        revision = subprocess.check_output(
            ["git", "rev-parse", checkpoint], cwd=repo, text=True).strip()
        test_path = "tests/app/" + filename
        frozen = subprocess.check_output(
            ["git", "cat-file", "blob", f"{revision}:{test_path}"], cwd=repo)
        if frozen != (repo / test_path).read_bytes():
            raise ValueError(f"{name}: test differs from its approved checkpoint")
        expected_names, _ = identities(test_path, frozen)
        if len(expected_names) != count:
            raise ValueError(f"{name}: unexpected test count")
    print(f"Verified {len(GROUPS)} frozen RED groups")


def replay(repo, output):
    output = output.resolve()
    if output == repo or output.is_relative_to(repo):
        raise ValueError("Evidence output must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for name, checkpoint, filename, count, allowed in GROUPS:
        revision = subprocess.check_output(["git", "rev-parse", checkpoint], cwd=repo, text=True).strip()
        test_path = "tests/app/" + filename
        archived = subprocess.check_output(["git", "archive", revision, "src", test_path], cwd=repo)
        artifact = output / name
        artifact.mkdir()
        with tempfile.TemporaryDirectory(prefix="belegdock-red-replay-") as temporary:
            root = Path(temporary)
            with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
                archive.extractall(root, filter="data")
            test_bytes = (root / test_path).read_bytes()
            if test_bytes != (repo / test_path).read_bytes():
                raise ValueError(f"{name}: test differs from its approved checkpoint")
            expected_names, expected_nodes = identities(test_path, test_bytes)
            if len(expected_names) != count:
                raise ValueError(f"{name}: unexpected test count")
            env = dict(os.environ, PYTHONPATH=str(root / "src"),
                       PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTHONHOME", None)
            collected = subprocess.run([sys.executable, "-m", "pytest", test_path, "--collect-only", "-q"],
                                       cwd=root, env=env, text=True, capture_output=True, timeout=60)
            nodes = {line.strip() for line in collected.stdout.splitlines() if "::" in line}
            if collected.returncode or nodes != expected_nodes:
                raise ValueError(f"{name}: collection differs from the frozen definitions")
            junit = artifact / "junit.xml"
            command = [sys.executable, "-m", "pytest", test_path, "-q", f"--junitxml={junit}"]
            started = datetime.now(timezone.utc).isoformat()
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=60)
            (artifact / "stdout.txt").write_text(result.stdout, encoding="utf-8")
            (artifact / "stderr.txt").write_text(result.stderr, encoding="utf-8")
            failed = validate_report(junit, expected_names, result.returncode, allowed)
            sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted((root / "src").rglob("*.py"))}
            record = {"checkpoint": revision, "test_sha256": hashlib.sha256(test_bytes).hexdigest(),
                      "source_files": sources, "failed_tests": failed, "command": command,
                      "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                      "python": sys.version, "platform": platform.platform(), "status": "expected-red"}
            (artifact / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            summaries.append({"group": name, "tests": len(failed), "checkpoint": revision})
    (output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"Verified {sum(item['tests'] for item in summaries)} expected RED tests in {len(summaries)} groups")


def main():
    parser = argparse.ArgumentParser(
        description="Replay the eight frozen feature RED checkpoints, or --verify them without executing pytest")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify and args.output is not None:
        parser.error("--verify and --output are mutually exclusive")
    if not args.verify and args.output is None:
        parser.error("--output is required unless --verify is used")
    try:
        if args.verify:
            verify(args.repo.resolve(strict=True))
        else:
            replay(args.repo.resolve(strict=True), args.output)
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as error:
        print(f"RED replay failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
