# Befunde der ausgelieferten Desktop-App (REA)

| | |
|---|---|
| Zweck | Belegt am fertig installierten Artefakt, was die Desktop-App von W.A.I.S. tatsächlich enthält und welche Schutzschalter gesetzt sind. |
| Zielgruppe | Sicherheits- und Release-Verantwortliche, Entwickler der Desktop-App |
| Dokumentart | Referenz (Befundbericht) |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce und die installierte App in Version 0.6.0 |
| Quellen | Installation unter `%LOCALAPPDATA%\Programs\wamo-desktop`, `desktop/main.js`, `desktop/preload.js`, `desktop/package.json`, `README.md` (Abschnitt zu den Fuses) |

## Warum REA, und warum nur hier

REA (Reverse Engineer Anything) untersucht ausgelieferte Artefakte. Für den Quellcode im Repo nutzt diese Dokumentation normale Lesewerkzeuge, so sieht es auch die REA-Anleitung selbst vor. REA beantwortet dagegen eine Frage, die der Quellcode nicht beantworten kann: Was steckt in der Datei, die auf dem PC der Mitglieder liegt? Das ist für die Desktop-App (Electron) wichtig, weil Schutzschalter wie die Electron-Fuses erst beim Verpacken in die Programmdatei geschrieben werden.

Die README nennt sechs der neun Fuses kurz. Dieses Dokument ergänzt sie um alle neun, mit Evidence, und um die Kanalkarte und die Fensterschalter. Die Begründungen der README bleiben dort maßgeblich.

## Methode

| Schritt | Befehl (REA 6.8.0, nur lesend, die App wurde nicht gestartet) |
|---|---|
| Fuses der Programmdatei | `rea inspect-electron-fuses <Installationsordner>\WAMO.exe` |
| Statische Analyse des Anwendungsarchivs | `rea analyze-javascript-application <Installationsordner>\resources\app.asar --detail summary --evidence_output <Datei>` |
| Gegenprobe der Kanalnamen | `app.asar` mit `@electron/asar` in einen eigenen leeren Ordner entpackt, Textsuche nach `ipcMain`, `ipcRenderer`, `contextBridge`, `BrowserWindow` |

Jede REA-Aussage trägt eine Evidence-Kennung. Beobachtung, Ableitung und Unbekanntes sind getrennt gehalten, siehe Abschnitt "Grenzen".

## Befund 1: Identität des Artefakts

| Merkmal | Wert |
|---|---|
| Programmdatei | `WAMO.exe`, PE, x86-64, 245.785.600 Byte |
| SHA-256 der Programmdatei | `97e4dd60c643482e2acc50a7f54f00d7a788591b30a93a2524c826f7ce9ae9d4` |
| Anwendungsarchiv | `resources/app.asar` |
| SHA-256 des Archivs | `3962bf4c576e4447e2ef81b114386725c2e368d4e5f6624e22b7d1f00b2a25d8` |
| Version in `package.json` des Archivs | 0.6.0, gleich `desktop/package.json` im Repo |
| Evidence Fuses | `ev_be93c9ebee6928ac2d00034d419053f72c7eed64e8d83a03ab42a9e0d1e0e2c5` |
| Evidence Analyse (Elternbefund) | `ev_b145597f1fe24d6012ccebc3cb220fcc0f8cf1c14660562155c74a369f6c2410` |

## Befund 2: Electron-Fuses (beobachtet)

Fuses sind Schalter in der Programmdatei, die Funktionen von Electron abschalten, bevor der eigene Code läuft. REA liest sie aus der Programmdatei, ohne sie zu starten.

| Fuse | Zustand | Wirkung |
|---|---|---|
| `RunAsNode` | aus | Die Programmdatei lässt sich nicht als Node-Interpreter missbrauchen. |
| `EnableNodeOptionsEnvironmentVariable` | aus | `NODE_OPTIONS` wird ignoriert. |
| `EnableNodeCliInspectArguments` | aus | `--inspect` und verwandte Schalter werden nicht beachtet. |
| `EnableEmbeddedAsarIntegrityValidation` | an | Das Archiv wird beim Laden gegen den eingebetteten Hash geprüft. |
| `OnlyLoadAppFromAsar` | an | Die App wird nur aus `app.asar` geladen, nicht aus einem daneben abgelegten Ordner. |
| `EnableCookieEncryption` | an | Cookies der App werden verschlüsselt abgelegt. |
| `GrantFileProtocolExtraPrivileges` | an | Seiten über `file://` behalten erweiterte Rechte (Voreinstellung von Electron). Laut README bleibt der Schalter an, weil `start.html` und `overlay.html` per `file://` aus dem Archiv geladen werden; mit "aus" scheitert der Start am gebauten Programm mit `ERR_FILE_NOT_FOUND`. |
| `LoadBrowserProcessSpecificV8Snapshot` | aus | Kein gesonderter Snapshot für den Browserprozess. |
| `WasmTrapHandlers` | an | WebAssembly nutzt Trap-Handler. |

