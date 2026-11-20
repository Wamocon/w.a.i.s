"""Die Frist des Testlabors kommt aus einer einzigen Konstante (wamo_labor_dienst/frist.py): Labortag, Aufbewahrung (D10) und erstes Löschdatum
folgen daraus. Die Entscheidung über das Datum steht nur hier und in frist.py; alle anderen Tests leiten ihre Daten von den Konstanten ab."""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from hilfen import BETREUER_TOKEN, KERN_TOKEN, token_datei

from wamo_labor_dienst import frist
from wamo_labor_dienst import konfig as konfig_modul
from wamo_labor_dienst.konfig import KonfigFehler, aus_umgebung

WURZEL = Path(__file__).resolve().parents[2]
PAKET_ORDNER = Path(__file__).resolve().parents[1]
FRIST_ENV = WURZEL / "infra" / "sokrates2" / "wamo-labor" / "frist.env"
SEITE = Path(frist.__file__).resolve().parent / "web" / "datenschutz.html"
DEUTSCHES_DATUM = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")


def _env(tmp_path, **extra):
    kern, betreuer = tmp_path / "k", tmp_path / "b"
    token_datei(kern, KERN_TOKEN)
    token_datei(betreuer, BETREUER_TOKEN)
    return {"WAMO_LABOR_DIENST_KERN_TOKEN_DATEI": str(kern), "WAMO_LABOR_DIENST_BETREUER_TOKEN_DATEI": str(betreuer), **extra}


# ---------- die Entscheidung und ihre Ableitung ----------
def test_der_labortag_ist_der_05_12_2026():
    """Die Frist ist verschoben (vom 28.11.): Vorschlag, bis Niko sie bestätigt. Eine weitere Verschiebung ändert LABORTAG und diese Zeile."""
    assert frist.LABORTAG == date(2026, 12, 5)
    assert frist.LABORTAG.weekday() == 5  # ein Samstag


def test_aufbewahrung_und_loeschlauf_folgen_aus_dem_labortag():
    assert frist.AUFBEWAHRUNG_NACH_LABORTAG_TAGE == 13
    assert frist.AUFBEWAHRUNG_BIS == frist.LABORTAG + timedelta(days=13) == date(2026, 12, 18)
    assert frist.LOESCHLAUF_AB == frist.AUFBEWAHRUNG_BIS + timedelta(days=1) == frist.LABORTAG + timedelta(days=14) == date(2026, 12, 19)


def test_deutsches_datum_hat_fuehrende_nullen():
    assert frist.deutsch(date(2026, 12, 5)) == "05.12.2026"
    assert frist.deutsch(frist.AUFBEWAHRUNG_BIS) == "18.12.2026"


def test_konfig_leitet_alle_grenzen_aus_der_frist_ab():
    assert konfig_modul.STANDARD_BIS == konfig_modul.HOECHSTES_BIS == frist.AUFBEWAHRUNG_BIS
    assert konfig_modul.FRUEHESTES_BIS == frist.LABORTAG  # davor darf die Aufbewahrung nie enden: Die Daten des Labortags blieben nicht
    assert konfig_modul.FRUEHESTES_DATUM < frist.LABORTAG  # eine Uhr vor dem Bau geht falsch, liegt aber vor dem Labortag


# ---------- Grenzfälle der Einstellung WAMO_LABOR_DIENST_BIS ----------
def test_standard_ist_das_ende_der_aufbewahrung(tmp_path):
    assert aus_umgebung(_env(tmp_path)).bis == frist.AUFBEWAHRUNG_BIS


@pytest.mark.parametrize("bis", [frist.LABORTAG, frist.LABORTAG + timedelta(days=1), frist.AUFBEWAHRUNG_BIS - timedelta(days=1), frist.AUFBEWAHRUNG_BIS])
def test_bis_von_labortag_bis_ende_der_aufbewahrung_ist_erlaubt(tmp_path, bis):
    assert aus_umgebung(_env(tmp_path, WAMO_LABOR_DIENST_BIS=bis.isoformat())).bis == bis


@pytest.mark.parametrize("bis", [frist.LABORTAG - timedelta(days=1), date(2026, 11, 28), date(2026, 11, 12), date(2020, 1, 1),
                                 frist.AUFBEWAHRUNG_BIS + timedelta(days=1), frist.LOESCHLAUF_AB, date(2027, 1, 1), date(2099, 12, 31)])
def test_bis_vor_dem_labortag_oder_nach_der_aufbewahrung_ist_ein_fehler(tmp_path, bis):
    with pytest.raises(KonfigFehler, match=f"WAMO_LABOR_DIENST_BIS.*{frist.LABORTAG.isoformat()}.*{frist.AUFBEWAHRUNG_BIS.isoformat()}"):
        aus_umgebung(_env(tmp_path, WAMO_LABOR_DIENST_BIS=bis.isoformat()))


