from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import gettext
from pathlib import Path
from pathlib import PurePath
from threading import Lock
from typing import Any

from .service import refresh_remote_inventory
from .workflow import DocumentRejected, Store


_ = gettext.gettext

PREPARE_HELPER = _(
    "This saves selected files locally and sends nothing to Lexware."
)
DOCUMENT_TABLE_COLUMNS = ("filename", "size", "status")
DESKTOP_LAYOUT_BREAKPOINT = 1050
INITIAL_WINDOW_GEOMETRY = "1488x1060"
MIN_WINDOW_SIZE = (760, 720)
LOCAL_RESTORE_GUIDANCE = _(
    "Local document integrity failed; restore state.sqlite3 and blobs from a consistent backup."
)


def format_size(value: Any) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        return _("Unknown size")
    units = (_("bytes"), _("KiB"), _("MiB"), _("GiB"), _("TiB"))
    if size < 1024:
        return _("%(size)d %(unit)s") % {"size": size, "unit": units[0]}
    amount = float(size)
    unit = 0
    while amount >= 1024 and unit < len(units) - 1:
        amount /= 1024
        unit += 1
    return _("%(size).1f %(unit)s") % {"size": amount, "unit": units[unit]}


_STATUS_LABELS = {
    "staged": _("Staged"),
    "uploaded": _("Uploaded"),
    "already_present": _("Already present in Lexware"),
    "uncertain": _("Uncertain"),
    "uploading": _("Uploading"),
    "rejected": _("Rejected"),
}


def status_label(status_code: str) -> str:
    return _STATUS_LABELS.get(status_code, _("Unknown"))


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
        "labels": _("Could not load Gmail labels; check the account connection."),
        "candidates": _("Could not load attachments; check the label and account connection."),
        "stage": _("Staging failed; check the selection, connection, and local storage."),
        "documents": _("Could not load Documents; check local storage."),
        "upload": _("Upload failed; inspect Documents. Uncertain outcomes require CLI recovery."),
        "rejected": _("Lexware rejected the document; correct the document and stage new bytes."),
    }.get(operation, _("Operation failed; check the account connection and local storage."))


def document_action_state(
    status_code: str, integrity: str | None, origin: str | None = None
) -> tuple[bool, str, str]:
    if integrity != "ok":
        return False, _("Restore required"), LOCAL_RESTORE_GUIDANCE
    if origin == "already_present":
        return False, _("Already present in Lexware"), _("No upload needed.")
    if status_code == "uploaded":
        return False, status_label(status_code), _("This document was already sent to Lexware.")
    if status_code == "rejected":
        return False, status_label(status_code), _safe_error("rejected", RuntimeError())
    if status_code in {"uncertain", "uploading"}:
        return False, status_label(status_code), _(
            "Outcome is uncertain; use the CLI recovery and reconciliation commands."
        )
    if status_code == "staged":
        return True, _("Ready to send."), ""
    return False, status_label(status_code), _("Only staged documents can be sent.")


def _safe_filename(value: Any) -> str:
    name = PurePath(str(value).replace("\\", "/")).name
    cleaned = "".join(character if character.isprintable() else "_" for character in name)
    return cleaned[:120] or _("(unnamed document)")


