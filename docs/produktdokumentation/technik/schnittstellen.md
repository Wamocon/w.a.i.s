# Schnittstellen von W.A.I.S.

| | |
|---|---|
| Zweck | Vollständige Referenz der Schnittstellen: HTTP-Routen des Kerns, Nachrichten zwischen Oberfläche und Kern, Werkzeuge des PC-Hosts, Schnittstelle zum Auftrags-Dispatcher und Fehlercodes. |
| Zielgruppe | Entwicklerinnen und Entwickler, Betrieb, Prüferinnen und Prüfer. |
| Dokumentart | Referenz |
| Stand | 19.11.2026, geprüft gegen Commit 497e3ce |
| Quellen | `voice-core/wamo_api.py`, `voice-core/auth_gate.py`, `voice-core/*_api.py`, `voice-core/bot.py`, `ui/src/lib/nachrichten.ts`, `ui/src/lib/useWamo.ts`, `host/wamo_host.py`, `voice-core/pc_host.py`, `infra/sokrates2/wamo_job_dispatch.py`, `infra/sokrates2/wamo_job_kernkanal.py` |

Der Code ist maßgeblich. Wo ein Modul unter `voice-core/` im Kopf einer Route etwas anderes sagt als der Handler, gilt der Handler. Begriffe wie Kern, Host, Slot und Freigabekarte stehen in [`../glossar.md`](../glossar.md).

## 1. Zugangsregeln für alle Wege

Jede HTTP-Anfrage an den Kern läuft zuerst durch die Zugangskontrolle `AccessMiddleware` in `voice-core/auth_gate.py`. Sie ist als einzige Middleware vor den Runner gehängt, `voice-core/kern_dienst.py` lässt den Server ohne sie nicht starten.

| Prüfung | Ergebnis bei Verstoß |
|---|---|
| Bearer-Token vorhanden, Signatur, Ablauf, Aussteller und Zielgruppe gültig | 401 |
| Zweiter Faktor (`aal2`) im Token | 403 `zweiter faktor fehlt` |
| Höchstalter der Anmeldung (`WAMO_ANMELDUNG_MAX_STUNDEN`, Standard 168 Stunden) ab Passwort und Code | 401, Code `anmeldung_zu_alt` |
| Aktives Profil in `<schema>.profiles` | 403 |
| Erstanmeldung erledigt (außer Laborprofile): sonst nur die zwei Wege aus Abschnitt 2.1 | 403 `passwort_wechsel_noetig` oder `startpasswort_abgelaufen` |
| Datenbank oder Anmeldedienst nicht erreichbar | 503 (fail closed, nie Durchlass) |
| WebSocket | wird abgelehnt, W.A.I.S. nutzt nur WebRTC |

Preflight (`OPTIONS`) bleibt offen, er trägt keine Daten. Die Routen unter `/wamo/api` holen die geprüfte Identität erneut über `wamo_api.identitaet`, die Profil-ID kommt nie aus Body oder Header. Antworten tragen bei den meisten Routen `Cache-Control: no-store`. Viele Routen begrenzen zusätzlich die Zahl der Anfragen je Profil (Ratengrenze, 429) und die Größe des Bodys.

Laborprofile (Testlabor, Rolle `mitglied` mit Laborkennung) erreichen nur eine feste Liste aus `voice-core/labor.py`: Start, WebRTC-Angebot und ICE-Updates, die Laborrouten und beim Schaufenster zusätzlich `GET /wamo/api/vorgaenge`. Alles andere endet mit 403 und dem Code `labor_pfad_gesperrt`.

## 2. HTTP-Routen des Kerns

Basis ist `https://<Server>:55444` (Caddy vor dem Unix-Socket des Kerns, siehe [`../architektur/arc42.md`](../architektur/arc42.md), Abschnitt 7). "Anmeldung" bedeutet die vollständige Prüfung aus Abschnitt 1. Jede Route hängt in einem Modul, das `ROUTEN_MODULE` in `voice-core/wamo_api.py` nennt. Das Modul `einwilligung_api` steht dort, die Datei fehlt im Repo, `wamo_api._module` überspringt sie.

### 2.1 Sitzung und Anmeldung

| Methode und Pfad | Zweck | Zugriff | Grenzen und Hinweise |
|---|---|---|---|
| `POST /start` | Pipecat-Runner: Sitzung anlegen. Die Middleware schreibt die geprüfte Identität in `body.wamo` und ersetzt jeden vom Client gesendeten Schlüssel `wamo`. | Anmeldung | Body höchstens 256 KB |
| `POST /api/offer`, `POST /sessions/<id>/api/offer` | WebRTC-Angebot (SDP), startet den Bot. Die Identität steht in `request_data.wamo`. | Anmeldung | Body höchstens 256 KB |
| `PATCH /api/offer`, `PATCH /sessions/<id>/api/offer` | ICE-Kandidaten nachreichen | Anmeldung | |
| `GET /wamo/slot` | Welcher Kern-Slot (a oder b) neue Sitzungen bekommt. Der Pfad ist eine Route von Caddy, nicht des Kerns. | ohne Token (Caddy `slot.inc`) | `ui/src/lib/kernSlot.ts` liest ihn vor dem Verbinden. Pfade `/i/a/` und `/i/b/` halten eine Sitzung auf ihrer Instanz |
| `GET /wamo/api/erstanmeldung` | Stand der Erstanmeldung: `keine`, `offen`, `abgelaufen`, `erledigt`, dazu `mindestlaenge` (12). Im Stand `offen` vermerkt sie den Beginn. | Anmeldung, auch im Stand `offen` und `abgelaufen` | Ratengrenze je Profil. Laborprofil 403 |
| `POST /wamo/api/erstanmeldung/passwort` | Startpasswort wechseln. Der Kern reicht den Wechsel mit dem eigenen Token an GoTrue weiter (`PUT /auth/v1/user` über Loopback), weil Caddy `PUT` auf `.../user` sperrt. | Anmeldung, nur im Stand `offen` | Ratengrenze je Profil. Passwort mindestens 12 Zeichen |
| `POST /wamo/release/<id>/freigeben` | Freigabe einer Änderung der Selbstüberarbeitung. Caddy leitet genau diesen Pfad am Kern vorbei an den Freigabe-Dienst des Ankers. | Token mit aal2 und zweitem Faktor höchstens 60 Sekunden alt, geprüft vom Freigabe-Dienst | Body `{"commit_id", "tree_id"}`. CORS nur für die Oberfläche auf Port 55445. Fehlercodes in Abschnitt 6.3 |

