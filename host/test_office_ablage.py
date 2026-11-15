"""Tests für office_ablage.py: Ordner WAIS im bekannten Ordner Dokumente, Dateinamen, Register, nie überschreiben, keine Umleitung."""

import hashlib
import json
import os
import sys
import threading
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


def _symlink(ziel: Path, verweis: Path) -> None:
    try:
        os.symlink(ziel, verweis)
    except (OSError, NotImplementedError) as e:  # Windows ohne Entwicklermodus oder Recht
        pytest.skip(f"Symlink nicht anlegbar ({type(e).__name__})")


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


@pytest.mark.parametrize("zeichen", [0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x061C, 0x00AD, 0x180E, 0xD800, 0xDBFF, 0xDFFF])
def test_unsichtbare_zeichen_fallen_aus_dem_dateinamen(zeichen):
    assert oa.dateiname("Ange" + chr(zeichen) + "bot", "word", TAG) == "2026-11-30 Angebot.docx"


def test_dateiname_kuerzt_titel_auf_80_zeichen_und_endung_je_format():
    name = oa.dateiname("x" * 300, "excel", TAG)
    assert name == "2026-11-30 " + "x" * oa.TITEL_MAX + ".xlsx"
    endungen = [oa.dateiname("t", f, TAG).rsplit(".", 1)[1] for f in ("word", "excel", "powerpoint", "pdf", "csv", "markdown")]
    assert endungen == ["docx", "xlsx", "pptx", "pdf", "csv", "md"]
    with pytest.raises(oa.AblageFehler):
        oa.dateiname("t", "exe", TAG)


# ---------- Speichern ----------
def test_speichern_legt_ordner_an_und_registriert_mit_pruefsumme(ablage):
    eintrag, pfad = ablage.speichern(b"inhalt", "Angebot", "word", canvas_id="11111111-1111-4111-8111-111111111111", datum=TAG)
    assert pfad == ablage.ordner() / eintrag["name"]  # der Pfad kommt gleich mit, ohne zweites Nachschlagen
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
    a, pa = ablage.speichern(b"eins", "Gleich", "word", datum=TAG)
    b, _ = ablage.speichern(b"zwei", "Gleich", "word", datum=TAG)
    c, _ = ablage.speichern(b"drei", "Gleich", "word", datum=TAG)
    assert [a["name"], b["name"], c["name"]] == ["2026-11-30 Gleich.docx", "2026-11-30 Gleich (2).docx", "2026-11-30 Gleich (3).docx"]
    assert pa.read_bytes() == b"eins"


def test_vorhandene_fremde_datei_bleibt(ablage):
    ordner = ablage.ordner()
    (ordner / "2026-11-30 Bericht.pdf").write_bytes(b"von Niko")
    e, _ = ablage.speichern(b"%PDF-neu", "Bericht", "pdf", datum=TAG)
    assert e["name"] == "2026-11-30 Bericht (2).pdf"
    assert (ordner / "2026-11-30 Bericht.pdf").read_bytes() == b"von Niko"


def test_register_hoechstens_max_eintraege(tmp_path):
    (tmp_path / "D").mkdir()
    ablage = oa.Ablage(tmp_path / "D", tmp_path / "r.json", max_eintraege=3)
    kennungen = [ablage.speichern(b"x", f"T{i}", "markdown", datum=TAG)[0]["kennung"] for i in range(5)]
    assert [e["kennung"] for e in ablage.eintraege()] == kennungen[-3:]
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(kennungen[0])


