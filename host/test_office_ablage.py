"""Tests für office_ablage.py: Ordner WAIS im bekannten Ordner Dokumente, Dateinamen, Register, nie überschreiben, keine Umleitung."""

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

import office_ablage as oa

TAG = date(2026, 11, 30)


@pytest.fixture
def ablage(tmp_path):
    dokumente = tmp_path / "Dokumente"
    dokumente.mkdir()
    return oa.Ablage(dokumente, tmp_path / "WAMO" / "ablage.json")


# ---------- Dateinamen ----------
@pytest.mark.parametrize("titel,erwartet", [
    ("Angebot Kunde X", "2026-11-30 Angebot Kunde X.docx"),
    ('Angebot: Kunde/X? <neu> "a"|b*c\\d', "2026-11-30 Angebot Kunde X neu a b c d.docx"),
    ("Ende mit Punkt...", "2026-11-30 Ende mit Punkt.docx"),
    ("  ..versteckt  ", "2026-11-30 versteckt.docx"),
    ("", "2026-11-30 Canvas.docx"),
    ("CON", "2026-11-30 CON.docx"),
    ("a" + chr(0x202E) + "fdp.exe" + chr(7), "2026-11-30 afdp.exe.docx"),
])
def test_dateiname(titel, erwartet):
    assert oa.dateiname(titel, "word", TAG) == erwartet


def test_dateiname_kuerzt_titel_auf_80_zeichen_und_endung_je_format():
    name = oa.dateiname("x" * 300, "excel", TAG)
    assert name == "2026-11-30 " + "x" * oa.TITEL_MAX + ".xlsx"
    endungen = [oa.dateiname("t", f, TAG).rsplit(".", 1)[1] for f in ("word", "excel", "powerpoint", "pdf", "csv", "markdown")]
    assert endungen == ["docx", "xlsx", "pptx", "pdf", "csv", "md"]
    with pytest.raises(oa.AblageFehler):
        oa.dateiname("t", "exe", TAG)


# ---------- Speichern ----------
def test_speichern_legt_ordner_an_und_registriert_mit_pruefsumme(ablage):
    eintrag = ablage.speichern(b"inhalt", "Angebot", "word", canvas_id="11111111-1111-4111-8111-111111111111", datum=TAG)
    pfad = ablage.ordner() / eintrag["name"]
    assert pfad.read_bytes() == b"inhalt"
    assert pfad.parent.name == "WAIS"
    assert eintrag["groesse"] == 6 and eintrag["sha256"] == hashlib.sha256(b"inhalt").hexdigest()
    assert eintrag["format"] == "word" and len(eintrag["kennung"]) == 16
    register = json.loads(ablage.register.read_text(encoding="utf-8"))
    assert register["dateien"][-1]["kennung"] == eintrag["kennung"]
    assert register["dateien"][-1]["canvas_id"] == "11111111-1111-4111-8111-111111111111"
    assert "inhalt" not in ablage.register.read_text(encoding="utf-8")  # nie Inhalte im Register
    assert ablage.pfad(eintrag["kennung"]) == pfad


def test_nie_ueberschreiben(ablage):
    a = ablage.speichern(b"eins", "Gleich", "word", datum=TAG)
    b = ablage.speichern(b"zwei", "Gleich", "word", datum=TAG)
    c = ablage.speichern(b"drei", "Gleich", "word", datum=TAG)
    assert [a["name"], b["name"], c["name"]] == ["2026-11-30 Gleich.docx", "2026-11-30 Gleich (2).docx", "2026-11-30 Gleich (3).docx"]
    assert (ablage.ordner() / a["name"]).read_bytes() == b"eins"


def test_vorhandene_fremde_datei_bleibt(ablage):
    ordner = ablage.ordner()
    (ordner / "2026-11-30 Bericht.pdf").write_bytes(b"von Niko")
    e = ablage.speichern(b"%PDF-neu", "Bericht", "pdf", datum=TAG)
    assert e["name"] == "2026-11-30 Bericht (2).pdf"
    assert (ordner / "2026-11-30 Bericht.pdf").read_bytes() == b"von Niko"