Quellen: `voice-core/auth_gate.py`, `voice-core/erstanmeldung_api.py`, `infra/sokrates2/wamo-caddy/kern/wamo-core.caddy`, `infra/sokrates2/anker/freigabe_dienst.py`.

### 2.2 Profil, Gedächtnis, Hinweise, Einrichtung

| Methode und Pfad | Zweck | Zugriff | Grenzen und Hinweise |
|---|---|---|---|
| `GET /wamo/api/einrichtung/stand` | Prüfliste der Ersteinrichtung ("Erste Schritte"): Punkte mit Stufe `gruen`, `rot` oder `hinweis` und je einem Satz. Nur lesen. | Anmeldung, nie Labor (403) | Ergebnis gilt kurz je Profil (Knopf "Erneut prüfen") |
| `GET /wamo/api/hinweise` | Neueste 50 eigene Hinweise und Zahl der ungelesenen | Anmeldung | |
| `POST /wamo/api/hinweise/gelesen` | Alle eigenen Hinweise quittieren | Anmeldung | |
| `POST /wamo/api/hinweise/{id}/gelesen` | Einen eigenen Hinweis quittieren | Anmeldung | 404 bei unbekanntem Hinweis |
| `GET /wamo/api/gedaechtnis/vorschlaege` | Offene Vorschläge für das gemeinsame Gedächtnis | Rolle `admin` | Ratengrenze |
| `POST /wamo/api/gedaechtnis/entscheiden` | Vorschlag `freigeben` oder `ablehnen`, Antwort `ergebnis` `freigegeben`, `abgelehnt` oder `nicht_offen` | Rolle `admin` | Ratengrenze. Entscheiden nur über die Datenbankfunktion `gedaechtnis_vorschlag_entscheiden` (Migration 0020) |
| `GET /wamo/api/vorgaenge` | Letzte 20 eigene Vorgänge (Aufgabenleiste), neueste zuerst | Anmeldung, beim Schaufenster-Laborprofil erlaubt | Tabelle `vorgaenge` (Migration 0017) |
| `GET /wamo/api/canvas/historie` | Geschlossene und ältere Canvas-Elemente: `eigene` und `geteilte`, je `id`, `titel`, `art`, `zeit` | Anmeldung, Laborprofil 403 `labor_pfad_gesperrt` | Nur Titel, Art und Zeit, nie Inhalte. Wieder geöffnet wird über `GET /geteilt/canvas/{id}` |
| `GET /wamo/api/admin/neue-mitglieder` | Einrichtungsstand je Profil (ohne Laborprofile), nur Stände und Ja oder Nein | Rolle `admin`, kein Laborprofil | Ratengrenze. Funktion `neue_mitglieder` (Migration 0022) |

Quellen: `voice-core/einrichtung_api.py`, `voice-core/hinweise_api.py`, `voice-core/gedaechtnis_api.py`, `voice-core/vorgaenge_api.py`, `voice-core/canvas_historie.py`, `voice-core/mitglieder_admin_api.py`.

### 2.3 Modelle, Schlüssel und persönliche Zugänge

| Methode und Pfad | Zweck | Zugriff | Grenzen und Hinweise |
|---|---|---|---|
| `GET /wamo/api/modellzugang` | Stand des eigenen Modellzugangs (nur "hinterlegt" und die letzten vier Zeichen) | Anmeldung, Laborprofil 403 `labor_pfad_gesperrt` | no-store |
| `POST /wamo/api/modellzugang` | Aktion im Feld `aktion`: `hinterlegen`, `loeschen`, `modus`, `stimme`, `modell`, `haus_stimme`, `status`. Gleiche Funktion wie die Client-Nachricht `modellzugang`. | Anmeldung, kein Laborprofil | Body wird nie geloggt. Ratengrenzen für Testanfragen, Modellwahl und Stimme. Fehler stehen als Text im Feld `fehler` der Antwort |
| `GET /wamo/api/github-zugang` | Stand des eigenen GitHub-Zugangs (Art, Login, Rechte, Ablauf, letzte vier Zeichen) | Anmeldung, kein Laborprofil | no-store |
| `POST /wamo/api/github-zugang` | Aktion `stand`, `speichern` (Feld `token`), `pruefen`, `loeschen` | Anmeldung, Speichern und Prüfen nur mit Zulassung für Entwicklungsaufträge und `WAMO_ENTWICKLUNG_GITHUB=an` | Ratengrenze für Prüfungen bei GitHub. Löschen geht immer |
| `GET /wamo/api/admin/github-rechte` | Je Profil die erlaubten Ausnahmen der Token-Rechte und der Stand ohne Wert | Rolle `admin`, kein Laborprofil | Ratengrenze |
| `POST /wamo/api/admin/github-rechte` | `user_id` und `scopes_ausnahmen` setzen, nur Werte aus `SCOPES_AUSNAHMEN` | Rolle `admin` | Ratengrenze. Jede Änderung als Zeile in `actions` (Werkzeug `github_rechte`) |

Quellen: `voice-core/modellzugang_api.py`, `voice-core/github_zugang_api.py`.

### 2.4 Geräte, Büro und Fernzugriff

