"""Wächter für die vier Fälle des Modellzugangs nach Entscheidung D2 (docs/ausrollen-neue-nutzer.md, Abschnitt 4.7, Paket P2).

Der geführte Ablauf fragt erst nach dem Claude-Code-Token, dann nach dem API-Schlüssel, beide überspringbar; die Zusammenfassung in der
Oberfläche (ui/src/lib/einrichtungSchritte.ts) sagt je Fall, womit W.A.I.S. arbeitet. Diese Tests nageln fest, dass der Kern genau das tut:

  Token und API-Schlüssel  Gespräch Claude über den eigenen Schlüssel, Entwicklungsaufträge mit dem Token (Vorrang), Stimme Soniox
  nur Token (Mischfall)    Gespräch über Hausmodelle (kein Aufruf der Messages-API mit dem Token), Aufträge mit dem Token, Stimme Soniox
  nur API-Schlüssel        Gespräch Claude, Aufträge mit dem API-Schlüssel, Stimme Soniox
  nichts                   alles über Hausmodelle, heute keine Entwicklungsaufträge, Stimme Soniox (D3: Soniox für alle)

Datenbank und Hauptschlüssel sind Attrappen (test_modellwahl.py); es gibt kein Netz.
"""

from __future__ import annotations

import pytest

import boss
import modellzugang as mz
import sprache_anbieter
from test_modellwahl import API, NIKO, TOKEN, _mit_api_schluessel, _mit_token, _zeile
from test_modellwahl import db, tresor  # noqa: F401 (Fixtures aus test_modellwahl)


@pytest.fixture(autouse=True)
def _sprache_aus_dem_profil(monkeypatch):
    monkeypatch.delenv("WAMO_STT_ANBIETER", raising=False)
    monkeypatch.delenv("WAMO_TTS_ANBIETER", raising=False)


async def _fall(db, tresor):
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor)
    lauf = await mz.claude_code_zugang_fuer(NIKO, db=db, tresor=tresor)
    sprache = await sprache_anbieter.sprach_wahl(z)
    return z, boss.entwicklung_quelle(z), (lauf or {}).get("typ"), (sprache.stt.anbieter, sprache.tts.anbieter)


async def test_token_und_api_schluessel(db, tresor):
    _mit_api_schluessel(db, tresor)
    _mit_token(db, tresor)
    z, quelle, lauf, sprache = await _fall(db, tresor)
    assert (z.art, z.quelle, z.claude_schluessel) == ("claude", "profil", API)
    assert (quelle, lauf, sprache) == ("token", "oauth", ("soniox", "soniox"))


async def test_nur_token_ist_der_mischfall(db, tresor):
    """Wächter für den Mischfall: Aufträge mit dem Token, das Gespräch über Hausmodelle, der Token nie im Zugang des Gesprächs."""
    db.zeilen[NIKO] = _zeile()
    _mit_token(db, tresor)
    z, quelle, lauf, sprache = await _fall(db, tresor)
    assert (z.art, z.quelle, z.claude_schluessel, z.claude_code) == ("haus", "keiner", None, True)
    assert boss.modus_wirksam(z) == "nur_haus"
    assert TOKEN not in repr(z)
    assert (quelle, lauf, sprache) == ("token", "oauth", ("soniox", "soniox"))


async def test_nur_api_schluessel(db, tresor):
    _mit_api_schluessel(db, tresor)
    z, quelle, lauf, sprache = await _fall(db, tresor)
    assert (z.art, z.quelle, z.claude_code) == ("claude", "profil", False)
    assert (quelle, lauf, sprache) == ("api", "api", ("soniox", "soniox"))


@pytest.mark.parametrize("zeile", [None, "leer"])
async def test_nichts_hinterlegt_heisst_hausmodelle_fuer_alles(db, tresor, zeile):
    if zeile == "leer":
        db.zeilen[NIKO] = _zeile()
    z, quelle, lauf, sprache = await _fall(db, tresor)
    assert (z.art, z.quelle, z.claude_schluessel, z.claude_code) == ("haus", "keiner", None, False)
    assert (quelle, lauf, sprache) == ("keine", None, ("soniox", "soniox"))


async def test_wahl_nur_haus_schickt_auch_mit_token_nichts_an_anthropic(db, tresor):
    _mit_api_schluessel(db, tresor, modell_modus="nur_haus")
    _mit_token(db, tresor)
    z, quelle, lauf, _ = await _fall(db, tresor)
    assert (z.art, z.quelle, z.claude_code) == ("haus", "wahl", False)
    assert (quelle, lauf) == ("keine", None)


async def test_laborprofil_nie_ein_entwicklungsauftrag(db, tresor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-anthropic")
    db.zeilen[NIKO] = _zeile()
    z = await mz.zugang_laden(NIKO, db=db, tresor=tresor, labor_art="platz")
    assert (z.quelle, boss.entwicklung_quelle(z)) == ("labor", "keine")