def test_register_hoechstens_max_eintraege(tmp_path):
    (tmp_path / "D").mkdir()
    ablage = oa.Ablage(tmp_path / "D", tmp_path / "r.json", max_eintraege=3)
    kennungen = [ablage.speichern(b"x", f"T{i}", "markdown", datum=TAG)["kennung"] for i in range(5)]
    assert [e["kennung"] for e in ablage.eintraege()] == kennungen[-3:]
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(kennungen[0])


def test_kaputtes_register_gilt_als_leer(ablage):
    ablage.register.parent.mkdir(parents=True, exist_ok=True)
    ablage.register.write_text("{kaputt", encoding="utf-8")
    assert ablage.eintraege() == []
    e = ablage.speichern(b"x", "Neu", "csv", datum=TAG)
    assert ablage.pfad(e["kennung"]).name == e["name"]


# ---------- Öffnen nur aus dem Register ----------
@pytest.mark.parametrize("kennung", ["", "zz", "../../x", "0123456789abcdeg", None, 5])
def test_pfad_nur_mit_gueltiger_kennung(ablage, kennung):
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(kennung)


def test_pfad_geloeschte_datei(ablage):
    e = ablage.speichern(b"x", "Weg", "word", datum=TAG)
    (ablage.ordner() / e["name"]).unlink()
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(e["kennung"])


def test_pfad_mit_manipuliertem_namen_im_register(ablage):
    e = ablage.speichern(b"x", "Echt", "word", datum=TAG)
    daten = json.loads(ablage.register.read_text(encoding="utf-8"))
    daten["dateien"][-1]["name"] = "..\\..\\geheim.docx"
    ablage.register.write_text(json.dumps(daten), encoding="utf-8")
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(e["kennung"])


# ---------- Umleitungen ----------
@pytest.mark.skipif(sys.platform != "win32", reason="Abzweigpunkte gibt es nur unter Windows")
def test_wais_als_abzweigpunkt_wird_abgelehnt(tmp_path):
    import _winapi

    dokumente, anderswo = tmp_path / "Dokumente", tmp_path / "anderswo"
    dokumente.mkdir()
    anderswo.mkdir()
    _winapi.CreateJunction(str(anderswo), str(dokumente / "WAIS"))
    ablage = oa.Ablage(dokumente, tmp_path / "r.json")
    assert oa.ist_verweis(dokumente / "WAIS")
    with pytest.raises(oa.AblageFehler):
        ablage.speichern(b"x", "T", "word", datum=TAG)
    assert list(anderswo.iterdir()) == []


def test_normaler_ordner_ist_kein_verweis(tmp_path):
    assert not oa.ist_verweis(tmp_path)
    assert not oa.ist_verweis(tmp_path / "gibt-es-nicht")


def test_wais_als_datei_wird_abgelehnt(tmp_path):
    (tmp_path / "D").mkdir()
    (tmp_path / "D" / "WAIS").write_bytes(b"")
    with pytest.raises(oa.AblageFehler):
        oa.Ablage(tmp_path / "D", tmp_path / "r.json").ordner()


def test_fehlender_dokumente_ordner(tmp_path):
    with pytest.raises(oa.AblageFehler):
        oa.Ablage(tmp_path / "fehlt", tmp_path / "r.json").ordner()


# ---------- Bekannter Ordner ----------
@pytest.mark.skipif(sys.platform != "win32", reason="bekannter Ordner nur unter Windows")
def test_dokumente_ordner_ist_der_bekannte_ordner():
    pfad = oa.dokumente_ordner()
    assert pfad.is_absolute() and pfad.is_dir()


def test_dokumente_ordner_rueckfall_ohne_shell(tmp_path):
    with mock.patch.object(oa, "_bekannter_ordner", return_value=None), \
         mock.patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
        assert oa.dokumente_ordner() == tmp_path / "Documents"


def test_standard_ablage_nutzt_localappdata_fuer_das_register(tmp_path):
    with mock.patch.object(oa, "dokumente_ordner", return_value=tmp_path), \
         mock.patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path / "lad")}):
        ablage = oa.Ablage.standard()
    assert ablage.register == tmp_path / "lad" / "WAMO" / "ablage.json"
    assert ablage.wurzel == tmp_path
    assert Path(ablage.wurzel / oa.ORDNER_NAME).name == "WAIS"
