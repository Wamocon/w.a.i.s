"""Lesende Endpunkte: Kennzahlen, Betrieb, Protokolle, Stand des Labors. Dazu der Marker-Test (kein Gesprächstext in irgendeiner Antwort)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import conftest as k
from attrappe import MARKER, karte_roh
from conftest import kopf, token
from wamo_werkstatt import lesen

BASIS = "/werkstatt/api"


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


def schreibe_betrieb(ordner, **mehr):
    inhalt = {"zeit": jetzt().isoformat(), "kern": {"slot": "a", "release": "v0.7.0-41ecf4c", "aktiv": True},
              "oberflaeche": {"farbe": "gruen", "version": "0.7.1"}, "installer": {"version": "0.7.1"}, "kanal": {"zustand": "zu"},
              "labor_dienst": {"zustand": "ok"}, **mehr}
    (ordner / "betrieb.json").write_text(json.dumps(inhalt), encoding="utf-8")


def zeile(marke="wamo-core", stufe="info", code="labor_stufe_ende", vor_min=5, **mehr):
    return json.dumps({"zeit": (jetzt() - timedelta(minutes=vor_min)).isoformat(), "marke": marke, "stufe": stufe, "code": code,
                       "zahlen": {"sitzungen": 1}, **mehr})


def test_betrieb(client, daten_ordner):
    schreibe_betrieb(daten_ordner)
    r = client.get(f"{BASIS}/betrieb", headers=kopf())
    assert r.status_code == 200
    d = r.json()
    assert d["kern"] == {"slot": "a", "release": "v0.7.0-41ecf4c", "aktiv": True}
    assert d["oberflaeche"] == {"farbe": "gruen", "version": "0.7.1"}
    assert d["kanal"] == {"zustand": "zu"} and d["labor_dienst"] == {"zustand": "ok"} and d["installer"] == {"version": "0.7.1"}
    assert 0 <= d["alter_s"] < 10


def test_betrieb_nur_erlaubte_felder_und_werte(client, daten_ordner):
    schreibe_betrieb(daten_ordner, geheim=MARKER, kern=[{"slot": "a", "release": MARKER + "\x00", "aktiv": "ja", "extra": MARKER}, "x"],
                     kanal={"zustand": "zu", "inhalt": MARKER}, installer="kaputt")
    d = client.get(f"{BASIS}/betrieb", headers=kopf()).json()
    assert MARKER not in json.dumps(d)
    assert d["kern"] == [{"slot": "a", "release": None, "aktiv": None}]
    assert d["installer"] is None


@pytest.mark.parametrize("inhalt", [None, "kein json", "[]", json.dumps({"zeit": "gestern"}), json.dumps({"kern": {}})])
def test_betrieb_fehlt_oder_unbrauchbar_503(client, daten_ordner, inhalt):
    if inhalt is not None:
        (daten_ordner / "betrieb.json").write_text(inhalt, encoding="utf-8")
    r = client.get(f"{BASIS}/betrieb", headers=kopf())
    assert r.status_code == 503 and r.json()["code"] == "nicht_verfuegbar"


def test_betrieb_zu_gross(client, daten_ordner):
    (daten_ordner / "betrieb.json").write_text(" " * 70000, encoding="utf-8")
    assert client.get(f"{BASIS}/betrieb", headers=kopf()).status_code == 503


def test_sitzungen_latenz_aktionen(client, db):
    db.funktionen["sitzungen"] = [
        {"tag": date(2026, 11, 20), "anzahl": 3, "dauer_p50_s": Decimal("12.345"), "dauer_p95_s": 40.0, "offen": 1, "content": MARKER},
        {"tag": "kein datum", "anzahl": 1}, {"tag": date(2026, 11, 19), "anzahl": -1}]
    db.funktionen["latenz"] = [{"zuege": 10, "p50_ms": 1700, "p95_ms": float("nan"), "summary": MARKER}, {"zuege": None}]
    db.funktionen["aktionen"] = [{"tool": "entwicklungsauftrag", "status": "done", "anzahl": 2, "params": MARKER},
                                 {"tool": "Böse Name", "status": "done", "anzahl": 1}, {"tool": "x", "status": "komisch", "anzahl": 1}]
    s = client.get(f"{BASIS}/dashboard/sitzungen?tage=7", headers=kopf()).json()
    assert s == {"tage": 7, "zeilen": [{"tag": "2026-11-20", "anzahl": 3, "dauer_p50_s": 12.3, "dauer_p95_s": 40.0, "offen": 1}]}
    assert client.get(f"{BASIS}/dashboard/latenz", headers=kopf()).json() == {
        "tage": 14, "zeilen": [{"zuege": 10, "p50_ms": 1700, "p95_ms": None}]}
    assert client.get(f"{BASIS}/dashboard/aktionen", headers=kopf()).json()["zeilen"] == [
        {"tool": "entwicklungsauftrag", "status": "done", "anzahl": 2}]


def test_latenz_je_tag(client, db):
    db.funktionen["latenz"] = [{"tag": date(2026, 11, 20), "zuege": 4, "p50_ms": 1, "p95_ms": 2}]
    assert client.get(f"{BASIS}/dashboard/latenz", headers=kopf()).json()["zeilen"][0]["tag"] == "2026-11-20"


@pytest.mark.parametrize("abfrage", ["tage=0", "tage=31", "tage=-1", "tage=x", "tage=1&tage=2", "tage=", "tage=1.5", "tage=%EF%BC%91"])
def test_tage_ausserhalb_422(client, abfrage):
    r = client.get(f"{BASIS}/dashboard/sitzungen?{abfrage}", headers=kopf())
    assert r.status_code == 422 and r.json()["code"] == "ungueltig"


def test_labor_stand(client, db):
    db.funktionen["labor_stand"] = [
        {"kennung": "labor-01", "art": "platz", "platz": 1, "aktiv": False, "zeilen": 0, "email": MARKER + "@x.test", "display_name": MARKER},
        {"art": "schaufenster", "platz": None, "freigeschaltet": True, "zeilenzahl": 4},
        {"art": "geheim", "platz": 1, "aktiv": True}, {"art": "platz", "platz": 99, "aktiv": True, "kennung": MARKER}]
    r = client.get(f"{BASIS}/labor/stand", headers=kopf())
    d = r.json()
    assert MARKER not in r.text
    assert d["profile"][0] == {"kennung": "labor-01", "art": "platz", "platz": 1, "aktiv": False, "zeilen": 0}
    assert d["profile"][1] == {"art": "schaufenster", "platz": None, "aktiv": True, "zeilen": 4}
    assert d["profile"][2]["platz"] is None and "kennung" not in d["profile"][2]
    assert d["naechster_termin"] is None


def test_protokolle(client, daten_ordner):
    (daten_ordner / "protokolle" / "wamo-core.jsonl").write_text("\n".join([
        zeile(vor_min=10), zeile(stufe="fehler", code="media_stream_fehler", vor_min=3), zeile(vor_min=60 * 30),  # zu alt für 24 Stunden
        "kein json", json.dumps([1]), zeile(stufe="debug"), zeile(marke="anderes"), zeile(code="Mit Leerzeichen"),
        zeile(code="mit_zahlen", vor_min=0, zahlen={"a": MARKER, "b": 2, "Böse": 1}),
        zeile(zahlen="kaputt")]), encoding="utf-8")
    (daten_ordner / "protokolle" / "unbekannt.jsonl").write_text(zeile(marke="unbekannt"), encoding="utf-8")
    r = client.get(f"{BASIS}/protokolle", headers=kopf())
    assert r.status_code == 200
    d = r.json()
    assert [z["code"] for z in d["zeilen"]] == ["mit_zahlen", "media_stream_fehler", "labor_stufe_ende"]
    assert d["zeilen"][0]["zahlen"] == {"b": 2} and MARKER not in r.text
    assert d["stunden"] == 24 and "wamo-core" in d["marken"] and d["stufen"] == ["info", "warnung", "fehler"]
    nur_fehler = client.get(f"{BASIS}/protokolle?stufe=fehler&marke=wamo-core&stunden=1", headers=kopf()).json()
    assert [z["code"] for z in nur_fehler["zeilen"]] == ["media_stream_fehler"]
    lang = client.get(f"{BASIS}/protokolle?stunden=48", headers=kopf()).json()
    assert len(lang["zeilen"]) == 4


@pytest.mark.parametrize("abfrage", ["marke=unbekannt", "marke=../betrieb", "marke=wamo-core&marke=wais-deploy", "stufe=debug", "stunden=0",
                                     "stunden=169", "stunden=x", "marke=%2e%2e%2fadmins"])
def test_protokolle_abfrage_ungueltig(client, abfrage):
    r = client.get(f"{BASIS}/protokolle?{abfrage}", headers=kopf())
    assert r.status_code == 422


def test_protokolle_nur_ende_grosser_dateien_und_nie_ein_link(client, daten_ordner):
    datei = daten_ordner / "protokolle" / "wamo-core.jsonl"
    datei.write_text("\n".join(zeile(code=f"zeile_{i}") for i in range(10)) + "\n" + "x" * (lesen.DATEI_MAX_BYTES + 10), encoding="utf-8")
    assert client.get(f"{BASIS}/protokolle", headers=kopf()).json()["zeilen"] == []  # das Ende ist Müll, die Zeilen davor liegen außerhalb
    datei.unlink()
    ziel = daten_ordner / "ziel.jsonl"
    ziel.write_text(zeile(), encoding="utf-8")
    try:
        datei.symlink_to(ziel)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks nicht erlaubt")
    assert client.get(f"{BASIS}/protokolle", headers=kopf()).json()["zeilen"] == []


def test_protokolle_mehr_als_500_werden_gekuerzt(client, daten_ordner):
    (daten_ordner / "protokolle" / "wamo-core.jsonl").write_text("\n".join(zeile(code=f"z{i}") for i in range(700)), encoding="utf-8")
    assert len(client.get(f"{BASIS}/protokolle", headers=kopf()).json()["zeilen"]) == 500


def test_marker_in_keiner_antwort(client, db, daten_ordner, caplog):
    """Ein Marker in Gesprächstext, Zusammenfassung, Gedächtnis und E-Mail darf in keiner Antwort und in keiner Journalzeile stehen."""
    caplog.set_level(logging.DEBUG)
    schreibe_betrieb(daten_ordner)
    db.funktionen["sitzungen"] = [{"tag": date(2026, 11, 20), "anzahl": 1, "turns_content": MARKER, "summary": MARKER}]
    db.funktionen["latenz"] = [{"zuege": 1, "p50_ms": 1, "p95_ms": 2, "content": MARKER}]
    db.funktionen["aktionen"] = [{"tool": "x", "status": "done", "anzahl": 1, "params": MARKER, "result": MARKER}]
    db.funktionen["labor_stand"] = [{"art": "platz", "platz": 1, "aktiv": True, "zeilen": 1, "email": MARKER, "name": MARKER}]
    (daten_ordner / "protokolle" / "wamo-core.jsonl").write_text(zeile(text=MARKER, nachricht=MARKER), encoding="utf-8")
    db.karten_tab["W1"] = karte_roh("W1")
    pfade = ["/ich", "/betrieb", "/dashboard/sitzungen", "/dashboard/latenz", "/dashboard/aktionen", "/protokolle", "/labor/stand", "/labor/termine",
             "/karten", "/karten/versionen", "/karten/W1", "/karten/gibtesnicht"]
    for pfad in pfade:
        r = client.get(BASIS + pfad, headers=kopf())
        assert MARKER not in r.text and MARKER not in json.dumps(dict(r.headers)), pfad
    for pfad in ("/karten/pruefen", "/karten/karte"):
        r = client.post(BASIS + pfad, headers=kopf())
        assert MARKER not in r.text, pfad
    assert MARKER not in "
".join(r.getMessage() for r in caplog.records if r.name == "wamo-werkstatt")


def test_journal_ohne_inhalte(client, caplog, db):
    caplog.set_level(logging.INFO)
    tok = token()
    client.get(f"{BASIS}/karten/W1?geheim=abc123", headers=kopf(tok))
    zeilen = [r.getMessage() for r in caplog.records if r.name == "wamo-werkstatt"]
    assert any(z.startswith("wamo-werkstatt: anfrage ") and "route=/karten/{kennung}" in z and "status=404" in z for z in zeilen)
    eigene = "
".join(zeilen)  # der Testclient (httpx) schreibt seine eigene Zeile mit der Adresse
    assert tok not in eigene and "abc123" not in eigene and k.ADMIN not in eigene
    assert any("admin=11111111" in z for z in zeilen)


def test_db_ausfall_beim_lesen_503(client, db):
    # Das Profil kommt noch durch, die Kennzahlen scheitern
    async def kaputt(_tage):
        from wamo_werkstatt.daten import DatenbankFehler

        raise DatenbankFehler("Attrappe: Passwort ist geheim")

    db.sitzungen = kaputt
    r = client.get(f"{BASIS}/dashboard/sitzungen", headers=kopf())
    assert r.status_code == 503 and "geheim" not in r.text


def test_unerwarteter_fehler_503_ohne_text(client, db):
    async def kaputt(_tage):
        raise RuntimeError("Stapel mit " + MARKER)

    db.latenz = kaputt
    r = client.get(f"{BASIS}/dashboard/latenz", headers=kopf())
    assert r.status_code == 503 and MARKER not in r.text and r.headers["cache-control"] == "no-store"
    assert r.json()["code"] == "nicht_verfuegbar"


def test_zahlen_und_texte_helfer():
    assert lesen.zahl(True) is None and lesen.zahl("1") is None and lesen.zahl(float("inf")) is None and lesen.zahl(Decimal("1.26")) == 1.3
    assert lesen.ganz(-1) is None and lesen.ganz(3.0) == 3 and lesen.ganz("3") is None
    assert lesen.tag(datetime(2026, 1, 2, 3)) == "2026-01-02" and lesen.tag("x") is None
    assert lesen.kurztext("v0.7.1-abc") == "v0.7.1-abc" and lesen.kurztext("a\nb") is None and lesen.kurztext("") is None
    assert lesen.kurztext("x" * 61) is None and lesen.kurztext(5) is None
    assert lesen.zeit_lesen("2026-11-20T10:00:00") == datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
    assert lesen.zeit_lesen("2026-11-20T10:00:00Z").tzinfo is not None and lesen.zeit_lesen("morgen") is None and lesen.zeit_lesen(5) is None
