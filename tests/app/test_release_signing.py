import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from test_release import WORKFLOW, load_build_module

SETUP = "BelegDock-0.1.0a1-windows-x64-setup.exe"
SIGNED_FIELDS = dict(
    expected_signer="SignPath Foundation",
    subject="CN=SignPath Foundation, O=SignPath Foundation, C=US",
    thumbprint="AB" * 20,
    timestamper="CN=Example Timestamp Authority",
    verified_at="2026-10-21T10:00:00Z",
)


def make_manifest(unsigned: bytes) -> dict:
    return {
        "artifact": SETUP,
        "version": "0.1.0a1",
        "sha256": hashlib.sha256(unsigned).hexdigest(),
        "size": len(unsigned),
        "wheel": "belegdock-0.1.0a1-py3-none-any.whl",
    }


class ApplySignatureTests(unittest.TestCase):
    def test_apply_signature_describes_the_signed_file_and_records_signer(self):
        module = load_build_module()
        manifest = make_manifest(b"unsigned")
        original = copy.deepcopy(manifest)
        with tempfile.TemporaryDirectory() as temporary:
            signed = Path(temporary) / SETUP
            signed.write_bytes(b"unsigned+signature")
            updated = module.apply_signature(manifest, signed, **SIGNED_FIELDS)
        self.assertEqual(updated["sha256"], hashlib.sha256(b"unsigned+signature").hexdigest())
        self.assertEqual(updated["size"], len(b"unsigned+signature"))
        self.assertEqual(
            updated["signature"],
            {
                "expected_signer": "SignPath Foundation",
                "subject": SIGNED_FIELDS["subject"],
                "thumbprint": SIGNED_FIELDS["thumbprint"],
                "timestamper": SIGNED_FIELDS["timestamper"],
                "verified_at": SIGNED_FIELDS["verified_at"],
                "unsigned_sha256": original["sha256"],
            },
        )
        self.assertEqual(updated["wheel"], original["wheel"])
        self.assertEqual(manifest, original)

    def test_apply_signature_rejects_a_file_with_a_different_name(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            signed = Path(temporary) / "BelegDock-9.9.9-windows-x64-setup.exe"
            signed.write_bytes(b"other")
            with self.assertRaises(ValueError):
                module.apply_signature(make_manifest(b"unsigned"), signed, **SIGNED_FIELDS)

    def test_apply_signature_rejects_a_file_identical_to_the_unsigned_one(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            signed = Path(temporary) / SETUP
            signed.write_bytes(b"unsigned")
            with self.assertRaises(ValueError):
                module.apply_signature(make_manifest(b"unsigned"), signed, **SIGNED_FIELDS)

    def test_apply_signature_rejects_a_manifest_that_is_already_signed(self):
        module = load_build_module()
        manifest = make_manifest(b"unsigned")
        manifest["signature"] = {"subject": "CN=x"}
        with tempfile.TemporaryDirectory() as temporary:
            signed = Path(temporary) / SETUP
            signed.write_bytes(b"signed")
            with self.assertRaises(ValueError):
                module.apply_signature(manifest, signed, **SIGNED_FIELDS)

    def test_apply_signature_rejects_an_unexpected_signer_and_empty_metadata(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            signed = Path(temporary) / SETUP
            signed.write_bytes(b"signed")
            wrong = dict(SIGNED_FIELDS, subject="CN=Somebody Else")
            with self.assertRaises(ValueError):
                module.apply_signature(make_manifest(b"unsigned"), signed, **wrong)
            for field in ("thumbprint", "timestamper", "verified_at", "expected_signer"):
                with self.subTest(field=field):
                    with self.assertRaises(ValueError):
                        module.apply_signature(
                            make_manifest(b"unsigned"), signed, **dict(SIGNED_FIELDS, **{field: " "})
                        )

    def test_apply_signature_subcommand_replaces_installer_and_rewrites_manifest(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            (assets / SETUP).write_bytes(b"unsigned")
            (assets / "artifact.json").write_text(
                json.dumps(make_manifest(b"unsigned")), encoding="utf-8"
            )
            signed = root / "signed" / SETUP
            signed.parent.mkdir()
            signed.write_bytes(b"unsigned+signature")
            result = module.main(
                [
                    "apply-signature",
                    "--assets", str(assets),
                    "--signed", str(signed),
                    "--expected-signer", SIGNED_FIELDS["expected_signer"],
                    "--subject", SIGNED_FIELDS["subject"],
                    "--thumbprint", SIGNED_FIELDS["thumbprint"],
                    "--timestamper", SIGNED_FIELDS["timestamper"],
                    "--verified-at", SIGNED_FIELDS["verified_at"],
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual((assets / SETUP).read_bytes(), b"unsigned+signature")
            manifest = json.loads((assets / "artifact.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], hashlib.sha256(b"unsigned+signature").hexdigest())
            self.assertEqual(manifest["signature"]["unsigned_sha256"], hashlib.sha256(b"unsigned").hexdigest())

    def test_apply_signature_subcommand_keeps_assets_when_the_signature_is_rejected(self):
        module = load_build_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            (assets / SETUP).write_bytes(b"unsigned")
            manifest_text = json.dumps(make_manifest(b"unsigned"))
            (assets / "artifact.json").write_text(manifest_text, encoding="utf-8")
            signed = root / SETUP
            signed.write_bytes(b"signed")
            with self.assertRaises(SystemExit):
                module.main(
                    [
                        "apply-signature",
                        "--assets", str(assets),
                        "--signed", str(signed),
                        "--expected-signer", "SignPath Foundation",
                        "--subject", "CN=Somebody Else",
                        "--thumbprint", SIGNED_FIELDS["thumbprint"],
                        "--timestamper", SIGNED_FIELDS["timestamper"],
                        "--verified-at", SIGNED_FIELDS["verified_at"],
                    ]
                )
            self.assertEqual((assets / SETUP).read_bytes(), b"unsigned")
            self.assertEqual((assets / "artifact.json").read_text(encoding="utf-8"), manifest_text)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], start: int, parent_indent: int) -> tuple[list[str], int]:
    end = start
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > parent_indent):
        end += 1
    return lines[start:end], end


def _mapping(lines: list[str], indent: int) -> dict:
    result: dict = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        key, _, value = line.strip().partition(":")
        index += 1
        value = value.strip()
        body, index = _block(lines, index, indent)
        if value in ("|", ">"):
            result[key] = "\n".join(text[indent + 2 :] for text in body)
        elif value:
            result[key] = _unquote(value)
        else:
            result[key] = _mapping(body, indent + 2)
    return result


def load_jobs() -> dict[str, dict]:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index("jobs:") + 1
    body, _ = _block(lines, start, 0)
    jobs: dict[str, dict] = {}
    index = 0
    while index < len(body):
        line = body[index]
        if line.strip() and _indent(line) == 2 and line.rstrip().endswith(":"):
            job_lines, index = _block(body, index + 1, 2)
            steps_at = next(i for i, text in enumerate(job_lines) if text.strip() == "steps:")
            job = _mapping(job_lines[:steps_at], 4)
            steps: list[dict] = []
            current: list[str] = []
            for text in job_lines[steps_at + 1 :]:
                if text.startswith("      - "):
                    if current:
                        steps.append(_mapping(current, 8))
                    current = ["        " + text[8:]]
                elif text.strip():
                    current.append(text)
            if current:
                steps.append(_mapping(current, 8))
            job["steps"] = steps
            jobs[line.strip()[:-1]] = job
        else:
            index += 1
    return jobs


def step_using(job: dict, action: str) -> dict:
    matches = [step for step in job["steps"] if step.get("uses", "").startswith(action)]
    assert len(matches) == 1, f"expected exactly one {action} step, found {len(matches)}"
    return matches[0]


def step_named(job: dict, fragment: str) -> dict:
    matches = [step for step in job["steps"] if fragment in step.get("name", "")]
    assert len(matches) == 1, f"expected exactly one step named like {fragment!r}"
    return matches[0]


def condition(job: dict) -> str:
    text = job["if"].strip()
    match = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


class WorkflowParserTests(unittest.TestCase):
    def test_parser_finds_the_release_jobs_and_steps(self):
        jobs = load_jobs()
        self.assertEqual(set(jobs), {"build", "sign", "publish"})
        self.assertGreater(len(jobs["build"]["steps"]), 5)
        self.assertIn("run", step_named(jobs["build"], "Smoke install"))


class SigningWorkflowTests(unittest.TestCase):
    def test_build_job_uploads_the_unsigned_installer_with_an_exposed_artifact_id(self):
        build = load_jobs()["build"]
        upload = next(
            step for step in build["steps"] if step.get("id") == "upload-unsigned"
        )
        self.assertEqual(upload["uses"], "actions/upload-artifact@v4")
        self.assertIn("windows-x64-setup.exe", upload["with"]["path"])
        self.assertNotIn("artifact.json", upload["with"]["path"])
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertIn("steps.upload-unsigned.outputs.artifact-id", build["outputs"]["unsigned_artifact_id"])

    def test_sign_job_runs_only_when_signpath_is_configured(self):
        sign = load_jobs()["sign"]
        self.assertEqual(sign["needs"], "build")
        self.assertEqual(condition(sign), "vars.SIGNPATH_ORGANIZATION_ID != ''")
        self.assertEqual(sign["runs-on"], "windows-latest")

    def test_sign_job_has_read_only_permissions_needed_by_signpath(self):
        sign = load_jobs()["sign"]
        self.assertEqual(sign["permissions"], {"actions": "read", "contents": "read"})

    def test_sign_job_submits_the_uploaded_artifact_to_signpath_and_waits(self):
        sign = load_jobs()["sign"]
        submit = step_using(sign, "signpath/github-action-submit-signing-request@")
        self.assertEqual(
            submit["uses"], "signpath/github-action-submit-signing-request@v3"
        )
        inputs = submit["with"]
        self.assertEqual(inputs["api-token"], "${{ secrets.SIGNPATH_API_TOKEN }}")
        self.assertEqual(
            inputs["github-artifact-id"], "${{ needs.build.outputs.unsigned_artifact_id }}"
        )
        self.assertEqual(inputs["organization-id"], "${{ vars.SIGNPATH_ORGANIZATION_ID }}")
        self.assertEqual(inputs["project-slug"], "${{ vars.SIGNPATH_PROJECT_SLUG }}")
        self.assertEqual(
            inputs["signing-policy-slug"], "${{ vars.SIGNPATH_SIGNING_POLICY_SLUG }}"
        )
        self.assertIn("SIGNPATH_ARTIFACT_CONFIGURATION_SLUG", inputs["artifact-configuration-slug"])
        self.assertEqual(inputs["wait-for-completion"], "true")
        self.assertGreaterEqual(int(inputs["wait-for-completion-timeout-in-seconds"]), 3600)
        self.assertTrue(inputs["output-artifact-directory"])

    def test_verify_step_fails_closed_unless_signature_is_valid_expected_and_timestamped(self):
        sign = load_jobs()["sign"]
        verify = step_named(sign, "Verify signature")
        script = verify["run"]
        self.assertEqual(verify["shell"], "pwsh")
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertRegex(script, r"\.Status\s+-ne\s+'Valid'")
        self.assertIn("SignerCertificate.Subject", script)
        self.assertIn("$env:EXPECTED_SIGNER", script)
        self.assertRegex(script, r"\$null\s+-eq\s+\$signature\.TimeStamperCertificate")
        self.assertIn("Thumbprint", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("SignPath Foundation", verify["env"]["EXPECTED_SIGNER"])
        self.assertIn("vars.SIGNPATH_EXPECTED_SIGNER", verify["env"]["EXPECTED_SIGNER"])

    def test_sign_job_rebuilds_release_assets_with_the_signed_installer(self):
        sign = load_jobs()["sign"]
        names = [step.get("name", "") for step in sign["steps"]]
        submit = names.index(step_using(sign, "signpath/").get("name", ""))
        verify = names.index(step_named(sign, "Verify signature")["name"])
        apply_index = next(
            i for i, step in enumerate(sign["steps"]) if "apply-signature" in step.get("run", "")
        )
        upload = next(
            i
            for i, step in enumerate(sign["steps"])
            if step.get("uses", "").startswith("actions/upload-artifact@v4")
        )
        self.assertLess(submit, verify)
        self.assertLess(verify, apply_index)
        self.assertLess(apply_index, upload)
        self.assertEqual(sign["steps"][upload]["with"]["name"], "release-assets-signed")
        self.assertEqual(sign["steps"][upload]["with"]["if-no-files-found"], "error")
        download = step_using(sign, "actions/download-artifact@v4")
        self.assertEqual(download["with"]["name"], "release-assets")

    def test_publish_waits_for_sign_and_does_not_run_after_failure_or_cancellation(self):
        publish = load_jobs()["publish"]
        needs = publish["needs"]
        self.assertIn("build", needs)
        self.assertIn("sign", needs)
        expression = condition(publish)
        self.assertIn("!cancelled()", expression)
        self.assertIn("!failure()", expression)
        self.assertIn("needs.sign.result == 'success'", expression)
        self.assertIn("needs.sign.result == 'skipped'", expression)
        self.assertIn("vars.SIGNPATH_ORGANIZATION_ID == ''", expression)

    def test_publish_downloads_the_signed_set_when_signing_ran(self):
        download = step_using(load_jobs()["publish"], "actions/download-artifact@v4")
        name = download["with"]["name"]
        self.assertIn("release-assets-signed", name)
        self.assertIn("needs.sign.result == 'success'", name)
        self.assertIn("'release-assets'", name)

    def test_only_publish_can_write_contents(self):
        jobs = load_jobs()
        for name, job in jobs.items():
            writes = "write" in job.get("permissions", {}).values()
            self.assertEqual(writes, name == "publish", name)
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write"})

    def test_signpath_token_is_only_used_by_the_signing_submission(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            set(re.findall(r"secrets\.(\w+)", text)), {"SIGNPATH_API_TOKEN", "GITHUB_TOKEN"}
        )
        for name, job in load_jobs().items():
            for step in job["steps"]:
                step_text = json.dumps(step)
                if "SIGNPATH_API_TOKEN" in step_text:
                    self.assertEqual(name, "sign")
                    self.assertTrue(step["uses"].startswith("signpath/"))
                    self.assertEqual(step_text.count("SIGNPATH_API_TOKEN"), 1)

    def test_run_scripts_never_interpolate_expressions_directly(self):
        for name, job in load_jobs().items():
            for step in job["steps"]:
                with self.subTest(job=name, step=step.get("name", step.get("uses"))):
                    self.assertNotIn("${{", step.get("run", ""))

    def test_signed_artifact_is_named_in_the_reference_configuration(self):
        path = WORKFLOW.parents[2] / "packaging" / "signpath" / "artifact-configuration.xml"
        text = path.read_text(encoding="utf-8")
        self.assertIn('xmlns="http://signpath.io/artifact-configuration/v1"', text)
        self.assertIn("<zip-file>", text)
        self.assertIn('<pe-file path="BelegDock-*-windows-x64-setup.exe"', text)
        self.assertIn('product-name="BelegDock"', text)
        self.assertIn("<authenticode-sign", text)


if __name__ == "__main__":
    unittest.main()
