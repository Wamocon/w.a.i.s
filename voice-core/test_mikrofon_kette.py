"""Tests für mikrofon_kette.py: Prüfung der Nachricht mikrofon_info, Logzeile, Kurzform für die Stimmzeilen, Grenzen.

Ausführen:  python -m pytest -q test_mikrofon_kette.py   (im Ordner voice-core/)

Festgehalten wird vor allem, was nie ins Protokoll gelangt: kein Gerätename, keine Kennung, kein freier Text. Nur sechs Felder zählen,
jeder andere Inhalt der Nachricht fällt weg.
"""

from __future__ import annotations

import pytest
from loguru import logger

import mikrofon_kette as mk
from mikrofon_kette import Kette, KettenProtokoll

VOLL = {"echo": True, "rauschen": True, "verstaerkung": True, "rate": 48000, "kanaele": 1, "klasse": "bluetooth"}


def _kette(daten: dict) -> Kette:
    """Wie aus_nachricht, mit der Klasse unbekannt als gültigem Feld, damit die Nachricht nicht schon als leer gilt."""
    return mk.aus_nachricht({"klasse": "unbekannt", **daten})


@pytest.fixture
def zeilen():
    """Alles, was der Kern über loguru schreibt, als Liste von Texten."""
    gesammelt: list[str] = []
    kennung = logger.add(lambda m: gesammelt.append(str(m).rstrip("\n")), format="{message}", level="DEBUG")
    yield gesammelt
    logger.remove(kennung)


# ---------- Prüfung der Nachricht ----------


def test_gueltige_nachricht_wird_uebernommen():
    assert mk.aus_nachricht(VOLL) == Kette(klasse="bluetooth", echo=True, rauschen=True, verstaerkung=True, rate=48000, kanaele=1)


def test_nur_die_sechs_felder_zaehlen_alles_andere_faellt_weg():
    daten = {**VOLL, "geraet": "Sony WH-1000XM4", "label": "Headset (Buds)", "id": "ab" * 16, "zusatz": {"a": 1}}
    kette = mk.aus_nachricht(daten)
    assert kette == mk.aus_nachricht(VOLL)
    assert not hasattr(kette, "geraet") and not hasattr(kette, "label")
    assert set(Kette.__dataclass_fields__) == {"klasse", "echo", "rauschen", "verstaerkung", "rate", "kanaele"}


@pytest.mark.parametrize("daten", [None, "bluetooth", 5, 1.5, [], [VOLL], (VOLL,), b"{}", True])
def test_was_kein_objekt_ist_wird_verworfen(daten):
    assert mk.aus_nachricht(daten) is None


def test_ohne_ein_einziges_gueltiges_feld_gilt_die_nachricht_nicht():
    """Eine leere oder bloße Unsinn-Nachricht darf keinen bekannten Stand überschreiben (Befund des Reviews)."""
    for daten in ({}, {"klasse": "x"}, {"klasse": None}, {"echo": "ja", "rate": 5, "kanaele": 99}, {"zusatz": 1}, {"echo": None, "rate": None}):
        assert mk.aus_nachricht(daten) is None, daten
    assert Kette() == Kette(klasse="unbekannt", echo=None, rauschen=None, verstaerkung=None, rate=None, kanaele=None)


def test_ein_geraet_ohne_erkennbare_klasse_und_ohne_zahlen_ist_trotzdem_eine_meldung():
    """Meldet die Oberfläche ausdrücklich klasse unbekannt (mehr gibt der Browser nicht her), ist das Wissen: es gab eine Meldung."""
    assert mk.aus_nachricht({"klasse": "unbekannt", "echo": None, "rate": None}) == Kette()


def test_unterklassen_von_int_und_str_zaehlen_nicht():
    class MeinInt(int):
        pass

    class MeinStr(str):
        pass

    kette = mk.aus_nachricht({"rate": MeinInt(48000), "kanaele": MeinInt(1), "klasse": MeinStr("bluetooth"), "echo": True})
    assert (kette.rate, kette.kanaele, kette.klasse) == (None, None, "unbekannt")
    assert kette.echo is True
    assert "\n" not in mk.aus_nachricht({"klasse": MeinStr("bluetooth\nEinschleusung"), "echo": True}).zeile()


@pytest.mark.parametrize("klasse", ["bluetооth", "ｂｌｕｅｔｏｏｔｈ", "bluetooth​", "bluetooth\x00"])
def test_aehnlich_aussehende_klassen_sind_unbekannt(klasse):
    assert mk.aus_nachricht({"klasse": klasse, "echo": True}).klasse == "unbekannt"


