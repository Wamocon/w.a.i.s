# Testlabor 28.11.2026: Restplan ab Montag, 16.11.2026

## Nachtrag 17.11.2026: Live-Stand, Risiken und Fahrplan bis 11.12.

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

### N.2 Entscheidungen von Niko, Ergänzung

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
| R5 | Die TTS-Instanz hat keine Speichergrenze, sie hat nur ein Lock | offen |
| R6 | Gateway-Änderungen sind nur in unserem Repo dokumentiert | teilweise: Betriebsnotiz `infra/sokrates1/gateway-wamo.md` angelegt, Pflege beim Betreiber |
| R7 | Geordnetes Abschalten des Kerns: Fristen, Timeout bei `ausleiten` | behoben mit #181 |
| R8 | Lasttest nahm einen festen Slot b an | behoben mit #182 |
| R9 | Ausweichweg Hausmodell `gemma4-31b` (3 Läufe am 17.11.): a1 bricht in 3 von 3 Läufen ab. Der erste Satz kommt nach 0,7 s, der Aufruf von `canvas_zeigen` mit den Stories kommt als Block und überschreitet die Lesefrist des Gesprächs von 20 s (`GESPRAECH_LESE_TIMEOUT_SECS`). Gilt auch im Büro für Nutzer mit Hausmodellen. Vorschlag: längere Lesefrist nur für Hausmodelle, Entscheidung durch Niko vor dem Freeze-Kandidaten | offen |
| R10 | Büro-Fall I04 („Puh, das ist schwierig.“ soll warten): am 17.11. 4 von 17 Läufen bestanden (vor #176 4 von 5, danach 3 von 5). W.A.I.S. antwortet sofort mit einer freundlichen Rückfrage statt zu warten. Betrifft nur das Büro, das Labor hat diesen Fall nicht. Vorschlag: ein Beispiel in der Marker-Regel ergänzen und mit der Messrunde gegenprüfen, Entscheidung durch Niko | offen |

### N.4 Fahrplan Di 17.11. bis Fr 11.12.

| Wann | Was | Wer | Bedingung |
| --- | --- | --- | --- |
| Di 17.11. | Installer 0.5.0: Signatur durch Niko, danach Verteilung am Server und GitHub-Release v0.5.0 | Niko, W.A.I.S. | erledigt 07:00 |
| Di 17.11. | Messrunde mit 20 weiteren Läufen (R2, Marker bei a1) | W.A.I.S. | erledigt 07:07, Ergebnis unter R2, Ausweichweg unter R9 |
| Mi 18.11. | N3 bis N5 liefern: Preise und Ratenlimit, Fassung der Regeln, Büro-Adressen für die Ports 55446, 55322 und 56543 | Niko | Abschnitt 5 |
| Do 19.11. | Erwartungswerte des Trainers zu W1 und W2 (N8) | Niko, Trainer | Pflicht vor dem Ausdruck |
| Fr 20.11. vormittags | **Lasttest voll**: Stufen 1, 2, 4, 8 mit je 15 Minuten, danach Murmelstufen, mit Preisen, Ratenlimit und `--kosten-obergrenze`. Vorher den Kern-Kanal sperren (`wamo-job-kern-rueckweg.sh notaus`) und die Plätze 1 bis 8 leeren (Betreuer-Aktion „Daten löschen“, Starttickets zählen als belegt) | W.A.I.S., Niko | Ja von Niko, N3, E5 |
| Fr 20.11. nachmittags | Zweite Faktoren neu auf die Betreuer-Geräte (E2), zuerst ein Profil. Aufzeichnung des Schaufensters | W.A.I.S., Betreuer, Niko | Lasttest abgeschlossen |
| Sa 21.11. | Letzte Freischaltungen der Mitglieder (E4). Puffer für Befunde aus dem Lasttest | Niko, W.A.I.S. | E4 |
| So 22.11. abends | Freeze-Kandidat ist ausgerollt: Kern mit Bewährung, Oberfläche, Labor-Rauchtest, Lasttest-Probelauf mit einer Sitzung. Ab hier nur noch Sicherheitskorrekturen mit Nikos Ja | W.A.I.S. | E1 |
| Mo 23.11. früh | **Freeze** (E1): Etikett `labor-freeze` auf den ausgerollten Stand. Platz-Skript auf einem echten Laptop im Kiosk-Konto und auf einem Ersatzgerät (`einrichten`, CA, `pruefen`, Board) | W.A.I.S., Niko, Kollegen | Geräte da |
| Di 24.11. | Kartensatz drucken, Zahlen aus dem Lasttest ins Runbook | W.A.I.S., Niko | Lasttest-Ergebnis, W1, W2 |
| Mi 25.11. | Betreuer-Token persönlich übergeben, Namen und Telefonnummern eintragen | Niko | N6, N7 |
| Do 26.11. | Generalprobe, drei Stunden, vier Kollegen als Besucher, zwei Betreuer, acht Geräte | alle | Kartensatz gedruckt |
| Fr 27.11. | Daten-Freeze 12:00. Rückwegübung mit dem Ziel aus E6, Einweisung der Betreuer. Ab 12:00 kein Neustart des Gateways bis Sa 28.11. abends (N10) | W.A.I.S., Betreuer, Niko | Morgencheckliste Teil A |
| Sa 28.11. | Labortag. Kern-Kanal morgens sperren, kein Neustart des Gateways | alle | Morgencheckliste Teil B |
| ab Mo 30.11. | Nachlauf `wamo_labor_nachlauf.py nachlauf --ausfuehren`, Kern-Kanal wieder öffnen (`notaus-aufheben`, `schluessel`). Messungen H0 und M3 (`docs/hausmodelle-und-kikollege.md`) | W.A.I.S. | Runbook Abschnitt 10 |
| Mo 30.11. bis Fr 04.12. | Skript zum Löschen der Laborkonten und Widerrufen der Sitzungen (Trockenlauf als Standard, Bestätigungswort, Nachweis), mit Review | W.A.I.S. | Lücke 1 |
| bis Fr 11.12. | Skript ausführen, Umschlag-Datei und Sicherungen löschen. Ab 12.12. Löschlauf des Dienstes | W.A.I.S., Niko | Ja von Niko |

### N.5 Offene Lieferungen

Offen am 17.11.2026: N3 bis N8 und N10 (Abschnitt 5). N10 ist neu: Gateway ohne Neustart von Fr 27.11. 12:00 bis Sa 28.11. abends. Niko betreut das Gateway selbst (`infra/sokrates1/gateway-wamo.md`).

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
| E1 | **Freeze Mo 23.11. früh.** Bis So 22.11. abends darf Code gemergt und ausgerollt werden, danach nur Sicherheitskorrekturen mit Nikos Ja. Daten-Freeze Fr 27.11., 12:00 bleibt |
| E2 | Zweite Faktoren der Laborprofile neu auf die Betreuer-Geräte am **Fr 20.11. nach dem Lasttest**, damit gilt die Regel „keine Änderung an der Anmeldung in der Laborwoche“ |
| E3 | Messrunde auf 0.4.1 wiederholt (erledigt, Ergebnis in Abschnitt 2) |
| E4 | **Mitglieder bis Sa 21.11.** freigeschaltet und mit gewechseltem Passwort, wer es nicht schafft, kommt ab Mo 30.11. dran |
| E6 | Rückweg-Ziel des Kerns ist immer ein Release mit Erstanmeldung (ab 0.3.0), nie `c751d04` oder älter. Ein solcher Kern kennt `wamo_auth` nicht und ließe Mitglieder mit offenem Passwortwechsel in die App |

## 4. Fahrplan (Stand 16.11.; ab Di 17.11. gilt Nachtrag N.4)

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
| Di 24.11. | Kartensatz drucken, Zahlen aus dem Lasttest ins Runbook | W.A.I.S., Niko | W1, W2 |
| Mi 25.11. | Betreuer-Token persönlich übergeben, Namen und Telefonnummern eintragen | Niko | N6, N7 |
| Do 26.11. | Generalprobe, drei Stunden, vier Kollegen als Besucher, zwei Betreuer, acht Geräte | alle | Kartensatz gedruckt |
| Fr 27.11. | Daten-Freeze 12:00, Rückwegübung mit dem Ziel aus E6, Einweisung der Betreuer | W.A.I.S., Betreuer | Morgencheckliste Teil A |
| Sa 28.11. | Labortag. Kern-Kanal morgens sperren (`notaus`) | alle | Morgencheckliste Teil B |
| Mo 30.11. | Nachlauf `wamo_labor_nachlauf.py nachlauf --ausfuehren`, Kern-Kanal wieder öffnen (`notaus-aufheben`, `schluessel`) | W.A.I.S. | Runbook Abschnitt 10 |
| Mo 30.11. bis Fr 04.12. | Skript zum Löschen der Laborkonten und Widerrufen der Sitzungen (Trockenlauf als Standard, Bestätigungswort, Nachweis), mit Review | W.A.I.S. | Lücke 1 |
| bis Fr 11.12. | Skript ausführen, Umschlag-Datei und Sicherungen löschen. Ab 12.12. Löschlauf des Dienstes | W.A.I.S., Niko | Ja von Niko |

## 5. Was Niko noch entscheiden oder liefern muss

| Nr | Was | Frist | Empfehlung |
| --- | --- | --- | --- |
| N3 | Preise und Ratenlimit aus der Konsole für den Lasttest | Mi 18.11. | Eintragen, dann gilt `--kosten-obergrenze` |
| N4 | Q6: Fassung der Regeln | Mi 18.11. | Standard (steht am Server) |
| N5 | Q13: Büro-Adressen für 55446, 55322 und 56543 in `LAN_PORTS_ADMIN` (Liste `/etc/wamo/admin-quellen`, `infra/sokrates2/README.md` 6.1) | Mi 18.11. | Liste der Admin-Geräte nennen, Firewall-Änderung mit `--trocken` und Rückweg |
| N6 | Weg des Betreuer-Tokens | Mi 18.11. | Persönliche Übergabe am Gerät, nie Chat, Mail oder Ausdruck |
| N7 | Namen, Telefonnummern, Raum, Zeiten (Runbook Abschnitt 8 und 11) | Mi 25.11. | vor der Generalprobe |
| N8 | W1 und W2 vom Trainer, Seminar-Angaben, Soniox-Vertragspartner GmbH, Aufbewahrung über den 11.12. | Do 19.11. | wie in der Morgencheckliste |
| N10 | Gateway (zentrales LiteLLM auf Sokrates-1): kein Neustart von Fr 27.11. 12:00 bis Sa 28.11. abends. Niko betreut es selbst, Betriebsnotiz `infra/sokrates1/gateway-wamo.md` | Fr 27.11. 12:00 | Keine Änderung am Gateway in dieser Zeit |
| E5 | Kern-Kanal während Lasttest und Labortag sperren | Fr 20.11. | Ja, das Schaufenster zeigt nur die Aufzeichnung |

## 6. Lücken und Risiken

1. **Laborkonten löschen und Sitzungen widerrufen:** noch kein Skript (Bau nach dem Labortag, Fahrplan).
2. **Marker bei w2:** Bis zur Korrektur schweigt W.A.I.S. bei der Wissensfrage zur CTFL-Prüfung. Ob der Büro-Prompt betroffen ist, klärt die Ursachenanalyse.
3. **CPU des Kerns:** schon bei 1 Sitzung p95 43,5 Prozent eines Kerns. Erst der volle Lasttest zeigt, ob 8 Sitzungen unter 70 Prozent bleiben.
4. **Gemeinsamer Server:** Entwicklungsaufträge (bis 6) und das Hausmodell teilen sich Sokrates-2 mit dem Kern und dem Labor-Dienst. Darum sperrt der Kern-Kanal während Lasttest und Labortag.
5. **Ein Schlüssel für alle Plätze** (Ratenlimit und Guthaben). Der Lasttest ist die einzige Messung dafür.
6. **Platz-Laptop im Kiosk-Konto** wurde noch nicht gesehen, der Rauchtest am Server kann das nicht belegen.
7. **Gäste-Laptops im flachen Büronetz**, das Netzkonzept liegt bei den Kollegen.

---

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