| Methode und Pfad | Zweck | Zugriff | Grenzen und Hinweise |
|---|---|---|---|
| `GET /wamo/api/geraet/herausforderung` | Einmal-Herausforderung für die Bindung des Laptops (an das Profil gebunden, 5 Minuten) | Anmeldung, nur Büro-Kern (`WAMO_BETRIEB=buero`), sonst 404 | 429 bei zu vielen Versuchen |
| `POST /wamo/api/geraet/binden` | Gerät binden: Schlüssel, Rechnername, Signatur der Herausforderung. Antwort bei aktivem Gerät mit Tunnelziel. | Anmeldung, nur Büro-Kern | Regeln der Erstbindung in Migration 0002. 400 bei ungültiger Signatur, 403 bei fremdem Gerät, 429 bei zu vielen Geräten |
| `GET /wamo/api/geraete/verwaltung` | Alle persönlichen Geräte aller Profile ohne Schlüsselmaterial | Rolle `admin` | Ratengrenze |
| `POST /wamo/api/geraete/verwaltung/aktion` | Gerät freigeben, sperren, entsperren oder widerrufen (`kennung`, `aktion`, `grund`, `fingerabdruck`) | Rolle `admin` und zweiter Faktor höchstens 120 Sekunden alt, sonst 403 `zweiter_faktor_zu_alt` | Ratengrenze. Fingerabdruck ist Pflicht bei Freigeben und Entsperren, ein Grund bei Sperren und Widerruf |
| `GET /wamo/api/buero/status` | Bürogeräte mit Ampel, Klartext und Kennzahlen, dazu die Zahl unbekannter Geräte | Anmeldung (jede Rolle), nur Büro-Kern, sonst 503 | Antwortfelder fest, keine Namen oder Adressen unbekannter Geräte |
| `POST /wamo/api/buero/steuern` | Gerät `an`, `aus`, `lauter`, `leiser`, `stumm`, `laut` (nur Fernseher, Lautsprecher, Steckdosen) | Rolle `admin` | Der Gerätedienst prüft Rechte und hat eine eigene Grenze. Jeder Versuch steht in `actions` |
| `GET /wamo/api/buerogeraete` | Bürogeräte mit Fähigkeiten | Anmeldung, nur Büro-Kern | |
| `GET /wamo/api/scans` | Eigene Einträge der Ablage (Scans, NAS-Dateien) | Anmeldung, nur Büro-Kern | |
| `GET /wamo/api/scans/{id}` | Eigene Datei herunterladen (Anhang) | Anmeldung | `id` 32 Hexzeichen, sonst 404 |
| `DELETE /wamo/api/scans/{id}` | Eigenen Eintrag löschen | Anmeldung | |
| `GET /wamo/api/rd/ziele` | Ziele des Fernzugriffs mit Zustand `frei`, `belegt`, `nicht_erreichbar` | Rolle `admin` | Ratengrenze |
| `POST /wamo/api/rd/start` | Fernsitzung starten (`{"ziel": "sokrates2"}`), liefert die Adresse der Gateway-Seite | Rolle `admin`. Alter des Codes begrenzt `WAMO_RD_ANMELDUNG_MAX_MIN`, sonst 403 `zweiter_faktor_zu_alt` | Ziel nur aus `/etc/wamo-rd/ziele.toml`. Höchstens 3 Sitzungen gleichzeitig und 6 Starts je Stunde und Profil |
| `POST /wamo/api/rd/ende` | Eigene Fernsitzung beenden (`{"sitzung": "<uuid>"}`) | Rolle `admin` | Ratengrenze |
| `GET /wamo/api/release/status` | Stand des Release-Dienstes in geprüfter Sicht. Ist der Dienst weg, kommt 200 mit `{"verfuegbar": false, "grund": ...}`. | Rolle `admin` | Ratengrenze |

Quellen: `voice-core/geraet_api.py`, `voice-core/geraete_admin_api.py`, `voice-core/buero_api.py`, `voice-core/geraete_api.py`, `voice-core/rd_api.py`, `voice-core/release_api.py`.

### 2.5 Geteilte Arbeit und Installer

Alle Routen in `voice-core/teilen_api.py` verlangen die Anmeldung. Besitz und Teilung prüft `voice-core/teilen.py`.

| Methode und Pfad | Zweck | Hinweise |
|---|---|---|
| `GET /wamo/api/profile` | Aktive Profile außer dem eigenen (Empfängerwahl) | |
| `GET /wamo/api/teilen` | Laufende Teilungen `von_mir` und `mit_mir` | |
| `POST /wamo/api/teilen` | Teilen: `art` (`canvas`, `auftrag`, `datei`, `scan`), `objekt`, `empfaenger`, `recht`, optional `hinweis` | |
| `POST /wamo/api/teilen/{id}/recht` | Recht ändern | nur Besitzer |
| `POST /wamo/api/teilen/{id}/widerrufen` | Teilung widerrufen | nur Besitzer |
| `POST /wamo/api/teilen/{id}/zurueckgeben` | Teilung zurückgeben | nur Empfänger |
| `GET /wamo/api/teilen/{id}/protokoll` | Protokoll einer Teilung | nur Besitzer |
| `GET /wamo/api/teilen/{id}/dokumente` | Ergebnisdokumente eines geteilten Projekts | |
| `GET /wamo/api/geteilt/canvas/{id}` | Neueste Fassung eines Canvas (eigen oder geteilt) mit Fassungsnummer | |
| `PUT /wamo/api/geteilt/canvas/{id}` | Neue Fassung (`inhalt`, `basis`) | Besitzer oder Recht `bearbeiten`, 409 bei Konflikt |
| `GET /wamo/api/dateien` | Eigene Dateien ohne Inhalt | |
| `POST /wamo/api/dateien` | Datei hochladen, Rohdaten im Body, Name URL-kodiert im Header `X-Dateiname` | Größenobergrenze im Kern. Caddy erlaubt hier bis 26 MiB, sonst 512 KB |
| `GET /wamo/api/dateien/{id}` | Herunterladen, immer als Anhang | Besitzer oder Empfänger |
| `POST /wamo/api/dateien/{id}/fassung` | Neue Fassung | wie Upload |
| `POST /wamo/api/dateien/{id}/loeschen` | Datei weich löschen, widerruft laufende Teilungen | nur Besitzer, endgültig nach 7 Tagen |
| `GET /wamo/api/installer` | Stand der Installer-Ablage: exaktes `manifest`, `signatur`, geprüfte Felder `v`, `produkt`, `version`, `datei`, `groesse`, `sha256`, `bauzeit`, `commit` | Laborprofil 403 `installer_labor`. Ratengrenze |
| `GET /wamo/api/installer/datei` | Installer genau aus dem Manifest, Range möglich | Ratengrenze je Stunde und Profil, 429 `installer_zu_oft`, 503 `installer_fehlt`. Jeder Download steht in `actions` (Werkzeug `installer_download`) |

Quellen: `voice-core/teilen_api.py`, `voice-core/verteilung_api.py`, `infra/sokrates2/wamo-caddy/kern/wamo-core.caddy`.

### 2.6 Weitere Endpunkte ohne Kern

