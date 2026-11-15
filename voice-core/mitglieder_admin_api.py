"""Admin-Übersicht "Neue Mitglieder" (Paket P7, docs/ausrollen-neue-nutzer.md; Migration 0022).

  GET /wamo/api/admin/neue-mitglieder   je Profil (ohne Laborprofile), wie weit die Einrichtung ist

Die Daten kommen allein aus der Funktion neue_mitglieder(p_admin) der Datenbank (SECURITY DEFINER, nur für wamo_core). Sie
liefert nur Stände und Ja oder Nein, nie E-Mail, Schlüssel, Token oder den Stimmvektor. Die Datenbank prüft nur, dass die
übergebene Kennung ein aktiver Admin ohne Laborkennung ist; den Aufrufer kennt sie nicht. Dieses Modul prüft davor, was die
Datenbank nicht sehen kann:

  * Anmeldung wie bei allen Routen (wamo_api.identitaet: Token mit zweitem Faktor, Höchstalter, aktives Profil).
  * Rolle admin und kein Laborprofil (Identity.is_admin), sonst 403 ohne Abfrage.
  * Höchstens 30 Abrufe je Minute und Admin.
  * Jede Zeile wird auf die erlaubten Felder und Werte verkleinert; Unbekanntes wird null, eine Zeile ohne gültige Kennung
    fällt weg. Fehler nennen nie interne Namen.
"""

from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from loguru import logger

from memory import DB_ERRORS, DatabaseUnavailable, normalize_uuid, shared_database
from wamo_api import identitaet

router = APIRouter()

LISTE_GRENZE = (30, 60.0)  # Abrufe je Fenster in Sekunden, je Admin
NAME_MAX = 60
STEUER_RE = re.compile("[\x00-\x1f\x7f-\x9f​-‏‪-‮⁠-⁩﻿]")
ROLLEN = ("admin", "mitglied")
GERAET_STAENDE = ("aktiv", "beantragt", "gesperrt", "widerrufen", "keins")
MODELLZUGAENGE = ("token_und_schluessel", "token", "schluessel", "haus")
PASSWORT_STAENDE = ("keine", "offen", "abgelaufen", "erledigt")  # Stände aus wamo_auth (P1a), die Datenbank filtert schon

_versuche: dict[str, deque[float]] = {}


def _drosseln(user_id: str, jetzt: float | None = None) -> None:
    anzahl, fenster = LISTE_GRENZE
    jetzt = time.monotonic() if jetzt is None else jetzt
    q = _versuche.setdefault(user_id, deque())
    while q and jetzt - q[0] > fenster:
        q.popleft()
    if len(q) >= anzahl:
        raise HTTPException(429, "Zu viele Anfragen, bitte gleich noch einmal")
    q.append(jetzt)
    if len(_versuche) > 200:
        for k in [k for k, d in _versuche.items() if not d or jetzt - d[-1] > fenster]:
            del _versuche[k]


def _db():
    try:
        db = shared_database()
    except ValueError as e:
        raise HTTPException(503, "Datenbank nicht eingerichtet") from e
    if not db.configured:
        raise HTTPException(503, "Datenbank nicht eingerichtet")
    return db


def _zeit(wert: object) -> str | None:
    return wert.isoformat() if isinstance(wert, datetime) else None


def _aus(wert: object, erlaubt: tuple[str, ...]) -> str | None:
    return wert if isinstance(wert, str) and wert in erlaubt else None


def _ja(wert: object) -> bool:
    return wert is True


def zeile_pruefen(r: Any) -> dict | None:
    """Eine Zeile der Datenbank auf genau die erlaubten Felder verkleinern; ohne gültige Kennung None."""
    user_id = normalize_uuid(r["user_id"])  # die Funktion liefert die Spalte immer; asyncpg.Record und dict gleich
    if user_id is None:
        return None
    name = r["anzeigename"] if isinstance(r["anzeigename"], str) else ""
    passwort = r["passwort_stand"]
    return {
        "user_id": user_id,
        "anzeigename": STEUER_RE.sub("", name)[:NAME_MAX],
        "rolle": _aus(r["rolle"], ROLLEN),
        "aktiv": _ja(r["aktiv"]),
        "angelegt": _zeit(r["angelegt"]),
        "letzte_anmeldung": _zeit(r["letzte_anmeldung"]),
        "faktor_bestaetigt": _ja(r["faktor_bestaetigt"]),
        "passwort_stand": _aus(passwort, PASSWORT_STAENDE),
        "geraet_stand": _aus(r["geraet_stand"], GERAET_STAENDE),
        "modellzugang": _aus(r["modellzugang"], MODELLZUGAENGE),
        "stimmabdruck": _ja(r["stimmabdruck"]),
    }


@router.get("/admin/neue-mitglieder")
async def liste(request: Request, response: Response) -> dict:
    ich = await identitaet(request)
    if not ich.is_admin:
        raise HTTPException(403, "Die Übersicht der neuen Mitglieder ist nur für Admins")
    _drosseln(ich.user_id)
    response.headers["Cache-Control"] = "no-store"
    db = _db()
    try:
        zeilen = await db.fetch(f"select * from {db.t('neue_mitglieder')}($1::uuid)", ich.user_id)
    except (*DB_ERRORS, DatabaseUnavailable) as e:
        if getattr(e, "sqlstate", None) == "42501":
            raise HTTPException(403, "Dir fehlt die Berechtigung für diese Übersicht") from e
        logger.warning("Neue Mitglieder: Liste fehlgeschlagen ({})", type(e).__name__)
        raise HTTPException(503, "Die Übersicht ist gerade nicht verfügbar") from e
    return {"mitglieder": [m for m in (zeile_pruefen(r) for r in zeilen) if m is not None]}
