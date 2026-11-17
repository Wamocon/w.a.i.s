"""Spracherkennung (STT) und Sprachausgabe (TTS) je Sitzung: Soniox (Standard) oder im Haus über LiteLLM (Phase P5).

Wahl je Baustein, in dieser Reihenfolge:
  0. Laborsitzung: immer Soniox, ohne Ausnahme (Entscheidung F4 in docs/hausmodelle-und-kikollege.md). Weder die Wahl im
     Profil noch die Übersteuerung in der Umgebung gilt dort, das Gateway wird gar nicht gefragt.
  1. WAMO_STT_ANBIETER bzw. WAMO_TTS_ANBIETER (soniox | haus), wenn gesetzt: gilt für alle Sitzungen dieses Kerns,
     z. B. für Tests oder um bei einer Störung im Haus alle auf Soniox zu stellen.
  2. die Wahl des Profils (Modellzugang, Felder stt und tts, getrennt wählbar; dazu die Stimme im Haus, tts_stimme). Soniox gilt für alle Profile, unabhängig vom Modellzugang
     (Entscheidung D3 in docs/ausrollen-neue-nutzer.md): auch ein Profil ohne Claude-Zugang hört und spricht über Soniox.
     Die Person wählt selbst in der Oberfläche (modellzugang.stimme_setzen, Migration 0023), ein Admin über wamo_admin.py.
  3. sonst soniox.

Im Haus geht alles über das LiteLLM-Gateway (LITELLM_BASE_URL, LITELLM_API_KEY), nie direkt an die Knoten:
  * STT: /v1/audio/transcriptions mit WAMO_STT_HAUS_MODELL (OpenAI-kompatibel, ganze Äußerung nach dem Sprechende,
    keine Zwischenergebnisse, keine Sprechertrennung, keine Wortzeitstempel).
  * TTS: /v1/audio/speech mit WAMO_TTS_HAUS_MODELL und WAMO_TTS_HAUS_STIMME, Antwort als WAV (Abtastrate aus dem Kopf,
    wird auf die Ausgaberate umgerechnet). Ohne Wortzeitstempel: Die weiche Unterbrechung greift dann über die
    Zeitgrenze in soft_interrupt.py, die Untertitel kommen satzweise. Mit WAMO_TTS_HAUS_STREAM=an gestreamt über die
    Durchreiche /<modell>/v1/audio/speech des Gateways (HausTTSService), sonst ganze Datei je Satz.

Rückfall: Fehlt Modell, Schlüssel oder Adresse, ist das Gateway nicht erreichbar oder bietet es das Modell nicht an,
steht der Grund im Log und der Baustein nutzt Soniox. Die Oberfläche zeigt das am Namen ("Soniox (Rückfall)") und nennt den
Grund in einem Satz für Menschen (SprachWahl.grund, Feld sprache_grund in betrieb), ohne Namen aus der Umgebung.
Stand 16.11.2026: Das Gateway bietet noch kein Audiomodell an (Einträge vorbereitet, Messung M7 in
docs/hausmodelle-und-kikollege.md); "haus" fällt deshalb heute immer auf Soniox zurück.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from urllib.parse import quote
from dataclasses import dataclass

import httpx
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from llm_anbieter import litellm_basis, litellm_problem, litellm_problem_statisch
from satz_vor_werkzeug import SatzVorWerkzeugTTS

ANBIETER = ("soniox", "haus")
HAUS_TIMEOUT_SECS = 20.0  # eine Äußerung bzw. ein Satz; danach Fehler statt Hänger
# Steht immer vorn im Feld prompt der Spracherkennung im Haus. Befund 17.11.2026 am Server: Qwen3-ASR-1.7B hinter vLLM 0.22.1 übergeht
# language=de, ein deutscher Satz kam mit und ohne die Angabe als Niederländisch zurück ("Wie wordt het weer am Wachtenende in
# Ashbourne?"); mit einem deutschen Hinweissatz im prompt kam Deutsch. language=de geht trotzdem mit.
STT_HAUS_HINWEIS = "Die folgende Aufnahme ist auf Deutsch."
WAV_KOPF_BYTES = 44
# Antworten des Gateways, die heißen "Durchreiche nicht eingerichtet oder für diesen Schlüssel nicht frei": dann der Modellweg
DURCHREICHE_ABGELEHNT = frozenset({401, 403, 404})
DURCHREICHE_PAUSE_SECS = 300.0
_uhr = time.monotonic  # Zeitquelle der Pause, in Tests ersetzbar (asyncio nutzt time.monotonic selbst)

# Gründe eines Rückfalls für die Oberfläche: kurze Sätze ohne Namen aus der Umgebung, ohne Adressen (anzeige_grund)
GRUND_EINRICHTUNG = "im Kern noch nicht eingerichtet"
GRUND_MODELL = "das Gateway bietet das Sprachmodell noch nicht an"
GRUND_GATEWAY = "das Gateway ist gerade nicht erreichbar oder meldet einen Fehler"
GRUND_SONST = "im Haus gerade nicht nutzbar"
GRUND_BETRIEB_SONIOX = "vom Betrieb für alle auf Soniox gestellt"
GRUND_BETRIEB_HAUS = "vom Betrieb für alle auf Im Haus gestellt"
# Nur Aliase mit Hausnamen gelten als Modell im Haus: ein Alias des Gateways auf einen Cloud-Dienst bekäme sonst Audio und Text
# unter dem Namen "Im Haus" (Sicherheitsreview 16.11.2026). Die Einträge heißen wamo-stt-haus und wamo-tts-haus.
HAUS_MODELL_RE = re.compile(r"wamo-[a-z0-9][a-z0-9-]{0,40}")
# Stimmen der Sprachausgabe im Haus, die eine Person wählen darf: genau diese Liste, an dieser einen Stelle (Entscheidung von Niko vom
# 16.11.2026 nach den Hörproben aus Messung M7, docs/hausmodelle-und-kikollege.md). Reihenfolge wie in der Oberfläche, die erste ist der
# Standard, wenn WAMO_TTS_HAUS_STIMME keine dieser Stimmen nennt. Eine weitere Stimme ist eine Zeile hier (Kennung, Name, Hinweis); der Kern
# lehnt alles andere ab (modellzugang.haus_stimme_setzen) und spricht nie mit einer anderen Stimme (sprach_wahl, haus_tts). Der Dienst kennt
# neun Stimmen, keine ist nativ deutsch. Spalte tts_stimme (Migration 0024), NULL heißt Standard.
HAUS_STIMMEN: tuple[tuple[str, str, str], ...] = (
    ("sohee", "Sohee", "am schnellsten gemessen, fehlerfrei zurückgelesen"),
    ("uncle_fu", "Uncle Fu", ""),
    ("ono_anna", "Ono Anna", ""),
)
HAUS_STIMMEN_IDS: tuple[str, ...] = tuple(s[0] for s in HAUS_STIMMEN)
STIMMEN_HINWEIS = "Keine der Stimmen ist nativ deutsch; sie sprechen Deutsch mit Akzent."


def haus_stimmen() -> list[dict[str, str]]:
    """Die wählbaren Stimmen im Haus für die Oberfläche (Kennung, Name, Hinweis), in der festgelegten Reihenfolge."""
    return [{"id": k, "name": n, "hinweis": h} for k, n, h in HAUS_STIMMEN]


def stimme_normal(wert: object) -> str | None:
    """Kennung einer freigegebenen Stimme (Kleinschreibung, ohne Leerraum) oder None."""
    w = wert.strip().lower() if isinstance(wert, str) else ""
    return w if w in HAUS_STIMMEN_IDS else None


def haus_stimme_standard() -> str:
    """Stimme ohne Wahl der Person: WAMO_TTS_HAUS_STIMME, wenn sie freigegeben ist, sonst die erste der Liste. So spricht die Sitzung nie
    mit einer Stimme außerhalb der Liste, und die Oberfläche zeigt denselben Standard, mit dem gesprochen wird."""
    return stimme_normal(_env("WAMO_TTS_HAUS_STIMME")) or HAUS_STIMMEN_IDS[0]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def gewuenscht(baustein: str, profil_wert: str | None = None) -> str:
    """Gewünschter Anbieter für "stt" oder "tts": Umgebung vor Profil vor Standard (soniox)."""
    umgebung = _env(f"WAMO_{baustein.upper()}_ANBIETER").lower()
    if umgebung in ANBIETER:
        return umgebung
    if umgebung:
        logger.warning("WAMO_{}_ANBIETER={!r} unbekannt (soniox oder haus), nutze die Wahl des Profils", baustein.upper(), umgebung)
    wert = (profil_wert or "").strip().lower()
    return wert if wert in ANBIETER else "soniox"


def anzeige_grund(problem: str | None) -> str | None:
    """Grund eines Rückfalls als kurzer Satz für die Person. Der technische Grund (Namen aus der Umgebung, Modell) steht nur im Log."""
    if not problem:
        return None
    if (problem.endswith("fehlt") or problem.startswith(("LITELLM_", "WAMO_")) or problem == "kein Modell gesetzt"
            or "Schlüssel" in problem):
        return GRUND_EINRICHTUNG
    if "bietet das Modell" in problem:
        return GRUND_MODELL
    if "Gateway" in problem:
        return GRUND_GATEWAY
    return GRUND_SONST


@dataclass(frozen=True)
class Baustein:
    gewuenscht: str  # soniox | haus
    anbieter: str  # wirksam: soniox | haus
    modell: str | None = None
    problem: str | None = None  # Grund für den Rückfall
    uebersteuert: bool = False  # WAMO_STT_ANBIETER bzw. WAMO_TTS_ANBIETER weicht von der Wahl des Profils ab
    stimme: str | None = None  # nur tts im Haus: Wahl der Person (HAUS_STIMMEN), sonst haus_stimme_standard()

    @property
    def rueckfall(self) -> bool:
        return self.gewuenscht == "haus" and self.anbieter == "soniox"


@dataclass(frozen=True)
class SprachWahl:
    stt: Baustein
    tts: Baustein

    def anzeige(self, soniox_stimme: str) -> dict[str, str]:
        """Namen für die Oberfläche (betrieb.modelle.stt/tts)."""
        def name(b: Baustein, soniox: str) -> str:
            if b.anbieter == "haus":
                return f"Haus ({b.modell})"
            return f"{soniox} (Rückfall)" if b.rueckfall else soniox
        return {"stt": name(self.stt, "Soniox"), "tts": name(self.tts, f"Soniox {soniox_stimme}")}

    @property
    def im_haus(self) -> bool:
        return self.stt.anbieter == "haus" and self.tts.anbieter == "haus"

    def grund(self) -> str | None:
        """Warum die Sitzung trotz Wahl "haus" über Soniox hört oder spricht (Feld sprache_grund in betrieb), sonst None."""
        def grund(b: Baustein) -> str | None:
            if b.rueckfall:
                return anzeige_grund(b.problem) or GRUND_SONST
            if b.uebersteuert:
                return GRUND_BETRIEB_HAUS if b.anbieter == "haus" else GRUND_BETRIEB_SONIOX
            return None

        gruende = {name: g for name, b in (("Spracherkennung", self.stt), ("Sprachausgabe", self.tts)) if (g := grund(b))}
        if not gruende:
            return None
        if len(gruende) == 2 and len(set(gruende.values())) == 1:
            return f"Spracherkennung und Sprachausgabe: {next(iter(gruende.values()))}"
        return "; ".join(f"{name}: {grund}" for name, grund in gruende.items())


def _problem_statisch(baustein: str, *, gateway: bool = True) -> str | None:
    """Was ohne Netz schon feststeht: Modell gesetzt und mit Hausnamen, Stimme gesetzt (nur tts), mit gateway auch Adresse und
    Schlüssel des Gateways (die prüft in der Sitzung litellm_problem selbst)."""
    name = f"WAMO_{baustein.upper()}_HAUS_MODELL"
    modell = _env(name)
    if not modell:
        return f"{name} fehlt"
    if not HAUS_MODELL_RE.fullmatch(modell):
        return f"{name} ist kein Hausmodell (wamo-...)"
    if baustein == "tts" and not _env("WAMO_TTS_HAUS_STIMME"):
        return "WAMO_TTS_HAUS_STIMME fehlt"
    return litellm_problem_statisch(modell) if gateway else None


def haus_problem_statisch() -> str | None:
    """Erster Grund, warum Hören und Stimme im Haus in diesem Kern gar nicht gehen können (ohne Netz), sonst None. Für die Karte
    Modellzugang (Feld stimme_haus), bevor eine Person "Im Haus" wählt."""
    return _problem_statisch("stt") or _problem_statisch("tts")


async def _baustein(baustein: str, profil_wert: str | None, stimme: str | None = None) -> Baustein:
    wunsch = gewuenscht(baustein, profil_wert)
    profil = (profil_wert or "").strip().lower()
    uebersteuert = _env(f"WAMO_{baustein.upper()}_ANBIETER").lower() in ANBIETER and wunsch != (profil if profil in ANBIETER else "soniox")
    if wunsch == "soniox":
        return Baustein("soniox", "soniox", uebersteuert=uebersteuert)
    modell = _env(f"WAMO_{baustein.upper()}_HAUS_MODELL")
    problem = _problem_statisch(baustein, gateway=False)
    if not problem:
        problem = await litellm_problem(modell)
    if problem:
        logger.error("{} im Haus nicht nutzbar ({}), Rückfall auf Soniox", baustein.upper(), problem)
        return Baustein("haus", "soniox", modell or None, problem, uebersteuert=uebersteuert)
    logger.info("{} im Haus über LiteLLM: {}", baustein.upper(), modell)
    if baustein != "tts":
        return Baustein("haus", "haus", modell, uebersteuert=uebersteuert)
    # Nur eine Stimme aus der festen Liste; alles andere (auch ein Wert aus einer alten Zeile) heißt Standard
    return Baustein("haus", "haus", modell, uebersteuert=uebersteuert, stimme=stimme_normal(stimme) or haus_stimme_standard())


async def sprach_wahl(zugang: object | None = None, *, labor: bool = False) -> SprachWahl:
    """Wahl für eine Sitzung. zugang: Modellzugang des Profils (Attribute stt und tts), fehlt er, gilt die Umgebung.
    labor: Laborsitzung (bot.py, labor_sitzung); dann gilt immer Soniox, ohne Umgebung, Profil und Gateway (F4)."""
    if labor:
        return SprachWahl(stt=Baustein("soniox", "soniox"), tts=Baustein("soniox", "soniox"))
    return SprachWahl(
        stt=await _baustein("stt", getattr(zugang, "stt", None)),
        tts=await _baustein("tts", getattr(zugang, "tts", None), getattr(zugang, "tts_stimme", None)),
    )


class HausSTTService(OpenAISTTService):
    """STT im Haus über LiteLLM (/audio/transcriptions). Schickt immer response_format json: Ohne Angabe fordert LiteLLM von sich
    aus verbose_json an, und Qwen3-ASR lehnt das mit HTTP 400 ab (Befund über das Gateway vom 16.11.2026)."""

    async def _transcribe(self, audio: bytes):
        anfrage: dict = {
            "file": ("audio.wav", audio, "audio/wav"),
            "model": self._settings.model,
            "language": self._settings.language,
            "response_format": "json",
        }
        if self._settings.prompt:
            anfrage["prompt"] = self._settings.prompt
        return await self._client.audio.transcriptions.create(**anfrage)


def stt_haus_prompt(begriffe: list[str]) -> str:
    """Hinweis für die Spracherkennung im Haus: immer erst der deutsche Satz (STT_HAUS_HINWEIS), dann die Fachbegriffe wie bei Whisper."""
    return f"{STT_HAUS_HINWEIS} {', '.join(begriffe)}" if begriffe else STT_HAUS_HINWEIS


def haus_stt(b: Baustein, begriffe: list[str]) -> HausSTTService:
    """STT im Haus: OpenAI-kompatibel über LiteLLM; vorn der deutsche Hinweissatz, dahinter die Fachbegriffe (prompt)."""
    return HausSTTService(
        api_key=_env("LITELLM_API_KEY"),
        base_url=litellm_basis(),
        settings=OpenAISTTService.Settings(
            model=b.modell,
            language=Language.DE,
            prompt=stt_haus_prompt(begriffe),
        ),
    )


def tts_stream_an() -> bool:
    """WAMO_TTS_HAUS_STREAM=an: Sprachausgabe gestreamt über die Durchreiche des Gateways (Standard aus)."""
    return _env("WAMO_TTS_HAUS_STREAM").lower() == "an"


def litellm_wurzel(basis: str) -> str:
    """Adresse des Gateways ohne /v1: Durchreichen (pass_through_endpoints) liegen an der Wurzel, nicht unter /v1."""
    basis = basis.rstrip("/")
    return basis[: -len("/v1")] if basis.endswith("/v1") else basis


async def _mit_ganzem_kopf(stuecke: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Hält die ersten Bytes zurück, bis der 44-Byte-Kopf einer WAV vollständig ist. Pipecat liest die Abtastrate nur aus einem
    ersten Stück mit mindestens 44 Byte; über das Netz kann ein gestreamter Kopf zerteilt ankommen."""
    anfang: bytes | None = b""
    async for stueck in stuecke:
        if anfang is None:
            yield stueck
            continue
        anfang += stueck
        if len(anfang) >= WAV_KOPF_BYTES:
            yield anfang
            anfang = None
    if anfang:
        yield anfang