| Endpunkt | Zweck | Quelle |
|---|---|---|
| `GET /version.json` der Oberfläche | Gesundheitsprobe und Build-Angaben der Oberfläche, Grundlage des Umschaltens von Blau und Grün | `ui/src/app/version.json/route.ts`, `ui/src/lib/buildInfo.ts` |
| Host-HTTP (`--http`) | MCP über Streamable HTTP nur auf Loopback (`WAMO_HOST_BIND`, Standard `127.0.0.1:8765`), Bearer-Token aus `WAMO_HOST_TOKEN_FILE`. Erreichbar für den Kern nur über den SSH-Rücktunnel. | `host/wamo_host.py`, `host/host_http.py` |
| Release-Dienst (`ctl.sock`) | Unix-Socket, Befehle `status`, `anfordern`, `abbrechen`, `zurueck`. Der Kern darf nur `status` und `anfordern`. Freigaben nimmt der Release-Dienst nie an. | `infra/sokrates2/release/wamo_release.py` |
| Labor-Dienst | Aufrufe V1 bis V7 des Kerns an den Dienst des Testlabors | [`../../labor-dienst-vertrag.md`](../../labor-dienst-vertrag.md) |

## 3. Nachrichten zwischen Oberfläche und Kern

Die Oberfläche spricht mit dem Kern über eine WebRTC-Verbindung (Pipecat, RTVI). Sprache läuft als Audio, alles andere als Nachrichten mit `type`. Der Kern prüft jede Client-Nachricht gegen feste Listen. In Laborsitzungen verwirft `voice-core/labor_rtvi.py` alles außer `client-ready`, `send-text` (in der Länge begrenzt) und der Freigabe mit `job` `labor`.

### 3.1 Client zu Kern

Typen der Oberfläche in `ui/src/lib/useWamo.ts` (`ClientMessage`), Auswertung in `voice-core/bot.py` (`on_client_message`) und `voice-core/dev_agent.py`.

| `type` | Felder in `data` | Wirkung und Voraussetzung |
|---|---|---|
| `freigabe` | `job`, `id`, `entscheidung` (`ja` oder `nein`) | Klick auf eine Freigabekarte. `job` `pc` (PC-Aktion), `geraet` (Bürogerät), `labor` (nur Laborsitzung), `jira` (Jira-Story), sonst Entwicklungsaufträge. Karte und Klick gehören zur selben Sitzung |
| `vergessen` | `id` | Eigenen Gedächtniseintrag deaktivieren, Antwort `vergessen` |
| `pc_steuerung` | `an` | PC-Steuerung ein oder aus. Ein nur mit Stufe (`rechte.pc_stufe`), eingerichtetem Host und freier PC-Sperre, aus geht immer |
| `bildstrom` | `aktion` (`an`, `aus`, `monitor`, `ack`, `anfordern`), `monitor`, `seq`, `token` | Live-Bild des eigenen Laptops, nur mit Stufe der PC-Steuerung, gebundenem Gerät und PC-Steuerung an |
| `modellzugang` | `aktion` wie bei `POST /wamo/api/modellzugang`, `schluesselart` (`api`, `code`), `schluessel`, `workspace`, `modus`, `stt`, `tts`, `bereich`, `modell`, `stimme` | Modellzugang ohne Umweg über HTTP. Inhalt wird nie geloggt |
| `github_zugang` | `aktion`, `token` | Wie `POST /wamo/api/github-zugang` |
| `stimmabdruck` | `aktion` `start` (mit `einwilligung`, optional `mikrofon` als Name des Mikrofons im Gespräch), `abbrechen`, `loeschen` (optional `mikrofon` als Kennung, ohne Angabe alle Abdrücke) | Stimmabdruck einlernen, abbrechen oder löschen. Nur per Klick, nie per Sprache, nie im Labor. Einlernen nur mit der aktuellen Version der Einwilligung (`stimme-1` bis `stimme-3`), ersetzt nur den Abdruck dieses Mikrofons. Ersetzen und Löschen verlangen seit 18.11.2026 nur im Modus `streng` einen Nachweis |
| `mikrofontest` | `aktion` `start` | Mikrofontest in den Einstellungen: Der Kern unterbricht eine laufende Antwort von W.A.I.S., die Oberfläche schaltet die Wiedergabe stumm. Keine Antwortnachricht, nie im Labor |
| `kontingent` | leer | Stand des Max-Abos abfragen (gespeicherter Stand) |
| `auftrag_start` | `job`, `entscheidung` | Klick "Starten" oder Ablehnen auf der Startkarte eines Entwicklungsauftrags |
| `einreichen` | `job`, `commit_id`, `tree_id`, `bestaetigt[]` | Persönlicher GitHub-Weg: Änderung einreichen (Push und Pull Request) nach der Karte |
| `verwerfen` | `job` | Persönlicher GitHub-Weg: Änderung verwerfen |
| `auftrag_entwurf` | `aktion` `liste`, `speichern` (`job`), `laden` und `loeschen` (`id`) | Gespeicherte Entwicklungsaufträge (Tabelle `auftrag_entwuerfe`, Migration 0026) |
| `jira_story` | `canvas_id` | Knopf "Als User Story in Jira", legt nur die Karte an, nie die Story |
| `canvas_export` | `canvas_id`, `format` | Canvas als Datei am PC speichern (`WAMO_OFFICE=dateien`) |
| `datei_oeffnen` | `kennung`, `ordner` | Gespeicherte Datei oder ihren Ordner öffnen |
| `mail_vorbereiten` | `canvas_id`, `an[]`, `cc[]`, `betreff`, `text`, `anhang` | Mail über Outlook zur Freigabe vorbereiten (`WAMO_OFFICE=outlook`) |
| `mail_zurueckholen` | `id` | Geplanten Versand zurückholen |
| `onenote_seite` | `canvas_id` | Canvas als OneNote-Seite, erst nach der Karte (`WAMO_OFFICE=onenote`) |
| `teams_vorbereiten` | `an[]`, `gruppenname`, `text` | Teams-Chat mit vorbefülltem Text vorbereiten (`WAMO_OFFICE=teams`). Gesendet wird in Teams nur von der Person |
| `canvas_aktiv` | `canvas_id` oder null | Offener Reiter des Canvas, das Modell bekommt einen Systemhinweis ohne Antwort |

