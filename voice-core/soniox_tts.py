"""Soniox-TTS, das seinen Stream erst beim ersten Text oeffnet.

Pipecat oeffnet den Soniox-Stream schon, wenn Claude zu antworten beginnt (on_turn_context_created),
damit der erste Ton schneller kommt. Braucht Claude aber lange (am 17.10.2026 einmal 13 s), laeuft der
leere Stream in Soniox' Leerlauf-Timeout: erst "408 request_timeout", dann "400 Stream not found",
und die Antwort bleibt stumm. Hier wird der Stream deshalb erst mit dem ersten Satz geoeffnet.
Kostet ein paar Millisekunden, verliert aber keine Antworten mehr.

Zeit bis zum ersten Ton (Messung: latenz.py, WAMO_LATENZ_LOG=1): Soniox beginnt im Stream erst zu sprechen, wenn rund
65 Zeichen (ohne Leerraum) eingegangen sind oder text_end kommt (Direktverbindung am 21.10.2026: 62 Zeichen warten bis
text_end, 66 starten nach 285 ms; Leerzeichen und Zeilenumbrueche zaehlen nicht). Pipecat gibt den Text satzweise weiter,
bei einem langen ersten Satz ("Eins, zwei, drei, ...") wartet der erste Ton deshalb bis zum Satzende. Der Aggregator
hier gibt den Text schon an einer Wortgrenze frei, sobald die Schwelle erreicht ist (WAMO_TTS_START_ZEICHEN, Standard
68, 0 = Pipecat-Standard). Die Fuge ist fuer Soniox unsichtbar, es sieht einen durchgehenden Text.

Rueckhalt am Textende (Messung 22.10.2026, direkte Verbindung): Soniox spricht nur Text, hinter dem noch etwa 65 Zeichen
Vorschau stehen, oder alles bis text_end. Der Rest eines Satzes erklingt erst, wenn der naechste Text oder text_end eintrifft
(Satz A 95 Zeichen, Satz B 3 s spaeter: Pause von 2 s mitten in A; Satz B allein erklingt erst mit text_end). Solange das
Modell schneller liefert als WAMO spricht, merkt man nichts davon; bei langsamem Modell oder einem Werkzeugaufruf mitten in
der Antwort entsteht daraus Stille. Dagegen hilft der Wartesatz (wartesatz.py), nicht ein anderer Aggregator.

Satzende (WAMO_TTS_SATZLEERZEICHEN, Standard aus bis zur Messung): Pipecat reicht jeden Satz ohne Leerzeichen am Ende
an Soniox. Das Textende ohne Leerraum kann Soniox mit dem Anfang des nächsten Satzes verkleben ("Nutzung.Ich") und das
Satzzeichen vorlesen. fuer_soniox hängt deshalb ein Leerzeichen an; es zählt nicht mit (siehe 65-Zeichen-Schwelle) und
steht nicht im Verlauf, denn der Verlauf kommt aus den Wort-Zeitstempeln.

Stimme, Tempo und Pausen (stimme_einstellung): SONIOX_VOICE, SONIOX_SPEED (0,7 bis 1,3) und SONIOX_REDUCE_SILENCE kommen aus
der Umgebung; leer bleibt die Standardeinstellung von Pipecat und Soniox. Welche Stimme gilt, entscheidet die Hörprobe, nicht
dieser Code.

Gemessen und verworfen: den Stream frueher oeffnen (234 ms bis zum ersten Audio, ob die Konfiguration mit dem Text oder
0,3 s vorher kommt), den Text tokenweise reichen (Pipecat-Modus TOKEN: nach einer Unterbrechung stand nur ein Wort im
Verlauf, Oberflaeche und Kontext waeren falsch) und einen Satzteil am Komma freigeben (unter der Schwelle startet
Soniox nichts).

Pause im Antwortstrom (Befund im Journal des Kerns am 17.11.2026, Hausmodell gemma4-31b über LiteLLM): Das Gateway liefert einen
Werkzeugaufruf erst als ganzen Block, während das Modell ihn schreibt, kommt kein Zeichen. Lag schon ein kurzer Satz bei Soniox, hielt
Soniox ihn zurück (Rückhalt am Textende), und Pipecat erklärte den Kontext nach stop_frame_timeout_s (3 s) ohne Ton für beendet:
"audio context ... completed with no audio", ein ErrorFrame bis in die Oberfläche, ein eigenes Antwortende vor dem des Modells, Wörter
fielen aus dem Verlauf. Der Stream blieb bei Soniox offen und endete rund 10 s später mit 408 request_timeout (noch ein ErrorFrame).
Nach drei solchen Kontexten in Folge schreibt Pipecat die Sprachausgabe ganz ab (max_consecutive_zero_audio_contexts), die Sitzung
wäre dann stumm. Deshalb:
  * Ein offener Stream (Text bei Soniox, noch kein text_end) wird nach STILLE_ABSCHLUSS_SECS ohne neuen Text des Modells
    abgeschlossen, wie beim Satz vor dem Werkzeug (satz_vor_werkzeug.py): Rest des Aggregators in denselben Stream, dann text_end.
    Soniox spricht sofort, weiterer Text derselben Antwort öffnet einen neuen Stream. Ohne offenen Stream ändert sich nichts.
  * Solange das Modell Text liefert (auch nur in den Aggregator), bleibt der Kontext des offenen Streams wach (Pipecats Wartezeit
    beginnt mit jedem Text von vorn).
  * Text ohne Buchstaben und Ziffern (Leerraum, Satzende-Marker, Satzzeichen) öffnet keinen Stream: Soniox spricht ihn nicht, der
    Kontext bliebe ohne Ton.

Neuverbindung kurz nach dem Start (Journal 17.11.2026: "connection closed by server", dann "reconnecting (attempt: 1)", rund 11 s nach
jedem Sitzungsstart): Soniox schließt die Verbindung, wenn nach der Begrüßung kein Stream mehr läuft, früher als in seiner Doku (dort
rund 40 s ohne Stream und ohne Nachricht); Pipecats keep_alive kommt erst nach 20 s. Pipecat verbindet sofort neu, und weil die
Verbindung länger als 5 s hielt, zählt das nicht als Schnellfehler. Ohne laufenden Stream bleibt das folgenlos: der nächste Satz
öffnet seinen Stream auf der neuen Verbindung. Fiele die Neuverbindung in eine laufende Antwort, verwürfe Pipecat den gerade
spielenden Kontext (remove_active_audio_context) und vergäße offene Streams. Im Leerlauf folgenlos, deshalb nicht geändert; trifft
es doch eine Antwort, wäre ein früheres keep_alive die Abhilfe.
"""

