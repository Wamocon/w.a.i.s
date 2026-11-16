"""Tests für den TTS-Dienst der eigenen Instanz auf Sokrates-1 (infra/sokrates1/wamo-tts-haus/app.py): gestreamte Antwort,
Freigabe des GPU-Locks bei jedem Abbruch, Fehler vor und mitten im Strom. Das Modell ist durch eine Attrappe ersetzt."""

import asyncio
import importlib.util
import json
import struct
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

PFAD = Path(__file__).resolve().parent.parent / "infra" / "sokrates1" / "wamo-tts-haus" / "app.py"
_spec = importlib.util.spec_from_file_location("wamo_tts_haus_app", PFAD)
dienst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dienst)

BLOCK_SAMPLES = 1920  # ein Frame, 80 ms bei 24 kHz
BLOCK_BYTES = BLOCK_SAMPLES * 2


def attrappe(*, anzahl: int = 20, vorlauf: float = 0.0, pause: float = 0.01, fehler_bei: int | None = None, spur: list):
    """Ersatz für _stream_bloecke: schreibt in spur, ob die Erzeugung gestoppt wurde oder durchlief."""
    def bloecke(text, speaker, language, instruct, erster, block, stopp):
        spur.append(("start", text))
        time.sleep(vorlauf)
        for i in range(anzahl):
            if stopp.is_set():
                spur.append(("stopp", i))
                return
            if fehler_bei == i:
                raise RuntimeError("kaputt")
            yield np.full(BLOCK_SAMPLES, 0.1, dtype=np.float32), 24000
            time.sleep(pause)
        spur.append(("ende", anzahl))
    return bloecke


async def post(koerper: dict, *, trennen: str | None = None, gesendet: list | None = None) -> list[dict]:
    """Ruft die ASGI-App direkt auf. trennen: None (liest alles), "sofort" (der Aufrufer ist nach der Anfrage weg) oder
    "nach_erstem" (trennt nach dem ersten Audioblock, wie eine Unterbrechung im Gespräch)."""
    gesendet = [] if gesendet is None else gesendet
    getrennt = asyncio.Event()
    if trennen == "sofort":
        getrennt.set()
    gelesen = False

    async def receive():
        nonlocal gelesen
        if not gelesen:
            gelesen = True
            return {"type": "http.request", "body": json.dumps(koerper).encode(), "more_body": False}
        await getrennt.wait()
        return {"type": "http.disconnect"}

    async def send(nachricht):
        gesendet.append(nachricht)
        if trennen == "nach_erstem" and nachricht["type"] == "http.response.body" and nachricht.get("body"):
            getrennt.set()

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": "/v1/audio/speech", "raw_path": b"/v1/audio/speech", "root_path": "", "query_string": b"",
             "headers": [(b"content-type", b"application/json")], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
    await dienst.app(scope, receive, send)
    return gesendet


def koerper_bytes(gesendet: list[dict]) -> bytes:
    return b"".join(n.get("body", b"") for n in gesendet if n["type"] == "http.response.body")


def warte_bis(bedingung, frist: float = 3.0) -> bool:
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.02)
    return bedingung()


def lock_frei() -> bool:
    if dienst.LOCK.acquire(blocking=False):
        dienst.LOCK.release()
        return True
    return False


ANFRAGE = {"input": "Hallo, das ist ein Test.", "voice": "sohee", "response_format": "wav", "stream": True}


class StreamTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.spur: list = []
        self._vorher = (dienst.MODEL, dienst.STREAM_BEREIT, dienst._stream_bloecke)
        dienst.MODEL = SimpleNamespace(sample_rate=24000)
        dienst.STREAM_BEREIT = True

    def tearDown(self):
        dienst.MODEL, dienst.STREAM_BEREIT, dienst._stream_bloecke = self._vorher
        self.assertTrue(warte_bis(lock_frei), "GPU-Lock bleibt belegt")

    def ersetze(self, **kwargs):
        dienst._stream_bloecke = attrappe(spur=self.spur, **kwargs)

    async def test_wav_kopf_ohne_laenge_dann_alle_bloecke(self):
        self.ersetze(anzahl=5)
        gesendet = await post(ANFRAGE)
        start = gesendet[0]
        self.assertEqual(start["status"], 200)
        kopfzeilen = dict(start["headers"])
        self.assertEqual(kopfzeilen[b"x-stream"], b"1")
        self.assertEqual(kopfzeilen[b"content-type"], b"audio/wav")
        daten = koerper_bytes(gesendet)
        self.assertEqual(daten[:4], b"RIFF")
        self.assertEqual(daten[8:16], b"WAVEfmt ")
        self.assertEqual(struct.unpack("<I", daten[24:28])[0], 24000)
        self.assertEqual(struct.unpack("<I", daten[40:44])[0], 0xFFFFFFFF)
        self.assertEqual(len(daten), 44 + 5 * BLOCK_BYTES)
        # Kopf und erster Block gehen in einem Stück (der Kern liest die Abtastrate aus dem ersten Stück)
        erstes = next(n for n in gesendet if n["type"] == "http.response.body")
        self.assertEqual(len(erstes["body"]), 44 + BLOCK_BYTES)
        self.assertTrue(warte_bis(lambda: ("ende", 5) in self.spur))

    async def test_pcm_ohne_kopf(self):
        self.ersetze(anzahl=2)
        gesendet = await post({**ANFRAGE, "response_format": "pcm"})
        self.assertEqual(len(koerper_bytes(gesendet)), 2 * BLOCK_BYTES)

    async def test_unterbrechung_nach_dem_ersten_block_stoppt_die_erzeugung(self):
        self.ersetze(anzahl=200, pause=0.02)
        await post(ANFRAGE, trennen="nach_erstem")
        self.assertTrue(warte_bis(lambda: any(e[0] == "stopp" for e in self.spur)), self.spur)
        self.assertLess(next(e[1] for e in self.spur if e[0] == "stopp"), 50)

    async def test_trennen_vor_dem_ersten_block_stoppt_die_erzeugung(self):
        self.ersetze(anzahl=200, vorlauf=0.4)
        gesendet = await post(ANFRAGE, trennen="sofort")
        self.assertNotEqual(gesendet[0]["status"], 200)
        self.assertTrue(warte_bis(lambda: ("stopp", 0) in self.spur), self.spur)

    async def test_wer_auf_den_lock_wartet_und_trennt_gibt_auf(self):
        self.ersetze(anzahl=5)
        dienst.LOCK.acquire()
        try:
            await post(ANFRAGE, trennen="sofort")
        finally:
            await asyncio.sleep(0.3)
            dienst.LOCK.release()
        await asyncio.sleep(0.3)
        self.assertEqual(self.spur, [])  # nie erzeugt

    async def test_fehler_vor_dem_ersten_block_ist_http_500(self):
        self.ersetze(fehler_bei=0)
        gesendet = await post(ANFRAGE)
        self.assertEqual(gesendet[0]["status"], 500)

    async def test_fehler_mitten_im_strom_bricht_die_verbindung_ab(self):
        self.ersetze(anzahl=10, fehler_bei=3)
        gesendet: list = []
        with self.assertRaises(BaseException):
            await post(ANFRAGE, gesendet=gesendet)
        self.assertEqual(gesendet[0]["status"], 200)
        self.assertEqual(len(koerper_bytes(gesendet)), 44 + 3 * BLOCK_BYTES)
        # kein sauberes Ende (more_body False): der Aufrufer sieht einen Abbruch statt eines scheinbar ganzen Satzes
        self.assertFalse([n for n in gesendet if n["type"] == "http.response.body" and not n.get("more_body", False)])

    async def test_unbekanntes_format_wird_abgelehnt(self):
        self.ersetze(anzahl=1)
        for fmt in ("../../tmp/x", "m3u8", "wav/../x"):
            gesendet = await post({**ANFRAGE, "stream": False, "response_format": fmt})
            self.assertEqual(gesendet[0]["status"], 422, fmt)
        self.assertEqual(self.spur, [])

    async def test_ohne_streaming_bereitschaft_kein_stream(self):
        dienst.STREAM_BEREIT = False
        self.ersetze(anzahl=1)
        def ganze_datei(*_):
            raise dienst.HTTPException(418, "Weg ohne Streaming")

        vorher = dienst._synthesize
        dienst._synthesize = ganze_datei
        try:
            gesendet = await post(ANFRAGE)
        finally:
            dienst._synthesize = vorher
        self.assertEqual(gesendet[0]["status"], 418)
        self.assertEqual(self.spur, [])


class BlockTest(unittest.TestCase):
    def test_anlauf_der_bloecke(self):
        folge, geliefert, ziel = [], 0, 2
        for _ in range(13):
            folge.append(ziel)
            geliefert += ziel
            ziel = dienst.naechster_block(geliefert, 6)
        self.assertEqual(folge, [2, 1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 6, 6])

    def test_vorrat_bleibt_auch_unter_last_ueber_null(self):
        # Ohne Last rund 48 ms Rechenzeit je Frame, mit anderer Last auf der GPU gemessen bis rund 65 ms (80 ms Audio je Frame),
        # dazu rund 5 ms je Block für den Decoder: jeder Folgeblock ist fertig, bevor das Gelieferte abgespielt ist
        folge, geliefert, ziel = [], 0, 2
        for _ in range(20):
            folge.append(ziel)
            geliefert += ziel
            ziel = dienst.naechster_block(geliefert, 6)
        for je_frame in (0.048, 0.065):
            ankunft, audio_bis, t_erst = 0.0, 0.0, None
            for n in folge:
                ankunft += n * je_frame + 0.005
                if t_erst is None:
                    t_erst = ankunft
                else:
                    self.assertLess(ankunft, t_erst + audio_bis, (je_frame, folge))
                audio_bis += n * 0.08

    def test_blockgroesse_aus_der_anfrage_begrenzt(self):
        self.assertEqual(dienst._block_wert({"block": 100}, "block", 6, 48), 48)
        self.assertEqual(dienst._block_wert({"block": 0}, "block", 6, 48), 1)
        self.assertEqual(dienst._block_wert({"block": True}, "block", 6, 48), 6)
        self.assertEqual(dienst._block_wert({"block": "3"}, "block", 6, 48), 6)
        self.assertEqual(dienst._block_wert({}, "block", 6, 48), 6)


if __name__ == "__main__":
    unittest.main()
