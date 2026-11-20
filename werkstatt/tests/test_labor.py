"""Labor-Planer: Termine, Fristen, Plätze, Checkliste, Prüfspur, Eingaben mit Steuerzeichen und zu langen Feldern."""

from __future__ import annotations

from datetime import date

import pytest

import conftest as k
from conftest import kopf, token
from wamo_werkstatt import labor_regeln
from wamo_werkstatt.eingabe import datum_lesen, ganzzahl_lesen, nummer_lesen, text_lesen, uuid_lesen, zeit_lesen
from wamo_werkstatt.fehler import WerkstattFehler

B = "/werkstatt/api/labor/termine"


def neu(client, tag="2026-12-05", **mehr):
    r = client.post(B, json={"tag": tag, **mehr}, headers=kopf())
    assert r.status_code == 201, r.text
    return r.json()["termin"]


def test_termin_anlegen_mit_fristen(client, db):
    t = neu(client, beginn="10:00", ende="13:30")
    assert t["tag"] == "2026-12-05" and t["status"] == "entwurf" and t["einwilligung_version"] == 1
    assert t["beginn"] == "10:00" and t["ende"] == "13:30"
    assert t["aufbewahrung_bis"] == "2026-12-18" and t["loeschlauf_ab"] == "2026-12-19"
    assert db.actions[-1]["tool"] == "werkstatt_termin_anlegen" and db.actions[-1]["risk"] == "change"
    assert db.actions[-1]["user_id"] == k.ADMIN and db.actions[-1]["params"] == {"termin": t["id"]}


def test_termin_liste_und_lesen(client):
    a, b = neu(client, "2026-12-05"), neu(client, "2027-01-30")
    liste = client.get(B, headers=kopf()).json()["termine"]
    assert [t["id"] for t in liste] == [b["id"], a["id"]]
    assert client.get(f"{B}/{a['id']}", headers=kopf()).json()["termin"] == a
    assert client.get(f"{B}/{k.neue_id()}", headers=kopf()).status_code == 404
    assert client.get(f"{B}/kein-uuid", headers=kopf()).status_code == 404


def test_termin_doppelter_tag_409(client):
    neu(client)
    r = client.post(B, json={"tag": "2026-12-05"}, headers=kopf())
    assert r.status_code == 409 and r.json()["code"] == "konflikt"


@pytest.mark.parametrize("eingabe", [
    {}, {"tag": None}, {"tag": "05.12.2026"}, {"tag": "2026-13-45"}, {"tag": "20261205"}, {"tag": 5}, {"tag": "2019-01-01"}, {"tag": "2099-01-01"},
    {"tag": "2026-12-05", "beginn": "25:00"}, {"tag": "2026-12-05", "beginn": "9:00"}, {"tag": "2026-12-05", "beginn": "12:00", "ende": "11:00"},
    {"tag": "2026-12-05", "einwilligung_version": 0}, {"tag": "2026-12-05", "einwilligung_version": 100},
    {"tag": "2026-12-05", "einwilligung_version": "1"}, {"tag": "2026-12-05", "einwilligung_version": True},
    {"tag": "2026-12-05", "status": "fertig"}, {"tag": "2026-12-05", "aufbewahrung_bis": "2026-12-04"},
    {"tag": "2026-12-05", "aufbewahrung_bis": "2026-12-20"}, {"tag": "2026-12-05", "aufbewahrung_bis": "kein Datum"},
])
def test_termin_ungueltig_422(client, eingabe):
    r = client.post(B, json=eingabe, headers=kopf())
    assert r.status_code == 422 and r.json()["code"] == "ungueltig"


def test_aufbewahrung_grenzen(client):
    assert neu(client, "2026-12-05", aufbewahrung_bis="2026-12-19")["loeschlauf_ab"] == "2026-12-20"
    assert neu(client, "2027-02-01", aufbewahrung_bis="2027-02-01")["aufbewahrung_bis"] == "2027-02-01"


def test_termin_aendern_behaelt_fehlende_felder(client, db):
    t = neu(client, beginn="10:00", ende="12:00", einwilligung_version=2)
    r = client.put(f"{B}/{t['id']}", json={"status": "freigegeben"}, headers=kopf())
    assert r.status_code == 200
    neu_t = r.json()["termin"]
    assert neu_t["status"] == "freigegeben" and neu_t["beginn"] == "10:00" and neu_t["einwilligung_version"] == 2
    assert db.actions[-1]["tool"] == "werkstatt_termin_aendern"


