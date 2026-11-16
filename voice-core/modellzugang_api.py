"""Modellzugang über HTTP, ohne laufendes Gespräch (neben der RTVI-Nachricht "modellzugang" in einer Sitzung).

Wofür: Wer seinen Claude-API-Schlüssel, seinen Claude-Code-Token oder die Modellwahl einstellen will, muss dafür kein
Gespräch starten. Die Oberfläche nutzt diese Routen, solange keine Sitzung läuft, und die Nachricht der Sitzung, sobald
eine läuft. Beide Wege rufen dieselbe Funktion (modellzugang.modellzugang_nachricht) und liefern dieselbe Antwort.

  GET  /wamo/api/modellzugang   Stand des eigenen Profils (nur "hinterlegt" und die letzten vier Zeichen)
  POST /wamo/api/modellzugang   {"aktion": "hinterlegen" | "loeschen" | "modus" | "stimme" | "status",
                                 "schluesselart": "api" | "code", "schluessel": ..., "workspace": ..., "modus": ...,
                                 "stt": "soniox" | "haus", "tts": "soniox" | "haus"}

Sicherheit
  * Wie alle Routen unter /wamo/api: Token mit zweitem Faktor (aal2), Höchstalter der Anmeldung, aktives Profil
    (wamo_api.identitaet). Die Profil-ID kommt nur aus der geprüften Identität, nie aus dem Body.
  * Nie für Laborprofile: Die Laborsperre der Middleware (labor.pfad_pruefen) lässt den Pfad nicht durch; die Route lehnt
    zusätzlich selbst mit 403 und dem Code labor_pfad_gesperrt ab, bevor sie etwas liest oder schreibt.
  * Die Wahl von Hören und Stimme (aktion stimme) schickt keine Daten an einen anderen Dienst; sie entscheidet nur, wohin die
    nächste Sitzung Audio und Antworttext schickt (Soniox in der EU oder das Gateway im Haus).
  * Der Body (höchstens 8 KB) wird nie geloggt und nie zurückgegeben; Antworten enthalten weder Schlüssel noch Token.
    Fehler (Format, Anthropic lehnt ab, Datenbank) stehen als Text in "fehler" der Antwort, nicht als Ausnahme mit Inhalt.
  * Die Begrenzungen gelten auch hier (je Profil und Prozess): Testanfragen beim Hinterlegen 5 je 10 Minuten, Modellwahl (aktion
    modell, mit einer Testanfrage je Claude-Modell) 10 je 10 Minuten, Hören, Stimme und Stimme im Haus zusammen 10 je 10 Minuten.
  * Aktionen modell ({"bereich", "modell"}) und haus_stimme ({"stimme"}): nur Werte aus festen Listen des Kerns (modellwahl.py,
    sprache_anbieter.HAUS_STIMMEN); alles andere wird mit einem Satz abgelehnt.
  * Cache-Control: no-store.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

import labor
import modellzugang as mz
from wamo_api import identitaet, lies_json

router = APIRouter()
MAX_BODY_BYTES = 8 * 1024  # ein Schlüssel ist unter 300 Zeichen lang


def _labor_gesperrt() -> JSONResponse:
    """Laborprofile nie (zweite Sperre hinter der Middleware, F4): 403 mit Code, wie die übrigen Laborpfade."""
    return JSONResponse({"detail": "Für Laborprofile gesperrt", "code": labor.CODE_PFAD_GESPERRT}, status_code=403,
                        headers={"Cache-Control": "no-store"})


async def _ausfuehren(user_id: str, data: dict) -> dict:
    """Führt die Aktion aus und liefert die Nachricht, die sonst über RTVI an die Oberfläche ginge."""
    antworten: list[dict] = []

    async def senden(nachricht: dict) -> None:
        antworten.append(nachricht)

    await mz.modellzugang_nachricht(user_id, data, senden)
    if not antworten:  # nie ohne Antwort
        logger.error("Modellzugang-API: keine Antwort für Profil {}", user_id[:8])
        return {"type": "modellzugang", "aktion": "status", "fehler": "Unerwarteter Fehler, bitte später noch einmal"}
    return antworten[-1]


@router.get("/modellzugang", response_model=None)
async def stand(request: Request, response: Response) -> dict | JSONResponse:
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _labor_gesperrt()
    response.headers["Cache-Control"] = "no-store"
    return await _ausfuehren(ich.user_id, {"aktion": "status"})


@router.post("/modellzugang", response_model=None)
async def aendern(request: Request, response: Response) -> dict | JSONResponse:
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _labor_gesperrt()
    response.headers["Cache-Control"] = "no-store"
    data = await lies_json(request, MAX_BODY_BYTES)
    return await _ausfuehren(ich.user_id, data)
