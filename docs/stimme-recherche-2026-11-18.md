WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn

# Sprechererkennung in W.A.I.S.: Warum der Kosinus einbricht und wie ein weiches Signal brauchbar wird

Stand 18.11.2026. Arbeitsunterlage (Markdown) für den Produktinhaber. Bei Weitergabe als Dokument gilt die WMC-Vorlage (Logo, Kopf- und Fußzeile mit Seitenzahl).
Kennzeichnung jeder Aussage: **[belegt]** (Quelle oder eigene Messung), **[abgeleitet]** (Schluss aus Belegen), **[Vermutung]** (plausibel, nicht geprüft).

## Denkmodi in einem Satz je Modus

- IQ: Die Zahlen zeigen, dass unter einer Sekunde und bei Gerätewechsel auch Spitzenmodelle bei etwa 4 bis 30 % EER liegen, also ist eine harte Sperre mathematisch nicht zu halten, ein kalibriertes weiches Signal schon.
- EQ: Wer zehnmal als Fremder behandelt wird, obwohl er selbst spricht, verliert das Vertrauen in den Assistenten, deshalb zählt die Rate falscher Abweisungen mehr als die Rate falscher Annahmen.
- VQ: Ein Ampelsignal mit drei Stufen und eine Wochenkurve der Score-Verteilung je Gerät machen Drift sichtbar, ohne dass jemand Zahlen lesen muss.
- Synthese: Erst die Signalkette und das Einlernen je Mikrofon verbessern (billig, stärkste Wirkung), dann Kalibrierung und Normalisierung mit einer Kohorte, das Modell nicht wechseln.

## 1. Ergebnis in Kürze

1. Der Einbruch von 0,53 bis 0,75 auf 0,0 bis 0,35 ist mit hoher Wahrscheinlichkeit ein Wechsel der Signalkette (Mikrofon, Codec, Rauschunterdrückung, Pegel) in Verbindung mit kurzen Äußerungen, nicht reines Rauschen. Der eigene Versuch mit 15 dB Rauschabstand senkte den Mittelwert nur um etwa 0,08 [belegt, README Zeile 1171 bis 1195], der Gerätewechsel allein um 0,15 bis 0,25 [belegt, README Zeile 1195]. [abgeleitet]
2. Die Aufnahme startet ohne eigene Vorgaben für Echo, Rauschen und Verstärkung, die Browser setzen dann ihre Standardwerte (in Chrome nach einer Entwicklerquelle alle drei an). Der Kern verändert das Audio vor TitaNet nicht weiter. Ob die Browser-Aufbereitung die Abdrücke verschlechtert, ist in der Literatur nicht gemessen. Verwandte Messung: Rauschfilter wie DeepFilterNet erhöhten die EER bei Kurzäußerungen um 2,0 bis 4,9 Punkte [belegt, arXiv 2611.09516].
3. Es gibt keine Maßnahme ohne Training, die eine Lücke von 0,3 Kosinus schließt. Die belegten Hebel sind einzeln klein (Score-Normalisierung 9 bis 21 % relativ, Qualitätskalibrierung 6 bis 9 % relativ). Der große Hebel ist ein Abdruck je Mikrofon. Das stützt die Entscheidung des Produktinhabers, die Stimme nur als weiches Signal zu nutzen.
4. In der Literatur ist die Kurzäußerung der schwächste Punkt aller Modelle. Eine Modellumstellung (zum Beispiel ReDimNet) bringt bei langer, sauberer Sprache etwa 15 bis 25 % relativ, bei Kurzäußerungen und Telefonie gibt es dafür keinen Beleg.
5. Die README nennt für TitaNet "2,4 % bei 3 s auf 18,4 % bei 1 s". Diese Zahlen stehen in einer anderen Arbeit und gehören zu WavLM plus ECAPA-TDNN, nicht zu TitaNet (siehe 2.3). Das TitaNet-Paper enthält keine Messung für Kurzäußerungen oder Rauschen.

## 2. Lokale Prüfung (nur gelesen, nichts geändert)

### 2.1 Mikrofon im Browser und in der App

- `ui/node_modules/@pipecat-ai/small-webrtc-transport/dist/index.js` Zeile 1086 bis 1108: `WavRecorder.begin` ruft `getUserMedia({ audio: true })` auf, mit Gerätewahl `{ audio: { deviceId: { exact: id } } }`. Keine Vorgabe für `echoCancellation`, `noiseSuppression`, `autoGainControl`, keine Abtastrate.
- `ui/src/lib/useWamo.ts` Zeile 973 bis 983: `GeraeteMedienManager` bzw. `StillMedienManager` übergibt nur die Gerätekennung. `ui/src/lib/geraeteMedien.ts` Zeile 1 bis 30 und `stillMedien.ts` bestätigen, dass der Manager nur das Gerät wählt.
- `ui/src/lib/mikrofonTest.ts` Zeile 8: "getUserMedia ohne eigene Vorgaben: Echo- und Rauschunterdrückung und automatische Verstärkung wie beim Sprechen mit W.A.I.S." Das ist die eigene Beschreibung des Ist-Zustands.
- `desktop/main.js` Zeile 545 und 1151: Die Electron-App lädt dieselbe Oberfläche (`loadFile` für den Start, `loadURL(UI_URL)`), also derselbe Pfad. In `desktop/` gibt es keine Mikrofonvorgaben, die Schalter in Zeile 155 bis 158 betreffen nur Hintergrunddrosselung.
- Folge [abgeleitet]: Es gelten die Standardwerte des Browsers. Chrome schaltet nach einer Entwicklerquelle Echo, Rauschen und Verstärkung standardmäßig ein, belegt ist das nur sekundär (addpipe-Blog), MDN nennt keinen Standardwert. Prüfbar mit `track.getSettings()`.

### 2.2 Weg des Tons im Kern

