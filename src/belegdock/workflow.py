from collections.abc import Callable
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterator


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.blobs = self.data_dir / "blobs"
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
                    voucher_id TEXT
                );
                CREATE TABLE IF NOT EXISTS occurrences (
                    hash TEXT NOT NULL REFERENCES documents(hash),
                    account TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    PRIMARY KEY (account, message_id, part_id)
                );
                """
            )
            connection.commit()

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
        if target.exists():
            try:
                existing_data = target.read_bytes()
            except OSError as error:
                raise RuntimeError("existing staged document is unavailable") from error
            if hashlib.sha256(existing_data).hexdigest() != digest:
                raise RuntimeError("existing staged document integrity check failed")
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

    def list_documents(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT hash, filename, size, status, id, voucher_id FROM documents ORDER BY hash"
            ).fetchall()
        return [
            {
                "hash": row[0],
                "filename": row[1],
                "size": row[2],
                "status": row[3],
                "id": row[4],
                "voucherId": row[5],
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

    def upload(self, digest: str, uploader: Callable[[bytes, str], dict[str, str]]) -> dict[str, str]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT filename, status, id, voucher_id FROM documents WHERE hash=?",
                (digest,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown document hash")
            filename, status, file_id, voucher_id = row
            if status == "uploaded":
                return {"id": file_id, "voucherId": voucher_id}
            if status in {"uploading", "uncertain"}:
                raise RuntimeError("upload outcome is uncertain; reconcile before retry")
            path = self.blobs / digest
            try:
                data = path.read_bytes()
            except OSError as error:
                raise RuntimeError("staged document is unavailable") from error
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("staged document integrity check failed")
            connection.execute("UPDATE documents SET status='uploading' WHERE hash=?", (digest,))
            connection.commit()
        try:
            result = uploader(data, filename)
            if not isinstance(result, dict) or not result.get("id") or not result.get("voucherId"):
                raise ValueError("uploader result must contain id and voucherId")
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
                "UPDATE documents SET status='uploaded', id=?, voucher_id=? WHERE hash=? AND status='uploading'",
                (result["id"], result["voucherId"], digest),
            )
            connection.commit()
        return result

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.data_dir / "state.sqlite3", timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

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
