"""Lesende Endpunkte: ich, betrieb, dashboard, protokolle. Antworten enthalten nur Zahlen, Stände und Zeiten."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, Request

from . import lesen
from .anmeldung import Zugang
from .dienst import dienst_von, zugang_pruefen
from .eingabe import abfrage_ganz, abfrage_wahl
from .fehler import WerkstattFehler

router = APIRouter()
TAGE = dict(minimum=1, maximum=30)
STUNDEN = dict(minimum=1, maximum=168)


@router.get("/ich")
async def ich(zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    return {"rolle": zugang.rolle, "aal2_alter_s": zugang.aal2_alter_s, "erlaubt": True}


@router.get("/betrieb")
async def betrieb(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    stand = await asyncio.to_thread(lesen.betrieb_lesen, dienst.konfig.daten_ordner, dienst.jetzt())
    if stand is None:  # der Sammler hat noch nichts geliefert oder die Datei ist unbrauchbar
        raise WerkstattFehler("nicht_verfuegbar", "Der Sammler hat noch keine Werte geliefert.")
    return stand


@router.get("/dashboard/sitzungen")
async def sitzungen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    tage = abfrage_ganz(request, "tage", 14, **TAGE)
    return {"tage": tage, "zeilen": lesen.sitzungen_zeilen(await dienst_von(request).db.sitzungen(tage))}


@router.get("/dashboard/latenz")
async def latenz(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    tage = abfrage_ganz(request, "tage", 14, **TAGE)
    return {"tage": tage, "zeilen": lesen.latenz_zeilen(await dienst_von(request).db.latenz(tage))}


@router.get("/dashboard/aktionen")
async def aktionen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    tage = abfrage_ganz(request, "tage", 14, **TAGE)
    return {"tage": tage, "zeilen": lesen.aktionen_zeilen(await dienst_von(request).db.aktionen(tage))}


@router.get("/protokolle")
async def protokolle(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    erlaubt = dienst.konfig.marken
    marke = abfrage_wahl(request, "marke", erlaubt)
    stufe = abfrage_wahl(request, "stufe", lesen.STUFEN)
    stunden = abfrage_ganz(request, "stunden", 24, **STUNDEN)
    seit = dienst.jetzt() - timedelta(hours=stunden)
    zeilen = await asyncio.to_thread(lesen.protokolle_lesen, dienst.konfig.daten_ordner, (marke,) if marke else erlaubt,
                                     stufe=stufe, seit=seit)
    return {"stunden": stunden, "marken": list(erlaubt), "stufen": list(lesen.STUFEN), "zeilen": zeilen}