@pytest.mark.parametrize("wert", ["ja", "true", 1, 0, 1.0, [], {}, "an"])
@pytest.mark.parametrize("feld", ["echo", "rauschen", "verstaerkung"])
def test_schalter_sind_nur_wahr_oder_falsch_sonst_unbekannt(feld, wert):
    assert getattr(_kette({feld: wert}), feld) is None


@pytest.mark.parametrize("feld", ["echo", "rauschen", "verstaerkung"])
def test_schalter_wahr_und_falsch_und_null(feld):
    assert getattr(_kette({feld: True}), feld) is True
    assert getattr(_kette({feld: False}), feld) is False
    assert getattr(_kette({feld: None}), feld) is None


@pytest.mark.parametrize("rate", [8000, 16000, 44100, 48000, 96000, mk.RATE_MAX])
def test_rate_in_den_grenzen(rate):
    assert _kette({"rate": rate}).rate == rate


@pytest.mark.parametrize("rate", [0, -1, 7999, mk.RATE_MAX + 1, 10**9, 48000.0, 44100.5, "48000", True, False, None, [], float("nan"), float("inf")])
def test_rate_ausserhalb_oder_falscher_typ_ist_unbekannt(rate):
    assert _kette({"rate": rate}).rate is None


@pytest.mark.parametrize("kanaele", [1, 2, 4, 8])
def test_kanaele_in_den_grenzen(kanaele):
    assert _kette({"kanaele": kanaele}).kanaele == kanaele


@pytest.mark.parametrize("kanaele", [0, -1, 9, 100, 1.0, 2.5, "2", True, False, None, []])
def test_kanaele_ausserhalb_oder_falscher_typ_ist_unbekannt(kanaele):
    assert _kette({"kanaele": kanaele}).kanaele is None


@pytest.mark.parametrize("klasse", ["eingebaut", "headset", "bluetooth", "unbekannt"])
def test_die_vier_klassen_gehen_durch(klasse):
    assert mk.aus_nachricht({"klasse": klasse}).klasse == klasse


@pytest.mark.parametrize(
    "klasse", ["Bluetooth", "BLUETOOTH", " bluetooth", "bluetooth ", "usb", "", "Sony WH-1000XM4", "AirPods Pro", None, 3, True, [], {}, "x" * 10_000]
)
def test_jede_andere_klasse_heisst_unbekannt(klasse):
    assert mk.aus_nachricht({"klasse": klasse, "echo": True}).klasse == "unbekannt"


def test_ein_objekt_dessen_zugriff_wirft_bringt_nichts_zum_absturz():
    class Boese(dict):
        def get(self, *a, **k):
            raise RuntimeError("kaputt")

    assert mk.aus_nachricht(Boese(VOLL)) is None


# ---------- Logzeile und Kurzform ----------


def test_zeile_hat_genau_die_vorgegebene_form():
    assert mk.aus_nachricht(VOLL).zeile() == "Mikrofonkette: klasse=bluetooth echo=an rauschen=an verstaerkung=an rate=48000 kanaele=1"


def test_zeile_zeigt_aus_und_fragezeichen():
    kette = mk.aus_nachricht({"echo": False, "rauschen": None, "klasse": "eingebaut", "kanaele": 2})
    assert kette.zeile() == "Mikrofonkette: klasse=eingebaut echo=aus rauschen=? verstaerkung=? rate=? kanaele=2"


def test_zeile_ohne_jedes_wissen():
    assert Kette().zeile() == "Mikrofonkette: klasse=unbekannt echo=? rauschen=? verstaerkung=? rate=? kanaele=?"


def test_kurzform_ist_nur_die_klasse():
    assert Kette(klasse="headset", echo=True, rate=48000).kurz() == ", Kette headset"


# ---------- Protokoll der Sitzung ----------


def test_ohne_nachricht_steht_nichts_in_den_stimmzeilen():
    assert KettenProtokoll().kurz() == ""
    assert KettenProtokoll().stand is None


def test_eine_nachricht_schreibt_genau_eine_zeile_und_merkt_sich_den_stand(zeilen):
    p = KettenProtokoll()
    assert p.aufnehmen(VOLL) is True
    assert zeilen == ["Mikrofonkette: klasse=bluetooth echo=an rauschen=an verstaerkung=an rate=48000 kanaele=1"]
    assert p.stand == mk.aus_nachricht(VOLL)
    assert p.kurz() == ", Kette bluetooth"


