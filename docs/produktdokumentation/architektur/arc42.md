# Architekturdokumentation nach arc42

| | |
|---|---|
| Zweck | Beschreibt Aufbau, Zusammenspiel, Verteilung und Qualitätsziele von W.A.I.S. in den zwölf Abschnitten von arc42. |
| Zielgruppe | Entwicklerinnen und Entwickler, Architektur, Betrieb, Prüferinnen und Prüfer. |
| Dokumentart | Erklärung |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `CLAUDE.md`, `README.md`, `infra/sokrates2/README.md`, `voice-core/bot.py`, `voice-core/auth_gate.py`, `host/wamo_host.py`, `docs/*.md` |

arc42 ist eine Gliederung für Architekturdokumentation mit zwölf festen Abschnitten. Die Diagramme dazu stehen in [`c4-diagramme.md`](c4-diagramme.md), die Entscheidungen in [`entscheidungen.md`](entscheidungen.md), die Schnittstellen in [`../technik/schnittstellen.md`](../technik/schnittstellen.md). Begriffe erklärt [`../glossar.md`](../glossar.md). Der Code ist maßgeblich vor Prosa. Wo eine Aussage nur im README steht und sich nicht am Code prüfen lässt, steht "laut README".

## 1. Einführung und Ziele

Quellen: `README.md`, `CLAUDE.md`, `docs/testlabor-wamo.md`.

### 1.1 Aufgabenstellung

W.A.I.S. ist der Sprachassistent der WAMOCON GmbH. Die Langform ist "WAMOCON's Artificial Intelligence System", gesprochen "Wais". Er führt Livegespräche mit natürlichen Unterbrechungen, bietet eine Oberfläche im WMC-Design, bedient den Windows-PC der Person über Werkzeuge, führt Entwicklungsaufträge mit Claude Code, ECC und REA aus und hält ein persönliches und ein gemeinsames Gedächtnis. Mehrere Profile nutzen denselben Kern.

| Fähigkeit | Kurzbeschreibung | Mehr |
|---|---|---|
| Gespräch | Sprache rein, Sprache raus, Unterbrechen jederzeit, Untertitel, Canvas für Tabellen, Code, Dokumente, Diagramme | [`../fachlich/funktionskatalog.md`](../fachlich/funktionskatalog.md) |
| PC-Steuerung | Fenster, Tastatur, Maus, PowerShell lesen, Office, Mail, Teams, OneNote am eigenen Laptop, jede kritische Aktion nur nach Klick | [`../technik/host-und-desktop.md`](../technik/host-und-desktop.md) |
| Entwicklungsaufträge | Claude Code in einer Sandbox auf dem Server, Ergebnis als Pull Request nach Klick | [`../../entwicklung-im-betrieb.md`](../../entwicklung-im-betrieb.md) |
| Gedächtnis | Persönliche Eigenschaften und gemeinsames Firmenwissen, gemeinsame Einträge erst nach Freigabe | [`../technik/datenmodell.md`](../technik/datenmodell.md) |
| Bürogeräte | Status und Steuerung gemeinsamer Geräte im Büro über einen Gerätedienst | `geraete/README.md` |
| Testlabor | Eingeschränktes Profil für Besucher am Labortag 28.11.2026 | [`../../testlabor-wamo.md`](../../testlabor-wamo.md) |

Produktumfang und Abgrenzung: [`../fachlich/produktuebersicht.md`](../fachlich/produktuebersicht.md).

### 1.2 Qualitätsziele

Die fünf wichtigsten Ziele, geordnet nach Gewicht. Konkrete Szenarien stehen in Abschnitt 10.

| Rang | Qualitätsziel | Bedeutung |
|---|---|---|
| 1 | Sicherheit | Zugang nur mit zweitem Faktor und aktivem Profil. Jede Unsicherheit führt zur Ablehnung. Kritische Aktionen nur nach dem Klick einer Person. Inhalte von außen sind Daten, nie Anweisungen. |
| 2 | Gesprächsqualität und Latenz | Das Gespräch muss sich wie zwischen Menschen anfühlen: kurze Wartezeit bis zum ersten Ton, natürliche Unterbrechungen, keine tote Stille. |
| 3 | Datenschutz | Daten bleiben im Haus (eigener Datenbankstack, Hausmodelle). Spracherkennung und Sprachausgabe laufen über EU-Endpunkte. Stimmabdruck nur mit Einwilligung. Das Labor löscht vollständig. |
| 4 | Verfügbarkeit im Betrieb | Releases ohne Unterbrechung laufender Gespräche. Fällt der PC oder ein Modell aus, bleibt W.A.I.S. ansprechbar und sagt es. |
| 5 | Wartbarkeit | Eindeutige Namen, feste Listen mit Gegenstück und Vertragstest, jedes neue Verhalten hinter einem Schalter mit Rückweg. |

### 1.3 Stakeholder

| Rolle | Erwartung |
|---|---|
| Mitglieder der WAMOCON GmbH | Verlässlicher Assistent am eigenen Laptop. Rechte und Freigaben sind verständlich. |
| Admins | Verwalten Konten, Geräte, gemeinsames Gedächtnis und Fernzugriff. Geben Änderungen frei. |
| Geschäftsführung (Niko) | Entscheidet über Umfang, Schalter und Freigabe von Stufen. Verbindliche Entscheidungen stehen in [`entscheidungen.md`](entscheidungen.md). |
| Besucher und Betreuer des Testlabors | Eng begrenzter Zugang am Platz, Betreuer führen und können abschalten. |
| Betrieb und Entwicklung | Wiederholbare Einrichtung, Rückwege, klare Fehlermeldungen, Tests. |
| Datenschutz und Recht | Einwilligung, Löschfristen, Nachweis. Beispiele: `docs/labor-datenschutz-entwurf.md`, Einwilligung zum Stimmabdruck in `voice-core/stimme_einwilligung.py`. |

## 2. Randbedingungen

Quellen: `README.md`, `CLAUDE.md`, `voice-core/pyproject.toml`, `ui/package.json`, `desktop/package.json`, `host/pyproject.toml`.

