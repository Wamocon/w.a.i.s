"""Kennzahlen und Dateien lesen: nur erlaubte Felder, nur Zahlen, Stände und Zeiten.

Jede Zeile aus der Datenbank oder aus einer Datei wird auf eine feste Liste von Feldern verkleinert. Was nicht auf der Liste steht,
verlässt den Dienst nie, auch wenn eine Funktion der Datenbank (versehentlich) mehr liefert. Werte, die nicht zum Feld passen,
werden null, eine Zeile ohne ihr Schlüsselfeld fällt weg. Gesprächstext, Namen, E-Mail und Geräte kommen hier nie vor.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

PROTOKOLL_MAX_ZEILEN = 500
DATEI_MAX_BYTES = 1024 * 1024  # je Protokolldatei wird höchstens das Ende von 1 MB gelesen
BETRIEB_MAX_BYTES = 64 * 1024
STUFEN = ("info", "warnung", "fehler")
AKTION_STATUS = ("pending", "approved", "rejected", "running", "done", "failed", "blocked")
LABOR_ARTEN = ("platz", "schaufenster")
_KENNUNG_RE = re.compile(r"^labor-[a-z0-9]{2,8}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
_ZAHLEN_SCHLUESSEL_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_KURZ_ERLAUBT = frozenset("LNPS")


def _wert(zeile: Mapping[str, Any], *namen: str) -> Any:
    for name in namen:
        if name in zeile:
            return zeile[name]
    return None


def zahl(wert: object, *, nachkommastellen: int = 1) -> float | int | None:
    """Endliche Zahl (nie bool), Decimal und float werden gerundet, sonst None."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, int):
        return wert
    if isinstance(wert, (float, Decimal)):
        z = float(wert)
        return round(z, nachkommastellen) if math.isfinite(z) else None
    return None


def ganz(wert: object) -> int | None:
    z = zahl(wert, nachkommastellen=0)
    return int(z) if z is not None and z >= 0 else None


def tag(wert: object) -> str | None:
    if isinstance(wert, datetime):
        return wert.date().isoformat()
    return wert.isoformat() if isinstance(wert, date) else None


def kurztext(wert: object, maximum: int = 60) -> str | None:
    """Kurzer Text aus Buchstaben, Ziffern, Satzzeichen und Symbolen (Version, Farbe, Zustand), sonst None."""
    if not isinstance(wert, str) or not 1 <= len(wert) <= maximum:
        return None
    if any(c != " " and unicodedata.category(c)[0] not in _KURZ_ERLAUBT for c in wert):
        return None
    return wert.strip() or None


def zeit_lesen(wert: object) -> datetime | None:
    """ISO-Zeitstempel mit Zeitzone (ohne Zone gilt UTC), sonst None."""
    if not isinstance(wert, str) or not 10 <= len(wert) <= 40:
        return None
    try:
        z = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------------- Datenbank
def sitzungen_zeilen(zeilen: Iterable[Mapping[str, Any]]) -> list[dict]:
    aus = []
    for z in zeilen:
        t, anzahl = tag(_wert(z, "tag", "datum")), ganz(_wert(z, "anzahl", "sitzungen"))
        if t is None or anzahl is None:
            continue
        aus.append({"tag": t, "anzahl": anzahl, "dauer_p50_s": zahl(_wert(z, "dauer_p50_s", "p50_s", "dauer_p50")),
                    "dauer_p95_s": zahl(_wert(z, "dauer_p95_s", "p95_s", "dauer_p95")), "offen": ganz(_wert(z, "offen", "offene"))})
    return aus


def latenz_zeilen(zeilen: Iterable[Mapping[str, Any]]) -> list[dict]:
    aus = []
    for z in zeilen:
        zuege = ganz(_wert(z, "zuege", "anzahl"))
        if zuege is None:
            continue
        zeile: dict[str, Any] = {"zuege": zuege, "p50_ms": zahl(_wert(z, "p50_ms", "p50")), "p95_ms": zahl(_wert(z, "p95_ms", "p95"))}
        t = tag(_wert(z, "tag", "datum"))
        if t is not None:
            zeile = {"tag": t, **zeile}
        aus.append(zeile)
    return aus


def aktionen_zeilen(zeilen: Iterable[Mapping[str, Any]]) -> list[dict]:
    aus = []
    for z in zeilen:
        werkzeug, status, anzahl = _wert(z, "tool", "werkzeug"), _wert(z, "status"), ganz(_wert(z, "anzahl"))
        if isinstance(werkzeug, str) and _TOOL_RE.fullmatch(werkzeug) and status in AKTION_STATUS and anzahl is not None:
            aus.append({"tool": werkzeug, "status": status, "anzahl": anzahl})
    return aus


