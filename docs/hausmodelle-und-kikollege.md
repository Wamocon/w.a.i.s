# Alles über Sokrates: Hausmodelle für W.A.I.S. und Anbindung an KiKollege

Planpapier, Stand 15.11.2026, Basis `origin/main` e01dd14 (Zweig `docs/hausmodelle-plan`, nur dieses Papier, kein Code). Kennzeichnung wie in den anderen
Planpapieren: **B** belegt (Datei:Zeile, Befehl oder Quelle), **A** abgeleitet, **V** vermutet oder nur durch eine Messung zu klären. Nichts wurde installiert,
umgestellt oder neu gestartet. Die Bestandsaufnahme lief nur lesend: SSH als `wamocon` auf die drei Sparks (`free`, `nvidia-smi`, `ollama list`, `docker ps`,
Prozessliste mit geschwärzten Argumenten), die Modellliste der Gateway-Konfiguration ohne Schlüsselzeilen, Abfragen an das vorhandene Prometheus und die
öffentlichen Statusendpunkte der KiKollege-Laufzeit. Keine `.env`, kein Schlüssel und keine Konfiguration mit Geheimnissen wurde gelesen.
Im Text heißt der Assistent W.A.I.S., technisch bleibt alles `wamo` (`CLAUDE.md`, Namensvertrag).

**Nachtrag 16.11.2026 (Paket H5, Zweig `feat/stimme-im-haus`).** Entscheidung von Niko: "Jetzt messen und einbauen, aber nicht umstellen
sondern in der Oberfläche umschaltbar machen". Messung M7 steht in Abschnitt 2.5, der Stand von H5 in Abschnitt 5. Soniox bleibt Standard,
Laborprofile hören immer über Soniox (F4). Die zwei Einträge im Gateway (2.5) sind seit 16.11.2026, 18:27 Uhr aktiv (Nikos Ja,
eingetragen vom Koordinator); Migration 0023 und `core.env` folgen nach demselben Ja.

Das Testlabor am 28.11.2026 hat Vorrang. Der Freeze für Kern, Migration, Oberfläche und Dienste am Server gilt seit So 15.11.2026 (`docs/testlabor-wamo.md:34`,
Entscheidung E14, vorher Fr 20.11. nach E5), der Daten-Freeze am Fr 27.11. Jedes Paket dieses Papiers beginnt deshalb frühestens am Mo 30.11.2026.

**Wunsch von Niko vom 15.11.2026 (wörtlich).** "Für die Zukunft müssen wir W.A.I.S. auch komplett auf die haueigenen Modelle in der UI umstellen können, also alles
über Sokrates und seine Modelle! Dafür muss du die besten bestehenden Modelle auf den Sparks dafür finden oder neuen Modelle dafür installieren! Es gibt auch ein Projekt
das heißt KiKollege von Erwin er hat schon Hermes eingebunden und viele Angenten, die Anbindung daran kannst du auch planen! Nutze dafür immer ECC und REA!"

## Kurzfassung

1. **Vieles ist schon da.** Je Profil gibt es heute die Wahl "Automatisch" oder "Nur Hausmodelle" in der Oberfläche, einen Zwang des Admins (nur über die
   Kommandozeile) und für Hausprofile einen Weg ohne jeden Aufruf an Anthropic: Gespräch, Lernen, Zusammenfassung und Bildschirm über LiteLLM, Websuche über SearXNG
   (**B** `voice-core/modellzugang.py:155` bis `:159`, `voice-core/tools.py:272`). Es fehlen ein **globaler Schalter für alle Profile**, der **Admin-Zwang in der
   Oberfläche** (die Datenbank verwehrt dem Kern das Schreiben von `nur_haus` heute bewusst), die **Stimme im Haus** (das Gateway führt kein Audiomodell) und
   **Entwicklungsaufträge ohne Claude**. Eine Lücke gibt es schon heute: Ein Hausprofil ohne API-Schlüssel, aber mit Claude-Code-Token startet weiter
   Entwicklungsaufträge mit Claude Code (**B** `voice-core/boss.py:213` bis `:216`).
2. **Bestes vorhandenes Gesprächsmodell im Haus bleibt `gemma4-31b`** (Werkzeugtreue 91,5 %, aber nur rund 10 Token/s und 7,5 s bis zum ersten Token bei neuem
   Prompt, **B** `voice-core/modellkarte.py:195`). Kein Hausmodell erfüllt heute die Freigabe des Testsatzes, Claude Haiku übrigens auch nicht (Marker 88 %).
3. **Erster neuer Kandidat fürs Gespräch: `google/gemma-4-26B-A4B-it`** (Apache 2.0, 3,8 Mrd. aktive Parameter, auf GB10 von Dritten mit rund 52 Token/s gemessen),
   betrieben mit vLLM statt Ollama, mit Prefix-Caching für den langen Systemprompt. Gleiche Familie wie das heutige Bestmodell, also gleiche Vorlage und ähnliches
   Werkzeugverhalten (**V**, nur die Messung entscheidet).
4. **Bildschirm, Lernen, Zusammenfassung, Boss:** vorhandene Modelle reichen. Für Hausprofile wählt der Boss dafür heute meist `gemma4-31b`; gemessen wird, ob das schnellere
   `qwen3.6-35b` gleich gut ist. Hintergrundlast von W.A.I.S. gehört **nicht auf Caesar**: Dort läuft KiKollege, und Caesar ist der einzige ausgelastete Knoten
   (GPU im Mittel 21 %, p95 96 % über 7 Tage).
5. **Stimme:** Soniox bleibt für alle der Standard (Vorgabe Niko). Als Option im Haus: Qwen3-ASR und Qwen3-TTS laufen schon auf Sokrates-1, es fehlen nur die Einträge im
   Gateway. Für echtes Streaming im Haus ist `mistralai/Voxtral-Mini-4B-Realtime-2602` (Apache 2.0) der Kandidat.
6. **Entwicklungsaufträge im Haus:** erst ein Spike, der Claude Code über das Gateway gegen einen offenen Agenten (OpenCode oder Qwen Code) mit `qwen3.6-35b` am selben
   Aufgabensatz misst. Anthropic unterstützt Claude Code mit fremden Modellen ausdrücklich nicht.
7. **KiKollege** ist das Vorhaben "KI-Mitarbeiter": Hermes Agent 0.22.1 auf Caesar mit sieben Profilen (Orchestrator, Reviewer, Researcherin, Architekt, Tester,
   Seitenpfleger, Übung), Qwen 3.8 27B, Aufträge heute nur über Telegram. **Empfehlung: Variante V2**, eine schmale Brücke zur Runs-API von Hermes, damit W.A.I.S.
   Aufträge an den Orchestrator weiterreicht, nach Freigabekarte, mit Ergebnis als Fremdinhalt. W.A.I.S. wird damit die Sprachbedienung von KiKollege, ohne Code
   zu übernehmen (Entscheidung vom 31.10.2026 bleibt).
8. **Aufwand:** rund 138 Stunden für alle Pflichtpakete auf Seite W.A.I.S., dazu 20 Stunden optional für Streaming-STT und rund 10 Stunden auf Seite KiKollege.

## 1. Bestandsaufnahme der Sparks (15.11.2026, 18:45 Uhr)

### 1.1 Modelle je Knoten

| Knoten | Dienst | Modelle (Belege) | Bemerkung |
| --- | --- | --- | --- |
| Sokrates-1 `192.168.178.75` | Ollama (systemweit) | `gemma4:31b` 19 GB, `qwen3.6:35b` 23 GB, `laaj-judge:v2` 36 GB, `sokrates-steuer:v0.1` 29 GB, `qwen3-embedding:8b` 4,7 GB, `all-minilm` (**B** `ollama list`) | Zum Zeitpunkt kein Modell geladen (`ollama ps` leer) |
| Sokrates-1 | vLLM (Container `vllm-qwen3-asr`, :8101) | `Qwen/Qwen3-ASR-1.7B` als `qwen3-asr-1.7b`, `--gpu-memory-utilization 0.08`, `--max-model-len 8192` (**B** Prozessliste) | belegt rund 8,8 GB GPU-Speicher |
| Sokrates-1 | Container `qwen3-tts` (:8102) | Qwen3-TTS, eigener Uvicorn-Dienst (**B** `docker ps`, Prozessliste) | rund 4,7 GB GPU-Speicher; API siehe 2.5 (**B**, 16.11.) |
| Sokrates-1 | LiteLLM (Container `uaol-litellm`, :4000) | zentrales Gateway, Modellliste siehe 1.2 | Hausregel: alle Modellaufrufe nur hierüber |
| Sokrates-2 `192.168.178.136` | Ollama | `qwen3.6:35b` 23 GB (geladen, 16k Kontext), `wamocon-coder:latest` 84 GB, `qwen3-coder-next:q8_0` 84 GB, `tr-legal-tuned-raw` 29 GB, `bge-m3`, `nomic-embed-text` (**B** `ollama list`, `ollama ps`) | Kern von W.A.I.S. läuft hier (`/opt/wamo-core/slots/a`) |
| Sokrates-2 | vLLM (Container `ocr-dots`, :8300) | OCR-Modell `dots-mocr`, `--gpu-memory-utilization 0.20` (**B**) | rund 20 GB GPU-Speicher |
| Caesar `192.168.178.64` | Ollama (Container `ollama`, :11434) | `qwen3.8:27b` 17 GB, `sokrates-qwen27-fable` 17 GB, `qwen3-coder-next:q8_0` 84 GB (**B** `docker exec ollama ollama list`) | Laufzeit von KiKollege (Hermes) nutzt `qwen3.8:27b` |
| Caesar | Sprache | `qwen3-asr-adapter` :8103, `whisper-gpu` :8791, `faster-whisper` :8787, `piper-de-mls` :8793, `speech-router` :8790, zwei weitere TTS-Dienste auf CPU (**B** `docker ps`) | `speech-router` lieferte am 19.10. HTTP 500 und bleibt gesperrt (`voice-core/modellkarte.py`) |
| Caesar | Weiteres | SearXNG :8080 (Websuche im Haus), eigenes LiteLLM :4000 für KiKollege, Hermes Agent (Dashboard :9120, Gateway) | siehe Abschnitt 4 |

### 1.2 Was das zentrale Gateway anbietet

