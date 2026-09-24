import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_pilot_fixtures.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pilot_fixture_generation", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("fixture generator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PilotFixtureGenerationTests(unittest.TestCase):
    def load_module(self):
        return load_module()

    def test_templates_are_small_synthetic_inputs(self):
        templates = ROOT / "pilot_fixtures" / "templates"
        metadata = json.loads((templates / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["source"].split()[0].lower(), "synthetic")
        for name, entry in metadata["files"].items():
            path = templates / name
            self.assertTrue(path.is_file())
            self.assertLessEqual(path.stat().st_size, 5_000_000)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])

    def test_xml_template_is_pinned_to_lf_line_endings(self):
        self.assertTrue((ROOT / ".gitattributes").is_file())
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("pilot_fixtures/templates/*.xml text eol=lf", attributes)
        template = (ROOT / "pilot_fixtures" / "templates" / "accepted-invoice.xml").read_bytes()
        self.assertNotIn(b"\r\n", template)


        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "batch"
            result = module.generate_batch(output, "pilot-001")

            self.assertEqual(result["runId"], "pilot-001")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["runId"], "pilot-001")
            self.assertEqual(
                {entry["file"] for entry in manifest["documents"]},
                {
                    "accepted-001.pdf",
                    "duplicate-001.pdf",
                    "rejected-001.xml",
                    "accepted-002.xml",
                },
            )
            self.assertEqual(
                (output / "accepted-001.pdf").read_bytes(),
                (output / "duplicate-001.pdf").read_bytes(),
            )
            ET.fromstring((output / "accepted-002.xml").read_bytes())
            with self.assertRaises(ET.ParseError):
                ET.fromstring((output / "rejected-001.xml").read_bytes())
            self.assertEqual(module.validate_batch(output)["runId"], "pilot-001")

    def test_same_run_id_is_deterministic_and_new_run_id_is_unique(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            different = root / "different"
            module.generate_batch(first, "pilot-001")
            module.generate_batch(second, "pilot-001")
            module.generate_batch(different, "pilot-002")

            self.assertEqual(
                (first / "accepted-001.pdf").read_bytes(),
                (second / "accepted-001.pdf").read_bytes(),
            )
            self.assertEqual(
                (first / "accepted-001.pdf").read_bytes(),
                (different / "accepted-001.pdf").read_bytes(),
            ) if False else None
            self.assertNotEqual(
                (first / "accepted-001.pdf").read_bytes(),
                (different / "accepted-001.pdf").read_bytes(),
            )
            self.assertNotEqual(
                (first / "accepted-002.xml").read_bytes(),
                (different / "accepted-002.xml").read_bytes(),
            )

    def test_validate_rejects_tampering(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "batch"
            module.generate_batch(output, "pilot-001")
            (output / "accepted-001.pdf").write_bytes(b"tampered")
            with self.assertRaises(module.FixtureError):
                module.validate_batch(output)

    def test_output_must_be_outside_repository_and_not_collide(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(module.FixtureError):
                module.generate_batch(occupied, "pilot-001")
            with self.assertRaises(module.FixtureError):
                module.generate_batch(ROOT / "generated-pilot-batch", "pilot-001")

    def test_run_id_and_attachment_size_are_bounded(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "batch"
            with self.assertRaises(module.FixtureError):
                module.generate_batch(output, "../escape")
            module.generate_batch(output, "pilot-001")
            with self.assertRaises(module.FixtureError):
                module._validate_bytes("oversized.pdf", b"x" * (module.MAX_FILE_SIZE + 1))


if __name__ == "__main__":
    unittest.main()
