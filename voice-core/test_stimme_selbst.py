"""Tests: Die Person wählt Hören und Stimme selbst (Soniox oder im Haus, Paket H5, Entscheidung von Niko vom 16.11.2026).

Soniox bleibt Standard. Die Wahl gilt ab der nächsten Sitzung, steht als Zeile in actions und geht nie für Laborprofile (403 wie die
übrigen Laborpfade; in einer Laborsitzung gilt immer Soniox, auch bei einer Wahl im Profil oder einer Übersteuerung in der Umgebung).
Fällt der Kern auf Soniox zurück, erfährt die Oberfläche den Grund in einem Satz für Menschen, ohne Namen aus der Umgebung."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import labor
import modellzugang as mz
import modellzugang_api as api
import sprache_anbieter as sa
from auth_gate import Identity
from schluessel import kek_erzeugen
from test_modellwahl import NIKO, FakeDb, _zeile

WURZEL = Path(__file__).resolve().parent.parent
NAMEN = ("WAMO_STT_ANBIETER", "WAMO_TTS_ANBIETER", "WAMO_STT_HAUS_MODELL", "WAMO_TTS_HAUS_MODELL", "WAMO_TTS_HAUS_STIMME",
          "WAMO_TTS_HAUS_STREAM")


@pytest.fixture(autouse=True)
def _bremse_frisch(monkeypatch):
    monkeypatch.setattr(mz, "_stimme_versuche", {})  # die Bremse zählt je Prozess; jeder Test beginnt ohne Wechsel


# --- Kern: stimme_setzen ------------------------------------------------------------------------------------------


async def test_die_person_waehlt_hoeren_und_stimme_im_haus():
    db = FakeDb()
    stand = await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert (stand.stt, stand.tts) == ("haus", "haus")
    assert (db.zeilen[NIKO]["stt"], db.zeilen[NIKO]["tts"]) == ("haus", "haus")
    n = stand.nachricht(aktion="stimme")
    assert (n["aktion"], n["stt"], n["tts"], n["wirksam"]) == ("stimme", "haus", "haus", "ab der nächsten Sitzung")


async def test_zurueck_auf_soniox_und_getrennte_werte():
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(stt="haus", tts="haus")
    stand = await mz.stimme_setzen(NIKO, "soniox", "soniox", db=db)
    assert (stand.stt, stand.tts) == ("soniox", "soniox")
    stand = await mz.stimme_setzen(NIKO, "haus", "soniox", db=db)  # die Schnittstelle kennt beide Bausteine einzeln
    assert (stand.stt, stand.tts) == ("haus", "soniox")


@pytest.mark.parametrize("stt,tts", [("cloud", "haus"), ("haus", None), (None, None), ("HAUS", "haus"), (["haus"], "haus"),
                                     ("haus", "haus; drop table")])
async def test_nur_soniox_oder_haus(stt, tts):
    db = FakeDb()
    with pytest.raises(mz.ZugangFehler, match="soniox oder haus"):
        await mz.stimme_setzen(NIKO, stt, tts, db=db)
    assert db.zeilen == {} and db.aktionen == []
    assert not [s for s in db.sql if s.startswith("insert")]


async def test_zwang_des_admins_sperrt_die_stimme_nicht():
    """nur_haus gilt für die Sprachmodelle; Soniox bleibt für alle Profile wählbar (D3), Hausstimme ebenso."""
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(nur_haus=True)
    stand = await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert (stand.stt, stand.tts, stand.festgelegt) == ("haus", "haus", True)


async def test_eintrag_in_actions_nur_mit_den_werten():
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(stt="soniox", tts="soniox")
    await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert len(db.aktionen) == 1
    uid, werkzeug, params, grund = db.aktionen[0]
    assert (uid, werkzeug) == (NIKO, mz.STIMME_WERKZEUG)
    assert json.loads(params) == {"stt": "haus", "tts": "haus", "vorher": {"stt": "soniox", "tts": "soniox"}}
    assert "nächsten Sitzung" in grund
    sql = next(s for s in db.sql if "actions" in s)
    assert "'change'" in sql and "'done'" in sql and "finished_at" in sql


async def test_protokoll_weg_hindert_die_wahl_nicht():
    import asyncpg

    db = FakeDb()
    original = db.execute

    async def execute(sql, *args):
        if "actions" in sql:
            raise asyncpg.PostgresConnectionError("weg")
        return await original(sql, *args)

    db.execute = execute
    stand = await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert (stand.stt, stand.tts) == ("haus", "haus")


async def test_ohne_migration_0023_ein_klarer_satz():
    db = FakeDb(ohne_0023=True)
    with pytest.raises(mz.ZugangFehler, match="noch nicht freigeschaltet") as fehler:
        await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert "Migration" not in str(fehler.value)  # interne Namen gehören ins Log, nicht in den Satz für die Person
    assert db.aktionen == []


async def test_gleiche_wahl_schreibt_und_protokolliert_nichts():
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(stt="haus", tts="haus")
    stand = await mz.stimme_setzen(NIKO, "haus", "haus", db=db)
    assert (stand.stt, stand.tts) == ("haus", "haus")
    leer = FakeDb()  # ohne Zeile gilt Soniox; Soniox wählen ändert nichts
    await mz.stimme_setzen(NIKO, "soniox", "soniox", db=leer)
    for d in (db, leer):
        assert d.aktionen == [] and not [s for s in d.sql if s.startswith("insert")]


async def test_zu_viele_wechsel_werden_gebremst(monkeypatch):
    monkeypatch.setattr(mz, "_stimme_versuche", {})
    db = FakeDb()
    for i in range(mz.STIMME_JE_FENSTER):
        await mz.stimme_setzen(NIKO, "haus" if i % 2 == 0 else "soniox", "haus" if i % 2 == 0 else "soniox", db=db)
    with pytest.raises(mz.ZugangFehler, match="Zu viele Wechsel"):
        await mz.stimme_setzen(NIKO, "haus" if db.zeilen[NIKO]["stt"] == "soniox" else "soniox",
                               "haus" if db.zeilen[NIKO]["stt"] == "soniox" else "soniox", db=db)
    assert len(db.aktionen) == mz.STIMME_JE_FENSTER


async def test_stand_nennt_ob_im_haus_eingerichtet_ist(monkeypatch):
    for name in ("WAMO_STT_HAUS_MODELL", "WAMO_TTS_HAUS_MODELL", "WAMO_TTS_HAUS_STIMME"):
        monkeypatch.delenv(name, raising=False)
    n = (await mz.stand_laden(NIKO, db=FakeDb())).nachricht()
    assert n["stimme_haus"] == sa.GRUND_EINRICHTUNG
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.test.invalid:4000/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.setenv("WAMO_STT_HAUS_MODELL", "wamo-stt-haus")
    monkeypatch.setenv("WAMO_TTS_HAUS_MODELL", "wamo-tts-haus")
    monkeypatch.setenv("WAMO_TTS_HAUS_STIMME", "sohee")
    assert (await mz.stand_laden(NIKO, db=FakeDb())).nachricht()["stimme_haus"] == "bereit"
    monkeypatch.setenv("WAMO_STT_HAUS_MODELL", "whisper-1")  # kein Hausname: nicht eingerichtet
    assert (await mz.stand_laden(NIKO, db=FakeDb())).nachricht()["stimme_haus"] == sa.GRUND_EINRICHTUNG


async def test_ohne_datenbank_und_mit_falschem_profil():
    with pytest.raises(mz.ZugangFehler, match="Profil ungültig"):
        await mz.stimme_setzen("kein-profil", "haus", "haus", db=FakeDb())
    leer = FakeDb()
    leer.configured = False
    with pytest.raises(mz.ZugangFehler, match="Keine Datenbank"):
        await mz.stimme_setzen(NIKO, "haus", "haus", db=leer)


async def test_nachricht_der_sitzung_kennt_die_aktion_stimme():
    db = FakeDb()
    gesendet: list[dict] = []

    async def senden(n: dict) -> None:
        gesendet.append(n)

    await mz.modellzugang_nachricht(NIKO, {"aktion": "stimme", "stt": "haus", "tts": "haus"}, senden, db=db)
    assert (gesendet[-1]["aktion"], gesendet[-1]["stt"], gesendet[-1]["tts"]) == ("stimme", "haus", "haus")
    assert "fehler" not in gesendet[-1]
    await mz.modellzugang_nachricht(NIKO, {"aktion": "stimme", "stt": "quatsch", "tts": "haus"}, senden, db=db)
    assert gesendet[-1]["aktion"] == "stimme" and "soniox oder haus" in gesendet[-1]["fehler"]
    assert gesendet[-1]["stt"] == "haus"  # der Stand bleibt, wie er war


# --- HTTP: /wamo/api/modellzugang mit aktion stimme, nie für Laborprofile ----------------------------------------


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(mz, "shared_database", lambda: fake)
    monkeypatch.setenv("WAMO_SCHLUESSEL_KEK", kek_erzeugen())
    return fake


def _client(monkeypatch, identitaet: Identity) -> TestClient:
    async def pruefen(_request):
        return identitaet

    monkeypatch.setattr(api, "identitaet", pruefen)
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    return TestClient(app)


def test_route_setzt_hoeren_und_stimme(db, monkeypatch):
    c = _client(monkeypatch, Identity(user_id=NIKO, name="Niko", rolle="mitglied", anrede="du", anmeldung=1.0))
    r = c.post("/wamo/api/modellzugang", json={"aktion": "stimme", "stt": "haus", "tts": "haus"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert (r.json()["stt"], r.json()["tts"], r.json()["aktion"]) == ("haus", "haus", "stimme")
    assert c.get("/wamo/api/modellzugang").json()["stt"] == "haus"
    assert len(db.aktionen) == 1


@pytest.mark.parametrize("art", ["platz", "schaufenster"])
def test_laborprofile_bekommen_403(db, monkeypatch, art):
    ich = Identity(user_id=NIKO, name="Labor", rolle="mitglied", anrede="du", anmeldung=1.0, labor_art=art, labor_platz=3,
                   labor_aktiv=True)
    c = _client(monkeypatch, ich)
    r = c.post("/wamo/api/modellzugang", json={"aktion": "stimme", "stt": "haus", "tts": "haus"})
    assert r.status_code == 403 and r.headers["cache-control"] == "no-store"
    assert r.json()["code"] == labor.CODE_PFAD_GESPERRT
    assert c.get("/wamo/api/modellzugang").status_code == 403
    assert db.zeilen == {} and db.sql == [] and db.aktionen == []


def test_laborpfad_bleibt_in_der_laborsperre_gesperrt():
    """Erste Sperre vor der Route: die Middleware lässt /wamo/api/modellzugang für Laborprofile nie durch."""
    for art in ("platz", "schaufenster"):
        for methode in ("GET", "POST"):
            assert labor.pfad_pruefen(art, methode, "/wamo/api/modellzugang") is None
        assert not labor.client_nachricht_erlaubt(art, "modellzugang", {"aktion": "stimme", "stt": "haus", "tts": "haus"})


# --- Sitzung: Labor immer Soniox, Grund des Rückfalls -------------------------------------------------------------


async def test_laborsitzung_hoert_und_spricht_immer_ueber_soniox():
    env = {"WAMO_STT_ANBIETER": "haus", "WAMO_TTS_ANBIETER": "haus", "WAMO_STT_HAUS_MODELL": "wamo-stt-haus",
           "WAMO_TTS_HAUS_MODELL": "wamo-tts-haus", "WAMO_TTS_HAUS_STIMME": "sohee"}
    with mock.patch.dict("os.environ", env), \
            mock.patch.object(sa, "litellm_problem", side_effect=AssertionError("im Labor nie das Gateway fragen")):
        w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"), labor=True)
    assert (w.stt.anbieter, w.tts.anbieter, w.stt.gewuenscht, w.tts.gewuenscht) == ("soniox",) * 4
    assert w.grund() is None and w.anzeige("Nina") == {"stt": "Soniox", "tts": "Soniox Nina"}


@pytest.mark.parametrize("problem,satz", [
    ("WAMO_STT_HAUS_MODELL fehlt", sa.GRUND_EINRICHTUNG),
    ("LITELLM_API_KEY fehlt", sa.GRUND_EINRICHTUNG),
    ("LITELLM_BASE_URL muss mit http:// oder https:// beginnen", sa.GRUND_EINRICHTUNG),
    ("kein Modell gesetzt", sa.GRUND_EINRICHTUNG),
    ("Gateway lehnt den Schlüssel ab (HTTP 401)", sa.GRUND_EINRICHTUNG),
    ("das Gateway bietet das Modell 'wamo-stt-haus' nicht an", sa.GRUND_MODELL),
    ("Gateway nicht erreichbar (ConnectError)", sa.GRUND_GATEWAY),
    ("Gateway antwortet mit HTTP 502", sa.GRUND_GATEWAY),
    ("WAMO_STT_HAUS_MODELL ist kein Hausmodell (wamo-...)", sa.GRUND_EINRICHTUNG),
    ("etwas ganz anderes", sa.GRUND_SONST),
])
def test_grund_fuer_menschen_ohne_namen_aus_der_umgebung(problem, satz):
    assert sa.anzeige_grund(problem) == satz
    assert not re.search(r"[A-Z]{3,}_[A-Z]", satz) and "'" not in satz


async def test_echte_gruende_des_gateways_werden_richtig_zugeordnet(monkeypatch):
    """Die Texte kommen aus llm_anbieter.py selbst (nicht abgeschrieben): ändert sich dort ein Satz, fällt es hier auf."""
    import httpx

    import llm_anbieter as la

    for name in ("LITELLM_BASE_URL", "LITELLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert sa.anzeige_grund(la.litellm_problem_statisch("wamo-stt-haus")) == sa.GRUND_EINRICHTUNG
    monkeypatch.setenv("LITELLM_BASE_URL", "gateway.test.invalid")
    assert sa.anzeige_grund(la.litellm_problem_statisch("wamo-stt-haus")) == sa.GRUND_EINRICHTUNG
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.test.invalid:4000/v1")
    assert sa.anzeige_grund(la.litellm_problem_statisch("wamo-stt-haus")) == sa.GRUND_EINRICHTUNG  # Schlüssel fehlt
    monkeypatch.setenv("LITELLM_API_KEY", "k")

    async def grund(antwort) -> str:
        client = httpx.AsyncClient(transport=httpx.MockTransport(antwort))
        try:
            return sa.anzeige_grund(await la._alias_pruefen("wamo-stt-haus", client=client))
        except la.LLMFehler as e:
            return sa.anzeige_grund(str(e))

    assert await grund(lambda r: httpx.Response(404)) == sa.GRUND_MODELL
    assert await grund(lambda r: httpx.Response(401)) == sa.GRUND_EINRICHTUNG
    assert await grund(lambda r: httpx.Response(503)) == sa.GRUND_GATEWAY

    def weg(request):
        raise httpx.ConnectError("weg", request=request)

    assert await grund(weg) == sa.GRUND_GATEWAY


async def test_nur_modelle_mit_hausnamen(monkeypatch):
    """Ein Alias, der nicht wie ein Hausmodell heißt (z. B. ein Cloud-Modell im Gateway), wird nie für "Im Haus" genommen."""
    env = {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": "", "WAMO_STT_HAUS_MODELL": "whisper-1",
           "WAMO_TTS_HAUS_MODELL": "wamo-tts-haus", "WAMO_TTS_HAUS_STIMME": "sohee",
           "LITELLM_BASE_URL": "http://gateway.test.invalid:4000/v1", "LITELLM_API_KEY": "k"}
    with mock.patch.dict("os.environ", env), mock.patch.object(sa, "litellm_problem", mock.AsyncMock(return_value=None)):
        w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"))
    assert (w.stt.anbieter, w.tts.anbieter) == ("soniox", "haus")
    assert w.grund() == f"Spracherkennung: {sa.GRUND_EINRICHTUNG}"


async def test_uebersteuerung_des_betriebs_wird_genannt():
    env = {"WAMO_STT_ANBIETER": "soniox", "WAMO_TTS_ANBIETER": "soniox"}
    with mock.patch.dict("os.environ", env):
        w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"))
    assert (w.stt.anbieter, w.tts.anbieter) == ("soniox", "soniox") and not w.stt.rueckfall
    assert w.grund() == f"Spracherkennung und Sprachausgabe: {sa.GRUND_BETRIEB_SONIOX}"
    with mock.patch.dict("os.environ", {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": ""}):
        assert (await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus"))).stt.uebersteuert is False


def test_grund_beider_bausteine():
    modell = "das Gateway bietet das Modell 'x' nicht an"
    beide = sa.SprachWahl(sa.Baustein("haus", "soniox", "x", modell), sa.Baustein("haus", "soniox", "y", modell))
    assert beide.grund() == f"Spracherkennung und Sprachausgabe: {sa.GRUND_MODELL}"
    einer = sa.SprachWahl(sa.Baustein("haus", "haus", "x"), sa.Baustein("haus", "soniox", None, "WAMO_TTS_HAUS_STIMME fehlt"))
    assert einer.grund() == f"Sprachausgabe: {sa.GRUND_EINRICHTUNG}"
    getrennt = sa.SprachWahl(sa.Baustein("haus", "soniox", "x", "Gateway nicht erreichbar (ConnectError)"),
                             sa.Baustein("haus", "soniox", "y", "WAMO_TTS_HAUS_STIMME fehlt"))
    assert getrennt.grund() == f"Spracherkennung: {sa.GRUND_GATEWAY}; Sprachausgabe: {sa.GRUND_EINRICHTUNG}"
    ohne = sa.SprachWahl(sa.Baustein("soniox", "soniox"), sa.Baustein("haus", "haus", "y"))
    assert ohne.grund() is None


def test_betrieb_traegt_den_grund_nur_bei_rueckfall():
    import bot

    m = bot.betrieb_message("aus", sprache={"stt": "Soniox (Rückfall)", "tts": "Soniox Nina (Rückfall)"},
                            sprache_grund="Spracherkennung und Sprachausgabe: " + sa.GRUND_MODELL + "x" * 300)
    assert m["modelle"]["stt"] == "Soniox (Rückfall)" and m["sprache_grund"].startswith("Spracherkennung")
    assert len(m["sprache_grund"]) == 160
    assert "sprache_grund" not in bot.betrieb_message("aus")


def test_bot_reicht_labor_und_grund_weiter():
    quelle = (Path(__file__).resolve().parent / "bot.py").read_text(encoding="utf-8")
    assert "sprach_wahl(zugang, labor=labor_sitzung is not None)" in quelle
    assert "sprache_grund=sprache.grund()" in quelle


# --- Umgebung am Server: wamo-core-env (L12) ----------------------------------------------------------------------


def test_der_kern_liest_genau_diese_namen():
    namen = set()
    for datei in Path(__file__).resolve().parent.glob("*.py"):
        if not datei.name.startswith("test_"):
            namen |= set(re.findall(r"WAMO_(?:STT|TTS)_(?:ANBIETER|HAUS_[A-Z]+)\b", datei.read_text(encoding="utf-8")))
    assert namen == set(NAMEN)


def test_am_server_setzbar_nie_vom_pc_kopiert():
    """Die Übersteuerung für alle Sitzungen und die Modelle gehören dem Server: eine .env des PCs (Tests mit haus) darf sie nie mitnehmen."""
    from test_env_schalter import EntwicklungsSchalterNieUebertragenTest as Laden

    env = Laden._laden("wamo_core_env_stimme", WURZEL / "infra" / "sokrates2" / "wamo_core_env.py")
    skript = Laden._laden("wamo_kern_sokrates2_stimme", WURZEL / "scripts" / "wamo_kern_sokrates2.py")
    for name in NAMEN:
        assert env.erlaubt(name), name
        assert name not in env.PFLICHT
        assert name not in skript.AUS_ENV, name
    assert not [p for p in (*env.ERLAUBT_PRAEFIX, *skript.AUS_ENV_PRAEFIX) if p.startswith(("WAMO_STT", "WAMO_TTS"))]
    for name in ("WAMO_STT_", "WAMO_STT_HAUS_SCHLUESSEL", "WAMO_TTS_HAUS_URL", "WAMO_STT_URL", "wamo_stt_anbieter"):
        assert not env.erlaubt(name), name


def test_leer_in_der_vorlage():
    text = (Path(__file__).resolve().parent / ".env.example").read_text(encoding="utf-8")
    for name in NAMEN:
        assert re.search(rf"(?m)^{name}=$", text), f"{name} fehlt oder hat einen Wert in voice-core/.env.example"
