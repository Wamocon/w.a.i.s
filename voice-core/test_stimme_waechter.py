"""Tests für stimme_waechter.py: im Modus streng mit Abdruck erreicht nur die eigene Stimme das Sprachmodell (seit 17.11.2026), mit
WAMO_STIMME_NUR_EIGEN=aus gilt die Regel vom 16.11.2026 (fremd oder unklar mit niedrigem Wert). Dazu die Meldung je Urteil mit dem
Zeitstempel des Transkripts und die Abfrage der Startstrategie, ob die laufende Äußerung W.A.I.S. unterbrechen darf.

Ausführen:  python -m pytest -q test_stimme_waechter.py   (im Ordner voice-core/)
"""

import asyncio
import time
import unittest
from unittest import mock

import numpy as np

from pipecat.frames.frames import InputAudioRawFrame, InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.tests.utils import run_test
from pipecat.transcriptions.language import Language

import stimme_waechter
from stimme_gate import EIGEN, FREMD, KURZ, UNKLAR, Schwellen, StimmGate
from stimme_modell import DIM
from stimme_pruefer import Stimmpruefer, Urteil
from stimme_waechter import NACHFRIST_SECS, WARTEN_SECS, ZEIT_MAX, StimmWaechter, nur_eigen_unterbricht, verwerfen

RATE = 16000
EIGENER = np.eye(DIM, dtype=np.float32)[0]
FREMDER = np.eye(DIM, dtype=np.float32)[1]


class Uhr:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def bereites_gate(modus="streng", uhr=None, schwellen: Schwellen | None = None) -> StimmGate:
    gate = StimmGate(modus=modus, uhr=uhr or Uhr(), schwellen=schwellen or Schwellen())
    gate.setze_abdruck(EIGENER)
    gate.modell_ok = True
    return gate


def urteil(art: str, secs: float = 2.0, wert: float | None = 0.12, nr: int = 1, ueberlappung: bool = False) -> Urteil:
    return Urteil(nr=nr, urteil=art, wert=wert, secs=secs, ueberlappung=ueberlappung, um=1000.0)


def eingestuft(wert: float, secs: float, ueberlappung: bool = False, schwellen: Schwellen | None = None) -> Urteil:
    """Ein Urteil, wie der Prüfer es fällt (StimmGate.einstufen mit den Standardschwellen oder den übergebenen)."""
    gate = StimmGate(schwellen=schwellen or Schwellen())
    return urteil(gate.einstufen(wert, secs, ueberlappung), secs=secs, wert=wert, ueberlappung=ueberlappung)


def alt(**kwargs) -> Schwellen:
    """Beide Schalter vom 17.11.2026 aus (WAMO_STIMME_NUR_EIGEN=aus, WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN=aus): das Verhalten davor."""
    return Schwellen(nur_eigen=False, unterbrechen_nur_eigen=False, **kwargs)


ALT = alt()
ZEIT = "2026-11-14T10:00:00Z"  # Zeitstempel der Transkripte in diesen Tests (final, zwischenstand)


class RegelTests(unittest.TestCase):
    """Die bisherige Regel des Wächters (verwerfen mit beiden Schaltern aus), mit den Werten aus dem Journal des Kerns vom 16.11.2026
    (Modus streng, Abdruck bereit)."""

    def test_befund_vom_16_11(self):
        faelle = (
            # (Wert, Sprache in s, Urteil des Prüfers, verwerfen?)
            (0.30, 3.3, FREMD, True), (0.27, 1.7, FREMD, True), (0.15, 1.1, FREMD, True),  # schon bisher verworfen
            (0.29, 0.96, FREMD, True), (0.15, 0.4, FREMD, True), (0.23, 0.3, FREMD, True),  # fremd und kurz: neu verworfen
            (0.31, 1.1, UNKLAR, True),  # unklar mit niedrigem Wert: neu verworfen
            (0.73, 1.6, EIGEN, False), (0.62, 0.8, KURZ, False),  # die eigene Stimme, auch ein kurzes "Ja"
        )
        for wert, secs, art, soll in faelle:
            u = eingestuft(wert, secs)
            self.assertEqual(u.urteil, art, (wert, secs))
            self.assertEqual(verwerfen(u, ALT), soll, (wert, secs, art))

    def test_unklar_mit_hohem_wert_geht_durch_auch_kurz(self):
        for wert, secs in ((0.4, 1.5), (0.45, 1.5), (0.49, 0.5), (0.4, 0.3)):
            u = eingestuft(wert, secs)
            self.assertEqual(u.urteil, UNKLAR, (wert, secs))
            self.assertFalse(verwerfen(u, ALT), (wert, secs))  # ab VERWERFEN_MAX (0,4) nicht verworfen

    def test_spricht_wamo_gleichzeitig_geht_alles_durch(self):
        """Echo oder Überlappung: der Prüfer urteilt unklar, der Wächter verwirft nicht (wie bisher), auch bei sehr niedrigem Wert."""
        for wert, secs in ((0.05, 3.0), (0.2, 0.4), (0.35, 1.2)):
            u = eingestuft(wert, secs, ueberlappung=True)
            self.assertEqual(u.urteil, UNKLAR)
            self.assertFalse(verwerfen(u, ALT), (wert, secs))

    def test_unmoegliche_kombinationen_bleiben_sicher(self):
        """Der Prüfer liefert sie nicht, die Regel bleibt trotzdem eindeutig: Überlappung verwirft nie, eigen und kurz nie."""
        self.assertFalse(verwerfen(urteil(FREMD, wert=0.1, ueberlappung=True), ALT))
        self.assertFalse(verwerfen(urteil(EIGEN, wert=0.1), ALT))
        self.assertFalse(verwerfen(urteil(KURZ, wert=0.1, secs=0.4), ALT))

    def test_ohne_urteil_oder_wert_geht_alles_durch(self):
        self.assertFalse(verwerfen(None, ALT))  # Frist abgelaufen
        self.assertFalse(verwerfen(urteil(UNKLAR, wert=None), ALT))  # Prüfung fehlgeschlagen
        self.assertFalse(verwerfen(urteil(FREMD, wert=None), ALT))

    def test_verwerfen_max_gleich_fremd_max_schaltet_das_verwerfen_unklarer_ab(self):
        s = alt(verwerfen_max=0.3)
        self.assertFalse(verwerfen(eingestuft(0.31, 1.1, schwellen=s), s))
        self.assertTrue(verwerfen(eingestuft(0.3, 1.1, schwellen=s), s))  # fremd bleibt verworfen

    def test_verwerfen_max_gleich_eigen_min_verwirft_jede_unklare(self):
        s = alt(verwerfen_max=0.5)
        self.assertTrue(verwerfen(eingestuft(0.49, 1.1, schwellen=s), s))
        self.assertFalse(verwerfen(eingestuft(0.5, 0.6, schwellen=s), s))  # kurz, klingt nach der Person

    def test_mindestdauer_zum_verwerfen(self):
        """WAMO_STIMME_VERWERFEN_MIN_SECS: mit 1 s verhält sich der Wächter für kurze Äußerungen wie vor dem 16.11.2026."""
        s = alt(verwerfen_min_secs=1.0)
        self.assertFalse(verwerfen(eingestuft(0.15, 0.4, schwellen=s), s))
        self.assertFalse(verwerfen(eingestuft(0.31, 0.9, schwellen=s), s))
        self.assertTrue(verwerfen(eingestuft(0.15, 1.1, schwellen=s), s))
        self.assertTrue(verwerfen(eingestuft(0.31, 1.0, schwellen=s), s))