class HausTTSService(SatzVorWerkzeugTTS, TTSService):
    """TTS im Haus über LiteLLM (WAV, satzweise, ohne Wortzeitstempel).

    Beginnt ein Werkzeugaufruf (satz_vor_werkzeug.py), geht der Rest des Satz-Aggregators sofort als eigene Anfrage hinaus. Einen
    Stream, der Text zurückhält, gibt es hier nicht: jeder Satz ist eine eigene Anfrage (stream_vor_werkzeug_beenden bleibt aus).

    Zwei Wege, beide über das Gateway (Hausregel):
      * Modellweg /v1/audio/speech: LiteLLM 1.92.0 holt dort die ganze Datei, bevor es das erste Byte weitergibt (das Feld stream
        reicht es nicht durch). Erstes Audio = Gesamtdauer des Satzes.
      * Durchreiche /<modell>/v1/audio/speech mit "stream": true (WAMO_TTS_HAUS_STREAM=an): ein pass_through_endpoint des Gateways
        mit auth, der den Strom des Dienstes Stück für Stück weitergibt. Erstes Audio nach rund 0,14 s, unabhängig von der Satzlänge;
        bricht die Sitzung ab (Unterbrechung), endet die Erzeugung im Dienst sofort und gibt ihn für den nächsten Satz frei.
    Lehnt das Gateway die Durchreiche ab (404 nicht eingerichtet, 401 oder 403 Schlüssel ohne allowed_passthrough_routes), geht
    derselbe Satz über den Modellweg, und für DURCHREICHE_PAUSE_SECS nutzen alle Sitzungen dieses Kerns nur den Modellweg."""

    durchreiche_pause_bis: float = 0.0  # time.monotonic(); gemeinsam für alle Sitzungen dieses Kerns

    def __init__(self, *, modell: str, stimme: str, basis: str | None = None, schluessel: str | None = None,
                 client: httpx.AsyncClient | None = None, stream: bool | None = None, **kwargs):
        # Vollständige Einstellungen aus der eigenen Konfiguration (Pipecat prüft beim Start jeder Sitzung, ob keine fehlt, sonst
        # "TTSSettings: the following fields are NOT_GIVEN"). language None: die Anfrage nennt keine Sprache (der Dienst im Haus hat
        # seine eigene), und Pipecat trennt die Sätze wie bisher ohne Sprachangabe.
        kwargs.setdefault("settings", TTSSettings(model=modell, voice=stimme, language=None))
        super().__init__(push_text_frames=True, push_start_frame=True, push_stop_frames=True, **kwargs)
        self._modell = modell
        self._stimme = stimme
        self._basis = (basis or litellm_basis()).rstrip("/")
        self._schluessel = schluessel if schluessel is not None else _env("LITELLM_API_KEY")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(HAUS_TIMEOUT_SECS, connect=3.0))
        self.stream = tts_stream_an() if stream is None else stream

    def can_generate_metrics(self) -> bool:
        return True

    async def cleanup(self):
        await super().cleanup()
        await self._client.aclose()

    def _wege(self, anfrage: dict) -> list[tuple[str, dict]]:
        """Adresse und Körper je Versuch: erst die Durchreiche (wenn an und nicht pausiert), dann der Modellweg."""
        wege = []
        if self.stream and _uhr() >= HausTTSService.durchreiche_pause_bis:
            pfad = quote(self._modell, safe="")
            wege.append((f"{litellm_wurzel(self._basis)}/{pfad}/v1/audio/speech", {**anfrage, "stream": True}))
        wege.append((f"{self._basis}/audio/speech", anfrage))
        return wege

    async def run_tts(self, text: str, context_id: str) -> AsyncIterator[Frame | None]:
        anfrage = {"model": self._modell, "input": text, "voice": self._stimme, "response_format": "wav"}
        kopf = {"Authorization": f"Bearer {self._schluessel}"}
        wege = self._wege(anfrage)
        try:
            for nr, (adresse, koerper) in enumerate(wege, start=1):
                async with self._client.stream("POST", adresse, json=koerper, headers=kopf) as r:
                    if r.status_code in DURCHREICHE_ABGELEHNT and nr < len(wege):
                        await r.aread()
                        HausTTSService.durchreiche_pause_bis = _uhr() + DURCHREICHE_PAUSE_SECS
                        logger.error("{}: Durchreiche für gestreamte Sprachausgabe abgelehnt (HTTP {}), {} s nur über den Modellweg",
                                     self, r.status_code, int(DURCHREICHE_PAUSE_SECS))
                        continue
                    if r.status_code != 200:
                        await r.aread()
                        logger.error("{}: Sprachausgabe im Haus fehlgeschlagen (HTTP {})", self, r.status_code)
                        yield ErrorFrame(error=f"Sprachausgabe im Haus: HTTP {r.status_code}")
                        return
                    await self.start_tts_usage_metrics(text)
                    async with aclosing(_mit_ganzem_kopf(r.aiter_bytes())) as stuecke, aclosing(
                        self._stream_audio_frames_from_iterator(stuecke, strip_wav_header=True, context_id=context_id)
                    ) as frames:
                        async for frame in frames:
                            await self.stop_ttfb_metrics()
                            yield frame
                    return
        except httpx.HTTPError as e:
            logger.error("{}: Sprachausgabe im Haus nicht erreichbar ({})", self, type(e).__name__)
            yield ErrorFrame(error=f"Sprachausgabe im Haus nicht erreichbar ({type(e).__name__})")


def haus_tts(b: Baustein) -> HausTTSService:
    return HausTTSService(modell=b.modell or "", stimme=stimme_normal(b.stimme) or haus_stimme_standard())
