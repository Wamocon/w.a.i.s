"""Nur diese Stimme hören: eine fremde Äußerung (fremd oder unklar mit niedrigem Wert) erreicht das Sprachmodell nicht (Modus streng, nur mit
eingelerntem Abdruck).

Der Wächter sitzt hinter der Spracherkennung und vor dem Aggregator des Nutzers. Er hält ausschließlich das endgültige Transkript einer
Äußerung (TranscriptionFrame) an, bis das Urteil des Prüfers (stimme_pruefer.py) zu genau dieser Äußerung da ist (aeusserung_zuordnen),
höchstens WARTEN_SECS; spätere Äußerungen halten es nicht auf. Die Prüfung beginnt beim Sprechende und läuft parallel zur Spracherkennung,
die Antwortzeit wächst für die eigene Stimme also höchstens um den Rest der Prüfzeit, der über die Wartezeit der Spracherkennung hinausgeht.
Zwischenstände (InterimTranscriptionFrame) hält und ändert der Wächter nie. Steht aber ein endgültiges Transkript bei ihm, warten alle Frames
dahinter in seiner geordneten Warteschlange, auch die Zwischenstände der nächsten Äußerung; nur Systemframes (VAD-Meldungen) laufen vorbei.

Haltezeit und Stop-Strategie: Die Stop-Strategie (TurnAnalyzerUserTurnStopStrategy) wartet nach dem Sprechende nur so lange auf ein
Transkript, wie die Spracherkennung laut STTMetadataFrame braucht (ttfs_p99_latency, bei Soniox 0,35 s). Hält der Wächter länger, beendete sie
einen Zug aus zwei Äußerungen mit dem Text der ersten, während die zweite noch hier stand. Deshalb rechnet der Wächter im Modus streng seine
Haltezeit auf diese Angabe auf. Kosten: Nur wenn zu einer Äußerung gar kein Transkript kommt, endet der Zug um WARTEN_SECS später; ein
endgültiges Transkript beendet ihn wie bisher sofort. WARTEN_SECS bleibt deshalb kurz: Die Prüfung von 8 s Sprache dauert rund 250 ms.

Regel (verwerfen, verschärft am 16.11.2026 nach dem Journal einer Sitzung im Büro): Verworfen wird nur im Modus streng mit bereitem Abdruck
und Modell, und nur, wenn WAMO nicht gleichzeitig sprach (dann ist ein niedriger Wert nur unklar, Echo; siehe StimmGate.einstufen und
Urteil.ueberlappung). Dann gilt:
- fremd (Wert bis WAMO_STIMME_FREMD_MAX, 0,3): verworfen, unabhängig von der Länge. Bis dahin brauchte auch fremd mindestens min_secs
  (1 s) Sprache, deshalb gingen kurze fremde Einwürfe ("0,15 bei 0,4 s") durch.
- unklar mit Wert unter WAMO_STIMME_VERWERFEN_MAX (0,4, liegt von FREMD_MAX bis EIGEN_MIN): verworfen, ebenso unabhängig von der Länge
  ("0,31 bei 1,1 s"). Ein unklares Urteil mit höherem Wert geht durch, ebenso jedes unklare ohne Wert (Prüfung fehlgeschlagen).
- eigen und kurz (Wert ab EIGEN_MIN, 0,5) gehen immer durch: ein kurzes "Ja" der Person ("0,62 bei 0,8 s") wird nie überhört.
- WAMO_STIMME_VERWERFEN_MIN_SECS (Standard 0) verlangt mindestens so viel Sprache für jedes Verwerfen; 1 stellt für kurze Äußerungen das
  Verhalten vor dem 16.11.2026 wieder her, ohne Release.
Alles andere geht durch: kein Urteil in der Frist (Zeitüberschreitung gilt als unklar), beobachten, aus, kein Abdruck. Werkzeuge bleiben
dann trotzdem gesperrt, wenn die Stimme nicht sicher erkannt ist (StimmGate.pruefen).
Eine Äußerung, die so durchgeht, aber nicht sicher die Stimme der Person war, färbt in bot.py den Zug wie Fremdinhalte
(StimmGate.nicht_sicher_eigen): kein Lernen, kein Hinweis des Ja-Wächters, Markierung im Protokoll.

Verwerfen heißt: Das Transkript wird durch ein Leerzeichen ersetzt (ein neues Frame mit demselben Zeitstempel). Der Zug des Nutzers endet
dann leer: kein Satz im Verlauf, nichts für das Gedächtnis, kein Aufruf des Modells. bot.py kehrt in on_user_turn_stopped bei leerem Inhalt
zurück (eine Markierung des Wächters bräuchte es dafür nicht, sie hinge auch an keinem Zug, denn der Behandler läuft als eigene Aufgabe).
Dazu geht eine Meldung an die Oberfläche: {"type": "stimme", "ergebnis": "fremd" | "unklar", "wert", "modus", "ignoriert": true}, einmal je
Urteil; im Log steht "Stimme: fremde (oder unklare) Äußerung ignoriert (Wert bei Sekunden)".

Untertitel: Pipecat meldet jedes Transkript an die Oberfläche, sobald es die Spracherkennung verlässt (RTVIObserver, user-transcription,
nur beim ersten Push eines Frames), also vor dem Urteil. Zwischenstände und das endgültige Transkript stehen deshalb kurz im Untertitel.
Das Ersatztranskript ist ein neues Frame und wird ebenso gemeldet: endgültig, ohne Text, mit dem Zeitstempel des Originals. Die
Oberfläche nimmt damit genau diesen Teil wieder aus dem Untertitel und, falls er schon dort stand, aus dem Verlauf (ui/src/lib/wamo.ts,
nutzerTranskript). Den Zeitstempel deshalb beim Ersetzen nie ändern.

Grenzen: Spricht jemand Fremdes dazwischen, während WAMO redet, ist das Urteil unklar und der Satz geht durch (nur Werkzeuge bleiben
gesperrt). Eine eigene Äußerung mit niedrigem Wert (Erkältung, Lärm, weit vom Mikrofon, sehr kurz) wird verworfen; die Oberfläche zeigt
dann den Hinweis, getippter Text geht immer.

Abbruch durch Zwischenstände (nur_endgueltig): Schon ein Zwischenstand startet in der Startstrategie den Zug, und spricht WAMO nicht,
bricht das SoftInterruptGate sofort hart ab, bevor ein Urteil da ist. Eine fremde Stimme hätte so eine laufende Antwort oder ein Werkzeug
abgebrochen, danach verwarf der Wächter ihr Transkript und WAMO schwieg. Deshalb startet im Modus streng mit bereitem Abdruck, solange WAMO
nicht spricht, aber das Modell an einer Antwort arbeitet oder ein Werkzeug läuft, erst das endgültige Transkript nach dem Urteil den Zug
(soft_interrupt.MeaningfulWordsUserTurnStartStrategy, nur_endgueltig). Abwägung: Die eigene Stimme bricht dort etwas später ab (nach
Sprechende, Erkennung und Urteil), und weil der Zug erst dann beginnt, entscheidet die Stop-Strategie das Satzende ohne Smart-Turn (sie
wartet ihre Frist ab, mit der Haltezeit bei Soniox rund 1,2 s; ein Werkzeug oder eine Antwort ist da schon abgebrochen). Beim
Sprechen bleibt der schnelle Weg über Zwischenstände, denn dort muss WAMO auf "Stopp" sofort hören; eine fremde Stimme ist dann meist
unklar (Echo, Überlappung) und kostet höchstens den Rest des Satzes. Läuft nichts, bleibt ebenfalls alles wie bisher: Ein Abbruch schadet
dort nicht, und die Erkennung des Satzendes braucht den Zug ab dem ersten Wort.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from loguru import logger

from pipecat.frames.frames import Frame, STTMetadataFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from stimme_gate import FREMD, UNKLAR, Schwellen, StimmGate

if TYPE_CHECKING:
    from stimme_pruefer import Urteil

WARTEN_SECS = 1.0  # so lange hält das endgültige Transkript höchstens auf das Urteil (geht in die Frist der Stop-Strategie ein)
SATZZEICHEN = (".", "!", "?", "…")  # so endet ein fertiger Satz im Transkript
_LOG_ART = {FREMD: "fremde", UNKLAR: "unklare"}


def _satz_fertig(text: str) -> bool:
    return text.rstrip().endswith(SATZZEICHEN)


def verwerfen(urteil: Urteil | None, schwellen: Schwellen) -> bool:
    """Soll der Wächter das Transkript zu diesem Urteil verwerfen (Regel oben)? Fragt nur nach dem Urteil; Modus und Abdruck prüft der
    Wächter vorher (aktiv). None (keine Antwort in der Frist), kein Wert (Prüfung fehlgeschlagen) und Überlappung mit WAMO: nie."""
    if urteil is None or urteil.wert is None or urteil.ueberlappung or urteil.secs < schwellen.verwerfen_min_secs:
        return False
    if urteil.urteil == FREMD:
        return True
    return urteil.urteil == UNKLAR and urteil.wert < schwellen.verwerfen_max


def nur_endgueltig(waechter: StimmWaechter, *beschaeftigt: Callable[[], bool]) -> Callable[[], bool]:
    """Abfrage für die Startstrategie (siehe oben): ja, wenn der Wächter verwerfen kann und eine der Arbeiten läuft (Werkzeug, Modell)."""
    return lambda: waechter.aktiv() and any(laeuft() for laeuft in beschaeftigt)


class StimmWaechter(FrameProcessor):
    def __init__(self, gate: StimmGate, pruefer, *, warten: float = WARTEN_SECS, **kwargs):
        super().__init__(**kwargs)
        self._gate = gate
        self._pruefer = pruefer
        self._warten = warten
        self._gemeldet_nr = 0

    def aktiv(self) -> bool:
        """Kann der Wächter verwerfen (Modus streng, Abdruck und Modell bereit)?"""
        return self._gate.modus == "streng" and self._gate.status == "bereit"

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, STTMetadataFrame) and self._gate.modus == "streng":
            # Die Stop-Strategie soll auf ein Transkript warten, das hier noch auf sein Urteil steht (siehe oben). Nur der Modus zählt: Der
            # Abdruck lädt erst nach dem Start, und diese Angabe kommt nur einmal.
            frame = replace(frame, ttfs_p99_latency=(frame.ttfs_p99_latency or 0.0) + self._warten)
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame):
            if frame.text.strip():
                # in jedem Modus, auch ohne Abdruck: nach diesem Transkript gilt Getipptes nicht mehr für die Pflichtstufe der Mitglieder
                # (stimme_gate.pflicht_grund), auch wenn die Sprachpausenerkennung die Äußerung nicht gemeldet hat. Getippter Text kommt
                # nie als Transkript (Pipecat: LLMMessagesAppendFrame)
                self._gate.gesprochen()
            if _satz_fertig(frame.text):
                self._pruefer.satz_ende()  # was danach gesprochen wird, gehört nicht mehr zu diesem Satz (auch wenn er verworfen wird)
            if self.aktiv():
                frame = await self._pruefen(frame)
        await self.push_frame(frame, direction)

    async def _pruefen(self, frame: TranscriptionFrame) -> TranscriptionFrame:
        if not frame.text.strip():
            return frame
        # Eine Unterbrechung (die Person fällt WAMO ins Wort) bricht in Pipecat das Frame ab, das ein Verarbeiter gerade bearbeitet. Während des
        # Wartens gehört das Transkript aber der Person: es darf nicht verloren gehen.
        frame.interruptible = False
        nr = self._pruefer.aeusserung_zuordnen()  # die Äußerung zu diesem Transkript, nicht die jüngste
        urteil = await self._pruefer.urteil_abwarten(self._warten, nr)  # None: Frist abgelaufen oder nichts geprüft, gilt als unklar
        if urteil is None or urteil.wert is None or not verwerfen(urteil, self._gate.schwellen):
            return frame
        if urteil.nr != self._gemeldet_nr:
            self._gemeldet_nr = urteil.nr
            wert = float(urteil.wert)
            logger.info("Stimme: {} Äußerung ignoriert ({:.2f} bei {:.1f} s)", _LOG_ART.get(urteil.urteil, urteil.urteil), wert, urteil.secs)
            await self.push_frame(RTVIServerMessageFrame(data={
                "type": "stimme", "ergebnis": urteil.urteil, "wert": round(wert, 2), "modus": self._gate.modus, "ignoriert": True,
            }))
        # Ein neues Frame: Beobachter der Pipeline halten das Original. Der Zeitstempel bleibt, die Oberfläche nimmt damit den schon
        # gezeigten Untertitel zurück (siehe oben)
        return replace(frame, text=" ", result=None)
