"""Gemeinsame Bausteine: Schlüsselpaar und Tokens, feste Schlüsselquelle, Attrappe der Datenbank, Anwendung und Client."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from attrappe import AttrappeDB
from wamo_werkstatt.anmeldung import QuelleNichtErreichbar
from wamo_werkstatt.app import create_app
from wamo_werkstatt.daten import Profil
from wamo_werkstatt.konfig import Konfig

ISS = "https://stack.test/auth/v1"
AUD = "authenticated"
HERKUNFT = "https://ui.test:55445"
ADMIN = "11111111-1111-4111-8111-111111111111"
ANDERER_ADMIN = "22222222-2222-4222-8222-222222222222"
MITGLIED = "33333333-3333-4333-8333-333333333333"
LABOR = "44444444-4444-4444-8444-444444444444"
AUSSERHALB = "55555555-5555-4555-8555-555555555555"
OHNE_PROFIL = "66666666-6666-4666-8666-666666666666"

SCHLUESSEL = ec.generate_private_key(ec.SECP256R1())
FREMDER_SCHLUESSEL = ec.generate_private_key(ec.SECP256R1())


class FesteQuelle:
    """Schlüsselsatz ohne Netz: kid k1 gehört zum Schlüssel der Tests."""

    def __init__(self):
        self.ausfall = False

    async def schluessel(self, kid):
        if self.ausfall:
            raise QuelleNichtErreichbar("Attrappe")
        if kid != "k1":
            raise KeyError(kid)
        return SCHLUESSEL.public_key()


def token(sub: str = ADMIN, *, aal: str | None = "aal2", totp_alter: float | None = 5, exp_in: float = 3600, iss: str = ISS, aud: str = AUD,
          schluessel=SCHLUESSEL, kid: str | None = "k1", algorithmus: str = "ES256", extra_amr: list | None = None) -> str:
    jetzt = time.time()
    amr = [{"method": "password", "timestamp": int(jetzt - 600)}] + (extra_amr or [])
    if totp_alter is not None:
        amr.append({"method": "totp", "timestamp": int(jetzt - totp_alter)})
    daten = {"sub": sub, "iss": iss, "aud": aud, "iat": int(jetzt), "exp": int(jetzt + exp_in), "amr": amr}
    if aal is not None:
        daten["aal"] = aal
    return jwt.encode(daten, schluessel, algorithm=algorithmus, headers={"kid": kid} if kid else None)


def kopf(tok: str | None = None) -> dict:
    return {"Authorization": f"Bearer {tok if tok is not None else token()}"}


class Uhr:
    """Monotone Uhr, die der Test vorstellt (für die Drosselung)."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db() -> AttrappeDB:
    d = AttrappeDB()
    d.profile = {
        ADMIN: Profil(ADMIN, "admin", True, None),
        ANDERER_ADMIN: Profil(ANDERER_ADMIN, "admin", True, None),
        AUSSERHALB: Profil(AUSSERHALB, "admin", True, None),
        MITGLIED: Profil(MITGLIED, "mitglied", True, None),
        LABOR: Profil(LABOR, "mitglied", False, "platz"),
    }
    return d


@pytest.fixture
def quelle() -> FesteQuelle:
    return FesteQuelle()


@pytest.fixture
def mono() -> Uhr:
    return Uhr()


@pytest.fixture
def daten_ordner(tmp_path) -> Path:
    ordner = tmp_path / "daten"
    (ordner / "protokolle").mkdir(parents=True)
    return ordner


@pytest.fixture
def konfig(tmp_path, daten_ordner) -> Konfig:
    admins = tmp_path / "admins"
    admins.write_text(f"# erlaubte Admins\n{ADMIN}\n{ANDERER_ADMIN}  # zweite Person\n{MITGLIED}\n{LABOR}\n", encoding="utf-8")
    return Konfig(schema="wamo_dev", supabase_url="https://stack.test", jwks_url="https://stack.test/auth/v1/.well-known/jwks.json", issuer=ISS,
                  audience=AUD, herkunft=HERKUNFT, admins_datei=admins, daten_ordner=daten_ordner)


@pytest.fixture
def app(konfig, db, quelle, mono):
    return create_app(konfig, db, quelle, mono=mono, aufraeumen=False)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c


def neue_id() -> str:
    return str(uuid.uuid4())
