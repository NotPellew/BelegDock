# BelegDock

Eine lokale CLI zur ausdrücklichen Auswahl von Gmail-Anhängen und zur Übertragung
von Dokumenten an Lexware Office, ohne das Postfach zu verändern.

## Status

Früher Machbarkeitsstand, keine Produktionsfreigabe. Offline-Tests decken Auswahl,
Vorbereitung, Duplikate und unklare Sendeergebnisse ab. Live-Tests von Gmail bis
Lexware akzeptierten einfache PDFs, ZUGFeRD-PDFs und eigenständige XML-Dateien,
ohne Labels oder Originalnachrichten zu verändern. Die lokale Verhinderung erneuter
Übertragungen bestand für jedes Format; eine serverseitige Duplikatprüfung bestand
ebenfalls für das einfache PDF. Ein fehlerhaftes XML wurde abgelehnt (406), seine
korrigierte Kopie wurde akzeptiert (202). Diese Akzeptanz bestätigt weder die
Gültigkeit einer Rechnung noch den Abschluss der Buchhaltung. Dieselbe Live-Strecke
bestand unter nativem Windows mit dem gebauten Paket und Windows Credential Manager
für beide Konten. Eine manuelle Live-Abstimmung eines unterbrochenen Sendevorgangs
bestand ebenfalls: Der unterbrochene Prozess ließ das Dokument unklar; erst nachdem
die von der Bedienperson angegebenen Remote-Datei und der Beleg die Verknüpfung
bestätigt hatten und die heruntergeladenen Bytes dem Hash der vorbereiteten Datei
entsprachen, wurde das Dokument als gesendet gespeichert. Eine nicht passende
Remote-Datei und eine wiederholte Abstimmung schlugen fehl, ohne erneut zu senden
oder das Postfach zu verändern.

Python 3.12+; Windows- und Linux-Anwendungsprüfungen laufen in CI. Der separate
geschützte Entwickler-Launcher unterstützt derzeit nur Linux.

## Installieren und verbinden

Aus diesem Checkout mit `uv tool install .` installieren und anschließend
`belegdock --help` ausführen. Konto-Einrichtungsdateien und Dokumentdaten bleiben
außerhalb des Repositorys.

1. Ein Google-Cloud-Testprojekt erstellen, die Gmail API aktivieren und OAuth als
   External / Testing konfigurieren; das Gmail-Konto als Testnutzer eintragen. Eine
   Desktop-App-Client-ID erstellen und deren JSON außerhalb dieses Checkouts speichern.
2. `belegdock login-gmail --client /path/to/client.json` ausführen und die
   Browser-Anfrage bestätigen. Der einzige angeforderte Gmail-Bereich ist
   `gmail.readonly`.