- `voice-core/bot.py` Zeile 362 bis 365: `TransportParams(audio_in_enabled=True, audio_out_enabled=True)`, kein `audio_in_filter` (Pipecat bietet RNNoiseFilter und KrispVivaFilter an, beide ungenutzt). Keine feste `audio_in_sample_rate`.
- Pipecat 1.12, `transports/smallwebrtc/transport.py` Zeile 405 bis 436: aiortc dekodiert Opus, ein `AudioResampler` wandelt auf die Eingangsrate und Mono, danach `int16`.
- `voice-core/stimme_pruefer.py` Zeile 202 bis 210 (`on_audio`): Ring von 10 s, die Rate steht im Frame (Startwert 16000 in Zeile 130). Beim Einlernen wird nur das Audio für die Spracherkennung stumm geschaltet.
- `voice-core/stimme_modell.py` Zeile 118 bis 126 und 255 bis 258: `int16` zu `float32`, dann `sherpa_onnx` ohne eigene Vorverarbeitung. Zuschnitt in `ohne_pausen` (Zeile 282) und `pruefsegment` (Zeile 314): nur stille 20-ms-Blöcke fallen weg. Keine Entrauschung, keine Lautstärkenormierung, kein Neu-Abtasten im Kern.
- sherpa-onnx liest für TitaNet aus den Modell-Metadaten Fensterlänge und Merkmalszahl und normiert die Mel-Merkmale je Äußerung auf Mittelwert und Standardabweichung (`per_feature`), die Ausgabe wird nicht normiert (Quelltext `speaker-embedding-extractor-nemo-impl.h`). Das entspricht einer Kanalmittelwertnormierung je Äußerung. Bei 0,3 bis 1 s ist diese Schätzung ungenau und enthält Pausenanteile [abgeleitet].

### 2.3 Frühere Messungen im Repo (nicht wiederholen)

Die Messungen stehen in `README.md` (Abschnitt Stimmabdruck), nicht in `docs/`; eine Suche in `docs/` nach Stimme, TitaNet, Schwelle, Kosinus ergab nur Richtlinien und Datenschutz (`docs/ausrollen-neue-nutzer.md`, `docs/labor-datenschutz-entwurf.md` Abschnitt 4), keine Messreihen.

| Datum | Befund | Fundstelle |
|---|---|---|
| 17.11. | Über 70 % der Äußerungen des Besitzers verworfen, eigene Werte 0,35 bis 0,60 bei 0,4 bis 1,8 s, zweite Person 0,10 bis 0,30 | README 1156 |
| 17.11. | Sieben synthetische Hausstimmen: eigen Mittel 0,60 (1 s) bis 0,73 (4,5 s), mit Rauschen 15 dB unter der Sprache 0,52 bei 1 s; fremde höchstens 0,51 bis 0,53; vier ähnliche Hausstimmen 0,45 bis 0,53 | README 1171 |
| 18.11. | 154 Urteile: Bluetooth-Headset eingelernt, eingebautes Mikrofon geprüft, Pegelspitze im Median minus 27 statt minus 8 dBFS; Neu-Einlernen am selben Gerät hob die Werte um 0,15 bis 0,25 | README 1195 |
| 18.11. | Unter 1 s: eigene Werte 0,14 bis 0,49, fremde 0,10 bis 0,30, nicht trennbar | `stimme_gate.py` Zeile 84 |
| 18.11. | Schatten WeSpeaker ResNet34 mit abgeleitetem CMN-Eintrag; ohne ihn lagen fremde Stimmen bei 0,75 statt 0,17; CAM++ in sherpa-onnx 2.0.1 mit stark schwankenden Abdrücken (0,19 bei 1,5 s, 0,92 bei 2 s, 0,09 bei 2,5 s) ausgeschieden | README 1284 |

**Korrektur an der README (Zeile 1159):** "Literatur zu TitaNet-L: ... Fehlerrate steigt von 2,4 % bei 3 s auf 18,4 % bei 1 s". Diese Werte (2,393 % bei 3 s, 5,242 % bei 2 s, 18,437 % bei 1 s auf Vox1-O) stehen in arXiv 2609.25007 für die Basislinie WavLM plus ECAPA-TDNN, trainiert auf VoxCeleb2. Das TitaNet-Paper (arXiv 2110.04410) berichtet weder Kurzäußerungen noch Rauschen. Der Wert "um 0,30, empfohlen mindestens 0,33" passt zu arXiv 2611.09516 (Callcenter-Telefonie, TitaNet-Large 0,3027, Small 0,3336) und ist dort kein Wert für Laptop-Mikrofone. [belegt]

## 3. Antworten auf die Fragen

### Frage 1: Warum bricht der Kosinus bei gleichem Sprecher ein?

**Kurzäußerungen.** [belegt] Die EER steigt bei kürzerem Test stark, die Zahlen widersprechen sich aber je nach Protokoll:

| Quelle | Modell, Training | voll | 3 s | 2 s | 1 s | 0,5 s |
|---|---|---|---|---|---|---|
| arXiv 2506.14226 (2025) | ECAPA (WeSpeaker-Konfiguration), VoxCeleb1, ohne Normierung | 2,05 | k. A. | 5,39 | 12,82 | 26,83 |
| arXiv 2609.25007 (2026) | WavLM + ECAPA, VoxCeleb2 | k. A. | 2,39 | 5,24 | 18,44 | k. A. |
| arXiv 2406.07103 (2024) | ECAPA, VoxCeleb1+2, Training mit 1 bis 3 s Ausschnitten, MUSAN+RIR | 0,95 | k. A. | 1,79 | 3,94 | k. A. |

Lesart [abgeleitet]: Bei 1 s liegt die EER je nach Training zwischen etwa 4 und 18 %. Training mit kurzen Ausschnitten hilft am meisten, das haben wir bei einem fertigen Modell nicht in der Hand. TitaNet-L wurde mit Ausschnitten von 1,5, 2 und 3 s trainiert [belegt, Paper], 1,5 s ist also noch im Trainingsbereich, darunter nicht. Zwischen 1 s und 2 s halbiert bis drittelt sich die EER in allen drei Arbeiten, daher lohnt jede Sekunde Beweismaterial (der Zug in `stimme_pruefer.py` tut das bereits).

**Sub-Sekunde im Feld.** [belegt, ein Preprint] arXiv 2611.09516 (2026) misst 400 echte Callcenter-Gespräche und 11.070 Äußerungen live: Unter 1 s liegt die EER aller Modelle bei etwa 29 bis 30 % (CAM++ 28,69, TitaNet-Large 29,62, ECAPA 29,78), im Feld 30,6 bis 31,9 % für TitaNet und CAM++, ECAPA fällt auf Zufall (51 %). Grenzen: Telefonie, überwiegend männliche Hindi-Sprecher, eine Firma, Preprint. Es bestätigt dennoch, dass bei Sub-Sekunden und Kanalmischung kein Modell hart sperren kann.