| Art | Randbedingung | Folge |
|---|---|---|
| Technik | Voice-Core auf Pipecat ab 1.12 und unter 2, Python ab 3.11 | Pipeline aus Bausteinen (Frames), Soniox, Anthropic, MCP und WebRTC kommen als Pipecat-Pakete |
| Technik | Oberfläche Next.js 16.4.6 mit React 19.3.0, Desktop-App Electron 44.10.1, beide in Version 0.6.0 | Gemeinsame Oberfläche für Browser und App, Brücke `window.wamoDesktop` |
| Technik | PC-Host nur für Windows (MCP-Server mit PowerShell, UI Automation, COM) | PC-Steuerung gibt es nur an Windows-Laptops |
| Technik | Eigener Supabase-Stack auf dem Server Sokrates-2, Postgres mit TLS, Rolle `wamo_core` | Kein `service_role` im Kern, Schemas `wamo_dev`, `wamo_test`, `wamo_prod` |
| Technik | Modelle im Haus nur über das zentrale LiteLLM-Gateway | Keine direkten Adressen von Modellknoten |
| Technik | Server ist ein ARM64-Linux (Runner-Labels `linux, ARM64`), Zugriff über SSH | Skripte für Einrichtung und Rückweg je Dienst unter `infra/sokrates2/` |
| Organisation | Freeze für Kern, Migrationen, Oberfläche und Dienste ab Montag 23.11.2026 früh, Testlabor am 28.11.2026 | Neuere Pakete laufen hinter Schaltern, Stand je Paket im jeweiligen Planpapier |
| Organisation | Einheitliches Corporate Design WMC, deutsche Texte mit echten Umlauten, keine Gedankenstriche im Fließtext | Gilt für Oberfläche, Sprachausgabe und Dokumente |
| Organisation | Namensvertrag: Anzeigename W.A.I.S., alle technischen Kennungen bleiben `wamo` | Siehe Abschnitt 8.3 |
| Recht | Einwilligung für Stimmabdruck und Laborprofile, Löschfristen, Datenschutzhinweis | Eigene Tabellen und Löschläufe, Version der Einwilligung wird geprüft |
| Konvention | Migrationen sind nach dem Apply auf PROD unveränderlich, neue Tabellen mit Row Level Security | Siehe [`entscheidungen.md`](entscheidungen.md), Abschnitt 5 |

## 3. Kontextabgrenzung

Quellen: `README.md`, `CLAUDE.md`, `voice-core/bot.py`, `voice-core/llm_anbieter.py`, `voice-core/sprache_anbieter.py`.

### 3.1 Fachlicher Kontext

| Partner | Austausch mit W.A.I.S. |
|---|---|
| Mitglied oder Admin | Spricht und tippt, liest Antworten und Karten, klickt Freigaben |
| Besucher und Betreuer im Labor | Besucher sprechen am Platz, Betreuer führen den Durchlauf und beenden ihn |
| Windows-Laptop der Person | Wird gesteuert, zeigt Fenster, Dateien, Outlook, Teams und OneNote |
| Bürogeräte | Status und Steuerung (Fernseher, Lautsprecher, Steckdosen, Drucker, Scanner, NAS) |
| GitHub | Ziel der Pull Requests aus Entwicklungsaufträgen, Quelle von Prüfläufen |
| Jira | Anlegen von User Stories nach Klick, im Labor ein eigener Test-Dienst |
| Anbieter von Sprach- und Sprachmodellen | Soniox (Hören und Sprechen), Claude (Gespräch und Entwicklungsaufträge), Hausmodelle |

### 3.2 Technischer Kontext

| Nachbar | Richtung | Protokoll und Absicherung | Quelle |
|---|---|---|---|
| Browser und Desktop-App | beide | WebRTC (Audio, Nachrichten), HTTPS für `/start`, Angebot und `/wamo/api/...`, Bearer-Token mit aal2 | `voice-core/auth_gate.py` |
| Anmeldedienst und Datenbank (Supabase) | Kern und Oberfläche nach Supabase | HTTPS (Token, JWKS), Postgres über Pooler mit TLS und eigener CA | `voice-core/memory.py`, `voice-core/wamo_tls.py` |
| Soniox | Kern nach Soniox | Streaming für Erkennung und Sprachausgabe, EU-Endpunkte | `voice-core/sprache_anbieter.py`, `voice-core/soniox_tts.py` |
| Claude (Anthropic) | Kern nach Anthropic | HTTPS, Schlüssel je Profil oder Server-Schlüssel, Websuche wahlweise über SearXNG | `voice-core/llm_anbieter.py`, `voice-core/suche.py` |
| LiteLLM-Gateway und Hausmodelle | Kern nach Gateway | HTTP im Büro-LAN, OpenAI-kompatible Schnittstelle, Modell-Aliase | `voice-core/llm_anbieter.py`, `docs/hausmodelle-und-kikollege.md` |
| PC-Host | Kern nach Laptop | MCP über Streamable HTTP, nur über SSH-Rücktunnel je Gerät, Bearer-Token | `voice-core/pc_host.py`, `voice-core/pc_tunnel.py` |
| Auftrags-Dispatcher | Kern nach Server | SSH mit eigenem Schlüssel, Forced Command, JSON-Zeilen als Antwort | `voice-core/dev_agent_weg.py`, `infra/sokrates2/wamo_job_dispatch.py` |
| Gerätedienst | Kern nach Dienst | Unix-Socket, eine JSON-Zeile je Anfrage | `voice-core/geraete_client.py`, `geraete/README.md` |
| Labor-Dienst | Kern nach Dienst | HTTP mit Token, Vertrag V1 bis V7 | `voice-core/labor_client.py`, `docs/labor-dienst-vertrag.md` |
| Release-Dienst und Freigabe-Dienst | Kern und Oberfläche nach Dienst | Unix-Socket, die Freigabe geht über Caddy direkt an den Freigabe-Dienst | `voice-core/release_client.py`, `infra/sokrates2/wamo-caddy/kern/wamo-core.caddy` |
| Jira und GitHub | Kern nach extern | REST über HTTPS, Token je Person oder technischer Benutzer | `voice-core/jira_client.py`, `voice-core/github_zugang.py` |

## 4. Lösungsstrategie

Quellen: `CLAUDE.md` (Architektur-Entscheidungen), `README.md` (Sicherheitsmodell), `docs/selbstueberarbeitung.md`, `docs/gespraech-optimierung.md`.

