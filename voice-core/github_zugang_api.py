"""Persönlicher GitHub-Zugang über HTTP, ohne laufendes Gespräch (Plan C, C.4), und die Admin-Einstellung der Rechte je Person.

  GET  /wamo/api/github-zugang           Stand des eigenen Zugangs (Art, Login, Rechte, Ablauf, die letzten vier Zeichen)
  POST /wamo/api/github-zugang           {"aktion": "stand" | "speichern" | "pruefen" | "loeschen", "token": ...}
  GET  /wamo/api/admin/github-rechte     nur Admin: je Profil ohne Laborprofile die erlaubten Ausnahmen und der Stand ohne Wert
  POST /wamo/api/admin/github-rechte     nur Admin: {"user_id": ..., "scopes_ausnahmen": [...]} nur aus SCOPES_AUSNAHMEN (C.2.8)

Sicherheit
  * Wie alle Routen unter /wamo/api: Token mit zweitem Faktor, Höchstalter der Anmeldung, aktives Profil (wamo_api.identitaet). Die
    Profil-ID der Person kommt nur aus der geprüften Identität, nie aus dem Body; nur die Admin-Route nennt ein Zielprofil.
  * Nie für Laborprofile: Die Laborsperre der Middleware lässt die Pfade nicht durch (Erlaubnisliste in labor.py); die Routen lehnen
    zusätzlich selbst mit 403 und dem Code labor_pfad_gesperrt ab, bevor sie etwas lesen oder schreiben.
  * Speichern und Prüfen nur mit Zulassung für Entwicklungsaufträge und mit WAMO_ENTWICKLUNG_GITHUB=an (github_zugang.verfuegbar_grund);
    Löschen geht immer. 5 Prüfungen bei GitHub je Profil in 10 Minuten.
  * Admin-Route: Rolle admin ohne Laborkennung (Identity.is_admin), sonst 403 ohne Abfrage; 30 Abrufe je Minute, 20 Änderungen je
    10 Minuten; jede Änderung als Zeile in actions (Werkzeug github_rechte). nie delete_repo, site_admin, admin:enterprise.
  * Bodys höchstens 4 KiB, nie geloggt und nie zurückgegeben; Antworten enthalten nie ein Token. Cache-Control: no-store.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

import github_zugang as gz
import labor
from memory import DB_ERRORS, DatabaseUnavailable, normalize_uuid
from wamo_api import identitaet, lies_json

router = APIRouter()
MAX_BODY_BYTES = 4 * 1024  # ein Token ist höchstens 93 Zeichen lang
LISTE_GRENZE = (30, 60.0)  # Abrufe der Admin-Liste je Fenster in Sekunden, je Admin

_abrufe: dict[str, deque[float]] = {}


def _labor_gesperrt() -> JSONResponse:
    return JSONResponse({"detail": "Für Laborprofile gesperrt", "code": labor.CODE_PFAD_GESPERRT}, status_code=403,
                        headers={"Cache-Control": "no-store"})


async def _ausfuehren(ich, data: dict) -> dict:
    antworten: list[dict] = []

    async def senden(nachricht: dict) -> None:
        antworten.append(nachricht)

    await gz.github_zugang_nachricht(ich, data, senden)
    if not antworten:
        logger.error("GitHub-Zugang-API: keine Antwort für Profil {}", ich.user_id[:8])
        return {"type": "github_zugang", "aktion": "stand", "verfuegbar": False, "fehler": "Unerwarteter Fehler, bitte später noch einmal."}
    return antworten[-1]


@router.get("/github-zugang", response_model=None)
async def stand(request: Request, response: Response) -> dict | JSONResponse:
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _labor_gesperrt()
    response.headers["Cache-Control"] = "no-store"
    return await _ausfuehren(ich, {"aktion": "stand"})


@router.post("/github-zugang", response_model=None)
async def aendern(request: Request, response: Response) -> dict | JSONResponse:
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _labor_gesperrt()
    response.headers["Cache-Control"] = "no-store"
    data = await lies_json(request, MAX_BODY_BYTES)
    return await _ausfuehren(ich, data)


def _drosseln(admin: str, jetzt: float | None = None) -> None:
    anzahl, fenster = LISTE_GRENZE
    jetzt = time.monotonic() if jetzt is None else jetzt
    q = _abrufe.setdefault(admin, deque())
    while q and jetzt - q[0] > fenster:
        q.popleft()
    if len(q) >= anzahl:
        raise HTTPException(429, "Zu viele Anfragen, bitte gleich noch einmal", headers={"Cache-Control": "no-store"})
    q.append(jetzt)


async def _admin(request: Request):
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return None, _labor_gesperrt()
    if not ich.is_admin:
        raise HTTPException(403, "Die Rechte der GitHub-Zugänge stellen nur Admins ein", headers={"Cache-Control": "no-store"})
    return ich, None


def _liste_antwort(personen: list[gz.Person]) -> dict:
    return {"personen": [p.daten() for p in personen], "erlaubbar": list(gz.SCOPES_AUSNAHMEN),
            "unbedenklich": list(gz.SCOPES_UNBEDENKLICH), "nie": list(gz.SCOPES_NIE)}


@router.get("/admin/github-rechte", response_model=None)
async def rechte_liste(request: Request, response: Response) -> dict | JSONResponse:
    ich, gesperrt = await _admin(request)
    if gesperrt is not None:
        return gesperrt
    _drosseln(ich.user_id)
    response.headers["Cache-Control"] = "no-store"
    try:
        personen = await gz.rechte_liste()
    except gz.ZugangFehler as e:
        raise HTTPException(503, str(e), headers={"Cache-Control": "no-store"}) from None
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("GitHub-Rechte: Liste fehlgeschlagen ({})", type(e).__name__)
        raise HTTPException(503, "Die Übersicht ist gerade nicht verfügbar", headers={"Cache-Control": "no-store"}) from None
    return _liste_antwort(personen)


@router.post("/admin/github-rechte", response_model=None)
async def rechte_setzen(request: Request, response: Response) -> dict | JSONResponse:
    ich, gesperrt = await _admin(request)
    if gesperrt is not None:
        return gesperrt
    _drosseln(ich.user_id)
    response.headers["Cache-Control"] = "no-store"
    data = await lies_json(request, MAX_BODY_BYTES)
    try:
        ausnahmen = await gz.rechte_setzen(ich.user_id, data.get("user_id"), data.get("scopes_ausnahmen"))
    except gz.ZugangFehler as e:
        return JSONResponse({"detail": str(e)}, status_code=400, headers={"Cache-Control": "no-store"})
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("GitHub-Rechte: Änderung fehlgeschlagen ({})", type(e).__name__)
        raise HTTPException(503, "Die Änderung ist gerade nicht möglich", headers={"Cache-Control": "no-store"}) from None
    return {"user_id": normalize_uuid(data.get("user_id")), "scopes_ausnahmen": list(ausnahmen)}
