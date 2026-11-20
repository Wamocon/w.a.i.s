"""Kartenkatalog: Karten (Use Cases), Zuordnung zu den Gästen, Versionen.

Eine Karte ändern setzt sie wieder auf Entwurf. Gelesen wird der Katalog vom Kern allein über die aktive Version, ein Entwurf wirkt
im Betrieb also erst nach dem Veröffentlichen (routen_veroeffentlichen.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .anmeldung import Zugang
from .daten import Verbindung
from .dienst import dienst_von, zugang_pruefen
from .eingabe import abfrage_ganz, json_objekt, pfad_id
from .fehler import WerkstattFehler, ungueltig
from .karten_regeln import (GRUPPEN, KARTE_ID_RE, WISSEN_MAX, gruppe_lesen, karte_ausgabe, karte_felder, matrix_pruefen, naechste_id,
                            sortierschluessel, zeichen)

router = APIRouter()


def karte_id(wert: str) -> str:
    if not KARTE_ID_RE.fullmatch(wert):
        raise WerkstattFehler("nicht_gefunden")
    return wert


async def _karte(db: Verbindung, kennung: str) -> dict:
    zeile = await db.karte(kennung)
    if zeile is None:
        raise WerkstattFehler("nicht_gefunden")
    return zeile


@router.get("/karten")
async def karten_liste(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    zeilen = sorted(await dienst.db.karten(), key=lambda k: sortierschluessel(k["id"]))
    return {"karten": [karte_ausgabe(k) for k in zeilen], "gruppen": GRUPPEN, "aktive_version": await dienst.db.aktive_version(),
            "zeichen": zeichen(zeilen, dienst.konfig.wissen_basis), "zeichen_max": WISSEN_MAX, "basis_zeichen": dienst.konfig.wissen_basis}


@router.get("/karten/versionen")
async def versionen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    grenze = abfrage_ganz(request, "grenze", 50, minimum=1, maximum=200)
    return {"versionen": [{"version": v["version"], "erstellt_at": v["erstellt_at"].isoformat(), "anzahl_aenderungen": v["anzahl_aenderungen"],
                           "wissen_zeichen": v["wissen_zeichen"], "aktiv": v["aktiv"] is True}
                          for v in await dienst_von(request).db.versionen(grenze)]}


@router.post("/karten", status_code=201)
async def karte_anlegen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    eingabe = await json_objekt(request)
    buchstabe, gruppe = gruppe_lesen(eingabe.get("gruppe"))
    felder = karte_felder(eingabe)
    async with dienst.schreiben(zugang, "werkstatt_karte_anlegen") as (tx, buchung):
        neue = naechste_id(buchstabe, [k["id"] for k in await tx.karten()])
        if neue is None:
            raise WerkstattFehler("konflikt", "Diese Gruppe hat schon 99 Karten.")
        zeile = await tx.karte_anlegen(neue, {**felder, "gruppe": gruppe}, zugang.user_id)
        buchung.params = {"karte": neue}
    return {"karte": karte_ausgabe(zeile)}


@router.get("/karten/{kennung}")
async def karte_lesen(kennung: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    return {"karte": karte_ausgabe(await _karte(dienst_von(request).db, karte_id(kennung)))}


@router.put("/karten/{kennung}")
async def karte_aendern(kennung: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, nummer = dienst_von(request), karte_id(kennung)
    eingabe = await json_objekt(request)
    felder = karte_felder(eingabe)
    async with dienst.schreiben(zugang, "werkstatt_karte_aendern") as (tx, buchung):
        bestehend = await _karte(tx, nummer)
        if "gruppe" in eingabe and gruppe_lesen(eingabe["gruppe"])[1] != bestehend["gruppe"]:
            raise ungueltig("Die Gruppe einer Karte lässt sich nicht ändern. Kopiere die Karte in die neue Gruppe.")
        zeile = await tx.karte_aendern(nummer, felder, zugang.user_id)
        if zeile is None:
            raise WerkstattFehler("nicht_gefunden")
        buchung.params = {"karte": nummer}
    return {"karte": karte_ausgabe(zeile)}


@router.delete("/karten/{kennung}")
async def karte_loeschen(kennung: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, nummer = dienst_von(request), karte_id(kennung)
    async with dienst.schreiben(zugang, "werkstatt_karte_loeschen") as (tx, buchung):
        if (await _karte(tx, nummer))["stand"] != "entwurf":
            raise WerkstattFehler("konflikt", "Veröffentlichte Karten lassen sich nicht löschen.")
        if not await tx.karte_loeschen(nummer):
            raise WerkstattFehler("konflikt")
        buchung.params = {"karte": nummer}
    return {"geloescht": True}


def _termin_param(request: Request) -> str:
    werte = request.query_params.getlist("termin")
    if len(werte) != 1:
        raise ungueltig("Der Termin fehlt.")
    return pfad_id(werte[0])


@router.get("/zuordnung")
async def zuordnung_lesen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    db, termin = dienst_von(request).db, _termin_param(request)
    if await db.termin(termin) is None:
        raise WerkstattFehler("nicht_gefunden")
    return {"termin": termin, "zuordnung": {str(p): ids for p, ids in (await db.zuordnung(termin)).items()}}


@router.put("/zuordnung")
async def zuordnung_setzen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, termin = dienst_von(request), _termin_param(request)
    matrix = matrix_pruefen(await json_objekt(request))
    async with dienst.schreiben(zugang, "werkstatt_zuordnung_setzen") as (tx, buchung):
        if await tx.termin(termin) is None:
            raise WerkstattFehler("nicht_gefunden")
        vorhanden = {k["id"] for k in await tx.karten()}
        if any(i not in vorhanden for ids in matrix.values() for i in ids):
            raise ungueltig("Die Zuordnung nennt eine Karte, die es nicht gibt.")
        await tx.zuordnung_setzen(termin, matrix)
        buchung.params = {"termin": termin}
        buchung.ergebnis = {"ok": True, "plaetze": len(matrix), "eintraege": sum(len(i) for i in matrix.values())}
    return {"termin": termin, "zuordnung": {str(p): ids for p, ids in matrix.items()}}
