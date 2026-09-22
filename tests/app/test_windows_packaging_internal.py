import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_internal", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingInternalTests(unittest.TestCase):
    def test_bundled_runtime_data_skips_incidental_text_paths_but_keeps_metadata_rules(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = root / "_internal" / "googleapiclient" / "discovery_cache" / "documents"
            documents.mkdir(parents=True)
            (documents / "dataproc.v1.json").write_text(
                '{"example": "/home/usr/bin"}', encoding="utf-8"
            )
            (root / "notes.txt").write_text("built at C:\\Users\\pilot\\src\n", encoding="utf-8")
            (root / "_internal" / "key.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
            internal_tests = root / "_internal" / "tests"
            internal_tests.mkdir()
            (internal_tests / "helper.py").write_text("", encoding="utf-8")

            findings = module.forbidden_entries(root)

            self.assertNotIn(
                "_internal/googleapiclient/discovery_cache/documents/dataproc.v1.json",
                findings,
            )
            self.assertIn("notes.txt", findings)
            self.assertIn("_internal/key.pem", findings)
            self.assertIn("_internal/tests/helper.py", findings)


if __name__ == "__main__":
    unittest.main()
