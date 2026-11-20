# Admin-Panel "Werkstatt": Bauplan und Schnittstellen-Inventur

Stand: 20.11.2026. Status: Entscheidungen von Niko am 20.11.2026 getroffen (Abschnitt 1), gebaut wird nach dem Labortag. Das Konzept mit Varianten und Entscheidungen steht in `docs/adminpanel-werkstatt.md`. Dieses Dokument plant den Bau (ECC-Planung) und hält die Inventur der vorhandenen Schnittstellen fest (REA, aus der laufenden Oberfläche Version 0.7.0 und dem Quelltext).

## 1. Entscheidungen von Niko (20.11.2026)

Niko hat die fünf Punkte des Konzepts am 20.11.2026 entschieden. A3 ist gegenüber der Empfehlung erweitert, A4 verkürzt.

| Nr. | Entscheidung |
| --- | --- |
| A1 | Variante B: eigener Dienst `wamo-werkstatt` mit Datenbankrolle `wamo_werkstatt`, Port 55448 hinter `wamo-caddy` |
| A2 | Zugang nur für Admins mit aktivem Profil, ohne `labor_art`, mit zweitem Faktor (aal2) und Erlaubnisliste; der Port ist nur aus den Admin-Quellen erreichbar (`infra/sokrates2/README.md`, Abschnitt 6.1) |
| A3 | Alles darf das Panel schreiben, stufenweise. Stufe 1: Laborkonfiguration und Laborerstellung (Termine, Plätze, Fristen, Checkliste, Laborprofile anlegen). Stufe 2: freischalten, sperren, zählen, Löschwunsch je Zeitfenster. Stufe 3: weitere Aktionen (zum Beispiel Mitglieder, Releases, Installer, Aufträge), je Stufe mit eigener Sicherheitsprüfung. Geheimnisse (Startpasswörter, zweite Faktoren mit QR und Seeds, Dienstschlüssel) erscheinen nie im Browser: Ein kleiner Helfer am Server erzeugt sie und übergibt sie nur an die Betreuer |
| A4 | Kennzahlen werden verdichtet und ohne `user_id` gespeichert, Frist 30 Tage |
| A5 | Phase 1 läuft parallel zu Plan C, Phase 2 ist vor dem nächsten Labortag fertig |

Folge von A3: Die Pakete W7 bis W9 beginnen mit Laborkonfiguration und Laborerstellung. Dazu kommt ein Paket für den Helfer am Server, der Konten, Passwörter und Faktoren erzeugt (Aufwand wird in Phase 0 neu geschätzt, die Stundenangaben unten gelten für den Umfang vor dieser Entscheidung).

Weitere Annahmen: systemd-Dienst mit Unix-Socket und nft-Ausgang wie beim Freigabe-Dienst (`infra/sokrates2/freigabe-einrichten.sh`); 20 Stunden Arbeit je Woche, Pause vom 24.12. bis 01.01.

## 2. Arbeitspakete

Jedes Paket kann ein eigener PR sein.

