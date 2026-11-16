"""qwen3-tts (eigene Instanz für W.A.I.S.): OpenAI-kompatibler /v1/audio/speech-Endpunkt für Qwen3-TTS-12Hz-1.7B-CustomVoice
(Apache-2.0) über faster-qwen3-tts (MIT, CUDA-Graphen). Abgeleitet vom PoC-Dienst vom 24.09.2026 (app.py.original am Server).

Stimmen: die 9 fest eingebauten CustomVoice-Sprecher des Modells (vivian, serena, uncle_fu, dylan, eric,
ryan, aiden, ono_anna, sohee). Laut Modellkarte kann jeder Sprecher alle 10 Sprachen sprechen, nativ ist
aber keiner deutsch oder russisch. Die Sprache wird aus dem Anfragefeld "language" genommen, sonst aus
der Schrift des Textes abgeleitet (kyrillisch -> Russian, sonst Deutsch-Hinweise -> German, sonst TTS_STANDARD_SPRACHE).

Streaming (16.11.2026): Mit "stream": true im Körper und response_format wav (oder pcm) liefert der Dienst das Audio in Blöcken,
sobald das Modell sie erzeugt (12,5 Codec-Frames je Sekunde Audio, 80 ms je Frame). Der erste Block ist klein (TTS_STREAM_ERSTER_BLOCK Frames), damit
der erste Ton früh kommt; danach wachsen die Blöcke im Anlauf bis TTS_STREAM_BLOCK (weniger Decoder-Aufwand, keine Lücke nach dem
ersten Ton, siehe naechster_block). WAV kommt mit einem
Kopf ohne Längenangabe (0xFFFFFFFF), Kopf und erster Block gehen in einem Stück. Ohne "stream" bleibt alles wie bisher (ganze Datei).
Bricht der Aufrufer ab (Unterbrechung im Gespräch), endet die Erzeugung nach dem laufenden Block und gibt die GPU frei.

Das Modell ist nicht für mehrere gleichzeitige Anfragen gebaut: ein Lock serialisiert die GPU-Nutzung."""
import asyncio, glob, logging, os, re, struct, subprocess, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.concurrency import run_in_threadpool

log = logging.getLogger("qwen3-tts")
logging.basicConfig(level=logging.INFO)

