"""Die PC-Freigabe bleibt verhaltensgleich (Testlabor, docs/testlabor-wamo.md 3.2, "Trennung von der PC-Freigabe").

Der Beweis hat drei Teile: Dateien, die sich nicht ändern dürfen, per Hash (pc_freigaben.py, pc_host.py), die gemeinsame Datei bot.py nur für die
Funktion darf_pc_freigeben per Hash ihres Quelltexts (bot.py ändert sich sonst durch Einhängepunkte), und ein Verhaltenstest. Ändert jemand mit
Absicht eine dieser Stellen, ändert er den Hash hier im selben Commit und sagt im Review, warum.

Zeilenenden werden vor dem Hash vereinheitlicht (Windows und Linux).
"""

from __future__ import annotations

import ast
import hashlib
import os
import pathlib
from dataclasses import dataclass
from unittest import mock

import pytest

from auth_gate import Identity

HIER = pathlib.Path(__file__).parent
# 15.11.2026: pc_freigaben.py kennt die Freigabeart mail (Protokoll ohne Inhalte, Warnung, nach_ergebnis; outlook_werkzeuge.py)
# 15.11.2026: und teams (Protokoll ohne Adressen und Text wie bei mail, Satz "das Öffnen des Teams-Chats"; teams_werkzeuge.py)
# 15.11.2026 (Paket P4, PC-Steuerung für Mitglieder, docs/ausrollen-neue-nutzer.md 4.5): pc_freigaben.py kennt Freigaben des Kerns (Aktion
# aendern, kern_vormerken, nur Mitglieder nach Fremdinhalt); pc_host.py hat LLM_TOOLS_MITGLIED und filtert den Host-Client nach der Stufe;
# darf_pc_freigeben fragt rechte.pc_stufe statt is_admin. Laborprofile bekommen weiter nie eine Stufe (Tests unten).
# 16.11.2026 (Entscheidung Niko zu N10, Mitglieder bekommen für ihren eigenen Laptop dieselben PC-Werkzeuge wie Admins): pc_host.py hat
# keine eigene Liste LLM_TOOLS_MITGLIED mehr (werkzeuge_fuer gibt beiden Stufen LLM_TOOLS); pc_freigaben.py führt Freigaben des Kerns für
# Werkzeuge, die der Kern selbst ausführt (auf_bildschirm_klicken, canvas_exportieren), über kern_ausfuehrer aus und warnt bei Mitgliedern
# nach Fremdinhalt auf jeder Karte (fremd_warnung). darf_pc_freigeben bleibt unverändert, Laborprofile bekommen weiter nie eine Stufe, kein
# Bildschirm, kein Live-Bild und kein Office (Tests unten).
# 16.11.2026 (Entscheidungen Niko zu HIGH 2 und Befund 5 aus PR 165): pc_freigaben.py kennt die Karte des Kerns mit der Aktion
# bildschirm (Einwilligung der Mitglieder für das Bildschirmbild, KERN_AKTIONEN); Admins und Laborprofile unverändert.
HASH_PC_FREIGABEN = "ee5bae8fd313d4af3be4b7075419b881d7c69742d297e6815fd1ca33c821d1e5"
HASH_PC_HOST = "bfdab8be2dd3e875b575291d668726dd513941f852dd4d94dc3a468ede9be6f7"
HASH_DARF_PC_FREIGEBEN = "f2e90ef81b444e26b95408748e0158c298188332e1df46496dee83024b00252a"

DUMMY_ENV = {"SONIOX_API_KEY": "dummy-soniox", "ANTHROPIC_API_KEY": "dummy-anthropic", "WAMO_DATABASE_URL": "",
             "WAMO_DB_SCHEMA": "wamo_test", "WAMO_PC_HOST": "off"}


def _sha(daten: bytes) -> str:
    return hashlib.sha256(daten.replace(b"\r\n", b"\n")).hexdigest()


@pytest.fixture(scope="module")
def bot():
    with mock.patch.dict(os.environ, DUMMY_ENV):
        import bot as modul
    return modul


@dataclass(frozen=True)
class LaborIdentity(Identity):
    """Stand-in für eine Laboridentität: dieselbe Identität mit der Art des Laborprofils (die Schnittstelle getattr(identity, "labor_art"))."""

    labor_art: str | None = "platz"


def test_pc_freigaben_und_pc_host_sind_unveraendert():
    assert _sha((HIER / "pc_freigaben.py").read_bytes()) == HASH_PC_FREIGABEN
    assert _sha((HIER / "pc_host.py").read_bytes()) == HASH_PC_HOST


def test_darf_pc_freigeben_ist_im_quelltext_unveraendert():
    text = (HIER / "bot.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
    knoten = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "darf_pc_freigeben"]
    assert len(knoten) == 1
    assert hashlib.sha256(ast.get_source_segment(text, knoten[0]).encode("utf-8")).hexdigest() == HASH_DARF_PC_FREIGEBEN


ADMIN = Identity("11111111-1111-4111-8111-111111111111", "Niko", "admin", "du")
MITGLIED = Identity("11111111-1111-4111-8111-111111111111", "Niko", "mitglied", "du")


@pytest.fixture
def ohne_freischaltung(monkeypatch):
    monkeypatch.delenv("WAMO_PC_MITGLIEDER_PROFILE", raising=False)
    return monkeypatch