| Ziel | Ansatz | Wo umgesetzt |
|---|---|---|
| Sicherheit | Zugangskontrolle als einzige Middleware vor allen Routen. Rechte im Code, nicht im Prompt. Kritische Aktionen als Karte mit Klick. Fail closed bei jeder Unsicherheit. | `voice-core/auth_gate.py`, `voice-core/rechte.py`, `host/wamo_host.py` |
| Gesprächsqualität | Kaskade aus Sprachaktivität, Spracherkennung, Turn-Erkennung, Modell im Streaming und Sprachausgabe. Innehalten statt hartem Abbruch, Rückmeldelaute stoppen nicht, Latenz je Zug messbar. | `voice-core/bot.py`, `voice-core/soft_interrupt.py`, `voice-core/latenz.py` |
| Datenschutz | Eigener Stack, Hausmodelle als Option, EU-Endpunkte, Stimmabdruck je Mikrofon als Zahlenvektor nach Einwilligung, Fehlerbuch nur im Speicher. | `voice-core/memory.py`, `voice-core/stimme_*.py`, `voice-core/fehlerbuch.py` |
| Verfügbarkeit | Zwei Kern-Instanzen (Slots) und zwei Oberflächen-Container (blau und grün), Umschalten über Include-Dateien, Notanker außerhalb des Repo-Deploys. | `infra/sokrates2/wamo-core-slots.sh`, `infra/sokrates2/wamo-ui-umschalten.sh` |
| Wartbarkeit | Namensvertrag, Vertragstests zwischen Kern und Dispatcher, feste Listen mit Gegenstück, Skripte mit `einrichten` und `rueckweg`. | `voice-core/test_kernkanal_vertrag.py`, `infra/sokrates2/*-einrichten.sh` |
| Beherrschbare Einführung | Neue Pakete laufen hinter Schaltern, Standard aus. Pakete werden in Stufen geschaltet und lassen sich zurücknehmen. | `voice-core/env_schalter.py`, `docs/entwicklung-im-betrieb.md` |
| Modellflexibilität | Anbieter je Baustein umschaltbar. Ein Regelwerk ("Boss") wählt nach Aufgabenklasse, gemessener Güte und Antwortzeit. | `voice-core/llm_anbieter.py`, `voice-core/boss.py`, `voice-core/modellkarte.py` |

## 5. Bausteinsicht

Quellen: `README.md` (Tabelle der Ordner), `CLAUDE.md`, Ordnerstruktur des Repos.

### 5.1 Ebene 1: das Gesamtsystem

| Baustein | Aufgabe | Technik | Läuft auf | Tiefe |
|---|---|---|---|---|
| `ui/` | Oberfläche: Präsenzkern, Untertitel, Stimmlinie, Werkzeug-Zeitleiste, Canvas, Freigabekarten, Anmeldung mit zweitem Faktor, Einstellungen | Next.js 16, React 19 | als Container `wamo-ui` auf dem Server (Browser), in der Desktop-App eingebettet | [`../technik/oberflaeche.md`](../technik/oberflaeche.md) |
| `desktop/` | App-Fenster, Markierung am Zielfenster, Tray, Autostart, Update, Host-Umgebung, Live-Bild | Electron 44 | Windows-PC | [`../technik/host-und-desktop.md`](../technik/host-und-desktop.md) |
| `host/` | Werkzeuge am Windows-PC mit Risikoklassen und Audit-Log | Python, MCP (FastMCP) | Windows-PC | [`../technik/host-und-desktop.md`](../technik/host-und-desktop.md) |
| `voice-core/` | Gespräch, Zugangskontrolle, Rechte, Werkzeuge, Gedächtnis, Entwicklungsaufträge, HTTP-Schnittstellen | Python, Pipecat | Server (Büro) oder PC (Unterwegs) | [`../technik/voice-core.md`](../technik/voice-core.md) |
| `supabase/` | Migrationen mit Platzhalter `__SCHEMA__`, SQL-Tests | SQL | eigener Supabase-Stack auf dem Server | [`../technik/datenmodell.md`](../technik/datenmodell.md) |
| `geraete/` | Gerätedienst `wamo-geraete` für Bürogeräte | Python | Server | `geraete/README.md` |
| `labor-dienst/` | Test-Jira des Testlabors (API, Speicher, Betreuer-Seite) | Python, FastAPI, SQLite | Server (Container) | [`../../labor-dienst-vertrag.md`](../../labor-dienst-vertrag.md) |
| `infra/sokrates2/` | Einrichtung und Betrieb aller Dienste: Stack, TLS, Firewall, Kern-Slots, Dispatcher, Release, Anker, Freigabe, Prüfer, Proxys, Gateway für Fernzugriff, Runner | Shell, Python, nft, systemd | Server | [`../betrieb/betriebshandbuch.md`](../betrieb/betriebshandbuch.md) |
| `scripts/` | Start der Desktop-App, Nutzerverwaltung, Migrationen, Versionsskript, Messwerkzeuge, Labor-Skripte | Python, Node, PowerShell | Entwicklungs-PC und Admin-PC | [`../entwicklung/entwicklerhandbuch.md`](../entwicklung/entwicklerhandbuch.md) |

### 5.2 Ebene 2: Voice-Core

Der Kern ist der größte Baustein. Die Gruppen unten fassen die Module in `voice-core/` zusammen. Ein Modul gehört zu genau einer Gruppe. Die Tiefe steht in [`../technik/voice-core.md`](../technik/voice-core.md), die Diagramme in [`c4-diagramme.md`](c4-diagramme.md), Abschnitt 4.

| Gruppe | Module (Auswahl) | Aufgabe |
|---|---|---|
| Zugang und Schnittstellen | `auth_gate.py`, `wamo_api.py`, `*_api.py`, `kern_dienst.py` | Token-Prüfung, Identität, HTTP-Routen, Start als Dienst auf einem Unix-Socket |
| Gespräch | `bot.py`, `persona.py`, `llm_anbieter.py`, `sprache_anbieter.py`, `soniox_tts.py`, `soft_interrupt.py`, `wiedergabe.py`, `turn_wache.py`, `wartesatz.py`, `fuellwoerter.py`, `latenz.py` | Pipeline, Persona, Wahl der Anbieter, Unterbrechungen, Wartesätze, Latenzmessung |
| Stimmprüfung | `stimme_pruefer.py`, `stimme_gate.py`, `stimme_waechter.py`, `stimme_modell.py`, `stimme_mikrofon.py`, `stimme_einlernen.py`, `stimme_sitzung.py`, `stimme_speicher.py` | Stimmabdruck je Mikrofon einlernen, jede Äußerung prüfen, Regeln für Werkzeuge (nur im Modus streng sperrend) |
| Werkzeuge im Gespräch | `tools.py`, `activity.py`, `werkzeug_wache.py`, `ausgaben_kuerzen.py`, `suche.py`, `screen.py` | Zeit, Websuche, Canvas, Merken, Bildschirm, Aktivitätsmeldungen |
| PC-Steuerung | `pc_host.py`, `pc_geraet.py`, `pc_tunnel.py`, `pc_freigaben.py`, `pc_mitglied.py`, `rechte.py` | Verbindung zum Host je Gerät, Freigabekarten, Schutz der Mitglieder |
| Office und Versand | `office_werkzeuge.py`, `outlook_werkzeuge.py`, `teams_werkzeuge.py`, `onenote_werkzeuge.py`, `jira_*.py` | Canvas als Datei, Mail, Teams, OneNote, Jira-Story, jeweils mit Karte |
| Geräte und Teilen | `geraete_*.py`, `buero_api.py`, `teilen.py`, `teilen_werkzeuge.py` | Bürogeräte, geteilte Canvas, Dateien und Aufträge |
| Entwicklungsaufträge | `dev_agent*.py`, `dev_guard.py`, `entwicklung_betrieb.py`, `abnahme*.py`, `github_*.py`, `kontingent.py`, `werkzeugkarte.py`, `vorgang_stream.py` | Aufträge vorbereiten, an den Dispatcher geben, Fortschritt, Prüfen, Einreichen |
| Modelle und Zugänge | `modellzugang.py`, `modellwahl.py`, `schluessel.py`, `boss.py`, `modellkarte.py` | Eigener Schlüssel je Profil (verschlüsselt), Modellwahl, Boss |
| Daten | `memory.py`, `learning.py`, `vorgaenge.py`, `fehlerbuch.py`, `canvas_*.py` | Gedächtnis, Lernen, Vorgänge, Fehlerbuch, Canvas |
| Labor | `labor*.py` | Eng begrenztes Profil: Pfadliste, Durchlauf, Einwilligung, Ticket-Werkzeuge, Löschfunktion |
| Betrieb | `sitzungen.py`, `sitzungen_bruecke.py`, `abschaltung.py`, `release_client.py`, `verteilung_api.py`, `einrichtung_api.py` | Eine Sitzung je Profil, Ablösen zwischen Slots, geordnetes Beenden, Stand der Release-Dienste, Installer, Prüfliste |

