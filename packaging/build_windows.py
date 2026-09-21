import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PYINSTALLER_VERSION = "6.11.1"
BUNDLE_NAME = "BelegDock"
CONSOLE_EXE = "belegdock.exe"
GUI_EXE = "BelegDock-Desktop.exe"
DEFAULT_VERSION = "0.1.0.dev0"

BUILD_ROOT = Path(r"C:\belegdock-build")
VENV_DIR = BUILD_ROOT / "venv"
WORK_DIR = BUILD_ROOT / "work"

PACKAGING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGING_DIR.parent
SPEC_FILE = PACKAGING_DIR / "belegdock.spec"
ISS_FILE = PACKAGING_DIR / "belegdock.iss"

FORBIDDEN_NAMES = {"state.sqlite3", ".env"}
FORBIDDEN_PARTS = {"blobs", "tests"}
FORBIDDEN_SUFFIXES = {".pem", ".whl"}
FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"^client.*\.json$", re.IGNORECASE),
    re.compile(r"^test_.*\.py$", re.IGNORECASE),
)
FORBIDDEN_TEXT_PATTERNS = (
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
)
TEXT_SUFFIXES = {
    ".py",
    ".txt",
    ".json",
    ".toml",
    ".md",
    ".iss",
    ".spec",
    ".yml",
    ".yaml",
    ".cfg",
    ".ini",
    ".ps1",
    ".sh",
}

REQUIRED_BUNDLE_ENTRIES = ("_tkinter.pyd", "tcl", "tk", CONSOLE_EXE, GUI_EXE)
REQUIRED_MODULES = (
    "belegdock.cli",
    "belegdock.desktop",
    "googleapiclient.discovery",
    "google_auth_oauthlib.flow",
    "google.oauth2.credentials",
    "google.auth.transport.requests",
    "httpx",
    "keyring.backends.Windows",
    "platformdirs",
    "tkinter",
)

SILENT_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]


def artifact_name(version: str) -> str:
    return f"BelegDock-{version}-windows-x64-setup.exe"


def version_info(version: str) -> str:
    numbers = re.findall(r"\d+", version)[:4]
    numbers += ["0"] * (4 - len(numbers))
    return ".".join(numbers)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    artifact: Path,
    version: str,
    wheel: Path,
    python: str,
    pyinstaller: str,
    git_revision: str,
) -> dict:
    artifact_path = Path(artifact)
    wheel_path = Path(wheel)
    return {
        "artifact": artifact_path.name,
        "version": version,
        "sha256": sha256_file(artifact_path),
        "size": artifact_path.stat().st_size,
        "wheel": wheel_path.name,
        "wheel_sha256": sha256_file(wheel_path),
        "python": python,
        "pyinstaller": pyinstaller,
        "git_revision": git_revision,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def forbidden_entries(root: Path) -> list[str]:
    root = Path(root)
    findings = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        name = path.name
        if name in FORBIDDEN_NAMES or set(relative.parts) & FORBIDDEN_PARTS:
            findings.add(relative.as_posix())
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.add(relative.as_posix())
            continue
        if any(pattern.match(name) for pattern in FORBIDDEN_NAME_PATTERNS):
            findings.add(relative.as_posix())
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            text = _read_text(path)
            if any(pattern.search(text) for pattern in FORBIDDEN_TEXT_PATTERNS):
                findings.add(relative.as_posix())
    return sorted(findings)


def data_dir_is_external(data_dir: Path, install_dir: Path) -> bool:
    data = Path(data_dir).resolve()
    install = Path(install_dir).resolve()
    return data != install and install not in data.parents


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"artifact check failed: {message}")


def _run(command, **kwargs) -> None:
    printable = " ".join(str(item) for item in command)
    print(f"+ {printable}", flush=True)
    subprocess.run([str(item) for item in command], check=True, **kwargs)


def _capture(command) -> str:
    result = subprocess.run(
        [str(item) for item in command], check=True, capture_output=True, text=True
    )
    return result.stdout


def _project_version() -> str:
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return DEFAULT_VERSION
    import tomllib

    with pyproject.open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _reset_build_root() -> None:
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    WORK_DIR.mkdir(parents=True)


def _create_venv() -> Path:
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    python = VENV_DIR / "Scripts" / "python.exe"
    _require(python.is_file(), "temporary build environment has no interpreter")
    return python


def _find_bundle_entry(bundle: Path, name: str) -> Path | None:
    for candidate in (bundle / name, bundle / "_internal" / name):
        if candidate.exists():
            return candidate
    return None


def _archive_viewer() -> Path:
    viewer = VENV_DIR / "Scripts" / "pyi-archive_viewer.exe"
    _require(viewer.is_file(), "pyi-archive_viewer is missing; run build first")
    return viewer


