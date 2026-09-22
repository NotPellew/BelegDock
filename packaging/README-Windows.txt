BelegDock – Windows-Pilot
=========================

Unterstützt: Windows 10 22H2 (10.0.19045) und Windows 11, nur x64.
Für die Installation sind keine Administratorrechte nötig. ARM64 und ältere
Windows-Versionen werden nicht unterstützt.

Voraussetzungen
---------------
Windows 10 22H2 oder Windows 11 (x64), ein Gmail-Konto mit Lesezugriff und ein
Lexware-Office-API-Schlüssel. Python oder uv sind für die fertige Installation
nicht erforderlich. Optional vorab: die SHA-256-Prüfsumme der Setup-Datei mit der
Angabe in artifact.json vergleichen.

Installation
------------
1. BelegDock-0.1.0.dev0-windows-x64-setup.exe starten.
2. Die Windows-SmartScreen-Warnung erscheint, weil das Paket nicht signiert ist.
   Über "Weitere Informationen" und "Trotzdem ausführen" fortfahren.
3. Der deutsche Assistent installiert nach
   %LOCALAPPDATA%\Programs\BelegDock und trägt dieses Verzeichnis in den
   Benutzer-PATH ein. Ein Neustart der Eingabeaufforderung ist nötig, damit
   belegdock gefunden wird.
4. Der Startmenü-Eintrag "BelegDock" startet die Desktop-Oberfläche.

Erste Anmeldung (einmalig, in einer neuen Eingabeaufforderung)
--------------------------------------------------------------
  belegdock login-gmail --client C:\Pfad\zum\client.json
  belegdock login-lexware

Anmeldedaten liegen ausschließlich im Windows Credential Manager. Es gibt keinen
Klartext-Fallback.

Starten
-------
Über das Startmenü "BelegDock" oder mit:
  belegdock desktop

Ohne vorherige Anmeldung erscheint eine deutsche Fehlermeldung statt eines
Fensters.

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