### 5.3 Ebene 2: weitere Bausteine

| Baustein | Teile | Hinweis |
|---|---|---|
| Oberfläche | `ui/src/app` (Seiten und `version.json`), `ui/src/components` (Karten, Canvas, Formulare), `ui/src/lib` (Zustand, Nachrichten, Schnittstellen) | Zentrale Zustandsverwaltung und Verbindung in `ui/src/lib/useWamo.ts`, Nachrichtenformate in `ui/src/lib/nachrichten.ts` |
| Host | `host/wamo_host.py` (Werkzeuge), `windows_control.py`, `uia_control.py` (UI Automation), `office_*.py`, `live_bild.py`, `host_http.py` | Der Host erzwingt Klassen und Freigaben selbst |
| Desktop | `desktop/main.js`, `preload.js`, `geraet.js`, `host-umgebung.js`, `update.js`, `livebild.js`, `markierung.js` | Brücke `window.wamoDesktop` zwischen Oberfläche und Rechner |
| Dienste auf dem Server | Dispatcher mit Kern-Kanal, Release-Dienst, Anker, Freigabe-Dienst, Prüfer-Sandbox, Haus-Proxy, Gerätedienst, Gateway für Fernzugriff, Labor-Dienst | Namen, Pfade und Schalter stehen in der Tabelle "Namensvertrag" in `CLAUDE.md` |

## 6. Laufzeitsicht

Quellen: `voice-core/bot.py`, `voice-core/auth_gate.py`, `voice-core/pc_freigaben.py`, `voice-core/dev_agent.py`, `infra/sokrates2/wamo_job_dispatch.py`. Die Sequenzdiagramme zu 6.1 bis 6.3 stehen in [`c4-diagramme.md`](c4-diagramme.md), Abschnitt 6.

### 6.1 Sprachgespräch mit Werkzeugaufruf und Freigabe

1. Die Oberfläche startet die Sitzung mit `POST /start` und sendet das WebRTC-Angebot. Die Zugangskontrolle prüft Token, zweiten Faktor, Höchstalter, aktives Profil und Erstanmeldung und schreibt die geprüfte Identität in den Body.
2. Der Bot baut die Pipeline: Mikrofon, Sprachaktivität (Silero), Spracherkennung (Soniox), Turn-Erkennung (Smart Turn und Satzende-Marker des Modells), Modell im Streaming, Sprachausgabe.
3. Die Stimmprüfung bewertet jede Äußerung und vergleicht sie mit den Abdrücken der Person (ein Abdruck je Mikrofon). Im Standardmodus `beobachten` misst sie nur und sperrt nichts, im Modus `streng` (nur auf ausdrücklichen Wunsch) verwirft sie fremde Stimmen. Für gesprochene PC-Befehle brauchen Mitglieder zusätzlich einen eingelernten Abdruck.
4. Ruft das Modell ein PC-Werkzeug auf, prüft der Kern Rechte (`rechte.py`), PC-Steuerung und PC-Sperre und leitet an den Host weiter. Der Host stuft die Aktion ein.
5. Eine kritische Aktion liefert `needs_approval`. Der Kern zeigt eine Freigabekarte. Erst der Klick der Person führt die Aktion einmal aus, vorher prüft der Host Ziel, Sperre und Adresse erneut.
6. Das Ergebnis geht als Fremdinhalt zurück ins Gespräch. Aktivitäten, Untertitel und Canvas erscheinen live in der Oberfläche.

### 6.2 Anmeldung mit Erstanmeldung

1. Die Person meldet sich mit Passwort und Code der Authenticator-App an. Das Token trägt `aal2` und `amr` mit dem Zeitstempel der Anmeldung.
2. Vor jeder Sitzung liest das Tor den Stand der Erstanmeldung. Im Stand `offen` sind nur `GET /wamo/api/erstanmeldung` und `POST /wamo/api/erstanmeldung/passwort` erlaubt, alles andere 403.
3. Die Person wechselt das Startpasswort. Der Kern reicht den Wechsel an den Anmeldedienst weiter, weil der Browser ihn dort nicht selbst aufrufen darf.
4. Danach führt die Oberfläche durch die Schritte (Token, API-Schlüssel, Installer, Prüfliste "Erste Schritte"). Ohne beides läuft alles über Hausmodelle.

### 6.3 Entwicklungsauftrag über den Kern-Kanal

1. Das Modell bereitet einen Auftrag vor. Der Kern prüft Zulassung, Schalter, Kostengrenzen und Auftragsart und zeigt eine Startkarte.
2. Nach dem Klick ruft der Kern den Dispatcher per SSH mit dem Schlüssel des Kern-Kanals auf. Der Dispatcher prüft die Regeln des Kanals in fester Reihenfolge und antwortet bei Verstoß mit `kanal_gesperrt`.
3. Er startet Claude Code in einer abgeschotteten Sandbox mit einem Platz je Person. Ereignisse und Fortschritt kommen als JSON-Zeilen zurück und erscheinen in der Aufgabenleiste.
4. Im persönlichen GitHub-Weg bleibt das Token außerhalb der Sandbox. Der Dispatcher meldet die Änderung, die Person liest die Karte und klickt "Einreichen". Erst dann gehen Push auf `wamo/<auftrag>` und Pull Request hinaus.

### 6.4 Release ohne Unterbrechung

