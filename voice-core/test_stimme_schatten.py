"""Tests für stimme_schatten.py: zweites Sprechermodell im Schattenbetrieb (Laden mit Prüfsummen, Wert je Äußerung nur ins Log, Abdruck beim
Einlernen, Speichern und Laden in speakers, Schalter). Das Urteil bleibt allein bei TitaNet.

Ausführen:  python -m pytest -q test_stimme_schatten.py   (im Ordner voice-core/)

Modelle und Datenbank sind Ersatz. Der letzte Block braucht die echte Datei des Schattenmodells im Cache-Ordner und wird sonst übersprungen.
"""

import asyncio
import hashlib
import re
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import asyncpg
import numpy as np

import memory as m
import stimme_modell as sm
import stimme_schatten as sch
import stimme_sitzung
import stimme_speicher as ss
from auth_gate import Identity
from stimme_einlernen import ZIEL_SECS, Einlernen
from stimme_gate import EIGEN, KURZ, StimmGate
from stimme_modell import DIM, als_vektor, kosinus
from stimme_pruefer import Stimmpruefer

RATE = 16000
USER_A = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
EIGENER = np.eye(DIM, dtype=np.float32)[0]
SCHATTEN = sm.normalisieren(np.arange(1, sch.SCHATTEN_DIM + 1, dtype=np.float32))
ZEILE_RE = re.compile(r"Stimmschatten: titanet=-?\d+\.\d{3} schatten=-?\d+\.\d{3} secs=\d+\.\d{2} wamo=[01] urteil=(eigen|fremd|unklar|kurz) "
                      r"ms_titanet=\d+ ms_schatten=\d+")


class Uhr:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Rechner:
    """Ersatz für den Embedder. wert: fester Abdruck. dauer: so lange blockiert embed (im Thread). fehler: embed wirft."""

    def __init__(self, wert: np.ndarray, dauer: float = 0.0, fehler: Exception | None = None):
        self.wert = wert
        self.dauer = dauer
        self.fehler = fehler
        self.aufrufe = 0

    def embed(self, pcm: bytes, rate: int) -> np.ndarray:
        self.aufrufe += 1
        if self.dauer:
            time.sleep(self.dauer)
        if self.fehler:
            raise self.fehler
        return self.wert


class Modell:
    def __init__(self, rechner: Rechner | None, bereit: bool = True):
        self.rechner = rechner
        self.bereit = bereit
        self.gescheitert = False
        self.gewaermt = 0

    async def get(self):
        return self.rechner if self.bereit else None

    def vorwaermen(self) -> None:
        self.gewaermt += 1


def audio(wert: int, secs: float = 0.02):
    from pipecat.frames.frames import InputAudioRawFrame

    return InputAudioRawFrame(audio=np.full(int(RATE * secs), wert, dtype=np.int16).tobytes(), sample_rate=RATE, num_channels=1)


def zeilen(info) -> list[str]:
    """Die Logzeilen des Schattens, formatiert wie loguru sie schreibt."""
    return [c.args[0].format(*c.args[1:]) for c in info.call_args_list if c.args and str(c.args[0]).startswith("Stimmschatten: titanet")]


# ---------------------------------------------------------------------------------------------------------- Schalter und Konstanten