Auszug aus `/app/config.yaml` im Container `uaol-litellm`, nur die Zeilen `model_name`, `model` und `api_base` (**B**). Aliase anderer Projekte sind weggelassen
(Regel `WAMO_LLM_AUSBLENDEN`, `voice-core/llm_anbieter.py:24` bis `:26`).

| Alias | Modell | Knoten |
| --- | --- | --- |
| `gemma4-31b`, `sokrates-fast` | `gemma4:31b` | Sokrates-1 |
| `qwen3.6-35b`, `sokrates`, `sokrates-pro` | `qwen3.6:35b` | Sokrates-1 |
| `qwen3-embedding` | `qwen3-embedding:8b` | Sokrates-1 |
| `laaj-judge` | eigener Bewertungsserver :8100 | Sokrates-1 |
| `qwen3-coder-next` | `wamocon-coder:latest` (84 GB) | Sokrates-2 |
| `qwen3-coder-next-raw` | `qwen3-coder-next:q8_0` (84 GB) | Sokrates-2 |
| `qwen3.8-27b` | `qwen3.8:27b` | **Caesar** |
| `sokrates-steuer`, `sokrates-fable-qwen27` | Fachmodell Recht, unbekanntes Modell | nie für W.A.I.S. (`voice-core/modellkarte.py`, Status `fachmodell` und `gesperrt`) |

Die Gruppen-Aliase der Modellkarte (`wamo-allgemein`, `wamo-vision`, `wamo-coder`, `wamo-embed`, `wamo-review`) stehen nicht in der Datei, das Gateway bedient sie über
seine Datenbank (**A** aus `voice-core/llm_anbieter.py:24`). Laut Modellkarte verhält sich `wamo-allgemein` wie `qwen3.8-27b`, läuft also auf Caesar.
**Kein Audiomodell** steht in der Datei (**B**), wie schon am 21.10. festgestellt (`voice-core/sprache_anbieter.py:18`). Ob die Datenbank des Gateways eines führt, lässt
sich ohne Schlüssel nicht prüfen (**V**). Routing `least-busy`, Rückfall aller Hausmodelle auf `sokrates`, Zeitgrenze 120 s (**B**).

### 1.3 Auslastung und freier Speicher

Quelle: das vorhandene Prometheus auf Sokrates-1 (Exporter `nvidia_gpu_exporter` :9835 und `node_exporter` :9100 auf allen drei Knoten), Fenster 7 Tage bis 15.11.2026
18:50 Uhr (**B**). Dazu die Momentaufnahme aus `free -g` und `nvidia-smi`.

| Knoten | GPU im Mittel (7 Tage) | GPU p95 (7 Tage) | Anteil Zeit mit GPU über 50 % | Speicher verfügbar, Minimum / Mittel (7 Tage) | jetzt verfügbar | GPU-Prozesse jetzt |
| --- | --- | --- | --- | --- | --- | --- |
| Sokrates-1 | 0,7 % | 0 % | 0,7 % | 23,6 GB / 52,2 GB | 83 GB | Qwen3-ASR 8,8 GB, Qwen3-TTS 4,7 GB |
| Sokrates-2 | 0,0 % (**V**, Plausibilität offen) | 0 % | 0 % | 53,8 GB / 64,2 GB | 64 GB | Ollama `qwen3.6:35b` 23 GB, OCR 20 GB |
| Caesar | 21,1 % | 96 % | 21,7 % | 30,5 GB / 84,4 GB | 97 GB | Whisper 6,8 GB, dazu Ollama nach Bedarf |

Speicher ist bei GB10 gemeinsamer Speicher von CPU und GPU (121 GB nutzbar). Sokrates-1 ist an Diensten stark belegt (Gateway, Datenbanken, Monitoring, Weboberflächen),
die GPU aber kaum. Ein Wert von genau 0,0 auf Sokrates-2 trotz geladener Modelle kann auch heißen, dass der Exporter kurze Rechenspitzen zwischen zwei Abtastungen nicht
sieht (**V**). Werktage und Wochenende lassen sich im Fenster nicht trennen; vor dem Einrichten eines Dauerdienstes misst Paket H0 deshalb eine Arbeitswoche.

### 1.4 Folgerungen für den Ort

1. **Caesar bleibt frei von W.A.I.S.-Last.** Dort rechnet KiKollege, und dort liegt die einzige echte GPU-Last. Die Aliase `qwen3.8-27b` und `wamo-allgemein`
   (laut Karte gleiches Verhalten) zeigen auf Caesar (**B** 1.2). Die Pakete nehmen sie für W.A.I.S. aus der Wahl des Boss.
2. **Sokrates-2 ist der natürliche Ort für das Gesprächsmodell im Haus:** GPU frei, mindestens 53,8 GB verfügbar, und der Kern läuft auf demselben Knoten. Ein vLLM-Dienst
   mit festem Speicheranteil verträgt sich aber nicht mit den beiden 84-GB-Codermodellen im Ollama desselben Knotens. Genau eines davon wählt der Boss heute für jede
   Aufgabe der Art `code`, auch für Claude-Profile, wegen des Spezialistenvorschusses (**B** `voice-core/boss.py:96`, `voice-core/test_boss.py:92`). Neben einem
   festen vLLM-Anteil könnte so ein Auftrag den Speicher des Knotens füllen, auf dem der Kern läuft (**A**). Paket H1 sperrt die Codermodelle deshalb vorher in der
   Karte; Entscheidung F3.
3. **Sokrates-1 bekommt nichts Neues** außer zwei Einträgen im Gateway (Stimme) und dem Alias für das neue Gesprächsmodell. Das Gateway ist geteilt; Einträge nur
   nach Absprache mit seinem Betreiber (Hausregel, Gedächtnis "Eigene Instanzen statt mitnutzen").

### 1.5 Befunde nebenbei

- **Schlüssel in der Prozessliste.** Ein vorhandener vLLM-Dienst auf Sokrates-2 bekommt seinen API-Schlüssel als Befehlszeilenargument; jeder lokale Benutzer sieht ihn mit
  `ps`. Der Wert steht hier bewusst nicht. Für eigene vLLM-Dienste gilt deshalb: Schlüssel aus einer Datei mit Rechten 0400 oder über die Umgebung (`VLLM_API_KEY`),
  nie als Argument. Der Betreiber des Dienstes sollte den Schlüssel tauschen.
- **KiKollege-Dashboard im LAN.** Das Hermes-Dashboard auf Caesar lauscht auf `0.0.0.0:9120`. Anmeldung ist Pflicht, aber `/api/status` antwortet ohne Anmeldung mit
  Version, Zustand der Telegram-Kanäle je Profil und Installationskennung (**B**, siehe 4.2). Hinweis an KiKollege, keine Änderung durch W.A.I.S.
- **Zweites Gateway.** KiKollege nutzt ein eigenes LiteLLM auf Caesar statt des zentralen. Für W.A.I.S. ohne Folge, nur zur Einordnung.

## 2. Bewertung je Baustein

### 2.1 Messlatte

Ein Modell taugt fürs Gespräch nur bei mindestens 95 % richtigen Werkzeugaufrufen, mindestens 98 % korrekten Satzende-Markern, erstem Token p95 höchstens 0,6 s, ohne
Verstoß in den Muss-Fällen und in drei Läufen hintereinander (**B** `README.md:1446`). Diese Latte reißt auch Claude Haiku 5.5 (Werkzeug 96,1 %, Marker 88,2 %, erstes
Token p95 1,04 s, **B** `voice-core/modellkarte.py:167`). Für den Haus-Modus schlägt dieses Papier eine eigene Stufe vor (Entscheidung F1): Werkzeug mindestens 95 %,
Marker mindestens 95 %, erstes Token p95 höchstens 1,5 s mit warmem Prompt, keine Muss-Verstöße, pass^3.

Die Zahlen der Modellkarte stammen vom 20. bis 22.10.2026. Seitdem haben sich Persona und Werkzeuge geändert (Messungen vom 1.11. und 10.11. in
`docs/gespraech-optimierung.md`); vor jeder Entscheidung misst Paket H0 die vorhandenen Modelle neu.

### 2.2 Empfehlung je Baustein

M heißt von Dritten auf GB10 gemessen, S geschätzt (Token/s ≈ Wirkungsgrad × 273 GB/s ÷ aktive Parameter in Byte; Wirkungsgrad aus Messungen kalibriert, rund 0,4 bei
MoE, 0,65 bei dichten Modellen). Hauszahlen (H) aus der Modellkarte.

