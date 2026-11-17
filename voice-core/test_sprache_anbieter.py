"""Tests für die Wahl von Spracherkennung und Sprachausgabe je Sitzung (sprache_anbieter.py)."""

import io
import json
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

    async def test_deutsch_steht_immer_vorn_im_prompt(self):
        """Befund 17.11.2026 am Server: Qwen3-ASR hinter vLLM übergeht language=de ("Wie wordt het weer am Wachtenende in Ashbourne?"),
        mit einem deutschen Hinweis im Feld prompt kommt Deutsch zurück. Der Hinweis steht deshalb immer vorn, auch ohne Fachbegriffe."""
        with mock.patch.dict("os.environ", UMGEBUNG):
            ohne = sa.haus_stt(sa.Baustein("haus", "haus", "wamo-stt-haus"), [])
            mit = sa.haus_stt(sa.Baustein("haus", "haus", "wamo-stt-haus"), ["WAMO", "Eschborn"])
        self.assertEqual(ohne._settings.prompt, sa.STT_HAUS_HINWEIS)
        self.assertEqual(mit._settings.prompt, f"{sa.STT_HAUS_HINWEIS} WAMO, Eschborn")
        self.assertIn("Deutsch", sa.STT_HAUS_HINWEIS)
        self.assertEqual(ohne._settings.language, "de", "language=de bleibt")

        anfragen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, json={"text": "Wie wird das Wetter am Wochenende in Eschborn?"})

        ohne._client = sa.HausSTTService(api_key="k", base_url="http://litellm.test.invalid:4000/v1",
                                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))._client
        await ohne._transcribe(wav(16000))
        teile = anfragen[0].content.decode("latin-1")  # mit der WAV im Körper; der Hinweissatz selbst ist ASCII
        self.assertIn(f'name="prompt"\r\n\r\n{sa.STT_HAUS_HINWEIS}\r\n', teile)
        self.assertIn('name="language"\r\n\r\nde\r\n', teile)


class HausTTSEinstellungenTest(unittest.TestCase):
    """Befund im Journal 17.11.2026: "TTSSettings: the following fields are NOT_GIVEN: model, voice, language" bei jedem Start einer
    Sitzung mit Sprachausgabe im Haus. Der Dienst trägt seine Konfiguration jetzt als Pipecat-Einstellungen."""

    def test_einstellungen_vollstaendig_aus_der_konfiguration(self):
        from pipecat.utils.types import is_given

        fehler: list[str] = []
        senke = sa.logger.add(lambda m: fehler.append(str(m)), level="ERROR")
        try:
            dienst = sa.HausTTSService(modell="wamo-tts-haus", stimme="sohee", basis="http://litellm.test.invalid:4000/v1",
                                       schluessel="k")
            dienst._settings.validate_complete()  # ruft Pipecat beim Start der Sitzung auf (AIService.start)
        finally:
            sa.logger.remove(senke)
        self.assertEqual(fehler, [])
        s = dienst._settings
        self.assertTrue(all(is_given(getattr(s, f)) for f in ("model", "voice", "language")))
        self.assertEqual((s.model, s.voice, s.language), ("wamo-tts-haus", "sohee", None))

    def test_verhalten_bleibt_satzgrenzen_und_anfrage_wie_bisher(self):
        """language None: der Dienst schickt keine Sprache (der Dienst im Haus hat seine eigene), und Pipecat trennt die Sätze wie
        vorher (Standard ohne Sprache)."""
        dienst = sa.HausTTSService(modell="wamo-tts-haus", stimme="sohee", basis="http://litellm.test.invalid:4000/v1", schluessel="k")
        self.assertEqual(dienst._text_aggregator.language, "en")
        self.assertEqual(sa.haus_tts(sa.Baustein("haus", "haus", "wamo-tts-haus", stimme="uncle_fu"))._settings.voice, "uncle_fu")


