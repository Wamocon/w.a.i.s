"""Tests der Prüfliste der Ersteinrichtung (einrichtung_api.py, Planpapier docs/ausrollen-neue-nutzer.md 4.3): jeder Punkt grün und
nicht grün mit Attrappen, Laborprofil ohne Abfrage einer Quelle, ohne Identität keine Abfrage, Zwischenspeicher von 10 Sekunden, keine
Geheimnisse und keine Pfade in der Antwort, nie ein MCP-Start oder Werkzeugaufruf und kein Byte an den Socket des Laptops.

Ohne Datenbank, Netz und Socket. Ausführen:  uv run python -m pytest -q test_einrichtung_api.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass

import anyio
import asyncpg
import httpcore
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import einrichtung_api as api
import geraete_register as gr
import modellzugang as mz
import pc_geraet
import pc_host
import pc_tunnel
from auth_gate import Identity

ADMIN = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
MITGLIED = "5b3f1c2d-8e7a-4b6c-9d0e-1f2a3b4c5d6e"
STAND = "/wamo/api/einrichtung/stand"
FINGERABDRUCK = "SHA256:" + "Q" * 43
GERAET = gr.Geraet("7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f", "pc-niko", 7, "Laptop Niko", "WMC-TEST-01", FINGERABDRUCK)
TOKEN = "T" * 43 + "geheim"
FREIGABE = "F" * 43 + "geheim"
SONIOX = "soniox-geheim-0815"
ECHT = {name: getattr(api, name) for name in ("soniox_gesetzt", "dateien_pruefen", "gegenstelle_pruefen", "GEGENSTELLE")}
IDS = ["passwort", "geraet", "tunnel", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"]


@dataclass(frozen=True)
class ErstIdentity(Identity):
    """Identität mit dem Stand der Erstanmeldung, wie ihn Paket P1b anhängen wird."""

    erstanmeldung: object = None


def stand_von(art="claude", quelle="profil", stt="soniox", tts="soniox", code=False) -> mz.Stand:
    return mz.Stand(art=art, quelle=quelle, hinterlegt=quelle == "profil", ende="abcd" if quelle == "profil" else None,
                    geprueft=None, festgelegt=quelle == "festgelegt", modell="Claude Haiku", stt=stt, tts=tts,
                    code_hinterlegt=code)


def _wert(wert):
    if isinstance(wert, BaseException):
        raise wert
    return wert


class Quellen:
    """Attrappen aller Quellen der Prüfliste. Zählt jeden Aufruf; Werte oder Ausnahmen setzt der Test."""

    def __init__(self):
        self.aufrufe: list[str] = []
        self.geraet: object = GERAET
        self.status: object = frozenset()
        self.dateien: object = ("/run/wamo-pc/t07/pc.sock", 1007)
        self.socket: object = None
        self.stand: object = stand_von(code=True)
        self.soniox: object = True
        self.abdruck: object = True
        self.problem: object = None

    def installieren(self, monkeypatch) -> None:
        q = self

        def merken(name, wert):
            q.aufrufe.append(name)
            return _wert(wert)

        async def aktives_geraet(_uid):
            return merken("aktives_geraet", q.geraet)

        async def geraete_status(_uid):
            return merken("geraete_status", q.status)

        async def dateien_pruefen(geraet):
            assert geraet == GERAET  # nur das eigene Gerät
            return merken("dateien_pruefen", q.dateien)

        async def gegenstelle_pruefen(_pfad, _uid):
            return merken("gegenstelle_pruefen", q.socket)

        async def modellzugang_stand(_uid):
            return merken("modellzugang_stand", q.stand)

        async def abdruck_vorhanden(_uid):
            return merken("abdruck_vorhanden", q.abdruck)

        for name, f in (("aktives_geraet", aktives_geraet), ("geraete_status", geraete_status),
                        ("dateien_pruefen", dateien_pruefen), ("gegenstelle_pruefen", gegenstelle_pruefen),
                        ("modellzugang_stand", modellzugang_stand), ("abdruck_vorhanden", abdruck_vorhanden),
                        ("soniox_gesetzt", lambda: merken("soniox_gesetzt", q.soniox)),
                        ("entwicklung_problem", lambda: merken("entwicklung_problem", q.problem))):
            monkeypatch.setattr(api, name, f)


class Uhr:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def umgebung(monkeypatch):
    for name, wert in (("WAMO_BETRIEB", "buero"), ("WAMO_PC_REGISTER", "an"), ("WAMO_PC_HOST", "on"),
                       ("WAMO_ENTWICKLUNG_BUERO", "an"), ("WAMO_ENTWICKLUNG_PROFILE", ADMIN)):
        monkeypatch.setenv(name, wert)
    for name in ("WAMO_PC_MITGLIEDER", "WAMO_STT_ANBIETER", "WAMO_TTS_ANBIETER", "WAMO_PC_SOCKET_WURZEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def quellen(monkeypatch, umgebung):
    q = Quellen()
    q.installieren(monkeypatch)
    api._zwischenspeicher.clear()
    api._laufend.clear()
    uhr = Uhr()
    monkeypatch.setattr(api, "_uhr", uhr)
    q.uhr = uhr
    return q


class Ctx:
    def __init__(self):
        self.ich: Identity = Identity(ADMIN, "Niko", "admin", "du")


@pytest.fixture
def ctx(monkeypatch, quellen):
    k = Ctx()

    async def identitaet(_request):
        return k.ich

    monkeypatch.setattr(api, "identitaet", identitaet)
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    k.client = TestClient(app)
    return k


def punkte(ctx) -> dict[str, tuple[str, str]]:
    r = ctx.client.get(STAND)
    assert r.status_code == 200, r.text
    return {p["id"]: (p["stufe"], p["text"]) for p in r.json()["punkte"]}


def neu(ctx, quellen) -> dict[str, tuple[str, str]]:
    """Zweite Abfrage nach Ablauf des Zwischenspeichers."""
    quellen.uhr.t += api.ZWISCHENSPEICHER_SECS + 1
    return punkte(ctx)


# ---------- Vertrag ----------
def test_vertrag_reihenfolge_form_und_alles_gruen_fuer_admin(ctx):
    r = ctx.client.get(STAND)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert set(d) == {"punkte", "geprueft"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", d["geprueft"])
    assert [p["id"] for p in d["punkte"]] == IDS == list(api.PUNKTE)
    for p in d["punkte"]:
        assert set(p) == {"id", "stufe", "text"}
        assert p["stufe"] == "gruen", p
        assert isinstance(p["text"], str) and p["text"].strip() and p["text"][-1] in ".?"


def test_alle_saetze_ohne_gedankenstrich_und_mit_satzende():
    saetze = [w for n, w in vars(api).items() if n.startswith("SATZ_") and isinstance(w, str)]
    assert len(saetze) >= 30
    for s in saetze:
        assert "–" not in s and "—" not in s and " - " not in s, s
        assert s[-1] in ".?" and "/" not in s, s


def test_modul_ist_im_kern_eingehaengt():
    import wamo_api

    assert "einrichtung_api" in wamo_api.ROUTEN_MODULE


# ---------- passwort ----------
@pytest.mark.parametrize("wert,stufe,text", [
    (None, "gruen", api.SATZ_PASSWORT_KEINE), ("keine", "gruen", api.SATZ_PASSWORT_KEINE),
    ("erledigt", "gruen", api.SATZ_PASSWORT_OK), ("offen", "rot", "Bitte zuerst dein Passwort ändern."),
    ("abgelaufen", "rot", "Bitte zuerst dein Passwort ändern."), (1, "rot", "Bitte zuerst dein Passwort ändern."),
])
def test_passwort(ctx, wert, stufe, text):
    ctx.ich = ErstIdentity(ADMIN, "Niko", "admin", "du", erstanmeldung=wert)
    assert punkte(ctx)["passwort"] == (stufe, text)


def test_passwort_ohne_feld_der_identitaet_ist_keine():
    assert api.erstanmeldung_stand(Identity(ADMIN, "Niko", "admin", "du")) is None


# ---------- geraet ----------
@pytest.mark.parametrize("status,text", [
    (frozenset({"beantragt"}), "Dein Laptop wartet auf die Freigabe durch einen Admin."),
    (frozenset({"widerrufen", "beantragt"}), "Dein Laptop wartet auf die Freigabe durch einen Admin."),
    (frozenset(), "Dein Laptop ist noch nicht eingerichtet. Melde dich in der Desktop-App an."),
    (frozenset({"widerrufen"}), "Dein Laptop ist noch nicht eingerichtet. Melde dich in der Desktop-App an."),
    (frozenset({"gesperrt"}), api.SATZ_GERAET_GESPERRT),
])
def test_geraet_ohne_aktives_geraet_ist_rot(ctx, quellen, status, text):
    quellen.geraet, quellen.status = None, status
    p = punkte(ctx)
    assert p["geraet"] == ("rot", text)
    assert p["tunnel"] == ("rot", api.SATZ_TUNNEL_OHNE_GERAET) and p["pc"][0] == "rot"
    assert "dateien_pruefen" not in quellen.aufrufe and "gegenstelle_pruefen" not in quellen.aufrufe


def test_geraet_gruen(ctx, quellen):
    assert punkte(ctx)["geraet"] == ("gruen", api.SATZ_GERAET_OK)
    assert "geraete_status" not in quellen.aufrufe


@pytest.mark.parametrize("fehler", [gr.RegisterFehler("Register nicht erreichbar (X)"), ValueError("WAMO_DB_SCHEMA"), TimeoutError()])
def test_geraet_register_nicht_lesbar(ctx, quellen, fehler):
    quellen.geraet = fehler
    p = punkte(ctx)
    assert p["geraet"] == ("rot", api.SATZ_GERAET_FEHLER)
    assert p["tunnel"] == ("rot", api.SATZ_TUNNEL_UNKLAR) and p["pc"][0] == "rot"


def test_geraet_status_nicht_lesbar(ctx, quellen):
    quellen.geraet, quellen.status = None, asyncpg.PostgresError("permission denied for table devices")
    p = punkte(ctx)
    assert p["geraet"] == ("rot", api.SATZ_GERAET_FEHLER)
    assert "permission" not in str(p)


# ---------- tunnel ----------
def test_tunnel_gruen_prueft_dateien_und_gegenstelle(ctx, quellen):
    assert punkte(ctx)["tunnel"] == ("gruen", api.SATZ_TUNNEL_OK)
    assert quellen.aufrufe.count("dateien_pruefen") == 1 and quellen.aufrufe.count("gegenstelle_pruefen") == 1


@pytest.mark.parametrize("feld,fehler", [
    ("dateien", pc_geraet.PcGeraetFehler("Geräteordner fehlt (Tunnel steht nicht)")),
    ("dateien", pc_geraet.PcGeraetFehler("Der Tunnel nutzt nicht den Schlüssel, den das Register für dieses Gerät führt")),
    ("dateien", TimeoutError()),
    ("socket", pc_tunnel.GegenstelleFalsch("Gegenstelle gehört nicht dem erwarteten Benutzer")),
    ("socket", httpcore.ConnectError("No such file or directory")),
    ("socket", OSError("Connection refused")),
])
def test_tunnel_rot(ctx, quellen, feld, fehler):
    setattr(quellen, feld, fehler)
    p = punkte(ctx)
    assert p["tunnel"] == ("rot", "Der Tunnel steht nicht. Bist du im Büronetz?")
    assert p["geraet"][0] == "gruen"
    assert p["pc"] == ("rot", api.SATZ_PC_NICHT_ERREICHBAR)


def test_tunnel_ohne_register_modus(ctx, quellen, monkeypatch):
    monkeypatch.setenv("WAMO_PC_REGISTER", "aus")
    p = punkte(ctx)
    assert p["tunnel"] == ("rot", api.SATZ_TUNNEL_AUS)
    assert "dateien_pruefen" not in quellen.aufrufe and "gegenstelle_pruefen" not in quellen.aufrufe


# ---------- stimme ----------
def test_stimme_gruen(ctx):
    assert punkte(ctx)["stimme"] == ("gruen", api.SATZ_STIMME_OK)


def test_stimme_ohne_schluessel_am_server(ctx, quellen):
    quellen.soniox = False
    assert punkte(ctx)["stimme"] == ("rot", "Die Stimme ist am Server nicht eingerichtet.")


@pytest.mark.parametrize("stt,tts", [("haus", "soniox"), ("soniox", "haus"), ("haus", "haus")])
def test_stimme_profil_im_haus(ctx, quellen, stt, tts):
    quellen.stand = stand_von(stt=stt, tts=tts)
    assert punkte(ctx)["stimme"] == ("hinweis", api.SATZ_STIMME_HAUS)


def test_stimme_im_haus_braucht_keinen_soniox_schluessel(ctx, quellen):
    quellen.soniox, quellen.stand = False, stand_von(stt="haus", tts="haus")
    assert punkte(ctx)["stimme"] == ("hinweis", api.SATZ_STIMME_HAUS)
    assert "soniox_gesetzt" not in quellen.aufrufe
    quellen.stand = stand_von(stt="haus", tts="soniox")  # ein Baustein auf Soniox braucht den Schlüssel
    assert neu(ctx, quellen)["stimme"] == ("rot", api.SATZ_STIMME_FEHLT)


def test_stimme_umgebung_ueberstimmt_das_profil(ctx, monkeypatch):
    monkeypatch.setenv("WAMO_TTS_ANBIETER", "haus")
    assert punkte(ctx)["stimme"] == ("hinweis", api.SATZ_STIMME_HAUS)


def test_stimme_schluessel_nur_ob_nie_der_wert(monkeypatch):
    monkeypatch.setenv("SONIOX_API_KEY", SONIOX)
    assert ECHT["soniox_gesetzt"]() is True
    monkeypatch.setenv("SONIOX_API_KEY", "  ")
    assert ECHT["soniox_gesetzt"]() is False
    monkeypatch.delenv("SONIOX_API_KEY")
    assert ECHT["soniox_gesetzt"]() is False


# ---------- gespraech ----------
@pytest.mark.parametrize("art,quelle,stufe,text", [
    ("claude", "profil", "gruen", api.SATZ_GESPRAECH_OK),
    ("haus", "keiner", "hinweis", "Ohne eigenen Schlüssel spricht W.A.I.S. mit den Hausmodellen."),
    ("haus", "wahl", "hinweis", api.SATZ_GESPRAECH_WAHL),
    ("haus", "festgelegt", "hinweis", api.SATZ_GESPRAECH_FESTGELEGT),
    ("claude", "zuordnung", "hinweis", api.SATZ_GESPRAECH_ZUORDNUNG),
])
def test_gespraech(ctx, quellen, art, quelle, stufe, text):
    quellen.stand = stand_von(art=art, quelle=quelle)
    assert punkte(ctx)["gespraech"] == (stufe, text)


def test_modellzugang_nicht_lesbar(ctx, quellen):
    quellen.stand = asyncpg.PostgresError('relation "wamo_test.model_access" does not exist')
    p = punkte(ctx)
    assert p["gespraech"] == ("rot", api.SATZ_GESPRAECH_UNKLAR)
    assert p["stimme"] == ("rot", api.SATZ_STIMME_UNKLAR)
    assert p["entwicklung"] == ("rot", api.SATZ_ENT_UNKLAR)
    assert "model_access" not in str(p)


# ---------- entwicklung ----------
def test_entwicklung_gruen_mit_eigenem_token(ctx):
    assert punkte(ctx)["entwicklung"] == ("gruen", api.SATZ_ENT_OK)


def test_entwicklung_gruen_mit_eigenem_api_schluessel(ctx, quellen):
    quellen.stand = stand_von(code=False)
    assert punkte(ctx)["entwicklung"] == ("gruen", api.SATZ_ENT_OK)


def test_entwicklung_mitglied_ist_hinweis_ohne_quellen(ctx, quellen):
    ctx.ich = Identity(MITGLIED, "Mitglied", "mitglied", "du")
    assert punkte(ctx)["entwicklung"] == ("hinweis", "Entwicklungsaufträge sind für dein Profil noch nicht freigeschaltet.")
    assert "entwicklung_problem" not in quellen.aufrufe


@pytest.mark.parametrize("schalter,text", [
    ("aus", "Der Schalter für Entwicklungsaufträge im Büro ist aus."),
    ("vielleicht", "Der Schalter für Entwicklungsaufträge im Büro ist ungültig."),
])
def test_entwicklung_schalter(ctx, monkeypatch, schalter, text):
    monkeypatch.setenv("WAMO_ENTWICKLUNG_BUERO", schalter)
    assert punkte(ctx)["entwicklung"] == ("rot", text)


def test_entwicklung_problem_ohne_werte_und_namen(ctx, quellen):
    quellen.problem = "WAMO_ENTWICKLUNG_KOSTEN_TAG_USD fehlt oder ist ungültig (positive Zahl mit Punkt)"
    stufe, text = punkte(ctx)["entwicklung"]
    assert (stufe, text) == ("rot", api.SATZ_ENT_PROBLEM) and "WAMO_" not in text


def test_entwicklung_profil_nicht_in_der_liste(ctx, monkeypatch):
    monkeypatch.setenv("WAMO_ENTWICKLUNG_PROFILE", MITGLIED)
    assert punkte(ctx)["entwicklung"] == ("rot", "Dieses Profil ist für Entwicklungsaufträge im Büro nicht freigegeben.")


@pytest.mark.parametrize("stand", [stand_von(art="haus", quelle="keiner"), stand_von(art="claude", quelle="zuordnung"),
                                   stand_von(art="haus", quelle="wahl", code=True),
                                   stand_von(art="haus", quelle="festgelegt", code=True)])
def test_entwicklung_ohne_eigenen_zugang_im_buero(ctx, quellen, stand):
    quellen.stand = stand
    assert punkte(ctx)["entwicklung"] == ("rot", api.SATZ_ENT_KEIN_ZUGANG)


def test_entwicklung_unterwegs_wie_heute(ctx, quellen, monkeypatch):
    monkeypatch.delenv("WAMO_BETRIEB")
    monkeypatch.delenv("WAMO_ENTWICKLUNG", raising=False)
    assert punkte(ctx)["entwicklung"] == ("rot", api.SATZ_ENT_AUS)
    monkeypatch.setenv("WAMO_ENTWICKLUNG", "an")
    quellen.stand = stand_von(art="claude", quelle="zuordnung")  # unterwegs gilt der Übergang wie bisher
    assert neu(ctx, quellen)["entwicklung"] == ("gruen", api.SATZ_ENT_OK)
    quellen.stand = stand_von(art="haus", quelle="keiner")
    assert neu(ctx, quellen)["entwicklung"] == ("rot", api.SATZ_ENT_KEIN_ZUGANG)


def test_entwicklung_pruefung_wirft(ctx, quellen):
    quellen.problem = RuntimeError("kaputt")
    assert punkte(ctx)["entwicklung"] == ("rot", api.SATZ_ENT_UNKLAR)


async def test_entwicklung_problem_laeuft_nicht_in_der_ereignisschleife(quellen, monkeypatch):
    faeden: list[int] = []
    monkeypatch.setattr(api, "entwicklung_problem", lambda: faeden.append(threading.get_ident()))  # liest am Server Dateien
    stand = await api.stand_fuer(Identity(ADMIN, "Niko", "admin", "du"))
    assert stand["punkte"][5]["stufe"] == "gruen" and faeden and faeden[0] != threading.get_ident()


# ---------- stimmabdruck ----------
@pytest.mark.parametrize("wert,stufe,text", [
    (True, "gruen", api.SATZ_ABDRUCK_OK),
    (False, "hinweis", "Ohne Stimmabdruck nimmt W.A.I.S. PC-Befehle nur getippt an."),
    (None, "rot", api.SATZ_ABDRUCK_UNKLAR),
    (asyncpg.PostgresError("speakers"), "rot", api.SATZ_ABDRUCK_UNKLAR),
])
def test_stimmabdruck(ctx, quellen, wert, stufe, text):
    quellen.abdruck = wert
    assert punkte(ctx)["stimmabdruck"] == (stufe, text)


async def test_abdruck_nutzt_den_lesewert_des_kerns(monkeypatch):
    import stimme_speicher

    gesehen, antworten = [], [(True, object()), (True, None), (False, None)]

    async def laden(speicher):
        gesehen.append(speicher.user_id)
        return antworten[len(gesehen) - 1]

    monkeypatch.setattr(stimme_speicher, "abdruck_laden", laden)
    for erwartet in (True, False, None):
        assert await api.abdruck_vorhanden(ADMIN) is erwartet
    assert gesehen == [ADMIN] * 3


# ---------- pc ----------
def test_pc_admin_gruen(ctx):
    assert punkte(ctx)["pc"] == ("gruen", api.SATZ_PC_OK)


def test_pc_mitglied_ohne_schalter(ctx):
    ctx.ich = Identity(MITGLIED, "Mitglied", "mitglied", "du")
    assert punkte(ctx)["pc"] == ("rot", "PC-Steuerung ist für dein Profil noch nicht freigeschaltet.")


def test_pc_mitglied_mit_schalter_und_erreichbarem_geraet(ctx, quellen, monkeypatch):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER", "an")
    ctx.ich = Identity(MITGLIED, "Mitglied", "mitglied", "du")
    assert punkte(ctx)["pc"] == ("gruen", api.SATZ_PC_OK)
    quellen.socket = pc_tunnel.GegenstelleFalsch("x")
    assert neu(ctx, quellen)["pc"] == ("rot", api.SATZ_PC_NICHT_ERREICHBAR)


def test_pc_am_server_aus(ctx, monkeypatch):
    monkeypatch.setenv("WAMO_PC_HOST", "off")
    assert punkte(ctx)["pc"] == ("rot", api.SATZ_PC_AUS)


# ---------- Zugang ----------
@pytest.mark.parametrize("art", ["platz", "schaufenster", "unbekannt", ""])
def test_laborprofil_403_ohne_abfrage(ctx, quellen, art):
    ctx.ich = Identity(MITGLIED, "Gast", "mitglied", "du", labor_art=art)
    r = ctx.client.get(STAND)
    assert r.status_code == 403 and r.headers["cache-control"] == "no-store"
    assert quellen.aufrufe == [] and api._zwischenspeicher == {}


@pytest.mark.parametrize("status", [401, 403, 503])
def test_ohne_identitaet_keine_abfrage(ctx, quellen, monkeypatch, status):
    async def abgelehnt(_request):
        raise HTTPException(status, "nicht berechtigt")

    monkeypatch.setattr(api, "identitaet", abgelehnt)
    assert ctx.client.get(STAND).status_code == status
    assert quellen.aufrufe == []


def test_echte_identitaet_ohne_zugangskontrolle(quellen, monkeypatch):
    import wamo_api

    monkeypatch.setattr(wamo_api, "_gate", None)
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    assert TestClient(app).get(STAND).status_code == 503
    assert quellen.aufrufe == []


# ---------- Zwischenspeicher ----------
def test_zwischenspeicher_zehn_sekunden_je_profil(ctx, quellen):
    erste = ctx.client.get(STAND).json()
    anzahl = len(quellen.aufrufe)
    quellen.uhr.t += api.ZWISCHENSPEICHER_SECS - 0.5
    quellen.soniox = False  # ändert sich, wird aber noch nicht neu geprüft
    assert ctx.client.get(STAND).json() == erste and len(quellen.aufrufe) == anzahl
    ctx.ich = Identity(MITGLIED, "Mitglied", "mitglied", "du")  # anderes Profil: eigene Prüfung
    assert ctx.client.get(STAND).json()["punkte"][3]["stufe"] == "rot" and len(quellen.aufrufe) > anzahl
    ctx.ich = Identity(ADMIN, "Niko", "admin", "du")
    quellen.uhr.t += 1.0
    assert ctx.client.get(STAND).json()["punkte"][3] == {"id": "stimme", "stufe": "rot",
                                                         "text": "Die Stimme ist am Server nicht eingerichtet."}


def langsames_geraet(quellen, monkeypatch) -> asyncio.Event:
    """aktives_geraet wartet, bis der Test das Ereignis setzt."""
    frei = asyncio.Event()

    async def aktives_geraet(_uid):
        quellen.aufrufe.append("aktives_geraet")
        await frei.wait()
        return GERAET

    monkeypatch.setattr(api, "aktives_geraet", aktives_geraet)
    return frei


async def schritte(n: int = 5) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


ICH = Identity(ADMIN, "Niko", "admin", "du")


async def test_gleichzeitige_aufrufe_pruefen_einmal(quellen, monkeypatch):
    frei = langsames_geraet(quellen, monkeypatch)
    laeufe = [asyncio.create_task(api.stand_fuer(ICH)) for _ in range(5)]
    await schritte()
    frei.set()
    ergebnisse = await asyncio.gather(*laeufe)
    assert quellen.aufrufe.count("aktives_geraet") == 1 and all(e == ergebnisse[0] for e in ergebnisse)
    assert api._laufend == {}


async def test_abbruch_eines_wartenden_beendet_die_geteilte_pruefung_nicht(quellen, monkeypatch):
    frei = langsames_geraet(quellen, monkeypatch)
    a, b = asyncio.create_task(api.stand_fuer(ICH)), asyncio.create_task(api.stand_fuer(ICH))
    await schritte()
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    frei.set()
    assert (await b)["punkte"][1] == {"id": "geraet", "stufe": "gruen", "text": api.SATZ_GERAET_OK}
    assert api._laufend == {} and (ADMIN, "admin") in api._zwischenspeicher


async def test_auch_ohne_wartende_endet_die_pruefung_und_wird_gespeichert(quellen, monkeypatch):
    frei = langsames_geraet(quellen, monkeypatch)
    einziger = asyncio.create_task(api.stand_fuer(ICH))
    await schritte()
    lauf = api._laufend[(ADMIN, "admin")]
    einziger.cancel()
    frei.set()
    await lauf
    await schritte(2)
    assert api._laufend == {} and (ADMIN, "admin") in api._zwischenspeicher


async def test_nach_einem_fehler_bleibt_nichts_laufend_und_nichts_gespeichert(quellen, monkeypatch):
    async def kaputt(_ich):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(api, "_pruefen", kaputt)
    with pytest.raises(RuntimeError):
        await api.stand_fuer(ICH)
    await schritte(2)
    assert api._laufend == {} and api._zwischenspeicher == {}


async def test_verdraengung_nur_des_aeltesten_und_abgelaufene_beim_schreiben(quellen, monkeypatch):
    monkeypatch.setattr(api, "MAX_ZWISCHENSPEICHER", 3)
    profile = [str(uuid.UUID(int=i + 1, version=4)) for i in range(5)]
    for p in profile[:4]:  # Zeit 1000, 1001, 1002, 1003: beim vierten fällt nur der älteste weg
        await api.stand_fuer(Identity(p, "Mitglied", "mitglied", "du"))
        quellen.uhr.t += 1.0
    assert [k[0] for k in api._zwischenspeicher] == profile[1:4]
    quellen.uhr.t = 1012.5  # profile[1] und [2] sind abgelaufen, [3] noch nicht
    await api.stand_fuer(Identity(profile[4], "Mitglied", "mitglied", "du"))
    assert [k[0] for k in api._zwischenspeicher] == [profile[3], profile[4]]


# ---------- Auffangschutz und Fristen ----------
def test_erstanmeldung_wirft_passwort_rot_rest_unberuehrt(ctx, quellen, monkeypatch):
    def wirft(_ich):
        raise RuntimeError("Feld kaputt")

    monkeypatch.setattr(api, "erstanmeldung_stand", wirft)
    p = punkte(ctx)
    assert p["passwort"] == ("rot", api.SATZ_PASSWORT_UNKLAR)
    assert all(stufe == "gruen" for pid, (stufe, _) in p.items() if pid != "passwort")


def test_wirft_eine_teilpruefung_werden_offene_punkte_rot_und_gespeichert(ctx, quellen, monkeypatch):
    def kaputt(_stand):
        raise RuntimeError("unerwartet")

    monkeypatch.setattr(api, "_stimme", kaputt)
    p = punkte(ctx)
    assert list(p) == IDS
    for pid in ("stimme", "gespraech", "entwicklung", "pc"):
        assert p[pid] == ("rot", api.UNKLAR[pid]), pid
    for pid, (stufe, text) in p.items():  # was vorher fertig war, bleibt; alles andere ist rot und unklar
        assert stufe == "gruen" or (stufe, text) == ("rot", api.UNKLAR[pid]), pid
    anzahl = len(quellen.aufrufe)
    quellen.uhr.t += api.ZWISCHENSPEICHER_SECS - 1
    assert punkte(ctx) == p and len(quellen.aufrufe) == anzahl  # auch dieses Ergebnis gilt 10 Sekunden
    assert api._laufend == {}


def test_haengende_quelle_endet_mit_quellenfrist(ctx, quellen, monkeypatch):
    async def haengt(_uid):
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "QUELLE_SECS", 0.05)
    monkeypatch.setattr(api, "aktives_geraet", haengt)
    p = punkte(ctx)
    assert p["geraet"] == ("rot", api.SATZ_GERAET_FEHLER) and p["tunnel"] == ("rot", api.SATZ_TUNNEL_UNKLAR)
    assert p["stimme"][0] == p["gespraech"][0] == p["stimmabdruck"][0] == "gruen"


def test_gesamtfrist_macht_offene_punkte_rot(ctx, quellen, monkeypatch):
    abgebrochen = []

    async def haengt(_pfad, _uid):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            abgebrochen.append(True)
            raise

    monkeypatch.setattr(api, "GESAMT_SECS", 0.1)
    monkeypatch.setattr(api, "gegenstelle_pruefen", haengt)
    p = punkte(ctx)
    assert p["geraet"] == ("gruen", api.SATZ_GERAET_OK)
    assert p["tunnel"] == ("rot", api.SATZ_TUNNEL_UNKLAR) and p["pc"] == ("rot", api.SATZ_PC_UNKLAR)
    assert p["stimme"][0] == p["entwicklung"][0] == p["stimmabdruck"][0] == "gruen"
    assert abgebrochen == [True] and api._laufend == {}


def test_dateien_lesen_hat_die_quellenfrist(ctx, echter_tunnel, monkeypatch):
    def langsam(*_args, **_kwargs):
        threading.Event().wait(0.3)

    monkeypatch.setattr(api, "QUELLE_SECS", 0.05)
    monkeypatch.setattr(pc_geraet, "lies_geheimnisse", langsam)
    assert punkte(ctx)["tunnel"] == ("rot", api.SATZ_TUNNEL_ROT)
    assert echter_tunnel.verbunden == []


# ---------- Quellen mit Attrappen-Datenbank ----------
class Db:
    def __init__(self, configured=True, zeilen=()):
        self.configured, self.zeilen, self.aufrufe = configured, list(zeilen), []

    def t(self, name):
        return f"wamo_test.{name}"

    async def fetch(self, sql, *args):
        self.aufrufe.append((sql, args))
        return self.zeilen


async def test_geraete_status_liest_nur_eigene_persoenliche_geraete(monkeypatch):
    db = Db(zeilen=[{"status": "beantragt"}, {"status": "gesperrt"}])
    monkeypatch.setattr(api, "shared_database", lambda: db)
    assert await api.geraete_status(ADMIN.upper()) == frozenset({"beantragt", "gesperrt"})
    ((sql, args),) = db.aufrufe
    assert "wamo_test.devices" in sql and "'persoenlich'" in sql and "limit 8" in sql and "$1::uuid" in sql
    assert args == (ADMIN,)
    with pytest.raises(gr.RegisterFehler):
        await api.geraete_status("kein-profil")
    monkeypatch.setattr(api, "shared_database", lambda: Db(configured=False))
    with pytest.raises(gr.RegisterFehler):
        await api.geraete_status(ADMIN)
    assert len(db.aufrufe) == 1


async def test_modellzugang_stand_ohne_datenbank(monkeypatch):
    from memory import DatabaseUnavailable

    gefragt = []

    async def stand_laden(user_id, *, db):
        gefragt.append((user_id, db))
        return stand_von()

    monkeypatch.setattr(mz, "stand_laden", stand_laden)
    monkeypatch.setattr(api, "shared_database", lambda: Db(configured=False))
    with pytest.raises(DatabaseUnavailable):
        await api.modellzugang_stand(ADMIN)
    assert gefragt == []
    db = Db()
    monkeypatch.setattr(api, "shared_database", lambda: db)
    assert (await api.modellzugang_stand(ADMIN)).quelle == "profil" and gefragt == [(ADMIN, db)]


# ---------- Geheimnisse, Pfade, MCP und Socket ----------
class Strom:
    """Attrappe eines verbundenen Unix-Sockets: merkt sich jedes Schreiben und das Schließen."""

    def __init__(self, uid: int):
        self.uid = uid
        self.geschrieben: list[bytes] = []
        self.zu = False

    def get_extra_info(self, name):
        return self if name == "socket" else None

    async def write(self, daten, timeout=None):
        self.geschrieben.append(daten)

    async def read(self, n, timeout=None):
        raise AssertionError("die Prüfliste liest nie vom Socket")

    async def aclose(self):
        self.zu = True


@pytest.fixture
def echter_tunnel(monkeypatch, quellen):
    """Die echten Prüfungen von Ordner, Dateien und Gegenstelle; nur Dateisystem und Socket sind Attrappen."""
    t = type("T", (), {})()
    t.gelesen, t.verbunden, t.stroeme, t.gegenstelle = [], [], [], 1007

    def lies_geheimnisse(geraet, wurzel, *, uid=None, **_):
        t.gelesen.append((geraet, wurzel, uid))
        return pc_geraet.Geheimnisse(TOKEN, FREIGABE)

    async def verbinden(self, path, timeout=None, socket_options=None):
        t.verbunden.append(path)
        strom = Strom(t.gegenstelle)
        t.stroeme.append(strom)
        return strom

    monkeypatch.setattr(pc_geraet, "lies_geheimnisse", lies_geheimnisse)
    monkeypatch.setattr(pc_geraet, "_uid_von", lambda benutzer: 1007 if benutzer == "wamo-t-07" else 1)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_unix_socket", verbinden)
    for name in ("dateien_pruefen", "gegenstelle_pruefen"):
        monkeypatch.setattr(api, name, ECHT[name])
    # SO_PEERCRED gibt es nur unter Linux: die Gegenstelle liest hier die Attrappe, die Prüfung selbst ist die echte
    monkeypatch.setattr(api, "GEGENSTELLE", lambda uid: pc_tunnel.GegenstellenPruefung(uid, lesen=lambda sock: sock.uid))
    return t


def test_echter_tunnel_gruen_ohne_ein_byte(ctx, echter_tunnel):
    assert punkte(ctx)["tunnel"] == ("gruen", api.SATZ_TUNNEL_OK)
    assert echter_tunnel.gelesen == [(GERAET, "/run/wamo-pc", 1007)]
    assert echter_tunnel.verbunden == ["/run/wamo-pc/t07/pc.sock"]
    assert all(s.zu and s.geschrieben == [] for s in echter_tunnel.stroeme)


def test_falsche_gegenstelle_ist_rot_und_geschlossen(ctx, echter_tunnel):
    echter_tunnel.gegenstelle = 1008
    assert punkte(ctx)["tunnel"] == ("rot", "Der Tunnel steht nicht. Bist du im Büronetz?")
    assert all(s.zu and s.geschrieben == [] for s in echter_tunnel.stroeme)


async def test_gegenstelle_hat_eine_frist_und_schliesst_auch_bei_abbruch(monkeypatch):
    monkeypatch.setattr(api, "GEGENSTELLE", lambda uid: pc_tunnel.GegenstellenPruefung(uid, lesen=lambda sock: sock.uid))
    monkeypatch.setattr(api, "SOCKET_SECS", 0.05)

    async def haengt(self, path, timeout=None, socket_options=None):
        assert timeout is None  # nur die eine Frist von gegenstelle_pruefen
        await asyncio.Event().wait()

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_unix_socket", haengt)
    with pytest.raises(TimeoutError):
        await api.gegenstelle_pruefen("/run/wamo-pc/t07/pc.sock", 1007)

    strom, frei = Strom(1007), asyncio.Event()

    async def langsam_zu():
        await frei.wait()
        strom.zu = True

    async def verbinden(self, path, timeout=None, socket_options=None):
        return strom

    strom.aclose = langsam_zu
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_unix_socket", verbinden)
    lauf = asyncio.create_task(api.gegenstelle_pruefen("/run/wamo-pc/t07/pc.sock", 1007))
    await schritte()
    lauf.cancel()  # Abbruch während des Schließens: das Schließen läuft weiter
    with pytest.raises(asyncio.CancelledError):
        await lauf
    frei.set()
    await schritte()
    assert strom.zu and strom.geschrieben == []


def test_kein_geheimnis_und_kein_pfad_in_der_antwort(ctx, quellen, echter_tunnel, monkeypatch):
    monkeypatch.setenv("SONIOX_API_KEY", SONIOX)
    monkeypatch.setattr(api, "soniox_gesetzt", ECHT["soniox_gesetzt"])
    text = ctx.client.get(STAND).text
    quellen.stand = asyncpg.PostgresError('permission denied for relation "wamo_prod.model_access" /etc/wamo')
    quellen.geraet, quellen.status = None, gr.RegisterFehler("Register nicht erreichbar (/run/wamo-pc)")
    text += neu(ctx, quellen).__repr__()
    for geheim in (TOKEN, FREIGABE, SONIOX, FINGERABDRUCK, "pc-niko", "wamo-t-07", "t07", "/run", "/etc", "wamo_prod",
                   "permission", "1007", "abcd", ADMIN):
        assert geheim not in text, geheim


def test_nie_mcp_start_und_nie_werkzeugaufruf(ctx, quellen, echter_tunnel, monkeypatch):
    verboten: list[str] = []

    def falle(name):
        def f(*args, **kwargs):
            verboten.append(name)
            raise AssertionError(f"{name} darf die Prüfliste nie aufrufen")
        return f

    def falle_async(name):
        async def f(*args, **kwargs):
            verboten.append(name)
            raise AssertionError(f"{name} darf die Prüfliste nie aufrufen")
        return f

    # MCP und Werkzeuge (auch der stdio-Weg, der den Host als Prozess startet), HTTP an den Laptop und jeder Prozessstart
    for modul, name in ((pc_host, "host_client"), (pc_host, "host_tools"), (pc_host, "call_host_tool"), (pc_host, "pc_zugang"),
                        (pc_host, "pc_sperre_pruefen"), (pc_host, "MCPClient"), (pc_geraet, "pc_zugang_fuer"),
                        (pc_tunnel, "TunnelHost"), (subprocess, "Popen")):
        monkeypatch.setattr(modul, name, falle(f"{modul.__name__}.{name}"))
    for modul, name in ((httpx.AsyncClient, "send"), (asyncio, "create_subprocess_exec"), (asyncio, "create_subprocess_shell"),
                        (anyio, "open_process")):
        monkeypatch.setattr(modul, name, falle_async(f"{getattr(modul, '__name__', modul)}.{name}"))
    p = punkte(ctx)
    assert p["tunnel"] == ("gruen", api.SATZ_TUNNEL_OK) and p["pc"] == ("gruen", api.SATZ_PC_OK)
    assert verboten == []
    assert echter_tunnel.stroeme and all(s.zu and s.geschrieben == [] for s in echter_tunnel.stroeme)


def test_quelltext_kennt_keinen_weg_zum_host():
    baum = ast.parse(pathlib.Path(api.__file__).read_text(encoding="utf-8"))
    namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(baum) if isinstance(n, ast.Attribute)}
    for verboten in ("host_client", "host_tools", "call_host_tool", "pc_zugang", "pc_zugang_fuer", "TunnelHost", "MCPClient",
                     "call_text", "pc_sperre_pruefen", "write", "send", "sendall", "Popen", "create_subprocess_exec",
                     "create_subprocess_shell", "open_process"):
        assert verboten not in namen, verboten