class SchalterTests(unittest.TestCase):
    def test_standard_aus_und_nur_an_schaltet_ein(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertFalse(sch.schatten_an(""))
        self.assertTrue(sch.schatten_an("an"))
        self.assertFalse(sch.schatten_an("aus"))
        self.assertFalse(sch.schatten_an("anm"))  # ein Tippfehler bleibt aus

    def test_name_des_schalters(self):
        self.assertEqual(sch.SCHALTER, "WAMO_STIMME_SCHATTEN")
        with mock.patch.dict("os.environ", {"WAMO_STIMME_SCHATTEN": "an"}):
            self.assertTrue(sch.schatten_an())


class KonstantenTests(unittest.TestCase):
    def test_modell_aus_dem_release_von_sherpa_onnx_mit_summen(self):
        self.assertEqual(sch.SCHATTEN_NAME, "wespeaker_en_voxceleb_resnet34.onnx")
        self.assertEqual(sch.SCHATTEN_URL, "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
                                           "wespeaker_en_voxceleb_resnet34.onnx")
        self.assertEqual(sch.SCHATTEN_SHA256, "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94")
        self.assertEqual(sch.SCHATTEN_SHA256_CMN, "6928c40c3b5c695352998c261cb6f2250c4e52a991e324c0f63c2e10fe7c31f8")
        self.assertEqual(sch.SCHATTEN_DIM, 256)
        self.assertNotEqual(sch.SCHATTEN_DATEI, sch.SCHATTEN_NAME)
        self.assertRegex(sch.SCHATTEN_MODELL, r"^[a-z0-9][a-z0-9_.+-]{0,59}$")  # passt zur Prüfung in Migration 0028

    def test_zusatz_ist_genau_ein_metadateneintrag_fuer_die_mittelwertbereinigung(self):
        """ModelProto.metadata_props ist Feld 14 (Tag 0x72), darin key (0x0a) und value (0x12). Angehängt an eine Datei ist das ein weiterer
        Eintrag: sherpa-onnx liest feature_normalize_type=global-mean und zieht je Äußerung den Mittelwert der Merkmale ab (CMN)."""
        self.assertEqual(sch.CMN_ZUSATZ.hex(), "72250a16666561747572655f6e6f726d616c697a655f74797065120b676c6f62616c2d6d65616e")
        self.assertEqual(sch.metadaten_eintrag("feature_normalize_type", "global-mean"), sch.CMN_ZUSATZ)


class AbleitenTests(unittest.TestCase):
    def test_haengt_den_zusatz_an_und_prueft_die_summe(self):
        with tempfile.TemporaryDirectory() as tmp:
            roh, fertig = Path(tmp) / "roh.onnx", Path(tmp) / "fertig.onnx"
            roh.write_bytes(b"modell")
            soll = hashlib.sha256(b"modell" + sch.CMN_ZUSATZ).hexdigest()
            sch.ableiten(roh, fertig, soll)
            self.assertEqual(fertig.read_bytes(), b"modell" + sch.CMN_ZUSATZ)
            self.assertEqual(roh.read_bytes(), b"modell")  # die Datei aus dem Release bleibt unverändert
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["fertig.onnx", "roh.onnx"])

    def test_falsche_summe_hinterlaesst_nichts(self):
        with tempfile.TemporaryDirectory() as tmp:
            roh, fertig = Path(tmp) / "roh.onnx", Path(tmp) / "fertig.onnx"
            roh.write_bytes(b"modell")
            with self.assertRaises(ValueError):
                sch.ableiten(roh, fertig, "0" * 64)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["roh.onnx"])


# ---------------------------------------------------------------------------------------------------------- Laden


class LadenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self.tmp.name)
        self.roh_inhalt = b"roh"
        self.zeit = [100.0]
        self.cache = mock.patch("stimme_modell.cache_ordner", return_value=self.ordner)
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.tmp.cleanup()

    def modell(self) -> sch.SchattenModell:
        return sch.SchattenModell(self.ordner, roh_sha256=hashlib.sha256(self.roh_inhalt).hexdigest(),
                                  sha256=hashlib.sha256(self.roh_inhalt + sch.CMN_ZUSATZ).hexdigest(), uhr=lambda: self.zeit[0])

    async def test_ohne_dateien_wird_die_datei_des_releases_geladen_und_abgeleitet(self):
        async def laden(pfad, url, sha256):
            self.assertEqual((pfad.name, url), (sch.SCHATTEN_NAME, sch.SCHATTEN_URL))
            self.assertEqual(sha256, hashlib.sha256(self.roh_inhalt).hexdigest())
            pfad.write_bytes(self.roh_inhalt)

        modell = self.modell()
        with mock.patch("stimme_modell.herunterladen", side_effect=laden) as geladen, \
                mock.patch("stimme_modell.Embedder", return_value="rechner") as klasse:
            self.assertEqual(await modell.get(), "rechner")
        geladen.assert_awaited_once()
        self.assertTrue(modell.bereit)
        pfad = klasse.call_args.args[0]
        self.assertEqual(pfad, self.ordner / sch.SCHATTEN_DATEI)
        self.assertEqual(klasse.call_args.kwargs["dim"], sch.SCHATTEN_DIM)
        self.assertEqual(pfad.read_bytes(), self.roh_inhalt + sch.CMN_ZUSATZ)

    async def test_vorhandene_abgeleitete_datei_wird_nur_geprueft(self):
        (self.ordner / sch.SCHATTEN_DATEI).write_bytes(self.roh_inhalt + sch.CMN_ZUSATZ)
        with mock.patch("stimme_modell.herunterladen", mock.AsyncMock()) as geladen, \
                mock.patch("stimme_modell.Embedder", return_value="rechner"):
            self.assertEqual(await self.modell().get(), "rechner")
        geladen.assert_not_awaited()

    async def test_vorab_abgelegte_datei_des_releases_genuegt(self):
        """So legt der Betreiber das Modell am Server ab: nur die Datei aus dem Release, der Kern leitet die zweite selbst ab."""
        (self.ordner / sch.SCHATTEN_NAME).write_bytes(self.roh_inhalt)
        with mock.patch("stimme_modell.herunterladen", mock.AsyncMock()) as geladen, \
                mock.patch("stimme_modell.Embedder", return_value="rechner"):
            self.assertEqual(await self.modell().get(), "rechner")
        geladen.assert_not_awaited()
        self.assertTrue((self.ordner / sch.SCHATTEN_DATEI).is_file())

    async def test_falsche_datei_ist_nur_ein_hinweis_und_wird_geloescht(self):
        (self.ordner / sch.SCHATTEN_NAME).write_bytes(b"ausgetauscht")
        modell = self.modell()
        with mock.patch.object(sch.logger, "info") as info, mock.patch.object(sm.logger, "warning") as warnung, \
                mock.patch("stimme_modell.herunterladen", mock.AsyncMock()) as geladen:
            self.assertIsNone(await modell.get())
            self.assertIsNone(await modell.get())  # gleich danach kein neuer Versuch
        geladen.assert_not_awaited()
        warnung.assert_not_called()
        self.assertFalse((self.ordner / sch.SCHATTEN_NAME).exists())
        self.assertFalse(modell.bereit)
        (hinweis,) = [c.args[0] for c in info.call_args_list]
        self.assertIn("TitaNet", hinweis)

    async def test_falsche_abgeleitete_datei_wird_geloescht_und_spaeter_neu_abgeleitet(self):
        (self.ordner / sch.SCHATTEN_DATEI).write_bytes(b"kaputt")
        (self.ordner / sch.SCHATTEN_NAME).write_bytes(self.roh_inhalt)
        modell = self.modell()
        with mock.patch("stimme_modell.Embedder", return_value="rechner"):
            self.assertIsNone(await modell.get())
            self.assertFalse((self.ordner / sch.SCHATTEN_DATEI).exists())
            self.zeit[0] += sm.NEUER_VERSUCH_SECS + 1
            self.assertEqual(await modell.get(), "rechner")

    async def test_fehler_beim_bauen_wirft_nie(self):
        (self.ordner / sch.SCHATTEN_DATEI).write_bytes(self.roh_inhalt + sch.CMN_ZUSATZ)
        with mock.patch("stimme_modell.Embedder", side_effect=ValueError("Modell liefert 192 statt 256 Werte")):
            self.assertIsNone(await self.modell().get())

    async def test_vorwaermen_laedt_einmal_im_hintergrund(self):
        (self.ordner / sch.SCHATTEN_DATEI).write_bytes(self.roh_inhalt + sch.CMN_ZUSATZ)
        modell = self.modell()
        with mock.patch("stimme_modell.Embedder", return_value="rechner") as klasse:
            modell.vorwaermen()
            modell.vorwaermen()
            await modell.warten()
            modell.vorwaermen()
        self.assertTrue(modell.bereit)
        klasse.assert_called_once()

    def test_vorwaermen_ohne_ereignisschleife_tut_nichts(self):
        self.modell().vorwaermen()


# ---------------------------------------------------------------------------------------------------------- Gate


class GateTests(unittest.TestCase):
    def test_schatten_gehoert_zum_abdruck(self):
        gate = StimmGate(modus="streng")
        gate.setze_abdruck(EIGENER, schatten=SCHATTEN)
        self.assertIs(gate.schatten_abdruck, SCHATTEN)
        gate.setze_abdruck(EIGENER)
        self.assertIsNone(gate.schatten_abdruck)  # neu eingelernt ohne Schatten: der alte gilt nicht
        gate.setze_abdruck(None, schatten=SCHATTEN)
        self.assertIsNone(gate.schatten_abdruck)
        gate.setze_abdruck(EIGENER, ok=False, schatten=SCHATTEN)
        self.assertIsNone(gate.schatten_abdruck)


# ---------------------------------------------------------------------------------------------------------- Prüfen


class PruefenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uhr = Uhr()
        self.gate = StimmGate(modus="streng", uhr=self.uhr)
        self.gate.setze_abdruck(EIGENER, schatten=SCHATTEN)
        self.gate.modell_ok = True
        self.titanet = Rechner(EIGENER)
        self.schatten_rechner = Rechner(sm.normalisieren(SCHATTEN + 0.5 * np.eye(sch.SCHATTEN_DIM, dtype=np.float32)[0]))
        self.schatten = Modell(self.schatten_rechner)
        self.v = self.pruefer(self.schatten)

    def pruefer(self, schatten) -> Stimmpruefer:
        v = Stimmpruefer(self.gate, Modell(self.titanet), speichern=mock.AsyncMock(return_value=True), sagen=mock.AsyncMock(),
                         uhr=self.uhr, schatten=schatten)
        v.push_frame = mock.AsyncMock()
        return v

    async def sprechen(self, secs: float, wert: int = 8000):
        self.v.on_speech_start(self.uhr.t + 0.2, 0.2)
        for _ in range(int(secs / 0.02)):
            self.uhr.t += 0.02
            await self.v.on_audio(audio(wert))
        for _ in range(10):
            self.uhr.t += 0.02
            await self.v.on_audio(audio(0))
        self.v.on_speech_stop(self.uhr.t, 0.2)

    async def test_eine_zeile_je_aeusserung_nur_mit_zahlen(self):
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            urteil = await self.v.urteil_abwarten(5.0)
            await self.v.schatten_warten()
        (zeile,) = zeilen(info)
        self.assertRegex(zeile, ZEILE_RE)
        self.assertIn(f"titanet={urteil.wert:.3f}", zeile)
        soll = kosinus(self.schatten_rechner.wert, SCHATTEN)
        self.assertIn(f"schatten={soll:.3f}", zeile)
        self.assertIn(f"secs={urteil.secs:.2f}", zeile)
        self.assertIn("wamo=0", zeile)
        self.assertIn(f"urteil={urteil.urteil}", zeile)
        self.assertEqual(self.schatten_rechner.aufrufe, 1)

    async def test_das_urteil_wartet_nie_auf_den_schatten(self):
        self.schatten_rechner.dauer = 1.0
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            start = time.perf_counter()
            urteil = await self.v.urteil_abwarten(5.0)
            dauer = time.perf_counter() - start
            self.assertIsNotNone(urteil)
            self.assertLess(dauer, 0.7)  # TitaNet rechnet ohne Pause, der Schatten braucht 1 s
            self.assertEqual(zeilen(info), [])  # der Schatten rechnet noch
            await self.v.schatten_warten()
        (zeile,) = zeilen(info)
        self.assertGreaterEqual(int(re.search(r"ms_schatten=(\d+)", zeile).group(1)), 950)

    async def test_ueberlappung_steht_in_der_zeile(self):
        with mock.patch.object(sch.logger, "info") as info:
            self.v.on_bot_speaking(True)
            await self.sprechen(1.4)
            await self.v.urteil_abwarten(5.0)
            await self.v.schatten_warten()
        self.assertIn("wamo=1", zeilen(info)[0])

    async def test_kurze_aeusserung_mit_urteil_kurz(self):
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(0.6)
            urteil = await self.v.urteil_abwarten(5.0)
            await self.v.schatten_warten()
        self.assertEqual(urteil.urteil, KURZ)
        self.assertIn("urteil=kurz", zeilen(info)[0])

    async def test_ohne_schatten_abdruck_rechnet_der_schatten_nicht(self):
        self.gate.setze_abdruck(EIGENER)
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            self.assertEqual((await self.v.urteil_abwarten(5.0)).urteil, EIGEN)
            await self.v.schatten_warten()
        self.assertEqual(zeilen(info), [])
        self.assertEqual(self.schatten_rechner.aufrufe, 0)

    async def test_ohne_schattenmodell_wie_bisher(self):
        self.v = self.pruefer(None)
        await self.sprechen(1.4)
        self.assertEqual((await self.v.urteil_abwarten(5.0)).urteil, EIGEN)
        await self.v.schatten_warten()
        self.assertEqual(self.schatten_rechner.aufrufe, 0)

    async def test_schattenmodell_nicht_verfuegbar_aendert_nichts_und_wird_vorgewaermt(self):
        self.schatten.bereit = False
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            self.assertEqual((await self.v.urteil_abwarten(5.0)).urteil, EIGEN)
            await self.v.schatten_warten()
        self.assertEqual(zeilen(info), [])
        self.assertEqual(self.schatten.gewaermt, 1)  # geladen wird im Hintergrund, nie in der Aufgabe des Schattens
        self.assertEqual(self.v._schatten.uebersprungen, 0)

    async def test_fehler_im_schatten_aendert_das_urteil_nicht(self):
        self.schatten_rechner.fehler = RuntimeError("kaputt")
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            self.assertEqual((await self.v.urteil_abwarten(5.0)).urteil, EIGEN)
            await self.v.schatten_warten()
        self.assertEqual(zeilen(info), [])
        self.assertEqual(self.gate._wer, EIGEN)

    async def test_fehlgeschlagene_pruefung_ohne_wert_rechnet_keinen_schatten(self):
        self.titanet.fehler = RuntimeError("kaputt")
        await self.sprechen(1.4)
        urteil = await self.v.urteil_abwarten(5.0)
        await self.v.schatten_warten()
        self.assertIsNone(urteil.wert)
        self.assertEqual(self.schatten_rechner.aufrufe, 0)

    async def test_laeuft_der_schatten_noch_wird_die_naechste_aeusserung_uebersprungen(self):
        self.schatten_rechner.dauer = 0.3
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            await self.v.urteil_abwarten(5.0)
            self.uhr.t += 4.0  # neuer Zug
            await self.sprechen(1.4)
            await self.v.urteil_abwarten(5.0)
            await self.v.schatten_warten()
        self.assertEqual(len(zeilen(info)), 1)
        self.assertEqual(self.v._schatten.uebersprungen, 1)

    async def test_aufraeumen_bricht_den_schatten_ab(self):
        self.schatten_rechner.dauer = 0.3
        await self.sprechen(1.4)
        await self.v.urteil_abwarten(5.0)
        await asyncio.sleep(0.05)
        with mock.patch.object(sch.logger, "info") as info:
            await self.v.cleanup()
            await asyncio.sleep(0.4)
        self.assertEqual(zeilen(info), [])

    async def test_nach_dem_aufraeumen_beginnt_kein_schatten_mehr(self):
        """Eine Prüfung, die beim Aufräumen noch zu Ende läuft, startet keinen Schatten mehr, der die Sitzung überdauert."""
        await self.v.cleanup()
        self.v._schatten.starten(bytes([1, 0]) * 1000, RATE, 1.2, False, EIGEN, 0.6, 10.0)
        self.assertIsNone(self.v._schatten._task)
        self.assertEqual(self.schatten_rechner.aufrufe, 0)

    async def test_geloeschter_abdruck_waehrend_des_rechnens_schreibt_nichts(self):
        self.schatten_rechner.dauer = 0.2
        with mock.patch.object(sch.logger, "info") as info:
            await self.sprechen(1.4)
            await self.v.urteil_abwarten(5.0)
            self.gate.setze_abdruck(None, geloescht=True)
            await self.v.schatten_warten()
        self.assertEqual(zeilen(info), [])


