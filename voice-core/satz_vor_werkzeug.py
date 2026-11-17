"""Satz vor dem Werkzeug: Text, den das Modell vor einem Werkzeugaufruf sagt, sofort sprechen.

Befund (Lasttest-Vorstufe 17.11.2026, Zeilen LATENZ_JSON im Journal des Kerns): Sagt Claude einen kurzen Einleitungssatz und ruft
danach ein Werkzeug mit langen Argumenten auf (canvas_zeigen mit fünf Stories), erklingt der Satz erst, wenn die Argumente fertig
erzeugt sind. Zwei Stellen halten ihn zurück:
  * Pipecats Satzende-Erkennung wartet nach dem Punkt auf weiteren Text. Nach dem Punkt kommt nur noch der Werkzeugaufruf, der
    Satz geht also erst mit dem Antwortende an die Sprachausgabe (Fall 1: llm_token 939 ms, tts_satz 4269 ms, tts_audio 4471 ms).
  * Soniox spricht einen Text unter etwa 65 Zeichen erst, wenn mehr Text oder text_end kommt (soniox_tts.py, "Rückhalt am
    Textende"; Fall 2: tts_satz 1129 ms, tts_audio 6697 ms).
Folge: 4 bis 6 s Stille, obwohl der Satz nach 1 s fertig war.

Weg: Beginnt im Antwortstrom von Claude ein Block vom Typ tool_use (Ereignis content_block_start) und hat diese Antwort schon
gesprochenen Text geliefert, schickt der Dienst einen SatzVorWerkzeugFrame hinter dem Text her (SatzVorWerkzeugLLM, Haken
_create_message_stream). Die Sprachausgabe (SatzVorWerkzeugTTS) gibt darauf den Rest ihres Satz-Aggregators sofort weiter, ohne
den Zug oder den Kontext zu beenden. Soniox schließt zusätzlich den laufenden Stream mit text_end ab (stream_vor_werkzeug_beenden),
weiterer Text derselben Antwort öffnet einen neuen Stream, Text nach dem Werkzeug kommt wie bisher in einer neuen Antwort mit
eigenem Stream. Die Sprachausgabe im Haus schickt ohnehin jeden Satz als eigene Anfrage; dort wirkt nur der Aggregator.

Was gleich bleibt: Ein Marker allein (●, ◐, ○) ist kein gesprochener Text. Verlauf, Untertitel und Kontext entstehen wie bisher
aus den Wort-Zeitstempeln. Das Antwortende (LLMFullResponseEndFrame) geht wie bisher einmal je Antwort hinter dem letzten Wort des
Satzes weiter, also vor dem Werkzeugaufruf im Kontext (SatzVorWerkzeugTTS._maybe_reset_word_timestamps). Eine Unterbrechung
verwirft alles wie bisher; für den vorab abgeschlossenen Stream schickt Soniox dabei kein cancel mehr (Pipecat: nie cancel nach
text_end). Wartesatz und Füllwörter sehen dieselben Frames wie bisher (der neue Frame ist ihnen fremd, sie reichen ihn weiter); die
Sprachausgabe gibt ihn nicht weiter.

Was sich sichtbar ändert: Endet der vorab abgeschlossene Stream, bevor das Modell die Argumente fertig hat (der Normalfall bei langen
Argumenten), gibt die Sprachausgabe dort ein eigenes Antwortende weiter, das spätere des Modells verfällt. Beobachter, die Frames nach
ihrer Kennung zählen, sehen dann zwei Antwortenden mit verschiedener Kennung (im Journal zweimal "Antwort des Modells beendet", einmal
vom Modell, einmal von der Sprachausgabe; RTVI meldet bot-llm-stopped zweimal, die Oberfläche wertet das nicht aus). Selten und
bewusst nicht behandelt: Text hinter einem Werkzeugblock in derselben Antwort (Claude schreibt Werkzeugblöcke ans Ende; Pipecat 1.12
führt dann ohnehin nur den letzten Werkzeugaufruf aus). Der Text geht dann in einen neuen Stream und bleibt erhalten, kommt aber als
eigene Nachricht ohne ● in den Verlauf, mit einem zweiten Antwortende (test_satz_vor_werkzeug.py hält das genau so fest).

Hausmodelle (LiteLLMService) schicken den Frame nicht: Das Gateway liefert einen Werkzeugaufruf erst als ganzen Block (llm_anbieter.py,
HAUS_GESPRAECH_LESE_TIMEOUT_SECS), sein Beginn fällt also mit dem Ende der Argumente und dem Antwortende zusammen. Während das Modell
die Argumente schreibt, schweigt der Strom; liegt dann schon Text bei Soniox, schließt die Soniox-Sprachausgabe den Stream nach einer
Sekunde Stille auf demselben Weg ab (_vor_werkzeug_sprechen mit anlass "Modell schweigt", soniox_tts.py, Befund 17.11.2026).

Schalter: WAMO_TTS_VOR_WERKZEUG (an oder aus, Standard an, gelesen je Antwort). Aus heißt: der Antwortstrom bleibt unberührt, kein
Frame, alles wie vor dem 17.11.2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from env_schalter import schalter_an

from pipecat.frames.frames import (
    AggregatedTextFrame,
    ControlFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.utils.text.pattern_pair_aggregator import PatternMatch

MARKER = "●◐○"  # Satzende-Marker der Persona (Pipecat-Standard): allein kein gesprochener Text
# Teile von Pipecats TTSService (1.12), auf die SatzVorWerkzeugTTS zugreift; ein Test prüft sie an beiden Sprachausgaben
PIPECAT_TEILE = (
    "_text_aggregator", "_push_tts_frames", "_push_sequencer_frames", "_aggregated_frame_sequencer", "_turn_context_id",
    "_pending_llm_response_end_frames", "_llm_response_started", "_word_last_pts", "_push_text_frames", "flush_audio",
    "create_context_id", "audio_context_available", "reset_word_timestamps", "stop_text_aggregation_metrics",
)


def tts_vor_werkzeug_an(wert: str | None = None) -> bool:
    """WAMO_TTS_VOR_WERKZEUG: Text vor einem Werkzeugaufruf sofort sprechen (Standard an)."""
    return schalter_an("WAMO_TTS_VOR_WERKZEUG", wert)


def gesprochener_text(text: str) -> bool:
    """Enthält der Text etwas Hörbares? Leerraum und Satzende-Marker zählen nicht."""
    return any(not c.isspace() and c not in MARKER for c in text)


def ist_werkzeug_beginn(ereignis: Any) -> bool:
    """Ereignis des Anthropic-Stroms, mit dem ein Werkzeugaufruf beginnt (content_block_start mit einem Block tool_use)."""
    block = getattr(ereignis, "content_block", None)
    return getattr(ereignis, "type", None) == "content_block_start" and getattr(block, "type", None) == "tool_use"


@dataclass
class SatzVorWerkzeugFrame(ControlFrame):
    """Das Modell beginnt einen Werkzeugaufruf, der Text davor soll jetzt erklingen. Ein Steuerframe: er läuft in der Reihenfolge
    hinter dem Text und wird bei einer Unterbrechung verworfen. Dienste, die ihn nicht kennen, reichen ihn weiter."""


class _StromMitWerkzeugBeginn:
    """Reicht den Antwortstrom unverändert durch und ruft beim Beginn eines Werkzeugaufrufs zuerst beim_werkzeug auf."""

    def __init__(self, strom: Any, beim_werkzeug):
        self._strom = strom
        self._beim_werkzeug = beim_werkzeug
        self._iterator: Any = None

    def __aiter__(self):
        self._iterator = self._strom.__aiter__()
        return self

    async def __anext__(self):
        ereignis = await self._iterator.__anext__()
        if ist_werkzeug_beginn(ereignis):
            await self._beim_werkzeug()
        return ereignis

    def __getattr__(self, name: str):
        return getattr(self._strom, name)


class SatzVorWerkzeugLLM:
    """Mixin für den Claude-Dienst (vor AnthropicLLMService in die Basisklassen). Merkt sich je Antwort, ob schon gesprochener
    Text hinausging, und schickt beim Beginn eines Werkzeugaufrufs einen SatzVorWerkzeugFrame hinter ihm her (höchstens einen je
    Text: ein zweiter Werkzeugblock ohne neuen Text schickt keinen)."""

    _wamo_text_unterwegs = False

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self._wamo_text_unterwegs = False
            elif isinstance(frame, LLMTextFrame) and gesprochener_text(frame.text):
                self._wamo_text_unterwegs = True
        await super().push_frame(frame, direction)

    async def _create_message_stream(self, api_call, params):
        strom = await super()._create_message_stream(api_call, params)
        if not tts_vor_werkzeug_an():
            return strom  # Schalter aus: der Strom bleibt unberührt
        return _StromMitWerkzeugBeginn(strom, self._vor_werkzeug)

    async def _vor_werkzeug(self) -> None:
        if not self._wamo_text_unterwegs:
            return
        self._wamo_text_unterwegs = False
        try:
            await self.push_frame(SatzVorWerkzeugFrame())
        except Exception as e:  # nie den Antwortstrom abbrechen: schlimmstenfalls erklingt der Satz wie bisher am Antwortende
            logger.warning("Satz vor dem Werkzeug nicht weitergegeben: {}", type(e).__name__)


class SatzVorWerkzeugTTS:
    """Mixin für Pipecat-Sprachausgaben (vor den Dienst in die Basisklassen): versteht den SatzVorWerkzeugFrame.

    Greift auf Attribute von Pipecats TTSService zu (PIPECAT_TEILE: Aggregator, Sequencer, Kontext des Zugs, gehaltene
    Antwortenden); fehlt eines (Pipecat-Umbau), bleibt es beim bisherigen Verhalten, und es gibt einmal eine Warnung.

    stream_vor_werkzeug_beenden: Dienste mit einem Stream je Zug, der Text zurückhält (Soniox), schließen ihn mit flush_audio
    (text_end) ab und beginnen für weiteren Text derselben Antwort einen neuen Kontext. Pipecat gibt das Antwortende am Ende des
    abgeschlossenen Kontexts weiter; damit das im Normalfall genau einmal geschieht (Ausnahme im Kopfkommentar), merkt sich der
    Dienst den alten und den neuen Kontext."""

    stream_vor_werkzeug_beenden = False
    _wamo_vor_werkzeug_alt: str | None = None  # Kontext, dessen Stream vor dem Antwortende abgeschlossen wurde
    _wamo_vor_werkzeug_neu: str | None = None  # Kontext des Zugs danach (bekommt nur Text, der in derselben Antwort folgt)
    _wamo_vor_werkzeug_warnung = False
    wamo_vor_werkzeug_gesprochen = 0  # für Tests und das Log

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, SatzVorWerkzeugFrame):
            if direction == FrameDirection.DOWNSTREAM:
                await self._vor_werkzeug_sprechen()
            return  # nur für die Sprachausgabe: geht nicht weiter zu Ausgabe, Verlauf und Kontext
        if isinstance(frame, InterruptionFrame):
            self._wamo_vor_werkzeug_alt = self._wamo_vor_werkzeug_neu = None  # Pipecat verwirft gehaltene Antwortenden selbst
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseEndFrame) and self._wamo_vor_werkzeug_neu is not None:
            self._antwortende_zuordnen()

    def _pipecat_passt(self) -> bool:
        """Hat der Dienst alle Teile von Pipecats TTSService, die hier gebraucht werden (auch die Methode, die dieser Mixin
        überschreibt)? Sonst bleibt alles wie bisher."""
        if all(hasattr(self, name) for name in PIPECAT_TEILE) and hasattr(
            super(SatzVorWerkzeugTTS, self), "_maybe_reset_word_timestamps"
        ):
            return True
        if not self._wamo_vor_werkzeug_warnung:
            self._wamo_vor_werkzeug_warnung = True
            logger.warning("Satz vor dem Werkzeug nicht möglich: Pipecats TTSService hat andere Attribute als erwartet")
        return False

    async def _vor_werkzeug_sprechen(self, anlass: str = "Werkzeugaufruf beginnt") -> None:
        """anlass steht nur im Log: der Frame vor einem Werkzeug oder der Stille-Abschluss der Soniox-Sprachausgabe (soniox_tts.py)."""
        if not self._pipecat_passt():
            return  # der Satz erklingt wie bisher mit dem Antwortende
        rest = await self._text_aggregator.flush()
        await self.stop_text_aggregation_metrics()
        gesendet = bool(rest and rest.text.strip())
        if gesendet:  # derselbe Weg wie Pipecats Antwortende (TTSService.process_frame, LLMFullResponseEndFrame)
            raw = rest.full_match if isinstance(rest, PatternMatch) else rest.text
            await self._push_tts_frames(AggregatedTextFrame(rest.text, rest.type, raw_text=raw))
        await self._push_sequencer_frames(
            await self._aggregated_frame_sequencer.finalize(self._turn_context_id), self._turn_context_id
        )
        abgeschlossen = self.stream_vor_werkzeug_beenden and await self._stream_abschliessen()
        if gesendet or abgeschlossen:
            self.wamo_vor_werkzeug_gesprochen += 1
            logger.info("{}: Text vorher sofort an die Sprachausgabe{} ({})", anlass,
                        ", Stream abgeschlossen" if abgeschlossen else "", self.wamo_vor_werkzeug_gesprochen)

    async def _stream_abschliessen(self) -> bool:
        """text_end für den laufenden Stream (wie Pipecats Soniox bei einer neuen Stimme mitten im Zug) und ein neuer Kontext für
        weiteren Text dieser Antwort. False, wenn in diesem Zug noch kein Text an die Sprachausgabe ging."""
        alt = self._turn_context_id
        if not alt or not self.audio_context_available(alt):
            return False
        # Erst die Buchführung, dann das await: endet der Stream schon währenddessen, findet _maybe_reset_word_timestamps sie vor
        self._turn_context_id = None
        self._turn_context_id = self.create_context_id()
        self._wamo_vor_werkzeug_alt, self._wamo_vor_werkzeug_neu = alt, self._turn_context_id
        await self.flush_audio(context_id=alt)
        self._stream_abgeschlossen(alt)
        return True

    def _stream_abgeschlossen(self, context_id: str) -> None:
        """Nach text_end für context_id: Platz für Dienste, die sich offene Streams merken (Soniox). Standard: nichts."""

    def _antwortende_zuordnen(self) -> None:
        """Das echte Antwortende ist da. Kam nach dem Werkzeugbeginn kein Text mehr, hängt Pipecat es an den neuen Kontext, der nie
        Ton bekommt: dann gehört es zum abgeschlossenen Kontext (endet der noch, gibt Pipecat es dort weiter) oder ist schon
        weitergegeben (der Kontext ist fertig, siehe _maybe_reset_word_timestamps)."""
        neu, self._wamo_vor_werkzeug_neu = self._wamo_vor_werkzeug_neu, None
        if self.audio_context_available(neu):
            return  # Text derselben Antwort ging in den neuen Stream: Pipecat gibt das Antwortende an dessen Ende weiter
        ende = self._pending_llm_response_end_frames.pop(neu, None)
        alt = self._wamo_vor_werkzeug_alt
        if ende is not None and alt is not None:
            self._pending_llm_response_end_frames[alt] = ende

    async def _maybe_reset_word_timestamps(self, context_id: str):
        if context_id != self._wamo_vor_werkzeug_alt or self._push_text_frames:
            return await super()._maybe_reset_word_timestamps(context_id)
        self._wamo_vor_werkzeug_alt = None  # vor jedem await: das Antwortende ordnet sich ab hier nicht mehr hier zu
        if context_id in self._pending_llm_response_end_frames:
            return await super()._maybe_reset_word_timestamps(context_id)  # das echte Antwortende, mit dem Zeitstempel
        # Der Stream endet vor dem Antwortende (die Argumente laufen noch): Antwortende hier weitergeben, wo Pipecat es am Ende des
        # Kontexts weitergibt, also vor dem Werkzeugaufruf im Kontext. Das echte folgt später und verfällt (_antwortende_zuordnen).
        await self.reset_word_timestamps()
        self._llm_response_started = False
        ende = LLMFullResponseEndFrame()
        ende.pts = self._word_last_pts
        await self.push_frame(ende)
