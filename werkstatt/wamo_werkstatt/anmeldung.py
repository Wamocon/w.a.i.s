"""Anmeldung an der Werkstatt: Token (ES256 über JWKS wie im Kern), zweiter Faktor, Erlaubnisliste.

Der Algorithmus ist fest ES256 und kommt nie aus dem Token (kein "none", kein HS256 mit einem öffentlichen Schlüssel). Der Schlüsselsatz
kommt von GoTrue über HTTPS (Prüfung gegen die WAMO-CA), wird im Speicher gehalten und höchstens alle 30 Sekunden neu geholt, damit ein
Angreifer mit erfundenen Schlüsselkennungen GoTrue nicht fluten kann. Ein Schlüssel, den GoTrue nicht mehr nennt, gilt höchstens eine
Stunde weiter, wenn der Abruf scheitert.

aal2_alter_s zählt ab dem JÜNGSTEN totp-Eintrag in amr (der Moment, in dem der Code eingegeben wurde). Das Gegenstück im Kern
(auth_gate.anmeldezeit) nimmt den frühesten Eintrag, denn dort zählt, wann die Sitzung begann.

Nie in einer Ausgabe oder im Journal: das Token, der Schlüsselsatz oder Teile davon.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import jwt

from . import protokoll
from .fehler import WerkstattFehler

TOKEN_MAX_ZEICHEN = 8192
LEEWAY_S = 30  # Uhren von Laptop und Server dürfen etwas auseinanderlaufen
AAL2_MAX_ALTER_S = 60  # für das Ausführen einer Freigabekarte
AAL2_ZUKUNFT_S = 5
JWKS_MAX_BYTES = 65536
JWKS_TTL_S = 300.0
JWKS_MIN_ABSTAND_S = 30.0
JWKS_ALT_MAX_S = 3600.0
ADMINS_MAX_BYTES = 16384


class QuelleNichtErreichbar(Exception):
    """Der Schlüsselsatz ließ sich nicht holen (Netz, TLS, Zeitüberschreitung)."""


class SchluesselQuelle(Protocol):
    async def schluessel(self, kid: str | None) -> object:
        """Öffentlicher Schlüssel zu dieser Kennung. Wirft KeyError (unbekannt) oder QuelleNichtErreichbar."""


class JwksQuelle:
    """Schlüsselsatz von GoTrue (JWKS), nur P-256-Schlüssel zum Signieren."""

    def __init__(self, url: str, ssl_context: ssl.SSLContext | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
                 mono: Callable[[], float] = time.monotonic):
        self._url, self._ssl, self._transport, self._mono = url, ssl_context, transport, mono
        self._schluessel: dict[str, object] = {}
        self._geholt: float | None = None
        self._versuch: float | None = None
        self._sperre = asyncio.Lock()

    async def _abrufen(self) -> bytes:
        verify: ssl.SSLContext | bool = self._ssl if self._ssl is not None else True
        try:
            async with httpx.AsyncClient(timeout=5, verify=verify, transport=self._transport, follow_redirects=False, trust_env=False) as client:
                antwort = await client.get(self._url, headers={"Accept": "application/json"})
        except (httpx.HTTPError, ssl.SSLError, OSError) as e:
            raise QuelleNichtErreichbar(type(e).__name__) from None
        if antwort.status_code != 200 or len(antwort.content) > JWKS_MAX_BYTES:
            raise QuelleNichtErreichbar("Antwort")
        return antwort.content

    async def _laden(self, jetzt: float) -> None:
        self._versuch = jetzt
        try:
            roh = await self._abrufen()
            neu: dict[str, object] = {}
            for k in json.loads(roh).get("keys", []):
                if (isinstance(k, dict) and k.get("kty") == "EC" and k.get("crv") == "P-256" and isinstance(k.get("kid"), str)
                        and k.get("use", "sig") == "sig"):
                    neu[k["kid"]] = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(k))
        except QuelleNichtErreichbar:
            return  # der alte Satz bleibt
        except (ValueError, jwt.PyJWTError, AttributeError, TypeError):
            return  # kein brauchbarer Satz: der alte bleibt, im Journal steht nur der Hinweis
        if neu:
            self._schluessel, self._geholt = neu, jetzt

    async def schluessel(self, kid: str | None) -> object:
        if not isinstance(kid, str):
            raise KeyError("kid")
        async with self._sperre:
            jetzt = self._mono()
            frisch = self._geholt is not None and jetzt - self._geholt < JWKS_TTL_S
            darf_holen = self._versuch is None or jetzt - self._versuch >= JWKS_MIN_ABSTAND_S
            if not (frisch and kid in self._schluessel) and darf_holen:
                await self._laden(jetzt)
            if kid in self._schluessel and self._geholt is not None and jetzt - self._geholt < JWKS_ALT_MAX_S:
                return self._schluessel[kid]
            if self._geholt is None or jetzt - self._geholt >= JWKS_ALT_MAX_S:
                raise QuelleNichtErreichbar("kein Schlüsselsatz")
        raise KeyError("kid")


class TokenPruefer:
    def __init__(self, quelle: SchluesselQuelle, *, aussteller: str, zielgruppe: str):
        self._quelle, self._aussteller, self._zielgruppe = quelle, aussteller, zielgruppe

    async def pruefen(self, token: str | None) -> dict:
        """Claims eines gültigen Tokens. Wirft nicht_angemeldet (jede Unstimmigkeit) oder nicht_verfuegbar (Anmeldedienst nicht erreichbar)."""
        if not isinstance(token, str) or not 20 <= len(token) <= TOKEN_MAX_ZEICHEN or token.count(".") != 2:
            raise WerkstattFehler("nicht_angemeldet")
        try:
            kopf = jwt.get_unverified_header(token)
            if kopf.get("alg") != "ES256":  # fest, nie aus dem Token übernehmen
                raise WerkstattFehler("nicht_angemeldet")
            schluessel = await self._quelle.schluessel(kopf.get("kid"))
            return jwt.decode(token, schluessel, algorithms=["ES256"], audience=self._zielgruppe, issuer=self._aussteller,
                              leeway=LEEWAY_S, options={"require": ["exp", "sub", "iss", "aud"]})
        except WerkstattFehler:
            raise
        except QuelleNichtErreichbar:
            protokoll.ereignis("anmeldedienst_nicht_erreichbar")
            raise WerkstattFehler("nicht_verfuegbar") from None
        except Exception:  # noqa: BLE001  jede Unstimmigkeit heißt "nicht angemeldet" (fail closed, ohne Text)
            raise WerkstattFehler("nicht_angemeldet") from None


def konto_von(claims: dict) -> str:
    """Kennung des Kontos (sub) als kanonische UUID, sonst 401."""
    sub = claims.get("sub")
    if isinstance(sub, str) and len(sub) == 36:
        try:
            return str(uuid.UUID(sub))
        except ValueError:
            pass
    raise WerkstattFehler("nicht_angemeldet")


def aal2_alter_s(claims: dict, jetzt: float) -> int | None:
    """Sekunden seit dem jüngsten totp-Code. None, wenn es keinen gibt oder sein Zeitstempel in der Zukunft liegt (dann gilt er nicht)."""
    eintraege = claims.get("amr")
    zeiten = []
    for eintrag in eintraege if isinstance(eintraege, list) else []:
        if isinstance(eintrag, dict) and eintrag.get("method") == "totp":
            t = eintrag.get("timestamp")
            if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0:
                zeiten.append(float(t))
    if not zeiten:
        return None
    jung = max(zeiten)
    if jung > jetzt + AAL2_ZUKUNFT_S:
        return None
    return max(0, int(jetzt - jung))


@dataclass(frozen=True)
class Zugang:
    """Ein angemeldeter, berechtigter Admin."""

    user_id: str
    rolle: str
    aal2_alter_s: int | None

    @property
    def kurz(self) -> str:
        """Die ersten acht Zeichen der Kennung, für das Journal."""
        return self.user_id[:8]


class Erlaubnisliste:
    """Die Datei mit den erlaubten Admins (eine UUID je Zeile, # beginnt einen Kommentar). Sie wird bei jeder Änderung neu gelesen,
    ein Eintrag wirkt also ohne Neustart. Ist sie nicht lesbar, ist die Liste leer (niemand kommt hinein) und das Journal sagt es."""

    def __init__(self, pfad: Path):
        self._pfad = pfad
        self._stand: tuple[int, int] | None = None
        self._ids: frozenset[str] = frozenset()
        self._gemeldet = False

    def _lesen(self) -> frozenset[str]:
        try:
            with open(self._pfad, "rb") as f:
                st = os.fstat(f.fileno())
                stand = (st.st_mtime_ns, st.st_size)
                if stand == self._stand:
                    return self._ids
                roh = f.read(ADMINS_MAX_BYTES + 1)
        except OSError:
            self._stand = None
            if not self._gemeldet:
                protokoll.ereignis("erlaubnisliste_nicht_lesbar", stufe=logging.ERROR)
                self._gemeldet = True
            return frozenset()
        self._gemeldet = False
        ids: set[str] = set()
        if len(roh) <= ADMINS_MAX_BYTES:
            for zeile in roh.decode("utf-8", "replace").splitlines():
                kennung = zeile.split("#", 1)[0].strip().lower()
                if len(kennung) == 36:
                    try:
                        ids.add(str(uuid.UUID(kennung)))
                    except ValueError:
                        continue
        self._stand, self._ids = stand, frozenset(ids)
        return self._ids

    def enthaelt(self, user_id: str) -> bool:
        return user_id in self._lesen()