1. Ein neuer Kern-Stand wird als Release in den inaktiven Slot gelegt und vorgeprüft.
2. Caddy schaltet per Include-Datei um. Neue Sitzungen gehen auf den neuen Slot, laufende bleiben auf ihrer Instanz (Pfad `/i/<slot>/`) und laufen aus.
3. Die Oberfläche wird als Container der anderen Farbe gebaut, geprüft (`GET /version.json`) und umgeschaltet. Der Rückweg ist dieselbe Handlung rückwärts.

### 6.5 Laborsitzung

1. Ein Laborprofil durchläuft dieselbe Zugangskontrolle, danach gilt eine feste Pfadliste.
2. Vor `/start` und jedem Angebot prüft der Kern beim Labor-Dienst Durchlauf und Einwilligung. Fehlt eine von beiden, endet es mit 403, ist der Dienst nicht erreichbar, mit 503.
3. Die Sitzung kennt nur Zeit, Websuche, Canvas und Ticket-Werkzeuge. Der Betreuer beendet den Durchlauf, die Oberfläche lädt neu.

## 7. Verteilungssicht

Quellen: `infra/sokrates2/README.md` (Abschnitte 0, 5, 6, 10, 12), `CLAUDE.md` (Namensvertrag), `docs/hausmodelle-und-kikollege.md` (Bestandsaufnahme 15.11.2026). Der tatsächliche Zustand des Servers ist nur laut README belegt, Stand je Abschnitt.

### 7.1 Knoten

| Knoten | Rolle | Dienste |
|---|---|---|
| Windows-PC der Person | Arbeitsplatz | Desktop-App oder Browser, Host (MCP) und Tunnelskripte, Chrome-Profil für den Browserbetrieb |
| Sokrates-2 | Zentraler Server im Büro | Supabase-Stack, Kern in zwei Slots, Oberfläche in zwei Farben, Caddy, Dispatcher mit Sandboxen, Release-Dienst, Anker, Freigabe-Dienst, Prüfer-Sandbox, Haus-Proxy, Gerätedienst, Gateway für Fernzugriff, Labor-Dienst, Runner für das Ausrollen |
| Sokrates-1 | Modellknoten | Zentrales LiteLLM-Gateway, Ollama mit Hausmodellen, Spracherkennung und Sprachausgabe im Haus (Container) |
| Caesar | Weiterer Knoten | Hausmodelle, Websuche im Haus (SearXNG) und Ziel des Fernzugriffs |
| Externe Dienste | Anbieter | Soniox (EU), Anthropic, GitHub, Jira |

### 7.2 Netze und Ports

Alle WAMO-Ports nehmen nur Verbindungen aus Loopback und dem Büro-LAN an. Unterwegs gilt der Weg über WireGuard ins Büronetz. Die Regeln setzt die Firewall `wamo-firewall` in der Kette `DOCKER-USER` (laut README seit 19.10.2026).

| Port | Dienst | Erlaubt |
|---|---|---|
| 55443 | API und Auth des Supabase-Stacks über HTTPS (Caddy) | Loopback, Büro-LAN |
| 55444 | Kern über HTTPS (Caddy vor dem Unix-Socket, kein TCP-Port am Kern) | Loopback, Büro-LAN |
| 55445 | Oberfläche über HTTPS (Caddy vor `wamo-ui`) | Loopback, Büro-LAN |
| 55446 | Gateway für Fernzugriff über HTTPS | Loopback und freigegebene Admin-Quellen |
| 55447 | Labor-Dienst über HTTPS | feste Quellen (Kette `WAMO-FW-LABOR`) |
| 55322, 56543 | Postgres über Supavisor mit TLS | Loopback und freigegebene Admin-Quellen |
| 55321 | HTTP-Zugang des Stacks, nur intern (Stufe 2) | Loopback und Caddy-Netz |
| 18090, 18080, 18081, 18765 | Haus-Proxy, Proxys der Prüfer-Sandbox, Labor-Dienst für den Kern | nur Loopback |

### 7.3 Wege zwischen den Knoten

| Weg | Beschreibung |
|---|---|
| Browser oder App zum Kern | HTTPS auf Port 55444 mit der internen CA. Weitere PCs importieren die CA einmal. |
| Kern zum Laptop | SSH-Rücktunnel je Gerät. Jeder Laptop hat einen eigenen Benutzer und Socket auf dem Server. Der Kern erreicht den Host nur über diesen Socket mit Bearer-Token. |
| Kern zum Dispatcher | SSH mit eigenem Schlüssel für den Kern-Kanal. Der Dispatcher erkennt den Kanal am Schlüssel. |
| Kern zu Gerätedienst, Release-Dienst und Labor-Dienst | Unix-Sockets beziehungsweise Loopback |
| Sandbox zum Netz | Ausgang nur über Regeln der Firewall und Proxys mit Allowlist |
| Kern zu Modellen | Über das LiteLLM-Gateway, Spracherkennung und Sprachausgabe im Haus über dieselbe Gateway-Wurzel |

### 7.4 Betriebsarten

| Art | Wo läuft der Kern | Hinweis |
|---|---|---|
| Büro | Dienst `wamo-core` (Vorlage `wamo-core@.service`, Slots a und b) auf dem Server | Alle Profile, PC-Werkzeuge über den Tunnel, Entwicklungsaufträge über den Kern-Kanal |
| Unterwegs | Auf dem eigenen PC, Host als Unterprozess über stdio | Standard laut README, der Host ist nicht im Netz erreichbar |

## 8. Querschnittliche Konzepte

### 8.1 Rechte und Freigaben

Quellen: `voice-core/rechte.py`, `voice-core/pc_mitglied.py`, `voice-core/pc_freigaben.py`, `voice-core/auth_gate.py`, `host/wamo_host.py`, `README.md` (Sicherheitsmodell). Die Matrix steht in [`../fachlich/rollen-und-rechte.md`](../fachlich/rollen-und-rechte.md).

| Ebene | Regel |
|---|---|
| Zugang | Token mit `aal2`, aktives Profil, Erstanmeldung erledigt. Jede Unsicherheit führt zur Ablehnung. |
| Rolle | `admin` und `mitglied`. Laborprofile sind immer Mitglieder mit eigener Pfadliste und nie Admin. |
| PC-Steuerung | `rechte.pc_stufe` liefert `admin`, `mitglied` oder keine Stufe. Mitglieder brauchen die Freischaltung je Profil. Für Mitglieder gelten zusätzlich Schutzregeln (eingelernter Stimmabdruck für gesprochene PC-Befehle, Karte nach Fremdinhalt, Einwilligung fürs Bildschirmbild). |
| Stimme | Die Stimme ist ein Hinweis, kein Zugangsschutz. Seit 18.11.2026 sperrt sie nichts, solange der Modus `beobachten` gilt (Standard von `WAMO_STIMME_PRUEFUNG`). Es schützen weiter zweiter Faktor und Freigabekarten. |
| Risikoklassen im Host | `read` sofort, `change` protokolliert, `critical` nur nach Karte, `blocked` nie. Das Modell kann keine Freigabe erteilen. |
| Freigabekarte | Gilt für eine Sitzung, befristet und genau einmal. Solange eine Karte offen ist, ruhen alle Eingaben. |
| Entwicklungsaufträge | Zulassung je Profil, Kostengrenzen, Kanalregeln im Dispatcher, Klick für Start und Einreichen. |