def labor_stand_zeilen(zeilen: Iterable[Mapping[str, Any]]) -> list[dict]:
    aus = []
    for z in zeilen:
        art = _wert(z, "art", "labor_art")
        platz = ganz(_wert(z, "platz", "labor_platz"))
        aktiv = _wert(z, "aktiv", "freigeschaltet", "labor_aktiv")
        if art not in LABOR_ARTEN or not isinstance(aktiv, bool):
            continue
        zeile: dict[str, Any] = {"art": art, "platz": platz if platz is not None and 1 <= platz <= 16 else None, "aktiv": aktiv,
                                 "zeilen": ganz(_wert(z, "zeilen", "zeilenzahl", "anzahl"))}
        kennung = _wert(z, "kennung")
        if isinstance(kennung, str) and _KENNUNG_RE.fullmatch(kennung):
            zeile = {"kennung": kennung, **zeile}
        aus.append(zeile)
    return aus


# ---------------------------------------------------------------------------------------------------------------- Dateien
def _datei_lesen(pfad: Path, maximum: int, *, ende: bool) -> bytes | None:
    """Liest eine reguläre Datei ohne einem Link zu folgen (sonst None). ende=True liest höchstens das Ende, sonst die Datei ganz (zu groß: None)."""
    try:
        fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > maximum:
            if not ende:
                return None
            os.lseek(fd, st.st_size - maximum, os.SEEK_SET)
        roh = os.read(fd, maximum + 1)
        return roh[:maximum] if ende else roh
    except OSError:
        return None
    finally:
        os.close(fd)


def _betrieb_teil(wert: object, felder: Mapping[str, str]) -> dict[str, Any] | None:
    """Ein Teilobjekt auf die erlaubten Felder verkleinern. felder: Name -> Art (text oder bool)."""
    if not isinstance(wert, dict):
        return None
    aus: dict[str, Any] = {}
    for name, art in felder.items():
        roh = wert.get(name)
        aus[name] = roh if art == "bool" and isinstance(roh, bool) else kurztext(roh) if art == "text" else None
    return aus


def betrieb_lesen(ordner: Path, jetzt: datetime) -> dict | None:
    """Inhalt von betrieb.json (schreibt der Sammler) auf die erlaubten Felder verkleinert, dazu alter_s. None, wenn die Datei fehlt
    oder unbrauchbar ist."""
    roh = _datei_lesen(ordner / "betrieb.json", BETRIEB_MAX_BYTES, ende=False)
    if roh is None:
        return None
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(daten, dict):
        return None
    zeit = zeit_lesen(daten.get("zeit"))
    if zeit is None:
        return None
    kern_felder = {"slot": "text", "release": "text", "aktiv": "bool"}
    kern_roh = daten.get("kern")
    kern: Any = ([k for k in (_betrieb_teil(e, kern_felder) for e in kern_roh[:4]) if k] if isinstance(kern_roh, list)
                 else _betrieb_teil(kern_roh, kern_felder))
    return {
        "zeit": zeit.isoformat(), "alter_s": max(0, int((jetzt - zeit).total_seconds())), "kern": kern,
        "oberflaeche": _betrieb_teil(daten.get("oberflaeche"), {"farbe": "text", "version": "text"}),
        "installer": _betrieb_teil(daten.get("installer"), {"version": "text"}),
        "kanal": _betrieb_teil(daten.get("kanal"), {"zustand": "text"}),
        "labor_dienst": _betrieb_teil(daten.get("labor_dienst"), {"zustand": "text"}),
    }


def _protokollzeile(zeile: object, marke: str) -> dict | None:
    if not isinstance(zeile, dict):
        return None
    zeit, code, rohe_zahlen = zeit_lesen(zeile.get("zeit")), zeile.get("code"), zeile.get("zahlen", {})
    if zeit is None or zeile.get("marke") != marke or zeile.get("stufe") not in STUFEN:
        return None
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code) or not isinstance(rohe_zahlen, dict):
        return None
    zahlen = {k: z for k, v in list(rohe_zahlen.items())[:8]
              if isinstance(k, str) and _ZAHLEN_SCHLUESSEL_RE.fullmatch(k) and (z := zahl(v, nachkommastellen=3)) is not None}
    return {"zeit": zeit.isoformat(), "_t": zeit, "marke": marke, "stufe": zeile["stufe"], "code": code, "zahlen": zahlen}


def protokolle_lesen(ordner: Path, marken: Iterable[str], *, stufe: str | None, seit: datetime) -> list[dict]:
    """Zeilen aus protokolle/<marke>.jsonl, neueste zuerst, höchstens PROTOKOLL_MAX_ZEILEN. Es werden nur Dateien der gegebenen Marken
    gelesen (nie eine Auflistung des Ordners), jede Zeile wird auf zeit, marke, stufe, code und Zahlen verkleinert."""
    treffer: list[dict] = []
    for marke in marken:
        roh = _datei_lesen(ordner / "protokolle" / f"{marke}.jsonl", DATEI_MAX_BYTES, ende=True)
        if roh is None:
            continue
        for text in roh.decode("utf-8", "replace").splitlines():
            try:
                zeile = _protokollzeile(json.loads(text), marke)
            except (ValueError, RecursionError):
                continue
            if zeile is not None and zeile["_t"] >= seit and (stufe is None or zeile["stufe"] == stufe):
                treffer.append(zeile)
    treffer.sort(key=lambda z: z["_t"], reverse=True)
    return [{k: v for k, v in z.items() if k != "_t"} for z in treffer[:PROTOKOLL_MAX_ZEILEN]]