| Baustein | Heute im Claude-Profil | Bestes vorhandenes Hausmodell (Beleg) | Neuer Kandidat (Quelle) | Empfehlung |
| --- | --- | --- | --- | --- |
| Gespräch | Claude Haiku 5.5 | `gemma4-31b`: Gespräch 0,961, Marker 96,7 %, Werkzeug 91,5 %, 10 Token/s, erstes Token warm 1,4 s, neuer Prompt 7,5 s (H) | `google/gemma-4-26B-A4B-it`, Apache 2.0, 25,2 Mrd. / 3,8 Mrd. aktiv, 16,5 GB NVFP4, M 52 Token/s, erstes Token 53 ms (vLLM); Tau2 68,2 gegen 76,9 beim 31B \[3\]\[4\] | 26B-A4B in vLLM (FP8, Prefix-Caching, zuerst ohne MTP) gegen den Testsatz; `gemma4-31b` bleibt Referenz und Rückfall |
| Werkzeuge | wie Gespräch | wie Gespräch, Werkzeugtreue 91,5 % (H) | Nemotron 3.5 Lightning 30B-A3B (OpenMDW, Deutsch unterstützt, keine Werkzeug-Benchmarks) \[9\]; `openai/gpt-oss-120b` (Apache 2.0, rund 62 GB MXFP4, M 60 Token/s) \[1\]\[10\] | nur messen, wenn der 26B-A4B die Latte reißt; gpt-oss nur mit eigenem Knoten (Größe) |
| Sehen (Bildschirm) | Claude (VISION_MODEL) | `wamo-vision` bzw. `gemma4-31b`: 2/2, 14 s (H); `qwen3.6-35b`: 1/1, 3,8 s (H, dünn) | `Hcompany/Holo4-35B-A3B` (Basis Qwen 3.6, laut Karte Apache 2.0, Lizenz widersprüchlich) \[20\]\[21\]; `Qwen/Qwen3.8-27B` (OSWorld laut Hersteller 84,3, aber auf Caesar) \[5\] | `qwen3.6-35b` mit mehr Fällen messen (schnell, Sokrates-1); `gemma4-31b` bleibt Qualitätsreferenz; Holo4 erst nach Lizenzklärung |
| Lernen | laut Rangliste `gemma4-31b` mit 15 s Vorversuch, danach Claude Haiku (`voice-core/llm_anbieter.py:93`, `voice-core/test_boss.py:340`) | `gemma4-31b` 1,0 in 47 s; `wamo-allgemein` 1,0 in 16 s (Caesar); `qwen3.6-35b` 0,75 in 14 s (H) | kein neues Modell nötig; das JSON-Schema schickt der Kern schon (`voice-core/learning.py:147`); ob Ollama es über das Gateway erzwingt, zeigt M3 (vLLM tut es nachweislich \[25\]) | `qwen3.6-35b` gegen `gemma4-31b` messen; das schnellere Modell bei gleicher Güte |
| Zusammenfassung | wie Gespräch | `qwen3.6-35b` 1/1 in 4,1 s, 262k Kontext \[8\] (H) | keiner | `qwen3.6-35b`, mit mehr Fällen nachmessen |
| Boss (unklare Aufgaben) | Claude Haiku | unklare Aufträge laufen über die Klasse Gespräch (`voice-core/boss.py:682`), also über das Gesprächsmodell des Hauses | Router wie Ministral-3-3B (Apache 2.0) \[26\] | kein neues Modell und keine Codeänderung; der Boss fragt selten |
| Entwicklungsaufträge | Claude Code (Token Sonnet, sonst Haiku) | `wamo-coder` 7/8 in 7,2 s; `qwen3.6-35b` 7/8 in 3,6 s (H) | `Qwen/Qwen3.6-35B-A3B` FP8: SWE-bench Verified 73,4, Terminal-Bench 2.0 51,5, M 54 bis 86 Token/s \[1\]\[8\]\[40\]; Coder-Next ist überholt (SWE-V 70,6) und 84 GB groß \[41\] | Spike H6: Agent (Claude Code über Gateway oder OpenCode) mit `qwen3.6-35b` |
| STT | Soniox (EU) | `qwen3-asr` 1.7B: p50 280 ms, p95 573 ms je ganzer Äußerung, Wortfehlerrate 1,2 %, ohne Zwischenergebnisse (M7, 2.5) | `mistralai/Voxtral-Mini-4B-Realtime-2602`, Apache 2.0, echtes Streaming, WER Deutsch FLEURS 6,19 % bei 480 ms \[43\]; `nvidia/parakeet-tdt-0.6b-v3` (CC-BY-4.0, WER 5,04 %, nur gepuffert) \[45\] | Soniox bleibt Standard; Option Haus zuerst mit Qwen3-ASR, später Voxtral Realtime |
| TTS | Soniox (EU) | `qwen3-tts`: kein Streaming, erstes Audio 1,4 bis 2,1 s je Satz, nur eine Anfrage zugleich (M7, 2.5); `piper-de` 0,1 bis 0,2 s (H) | Qwen3-TTS bleibt die beste freie Wahl (Apache 2.0, Streaming über vLLM-Omni) \[49\]\[50\]; Voxtral-4B-TTS ist nicht kommerziell (CC BY-NC) \[55\] | Soniox bleibt Standard; Option Haus mit Qwen3-TTS, Piper als schneller Rückfall (Lizenz der Stimme prüfen) |

### 2.3 Betrieb der neuen Modelle

- **vLLM statt Ollama für das Gespräch.** Auf GB10 sank das erste Token beim Wechsel von Ollama auf vLLM von rund 3 s auf 0,12 s, der Durchsatz stieg von 40 auf 52 Token/s
  (Gemma 4 26B-A4B, M) \[2\]. Prefix-Caching hält den langen Systemprompt mit den Werkzeugschemas warm; genau das kostet heute 7,5 s bei neuem Prompt.
- **FP8 vor NVFP4 bei MoE**, weil NVFP4-MoE auf GB10 oft auf langsamere Kernel ausweicht \[40\]. Nur der NVIDIA-Container, kein `pip`; `--gpu-memory-utilization` ist ein
  Anteil am gesamten gemeinsamen Speicher \[19\].
- **Vorsicht bei Gemma 4 in vLLM:** Der Streaming-Werkzeugparser hat einen offenen Fehler, und mit MTP (spekulatives Dekodieren) werden Werkzeugaufrufe beschädigt \[13\]\[14\].
  Deshalb zuerst ohne MTP messen; die Zahlen des Testsatzes entscheiden, nicht die Benchmarks.
- **Warmhalten:** Der Vorschlag aus `README.md:1500` (Aufwärmanfrage beim Anmelden, alle 5 Minuten wiederholen) wird Teil von Paket H2. Mit vLLM bleibt das Modell
  ohnehin geladen; Ollama-Modelle brauchen `keep_alive`.
- **Für deutsches Werkzeugverhalten gibt es keine unabhängigen Benchmarks** \[18\]. Der hauseigene Testsatz mit 51 Zügen ist der entscheidende Beleg.

### 2.4 Messplan mit den vorhandenen Werkzeugen

Alle Läufe im Ordner `voice-core/`, nacheinander mit Pausen, nur über das Gateway, Ergebnisse unter `voice-core/eval/ergebnisse/` (nur anhängen). Die Modellkarte wird erst
nach den Läufen geändert, `test_modellkarte.py` rechnet jede Zahl nach.

| Schritt | Befehl | Modelle | Freigabe | Dauer |
| --- | --- | --- | --- | --- |
| M1 Gespräch, Bestand | `uv run python eval/abnahme.py --anbieter litellm --modell <alias> --wiederholungen 3` | `gemma4-31b`, `qwen3.6-35b`, Referenz `--anbieter claude` | Haus-Stufe aus 2.1 (F1), pass^3 | je Modell rund 40 min |
| M2 Antwortzeit live | `uv run python eval/modellkarte_messen.py latenz --modell <alias> --nach-pause 330` | dieselben | erstes Token mit neuem Prompt höchstens 10 s (`LIVE_NEU_MAX_S`), warm p95 höchstens 1,5 s | je 15 min |
| M3 Bausteine | `uv run python eval/bausteine.py --anbieter litellm --modell <alias>`, dreimal | `qwen3.6-35b` (Lernen mit JSON-Schema, Zusammenfassung, Bild), `gemma4-31b` (Bild) | Lernen 4/4 in allen drei Läufen, Bild 3/3 | je 10 min |
| M4 Labor-Fälle | `python eval/messrunde_labor.py --anbieter litellm --modell <alias> --wiederholungen 3` | Gesprächssieger aus M1 | keine Muss-Verstöße (indirekte Injektion) | 30 min |
| M5 Neues Gesprächsmodell | M1, M2 und M4 mit dem neuen Alias `wamo-gespraech` | `gemma-4-26B-A4B-it` in vLLM | wie M1 | 2 h |
| M6 Code | `uv run python eval/modellkarte_messen.py code --anbieter litellm --modell <alias>` und der Spike aus H6 | `qwen3.6-35b`, `wamo-coder` | 8/8, danach drei echte Aufgaben | 1 h plus Spike |
| M7 Stimme | `scripts/wamo_stimme.py` und `scripts/wamo_latenz.py` mit `WAMO_STT_ANBIETER=haus` bzw. `WAMO_TTS_ANBIETER=haus` | Qwen3-ASR, Qwen3-TTS, später Voxtral | erster Ton nach Sprechende p95 höchstens 0,5 s über Soniox; Hörprobe von Niko | je Lauf 15 min |

### 2.5 Messung M7: Stimme im Haus (16.11.2026)

Einmalig direkt an den Diensten auf Sokrates-1 gemessen, vom Laptop im Büronetz (für diese Messung erlaubt; der Kern spricht die Dienste
nie direkt an, nur über das Gateway). Nur lesend: `docker ps`, `docker inspect` ohne Werte der Umgebung, `/health`, `/openapi.json`, der
Quelltext des TTS-Dienstes. Am Gateway wurde nichts geändert. Soniox nicht neu gemessen (Kosten); Vergleich aus
`docs/sprache-elevenlabs-soniox.md` 6.2 (`LATENZ_JSON`, 03.11. bis 15.11.2026). Skript und Rohwerte lagen nur lokal, Hörproben
der Stimmen unter `D:\tmp\stimme-hoerprobe-haus` (nicht im Repo).

**Schnittstellen (B).**

| Dienst | Container und Aufruf | Schnittstelle | Besonderheiten |
| --- | --- | --- | --- |
| Spracherkennung | `vllm-qwen3-asr`, Port 8101 auf 8000, `vllm serve Qwen/Qwen3-ASR-1.7B --served-model-name qwen3-asr-1.7b --gpu-memory-utilization 0.08 --max-model-len 8192 --max-num-seqs 16`, ohne Schlüssel | OpenAI-kompatibel: `POST /v1/audio/transcriptions` (multipart `file`, `model`, `language`, `prompt`, `response_format`, `temperature`), dazu `/v1/audio/translations`, `/v1/models`, `/health` | Antwort `{"text", "usage"}` als reiner Text, ohne Sprachpräfix; ganze Äußerung, keine Zwischenergebnisse |
| Sprachausgabe | `qwen3-tts`, Port 8102 auf 8000, eigener FastAPI-Dienst mit `faster-qwen3-tts`, Modell `Qwen3-TTS-12Hz-1.7B-CustomVoice` (Apache 2.0), ohne Schlüssel | OpenAI-ähnlich: `POST /v1/audio/speech` mit JSON `input`, `voice`, `response_format` (Standard mp3; `wav` und `pcm` liefern WAV, sonst über ffmpeg), optional `language` und `instructions`; `model` wird nicht ausgewertet; `GET /health` nennt die Stimmen | ganze Datei, kein Streaming; WAV mono 16 Bit, 24 kHz; Kopfzeilen `X-Synth-Seconds`, `X-Language`; ein Lock: immer nur eine Anfrage zugleich |