def test_termin_verschieben_setzt_frist_neu(client):
    t = neu(client)
    verschoben = client.put(f"{B}/{t['id']}", json={"tag": "2026-12-12"}, headers=kopf()).json()["termin"]
    assert verschoben["aufbewahrung_bis"] == "2026-12-25" and verschoben["loeschlauf_ab"] == "2026-12-26"
    behalten = client.put(f"{B}/{t['id']}", json={"tag": "2026-12-12", "aufbewahrung_bis": "2026-12-20"}, headers=kopf()).json()["termin"]
    assert behalten["aufbewahrung_bis"] == "2026-12-20"
    leer = client.put(f"{B}/{t['id']}", json={"beginn": ""}, headers=kopf()).json()["termin"]
    assert leer["beginn"] is None


def test_termin_aendern_fehler(client):
    a, b = neu(client, "2026-12-05"), neu(client, "2027-01-30")
    assert client.put(f"{B}/{k.neue_id()}", json={"status": "laufend"}, headers=kopf()).status_code == 404
    assert client.put(f"{B}/{a['id']}", json={"tag": "2027-01-30"}, headers=kopf()).status_code == 409
    assert client.put(f"{B}/{b['id']}", json={"tag": None}, headers=kopf()).status_code == 422
    assert client.put(f"{B}/{b['id']}", json=[1], headers=kopf()).status_code == 422


def test_termin_loeschen_nur_entwurf(client, db):
    t = neu(client)
    client.put(f"{B}/{t['id']}/plaetze", json={"plaetze": [{"platz": 1, "zweck": "besucher"}]}, headers=kopf())
    client.put(f"{B}/{t['id']}", json={"status": "freigegeben"}, headers=kopf())
    r = client.delete(f"{B}/{t['id']}", headers=kopf())
    assert r.status_code == 409 and r.json()["code"] == "konflikt"
    client.put(f"{B}/{t['id']}", json={"status": "entwurf"}, headers=kopf())
    assert client.delete(f"{B}/{t['id']}", headers=kopf()).json() == {"geloescht": True}
    assert client.get(f"{B}/{t['id']}", headers=kopf()).status_code == 404
    assert t["id"] not in db.plaetze_tab
    assert client.delete(f"{B}/{t['id']}", headers=kopf()).status_code == 404
    assert db.actions[-1]["tool"] == "werkstatt_termin_loeschen"


def test_plaetze(client, db):
    t = neu(client)
    plaetze = [{"platz": 15, "zweck": "abnahme", "kennung": "labor-15", "gast": "Abnahme"}, {"platz": 1, "zweck": "besucher", "kennung": "labor-01",
               "gast": "Gast 1"}, {"platz": 5, "zweck": "reserve"}]
    r = client.put(f"{B}/{t['id']}/plaetze", json={"plaetze": plaetze}, headers=kopf())
    assert r.status_code == 200
    assert [p["platz"] for p in r.json()["plaetze"]] == [1, 5, 15]
    gelesen = client.get(f"{B}/{t['id']}/plaetze", headers=kopf()).json()["plaetze"]
    assert gelesen[1] == {"platz": 5, "zweck": "reserve", "kennung": None, "gast": None}
    assert db.actions[-1]["tool"] == "werkstatt_plaetze_setzen" and db.actions[-1]["result"]["plaetze"] == 3
    # ersetzt den ganzen Satz
    client.put(f"{B}/{t['id']}/plaetze", json={"plaetze": []}, headers=kopf())
    assert client.get(f"{B}/{t['id']}/plaetze", headers=kopf()).json()["plaetze"] == []
    assert client.get(f"{B}/{k.neue_id()}/plaetze", headers=kopf()).status_code == 404
    assert client.put(f"{B}/{k.neue_id()}/plaetze", json={"plaetze": []}, headers=kopf()).status_code == 404


