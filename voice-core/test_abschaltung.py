"""Tests der begrenzten Abschaltung des Kerns (abschaltung.py, R7: der Stopp beim Ausleiten lief am 16.11.2026 in TimeoutStopSec).

Nachgestellt wird der Fehlerfall vom 16.11.2026: Pipecats Lifespan schließt beim Herunterfahren alle Einträge seines
Verbindungsverzeichnisses. Ein alter Eintrag (pc_id vor einer Neuverhandlung mit Neustart) gehört zu einer Verbindung, deren Schließen in
aiortc auf einen Future wartet, der nie fertig wird. Ohne Frist hängt "Waiting for application shutdown" bis zum SIGKILL von systemd.

Ausführen:  uv run python -m pytest -q test_abschaltung.py   (in voice-core/)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from loguru import logger

import abschaltung
import kern_dienst
import wamo_api

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"


def _timeout_stop_sec(unit: Path) -> float:
    for zeile in unit.read_text(encoding="utf-8").splitlines():
        if zeile.strip().startswith("TimeoutStopSec="):
            return float(zeile.split("=", 1)[1].strip())
    raise AssertionError(f"{unit.name} ohne TimeoutStopSec")


@contextlib.contextmanager
def _meldungen():
    zeilen: list[str] = []
    kennung = logger.add(lambda m: zeilen.append(str(m)), level="WARNING", format="{level} {message}")
    try:
        yield zeilen
    finally:
        logger.remove(kennung)


class _HaengendeVerbindung:
    """Wie SmallWebRTCConnection nach dem abgebrochenen Schließen: disconnect() wartet auf einen Future, der nie fertig wird."""

    def __init__(self):
        self.versuche = 0
        self.abgebrochen = 0

    async def disconnect(self):
        self.versuche += 1
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            self.abgebrochen += 1
            raise


def _app_wie_im_kern(verbindung, aufgaben=()) -> FastAPI:
    """Zusammensetzung wie bot.py: erst wamo_api (Hintergrundaufgaben), dann der Runner mit seinem WebRTC-Lifespan."""
    from pipecat.runner.run import _add_lifespan_to_app
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler

    app = FastAPI()
    wamo_api._hintergrund_lifespan(app, list(aufgaben))
    handler = SmallWebRTCRequestHandler()
    # drei pc_ids, eine Verbindung: so sah das Verzeichnis nach drei Neuverhandlungen mit Neustart aus
    for pc_id in ("SmallWebRTCConnection#0-df5e07d0", "SmallWebRTCConnection#0-dcbfb870", "SmallWebRTCConnection#0-99c7a152"):
        handler._pcs_map[pc_id] = verbindung

    @contextlib.asynccontextmanager
    async def smallwebrtc_lifespan(_app):
        yield
        await handler.close()

    _add_lifespan_to_app(app, smallwebrtc_lifespan)
    return app


async def _lebenszyklus(app) -> float:
    beginn = time.monotonic()
    async with app.router.lifespan_context(app):
        pass
    return time.monotonic() - beginn


def test_fristen_bleiben_deutlich_unter_der_zeitgrenze_von_systemd():
    for unit in (INFRA / "wamo-core@.service", INFRA / "wamo-core.service"):
        grenze = _timeout_stop_sec(unit)
        # SIGTERM bis Prozessende im schlimmsten Fall: Verbindungen (uvicorn), dann spätestens die Notbremse; 5 s bleiben frei
        assert abschaltung.FRIST_VERBINDUNGEN_S + abschaltung.FRIST_NOTBREMSE_S <= grenze - 5, unit.name
    # nach dem Abbruch des Lifespans enden die eigenen Aufgaben noch geordnet, bevor die Notbremse greift
    assert abschaltung.FRIST_LIFESPAN_S + abschaltung.FRIST_AUFGABEN_S < abschaltung.FRIST_NOTBREMSE_S
    assert isinstance(abschaltung.FRIST_VERBINDUNGEN_S, int)   # uvicorn erwartet ganze Sekunden


async def test_ohne_frist_haengt_der_lifespan_wie_am_16_11():
    verbindung = _HaengendeVerbindung()
    app = _app_wie_im_kern(verbindung)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_lebenszyklus(app), timeout=0.5)
    assert verbindung.versuche == 3   # jeder alte Eintrag wird geschlossen, alle hängen an derselben Verbindung


async def test_haengende_verbindung_endet_nach_der_frist():
    verbindung = _HaengendeVerbindung()
    app = _app_wie_im_kern(verbindung)
    bremsen: list[str] = []
    abschaltung.lifespan_begrenzen(app, frist=0.2, notbremse=lambda: bremsen.append("an"))
    with _meldungen() as zeilen:
        dauer = await _lebenszyklus(app)
    assert dauer < 1.5
    assert bremsen == ["an"]   # die Notbremse wacht ab dem Beginn des Herunterfahrens
    assert verbindung.abgebrochen == 3
    assert any("nicht fertig" in z and "abgebrochen" in z for z in zeilen), zeilen


async def test_eigene_hintergrundaufgaben_enden_auch_nach_dem_abbruch_geordnet():
    beendet = asyncio.Event()

    async def aufgabe():
        try:
            await asyncio.sleep(3600)
        finally:
            beendet.set()

    app = _app_wie_im_kern(_HaengendeVerbindung(), [aufgabe])
    abschaltung.lifespan_begrenzen(app, frist=0.2, notbremse=lambda: None)
    assert await _lebenszyklus(app) < 1.5
    assert beendet.is_set()


async def test_geordneter_lifespan_bleibt_unveraendert():
    ablauf: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        ablauf.append("start")
        yield {"wert": 1}
        await asyncio.sleep(0)
        ablauf.append("ende")

    app = FastAPI(lifespan=lifespan)
    abschaltung.lifespan_begrenzen(app, frist=1.0, notbremse=lambda: ablauf.append("notbremse"))
    abschaltung.lifespan_begrenzen(app, frist=1.0, notbremse=lambda: ablauf.append("doppelt"))   # schachtelt nicht
    with _meldungen() as zeilen:
        async with app.router.lifespan_context(app) as zustand:
            assert zustand == {"wert": 1}
    assert ablauf == ["start", "notbremse", "ende"]
    assert zeilen == []


async def test_fehler_beim_start_wird_nicht_verschluckt():
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        raise RuntimeError("Start gescheitert")
        yield  # pragma: no cover

    app = FastAPI(lifespan=lifespan)
    abschaltung.lifespan_begrenzen(app, notbremse=lambda: None)
    with pytest.raises(RuntimeError, match="Start gescheitert"):
        async with app.router.lifespan_context(app):
            pass


async def test_fehler_beim_herunterfahren_wird_gemeldet_und_beendet_den_kern_nicht():
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        raise RuntimeError("geht nicht zu")

    app = FastAPI(lifespan=lifespan)
    abschaltung.lifespan_begrenzen(app, frist=1.0, notbremse=lambda: None)
    with _meldungen() as zeilen:
        await _lebenszyklus(app)
    assert any("RuntimeError" in z for z in zeilen), zeilen


async def test_aufgaben_beenden_wartet_hoechstens_die_frist():
    abbrueche = 0

    async def stur():
        nonlocal abbrueche
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                abbrueche += 1
                if abbrueche > 1:
                    raise   # erst der zweite Abbruch wirkt (Aufräumen im Test)

    async def brav():
        await asyncio.sleep(3600)

    t_stur, t_brav = asyncio.create_task(stur()), asyncio.create_task(brav())
    await asyncio.sleep(0)
    beginn = time.monotonic()
    with _meldungen() as zeilen:
        offen = await abschaltung.aufgaben_beenden([t_stur, t_brav], 0.2)
    assert time.monotonic() - beginn < 1.0
    assert offen == 1 and t_brav.cancelled() and not t_stur.done()
    assert any("1 Hintergrundaufgabe" in z for z in zeilen), zeilen
    t_stur.cancel()
    await asyncio.gather(t_stur, return_exceptions=True)
    assert await abschaltung.aufgaben_beenden([], 0.2) == 0


async def test_hintergrund_lifespan_von_wamo_api_ist_begrenzt(monkeypatch):
    monkeypatch.setattr(abschaltung, "FRIST_AUFGABEN_S", 0.2)
    weiter = asyncio.Event()

    async def stur():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await weiter.wait()   # ignoriert den Abbruch, bis der Test sie freigibt

    app = FastAPI()
    wamo_api._hintergrund_lifespan(app, [stur])
    try:
        assert await asyncio.wait_for(_lebenszyklus(app), timeout=2.0) < 1.0
    finally:
        weiter.set()
        await asyncio.sleep(0)


def test_notbremse_beendet_den_prozess_nach_der_frist():
    ausgeloest = threading.Event()
    codes: list[int] = []

    def beenden(code: int) -> None:
        codes.append(code)
        ausgeloest.set()

    with _meldungen() as zeilen:
        zeitgeber = abschaltung.notbremse_starten(0.05, beenden=beenden)
        assert zeitgeber.daemon   # hält das Ende des Prozesses nie auf
        assert ausgeloest.wait(2.0)
        zeitgeber.join(2.0)
    assert codes == [abschaltung.NOTBREMSE_EXIT] == [1]   # sichtbar: Result=exit-code statt success
    assert any("Notbremse" in z for z in zeilen), zeilen


def test_dienststart_begrenzt_verbindungen_und_lifespan(monkeypatch):
    monkeypatch.delenv("WAMO_CORE_UDS", raising=False)
    aufrufe: list[dict] = []
    runner = types.SimpleNamespace(uvicorn=types.SimpleNamespace(run=lambda app, **kw: aufrufe.append(kw)))
    kern_dienst.runner_vorbereiten(runner, lambda: None)
    import auth_gate

    app = FastAPI()
    auth_gate.install_access_gate(app)
    vorher = app.router.lifespan_context
    runner.uvicorn.run(app, host="localhost", port=7860)
    assert aufrufe == [{"host": "localhost", "port": 7860, "timeout_graceful_shutdown": abschaltung.FRIST_VERBINDUNGEN_S}]
    assert app.router.lifespan_context is not vorher
    assert getattr(app.router.lifespan_context, abschaltung.MARKE, False)


def test_zugangspruefung_bleibt_das_letzte_vor_dem_serverstart(monkeypatch):
    # Nach pruefe_zugang darf nichts mehr die App ändern (etwa die Middleware-Liste), sonst wäre die Prüfung wertlos
    monkeypatch.delenv("WAMO_CORE_UDS", raising=False)
    ablauf: list[str] = []
    monkeypatch.setattr(abschaltung, "lifespan_begrenzen", lambda app: ablauf.append("lifespan"))
    monkeypatch.setattr(kern_dienst, "pruefe_zugang", lambda app: ablauf.append("zugang"))
    runner = types.SimpleNamespace(uvicorn=types.SimpleNamespace(run=lambda app, **kw: ablauf.append("start")))
    kern_dienst.runner_vorbereiten(runner, lambda: ablauf.append("logging"))
    runner.uvicorn.run(FastAPI(), host="localhost", port=7860)
    assert ablauf == ["logging", "lifespan", "zugang", "start"]


async def test_standardverdrahtung_startet_die_notbremse(monkeypatch):
    gestartet: list[str] = []
    monkeypatch.setattr(abschaltung, "notbremse_starten", lambda: gestartet.append("an"))
    app = FastAPI()
    abschaltung.lifespan_begrenzen(app)
    await _lebenszyklus(app)
    assert gestartet == ["an"]


async def test_ohne_notbremse_laeuft_das_aufraeumen_trotzdem():
    ablauf: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        ablauf.append("aufgeraeumt")

    def kaputt():
        raise RuntimeError("can't start new thread")

    app = FastAPI(lifespan=lifespan)
    abschaltung.lifespan_begrenzen(app, notbremse=kaputt)
    with _meldungen() as zeilen:
        await _lebenszyklus(app)
    assert ablauf == ["aufgeraeumt"]
    assert any("Notbremse nicht gestartet" in z for z in zeilen), zeilen


async def test_ausnahme_im_betrieb_erreicht_den_inneren_lifespan():
    gesehen: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        except RuntimeError as e:
            gesehen.append(str(e))
            raise

    app = FastAPI(lifespan=lifespan)
    abschaltung.lifespan_begrenzen(app, notbremse=lambda: None)
    with pytest.raises(RuntimeError, match="im Betrieb"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("im Betrieb")
    assert gesehen == ["im Betrieb"]


DIENST = """
import asyncio, contextlib, sys, types
sys.path.insert(0, sys.argv[2])
import uvicorn
from fastapi import FastAPI
import abschaltung, kern_dienst

