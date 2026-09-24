import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "pilot_fixtures" / "templates"
MAX_FILE_SIZE = 5_000_000
PDF_TEMPLATE = "accepted-invoice.pdf"
XML_TEMPLATE = "accepted-invoice.xml"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PDF_ID_PATTERN = re.compile(rb"/ID\[<[0-9A-Fa-f]{32}><[0-9A-Fa-f]{32}>\]")


class FixtureError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise FixtureError("run ID must contain only letters, numbers, dots, underscores, or hyphens")
    return run_id


def _validate_bytes(filename: str, data: bytes) -> None:
    if (
        not isinstance(filename, str)
        or not filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        raise FixtureError("fixture filename is invalid")
    if not isinstance(data, bytes):
        raise FixtureError("fixture data must be bytes")
    if len(data) > MAX_FILE_SIZE:
        raise FixtureError(f"fixture exceeds the {MAX_FILE_SIZE}-byte limit: {filename}")
    if Path(filename).suffix.lower() not in {".pdf", ".xml"}:
        raise FixtureError(f"unsupported fixture format: {filename}")


def _regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise FixtureError(f"template is unavailable: {path.name}") from error
    if not stat.S_ISREG(info.st_mode):
        raise FixtureError(f"template is not a regular file: {path.name}")


def _load_template_metadata(template_dir: Path) -> dict[str, Any]:
    metadata_path = template_dir / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureError("template metadata is unavailable or invalid") from error
    if not isinstance(metadata, dict) or not isinstance(metadata.get("version"), str):
        raise FixtureError("template metadata is invalid")
    files = metadata.get("files")
    if not isinstance(files, dict):
        raise FixtureError("template metadata has no file entries")
    return metadata


def _load_template(template_dir: Path, metadata: dict[str, Any], name: str) -> bytes:
    if name not in {PDF_TEMPLATE, XML_TEMPLATE}:
        raise FixtureError(f"unknown template: {name}")
    path = template_dir / name
    _regular_file(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise FixtureError(f"template cannot be read: {name}") from error
    if len(data) > MAX_FILE_SIZE:
        raise FixtureError(f"template exceeds the {MAX_FILE_SIZE}-byte limit: {name}")
    entries = metadata.get("files")
    entry = entries.get(name) if isinstance(entries, dict) else None
    if not isinstance(entry, dict) or entry.get("sha256") != _sha256(data):
        raise FixtureError(f"template hash does not match metadata: {name}")
    return data


def _vary_pdf(data: bytes, run_id: str) -> bytes:
    if not data.startswith(b"%PDF-") or data.count(b"%%EOF") != 1:
        raise FixtureError("PDF template is not a single-document PDF")
    first = hashlib.sha256((run_id + ":first").encode("ascii")).hexdigest()[:32].upper()
    second = hashlib.sha256((run_id + ":second").encode("ascii")).hexdigest()[:32].upper()
    replacement = f"/ID[<{first}><{second}>]".encode("ascii")
    varied, count = PDF_ID_PATTERN.subn(replacement, data, count=1)
    if count != 1:
        raise FixtureError("PDF template has no fixed-length document identifier")
    if len(varied) != len(data):
        raise FixtureError("PDF template identifier transformation changed its length")
    return varied


def _vary_xml(data: bytes, run_id: str) -> bytes:
    try:
        ET.fromstring(data)
    except ET.ParseError as error:
        raise FixtureError("XML template is not well-formed") from error
    marker = 1 + int(hashlib.sha256(run_id.encode("ascii")).hexdigest(), 16) % 4096
    return data + b"\n" + (b" " * marker) + b"\n"


def _malformed_xml(data: bytes) -> bytes:
    closing = b"</Invoice>"
    position = data.rfind(closing)
    if position < 0:
        raise FixtureError("XML template has no Invoice closing element")
    malformed = data[:position] + data[position + len(closing) :]
    try:
        ET.fromstring(malformed)
    except ET.ParseError:
        return malformed
    raise FixtureError("malformed XML transformation remained well-formed")


def _expected_files(run_id: str, template_dir: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    template_dir = Path(template_dir).resolve()
    metadata = _load_template_metadata(template_dir)
    pdf_template = _load_template(template_dir, metadata, PDF_TEMPLATE)
    xml_template = _load_template(template_dir, metadata, XML_TEMPLATE)
    accepted_pdf = _vary_pdf(pdf_template, run_id)
    accepted_xml = _vary_xml(xml_template, run_id)
    files = {
        "accepted-001.pdf": accepted_pdf,
        "duplicate-001.pdf": accepted_pdf,
        "rejected-001.xml": _malformed_xml(_vary_xml(xml_template, run_id)),
        "accepted-002.xml": accepted_xml,
    }
    return metadata, files


def _prepare_output(output: Path) -> Path:
    raw = Path(output).expanduser()
    if raw.is_symlink():
        raise FixtureError("output directory must not be a symlink")
    resolved = raw.resolve()
    repository = REPO_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise FixtureError("output directory must be outside the repository")
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise FixtureError("output directory must be new or empty")
    else:
        resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _entry(filename: str, role: str, expected: str, data: bytes) -> dict[str, Any]:
    _validate_bytes(filename, data)
    return {
        "file": filename,
        "role": role,
        "expected": expected,
        "size": len(data),
        "sha256": _sha256(data),
    }


def generate_batch(
    output: Path,
    run_id: str,
    template_dir: Path = TEMPLATE_DIR,
) -> dict[str, Any]:
    run_id = _validate_run_id(run_id)
    output = _prepare_output(Path(output))
    template_dir = Path(template_dir).resolve()
    metadata, expected_files = _expected_files(run_id, template_dir)
    roles = {
        "accepted-001.pdf": ("accepted", "accept"),
        "duplicate-001.pdf": ("duplicate", "deduplicate"),
        "rejected-001.xml": ("rejected", "reject"),
        "accepted-002.xml": ("accepted", "accept"),
    }
    entries = []
    for filename, data in expected_files.items():
        role, expected = roles[filename]
        _validate_bytes(filename, data)
        (output / filename).write_bytes(data)
        entries.append(_entry(filename, role, expected, data))
    manifest = {
        "schemaVersion": 1,
        "runId": run_id,
        "templateVersion": metadata["version"],
        "documents": entries,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_batch(output)


def _validate_manifest_entry(batch: Path, entry: Any) -> tuple[dict[str, Any], bytes]:
    if not isinstance(entry, dict):
        raise FixtureError("manifest document entry is invalid")
    required = {"file", "role", "expected", "size", "sha256"}
    if set(entry) != required:
        raise FixtureError("manifest document entry has unexpected fields")
    filename = entry["file"]
    if not isinstance(filename, str):
        raise FixtureError("manifest filename is invalid")
    _validate_bytes(filename, b"x")
    if Path(filename).name != filename:
        raise FixtureError("manifest filename must not contain a directory")
    path = batch / filename
    if path.parent != batch or path.is_symlink():
        raise FixtureError("manifest document path is unsafe")
    _regular_file(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise FixtureError(f"manifest document cannot be read: {filename}") from error
    if not isinstance(entry["size"], int) or isinstance(entry["size"], bool):
        raise FixtureError("manifest document size is invalid")
    if entry["size"] != len(data) or not isinstance(entry["sha256"], str):
        raise FixtureError("manifest document metadata is invalid")
    if entry["sha256"] != _sha256(data):
        raise FixtureError(f"manifest hash mismatch: {filename}")
    role_expectations = {"accepted": "accept", "duplicate": "deduplicate", "rejected": "reject"}
    if entry["role"] not in role_expectations:
        raise FixtureError("manifest document role is invalid")
    if entry["expected"] != role_expectations[entry["role"]]:
        raise FixtureError("manifest document expectation does not match its role")
    if entry["role"] == "rejected":
        try:
            ET.fromstring(data)
        except ET.ParseError:
            pass
        else:
            raise FixtureError("rejected XML fixture is well-formed")
    else:
        ET.fromstring(data) if filename.endswith(".xml") else None
    if filename.endswith(".pdf") and (not data.startswith(b"%PDF-") or not data.endswith(b"%%EOF\r\n")):
        raise FixtureError("PDF fixture is malformed")
    return ({
        "file": filename,
        "role": entry["role"],
        "expected": entry["expected"],
        "size": entry["size"],
        "sha256": entry["sha256"],
    }, data)


def _validate_batch(
    batch: Path,
    template_dir: Path = TEMPLATE_DIR,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    raw_batch = Path(batch).expanduser()
    if raw_batch.is_symlink():
        raise FixtureError("fixture batch directory must not be a symlink")
    batch = raw_batch.resolve()
    if not batch.is_dir():
        raise FixtureError("fixture batch directory is unavailable")
    manifest_path = batch / "manifest.json"
    _regular_file(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureError("fixture manifest is unavailable or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise FixtureError("fixture manifest schema is invalid")
    run_id_value = manifest.get("runId")
    if not isinstance(run_id_value, str):
        raise FixtureError("fixture manifest run ID is invalid")
    run_id = _validate_run_id(run_id_value)
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise FixtureError("fixture manifest has no documents")
    if len({entry.get("file") for entry in documents if isinstance(entry, dict)}) != len(documents):
        raise FixtureError("fixture manifest has duplicate filenames")
    validated_with_data = [_validate_manifest_entry(batch, entry) for entry in documents]
    validated = [entry for entry, _ in validated_with_data]
    actual_files = {entry["file"]: data for entry, data in validated_with_data}
    metadata, expected_files = _expected_files(run_id, template_dir)
    if manifest.get("templateVersion") != metadata["version"]:
        raise FixtureError("fixture manifest template version is invalid")
    if set(actual_files) != set(expected_files):
        raise FixtureError("fixture manifest does not contain the generated fixture set")
    for filename, expected_data in expected_files.items():
        if actual_files[filename] != expected_data:
            raise FixtureError(f"fixture bytes do not match the trusted template batch: {filename}")
    roles = [entry["role"] for entry in validated]
    if sorted(roles) != ["accepted", "accepted", "duplicate", "rejected"]:
        raise FixtureError("fixture manifest has an unexpected role set")
    accepted_pdfs = [
        entry for entry in validated if entry["role"] == "accepted" and entry["file"].endswith(".pdf")
    ]
    if len(accepted_pdfs) != 1:
        raise FixtureError("fixture manifest has no unique accepted PDF")
    duplicate = next(entry for entry in validated if entry["role"] == "duplicate")
    if not duplicate["file"].endswith(".pdf"):
        raise FixtureError("duplicate fixture must be a PDF")
    if duplicate["sha256"] != accepted_pdfs[0]["sha256"] or duplicate["size"] != accepted_pdfs[0]["size"]:
        raise FixtureError("duplicate fixture does not match the accepted PDF")
    manifest_sha256 = _sha256(manifest_path.read_bytes())
    return {
        "runId": run_id,
        "templateVersion": manifest["templateVersion"],
        "manifestSha256": manifest_sha256,
        "documents": validated,
    }, actual_files


def validated_batch(
    batch: Path,
    template_dir: Path = TEMPLATE_DIR,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    return _validate_batch(batch, template_dir)


def validate_batch(batch: Path, template_dir: Path = TEMPLATE_DIR) -> dict[str, Any]:
    return _validate_batch(batch, template_dir)[0]


def validated_files(batch: Path, template_dir: Path = TEMPLATE_DIR) -> dict[str, bytes]:
    return _validate_batch(batch, template_dir)[1]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic pilot fixtures.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--run-id", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--batch", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "generate":
            result = generate_batch(args.output, args.run_id)
        else:
            result = validate_batch(args.batch)
    except (FixtureError, OSError, ValueError) as error:
        print(f"pilot fixture operation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
