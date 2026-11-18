"""Wertet die Logzeilen des Sprechermodells im Schattenbetrieb aus (voice-core/stimme_schatten.py, WAMO_STIMME_SCHATTEN=an).

Je Äußerung schreibt der Kern eine Zeile nur mit Zahlen, zum Beispiel
  Stimmschatten: titanet=0.512 schatten=0.634 secs=1.42 wamo=0 urteil=eigen ms_titanet=41 ms_schatten=37
Dieses Skript liest solche Zeilen (aus journalctl, der Rest der Zeile stört nicht) und zeigt je Längenklasse (unter 1 s, 1 bis 2 s, ab 2 s):
die Verteilung beider Werte je Gruppe (10-%-Quantil, Median, 90-%-Quantil), die Trennung zwischen eigen und fremd für beide Modelle (AUC:
Anteil der Paare, in denen eine eigene Äußerung höher liegt als eine fremde; EER: Fehlerrate, bei der Fehlannahmen und Fehlabweisungen gleich
häufig sind; d': Abstand der Mittelwerte in Standardabweichungen) und die Rechenzeit (Median und 95-%-Quantil).

Zwei Arten von Gruppen:
- Ohne Optionen (stdin) gelten die Urteile von TitaNet als Gruppen. Vorsicht: Die Gruppen eigen und fremd sind an den Schwellen von TitaNet
  geschnitten, TitaNet trennt sie also immer gut. Aussagekräftig ist dann nur, wie sehr der Schatten mit TitaNet übereinstimmt.
- Mit --eigen DATEI und --fremd DATEI zählt, wer wirklich sprach: Die erste Datei enthält nur Äußerungen der eingelernten Person (zum Beispiel
  eine Sitzung mit Headset allein im Raum), die zweite nur fremde Stimmen (eine andere Person spricht am selben Profil, Modus beobachten). Nur
  diese Trennung taugt für die Entscheidung, ob umgestellt wird.

Aufruf am Server (Lesen des Journals braucht sudo):
  sudo journalctl -u 'wamo-core@*' --since today -o cat | python3 scripts/wamo_stimme_schatten_auswerten.py
  sudo journalctl -u 'wamo-core@*' --since '2026-11-19 10:00' --until '2026-11-19 10:20' -o cat > eigen.log
  python3 scripts/wamo_stimme_schatten_auswerten.py --eigen eigen.log --fremd fremd.log [--ohne-wamo] [--json]
--ohne-wamo lässt Äußerungen weg, während der W.A.I.S. sprach (Echo). Nur Standardbibliothek; es liest nur Zahlen, nie Text oder Ton.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

ZEILE_RE = re.compile(r"Stimmschatten: titanet=(-?\d+(?:\.\d+)?) schatten=(-?\d+(?:\.\d+)?) secs=(\d+(?:\.\d+)?) wamo=([01]) "
                      r"urteil=([a-z]+) ms_titanet=(\d+) ms_schatten=(\d+)")
KLASSEN = ("unter 1 s", "1 bis 2 s", "ab 2 s")
URTEILE = ("eigen", "kurz", "unklar", "fremd")
MODELLE = ("titanet", "schatten")


@dataclass(frozen=True)
class Messung:
    titanet: float
    schatten: float
    secs: float
    wamo: bool
    urteil: str
    ms_titanet: int
    ms_schatten: int


def zeilen_lesen(text: TextIO) -> list[Messung]:
    """Alle Zeilen des Schattens aus einem Text; andere Zeilen und kaputte Zahlen werden übergangen."""
    messungen = []
    for zeile in text:
        treffer = ZEILE_RE.search(zeile)
        if not treffer:
            continue
        t, s, secs, wamo, urteil, mt, ms = treffer.groups()
        werte = (float(t), float(s), float(secs))
        if all(math.isfinite(w) for w in werte):
            messungen.append(Messung(werte[0], werte[1], werte[2], wamo == "1", urteil, int(mt), int(ms)))
    return messungen


def klasse(secs: float) -> str:
    return KLASSEN[0] if secs < 1.0 else KLASSEN[1] if secs < 2.0 else KLASSEN[2]


def quantil(werte: list[float], q: float) -> float | None:
    """Quantil mit linearer Interpolation (wie numpy.quantile), None ohne Werte."""
    if not werte:
        return None
    sortiert = sorted(werte)
    pos = (len(sortiert) - 1) * q
    unten = math.floor(pos)
    oben = min(unten + 1, len(sortiert) - 1)
    return sortiert[unten] + (sortiert[oben] - sortiert[unten]) * (pos - unten)


def verteilung(werte: list[float]) -> dict:
    return {"n": len(werte), "p10": quantil(werte, 0.1), "median": quantil(werte, 0.5), "p90": quantil(werte, 0.9)}


def trennung(eigen: list[float], fremd: list[float]) -> dict | None:
    """AUC, EER und d' zwischen eigenen und fremden Werten; None, wenn eine Seite leer ist."""
    if not eigen or not fremd:
        return None
    auc = _auc(eigen, fremd)
    e_sortiert, f_sortiert = sorted(eigen), sorted(fremd)
    beste = None
    for schwelle in sorted(set(eigen) | set(fremd)):  # angenommen ab schwelle: Fehlannahme fremd >= schwelle, Fehlabweisung eigen < schwelle
        fa = (len(fremd) - bisect.bisect_left(f_sortiert, schwelle)) / len(fremd)
        fr = bisect.bisect_left(e_sortiert, schwelle) / len(eigen)
        if beste is None or abs(fa - fr) < beste[0]:
            beste = (abs(fa - fr), (fa + fr) / 2, schwelle)
    me, mf = sum(eigen) / len(eigen), sum(fremd) / len(fremd)
    ve = sum((x - me) ** 2 for x in eigen) / len(eigen)
    vf = sum((x - mf) ** 2 for x in fremd) / len(fremd)
    streuung = math.sqrt((ve + vf) / 2)
    return {"auc": auc, "eer": beste[1], "schwelle_eer": beste[2], "dprime": (me - mf) / streuung if streuung > 0 else None}