class NurEigenRegelTests(unittest.TestCase):
    """Entscheidung vom 17.11.2026: W.A.I.S. hört nur der eingelernten Stimme zu. Im Modus streng mit Abdruck geht nur durch, was eigen ist
    (Wert ab EIGEN_MIN, also auch ein kurzes eigenes "Ja"); alles andere wird verworfen."""

    def test_standard_ist_nur_eigen(self):
        self.assertTrue(Schwellen().nur_eigen)
        self.assertTrue(Schwellen().unterbrechen_nur_eigen)

    def test_alles_ausser_eigen_wird_verworfen(self):
        s = Schwellen()
        faelle = (
            (urteil(FREMD, wert=0.12), True), (urteil(FREMD, secs=0.3, wert=0.2), True),  # fremd, auch kurz
            (eingestuft(0.31, 1.1), True), (eingestuft(0.45, 1.5), True), (eingestuft(0.49, 0.5), True),  # unklar mit jedem Wert
            (urteil(UNKLAR, wert=None), True), (urteil(FREMD, wert=None), True),  # Prüfung fehlgeschlagen
            (None, True),  # keine Antwort in der Frist
            (eingestuft(0.73, 1.6), False), (eingestuft(0.62, 0.8), False),  # eigen, auch kurz (Wert ab EIGEN_MIN)
        )
        for u, soll in faelle:
            self.assertEqual(verwerfen(u, s), soll, u)

    def test_verwerfen_max_und_min_secs_wirken_nur_bei_aus(self):
        """Die Schalter vom 16.11.2026 wirken nur mit WAMO_STIMME_NUR_EIGEN=aus wie bisher."""
        s = Schwellen(verwerfen_max=0.3, verwerfen_min_secs=5.0)
        self.assertTrue(verwerfen(eingestuft(0.35, 1.1, schwellen=s), s))
        self.assertTrue(verwerfen(eingestuft(0.15, 0.4, schwellen=s), s))
        s = Schwellen(verwerfen_max=0.3, verwerfen_min_secs=5.0, nur_eigen=False)
        self.assertFalse(verwerfen(eingestuft(0.35, 1.1, schwellen=s), s))
        self.assertFalse(verwerfen(eingestuft(0.15, 0.4, schwellen=s), s))

    def test_waehrend_wamo_spricht_gilt_nur_eigen_mit_dem_schalter_fuers_unterbrechen(self):
        """Überlappung (W.A.I.S. sprach gleichzeitig): mit WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN (Standard an) wird auch dann alles außer eigen
        verworfen, unabhängig von WAMO_STIMME_NUR_EIGEN; aus heißt wie bisher: der Satz geht durch."""
        fremd_dabei = eingestuft(0.12, 2.0, ueberlappung=True)
        eigen_dabei = eingestuft(0.7, 2.0, ueberlappung=True)
        self.assertEqual(fremd_dabei.urteil, UNKLAR)
        for s, soll in ((Schwellen(), True), (Schwellen(nur_eigen=False), True), (Schwellen(unterbrechen_nur_eigen=False), False),
                        (ALT, False)):
            self.assertEqual(verwerfen(fremd_dabei, s), soll, s)
            self.assertFalse(verwerfen(eigen_dabei, s), s)

    def test_keine_antwort_waehrend_wamo_spricht(self):
        """Ohne Urteil zählt, ob W.A.I.S. sprach, als das Transkript ankam (wie Überlappung)."""
        self.assertTrue(verwerfen(None, Schwellen(nur_eigen=False), waehrend_rede=True))
        self.assertFalse(verwerfen(None, Schwellen(nur_eigen=False), waehrend_rede=False))  # bisherige Regel
        self.assertFalse(verwerfen(None, Schwellen(unterbrechen_nur_eigen=False), waehrend_rede=True))  # wie bisher
        self.assertTrue(verwerfen(None, Schwellen(), waehrend_rede=False))

    def test_frueh_als_eigen_erkannt_wird_nie_verworfen(self):
        for u in (eingestuft(0.4, 2.0, ueberlappung=True), urteil(FREMD), urteil(UNKLAR, wert=None), None):
            self.assertFalse(verwerfen(u, Schwellen(), frueh_eigen=True), u)
            self.assertTrue(verwerfen(u, Schwellen(), frueh_eigen=False), u)


class AttrappePruefer:
    """Gibt nach dauer Sekunden das vorbereitete Urteil zurück, oder None, wenn die Frist vorher abläuft."""

    def __init__(self, ergebnis: Urteil | None, dauer: float = 0.0, *, dauern: list[float] | None = None):
        """dauern: je Anfrage eine eigene Dauer (die erste für das erste Transkript usw.), sonst gilt dauer für alle."""
        self.ergebnis = ergebnis
        self.dauer = dauer
        self.dauern = dauern
        self.fragen: list[float] = []
        self.nummern: list[int | None] = []
        self.satzenden = 0
        self._zugeordnet = 0
        self.eigen_laufend = False  # Antwort auf laufend_eigen (frühes Urteil eigen für die laufende Äußerung)
        self.frueh_nr: int | None = None  # Äußerung, die früh als eigen erkannt wurde (frueh_eigen)

    def satz_ende(self) -> None:
        self.satzenden += 1

    def laufend_eigen(self) -> bool:
        return self.eigen_laufend

    def frueh_eigen(self, nr: int) -> bool:
        return nr == self.frueh_nr

    def aeusserung_zuordnen(self) -> int:
        self._zugeordnet += 1
        return self._zugeordnet

    async def urteil_abwarten(self, frist: float, nr: int | None = None):
        self.fragen.append(frist)
        self.nummern.append(nr)
        dauer = self.dauern[len(self.fragen) - 1] if self.dauern else self.dauer
        if dauer > frist:
            await asyncio.sleep(frist)
            return None
        await asyncio.sleep(dauer)
        return self.ergebnis


def final(text: str = "Mach die Heizung an") -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="u", timestamp="2026-11-14T10:00:00Z", language=Language.DE, finalized=True)


def zwischenstand(text: str = "Mach die") -> InterimTranscriptionFrame:
    return InterimTranscriptionFrame(text=text, user_id="u", timestamp="2026-11-14T10:00:00Z", language=Language.DE)


async def durchlassen(waechter, frames):
    unten, _ = await run_test(waechter, frames_to_send=frames)
    texte = [f for f in unten if isinstance(f, (TranscriptionFrame, InterimTranscriptionFrame))]
    meldungen = [f.data for f in unten if isinstance(f, RTVIServerMessageFrame)]
    return texte, meldungen


