"""Regeln für Termine, Plätze und Checkliste des Labor-Planers (ohne Datenbank, ohne Netz).

Die Prüfungen sind dieselben wie die der Datenbank (Migration 0031), nur mit einem Satz für die Person statt eines Datenbankfehlers.
Fristen: Aufbewahrung bis = Labortag + 13 Tage (Vorgabe, höchstens + 14), Löschlauf ab = Aufbewahrung bis + 1 Tag (nur berechnet, nie
gespeichert).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, time, timedelta
from typing import Any

from .eingabe import datum_lesen, ganzzahl_lesen, text_lesen, zeit_lesen
from .fehler import ungueltig

TERMIN_STATUS = ("entwurf", "freigegeben", "laufend", "nachlauf", "abgeschlossen")
ZWECKE = ("besucher", "reserve", "abnahme")
ABNAHME_PLAETZE = (15, 16)
PLATZ_MAX = 16
KENNUNG_RE = re.compile(r"^labor-[a-z0-9]{2,8}$")
FRIST_VORGABE_TAGE = 13
FRIST_MAX_TAGE = 14
CHECKLISTE_MAX = 100
TAG_ZURUECK = timedelta(days=366)
TAG_VOR = timedelta(days=366 * 5)


def loeschlauf_ab(aufbewahrung_bis: date) -> date:
    return aufbewahrung_bis + timedelta(days=1)


def uhrzeit(wert: time | None) -> str | None:
    return wert.strftime("%H:%M") if isinstance(wert, time) else None


def termin_ausgabe(zeile: Mapping[str, Any]) -> dict[str, Any]:
    """Ein Termin für die Antwort: Datum und Zeit als Text, dazu der berechnete Löschlauf."""
    bis = zeile["aufbewahrung_bis"]
    return {"id": zeile["id"], "tag": zeile["tag"].isoformat(), "beginn": uhrzeit(zeile.get("beginn")), "ende": uhrzeit(zeile.get("ende")),
            "einwilligung_version": zeile["einwilligung_version"], "status": zeile["status"], "aufbewahrung_bis": bis.isoformat(),
            "loeschlauf_ab": loeschlauf_ab(bis).isoformat()}


def _aus_zeile(bestehend: Mapping[str, Any]) -> dict[str, Any]:
    return {k: bestehend.get(k) for k in ("tag", "beginn", "ende", "einwilligung_version", "status", "aufbewahrung_bis")}


def termin_pruefen(daten: Mapping[str, Any], heute: date, bestehend: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Die Felder eines Termins für die Datenbank. Mit bestehend (PUT) behalten fehlende Felder ihren Wert; ändert sich der Tag und
    fehlt aufbewahrung_bis, gilt die Vorgabe für den neuen Tag. Unbekannte Felder werden ignoriert und nie weitergegeben."""
    if bestehend is None:
        werte: dict[str, Any] = {"tag": None, "beginn": None, "ende": None, "einwilligung_version": 1, "status": "entwurf", "aufbewahrung_bis": None}
    else:
        werte = _aus_zeile(bestehend)
    alter_tag = werte["tag"]
    if "tag" in daten or bestehend is None:
        werte["tag"] = datum_lesen(daten.get("tag"), "Der Labortag")
    for name, bezeichnung in (("beginn", "Der Beginn"), ("ende", "Das Ende")):
        if name in daten:
            werte[name] = zeit_lesen(daten.get(name), bezeichnung)
    if "einwilligung_version" in daten:
        werte["einwilligung_version"] = ganzzahl_lesen(daten.get("einwilligung_version"), "Die Version der Einwilligung", minimum=1, maximum=99)
    if "status" in daten:
        if daten.get("status") not in TERMIN_STATUS:
            raise ungueltig("Der Stand des Termins ist unbekannt.")
        werte["status"] = daten["status"]
    tag = werte["tag"]
    if not heute - TAG_ZURUECK <= tag <= heute + TAG_VOR:
        raise ungueltig("Der Labortag liegt zu weit in der Vergangenheit oder in der Zukunft.")
    if "aufbewahrung_bis" in daten and daten.get("aufbewahrung_bis") not in (None, ""):
        werte["aufbewahrung_bis"] = datum_lesen(daten.get("aufbewahrung_bis"), "Die Aufbewahrung")
    elif werte["aufbewahrung_bis"] is None or tag != alter_tag:
        werte["aufbewahrung_bis"] = tag + timedelta(days=FRIST_VORGABE_TAGE)
    if not tag <= werte["aufbewahrung_bis"] <= tag + timedelta(days=FRIST_MAX_TAGE):
        raise ungueltig("Die Aufbewahrung muss zwischen dem Labortag und 14 Tagen danach enden.")
    if werte["beginn"] is not None and werte["ende"] is not None and werte["beginn"] >= werte["ende"]:
        raise ungueltig("Der Beginn muss vor dem Ende liegen.")
    return werte


