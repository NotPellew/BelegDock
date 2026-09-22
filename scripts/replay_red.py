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
    ("bootstrap", "90b84f13879c13be017ed6fac4b577861d63dfdd", "test_cli_bootstrap.py", 2, {"AssertionError"}),
    ("accounts", "439ced7", "test_accounts.py", 5, {"AssertionError"}),
    ("integrations", "0c57455", "test_integrations.py", 7, {"AssertionError"}),
    ("workflow", "0c57455", "test_workflow.py", 12, {"NotImplementedError"}),
    ("commands", "578b10e2ba971ca5e9d47022751b653aace2f264", "test_cli_workflow.py", 5, {"AssertionError"}),
    ("login", "afc60ac", "test_login.py", 3, {"AssertionError", "NotImplementedError"}),
    ("integration_validation", "052c772", "test_integration_validation.py", 4, {"AssertionError"}),
    ("workflow_recovery", "2cb17cd", "test_workflow_recovery.py", 4, {"NotImplementedError"}),
    ("help", "46fd0cf51ebe8771c24d9866d258629ef9d709a1", "test_cli_help.py", 2, {"AssertionError"}),
    ("recovery_commands", "d80c9110f79836290e69917e1c959d259f431121", "test_cli_recovery_commands.py", 3, {"AssertionError"}),
    ("recovery_review_regressions", "0daacce8567a335e669862754c0d15c35bababd1", "test_cli_recovery_review_regressions.py", 2, {"AssertionError"}),
    ("recovery_state_guidance", "f80559e", "test_cli_recovery_state_guidance.py", 2, {"AssertionError"}),
    ("recovery_state_unavailable", "38b890149ba594590f229a2effcf421618da1c74", "test_cli_recovery_state_unavailable.py", 2, {"AssertionError"}),
    ("recovery_unavailable_commands", "df0dd18a3aafc56b37678103f3b8d5fcea3977a8", "test_cli_recovery_unavailable_commands.py", 2, {"AssertionError"}),
    ("recovery_integrity_guidance", "79ff45a55648e78c508e1303523fc809a1108be3", "test_cli_recovery_integrity_guidance.py", 2, {"AssertionError"}),
    ("recover_upload_integrity", "e67375a7bf2980178825c7c774aeff41806b568d", "test_cli_recover_upload_integrity.py", 1, {"AssertionError"}),
    ("recovery_status_lookup", "d809154", "test_cli_recovery_status_lookup.py", 1, {"AssertionError"}),
    ("rejected_upload_guidance", "59efa18d82dc4823ad7d736f6ee7c26fbdbd7dbd", "test_cli_rejected_upload_guidance.py", 1, {"AssertionError"}),
    ("uploaded_upload_guidance", "13cbb07959104aa6afc06d0375bb5fa2bf07517e", "test_cli_uploaded_upload_guidance.py", 1, {"AssertionError"}),
    ("recovery_lock_guidance", "b685ab9ba35238c85e4de658fa3c0ab3004e40b6", "test_cli_recovery_lock_guidance.py", 3, {"AssertionError"}),
    ("desktop_already_present", "c13c26ef4e71d8b1b65ed08efcc9016a518b280a", "test_desktop_already_present.py", 2, {"AssertionError"}),
    ("desktop_detail_reset", "06d0ed8aaf42a01f576365b368f6fd062f011d66", "test_desktop_detail_reset.py", 1, {"AssertionError"}),
    ("desktop_integrity", "98dc704b5567c14ac509a4d1fe5e794d7d656c98", "test_desktop_integrity.py", 1, {"AssertionError"}),
    ("desktop_layout_states", "e72509c6ae827c394acb4d39aeeedd2bcdc0bce5", "test_desktop_layout_states.py", 2, {"AssertionError"}),
    ("desktop_states", "316a37320075b6135d59e782d98e06c75c11c7f7", "test_desktop_states.py", 2, {"AssertionError"}),
    ("desktop_ui_polish", "fe283fc6f5ad8b74592e4f6f965ebe7a71594b28", "test_desktop_ui_polish.py", 3, {"AssertionError"}),
    ("restore_integrity", "7bf3d5ac2a4ec52d7acdd09349bca4f81f546941", "test_restore_integrity.py", 2, {"AssertionError"}),
    ("restore_integrity_bounds", "b3fb5e90d3df182a8bc1eb418100ab4b6a058e68", "test_restore_integrity_bounds.py", 1, {"AssertionError"}),
    ("upload_reconciliation", "7541b551da120594ea79f1727b52fbc95879864d", "test_upload_reconciliation.py", 1, {"AssertionError"}),
    ("parse_errors", "4f0d740", "test_german_cli_parse_errors.py", 3, {"AssertionError"}),
    ("parse_error_edges", "28da414", "test_german_cli_parse_error_edges.py", 2, {"AssertionError"}),
    ("final_guidance", "47b5d5d", "test_german_cli_final_guidance.py", 3, {"AssertionError"}),
    ("windows_packaging", "beaf52ac145821cd88de123d05243715181d9c30", "test_windows_packaging.py", 10, {"AssertionError"}),
    ("windows_packaging_bounds", "beaf52ac145821cd88de123d05243715181d9c30", "test_windows_packaging_bounds.py", 4, {"AssertionError"}),
    ("windows_packaging_internal", "c6bdc14395fc532f9baae0e823d868632668b0b7", "test_windows_packaging_internal.py", 1, {"AssertionError"}),
    ("desktop_launch", "29d8232bdeb2c331cdb77d4211c9ff96bf00301f", "test_desktop_launch.py", 3, {"AssertionError"}),
)


