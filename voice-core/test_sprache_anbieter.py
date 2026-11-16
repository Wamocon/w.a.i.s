"""Tests für die Wahl von Spracherkennung und Sprachausgabe je Sitzung (sprache_anbieter.py)."""

import io
import unittest
import wave
from types import SimpleNamespace
from unittest import mock

import httpx

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSSpeakFrame
from pipecat.tests.utils import run_test

import sprache_anbieter as sa

UMGEBUNG = {"LITELLM_BASE_URL": "http://litellm.test.invalid:4000/v1", "LITELLM_API_KEY": "test-schluessel"}


def wav(rate: int = 22050, sekunden: float = 0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * sekunden))
    return buf.getvalue()


class WahlTest(unittest.IsolatedAsyncioTestCase):
    def test_reihenfolge_umgebung_vor_profil_vor_standard(self):
        with mock.patch.dict("os.environ", {"WAMO_STT_ANBIETER": ""}, clear=False):
            self.assertEqual(sa.gewuenscht("stt"), "soniox")
            self.assertEqual(sa.gewuenscht("stt", "haus"), "haus")
            self.assertEqual(sa.gewuenscht("stt", "unsinn"), "soniox")
        with mock.patch.dict("os.environ", {"WAMO_STT_ANBIETER": "soniox"}):
            self.assertEqual(sa.gewuenscht("stt", "haus"), "soniox", "Umgebung stellt alle Sitzungen zurück")
        with mock.patch.dict("os.environ", {"WAMO_TTS_ANBIETER": "HAUS"}):
            self.assertEqual(sa.gewuenscht("tts", "soniox"), "haus")

    async def test_ohne_wunsch_bleibt_soniox_ohne_gateway_pruefung(self):
        with mock.patch.dict("os.environ", {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": ""}), \
                mock.patch.object(sa, "litellm_problem", side_effect=AssertionError("nicht prüfen")):
            w = await sa.sprach_wahl(None)
        self.assertEqual((w.stt.anbieter, w.tts.anbieter), ("soniox", "soniox"))
        self.assertEqual(w.anzeige("Bryce"), {"stt": "Soniox", "tts": "Soniox Bryce"})

    async def test_profil_haus_ohne_modell_faellt_mit_grund_zurueck(self):
        with mock.patch.dict("os.environ", {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": "", "WAMO_STT_HAUS_MODELL": "",
                                            "WAMO_TTS_HAUS_MODELL": ""}):
            w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"))
        self.assertTrue(w.stt.rueckfall and w.tts.rueckfall)
        self.assertEqual(w.stt.problem, "WAMO_STT_HAUS_MODELL fehlt")
        self.assertEqual(w.anzeige("Bryce"), {"stt": "Soniox (Rückfall)", "tts": "Soniox Bryce (Rückfall)"})

    async def test_gateway_bietet_modell_nicht_an(self):
        env = {"WAMO_STT_ANBIETER": "haus", "WAMO_STT_HAUS_MODELL": "wamo-stt", "WAMO_TTS_ANBIETER": ""}
        with mock.patch.dict("os.environ", env), \
                mock.patch.object(sa, "litellm_problem", mock.AsyncMock(return_value="Modell wamo-stt nicht im Gateway")):
            w = await sa.sprach_wahl(None)
        self.assertEqual(w.stt.anbieter, "soniox")
        self.assertIn("nicht im Gateway", w.stt.problem)

    async def test_haus_wird_genutzt_wenn_das_gateway_es_anbietet(self):
        env = {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": "", "WAMO_STT_HAUS_MODELL": "wamo-stt",
               "WAMO_TTS_HAUS_MODELL": "wamo-tts", "WAMO_TTS_HAUS_STIMME": "thorsten", **UMGEBUNG}
        with mock.patch.dict("os.environ", env), mock.patch.object(sa, "litellm_problem", mock.AsyncMock(return_value=None)):
            w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"))
            self.assertTrue(w.im_haus)
            self.assertEqual(w.anzeige("Bryce"), {"stt": "Haus (wamo-stt)", "tts": "Haus (wamo-tts)"})
            stt = sa.haus_stt(w.stt, ["WAMO", "Eschborn"])
            self.assertIsInstance(stt, sa.OpenAISTTService)
            self.assertIsInstance(sa.haus_tts(w.tts), sa.HausTTSService)

    async def test_tts_ohne_stimme_faellt_zurueck(self):
        env = {"WAMO_TTS_ANBIETER": "haus", "WAMO_TTS_HAUS_MODELL": "wamo-tts", "WAMO_TTS_HAUS_STIMME": "",
               "WAMO_STT_ANBIETER": ""}
        with mock.patch.dict("os.environ", env):
            w = await sa.sprach_wahl(None)
        self.assertEqual((w.tts.anbieter, w.tts.problem), ("soniox", "WAMO_TTS_HAUS_STIMME fehlt"))


class HausSTTTest(unittest.IsolatedAsyncioTestCase):
    """Über das Gateway fordert LiteLLM ohne Angabe verbose_json an, das Qwen3-ASR ablehnt (HTTP 400, Befund 16.11.2026):
    die Spracherkennung im Haus schickt deshalb immer response_format json und die Sprache de."""

    async def test_json_und_deutsch_an_das_gateway(self):
        anfragen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, json={"text": "Wie heißt die Hauptstadt von Frankreich?"})

        stt = sa.HausSTTService(
            api_key="k", base_url="http://litellm.test.invalid:4000/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            settings=sa.HausSTTService.Settings(model="wamo-stt-haus", language=sa.Language.DE, prompt="WAMO, Eschborn"),
        )
        antwort = await stt._transcribe(wav(16000))
        self.assertEqual(antwort.text, "Wie heißt die Hauptstadt von Frankreich?")
        self.assertEqual(anfragen[0].url.path, "/v1/audio/transcriptions")
        teile = anfragen[0].content.decode("latin-1")
        for name, wert in (("response_format", "json"), ("language", "de"), ("model", "wamo-stt-haus"), ("prompt", "WAMO, Eschborn")):
            self.assertIn(f'name="{name}"\r\n\r\n{wert}\r\n', teile, name)
        self.assertNotIn('name="include"', teile)

    async def test_haus_stt_baut_diesen_dienst(self):
        with mock.patch.dict("os.environ", UMGEBUNG):
            stt = sa.haus_stt(sa.Baustein("haus", "haus", "wamo-stt-haus"), [])
        self.assertIsInstance(stt, sa.HausSTTService)


class HausTTSTest(unittest.IsolatedAsyncioTestCase):
    def dienst(self, handler) -> sa.HausTTSService:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return sa.HausTTSService(modell="wamo-tts", stimme="thorsten", basis="http://litellm.test.invalid:4000/v1",
                                 schluessel="k", client=client, sample_rate=24000)

    async def test_wav_wird_als_audio_ausgegeben_und_umgerechnet(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, content=wav(22050))

        unten, _ = await run_test(self.dienst(handler), frames_to_send=[TTSSpeakFrame("Hallo.")])
        audio = [f for f in unten if isinstance(f, TTSAudioRawFrame)]
        self.assertTrue(audio)
        self.assertTrue(all(f.sample_rate == 24000 for f in audio))
        self.assertEqual(anfragen[0].url.path, "/v1/audio/speech")
        self.assertEqual(anfragen[0].headers["authorization"], "Bearer k")
        self.assertIn(b'"response_format":"wav"', anfragen[0].content.replace(b" ", b""))

    async def test_http_fehler_ergibt_fehlermeldung_statt_haenger(self):
        unten, oben = await run_test(self.dienst(lambda r: httpx.Response(500, text="kaputt")),
                                     frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertFalse([f for f in unten if isinstance(f, TTSAudioRawFrame)])
        self.assertTrue([f for f in [*unten, *oben] if isinstance(f, ErrorFrame)])


if __name__ == "__main__":
    unittest.main()
