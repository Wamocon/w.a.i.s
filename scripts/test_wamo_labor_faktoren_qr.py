"""Tests für einrichten --qr von scripts/wamo_labor_faktoren.py (QR-Code eines neuen Faktors zum Scannen anzeigen).

Aufruf (aus scripts):  D:\\IDEA\\Projekt\\wamo\\voice-core\\.venv\\Scripts\\python.exe -m pytest -q
Kein Netz außer der Attrappe von GoTrue auf Loopback, nie die echte Umschlag-Datei, nie ein echter Browser und nie eine echte Eingabe:
Öffnen und Warten sind ersetzt (die selbstwirkende Fixture kein_echtes_home sperrt beides zusätzlich), QR-Dateien entstehen nur im
temporären Ordner (LOCALAPPDATA zeigt dorthin). Die SVG der Attrappe trägt die otpauth-URI samt Seed als Text, so fällt jede Spur
in einer Ausgabe auf.
"""
from __future__ import annotations

import base64
import os
import re
import signal
from pathlib import Path

import pytest

import wamo_labor_faktoren as wlf
import wamo_labor_faktoren_qr as qr
import wamo_labor_faktoren_signale as sg
from test_wamo_labor_faktoren import seed_von, umschlag_datei, umschlag_text
from test_wamo_labor_faktoren_lauf import (  # noqa: F401  (Fixtures)
    _alle_geheimnisse, einrichten, email, kein_echtes_home, labor, seed_der_datei, umgebung)


def ablage() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "WAMO"


def qr_ordner() -> list[Path]:
    return sorted(ablage().glob(qr.ORDNER_PRAEFIX + "*")) if ablage().is_dir() else []


class Browser:
    """Ersetzt Öffnen und Warten: merkt sich je Aufruf Datei und Inhalt. Beim Warten muss die Datei noch da sein."""

    def __init__(self, beim_warten=None):
        self.geoeffnet: list[Path] = []
        self.inhalte: list[str] = []
        self.gewartet = 0
        self.beim_warten = beim_warten

    def oeffnen(self, pfad: Path) -> None:
        self.geoeffnet.append(Path(pfad))
        self.inhalte.append(Path(pfad).read_text(encoding="utf-8"))

    def warten(self, prompt: str = "") -> str:
        assert prompt == "" and self.geoeffnet[-1].is_file(), "beim Warten ist die QR-Datei noch da"
        self.gewartet += 1
        if self.beim_warten is not None:
            self.beim_warten()
        return ""


@pytest.fixture
def browser(monkeypatch):
    b = Browser()
    monkeypatch.setattr(qr, "OEFFNEN", b.oeffnen)
    monkeypatch.setattr(qr, "WARTEN", b.warten)
    monkeypatch.setattr(qr, "KONSOLE", lambda: True)
    return b


def svg_der_seite(inhalt: str) -> str:
    treffer = re.search(r'class="qr"[^>]*src="data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"', inhalt)
    assert treffer, "die Seite zeigt den QR als Daten-URL"
    return base64.b64decode(treffer.group(1)).decode("utf-8")


def svg_des_profils(labor, kennung: str) -> str:
    faktoren = [f for f in labor.faktoren_von(email(kennung)) if f["status"] == "verified"]
    assert len(faktoren) == 1
    return labor.qr_svgs[faktoren[0]["id"]]


# ---------- Normalfall ----------

def test_qr_je_profil_mit_der_svg_und_nach_enter_geloescht(capsys, umgebung, labor, tmp_path, browser):
    datei = umschlag_datei(tmp_path, umschlag_text(3))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02,labor-03", "--qr")
    assert code == 0 and err == ""
    kennungen = ["labor-01", "labor-02", "labor-03"]
    assert [p.name for p in browser.geoeffnet] == [f"qr-{k}.html" for k in kennungen] and browser.gewartet == 3
    for k, pfad, inhalt in zip(kennungen, browser.geoeffnet, browser.inhalte):
        assert svg_der_seite(inhalt) == svg_des_profils(labor, k), "genau die SVG aus der Antwort beim Anlegen"
        assert f"<h1>{k}</h1>" in inhalt and "Mit der Authenticator-App scannen, dann im Konsolenfenster Enter drücken." in inhalt
        assert pfad.parent.parent == ablage() and pfad.parent.name.startswith(qr.ORDNER_PRAEFIX)
        assert not pfad.exists() and not pfad.parent.exists(), "Datei und Ordner sind nach Enter gelöscht"
        assert f"QR für {k} angezeigt, nach dem Scannen Enter drücken" in out
        assert f"{k}: QR-Datei gelöscht, bitte den Tab im Browser schließen" in out
        assert seed_der_datei(datei, k) == labor.faktoren_von(email(k))[0]["seed"], "der Seed steht weiter in der Umschlag-Datei"
    assert out.index("labor-01: Faktor eingerichtet") < out.index("QR für labor-01 angezeigt") < out.index("labor-02: Faktor eingerichtet")
    assert qr_ordner() == [] and labor.sitzungen == {}, "QR erst nach dem Ende der Sitzung"
    assert "Zusammenfassung: 3 eingerichtet, 0 übersprungen, 0 fehlgeschlagen" in out