Inhalte aus Web, Dateien, Gedächtnis und Werkzeugen gelten als Daten und werden nie als Anweisung befolgt.

### 8.2 Gedächtnis

Quellen: `voice-core/memory.py`, `voice-core/learning.py`, `voice-core/gedaechtnis_api.py`.

Das Gedächtnis hat zwei Bereiche. `persoenlich` gehört genau einem Profil, `gemeinsam` gilt für alle, aber nur mit Status `aktiv`. Automatisch gelernte gemeinsame Einträge starten als `vorgeschlagen`. Ausdrücklich gemerkte Einträge von Admins sind sofort aktiv, die von Mitgliedern bleiben Vorschläge. Admins entscheiden in der Oberfläche über Vorschläge. Das Entscheiden läuft über eine Datenbankfunktion, der Kern hat kein Recht, den Status direkt zu ändern. Laborprofile haben kein Gedächtnis.

### 8.3 Namensvertrag

Quelle: `CLAUDE.md` (Tabelle "Namensvertrag").

Der Anzeigename ist "W.A.I.S." mit Schlusspunkt, gesprochen "Wais" (die Stimme bekommt "Ways"). Alle Kennungen bleiben `wamo`: Pakete `wamo-*`, Umgebung `WAMO_*`, Schemas `wamo_dev`, `wamo_test`, `wamo_prod`, Datenbankrollen `wamo_core` und `wamo_admin`, Dienste, Pfade. Konstanten des Anzeigenamens stehen in `voice-core/persona.py` und `ui/src/lib/anzeigename.ts`. Der Overlay-Fenstertitel und der Weckwort-Wert bleiben bewusst unverändert. Das Repo trägt auf GitHub seit 14.11.2026 den Namen `w.a.i.s`, `SELF_REPOS` führt jeden Namen, den es je trug.

### 8.4 Schalter und Rückwege

Quellen: `voice-core/env_schalter.py`, `infra/sokrates2/*-einrichten.sh`, `infra/sokrates2/*-rueckweg.sh`, `CLAUDE.md`.

Neue Fähigkeiten stehen hinter einem Schalter, Standard aus. Beispiele: `WAMO_ENTWICKLUNG_BUERO`, `WAMO_ENTWICKLUNG_GITHUB`, `WAMO_OFFICE` (Teile `dateien`, `outlook`, `teams`, `onenote`), `WAMO_JIRA`, `WAMO_PC_MITGLIEDER_PROFILE`. Server-Einstellungen setzt nur `wamo-core-env` über stdin, sie wirken mit dem nächsten Kern-Release. Fast jeder Dienst hat ein Paar Skripte `einrichten` und `rueckweg`, oft mit Probelauf (`--trocken`) und Sicherung des vorigen Standes. Der Notaus des Kern-Kanals ist eine Datei, die alle Starts sperrt. Die vollständige Liste: [`../technik/konfiguration.md`](../technik/konfiguration.md).

### 8.5 Fehlerbehandlung und Degradierung

Quellen: `voice-core/auth_gate.py`, `voice-core/werkzeug_wache.py`, `voice-core/fehlerbuch.py`, `voice-core/abschaltung.py`.

| Prinzip | Umsetzung |
|---|---|
| Fail closed | Nicht erreichbare Datenbank oder Anmeldedienst ergibt 503, nie einen Durchlass. Unbekannte Werte sperren. |
| Ehrliche Fehler | Abgebrochene Werkzeuge werden gemeldet, doppelte Aufrufe im selben Zug sauber behandelt. Das Fehlerbuch erklärt auf Nachfrage, warum etwas nicht ging, nur im Speicher der Sitzung. |
| Weiter sprechen | Ist der PC nicht erreichbar, sagt W.A.I.S. es und spricht weiter (laut README getestet am 20.10.2026). Im Modus "Nur Hausmodelle" gibt es keinen Rückfall auf Claude, im Modus "Automatisch" wählt der Boss unter den erreichbaren Modellen. |
| Feste Fehlercodes | Zugangskontrolle, Routen und Kern-Kanal melden maschinenlesbare Codes, siehe [`../technik/schnittstellen.md`](../technik/schnittstellen.md), Abschnitt 6. |
| Geordnetes Beenden | Beim Herunterfahren gelten Fristen unter dem Zeitlimit der Unit, damit der Slotwechsel nicht hängt. |
| Protokoll | Audit des Hosts als JSONL, Aktionen in der Tabelle `actions`, Dispatcher mit Zähler `kernkanal.jsonl`. Das Journal des Kerns enthält keine Gesprächsinhalte (Log-Stufe `INFO`). |

### 8.6 Abschottung von Entwicklungsaufträgen

Quellen: `infra/sokrates2/wamo_job_dispatch.py`, `voice-core/dev_guard.py`, `CLAUDE.md` (Prüfer-Sandbox, Haus-Proxy).

Aufträge laufen als eigener Benutzer in einer Sandbox ohne Zugang zu den Geheimnissen des Servers. Der Ausgang ist durch Firewall-Regeln begrenzt, die Ports je Platz sind getrennt. Ein Wächter vor jedem Werkzeugaufruf von Claude Code entscheidet nach Regeln im Code, nicht im Prompt. Das Repo von W.A.I.S. selbst ist für Aufträge gesperrt. Der Dispatcher prüft jeden Start gegen Regeln des Kanals, Grenzen je Person und Gesamtgrenzen. Fremder Code wird in einer eigenen Prüfer-Sandbox ohne Geheimnisse geprüft.

### 8.7 Blau und Grün, Kern-Slots

Quellen: `docs/selbstueberarbeitung.md`, `infra/sokrates2/wamo-core-slots.sh`, `ui/src/lib/kernSlot.ts`.

