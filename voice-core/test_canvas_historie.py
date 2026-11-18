"""Tests der Route GET /wamo/api/canvas/historie (canvas_historie.py): Historie des Canvas, eigene Elemente und mit der Person geteilte,
nur über die geprüfte Identität, nie für Laborprofile, keine Datenbankmeldungen nach außen. Keine echte Datenbank.

Ausführen:  python -m pytest -q test_canvas_historie.py   (im Ordner voice-core/)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import canvas_historie as api
import labor
import wamo_api
from auth_gate import Identity
from memory import DatabaseUnavailable

ICH = "123e4567-e89b-12d3-a456-426614174000"
ANDERER = "7d3e9c1a-2b4f-4e6a-8c0d-1f2a3b4c5d6e"


def eigen(i: int, typ: str = "document", titel: str | None = None) -> dict:
    return {"id": f"aaaaaaaa-0000-4000-8000-{i:012d}", "title": titel or f"Dokument {i}", "typ": typ,
            "zeit": datetime(2026, 11, 18, 9, i % 60, tzinfo=timezone.utc)}


def geteilt(i: int, von: str | None = "Kollegin", recht: str = "lesen") -> dict:
    return {**eigen(100 + i, "table", f"Geteilt {i}"), "von": von, "recht": recht}


class FalscheDatenbank:
    configured = True

    def __init__(self):
        self.eigene = [eigen(i) for i in range(1, 4)] + [eigen(4, "mermaid", "Ablauf"), eigen(5, "whiteboard", "Alt")]
        self.geteilte = [geteilt(1), geteilt(2, von=None, recht="bearbeiten")]
        self.abfragen: list[tuple[str, tuple]] = []
        self.fehler: BaseException | None = None

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    async def fetch(self, sql: str, *args):
        self.abfragen.append((sql, args))
        if self.fehler:
            raise self.fehler
        return self.geteilte if "teilungen" in sql else self.eigene


class Kontext:
    gesperrt = False
    labor_art: str | None = None


@pytest.fixture
def ctx(monkeypatch):
    k = Kontext()

    async def identitaet(_request):
        if k.gesperrt:
            raise HTTPException(403, "kein aktives WAMO-Profil oder zweiter Faktor fehlt")
        return Identity(user_id=ICH, name="Ich", rolle="mitglied", anrede="du", anmeldung=1.0, labor_art=k.labor_art,
                        labor_platz=3 if k.labor_art else None, labor_aktiv=bool(k.labor_art))

    monkeypatch.setattr(api, "identitaet", identitaet)
    return k


@pytest.fixture
def db(monkeypatch):
    fake = FalscheDatenbank()
    monkeypatch.setattr(api, "shared_database", lambda: fake)
    return fake


@pytest.fixture
def client(ctx, db):
    app = FastAPI()
    app.include_router(api.router, prefix="/wamo/api")
    return TestClient(app)


def test_route_ist_in_der_modulliste_der_kern_api():
    assert "canvas_historie" in wamo_api.ROUTEN_MODULE


def test_eigene_und_geteilte_eintraege_mit_titel_art_und_zeit(client):
    r = client.get("/wamo/api/canvas/historie")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    daten = r.json()
    eigene, geteilte = daten["eigene"], daten["geteilt"]
    assert [e["titel"] for e in eigene] == ["Dokument 1", "Dokument 2", "Dokument 3", "Ablauf"]  # unbekannte Art fällt weg
    assert eigene[0] == {"id": "aaaaaaaa-0000-4000-8000-000000000001", "titel": "Dokument 1", "art": "dokument",
                         "zeit": "2026-11-18T09:01:00+00:00"}
    assert eigene[3]["art"] == "mermaid"
    assert geteilte[0] == {"id": "aaaaaaaa-0000-4000-8000-000000000101", "titel": "Geteilt 1", "art": "tabelle",
                           "zeit": "2026-11-18T09:41:00+00:00", "von": "Kollegin", "recht": "lesen"}
    assert geteilte[1]["von"] is None and geteilte[1]["recht"] == "bearbeiten"


def test_profil_nur_aus_der_zugangskontrolle_und_nur_eigene_oder_geteilte_zeilen(client, db):
    client.get("/wamo/api/canvas/historie", params={"user_id": ANDERER}, headers={"X-User": ANDERER})
    (sql_eigen, args_eigen), (sql_geteilt, args_geteilt) = db.abfragen
    assert args_eigen[0] == ICH and args_geteilt[0] == ICH
    assert "w.user_id = $1::uuid" in sql_eigen and "w.parent_id is null" in sql_eigen
    assert "wamo_test.canvas_items" in sql_eigen and "teilungen" not in sql_eigen
    assert "x.empfaenger = $1::uuid" in sql_geteilt and "x.widerrufen_at is null" in sql_geteilt and "x.art = 'canvas'" in sql_geteilt
    # nie der Inhalt, nur Titel, Art und Zeit
    for sql in (sql_eigen, sql_geteilt):
        assert ".data" not in sql.split(" from ", 1)[0]
    # Grenzen stehen als Parameter in der Abfrage
    assert api.MAX_EIGENE in args_eigen and api.MAX_GETEILT in args_geteilt


def test_titel_werden_bereinigt_und_gekuerzt(client, db):
    db.eigene = [eigen(1, titel="Böse" + chr(0x202E) + "\x00 Zeile\nzwei " + "y" * 300)]
    db.geteilte = [{**geteilt(1), "von": "Name\x00" + chr(0x200B) + "X"}]
    daten = client.get("/wamo/api/canvas/historie").json()
    titel = daten["eigene"][0]["titel"]
    assert chr(0x202E) not in titel and "\x00" not in titel and "\n" not in titel and len(titel) <= api.TITEL_MAX
    assert daten["geteilt"][0]["von"] == "Name X"  # unsichtbare Zeichen werden zu Leerraum (persona.clean_inline)


def test_unbekanntes_recht_wird_lesen(client, db):
    db.geteilte = [geteilt(1, recht="alles")]
    assert client.get("/wamo/api/canvas/historie").json()["geteilt"][0]["recht"] == "lesen"


def test_laborprofile_bekommen_403_mit_code_und_die_datenbank_wird_nicht_gefragt(client, db, ctx):
    ctx.labor_art = "platz"
    r = client.get("/wamo/api/canvas/historie")
    assert r.status_code == 403
    assert r.json()["code"] == labor.CODE_PFAD_GESPERRT
    assert db.abfragen == []


def test_ohne_zugang_kommt_nichts(client, db, ctx):
    ctx.gesperrt = True
    assert client.get("/wamo/api/canvas/historie").status_code == 403
    assert db.abfragen == []


@pytest.mark.parametrize("fehler", [DatabaseUnavailable("x"), OSError("geheimer Pfad /etc/x")])
def test_datenbankfehler_ergibt_503_ohne_details(client, db, fehler):
    db.fehler = fehler
    r = client.get("/wamo/api/canvas/historie")
    assert r.status_code == 503
    assert "geheim" not in r.text and "/etc" not in r.text


def test_ohne_datenbank_503(client, monkeypatch):
    def fehlt():
        raise ValueError("WAMO_DATABASE_URL fehlt")

    monkeypatch.setattr(api, "shared_database", fehlt)
    assert client.get("/wamo/api/canvas/historie").status_code == 503
