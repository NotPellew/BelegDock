import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
DISCOVERY_DOCUMENTS = "_internal/googleapiclient/discovery_cache/documents"
KNOWN_GOOGLE_EXAMPLES = {
    f"{DISCOVERY_DOCUMENTS}/cloudidentity.v1.json": (
        r"C:\\Users\\%USERPROFILE%\\.secureConnect\\context_aware_config.json"
    ),
    f"{DISCOVERY_DOCUMENTS}/cloudidentity.v1beta1.json": (
        r"C:\\Users\\%USERPROFILE%\\.secureConnect\\context_aware_config.json"
    ),
    f"{DISCOVERY_DOCUMENTS}/dataproc.v1.json": (
        "file:///home/usr/lib/hadoop-mapreduce/hadoop-mapreduce-examples.jar"
    ),
    f"{DISCOVERY_DOCUMENTS}/dataproc.v1beta2.json": (
        "file:///home/usr/lib/hadoop-mapreduce/hadoop-mapreduce-examples.jar"
    ),
    f"{DISCOVERY_DOCUMENTS}/homegraph.v1.json": (
        "cs//depot/google3/home/homeservicelayer/uddm/types/uddm_device_types.proto"
    ),
}


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_path_scan", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingPathScanTests(unittest.TestCase):
    def test_machine_specific_paths_are_rejected_throughout_bundled_runtime_text(self):
        module = load_build_module()
        cases = {
            "_internal/application/config.json": r"source=C:\Users\pilot\checkout",
            "_internal/application/escaped.json": r"source=C:\\Users\\pilot\\checkout",
            "_internal/application/paths.toml": "source=/home/pilot/checkout",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, content in cases.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            self.assertEqual(module.forbidden_entries(root), sorted(cases))

    def test_documented_google_discovery_examples_are_allowed(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, content in KNOWN_GOOGLE_EXAMPLES.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            self.assertEqual(module.forbidden_entries(root), [])

    def test_known_example_files_do_not_hide_other_machine_specific_paths(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, example in KNOWN_GOOGLE_EXAMPLES.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(example + "\nsource=/home/pilot/private\n", encoding="utf-8")

            self.assertEqual(
                module.forbidden_entries(root),
                sorted(KNOWN_GOOGLE_EXAMPLES),
            )


if __name__ == "__main__":
    unittest.main()
