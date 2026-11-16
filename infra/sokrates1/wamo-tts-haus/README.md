# Sprachausgabe im Haus: eigene Instanz `wamo-qwen3-tts` auf Sokrates-1

Eigener Container für W.A.I.S. mit Qwen3-TTS-12Hz-1.7B-CustomVoice (Apache 2.0) über faster-qwen3-tts 0.4.0 (MIT, CUDA-Graphen).
Der Kern erreicht ihn nur über das zentrale Gateway (Modell `wamo-tts-haus`, gestreamt über die Durchreiche `/wamo-tts-haus/v1/audio/speech`),
nie direkt. Der Container `qwen3-tts` (Port 8102) gehört nicht zu W.A.I.S. und bleibt unberührt.

`app.py` hier ist die Quelle der Datei `~/wamo-tts-haus/app.py` am Server. Sie wird als Datei in den Container gebunden; das Abbild
`qwen3-tts:new` bleibt unverändert.

## Was der Dienst kann

- `POST /v1/audio/speech` wie bisher (ganze Datei, `response_format` wav, pcm, mp3 und weitere über ffmpeg).
- Neu: mit `"stream": true` und `response_format` wav (oder pcm) kommt das Audio in Blöcken, sobald es erzeugt ist. Erster Block
  2 Frames (160 ms Audio), danach wachsend bis 6 Frames (`naechster_block`). WAV-Kopf ohne Längenangabe, Kopf und erster Block in
  einem Stück. Bricht der Aufrufer ab, endet die Erzeugung nach dem laufenden Frame und der Dienst ist sofort frei.
- Kopfzeilen der gestreamten Antwort: `X-Stream: 1`, `X-Sample-Rate`, `X-First-Audio-Seconds`, `X-Language`.
- Umgebung: `TTS_STANDARD_SPRACHE` (im Zweifel diese Sprache, hier `German`), `TTS_STREAM_ERSTER_BLOCK` (1 bis 24, Standard 2),
  `TTS_STREAM_BLOCK` (1 bis 48, Standard 6), `DEFAULT_SPEAKER` (Standard `aiden`). Für Messungen nimmt eine Anfrage auch
  `erster_block` und `block` (begrenzt).
- Ein Lock: immer nur eine Erzeugung zugleich; weitere Anfragen warten.

Messung am 16.11.2026 (direkt an der Instanz, je 20 Anfragen): erstes Audio p50 0,13 s, p95 0,14 s für kurze und normale Sätze;
ohne Streaming p50 0,57 bis 0,63 s (kurz) und 2,8 s (normal). Über eine LiteLLM 1.92.0 mit Durchreiche p50 0,14 s.

## Einsetzen

```bash
cd ~/wamo-tts-haus
cp -p app.py app.py.vorher.$(date +%Y%m%d-%H%M%S)   # Sicherung
cat /pfad/zur/neuen/app.py > app.py                 # Inhalt ersetzen (die Bindung zeigt auf diese Datei)
docker restart wamo-qwen3-tts                       # rund 30 s bis /health "ok": true meldet
curl -s http://172.17.0.1:8104/health
```

Der Neustart betrifft nur diesen Container. Während der rund 30 s fällt der Kern bei "Im Haus" mit einer Fehlermeldung je Satz aus;
deshalb außerhalb von Gesprächen.

## Start des Containers (falls er neu angelegt werden muss)

```bash
docker run -d --name wamo-qwen3-tts --restart unless-stopped --runtime nvidia --gpus all \
  -p 172.17.0.1:8104:8000 \
  -e TTS_STANDARD_SPRACHE=German -e HF_HUB_OFFLINE=1 \
  -v /home/wamocon/.cache/huggingface/hub:/models:ro \
  -v /home/wamocon/wamo-tts-haus/app.py:/app/app.py:ro \
  --log-opt max-size=100m --log-opt max-file=3 \
  qwen3-tts:new uvicorn app:app --host 0.0.0.0 --port 8000
```

Der Port liegt nur auf der Docker-Brücke (172.17.0.1); das Gateway erreicht ihn als `host.docker.internal:8104`.

## Rückweg

```bash
cd ~/wamo-tts-haus
cp -p app.py.vor-stream.20261116 app.py   # Stand vor dem Streaming (16.11.2026)
docker restart wamo-qwen3-tts
```

Im Kern zuerst `WAMO_TTS_HAUS_STREAM` auf `aus` stellen (über `wamo-core-env`), dann fragt er nur noch den Modellweg. Der alte Stand
kennt `"stream"` nicht und liefert dann einfach die ganze Datei; der Kern kommt mit beidem zurecht.
