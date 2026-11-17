"""Tests für den Satz vor dem Werkzeug (satz_vor_werkzeug.py): Text, den Claude vor einem Werkzeugaufruf sagt, geht sofort an die
Sprachausgabe; Soniox bekommt text_end, bevor die Argumente des Werkzeugs fertig sind (Befund Lasttest-Vorstufe 17.11.2026).

Claude läuft als echter Dienst der Fabrik mit einer Attrappe des Antwortstroms (Ereignisse wie im Anthropic-SDK), Soniox als echter
LazySonioxTTSService mit einer Attrappe des Websockets, die jede Nachricht protokolliert und auf text_end wie Soniox antwortet (Ton,
Wortzeiten, terminated). Die Sprachausgabe im Haus läuft mit einem Gateway aus httpx.MockTransport."""

from __future__ import annotations

import asyncio
import io
import json
import wave
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
from websockets.protocol import State

import llm_anbieter as la
import sprache_anbieter as sa
from satz_vor_werkzeug import SatzVorWerkzeugFrame, SatzVorWerkzeugLLM, SatzVorWerkzeugTTS, gesprochener_text, tts_vor_werkzeug_an
from soniox_tts import LazySonioxTTSService

from pipecat.frames.frames import (
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.tts_service import TTSService
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_turn_completion_mixin import UserTurnCompletionConfig

USER = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
EINLEITUNG = "Ich zeige dir die Stories."
ARGUMENTE = ['{"titel": "Stories", ', '"inhalt": "', *[f"Story {i}: Als Nutzer möchte ich mich anmelden. " for i in range(1, 6)], '"}']


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch):
    for name in ("WAMO_TTS_VOR_WERKZEUG", "WAMO_TTS_START_ZEICHEN", "WAMO_TTS_SATZLEERZEICHEN", "WAMO_MARKER_FALLBACK"):
        monkeypatch.delenv(name, raising=False)


async def bis(bedingung, frist: float = 3.0) -> None:
    ende = asyncio.get_running_loop().time() + frist
    while not bedingung():
        if asyncio.get_running_loop().time() > ende:
            raise AssertionError("Bedingung nicht erreicht")
        await asyncio.sleep(0.01)


async def fertig(lauf: asyncio.Task, tor: asyncio.Event):
    """Strom freigeben und die Pipeline zu Ende laufen lassen, auch wenn eine Prüfung vorher scheiterte (kein hängender Test)."""
    tor.set()
    return await asyncio.wait_for(lauf, 15)


# --- Attrappe des Antwortstroms von Claude ---------------------------------------------------------------------------------


def text(t: str, index: int = 0):
    return SimpleNamespace(type="content_block_delta", index=index, delta=SimpleNamespace(type="text_delta", text=t))


def block_text(index: int = 0):
    return SimpleNamespace(type="content_block_start", index=index, content_block=SimpleNamespace(type="text", text=""))


def block_werkzeug(index: int = 1, kennung: str = "toolu_1", name: str = "canvas_zeigen"):
    return SimpleNamespace(type="content_block_start", index=index,
                           content_block=SimpleNamespace(type="tool_use", id=kennung, name=name, input={}))


def argumente(teil: str, index: int = 1):
    return SimpleNamespace(type="content_block_delta", index=index, delta=SimpleNamespace(type="input_json_delta", partial_json=teil))


def block_ende(index: int):
    return SimpleNamespace(type="content_block_stop", index=index)


def stopp(grund: str = "tool_use"):
    return SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason=grund), usage=SimpleNamespace(output_tokens=12))


def werkzeug(index: int, kennung: str = "toolu_1") -> list:
    return [block_werkzeug(index, kennung), *[argumente(a, index) for a in ARGUMENTE], block_ende(index)]


def antwort_mit_werkzeug(*texte: str) -> list:
    """Wie im Befund: optional ein Einleitungstext, danach ein Werkzeugaufruf mit langen Argumenten."""
    vorne = [block_text(0), *[text(t) for t in texte], block_ende(0)] if texte else []
    return [*vorne, *werkzeug(len(vorne) and 1), stopp()]