Der Kern läuft in zwei Instanzen (Slots a und b) mit eigenem Release-Ordner und eigenem Socket. Caddy leitet über `/i/<slot>/` und hält jede Sitzung auf ihrer Instanz, die alte Instanz läuft aus, bis ihre letzte Sitzung endet (höchstens `WAMO_MAX_SITZUNG_MIN`, Standard 120 Minuten laut Konzept). Eine Brücke löst Sitzungen zwischen den Instanzen ab ("eine Sitzung je Profil"). Die Oberfläche läuft als `wamo-ui-blau` und `wamo-ui-gruen`, Caddy zeigt über eine Include-Datei auf die aktive Farbe, die Gesundheitsprobe ist `GET /version.json`. Migrationen im Release sind nur erweiternd.

## 9. Architekturentscheidungen

Das Register mit Datum, Begründung, Folge und Quelle steht in [`entscheidungen.md`](entscheidungen.md). Die tragenden Entscheidungen im Überblick:

| Thema | Entscheidung | Nummer |
|---|---|---|
| Datenhaltung | Eigener Supabase-Stack, Kern nur mit Rolle `wamo_core` | E-01 |
| Zugang | Mehrere Profile, zweiter Faktor Pflicht, fail closed | E-02 |
| PC-Steuerung | Risikoklassen im Host, Freigabe nur per Klick, Tunnel je Gerät | E-04, E-09, E-23 |
| Release | Slots, blau und grün, vier getrennte Akteure bei der Selbstüberarbeitung | E-13, E-14 |
| Entwicklungsaufträge | Eigener Kern-Kanal, persönliche GitHub-Zugänge ohne Token in der Sandbox | E-18, E-35 |
| Modelle | Soniox und Claude als Start, Hausmodelle als Option | E-05, E-10, E-30 |
| Stimme | Die Stimme sperrt nichts, Standard `beobachten`, ein Abdruck je Mikrofon | E-33, E-34, E-40 |
| Ausrollen | Erstanmeldung, Installer vom Server, signierte Updates | E-27, E-28 |

## 10. Qualitätsanforderungen

Quellen: `README.md` (Stand 20.10.2026), `docs/gespraech-optimierung.md`, `docs/testlabor-wamo.md`, `docs/labor-lasttest.md`, Tests unter `voice-core/`, `host/`, `ui/src/`.

Zahlen stehen nur, wo sie im Repo belegt sind. Messwerte sind Momentaufnahmen mit Datum, keine Zusagen.

| Nr | Qualität | Szenario | Maß und Beleg |
|---|---|---|---|
| Q-1 | Latenz | Eine Person beendet einen Satz. Bis zum ersten Ton der Antwort vergeht die Zeit. | Büro: p50 1,32 s, p95 2,00 s, je 20 Fragen (laut README, 20.10.2026). Sitzungsprotokoll vom 31.10.2026: 1,4 bis 1,9 s in 11 von 15 Zügen, Ausreißer bis 6,1 s. Die Quellenlage nennt für die Praxis etwa 800 ms als Ziel (`docs/gespraech-optimierung.md`). |
| Q-2 | Unterbrechung | Die Person spricht dazwischen. W.A.I.S. verstummt, Rückmeldelaute stoppen nicht. | Verstummen im Median 1,3 s, 0 von 15 falschen Unterbrechungen (31.10.2026, `docs/gespraech-optimierung.md`). |
| Q-3 | Sicherheit, Zugang | Eine Anfrage kommt ohne zweiten Faktor, ohne aktives Profil oder bei gestörter Datenbank. | Abgelehnt mit 401, 403 oder 503, kein Werkzeug, keine Sitzung. Ende-zu-Ende-Test gegen den echten Stack 12 von 12 (laut README, 20.10.2026). Tests: `voice-core/test_auth_gate.py`. |
| Q-4 | Sicherheit, Freigabe | Das Modell verlangt eine kritische PC-Aktion, etwa Senden einer Nachricht. | Der Host antwortet mit `needs_approval`, ausgeführt wird erst nach dem Klick einmal und befristet. Tests: `host/test_security.py`, `voice-core/test_pc_freigaben.py`. |
| Q-5 | Sicherheit, Entwicklungsaufträge | Ein Auftrag soll eine Datei außerhalb seines Projekts ändern oder das Repo von W.A.I.S. berühren. | Wächter und Kanalregeln weisen ab. Der Vertragstest `voice-core/test_kernkanal_vertrag.py` prüft Kern und Dispatcher gegeneinander. |
| Q-6 | Verfügbarkeit | Ein neuer Kern-Stand wird ausgerollt, während Gespräche laufen. | Neue Sitzungen gehen auf den neuen Slot, laufende bleiben auf der alten Instanz, bis sie enden. Umschaltung am 02.11.2026 live geübt (laut README). |
| Q-7 | Verfügbarkeit | Der Tunnel zum Laptop bricht ab. | W.A.I.S. meldet "PC nicht erreichbar" und spricht weiter, danach wieder verbunden (laut README, Gesprächstest 20.10.2026). |
| Q-8 | Wartbarkeit | Ein Grund-Code des Kern-Kanals wird ergänzt. | Der Vertragstest schlägt fehl, bis beide Seiten dieselbe Liste führen. |
| Q-9 | Datenschutz, Stimme | Eine Person lernt ihren Stimmabdruck ein. | Nur nach ausdrücklicher Einwilligung (Version `stimme-3` nennt je Mikrofon einen Abdruck). Gespeichert wird je Mikrofon ein Zahlenvektor (192 Zahlen), höchstens drei je Person, nie eine Aufnahme. Löschen geht jederzeit. Beleg: `README.md` (Sicherheitsmodell, Stimmabdruck), `voice-core/stimme_einwilligung.py`, `voice-core/stimme_mikrofon.py`. |
| Q-10 | Datenschutz, Labor | Der Labortag ist vorbei. | Laborprofile werden gesperrt, alle Texte gelöscht, Löschfrist 11.12.2026. Test "danach ist nichts mehr da" (`docs/testlabor-wamo.md`, `voice-core/test_labor_loeschen.py`). |
| Q-11 | Last, Labor | Mehrere Plätze laufen gleichzeitig (am Labortag vier Besucher-Plätze, der Lasttest prüft bis acht Sitzungen). | Bestehensregel des Plans bei acht Sitzungen: p95 des ersten Tons höchstens 3500 ms und höchstens das 1,5-fache des Werts bei einer Sitzung, keine Abbrüche, CPU unter 70 Prozent, Speicher unter 2,8 GB, kein 429. Der volle Lasttest ist für Freitag 20.11.2026 geplant (`docs/testlabor-wamo.md`, `docs/labor-lasttest.md`). |

## 11. Risiken und technische Schulden

Quellen: `README.md` (Abschnitte "Stand" und "Offen"), `docs/labor-restplan.md`, `docs/persoenliche-zugaenge.md`, `docs/remote-desktop.md`, `docs/gespraech-optimierung.md`. Genannt sind nur Punkte, die das Repo bereits dokumentiert.

