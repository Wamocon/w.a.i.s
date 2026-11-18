"""Tests für stimme_gate.py: wer Werkzeuge auslösen darf, Einstufung, Schalter, Absicherung der Werkzeuge.

Ausführen:  python -m pytest -q test_stimme_gate.py   (im Ordner voice-core/)
"""

import asyncio
import unittest
from unittest import mock

import numpy as np

from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.processors.frameworks.rtvi import RTVIProcessor

import stimme_gate
from stimme_gate import (
    EIGEN,
    FREMD,
    KURZ,
    OFFENE_WERKZEUGE,
    UNKLAR,
    Schwellen,
    StimmGate,
    abgesichert,
    pruefmodus,
    schemas_absichern,
    schwellen_aus_env,
    tippen_beobachten,
    werkzeuge_absichern,
)
from stimme_modell import DIM

ABDRUCK = np.eye(DIM, dtype=np.float32)[0]


class Uhr:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def bereites_gate(modus="streng", uhr=None) -> StimmGate:
    gate = StimmGate(modus=modus, uhr=uhr or Uhr())
    gate.setze_abdruck(ABDRUCK)
    gate.modell_ok = True
    return gate


class Params:
    def __init__(self):
        self.result_callback = mock.AsyncMock()


class KurzErbenTests(unittest.TestCase):
    """Befund 18.11.2026: Unter 1 s lagen die eigenen Werte bei 0,14 bis 0,49 (11 Äußerungen, nur 27 % erkannt), eine fremde Stimme bei
    0,10 bis 0,30. Eine so kurze Äußerung erbt deshalb das Urteil eigen, wenn WAMO nicht spricht und die letzte sichere Erkennung
    höchstens 60 s zurückliegt."""

    def setUp(self):
        self.uhr = Uhr()
        self.gate = bereites_gate(uhr=self.uhr)
        self.gate.eintragen(EIGEN)

    def test_kurz_nach_eigen_erbt(self):
        for wert in (0.14, 0.21, 0.31):  # die eigenen Werte vom 18.11.2026
            self.assertEqual(self.gate.einstufen(wert, 0.7, False), KURZ, wert)
        self.uhr.t += 60
        self.assertEqual(self.gate.einstufen(0.2, 0.5, False), KURZ)

    def test_nicht_mehr_nach_der_frist(self):
        self.uhr.t += 61
        self.assertEqual(self.gate.einstufen(0.2, 0.5, False), FREMD)
        self.assertEqual(self.gate.einstufen(0.33, 0.5, False), UNKLAR)

    def test_nie_waehrend_wamo_spricht(self):
        self.assertEqual(self.gate.einstufen(0.2, 0.5, True), UNKLAR)  # Echo bleibt draußen

    def test_klar_fremd_erbt_nie(self):
        self.assertEqual(self.gate.einstufen(0.09, 0.5, False), FREMD)  # unter kurz_erben_min: Echo, Rauschen oder klar fremd
        self.assertEqual(self.gate.einstufen(-0.4, 0.5, False), FREMD)
        self.assertEqual(self.gate.einstufen(0.10, 0.5, False), KURZ)

    def test_nie_ab_einer_sekunde(self):
        self.assertEqual(self.gate.einstufen(0.2, 1.2, False), FREMD)  # dort trennt der Wert, das Urteil gilt

    def test_nie_nach_tippen_fremd_oder_ohne_urteil(self):
        for vorher in ("getippt", FREMD, UNKLAR, None):
            gate = bereites_gate(uhr=self.uhr)
            if vorher == "getippt":
                gate.getippt()
            elif vorher is not None:
                gate.eintragen(vorher)
            self.assertNotEqual(gate.einstufen(0.2, 0.5, False), KURZ, vorher)

    def test_geerbt_oeffnet_werkzeuge_nur_kurz(self):
        self.gate.eintragen(self.gate.einstufen(0.2, 0.5, False))
        self.uhr.t += 10
        self.assertIsNone(self.gate.grund_der_stimme())
        self.uhr.t += 6  # über kurz_vertrauen_secs (15 s) seit der letzten sicheren Erkennung
        self.assertEqual(self.gate.grund_der_stimme(), "Stimme nur kurz gehört, nicht sicher erkannt")

    def test_schalter(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_KURZ_ERBEN_SECS": "0"}, clear=True):
            self.assertEqual(schwellen_aus_env().kurz_erben_secs, 0.0)
        with mock.patch.dict("os.environ", {"WAMO_STIMME_KURZ_ERBEN_SECS": "kaputt"}, clear=True):
            self.assertEqual(schwellen_aus_env().kurz_erben_secs, 60.0)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(schwellen_aus_env().kurz_erben_secs, 60.0)
        aus = StimmGate(modus="streng", uhr=self.uhr, schwellen=Schwellen(kurz_erben_secs=0.0))
        aus.setze_abdruck(ABDRUCK)
        aus.modell_ok = True
        aus.eintragen(EIGEN)
        self.assertEqual(aus.einstufen(0.2, 0.5, False), FREMD)


class EinstufungTests(unittest.TestCase):
    def test_einstufung(self):
        gate = StimmGate()
        self.assertEqual(gate.einstufen(0.7, 2.0, False), EIGEN)
        self.assertEqual(gate.einstufen(0.9, 0.5, False), KURZ)  # zu kurz für "eigen", klingt aber nach der Person
        self.assertEqual(gate.einstufen(0.33, 0.5, False), UNKLAR)  # kurz und nicht nach der Person: das Vertrauen geht
        self.assertEqual(gate.einstufen(0.33, 0.5, True), UNKLAR)
        self.assertEqual(gate.einstufen(0.1, 0.5, False), FREMD)  # auch kurz klar fremd
        self.assertEqual(gate.einstufen(0.1, 2.0, False), FREMD)
        self.assertEqual(gate.einstufen(0.1, 2.0, True), UNKLAR)  # WAMO sprach gleichzeitig, es kann Echo sein
        self.assertEqual(gate.einstufen(0.4, 3.5, False), UNKLAR)

    def test_grenzen_gehoeren_zur_besseren_seite(self):
        gate = StimmGate()
        self.assertEqual(gate.einstufen(0.35, 1.0, False), EIGEN)
        self.assertEqual(gate.einstufen(0.45, 3.0, False), EIGEN)
        self.assertEqual(gate.einstufen(0.3, 1.0, False), FREMD)

    def test_eigene_schwellen(self):
        gate = StimmGate(schwellen=Schwellen(eigen_min_kurz=0.6, eigen_min_lang=0.6, fremd_max=0.2, min_secs=2.0))
        self.assertEqual(gate.einstufen(0.55, 3.0, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.25, 3.0, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.65, 1.5, False), KURZ)


class SchwelleNachLaengeTests(unittest.TestCase):
    """Befund vom 17.11.2026: kurze eigene Äußerungen (0,4 bis 1,8 s) lagen meist bei 0,35 bis 0,60, eine zweite Person bei 0,10 bis 0,30.
    Die Schwelle für "eigen" hängt deshalb von der Länge ab: bis KURZ_BIS_SECS die kurze, ab LANG_AB_SECS die lange, dazwischen linear."""

    def test_standard_kurz_0_35_lang_0_45_fremd_0_3(self):
        s = Schwellen()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang, s.fremd_max), (0.35, 0.45, 0.3))
        self.assertEqual((stimme_gate.KURZ_BIS_SECS, stimme_gate.LANG_AB_SECS), (1.5, 3.0))

    def test_schwelle_waechst_linear_mit_der_laenge(self):
        gate = StimmGate()
        for secs, soll in ((0.4, 0.35), (1.0, 0.35), (1.5, 0.35), (2.25, 0.40), (3.0, 0.45), (4.5, 0.45), (8.0, 0.45)):
            self.assertAlmostEqual(gate.schwelle_fuer(secs), soll, places=6, msg=secs)

    def test_einstufung_nach_laenge(self):
        gate = StimmGate()
        self.assertEqual(gate.einstufen(0.36, 1.2, False), EIGEN)  # kurz, aber genug Sprache für ein Urteil
        self.assertEqual(gate.einstufen(0.36, 0.6, False), KURZ)
        self.assertEqual(gate.einstufen(0.34, 0.6, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.39, 2.25, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.40, 2.25, False), EIGEN)
        self.assertEqual(gate.einstufen(0.44, 3.0, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.46, 4.5, False), EIGEN)
        for secs in (0.4, 1.0, 2.0, 4.5):  # fremd bis 0,3 für alle Längen
            self.assertEqual(gate.einstufen(0.3, secs, False), FREMD, secs)
            self.assertEqual(gate.einstufen(0.3, secs, True), UNKLAR, secs)

    def test_befund_vom_17_11(self):
        """Die eigenen Werte (0,35 bis 0,60 bei 0,4 bis 1,5 s) gelten als eigen oder kurz, die zweite Person (0,10 bis 0,30) nie."""
        gate = StimmGate()
        for wert in (0.35, 0.41, 0.6):
            for secs in (0.4, 0.9, 1.5):
                self.assertIn(gate.einstufen(wert, secs, False), (EIGEN, KURZ), (wert, secs))
        for wert in (0.1, 0.2, 0.3):
            for secs in (0.4, 0.9, 1.8):
                self.assertEqual(gate.einstufen(wert, secs, False), FREMD, (wert, secs))

    def test_kurz_bewertet_immer_mit_der_kurzen_schwelle(self):
        """Unter WAMO_STIMME_MIN_SECS gilt die kurze Schwelle, auch wenn MIN_SECS über KURZ_BIS_SECS liegt."""
        gate = StimmGate(schwellen=Schwellen(min_secs=2.5))
        self.assertEqual(gate.einstufen(0.36, 2.0, False), KURZ)
        self.assertAlmostEqual(gate.schwelle_fuer(2.0), 0.35)
        self.assertEqual(gate.einstufen(0.36, 2.6, False), UNKLAR)

    def test_persoenliche_schwelle_ersetzt_die_kurze(self):
        gate = bereites_gate()
        gate.setze_abdruck(ABDRUCK, schwelle=0.42)
        self.assertEqual(gate.schwelle_kurz, 0.42)
        self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.42)
        self.assertAlmostEqual(gate.schwelle_fuer(3.0), 0.45)  # die lange bleibt aus der Umgebung
        self.assertEqual(gate.einstufen(0.41, 1.2, False), UNKLAR)
        self.assertEqual(gate.einstufen(0.42, 1.2, False), EIGEN)
        gate.setze_abdruck(ABDRUCK, schwelle=0.31)
        self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.31)
        self.assertAlmostEqual(gate.schwelle_fuer(2.25), 0.38)
        self.assertEqual(gate.einstufen(0.32, 0.8, False), KURZ)

    def test_die_lange_schwelle_liegt_nie_unter_der_persoenlichen(self):
        gate = bereites_gate()
        gate.setze_abdruck(ABDRUCK, schwelle=0.48)
        for secs in (1.0, 2.25, 3.0, 6.0):
            self.assertAlmostEqual(gate.schwelle_fuer(secs), 0.48, msg=secs)

    def test_persoenliche_schwelle_nie_unter_fremd_max(self):
        gate = StimmGate(schwellen=Schwellen(fremd_max=0.33))
        gate.setze_abdruck(ABDRUCK, schwelle=0.30)
        self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.33)

    def test_ohne_abdruck_oder_ohne_angabe_keine_persoenliche_schwelle(self):
        gate = bereites_gate()
        gate.setze_abdruck(ABDRUCK, schwelle=0.42)
        gate.setze_abdruck(ABDRUCK)  # neu eingelernt oder geladen ohne Schwelle (Migration 0025 fehlt)
        self.assertIsNone(gate.schwelle_kurz)
        self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.35)
        gate.setze_abdruck(ABDRUCK, schwelle=0.42)
        gate.setze_abdruck(None, geloescht=True)
        self.assertIsNone(gate.schwelle_kurz)
        gate.setze_abdruck(ABDRUCK, schwelle=0.42)
        gate.setze_abdruck(ABDRUCK, ok=False, schwelle=0.42)  # nicht lesbar: nichts davon gilt
        self.assertIsNone(gate.schwelle_kurz)

    def test_ohne_speicherbare_schwelle_gilt_keine(self):
        """Fehlt die Spalte in der Datenbank (Migration 0025), setzt die Sitzung schwelle_erlaubt auf False: dann wirkt auch eine gerade
        berechnete Schwelle nicht, alles läuft wie mit der Schwelle aus der Umgebung."""
        gate = bereites_gate()
        gate.schwelle_erlaubt = False
        gate.setze_abdruck(ABDRUCK, schwelle=0.48)
        self.assertIsNone(gate.schwelle_kurz)
        self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.35)

    def test_unbrauchbare_persoenliche_schwelle_gilt_nicht(self):
        gate = bereites_gate()
        for falsch in (float("nan"), float("inf"), 0.1, 0.9, -0.4):
            gate.setze_abdruck(ABDRUCK, schwelle=falsch)
            self.assertIsNone(gate.schwelle_kurz, falsch)
            self.assertAlmostEqual(gate.schwelle_fuer(1.0), 0.35)