def nur_text(*texte: str) -> list:
    return [block_text(0), *[text(t) for t in texte], block_ende(0), stopp("end_turn")]


class Strom:
    """Antwortstrom wie beim Anthropic-SDK. tor hält ihn vor dem Ereignis mit dem Index tor_vor an (die Argumente entstehen noch)."""

    def __init__(self, ereignisse: list, tor: asyncio.Event | None = None, tor_vor: int | None = None):
        self._ereignisse, self._tor, self._tor_vor = ereignisse, tor, tor_vor

    def __aiter__(self):
        return self._lauf()

    async def _lauf(self):
        for i, ereignis in enumerate(self._ereignisse):
            if self._tor is not None and i == self._tor_vor:
                await self._tor.wait()
            yield ereignis
            await asyncio.sleep(0)


def claude(*antworten: list, tor: asyncio.Event | None = None, tor_vor: int | None = None, satzende_filter: bool = True):
    """Echter Claude-Dienst der Fabrik; jede Anfrage bekommt die nächste Antwort aus antworten."""
    zugang = la.Zugang(USER, "claude", "profil", claude_schluessel="sk-ant-api03-PROFILeins-0123456789abcdefghijkl")
    d = la.gespraech_dienst(la.Wahl("gespraech", "claude", "claude-haiku-5-5", "claude"), "sys", zugang)
    reihe = iter(antworten)

    async def create(**params):
        return Strom(next(reihe), tor, tor_vor)

    d._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    if satzende_filter:  # wie im Gespräch: Satzende-Marker ●, ◐, ○ (bot.py)
        d._filter_incomplete_user_turns = True
        d.set_user_turn_completion_config(UserTurnCompletionConfig())
    return d


def kontext() -> LLMContextFrame:
    return LLMContextFrame(LLMContext(messages=[{"role": "user", "content": "Leg bitte fünf Stories im Canvas an."}]))


def vor_werkzeug(frames) -> list:
    return [f for f in frames if isinstance(f, SatzVorWerkzeugFrame)]


# --- Attrappe des Soniox-Websockets --------------------------------------------------------------------------------------


class SonioxAttrappe:
    """Protokolliert jede Nachricht an Soniox. Auf text_end antwortet sie wie Soniox (_receive_messages): Ton, Wortzeiten,
    terminated. verzoegerung: so lange braucht Soniox für die Antwort."""

    def __init__(self, dienst: LazySonioxTTSService, log: list, verzoegerung: float = 0.0):
        self.state = State.OPEN
        self._dienst, self._log, self._verzoegerung = dienst, log, verzoegerung
        self._texte: dict[str, str] = {}
        self._antworten: list[asyncio.Task] = []

    async def send(self, nachricht: str):
        m = json.loads(nachricht)
        self._log.append(m)
        sid = m.get("stream_id")
        if "text" in m:
            self._texte[sid] = self._texte.get(sid, "") + m["text"]
        if m.get("text_end"):
            self._antworten.append(asyncio.get_running_loop().create_task(self._antworten_fuer(sid)))

    async def _antworten_fuer(self, sid: str):
        await asyncio.sleep(self._verzoegerung)
        d = self._dienst
        if not d.audio_context_available(sid):
            return  # unterbrochen
        await d.append_to_audio_context(sid, TTSAudioRawFrame(b"\x00\x00" * 480, d.sample_rate, 1, context_id=sid))
        woerter = self._texte.get(sid, "").split()
        await d.add_word_timestamps([(w, 0.02 * i) for i, w in enumerate(woerter)], sid)
        await d.append_to_audio_context(sid, TTSStoppedFrame(context_id=sid))
        await d.remove_audio_context(sid)
        d._configured_contexts.discard(sid)

    async def close(self):
        self.state = State.CLOSED


class ProtokollSoniox(LazySonioxTTSService):
    """Notiert im selben Protokoll, wann das Antwortende die Sprachausgabe erreicht."""

    def __init__(self, log: list, **kwargs):
        super().__init__(**kwargs)
        self.log = log

    async def process_frame(self, frame, direction):
        if isinstance(frame, LLMFullResponseEndFrame):
            self.log.append("ende")
        await super().process_frame(frame, direction)