from __future__ import annotations

import asyncio
import os
import time

from loguru import logger
from websockets.protocol import State

from env_schalter import schalter_an, schalter_oder_none, zahl_im_bereich
from satz_vor_werkzeug import SatzVorWerkzeugFrame, SatzVorWerkzeugTTS

from pipecat.frames.frames import (
    AggregatedTextFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.soniox.tts import SonioxTTSService
from pipecat.services.tts_service import TextAggregationMode
from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

START_ZEICHEN_STANDARD = 68
# Stille des Modells, nach der ein offener Stream abgeschlossen wird. Unter Pipecats Wartezeit auf Ton (3 s), damit Soniox danach
# noch Zeit für den ersten Ton bleibt; länger als die Pause zwischen zwei Tokens eines langsamen Modells (gemma4-31b, rund 10 Token/s).
STILLE_ABSCHLUSS_SECS = 1.0
_uhr = time.monotonic  # Zeitquelle der Stille, in Tests ersetzbar
# Frames, deren Verarbeitung Text an Soniox schicken oder den Stream schließen kann: nie gleichzeitig mit dem Stille-Abschluss
_TEXT_FRAMES = (TextFrame, AggregatedTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame, SatzVorWerkzeugFrame)
TEMPO_MIN, TEMPO_MAX = 0.7, 1.3  # Bereich, den Soniox für speed annimmt


def satz_leerzeichen_an(wert: str | None = None) -> bool:
    """WAMO_TTS_SATZLEERZEICHEN: Leerzeichen am Ende jedes Textstücks für Soniox (Standard aus, bis gemessen)."""
    return schalter_an("WAMO_TTS_SATZLEERZEICHEN", wert)


def fuer_soniox(text: str, an: bool | None = None) -> str:
    """Der Text, wie er an Soniox geht: mit einem Leerzeichen am Ende, damit das Satzzeichen nicht mit dem nächsten Satz
    verklebt und vorgelesen wird. an=None liest den Schalter. Leerer Text und Text mit Leerraum am Ende bleiben unverändert."""
    if not (satz_leerzeichen_an() if an is None else an):
        return text
    return text if not text or text[-1].isspace() else text + " "


def stimme_einstellung(speed: str | None = None, reduce_silence: str | None = None) -> dict:
    """Zusätzliche Einstellungen der Stimme aus der Umgebung: speed (SONIOX_SPEED, 0,7 bis 1,3) und reduce_silence
    (SONIOX_REDUCE_SILENCE, an oder aus). Nur gesetzte und gültige Werte stehen im Ergebnis; ein ungültiger Wert wird
    mit Warnung ignoriert, die Stimme bleibt dann beim Standard. Die Parameter ersetzen die Umgebung (für Tests)."""
    out: dict = {}
    tempo = zahl_im_bereich("SONIOX_SPEED", TEMPO_MIN, TEMPO_MAX, speed)
    if tempo is not None:
        out["speed"] = tempo
    pausen = schalter_oder_none("SONIOX_REDUCE_SILENCE", reduce_silence)
    if pausen is not None:
        out["reduce_silence"] = pausen
    return out


def start_zeichen(wert: str | None = None) -> int:
    """Zeichen ohne Leerraum, ab denen der erste Text an Soniox geht (WAMO_TTS_START_ZEICHEN), 0 = aus."""
    w = os.getenv("WAMO_TTS_START_ZEICHEN") if wert is None else wert
    if w is None or not w.strip():
        return START_ZEICHEN_STANDARD
    try:
        return max(0, int(w.strip()))
    except ValueError:
        return START_ZEICHEN_STANDARD


def sprechbar(text: str) -> bool:
    """Hat der Text etwas, das Soniox spricht (Buchstabe oder Ziffer)? Leerraum, Satzende-Marker (●, ◐, ○), Satz- und Sonderzeichen
    allein ergeben bei Soniox keinen Ton."""
    return any(c.isalnum() for c in text)


def _zeichen(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


class StartAggregator(SimpleTextAggregator):
    """Satz-Aggregator, der den Anfang einer Antwort an einer Wortgrenze freigibt, sobald Soniox genug Text hat.

    Zaehlt je Antwort die Zeichen (ohne Leerraum), die schon an die Sprachausgabe gingen. Erreichen sie mit dem Puffer
    die Schwelle, geht der Puffer ohne Satzende raus; danach gilt wieder die Satzgrenze. Kurze Antworten bleiben
    unveraendert (sie erreichen die Schwelle nie, Soniox wartet dann auf text_end)."""

    def __init__(self, *, schwelle: int = START_ZEICHEN_STANDARD, **kwargs):
        super().__init__(**kwargs)
        self._schwelle = schwelle
        self._gesendet = 0

    async def _check_sentence_with_lookahead(self, char: str) -> Aggregation | None:
        satz = await super()._check_sentence_with_lookahead(char)
        if satz is not None:
            self._gesendet += _zeichen(satz.text)
            return satz
        if self._gesendet >= self._schwelle or not char.isspace() or self._text[-2:-1].isspace():
            return None
        if self._gesendet + _zeichen(self._text) < self._schwelle:
            return None
        teil = self._text.strip()
        await SimpleTextAggregator.reset(self)  # Puffer und Vorschau leeren, Zaehler bleibt
        self._gesendet += _zeichen(teil)
        # Mit Leerzeichen am Ende: Pipecat reicht den Text unverändert an Soniox, der Rest des Satzes beginnt ohne Leerzeichen.
        # An einer Satzgrenze trennt das Satzzeichen die Teile, hier mitten im Satz müsste sonst "des" + "Landes" zu "desLandes"
        # werden.
        return Aggregation(text=teil + " ", type=AggregationType.SENTENCE)

    async def flush(self) -> Aggregation | None:
        try:
            return await super().flush()
        finally:
            self._gesendet = 0

    async def handle_interruption(self):
        await super().handle_interruption()
        self._gesendet = 0

    async def reset(self):
        await super().reset()
        self._gesendet = 0


class LazySonioxTTSService(SatzVorWerkzeugTTS, SonioxTTSService):
    # Beginnt ein Werkzeugaufruf (satz_vor_werkzeug.py): Rest des Aggregators sofort an Soniox und den Stream mit text_end
    # abschließen, damit Soniox auch einen kurzen Satz sofort spricht (Rückhalt am Textende, siehe oben). Weiterer Text derselben
    # Antwort öffnet einen neuen Stream (run_tts schickt die Konfiguration für jeden neuen Kontext), Text nach dem Werkzeug kommt
    # in einer neuen Antwort und damit ohnehin in einem neuen Stream.
    stream_vor_werkzeug_beenden = True
    stille_abschluss_secs = STILLE_ABSCHLUSS_SECS
    wamo_stille_abgeschlossen = 0  # für Tests und das Log
    _wamo_letzter_text = 0.0  # _uhr(): letzter Text des Modells an diese Sprachausgabe
    _wamo_stille_waechter: asyncio.Task | None = None

    def _stream_abgeschlossen(self, context_id: str) -> None:
        # Nach text_end kein cancel mehr für diesen Stream, auch nicht bei einer Unterbrechung (Pipecat, SonioxTTSService._close_stream:
        # "Do not call after text_end:true"); Ton, der danach noch für ihn kommt, verwirft der Empfang, weil der Kontext dann fehlt.
        self._configured_contexts.discard(context_id)

    def __init__(self, *args, start: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        schwelle = start_zeichen() if start is None else start
        if schwelle > 0 and self._text_aggregation_mode == TextAggregationMode.SENTENCE:
            self._text_aggregator = StartAggregator(
                schwelle=schwelle,
                aggregation_type=self._text_aggregation_mode,
                language=self._text_aggregator.language,
            )
        self._wamo_sperre = asyncio.Lock()  # Text an Soniox und der Stille-Abschluss nie gleichzeitig

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, InterruptionFrame):
            await self._stille_waechter_beenden()  # den Stream verwirft Pipecat selbst (cancel)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, _TEXT_FRAMES):
            async with self._wamo_sperre:
                await super().process_frame(frame, direction)
            if isinstance(frame, TextFrame):
                self._wamo_letzter_text = _uhr()
                self._wach_halten(self._offener_stream())
            return
        await super().process_frame(frame, direction)

    async def _push_tts_frames(self, src_frame: AggregatedTextFrame, *args, **kwargs):
        # Nur im Satzmodus: beim Streamen einzelner Tokens gehört ein Satzzeichen zum Satz. Aggregationen, die Pipecat ohnehin nicht
        # spricht (skip_aggregator_types), behandelt Pipecat selbst.
        if (not self._is_streaming_tokens and src_frame.aggregated_by not in self._skip_aggregator_types
                and not sprechbar(src_frame.text)):
            if src_frame.text.strip():
                logger.debug("{}: kein sprechbarer Text, kein Stream ({} Zeichen)", self, len(src_frame.text.strip()))
            return
        await super()._push_tts_frames(src_frame, *args, **kwargs)

    def _offener_stream(self) -> str | None:
        """Stream dieser Antwort, der Text bekommen hat und noch auf text_end wartet, sonst None."""
        kontext = self._turn_context_id
        if kontext and self.audio_context_available(kontext) and kontext in self._configured_contexts:
            return kontext
        return None

    def _wach_halten(self, kontext: str | None) -> None:
        """Pipecats Wartezeit auf Ton für diesen Kontext beginnt von vorn (Pipecat 1.12, _refresh_audio_context; fehlt es, bleibt es beim
        Stille-Abschluss)."""
        wach = getattr(self, "_refresh_audio_context", None)
        if kontext is not None and wach is not None:
            wach(kontext)

    def _stille_waechter_starten(self) -> None:
        if self._wamo_stille_waechter is None or self._wamo_stille_waechter.done():
            self._wamo_stille_waechter = self.create_task(self._stille_waechter(), name="stille_abschluss")

    async def _stille_waechter_beenden(self) -> None:
        waechter, self._wamo_stille_waechter = self._wamo_stille_waechter, None
        if waechter is not None and not waechter.done() and waechter is not asyncio.current_task():
            await self.cancel_task(waechter)

    async def _stille_waechter(self) -> None:
        """Läuft, solange ein Stream offen ist. Schweigt das Modell stille_abschluss_secs, geht der Rest des Aggregators in den Stream,
        und der Stream bekommt text_end (derselbe Weg wie beim Satz vor dem Werkzeug)."""
        while self._offener_stream() is not None:
            rest = self._wamo_letzter_text + self.stille_abschluss_secs - _uhr()
            if rest > 0:
                await asyncio.sleep(rest)
                continue
            async with self._wamo_sperre:
                kontext = self._offener_stream()
                if kontext is None or _uhr() - self._wamo_letzter_text < self.stille_abschluss_secs:
                    continue  # inzwischen abgeschlossen oder neuer Text: neu prüfen
                self.wamo_stille_abgeschlossen += 1
                await self._vor_werkzeug_sprechen(anlass="Modell schweigt")
                self._wach_halten(kontext if self.audio_context_available(kontext) else None)  # volle Wartezeit für den ersten Ton
            return

    async def cleanup(self):
        await self._stille_waechter_beenden()
        await super().cleanup()

    async def on_turn_context_created(self, context_id: str):
        # Bewusst nichts tun: kein Stream ohne Text (siehe Modul-Docstring).
        return

    async def run_tts(self, text: str, context_id: str):
        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()
            await self._send_config(context_id)  # idempotent, nur beim ersten Satz wirksam
        except Exception as e:
            logger.warning(f"{self}: Soniox-Stream {context_id} konnte nicht geoeffnet werden: {e}")
        async for frame in super().run_tts(fuer_soniox(text), context_id):
            yield frame
        if context_id == self._turn_context_id:  # Text einer Antwort des Modells (ein TTSSpeakFrame bekommt sofort text_end)
            self._wamo_letzter_text = max(self._wamo_letzter_text, _uhr())
            self._stille_waechter_starten()