class VerwerfenTests(unittest.IsolatedAsyncioTestCase):
    async def test_sicher_fremd_ersetzt_das_transkript_durch_nichts(self):
        gate = bereites_gate()
        waechter = StimmWaechter(gate, AttrappePruefer(urteil(FREMD)))
        texte, meldungen = await durchlassen(waechter, [final()])
        self.assertEqual(len(texte), 1)
        self.assertEqual(texte[0].text.strip(), "")  # der Zug endet leer, das Modell sieht keinen Satz
        self.assertTrue(texte[0].finalized)  # ... damit der Zug normal endet
        self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": "fremd", "wert": 0.12, "modus": "streng", "ignoriert": True,
                                      "zeit": ZEIT}])

    async def test_das_ersatztranskript_traegt_den_zeitstempel_des_originals(self):
        """Die Oberfläche hat den Text schon (Pipecat meldet das Transkript beim Verlassen der Spracherkennung). Das Ersatztranskript ohne Text
        mit demselben Zeitstempel nimmt ihn dort wieder aus dem Untertitel (ui/src/lib/wamo.ts, nutzerTranskript)."""
        original = final("Schließ die Tür")
        texte, _ = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(urteil(FREMD))), [original])
        self.assertEqual((texte[0].text, texte[0].timestamp, texte[0].user_id), (" ", original.timestamp, original.user_id))
        self.assertIsNot(texte[0], original)

    async def test_unklar_mit_niedrigem_wert_wird_verworfen_und_als_unklar_gemeldet(self):
        waechter = StimmWaechter(bereites_gate(), AttrappePruefer(urteil(UNKLAR, secs=1.1, wert=0.31)))
        with mock.patch.object(stimme_waechter.logger, "info") as info:
            texte, meldungen = await durchlassen(waechter, [final("Was gibt es heute in der Kantine")])
        self.assertEqual(info.call_args.args[1:], ("unklare", 0.31, 1.1))  # nie ein Inhalt im Log
        self.assertNotIn("Kantine", repr(info.call_args))
        self.assertEqual(texte[0].text.strip(), "")
        self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": "unklar", "wert": 0.31, "modus": "streng", "ignoriert": True,
                                      "zeit": ZEIT}])

    async def test_mit_beiden_schaltern_aus_gehen_eigen_kurz_und_unsicheres_unveraendert_durch(self):
        """Das Verhalten vor dem 17.11.2026: nur die Meldung je Urteil (mit ignoriert false und zeit) ist neu."""
        for u, ergebnis, wert in ((urteil(EIGEN, secs=1.6, wert=0.73), "eigen", 0.73), (urteil(KURZ, secs=0.8, wert=0.62), "unklar", 0.62),
                                  (urteil(UNKLAR, secs=1.5, wert=0.45), "unklar", 0.45),
                                  (urteil(UNKLAR, secs=2.0, wert=0.12, ueberlappung=True), "unklar", 0.12),
                                  (urteil(UNKLAR, wert=None), "unklar", None)):
            waechter = StimmWaechter(bereites_gate(schwellen=ALT), AttrappePruefer(u))
            texte, meldungen = await durchlassen(waechter, [final("Hallo WAMO")])
            self.assertEqual([t.text for t in texte], ["Hallo WAMO"], u)
            self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": ergebnis, "wert": wert, "modus": "streng", "ignoriert": False,
                                          "zeit": ZEIT}], u)

    async def test_endgueltiges_transkript_mit_satzzeichen_meldet_das_satzende(self):
        for text, erwartet in (("Mach die Heizung an.", 1), ("Wie spät ist es?", 1), ("Stopp!", 1), ("Mach die Heizung", 0),
                               ("  ", 0), ("Mach die Heizung an. Und dann", 0)):
            pruefer = AttrappePruefer(urteil(EIGEN))
            await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final(text)])
            self.assertEqual(pruefer.satzenden, erwartet, text)

    async def test_zwischenstaende_und_verworfene_saetze_melden_das_satzende_richtig(self):
        pruefer = AttrappePruefer(urteil(EIGEN))
        await durchlassen(StimmWaechter(bereites_gate(), pruefer), [zwischenstand("Mach die Heizung an.")])
        self.assertEqual(pruefer.satzenden, 0)  # nur das endgültige Transkript zählt
        pruefer = AttrappePruefer(urteil(FREMD))
        await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("Mach die Heizung an.")])
        self.assertEqual(pruefer.satzenden, 1)  # auch ein verworfener Satz ist zu Ende

    async def test_fremd_und_kurz_wird_verworfen(self):
        """Seit 16.11.2026: auch wenig Sprache reicht, wenn der Wert klar fremd ist (Journal: 0,15 bei 0,4 s ging bisher durch)."""
        waechter = StimmWaechter(bereites_gate(), AttrappePruefer(urteil(FREMD, secs=0.4, wert=0.15)))
        texte, meldungen = await durchlassen(waechter, [final("Ja")])
        self.assertEqual(texte[0].text.strip(), "")
        self.assertEqual(meldungen[0]["ignoriert"], True)

    async def test_keine_antwort_in_der_frist_gilt_als_unklar_und_geht_mit_beiden_schaltern_aus_durch(self):
        pruefer = AttrappePruefer(urteil(FREMD), dauer=5.0)
        waechter = StimmWaechter(bereites_gate(schwellen=ALT), pruefer, warten=0.05)
        start = time.monotonic()
        texte, _ = await durchlassen(waechter, [final("Hallo")])
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual([t.text for t in texte], ["Hallo"])
        self.assertEqual(pruefer.fragen, [0.05])

    async def test_kein_urteil_geht_mit_beiden_schaltern_aus_durch(self):
        waechter = StimmWaechter(bereites_gate(schwellen=ALT), AttrappePruefer(None))
        texte, _ = await durchlassen(waechter, [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])

    async def test_standardfrist_ist_begrenzt(self):
        self.assertLessEqual(WARTEN_SECS, 2.0)
        pruefer = AttrappePruefer(urteil(EIGEN))
        await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final()])
        self.assertEqual(pruefer.fragen, [WARTEN_SECS])

    async def test_zwischenstaende_werden_nie_angehalten_oder_veraendert(self):
        pruefer = AttrappePruefer(urteil(FREMD))
        waechter = StimmWaechter(bereites_gate(), pruefer)
        texte, _ = await durchlassen(waechter, [zwischenstand("Mach"), zwischenstand("Mach die")])
        self.assertEqual([t.text for t in texte], ["Mach", "Mach die"])
        self.assertEqual(pruefer.fragen, [])  # kein Warten: Unterbrechen durch die Person bleibt so schnell wie bisher

    async def test_leeres_transkript_bleibt_unberuehrt(self):
        pruefer = AttrappePruefer(urteil(FREMD))
        texte, _ = await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("  ")])
        self.assertEqual([t.text for t in texte], ["  "])
        self.assertEqual(pruefer.fragen, [])

    async def test_jedes_transkript_fragt_nach_dem_urteil_seiner_aeusserung(self):
        pruefer = AttrappePruefer(urteil(EIGEN))
        await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("eins"), final("zwei")])
        self.assertEqual(pruefer.nummern, [1, 2])

    async def test_mehrere_transkripte_zu_einem_urteil_nur_eine_meldung(self):
        waechter = StimmWaechter(bereites_gate(), AttrappePruefer(urteil(FREMD)))
        texte, meldungen = await durchlassen(waechter, [final("eins"), final("zwei")])
        self.assertEqual([t.text.strip() for t in texte], ["", ""])
        self.assertEqual(len(meldungen), 1)

    async def test_eine_unterbrechung_waehrend_des_wartens_verliert_das_transkript_nicht(self):
        """Pipecat bricht bei einer Unterbrechung das Frame ab, das ein Verarbeiter gerade bearbeitet. Das gehaltene Transkript der Person darf
        dabei nicht verloren gehen (zum Beispiel wenn sie WAMO ins Wort fällt, während das Urteil noch aussteht)."""
        from pipecat.frames.frames import InterruptionFrame
        from pipecat.tests.utils import SleepFrame

        pruefer = AttrappePruefer(urteil(EIGEN), dauer=0.2)
        waechter = StimmWaechter(bereites_gate(), pruefer)
        unten, _ = await run_test(waechter, frames_to_send=[final("Mach die Heizung an"), SleepFrame(0.05), InterruptionFrame(), SleepFrame(0.4)])
        texte = [f.text for f in unten if isinstance(f, TranscriptionFrame)]
        self.assertEqual(texte, ["Mach die Heizung an"])

    async def test_nur_in_fahrtrichtung_abwaerts(self):
        pruefer = AttrappePruefer(urteil(FREMD))
        waechter = StimmWaechter(bereites_gate(), pruefer)
        waechter.push_frame = mock.AsyncMock()
        frame = final("hoch")
        with mock.patch("pipecat.processors.frame_processor.FrameProcessor.process_frame", mock.AsyncMock()):
            await waechter.process_frame(frame, FrameDirection.UPSTREAM)
        waechter.push_frame.assert_awaited_once_with(frame, FrameDirection.UPSTREAM)
        self.assertEqual(pruefer.fragen, [])


class ModusTests(unittest.IsolatedAsyncioTestCase):
    async def test_beobachten_und_aus_verwerfen_nie_und_warten_nie(self):
        for modus in ("beobachten", "aus"):
            for u in (urteil(FREMD), urteil(FREMD, secs=0.4), urteil(UNKLAR, wert=0.31)):  # auch nicht nach der strengeren Regel
                pruefer = AttrappePruefer(u)
                waechter = StimmWaechter(bereites_gate(modus), pruefer)
                texte, meldungen = await durchlassen(waechter, [final("Hallo")])
                self.assertEqual([t.text for t in texte], ["Hallo"], (modus, u))
                self.assertEqual((meldungen, pruefer.fragen), ([], []), (modus, u))

    async def test_ohne_abdruck_wird_nichts_verworfen_und_nicht_gewartet(self):
        for u in (urteil(FREMD), urteil(UNKLAR, wert=0.31)):
            gate = bereites_gate()
            gate.setze_abdruck(None)
            pruefer = AttrappePruefer(u)
            texte, _ = await durchlassen(StimmWaechter(gate, pruefer), [final("Hallo")])
            self.assertEqual([t.text for t in texte], ["Hallo"], u)
            self.assertEqual(pruefer.fragen, [], u)

    async def test_ist_das_modell_nicht_bereit_geht_alles_durch(self):
        for u in (urteil(FREMD), urteil(UNKLAR, wert=0.31)):
            gate = bereites_gate()
            gate.modell_ok = False
            pruefer = AttrappePruefer(u)
            texte, _ = await durchlassen(StimmWaechter(gate, pruefer), [final("Hallo")])
            self.assertEqual([t.text for t in texte], ["Hallo"], u)

    async def test_eigene_schwellen_gelten_fuer_die_mindestdauer(self):
        gate = bereites_gate()
        gate.schwellen = alt(verwerfen_min_secs=3.0)
        waechter = StimmWaechter(gate, AttrappePruefer(urteil(FREMD, secs=2.0)))
        texte, _ = await durchlassen(waechter, [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])

    async def test_die_mindestdauer_fuer_eigen_zaehlt_nicht_mehr_fuer_das_verwerfen(self):
        gate = bereites_gate()
        gate.schwellen = Schwellen(min_secs=3.0)
        waechter = StimmWaechter(gate, AttrappePruefer(urteil(FREMD, secs=2.0)))
        texte, _ = await durchlassen(waechter, [final("Hallo")])
        self.assertEqual(texte[0].text.strip(), "")