### 11.1 Risiken

| Nr | Risiko | Stand laut Repo | Gegenmaßnahme |
|---|---|---|---|
| RK-1 | Die Stimmerkennung war bei Mikrofon- oder Raumwechsel zu ungenau, Aufträge und Aktionen blieben stehen. | Standard ist `beobachten` seit 18.11.2026 abends, die Stimme sperrt nichts (`CLAUDE.md`, `README.md`). | Schutz bleibt über zweiten Faktor und Freigabekarten. Ein Abdruck je Mikrofon (höchstens drei, Migration 0029) mindert die Streuung. Mitglieder brauchen für gesprochene PC-Befehle einen eingelernten Abdruck. Recherche: `docs/stimme-recherche-2026-11-18.md`. |
| RK-2 | Wartezeit bis zum ersten Ton liegt über dem Ziel, einzelne Ausreißer bis 6,1 s. | Messung 31.10.2026, Maßnahmen und Schalter in `docs/gespraech-optimierung.md`. | Persona-Block, Wartesatz, Satz vor Werkzeug, Prompt-Cache vorwärmen. Schalter erst nach Messung an. |
| RK-3 | Ein gekaperter Kern sieht entschlüsselte persönliche Tokens. | Bewusst akzeptiert (Plan C, C4). | Token nie in der Sandbox, Push erst nach Klick, Schreiben nur auf eigenen Zweig. |
| RK-4 | Ein gestohlenes Anmelde-Token kann Fernsitzungen starten, bis die Anmeldung abläuft. | Restrisiko in `docs/remote-desktop.md` beschrieben. | Jeder Start geht als Hinweis an alle Admins. Ein Stufenschalter begrenzt das Alter des Codes. |
| RK-5 | Der Labortag am 28.11.2026 hängt an Ausweichwegen: Das Hausmodell als Ausweichweg bricht in Tests ab, ein Büro-Fall besteht nur 4 von 17 Läufen. | `docs/labor-restplan.md` (R9, R10), Stand 17.11.2026. | Laufende Messrunden, Lasttest am 20.11.2026, Freeze ab 23.11.2026. |
| RK-6 | Das gemeinsame Ratenlimit des einen Server-Schlüssels zeigt sich erst bei gleichzeitiger Last von Labor und Büro. | `docs/labor-lasttest.md`. | Der Lasttest misst es ausdrücklich. |
| RK-7 | Der Stand einzelner Pakete am Server ist nur dort prüfbar. Rauchtests des Kern-Kanals liefen laut README Stand 11.11.2026 noch nicht. | Mehrere Abschnitte in `README.md` und `infra/sokrates2/README.md` tragen den Zusatz "nicht ausgerollt". | Stufen mit eigenen Rauchtests je Dienst, siehe [`../betrieb/betriebshandbuch.md`](../betrieb/betriebshandbuch.md). |
| RK-8 | Zugänge zu Jira, Vercel und Supabase für Aufträge sind gesperrt, bis technische Konten und enge Token bereitstehen. | `README.md` (Abschnitt "Offen"), Vercel und Supabase persönlich erst nach dem 05.12.2026. | Schalter bleiben aus. |

### 11.2 Technische Schulden

| Nr | Schuld | Beleg | Hinweis |
|---|---|---|---|
| TS-1 | Migrationen 0010, 0011 und 0013 sind auf `wamo_prod` im Repo nicht als angewendet belegt. | `README.md` (Abschnitt "Offen") | Vor jedem Apply auf PROD prüft der Agent `database-reviewer`. |
| TS-2 | Das README trägt mehrere Stand-Abschnitte, ältere sind teilweise überholt und als solche markiert. | `README.md` | Diese Produktdokumentation soll die Lesbarkeit verbessern. Pflege: [`../dokumentationskonzept.md`](../dokumentationskonzept.md). |
| TS-3 | Einzelne Dateien sind sehr groß: `infra/sokrates2/wamo_job_dispatch.py` hat 5344 Zeilen, `host/wamo_host.py` 2820, `ui/src/lib/useWamo.ts` 2116, `voice-core/bot.py` 1961, `voice-core/dev_agent.py` 1938 (Zeilen je nach Arbeitsstand). | Zeilenzahl der Dateien | Teile sind schon in Module ausgelagert (zum Beispiel `wamo_job_kernkanal.py`, `wamo_job_github.py`). |
| TS-4 | Codesignatur des Installers: Der Weg ist eingebaut, das Zertifikat folgt. Ohne Zertifikat baut `npm run dist` unsigniert. | `README.md` (Windows-Installer) | Signierte Updates der App sind eigenständig gelöst (E-28). |
| TS-5 | Aktuelle Ergebnisse der Testläufe sind im Repo nicht zusammengefasst, das README nennt Zahlen vom 20.10.2026. | `README.md` | Teststrategie: [`../entwicklung/qualitaet-und-tests.md`](../entwicklung/qualitaet-und-tests.md). |
| TS-6 | Das Weckwort "Hey WAMO" ist vorgesehen und nicht umgesetzt. Hören und Stimme im Haus sind eingebaut, aber nicht umgestellt. | `CLAUDE.md` (Namensvertrag) | Soniox bleibt Standard (E-30). |

## 12. Glossar

Die Begriffe stehen in [`../glossar.md`](../glossar.md). Die wichtigsten, die dieses Dokument braucht: Kern (Voice-Core), Host, Slot, Freigabekarte, Kern-Kanal, Dispatcher, Anker, Stimmabdruck, Laborprofil, aal2.

## Weiterführend

- Diagramme (Kontext, Container, Komponenten, Verteilung, Sequenzen): [`c4-diagramme.md`](c4-diagramme.md)
- Entscheidungsregister: [`entscheidungen.md`](entscheidungen.md)
- Schnittstellen und Fehlercodes: [`../technik/schnittstellen.md`](../technik/schnittstellen.md)
- Aufbau des Kerns, der Oberfläche, des Hosts: [`../technik/voice-core.md`](../technik/voice-core.md), [`../technik/oberflaeche.md`](../technik/oberflaeche.md), [`../technik/host-und-desktop.md`](../technik/host-und-desktop.md)
- Betrieb und Sicherheit: [`../betrieb/betriebshandbuch.md`](../betrieb/betriebshandbuch.md), [`../sicherheit/sicherheit-und-datenschutz.md`](../sicherheit/sicherheit-und-datenschutz.md)
- Planpapiere: [`../../selbstueberarbeitung.md`](../../selbstueberarbeitung.md), [`../../entwicklung-im-betrieb.md`](../../entwicklung-im-betrieb.md), [`../../hausmodelle-und-kikollege.md`](../../hausmodelle-und-kikollege.md)