| Nr. | Paket | Inhalt | Ergebnis (prüfbar) | Abhängigkeit | Stunden | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| W0 | Papier | Bauplan, Vertragsentwurf, statischer Klickdummy | Doku-PR, nichts ausgerollt | keine | 6 | 0 |
| W1 | Dienst-Gerüst | `werkstatt/` (FastAPI), Benutzer, Socket, `wamo-caddy/kern/wamo-werkstatt.caddy`, Port 55448 in `LAN_PORTS_ADMIN`; Skripte `wamo-werkstatt-einrichten.sh` (`--trocken`, Probelauf `WAMO_WERKSTATT_WURZEL`), `wamo-werkstatt-rueckweg.sh`, `wamo_werkstatt_rauchtest.py` | Rauchtest grün, Rückweg ohne Reste, Port aus fremder Quelle zu | W0 | 10 | 1 |
| W2 | Rolle, Lesemigration | `0031_werkstatt_lesen` mit `.down.sql` und SQL-Test: Gruppenrolle, Lesefunktionen `security definer` mit Admin-Prüfung wie `neue_mitglieder` (`0022`), `werkstatt_kennzahlen` mit RLS, Verdichtung per Timer; Login-Rolle über `scripts/wamo_dienst_db.py` | zweimal angewendet; kein `select` auf `turns`, `sessions`, `memories` | keine | 8 | 1 |
| W3 | Anmeldung | JWKS ES256, aal2, Profil, Erlaubnisliste `/etc/wamo-werkstatt/admins`, 30 Abrufe je Minute (Muster `voice-core/mitglieder_admin_api.py`) | Sicherheitsproben grün | W1, W2 | 6 | 1 |
| W4 | Lese-API | Sitzungen, Latenz (`turns.latency_ms`), Aktionen, Labor-Stand; Feldfilter je Zeile (`zeile_pruefen`) | Marker-Test grün | W3 | 6 | 1 |
| W5 | Protokolle | Journal nur mit Marken der Erlaubnisliste (`docs/produktdokumentation/betrieb.md`, Abschnitt 10) über einen root-Leser am Socket; `actions` ohne `params` und `result` | ein Test je Quelle | W3 | 5 | 1 |
| W6 | Oberfläche 1 | Anmeldung, Dashboards, Protokolle; WMC-Design, Tastaturbedienung, Kontrast AA | Komponententests | W4, W5 | 8 | 1 |
| W7 | Plan-Migration | `0032_labor_plan` mit `.down.sql` und Test (Abschnitt 4); Wrapper-Funktionen statt Rechten auf `labor_loeschen` und `labor_zaehlen` | Selbsttest von `0018` bleibt beim erneuten Lauf grün | W2 | 10 | 2 |
| W8 | Karten-Ablauf | Trockenlauf, Karte, frischer Faktor höchstens 60 Sekunden (`aal2_zeit` aus `infra/sokrates2/anker/freigabe.py`), Ausführung, Audit | Proben mit alter, fremder und doppelter Karte | W7 | 10 | 2 |
| W9 | Oberfläche 2 | Labor-Planer, Checkliste, Nachlauf als geführte Ansicht mit Verweis auf die Skripte | Komponententests | W8 | 10 | 2 |
| W10 | Fristen aus einer Quelle | Export des Plans; die Löschfrist im Löschlauf (`infra/sokrates2/wamo-labor-loeschlauf.sh`) und `WAMO_LABOR_DIENST_BIS` lesen ihn | Vertragstest | W7 | 6 | 2 |
| W11 | Vertragstest | Panel gegen `scripts/wamo_labor.py`: gleiche Funktionen, `KENNUNG_RE`, Fehlercodes | grün | W8 | 4 | 2 |
| W12 | Doku | Abschnitt in `infra/sokrates2/README.md`, Runbook Abschnitt 9, Namensvertrag in `CLAUDE.md` | Review | je Phase | 5 | 1 und 2 |
| W13 | Phase 3 | Releases, Installer, Selbstaufträge, Aufträge | eigener Plan | W12 | 40 | 3 |

Summen: Phase 1 rund 45 Stunden, Phase 2 rund 43 Stunden.

Zwei Befunde stecken in W7 und W10:

- **Migration 0018:** Der Selbsttest bricht ab, sobald eine andere Rolle als `wamo_admin` die Funktionen `labor_loeschen` oder `labor_zaehlen` ausführen darf (`supabase/migrations/0018_labor_profile.sql`, Teile 6 und 7). Deshalb laufen alle Schreibwege über Wrapper.
- **Fristen:** Der Labor-Dienst nahm als Ende der Aufbewahrung nur Werte zwischen 28.11. und 11.12.2026 an. Das ändert PR 241 (Labortag und Fristen aus einer Quelle). Die Annahme "Löschfrist zwischen Labortag und Labortag plus 14 Tage" bleibt mit den dort bestätigten Fristen vereinbar (Aufbewahrung bis 18.12., Löschlauf ab 19.12.).

## 3. Schnittstelle (Gerüst)

Alle Antworten sind `no-store` und enthalten nur Zahlen, Stände und Zeiten.

