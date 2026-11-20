# Testlabor 05.12.2026: Restplan ab Montag, 16.11.2026

## Nachtrag 20.11.2026: Labortag verschoben auf Sa 05.12.2026

**Stand:** 20.11.2026. Der Labortag ist vom Sa 28.11.2026 auf Sa 05.12.2026 verschoben. Der Freeze bleibt Mo 23.11.2026 früh, der Freeze-Kandidat wird So 22.11. abends ausgerollt. Alle Termine, die am Labortag hängen, rücken um 7 Tage (gleiche Wochentage). Was heute (Fr 20.11.), am Sa 21.11. und am So 22.11. geplant ist, bleibt unverändert. Die Fahrpläne weiter unten (Nachtrag 17.11. und Abschnitt 4) tragen die neuen Termine. Die Tabellen und Beschlüsse mit Datum vom 16. und 17.11. bleiben als Protokoll stehen.

| Termin | bisher | jetzt |
| --- | --- | --- |
| Kartensatz drucken | Di 24.11. | Di 01.12. |
| Betreuer-Token übergeben, Namen und Telefonnummern eintragen | Mi 25.11. | Mi 02.12. |
| Generalprobe | Do 26.11. | Do 03.12. |
| Daten-Freeze 12:00, Rückwegübung, Einweisung der Betreuer | Fr 27.11. | Fr 04.12. |
| Gateway ohne Neustart (N10) | Fr 27.11. 12:00 bis Sa 28.11. abends | Fr 04.12. 12:00 bis Sa 05.12. abends |
| Labortag | Sa 28.11. | Sa 05.12. |
| Nachlauf, Kern-Kanal wieder öffnen | ab Mo 30.11. | ab Mo 07.12. |
| Laborkonten löschen, Sitzungen widerrufen | Mo 30.11. bis Fr 04.12. | Mo 07.12. bis Fr 11.12. |
| Aufbewahrung und Löschlauf des Dienstes | bis Fr 11.12., Löschlauf ab Sa 12.12. | bis Fr 18.12., Löschlauf ab Sa 19.12. (entschieden am 20.11.2026) |

**Löschfrist.** Von Niko am 20.11.2026 bestätigt: Aufbewahrung bis Fr 18.12.2026 und Löschlauf des Dienstes ab Sa 19.12.2026 (Labortag plus 13 und plus 14 Tage, der gleiche Abstand wie bisher mit Fr 11.12. und Sa 12.12.). Die Laborkonten werden direkt nach dem Labortag gelöscht (Nachlauf ab Mo 07.12., Konten löschen bis Fr 11.12.), der 18.12. und der 19.12. sind die Absicherung. Besuchertext: „Ihre Daten werden unmittelbar nach der Veranstaltung gelöscht, spätestens bis zum 18.12.2026.“ Code, Skripte und Einstellungen leiten die Daten aus der einen Konstante `LABORTAG` in `labor-dienst/wamo_labor_dienst/frist.py` ab (Löschlauf und Rauchtest lesen die erzeugte Datei `infra/sokrates2/wamo-labor/frist.env`). Am Server wirkt das mit dem nächsten Ausrollen und dem Neubau des Images.

**Weiterhin offen:** Kiosk-Test des Platz-Skripts auf einem echten Platz-Laptop und einem Ersatzgerät, vor dem Freeze `[offen: Niko]`.

## Nachtrag 17.11.2026: Live-Stand, Risiken und Fahrplan bis zur Löschfrist

**Stand:** 17.11.2026. Dieser Nachtrag steht über dem Plan vom 16.11. und ersetzt dessen Fahrplan (Abschnitt 4) ab Di 17.11. Die Abschnitte 1 bis 6 vom 16.11. bleiben als Grundlage stehen. Was offen ist, steht mit `[offen: ...]` im Text.

### N.1 Live-Stand am 17.11.2026

| Baustein | Stand | Beleg |
| --- | --- | --- |
| Kern | Version 0.5.0. Slot a `v0.5.0-ddada3f` aktiv, Slot b `v0.5.0-d12ba6f` inaktiv (Rückweg-Ziel, mit Erstanmeldung) | `wamo-core-slots.sh status` am Server |
| Oberfläche | 0.5.0 (Commit `d12ba6f`) | `version.json` am Server |
| Labor-Dienst | Labor-Rauchtest ohne Fehler | `wamo_labor_rauchtest.py` |
| Installer | 0.5.0 von Niko signiert (SHA-256 `40a372e8…92d1`), am Server eingesetzt (aktuell 0.5.0, vorher 0.4.1), die Oberfläche bietet ihn an; GitHub-Release v0.5.0 mit Installer | `wamo_installer_sokrates2.py status`, Release v0.5.0 |

Seit dem Restplan vom 16.11. am Nachmittag sind live:

- #175: Stimmwächter strenger
- #176: Marker-Regel, und `think` auf false für Hausmodelle
- #177: Sprache im Haus umschaltbar (Migration 0023)
- #178: Sprachausgabe mit Streaming. Eigene Instanz `wamo-qwen3-tts` auf Sokrates-1, Durchreiche im Gateway
- #179: alle Modelle je Person umschaltbar (Migration 0024, Stimmen `sohee`, `uncle_fu` und `ono_anna`)
- #181: geordnetes Abschalten des Kerns (`voice-core/abschaltung.py`). `ausleiten` meldet bei einem Timeout und ruft danach `reset-failed` auf
- #182: Lasttest fragt den aktiven Slot am Server ab, kein fester Slot b mehr
- Dazu entfernt: die Umgebungsvariable `WAMO_LLM_VISION_MODELL`

### N.1a Prüfungen und Messungen am 17.11.2026

| Baustein | Stand | Beleg |
| --- | --- | --- |
| Token-Test (`infra/sokrates2/labor_tokentest.py`, über Caddy mit `--basis https://192.168.178.136:55443`) | 11 erwartet, 6 dokumentiert, 0 offen, 3 nicht gemessen. Von den 3 sind 2 bewusst nicht gemessen (Schreibprobe, Realtime-Auslieferung), 1 nicht gemessen, weil `/rest/v1/` über Caddy 403 statt des Verzeichnisses liefert. Das ist strenger als erwartet und unkritisch. Passwortwechsel mit dem Besucher-Token: 403. Wegwerf-Konto gelöscht | Lauf 17.11. |
| Restrisiko aus dem Token-Test | Ein Besucher kann mit aal2 den eigenen bestätigten Faktor löschen. Abhilfe im Betrieb: Reserveprofil (Runbook 6.7), Entwicklerwerkzeuge im Kiosk gesperrt | R13 |
| Lasttest, Trockenlauf | 8 Sitzungen sauber: 12 Sprechproben, 8 Seeds, geschätzt 0,34 USD. `WAMO_LATENZ_LOG` am Kern gesetzt | Trockenlauf 17.11. |
| REA | Installer 0.5.0 gegen 0.4.1 ohne Befund. Nur die Versionsnummer hat sich geändert, die Fuses sind unverändert und korrekt, die Update-Signatur prüft. Offen bleibt nur die bekannte fehlende Codesignatur | REA 17.11. |
| Soniox-Grenzen | Sprachausgabe 15, Erkennung 20 gleichzeitige Streams, in Region USA und EU genehmigt | R11 |
| Hausmodell `gemma4-31b` | a1 in 3 von 3 Läufen, Kern `v0.5.0-7fc7a84` | R9 |

### N.2 Entscheidungen von Niko, Ergänzung

