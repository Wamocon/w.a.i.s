"""Rechte für die PC-Steuerung an einer Stelle (rechte.py, Plan docs/ausrollen-neue-nutzer.md 4.5, Befund H1).

Wertetabelle aus Rolle, Freischaltung je Profil (WAMO_PC_MITGLIEDER_PROFILE) und Laborprofil. Laborprofile haben die Rolle mitglied und
bekommen trotzdem nie eine Stufe, auch nicht mit ihrer user_id in der Liste.

Ausführen:  python -m pytest -q test_rechte.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import os
import types
from unittest import mock

import pytest

import rechte
from auth_gate import Identity

ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MITGLIED_ID = "22222222-2222-4222-8222-222222222222"
ANDERES_ID = "33333333-3333-4333-8333-333333333333"


def ident(uid: str, rolle: str, labor_art: str | None = None) -> Identity:
    return Identity(uid, "Erika", rolle, "du", labor_art=labor_art)


@pytest.fixture(autouse=True)
def ohne_freischaltung(monkeypatch):
    monkeypatch.delenv("WAMO_PC_MITGLIEDER_PROFILE", raising=False)
    monkeypatch.delenv("WAMO_PC_MITGLIEDER", raising=False)


@pytest.mark.parametrize("rolle, liste, labor_art, erwartet", [
    ("admin", "", None, "admin"),
    ("admin", MITGLIED_ID, None, "admin"),
    ("mitglied", "", None, None),  # Standard leer heißt aus
    ("mitglied", MITGLIED_ID, None, "mitglied"),
    ("mitglied", ANDERES_ID, None, None),  # nicht in der Liste
    ("mitglied", f"{ANDERES_ID}, {MITGLIED_ID}", None, "mitglied"),
    ("mitglied", MITGLIED_ID.upper(), None, "mitglied"),  # kanonisch verglichen
    ("mitglied", f"{MITGLIED_ID},kein-uuid", None, None),  # ein ungültiger Eintrag macht die ganze Liste ungültig
    ("mitglied", f"{MITGLIED_ID},,", None, None),
    ("mitglied", MITGLIED_ID, "platz", None),  # Laborprofil nie, auch mit Freischaltung
    ("mitglied", MITGLIED_ID, "schaufenster", None),
    ("mitglied", MITGLIED_ID, "unbekannt", None),
    ("admin", MITGLIED_ID, "platz", None),  # ein Laborprofil ist nie Admin
    ("gast", MITGLIED_ID, None, None),  # unbekannte Rolle
    ("", MITGLIED_ID, None, None),
    ("ADMIN", "", None, None),  # Rollen sind klein geschrieben, alles andere ist unbekannt
])
def test_pc_stufe_wertetabelle(monkeypatch, rolle, liste, labor_art, erwartet):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", liste)
    uid = ADMIN_ID if rolle == "admin" else MITGLIED_ID
    assert rechte.pc_stufe(ident(uid, rolle, labor_art)) == erwartet


def test_der_alte_kernweite_schalter_wirkt_nicht_mehr(monkeypatch):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER", "an")
    assert rechte.pc_stufe(ident(MITGLIED_ID, "mitglied")) is None


def test_zu_viele_eintraege_heisst_niemand(monkeypatch):
    viele = [f"{i:08x}-2222-4222-8222-222222222222" for i in range(rechte.MAX_PC_MITGLIEDER + 1)]
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", ",".join(viele))
    assert rechte.pc_mitglieder_profile() == frozenset()
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", ",".join(viele[:rechte.MAX_PC_MITGLIEDER]))
    assert len(rechte.pc_mitglieder_profile()) == rechte.MAX_PC_MITGLIEDER


def test_auch_eine_falsch_gebaute_identitaet_mit_laborart_bekommt_nichts(monkeypatch):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED_ID)
    for rolle in ("admin", "mitglied"):
        falsch = types.SimpleNamespace(user_id=MITGLIED_ID, rolle=rolle, is_admin=True, labor_art="platz")
        assert rechte.pc_stufe(falsch) is None
    ohne_rolle = types.SimpleNamespace(user_id=MITGLIED_ID)
    assert rechte.pc_stufe(ohne_rolle) is None


def test_liste_liest_nur_die_umgebung_des_kerns():
    with mock.patch.dict(os.environ, {"WAMO_PC_MITGLIEDER_PROFILE": f" {MITGLIED_ID} "}):
        assert rechte.pc_mitglieder_profile() == frozenset({MITGLIED_ID})


def test_mit_stufe_dieselben_werkzeuge_wie_ein_admin(monkeypatch):
    """Entscheidung Niko vom 16.11.2026: Mitglieder mit Stufe bekommen für ihren eigenen Laptop dieselben Werkzeuge des Hosts wie Admins
    (pc_host.werkzeuge_fuer); ohne Stufe, auch als Laborprofil, keine."""
    import pc_host

    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED_ID)
    admin = pc_host.werkzeuge_fuer(rechte.pc_stufe(ident(ADMIN_ID, "admin")))
    assert pc_host.werkzeuge_fuer(rechte.pc_stufe(ident(MITGLIED_ID, "mitglied"))) == admin == pc_host.LLM_TOOLS
    assert pc_host.werkzeuge_fuer(rechte.pc_stufe(ident(ANDERES_ID, "mitglied"))) == []
    assert pc_host.werkzeuge_fuer(rechte.pc_stufe(ident(MITGLIED_ID, "mitglied", "platz"))) == []
