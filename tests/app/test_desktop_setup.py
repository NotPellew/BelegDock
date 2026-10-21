import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from async_dispatch_test_helper import ManualOperationDispatcher
from setup_test_support import require, require_module

LEXWARE_KEY = "synthetic-lexware-key-0123"
HINT_URL = "https://app.lexware.de/addons/public-api"


class FakeVar:
    registry = None

    def __init__(self, master=None, value="", name=None):
        self.value = value
        type(self).registry.append(self)

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def make_tk():
    registry = []
    variable = type("Var", (FakeVar,), {"registry": registry})
    return SimpleNamespace(StringVar=variable, BooleanVar=variable, TclError=RuntimeError, vars=registry)


class SetupViewHarness:
    def __init__(self, gmail="missing", lexware="missing"):
        self.setup = require_module("belegdock.setup")
        self.module = require_module("belegdock.desktop_setup")
        self.tk = make_tk()
        self.ttk = MagicMock()
        self.root = MagicMock()
        self.filedialog = Mock()
        self.filedialog.askopenfilename.return_value = "/home/private-user/clients/client_secret.json"
        self.dispatch = ManualOperationDispatcher()
        self.authorization = SimpleNamespace(account="tester@example.test", token="synthetic-token")
        self.services = require(self.module, "SetupServices")(
            authorize_gmail=Mock(return_value=self.authorization),
            save_gmail=Mock(),
            validate_lexware=Mock(),
            save_lexware=Mock(),
        )
        self.completed = Mock()
        self.closed = Mock()
        state = require(self.setup, "SetupState")(True, gmail, lexware)
        self.view = require(self.module, "SetupView")(
            self.root,
            self.tk,
            self.ttk,
            self.filedialog,
            self.services,
            state,
            dispatch=self.dispatch,
            on_complete=self.completed,
            on_close=self.closed,
        )

    def error(self, code):
        return require(self.setup, "SetupError")(code)

    def texts(self):
        values = [str(variable.get()) for variable in self.tk.vars]
        for widget in (self.ttk.Label, self.ttk.Button, self.ttk.Frame, self.ttk.LabelFrame):
            for call in widget.call_args_list:
                text = call.kwargs.get("text")
                if text is not None:
                    values.append(str(text))
        return values

    def connect_gmail(self):
        self.view.choose_client_file()
        self.view.connect_gmail()

    def enter_key(self, key=LEXWARE_KEY):
        self.view.lexware_key.set(key)
        self.view.submit_lexware()


class SetupViewStateTests(unittest.TestCase):
    def test_missing_credentials_start_not_connected_and_block_continue(self):
        harness = SetupViewHarness("missing", "missing")

        self.assertEqual(harness.view.gmail_state.status, "missing")
        self.assertEqual(harness.view.lexware_state.status, "missing")
        self.assertIn("Nicht verbunden", harness.view.gmail_status.get())
        self.assertIn("Nicht verbunden", harness.view.lexware_status.get())
        self.assertFalse(harness.view.can_continue)
        harness.view.proceed()
        harness.completed.assert_not_called()

    def test_stored_credentials_show_connected_and_are_skippable(self):
        harness = SetupViewHarness("present", "present")

        self.assertEqual(harness.view.gmail_state.status, "connected")
        self.assertEqual(harness.view.lexware_state.status, "connected")
        self.assertIn("Verbunden", harness.view.gmail_status.get())
        self.assertTrue(harness.view.can_continue)
        harness.view.proceed()
        harness.completed.assert_called_once_with()
        harness.services.authorize_gmail.assert_not_called()
        harness.services.validate_lexware.assert_not_called()

    def test_one_stored_credential_still_requires_the_other_step(self):
        harness = SetupViewHarness("present", "missing")

        self.assertEqual(harness.view.gmail_state.status, "connected")
        self.assertEqual(harness.view.lexware_state.status, "missing")
        self.assertFalse(harness.view.can_continue)

    def test_unreadable_stored_credential_is_an_error_with_guidance(self):
        harness = SetupViewHarness("read_failed", "present")

        self.assertEqual(harness.view.gmail_state.status, "error")
        self.assertIn("nicht gelesen", harness.view.gmail_status.get())
        self.assertFalse(harness.view.can_continue)

    def test_proceeding_destroys_the_setup_frame_and_notifies_once(self):
        harness = SetupViewHarness("present", "present")

        harness.view.proceed()
        harness.view.proceed()

        harness.ttk.Frame.return_value.destroy.assert_called()
        harness.completed.assert_called_once_with()

    def test_close_request_exits_and_discards_pending_results(self):
        harness = SetupViewHarness()
        harness.connect_gmail()
        protocol = [call for call in harness.root.protocol.call_args_list if call.args[0] == "WM_DELETE_WINDOW"]
        self.assertTrue(protocol)

        protocol[-1].args[1]()
        harness.dispatch.complete_next()

        harness.closed.assert_called_once_with()
        harness.services.save_gmail.assert_not_called()
        harness.completed.assert_not_called()

    def test_narrow_windows_wrap_text_tighter_than_wide_windows(self):
        harness = SetupViewHarness()

        harness.view.resize(1400)
        wide = harness.view.wraplength
        harness.view.resize(560)
        narrow = harness.view.wraplength

        self.assertGreater(wide, narrow)
        self.assertGreaterEqual(narrow, 240)

    def test_screen_explains_prerequisites_and_links_the_lexware_key_page(self):
        harness = SetupViewHarness()
        joined = "\n".join(harness.texts())

        self.assertIn(HINT_URL, joined)
        self.assertIn("nicht überprüft", joined)
        self.assertIn("OAuth-Client-Datei auswählen", joined)
        self.assertIn("Mit Google verbinden", joined)
        self.assertIn("Prüfen und speichern", joined)
        self.assertIn("Weiter", joined)