def soniox(log: list, *, start: int | None = None, verzoegerung: float = 0.0) -> ProtokollSoniox:
    d = ProtokollSoniox(log, api_key="x", sample_rate=24000, start=start)
    d._connect = mock.AsyncMock()  # kein Netz: die Attrappe ist der Websocket
    d._disconnect = mock.AsyncMock()
    d._websocket = SonioxAttrappe(d, log, verzoegerung)
    return d


def kurz(log: list) -> list:
    """Das Protokoll kurz: ("config", stream), ("text", stream, text), ("text_end", stream), ("cancel", stream) und "ende"."""
    out: list = []
    for e in log:
        if e == "ende":
            out.append("ende")
        elif "api_key" in e:
            out.append(("config", e["stream_id"]))
        elif e.get("cancel"):
            out.append(("cancel", e["stream_id"]))
        elif e.get("text_end"):
            out.append(("text_end", e["stream_id"]))
        else:
            out.append(("text", e["stream_id"], e["text"].strip()))
    return out


def woerter(frames) -> list[str]:
    return [f.text for f in frames if isinstance(f, TTSTextFrame)]


def antwortenden(frames) -> list[int]:
    return [i for i, f in enumerate(frames) if isinstance(f, LLMFullResponseEndFrame)]


# --- Schalter und Text ---------------------------------------------------------------------------------------------------


def test_schalter_standard_an_und_abschaltbar(monkeypatch):
    assert tts_vor_werkzeug_an("") and tts_vor_werkzeug_an("an")
    assert not tts_vor_werkzeug_an("aus") and not tts_vor_werkzeug_an("0")
    assert tts_vor_werkzeug_an()
    monkeypatch.setenv("WAMO_TTS_VOR_WERKZEUG", "aus")
    assert not tts_vor_werkzeug_an()


def test_ein_marker_allein_ist_kein_gesprochener_text():
    assert gesprochener_text("Ich") and gesprochener_text(" zeige") and gesprochener_text("● Ich")
    for t in ("", " ", "\n", "●", "● ", " ◐", "○\n", "●◐○", " ● \n"):
        assert not gesprochener_text(t), repr(t)


def test_haken_sitzt_im_claude_dienst_und_in_beiden_sprachausgaben():
    assert hasattr(AnthropicLLMService, "_create_message_stream"), "Pipecat-Haken für den Antwortstrom fehlt"
    assert issubclass(la.ClaudeService, SatzVorWerkzeugLLM)
    assert not issubclass(la.LiteLLMService, SatzVorWerkzeugLLM), "das Gateway liefert Werkzeugaufrufe als ganzen Block"
    assert issubclass(LazySonioxTTSService, SatzVorWerkzeugTTS) and issubclass(sa.HausTTSService, SatzVorWerkzeugTTS)
    assert LazySonioxTTSService.stream_vor_werkzeug_beenden and not sa.HausTTSService.stream_vor_werkzeug_beenden


def test_pipecat_teile_vorhanden_sonst_bleibt_alles_wie_bisher():
    """Vertrag mit Pipecat 1.12: beide Sprachausgaben haben die Teile, die der Mixin braucht. Fehlt einer (Pipecat-Umbau),
    tut der Frame nichts, und der Satz erklingt wie bisher mit dem Antwortende."""
    assert hasattr(TTSService, "_maybe_reset_word_timestamps"), "die Methode, die SatzVorWerkzeugTTS überschreibt, fehlt in Pipecat"
    for dienst in (LazySonioxTTSService(api_key="x"),
                   sa.HausTTSService(modell="wamo-tts", stimme="sohee", basis="http://litellm.test.invalid:4000/v1", schluessel="k")):
        assert dienst._pipecat_passt(), type(dienst).__name__
    dienst = LazySonioxTTSService(api_key="x")
    del dienst._pending_llm_response_end_frames
    dienst._text_aggregator = mock.Mock()
    assert not dienst._pipecat_passt()
    asyncio.run(dienst._vor_werkzeug_sprechen())
    dienst._text_aggregator.flush.assert_not_called()


