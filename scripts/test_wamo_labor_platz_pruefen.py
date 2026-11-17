"""Tests für `wamo_labor_platz.py pruefen`: Zertifikat, Richtlinien, Chrome, Adressen mit TLS gegen die CA, Uhr, Netztrennung, Mikrofon.

Kein Netz: Abruf und TCP-Versuch der Netzprobe sind Attrappen. Die Eingabegeräte stehen in der Attrappe der Registrierung (nur lesend gelesen).
"""
from __future__ import annotations

import ipaddress
import json
import sys
import time
from email.utils import formatdate
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_labor_platz_attrappe as at  # noqa: E402
import wamo_labor_platz_testwelt as tw  # noqa: E402
from wamo_labor_platz_umgebung import Abruf, AbrufFehler  # noqa: E402

MM = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Capture"
BESCHR, SCHNITT = "{a45c254e-df1c-4efd-8020-67d146a850e0},2", "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
FESTE = ("https://192.168.178.136:55443/auth/v1/health", "https://192.168.178.136:55444/", "https://192.168.178.136:55445/",
         "https://192.168.178.136:55447/board")


@pytest.fixture(autouse=True)
def _fallen(monkeypatch, tmp_path):
    tw.fallen_stellen(monkeypatch, tmp_path / "echt")


def _mikrofon(reg, kennung: str, kurz: str, schnittstelle: str, zustand: int = 1) -> None:
    reg.vorbelegen("HKLM", f"{MM}\\{kennung}", {"DeviceState": ("dword", zustand)})
    reg.vorbelegen("HKLM", f"{MM}\\{kennung}\\Properties", {BESCHR: ("sz", kurz), SCHNITT: ("sz", schnittstelle)})


def _datum(abweichung_s: float = 0.0) -> str:
    return formatdate(tw.JETZT + abweichung_s, usegmt=True)


@pytest.fixture
def welt(tmp_path):
    w = tw.Welt(tmp_path / "w")
    assert w.lauf("einrichten", "--kiosk-konto", "--platz", "3") == 0
    w.umg.abruf = at.AbrufAttrappe(Abruf(200, _datum()))
    _mikrofon(w.reg, "{1}", "Mikrofon", "USB-Headset Modell A")
    w.zeilen.clear()
    return w


def _stufen(welt) -> list[str]:
    return [z.split("]")[0].lstrip("[") for z in welt.zeilen if z.startswith("[")]


def test_alles_in_ordnung(welt):
    assert welt.lauf("pruefen") == 0
    assert set(_stufen(welt)) == {"ok"} and len(_stufen(welt)) >= 9
    for thema in ("Zertifikat", "Richtlinien", "Chrome", "Uhr", "Mikrofon", "Platz"):
        assert any(thema in z for z in welt.zeilen), thema


def test_adressen_nur_die_festen_und_mit_ca_datei(welt):
    welt.lauf("pruefen")
    import wamo_labor_platz_adressen as adr
    urls = [u for u, _ in welt.umg.abruf.aufrufe]
    assert sorted(urls) == sorted(FESTE) and all(adr.adresse_zulaessig(u) for u in urls)
    assert {ca for _, ca in welt.umg.abruf.aufrufe} == {str(welt.ca)}


def test_pruefen_aendert_nichts(welt):
    dateien, reg, zert = welt.dateien(), welt.reg.momentaufnahme(), set(welt.zert.speicher)
    schreib, aenderungen = welt.reg.schreibzugriffe, welt.zert.aenderungen
    welt.lauf("pruefen")
    assert welt.dateien() == dateien and welt.reg.momentaufnahme() == reg and welt.zert.speicher == zert
    assert welt.reg.schreibzugriffe == schreib and welt.zert.aenderungen == aenderungen and welt.prozesse.aufrufe == []


def test_veraenderte_platzdatei_wird_gemeldet_und_nie_abgerufen(welt):
    daten = json.loads(welt.platz_datei.read_text(encoding="utf-8"))
    daten["board_url"] = "https://boese.example:55447/board"
    welt.platz_datei.write_text(json.dumps(daten), encoding="utf-8")
    assert welt.lauf("pruefen") == 1 and "verändert" in welt.text
    assert not any("boese" in u for u, _ in welt.umg.abruf.aufrufe)


