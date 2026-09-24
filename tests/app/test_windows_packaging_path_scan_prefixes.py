import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
DATAPROC_V1 = "_internal/googleapiclient/discovery_cache/documents/dataproc.v1.json"
HADOOP_EXAMPLE = "file:///home/usr/lib/hadoop-mapreduce/hadoop-mapreduce-examples.jar"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location(
        "belegdock_build_windows_path_scan_prefixes", path
    )
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingPathScanPrefixTests(unittest.TestCase):
    def test_exception_literals_require_a_leading_value_boundary(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / DATAPROC_V1
            path.parent.mkdir(parents=True)
            path.write_text(
                "file:///home/usr/bin\n"
                "prefix/home/usr/bin\n"
                f"build-prefix/{HADOOP_EXAMPLE}\n",
                encoding="utf-8",
            )

            self.assertEqual(module.forbidden_entries(root), [DATAPROC_V1])


if __name__ == "__main__":
    unittest.main()