**Gerät und Kanal.** Die Literatur zeigt, dass Einbettungen domänenempfindlich sind (Alam et al., Odyssey 2018; EDITnet; DEAAN) [belegt], eine isolierte Messung "Laptop gegen Headset" habe ich nicht gefunden. Physikalisch ist ein Bluetooth-Headset im Telefonprofil schmalbandig (CVSD 8 kHz, 3,4 kHz Bandbreite) oder mit mSBC bei 16 kHz und 7 kHz Bandbreite [belegt, Herstellerquellen], Opus im Schmalbandmodus verwirft zudem Energie über 4 kHz; bei sinkender Bitrate wächst die Streuung innerhalb eines Sprechers (arXiv 2509.02771, 2025) [belegt]. Zahlen zum Effekt auf Einbettungen fand ich nicht. Der Webbrowser sendet Opus meist mit 32 kbit/s oder mehr, ab 24 kbit/s ist der Opus-Effekt klein [belegt, 2509.02771], bei uns nicht gemessen.

**Rauschen.** TitaNet-L liegt unter 10 dB Rauschabstand vor ECAPA (SpeechBrain), darüber gleichauf [belegt, arXiv 2504.18950, Sprecherabruf, nicht Verifikation, Zahlen nur als Kurven]. Das TitaNet-Paper erwähnt keine Rauschaugmentierung, nur Nachhall, Tempo und SpecAugment [belegt]. Eigener Versuch: 15 dB Rauschabstand senkt den Mittelwert um etwa 0,08 [belegt]. Der beobachtete Einbruch ist viel größer, also wirkt etwas anderes mit (Kette, Pegel, Aufbereitung). [abgeleitet]

**Was am meisten hilft (belegt oder eigene Messung, nach Wirkung):**

1. Abdruck am selben Mikrofon: plus 0,15 bis 0,25 Kosinus [belegt, README 1195]. Apple nennt als Zweck der impliziten Aufnahme genau diese Umgebungsvielfalt und sagt, die ausdrückliche Aufnahme enthalte "very little environmental variability" [belegt, Apple 2018].
2. Mehr Sprache je Urteil (siehe Tabelle oben).
3. Score-Normalisierung mit passender Kohorte (Frage 2).
4. Qualitätskalibrierung nach Dauer und Rauschen (Frage 7).
5. Unbehandeltes Audio statt Entrauschung (Frage 5).
6. Modellwechsel: nur bei langer, sauberer Sprache belegt (Frage 4).

**Offene Diagnose, die heute lösbar ist [Vermutung]:** Ein 2 mal 2 Versuch (Laptop und Headset, jeweils Rauschunterdrückung und Verstärkung an und aus, zehn feste Sätze, derselbe Offline-Rechner mit TitaNet) klärt in einer Stunde, welcher Faktor den Einbruch trägt.

### Frage 2: Score-Normalisierung und Kalibrierung ohne Trainingsdaten

[belegt] Normalisierung braucht keine Trainingsdaten, nur eine Kohorte von Einbettungen.

- WeSpeaker, VoxCeleb v2 (README): ResNet34 0,867 % EER ohne, 0,787 % mit AS-Norm (minus 9 % relativ); mit Feinabstimmung 0,797 zu 0,723 (minus 9 %); mit Qualitätsfunktionen (QMF) zusätzlich 0,659 (minus 9 %). ECAPA C=1024: 0,856 zu 0,808 (minus 6 %), ResNet293 0,595 zu 0,537 (minus 10 %). Die Wirkung ist innerhalb der Domäne der Kohorte gemessen.
- ReDimNet (Interspeech 2024), Vox1-O: B0 1,16 zu 1,07, B1 0,85 zu 0,73, B4 0,51 zu 0,44, B6 0,40 zu 0,37 (minus 8 bis 14 %).
- Kohorte aus der falschen Domäne schadet: Thienpondt et al. (Interspeech 2020) mit persischen Daten: ohne Normierung 2,14 % EER, Kohorte VoxCeleb 2,46 % (schlechter), Kohorte in-domain 1,69 % (minus 21 %), top-40 adaptiv. [belegt]
- Kohortengröße ist unkritisch (in der Suche zitiert: 1000 für VoxCeleb, 50 bei Fremddaten im ECAPA-TDNN-Paper) [belegt, Suchzusammenfassung, nicht im Volltext geprüft].

Übertragung auf uns [abgeleitet]:

- Eine eigene Kohorte aus den sieben Profilen ist zu klein und verarbeitet fremde Biometrie (Datenschutz). Besser: Einbettungen aus öffentlichen deutschen Sprachdaten mit vielfältigen Mikrofonen. Kandidat: Mozilla Common Voice Deutsch, Release 25.0, 1.485 h, 20.466 Sprecher, CC0, aber die Nutzungsbedingungen verbieten nach der Datenseite, Sprecher zu identifizieren und die Daten weiterzugeben. Eine Rechtsprüfung ist nötig, bevor daraus abgeleitete Einbettungen im Repo liegen. [belegt, Datenseite]
- Erwarteter Nutzen: 5 bis 15 % relative EER bei passender Kohorte, mehr bei Kanalabweichung, aber nie die ganze Lücke von 0,3. [Vermutung auf Basis der Zahlen oben]
- Mittelwertabzug: WeSpeaker bewertet "cosine (sub mean of vox2_dev)" [belegt, README], also mit Abzug des mittleren Einbettungsvektors. Bei uns fehlt dieser Schritt. Kosten: ein Vektor je Modell, einmal berechnet. Der Einzeleffekt ist in der README nicht getrennt ausgewiesen, nur die Gesamt-EER. [abgeleitet: Versuch lohnt, Zahl unbekannt]
- Schwellen je Länge haben wir bereits (0,35 bis 0,45). Kalibrierung auf Zielbedingungen braucht beschriftete Fälle (Frage 7).
- Einfache Kanaladaption (CORAL, Alam et al. 2018): i-Vektoren 12,68 zu 12,11 % EER, x-Vektoren 8,93 zu 8,91 %, also fast kein Gewinn bei neuronalen Einbettungen [belegt, nur Abstract].

### Frage 3: Mehrere Abdrücke, Nachlernen, Risiken

