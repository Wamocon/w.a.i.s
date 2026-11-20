# Admin-Panel "Werkstatt" für W.A.I.S.: Konzeptentwurf

Stand: 20.11.2026. Status: Die fünf Entscheidungen in Abschnitt 7 hat Niko am 20.11.2026 getroffen. Anlass ist der Wunsch von Niko vom 20.11.2026 nach einem separat aufrufbaren Admin-Panel, in dem sich ein Labortag planen und konfigurieren lässt und das Dashboards und Protokolle enthält.

Der Bauplan mit Arbeitspaketen, Schnittstelle, Datenmodell, Testplan und der Inventur der vorhandenen Schnittstellen steht in `docs/adminpanel-bauplan.md`.

## 1. Einschätzung

Die Idee lohnt sich, aber erst nach dem Labortag am 05.12.2026 und nur als getrennter, schmaler Dienst. Der größte Nutzen: Stand, Protokolle und Laborvorbereitung liegen an einem Ort. Heute sind es über ein Dutzend Einstiegsskripte mit ssh (`docs/labor-runbook.md`, Abschnitte 9 und 10). Die größte Gefahr ist ein Generalschlüssel im Browser, der Profile freischaltet und Daten löscht und so die heutige Rechtetrennung aushebelt.

## 2. Zielbild und Nutzer

Das Panel ist nur für Admins ohne Laborprofil und nur aus den Admin-Quellen erreichbar (`infra/sokrates2/README.md`, Abschnitt 6.1). Admins sehen den Betrieb in Zahlen und lesen gefilterte Protokolle. Sie planen einen Labortag vom Termin bis zum Nachlauf und überblicken Releases, Installer und den Rückstand. Durchläufe und Einwilligungen bleiben auf der Betreuer-Seite des Labor-Dienstes (`docs/labor-dienst-vertrag.md`, Abschnitt 6, D9). Die Werkstatt verlinkt sie nur.

## 3. Funktionsblöcke

| Block | Beispiele | Zugriff |
| --- | --- | --- |
| Dashboards | Sitzungen, Latenz p50 und p95 (`voice-core/latenz.py`), Verbrauch je Baustein (`voice-core/llm_anbieter.py`), Aufträge (`kernkanal.jsonl`), Kern-Slots, Installer | lesend |
| Protokolle | Journal-Marken nach Erlaubnisliste (`docs/produktdokumentation/betrieb.md`, Abschnitt 10), Tabelle `actions`, Löschnachweise | lesend |
| Labor-Planer | Termin, Plätze, Einwilligungsversion, Checkliste; Laborprofile freischalten und sperren, Zählung, Löschwunsch je Zeitfenster, Nachlauf als geführter Ablauf | schreibend mit Karte |
| Werkstatt | Release-Stand, Selbstaufträge (`docs/selbstauftraege.md`), Schalter-Übersicht | lesend |

Diese Handgriffe bleiben Skript:

- Konten anlegen (läuft über die Umschlag-Datei)
- zweite Faktoren mit QR
- Laborkonten löschen (liest den Dienstschlüssel, `infra/sokrates2/wamo_labor_konten_loeschen.py`)
- Dienst und Labor-Daten einrichten sowie der Löschlauf (alle drei brauchen root)
- Platz-Skript (läuft am Kiosk-Laptop)
- Lasttest und Schlüsseltausch

## 4. Architekturvarianten

**A: Bereich in der Oberfläche, API im Kern.** Die Muster gibt es schon (`voice-core/mitglieder_admin_api.py`, Gruppe "Verwaltung" in `ui/src/lib/einstellungenAbschnitte.ts`), der Aufwand ist gering. Nachteile: Der Kern bräuchte Rechte, die heute nur `wamo_admin` hat (`voice-core/wamo_admin.py`). Jede Änderung wird ein Kern-Release, und der Sprachpfad bekommt mehr Angriffsfläche.

**B: Eigener Dienst.** Er bekommt einen eigenen Benutzer und eine eigene Datenbankrolle (Vorschlag `wamo_werkstatt`). Er läuft auf einem eigenen Port hinter `wamo-caddy` (Vorschlag 55448, in `infra/` nicht belegt). Tokens prüft er über JWKS wie der Kern und der Freigabe-Dienst. Nachteil: Container, Caddy-Site, Firewall, Rauchtest und Rückweg kosten etwa 20 Stunden (Schätzung).

**C: Karten und Skripte im Gespräch.** Vorteil: Es braucht keinen neuen Bildschirm. Nachteile: Tabellen passen nicht in Sprache, das Modell sitzt zwischen Admin und Löschaktion, und es ist nicht separat aufrufbar.

