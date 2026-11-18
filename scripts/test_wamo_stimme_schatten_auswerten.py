"""Tests für scripts/wamo_stimme_schatten_auswerten.py (Logzeilen des Sprechermodells im Schattenbetrieb auswerten).

Aufruf (aus scripts, mit der Python-Umgebung von voice-core):
  D:\\IDEA\\Projekt\\wamo\\voice-core\\.venv\\Scripts\\python.exe -m pytest -q test_wamo_stimme_schatten_auswerten.py

Reine Rechnung mit erfundenen Zeilen, kein Netz. Die Zeilen haben genau das Format von voice-core/stimme_schatten.ZEILE.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_stimme_schatten_auswerten as aw  # noqa: E402

VOICE_CORE = Path(__file__).resolve().parent.parent / "voice-core"


def zeile(titanet: float, schatten: float, secs: float, urteil: str = "eigen", wamo: int = 0, mt: int = 40, ms: int = 30) -> str:
    """Wie journalctl -o short sie zeigt: Kopf des Journals, Kopf von loguru, dann die Zeile des Kerns."""
    return (f"Nov 19 10:00:00 sokrates2 wamo-core[4242]: 2026-11-19 10:00:00.123 | INFO | stimme_schatten:_rechnen:180 - "
            f"Stimmschatten: titanet={titanet:.3f} schatten={schatten:.3f} secs={secs:.2f} wamo={wamo} urteil={urteil} "
            f"ms_titanet={mt} ms_schatten={ms}\n")


def test_format_passt_zur_zeile_des_kerns():
    sys.path.insert(0, str(VOICE_CORE))
    try:
        import stimme_schatten
    finally:
        sys.path.remove(str(VOICE_CORE))
    text = stimme_schatten.ZEILE.format(0.5123, 0.61, 1.416, 1, "kurz", 41.4, 29.6)
    (m,) = aw.zeilen_lesen(io.StringIO("irgendwas " + text + "\n"))
    assert (m.titanet, m.schatten, m.secs, m.wamo, m.urteil, m.ms_titanet, m.ms_schatten) == (0.512, 0.61, 1.42, True, "kurz", 41, 30)


def test_andere_zeilen_werden_uebergangen():
    text = "Stimme: 0.51 bei 1.4 s -> eigen (Schwelle 0.37)\n" + zeile(0.5, 0.6, 1.2) + "Stimmschatten: übersprungen\n"
    assert len(aw.zeilen_lesen(io.StringIO(text))) == 1


def test_laengenklassen():
    assert [aw.klasse(s) for s in (0.3, 0.99, 1.0, 1.99, 2.0, 7.5)] == ["unter 1 s", "unter 1 s", "1 bis 2 s", "1 bis 2 s", "ab 2 s", "ab 2 s"]


def test_quantil_wie_numpy():
    assert aw.quantil([], 0.5) is None
    assert aw.quantil([3.0], 0.9) == 3.0
    assert aw.quantil([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert aw.quantil([0.0, 10.0], 0.1) == pytest.approx(1.0)


def test_trennung_perfekt_zufall_und_umgekehrt():
    perfekt = aw.trennung([0.6, 0.7, 0.8], [0.1, 0.2, 0.3])
    assert perfekt["auc"] == pytest.approx(1.0) and perfekt["eer"] == pytest.approx(0.0) and perfekt["dprime"] > 3
    gleich = aw.trennung([0.5, 0.5], [0.5, 0.5])
    assert gleich["auc"] == pytest.approx(0.5) and gleich["dprime"] is None
    umgekehrt = aw.trennung([0.1, 0.2], [0.8, 0.9])
    assert umgekehrt["auc"] == pytest.approx(0.0)
    assert aw.trennung([], [0.1]) is None and aw.trennung([0.1], []) is None


def test_auc_ueber_raenge_gleicht_dem_paarvergleich():
    eigen, fremd = [0.4, 0.5, 0.5, 0.7, 0.2], [0.5, 0.1, 0.3, 0.45]
    paare = sum((e > f) + 0.5 * (e == f) for e in eigen for f in fremd) / (len(eigen) * len(fremd))
    assert aw.trennung(eigen, fremd)["auc"] == pytest.approx(paare)


def test_eer_bei_ueberlappung():
    tr = aw.trennung([0.3, 0.5, 0.6, 0.7], [0.1, 0.2, 0.4, 0.55])
    assert 0.0 < tr["eer"] <= 0.5


def test_ohne_optionen_gruppen_nach_urteil_und_je_klasse():
    text = "".join([zeile(0.55, 0.62, 1.4), zeile(0.6, 0.7, 1.6), zeile(0.2, 0.15, 1.3, "fremd"), zeile(0.38, 0.5, 0.6, "kurz"),
                    zeile(0.41, 0.4, 2.4, "unklar", wamo=1)])
    aus = io.StringIO()
    assert aw.main([], stdin=io.StringIO(text), stdout=aus) == 0
    bericht = aus.getvalue()
    assert "Urteile von TitaNet" in bericht
    for teil in ("== unter 1 s", "== 1 bis 2 s", "== ab 2 s", "== alle", "Trennung TitaNet: AUC 1.000", "Trennung Schatten: AUC 1.000",
                 "Rechenzeit ms"):
        assert teil in bericht, teil
    assert "–" not in bericht and "—" not in bericht


def test_json_nach_klassen():
    text = zeile(0.55, 0.62, 1.4) + zeile(0.2, 0.15, 1.3, "fremd") + zeile(0.3, 0.4, 0.5, "kurz", ms=12)
    aus = io.StringIO()
    aw.main(["--json"], stdin=io.StringIO(text), stdout=aus)
    daten = json.loads(aus.getvalue())
    klasse = daten["klassen"]["1 bis 2 s"]
    assert set(klasse["gruppen"]) == {"eigen", "fremd"}
    assert klasse["gruppen"]["eigen"]["schatten"]["median"] == pytest.approx(0.62)
    assert klasse["trennung"]["schatten"]["auc"] == pytest.approx(1.0)
    assert daten["klassen"]["unter 1 s"]["ms"]["schatten"]["median"] == pytest.approx(12.0)
    assert daten["klassen"]["unter 1 s"]["trennung"]["titanet"] is None  # dort nur kurz, kein fremd


def test_wahrheit_aus_zwei_dateien_und_ohne_wamo(tmp_path):
    eigen = tmp_path / "eigen.log"
    fremd = tmp_path / "fremd.log"
    # die eigene Person einmal mit dem Urteil fremd (TitaNet irrte), der Schatten lag richtig
    eigen.write_text(zeile(0.55, 0.6, 1.5) + zeile(0.25, 0.58, 1.2, "fremd") + zeile(0.5, 0.2, 1.4, wamo=1), encoding="utf-8")
    fremd.write_text(zeile(0.3, 0.2, 1.5, "fremd") + zeile(0.28, 0.25, 1.1, "fremd"), encoding="utf-8")
    aus = io.StringIO()
    assert aw.main(["--eigen", str(eigen), "--fremd", str(fremd), "--ohne-wamo", "--json"], stdout=aus) == 0
    tr = json.loads(aus.getvalue())["klassen"]["1 bis 2 s"]["trennung"]
    assert tr["schatten"]["auc"] == pytest.approx(1.0)
    assert tr["titanet"]["auc"] < 1.0
    aus = io.StringIO()
    aw.main(["--eigen", str(eigen), "--fremd", str(fremd)], stdout=aus)
    assert "wer wirklich sprach" in aus.getvalue()


def test_nur_eine_datei_ist_ein_fehler(tmp_path):
    datei = tmp_path / "eigen.log"
    datei.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        aw.main(["--eigen", str(datei)], stdout=io.StringIO())


def test_ohne_zeilen_ein_hinweis_und_fehlercode():
    aus = io.StringIO()
    assert aw.main([], stdin=io.StringIO("nichts\n"), stdout=aus) == 1
    assert "WAMO_STIMME_SCHATTEN" in aus.getvalue()
