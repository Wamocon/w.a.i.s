"""Sprachausgabe ohne Ton (Befund im Journal des Kerns am 17.11.2026, Hausmodell gemma4-31b über LiteLLM, Soniox spricht).

Ablauf im Journal: Das Hausmodell sagt etwas, dann bleibt der Strom des Gateways stumm, bis der Werkzeugaufruf als ganzer Block kommt
(llm_anbieter.HAUS_GESPRAECH_LESE_TIMEOUT_SECS). Soniox hält einen Text unter etwa 65 Zeichen bis text_end zurück (soniox_tts.py,
"Rückhalt am Textende"). Pipecat wartet je Kontext höchstens stop_frame_timeout_s (3 s) auf Ton und erklärt ihn dann für beendet:
"audio context ... completed with no audio", ErrorFrame bis in die Oberfläche, ein eigenes Antwortende vor dem des Modells, verworfene
Wörter. Der Stream bei Soniox bleibt offen und läuft nach rund 10 s in Soniox' Leerlauf-Timeout (408, wieder ein ErrorFrame).

Soniox läuft hier als echter LazySonioxTTSService mit Pipecats echtem Empfang (_receive_messages). Der Nachbau des Websockets antwortet
wie Soniox: Ton und Wortzeiten erst mit text_end, ohne sprechbaren Text nur terminated, auf cancel terminated, und nach leerlauf
Sekunden ohne text_end der Fehler 408. Die Zeiten sind verkürzt (Pipecat 3 s, Stille 1 s, Soniox rund 10 s), das Verhältnis bleibt."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from websockets.protocol import State

import soniox_tts
from fuellwoerter import ALLE_SAETZE, FuellwortBank, FuellwortSpieler
from soniox_tts import LazySonioxTTSService, sprechbar
from test_satz_vor_werkzeug import ProtokollSoniox, antwortenden, kurz, woerter
from wartesatz import Wartesatz

from pipecat.frames.frames import (
    ErrorFrame,
    FunctionCallFromLLM,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import SleepFrame, run_test

WARTE = 0.6  # Pipecat: so lange wartet ein Kontext auf Ton (stop_frame_timeout_s, im Betrieb 3 s)
STILLE = 0.2  # Stille des Modells, nach der ein offener Stream abgeschlossen wird (im Betrieb STILLE_ABSCHLUSS_SECS)
LEERLAUF = 1.5  # Soniox: Stream mit Text, aber ohne text_end, endet mit 408 (im Betrieb rund 10 s)
PAUSE = 1.0  # das Gateway schweigt, während das Hausmodell den Werkzeugaufruf schreibt (länger als WARTE)
ERSTER = "Ich habe nichts gefunden."


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch):
    for name in ("WAMO_TTS_VOR_WERKZEUG", "WAMO_TTS_START_ZEICHEN", "WAMO_TTS_SATZLEERZEICHEN"):
        monkeypatch.delenv(name, raising=False)


class SonioxNachbau:
    """Websocket wie Soniox, Nachrichten an den echten Empfang von Pipecat (async for über den Websocket)."""

    def __init__(self, log: list, ereignisse: list, *, verzoegerung: float = 0.05, leerlauf: float = LEERLAUF):
        self.state = State.OPEN
        self._log, self._ereignisse = log, ereignisse
        self._verzoegerung, self._leerlauf = verzoegerung, leerlauf
        self._texte: dict[str, str] = {}
        self._ende: set[str] = set()
        self._uhren: dict[str, asyncio.Task] = {}
        self._aufgaben: list[asyncio.Task] = []
        self._post: asyncio.Queue = asyncio.Queue()

    async def send(self, nachricht: str):
        m = json.loads(nachricht)
        if m.get("keep_alive"):
            return
        self._log.append(m)
        sid = m.get("stream_id")
        if m.get("cancel"):
            self._uhr_stoppen(sid)
            self._post.put_nowait({"stream_id": sid, "terminated": True})
            return
        if "text" in m:
            if sid in self._ende:
                self._ereignisse.append(("text_nach_ende", sid))
            self._texte[sid] = self._texte.get(sid, "") + m["text"]
            if m["text"] and sid not in self._uhren:
                self._uhren[sid] = asyncio.get_running_loop().create_task(self._leerlauf_uhr(sid))
        if m.get("text_end"):
            self._ende.add(sid)
            self._uhr_stoppen(sid)
            self._aufgaben.append(asyncio.get_running_loop().create_task(self._sprechen(sid)))

    def _uhr_stoppen(self, sid: str) -> None:
        uhr = self._uhren.pop(sid, None)
        if uhr is not None:
            uhr.cancel()

    async def _leerlauf_uhr(self, sid: str):
        await asyncio.sleep(self._leerlauf)
        self._ereignisse.append(("408", sid))
        self._post.put_nowait({"stream_id": sid, "error_code": 408, "error_type": "request_timeout",
                               "error_message": "Request timeout."})

    async def _sprechen(self, sid: str):
        await asyncio.sleep(self._verzoegerung)
        text = self._texte.get(sid, "")
        if sprechbar_fuer_soniox(text):
            self._post.put_nowait({"stream_id": sid, "audio": base64.b64encode(b"\x00\x01" * 480).decode()})
            zeichen = list(text.strip())
            self._post.put_nowait({"stream_id": sid, "timestamps": {
                "characters": zeichen, "character_start_times_seconds": [0.01 * i for i in range(len(zeichen))]}})
        self._post.put_nowait({"stream_id": sid, "terminated": True})

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self._post.get()
        if m is None:
            raise StopAsyncIteration
        return json.dumps(m)

    async def ping(self):
        return None

    async def close(self):
        self.state = State.CLOSED
        for t in [*self._uhren.values(), *self._aufgaben]:
            t.cancel()
        self._post.put_nowait(None)


def sprechbar_fuer_soniox(text: str) -> bool:
    """So viel weiß der Nachbau über Soniox: ohne Buchstaben und Ziffern kein Ton."""
    return any(c.isalnum() for c in text)


def soniox(log: list, ereignisse: list, *, start: int | None = None, verzoegerung: float = 0.05) -> ProtokollSoniox:
    d = ProtokollSoniox(log, api_key="x", sample_rate=24000, start=start)
    d._websocket = SonioxNachbau(log, ereignisse, verzoegerung=verzoegerung)
    d._stop_frame_timeout_s = WARTE
    d.stille_abschluss_secs = STILLE
    return d


def fehler(oben) -> list[str]:
    return [f.error for f in oben if isinstance(f, ErrorFrame)]


def texte_an_soniox(log: list) -> str:
    return " ".join(e[2] for e in kurz(log) if isinstance(e, tuple) and e[0] == "text")


# --- der Befund ----------------------------------------------------------------------------------------------------------


async def test_pause_im_strom_des_hausmodells_ergibt_keinen_kontext_ohne_ton():
    """Zwei Sätze, der erste geht an Soniox (kurz, also zurückgehalten), dann schweigt das Gateway länger als Pipecat auf Ton wartet."""
    log, ereignisse = [], []
    tts = soniox(log, ereignisse)
    unten, oben = await run_test(tts, frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(ERSTER), LLMTextFrame(" Ich suche noch einmal."), SleepFrame(PAUSE),
        LLMFullResponseEndFrame(), SleepFrame(0.3)])
    assert fehler(oben) == []
    assert ereignisse == []
    k = kurz(log)
    a = k[0][1]
    # derselbe Stream bekommt den Rest und text_end während der Pause, das Antwortende des Modells kommt danach
    assert k == [("config", a), ("text", a, ERSTER), ("text", a, "Ich suche noch einmal."), ("text_end", a), "ende"]
    assert woerter(unten) == [*ERSTER.split(), "Ich", "suche", "noch", "einmal."]
    assert len(antwortenden(unten)) == 1 and antwortenden(unten)[0] > max(i for i, f in enumerate(unten) if isinstance(f, TTSTextFrame))
    assert tts._pending_llm_response_end_frames == {}


async def test_pause_laenger_als_soniox_leerlauf_kein_408():
    """Text liegt schon ganz bei Soniox (Aggregator leer), das Antwortende kommt erst nach Soniox' Leerlauf-Timeout."""
    log, ereignisse = [], []
    unten, oben = await run_test(soniox(log, ereignisse, start=15), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("Eins zwei drei vier "), SleepFrame(LEERLAUF + 0.5), LLMFullResponseEndFrame(),
        SleepFrame(0.2)])
    assert fehler(oben) == []
    assert ereignisse == [], "kein 408 und kein Text nach text_end"
    k = kurz(log)
    a = k[0][1]
    assert k == [("config", a), ("text", a, "Eins zwei drei vier"), ("text_end", a), "ende"]
    assert woerter(unten) == ["Eins", "zwei", "drei", "vier"]
    assert len(antwortenden(unten)) == 1