# ---------------------------------------------------------------------------------------------------------- Einlernen


class EinlernenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uhr = Uhr()
        self.gate = StimmGate(modus="streng", uhr=self.uhr)
        self.gate.setze_abdruck(None)
        self.speichern = mock.AsyncMock(return_value=True)
        self.schatten_rechner = Rechner(SCHATTEN)

    def einlernen(self, schatten) -> Einlernen:
        return Einlernen(self.gate, Modell(Rechner(EIGENER)), senden=mock.AsyncMock(), sagen=mock.AsyncMock(), speichern=self.speichern,
                         uhr=self.uhr, schatten=schatten)

    async def durchlaufen(self, e: Einlernen):
        await e.starten("stimme-1", datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc))
        e.bot_spricht(True)
        e.bot_spricht(False)
        for _ in range(int((ZIEL_SECS + 1) / 0.02)):
            self.uhr.t += 0.02
            await e.sammeln(np.full(int(RATE * 0.02), 8000, dtype=np.int16).tobytes(), RATE)
        await e.warten()

    async def test_schatten_abdruck_aus_denselben_stuecken(self):
        modell = Modell(self.schatten_rechner)
        with mock.patch.object(sch.logger, "info") as info:
            await self.durchlaufen(self.einlernen(modell))
        self.speichern.assert_awaited_once()
        schatten = self.speichern.call_args.kwargs["schatten"]
        self.assertEqual(schatten.shape, (sch.SCHATTEN_DIM,))
        self.assertAlmostEqual(kosinus(schatten, SCHATTEN), 1.0, places=5)
        self.assertGreaterEqual(self.schatten_rechner.aufrufe, 8)  # je Stück einmal, wie TitaNet
        self.assertIs(self.gate.schatten_abdruck, schatten)
        self.assertTrue(any("Stücke" in c.args[0] for c in info.call_args_list))

    async def test_ohne_schattenmodell_kein_schatten(self):
        await self.durchlaufen(self.einlernen(None))
        self.assertIsNone(self.speichern.call_args.kwargs["schatten"])
        self.assertIsNone(self.gate.schatten_abdruck)
        self.assertIsNotNone(self.gate.abdruck)

    async def test_noch_nicht_geladenes_schattenmodell_wird_vorgewaermt_und_fehlt_diesmal(self):
        modell = Modell(self.schatten_rechner, bereit=False)
        await self.durchlaufen(self.einlernen(modell))
        self.assertGreaterEqual(modell.gewaermt, 1)
        self.assertIsNone(self.speichern.call_args.kwargs["schatten"])
        self.assertIsNotNone(self.gate.abdruck)

    async def test_haengender_schatten_haelt_das_einlernen_nicht_auf(self):
        self.schatten_rechner.dauer = 0.05  # je Stück, zusammen weit über der Frist
        with mock.patch("stimme_einlernen.SCHATTEN_SECS", 0.1):
            await self.durchlaufen(self.einlernen(Modell(self.schatten_rechner)))
        self.speichern.assert_awaited_once()
        self.assertIsNone(self.speichern.call_args.kwargs["schatten"])
        self.assertIsNotNone(self.gate.abdruck)

    async def test_fehler_im_schatten_laesst_das_einlernen_gelingen(self):
        self.schatten_rechner.fehler = RuntimeError("kaputt")
        await self.durchlaufen(self.einlernen(Modell(self.schatten_rechner)))
        self.speichern.assert_awaited_once()
        self.assertIsNone(self.speichern.call_args.kwargs["schatten"])
        self.assertIsNotNone(self.gate.abdruck)


# ---------------------------------------------------------------------------------------------------------- Speichern und Laden


class SchattenDb:
    """speakers mit den Spalten der Migration 0028. ohne_0028: die Spalten fehlen."""

    configured = True
    schema = "wamo_test"

    def __init__(self, zeile: dict | None = None, ohne_0028: bool = False, fehler: Exception | None = None):
        self.zeile = zeile
        self.ohne_0028 = ohne_0028
        self.fehler = fehler
        self.calls: list[tuple] = []

    def t(self, name):
        return f"wamo_test.{name}"

    def _pruefen(self, sql):
        if self.fehler:
            raise self.fehler
        if self.ohne_0028 and "voiceprint_shadow" in sql:
            raise asyncpg.UndefinedColumnError('column "voiceprint_shadow" does not exist')

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        self._pruefen(sql)
        return self.zeile

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        self._pruefen(sql)
        return "UPDATE 1" if sql.startswith("update") else "INSERT 0 1"


def speicher(db) -> m.MemoryStore:
    return m.MemoryStore(USER_A, db)


class SpeicherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ss._GEMELDET.clear()
        self.am = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)

    async def test_laedt_den_schatten_nur_mit_passendem_modell(self):
        db = SchattenDb({"schatten": als_vektor(SCHATTEN), "modell": sch.SCHATTEN_MODELL})
        schatten = await ss.schatten_laden(speicher(db), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM)
        self.assertAlmostEqual(kosinus(schatten, SCHATTEN), 1.0, places=5)
        _, sql, args = db.calls[0]
        for teil in ("voiceprint_shadow", "shadow_model", "wamo_test.speakers", "is_owner", "voiceprint is not null"):
            self.assertIn(teil, sql)
        self.assertEqual(args, (USER_A,))

    async def test_anderes_modell_falsche_laenge_oder_keiner_ergibt_keinen(self):
        for zeile in ({"schatten": als_vektor(SCHATTEN), "modell": "anderes-modell"}, {"schatten": als_vektor(EIGENER), "modell": sch.SCHATTEN_MODELL},
                      {"schatten": None, "modell": None}, None):
            self.assertIsNone(await ss.schatten_laden(speicher(SchattenDb(zeile)), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM), zeile)

    async def test_ohne_migration_0028_kein_schatten_und_ein_hinweis(self):
        db = SchattenDb(ohne_0028=True)
        with mock.patch.object(ss.logger, "warning") as warnung:
            self.assertIsNone(await ss.schatten_laden(speicher(db), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM))
            self.assertIsNone(await ss.schatten_laden(speicher(db), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM))
        self.assertEqual(warnung.call_count, 1)
        self.assertIn("0028", warnung.call_args.args[0])

    async def test_datenbankfehler_oder_ohne_datenbank_kein_schatten(self):
        self.assertIsNone(await ss.schatten_laden(speicher(SchattenDb(fehler=asyncpg.PostgresError("x"))), sch.SCHATTEN_MODELL,
                                                  sch.SCHATTEN_DIM))
        self.assertIsNone(await ss.schatten_laden(m.MemoryStore(USER_A, None), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM))

    async def test_speichert_den_schatten_nach_dem_abdruck(self):
        db = SchattenDb()
        ok = await ss.abdruck_speichern(speicher(db), EIGENER, version="stimme-1", name="E", einwilligung_am=self.am, schwelle=0.33,
                                        schatten=SCHATTEN, schatten_modell=sch.SCHATTEN_MODELL)
        self.assertTrue(ok)
        self.assertEqual(len(db.calls), 2)
        _, sql, args = db.calls[1]
        self.assertTrue(sql.startswith("update wamo_test.speakers set voiceprint_shadow"))
        for teil in ("shadow_model", "is_owner", "voiceprint is not null", "extensions.vector"):
            self.assertIn(teil, sql)
        self.assertEqual(args, (USER_A, als_vektor(SCHATTEN), sch.SCHATTEN_MODELL))

    async def test_ohne_schatten_nur_der_abdruck(self):
        """Den alten Schatten eines früheren Abdrucks verwirft die Datenbank selbst (Trigger in Migration 0028)."""
        db = SchattenDb()
        self.assertTrue(await ss.abdruck_speichern(speicher(db), EIGENER, version="stimme-1", name="E", einwilligung_am=self.am))
        self.assertEqual(len(db.calls), 1)
        self.assertNotIn("voiceprint_shadow", db.calls[0][1])

    async def test_ohne_migration_0028_bleibt_der_abdruck_gespeichert(self):
        db = SchattenDb(ohne_0028=True)
        with mock.patch.object(ss.logger, "warning") as warnung:
            ok = await ss.abdruck_speichern(speicher(db), EIGENER, version="stimme-1", name="E", einwilligung_am=self.am,
                                            schatten=SCHATTEN, schatten_modell=sch.SCHATTEN_MODELL)
        self.assertTrue(ok)
        self.assertEqual(warnung.call_count, 1)

    async def test_misslungener_abdruck_speichert_keinen_schatten(self):
        db = SchattenDb(fehler=asyncpg.PostgresError("x"))
        self.assertFalse(await ss.abdruck_speichern(speicher(db), EIGENER, version="stimme-1", name="E", einwilligung_am=self.am,
                                                    schatten=SCHATTEN, schatten_modell=sch.SCHATTEN_MODELL))
        self.assertEqual(len(db.calls), 1)


