from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from pathlib import PurePath
from threading import Lock
from typing import Any

from .service import refresh_remote_inventory
from .workflow import DocumentRejected, Store


LOCAL_RESTORE_GUIDANCE = (
    "Local document integrity failed; restore state.sqlite3 and blobs from a consistent backup."
)


class DesktopUnavailableError(RuntimeError):
    pass


class DesktopService:
    def __init__(self, store: Store, account: str, gmail: Any, remote: Any):
        self.store = store
        self.account = account
        self.gmail = gmail
        self.remote = remote
        self._flight = Lock()

    def labels(self) -> list[str]:
        labels = self.gmail.labels()
        return [label for label in labels if isinstance(label, str)]

    def candidates(self, label: str) -> list[dict[str, Any]]:
        return [
            {"id": candidate["id"], "filename": candidate["filename"], "size": candidate["size"]}
            for candidate in self.gmail.candidates(label)
        ]

    def stage(self, label: str, selected_ids: Sequence[str]) -> list[str]:
        with self._operation():
            candidates = self.gmail.candidates(label)
            selected = set(selected_ids)
            known = {candidate["id"] for candidate in candidates}
            if not selected or not selected.issubset(known):
                raise ValueError("select one or more displayed documents")
            return [
                self.store.stage(
                    self.account,
                    candidate["message_id"],
                    candidate["part_id"],
                    candidate["filename"],
                    self.gmail.fetch(candidate),
                )
                for candidate in candidates
                if candidate["id"] in selected
            ]

    def documents(self) -> list[dict[str, Any]]:
        return self.store.list_documents()

    def upload(self, digest: str) -> dict[str, str]:
        with self._operation():
            verify = getattr(self.remote, "verify_existing", None)
            return self.store.upload(
                digest,
                self.remote.upload,
                lambda: refresh_remote_inventory(self.store, self.remote),
                verify=verify if callable(verify) else None,
            )

    def close(self) -> None:
        client = getattr(self.remote, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if not self._flight.acquire(blocking=False):
            raise RuntimeError("another desktop operation is already running")
        try:
            yield
        finally:
            self._flight.release()


def _safe_error(operation: str, error: Exception) -> str:
    del error
    return {
        "labels": "Could not load Gmail labels; check the account connection.",
        "candidates": "Could not load attachments; check the label and account connection.",
        "stage": "Staging failed; check the selection, connection, and local storage.",
        "upload": "Upload failed; inspect Documents. Uncertain outcomes require CLI recovery.",
        "rejected": "Lexware rejected the document; correct the document and stage new bytes.",
    }.get(operation, "Operation failed; check the account connection and local storage.")


def _safe_filename(value: Any) -> str:
    name = PurePath(str(value).replace("\\", "/")).name
    cleaned = "".join(character if character.isprintable() else "_" for character in name)
    return cleaned[:120] or "(unnamed document)"


class DesktopApplication:
    def __init__(self, service: DesktopService, tk: Any, ttk: Any, messagebox: Any):
        self.service = service
        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("BelegDock")
        self.label = tk.StringVar()
        self.notice = tk.StringVar(value="Select a Gmail label.")
        self._candidate_ids: dict[str, str] = {}
        self._document_hashes: dict[str, str] = {}
        self._build()
        self._load_labels()
        self._load_documents()

    def _build(self) -> None:
        frame = self.ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.ttk.Label(frame, text="Gmail label").grid(row=0, column=0, sticky="w")
        self.label_box = self.ttk.Combobox(frame, textvariable=self.label, state="readonly")
        self.label_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.label_box.bind("<<ComboboxSelected>>", self._label_changed)
        self.candidates_view = self.ttk.Treeview(
            frame, columns=("filename", "size"), show="headings", selectmode="extended", height=8
        )
        self.candidates_view.heading("filename", text="Filename")
        self.candidates_view.heading("size", text="Size")
        self.candidates_view.column("filename", width=320, anchor="w")
        self.candidates_view.column("size", width=100, anchor="e")
        self.candidates_view.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 5))
        self.stage_button = self.ttk.Button(frame, text="Stage selected", command=self._stage)
        self.stage_button.grid(row=2, column=0, sticky="w")
        self.documents_view = self.ttk.Treeview(
            frame,
            columns=("filename", "size", "status", "file_id", "voucher_id"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        headings = {
            "filename": "Filename",
            "size": "Size",
            "status": "State",
            "file_id": "Lexware file ID",
            "voucher_id": "Lexware voucher ID",
        }
        for column, heading in headings.items():
            self.documents_view.heading(column, text=heading)
        self.documents_view.column("filename", width=220, anchor="w")
        self.documents_view.column("size", width=80, anchor="e")
        self.documents_view.column("status", width=110, anchor="w")
        self.documents_view.column("file_id", width=160, anchor="w")
        self.documents_view.column("voucher_id", width=160, anchor="w")
        self.documents_view.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(12, 5))
        self.upload_button = self.ttk.Button(frame, text="Upload selected", command=self._upload)
        self.upload_button.grid(row=4, column=0, sticky="w")
        self.ttk.Label(frame, textvariable=self.notice, wraplength=650).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

    def run(self) -> None:
        self.root.mainloop()

    def _load_labels(self) -> None:
        try:
            labels = self.service.labels()
        except Exception as error:
            self.notice.set(_safe_error("labels", error))
            return
        self.label_box["values"] = labels
        if labels:
            self.label.set(labels[0])
            self._load_candidates()

    def _label_changed(self, _event: Any = None) -> None:
        self._load_candidates()

    def _load_candidates(self) -> None:
        for row in self.candidates_view.get_children():
            self.candidates_view.delete(row)
        self._candidate_ids.clear()
        if not self.label.get():
            return
        try:
            candidates = self.service.candidates(self.label.get())
        except Exception as error:
            self.notice.set(_safe_error("candidates", error))
            return
        for candidate in candidates:
            row = self.candidates_view.insert("", "end", values=(candidate["filename"], candidate["size"]))
            self._candidate_ids[row] = candidate["id"]
        self.notice.set("Select one or more attachments, then choose Stage selected.")

    def _stage(self) -> None:
        selected_rows = self.candidates_view.selection()
        selected_ids = [self._candidate_ids[row] for row in selected_rows]
        try:
            self.service.stage(self.label.get(), selected_ids)
        except Exception as error:
            self.notice.set(_safe_error("stage", error))
            return
        self.notice.set("Selected attachments staged locally.")
        self._load_documents()

    def _load_documents(self) -> None:
        for row in self.documents_view.get_children():
            self.documents_view.delete(row)
        self._document_hashes.clear()
        self._document_integrity: dict[str, str | None] = {}
        try:
            documents = self.service.documents()
        except Exception as error:
            self.notice.set(_safe_error("documents", error))
            return
        restore_required = False
        for document in documents:
            integrity = document.get("localIntegrity")
            display_status = document["status"]
            if display_status == "uploaded" and document.get("origin") == "already_present":
                display_status = "already present in Lexware"
            if integrity != "ok":
                display_status = "restore required"
                restore_required = True
            row = self.documents_view.insert(
                "",
                "end",
                values=(
                    document["filename"],
                    document["size"],
                    display_status,
                    document.get("id") or "",
                    document.get("voucherId") or "",
                ),
            )
            self._document_hashes[row] = document["hash"]
            self._document_integrity[row] = integrity
        if restore_required:
            self.notice.set(LOCAL_RESTORE_GUIDANCE)

    def _upload(self) -> None:
        rows = self.documents_view.selection()
        if len(rows) != 1:
            self.notice.set("Select one staged document to upload.")
            return
        row = rows[0]
        values = self.documents_view.item(row, "values")
        if getattr(self, "_document_integrity", {}).get(row, "ok") != "ok":
            self.notice.set(LOCAL_RESTORE_GUIDANCE)
            return
        status = values[2]
        if status in {"uncertain", "uploading"}:
            self.notice.set("Outcome is uncertain; use the CLI recovery and reconciliation commands.")
            return
        if status != "staged":
            self.notice.set("Only staged documents can be uploaded.")
            return
        filename = _safe_filename(values[0])
        size = values[1] if isinstance(values[1], int) else str(values[1])
        if not self.messagebox.askyesno(
            "Confirm upload", f"Upload {filename} ({size} bytes) to Lexware?"
        ):
            return
        try:
            result = self.service.upload(self._document_hashes[row])
        except DocumentRejected as error:
            self.notice.set(_safe_error("rejected", error))
            self._load_documents()
            return
        except Exception as error:
            self.notice.set(_safe_error("upload", error))
            self._load_documents()
            return
        if result.get("status") == "already_present":
            self.notice.set(
                f"Already present in Lexware; no upload was sent. Lexware file {result['id']} "
                f"and voucher {result['voucherId']}."
            )
        else:
            self.notice.set(f"Uploaded; Lexware file {result['id']} and voucher {result['voucherId']}.")
        self._load_documents()


def run_desktop(data_dir: Path | None) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ModuleNotFoundError as error:
        if error.name == "tkinter":
            raise DesktopUnavailableError(
                "Desktop UI is unavailable; install Python Tk support and run 'belegdock desktop' again."
            ) from error
        raise
    from . import cli

    store = Store(data_dir or cli.default_data_dir())
    account, gmail = cli.gmail_client()
    remote = cli.lexware_client()
    application = DesktopApplication(DesktopService(store, account, gmail, remote), tk, ttk, messagebox)
    try:
        application.run()
    finally:
        application.service.close()