class MitEchtemPrueferTests(unittest.IsolatedAsyncioTestCase):
    """Prüfer und Wächter zusammen: dieselben Äußerungen wie im Gespräch, das Modell ist ein Ersatz."""

    def setUp(self):
        self.uhr = Uhr()
        self.gate = bereites_gate(uhr=self.uhr)
        rechner = mock.Mock()
        rechner.embed = lambda pcm, rate: EIGENER if np.frombuffer(pcm, dtype=np.int16).astype(np.int64).sum() > 0 else FREMDER
        modell = mock.Mock()
        modell.get = mock.AsyncMock(return_value=rechner)
        self.pruefer = Stimmpruefer(self.gate, modell, speichern=mock.AsyncMock(), sagen=mock.AsyncMock(), uhr=self.uhr)
        self.pruefer.push_frame = mock.AsyncMock()
        self.waechter = StimmWaechter(self.gate, self.pruefer)

    async def sprechen(self, wert: int, secs: float):
        self.pruefer.on_speech_start(self.uhr.t + 0.2, 0.2)
        for _ in range(int(secs / 0.02)):
            self.uhr.t += 0.02
            await self.pruefer.on_audio(InputAudioRawFrame(audio=np.full(320, wert, dtype=np.int16).tobytes(), sample_rate=RATE, num_channels=1))
        for _ in range(10):
            self.uhr.t += 0.02
            await self.pruefer.on_audio(InputAudioRawFrame(audio=bytes(640), sample_rate=RATE, num_channels=1))
        self.pruefer.on_speech_stop(self.uhr.t, 0.2)

    async def test_fremde_aeusserung_wird_verworfen_die_eigene_geht_durch(self):
        await self.sprechen(-8000, 2.0)  # ein Gast; das Transkript kommt, während die Prüfung noch läuft
        texte, meldungen = await durchlassen(self.waechter, [final("Schließ die Tür")])
        self.assertEqual(texte[0].text.strip(), "")
        self.assertEqual(meldungen[0]["ergebnis"], "fremd")
        self.assertTrue(meldungen[0]["ignoriert"])
        self.pruefer.on_turn_end()
        await self.sprechen(8000, 2.0)  # danach die Person
        texte, meldungen = await durchlassen(self.waechter, [final("Mach die Heizung an")])
        self.assertEqual([t.text for t in texte], ["Mach die Heizung an"])
        self.assertEqual([(m["ergebnis"], m["ignoriert"], m["zeit"]) for m in meldungen], [("eigen", False, ZEIT)])

    async def test_kurze_fremde_aeusserung_wird_verworfen_ein_kurzes_eigenes_ja_nicht(self):
        await self.sprechen(-8000, 0.4)  # ein Gast, kurz
        texte, meldungen = await durchlassen(self.waechter, [final("Ja.")])
        self.assertEqual(texte[0].text.strip(), "")
        self.assertTrue(meldungen[0]["ignoriert"])
        self.pruefer.on_turn_end()
        await self.sprechen(8000, 0.4)  # die Person, ebenso kurz: Urteil kurz, geht durch
        texte, meldungen = await durchlassen(self.waechter, [final("Ja.")])
        self.assertEqual([t.text for t in texte], ["Ja."])
        self.assertEqual([(m["ergebnis"], m["ignoriert"]) for m in meldungen], [("unklar", False)])  # kurz heißt in der Meldung unklar

    async def test_fremde_stimme_waehrend_wamo_spricht_wird_verworfen(self):
        """Seit 17.11.2026 (WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN, Standard an): auch während W.A.I.S. spricht, geht nur die eigene Stimme durch."""
        self.pruefer.on_bot_speaking(True)
        await self.sprechen(-8000, 2.0)
        texte, meldungen = await durchlassen(self.waechter, [final("Schließ die Tür")])
        self.assertEqual(texte[0].text.strip(), "")
        self.assertEqual([(m["ergebnis"], m["ignoriert"]) for m in meldungen], [("unklar", True)])

    async def test_fremde_stimme_waehrend_wamo_spricht_geht_mit_dem_schalter_aus_durch(self):
        """WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN=aus: Echo oder Überlappung, unklar, der Satz geht durch wie bisher (nur Werkzeuge bleiben gesperrt)."""
        self.gate.schwellen = Schwellen(unterbrechen_nur_eigen=False)
        self.pruefer.on_bot_speaking(True)
        await self.sprechen(-8000, 2.0)
        texte, meldungen = await durchlassen(self.waechter, [final("Schließ die Tür")])
        self.assertEqual([t.text for t in texte], ["Schließ die Tür"])
        self.assertEqual([(m["ergebnis"], m["ignoriert"]) for m in meldungen], [("unklar", False)])

    async def test_spaetes_transkript_bekommt_das_urteil_seiner_aeusserung(self):
        """Das Transkript eines Gastes kommt erst, als die Person schon wieder spricht: es gilt das Urteil der Äußerung des Gastes. Es wartet
        nicht auf das Ende der laufenden (sonst käme es erst nach deren Ende beim Aggregator an, und der Zug endete ohne sie)."""
        await self.sprechen(-8000, 2.0)
        self.pruefer.on_speech_start(self.uhr.t + 0.2, 0.2)
        texte, meldungen = await durchlassen(self.waechter, [final("Schließ die Tür")])
        self.assertEqual(texte[0].text.strip(), "")
        self.assertEqual(meldungen[0]["ergebnis"], "fremd")

    async def test_laufende_aeusserung_ohne_ende_haelt_hoechstens_die_frist_auf(self):
        self.pruefer.on_speech_start(self.uhr.t + 0.2, 0.2)  # VAD meldet nie ein Ende
        waechter = StimmWaechter(self.gate, self.pruefer, warten=0.05)
        start = time.monotonic()
        texte, meldungen = await durchlassen(waechter, [final("Hallo")])
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(texte[0].text.strip(), "")  # kein Urteil: nicht eigen, verworfen
        self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": "unklar", "wert": None, "modus": "streng", "ignoriert": True,
                                      "zeit": ZEIT}])
        self.gate.schwellen = ALT
        texte, _ = await durchlassen(StimmWaechter(self.gate, self.pruefer, warten=0.05), [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])  # beide Schalter aus: unklar, geht durch wie bisher

    async def test_zwei_profile_im_selben_prozess_urteilen_getrennt(self):
        zweites_gate = bereites_gate(uhr=self.uhr)
        zweiter = StimmWaechter(zweites_gate, AttrappePruefer(urteil(EIGEN, wert=0.8)))
        await self.sprechen(-8000, 2.0)
        texte, _ = await durchlassen(zweiter, [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])  # das Urteil der ersten Sitzung gilt nicht für die zweite
        texte, _ = await durchlassen(self.waechter, [final("Hallo")])
        self.assertEqual(texte[0].text.strip(), "")


