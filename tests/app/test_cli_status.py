from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from unittest.mock import patch

from belegdock import cli
from belegdock.workflow import Store


def invoke_cli(*arguments):
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        exit_code = cli.main(list(arguments))
    return exit_code, output.getvalue(), error.getvalue()


def test_status_uninitialized_directory_reports_empty_and_does_not_create_files(tmp_path):
    target = tmp_path / "nonexistent"
    exit_code, output, error = invoke_cli("--data-dir", str(target), "status")

    assert exit_code == 0
    assert error == ""
    assert not target.exists()
    assert "0" in output
    assert "datenverzeichnis" in output.lower()


def test_status_human_readable_output_with_various_document_states(tmp_path):
    store = Store(tmp_path)
    # Stage sample files
    store.stage("acc", "m1", "p1", "doc1.pdf", b"bytes1")
    d_uploading = store.stage("acc", "m2", "p2", "doc2.pdf", b"bytes2")
    d_uncertain = store.stage("acc", "m3", "p3", "doc3.pdf", b"bytes3")
    d_uploaded = store.stage("acc", "m4", "p4", "doc4.pdf", b"bytes4")
    d_rejected = store.stage("acc", "m5", "p5", "doc5.pdf", b"bytes5")

    with store._connection() as conn:
        conn.execute("UPDATE documents SET status='uploading' WHERE hash=?", (d_uploading,))
        conn.execute("UPDATE documents SET status='uncertain' WHERE hash=?", (d_uncertain,))
        conn.execute("UPDATE documents SET status='uploaded', id='fid-1', voucher_id='vid-1' WHERE hash=?", (d_uploaded,))
        conn.execute("UPDATE documents SET status='rejected', rejection_status=406 WHERE hash=?", (d_rejected,))
        conn.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refresh_status', 'success')")
        conn.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refreshed_at', '2026-09-26T12:00:00+00:00')")
        conn.commit()

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 0
    assert error == ""
    assert str(tmp_path) in output
    assert "5" in output  # Total
    assert "Vorbereitet" in output or "staged" in output
    assert "Wird gesendet" in output or "uploading" in output
    assert "Unklar" in output or "uncertain" in output
    assert "Gesendet" in output or "uploaded" in output
    assert "Abgelehnt" in output or "rejected" in output
    assert "2026-09-26" in output


def test_status_recommends_next_commands_for_actionable_documents(tmp_path):
    store = Store(tmp_path)
    d_staged = store.stage("acc", "m1", "p1", "doc1.pdf", b"bytes1")
    d_uploading = store.stage("acc", "m2", "p2", "doc2.pdf", b"bytes2")
    d_uncertain = store.stage("acc", "m3", "p3", "doc3.pdf", b"bytes3")

    with store._connection() as conn:
        conn.execute("UPDATE documents SET status='uploading' WHERE hash=?", (d_uploading,))
        conn.execute("UPDATE documents SET status='uncertain' WHERE hash=?", (d_uncertain,))
        conn.commit()

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 0
    assert error == ""
    assert f"belegdock upload {d_staged}" in output
    assert f"belegdock recover-upload {d_uploading}" in output
    assert f"belegdock reconcile {d_uncertain} --file-id FILE_ID --voucher-id VOUCHER_ID" in output


def test_status_caps_actionable_commands_at_five_per_status(tmp_path):
    store = Store(tmp_path)
    hashes = []
    for i in range(7):
        hashes.append(store.stage("acc", f"m{i}", f"p{i}", f"doc{i}.pdf", f"content{i}".encode()))

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 0
    assert error == ""
    # Should contain 5 upload commands
    upload_count = sum(1 for line in output.splitlines() if "belegdock upload " in line)
    assert upload_count == 5
    # Should mention the remaining 2 documents
    assert "2 weitere" in output


def test_status_json_output_contract(tmp_path):
    store = Store(tmp_path)
    d_staged = store.stage("acc", "m1", "p1", "doc1.pdf", b"bytes1")
    with store._connection() as conn:
        conn.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refresh_status', 'success')")
        conn.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refreshed_at', '2026-09-26T12:00:00+00:00')")
        conn.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('organization_id', 'org-123')")
        conn.commit()

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status", "--json")

    assert exit_code == 0
    assert error == ""
    data = json.loads(output)
    assert data["dataDir"] == str(tmp_path)
    assert data["totalDocuments"] == 1
    assert data["counts"]["staged"] == 1
    assert data["counts"]["uploading"] == 0
    assert data["counts"]["uncertain"] == 0
    assert data["counts"]["uploaded"] == 0
    assert data["counts"]["rejected"] == 0
    assert data["integrityIssues"] == 0
    assert data["remoteRefresh"]["status"] == "success"
    assert data["remoteRefresh"]["refreshedAt"] == "2026-09-26T12:00:00+00:00"
    assert data["remoteRefresh"]["organizationId"] == "org-123"
    assert len(data["nextActions"]) == 1
    assert data["nextActions"][0]["hash"] == d_staged
    assert data["nextActions"][0]["status"] == "staged"
    assert data["nextActions"][0]["command"] == f"belegdock upload {d_staged}"


def test_status_reports_damaged_blobs_and_exits_zero(tmp_path):
    store = Store(tmp_path)
    digest = store.stage("acc", "m1", "p1", "doc1.pdf", b"goodbytes")
    # Corrupt the blob file
    (tmp_path / "blobs" / digest).write_bytes(b"corrupted")

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 0
    assert error == ""
    assert "1" in output  # 1 damaged document
    assert "README.md" in output


def test_status_corrupt_database_exits_one_with_restore_guidance(tmp_path):
    database = tmp_path / "state.sqlite3"
    database.write_bytes(b"corrupt sqlite header")

    exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 1
    assert "wiederher" in error.lower()
    assert "Traceback" not in error


def test_status_makes_no_network_requests(tmp_path):
    store = Store(tmp_path)
    store.stage("acc", "m1", "p1", "doc1.pdf", b"bytes1")

    with patch("socket.socket", side_effect=AssertionError("network accessed")):
        exit_code, output, error = invoke_cli("--data-dir", str(tmp_path), "status")

    assert exit_code == 0
    assert error == ""
