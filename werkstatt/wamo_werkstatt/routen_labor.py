"""Labor-Planer: Stand der Laborprofile (nur lesend), Termine, Plätze, Checkliste. Jede Änderung schreibt eine Zeile in actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from . import lesen
from .anmeldung import Zugang
from .daten import Verbindung
from .dienst import dienst_von, zugang_pruefen
from .eingabe import json_objekt, nummer_lesen, pfad_id
from .fehler import WerkstattFehler, ungueltig
from .labor_regeln import (CHECKLISTE_MAX, platz_ausgabe, plaetze_pruefen, punkt_ausgabe, punkt_pruefen, termin_ausgabe,
                           termin_pruefen)

router = APIRouter()


async def _termin(db: Verbindung, termin_id: str) -> dict:
    zeile = await db.termin(termin_id)
    if zeile is None:
        raise WerkstattFehler("nicht_gefunden")
    return zeile


@router.get("/labor/stand")
async def stand(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    termine = await dienst.db.termine()
    offen = sorted((t for t in termine if t["status"] != "abgeschlossen"), key=lambda t: t["tag"])
    return {"profile": lesen.labor_stand_zeilen(await dienst.db.labor_stand()),
            "naechster_termin": termin_ausgabe(offen[0]) if offen else None}


@router.get("/labor/termine")
async def termine(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    return {"termine": [termin_ausgabe(t) for t in await dienst_von(request).db.termine()]}


@router.post("/labor/termine", status_code=201)
async def termin_anlegen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    daten = termin_pruefen(await json_objekt(request), dienst.jetzt().date())
    async with dienst.schreiben(zugang, "werkstatt_termin_anlegen") as (tx, buchung):
        zeile = await tx.termin_anlegen(daten, zugang.user_id)
        buchung.params = {"termin": zeile["id"]}
    return {"termin": termin_ausgabe(zeile)}


@router.get("/labor/termine/{termin_id}")
async def termin_lesen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    return {"termin": termin_ausgabe(await _termin(dienst_von(request).db, pfad_id(termin_id)))}


@router.put("/labor/termine/{termin_id}")
async def termin_aendern(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, kennung = dienst_von(request), pfad_id(termin_id)
    eingabe = await json_objekt(request)
    async with dienst.schreiben(zugang, "werkstatt_termin_aendern") as (tx, buchung):
        daten = termin_pruefen(eingabe, dienst.jetzt().date(), await _termin(tx, kennung))
        zeile = await tx.termin_aendern(kennung, daten)
        if zeile is None:
            raise WerkstattFehler("nicht_gefunden")
        buchung.params = {"termin": kennung}
    return {"termin": termin_ausgabe(zeile)}


@router.delete("/labor/termine/{termin_id}")
async def termin_loeschen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, kennung = dienst_von(request), pfad_id(termin_id)
    async with dienst.schreiben(zugang, "werkstatt_termin_loeschen") as (tx, buchung):
        if (await _termin(tx, kennung))["status"] != "entwurf":
            raise WerkstattFehler("konflikt", "Nur Termine im Stand Entwurf lassen sich löschen.")
        if not await tx.termin_loeschen(kennung):
            raise WerkstattFehler("nicht_gefunden")
        buchung.params = {"termin": kennung}
    return {"geloescht": True}


@router.get("/labor/termine/{termin_id}/plaetze")
async def plaetze_lesen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    db, kennung = dienst_von(request).db, pfad_id(termin_id)
    await _termin(db, kennung)
    return {"plaetze": [platz_ausgabe(p) for p in await db.plaetze(kennung)]}


@router.put("/labor/termine/{termin_id}/plaetze")
async def plaetze_setzen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, kennung = dienst_von(request), pfad_id(termin_id)
    plaetze = plaetze_pruefen(await json_objekt(request))
    async with dienst.schreiben(zugang, "werkstatt_plaetze_setzen") as (tx, buchung):
        await _termin(tx, kennung)
        await tx.plaetze_setzen(kennung, plaetze)
        buchung.params = {"termin": kennung}
        buchung.ergebnis = {"ok": True, "plaetze": len(plaetze)}
    return {"plaetze": [platz_ausgabe(p) for p in plaetze]}


@router.get("/labor/termine/{termin_id}/checkliste")
async def checkliste_lesen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    db, kennung = dienst_von(request).db, pfad_id(termin_id)
    await _termin(db, kennung)
    return {"punkte": [punkt_ausgabe(p) for p in await db.checkliste(kennung)]}


@router.post("/labor/termine/{termin_id}/checkliste", status_code=201)
async def checkliste_anlegen(termin_id: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, kennung = dienst_von(request), pfad_id(termin_id)
    daten = punkt_pruefen(await json_objekt(request))
    async with dienst.schreiben(zugang, "werkstatt_checkliste_anlegen") as (tx, buchung):
        await _termin(tx, kennung)
        if len(await tx.checkliste(kennung)) >= CHECKLISTE_MAX:
            raise ungueltig(f"Die Checkliste ist voll (höchstens {CHECKLISTE_MAX} Punkte).")
        zeile = await tx.checkliste_anlegen(kennung, daten)
        buchung.params = {"termin": kennung, "nr": zeile["nr"]}
    return {"punkt": punkt_ausgabe(zeile)}


@router.patch("/labor/termine/{termin_id}/checkliste/{nr}")
async def checkliste_abhaken(termin_id: str, nr: str, request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst, kennung, nummer = dienst_von(request), pfad_id(termin_id), nummer_lesen(nr)
    erledigt = (await json_objekt(request)).get("erledigt")
    if nummer is None:
        raise WerkstattFehler("nicht_gefunden")
    if not isinstance(erledigt, bool):
        raise ungueltig("Erledigt muss wahr oder falsch sein.")
    async with dienst.schreiben(zugang, "werkstatt_checkliste_abhaken") as (tx, buchung):
        zeile = await tx.checkliste_abhaken(kennung, nummer, erledigt, zugang.user_id)
        if zeile is None:
            raise WerkstattFehler("nicht_gefunden")
        buchung.params = {"termin": kennung, "nr": nummer}
        buchung.ergebnis = {"ok": True, "erledigt": erledigt}
    return {"punkt": punkt_ausgabe(zeile)}
