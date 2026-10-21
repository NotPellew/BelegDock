# Implementation Plan — Issue #43: Version surface and About screen (icon deferred)

## Scope

- In scope: „Über BelegDock“-Button im Desktop-Hauptfenster, modaler deutscher
  About-Dialog, Build-Revision im Windows-Freeze, Versions-Konsistenzprüfung.
- Out of scope: Anwendungssymbol (kein Asset freigegeben; Issue bleibt dafür
  offen), Push/PR, Setup-/Login-UI, Versionsänderung (`0.1.0.dev0` bleibt).

## Confirmed decisions

- Button tastaturerreichbar und unauffällig im Kopfbereich; funktioniert in
  breitem und schmalem Layout (Kopfbereich liegt außerhalb der Sektionen).
- Dialog zeigt Produktname, `belegdock.__version__`, kurze Build-Revision nur
  bei eingebetteter Revision, Lizenz „Apache License 2.0“ mit LICENSE-URL,
  Projekt-URL und 2–3 Sätze Datenschutz. Keine Pfade, Zugangsdaten oder
  Dokumentdaten. Buttons öffnen die URLs per `webbrowser`.
- Texte widgetfrei in `src/belegdock/build_info.py` (`build_info()`,
  `about_text()`); Tk nur in `DesktopApplication._show_about`.
- Freeze: `cmd_build` schreibt die Git-Revision als Datendatei
  `belegdock/build_revision.txt` (Env `BELEGDOCK_BUILD_REVISION_FILE`, Spec-
  `datas`); Quell-/Wheel-Installationen zeigen keine Revision.
- `version_mismatches()` in `packaging/build_windows.py` vergleicht Paket-,
  pyproject-, `artifact.json`-Version/Revision und eingebettete Revision;
  `check-artifact` schlägt bei Abweichung fehl.

## Tests (neu, vor Implementierung)

- `tests/app/test_about.py`: `build_info`/`about_text` ohne/mit Revision,
  Datenschutz-/Lizenz-/Projektangaben, keine Revisionszeile ohne Freeze,
  About-Dialog und URL-Buttons mit Fake-Widgets.
- `tests/app/test_version_consistency.py`: Übereinstimmung und jede
  Abweichungsart, reale Repo-Konsistenz, Spec-Verdrahtung, `--version`.
- Bestehende Tests unverändert; Desktop-Smoke öffnet/schließt den Dialog.

## Verification

- `uv run pytest tests/app -q`, `uv run ruff check .`, `uv run mypy src`,
  `uv run python scripts/replay_red.py --verify`
- Nativer Tk-Lauf mit Screenshot; Mutationsprobe an der Konsistenzprüfung.