async def test_modell_schreibt_langsam_weiter_kein_kontext_ohne_ton():
    """Das Modell liefert weiter Text (langer Satz im Aggregator), nur nichts Neues an Soniox: kein Abschluss, aber auch kein Ende
    des Kontexts nach WARTE Sekunden."""
    log, ereignisse = [], []
    langsam = []
    for wort in ("Ich", " suche", " noch", " einmal", " nach", " dem", " Wetter", " in", " Eschborn."):
        langsam += [SleepFrame(STILLE / 2), LLMTextFrame(wort)]
    unten, oben = await run_test(soniox(log, ereignisse), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(ERSTER + " "), *langsam, LLMFullResponseEndFrame(), SleepFrame(0.3)])
    assert fehler(oben) == []
    assert [e[0] for e in kurz(log) if isinstance(e, tuple)].count("config") == 1, "ein Stream: kein Abschluss, solange Text kommt"
    assert texte_an_soniox(log) == f"{ERSTER} Ich suche noch einmal nach dem Wetter in Eschborn."
    assert woerter(unten)[-2:] == ["in", "Eschborn."]
    assert len(antwortenden(unten)) == 1


@pytest.mark.parametrize("text", ["●", "● ", "◐ …", "…", " – *", "\n●\n"])
async def test_ohne_sprechbaren_text_kein_stream(text):
    log, ereignisse = [], []
    unten, oben = await run_test(soniox(log, ereignisse), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(text), SleepFrame(0.1), LLMFullResponseEndFrame(), SleepFrame(WARTE + 0.2)])
    assert fehler(oben) == []
    assert kurz(log) == ["ende"], "kein Stream bei Soniox"
    # wie eine Antwort nur aus Leerraum oder nur mit Werkzeugaufruf: Pipecat 1.12 hält deren Antwortende ohne Kontext zurück
    assert antwortenden(unten) == []