| Pfad | Felder |
| --- | --- |
| `GET /werkstatt/api/ich` | `rolle`, `aal2_alter_s`, `erlaubt` |
| `GET /werkstatt/api/sitzungen?tage=` | je Tag `anzahl`, `dauer_p50_s`, `dauer_p95_s`, `offen` |
| `GET /werkstatt/api/latenz?tage=` | `zuege`, `p50_ms`, `p95_ms` |
| `GET /werkstatt/api/aktionen?tage=` | je `tool` und `status` die `anzahl` |
| `GET /werkstatt/api/protokolle?marke=&stunden=` | `zeit`, `marke`, `stufe`, `code` |
| `GET /werkstatt/api/labor/stand` | je Kennung `art`, `platz`, `freigeschaltet`, `zeilen`; dazu `tag`, `frist_loeschen` |
| `POST /werkstatt/api/labor/karte` | `karte_id`, `wirkung`, `zahlen`, `gilt_bis` |
| `POST /werkstatt/api/labor/karte/{id}/ausfuehren` | `status`, `zahlen`, `nachweis` |

Ablauf beim Schreiben:

1. Trockenlauf: zählen, nichts ändern.
2. Karte: fünf Minuten gültig, einmalig, an den Admin gebunden.
3. Frischer Code des zweiten Faktors.
4. Der Wrapper führt aus und schreibt in derselben Transaktion eine Zeile in `actions` (Werkzeug `werkstatt_<aktion>`, Risiko `critical`).
5. Eine Zeile mit der Journal-Marke `wamo-werkstatt`.

Der Löschwunsch läuft geführt: sperren, die drei Minuten Sperrfrist abwarten (Migration `0018`), löschen, nachzählen, bei Bedarf wieder freischalten.

Fehlerbild: `{code, text}` ohne interne Namen.

- 401 `nicht_angemeldet`
- 403 `aal2_fehlt`, `aal2_alt`, `nicht_berechtigt`, `labor_profil`
- 409 `sperrfrist` (mit `warte_s`), `sitzung_laeuft`, `karte_verbraucht`
- 410 `karte_abgelaufen`
- 429 `zu_oft`
- 503 `nicht_verfuegbar`

## 4. Datenmodell (Migration 0032, grob)

- **`labor_termine`:** `tag` (eindeutig), `beginn`, `ende`, `status` (entwurf, freigegeben, laufend, nachlauf, abgeschlossen), `einwilligung_version`, `frist_loeschen` mit der Prüfung "zwischen `tag` und `tag` plus 14 Tage" (Annahme). `erstellt_von` als Fremdschlüssel mit `on delete set null` und partiellem Index.
- **`labor_termin_plaetze`:** Schlüssel ist Termin plus Platz 1 bis 16. `zweck` ist besucher, reserve oder abnahme, wobei abnahme nur die Plätze 15 und 16 bekommen (`docs/labor-dienst-vertrag.md`, Abschnitt 6). `kennung` nach `KENNUNG_RE`. Kein Gerätename.
- **`labor_checkliste`:** `nr`, `titel` (höchstens 120 Zeichen), `quelle` (Abschnitt im Runbook), `faellig`, `erledigt_at`, `erledigt_von`.
- **`werkstatt_karten`:** `admin`, `aktion`, `ziel` (nur Kennungen und Zeitfenster), `zahlen`, `gilt_bis` (höchstens fünf Minuten), `ausgefuehrt_at` (nur einmal setzbar, per Trigger), `action_id`.
- **Audit:** die bestehende Tabelle `actions` (`supabase/migrations/0001_wamo_init.sql`).

Für alle neuen Tabellen gilt: RLS, Policy nach dem `core_all`-Muster für `wamo_werkstatt`, kein `delete` außer dem Aufräumen nach Frist, keine Rechte für `anon`, `authenticated` und `service_role`.

## 5. Testplan