Stimmen: neun eingebaute Sprecher (`vivian`, `serena`, `uncle_fu`, `dylan`, `eric`, `ryan`, `aiden`, `ono_anna`, `sohee`), keiner nativ deutsch,
Standard des Dienstes `aiden`. Die Sprache nimmt der Dienst aus `language`, sonst rät er sie am Text (Umlaute oder Wörter wie "und", "ich",
"ist"), im Zweifel Englisch.

**Ergebnisse.**

| Messung | Haus (Qwen3) | Soniox (Vergleich) |
| --- | --- | --- |
| STT, 12 Sprechproben Windows-Stimme Hedda (2,2 bis 7,5 s, 16 kHz), je 3 Läufe, Zeit von der fertigen Äußerung bis zum Text | p50 280 ms, p95 573 ms, max 733 ms (n = 36); erste Anfrage nach Pause einmal 2,5 s | Sprechende bis endgültiges Transkript p50 229 ms, p95 280 ms |
| STT, dazu vor dem Senden | Ende der Sprachaktivität `WAMO_VAD_STOP_SECS` (Standard 0,2 s), Weg über das Gateway (nicht gemessen) | im Wert oben enthalten |
| STT, Wortfehlerrate gegen den bekannten Text | 1,2 % gewichtet (ein Fehler: "Mach" als "Macht"); Fachbegriffe als `prompt` ohne Wirkung | Herstellerangabe Deutsch 1,25 % |
| STT, neuronale Stimme statt natürlicher Aufnahme (im Repo liegt keine; sechs Sätze aus Qwen3-TTS, je 2 Läufe) | p50 358 ms, p95 619 ms, Wortfehlerrate 2,9 % | nicht gemessen |
| TTS, 1 Satz (39 Zeichen, 2,4 bis 3,3 s Audio), Stimmen `uncle_fu` und `sohee`, je 3 Läufe | erstes Audio 1,42 bis 2,13 s, gleich der Gesamtdauer | erster Satz bis erstes Audio p50 172 ms, p95 382 ms |
| TTS, 2 Sätze (87 Zeichen, 5,0 bis 5,4 s Audio) | 2,9 bis 3,5 s | Streaming |
| TTS, 4 Sätze (rund 200 Zeichen, 12,9 bis 13,2 s Audio) | 6,3 bis 8,6 s; Echtzeitfaktor 0,51 bis 0,62 | Streaming |
| TTS, kurze Antworten ("Gerne.", "Fertig.", "Alles klar.") | 0,44 bis 0,58 s; "Erledigt." und "Moment." 1,3 bis 1,7 s | |
| TTS, zwei Anfragen zugleich | die zweite wartet: 1,8 s und 3,4 s | |
| TTS, Stimmenwahl Deutsch (2 Sätze, Rückweg über die Spracherkennung) | Wortfehlerrate 0 % bei acht Stimmen, 7 % bei `aiden` ("Gerne" als "Kenne"); Dauer 2,5 s (`sohee`) bis 4,1 s (`ryan`) | |
| TTS, Sprache ohne Feld `language` (so kommt die Anfrage über das Gateway an) | 6 von 8 kurzen deutschen Antworten als Englisch gesprochen ("Alles klar.", "Erledigt.", "Moment.", "Gerne.", "Fertig.", "Guten Morgen!") | Deutsch fest eingestellt |

**Über das Gateway (erste Proben des Koordinators nach dem Eintrag, Schlüssel des Kerns, Stimme `sohee`).** Spracherkennung ohne
`response_format` lehnt das Gateway mit HTTP 400 ab (LiteLLM verlangt von sich aus verbose_json, das Qwen3-ASR nicht kann); mit `json`
geht es, der Kern schickt es seitdem immer (`HausSTTService`). Sprachausgabe 0,56 bis 1,47 s je Satz. Beim Rücklesen kamen 3 von 4 kurzen
Sätzen deutsch an, "Erledigt." nicht; zwei der drei guten waren auch direkt ohne Sprachangabe deutsch. Die volle Wiederholung von M7 über
das Gateway (Skript mit eingebetteten Sprechproben, nur Messwerte in der Ausgabe) steht aus.

**Bewertung.**

1. **Spracherkennung im Haus taugt.** Gleiche Güte wie Soniox bei klarer Sprache, dafür rund 0,3 bis 0,5 s später (Ende der Sprachaktivität
   plus ganze Äußerung) und ohne Live-Mitschreiben. Ungeprüft bleiben echte Stimmen, Störgeräusche und Fachwörter; das zeigt erst ein
   Lauf mit `scripts/wamo_stimme.py`.
2. **Sprachausgabe im Haus reißt die Latte von M7** (erster Ton höchstens 0,5 s über Soniox): je Satz 1,2 bis 1,8 s später, weil der Dienst die
   ganze Datei erst am Ende liefert. Er bedient außerdem nur eine Anfrage zugleich; mehrere Personen im Haus warten aufeinander.
3. **Sprache Deutsch erzwingen, bevor jemand "Im Haus" wählt.** Das Gateway reicht bei `/audio/speech` nur `response_format`, `speed` und
   `instructions` weiter (LiteLLM 1.92.0, `litellm/main.py`, `speech`), nie `language`. Kurze Sätze ohne Umlaut oder Hinweiswort spricht der
   Dienst deshalb englisch aus. Abhilfe am Dienst: im Zweifel Deutsch statt Englisch (eine Zeile in `_guess_language` oder eine Umgebungsvariable
   wie `DEFAULT_SPEAKER`), nur mit Nikos Ja.
4. **Stimme:** Vorschlag `sohee` (schnellste, 0 % Fehler), endgültig nach Nikos Hörprobe; `aiden` nicht nehmen.
5. **Folge für die Oberfläche:** "Im Haus" ist ein Datenschutzmodus mit spürbarer Wartezeit, kein Ersatz für Soniox. Der Satz unter dem
   Schalter nennt die Folgen. Für echtes Streaming der Stimme bleibt Qwen3-TTS über vLLM-Omni \[50\] (neues Paket, Messung wie hier).

**Einträge im Gateway (seit 16.11.2026, 18:27 Uhr aktiv).** Unter `model_list` der Konfiguration des zentralen Gateways (`/app/config.yaml`
im Container `uaol-litellm`, Bindung an eine Datei im Home von `wamocon` auf Sokrates-1), neben `wamo-haus-coder`. Eingetragen ist es mit
`api_base` auf `192.168.178.75` (gleichwertig zu `host.docker.internal`, beide aus dem Container geprüft) und bei `wamo-tts-haus` zusätzlich
`extra_body: {language: German}`. Nach dem Quelltext von LiteLLM 1.92.0 erreicht `extra_body` den Dienst bei Speech nicht (siehe Punkt 3
oben); die Messung über das Gateway entscheidet. Der Schlüssel des Kerns sieht beide Modelle in `/v1/models`. Sicherung der Datei:
`litellm_config.yaml.vor-wamo-stimme.20261116-182624`. Vorlage:

```yaml
  # W.A.I.S.: Hören und Stimme im Haus (Paket H5). Beide Dienste prüfen keinen Schlüssel; "none" ist ein Platzhalter und verhindert,
  # dass LiteLLM einen OPENAI_API_KEY aus seiner Umgebung an die Dienste schickt.
  - model_name: wamo-stt-haus
    litellm_params:
      model: openai/qwen3-asr-1.7b
      api_base: http://host.docker.internal:8101/v1
      api_key: "none"
      timeout: 30
    model_info:
      id: wamo-stt-haus-node1
      mode: audio_transcription
  - model_name: wamo-tts-haus
    litellm_params:
      model: openai/qwen3-tts
      api_base: http://host.docker.internal:8102/v1
      api_key: "none"
      timeout: 60
    model_info:
      id: wamo-tts-haus-node1
      mode: audio_speech
```

Rückweg: die Sicherung `litellm_config.yaml.vor-wamo-stimme.20261116-182624` zurückkopieren (oder die beiden Blöcke löschen) und
`docker restart uaol-litellm`. Ohne die Einträge fällt der Kern von selbst auf Soniox zurück und nennt den Grund.
Der Neustart unterbricht das Gateway für alle Nutzer kurz; deshalb außerhalb von Gesprächen und Läufen.

## 3. Entwurf "Alles über Sokrates"

### 3.1 Was es heute gibt

| Ebene | Heute | Beleg |
| --- | --- | --- |
| Person | Umschalter "Automatisch" oder "Nur Hausmodelle" in der Karte Modellzugang, ab der nächsten Sitzung | `ui/src/components/ModellWahl.tsx:12`, `voice-core/modellzugang.py:157` |
| Admin je Profil | Zwang `nur_haus`, dazu `stt`, `tts`, Claude-Modell, **nur über die Kommandozeile** | `voice-core/wamo_admin.py:69` bis `:75` |
| Global | nur Umgebungsvariablen am Kern: `WAMO_STT_ANBIETER`, `WAMO_TTS_ANBIETER` für alle, `WAMO_LLM_*` je Baustein, aber mit Rückfall auf Claude | `voice-core/sprache_anbieter.py:45`, `voice-core/llm_anbieter.py:300` |
| Fehlerfall | jede Unsicherheit führt zu "nur Hausmodelle" (fail-closed) | `voice-core/modellzugang.py:136` |
| Hausprofil | kein Anthropic-Aufruf im Kern, auch nicht als Rückfall; Websuche über SearXNG; Boss wählt nur Hausmodelle. Claude-Code-Aufträge nur bei Quelle `wahl` oder `festgelegt` aus; ein Hausprofil ohne API-Schlüssel, aber mit Token startet sie weiter | `voice-core/boss.py:201` bis `:216`, `voice-core/modellzugang.py:186`, `voice-core/tools.py:272` |

### 3.2 Zielbild: drei Ebenen, eine Wirkung

1. **Global (Betrieb, nur Admin):** Schalter "Alles über Sokrates". Ist er an, laden alle Büro-Profile ihren Zugang als `haus` mit der Quelle `betrieb`, unabhängig von
   Schlüssel und Wahl. Laborprofile bleiben ausgenommen, solange Niko es nicht anders entscheidet (F4).
2. **Admin je Profil:** wie heute `nur_haus`, aber in der Oberfläche statt über die Kommandozeile, mit Stimme (Soniox oder Haus) je Profil.
3. **Person:** wie heute "Automatisch" oder "Nur Hausmodelle", neu dazu die Stimme "Soniox (Standard)" oder "Im Haus".

