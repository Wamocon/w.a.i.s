"""Tests für stimme_modell.py: Rechenwege rund um den Stimmabdruck, Laden und Prüfsumme des Modells.

Ausführen:  python -m pytest -q test_stimme_modell.py   (im Ordner voice-core/)

Der letzte Block braucht das echte Modell (Ordner .cache/sprecher/ oder WAMO_STIMME_MODELL) und wird sonst übersprungen.
"""

import asyncio
import hashlib
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
import numpy as np

import stimme_modell as sm
from stimme_modell import (
    DIM,
    Embedder,
    NEUER_VERSUCH_SECS,
    StimmModell,
    als_vektor,
    aus_vektor,
    einlern_stuecke,
    kosinus,
    mittelpunkt,
    modell_pfad,
    normalisieren,
    ohne_pausen,
    schwelle_einlernen,
)

RATE = 16000


def ton(secs: float, amplitude: int = 8000) -> bytes:
    t = np.arange(int(RATE * secs)) / RATE
    return (np.sin(2 * np.pi * 220 * t) * amplitude).astype(np.int16).tobytes()


def stille(secs: float) -> bytes:
    return bytes(int(RATE * secs) * 2)


class VektorTests(unittest.TestCase):
    def test_hin_und_zurueck_ueber_die_datenbank(self):
        v = normalisieren(np.random.default_rng(1).normal(size=DIM).astype(np.float32))
        zurueck = aus_vektor(als_vektor(v))
        self.assertIsNotNone(zurueck)
        self.assertAlmostEqual(kosinus(v, zurueck), 1.0, places=5)

    def test_liste_wird_auch_gelesen(self):
        self.assertIsNotNone(aus_vektor([0.1] * DIM))

    def test_falsche_laenge_oder_unbrauchbares_wird_abgelehnt(self):
        for wert in ("[0.1,0.2]", None, 5, "", "[a,b]", [float("nan")] * DIM):
            with self.subTest(wert=wert):
                self.assertIsNone(aus_vektor(wert))

    def test_nullvektor_ist_kein_abdruck(self):
        self.assertIsNone(aus_vektor([0.0] * DIM))

    def test_mittelwert_ist_normiert_und_misst_die_streuung(self):
        a = np.zeros(DIM, dtype=np.float32)
        a[0] = 1
        mitte, streuung = mittelpunkt([a, a, a])
        self.assertAlmostEqual(float(np.linalg.norm(mitte)), 1.0, places=5)
        self.assertAlmostEqual(streuung, 1.0, places=5)
        b = np.zeros(DIM, dtype=np.float32)
        b[1] = 1
        self.assertLess(mittelpunkt([a, b])[1], 0.8)


def secs(pcm: bytes) -> float:
    return len(pcm) / 2 / RATE


class AudioTests(unittest.TestCase):
    """Einlernen passend zum Prüfen (17.11.2026): kein Schnitt in 20-ms-Blöcke mehr, nur Pausen über PAUSE_SECS fallen weg, wie in einer
    Äußerung, die der Prüfer anhand der Sprachpausenerkennung ausschneidet."""

    def test_lange_pausen_fallen_weg(self):
        self.assertEqual(sm.PAUSE_SECS, 0.3)
        self.assertAlmostEqual(secs(ohne_pausen(ton(1.0) + stille(2.0) + ton(1.0), RATE)), 2.0, places=2)
        self.assertAlmostEqual(secs(ohne_pausen(ton(1.0) + stille(0.32) + ton(1.0), RATE)), 2.0, places=2)

    def test_kurze_pausen_und_raender_bleiben(self):
        self.assertAlmostEqual(secs(ohne_pausen(ton(1.0) + stille(0.2) + ton(1.0), RATE)), 2.2, places=2)
        self.assertAlmostEqual(secs(ohne_pausen(stille(0.24) + ton(1.0) + stille(0.1), RATE)), 1.34, places=2)

    def test_leise_sprache_wird_nicht_zerschnitten(self):
        """Ein leiser Block mitten im Wort (unter -45 dBFS, kürzer als eine Pause) bleibt: der Ton ist derselbe wie beim Prüfen."""
        pcm = ton(0.5) + ton(0.1, amplitude=100) + ton(0.5)
        self.assertEqual(ohne_pausen(pcm, RATE), pcm)

    def test_nur_stille_ergibt_nichts(self):
        self.assertEqual(ohne_pausen(stille(1.0), RATE), b"")
        self.assertEqual(ohne_pausen(b"", RATE), b"")

    def test_stuecke_von_anderthalb_sekunden_rest_faellt_weg(self):
        self.assertEqual(sm.STUECK_SECS, 1.5)
        stuecke = einlern_stuecke(ton(10.0), RATE)
        self.assertEqual(len(stuecke), 6)
        self.assertTrue(all(len(s) == int(RATE * 1.5) * 2 for s in stuecke))

    def test_zwanzig_sekunden_sprache_ergeben_genug_stuecke(self):
        pcm = b"".join(ton(2.0) + stille(0.6) for _ in range(10))  # 20 s Sprache mit Pausen zwischen den Sätzen
        stuecke = einlern_stuecke(ohne_pausen(pcm, RATE), RATE)
        self.assertEqual(len(stuecke), 13)
        self.assertGreaterEqual(len(stuecke), sm.MIN_STUECKE)
        self.assertLessEqual(sm.MIN_STUECKE, 10)
        self.assertGreaterEqual(sm.MIN_STUECKE, 6)


