"""Was eine Person je Bereich als Modell wählen darf (Wunsch von Niko vom 16.11.2026, Migration 0024).

Drei Bereiche, je "automatisch" (der Boss wählt, Standard) oder ein Modell aus einer festen Liste:

  gespraech    Gesprächsmodell (Baustein gespraech)
  bilder       Bildschirm und Bilder (Baustein vision)
  hintergrund  Lernen und Zusammenfassung (Bausteine lernen und zusammenfassung, ein Modell für beide)

Die Liste entsteht allein aus der Modellkarte (modellkarte.py) und der Rangliste des Boss (boss.rangliste): nur Modelle mit Status
standard, keine Sprachmodelle, keine Fachmodelle, keine unbekannten Modelle, keine Verweise, und nur solche, die der Boss für die Klasse
überhaupt in Frage zieht (auch als Notlösung, dann steht das in der Zeile). Claude-Modelle stehen nur für einen Zugang mit Claude
(eigener API-Schlüssel oder die Zuordnung des Kernschlüssels) in der Liste: Haiku, Sonnet und Opus wie bei den Entwicklungsaufträgen
(werkzeugkarte.MODELLE_ERLAUBT). Hat ein Admin ein Claude-Modell für das Profil festgelegt, ist es das einzige Claude-Modell.

Der Kern prüft jede Wahl mit gueltig() (modellzugang.modell_setzen beim Setzen, modellzugang.zugang_laden beim Laden); die Oberfläche
bekommt nur die Liste zum Anzeigen. Kein Wert aus der Oberfläche wird je als Spaltenname oder Modellname genutzt, der nicht hier steht.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import boss
import modellkarte as karte
from llm_anbieter import lesbarer_modellname
from werkzeugkarte import MODELLE_ERLAUBT

BEREICHE = ("gespraech", "bilder", "hintergrund")
AUTOMATISCH = "automatisch"
# Spalte in model_access je Bereich (Migration 0024); nur diese drei Namen kommen je in eine Anweisung an die Datenbank
SPALTEN = {"gespraech": "modell_gespraech", "bilder": "modell_bilder", "hintergrund": "modell_hintergrund"}
# Aufgabenklassen des Boss je Bereich; bei mehreren muss ein Modell für alle taugen
KLASSEN = {"gespraech": ("gespraech",), "bilder": ("vision",), "hintergrund": ("lernen", "zusammenfassung")}
# Messwert, der das Tempo einer Klasse am besten beschreibt (Name in der Karte, Text davor)
TEMPO_WERT = {"gespraech": ("ttft_p50_s", "erstes Wort"), "vision": ("vision_s", "je Bild"),
              "lernen": ("lernen_s", "je Durchgang"), "zusammenfassung": ("zusammenfassung_s", "je Zusammenfassung")}
CLAUDE_MODELLE: tuple[str, ...] = MODELLE_ERLAUBT  # Haiku (Standard), Sonnet, Opus
CLAUDE_UNGEMESSEN = {
    "claude-sonnet-5-5": "nicht gemessen, Cloud, deutlich teurer als Haiku (eigenes Guthaben)",
    "claude-opus-5-5": "nicht gemessen, Cloud, am teuersten (eigenes Guthaben)",
}


@dataclass(frozen=True)
class Option:
    id: str  # Alias beim Gateway oder Claude-ID
    name: str
    art: Literal["haus", "claude"]
    zeile: str  # eine Zeile zu Tempo und Güte

    def daten(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "art": self.art, "zeile": self.zeile}


def _zahl(wert: float) -> str:
    return f"{wert:.1f}".replace(".", ",")


def _messwert(m: karte.Modell, faehigkeit: str, name: str) -> float | None:
    e = m.eignungen.get(faehigkeit)
    return next((w.wert for w in (e.messwerte if e else ()) if w.name == name), None)


def zeile(m: karte.Modell, klasse: str, *, notfall: bool = False) -> str:
    """Eine Zeile zu Güte und Tempo aus der Karte, z. B. "Güte 92 %, Tempo mittel (erstes Wort 0,6 s)"."""
    faehigkeit = boss.FAEHIGKEIT[klasse]
    e = m.eignungen[faehigkeit]
    g = e.guete if e.guete is not None else 0.0
    if klasse == "gespraech" and (w := m.eignungen.get("werkzeuge")) is not None and w.guete is not None:
        g = min(g, w.guete)  # wie der Boss: das Schwächere aus Gespräch und Werkzeug-Treue
    name, text = TEMPO_WERT[klasse]
    sekunden = _messwert(m, faehigkeit, name)
    tempo = f"Tempo {e.latenz}" + (f" ({text} {_zahl(sekunden)} s)" if sekunden is not None else "")
    teile = [f"Güte {round(g * 100)} %", tempo]
    if m.datenschutz == "cloud":
        teile.append("Cloud, kostet je Anfrage")
    if notfall:
        teile.append("nur als Notlösung")
    return ", ".join(teile)


def _haus(bereich: str) -> list[Option]:
    klassen = KLASSEN[bereich]
    listen = [boss.rangliste(k, claude_erlaubt=False) for k in klassen]
    ueberall = set.intersection(*({k.alias for k in liste} for liste in listen))
    optionen: list[Option] = []
    for k in listen[0]:
        m = karte.modell(k.alias)
        if k.alias not in ueberall or m is None or m.anbieter != "haus":
            continue
        optionen.append(Option(k.alias, m.anzeige, "haus", zeile(m, klassen[0], notfall=k.notfall)))
    return optionen


def _claude(bereich: str, claude_fest: str | None) -> list[Option]:
    if claude_fest:
        return [Option(claude_fest, lesbarer_modellname(claude_fest), "claude", "vom Admin für dein Profil festgelegt, Cloud")]
    optionen = []
    for alias in CLAUDE_MODELLE:
        m = karte.modell(alias)
        text = zeile(m, KLASSEN[bereich][0]) if m is not None and boss.FAEHIGKEIT[KLASSEN[bereich][0]] in m.eignungen \
            else CLAUDE_UNGEMESSEN.get(alias, "nicht gemessen, Cloud")
        optionen.append(Option(alias, m.anzeige if m else lesbarer_modellname(alias), "claude", text))
    return optionen


def optionen(bereich: str, *, claude: bool, claude_fest: str | None = None) -> list[Option]:
    """Die wählbaren Modelle des Bereichs ohne "automatisch": Claude zuerst (nur mit claude), dann die Hausmodelle in der Reihenfolge
    des Boss. claude_fest: das vom Admin gesetzte Claude-Modell des Profils (dann das einzige Claude-Modell)."""
    if bereich not in BEREICHE:
        raise ValueError(f"unbekannter Bereich {bereich!r}")
    return [*(_claude(bereich, claude_fest) if claude else []), *_haus(bereich)]


def gueltig(bereich: object, wert: object, *, claude: bool, claude_fest: str | None = None) -> bool:
    """Ist wert ein Modell aus der festen Liste dieses Bereichs für diesen Zugang? "automatisch" zählt nicht (kein Modell)."""
    if not isinstance(bereich, str) or bereich not in BEREICHE or not isinstance(wert, str):
        return False
    return any(o.id == wert for o in optionen(bereich, claude=claude, claude_fest=claude_fest))


def anzeige(wert: str) -> str:
    """Lesbarer Name eines Modells für Hinweise ("Claude Sonnet 5.5", "Gemma 4 31B")."""
    return boss.lesbar(wert)