class MitEchtemAggregatorTests(unittest.IsolatedAsyncioTestCase):
    """Der Zug des Nutzers endet auch ohne Satz: der echte Aggregator von Pipecat ruft das Modell dann nicht auf."""

    async def lauf(self, ergebnis: Urteil | None, text: str):
        from pipecat.frames.frames import LLMContextFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
        from pipecat.tests.utils import SleepFrame
        from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
        from pipecat.turns.user_turn_strategies import UserTurnStrategies
        from soft_interrupt import MeaningfulWordsUserTurnStartStrategy

        kontext = LLMContext()
        nutzer, _ = LLMContextAggregatorPair(kontext, user_params=LLMUserAggregatorParams(
            # wie in bot.py: die Startstrategie unterbricht nie selbst (das entscheidet das SoftInterruptGate)
            user_turn_strategies=UserTurnStrategies(
                start=[MeaningfulWordsUserTurnStartStrategy(min_words=1, enable_interruptions=False)],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)])))
        zuege: list[str] = []

        @nutzer.event_handler("on_user_turn_stopped")
        async def _zug_zu(_agg, _strategie, nachricht):
            zuege.append(nachricht.content)

        waechter = StimmWaechter(bereites_gate(), AttrappePruefer(ergebnis))
        frames = [VADUserStartedSpeakingFrame(start_secs=0.2, timestamp=time.time()), zwischenstand(text), SleepFrame(0.05),
                  VADUserStoppedSpeakingFrame(stop_secs=0.2, timestamp=time.time()), final(text), SleepFrame(0.6)]
        unten, _ = await run_test(Pipeline([waechter, nutzer]), frames_to_send=frames)
        return zuege, [f for f in unten if isinstance(f, LLMContextFrame)], kontext, waechter

    async def test_eigene_aeusserung_ruft_das_modell_auf(self):
        zuege, kontextframes, kontext, _ = await self.lauf(urteil(EIGEN), "Mach die Heizung an")
        self.assertEqual(zuege, ["Mach die Heizung an"])
        self.assertEqual(len(kontextframes), 1)

    async def test_fremde_aeusserung_beendet_den_zug_leer_ohne_modellaufruf(self):
        zuege, kontextframes, kontext, _ = await self.lauf(urteil(FREMD), "Schließ die Tür")
        self.assertEqual([z.strip() for z in zuege], [""])  # genau ein Zug, ohne Satz: bot.py kehrt bei leerem Inhalt zurück
        self.assertEqual(kontextframes, [])
        self.assertEqual(kontext.messages, [])  # nichts im Verlauf


class FesteMarke:
    """Smart-Turn-Ersatz für die Stop-Strategie: liefert der Reihe nach die vorgegebenen Urteile zum Satzende."""

    def __init__(self, *urteile):
        from pipecat.audio.turn.base_turn_analyzer import BaseTurnParams, EndOfTurnState

        self.urteile = list(urteile)
        self.unfertig = EndOfTurnState.INCOMPLETE
        self.speech_triggered = False
        self.params = BaseTurnParams()

    def set_sample_rate(self, rate):
        pass

    def update_vad_start_secs(self, secs):
        pass

    def append_audio(self, buffer, is_speech):
        return self.unfertig

    async def analyze_end_of_turn(self):
        return self.urteile.pop(0), None

    def clear(self):
        pass

    async def cleanup(self):
        pass


class VadStempel(FrameProcessor):
    """Setzt den Zeitstempel der VAD-Meldungen beim Durchgang, wie VAD ihn im Betrieb setzt (die Stop-Strategie rechnet ihre Frist ab dort)."""

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame

        await super().process_frame(frame, direction)
        if isinstance(frame, (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            frame.timestamp = time.time()
        await self.push_frame(frame, direction)


class HaltezeitTests(unittest.IsolatedAsyncioTestCase):
    """Der Wächter hält das endgültige Transkript bis zum Urteil an. Die Stop-Strategie wartet nach dem Sprechende aber nur so lange auf ein
    Transkript, wie die Spracherkennung laut ihrer Angabe braucht (STTMetadataFrame, ttfs_p99_latency). Ohne Ausgleich beendete sie einen Zug
    aus zwei Äußerungen mit dem Text der ersten, während die zweite noch beim Wächter stand."""

    async def metadaten(self, modus: str) -> float:
        from pipecat.frames.frames import STTMetadataFrame

        unten, _ = await run_test(StimmWaechter(bereites_gate(modus), AttrappePruefer(None)),
                                  frames_to_send=[STTMetadataFrame(service_name="stt", ttfs_p99_latency=0.35)])
        return next(f.ttfs_p99_latency for f in unten if isinstance(f, STTMetadataFrame))

    async def test_die_stop_strategie_kennt_die_haltezeit(self):
        self.assertAlmostEqual(await self.metadaten("streng"), 0.35 + WARTEN_SECS)

    async def test_ohne_verwerfen_bleibt_die_frist_der_spracherkennung(self):
        for modus in ("beobachten", "aus"):
            self.assertAlmostEqual(await self.metadaten(modus), 0.35, msg=modus)

    async def test_zug_endet_erst_mit_dem_gehaltenen_transkript(self):
        """Zwei Äußerungen in einem Zug, das Urteil zur zweiten kommt 0,8 s nach ihrem Transkript (Smart-Turn: erst unfertig, dann fertig)."""
        from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
        from pipecat.frames.frames import STTMetadataFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
        from pipecat.tests.utils import SleepFrame
        from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
        from pipecat.turns.user_turn_strategies import UserTurnStrategies
        from soft_interrupt import MeaningfulWordsUserTurnStartStrategy

        marke = FesteMarke(EndOfTurnState.INCOMPLETE, EndOfTurnState.COMPLETE)
        nutzer, _ = LLMContextAggregatorPair(LLMContext(), user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[MeaningfulWordsUserTurnStartStrategy(min_words=2, enable_interruptions=False)],
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=marke)])))
        zuege: list[str] = []

        @nutzer.event_handler("on_user_turn_stopped")
        async def _zug_zu(_agg, _strategie, nachricht):
            zuege.append(nachricht.content)

        waechter = StimmWaechter(bereites_gate(), AttrappePruefer(urteil(EIGEN), dauern=[0.0, 0.8]))
        frames = [STTMetadataFrame(service_name="stt", ttfs_p99_latency=0.35),
                  VADUserStartedSpeakingFrame(start_secs=0.2), zwischenstand("Mach die"), SleepFrame(0.05),
                  VADUserStoppedSpeakingFrame(stop_secs=0.2), final("Mach die"), SleepFrame(0.2),
                  VADUserStartedSpeakingFrame(start_secs=0.2), zwischenstand("Heizung an"), SleepFrame(0.05),
                  VADUserStoppedSpeakingFrame(stop_secs=0.2), final("Heizung an"), SleepFrame(2.0)]
        await run_test(Pipeline([VadStempel(), waechter, nutzer]), frames_to_send=frames)
        self.assertEqual(zuege, ["Mach die Heizung an"])