# ---------------------------------------------------------------------------------------------------------- Sitzung


class SitzungTests(unittest.IsolatedAsyncioTestCase):
    def identity(self, **kw) -> Identity:
        return Identity(USER_A, "Erika", "mitglied", "du", **kw)

    def test_schalter_an_gibt_der_sitzung_das_schattenmodell(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_SCHATTEN": "an"}):
            s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                                 modell=Modell(Rechner(EIGENER)))
        self.assertIs(s.schatten, sch.SCHATTEN)
        with mock.patch.dict("os.environ", {"WAMO_STIMME_SCHATTEN": ""}):
            s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                                 modell=Modell(Rechner(EIGENER)))
        self.assertIsNone(s.schatten)

    def test_laborprofile_bleiben_ohne_stimmprufung(self):
        with mock.patch.dict("os.environ", {"WAMO_STIMME_SCHATTEN": "an"}):
            s = stimme_sitzung.StimmSitzung.fuer(self.identity(labor_art="platz", labor_platz=2, labor_aktiv=True), speicher(SchattenDb()),
                                                 senden=mock.AsyncMock(), sagen=mock.AsyncMock())
        self.assertIsNone(s)

    async def test_laden_holt_den_schatten_abdruck_und_waermt_das_modell(self):
        schatten = Modell(Rechner(SCHATTEN), bereit=False)
        s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                             modell=Modell(Rechner(EIGENER)), gate=StimmGate(modus="streng"), schatten=schatten)
        with mock.patch("stimme_sitzung.abdruck_mit_schwelle_laden", mock.AsyncMock(return_value=(True, EIGENER, None))), \
                mock.patch("stimme_sitzung.schatten_laden", mock.AsyncMock(return_value=SCHATTEN)) as laden:
            await s.vorbereiten()
        laden.assert_awaited_once()
        self.assertEqual(laden.call_args.args[1:], (sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM))
        self.assertIs(s.gate.schatten_abdruck, SCHATTEN)
        self.assertEqual(schatten.gewaermt, 1)

    async def test_der_abdruck_von_titanet_wartet_nicht_auf_den_schatten(self):
        gelesen = asyncio.Event()

        async def langsam(*_a):
            gelesen.set()
            await asyncio.sleep(10)

        s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                             modell=Modell(Rechner(EIGENER)), gate=StimmGate(modus="streng"), schatten=Modell(Rechner(SCHATTEN)))
        with mock.patch("stimme_sitzung.abdruck_mit_schwelle_laden", mock.AsyncMock(return_value=(True, EIGENER, None))),                 mock.patch("stimme_sitzung.schatten_laden", side_effect=langsam), mock.patch("stimme_sitzung.SCHATTEN_LADEN_SECS", 0.1):
            vorbereiten = asyncio.create_task(s.vorbereiten())
            await gelesen.wait()
            self.assertIs(s.gate.abdruck, EIGENER)  # schon gesetzt, während der Schatten noch gelesen wird
            await vorbereiten
        self.assertIsNone(s.gate.schatten_abdruck)
        self.assertEqual(s.gate.zustand, "da")

    async def test_ohne_schalter_wird_kein_schatten_gelesen(self):
        s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                             modell=Modell(Rechner(EIGENER)), gate=StimmGate(modus="streng"))
        with mock.patch("stimme_sitzung.abdruck_mit_schwelle_laden", mock.AsyncMock(return_value=(True, EIGENER, None))), \
                mock.patch("stimme_sitzung.schatten_laden", mock.AsyncMock()) as laden:
            await s.vorbereiten()
        laden.assert_not_awaited()
        self.assertIsNone(s.gate.schatten_abdruck)

    async def test_speichern_der_sitzung_gibt_den_schatten_weiter(self):
        s = stimme_sitzung.StimmSitzung.fuer(self.identity(), speicher(SchattenDb()), senden=mock.AsyncMock(), sagen=mock.AsyncMock(),
                                             modell=Modell(Rechner(EIGENER)), schatten=Modell(Rechner(SCHATTEN)))
        with mock.patch("stimme_sitzung.abdruck_speichern", mock.AsyncMock(return_value=True)) as speichern:
            await s._speichern(EIGENER, "stimme-1", datetime.now(timezone.utc), schwelle=0.33, schatten=SCHATTEN)
        self.assertIs(speichern.call_args.kwargs["schatten"], SCHATTEN)
        self.assertEqual(speichern.call_args.kwargs["schatten_modell"], sch.SCHATTEN_MODELL)


# ---------------------------------------------------------------------------------------------------------- Echtes Modell (optional)


@unittest.skipUnless((sm.cache_ordner() / sch.SCHATTEN_DATEI).is_file() or (sm.cache_ordner() / sch.SCHATTEN_NAME).is_file(),
                     "Schattenmodell fehlt im Cache-Ordner (.cache/sprecher/)")
class EchtesModellTests(unittest.IsolatedAsyncioTestCase):
    async def test_laedt_und_rechnet_256_werte_stabil_ueber_die_laenge(self):
        rechner = await sch.SchattenModell().get()
        self.assertIsNotNone(rechner)
        rng = np.random.default_rng(3)
        ton = (rng.normal(size=4 * RATE) * 3000).astype(np.int16).tobytes()
        voll = rechner.embed(ton, RATE)
        self.assertEqual(voll.shape, (sch.SCHATTEN_DIM,))
        start = time.perf_counter()
        teil = rechner.embed(ton[: 2 * RATE * 2], RATE)
        self.assertLess(time.perf_counter() - start, 0.5)
        self.assertTrue(np.isfinite(kosinus(voll, teil)))


if __name__ == "__main__":
    unittest.main()