Ableitung von REA: Inspector-Zugriff über die Kommandozeile und Node-Missbrauch sind nicht möglich, die Archivprüfung wird erzwungen und die App lädt nur aus dem Archiv.

## Befund 3: Inhalt des Pakets

| Teil | Inhalt |
|---|---|
| `resources/app.asar` | 28 Einträge ohne `node_modules`: `main.js`, `preload.js`, `overlay-preload.js`, `update.js`, `geraet.js`, `installation.js`, `livebild.js`, `markierung.js`, `lichtrahmen.js`, `berechtigungen.js`, `zertifikat.js`, `vollbild.js`, `taskleiste.js`, `entladen.js`, `host-umgebung.js`, `symbol-reparatur.js`, `start.html`, `start.js`, `overlay.html`, `overlay.css`, `livebild-hinweis.*`, `update-schluessel.json`, `package.json`, Bilder unter `assets/` |
| REA-Zählung | 23 relevante Dateien, 18 JavaScript-Dateien geparst, keine Parsefehler, 113 untersuchte Elemente im Anwendungsgraphen |
| `resources/host/` | der PC-Host (Python): `wamo_host.py`, `windows_control.py`, `uia_control.py`, `live_bild.py`, die Office-Module, `host_http.py`, `pyproject.toml`, `uv.lock` |
| `resources/scripts/` | PowerShell-Skripte für Tunnel und Symbolreparatur |
| `resources/uv/` | das Werkzeug `uv` für die Python-Umgebung des Hosts |
| `resources/wamo-ca.crt` | das Zertifikat der eigenen Zertifizierungsstelle |

## Befund 4: Fenster, Brücken und Kanäle

### Fenster

REA findet drei Browserfenster. Sie sind in der Quelle mit den sicheren Einstellungen angelegt (Gegenprobe per Textsuche in den entpackten Quellen):

| Einstellung | Wert in allen drei Fenstern |
|---|---|
| `contextIsolation` | `true` |
| `nodeIntegration` | `false` |
| `sandbox` | `true` |

REA zählt 18 ausdrücklich gesetzte Web-Einstellungen in diesen Fenstern. Neue Fenster und Navigation sind in `main.js` gesperrt (`setWindowOpenHandler` verweigert, `will-navigate` wird verhindert).

### Brücken

Zwei Brücken (`contextBridge`) mit zusammen 19 freigegebenen Mitgliedern:

| Brücke | Datei | Zweck |
|---|---|---|
| `window.wamoDesktop` | `preload.js` | Schnittstelle der Oberfläche zur Desktop-App: Betriebsart, Rechnername, Mikrofonstatus, Geräteeinrichtung, Updates, Zustand und Markierung |
| `window.overlay` | `overlay-preload.js` | Schnittstelle des Markierungsfensters |

### Kanäle (13 Namen, 12 Handler)

