"""Tests: Die Person wählt ihre Modelle selbst (Wunsch von Niko vom 16.11.2026, Migration 0024).

Je Profil wählbar: Gesprächsmodell, Modell für Bildschirm und Bilder, Modell für Lernen und Zusammenfassung (je "automatisch" oder
ein Modell aus der festen Liste der Modellkarte), Spracherkennung und Sprachausgabe getrennt (Soniox oder im Haus) und die Stimme im
Haus (eine der freigegebenen Stimmen, sprache_anbieter.HAUS_STIMMEN). Regeln: ein Hausprofil sieht keine Claude-Modelle, ohne Claude-Zugang keine Claude-Wahl,
ein vom Admin festgelegtes Profil ist für die Modellwahl gesperrt (die Stimme bleibt wählbar), ein vom Admin gesetztes Claude-Modell
ist das einzige Claude-Modell. Der Kern prüft jede Wahl selbst, schreibt eine Zeile in actions, und die Wahl gilt ab der nächsten
Sitzung. Laborprofile erreichen nichts davon. Datenbank, Gateway und Anthropic sind Attrappen."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

import boss
import labor
import llm_anbieter as la
import modellkarte as karte
import modellwahl as mw
import modellzugang as mz
import modellzugang_api as api
import sprache_anbieter as sa
from auth_gate import Identity
from llm_anbieter import Zugang
from schluessel import SCHLUESSEL, Tresor, kek_erzeugen
from test_modellwahl import API, NIKO, FakeDb as FakeDb0023, _zeile

WURZEL = Path(__file__).resolve().parent.parent

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


class FakeDb(FakeDb0023):
    """Wie in test_modellwahl, dazu die Spalten aus 0024 (ohne_0024: die Spalten fehlen, ohne_rechte: 0024 ohne Schreibrecht)."""

    def __init__(self, *, ohne_0024: bool = False, ohne_rechte: bool = False):
        super().__init__()
        self.ohne_0024 = ohne_0024
        self.ohne_rechte = ohne_rechte

    @staticmethod
    def _neu(sql: str) -> bool:
        return any(s in sql for s in (*mw.SPALTEN.values(), "tts_stimme"))

    async def fetchrow(self, sql: str, *args):
        if self.ohne_0024 and self._neu(sql):
            self.sql.append(sql)
            raise asyncpg.UndefinedColumnError("column does not exist")
        return await super().fetchrow(sql, *args)

    async def execute(self, sql: str, *args):
        if self._neu(sql) and sql.startswith("insert into wamo_test.model_access"):
            self.sql.append(sql)
            if self.ohne_0024:
                raise asyncpg.UndefinedColumnError("column does not exist")
            if self.ohne_rechte:
                raise asyncpg.InsufficientPrivilegeError("permission denied for table model_access")
            spalte = sql.split("(user_id, ", 1)[1].split(")", 1)[0]
            assert spalte in (*mw.SPALTEN.values(), "tts_stimme"), spalte  # nur Spalten aus der festen Liste
            self.zeilen.setdefault(args[0], _zeile())[spalte] = args[1]
            return "INSERT 0 1"
        return await super().execute(sql, *args)


@pytest.fixture
def tresor():
    return Tresor(base64.urlsafe_b64decode(kek_erzeugen()))


@pytest.fixture
def log():
    zeilen: list[str] = []
    sink = logger.add(lambda m: zeilen.append(str(m)), level="DEBUG")
    yield zeilen
    logger.remove(sink)


@pytest.fixture(autouse=True)
def _bremse_frisch(monkeypatch):
    monkeypatch.setattr(mz, "_wahl_versuche", {})
    monkeypatch.setattr(mz, "_stimme_versuche", {})


def _claude_zeile(tresor, **werte) -> dict:
    return _zeile(claude_schluessel=tresor.verschluesseln(NIKO, API, SCHLUESSEL), claude_schluessel_ende=API[-4:], **werte)


def _pruefer(grund: str | None = None, gesehen: list | None = None):
    async def pruefen(schluessel, workspace, modell):
        if gesehen is not None:
            gesehen.append((schluessel, workspace, modell))
        return grund
    return pruefen


def _ids(optionen) -> list[str]:
    return [o.id for o in optionen]


# --- Feste Listen (modellwahl.py) ----------------------------------------------------------------------------------


@pytest.mark.parametrize("bereich", mw.BEREICHE)
def test_hausprofil_sieht_nur_hausmodelle_der_karte(bereich):
    optionen = mw.optionen(bereich, claude=False)
    assert optionen, bereich
    for o in optionen:
        m = karte.modell(o.id)
        assert m is not None and m.anbieter == "haus" and m.status == "standard" and not m.sprache, o.id
        assert o.art == "haus" and o.name == m.anzeige
        assert "Güte" in o.zeile and "Tempo" in o.zeile, o.zeile
        assert la.anthropic_ziel(o.id) is None
    for verboten in ("sokrates-steuer", "sokrates-fable-qwen27", "sokrates", "sokrates-fast", "qwen3-asr", "soniox-stt",
                     "laaj-judge", "wamo-embed", HAIKU, SONNET):
        assert verboten not in _ids(optionen)


def test_reihenfolge_wie_der_boss_und_notloesungen_gekennzeichnet():
    gespraech = mw.optionen("gespraech", claude=False)
    assert gespraech[0].id == boss.hausstandard("gespraech") == "gemma4-31b"
    notfall = {k.alias for k in boss.rangliste("gespraech", claude_erlaubt=False) if k.notfall}
    for o in gespraech:
        assert ("Notlösung" in o.zeile) == (o.id in notfall), o
    assert mw.optionen("bilder", claude=False)[0].id == "wamo-vision"


def test_hintergrund_nur_modelle_fuer_lernen_und_zusammenfassung():
    ids = set(_ids(mw.optionen("hintergrund", claude=False)))
    lernen = {k.alias for k in boss.rangliste("lernen", claude_erlaubt=False)}
    zusammenfassung = {k.alias for k in boss.rangliste("zusammenfassung", claude_erlaubt=False)}
    assert ids == lernen & zusammenfassung and ids


def test_claude_profil_sieht_die_claude_modelle_mit_kostenhinweis():
    optionen = mw.optionen("gespraech", claude=True)
    claude = [o for o in optionen if o.art == "claude"]
    assert _ids(claude) == list(mw.CLAUDE_MODELLE) == [HAIKU, SONNET, "claude-opus-5-5"]
    haiku, sonnet = claude[0], claude[1]
    assert haiku.name == "Claude Haiku 5.5" and "Güte" in haiku.zeile and "Cloud" in haiku.zeile
    assert sonnet.name == "Claude Sonnet 5.5" and "nicht gemessen" in sonnet.zeile and "teurer" in sonnet.zeile
    assert [o.art for o in optionen[:3]] == ["claude"] * 3  # Claude zuerst, dann die Hausmodelle


def test_vom_admin_gesetztes_claude_modell_ist_das_einzige():
    claude = [o for o in mw.optionen("gespraech", claude=True, claude_fest=SONNET) if o.art == "claude"]
    assert _ids(claude) == [SONNET] and "Admin" in claude[0].zeile
    assert mw.gueltig("gespraech", SONNET, claude=True, claude_fest=SONNET)
    assert not mw.gueltig("gespraech", HAIKU, claude=True, claude_fest=SONNET)


@pytest.mark.parametrize("wert", [None, "", "automatisch", "GEMMA4-31B", "gemma4-31b ", ["gemma4-31b"], 7, "sokrates-steuer",
                                  "claude-haiku-5-5; drop table", "../etc", "claude-opus-9", "qwen3-coder-next"])
def test_nur_werte_aus_der_festen_liste(wert):
    for bereich in mw.BEREICHE:
        assert not mw.gueltig(bereich, wert, claude=True)
    assert not mw.gueltig("unbekannt", "gemma4-31b", claude=True)


def test_claude_nur_mit_claude_zugang():
    assert mw.gueltig("gespraech", HAIKU, claude=True)
    assert not mw.gueltig("gespraech", HAIKU, claude=False)
    assert mw.gueltig("gespraech", "gemma4-31b", claude=False)


# --- Zugang der Sitzung (zugang_laden, person_wunsch) --------------------------------------------------------------


async def test_wahl_der_person_reist_im_zugang(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor, modell_gespraech="gemma4-31b", modell_bilder=SONNET, tts_stimme="uncle_fu")
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert (z.art, z.quelle) == ("claude", "profil")
    assert la.person_wunsch("gespraech", z) == ("litellm", "gemma4-31b")
    assert la.person_wunsch("vision", z) == ("claude", SONNET)
    assert la.person_wunsch("lernen", z) is None and la.person_wunsch("boss_code", z) is None
    assert z.tts_stimme == "uncle_fu"
    assert API not in repr(z)


async def test_hausprofil_verliert_eine_gespeicherte_claude_wahl(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor, modell_modus="nur_haus", modell_gespraech=SONNET, modell_hintergrund="gemma4-31b")
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert (z.art, z.quelle) == ("haus", "wahl")
    assert la.person_wunsch("gespraech", z) is None
    assert la.person_wunsch("zusammenfassung", z) == ("litellm", "gemma4-31b")


async def test_unbekannte_werte_aus_der_datenbank_gelten_nicht(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(modell_gespraech="sokrates-steuer", modell_bilder="claude-haiku-5-5", tts_stimme="hedda")
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert z.modell_wahl == () and z.tts_stimme is None


async def test_vom_admin_festgelegt_gilt_auch_eine_alte_wahl_nicht(tresor):
    """Eine Wahl von vor der Sperre wirkt nicht weiter; die Stimme im Haus bleibt (D3), der Stand nennt den Grund."""
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(nur_haus=True, modell_gespraech="qwen3.6-35b", tts_stimme="ono_anna")
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert (z.quelle, z.modell_wahl, z.tts_stimme) == ("festgelegt", (), "ono_anna")
    assert la.person_wunsch("gespraech", z) is None
    n = (await mz.stand_laden(NIKO, db=db)).nachricht()
    assert n["modelle"]["gespraech"]["wahl"] == mw.AUTOMATISCH
    assert "Admin" in n["modelle"]["gespraech"]["hinweis"] and n["haus_stimme"] == "ono_anna"


async def test_admin_modell_geht_vor(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor, claude_modell=HAIKU, modell_gespraech=SONNET, modell_bilder=HAIKU)
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert la.person_wunsch("gespraech", z) is None
    assert la.person_wunsch("vision", z) == ("claude", HAIKU)


@pytest.mark.parametrize("art", ["platz", "schaufenster"])
async def test_laborprofil_bekommt_nie_eine_wahl(tresor, art):
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(modell_gespraech="qwen3.6-35b", tts_stimme="ryan", stt="haus", tts="haus")
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor, labor_art=art)
    assert z.quelle == "labor" and z.modell_wahl == () and z.tts_stimme is None


async def test_ohne_migration_0024_gilt_der_stand_davor(tresor, log):
    db = FakeDb(ohne_0024=True)
    db.zeilen[NIKO] = _claude_zeile(tresor)
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    assert (z.art, z.quelle, z.modell_wahl) == ("claude", "profil", ())
    assert any("0024" in zeile for zeile in log)


# --- Setzen: modell_setzen ------------------------------------------------------------------------------------------


async def test_hausprofil_waehlt_ein_hausmodell_mit_zeile_in_actions(tresor):
    db = FakeDb()
    stand = await mz.modell_setzen(NIKO, "gespraech", "qwen3.6-35b", db=db, tresor=tresor)
    assert db.zeilen[NIKO]["modell_gespraech"] == "qwen3.6-35b"
    n = stand.nachricht(aktion="modell")
    assert n["modelle"]["gespraech"]["wahl"] == "qwen3.6-35b" and n["wirksam"] == "ab der nächsten Sitzung"
    assert len(db.aktionen) == 1
    uid, werkzeug, params, grund = db.aktionen[0]
    assert (uid, werkzeug) == (NIKO, mz.MODELL_WERKZEUG)
    assert json.loads(params) == {"bereich": "gespraech", "modell": "qwen3.6-35b", "vorher": mw.AUTOMATISCH}
    assert "nächsten Sitzung" in grund


async def test_automatisch_leert_die_wahl(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(modell_hintergrund="gemma4-31b")
    stand = await mz.modell_setzen(NIKO, "hintergrund", "automatisch", db=db, tresor=tresor)
    assert db.zeilen[NIKO]["modell_hintergrund"] is None
    assert stand.nachricht()["modelle"]["hintergrund"]["wahl"] == mw.AUTOMATISCH
    assert json.loads(db.aktionen[0][2])["vorher"] == "gemma4-31b"


async def test_vom_admin_festgelegt_ist_gesperrt(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(nur_haus=True)
    with pytest.raises(mz.ZugangFehler, match="Admin"):
        await mz.modell_setzen(NIKO, "gespraech", "gemma4-31b", db=db, tresor=tresor)
    assert db.aktionen == [] and not [s for s in db.sql if s.startswith("insert")]
    n = (await mz.stand_laden(NIKO, db=db)).nachricht()
    assert "Admin" in n["modell_sperre"]


async def test_hausprofil_bekommt_kein_claude_und_fragt_anthropic_nie(tresor):
    db = FakeDb()
    gesehen: list = []
    with pytest.raises(mz.ZugangFehler, match="nicht wählbar"):
        await mz.modell_setzen(NIKO, "gespraech", SONNET, db=db, tresor=tresor, testen=_pruefer(gesehen=gesehen))
    assert gesehen == [] and db.aktionen == []


async def test_claude_wahl_wird_mit_dem_eigenen_schluessel_geprueft(tresor, log):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor)
    gesehen: list = []
    stand = await mz.modell_setzen(NIKO, "gespraech", SONNET, db=db, tresor=tresor, testen=_pruefer(gesehen=gesehen))
    assert gesehen == [(API, None, SONNET)]
    assert db.zeilen[NIKO]["modell_gespraech"] == SONNET
    n = stand.nachricht(aktion="modell")
    assert n["modelle"]["gespraech"]["wahl"] == SONNET and n["modell"] == "Claude Sonnet 5.5"
    text = json.dumps(n) + "".join(log) + repr(db.aktionen)
    assert API not in text and API[:20] not in text


async def test_claude_lehnt_das_modell_ab(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor)
    with pytest.raises(mz.ZugangFehler, match="darf dieses Modell nicht"):
        await mz.modell_setzen(NIKO, "bilder", "claude-opus-5-5", db=db, tresor=tresor,
                               testen=_pruefer("Der Schlüssel darf dieses Modell nicht nutzen (403)"))
    assert db.zeilen[NIKO].get("modell_bilder") is None and db.aktionen == []


@pytest.mark.parametrize("bereich,wert", [("gespraech", "sokrates-steuer"), ("unbekannt", "gemma4-31b"), (None, None),
                                          ("gespraech", ["gemma4-31b"]), ("bilder", "laaj-judge"), ("gespraech", "")])
async def test_unbekannte_werte_werden_abgelehnt(tresor, bereich, wert):
    db = FakeDb()
    with pytest.raises(mz.ZugangFehler):
        await mz.modell_setzen(NIKO, bereich, wert, db=db, tresor=tresor)
    assert db.aktionen == [] and not [s for s in db.sql if s.startswith("insert")]


async def test_gleiche_wahl_schreibt_nichts(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(modell_gespraech="gemma4-31b")
    await mz.modell_setzen(NIKO, "gespraech", "gemma4-31b", db=db, tresor=tresor)
    await mz.modell_setzen(NIKO, "bilder", "automatisch", db=db, tresor=tresor)
    assert db.aktionen == [] and not [s for s in db.sql if s.startswith("insert")]


@pytest.mark.parametrize("fake", [{"ohne_0024": True}, {"ohne_rechte": True}])
async def test_ohne_migration_0024_ein_klarer_satz(tresor, fake):
    db = FakeDb(**fake)
    with pytest.raises(mz.ZugangFehler, match="noch nicht freigeschaltet") as fehler:
        await mz.modell_setzen(NIKO, "gespraech", "gemma4-31b", db=db, tresor=tresor)
    assert "Migration" not in str(fehler.value) and db.aktionen == []


async def test_zu_viele_wechsel_werden_gebremst(tresor):
    db = FakeDb()
    werte = ["gemma4-31b", "qwen3.6-35b"]
    for i in range(mz.WAHL_JE_FENSTER):
        await mz.modell_setzen(NIKO, "gespraech", werte[i % 2], db=db, tresor=tresor)
    with pytest.raises(mz.ZugangFehler, match="Zu viele Wechsel"):
        await mz.modell_setzen(NIKO, "gespraech", werte[mz.WAHL_JE_FENSTER % 2], db=db, tresor=tresor)
    assert len(db.aktionen) == mz.WAHL_JE_FENSTER


async def test_ohne_datenbank_und_mit_falschem_profil(tresor):
    with pytest.raises(mz.ZugangFehler, match="Profil ungültig"):
        await mz.modell_setzen("kein-profil", "gespraech", "gemma4-31b", db=FakeDb(), tresor=tresor)
    leer = FakeDb()
    leer.configured = False
    with pytest.raises(mz.ZugangFehler, match="Keine Datenbank"):
        await mz.modell_setzen(NIKO, "gespraech", "gemma4-31b", db=leer, tresor=tresor)


# --- Stimme im Haus: haus_stimme_setzen -----------------------------------------------------------------------------


def test_nur_die_freigegebenen_stimmen_in_dieser_reihenfolge():
    """Entscheidung von Niko vom 16.11.2026 nach den Hörproben: sohee (Standard), uncle_fu, ono_anna; an genau einer Stelle im Kern."""
    assert sa.HAUS_STIMMEN_IDS == ("sohee", "uncle_fu", "ono_anna")
    assert [s["id"] for s in sa.haus_stimmen()] == list(sa.HAUS_STIMMEN_IDS)
    assert len({s["name"] for s in sa.haus_stimmen()}) == len(sa.HAUS_STIMMEN_IDS)
    assert "nativ deutsch" in sa.STIMMEN_HINWEIS
    quellen = [d for d in (WURZEL / "voice-core").glob("*.py") if not d.name.startswith("test_")]
    for name in ("serena", "vivian", "aiden", "ryan", "eric", "dylan"):  # nicht freigegeben: nirgends im Kern als Wert
        assert not [d.name for d in quellen if f'"{name}"' in d.read_text(encoding="utf-8")], name


def test_standard_ist_die_erste_freigegebene_oder_die_des_kerns(monkeypatch):
    monkeypatch.setenv("WAMO_TTS_HAUS_STIMME", "Uncle_Fu ")
    assert sa.haus_stimme_standard() == "uncle_fu"
    monkeypatch.setenv("WAMO_TTS_HAUS_STIMME", "aiden")  # nicht freigegeben: gesprochen wird trotzdem nur aus der Liste
    assert sa.haus_stimme_standard() == "sohee"
    assert sa.haus_tts(sa.Baustein("haus", "haus", "wamo-tts-haus", stimme="ryan"))._stimme == "sohee"


async def test_stimme_im_haus_waehlen_und_zuruecksetzen():
    db = FakeDb()
    db.zeilen[NIKO] = _zeile(nur_haus=True)  # der Zwang des Admins sperrt die Stimme nicht (D3)
    stand = await mz.haus_stimme_setzen(NIKO, "uncle_fu", db=db)
    assert db.zeilen[NIKO]["tts_stimme"] == "uncle_fu" and stand.nachricht()["haus_stimme"] == "uncle_fu"
    stand = await mz.haus_stimme_setzen(NIKO, "standard", db=db)
    assert db.zeilen[NIKO]["tts_stimme"] is None and stand.nachricht()["haus_stimme"] is None
    assert [json.loads(a[2]) for a in db.aktionen] == [{"haus_stimme": "uncle_fu", "vorher": None},
                                                        {"haus_stimme": None, "vorher": "uncle_fu"}]
    assert {a[1] for a in db.aktionen} == {mz.STIMME_WERKZEUG}
    # die Standardstimme selbst zu wählen heißt Standard: nichts zu schreiben
    await mz.haus_stimme_setzen(NIKO, sa.haus_stimme_standard(), db=db)
    assert len(db.aktionen) == 2 and db.zeilen[NIKO]["tts_stimme"] is None


@pytest.mark.parametrize("wert", ["hedda", "ryan", "aiden", "serena", "SOHEE", None, ["sohee"], "sohee; drop", ""])
async def test_werte_ausserhalb_der_liste_lehnt_der_kern_ab(wert):
    db = FakeDb()
    with pytest.raises(mz.ZugangFehler, match="Stimme"):
        await mz.haus_stimme_setzen(NIKO, wert, db=db)
    assert db.aktionen == [] and not [s for s in db.sql if s.startswith("insert")]


async def test_stimme_ohne_migration_0024():
    with pytest.raises(mz.ZugangFehler, match="noch nicht freigeschaltet"):
        await mz.haus_stimme_setzen(NIKO, "uncle_fu", db=FakeDb(ohne_rechte=True))


# --- Stand für die Oberfläche --------------------------------------------------------------------------------------


async def test_stand_nennt_angebot_wahl_und_stimmen(tresor, monkeypatch):
    monkeypatch.setenv("WAMO_TTS_HAUS_STIMME", "sohee")
    db = FakeDb()
    n = (await mz.stand_laden(NIKO, db=db)).nachricht()
    assert set(n["modelle"]) == set(mw.BEREICHE)
    for bereich in mw.BEREICHE:
        eintrag = n["modelle"][bereich]
        assert eintrag["wahl"] == mw.AUTOMATISCH and eintrag["optionen"]
        assert {o["art"] for o in eintrag["optionen"]} == {"haus"}
        assert set(eintrag["optionen"][0]) == {"id", "name", "art", "zeile"}
    assert n.get("modell_sperre") is None
    assert [s["id"] for s in n["haus_stimmen"]] == list(sa.HAUS_STIMMEN_IDS)
    assert n["haus_stimme"] is None and n["haus_stimme_standard"] == "sohee"
    db.zeilen[NIKO] = _claude_zeile(tresor)
    n = (await mz.stand_laden(NIKO, db=db)).nachricht()
    assert {o["art"] for o in n["modelle"]["gespraech"]["optionen"]} == {"haus", "claude"}


async def test_gespeicherte_claude_wahl_im_hausmodus_mit_hinweis(tresor):
    db = FakeDb()
    db.zeilen[NIKO] = _claude_zeile(tresor, modell_modus="nur_haus", modell_gespraech=SONNET)
    n = (await mz.stand_laden(NIKO, db=db)).nachricht()
    assert n["modelle"]["gespraech"]["wahl"] == mw.AUTOMATISCH
    assert "Claude Sonnet 5.5" in n["modelle"]["gespraech"]["hinweis"]


async def test_nachricht_der_sitzung_kennt_modell_und_haus_stimme(tresor):
    db = FakeDb()
    gesendet: list[dict] = []

    async def senden(n: dict) -> None:
        gesendet.append(n)

    await mz.modellzugang_nachricht(NIKO, {"aktion": "modell", "bereich": "bilder", "modell": "gemma4-31b"}, senden, db=db,
                                    tresor=tresor)
    assert gesendet[-1]["aktion"] == "modell" and gesendet[-1]["modelle"]["bilder"]["wahl"] == "gemma4-31b"
    await mz.modellzugang_nachricht(NIKO, {"aktion": "haus_stimme", "stimme": "ono_anna"}, senden, db=db)
    assert gesendet[-1]["aktion"] == "haus_stimme" and gesendet[-1]["haus_stimme"] == "ono_anna"
    await mz.modellzugang_nachricht(NIKO, {"aktion": "haus_stimme", "stimme": "ryan"}, senden, db=db)
    assert "Unbekannte Stimme" in gesendet[-1]["fehler"] and gesendet[-1]["haus_stimme"] == "ono_anna"
    await mz.modellzugang_nachricht(NIKO, {"aktion": "modell", "bereich": "gespraech", "modell": SONNET}, senden, db=db,
                                    tresor=tresor)
    assert gesendet[-1]["aktion"] == "modell" and "nicht wählbar" in gesendet[-1]["fehler"]


# --- Wirkung in der Sitzung (llm_anbieter.waehlen, Boss) ------------------------------------------------------------


@pytest.fixture
def boss_frei(monkeypatch):
    """Boss entscheidet (keine Übersteuerung des Betriebs), Gateway ohne Netz und ohne Probleme."""
    for name in ("WAMO_LLM_ANBIETER", "WAMO_LLM_LERNEN", "WAMO_LLM_VISION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "gateway-test")
    probleme: dict[str, str] = {}

    async def problem(modell):
        return probleme.get(modell)

    monkeypatch.setattr(la, "litellm_problem", problem)
    return probleme


def _cz(**kw) -> Zugang:
    return Zugang(NIKO, "claude", "profil", claude_schluessel=API, **kw)


async def test_claude_profil_mit_hausmodell_fuers_gespraech(boss_frei):
    z = _cz(modell_wahl=(("gespraech", "qwen3.6-35b"),))
    w = await la.waehlen("gespraech", z)
    assert (w.anbieter, w.modell, w.grund) == ("litellm", "qwen3.6-35b", None)
    assert (await la.waehlen("lernen", z)).modell == boss.rangliste("lernen", claude_erlaubt=True)[0].alias  # ohne Wahl: Boss
    assert la.konfiguration("gespraech", z) == ("litellm", "qwen3.6-35b")


async def test_hausprofil_mit_wahl_und_rueckfall_mit_grund(boss_frei):
    z = Zugang.haus(NIKO, "keiner", modell_wahl=(("gespraech", "qwen3.8-27b"),))
    assert (await la.waehlen("gespraech", z)).modell == "qwen3.8-27b"
    boss_frei["qwen3.8-27b"] = "das Gateway bietet das Modell 'qwen3.8-27b' nicht an"
    w = await la.waehlen("gespraech", z)
    assert w.modell == "gemma4-31b" and "Qwen 3.8 27B" in (w.grund or "")


async def test_claude_wahl_fuer_bilder_und_standard_fuer_den_rest(boss_frei):
    z = _cz(modell_wahl=(("bilder", SONNET),))
    assert la.claude_standardmodell("vision", z) == SONNET
    assert la.claude_standardmodell("gespraech", z) == HAIKU
    w = await la.waehlen("vision", z)
    assert (w.anbieter, w.modell) == ("claude", SONNET)
    assert (await la.waehlen("gespraech", z)).modell == HAIKU


async def test_admin_modell_vor_der_wahl_im_claude_standard():
    z = _cz(claude_modell=HAIKU, modell_wahl=(("gespraech", SONNET),))
    assert la.claude_standardmodell("gespraech", z) == HAIKU


async def test_hausprofil_nie_claude_auch_mit_manipuliertem_zugang(boss_frei):
    z = Zugang.haus(NIKO, "keiner", modell_wahl=(("gespraech", SONNET),))
    assert la.person_wunsch("gespraech", z) is None
    w = await la.waehlen("gespraech", z)
    assert w.anbieter == "litellm"


async def test_vorgabe_des_betriebs_geht_vor_mit_grund(monkeypatch, boss_frei):
    monkeypatch.setenv("WAMO_LLM_MODELL", "gemma4-31b")
    z = Zugang.haus(NIKO, "keiner", modell_wahl=(("gespraech", "qwen3.6-35b"),))
    w = await la.waehlen("gespraech", z)
    assert w.modell == "gemma4-31b" and la.BETRIEB_VOR_WAHL in (w.grund or "")
    monkeypatch.setenv("WAMO_LLM_ANBIETER", "claude")  # Betrieb legt Claude fest: die Hauswahl der Person gilt nicht
    w = await la.waehlen("gespraech", _cz(modell_wahl=(("gespraech", "qwen3.6-35b"),)))
    assert w.anbieter == "claude" and la.BETRIEB_VOR_WAHL in (w.grund or "")


async def test_zusammenfassung_folgt_der_wahl_fuer_lernen_und_zusammenfassung(boss_frei, monkeypatch):
    """Pipecat fasst nur dann mit dem Gesprächsmodell zusammen, wenn beides dasselbe Claude-Modell ist; sonst ein eigener Dienst."""
    async def kein_problem(_zugang):
        return None

    monkeypatch.setattr(la, "claude_problem", kein_problem)
    assert await la.zusammenfassung_llm(_cz()) is None  # beides Haiku: wie bisher
    for z, modell in ((_cz(modell_wahl=(("hintergrund", "claude-opus-5-5"),)), "claude-opus-5-5"),
                      (_cz(modell_wahl=(("gespraech", "claude-opus-5-5"),)), HAIKU),
                      (_cz(modell_wahl=(("gespraech", "gemma4-31b"),)), HAIKU),
                      (_cz(modell_wahl=(("hintergrund", "gemma4-31b"),)), "gemma4-31b")):
        dienst = await la.zusammenfassung_llm(z)
        assert dienst is not None and dienst._settings.model == modell, (z.modell_wahl, modell)


async def test_betrieb_legt_nur_den_anbieter_fest_die_wahl_fuellt_das_modell(monkeypatch, boss_frei):
    monkeypatch.setenv("WAMO_LLM_ANBIETER", "litellm")
    w = await la.waehlen("gespraech", _cz(modell_wahl=(("gespraech", "qwen3.6-35b"),)))
    assert (w.anbieter, w.modell, w.grund) == ("litellm", "qwen3.6-35b", None)
    assert (await la.waehlen("gespraech", _cz())).modell == boss.hausstandard("gespraech")


async def test_boss_aufgaben_folgen_keiner_wahl(boss_frei):
    z = _cz(modell_wahl=(("bilder", "claude-opus-5-5"), ("gespraech", "claude-opus-5-5")))
    w = await boss.waehlen("vision", z, baustein="boss_bild", probe=False)
    assert w.modell != "claude-opus-5-5"
    w = await boss.waehlen("gespraech", z, baustein="boss_einordnen", probe=False)
    assert w.modell == HAIKU


async def test_nur_spalten_aus_der_festen_liste():
    with pytest.raises(ValueError):
        await mz._spalte_schreiben(FakeDb(), NIKO, "nur_haus", "true")


# --- Stimme im Haus in der Sitzung -----------------------------------------------------------------------------------


async def test_sitzung_spricht_mit_der_gewaehlten_stimme(monkeypatch):
    env = {"WAMO_STT_ANBIETER": "", "WAMO_TTS_ANBIETER": "", "WAMO_TTS_HAUS_MODELL": "wamo-tts-haus",
           "WAMO_TTS_HAUS_STIMME": "sohee", "WAMO_STT_HAUS_MODELL": "wamo-stt-haus",
           "LITELLM_BASE_URL": "http://gateway.test.invalid:4000/v1", "LITELLM_API_KEY": "k"}
    with mock.patch.dict("os.environ", env), mock.patch.object(sa, "litellm_problem", mock.AsyncMock(return_value=None)):
        w = await sa.sprach_wahl(SimpleNamespace(stt="soniox", tts="haus", tts_stimme="uncle_fu"))
        assert (w.stt.anbieter, w.tts.anbieter, w.tts.stimme) == ("soniox", "haus", "uncle_fu")
        assert sa.haus_tts(w.tts)._stimme == "uncle_fu"
        w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus", tts_stimme="ryan"))  # nicht freigegeben: Standard des Kerns
        assert (w.stt.anbieter, w.tts.stimme) == ("haus", "sohee")
        w = await sa.sprach_wahl(SimpleNamespace(stt="haus", tts="haus", tts_stimme="uncle_fu"), labor=True)
        assert (w.stt.anbieter, w.tts.anbieter, w.tts.stimme) == ("soniox", "soniox", None)


# --- HTTP und Labor ---------------------------------------------------------------------------------------------------


@pytest.fixture
def http_db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(mz, "shared_database", lambda: fake)
    monkeypatch.setenv("WAMO_SCHLUESSEL_KEK", kek_erzeugen())
    return fake


def _client(monkeypatch, ich: Identity) -> TestClient:
    async def pruefen(_request):
        return ich

    monkeypatch.setattr(api, "identitaet", pruefen)
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    return TestClient(app)


def test_route_setzt_modell_und_stimme_nur_fuer_das_eigene_profil(http_db, monkeypatch):
    c = _client(monkeypatch, Identity(user_id=NIKO, name="Niko", rolle="mitglied", anrede="du", anmeldung=1.0))
    r = c.post("/wamo/api/modellzugang", json={"aktion": "modell", "bereich": "gespraech", "modell": "gemma4-31b",
                                               "user_id": "7d3e9c1a-2b4f-4e6a-8c0d-1f2a3b4c5d6e"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["modelle"]["gespraech"]["wahl"] == "gemma4-31b"
    assert list(http_db.zeilen) == [NIKO]  # die Profil-ID kommt nur aus der Identität
    r = c.post("/wamo/api/modellzugang", json={"aktion": "haus_stimme", "stimme": "uncle_fu"})
    assert r.json()["haus_stimme"] == "uncle_fu"


@pytest.mark.parametrize("art", ["platz", "schaufenster"])
def test_laborprofile_403_fuer_jede_wahl(http_db, monkeypatch, art):
    ich = Identity(user_id=NIKO, name="Labor", rolle="mitglied", anrede="du", anmeldung=1.0, labor_art=art, labor_platz=3,
                   labor_aktiv=True)
    c = _client(monkeypatch, ich)
    for daten in ({"aktion": "modell", "bereich": "gespraech", "modell": "gemma4-31b"},
                  {"aktion": "haus_stimme", "stimme": "sohee"}):
        r = c.post("/wamo/api/modellzugang", json=daten)
        assert r.status_code == 403 and r.json()["code"] == labor.CODE_PFAD_GESPERRT
        assert not labor.client_nachricht_erlaubt(art, "modellzugang", daten)
    assert http_db.zeilen == {} and http_db.sql == [] and http_db.aktionen == []
