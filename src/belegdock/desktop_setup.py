from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
import json
import os
from pathlib import Path
from typing import Any
import webbrowser

from .desktop import _, _TkWorkerDispatcher, configure_theme
from .setup import (
    GMAIL_AUTH_TIMEOUT_SECONDS,
    SetupError,
    SetupState,
    authorize_gmail_guided,
    save_gmail,
    save_lexware_key,
    validate_lexware_key,
)

LEXWARE_KEY_URL = "https://app.lexware.de/addons/public-api"
SETUP_START_WIDTH = 760
SETUP_MIN_SIZE = (480, 360)
SCREEN_MARGIN = 96
SETUP_PROBE_ENV = "BELEGDOCK_SETUP_PROBE_DUMP"
CANVAS_BACKGROUND = "#fbfcff"
MIN_WRAP = 240
MAX_WRAP = 760
WRAP_MARGIN = 112
CANVAS_WIDTH_OFFSET = 88
WHEEL_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")
KEY_MASK = "•"
CLEARED_KEY_CODES = {"rejected", "invalid_key"}
NO_PREFIX_CODES = {"cancelled", "expired"}

INTRO_TEXT = _(
    "Verbinde einmalig Gmail und Lexware. Gmail wird nur gelesen; BelegDock sendet "
    "nichts automatisch."
)
GMAIL_HINT = _(
    "Wähle die OAuth-Client-Datei (JSON), die du vom Herausgeber erhalten hast. Sie wird "
    "nur gelesen und nicht kopiert. Danach meldest du dich im Browser bei Google an. "
    "Zeigt Google „Diese App wurde nicht von Google überprüft“, klicke auf „Weiter“ "
    "(gegebenenfalls zuerst auf „Erweitert“) und erlaube den Lesezugriff."
)
LEXWARE_HINT = _(
    "Erzeuge in Lexware Office einen API-Schlüssel auf dieser Seite (Link anklicken). Der "
    "Schlüssel wird geprüft und nur im Anmeldedatenspeicher des Betriebssystems abgelegt."
)
NO_FILE_TEXT = _("Keine Datei ausgewählt")
NOT_CONNECTED_TEXT = _("Nicht verbunden")
CONNECTED_STORED_TEXT = _("Verbunden (gespeichert)")
CONNECTED_TEXT = _("Verbunden als %(account)s")
ERROR_PREFIX = _("Fehler: ")
TESTER_HINT = _(
    "Zeigt Google „Zugriff blockiert“, muss der Herausgeber deine Gmail-Adresse als "
    "Testnutzer eintragen."
)

_STORE_TEXT = _(
    "Der Anmeldedatenspeicher des Betriebssystems ist nicht verfügbar. BelegDock speichert "
    "nie im Klartext."
)
GUIDANCE = {
    "gmail": {
        "connecting": _("Verbinde… Schließe die Anmeldung im Browser ab.") + " " + TESTER_HINT,
        "no_client_file": _("Wähle zuerst die OAuth-Client-Datei aus."),
        "client_file": _(
            "Die OAuth-Client-Datei ist nicht lesbar oder ungültig. Wähle die JSON-Datei "
            "vom Herausgeber erneut aus."
        ),
        "denied": _(
            "Google hat den Zugriff verweigert. Deine Gmail-Adresse muss vom Herausgeber als "
            "Testnutzer eingetragen sein. Erlaube im Browser außerdem den schreibgeschützten "
            "Zugriff auf Gmail."
        ),
        "timeout": _("Die Anmeldung im Browser wurde nicht rechtzeitig abgeschlossen. Versuche es erneut.")
        + " "
        + TESTER_HINT,
        "network": _("Google ist nicht erreichbar. Prüfe die Internetverbindung und versuche es erneut."),
        "store": _STORE_TEXT,
        "rejected": _("Google hat die Anfrage abgelehnt. Wende dich an den Herausgeber."),
        "unexpected": _("Die Verbindung zu Gmail ist fehlgeschlagen. Versuche es erneut."),
        "unreadable": _(
            "Gespeicherte Anmeldedaten konnten nicht gelesen werden (Speicher gesperrt?). "
            "Verbinde Gmail erneut."
        ),
        "cancelled": _("Verbindung abgebrochen. Du kannst es erneut versuchen.") + " " + TESTER_HINT,
        "expired": _(
            "Gmail-Anmeldung abgelaufen – bitte erneut verbinden. Im Testmodus von Google "
            "läuft die Anmeldung nach etwa 7 Tagen ab."
        ),
    },
    "lexware": {
        "connecting": _("Verbinde… Der Schlüssel wird geprüft."),
        "invalid_key": _("Gib den API-Schlüssel ein (ohne Leer- oder Sonderzeichen)."),
        "rejected": _("Schlüssel abgelehnt. Prüfe ihn in Lexware und gib ihn erneut ein."),
        "network": _("Lexware ist nicht erreichbar. Prüfe die Internetverbindung und versuche es erneut."),
        "store": _STORE_TEXT,
        "unexpected": _("Die Prüfung ist fehlgeschlagen. Versuche es erneut."),
        "unreadable": _(
            "Gespeicherte Anmeldedaten konnten nicht gelesen werden (Speicher gesperrt?). "
            "Gib den Schlüssel erneut ein."
        ),
        "cancelled": _("Prüfung abgebrochen. Der Schlüssel wurde nicht gespeichert."),
    },
}