Vorrang: global vor Admin vor Person. Die stärkste Einschränkung gewinnt; niemand kann eine höhere Ebene lockern. Gelesen wird beim Sitzungsstart. Ein Datenbankfehler
heißt wie heute "im Haus". Eine fehlende Tabelle (Kern-Release vor der Migration oder nach ihrem Rückweg) heißt dagegen "Schalter aus" mit Warnung im Log, wie es der Kern
schon für die fehlenden Spalten von Migration 0011 hält (`voice-core/modellzugang.py:113` bis `:117`); sonst landeten alle Profile ungewollt im Haus.
Zusätzlich ein **Notschalter** `WAMO_LLM_NUR_HAUS=an` in `core.env`, der ohne Datenbank wirkt, für den Fall, dass ein Anbieter gesperrt werden muss. Der Name liegt
bewusst im Präfix `WAMO_LLM_`, das `wamo-core-env` schon zulässt (`infra/sokrates2/wamo_core_env.py:105`). Anders als der Schalter in der Oberfläche gilt der Notschalter
auch für Laborprofile, denn er ist für den Fall gedacht, dass gar nichts mehr an Anthropic gehen darf.

### 3.3 Oberfläche

- **Einstellungen, neuer Abschnitt "Modelle im Betrieb" (nur Admin, zweiter Faktor):** Schalter "Alles über Sokrates" mit Bestätigungsdialog, der die Folgen nennt
  (Gespräch, Lernen, Bildschirm, Zusammenfassung und Websuche im Haus; Entwicklungsaufträge aus, solange H6 fehlt; Qualität laut Modellkarte; gilt ab der nächsten
  Sitzung). Darunter je Profil: Modus (Person wählt oder Haus erzwungen), Stimme (Soniox oder Haus), Claude-Modell. Jede Änderung schreibt einen Eintrag in `actions`
  (wer, was, wann, ohne Inhalte).
- **Karte Modellzugang der Person:** zeigt den wirksamen Stand und seinen Grund ("vom Admin für alle festgelegt"), sperrt die Wahl, wenn eine höhere Ebene sie festlegt,
  und bietet die Stimme an, mit dem Hinweis, dass die Stimme im Haus heute ohne Zwischenergebnisse arbeitet.
- **Statusleiste:** kurzer Hinweis "im Haus", wie heute der Modellname mit "(LiteLLM)" (`voice-core/llm_anbieter.py:202`).

### 3.4 Was im Kern fehlt

| Nr | Lücke | Ort | Paket |
| --- | --- | --- | --- |
| L1 | Globaler Schalter mit Quelle `betrieb`, dazu Notschalter `WAMO_LLM_NUR_HAUS`; fehlende Tabelle heißt "aus" (3.2) | neue Tabelle per Migration 0021 (mit `.down.sql`, RLS, Policy `core_all`, nur nötige Grants, Selbsttest), `modellzugang.zugang_laden` | H3 |
| L2 | Admin-Zwang je Profil (`nur_haus`, `stt`, `tts`, Modell) aus der Oberfläche. Migration 0010 gibt `wamo_core` darauf bewusst keine Schreibrechte, ihr Selbsttest bricht sogar ab, sobald `wamo_core` `nur_haus` schreiben darf (`supabase/migrations/0010_modellzugang.sql:86` und `:115`). Nötig ist ein eigener Weg, etwa eine `security definer`-Funktion mit Prüfung der Rolle `admin` des aufrufenden Profils und Audit, und ein angepasster Selbsttest (F10) | Migration 0021, `voice-core/modellzugang_api.py` | H3 |
| L3 | Die Stimme hängt schon heute nur an der Wahl des Profils (`voice-core/bot.py:735`); Soniox bleibt also im Modus "nur Haus". Nur `boss.sprache_wunsch` (`voice-core/boss.py:224`) behauptet anderes und wird allein in Tests benutzt: aufräumen. Neu ist nur, dass die Person ihre Stimme selbst wählen darf (wie L2). **Stand 16.11.2026:** Die Wahl der Person ist gebaut (Migration 0023 statt 0021, Aktion `stimme`, H5); das Aufräumen von `boss.sprache_wunsch` bleibt bei H3 | `boss.py`, Migration 0023 | H3, H5 |
| L4 | Audiomodelle im Gateway (Qwen3-ASR, Qwen3-TTS). **Stand 16.11.2026:** Einträge `wamo-stt-haus` und `wamo-tts-haus` vorbereitet (2.5), nicht eingetragen | zentrales LiteLLM, Betreiber fragen | H5 |
| L5 | Neues Gesprächsmodell als Dienst mit Rauchtest und Rückweg | `infra/sokrates2/` (Skript mit `--trocken`), Alias `wamo-gespraech` | H1 |
| L6 | Warmhalten des Gesprächsmodells | `boss.py`, Sitzungsstart | H2 |
| L7 | Entwicklungsaufträge im Haus: Die Auftragssandbox darf heute ins Internet (TCP 80 und 443), aber nicht ins LAN, dazu sperrt Landlock (`infra/sokrates2/wamo-job.sh:45` bis `:50`); das Gateway ist also nicht erreichbar. Der Dispatcher kennt und schwärzt nur Anthropic-Schlüssel (`infra/sokrates2/wamo_job_dispatch.py:177` bis `:189`). Nötig: genau eine Ausnahme in `wamo-egress.nft` für das Gateway (GitHub und npm bleiben offen), ein eigener virtueller Gateway-Schlüssel mit Budget, ein Schwärzmuster dafür und die Quelle `haus` in `boss.entwicklung_quelle` | Dispatcher, `wamo-egress.nft`, `boss.py` | H6 |
| L8 | Prüfung der Selbstüberarbeitung: Der Prüfer in der Sandbox nutzt Claude über einen eigenen Proxy (`wamo-pruefer-proxy@claude`). Im Haus-Modus entweder Ausnahme (Betreiberfunktion) oder Hausvariante | `infra/sokrates2/release/pruefer/` | F6 |
| L9 | Modellkarte und Boss mit den neuen Messungen; Caesar-Aliase und die 84-GB-Codermodelle aus der Wahl nehmen; veralteten Hinweis "US-Projekt" bei Soniox berichtigen (`voice-core/modellkarte.py:346`, seit 02.11. EU-Projekt laut `README.md`) | `voice-core/modellkarte.py`, `voice-core/test_boss.py` | H1, H2 |
| L10 | Prüfung "kein Anthropic-Client im Haus-Modus" als Test, der jeden Aufbau eines Anthropic-Clients im Kern scheitern lässt | neue Tests | H3 |
| L11 | Claude-Code-Aufträge im Haus-Modus sperren: Quelle `betrieb` in die Ausschlussliste von `boss.entwicklung_quelle` (`voice-core/boss.py:213`), Schalter und Notschalter auch in `claude_code_zugang_fuer` (`voice-core/modellzugang.py:434`), in `serverzugang_erlaubt` (`voice-core/dev_agent.py:187`) und beim Hinterlegen von Schlüssel und Token prüfen. L10 fängt das nicht, weil Claude Code in der Sandbox läuft | `boss.py`, `modellzugang.py`, `dev_agent.py` | H3 |
| L12 | `wamo-core-env` lässt außer festen Namen nur das Präfix `WAMO_LLM_` zu (`infra/sokrates2/wamo_core_env.py:38` bis `:105`). `WAMO_STT_*`, `WAMO_TTS_*` und ein Schalter für KiKollege brauchen eine erweiterte Liste, mit Tests. **Stand 16.11.2026:** Die fünf Namen der Stimme stehen in `ERLAUBT`, bewusst nicht in `AUS_ENV` von `scripts/wamo_kern_sokrates2.py` (ein Testwert `haus` am PC darf nie alle Sitzungen umstellen); der Schalter für KiKollege folgt mit K1 | `wamo_core_env.py` | H3, H5 |

### 3.5 Was "alles" im Haus-Modus heißt

| Teil | Im Haus-Modus | Bemerkung |
| --- | --- | --- |
| Gespräch und Werkzeuge | Hausmodell über das Gateway | Boss wählt nach Karte, kein Rückfall auf Claude |
| Lernen, Zusammenfassung, Boss, Analyse | Hausmodell | schon heute für Hausprofile |
| Bildschirm | Hausmodell | heute nehmen die Bildschirm-Werkzeuge bei Claude-Profilen Claude (`VISION_MODEL`); nur Bildaufgaben über `aufgabe_verteilen` laufen schon im Haus (`voice-core/boss.py:30`) |
| Websuche | SearXNG auf Caesar | Suchanfragen gehen ohne Personenbezug an Suchmaschinen |
| Stimme | Soniox (Standard) oder Haus je Profil | Vorgabe Niko |
| Entwicklungsaufträge | aus, auch mit hinterlegtem Claude-Code-Token (L11), bis H6 abgenommen ist | danach Hausagent |
| Jira, Outlook, Teams, OneNote | unverändert | das sind Ziele, keine Modelle; jeder Versand weiter nur nach Freigabekarte |
| Prüfer der Selbstüberarbeitung | nach F6 | Betreiberfunktion, keine Personendaten |
| Testlabor | unverändert (Haiku über den Server-Schlüssel) | F4 |

### 3.6 Datenschutzgewinn

| Datenart | Claude-Profil heute | Haus-Modus, Stimme Soniox | Haus-Modus, Stimme im Haus |
| --- | --- | --- | --- |
| Gesprochenes (Audio) | Soniox, EU-Projekt | Soniox, EU-Projekt | bleibt im Haus |
| Abschrift, Antworten, Verlauf | Anthropic (USA) | Text nur bei Soniox (Abschrift, Sprachausgabe), Modell im Haus | bleibt im Haus |
| Gedächtnis, Canvas, Dateien im Prompt | Anthropic | bleibt im Haus | bleibt im Haus |
| Bildschirmfotos | Anthropic (`VISION_MODEL`), nur Bildaufgaben des Boss im Haus | bleibt im Haus | bleibt im Haus |
| Websuche | Anthropic-Websuche | SearXNG | SearXNG |
| Code bei Entwicklungsaufträgen | Anthropic (Claude Code) | aus bzw. im Haus nach H6 | aus bzw. im Haus nach H6 |

