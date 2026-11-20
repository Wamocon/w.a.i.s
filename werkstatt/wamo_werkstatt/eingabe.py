"""Eingaben prüfen: Text, Zahlen, Datum, Zeit, Kennungen, JSON-Körper und Abfrageparameter.

Regeln für Text (gleich streng wie die Prüfungen der Datenbank, nur mit einem Satz statt eines Datenbankfehlers):
  * Zeilenumbrüche, Tabulatoren und mehrfache Leerzeichen werden zu einem Leerzeichen, Anfang und Ende werden gekürzt.
  * Danach sind nur Buchstaben, Zeichen mit Akzent, Ziffern, Satzzeichen und Symbole erlaubt (keine Steuer-, Format-, Bidi-,
    Trenn- und privaten Zeichen), sonst 422.
  * Zu lange Felder werden nie gekürzt, sondern abgelehnt.
Fehlersätze nennen das Feld in Worten, nie den Wert.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import date, time
from typing import Any

from fastapi import Request

from .fehler import WerkstattFehler, ungueltig

MAX_KOERPER = 128 * 1024  # Bytes; die größte erlaubte Eingabe (Zuordnung für 16 Plätze) bleibt weit darunter
_ERLAUBTE_KATEGORIEN = frozenset("LMNPS")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZEIT_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$")


def text_lesen(wert: object, feld: str, *, maximum: int, minimum: int = 0, pflicht: bool = False) -> str | None:
    """Ein sauberer Text oder None (leer und nicht Pflicht). Wirft 422 bei falschem Typ, Zeichen oder Länge."""
    if wert is None or wert == "":
        if pflicht:
            raise ungueltig(f"{feld} fehlt.")
        return None
    if not isinstance(wert, str):
        raise ungueltig(f"{feld} muss ein Text sein.")
    if len(wert) > maximum * 4 + 64:  # grob vorab, damit riesige Eingaben nicht erst bereinigt werden
        raise ungueltig(f"{feld} ist zu lang (höchstens {maximum} Zeichen).")
    sauber = " ".join(wert.split())
    if any(c != " " and unicodedata.category(c)[0] not in _ERLAUBTE_KATEGORIEN for c in sauber):
        raise ungueltig(f"{feld} enthält Zeichen, die nicht erlaubt sind.")
    if not sauber:
        if pflicht:
            raise ungueltig(f"{feld} fehlt.")
        return None
    if len(sauber) > maximum:
        raise ungueltig(f"{feld} ist zu lang (höchstens {maximum} Zeichen).")
    if len(sauber) < minimum:
        raise ungueltig(f"{feld} ist zu kurz (mindestens {minimum} Zeichen).")
    return sauber


def ganzzahl_lesen(wert: object, feld: str, *, minimum: int, maximum: int) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int):
        raise ungueltig(f"{feld} muss eine ganze Zahl sein.")
    if not minimum <= wert <= maximum:
        raise ungueltig(f"{feld} muss zwischen {minimum} und {maximum} liegen.")
    return wert


def datum_lesen(wert: object, feld: str, *, pflicht: bool = True) -> date | None:
    """JJJJ-MM-TT, sonst 422."""
    if wert is None or wert == "":
        if pflicht:
            raise ungueltig(f"{feld} fehlt.")
        return None
    if not isinstance(wert, str) or not _DATUM_RE.fullmatch(wert):
        raise ungueltig(f"{feld} muss ein Datum der Form JJJJ-MM-TT sein.")
    try:
        return date.fromisoformat(wert)
    except ValueError:
        raise ungueltig(f"{feld} ist kein gültiges Datum.") from None


def zeit_lesen(wert: object, feld: str) -> time | None:
    """HH:MM (auch HH:MM:SS), leer ergibt None."""
    if wert is None or wert == "":
        return None
    treffer = _ZEIT_RE.fullmatch(wert) if isinstance(wert, str) else None
    if treffer is None:
        raise ungueltig(f"{feld} muss eine Uhrzeit der Form HH:MM sein.")
    return time(int(treffer.group(1)), int(treffer.group(2)))


def uuid_lesen(wert: object) -> str | None:
    """Kleingeschriebene UUID mit Bindestrichen oder None (jede andere Schreibweise zählt nicht)."""
    if not isinstance(wert, str) or not _UUID_RE.fullmatch(wert):
        return None
    try:
        return str(uuid.UUID(wert))
    except ValueError:  # pragma: no cover  (das Muster lässt nur gültige Formen zu)
        return None


def nummer_lesen(wert: object) -> int | None:
    """Positive ganze Zahl aus einem Pfadteil (nur Ziffern, höchstens 18 Stellen) oder None."""
    if isinstance(wert, str) and wert.isascii() and wert.isdigit() and len(wert) <= 18 and int(wert) >= 1:
        return int(wert)
    return None


def _konstante_ablehnen(_name: str) -> Any:
    raise ValueError("NaN und Unendlich sind kein JSON")


async def json_objekt(request: Request, *, optional: bool = False) -> dict:
    """Der Körper als JSON-Objekt. optional=True erlaubt einen leeren Körper (ergibt {}). Zu groß, kein JSON oder kein Objekt: 422."""
    laenge = request.headers.get("content-length")
    if laenge is not None and (not laenge.isdigit() or int(laenge) > MAX_KOERPER):
        raise ungueltig("Die Eingabe ist zu groß.")
    teile: list[bytes] = []
    gesamt = 0
    async for teil in request.stream():
        gesamt += len(teil)
        if gesamt > MAX_KOERPER:
            raise ungueltig("Die Eingabe ist zu groß.")
        teile.append(teil)
    roh = b"".join(teile)
    if not roh.strip():
        if optional:
            return {}
        raise ungueltig("Die Eingabe fehlt.")
    try:
        daten = json.loads(roh.decode("utf-8"), parse_constant=_konstante_ablehnen)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ungueltig("Die Eingabe ist kein gültiges JSON.") from None
    if not isinstance(daten, dict):
        raise ungueltig("Die Eingabe muss ein JSON-Objekt sein.")
    return daten


def abfrage_ganz(request: Request, name: str, standard: int, *, minimum: int, maximum: int) -> int:
    """Ganzzahliger Abfrageparameter. Fehlt er, gilt der Standard; ein Wert außerhalb der Grenzen oder doppelt: 422."""
    werte = request.query_params.getlist(name)
    if not werte:
        return standard
    if len(werte) > 1 or not werte[0].isascii() or not werte[0].isdigit() or len(werte[0]) > 6:
        raise ungueltig(f"{name} muss eine Zahl zwischen {minimum} und {maximum} sein.")
    zahl = int(werte[0])
    if not minimum <= zahl <= maximum:
        raise ungueltig(f"{name} muss eine Zahl zwischen {minimum} und {maximum} sein.")
    return zahl


def abfrage_wahl(request: Request, name: str, erlaubt: tuple[str, ...]) -> str | None:
    """Abfrageparameter, der leer sein oder einer der erlaubten Werte sein muss (sonst 422)."""
    werte = request.query_params.getlist(name)
    if not werte or werte == [""]:
        return None
    if len(werte) > 1 or werte[0] not in erlaubt:
        raise ungueltig(f"{name} hat keinen erlaubten Wert.")
    return werte[0]


def pfad_id(wert: str) -> str:
    """Pfadteil als UUID, sonst 404 (so eine Kennung kann es nicht geben)."""
    kennung = uuid_lesen(wert)
    if kennung is None:
        raise WerkstattFehler("nicht_gefunden")
    return kennung
