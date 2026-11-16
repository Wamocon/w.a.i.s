# Testlabor 28.11.2026: Restplan ab Montag, 16.11.2026

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

## 4. Fahrplan

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
| N5 | Q13: Büro-Adressen für 55446, 55322 und 56543 in `LAN_PORTS_ADMIN` | Mi 18.11. | Liste der Admin-Geräte nennen, Firewall-Änderung mit `--trocken` und Rückweg |
| N6 | Weg des Betreuer-Tokens | Mi 18.11. | Persönliche Übergabe am Gerät, nie Chat, Mail oder Ausdruck |
| N7 | Namen, Telefonnummern, Raum, Zeiten (Runbook Abschnitt 8 und 11) | Mi 25.11. | vor der Generalprobe |
| N8 | W1 und W2 vom Trainer, Seminar-Angaben, Soniox-Vertragspartner GmbH, Aufbewahrung über den 11.12. | Do 19.11. | wie in der Morgencheckliste |
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
