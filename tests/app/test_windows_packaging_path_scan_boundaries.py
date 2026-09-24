import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
DATAPROC_V1 = "_internal/googleapiclient/discovery_cache/documents/dataproc.v1.json"
DATAPROC_V1BETA2 = "_internal/googleapiclient/discovery_cache/documents/dataproc.v1beta2.json"
HADOOP_EXAMPLE = "file:///home/usr/lib/hadoop-mapreduce/hadoop-mapreduce-examples.jar"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location(
        "belegdock_build_windows_path_scan_boundaries", path
    )
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingPathScanBoundaryTests(unittest.TestCase):
    def test_exception_literals_are_bounded_to_complete_values(self):
        module = load_build_module()
        cases = {
            DATAPROC_V1: f"/home/usr/bin/other-build/path\n{HADOOP_EXAMPLE}.shadow\n",
            DATAPROC_V1BETA2: "/home/usr/bin\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, content in cases.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            self.assertEqual(module.forbidden_entries(root), sorted(cases))


if __name__ == "__main__":
    unittest.main()
