import contextlib
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    assert path.is_file(), "missing packaging/build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_release", path)
    assert spec is not None and spec.loader is not None, "build_windows.py is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_workflow() -> str:
    assert WORKFLOW.is_file(), "missing .github/workflows/release.yml"
    return WORKFLOW.read_text(encoding="utf-8")


class ReleaseTagTests(unittest.TestCase):
    def test_version_from_tag_strips_leading_v(self):
        module = load_build_module()
        self.assertEqual(module.version_from_tag("v0.1.0"), "0.1.0")
        self.assertEqual(module.version_from_tag("v0.1.0.dev0"), "0.1.0.dev0")
        self.assertEqual(module.version_from_tag("v1.2.3rc1"), "1.2.3rc1")

    def test_version_from_tag_rejects_missing_or_empty_version(self):
        module = load_build_module()
        for tag in ("0.1.0", "v", "", "release-0.1.0"):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    module.version_from_tag(tag)

    def test_validate_release_tag_accepts_matching_project_version(self):
        module = load_build_module()
        self.assertEqual(
            module.validate_release_tag("v0.1.0.dev0", "0.1.0.dev0"), "0.1.0.dev0"
        )
        self.assertEqual(module.validate_release_tag("v1.0.0", "1.0.0"), "1.0.0")

    def test_validate_release_tag_rejects_mismatched_project_version(self):
        module = load_build_module()
        with self.assertRaises(ValueError) as raised:
            module.validate_release_tag("v0.2.0", "0.1.0.dev0")
        message = str(raised.exception)
        self.assertIn("0.2.0", message)
        self.assertIn("0.1.0.dev0", message)

    def test_validate_release_tag_rejects_tag_without_v(self):
        module = load_build_module()
        with self.assertRaises(ValueError):
            module.validate_release_tag("0.1.0.dev0", "0.1.0.dev0")


class PrereleaseTests(unittest.TestCase):
    def test_is_prerelease_for_pep440_pre_and_dev_versions(self):
        module = load_build_module()
        for version in (
            "0.1.0a1",
            "0.1.0alpha1",
            "0.1.0b2",
            "0.1.0rc1",
            "0.1.0.dev0",
            "1.0.0a1.dev1",
            "1.0.0-rc1",
        ):
            with self.subTest(version=version):
                self.assertTrue(module.is_prerelease(version))

    def test_is_prerelease_false_for_final_versions(self):
        module = load_build_module()
        for version in ("0.1.0", "1.2.3", "0.1.0.post1", "1.0.0+build1"):
            with self.subTest(version=version):
                self.assertFalse(module.is_prerelease(version))


class ChecksumsTests(unittest.TestCase):
    def test_sha256sums_content_uses_sha256sum_format_sorted_by_name(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "belegdock-0.1.0.dev0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-bytes")
            setup = root / "BelegDock-0.1.0.dev0-windows-x64-setup.exe"
            setup.write_bytes(b"installer-bytes")
            content = module.sha256sums_content([wheel, setup])
            expected = (
                f"{hashlib.sha256(b'installer-bytes').hexdigest()}  {setup.name}\n"
                f"{hashlib.sha256(b'wheel-bytes').hexdigest()}  {wheel.name}\n"
            )
            self.assertEqual(content, expected)

    def test_sha256sums_content_excludes_the_sums_file_itself(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "artifact.json"
            asset.write_text("{}", encoding="utf-8")
            sums = root / "SHA256SUMS.txt"
            sums.write_text("stale\n", encoding="utf-8")
            content = module.sha256sums_content([sums, asset])
            self.assertNotIn("SHA256SUMS.txt", content)
            self.assertIn("artifact.json", content)

    def test_sha256sums_content_empty_without_assets(self):
        module = load_build_module()
        self.assertEqual(module.sha256sums_content([]), "")

    def test_write_checksums_subcommand_writes_sha256sums_file(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "artifact.json"
            asset.write_bytes(b"manifest")
            output = root / "SHA256SUMS.txt"
            result = module.main(
                ["write-checksums", "--output", str(output), str(asset)]
            )
            self.assertEqual(result, 0)
            expected = f"{hashlib.sha256(b'manifest').hexdigest()}  artifact.json\n"
            self.assertEqual(output.read_text(encoding="utf-8"), expected)


class ReleaseSubcommandTests(unittest.TestCase):
    def test_check_release_tag_subcommand_reports_version_and_prerelease(self):
        module = load_build_module()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = module.main(["check-release-tag", "--tag", "v0.1.0.dev0"])
        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("version=0.1.0.dev0", output)
        self.assertIn("prerelease=true", output)

    def test_check_release_tag_subcommand_fails_closed_on_mismatch(self):
        module = load_build_module()
        with self.assertRaises(SystemExit) as raised:
            module.main(["check-release-tag", "--tag", "v9.9.9"])
        self.assertIn("9.9.9", str(raised.exception))


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_triggers_on_version_tags_and_dispatch_tag(self):
        text = read_workflow()
        self.assertIn("tags:", text)
        self.assertIn('"v*"', text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("required: true", text)
        self.assertIn("inputs.tag", text)

    def test_release_workflow_limits_write_permission_to_publish_job(self):
        text = read_workflow()
        self.assertEqual(text.count("contents: write"), 1)
        self.assertIn("contents: read", text)
        self.assertIn("needs: build", text)
        self.assertIn("gh release create", text)
        self.assertIn("--prerelease", text)
        self.assertNotIn("softprops", text)
        self.assertNotIn("action-gh-release", text)

    def test_release_workflow_reuses_build_checks_and_pinned_actions(self):
        text = read_workflow()
        self.assertIn("actions/checkout@v4", text)
        self.assertIn("astral-sh/setup-uv@v6", text)
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("actions/download-artifact@v4", text)
        self.assertIn("build_windows.py build", text)
        self.assertIn("check-artifact", text)
        self.assertIn("smoke-install", text)
        self.assertIn("uv build", text)

    def test_release_workflow_publishes_all_release_assets(self):
        text = read_workflow()
        self.assertIn("windows-x64-setup.exe", text)
        self.assertIn("*.whl", text)
        self.assertIn("*.tar.gz", text)
        self.assertIn("artifact.json", text)
        self.assertIn("SHA256SUMS.txt", text)
        self.assertIn("write-checksums", text)
        self.assertIn("check-release-tag", text)


if __name__ == "__main__":
    unittest.main()