3. Ein [Lexware-Testkonto](https://app.lexware.de/signup/app/trial) erstellen und
   in den [Einstellungen der Public API](https://app.lexware.de/addons/public-api)
   einen Schlüssel erzeugen. `belegdock login-lexware` ausführen und ihn an der
   verdeckten Eingabe eingeben. Das Speichern eines Schlüssels bestätigt nicht,
   dass Lexware ihn akzeptiert.

Anmeldedaten werden unter Windows im Credential Manager und unter Linux im Secret
Service gespeichert.
Ein nicht verfügbarer Speicher ist ein Fehler; es gibt keinen stillen Fallback auf
Klartext. Die Google-OAuth-Client-JSON ist Einrichtungsmaterial; Aktualisierungs-
und Zugriffstoken werden nur im Anmeldedatenspeicher des Betriebssystems abgelegt.
Siehe [Googles Einrichtungsanleitung](https://developers.google.com/workspace/gmail/api/quickstart/python)
und [Lexwares API-Anleitung](https://developers.lexware.io/cookbooks/public-api/).

## Auswählen und übertragen

Für das erste Experiment ein eigenes Label mit synthetischen Dokumenten verwenden.
Die Befehle erzeugen JSON; eine Kandidaten-ID aus `scan` und anschließend einen
Hash aus `stage` übernehmen:

```sh
belegdock scan --label "Rechnungen"
belegdock stage --label "Rechnungen" --select "MESSAGE_ID:PART_ID"
belegdock documents
belegdock refresh
belegdock upload SHA256_HASH
```

Für die lokale Desktop-Ansicht desselben Ablaufs `belegdock desktop` ausführen.
Ein Gmail-Label auswählen, Anhänge nach Dateiname und Größe markieren und
„Ausgewählte Dokumente vorbereiten“ wählen. Das Vorbereiten speichert die
ausgewählten Dateien lokal und sendet nichts an Lexware. „Dokumente prüfen“ zeigt
eine kompakte Zeile pro vorbereitetem Dokument; die Auswahl einer Zeile zeigt die
vollständigen Lexware-Datei- und Beleg-IDs mit Kopieraktionen. Das Senden eines
vorbereiteten Dokuments erfordert eine Bestätigung. Die Desktop-Oberfläche führt
nur von der Bedienperson ausgelöste Vorgänge einzeln aus; sie fragt nicht im
Hintergrund ab, wiederholt nichts automatisch und bietet keine Abstimmung unklarer
Sendeergebnisse an. Wenn ein Dokument `uploading` oder `uncertain` ist, die
CLI-Wiederherstellungsanleitung unten verwenden. Python muss mit Tk-Unterstützung
installiert sein; bei fehlender optionaler Desktop-Abhängigkeit wird ein klarer
Fehler ausgegeben.

`--select` für weitere Anhänge wiederholen. Das Scannen sendet nichts; Gmail-
Nachrichtenantworten können Inline-Anhangsdaten enthalten, aber nur ausdrücklich
ausgewählte Anhänge werden vorbereitet. PDF/XML-Dateinamen kennzeichnen
Kandidaten, sind aber keine geprüften Rechnungen. Die konservative Größenbegrenzung
beträgt 5.000.000 Bytes pro Anhang. Bytegleiche Duplikate teilen sich einen Blob,
während jedes Quellvorkommen erhalten bleibt.

`refresh` liest das Lexware-Profil und beide Archivzustände der paginierten
Beleginventur und prüft anschließend die Dateiverknüpfungen und Hashes der aktuellen
Dateibytes jedes Belegs. Der Cache wird erst nach einer vollständigen Aktualisierung
ersetzt; unveränderte Dateimetadaten werden wiederverwendet. `upload` aktualisiert
immer und prüft vor dem Senden eines POST eine positive Datei-/Belegübereinstimmung.
Netzwerk-GETs werden bei HTTP-429-Antworten höchstens fünfmal versucht; Remote-
Dateien werden mit einer Grenze von 5.000.000 Bytes gestreamt.

Daten liegen standardmäßig im Anwendungsdatenverzeichnis des Betriebssystems
(`BelegDock`) mit `state.sqlite3` und `blobs/`. Vor dem Befehl überschreiben, zum
Beispiel mit `belegdock --data-dir /path/to/test-data documents`. Das gesamte
Verzeichnis für die Wiederherstellung aufbewahren und sichern, solange kein Befehl
läuft. Es werden keine Dateien automatisch gelöscht. Nach dem Upgrade eines
vorhandenen Zustands einmal `documents` ausführen, bevor parallele BelegDock-Befehle
gestartet werden. Das lokale Schema-Upgrade kann einen parallelen ersten Start
ablehnen und stellt keine Remote-Anfrage.

BelegDock initialisiert ein fehlendes oder leeres Datenverzeichnis. Wenn ein
Verzeichnis bereits Vorbereitungsartefakte enthält, aber `state.sqlite3` fehlt oder
leer ist, wird die Initialisierung abgelehnt, damit eine unvollständige
Wiederherstellung keinen lokalen Zustand verdeckt. `documents` prüft jeden
gespeicherten Blob und meldet `localIntegrity` als `ok`, `missing`, `corrupt` oder
`unreadable`; ein beschädigtes Ergebnis führt zu einem Fehlerstatus mit Hinweis zur
Wiederherstellung.

Ein bestätigter Upload-Hash wird nicht erneut gesendet. Eine dokumentierte
Lexware-Ablehnung (HTTP 400 oder 406) wird als `rejected` gespeichert; das Dokument
korrigieren und seine neuen Bytes vorbereiten. `uploading` und `uncertain` blockieren
einen weiteren Upload.

Wenn ein Prozess während des Sendens beendet wurde, `belegdock recover-upload SHA256_HASH`
ausführen. Der Befehl ändert nur einen lokalen Datensatz mit `uploading`, dessen
prozessbezogene Betriebssystem-Sperre nicht mehr gehalten wird, zu `uncertain`.
Zuvor werden die vorbereiteten Bytes geprüft; beschädigte oder nicht verfügbare Bytes
lassen den Status `uploading` bestehen und geben Hinweise zur Wiederherstellung aus.
Der Befehl sendet nichts und erlaubt keinen erneuten Upload.

Zuerst Lexware prüfen. Wenn das passende Dokument gefunden wurde, ausführen:

```sh
belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID
```

Der Befehl lädt die Remote-Datei und den Beleg herunter, verlangt, dass der Beleg
auf die Datei verweist, und speichert die IDs nur, wenn die heruntergeladenen Bytes
dem Hash der vorbereiteten Datei entsprechen. Eine fehlgeschlagene Abstimmung lässt
das Dokument `uncertain`. Den Zustand nicht zurücksetzen und die Vorbereitung nicht
löschen, um einen erneuten Versuch zu erzwingen; ein erneuter Versuch nach einem
unklaren Ergebnis bleibt zurückgestellt, weil dieser begrenzte Ablauf das Fehlen
auf der Remote-Seite nicht beweisen kann.

## Windows-Installation (Pilot)

Für den Firmen-Pilot steht eine fertige Windows-Installation ohne
Administratorrechte bereit; ein Quellcheckout, `uv` oder eine eigene virtuelle
Umgebung sind nicht nötig.

1. `BelegDock-0.1.0.dev0-windows-x64-setup.exe` aus den CI-Artefakten des
   `windows-installer`-Laufs herunterladen und die SHA-256-Prüfsumme mit
   `artifact.json` vergleichen.
2. Die Setup-Datei starten. Der deutsche Assistent installiert nach
   `%LOCALAPPDATA%\Programs\BelegDock`, trägt das Verzeichnis in den
   Benutzer-PATH ein und legt einen Startmenü-Eintrag „BelegDock“ an. Eine
   Administratorabfrage entfällt; Windows SmartScreen warnt, weil das Paket
   nicht signiert ist.
3. In einer neuen Eingabeaufforderung einmalig anmelden:

```sh
belegdock login-gmail --client C:\Pfad\zum\client.json
belegdock login-lexware
```

4. Über das Startmenü „BelegDock“ oder mit `belegdock desktop` starten.

Daten liegen unter `%LOCALAPPDATA%\BelegDock` mit `state.sqlite3` und `blobs/`
außerhalb der Installation; sie bleiben bei einem Upgrade und bei der
Deinstallation erhalten. Zum Aktualisieren die neuere Setup-Datei über die
vorhandene Installation ausführen und danach einmal `belegdock documents`
starten. Zum Deinstallieren „BelegDock“ in „Apps und Features“ auswählen;
Installationsverzeichnis, PATH-Eintrag und Startmenü-Verknüpfung werden entfernt,
`%LOCALAPPDATA%\BelegDock` wird nicht gelöscht. Für die endgültige Entfernung
dieses Verzeichnis bewusst selbst löschen.

Unterstützt sind Windows 10 22H2 (10.0.19045) und Windows 11, nur x64; ARM64 und
ältere Windows-Versionen lehnt der Installer ab. Die Anleitung für den Pilot liegt
dem Paket als `README-Windows.txt` bei. Das Paket enthält kein eigenes
Anwendungssymbol und ist nicht signiert. Die Offline-Paketprüfung testet weder
Gmail- noch Lexware-Konnektivität; ein separater Windows-Test des gebauten
Python-Pakets bestand mit Windows Credential Manager, dem Live-Scannen und
Vorbereiten in Gmail sowie dem Senden und der Ablehnungsbehandlung in Lexware.
Dieser gefrorene Installer wurde noch nicht live gegen Gmail und Lexware geprüft;
dafür ist ein eigener Pilotlauf mit Testkonto und Testdaten nötig.

## Windows-Test-Fixtures und Gmail-Pilotversand

Für den Windows-Pilot können synthetische PDF/XML-Dokumente außerhalb dieses
Checkouts erzeugt werden. Die Generator- und Versandwerkzeuge gehören nicht zur
installierten Anwendung und werden nicht in den Windows-Installer aufgenommen.
Die Vorlagen enthalten nur synthetische Beispieldaten.

Im Checkout mit uv eine neue, noch nicht verwendete Ausgabe anlegen:

```sh
uv run python scripts/generate_pilot_fixtures.py generate \
  --output C:/Temp/BelegDockPilot/pilot-001 \
  --run-id pilot-001
uv run python scripts/generate_pilot_fixtures.py validate \
  --batch C:/Temp/BelegDockPilot/pilot-001
```

Die Ausgabe enthält einen Manifesteintrag mit relativen Dateinamen, Größen und
SHA-256-Hashes. Sie erzeugt einen frischen PDF-Hash, eine bytegleiche
Dublette, ein absichtlich fehlerhaftes XML und eine korrigierte XML-Version.
Die Ausgabe darf nicht im Repository liegen und darf nicht überschrieben werden.

Der Versand ist ein eigener, expliziter Testschritt. Dafür ist ein separates
Google-OAuth-Client-JSON außerhalb des Checkouts und ein dediziertes
Test-Gmail-Konto mit einem bereits vorhandenen Testlabel erforderlich. Der
Versand verwendet einen eigenen Credential-Manager-Eintrag `BelegDock-Pilot`
und die Scopes `gmail.send` und `gmail.modify`; die BelegDock-Anmeldung bleibt
unverändert auf `gmail.readonly`.

```sh
uv run python scripts/pilot_mail.py login \
  --client C:/Secure/pilot-client.json \
  --expected-account pilot@example.test
uv run python scripts/pilot_mail.py inspect \
  --manifest C:/Temp/BelegDockPilot/pilot-001/manifest.json
uv run python scripts/pilot_mail.py send \
  --manifest C:/Temp/BelegDockPilot/pilot-001/manifest.json \
  --expected-account pilot@example.test \
  --label BelegDock-Pilot \
  --execute
```

Ohne `--execute` wird nur ein lokaler Trockenlauf ausgeführt. Mit `--execute`
erstellt der Versand genau eine neue Nachricht im angegebenen Testkonto und
wendet das Label nur auf diese Nachricht an. Es werden keine vorhandenen
Nachrichten oder Labels verändert. Ein unbekannter Konto-Account, ein fehlendes
Label, ein unklares Sendenergebnis oder ein fehlgeschlagenes Label-Update
führt zu einemAbbruch ohne automatischen Wiederholungsversuch. Der
Zustellstatus wird in einem Zustellnachweis außerhalb des Checkouts
dokumentiert. Die Statuswerte unterscheiden zwischen `send_rejected`
(definitiv nicht gesendet), `send_uncertain` (Remote-Ergebnis unbekannt) und
`sent_label_unknown` (gesendet, Label-Ergebnis unbekannt). Ein bereits
vorhandener Zustellnachweis sperrt weitere Zustellversuche für denselben
Batch.

Die Werkzeuge erzeugen und versenden nur Testdaten. Sie führen keinen
Lexware-Upload und keine Wiederherstellung aus. ZUGFeRD-Dokumente sind in der
ersten Version nicht enthalten, weil dafür eine separat geprüfte Vorlage und
ein erneuter Live-Nachweis erforderlich sind.

## Entwicklung

- [AGENTS.md](AGENTS.md): Arbeitsablauf, unveränderliche Tests, Entwicklungsbefehle und Isolation.
- [Architektur](docs/arc42.md): Geltungsbereich, Entscheidungen, Grenzen und offene Arbeit.
- [Feature-Formular](https://github.com/NotPellew/BelegDock/issues/new?template=feature.yml):
  Arbeit in einem Issue präzisieren; die Liefernachweise bleiben im zugehörigen PR.

Öffentliches Gmail-Onboarding, Zeitplanung und Dokumentarchivierung bleiben zurückgestellt.
Lizenziert unter der Apache License 2.0; siehe [LICENSE](LICENSE).