class VertrauenTests(unittest.TestCase):
    def test_vertrauen_haelt_ueber_kurze_folgesaetze_und_laeuft_ab(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        self.assertIsNotNone(gate.grund_der_stimme())  # noch nichts gehört
        gate.eintragen(EIGEN)
        gate.eintragen(KURZ)  # kurzes "Ja"
        self.assertIsNone(gate.grund_der_stimme())
        uhr.t += gate.schwellen.vertrauen_secs + 1
        self.assertIsNotNone(gate.grund_der_stimme())

    def test_vertrauen_aus_kurzen_aeusserungen_gilt_hoechstens_15_sekunden(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.eintragen(EIGEN)
        uhr.t += 10
        gate.eintragen(KURZ)
        self.assertIsNone(gate.grund_der_stimme())
        uhr.t += 4  # 14 s nach der sicheren Erkennung
        gate.eintragen(KURZ)  # eine weitere kurze Äußerung verlängert nichts
        self.assertIsNone(gate.grund_der_stimme())
        uhr.t += 2  # 16 s
        self.assertEqual(gate.grund_der_stimme(), "Stimme nur kurz gehört, nicht sicher erkannt")
        gate.eintragen(EIGEN)  # eine sichere Erkennung erneuert das Vertrauen
        self.assertIsNone(gate.grund_der_stimme())

    def test_ohne_kurze_aeusserung_gilt_das_vertrauen_bis_zur_langen_frist(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.eintragen(EIGEN)
        uhr.t += 60
        self.assertIsNone(gate.grund_der_stimme())

    def test_kurze_aeusserung_nach_getipptem_text_gilt_ebenfalls_hoechstens_15_sekunden(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.getippt()
        gate.eintragen(KURZ)
        uhr.t += 16
        self.assertIsNotNone(gate.grund_der_stimme())

    def test_kurz_ohne_vorheriges_vertrauen_gibt_keines(self):
        gate = bereites_gate()
        gate.eintragen(KURZ)
        self.assertEqual(gate.grund_der_stimme(), "Stimme noch nicht erkannt")

    def test_getippt_erneuert_das_kurz_vertrauen(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.eintragen(EIGEN)
        gate.eintragen(KURZ)
        uhr.t += 20
        self.assertIsNotNone(gate.grund_der_stimme())
        gate.getippt()
        self.assertIsNone(gate.grund_der_stimme())

    def test_loeschen_des_abdrucks_loescht_auch_den_kurz_zustand(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.eintragen(EIGEN)
        gate.eintragen(KURZ)
        gate.setze_abdruck(None)
        gate.setze_abdruck(ABDRUCK)
        gate.eintragen(EIGEN)
        uhr.t += 20
        self.assertIsNone(gate.grund_der_stimme())  # ein neuer Abdruck beginnt ohne Rest des alten Zustands

    def test_unklar_mit_genug_sprache_entzieht_das_vertrauen(self):
        gate = bereites_gate()
        gate.eintragen(EIGEN)
        gate.eintragen(UNKLAR)
        self.assertEqual(gate.grund_der_stimme(), "Stimme nicht sicher erkannt")

    def test_aeltere_aeusserung_ueberschreibt_getippten_text_nicht(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gehoert = uhr()  # ein Gast spricht ...
        uhr.t += 1
        gate.getippt()  # ... die Person tippt, während die Prüfung noch läuft
        gate.eintragen(FREMD, gehoert)
        self.assertIsNone(gate.grund_der_stimme())
        gate.eintragen(FREMD, uhr())  # spricht der Gast danach, zählt es
        self.assertEqual(gate.grund_der_stimme(), "fremde Stimme")

    def test_fremde_stimme_sperrt_bis_die_person_wieder_erkannt_wird_oder_tippt(self):
        gate = bereites_gate()
        gate.eintragen(EIGEN)
        gate.eintragen(FREMD)
        self.assertEqual(gate.grund_der_stimme(), "fremde Stimme")
        gate.getippt()
        self.assertIsNone(gate.grund_der_stimme())
        gate.eintragen(FREMD)
        gate.eintragen(EIGEN)
        self.assertIsNone(gate.grund_der_stimme())

    def test_stimme_vertraut_nur_nach_sicherer_erkennung_nicht_nach_tippen(self):
        gate = bereites_gate()
        gate.getippt()
        self.assertFalse(gate.stimme_vertraut())
        gate.eintragen(EIGEN)
        self.assertTrue(gate.stimme_vertraut())

    def test_zwei_sitzungen_teilen_keinen_zustand(self):
        a, b = bereites_gate(), bereites_gate()
        a.eintragen(FREMD)
        self.assertEqual(a.grund_der_stimme(), "fremde Stimme")
        self.assertEqual(b.grund_der_stimme(), "Stimme noch nicht erkannt")


class AbdruckGeschuetztTests(unittest.TestCase):
    def test_ein_abdruck_schuetzt_auch_nach_dem_loeschen_in_derselben_sitzung(self):
        gate = StimmGate(modus="streng", uhr=Uhr())
        self.assertFalse(gate.abdruck_geschuetzt)
        gate.setze_abdruck(None)  # erster Stand: nichts eingelernt
        self.assertFalse(gate.abdruck_geschuetzt)
        gate.setze_abdruck(ABDRUCK)
        self.assertTrue(gate.abdruck_geschuetzt)
        gate.setze_abdruck(None, geloescht=True)  # gelöscht: der Schutz bleibt, sonst könnte jemand Fremdes danach neu einlernen
        self.assertTrue(gate.abdruck_geschuetzt)
        gate.setze_abdruck(ABDRUCK)  # neu eingelernt
        self.assertTrue(gate.abdruck_geschuetzt)
        gate.setze_abdruck(None)  # ein späterer leerer Stand hebt den Schutz nicht auf
        self.assertTrue(gate.abdruck_geschuetzt)

    def test_ein_nicht_lesbarer_stand_ist_kein_abdruck(self):
        gate = StimmGate(modus="streng", uhr=Uhr())
        gate.setze_abdruck(None, ok=False)
        self.assertFalse(gate.abdruck_geschuetzt)  # der Stand ist unbekannt, das prüft die Sitzung über den Zustand


class NichtSicherEigenTests(unittest.IsolatedAsyncioTestCase):
    """Ein Zug, der nicht sicher von der Person stammt (Abdruck da, Prüfung bereit, Modus streng), gilt als gefärbt."""

    def test_vor_dem_ersten_urteil_und_nach_unklar_oder_fremd(self):
        gate = bereites_gate()
        self.assertTrue(gate.nicht_sicher_eigen())  # noch nichts erkannt
        gate.eintragen(EIGEN)
        self.assertFalse(gate.nicht_sicher_eigen())
        for urteil in (UNKLAR, FREMD):
            gate.eintragen(urteil)
            self.assertTrue(gate.nicht_sicher_eigen(), urteil)

    def test_kurz_nach_eigen_und_getippter_text_sind_sicher_aber_nur_begrenzt(self):
        uhr = Uhr()
        gate = bereites_gate(uhr=uhr)
        gate.eintragen(EIGEN)
        gate.eintragen(KURZ)
        self.assertFalse(gate.nicht_sicher_eigen())
        uhr.t += 16
        self.assertTrue(gate.nicht_sicher_eigen())
        gate.getippt()
        self.assertFalse(gate.nicht_sicher_eigen())

    async def test_eine_laufende_pruefung_gilt_als_nicht_sicher(self):
        gate = bereites_gate()
        gate.eintragen(EIGEN)
        offen = asyncio.create_task(asyncio.sleep(1))
        gate.verfolgen(offen)
        self.assertTrue(gate.nicht_sicher_eigen())
        offen.cancel()
        await asyncio.gather(offen, return_exceptions=True)
        self.assertFalse(gate.nicht_sicher_eigen())

    def test_ohne_abdruck_ohne_bereite_pruefung_und_ausser_streng_aendert_sich_nichts(self):
        ohne = StimmGate(modus="streng", uhr=Uhr())
        ohne.setze_abdruck(None)
        self.assertFalse(ohne.nicht_sicher_eigen())
        laedt = StimmGate(modus="streng", uhr=Uhr())
        laedt.setze_abdruck(ABDRUCK)  # Modell noch nicht geladen
        self.assertFalse(laedt.nicht_sicher_eigen())
        for modus in ("beobachten", "aus"):
            gate = bereites_gate(modus)
            gate.eintragen(FREMD)
            self.assertFalse(gate.nicht_sicher_eigen(), modus)


class StatusTests(unittest.TestCase):
    def test_status_je_zustand(self):
        gate = StimmGate(modus="streng")
        self.assertEqual(gate.status, "laedt")
        gate.setze_abdruck(None)
        self.assertEqual(gate.status, "fehlt")
        gate.setze_abdruck(ABDRUCK)
        self.assertEqual(gate.status, "laedt")  # Abdruck da, Modell noch nicht geladen
        gate.modell_ok = True
        self.assertEqual(gate.status, "bereit")
        gate.modell_ok = False
        self.assertEqual(gate.status, "kaputt")
        gate.setze_abdruck(None, ok=False)
        self.assertEqual(gate.status, "kaputt")
        gate.modus = "aus"
        self.assertEqual(gate.status, "aus")

    def test_wirkt_nur_mit_abdruck(self):
        gate = StimmGate(modus="streng")
        self.assertFalse(gate.hat_abdruck)
        gate.setze_abdruck(ABDRUCK)
        self.assertTrue(gate.hat_abdruck)
        gate.setze_abdruck(None)
        self.assertFalse(gate.hat_abdruck)


class SperrTests(unittest.IsolatedAsyncioTestCase):
    async def test_streng_sperrt_mit_ergebnis_fuer_das_modell(self):
        gate = bereites_gate()
        gate.eintragen(FREMD)
        gesperrt = await gate.pruefen("programm_oeffnen")
        self.assertEqual(gesperrt["status"], "blocked")
        self.assertTrue(gesperrt["grund"].startswith("Stimmprüfung"))
        self.assertIn("Nicht erneut", gesperrt["hinweis"])

    async def test_offene_werkzeuge_und_modus_beobachten_und_aus_sperren_nie(self):
        self.assertEqual(OFFENE_WERKZEUGE, {"aktuelle_zeit", "websuche", "canvas_zeigen"})
        gate = bereites_gate()
        gate.eintragen(FREMD)
        for name in OFFENE_WERKZEUGE:
            self.assertIsNone(await gate.pruefen(name))
        gate.modus = "beobachten"
        self.assertIsNone(await gate.pruefen("programm_oeffnen"))
        gate.modus = "aus"
        self.assertIsNone(await gate.pruefen("programm_oeffnen"))

    async def test_ohne_abdruck_wird_nichts_gesperrt(self):
        gate = StimmGate(modus="streng", uhr=Uhr())
        gate.setze_abdruck(None)
        self.assertEqual(gate.status, "fehlt")
        self.assertIsNone(await gate.pruefen("programm_oeffnen"))
        self.assertIsNone(await gate.pruefen("merken"))

    async def test_streng_sperrt_solange_ein_vorhandener_abdruck_nicht_pruefbar_ist(self):
        gate = StimmGate(modus="streng")  # Abdruck lädt noch
        self.assertEqual(gate.status, "laedt")
        self.assertIsNotNone(await gate.pruefen("programm_oeffnen"))
        gate.setze_abdruck(None, ok=False)  # Datenbank nicht lesbar: unbekannt, ob es einen Abdruck gibt
        self.assertEqual(gate.status, "kaputt")
        self.assertIsNotNone(await gate.pruefen("programm_oeffnen"))
        gate.setze_abdruck(ABDRUCK)
        gate.modell_ok = False  # Abdruck da, Modell fehlt
        self.assertIsNotNone(await gate.pruefen("programm_oeffnen"))

    async def test_getippter_text_geht_auch_wenn_die_pruefung_nicht_bereit_ist(self):
        gate = StimmGate(modus="streng", uhr=Uhr())
        gate.setze_abdruck(None, ok=False)
        gate.getippt()
        self.assertIsNone(await gate.pruefen("programm_oeffnen"))

    async def test_wartet_auf_die_laufende_pruefung(self):
        gate = bereites_gate()

        async def pruefen():
            await asyncio.sleep(0.05)
            gate.eintragen(EIGEN)

        gate.verfolgen(asyncio.create_task(pruefen()))
        self.assertIsNone(await gate.pruefen("programm_oeffnen"))

    async def test_zu_lange_pruefung_sperrt_statt_altes_ergebnis(self):
        gate = bereites_gate()
        gate.eintragen(EIGEN)
        langsam = asyncio.create_task(asyncio.sleep(1))
        gate.verfolgen(langsam)
        with mock.patch.object(stimme_gate, "WARTEN_WERKZEUG_SECS", 0.02):
            gesperrt = await gate.pruefen("programm_oeffnen")
        langsam.cancel()
        self.assertIn("dauert zu lange", gesperrt["grund"])


class SchalterTests(unittest.TestCase):
    def test_modus_standard_ist_streng_und_unbekanntes_auch(self):
        self.assertEqual(pruefmodus(""), "streng")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(pruefmodus(None), "streng")
        for modus in ("aus", "beobachten", "streng"):
            self.assertEqual(pruefmodus(modus), modus)
            self.assertEqual(pruefmodus(f"  {modus.upper()} "), modus)
        self.assertEqual(pruefmodus("strenge"), "streng")

    def test_unbekannter_modus_wird_einmal_gewarnt(self):
        stimme_gate._GEWARNT.clear()
        with mock.patch.object(stimme_gate.logger, "warning") as warnung:
            pruefmodus("vielleicht")
            pruefmodus("vielleicht")
        self.assertEqual(warnung.call_count, 1)

    def test_modus_aus_der_umgebung(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_PRUEFUNG": "beobachten"}):
            self.assertEqual(StimmGate.aus_umgebung().modus, "beobachten")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(StimmGate.aus_umgebung().modus, "streng")

    def test_schwellen_standard(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang, s.fremd_max, s.min_secs, s.vertrauen_secs), (0.35, 0.45, 0.3, 1.0, 120.0))

    def test_schwellen_aus_der_umgebung_mit_komma(self):
        umgebung = {"WAMO_STIMME_EIGEN_MIN": "0,6", "WAMO_STIMME_FREMD_MAX": "0.25", "WAMO_STIMME_MIN_SECS": "1.5",
                    "WAMO_STIMME_VERTRAUEN_SECS": "60"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            s = schwellen_aus_env()
        # nur das alte WAMO_STIMME_EIGEN_MIN gesetzt: es gilt für beide Längen wie bisher
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang, s.fremd_max, s.min_secs, s.vertrauen_secs), (0.6, 0.6, 0.25, 1.5, 60.0))

    def test_unbrauchbare_zahlen_heissen_standard(self):
        umgebung = {"WAMO_STIMME_VERTRAUEN_SECS": "nan", "WAMO_STIMME_EIGEN_MIN": "x", "WAMO_STIMME_MIN_SECS": "inf",
                    "WAMO_STIMME_FREMD_MAX": "9"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            s = schwellen_aus_env()
        self.assertEqual(s, Schwellen())

    def test_fremd_muss_unter_eigen_liegen_sonst_gelten_beide_standardwerte(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN": "0.4", "WAMO_STIMME_FREMD_MAX": "0.45"}, clear=True):
            self.assertEqual(schwellen_aus_env(), Schwellen())

    def test_kurz_vertrauen_standard_und_schalter(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(schwellen_aus_env().kurz_vertrauen_secs, 15.0)
        with mock.patch.dict("os.environ", {"WAMO_STIMME_KURZ_VERTRAUEN_SECS": "30"}, clear=True):
            self.assertEqual(schwellen_aus_env().kurz_vertrauen_secs, 30.0)
        for roh in ("0", "-5", "x", "nan", "9999"):
            with mock.patch.dict("os.environ", {"WAMO_STIMME_KURZ_VERTRAUEN_SECS": roh}, clear=True):
                self.assertEqual(schwellen_aus_env().kurz_vertrauen_secs, 15.0, roh)

    def test_kurz_vertrauen_bleibt_wenn_fremd_und_eigen_nicht_zusammenpassen(self):
        umgebung = {"WAMO_STIMME_EIGEN_MIN": "0.4", "WAMO_STIMME_FREMD_MAX": "0.45", "WAMO_STIMME_KURZ_VERTRAUEN_SECS": "30"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang, s.fremd_max, s.kurz_vertrauen_secs), (0.35, 0.45, 0.3, 30.0))

    def test_eigen_min_hat_die_untergrenze_0_35(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN": "0.3", "WAMO_STIMME_FREMD_MAX": "0.1"}, clear=True):
            s = schwellen_aus_env()
            self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.35, 0.45))  # zu niedrig: Standard
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN": "0.35", "WAMO_STIMME_FREMD_MAX": "0.2"}, clear=True):
            s = schwellen_aus_env()
            self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.35, 0.35))

    def test_kurz_und_lang_aus_der_umgebung(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN_KURZ": "0,4", "WAMO_STIMME_EIGEN_MIN_LANG": "0.5"}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.4, 0.5))

    def test_neue_schalter_gehen_vor_das_alte_gilt_fuer_den_rest(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN": "0.5", "WAMO_STIMME_EIGEN_MIN_LANG": "0.6"}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.5, 0.6))
        with mock.patch.dict("os.environ", {"WAMO_STIMME_EIGEN_MIN": "0.5", "WAMO_STIMME_EIGEN_MIN_KURZ": "0.4"}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.4, 0.5))

    def test_kurz_nie_ueber_lang(self):
        stimme_gate._GEWARNT.clear()
        umgebung = {"WAMO_STIMME_EIGEN_MIN_KURZ": "0.5", "WAMO_STIMME_EIGEN_MIN_LANG": "0.4"}
        with mock.patch.dict("os.environ", umgebung, clear=True), mock.patch.object(stimme_gate.logger, "warning") as warnung:
            s = schwellen_aus_env()
            schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang), (0.5, 0.5))  # die lange steigt auf die kurze
        self.assertEqual(warnung.call_count, 1)

    def test_kurz_und_lang_haben_denselben_bereich_wie_eigen_min(self):
        for name, standard in (("WAMO_STIMME_EIGEN_MIN_KURZ", 0.35), ("WAMO_STIMME_EIGEN_MIN_LANG", 0.45)):
            for roh in ("0.3", "0.96", "x", "nan"):
                with mock.patch.dict("os.environ", {name: roh}, clear=True):
                    s = schwellen_aus_env()
                self.assertEqual(s.eigen_min_kurz if name.endswith("KURZ") else s.eigen_min_lang, standard, (name, roh))

    def test_fremd_muss_unter_der_kurzen_liegen(self):
        umgebung = {"WAMO_STIMME_EIGEN_MIN_KURZ": "0.4", "WAMO_STIMME_FREMD_MAX": "0.42"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            self.assertEqual(schwellen_aus_env(), Schwellen())

    def test_vertrauen_hat_eine_grenze_nach_unten(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_VERTRAUEN_SECS": "0"}, clear=True):
            self.assertEqual(schwellen_aus_env().vertrauen_secs, 120.0)

    def test_verwerfen_standard(self):
        """Strenger Wächter (16.11.2026): unklare Äußerungen bis 0,4 verwerfen, ohne Mindestlänge."""
        with mock.patch.dict("os.environ", {}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.verwerfen_max, s.verwerfen_min_secs), (0.4, 0.0))
        self.assertEqual((Schwellen().verwerfen_max, Schwellen().verwerfen_min_secs), (0.4, 0.0))

    def test_verwerfen_aus_der_umgebung(self):
        umgebung = {"WAMO_STIMME_VERWERFEN_MAX": "0,45", "WAMO_STIMME_VERWERFEN_MIN_SECS": "0.5"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.verwerfen_max, s.verwerfen_min_secs), (0.45, 0.5))
        with mock.patch.dict("os.environ", {"WAMO_STIMME_VERWERFEN_MIN_SECS": "0"}, clear=True):
            self.assertEqual(schwellen_aus_env().verwerfen_min_secs, 0.0)  # 0 ist ein gültiger Wert, kein "leer"
        with mock.patch.dict("os.environ", {"WAMO_STIMME_VERWERFEN_MIN_SECS": "10"}, clear=True):
            self.assertEqual(schwellen_aus_env().verwerfen_min_secs, 10.0)  # die Obergrenze gilt noch

    def test_verwerfen_max_liegt_zwischen_fremd_und_eigen(self):
        """Beide Ränder sind erlaubt: FREMD_MAX schaltet das Verwerfen unklarer Äußerungen ab, EIGEN_MIN_LANG (die höchste Schwelle für
        eigen) verwirft jede unklare. Zahlen außerhalb werden an den Rand gesetzt ("0" heißt also: nur fremde verwerfen), keine Zahl heißt
        Standard."""
        for roh, soll in (("0.3", 0.3), ("0.45", 0.45), ("0.29", 0.3), ("0", 0.3), ("0.5", 0.45), ("0.9", 0.45), ("x", 0.4),
                          ("nan", 0.4), ("-1", 0.4)):
            with mock.patch.dict("os.environ", {"WAMO_STIMME_VERWERFEN_MAX": roh}, clear=True):
                self.assertEqual(schwellen_aus_env().verwerfen_max, soll, roh)

    def test_verwerfen_max_ausserhalb_wird_einmal_gewarnt(self):
        stimme_gate._GEWARNT.clear()
        with mock.patch.dict("os.environ", {"WAMO_STIMME_VERWERFEN_MAX": "0.1"}, clear=True), \
                mock.patch.object(stimme_gate.logger, "warning") as warnung:
            schwellen_aus_env()
            schwellen_aus_env()
        self.assertEqual(warnung.call_count, 1)

    def test_verwerfen_max_folgt_geaenderten_schwellen(self):
        """Der Standard 0,4 rückt in den Bereich von FREMD_MAX bis EIGEN_MIN, wenn diese verschoben sind."""
        with mock.patch.dict("os.environ", {"WAMO_STIMME_FREMD_MAX": "0.45", "WAMO_STIMME_EIGEN_MIN": "0.6"}, clear=True):
            self.assertEqual(schwellen_aus_env().verwerfen_max, 0.45)
        with mock.patch.dict("os.environ", {"WAMO_STIMME_FREMD_MAX": "0.1", "WAMO_STIMME_EIGEN_MIN": "0.35"}, clear=True):
            self.assertEqual(schwellen_aus_env().verwerfen_max, 0.35)
        umgebung = {"WAMO_STIMME_FREMD_MAX": "0.45", "WAMO_STIMME_EIGEN_MIN": "0.6", "WAMO_STIMME_VERWERFEN_MAX": "0.4"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            self.assertEqual(schwellen_aus_env().verwerfen_max, 0.45)  # unter FREMD_MAX: Standard im neuen Bereich

    def test_verwerfen_bleibt_wenn_fremd_und_eigen_nicht_zusammenpassen(self):
        umgebung = {"WAMO_STIMME_EIGEN_MIN": "0.4", "WAMO_STIMME_FREMD_MAX": "0.45", "WAMO_STIMME_VERWERFEN_MAX": "0.42",
                    "WAMO_STIMME_VERWERFEN_MIN_SECS": "0.5"}
        with mock.patch.dict("os.environ", umgebung, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.eigen_min_kurz, s.eigen_min_lang, s.fremd_max, s.verwerfen_max, s.verwerfen_min_secs),
                         (0.35, 0.45, 0.3, 0.42, 0.5))

    def test_verwerfen_min_secs_unbrauchbar_heisst_standard(self):
        for roh in ("-1", "x", "nan", "11"):
            with mock.patch.dict("os.environ", {"WAMO_STIMME_VERWERFEN_MIN_SECS": roh}, clear=True):
                self.assertEqual(schwellen_aus_env().verwerfen_min_secs, 0.0, roh)

    def test_nur_eigen_schalter(self):
        """WAMO_STIMME_NUR_EIGEN und WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN (17.11.2026): Standard an, aus heißt das Verhalten davor."""
        with mock.patch.dict("os.environ", {}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.nur_eigen, s.unterbrechen_nur_eigen), (True, True))
        with mock.patch.dict("os.environ", {"WAMO_STIMME_NUR_EIGEN": "aus", "WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN": "0"}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.nur_eigen, s.unterbrechen_nur_eigen), (False, False))
        with mock.patch.dict("os.environ", {"WAMO_STIMME_NUR_EIGEN": "aus"}, clear=True):
            s = schwellen_aus_env()
        self.assertEqual((s.nur_eigen, s.unterbrechen_nur_eigen), (False, True))  # unabhängig voneinander
        with mock.patch.dict("os.environ", {"WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN": "vielleicht"}, clear=True):
            self.assertTrue(schwellen_aus_env().unterbrechen_nur_eigen)  # Tippfehler: bleibt an (env_schalter)

    def test_nur_eigen_gilt_nur_im_strengen_modus_mit_bereiter_pruefung(self):
        gate = StimmGate(modus="streng", uhr=Uhr())
        self.assertFalse(gate.verwirft or gate.nur_eigen_unterbricht())  # Abdruck noch nicht geladen
        gate.setze_abdruck(ABDRUCK)
        gate.modell_ok = True
        self.assertTrue(gate.verwirft and gate.nur_eigen_unterbricht())
        gate.schwellen = Schwellen(unterbrechen_nur_eigen=False)
        self.assertEqual((gate.verwirft, gate.nur_eigen_unterbricht()), (True, False))
        gate.schwellen = Schwellen()
        for modus in ("beobachten", "aus"):
            gate.modus = modus
            self.assertFalse(gate.verwirft or gate.nur_eigen_unterbricht(), modus)
        gate.modus = "streng"
        gate.setze_abdruck(None)  # kein Abdruck (auch jedes Laborprofil: es bekommt nie ein Gate)
        self.assertFalse(gate.verwirft or gate.nur_eigen_unterbricht())


class WerkzeugTests(unittest.IsolatedAsyncioTestCase):
    async def test_gesperrt_ruft_den_handler_nicht_auf(self):
        gate = bereites_gate()
        gate.eintragen(FREMD)
        handler = mock.AsyncMock()
        params = Params()
        await abgesichert("programm_oeffnen", handler, gate)(params)
        handler.assert_not_awaited()
        self.assertEqual(params.result_callback.await_args.args[0]["status"], "blocked")

    async def test_handler_fuer_alle_werkzeuge_prueft_den_aufgerufenen_namen(self):
        gate = bereites_gate()
        gate.eintragen(FREMD)
        handler = mock.AsyncMock()
        eingepackt = abgesichert(None, handler, gate)
        params = Params()
        params.function_name = "programm_oeffnen"
        await eingepackt(params)
        handler.assert_not_awaited()
        params.function_name = "aktuelle_zeit"
        await eingepackt(params)
        handler.assert_awaited_once()

    async def test_erlaubt_ruft_den_handler_auf(self):
        gate = bereites_gate()
        gate.eintragen(EIGEN)
        handler = mock.AsyncMock()
        params = Params()
        await abgesichert("programm_oeffnen", handler, gate)(params)
        handler.assert_awaited_once_with(params)

    def test_offen_und_schon_geprueft_bleiben_unveraendert(self):
        gate = bereites_gate()
        handler = mock.AsyncMock()
        self.assertIs(abgesichert("aktuelle_zeit", handler, gate), handler)
        eingepackt = abgesichert("merken", handler, gate)
        self.assertIs(abgesichert("merken", eingepackt, gate), eingepackt)
        anderes = bereites_gate()
        self.assertIsNot(abgesichert("merken", eingepackt, anderes), eingepackt)  # ein anderes Gate prüft selbst

    def test_tool_options_bleiben_erhalten(self):
        @tool_options(timeout_secs=30)
        async def handler(params):
            pass

        self.assertEqual(abgesichert("bildschirm_ansehen", handler, bereites_gate())._pipecat_timeout_secs, 30)

    def test_registrierung_am_llm_laeuft_durch_das_gate(self):
        gate = bereites_gate()
        llm = mock.Mock()
        original = llm.register_function
        werkzeuge_absichern(llm, gate)
        handler = mock.AsyncMock()
        llm.register_function("merken", handler, timeout_secs=5)
        name, registriert = original.call_args.args
        self.assertEqual(name, "merken")
        self.assertIs(registriert._wamo_stimme_gate, gate)
        self.assertEqual(original.call_args.kwargs, {"timeout_secs": 5})
        llm.register_function("aktuelle_zeit", handler)
        self.assertIs(original.call_args.args[1], handler)

    def test_echtes_llm_registriert_eingepackte_handler(self):
        from pipecat.services.anthropic.llm import AnthropicLLMService

        gate = bereites_gate()
        llm = AnthropicLLMService(api_key="test")
        werkzeuge_absichern(llm, gate)
        llm.register_function("merken", mock.AsyncMock())
        self.assertIs(llm._functions["merken"].handler._wamo_stimme_gate, gate)
        # Host-Werkzeuge kommen mit Handler im Schema; Pipecat gleicht sie bei jedem Kontext ab
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        tools = ToolsSchema(standard_tools=schemas_absichern(
            [FunctionSchema("programm_oeffnen", "x", {}, [], handler=mock.AsyncMock())], gate))
        llm._sync_registered_tool_handlers(tools)
        erster = llm._functions["programm_oeffnen"].handler
        llm._sync_registered_tool_handlers(tools)
        self.assertIs(llm._functions["programm_oeffnen"].handler, erster)
        self.assertIs(erster._wamo_stimme_gate, gate)

    def test_host_werkzeuge_werden_genau_einmal_eingepackt(self):
        gate = bereites_gate()
        roh = mock.AsyncMock()
        schemas = [FunctionSchema("programm_oeffnen", "x", {}, [], handler=roh), FunctionSchema("ohne", "y", {}, [])]
        neu = schemas_absichern(schemas, gate)
        self.assertEqual([s.name for s in neu], ["programm_oeffnen", "ohne"])
        self.assertIsNot(neu[0].handler, roh)
        self.assertIsNone(neu[1].handler)
        self.assertIs(abgesichert(neu[0].name, neu[0].handler, gate), neu[0].handler)  # nicht noch einmal einpacken
        self.assertEqual(neu[0].required, [])
        self.assertEqual(neu[0].description, "x")


class GetipptTests(unittest.IsolatedAsyncioTestCase):
    def test_pipecat_hat_den_haken_noch(self):
        self.assertTrue(hasattr(RTVIProcessor, "_handle_send_text"))

    async def test_getippter_text_zaehlt_wie_die_eigene_stimme(self):
        gate = bereites_gate()
        gate.eintragen(FREMD)
        rtvi = mock.Mock()
        original = mock.AsyncMock()
        rtvi._handle_send_text = original
        self.assertTrue(tippen_beobachten(rtvi, gate))
        await rtvi._handle_send_text("daten")
        original.assert_awaited_once_with("daten")
        self.assertIsNone(gate.grund_der_stimme())

    def test_fehlender_haken_wird_gemeldet(self):
        self.assertFalse(tippen_beobachten(object(), bereites_gate()))


class StandNachrichtTests(unittest.TestCase):
    """Die Stand-Nachricht {"type": "stimme", "status", "modus"} entsteht an einer Stelle (Gate), nicht in Prüfer, Sitzung und Einlernen."""

    def test_stand_des_gates(self):
        gate = StimmGate(modus="streng")
        self.assertEqual(gate.stand(), {"type": "stimme", "status": "laedt", "modus": "streng"})
        self.assertEqual(bereites_gate().stand(), {"type": "stimme", "status": "bereit", "modus": "streng"})
        self.assertEqual(gate.stand("kaputt"), {"type": "stimme", "status": "kaputt", "modus": "streng"})
        self.assertEqual(stimme_gate.stand_nachricht("aus", "aus"), {"type": "stimme", "status": "aus", "modus": "aus"})

    def test_keine_zweite_stelle_baut_sie(self):
        from pathlib import Path

        ordner = Path(stimme_gate.__file__).parent
        for datei in ("stimme_pruefer.py", "stimme_sitzung.py", "stimme_einlernen.py", "stimme_waechter.py"):
            self.assertNotIn('"type": "stimme", "status"', (ordner / datei).read_text(encoding="utf-8").split('"""', 2)[-1], datei)


if __name__ == "__main__":
    unittest.main()