def test_sprechbar():
    for t in ("Ja.", "3", "Öl", " ß ", "Wais"):
        assert sprechbar(t), t
    for t in ("", " ", "\n", "●", "● ◐ ○", "…", "–", "*", "?!", "😀"):
        assert not sprechbar(t), repr(t)


async def test_unterbrechung_in_der_pause_kein_text_end_nach_cancel():
    log, ereignisse = [], []
    unten, oben = await run_test(soniox(log, ereignisse), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame(ERSTER), LLMTextFrame(" Ich"), SleepFrame(STILLE / 2), InterruptionFrame(),
        SleepFrame(PAUSE)])
    assert fehler(oben) == []
    k = kurz(log)
    a = k[0][1]
    assert k == [("config", a), ("text", a, ERSTER), ("cancel", a)]
    assert ereignisse == []


async def test_ohne_offenen_stream_wartet_ein_satz_wie_bisher_auf_das_antwortende():
    """Ein einzelner Satz bleibt im Aggregator (Pipecat wartet nach dem Punkt auf mehr Text): kein Stream, nichts zu schließen, der
    Satz geht wie bisher mit dem Antwortende hinaus."""
    log, ereignisse = [], []
    unten, oben = await run_test(soniox(log, ereignisse), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("Ich schaue nach."), SleepFrame(PAUSE), LLMFullResponseEndFrame(), SleepFrame(0.3)])
    assert fehler(oben) == []
    k = kurz(log)
    a = k[1][1]
    assert k == ["ende", ("config", a), ("text", a, "Ich schaue nach."), ("text_end", a)]
    assert woerter(unten) == ["Ich", "schaue", "nach."]


