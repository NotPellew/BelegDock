from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from belegdock.workflow import Store


@pytest.mark.parametrize("operation", ["stage", "reconcile"])
@pytest.mark.parametrize("damage", ["symlink", "oversized", "directory"])
def test_restore_reuse_rejects_unsafe_blob_before_read_or_remote(tmp_path, operation, damage):
    store = Store(tmp_path)
    payload = b"synthetic receipt"
    digest = store.stage("account", "message", "part", "receipt.pdf", payload)
    if operation == "reconcile":
        with sqlite3.connect(tmp_path / "state.sqlite3") as connection:
            connection.execute("UPDATE documents SET status='uncertain' WHERE hash=?", (digest,))
    blob = tmp_path / "blobs" / digest
    if damage == "oversized":
        with blob.open("wb") as handle:
            handle.truncate(5_000_001)
    elif damage == "directory":
        blob.unlink()
        blob.mkdir()
    original_lstat, original_open = Path.lstat, Path.open
    reads = []
    def metadata(path, *args, **kwargs):
        if path == blob and damage == "symlink":
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_size=len(payload))
        return original_lstat(path, *args, **kwargs)
    def opened(path, *args, **kwargs):
        if path == blob:
            reads.append(True)
        return original_open(path, *args, **kwargs)
    remote = Mock(return_value=payload)
    with patch.object(Path, "lstat", metadata), patch.object(Path, "open", opened):
        with pytest.raises(RuntimeError):
            if operation == "stage":
                store.stage("account", "second-message", "part", "receipt.pdf", payload)
            else:
                store.reconcile(digest, "file", "voucher", remote)
    assert reads == []
    remote.assert_not_called()
    assert len(store.occurrences(digest)) == 1
    with sqlite3.connect(tmp_path / "state.sqlite3") as connection:
        assert connection.execute("SELECT status FROM documents WHERE hash=?", (digest,)).fetchone()[0] == ("uncertain" if operation == "reconcile" else "staged")
