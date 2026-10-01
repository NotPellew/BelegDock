import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .desktop import DesktopApplication, DesktopService
from .workflow import Store

SMOKE_DUMP_ENV = "BELEGDOCK_DESKTOP_SMOKE_DUMP"
SMOKE_DATA_ENV = "BELEGDOCK_DESKTOP_SMOKE_DATA"


def _entries() -> list[dict[str, Any]]:
    return [
        {"id": "smoke:1", "message_id": "smoke", "part_id": "1", "filename": "Rechnung_1.pdf", "size": 4},
        {"id": "smoke:2", "message_id": "smoke", "part_id": "2", "filename": "Rechnung_2.pdf", "size": 4},
        {"id": "smoke:3", "message_id": "smoke", "part_id": "3", "filename": "Rechnung_3.pdf", "size": 4},
    ]


class _SmokeGmail:
    def __init__(self, delay: float = 0.2) -> None:
        self.delay = delay

    def labels(self) -> list[str]:
        time.sleep(self.delay)
        return ["Smoke-Invoices"]

    def candidates(self, _label: str, *, cancelled: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
        time.sleep(self.delay)
        return _entries()

    def fetch(self, candidate: dict[str, Any]) -> bytes:
        time.sleep(self.delay)
        return b"%PD" + str(candidate["part_id"]).encode()

    def candidate_classification(self, _candidate_id: str) -> Any:
        raise ValueError("smoke classification unavailable")


class _SmokeRemote:
    def __init__(self, delay: float = 0.3) -> None:
        self.delay = delay
        self.uploads = 0

    def inventory(
        self, include_archived: bool = False, expected_organization_id: str | None = None
    ) -> dict[str, Any]:
        time.sleep(self.delay)
        return {"organizationId": "smoke-org", "files": []}

    def hash_file(self, _file_id: str) -> str:
        return ""

    def upload(self, _data: bytes, _filename: str) -> dict[str, str]:
        time.sleep(self.delay)
        self.uploads += 1
        return {"id": "file-smoke", "voucherId": "voucher-smoke"}

    def verify_existing(self, _file_id: str, _voucher_id: str) -> bytes:
        return b""


class _SmokeMessageBox:
    def askyesno(self, _title: str, _prompt: str) -> bool:
        return True


class _SmokeDriver:
    def __init__(self, application: DesktopApplication, dump_path: Path, timeout: float = 90.0) -> None:
        self.application = application
        self.dump_path = dump_path
        self.deadline = time.monotonic() + timeout

    def start(self) -> None:
        self._poll(self._labels_ready, self._on_labels, "labels")

    def _write(self, state: str, **fields: Any) -> None:
        record = {"state": state, **fields}
        try:
            with self.dump_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass

    def _expired(self) -> bool:
        return time.monotonic() >= self.deadline

    def _poll(self, condition: Callable[[], bool], ready: Callable[[], None], label: str) -> None:
        try:
            done = condition()
        except Exception as error:
            self._write("error", at=label, detail=type(error).__name__)
            self._finish()
            return
        if done:
            try:
                ready()
            except Exception as error:
                self._write("error", at=label, detail=type(error).__name__)
                self._finish()
            return
        if self._expired():
            self._write("timeout", at=label)
            self._finish()
            return
        self.application.root.after(50, lambda: self._poll(condition, ready, label))

    def _finish(self) -> None:
        try:
            self.application._request_close()
        except Exception:
            try:
                self.application.root.destroy()
            except Exception:
                pass

    def _labels_ready(self) -> bool:
        return bool(self.application.label_box["values"])

    def _on_labels(self) -> None:
        self._write("labels", selected=self.application.label.get())
        self._poll(self._candidates_ready, self._on_candidates, "candidates")

    def _candidates_ready(self) -> bool:
        return bool(self.application.candidates_view.get_children())

    def _on_candidates(self) -> None:
        rows = self.application.candidates_view.get_children()
        self._write("candidates", count=len(rows))
        self.application.candidates_view.selection_set(rows[0])
        self._poll(lambda: not self.application._operation_active, self._start_stage, "idle")

    def _start_stage(self) -> None:
        self._write("staging", cancel=self._cancel_enabled())
        self.application._stage()
        self._poll(self._staged_ready, self._on_staged, "staged")

    def _staged_ready(self) -> bool:
        return (
            not self.application._operation_active
            and bool(self.application.documents_view.get_children())
        )

    def _on_staged(self) -> None:
        rows = self.application.documents_view.get_children()
        self._write("staged", count=len(rows))
        self.application.documents_view.selection_set(rows[0])
        self._poll(lambda: not self.application._operation_active, self._start_upload, "idle")

    def _start_upload(self) -> None:
        self.application._upload()
        self._poll(self._uncancellable_ready, self._on_uncancellable, "uncancellable")

    def _uncancellable_ready(self) -> bool:
        return bool(self.application._uncancellable)

    def _on_uncancellable(self) -> None:
        self._write("uncancellable", cancel=self._cancel_enabled())
        self._poll(self._upload_done, self._on_uploaded, "upload")

    def _upload_done(self) -> bool:
        return not self.application._operation_active

    def _on_uploaded(self) -> None:
        statuses = list(self.application._document_status.values())
        self._write("uploaded", statuses=statuses)
        self.application._layout_sections(SimpleNamespace(width=700))
        narrow = self.application._section_layout
        self.application._layout_sections(SimpleNamespace(width=1200))
        wide = self.application._section_layout
        self._write("layout", narrow=narrow, wide=wide)
        self._write("terminal", ok=True)
        self._finish()

    def _cancel_enabled(self) -> bool:
        try:
            return not bool(self.application.cancel_button.instate(["disabled"]))
        except Exception:
            return False


def run_desktop_smoke(tk: Any, ttk: Any, messagebox: Any) -> None:
    del messagebox
    dump_path = Path(os.environ[SMOKE_DUMP_ENV])
    data_dir = Path(
        os.environ.get(SMOKE_DATA_ENV) or tempfile.mkdtemp(prefix="belegdock-desktop-smoke-")
    )
    store = Store(data_dir)
    application = DesktopApplication(
        DesktopService(store, account="smoke@example.test", gmail=_SmokeGmail(), remote=_SmokeRemote()),
        tk,
        ttk,
        _SmokeMessageBox(),
    )
    application._smoke_dump = dump_path
    driver = _SmokeDriver(application, dump_path)
    application.root.after(50, driver.start)
    try:
        application.run()
    finally:
        application.service.close()
