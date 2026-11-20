"""Schnittstelle zur Datenbank (Protocol) und ihre Fehler.

Die Logik der Werkstatt kennt nur diese Schnittstelle. Zwei Umsetzungen: pg.py (asyncpg, Rolle wamo_werkstatt) und die Attrappe
der Tests (tests/attrappe.py, im Speicher). So lässt sich alles ohne Datenbank prüfen, auch das Verhalten bei Fehlern und der Ablauf
einer Transaktion.

Die Datenbank liefert Werte in ihren eigenen Typen (date, time, datetime, int, str, bool). Die Umwandlung in JSON-Werte und die
Beschränkung auf erlaubte Felder macht allein die Logik der Werkstatt (ausgabe.py, lesen.py), nie die Datenbank.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol


class DatenbankFehler(Exception):
    """Die Datenbank ist nicht erreichbar, eine Zeitgrenze riss oder ein Recht fehlt. Nur der Typ des Auslösers steht in der Meldung."""


class KonfliktFehler(Exception):
    """Die Datenbank lehnt ab, weil etwas schon da ist oder fehlt (eindeutiger Schlüssel, Fremdschlüssel)."""


class PruefFehler(Exception):
    """Eine Regel der Datenbank (Prüfung, Pflichtfeld, Wertebereich) lehnt die Angabe ab."""


@dataclass(frozen=True)
class Profil:
    user_id: str
    rolle: str | None
    aktiv: bool
    labor_art: str | None


@dataclass(frozen=True)
class FreigabeKarte:
    """Eine Freigabekarte (Tabelle werkstatt_karten). abgelaufen entscheidet die Datenbank mit ihrer Uhr."""

    id: str
    admin: str
    aktion: str
    ziel: Mapping[str, Any]
    gilt_bis: datetime
    abgelaufen: bool
    ausgefuehrt: bool


class Verbindung(Protocol):
    """Alle Abfragen und Änderungen. Innerhalb von Datenbank.transaktion() gehören sie zu einer Transaktion."""

    # Anmeldung
    async def profil(self, user_id: str) -> Profil | None: ...

    # Kennzahlen (Rohzeilen der Lesefunktionen; lesen.py filtert auf die erlaubten Felder)
    async def sitzungen(self, tage: int) -> list[Mapping[str, Any]]: ...
    async def latenz(self, tage: int) -> list[Mapping[str, Any]]: ...
    async def aktionen(self, tage: int) -> list[Mapping[str, Any]]: ...
    async def labor_stand(self) -> list[Mapping[str, Any]]: ...

    # Termine, Plätze, Checkliste
    async def termine(self) -> list[dict[str, Any]]: ...
    async def termin(self, termin_id: str) -> dict[str, Any] | None: ...
    async def termin_anlegen(self, daten: Mapping[str, Any], admin: str) -> dict[str, Any]: ...
    async def termin_aendern(self, termin_id: str, daten: Mapping[str, Any]) -> dict[str, Any] | None: ...
    async def termin_loeschen(self, termin_id: str) -> bool: ...
    async def plaetze(self, termin_id: str) -> list[dict[str, Any]]: ...
    async def plaetze_setzen(self, termin_id: str, plaetze: list[dict[str, Any]]) -> None: ...
    async def checkliste(self, termin_id: str) -> list[dict[str, Any]]: ...
    async def checkliste_anlegen(self, termin_id: str, daten: Mapping[str, Any]) -> dict[str, Any]: ...
    async def checkliste_abhaken(self, termin_id: str, nr: int, erledigt: bool, admin: str) -> dict[str, Any] | None: ...

    # Karten, Zuordnung, Versionen
    async def karten(self, *, sperren: bool = False) -> list[dict[str, Any]]: ...
    async def karte(self, karte_id: str) -> dict[str, Any] | None: ...
    async def karte_anlegen(self, karte_id: str, daten: Mapping[str, Any], admin: str) -> dict[str, Any]: ...
    async def karte_aendern(self, karte_id: str, daten: Mapping[str, Any], admin: str) -> dict[str, Any] | None: ...
    async def karte_loeschen(self, karte_id: str) -> bool: ...
    async def zuordnung(self, termin_id: str) -> dict[int, list[str]]: ...
    async def zuordnung_setzen(self, termin_id: str, matrix: dict[int, list[str]]) -> None: ...
    async def versionen(self, grenze: int) -> list[dict[str, Any]]: ...
    async def aktive_version(self) -> int | None: ...

    # Veröffentlichen
    async def freigabekarte_anlegen(self, admin: str, aktion: str, ziel: Mapping[str, Any], gilt_s: int) -> FreigabeKarte: ...
    async def freigabekarte_sperren(self, karte_id: str) -> FreigabeKarte | None: ...
    async def freigabekarte_verbrauchen(self, karte_id: str) -> bool: ...
    async def version_anlegen(self, admin: str, aenderungen: int, zeichen: int, karten: list[dict[str, Any]]) -> int: ...
    async def entwuerfe_veroeffentlichen(self) -> int: ...

    # Prüfspur und Pflege
    async def aktion_buchen(self, user_id: str, tool: str, risiko: str, params: Mapping[str, Any], ergebnis: Mapping[str, Any]) -> None: ...
    async def aufraeumen(self) -> None: ...


class Datenbank(Verbindung, Protocol):
    def transaktion(self) -> AbstractAsyncContextManager[Verbindung]:
        """Alles im Block gehört zu einer Transaktion: ohne Ausnahme gilt es zusammen, mit Ausnahme gilt nichts davon."""
        ...

    async def schliessen(self) -> None: ...


# Werte, die die Datenbank liefert und die Logik umwandelt
Tag = date
Uhrzeit = time