class GmailStepTests(unittest.TestCase):
    def test_file_dialog_filters_json_and_only_the_file_name_is_shown(self):
        harness = SetupViewHarness()

        harness.view.choose_client_file()

        options = harness.filedialog.askopenfilename.call_args.kwargs
        patterns = [pattern for _, pattern in options["filetypes"]]
        self.assertIn("*.json", patterns)
        self.assertEqual(harness.view.client_file_name.get(), "client_secret.json")
        for text in harness.texts():
            self.assertNotIn("private-user", text)
            self.assertNotIn("/home", text)

    def test_windows_style_path_shows_only_the_file_name(self):
        harness = SetupViewHarness()
        harness.filedialog.askopenfilename.return_value = "C:\\Users\\private-user\\Downloads\\client.json"

        harness.view.choose_client_file()

        self.assertEqual(harness.view.client_file_name.get(), "client.json")
        self.assertFalse(any("private-user" in text for text in harness.texts()))

    def test_dismissed_dialog_keeps_the_previous_choice(self):
        harness = SetupViewHarness()
        harness.view.choose_client_file()
        harness.filedialog.askopenfilename.return_value = ""

        harness.view.choose_client_file()

        self.assertEqual(harness.view.client_file_name.get(), "client_secret.json")

    def test_connecting_without_a_file_asks_for_one_and_starts_nothing(self):
        harness = SetupViewHarness()

        harness.view.connect_gmail()

        self.assertEqual(harness.dispatch.pending_count, 0)
        self.assertEqual(harness.view.gmail_state.status, "error")
        self.assertIn("OAuth-Client-Datei", harness.view.gmail_status.get())

    def test_success_authorizes_in_the_worker_then_saves_and_shows_the_account(self):
        harness = SetupViewHarness()

        harness.connect_gmail()

        self.assertEqual(harness.view.gmail_state.status, "connecting")
        self.assertIn("Verbinde", harness.view.gmail_status.get())
        self.assertTrue(harness.view.is_busy)
        self.assertEqual(harness.dispatch.pending_count, 1)
        harness.services.authorize_gmail.assert_not_called()

        harness.dispatch.complete_next()

        path = harness.services.authorize_gmail.call_args.args[0]
        self.assertEqual(Path(path).name, "client_secret.json")
        harness.services.save_gmail.assert_called_once_with(harness.authorization)
        self.assertEqual(harness.view.gmail_state.status, "connected")
        self.assertIn("Verbunden als tester@example.test", harness.view.gmail_status.get())
        self.assertFalse(harness.view.is_busy)

    def test_failures_show_german_guidance_save_nothing_and_allow_retry(self):
        cases = {
            "client_file": "OAuth-Client-Datei",
            "denied": "Testnutzer",
            "timeout": "erneut",
            "network": "Internetverbindung",
            "store": "Klartext",
            "rejected": "Herausgeber",
            "unexpected": "fehlgeschlagen",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                harness = SetupViewHarness()
                harness.services.authorize_gmail.side_effect = harness.error(code)
                harness.connect_gmail()

                harness.dispatch.complete_next()

                self.assertEqual(harness.view.gmail_state.status, "error")
                self.assertEqual(harness.view.gmail_state.code, code)
                self.assertIn(expected, harness.view.gmail_status.get())
                harness.services.save_gmail.assert_not_called()
                self.assertFalse(harness.view.is_busy)
                self.assertFalse(harness.view.can_continue)
                harness.view.connect_gmail()
                self.assertEqual(harness.dispatch.pending_count, 1)

    def test_browser_denial_explains_test_user_and_read_only_permission(self):
        harness = SetupViewHarness()
        harness.services.authorize_gmail.side_effect = harness.error("denied")
        harness.connect_gmail()

        harness.dispatch.complete_next()

        text = harness.view.gmail_status.get()
        self.assertIn("Testnutzer", text)
        self.assertIn("schreibgeschützt", text)

    def test_unclassified_errors_never_surface_their_text(self):
        harness = SetupViewHarness()
        harness.services.authorize_gmail.side_effect = RuntimeError("/home/private-user token=abc123")
        harness.connect_gmail()

        harness.dispatch.complete_next()

        self.assertEqual(harness.view.gmail_state.status, "error")
        for text in harness.texts():
            self.assertNotIn("abc123", text)
            self.assertNotIn("private-user", text)

    def test_save_failure_after_authorization_is_an_error_not_a_connection(self):
        harness = SetupViewHarness()
        harness.services.save_gmail.side_effect = harness.error("store")
        harness.connect_gmail()

        harness.dispatch.complete_next()

        self.assertEqual(harness.view.gmail_state.status, "error")
        self.assertIn("Klartext", harness.view.gmail_status.get())

    def test_second_connect_while_busy_starts_no_second_flow(self):
        harness = SetupViewHarness()
        harness.connect_gmail()

        harness.view.connect_gmail()

        self.assertEqual(harness.dispatch.pending_count, 1)

    def test_cancel_returns_to_retry_at_once_and_discards_the_late_result(self):
        harness = SetupViewHarness()
        harness.connect_gmail()

        harness.view.cancel()

        self.assertFalse(harness.view.is_busy)
        self.assertEqual(harness.view.gmail_state.status, "missing")
        self.assertIn("abgebrochen", harness.view.gmail_status.get())
        harness.dispatch.complete_next()
        harness.services.save_gmail.assert_not_called()
        self.assertEqual(harness.view.gmail_state.status, "missing")
        self.assertIn("abgebrochen", harness.view.gmail_status.get())
        self.assertFalse(harness.view.can_continue)

    def test_late_failure_of_an_abandoned_flow_does_not_replace_the_retry_state(self):
        harness = SetupViewHarness()
        harness.services.authorize_gmail.side_effect = harness.error("timeout")
        harness.connect_gmail()
        harness.view.cancel()

        harness.dispatch.complete_next()

        self.assertIn("abgebrochen", harness.view.gmail_status.get())

    def test_retry_after_cancel_saves_only_the_new_authorization(self):
        harness = SetupViewHarness()
        stale = SimpleNamespace(account="stale@example.test", token="stale-token")
        fresh = SimpleNamespace(account="fresh@example.test", token="fresh-token")
        harness.services.authorize_gmail.side_effect = [stale, fresh]
        harness.connect_gmail()
        harness.view.cancel()
        harness.view.connect_gmail()
        self.assertEqual(harness.dispatch.pending_count, 2)

        harness.dispatch.complete_next()
        harness.dispatch.complete_next()

        harness.services.save_gmail.assert_called_once_with(fresh)
        self.assertIn("fresh@example.test", harness.view.gmail_status.get())


class LexwareStepTests(unittest.TestCase):
    def test_key_entry_is_masked_and_bound_to_the_key_variable(self):
        harness = SetupViewHarness()

        entries = [call.kwargs for call in harness.ttk.Entry.call_args_list]

        masked = [kwargs for kwargs in entries if kwargs.get("show")]
        self.assertTrue(masked, "no masked entry")
        self.assertEqual(masked[0]["show"], "•")
        self.assertIs(masked[0]["textvariable"], harness.view.lexware_key)

    def test_success_validates_once_in_the_worker_then_saves_and_clears_the_key(self):
        harness = SetupViewHarness()

        harness.enter_key(f"  {LEXWARE_KEY}  ")

        self.assertEqual(harness.view.lexware_state.status, "connecting")
        self.assertTrue(harness.view.is_busy)
        harness.services.validate_lexware.assert_not_called()
        harness.services.save_lexware.assert_not_called()

        harness.dispatch.complete_next()

        harness.services.validate_lexware.assert_called_once_with(LEXWARE_KEY)
        harness.services.save_lexware.assert_called_once_with(LEXWARE_KEY)
        self.assertEqual(harness.view.lexware_state.status, "connected")
        self.assertEqual(harness.view.lexware_key.get(), "")
        for text in harness.texts():
            self.assertNotIn(LEXWARE_KEY, text)

    def test_rejected_key_is_not_saved_and_a_corrected_key_can_be_saved(self):
        harness = SetupViewHarness()
        harness.services.validate_lexware.side_effect = [harness.error("rejected"), None]
        harness.enter_key("wrong-key-value")

        harness.dispatch.complete_next()

        self.assertEqual(harness.view.lexware_state.status, "error")
        self.assertIn("Schlüssel abgelehnt", harness.view.lexware_status.get())
        harness.services.save_lexware.assert_not_called()
        self.assertFalse(harness.view.can_continue)

        harness.enter_key(LEXWARE_KEY)
        harness.dispatch.complete_next()

        harness.services.save_lexware.assert_called_once_with(LEXWARE_KEY)
        self.assertEqual(harness.view.lexware_state.status, "connected")

    def test_other_failures_show_guidance_and_save_nothing(self):
        cases = {"network": "Internetverbindung", "store": "Klartext", "unexpected": "fehlgeschlagen"}
        for code, expected in cases.items():
            with self.subTest(code=code):
                harness = SetupViewHarness()
                harness.services.validate_lexware.side_effect = harness.error(code)
                harness.enter_key()

                harness.dispatch.complete_next()

                self.assertIn(expected, harness.view.lexware_status.get())
                harness.services.save_lexware.assert_not_called()
                self.assertEqual(harness.view.lexware_state.status, "error")

    def test_raw_errors_never_surface_the_key(self):
        harness = SetupViewHarness()
        harness.services.validate_lexware.side_effect = RuntimeError(f"Bearer {LEXWARE_KEY}")
        harness.enter_key()

        harness.dispatch.complete_next()

        for text in harness.texts():
            self.assertNotIn(LEXWARE_KEY, text)

    def test_blank_key_asks_for_a_key_and_starts_nothing(self):
        harness = SetupViewHarness()

        harness.enter_key("   ")

        self.assertEqual(harness.dispatch.pending_count, 0)
        self.assertEqual(harness.view.lexware_state.status, "error")
        harness.services.validate_lexware.assert_not_called()

    def test_save_failure_after_validation_is_an_error_not_a_connection(self):
        harness = SetupViewHarness()
        harness.services.save_lexware.side_effect = harness.error("store")
        harness.enter_key()

        harness.dispatch.complete_next()

        self.assertEqual(harness.view.lexware_state.status, "error")
        self.assertIn("Klartext", harness.view.lexware_status.get())

    def test_cancel_discards_a_late_valid_result_without_saving(self):
        harness = SetupViewHarness()
        harness.enter_key()

        harness.view.cancel()
        self.assertFalse(harness.view.is_busy)
        self.assertEqual(harness.view.lexware_state.status, "missing")
        harness.dispatch.complete_next()

        harness.services.save_lexware.assert_not_called()
        self.assertEqual(harness.view.lexware_state.status, "missing")
        self.assertIn("abgebrochen", harness.view.lexware_status.get())

    def test_second_submit_while_busy_starts_no_second_probe(self):
        harness = SetupViewHarness()
        harness.enter_key()

        harness.view.submit_lexware()

        self.assertEqual(harness.dispatch.pending_count, 1)


class CompletionTests(unittest.TestCase):
    def test_continue_is_available_only_after_both_steps_connect(self):
        harness = SetupViewHarness()
        harness.connect_gmail()
        harness.dispatch.complete_next()
        self.assertFalse(harness.view.can_continue)
        harness.enter_key()
        harness.dispatch.complete_next()

        self.assertTrue(harness.view.can_continue)
        harness.view.proceed()
        harness.completed.assert_called_once_with()

    def test_gmail_step_can_be_skipped_when_only_lexware_is_missing(self):
        harness = SetupViewHarness("present", "missing")
        harness.enter_key()
        harness.dispatch.complete_next()

        self.assertTrue(harness.view.can_continue)
        harness.services.authorize_gmail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
