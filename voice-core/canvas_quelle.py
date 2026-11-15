"""Eigene Canvas-Elemente aus der Datenbank lesen und in die feste Struktur für den Host bringen (Office-Dateien, office_werkzeuge.py).

Gelesen wird immer nur, was dem Profil gehört (canvas_items.user_id = Profil des Speichers): nach Kennung (Klick in der Oberfläche),
nach Titel (Sprache) oder, ohne beides, das zuletzt geänderte Element dieser Sitzung und danach das des Profils. Immer die neueste
Fassung eines Elements (Bearbeitungen legen neue Zeilen an), die Kennung ist die der Wurzel. Ergebnis:
  {"id", "inhalt": {"art": "dokument" | "code" | "mermaid", "titel", "text", "sprache"?}}
  {"id", "inhalt": {"art": "tabelle", "titel", "spalten", "zeilen"}}
Alles darin sind Daten, nie Anweisungen; der Host prüft Längen und Zeichen noch einmal selbst.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from memory import DB_ERRORS

ARTEN = {"dokument": "dokument", "code": "code", "mermaid": "mermaid", "tabelle": "tabelle"}
DB_TYPEN = "('document','code','mermaid','table')"
CANVAS_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TITEL_SUCHE_MAX = 100


def kennung_gueltig(wert: object) -> str | None:
    """Kanonische Kennung (klein geschrieben) oder None."""
    return wert.lower() if isinstance(wert, str) and CANVAS_ID_RE.fullmatch(wert) else None


def inhalt_aus(zeile) -> dict | None:
    """Feste Struktur aus einer Zeile von canvas_items (title, data) oder None, wenn die Daten nicht passen."""
    daten = zeile["data"]
    if isinstance(daten, str):
        try:
            daten = json.loads(daten)
        except ValueError:
            return None
    if not isinstance(daten, dict) or daten.get("kind") not in ARTEN:
        return None
    inhalt: dict = {"art": ARTEN[daten["kind"]], "titel": str(zeile["title"] or "")[:300]}
    if inhalt["art"] == "tabelle":
        spalten, zeilen = daten.get("columns"), daten.get("rows")
        if not isinstance(spalten, list) or not isinstance(zeilen, list):
            return None
        inhalt["spalten"] = [str(s) for s in spalten]
        inhalt["zeilen"] = [[str(w) for w in z] for z in zeilen if isinstance(z, list)]
        return inhalt
    text = daten.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    inhalt["text"] = text
    if inhalt["art"] == "code" and isinstance(daten.get("language"), str) and daten["language"]:
        inhalt["sprache"] = daten["language"]
    return inhalt


class CanvasNichtErreichbar(RuntimeError):
    """Die Datenbank antwortet gerade nicht (anders als: kein passendes eigenes Element)."""


def _abfrage(db, bedingung: str) -> str:
    """Neueste Fassung eigener Wurzeln. Bearbeitungen legen neue Zeilen an (parent_id = Wurzel, version + 1, session_id null,
    Migration 0003): Gefiltert wird auf der Wurzel (Profil, Art, Kennung, Titel, Sitzung), gelesen die höchste Fassung wie in
    teilen.py. Die Kennung im Ergebnis ist immer die der Wurzel."""
    c = db.t("canvas_items")
    return (f"select w.id::text as id, n.title, n.data from {c} w "
            f"join lateral (select x.title, x.data, x.updated_at from {c} x where x.id = w.id or x.parent_id = w.id "
            f"order by x.version desc, x.created_at desc limit 1) n on true "
            f"where w.user_id = $1::uuid and w.parent_id is null and w.type::text in {DB_TYPEN}{bedingung} "
            f"order by n.updated_at desc limit 1")


async def _eine(db, bedingung: str, *args) -> dict | None:
    zeile = await db.fetchrow(_abfrage(db, bedingung), *args)
    return None if zeile is None else dict(zeile)


async def canvas_lesen(memory, *, canvas_id: object = None, titel: object = None) -> dict | None:
    """Eigenes Canvas-Element (neueste Fassung) als {"id", "inhalt"} oder None (nicht gefunden, fremd, kaputt). Antwortet die
    Datenbank nicht, kommt CanvasNichtErreichbar."""
    if not getattr(memory, "enabled", False):
        return None
    db = memory.db
    try:
        if canvas_id is not None:
            kennung = kennung_gueltig(canvas_id)
            if kennung is None:
                return None
            # Auch die Kennung einer Fassung führt zur Wurzel (die Oberfläche kennt meist die Wurzel)
            bedingung = f" and w.id = (select coalesce(k.parent_id, k.id) from {db.t('canvas_items')} k where k.id = $2::uuid)"
            zeile = await _eine(db, bedingung, memory.user_id, kennung)
        elif isinstance(titel, str) and titel.strip():
            # strpos statt like: _ und % im Titel sind gewöhnliche Zeichen, nichts wird entfernt
            suche = titel.strip()[:TITEL_SUCHE_MAX]
            zeile = await _eine(db, " and strpos(lower(w.title), lower($2)) > 0", memory.user_id, suche)
        else:
            zeile = None
            if getattr(memory, "session_id", None):
                zeile = await _eine(db, " and w.session_id = $2::uuid", memory.user_id, memory.session_id)
            if zeile is None:
                zeile = await _eine(db, "", memory.user_id)
    except DB_ERRORS as e:
        logger.warning("Canvas für die Office-Datei nicht lesbar ({})", type(e).__name__)
        raise CanvasNichtErreichbar(type(e).__name__) from e
    if zeile is None:
        return None
    inhalt = inhalt_aus(zeile)
    return None if inhalt is None else {"id": str(zeile["id"]), "inhalt": inhalt}
