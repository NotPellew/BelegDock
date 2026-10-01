import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from belegdock import desktop, workflow
from belegdock.workflow import DocumentRejected, Store
from async_dispatch_test_helper import ManualOperationDispatcher


THREE_ENTRIES = [
    {"id": "m:1", "message_id": "m", "part_id": "1", "filename": "Rechnung_1.pdf", "size": 4},
    {"id": "m:2", "message_id": "m", "part_id": "2", "filename": "Rechnung_2.pdf", "size": 4},
    {"id": "m:3", "message_id": "m", "part_id": "3", "filename": "Rechnung_3.pdf", "size": 4},
]


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.enabled = True

    def state(self, spec):
        for item in list(spec) if isinstance(spec, (list, tuple)) else [spec]:
            if item == "disabled":
                self.enabled = False
            elif item == "!disabled":
                self.enabled = True


class FakeLabelBox:
    def __init__(self):
        self.values = ()
        self.selected_index = None
        self.enabled = True

    def __setitem__(self, key, value):
        if key == "values":
            self.values = tuple(value)

    def current(self, index):
        self.selected_index = index

    def state(self, spec):
        for item in list(spec) if isinstance(spec, (list, tuple)) else [spec]:
            if item == "disabled":
                self.enabled = False
            elif item == "!disabled":
                self.enabled = True


class FakeProgress:
    def __init__(self):
        self.mode = "indeterminate"
        self.value = 0
        self.maximum = 0
        self.running = False

    def configure(self, **options):
        for key, value in options.items():
            setattr(self, key, value)

    def start(self, interval=None):
        self.running = True

    def stop(self):
        self.running = False


class FakeTree:
    def __init__(self):
        self.rows = []
        self.selection_rows = []

    def get_children(self):
        return tuple(row[0] for row in self.rows)

    def delete(self, row):
        self.rows = [item for item in self.rows if item[0] != row]

    def insert(self, _parent, _index, values):
        row = str(len(self.rows))
        self.rows.append((row, tuple(values)))
        return row

    def selection(self):
        return list(self.selection_rows)

    def selection_set(self, *rows):
        self.selection_rows = list(rows)

    def item(self, row, _key):
        for identifier, values in self.rows:
            if identifier == row:
                return values
        return ()


class FakeRoot:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class AutoConfirm:
    def askyesno(self, _title, _prompt):
        return True


class ManualRoot:
    def __init__(self):
        self.pending = []
        self.destroyed = False

    def after(self, _delay, callback):
        self.pending.append(callback)
        return "after"

    def destroy(self):
        self.destroyed = True

    def run_pending(self):
        pending, self.pending = self.pending, []
        for callback in pending:
            callback()


class RecordingDispatcher:
    def __init__(self, handler=None):
        self._operations = []
        self.events = []
        self.handler = handler

    def __call__(self, operation, completed):
        self._operations.append((operation, completed))

    @property
    def pending_count(self):
        return len(self._operations)

    def complete_next(self):
        operation, completed = self._operations.pop(0)
        try:
            result = operation()
        except Exception as error:
            completed(None, error)
        else:
            completed(result, None)

    def report(self, event):
        self.events.append(event)
        if self.handler is not None:
            self.handler(event)


class RecordingGmail:
    def __init__(self, entries=None, delay=0.0, fail=None):
        self.entries = [dict(entry) for entry in (entries or THREE_ENTRIES)]
        self.delay = delay
        self.fail = fail

    def labels(self):
        if self.fail is not None:
            raise self.fail
        if self.delay:
            time.sleep(self.delay)
        return ["Invoices"]

    def candidates(self, _label, cancelled=None):
        if self.fail is not None:
            raise self.fail
        if self.delay:
            time.sleep(self.delay)
        return [dict(entry) for entry in self.entries]

    def fetch(self, candidate):
        if self.delay:
            time.sleep(self.delay)
        return b"%PD" + str(candidate["part_id"]).encode()

    def candidate_classification(self, _candidate_id):
        raise ValueError("smoke classification unavailable")