- Apple (Personalized Hey Siri, 2018): 5 Vektoren aus der ausdrücklichen Aufnahme, bei der impliziten Aufnahme wächst das Profil bis 40 Vektoren, die Entscheidung ist der Mittelwert der Kosinuswerte gegen alle Profilvektoren gegen eine Schwelle (kein Maximum). Wenn Fremdannahmen früh ins Profil gelangen, sei das Profil "corrupted". Apple nennt keinen Filter. [belegt]
- Amazon (arXiv 2109.02576): Profileinbettung = L2-normierte Einbettungen gemittelt, Entscheidung über das höchste Profil im Haushalt [belegt].
- Mittelwert gegen Maximum über die Aufnahmestücke: Für i-Vektoren und PLDA sind Maximum und Mittel ähnlich gut [belegt, Suche]. Moderne Neuronalmodelle: kein Vergleichstest gefunden.
- Qualitätsgestütztes Nachlernen: nur nach bestandenem Prüftor, Gewicht klein, sonst "absorbiert" die Vorlage später gesprochene Sprache (Uppsala-Abschlussarbeit, nur Suchzusammenfassung, PDF nicht lesbar) [belegt schwach]. Unüberwachte Adaption brachte im NIST-Modus 15 % DCF und 35 % EER relativ (ältere Arbeit mit i-Vektoren) [belegt, anderer Modelltyp].

Empfehlung für uns [abgeleitet]:

- Ein Mittelpunkt je Mikrofonklasse (eingebaut, Headset kabelgebunden, Bluetooth, unbekannt), bestimmt aus dem Einlernen am jeweiligen Gerät. Bewertung: Maximum der Mittelpunktwerte, nicht Maximum über Einzelstücke, das hebt auch die Fremdwerte.
- Nachlernen nur als Kandidatenliste je Gerät, nie den ersten Abdruck ersetzen. Prüftor: Posterior hoch (Frage 7), Dauer mindestens 2 s, Kosinus zum Anker mindestens eine feste Grenze, höchstens ein neuer Vektor alle 5 Minuten, Obergrenze 20 Vektoren je Gerät mit ältester zuerst entfernt, Zurücksetzen durch die Person jederzeit.
- Vergiftung: Der Angreifer müsste das Prüftor passieren, also schon wie die Person klingen; das Risiko wächst bei Familienmitgliedern oder ähnlichen Stimmen (vier ähnliche Hausstimmen erreichten 0,45 bis 0,53, README 1171). Darum Anker nie überschreiben.
- Modellwechsel zwingt zu neuem Einlernen, weil wir kein Audio speichern. Apple speichert Audio, um Profile neu zu bauen. Das ist bei uns nicht zulässig (README und Einwilligung: nie eine Aufnahme). Schema deshalb mit `model_id` und Gerätekennung je Abdruck.

### Frage 4: Modellvergleich (Stand 2024 bis 2026)

Alle Zahlen: Vox1-O (bereinigt), volle Länge, je Quelle, mit Vorbehalt bei Protokollen. Zeit auf CPU: nur die eigene Messung aus der README (TitaNet 33, 41, 54 ms für 1, 1,5, 2 s; WeSpeaker ResNet34 23, 37, 47 ms, 2 Threads, x86 Laptop), nichts selbst gemessen.

| Modell | Größe | EER Vox1-O (volle Länge) | Kurz oder Rauschen | Lizenz (Gewichte) |
|---|---|---|---|---|
| TitaNet-Large | 25,3 M | 0,68 (Paper), 0,66 (Modellkarte) | keine Messung im Paper; im Feld unter 1 s etwa 30 % (Telefonie) | CC-BY-4.0 laut Modellkarte; Trainingsdaten VoxCeleb1+2, Fisher, Switchboard, LibriSpeech, SRE 2004 bis 2010 |
| ECAPA-TDNN (SpeechBrain) | k. A. | 0,80 | im Feld nahe Zufall (2611.09516) | Apache-2.0, trainiert auf VoxCeleb1+2, keine Garantie für andere Daten |
| WeSpeaker ResNet34 | 6,6 M | 0,867 (0,659 mit LM, AS-Norm, QMF) | k. A. | CC-BY-4.0 laut Modellkarte (pyannote), "folgt der Lizenz von VoxCeleb" |
| WeSpeaker ResNet293 | 28,6 M | 0,595 (0,425 mit allem) | k. A. | wie oben |
| CAM++ | 7,2 M | 0,71 bis 0,80 (0,659 mit LM, AS-Norm) | Feld: 31,3 bis 32,6 % | 3D-Speaker: Code Apache-2.0, Modelllizenz nicht genannt, Training teils chinesische Daten |
| ERes2NetV2 (3D-Speaker) | 17,8 M | 0,61 | k. A. | wie oben |
| ReDimNet B2, B3 | 4,7 M, 3,0 M | 0,57, 0,50 (mit LM) | nur MUSAN und RIR im Training | MIT (Gewichte auf Torch Hub, ONNX nicht mitgeliefert) |
| ReDimNet B6 | 15 M | 0,40 (0,37 mit AS-Norm) | 4-s-Fenster in ReDimNet2+ | MIT |
| ReDimNet2+ | 12,3 M | 0,351 (4-s-Fenster, lokal) | Stress-EER mit 26 Kodierungen 1,99 % | Gewichte auf Hugging Face, Lizenz nicht geprüft |
| ECAPA2 | 27 M | 0,34 bis 0,44 | k. A. | **CC-BY-NC-4.0, nicht kommerziell nutzbar** |
| WavLM Large + ECAPA | 316 M und mehr | 0,38 bis 0,42 (je Fassung) | k. A. | nicht für CPU unter 150 ms geeignet [Vermutung] |
| Resemblyzer (GE2E, 256 Werte) | k. A. | keine Angabe vom Projekt | "5 bis 30 s für ein Profil" | Apache-2.0, veraltet |
| Picovoice Eagle | 4,5 MB | Hersteller: 0,18 % EER (Datensatz laut Seite nicht beschrieben) | k. A. | geschlossen, Lizenzschlüssel; REA nicht angewandt, kein Quelltext |

Kritik und Einschätzung:

- Die Rangfolge in der Tabelle gilt für lange, saubere Sprache [belegt]. Im Sub-Sekunden-Feld (2611.09516) liegen TitaNet, CAM++ und ECAPA innerhalb von einem Punkt, ECAPA sogar am Zufall. TitaNet-L wurde unter anderem mit Telefondaten (Fisher, Switchboard, SRE) trainiert; das passt zu dessen relativer Stabilität dort und könnte bei schmalbandigem Bluetooth helfen [Vermutung]. Ein Wechsel auf ein reines VoxCeleb-Modell (WeSpeaker, ReDimNet) könnte also schlechter, nicht besser sein.
- Der Vorsprung von ReDimNet zu TitaNet bei langer Sprache beträgt rund 15 bis 25 % relativ (B2, B3, jeweils mit großem Randabstand-Feintuning, andere Protokolle) [abgeleitet].
- Die Größen sind alle auf CPU unter 150 ms machbar [Vermutung: die README-Messung liegt bis 2 s unter 60 ms; ReDimNet-B2 hat 0,9 GMACs, ReDimNet-B3 3,0 GMACs gegen CAM++ 1,15, bei 2 s gemessen, nach Paper].
- Lizenz in einer Firma: ECAPA2 scheidet aus (nicht kommerziell). Alle VoxCeleb-Gewichte tragen die offene Frage, ob die Nutzung der YouTube-Audiodaten für Trainingsmodelle in kommerziellem Einsatz geklärt ist. Die Seite von VoxCeleb lizenziert nur die Metadaten (CC BY-SA 4.0) und sagt nichts zur kommerziellen Nutzung der Modelle. Das ist eine Frage für die Rechtsberatung, keine Antwort von mir.
- Picovoice: Vom Hersteller selbst betriebene Messung; die Seite des Herstellers und die README im Repo nennen für pyannote und SpeechBrain vertauschte Zahlen (0,49 und 0,70), Datensatz, Aufnahmelänge und Modellversionen fehlen. Als Beleg ungeeignet [belegt].

### Frage 5: Audiovorverarbeitung vor dem Embedding

- **Browser-Aufbereitung (Echo, Rauschen, Verstärkung).** Keine Messung zum Einfluss auf Sprechereinbettungen gefunden [belegt, Lücke]. Für Spracherkennung und VAD empfehlen Praxisquellen, Echo an und Rauschen und Verstärkung aus zu lassen, weil Unterdrückung Wortanfänge und Wortenden abschneidet und die Verstärkung Hintergrund anhebt (micdrop.dev, Praxisblog, keine Messreihe). Der Wert ist je Browser ein "Wunsch", kein Zwang (MDN). Ein gemessener Satz bleibt aus; deshalb A/B-Test mit eigenen Daten (Empfehlung 9).
- **Eigene Entrauschung vor dem Embedding.** [belegt] In arXiv 2611.09516 erhöht DeepFilterNet die EER für alle vier konkurrierenden Modelle um 2,03 bis 4,89 Punkte (TitaNet-Large 29,62 zu 33,18), DTLN half nur ECAPA um 0,45 Punkte; Erklärung: Glättung der Formantfeinstruktur. Empfehlung des Preprints: Verifikation auf unverändertem Signal, Entrauschen nur für die Spracherkennung, hinter der Abzweigung. arXiv 2508.18913 (2025): Entrauschung kann Sprechereigenschaften verfälschen, generative Verfahren am stärksten; Fusion aus verrauschter und entrauschter Einbettung hilft, mit lernbarem Netz. FaSNet bei 5 dB: 34,4 % EER unbehandelt, 45,7 % allein mit FaSNet (Suchzusammenfassung). RNNoise: keine Untersuchung zu Sprechereinbettungen gefunden. Fazit: Kein Rauschfilter vor TitaNet. [belegt für DeepFilterNet und generative Verfahren, Vermutung für RNNoise und Browser-NS]
- **Zuschnitt.** Wir schneiden Pausen, Vorlauf und Nachlauf (stimme_modell.py:314). Der Preprint fand, dass volle VAD-Stücke bis rund 1 s besser sind als feste 700-ms-Ausschnitte (+0,8 bis +2,2 Punkte EER); er sagt nichts über das Entfernen von Stille [belegt]. Mindestsprachlänge: unter 1 s ist keine Trennung möglich, das deckt sich mit unserem Befund (0,14 bis 0,49 gegen 0,10 bis 0,30).
- **Lautstärke.** TitaNet normiert Merkmale je Äußerung (per_feature), reine Verstärkung ist also ohne Wirkung, Verstärkung mit Pumpen (AGC) verändert aber das Rauschverhältnis in kurzen Stücken [abgeleitet].
- Der Mikrofontest in den Einstellungen misst bereits Grundrauschen und Sprachpegel; das ist die richtige Stelle, um zusätzlich `getSettings()` zu protokollieren.

### Frage 6: Wie lösen es die anderen?

| System | Mechanismus | Verhalten bei Unsicherheit | Quelle, Stärke |
|---|---|---|---|
| Apple, Personalisiertes Hey Siri | Festtext (Weckwort), 5 Vektoren ausdrücklich, bis 40 implizit, Mittelwert der Kosinus gegen Schwelle | Weckwort unterbleibt (FR 5 bis 10 %, FA etwa ein Fall pro Monat, EER der Erkennung 4,3 bis 8,0 %); Schwelle tauscht FA gegen FR | Apple 2018, primär |
| Google Voice Match | Sprachmodell wird auf dem Gerät gehalten, die Anfrage bei Nichttreffer als Gästeanfrage | "Without a match, the device treats the query as a guest query and won't provide personal results"; Hinweis, dass eine ähnliche Stimme persönliche Ergebnisse erreichen könne | Google-Hilfeseite, primär (Ähnlichkeitswarnung aus Suchtreffer, nicht wörtlich abgerufen) |
| Amazon Voice ID | Stimmprofil im Cloud-Modell; Profil standardmäßig aus, dann behandelt Alexa jede Stimme wie den Hauptkonto-Inhaber | Personalisierung, kein Sperren; Details der Schwelle nicht veröffentlicht | AARP (sekundär), arXiv 2109.02576 |
| LiveKit Agents | Kein Sprecherabdruck. Voice Isolation (Krisp VIVA, ai-coustics) hebt den Hauptsprecher hervor, Hintergrundstimmen werden unterdrückt; `MultiSpeakerAdapter` wählt den Hauptsprecher nach Lautstärke | Hintergrundstimmen können weiter unterbrechen, wenn man nur Transkripte filtert | LiveKit-Dokumentation, primär |
| Pipecat | Kein Sprecherabdruck, aber Filter (RNNoise, Krisp VIVA, Koala) und Soniox-Diarisierung (`enable_speaker_diarization`) | keine | lokaler Quelltext |
| Home Assistant, Rhasspy, Wyoming | Keine Sprechererkennung eingebaut; nur Wünsche und Eigenbauten | k. A. | Forum, schwach (nicht geprüft) |
| Picovoice Eagle | Geschlossenes Modell, 4,5 MB, Herstellermessung | k. A. | siehe Frage 4 |

