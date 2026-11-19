# Glossar

| | |
|---|---|
| Zweck | Erklärt die Begriffe, die in der Produktdokumentation und im Repo von W.A.I.S. vorkommen. |
| Zielgruppe | Alle Leser, besonders neue Mitglieder und Entwickler |
| Dokumentart | Referenz |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `CLAUDE.md` (Namensvertrag), `README.md`, `docs/*.md`, die genannten Module |

Einträge stehen alphabetisch. Wo ein Begriff ein Modul oder einen Dienst bezeichnet, steht der Pfad dabei. Namen und Pfade des Namensvertrags bleiben `wamo`, auch wenn der Anzeigename "W.A.I.S." heißt.

| Begriff | Bedeutung |
|---|---|
| aal2 | Anmeldestufe mit zweitem Faktor (Authenticator-App). Zugang zu W.A.I.S. gibt es nur mit aktivem Profil und aal2. |
| Abnahme (Entwicklungsaufträge) | Prüfung eines Entwicklungsauftrags gegen ein prüfbares Ziel in mehreren Runden (`README.md`, Abschnitt "Abnahme: prüfbares Ziel mit Runden"). |
| Admin | Rolle `admin`: darf zusätzlich zu den Rechten eines Mitglieds Nutzer verwalten, PC-Werkzeuge und Entwicklungsaufträge nutzen (nach Schaltern und Freigaben). Details in `fachlich/rollen-und-rechte.md`. |
| Notanker (Anker) | Dienst `wamo-anker` auf dem Server, läuft als root, nur über einen Unix-Socket erreichbar, Code außerhalb von `/opt/wamo*`. Er kann nur zurückführen (Rückweg), sperren und prüfen. Teil der Selbstüberarbeitung, deren Betriebszustand laut README nicht belegt ist. |
| Anzeigename | `W.A.I.S.` mit Schlusspunkt. Gesprochen "Wais" wie englisch "ways". Die Langform ist "WAMOCON's Artificial Intelligence System". |
| Audit | Protokoll sicherheitsrelevanter Aktionen. Der PC-Host schreibt `host/wamo_audit.jsonl`, der Kern führt Aktionen in der Tabelle `actions`. |
| Betriebsart | "Büro" (Kern auf Sokrates-2, PC-Werkzeuge per Tunnel) oder "Unterwegs" (Kern auf dem eigenen PC, Host per stdio). |
| Blau/Grün | Zwei Container der Oberfläche (`wamo-ui-blau`, `wamo-ui-gruen`). Ein Skript schaltet zwischen ihnen um, damit ein Wechsel ohne Ausfall möglich ist. |
| Boss | Regelwerk im Kern (`voice-core/boss.py`), das je Aufgabe das Modell wählt, auf Grundlage der gemessenen Modellkarte. |
| Büro-Karte | Übersicht der Bürogeräte in der Oberfläche. |
| Caddy | Reverse-Proxy (`wamo-caddy`) mit TLS vor den Diensten auf Sokrates-2, mit eigener Zertifizierungsstelle. |
| Canvas | Arbeitsfläche neben dem Gespräch, in der W.A.I.S. Texte, Diagramme, Bilder und Dokumente zeigt. Inhalte lassen sich schließen, aus der Historie öffnen und exportieren. |
| Desktop-App | Electron-Programm `desktop/` mit Hauptfenster, Tray, Markierung am Zielfenster, Updater. Installiert als `WAMO.exe`, Produktname W.A.I.S. |
| DevAgent | Teil des Kerns (`voice-core/dev_agent.py`), der Entwicklungsaufträge vorbereitet, per Karte freigeben lässt und an den Dispatcher übergibt. |
| Dispatcher | Dienst auf Sokrates-2 (`infra/sokrates2/wamo_job_dispatch.py`), der Entwicklungsaufträge in einer abgeschotteten Umgebung ausführt. |
| ECC | Sammlung von Skills und Agenten für Claude Code (Plugin `ecc`), im Projekt für Planung, Prüfung und Dokumentation genutzt. |
| Entwicklungsauftrag | Auftrag an W.A.I.S., Code in einer Sandbox zu ändern. Nur mit Zulassung und Freigabe, nie für Laborprofile. |
| Erstanmeldung | Erste Anmeldung eines Kontos mit Startpasswort. Danach ist ein Passwortwechsel Pflicht. |
| Fehlerbuch | Kurzzeitspeicher der Sitzung (`voice-core/fehlerbuch.py`), der erklärt, warum etwas nicht ging. Nie in der Datenbank. |
| Freigabe, Freigabekarte | Bestätigung durch die Person in der Oberfläche vor einer riskanten Aktion. Ohne Klick geschieht nichts. |
| Gate (Stimm-Gate) | Prüfstufe (`voice-core/stimme_gate.py`), die entscheidet, ob eine Äußerung zählt, zum Beispiel nur die eigene Stimme. |
| Gedächtnis | Gespeichertes Wissen. Persönlich gehört genau einem Profil, gemeinsam gilt für alle und wirkt erst im Status "aktiv". Inhalte gelten als Daten, nie als Anweisungen. |
| Gerät | Eintrag im Geräteregister (`devices`). Laptops heißen `pc-<name>`. |
| Hausmodelle | Sprachmodelle auf den eigenen Servern, erreichbar nur über LiteLLM. Gegenstück zu Claude. |
| Haus-Proxy | Dienst `wamo-haus-proxy`, der Entwicklungsaufträge mit Hausmodellen an LiteLLM weiterleitet. |
| Host (PC-Host) | Werkzeugserver am PC (`host/wamo_host.py`, MCP). Führt Fenster-, Office- und Bildschirmaktionen nach Risikoklasse aus. |
| Kern, Voice-Core | Python-Dienst `voice-core/` mit Sprachpipeline, Rechten, Gedächtnis, Werkzeugen und API. |
| Kern-Kanal | Weg vom Kern zum Dispatcher über SSH für Entwicklungsaufträge im Büro. |
| Kern-Slot | Zwei Instanzen des Kerns (`wamo-core@a`, `wamo-core@b`), zwischen denen ohne Ausfall umgeschaltet wird. |
| Labor, Testlabor | Veranstaltung am 28.11.2026 mit eigenen Laborprofilen, Test-Jira (Labor-Dienst) und Betreuern. Laborprofile haben bewusst eingeschränkte Rechte. |
| Labor-Dienst | Dienst `labor-dienst/`, das Test-Jira des Testlabors (FastAPI, SQLite). |
| LiteLLM | Gateway für Modelle. Hausmodelle sind nur darüber erreichbar. |
| Live-Bild | Bild des Bildschirms am Laptop, das W.A.I.S. mit Einwilligung sieht (`host/live_bild.py`, `desktop/livebild.js`). |
| Markierung (Overlay) | Lichtrahmen ums Zielfenster und Welle am Klickpunkt, wenn W.A.I.S. am Bildschirm handelt. |
| MCP | Model Context Protocol. Der PC-Host ist ein MCP-Server (Version 1). |
| Mitglied | Rolle `mitglied`: normale Nutzerin oder normaler Nutzer. PC-Steuerung und Entwicklungsaufträge nur nach Freischaltung. |
| Modellkarte | Datentabelle (`voice-core/modellkarte.py`) mit gemessenen Fähigkeiten, Latenzklasse, Datenschutz und Status je Modell. |
| Namensvertrag | Verbindliche Tabelle in `CLAUDE.md` mit allen Namen, Pfaden, Diensten und Schaltern. |
| Notaus | Sperrdatei oder Schalter, der einen Kanal oder Dienst sofort sperrt (zum Beispiel der Kern-Kanal). |
| PC-Steuerung | Fähigkeit von W.A.I.S., einen PC zu bedienen. Rechte regelt `voice-core/rechte.py` (`pc_stufe`: `admin`, `mitglied` oder keine). |
| Persona | Der Prompt, der Rolle, Ton und Regeln von W.A.I.S. festlegt (`voice-core/persona.py`). |
| Pipecat | Framework für die Sprachpipeline im Kern. |
| Planpapier | Konzeptdokument in `docs/` mit Stand und Basis-Commit. Es kann überholt sein, der Kopf nennt den Stand. |
| Profil | Eintrag in `<schema>.profiles`: Rolle, Aktivstatus und Einstellungen einer Person. Zugang nur mit aktivem Profil. |
| Prüfer-Sandbox | Abgeschottete Umgebung (`wamo-pruefer`), in der fremder Code geprüft wird. |
| Release-Dienst | Dienst `wamo-release` (ohne root) für die Selbstüberarbeitung: nimmt Anfragen eines aktiven Admins entgegen (`anfordern`, `abbrechen`, `zurueck`). Die Freigabe selbst nimmt der getrennte Freigabe-Dienst `wamo-freigabe` an. |
| REA | Reverse Engineer Anything: Werkzeug zur Analyse ausgelieferter Programme, im Projekt für die Desktop-App genutzt. |
| RLS | Row Level Security: Zeilenschutz in der Datenbank. Jede neue Tabelle braucht ihn. |
| Schema (Datenbank) | `wamo_dev`, `wamo_test`, `wamo_prod`: getrennte Umgebungen in derselben Datenbank. |
| Sokrates-1, Sokrates-2 | Server im Büro-LAN. Sokrates-2 hostet Datenbank, Kern und Oberfläche. |
| Soniox | Anbieter für Spracherkennung und Sprachausgabe (Standard), Alternative sind Hausmodelle. |
| Sparks | Rechner mit den Hausmodellen. Zugriff nur über LiteLLM. |
| Stimmabdruck | Biometrisches Merkmal der eigenen Stimme, nach Einwilligung eingelernt, je Mikrofon einer (höchstens drei je Person). Die Stimmprüfung misst und zeigt im Standard nur ("beobachten"), sie sperrt erst im Modus "streng". |
| Stimmwächter | Logik im Kern (`voice-core/stimme_waechter.py`), die fremde Stimmen erkennt. Verwerfen und Sperren gelten nur im Prüfmodus "streng", der Standard ist "beobachten". |
| Supabase | Datenbank und Anmeldedienst, eigener Stack auf Sokrates-2. |
| Tunnel | SSH-Rücktunnel vom Laptop zum Server, damit der Kern den Host am Laptop steuern kann. Je Laptop ein Benutzer `wamo-t-NN`. |
| TOTP | Zeitbasiertes Einmalpasswort der Authenticator-App (zweiter Faktor). |
| Unterwegs | Betriebsart ohne Büro-Server, siehe Betriebsart. |
| Vorgang | Laufender oder beendeter Auftrag in der Tafel "Vorgänge" der Oberfläche. |
| Weckwort | "Hey WAMO", vorgesehen für später (Datenbankstandard `wake_word = 'wamo'`). |
| WMC | WAMOCON. WMC-Rot `#F40E0E` ist die Hauptfarbe des Designs. |

## Weiterführend

- [Dokumentenlandkarte](README.md)
- [Rollen und Rechte](fachlich/rollen-und-rechte.md)
- [Architektur (arc42)](architektur/arc42.md)