def cmd_build(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        raise SystemExit("the windows installer can only be built on Windows")
    wheel = Path(args.wheel).resolve(strict=True)
    dist = Path(args.dist).resolve()
    version = _project_version()
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    _reset_build_root()
    python = _create_venv()
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-input",
            "--no-cache-dir",
            "--disable-pip-version-check",
            str(wheel),
            f"pyinstaller=={PYINSTALLER_VERSION}",
        ]
    )
    environment = dict(os.environ)
    environment["BELEGDOCK_VERSION"] = version
    _run(
        [
            python,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(WORK_DIR / "pyinstaller"),
            str(SPEC_FILE),
        ],
        env=environment,
    )
    bundle = dist / BUNDLE_NAME
    _require(bundle.is_dir(), f"expected onedir bundle at {bundle}")
    _run(
        [
            "iscc",
            f"/DAppVersion={version}",
            f"/DVersionInfo={version_info(version)}",
            f"/DDistDir={dist}",
            f"/DBundleDir={bundle}",
            str(ISS_FILE),
        ]
    )
    artifact = dist / artifact_name(version)
    _require(artifact.is_file(), f"missing installer {artifact}")
    manifest = build_manifest(
        artifact=artifact,
        version=version,
        wheel=wheel,
        python=sys.version.split()[0],
        pyinstaller=PYINSTALLER_VERSION,
        git_revision=_git_revision(),
    )
    (dist / "artifact.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_check_artifact(args: argparse.Namespace) -> int:
    dist = Path(args.dist).resolve(strict=True)
    manifest = json.loads((dist / "artifact.json").read_text(encoding="utf-8"))
    artifact = dist / manifest["artifact"]
    _require(artifact.is_file(), f"missing installer {artifact}")
    _require(sha256_file(artifact) == manifest["sha256"], "installer hash differs from manifest")
    _require(artifact.stat().st_size == manifest["size"], "installer size differs from manifest")
    bundle = dist / BUNDLE_NAME
    _require(bundle.is_dir(), "missing onedir bundle")
    for entry in REQUIRED_BUNDLE_ENTRIES:
        _require(
            _find_bundle_entry(bundle, entry) is not None,
            f"bundle misses {entry}",
        )
    _require(not forbidden_entries(dist), "forbidden content found in the artifact folder")
    listing = subprocess.run(
        [str(_archive_viewer()), "-r", str(bundle / CONSOLE_EXE)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for module in REQUIRED_MODULES:
        _require(module in listing, f"console archive misses module {module}")
    print("artifact check passed")
    return 0


def _read_user_path(winreg) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return str(value)
    except OSError:
        return ""


def _start_menu_link() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "BelegDock.lnk"
    )


def cmd_smoke_install(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        raise SystemExit("smoke-install is supported on Windows only")
    import winreg

    dist = Path(args.dist).resolve(strict=True)
    manifest = json.loads((dist / "artifact.json").read_text(encoding="utf-8"))
    setup = dist / manifest["artifact"]
    install_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "BelegDock"
    data_dir = Path(os.environ["LOCALAPPDATA"]) / "BelegDock"
    console = install_dir / CONSOLE_EXE
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)

    _run([setup, *SILENT_FLAGS])
    _require(console.is_file(), "console executable missing after install")
    _require((install_dir / GUI_EXE).is_file(), "desktop executable missing after install")
    _require(not data_dir.exists(), "installer created the user data directory")
    _require(
        str(install_dir).lower() in _read_user_path(winreg).lower(),
        "install directory missing from the per-user PATH",
    )
    link = _start_menu_link()
    _require(link.is_file(), "start menu shortcut missing after install")

    _require(_capture([console, "--version"]).strip() == manifest["version"], "unexpected version")
    _require("Schnellstart:" in _capture([console, "--help"]), "help output misses German quick start")
    _run([console, "--data-dir", str(data_dir), "documents"])
    _require((data_dir / "state.sqlite3").is_file(), "documents did not initialize local state")
    probe = subprocess.run([str(console), "desktop"], capture_output=True, text=True, timeout=120)
    _require(probe.returncode == 1, "desktop probe did not fail without credentials")
    _require("Desktop" in probe.stderr, "desktop probe did not report the German failure")
    _require(data_dir_is_external(data_dir, install_dir), "user data is inside the install directory")

    _run([install_dir / "unins000.exe", *SILENT_FLAGS])
    _require(not install_dir.exists(), "install directory survived the silent uninstall")
    _require(
        str(install_dir).lower() not in _read_user_path(winreg).lower(),
        "per-user PATH entry survived the silent uninstall",
    )
    _require(not link.exists(), "start menu shortcut survived the silent uninstall")
    _require((data_dir / "state.sqlite3").is_file(), "uninstall removed the preserved user data")

    shutil.rmtree(data_dir, ignore_errors=True)
    print("smoke install passed")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and verify the BelegDock Windows installer.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the onedir bundle and the setup executable")
    build.add_argument("--wheel", required=True, type=Path)
    build.add_argument("--dist", required=True, type=Path)
    build.set_defaults(handler=cmd_build)
    check = commands.add_parser("check-artifact", help="verify the built artifact offline")
    check.add_argument("--dist", required=True, type=Path)
    check.set_defaults(handler=cmd_check_artifact)
    smoke = commands.add_parser("smoke-install", help="install, probe and uninstall the artifact")
    smoke.add_argument("--dist", required=True, type=Path)
    smoke.set_defaults(handler=cmd_smoke_install)
    return parser


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