FOCUSED = {
    "desktop_already_present": {
        "test_already_present_document_has_a_distinct_state",
        "test_already_present_result_says_no_upload_was_sent",
    },
    "desktop_detail_reset": {"test_reload_clears_detail_values_for_removed_document"},
    "desktop_integrity": {"test_damaged_document_is_not_ready_or_uploadable_and_shows_restore_guidance"},
    "desktop_layout_states": {
        "test_action_states_keep_remote_outcomes_no_send",
        "test_clearing_selection_resets_action_region_and_disables_send",
    },
    "desktop_states": {
        "test_rejection_shows_corrective_guidance_not_uncertain_guidance",
        "test_uncertain_document_shows_cli_only_recovery_guidance",
    },
    "desktop_ui_polish": {
        "test_file_sizes_are_human_readable",
        "test_status_codes_have_readable_labels",
        "test_prepare_disclaimer_is_exposed_without_a_workflow_stepper",
    },
    "restore_integrity": {
        "test_cli_missing_database_reports_restore_guidance_without_empty_success",
        "test_uploaded_missing_or_corrupt_blob_is_flagged_without_rewriting_status",
    },
    "restore_integrity_bounds": {"test_unusable_database_cli_gives_restore_guidance_without_creating_blobs"},
    "upload_reconciliation": {"test_cli_reports_a_sanitized_documented_rejection"},
}


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


def validate_focused_report(path, expected_names, returncode, allowed):
    if returncode != 1 or not expected_names:
        raise ValueError("RED requires pytest exit 1 and expected tests")
    cases = ET.parse(path).getroot().findall(".//testcase")
    focused = set(expected_names)
    seen = set()
    for case in cases:
        name = case.attrib.get("classname", "") + "." + case.attrib.get("name", "")
        base_name = name.split("[", 1)[0]
        failure = case.find("failure")
        if base_name in focused:
            seen.add(base_name)
            if failure is None or case.find("skipped") is not None or case.find("error") is not None:
                raise ValueError("Every focused historical test must fail for its intended missing behavior")
            message = failure.attrib.get("message", "")
            if not any(message.startswith(marker) for marker in allowed):
                raise ValueError("Unexpected failure type; dependency/import errors are not RED")
        elif failure is not None or case.find("skipped") is not None or case.find("error") is not None:
            raise ValueError("Unfocused tests must pass during focused RED replay")
    if seen != focused:
        raise ValueError("Executed focused tests differ from the frozen test identities")
    return sorted(seen)


def identities(test_path, data):
    module = test_path[:-3].replace("/", ".")
    names, nodes = set(), set()
    for item in ast.parse(data).body:
        if isinstance(item, ast.ClassDef):
            for method in item.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"):
                    names.add(f"{module}.{item.name}.{method.name}")
                    nodes.add(f"{test_path}::{item.name}::{method.name}")
        elif isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
            names.add(f"{module}.{item.name}")
            nodes.add(f"{test_path}::{item.name}")
    return names, nodes


def focused_identities(group, names, nodes):
    selected = FOCUSED.get(group)
    if selected is None:
        return names, nodes
    focused_names = {name for name in names if name.rsplit(".", 1)[-1] in selected}
    focused_nodes = {node for node in nodes if node.rsplit("::", 1)[-1] in selected}
    if {name.rsplit(".", 1)[-1] for name in focused_names} != selected:
        raise ValueError(f"{group}: focused tests differ from the frozen definitions")
    return focused_names, focused_nodes


def base_node(node):
    return node.split("[", 1)[0]


def verify(repo):
    for name, checkpoint, filename, count, allowed in GROUPS:
        revision = subprocess.check_output(
            ["git", "rev-parse", checkpoint], cwd=repo, text=True).strip()
        test_path = "tests/app/" + filename
        archived = subprocess.check_output(["git", "archive", revision, test_path], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
            member = archive.extractfile(test_path)
            if member is None:
                raise ValueError(f"{name}: test differs from its approved checkpoint")
            frozen = member.read()
        if frozen != (repo / test_path).read_bytes():
            raise ValueError(f"{name}: test differs from its approved checkpoint")
        all_names, all_nodes = identities(test_path, frozen)
        expected_names, _ = focused_identities(name, all_names, all_nodes)
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
            all_names, all_nodes = identities(test_path, test_bytes)
            expected_names, _ = focused_identities(name, all_names, all_nodes)
            expected_nodes = {base_node(node) for node in all_nodes}
            if len(expected_names) != count:
                raise ValueError(f"{name}: unexpected test count")
            env = dict(os.environ, PYTHONPATH=str(root / "src"),
                       PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTHONHOME", None)
            collected = subprocess.run([sys.executable, "-m", "pytest", test_path, "--collect-only", "-q"],
                                       cwd=root, env=env, text=True, capture_output=True, timeout=60)
            nodes = {base_node(line.strip()) for line in collected.stdout.splitlines() if "::" in line}
            if collected.returncode or nodes != expected_nodes:
                raise ValueError(f"{name}: collection differs from the frozen definitions")
            junit = artifact / "junit.xml"
            command = [sys.executable, "-m", "pytest", test_path, "-q", f"--junitxml={junit}"]
            started = datetime.now(timezone.utc).isoformat()
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=60)
            (artifact / "stdout.txt").write_text(result.stdout, encoding="utf-8")
            (artifact / "stderr.txt").write_text(result.stderr, encoding="utf-8")
            if name in FOCUSED:
                failed = validate_focused_report(junit, expected_names, result.returncode, allowed)
            else:
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
        description=f"Replay the {len(GROUPS)} frozen feature RED checkpoints, or --verify them without executing pytest")
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
