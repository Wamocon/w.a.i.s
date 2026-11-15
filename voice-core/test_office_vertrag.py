"""Vertragstest zwischen Kern (voice-core/office_werkzeuge.py) und Host (host/office_dateien.py, host/office_ablage.py) für die
Office-Dateien aus dem Canvas.

Beide Seiten halten ihre Listen selbst (der Kern importiert nichts aus dem Host). Weicht eine Seite ab, wird dieser Test rot, nicht
erst der Betrieb: Formate, Formate je Art und die Form der Dateikennung. Die Module des Hosts brauchen beim Laden nur die
Standardbibliothek. Ausführen (im Ordner voice-core/):  python -m pytest -q test_office_vertrag.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import office_werkzeuge as ow

HOST = Path(__file__).resolve().parent.parent / "host"


def _lade(name: str, datei: str):
    spec = importlib.util.spec_from_file_location(name, HOST / datei)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


OD = _lade("office_dateien_vertrag", "office_dateien.py")
OA = _lade("office_ablage_vertrag", "office_ablage.py")


def test_formate_gleich_und_in_derselben_reihenfolge():
    assert ow.FORMATE == OD.FORMATE


def test_formate_je_art_gleich():
    assert {art: tuple(f) for art, f in ow.FORMATE_JE_ART.items()} == {art: tuple(f) for art, f in OD.FORMATE_JE_ART.items()}
    assert set(ow.FORMATE_JE_ART) == set(OD.ARTEN)


def test_jedes_format_hat_eine_endung_und_einen_namen():
    assert set(OA.ENDUNGEN) == set(ow.FORMATE) == set(ow.FORMAT_NAMEN)


def test_dateikennung_gleich():
    assert ow.KENNUNG_RE.pattern == OA.KENNUNG_RE.pattern
