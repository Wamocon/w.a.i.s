"""Die Anwendung: FastAPI mit festem Fehlerbild, Schutzkopfzeilen, CORS nur für die Oberfläche und Journalzeilen ohne Inhalte.

Es gibt keine Oberfläche der Schnittstellen-Dokumentation (kein /docs, kein /openapi.json). Jeder unbekannte Pfad ist 404, jede falsche
Methode ebenfalls (nicht_gefunden), es gibt keine Umleitungen. Jede Antwort trägt Cache-Control: no-store.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import protokoll, routen_basis, routen_karten, routen_labor, routen_veroeffentlichen
from .anmeldung import SchluesselQuelle, TokenPruefer
from .daten import Datenbank, DatenbankFehler, KonfliktFehler, PruefFehler
from .dienst import Dienst
from .fehler import WerkstattFehler
from .konfig import Konfig

AUFRAEUMEN_S = 3600
SCHUTZ_KOEPFE = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)


class SchutzMiddleware:
    """Setzt die Schutzkopfzeilen auf jede Antwort und schreibt eine Journalzeile je Anfrage (Methode, Route ohne Werte, Status,
    Dauer, die ersten acht Zeichen der Admin-Kennung). Nie der Pfad mit Kennungen, nie die Abfrage, nie ein Körper."""

    def __init__(self, app: ASGIApp, mono: Callable[[], float] = time.monotonic):
        self.app, self._mono = app, mono

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        beginn = self._mono()
        gestartet = False

        async def senden(nachricht: Message) -> None:
            nonlocal gestartet
            if nachricht["type"] == "http.response.start":
                gestartet = True
                eigene = {name for name, _ in SCHUTZ_KOEPFE}
                koepfe = [(n, w) for n, w in nachricht.get("headers", []) if n.lower() not in eigene]
                nachricht = {**nachricht, "headers": [*koepfe, *SCHUTZ_KOEPFE]}
                route = scope.get("route")
                protokoll.ereignis("anfrage", methode=scope["method"], route=getattr(route, "path", "unbekannt"),
                                   status=nachricht["status"], ms=int((self._mono() - beginn) * 1000),
                                   admin=scope.get("state", {}).get("admin"))
            await send(nachricht)

        try:
            await self.app(scope, receive, senden)
        except Exception as e:  # noqa: BLE001  nie ein Stapel und nie ein Text nach außen, im Journal nur der Typ
            protokoll.ereignis("fehler", stufe=logging.ERROR, art=type(e).__name__)
            if not gestartet:
                await _antwort(WerkstattFehler("nicht_verfuegbar"))(scope, receive, senden)


def _antwort(fehler: WerkstattFehler) -> JSONResponse:
    koepfe = {"Retry-After": str(fehler.warte_s)} if fehler.warte_s else None
    if fehler.http >= 400 and fehler.code not in ("nicht_angemeldet", "zu_oft"):
        protokoll.ereignis("abgelehnt", code=fehler.code, status=fehler.http)
    return JSONResponse(fehler.koerper(), status_code=fehler.http, headers=koepfe)


async def _fehler_werkstatt(_r: Request, e: WerkstattFehler) -> JSONResponse:
    return _antwort(e)


async def _fehler_konflikt(_r: Request, _e: KonfliktFehler) -> JSONResponse:
    return _antwort(WerkstattFehler("konflikt"))


async def _fehler_pruefung(_r: Request, _e: PruefFehler) -> JSONResponse:
    return _antwort(WerkstattFehler("ungueltig"))


async def _fehler_datenbank(_r: Request, e: DatenbankFehler) -> JSONResponse:
    protokoll.ereignis("datenbank_nicht_erreichbar", stufe=logging.ERROR, art=str(e)[:40])
    return _antwort(WerkstattFehler("nicht_verfuegbar"))


async def _fehler_eingabe(_r: Request, _e: RequestValidationError) -> JSONResponse:
    return _antwort(WerkstattFehler("ungueltig"))


async def _fehler_http(_r: Request, _e: HTTPException) -> JSONResponse:
    """Unbekannter Pfad und falsche Methode: beides nicht_gefunden (kein Hinweis, welche Pfade es gibt)."""
    return _antwort(WerkstattFehler("nicht_gefunden"))


async def _aufraeumen(dienst: Dienst) -> None:
    """Räumt abgelaufene Freigabekarten auf (werkstatt_aufraeumen): beim Start und danach stündlich."""
    while True:
        try:
            await dienst.db.aufraeumen()
        except Exception as e:  # noqa: BLE001  der Dienst läuft weiter, im Journal steht nur der Typ
            protokoll.ereignis("aufraeumen_fehlgeschlagen", stufe=logging.WARNING, art=type(e).__name__)
        await asyncio.sleep(AUFRAEUMEN_S)


def create_app(konfig: Konfig, db: Datenbank, quelle: SchluesselQuelle, *, uhr: Callable[[], float] = time.time,
               mono: Callable[[], float] = time.monotonic, aufraeumen: bool = True) -> FastAPI:
    """Baut die Anwendung. db und quelle (Schlüsselsatz) kommen von außen, damit Tests ohne Datenbank und ohne Netz laufen."""
    dienst = Dienst(konfig, db, TokenPruefer(quelle, aussteller=konfig.issuer, zielgruppe=konfig.audience), uhr=uhr, mono=mono)

    @contextlib.asynccontextmanager
    async def lebenszeit(_app: FastAPI) -> AsyncIterator[None]:
        aufgabe = asyncio.create_task(_aufraeumen(dienst)) if aufraeumen else None
        try:
            yield
        finally:
            if aufgabe is not None:
                aufgabe.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await aufgabe
            await db.schliessen()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False, lifespan=lebenszeit)
    app.state.dienst = dienst
    for router in (routen_basis.router, routen_labor.router, routen_veroeffentlichen.router, routen_karten.router):
        app.include_router(router, prefix=konfig.pfad)
    for art, behandler in ((WerkstattFehler, _fehler_werkstatt), (KonfliktFehler, _fehler_konflikt), (PruefFehler, _fehler_pruefung),
                           (DatenbankFehler, _fehler_datenbank), (RequestValidationError, _fehler_eingabe), (HTTPException, _fehler_http)):
        app.add_exception_handler(art, behandler)
    app.add_middleware(CORSMiddleware, allow_origins=[konfig.herkunft], allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False, max_age=600)
    app.add_middleware(SchutzMiddleware, mono=mono)
    return app
