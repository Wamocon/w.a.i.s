"""Tests für die Admin-Übersicht "Neue Mitglieder" (mitglieder_admin_api.py, Migration 0022).

Ohne Datenbank: shared_database und identitaet werden ersetzt. Geprüft wird, dass nur Admins die Liste sehen, Laborprofile nie,
dass die Antwort genau die erlaubten Felder enthält (nie E-Mail, Schlüssel oder Token) und dass Fehler der Datenbank nichts
Internes nach außen geben.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mitglieder_admin_api as api
from auth_gate import Identity

ADMIN = "00000000-0000-4000-8000-0000000022a1"
PERSON = "00000000-0000-4000-8000-0000000022b1"
FELDER = {"user_id", "anzeigename", "rolle", "aktiv", "angelegt", "letzte_anmeldung", "faktor_bestaetigt", "passwort_stand",
          "geraet_stand", "modellzugang", "stimmabdruck"}


def zeile(**teil) -> dict:
    z = {
        "user_id": PERSON,
        "anzeigename": "Person A",
        "rolle": "mitglied",
        "aktiv": True,
        "angelegt": datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc),
        "letzte_anmeldung": None,
        "faktor_bestaetigt": False,
        "passwort_stand": None,
        "geraet_stand": "keins",
        "modellzugang": "haus",
        "stimmabdruck": False,
    }
    z.update(teil)
    return z


class FakeDb:
    configured = True

    def __init__(self) -> None:
        self.sql: list[tuple[str, tuple]] = []
        self.liste: list[dict] = [zeile()]
        self.fehler: BaseException | None = None

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    async def fetch(self, sql, *args):
        self.sql.append((sql, args))
        if self.fehler:
            raise self.fehler
        return self.liste


class Kontext:
    rolle = "admin"
    labor_art: str | None = None


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(api, "shared_database", lambda: fake)
    return fake


@pytest.fixture
def ctx(monkeypatch):
    k = Kontext()

    async def identitaet(_request):
        return Identity(user_id=ADMIN, name="Admin", rolle=k.rolle, anrede="du", anmeldung=1.0, labor_art=k.labor_art)

    monkeypatch.setattr(api, "identitaet", identitaet)
    monkeypatch.setattr(api, "_versuche", {})
    return k


@pytest.fixture
def client(db, ctx):
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    return TestClient(app)


URL = "/wamo/api/admin/neue-mitglieder"


def test_admin_sieht_die_liste_mit_genau_den_erlaubten_feldern(client, db):
    db.liste = [zeile(), zeile(user_id=ADMIN, anzeigename="Admin", rolle="admin", faktor_bestaetigt=True,
                               letzte_anmeldung=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
                               passwort_stand="erledigt", geraet_stand="aktiv", modellzugang="token", stimmabdruck=True)]
    r = client.get(URL)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    mitglieder = r.json()["mitglieder"]
    assert [set(m) for m in mitglieder] == [FELDER, FELDER]
    assert mitglieder[0]["angelegt"] == "2026-11-15T09:00:00+00:00"
    assert mitglieder[1]["letzte_anmeldung"] == "2026-11-16T08:00:00+00:00"
    assert mitglieder[1]["passwort_stand"] == "erledigt"
    sql, args = db.sql[0]
    assert "wamo_test.neue_mitglieder($1::uuid)" in sql
    assert args == (ADMIN,)


def test_unbekannte_werte_und_zusatzfelder_fallen_weg(client, db):
    db.liste = [zeile(geraet_stand="quatsch", modellzugang="sk-ant-api03-geheim", passwort_stand="x" * 80, email="a@b.c",
                      claude_schluessel=b"geheim", anzeigename="Name‮ mit Steuerzeichen\x00")]
    m = client.get(URL).json()["mitglieder"][0]
    assert set(m) == FELDER
    assert m["geraet_stand"] is None
    assert m["modellzugang"] is None
    assert m["passwort_stand"] is None
    assert "‮" not in m["anzeigename"] and "\x00" not in m["anzeigename"]
    assert "geheim" not in str(m)


def test_zeile_ohne_gueltige_kennung_wird_verworfen(client, db):
    db.liste = [zeile(user_id="keine-uuid"), zeile()]
    assert len(client.get(URL).json()["mitglieder"]) == 1


@pytest.mark.parametrize("rolle, labor", [("mitglied", None), ("admin", "platz"), ("mitglied", "schaufenster")])
def test_mitglied_und_laborprofil_bekommen_403_ohne_datenbank(client, db, ctx, rolle, labor):
    ctx.rolle, ctx.labor_art = rolle, labor
    r = client.get(URL)
    assert r.status_code == 403
    assert db.sql == []


def test_datenbank_lehnt_ab_heisst_403(client, db):
    fehler = asyncpg.exceptions.InsufficientPrivilegeError("neue_mitglieder: nur für einen aktiven Admin")
    db.fehler = fehler
    r = client.get(URL)
    assert r.status_code == 403
    assert "neue_mitglieder" not in r.text


def test_datenbankfehler_heisst_503_ohne_interne_meldung(client, db):
    db.fehler = asyncpg.exceptions.UndefinedFunctionError("function wamo_test.neue_mitglieder(uuid) does not exist")
    r = client.get(URL)
    assert r.status_code == 503
    assert "wamo_test" not in r.text and "function" not in r.text


def test_ohne_datenbank_503(client, monkeypatch):
    class Leer:
        configured = False

    monkeypatch.setattr(api, "shared_database", lambda: Leer())
    assert client.get(URL).status_code == 503


def test_drosselung_je_admin(client, db, monkeypatch):
    monkeypatch.setattr(api, "LISTE_GRENZE", (3, 60.0))
    assert [client.get(URL).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_route_ist_im_kern_eingetragen():
    import wamo_api

    assert "mitglieder_admin_api" in wamo_api.ROUTEN_MODULE


class WertZeile(dict):
    """Wie asyncpg.Record bei "in": prüft Werte statt Schlüssel. Die Route darf sich darauf nicht verlassen."""

    def __contains__(self, wert: object) -> bool:
        return wert in self.values()


def test_zeilen_wie_asyncpg_record_werden_gelesen(client, db):
    db.liste = [WertZeile(zeile())]
    mitglieder = client.get(URL).json()["mitglieder"]
    assert len(mitglieder) == 1
    assert mitglieder[0]["user_id"] == PERSON


def test_passwortstand_nur_die_vier_werte(client, db):
    db.liste = [zeile(passwort_stand="offen"), zeile(user_id=ADMIN, passwort_stand="beliebig")]
    staende = [m["passwort_stand"] for m in client.get(URL).json()["mitglieder"]]
    assert staende == ["offen", None]
