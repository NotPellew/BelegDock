import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "protected_run.py"
PROTECTED = (
    "tests/test_contract.py",
    "tests/fixtures/input.json",
    "tests/conftest.py",
    "scripts/check.py",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/checks.yml",
    ".git/config",
    ".codex/config.toml",
    "AGENTS.md",
)


class ProtectedSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="belegdock-protection-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        for directory in ("src", "docs", "tests/fixtures", "scripts", ".github/workflows", ".git", ".codex"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in PROTECTED:
            (self.root / name).write_text(f"protected:{name}\n")
        (self.root / "README.md").write_text("Original README\n")

    def run_child(self, code, *, extra=(), env=None):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), "--repo", str(self.root), *extra, "--", "/usr/bin/python3", "-c", code],
            text=True,
            capture_output=True,
            timeout=20,
            env=env,
        )

    def assert_blocked(self, code):
        result = self.run_child(
            "from pathlib import Path\nimport os\n"
            "try:\n"
            + "\n".join("    " + line for line in code.splitlines())
            + "\nexcept OSError:\n    print('BLOCKED')\nelse:\n    print('ALLOWED')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "BLOCKED", result.stdout)

    def test_protected_files_cannot_be_written(self):
        for name in PROTECTED:
            with self.subTest(path=name):
                self.assert_blocked(f"Path({name!r}).write_text('changed')")
                self.assertEqual((self.root / name).read_text(), f"protected:{name}\n")

    def test_delete_rename_replace_and_chmod_are_blocked(self):
        operations = (
            "Path('tests/fixtures/input.json').unlink()",
            "Path('scripts/check.py').rename('scripts/renamed.py')",
            "Path('src/replacement').write_text('changed')\nos.replace('src/replacement', 'tests/test_contract.py')",
            "Path('uv.lock').chmod(0o666)",
            "Path('tests').rename('renamed-tests')",
            "Path('new-test-config').write_text('override')",
        )
        for code in operations:
            with self.subTest(operation=code):
                self.assert_blocked(code)

    def test_protected_files_are_readable_and_allowed_edits_persist(self):
        result = self.run_child(
            "from pathlib import Path\n"
            "print(Path('tests/test_contract.py').read_text().strip())\n"
            "Path('src/feature.py').write_text('value = 1\\n')\n"
            "Path('docs/feature.md').write_text('Feature description\\n')\n"
            "Path('README.md').write_text('Updated README\\n')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "protected:tests/test_contract.py")
        self.assertEqual((self.root / "src/feature.py").read_text(), "value = 1\n")
        self.assertEqual((self.root / "docs/feature.md").read_text(), "Feature description\n")
        self.assertEqual((self.root / "README.md").read_text(), "Updated README\n")

    def test_original_host_path_is_not_an_alternate_route(self):
        original = self.root / "tests/test_contract.py"
        result = self.run_child(f"from pathlib import Path; print(Path({str(original)!r}).exists())")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_existing_symlink_in_writable_tree_rejects_launch(self):
        (self.root / "src/alias").symlink_to("../tests/test_contract.py")
        result = self.run_child("from pathlib import Path; Path('src/executed').touch()")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse((self.root / "src/executed").exists())

    def test_existing_hardlink_in_writable_tree_rejects_launch(self):
        os.link(self.root / "tests/test_contract.py", self.root / "src/alias")
        result = self.run_child("from pathlib import Path; Path('src/executed').touch()")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hardlink", result.stderr.lower())
        self.assertFalse((self.root / "src/executed").exists())

    def test_new_symlink_cannot_write_protected_file(self):
        self.assert_blocked(
            "Path('src/alias').symlink_to('../tests/test_contract.py')\n"
            "Path('src/alias').write_text('changed')"
        )
        self.assertEqual((self.root / "tests/test_contract.py").read_text(), "protected:tests/test_contract.py\n")

    def test_new_hardlink_cannot_alias_protected_file(self):
        self.assert_blocked("os.link('tests/test_contract.py', 'src/alias')")

    def test_nested_user_namespace_cannot_undo_protection(self):
        result = self.run_child(
            "import subprocess\n"
            "attempt = subprocess.run(['unshare', '--user', '--map-root-user', '--mount', 'true'], capture_output=True)\n"
            "print('BLOCKED' if attempt.returncode else 'ALLOWED')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "BLOCKED")

    def test_network_is_off_by_default(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            result = self.run_child(
                "import socket\n"
                "try:\n"
                f"    connection = socket.create_connection(('127.0.0.1', {port}), timeout=1)\n"
                "except OSError:\n    print('BLOCKED')\n"
                "else:\n    connection.close()\n    print('ALLOWED')\n"
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "BLOCKED")

    def test_child_exit_status_is_preserved(self):
        result = self.run_child("import sys; sys.exit(23)")
        self.assertEqual(result.returncode, 23, result.stderr)

    def test_missing_bubblewrap_fails_without_running_child(self):
        env = dict(os.environ, PATH=str(Path(self.temporary.name) / "missing-bin"))
        result = self.run_child("from pathlib import Path; Path('src/executed').touch()", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bubblewrap", result.stderr.lower())
        self.assertFalse((self.root / "src/executed").exists())

    def test_unsupported_platform_fails_without_running_child(self):
        arguments = [str(LAUNCHER), "--repo", str(self.root), "--", "/usr/bin/python3", "-c", "from pathlib import Path; Path('src/executed').touch()"]
        result = subprocess.run(
            [sys.executable, "-c", f"import runpy, sys; sys.platform = 'win32'; sys.argv = {arguments!r}; runpy.run_path({str(LAUNCHER)!r}, run_name='__main__')"],
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("linux", result.stderr.lower())
        self.assertFalse((self.root / "src/executed").exists())


if __name__ == "__main__":
    unittest.main()