abschaltung.FRIST_VERBINDUNGEN_S = 1
abschaltung.FRIST_LIFESPAN_S = 0.5
abschaltung.FRIST_NOTBREMSE_S = 2.0
kern_dienst.pruefe_zugang = lambda app: None   # hier geht es nur um das Herunterfahren

@contextlib.asynccontextmanager
async def lifespan(app):
    yield
    if sys.argv[1] == "haengt":      # wie das close() von aiortc am 16.11.: wartet, nimmt den Abbruch aber an
        await asyncio.get_running_loop().create_future()
    while sys.argv[1] == "stur":     # nimmt den Abbruch nie an: nur die Notbremse beendet den Prozess
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

runner = types.SimpleNamespace(uvicorn=uvicorn)
kern_dienst.runner_vorbereiten(runner, lambda: None)
runner.uvicorn.run(FastAPI(lifespan=lifespan), host="127.0.0.1", port=0, log_level="info")
"""


@pytest.mark.skipif(os.name != "posix", reason="SIGTERM wie von systemd nur unter Linux")
# uvicorn löst das SIGTERM am Ende erneut aus: ein geordnetes Ende ist "durch SIGTERM beendet" (-15, für systemd sauber),
# die Notbremse endet mit Exit 1
@pytest.mark.parametrize("art,code,meldung", [("haengt", -signal.SIGTERM, "nicht fertig"), ("stur", 1, "Notbremse")])
def test_echter_dienst_endet_nach_sigterm_innerhalb_der_fristen(tmp_path, art, code, meldung):
    skript = tmp_path / "dienst.py"
    skript.write_text(DIENST, encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(skript), art, str(Path(__file__).resolve().parent)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    zeilen: list[str] = []
    bereit = threading.Event()

    def lesen():
        for zeile in p.stdout:
            zeilen.append(zeile)
            if "Uvicorn running" in zeile:
                bereit.set()

    leser = threading.Thread(target=lesen, daemon=True)
    leser.start()
    try:
        assert bereit.wait(30), "".join(zeilen)
        beginn = time.monotonic()
        p.send_signal(signal.SIGTERM)
        rc = p.wait(timeout=15)
        dauer = time.monotonic() - beginn
    finally:
        if p.poll() is None:
            p.kill()
    leser.join(5)
    ausgabe = "".join(zeilen)
    assert rc == code, ausgabe
    assert meldung in ausgabe, ausgabe
    assert dauer < 6, ausgabe   # Fristen hier 1 + 2 s; in Betrieb 4 + 9 s gegen TimeoutStopSec=20
