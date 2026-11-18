"""Historie des Canvas (Wunsch vom 18.11.2026): geschlossene und ältere Canvas-Elemente der Person, zum Wiederöffnen als Reiter.

  GET  /wamo/api/canvas/historie   {"eigene": [...], "geteilt": [...]}, je Eintrag {"id", "titel", "art", "zeit"}, bei geteilten dazu
                                   {"von", "recht"}; neueste zuerst

Schließen eines Reiters blendet ihn nur aus (Oberfläche, Werkzeug canvas_schliessen in tools.py): Die Zeilen in canvas_items bleiben, eine
Spalte für "geschlossen" braucht es nicht, denn die Reiter gehören der Oberfläche und beginnen jede Sitzung leer. Die Historie liest:
  * eigene Wurzeln (parent_id null) der vier Arten, die das Canvas kennt, mit Titel und Zeit der neuesten Fassung. canvas_zeigen speichert
    jede Überarbeitung als eigene Wurzel; damit die Liste nicht jede Fassung einzeln zeigt, bleibt je Sitzung, Art und Titel nur die
    neueste.
    Vorab nur die letzten VORAUSWAHL Wurzeln, damit die Abfrage auch bei langer Nutzung klein bleibt.
  * mit der Person geteilte Elemente (laufende Teilungen der Art canvas), wie sie die geteilte Arbeit kennt (teilen.py).
Wieder geöffnet wird über die bestehende Route GET /wamo/api/geteilt/canvas/{id} (teilen_api.py), die Besitz oder Teilung selbst prüft.

Sicherheit: Token mit zweitem Faktor und aktives Profil prüft die Zugangskontrolle (wamo_api.identitaet); das Profil kommt nur von dort.
Nie für Laborprofile: die Middleware lässt den Pfad nicht durch (labor.pfad_pruefen), die Route lehnt zusätzlich selbst mit 403 und dem
Code labor_pfad_gesperrt ab, bevor sie liest. Gelesen werden nur Titel, Art und Zeit, nie Inhalte; Titel und Namen laufen durch
clean_inline. Fehler nennen keine Datenbankmeldung. Cache-Control: no-store.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

import labor
from memory import DB_ERRORS, Database, shared_database
from persona import clean_inline
from wamo_api import identitaet

router = APIRouter()
MAX_EIGENE = 40
MAX_GETEILT = 20
VORAUSWAHL = 400
TITEL_MAX = 120
NAME_MAX = 60
ARTEN = {"document": "dokument", "code": "code", "mermaid": "mermaid", "table": "tabelle"}
_DB_TYPEN = "('document','code','mermaid','table')"
_RECHTE = ("lesen", "bearbeiten")


def _labor_gesperrt() -> JSONResponse:
    return JSONResponse({"detail": "Für Laborprofile gesperrt", "code": labor.CODE_PFAD_GESPERRT}, status_code=403,
                        headers={"Cache-Control": "no-store"})


def _db() -> Database:
    try:
        db = shared_database()
    except ValueError as e:
        raise HTTPException(503, "Datenbank nicht eingerichtet") from e
    if not db.configured:
        raise HTTPException(503, "Datenbank nicht eingerichtet")
    return db


def _neueste(c: str, alias: str) -> str:
    """Titel und Zeit der neuesten Fassung einer Wurzel (Bearbeitungen geteilter Dokumente legen Fassungen mit parent_id an)."""
    return (f"join lateral (select {alias}.title, {alias}.updated_at from {c} {alias} where {alias}.id = w.id or {alias}.parent_id = w.id "
            f"order by {alias}.version desc, {alias}.created_at desc limit 1) n on true")


def _sql_eigene(db: Database) -> str:
    c = db.t("canvas_items")
    return (f"select h.id, h.title, h.typ, h.zeit from ("
            f"select distinct on (coalesce(w.session_id, w.id), w.type, lower(w.title)) "
            f"w.id::text as id, n.title, w.type::text as typ, n.updated_at as zeit "
            f"from (select w.id, w.session_id, w.type, w.title from {c} w "
            f"where w.user_id = $1::uuid and w.parent_id is null and w.type::text in {_DB_TYPEN} "
            f"order by w.updated_at desc limit $2) w "
            f"{_neueste(c, 'x')} "
            f"order by coalesce(w.session_id, w.id), w.type, lower(w.title), n.updated_at desc"
            f") h order by h.zeit desc, h.id desc limit $3")


def _sql_geteilt(db: Database) -> str:
    c, t, p = db.t("canvas_items"), db.t("teilungen"), db.t("profiles")
    return (f"select w.id::text as id, n.title, w.type::text as typ, n.updated_at as zeit, b.display_name as von, x.recht "
            f"from {t} x join {c} w on w.id = x.canvas_id and w.parent_id is null "
            f"{_neueste(c, 'y')} "
            f"left join {p} b on b.user_id = x.besitzer "
            f"where x.empfaenger = $1::uuid and x.art = 'canvas' and x.widerrufen_at is null and w.type::text in {_DB_TYPEN} "
            f"order by n.updated_at desc, w.id desc limit $2")


def _zeit(wert: datetime | None) -> str | None:
    return wert.isoformat() if wert is not None else None


def _eintrag(zeile: Mapping) -> dict | None:
    art = ARTEN.get(zeile["typ"])
    if art is None:
        return None
    return {"id": zeile["id"], "titel": clean_inline(zeile["title"], TITEL_MAX) or "Ohne Titel", "art": art, "zeit": _zeit(zeile["zeit"])}


def _geteilt(zeile: Mapping) -> dict | None:
    eintrag = _eintrag(zeile)
    if eintrag is None:
        return None
    von = clean_inline(zeile["von"], NAME_MAX) if zeile["von"] else None
    return {**eintrag, "von": von or None, "recht": zeile["recht"] if zeile["recht"] in _RECHTE else "lesen"}


@router.get("/canvas/historie", response_model=None)
async def historie(request: Request, response: Response) -> dict | JSONResponse:
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _labor_gesperrt()
    db = _db()
    try:
        eigene = await db.fetch(_sql_eigene(db), ich.user_id, VORAUSWAHL, MAX_EIGENE)
        geteilte = await db.fetch(_sql_geteilt(db), ich.user_id, MAX_GETEILT)
    except DB_ERRORS as e:
        logger.warning("Canvas-Historie: Abfrage fehlgeschlagen ({})", type(e).__name__)
        raise HTTPException(503, "Historie gerade nicht verfügbar") from e
    response.headers["Cache-Control"] = "no-store"
    return {"eigene": [e for z in eigene if (e := _eintrag(z))], "geteilt": [e for z in geteilte if (e := _geteilt(z))]}
