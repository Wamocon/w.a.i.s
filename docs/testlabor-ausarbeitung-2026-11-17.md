# Testlabor: Ausarbeitung vom 17.11.2026

Stand: 17.11.2026. Dieses Dokument hält den Austausch vom 17.11.2026 zum Testlabor am Tag der offenen Tür (28.11.2026, Eschborn) fest. Es ist kein Rechtsrat. Punkte mit **[prüfen]** klärt der Datenschutzbeauftragte oder ein Anwalt.

Inhalt:

1. Entscheidungen vom 17.11.2026
2. Rechtliche Prüfung der Wissensbasis
3. To-Do-Liste für einen rechtlich sicheren Weg
4. Abgleich mit dem Konzept vom 05.11.2026 und Fassung 2 des Kartensatzes

Zugehörige Dateien: [testlabor-wamocon-wissensbasis.md](testlabor-wamocon-wissensbasis.md), [labor-kartensatz.html](labor-kartensatz.html) (Fassung 2), [labor-datenschutz-entwurf.md](labor-datenschutz-entwurf.md), [testlabor-wamo.md](testlabor-wamo.md).

## 1. Entscheidungen vom 17.11.2026

| Thema | Entscheidung |
| --- | --- |
| Datenschutzbeauftragter | intern benannt (der Entwurf [labor-datenschutz-entwurf.md](labor-datenschutz-entwurf.md) sagt noch „nicht bestellt“) |
| Verantwortlich | WAMOCON GmbH und WAMOCON Academy gemeinsam (Art. 26 DSGVO) |
| Gesprächstext | Variante A, es wird kein Gesprächstext gespeichert |
| Sprachmodell im Labor | lokales Modell statt Claude Haiku (E8 in [testlabor-wamo.md](testlabor-wamo.md) ist damit überholt) |
| Spracherkennung und Stimme | offen: Soniox oder im Haus (der Code erzwingt im Labor heute Soniox) |
| Alter | ab 18 |
| Websuche im Labor | aus |
| Fotos | ja, für Social Media |
| Kontakt | E-Mail und Telefon als getrennte Einwilligungen |
| CTFL-Kurs | AZAV-zugelassen, Academy beim GTB akkreditiert, Kursform gemischt (Präsenz und online, FernUSG prüfen) |

## 2. Rechtliche Prüfung der Wissensbasis

Geprüft wurden die Wissensbasis und die Datenschutzzusagen im Repo. Wichtigstes Ergebnis: Es gab zwei Datenschutztexte, die sich widersprechen (Wissensbasis Abschnitte 14 und 16 gegen den Entwurf vom 13.11. für den Labor-Modus). Bis zum 28.11. braucht es einen einzigen Text, den die Geschäftsführung abzeichnet.

> Stand nach den Entscheidungen: Punkt 2 (Datenschutzbeauftragter) ist durch den internen DSB erledigt. Punkt 3 (Anthropic) entfällt mit dem lokalen Modell; für Soniox gilt er nur, falls Soniox bleibt. Punkt 4 (Alter) ist mit „ab 18“ entschieden. Die Zeilennummern beziehen sich auf den Stand der Wissensbasis am 17.11.2026.

### Übersicht

| Nr | Punkt | Risiko | Was tun |
| --- | --- | --- | --- |
| 1 | Zwei Datenschutztexte widersprechen sich | kritisch | Einen Text festlegen, die Geschäftsführung zeichnet ab |
| 2 | Pflicht zur DSFA zieht die Pflicht zu einem Datenschutzbeauftragten nach sich | kritisch | Bis spätestens ca. 20.11. entscheiden |
| 3 | Daten gehen an Anthropic (USA) und Soniox, der Vertragspartner ist unklar | kritisch | Verträge mit den Dienstleistern (AVV) und Drittlandgrundlage prüfen, Hinweistext ergänzen |
| 4 | Altersgrenze: „Lehrkraft stimmt zu“ trägt rechtlich nicht | hoch | Ab 18, oder Zustimmung nur durch Sorgeberechtigte |
| 5 | Eine Einwilligung deckt den Test und das „Training“ gemeinsam ab | hoch | Zwei Kästchen oder das Training streichen |
| 6 | Telefonwerbung ohne Dokumentationspflicht nach § 7a UWG | hoch | Kästchen für E-Mail und Telefon trennen, 5 Jahre dokumentieren |
| 7 | Werbeaussagen zu Förderung und CTFL | hoch | Keine Förderaussage vor dem Bescheid, kein „unbedingt nötig“ |
| 8 | KI-Verordnung: Kennzeichnung und KI-Kompetenz | mittel | „KI“ ausdrücklich nennen, Betreuer einweisen |
| 9 | Verzeichnis der Verarbeitungstätigkeiten (VVT) fehlt | mittel | Einträge für Anmeldung, Station und Fotos anlegen |
| 10 | Beratung über Leistungen und Zahlen | mittel | Allgemein bleiben, Zahlen gegen amtliche Quellen prüfen |

