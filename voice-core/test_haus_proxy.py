"""Tests des Proxys für Entwicklungsaufträge mit Hausmodellen (infra/sokrates2/wamo_haus_proxy.py, Paket P6a).

Laufen überall ohne Netz: LiteLLM ist eine Attrappe auf Loopback, die jede Anfrage mitschreibt. Geprüft wird vor allem, dass nichts nach
draußen geht, was nicht erlaubt ist (Weg, Methode, Token, Größe, Modell, Budget), dass Streaming unverändert ankommt, dass der Schlüssel
nur zu LiteLLM geht und dass weder Token noch Schlüssel im Protokoll stehen.

Ausführen:  uv run python -m pytest -q test_haus_proxy.py   (in voice-core/)
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"
sys.path.insert(0, str(INFRA))

import wamo_haus_proxy as X  # noqa: E402

SCHLUESSEL = "sk-litellm-test-0123456789"
JOB = "0123456789abcdef0123"
TOKEN = f"wh1-{JOB}-{'a' * 64}"
MODELL = "qwen3.6-35b"

SSE = (b"event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"m1\",\"usage\":{\"input_tokens\":1200,"
       b"\"cache_read_input_tokens\":300,\"output_tokens\":1}}}\n\n"
       b"event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"Hallo\"}}\n\n"
       b"event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"},\"usage\":{\"output_tokens\":42}}\n\n"
       b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n")


class Attrappe:
    """LiteLLM-Attrappe: schreibt Kopf und Körper jeder Anfrage mit und antwortet je nach Art mit SSE (gestückelt), JSON oder wartet."""

    def __init__(self, art="sse", warten: asyncio.Event | None = None, status=200):
        self.art, self.warten, self.status = art, warten, status
        self.anfragen: list[tuple[str, bytes]] = []

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._bediene, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()

    async def _bediene(self, r, w):
        kopf = (await r.readuntil(b"\r\n\r\n")).decode("ascii")
        laenge = int(next(z.split(":", 1)[1] for z in kopf.split("\r\n") if z.lower().startswith("content-length:")))
        koerper = await r.readexactly(laenge)
        self.anfragen.append((kopf, koerper))
        if self.warten is not None:
            await self.warten.wait()
        if self.art == "abbruch":  # Kopf und ein halbes Stück, dann weg (Antwort zu kurz)
            w.write(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n40\r\nevent: mess")
        elif self.art == "ohne_usage":
            body = json.dumps({"type": "message", "content": [{"type": "text", "text": "x" * 400}]}).encode()
            w.write(f"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {len(body)}\r\n\r\n".encode() + body)
        elif self.art == "sse":
            w.write(f"HTTP/1.1 {self.status} OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n".encode())
            for i in range(0, len(SSE), 37):  # Stücke quer durch die Zeilen
                teil = SSE[i:i + 37]
                w.write(f"{len(teil):x}\r\n".encode() + teil + b"\r\n")
                await w.drain()
            w.write(b"0\r\n\r\n")
        else:
            body = json.dumps({"type": "message", "content": [{"type": "text", "text": "ok"}],
                               "usage": {"input_tokens": 50, "output_tokens": 7},
                               "intern": "api_base http://10.0.0.1:11434 und schluessel-hash"}).encode()
            w.write(f"HTTP/1.1 {self.status} OK\r\ncontent-type: application/json\r\ncontent-length: {len(body)}\r\n\r\n".encode() + body)
        await w.drain()
        w.close()


class Welt:
    def __init__(self, attrappe: Attrappe, parallel=2, warte_s=5.0, tag_token_max=10_000_000, max_token=100_000, bis=None,
                 verbrauch_datei=True):
        self.attrappe, self.parallel, self.warte_s, self.tag_token_max = attrappe, parallel, warte_s, tag_token_max
        self.max_token, self.bis, self.verbrauch_datei = max_token, bis, verbrauch_datei
        self.log: list[str] = []

    async def __aenter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self.tmp.name) / "auftraege"
        self.ordner.mkdir()
        self.tokendatei(JOB, TOKEN, max_token=self.max_token, bis=self.bis)
        self.verbrauch = X.Verbrauch(Path(self.tmp.name) / "verbrauch.jsonl" if self.verbrauch_datei else None)
        self.proxy = X.Proxy(X.Ziel("127.0.0.1", self.attrappe.port, ""), SCHLUESSEL, frozenset({MODELL}), self.ordner, self.verbrauch,
                             parallel_max=self.parallel, tag_token_max=self.tag_token_max, warte_s=self.warte_s,
                             protokoll=self.log.append)
        self.server = await X.serve(self.proxy, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()
        self.tmp.cleanup()

    def tokendatei(self, datei_job, token, max_token=100_000, bis=None, **extra):
        d = {"v": 1, "job": datei_job, "hash": hashlib.sha256(token.encode()).hexdigest(), "profil": "1a2b3c4d",
             "bis": int(time.time()) + 600 if bis is None else bis, "max_token": max_token, **extra}
        (self.ordner / f"{datei_job}.json").write_text(json.dumps(d), encoding="utf-8")

    async def anfrage(self, *, methode="POST", weg="/v1/messages?beta=true", token=TOKEN, kopf_art="x-api-key", body=None,
                      zusatz: list[str] | None = None, roh: bytes | None = None) -> tuple[int, dict, bytes]:
        r, w = await asyncio.open_connection("127.0.0.1", self.port)
        if roh is None:
            daten = json.dumps(body if body is not None else {"model": MODELL, "max_tokens": 16, "stream": True,
                                                             "messages": [{"role": "user", "content": "Hallo"}]}).encode()
            zeilen = [f"{methode} {weg} HTTP/1.1", "Host: 127.0.0.1", "Content-Type: application/json", f"Content-Length: {len(daten)}",
                      "anthropic-version: 2023-06-01", "anthropic-beta: tools-2024", "X-Fremd: soll-nicht-weiter"]
            if token is not None:
                zeilen.append(f"x-api-key: {token}" if kopf_art == "x-api-key" else f"Authorization: Bearer {token}")
            zeilen += zusatz or []
            roh = ("\r\n".join(zeilen) + "\r\n\r\n").encode() + daten
        w.write(roh)
        await w.drain()
        antwort = await asyncio.wait_for(r.read(), 10)
        w.close()
        kopf, _, rest = antwort.partition(b"\r\n\r\n")
        zeilen = kopf.decode().split("\r\n")
        status = int(zeilen[0].split(" ")[1])
        k = {z.split(":", 1)[0].lower(): z.split(":", 1)[1].strip() for z in zeilen[1:]}
        if k.get("transfer-encoding") == "chunked":
            rest = entstueckeln(rest)
        return status, k, rest


def entstueckeln(daten: bytes) -> bytes:
    aus = b""
    while True:
        zeile, _, daten = daten.partition(b"\r\n")
        if not zeile:  # abgebrochene Antwort
            return aus
        n = int(zeile, 16)
        if n == 0:
            return aus
        aus, daten = aus + daten[:n], daten[n + 2:]


def lauf(coro):
    return asyncio.run(coro)


class Abweisungen(unittest.TestCase):
    def pruefe(self, erwartet, **kw):
        async def t():
            async with Attrappe() as a, Welt(a) as welt:
                status, _, body = await welt.anfrage(**kw)
                self.assertEqual(status, erwartet, body)
                self.assertEqual(a.anfragen, [], "bei einer Abweisung darf nichts an LiteLLM gehen")
                self.assertEqual(json.loads(body)["type"], "error")
                return welt
        return lauf(t())

    def test_weg_falsch(self):
        self.pruefe(404, weg="/v1/models")
        self.pruefe(404, weg="/v1/chat/completions")
        self.pruefe(404, weg="/v1/messages?beta=true&x=1")
        self.pruefe(404, weg="/v1/messages/../models")

    def test_methode(self):
        self.pruefe(405, methode="GET")

    def test_token(self):
        self.pruefe(401, token=None)
        self.pruefe(401, token="sk-ant-api03-" + "x" * 40)
        self.pruefe(401, token=f"wh1-{JOB}-{'b' * 64}")  # richtige Form, falscher Hash
        self.pruefe(401, token=f"wh1-{'f' * 20}-{'a' * 64}")  # keine Datei

    def test_token_abgelaufen(self):
        async def t():
            async with Attrappe() as a, Welt(a, bis=int(time.time()) - 1) as welt:
                status, _, _ = await welt.anfrage()
                self.assertEqual(status, 401)
                self.assertEqual(a.anfragen, [])
        lauf(t())

    def test_tokendatei_link_und_falsche_felder(self):
        async def t():
            async with Attrappe() as a, Welt(a) as welt:
                anderer = f"wh1-{'c' * 16}-{'d' * 64}"
                welt.tokendatei("c" * 16, anderer, job="e" * 16)  # Datei nennt einen anderen Auftrag
                self.assertEqual((await welt.anfrage(token=anderer))[0], 401)
                if hasattr(os, "symlink"):
                    ziel = welt.ordner / ("1" * 16 + ".json")
                    welt.tokendatei("1" * 16, f"wh1-{'1' * 16}-{'a' * 64}")
                    try:
                        os.symlink(ziel, welt.ordner / ("2" * 16 + ".json"))
                    except OSError:
                        return
                    self.assertEqual((await welt.anfrage(token=f"wh1-{'2' * 16}-{'a' * 64}"))[0], 401)
                self.assertEqual(a.anfragen, [])
        lauf(t())

    def test_laenge(self):
        roh = (f"POST /v1/messages HTTP/1.1\r\nx-api-key: {TOKEN}\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n").encode()
        self.pruefe(411, roh=roh)
        roh = f"POST /v1/messages HTTP/1.1\r\nx-api-key: {TOKEN}\r\nContent-Length: {X.KOERPER_MAX + 1}\r\n\r\n".encode()
        self.pruefe(413, roh=roh)
        self.pruefe(400, zusatz=["X-Fremd: doppelt"])  # doppelte Kopfzeile

    def test_modell(self):
        self.pruefe(400, body={"model": "claude-sonnet-4-5", "max_tokens": 1, "messages": []})
        self.pruefe(400, body={"model": "sokrates-steuer", "max_tokens": 1, "messages": []})
        self.pruefe(400, body=["kein", "objekt"])

    def test_kein_token_oder_schluessel_im_protokoll(self):
        welt = self.pruefe(401, token=f"wh1-{JOB}-{'b' * 64}")
        text = "\n".join(welt.log)
        self.assertNotIn("b" * 64, text)
        self.assertNotIn(SCHLUESSEL, text)
        self.assertIn("token_falsch", text)


class Durchreichen(unittest.TestCase):
    def test_streaming_unveraendert_und_gezaehlt(self):
        async def t():
            async with Attrappe("sse") as a, Welt(a) as welt:
                status, kopf, body = await welt.anfrage()
                self.assertEqual(status, 200)
                self.assertEqual(kopf["content-type"], "text/event-stream")
                self.assertEqual(body, SSE)
                anfrage_kopf, anfrage_body = a.anfragen[0]
                self.assertTrue(anfrage_kopf.startswith("POST /v1/messages?beta=true HTTP/1.1\r\n"))
                self.assertIn(f"Authorization: Bearer {SCHLUESSEL}\r\n", anfrage_kopf)
                self.assertIn("anthropic-version: 2023-06-01", anfrage_kopf)
                self.assertNotIn(TOKEN, anfrage_kopf)
                self.assertNotIn("x-api-key", anfrage_kopf.lower())
                self.assertNotIn("x-fremd", anfrage_kopf.lower())
                self.assertEqual(json.loads(anfrage_body)["model"], MODELL)
                self.assertEqual(welt.verbrauch.je_auftrag[JOB], 1200 + 300 + 42)
                eintrag = json.loads((Path(welt.tmp.name) / "verbrauch.jsonl").read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual((eintrag["ein"], eintrag["aus"], eintrag["status"], eintrag["profil"]), (1500, 42, 200, "1a2b3c4d"))
                text = "\n".join(welt.log)
                self.assertNotIn(SCHLUESSEL, text)
                self.assertNotIn(TOKEN, text)
                self.assertIn(f"job={JOB}", text)
        lauf(t())

    def test_json_mit_bearer_und_count_tokens(self):
        async def t():
            async with Attrappe("json") as a, Welt(a) as welt:
                status, _, body = await welt.anfrage(kopf_art="bearer", weg="/v1/messages/count_tokens")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["usage"]["output_tokens"], 7)
                self.assertTrue(a.anfragen[0][0].startswith("POST /v1/messages/count_tokens HTTP/1.1\r\n"))
                self.assertEqual(welt.verbrauch.je_auftrag[JOB], 57)
        lauf(t())

    def test_fehler_von_litellm_nur_als_eigener_fehler(self):
        async def t():
            async with Attrappe("json", status=500) as a, Welt(a) as welt:
                status, _, body = await welt.anfrage()
                self.assertEqual(status, 500)
                self.assertNotIn(b"api_base", body)
                self.assertIn("LiteLLM meldet Status 500", json.loads(body)["error"]["message"])
                self.assertEqual(sum("ziel_fehler" in z for z in welt.log), 1)
        lauf(t())

    def test_felder_nur_aus_der_liste(self):
        for feld in ("fallbacks", "api_base", "mock_response", "extra_headers", "litellm_metadata", "num_retries"):
            with self.subTest(feld=feld):
                async def t():
                    async with Attrappe("json") as a, Welt(a) as welt:
                        status, _, _ = await welt.anfrage(body={"model": MODELL, "max_tokens": 8, "messages": [], feld: "x"})
                        self.assertEqual(status, 400)
                        self.assertEqual(a.anfragen, [])
                lauf(t())

    def test_metadata_und_max_tokens_bereinigt(self):
        async def t():
            async with Attrappe("json") as a, Welt(a) as welt:
                body = {"model": MODELL, "max_tokens": 64000, "messages": [], "metadata": {"user_id": "u1", "tags": ["cloud"]},
                        "context_management": {"edits": []}, "output_config": {}, "thinking": {"type": "disabled"}}
                status, _, _ = await welt.anfrage(body=body)
                self.assertEqual(status, 200)
                weiter = json.loads(a.anfragen[0][1])
                self.assertEqual(weiter["metadata"], {"user_id": "u1"})
                self.assertEqual(weiter["max_tokens"], X.MAX_AUSGABE_TOKEN)
                laenge = next(z.split(":")[1] for z in a.anfragen[0][0].split("\r\n") if z.startswith("Content-Length"))
                self.assertEqual(int(laenge), len(a.anfragen[0][1]))
        lauf(t())

    def test_abbruch_wird_geschaetzt_gebucht(self):
        async def t():
            async with Attrappe("abbruch") as a, Welt(a) as welt:
                await welt.anfrage(body={"model": MODELL, "max_tokens": 5000, "stream": True,
                                         "messages": [{"role": "user", "content": "x" * 3000}]})
                self.assertEqual(len(a.anfragen), 1)
                self.assertGreaterEqual(welt.verbrauch.je_auftrag.get(JOB, 0), 5000 + 1000)
                self.assertTrue(any("abbruch" in z and "geschaetzt=ja" in z for z in welt.log))
        lauf(t())

    def test_ohne_usage_wird_geschaetzt(self):
        async def t():
            async with Attrappe("ohne_usage") as a, Welt(a) as welt:
                status, _, _ = await welt.anfrage(body={"model": MODELL, "max_tokens": 8,
                                                        "messages": [{"role": "user", "content": "y" * 900}]})
                self.assertEqual(status, 200)
                self.assertGreater(welt.verbrauch.je_auftrag.get(JOB, 0), 300)
        lauf(t())

    def test_litellm_nicht_erreichbar(self):
        async def t():
            async with Attrappe() as a:
                port = a.port
            welt = Welt(a)
            async with welt:
                welt.proxy.ziel = X.Ziel("127.0.0.1", port, "")
                status, _, _ = await welt.anfrage()
                self.assertEqual(status, 502)
        lauf(t())


class Grenzen(unittest.TestCase):
    def test_budget_auftrag(self):
        async def t():
            async with Attrappe("sse") as a, Welt(a, max_token=1000) as welt:
                self.assertEqual((await welt.anfrage())[0], 200)  # 1542 Token: danach ist das Budget weg
                status, _, body = await welt.anfrage()
                self.assertEqual(status, 403)
                self.assertIn("Budget", json.loads(body)["error"]["message"])
                self.assertEqual(len(a.anfragen), 1)
        lauf(t())

    def test_budget_tag(self):
        async def t():
            async with Attrappe("sse") as a, Welt(a, tag_token_max=10_000) as welt:
                welt.verbrauch.je_tag[X.Verbrauch.tag(time.time())] = 10_000
                self.assertEqual((await welt.anfrage())[0], 403)
                self.assertEqual(a.anfragen, [])
        lauf(t())

    def test_gleichzeitigkeit(self):
        async def t():
            tor = asyncio.Event()
            async with Attrappe("json", warten=tor) as a, Welt(a, parallel=1, warte_s=0.3) as welt:
                erste = asyncio.ensure_future(welt.anfrage())
                while not a.anfragen:
                    await asyncio.sleep(0.01)
                status, kopf, _ = await welt.anfrage()
                self.assertEqual(status, 429)
                self.assertEqual(kopf.get("retry-after"), "10")
                tor.set()
                self.assertEqual((await erste)[0], 200)
                self.assertEqual(len(a.anfragen), 1)
        lauf(t())

    def test_budget_profil(self):
        async def t():
            async with Attrappe("sse") as a, Welt(a) as welt:
                welt.proxy.profil_tag_token_max = 100
                welt.verbrauch.je_profil_tag[("1a2b3c4d", X.Verbrauch.tag(time.time()))] = 100
                status, _, body = await welt.anfrage()
                self.assertEqual(status, 403)
                self.assertIn("Profil", json.loads(body)["error"]["message"])
                self.assertEqual(a.anfragen, [])
        lauf(t())

    def test_verbindungen_begrenzt(self):
        async def t():
            tor = asyncio.Event()
            async with Attrappe("json", warten=tor) as a, Welt(a, parallel=2, warte_s=5) as welt:
                laufend = [asyncio.ensure_future(welt.anfrage()) for _ in range(X.VERBINDUNGEN_JE_AUFTRAG)]
                while len(a.anfragen) < 2:
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.1)
                status, _, body = await welt.anfrage()
                self.assertEqual(status, 429)
                self.assertIn("dieses Auftrags", json.loads(body)["error"]["message"])
                welt.proxy._verbindungen_max = welt.proxy._offen
                status, _, body = await welt.anfrage(token=None)
                self.assertEqual(status, 429)
                tor.set()
                self.assertEqual([(await f)[0] for f in laufend], [200] * X.VERBINDUNGEN_JE_AUFTRAG)
        lauf(t())

    def test_verbrauch_nach_neustart(self):
        with tempfile.TemporaryDirectory() as d:
            pfad = Path(d) / "verbrauch.jsonl"
            v = X.Verbrauch(pfad)
            jetzt = time.time()
            v.buchen({"zeit": int(jetzt), "tag": X.Verbrauch.tag(jetzt), "job": JOB, "profil": "1a2b3c4d", "weg": "/v1/messages",
                      "modell": MODELL, "status": 200, "ein": 10, "aus": 5, "ms": 1})
            with open(pfad, "a", encoding="utf-8") as f:
                f.write("kaputt\n")
            neu = X.Verbrauch(pfad)
            neu.laden()
            self.assertEqual(neu.je_auftrag[JOB], 15)
            self.assertEqual(neu.je_tag[X.Verbrauch.tag(jetzt)], 15)


class Aufbau(unittest.TestCase):
    def test_nur_loopback(self):
        async def t():
            p = X.Proxy(X.Ziel("127.0.0.1", 1, ""), SCHLUESSEL, frozenset({MODELL}), Path("."), X.Verbrauch(None))
            with self.assertRaises(ValueError):
                await X.serve(p, "0.0.0.0", 0)
        lauf(t())

    def test_ziel_url(self):
        z = X.Ziel.aus_url("http://192.168.178.75:4000")
        self.assertEqual((z.host, z.port, z.basis), ("192.168.178.75", 4000, ""))
        for falsch in ("https://192.168.178.75:4000", "http://nutzer:pw@192.168.178.75:4000", "http://192.168.178.75:4000/?a=1", "ftp://x"):
            with self.assertRaises(ValueError):
                X.Ziel.aus_url(falsch)

    def test_schluessel_und_modelle(self):
        with self.assertRaises(ValueError):
            X.Proxy(X.Ziel("127.0.0.1", 1, ""), "", frozenset({MODELL}), Path("."), X.Verbrauch(None))
        with self.assertRaises(ValueError):
            X.Proxy(X.Ziel("127.0.0.1", 1, ""), "a\r\nb", frozenset({MODELL}), Path("."), X.Verbrauch(None))
        with self.assertRaises(ValueError):
            X.Proxy(X.Ziel("127.0.0.1", 1, ""), SCHLUESSEL, frozenset(), Path("."), X.Verbrauch(None))
        p = X.Proxy(X.Ziel("127.0.0.1", 1, ""), SCHLUESSEL, frozenset({MODELL}), Path("."), X.Verbrauch(None))
        self.assertNotIn(SCHLUESSEL, repr(p))

    def test_schluessel_lesen(self):
        with tempfile.TemporaryDirectory() as d:
            pfad = Path(d) / "litellm.key"
            pfad.write_text(SCHLUESSEL + "\n", encoding="utf-8")
            self.assertEqual(X.schluessel_lesen(str(pfad)), SCHLUESSEL)
            pfad.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                X.schluessel_lesen(str(pfad))


class Zaehlung(unittest.TestCase):
    def test_sse_in_kleinen_stuecken(self):
        z = X.Zaehler(True)
        for i in range(len(SSE)):
            z.futter(SSE[i:i + 1])
        z.ende()
        self.assertEqual((z.ein, z.aus), (1500, 42))

    def test_keine_zahl_wirft_nicht(self):
        z = X.Zaehler(True)
        z.futter(b'data: {"type":"message_delta","usage":{"output_tokens":"viel"}}\n')
        z.futter(b'data: {"type":"message_start","message":{"usage":{"input_tokens":-5}}}\n')
        z.ende()
        self.assertEqual((z.ein, z.aus), (0, 0))

    def test_json_kaputt_zaehlt_null(self):
        z = X.Zaehler(False)
        z.futter(b"{kaputt")
        z.ende()
        self.assertEqual((z.ein, z.aus), (0, 0))


def _bash() -> str | None:
    import shutil
    return shutil.which("bash")


class SandboxAusnahme(unittest.TestCase):
    """Ausnahme der Sandbox (wamo-job.sh, wamo-egress.nft): genau ein Port, für Landlock nur bei ANTHROPIC_BASE_URL des Proxys."""

    def setUp(self):
        self.runner = (INFRA / "wamo-job.sh").read_text(encoding="utf-8")
        self.nft = (INFRA / "wamo-egress.nft").read_text(encoding="utf-8")

    def test_erlaubnisliste(self):
        import re
        erlaubt = re.search(r"ERLAUBT_RE='\^\(([^)]*)\)\$'", self.runner).group(1).split("|")
        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                     "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                     "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
            self.assertIn(name, erlaubt)
        for name in ("LITELLM_API_KEY", "ANTHROPIC_AUTH_TOKEN", "WAMO_HAUS"):
            self.assertNotIn(name, erlaubt)
        pruefen = re.search(r"ERLAUBT_PRUEFEN_RE='\^\(([^)]*)\)\$'", self.runner).group(1).split("|")
        self.assertFalse(any(n.startswith(("ANTHROPIC", "CLAUDE")) for n in pruefen))

    def test_ein_port_ueberall_gleich(self):
        self.assertIn("HAUS_PROXY_PORT=18090\n", self.runner)
        self.assertIn("\t\tip daddr 127.0.0.1 tcp dport 18090 accept\n", self.nft)
        self.assertEqual(self.nft.count("18090 accept"), 1)
        skript = (INFRA / "wamo-haus-proxy-einrichten.sh").read_text(encoding="utf-8")
        self.assertIn("LISTEN=127.0.0.1:18090\n", skript)
        # Die Ausnahme steht vor den Abweisungen von Loopback (intern4) und lokalen Adressen
        self.assertLess(self.nft.index("tcp dport 18090 accept"), self.nft.index("ip daddr @intern4 counter jump abweisen"))

    def _sperrports(self, base_url: str | None, **zusatz: str) -> tuple[int, str]:
        import re
        import subprocess
        haus = re.search(r"\nHAUS_PROXY_PORT=18090\n.*?\n# Gesperrte Ports", self.runner, re.S).group(0)
        frei = re.search(r"\nFREI_PORTS=.*?\n\)\n", self.runner, re.S).group(0)
        skript = ('fehler() { echo "FEHLER $*"; exit 70; }\nNETZ_SPERRPORTS="4000 8000 8001 11434"\nNETZ_IMMER_ERLAUBT="53 80 443"\n'
                  'HOST_PORTS="22\n53\n4000\n55443"\n' + haus + frei
                  + 'echo "$SPERRPORTS ${ANTHROPIC_DEFAULT_HAIKU_MODEL:-ohne_modell}"\n')
        weg = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_DEFAULT_HAIKU_MODEL")
        env = {k: v for k, v in os.environ.items() if k not in weg}
        if base_url is not None:
            env["ANTHROPIC_BASE_URL"] = base_url
        env.update(zusatz)
        r = subprocess.run([_bash(), "-c", skript], capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        return r.returncode, r.stdout.strip()

    @unittest.skipUnless(_bash(), "bash fehlt")
    def test_landlock_nur_bei_haus_offen(self):
        # Ohne Haus steht 18090 immer in der Sperre, auch wenn der Proxy gerade nicht lauscht; Modellnamen fürs Haus fallen weg
        code, ausgabe = self._sperrports(None, ANTHROPIC_DEFAULT_HAIKU_MODEL=MODELL)
        self.assertEqual(code, 0)
        ports, modell = ausgabe.split(" ")
        self.assertIn("18090", ports.split(","))
        self.assertEqual(modell, "ohne_modell")
        code, ausgabe = self._sperrports("http://127.0.0.1:18090", ANTHROPIC_API_KEY=TOKEN, ANTHROPIC_DEFAULT_HAIKU_MODEL=MODELL)
        self.assertEqual(code, 0, ausgabe)
        ports, modell = ausgabe.split(" ")
        self.assertNotIn("18090", ports.split(","))
        self.assertIn("4000", ports.split(","))  # LiteLLM-Port bleibt immer zu
        self.assertEqual(modell, MODELL)
        for falsch in ("http://192.168.178.75:4000", "https://api.anthropic.com", "http://127.0.0.1:18090/", "http://localhost:18090"):
            with self.subTest(url=falsch):
                code, ausgabe = self._sperrports(falsch, ANTHROPIC_API_KEY=TOKEN)
                self.assertEqual(code, 70)
                self.assertIn("nur für den Proxy der Hausmodelle", ausgabe)

    @unittest.skipUnless(_bash(), "bash fehlt")
    def test_haus_nur_mit_auftragstoken(self):
        url = "http://127.0.0.1:18090"
        for zusatz in ({}, {"ANTHROPIC_API_KEY": "sk-ant-api03-" + "x" * 40}, {"ANTHROPIC_API_KEY": TOKEN + "0"},
                       {"ANTHROPIC_API_KEY": TOKEN, "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "y" * 40},
                       {"ANTHROPIC_API_KEY": TOKEN, "ANTHROPIC_CUSTOM_HEADERS": "anthropic-workspace-id: w"}):
            with self.subTest(namen=sorted(zusatz)):
                code, ausgabe = self._sperrports(url, **zusatz)
                self.assertEqual(code, 70)
                self.assertIn("Hausmodelle:", ausgabe)


class DienstUndSkripte(unittest.TestCase):
    def test_unit(self):
        unit = (INFRA / "wamo-haus-proxy.service").read_text(encoding="utf-8")
        for zeile in ("User=wamo-haus-proxy", "LoadCredential=litellm.key:/etc/wamo-haus-proxy/litellm.key", "--schluessel-datei %d/litellm.key",
                      "ExecStartPre=/usr/bin/sha256sum -c --quiet SHA256SUMS", "NoNewPrivileges=yes", "ProtectSystem=strict",
                      "CapabilityBoundingSet=\n", "IPAddressDeny=any", "IPAddressAllow=127.0.0.0/8 192.168.178.75/32",
                      "--auftraege /run/wamo-haus", "ConditionPathExists=/etc/wamo-haus-proxy/litellm.key"):
            self.assertIn(zeile, unit)
        self.assertNotIn("Environment=LITELLM", unit)
        tmpfiles = (INFRA / "wamo-haus.tmpfiles").read_text(encoding="utf-8")
        self.assertIn("d /run/wamo-haus 2750 wamo wamo-haus-proxy - -", tmpfiles)
        skript = (INFRA / "wamo-haus-proxy-einrichten.sh").read_text(encoding="utf-8")
        self.assertIn("ZIEL=http://192.168.178.75:4000\n", skript)  # Hausregel: nur das zentrale LiteLLM, passend zu IPAddressAllow
        self.assertIn("MODELLE=qwen3.6-35b\n", skript)

    @unittest.skipUnless(_bash() and os.name == "posix", "nur unter Linux (Probelauf mit Pfaden ohne Laufwerk)")
    def test_probelauf_einrichten_und_schluessel(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "WAMO_HAUS_PROXY_WURZEL": d}
            skript = str(INFRA / "wamo-haus-proxy-einrichten.sh")
            r = subprocess.run([_bash(), skript, "einrichten", "--trocken"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(Path(d, "etc").exists())
            r = subprocess.run([_bash(), skript, "einrichten"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            konf = Path(d, "etc/wamo-haus-proxy/proxy.env").read_text(encoding="utf-8")
            self.assertIn("LISTEN=127.0.0.1:18090", konf)
            self.assertTrue(Path(d, "opt/wamo-haus-proxy/app/SHA256SUMS").is_file())
            self.assertTrue(Path(d, "etc/systemd/system/wamo-haus-proxy.service").is_file())
            self.assertFalse(Path(d, "etc/wamo-haus-proxy/litellm.key").exists())
            r = subprocess.run([_bash(), skript, "schluessel", "sk-als-argument"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("sk-als-argument", r.stdout + r.stderr)
            r = subprocess.run([_bash(), skript, "schluessel"], input="sk-test-geheim-123\n", capture_output=True, text=True, encoding="utf-8", env=env,
                               timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("sk-test-geheim-123", r.stdout + r.stderr)
            datei = Path(d, "etc/wamo-haus-proxy/litellm.key")
            self.assertEqual(datei.read_text(encoding="utf-8"), "sk-test-geheim-123\n")
            self.assertEqual(datei.stat().st_mode & 0o777, 0o400)


class Rauchtest(unittest.TestCase):
    def test_attrappe(self):
        import wamo_haus_proxy_rauchtest as R
        self.assertIsNone(asyncio.run(R.probe_attrappe()))


if __name__ == "__main__":
    unittest.main()