def streuende(n: int, abstand: float, seed: int = 3) -> list[np.ndarray]:
    """n Abdrücke um eine gemeinsame Richtung, je weiter abstand, desto unähnlicher."""
    rng = np.random.default_rng(seed)
    basis = normalisieren(rng.normal(size=DIM))
    return [normalisieren(basis + abstand * normalisieren(rng.normal(size=DIM))) for _ in range(n)]


class PersoenlicheSchwelleTests(unittest.TestCase):
    """Beim Einlernen: je Stück der Kosinus gegen den Mittelpunkt der übrigen Stücke (leave-one-out), davon das 10-%-Quantil minus 0,03,
    begrenzt auf 0,30 bis 0,50."""

    def test_feste_werte(self):
        self.assertEqual((sm.SCHWELLE_QUANTIL, sm.SCHWELLE_ABSTAND, sm.SCHWELLE_MIN, sm.SCHWELLE_MAX), (0.10, 0.03, 0.30, 0.50))

    def test_leave_one_out_quantil_minus_abstand(self):
        abdruecke = streuende(12, 1.4)
        loo = []
        for i, e in enumerate(abdruecke):
            rest = normalisieren(np.mean([x for j, x in enumerate(abdruecke) if j != i], axis=0))
            loo.append(kosinus(e, rest))
        q10 = float(np.quantile(loo, 0.10))
        self.assertTrue(0.33 < q10 < 0.53, q10)  # die Daten liegen so, dass die Grenzen nicht greifen
        schwelle, quantil = schwelle_einlernen(abdruecke)
        self.assertAlmostEqual(quantil, q10, places=5)
        self.assertAlmostEqual(schwelle, q10 - 0.03, places=5)
        self.assertIsInstance(schwelle, float)

    def test_begrenzt_auf_0_30_bis_0_50(self):
        gleich = [normalisieren(np.ones(DIM))] * 12
        self.assertEqual(schwelle_einlernen(gleich)[0], 0.50)  # sehr ruhige Aufnahme: nie strenger als 0,5
        zufall = [normalisieren(x) for x in np.random.default_rng(9).normal(size=(12, DIM))]
        schwelle, quantil = schwelle_einlernen(zufall)
        self.assertLess(quantil, 0.3)
        self.assertEqual(schwelle, 0.30)  # unruhige Aufnahme: nie lockerer als 0,3

    def test_zu_wenig_stuecke_ergeben_keine_schwelle(self):
        self.assertEqual(schwelle_einlernen([]), (None, None))
        self.assertEqual(schwelle_einlernen([normalisieren(np.ones(DIM))]), (None, None))


class ModellPfadTests(unittest.TestCase):
    def test_eigener_pfad_geht_vor(self):
        self.assertEqual(modell_pfad({"WAMO_STIMME_MODELL": "/x/y/m.onnx", "XDG_CACHE_HOME": "/var/cache/wamo-core"}), Path("/x/y/m.onnx"))

    def test_im_cache_ordner_des_dienstes(self):
        pfad = modell_pfad({"XDG_CACHE_HOME": "/var/cache/wamo-core"})
        self.assertEqual(pfad, Path("/var/cache/wamo-core") / "wamo" / "sprecher" / sm.MODELL_NAME)

    def test_sonst_neben_dem_code(self):
        pfad = modell_pfad({})
        self.assertEqual(pfad, Path(sm.__file__).resolve().parent / ".cache" / "sprecher" / sm.MODELL_NAME)
        self.assertEqual(modell_pfad({"XDG_CACHE_HOME": "  ", "WAMO_STIMME_MODELL": " "}), pfad)


class FalscherExtraktor:
    dim = DIM + 1


class AttrappeExtraktor:
    """Ersatz für den Extraktor von sherpa-onnx: zählt gleichzeitige Aufrufe."""

    dim = DIM

    def __init__(self):
        self.gleichzeitig = 0
        self.hoechstens = 0
        self._sperre = threading.Lock()

    def create_stream(self):
        return mock.Mock()

    def compute(self, stream):
        with self._sperre:
            self.gleichzeitig += 1
            self.hoechstens = max(self.hoechstens, self.gleichzeitig)
        time.sleep(0.03)
        with self._sperre:
            self.gleichzeitig -= 1
        return [1.0] + [0.0] * (DIM - 1)


