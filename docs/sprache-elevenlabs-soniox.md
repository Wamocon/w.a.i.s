# Sprache: Soniox oder ElevenLabs? Kosten, Eignung und Empfehlung

**Stand:** 15.11.2026, Recherche auf `main` (e01dd14). Anlass ist Nikos Frage vom 15.11.2026: "Wegen SONIOX: Wir haben Elevenlabs ein Firmenkonto mit 131.000 Tokens Limit! Mache eine Analyse ob wir umsteigen können und ob Elevenlabs vom Preis gleich ist wie SONIOX oder müssen wir bei Elevenlabs mehr zahlen?"

Das Papier ist reine Recherche. Am Code, an den Diensten und an den Konten wurde nichts geändert, es wurde kein Schlüssel gelesen und kein Testaufruf mit einem Firmenschlüssel gemacht. Alle Preise sind in US-Dollar ohne Steuern angegeben und wurden am 15.11.2026 von den Preisseiten der Anbieter abgerufen. Gemessene Werte stehen mit Quelle im Text, Schätzungen sind als solche gekennzeichnet.

## Kurzfassung

- **Preis:** ElevenLabs kostet in jedem Szenario etwa das Dreifache von Soniox. Bei der Spracherkennung ist es etwa das 2,5-Fache (mit Fachbegriffen), bei der Sprachausgabe etwa das 3,4-Fache, und das schon mit dem günstigsten Modell Flash.
- **Kontingent:** 131.000 Credits gehören zu keinem Tarif genau. Am nächsten liegt Creator (22 USD im Monat, 121.000 Credits, ungenutzte Credits bleiben bis zu zwei Monate erhalten). Das Kontingent reicht höchstens für den heutigen Betrieb, in dem praktisch nur Niko spricht. Für 8 Personen reicht es nicht und nicht einmal für den Labortag allein.
- **Technik:** Ein Umstieg ist machbar, denn Pipecat 1.12 bringt beide Dienste mit. Die Sprechertrennung fiele aber weg, die Füllwörter müssten neu aufgenommen werden, und die Unterbrechungslogik ist auf Soniox eingestellt. Latenz und deutsche Erkennung müssten neu gemessen werden. Der mögliche Latenzgewinn liegt nach Herstellerangaben bei höchstens 50 bis 100 ms, die Antwortzeit insgesamt liegt bei etwa 1,7 s.
- **Datenschutz:** Soniox verarbeitet und speichert in der EU, speichert Echtzeit-Audio nicht und trainiert nie mit Kundendaten. ElevenLabs speichert ohne Enterprise-Vertrag in den USA. Zero Retention und EU-Datenresidenz gibt es dort nur mit Enterprise, und das Training mit Kundendaten muss man selbst abwählen.
- **Empfehlung:** Nicht umsteigen, Soniox bleibt für Hören und Stimme. Erst nach dem Testlabor lohnt sich die Frage, ob die Stimme (nur TTS) über ElevenLabs als wählbare Option hinter einem Schalter kommt. Das setzt voraus, dass eine Hörprobe klar besser ausfällt und die Mehrkosten gewollt sind. Vor dem 28.11. ändert sich nichts am Kern.

## 1. Ausgangslage

| Baustein | Heute | Stelle im Code |
| --- | --- | --- |
| Hören (STT) | Soniox in Echtzeit über WebSocket, EU-Endpunkt `stt-rt.eu.soniox.com`, nur Deutsch (strikt), Fachbegriffe als Kontext (`SONIOX_TERMS`), Sprechertrennung an | `voice-core/bot.py` (`soniox_stt`) |
| Stimme (TTS) | Soniox in Echtzeit über WebSocket, `tts-rt.eu.soniox.com`, Stimme über `SONIOX_VOICE`; der Strom öffnet erst mit dem ersten Text, der Start erfolgt ab 68 Zeichen | `voice-core/soniox_tts.py` |
| Füllwörter | vorab mit der Soniox-Stimme aufgenommen | `voice-core/fuellwoerter.py`, `voice-core/bot.py` (Zeile 960) |
| Aussprache | Ersetzung vor der Stimme ("Ways", "Weh Ej, Ei Es") | `voice-core/aussprache.py` |
| Wahl je Profil | `soniox` oder `haus` (`haus` fällt heute auf Soniox zurück) | `voice-core/sprache_anbieter.py`, `voice-core/modellzugang.py`, `supabase/migrations/0010_modellzugang.sql` |
| Sprechertrennung | die Sprecher-Kennung je Wort färbt Kern und Stimmlinie | `voice-core/audio_monitor.py` (`SpeakerTracker`) |

Zu den Konten: Soniox läuft in der Region EU, Vertragspartner ist Soniox Inc. (USA). Das Konto ist noch nicht auf die GmbH umgestellt, die AVV ist in Arbeit. Bei ElevenLabs gibt es ein Firmenkonto mit "131.000 Tokens"; ElevenLabs nennt diese Einheit Credits. Welcher Tarif dahintersteht, ist nicht bekannt (siehe Abschnitt 2.3).