def test_ohne_einrichten_wird_gemeldet(welt):
    welt.lauf("rueckweg")
    welt.zeilen.clear()
    assert welt.lauf("pruefen") == 1 and "nicht eingerichtet" in welt.text


# ---------- Adressen und TLS ----------

def test_tls_fehler_ist_ein_fehler(welt):
    welt.umg.abruf.antworten[FESTE[2]] = AbrufFehler("tls", "Zertifikat wird nicht als vertrauenswürdig erkannt")
    assert welt.lauf("pruefen") == 1
    zeile = next(z for z in welt.zeilen if "55445" in z)
    assert zeile.startswith("[FEHLER]") and "TLS" in zeile


def test_nicht_erreichbar_ist_ein_fehler_und_die_uhr_bleibt_ungeprueft(welt):
    welt.umg.abruf.standard = AbrufFehler("verbindung", "keine Verbindung")
    assert welt.lauf("pruefen") == 1
    assert any(z.startswith("[WARNUNG]") and "Uhr" in z for z in welt.zeilen)


@pytest.mark.parametrize("status,stufe", [(200, "ok"), (401, "ok"), (404, "ok"), (503, "WARNUNG")])
def test_jede_antwort_zeigt_erreichbarkeit_nur_serverfehler_warnen(welt, status, stufe):
    welt.umg.abruf.antworten[FESTE[3]] = Abruf(status, _datum())
    assert welt.lauf("pruefen") == 0
    assert next(z for z in welt.zeilen if "55447" in z).startswith(f"[{stufe}]")


def test_fehlende_ca_datei_verhindert_die_adresspruefung(welt):
    welt.ca.unlink()
    assert welt.lauf("pruefen") == 1 and "CA-Datei" in welt.text
    assert welt.umg.abruf.aufrufe == []


# ---------- Uhr ----------

@pytest.mark.parametrize("delta,rc", [(0, 0), (299, 0), (-299, 0), (300, 0), (301, 1), (-301, 1), (3600, 1), (-86400, 1)])
def test_uhr_hoechstens_fuenf_minuten_abweichung(welt, delta, rc):
    welt.umg.abruf.standard = Abruf(200, _datum(delta))
    assert welt.lauf("pruefen") == rc
    if rc:
        assert any(z.startswith("[FEHLER]") and "Uhr" in z for z in welt.zeilen)


def test_uhr_ohne_date_kopf_ist_nur_eine_warnung(welt):
    welt.umg.abruf.standard = Abruf(200, None)
    assert welt.lauf("pruefen") == 0
    assert any(z.startswith("[WARNUNG]") and "Uhr" in z for z in welt.zeilen)


def test_uhr_mit_unlesbarem_date_kopf_ist_nur_eine_warnung(welt):
    welt.umg.abruf.standard = Abruf(200, "gestern gegen Abend")
    assert welt.lauf("pruefen") == 0 and any(z.startswith("[WARNUNG]") and "Uhr" in z for z in welt.zeilen)


# ---------- Netztrennung (Gegenprobe: verbotene Ziele) ----------

def _netz(welt) -> list[str]:
    return [z for z in welt.zeilen if z.split("] ", 1)[-1].startswith("Netztrennung:")]


def test_netzprobe_alle_gesperrt_ist_in_ordnung_und_trifft_genau_die_festen_ziele(welt):
    import wamo_labor_platz_adressen as adr
    assert welt.lauf("pruefen") == 0
    zeilen = _netz(welt)
    assert len(zeilen) == len(adr.VERBOTENE_ZIELE) and all(z.startswith("[ok]") and "gesperrt (keine Antwort)" in z for z in zeilen)
    assert sorted((h, p) for h, p, _ in welt.tcp.aufrufe) == sorted((z.host, z.port) for z in adr.VERBOTENE_ZIELE)
    assert {f for _, _, f in welt.tcp.aufrufe} == {1.5}
    assert any("192.168.178.136:55446 (Sokrates-2, Remote-Desktop-Gateway) gesperrt" in z for z in zeilen)