MODEL_DIR = glob.glob("/models/models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice/snapshots/*")
SPEAKERS = ["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"]
LANG_MAP = {"de": "German", "en": "English", "ru": "Russian", "fr": "French", "es": "Spanish", "it": "Italian",
            "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
DE_HINT = re.compile(r"[äöüßÄÖÜ]|\b(und|der|die|das|ist|nicht|ein|eine|ich|wir|sie|mit|für)\b", re.I)
DEFAULT_SPEAKER = os.environ.get("DEFAULT_SPEAKER", "aiden")
KONTEXT_FRAMES = 25  # wie faster-qwen3-tts: Vorlauf des Codec-Decoders für Folgeblöcke, damit die Übergänge sauber bleiben
MAX_ZEICHEN = 4000   # Schutz vor Endlosanfragen; der Kern schickt Sätze


def _int_env(name: str, standard: int, unten: int, oben: int) -> int:
    try:
        wert = int(os.environ.get(name, standard))
    except ValueError:
        wert = standard
    return max(unten, min(oben, wert))


ERSTER_BLOCK = _int_env("TTS_STREAM_ERSTER_BLOCK", 2, 1, 24)  # Frames bis zum ersten Ton (1 Frame = 80 ms Audio)
BLOCK = _int_env("TTS_STREAM_BLOCK", 6, 1, 48)                # Frames je Folgeblock

app = FastAPI(title="qwen3-tts")
MODEL = None
LOCK = threading.Lock()
STREAM_BEREIT = False
# Eigene Threads für gestreamte Erzeugungen: Wartende blockieren nicht den gemeinsamen Pool von asyncio
STREAM_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tts-stream")
STREAM_FRIST_SECS = 30.0  # längste Pause zwischen zwei Blöcken, danach gilt die Erzeugung als hängend


def _guess_language(text: str) -> str:
    if re.search(r"[Ѐ-ӿ]", text):
        return "Russian"
    return "German" if DE_HINT.search(text) else os.environ.get("TTS_STANDARD_SPRACHE", "English")  # W.A.I.S.: eigene Instanz mit German


def _wav_kopf(sr: int) -> bytes:
    """44 Byte WAV-Kopf (PCM 16 Bit mono) ohne bekannte Länge, für gestreamte Antworten."""
    unbekannt = 0xFFFFFFFF
    return (b"RIFF" + struct.pack("<I", unbekannt) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
            + b"data" + struct.pack("<I", unbekannt))


def _pcm16(audio) -> bytes:
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    return (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _decode(alle):
    """Codec-Frames in Audio wandeln (wie generate_custom_voice_streaming in faster-qwen3-tts)."""
    audio_list, sr = MODEL.speech_tokenizer.decode({"audio_codes": alle.unsqueeze(0)})
    audio = audio_list[0]
    audio = audio.flatten().cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio).reshape(-1)
    return audio, sr


def naechster_block(geliefert: int, block: int) -> int:
    """Anlauf: der nächste Block ist höchstens halb so lang wie das schon gelieferte Audio (2, 1, 1, 2, 3, 4, 6, 6 ... Frames bei
    erster Block 2, block 6). Bei rund 50 ms Rechenzeit je Frame (80 ms Audio) ist er dann fertig, bevor das Gelieferte abgespielt
    ist; gemessen bleiben mindestens rund 0,1 s Vorrat. Ein sofort großer zweiter Block ließe nach dem ersten Ton eine Lücke."""
    return max(1, min(block, geliefert // 2))


def _stream_bloecke(text: str, speaker: str, language: str, instruct: str | None, erster: int, block: int, stopp: threading.Event):
    """Erzeugt Audio-Blöcke (float32, sr): erst `erster` Frames, dann im Anlauf wachsend bis `block` Frames. Ruft der Aufrufer stopp.set(), endet die
    Erzeugung vor dem nächsten Frame. Nutzt die Bausteine von faster-qwen3-tts 0.4.0 (im Abbild fest), sonst deren öffentliche
    Streaming-Funktion mit fester Blockgröße."""
    import torch
    if not hasattr(MODEL, "_prepare_generation_custom"):
        gen = MODEL.generate_custom_voice_streaming(text=text, speaker=speaker, language=language, instruct=instruct or None,
                                                    chunk_size=erster)
        try:
            for audio, sr, _ in gen:
                if stopp.is_set():
                    return
                yield audio, sr
        finally:
            gen.close()
        return

    from faster_qwen3_tts.streaming import fast_generate_streaming
    with torch.inference_mode():
        MODEL.model._validate_languages([language])
        MODEL.model._validate_speakers([speaker])
        _m, talker, config, tie, tam, tth, tpe = MODEL._prepare_generation_custom(
            text=text, language=language, speaker=speaker, instruct=instruct or None, non_streaming_mode=True)
        gen = fast_generate_streaming(talker=talker, talker_input_embeds=tie, attention_mask=tam, trailing_text_hiddens=tth,
                                      tts_pad_embed=tpe, config=config, predictor_graph=MODEL.predictor_graph,
                                      talker_graph=MODEL.talker_graph, max_new_tokens=2048, min_new_tokens=2, temperature=0.9,
                                      top_k=50, top_p=1.0, do_sample=True, repetition_penalty=1.05, chunk_size=1)
        frames, neu, ziel, geliefert = [], 0, erster, 0
        bisher_samples, samples_je_frame = 0, None
        try:
            for codes, _timing in gen:
                if stopp.is_set():
                    return
                frames.append(codes)
                neu += codes.shape[0]
                if neu < ziel:
                    continue
                audio, sr, bisher_samples, samples_je_frame = _block_audio(frames, neu, bisher_samples, samples_je_frame)
                geliefert += neu
                neu, ziel = 0, naechster_block(geliefert, block)
                yield audio, sr
            if neu and not stopp.is_set():
                audio, sr, _, _ = _block_audio(frames, neu, bisher_samples, samples_je_frame)
                yield audio, sr
        finally:
            gen.close()


def _block_audio(frames: list, neu: int, bisher_samples: int, samples_je_frame: float | None):
    """Audio der letzten `neu` Frames. Bis genug Frames für das Kontextfenster da sind, wird alles von vorn dekodiert und der neue
    Teil abgeschnitten; danach nur ein Fenster mit KONTEXT_FRAMES Vorlauf (gleiches Verfahren wie faster-qwen3-tts)."""
    import torch
    alle = torch.cat(frames, dim=0)
    gesamt = alle.shape[0]
    if samples_je_frame is None:
        audio, sr = _decode(alle)
        neu_audio = audio[bisher_samples:]
        bisher_samples = len(audio)
        if gesamt >= KONTEXT_FRAMES:
            samples_je_frame = len(audio) / gesamt
        return neu_audio, sr, bisher_samples, samples_je_frame
    start = max(0, gesamt - neu - KONTEXT_FRAMES)
    fenster = alle[start:]
    audio, sr = _decode(fenster)
    vorlauf = fenster.shape[0] - neu
    if vorlauf > 0:
        audio = audio[int(round(vorlauf * samples_je_frame)):]
    return audio, sr, bisher_samples, samples_je_frame


@app.on_event("startup")
def load():
    global MODEL
    if not MODEL_DIR:
        raise RuntimeError("Qwen3-TTS-12Hz-1.7B-CustomVoice nicht im gemounteten HF-Cache gefunden")
    from faster_qwen3_tts import FasterQwen3TTS
    t = time.time()
    MODEL = FasterQwen3TTS.from_pretrained(MODEL_DIR[0], device="cuda", local_files_only=True)
    MODEL.warmup(prefill_len=100)                      # CUDA-Graphen einmalig beim Start aufnehmen
    # Ein echter kurzer Lauf über den Streaming-Weg wärmt Tokenizer und Codec-Decoder auf, damit die erste Anfrage nicht wartet.
    # Scheitert er (etwa eine geänderte Bibliothek), bleibt der Dienst ohne Streaming nutzbar: "stream" liefert dann die ganze Datei.
    global STREAM_BEREIT
    try:
        for _ in _stream_bloecke("Hallo, ich bin bereit.", DEFAULT_SPEAKER, "German", None, ERSTER_BLOCK, BLOCK, threading.Event()):
            pass
        STREAM_BEREIT = True
    except Exception:
        log.exception("Streaming nicht nutzbar, der Dienst liefert nur ganze Dateien")
    log.info("Modell geladen und aufgewärmt in %.1f s, Abtastrate %s, Streaming %s, erster Block %d, Folgeblock %d Frames",
             time.time() - t, MODEL.sample_rate, "an" if STREAM_BEREIT else "aus", ERSTER_BLOCK, BLOCK)


@app.get("/health")
def health():
    return {"ok": MODEL is not None, "speakers": SPEAKERS, "default_speaker": DEFAULT_SPEAKER,
            "stream": {"bereit": STREAM_BEREIT, "erster_block": ERSTER_BLOCK, "block": BLOCK}}


def _synthesize(text: str, speaker: str, language: str, instruct: str | None):
    with LOCK:
        t = time.time()
        audio_list, sr = MODEL.generate_custom_voice(text=text, speaker=speaker, language=language,
                                                     instruct=instruct or None)
        dt = time.time() - t
    audio = np.concatenate([np.asarray(a, dtype=np.float32).reshape(-1) for a in audio_list])
    return audio, sr, dt


def _block_wert(body: dict, feld: str, standard: int, oben: int) -> int:
    """Blockgröße aus der Anfrage (für Messungen), begrenzt; sonst der Standard aus der Umgebung."""
    wert = body.get(feld)
    if isinstance(wert, int) and not isinstance(wert, bool):
        return max(1, min(oben, wert))
    return standard


class _Strom(StreamingResponse):
    """StreamingResponse, die beim Ende der Antwort auf jedem Weg die Erzeugung stoppt: auch wenn der Aufrufer trennt, bevor der
    Körper überhaupt gelesen wird (dann läuft ein finally im Körper-Generator nie)."""

    def __init__(self, *args, stopp: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self._stopp = stopp

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._stopp.set()


def _lock_holen(stopp: threading.Event) -> bool:
    """Wartet auf den Lock, gibt aber auf, sobald der Aufrufer weg ist (stopp gesetzt)."""
    while not LOCK.acquire(timeout=0.1):
        if stopp.is_set():
            return False
    return True


async def _erstes(schlange: asyncio.Queue, request: Request, stopp: threading.Event):
    """Erstes Element der Schlange; trennt der Aufrufer vorher (Unterbrechung, auch während er auf den Lock wartet), None."""
    try:
        while True:
            try:
                return await asyncio.wait_for(schlange.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    stopp.set()
                    return None
    except BaseException:
        stopp.set()
        raise


async def _stream_antwort(request: Request, text: str, speaker: str, language: str, instruct: str | None, fmt: str, erster: int,
                          block: int):
    loop = asyncio.get_running_loop()
    schlange: asyncio.Queue = asyncio.Queue()
    stopp = threading.Event()
    ende = object()
    t0 = time.time()

    def arbeit():
        n_samples, sr, t_erst = 0, MODEL.sample_rate, None
        try:
            if not _lock_holen(stopp):
                return
            try:
                t_lock = time.time()
                for audio, sr in _stream_bloecke(text, speaker, language, instruct, erster, block, stopp):
                    if t_erst is None:
                        t_erst = time.time() - t0
                    n_samples += len(audio)
                    loop.call_soon_threadsafe(schlange.put_nowait, (_pcm16(audio), sr))
            finally:
                LOCK.release()
            log.info("%s/%s stream: %d Zeichen -> %.2f s Audio, Warten auf Lock %.3f s, erstes Audio %.3f s, gesamt %.2f s%s",
                     speaker, language, len(text), n_samples / sr, t_lock - t0, t_erst or 0.0, time.time() - t0,
                     " (abgebrochen)" if stopp.is_set() else "")
        except Exception as e:  # Fehler an die Antwort weitergeben statt still zu enden
            log.exception("Streaming-Erzeugung fehlgeschlagen")
            loop.call_soon_threadsafe(schlange.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(schlange.put_nowait, ende)

    loop.run_in_executor(STREAM_POOL, arbeit)
    erstes = await _erstes(schlange, request, stopp)
    if erstes is None:
        return Response(status_code=499)  # Aufrufer schon weg; niemand liest diese Antwort
    if isinstance(erstes, Exception):
        stopp.set()
        raise HTTPException(500, "Erzeugung fehlgeschlagen")
    t_erst = time.time() - t0
    sr = erstes[1] if erstes is not ende else MODEL.sample_rate

    async def koerper():
        kopf = _wav_kopf(sr) if fmt == "wav" else b""
        if erstes is ende:
            yield kopf
            return
        yield kopf + erstes[0]
        while True:
            try:
                teil = await asyncio.wait_for(schlange.get(), timeout=STREAM_FRIST_SECS)
            except asyncio.TimeoutError:
                raise RuntimeError("Erzeugung hängt") from None
            if teil is ende:
                return
            if isinstance(teil, Exception):
                # Verbindung unvollständig abbrechen: der Kopf nennt keine Länge, ein sauberes Ende sähe wie ein ganzer Satz aus
                raise RuntimeError("Erzeugung mitten im Strom fehlgeschlagen") from teil
            yield teil[0]

    media = "audio/wav" if fmt == "wav" else "audio/pcm"
    return _Strom(koerper(), stopp=stopp, media_type=media,
                  headers={"X-Language": language, "X-Stream": "1", "X-Sample-Rate": str(sr),
                           "X-First-Audio-Seconds": f"{t_erst:.3f}", "Cache-Control": "no-store"})


@app.post("/v1/audio/speech")
async def speech(request: Request):
    body = await request.json()
    text = (body.get("input") or "").strip()
    if not text:
        raise HTTPException(422, "input fehlt")
    if len(text) > MAX_ZEICHEN:
        raise HTTPException(422, "input zu lang")
    speaker = str(body.get("voice") or DEFAULT_SPEAKER).lower()
    if speaker not in SPEAKERS:
        speaker = DEFAULT_SPEAKER
    lang = body.get("language")
    language = LANG_MAP.get(str(lang).lower()[:2], None) if lang else None
    language = language or _guess_language(text)
    fmt = (body.get("response_format") or "mp3").lower()

    if body.get("stream") is True and fmt in ("wav", "pcm") and STREAM_BEREIT:
        return await _stream_antwort(request, text, speaker, language, body.get("instructions"), fmt,
                                     _block_wert(body, "erster_block", ERSTER_BLOCK, 24), _block_wert(body, "block", BLOCK, 48))

    audio, sr, dt = await run_in_threadpool(_synthesize, text, speaker, language, body.get("instructions"))
    log.info("%s/%s: %d Zeichen -> %.2f s Audio in %.2f s", speaker, language, len(text), len(audio) / sr, dt)

    with tempfile.NamedTemporaryFile(suffix=".wav") as src:
        sf.write(src.name, audio, sr, subtype="PCM_16")
        if fmt in ("wav", "pcm"):
            return Response(open(src.name, "rb").read(), media_type="audio/wav",
                            headers={"X-Synth-Seconds": f"{dt:.3f}", "X-Language": language})
        with tempfile.NamedTemporaryFile(suffix="." + fmt) as dst:
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src.name, dst.name], capture_output=True)
            if r.returncode != 0:
                raise HTTPException(500, "ffmpeg-Fehler: " + r.stderr.decode()[:300])
            data = open(dst.name, "rb").read()
    media = {"mp3": "audio/mpeg", "opus": "audio/opus", "flac": "audio/flac", "aac": "audio/aac"}.get(fmt, "audio/mpeg")
    return Response(data, media_type=media, headers={"X-Synth-Seconds": f"{dt:.3f}", "X-Language": language})