def test_die_alte_frist_ist_nicht_mehr_gueltig(tmp_path):
    """Ein veralteter Eintrag WAMO_LABOR_DIENST_BIS=2026-11-28 (alter Labortag) wird beim Start gemeldet, statt die Daten des neuen Labortags zu löschen."""
    with pytest.raises(KonfigFehler, match="WAMO_LABOR_DIENST_BIS"):
        aus_umgebung(_env(tmp_path, WAMO_LABOR_DIENST_BIS="2026-11-28"))


# ---------- die Seite für die Besucher ----------
def test_die_seite_nennt_das_ende_der_aufbewahrung_aus_der_konstante(client):
    r = client.get("/datenschutz")
    assert r.status_code == 200
    assert frist.deutsch(frist.AUFBEWAHRUNG_BIS) in r.text and frist.PLATZHALTER not in r.text and "{{" not in r.text


def test_die_quelle_der_seite_hat_nur_den_platzhalter_kein_festes_datum():
    quelle = SEITE.read_text(encoding="utf-8")
    assert quelle.count(frist.PLATZHALTER) == 1 and not DEUTSCHES_DATUM.search(quelle)


def test_einsetzen_ersetzt_jeden_platzhalter_und_laesst_sonst_alles():
    datum = frist.deutsch(frist.AUFBEWAHRUNG_BIS)
    assert frist.einsetzen("bis " + frist.PLATZHALTER + ", dann " + frist.PLATZHALTER + ".") == f"bis {datum}, dann {datum}."
    assert frist.einsetzen("ohne Platzhalter") == "ohne Platzhalter"
    assert frist.einsetzen_bytes(("<b>" + frist.PLATZHALTER + "</b>").encode()) == f"<b>{datum}</b>".encode()


# ---------- Übergabe an Skripte (Shell, Rauchtest) ----------
def test_umgebungszeilen_sind_dreimal_jjjjmmtt():
    zeilen = frist.umgebungszeilen()
    assert zeilen == [f"WAMO_LABOR_LABORTAG={frist.LABORTAG:%Y%m%d}", f"WAMO_LABOR_AUFBEWAHRUNG_BIS={frist.AUFBEWAHRUNG_BIS:%Y%m%d}",
                      f"WAMO_LABOR_LOESCHLAUF_AB={frist.LOESCHLAUF_AB:%Y%m%d}"]
    assert all(re.fullmatch(r"WAMO_LABOR_[A-Z_]+=[0-9]{8}", z) for z in zeilen)


def test_die_datei_frist_env_im_betrieb_stimmt_mit_der_konstante_ueberein():
    """frist.env liegt neben der Compose-Datei, weil Löschlauf und Rauchtest allein auf dem Server laufen und das Paket des Dienstes dort nicht kennen.
    Sie wird erzeugt, nie von Hand geändert: python -m wamo_labor_dienst.frist --schreiben ../infra/sokrates2/wamo-labor/frist.env (im Ordner labor-dienst)."""
    assert FRIST_ENV.read_text(encoding="utf-8") == frist.datei_inhalt(), "frist.env ist veraltet, neu erzeugen (siehe Docstring)"
    assert b"\r" not in FRIST_ENV.read_bytes()


def test_der_einstieg_gibt_die_zeilen_aus():
    r = subprocess.run([sys.executable, "-m", "wamo_labor_dienst.frist"], cwd=PAKET_ORDNER, capture_output=True, timeout=30)
    assert r.returncode == 0 and r.stdout == frist.datei_inhalt().encode("utf-8")  # Bytes: gleich auf Windows und Linux, nur LF


def test_der_einstieg_prueft_eine_datei(tmp_path):
    gut, schlecht = tmp_path / "gut.env", tmp_path / "schlecht.env"
    gut.write_text(frist.datei_inhalt(), encoding="utf-8", newline="\n")
    schlecht.write_text("WAMO_LABOR_LABORTAG=20261128\n", encoding="utf-8", newline="\n")
    kommando = [sys.executable, "-m", "wamo_labor_dienst.frist", "--pruefen"]
    assert subprocess.run([*kommando, str(gut)], cwd=PAKET_ORDNER, capture_output=True, timeout=30).returncode == 0
    assert subprocess.run([*kommando, str(schlecht)], cwd=PAKET_ORDNER, capture_output=True, timeout=30).returncode == 1
    assert subprocess.run([*kommando, str(tmp_path / "fehlt.env")], cwd=PAKET_ORDNER, capture_output=True, timeout=30).returncode == 1


def test_der_einstieg_schreibt_eine_datei(tmp_path):
    ziel = tmp_path / "frist.env"
    r = subprocess.run([sys.executable, "-m", "wamo_labor_dienst.frist", "--schreiben", str(ziel)], cwd=PAKET_ORDNER, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and ziel.read_bytes() == frist.datei_inhalt().encode("utf-8")