def test_qr_datei_bekommt_die_rechte_solange_sie_leer_ist(capsys, umgebung, labor, tmp_path, browser):
    assert einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--qr")[0] == 0
    html = [(p, groesse) for p, groesse in umgebung.aufrufe if p.suffix == ".html"]
    assert html == [(browser.geoeffnet[0], 0)]


@pytest.mark.skipif(os.name != "nt", reason="icacls nur unter Windows")
def test_qr_datei_mit_den_echten_rechten_nur_fuer_den_benutzer(capsys, monkeypatch, umgebung, labor, tmp_path, browser):
    import subprocess
    import wamo_labor_faktoren_umschlag as um
    monkeypatch.setattr(wlf, "RECHTE_SETZEN", um.rechte_nur_benutzer)
    acl = []

    def oeffnen(pfad):
        acl.append(subprocess.run([os.path.join(os.environ["SystemRoot"], "System32", "icacls.exe"), str(pfad)], capture_output=True,
                                  text=True).stdout)
        browser.oeffnen(pfad)

    monkeypatch.setattr(qr, "OEFFNEN", oeffnen)
    assert einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--qr")[0] == 0
    assert len(acl) == 1 and acl[0].count("(F)") == 1 and "(I)" not in acl[0] and "Everyone" not in acl[0], acl[0]


