import argparse
import getpass
import json
import os
import re
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, NoReturn

from . import __version__, accounts
from .classification import classify_candidate_mapping
from .integrations import GmailAdapter, LexwareAdapter
from .desktop import DesktopUnavailableError, run_desktop
from .service import refresh_remote_inventory as _refresh_remote_inventory
from .workflow import DocumentRejected, LocalIntegrityError, Store, TransferActiveError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
LOCAL_INTEGRITY_FAILED = "local_integrity_failed"

QUICK_START = """Schnellstart:
  belegdock login-gmail --client CLIENT_JSON
  belegdock login-lexware
  belegdock scan --label LABEL
  belegdock stage --label LABEL --select MESSAGE_ID:PART_ID
  belegdock documents
  belegdock status
  belegdock refresh
  belegdock upload SHA256_HASH

Wiederherstellung nach einem unterbrochenen Sendevorgang:
  belegdock recover-upload SHA256_HASH
  belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID
  Ein unklares Sendeergebnis wird nie automatisch erneut gesendet."""


class GermanArgumentParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "Aufruf:", 1)

    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "Aufruf:", 1)
            .replace("positional arguments:", "Positionsargumente:", 1)
            .replace("options:", "Optionen:", 1)
            .replace("show this help message and exit", "Diese Hilfe anzeigen und beenden", 1)
        )

    def error(self, message: str) -> NoReturn:
        translated = (
            message.replace("the following arguments are required:", "Folgende Argumente sind erforderlich:")
            .replace("expected one argument", "Ein Argument wird erwartet")
            .replace("invalid choice:", "Ungültige Auswahl:")
            .replace(" (choose from ", " (mögliche Werte: ")
            .replace("unrecognized arguments:", "Unbekannte Argumente:")
            .replace("ignored explicit argument", "Explizites Argument")
            .replace("argument command:", "Argument Befehl:")
            .replace("argument ", "Argument ")
        )
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: Fehler: {translated}\n")


def build_gmail(credentials: Any) -> Any:
    return import_module("googleapiclient.discovery").build(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )


def connect_gmail(client_path: Path) -> str:
    accounts.native_backend()
    flow = import_module("google_auth_oauthlib.flow").InstalledAppFlow.from_client_secrets_file(
        str(client_path), SCOPES
    )
    credentials = flow.run_local_server(port=0)
    service = build_gmail(credentials)
    account = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    accounts.save_secret("gmail", credentials.to_json())
    return account


def gmail_client() -> tuple[str, GmailAdapter]:
    info = json.loads(accounts.load_secret("gmail"))
    credentials = import_module("google.oauth2.credentials").Credentials.from_authorized_user_info(
        info, SCOPES
    )
    if not credentials.valid:
        credentials.refresh(import_module("google.auth.transport.requests").Request())
        accounts.save_secret("gmail", credentials.to_json())
    service = build_gmail(credentials)
    account = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    return account, GmailAdapter(service)


def lexware_client() -> LexwareAdapter:
    client = import_module("httpx").Client(
        headers={"Authorization": "Bearer " + accounts.load_secret("lexware"), "Accept": "application/json"},
        follow_redirects=False,
    )
    return LexwareAdapter(client)


def default_data_dir() -> Path:
    return Path(import_module("platformdirs").user_data_dir("BelegDock", appauthor=False))


def recover_upload_command(digest: str) -> str:
    return f"belegdock recover-upload {digest}"


def reconcile_command(digest: str) -> str:
    return f"belegdock reconcile {digest} --file-id FILE_ID --voucher-id VOUCHER_ID"


def transfer_active_wait_message(digest: str) -> str:
    return f"Ein anderer Vorgang ist aktiv für {digest}; warte, bis er beendet ist. Nicht erneut senden."


def recovery_state_unavailable_message(digest: str) -> str:
    return (
        f"Wiederherstellungsstatus für {digest} konnte nicht geprüft werden; den Upload nicht erneut senden. "
        "Stelle den lokalen Zustand wieder her oder prüfe ihn, bevor du einen Wiederherstellungsbefehl wählst."
    )