def _auc(eigen: list[float], fremd: list[float]) -> float:
    """Mann-Whitney über Ränge (gleiche Werte bekommen den mittleren Rang): wie der Paarvergleich, aber in n log n."""
    alle = sorted([(w, 1) for w in eigen] + [(w, 0) for w in fremd])
    rang_eigen = 0.0
    i = 0
    while i < len(alle):
        j = i
        while j < len(alle) and alle[j][0] == alle[i][0]:
            j += 1
        mittel = (i + 1 + j) / 2  # Ränge i+1 bis j
        rang_eigen += mittel * sum(marke for _, marke in alle[i:j])
        i = j
    n_e, n_f = len(eigen), len(fremd)
    return (rang_eigen - n_e * (n_e + 1) / 2) / (n_e * n_f)


def auswerten(gruppen: dict[str, list[Messung]], ohne_wamo: bool = False) -> dict:
    """gruppen: Name der Gruppe (eigen, fremd, oder die Urteile von TitaNet) -> Messungen. Ergebnis je Längenklasse."""
    ergebnis: dict = {"klassen": {}}
    for name_klasse in (*KLASSEN, "alle"):
        teil = {g: [m for m in ms if (name_klasse == "alle" or klasse(m.secs) == name_klasse) and not (ohne_wamo and m.wamo)]
                for g, ms in gruppen.items()}
        eintrag: dict = {"gruppen": {}, "trennung": {}, "ms": {}}
        for g, ms in teil.items():
            if ms:
                eintrag["gruppen"][g] = {modell: verteilung([getattr(m, modell) for m in ms]) for modell in MODELLE}
        for modell in MODELLE:
            eintrag["trennung"][modell] = trennung([getattr(m, modell) for m in teil.get("eigen", [])],
                                                   [getattr(m, modell) for m in teil.get("fremd", [])])
        alle = [m for ms in teil.values() for m in ms]
        for modell in MODELLE:
            dauer = [float(getattr(m, f"ms_{modell}")) for m in alle]
            eintrag["ms"][modell] = {"median": quantil(dauer, 0.5), "p95": quantil(dauer, 0.95)}
        ergebnis["klassen"][name_klasse] = eintrag
    return ergebnis