def plaetze_pruefen(daten: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Die Plätze eines Termins (ersetzen den bisherigen Satz). Jeder Platz höchstens einmal, jede Kennung höchstens einmal."""
    roh = daten.get("plaetze")
    if not isinstance(roh, list) or len(roh) > PLATZ_MAX:
        raise ungueltig("Die Plätze müssen eine Liste mit höchstens 16 Einträgen sein.")
    aus: list[dict[str, Any]] = []
    plaetze: set[int] = set()
    kennungen: set[str] = set()
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise ungueltig("Jeder Platz muss ein Objekt sein.")
        platz = ganzzahl_lesen(eintrag.get("platz"), "Die Platznummer", minimum=1, maximum=PLATZ_MAX)
        zweck = eintrag.get("zweck")
        if zweck not in ZWECKE:
            raise ungueltig("Der Zweck eines Platzes ist unbekannt.")
        if zweck == "abnahme" and platz not in ABNAHME_PLAETZE:
            raise ungueltig("Abnahmeplätze sind nur die Plätze 15 und 16.")
        kennung = text_lesen(eintrag.get("kennung"), "Die Kennung", maximum=20)
        if kennung is not None and not KENNUNG_RE.fullmatch(kennung):
            raise ungueltig("Die Kennung hat nicht die Form labor-xx.")
        if platz in plaetze or (kennung is not None and kennung in kennungen):
            raise ungueltig("Ein Platz oder eine Kennung kommt doppelt vor.")
        plaetze.add(platz)
        if kennung is not None:
            kennungen.add(kennung)
        aus.append({"platz": platz, "zweck": zweck, "kennung": kennung, "gast": text_lesen(eintrag.get("gast"), "Der Gast", maximum=20)})
    return sorted(aus, key=lambda p: p["platz"])


def platz_ausgabe(zeile: Mapping[str, Any]) -> dict[str, Any]:
    return {"platz": zeile["platz"], "zweck": zeile["zweck"], "kennung": zeile.get("kennung"), "gast": zeile.get("gast")}


def punkt_pruefen(daten: Mapping[str, Any]) -> dict[str, Any]:
    return {"titel": text_lesen(daten.get("titel"), "Der Titel", maximum=120, pflicht=True),
            "quelle": text_lesen(daten.get("quelle"), "Die Quelle", maximum=80),
            "faellig": datum_lesen(daten.get("faellig"), "Das Fälligkeitsdatum", pflicht=False)}


def punkt_ausgabe(zeile: Mapping[str, Any]) -> dict[str, Any]:
    faellig, erledigt = zeile.get("faellig"), zeile.get("erledigt_at")
    return {"nr": zeile["nr"], "titel": zeile["titel"], "quelle": zeile.get("quelle"),
            "faellig": faellig.isoformat() if isinstance(faellig, date) else None,
            "erledigt": erledigt is not None, "erledigt_at": erledigt.isoformat() if erledigt is not None else None}