Gewinn: Mit dem Haus-Modus verlässt kein Inhalt aus Gedächtnis, Canvas, Gespräch und kein Bildschirmfoto mehr das Haus in Richtung eines US-Anbieters. Es bleibt Soniox als
Auftragsverarbeiter in der EU für Audio und Abschrift (AVV liegt als Entwurf vor). Mit der Stimme im Haus bleiben nur noch Suchanfragen und die ausdrücklich
freigegebenen Ziele (Jira, Mail, Teams).

### 3.7 Der Preis

Ehrlich gesagt: Im Haus wird W.A.I.S. heute langsamer und fehleranfälliger als mit Claude. `gemma4-31b` braucht beim ersten Satz einer neuen Sitzung 7,5 s und schreibt
10 Token/s; schnelle Modelle wie `qwen3.6-35b` treffen Werkzeuge zu selten (73,9 %). Paket H1 soll diese Lücke mit vLLM und dem 26B-A4B schließen, belegt ist das erst
nach M5. Bis dahin ist der Haus-Modus ein Datenschutzmodus mit spürbarem Qualitätsverlust, kein gleichwertiger Ersatz.

## 4. KiKollege

### 4.1 Kurzbeschreibung

KiKollege ist das Vorhaben "KI-Mitarbeiter" der WAMOCON (verantwortet von Erwin). Das Repository `Wamocon/kiKollege` (öffentlich, letzter Merge 13.11.2026, 3709191)
enthält nur die Seiten des Vorhabens (Next.js, statischer Export, Daten aus `data/projektstand.json`), nicht die Laufzeit (**B**). Die Laufzeit steht auf Caesar.

- **Prinzip:** "Ein KI-Mitarbeiter arbeitet zu. Ein Mensch entscheidet." Jeder KI-Mitarbeiter hat eine Akte (Auftrag, Haltung, Grenze als Dateien), ein eigenes Programm,
  der Zaun, prüft jeden Werkzeugaufruf gegen die Grenze, bevor er läuft. Übergaben zwischen KI-Mitarbeitern laufen über Dateien (**B** `projektstand.json`,
  Felder `mannschaft.akte`, `steuerung`, `techstack`).
- **Laufzeit:** Hermes Agent von Nous Research, je KI-Mitarbeiter ein Profil; Modell Qwen 3.8 27B über Ollama; Kanban-Board von Hermes, eine Karte je Auftrag; Ablage als
  Obsidian-Vault in Git (**B** `techstack`).
- **Mannschaft:** Orchestrator Hermes, Reviewer Fritz (prüft Ausbildungsunterlagen), Researcherin julia-trend (einzige mit Netz), Technischer Architekt Arnold,
  Pfleger der Seiten Gregor Dev, Tester Theo (Robot Framework); Reporter, Entwickler und Gestalter sind entschieden, aber nicht eingerichtet (**B** `mannschaft`).
- **Kanäle:** Aufträge an den Orchestrator über Telegram, Theo mit eigenem Zugang; Jira für Epics und Stories. Der Orchestrator nimmt nur Aufträge aus seiner Tabelle an,
  lehnt allgemeine Fragen ab und reicht Ergebnisse unverändert zurück (**B** `anleitung`).
- **Stand:** Am 10.11. ging die geübte Fassung des Orchestrators in Betrieb (17 bis 18 von 18 Prüffällen je Lauf, Antwortzeit im Median rund eine Minute). Das Team bekommt
  Zugang frühestens ab 23.11. (Meilenstein M2), "Sprache für alle" ist Meilenstein M3, Termin offen (**B** `training.laeufe`, `meilensteinplanAktuell`).
- **Regel:** Kein KI-Mitarbeiter wird mit Antworten von Claude nachtrainiert (**B** `training.regel`).

### 4.2 Laufzeitsicht (lesend)

| Was | Befund | Beleg |
| --- | --- | --- |
| Version | Hermes Agent 0.22.1 (Release 24.09.2026); aktuell ist 0.23.1 vom 09.11.2026 \[57\] | `GET /api/health`, `GET /api/status` |
| Dienste | `hermes-gateway.service` (Telegram), `hermes-dashboard.service` (Web und Fernzugang für Hermes Desktop), beide als Benutzerdienste | `systemctl --user list-units` |
| Profile | `hermes-chef`, `hermes-uebung`, `fritz`, `julia-trend`, `tester`, `arnold`, `gregor-dev` | Ordner `profiles` |
| Telegram | vier verbundene Kanäle (Orchestrator, Fritz, julia-trend, Tester) | `/api/status` |
| Dashboard | `0.0.0.0:9120`, Anmeldung Pflicht (Basic, Cookie, PKCE); `/api/profiles`, `/api/sessions`, `/api/config` antworten 401; `/api/status` und `/api/health` ohne Anmeldung | `curl`, nur GET |
| OpenAI-kompatible Schnittstelle | auf dem Dashboard-Port nicht vorhanden (`/v1/models` leitet zur Anmeldung); kein API-Server auf 8642 und keine Webhooks auf 8644 im LAN | `ss -ltnp` |
| Modelle | eigenes LiteLLM auf Caesar mit Aliasen auf `qwen3.8:27b` für Orchestrator und Verteiler | Modellliste ohne Schlüssel |
| REA | `rea analyze-javascript-application` (REA 6.8.0) auf das öffentlich ausgelieferte Anmeldeskript: ein Skript, ein Netzwerkendpunkt `/auth/password-login`; die eigentliche Oberfläche liegt hinter der Anmeldung und wurde nicht analysiert | Evidence `ev_1c96ddf1…` (lokal) |

### 4.3 Schnittstellen, die eine Anbindung nutzen könnte

Laut Dokumentation von Hermes Agent \[58\]\[59\]\[62\]\[63\]\[64\]:

- **API-Server:** `/v1/chat/completions`, `/v1/responses`, `/v1/models` und `/v1/runs` (Auftrag mit `session_id` und `Idempotency-Key`, Rückgabe `run_id`, Stand über
  `GET /v1/runs/{id}` oder Ereignisse per SSE, Freigaben über `/approval`). Bearer-Schlüssel auch auf Loopback Pflicht, Standard `127.0.0.1:8642`. Auf Caesar nicht aktiv.
- **Webhooks:** Port 8644, HMAC-Signatur; Ergebnisse gehen nur an Plattformen (Slack, Mail, Log), keine allgemeine Rückruf-Adresse.
- **MCP:** Hermes ist MCP-Client (stdio und HTTP); als MCP-Server nur über das Plugin `mcp-serve` ab 0.23.0.
- **ACP** über stdio für Editoren, hängt am Gateway-Dienst.
- **Telegram** wie heute.

### 4.4 Drei Varianten

| Variante | Wie | Vorteile | Nachteile |
| --- | --- | --- | --- |
| **V1 Messenger** | W.A.I.S. schreibt dem Orchestrator über ein eigenes Telegram-Konto | auf Seite KiKollege nichts zu bauen | Inhalte laufen über einen Cloud-Messenger; Bots können Bots nicht anschreiben, also bräuchte es ein Benutzerkonto; Zuordnung zur Person unklar; Ergebnis nur als Chattext |
| **V2 Runs-Brücke (empfohlen)** | Hermes-API-Server nur auf Loopback auf Caesar; davor eine schmale Brücke (eigener Benutzer, eigener Schlüssel), die genau zwei Dinge erlaubt: Auftrag an das Profil des Orchestrators mit der Kennung der Person, Stand und Ergebnis eines eigenen Auftrags abfragen. Aufgerufen vom Kern über einen Zwangsbefehl per SSH, wie der Kern-Kanal des Dispatchers (`infra/sokrates2/wamo_job_kernkanal.py`) | alles im Haus; der Orchestrator bleibt Türsteher mit seiner Tabelle und seinem Zaun; W.A.I.S. wird die Sprachbedienung (KiKollege M3), ohne dass KiKollege Sprache bauen muss; Ergebnis kommt als Daten in eine Karte unter Vorgänge | Hermes-Update auf mindestens 0.23.1 nötig; Brücke und Schlüssel liegen auf Seite KiKollege; asynchron (Median rund eine Minute) |
| **V3 MCP in beide Richtungen** | Hermes bindet W.A.I.S. als MCP-Server ein (etwa Gedächtnis lesen, Canvas schreiben), oder W.A.I.S. bindet Hermes über `mcp-serve` ein | feinkörnig, Standardprotokoll | ein autonomer Agent griffe in Personendaten von W.A.I.S.; Freigabekarten kann kein Agent klicken; `mcp-serve` ist neu (05.11.2026); größte Angriffsfläche |

Verworfen: Aufträge als Notiz direkt in die Ablage oder das Kanban-Board von KiKollege zu schreiben. Die Ablage kommt dort erst nach dem Ja eines Menschen auf den
KI-Rechner, und W.A.I.S. bekäme Schreibrecht auf fremdes Wissen.

**Empfehlung V2**, erst nur für Admin-Profile, nach M2 von KiKollege für Mitglieder, die auch auf der Auftraggeberliste von KiKollege stehen. Umgekehrte Richtung
(KiKollege ruft W.A.I.S.) erst, wenn ein konkreter Fall da ist, und dann nur lesend und ohne PC-Werkzeuge.

### 4.5 Sicherheitsgrenzen

- **Fremdinhalt:** Ergebnisse von KiKollege sind Daten, nie Anweisungen. Behandlung wie bei `aufgabe_ergebnis`: Marker und Steuerzeichen entfernt, gekennzeichnet,
  `turn.taint()`, kein Lernen, kein sofort wirksames gemeinsames Wissen, nach dem Abholen keine neue Aufgabe im selben Zug (`voice-core/boss.py:1` bis `:31`). Die
  Researcherin von KiKollege liest im Netz; versteckte Anweisungen sind also zu erwarten.
- **Freigabekarten:** Jeder Auftrag an KiKollege braucht eine Karte (Job `kikollege`) mit dem genauen Text, dem Empfänger (Orchestrator) und dem Hinweis, welche Daten
  W.A.I.S. verlassen. Ohne Klick geht nichts raus. W.A.I.S. schickt nie Gedächtnis, Canvas, Dateien oder Bildschirm mit, nur den Text der Karte.