def _zahl(wert: float | None, stellen: int = 2) -> str:
    return "-" if wert is None else f"{wert:.{stellen}f}"


def bericht(ergebnis: dict, wahrheit: bool) -> str:
    zeilen = ["Gruppen: " + ("wer wirklich sprach (--eigen, --fremd)" if wahrheit else
                             "Urteile von TitaNet (eigen und fremd sind an TitaNet geschnitten, siehe Hilfe)")]
    for name_klasse, eintrag in ergebnis["klassen"].items():
        zeilen.append("")
        zeilen.append(f"== {name_klasse}")
        if not eintrag["gruppen"]:
            zeilen.append("  keine Äußerungen")
            continue
        zeilen.append(f"  {'Gruppe':8} {'n':>5}   {'TitaNet p10 / Median / p90':28} {'Schatten p10 / Median / p90':28}")
        for gruppe, werte in eintrag["gruppen"].items():
            t, s = (" / ".join(_zahl(werte[modell][k]) for k in ("p10", "median", "p90")) for modell in MODELLE)
            zeilen.append(f"  {gruppe:8} {werte['titanet']['n']:>5}   {t:28} {s}")
        for modell, name in (("titanet", "TitaNet"), ("schatten", "Schatten")):
            tr = eintrag["trennung"][modell]
            if tr is None:
                zeilen.append(f"  Trennung {name}: zu wenig Daten (eigen und fremd nötig)")
            else:
                zeilen.append(f"  Trennung {name}: AUC {_zahl(tr['auc'], 3)}, EER {_zahl(tr['eer'] * 100, 1)} % bei {_zahl(tr['schwelle_eer'])}, "
                              f"d' {_zahl(tr['dprime'])}")
        ms = eintrag["ms"]
        zeilen.append(f"  Rechenzeit ms (Median / p95): TitaNet {_zahl(ms['titanet']['median'], 0)} / {_zahl(ms['titanet']['p95'], 0)}, "
                      f"Schatten {_zahl(ms['schatten']['median'], 0)} / {_zahl(ms['schatten']['p95'], 0)}")
    return "\n".join(zeilen)


def main(argv: list[str] | None = None, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Logzeilen des Sprechermodells im Schattenbetrieb auswerten")
    parser.add_argument("--eigen", type=Path, help="Logzeilen nur mit der Stimme der eingelernten Person")
    parser.add_argument("--fremd", type=Path, help="Logzeilen nur mit fremden Stimmen")
    parser.add_argument("--ohne-wamo", action="store_true", help="Äußerungen weglassen, während der W.A.I.S. sprach")
    parser.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    args = parser.parse_args(argv)
    aus = stdout or sys.stdout
    if bool(args.eigen) != bool(args.fremd):
        parser.error("--eigen und --fremd nur zusammen")
    if args.eigen:
        with args.eigen.open(encoding="utf-8", errors="replace") as e, args.fremd.open(encoding="utf-8", errors="replace") as f:
            gruppen = {"eigen": zeilen_lesen(e), "fremd": zeilen_lesen(f)}
    else:
        alle = zeilen_lesen(stdin or sys.stdin)
        gruppen = {u: [m for m in alle if m.urteil == u] for u in URTEILE}
        gruppen.update({u: [m for m in alle if m.urteil == u] for u in sorted({m.urteil for m in alle} - set(URTEILE))})
    if not any(gruppen.values()):
        print("Keine Zeilen des Schattens gefunden (Stimmschatten: ...). Ist WAMO_STIMME_SCHATTEN an und neu eingelernt?", file=aus)
        return 1
    ergebnis = auswerten(gruppen, ohne_wamo=args.ohne_wamo)
    print(json.dumps(ergebnis, ensure_ascii=False, indent=2) if args.json else bericht(ergebnis, wahrheit=bool(args.eigen)), file=aus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