def test_seite_laedt_nichts_aus_dem_netz(capsys, umgebung, labor, tmp_path, browser):
    assert einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--qr")[0] == 0
    inhalt = browser.inhalte[0]
    assert "default-src 'none'" in inhalt and "img-src data:" in inhalt
    assert all(q.startswith("data:") for q in re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', inhalt))
    for verboten in ("<script", "<link", "<iframe", "<object", "@import", "url(", "http://", "https://"):
        assert verboten not in inhalt, verboten


def test_qr_roh_ohne_daten_url_wird_ebenso_gezeigt(capsys, umgebung, labor, tmp_path, browser):
    labor.qr_form = "roh"
    assert einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--qr")[0] == 0
    assert svg_der_seite(browser.inhalte[0]) == svg_des_profils(labor, "labor-01")


def test_neu_mit_qr_zeigt_den_neuen_faktor(capsys, umgebung, labor, tmp_path, browser):
    _, alter_seed = labor.faktor_anlegen(email("labor-01"))
    datei = umschlag_datei(tmp_path, umschlag_text(1, seeds={"labor-01": alter_seed}))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01", "--neu", "--qr")
    assert code == 0 and err == ""
    assert svg_der_seite(browser.inhalte[0]) == svg_des_profils(labor, "labor-01")
    assert alter_seed not in browser.inhalte[0] and seed_der_datei(datei, "labor-01") != alter_seed


# ---------- Abbruch und Fehler ----------

def test_ausnahme_nach_dem_oeffnen_loescht_die_datei_und_haelt_an(capsys, umgebung, labor, tmp_path, browser):
    def kaputt():
        raise RuntimeError("Text mit Wert")

    browser.beim_warten = kaputt
    datei = umschlag_datei(tmp_path, umschlag_text(3))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02,labor-03", "--qr")
    assert code == 1
    assert len(browser.geoeffnet) == 1 and not browser.geoeffnet[0].exists() and qr_ordner() == []
    assert "labor-01: FEHLER: QR nicht angezeigt (unerwarteter Fehler (RuntimeError))" in err and "Text mit Wert" not in out + err
    assert "einrichten --profile labor-01 --neu --qr" in err and "nicht begonnen: labor-02, labor-03" in err
    assert seed_der_datei(datei, "labor-01") == labor.faktoren_von(email("labor-01"))[0]["seed"], "der Faktor bleibt mit Seed"
    assert labor.faktoren_von(email("labor-02")) == [] and labor.faktoren_von(email("labor-03")) == [], "die übrigen bleiben unberührt"
    assert "labor-01: QR-Datei gelöscht, bitte den Tab im Browser schließen" in out


def test_strg_c_beim_warten_loescht_die_datei(capsys, umgebung, labor, tmp_path, browser):
    def strg_c():
        raise KeyboardInterrupt

    browser.beim_warten = strg_c
    datei = umschlag_datei(tmp_path, umschlag_text(2))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02", "--qr")
    assert code == wlf.EXIT_ABBRUCH and "Abgebrochen." in err
    assert not browser.geoeffnet[0].exists() and qr_ordner() == []
    assert seed_der_datei(datei, "labor-01") and labor.faktoren_von(email("labor-02")) == []


def test_signal_beim_warten_loescht_die_datei(capsys, umgebung, labor, tmp_path, browser):
    vorher = {s: signal.getsignal(s) for s in sg.SIGNALE}
    browser.beim_warten = lambda: signal.raise_signal(signal.SIGTERM)
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02", "--qr")
    assert code == 128 + signal.SIGTERM and not browser.geoeffnet[0].exists() and qr_ordner() == []
    assert {s: signal.getsignal(s) for s in sg.SIGNALE} == vorher


def test_eof_statt_enter_haelt_an_und_loescht(capsys, umgebung, labor, tmp_path, browser):
    def eof():
        raise EOFError

    browser.beim_warten = eof
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02", "--qr")
    assert code == 1 and "keine Eingabe in der Konsole möglich" in err and qr_ordner() == []


def test_browser_startet_nicht(capsys, umgebung, labor, tmp_path, browser, monkeypatch):
    def nein(pfad):
        raise OSError("kein Programm für .html")

    monkeypatch.setattr(qr, "OEFFNEN", nein)
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02", "--qr")
    assert code == 1 and "QR nicht angezeigt (Ein-/Ausgabefehler (OSError))" in err and "kein Programm" not in err
    assert qr_ordner() == [] and browser.gewartet == 0 and "QR für labor-01 angezeigt" not in out


@pytest.mark.parametrize("form,grund", [("fehlt", "keinen QR-Code geliefert"), ("kaputt", "keine SVG")])
def test_qr_fehlt_oder_kaputt_haelt_an(capsys, umgebung, labor, tmp_path, browser, form, grund):
    labor.qr_form = form
    datei = umschlag_datei(tmp_path, umschlag_text(2))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02", "--qr")
    assert code == 1 and grund in err and "nicht begonnen: labor-02" in err and browser.geoeffnet == []
    assert seed_der_datei(datei, "labor-01") and labor.faktoren_von(email("labor-02")) == []


def test_fehler_eines_profils_laesst_die_uebrigen_mit_qr_weiterlaufen(capsys, umgebung, labor, tmp_path, browser):
    labor.fehler("POST", "/verify", 400, "mfa_verification_failed", email=email("labor-01"))
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02", "--qr")
    assert code == 1 and "labor-01: FEHLER:" in err and [p.name for p in browser.geoeffnet] == ["qr-labor-02.html"]


# ---------- ohne --qr, Trockenlauf, übersprungen, Konsole ----------

def test_ohne_qr_wird_nichts_geoeffnet(capsys, umgebung, labor, tmp_path, browser):
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02")
    assert code == 0 and browser.geoeffnet == [] and browser.gewartet == 0
    assert "QR" not in out + err and not ablage().exists()


def test_trocken_mit_qr_zeigt_nur_den_plan(capsys, umgebung, labor, tmp_path, browser):
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path, umschlag_text(2)), "--profile", "labor-01,labor-02", "--trocken",
                                "--neu", "--qr")
    assert code == 0 and labor.anfragen == [] and browser.geoeffnet == [] and not ablage().exists()
    assert out.count("danach den QR-Code zum Scannen im Browser zeigen") == 2


def test_trocken_ohne_qr_nennt_keinen_qr(capsys, umgebung, labor, tmp_path, browser):
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--trocken")
    assert code == 0 and "QR" not in out


def test_uebersprungenes_profil_bekommt_keinen_qr(capsys, umgebung, labor, tmp_path, browser):
    _, seed = labor.faktor_anlegen(email("labor-01"))
    datei = umschlag_datei(tmp_path, umschlag_text(2, seeds={"labor-01": seed}))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02", "--qr")
    assert code == 0 and "labor-01: kein QR, der Faktor bestand schon (für einen neuen QR mit --neu einrichten)" in out
    assert [p.name for p in browser.geoeffnet] == ["qr-labor-02.html"]


def test_ohne_konsole_beginnt_der_lauf_nicht(capsys, umgebung, labor, tmp_path, monkeypatch):
    datei = umschlag_datei(tmp_path)
    vorher = datei.read_bytes()
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01", "--qr")
    assert code == 2 and "--qr braucht eine Konsole" in err
    assert labor.anfragen == [] and datei.read_bytes() == vorher, "weder Server noch Datei werden angefasst"