class NurEndgueltigTests(unittest.IsolatedAsyncioTestCase):
    """Befund: Ein Zwischenstand einer fremden Stimme startete den Zug, das SoftInterruptGate brach sofort hart ab (Antwort oder Werkzeug
    weg), danach verwarf der Wächter das endgültige Transkript und WAMO schwieg. Im Modus streng mit Abdruck zählt deshalb, solange WAMO
    nicht spricht, aber Modell oder Werkzeug arbeiten, erst das endgültige Transkript nach dem Urteil des Wächters."""

    async def lauf(self, ergebnis: Urteil | None, *, werkzeug: bool = False, denkt: bool = False, gate: StimmGate | None = None,
                   text: str = "Schließ mal die Tür"):
        from pipecat.frames.frames import (FunctionCallInProgressFrame, InterruptionFrame, LLMContextFrame, VADUserStartedSpeakingFrame,
                                           VADUserStoppedSpeakingFrame)
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
        from pipecat.tests.utils import SleepFrame
        from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
        from pipecat.turns.user_turn_strategies import UserTurnStrategies
        from soft_interrupt import MeaningfulWordsUserTurnStartStrategy, SoftInterruptGate
        from stimme_waechter import nur_endgueltig
        from turn_wache import TurnWache

        waechter = StimmWaechter(gate or bereites_gate(), AttrappePruefer(ergebnis))
        weiche = SoftInterruptGate()
        wache = TurnWache()
        if denkt:  # eine Anfrage ist beim Modell, die Antwort ist noch nicht zu hören
            self.assertTrue(wache.durchlassen(LLMContextFrame(context=LLMContext(messages=[{"role": "user", "content": "Wetter?"}]))))
        nutzer, _ = LLMContextAggregatorPair(LLMContext(), user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[MeaningfulWordsUserTurnStartStrategy(
                    min_words=2, enable_interruptions=False, werkzeug_laeuft=weiche.werkzeug_laeuft,
                    nur_endgueltig=nur_endgueltig(waechter, weiche.werkzeug_laeuft, wache.modell_beschaeftigt))],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)])))
        frames = [FunctionCallInProgressFrame(function_name="websuche", tool_call_id="w1", arguments={}, cancel_on_interruption=True),
                  SleepFrame(0.05)] if werkzeug else []  # das Werkzeug läuft schon, bevor jemand spricht
        frames += [VADUserStartedSpeakingFrame(start_secs=0.2, timestamp=time.time()), zwischenstand(text), SleepFrame(0.05),
                   VADUserStoppedSpeakingFrame(stop_secs=0.2, timestamp=time.time()), final(text), SleepFrame(0.6)]
        unten, _ = await run_test(Pipeline([waechter, nutzer, weiche]), frames_to_send=frames)
        abbrueche = sum(isinstance(f, InterruptionFrame) for f in unten)
        kontexte = [f for f in unten if isinstance(f, LLMContextFrame)]
        return abbrueche, kontexte, weiche, wache

    async def test_fremde_stimme_bricht_ein_laufendes_werkzeug_nicht_ab(self):
        abbrueche, kontexte, weiche, _ = await self.lauf(urteil(FREMD), werkzeug=True)
        self.assertEqual(abbrueche, 0)
        self.assertEqual(kontexte, [])
        self.assertTrue(weiche.werkzeug_laeuft())  # das Werkzeug läuft weiter

    async def test_fremde_stimme_bricht_das_denkende_modell_nicht_ab(self):
        abbrueche, kontexte, _, wache = await self.lauf(urteil(FREMD), denkt=True)
        self.assertEqual((abbrueche, kontexte), (0, []))
        self.assertTrue(wache.modell_beschaeftigt())

    async def test_eigene_stimme_bricht_nach_dem_endgueltigen_transkript_ab(self):
        abbrueche, kontexte, _, _ = await self.lauf(urteil(EIGEN), werkzeug=True)
        self.assertEqual(abbrueche, 1)
        self.assertEqual(len(kontexte), 1)
        self.assertEqual(kontexte[0].context.messages[-1]["content"], "Schließ mal die Tür")

    async def test_ohne_laufende_arbeit_bleibt_der_schnelle_weg(self):
        """Nichts läuft: der Zwischenstand startet den Zug wie bisher (ein Abbruch schadet dort nicht, die Erkennung des Satzendes bleibt)."""
        abbrueche, kontexte, _, _ = await self.lauf(urteil(FREMD))
        self.assertEqual((abbrueche, kontexte), (1, []))

    async def test_ohne_abdruck_bleibt_alles_wie_bisher(self):
        gate = bereites_gate()
        gate.setze_abdruck(None)
        abbrueche, kontexte, _, _ = await self.lauf(None, werkzeug=True, gate=gate)
        self.assertEqual((abbrueche, len(kontexte)), (1, 1))

    def strategie(self, *, endgueltig: bool, spricht: bool):
        from soft_interrupt import MeaningfulWordsUserTurnStartStrategy

        s = MeaningfulWordsUserTurnStartStrategy(min_words=2, enable_interruptions=False, nur_endgueltig=lambda: endgueltig)
        s._bot_speaking = spricht
        self.ausgeloest, self.zurueck = [], []

        async def start():
            self.ausgeloest.append(True)

        async def reset():
            self.zurueck.append(True)

        s.trigger_user_turn_started, s.trigger_reset_aggregation = start, reset
        return s

    async def test_zwischenstand_startet_keinen_zug_das_endgueltige_transkript_schon(self):
        s = self.strategie(endgueltig=True, spricht=False)
        ergebnis = await s.process_frame(zwischenstand("Schließ mal die Tür"))
        self.assertEqual((ergebnis.name, self.ausgeloest, self.zurueck), ("CONTINUE", [], []))
        ergebnis = await s.process_frame(final("Schließ mal die Tür"))
        self.assertEqual((ergebnis.name, self.ausgeloest), ("STOP", [True]))

    async def test_beim_sprechen_bleibt_der_schnelle_weg_ueber_zwischenstaende(self):
        s = self.strategie(endgueltig=True, spricht=True)
        ergebnis = await s.process_frame(zwischenstand("Stopp, warte mal"))
        self.assertEqual((ergebnis.name, self.ausgeloest), ("STOP", [True]))

    async def test_ohne_abfrage_zaehlt_der_zwischenstand_wie_bisher(self):
        s = self.strategie(endgueltig=False, spricht=False)
        ergebnis = await s.process_frame(zwischenstand("Schließ"))
        self.assertEqual((ergebnis.name, self.ausgeloest), ("STOP", [True]))


class PflichtstufeTests(unittest.IsolatedAsyncioTestCase):
    """Paket P4: Ein endgültiges Transkript zählt für die Pflichtstufe der Mitglieder als gesprochen, in jedem Modus und ohne Abdruck."""

    async def test_transkript_beendet_das_vertrauen_aus_dem_tippen(self):
        for modus in ("aus", "beobachten", "streng"):
            uhr = Uhr()
            gate = StimmGate(modus=modus, uhr=uhr)
            gate.setze_abdruck(None)  # kein Abdruck: nur getippt
            gate.getippt()
            self.assertIsNone(gate.pflicht_grund(), modus)
            uhr.t += 1
            await durchlassen(StimmWaechter(gate, AttrappePruefer(None)), [final("Öffne den Editor")])
            self.assertIsNotNone(gate.pflicht_grund(), modus)

    async def test_leeres_transkript_zaehlt_nicht(self):
        uhr = Uhr()
        gate = StimmGate(modus="aus", uhr=uhr)
        gate.setze_abdruck(None)
        gate.getippt()
        uhr.t += 1
        await durchlassen(StimmWaechter(gate, AttrappePruefer(None)), [final("  ")])
        self.assertIsNone(gate.pflicht_grund())