Die Office-Nachrichten gehen nur in Sitzungen mit Stufe der PC-Steuerung und dem jeweiligen Teil von `WAMO_OFFICE`, nie im Labor. Ohne die Voraussetzung loggt der Kern eine Abweisung und antwortet nicht.

### 3.2 Kern zu Client

Typen in `ui/src/lib/nachrichten.ts` (`ServerMessage`, `parseServerMessage` verwirft Unbekanntes und Unvollständiges), Sender in `voice-core/bot.py` und den Modulen.

| `type` | Inhalt | Anlass |
|---|---|---|
| `profil` | `name`, `rolle` | beim Verbinden |
| `betrieb` | `modus` (`lokal`, `buero`), `modelle` (`llm`, `stt`, `tts`), `pc` (`verbindet`, `verbunden`, `getrennt`, `aus`, `gesperrt`), `ort`, `pcLatenzMs`, `pcSteuerung`, `pcStufe` (`admin`, `mitglied`), `entwicklung`, `entwicklungGrund`, `pcName`, `pcBelegt`, `modellModus`, `modellQuelle`, `modellHinweis`, `office[]`, `mail`, `onenote`, `teams`, `spracheGrund` | beim Verbinden und wenn der PC-Host steht |
| `canvas` | `item` (Tabelle, Code, Dokument, Mermaid, Bild), optional `ersetzt` | Modell zeigt oder überarbeitet ein Element |
| `canvas_schliessen` | `ziel` `offen`, `alle` oder `ids` mit `ids[]` | Werkzeug `canvas_schliessen` |
| `aktivitaet` | `id`, `name`, `detail`, `status` (`laeuft`, `fertig`, `abgelehnt`, `fehler`, `wartet`) | Werkzeug-Zeitleiste |
| `vorgang` | `vorgang` (Art, Status, Schritte, Kriterien) | Aufgabenleiste |
| `freigaben` | `job`, `projekt`, `items[]` | Freigabekarte eines Entwicklungsauftrags |
| `auftrag` | Startkarte eines Auftrags ohne Zustand (den setzt allein die Oberfläche) | Entwicklungsauftrag vorbereitet |
| `auftrag_quittung` | `job`, `ok`, `grund` | Antwort auf `auftrag_start` |
| `auftrag_entwuerfe` | `aktion`, `ok`, `text`, `job`, `entwuerfe[]`, `max` | Antwort auf `auftrag_entwurf` |
| `gemerkt` | `bereich`, `status`, `text`, `id` | nach jedem gespeicherten Gedächtniseintrag |
| `vergessen` | `id`, `ok` | Antwort auf `vergessen` |
| `modellzugang` | Stand, Modellwahl je Aufgabe, Stimmwahl, `fehler` | Antwort auf `modellzugang` |
| `github_zugang` | Stand des GitHub-Zugangs, `verfuegbar`, `fehler` | Antwort auf `github_zugang` |
| `kontingent` | Limits des Max-Abos | Antwort auf `kontingent` und bei Beobachtung |
| `stimme` | Stand (`aus`, `fehlt`, `laedt`, `kaputt`, `bereit`) mit `modus` (`aus`, `beobachten`, `streng`) oder Ergebnis (`eigen`, `fremd`, `unklar`) mit `wert`, `ignoriert`, `zeit` | nach jedem Urteil der Stimmprüfung. Standardmodus ist `beobachten` (messen und anzeigen, nichts sperren), `ignoriert` gibt es nur im Modus `streng` |
| `stimmabdruck` | `status` (`start`, `aufnahme`, `rechnet`, `fertig`, `fehler`, `abgebrochen`, `geloescht`), `sekunden`, `ziel`, `text`, `mikrofon` (Kennung bei `fertig` und beim Löschen eines einzelnen Abdrucks) | Einlernen |
| `stimmabdruck_mikrofone` | `mikrofone[]` mit `kennung`, `name`, `am`, dazu `max` (höchstens 3, ohne Migration 0029 nur 1) | eingelernte Mikrofone, ein Abdruck je Mikrofon (`voice-core/stimme_mikrofon.py`) |
| `stimmabdruck_einwilligung` | `version` (`stimme-1`, im Schattenbetrieb `stimme-2`, mit Abdrücken je Mikrofon `stimme-3`), `text` | beim Verbinden |
| `mikrofon` | `zustand` (`still`, `fehlt`, `ok`), `sekunden` | 10 Sekunden digitale Stille, 5 Sekunden ohne Audiopakete, wieder Ton |
| `sprecher` | `index` | aktiver Sprecher der Anzeige |
| `leiser_stopp`, `stimme_leiser` | `sofort`, `an` | weiche Unterbrechung der Stimme |
| `bildstrom`, `bild` | Zustand, Monitor, Bild als JPEG mit `seq`, `restS` | Live-Bild (Rückstau über `ack`) |
| `markierung` | Rechteck und Punkt des Zielfensters | Rahmen am gesteuerten Fenster, die Desktop-App zeichnet ihn |
| `fernzugriff_oeffnen` | keine Nutzdaten | Oberfläche zeigt den Abschnitt Fernzugriff, gestartet wird nur per Klick |
| `datei` | `ok`, Kennung, Name, Ordner, Pfad oder `grund` | Antwort auf `canvas_export`, nie ein Dateiinhalt |
| `mail_antwort`, `mail_versand` | `ok`, `grund`; `id`, `zustand`, `restS`, `text` | Antworten auf Mail-Nachrichten, nie ein Inhalt |
| `onenote`, `teams_antwort` | `ok`, `text` oder `grund` | Antworten auf die Nachrichten |
| `jira_status`, `jira_ergebnis` | Projekte und Standard; `ok`, `text`, `schluessel`, `link` | Jira-Stories |
| `sitzung_beendet` | `grund`, `anmelden` | Sitzung vom Kern beendet, optional mit Aufforderung zur neuen Anmeldung |
| `labor_durchlauf_ende` | keine Felder | Betreuer beendet den Durchlauf, die Seite lädt neu |

Daneben sendet Pipecat selbst `bot-output` (Antworttext mit Wortfortschritt) und `user-transcription` (Transkript der Person). Die Oberfläche zeigt Sätze der Person im strengen Stimmmodus erst nach der Meldung `stimme` mit `zeit` (`ui/src/lib/stimmFilter.ts`).