- Am Labortag nur vier Besucher-Plätze (1 bis 4). Die Besucher wechseln sich ab. Die Profile `labor-05` bis `labor-08` bleiben eingerichtet und dienen als Reserve, Platz 9 bleibt Reserve-Laptop (17.11.).
- Der Lasttest prüft weiter bis 8 Sitzungen, aber nur als Reserve. Realistisch sind 4 Sitzungen gleichzeitig (17.11.).
- Keine Aufzeichnung fürs Schaufenster mehr (hebt die Aufzeichnung aus E9 auf). Der Rückfall ist die Vorführung am Betreuer-Platz oder die Texteingabe (Runbook 7, 17.11.).
- Vorstufe des Lasttests auf Wunsch von Niko schon am 17.11. gelaufen (Lauf last-20261117-114851, Stufen 2 und 4 Sitzungen je 10 Minuten): 0 Abbrüche, 0 Ablehnungen 429, 0 Soniox-Fehler, erster Ton p50 1,2 s und p95 bei 4 Sitzungen 2,5 s (Grenze 3,5 s), Speicher des Kerns 0,57 GiB. Das Werkzeug urteilte „durchgefallen“ nur wegen der Gesamt-CPU (108 Prozent eines Kerns bei 4 Sitzungen). Ein Messlauf mit 4 Sitzungen und CPU je Thread (last-20261117-121511) zeigt: Hauptthread 29 bis 34 Prozent, der Rest verteilt sich auf viele Hilfs-Threads unter je 4 Prozent. Kriterium deshalb auf den Hauptthread präzisiert (`docs/labor-lasttest.md`), hochgerechnet etwa 60 bis 68 Prozent bei 8 Sitzungen. Ausreißer bis 7,5 s erster Ton nur bei A1 und J1 (Werkzeugaufruf, nicht Last). Messlücke: Tokens je Minute zeigt nur 160. Zwei Fehlstarts behoben (Playwright am Mess-PC, #190). Der volle Lasttest bleibt Fr 20.11.
- Freeze Mo 23.11. früh (E1 bleibt).
- Die zweiten Faktoren der Laborprofile werden am Fr 20.11. nach dem Lasttest neu eingerichtet, nicht am 25.11. (E2 präzisiert).
- Der Lasttest läuft voll am Fr 20.11., nicht am 24.11.
- Mitglieder bis Sa 21.11. (E4).
- Jede neue Version bekommt einen Installer, den die Oberfläche anbietet.
- Niko betreut das zentrale LiteLLM-Gateway auf Sokrates-1 selbst. Der frühere Betreuer ist nicht mehr im Betrieb. Die Betriebsnotiz dazu ist `infra/sokrates1/gateway-wamo.md`.

### N.3 Risiken aus der Planung vom 16.11. abends

| Nr | Risiko | Stand |
| --- | --- | --- |
| R1 | Der Stimmwächter kann kurze eigene Sätze neuer Mitglieder verwerfen. Regler `WAMO_STIMME_VERWERFEN_MIN_SECS` | offen |
| R2 | Die Marker-Regel gilt auch im Labor, a1 steht bei 5 von 10 Läufen. Messrunde mit 20 weiteren Läufen | gemessen 17.11. auf Kern v0.5.0-ddada3f (20 Läufe, 420 Züge, 0,15 USD): a1 13 von 20, alle 7 Befunde sind Inhalt (eine Story mit nur einem Kriterium), kein Schweigen; w2 19, m1 19, j1 19, m2 19, s1 16 von 20 (4-mal unerwartet `canvas_zeigen`), w1, s2, i1, i2 je 20 von 20; erstes Token p50 0,51 s, p95 0,57 s. Die Karten mit erwartetem Fehler a3 und `m3_antwort` bleiben wie unter 0.4.1 bei 0 von 20 |
| R3 | `think` auf false gilt für alle LiteLLM-Anfragen, nicht nur für Hausmodelle | offen |
| R4 | Migrationen 0023 und 0024 in `wamo_dev` und `wamo_test` | geprüft: je zweimal angewendet, Test OK |
| R5 | Die TTS-Instanz hat keine Speichergrenze, sie hat nur ein Lock | teilweise behoben am 17.11.: Speichergrenze 4 GiB für den Container (`docker update`, im Startbefehl der README nachgezogen); belegt sind 0,5 GiB Hauptspeicher. Der GPU-Speicher (5,2 GiB) zählt nicht in diese Grenze und bleibt ohne Grenze |
| R6 | Gateway-Änderungen sind nur in unserem Repo dokumentiert | teilweise: Betriebsnotiz `infra/sokrates1/gateway-wamo.md` angelegt, Pflege beim Betreiber |
| R7 | Geordnetes Abschalten des Kerns: Fristen, Timeout bei `ausleiten` | behoben mit #181 |
| R8 | Lasttest nahm einen festen Slot b an | behoben mit #182 |
| R9 | Ausweichweg Hausmodell `gemma4-31b` (3 Läufe am 17.11.): a1 bricht in 3 von 3 Läufen ab. Der erste Satz kommt nach 0,7 s, der Aufruf von `canvas_zeigen` mit den Stories kommt als Block und überschreitet die Lesefrist des Gesprächs von 20 s (`GESPRAECH_LESE_TIMEOUT_SECS`). Gilt auch im Büro für Nutzer mit Hausmodellen. Vorschlag: längere Lesefrist nur für Hausmodelle, Entscheidung durch Niko vor dem Freeze-Kandidaten | behoben mit #184 (Lesefrist 60 s für Hausmodelle, Claude bleibt bei 20 s), a1 mit `gemma4-31b` danach 3 von 3, ausgerollt 17.11. als Kern v0.5.0-7fc7a84 (Bewährung bestanden, Labor-Rauchtest 20 OK) |
| R10 | Büro-Fall I04 („Puh, das ist schwierig.“ soll warten): am 17.11. 4 von 17 Läufen bestanden (vor #176 4 von 5, danach 3 von 5). W.A.I.S. antwortet sofort mit einer freundlichen Rückfrage statt zu warten. Betrifft nur das Büro, das Labor hat diesen Fall nicht. Vorschlag: ein Beispiel in der Marker-Regel ergänzen und mit der Messrunde gegenprüfen, Entscheidung durch Niko | verschoben auf nach dem Labortag (Entscheidung 17.11.: die Marker-Regel vor dem Freeze nicht mehr ändern, Schweigen wiegt schwerer als eine zu schnelle Antwort im Büro) |
| R11 | Soniox-Grenzen der Organisation: Sprachausgabe 3 gleichzeitige Streams (über alle Verbindungen, darüber Ablehnung 429), Spracherkennung 10. Für 8 Plätze, Schau-Profil und Büro zu wenig | behoben: Erhöhung auf 15 und 20 am 17.11. in Region USA und EU genehmigt, Prüfung im vollen Lasttest Fr 20.11. |
| R12 | Betreuer-Geräte flatterten: mDNS lieferte abwechselnd tote Adressen, jede abweichende Antwort entzog die zugelassene sofort (492 Paare in 24 h, je ein Caddy-Reload, `/betreuer` je eine Minute gesperrt) | behoben mit #186 (ersetzte Adresse bleibt 15 Minuten, Adresse nur aus mDNS erst nach ARP-Nachweis per UDP-Probe), eingespielt 17.11., danach kein Flattern mehr |
| R13 | Besucher löscht mit aal2 den eigenen bestätigten zweiten Faktor (Token-Test am 17.11.). Ein Besucher kann so sein Profil unbrauchbar machen | Restrisiko. Abhilfe im Betrieb: Reserveprofile `labor-05` bis `labor-08` (Runbook 6.7), Entwicklerwerkzeuge im Kiosk gesperrt. Zuordnung Reserveprofil zu Laptop `[offen: Generalprobe]` |

### N.4 Fahrplan Di 17.11. bis zur Löschfrist (Termine ab Di 24.11. mit dem Labortag um 7 Tage verschoben, Stand 20.11.2026)

| Wann | Was | Wer | Bedingung |
| --- | --- | --- | --- |
| Di 17.11. | Installer 0.5.0: Signatur durch Niko, danach Verteilung am Server und GitHub-Release v0.5.0 | Niko, W.A.I.S. | erledigt 07:00 |
| Di 17.11. | Messrunde mit 20 weiteren Läufen (R2, Marker bei a1) | W.A.I.S. | erledigt 07:07, Ergebnis unter R2, Ausweichweg unter R9 |
| Mi 18.11. | N3 bis N5 liefern: Preise und Ratenlimit, Fassung der Regeln, Büro-Adressen für die Ports 55446, 55322 und 56543 | Niko | erledigt 17.11. (N3 bis N5) |
| Do 19.11. | Erwartungswerte des Trainers zu W1 und W2 (N8) | Niko, Trainer | Pflicht vor dem Ausdruck |
| Fr 20.11. vormittags | **Lasttest voll**: Stufen 1, 2, 4, 8 mit je 15 Minuten, danach Murmelstufen, mit Preisen, Ratenlimit und `--kosten-obergrenze`. Vorher den Kern-Kanal sperren (`wamo-job-kern-rueckweg.sh notaus`) und die Plätze 1 bis 8 leeren (Betreuer-Aktion „Daten löschen“, Starttickets zählen als belegt) | W.A.I.S., Niko | Ja von Niko, N3, E5 |
| Di 17.11. (vorgezogen) | Vorstufe Lasttest mit 2 und 4 Sitzungen je 10 Minuten, dazu Messlauf CPU je Thread | W.A.I.S. | erledigt, siehe N.1a |
| Fr 20.11. nachmittags | Zweite Faktoren neu auf die Betreuer-Geräte (E2), zuerst ein Profil, mit QR zum Scannen (`einrichten --profile labor-01 --neu --qr`, Ablauf Runbook 9.7). Die zweiten Faktoren der Profile 01 bis 08 bleiben eingerichtet (05 bis 08 als Reserve). ~~Aufzeichnung des Schaufensters~~ entfällt (17.11.) | W.A.I.S., Betreuer, Niko | Lasttest abgeschlossen |
| Fr 20.11. | Finale Datenschutzrichtlinie der Betreuer (N11) liefern. Kommt sie bis dahin, wird sie als Fassung 2 vor dem Freeze eingebaut, sonst gilt Fassung 1 | Betreuer, W.A.I.S., Niko | N11 |
| Sa 21.11. | Letzte Freischaltungen der Mitglieder (E4). Puffer für Befunde aus dem Lasttest | Niko, W.A.I.S. | E4 |
| So 22.11. abends | Freeze-Kandidat ist ausgerollt: Kern mit Bewährung, Oberfläche, Labor-Rauchtest, Lasttest-Probelauf mit einer Sitzung. Ab hier nur noch Sicherheitskorrekturen mit Nikos Ja | W.A.I.S. | E1 |
| Mo 23.11. früh | **Freeze** (E1): Etikett `labor-freeze` auf den ausgerollten Stand. Kiosk-Test des Platz-Skripts auf einem echten Platz-Laptop im Kiosk-Konto und auf einem Ersatzgerät (`einrichten`, CA, `pruefen`, Board), Termin `[offen: Niko]`, muss vor dem Freeze liegen | W.A.I.S., Niko, Kollegen | Geräte da |
| Di 01.12. (vorher Di 24.11.) | Kartensatz drucken, Zahlen aus dem Lasttest ins Runbook | W.A.I.S., Niko | Lasttest-Ergebnis, W1, W2 |
| Mi 02.12. (vorher Mi 25.11.) | Betreuer-Token persönlich übergeben, Namen und Telefonnummern eintragen | Niko | N6, N7 |
| Do 03.12. (vorher Do 26.11.) | Generalprobe, drei Stunden, vier Kollegen als Besucher an den Plätzen 1 bis 4, zwei Betreuer, Reserve-Laptop (Platz 9) | alle | Kartensatz gedruckt |
| Fr 04.12. (vorher Fr 27.11.) | Daten-Freeze 12:00. Rückwegübung mit dem Ziel aus E6, Einweisung der Betreuer. Ab 12:00 kein Neustart des Gateways bis Sa 05.12. abends (N10) | W.A.I.S., Betreuer, Niko | Morgencheckliste Teil A |
| Sa 05.12. (vorher Sa 28.11.) | Labortag. Kern-Kanal morgens sperren, kein Neustart des Gateways | alle | Morgencheckliste Teil B |
| ab Mo 07.12. (vorher Mo 30.11.) | Nachlauf `wamo_labor_nachlauf.py nachlauf --ausfuehren`, Kern-Kanal wieder öffnen (`notaus-aufheben`, `schluessel`). Messungen H0 und M3 (`docs/hausmodelle-und-kikollege.md`) | W.A.I.S. | Runbook Abschnitt 10 |
| Mo 07.12. bis Fr 11.12. (vorher Mo 30.11. bis Fr 04.12.) | Laborkonten löschen und Sitzungen widerrufen, nach dem Nachlauf. Das Werkzeug liegt vor: `infra/sokrates2/wamo_labor_konten_loeschen.py` (Trockenlauf als Standard, Bestätigungswort, Höchstgrenze 12, Nachweis). Ablauf: Trockenlauf `ssh wamo-sokrates2 "python3 -E -s ~/wamo-infra/wamo_labor_konten_loeschen.py"`, dann ein Reservekonto mit `--kennung labor-09 --ausfuehren --bestaetigung LABORKONTEN-LOESCHEN`, dann alle mit `--ausfuehren --bestaetigung LABORKONTEN-LOESCHEN` | W.A.I.S., Niko | Nachlauf gelaufen, Ja von Niko, Runbook Abschnitt 10, Punkt 6 |
| bis zur Löschfrist Fr 18.12.2026, Löschlauf ab Sa 19.12.2026 (entschieden am 20.11.2026; vorher bis Fr 11.12., Löschlauf ab 12.12.) | Nachweis "verbliebene Laborkonten: 0" (Ausgang 0, Zeile in `journalctl -t wamo-labor-loeschen`), Umschlag-Datei und Sicherungen löschen. Danach Löschlauf des Dienstes | W.A.I.S., Niko | Ja von Niko |

### N.5 Offene Lieferungen

Stand am 17.11.2026, Nachmittag: N3 bis N5 erledigt. Datenschutz: Fassung 1 des Hinweises am 17.11. von Niko freigegeben, die finale Datenschutzrichtlinie liefern die Betreuer (N11, Fassung 2 nur bis Fr 20.11.). Offen sind N6 bis N8, N10 und N11 (Abschnitt 5). N10 ist neu: Gateway ohne Neustart von Fr 04.12. 12:00 bis Sa 05.12. abends (verschoben auf 05.12.2026, Stand 20.11.2026; vorher Fr 27.11. bis Sa 28.11.). Niko betreut das Gateway selbst (`infra/sokrates1/gateway-wamo.md`).

---

**Stand:** 16.11.2026, Nachmittag. Dieser Plan ersetzt die Fassung vom 13.11.2026. Der damalige Freeze am 15.11. ist überholt: Auf ausdrücklichen Auftrag von Niko liefen seitdem die Releases 0.2.0 bis 0.4.1 (Erstanmeldung, Werkzeuge und Entwicklungsaufträge für Mitglieder, Hausmodelle, gleichzeitige Aufträge). Der Plan entstand mit dem ECC-Planer (Regressionsanalyse) und REA (Analyse der ausgelieferten Oberfläche) und ist mit echten Läufen am Server belegt. Was belegt ist, steht mit Quelle im Text. Was nur ein Mensch klären oder ein echter Lauf zeigen kann, steht in Abschnitt 5 und 6.

## 1. Stand am 16.11. (gemessen)

| Baustein | Stand | Beleg |
| --- | --- | --- |
| Kern | Slot b `v0.4.1-fecb8e5` aktiv, Slot a `v0.4.0-55eb122` inaktiv (Rückweg-Ziel, mit Erstanmeldung) | `wamo-core-slots.sh status` am Server |
| Oberfläche | 0.4.1 live (Commit `fecb8e5`) | `https://192.168.178.136:55445/version.json` |
| Labor-Dienst | Container gesund, Rauchtest mit root 0 Fehler | `wamo_labor_rauchtest.py --betrieb` am 16.11. |
| Kern-Umgebung | `WAMO_LABOR_TEXT_SPEICHERN='an'`, `WAMO_LABOR_EINWILLIGUNG_MIN='1'`, Labordaten unter `/etc/wamo-labor/daten` | `core.env` (nur diese Zeilen gelesen) |
| Laborprofile | `labor-01` bis `labor-09` gesperrt, Seeds in der Umschlag-Datei | `wamo_labor.py status` |
| Plätze | Platz 1 nach dem Lasttest leer (ohne Starttickets), Plätze 2 bis 8 geschlossen mit 6 Starttickets | Betreuer-Schnittstelle |
| Kern-Kanal | Dispatcher 9, Kanal für `recherche` offen bis 11.12., höchstens 6 Aufträge gleichzeitig, 3 je Person | `wamo-job-dispatch ping` |

## 2. Regression seit dem Labor-Release `c751d04`

Der Kern hat sich seit dem Labor-Release in 66 Dateien geändert (rund 8 900 Zeilen ohne Tests). Geprüft auf drei Wegen:

**ECC-Planer (Code und Tests).** Kein Weg gefunden, auf dem Erstanmeldung, Sitzungswächter, Trigger 0021 (`profiles_freischaltung_guard`) oder die Einrichtungs-Prüfliste ein Laborprofil sperren oder abmelden. Jede neue Prüfung fragt zuerst `labor.ist_labor` oder `labor_art` ab und liest den Stand erst danach, jede Abzweigung hat einen eigenen Test (unter anderem `test_erstanmeldung.py` mit `test_laborprofil_fragt_den_stand_nie_ab`, `test_labor_sperre.py` mit `test_t2_jede_route_der_apps_ist_gesperrt_ausser_der_liste`). Die Pfadliste des Labors (`voice-core/labor.py`, `_ROUTEN_ART`) ist so eng wie vorher. Die Lücke im Werkzeugtest (Serverschalter seit dem Labor-Release fehlten in den Testumgebungen) ist mit PR #172 geschlossen: Auch mit allen neuen Schaltern gleichzeitig bekommt eine Laborsitzung genau ihre Erlaubnisliste.

**REA (ausgelieferte Oberfläche 0.4.1).** 94 JavaScript-Dateien ohne Anmeldung geladen, die Datei mit dem App-Code mit `rea analyze-javascript-application` untersucht (Evidenz `ev_dde490d0c5297373d6c56e9e51f9491a2ea6929d680d7c8e6104a5c33ae17767`). Die Oberfläche ruft den Kern über eine gemeinsame Hilfe `/wamo/api` plus Pfad auf, die Routen der Erstanmeldung stehen als Text im Bundle. Ein 403 `labor_pfad_gesperrt` behandelt die Oberfläche als „keine Erstanmeldung“ (`ui/src/lib/erstanmeldung.ts`), Laborkonten fragen den Stand gar nicht ab. **Grenzen:** REA liest nur Text, die Analyse einer sehr großen Bibliotheksdatei lief in die Zeitgrenze und ist nicht enthalten.

**Echte Läufe am Server.**
- Probelauf einer Laborsitzung (labor-01, Niko im Browser): Anmeldung mit zweitem Faktor ohne Passwortwechsel und ohne „Erste Schritte“, Sitzung auf Platz 1 mit 6 Werkzeugen, Ticket-Suche im Dienst, Tafel, 0 Fehler im Journal. Danach gesperrt und gelöscht.
- Lasttest-Probelauf mit 1 Sitzung und 3 Minuten (`last-20261116-145550`): Anmeldung im Browser, Gespräch mit Sprechproben, Freigabekarte bei J1, Aufräumen vollständig. 0 Abbrüche, 0 mal 429, Speicher 0,31 GiB, CPU des Kerns p95 43,5 Prozent eines Kerns, erster Ton p50 1,39 s und p95 4,47 s (nur 5 Schritte). Vorher behoben: Das Messwerkzeug suchte die cgroup der Kern-Slots am falschen Ort (PR #173).
- Messrunde mit den 17 Karten (Haiku, 10 Läufe, Standardfassung, Kosten 0,08 US-Dollar): **0 Muss-Verstöße**, j1 bis j3, w1, m2 wie am 13.11. **Befund:** w2 fällt von 7 auf 0 von 10 (Haiku setzt den Marker ◐ statt ● und schweigt), a2 von 10 auf 7 von 10. Ursache und Korrektur sind in Arbeit (Abschnitt 4).

## 3. Entscheidungen von Niko (16.11.2026)

| Nr | Entscheidung |
| --- | --- |
| E1 | **Freeze Mo 23.11. früh.** Bis So 22.11. abends darf Code gemergt und ausgerollt werden, danach nur Sicherheitskorrekturen mit Nikos Ja. Daten-Freeze Fr 04.12., 12:00 (verschoben auf 05.12.2026, Stand 20.11.2026; vorher Fr 27.11.) |
| E2 | Zweite Faktoren der Laborprofile neu auf die Betreuer-Geräte am **Fr 20.11. nach dem Lasttest**, damit gilt die Regel „keine Änderung an der Anmeldung in der Laborwoche“ |
| E3 | Messrunde auf 0.4.1 wiederholt (erledigt, Ergebnis in Abschnitt 2) |
| E4 | **Mitglieder bis Sa 21.11.** freigeschaltet und mit gewechseltem Passwort, wer es nicht schafft, kommt nach dem Labortag dran, ab Mo 07.12. (verschoben auf 05.12.2026, Stand 20.11.2026; vorher ab Mo 30.11.) |
| E6 | Rückweg-Ziel des Kerns ist immer ein Release mit Erstanmeldung (ab 0.3.0), nie `c751d04` oder älter. Ein solcher Kern kennt `wamo_auth` nicht und ließe Mitglieder mit offenem Passwortwechsel in die App |

## 4. Fahrplan (Stand 16.11.; ab Di 17.11. gilt Nachtrag N.4; die Termine ab Di 24.11. sind mit dem Labortag um 7 Tage verschoben, Stand 20.11.2026)

| Wann | Was | Wer | Bedingung |
| --- | --- | --- | --- |
| Mo 16.11. | Regression (Abschnitt 2), Korrektur des Markers bei w2 mit Messung vorher und nachher | W.A.I.S. | erledigt bis auf die Korrektur |
| Di 17.11. | Korrektur des Markers mergen und ausrollen (Kern über die Slots, Bewährung 30 Minuten, Labor-Rauchtest), danach Messrunde der 17 Karten wiederholen | W.A.I.S. | CI grün |
| Di 17.11. bis Mi 18.11. | Konsole des Sprachmodells: Preise, Ratenlimit, Ausgabenlimit (N3). Soniox: mindestens 9 gleichzeitige Sitzungen bestätigen. N4 bis N6 | Niko | Abschnitt 5 |
| Do 19.11. | Erwartungswerte des Trainers zu W1 und W2 | Niko, Trainer | Pflicht vor dem Ausdruck |
| Fr 20.11. vormittags | **Lasttest voll**: Stufen 1, 2, 4, 8 mit je 15 Minuten, danach Murmelstufen, mit Preisen, Ratenlimit und `--kosten-obergrenze`. Vorher die Plätze 1 bis 8 leeren (Betreuer-Aktion „Daten löschen“, der Lasttest verlangt Plätze ohne Starttickets) und den Kern-Kanal sperren (`wamo-job-kern-rueckweg.sh notaus`), damit keine Entwicklungsaufträge mitlaufen | W.A.I.S., Niko | Ja von Niko, N3 |
| Fr 20.11. nachmittags | Zweite Faktoren neu auf die Betreuer-Geräte (E2), zuerst ein Profil. Aufzeichnung des Schaufensters | W.A.I.S., Betreuer, Niko | E2 |
| Sa 21.11. | Letzte Freischaltungen der Mitglieder (E4). Puffer für Befunde aus dem Lasttest | Niko, W.A.I.S. | E4 |
| So 22.11. abends | Freeze-Kandidat ist ausgerollt (Kern mit Bewährung, Oberfläche, Labor-Rauchtest, Lasttest-Probelauf mit 1 Sitzung) | W.A.I.S. | E1 |
| Mo 23.11. früh | **Freeze** (E1): Etikett `labor-freeze` auf den ausgerollten Stand. Platz-Skript auf einem echten Laptop im Kiosk-Konto und einem Ersatzgerät (`einrichten`, CA, `pruefen`, Board) | W.A.I.S., Niko, Kollegen | Geräte da |
| Di 01.12. (vorher Di 24.11.) | Kartensatz drucken, Zahlen aus dem Lasttest ins Runbook | W.A.I.S., Niko | W1, W2 |
| Mi 02.12. (vorher Mi 25.11.) | Betreuer-Token persönlich übergeben, Namen und Telefonnummern eintragen | Niko | N6, N7 |
| Do 03.12. (vorher Do 26.11.) | Generalprobe, drei Stunden, vier Kollegen als Besucher, zwei Betreuer, acht Geräte | alle | Kartensatz gedruckt |
| Fr 04.12. (vorher Fr 27.11.) | Daten-Freeze 12:00, Rückwegübung mit dem Ziel aus E6, Einweisung der Betreuer | W.A.I.S., Betreuer | Morgencheckliste Teil A |
| Sa 05.12. (vorher Sa 28.11.) | Labortag. Kern-Kanal morgens sperren (`notaus`) | alle | Morgencheckliste Teil B |
| Mo 07.12. (vorher Mo 30.11.) | Nachlauf `wamo_labor_nachlauf.py nachlauf --ausfuehren`, Kern-Kanal wieder öffnen (`notaus-aufheben`, `schluessel`) | W.A.I.S. | Runbook Abschnitt 10 |
| Mo 07.12. bis Fr 11.12. (vorher Mo 30.11. bis Fr 04.12.) | Skript zum Löschen der Laborkonten und Widerrufen der Sitzungen (Trockenlauf als Standard, Bestätigungswort, Nachweis), mit Review | W.A.I.S. | Lücke 1 |
| bis zur Löschfrist Fr 18.12.2026, Löschlauf ab Sa 19.12.2026 (entschieden am 20.11.2026; vorher bis Fr 11.12., Löschlauf ab 12.12.) | Skript ausführen, Umschlag-Datei und Sicherungen löschen. Danach Löschlauf des Dienstes | W.A.I.S., Niko | Ja von Niko |

## 5. Was Niko noch entscheiden oder liefern muss

| Nr | Was | Frist | Empfehlung |
| --- | --- | --- | --- |
| N3 | Preise und Ratenlimit aus der Konsole für den Lasttest | Mi 18.11. | erledigt 17.11.: Ausgabenlimit 100 USD; Ratenlimit des Schlüssels für Haiku 5.5 4.000 Anfragen, 2 Mio. Eingabe- und 400.000 Ausgabe-Tokens je Minute; Preise 0,10 und 0,50 USD je Mio. Tokens |
| N4 | Q6: Fassung der Regeln | Mi 18.11. | erledigt 17.11.: Standard bestätigt |
| N5 | Q13: Büro-Adressen für 55446, 55322 und 56543 in `LAN_PORTS_ADMIN` (Liste `/etc/wamo/admin-quellen`, PR #185, `infra/sokrates2/README.md` 6.1) | Mi 18.11. | erledigt 17.11.: Liste mit dem Laptop des Admins (WLAN und feste WireGuard-Adresse), eingespielt mit `--trocken` und Rauchtests |
| N6 | Weg des Betreuer-Tokens | Mi 18.11. | Persönliche Übergabe am Gerät, nie Chat, Mail oder Ausdruck |
| N7 | Namen, Telefonnummern, Raum, Zeiten (Runbook Abschnitt 8 und 11) | Mi 02.12. (vorher Mi 25.11.) | vor der Generalprobe |
| N8 | W1 und W2 vom Trainer, Seminar-Angaben, Soniox-Vertragspartner GmbH, Aufbewahrung über die Löschfrist hinaus (Frist offen, siehe Nachtrag 20.11.) | Do 19.11. | wie in der Morgencheckliste; Entwurf mit Musterantworten an den verantwortlichen Trainer am 17.11., Seminar-Angaben sind kein Muss (`ausgang.md` verweist sonst auf den Stand) |
| N10 | Gateway (zentrales LiteLLM auf Sokrates-1): kein Neustart von Fr 04.12. 12:00 bis Sa 05.12. abends (vorher Fr 27.11. bis Sa 28.11.). Niko betreut es selbst, Betriebsnotiz `infra/sokrates1/gateway-wamo.md` | Fr 04.12. 12:00 | Keine Änderung am Gateway in dieser Zeit |
| N11 | Datenschutz: finale Datenschutzrichtlinie der Betreuer. Fassung 1 des Hinweises ist am 17.11. von Niko freigegeben (`docs/labor-datenschutz-entwurf.md`, Dienst `labor-dienst/wamo_labor_dienst/web/datenschutz.html`) | Fr 20.11. für Fassung 2, sonst gilt am Labortag Fassung 1 | Kommt sie bis Fr 20.11., wird sie als Fassung 2 vor dem Freeze eingebaut: neuer Text im Dienst, Versionsnummer 2 auf der Betreuer-Seite, `WAMO_LABOR_EINWILLIGUNG_MIN=2` am Kern mit dem Freeze-Kandidaten So 22.11. |
| E5 | Kern-Kanal während Lasttest und Labortag sperren | Fr 20.11. | Ja. Der Grund Schaufenster entfällt (17.11.), der gemeinsame Server bleibt (Abschnitt 6, Punkt 4) |

## 6. Lücken und Risiken

1. **Laborkonten löschen und Sitzungen widerrufen:** Das Werkzeug liegt vor (`infra/sokrates2/wamo_labor_konten_loeschen.py`, Runbook Abschnitt 10, Punkt 6). Offen ist der Lauf am Server nach dem Nachlauf, im Fenster Mo 07.12. bis Fr 11.12. Erst der Lauf zeigt, ob die Rolle postgres die Tabellen im Schema auth lesen und dort löschen darf.
2. **Marker bei w2:** Bis zur Korrektur schweigt W.A.I.S. bei der Wissensfrage zur CTFL-Prüfung. Ob der Büro-Prompt betroffen ist, klärt die Ursachenanalyse.
3. **CPU des Kerns:** schon bei 1 Sitzung p95 43,5 Prozent eines Kerns. Erst der volle Lasttest zeigt, ob 4 Sitzungen (Betrieb) und 8 Sitzungen (Reserve) unter 70 Prozent bleiben.
4. **Gemeinsamer Server:** Entwicklungsaufträge (bis 6) und das Hausmodell teilen sich Sokrates-2 mit dem Kern und dem Labor-Dienst. Darum sperrt der Kern-Kanal während Lasttest und Labortag.
5. **Ein Schlüssel für alle Plätze** (Ratenlimit und Guthaben). Der Lasttest ist die einzige Messung dafür.
6. **Platz-Laptop im Kiosk-Konto** wurde noch nicht gesehen, der Rauchtest am Server kann das nicht belegen. Kiosk-Test auf einem echten Platz-Laptop vor dem Freeze, Termin `[offen: Niko]`.
7. **Gäste-Laptops im flachen Büronetz**, das Netzkonzept liegt bei den Kollegen.

---

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