@pytest.mark.parametrize("plaetze", [
    "kein", [{"platz": 0, "zweck": "besucher"}], [{"platz": 17, "zweck": "besucher"}], [{"platz": "1", "zweck": "besucher"}],
    [{"platz": 1, "zweck": "gast"}], [{"platz": 1, "zweck": "abnahme"}], [{"platz": 14, "zweck": "abnahme"}], [{"platz": 1, "zweck": "besucher", "kennung": "Labor-01"}],
    [{"platz": 1, "zweck": "besucher", "kennung": "labor-x"}], [{"platz": 1, "zweck": "besucher", "gast": "x" * 21}],
    [{"platz": 1, "zweck": "besucher"}, {"platz": 1, "zweck": "reserve"}],
    [{"platz": 1, "zweck": "besucher", "kennung": "labor-01"}, {"platz": 2, "zweck": "besucher", "kennung": "labor-01"}],
    [{"platz": i % 16 + 1, "zweck": "besucher"} for i in range(17)], ["x"], [{"platz": 1, "zweck": "besucher", "gast": "Gast\x07"}],
])
def test_plaetze_ungueltig(client, plaetze):
    t = neu(client)
    r = client.put(f"{B}/{t['id']}/plaetze", json={"plaetze": plaetze}, headers=kopf())
    assert r.status_code == 422, r.text


def test_checkliste(client, db):
    t = neu(client)
    url = f"{B}/{t['id']}/checkliste"
    p1 = client.post(url, json={"titel": "Lasttest ausgewertet", "quelle": "Runbook 9", "faellig": "2026-12-01"}, headers=kopf())
    assert p1.status_code == 201
    punkt = p1.json()["punkt"]
    assert punkt["erledigt"] is False and punkt["faellig"] == "2026-12-01" and punkt["quelle"] == "Runbook 9"
    client.post(url, json={"titel": "Zweiter Punkt"}, headers=kopf())
    assert [p["titel"] for p in client.get(url, headers=kopf()).json()["punkte"]] == ["Lasttest ausgewertet", "Zweiter Punkt"]
    erledigt = client.patch(f"{url}/{punkt['nr']}", json={"erledigt": True}, headers=kopf())
    assert erledigt.status_code == 200 and erledigt.json()["punkt"]["erledigt"] is True and erledigt.json()["punkt"]["erledigt_at"]
    offen = client.patch(f"{url}/{punkt['nr']}", json={"erledigt": False}, headers=kopf()).json()["punkt"]
    assert offen["erledigt"] is False and offen["erledigt_at"] is None
    assert db.actions[-1]["tool"] == "werkstatt_checkliste_abhaken" and db.actions[-1]["params"] == {"termin": t["id"], "nr": punkt["nr"]}
    assert client.patch(f"{url}/9999", json={"erledigt": True}, headers=kopf()).status_code == 404
    assert client.patch(f"{url}/abc", json={"erledigt": True}, headers=kopf()).status_code == 404
    assert client.patch(f"{url}/0", json={"erledigt": True}, headers=kopf()).status_code == 404
    assert client.patch(f"{url}/{punkt['nr']}", json={"erledigt": "ja"}, headers=kopf()).status_code == 422
    assert client.patch(f"{url}/{punkt['nr']}", json={}, headers=kopf()).status_code == 422
    assert client.get(f"{B}/{k.neue_id()}/checkliste", headers=kopf()).status_code == 404
    assert client.post(f"{B}/{k.neue_id()}/checkliste", json={"titel": "x"}, headers=kopf()).status_code == 404


@pytest.mark.parametrize("eingabe", [{}, {"titel": ""}, {"titel": "   "}, {"titel": "x" * 121}, {"titel": "ok", "quelle": "q" * 81},
                                     {"titel": "ok", "faellig": "bald"}, {"titel": 5}, {"titel": "Punkt\x00mit Nullbyte"},
                                     {"titel": "Punkt‮bidi"}, {"titel": "ok", "quelle": ["x"]}])
def test_checkliste_ungueltig(client, eingabe):
    t = neu(client)
    assert client.post(f"{B}/{t['id']}/checkliste", json=eingabe, headers=kopf()).status_code == 422


def test_checkliste_voll(client, db):
    t = neu(client)
    db.checkliste_tab[t["id"]] = [{"nr": i, "titel": "x", "quelle": None, "faellig": None, "erledigt_at": None} for i in range(labor_regeln.CHECKLISTE_MAX)]
    r = client.post(f"{B}/{t['id']}/checkliste", json={"titel": "noch einer"}, headers=kopf())
    assert r.status_code == 422 and "voll" in r.json()["text"]