# --- Claude: der Frame beim Beginn eines Werkzeugaufrufs ----------------------------------------------------------------


async def test_einleitung_vor_dem_werkzeug_schickt_den_frame_hinter_dem_text():
    unten, _ = await run_test(claude(antwort_mit_werkzeug("● Ich zeige", " dir die Stories.")), frames_to_send=[kontext()])
    assert len(vor_werkzeug(unten)) == 1
    stelle = unten.index(vor_werkzeug(unten)[0])
    letzter_text = max(i for i, f in enumerate(unten) if isinstance(f, LLMTextFrame))
    assert letzter_text < stelle < antwortenden(unten)[0]
    assert "".join(f.text for f in unten if isinstance(f, LLMTextFrame)) == EINLEITUNG  # Text und Marker wie bisher


async def test_frame_kommt_bevor_die_argumente_fertig_sind():
    tor = asyncio.Event()
    antwort = antwort_mit_werkzeug("● Ich zeige", " dir die Stories.")
    erstes_argument = next(i for i, e in enumerate(antwort) if hasattr(getattr(e, "delta", None), "partial_json"))
    gesehen: list = []

    class Aufnahme(LazySonioxTTSService):  # nur als Empfänger hinter dem Modell
        async def process_frame(self, frame, direction):
            gesehen.append(frame)
            await super().process_frame(frame, direction)

    empfaenger = Aufnahme(api_key="x", sample_rate=24000)
    empfaenger._connect = mock.AsyncMock()
    empfaenger._disconnect = mock.AsyncMock()
    empfaenger._websocket = SonioxAttrappe(empfaenger, [])
    lauf = asyncio.create_task(run_test(Pipeline([claude(antwort, tor=tor, tor_vor=erstes_argument), empfaenger]),
                                        frames_to_send=[kontext()]))
    try:
        await bis(lambda: bool(vor_werkzeug(gesehen)))
        assert not antwortenden(gesehen), "die Antwort läuft noch, die Argumente entstehen erst"
    finally:
        await fertig(lauf, tor)


async def test_ohne_text_vor_dem_werkzeug_kein_frame():
    unten, _ = await run_test(claude(antwort_mit_werkzeug()), frames_to_send=[kontext()])
    assert not vor_werkzeug(unten)


@pytest.mark.parametrize("marker", ["●", "● ", "● \n"])
async def test_nur_ein_marker_vor_dem_werkzeug_ist_kein_text(marker):
    unten, _ = await run_test(claude(antwort_mit_werkzeug(marker)), frames_to_send=[kontext()])
    assert not vor_werkzeug(unten)


async def test_marker_ohne_satzende_filter_ist_kein_text():
    unten, _ = await run_test(claude(antwort_mit_werkzeug("●", " "), satzende_filter=False), frames_to_send=[kontext()])
    assert [f.text for f in unten if isinstance(f, LLMTextFrame)] == ["●", " "]  # ohne Filter kommt der Marker als Text
    assert not vor_werkzeug(unten)


async def test_schalter_aus_heisst_kein_frame(monkeypatch):
    monkeypatch.setenv("WAMO_TTS_VOR_WERKZEUG", "aus")
    unten, _ = await run_test(claude(antwort_mit_werkzeug("● Ich zeige", " dir die Stories.")), frames_to_send=[kontext()])
    assert not vor_werkzeug(unten)
    assert "".join(f.text for f in unten if isinstance(f, LLMTextFrame)) == EINLEITUNG


async def test_schalter_aus_laesst_den_antwortstrom_unberuehrt(monkeypatch):
    d = claude()
    strom = object()
    with mock.patch.object(AnthropicLLMService, "_create_message_stream", mock.AsyncMock(return_value=strom)):
        monkeypatch.setenv("WAMO_TTS_VOR_WERKZEUG", "aus")
        assert await d._create_message_stream(None, {}) is strom
        monkeypatch.setenv("WAMO_TTS_VOR_WERKZEUG", "an")
        assert await d._create_message_stream(None, {}) is not strom