| Kanal | Art | Richtung | Zweck |
|---|---|---|---|
| `betriebsart:lesen` | handle | Oberfläche an Hauptprozess | liest die Betriebsart (Büro oder Unterwegs) |
| `betriebsart:setzen` | handle | Oberfläche an Hauptprozess | setzt eine der zwei bekannten Betriebsarten |
| `betriebsart` | Ereignis | Hauptprozess an Oberfläche | meldet Wechsel der Betriebsart |
| `rechnername` | handle | Oberfläche an Hauptprozess | Name des PCs, damit die PC-Steuerung im Büro automatisch eingeschaltet werden kann |
| `mikrofon:status` | handle | Oberfläche an Hauptprozess | Windows-Datenschutzstatus des Mikrofons (einer von fünf festen Werten) |
| `geraet:vorbereiten` | handle | Oberfläche an Hauptprozess | Laptop für den Tunnel vorbereiten (nur Büro) |
| `geraet:signieren` | handle | Oberfläche an Hauptprozess | feste Bindungsnachricht mit dem Geräteschlüssel signieren (der Schlüssel bleibt im Hauptprozess) |
| `geraet:aktivieren` | handle | Oberfläche an Hauptprozess | Geräteeinrichtung abschließen |
| `geraet:status` | handle | Oberfläche an Hauptprozess | Stand der Geräteeinrichtung |
| `update:pruefen` | handle | Oberfläche an Hauptprozess | prüft ein Update-Angebot (Signatur und steigende Version) |
| `update:installieren` | handle | Oberfläche an Hauptprozess | lädt, prüft Größe und SHA-256 und startet erst dann den Installer |
| `levels` | on | Oberfläche an Hauptprozess | meldet den Zustand der Oberfläche (Energiesparschutz, Bezug für die Markierung); der Name stammt aus früherer Verträglichkeit, Pegel werden nicht ausgewertet |
| `markierung` | on und Ereignis | Oberfläche an Hauptprozess, dann an das Markierungsfenster | Lichtrahmen und Klickwelle am Zielfenster |

Die Zwecke stehen in den Kommentaren und Handlern von `desktop/main.js` und `desktop/preload.js`. REA belegt Anzahl und Kopplung: 12 Sendungen der Oberfläche, 12 Handler im Hauptprozess, alle gepaart, keine dynamisch gebildeten Kanalnamen, keine mehrdeutigen Zuordnungen.

### Absenderprüfung: REA und Quelle

REA meldet 0 "Beobachtungen zur Absenderprüfung". Das ist keine Lücke der App: Alle zwölf Handler prüfen den Absender über die Hilfsfunktion `fromMainUi(event)` (`desktop/main.js`, Zeile 919). Sie verlangt, dass der Absender das Hauptfenster ist und der Rahmen von der eigenen Adresse stammt. Die statische Erkennung von REA erfasst solche Hilfsfunktionen nicht als Muster. Für die Prüfung gilt deshalb die Quelle, und REA bestätigt dazu die Zahl der Handler.

### Prozesse und native Teile

REA findet keine Utility-Prozesse und keine nativen Erweiterungen (Addons) in der Desktop-App. Die Python-Teile liegen als Quelltext im Ordner `resources/host`.

## Grenzen dieses Befunds

- Alle Aussagen sind statisch. Nichts wurde ausgeführt, die App wurde nicht gestartet.
- Der Zustand der Fuses beweist nicht, dass die App den Inspector nicht auf anderem Weg einschaltet, etwa über einen Schalter im Anwendungscode. In `desktop/main.js` wurde dazu nicht gesucht.
- REA nennt 4519 semantische Unbekannte (dynamische Ausdrücke, nicht aufgelöste Verweise). Sie sind im Evidence-Bündel erhalten, aber nicht einzeln geprüft.
- Das Evidence-Bündel (24 MB) liegt nur im lokalen Arbeitsordner dieser Sitzung und gehört nicht ins Repo.

## Offener Punkt für das Release-Team

| Punkt | Stand |
|---|---|
| Im Installationsordner liegt `resources/host/wamo_audit.jsonl` (Laufzeitdatei des Hosts). | Der Inhalt wurde nicht gelesen. Ob Updates diese Datei erhalten, ist nicht geprüft. |

## Befunde nachprüfen

```text
rea inspect-electron-fuses "%LOCALAPPDATA%\Programs\wamo-desktop\WAMO.exe"
rea analyze-javascript-application "%LOCALAPPDATA%\Programs\wamo-desktop\resources\app.asar" --detail summary --evidence_output <neue Datei>
```

REA überschreibt kein vorhandenes Bündel, der zweite Befehl braucht einen neuen Dateinamen. Nach jedem Versionssprung der Desktop-App (Installer, siehe `../betrieb/release-und-ausrollen.md`) sind beide Befehle zu wiederholen und die Hashes in Befund 1 zu erneuern. Der Plan dafür steht in `../../ausrollen-neue-nutzer.md` (Abschnitt zur REA-Prüfung am gebauten Installer).

## Weiterführend

- [Host und Desktop (Quellcode-Sicht)](host-und-desktop.md)
- [Sicherheit und Datenschutz](../sicherheit/sicherheit-und-datenschutz.md)
- [Release und Ausrollen](../betrieb/release-und-ausrollen.md)
- [Dokumentationskonzept (zur Methode)](../dokumentationskonzept.md)