def local_integrity_restore_message() -> str:
    return (
        "Lokale Dokumentintegrität fehlgeschlagen; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. "
        "Wiederherstellung ist erforderlich."
    )


def format_damaged_documents_message(documents: list[dict[str, Any]]) -> str:
    damaged = sorted(
        [item for item in documents if item.get("localIntegrity") != "ok"],
        key=lambda item: (str(item.get("filename") or ""), str(item.get("hash") or "")),
    )
    if not damaged:
        return local_integrity_restore_message()
    lines = ["Lokale Dokumentintegrität fehlgeschlagen; folgende Dateien sind beschädigt oder fehlen:"]
    status_map = {
        "missing": "fehlt (missing)",
        "corrupt": "ist beschädigt (corrupt)",
        "unreadable": "ist nicht lesbar (unreadable)",
    }
    for item in damaged[:5]:
        filename = item.get("filename") or "Dokument"
        digest = item.get("hash") or ""
        integrity = item.get("localIntegrity") or "beschädigt"
        status_desc = status_map.get(integrity, f"ist {integrity}")
        lines.append(f"  - {filename} ({digest}): Blob {status_desc}")
    if len(damaged) > 5:
        remaining = len(damaged) - 5
        lines.append(f"  ... und {remaining} weitere beschädigte Dokumente")
    lines.append(local_integrity_restore_message())
    return "\n".join(lines)


def single_document_integrity_failure_message(data_dir: Path, digest: str) -> str:
    filename = "Dokument"
    integrity = "beschädigt"
    try:
        store = Store(data_dir)
        for doc in store.list_documents(digest):
            if doc.get("hash") == digest:
                filename = doc.get("filename") or filename
                integrity = doc.get("localIntegrity") or integrity
                break
    except Exception:
        pass
    status_map = {
        "missing": "fehlt (missing)",
        "corrupt": "ist beschädigt (corrupt)",
        "unreadable": "ist nicht lesbar (unreadable)",
    }
    status_desc = status_map.get(integrity, f"ist {integrity}")
    return (
        f"Lokale Dokumentintegrität fehlgeschlagen für {filename} ({digest}): Blob {status_desc}. "
        "Lokale Daten sind nicht verfügbar; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. "
        + local_integrity_restore_message()
    )


def empty_status_summary(data_dir: Path) -> dict[str, Any]:
    return {
        "dataDir": str(data_dir),
        "totalDocuments": 0,
        "counts": {
            "staged": 0,
            "uploading": 0,
            "uncertain": 0,
            "uploaded": 0,
            "rejected": 0,
        },
        "integrityIssues": 0,
        "remoteRefresh": {
            "status": None,
            "refreshedAt": None,
            "organizationId": None,
        },
        "nextActions": [],
        "initialized": False,
    }