## 4. Werkzeuge des PC-Hosts

Der Host (`host/wamo_host.py`, MCP) erzwingt Risikoklassen selbst, nicht der Prompt. Klassen: `read` sofort, `change` sofort und protokolliert, `critical` nur als Freigabe-Anfrage, ausgeführt erst nach dem Klick der Person, `blocked` nie. Jeder Aufruf steht im Audit-Log `host/wamo_audit.jsonl`. Ob ein Werkzeug das Sprachmodell sieht, regelt `LLM_TOOLS` in `voice-core/pc_host.py`. Admins und freigeschaltete Mitglieder bekommen dieselbe Liste.

| Werkzeug | Klasse laut Audit | Sieht das Modell |
|---|---|---|
| `system_info`, `fenster_auflisten`, `elemente_auflisten`, `element_lesen`, `browser_lesen` | `read` | ja (außer `fenster_auflisten` und `element_lesen` je nach Liste, siehe `LLM_TOOLS`) |
| `powershell_lesen` | `read` bei reinen Get- und Test-Befehlen, `critical` bei allem, was sich nicht sicher als Lesen einstufen lässt, `blocked` bei gesperrten Befehlen | ja |
| `sperre_pruefen`, `live_bild_status`, `bild_holen`, `live_bild_beenden`, `bildschirmfoto` | `read` | nein, nur der Kern ruft sie auf |
| `webseite_oeffnen`, `programm_oeffnen`, `ordner_anlegen`, `oeffnen_mit`, `fenster_fokussieren`, `dark_mode`, `maus_scrollen` | `change` | ja |
| `tastatur_tippen`, `tasten_druecken` | `change`, `critical` wenn das Ziel ein Mail- oder Messenger-Fenster ist und die Eingabe sendet | ja |
| `element_klicken`, `element_text_setzen` | `change`, `critical` bei Mail- und Messenger-Fenstern, Systemfenstern und Elementen zum Senden, Bezahlen, Löschen oder Veröffentlichen | ja |
| `maus_klicken` | `change`, `critical` in Mail- und Messenger-Fenstern | nein, nur der Kern (Koordinaten aus dem Bildmodell) |
| `git_klonen` | `change` | ja |
| `github_repo_anlegen` | `critical` | ja |
| `live_bild_anfordern` | `change` | nein |
| `office_faehigkeiten` | `read` | nein |
| `office_datei_erstellen`, `office_datei_oeffnen` | `change` (Dateien nur in `Dokumente\WAIS`, Sperre `office.aus`) | nein |
| `outlook_mail_anfragen` | `critical` bei Senden über das klassische Outlook, `change` bei einem Entwurf im neuen Outlook, beides erst nach der Karte | nein |
| `outlook_zurueckholen`, `outlook_versand_status` | `change`, `read` | nein |
| `onenote_seite_anfragen` | `critical` | nein |
| `teams_chat_anfragen` | `critical`, W.A.I.S. sendet in Teams nie selbst | nein |
| `freigabe_entscheiden` | Ausführung einer freigegebenen Anfrage | nie, nur der Kern nach dem Klick, dazu ein zweites Geheimnis neben dem Bearer-Token |

Eine Freigabe gilt `FREIGABE_GUELTIG_SECS` lang und wird genau einmal ausgeführt. Direkt davor prüft der Host Ziel, Sperre und Adresse erneut. Solange eine Anfrage offen ist, ruhen alle Eingaben (`status=wartet`). Bei gesperrtem Bildschirm gibt es keine Eingaben, Klicks, Fotos, kein Öffnen und kein Lesen. Das Verhalten im Einzelnen: [`host-und-desktop.md`](host-und-desktop.md).

## 5. Schnittstelle zum Auftrags-Dispatcher

Der Dispatcher (`infra/sokrates2/wamo_job_dispatch.py`, `VERSION = "10"`) ist das Forced Command der SSH-Schlüssel auf Sokrates-2. Der Kern ruft ihn mit dem Schlüssel `wamo-kern-jobs` auf. Der Kanal ergibt sich aus dem benutzten Schlüssel (`ExposeAuthInfo`), nie aus der Adresse: `lokal` (ohne SSH), `pc` (Schlüssel aus `authorized_keys.d/wamo`) und `kern` (Schlüssel aus `authorized_keys.d/wamo-kern`, gewinnt vor `pc`). Regeln des Kern-Kanals stehen in `infra/sokrates2/wamo_job_kernkanal.py`, Regeldatei ist `/etc/wamo/kernkanal.conf`.

### 5.1 Befehle

| Befehl | Argumente | Zweck |
|---|---|---|
| `ping` | | Erreichbarkeit, Version, Kanal, `kernkanal.arten`, `haus` |
| `start` | `<job> <projekt> <art> [<session>]`, stdin: Kopfzeile als JSON, optional zweite Zeile mit dem persönlichen Claude-Zugang | Auftrag ausführen. Danach bleibt stdin als Lebenslinie offen, endet sie, endet der Auftrag |
| `status` | `<job>` | Zustand des Auftrags |
| `pending` | `<job>` | Offene Freigabe-Anfragen, geprüft |
| `approve` | `<job> <fingerabdruck>` | Freigabe für den nächsten Lauf |
| `cancel` | `<job>` | Laufenden Auftrag beenden |
| `pruefen` | `<job>` | Ein Befehl der Abnahme in der Sandbox (Standard aus, Schalter `WAMO_PRUEFEN=an` in `geheim.env`) |
| `aenderung`, `einreichen`, `verwerfen` | `<job> <profil>` | Persönlicher GitHub-Weg: Änderungsübersicht, Push mit Pull Request, Kandidat löschen |
| `aufraeumen` | `[alle]` | Nur lokal (Timer, Rückweg): Kopien privater Repos löschen |

Im Kern-Kanal gilt die Liste `BEFEHLE_KERN` (ohne `pruefen` und `aufraeumen`). Bei geschlossenem Kanal gehen nur `ping`, `status`, `pending`, `cancel`, `aenderung` und `verwerfen`, bei Notaus nur `ping` und `status`. Kopffelder von `start`: `auftrag`, `system`, `modell`, `repo`, `zugang` (`folgt`, `server`, `haus`), `profil` (8 Hexzeichen, Pflicht bei `folgt` und `haus`), `github` (`persoenlich`) und `scopes_ausnahmen`. Im Kern-Kanal sind nur `folgt` und `haus` erlaubt (`ZUGAENGE_KERN`).