- **Unit** (pytest, mindestens 80 Prozent Abdeckung): Token, Alter des zweiten Faktors, Erlaubnisliste, Feldfilter, Drosselung, Zustände der Karte.
- **SQL:** je ein Test für `0031` und `0032`, Rechte-Selbsttest, danach `0018` erneut anwenden.
- **Vertrag:** W10 und W11.
- **Rauchtest am Server:** mit echtem GoTrue-Token nach dem Muster von `infra/sokrates2/freigabe_tokentest.py`.
- **Sicherheitsproben:**
  - Laborprofil, Mitglied und Admin außerhalb der Liste werden mit 403 abgewiesen, ebenso Tokens ohne aal2.
  - Ein Code älter als 60 Sekunden wird abgewiesen.
  - Eine fremde, abgelaufene oder doppelt genutzte Karte wird abgewiesen.
  - Der 31. Abruf in einer Minute ergibt 429.
  - Marker-Test: Ein Marker steht in `turns.content`, `sessions.summary`, `memories` und in einer E-Mail. Keine Antwort darf ihn enthalten.
- **Oberfläche:** vitest, Bedienung nur mit der Tastatur, Kontrast.

## 6. Zeitplan

Bis Mo 23.11. früh entsteht nur Papier: Die Entscheidungen A1 bis A5 sind getroffen, dazu dieser Plan, der Vertragsentwurf und ein Klickdummy ohne Server. Bis zum Labortag am Sa 05.12. ruht das Panel.

| Meilenstein | Datum | Inhalt |
| --- | --- | --- |
| M1 | Fr 11.12.2026 | Löschnachweis des Labors erbracht (hat Vorrang); W1 und W2 in `wamo_dev` |
| M2 | Fr 18.12.2026 | W3 bis W5 fertig, Sicherheitsproben grün |
| M3 | Fr 15.01.2027 | W6 und Doku; Phase 1 in Betrieb |
| M4 | Fr 12.02.2027 | Phase 2 in Betrieb. Gilt nur, wenn der nächste Labortag frühestens am 12.03.2027 liegt, sonst den Umfang kürzen |

## 7. Risiken, Abbruchkriterien, Definition of Done

Risiken mit Abbruchkriterium:

1. **Rechte:** Findet `database-reviewer` oder `security-reviewer` einen kritischen Befund an `wamo_werkstatt`, bleibt das Panel lesend. Das Schreiben bleibt dann Skript.
2. **Datenschutz:** Schon ein Treffer im Marker-Test schaltet die betroffene Quelle ab, bis der Fehler behoben ist.
3. **Vorrang:** Gefährdet das Panel den Löschnachweis bis 11.12. oder Plan C, oder braucht Phase 1 mehr als 60 Stunden, wird Phase 2 verschoben. In Phase 0 wird außerdem geprüft, ob die Anmeldung über GoTrue vom eigenen Port aus geht (CORS). Scheitert das, wird die Variante neu entschieden.

Definition of Done:

- **Phase 0:** Entscheidungen getroffen, Doku-PR liegt vor, Aufwand für A3 neu geschätzt, nichts ausgerollt.
- **Phase 1:** Rauchtest grün und Rückweg geprobt; Sicherheitsproben grün und Abdeckung mindestens 80 Prozent; Migration in `wamo_dev` und `wamo_test` je zweimal angewendet; Reviews ohne CRITICAL und ohne HIGH; Kennzahlen verschwinden nach 30 Tagen (Test); Doku und Namensvertrag nachgezogen.
- **Phase 2:** Alles aus Phase 1, dazu: Jede Schreibaktion hat Trockenlauf, Karte, frischen Faktor und eine Zeile in `actions`; Vertragstest grün; `scripts/wamo_labor.py` bleibt unverändert als Rückweg; Probe mit einem Wegwerf-Laborprofil in `wamo_dev` bis zum Nachweis 0; Fristen kommen aus einer Quelle.

## 8. Inventur der vorhandenen Schnittstellen (REA)

Methode: Die Startseite und 94 JavaScript-Teile (rund 7 MB) der laufenden Oberfläche (Version 0.7.0, Commit 703d696 laut `/version.json`) wurden ohne Anmeldung per GET geladen und mit dem Quelltext abgeglichen. "Basis B" heißt: Token mit aal2, aktives Profil, Laborprofile erhalten 403 (`wamo_api.identitaet`, `labor.py`).

### 8.1 Schnittstellen und Nachrichten