async def test_zwei_werkzeugbloecke_nach_einem_text_ein_frame():
    antwort = [block_text(0), text("● Moment,"), text(" ich lege beides an."), block_ende(0),
               *werkzeug(1, "toolu_1"), *werkzeug(2, "toolu_2"), stopp()]
    unten, _ = await run_test(claude(antwort), frames_to_send=[kontext()])
    assert len(vor_werkzeug(unten)) == 1


async def test_jede_antwort_zaehlt_ihren_text_fuer_sich():
    """Text aus der vorigen Antwort zählt nicht: eine Antwort nur mit Werkzeugaufruf schickt keinen Frame."""
    unten, _ = await run_test(claude(nur_text("● Hallo, gern."), antwort_mit_werkzeug()), frames_to_send=[kontext(), kontext()])
    assert len(antwortenden(unten)) == 2
    assert not vor_werkzeug(unten)


# --- Soniox: Rest sofort sprechen und Stream mit text_end abschließen ------------------------------------------------------


async def test_soniox_spricht_den_satz_vor_dem_antwortende():
    log: list = []
    unten, _ = await run_test(soniox(log), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("Ich zeige"), LLMTextFrame(" dir die Stories."), SatzVorWerkzeugFrame(),
        LLMFullResponseEndFrame()])
    k = kurz(log)
    sid = k[0][1]
    assert k == [("config", sid), ("text", sid, EINLEITUNG), ("text_end", sid), "ende"]  # kein zweites text_end am Antwortende
    assert woerter(unten) == EINLEITUNG.split()
    assert len(antwortenden(unten)) == 1 and antwortenden(unten)[0] > max(i for i, f in enumerate(unten) if isinstance(f, TTSTextFrame))


async def test_soniox_ohne_frame_wie_bisher():
    log: list = []
    unten, _ = await run_test(soniox(log), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("Ich zeige"), LLMTextFrame(" dir die Stories."), LLMFullResponseEndFrame()])
    k = kurz(log)
    sid = k[1][1]
    assert k == ["ende", ("config", sid), ("text", sid, EINLEITUNG), ("text_end", sid)]
    assert woerter(unten) == EINLEITUNG.split() and len(antwortenden(unten)) == 1


@pytest.mark.parametrize("soniox_langsam", [False, True])
async def test_soniox_genau_ein_antwortende_hinter_dem_letzten_wort(soniox_langsam):
    """Soniox fertig vor dem Antwortende (Argumente lang) oder erst danach (Soniox langsam): Verlauf und Antwortende gleich."""
    log: list = []
    ende = LLMFullResponseEndFrame()
    frames = [LLMFullResponseStartFrame(), LLMTextFrame(EINLEITUNG), SatzVorWerkzeugFrame()]
    frames += [ende] if soniox_langsam else [SleepFrame(0.3), ende]
    tts = soniox(log, verzoegerung=0.3 if soniox_langsam else 0.0)
    unten, _ = await run_test(tts, frames_to_send=frames)
    assert woerter(unten) == EINLEITUNG.split()
    assert len(antwortenden(unten)) == 1
    assert antwortenden(unten)[0] > max(i for i, f in enumerate(unten) if isinstance(f, TTSTextFrame))
    if soniox_langsam:  # das echte Antwortende kam vor dem Ende des Streams: es selbst geht weiter, mit seiner Kennung
        assert unten[antwortenden(unten)[0]] is ende
    assert tts._pending_llm_response_end_frames == {}, "kein Antwortende bleibt an einem Kontext ohne Ton hängen"


async def test_soniox_satz_schon_bei_soniox_bekommt_trotzdem_text_end():
    """Fall 2 des Befunds: der Text ging schon an Soniox (Aggregator leer), Soniox hält ihn unter 65 Zeichen zurück."""
    log: list = []
    await run_test(soniox(log, start=15), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("Eins zwei drei vier "), SatzVorWerkzeugFrame(), LLMFullResponseEndFrame()])
    k = kurz(log)
    sid = k[0][1]
    assert k == [("config", sid), ("text", sid, "Eins zwei drei vier"), ("text_end", sid), "ende"]


