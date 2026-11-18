"""Tests für stimme_mikrofon.py: Name des Mikrofons aus der Oberfläche bereinigen, Kennung daraus bilden.

Ausführen:  python -m pytest -q test_stimme_mikrofon.py   (im Ordner voice-core/)
"""

import re

import pytest

import stimme_mikrofon as mk


def test_name_wird_bereinigt_und_begrenzt():
    assert mk.mikrofon_name("  Headset (Jabra Evolve2 65)  ") == "Headset (Jabra Evolve2 65)"
    assert mk.mikrofon_name("Standard - Mikrofonarray (Realtek)") == "Mikrofonarray (Realtek)"  # Vorsatz von Chrome wie in der Oberfläche
    assert mk.mikrofon_name("Kommunikation \u2013 Headset") == "Headset"
    assert mk.mikrofon_name("Head\x00set\u202e\u200b  mit\tTab") == "Headset mit Tab"  # Steuer- und Formatzeichen weg, Leerraum zusammen
    assert mk.mikrofon_name("x" * 500) == "x" * mk.MAX_NAME
    assert len(mk.mikrofon_name("ä" * 200) or "") == mk.MAX_NAME


@pytest.mark.parametrize("roh", [None, "", "   ", "\x00\x01", 7, True, ["Headset"], {"name": "Headset"}, "Standard - "])
def test_ohne_brauchbaren_namen_kein_name(roh):
    assert mk.mikrofon_name(roh) is None
    assert mk.mikrofon_aus(roh) == mk.UNBEKANNTES_MIKROFON


def test_kennung_haengt_nur_am_bereinigten_namen():
    a = mk.mikrofon_aus("Headset (Jabra)")
    assert a.name == "Headset (Jabra)"
    assert re.fullmatch(r"[0-9a-f]{32}", a.kennung)
    assert mk.mikrofon_aus("Standard - headset (JABRA) ").kennung == a.kennung  # Groß und klein, Vorsatz, Leerraum zählen nicht
    assert mk.mikrofon_aus("Mikrofonarray").kennung != a.kennung
    assert mk.kennung_gueltig(a.kennung) and mk.kennung_gueltig(mk.UNBEKANNT)


@pytest.mark.parametrize("falsch", ["", "Headset", "A" * 32, "0" * 31, "0" * 33, None, 3, ["unbekannt"], "unbekannt "])
def test_ungueltige_kennungen(falsch):
    assert not mk.kennung_gueltig(falsch)


def test_einzelnes_surrogat_aus_json_wirft_nie():
    """Review 18.11.2026: ein einzelnes Surrogat aus JSON ist ein gültiger Python-Text, aber kein UTF-8. Es fällt weg, die Kennung entsteht ohne Fehler."""
    import json

    roh = json.loads('"Head\\ud800set\\u0000\\u202e"')
    m = mk.mikrofon_aus(roh)
    assert m.name == "Headset"
    assert m.kennung == mk.mikrofon_aus("Headset").kennung
    assert mk.mikrofon_aus(json.loads('"\\ud800"')) == mk.UNBEKANNTES_MIKROFON
    assert mk.mikrofon_name("Cafe\u0301") == "Caf\u00e9"  # NFC: dieselbe Kennung für beide Schreibweisen
    assert mk.mikrofon_aus("Cafe\u0301").kennung == mk.mikrofon_aus("Caf\u00e9").kennung


def test_hoechstens_drei_abdruecke():
    assert mk.MAX_ABDRUECKE == 3


# ---------- Einwilligung stimme-3 (je Mikrofon ein Abdruck, Entscheidung vom 18.11.2026) ----------

import stimme_einwilligung as se  # noqa: E402


def test_fassung_stimme_3_nennt_mikrofone_zahlen_zweck_und_loeschen():
    text = se.EINWILLIGUNG_TEXT_MIKROFONE
    assert se.EINWILLIGUNG_VERSION_MIKROFONE == "stimme-3"
    for teil in ("je eingelerntem Mikrofon", "192 Zahlen", "256 Zahlen", "höchstens drei Mikrofone", "keine Aufnahme", "freiwillig",
                 "alle meine Stimmabdrücke", "Einstellungen", "Widerruf", "Artikel 9", "nie einen Ton oder einen Text"):
        assert teil in text, teil
    assert "–" not in text and "—" not in text and " - " not in text
    assert se.TEXTE["stimme-3"] == text


def test_mit_mehreren_mikrofonen_gilt_nur_stimme_3():
    """Der neue Weg (Migration 0029 da) verlangt stimme-3, mit und ohne Schatten; ohne ihn bleibt es bei stimme-1 und stimme-2."""
    assert se.aktuelle_version(False, mikrofone=True) == se.aktuelle_version(True, mikrofone=True) == "stimme-3"
    assert (se.aktuelle_version(False), se.aktuelle_version(True)) == ("stimme-1", "stimme-2")
    assert se.einwilligung_gilt("stimme-3", schatten=False, mikrofone=True) and se.einwilligung_gilt("stimme-3", schatten=True, mikrofone=True)
    for falsch in ("stimme-1", "stimme-2", "Stimme-3", " stimme-3", "", None, 3, True):
        assert not se.einwilligung_gilt(falsch, schatten=True, mikrofone=True), falsch
    assert not se.einwilligung_gilt("stimme-3") and not se.einwilligung_gilt("stimme-3", schatten=True)
    assert se.einwilligung_nachricht(schatten=False, mikrofone=True) == {
        "type": "stimmabdruck_einwilligung", "version": "stimme-3", "text": se.EINWILLIGUNG_TEXT_MIKROFONE}


def test_vorhandene_fassungen_bleiben_gueltig_und_stimme_3_deckt_den_schatten():
    assert all(se.einwilligung_bekannt(v) for v in ("stimme-1", "stimme-2", "stimme-3"))
    assert [v for v in ("stimme-1", "stimme-2", "stimme-3", "stimme-4", None) if se.schatten_erlaubt(v)] == ["stimme-2", "stimme-3"]
