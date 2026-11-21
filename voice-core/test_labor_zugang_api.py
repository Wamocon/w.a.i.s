"""Tests der HTTP-Routen des Claude-Zugangs des Labors (labor_zugang_api.py): nur Admins ohne Laborprofil, schreibende Aufrufe nur mit frischem
zweiten Faktor (höchstens 60 Sekunden), höchstens 5 Schreibversuche in 10 Minuten, Fehler als {code, text}, nie ein Schlüssel in Antworten, Logs
oder actions. Datenbank und Anthropic sind Attrappen."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

import labor_zugang as lz
import labor_zugang_api as api
import wamo_api
from auth_gate import Identity
from schluessel import Tresor, kek_erzeugen
from test_labor_schluessel import ADMIN, GAST, MARKER, SCHLUESSEL_NEU, SERVER, FakeDb

PFAD = "/wamo/api/admin/labor-zugang"


def token(*, totp_vor: float | None = 10.0, aal: str = "aal2") -> str:
    jetzt = time.time()
    amr = [{"method": "password", "timestamp": int(jetzt - 3600)}]
    if totp_vor is not None:
        amr.append({"method": "totp", "timestamp": int(jetzt - totp_vor)})
    return jwt.encode({"sub": ADMIN, "aal": aal, "amr": amr}, "nur-fuer-tests-nur-fuer-tests-123456", algorithm="HS256")


def kopf(**kw) -> dict:
    return {"Authorization": f"Bearer {token(**kw)}"}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(lz, "shared_database", lambda: fake)
    monkeypatch.setenv("WAMO_SCHLUESSEL_KEK", kek_erzeugen())
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    api._abrufe.clear()
    api._schreibversuche.clear()
    return fake


@pytest.fixture
def test_anfragen(monkeypatch):
    """Ersetzt die Testanfrage bei Anthropic: merkt sich die Schlüssel, die sie bekam, und gelingt (oder wirft, was der Test vorgibt)."""
    zustand = {"schluessel": [], "wirft": None}

    async def pruefen(schluessel, workspace):
        zustand["schluessel"].append(schluessel)
        if zustand["wirft"]:
            raise zustand["wirft"]

    monkeypatch.setattr(lz, "schluessel_pruefen", pruefen)
    return zustand


def _client(monkeypatch, uid=ADMIN, rolle="admin", labor_art=None):
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
    assert "labor_zugang_api" in wamo_api.ROUTEN_MODULE


# --- Wer darf ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("methode", ["GET", "PUT", "DELETE"])
def test_laborprofil_immer_403_und_ohne_datenbank(db, monkeypatch, test_anfragen, methode):
    c = _client(monkeypatch, uid=GAST, rolle="admin", labor_art="platz")  # auch ein Laborprofil mit Rolle admin (is_admin lügt nie, die Route prüft doppelt)
    r = c.request(methode, PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 403 and r.json()["code"] == "labor_pfad_gesperrt" and r.headers["cache-control"] == "no-store"
    assert db.sql == [] and test_anfragen["schluessel"] == []


@pytest.mark.parametrize("methode", ["GET", "PUT", "DELETE"])
def test_mitglied_nie(db, monkeypatch, test_anfragen, methode):
    c = _client(monkeypatch, uid=GAST, rolle="mitglied")
    r = c.request(methode, PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 403 and r.json()["code"] == "nicht_berechtigt" and "Admins" in r.json()["text"]
    assert db.sql == [] and db.zeile is None and test_anfragen["schluessel"] == []


# --- Lesen -------------------------------------------------------------------------------------------------------------


def test_stand_ohne_zweiten_faktor_frisch_und_ohne_schluessel(db, monkeypatch):
    c = _client(monkeypatch)
    r = c.get(PFAD, headers=kopf(totp_vor=3000))  # der Code ist alt: Lesen geht trotzdem
    d = r.json()
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert (d["quelle"], d["endet_auf"]) == ("server", SERVER[-4:]) and SERVER not in r.text
    assert set(d) == {"quelle", "endet_auf", "workspace", "gesetzt_am", "geprueft_am", "hinweis"}


def test_abrufe_sind_begrenzt(db, monkeypatch):
    c = _client(monkeypatch)
    for _ in range(api.LISTE_GRENZE[0]):
        assert c.get(PFAD).status_code == 200
    r = c.get(PFAD)
    assert r.status_code == 429 and r.json()["code"] == "zu_oft"


def test_ohne_datenbank_503_als_code_und_text(db, monkeypatch):
    db.configured = False
    r = _client(monkeypatch).get(PFAD)
    assert r.status_code == 503 and r.json()["code"] == "datenbank" and r.json()["text"] and r.json()["detail"] == r.json()["text"]


# --- Setzen ------------------------------------------------------------------------------------------------------------


def test_setzen_mit_frischem_code_prueft_speichert_und_nennt_nur_das_ende(db, monkeypatch, test_anfragen):
    c = _client(monkeypatch)
    r = c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU, "user_id": GAST}, headers=kopf(totp_vor=30))
    d = r.json()
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert (d["quelle"], d["endet_auf"]) == ("gespeichert", SCHLUESSEL_NEU[-4:]) and SCHLUESSEL_NEU not in r.text and MARKER not in r.text
    assert test_anfragen["schluessel"] == [SCHLUESSEL_NEU]
    assert db.zeile["gesetzt_von"] == ADMIN  # die Person kommt nur aus der Identität, nie aus dem Body
    assert [a[1] for a in db.aktionen] == [lz.WERKZEUG_SETZEN]
    assert c.get(PFAD).json()["quelle"] == "gespeichert"


@pytest.mark.parametrize("totp_vor", [61, 600, None])
def test_ohne_frischen_zweiten_faktor_nichts_und_der_body_wird_nicht_gelesen(db, monkeypatch, test_anfragen, totp_vor):
    c = _client(monkeypatch)
    r = c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf(totp_vor=totp_vor))
    assert r.status_code == 403 and r.json()["code"] == "zweiter_faktor_zu_alt" and "Minute" in r.json()["text"]
    assert r.headers["cache-control"] == "no-store"
    assert db.zeile is None and db.aktionen == [] and test_anfragen["schluessel"] == []
    r = c.delete(PFAD, headers=kopf(totp_vor=totp_vor))
    assert r.status_code == 403 and r.json()["code"] == "zweiter_faktor_zu_alt"


def test_faktor_nur_aus_der_vergangenheit_und_nur_mit_aal2(db, monkeypatch, test_anfragen):
    c = _client(monkeypatch)
    assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf(totp_vor=-120)).status_code == 403  # aus der Zukunft
    assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf(aal="aal1")).status_code == 403
    assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}).status_code == 403  # kein Token im Header
    assert test_anfragen["schluessel"] == []


def test_faktor_frisch_grenzen():
    assert not api.faktor_frisch(None)
    assert api.faktor_frisch(1000.0, 1000.0) and api.faktor_frisch(1000.0, 1060.0) and api.faktor_frisch(1000.0, 996.0)
    assert not api.faktor_frisch(1000.0, 1060.5) and not api.faktor_frisch(1000.0, 994.0)


@pytest.mark.parametrize("body, code", [
    ({}, "schluessel_ungueltig"),
    ({"schluessel": ""}, "schluessel_ungueltig"),
    ({"schluessel": 12345}, "schluessel_ungueltig"),
    ({"schluessel": "kein-schluessel"}, "schluessel_ungueltig"),
    ({"schluessel": "sk-ant-oat01-" + "x" * 40}, "schluessel_ungueltig"),
    ({"schluessel": SCHLUESSEL_NEU, "workspace": "abc"}, "workspace_ungueltig"),
])
def test_ungueltige_eingaben_400_ohne_testanfrage(db, monkeypatch, test_anfragen, body, code):
    r = _client(monkeypatch).put(PFAD, json=body, headers=kopf())
    assert r.status_code == 400 and r.json()["code"] == code and r.json()["text"] and r.headers["cache-control"] == "no-store"
    assert test_anfragen["schluessel"] == [] and db.zeile is None


def test_body_zu_gross_und_kein_json(db, monkeypatch, test_anfragen):
    c = _client(monkeypatch)
    r = c.put(PFAD, content=b'{"schluessel": "' + b"x" * 5000 + b'"}', headers={**kopf(), "content-type": "application/json"})
    assert r.status_code == 413
    r = c.put(PFAD, content=b"das ist kein json " + SCHLUESSEL_NEU.encode(), headers={**kopf(), "content-type": "application/json"})
    assert r.status_code == 400 and MARKER not in r.text  # der Body wird nie zurückgespiegelt
    assert db.zeile is None and test_anfragen["schluessel"] == []


def test_wenn_anthropic_ablehnt_wird_nichts_gespeichert(db, monkeypatch, test_anfragen):
    test_anfragen["wirft"] = lz.LaborZugangFehler("schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401): ungültig.")
    r = _client(monkeypatch).put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 400 and r.json()["code"] == "schluessel_abgelehnt" and "401" in r.json()["text"]
    assert db.zeile is None and db.aktionen == []


def test_anthropic_nicht_erreichbar_ist_502(db, monkeypatch, test_anfragen):
    test_anfragen["wirft"] = lz.LaborZugangFehler("anthropic_nicht_erreichbar", "Anthropic ist gerade nicht erreichbar.", 502)
    r = _client(monkeypatch).put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 502 and r.json()["code"] == "anthropic_nicht_erreichbar"


def test_hoechstens_fuenf_schreibversuche_in_zehn_minuten(db, monkeypatch, test_anfragen):
    c = _client(monkeypatch)
    for _ in range(api.SCHREIB_GRENZE[0]):
        assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf()).status_code == 200
    r = c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 429 and r.json()["code"] == "zu_oft" and len(test_anfragen["schluessel"]) == 5
    assert c.delete(PFAD, headers=kopf()).status_code == 429  # Setzen und Entfernen teilen sich die Grenze
    assert c.get(PFAD).status_code == 200  # Lesen bleibt frei


def test_die_bremse_zaehlt_nur_je_admin_und_laesst_das_fenster_ablaufen():
    speicher: dict = {}
    assert all(api._bremse(speicher, "a", (5, 600.0), jetzt=float(i)) for i in range(5))
    assert not api._bremse(speicher, "a", (5, 600.0), jetzt=10.0)
    assert api._bremse(speicher, "b", (5, 600.0), jetzt=10.0)
    assert api._bremse(speicher, "a", (5, 600.0), jetzt=700.0)  # das Fenster ist vorbei


# --- Entfernen ---------------------------------------------------------------------------------------------------------


def test_entfernen_loescht_und_der_server_schluessel_gilt_wieder(db, monkeypatch, test_anfragen):
    c = _client(monkeypatch)
    assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf()).status_code == 200
    r = c.delete(PFAD, headers=kopf())
    d = r.json()
    assert r.status_code == 200 and (d["quelle"], d["endet_auf"]) == ("server", SERVER[-4:]) and db.zeile is None
    assert r.headers["cache-control"] == "no-store"
    assert [a[1] for a in db.aktionen] == [lz.WERKZEUG_SETZEN, lz.WERKZEUG_ENTFERNEN]


def test_unerwarteter_fehler_gibt_nur_einen_festen_satz(db, monkeypatch, log):
    async def kaputt(*a, **k):
        raise RuntimeError("Innenleben " + SCHLUESSEL_NEU)

    monkeypatch.setattr(lz, "setzen", kaputt)
    r = _client(monkeypatch).put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf())
    assert r.status_code == 500 and r.json()["code"] == "intern"
    assert MARKER not in r.text and MARKER not in "\n".join(log) and "RuntimeError" in "\n".join(log)


# --- Der Schlüssel erscheint nirgends ----------------------------------------------------------------------------------


def test_marker_in_keiner_antwort_keinem_log_und_keiner_protokollzeile(db, monkeypatch, test_anfragen, log):
    c = _client(monkeypatch)
    antworten = [
        c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU, "workspace": "kein-workspace"}, headers=kopf()),  # 400
        c.put(PFAD, content=SCHLUESSEL_NEU.encode(), headers={**kopf(), "content-type": "application/json"}),  # 400, kein JSON
        c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf(totp_vor=999)),  # 403, zu alt
        c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf()),  # 200
        c.get(PFAD),
        c.delete(PFAD, headers=kopf()),
    ]
    test_anfragen["wirft"] = lz.LaborZugangFehler("schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401).")
    antworten.append(c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf()))  # 400
    gesamt = "\n".join(a.text + repr(dict(a.headers)) for a in antworten) + "\n".join(log) + repr(db.aktionen) + "\n".join(db.sql)
    assert MARKER not in gesamt and SCHLUESSEL_NEU not in gesamt
    assert SCHLUESSEL_NEU[-4:] in repr(db.aktionen)  # nur "endet auf" steht im Protokoll
    assert [a.status_code for a in antworten] == [400, 400, 403, 200, 200, 200, 400]


def test_der_gespeicherte_schluessel_wirkt_erst_fuer_neue_laborsitzungen_und_nur_dort(db, monkeypatch, test_anfragen):
    """Ende zu Ende: gesetzt über die Route, danach liest zugang_laden ihn für ein Laborprofil, nicht für ein anderes."""
    import asyncio

    import modellzugang as mz

    tresor = Tresor.from_env()
    c = _client(monkeypatch)
    assert c.put(PFAD, json={"schluessel": SCHLUESSEL_NEU}, headers=kopf()).status_code == 200

    class ZugangsDb(FakeDb):
        async def fetchrow(self, sql, *args):
            if "model_access" in sql:
                return None
            return await db.fetchrow(sql, *args)

    d = ZugangsDb()
    labor = asyncio.run(mz.zugang_laden(GAST, db=d, tresor=tresor, labor_art="platz"))
    andere = asyncio.run(mz.zugang_laden(ADMIN, db=d, tresor=tresor))
    assert (labor.quelle, labor.claude_schluessel) == ("labor", SCHLUESSEL_NEU)
    assert (andere.quelle, andere.claude_schluessel) == ("keiner", None)