- **Rechte:** zuerst nur Admin in Sitzungen der Betriebsart Büro, nie Laborprofile; eine Kennung je Person (keine geteilte Identität), damit der Orchestrator wie
  heute festhält, von wem ein Auftrag kam und nur über eigene Aufträge Auskunft gibt. Weil die eine Brücke die Kennung trägt, die der Kern ihr nennt, erzwingt die
  Brücke selbst: Zuordnung jeder `run_id` zur Kennung, Abfrage nur eigener Aufträge, nur Kennungen von der Auftraggeberliste von KiKollege.
- **Grenzen:** höchstens 10 Aufträge am Tag je Profil im Kern, dazu ein Stundenlimit und eine Notaus-Datei auf Seite der Brücke (wie `MAX_VERSUCH_STUNDE` und
  `kernkanal.notaus` beim Kern-Kanal); Größengrenzen für Auftrag und Ergebnis (wie `MAX_ERGEBNIS_ZEICHEN`, `voice-core/boss.py:365`); eine Grenze für Abfragen.
  Fordert Hermes eine Freigabe an (`/approval`), lehnt die Brücke sie sofort ab, statt den Lauf hängen zu lassen.
- **Weg:** Brücke mit Zwangsbefehl in `authorized_keys` mit `restrict` und `from="192.168.178.136"` (keine Shell), der Host-Schlüssel von Caesar fest in
  `known_hosts` des Kerns, Hermes-API nur auf Loopback, deren Schlüssel nur bei KiKollege. W.A.I.S. speichert keinen Schlüssel von KiKollege im Kern, nur den
  SSH-Schlüssel der Brücke.
- **Keine Kette:** Nach `kikollege_stand` gibt es im selben Zug weder einen neuen Auftrag noch einen Versand (Jira, Mail, Teams, OneNote).
- **Nie:** PC-Werkzeuge, Freigaben oder Entwicklungsaufträge von W.A.I.S. für Hermes. Hermes wird nicht in W.A.I.S. eingebaut (Entscheidung vom 31.10.2026).
- **Protokoll:** je Auftrag ein Eintrag in `actions` (Werkzeug `kikollege_auftrag`, Profilkennung, Zeit, Ergebnis ja oder nein), ohne Inhalte.
- **Hinweise an KiKollege**, ohne Eingriff: Dashboard auf Loopback oder hinter VPN binden, `/api/status` nicht offen ins LAN, auf 0.23.1 aktualisieren (Liste bekannter
  Schwachstellen älterer Fassungen in \[66\]\[67\], dort nur teils mit Primärquelle).

### 4.6 Aufwand

| Teil | Stunden |
| --- | --- |
| Abstimmung mit KiKollege, Vertrag der Brücke (Nachrichten, Fehler, Grenzen) als Dokument mit Vertragstest | 8 |
| Kern: Werkzeuge `kikollege_auftrag` und `kikollege_stand`, Freigabekarte, Karte unter Vorgänge, Fremdinhalt, Grenzen, keine Kette, Audit | 16 |
| Tests (Einheit, Fremdinhalt, Freigabe, Grenzen, Größen, keine Kette) und Sicherheitsreview mit `security-reviewer` | 6 |
| Summe W.A.I.S. | **30** |
| Seite KiKollege: Hermes 0.23.1, API-Server auf Loopback, Brücke, Auftraggeberliste | rund 10 (Schätzung, entscheidet KiKollege) |

## 5. Pakete

Reihenfolge: H0 zuerst. Danach laufen zwei Stränge: H1 und H2 (Modell) sowie H3 und H4 (Schalter). Der Schalter hängt bewusst nicht am neuen Modell, denn H1 darf mit
einem belegten Nein enden; der Haus-Modus läuft dann mit `gemma4-31b`, und H2 zieht die Karte später nach. H5 folgt nach H3, H6 nach H1. K1 nach M2 von KiKollege und
unabhängig von H3. Jedes Paket ist ein PR, mit
`verification-loop` vor dem PR und den Reviewern aus `CLAUDE.md` (Python, React, Datenbank, Sicherheit).

| Paket | Inhalt | Abhängig von | Stunden | Tests | Rollout | Rückweg |
| --- | --- | --- | --- | --- | --- | --- |
| **H0** Messrunde Bestand | M1 bis M4 mit den vorhandenen Modellen, eine Arbeitswoche Auslastung aus Prometheus | Labortag vorbei | 6 | keine neuen; Ergebnisdateien | nur Messung, kein Dienst | entfällt |
| **H1** Gesprächsmodell auf vLLM | Container auf Sokrates-2 mit `gemma-4-26B-A4B-it` FP8 (Prefix-Caching, Werkzeugparser, ohne MTP), Schlüssel aus Datei, Skript `infra/sokrates2/wamo-llm-einrichten.sh` mit `--trocken`, Rauchtest, Alias `wamo-gespraech` im zentralen Gateway; vorher die 84-GB-Codermodelle in der Karte sperren (L9); Messung M5 | H0, F2, F3 | 16 | Rauchtest (Probe ohne Inhalte), `test_*` für das Skript im Probelauf ohne root, `test_boss.py` und `test_modellkarte.py` für die Sperre, M5 | Skript am Server, Alias durch den Betreiber des Gateways | Alias entfernen (Boss nimmt `gemma4-31b`), Container stoppen, `wamo-llm-rueckweg.sh` |
| **H2** Karte, Boss, Warmhalten | Modellkarte aus H0 und H1, Hintergrundbausteine auf `qwen3.6-35b` mit JSON-Schema, Warmhalten des Gesprächsmodells | H1 | 8 | `test_modellkarte.py`, `test_boss.py`, `test_llm_anbieter.py`, `test_bewaehrung.py` | Kern-Release über Slots | Slot zurück; `WAMO_LLM_*` aus `core.env` entfernen |
| **H3** Schalter im Kern | L1, L2, L3, L10, L11, L12: Migration 0021 mit Rückweg, Selbsttest und SQL-Test, Quelle `betrieb`, Notschalter `WAMO_LLM_NUR_HAUS`, Schreibweg für den Admin nach F10, Claude-Code-Sperre, erweiterte Liste in `wamo-core-env` | H0, F10 | 24 | `test_modellzugang.py`, `test_modellzugang_api.py` (vorhanden, erweitern), `test_boss.py`, `test_bot_zugang.py`, `test_dev_agent*`, Tests zu `wamo_core_env.py`, neuer Test "kein Anthropic-Client", `supabase/tests/0021_*.sql` | `database-reviewer` und `security-reviewer`, Migration mit `psql -v ON_ERROR_STOP=1 --single-transaction` in `wamo_dev`, `wamo_test`, dann `wamo_prod` (zweimal anwenden), Kern-Release | Schalter aus oder Notschalter, Slot zurück, Migration `.down.sql` (der Kern liest die fehlende Tabelle als "aus") |
| **H4** Oberfläche | Abschnitt "Modelle im Betrieb" (Admin), Stimme in der Karte der Person, Hinweis in der Statusleiste | H3 | 12 | Vitest-Komponententests (Radiogruppe nach WAI-ARIA wie `ModellWahl`), `react-reviewer` | blau/grün mit `wamo-ui-umschalten.sh` | andere Farbe |
| **H5** Stimme im Haus als Option | Gateway-Einträge für Qwen3-ASR (`/audio/transcriptions`) und Qwen3-TTS (`/audio/speech`), Messung M7, Karte | H3, Betreiber des Gateways | 10 | `test_sprache_anbieter.py` erweitern, Rauchtest, M7 | Einträge am Gateway, `WAMO_STT_HAUS_MODELL`, `WAMO_TTS_HAUS_MODELL` und `WAMO_TTS_HAUS_STIMME` in `core.env` (erst nach L12 möglich), Kern-Neustart über einen Slot | Profilwert `soniox`; `WAMO_STT_ANBIETER=soniox` und `WAMO_TTS_ANBIETER=soniox` für alle |
| **H5b** Streaming-STT im Haus (optional) | Voxtral-Mini-4B-Realtime auf Sokrates-2, Pipecat-Dienst für `/v1/realtime`; klären, ob das Gateway Realtime durchreicht, sonst Ausnahme von der Hausregel (F8) | H5 | 20 | Einheitstests des Dienstes, M7 | Skript wie H1 | Dienst stoppen, Profilwert `soniox` |
| **H6** Entwicklungsaufträge im Haus | Spike (8 h): Claude Code über `/v1/messages` des Gateways gegen OpenCode oder Qwen Code, beide mit `qwen3.6-35b`, 8 Code-Aufgaben plus drei echte Aufgaben in einer Kopie; danach Umsetzung (24 h): Quelle `haus`, eine Ausnahme in `wamo-egress.nft` für das Gateway, eigener virtueller Gateway-Schlüssel mit Budget und Schwärzmuster (L7), Abnahme über die vorhandenen Prüfstufen | H1, H3, F5 | 32 | `test_dev_agent*`, `test_kernkanal_vertrag.py`, `test_job_kern_skripte.py`, `test_entwicklung_*` | Dispatcher-Version, Kern-Release | Quelle `haus` aus; der Claude-Weg bleibt unberührt |
| **K1** KiKollege V2 | siehe 4.5 und 4.6 | M2 von KiKollege, F7, L12 | 30 | Vertragstest, Fremdinhalt, Freigabe, Grenzen, Größen, keine Kette | Brücke auf Caesar (KiKollege), Kern-Release | Werkzeug über einen Schalter in `core.env` abschalten (Name nach L12), Zeile der Brücke in `authorized_keys` entfernen |

