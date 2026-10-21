from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
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
SETUP_MIN_SIZE = (480, 480)
MIN_WRAP = 240
MAX_WRAP = 760
WRAP_MARGIN = 112
KEY_MASK = "•"
RETRYABLE_KEY_CODES = {"network", "store"}

INTRO_TEXT = _(
    "Verbinde einmalig Gmail und Lexware. Gmail wird nur gelesen; BelegDock sendet "
    "nichts automatisch."
)
GMAIL_HINT = _(
    "Wähle die OAuth-Client-Datei (JSON), die du vom Herausgeber erhalten hast. Sie wird "
    "nur gelesen und nicht kopiert. Danach meldest du dich im Browser bei Google an. "
    "Zeigt Google „Google hat diese App nicht überprüft“, wähle „Erweitert“, fahre fort "
    "und erlaube den Lesezugriff."
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

_STORE_TEXT = _(
    "Der Anmeldedatenspeicher des Betriebssystems ist nicht verfügbar. BelegDock speichert "
    "nie im Klartext."
)
GUIDANCE = {
    "gmail": {
        "connecting": _("Verbinde… Schließe die Anmeldung im Browser ab."),
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
        "timeout": _("Die Anmeldung im Browser wurde nicht rechtzeitig abgeschlossen. Versuche es erneut."),
        "network": _("Google ist nicht erreichbar. Prüfe die Internetverbindung und versuche es erneut."),
        "store": _STORE_TEXT,
        "rejected": _("Google hat die Anfrage abgelehnt. Wende dich an den Herausgeber."),
        "unexpected": _("Die Verbindung zu Gmail ist fehlgeschlagen. Versuche es erneut."),
        "unreadable": _(
            "Gespeicherte Anmeldedaten konnten nicht gelesen werden (Speicher gesperrt?). "
            "Verbinde Gmail erneut."
        ),
        "cancelled": _("Verbindung abgebrochen. Du kannst es erneut versuchen."),
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
        self.gmail_status = tk.StringVar()
        self.lexware_status = tk.StringVar()
        self.client_file_name = tk.StringVar(value=NO_FILE_TEXT)
        self.lexware_key = tk.StringVar()
        self._build()
        self._refresh()

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
        self.frame = ttk.Frame(self.root, padding=24, style="Main.TFrame")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self._wrapped.append(
            self._label(self.frame, _("BelegDock einrichten"), "SectionTitle.TLabel", row=0)
        )
        self._wrapped.append(self._label(self.frame, INTRO_TEXT, "Helper.TLabel", row=1, pady=(6, 14)))

        gmail = ttk.Frame(self.frame, style="Main.TFrame")
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

        lexware = ttk.Frame(self.frame, style="Main.TFrame")
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

        footer = ttk.Frame(self.frame, style="Main.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=0, sticky="w")
        self.cancel_button = ttk.Button(footer, text=_("Abbrechen"), command=self.cancel)
        self.cancel_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.continue_button = ttk.Button(
            footer, text=_("Weiter"), command=self.proceed, style="Primary.TButton"
        )
        self.continue_button.grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.frame.bind("<Configure>", lambda event: self.resize(getattr(event, "width", 0)))

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
            if state.account:
                return CONNECTED_TEXT % {"account": state.account}
            return CONNECTED_STORED_TEXT
        if state.status == "connecting":
            return GUIDANCE[step]["connecting"]
        if state.code is None:
            return NOT_CONNECTED_TEXT
        guidance = GUIDANCE[step].get(state.code, GUIDANCE[step]["unexpected"])
        return guidance if state.code == "cancelled" else ERROR_PREFIX + guidance

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

    def _begin(self, step: str) -> int:
        self._attempt += 1
        self._active = step
        return self._attempt

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
            self.gmail_state = StepState("error", _error_code(error))
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
            self.lexware_state = StepState("error", code)
            if code not in RETRYABLE_KEY_CODES:
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
        cancelled = StepState("missing", "cancelled")
        if step == "gmail":
            self.gmail_state = cancelled
        else:
            self.lexware_state = cancelled
        self._refresh()

    def proceed(self) -> None:
        if self._closed or self._finished or self.is_busy or not self.can_continue:
            return
        self._finished = True
        self._closed = True
        self.frame.destroy()
        self.on_complete()

    def request_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._attempt += 1
        self.on_close()


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

    SetupView(
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
    root.geometry(f"{SETUP_MIN_SIZE[0]}x{SETUP_MIN_SIZE[1]}")
    root.update()
    height = root.winfo_reqheight()
    root.minsize(SETUP_MIN_SIZE[0], height)
    root.geometry(f"{SETUP_START_WIDTH}x{height}")
    root.mainloop()
    if completed:
        return root
    try:
        root.destroy()
    except Exception:
        pass
    return None