def format_status_human(summary: dict[str, Any]) -> str:
    lines = [
        "BelegDock-Status:",
        f"  Datenverzeichnis: {summary['dataDir']}",
        f"  Dokumente gesamt: {summary['totalDocuments']}",
        f"    Vorbereitet (staged):      {summary['counts']['staged']}",
        f"    Wird gesendet (uploading): {summary['counts']['uploading']}",
        f"    Unklar (uncertain):        {summary['counts']['uncertain']}",
        f"    Gesendet (uploaded):       {summary['counts']['uploaded']}",
        f"    Abgelehnt (rejected):      {summary['counts']['rejected']}",
    ]
    if summary.get("integrityIssues", 0) > 0:
        lines.append(
            f"  Beschädigte lokale Dokumente: {summary['integrityIssues']} "
            "(Dateien fehlen oder sind beschädigt; siehe README.md für Wiederherstellung)"
        )
    refresh = summary.get("remoteRefresh") or {}
    if refresh.get("status"):
        status_text = "Erfolg" if refresh["status"] == "success" else "Fehlgeschlagen"
        time_text = f" ({refresh['refreshedAt']})" if refresh.get("refreshedAt") else ""
        lines.append(f"  Letzte Lexware-Aktualisierung: {status_text}{time_text}")
    elif summary.get("initialized", True):
        lines.append("  Letzte Lexware-Aktualisierung: Noch keine Aktualisierung durchgeführt")

    next_actions = summary.get("nextActions") or []
    if next_actions:
        lines.append("")
        lines.append("Nächste empfohlene Schritte:")
        by_status: dict[str, list[dict[str, str]]] = {}
        for action in next_actions:
            by_status.setdefault(action["status"], []).append(action)

        status_labels = {
            "uncertain": "unklar",
            "uploading": "wird gesendet",
            "staged": "vorbereitet",
        }
        for status_key in ("uncertain", "uploading", "staged"):
            items = by_status.get(status_key, [])
            if not items:
                continue
            for action in items[:5]:
                lines.append(f"  [{status_labels.get(status_key, status_key)}] {action['command']}")
            if len(items) > 5:
                remaining = len(items) - 5
                label_plural = {
                    "uncertain": "unklare",
                    "uploading": "unterbrochene",
                    "staged": "vorbereitete",
                }.get(status_key, status_key)
                lines.append(f"  ... und {remaining} weitere {label_plural} Dokumente")
    return "\n".join(lines)


def valid_document_hash(digest: str) -> bool:
    try:
        Store._validate_digest(digest)
    except ValueError:
        return False
    return True


def document_status(data_dir: Path, digest: str) -> tuple[str | None, bool]:
    try:
        for document in Store(data_dir).list_documents(digest):
            if document.get("hash") == digest:
                status = document.get("status")
                if document.get("localIntegrity") != "ok":
                    return LOCAL_INTEGRITY_FAILED, True
                return (status if isinstance(status, str) else None), True
    except Exception:
        return None, False
    return None, True


def is_verbose(args: argparse.Namespace) -> bool:
    if getattr(args, "verbose", False):
        return True
    return os.environ.get("BELEGDOCK_VERBOSE", "").strip().lower() in {"1", "true", "yes"}


def format_verbose_exception(error: BaseException) -> str:
    message = str(error).replace("\n", " ").strip()
    message = re.sub(r"(Bearer\s+)[^\s'\"]+", r"\1***", message, flags=re.IGNORECASE)
    for name in ("lexware", "gmail"):
        try:
            secret = accounts.load_secret(name)
            if secret and secret in message:
                message = message.replace(secret, "***")
        except Exception:
            pass
    if message:
        return f"Fehlerdetails: {type(error).__name__}: {message}"
    return f"Fehlerdetails: {type(error).__name__}"


