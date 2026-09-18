import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys


def validate_tree(root: Path, writable: list[Path]) -> None:
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names + files:
            path = Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"Checkout symlinks are not supported: {path.relative_to(root)}")
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                raise ValueError(f"Special file is not allowed: {path.relative_to(root)}")
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
                if any(path == area or path.is_relative_to(area) for area in writable):
                    raise ValueError(f"Unsafe hardlink in writable content: {path.relative_to(root)}")


def sandbox_command(
    bubblewrap: str, root: Path, writable: list[Path], command: list[str], network: bool
) -> list[str]:
    arguments = [
        bubblewrap,
        "--unshare-all", "--unshare-user", "--disable-userns",
        "--cap-drop", "ALL", "--die-with-parent", "--new-session", "--clearenv",
    ]
    if network:
        arguments.append("--share-net")
    for name in ("/usr", "/bin", "/lib", "/lib64"):
        path = Path(name)
        if path.is_symlink():
            arguments.extend(("--symlink", os.readlink(path), name))
        elif path.is_dir():
            arguments.extend(("--ro-bind", name, name))
    for name in (
        "/etc/ld.so.cache", "/etc/passwd", "/etc/group",
        "/etc/nsswitch.conf", "/etc/ssl", "/etc/resolv.conf",
    ):
        path = Path(name)
        if path.exists():
            arguments.extend(("--ro-bind", str(path.resolve()), name))
    arguments.extend((
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--dir", "/home", "--tmpfs", "/home/agent",
        "--ro-bind", str(root), "/workspace",
    ))
    for path in writable:
        arguments.extend(("--bind", str(path), f"/workspace/{path.relative_to(root)}"))
    arguments.extend((
        "--remount-ro", "/",
        "--chdir", "/workspace",
        "--setenv", "HOME", "/home/agent",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TERM", os.environ.get("TERM", "xterm"),
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--",
        *command,
    ))
    return arguments


def main() -> int:
    if sys.platform != "linux":
        print("Protected sessions require Linux; this platform has no verified boundary.", file=sys.stderr)
        return 2
    import shutil

    parser = argparse.ArgumentParser(
        description="Run a separate CLI with tests and verification inputs read-only."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Checkout to expose as /workspace")
    parser.add_argument(
        "--network", action="store_true",
        help="Opt in to host networking; host TCP services become reachable",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --, for example -- bash")
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        parser.error("Bubblewrap (bwrap) is required; refusing to run without isolation")
    try:
        root = arguments.repo.resolve(strict=True)
        if not root.is_dir() or root == Path("/"):
            raise ValueError("--repo must name a checkout directory, not the filesystem root")
        writable = [root / "src", root / "docs"]
        for path in writable:
            if path.is_symlink():
                raise ValueError(f"Writable directory must not be a symlink: {path.name}")
            path.mkdir(exist_ok=True)
        readme = root / "README.md"
        if readme.exists() or readme.is_symlink():
            if readme.is_symlink() or not readme.is_file():
                raise ValueError("README.md must be a regular file, not a symlink")
            writable.append(readme)
        validate_tree(root, writable)
        executable = shutil.which(command[0])
        if executable:
            command[0] = executable
        result = subprocess.run(
            sandbox_command(bubblewrap, root, writable, command, arguments.network),
            close_fds=True,
        )
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Protected session refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