| Name (Quelle) | Methode | Rolle | Felder | personenbezogen | wiederverwendbar |
| --- | --- | --- | --- | --- | --- |
| `/wamo/api/admin/neue-mitglieder` (`mitglieder_admin_api.py:107`) | GET | B, Admin, 30 je Minute | user_id, anzeigename, rolle, aktiv, angelegt, letzte_anmeldung, faktor, passwort_stand, geraet_stand, modellzugang, stimmabdruck | ja (Name, Datum) | ja |
| `/geraete/verwaltung` und `/aktion` (`geraete_admin_api.py:227,244`) | GET, POST | B, Admin, bei Aktion aal2 höchstens 120 Sekunden | kennung, rechnername, profil, status, fingerabdruck, ereignisse | ja | ja, Muster für schreibende Aktionen |
| `/admin/github-rechte` (`github_zugang_api.py:103,120`) | GET, POST | B, Admin | personen, erlaubbar, nie | ja | ja |
| `/release/status` (`release_api.py:47`) | GET | B, Admin, 60 je Minute | Stand Release-Dienst, von_mir, pruefstand | nein | ja |
| `/gedaechtnis/vorschlaege` und `/entscheiden` (`gedaechtnis_api.py:110,129`) | GET, POST | B, Admin | id, art, text, autor | ja (Freitext) | ja, mit Erlaubnisliste |
| `/installer` (`verteilung_api.py:295`) | GET | B, 30 je Minute | version, sha256, bauzeit, commit, signatur | nein | ja |
| `/buero/status` (`buero_api.py:445`) | GET | B | id, ampel, text, kennzahlen | nein | ja |
| `/rd/ziele`, `/start`, `/ende` (`rd_api.py`) | GET, POST | B, Admin | Ziele, Zustand | nein | nur Zustand |
| `/einrichtung/stand`, `/modellzugang`, `/github-zugang`, `/vorgaenge`, `/hinweise`, `/teilen`, `/dateien`, `/canvas/historie`, `/erstanmeldung`, `/geraet/*` | GET, POST | B, nur eigenes Profil | eigene Daten | ja | nein, Eigenbereich |
| Labor-Dienst `/gesundheit` (`app.py:28`) | GET | ohne Token | zustand ok oder gestoert | nein | ja |
| Labor-Dienst `/api/betreuer/plaetze` (`betreuer_api.py:165`) | GET | Betreuer-Bearer | platz, durchlauf_id, offen, einwilligung_version, einwilligung_zeit, tickets, kommentare | pseudonym | ja, lesend |
| Labor-Dienst `/api/betreuer/plaetze/n/...` (durchlauf-beenden, neuer-durchlauf, zuruecksetzen, daten-loeschen, platz-token) und `/api/kern/*` | POST | Betreuer- oder Kern-Bearer | Vertrag V1 bis V7 | nein | nein, Betreuer-Seite (D9) |
| RTVI-Nachrichten `betrieb`, `kontingent`, `profil`, `stimme` (`bot.py:20-130`) | Sitzung | Sitzung | modus, ort, modelle, pc; zustand, limits | nein | nein, nur in laufender Sitzung |

### 8.2 Datenbankfunktionen und Sichten

| Name | Datei | Rechte | Nutzen für `wamo_werkstatt` |
| --- | --- | --- | --- |
| `labor_zaehlen(uuid)`, `labor_loeschen(uuid, ab, bis)` | `0018:123,157` | execute nur `wamo_admin`, nie `wamo_core` | ja, einziger direkter Treffer; Sperrfrist 3 Minuten |
| `neue_mitglieder`, `geraete_verwaltung_liste`, `geraet_entscheiden`, `gedaechtnis_vorschlag_entscheiden` | 0022, 0014, 0020 | execute nur `wamo_core` | nur mit neuer Migration, sonst über Kern-Routen |
| `actions` (Audit) | `0001:192` | `wamo_admin` ohne select (Grants `0001:351-355`) | Lesesicht nötig; `params` und `result` geschwärzt, aber Freitext |
| `sessions`, `turns`, `vorgaenge` | 0001, 0017 | kein Grant für `wamo_admin` | nur aggregiert; `turns.content` ist Gesprächsinhalt |
| `selbstauftraege` | `0030:56` | select `wamo_core`; Wechsel nur per Funktion | Skript liest schon |
| `auftrag_entwuerfe` | 0026 | select, delete `wamo_core` | nein |
| Einwilligung (`speakers.consent_*`, Labor `einwilligung_zeit`) | `0001:116` | `wamo_core` | Labor nur im Dienst |
| `devices`, `device_events`, `hinweise`, `teilungen`, `model_access` (Metadaten), `github_zugang` (ohne Token) | 0002, 0003, 0010, 0027 | select `wamo_admin` | ja |

