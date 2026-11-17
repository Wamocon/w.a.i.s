# Betriebsnotiz: W.A.I.S. im zentralen Gateway auf Sokrates-1

**Stand:** 17.11.2026. Für Niko als Betreuer des zentralen LiteLLM-Gateways auf Sokrates-1. Diese Notiz enthält keine Schlüssel, keine Passwörter und keine Werte aus der Konfiguration. Die Werte stehen nur in der Konfiguration selbst und in der Umgebung des Gateway-Containers.

**Quellen:** `docs/hausmodelle-und-kikollege.md` (Abschnitte 2.5 und 2.6), `infra/sokrates1/wamo-tts-haus/README.md`, `docs/labor-restplan.md` (Nachtrag, Abschnitt N.5). Die Konfiguration des Gateways wurde für diese Notiz nicht gelesen. Die Angaben stammen aus dem Repo und aus den Messungen vom 16.11.2026.

## 1. Wo was liegt

| Was | Wo |
| --- | --- |
| Konfiguration des Gateways | Datei `litellm_config.yaml` im Gateway-Ordner auf Sokrates-1. Der vollständige Pfad steht in der Betreuer-Ablage, nicht im Repo |
| Gateway-Container | LiteLLM 1.92.0. Name und Startbefehl stehen in der Betreuer-Ablage |
| Sicherungen | Neben der Konfiguration, Dateinamen mit `.vor-wamo-…` und Zeitstempel. Vom 16.11.2026 sind es `.vor-wamo-haus-coder.20261116-081339`, `.vor-wamo-stimme.20261116-182624`, dazu `.vor-wamo-tts-instanz.*` und `.vor-wamo-stream.*` |
| Eigene Sprachausgabe | `wamo-qwen3-tts`, Quelle und Rückweg in `infra/sokrates1/wamo-tts-haus/` |

## 2. Die W.A.I.S.-Einträge

| Eintrag | Zweck | Ziel |
| --- | --- | --- |
| `wamo-haus-coder` | Modell für Entwicklungsaufträge im Haus | Ollama auf Sokrates-2 (`http://192.168.178.136:11434`), `options.num_ctx` 65536 |
| `wamo-stt-haus` | Spracherkennung im Haus | Qwen3-ASR auf Sokrates-1 (Port 8101), Adresse wie in der Konfiguration |
| `wamo-tts-haus` | Sprachausgabe im Haus | `host.docker.internal:8104`, die eigene Instanz `wamo-qwen3-tts` |

Durchreiche für die gestreamte Sprachausgabe (`general_settings.pass_through_endpoints`): Pfad `/wamo-tts-haus/v1/audio/speech`, Ziel `http://host.docker.internal:8104/v1/audio/speech`, `auth: true`. Der Modellweg `/v1/audio/speech` puffert die ganze Datei, nur die Durchreiche streamt (Hausmodelle-Papier, Abschnitt 2.6).

## 3. Schlüssel des Kerns

- Der Kern-Schlüssel hat den Alias `wamo`. In seinen Metadaten steht `allowed_passthrough_routes` mit dem Eintrag `/wamo-tts-haus`. Ohne diesen Eintrag weist die Durchreiche den Schlüssel mit 403 ab.
- Die Metadaten werden über die Admin-API (`POST /key/update`) gesetzt. Den Admin-Schlüssel liest man aus der Umgebung des Containers. Er gehört weder in diese Notiz noch in einen Befehl, der im Verlauf landet.
- Der Kern-Schlüssel wird in Notizen, Protokollen und im Chat nur als SHA-256 erwähnt, nie als Wert.
- Der Haus-Proxy hat einen eigenen virtuellen Schlüssel (`wamo-haus-proxy`). Er ist nie der Kern-Schlüssel und bleibt bei einer Änderung am Kern unberührt.

## 4. Neustarts und Prüfung

- Am 16.11.2026 wurde das Gateway mehrfach neu gestartet, jeweils nach einer Änderung der Einträge.
- Nach jedem Neustart prüfen:
  1. Der Gesundheitsweg des Gateways antwortet (`/health`).
  2. `/v1/models` mit dem Kern-Schlüssel zeigt `wamo-stt-haus` und `wamo-tts-haus`. Den Schlüssel aus der Umgebung des Kerns übergeben, nie in den Befehl schreiben.
  3. Eine gestreamte Probe an `/wamo-tts-haus/v1/audio/speech` (mit `stream` gesetzt) liefert Status 200 und die Kopfzeile `X-Stream: 1`. Die ersten Bytes kommen nach rund 0,15 Sekunden. Ein Schlüssel ohne den Eintrag bekommt 403.
- **Regel: kein Neustart des Gateways am Labortag.** Die Sperre gilt von Fr 27.11.2026 um 12:00 bis Sa 28.11.2026 abends (Restplan, N10).

## 5. Rückweg je Eintrag

- `wamo-haus-coder`: Modelleintrag entfernen, das Recht des Kern-Schlüssels auf dieses Modell zurücknehmen, die Sicherung `.vor-wamo-haus-coder.20261116-081339` zurücklegen, Neustart. Für Proxy und Kern gilt der Rückweg aus der Projektbeschreibung (`CLAUDE.md`, Eintrag Haus-Proxy).
- `wamo-stt-haus` und `wamo-tts-haus`: Vorher im Kern die Stimme im Haus abschalten (Profile zurück auf Soniox). Dann Eintrag entfernen oder die Sicherung zurücklegen, Neustart.
- Durchreiche: Block `pass_through_endpoints` entfernen, die Metadaten des Kern-Schlüssels bereinigen (`allowed_passthrough_routes` über `/key/update`), Neustart. Der Kern fällt bei 404, 401 oder 403 der Durchreiche selbst für 5 Minuten auf den Modellweg zurück (`DURCHREICHE_PAUSE_SECS`). Mit `WAMO_TTS_HAUS_STREAM=aus` über `wamo-core-env` schaltet er die gestreamte Ausgabe ganz ab.
- Instanz `wamo-qwen3-tts`: Rückweg nach `infra/sokrates1/wamo-tts-haus/README.md`. Vorher im Kern das Streaming abschalten.

## 6. Was nicht angefasst wird

- Der Container `qwen3-tts` auf Port 8102 gehört nicht zu W.A.I.S. Ein anderes Gerät nutzt ihn. Er darf nicht verändert werden.
- Die eigene Instanz `wamo-qwen3-tts` gehört zu W.A.I.S. Änderungen nur nach der Anleitung in `infra/sokrates1/wamo-tts-haus/README.md`.

## 7. Regeln für Änderungen

- Jede Änderung am Gateway braucht Nikos Ja. Sie wird in dieser Notiz nachgetragen, damit W.A.I.S. ihren Stand im Repo kennt (Restplan, Risiko R6).
- Vor jeder Änderung eine Sicherung der Konfiguration mit Zeitstempel im Gateway-Ordner anlegen.

---

WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn
