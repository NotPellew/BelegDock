import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/test_evidence.py"


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        (self.root / "tests/app").mkdir(parents=True)
        (self.root / "src").mkdir()
        (self.root / "src/feature.py").write_text("value = 1\n")
        (self.root / "tests/app/test_feature.py").write_text("def test_feature():\n    assert True\n")
        self.snapshot = self.root.parent / "snapshot.json"

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(self.root), "--python", sys.executable], text=True, capture_output=True, timeout=30)

    def freeze(self):
        result = self.invoke("snapshot", "--output", str(self.snapshot))
        self.assertEqual(result.returncode, 0, result.stderr)

    def green(self, name):
        output = self.root.parent / name
        return self.invoke("run", "--snapshot", str(self.snapshot), "--output", str(output), "--phase", "green"), output

    def test_source_hash_changes_when_implementation_changes(self):
        self.freeze()
        first, first_output = self.green("first")
        self.assertEqual(first.returncode, 0, first.stderr)
        (self.root / "src/feature.py").write_text("value = 2\n")
        second, second_output = self.green("second")
        self.assertEqual(second.returncode, 0, second.stderr)
        a = json.loads((first_output / "evidence.json").read_text())
        b = json.loads((second_output / "evidence.json").read_text())
        self.assertNotEqual(a["metadata"]["source_hash"], b["metadata"]["source_hash"])

    def test_existing_evidence_directory_cannot_be_overwritten(self):
        self.freeze()
        result, output = self.green("record")
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (output / "evidence.json").read_bytes()
        again, _ = self.green("record")
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual((output / "evidence.json").read_bytes(), original)

    def test_collection_preserves_spaces_in_parameter_ids(self):
        (self.root / "tests/app/test_feature.py").write_text("import pytest\n@pytest.mark.parametrize('value',[True],ids=['has space'])\ndef test_feature(value):\n    assert value\n")
        self.freeze()
        content = json.loads(self.snapshot.read_text())
        self.assertEqual(content["test_ids"], ["tests/app/test_feature.py::test_feature[has space]"])