Übertragbare Muster [abgeleitet]:

1. **Gastmodus statt Sperre** (Google): Wer nicht erkannt wird, bekommt keine persönlichen Daten. Bei uns: keine PC-Aktion ohne Bestätigungskarte, Auskünfte ohne Persönliches bleiben frei.
2. **Schwelle ist ein Regler** (Apple): Wer die Schwelle hebt, tauscht Fremdannahmen gegen Fehlabweisungen. Bei Apple gilt FA und FR im Prozentbereich auch mit viel Entwicklungsaufwand, EER 4 bis 8 % für das Weckwort.
3. **Implizit lernen mit Vorsicht** (Apple).
4. **Entfernen statt Erkennen** (LiveKit/Krisp): Fremde Stimmen aus dem Signal nehmen. Das ist keine Verifikation, setzt geschlossene Modelle voraus und passt nur, wenn ein Hauptsprecher klar lauter ist.
5. **Zusatzsignal für Sprecherwechsel**: Die Soniox-Diarisierung ist im Pipecat-Dienst vorhanden und liefert Sprechermarken je Sitzung, aber keine Identität; sie kann ein Signal "es spricht jemand anderes als vorher" liefern [Vermutung, nicht getestet, Kosten und Qualität offen].

Nicht übertragbar: Apple, Google, Amazon verifizieren auf eigener Hardware mit festem Mikrofon und meist festem Weckwort, mit riesigen Trainingsdaten und (Apple) gespeichertem Audio zum Neuaufbau. Bei uns gilt freie Sprache, wechselnde Mikrofone und keine Aufnahme.

### Frage 7: Weiche Nutzung, Wahrscheinlichkeit aus Score, Länge, Pegel, Verlauf

Aufbau [abgeleitet, keine Quelle für Sitzungsfusion gefunden; der Preprint 2611.09516 nennt Aggregation über Folgestücke als offene Arbeit]:

1. **Kalibrierung je Äußerung.** Logistische Regression (Platt) auf den Merkmalen: Kosinus TitaNet, Kosinus Schatten, log(Dauer in s), Rauschabstand (Grundrauschen gegen Sprachpegel, aus dem Mikrofontest oder je Segment), Gerätekasse, Wert minus Gerätemittelwert. Ergebnis: Wahrscheinlichkeit p(eigen | Daten) oder Log-Likelihood-Quotient. Das ist genau die QMF-Technik (Dauer, Rauschabstand, Einbettungsnorm als Qualitätsmerkmale), die in WeSpeaker bis 9 % relativ gewann und in einer Arbeit über Kalibrierung mit Dauer und Rauschen im Mittel 6 % EER [belegt; die zweite nur als Suchzusammenfassung].
2. **Sitzungskontext.** Prior hoch: Die Person ist mit Passwort und zweitem Faktor angemeldet und sitzt am eigenen Laptop, Fremdstimmen sind selten. Logarithmische Quotienten verrechnen mit Vergessen: `L_t = rho * L_(t-1) + LLR_t`, `p = sigmoid(L_t + logit(prior))`, `rho` etwa 0,7 bis 0,9, Deckel auf `L_t`. Aufeinanderfolgende Fehler sind nicht unabhängig (gleicher Kanal), darum `rho` kleiner als 1 [Vermutung, an Daten zu prüfen].
3. **Trainingsdaten für die Kalibrierung.** Eigene Fälle: Sitzungen der Person allein (alle eigen) und Fremdstimmen. Fremdfälle ohne fremde Biometrie: Einbettungen öffentlicher Kohorte (Frage 2). Nötig sind einige hundert Fälle je Klasse und Gerätekasse; ohne diese bleibt es bei den heutigen Schwellen.
4. **Nutzung ohne Sperre.**
   - Anzeige: drei Stufen (grün, gelb, rot) und die Zahl der letzten Urteile, nur für die Person selbst sichtbar.
   - Protokoll: Zahlen, nie Inhalt.
   - Zusatzfrage nur bei kritischen Aktionen: Karte mit "Bist du es?" nur, wenn p unter einer Grenze liegt und die Aktion kritisch ist. Das ergänzt die vorhandenen Karten (`pc_freigaben.py`), ersetzt sie nicht.
   - Das Signal ändert Reibung, nicht Rechte.
5. **Achtung Sicherheitsarchitektur** [belegt, `docs/ausrollen-neue-nutzer.md` Zeilen 394 und 501]: Für Mitglieder gilt heute, dass PC-Werkzeuge Sprache nur mit eingelerntem Abdruck annehmen, unabhängig vom Modus (Risiko S9, "Fremde Stimme löst PC-Befehle bei einem Mitglied aus"). Wird die Stimme nur noch Hinweis, entfällt dieser Schutz. Der verbleibende Schutz sind die Karten für kritische Aktionen; Niko sollte S9 ausdrücklich neu bewerten (Beschluss mit Datum).

### Frage 8: Online-Diagnose ohne Audio

Je Äußerung eine Zeile mit Zahlen (Erweiterung der vorhandenen Zeile `Stimmschatten:`; kein Text, kein Ton, keine Hashes des Tons):

- Kosinus TitaNet und Schatten, Differenz, Dauer der Sprache, Urteil, ob W.A.I.S. gleichzeitig sprach, Anzahl vorheriger Urteile je Sitzung.
- Rauschen: Grundrauschen und Sprachpegel in dBFS (zum Beispiel unterste 10 % der 20-ms-Blöcke gegen die lautesten 10 %), Spitzenpegel, Anteil übersteuerter Abtastwerte.
- Kette: Gerätekasse (eingebaut, Headset, Bluetooth, unbekannt, nur als Klasse, nicht als Name), `getSettings()` der Spur (`echoCancellation`, `noiseSuppression`, `autoGainControl`, `sampleRate`, `channelCount`), Browser und App-Version, Tageszeit in Stunden.
- Abdruck: `model_id`, Alter des Abdrucks in Tagen, Gerätekasse beim Einlernen.

