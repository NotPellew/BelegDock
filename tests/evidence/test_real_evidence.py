from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test_evidence.py"
PYTHON = sys.executable


class RealEvidenceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="belegdock-real-evidence-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        (self.root / "tests/app").mkdir(parents=True)
        (self.root / "src").mkdir()
        for name, content in (("AGENTS.md", "rules\n"), ("pyproject.toml", "[tool.pytest.ini_options]\n"),
                              ("uv.lock", "lock\n")):
            (self.root / name).write_text(content)
        (self.root / "src/__init__.py").write_text("")

    def call(self, *args):
        return subprocess.run([PYTHON, str(SCRIPT), *args], cwd=self.root,
                              text=True, capture_output=True, timeout=30)

    def snapshot(self):
        path = Path(self.temporary.name) / "snapshot.json"
        result = self.call("snapshot", "--repo", str(self.root), "--output", str(path), "--python", PYTHON)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def test_real_red_then_green_and_cache_are_valid(self):
        (self.root / "src/impl.py").write_text("VALUE = False\n")
        (self.root / "tests/app/test_value.py").write_text(
            "from src.impl import VALUE\n\ndef test_value():\n    assert VALUE\n")
        snapshot = self.snapshot()
        evidence = Path(self.temporary.name) / "red"
        red = self.call("run", "--repo", str(self.root), "--snapshot", str(snapshot), "--output", str(evidence),
                        "--phase", "red", "--expected-failure", "tests/app/test_value.py::test_value", "--python", PYTHON)
        self.assertEqual(red.returncode, 0, red.stderr)
        (self.root / "src/impl.py").write_text("VALUE = True\n")
        (self.root / "tests/__pycache__").mkdir(exist_ok=True)
        (self.root / "tests/__pycache__/generated.pyc").write_bytes(b"cache")
        green = self.call("run", "--repo", str(self.root), "--snapshot", str(snapshot), "--output",
                          str(Path(self.temporary.name) / "green"), "--phase", "green", "--python", PYTHON)
        self.assertEqual(green.returncode, 0, green.stderr)

    def test_skipped_test_is_rejected(self):
        (self.root / "tests/app/test_skip.py").write_text(
            "import pytest\n\n@pytest.mark.skip\ndef test_skip():\n    pass\n")
        snapshot = self.snapshot()
        result = self.call("run", "--repo", str(self.root), "--snapshot", str(snapshot),
                           "--output", str(Path(self.temporary.name) / "out"), "--phase", "green", "--python", PYTHON)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("skipped", result.stderr.lower())

    def test_duplicate_method_names_are_mapped_by_full_id(self):
        (self.root / "tests/app/test_dupes.py").write_text(
            "class TestA:\n    def test_same(self):\n        assert False\n\n"
            "class TestB:\n    def test_same(self):\n        assert True\n")
        snapshot = self.snapshot()
        result = self.call("run", "--repo", str(self.root), "--snapshot", str(snapshot),
                           "--output", str(Path(self.temporary.name) / "out"), "--phase", "red",
                           "--expected-failure", "tests/app/test_dupes.py::TestA::test_same", "--python", PYTHON)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