def test_darf_pc_freigeben_verhalten(bot, ohne_freischaltung):
    assert bot.darf_pc_freigeben(ADMIN, True, True, True) is True  # Admin mit PC-Werkzeugen, Steuerung an, Sperre gehalten
    for pc, steuerung, sperre in ((False, True, True), (True, False, True), (True, True, False), (False, False, False)):
        assert not bot.darf_pc_freigeben(ADMIN, pc, steuerung, sperre)
    assert not bot.darf_pc_freigeben(MITGLIED, True, True, True)  # Mitglied ohne Freischaltung (Standard leer)
    ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED.user_id)
    assert bot.darf_pc_freigeben(MITGLIED, True, True, True) is True  # freigeschaltet: Aktionen am eigenen Laptop
    assert not bot.darf_pc_freigeben(MITGLIED, True, False, True)


@pytest.mark.parametrize("art", ["platz", "schaufenster", "unbekannt", ""])
@pytest.mark.parametrize("freigeschaltet", [False, True])
def test_keine_laboridentitaet_darf_pc_freigeben(bot, ohne_freischaltung, art, freigeschaltet):
    # Laborprofile sind immer Mitglieder (Migration 0018): auch bei vollem Schalterstand und mit der eigenen user_id in der Freischaltung
    # der Mitglieder (WAMO_PC_MITGLIEDER_PROFILE, Paket P4) gibt es keine PC-Freigabe
    if freigeschaltet:
        ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED.user_id)
    labor = LaborIdentity(MITGLIED.user_id, "Gast", "mitglied", "du", labor_art=art)
    assert not bot.darf_pc_freigeben(labor, True, True, True)


@pytest.mark.parametrize("art", ["platz", "schaufenster"])
async def test_laborprofil_mit_freischaltung_bekommt_weder_stufe_noch_zugang_noch_nachholen(ohne_freischaltung, art):
    """Paket P4: Die Freischaltung der Mitglieder öffnet für Laborprofile nichts, auch wenn ihre user_id in der Liste steht. Das Register
    wird dabei gar nicht erst gefragt."""
    import pc_geraet
    import pc_nachverbinden
    import rechte

    ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED.user_id)
    ohne_freischaltung.setenv("WAMO_BETRIEB", "buero")
    ohne_freischaltung.setenv("WAMO_PC_REGISTER", "an")
    ohne_freischaltung.setenv("WAMO_PC_HOST", "on")
    labor = LaborIdentity(MITGLIED.user_id, "Gast", "mitglied", "du", labor_art=art)

    class Register:
        abfragen = 0

        async def aktives_geraet(self, user_id):
            Register.abfragen += 1
            return object()

    assert rechte.pc_stufe(labor) is None
    assert await pc_geraet.pc_zugang_fuer(labor, Register()) is None
    assert await pc_nachverbinden.nachholen_moeglich(labor, zugang_da=False, register=Register()) is False
    assert Register.abfragen == 0


def test_laborprompt_und_laborwerkzeuge_kennen_keine_pc_werkzeuge_der_mitglieder():
    """Die Laborsitzung baut ihren eigenen Prompt und ihre Erlaubnisliste (labor.WERKZEUGE_BASIS): kein PC-Werkzeug darin, weder des Hosts
    noch des Kerns (Bildschirm, Office, Outlook, Teams, OneNote)."""
    import labor
    import pc_host
    import pc_mitglied

    assert not set(pc_host.LLM_TOOLS) & set(labor.WERKZEUGE_BASIS)
    assert not pc_mitglied.WERKZEUGE_MITGLIED & set(labor.WERKZEUGE_BASIS)


@pytest.mark.parametrize("art", ["platz", "schaufenster", "unbekannt"])
async def test_laborprofil_mit_freischaltung_bekommt_weder_office_noch_live_bild(ohne_freischaltung, art):
    """16.11.2026: Mitglieder mit Freischaltung bekommen Bildschirm, Live-Bild und Office. Ein Laborprofil bekommt nichts davon, auch mit
    seiner user_id in WAMO_PC_MITGLIEDER_PROFILE und mit allen Teilen von WAMO_OFFICE."""
    from types import SimpleNamespace

    import bild_fern
    import office_werkzeuge
    import onenote_werkzeuge
    import outlook_werkzeuge
    import teams_werkzeuge

    ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", MITGLIED.user_id)
    ohne_freischaltung.setenv("WAMO_OFFICE", "dateien,outlook,teams,onenote")
    labor = LaborIdentity(MITGLIED.user_id, "Gast", "mitglied", "du", labor_art=art)
    for modul in (office_werkzeuge, onenote_werkzeuge, outlook_werkzeuge, teams_werkzeuge):
        assert not modul.fuer_sitzung(labor), modul.__name__
    assert office_werkzeuge.fuer_sitzung(MITGLIED)  # zum Vergleich: dasselbe Profil ohne Laborart bekommt es

    class Tor:
        async def authorize(self, _token):
            return SimpleNamespace(identity=labor, status=200, reason="", erstanmeldung="erledigt")

    pruefen = bild_fern.pruefer(MITGLIED.user_id, lambda: Tor())
    assert await pruefen("a" * 10 + "." + "b" * 10 + "." + "c" * 10) == bild_fern.TEXT_FALSCH


def test_ein_admin_ohne_labor_hat_kein_labor_werkzeug_und_keine_labor_freigabe():
    import labor_werkzeuge

    assert labor_werkzeuge.laborart(ADMIN) is None and labor_werkzeuge.laborart(MITGLIED) is None
    assert labor_werkzeuge.laborart(LaborIdentity(ADMIN.user_id, "Niko", "admin", "du", labor_art=None)) is None
    assert labor_werkzeuge.laborart(LaborIdentity(MITGLIED.user_id, "Gast", "mitglied", "du", labor_art="platz")) == "platz"