@dataclass
class StepState:
    status: str = "missing"
    code: str | None = None
    account: str | None = None


@dataclass(frozen=True)
class SetupServices:
    authorize_gmail: Callable[[Path], Any]
    save_gmail: Callable[[Any], None]
    validate_lexware: Callable[[str], None]
    save_lexware: Callable[[str], None]


def default_services() -> SetupServices:
    return SetupServices(
        authorize_gmail=lambda path: authorize_gmail_guided(
            path, importer=import_module, timeout_seconds=GMAIL_AUTH_TIMEOUT_SECONDS
        ),
        save_gmail=save_gmail,
        validate_lexware=validate_lexware_key,
        save_lexware=save_lexware_key,
    )


def _initial_step(stored: str) -> StepState:
    if stored == "present":
        return StepState("connected")
    if stored == "read_failed":
        return StepState("error", "unreadable")
    if stored == "expired":
        return StepState("error", "expired")
    return StepState()


def _error_code(error: BaseException) -> str:
    return error.code if isinstance(error, SetupError) else "unexpected"


def _display_name(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(character if character.isprintable() else "_" for character in name)
    return cleaned[:120] or NO_FILE_TEXT


class SetupView:
    def __init__(
        self,
        root: Any,
        tk: Any,
        ttk: Any,
        filedialog: Any,
        services: SetupServices,
        state: SetupState,
        *,
        dispatch: Callable[[Callable[[], Any], Callable[[Any, Exception | None], None]], None],
        on_complete: Callable[[], None],
        on_close: Callable[[], None],
    ):
        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.services = services
        self.dispatch = dispatch
        self.on_complete = on_complete
        self.on_close = on_close
        self.gmail_state = _initial_step(state.gmail)
        self.lexware_state = _initial_step(state.lexware)
        self.wraplength = MAX_WRAP
        self._client_path: Path | None = None
        self._attempt = 0
        self._active: str | None = None
        self._closed = False
        self._finished = False
        self._wrapped: list[Any] = []
        self._previous: dict[str, StepState] = {}
        self.gmail_status = tk.StringVar()
        self.lexware_status = tk.StringVar()
        self.client_file_name = tk.StringVar(value=NO_FILE_TEXT)
        self.lexware_key = tk.StringVar()
        self._build()
        self._refresh()
        self._record_probe()

    def _record_probe(self) -> None:
        path = os.environ.get(SETUP_PROBE_ENV)
        if not path:
            return
        record = {"state": "setup", "gmail": self.gmail_state.status, "lexware": self.lexware_state.status}
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass

    @property
    def is_busy(self) -> bool:
        return self._active is not None

    @property
    def can_continue(self) -> bool:
        return self.gmail_state.status == "connected" and self.lexware_state.status == "connected"

    def _build(self) -> None:
        ttk = self.ttk
        self.root.title(_("BelegDock einrichten"))
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.frame = ttk.Frame(self.root, padding=(24, 24, 24, 12), style="Main.TFrame")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.canvas = self.tk.Canvas(self.frame, highlightthickness=0, background=CANVAS_BACKGROUND)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Frame(self.canvas, style="Main.TFrame")
        self.content.columnconfigure(0, weight=1)
        self._content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _event: self._content_resized())
        self.canvas.bind("<Configure>", self._canvas_resized)
        for sequence in WHEEL_SEQUENCES:
            self.root.bind(sequence, self._on_wheel)
        self._wrapped.append(
            self._label(self.content, _("BelegDock einrichten"), "SectionTitle.TLabel", row=0)
        )
        self._wrapped.append(self._label(self.content, INTRO_TEXT, "Helper.TLabel", row=1, pady=(6, 14)))

        gmail = ttk.Frame(self.content, style="Main.TFrame")
        gmail.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        gmail.columnconfigure(1, weight=1)
        ttk.Label(gmail, text=_("1. Gmail verbinden"), style="SubsectionTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self._wrapped.append(self._label(gmail, GMAIL_HINT, "Helper.TLabel", row=1, columnspan=2, pady=(6, 10)))
        self.choose_button = ttk.Button(
            gmail, text=_("OAuth-Client-Datei auswählen…"), command=self.choose_client_file
        )
        self.choose_button.grid(row=2, column=0, sticky="w")
        self._wrapped.append(
            self._label(
                gmail, self.client_file_name, "Field.TLabel", row=3, columnspan=2, pady=(6, 0), variable=True
            )
        )
        self.connect_button = ttk.Button(
            gmail, text=_("Mit Google verbinden"), command=self.connect_gmail, style="Primary.TButton"
        )
        self.connect_button.grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.gmail_label = self._label(
            gmail, self.gmail_status, "Helper.TLabel", row=5, columnspan=2, pady=(8, 0), variable=True
        )
        self._wrapped.append(self.gmail_label)

        lexware = ttk.Frame(self.content, style="Main.TFrame")
        lexware.grid(row=3, column=0, sticky="ew")
        lexware.columnconfigure(1, weight=1)
        ttk.Label(lexware, text=_("2. Lexware verbinden"), style="SubsectionTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self._wrapped.append(self._label(lexware, LEXWARE_HINT, "Helper.TLabel", row=1, columnspan=2, pady=(6, 4)))
        link = ttk.Label(
            lexware, text=LEXWARE_KEY_URL, style="Link.TLabel", cursor="hand2", wraplength=self.wraplength
        )
        self._wrapped.append(link)
        link.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))
        link.bind("<Button-1>", lambda _event: webbrowser.open(LEXWARE_KEY_URL))
        ttk.Label(lexware, text=_("API-Schlüssel"), style="Field.TLabel").grid(row=3, column=0, sticky="w")
        self.key_entry = ttk.Entry(
            lexware, textvariable=self.lexware_key, show=KEY_MASK, style="Detail.TEntry", width=44
        )
        self.key_entry.grid(row=3, column=1, sticky="ew", padx=(12, 0))
        self.key_entry.bind("<Return>", lambda _event: self.submit_lexware())
        self.submit_button = ttk.Button(
            lexware, text=_("Prüfen und speichern"), command=self.submit_lexware, style="Primary.TButton"
        )
        self.submit_button.grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.lexware_label = self._label(
            lexware, self.lexware_status, "Helper.TLabel", row=5, columnspan=2, pady=(8, 0), variable=True
        )
        self._wrapped.append(self.lexware_label)

        self.footer = ttk.Frame(self.frame, style="Main.TFrame")
        self.footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer = self.footer
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=0, sticky="w")
        self.cancel_button = ttk.Button(footer, text=_("Abbrechen"), command=self.cancel)
        self.cancel_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.continue_button = ttk.Button(
            footer, text=_("Weiter"), command=self.proceed, style="Primary.TButton"
        )
        self.continue_button.grid(row=0, column=2, sticky="e", padx=(12, 0))

    def _canvas_resized(self, event: Any) -> None:
        width = int(getattr(event, "width", 0))
        self.canvas.itemconfigure(self._content_window, width=width)
        self.resize(width + CANVAS_WIDTH_OFFSET)
        self._content_resized()

    def _content_resized(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()

    def _on_wheel(self, event: Any) -> None:
        if self.content.winfo_reqheight() <= self.canvas.winfo_height():
            return
        number = getattr(event, "num", 0)
        if number == 4:
            step = -1
        elif number == 5:
            step = 1
        else:
            step = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def _release_bindings(self) -> None:
        for sequence in WHEEL_SEQUENCES:
            self.root.unbind(sequence)

    def preferred_height(self) -> int:
        return int(self.content.winfo_reqheight() + self.footer.winfo_reqheight() + 48)

    def _label(
        self,
        parent: Any,
        content: Any,
        style: str,
        *,
        row: int,
        columnspan: int = 1,
        pady: tuple[int, int] | int = 0,
        variable: bool = False,
    ) -> Any:
        options = {"textvariable": content} if variable else {"text": content}
        label = self.ttk.Label(parent, style=style, wraplength=self.wraplength, **options)
        label.grid(row=row, column=0, columnspan=columnspan, sticky="w", pady=pady)
        return label

    def resize(self, width: int) -> None:
        if width <= 0:
            return
        wraplength = max(MIN_WRAP, min(MAX_WRAP, width - WRAP_MARGIN))
        if wraplength == self.wraplength:
            return
        self.wraplength = wraplength
        for label in self._wrapped:
            label.configure(wraplength=wraplength)

    def _step_text(self, step: str, state: StepState) -> str:
        if state.status == "connected":
            text = CONNECTED_TEXT % {"account": state.account} if state.account else CONNECTED_STORED_TEXT
            if state.code is None:
                return text
            return text + "\n" + GUIDANCE[step].get(state.code, GUIDANCE[step]["unexpected"])
        if state.status == "connecting":
            return GUIDANCE[step]["connecting"]
        if state.code is None:
            return NOT_CONNECTED_TEXT
        guidance = GUIDANCE[step].get(state.code, GUIDANCE[step]["unexpected"])
        return guidance if state.code in NO_PREFIX_CODES else ERROR_PREFIX + guidance

    def _set_enabled(self, widget: Any, enabled: bool) -> None:
        widget.state(["!disabled"] if enabled else ["disabled"])

    def _refresh(self) -> None:
        self.gmail_status.set(self._step_text("gmail", self.gmail_state))
        self.lexware_status.set(self._step_text("lexware", self.lexware_state))
        for label, state in ((self.gmail_label, self.gmail_state), (self.lexware_label, self.lexware_state)):
            label.configure(style={"connected": "Ok.TLabel", "error": "Error.TLabel"}.get(state.status, "Helper.TLabel"))
        idle = not self.is_busy
        for widget in (self.choose_button, self.connect_button, self.key_entry, self.submit_button):
            self._set_enabled(widget, idle)
        self._set_enabled(self.cancel_button, not idle)
        self._set_enabled(self.continue_button, idle and self.can_continue)
        if idle:
            self.progress.stop()
            self.progress.grid_remove()
        else:
            self.progress.grid()
            self.progress.start(20)

    def _step(self, step: str) -> StepState:
        return self.gmail_state if step == "gmail" else self.lexware_state

    def _set_step(self, step: str, state: StepState) -> None:
        if step == "gmail":
            self.gmail_state = state
        else:
            self.lexware_state = state

    def _begin(self, step: str) -> int:
        self._attempt += 1
        self._active = step
        self._previous[step] = self._step(step)
        return self._attempt

    def _fail(self, step: str, code: str) -> None:
        previous = self._previous.get(step, StepState())
        if previous.status == "connected":
            self._set_step(step, StepState("connected", code, previous.account))
        elif code == "cancelled":
            self._set_step(step, StepState("missing", code))
        else:
            self._set_step(step, StepState("error", code))

    def _finish(self) -> None:
        self._active = None

    def choose_client_file(self) -> None:
        if self._closed or self.is_busy:
            return
        chosen = self.filedialog.askopenfilename(
            title=_("OAuth-Client-Datei auswählen"),
            filetypes=[(_("JSON-Dateien"), "*.json"), (_("Alle Dateien"), "*.*")],
        )
        if not chosen:
            return
        self._client_path = Path(chosen)
        self.client_file_name.set(_display_name(str(chosen)))

    def connect_gmail(self) -> None:
        if self._closed or self.is_busy:
            return
        path = self._client_path
        if path is None:
            self.gmail_state = StepState("error", "no_client_file")
            self._refresh()
            return
        attempt = self._begin("gmail")
        self.gmail_state = StepState("connecting")
        self._refresh()
        self.dispatch(
            lambda: self.services.authorize_gmail(path),
            lambda result, error: self._gmail_authorized(attempt, result, error),
        )

    def _gmail_authorized(self, attempt: int, result: Any, error: Exception | None) -> None:
        if self._closed or attempt != self._attempt:
            return
        self._finish()
        if error is None:
            try:
                self.services.save_gmail(result)
            except Exception as problem:
                error = problem
        if error is not None:
            self._fail("gmail", _error_code(error))
        else:
            self.gmail_state = StepState("connected", account=str(result.account))
        self._refresh()

    def submit_lexware(self) -> None:
        if self._closed or self.is_busy:
            return
        key = str(self.lexware_key.get()).strip()
        if not key:
            self.lexware_state = StepState("error", "invalid_key")
            self._refresh()
            return
        attempt = self._begin("lexware")
        self.lexware_state = StepState("connecting")
        self._refresh()
        self.dispatch(
            lambda: self.services.validate_lexware(key),
            lambda _result, error: self._lexware_validated(attempt, key, error),
        )

    def _lexware_validated(self, attempt: int, key: str, error: Exception | None) -> None:
        if self._closed or attempt != self._attempt:
            return
        self._finish()
        if error is None:
            try:
                self.services.save_lexware(key)
            except Exception as problem:
                error = problem
        if error is not None:
            code = _error_code(error)
            self._fail("lexware", code)
            if code in CLEARED_KEY_CODES:
                self.lexware_key.set("")
        else:
            self.lexware_key.set("")
            self.lexware_state = StepState("connected")
        self._refresh()

    def cancel(self) -> None:
        step = self._active
        if step is None:
            return
        self._attempt += 1
        self._finish()
        self._fail(step, "cancelled")
        self._refresh()

    def proceed(self) -> None:
        if self._closed or self._finished or self.is_busy or not self.can_continue:
            return
        self._finished = True
        self._closed = True
        self._release_bindings()
        self.frame.destroy()
        self.on_complete()

    def request_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._attempt += 1
        self._release_bindings()
        self.on_close()


def fit_height(needed: int, screen_height: int) -> int:
    return max(SETUP_MIN_SIZE[1], min(needed, screen_height - SCREEN_MARGIN))


def run_setup(
    tk: Any, ttk: Any, filedialog: Any, state: SetupState, services: SetupServices | None = None
) -> Any:
    root = tk.Tk()
    configure_theme(root, tk, ttk)
    style = ttk.Style(root)
    style.configure("Ok.TLabel", background="#fbfcff", foreground="#0b7a3b")
    style.configure("Error.TLabel", background="#fbfcff", foreground="#b3261e")
    style.configure("Link.TLabel", background="#fbfcff", foreground="#0757ff", font=("TkDefaultFont", 10, "underline"))
    dispatcher = _TkWorkerDispatcher(root, lambda event: None)
    completed = False

    def finish() -> None:
        nonlocal completed
        completed = True
        dispatcher.close()
        root.quit()

    def close() -> None:
        dispatcher.close()
        root.quit()

    view = SetupView(
        root,
        tk,
        ttk,
        filedialog,
        services or default_services(),
        state,
        dispatch=dispatcher,
        on_complete=finish,
        on_close=close,
    )
    root.minsize(*SETUP_MIN_SIZE)
    root.geometry(f"{SETUP_START_WIDTH}x{SETUP_MIN_SIZE[1]}")
    root.update()
    height = fit_height(view.preferred_height(), root.winfo_screenheight())
    root.geometry(f"{SETUP_START_WIDTH}x{height}")
    root.mainloop()
    if completed:
        return root
    try:
        root.destroy()
    except Exception:
        pass
    return None