### 5.2 Ereignisse und Exit-Codes

Der Dispatcher schreibt auf stdout Zeilen `{"type": "wamo", "ereignis": ...}` neben der Ausgabe von Claude Code. Zeilen dieses Typs aus der Sandbox verwirft er.

| Ereignis | Bedeutung |
|---|---|
| `gestartet`, `ende` | Lauf beginnt, Lauf endet (mit Dauer) |
| `selbsttest_ok`, `selbsttest_fehlgeschlagen` | Selbsttest der Sandbox vor dem Start (Exit 3 bei Fehlschlag) |
| `kanal_gesperrt` | Ein Verstoß gegen die Regeln des Kern-Kanals, Feld `grund` aus `KANAL_GRUENDE`, Exit 2 |
| `belegt` | Ein Start an einer Platzgrenze, Feld `grenze` aus `BELEGT_GRENZEN` (`auftrag`, `projekt`, `gesamt`, `profil`) und `max`, Exit 4 |
| `keine_zugangsdaten` | Es fehlt der Claude-Zugang oder bei `haus` der Ordner `/run/wamo-haus`, Exit 5 |
| `zugang_ungueltig`, `zugang_erweitert` | Zugang unbrauchbar, oder der Lauf bekäme einen Zugang, den frühere Läufe im Projekt nicht hatten (nur nach Freigabe), Exit 7 |
| `start_abgelehnt` | GitHub-Teil des Starts gescheitert, Exit 8, Feld `grund` aus `GITHUB_GRUENDE` |
| `gh_widerruf_fehlgeschlagen` | Das kurzlebige Installations-Token ließ sich nicht widerrufen |
| `github`, `aenderung`, `eingereicht`, `einreichen_fehler`, `verworfen` | Persönlicher GitHub-Weg. `aenderung` trägt `gruende` aus `AENDERUNG_GRUENDE`, `einreichen_fehler` einen Grund aus `EINREICHEN_GRUENDE` oder `KANAL_GRUENDE` |
| `kontingent` | Limits des Max-Abos aus den `rate_limit_event` von Claude Code (nur Felder einer Allowlist) |

| Exit | Bedeutung |
|---|---|
| 0 | in Ordnung |
| 2 | abgewiesen oder nicht möglich |
| 3 | Selbsttest fehlgeschlagen |
| 4 | belegt |
| 5 | keine Zugangsdaten |
| 6 | interner Fehler |
| 7 | Zugang erweitert, Freigabe nötig |
| 8 | GitHub-Teil gescheitert |
| 124 | Zeitlimit |
| 130 | abgebrochen |

Bei `pruefen` bedeutet Exit 0, dass der Befehl lief (auch wenn er scheiterte). Die Antwort ist eine JSON-Zeile mit `ok`, `exit`, `abgebrochen`, `grund`, `dauer_s`, `ausgabe`, `gekuerzt`.

### 5.3 Gründe der Abweisung im Kern-Kanal

Die feste Liste `KANAL_GRUENDE` bildet die Schnittstelle zum Kern. `voice-core/entwicklung_betrieb.py` hält `GRUND_SAETZE` mit denselben Schlüsseln, `voice-core/test_kernkanal_vertrag.py` prüft beide Seiten gegeneinander. Die Reihenfolge der Prüfungen steht im Modulkopf von `wamo_job_kernkanal.py`.

| Code | Bedeutung |
|---|---|
| `notaus` | Notaus-Datei vorhanden |
| `konfig_ungueltig`, `kanal_zu`, `abgelaufen` | Regeldatei fehlerhaft, Kanal geschlossen, Freigabe des Kanals abgelaufen |
| `befehl` | Befehl nicht in der Liste des Kanals |
| `fremd` | Auftrag gehört nicht zum Kern-Kanal (`auftrag.json` ohne `kanal=kern`) |
| `art`, `repo`, `repo_fehlt`, `dienst` | Auftragsart, Repo oder Dienst nicht erlaubt, oder das Repo fehlt |
| `projekt` | Projektname passt nicht zu `kern-<Kennung>-<Name>`, oder der Ordner gehört einem anderen Profil |
| `zugang` | Zugang nicht `folgt` oder `haus`, oder der Wert kam nicht wie vorgesehen an |
| `fork` | Repo ist Kopie oder Vorlage und gesperrt (Fork-Prüfung beim ersten Zugriff) |
| `herkunft_unklar` | Schlüssel lässt sich keinem Kanal zuordnen (strikter Modus) |
| `grenze_start`, `grenze_laufzeit`, `grenze_folgen`, `abstand`, `platz`, `grenze_profil` | Obergrenzen je Stunde und Tag, Fortsetzungen, Mindestabstand, freier Platz, Grenzen je Profil |
| `persoenlich_aus`, `grenze_einreichen` | Persönlicher GitHub-Weg nicht eingeschaltet, Tagesgrenze fürs Einreichen erreicht |

Für den GitHub-Teil gelten drei weitere feste Listen. `GITHUB_GRUENDE`: `github_zeile`, `token_ungueltig`, `token_abgelaufen`, `token_rechte`, `repo_nicht_erreichbar`, `eigenes_repo`, `repo_zu_gross`, `klon_fehler`, `bereinigung`, `projekt_gewechselt`, `github_wechsel`. `AENDERUNG_GRUENDE`: `pfad_gesperrt`, `geheimnis`, `zu_gross`, `zu_viele_commits`, `symlink`, `sonderdatei`, `basis_fehlt`, `bundle_ungueltig`, `pruefung_fehler`, `schon_eingereicht`. `EINREICHEN_GRUENDE`: `zustand`, `veraltet`, `bestaetigung`, `konto`, `token_rechte`, `repo_geaendert`, `keine_schreibrechte`, `zweig_belegt`, `geheimnis`, `token_abgelaufen`, `github_fehler`. Die Sätze dazu halten `GITHUB_SAETZE`, `AENDERUNG_SAETZE` und `EINREICHEN_SAETZE` in `voice-core/entwicklung_betrieb.py`.

