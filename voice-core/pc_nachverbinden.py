"""Zugang zum eigenen Laptop nachholen, wenn der Tunnel erst nach dem Sitzungsstart steht (Büro-Kern, WAMO_PC_REGISTER=an).

Befund 15.11.2026: Die Desktop-App startete die Sitzung 18 Sekunden, bevor der Tunnel des Laptops stand. build_session (bot.py) fragte
pc_zugang genau einmal, die Sitzung blieb ohne PC, und jeder Klick auf den Schalter PC-Steuerung endete still in "aus". Dasselbe geschah bei
jedem stillen Start und jedem Neuaufbau des Tunnels.

Regeln:
  * Nachgeholt wird nur für Admins, nie im Labor, nur im Tunnel je Gerät mit Host an und nur, wenn das Register für das Profil ein aktives
    Gerät führt (nachholen_moeglich). Mitglieder und Laborprofile bekommen auf diesem Weg nie PC-Werkzeuge.
  * Ein Versuch ist genau der Weg des Sitzungsstarts (bot.py, pc_nachholen_versuch): pc_zugang mit lies_geheimnisse, host_client nur für
    dieses Gerät, dann start_pc mit Rechnernamen-Abgleich, Gerätewache und Tunnelwächter. PC-Sperre, Stimmabdruck-Gate und das Gate der
    PC-Werkzeuge gelten unverändert; eingeschaltet wird nur per Klick der Person.
  * Höchstens ein Versuch gleichzeitig. Zwischen dem Ende eines Versuchs und dem nächsten liegen mindestens ABSTAND_SECS; ein Klick in
    dieser Zeit bekommt das Ergebnis des letzten Versuchs.
  * Im Hintergrund: erster Versuch nach ERSTE_SECS, dann alle SCHNELL_SECS in der ersten Minute, danach alle LANGSAM_SECS, höchstens
    DAUER_SECS nach dem Sitzungsstart. Danach meldet die Sitzung den PC als getrennt, Nachholen geht dann nur noch per Klick.
  * Nichts nach dem Ende der Sitzung und nichts nach einem Entzug des Geräts (aktiv() ist dann False). Ein Erfolg gilt für die ganze
    Sitzung, danach übernehmen Tunnelwächter und Gerätewache wie beim normalen Start.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from loguru import logger

import labor
from pc_geraet import geraet_erwartet
from pc_host import pc_host_enabled, register_modus

ERSTE_SECS = 3.0
SCHNELL_SECS = 5.0
SCHNELL_BIS_SECS = 60.0
LANGSAM_SECS = 15.0
DAUER_SECS = 180.0
ABSTAND_SECS = 2.0
HINWEIS_SECS = 20.0  # so oft höchstens sagt die Sitzung den Satz unten (wiederholte Klicks)
HINWEIS_NICHT_VERBUNDEN = "Der Laptop ist noch nicht verbunden. Läuft die Desktop-App?"


async def nachholen_moeglich(identity, *, zugang_da: bool, register=None) -> bool:
    """Soll diese Sitzung den Zugang zu IHREM Laptop nachholen? Nur Admin, nie Labor, nur im Tunnel je Gerät mit Host an, nur ohne
    Zugang beim Start und nur mit aktivem Gerät im Register. Die billigen Prüfungen zuerst: Register nur, wenn alle anderen passen."""
    if zugang_da or labor.ist_labor(identity) or not getattr(identity, "is_admin", False):
        return False
    if not (register_modus() and pc_host_enabled()):
        return False
    return await geraet_erwartet(identity, register)


class PcNachholer:
    """Holt den Zugang einer Sitzung nach: per Klick (versuchen) und im Hintergrund (hintergrund). versuch ist der Aufbau aus bot.py und
    liefert True, sobald der Zugang steht; aktiv sagt, ob die Sitzung noch läuft und das Gerät nicht entzogen ist. Uhr und Schlaf sind
    für die Tests austauschbar; ohne Angabe gelten die Werte des Moduls zum Zeitpunkt des Baus."""

    def __init__(self, versuch: Callable[[], Awaitable[bool]], *, aktiv: Callable[[], bool], erste: float | None = None,
                 schnell: float | None = None, schnell_bis: float | None = None, langsam: float | None = None,
                 dauer: float | None = None, abstand: float | None = None, hinweis_abstand: float | None = None,
                 uhr: Callable[[], float] = time.monotonic, schlaf: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._versuch, self._aktiv, self._uhr, self._schlaf = versuch, aktiv, uhr, schlaf
        self._erste = ERSTE_SECS if erste is None else erste
        self._schnell = SCHNELL_SECS if schnell is None else schnell
        self._schnell_bis = SCHNELL_BIS_SECS if schnell_bis is None else schnell_bis
        self._langsam = LANGSAM_SECS if langsam is None else langsam
        self._dauer = DAUER_SECS if dauer is None else dauer
        self._abstand = ABSTAND_SECS if abstand is None else abstand
        self._hinweis_abstand = HINWEIS_SECS if hinweis_abstand is None else hinweis_abstand
        self._sperre = asyncio.Lock()
        self._letztes_ende: float | None = None
        self._letzter_hinweis: float | None = None
        self.verbunden = False
        self.versuche = 0

    async def versuchen(self) -> bool:
        """Ein Versuch, wenn keiner läuft und der letzte lange genug her ist. Ein zweiter Aufruf wartet auf den laufenden und bekommt
        dessen Ergebnis. True, sobald der Zugang steht (dann für den Rest der Sitzung)."""
        if self.verbunden:
            return True
        if not self._aktiv():
            return False
        async with self._sperre:
            if self.verbunden:
                return True
            if not self._aktiv():
                return False
            if self._letztes_ende is not None and self._uhr() - self._letztes_ende < self._abstand:
                return False
            self.versuche += 1
            try:
                ok = await self._versuch()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 (ein gescheiterter Versuch ist kein Grund, die Sitzung zu stören)
                logger.warning("WAMO-GERAET Nachholen des Zugangs gescheitert ({})", type(e).__name__)
                ok = False
            finally:
                self._letztes_ende = self._uhr()
            self.verbunden = bool(ok)
            return self.verbunden

    async def hintergrund(self, am_ende: Callable[[], Awaitable[None]]) -> None:
        """Versuche nach dem Zeitplan des Moduls, bis der Zugang steht, die Sitzung endet oder die Dauer um ist (dann am_ende)."""
        beginn = self._uhr()
        pause = self._erste
        while self._uhr() - beginn + pause <= self._dauer:
            await self._schlaf(pause)
            if not self._aktiv():
                return
            if await self.versuchen():
                return
            pause = self._schnell if self._uhr() - beginn < self._schnell_bis else self._langsam
        if self._aktiv() and not self.verbunden:
            logger.info("WAMO-GERAET Zugang in {:.0f} s nicht nachgeholt: PC getrennt, weiter nur per Klick", self._dauer)
            await am_ende()

    def hinweis_faellig(self) -> bool:
        """Darf die Sitzung den Satz HINWEIS_NICHT_VERBUNDEN jetzt sagen? Höchstens einmal je hinweis_abstand."""
        jetzt = self._uhr()
        if self._letzter_hinweis is not None and jetzt - self._letzter_hinweis < self._hinweis_abstand:
            return False
        self._letzter_hinweis = jetzt
        return True