### Details

**1. Zwei Texte, sieben Widersprüche**

| Thema | Wissensbasis | Repo-Entwurf und Code |
| --- | --- | --- |
| Speicherdauer | Text bis Tagesende ([Zeile 501](testlabor-wamocon-wissensbasis.md#L501), [554](testlabor-wamocon-wissensbasis.md#L554)) | Gesprächstext bis 11.12.2026 (Variante B, [labor_speicher.py](../voice-core/labor_speicher.py)) |
| Zweck | Nur der Test, Training ausdrücklich nicht empfohlen ([602](testlabor-wamocon-wissensbasis.md#L602)) | „zu Trainingszwecken, Verbesserung von W.A.I.S.“ |
| Verantwortlich | Offen, eher WAMOCON Academy GmbH | WAMOCON GmbH |
| Datenschutzbeauftragter | Nötig ([496](testlabor-wamocon-wissensbasis.md#L496)) | „nicht bestellt“ |
| Alter | ab 18 | ab 16, Jüngere mit Zustimmung einer Aufsichtsperson |
| Websuche | abschalten ([668](testlabor-wamocon-wissensbasis.md#L668)) | im Labor erlaubt ([labor.py](../voice-core/labor.py), `WERKZEUGE_BASIS`) |
| Name | Jarvis | W.A.I.S. |

Wer einwilligt, muss wissen, worin. Wenn der Text am Stand etwas anderes zusagt, als der Code tut, ist die Einwilligung angreifbar. Am einfachsten wäre es, Variante A zu nehmen. Der Code kennt sie schon: `WAMO_LABOR_TEXT_SPEICHERN` ist standardmäßig aus, dann wird kein Text gespeichert. Damit hält die Zusage der Wissensbasis. Was Anthropic und Soniox selbst aufbewahren, hat WAMOCON aber nicht in der Hand. Zusagen wie „löschen wir am Tagesende“ deshalb nur für die eigenen Server machen.

**2. DSFA und Datenschutzbeauftragter**
- Die Wissensbasis kommt zu dem Schluss, dass eine DSFA nötig ist. Das ist vertretbar.
- Daraus folgt aber nach § 38 Abs. 1 Satz 2 BDSG: Ein Datenschutzbeauftragter muss benannt werden, egal wie viele Beschäftigte es gibt. Der Repo-Text sagt gleichzeitig „kein DSB bestellt“. Beides zusammen geht nicht.
- Variante A ändert daran nichts. Auslöser ist die KI-Interaktion selbst (DSK-Liste Nr. 11), nicht das Speichern.
- Es bleiben zwei Wege:
  - **Externen DSB benennen.** Das geht kurzfristig. Er muss vor dem 28.11. benannt und dem HBDI gemeldet sein (Art. 37 Abs. 7). Die DSFA muss vor dem ersten Besucher fertig sein.
  - **Ein Anwalt bewertet die Schwellwertanalyse anders** und hält das schriftlich fest.

Ohne eine dieser Entscheidungen sollte die Station nicht starten.

**3. Anthropic und Soniox**
- Laut [testlabor-wamo.md:23](testlabor-wamo.md#L23) läuft das Labor über „Nikos eigenen Claude-API-Schlüssel“. Ein Vertrag zur Auftragsverarbeitung muss aber zwischen WAMOCON als Verantwortlicher und Anthropic bestehen. Gehört der Schlüssel zu einem privaten Konto oder zu einer anderen Organisation, fehlt dieser Vertrag. Das muss geklärt werden.
- Der Repo-Text nennt weder die Rechtsgrundlage (Art. 13 Abs. 1 c) noch die Übermittlung in die USA mit ihrer Garantie (Art. 13 Abs. 1 f). Beides ist Pflicht.
- Soniox läuft über EU-Endpunkte ([bot.py:271](../voice-core/bot.py#L271)). Wo das Unternehmen seinen Sitz hat, ist damit noch nicht geklärt.
- Ist die Websuche an, gehen Suchanfragen an einen weiteren Empfänger. Das spricht für die Empfehlung der Wissensbasis, die Suche abzuschalten. Dann kann Karte W2 allerdings nicht mehr nachsuchen.

**4. Alter.** Der Repo-Text beruft sich auf Art. 8 DSGVO. Der gilt nur für Online-Dienste, die einem Kind direkt angeboten werden. Eine Lehrkraft ist außerdem keine gesetzliche Vertretung. Zielgruppe sind Erwachsene. Deshalb ist „ab 18, Jüngere schauen zu“ (Wissensbasis) der sauberere Weg.

**5. Zweck „Training“.** Für mehrere Zwecke braucht es getrennte Einwilligungen. Außerdem klingt „Training“ nach Modelltraining. Vorschlag: Im Text steht nur die Auswertung bis zum Löschdatum. Wer die Gespräche länger zur Verbesserung behalten will, braucht ein zweites Kästchen.

**6. § 7a UWG.** Das Formular in Abschnitt 14 erlaubt einen Anruf. Für Telefonwerbung bei Verbrauchern muss die Einwilligung dokumentiert und 5 Jahre aufbewahrt werden. Das passt nicht zu „6 Monate“, denn der Nachweis ist von den Beratungsdaten zu trennen. Besser getrennte Kästchen für E-Mail und Telefon. Als Beleg für „nichts vorankreuzen“ ist das EuGH-Urteil Planet49 (C-673/17) stärker als das LG-Urteil.

**7. Werbeaussagen**
- Vor dem Bescheid der Maßnahme darf keine Aussage wie „förderfähig“ oder „mit Bildungsgutschein“ erscheinen, sonst droht Irreführung (§ 5 UWG). Die Sperre aus der Word-Fassung ist richtig.
- Die Formulierung „Man braucht unbedingt CTFL, um KI zu testen“ eignet sich nicht für Werbung. Das stimmt sachlich nicht, und die Wissensbasis schließt Angstbotschaften selbst aus.
- Genauer wäre: Die CTFL ist die Grundlage für bewusstes Testen. Für KI gibt es bei ISTQB darauf aufbauend den Certified Tester AI Testing (CT-AI). Das ist sogar ein gutes Verkaufsargument.
- Noch zu klären: Ist die Academy beim GTB als ISTQB-Trainingsanbieter akkreditiert? Ohne Akkreditierung ist die Nutzung des Namens heikel.

**8. KI-Verordnung**
- Art. 50 Abs. 1 gilt seit 02.08.2026. Der Repo-Text sagt nur „Sprachassistent“ und sollte ausdrücklich „KI-System“ sagen.
- Art. 4 (KI-Kompetenz) gilt schon seit 02.02.2025. Die Betreuer an der Station brauchen eine kurze, dokumentierte Einweisung.
- W.A.I.S. darf am Tag nicht zur Einschätzung genutzt werden, ob jemand für den Kurs geeignet ist. Das würde in Richtung Hochrisiko (Anhang III Nr. 3) gehen.

**9. VVT.** Für Anmeldung, Einwilligungen, Station, Beratung und Fotos fehlen Einträge nach Art. 30. Dafür reicht eine Tabelle.

**10. Beratung.**
- Allgemeines zum Bildungsgutschein ist unproblematisch. Eine Einschätzung im Einzelfall wie „du bekommst ihn“ oder „dein ALG läuft so lange“ ist es nicht. Die gehört zur Agentur.
- Diese Zahlen vor der Gruppeninfo gegen Merkblatt 6 prüfen:
  - Fahrkosten 588 €
  - mindestens 90 Tage ALG
  - Zuständigkeit bei Kunden des Jobcenters

### Was in der Wissensbasis stimmt

- Getrennte Kästchen, nichts vorangekreuzt, kein Zwang zur Einwilligung, Widerruf.
- Die 72-Stunden-Frist läuft auch am Wochenende (Samstag 11 Uhr bis Dienstag 11 Uhr), zuständig ist der HBDI.
- Die Kriterien aus WP 248, keine biometrische Erkennung, keine Emotionsauswertung.
- Keine Frage nach Arbeitslosigkeit im Formular.

Der Code setzt vieles davon schon um: Mails gehen nur an `labor.test`, Freigaben nur per Klick, im Labor gibt es weder Stimmabdruck noch Gedächtnis, und eine Löschliste deckt alle Speicherorte ab.

### Nicht geprüft

- Ob Anthropic unter dem Data Privacy Framework zertifiziert ist.
- Wo Soniox seinen Sitz hat.
- Das Urteil des LG Nürnberg-Fürth und die Nummerierung der DSK-Muss-Liste.
- Die Beträge zum Bildungsgutschein.

## 3. To-Do-Liste für einen rechtlich sicheren Weg

Die Entscheidungen vom 17.11. erledigen schon einige Risiken:
- **Datenschutzbeauftragter:** Ihr habt einen internen DSB, damit ist § 38 BDSG erfüllt.
- **Lokales Modell:** Die Übermittlung an Anthropic in die USA fällt weg.
- **Variante A, ab 18, Websuche aus:** Datenschutztext und DSFA werden deutlich einfacher.
- **AZAV und GTB:** Mit Zulassung und Akkreditierung ist Werbung mit Förderung und dem Namen ISTQB möglich.

Die Liste ist nach Fristen bis zum 28.11. geordnet. Bei Punkten mit **[prüfen]** ist die Rechtslage nicht sicher. Die klärt der DSB oder ein Anwalt. Das hier ist kein Rechtsrat.

### Bis Mittwoch, 18.11.: Entscheidungen

- [ ] **Sprache festlegen: im Haus oder Soniox.** Davon hängen der Datenschutztext und ein Vertrag ab. Empfehlung: im Haus, wenn ein Probelauf Karte G3 besteht (Antwort in höchstens 3 Sekunden). *(Technik, Geschäftsführung)*
- [ ] **Rollen nach Art. 26 verteilen.** Wer ist die Anlaufstelle für Besucher? Wer meldet eine Datenpanne an den HBDI? *(Geschäftsführung beider GmbH)*
- [ ] **Name W.A.I.S. in allen Unterlagen.** Der Name „Jarvis“ wird nicht mehr verwendet.

### Bis Freitag, 20.11.: Datenschutz-Grundlagen

- [ ] **Benennung des DSB prüfen.**
  - Gilt sie für beide GmbH, und ist sie dem HBDI gemeldet (Art. 37 Abs. 7)?
  - Eine Person darf DSB für beide sein.
  - Kein Interessenkonflikt: Der DSB darf weder Geschäftsführer noch IT-Leitung sein. *(Geschäftsführung)*
- [ ] **Schwellwertanalyse mit dem DSB.** Falls nötig, eine kurze DSFA. Mit lokalem Modell, ohne Speichern und ab 18 fällt sie wahrscheinlich klein aus. Ergebnis schriftlich festhalten. *(DSB)*
- [ ] **Vereinbarung über gemeinsame Verantwortung (Art. 26).** Zwischen GmbH und Academy. Das Wesentliche daraus muss für Besucher einsehbar sein. *(Geschäftsführung, DSB)*
- [ ] **Einträge im Verarbeitungsverzeichnis (Art. 30).** In beiden Firmen für Teststation, Anmeldung und Beratung, Einwilligungsnachweise und Fotos. *(DSB)*
- [ ] **Nur falls Soniox bleibt:** Vertrag zur Auftragsverarbeitung abschließen. Sitz von Soniox und Grundlage für eine Übermittlung ins Ausland prüfen **[prüfen]**.

### Bis Dienstag, 24.11.: Technik passend zum Text

- [ ] **Labor auf das lokale Modell umstellen.** Heute nutzt die Quelle `labor` Claude Haiku (Entscheidung E8). Danach darf das Labor Anthropic nicht mehr erreichen, auch nicht als Rückfall. *(Technik)*
- [ ] **LiteLLM prüfen.** Speichert es für den Schlüssel des Labors Inhalte von Anfragen in Protokollen? Wenn ja, abschalten. *(Technik)*
- [ ] **Nur bei Sprache im Haus:** Die Sperre in `sprach_wahl(zugang, labor=True)` aufheben und den Rückfall auf Soniox im Labor ausschalten. Sonst stimmt die Zusage „nichts verlässt das Haus“ nicht.
- [ ] **Websuche aus der Werkzeugliste des Labors nehmen** ([labor.py](../voice-core/labor.py)).
- [ ] **`WAMO_LABOR_TEXT_SPEICHERN` muss aus sein.** In der Umgebung des Kerns nachsehen.
- [ ] **Restdaten klären.** Variante A speichert keinen Gesprächstext. Inhalte der Besucher landen aber trotzdem hier:
  - Tickets im Test-Jira (der Labor-Dienst bewahrt sie bis 11.12. auf)
  - Canvas-Elemente
  - Aktionen und bestätigte Laborpost
  - Protokolle

  Entweder alles am Abend des 28.11. mit dem Löschlauf löschen, oder die Frist im Datenschutztext nennen. Empfehlung: am Abend löschen. Dann stimmt „am Tagesende gelöscht“.
- [ ] **Alle 17 Karten mit dem lokalen Modell neu durchspielen.** Vor allem S1 (die Freigabekarte erscheint) und J1 bis J3. Die Karten W2 und W3 auf „sagt, dass es das nicht weiß“ umschreiben.

### Bis Mittwoch, 25.11.: Texte und Formulare

- [ ] **Ein gemeinsamer Datenschutztext für die Station.** Er ersetzt den Repo-Entwurf. *(DSB)*
  - **Rein:** beide Verantwortlichen und die Anlaufstelle, Kontakt des DSB, Zweck (nur der Betrieb der Teststation), Rechtsgrundlage, Empfänger (keine oder Soniox), Löschung, Rechte mit Widerruf, Beschwerde beim HBDI.
  - **Raus:** „Training“, „kein DSB bestellt“, die Regel ab 16.
- [ ] **KI-Hinweis am Platz (Art. 50 Abs. 1 KI-VO).** Zum Beispiel: „Du sprichst mit einem KI-System.“
- [ ] **Kennzeichnung der synthetischen Stimme (Art. 50 Abs. 2) [prüfen].** Wenn ihr die Stimme selbst betreibt, seid ihr eher Anbieter. Ob die Pflicht am 28.11. schon gilt, klären.
- [ ] **Anmeldeformular mit drei getrennten Kästchen:** Beratung per E-Mail, Beratung per Telefon, Fotos für Social Media. Nichts vorangekreuzt. Das Feld „Interesse an Förderung“ nur behalten, wenn es einen festen Zweck hat.
- [ ] **Telefon-Einwilligung dokumentieren (§ 7a UWG).** Nachweis 5 Jahre aufbewahren, getrennt von den Beratungsdaten (6 Monate). Das Formular im Original oder als Scan ablegen.
- [ ] **E-Mail per Bestätigungsmail prüfen (Double-Opt-in),** bevor Werbung verschickt wird.
- [ ] **Förderung richtig bewerben.**
  - „Förderfähig mit Bildungsgutschein“ ist erlaubt. Die Maßnahmenummer bereithalten.
  - Keine Zusage im Einzelfall. Richtig ist: „Ob du einen Gutschein bekommst, entscheidet die Agentur.“
  - 588 €, 160 € und 90 Tage gegen das aktuelle Merkblatt prüfen.
- [ ] **Die Botschaft zur CTFL umformulieren.** Statt „Man braucht unbedingt CTFL“ etwa so: „Mit der CTFL testest du KI bewusst. Du weißt, was du wann und wie prüfst. Für KI-Systeme baut der Certified Tester AI Testing (CT-AI) darauf auf.“
- [ ] **Name und Logo von ISTQB nach den Vorgaben des GTB nutzen.** „Akkreditiert“ nur für das akkreditierte Seminar schreiben.
- [ ] **FernUSG für den Kurs prüfen lassen [prüfen].** Er läuft teils online. Nach BGH III ZR 109/24 kann schon ein Online-Anteil mit Fragemöglichkeit als Fernunterricht gelten. Ohne ZFU-Zulassung wäre der Vertrag nichtig. Muss vor dem ersten Vertragsabschluss am 28.11. geklärt sein. *(Academy, Anwalt)*
- [ ] **Onepager und Karten anpassen:** „Du“ und „W.A.I.S.“. Den Satz „Ihre Sprache wird an KI-Dienste übertragen“ an die Entscheidung zur Sprache anpassen.

### Bis Donnerstag, 26.11.: Generalprobe und Einweisung

- [ ] **Generalprobe an allen vier Plätzen.** Prüfen, dass kein Platz Anthropic, die Websuche oder Soniox (falls abgewählt) erreichen kann.
- [ ] **Einweisung der Betreuer (Art. 4 KI-VO),** mit Teilnehmerliste.
  - Was W.A.I.S. kann und was nicht.
  - Keine Einschätzung, ob jemand für den Kurs geeignet ist (Anhang III Nr. 3).
  - Keine Beratung zu Leistungen der Agentur im Einzelfall.
  - Was bei einer Datenpanne zu tun ist.
- [ ] **Fotografen einweisen.**
  - Erkennbar nur Personen mit Einwilligung zeigen.
  - Keine Bildschirme mit Eingaben fotografieren.
  - Personen mit Aufkleber „Bitte nicht fotografieren“ auslassen.
- [ ] **Meldeweg für Datenpannen.** Wer ist am Samstag erreichbar? Die 72-Stunden-Frist läuft bis Dienstag, 01.12.

### Am 28.11.

- [ ] Am Eingang: Aushang zu Fotos und KI-Station. Aufkleber „Bitte nicht fotografieren“ bereitlegen.
- [ ] Am Platz: Datenschutzhinweis und Einwilligung auf dem Tablet. Das Alter mündlich prüfen, nicht aufschreiben.
- [ ] Nur die Daten von den Karten und Fantasienamen verwenden.
- [ ] Abends: Löschlauf ausführen und ein Protokoll abzeichnen.

### Nach dem Tag

- [ ] Löschnachweis ablegen.
- [ ] Fotos erst posten, wenn die Einwilligungen abgeglichen sind. Bei Widerruf den Beitrag entfernen.
- [ ] Unternehmensseite auf Social Media: gemeinsame Verantwortung mit dem Plattformbetreiber prüfen **[prüfen]**.

## 4. Abgleich mit dem Konzept vom 05.11.2026 und Fassung 2 des Kartensatzes

Grundlage: die alte Word-Fassung „Testlabor WAMOCON, Konzept, Ausgangslage und Einwilligung“ vom 05.11.2026 (nicht im Repo). Ergebnis ist Fassung 2 von [labor-kartensatz.html](labor-kartensatz.html).

### Alte Fassung (05.11.) und aktueller Stand

| Thema | Konzept vom 05.11. | Stand heute | Im Kartensatz |
| --- | --- | --- | --- |
| Welche KI | WAMOCON-Assistent und Diti, W.A.I.S. bewusst gestrichen | W.A.I.S. im Mittelpunkt (Chef, 10.11.), Labor-Modus im Code fertig | W.A.I.S. bleibt, Assistent und Diti nicht übernommen |
| Förderfragen | Laufen an keiner Station über eine KI | Im Kartensatz nicht geregelt | Als feste Regel am Platz |
| Didaktik | Erst ein eigener Fund, dann der eigene Bericht und Rückmeldung, Lob nur für echte Funde | 17 Karten ohne Reihenfolge, „Fehler erwartet“ für alle sichtbar | Pfade, Betreuerblatt, Abschluss mit Bericht |
| Ablauf | Offene Stationen ohne Zeitfenster | Slots von 30 Minuten, Pfade Grün und Blau | Pfade passend zu den Slots |

### Änderungen im Kartensatz

**Didaktisch**
- **„Fehler erwartet“ steht nur noch auf dem Betreuerblatt.** Bisher hat die Teilnehmerkarte die Lösung verraten.
- **Zwei Pfade statt 17 Karten.** In 30 Minuten schafft eine Person 4 bis 5 Karten.
  - **Grün:** W1, A2, J1, S1. Erst den Ablauf lernen, dann der erste eigene Fund.
  - **Blau:** W3, A3, J3, M1, M2 und ein eigener Testfall. Darin legt der Besucher das erwartete Ergebnis vor dem Test fest.
  - Die übrigen Karten sind Zusatz für Schnelle.
- **Klare Erklärung:** „Bestanden: nein“ heißt, du hast einen Fehler gefunden.
- **Abschluss:** „Wais, mach einen Testbericht“, dazu ein Fehlerbericht von Hand zum Mitnehmen.
- **Messen statt schätzen** bei G1 und G3.

**Fachlich**
- **CTFL-Bezug je Karte.** Jeder Use-Case hat ein Kapitel aus CTFL 4.0. Das Betreuerblatt nennt für jede Karte einen Begriff für die Rückmeldung.
- **„Was die KI anders macht“** steht bei jedem Use-Case. Das ist der Bogen zum CT-AI.
- **A1 zweimal sagen.** So erlebt der Besucher, dass eine KI nicht immer gleich antwortet.
- **M1:** „kommenden Freitag“ statt „nächsten Freitag“, denn das erwartete Ergebnis muss eindeutig sein. Am 28.11. ist das der 04.12.2026.

**Rechtlich**
- **W3:** Statt eines erfundenen Preises für WAMOCON fragt die Karte jetzt nach einem erfundenen Glossarbegriff. So entsteht vor Publikum keine falsche Aussage über das eigene Unternehmen.
- **M2:** `info@example.com` statt `kunde-beispiel.de`. Die Domäne ist für Beispiele reserviert und gehört niemandem.
- **S2:** Die zweite Stimme kommt nur vom Team, nie von einem anderen Besucher.
- **Regeln am Platz:** ab 18, Einwilligung am Tablet, Hinweis „KI-System“, keine Förderfragen an W.A.I.S., keine Eignungsbewertung, keine Fotos vom Bildschirm.
- **U1 ohne Websuche,** wie am 17.11. entschieden.

Die Kennungen W1 bis G3 sind gleich geblieben.

### Geprüft

Am Bildschirm sind alle Tabellen gerendert und angesehen. Sie bleiben im Seitenrand. Im Druck sind es jetzt 14 Seiten statt vorher 9, weil die Abschnitte nicht über Seiten hinweg umbrechen und das Betreuerblatt auf einer eigenen Seite beginnt. Die Druckseiten sind noch nicht einzeln angesehen.

### Noch offen

1. **Eval und Kartensatz passen nicht mehr zusammen.** In [faelle_labor.py](../voice-core/eval/faelle_labor.py) stehen bei W3, M1 und M2 noch die alten Sätze. Die Werte von M1 hängen an einer festen Testuhr. Vor Messrunde 1 am 19.11. muss die Eval angepasst werden, sonst misst sie andere Karten.
2. **Regel für W.A.I.S. selbst.** Die Regel zu Förderfragen fehlt noch in [persona-zusatz.md](../infra/sokrates2/labor-daten/persona-zusatz.md). Vorschlag: „Fragen zu Kurs, Preis, Förderung oder Bildungsgutschein beantwortest du nicht, sondern verweist auf das Team vor Ort.“ Die Datei darf höchstens 2000 Zeichen haben.
3. **Websuche abschalten** ist eine Codeänderung in [labor.py](../voice-core/labor.py). Die Karten gehen schon davon aus.
4. **Vom Trainer bis 19.11. zu bestätigen:**
   - die Werte für W2,
   - dass es den Begriff „Spiegel-Grenzwerttest“ nicht gibt,
   - die Kapitelangaben.
5. **„Fehler erwartet“ ist vorläufig.** Die Werte stammen aus Messungen mit Claude Haiku. Mit dem lokalen Modell gelten sie erst nach Messrunde 2.
6. **J2 [prüfen]:** Setzt der Labor-Dienst LAB-12 zwischen den Slots selbst zurück? Bis das geklärt ist, steht es als Handgriff auf dem Betreuerblatt.
7. **Onepager:** Er sagt noch „Sie“ und „Jarvis“, und seine Use-Case-Tabelle passt nicht mehr zu den Karten.