class MeldungTests(unittest.IsolatedAsyncioTestCase):
    """Nach jedem Urteil eine Meldung an die Oberfläche, auch bei Annahme: {"type": "stimme", "ergebnis", "wert", "modus", "ignoriert",
    "zeit"}. zeit ist genau der Zeitstempel, den das Transkript in user-transcription trägt (der Chat links ordnet damit zu,
    ui/src/lib/stimmFilter.ts)."""

    async def test_jeder_fall_des_verwerfens_mit_meldung_und_ersatztranskript(self):
        faelle = (
            (urteil(FREMD, wert=0.12), "fremd", 0.12), (urteil(UNKLAR, secs=1.5, wert=0.45), "unklar", 0.45),
            (urteil(UNKLAR, secs=1.1, wert=0.31), "unklar", 0.31), (urteil(UNKLAR, wert=None), "unklar", None),
            (urteil(UNKLAR, wert=0.2, ueberlappung=True), "unklar", 0.2),
        )
        for u, ergebnis, wert in faelle:
            texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(u)), [final("Hallo WAMO")])
            self.assertEqual((texte[0].text, texte[0].timestamp), (" ", ZEIT), u)
            self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": ergebnis, "wert": wert, "modus": "streng", "ignoriert": True,
                                          "zeit": ZEIT}], u)

    async def test_keine_antwort_in_der_frist_wird_verworfen(self):
        pruefer = AttrappePruefer(urteil(EIGEN, wert=0.9), dauer=5.0)
        texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), pruefer, warten=0.05, nachfrist=0.05), [final("Hallo")])
        self.assertEqual(texte[0].text, " ")
        self.assertEqual(pruefer.fragen, [0.05, 0.05])  # erst nach der Nachfrist
        self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": "unklar", "wert": None, "modus": "streng", "ignoriert": True,
                                      "zeit": ZEIT}])

    async def test_eigen_und_kurz_gehen_durch_und_werden_gemeldet(self):
        for u, ergebnis, wert in ((urteil(EIGEN, secs=1.6, wert=0.734), "eigen", 0.73), (urteil(KURZ, secs=0.8, wert=0.62), "unklar", 0.62),
                                  (urteil(EIGEN, wert=0.7, ueberlappung=True), "eigen", 0.7)):
            texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(u)), [final("Hallo WAMO")])
            self.assertEqual([t.text for t in texte], ["Hallo WAMO"], u)
            self.assertEqual(meldungen, [{"type": "stimme", "ergebnis": ergebnis, "wert": wert, "modus": "streng", "ignoriert": False,
                                          "zeit": ZEIT}], u)

    async def test_zeit_ist_genau_der_zeitstempel_aus_user_transcription(self):
        """Der Zeitstempel kommt aus Pipecat (RTVIObserver gibt TranscriptionFrame.timestamp unverändert als timestamp aus)."""
        from dataclasses import replace

        from pipecat.observers.base_observer import FramePushed
        from pipecat.processors.frameworks.rtvi.observer import RTVIObserver
        from pipecat.utils.time import time_now_iso8601

        gesendet: list[dict] = []

        class Rtvi:
            async def push_transport_message(self, model, exclude_none=True):
                gesendet.append(model.model_dump(exclude_none=exclude_none))

        original = TranscriptionFrame(text="Mach das Licht an", user_id="u", timestamp=time_now_iso8601(), language=Language.DE,
                                      finalized=True)
        await RTVIObserver(Rtvi()).on_push_frame(FramePushed(source=object(), destination=object(), frame=original,
                                                             direction=FrameDirection.DOWNSTREAM, timestamp=0))
        stempel = next(m for m in gesendet if m["type"] == "user-transcription")["data"]["timestamp"]
        for u in (urteil(EIGEN, wert=0.8), urteil(FREMD)):  # angenommen und verworfen
            _, meldungen = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(u)), [replace(original)])
            self.assertEqual(meldungen[0]["zeit"], stempel, u)
            self.assertLessEqual(len(meldungen[0]["zeit"]), ZEIT_MAX)

    async def test_jedes_angenommene_transkript_bekommt_seine_eigene_meldung(self):
        """Mehrere Teile einer Äußerung: der Chat wartet je Teil auf das Urteil mit dessen Zeitstempel."""
        teile = [TranscriptionFrame(text=text, user_id="u", timestamp=stempel, language=Language.DE, finalized=True)
                 for text, stempel in (("Mach das", "2026-11-17T10:00:01.000Z"), ("Licht an", "2026-11-17T10:00:02.500Z"))]
        texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(urteil(EIGEN, wert=0.8))), teile)
        self.assertEqual([t.text for t in texte], ["Mach das", "Licht an"])
        self.assertEqual([(m["zeit"], m["ignoriert"]) for m in meldungen],
                         [("2026-11-17T10:00:01.000Z", False), ("2026-11-17T10:00:02.500Z", False)])

    async def test_ein_spaetes_urteil_kommt_in_der_nachfrist_noch_an(self):
        """Verwerfen ohne Urteil verlöre einen eigenen Satz (der Rechner ist für alle Sitzungen einer): vorher wartet der Wächter noch
        NACHFRIST_SECS. Nur dann, wenn er sonst verwürfe; mit beiden Schaltern aus geht der Satz ohne Nachfrist durch."""
        pruefer = AttrappePruefer(urteil(EIGEN, wert=0.8), dauern=[5.0, 0.0])
        texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), pruefer, warten=0.05), [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])
        self.assertEqual(pruefer.fragen, [0.05, NACHFRIST_SECS])
        self.assertEqual((meldungen[0]["ergebnis"], meldungen[0]["ignoriert"]), ("eigen", False))
        pruefer = AttrappePruefer(None, dauer=5.0)
        await durchlassen(StimmWaechter(bereites_gate(schwellen=ALT), pruefer, warten=0.05), [final("Hallo")])
        self.assertEqual(pruefer.fragen, [0.05])
        pruefer = AttrappePruefer(urteil(FREMD))
        await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("Hallo")])
        self.assertEqual(len(pruefer.fragen), 1)  # mit Urteil keine Nachfrist

    async def test_was_frueh_als_eigen_erkannt_wurde_geht_durch(self):
        """Hat das frühe Urteil die Person erkannt (und W.A.I.S. deshalb unterbrochen), geht ihr Satz ans Modell, auch wenn das Urteil am
        Sprechende schwächer ausfällt (Echo am Anfang, zweite Stimme); sonst schwiege W.A.I.S. nach dem Abbruch. Werkzeuge sperrt das Gate
        dann weiter nach dem Urteil am Sprechende."""
        pruefer = AttrappePruefer(urteil(UNKLAR, wert=0.4, ueberlappung=True))
        pruefer.frueh_nr = 1
        texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("Stopp, warte mal")])
        self.assertEqual([t.text for t in texte], ["Stopp, warte mal"])
        self.assertEqual((meldungen[0]["ergebnis"], meldungen[0]["ignoriert"]), ("unklar", False))
        pruefer.frueh_nr = 2  # eine andere Äußerung: verworfen
        texte, _ = await durchlassen(StimmWaechter(bereites_gate(), pruefer), [final("Stopp, warte mal")])
        self.assertEqual(texte[0].text, " ")

    async def test_ein_zu_langer_zeitstempel_wird_nicht_gesendet(self):
        """Die Oberfläche lehnt eine Nachricht mit mehr als 64 Zeichen in zeit ab; kürzen hieße, dass sie nicht mehr passt."""
        lang = TranscriptionFrame(text="Hallo", user_id="u", timestamp="x" * (ZEIT_MAX + 1), language=Language.DE, finalized=True)
        texte, meldungen = await durchlassen(StimmWaechter(bereites_gate(), AttrappePruefer(urteil(FREMD))), [lang])
        self.assertEqual(texte[0].timestamp, "x" * (ZEIT_MAX + 1))  # das Ersatztranskript behält ihn trotzdem
        self.assertIsNone(meldungen[0]["zeit"])
        self.assertEqual(ZEIT_MAX, 64)

    async def test_ohne_strengen_modus_oder_abdruck_keine_meldung(self):
        for modus in ("beobachten", "aus"):
            _, meldungen = await durchlassen(StimmWaechter(bereites_gate(modus), AttrappePruefer(urteil(EIGEN))), [final()])
            self.assertEqual(meldungen, [], modus)
        gate = bereites_gate()
        gate.setze_abdruck(None)
        _, meldungen = await durchlassen(StimmWaechter(gate, AttrappePruefer(urteil(FREMD))), [final()])
        self.assertEqual(meldungen, [])

    async def test_keine_antwort_waehrend_wamo_spricht_wird_mit_dem_schalter_fuers_unterbrechen_verworfen(self):
        """WAMO_STIMME_NUR_EIGEN=aus, WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN an: ohne Urteil zählt, ob W.A.I.S. gerade spricht."""
        from pipecat.frames.frames import BotStartedSpeakingFrame

        gate = bereites_gate(schwellen=Schwellen(nur_eigen=False))
        texte, _ = await durchlassen(StimmWaechter(gate, AttrappePruefer(None, dauer=5.0), warten=0.05),
                                     [BotStartedSpeakingFrame(), final("Hallo")])
        self.assertEqual(texte[0].text, " ")
        texte, _ = await durchlassen(StimmWaechter(gate, AttrappePruefer(None, dauer=5.0), warten=0.05), [final("Hallo")])
        self.assertEqual([t.text for t in texte], ["Hallo"])  # ohne Rede von W.A.I.S.: die bisherige Regel


class AbfrageTests(unittest.TestCase):
    """nur_eigen_unterbricht: was die Startstrategie fragt, während W.A.I.S. spricht (None: Regel aus, wie bisher)."""

    def test_nur_im_strengen_modus_mit_abdruck_und_schalter(self):
        pruefer = AttrappePruefer(None)
        gate = bereites_gate()
        abfrage = nur_eigen_unterbricht(StimmWaechter(gate, pruefer))
        self.assertIs(abfrage(), False)  # noch kein Urteil eigen für die laufende Äußerung
        pruefer.eigen_laufend = True
        self.assertIs(abfrage(), True)
        gate.schwellen = Schwellen(unterbrechen_nur_eigen=False)
        self.assertIsNone(abfrage())
        gate.schwellen = Schwellen()
        gate.modus = "beobachten"
        self.assertIsNone(abfrage())
        gate.modus = "streng"
        gate.setze_abdruck(None)
        self.assertIsNone(abfrage())
        gate.setze_abdruck(EIGENER)
        gate.modell_ok = False
        self.assertIsNone(abfrage())