class CancellingGmail(RecordingGmail):
    def __init__(self, cancel_after=None, **kwargs):
        super().__init__(**kwargs)
        self.cancel_after = cancel_after
        self.cancel_event = None

    def fetch(self, candidate):
        data = super().fetch(candidate)
        if self.cancel_after is not None and candidate["id"] == self.cancel_after:
            self.cancel_event.set()
        return data


class RecordingRemote:
    def __init__(self, upload_result=None, upload_error=None, delay=0.0):
        self.upload_result = dict(upload_result or {"id": "file-new", "voucherId": "voucher-new"})
        self.upload_error = upload_error
        self.delay = delay
        self.uploads = 0

    def inventory(self, include_archived=False, expected_organization_id=None):
        if self.delay:
            time.sleep(self.delay)
        return {"organizationId": "org", "files": []}

    def hash_file(self, _file_id):
        return ""

    def upload(self, _data, _filename):
        self.uploads += 1
        if self.delay:
            time.sleep(self.delay)
        if self.upload_error is not None:
            raise self.upload_error
        return dict(self.upload_result)


class CancellingRemote(RecordingRemote):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cancel_event = None

    def inventory(self, include_archived=False, expected_organization_id=None):
        result = super().inventory(include_archived, expected_organization_id)
        if self.cancel_event is not None:
            self.cancel_event.set()
        return result