## 2. Preise

### 2.1 Soniox

Quelle: [soniox.com/pricing](https://soniox.com/pricing), der Rechner ist mit "Updated June 2026" bezeichnet.

| Leistung | Preis |
| --- | --- |
| STT in Echtzeit | etwa 0,12 USD je Stunde (Audio-Eingang 2,00 USD je 1 Mio. Token, Text 4,00 USD je 1 Mio. Token). Abgerechnet wird die "Duration of audio or streaming session". Sprechertrennung, Spracherkennung und Formatierung sind ohne Aufpreis enthalten |
| STT für Dateien | etwa 0,10 USD je Stunde |
| TTS in Echtzeit | etwa 0,70 USD je Stunde erzeugter Sprache (Text-Eingang 4,00 USD je 1 Mio. Token bei etwa 0,3 Token je Zeichen; Audio-Ausgang 21,50 USD je 1 Mio. Token bei etwa 30.000 Token je Stunde) |

Soniox rechnet nach Verbrauch ab und kennt keine Grundgebühr. Auf Zeichen umgerechnet kostet die Stimme etwa 11,70 USD je 1 Mio. Zeichen. Dabei sind 1.000 Zeichen je Minute Sprache angenommen, die gleiche Annahme, mit der ElevenLabs Credits in Minuten umrechnet. Spricht die Stimme langsamer (800 Zeichen je Minute), sind es etwa 14,60 USD.

### 2.2 ElevenLabs

Quelle für die API: [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api). Die Seite sagt ausdrücklich: "API usage is billed in US dollars, not credits."

| Leistung | Preis |
| --- | --- |
| TTS Flash oder Turbo (Standard in Pipecat: `eleven_flash_v2_5`) | 0,04 USD je 1.000 Zeichen |
| TTS Multilingual v2 und v3 | 0,08 USD je 1.000 Zeichen |
| STT Scribe v2 Realtime (gleiche Zeile wie Scribe v3 Live) | 0,22 USD je Stunde, mit Fachbegriffen ("keyterm prompting") 0,08 USD je Stunde mehr |
| STT Scribe v2 für Dateien | 0,20 USD je Stunde, mit Fachbegriffen 0,05 USD je Stunde mehr |

Ältere Fassungen dieser Seite und Drittquellen nennen für Scribe v2 Realtime 0,39 USD je Stunde und für Flash 0,05 USD je 1.000 Zeichen, so etwa der Pipecat-Vergleich von Soniox aus dem August 2026. Die Rechnung unten nimmt die heutigen, niedrigeren Preise. Mit den alten Preisen fiele ElevenLabs noch teurer aus.

Tarife laut [elevenlabs.io/pricing](https://elevenlabs.io/pricing), dazu die über die API enthaltene Menge laut API-Preisseite:

| Tarif | je Monat | Credits | über die API enthalten (Flash-Zeichen oder Stunden Realtime-STT) | gleichzeitig Flash / Realtime-STT |
| --- | --- | --- | --- | --- |
| Starter | 6 USD | 30.000 | 150.000 Zeichen oder 27 h | 6 / 9 |
| Creator | 22 USD | 121.000 | 550.000 Zeichen oder 100 h | 10 / 15 |
| Pro | 99 USD | 600.000 | 2.475.000 Zeichen oder 450 h | 20 / 30 |
| Scale | 299 USD | 1.800.000 | 7.475.000 Zeichen oder 1.359 h | 30 / 45 |
| Business | 990 USD | 6.000.000 | 24.750.000 Zeichen oder 4.500 h | 30 / 45 |

Die enthaltene Menge ist ein einziges Budget: Hören und Stimme zehren vom selben Topf, das "oder" in der Tabelle ist wörtlich gemeint. Die Grenzen für gleichzeitige Verbindungen stammen aus der Modell-Dokumentation ([elevenlabs.io/docs/overview/models](https://elevenlabs.io/docs/overview/models)). Creator trägt 8 Laborplätze, aber nicht sicher 8 Laborplätze und das Büro gleichzeitig.

Weitere Regeln:

- Ungenutzte Credits bleiben bis zu zwei Monate erhalten, höchstens bis zum Doppelten des Monatskontingents (FAQ auf der Preisseite).
- Ist das Kontingent aufgebraucht, gilt nur noch vorausbezahltes Guthaben (Aufladung ab 5 USD). Laut [Pay-as-you-go-Dokumentation](https://elevenlabs.io/docs/overview/administration/pay-as-you-go) bekommen neue Self-Serve-Kunden keine nutzungsbasierte Nachberechnung mehr, und bei leerem Guthaben "your service will pause immediately". Für W.A.I.S. hieße das: Ohne automatische Aufladung verstummt die Stimme mitten am Tag.

### 2.3 Was 131.000 Credits bedeuten

Der Wert 131.000 passt zu keinem Tarif. Am wahrscheinlichsten ist Creator (121.000) mit übertragenen Restcredits. Sicher klärt das nur ein Blick in das Konto. Die Quellen widersprechen sich außerdem darin, wie Credits und API-Nutzung zusammenhängen. Daher gibt es zwei Lesarten:

| | Lesart A: Dollarwert laut API-Preisseite | Lesart B: Credit-Sätze laut FAQ |
| --- | --- | --- |
| Grundlage | Creator: 22 USD entsprechen 121.000 Credits, 131.000 Credits also etwa 23,80 USD | Flash 0,5 Credit je Zeichen über die API (Hilfe-Center), STT 330 Credits je Minute (Preis-FAQ) |
| nur Stimme (Flash) | etwa 595.000 Zeichen, rund 10 Stunden Sprache | 262.000 Zeichen, rund 4,4 Stunden Sprache |
| nur Hören (Realtime) | etwa 108 Stunden, mit Fachbegriffen etwa 79 Stunden | etwa 6,6 Stunden |

Lesart A ist für die API die wahrscheinlichere, denn die API-Seite rechnet ausdrücklich in Dollar und nennt je Tarif die enthaltenen Mengen. Die 330 Credits je Minute gelten laut Drittquellen für die Web-App. Unabhängig von der Lesart teilen sich Hören und Stimme ein Kontingent.

## 3. Verbrauch von W.A.I.S. (gemessen)

Grundlage sind lesende Abfragen in der Datenbank des Kerns (Schema `wamo_dev`). Ausgewertet wurden nur Zählungen und Summen, keine Inhalte und keine Profilkennungen. Der Zeitraum reicht vom 20.10. bis 15.11.2026, also 27 Tage. Dazu kommen die Latenzzeilen im Journal des Kerns (`LATENZ_JSON`, 03.11. bis 15.11.2026).

| Größe | Wert |
| --- | --- |
| Sitzungen | 244 (241 beendet), 6 Profile, 29 Personentage |
| Sitzungsdauer gesamt | 1.185 Minuten (je Sitzung höchstens 180 Minuten gezählt), Median je Sitzung 2,1 Minuten, p90 5,0 Minuten |
| Züge | 1.901 der Person, 2.199 von W.A.I.S. (438 davon unterbrochen) |
| gesprochene Zeichen von W.A.I.S. | 233.220 (im Mittel 106 je Antwort) |
| erkannte Zeichen der Person | 92.259 |

Je Personentag:

| | Mittel | p90 | Maximum |
| --- | --- | --- | --- |
| Sitzungsminuten (Grundlage für STT) | 22,3 (Median 6,9) | 61,4 | 127,1 |
| Zeichen der Stimme (Grundlage für TTS) | 8.042 | 14.788 | 69.770 |
| Züge der Person | 65,6 | | |

Annahmen:

1. Beide Anbieter berechnen beim Hören die Dauer des Audiostroms, nicht nur die Sprechzeit. Soniox schreibt "Duration of audio or streaming session", ElevenLabs "billed per audio minute". Pipecat schickt das Mikrofon während der ganzen Sitzung. Daher gilt: Minuten Hören entsprechen den Sitzungsminuten.
2. Für die Stimme speichert der Kern bei Antworten nur das tatsächlich Gesprochene (Spalte `content`, Migration 0001). Antworten aus reinen Textsitzungen zählen mit, die Summe ist deshalb eher eine Obergrenze. Die Füllwörter liegen vorab aufgenommen im Speicher und fallen kaum ins Gewicht.
3. 29 Personentage in 27 Tagen heißt: Praktisch hat eine Person je Tag gesprochen, also Niko einschließlich der Tests.
4. Daraus ergeben sich rund 360 Zeichen Stimme je Sitzungsminute (8.042 / 22,3).

## 4. Szenarien und Kosten je Monat

| Szenario | Annahme | Hören | Stimme |
| --- | --- | --- | --- |
| S1 heute (praktisch nur Niko) | Messung auf 30 Tage hochgerechnet | 21,9 h | 259.000 Zeichen |
| S2 8 Personen normal | 21 Arbeitstage, je Person und Tag der Mittelwert (22,3 min, 8.042 Zeichen) | 62,4 h | 1,35 Mio. Zeichen |
| S3 8 Personen intensiv | wie S2, aber jeder Tag wie der p90-Tag (61,4 min, 14.788 Zeichen) | 171,9 h | 2,48 Mio. Zeichen |
| S4 Labortag 28.11. (ein Tag, Obergrenze) | 8 Plätze 6 Stunden verbunden, 360 Zeichen je Minute | 48 h | 1,04 Mio. Zeichen |

Gerechnet wird mit diesen Preisen: Soniox 0,12 USD je Stunde Hören und 0,70 USD je Stunde Stimme (1.000 Zeichen je Minute). ElevenLabs 0,30 USD je Stunde Hören (0,22 USD Realtime plus 0,08 USD Fachbegriffe, denn W.A.I.S. nutzt Fachbegriffe) und 0,04 USD je 1.000 Zeichen Stimme (Flash).

| Szenario | Soniox STT | Soniox TTS | **Soniox gesamt** | ElevenLabs STT | ElevenLabs TTS (Flash) | **ElevenLabs gesamt** | Faktor |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S1 heute | 2,63 | 3,02 | **5,66** | 6,58 | 10,37 | **16,95** | 3,0 |
| S2 8 Personen normal | 7,49 | 15,76 | **23,26** | 18,73 | 54,04 | **72,77** | 3,1 |
| S3 8 Personen intensiv | 20,63 | 28,98 | **49,61** | 51,58 | 99,38 | **150,95** | 3,0 |
| S4 Labortag (ein Tag) | 5,76 | 12,12 | **17,88** | 14,40 | 41,54 | **55,94** | 3,1 |

Alle Beträge in USD je Monat, S4 je Tag.

So empfindlich reagiert die Rechnung auf die Annahmen:

- Multilingual v2 oder v3 statt Flash verdoppelt die Stimme bei ElevenLabs. In S2 wären es dann 108,08 statt 54,04 USD.
- Ohne Fachbegriffe kostet Hören bei ElevenLabs 0,22 USD je Stunde (S2: 13,74 USD). Am Faktor ändert das wenig.
- Mit den älteren Preisen (0,39 plus 0,08 USD je Stunde, 0,05 USD je 1.000 Zeichen) läge ElevenLabs in S2 bei 96,90 USD.
- Spricht die Soniox-Stimme langsamer (800 Zeichen je Minute), steigt Soniox in S2 auf 27,20 USD.

Ergebnis: Im Basisfall ist ElevenLabs etwa dreimal so teuer, in keiner Variante weniger als das 2,5-Fache. Am Preis liegt es also nicht: ElevenLabs ist nicht gleich teuer, sondern deutlich teurer. Bei 8 Personen kostet ElevenLabs im Monat rund 50 USD mehr (normal) bzw. rund 100 USD mehr (intensiv). Wechselt nur die Stimme, sind es rund 38 USD (normal) bzw. rund 70 USD mehr (intensiv).

## 5. Reicht das Kontingent von 131.000 Credits?

Lesart A (131.000 Credits entsprechen etwa 23,80 USD):

| Szenario | ElevenLabs-Kosten | Anteil am Kontingent | Ergebnis |
| --- | ---: | ---: | --- |
| S1 heute | 16,95 USD | 71 % | reicht |
| S2 8 Personen normal | 72,77 USD | 306 % | reicht nicht, nötig wäre Pro (99 USD) |
| S3 8 Personen intensiv | 150,95 USD | 634 % | reicht nicht, nötig wäre Pro plus etwa 50 USD Aufladung oder Scale (299 USD) |
| S4 Labortag | 55,94 USD an einem Tag | 235 % | reicht nicht einmal für den Labortag |

Lesart B (Credit-Sätze der FAQ): S1 bräuchte rund 564.000 Credits (431 %), S2 rund 1,9 Mio., S3 rund 4,6 Mio., S4 rund 1,5 Mio. Damit reicht das Kontingent in keinem Szenario.

Fazit: Das Firmenkonto deckt höchstens den heutigen Betrieb mit praktisch einer Person. Sobald 8 Personen W.A.I.S. nutzen, braucht es bei ElevenLabs mindestens Pro für 99 USD im Monat; bei Soniox kostet derselbe Verbrauch rund 23 USD. Läuft das Kontingent leer und ist keine automatische Aufladung eingerichtet, pausiert ElevenLabs den Dienst sofort (Abschnitt 2.2).

## 6. Technische Eignung

### 6.1 Was Pipecat 1.12 mitbringt

Pipecat 1.12.0 ist im Kern installiert, die Dienste liegen unter `pipecat/services/elevenlabs/`.

- **Hören:** `ElevenLabsRealtimeSTTService` verbindet über `wss://<base_url>/v1/speech-to-text/realtime`, Standardmodell `scribe_v2_realtime`. Es liefert Zwischenergebnisse (`partial_transcript` wird zu `InterimTranscriptionFrame`). Den Abschluss steuert wie heute die VAD von Pipecat (`CommitStrategy.MANUAL`); wahlweise übernimmt die VAD von ElevenLabs. Fachbegriffe gehen über `keyterms`, die Sprache ist Deutsch (`deu`), der Host lässt sich über `base_url` frei wählen.
- **Stimme:** `ElevenLabsTTSService` arbeitet über den WebSocket `multi-stream-input`, Standardmodell `eleven_flash_v2_5`, mit `auto_mode` und einem Keepalive alle 10 s. Aus dem Alignment kommen Wortzeiten. Damit funktionieren Untertitel, der Verlauf nach einer Unterbrechung und die weiche Unterbrechung über dieselben Pipecat-Wege wie heute. Bei einer Unterbrechung schließt der Dienst den Kontext (Barge-in). Der Endpunkt ist frei wählbar (`url`). Die HTTP-Variante und das Datei-STT taugen nicht für den Echtzeitpfad.
- **Paket:** Das Extra `elevenlabs` fehlt in `voice-core/pyproject.toml`.

### 6.2 Latenz

| Abschnitt | Soniox heute (gemessen, `LATENZ_JSON`, 03.11. bis 15.11.2026) | ElevenLabs (Herstellerangabe) |
| --- | --- | --- |
| Sprechende bis endgültiges Transkript | p50 229 ms, p95 280 ms (n = 265) | Scribe v2 Realtime: Median etwa 150 ms bis zum festen Transkript |
| erster Satz bis erstes Audio der Stimme | p50 172 ms, p95 382 ms (n = 262) | Flash v2.5: Median etwa 100 ms, ohne Netz und Anwendung |
| Sprechende bis erster Ton insgesamt | p50 1.683 ms, p95 13.862 ms (n = 266) | nicht vergleichbar |

Den Großteil der Antwortzeit verbraucht das Sprachmodell (Antwort der API p50 1.091 ms) samt Werkzeugen, nicht Hören oder Stimme. Selbst wenn die Herstellerangaben im Büro eintreffen, gewinnt W.A.I.S. höchstens 50 bis 100 ms. Pipecat selbst schätzt die Wartezeit bis zum endgültigen Transkript (p99) für ElevenLabs Realtime auf 0,41 s, für Soniox auf 0,35 s (`pipecat/services/stt_latency.py`). Ohne Enterprise-Vertrag sichert ElevenLabs keinen Verarbeitungsort zu, der Netzweg aus dem Büro lässt sich daher nur messen. Latenz ist kein Grund für einen Wechsel.

### 6.3 Deutsche Qualität

- **Erkennung:** Die Belege widersprechen sich. Der unabhängige Streaming-Vergleich von Artificial Analysis (01.06.2026) setzt Scribe v2 Realtime mit 3,64 % Wortfehlerrate auf Platz zwei, Soniox dagegen auf 11,9 %. Die Sprachen der Testdaten nennt der Vergleich nicht, Deutsch wird nicht gesondert ausgewiesen. Soniox nennt für Deutsch 1,25 % gegenüber 3,16 % bei ElevenLabs, das ist aber eine Herstellerangabe. Bei W.A.I.S. ist Soniox auf Deutsch eingestellt (strikt, mit Fachbegriffen) und im Alltag erprobt. Ob ElevenLabs auf Deutsch besser erkennt, zeigt nur eine eigene Messung mit unseren Aufnahmen.
- **Stimme:** Flash v2.5 spricht Deutsch (32 Sprachen). ElevenLabs bietet eine deutlich größere Stimmenauswahl als Soniox, das ist der stärkste Grund für die Stimme von ElevenLabs. Wie Zahlen, Datumsangaben und Abkürzungen klingen, ist offen. Dafür gibt es `apply_text_normalization`; ob die Einstellung "on" Latenz kostet, ist unbestätigt und gehört in die Hörprobe.

### 6.4 Aussprache

Pipecat führt die Aussprachewörterbücher von ElevenLabs seit 1.6.0 als veraltet und empfiehlt Ersetzungen auf unserer Seite, weil serverseitige Ersetzungen die Wortzeiten verschieben (`tts.py`, Zeilen 145 bis 167). Phonem-Tags lesen nur englische Modelle. Unser Weg in `aussprache.py` bleibt also richtig. Die Schreibweisen "Ways" und "Weh Ej, Ei Es" sind aber nur mit der Soniox-Stimme gehört und müssten mit jeder neuen Stimme neu geprüft werden.

### 6.5 Was wegfiele oder neu gebaut werden müsste

- **Sprechertrennung:** Scribe v2 Realtime liefert keine Sprecher-Kennung je Wort. Der `SpeakerTracker` (`audio_monitor.py`, Zeilen 200 bis 231) bekäme nichts mehr. Das führt nicht zum Absturz, aber Kern und Stimmlinie verlieren die Sprecherfarbe.
- **Füllwörter:** Sie sind mit der Soniox-Stimme aufgenommen. Die heutige Bedingung `sprache.tts.anbieter != "haus"` (`bot.py`, Zeile 960) würde in einer ElevenLabs-Sitzung Soniox-Füllwörter abspielen; man hörte dann zwei Stimmen. Nötig wäre ein eigener Aufnahmeweg oder das Abschalten der Füllwörter.
- **Startverhalten der Stimme:** `LazySonioxTTSService` und die Startschwelle von 68 Zeichen sind auf Soniox zugeschnitten. ElevenLabs bringt Keepalive und `auto_mode` mit, das Startverhalten müsste neu gemessen werden.
- **Unterbrechung:** `MIN_INTERRUPT_WORDS = 2`, `SOFT_INTERRUPT_LAG_SECS = 0,5` und die Logik für Bruchstücke in `soft_interrupt.py` sind an Soniox gemessen, zuletzt am 14.11.2026.
- **Fehlerbilder:** ElevenLabs meldet unter anderem `commit_throttled`, `insufficient_audio_activity` und `session_time_limit_exceeded`. Wie sich das bei Sitzungen bis 120 Minuten verhält, ist zu prüfen.

### 6.6 Mischbetrieb

Technisch geht jede Mischung, denn Pipecat setzt Hören und Stimme als getrennte Dienste ein. Am sinnvollsten wäre: Hören über Soniox, Stimme über ElevenLabs. Die Stimme hängt an einer einzigen Stelle der Pipeline, keine Logik baut auf ihren Tokens auf, und ein Schalter stellt sofort zurück. Der umgekehrte Weg (Hören über ElevenLabs) lohnt nur, wenn eine eigene Messung auf Deutsch klar bessere Erkennung zeigt. Am Preis ändert der Mischbetrieb wenig, denn die Stimme ist bei ElevenLabs der größte Kostenblock.

Ein Befund am Rande, unabhängig von ElevenLabs: `WAMO_STT_ANBIETER` und `WAMO_TTS_ANBIETER` stehen nicht in der Erlaubnisliste von `infra/sokrates2/wamo_core_env.py` (Zeilen 37 bis 68). Am Server lassen sie sich also heute nicht über `wamo-core-env` setzen.

## 7. Datenschutz

| Punkt | Soniox | ElevenLabs ohne Enterprise (z. B. Creator) | ElevenLabs Enterprise |
| --- | --- | --- | --- |
| Vertragspartner | Soniox Inc., USA (Konto noch nicht auf die GmbH umgestellt) | Eleven Labs Inc., New York (Bedingungen für den EWR, Stand 09.10.2026) | wie links, mit eigenem Vertrag |
| AVV/DPA | in der Console unter "Security & compliance" | DPA (Stand 08.04.2026) gilt laut Bedingungen für Firmenkunden. Übermittlung in die USA über das EU-US Data Privacy Framework und Standardvertragsklauseln | individuell |
| Ort | Region EU: Audio und Transkripte bleiben für Verarbeitung und Speicherung in der EU | Speicherung in den USA als Standard, Datenresidenz gibt es nur mit Enterprise | EU-Umgebung `api.eu.residency.elevenlabs.io`: Speicherung in der EU, die Verarbeitung kann außerhalb stattfinden. Nur in der EU verarbeitet wird nur mit Zero Retention Mode über die API |
| Speicherung | Echtzeit-Audio und Transkripte werden nur auf ausdrückliche Anforderung gespeichert (Async, Löschung nach 30 Tagen) | Verlauf standardmäßig an ("history preservation"). Gelöschtes bleibt bis zu 30 Tage in Backups, Debug- und Moderationslogs sind möglich | Zero Retention Mode wählbar (TTS-WebSocket und Endpunkte `/v1/speech-to-text/`) |
| Training mit Kundendaten | nie | erlaubt; Abwahl im Konto unter "Data use", sie wirkt nur für künftige Inhalte | Abwahl, Zero Retention |
| Nachweise | SOC 2 Type 2, ISO/IEC 27001:2022 | SOC 2 (Angabe auf der Preisseite für Enterprise) | wie links |

Für W.A.I.S. heißt das: Die Stimme bekommt den Antworttext, also Gesprächsinhalte mit Namen und Firmendaten. Beim Hören geht das Mikrofon-Audio aus dem Büro an den Anbieter. Ohne Enterprise-Vertrag lägen beide bei ElevenLabs in den USA und im Verlauf des Kontos. ElevenLabs käme zudem als neuer Auftragsverarbeiter hinzu, die AVV wäre neu abzuschließen. Für das Testlabor nennt der Datenschutzhinweis für Besucher Soniox (`docs/labor-datenschutz-entwurf.md`). Ein Wechsel bräuchte dort einen neuen Text mit neuer Versionsnummer, die Einwilligungen müssten neu erfasst werden. Beim Datenschutz liegt Soniox in unserer Konfiguration klar vorn.

## 8. Aufwand und Risiken einer Umstellung

Die Integrationsbewertung (Agent `ecc:architect`, Abschnitt 13) und die Ergänzungen aus dieser Recherche ergeben:

| Paket | Inhalt | Stunden |
| --- | --- | ---: |
| 0 Klärung (kein Code) | Tarif und Abrechnung im ElevenLabs-Konto, DPA für die GmbH, Training abwählen, Verlauf ausschalten, Anfrage Enterprise (EU, Zero Retention) | 1 bis 2 |
| 1 Messung außerhalb des Kerns | eigenes Messskript nach der Klärung: Zeit bis zum ersten Ton, Hörprobe mehrerer Stimmen, Aussprache "Ways", Zahlen; deutsche Erkennung mit eigenen Aufnahmen ohne Personenbezug | 4 bis 6 |
| A Stimme über ElevenLabs hinter `WAMO_TTS_ANBIETER` (ohne Migration) | Fabrik, Anbieterwahl, Anzeige, Füllwörter aus (eigene Aufnahme plus 3 h), Tests, Latenz p50/p95, Hörprobe | 18 bis 21 |
| B Hören über ElevenLabs hinter `WAMO_STT_ANBIETER` | Fabrik, Fachbegriffe, Sprecherfarbe aus, Unterbrechungswerte neu einstellen, Tests, Messrunde (Transkriptzeit, Fachbegriffe, Echo, Unterbrechung) | 18 bis 22 |
| C Wahl je Profil | neue Migration mit `.down.sql` (Check auf `stt` und `tts`), Zugang, Verwaltung, Oberfläche, Rollout, `database-reviewer` | rund 10 |
| Nebenarbeiten | Schalter in `wamo_core_env.py`, neuer Schlüssel in `.env.example` und in der Verteilprüfung, Extra `elevenlabs` in `pyproject.toml` mit `uv.lock`, Datenschutzhinweise | 2 bis 4 |
| **Vollumstieg (0, 1, A, B, C, Nebenarbeiten)** | | **rund 53 bis 65** |
| **nur Stimme als Option (0, 1, A, Nebenarbeiten)** | | **rund 25 bis 33** |

Risiken:

- **Kosten und Ausfall:** dreifache laufende Kosten. Ein leeres Kontingent pausiert den Dienst sofort, W.A.I.S. verstummt.
- **Datenschutz:** neuer Auftragsverarbeiter, Speicherung in den USA ohne Enterprise, Training standardmäßig erlaubt.
- **Gesprächsführung:** Unterbrechung, Innehalten und Füllwörter sind auf Soniox eingestellt. Ein Wechsel öffnet Fehler, die gerade behoben sind.
- **Erkennung:** Die deutsche Qualität ist offen, Sprechertrennung und Sprecherfarbe fallen weg.
- **Bindung:** Bei Hören und Stimme zugleich hinge der Sprachpfad an einem Konto, dessen Abrechnungsregeln sich zuletzt mehrfach geändert haben (API in Dollar statt Credits, keine Nachberechnung mehr für neue Self-Serve-Kunden, neue Preise für Scribe Realtime).

## 9. Was vor dem Testlabor nicht passieren darf

Für den Kern gilt ab dem 20.11.2026 der Freeze, das Testlabor findet am 28.11.2026 statt. Bis dahin gilt:

- Kein Wechsel des Anbieters im Kern, kein neues Pipecat-Extra, kein neuer Schlüssel in `core.env`, keine Migration an `model_access`.
- Keine Änderung an Unterbrechungswerten, VAD, Füllwörtern oder Stimme. Die Werte sind am 14.11. an Soniox eingestellt und für den Labortag die Grundlage.
- Kein Austausch des Datenschutzhinweises für Besucher. Er nennt Soniox, ein anderer Anbieter bräuchte neuen Text und eine neue AVV.
- Keine Testaufrufe mit Gesprächsinhalten über das ElevenLabs-Konto, solange DPA, Abwahl des Trainings und Verlauf nicht geklärt sind.

Erlaubt und sinnvoll vor dem 28.11.: Klärungen im ElevenLabs-Konto (Paket 0), eine Anfrage zu Enterprise und vorrangig die Umstellung des Soniox-Kontos auf die GmbH samt AVV.

## 10. Bewertung und Entscheidung

| Blick | Kernaussage |
| --- | --- |
| Zahlen | ElevenLabs kostet in jedem Szenario etwa das Dreifache. 131.000 Credits decken höchstens den heutigen Betrieb, der Latenzgewinn liegt bei höchstens 50 bis 100 ms von 1,7 s |
| Wirkung | Das vorhandene Konto wirkt wie freie Kapazität, ist es aber nicht. Es reicht nur für eine Person, und ein leeres Kontingent ließe W.A.I.S. vor Kolleginnen, Kollegen oder Besuchern verstummen. Ein Wechsel kurz vor dem Labor gefährdet die gerade eingestellte Gesprächsführung |
| Bild | Die Kostentabelle in Abschnitt 4 trägt die Entscheidung: In jeder Zeile steht rechts etwa das Dreifache von links |

**Entscheidung:** Nicht umsteigen. Soniox bleibt Standard für Hören und Stimme. Das ElevenLabs-Konto eignet sich nach dem Testlabor für Hörproben und die Messung in Paket 1. Die Option "Stimme über ElevenLabs" (Paket A, rund 25 bis 33 Stunden mit Klärung und Messung) lohnt sich erst, wenn alle drei Bedingungen erfüllt sind:

1. Eine Hörprobe zeigt eine deutlich bessere deutsche Stimme.
2. Die Mehrkosten von rund 38 bis 70 USD im Monat bei 8 Personen sind gewollt.
3. Die DPA läuft auf die GmbH, das Training ist abgewählt und der Verlauf aus, oder es gibt einen Enterprise-Vertrag.

Beim Hören bleibt Soniox, solange keine eigene Messung auf Deutsch klar bessere Erkennung durch ElevenLabs zeigt.

**Nächster Schritt:** Niko prüft im ElevenLabs-Konto den Tarif, die Abrechnung der API (Credits oder Dollar) und die Einstellung "Data use". Vorrang hat weiter die Umstellung des Soniox-Kontos auf die GmbH.

## 11. Offene Fragen an Niko

1. Welcher Tarif steckt hinter dem ElevenLabs-Konto (vermutlich Creator)? Läuft es auf die WAMOCON GmbH? Zeigt die Abrechnung die API-Nutzung in Credits oder in Dollar?
2. Ist "Data use" (Training) abgewählt und der Verlauf ausgeschaltet?
3. Gibt es außer dem Preis einen Grund für ElevenLabs, zum Beispiel eine bestimmte Stimme?
4. Sollen wir ein Angebot für Enterprise anfragen (EU-Datenresidenz, Zero Retention)? Der Preis ist dort individuell.

## 12. Quellen

Alle Quellen wurden am 15.11.2026 abgerufen.

- Soniox, Preise: <https://soniox.com/pricing>
- Soniox, Datenresidenz: <https://docs.soniox.com/data-residency>
- Soniox, Sicherheit und Datenschutz: <https://docs.soniox.com/security-and-privacy>
- Soniox, Vergleich Deutsch (Herstellerangabe): <https://soniox.com/compare-stt/soniox-vs-elevenlabs/german>
- Soniox, Benchmarks mit Pipecat (Herstellerangabe, nennt 0,39 USD je Stunde für Scribe v2 Realtime): <https://soniox.com/benchmarks>
- ElevenLabs, Tarife und FAQ (Credits, 330 Credits je Minute STT, Übertrag zwei Monate): <https://elevenlabs.io/pricing>
- ElevenLabs, API-Preise (Dollar, enthaltene Mengen je Tarif): <https://elevenlabs.io/pricing/api>
- ElevenLabs, Pay as you go (keine Nachberechnung, Pause bei leerem Guthaben): <https://elevenlabs.io/docs/overview/administration/pay-as-you-go>
- ElevenLabs, Modelle und gleichzeitige Verbindungen: <https://elevenlabs.io/docs/overview/models>
- ElevenLabs, Datenresidenz: <https://elevenlabs.io/docs/overview/administration/data-residency>
- ElevenLabs, Zero Retention Mode: <https://elevenlabs.io/docs/developers/resources/zero-retention-mode>
- ElevenLabs, DPA (Stand 08.04.2026): <https://elevenlabs.io/dpa>
- ElevenLabs, Bedingungen für den EWR (Stand 09.10.2026): <https://elevenlabs.io/terms-of-use-eu>
- ElevenLabs, Hilfe-Center zu Credits je Zeichen (Turbo v2.5: 0,5 Credit): <https://help.elevenlabs.io/hc/en-us/articles/40263026676753-How-do-credits-work-on-the-ElevenLabs-iOS-or-Android-app>
- Artificial Analysis, Streaming-Benchmark (unabhängig, 01.06.2026): <https://artificialanalysis.ai/articles/new-streaming-speech-to-text-benchmark-aa-wer-streaming>
- Drittquellen zu 330 Credits je Minute STT: <https://www.stork.ai/blog/elevenlabs-speech-to-text-scribe-2026>, <https://casrai.org/guides/elevenlabs-pricing>
- Code: Pipecat 1.12.0 im venv des Kerns (`pipecat/services/elevenlabs/stt.py`, `tts.py`, `tts_base.py`, `pipecat/services/stt_latency.py`) sowie `voice-core/` und `supabase/migrations/` auf `main` (e01dd14)

## 13. Vorgehen

- **ECC:** Verwendet wurden die Skills `deep-research`, `market-research` und `search-first`. Firecrawl und Exa sind nicht eingerichtet, daher liefen Websuche und Abruf direkt auf den Herstellerseiten. Der Agent `ecc:architect` hat die Integration bewertet (Kopplungsstellen, Pakete, Stunden, Abschnitte 6 und 8). Die tragenden Stellen wurden im Code nachgeprüft (`bot.py` Zeile 960, `wamo_core_env.py`, `stt_latency.py`).
- **REA:** nicht eingesetzt. Die relevanten Artefakte sind Python-Quellen (Pipecat im venv und eigener Code) und lassen sich direkt lesen. Eine Laufzeitsicht auf den WebSocket von ElevenLabs hätte Aufrufe mit einem Firmenschlüssel gebraucht, die ausgeschlossen waren. Die Desktop-App spielt für den Sprachpfad keine Rolle, denn das Audio läuft über WebRTC zum Kern.
- **Zahlen:** lesende Abfragen am Server, `psql` im Datenbank-Container (nur `count` und `sum(length(...))`) und das Journal des Kerns (`LATENZ_JSON`, nur Zeiten). Es wurden keine Gesprächsinhalte und keine Profilkennungen ausgegeben.