### 8.3 Protokoll- und Kennzahlquellen

| Quelle | Ort, Format | Felder | Gesprächsinhalt |
| --- | --- | --- | --- |
| Kern-Journal | `journalctl -u wamo-core@a` oder `@b`, Text | `Verbrauch profil=<8 hex> anbieter modell baustein ein aus cache`; `LATENZ_JSON` (nur mit `WAMO_LATENZ_LOG=1`); Stimm- und Mikrofonzeilen | laut Kopf nein (`latenz.py`, `llm_anbieter.py:298`), Erlaubnisliste trotzdem nötig |
| Dispatcher | `/srv/wamo/logs/kernkanal.jsonl`, `auftraege.log` | Ereignisse start, ende, versuch, kanal_gesperrt, profil | nein |
| Bedienspur | `/var/log/wamo-job-kern/aktionen.jsonl` | Aktion ohne Werte | nein |
| Labor-Dienst | `dienst.jsonl`, `betreuer.jsonl` | Metadaten, nie Texte | nein |
| Haus-Proxy | `/var/lib/wamo-haus-proxy/verbrauch.jsonl` | Tokens je Lauf | Felder nicht geprüft |
| Anker, Release | `audit.jsonl` (Hashkette, root) | Aktionen | Lesezugriff nicht belegt |
| Slots, Lasttest | `wamo-core-slots.sh status` (Text, root); `wamo_labor_last_auswertung.py` (Kennzahlen je Stufe) | Slot, Zustand; p95, Kriterien | nein |

### 8.4 Lücken

- **Dashboards:** keine Aggregat-Route für Sitzungen, Latenz (p50 und p95) oder Verbrauch je Profil und Tag; kein Lesezugriff auf `actions`; eine Gesundheitsroute des Kerns ist nicht belegt; das Kontingent gibt es nur je eigener Sitzung.
- **Protokolle:** drei Formate (Journal, JSONL, Text), keine Leseroute, Journal und Hashketten brauchen root oder Gruppe, eine Erlaubnisliste fehlt.
- **Labor-Planer:** keine Termin- oder Plandaten; `labor_aktiv` und Anlegen nur per Skript; Einwilligungen nur im Labor-Dienst; der Betreuer-Token wirkt wie ein Generalschlüssel.
- **Werkstatt:** nur als Skript vorhanden sind `wamo_labor.py`, `wamo_nutzer.py`, `wamo_admin.py`, `wamo_selbstauftraege.py`, `wamo_installer_sokrates2.py`, `wamo-core-slots.sh`, `wamo-job-kern-einrichten.sh` und `wais-deploy`.

### 8.5 Auffälliges

Die Oberfläche ruft `/wamo/release/<id>/freigeben` am Freigabe-Dienst vorbei an `/wamo/api` auf; das ist die dokumentierte Route auf Port 55444 in `wamo-caddy/kern/wamo-core.caddy` (Tabelle in `CLAUDE.md`, Zeile Freigabe-Dienst) und steht in keinem Router des Kerns. `/scans`, `/buerogeraete` und `/hinweise/gelesen` gibt es im Kern, das ausgelieferte Paket ruft sie nicht auf; `/admin/...` besteht nur aus `neue-mitglieder` und `github-rechte`.

Nicht belegt: die Gesundheitsroute des Kerns, der Quelltext des Freigabe-Dienstes, die Felder der Buchung des Haus-Proxys und die Ablage der Lasttest-Berichte.
