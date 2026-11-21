"""Drosselung: höchstens N Abrufe je Fenster und Person (Standard 60 je Minute).

Die Zählung liegt im Speicher dieses Prozesses und überlebt keinen Neustart. Sie läuft auf einer monotonen Uhr, damit ein Sprung der
Systemuhr den Zähler nicht zurücksetzt. Der Speicher ist begrenzt: Personen ohne Abruf im Fenster werden regelmäßig entfernt.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from .fehler import WerkstattFehler

ABRUFE = 60
FENSTER_S = 60.0
AUFRAEUMEN_AB = 256  # ab so vielen Einträgen werden leere entfernt


class Drossel:
    def __init__(self, abrufe: int = ABRUFE, fenster_s: float = FENSTER_S, mono: Callable[[], float] = time.monotonic):
        self.abrufe, self.fenster_s, self._mono = abrufe, fenster_s, mono
        self._zeiten: dict[str, deque[float]] = {}

    def pruefen(self, person: str) -> None:
        """Zählt einen Abruf. Wirft zu_oft, wenn die Person im Fenster schon so viele hatte (der abgewiesene Abruf zählt nicht mit)."""
        jetzt = self._mono()
        zeiten = self._zeiten.setdefault(person, deque())
        while zeiten and jetzt - zeiten[0] >= self.fenster_s:
            zeiten.popleft()
        if len(zeiten) >= self.abrufe:
            warte = max(1, int(self.fenster_s - (jetzt - zeiten[0])) + 1)
            raise WerkstattFehler("zu_oft", warte_s=warte)
        zeiten.append(jetzt)
        if len(self._zeiten) > AUFRAEUMEN_AB:
            for schluessel in [k for k, z in self._zeiten.items() if not z or jetzt - z[-1] >= self.fenster_s]:
                del self._zeiten[schluessel]