class DesktopApplication:
    def __init__(self, service: DesktopService, tk: Any, ttk: Any, messagebox: Any):
        self.service = service
        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title(_("BelegDock"))
        self.label = tk.StringVar()
        self.notice = tk.StringVar(value=_("Select a Gmail label."))
        self._candidate_ids: dict[str, str] = {}
        self._document_hashes: dict[str, str] = {}
        self._document_status: dict[str, str] = {}
        self._document_details: dict[str, dict[str, str]] = {}
        self._build()
        self._load_labels()
        self._load_documents()

    def _build(self) -> None:
        self._configure_window()
        self._configure_style()
        frame = self.ttk.Frame(self.root, padding=32, style="Main.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        header = self.ttk.Frame(frame, style="Main.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 24))
        self.ttk.Label(header, text=_("BelegDock"), style="AppTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.ttk.Separator(header, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=(16, 0)
        )
        header.columnconfigure(0, weight=1)

        self.sections = self.ttk.Frame(frame, style="Main.TFrame")
        self.sections.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        self.choose_section = self.ttk.Frame(self.sections, style="Main.TFrame")
        self.review_section = self.ttk.Frame(self.sections, style="Main.TFrame")

        self.ttk.Label(
            self.choose_section, text=_("Choose documents"), style="SectionTitle.TLabel"
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.ttk.Label(self.choose_section, text=_("Gmail label"), style="Field.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(20, 4)
        )
        self.label_box = self.ttk.Combobox(
            self.choose_section,
            textvariable=self.label,
            state="readonly",
            style="Gmail.TCombobox",
            width=28,
        )
        self.label_box.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.label_box.bind("<<ComboboxSelected>>", self._label_changed)
        self.candidates_view = self._build_tree(
            self.choose_section,
            row=3,
            columns=("filename", "size"),
            headings={"filename": _("Filename"), "size": _("Size")},
            selectmode="extended",
        )
        self.candidates_view.bind("<Return>", lambda _event: self._stage())
        self.stage_button = self.ttk.Button(
            self.choose_section,
            text=_("Prepare selected documents"),
            command=self._stage,
            style="Primary.TButton",
        )
        self.stage_button.grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.ttk.Label(
            self.choose_section, text=PREPARE_HELPER, style="Helper.TLabel", wraplength=500
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.choose_section.columnconfigure(0, weight=1, minsize=280)

        self.ttk.Label(
            self.review_section, text=_("Review documents"), style="SectionTitle.TLabel"
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.ttk.Label(
            self.review_section, text=_("Prepared documents"), style="SubsectionTitle.TLabel"
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(20, 0))
        self.documents_view = self._build_tree(
            self.review_section,
            row=2,
            columns=DOCUMENT_TABLE_COLUMNS,
            headings={
                "filename": _("Filename"),
                "size": _("Size"),
                "status": _("Status"),
            },
            selectmode="browse",
        )
        self.documents_view.column("filename", width=280, minwidth=140, stretch=True, anchor="w")
        self.documents_view.column("size", width=110, minwidth=80, stretch=False, anchor="e")
        self.documents_view.column("status", width=180, minwidth=120, stretch=True, anchor="w")
        self.documents_view.bind("<<TreeviewSelect>>", self._show_document_detail)
        self.documents_view.bind("<Return>", lambda _event: self._upload())

        self.ttk.Separator(self.review_section, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(20, 18)
        )
        self.ttk.Label(
            self.review_section,
            text=_("Selected document details"),
            style="SubsectionTitle.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 8))
        detail = self.ttk.Frame(self.review_section, style="Main.TFrame")
        detail.grid(row=5, column=0, columnspan=3, sticky="ew")
        self.detail_filename = self.tk.StringVar(value=_("Select a document to review."))
        self.detail_status = self.tk.StringVar()
        self.detail_file_id = self.tk.StringVar()
        self.detail_voucher_id = self.tk.StringVar()
        self._detail_row: str | None = None
        self._detail_field(detail, 0, _("Filename"), self.detail_filename)
        self._detail_field(detail, 1, _("Status"), self.detail_status)
        self._detail_field(detail, 2, _("Lexware file ID"), self.detail_file_id, "file_id")
        self._detail_field(detail, 3, _("Lexware voucher ID"), self.detail_voucher_id, "voucher_id")

        action = self.ttk.Frame(self.review_section, style="Action.TFrame", padding=12)
        action.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        self.action_status = self.tk.StringVar(value=_("Select a document to review."))
        self.action_guidance = self.tk.StringVar()
        self.upload_button = self.ttk.Button(
            action,
            text=_("Send selected document"),
            command=self._upload,
            style="Primary.TButton",
        )
        self.upload_button.grid(row=0, column=0, sticky="w")
        self.ttk.Label(action, textvariable=self.action_status, style="Action.TLabel", wraplength=600).grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )
        self.ttk.Label(action, textvariable=self.action_guidance, style="Action.TLabel", wraplength=600).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.ttk.Label(action, textvariable=self.notice, style="Action.TLabel", wraplength=600).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.review_section.columnconfigure(0, weight=1)

        self._section_layout: str | None = None
        self.root.bind("<Configure>", self._layout_sections)
        self._layout_sections()

    def _configure_style(self) -> None:
        colors = {
            "background": "#fbfcff",
            "surface": "#ffffff",
            "foreground": "#07184d",
            "muted": "#47618f",
            "border": "#cbd8e8",
            "accent": "#0757ff",
            "selection": "#e8f1ff",
            "action": "#edf6ff",
        }
        self.root.configure(background=colors["background"])
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass
        style.configure("Main.TFrame", background=colors["background"])
        style.configure("Action.TFrame", background=colors["action"])
        style.configure(
            "AppTitle.TLabel",
            background=colors["background"],
            foreground=colors["foreground"],
            font=("TkDefaultFont", 25, "bold"),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=colors["background"],
            foreground=colors["foreground"],
            font=("TkDefaultFont", 20, "bold"),
        )
        style.configure(
            "SubsectionTitle.TLabel",
            background=colors["background"],
            foreground=colors["foreground"],
            font=("TkDefaultFont", 14, "bold"),
        )
        style.configure("Field.TLabel", background=colors["background"], foreground=colors["foreground"])
        style.configure("Helper.TLabel", background=colors["background"], foreground=colors["muted"])
        style.configure("Action.TLabel", background=colors["action"], foreground=colors["foreground"])
        style.configure("Gmail.TCombobox", padding=7)
        style.configure("Detail.TEntry", fieldbackground="#f4f7fb", foreground=colors["foreground"], padding=7)
        style.configure(
            "Documents.Treeview",
            background=colors["surface"],
            fieldbackground=colors["surface"],
            foreground=colors["foreground"],
            bordercolor=colors["border"],
            rowheight=36,
        )
        style.configure(
            "Documents.Treeview.Heading",
            background="#f2f6fb",
            foreground=colors["foreground"],
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
        )
        style.map(
            "Documents.Treeview",
            background=[("selected", colors["selection"])],
            foreground=[("selected", colors["foreground"])],
        )
        style.configure("Primary.TButton", padding=(14, 8), foreground=colors["accent"])

    def _configure_window(self) -> None:
        self.root.geometry(INITIAL_WINDOW_GEOMETRY)
        self.root.minsize(*MIN_WINDOW_SIZE)
        grid_propagate = getattr(self.root, "grid_propagate", None)
        if callable(grid_propagate):
            grid_propagate(False)

    def _layout_sections(self, event: Any = None) -> None:
        root = getattr(self, "root", None)
        if event is not None and root is not None and getattr(event, "widget", root) is not root:
            return
        width = getattr(event, "width", 0) or 0
        if not width and root is not None:
            try:
                width = root.winfo_width()
            except (AttributeError, RuntimeError):
                width = 0
        layout = "wide" if width >= DESKTOP_LAYOUT_BREAKPOINT else "stacked"
        if layout == self._section_layout:
            return
        self._section_layout = layout
        self._configure_layout_tracks(layout)
        if layout == "wide":
            self.choose_section.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
            self.review_section.grid(row=0, column=1, sticky="nsew", padx=(20, 0))
        else:
            self.choose_section.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
            self.review_section.grid(row=2, column=0, sticky="nsew", pady=(6, 0))

    def _configure_layout_tracks(self, layout: str) -> None:
        configure_column = getattr(self.sections, "columnconfigure", None)
        configure_row = getattr(self.sections, "rowconfigure", None)
        if layout == "wide":
            if callable(configure_column):
                configure_column(0, weight=2, minsize=360, uniform="sections")
                configure_column(1, weight=3, minsize=480, uniform="sections")
            if callable(configure_row):
                configure_row(0, weight=1)
                configure_row(1, weight=0)
                configure_row(2, weight=0)
            return
        if callable(configure_column):
            configure_column(0, weight=1, minsize=0, uniform="")
            configure_column(1, weight=0, minsize=0, uniform="")
        if callable(configure_row):
            configure_row(0, weight=0)
            configure_row(1, weight=1)
            configure_row(2, weight=1)

    def _build_tree(
        self,
        parent: Any,
        *,
        row: int,
        columns: tuple[str, ...],
        headings: dict[str, str],
        selectmode: str,
    ) -> Any:
        container = self.ttk.Frame(parent, style="Main.TFrame")
        container.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(10, 5))
        view = self.ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            selectmode=selectmode,
            height=5,
            takefocus=True,
            style="Documents.Treeview",
        )
        for column, heading in headings.items():
            view.heading(column, text=heading)
        if "filename" in columns:
            view.column("filename", width=340, minwidth=180, stretch=True, anchor="w")
        if "size" in columns:
            view.column("size", width=110, minwidth=80, stretch=False, anchor="e")
        view.grid(row=0, column=0, sticky="nsew")
        vertical = self.ttk.Scrollbar(container, orient="vertical", command=view.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        view.configure(yscrollcommand=vertical.set)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        return view

    def _detail_field(self, parent: Any, row: int, label: str, variable: Any, copy_key: str | None = None) -> None:
        self.ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=4
        )
        entry = self.ttk.Entry(
            parent, textvariable=variable, state="readonly", width=52, style="Detail.TEntry"
        )
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        if copy_key:
            self.ttk.Button(
                parent, text=_("Copy"), command=lambda key=copy_key: self._copy_detail(key)
            ).grid(row=row, column=2, sticky="e", padx=(12, 0), pady=4)
        parent.columnconfigure(1, weight=1)

    def run(self) -> None:
        self.root.mainloop()

    def _load_labels(self) -> None:
        try:
            labels = self.service.labels()
        except Exception as error:
            self.notice.set(_safe_error("labels", error))
            return
        self.label_box["values"] = tuple(labels)
        if labels:
            self.label.set(labels[0])
            self.label_box.current(0)
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
            row = self.candidates_view.insert(
                "", "end", values=(candidate["filename"], format_size(candidate["size"]))
            )
            self._candidate_ids[row] = candidate["id"]
        self.notice.set(_("Select one or more attachments, then choose Prepare selected documents."))

    def _stage(self) -> None:
        selected_rows = self.candidates_view.selection()
        selected_ids = [self._candidate_ids[row] for row in selected_rows]
        try:
            self.service.stage(self.label.get(), selected_ids)
        except Exception as error:
            self.notice.set(_safe_error("stage", error))
            return
        self.notice.set(_("Selected files were saved locally; nothing was sent to Lexware."))
        self._load_documents()

    def _load_documents(self) -> None:
        for row in self.documents_view.get_children():
            self.documents_view.delete(row)
        self._document_hashes.clear()
        self._document_status = {}
        self._document_details = {}
        self._document_action = {}
        self._document_integrity: dict[str, str | None] = {}
        self._detail_row = None
        detail_filename = getattr(self, "detail_filename", None)
        if detail_filename is not None:
            detail_filename.set(_("Select a document to review."))
        detail_status = getattr(self, "detail_status", None)
        if detail_status is not None:
            detail_status.set("")
        detail_file_id = getattr(self, "detail_file_id", None)
        if detail_file_id is not None:
            detail_file_id.set("")
        detail_voucher_id = getattr(self, "detail_voucher_id", None)
        if detail_voucher_id is not None:
            detail_voucher_id.set("")
        self._set_action_region(None)
        try:
            documents = self.service.documents()
        except Exception as error:
            self.notice.set(_safe_error("documents", error))
            return
        restore_required = False
        for document in documents:
            integrity = document.get("localIntegrity")
            status_code = str(document.get("status", "unknown"))
            display_status = status_label(status_code)
            if status_code == "uploaded" and document.get("origin") == "already_present":
                display_status = _("already present in Lexware")
            if integrity != "ok":
                display_status = _("Restore required")
                restore_required = True
            row = self.documents_view.insert(
                "",
                "end",
                values=(
                    document["filename"],
                    format_size(document["size"]),
                    display_status,
                ),
            )
            self._document_hashes[row] = document["hash"]
            self._document_status[row] = status_code
            self._document_details[row] = {
                "filename": _safe_filename(document["filename"]),
                "status": display_status,
                "file_id": str(document.get("id") or ""),
                "voucher_id": str(document.get("voucherId") or ""),
            }
            self._document_action[row] = document_action_state(
                status_code, integrity, document.get("origin")
            )
            self._document_integrity[row] = integrity
        if restore_required:
            self.notice.set(LOCAL_RESTORE_GUIDANCE)

    def _show_document_detail(self, _event: Any = None) -> None:
        rows = self.documents_view.selection()
        if not rows:
            self._detail_row = None
            self.detail_filename.set(_("Select a document to review."))
            detail_status = getattr(self, "detail_status", None)
            if detail_status is not None:
                detail_status.set("")
            self.detail_file_id.set("")
            self.detail_voucher_id.set("")
            self._set_action_region(None)
            return
        row = rows[0]
        values = self.documents_view.item(row, "values")
        details = getattr(self, "_document_details", {}).get(row, {})
        self._detail_row = row
        self.detail_filename.set(details.get("filename") or _safe_filename(values[0]))
        detail_status = getattr(self, "detail_status", None)
        if detail_status is not None:
            detail_status.set(details.get("status", ""))
        self.detail_file_id.set(details.get("file_id", ""))
        self.detail_voucher_id.set(details.get("voucher_id", ""))
        self._set_action_region(getattr(self, "_document_action", {}).get(row))

    def _set_action_region(self, action: tuple[bool, str, str] | None) -> None:
        status = getattr(self, "action_status", None)
        guidance = getattr(self, "action_guidance", None)
        button = getattr(self, "upload_button", None)
        if status is None or guidance is None or button is None:
            return
        if action is None:
            enabled = False
            status_text = _("Select a document to review.")
            guidance_text = ""
        else:
            enabled, status_text, guidance_text = action
        status.set(status_text)
        guidance.set(guidance_text)
        button.state(["!disabled"] if enabled else ["disabled"])

    def _copy_detail(self, field: str) -> None:
        variables = {"file_id": self.detail_file_id, "voucher_id": self.detail_voucher_id}
        variable = variables.get(field)
        value = variable.get() if variable is not None else ""
        if not value:
            self.notice.set(_("No Lexware identifier is available for this document."))
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        field_labels = {"file_id": _("Lexware file ID"), "voucher_id": _("Lexware voucher ID")}
        self.notice.set(_("Copied %(field)s to the clipboard.") % {"field": field_labels.get(field, field)})

    def _status_code_for_row(self, row: str, values: Sequence[Any]) -> str:
        document_status: dict[str, str] = getattr(self, "_document_status", {})
        known = document_status.get(row)
        if known:
            return str(known)
        displayed = str(values[2]) if len(values) > 2 else ""
        reverse = {label: code for code, label in _STATUS_LABELS.items()}
        return reverse.get(displayed, displayed)

    def _upload(self) -> None:
        rows = self.documents_view.selection()
        if len(rows) != 1:
            self.notice.set(_("Select one staged document to send."))
            return
        row = rows[0]
        values = self.documents_view.item(row, "values")
        if getattr(self, "_document_integrity", {}).get(row, "ok") != "ok":
            self.notice.set(LOCAL_RESTORE_GUIDANCE)
            return
        status = self._status_code_for_row(row, values)
        if status in {"uncertain", "uploading"}:
            self.notice.set(_("Outcome is uncertain; use the CLI recovery and reconciliation commands."))
            return
        if status != "staged":
            self.notice.set(_("Only staged documents can be sent."))
            return
        filename = _safe_filename(values[0])
        size = format_size(values[1]) if isinstance(values[1], int) else str(values[1])
        if not self.messagebox.askyesno(
            _("Confirm send"), _("Send %(filename)s (%(size)s) to Lexware?") % {"filename": filename, "size": size}
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
                _("Already present in Lexware; no upload was sent. Lexware file %(file_id)s "
                  "and voucher %(voucher_id)s.")
                % {"file_id": result["id"], "voucher_id": result["voucherId"]}
            )
        else:
            self.notice.set(
                _("Uploaded; Lexware file %(file_id)s and voucher %(voucher_id)s.")
                % {"file_id": result["id"], "voucher_id": result["voucherId"]}
            )
        self._load_documents()


def run_desktop(data_dir: Path | None) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ModuleNotFoundError as error:
        if error.name == "tkinter":
            raise DesktopUnavailableError(
                _("Desktop UI is unavailable; install Python Tk support and run 'belegdock desktop' again.")
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
