#!/usr/bin/python3 -I
"""Rauchtest des Proxys für Entwicklungsaufträge mit Hausmodellen (wamo-haus-proxy, Paket P6a).

Aufruf am Server (als root, nach wamo-haus-proxy-einrichten.sh):
  python3 -I /opt/wamo-haus-proxy/app/wamo_haus_proxy_rauchtest.py                 Attrappe, Dienst, Rechte
  python3 -I /opt/wamo-haus-proxy/app/wamo_haus_proxy_rauchtest.py --nur-attrappe  nur die Attrappe (ohne laufenden Dienst)
  python3 -I /opt/wamo-haus-proxy/app/wamo_haus_proxy_rauchtest.py --echt          zusätzlich eine winzige echte Anfrage über LiteLLM
Proben:
  attrappe  Der Proxy-Code dieses Servers mit einer LiteLLM-Attrappe auf Loopback: Streaming kommt unverändert an, Token werden gezählt,
            Abweisungen (Weg, Token, Modell, Budget) gehen nie an die Attrappe. Kein Netz, kein Schlüssel.
  dienst    wamo-haus-proxy läuft, lauscht nur auf 127.0.0.1:18090, weist ohne Token (401), falschen Weg (404) und GET (405) ab.
  rechte    litellm.key root:root 0400 und für wamo unlesbar; /run/wamo-haus 2750 wamo:wamo-haus-proxy.
  echt      Tokendatei für einen Probe-Auftrag, eine Anfrage mit max_tokens 8 an wamo-haus-coder, 200 und message_stop, gezählte Token (nicht
            geschätzt) in verbrauch.jsonl, Datei wieder weg.
Ausgabe: je Probe eine Zeile OK oder FEHLER, nie ein Inhalt, nie ein Schlüssel. Exit 0 nur, wenn alle Proben bestehen.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_haus_proxy as X  # noqa: E402

PORT = 18090
MODELL = "wamo-haus-coder"  # das Modell des Dispatchers (HAUS_MODELL)
ORDNER = Path("/run/wamo-haus")
SCHLUESSEL_DATEI = Path("/etc/wamo-haus-proxy/litellm.key")
VERBRAUCH = Path("/var/lib/wamo-haus-proxy/verbrauch.jsonl")
SSE = (b"event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"usage\":{\"input_tokens\":10,\"output_tokens\":1}}}\n\n"
       b"event: message_delta\ndata: {\"type\":\"message_delta\",\"usage\":{\"output_tokens\":3}}\n\n"
       b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n")


async def _anfrage(port: int, token: str | None, *, weg="/v1/messages", methode="POST", modell=MODELL, stream=True,
                   max_tokens=8) -> tuple[int, bytes]:
    body = json.dumps({"model": modell, "max_tokens": max_tokens, "stream": stream,
                       "messages": [{"role": "user", "content": "Antworte nur mit: ok"}]}).encode()
    zeilen = [f"{methode} {weg} HTTP/1.1", "Host: 127.0.0.1", "Content-Type: application/json", f"Content-Length: {len(body)}",
              "anthropic-version: 2023-06-01"]
    if token:
        zeilen.append(f"x-api-key: {token}")
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(("\r\n".join(zeilen) + "\r\n\r\n").encode() + body)
    await w.drain()
    antwort = await asyncio.wait_for(r.read(), 180)
    w.close()
    kopf, _, rest = antwort.partition(b"\r\n\r\n")
    return int(kopf.split(b" ")[1]), rest


async def probe_attrappe() -> str | None:
    angekommen: list[bytes] = []

    async def litellm(r, w):
        kopf = await r.readuntil(b"\r\n\r\n")
        laenge = int(next(z.split(b":")[1] for z in kopf.split(b"\r\n") if z.lower().startswith(b"content-length")))
        angekommen.append(kopf + await r.readexactly(laenge))
        w.write(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n"
                + f"{len(SSE):x}\r\n".encode() + SSE + b"\r\n0\r\n\r\n")
        await w.drain()
        w.close()

    with tempfile.TemporaryDirectory() as d:
        attrappe = await asyncio.start_server(litellm, "127.0.0.1", 0)
        job = secrets.token_hex(10)
        token = f"wh1-{job}-{secrets.token_hex(32)}"
        (Path(d) / f"{job}.json").write_text(json.dumps({"v": 1, "job": job, "hash": hashlib.sha256(token.encode()).hexdigest(),
                                                         "profil": "0badc0de", "bis": int(time.time()) + 120, "max_token": 20}))
        proxy = X.Proxy(X.Ziel("127.0.0.1", attrappe.sockets[0].getsockname()[1], ""), "rauchtest-attrappe", frozenset({MODELL}),
                        Path(d), X.Verbrauch(None), protokoll=lambda _z: None)
        server = await X.serve(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            for erwartet, kw in ((404, {"weg": "/v1/models"}), (401, {"token": None}), (400, {"modell": "claude-sonnet-4-5"})):
                status, _ = await _anfrage(port, kw.pop("token", token), **kw)
                if status != erwartet:
                    return f"Abweisung: {status} statt {erwartet}"
            if angekommen:
                return "eine Abweisung ging an die Attrappe"
            status, body = await _anfrage(port, token)
            if status != 200 or b"message_stop" not in body:
                return f"Streaming: Status {status}"
            if b"Bearer rauchtest-attrappe" not in angekommen[0] or token.encode() in angekommen[0]:
                return "Schlüssel oder Token falsch weitergereicht"
            status, _ = await _anfrage(port, token)  # 13 Token gebucht, max_token 20: noch frei
            status, _ = await _anfrage(port, token)  # 26 gebucht: jetzt gesperrt
            if status != 403:
                return f"Budget: Status {status} statt 403"
        finally:
            for s in (server, attrappe):
                s.close()
                await s.wait_closed()
    return None


def probe_dienst() -> str | None:
    if subprocess.run(["systemctl", "is-active", "--quiet", "wamo-haus-proxy"]).returncode != 0:
        return "wamo-haus-proxy läuft nicht"
    ss = subprocess.run(["ss", "-tlnH", f"sport = :{PORT}"], capture_output=True, text=True).stdout.split()
    adressen = [t for t in ss if t.endswith(f":{PORT}")]
    if adressen != [f"127.0.0.1:{PORT}"]:
        return f"lauscht nicht genau auf 127.0.0.1:{PORT}: {adressen}"

    async def proben():
        for erwartet, kw in ((401, {"token": None}), (404, {"token": None, "weg": "/v1/models"}),
                             (405, {"token": None, "methode": "GET"}), (401, {"token": f"wh1-{'0' * 20}-{'0' * 64}"})):
            status, _ = await _anfrage(PORT, kw.pop("token"), **kw)
            if status != erwartet:
                return f"{kw}: {status} statt {erwartet}"
        return None
    return asyncio.run(proben())


def probe_rechte() -> str | None:
    import grp
    import pwd
    st = os.stat(SCHLUESSEL_DATEI)
    if st.st_uid != 0 or st.st_gid != 0 or stat.S_IMODE(st.st_mode) != 0o400:
        return "litellm.key ist nicht root:root 0400"
    if subprocess.run(["runuser", "-u", "wamo", "--", "test", "-r", str(SCHLUESSEL_DATEI)]).returncode == 0:
        return "wamo kann litellm.key lesen"
    st = os.stat(ORDNER)
    if (stat.S_IMODE(st.st_mode) != 0o2750 or pwd.getpwuid(st.st_uid).pw_name != "wamo"
            or grp.getgrgid(st.st_gid).gr_name != "wamo-haus-proxy"):
        return "/run/wamo-haus ist nicht 2750 wamo:wamo-haus-proxy"
    return None


def probe_echt() -> str | None:
    import grp
    import pwd
    job = "f" * 4 + secrets.token_hex(8)
    token = f"wh1-{job}-{secrets.token_hex(32)}"
    datei = ORDNER / f"{job}.json"
    inhalt = json.dumps({"v": 1, "job": job, "hash": hashlib.sha256(token.encode()).hexdigest(), "profil": "0badc0de",
                         "bis": int(time.time()) + 300, "max_token": 20000})
    wamo = pwd.getpwnam("wamo")
    fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        try:
            os.write(fd, inhalt.encode())
            os.fchown(fd, wamo.pw_uid, grp.getgrnam("wamo-haus-proxy").gr_gid)
        finally:
            os.close(fd)
        beginn = time.time()
        status, body = asyncio.run(_anfrage(PORT, token))
        if status != 200 or b"message_stop" not in body:
            return f"echte Anfrage: Status {status}"
        dauer = time.time() - beginn
        time.sleep(0.5)
        buchung = None
        with open(VERBRAUCH, "rb") as f:  # nur das Ende der Datei, sie wird nicht gedreht
            f.seek(max(0, os.fstat(f.fileno()).st_size - 65536))
            for zeile in f.read().splitlines()[-50:]:
                try:
                    e = json.loads(zeile)
                except ValueError:
                    continue
                if e.get("job") == job:
                    buchung = e
        if buchung is None or buchung.get("geschaetzt") or not (buchung.get("ein", 0) > 0 and buchung.get("aus", 0) > 0):
            return "echte Anfrage: Token nicht gezählt (usage fehlt in der Antwort von LiteLLM)"
        print(f"  echt: 200 in {dauer:.1f} s, gezählt {buchung['ein']} ein, {buchung['aus']} aus")
    finally:
        try:
            os.unlink(datei)
        except FileNotFoundError:
            pass
    return None


def main(argv: list[str]) -> int:
    proben = [("attrappe", lambda: asyncio.run(probe_attrappe()))]
    if "--nur-attrappe" not in argv:
        proben += [("dienst", probe_dienst), ("rechte", probe_rechte)]
        if "--echt" in argv:
            proben.append(("echt", probe_echt))
    fehler = 0
    for name, probe in proben:
        try:
            grund = probe()
        except Exception as e:  # noqa: BLE001
            grund = f"{type(e).__name__}"
        print(f"{'OK    ' if grund is None else 'FEHLER'} {name}{'' if grund is None else ': ' + grund}")
        fehler += grund is not None
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
