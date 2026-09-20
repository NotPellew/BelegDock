from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import stat
from types import SimpleNamespace

import pytest

from belegdock import cli
from belegdock.workflow import Store


@pytest.mark.parametrize("kind", ["oversized", "directory", "symlink"])
def test_listing_rejects_unsafe_blob_before_opening(tmp_path, kind):
    store = Store(tmp_path)
    digest = store.stage("account", "message", "part", "receipt.pdf", b"receipt")
    blob = tmp_path / "blobs" / digest
    if kind == "oversized":
        with blob.open("wb") as handle:
            handle.truncate(5_000_001)
    elif kind == "directory":
        blob.unlink()
        blob.mkdir()
    original_lstat = Path.lstat
    original_open = Path.open
    reads = []
    def metadata(path, *args, **kwargs):
        if path == blob and kind == "symlink":
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_size=7)
        return original_lstat(path, *args, **kwargs)
    def opened(path, *args, **kwargs):
        if path == blob:
            reads.append(True)
        return original_open(path, *args, **kwargs)
    with patch.object(Path, "lstat", metadata), patch.object(Path, "open", opened):
        documents = store.list_documents()
    assert documents[0].get("localIntegrity") == "corrupt"
    assert reads == []


@pytest.mark.parametrize("kind", ["directory", "garbage"])
def test_unusable_database_cli_gives_restore_guidance_without_creating_blobs(tmp_path, kind):
    database = tmp_path / "state.sqlite3"
    if kind == "directory":
        database.mkdir()
    else:
        database.write_bytes(b"not a database; private bytes")
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        result = cli.main(["--data-dir", str(tmp_path), "documents"])
    assert result != 0
    assert "restore" in error.getvalue().lower()
    assert "private bytes" not in output.getvalue() + error.getvalue()
    assert not (tmp_path / "blobs").exists()