Auswertung ohne Beschriftung [abgeleitet]: In einer angemeldeten Einzelsitzung ist fast jede Äußerung eigen. Die Eigen-Rate je Person, Gerätekasse und Dauerklasse ist daher ein Stellvertreter für die Fehlabweisung. Wochenkurven mit P10, P50, P90 der Kosinuswerte je Gerätekasse; Alarm bei P50 unter dem Wert der ersten Woche minus 0,10 über mindestens 30 Äußerungen (Grenze ist eine Annahme); Vergleich der Verteilungen mit KS-Test oder PSI gegen die erste Woche; Abstand Schatten gegen Haupt je Dauerklasse als Zusatzsignal. Vorhandenes Skript `scripts/wamo_stimme_schatten_auswerten.py` (AUC, EER, d') liest dieselben Zeilen und braucht für die Trennung zwei beschriftete Läufe.

Datenschutz [abgeleitet, keine Rechtsberatung]: Zahlen je Äußerung mit Profilbezug sind personenbezogen. Bei einer Prüfung zur Identifizierung ist wahrscheinlich Art. 9 DSGVO berührt (EDPB-Leitlinien 02/2021 zu virtuellen Sprachassistenten behandeln Nutzererkennung per Stimme als biometrisch; die Bankenverbände hielten dagegen, Quelle nur als Zusammenfassung abgerufen). Maßnahmen: Journal mit Aufbewahrung (zum Beispiel 30 Tage für Einzelzeilen), danach nur Wochenaggregate; Profil in Auswertungen pseudonymisieren; die Einwilligungstexte `stimme-1` und `stimme-2` und die Datenschutz-Folgenabschätzung (Abschnitt 4 Punkt 1 in `docs/labor-datenschutz-entwurf.md`) um die Protokollzahlen ergänzen. Die Person muss löschen können (bereits vorgesehen).

### Frage 9: Empfehlung nach Aufwand und Wirkung

**Heute (Stunden, ohne Programmänderung oder minimal)**

1. `WAMO_STIMME_PRUEFUNG=beobachten` und `WAMO_STIMME_NUR_EIGEN=aus` über `wamo-core-env`: nichts wird mehr verworfen oder gesperrt, das Log bleibt. Wirkung: Sperren fallen sofort. Das ist die Entscheidung des Produktinhabers. [belegt: Modus beobachten existiert, README Abschnitt Modi]. Vorher klären, was mit der Pflichtstufe der Mitglieder (S9) geschieht (Frage 7, Punkt 5).
2. Offline-Versuch 2 mal 2 mal 10 Sätze (Laptop und Headset, Rauschunterdrückung und Verstärkung an und aus, dasselbe Modell) klärt, was den Einbruch trägt. Aufwand etwa eine Stunde, keine Annahme nötig.
3. Spurdaten `getSettings()` und Rauschpegel je Sitzung in den Log schreiben (nur Zahlen). Aufwand klein.

**Diese Woche (ein bis drei Tage)**

4. Ein Abdruck je Mikrofonklasse (bis zu drei), Bewertung Maximum über die Mittelpunkte. Erwartet bis plus 0,15 bis 0,25 am Fremdgerät [belegt, eigene Messung]. Der größte und am besten belegte Hebel.
5. Aufnahme ohne Browser-Rauschunterdrückung und ohne Verstärkung, mit Echo an, als A/B je Sitzung (Schalter im Medienmanager; `WavRecorder.begin` hat die Vorgabe fest, `GeraeteMedienManager` überschreibt schon Teile davon, siehe `geraeteMedien.ts` Zeile 73 bis 103). Wirkung unbekannt, Hinweis aus Praxis und aus 2611.09516. Gegenrisiko: Soniox hört mehr Rauschen; deshalb Wortfehlerrate mitprotokollieren. [Vermutung]
6. Weiche Anzeige: Ampel mit drei Stufen aus Kosinus und Dauer, Zusatzfrage nur bei kritischen Aktionen mit niedrigem Wert.
7. Mittelwertabzug aus einer Kohorte und AS-Norm mit Kohorte aus öffentlichen deutschen Daten (nach Rechtsprüfung der Nutzungsbedingungen), erst im Schatten testen. Erwartet 5 bis 15 % relativ [Vermutung auf Basis von 9 bis 21 %].

**Nach dem Labortag am 05.12.**

8. Kalibrierung (Platt mit Dauer, Rauschabstand, Gerätekasse, Schatten) auf den bis dahin gesammelten Zahlen, danach Sitzungsfusion mit Vergessen. Erwartet 6 bis 9 % relativ gegenüber reinen Kosinuswerten [belegt für QMF in anderer Domäne].
9. Nachlernen mit Prüftor und Kandidatenliste je Gerät (Frage 3).
10. Zweiter Prüfer im Schatten: ReDimNet B2 oder B3 (MIT, 3 bis 5 Mio. Parameter) nach eigenem ONNX-Export, Vergleich mit TitaNet an den eigenen Zeilen. Kein Wechsel, solange nichts im eigenen Feld für Kurzäußerungen belegt ist.
11. Optional: Gegenprobe mit Picovoice Eagle nur als technischer Test (Lizenzschlüssel, geschlossen, Herstellerzahlen nicht belastbar).

**Nicht übertragbar oder abzulehnen**

- Absolute EER-Werte aus VoxCeleb (lange Interviews) und aus 2611.09516 (Callcenter, Telefonie, Hindi).
- Apples Neuaufbau aus gespeichertem Audio (bei uns nicht erlaubt).
- ECAPA2 (nicht kommerziell).
- Entrauschung vor dem Embedding (belegt schädlich für DeepFilterNet und generative Verfahren).
- Training oder Feinabstimmung von TitaNet auf unseren Daten (kein Datensatz, keine Aufnahmen). Der Preprint nennt Feinabstimmung als besten Weg, das gilt nur mit eigenen beschrifteten Daten.

## 4. Methodik und Lücken

Gelesen: 14 Quellen im Volltext oder Tabellenteil (TitaNet via ar5iv, ReDimNet, ReDimNet2+ bis Zeichen 100.000, arXiv 2609.25007, 2506.14226, 2611.09516, 2406.07103, WeSpeaker-README, Thienpondt, Apple, Modellseiten, Picovoice-README, sherpa-onnx-Quelltext, Pipecat-Quelltext im lokalen venv). PDFs ließen sich über das Abrufwerkzeug nicht lesen (rohe Bytes), dafür wurden HTML-Fassungen genutzt. Nicht abrufbar oder nur als Suchzusammenfassung: ScienceDirect (403), Uppsala-Arbeit (PDF), EDPB-PDF (nur CMS-Zusammenfassung), Amazon-Hilfeseite (nur AARP), Google-Ähnlichkeitswarnung. Kein Skill `rea:reverse-engineer-anything` angewandt: Für die offenen Pakete genügte der Quelltext (sherpa-onnx, Pipecat); Picovoice Eagle ist ein geschlossenes Binärmodell, dort gibt es keine eigene Prüfung. Suchtreffer mit arXiv-Nummern 2607 bis 2611 stammen aus dem laufenden Stand (Datum heute 18.11.2026) und wurden, soweit zitiert, per Abruf gegengeprüft.
Gesamtbewertung der Beleglage: mittel. Direkte Messungen zu Browser-Aufbereitung und Bluetooth-Codec gegen Sprechereinbettungen fehlen; dort stehen Aussagen als [abgeleitet] oder [Vermutung].

## 5. Quellen

1. Koluguri, Park, Ginsburg: TitaNet, ICASSP 2022 (arXiv 2021). https://arxiv.org/abs/2110.04410 (gelesen über https://ar5iv.labs.arxiv.org/html/2110.04410)
2. NVIDIA: speakerverification_en_titanet_large, Modellkarte (v1.10.0). https://huggingface.co/nvidia/speakerverification_en_titanet_large
3. Beyond Short Segments: Expanding Speaker Embeddings with Vector Archives, 2026. https://arxiv.org/html/2609.25007
4. Investigation of Zero-shot Text-to-Speech Models for Enhancing Short-Utterance Speaker Verification, 2025. https://arxiv.org/html/2506.14226
5. MR-RawNet, 2024. https://arxiv.org/html/2406.07103
6. Benchmarking Speaker Embedders in the Sub-Second Regime for Real-Time Voice AI Agents, 2026 (Preprint). https://arxiv.org/html/2611.09516
7. Yakovlev et al.: Reshape Dimensions Network for Speaker Recognition, Interspeech 2024. https://arxiv.org/html/2407.18223
8. ReDimNet2+: Multi-Corpus Data Scaling for Robust Speaker Verification, 2026. https://arxiv.org/html/2609.37014
9. WeSpeaker VoxCeleb v2 README (Ergebnistabelle). https://github.com/wenet-e2e/wespeaker/blob/master/examples/voxceleb/v2/README.md
10. Thienpondt et al.: Cross-Lingual Speaker Verification with Domain-Balanced Hard Prototype Mining and Language-Dependent Score Normalization, Interspeech 2020. https://arxiv.org/html/2007.07689
11. Quality measures based calibration with duration and noise dependency for speaker recognition, Speech Communication 2015. https://www.sciencedirect.com/science/article/abs/pii/S0167639315000643 (nur Suchzusammenfassung)
12. IDLab VoxSRC-20 Submission: Large Margin Fine-Tuning and Quality-Aware Score Calibration, 2020. https://arxiv.org/abs/2010.11255
13. Apple: Personalized Hey Siri, Machine Learning Journal, 2018. https://machinelearning.apple.com/research/personalized-hey-siri
14. Google: Voice Match, Hilfeseite. https://support.google.com/assistant/answer/9071681
15. AARP: Alexa und Google Assistant (sekundär). https://www.aarp.org/personal-technology/tech-guru-alexa-google/
16. Improving Speaker Identification for Shared Devices by Adapting Embeddings to Speaker Subsets (Amazon), 2021. https://arxiv.org/html/2109.02576v1
17. LiveKit: Noise and echo cancellation (Voice Isolation, Krisp VIVA, ai-coustics). https://docs.livekit.io/transport/media/noise-cancellation/ ; Speaker diarization. https://docs.livekit.io/agents/models/stt/diarization/
18. Picovoice: speaker-recognition-benchmark (Herstellermessung). https://github.com/Picovoice/speaker-recognition-benchmark
19. A Framework for Robust Speaker Verification in Highly Noisy Environments Leveraging Both Noisy and Enhanced Audio, 2025. https://arxiv.org/abs/2508.18913
20. Speaker Retrieval in the Wild: Challenges, Effectiveness and Robustness, 2025. https://arxiv.org/html/2504.18950
21. addpipe: getUserMedia Audio Constraints (Praxisblog). https://blog.addpipe.com/getusermedia-audio-constraints/ ; MDN: MediaTrackConstraints.noiseSuppression. https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/noiseSuppression
22. Analysis of Speaker Verification Performance Trade-offs with Neural Audio Codec Transmission, APSIPA 2025. https://arxiv.org/html/2509.02771v1
23. sherpa-onnx, speaker-embedding-extractor-nemo-impl.h (Quelltext). https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/speaker-embedding-extractor-nemo-impl.h
24. Modell- und Datenlizenzen: pyannote/wespeaker-voxceleb-resnet34-LM https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM ; ECAPA2 (CC-BY-NC-4.0) https://huggingface.co/Jenthe/ECAPA2 ; ReDimNet (MIT) https://github.com/IDRnD/ReDimNet ; SpeechBrain ECAPA (Apache-2.0) https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb ; 3D-Speaker https://github.com/modelscope/3D-Speaker ; Resemblyzer https://github.com/resemble-ai/Resemblyzer ; VoxCeleb1 https://www.robots.ox.ac.uk/~vgg/data/voxceleb/vox1.html
25. WavLM: Large-Scale Self-Supervised Pre-Training for Full Stack Speech Processing (Suchtreffer, EER 0,383 bis 0,420 je Fassung). https://arxiv.org/abs/2110.13900
26. EDPB: Guidelines 02/2021 on Virtual Voice Assistants, v2.0, 2021. https://www.edpb.europa.eu/system/files/2021-07/edpb_guidelines_202102_on_vva_v2.0_adopted_en.pdf ; Zusammenfassung CMS https://cms.law/en/hun/legal-updates/EDPB-Guidelines-on-Virtual-Voice-Assistants
27. Mozilla Common Voice Scripted Speech 25.0, Deutsch. https://datacollective.mozillafoundation.org/datasets/cmn4rsdh6009unz07jdn2ol9p
28. Alam, Bhattacharya, Kenny: Speaker Verification in Mismatched Conditions with Frustratingly Easy Domain Adaptation, Odyssey 2018. https://www.isca-archive.org/odyssey_2018/alam18_odyssey.pdf
29. Deep Speaker Embeddings for Far-Field Speaker Recognition on Short Utterances, 2020. https://arxiv.org/abs/2002.06033
30. Lyu: Quality-Aware Template Update for Online Speaker Verification, Uppsala. https://uu.diva-portal.org/smash/get/diva2:2080552/FULLTEXT01.pdf (nur Suchzusammenfassung)
