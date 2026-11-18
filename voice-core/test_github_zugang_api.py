"""Tests der HTTP-Routen des GitHub-Zugangs (github_zugang_api.py): Profil nur aus der Identität, Laborprofile mit 403, nie ein Token in
Antworten oder Logs, Admin-Route nur für Admins, Rechte nur aus der festen Liste, Drosselung. Datenbank und GitHub sind Attrappen."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

import github_zugang as gz
import github_zugang_api as api
import wamo_api
from auth_gate import Identity
from schluessel import kek_erzeugen
from test_github_zugang import ADMIN, KLASSISCH, LABOR, PERSON, FakeDb, _pruefer


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(gz, "shared_database", lambda: fake)
    monkeypatch.setenv("WAMO_SCHLUESSEL_KEK", kek_erzeugen())
    monkeypatch.setenv(gz.ENV_SCHALTER, "an")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_PROFILE", f"{PERSON},{ADMIN}")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_MITGLIEDER", "an")
    monkeypatch.setattr(gz, "bei_github_pruefen", _pruefer())
    gz._versuche.clear()
    gz._rechte_versuche.clear()
    api._abrufe.clear()
    return fake


def _client(monkeypatch, uid=PERSON, rolle="mitglied", labor_art=None):
    async def identitaet(_request):
        return Identity(user_id=uid, name="Person", rolle=rolle, anrede="du", anmeldung=1.0, labor_art=labor_art,
                        labor_platz=1 if labor_art else None)

    monkeypatch.setattr(api, "identitaet", identitaet)
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    return TestClient(app)


@pytest.fixture
def log():
    zeilen: list[str] = []
    senke = logger.add(lambda m: zeilen.append(str(m)), level="DEBUG")
    yield zeilen
    logger.remove(senke)


def test_modul_ist_eingehaengt():
    assert "github_zugang_api" in wamo_api.ROUTEN_MODULE


def test_stand_speichern_loeschen_ohne_wert(db, monkeypatch, log):
    c = _client(monkeypatch)
    r = c.get("/wamo/api/github-zugang")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert (r.json()["type"], r.json()["hinterlegt"], r.json()["verfuegbar"]) == ("github_zugang", False, True)
    r = c.post("/wamo/api/github-zugang", json={"aktion": "speichern", "token": KLASSISCH, "user_id": ADMIN})
    d = r.json()
    assert d["hinterlegt"] is True and d["login"] == "person-eins" and KLASSISCH not in r.text
    assert PERSON in db.zugang and ADMIN not in db.zugang  # das Profil kommt nur aus der Identität
    r = c.post("/wamo/api/github-zugang", json={"aktion": "loeschen"})
    assert r.json()["hinterlegt"] is False and not db.zugang
    assert KLASSISCH not in "\n".join(log)


def test_body_zu_gross(db, monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/wamo/api/github-zugang", content=b'{"aktion": "speichern", "token": "' + b"x" * 5000 + b'"}',
               headers={"content-type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("methode, pfad", [("GET", "/wamo/api/github-zugang"), ("POST", "/wamo/api/github-zugang"),
                                           ("GET", "/wamo/api/admin/github-rechte"), ("POST", "/wamo/api/admin/github-rechte")])
def test_labor_immer_403_ohne_datenbank(db, monkeypatch, methode, pfad):
    c = _client(monkeypatch, uid=LABOR, labor_art="platz")
    r = c.request(methode, pfad, json={"aktion": "speichern", "token": KLASSISCH})
    assert r.status_code == 403 and r.json()["code"] == "labor_pfad_gesperrt" and db.sql == []


def test_admin_route_nur_fuer_admins(db, monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/wamo/api/admin/github-rechte").status_code == 403
    assert c.post("/wamo/api/admin/github-rechte", json={"user_id": PERSON, "scopes_ausnahmen": ["gist"]}).status_code == 403
    assert not db.rechte and db.sql == []


def test_admin_liste_und_setzen(db, monkeypatch):
    c = _client(monkeypatch, uid=ADMIN, rolle="admin")
    r = c.get("/wamo/api/admin/github-rechte")
    d = r.json()
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert d["erlaubbar"] == list(gz.SCOPES_AUSNAHMEN) and d["nie"] == list(gz.SCOPES_NIE)
    assert d["unbedenklich"] == list(gz.SCOPES_UNBEDENKLICH)
    assert {p["user_id"] for p in d["personen"]} == {PERSON, ADMIN}
    r = c.post("/wamo/api/admin/github-rechte", json={"user_id": PERSON.upper(), "scopes_ausnahmen": ["workflow"]})
    assert r.status_code == 200 and r.json() == {"user_id": PERSON, "scopes_ausnahmen": ["workflow"]}
    assert db.rechte[PERSON]["geaendert_von"] == ADMIN
    for falsch in ({"user_id": PERSON, "scopes_ausnahmen": ["delete_repo"]}, {"user_id": PERSON, "scopes_ausnahmen": "gist"},
                   {"user_id": PERSON, "scopes_ausnahmen": ["gist", "gist"]}, {"user_id": PERSON, "scopes_ausnahmen": ["read:org"]},
                   {"user_id": LABOR, "scopes_ausnahmen": ["gist"]}, {"user_id": "x", "scopes_ausnahmen": []}):
        r = c.post("/wamo/api/admin/github-rechte", json=falsch)
        assert r.status_code == 400 and r.json()["detail"], falsch
    assert db.rechte[PERSON]["scopes_ausnahmen"] == ["workflow"]


def test_admin_liste_gedrosselt(db, monkeypatch):
    c = _client(monkeypatch, uid=ADMIN, rolle="admin")
    for _ in range(api.LISTE_GRENZE[0]):
        assert c.get("/wamo/api/admin/github-rechte").status_code == 200
    assert c.get("/wamo/api/admin/github-rechte").status_code == 429


def test_admin_liste_ohne_tabelle(monkeypatch):
    fake = FakeDb(ohne_tabelle=True)
    monkeypatch.setattr(gz, "shared_database", lambda: fake)
    api._abrufe.clear()
    c = _client(monkeypatch, uid=ADMIN, rolle="admin")
    r = c.get("/wamo/api/admin/github-rechte")
    assert r.status_code == 503 and "0027" in r.json()["detail"]
