"""Claude-Zugang des Testlabors für Admins (Paket LABOR-ZUGANG, Migration 0032; Logik in labor_zugang.py).

  GET    /wamo/api/admin/labor-zugang   Stand: quelle (gespeichert, server, keiner), endet_auf, workspace, gesetzt_am, geprueft_am, hinweis
  PUT    /wamo/api/admin/labor-zugang   {"schluessel": "sk-ant-api...", "workspace": "wrkspc_..." (optional)}: prüfen und speichern
  DELETE /wamo/api/admin/labor-zugang   entfernt den gespeicherten Schlüssel, danach gilt wieder der Schlüssel des Servers

Die Oberfläche der Werkstatt spricht dafür mit dem Kern, nicht mit dem Werkstatt-Dienst: Der Dienst bleibt ohne Geheimnisse.

Sicherheit
  * Wie alle Routen unter /wamo/api: Token mit zweitem Faktor (aal2), Höchstalter der Anmeldung, aktives Profil (wamo_api.identitaet).
  * Nur Admins ohne Laborprofil (Identity.is_admin). Ein Laborprofil bekommt 403 mit dem Code labor_pfad_gesperrt, bevor etwas gelesen
    wird; die Laborsperre der Middleware lässt den Pfad ohnehin nicht durch.
  * Schreibende Aufrufe (PUT, DELETE) brauchen einen frischen zweiten Faktor: der Code der Authenticator-App höchstens 60 Sekunden alt
    (Zeitstempel des letzten totp-Eintrags im Claim amr, wie geraete_admin_api.aal2_zeit; die Oberfläche fragt den Code dafür ab). Sonst
    403 mit dem Code zweiter_faktor_zu_alt, und der Body wird nicht einmal gelesen.
  * Höchstens 5 Schreibversuche je Admin in 10 Minuten (jede Testanfrage geht an Anthropic), Abrufe 30 je Minute.
  * Der Body (höchstens 4 KiB) wird nie geloggt und nie zurückgegeben. Es gibt kein Datenmodell mit Eingabewert: Eine Validierung, die den
    Wert in einer 422 zurückspiegelt, kann es nicht geben (lies_json). Antworten enthalten den Schlüssel nie, auch nicht gekürzt (nur
    "endet auf"); Ausnahmen aus Datenbank oder Bibliothek werden nur nach Art ins Log geschrieben.
  * Fehler als {"code", "text"} (dazu "detail" mit demselben Text, den lib/kernApi.ts anzeigt), immer mit Cache-Control: no-store.
  * Jedes Setzen und Entfernen steht als Zeile in actions (labor_zugang_setzen, labor_zugang_entfernen), nie mit dem Wert.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

import labor
import labor_zugang as lz
from geraete_admin_api import ZUKUNFT_SECS, aal2_zeit  # dieselbe Quelle für den Zeitpunkt des zweiten Faktors wie die Geräteverwaltung
from wamo_api import bearer, identitaet, lies_json

router = APIRouter()
PFAD = "/admin/labor-zugang"
MAX_BODY_BYTES = 4 * 1024  # ein Schlüssel ist unter 300 Zeichen lang
LISTE_GRENZE = (30, 60.0)  # Abrufe je Fenster in Sekunden, je Admin
SCHREIB_GRENZE = (5, 600.0)  # Schreibversuche je Fenster in Sekunden, je Admin
FAKTOR_FRISCH_SECS = 60.0
CODE_FAKTOR_ALT = "zweiter_faktor_zu_alt"
CODE_NICHT_BERECHTIGT = "nicht_berechtigt"
CODE_ZU_OFT = "zu_oft"
SATZ_ADMIN = "Den Claude-Zugang des Labors stellen nur Admins ein."
SATZ_FAKTOR_ALT = "Bitte gib den Code deiner Authenticator-App noch einmal ein. Er darf höchstens eine Minute alt sein."
SATZ_ZU_OFT = "Zu viele Versuche. Bitte warte ein paar Minuten und versuche es dann noch einmal."

_abrufe: dict[str, deque[float]] = {}
_schreibversuche: dict[str, deque[float]] = {}


def _antwort(status: int, code: str, text: str) -> JSONResponse:
    return JSONResponse({"code": code, "text": text, "detail": text}, status_code=status, headers={"Cache-Control": "no-store"})


def _bremse(speicher: dict[str, deque[float]], admin: str, grenze: tuple[int, float], jetzt: float | None = None) -> bool:
    """True: dieser Versuch zählt und ist erlaubt. Höchstens grenze[0] Versuche je Admin im Fenster grenze[1]."""
    anzahl, fenster = grenze
    jetzt = time.monotonic() if jetzt is None else jetzt
    q = speicher.setdefault(admin, deque())
    while q and jetzt - q[0] > fenster:
        q.popleft()
    if len(q) >= anzahl:
        return False
    q.append(jetzt)
    if len(speicher) > 200:  # abgelaufene Admins aufräumen
        for k in [k for k, d in speicher.items() if not d or jetzt - d[-1] > fenster]:
            del speicher[k]
    return True


def faktor_frisch(zeit: float | None, jetzt: float | None = None) -> bool:
    """Ist der zweite Faktor höchstens 60 Sekunden alt (und nicht aus der Zukunft)?"""
    if zeit is None:
        return False
    jetzt = time.time() if jetzt is None else jetzt
    return -ZUKUNFT_SECS <= jetzt - zeit <= FAKTOR_FRISCH_SECS


async def _admin(request: Request):
    """(Identität, None) für einen Admin ohne Laborprofil, sonst (None, Antwort). Anmeldefehler wirft identitaet selbst."""
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return None, _antwort(403, labor.CODE_PFAD_GESPERRT, "Für Laborprofile gesperrt")
    if not ich.is_admin:
        return None, _antwort(403, CODE_NICHT_BERECHTIGT, SATZ_ADMIN)
    return ich, None


def _schreiben_erlaubt(request: Request, admin: str) -> JSONResponse | None:
    """None, wenn ein Schreibaufruf weitergehen darf, sonst die Ablehnung: erst der frische zweite Faktor, dann die Bremse."""
    if not faktor_frisch(aal2_zeit(bearer(request))):
        logger.info("Labor-Zugang: Änderung von Admin {} abgelehnt, zweiter Faktor zu alt", admin[:8])
        return _antwort(403, CODE_FAKTOR_ALT, SATZ_FAKTOR_ALT)
    if not _bremse(_schreibversuche, admin, SCHREIB_GRENZE):
        return _antwort(429, CODE_ZU_OFT, SATZ_ZU_OFT)
    return None


@router.get(PFAD, response_model=None)
async def lesen(request: Request) -> JSONResponse:
    ich, abgelehnt = await _admin(request)
    if abgelehnt is not None:
        return abgelehnt
    if not _bremse(_abrufe, ich.user_id, LISTE_GRENZE):
        return _antwort(429, CODE_ZU_OFT, SATZ_ZU_OFT)
    try:
        stand = await lz.stand()
    except lz.LaborZugangFehler as e:
        return _antwort(e.status, e.code, e.text)
    except Exception as e:  # noqa: BLE001 (nie eine Ausnahme mit Inhalt nach außen)
        logger.error("Labor-Zugang: Abruf fehlgeschlagen ({})", type(e).__name__)
        return _antwort(500, "intern", "Der Stand ist gerade nicht lesbar.")
    return JSONResponse(stand.daten(), headers={"Cache-Control": "no-store"})


@router.put(PFAD, response_model=None)
async def setzen(request: Request) -> JSONResponse:
    ich, abgelehnt = await _admin(request)
    if abgelehnt is not None:
        return abgelehnt
    if (nein := _schreiben_erlaubt(request, ich.user_id)) is not None:
        return nein
    daten = await lies_json(request, MAX_BODY_BYTES)
    try:
        stand = await lz.setzen(ich.user_id, daten.get("schluessel"), daten.get("workspace"))
    except lz.LaborZugangFehler as e:
        return _antwort(e.status, e.code, e.text)
    except Exception as e:  # noqa: BLE001 (der Schlüssel ist in diesem Rahmen im Speicher: nur die Art des Fehlers geht ins Log)
        logger.error("Labor-Zugang: Setzen fehlgeschlagen ({})", type(e).__name__)
        return _antwort(500, "intern", "Das Speichern ist fehlgeschlagen. Bitte den Stand prüfen und noch einmal versuchen.")
    return JSONResponse(stand.daten(), headers={"Cache-Control": "no-store"})


@router.delete(PFAD, response_model=None)
async def entfernen(request: Request) -> JSONResponse:
    ich, abgelehnt = await _admin(request)
    if abgelehnt is not None:
        return abgelehnt
    if (nein := _schreiben_erlaubt(request, ich.user_id)) is not None:
        return nein
    try:
        stand = await lz.entfernen(ich.user_id)
    except lz.LaborZugangFehler as e:
        return _antwort(e.status, e.code, e.text)
    except Exception as e:  # noqa: BLE001
        logger.error("Labor-Zugang: Entfernen fehlgeschlagen ({})", type(e).__name__)
        return _antwort(500, "intern", "Das Entfernen ist fehlgeschlagen. Bitte den Stand prüfen und noch einmal versuchen.")
    return JSONResponse(stand.daten(), headers={"Cache-Control": "no-store"})
