import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from urllib.parse import quote
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DocumentRejected(RuntimeError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"Lexware rejected document (HTTP {status_code})")


class LocalIntegrityError(RuntimeError):
    pass


class TransferActiveError(RuntimeError):
    pass


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.blobs = self.data_dir / "blobs"
        self._held_locks: set[str] = set()
        state_path = self.data_dir / "state.sqlite3"
        if self.data_dir.exists():
            if not self.data_dir.is_dir():
                raise LocalIntegrityError("data path is not a directory; restore the complete data directory")
            entries = list(self.data_dir.iterdir())
            if entries and not state_path.exists():
                raise LocalIntegrityError("state database is missing; restore the complete data directory")
            if state_path.exists():
                try:
                    state_info = state_path.lstat()
                except OSError as error:
                    raise LocalIntegrityError("state database is unavailable; restore the complete data directory") from error
                if not stat.S_ISREG(state_info.st_mode) or state_info.st_size == 0:
                    raise LocalIntegrityError("state database is incomplete; restore the complete data directory")
                self._preflight_database(state_path)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    hash TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    id TEXT,
                    voucher_id TEXT,
                    rejection_status INTEGER
                    ,origin TEXT
                );
                CREATE TABLE IF NOT EXISTS occurrences (
                    hash TEXT NOT NULL REFERENCES documents(hash),
                    account TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    PRIMARY KEY (account, message_id, part_id)
                );
                CREATE TABLE IF NOT EXISTS remote_files (
                    id TEXT PRIMARY KEY,
                    voucher_id TEXT,
                    digest TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                    ,version TEXT
                    ,metadata_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS remote_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
            if "rejection_status" not in columns:
                connection.execute("ALTER TABLE documents ADD COLUMN rejection_status INTEGER")
            if "origin" not in columns:
                connection.execute("ALTER TABLE documents ADD COLUMN origin TEXT")
            remote_columns = {row[1] for row in connection.execute("PRAGMA table_info(remote_files)")}
            if "version" not in remote_columns:
                connection.execute("ALTER TABLE remote_files ADD COLUMN version TEXT")
            if "metadata_hash" not in remote_columns:
                connection.execute("ALTER TABLE remote_files ADD COLUMN metadata_hash TEXT NOT NULL DEFAULT ''")
            connection.commit()

    @staticmethod
    def _preflight_database(state_path: Path) -> None:
        database_uri = f"file:{quote(str(state_path), safe='/')}?mode=ro"
        try:
            connection = sqlite3.connect(database_uri, uri=True, timeout=1)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError) as error:
            raise LocalIntegrityError("state database is corrupt; restore the complete data directory") from error
        if "documents" not in tables:
            raise LocalIntegrityError("state database is incomplete; restore the complete data directory")

    def stage(
        self,
        account: str,
        message_id: str,
        part_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        if not isinstance(data, bytes):
            raise ValueError("document data must be bytes")
        if not str(filename).lower().endswith((".pdf", ".xml")):
            raise ValueError("only PDF/XML filename candidates are supported")
        if len(data) > 5_000_000:
            raise ValueError("document exceeds the 5,000,000 byte limit")
        digest = hashlib.sha256(data).hexdigest()
        target = self.blobs / digest
        if target.exists() or target.is_symlink():
            integrity = self._blob_integrity(digest, len(data))
            if integrity != "ok":
                raise LocalIntegrityError(f"existing staged document integrity check failed: blob is {integrity}")
        else:
            self._write_blob(target, data)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT hash FROM occurrences WHERE account=? AND message_id=? AND part_id=?",
                (account, message_id, part_id),
            ).fetchone()
            if existing is not None and existing[0] != digest:
                raise ValueError("source occurrence conflicts with different document bytes")
            connection.execute(
                "INSERT OR IGNORE INTO documents(hash, filename, size, status) VALUES (?, ?, ?, 'staged')",
                (digest, filename, len(data)),
            )
            connection.execute(
                "INSERT OR IGNORE INTO occurrences(hash, account, message_id, part_id, filename) VALUES (?, ?, ?, ?, ?)",
                (digest, account, message_id, part_id, filename),
            )
            connection.commit()
        return digest

    def list_documents(self, digest: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT hash, filename, size, status, id, voucher_id, rejection_status, origin "
            "FROM documents"
        )
        parameters: tuple[str, ...] = ()
        if digest is not None:
            self._validate_digest(digest)
            query += " WHERE hash=?"
            parameters = (digest,)
        query += " ORDER BY hash"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "hash": row[0],
                "filename": row[1],
                "size": row[2],
                "status": row[3],
                "id": row[4],
                "voucherId": row[5],
                "rejectionStatus": row[6],
                "origin": row[7],
                "localIntegrity": self._blob_integrity(row[0], row[2]),
            }
            for row in rows
        ]

    def occurrences(self, digest: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT account, message_id, part_id, filename FROM occurrences WHERE hash=? ORDER BY account, message_id, part_id",
                (digest,),
            ).fetchall()
        return [
            {
                "account": row[0],
                "message_id": row[1],
                "part_id": row[2],
                "filename": row[3],
            }
            for row in rows
        ]

    def upload(
        self,
        digest: str,
        uploader: Callable[[bytes, str], dict[str, str]],
        refresh: Callable[[], Any] | None = None,
        verify: Callable[[str, str], bytes] | None = None,
    ) -> dict[str, str]:
        self._validate_digest(digest)
        with self._upload_lock(digest) as acquired:
            if not acquired:
                raise TransferActiveError("upload outcome is uncertain; reconcile before retry")
            with self._connection() as connection:
                row = connection.execute("SELECT filename, status, id, voucher_id, rejection_status FROM documents WHERE hash=?", (digest,)).fetchone()
            if row is None:
                raise ValueError("unknown document hash")
            filename, status, file_id, voucher_id, rejection_status = row
            if status == "uploaded":
                self._read_staged(digest)
                return {"id": file_id, "voucherId": voucher_id}
            if status == "rejected":
                raise DocumentRejected(rejection_status or 400)
            if status in {"uploading", "uncertain"}:
                raise RuntimeError("upload outcome is uncertain; reconcile before retry")
            data = self._read_staged(digest)
            if refresh is not None:
                refresh()
                presence = self.remote_presence(digest)
                if presence["status"] == "already_present":
                    if verify is None:
                        raise RuntimeError("remote match requires current verification")
                    verified = verify(presence["id"], presence["voucherId"])
                    if not isinstance(verified, bytes) or hashlib.sha256(verified).hexdigest() != digest:
                        raise RuntimeError("remote document does not match staged bytes")
                    with self._connection() as connection:
                        connection.execute(
                            "UPDATE documents SET status='uploaded', id=?, voucher_id=?, rejection_status=NULL, origin='already_present' "
                            "WHERE hash=? AND status='staged'",
                            (presence["id"], presence.get("voucherId"), digest),
                        )
                        connection.commit()
                    return {
                        "id": presence["id"],
                        "voucherId": presence["voucherId"],
                        "status": "already_present",
                    }
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE documents SET status='uploading' WHERE hash=?", (digest,))
                connection.commit()
            try:
                result = uploader(data, filename)
                if not isinstance(result, dict) or not result.get("id") or not result.get("voucherId"):
                    raise ValueError("uploader result must contain id and voucherId")
            except DocumentRejected as error:
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE documents SET status='rejected', rejection_status=?, origin=NULL "
                        "WHERE hash=? AND status='uploading'",
                        (error.status_code, digest),
                    )
                    connection.commit()
                raise
            except Exception as error:
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE documents SET status='uncertain' WHERE hash=? AND status='uploading'",
                        (digest,),
                    )
                    connection.commit()
                if isinstance(error, ValueError):
                    raise
                raise RuntimeError("upload outcome is uncertain; reconcile before retry") from error
            with self._connection() as connection:
                connection.execute(
                    "UPDATE documents SET status='uploaded', id=?, voucher_id=?, rejection_status=NULL, origin=? "
                    "WHERE hash=? AND status='uploading'",
                    (result["id"], result["voucherId"], "unknown" if refresh is not None else None, digest),
                )
                connection.commit()
            if refresh is not None:
                return dict(result, status="accepted", origin="unknown")
            return result

    def refresh_remote(self, organization_id: str, files: list[dict[str, Any]]) -> None:
        if not isinstance(organization_id, str) or not organization_id:
            raise ValueError("organization is invalid")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT value FROM remote_state WHERE key='organization_id'"
            ).fetchone()
            if previous is not None and previous[0] != organization_id:
                raise RuntimeError("remote inventory organization does not match this state directory")
            validated: list[tuple[Any, ...]] = []
            seen: set[str] = set()
            for item in files:
                if not isinstance(item, dict):
                    raise ValueError("remote inventory entry is invalid")
                file_id, digest = item.get("id"), item.get("hash")
                if not isinstance(file_id, str) or not file_id or file_id in seen or not isinstance(digest, str):
                    raise ValueError("remote inventory entry is invalid")
                self._validate_digest(digest)
                if not isinstance(item.get("voucherId"), str) or not item["voucherId"]:
                    raise ValueError("remote inventory voucher reference is invalid")
                seen.add(file_id)
                metadata_hash = hashlib.sha256(json.dumps({key: value for key, value in item.items() if key != "hash"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                validated.append((file_id, item["voucherId"], digest, organization_id, bool(item.get("archived")), item.get("version"), metadata_hash))
            if len({row[2] for row in validated}) != len(validated):
                raise RuntimeError("remote inventory contains conflicting matches")
            connection.execute("DELETE FROM remote_files")
            connection.executemany(
                "INSERT INTO remote_files(id, voucher_id, digest, organization_id, archived, version, metadata_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                validated,
            )
            connection.execute(
                "INSERT OR REPLACE INTO remote_state(key, value) VALUES ('organization_id', ?)",
                (organization_id,),
            )
            connection.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refresh_status', 'success')")
            connection.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refreshed_at', ?)", (datetime.now(timezone.utc).isoformat(),))
            connection.commit()

    def record_refresh_failure(self, message: str) -> None:
        with self._connection() as connection:
            connection.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refresh_status', 'failed')")
            connection.execute("INSERT OR REPLACE INTO remote_state(key, value) VALUES ('refresh_failed_at', ?)", (datetime.now(timezone.utc).isoformat(),))
            connection.commit()

    def remote_presence(self, digest: str) -> dict[str, str]:
        self._validate_digest(digest)
        with self._connection() as connection:
            rows = connection.execute("SELECT id, voucher_id FROM remote_files WHERE digest=? ORDER BY id", (digest,)).fetchall()
        if len(rows) > 1:
            raise RuntimeError("remote inventory contains conflicting matches")
        row = rows[0] if rows else None
        if row is None:
            return {"status": "absent"}
        return {"status": "already_present", "id": row[0], "voucherId": row[1]}

    def cached_remote_hash(self, organization_id: str, item: dict[str, Any]) -> str | None:
        file_id = item.get("id")
        if not isinstance(file_id, str) or not file_id:
            return None
        metadata_hash = hashlib.sha256(json.dumps({key: value for key, value in item.items() if key != "hash"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._connection() as connection:
            row = connection.execute("SELECT digest FROM remote_files WHERE id=? AND organization_id=? AND metadata_hash=?", (file_id, organization_id, metadata_hash)).fetchone()
        return row[0] if row else None

    def remote_organization(self) -> str | None:
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM remote_state WHERE key='organization_id'").fetchone()
        return row[0] if row else None

    def associate_remote(self, digest: str, file_id: str, voucher_id: str, verifier: Callable[[str, str], bytes]) -> dict[str, str]:
        self._validate_digest(digest)
        with self._upload_lock(digest) as acquired:
            if not acquired:
                raise RuntimeError("association is active")
            with self._connection() as connection:
                row = connection.execute("SELECT status FROM documents WHERE hash=?", (digest,)).fetchone()
            if row is None:
                raise ValueError("unknown document hash")
            if row[0] != "staged":
                raise RuntimeError("document is not staged")
            self._read_staged(digest)
            remote = verifier(file_id, voucher_id)
            if not isinstance(remote, bytes) or hashlib.sha256(remote).hexdigest() != digest:
                raise RuntimeError("remote document does not match staged bytes")
            with self._connection() as connection:
                connection.execute("UPDATE documents SET status='uploaded', id=?, voucher_id=?, origin='already_present' WHERE hash=? AND status='staged'", (file_id, voucher_id, digest))
                connection.commit()
        return {"id": file_id, "voucherId": voucher_id, "status": "already_present"}

    def _read_staged(self, digest: str) -> bytes:
        with self._connection() as connection:
            row = connection.execute("SELECT size FROM documents WHERE hash=?", (digest,)).fetchone()
        if row is None:
            raise ValueError("unknown document hash")
        size = row[0]
        integrity = self._blob_integrity(digest, size)
        if integrity != "ok":
            raise LocalIntegrityError(f"staged document integrity check failed: blob is {integrity}")
        path = self.blobs / digest
        try:
            with path.open("rb") as handle:
                data = handle.read(size)
                if len(data) != size or handle.read(1):
                    raise LocalIntegrityError("staged document integrity check failed")
        except OSError as error:
            raise LocalIntegrityError("staged document integrity check failed: blob is unreadable") from error
        if hashlib.sha256(data).hexdigest() != digest:
            raise LocalIntegrityError("staged document integrity check failed: blob is corrupt")
        return data

    def _blob_integrity(self, digest: str, expected_size: int) -> str:
        try:
            self._validate_digest(digest)
        except ValueError:
            return "corrupt"
        path = self.blobs / digest
        try:
            info = path.lstat()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unreadable"
        if (
            not stat.S_ISREG(info.st_mode)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or expected_size > 5_000_000
        ):
            return "corrupt"
        if info.st_size != expected_size:
            return "corrupt"
        hasher = hashlib.sha256()
        remaining = expected_size
        try:
            with path.open("rb") as handle:
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        return "corrupt"
                    hasher.update(chunk)
                    remaining -= len(chunk)
                if handle.read(1):
                    return "corrupt"
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unreadable"
        return "ok" if hasher.hexdigest() == digest else "corrupt"

    def reconcile(
        self,
        digest: str,
        file_id: str,
        voucher_id: str,
        verifier: Callable[[str, str], bytes],
    ) -> dict[str, str]:
        self._validate_digest(digest)
        if not isinstance(file_id, str) or not file_id or not isinstance(voucher_id, str) or not voucher_id:
            raise ValueError("remote IDs are invalid")
        with self._upload_lock(digest) as acquired:
            if not acquired:
                raise TransferActiveError("reconciliation is active")
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT status FROM documents WHERE hash=?", (digest,)
                ).fetchone()
                if row is None:
                    raise ValueError("unknown document hash")
                if row[0] != "uncertain":
                    raise RuntimeError("only an uncertain upload can be reconciled")
            self._read_staged(digest)
            remote_data = verifier(file_id, voucher_id)
            if not isinstance(remote_data, bytes) or hashlib.sha256(remote_data).hexdigest() != digest:
                raise RuntimeError("remote document does not match staged bytes")
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE documents SET status='uploaded', id=?, voucher_id=?, rejection_status=NULL "
                    "WHERE hash=? AND status='uncertain'",
                    (file_id, voucher_id, digest),
                )
                connection.commit()
        return {"id": file_id, "voucherId": voucher_id}

    def recover_upload(self, digest: str) -> dict[str, str]:
        self._validate_digest(digest)
        with self._upload_lock(digest) as acquired:
            if not acquired:
                raise TransferActiveError("upload is active and cannot be recovered")
            with self._connection() as connection:
                row = connection.execute("SELECT status FROM documents WHERE hash=?", (digest,)).fetchone()
                if row is None:
                    raise ValueError("unknown document hash")
                if row[0] != "uploading":
                    raise RuntimeError("only an interrupted upload can be recovered")
            self._read_staged(digest)
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE documents SET status='uncertain' WHERE hash=? AND status='uploading'", (digest,)
                )
                connection.commit()
        return {"status": "uncertain"}

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.data_dir / "state.sqlite3", timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _upload_lock(self, digest: str) -> Iterator[bool]:
        self._validate_digest(digest)
        if digest in self._held_locks:
            yield False
            return
        path = self.data_dir / f".{digest}.upload.lock"
        with path.open("a+b") as handle:
            acquired = False
            try:
                if sys.platform == "win32":
                    self._windows_lock(handle, "LK_NBLCK")
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                self._held_locks.add(digest)
            except OSError:
                pass
            try:
                yield acquired
            finally:
                if acquired:
                    self._held_locks.discard(digest)
                    if sys.platform == "win32":
                        self._windows_lock(handle, "LK_UNLCK")
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("document hash is invalid")

    @staticmethod
    def _windows_lock(handle: Any, mode: str) -> None:
        handle.seek(0)
        msvcrt = __import__("msvcrt")
        msvcrt.locking(handle.fileno(), getattr(msvcrt, mode), 1)

    def _write_blob(self, target: Path, data: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.blobs, prefix=f".{target.name}.", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            if sys.platform != "win32":
                directory = os.open(self.blobs, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except Exception:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