async def test_soniox_text_nach_dem_werkzeug_oeffnet_einen_neuen_stream():
    log: list = []
    unten, _ = await run_test(soniox(log), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(EINLEITUNG), SatzVorWerkzeugFrame(), LLMFullResponseEndFrame(),
        LLMFullResponseStartFrame(), LLMTextFrame("Fertig, die Stories stehen im Canvas."), LLMFullResponseEndFrame()])
    k = kurz(log)
    a, c = k[0][1], k[5][1]
    assert a != c
    assert k == [("config", a), ("text", a, EINLEITUNG), ("text_end", a), "ende", "ende",
                 ("config", c), ("text", c, "Fertig, die Stories stehen im Canvas."), ("text_end", c)]
    assert woerter(unten) == [*EINLEITUNG.split(), "Fertig,", "die", "Stories", "stehen", "im", "Canvas."]
    assert len(antwortenden(unten)) == 2


@pytest.mark.parametrize("zweites_werkzeug", [False, True])
async def test_soniox_text_nach_dem_frame_in_derselben_antwort_geht_in_einen_neuen_stream(zweites_werkzeug):
    """Selten (Claude schreibt Werkzeugblöcke ans Ende): Text hinter einem Werkzeugblock derselben Antwort, auch Text, Werkzeug,
    Text, Werkzeug. Der abgeschlossene Stream bekommt nichts mehr, kein Wort geht verloren. Bewusst festgehalten: je Stream ein
    Antwortende, der Verlauf bekommt den zweiten Teil also als eigene Nachricht (Kopfkommentar von satz_vor_werkzeug.py)."""
    log: list = []
    frames = [LLMFullResponseStartFrame(), LLMTextFrame(EINLEITUNG), SatzVorWerkzeugFrame(), LLMTextFrame(" Und noch etwas.")]
    frames += [SatzVorWerkzeugFrame()] if zweites_werkzeug else []
    unten, _ = await run_test(soniox(log), frames_to_send=[*frames, LLMFullResponseEndFrame()])
    k = kurz(log)
    a = k[0][1]
    b = next(e[1] for e in k if isinstance(e, tuple) and e[1] != a)
    zweiter =[("config", b), ("text", b, "Und noch etwas."), ("text_end", b)]
    assert k == ([("config", a), ("text", a, EINLEITUNG), ("text_end", a), *zweiter, "ende"] if zweites_werkzeug
                 else [("config", a), ("text", a, EINLEITUNG), ("text_end", a), "ende", *zweiter])
    assert woerter(unten) == [*EINLEITUNG.split(), "Und", "noch", "etwas."]
    assert len(antwortenden(unten)) == 2
    assert antwortenden(unten)[-1] > max(i for i, f in enumerate(unten) if isinstance(f, TTSTextFrame))


async def test_soniox_unterbrechung_nach_dem_frame_und_naechste_antwort_wie_gewohnt():
    log: list = []
    unten, _ = await run_test(soniox(log, verzoegerung=0.5), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(EINLEITUNG), SatzVorWerkzeugFrame(), SleepFrame(0.05), InterruptionFrame(),
        SleepFrame(0.05), LLMFullResponseStartFrame(), LLMTextFrame("Gut, dann nicht."), LLMFullResponseEndFrame()])
    k = kurz(log)
    a = k[0][1]
    c = next(e[1] for e in k[3:] if isinstance(e, tuple) and e[0] == "config")
    assert a != c
    # kein cancel für den Stream, der schon text_end hat (Pipecat: nie cancel nach text_end)
    assert k[:3] == [("config", a), ("text", a, EINLEITUNG), ("text_end", a)]
    assert k[3:] == ["ende", ("config", c), ("text", c, "Gut, dann nicht."), ("text_end", c)]
    assert woerter(unten) == ["Gut,", "dann", "nicht."]
    assert len(antwortenden(unten)) == 1


