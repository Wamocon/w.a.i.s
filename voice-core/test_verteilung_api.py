"""Tests der Kern-Routen für den Installer (verteilung_api.py, Paket P2, docs/ausrollen-neue-nutzer.md, Abschnitt 4.2 und 6.1).

Geprüft: nur die Datei aus dem Manifest (kein Pfad vom Client, Link aktuell nur innerhalb von staende/), Range, Ratengrenze, Kopfzeilen,
Laborprofil 403, fehlende oder unstimmige Ablage 503, Prüfsumme vor jeder Auslieferung, Eintrag in actions ohne Inhalt, dieselbe Prüfregel wie
am Server (Vertrag mit infra/sokrates2/wamo_verteilung_manifest.py). Ablage und Datenbank sind Attrappen in einem Wegwerf-Ordner.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import verteilung_api as va
from auth_gate import Identity

NIKO = "11111111-1111-4111-8111-111111111111"
MITGLIED = "22222222-2222-4222-8222-222222222222"
LABOR = "33333333-3333-4333-8333-333333333333"
COMMIT = "65b614b" + "0" * 33
INHALT = b"MZ" + bytes(range(256)) * 40  # kleine Attrappe einer exe
SERVER_REGEL = Path(__file__).resolve().parent.parent / "infra" / "sokrates2" / "wamo_verteilung_manifest.py"


def _manifest(version: str = "0.2.0", inhalt: bytes = INHALT, **ueber) -> bytes:
    daten = {"v": 1, "produkt": "wais-desktop", "version": version, "datei": f"WAIS-Setup-{version}.exe", "groesse": len(inhalt),
             "sha256": hashlib.sha256(inhalt).hexdigest(), "bauzeit": "2026-11-15T14:00:00.000Z", "commit": COMMIT}
    daten.update(ueber)
    return json.dumps(daten, separators=(",", ":")).encode("utf-8")


def _stand(basis: Path, version: str = "0.2.0", inhalt: bytes = INHALT, manifest: bytes | None = None, sig: bytes | None = None,
           aktuell: bool = True) -> Path:
    ordner = basis / "staende" / version
    ordner.mkdir(parents=True)
    (ordner / "aktuell.json").write_bytes(manifest if manifest is not None else _manifest(version, inhalt))
    (ordner / f"WAIS-Setup-{version}.exe").write_bytes(inhalt)
    if sig is not None:
        (ordner / "aktuell.json.sig").write_bytes(sig)
    if aktuell:
        link = basis / "aktuell"
        if link.is_symlink():
            link.unlink()
        os.symlink(f"staende/{version}", link, target_is_directory=True)
    return ordner


class FakeDb:
    configured = True

    def __init__(self):
        self.aufrufe: list[tuple] = []

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    async def execute(self, sql: str, *args):
        self.aufrufe.append((sql, args))
        return "INSERT 0 1"


@pytest.fixture
def basis(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "ORDNER", tmp_path)
    va._versuche.clear()
    va._pruefsummen.clear()
    yield tmp_path
    va._versuche.clear()
    va._pruefsummen.clear()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(va, "shared_database", lambda: fake)
    return fake


def _client(monkeypatch, identitaet: Identity | None) -> TestClient:
    async def pruefen(_request):
        if identitaet is None:
            raise HTTPException(401, "nicht angemeldet")
        return identitaet

    monkeypatch.setattr(va, "identitaet", pruefen)
    app = FastAPI()
    app.include_router(va.router, prefix="/wamo/api")
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, basis, db):
    return _client(monkeypatch, Identity(user_id=MITGLIED, name="Mitglied", rolle="mitglied", anrede="du", anmeldung=1.0))


@pytest.fixture
def labor_client(monkeypatch, basis, db):
    return _client(monkeypatch, Identity(user_id=LABOR, name="Platz 3", rolle="mitglied", anrede="du", anmeldung=1.0,
                                         labor_art="platz", labor_platz=3, labor_aktiv=True))


# ---------- Manifest ----------
def test_manifest_mit_exaktem_text_und_ohne_pfade(client, basis):
    roh = _manifest()
    _stand(basis, manifest=roh)
    r = client.get("/wamo/api/installer")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["manifest"] == roh.decode("utf-8") and d["signatur"] is None
    assert (d["v"], d["version"], d["datei"], d["groesse"]) == (1, "0.2.0", "WAIS-Setup-0.2.0.exe", len(INHALT))
    assert d["sha256"] == hashlib.sha256(INHALT).hexdigest() and d["commit"] == COMMIT
    assert str(basis) not in r.text and "staende" not in r.text and "/var/lib" not in r.text


def test_signatur_wird_ohne_zeilenende_durchgereicht(client, basis):
    sig = base64.b64encode(bytes(range(64)))
    _stand(basis, sig=sig + b"\n")
    assert client.get("/wamo/api/installer").json()["signatur"] == sig.decode("ascii")


@pytest.mark.parametrize("sig", [b"", b"kein base64", base64.b64encode(bytes(63)), base64.b64encode(bytes(64)) + b"\n\n"])
def test_kaputte_signatur_ist_eine_unstimmige_ablage(client, basis, sig):
    _stand(basis, sig=sig)
    r = client.get("/wamo/api/installer")
    assert r.status_code == 503 and r.json()["code"] == "installer_fehlt"


def test_ohne_ablage_503_mit_code(client, basis):
    r = client.get("/wamo/api/installer")
    assert r.status_code == 503 and r.json()["code"] == "installer_fehlt"
    assert "Installer" in r.json()["detail"] and str(basis) not in r.text
    r = client.get("/wamo/api/installer/datei")
    assert r.status_code == 503 and r.json()["code"] == "installer_fehlt"


@pytest.mark.parametrize("ueber", [
    {"version": "0.2"}, {"datei": "../../etc/passwd"}, {"datei": "WAIS-Setup-0.3.0.exe"}, {"groesse": True}, {"groesse": 0},
    {"sha256": "A" * 64}, {"commit": "65b614b"}, {"produkt": "anderes"}, {"v": True}, {"bauzeit": "gestern"}, {"zusatz": 1},
])
def test_manifest_ausserhalb_der_regel_ist_503(client, basis, ueber):
    _stand(basis, manifest=_manifest(**ueber))
    assert client.get("/wamo/api/installer").status_code == 503
    assert client.get("/wamo/api/installer/datei").status_code == 503


def test_falsche_pruefsumme_oder_groesse_liefert_nichts(client, basis):
    _stand(basis, manifest=_manifest(inhalt=INHALT[:-1] + b"X"))
    assert client.get("/wamo/api/installer").status_code == 503
    r = client.get("/wamo/api/installer/datei")
    assert r.status_code == 503 and INHALT[:50] not in r.content


def test_link_aktuell_ausserhalb_von_staende_wird_abgelehnt(client, basis, tmp_path_factory):
    fremd = tmp_path_factory.mktemp("fremd")
    (fremd / "aktuell.json").write_bytes(_manifest())
    (fremd / "WAIS-Setup-0.2.0.exe").write_bytes(INHALT)
    os.symlink(str(fremd), basis / "aktuell", target_is_directory=True)
    assert client.get("/wamo/api/installer").status_code == 503
    assert client.get("/wamo/api/installer/datei").status_code == 503


def test_exe_als_link_wird_abgelehnt(client, basis, tmp_path_factory):
    ordner = _stand(basis)
    fremd = tmp_path_factory.mktemp("fremd") / "x.exe"
    fremd.write_bytes(INHALT)
    (ordner / "WAIS-Setup-0.2.0.exe").unlink()
    os.symlink(str(fremd), ordner / "WAIS-Setup-0.2.0.exe")
    assert client.get("/wamo/api/installer/datei").status_code == 503


def test_manifest_zu_gross_wird_nicht_gelesen(client, basis):
    _stand(basis, manifest=b"{" + b" " * 5000 + b"}")
    assert client.get("/wamo/api/installer").status_code == 503


# ---------- Datei ----------
def test_datei_mit_festem_namen_und_kopfzeilen(client, basis, db):
    _stand(basis)
    r = client.get("/wamo/api/installer/datei")
    assert r.status_code == 200 and r.content == INHALT
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == 'attachment; filename="WAIS-Setup-0.2.0.exe"'
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert int(r.headers["content-length"]) == len(INHALT)


def test_kein_pfad_vom_client(client, basis):
    _stand(basis)
    for pfad in ("/wamo/api/installer/datei/../aktuell.json", "/wamo/api/installer/datei?datei=aktuell.json",
                 "/wamo/api/installer/WAIS-Setup-0.2.0.exe", "/wamo/api/installer/datei/aktuell.json"):
        r = client.get(pfad)
        assert r.status_code in (200, 404) and (r.status_code == 404 or r.content == INHALT), pfad


def test_range_liefert_einen_teil(client, basis):
    _stand(basis)
    r = client.get("/wamo/api/installer/datei", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == INHALT[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(INHALT)}"


def test_ratengrenze_drei_je_stunde_und_profil(client, basis, monkeypatch):
    _stand(basis)
    for _ in range(3):
        assert client.get("/wamo/api/installer/datei").status_code == 200
    r = client.get("/wamo/api/installer/datei")
    assert r.status_code == 429 and r.json()["code"] == "installer_zu_oft"
    # ein anderes Profil hat seine eigene Grenze
    anderes = _client(monkeypatch, Identity(user_id=NIKO, name="Niko", rolle="admin", anrede="du", anmeldung=1.0))
    assert anderes.get("/wamo/api/installer/datei").status_code == 200


def test_ratengrenze_laeuft_nach_einer_stunde_ab():
    va._versuche.clear()
    for t in (0.0, 1.0, 2.0):
        assert va._zulassen(MITGLIED, "datei", va.DATEI_GRENZE, jetzt=t)
    assert not va._zulassen(MITGLIED, "datei", va.DATEI_GRENZE, jetzt=3.0)
    assert va._zulassen(MITGLIED, "datei", va.DATEI_GRENZE, jetzt=3601.5)
    va._versuche.clear()


def test_teilabrufe_haben_eine_eigene_grenze(client, basis):
    _stand(basis)
    for _ in range(3):
        assert client.get("/wamo/api/installer/datei").status_code == 200
    assert client.get("/wamo/api/installer/datei", headers={"Range": "bytes=100-"}).status_code == 206


def test_eintrag_in_actions_ohne_inhalt(client, basis, db):
    _stand(basis)
    client.get("/wamo/api/installer/datei")
    assert len(db.aufrufe) == 1
    sql, args = db.aufrufe[0]
    assert "insert into wamo_test.actions" in sql and "installer_download" in args
    assert args[0] == MITGLIED
    params = json.loads(args[args.index("installer_download") + 1])
    assert params == {"version": "0.2.0", "teil": False}
    assert not any(isinstance(a, (bytes, bytearray)) for a in args)


def test_ausfall_der_datenbank_haelt_den_download_nicht_auf(client, basis, db, monkeypatch):
    import asyncpg

    async def kaputt(*_a):
        raise asyncpg.PostgresError("weg")

    monkeypatch.setattr(db, "execute", kaputt)
    _stand(basis)
    assert client.get("/wamo/api/installer/datei").status_code == 200


def test_pruefsumme_wird_je_stand_nur_einmal_berechnet(client, basis, monkeypatch):
    _stand(basis)
    zaehler = {"n": 0}
    echt = va._sha256_datei

    def zaehlen(pfad):
        zaehler["n"] += 1
        return echt(pfad)

    monkeypatch.setattr(va, "_sha256_datei", zaehlen)
    client.get("/wamo/api/installer")
    client.get("/wamo/api/installer/datei")
    client.get("/wamo/api/installer")
    assert zaehler["n"] == 1


def test_ausgetauschte_datei_wird_neu_geprueft(client, basis):
    ordner = _stand(basis)
    assert client.get("/wamo/api/installer").status_code == 200
    (ordner / "WAIS-Setup-0.2.0.exe").write_bytes(INHALT[:-1] + b"Y")
    assert client.get("/wamo/api/installer/datei").status_code == 503


def test_neuer_stand_nach_dem_umschalten(client, basis):
    _stand(basis)
    neu = INHALT + b"neu"
    _stand(basis, version="0.3.0", inhalt=neu)
    assert client.get("/wamo/api/installer").json()["version"] == "0.3.0"
    r = client.get("/wamo/api/installer/datei")
    assert r.content == neu and 'filename="WAIS-Setup-0.3.0.exe"' in r.headers["content-disposition"]


# ---------- Zugang ----------
def test_laborprofil_bekommt_nichts(labor_client, basis, db):
    _stand(basis)
    for pfad in ("/wamo/api/installer", "/wamo/api/installer/datei"):
        r = labor_client.get(pfad)
        assert r.status_code == 403 and r.json()["code"] == "installer_labor"
        assert INHALT[:50] not in r.content
    assert db.aufrufe == []


def test_ohne_anmeldung_nichts(monkeypatch, basis, db):
    _stand(basis)
    c = _client(monkeypatch, None)
    assert c.get("/wamo/api/installer").status_code == 401
    assert c.get("/wamo/api/installer/datei").status_code == 401


def test_laborpfadliste_laesst_den_installer_nicht_durch():
    import labor

    for art in ("platz", "schaufenster"):
        for pfad in ("/wamo/api/installer", "/wamo/api/installer/datei"):
            assert labor.pfad_pruefen(art, "GET", pfad, pfad.encode("ascii")) is None


def test_modul_ist_in_der_kern_api_eingehaengt():
    import wamo_api

    assert "verteilung_api" in wamo_api.ROUTEN_MODULE


# ---------- Vertrag mit der Prüfregel am Server ----------
def _server_regel():
    spec = importlib.util.spec_from_file_location("wamo_verteilung_manifest_vertrag", SERVER_REGEL)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


FAELLE = [
    _manifest(), _manifest("0.10.0"), _manifest(bauzeit="2026-11-15T14:00:00Z"), _manifest(bauzeit="2026-11-15T14:00:00.5Z"),
    _manifest("0.2"), _manifest("01.2.3"), _manifest("1.2.3 "), _manifest(datei="WAIS-Setup-0.2.0.EXE"), _manifest(groesse=True),
    _manifest(groesse=536_870_913), _manifest(groesse=536_870_912), _manifest(groesse=1.0), _manifest(sha256="g" * 64),
    _manifest(commit="A" * 40), _manifest(v=2), _manifest(v=1.0), _manifest(produkt="WAIS-desktop"), _manifest(bauzeit="2026-11-15T14:00:00+01:00"),
    _manifest(zusatz=None), b'{"v":1,"v":1}', b"[]", b"", b"\xef\xbb\xbf" + _manifest(), _manifest().replace(b'"v":1', b'"v":NaN'),
    json.dumps({k: v for k, v in json.loads(_manifest()).items() if k != "commit"}).encode(), "ü".encode("latin-1"),
    _manifest(version="0.2.0\n", datei="WAIS-Setup-0.2.0\n.exe"), _manifest(version="٠.٢.٠", datei="WAIS-Setup-٠.٢.٠.exe"),
]


@pytest.mark.parametrize("roh", FAELLE)
def test_kern_und_server_pruefen_gleich(roh):
    server = _server_regel()
    try:
        server.manifest_pruefen(roh)
        server_ok = True
    except ValueError:
        server_ok = False
    try:
        va.manifest_pruefen(roh)
        kern_ok = True
    except ValueError:
        kern_ok = False
    assert kern_ok == server_ok


def test_konstanten_gleich_wie_am_server():
    server = _server_regel()
    assert va.SCHLUESSEL == server.SCHLUESSEL and va.PRODUKT == server.PRODUKT
    assert va.MAX_MANIFEST == server.MAX_MANIFEST and va.MAX_GROESSE == server.MAX_GROESSE
    assert va.SIGNATUR_RE.pattern == server.SIGNATUR_RE.pattern.decode("ascii")
