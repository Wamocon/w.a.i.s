"""Konfiguration, Zugangsdatei und Einstieg: Fehlermeldungen nennen die Variable, nie einen Wert."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from wamo_werkstatt import __main__ as einstieg
from wamo_werkstatt import konfig, protokoll
from wamo_werkstatt.konfig import KonfigFehler, aus_umgebung, zugang_lesen, zugang_pfad

BASIS = {"WAMO_WERKSTATT_SCHEMA": "wamo_dev", "WAMO_WERKSTATT_SUPABASE_URL": "https://192.168.178.136:55443"}


def test_standardwerte():
    k = aus_umgebung(BASIS)
    assert k.schema == "wamo_dev" and k.supabase_url == "https://192.168.178.136:55443"
    assert k.jwks_url == "https://192.168.178.136:55443/auth/v1/.well-known/jwks.json" and k.issuer == "https://192.168.178.136:55443/auth/v1"
    assert (k.host, k.port, k.pfad, k.audience) == ("127.0.0.1", 18095, "/werkstatt/api", "authenticated")
    assert k.herkunft == "https://192.168.178.136:55445" and k.ca_datei is None
    assert k.admins_datei == Path("/etc/wamo-werkstatt/admins") and k.daten_ordner == Path("/var/lib/wamo-werkstatt")
    assert "wamo-core" in k.marken and "wamo-nutzer" not in k.marken and "wamo-auth" not in k.marken


def test_eigene_werte():
    k = aus_umgebung({**BASIS, "WAMO_WERKSTATT_PORT": "18999", "WAMO_WERKSTATT_PFAD": "/", "WAMO_WERKSTATT_HERKUNFT": "https://ui.test:55445/",
                      "WAMO_WERKSTATT_MARKEN": "wamo-core, wais-deploy,wamo-core", "WAMO_CA_FILE": ' "/etc/ca.crt" ',
                      "WAMO_WERKSTATT_ISS": "https://x.test/auth/v1/", "WAMO_WERKSTATT_AUD": "eigene", "WAMO_WERKSTATT_JWKS_URL": "https://x.test/jwks",
                      "WAMO_WERKSTATT_ADMINS": "/tmp/a", "WAMO_WERKSTATT_DATEN": "/tmp/d", "WAMO_WERKSTATT_HOST": "::1"})
    assert (k.port, k.pfad, k.herkunft, k.marken, k.ca_datei) == (18999, "", "https://ui.test:55445", ("wamo-core", "wais-deploy"), "/etc/ca.crt")
    assert (k.issuer, k.audience, k.jwks_url, k.host) == ("https://x.test/auth/v1", "eigene", "https://x.test/jwks", "::1")
    assert aus_umgebung({**BASIS, "WAMO_WERKSTATT_PFAD": "/api"}).pfad == "/api"
    assert aus_umgebung({**BASIS, "WAMO_WERKSTATT_SUPABASE_URL": "http://127.0.0.1:55321"}).supabase_url == "http://127.0.0.1:55321"
    assert aus_umgebung({**BASIS, "WAMO_WERKSTATT_HERKUNFT": "http://localhost:3000"}).herkunft == "http://localhost:3000"


@pytest.mark.parametrize("aenderung, variable", [
    ({"WAMO_WERKSTATT_SCHEMA": "public"}, "WAMO_WERKSTATT_SCHEMA"), ({"WAMO_WERKSTATT_SCHEMA": ""}, "WAMO_WERKSTATT_SCHEMA"),
    ({"WAMO_WERKSTATT_SUPABASE_URL": ""}, "WAMO_WERKSTATT_SUPABASE_URL"), ({"WAMO_WERKSTATT_SUPABASE_URL": "http://stack.test"}, "WAMO_WERKSTATT_SUPABASE_URL"),
    ({"WAMO_WERKSTATT_SUPABASE_URL": "https://u:p@stack.test"}, "WAMO_WERKSTATT_SUPABASE_URL"), ({"WAMO_WERKSTATT_JWKS_URL": "ftp://x"}, "WAMO_WERKSTATT_JWKS_URL"),
    ({"WAMO_WERKSTATT_HERKUNFT": "*"}, "WAMO_WERKSTATT_HERKUNFT"), ({"WAMO_WERKSTATT_HERKUNFT": "https://ui.test/pfad"}, "WAMO_WERKSTATT_HERKUNFT"),
    ({"WAMO_WERKSTATT_HERKUNFT": "http://ui.test"}, "WAMO_WERKSTATT_HERKUNFT"), ({"WAMO_WERKSTATT_PORT": "abc"}, "WAMO_WERKSTATT_PORT"),
    ({"WAMO_WERKSTATT_PORT": "80"}, "WAMO_WERKSTATT_PORT"), ({"WAMO_WERKSTATT_PFAD": "pfad-ohne-schraegstrich"}, "WAMO_WERKSTATT_PFAD"),
    ({"WAMO_WERKSTATT_PFAD": "/a//b"}, "WAMO_WERKSTATT_PFAD"), ({"WAMO_WERKSTATT_PFAD": "/api/"}, "WAMO_WERKSTATT_PFAD"),
    ({"WAMO_WERKSTATT_MARKEN": "Gross,klein"}, "WAMO_WERKSTATT_MARKEN"), ({"WAMO_WERKSTATT_MARKEN": "../x"}, "WAMO_WERKSTATT_MARKEN"), ({"WAMO_WERKSTATT_HOST": "kein host"}, "WAMO_WERKSTATT_HOST"), ({"WAMO_WERKSTATT_HOST": "0.0.0.0"}, "WAMO_WERKSTATT_HOST"),
    ({"WAMO_WERKSTATT_HOST": "192.168.178.136"}, "WAMO_WERKSTATT_HOST"),
])
def test_fehlerhafte_einstellung(aenderung, variable):
    with pytest.raises(KonfigFehler) as e:
        aus_umgebung({**BASIS, **aenderung})
    assert variable in str(e.value)
    for wert in aenderung.values():
        assert wert == "" or wert not in str(e.value)  # nie ein Wert in der Meldung


def test_zugang_pfad(tmp_path):
    assert zugang_pfad({"WAMO_WERKSTATT_DB_ZUGANG": "/x/z"}) == Path("/x/z")
    assert zugang_pfad({"CREDENTIALS_DIRECTORY": "/run/cred"}) == Path("/run/cred/db.zugang")
    assert zugang_pfad({}) == Path("/etc/wamo-werkstatt/db.zugang")


def schreibe(tmp_path, text: str) -> Path:
    p = tmp_path / "db.zugang"
    p.write_text(text, encoding="utf-8")
    return p


GUT = "# Zugang\nhost=db.test\nport=55322\ndbname=wamo\nuser=wamo_werkstatt_login\npassword=geheimgeheim12\nsslrootcert=/etc/wamo-ca.crt\n"


def test_zugang_lesen(tmp_path):
    z = zugang_lesen(schreibe(tmp_path, GUT))
    assert (z.host, z.port, z.dbname, z.user, z.sslrootcert, z.password) == ("db.test", 55322, "wamo", "wamo_werkstatt_login", "/etc/wamo-ca.crt", "geheimgeheim12")
    assert "geheimgeheim12" not in repr(z)
    assert zugang_lesen(schreibe(tmp_path, GUT.replace("/etc/wamo-ca.crt", "C:\\ca.crt"))).sslrootcert == "C:\\ca.crt"


@pytest.mark.parametrize("text", [
    GUT + "unbekannt=1\n", GUT + "host=doppelt\n", "ohne gleichheitszeichen\n", GUT.replace("host=db.test\n", ""), GUT.replace("port=55322", "port=abc"),
    GUT.replace("port=55322", "port=70000"), GUT.replace("db.test", "host mit leer"), GUT.replace("geheimgeheim12", "kurz"),
    GUT.replace("geheimgeheim12", "mit leerzeichen drin"), GUT.replace("/etc/wamo-ca.crt", "relativ/ca.crt"), GUT.replace("wamo_werkstatt_login", "bö;se"),
    "x" * 17000,
])
def test_zugang_fehler_ohne_werte(tmp_path, text):
    with pytest.raises(KonfigFehler) as e:
        zugang_lesen(schreibe(tmp_path, text))
    assert "geheimgeheim12" not in str(e.value) and "mit leerzeichen" not in str(e.value)


def test_zugang_fehlt_oder_kein_utf8(tmp_path):
    with pytest.raises(KonfigFehler):
        zugang_lesen(tmp_path / "gibtesnicht")
    p = tmp_path / "bin"
    p.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(KonfigFehler):
        zugang_lesen(p)


def test_protokoll_nur_sichere_werte(caplog):
    caplog.set_level(logging.INFO)
    protokoll.ereignis("test", gut="abc-1.2", boese="mit Leerzeichen", token="eyJ" + "x" * 100, leer=None)
    meldung = caplog.records[-1].getMessage()
    assert meldung == "wamo-werkstatt: test gut=abc-1.2 boese=? token=? leer=-"
    protokoll.ereignis("ohne_felder")
    assert caplog.records[-1].getMessage() == "wamo-werkstatt: ohne_felder"
    protokoll.einrichten()
    assert logging.getLogger("wamo-werkstatt").propagate is False
    logging.getLogger("wamo-werkstatt").propagate = True


def test_tls_fuer_jwks(tmp_path, monkeypatch):
    assert einstieg._tls(None) is None
    with pytest.raises(KonfigFehler) as e:
        einstieg._tls(str(tmp_path / "gibtesnicht.crt"))
    assert "WAMO_CA_FILE" in str(e.value)


def test_main_ohne_konfiguration_endet_mit_2(monkeypatch, capsys):
    for name in list(__import__("os").environ):
        if name.startswith("WAMO_WERKSTATT"):
            monkeypatch.delenv(name)
    assert einstieg.main() == 2
    assert "Konfiguration:" in capsys.readouterr().err


def test_main_startet_den_server(monkeypatch, tmp_path):
    zugang = schreibe(tmp_path, GUT)
    for name, wert in {**BASIS, "WAMO_WERKSTATT_DB_ZUGANG": str(zugang), "WAMO_WERKSTATT_ADMINS": str(tmp_path / "admins")}.items():
        monkeypatch.setenv(name, wert)
    gestartet = {}
    monkeypatch.setattr(einstieg.uvicorn, "run", lambda app, **kw: gestartet.update(app=app, **kw))
    assert einstieg.main() == 0
    assert gestartet["host"] == "127.0.0.1" and gestartet["port"] == 18095 and gestartet["access_log"] is False and gestartet["app"] is not None
    logging.getLogger("wamo-werkstatt").propagate = True
    assert konfig.SCHEMA_RE.fullmatch("wamo_prod")
