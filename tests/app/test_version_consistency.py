import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from belegdock import __version__
from belegdock import cli

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
REVISION = "abcdef1234567890abcdef1234567890abcdef12"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_43", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(version=__version__, revision=REVISION):
    return {"version": version, "git_revision": revision}


class VersionConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.module = load_build_module()

    def check(self, **overrides):
        values = {
            "package_version": __version__,
            "pyproject_version": __version__,
            "manifest": manifest(),
            "embedded_revision_value": REVISION,
        }
        values.update(overrides)
        return self.module.version_mismatches(**values)

    def test_matching_versions_pass(self):
        self.assertEqual(self.check(), [])

    def test_source_install_without_revision_passes_when_manifest_has_none(self):
        self.assertEqual(
            self.check(manifest=manifest(revision=""), embedded_revision_value=None),
            [],
        )

    def test_pyproject_mismatch_fails(self):
        errors = self.check(pyproject_version="9.9.9")

        self.assertTrue(errors)
        self.assertTrue(any("9.9.9" in error for error in errors))

    def test_manifest_version_mismatch_fails(self):
        errors = self.check(manifest=manifest(version="9.9.9"))

        self.assertTrue(errors)
        self.assertTrue(any("9.9.9" in error for error in errors))

    def test_manifest_revision_mismatch_fails(self):
        errors = self.check(
            manifest=manifest(revision="0" * 40),
        )

        self.assertTrue(errors)

    def test_missing_embedded_revision_fails_when_manifest_has_revision(self):
        errors = self.check(embedded_revision_value=None)

        self.assertTrue(errors)

    def test_embedded_revision_reads_bundle_data_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            target = bundle / "_internal" / "belegdock" / "build_revision.txt"
            target.parent.mkdir(parents=True)
            target.write_text(REVISION + "\n", encoding="utf-8")

            self.assertEqual(self.module.embedded_revision(bundle), REVISION)
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(self.module.embedded_revision(Path(temporary)))

    def test_repository_versions_agree(self):
        self.assertEqual(self.module._project_version(), __version__)

    def test_spec_embeds_revision_data_file(self):
        spec_text = (PACKAGING / "belegdock.spec").read_text(encoding="utf-8")

        self.assertIn("BELEGDOCK_BUILD_REVISION_FILE", spec_text)
        self.assertIn("build_revision.txt", spec_text)

    def test_check_artifact_fails_on_manifest_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = Path(temporary)
            installer = dist / "BelegDock-9.9.9-windows-x64-setup.exe"
            installer.write_bytes(b"installer")
            (dist / self.module.BUNDLE_NAME).mkdir()
            (dist / "artifact.json").write_text(
                json.dumps(
                    {
                        "artifact": installer.name,
                        "sha256": self.module.sha256_file(installer),
                        "size": installer.stat().st_size,
                        "version": "9.9.9",
                        "git_revision": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as raised:
                self.module.cmd_check_artifact(SimpleNamespace(dist=dist))

        self.assertIn("version mismatch", str(raised.exception))
        self.assertIn("9.9.9", str(raised.exception))

    def test_about_identity_must_match_the_manifest(self):
        records = [{"state": "about", "version": __version__, "revision": REVISION[:7]}]

        self.assertEqual(self.module.about_identity_mismatches(records, manifest()), [])
        self.assertTrue(self.module.about_identity_mismatches(records, manifest(version="9.9.9")))
        self.assertTrue(self.module.about_identity_mismatches(records, manifest(revision="1234567890")))
        self.assertTrue(
            self.module.about_identity_mismatches([{"state": "about", "open": True}], manifest())
        )
        self.assertEqual(
            self.module.about_identity_mismatches(
                [{"state": "about", "version": __version__, "revision": ""}], manifest(revision=None)
            ),
            [],
        )

    def test_desktop_smoke_invokes_the_about_button(self):
        smoke = (ROOT / "src" / "belegdock" / "desktop_smoke.py").read_text(encoding="utf-8")

        self.assertIn("about_button.invoke()", smoke)

    def test_cli_version_agrees_with_package_version(self):
        output = StringIO()
        with redirect_stdout(output):
            status = cli.main(["--version"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), __version__)


if __name__ == "__main__":
    unittest.main()
