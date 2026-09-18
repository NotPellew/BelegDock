import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test_evidence.py"


class EvidenceRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="belegdock-evidence-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        for directory in ("tests/app", "scripts", ".github/workflows"):
            (self.root / directory).mkdir(parents=True)
        (self.root / "tests/app/test_invoice.py").write_text("def test_invoice():\n    assert False\n")
        (self.root / "scripts/helper.py").write_text("VALUE = 1\n")
        (self.root / ".github/workflows/check.yml").write_text("name: check\n")
        (self.root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        (self.root / "AGENTS.md").write_text("rules\n")
        (self.root / "uv.lock").write_text("lock\n")
        self.runner = self.root / "fake-python"
        self.runner.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "if '--collect-only' in args:\n"
            "    print('tests/app/test_invoice.py::test_invoice')\n"
            "    raise SystemExit(0)\n"
            "xml = pathlib.Path(next(a[12:] for a in args if a.startswith('--junitxml=')))\n"
            "xml.parent.mkdir(parents=True, exist_ok=True)\n"
            "xml.write_text('<testsuite tests=\"1\" failures=\"1\" errors=\"0\" skipped=\"0\">'"
            " + '<testcase classname=\"tests.app.test_invoice\" name=\"test_invoice\">'"
            " + '<failure message=\"assertion\">assert False</failure></testcase></testsuite>')\n"
            "raise SystemExit(1)\n"
        )
        self.runner.chmod(0o755)

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            timeout=20,
        )

    def test_snapshot_records_collection_and_input_hashes(self):
        snapshot = Path(self.temporary.name) / "snapshot.json"
        result = self.invoke(
            "snapshot", "--repo", str(self.root), "--output", str(snapshot),
            "--python", str(self.runner),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        content = json.loads(snapshot.read_text())
        self.assertEqual(content["test_ids"], ["tests/app/test_invoice.py::test_invoice"])
        self.assertIn("tests/app/test_invoice.py", content["inputs"])
        self.assertIn("AGENTS.md", content["inputs"])

    def test_red_accepts_only_expected_assertion_failure(self):
        snapshot = Path(self.temporary.name) / "snapshot.json"
        evidence = Path(self.temporary.name) / "evidence"
        made = self.invoke(
            "snapshot", "--repo", str(self.root), "--output", str(snapshot),
            "--python", str(self.runner),
        )
        self.assertEqual(made.returncode, 0, made.stderr)
        result = self.invoke(
            "run", "--repo", str(self.root), "--snapshot", str(snapshot),
            "--output", str(evidence), "--phase", "red",
            "--expected-failure", "tests/app/test_invoice.py::test_invoice",
            "--python", str(self.runner),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((evidence / "evidence.json").read_text())
        self.assertEqual(report["phase"], "red")
        self.assertEqual(report["status"], "passed")
        self.assertTrue((evidence / "junit.xml").exists())

    def test_run_rejects_input_drift_and_unknown_expected_id(self):
        snapshot = Path(self.temporary.name) / "snapshot.json"
        evidence = Path(self.temporary.name) / "evidence"
        made = self.invoke(
            "snapshot", "--repo", str(self.root), "--output", str(snapshot),
            "--python", str(self.runner),
        )
        self.assertEqual(made.returncode, 0, made.stderr)
        (self.root / "scripts/helper.py").write_text("VALUE = 2\n")
        result = self.invoke(
            "run", "--repo", str(self.root), "--snapshot", str(snapshot),
            "--output", str(evidence), "--phase", "red",
            "--expected-failure", "missing::test", "--python", str(self.runner),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drift", (result.stderr + result.stdout).lower())


if __name__ == "__main__":
    unittest.main()