def test_reste_eines_abgebrochenen_laufs_werden_geloescht(capsys, umgebung, labor, tmp_path, browser):
    rest = ablage() / (qr.ORDNER_PRAEFIX + "alt1")
    rest.mkdir(parents=True)
    (rest / "qr-labor-01.html").write_text("alt", encoding="utf-8")
    fremd = ablage() / (qr.ORDNER_PRAEFIX + "alt2")
    fremd.mkdir()
    (fremd / "notiz.txt").write_text("fremd", encoding="utf-8")
    code, out, err = einrichten(capsys, labor, umschlag_datei(tmp_path), "--profile", "labor-01", "--qr")
    assert code == 0 and not rest.exists() and "QR-Datei eines abgebrochenen Laufs gelöscht" in out
    assert (fremd / "notiz.txt").is_file(), "fremde Dateien bleiben"
    assert "ließ sich nicht löschen" in err and str(fremd) in err


# ---------- Geheimnisse ----------

def test_geheimnisse_und_qr_erscheinen_nie_in_der_ausgabe(capsys, umgebung, labor, tmp_path, browser):
    datei = umschlag_datei(tmp_path, umschlag_text(3))
    labor.fehler("POST", "/verify", 400, "mfa_verification_failed", email=email("labor-02"))
    code, out, err = einrichten(capsys, labor, datei, "--profile", "labor-01,labor-02,labor-03", "--qr")
    assert code == 1 and browser.gewartet == 2
    text = out + err
    svgs = set(labor.qr_svgs.values())
    for wert in _alle_geheimnisse(labor, datei) | svgs | {base64.b64encode(s.encode()).decode() for s in svgs}:
        assert wert not in text, "ein Geheimnis oder die SVG steht in der Ausgabe"
    for muster in ("otpauth", "<svg", "data:image", "secret="):
        assert muster not in text, muster


def test_repr_nennt_den_qr_nicht():
    svg = "<svg>" + seed_von("x") + "</svg>"
    assert seed_von("x") not in repr(wlf.Ergebnis(wlf.EINGERICHTET, "labor-01", "ok", qr=svg))
    assert seed_von("x") not in repr(wlf.api.NeuerFaktor("faktor-1234", seed_von("y"), svg))


# ---------- Bausteine ----------

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0h1v1H0z"/></svg>'


@pytest.mark.parametrize("eingabe", [
    f"data:image/svg+xml;utf-8,{SVG}\n",
    f"data:image/svg+xml;charset=utf-8,{SVG}",
    "data:image/svg+xml;base64," + base64.b64encode(SVG.encode()).decode(),
    "data:image/svg+xml;charset=utf-8," + "".join(f"%{b:02X}" for b in SVG.encode()),
    SVG,
    '<?xml version="1.0" encoding="UTF-8"?>\n' + SVG,
])
def test_svg_aus_antwort_versteht_die_formen(eingabe):
    assert qr.svg_aus_antwort(eingabe).endswith(SVG)


@pytest.mark.parametrize("eingabe", [
    None, "", "   ", 7, "data:text/plain,abc", "data:image/png;base64,AAAA", "data:image/svg+xml;base64,@@@", "<html></html>",
    "data:image/svg+xml;utf-8",
])
def test_svg_aus_antwort_lehnt_ab(eingabe):
    with pytest.raises(qr.QrFehler):
        qr.svg_aus_antwort(eingabe)


def test_svg_aus_antwort_hat_eine_grenze():
    with pytest.raises(qr.QrFehler):
        qr.svg_aus_antwort("<svg " + "x" * qr.SVG_GRENZE + ">")


def test_ohne_viewbox_wird_er_aus_den_massen_ergaenzt():
    """So schreibt GoTrue die SVG (svgo): nur width und height, Attribute über Zeilen verteilt, Zeilenumbruch am Ende."""
    roh = "\n".join(['<svg width="147" height="147"', '     xmlns="http://www.w3.org/2000/svg"',
                     '     xmlns:xlink="http://www.w3.org/1999/xlink">', '<rect x="12" y="12" width="3" height="3" style="fill:black"/>',
                     "</svg>", ""])
    svg = qr.svg_aus_antwort("data:image/svg+xml;utf-8," + roh)
    assert svg.startswith('<svg viewBox="0 0 147 147" shape-rendering="crispEdges" width="147" height="147"') and svg.endswith("</svg>")
    assert qr.mit_viewbox(SVG) == SVG, "ein vorhandener viewBox bleibt"
    assert qr.mit_viewbox('<svg width="100%"><g/></svg>') == '<svg width="100%"><g/></svg>', "ohne Pixelmaße bleibt alles"


def test_zeigen_prueft_das_profil(monkeypatch):
    for kennung in ("labor-10", "..\\labor-01", "labor-01/x"):
        with pytest.raises(qr.QrFehler):
            qr.zeigen(kennung, SVG, print, print, lambda p: None)
    assert not ablage().exists()


def test_seite_maskiert_und_traegt_die_kopfzeile():
    inhalt = qr.seite("labor-01", SVG)
    assert inhalt.startswith("<!doctype html>") and "WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn" in inhalt
    assert "<title>QR labor-01</title>" in inhalt and SVG not in inhalt and "Seite 1" in inhalt