def test_offenes_verbotenes_ziel_ist_eine_warnung_mit_dem_satz(welt):
    welt.tcp.ergebnisse[("192.168.178.75", 4000)] = "offen"
    assert welt.lauf("pruefen") == 0  # Warnung, kein Fehler: Ausgang wie bei allen Warnungen von `pruefen`
    offen = [z for z in _netz(welt) if "OFFEN" in z]
    assert len(offen) == 1 and offen[0].startswith("[WARNUNG] Netztrennung: 192.168.178.75:4000 (Sokrates-1, zentrales LiteLLM-Gateway) ist OFFEN")
    assert "Die Netztrennung fehlt noch" in offen[0] and "192.168.178.136 auf TCP 55443, 55444, 55445 und 55447 und den UDP-Bereich" in offen[0]
    assert sum(z.startswith("[ok]") for z in _netz(welt)) == len(_netz(welt)) - 1
    assert welt.zeilen[-1].endswith("1 Warnung(en), 0 Fehler.")


def test_mehrere_offene_ziele_je_eine_warnung_und_daneben_ein_fehler_ergibt_ausgang_1(welt):
    welt.tcp.standard = "offen"
    welt.chrome.unlink()
    assert welt.lauf("pruefen") == 1
    assert all(z.startswith("[WARNUNG]") and "Die Netztrennung fehlt noch" in z for z in _netz(welt))


@pytest.mark.parametrize("ergebnis,text", [("frist", "keine Antwort"), ("abgewiesen", "abgewiesen"), ("unerreichbar", "nicht erreichbar")])
def test_jede_art_der_sperre_ist_in_ordnung(welt, ergebnis, text):
    welt.tcp.standard = ergebnis
    assert welt.lauf("pruefen") == 0
    assert all(z.startswith("[ok]") and z.endswith(f"gesperrt ({text})") for z in _netz(welt))


def test_fehler_beim_verbindungsaufbau_ist_nicht_gesperrt_sondern_nicht_pruefbar(welt):
    welt.tcp.ergebnisse[("192.168.178.1", 443)] = "fehler"
    assert welt.lauf("pruefen") == 0
    zeile = next(z for z in _netz(welt) if "192.168.178.1:443" in z)
    assert zeile.startswith("[WARNUNG]") and "nicht prüfbar" in zeile and "gesperrt" not in zeile


def test_netzprobe_laeuft_gleichzeitig(welt):
    import wamo_labor_platz_adressen as adr
    welt.tcp.dauer_s = 0.3  # nacheinander wären es 12 mal 0,3 Sekunden
    beginn = time.monotonic()
    assert welt.lauf("pruefen") == 0
    assert time.monotonic() - beginn < 0.3 * len(adr.VERBOTENE_ZIELE) / 2
    assert len(welt.tcp.aufrufe) == len(adr.VERBOTENE_ZIELE)


def test_gesamtdauer_ist_begrenzt_und_ein_haengendes_ziel_gilt_nicht_als_offen(welt):
    welt.umg.netz_gesamt_s = 0.3
    welt.tcp.haengen.add(("192.168.178.136", 22))
    welt.tcp.ergebnisse[("192.168.178.136", 22)] = "offen"  # käme erst nach der Gesamtfrist und zählt nicht mehr
    beginn = time.monotonic()
    try:
        assert welt.lauf("pruefen") == 0
        assert time.monotonic() - beginn < 2.0
    finally:
        welt.tcp.freigabe.set()
    zeile = next(z for z in _netz(welt) if "192.168.178.136:22" in z)
    assert zeile.startswith("[ok]") and "keine Antwort innerhalb der Gesamtfrist" in zeile


def test_ohne_netzprobe_kein_verbindungsversuch_und_ein_hinweis(welt):
    assert welt.lauf("pruefen", "--ohne-netzprobe") == 0
    assert welt.tcp.aufrufe == []
    assert _netz(welt) == ["[WARNUNG] Netztrennung: nicht geprüft (Schalter --ohne-netzprobe)"]


def test_netzprobe_laeuft_auch_ohne_platzdatei(welt):
    welt.platz_datei.unlink()
    assert welt.lauf("pruefen") == 1
    assert len(_netz(welt)) == len(welt.tcp.aufrufe) > 0


def test_fehler_der_attrappe_im_faden_kommt_beim_aufrufer_an(welt):
    welt.tcp.ergebnisse[("192.168.178.64", 3389)] = AssertionError("Falle im Faden")
    with pytest.raises(AssertionError, match="Falle im Faden"):
        welt.lauf("pruefen")