def make_parser() -> argparse.ArgumentParser:
    parser = GermanArgumentParser(
        prog="belegdock",
        description="BelegDock-CLI für lokale Dokumentübertragungsexperimente in einer frühen Entwicklungsphase.",
        epilog=QUICK_START,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="Diese Hilfe anzeigen und beenden")
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
        help="Versionsnummer anzeigen und beenden",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Ausführliche Fehlerdetails auf stderr ausgeben",
    )
    parser.add_argument("--data-dir", type=Path, help="Lokales Staging- und SQLite-Verzeichnis überschreiben")
    parser._optionals.title = "Optionen"
    commands = parser.add_subparsers(dest="command", title="Befehle", parser_class=GermanArgumentParser)

    def add_command(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        command = commands.add_parser(
            name,
            add_help=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            **kwargs,
        )
        command.add_argument("-h", "--help", action="help", help="Diese Hilfe anzeigen und beenden")
        command.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Ausführliche Fehlerdetails auf stderr ausgeben",
        )
        command._optionals.title = "Optionen"
        return command

    login = add_command("login-gmail", help="Gmail-Lesezugriff über Browser-OAuth verbinden")
    login.add_argument(
        "--client", type=Path, required=True, help="Desktop-OAuth-Client-JSON außerhalb des Checkouts"
    )
    add_command("login-lexware", help="API-Schlüssel über eine verdeckte Eingabe speichern")
    for name in ("scan", "stage"):
        command = add_command(
            name,
            help="Kandidaten auflisten" if name == "scan" else "Ausgewählte Anhänge vorbereiten",
        )
        command.add_argument("--label", required=True)
        if name == "stage":
            command.add_argument(
                "--select",
                action="append",
                required=True,
                help="Kandidaten-ID aus scan; für mehrere Auswahl wiederholen",
            )
    add_command("documents", help="Lokale Dokumente und Übertragungsstatus auflisten")
    status_cmd = add_command("status", help="Lokalen Übertragungsstatus und nächste Schritte zusammenfassen")
    status_cmd.add_argument("--json", action="store_true", help="Ausgabe im JSON-Format erzeugen")
    add_command("desktop", help="Lokale Desktop-Oberfläche für die Dokumentübertragung öffnen")
    add_command("refresh", help="Lokales Lexware-Dateiinventar aktualisieren")
    upload = add_command("upload", help="Einen vorbereiteten Hash ausdrücklich senden")
    upload.add_argument("hash")
    recover = add_command("recover-upload", help="Unterbrochenes lokales Senden als unklar markieren")
    recover.add_argument("hash")
    reconcile = add_command("reconcile", help="Bekanntes Remote-Dokument vor dem Speichern prüfen")
    reconcile.add_argument("hash")
    reconcile.add_argument("--file-id", required=True)
    reconcile.add_argument("--voucher-id", required=True)
    return parser