async def test_antwortende_auch_wenn_pipecat_die_antwort_schon_fuer_beendet_haelt():
    """Endet der vorab abgeschlossene Stream, gibt der Dienst dort das Antwortende weiter, auch wenn Pipecats Merker für die
    laufende Antwort schon zurückgesetzt ist (ein Kontext einer früheren Antwort endete nach dem Beginn dieser)."""
    d = LazySonioxTTSService(api_key="x", start=0)
    d._wamo_vor_werkzeug_alt = "A"
    d._llm_response_started = False
    d.push_frame = mock.AsyncMock()
    await d._maybe_reset_word_timestamps("A")
    assert isinstance(d.push_frame.await_args.args[0], LLMFullResponseEndFrame)
    assert d._wamo_vor_werkzeug_alt is None


# --- Sprachausgabe im Haus: nur der Satz-Aggregator ----------------------------------------------------------------------


def wav(rate: int = 24000, sekunden: float = 0.05) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * sekunden))
    return buf.getvalue()


class ProtokollHaus(sa.HausTTSService):
    def __init__(self, log: list, **kwargs):
        super().__init__(**kwargs)
        self.log = log

    async def process_frame(self, frame, direction):
        if isinstance(frame, LLMFullResponseEndFrame):
            self.log.append("ende")
        await super().process_frame(frame, direction)


def haus(log: list) -> ProtokollHaus:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(("anfrage", json.loads(request.content)["input"].strip()))
        return httpx.Response(200, content=wav())

    return ProtokollHaus(log, modell="wamo-tts", stimme="sohee", basis="http://litellm.test.invalid:4000/v1", schluessel="k",
                         client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sample_rate=24000, stream=False)


@pytest.mark.parametrize("mit_frame", [True, False])
async def test_haus_spricht_den_satz_vor_dem_antwortende(mit_frame):
    log: list = []
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("Ich zeige"), LLMTextFrame(" dir die Stories.")]
    frames += [SatzVorWerkzeugFrame()] if mit_frame else []
    unten, _ = await run_test(haus(log), frames_to_send=[*frames, LLMFullResponseEndFrame()])
    assert log == ([("anfrage", EINLEITUNG), "ende"] if mit_frame else ["ende", ("anfrage", EINLEITUNG)])
    assert [f.text for f in unten if isinstance(f, TTSTextFrame)] == [EINLEITUNG]  # Untertitel und Verlauf wie bisher
    assert len(antwortenden(unten)) == 1 and not vor_werkzeug(unten)


# --- Claude und Soniox zusammen -----------------------------------------------------------------------------------------


async def _claude_und_soniox(log: list, tor: asyncio.Event):
    antwort = antwort_mit_werkzeug("● Ich zeige", " dir die Stories.")
    erstes_argument = next(i for i, e in enumerate(antwort) if hasattr(getattr(e, "delta", None), "partial_json"))
    return asyncio.create_task(run_test(Pipeline([claude(antwort, tor=tor, tor_vor=erstes_argument), soniox(log)]),
                                        frames_to_send=[kontext()]))


async def test_claude_und_soniox_text_end_waehrend_die_argumente_noch_entstehen():
    log: list = []
    tor = asyncio.Event()
    lauf = await _claude_und_soniox(log, tor)
    try:
        await bis(lambda: any(isinstance(e, dict) and e.get("text_end") for e in log))
        assert "ende" not in log, "die Antwort läuft noch"
        assert [e[2] for e in kurz(log) if e[0] == "text"] == [EINLEITUNG]
    finally:
        unten, _ = await fertig(lauf, tor)
    assert kurz(log)[-1] == "ende" and len([e for e in kurz(log) if e[0] == "text_end"]) == 1
    assert woerter(unten) == EINLEITUNG.split() and len(antwortenden(unten)) == 1


async def test_claude_und_soniox_schalter_aus_wie_bisher(monkeypatch):
    monkeypatch.setenv("WAMO_TTS_VOR_WERKZEUG", "aus")
    log: list = []
    tor = asyncio.Event()
    lauf = await _claude_und_soniox(log, tor)
    try:
        await asyncio.sleep(0.3)
        assert log == [], "ohne Schalter wartet der Satz auf das Antwortende"
    finally:
        unten, _ = await fertig(lauf, tor)
    k = kurz(log)
    assert k[0] == "ende" and k[-1][0] == "text_end"
    assert woerter(unten) == EINLEITUNG.split() and len(antwortenden(unten)) == 1