class DesktopOperationTests(unittest.TestCase):
    def build(self, gmail, remote, dispatcher):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.service = desktop.DesktopService(
            Store(Path(temporary.name)), account="account@example.test", gmail=gmail, remote=remote
        )
        app.label = Variable()
        app.notice = Variable()
        app.messagebox = AutoConfirm()
        app.label_box = FakeLabelBox()
        app.candidates_view = FakeTree()
        app.documents_view = FakeTree()
        app._candidate_ids = {}
        app._document_hashes = {}
        app._document_status = {}
        app._document_details = {}
        app._document_action = {}
        app._document_integrity = {}
        app._detail_row = None
        app.detail_filename = Variable()
        app.detail_status = Variable()
        app.detail_file_id = Variable()
        app.detail_voucher_id = Variable()
        app.action_status = Variable()
        app.action_guidance = Variable()
        app.upload_button = FakeButton()
        app.stage_button = FakeButton()
        app.cancel_button = FakeButton()
        app.operation_status = Variable()
        app.progress = FakeProgress()
        app.root = FakeRoot()
        app._cancel_event = threading.Event()
        app._dispatch_operation = dispatcher
        return app

    def stage_document(self, app, entry_id="m:1"):
        digest = app.service.stage("Invoices", [entry_id])[0]
        app._load_documents()
        return digest

    def test_slow_label_load_shows_busy_and_populates_only_on_completion(self):
        self.assertTrue(hasattr(desktop.DesktopApplication, "_begin_operation"), "begin missing")
        app = self.build(RecordingGmail(), RecordingRemote(), ManualOperationDispatcher())
        app._load_candidates = Mock()

        app._load_labels()

        self.assertEqual(app.label_box.values, ())
        self.assertEqual(app.operation_status.get(), "Gmail-Labels werden geladen…")
        self.assertEqual(app._dispatch_operation.pending_count, 1)
        app._load_labels()
        self.assertEqual(app._dispatch_operation.pending_count, 1)

        app._dispatch_operation.complete_next()

        self.assertEqual(app.label_box.values, ("Invoices",))
        self.assertEqual(app.label.get(), "Invoices")
        app._load_candidates.assert_called_once_with()
        self.assertFalse(app._operation_active)

    def test_slow_candidate_load_populates_only_on_completion(self):
        self.assertTrue(hasattr(desktop.DesktopApplication, "_begin_operation"), "begin missing")
        app = self.build(RecordingGmail(), RecordingRemote(), ManualOperationDispatcher())
        app.label.set("Invoices")

        app._load_candidates()

        self.assertEqual(app.candidates_view.rows, [])
        self.assertEqual(app.operation_status.get(), "Anhänge werden geladen…")
        self.assertEqual(app._dispatch_operation.pending_count, 1)

        app._dispatch_operation.complete_next()

        self.assertEqual(len(app.candidates_view.rows), 3)
        self.assertFalse(app._operation_active)

    def test_staging_reports_determinate_progress(self):
        self.assertTrue(hasattr(desktop, "_TkWorkerDispatcher"), "dispatcher missing")
        texts = []

        def capture(event):
            app._handle_operation_event(event)
            texts.append(app.operation_status.get())

        dispatcher = RecordingDispatcher()
        app = self.build(RecordingGmail(), RecordingRemote(), dispatcher)
        dispatcher.handler = capture
        app.label.set("Invoices")
        app._load_candidates()
        dispatcher.complete_next()
        app.candidates_view.selection_set("0", "1", "2")

        app._stage()
        dispatcher.complete_next()

        self.assertEqual(
            dispatcher.events,
            [("progress", 1, 3), ("progress", 2, 3), ("progress", 3, 3)],
        )
        self.assertIn("Vorbereiten 1 von 3…", texts)
        self.assertIn("Vorbereiten 3 von 3…", texts)

    def test_staging_cancellation_keeps_committed_attachments_and_never_uploads(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        event = threading.Event()
        gmail = CancellingGmail(cancel_after="m:2")
        gmail.cancel_event = event
        app = self.build(gmail, RecordingRemote(), RecordingDispatcher())

        app._cancel_event = event
        app.label.set("Invoices")
        app._load_candidates()
        app._dispatch_operation.complete_next()
        app.candidates_view.selection_set("0", "1", "2")

        app._stage()
        app._dispatch_operation.complete_next()

        self.assertEqual(
            app.notice.get(),
            "Vorbereiten abgebrochen; 2 von 3 Dateien lokal gespeichert; "
            "nichts wurde an Lexware gesendet.",
        )
        documents = app.service.store.list_documents()
        self.assertEqual(len(documents), 2)
        self.assertTrue(all(document["status"] == "staged" for document in documents))
        self.assertEqual(app.service.remote.uploads, 0)
        self.assertEqual(app._dispatch_operation.pending_count, 1)

    def test_upload_cancellation_before_the_post_keeps_document_staged(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        event = threading.Event()
        remote = CancellingRemote()
        remote.cancel_event = event
        app = self.build(RecordingGmail(), remote, RecordingDispatcher())

        app._cancel_event = event
        self.stage_document(app)
        app.documents_view.selection_set("0")

        app._upload()
        app._dispatch_operation.complete_next()

        self.assertEqual(remote.uploads, 0)
        self.assertEqual(app.service.store.list_documents()[0]["status"], "staged")
        self.assertEqual(
            app.notice.get(),
            "Senden abgebrochen; das Dokument bleibt lokal vorbereitet und wurde nicht gesendet.",
        )
        self.assertEqual(app._dispatch_operation.pending_count, 1)

    def test_cancel_is_disabled_after_the_post_begins(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        snapshots = []

        def capture(event):
            app._handle_operation_event(event)
            snapshots.append((app._uncancellable, app.cancel_button.enabled))

        dispatcher = RecordingDispatcher()
        app = self.build(RecordingGmail(), RecordingRemote(), dispatcher)
        dispatcher.handler = capture
        self.stage_document(app)
        app.documents_view.selection_set("0")

        app._upload()
        dispatcher.complete_next()

        self.assertIn((True, False), snapshots)
        self.assertEqual(app.service.remote.uploads, 1)
        self.assertEqual(app.service.store.list_documents()[0]["status"], "uploaded")

    def test_rejection_and_uncertain_outcomes_are_distinguished(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        rejected = self.build(
            RecordingGmail(), RecordingRemote(upload_error=DocumentRejected(400)), RecordingDispatcher()
        )

        self.stage_document(rejected)
        rejected.documents_view.selection_set("0")
        rejected._upload()
        rejected._dispatch_operation.complete_next()

        self.assertIn("korrigiere das dokument", rejected.notice.get().lower())
        self.assertNotIn("unklar", rejected.notice.get().lower())

        uncertain = self.build(
            RecordingGmail(), RecordingRemote(upload_error=OSError("transport")), RecordingDispatcher()
        )
        digest = self.stage_document(uncertain)

        uncertain.documents_view.selection_set("0")
        uncertain._upload()
        uncertain._dispatch_operation.complete_next()

        self.assertEqual(uncertain.service.store.list_documents()[0]["status"], "uncertain")
        self.assertIn(digest, uncertain.notice.get())
        self.assertIn("nicht erneut senden", uncertain.notice.get().lower())
        self.assertEqual(uncertain.service.remote.uploads, 1)

    def test_failure_guidance_categories(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        cases = (
            ("candidates", workflow.LocalIntegrityError("broken"), "Lokaler Speicher"),
            ("candidates", ValueError("gmail"), "Gmail-Daten"),
            ("upload", workflow.RemoteAuthError(401), "Anmeldung fehlgeschlagen"),
            ("upload", OSError("offline"), "Verbindung fehlgeschlagen"),
            ("upload", workflow.UploadOutcomeUncertain("uncertain"), "unklar"),
            ("upload", RuntimeError("other"), "Lexware ist nicht erreichbar"),
            ("documents", RuntimeError("other"), "Lokaler Speicher"),
            ("anything", RuntimeError("other"), "Vorgang fehlgeschlagen"),
        )
        for operation, error, expected in cases:
            with self.subTest(operation=operation, error=type(error).__name__):
                self.assertIn(expected, desktop.failure_guidance(operation, error, "a" * 64))

    def test_interrupted_upload_reloads_with_cli_guidance_and_no_resend(self):
        self.assertTrue(hasattr(desktop, "failure_guidance"), "guidance missing")
        app = self.build(RecordingGmail(), RecordingRemote(), ManualOperationDispatcher())
        digest = app.service.stage("Invoices", ["m:1"])[0]
        with app.service.store._connection() as connection:
            connection.execute("UPDATE documents SET status='uploading' WHERE hash=?", (digest,))
            connection.commit()
        app.service.upload = Mock()

        app._load_documents()

        self.assertEqual(app._document_status["0"], "uploading")
        app.documents_view.selection_set("0")
        app._upload()

        self.assertIn("CLI-Befehle zur Wiederherstellung", app.notice.get())
        app.service.upload.assert_not_called()
        self.assertEqual(app._dispatch_operation.pending_count, 0)

    def test_shutdown_is_safe_during_cancellable_and_uncancellable_work(self):
        self.assertTrue(hasattr(desktop.DesktopApplication, "_request_close"), "close missing")
        cancellable = self.build(RecordingGmail(), RecordingRemote(), ManualOperationDispatcher())
        cancellable._load_labels()
        self.assertTrue(cancellable._operation_active)

        cancellable._request_close()

        self.assertTrue(cancellable._closed)
        self.assertTrue(cancellable._cancel_event.is_set())
        self.assertTrue(cancellable.root.destroyed)
        cancellable._dispatch_operation.complete_next()
        self.assertEqual(cancellable.label_box.values, ())

        uncancellable = self.build(RecordingGmail(), RecordingRemote(), ManualOperationDispatcher())
        self.stage_document(uncancellable)
        uncancellable.documents_view.selection_set("0")
        uncancellable._upload()
        uncancellable._uncancellable = True

        uncancellable._request_close()

        self.assertFalse(uncancellable._closed)
        self.assertTrue(uncancellable._close_after_completion)
        uncancellable._dispatch_operation.complete_next()
        self.assertTrue(uncancellable._closed)
        self.assertTrue(uncancellable.root.destroyed)

    def test_worker_dispatcher_marshals_results_and_events_through_the_pump(self):
        self.assertTrue(hasattr(desktop, "_TkWorkerDispatcher"), "dispatcher missing")
        root = ManualRoot()
        handled = []
        dispatcher = desktop._TkWorkerDispatcher(root, handled.append)
        dispatcher.report(("progress", 1, 1))
        result = {}

        def operation():
            return 42

        def completed(value, error):
            result["value"] = value
            result["error"] = error

        dispatcher(operation, completed)

        deadline = time.time() + 5
        while time.time() < deadline and "value" not in result:
            root.run_pending()
            time.sleep(0.01)

        self.assertEqual(result.get("value"), 42)
        self.assertIsNone(result.get("error"))
        self.assertIn(("progress", 1, 1), handled)


if __name__ == "__main__":
    unittest.main()