def test_verbotene_ziele_sind_fest_eindeutig_im_buero_und_nie_ein_erlaubter_port():
    import wamo_labor_platz_adressen as adr
    paare = [(z.host, z.port) for z in adr.VERBOTENE_ZIELE]
    assert len(paare) == len(set(paare)) and len({z.name for z in adr.VERBOTENE_ZIELE}) == len(paare)
    buero = ipaddress.ip_network("192.168.178.0/24")
    assert all(ipaddress.ip_address(h) in buero and 0 < p < 65536 for h, p in paare)
    assert not any(h == adr.HOST and p in adr.PORTS for h, p in paare)
    for pflicht in [(adr.HOST, p) for p in (22, 55321, 55322, 56543, 55446)] + [("192.168.178.75", 4000), ("192.168.178.1", 80),
                                                                                ("192.168.178.1", 443)]:
        assert pflicht in paare, pflicht


# ---------- Mikrofon ----------

def test_bluetooth_freisprechgeraet_wird_gewarnt(welt):
    _mikrofon(welt.reg, "{2}", "Headset", "WH-1000 Hands-Free AG Audio")
    assert welt.lauf("pruefen") == 0
    zeile = next(z for z in welt.zeilen if "Hands-Free" in z and z.startswith("[WARNUNG]"))
    assert "Bluetooth" in zeile and "Freisprech" in zeile and "USB" in zeile and "Klinke" in zeile


@pytest.mark.parametrize("schnittstelle", ["Kopfhörer BTHHFEnum", "Bluetooth Headset X", "Freisprechtelefon Y", "Handsfree Z"])
def test_bluetooth_erkennung_ueber_mehrere_namen(welt, schnittstelle):
    _mikrofon(welt.reg, "{2}", "Headset", schnittstelle)
    welt.lauf("pruefen")
    assert any(z.startswith("[WARNUNG]") and "Bluetooth" in z for z in welt.zeilen)


def test_deaktiviertes_oder_getrenntes_bluetooth_geraet_wird_ignoriert(welt):
    _mikrofon(welt.reg, "{2}", "Headset", "WH-1000 Hands-Free AG Audio", zustand=2)
    _mikrofon(welt.reg, "{3}", "Headset", "WH-2000 Hands-Free AG Audio", zustand=8)
    welt.lauf("pruefen")
    assert not any("Bluetooth" in z for z in welt.zeilen) and "Hands-Free" not in welt.text


def test_nur_usb_mikrofon_ist_in_ordnung_und_wird_genannt(welt):
    welt.lauf("pruefen")
    assert any(z.startswith("[ok]") and "Mikrofon (USB-Headset Modell A)" in z for z in welt.zeilen)


def test_kein_aktives_mikrofon_ist_eine_warnung(tmp_path):
    w = tw.Welt(tmp_path / "w")
    w.lauf("einrichten", "--kiosk-konto", "--platz", "3")
    w.umg.abruf = at.AbrufAttrappe(Abruf(200, _datum()))
    w.zeilen.clear()
    assert w.lauf("pruefen") == 0
    assert any(z.startswith("[WARNUNG]") and "Mikrofon" in z and "kein" in z.lower() for z in w.zeilen)


# ---------- Zertifikat, Richtlinien, Chrome ----------

def test_fehlendes_zertifikat_richtlinien_und_chrome_sind_fehler(welt):
    welt.zert.speicher.clear()
    welt.reg.setzen("HKCU", "Software\\Policies\\Google\\Chrome", "TranslateEnabled", "dword", 1)
    welt.chrome.unlink()
    assert welt.lauf("pruefen") == 1
    for thema in ("Zertifikat", "Richtlinien", "Chrome"):
        assert any(z.startswith("[FEHLER]") and thema in z for z in welt.zeilen), thema
    assert any("TranslateEnabled" in z for z in welt.zeilen)


def test_warten_wartet_bei_pruefen_immer_auf_enter(welt):
    welt.lauf("pruefen", "--warten")
    assert welt.tasten == [1]
    welt.lauf("pruefen")
    assert welt.tasten == [1]


def test_starten_mit_warten_wartet_nur_bei_fehlern(welt):
    welt.lauf("starten", "--warten", "--ohne-board")
    assert welt.tasten == []
    welt.chrome.unlink()
    assert welt.lauf("starten", "--warten") == 1 and welt.tasten == [1]