Dauerhaft sind `notaus`, `konfig_ungueltig`, `kanal_zu`, `abgelaufen`, `herkunft_unklar` und `persoenlich_aus` (`GRUENDE_DAUERHAFT`): Nach so einer Abweisung stellt der Kern 120 Sekunden lang keine neue Karte.

## 6. Fehlercodes

Fehler der Zugangskontrolle kommen als `{"error": "nicht berechtigt", "detail": <Satz>, "code": <Code>}` (der Code ist optional). Fehler der Routen kommen als `{"detail": <Satz>}`, bei einigen Routen mit `code`.

### 6.1 Zugang und Labor

| Status | Code | Bedeutung |
|---|---|---|
| 401 | ohne | Token fehlt, ungültig, abgelaufen, ohne Konto, ohne `amr` oder Signaturverfahren nicht erlaubt |
| 401 | `anmeldung_zu_alt` | Anmeldung älter als `WAMO_ANMELDUNG_MAX_STUNDEN`, die Oberfläche meldet ab |
| 403 | ohne | zweiter Faktor fehlt, kein Profil, Profil deaktiviert |
| 403 | `passwort_wechsel_noetig` | Erstanmeldung offen, Startpasswort muss zuerst geändert werden |
| 403 | `startpasswort_abgelaufen` | Startpasswort nicht rechtzeitig gewechselt, Admin ansprechen |
| 403 | `labor_pfad_gesperrt` | Weg für Laborprofile gesperrt |
| 403 | `labor_profil_unstimmig` | Laborprofil nicht stimmig eingerichtet |
| 403 | `labor_durchlauf_beendet` | Durchlauf vom Betreuer beendet |
| 403 | `labor_keine_einwilligung` | Für den Platz liegt keine gültige Einwilligung vor |
| 429 | `labor_zu_viele_anfragen` | Zu viele `/start` und Angebote je Profil |
| 503 | ohne | Anmeldedienst, Datenbank oder Profilprüfung nicht erreichbar, Erstanmeldung nicht prüfbar |
| 503 | `labor_dienst_nicht_erreichbar` | Labor-Dienst nicht erreichbar (bleibt die Prüfung aus, endet die Sitzung nach einer Frist) |

### 6.2 Fehlercodes einzelner Routen

| Route | Status und Code | Bedeutung |
|---|---|---|
| Erstanmeldung | 429 `zu_oft`, 413 `zu_gross`, 400 `passwort_ungueltig`, 409 `kein_wechsel_noetig`, 403 `startpasswort_abgelaufen` | Grenzen, Form des Passworts, falscher Stand |
| Erstanmeldung (aus GoTrue abgebildet) | 422 `same_password`, 422 `weak_password`, 401 `insufficient_aal`, 401 `reauthentication_needed`, 401 `sitzung_ungueltig`, 502 `anmeldedienst` | Passwort gleich dem alten oder zu schwach, zweiter Faktor oder neue Anmeldung nötig, Anmeldedienst gestört. Vom Text der GoTrue-Antwort liest der Kern nur Status und `error_code` |
| Erstanmeldung (Ablehnung der Zugangskontrolle) | `nicht_angemeldet` (401), `nicht_berechtigt` (403), `nicht_pruefbar` (503) | Ersatzcodes, wenn die Zugangskontrolle selbst keinen Code trägt |
| Installer | 403 `installer_labor`, 429 `installer_zu_oft`, 503 `installer_fehlt` | Laborprofil, Ratengrenze, Ablage unvollständig oder Prüfsumme passt nicht |
| Geräteverwaltung, Fernzugriff | 403 `zweiter_faktor_zu_alt` | Code des zweiten Faktors älter als 120 Sekunden (beim Fernzugriff nach `WAMO_RD_ANMELDUNG_MAX_MIN`) |
| Fernzugriff | 409 | Ziel belegt, nicht erreichbar oder Start durch neueren Start abgelöst |
| Allgemein | 400, 413 | Body kein JSON-Objekt oder zu groß |
| Allgemein | 429, 503 | Rate-Grenze der Route, Datenbank oder Dienst nicht eingerichtet oder nicht erreichbar |

### 6.3 Fehlercodes des Freigabe-Dienstes

Quelle: `infra/sokrates2/anker/freigabe.py`, Tabelle `FEHLER`.

| Status | Code | Bedeutung |
|---|---|---|
| 400 | `angaben` | Angaben unvollständig oder falsche Form |
| 401 | `token_ungueltig` | Anmeldung ungültig |
| 403 | `aal2_fehlt`, `aal2_alt`, `aal2_zukunft` | Zweiter Faktor fehlt, ist zu alt oder liegt in der Zukunft |
| 403 | `keine_berechtigung`, `zweiter_admin` | Keine Berechtigung, für die Sonderfreigabe fehlt ein zweiter Admin |
| 404 | `anfrage_unbekannt` | Anfrage gibt es nicht |
| 409 | `falscher_status`, `fassung_passt_nicht`, `wartezeit`, `schon_freigegeben`, `regel` | Anfrage wartet nicht auf Freigabe, Anfrage hat sich geändert, Wartezeit der Sonderfreigabe läuft, schon freigegeben, Regel der Datenbank lehnt ab |
| 429 | `zu_viele` | Zu viele Versuche |
| 503 | `datenbank` | Datenbank nicht erreichbar |

## Weiterführend

- Architektur im Überblick: [`../architektur/arc42.md`](../architektur/arc42.md), Diagramme: [`../architektur/c4-diagramme.md`](../architektur/c4-diagramme.md)
- Rollen und Rechte hinter den Zugriffsspalten: [`../fachlich/rollen-und-rechte.md`](../fachlich/rollen-und-rechte.md)
- Aufbau des Kerns und des Hosts: [`voice-core.md`](voice-core.md), [`host-und-desktop.md`](host-und-desktop.md)
- Umgebungsvariablen und Schalter: [`konfiguration.md`](konfiguration.md)
- Vertrag mit dem Labor-Dienst: [`../../labor-dienst-vertrag.md`](../../labor-dienst-vertrag.md)
- Konzept des Kern-Kanals: [`../../entwicklung-im-betrieb.md`](../../entwicklung-im-betrieb.md), Betrieb: `infra/sokrates2/README.md`, Abschnitt 18
