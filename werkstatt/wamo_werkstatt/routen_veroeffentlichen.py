"""Veröffentlichen des Kartenkatalogs in vier Schritten: Prüfen, Freigabekarte, zweiter Faktor, Ausführen.

Die Freigabekarte gilt fünf Minuten, einmal, nur für den Admin, der sie angelegt hat. Sie trägt Zahl und Nummern der Änderungen und
einen Fingerabdruck des ganzen Katalogs (nie Texte). Wer sie ausführt, braucht einen Code des zweiten Faktors, der höchstens 60 Sekunden
alt ist. Das Ausführen ist EINE Transaktion: neue Version mit Momentaufnahme anlegen, bisherige Version auf inaktiv, neue auf aktiv,
alle Entwürfe auf veröffentlicht, Karte verbrauchen und eine Zeile in actions (Risiko critical, ohne Texte). Geht ein Schritt schief,
gilt keiner. Ist der Katalog seit der Karte geändert worden, lehnt das Ausführen mit konflikt ab.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from . import protokoll
from .anmeldung import Zugang
from .daten import Verbindung
from .dienst import RISIKO_KRITISCH, dienst_von, zugang_frisch, zugang_pruefen
from .eingabe import pfad_id
from .fehler import WerkstattFehler
from .karten_regeln import (AKTION_VEROEFFENTLICHEN, KATALOG_BUDGET_ZEICHEN, STAND_ENTWURF, fingerabdruck, momentaufnahme, pruefen,
                            sortierschluessel)

router = APIRouter()
GILT_S = 295  # unter fünf Minuten, die Datenbank erzwingt die Grenze von 300 Sekunden
PROBLEME_IM_SATZ = 3


def _satz(probleme: list[str]) -> str:
    return "Die Prüfung ist nicht bestanden: " + " ".join(probleme[:PROBLEME_IM_SATZ])


@router.post("/karten/pruefen")
async def karten_pruefen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    karten = await dienst.db.karten()
    probleme, gesamt = pruefen(karten)
    entwuerfe = sorted((k["id"] for k in karten if k["stand"] == STAND_ENTWURF), key=sortierschluessel)
    return {"ok": not probleme, "probleme": probleme, "zeichen": gesamt, "grenze": KATALOG_BUDGET_ZEICHEN, "entwuerfe": entwuerfe}


@router.post("/karten/karte", status_code=201)
async def karte_anlegen(request: Request, zugang: Zugang = Depends(zugang_pruefen)) -> dict:
    dienst = dienst_von(request)
    async with dienst.schreiben(zugang, "werkstatt_karten_karte") as (tx, buchung):
        karten = await tx.karten()
        probleme, gesamt = pruefen(karten)
        if probleme:
            raise WerkstattFehler("ungueltig", _satz(probleme))
        nummern = sorted((k["id"] for k in karten if k["stand"] == STAND_ENTWURF), key=sortierschluessel)
        ziel = {"aenderungen": len(nummern), "karten": nummern, "stand": fingerabdruck(karten)}
        karte = await tx.freigabekarte_anlegen(zugang.user_id, AKTION_VEROEFFENTLICHEN, ziel, GILT_S)
        buchung.params = {"karte": karte.id, "aenderungen": len(nummern)}
        basis = await tx.aktive_version()
    return {"karte": {"id": karte.id, "gilt_bis": karte.gilt_bis.isoformat(), "aenderungen": len(nummern), "karten": nummern,
                      "basis_version": basis, "zeichen": gesamt, "grenze": KATALOG_BUDGET_ZEICHEN}}


async def _ausfuehren(tx: Verbindung, zugang: Zugang, kennung: str) -> tuple[int, int, int]:
    """Der Ablauf in einer Transaktion. Gibt Version, Zeichenzahl und Zahl der Änderungen zurück."""
    karte = await tx.freigabekarte_sperren(kennung)
    if karte is None or karte.aktion != AKTION_VEROEFFENTLICHEN:
        raise WerkstattFehler("nicht_gefunden")
    if karte.admin != zugang.user_id:
        raise WerkstattFehler("nicht_berechtigt", "Diese Karte gehört einem anderen Admin.")
    if karte.ausgefuehrt:
        raise WerkstattFehler("karte_verbraucht")
    if karte.abgelaufen:
        raise WerkstattFehler("karte_abgelaufen")
    karten = await tx.karten(sperren=True)
    if fingerabdruck(karten) != karte.ziel.get("stand"):
        raise WerkstattFehler("konflikt", "Der Katalog hat sich seit der Karte geändert. Bitte prüfe neu und lege eine neue Karte an.")
    probleme, gesamt = pruefen(karten)
    if probleme:
        raise WerkstattFehler("ungueltig", _satz(probleme))
    entwuerfe = [k["id"] for k in karten if k["stand"] == STAND_ENTWURF]
    version = await tx.version_anlegen(zugang.user_id, len(entwuerfe), gesamt, momentaufnahme(karten))
    # Nur die geprüften Entwürfe: eine Karte, die ein anderer Admin gerade neu anlegt (die Zeilensperre sieht sie nicht), bleibt Entwurf
    if await tx.entwuerfe_veroeffentlichen(entwuerfe) != len(entwuerfe):
        raise WerkstattFehler("konflikt", "Der Katalog hat sich während des Veröffentlichens geändert. Bitte prüfe neu und lege eine neue Karte an.")
    if not await tx.freigabekarte_verbrauchen(kennung):
        raise WerkstattFehler("karte_verbraucht")
    return version, gesamt, len(entwuerfe)


@router.post("/karten/karte/{karte}/ausfuehren")
async def ausfuehren(karte: str, request: Request, zugang: Zugang = Depends(zugang_frisch)) -> dict:
    dienst, kennung = dienst_von(request), pfad_id(karte)
    try:
        async with dienst.schreiben(zugang, "werkstatt_karten_veroeffentlichen", risiko=RISIKO_KRITISCH) as (tx, buchung):
            version, gesamt, aenderungen = await _ausfuehren(tx, zugang, kennung)
            buchung.params = {"karte": kennung, "version": version, "aenderungen": aenderungen}
            buchung.ergebnis = {"ok": True, "version": version, "zeichen": gesamt}
    except WerkstattFehler as e:
        protokoll.ereignis("veroeffentlichen_abgelehnt", admin=zugang.kurz, code=e.code)
        raise
    protokoll.ereignis("veroeffentlicht", admin=zugang.kurz, version=version, aenderungen=aenderungen, zeichen=gesamt)
    return {"version": version, "zeichen": gesamt}
