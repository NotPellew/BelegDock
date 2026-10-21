BelegDock – Windows-Pilot
=========================

Unterstützt: Windows 10 22H2 (10.0.19045) und Windows 11, nur x64.
Für die Installation sind keine Administratorrechte nötig. ARM64 und ältere
Windows-Versionen werden nicht unterstützt.

Voraussetzungen
---------------
Windows 10 22H2 oder Windows 11 (x64), ein Gmail-Konto mit Lesezugriff und ein
Lexware-Office-API-Schlüssel. Python oder uv sind für die fertige Installation
nicht erforderlich. Die Setup-Datei stammt von der GitHub-Releases-Seite
(https://github.com/NotPellew/BelegDock/releases). Optional vorab: die
SHA-256-Prüfsumme der Setup-Datei mit dem Eintrag in SHA256SUMS.txt desselben
Release vergleichen.

Installation
------------
1. BelegDock-<Version>-windows-x64-setup.exe starten.
2. Die Windows-SmartScreen-Warnung erscheint, weil das Paket nicht signiert ist.
   Über "Weitere Informationen" und "Trotzdem ausführen" fortfahren.
3. Der deutsche Assistent installiert nach
   %LOCALAPPDATA%\Programs\BelegDock und trägt dieses Verzeichnis in den
   Benutzer-PATH ein. Ein Neustart der Eingabeaufforderung ist nötig, damit
   belegdock gefunden wird.
4. Der Startmenü-Eintrag "BelegDock" startet die Desktop-Oberfläche.

Erste Einrichtung (einmalig, in BelegDock selbst)
------------------------------------------------
Beim ersten Start von "BelegDock" (Startmenü) erscheint ein Einrichtungsfenster. Ein
Terminal ist nicht nötig. Das Fenster lässt sich nicht überspringen; Schließen beendet
BelegDock.

Schritt 1: Gmail verbinden
  - Sie haben vom Herausgeber eine Datei mit der Endung .json erhalten (die
    "OAuth-Client-Datei"). Sie enthält die Kennung der BelegDock-Testanwendung bei
    Google. Speichern Sie sie irgendwo auf Ihrem Computer; BelegDock liest sie nur und
    kopiert sie nicht.
  - Der Herausgeber muss Ihre Gmail-Adresse vorab als "Testnutzer" eingetragen haben.
    Ohne diesen Eintrag verweigert Google den Zugriff.
  - Klicken Sie auf "OAuth-Client-Datei auswählen" und wählen Sie die Datei. Klicken
    Sie dann auf "Mit Google verbinden". Es öffnet sich Ihr Browser.
  - Weil die Anwendung bei Google im Testmodus läuft, erscheint die Warnung "Diese App
    wurde nicht von Google überprüft". Das ist erwartet. Klicken Sie auf „Weiter“
    (gegebenenfalls zuerst auf „Erweitert“) und erlauben Sie den Lesezugriff auf Gmail.
    BelegDock liest nur; es verändert, löscht oder sendet keine E-Mails.
  - Zeigt Google stattdessen "Zugriff blockiert", hat der Herausgeber Ihre Gmail-Adresse
    noch nicht als Testnutzer eingetragen. Bitten Sie ihn darum.
  - Im Testmodus läuft die Google-Anmeldung nach etwa 7 Tagen ab. Dann zeigt BelegDock
    beim Start die Einrichtung mit dem Hinweis "Gmail-Anmeldung abgelaufen"; wählen Sie
    die Datei erneut und klicken Sie auf "Mit Google verbinden".
  - Kehren Sie zu BelegDock zurück. Bei Erfolg steht dort "Verbunden als ...".
  - Mit "Abbrechen" können Sie jederzeit neu beginnen. Dauert die Anmeldung im Browser
    zu lange (etwa 3 Minuten), erscheint ein Hinweis und Sie versuchen es erneut.

Schritt 2: Lexware verbinden
  - Erzeugen Sie in Lexware Office einen API-Schlüssel unter
    https://app.lexware.de/addons/public-api (Link im Fenster anklickbar).
  - Fügen Sie den Schlüssel in das Feld "API-Schlüssel" ein (die Eingabe ist verdeckt)
    und klicken Sie auf "Prüfen und speichern". BelegDock prüft den Schlüssel mit einer
    einzigen Abfrage und speichert ihn nur, wenn Lexware ihn akzeptiert. Bei
    "Schlüssel abgelehnt" erzeugen Sie bei Bedarf einen neuen Schlüssel.

Wenn beide Schritte "Verbunden" zeigen, klicken Sie auf "Weiter". Die Anmeldedaten
liegen ausschließlich im Windows Credential Manager. Es gibt keinen Klartext-Fallback.
Beim nächsten Start öffnet BelegDock direkt die Hauptansicht.

Alternative für Fortgeschrittene (neue Eingabeaufforderung):
  belegdock login-gmail --client C:\Pfad\zum\client.json
  belegdock login-lexware

Starten
-------
Über das Startmenü "BelegDock" oder mit:
  belegdock desktop

Ist der Windows Credential Manager nicht verfügbar, zeigt BelegDock eine
Fehlermeldung statt eines Fensters.

Daten
-----
Lokale Daten liegen außerhalb der Installation unter:
  %LOCALAPPDATA%\BelegDock
Dort liegen state.sqlite3 und der Ordner blobs. Dieses Verzeichnis für die
Wiederherstellung sichern und aufbewahren, solange kein Befehl läuft.

Aktualisieren (Upgrade)
-----------------------
Eine neuere Setup-Datei über die vorhandene Installation ausführen. Die
Anwendung wird ersetzt; %LOCALAPPDATA%\BelegDock bleibt unverändert erhalten.
Nach dem Upgrade einmal "belegdock documents" ausführen, bevor parallele Befehle
gestartet werden.

Deinstallieren
--------------
"BelegDock" in "Apps und Features" auswählen oder die Deinstallation im
Startmenü ausführen. Das Installationsverzeichnis, der Benutzer-PATH-Eintrag und
die Startmenü-Verknüpfung werden entfernt. Ihre Daten bleiben erhalten:
%LOCALAPPDATA%\BelegDock mit state.sqlite3 und blobs wird nicht gelöscht.
Zum endgültigen Entfernen der Daten dieses Verzeichnis bewusst selbst löschen.

Wiederherstellung
-----------------
Nach einem unterbrochenen Sendevorgang die CLI-Anleitung im Projekt-README
befolgen:
  belegdock recover-upload SHA256_HASH
  belegdock reconcile SHA256_HASH --file-id FILE_ID --voucher-id VOUCHER_ID
Ein unklares Sendeergebnis wird nie automatisch erneut gesendet.

Grenzen
-------
Keine Code-Signatur, daher SmartScreen-Warnung. Kein eigenes Anwendungssymbol.
Live-Übertragungen mit Gmail und Lexware sind nicht Teil dieser Paketprüfung und
benötigen eine eigene Freigabe.
