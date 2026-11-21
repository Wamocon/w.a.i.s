"""Journal der Werkstatt (Marke wamo-werkstatt): Zeilen ohne Inhalte.

Jede Zeile hat die Form "wamo-werkstatt: <ereignis> schluessel=wert ...". Werte sind kurze Kennungen aus einem festen Zeichensatz,
alles andere wird zu "?". So gelangen nie Eingaben, Namen, Texte, Token oder Pfade mit Abfrage ins Journal, auch nicht aus Versehen.
Die Marke setzt zusätzlich die systemd-Unit (SyslogIdentifier), die Zeilen tragen sie zur Sicherheit auch im Text.
"""

from __future__ import annotations

import logging
import re

MARKE = "wamo-werkstatt"
_SICHER = re.compile(r"[A-Za-z0-9._:/{}@=-]{1,80}")
_log = logging.getLogger(MARKE)


def _wert(wert: object) -> str:
    text = "-" if wert is None else str(wert)
    return text if _SICHER.fullmatch(text) else "?"


def ereignis(name: str, *, stufe: int = logging.INFO, **felder: object) -> None:
    """Schreibt eine Zeile. name ist ein fester Bezeichner aus dem Code, felder sind Kennungen oder Zahlen."""
    teile = " ".join(f"{schluessel}={_wert(wert)}" for schluessel, wert in felder.items())
    _log.log(stufe, "%s: %s%s", MARKE, _wert(name), f" {teile}" if teile else "")


def einrichten(stufe: int = logging.INFO) -> None:
    """Journal auf stderr, eine Zeile je Ereignis (systemd hängt Zeit und Marke an)."""
    kopf = logging.StreamHandler()
    kopf.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _log.handlers[:] = [kopf]
    _log.setLevel(stufe)
    _log.propagate = False
