"""Nur diese Stimme hören: Im Modus streng mit eingelerntem Abdruck erreicht nur eine eigene Äußerung das Sprachmodell, und während WAMO
spricht, unterbricht nur die eigene Stimme (Entscheidung von Niko vom 17.11.2026). Alle anderen Stimmen ignoriert WAMO.

Der Wächter sitzt hinter der Spracherkennung und vor dem Aggregator des Nutzers. Er hält ausschließlich das endgültige Transkript einer
Äußerung (TranscriptionFrame) an, bis das Urteil des Prüfers (stimme_pruefer.py) zu genau dieser Äußerung da ist (aeusserung_zuordnen),
höchstens WARTEN_SECS; spätere Äußerungen halten es nicht auf. Die Prüfung beginnt beim Sprechende und läuft parallel zur Spracherkennung,
die Antwortzeit wächst für die eigene Stimme also höchstens um den Rest der Prüfzeit, der über die Wartezeit der Spracherkennung hinausgeht.
Zwischenstände (InterimTranscriptionFrame) hält und ändert der Wächter nie. Steht aber ein endgültiges Transkript bei ihm, warten alle Frames
dahinter in seiner geordneten Warteschlange, auch die Zwischenstände der nächsten Äußerung; nur Systemframes (VAD-Meldungen, Urteile des
Prüfers) laufen vorbei.

Haltezeit und Stop-Strategie: Die Stop-Strategie (TurnAnalyzerUserTurnStopStrategy) wartet nach dem Sprechende nur so lange auf ein
Transkript, wie die Spracherkennung laut STTMetadataFrame braucht (ttfs_p99_latency, bei Soniox 0,35 s). Hält der Wächter länger, beendete sie
einen Zug aus zwei Äußerungen mit dem Text der ersten, während die zweite noch hier stand. Deshalb rechnet der Wächter im Modus streng seine
Haltezeit auf diese Angabe auf. Kosten: Nur wenn zu einer Äußerung gar kein Transkript kommt, endet der Zug um WARTEN_SECS später; ein
endgültiges Transkript beendet ihn wie bisher sofort. WARTEN_SECS bleibt deshalb kurz: Die Prüfung von 8 s Sprache dauert rund 250 ms.
Nachfrist: Würde ein Transkript ohne Urteil verworfen (nur eigen, siehe unten), wartet der Wächter vorher noch NACHFRIST_SECS, denn der
Rechner ist für alle Sitzungen einer und kann belegt sein. Kommt das Urteil so spät, kann der Zug schon ohne diesen Satz geendet haben; der
Satz beginnt dann einen eigenen Zug. Das ist besser, als einen eigenen Satz still zu verlieren. Mit Urteil oder ohne Verwerfen gibt es
keine Nachfrist.

Regel (verwerfen), nur im Modus streng mit bereitem Abdruck und Modell (StimmGate.verwirft):
- WAMO_STIMME_NUR_EIGEN (an oder aus, Standard an): Es geht nur durch, was eigen ist, also einen Wert ab EIGEN_MIN (0,5) hat, auch ein kurzes
  eigenes "Ja" (Urteil kurz). Verworfen wird alles andere: fremd, unklar mit jedem Wert, unklar ohne Wert (Prüfung fehlgeschlagen) und
  keine Antwort des Prüfers in der Frist. WAMO_STIMME_VERWERFEN_MAX und WAMO_STIMME_VERWERFEN_MIN_SECS wirken dann nicht.
- Mit WAMO_STIMME_NUR_EIGEN=aus gilt die Regel vom 16.11.2026: fremd (Wert bis WAMO_STIMME_FREMD_MAX, 0,3) immer verworfen, unklar nur unter
  WAMO_STIMME_VERWERFEN_MAX (0,4); unklar ohne Wert und keine Antwort in der Frist gehen durch; WAMO_STIMME_VERWERFEN_MIN_SECS (Standard 0)
  verlangt mindestens so viel Sprache für jedes Verwerfen.
- Sprach WAMO gleichzeitig (Überlappung, Urteil.ueberlappung; ohne Urteil zählt, ob WAMO beim Eintreffen des Transkripts sprach): Mit
  WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN (an oder aus, Standard an) gilt auch dann nur eigen, unabhängig vom Schalter oben. Mit aus wie vor dem
  17.11.2026: ein niedriger Wert ist dort nur unklar (Echo), der Satz geht durch.
- Hat das frühe Urteil diese Äußerung als eigen erkannt und WAMO deshalb unterbrochen (Stimmpruefer.frueh_eigen), geht sie durch, auch wenn
  das Urteil am Sprechende schwächer ausfällt (Echo am Anfang, eine zweite Stimme); sonst schwiege WAMO nach dem Abbruch. Werkzeuge sperrt
  das Gate dann weiter nach dem Urteil am Sprechende, und der Zug ist wie Fremdinhalt gefärbt.
Nichts wird verworfen im Modus beobachten oder aus, ohne Abdruck, solange Abdruck oder Modell nicht bereit sind, und nie für Laborprofile
(sie bekommen gar keine Stimmsitzung, stimme_sitzung.StimmSitzung.fuer). Werkzeuge bleiben trotzdem gesperrt, wenn die Stimme nicht sicher
erkannt ist (StimmGate.pruefen). Eine Äußerung, die durchgeht, aber nicht sicher die Stimme der Person war (mit WAMO_STIMME_NUR_EIGEN=aus,
oder ein kurzes eigenes "Ja" direkt nach fremder Rede), färbt in bot.py den Zug wie Fremdinhalte (StimmGate.nicht_sicher_eigen): kein
Lernen, kein Hinweis des Ja-Wächters, Markierung im Protokoll.

Verwerfen heißt: Das Transkript wird durch ein Leerzeichen ersetzt (ein neues Frame mit demselben Zeitstempel). Der Zug des Nutzers endet
dann leer: kein Satz im Verlauf, nichts für das Gedächtnis, kein Aufruf des Modells. bot.py kehrt in on_user_turn_stopped bei leerem Inhalt
zurück (eine Markierung des Wächters bräuchte es dafür nicht, sie hinge auch an keinem Zug, denn der Behandler läuft als eigene Aufgabe).
Im Log steht "Stimme: fremde (oder unklare) Äußerung ignoriert (Wert bei Sekunden)", nie ein Inhalt.

Meldung an die Oberfläche nach jedem Urteil zu einem endgültigen Transkript mit Text (nur wenn der Wächter verwerfen kann): {"type": "stimme",
"ergebnis": "eigen" | "fremd" | "unklar", "wert": Zahl oder null, "modus", "ignoriert": true | false, "zeit"}. kurz heißt in der Meldung
unklar (wie beim Prüfer), keine Antwort in der Frist ebenso (wert null). zeit ist genau der Text, den dasselbe Transkript in der RTVI-Meldung
user-transcription als timestamp trägt: Pipecats RTVIObserver gibt TranscriptionFrame.timestamp unverändert aus, der Wächter nimmt denselben
Wert (höchstens ZEIT_MAX Zeichen, sonst null; kürzen ginge nicht, dann passte er nicht mehr). Der Chat links hält jeden gesprochenen Teil
zurück, bis die Meldung mit seiner zeit kommt (ui/src/lib/stimmFilter.ts): ignoriert false zeigt ihn, true verwirft ihn. Deshalb kommt
ignoriert false zu jedem Transkript, ignoriert true nur einmal je Äußerung (der Hinweis der Oberfläche zählt jede Meldung); weitere
verworfene Teile derselben Äußerung nimmt das Ersatztranskript zurück.

Untertitel: Pipecat meldet jedes Transkript an die Oberfläche, sobald es die Spracherkennung verlässt (RTVIObserver, user-transcription,
nur beim ersten Push eines Frames), also vor dem Urteil. Zwischenstände und das endgültige Transkript stehen deshalb kurz im Untertitel,
wenn die Person ihn eingeschaltet hat. Das Ersatztranskript ist ein neues Frame und wird ebenso gemeldet: endgültig, ohne Text, mit dem
Zeitstempel des Originals. Die Oberfläche nimmt damit genau diesen Teil wieder aus dem Untertitel und, falls er schon dort stand, aus dem
Verlauf (ui/src/lib/wamo.ts, nutzerTranskript). Den Zeitstempel deshalb beim Ersetzen nie ändern.

Unterbrechen nur durch die eigene Stimme (WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN, nur mit StimmGate.nur_eigen_unterbricht): Beginnt jemand zu
sprechen, während WAMO spricht, dämpft das SoftInterruptGate die Stimme sofort wie bisher (Ducken), bricht aber noch nicht ab. Die
Startstrategie fragt nur_eigen_unterbricht: Solange die laufende Äußerung nicht als eigen erkannt ist, wartet jeder Zwischenstand, auch ein
Stoppwort ("Stopp"). Das Urteil kommt vom Prüfer so früh wie verlässlich: nach einer Sekunde Sprache und dann jede Sekunde über die letzten
zwei Sekunden der laufenden Äußerung (frühes Urteil, nur eigen zählt), sonst am Sprechende (Begründung in stimme_pruefer.py). Eigen: der
wartende Zwischenstand wird wie bisher bewertet (Rückmeldung, Stoppwort, Mindestzahl der Wörter, Echo) und unterbricht weich, der Satz geht
ans Modell. Nicht eigen (fremd, unklar, keine Antwort): kein Abbruch, die Dämpfung endet sofort, WAMO spricht weiter, und dieser Wächter
verwirft das Transkript (kein Zug, kein Verlauf). Gewollter Preis: Die eigene Stimme unterbricht rund 0,5 bis 1 Sekunde später als bisher
(lange Äußerungen nach gut einer Sekunde, ein kurzes "Stopp" erst nach dem Sprechende plus der Pause der Sprachpausenerkennung).

Grenzen: Eine eigene Äußerung mit niedrigem Wert (Erkältung, Lärm, weit vom Mikrofon, sehr kurz) wird verworfen, und während WAMO spricht,
unterbricht sie WAMO dann nicht; die Oberfläche zeigt den Hinweis, getippter Text geht immer. Mit Lautsprechern statt Headset hört das
Mikrofon WAMO mit: Ein Einwurf mischt sich mit dem Echo, der Wert sinkt, und ein kurzes eigenes "Stopp" kann dann unter EIGEN_MIN fallen.
Hält das Echo die Sprachpausenerkennung dauerhaft offen, gibt es kein Sprechende und nur die frühen Urteile. Beginnt der Zug erst mit dem
Urteil am Sprechende (kurzes "Stopp"), hat die Stop-Strategie das Sprechende schon verpasst: sie entscheidet das Satzende ohne Smart-Turn
und wartet ihre Frist ab (mit der Haltezeit bei Soniox rund 1,2 s nach dem Transkript), die Antwort auf ein kurzes eigenes "Stopp" kommt
also rund eine Sekunde später als bisher; WAMO selbst verstummt schon an der nächsten Wortgrenze nach dem Urteil.

Abbruch durch Zwischenstände, während WAMO nicht spricht (nur_endgueltig): Schon ein Zwischenstand startet in der Startstrategie den Zug,
und spricht WAMO nicht, bricht das SoftInterruptGate sofort hart ab, bevor ein Urteil da ist. Eine fremde Stimme hätte so eine laufende
Antwort oder ein Werkzeug abgebrochen, danach verwarf der Wächter ihr Transkript und WAMO schwieg. Deshalb startet im Modus streng mit
bereitem Abdruck, solange WAMO nicht spricht, aber das Modell an einer Antwort arbeitet oder ein Werkzeug läuft, erst das endgültige
Transkript nach dem Urteil den Zug (soft_interrupt.MeaningfulWordsUserTurnStartStrategy, nur_endgueltig). Abwägung: Die eigene Stimme bricht
dort etwas später ab (nach Sprechende, Erkennung und Urteil), und weil der Zug erst dann beginnt, entscheidet die Stop-Strategie das
Satzende ohne Smart-Turn (sie wartet ihre Frist ab, mit der Haltezeit bei Soniox rund 1,2 s; ein Werkzeug oder eine Antwort ist da schon
abgebrochen). Läuft nichts, bleibt alles wie bisher: Ein Abbruch schadet dort nicht, und die Erkennung des Satzendes braucht den Zug ab dem
ersten Wort.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from loguru import logger

from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame, STTMetadataFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from stimme_gate import EIGEN, FREMD, KURZ, UNKLAR, Schwellen, StimmGate

if TYPE_CHECKING:
    from stimme_pruefer import Urteil

WARTEN_SECS = 1.0  # so lange hält das endgültige Transkript höchstens auf das Urteil (geht in die Frist der Stop-Strategie ein)
NACHFRIST_SECS = 1.0  # so lange wartet es danach noch, bevor es ohne Urteil verworfen würde (siehe oben)
ZEIT_MAX = 64  # so lang darf zeit in der Meldung höchstens sein (die Oberfläche lehnt Längeres ab, ui/src/lib/nachrichten.ts)
SATZZEICHEN = (".", "!", "?", "…")  # so endet ein fertiger Satz im Transkript
_LOG_ART = {FREMD: "fremde", UNKLAR: "unklare"}


def _satz_fertig(text: str) -> bool:
    return text.rstrip().endswith(SATZZEICHEN)


def ist_eigen(urteil: Urteil | None) -> bool:
    """Klingt die Äußerung nach der Person (Wert ab EIGEN_MIN)? Das Urteil kurz zählt mit, ein kurzes eigenes "Ja" wird nie überhört."""
    return urteil is not None and urteil.urteil in (EIGEN, KURZ)


def verwerfen(urteil: Urteil | None, schwellen: Schwellen, *, waehrend_rede: bool = False, frueh_eigen: bool = False) -> bool:
    """Soll der Wächter das Transkript zu diesem Urteil verwerfen (Regel oben)? Fragt nur nach dem Urteil; Modus und Abdruck prüft der
    Wächter vorher (aktiv). None: keine Antwort in der Frist. waehrend_rede: WAMO sprach, als das Transkript ohne Urteil ankam (zählt dann
    wie Überlappung). frueh_eigen: das frühe Urteil hat diese Äußerung als eigen erkannt und WAMO deshalb unterbrochen."""
    if frueh_eigen:
        return False
    ueberlappung = urteil.ueberlappung if urteil is not None else waehrend_rede
    if ueberlappung and not schwellen.unterbrechen_nur_eigen:
        return False  # wie vor dem 17.11.2026: WAMO sprach gleichzeitig, ein niedriger Wert ist nur unklar (Echo)
    if schwellen.nur_eigen or ueberlappung:
        return not ist_eigen(urteil)
    # Regel vom 16.11.2026 (WAMO_STIMME_NUR_EIGEN=aus)
    if urteil is None or urteil.wert is None or urteil.secs < schwellen.verwerfen_min_secs:
        return False
    if urteil.urteil == FREMD:
        return True
    return urteil.urteil == UNKLAR and urteil.wert < schwellen.verwerfen_max


def nur_endgueltig(waechter: StimmWaechter, *beschaeftigt: Callable[[], bool]) -> Callable[[], bool]:
    """Abfrage für die Startstrategie (siehe oben): ja, wenn der Wächter verwerfen kann und eine der Arbeiten läuft (Werkzeug, Modell)."""
    return lambda: waechter.aktiv() and any(laeuft() for laeuft in beschaeftigt)


def nur_eigen_unterbricht(waechter: StimmWaechter) -> Callable[[], bool | None]:
    """Abfrage für die Startstrategie, während WAMO spricht (siehe oben): None heißt, die Regel gilt nicht (anderer Modus, kein Abdruck,
    Schalter aus), alles wie bisher. True: die laufende Äußerung ist schon früh als eigen erkannt. False: noch nicht, warten."""
    return lambda: waechter.laufend_eigen() if waechter.unterbricht_nur_eigen() else None


def _zeit(stempel: object) -> str | None:
    """zeit für die Meldung: genau der Zeitstempel des Transkripts, oder None, wenn er fehlt oder zu lang ist (siehe oben)."""
    return stempel if isinstance(stempel, str) and 0 < len(stempel) <= ZEIT_MAX else None


class StimmWaechter(FrameProcessor):
    def __init__(self, gate: StimmGate, pruefer, *, warten: float = WARTEN_SECS, nachfrist: float = NACHFRIST_SECS, **kwargs):
        super().__init__(**kwargs)
        self._gate = gate
        self._pruefer = pruefer
        self._warten = warten
        self._nachfrist = nachfrist
        self._gemeldet_nr: int | None = None  # zuletzt als ignoriert gemeldete Äußerung (einmal je Äußerung)
        self._bot_spricht = False

    def aktiv(self) -> bool:
        """Kann der Wächter verwerfen (Modus streng, Abdruck und Modell bereit)?"""
        return self._gate.verwirft

    def unterbricht_nur_eigen(self) -> bool:
        """Unterbricht nur die eigene Stimme WAMO (zusätzlich WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN an)?"""
        return self._gate.nur_eigen_unterbricht()

    def laufend_eigen(self) -> bool:
        """Ist die laufende Äußerung schon früh als eigen erkannt (Stimmpruefer.laufend_eigen)?"""
        return self._pruefer.laufend_eigen()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (BotStartedSpeakingFrame, BotStoppedSpeakingFrame)):
            self._bot_spricht = isinstance(frame, BotStartedSpeakingFrame)  # kommt stromaufwärts vom Ausgang
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, STTMetadataFrame) and self._gate.modus == "streng":
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
        urteil = await self._pruefer.urteil_abwarten(self._warten, nr)  # None: Frist abgelaufen oder nichts geprüft
        regel = self._gate.schwellen
        if urteil is None and verwerfen(None, regel, waehrend_rede=self._bot_spricht):
            # Ohne Urteil verworfen wäre ein eigener Satz verloren (der Rechner ist langsam oder belegt): die Nachfrist (siehe oben). Ist
            # die Prüfung schon ohne Urteil zu Ende, kommt die Antwort sofort.
            urteil = await self._pruefer.urteil_abwarten(self._nachfrist, nr)
        weg = verwerfen(urteil, regel, waehrend_rede=self._bot_spricht,
                        frueh_eigen=self._pruefer.frueh_eigen(urteil.nr if urteil is not None else nr))
        await self._melden(frame, urteil, nr, weg)
        if not weg:
            return frame
        # Ein neues Frame: Beobachter der Pipeline halten das Original. Der Zeitstempel bleibt, die Oberfläche nimmt damit den schon
        # gezeigten Untertitel zurück (siehe oben)
        return replace(frame, text=" ", result=None)

    async def _melden(self, frame: TranscriptionFrame, urteil: Urteil | None, nr: int, weg: bool) -> None:
        """Meldung an die Oberfläche (siehe oben): angenommen zu jedem Transkript, verworfen einmal je Äußerung."""
        if weg:
            aeusserung = urteil.nr if urteil is not None else nr
            if aeusserung == self._gemeldet_nr:
                return
            self._gemeldet_nr = aeusserung
            _ignoriert_loggen(urteil)
        await self.push_frame(RTVIServerMessageFrame(data={
            "type": "stimme",
            "ergebnis": UNKLAR if urteil is None or urteil.urteil == KURZ else urteil.urteil,
            "wert": None if urteil is None or urteil.wert is None else round(float(urteil.wert), 2),
            "modus": self._gate.modus,
            "ignoriert": weg,
            "zeit": _zeit(frame.timestamp),
        }))


def _ignoriert_loggen(urteil: Urteil | None) -> None:
    """Eine Zeile je verworfener Äußerung, nur Art, Wert und Dauer, nie ein Inhalt."""
    if urteil is None:
        logger.info("Stimme: Äußerung ignoriert (kein Urteil in der Frist)")
    elif urteil.wert is None:
        logger.info("Stimme: Äußerung ignoriert (Prüfung fehlgeschlagen, {:.1f} s)", urteil.secs)
    else:
        logger.info("Stimme: {} Äußerung ignoriert ({:.2f} bei {:.1f} s)", _LOG_ART.get(urteil.urteil, urteil.urteil), float(urteil.wert),
                    urteil.secs)
