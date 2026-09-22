import hashlib
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


def read_text(path: Path) -> str:
    assert path.is_file(), f"missing file: {path.relative_to(ROOT).as_posix()}"
    return path.read_text(encoding="utf-8")


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hidden_imports(spec_text: str) -> set[str]:
    match = re.search(r"HIDDEN_IMPORTS\s*=\s*\[(.*?)\]", spec_text, re.DOTALL)
    assert match is not None, "belegdock.spec has no HIDDEN_IMPORTS list"
    return set(re.findall(r"""["']([^"'\n]+)["']""", match.group(1)))


def dynamic_imports() -> set[str]:
    names = set()
    for module in sorted((ROOT / "src" / "belegdock").glob("*.py")):
        names.update(re.findall(r'import_module\(\s*"([^"]+)"', module.read_text(encoding="utf-8")))
    assert names, "no dynamic imports found in src/belegdock"
    return names


def exe_targets(spec_text: str) -> list[tuple[str, str]]:
    targets = []
    for chunk in spec_text.split("EXE(")[1:]:
        name = re.search(r"""name\s*=\s*["']([^"']+)["']""", chunk)
        console = re.search(r"console\s*=\s*(True|False)", chunk)
        assert name is not None and console is not None, "spec EXE target is incomplete"
        targets.append((name.group(1), console.group(1)))
    return targets