def test_gleichzeitiges_speichern_und_oeffnen_aus_threads(ablage):
    fehler: list[BaseException] = []
    kennungen: list[str] = []
    start = threading.Barrier(8)

    def arbeit():
        try:
            start.wait()
            for _ in range(5):
                e, pfad = ablage.speichern(b"x", "Gleich", "csv", datum=TAG)
                kennungen.append(e["kennung"])
                assert ablage.pfad(e["kennung"]) == pfad
        except BaseException as e:  # noqa: BLE001
            fehler.append(e)

    faeden = [threading.Thread(target=arbeit) for _ in range(8)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(30)
    assert fehler == []
    eintraege = ablage.eintraege()
    assert len(eintraege) == 40 == len(kennungen)
    assert len({e["name"] for e in eintraege}) == 40  # nie zweimal derselbe Name
    assert sorted(p.name for p in ablage.ordner().iterdir()) == sorted(e["name"] for e in eintraege)


# ---------- Register: fehlt, kaputt, gesperrt ----------
def test_fehlendes_register_ist_leer(ablage):
    assert not ablage.register.exists()
    assert ablage.eintraege() == []


def test_kaputtes_register_wird_beiseitegelegt(ablage):
    ablage.register.parent.mkdir(parents=True, exist_ok=True)
    ablage.register.write_text("{kaputt", encoding="utf-8")
    assert ablage.eintraege() == []
    beiseite = list(ablage.register.parent.glob("ablage.json.*.kaputt"))
    assert len(beiseite) == 1 and beiseite[0].read_text(encoding="utf-8") == "{kaputt"  # nichts still verloren
    e, pfad = ablage.speichern(b"x", "Neu", "csv", datum=TAG)
    assert ablage.pfad(e["kennung"]) == pfad
    assert [x["kennung"] for x in ablage.eintraege()] == [e["kennung"]]


def test_gesperrtes_register_wird_kurz_wiederholt(ablage):
    ablage.speichern(b"x", "A", "csv", datum=TAG)
    echt = Path.read_text
    versuche = []

    def einmal_gesperrt(self, *a, **k):
        if self == ablage.register and not versuche:
            versuche.append(1)
            raise PermissionError("von einem Virenscanner gesperrt")
        return echt(self, *a, **k)

    with mock.patch.object(Path, "read_text", einmal_gesperrt), mock.patch.object(oa, "WARTEN_SECS", 0.001):
        assert len(ablage.eintraege()) == 1
    assert versuche == [1]


def test_dauerhaft_gesperrtes_register_ist_ein_fehler_kein_leeres(ablage):
    e, _ = ablage.speichern(b"x", "A", "csv", datum=TAG)
    echt = Path.read_text

    def gesperrt(self, *a, **k):
        if self == ablage.register:
            raise PermissionError("gesperrt")
        return echt(self, *a, **k)

    with mock.patch.object(Path, "read_text", gesperrt), mock.patch.object(oa, "WARTEN_SECS", 0.001):
        with pytest.raises(oa.AblageFehler):
            ablage.eintraege()
        with pytest.raises(oa.AblageFehler):
            ablage.speichern(b"y", "B", "csv", datum=TAG)  # nie ein Register ohne die alten Einträge schreiben
    assert [x["kennung"] for x in ablage.eintraege()] == [e["kennung"]]
    assert sorted(p.name for p in ablage.ordner().iterdir()) == [e["name"]]  # die neue Datei ist wieder weg


def test_ersetzen_wird_bei_permissionerror_wiederholt(ablage):
    echt = os.replace
    versuche = []

    def zweimal_gesperrt(a, b):
        if len(versuche) < 2:
            versuche.append(1)
            raise PermissionError("Register gerade offen")
        return echt(a, b)

    with mock.patch.object(oa.os, "replace", zweimal_gesperrt), mock.patch.object(oa, "WARTEN_SECS", 0.001):
        e, pfad = ablage.speichern(b"x", "A", "csv", datum=TAG)
    assert ablage.pfad(e["kennung"]) == pfad
    assert list(ablage.register.parent.glob("*.tmp")) == []


def test_ersetzen_scheitert_raeumt_auf(ablage):
    alt, _ = ablage.speichern(b"x", "Alt", "csv", datum=TAG)

    def immer_gesperrt(a, b):
        raise PermissionError("Register gerade offen")

    with mock.patch.object(oa.os, "replace", immer_gesperrt), mock.patch.object(oa, "WARTEN_SECS", 0.001):
        with pytest.raises(oa.AblageFehler):
            ablage.speichern(b"y", "Neu", "csv", datum=TAG)
    assert list(ablage.register.parent.glob("*.tmp")) == []  # keine Reste
    assert sorted(p.name for p in ablage.ordner().iterdir()) == [alt["name"]]  # die neue Datei ist wieder weg
    assert [e["kennung"] for e in ablage.eintraege()] == [alt["kennung"]]


# ---------- Öffnen nur aus dem Register ----------
@pytest.mark.parametrize("kennung", ["", "zz", "../../x", "0123456789abcdeg", None, 5])
def test_pfad_nur_mit_gueltiger_kennung(ablage, kennung):
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(kennung)


def test_pfad_geloeschte_datei(ablage):
    e, pfad = ablage.speichern(b"x", "Weg", "word", datum=TAG)
    pfad.unlink()
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(e["kennung"])


def _register_aendern(ablage, **felder) -> str:
    daten = json.loads(ablage.register.read_text(encoding="utf-8"))
    daten["dateien"][-1].update(felder)
    ablage.register.write_text(json.dumps(daten), encoding="utf-8")
    return daten["dateien"][-1]["kennung"]


def test_pfad_mit_manipuliertem_namen_im_register(ablage):
    ablage.speichern(b"x", "Echt", "word", datum=TAG)
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(_register_aendern(ablage, name="..\\..\\geheim.docx"))


@pytest.mark.parametrize("name,fmt", [("2026-11-30 Echt.exe", "word"), ("2026-11-30 Echt.docx", "pdf"),
                                      ("2026-11-30 Echt.docx", "exe"), ("2026-11-30 Echt.docx.", "word"),
                                      ("2026-11-30 Echt.lnk", "word")])
def test_pfad_nur_mit_fester_endung_passend_zum_format(ablage, name, fmt):
    e, pfad = ablage.speichern(b"x", "Echt", "word", datum=TAG)
    (pfad.parent / name.rstrip(".")).write_bytes(b"x")
    with pytest.raises(oa.AblageFehler):
        ablage.pfad(_register_aendern(ablage, name=name, format=fmt))


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


def test_haengender_symlink_in_wais_wird_nicht_verfolgt(ablage, tmp_path):
    anderswo = tmp_path / "anderswo"
    anderswo.mkdir()
    ziel = anderswo / "untergeschoben.docx"
    _symlink(ziel, ablage.ordner() / "2026-11-30 T.docx")
    e, pfad = ablage.speichern(b"x", "T", "word", datum=TAG)
    assert e["name"] == "2026-11-30 T (2).docx" and pfad.read_bytes() == b"x"
    assert not ziel.exists()  # Windows legte die Datei sonst am Ziel des Verweises an


def test_verweis_nach_dem_anlegen_wird_erkannt(ablage, tmp_path):
    """Auch wenn die Vorprüfung den Verweis nicht sieht (Wettlauf): der Endpfad der neuen Datei muss im Ordner WAIS liegen."""
    anderswo = tmp_path / "anderswo"
    anderswo.mkdir()
    ziel = anderswo / "untergeschoben.docx"
    _symlink(ziel, ablage.ordner() / "2026-11-30 T.docx")
    with mock.patch.object(oa, "_existiert", return_value=False):
        try:
            e, pfad = ablage.speichern(b"x", "T", "word", datum=TAG)
        except oa.AblageFehler:
            e = None
    assert not ziel.exists()  # angelegt und wieder entfernt, oder gar nicht angelegt
    if e is not None:
        assert pfad.parent == ablage.ordner() and not oa.ist_verweis(pfad)
    else:
        assert ablage.eintraege() == []


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