class EmbedderTests(unittest.TestCase):
    def test_falsche_laenge_des_modells_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            Embedder(Path("x.onnx"), extraktor=FalscherExtraktor())

    def test_abdruck_ist_normiert(self):
        e = Embedder(Path("x.onnx"), extraktor=AttrappeExtraktor())
        v = e.embed(ton(1.0), RATE)
        self.assertEqual(v.shape, (DIM,))
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)

    def test_nan_oder_unendlich_oder_nullvektor_aus_dem_modell_ist_ein_fehler(self):
        for schlecht in ([float("nan")] + [0.5] * (DIM - 1), [float("inf")] + [0.0] * (DIM - 1), [0.0] * DIM):
            extraktor = AttrappeExtraktor()
            extraktor.compute = lambda strom, werte=schlecht: werte
            e = Embedder(Path("x.onnx"), extraktor=extraktor)
            with self.assertRaises(ValueError):
                e.embed(ton(1.0), RATE)

    def test_mehrere_sitzungen_rechnen_nie_gleichzeitig_im_selben_modell(self):
        extraktor = AttrappeExtraktor()
        e = Embedder(Path("x.onnx"), extraktor=extraktor)
        threads = [threading.Thread(target=e.embed, args=(ton(0.5), RATE)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(extraktor.hoechstens, 1)


class LadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_falsche_datei_wird_geloescht_und_spaeter_neu_versucht(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "modell.onnx"
            pfad.write_bytes(b"ausgetauscht")
            jetzt = [100.0]
            modell = StimmModell(pfad, sha256="0" * 64, uhr=lambda: jetzt[0])
            with mock.patch("stimme_modell.cache_ordner", return_value=Path(tmp)):  # die Datei liegt im Cache-Ordner des Dienstes
                self.assertIsNone(await modell.get())
            self.assertFalse(pfad.exists())
            self.assertFalse(modell.bereit)
            with mock.patch("stimme_modell.herunterladen", mock.AsyncMock()) as laden:
                self.assertIsNone(await modell.get())  # gleich danach: kein neuer Versuch
                laden.assert_not_awaited()
                jetzt[0] += NEUER_VERSUCH_SECS + 1
                await modell.get()
                laden.assert_awaited_once()

    async def test_eine_falsche_datei_ausserhalb_des_cache_ordners_wird_nie_geloescht(self):
        """Ein Pfad aus WAMO_STIMME_MODELL gehört dem Betreiber: die falsche Summe ist ein Fehler, aber die Datei bleibt liegen."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            pfad = Path(tmp) / "eigenes.onnx"
            pfad.write_bytes(b"andere Datei")
            modell = StimmModell(pfad, sha256="0" * 64)
            with mock.patch("stimme_modell.cache_ordner", return_value=Path(cache)):
                self.assertIsNone(await modell.get())
            self.assertTrue(pfad.exists())
            self.assertTrue(modell.gescheitert)

    async def test_die_wartezeit_nach_fehlschlaegen_waechst(self):
        jetzt = [0.0]
        modell = StimmModell(Path("gibt-es-nicht/m.onnx"), uhr=lambda: jetzt[0])
        with mock.patch("stimme_modell.herunterladen", mock.AsyncMock(side_effect=httpx.ConnectError("kein Netz"))) as laden:
            await modell.get()
            self.assertEqual(laden.await_count, 1)
            for warten, versuche in ((59, 1), (61, 2), (299, 2), (301, 3), (1799, 3), (1801, 4), (1801, 5)):
                jetzt[0] += warten
                await modell.get()
                self.assertEqual(laden.await_count, versuche, (warten, versuche))

    async def test_nach_erfolg_beginnt_die_wartezeit_wieder_bei_60_sekunden(self):
        jetzt = [0.0]
        modell = StimmModell(Path("gibt-es-nicht/m.onnx"), uhr=lambda: jetzt[0])
        modell._fehlversuche = 3
        modell._gescheitert_um = 0.0
        jetzt[0] = 1801.0
        with mock.patch("stimme_modell.herunterladen", mock.AsyncMock()), mock.patch.object(Path, "is_file", return_value=False), \
                mock.patch("stimme_modell.Embedder", return_value="rechner"):
            self.assertEqual(await modell.get(), "rechner")
        self.assertEqual(modell._fehlversuche, 0)

    async def test_gute_datei_wird_einmal_geladen_und_dann_wiederverwendet(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "modell.onnx"
            pfad.write_bytes(b"inhalt")
            modell = StimmModell(pfad, sha256=hashlib.sha256(b"inhalt").hexdigest())
            with mock.patch("stimme_modell.Embedder", return_value="rechner") as klasse:
                ergebnisse = await asyncio.gather(modell.get(), modell.get(), modell.get())
                self.assertEqual(ergebnisse, ["rechner"] * 3)
                self.assertTrue(modell.bereit)
                self.assertEqual(await modell.get(), "rechner")
            klasse.assert_called_once()

    async def test_fehlt_die_datei_wird_sie_geladen(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "unter" / "modell.onnx"

            async def laden(ziel, **kwargs):
                ziel.parent.mkdir(parents=True, exist_ok=True)
                ziel.write_bytes(b"neu")

            modell = StimmModell(pfad, sha256=hashlib.sha256(b"neu").hexdigest())
            with mock.patch("stimme_modell.herunterladen", side_effect=laden) as geladen, \
                    mock.patch("stimme_modell.Embedder", return_value="rechner"):
                self.assertEqual(await modell.get(), "rechner")
            geladen.assert_awaited_once()

    async def test_fehler_beim_laden_ist_nicht_bereit_und_wirft_nicht(self):
        with tempfile.TemporaryDirectory() as tmp:
            modell = StimmModell(Path(tmp) / "m.onnx", sha256="0" * 64)
            with mock.patch("stimme_modell.herunterladen", mock.AsyncMock(side_effect=httpx.ConnectError("kein Netz"))):
                self.assertIsNone(await modell.get())
            self.assertFalse(modell.bereit)
            self.assertTrue(modell.gescheitert)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_richtige_pruefsumme_benennt_um(self):
        inhalt = b"x" * 3000
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "a" / "m.onnx"
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, content=inhalt))
            await sm.herunterladen(ziel, url="https://example.invalid/m.onnx", sha256=hashlib.sha256(inhalt).hexdigest(), transport=transport)
            self.assertEqual(ziel.read_bytes(), inhalt)
            self.assertFalse(ziel.with_name("m.onnx.part").exists())

    async def test_falsche_pruefsumme_hinterlaesst_nichts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "m.onnx"
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, content=b"anderes"))
            with self.assertRaises(ValueError):
                await sm.herunterladen(ziel, url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)
            self.assertFalse(ziel.exists())
            self.assertFalse(ziel.with_name("m.onnx.part").exists())

    async def test_zu_grosse_datei_bricht_ab_und_hinterlaesst_nichts(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sm, "MODELL_MAX_BYTES", 1000):
            ziel = Path(tmp) / "m.onnx"
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, content=b"x" * 5000))
            with self.assertRaises(ValueError):
                await sm.herunterladen(ziel, url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    async def test_angekuendigte_groesse_ueber_der_grenze_bricht_vor_dem_lesen_ab(self):
        gelesen = []

        class Strom(httpx.AsyncByteStream):
            async def __aiter__(self):
                gelesen.append(1)
                yield b"x"

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sm, "MODELL_MAX_BYTES", 1000):
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, headers={"content-length": "999999"}, stream=Strom()))
            with self.assertRaises(ValueError):
                await sm.herunterladen(Path(tmp) / "m.onnx", url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)
        self.assertEqual(gelesen, [])

    async def test_gesamtfrist_bricht_einen_zaehen_download_ab(self):
        class Langsam(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"x"
                await asyncio.sleep(5)
                yield b"y"

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sm, "GESAMT_FRIST_SECS", 0.1):
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, stream=Langsam()))
            with self.assertRaises(asyncio.TimeoutError):
                await sm.herunterladen(Path(tmp) / "m.onnx", url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    async def test_teildatei_traegt_die_prozessnummer(self):
        namen = []

        class Strom(httpx.AsyncByteStream):
            def __init__(self, ordner):
                self.ordner = ordner

            async def __aiter__(self):
                yield b"x" * 100
                namen.extend(p.name for p in self.ordner.iterdir())

        with tempfile.TemporaryDirectory() as tmp:
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(200, stream=Strom(Path(tmp))))
            with self.assertRaises(ValueError):
                await sm.herunterladen(Path(tmp) / "m.onnx", url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)
        self.assertEqual(namen, [f"m.onnx.{os.getpid()}.part"])

    async def test_fehlerantwort_wirft(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = httpx.MockTransport(lambda anfrage: httpx.Response(404))
            with self.assertRaises(httpx.HTTPStatusError):
                await sm.herunterladen(Path(tmp) / "m.onnx", url="https://example.invalid/m.onnx", sha256="0" * 64, transport=transport)


@unittest.skipUnless(modell_pfad().is_file(), "Modell fehlt (.cache/sprecher/ oder WAMO_STIMME_MODELL)")
class EchtesModellTests(unittest.TestCase):
    def test_pruefsumme_der_vorhandenen_datei_stimmt(self):
        self.assertEqual(sm.datei_sha256(modell_pfad()), sm.MODELL_SHA256)

    def test_abdruck_hat_192_werte_und_ist_stabil(self):
        modell = Embedder()
        pcm = ton(3.0) + np.random.default_rng(2).integers(-800, 800, RATE * 2, dtype=np.int16).tobytes()
        a, b = modell.embed(pcm, RATE), modell.embed(pcm, RATE)
        self.assertEqual(a.shape, (DIM,))
        self.assertAlmostEqual(float(np.linalg.norm(a)), 1.0, places=4)
        self.assertAlmostEqual(kosinus(a, b), 1.0, places=4)


class SchnittstelleTests(unittest.TestCase):
    """Prüfer, Einlernen und Sitzung kennen das Modell nur über eine Schnittstelle (Protocol), Ersatzmodelle in Tests erfüllen dieselbe."""

    def test_das_modell_des_prozesses_erfuellt_die_schnittstelle(self):
        from stimme_modell import ModellQuelle, Rechner

        self.assertIsInstance(sm.MODELL, ModellQuelle)
        self.assertTrue(issubclass(sm.Embedder, Rechner))

    def test_pruefer_einlernen_und_sitzung_nennen_die_schnittstelle(self):
        import typing

        from stimme_einlernen import Einlernen
        from stimme_modell import ModellQuelle
        from stimme_pruefer import Stimmpruefer
        from stimme_sitzung import StimmSitzung

        for klasse in (Stimmpruefer, Einlernen, StimmSitzung):
            self.assertIs(typing.get_type_hints(klasse.__init__)["modell"], ModellQuelle, klasse.__name__)


if __name__ == "__main__":
    unittest.main()