class WindowsPackagingTests(unittest.TestCase):
    def test_installer_is_admin_free_per_user_german_and_versioned(self):
        text = read_text(PACKAGING / "belegdock.iss")
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\BelegDock", text)
        self.assertIn("MinVersion=10.0.19045", text)
        self.assertIn("ArchitecturesAllowed=x64os", text)
        self.assertIn("OutputBaseFilename=BelegDock-{#AppVersion}-windows-x64-setup", text)
        self.assertIn("VersionInfoVersion={#VersionInfo}", text)
        self.assertNotRegex(text, r"VersionInfoVersion=\d")
        self.assertIn("[Languages]", text)
        languages = text.split("[Languages]", 1)[1].split("[", 1)[0]
        lines = [line for line in languages.splitlines() if line.strip()]
        self.assertTrue(lines)
        self.assertIn("german", lines[0].lower())

    def test_installer_preserves_data_and_credentials_on_uninstall(self):
        text = read_text(PACKAGING / "belegdock.iss")
        self.assertNotIn("[UninstallDelete]", text)
        self.assertNotIn("[UninstallRun]", text)
        self.assertNotIn("Credential", text)
        self.assertNotIn("uninsdelete", text.lower())
        self.assertIn("ChangesEnvironment=yes", text)
        self.assertIn("[Code]", text)
        code = text.split("[Code]", 1)[1]
        self.assertIn("HKCU", code)
        self.assertIn("Environment", code)
        self.assertIn("Path", code)

    def test_spec_covers_every_dynamic_import(self):
        spec = read_text(PACKAGING / "belegdock.spec")
        hidden = hidden_imports(spec)
        for name in sorted(dynamic_imports()):
            self.assertIn(name, hidden)
        self.assertIn("tkinter", hidden)
        self.assertIn("keyring.backends.Windows", hidden)

    def test_spec_builds_two_distinct_exe_targets(self):
        spec = read_text(PACKAGING / "belegdock.spec")
        targets = exe_targets(spec)
        self.assertEqual(len(targets), 2)
        names = [name.lower() for name, _ in targets]
        self.assertEqual(len(set(names)), 2)
        consoles = [console for _, console in targets]
        self.assertEqual(consoles.count("False"), 1)
        self.assertEqual(consoles.count("True"), 1)
        self.assertIn("belegdock", names)
        self.assertIn("belegdock-desktop", names)

    def test_build_module_exposes_artifact_helpers(self):
        module = load_build_module()
        self.assertEqual(
            module.artifact_name("0.1.0.dev0"),
            "BelegDock-0.1.0.dev0-windows-x64-setup.exe",
        )
        self.assertIsInstance(module.PYINSTALLER_VERSION, str)
        self.assertRegex(module.PYINSTALLER_VERSION, r"^\d+\.\d+")
        self.assertTrue(callable(module.forbidden_entries))
        self.assertTrue(callable(module.data_dir_is_external))

    def test_build_manifest_records_hashes_and_size(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "BelegDock-0.1.0.dev0-windows-x64-setup.exe"
            artifact.write_bytes(b"installer-bytes")
            wheel = root / "belegdock-0.1.0.dev0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-bytes")
            manifest = module.build_manifest(
                artifact=artifact,
                version="0.1.0.dev0",
                wheel=wheel,
                python="3.12.0",
                pyinstaller=module.PYINSTALLER_VERSION,
                git_revision="abc123",
            )
            self.assertEqual(manifest["artifact"], artifact.name)
            self.assertEqual(manifest["version"], "0.1.0.dev0")
            self.assertEqual(manifest["sha256"], hashlib.sha256(b"installer-bytes").hexdigest())
            self.assertEqual(manifest["size"], len(b"installer-bytes"))
            self.assertEqual(manifest["wheel"], wheel.name)
            self.assertEqual(manifest["wheel_sha256"], hashlib.sha256(b"wheel-bytes").hexdigest())
            self.assertEqual(manifest["python"], "3.12.0")
            self.assertEqual(manifest["pyinstaller"], module.PYINSTALLER_VERSION)
            self.assertEqual(manifest["git_revision"], "abc123")

    def test_forbidden_entries_flags_sensitive_content(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "state.sqlite3").write_bytes(b"db")
            (root / "blobs").mkdir()
            (root / "blobs" / "a.bin").write_bytes(b"data")
            (root / "client_secret.json").write_text("{}", encoding="utf-8")
            (root / "key.pem").write_text("pem", encoding="utf-8")
            (root / ".env").write_text("TOKEN=1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "helper.py").write_text("", encoding="utf-8")
            (root / "test_fixture.py").write_text("", encoding="utf-8")
            (root / "belegdock-0.1.0.dev0-py3-none-any.whl").write_bytes(b"wheel")
            (root / "notes.txt").write_text("built at C:\\Users\\pilot\\src\n", encoding="utf-8")
            (root / "paths.txt").write_text("source /home/pilot/checkout\n", encoding="utf-8")
            findings = module.forbidden_entries(root)
            for expected in (
                "state.sqlite3",
                "blobs/a.bin",
                "client_secret.json",
                "key.pem",
                ".env",
                "tests/helper.py",
                "test_fixture.py",
                "belegdock-0.1.0.dev0-py3-none-any.whl",
                "notes.txt",
                "paths.txt",
            ):
                self.assertIn(expected, findings)

    def test_forbidden_entries_accepts_clean_tree(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "_internal").mkdir()
            (root / "_internal" / "base_library.zip").write_bytes(b"zip")
            (root / "_internal" / "README-Windows.txt").write_text("BelegDock\n", encoding="utf-8")
            (root / "_internal" / "tcl").mkdir()
            (root / "_internal" / "tcl" / "init.tcl").write_text("puts ok\n", encoding="utf-8")
            (root / "belegdock.exe").write_bytes(b"exe")
            (root / "BelegDock-Desktop.exe").write_bytes(b"exe")
            self.assertEqual(module.forbidden_entries(root), [])

    def test_data_dir_is_external_to_install_dir(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "Programs" / "BelegDock"
            install.mkdir(parents=True)
            data = root / "BelegDock"
            data.mkdir()
            inside = install / "data"
            inside.mkdir()
            self.assertTrue(module.data_dir_is_external(data, install))
            self.assertFalse(module.data_dir_is_external(inside, install))
            self.assertFalse(module.data_dir_is_external(install, install))

    def test_pilot_documentation_covers_install_upgrade_and_uninstall(self):
        readme = read_text(ROOT / "README.md")
        pilot = read_text(PACKAGING / "README-Windows.txt")
        for text in (readme, pilot):
            lowered = text.lower()
            self.assertIn("installier", lowered)
            self.assertIn("deinstallier", lowered)
            self.assertTrue("upgrade" in lowered or "aktualisier" in lowered)
            self.assertIn("state.sqlite3", text)
            self.assertTrue(
                "erhalten" in lowered or "behalten" in lowered or "aufbewahr" in lowered
            )
            self.assertIn("login-gmail", text)
            self.assertIn("login-lexware", text)


if __name__ == "__main__":
    unittest.main()
