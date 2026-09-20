from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import Mock, patch

import pytest

from belegdock import cli
from belegdock.workflow import Store


def invoke(root, *args):
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        result = cli.main(["--data-dir", str(root), *args])
    return result, output.getvalue(), error.getvalue()


def staged(root):
    store = Store(root)
    digest = store.stage("synthetic", "message", "1", "invoice.pdf", b"synthetic invoice")
    return store, digest


@pytest.mark.parametrize("existing", [False, True])
def test_fresh_directory_still_initializes(tmp_path, existing):
    root = tmp_path / "fresh"
    if existing:
        root.mkdir()
    assert Store(root).list_documents() == []
    assert (root / "state.sqlite3").is_file()


@pytest.mark.parametrize("artifact", ["blobs", "blob", "lock", "journal"])
def test_missing_database_in_used_directory_is_rejected_without_writes(tmp_path, artifact):
    root = tmp_path / "partial"
    root.mkdir()
    if artifact in {"blobs", "blob"}:
        (root / "blobs").mkdir()
        if artifact == "blob":
            (root / "blobs" / hashlib.sha256(b"saved").hexdigest()).write_bytes(b"saved")
    else:
        (root / (".document.upload.lock" if artifact == "lock" else "state.sqlite3-journal")).write_bytes(b"saved")
    before = {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}
    with pytest.raises(RuntimeError, match="(?i)database|restore|incomplete"):
        Store(root)
    assert not (root / "state.sqlite3").exists()
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def test_zero_length_database_is_not_initialized_as_a_restore(tmp_path):
    database = tmp_path / "state.sqlite3"
    database.touch()
    with pytest.raises(RuntimeError, match="(?i)database|restore|incomplete"):
        Store(tmp_path)
    assert database.read_bytes() == b""
    assert not (tmp_path / "blobs").exists()


def test_cli_missing_database_reports_restore_guidance_without_empty_success(tmp_path):
    (tmp_path / "blobs").mkdir()
    status, output, error = invoke(tmp_path, "documents")
    assert status != 0
    assert not output.strip()
    assert "restore" in error.lower()
    assert not (tmp_path / "state.sqlite3").exists()


@pytest.mark.parametrize("state", ["staged", "uploaded", "rejected", "uncertain", "uploading"])
def test_complete_restore_reports_integrity_without_changing_remote_state(tmp_path, state):
    root = tmp_path / "source"
    store, digest = staged(root)
    store.stage("synthetic", "duplicate", "2", "copy.pdf", b"synthetic invoice")
    with sqlite3.connect(root / "state.sqlite3") as db:
        db.execute("UPDATE documents SET status=?, id='file', voucher_id='voucher' WHERE hash=?", (state, digest))
    restored = tmp_path / "restored"
    shutil.copytree(root, restored)
    result = Store(restored).list_documents()[0]
    assert result.get("localIntegrity") == "ok"
    assert (result["status"], result["id"], result["voucherId"]) == (state, "file", "voucher")
    assert len(Store(restored).occurrences(digest)) == 2
    status, output, error = invoke(restored, "documents")
    assert status == 0, error
    assert json.loads(output)[0]["localIntegrity"] == "ok"


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_uploaded_missing_or_corrupt_blob_is_flagged_without_rewriting_status(tmp_path, damage):
    store, digest = staged(tmp_path)
    store.upload(digest, lambda data, name: {"id": "file", "voucherId": "voucher"})
    blob = tmp_path / "blobs" / digest
    if damage == "missing":
        blob.unlink()
    else:
        blob.write_bytes(b"private corrupt contents")
    result = store.list_documents()[0]
    assert result.get("localIntegrity") == damage
    assert (result["status"], result["id"], result["voucherId"]) == ("uploaded", "file", "voucher")
    status, output, error = invoke(tmp_path, "documents")
    assert status != 0
    assert json.loads(output)[0]["localIntegrity"] == damage
    assert "restore" in error.lower()
    assert "private corrupt contents" not in output + error


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_uploaded_fast_path_does_not_hide_local_loss_or_contact_remote(tmp_path, damage):
    store, digest = staged(tmp_path)
    store.upload(digest, lambda data, name: {"id": "file", "voucherId": "voucher"})
    blob = tmp_path / "blobs" / digest
    if damage == "missing":
        blob.unlink()
    else:
        blob.write_bytes(b"broken")
    upload, refresh, verify = Mock(), Mock(), Mock()
    with pytest.raises(RuntimeError, match="(?i)integrity|unavailable|restore|missing|corrupt"):
        store.upload(digest, upload, refresh, verify)
    upload.assert_not_called()
    refresh.assert_not_called()
    verify.assert_not_called()
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        assert db.execute("SELECT status,id,voucher_id FROM documents WHERE hash=?", (digest,)).fetchone() == ("uploaded", "file", "voucher")


def test_unreadable_blob_is_reported_without_leaking_os_error(tmp_path):
    store, digest = staged(tmp_path)
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == tmp_path / "blobs" / digest:
            raise PermissionError("sensitive filesystem detail")
        return original(path, *args, **kwargs)
    with patch.object(Path, "open", denied):
        status, output, error = invoke(tmp_path, "documents")
    assert status != 0
    assert json.loads(output)[0].get("localIntegrity") == "unreadable"
    assert "sensitive filesystem detail" not in output + error


def test_legacy_database_without_newer_columns_remains_readable(tmp_path):
    store, digest = staged(tmp_path)
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute("ALTER TABLE documents DROP COLUMN origin")
        db.execute("ALTER TABLE documents DROP COLUMN rejection_status")
        db.execute("DROP TABLE remote_files")
        db.execute("DROP TABLE remote_state")
    reopened = Store(tmp_path)
    assert reopened.list_documents()[0]["hash"] == digest
    assert reopened.occurrences(digest)[0]["message_id"] == "message"