def test_naechster_termin_im_stand(client):
    neu(client, "2026-12-05")
    neu(client, "2027-01-30")
    d = client.get("/werkstatt/api/labor/stand", headers=kopf()).json()
    assert d["naechster_termin"]["tag"] == "2026-12-05" and d["naechster_termin"]["loeschlauf_ab"] == "2026-12-19"


def test_steuerzeichen_und_zu_lang_in_gast(client):
    t = neu(client)
    assert client.put(f"{B}/{t['id']}/plaetze", json={"plaetze": [{"platz": 1, "zweck": "besucher", "gast": "Gast\n1"}]}, headers=kopf()).status_code == 200
    assert client.get(f"{B}/{t['id']}/plaetze", headers=kopf()).json()["plaetze"][0]["gast"] == "Gast 1"


@pytest.mark.parametrize("roh", [b"", b"nicht json", b"[]", b'"text"', b"NaN", b'{"tag": Infinity}', b"\xff\xfe", b"{" * 5000])
def test_koerper_ungueltig(client, roh):
    r = client.post(B, content=roh, headers={**kopf(), "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["code"] == "ungueltig"


def test_koerper_zu_gross(client):
    r = client.post(B, content=b'{"tag": "2026-12-05", "x": "' + b"a" * 140000 + b'"}', headers={**kopf(), "Content-Type": "application/json"})
    assert r.status_code == 422


def test_schreiben_ohne_anmeldung_und_fuer_fremde(client, db):
    assert client.post(B, json={"tag": "2026-12-05"}).status_code == 401
    assert client.post(B, json={"tag": "2026-12-05"}, headers=kopf(token(sub=k.MITGLIED))).status_code == 403
    assert client.put(f"{B}/{k.neue_id()}", json={}, headers=kopf(token(sub=k.LABOR))).status_code == 403
    assert client.delete(f"{B}/{k.neue_id()}", headers=kopf(token(sub=k.AUSSERHALB))).status_code == 403
    assert db.actions == [] and db.termine_tab == {}


def test_buchung_fehlt_dann_gilt_nichts(client, db):
    db.buchen_fehler = True
    r = client.post(B, json={"tag": "2026-12-05"}, headers=kopf())
    assert r.status_code == 503
    assert db.termine_tab == {} and db.actions == []


def test_eingabe_helfer():
    assert text_lesen("  a \n b\t c ", "X", maximum=10) == "a b c"
    assert text_lesen("   ", "X", maximum=10) is None and text_lesen(None, "X", maximum=10) is None
    for falsch in (5, "x" * 11, "a\x00", "a​b", "a", "a b\x1f" + "\x85"[:0] + "\x07"):
        with pytest.raises(WerkstattFehler):
            text_lesen(falsch, "X", maximum=10)
    with pytest.raises(WerkstattFehler):
        text_lesen("", "X", maximum=10, pflicht=True)
    with pytest.raises(WerkstattFehler):
        text_lesen("  ", "X", maximum=10, pflicht=True)
    with pytest.raises(WerkstattFehler):
        text_lesen("ab", "X", maximum=10, minimum=3)
    with pytest.raises(WerkstattFehler):
        text_lesen("x" * 100, "X", maximum=10)
    assert text_lesen("Größe ✓ ß", "X", maximum=20) == "Größe ✓ ß"
    assert ganzzahl_lesen(3, "X", minimum=1, maximum=5) == 3
    for falsch in (True, "3", 3.0, 0, 6):
        with pytest.raises(WerkstattFehler):
            ganzzahl_lesen(falsch, "X", minimum=1, maximum=5)
    assert datum_lesen(None, "X", pflicht=False) is None and datum_lesen("2026-12-05", "X") == date(2026, 12, 5)
    assert zeit_lesen("09:05", "X").hour == 9 and zeit_lesen("09:05:30", "X").minute == 5 and zeit_lesen("", "X") is None
    assert uuid_lesen(k.ADMIN) == k.ADMIN and uuid_lesen(k.ADMIN.upper()) is None and uuid_lesen("{" + k.ADMIN + "}") is None and uuid_lesen(5) is None
    assert nummer_lesen("12") == 12 and nummer_lesen("0") is None and nummer_lesen("-1") is None and nummer_lesen("1" * 19) is None
    assert nummer_lesen("１２") is None and nummer_lesen(12) is None