class HausTTSTest(unittest.IsolatedAsyncioTestCase):
    def dienst(self, handler) -> sa.HausTTSService:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return sa.HausTTSService(modell="wamo-tts", stimme="thorsten", basis="http://litellm.test.invalid:4000/v1",
                                 schluessel="k", client=client, sample_rate=24000, stream=False)

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

    async def test_ohne_schalter_kein_stream_und_modellweg(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, content=wav(24000))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with mock.patch.dict("os.environ", {"WAMO_TTS_HAUS_STREAM": ""}):
            dienst = sa.HausTTSService(modell="wamo-tts", stimme="thorsten", basis="http://litellm.test.invalid:4000/v1",
                                       schluessel="k", client=client, sample_rate=24000)
        self.assertFalse(dienst.stream)
        await run_test(dienst, frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertEqual(anfragen[0].url.path, "/v1/audio/speech")
        self.assertNotIn("stream", json.loads(anfragen[0].content))


def stueckweise(daten: bytes, *groessen: int):
    """Antwortkörper in Stücken wie über das Netz: erst die genannten Größen, dann der Rest."""
    async def gen():
        rest = daten
        for g in groessen:
            yield rest[:g]
            rest = rest[g:]
        if rest:
            yield rest
    return gen()


def audio_bytes(frames) -> int:
    return sum(len(f.audio) for f in frames if isinstance(f, TTSAudioRawFrame))


class HausTTSStreamTest(unittest.IsolatedAsyncioTestCase):
    """Gestreamte Sprachausgabe über die Durchreiche des Gateways (WAMO_TTS_HAUS_STREAM=an)."""

    def setUp(self):
        sa.HausTTSService.durchreiche_pause_bis = 0.0

    def tearDown(self):
        sa.HausTTSService.durchreiche_pause_bis = 0.0

    def dienst(self, handler, *, stream: bool = True) -> sa.HausTTSService:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return sa.HausTTSService(modell="wamo-tts-haus", stimme="sohee", basis="http://litellm.test.invalid:4000/v1",
                                 schluessel="k", client=client, sample_rate=24000, stream=stream)

    def test_schalter_aus_der_umgebung(self):
        for wert, erwartet in (("an", True), ("AN", True), ("aus", False), ("", False), ("ja", False)):
            with mock.patch.dict("os.environ", {"WAMO_TTS_HAUS_STREAM": wert}):
                self.assertIs(sa.tts_stream_an(), erwartet, wert)

    def test_wurzel_des_gateways(self):
        self.assertEqual(sa.litellm_wurzel("http://gw:4000/v1"), "http://gw:4000")
        self.assertEqual(sa.litellm_wurzel("http://gw:4000/v1/"), "http://gw:4000")
        self.assertEqual(sa.litellm_wurzel("https://gw.example/litellm"), "https://gw.example/litellm")

    async def test_stream_geht_ueber_die_durchreiche_mit_stream_feld(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, content=stueckweise(wav(24000), 44 + 960, 960))

        unten, _ = await run_test(self.dienst(handler), frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertEqual(len(anfragen), 1)
        self.assertEqual(anfragen[0].url.host, "litellm.test.invalid")
        self.assertEqual(anfragen[0].url.path, "/wamo-tts-haus/v1/audio/speech")
        self.assertEqual(anfragen[0].headers["authorization"], "Bearer k")
        koerper = json.loads(anfragen[0].content)
        self.assertIs(koerper["stream"], True)
        self.assertEqual((koerper["model"], koerper["voice"], koerper["response_format"]), ("wamo-tts-haus", "sohee", "wav"))
        self.assertEqual(audio_bytes(unten), 24000 * 2 // 5)  # 0,2 s, 16 Bit, ohne Kopf

    async def test_wav_kopf_in_kleinen_stuecken_wird_erkannt(self):
        # Über das Netz kann der 44-Byte-Kopf zerteilt ankommen; die Abtastrate muss trotzdem aus dem Kopf kommen (hier 22050 Hz,
        # umgerechnet auf 24000 Hz), und kein Byte des Kopfes darf als Audio durchrutschen.
        async def ausgabe(*stuecke: int) -> int:
            antwort = lambda r: httpx.Response(200, content=stueckweise(wav(22050), *stuecke))  # noqa: E731
            unten, _ = await run_test(self.dienst(antwort), frames_to_send=[TTSSpeakFrame("Hallo.")])
            return audio_bytes(unten)

        am_stueck = await ausgabe()
        self.assertGreater(am_stueck, 0)
        self.assertAlmostEqual(await ausgabe(10, 20, 30), am_stueck, delta=8)
        self.assertAlmostEqual(await ausgabe(44, 1), am_stueck, delta=8)

    async def test_abgelehnte_durchreiche_faellt_auf_den_modellweg_zurueck_und_pausiert(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                sa.HausTTSService.durchreiche_pause_bis = 0.0
                anfragen = []

                def handler(request: httpx.Request, status=status) -> httpx.Response:
                    anfragen.append(request.url.path)
                    if request.url.path.startswith("/wamo-tts-haus/"):
                        return httpx.Response(status, json={"detail": "abgelehnt"})
                    return httpx.Response(200, content=wav(24000))

                unten, oben = await run_test(self.dienst(handler),
                                             frames_to_send=[TTSSpeakFrame("Hallo."), TTSSpeakFrame("Noch was.")])
                self.assertEqual(anfragen, ["/wamo-tts-haus/v1/audio/speech", "/v1/audio/speech", "/v1/audio/speech"])
                self.assertEqual(audio_bytes(unten), 2 * 24000 * 2 // 5)
                self.assertFalse([f for f in [*unten, *oben] if isinstance(f, ErrorFrame)])
                self.assertGreater(sa.HausTTSService.durchreiche_pause_bis, 0.0)

    async def test_nach_der_pause_wieder_die_durchreiche(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request.url.path)
            return httpx.Response(200, content=wav(24000))

        sa.HausTTSService.durchreiche_pause_bis = 1000.0
        with mock.patch.object(sa, "_uhr", return_value=999.0):
            await run_test(self.dienst(handler), frames_to_send=[TTSSpeakFrame("Hallo.")])
        with mock.patch.object(sa, "_uhr", return_value=1000.5):
            await run_test(self.dienst(handler), frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertEqual(anfragen, ["/v1/audio/speech", "/wamo-tts-haus/v1/audio/speech"])

    async def test_fehler_der_durchreiche_ausser_ablehnung_bleibt_ein_fehler(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request.url.path)
            return httpx.Response(500, text="kaputt")

        unten, oben = await run_test(self.dienst(handler), frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertEqual(anfragen, ["/wamo-tts-haus/v1/audio/speech"])
        self.assertTrue([f for f in [*unten, *oben] if isinstance(f, ErrorFrame)])

    async def test_ohne_stream_bleibt_der_modellweg(self):
        anfragen = []

        def handler(request: httpx.Request) -> httpx.Response:
            anfragen.append(request)
            return httpx.Response(200, content=wav(24000))

        await run_test(self.dienst(handler, stream=False), frames_to_send=[TTSSpeakFrame("Hallo.")])
        self.assertEqual(anfragen[0].url.path, "/v1/audio/speech")
        self.assertNotIn("stream", json.loads(anfragen[0].content))

    async def test_haus_tts_liest_den_schalter(self):
        env = {"WAMO_TTS_HAUS_STREAM": "an", "WAMO_TTS_HAUS_STIMME": "sohee", **UMGEBUNG}
        with mock.patch.dict("os.environ", env):
            self.assertTrue(sa.haus_tts(sa.Baustein("haus", "haus", "wamo-tts-haus")).stream)
        with mock.patch.dict("os.environ", {**env, "WAMO_TTS_HAUS_STREAM": "aus"}):
            self.assertFalse(sa.haus_tts(sa.Baustein("haus", "haus", "wamo-tts-haus")).stream)


if __name__ == "__main__":
    unittest.main()
