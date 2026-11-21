"""Der Dienst: Anmeldung je Anfrage, Zugriff auf Datenbank und Dateien, Schreiben mit Prüfspur in einer Transaktion.

Reihenfolge der Anmeldung (jede Stufe lehnt mit festem Code ab, nie mit einem internen Namen):
  Token (401) -> Drosselung je Person (429) -> zweiter Faktor aal2 (403 aal2_fehlt) -> Profil lesen (403 nicht_berechtigt, bei einem
  Laborprofil 403 labor_profil, Prüfung VOR aktiv, denn Laborprofile sind ohne Freischaltung inaktiv) -> Rolle admin (403) ->
  Erlaubnisliste (403). Die Datenbank wird bei jeder Anfrage neu befragt, es gibt keinen Zwischenspeicher für das Profil.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from .anmeldung import AAL2_MAX_ALTER_S, Erlaubnisliste, TokenPruefer, Zugang, aal2_alter_s, konto_von
from .daten import Datenbank, Verbindung
from .drossel import Drossel
from .fehler import WerkstattFehler
from .konfig import Konfig

RISIKO_AENDERN, RISIKO_KRITISCH = "change", "critical"


def bearer(request: Request) -> str | None:
    kopf = request.headers.get("authorization", "")
    teile = kopf.split(" ")
    return teile[1] if len(teile) == 2 and teile[0].lower() == "bearer" and teile[1] else None


@dataclass
class Buchung:
    """Was die Prüfspur (Tabelle actions) zu einem Schreibvorgang festhält: nur Kennungen und Zahlen, nie Texte."""

    params: dict[str, Any] = field(default_factory=dict)
    ergebnis: dict[str, Any] = field(default_factory=lambda: {"ok": True})


class Dienst:
    def __init__(self, konfig: Konfig, db: Datenbank, pruefer: TokenPruefer, *, uhr: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic):
        self.konfig, self.db, self.pruefer, self.uhr = konfig, db, pruefer, uhr
        self.drossel = Drossel(mono=mono)
        self.erlaubnis = Erlaubnisliste(konfig.admins_datei)

    def jetzt(self) -> datetime:
        return datetime.fromtimestamp(self.uhr(), tz=timezone.utc)

    async def anmelden(self, request: Request) -> Zugang:
        claims = await self.pruefer.pruefen(bearer(request))
        user_id = konto_von(claims)
        self.drossel.pruefen(user_id)
        if claims.get("aal") != "aal2":
            raise WerkstattFehler("aal2_fehlt")
        profil = await self.db.profil(user_id)  # DatenbankFehler wird in app.py zu 503
        if profil is None:
            raise WerkstattFehler("nicht_berechtigt")
        if profil.labor_art is not None:  # jeder Wert heißt Laborprofil, auch ein unbekannter
            raise WerkstattFehler("labor_profil")
        if not profil.aktiv or profil.rolle != "admin" or not self.erlaubnis.enthaelt(user_id):
            raise WerkstattFehler("nicht_berechtigt")
        zugang = Zugang(user_id, "admin", aal2_alter_s(claims, self.uhr()))
        request.state.admin = zugang.kurz  # für die Zeile im Journal
        return zugang

    @staticmethod
    def frisch(zugang: Zugang) -> None:
        """Verlangt einen Code des zweiten Faktors, der höchstens 60 Sekunden alt ist."""
        if zugang.aal2_alter_s is None:
            raise WerkstattFehler("aal2_fehlt")
        if zugang.aal2_alter_s > AAL2_MAX_ALTER_S:
            raise WerkstattFehler("aal2_alt")

    @contextlib.asynccontextmanager
    async def schreiben(self, zugang: Zugang, tool: str, *, risiko: str = RISIKO_AENDERN) -> AsyncIterator[tuple[Verbindung, Buchung]]:
        """Eine Transaktion mit der Prüfspur am Ende: Änderung und Zeile in actions gelten zusammen oder gar nicht. Wirft der Block eine
        Ausnahme, wird nichts geschrieben (auch keine Zeile in actions)."""
        buchung = Buchung()
        async with self.db.transaktion() as tx:
            yield tx, buchung
            await tx.aktion_buchen(zugang.user_id, tool, risiko, buchung.params, buchung.ergebnis)


def dienst_von(request: Request) -> Dienst:
    return request.app.state.dienst


async def zugang_pruefen(request: Request) -> Zugang:
    return await dienst_von(request).anmelden(request)


async def zugang_frisch(request: Request) -> Zugang:
    zugang = await dienst_von(request).anmelden(request)
    Dienst.frisch(zugang)
    return zugang
