import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_bounds", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsPackagingBoundsTests(unittest.TestCase):
    def test_public_ca_bundle_is_allowed_but_private_keys_are_not(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certifi = root / "_internal" / "certifi"
            certifi.mkdir(parents=True)
            (certifi / "cacert.pem").write_text("PUBLIC CA BUNDLE\n", encoding="utf-8")
            (root / "client-key.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
            lookalike = root / "other"
            lookalike.mkdir()
            (lookalike / "cacert.pem").write_text("lookalike pem\n", encoding="utf-8")

            findings = module.forbidden_entries(root)

            self.assertNotIn("_internal/certifi/cacert.pem", findings)
            self.assertIn("client-key.pem", findings)
            self.assertIn("other/cacert.pem", findings)

    def test_artifact_check_requires_the_tls_trust_store(self):
        module = load_build_module()
        self.assertIn("certifi", module.REQUIRED_MODULES)
        required_files = getattr(module, "REQUIRED_BUNDLE_FILES", ())
        normalized = {str(entry).replace("\\", "/") for entry in required_files}
        self.assertIn("certifi/cacert.pem", normalized)

    def test_bundle_expectations_follow_pyinstaller_tcl_data_names(self):
        module = load_build_module()
        entries = set(module.REQUIRED_BUNDLE_ENTRIES)
        self.assertIn("_tcl_data", entries)
        self.assertIn("_tk_data", entries)
        self.assertNotIn("tcl", entries)
        self.assertNotIn("tk", entries)

    def test_desktop_probe_accepts_only_the_credential_failure(self):
        module = load_build_module()
        probe = getattr(module, "desktop_probe_is_credential_failure", None)
        self.assertTrue(
            callable(probe), "build_windows.desktop_probe_is_credential_failure is missing"
        )
        credential_failure = (
            "belegdock: Desktop-Vorgang fehlgeschlagen; prüfe die Python-Tk-Unterstützung "
            "und die Kontoeinrichtung."
        )
        self.assertTrue(probe(1, credential_failure))
        self.assertFalse(probe(0, credential_failure))
        self.assertFalse(
            probe(
                1,
                "Desktop-Oberfläche ist nicht verfügbar; installiere Python-Tk-Unterstützung "
                "und starte „belegdock desktop“ erneut.",
            )
        )
        self.assertFalse(probe(1, "BelegDock konnte nicht gestartet werden."))


if __name__ == "__main__":
    unittest.main()