def dispatch(args: argparse.Namespace) -> Any:
    if args.command == "desktop":
        return run_desktop(args.data_dir)
    if args.command == "login-gmail":
        return {"account": connect_gmail(args.client)}
    if args.command == "login-lexware":
        accounts.native_backend()
        accounts.save_secret("lexware", getpass.getpass("Lexware-API-Schlüssel: "))
        return {"connected": "lexware"}
    if args.command in ("scan", "stage"):
        account, gmail = gmail_client()
        candidates = gmail.candidates(args.label)
        if args.command == "scan":
            return [classify_candidate_mapping(gmail, candidate) for candidate in candidates]
        selected = set(args.select)
        if selected - {item["id"] for item in candidates}:
            raise ValueError("Unknown selection; scan the label again.")
    data_dir = args.data_dir or default_data_dir()
    if args.command == "status":
        state_db = data_dir / "state.sqlite3"
        if not data_dir.exists() or (not state_db.exists() and not any(data_dir.iterdir())):
            return empty_status_summary(data_dir)
        return Store(data_dir).status_summary()
    store = Store(data_dir)
    if args.command == "documents":
        return store.list_documents()
    if args.command == "refresh":
        remote = lexware_client()
        try:
            return refresh_remote_inventory(store, remote)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    if args.command == "stage":
        return [store.stage(account, item["message_id"], item["part_id"], item["filename"], gmail.fetch(item))
                for item in candidates if item["id"] in selected]
    if args.command == "upload":
        remote = lexware_client()
        try:
            client = getattr(remote, "client", None)
            def refresh() -> dict[str, Any]:
                return refresh_remote_inventory(store, remote)
            verify = getattr(remote, "verify_existing", None)
            return store.upload(args.hash, remote.upload, refresh, verify=verify if callable(verify) else None)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    if args.command == "recover-upload":
        return store.recover_upload(args.hash)
    if args.command == "reconcile":
        remote = lexware_client()
        try:
            return store.reconcile(args.hash, args.file_id, args.voucher_id, remote.verify_existing)
        finally:
            client = getattr(remote, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    raise ValueError("Choose a command from --help.")


def refresh_remote_inventory(store: Store, remote: LexwareAdapter) -> dict[str, Any]:
    return _refresh_remote_inventory(store, remote)


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    if args.command is None:
        parser.print_help()
        return 0
    try:
        result = dispatch(args)
        if args.command == "status":
            if getattr(args, "json", False):
                print(json.dumps(result, ensure_ascii=True))
            else:
                print(format_status_human(result))
        elif args.command != "desktop":
            print(json.dumps(result, ensure_ascii=True))
        if args.command == "scan" and len(result) == 0:
            print(
                f"Keine PDF- oder XML-Anhänge im Gmail-Label '{args.label}' gefunden.",
                file=sys.stderr,
            )
        if args.command == "documents" and any(
            item.get("localIntegrity") != "ok" for item in result
        ):
            print(
                format_damaged_documents_message(result),
                file=sys.stderr,
            )
            return 1
        return 0
    except DocumentRejected as error:
        print(
            f"Lexware hat den Upload abgelehnt (HTTP {error.status_code}); korrigiere das Dokument und bereite die neuen Bytes vor.",
            file=sys.stderr,
        )
        if is_verbose(args):
            print(format_verbose_exception(error), file=sys.stderr)
        return 1
    except LocalIntegrityError as error:
        if hasattr(args, "hash") and valid_document_hash(args.hash):
            print(
                single_document_integrity_failure_message(args.data_dir or default_data_dir(), args.hash),
                file=sys.stderr,
            )
        else:
            print(
                "Lokale Daten sind nicht verfügbar; stelle state.sqlite3 und blobs aus einer konsistenten Sicherung wieder her. "
                "Wiederherstellung ist erforderlich.",
                file=sys.stderr,
            )
        if is_verbose(args):
            print(format_verbose_exception(error), file=sys.stderr)
        return 1
    except TransferActiveError as error:
        if args.command == "recover-upload":
            print(
                "Wiederherstellung fehlgeschlagen; ein aktives Senden kann nicht wiederhergestellt werden. "
                "Warte, bis es beendet ist. Wenn der Prozess vor der Ergebnismeldung beendet wurde, "
                f"führe '{recover_upload_command(args.hash)}' aus.",
                file=sys.stderr,
            )
        else:
            print(transfer_active_wait_message(args.hash), file=sys.stderr)
        if is_verbose(args):
            print(format_verbose_exception(error), file=sys.stderr)
        return 1
    except DesktopUnavailableError as error:
        print(
            "Desktop-Oberfläche ist nicht verfügbar; installiere Python-Tk-Unterstützung "
            "und starte „belegdock desktop“ erneut.",
            file=sys.stderr,
        )
        if is_verbose(args):
            print(format_verbose_exception(error), file=sys.stderr)
        return 1
    except Exception as error:
        if args.command == "stage":
            message = "Vorbereiten fehlgeschlagen; prüfe Auswahl, Verbindung, Dateigröße und lokalen Speicher."
        elif args.command == "upload":
            if not valid_document_hash(args.hash):
                message = "Ungültiger Dokument-Hash; führe 'belegdock documents' aus und kopiere einen SHA-256-Hash."
            else:
                status, status_available = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == LOCAL_INTEGRITY_FAILED:
                    message = single_document_integrity_failure_message(args.data_dir or default_data_dir(), args.hash)
                elif not status_available:
                    message = (
                        f"Sendeergebnis für {args.hash} konnte nicht geprüft werden; nicht erneut senden. "
                        "Prüfe den lokalen Zustand und Lexware, bevor du einen Wiederherstellungsbefehl wählst."
                    )
                elif status == "rejected":
                    message = "Dokument wurde abgelehnt; korrigiere es und bereite neue Bytes vor."
                elif status == "uploaded":
                    message = (
                        f"Upload für {args.hash} ist bereits gespeichert; nicht erneut senden. Führe "
                        "'belegdock documents' aus, um den lokalen Zustand zu prüfen."
                    )
                elif status == "uncertain":
                    message = (
                        f"Sendeergebnis für {args.hash} ist unklar; nicht erneut senden. Prüfe Lexware und führe "
                        f"anschließend '{reconcile_command(args.hash)}' aus."
                    )
                elif status == "uploading":
                    message = (
                        f"Senden für {args.hash} ist bereits aktiv; nicht erneut senden. Wenn der Prozess vor der "
                        f"Ergebnismeldung beendet wurde, führe '{recover_upload_command(args.hash)}' aus."
                    )
                else:
                    message = "Senden ist vor der Übertragung fehlgeschlagen; behebe das Problem und versuche es erneut."
        elif args.command == "recover-upload":
            if not valid_document_hash(args.hash):
                message = "Ungültiger Dokument-Hash; führe 'belegdock documents' aus und kopiere einen SHA-256-Hash."
            else:
                status, status_available = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == LOCAL_INTEGRITY_FAILED:
                    message = single_document_integrity_failure_message(args.data_dir or default_data_dir(), args.hash)
                elif not status_available:
                    message = recovery_state_unavailable_message(args.hash)
                elif status == "uncertain":
                    message = (
                        f"Wiederherstellung ist nicht erforderlich; das Ergebnis für {args.hash} ist bereits unklar; "
                        f"nicht erneut senden. Prüfe Lexware und führe anschließend '{reconcile_command(args.hash)}' aus."
                    )
                elif status == "uploading":
                    message = (
                        "Wiederherstellung fehlgeschlagen; ein aktives Senden kann nicht wiederhergestellt werden. "
                        "Warte, bis es beendet ist. Wenn der Prozess vor der Ergebnismeldung beendet wurde, "
                        f"führe '{recover_upload_command(args.hash)}' aus."
                    )
                else:
                    message = "Wiederherstellung wurde nicht gestartet; nur ein unterbrochenes Senden kann "
                    message += "wiederhergestellt werden. Prüfe 'belegdock documents'."
        elif args.command == "reconcile":
            if not valid_document_hash(args.hash):
                message = "Ungültiger Dokument-Hash; führe 'belegdock documents' aus und kopiere einen SHA-256-Hash."
            else:
                status, status_available = document_status(args.data_dir or default_data_dir(), args.hash)
                if status == LOCAL_INTEGRITY_FAILED:
                    message = single_document_integrity_failure_message(args.data_dir or default_data_dir(), args.hash)
                elif not status_available:
                    message = recovery_state_unavailable_message(args.hash)
                elif status == "uncertain":
                    message = (
                        f"Abstimmung für {args.hash} fehlgeschlagen; das Dokument bleibt unklar; nicht erneut senden. "
                        f"Prüfe Lexware und führe anschließend '{reconcile_command(args.hash)}' aus."
                    )
                elif status == "staged":
                    message = (
                        f"Abstimmung wurde nicht gestartet; das Dokument ist noch vorbereitet. Zum ausdrücklichen "
                        f"Senden führe 'belegdock upload {args.hash}' aus."
                    )
                elif status == "uploading":
                    message = (
                        "Abstimmung ist nicht möglich, solange ein Senden aktiv ist. Wenn der Prozess vor der "
                        f"Ergebnismeldung beendet wurde, führe '{recover_upload_command(args.hash)}' aus."
                    )
                else:
                    message = "Abstimmung wurde nicht gestartet; nur ein unklarer Upload kann abgestimmt werden. "
                    message += "Prüfe 'belegdock documents'."
        elif args.command.startswith("login"):
            message = "Verbindung fehlgeschlagen; prüfe den nativen Anmeldedatenspeicher und die Konto-/Client-Einrichtung."
        elif args.command == "desktop":
            message = "Desktop-Vorgang fehlgeschlagen; prüfe die Python-Tk-Unterstützung und die Kontoeinrichtung."
        else:
            message = "Vorgang fehlgeschlagen; prüfe Kontoverbindung, Label und lokalen Speicher."
        print(message, file=sys.stderr)
        if is_verbose(args):
            print(format_verbose_exception(error), file=sys.stderr)
        return 1