def test_dieselbe_kette_noch_einmal_schreibt_nichts(zeilen):
    p = KettenProtokoll()
    p.aufnehmen(VOLL)
    assert p.aufnehmen(dict(VOLL)) is False
    assert len(zeilen) == 1


def test_eine_geaenderte_kette_schreibt_eine_neue_zeile_und_ersetzt_den_stand(zeilen):
    p = KettenProtokoll()
    p.aufnehmen(VOLL)
    assert p.aufnehmen({**VOLL, "klasse": "eingebaut", "echo": False}) is True
    assert len(zeilen) == 2 and "klasse=eingebaut echo=aus" in zeilen[1]
    assert p.kurz() == ", Kette eingebaut"


def test_ungueltige_nachricht_aendert_den_stand_nicht(zeilen):
    p = KettenProtokoll()
    p.aufnehmen(VOLL)
    for falsch in (None, "x", 7, [], b"x"):
        assert p.aufnehmen(falsch) is False
    assert len(zeilen) == 1 and p.kurz() == ", Kette bluetooth"


def test_kein_geraetename_gelangt_ins_protokoll(zeilen):
    p = KettenProtokoll()
    p.aufnehmen({**VOLL, "klasse": "Sony WH-1000XM4", "geraet": "Sony WH-1000XM4", "deviceId": "abc123", "label": "Headset (AirPods Pro)"})
    p.aufnehmen({"klasse": "Bluetooth-Kopfhörer von Erika", "echo": "Erikas Laptop"})
    text = "\n".join(zeilen) + p.kurz()
    for name in ("Sony", "WH-1000", "abc123", "AirPods", "Erika", "Laptop", "Kopfhörer"):
        assert name not in text


def test_die_zahl_der_zeilen_je_sitzung_ist_begrenzt_der_stand_bleibt_aktuell(zeilen):
    p = KettenProtokoll()
    for i in range(mk.MAX_MELDUNGEN + 40):
        p.aufnehmen({**VOLL, "rate": 8000 + i})
    ketten = [z for z in zeilen if z.startswith("Mikrofonkette: klasse=")]
    assert len(ketten) == mk.MAX_MELDUNGEN
    assert p.stand.rate == 8000 + mk.MAX_MELDUNGEN + 39  # die Urteilszeilen sollen die jüngste Kette tragen, nicht eine veraltete
    assert len([z for z in zeilen if "Änderungen in dieser Sitzung" in z]) == 1  # die Warnung kommt genau einmal


def test_gleiche_nachrichten_verbrauchen_die_grenze_nicht(zeilen):
    """Befund des Reviews: 60 gleiche Meldungen durften den späteren Wechsel auf bluetooth nicht mehr zulassen."""
    p = KettenProtokoll()
    p.aufnehmen({**VOLL, "klasse": "eingebaut"})
    for _ in range(mk.MAX_MELDUNGEN + 10):
        p.aufnehmen({**VOLL, "klasse": "eingebaut"})
    assert p.aufnehmen({**VOLL, "klasse": "bluetooth"}) is True
    assert p.kurz() == ", Kette bluetooth"
    assert zeilen[-1].startswith("Mikrofonkette: klasse=bluetooth")


def test_unsinn_ueberschreibt_keinen_bekannten_stand_und_verbraucht_nichts(zeilen):
    p = KettenProtokoll()
    p.aufnehmen(VOLL)
    for _ in range(mk.MAX_MELDUNGEN + 10):
        assert p.aufnehmen({}) is False
        assert p.aufnehmen({"klasse": "x"}) is False
    assert p.kurz() == ", Kette bluetooth"
    assert p.aufnehmen({**VOLL, "klasse": "headset"}) is True


def test_platzhalter_und_zeilenumbrueche_in_den_werten_kommen_nie_ins_log(zeilen):
    p = KettenProtokoll()
    p.aufnehmen({"klasse": "{}\n{0}\r\nMikrofonkette: klasse=bluetooth", "echo": "{0}", "rate": "{}", "kanaele": True})
    p.aufnehmen({"klasse": "bluetooth", "echo": True, "rate": 48000})
    assert len(zeilen) == 1  # die erste Nachricht hatte kein gültiges Feld
    assert "{" not in zeilen[0] and "\n" not in zeilen[0] and "\r" not in zeilen[0]


def test_aufnehmen_wirft_nie_nach_aussen(monkeypatch):
    p = KettenProtokoll()
    monkeypatch.setattr(mk, "aus_nachricht", lambda d: (_ for _ in ()).throw(RuntimeError("kaputt")))
    assert p.aufnehmen(VOLL) is False
    assert p.kurz() == ""
