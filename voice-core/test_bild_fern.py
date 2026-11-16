"""Tests der Prüfung für die Fernanfrage des Live-Bilds (bild_fern.py): Token passt zur Sitzung, Stufe der PC-Steuerung (Admin oder
freigeschaltetes Mitglied, nie ein Laborprofil), frischer Code."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest

import bild_fern

USER = "11111111-2222-3333-4444-555555555555"


def token(aal="aal2", alter=30.0, methode="totp"):
    claims = {"sub": USER, "aal": aal, "amr": [{"method": methode, "timestamp": time.time() - alter}]}
    return jwt.encode(claims, "x" * 32, algorithm="HS256")


class Tor:
    def __init__(self, identity):
        self.identity = identity
        self.gefragt = []

    async def authorize(self, tok):
        self.gefragt.append(tok)
        # erstanmeldung: ohne Stand gilt eine Entscheidung nie als frei (auth_gate.erstanmeldung_sperre)
        return SimpleNamespace(identity=self.identity, status=401 if self.identity is None else 200, reason="x",
                               erstanmeldung="erledigt")


def ich(user=USER, admin=True, rolle=None, labor_art=None):
    return SimpleNamespace(user_id=user, is_admin=admin, rolle=rolle or ("admin" if admin else "mitglied"), labor_art=labor_art)


@pytest.fixture(autouse=True)
def ohne_freischaltung(monkeypatch):
    monkeypatch.delenv("WAMO_PC_MITGLIEDER_PROFILE", raising=False)
    return monkeypatch


async def pruefen(tok, tor):
    return await bild_fern.pruefer(USER, lambda: tor)(tok)


async def test_frischer_code_des_besitzers_passt():
    tor = Tor(ich())
    t = token()
    assert await pruefen(t, tor) is None
    assert tor.gefragt == [t]


async def test_zu_alter_code_ohne_aal2_oder_ohne_totp_wird_abgelehnt():
    assert await pruefen(token(alter=500), Tor(ich())) == bild_fern.TEXT_ALT
    assert await pruefen(token(aal="aal1"), Tor(ich())) == bild_fern.TEXT_ALT
    assert await pruefen(token(methode="password"), Tor(ich())) == bild_fern.TEXT_ALT


async def test_fremdes_token_nicht_admin_oder_abgelehnt():
    assert await pruefen(token(), Tor(ich(user="99999999-2222-3333-4444-555555555555"))) == bild_fern.TEXT_FALSCH
    assert await pruefen(token(), Tor(ich(admin=False))) == bild_fern.TEXT_FALSCH
    assert await pruefen(token(), Tor(None)) == bild_fern.TEXT_FALSCH


async def test_freigeschaltetes_mitglied_darf_den_eigenen_laptop_anfordern(ohne_freischaltung):
    """Entscheidung Niko vom 16.11.2026: das Live-Bild auch für freigeschaltete Mitglieder, am eigenen Laptop, mit Einwilligung dort."""
    assert await pruefen(token(), Tor(ich(admin=False))) == bild_fern.TEXT_FALSCH  # ohne Freischaltung nicht
    ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", USER)
    assert await pruefen(token(), Tor(ich(admin=False))) is None
    assert await pruefen(token(), Tor(ich(admin=False, labor_art="platz"))) == bild_fern.TEXT_FALSCH  # ein Laborprofil nie
    assert await pruefen(token(alter=500), Tor(ich(admin=False))) == bild_fern.TEXT_ALT  # frischer Code wie bei Admins
    anderes = "99999999-2222-3333-4444-555555555555"
    ohne_freischaltung.setenv("WAMO_PC_MITGLIEDER_PROFILE", f"{USER},{anderes}")
    assert await pruefen(token(), Tor(ich(user=anderes, admin=False))) == bild_fern.TEXT_FALSCH  # nie ein fremdes Token


async def test_ungueltige_eingaben_und_fehlendes_tor():
    tor = Tor(ich())
    for roh in (None, 5, "", "kurz", "x" * 20, "a.b", "a." * 9000):
        assert await pruefen(roh, tor) == bild_fern.TEXT_CODE
    assert tor.gefragt == [], "ungültige Eingaben erreichen die Zugangskontrolle nie"
    assert "nicht erreichbar" in await bild_fern.pruefer(USER, lambda: None)(token())