**Empfehlung: B.** Die Oberfläche übernimmt Design und Bausteine aus `ui/`. Ob als gemeinsames Paket oder als eigener Build, ist eine Annahme und wird in Phase 0 geklärt.

## 5. Sicherheitsmodell

- **Zugang:** Rolle `admin`, aktives Profil, kein `labor_art`, zweiter Faktor (aal2), dazu eine Erlaubnisliste der Profile.
- **Schreibende Aktionen:** zuerst ein Trockenlauf wie in den Skripten, dann eine Karte mit Wirkung und Zahlen. Danach ein frischer zweiter Faktor, höchstens 60 Sekunden alt (`infra/sokrates2/anker/freigabe.py`). Mitglieder werden nur über den Merker-Trigger aus der Migration `0021` freigeschaltet.
- **Audit:** je Schritt eine Zeile in `actions` (`voice-core/memory.py`, `log_action`, `aktion_abschliessen`), dazu eine eigene Journal-Marke.
- **Trennung vom Kern:** kein `service_role`, kein root, kein Docker-Socket. Die Rolle bekommt nur `execute` auf `labor_zaehlen` und `labor_loeschen` und Lesesichten (Annahme, braucht eine neue Migration).
- **Datenschutz:** nur Zahlen, Dauern und Stände. Nie Gesprächstext, Gerätename oder E-Mail (Vorbild `voice-core/mikrofon_kette.py`).

## 6. Phasen (Stunden geschätzt)

| Phase | Inhalt | Aufwand | Zeitpunkt |
| --- | --- | --- | --- |
| 0 | Konzept, Entscheidungen, statischer Klickdummy im WMC-Design | 6 h | Entscheidungen bis Mo 23.11. früh; der Klickdummy berührt nichts Ausgerolltes |
| 1 | Dienst-Gerüst, Dashboards, Protokolle | 40 h | ab Mo 07.12., also nach dem Labortag am Sa 05.12.; Nachlauf und Kontenlöschung haben Vorrang |
| 2 | Labor-Planer mit Karten und Migration | 45 h | fertig vier Wochen vor dem nächsten Labortag (Termin offen) |
| 3 | Releases, Installer, Selbstaufträge, Aufträge | 40 h | nach Phase 2; der Release-Dienst ist erst ein Gerüst (`betrieb.md`, Abschnitt 9) |

Hinweise aus der Prüfung:

- Runbook und Datenschutzentwurf nannten zum Zeitpunkt der Prüfung noch den 28.11. (`betrieb.md`, Abschnitt 15); sie werden mit der Verschiebung auf den 05.12. angepasst.
- Das Ende des Freezes steht nirgends. Angenommen wird, dass er bis zum Labortag gilt.

## 7. Entscheidungen (Niko, 20.11.2026)

1. **Variante:** B, eigener schmaler Dienst.
2. **Zugang:** Admins mit Erlaubnisliste, nur aus den Admin-Quellen.
3. **Schreibumfang:** Alles, stufenweise, beginnend mit Laborkonfiguration und Laborerstellung (Termine, Plätze, Fristen, Checkliste, Laborprofile anlegen). Geheimnisse (Startpasswörter, zweite Faktoren mit QR und Seeds, Dienstschlüssel) erscheinen nie im Browser: Ein kleiner Helfer am Server erzeugt sie und übergibt sie nur an die Betreuer.
4. **Datenhaltung:** verdichtete Kennzahlen mit 30 Tagen Löschfrist statt Rohprotokollen.
5. **Vorrang nach dem 05.12.** gegenüber Plan C (67 bis 87 Stunden, `docs/persoenliche-zugaenge.md`, Abschnitt 4.3): Phase 1 läuft parallel dazu, Phase 2 ist vor dem nächsten Labortag fertig.

## 8. Risiken

1. **Generalschlüssel im Browser.** Gegenmaßnahme: Admin-Quellen, frischer zweiter Faktor je Aktion, schmale Rolle, Ratengrenzen, Audit.
2. **Gesprächsinhalte rutschen in die Protokolle.** Gegenmaßnahme: Erlaubnisliste der Felder, ein Test je Quelle, Löschfrist.
3. **Skript und Panel laufen auseinander.** Gegenmaßnahme: Beide nutzen dieselben Datenbankfunktionen, die Skripte bleiben der Rückweg, dazu ein Vertragstest wie `voice-core/test_kernkanal_vertrag.py`.