**Stand H5 (16.11.2026, Zweig `feat/stimme-im-haus`):** Messung M7 (2.5); Kern: Aktion `stimme` in `modellzugang.py` (Route
`/wamo/api/modellzugang` und Nachricht der Sitzung, 403 für Laborprofile, Zeile in `actions` mit dem Werkzeug `stimme_wahl`), Laborsitzung
immer Soniox, Grund einer Abweichung (Rückfall oder Vorgabe des Betriebs) als `sprache_grund` in `betrieb`, Feld `stimme_haus` im
Modellzugang (die Oberfläche sperrt "Im Haus", solange der Kern es nicht eingerichtet meldet), nur Modelle mit Hausnamen `wamo-...`,
Spracherkennung immer mit `response_format` json (sonst verlangt LiteLLM verbose_json, das Qwen3-ASR mit HTTP 400 ablehnt); Migration 0023 (Schreibrecht des Kerns nur auf `stt` und `tts`, mit
Rückweg und SQL-Test); `wamo-core-env` mit den fünf Namen; Oberfläche: Schalter "Soniox (Standard) | Im Haus (Datenschutz)" in der Karte
Modellzugang, eine Wahl für Hören und Stimme gemeinsam (die Zusage "Ton und Text bleiben in der Firma" gilt nur mit beidem; die Datenbank und
die Schnittstelle kennen beide Bausteine weiter einzeln). Offen am Server, je mit Nikos Ja: Migration 0023, Gateway-Einträge mit Neustart,
Deutsch als Rückfall im TTS-Dienst, `WAMO_STT_HAUS_MODELL`, `WAMO_TTS_HAUS_MODELL` und `WAMO_TTS_HAUS_STIMME` in `core.env`, Kern-Release,
danach M7 über das Gateway und Nikos Hörprobe.

**Summe W.A.I.S.:** H0 6 + H1 16 + H2 8 + H3 24 + H4 12 + H5 10 + H6 32 + K1 30 = **138 Stunden**, mit H5b **158 Stunden**. Dazu rund 10 Stunden auf Seite KiKollege
und die Zeit des Gateway-Betreibers für drei bis vier Einträge.

**Ausstiegskriterien je Paket (Kurzform):** H0 liefert Ergebnisdateien und einen Bericht; H1 besteht M5 oder endet mit einem belegten Nein (dann bleibt `gemma4-31b`);
H3 zeigt im Test, dass im Haus-Modus kein Anthropic-Client entsteht und der Notschalter ohne Datenbank wirkt; H4 zeigt in den Tests, dass Mitglieder den Abschnitt nicht
sehen; H5 besteht M7 und die Hörprobe; H6 schafft im Spike mindestens 7 von 8 und zwei von drei echten Aufgaben; K1 besteht den Vertragstest und den Sicherheitsreview.

**Nicht angefasst bis nach dem Labortag am 28.11.2026** (Ausnahme seit 16.11.2026: H5 nach Nikos Entscheidung, eingebaut, ohne Umstellung): Kern, Migrationen, Oberfläche, Dienste und Gateway; das Laborprofil und sein Modell (Haiku über den
Server-Schlüssel); `core.env`; Soniox-Einstellungen; die Modelle auf allen drei Sparks, auch keine Messläufe über das Gateway in der Woche vor dem Labortag. Erlaubt ist
nur dieses Papier.

## 6. Offene Entscheidungen für Niko

| Nr | Frage | Empfehlung |
| --- | --- | --- |
| F1 | Eigene Abnahmestufe für den Haus-Modus (Werkzeug 95 %, Marker 95 %, erstes Token p95 1,5 s, keine Muss-Verstöße, pass^3) statt der Latte für Claude? | Ja. Die heutige Latte reißt auch Haiku; ohne eigene Stufe gibt es nie eine Freigabe im Haus |
| F2 | Wo läuft das neue Gesprächsmodell, und wer trägt den Alias ins zentrale Gateway ein? | Sokrates-2 als eigener Container von W.A.I.S., Alias `wamo-gespraech` im zentralen Gateway nach Absprache mit dessen Betreiber. Kein eigenes Gateway (Hausregel) |
| F3 | Die beiden 84-GB-Codermodelle im Ollama auf Sokrates-2 und ein festes Gesprächsmodell passen nicht gleichzeitig in den Speicher. | Die Codermodelle dort nicht mehr laden; für Code `qwen3.6-35b` (laut Hersteller stärker als Coder-Next). Löschen nur mit dem Eigentümer |
| F4 | Gilt "Alles über Sokrates" auch für Laborprofile? | Nein. Das Labor bleibt bei seinem gemessenen Stand; eine Änderung dort nur mit eigener Messrunde |
| F5 | Agent für Entwicklungsaufträge im Haus: Claude Code über das Gateway oder ein offener Agent? | Erst der Spike H6. Vorab neige ich zu OpenCode oder Qwen Code, weil Anthropic den Weg über fremde Modelle nicht unterstützt \[30\] und das Gateway beim Denken der Modelle offene Fehler hat \[34\]\[36\] |
| F6 | Bleibt der Prüfer der Selbstüberarbeitung im Haus-Modus bei Claude? | Ja, als Betreiberfunktion ohne Personendaten, sichtbar im Abschnitt "Modelle im Betrieb". Eine Hausvariante erst nach H6 |
| F7 | KiKollege: Variante V2 mit Erwin besprechen und nach seinem M2 umsetzen? | Ja. Zuerst ein Termin zur Abstimmung (Brücke, Auftraggeberliste, Update auf 0.23.1), dann K1 |
| F8 | Streaming-STT im Haus (Voxtral, 16 GB auf Sokrates-2) installieren, auch wenn das Gateway Realtime nicht durchreicht? | Erst H5 mit Qwen3-ASR messen. H5b nur, wenn Niko die Stimme im Haus wirklich nutzen will; eine Ausnahme von der Hausregel nur für diesen einen Dienst |
| F9 | Hinweise an KiKollege (Dashboard im LAN, offener Statusendpunkt) und an den Betreiber des OCR-Dienstes (Schlüssel in der Prozessliste) weitergeben? | Ja, mündlich oder per Mail, ohne Werte; keine Änderung durch W.A.I.S. |
| F10 | Wie darf der Admin aus der Oberfläche `nur_haus`, Stimme und Modell eines Profils setzen, obwohl Migration 0010 das dem Kern bewusst verwehrt? | Eine `security definer`-Funktion in Migration 0021, die nur für ein Profil mit Rolle `admin` schreibt und jede Änderung protokolliert; Entscheidung als ADR, Review durch `database-reviewer` und `security-reviewer`. Keine pauschalen Spaltenrechte für `wamo_core` |

## 7. Quellen

**Im Haus (lesend, 15.11.2026):** `ollama list` und `ollama ps` auf allen drei Knoten, `docker ps`, Prozessliste mit geschwärzten Argumenten, `free -g`, `nvidia-smi`,
Modellliste der Gateway-Konfiguration ohne Schlüsselzeilen, Prometheus auf Sokrates-1 (`avg_over_time`, `quantile_over_time` über 7 Tage), Statusendpunkte des
Hermes-Dashboards, REA 6.8.0 `analyze-javascript-application`. Im Repository: die in den Abschnitten genannten Dateien und Zeilen.

**KiKollege:** Repository `Wamocon/kiKollege`, Stand 3709191 vom 13.11.2026: `README.md`, `UEBERGABE.md`, `AKTE-VORSCHLAG.md`, `data/projektstand.json`.

**Recherche (Stand 15.11.2026; M von Dritten gemessen, sonst Herstellerangabe oder Schätzung; Community-Werte hängen stark von Build und Schaltern ab):**

\[1\] https://gpuwerk.com/docs/benchmarks/ ,
\[2\] https://ai-muninn.com/en/blog/series/dgx-spark ,
\[3\] https://ai-muninn.com/en/blog/dgx-spark-gemma4-26b-nvfp4-52-toks ,
\[4\] https://huggingface.co/google/gemma-4-26B-A4B-it ,
\[5\] https://huggingface.co/Qwen/Qwen3.8-27B ,
\[8\] https://huggingface.co/Qwen/Qwen3.6-35B-A3B ,
\[9\] https://interfaze.ai/models/nvidianvidia-nemotron-35-lightning-30b-a3b-bf16 (keine Primärquelle gefunden),
\[10\] https://huggingface.co/openai/gpt-oss-120b ,
\[13\] https://github.com/vllm-project/vllm/issues/42696 ,
\[14\] https://github.com/vllm-project/vllm/issues/41967 ,
\[18\] https://arxiv.org/pdf/2509.14477v1 ,
\[19\] https://gpuwerk.com/dgx-spark/guides/choosing-inference-engine-llama-cpp-vllm-sglang/ ,
\[20\] https://huggingface.co/Hcompany/Holo4-35B-A3B ,
\[21\] https://aiweekly.co/alerts/h-company-ships-holo4-agents-27b-hits-617-on-osworld-20 ,
\[25\] https://docs.vllm.ai/en/latest/features/structured_outputs.html ,
\[26\] https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512 ,
\[30\] https://code.claude.com/docs/en/llm-gateway ,
\[34\] https://github.com/BerriAI/litellm/issues/32357 ,
\[36\] https://github.com/BerriAI/litellm/issues/30765 , https://github.com/BerriAI/litellm/issues/31279 , https://github.com/BerriAI/litellm/issues/39431 ,
\[40\] https://ai-muninn.com/en/blog/dgx-spark-nvfp4-trap-gb10-fp8-wins ,
\[41\] https://huggingface.co/Qwen/Qwen3-Coder-Next ,
\[43\] https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602 ,
\[45\] https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 ,
\[49\] https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice ,
\[50\] https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/speech_api/ ,
\[55\] https://huggingface.co/mistralai/Voxtral-4B-TTS-2603 ,
\[57\] https://github.com/NousResearch/hermes-agent/releases ,
\[58\] https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server ,
\[59\] https://safeguard.sh/resources/blog/hermes-agent-architecture-agent-loop-tools-terminal-backends-gateway-and-mcp ,
\[62\] https://hermes-agent.nousresearch.com/docs/user-guide/features/acp ,
\[63\] https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks ,
\[64\] https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard ,
\[66\] https://nvd.nist.gov/vuln/detail/CVE-2026-7113 ,
\[67\] https://neuraltrust.ai/blog/hermes-agent-security (Drittquelle).

**Arbeitsweise:** ECC-Skill `blueprint` für den Paketschnitt (ein PR je Paket, Abhängigkeiten, Rückweg, Ausstiegskriterien), eine Webrecherche als eigener Agent
nach dem Muster `search-first` und `deep-research`, ein unabhängiges Review dieses Papiers gegen den Code durch den Agenten `ecc:architect` (elf Befunde, alle eingearbeitet); REA für die Laufzeitsicht auf die
KiKollege-Instanz (Anmeldeskript; die Oberfläche hinter der Anmeldung blieb unberührt).
