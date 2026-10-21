# Implementation Plan — Issue #39: Sign the Windows installer

## Scope

- In scope: SignPath-Foundation-Signierung der Setup-Datei im Release-Workflow,
  Signaturprüfung unter Windows, Signatur-Metadaten in `artifact.json`, Dokumentation.
- Out of scope: Signieren der inneren Programmdateien (SignPath kann nicht in eine
  Inno-Setup-Datei hinein signieren; Folgearbeit), Anwendungssymbol, öffentliches Release.

## Confirmed decisions

- Zertifikat: SignPath Foundation über SignPath.io. Aktivierung allein durch
  Repository-Konfiguration; ohne `SIGNPATH_ORGANIZATION_ID` bleibt das Release wie bisher
  unsigniert. Ist sie gesetzt, ist Signierung zwingend und schlägt geschlossen fehl.
- Workflow: `build` lädt die unsignierte Setup-Datei als eigenes Artefakt hoch
  (`unsigned-setup`); `sign` reicht sie per `signpath/github-action-submit-signing-request@v3`
  ein, prüft die Signatur (`Status` Valid, Signaturgeber enthält den erwarteten Namen,
  Zeitstempel vorhanden), ersetzt die Datei in den Release-Assets und schreibt
  `signature` in `artifact.json` (`packaging/build_windows.py apply-signature`);
  `publish` läuft nur nach `sign` erfolgreich oder bei nicht konfigurierter Signierung
  übersprungen und veröffentlicht dann den signierten Satz.
- `signature` in `artifact.json`: `expected_signer`, `subject`, `thumbprint`,
  `timestamper` (Zertifikat der Zeitstempelstelle), `verified_at` (UTC-Zeitpunkt der
  Prüfung), `unsigned_sha256`. `sha256` und `size` beschreiben die signierte Datei.
- Referenz der Artefaktkonfiguration: `packaging/signpath/artifact-configuration.xml`.
- Nur GitHub-gehostete Runner. Das Token erscheint nur als `secrets.SIGNPATH_API_TOKEN`
  im Signieraufruf; Run-Skripte erhalten Werte über `env`.

## Repository configuration

| Name | Art | Pflicht | Inhalt |
| --- | --- | --- | --- |
| `SIGNPATH_ORGANIZATION_ID` | Actions variable | ja (Schalter) | Organisations-ID aus SignPath |
| `SIGNPATH_PROJECT_SLUG` | Actions variable | ja | Projekt-Slug |
| `SIGNPATH_SIGNING_POLICY_SLUG` | Actions variable | ja | z. B. `release-signing` |
| `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | Actions variable | nein | Slug, sonst Standard-Konfiguration |
| `SIGNPATH_EXPECTED_SIGNER` | Actions variable | nein | Standard `SignPath Foundation` |
| `SIGNPATH_API_TOKEN` | Actions secret | ja | CI-Benutzer-Token |

## Maintainer checklist

1. Erstes unsigniertes Release veröffentlichen (Voraussetzung der Bewerbung).
2. Unter <https://signpath.org/apply> die Freigabe beantragen (Open-Source-Projekt,
   Apache-2.0, Abschnitt „Code signing policy“ im README).
3. Mehrfaktor-Anmeldung für GitHub und SignPath aktivieren.
4. SignPath GitHub App installieren und GitHub.com als vertrauenswürdiges Build-System
   des Projekts einrichten.
5. In SignPath Projekt und Signing Policy anlegen (Release-Policy mit manueller
   Genehmigung) und `packaging/signpath/artifact-configuration.xml` als
   Artefaktkonfiguration einfügen.
6. Einen CI-Benutzer mit API-Token anlegen; Token als Secret `SIGNPATH_API_TOKEN`
   hinterlegen (nie im Repository oder Chat).
7. Die Actions-Variablen aus der Tabelle setzen.
8. Ein Release-Tag setzen, die Signieranfrage in SignPath genehmigen und die
   Veröffentlichung abwarten.
9. Auf Windows die Signatur prüfen (README „Code signing policy“) und
   Installation, Start und Deinstallation mit Signaturgeber, Zeitstempel und Hash
   dokumentieren; erst dann Issue #39 abschließen.

## Tests

- `tests/app/test_release_signing.py`: `apply_signature` und `apply-signature`
  (Hash, Größe, Metadaten, Ablehnung falscher Datei, unveränderter Zustand bei
  Ablehnung); Workflow-Struktur je Job (Bedingung, Aktion und Version,
  Artefakt-ID, Prüfschritt, `publish`-Bedingung, Berechtigungen, Geheimnisse, keine
  `${{ }}`-Interpolation in `run`).
- Nicht automatisiert prüfbar: die SignPath-Anfrage und `Get-AuthenticodeSignature`
  (nur in einem echten Release auf Windows).

## Offene Folgearbeit

- Innere Programmdateien (`BelegDock.exe`, `belegdock.exe`) vor dem Setup-Bau signieren.
- Echter Signaturzeitpunkt statt Prüfzeitpunkt, falls ein belastbarer Weg gefunden wird.
