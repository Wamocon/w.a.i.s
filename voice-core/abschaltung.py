"""Geordnete, begrenzte Abschaltung des Kerns (R7, Ausleiten am 16.11.2026).

Befund: Beim Ausleiten von Slot a hing der Kern 20 s in "Waiting for application shutdown", bis systemd ihn nach
TimeoutStopSec mit SIGKILL beendete (Result=timeout, Zustand failed), obwohl der Slot keine Sitzung mehr hatte.
Ursache ist das Zusammenspiel von Pipecat (1.12) und aiortc (1.15):
  * Eine Neuverhandlung mit Neustart der Peer-Verbindung (restart_pc) gibt der Verbindung eine neue pc_id. Das
    Verzeichnis des SmallWebRTCRequestHandler behält die alte pc_id, beim Schließen fällt nur die aktuelle heraus.
  * Endet die Verbindung über den Verbindungs-Timeout, storniert Pipecats eigener Zustandshandler ("closed") die
    Timeout-Aufgabe mitten in RTCPeerConnection.close(). aiortc setzt seinen Abschluss-Future dann nie, und jedes
    weitere close() wartet für immer darauf.
  * Beim Herunterfahren schließt der Lifespan des Runners alle Einträge des Verzeichnisses, also auch die alten:
    dieses close() kehrt nie zurück.

Darum hat jede Stufe des Herunterfahrens eine Frist, zusammen deutlich unter TimeoutStopSec (20 s):
  * FRIST_VERBINDUNGEN_S: uvicorn wartet so lange auf offene Verbindungen und Sitzungen (timeout_graceful_shutdown)
  * FRIST_LIFESPAN_S: das Ende des ganzen Lifespans (WebRTC-Verbindungen des Runners, eigene Hintergrundaufgaben);
    danach wird es abgebrochen, in derselben Aufgabe (asyncio.timeout), damit Cancel-Scopes und Kontexte stimmen
  * FRIST_AUFGABEN_S: Hintergrundaufgaben aus wamo_api nach ihrem Abbruch
  * FRIST_NOTBREMSE_S: läuft der Prozess so lange nach dem Beginn des Lifespan-Endes noch (eine Aufgabe nimmt den
    Abbruch nicht an, ein Thread hängt), beendet er sich selbst mit Exit 1 und einer Meldung im Journal, statt auf das
    SIGKILL von systemd zu warten. Exit 1 hält den Fall sichtbar (Result=exit-code); wamo-core-slots.sh ausleiten
    meldet ihn und setzt den Zustand zurück.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from loguru import logger

FRIST_VERBINDUNGEN_S = 4
FRIST_LIFESPAN_S = 5.0
FRIST_AUFGABEN_S = 2.0
FRIST_NOTBREMSE_S = 9.0
NOTBREMSE_EXIT = 1
MARKE = "_wamo_abschaltung_begrenzt"


async def aufgaben_beenden(aufgaben: Iterable[asyncio.Future], frist: float) -> int:
    """Bricht die Aufgaben ab und wartet höchstens frist Sekunden. Liefert die Zahl der Aufgaben, die dann noch laufen."""
    liste = [a for a in aufgaben if not a.done()]
    if not liste:
        return 0
    for a in liste:
        a.cancel()
    fertig, offen = await asyncio.wait(liste, timeout=frist)
    for a in fertig:   # abholen, sonst meldet asyncio "exception was never retrieved"
        if not a.cancelled() and a.exception() is not None:
            logger.warning("Abschaltung: Hintergrundaufgabe endete mit {}", type(a.exception()).__name__)
    if offen:
        logger.warning("Abschaltung: {} Hintergrundaufgabe(n) nach {} s nicht beendet; sie enden mit dem Prozess "
                       "(spätestens über die Notbremse)", len(offen), frist)
    return len(offen)


def notbremse_starten(frist: float | None = None, beenden: Callable[[int], object] = os._exit) -> threading.Timer:
    """Daemon-Zeitgeber: lebt der Prozess nach frist Sekunden (Standard FRIST_NOTBREMSE_S) noch, endet er sofort
    (Exit NOTBREMSE_EXIT, Meldung im Journal)."""
    frist = FRIST_NOTBREMSE_S if frist is None else frist

    def ausloesen() -> None:
        try:
            logger.error("Abschaltung: Notbremse, der Prozess läuft {} s nach Beginn des Herunterfahrens noch und endet jetzt sofort", frist)
            sys.stderr.flush()
        finally:
            beenden(NOTBREMSE_EXIT)

    zeitgeber = threading.Timer(frist, ausloesen)
    zeitgeber.name = "wamo-notbremse"
    zeitgeber.daemon = True
    zeitgeber.start()
    return zeitgeber


def _notbremse_sicher(notbremse: Callable[[], object] | None) -> None:
    try:
        (notbremse or notbremse_starten)()
    except Exception as e:  # noqa: BLE001 (ohne Notbremse muss das Aufräumen trotzdem laufen)
        logger.warning("Abschaltung: Notbremse nicht gestartet ({})", type(e).__name__)


async def _ende_begrenzt(cm: Any, ausnahme: BaseException | None, frist: float) -> None:
    """Beendet den Lifespan in derselben Aufgabe; nach frist wird er abgebrochen. Fehler beim Herunterfahren werden protokolliert."""
    art = type(ausnahme) if ausnahme is not None else None
    try:
        async with asyncio.timeout(frist):
            await cm.__aexit__(art, ausnahme, ausnahme.__traceback__ if ausnahme is not None else None)
    except TimeoutError:
        logger.warning("Abschaltung: Lifespan nach {} s nicht fertig (z. B. eine WebRTC-Verbindung schließt nicht), abgebrochen", frist)
    except Exception as e:  # noqa: BLE001 (das Herunterfahren geht weiter, der Fehler steht mit Ablauf im Journal)
        if e is not ausnahme:
            logger.opt(exception=e).error("Abschaltung: Fehler beim Herunterfahren ({})", type(e).__name__)


def lifespan_begrenzen(app: Any, *, frist: float | None = None, notbremse: Callable[[], object] | None = None) -> None:
    """Legt eine Frist um das Ende des vollständig zusammengesetzten Lifespans (erst aufrufen, wenn alle Teile hängen,
    also direkt vor dem Serverstart). Start und Zustand bleiben unverändert. Wiederholte Aufrufe schachteln nicht."""
    router = getattr(app, "router", None)
    innen = getattr(router, "lifespan_context", None)
    if innen is None or getattr(innen, MARKE, False):
        return

    @contextlib.asynccontextmanager
    async def begrenzt(a):
        cm = innen(a)
        zustand = await cm.__aenter__()
        ausnahme: BaseException | None = None
        try:
            yield zustand
        except BaseException as e:
            ausnahme = e
            raise
        finally:
            _notbremse_sicher(notbremse)
            await _ende_begrenzt(cm, ausnahme, FRIST_LIFESPAN_S if frist is None else frist)

    setattr(begrenzt, MARKE, True)
    router.lifespan_context = begrenzt
