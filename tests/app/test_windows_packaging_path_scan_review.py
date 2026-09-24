import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
DATAPROC_DOCUMENT = "_internal/googleapiclient/discovery_cache/documents/dataproc.v1.json"
DATAPROC_EXAMPLE = "file:///home/usr/lib/hadoop-mapreduce/hadoop-mapreduce-examples.jar"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_path_scan_review", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingPathScanReviewTests(unittest.TestCase):
    def test_dataproc_exception_does_not_hide_another_build_path(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / DATAPROC_DOCUMENT
            path.parent.mkdir(parents=True)
            path.write_text(
                DATAPROC_EXAMPLE + "\nsource=/home/usr/ci/work/BelegDock\n",
                encoding="utf-8",
            )

            self.assertEqual(module.forbidden_entries(root), [DATAPROC_DOCUMENT])

    def test_unreadable_internal_text_is_reported(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("_internal/application/config.json")
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")

            with mock.patch.object(Path, "read_text", side_effect=PermissionError("locked")):
                self.assertEqual(module.forbidden_entries(root), [relative.as_posix()])


if __name__ == "__main__":
    unittest.main()
