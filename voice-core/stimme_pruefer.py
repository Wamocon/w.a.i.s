"""Stimmprüfung im Audiopfad: schneidet jede Äußerung aus einem Ringpuffer, vergleicht sie mit dem Stimmabdruck und lernt ihn auf Klick ein.

Der Prüfer sitzt direkt hinter dem Mikrofon (vor der Spracherkennung). Er hält die letzten Sekunden Ton vor, schneidet jede Äußerung anhand der
VAD-Meldungen heraus und vergleicht die laufende Äußerung (höchstens die letzten MAX_PRUEF_SECS) mit dem Stimmabdruck dieser Sitzung
(StimmGate.abdruck, stimme_gate.py). Ergebnis: eigen, fremd, unklar oder kurz. Die Prüfung beginnt beim Sprechende und läuft in einem Thread
parallel zur Spracherkennung. Jede Äußerung (VAD-Beginn bis VAD-Ende) hat eine Nummer, ihr Urteil trägt sie. Wer ein Ergebnis braucht
(stimme_waechter.py), ordnet sein Transkript mit aeusserung_zuordnen einer Äußerung zu und wartet mit urteil_abwarten höchstens die übergebene
Frist auf genau deren Urteil; spätere Äußerungen halten nicht auf. Ein Ablauf der Frist gilt als unklar (kein Urteil). Rohton wird nie
gespeichert, der Ringpuffer lebt nur im Arbeitsspeicher.

Zuschnitt und Evidenz über den Zug (18.11.2026): Jedes Segment wird wie beim Einlernen zugeschnitten (stimme_modell.pruefsegment: ohne
stillen Vor- und Nachlauf, Pausen über 0,3 s fallen weg, nie kürzer als die gemessene Sprache). Die Segmente eines Zugs werden zusammen
geprüft, ihr Ton hintereinander und jeder Ton nur einmal; so zählt jedes mit seiner Sprachdauer. Das ist bewusst der Ton und kein Mittel der
Einzelwerte: Der Wert eines längeren Stücks ist verlässlicher als das Mittel der Werte kurzer Stücke (die Werte kurzer Stücke liegen tiefer,
und die Schwellen nach Länge sind an ganzen Stücken gemessen). Zusammengeführt wird nur, solange W.A.I.S. nicht spricht: Ein Segment, in dem
W.A.I.S. spricht oder einsetzt, zählt für sich und beendet den Zug. Satzende (satz_ende), Zugende, Rede von W.A.I.S. und mehr als
ZUG_PAUSE_SECS Stille beginnen einen neuen Zug, damit ein fremder Einwurf nach einem fertigen Satz nichts erbt.

Das Modell ist je Prozess einmal vorhanden (stimme_modell.MODELL), der Prüfzustand und der Abdruck gehören je Sitzung zum Gate: zwei Profile
im selben Prozess teilen nur den Rechner. Gerechnet wird nur für ein Profil mit Abdruck und nur, wenn der Modus nicht aus ist.

Einlernen (stimme_einlernen.py) hängt am Prüfer, weil es den Ton braucht: Solange es läuft, sammelt es den Ton und der Prüfer ersetzt ihn
für Spracherkennung und VAD durch Stille. Meldungen an die Oberfläche: {"type": "stimme", "ergebnis": eigen | fremd | unklar, "wert",
"modus"} je Äußerung (kurz zählt als unklar), immer vor der Meldung des Wächters zum Transkript derselben Äußerung (mit ignoriert und zeit),
damit die Oberfläche zuletzt dessen Stand zeigt; den Stand (StimmGate.stand) melden Sitzung und Einlernen.

Frühes Urteil fürs Unterbrechen (Entscheidung vom 17.11.2026, nur wenn StimmGate.nur_eigen_unterbricht: Modus streng, Abdruck und Modell
bereit, WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN an): Spricht jemand, während WAMO spricht, soll nur die eigene Stimme WAMO unterbrechen, und
zwar so früh, wie das Urteil verlässlich ist. Was der Prüfer kann: TitaNet rechnet aus jedem Stück Ton einen Abdruck, die Rechenzeit wächst
mit der Länge (rund 250 ms für 8 s, für 1 bis 2 s also nur einige zehn Millisekunden), der Ton liegt schon im Ringpuffer. Unter einer
Sekunde Sprache streut der Abdruck stark, deshalb gilt dort nur "kurz" (StimmGate.einstufen, WAMO_STIMME_MIN_SECS 1 s). Gewählt ist
deshalb: FRUEH_AB_SECS (1 s) nach dem Beginn der Äußerung (laut VAD) und danach alle FRUEH_TAKT_SECS rechnet der Prüfer, solange die
Äußerung läuft und WAMO spricht, die letzten FRUEH_FENSTER_SECS (2 s) der Äußerung. Das Fenster statt der ganzen Äußerung, weil eine
Äußerung während der Rede von WAMO oft mit Echo oder einer fremden Stimme beginnt; die eigene Stimme danach soll trotzdem durchkommen.
Klingt es nach der Person (Wert ab der Schwelle für eigen, StimmGate.schwelle_fuer, unter Überlappung), schickt der Prüfer einmal je
Äußerung StimmUrteilFrame mit frueh, und laufend_eigen sagt ja, solange die Äußerung läuft. Ein frühes "nicht eigen" entscheidet nichts
(zu wenig Ton, Echo), es zählt erst das Urteil am Sprechende; dazu kommt ein StimmUrteilFrame ohne frueh, solange keine neuere Äußerung begonnen hat (sonst gälte es für sie).
Ein frühes eigen merkt sich der Prüfer auch für den Wächter (frueh_eigen). Kurze Äußerungen ("Stopp", unter einer Sekunde) bekommen also nur
das Urteil am Sprechende: WAMO hält dort rund 0,5 bis 1 Sekunde später an als bisher, und das ist so gewollt. Das frühe Urteil ändert
weder den Prüfzustand im Gate (Werkzeuge) noch das Urteil, auf das das Transkript wartet, und es geht nicht an die Oberfläche.

Schattenbetrieb (stimme_schatten.py, WAMO_STIMME_SCHATTEN, seit 18.11.2026): Mit einem Schattenmodell rechnet der Prüfer nach jedem Urteil
am Sprechende denselben Ton auch mit dem zweiten Modell, in einer eigenen Aufgabe nach der Meldung des Urteils; ins Log geht nur eine Zeile
mit Zahlen. Das Urteil bleibt allein bei TitaNet, das frühe Urteil rechnet ohne Schatten.

Ein Abdruck je Mikrofon (seit 18.11.2026, stimme_mikrofon.py): Der Prüfer vergleicht mit allen Abdrücken des Gates und nimmt den besten Wert
(StimmGate.vergleichen) mit der persönlichen Schwelle dieses Abdrucks; im Log steht mit mehreren Abdrücken, welcher es war (Nummer, nie Name
oder Kennung). Der Schatten nimmt ebenso den besten Wert über seine eigenen Abdrücke. Für den Mikrofontest der Oberfläche unterbricht
ausgabe_unterbrechen eine laufende Antwort von W.A.I.S.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from soft_interrupt import StimmUrteilFrame
from stimme_einlernen import Einlernen, Speichern
from stimme_gate import EIGEN, KURZ, UNKLAR, StimmGate
from stimme_mikrofon import UNBEKANNTES_MIKROFON, Mikrofon
from stimme_modell import ModellQuelle, pruefsegment
from stimme_schatten import SchattenPruefung

RING_SECS = 10.0
MAX_PRUEF_SECS = 8.0
ZUG_PAUSE_SECS = 3.0  # längere Stille: die nächste Äußerung wird für sich geprüft
VORLAUF_SECS = 0.25  # VAD meldet den Beginn erst nach start_secs, etwas Luft davor
NACHLAUF_SECS = 0.1
URTEIL_MAX_ALTER_SECS = 8.0  # so alt darf ein Urteil höchstens sein, damit ein Transkript sich darauf stützen darf
URTEILE_MERKEN = 16  # so viele Urteile der letzten Äußerungen bleiben abrufbar
# Frühes Urteil fürs Unterbrechen (siehe oben): ab so viel Sprache, in diesem Takt, über die letzten so vielen Sekunden
FRUEH_AB_SECS = 1.0
FRUEH_TAKT_SECS = 1.0
FRUEH_FENSTER_SECS = 2.0


@dataclass(frozen=True)
class Urteil:
    """Ergebnis der Prüfung einer Äußerung. nr: Nummer der Äußerung. urteil: eigen, fremd, unklar oder kurz. secs: reine Sprache.
    um: Zeitpunkt (Uhr des Gates). schwelle: ab diesem Wert hätte die Äußerung als eigen gegolten (StimmGate.schwelle_fuer), None ohne Wert."""

    nr: int
    urteil: str
    wert: float | None
    secs: float
    ueberlappung: bool
    um: float
    schwelle: float | None = None


class Stimmpruefer(FrameProcessor):
    """Prüft jede Äußerung gegen den Stimmabdruck und lernt ihn auf Klick ein (siehe oben)."""

    def __init__(
        self,
        gate: StimmGate,
        modell: ModellQuelle,
        *,
        speichern: Speichern,
        sagen: Callable[[str], Awaitable[None]],
        uhr: Callable[[], float] = time.time,
        nachweis: Callable[[], bool] | None = None,
        schatten: ModellQuelle | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._gate = gate
        self._modell = modell
        self._uhr = uhr  # Wanduhr wie VADUser...SpeakingFrame.timestamp
        self._einlernen = Einlernen(gate, modell, senden=self._senden, sagen=sagen, speichern=speichern, uhr=uhr, nachweis=nachweis,
                                    schatten=schatten)
        # Zweites Modell im Schattenbetrieb (stimme_schatten.py): nur messen, nie entscheiden; None ohne WAMO_STIMME_SCHATTEN
        self._schatten = SchattenPruefung(gate, schatten) if schatten is not None else None
        self._ring: deque[tuple[float, int, bytes]] = deque()  # (Ende des Pakets auf der Uhr, laufende Nummer, Ton)
        self._paket = 0  # Nummer des letzten Pakets im Ring (zählt nur hoch, auch wenn die Uhr springt)
        self._ring_secs = 0.0
        self._rate = 16000
        self._segment_start: float | None = None  # mit Luft davor (zum Ausschneiden)
        self._sprache_beginn = 0.0  # wie VAD ihn meldet (zum Messen der reinen Sprache)
        self._segment_ueberlappung = False
        self._zug = b""  # laufende Äußerung, höchstens MAX_PRUEF_SECS
        self._zug_secs = 0.0
        self._zug_ueberlappung = False
        self._zug_zu = True
        self._zug_bis = 0  # Nummer des letzten Pakets, das schon im Zug liegt: jeder Ton zählt nur einmal
        self._letztes_ende = -math.inf
        self._bot_spricht = False
        self._sprechend = False  # laut VAD läuft eine Äußerung (die Prüfung beginnt erst mit ihrem Ende)
        self._task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        # Nummern der Äußerungen: zuletzt begonnen, zuletzt beendet, zuletzt einem Transkript zugeordnet, bis hierhin alle Prüfungen fertig
        self._begonnen = self._beendet = self._zugeordnet = self._fertig = 0
        self._urteile: dict[int, Urteil] = {}
        self._aenderung = asyncio.Event()  # wird bei jeder fertigen Prüfung gesetzt und ersetzt (weckt urteil_abwarten)
        self._aufgeraeumt = False
        # Frühes Urteil (siehe oben): nächste Prüfung ab so viel Sprache, laufende Prüfung, Äußerung mit frühem Urteil eigen
        self._frueh_ab = FRUEH_AB_SECS
        self._frueh_task: asyncio.Task | None = None
        self._frueh_eigen_nr = 0

    # ---------- Stand und Einlernen ----------

    async def _senden(self, daten: dict) -> None:
        await self.push_frame(RTVIServerMessageFrame(data=daten))

    async def einlernen_starten(self, version: str, einwilligung_am: datetime, mikrofon: Mikrofon = UNBEKANNTES_MIKROFON) -> None:
        await self._einlernen.starten(version, einwilligung_am, mikrofon)

    async def einlernen_abbrechen(self) -> None:
        await self._einlernen.abbrechen()

    async def einlernen_warten(self) -> None:
        await self._einlernen.warten()

    async def ausgabe_unterbrechen(self) -> bool:
        """Mikrofontest in der Oberfläche (Wunsch vom 18.11.2026): Spricht W.A.I.S. gerade, wird die Antwort unterbrochen wie bei
        einem Einwurf (InterruptionFrame stromabwärts, das SoftInterruptGate behandelt es als Unterbrechung von anderer Stelle). True, wenn
        unterbrochen wurde. Nur während W.A.I.S. spricht: ein laufendes Werkzeug oder eine Antwort, die erst entsteht, bleibt unberührt."""
        if not self._bot_spricht:
            return False
        logger.info("Mikrofontest: W.A.I.S. wird unterbrochen")
        await self.push_frame(InterruptionFrame())
        return True

    # ---------- Frames ----------

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            await self.on_audio(frame)
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self.on_speech_start(frame.timestamp, frame.start_secs)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.on_speech_stop(frame.timestamp, frame.stop_secs)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.on_turn_end()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.on_bot_speaking(True)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.on_bot_speaking(False)
        await self.push_frame(frame, direction)

    def on_turn_end(self) -> None:
        self._zug_zu = True  # die nächste Äußerung wird für sich geprüft

    def satz_ende(self) -> None:
        """Das endgültige Transkript endete mit einem Satzzeichen (stimme_waechter.py): der Satz ist zu Ende, auch wenn der Zug noch
        offen ist. Ein neues Segment danach wird für sich geprüft, damit ein fremder Einwurf das Urteil des Satzes davor nicht erbt.
        Mitten im Satz (ohne Satzzeichen) bleibt der Zug zusammen."""
        self._zug_zu = True

    def on_bot_speaking(self, spricht: bool) -> None:
        self._bot_spricht = spricht
        self._zug_zu = True  # was vor oder nach der Rede von WAMO kommt, ist eine neue Äußerung
        if spricht and self._sprechend:
            self._segment_ueberlappung = True  # W.A.I.S. setzt mitten im Segment ein: es zählt für sich (siehe on_speech_stop)
        self._einlernen.bot_spricht(spricht)

    async def on_audio(self, frame: InputAudioRawFrame) -> None:
        pcm = frame.audio
        self._rate = frame.sample_rate
        self._paket += 1
        self._ring.append((self._uhr(), self._paket, pcm))
        self._ring_secs += _secs(pcm, self._rate)
        while self._ring_secs > RING_SECS and len(self._ring) > 1:
            self._ring_secs -= _secs(self._ring.popleft()[2], self._rate)
        if await self._einlernen.sammeln(pcm, self._rate):
            frame.audio = bytes(len(pcm))  # Spracherkennung und VAD hören Stille
        elif self._frueh_faellig():
            self._frueh_starten()

    def on_speech_start(self, zeit: float, start_secs: float) -> None:
        if self._einlernen.aktiv:
            return
        self._sprechend = True
        self._begonnen += 1
        self._sprache_beginn = zeit - start_secs
        if self._zug_zu or self._bot_spricht or self._sprache_beginn - self._letztes_ende > ZUG_PAUSE_SECS:
            self._zug_neu()
        self._segment_start = self._sprache_beginn - VORLAUF_SECS
        self._segment_ueberlappung = self._bot_spricht
        self._frueh_ab = FRUEH_AB_SECS

    def on_speech_stop(self, zeit: float, stop_secs: float) -> None:
        self._sprechend = False
        if self._einlernen.aktiv or self._segment_start is None:
            self._segment_start = None  # ein späteres Ende ohne neuen Beginn schneidet nie ab einem alten Beginn
            if self._begonnen > self._beendet:  # die laufende Äußerung endet ungeprüft (Einlernen begann): zu ihr gibt es kein Urteil
                self._beendet = self._fertig = self._begonnen
                self._melden()
            return
        nr = self._beendet = self._begonnen
        sprache_ende = zeit - stop_secs
        sprache_secs = sprache_ende - self._sprache_beginn
        sprache_secs = sprache_secs if math.isfinite(sprache_secs) and sprache_secs > 0 else 0.0
        ueberlappt = self._segment_ueberlappung or self._bot_spricht
        if ueberlappt:
            # Evidenz über den Zug nur, solange W.A.I.S. nicht spricht: dieses Segment zählt für sich, der Zug endet mit ihm
            self._zug_neu()
            self._zug_zu = True
        # Jeder Ton zählt nur einmal: reicht der Vorlauf in das Segment davor, beginnt der Schnitt nach dem letzten Paket des Zugs
        roh, bis = self._ausschneiden(self._segment_start, sprache_ende + NACHLAUF_SECS, nach=self._zug_bis)
        segment = _zuschneiden(roh, self._rate, sprache_secs)
        self._zug_ueberlappung = ueberlappt
        self._zug_bis = max(self._zug_bis, bis)
        self._segment_start = None
        self._letztes_ende = sprache_ende
        # Nur die letzten MAX_PRUEF_SECS behalten; gemessen wird die reine Sprache ohne die Luft drumherum
        self._zug = (self._zug + segment)[-int(MAX_PRUEF_SECS * self._rate) * 2 :]
        self._zug_secs = min(self._zug_secs + sprache_secs, MAX_PRUEF_SECS)
        vorherige = self._task
        self._task = self._starten(
            self._pruefen(self._zug, self._rate, self._zug_secs, self._zug_ueberlappung, self._gate.uhr(), vorherige, nr), nr
        )
        self._gate.verfolgen(self._task)
        self._gate.gesprochen()  # für die Pflichtstufe der Mitglieder: seit dem Tippen wurde gesprochen (stimme_gate.pflicht_grund)

    def _zug_neu(self) -> None:
        """Die nächste Äußerung wird für sich geprüft."""
        self._zug, self._zug_secs, self._zug_ueberlappung, self._zug_zu, self._zug_bis = b"", 0.0, False, False, 0

    def _ausschneiden(self, start: float, ende: float, nach: int = 0) -> tuple[bytes, int]:
        """Der Ton der Pakete, die in start bis ende hineinreichen und nach dem Paket nach kamen, und die Nummer des letzten davon
        (nach, wenn keines passt)."""
        teile = []
        bis = nach
        for t_ende, paket, pcm in self._ring:
            t_start = t_ende - _secs(pcm, self._rate)
            if paket > nach and t_ende > start and t_start < ende:
                teile.append(pcm)
                bis = paket
        return b"".join(teile), bis

    # ---------- Frühes Urteil fürs Unterbrechen ----------

    def laufend_eigen(self) -> bool:
        """Klingt die Äußerung, die gerade läuft, schon nach der Person (frühes Urteil, siehe oben)? Nach ihrem Ende nie mehr: dann zählt das
        Urteil am Sprechende."""
        return self._sprechend and self._begonnen > 0 and self._frueh_eigen_nr == self._begonnen

    def _frueh_faellig(self) -> bool:
        if not (self._sprechend and self._bot_spricht and self._segment_start is not None) or self._frueh_eigen_nr == self._begonnen:
            return False
        if self._frueh_task is not None and not self._frueh_task.done():
            return False  # eine frühe Prüfung rechnet noch
        return self._uhr() - self._sprache_beginn >= self._frueh_ab and self._gate.nur_eigen_unterbricht()

    def _frueh_starten(self) -> None:
        jetzt = self._uhr()
        dauer = jetzt - self._sprache_beginn
        self._frueh_ab = dauer + FRUEH_TAKT_SECS
        pcm, _ = self._ausschneiden(max(self._segment_start, jetzt - FRUEH_FENSTER_SECS), jetzt)  # die letzten Sekunden der Äußerung
        task = asyncio.create_task(self._frueh_pruefen(pcm, self._rate, min(dauer, FRUEH_FENSTER_SECS), self._begonnen))
        self._frueh_task = task
        self._tasks.add(task)
        task.add_done_callback(self._frueh_erledigt)

    def _frueh_erledigt(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (fehler := task.exception()) is not None:  # abgeholt: kein "never retrieved" im Log
            logger.warning("Stimmprüfung früh: Aufgabe mit Fehler beendet ({})", type(fehler).__name__)

    async def _frueh_pruefen(self, pcm: bytes, rate: int, secs: float, nr: int) -> None:
        """Prüft ein Stück der laufenden Äußerung nr (W.A.I.S. spricht). Nur ein Urteil eigen zählt, und nur, solange nr noch läuft. Das Stück
        wird wie am Sprechende zugeschnitten (stiller Vorlauf weg), im Thread des Rechners."""
        gate = self._gate
        rechner = await self._modell.get()
        if not gate.abdruecke or rechner is None or not pcm:
            return
        try:
            vektor = await asyncio.to_thread(lambda: rechner.embed(_zuschneiden(pcm, rate, secs), rate))
            vergleich = gate.vergleichen(vektor)  # bester Wert über alle Abdrücke (einer je Mikrofon)
        except Exception as e:  # ein früher Fehler entscheidet nichts, es zählt das Urteil am Sprechende
            logger.debug("Stimmprüfung früh fehlgeschlagen ({})", type(e).__name__)
            return
        if vergleich is None or not math.isfinite(vergleich[0]):
            return
        wert, treffer = vergleich
        urteil = gate.einstufen(wert, secs, True, treffer)
        logger.info("Stimme früh: {:.2f} bei {:.1f} s (WAMO spricht) -> {} (Schwelle {:.2f})", wert, secs, urteil,
                    gate.schwelle_fuer(secs, treffer))
        if urteil not in (EIGEN, KURZ) or not self._laeuft(nr) or not gate.nur_eigen_unterbricht():
            return
        self._frueh_eigen_nr = nr
        await self.push_frame(StimmUrteilFrame(nr=nr, eigen=True, frueh=True))

    def frueh_eigen(self, nr: int) -> bool:
        """Hat das frühe Urteil die Äußerung nr als eigen erkannt (und WAMO deshalb unterbrochen)? Für den Wächter: dann geht ihr Satz durch,
        auch wenn das Urteil am Sprechende schwächer ausfällt (stimme_waechter.py)."""
        return nr > 0 and nr == self._frueh_eigen_nr

    def _laeuft(self, nr: int) -> bool:
        """Läuft die Äußerung nr noch (VAD-Beginn ohne Ende, keine neuere)?"""
        return self._sprechend and nr == self._begonnen and nr not in self._urteile

    # ---------- Prüfen ----------

    def aeusserung_zuordnen(self) -> int:
        """Zu welcher Äußerung gehört ein endgültiges Transkript, das jetzt ankommt? Zur zuletzt beendeten, solange sie noch keinem Transkript
        gehört: die Erkennung schließt nach dem Sprechende ab, auch wenn die Person schon weiterspricht. Sonst zur laufenden (die Erkennung hat
        mitten in der Rede abgeschlossen) oder, wenn keine läuft, wieder zur zuletzt beendeten (ein zweites Transkript derselben Äußerung).
        0: es gab noch keine."""
        nr = self._begonnen if self._sprechend and self._beendet <= self._zugeordnet else self._beendet
        self._zugeordnet = max(self._zugeordnet, nr)
        return nr

    async def urteil_abwarten(self, frist: float, nr: int | None = None) -> Urteil | None:
        """Wartet höchstens frist Sekunden auf das Urteil der Äußerung nr (None: wie aeusserung_zuordnen) und gibt es zurück.
        None: Frist abgelaufen (gilt als unklar), nicht geprüft oder das Urteil ist zu alt für das, wonach gefragt wird."""
        nr = self.aeusserung_zuordnen() if nr is None else nr
        uhr = asyncio.get_running_loop().time
        ende = uhr() + frist
        while not (self._aufgeraeumt or nr <= self._fertig):  # Prüfungen laufen der Reihe nach
            try:
                await asyncio.wait_for(self._aenderung.wait(), max(0.0, ende - uhr()))
            except asyncio.TimeoutError:
                return None
        urteil = self._urteile.get(nr)
        if urteil is None or self._gate.uhr() - urteil.um > URTEIL_MAX_ALTER_SECS:
            return None
        return urteil

    def _melden(self) -> None:
        """Wer auf ein Urteil wartet, schaut nach."""
        self._aenderung.set()
        self._aenderung = asyncio.Event()

    async def _pruefen(
        self, pcm: bytes, rate: int, secs: float, ueberlappung: bool, gehoert_um: float, vorherige: asyncio.Task | None, nr: int
    ) -> None:
        """secs: reine Sprache. gehoert_um: Ende der Äußerung (Uhr des Gates). nr: Nummer der Äußerung."""
        if vorherige and not vorherige.done():
            await asyncio.wait({vorherige})  # der Reihe nach, sonst überholt ein altes Ergebnis
        gate = self._gate
        if not gate.abdruecke or gate.modus == "aus":
            return
        rechner = await self._modell.get()
        gate.modell_ok = rechner is not None
        try:
            if rechner is None or not pcm:
                raise RuntimeError("kein Modell" if rechner is None else "kein Ton ausgeschnitten")
            start = time.perf_counter()
            vektor = await asyncio.to_thread(rechner.embed, pcm, rate)
            titanet_ms = (time.perf_counter() - start) * 1000
            vergleich = gate.vergleichen(vektor)  # bester Wert über alle Abdrücke (einer je Mikrofon)
            if vergleich is None:
                return  # der Abdruck wurde während des Rechnens gelöscht
            wert, treffer = vergleich
            if not math.isfinite(wert):
                raise ValueError("Ähnlichkeit ist keine endliche Zahl")
        except Exception as e:  # nicht geprüft heißt nicht erkannt: nie das alte Ergebnis weiterverwenden
            if not gate.abdruecke:
                return  # der Abdruck wurde während des Rechnens gelöscht
            logger.warning("Stimmprüfung fehlgeschlagen ({}), gilt als unklar", e)
            await self._ergebnis(nr, UNKLAR, None, secs, ueberlappung, gehoert_um)
            return
        urteil = gate.einstufen(wert, secs, ueberlappung, treffer)
        quelle = None
        if len(gate.abdruecke) > 1 and treffer in gate.abdruecke:
            quelle = f"Abdruck {gate.abdruecke.index(treffer) + 1} von {len(gate.abdruecke)}"
        await self._ergebnis(nr, urteil, wert, secs, ueberlappung, gehoert_um, gate.schwelle_fuer(secs, treffer), quelle)
        if self._schatten is not None:
            # erst jetzt: das Urteil ist gemeldet, der Schatten rechnet in einer eigenen Aufgabe und hält keine Prüfung auf
            self._schatten.starten(pcm, rate, secs, ueberlappung, urteil, wert, titanet_ms)

    async def _ergebnis(
        self, nr: int, urteil: str, wert: float | None, secs: float, ueberlappung: bool, gehoert_um: float, schwelle: float | None = None,
        quelle: str | None = None,
    ) -> None:
        """quelle: welcher Abdruck den besten Wert hatte (nur mit mehreren, für das Protokoll; nie Name oder Kennung des Mikrofons)."""
        self._gate.eintragen(urteil, gehoert_um)
        self._urteile[nr] = Urteil(nr, urteil, wert, secs, ueberlappung, self._gate.uhr(), schwelle)
        for alt in [n for n in self._urteile if n <= nr - URTEILE_MERKEN]:
            del self._urteile[alt]
        self._fertig = max(self._fertig, nr)
        if wert is not None:
            # für die Kalibrierung: Wert, Länge, Urteil und die angewandte Schwelle, nie ein Inhalt
            sprach = " (WAMO sprach)" if ueberlappung else ""
            if quelle is None:
                logger.info("Stimme: {:.2f} bei {:.1f} s{} -> {} (Schwelle {:.2f})", wert, secs, sprach, urteil, schwelle)
            else:
                logger.info("Stimme: {:.2f} bei {:.1f} s{} -> {} (Schwelle {:.2f}, {})", wert, secs, sprach, urteil, schwelle, quelle)
        if self._gate.nur_eigen_unterbricht() and nr == self._begonnen:
            # fürs Unterbrechen (Start-Strategie und Gate, soft_interrupt.py); hat schon die nächste Äußerung begonnen, gälte es für sie
            await self.push_frame(StimmUrteilFrame(nr=nr, eigen=urteil in (EIGEN, KURZ)))
        meldung = {"type": "stimme", "ergebnis": UNKLAR if urteil == KURZ else urteil, "modus": self._gate.modus}
        if wert is not None:
            meldung["wert"] = round(float(wert), 2)
        await self._senden(meldung)
        # Erst jetzt wecken: die Meldung des Wächters (mit ignoriert und zeit) kommt so immer nach dieser und bleibt in der Oberfläche
        # stehen. Beide sind Systemframes in einer Warteschlange, das Transkript wartet darauf nicht spürbar.
        self._melden()

    # ---------- Aufräumen ----------

    def _starten(self, coro, nr: int) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._erledigt(t, nr))
        return task

    def _erledigt(self, task: asyncio.Task, nr: int) -> None:
        """Die Prüfung der Äußerung nr ist zu Ende, mit oder ohne Urteil."""
        self._tasks.discard(task)
        self._fertig = max(self._fertig, nr)
        self._melden()
        if not task.cancelled() and (fehler := task.exception()) is not None:  # abgeholt: kein "never retrieved" im Log
            logger.warning("Stimmprüfung: Aufgabe mit Fehler beendet ({})", type(fehler).__name__)

    async def schatten_warten(self) -> None:
        """Wartet auf eine laufende Rechnung des Schattens (für Tests)."""
        if self._schatten is not None:
            await self._schatten.warten()

    async def cleanup(self):
        await super().cleanup()
        await self._einlernen.aufraeumen()
        if self._schatten is not None:
            await self._schatten.aufraeumen()
        laufend = list(self._tasks)
        for task in laufend:
            task.cancel()
        self._aufgeraeumt = True  # wer noch wartet, bekommt kein Urteil statt ewig zu warten
        self._melden()
        await asyncio.gather(*laufend, return_exceptions=True)  # abgebrochen und abgewartet: danach läuft keine Prüfung mehr


def _secs(pcm: bytes, rate: int) -> float:
    return len(pcm) / 2 / rate if rate else 0.0


def _zuschneiden(pcm: bytes, rate: int, sprache_secs: float) -> bytes:
    """stimme_modell.pruefsegment (ohne stillen Vor- und Nachlauf, wie beim Einlernen), das nie wirft: Es läuft beim Ende einer Äußerung
    mitten in der Behandlung des Frames der Sprachpausenerkennung, ein Fehler darf diesen Frame nie aufhalten. Dann bleibt der Ton ungekürzt."""
    try:
        return pruefsegment(pcm, rate, sprache_secs)
    except Exception as e:
        logger.warning("Stimmprüfung: Zuschnitt fehlgeschlagen ({}), Segment ungekürzt", type(e).__name__)
        return pcm[: len(pcm) - len(pcm) % 2]
