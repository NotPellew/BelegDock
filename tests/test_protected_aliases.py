from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "protected_run.py"


class ProtectedAliasTests(unittest.TestCase):
    def test_protected_symlink_to_sandbox_source_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="belegdock-alias-test-") as temporary:
            root = Path(temporary)
            for name in ("src", "docs", "tests"):
                (root / name).mkdir()
            source = root / "src/contract.py"
            source.write_text("original\n")
            (root / "tests/test_contract.py").symlink_to("/workspace/src/contract.py")
            result = subprocess.run(
                [sys.executable, str(LAUNCHER), "--repo", str(root), "--", "/usr/bin/python3", "-c", "from pathlib import Path; Path('src/contract.py').write_text('changed')"],
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())
            self.assertEqual(source.read_text(), "original\n")


if __name__ == "__main__":
    unittest.main()