def test_stille_abschluss_im_betrieb_kuerzer_als_pipecats_wartezeit():
    d = LazySonioxTTSService(api_key="x")
    assert 0 < soniox_tts.STILLE_ABSCHLUSS_SECS < d._stop_frame_timeout_s
    assert d.stille_abschluss_secs == soniox_tts.STILLE_ABSCHLUSS_SECS


# --- der ganze Ablauf aus dem Journal ------------------------------------------------------------------------------------


def _aufruf(nr: int) -> tuple[FunctionCallsStartedFrame, FunctionCallInProgressFrame, FunctionCallResultFrame]:
    kennung, argumente = f"call_{nr}", {"anfrage": "Wetter Eschborn Wochenende"}
    return (
        FunctionCallsStartedFrame(function_calls=[FunctionCallFromLLM("websuche", kennung, argumente, None)]),
        FunctionCallInProgressFrame("websuche", kennung, argumente),
        FunctionCallResultFrame("websuche", kennung, argumente, {"ergebnis": "Nichts Brauchbares gefunden."}),
    )


async def test_ablauf_wie_im_journal_websuche_fuellwort_wartesatz_und_pause(tmp_path):
    """Antwort 1 nur mit websuche (Füllwort und Wartesatz), Antwort 2 mit zwei Sätzen und langer Pause bis zum nächsten websuche,
    Antwort 3 mit dem Ergebnis. Kein ErrorFrame, kein 408, alles gesprochen."""
    log, ereignisse = [], []
    bank = FuellwortBank("Testimme", ordner=tmp_path)
    bank._ton = {s: b"\x00\x00" * 960 for s in ALLE_SAETZE}
    kette = Pipeline([
        Wartesatz(nach_secs=0.15, werkzeug=True),
        FuellwortSpieler(bank, werkzeug=True, nach_secs=0.05),
        soniox(log, ereignisse),
    ])
    s1, l1, e1 = _aufruf(1)
    s2, l2, e2 = _aufruf(2)
    unten, oben = await run_test(kette, frames_to_send=[
        LLMFullResponseStartFrame(), s1, l1, LLMFullResponseEndFrame(), SleepFrame(WARTE + 0.2), e1,
        LLMFullResponseStartFrame(), LLMTextFrame(ERSTER), LLMTextFrame(" Ich suche noch einmal."), SleepFrame(PAUSE), s2, l2,
        LLMFullResponseEndFrame(), SleepFrame(0.2), e2,
        LLMFullResponseStartFrame(), LLMTextFrame("Leider finde ich dazu nichts."), LLMFullResponseEndFrame(), SleepFrame(WARTE)])
    assert fehler(oben) == []
    assert ereignisse == []
    gesagt = " ".join(woerter(unten))
    assert f"{ERSTER} Ich suche noch einmal." in gesagt and gesagt.endswith("Leider finde ich dazu nichts.")
    assert gesagt.startswith("Moment, ich suche das kurz.") or gesagt.startswith(("Ich schaue kurz nach.", "Einen Augenblick"))