class UnterbrechenNurEigenTests(unittest.IsolatedAsyncioTestCase):
    """Entscheidung vom 17.11.2026: Während W.A.I.S. spricht, unterbricht nur die eigene Stimme. Wer zu sprechen beginnt, wird sofort leiser
    gestellt (Ducken); abgebrochen wird erst nach dem Urteil eigen (früh oder am Sprechende, StimmUrteilFrame vom Prüfer). Fremd oder unklar:
    kein Abbruch, die Dämpfung endet, das Transkript wird verworfen. Stoppwörter wirken erst nach dem Urteil eigen."""

    def setUp(self):
        import soft_interrupt

        self._alt = soft_interrupt.DUCK_VERZOEGERUNG_SECS
        soft_interrupt.DUCK_VERZOEGERUNG_SECS = 0.02

    def tearDown(self):
        import soft_interrupt

        soft_interrupt.DUCK_VERZOEGERUNG_SECS = self._alt

    async def lauf(self, ergebnis: Urteil | None, urteile: list, *, text: str = "Stopp, warte mal", schwellen: Schwellen | None = None,
                   abdruck: bool = True, laufend_eigen: bool = False):
        from pipecat.frames.frames import (BotStartedSpeakingFrame, InterruptionFrame, LLMContextFrame, VADUserStartedSpeakingFrame,
                                           VADUserStoppedSpeakingFrame)
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
        from pipecat.tests.utils import SleepFrame
        from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
        from pipecat.turns.user_turn_strategies import UserTurnStrategies
        from soft_interrupt import MeaningfulWordsUserTurnStartStrategy, SoftInterruptGate

        gate = bereites_gate(schwellen=schwellen)
        if not abdruck:
            gate.setze_abdruck(None)
        pruefer = AttrappePruefer(ergebnis)
        pruefer.eigen_laufend = laufend_eigen
        waechter = StimmWaechter(gate, pruefer, warten=0.2)
        weiche = SoftInterruptGate(ducken=True, max_wait_secs=0.1, playback_lag_secs=0.0)
        nutzer, _ = LLMContextAggregatorPair(LLMContext(), user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[MeaningfulWordsUserTurnStartStrategy(min_words=2, enable_interruptions=False,
                                                            stimme_unterbricht=nur_eigen_unterbricht(waechter))],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)])))
        frames = [BotStartedSpeakingFrame(), SleepFrame(0.02), VADUserStartedSpeakingFrame(start_secs=0.2, timestamp=time.time()),
                  SleepFrame(0.1), zwischenstand(text), SleepFrame(0.1)]
        for u in urteile:  # Urteile des Prüfers (StimmUrteilFrame), so wie er sie schickt
            frames += [u, SleepFrame(0.1)]
        frames += [VADUserStoppedSpeakingFrame(stop_secs=0.2, timestamp=time.time()), final(text), SleepFrame(0.6)]
        unten, _ = await run_test(Pipeline([waechter, nutzer, weiche]), frames_to_send=frames)
        self.abbrueche = sum(isinstance(f, InterruptionFrame) for f in unten)
        self.kontexte = [f for f in unten if isinstance(f, LLMContextFrame)]
        self.leiser = [f.data["an"] for f in unten if isinstance(f, RTVIServerMessageFrame) and f.data.get("type") == "stimme_leiser"]
        self.stimme = [f.data for f in unten if isinstance(f, RTVIServerMessageFrame) and f.data.get("type") == "stimme"]
        self.unten = unten

    @staticmethod
    def urteil_frame(eigen: bool, frueh: bool = False):
        from soft_interrupt import StimmUrteilFrame

        return StimmUrteilFrame(nr=1, eigen=eigen, frueh=frueh)

    async def test_fremd_waehrend_wamo_spricht_bricht_nicht_ab_und_hebt_die_daempfung_auf(self):
        from soft_interrupt import StimmUrteilFrame

        await self.lauf(urteil(UNKLAR, wert=0.12, ueberlappung=True), [self.urteil_frame(False)])
        self.assertEqual(self.abbrueche, 0)
        self.assertEqual(self.leiser, [True, False])  # sofort gedämpft, nach dem Urteil wieder normal
        self.assertEqual(self.kontexte, [])  # kein Zug, nichts im Verlauf
        self.assertEqual([(m["ergebnis"], m["ignoriert"]) for m in self.stimme], [("unklar", True)])
        self.assertFalse([f for f in self.unten if isinstance(f, StimmUrteilFrame)])  # endet im Gate

    async def test_eigen_am_sprechende_bricht_ab_und_der_satz_geht_ans_modell(self):
        await self.lauf(urteil(EIGEN, wert=0.7, ueberlappung=True), [self.urteil_frame(True)])
        self.assertEqual(self.abbrueche, 1)
        self.assertEqual(len(self.kontexte), 1)
        self.assertEqual(self.kontexte[0].context.messages[-1]["content"], "Stopp, warte mal")
        self.assertEqual([(m["ergebnis"], m["ignoriert"]) for m in self.stimme], [("eigen", False)])

    async def test_fruehes_urteil_eigen_bricht_schon_waehrend_der_rede_ab(self):
        await self.lauf(urteil(EIGEN, wert=0.7, ueberlappung=True), [self.urteil_frame(True, frueh=True)])
        self.assertEqual(self.abbrueche, 1)
        namen = [type(f).__name__ for f in self.unten]
        # der Zug beginnt vor dem Sprechende (der Abbruch folgt an der nächsten Wortgrenze oder nach der Zeitgrenze des Gates)
        self.assertLess(namen.index("UserStartedSpeakingFrame"), namen.index("VADUserStoppedSpeakingFrame"))

    async def test_laeuft_schon_ein_urteil_eigen_unterbricht_der_zwischenstand_sofort(self):
        await self.lauf(urteil(EIGEN, wert=0.7, ueberlappung=True), [], laufend_eigen=True)
        self.assertEqual(self.abbrueche, 1)
        namen = [type(f).__name__ for f in self.unten]
        self.assertLess(namen.index("UserStartedSpeakingFrame"), namen.index("VADUserStoppedSpeakingFrame"))

    async def test_stoppwort_wirkt_erst_nach_dem_urteil_eigen(self):
        await self.lauf(urteil(UNKLAR, wert=0.2, ueberlappung=True), [self.urteil_frame(False)], text="Stopp")
        self.assertEqual((self.abbrueche, self.kontexte), (0, []))
        await self.lauf(urteil(KURZ, wert=0.6, secs=0.4, ueberlappung=True), [self.urteil_frame(True)], text="Stopp")
        self.assertEqual(self.abbrueche, 1)
        self.assertEqual(self.kontexte[0].context.messages[-1]["content"], "Stopp")

    async def test_ohne_urteil_bricht_nichts_ab(self):
        """Der Prüfer schweigt (zu langsam): kein Abbruch, das Transkript wird verworfen (keine Antwort in der Frist gilt nicht als eigen)."""
        await self.lauf(None, [])
        self.assertEqual((self.abbrueche, self.kontexte), (0, []))

    async def test_schalter_aus_jede_stimme_unterbricht_sofort_wie_bisher(self):
        await self.lauf(urteil(UNKLAR, wert=0.12, ueberlappung=True), [], schwellen=Schwellen(unterbrechen_nur_eigen=False))
        self.assertEqual(self.abbrueche, 1)
        self.assertEqual(len(self.kontexte), 1)  # Überlappung: der Satz geht durch wie bisher

    async def test_ohne_abdruck_wie_bisher(self):
        await self.lauf(None, [], abdruck=False)
        self.assertEqual((self.abbrueche, len(self.kontexte)), (1, 1))
        self.assertEqual(self.stimme, [])


if __name__ == "__main__":
    unittest.main()
