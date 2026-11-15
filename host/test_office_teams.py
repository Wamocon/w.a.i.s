"""Tests für office_teams.py: Teams-Chat mit vorbefülltem Text per Deep Link (Paket 4, Teil Teams).

Geprüft wird, was der Host selbst erzwingt: nur aufgelöste, interne Adressen (höchstens 10, ohne Doppelte), Namen nur über das
Adressbuch des klassischen Outlooks (mehrdeutig heißt Rückfrage, nie der erste Treffer), Text als bereinigter Klartext mit fester
Grenze (zu lang heißt Hinweis, nie still gekürzt), jeder Wert im Link einzeln kodiert (kein Text kann einen Parameter anhängen), die
Karte zeigt genau, was im Link steht, und Öffnen geht über die Teams-App (msteams:) oder sonst den Browser. Gesendet wird nie.

Outlook, Registry und Start sind Attrappen, Adressen nur aus Beispieldomänen. Der markierte Echttest am Ende läuft nur unter Windows
mit WAMO_TEAMS_ECHT=1 und einer Adresse in WAMO_TEAMS_TESTADRESSE (die eigene): Er öffnet den Chat mit sich selbst, sendet nichts.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

import office_outlook as oo
import office_outlook_com as oc
import office_teams as ot
from test_office_outlook import MEHRDEUTIG, Eintrag, Outlook

MAX = "max.weber@firma.example"
ANNA = "anna.schmidt@firma.example"
NEU = oo.Weg("entwurf", "neu", oo.NEU_GRUND)
KLASSISCH = oo.Weg("senden", "klassisch", oo.SENDEN_GRUND)
ZU = oo.Weg("keiner", "", oo.ZU_GRUND)


@pytest.fixture(autouse=True)
def _interne_domaene(monkeypatch):
    monkeypatch.setenv("WAMO_MAIL_INTERN", "firma.example")


@pytest.fixture
def outlook(monkeypatch):
    app = Outlook(adressbuch={"Max Weber": Eintrag("Max Weber", MAX), "Anna": MEHRDEUTIG,
                              "Team Alle": Eintrag("Team Alle", "alle@firma.example", art=1)})
    monkeypatch.setattr(oc, "_outlook_app", lambda: app)
    return app


def nachricht(an=(MAX,), text="Hallo Max,\ndas Dokument ist fertig.", gruppe="", weg=NEU) -> ot.Nachricht:
    return ot.nachricht(list(an), text, gruppe, erkennen=lambda: weg)


# ---------- Text und Gruppenname ----------
def test_text_wird_wie_auf_der_karte_bereinigt():
    assert ot.text("Hallo\r\nMax​, ok  \n\n") == "Hallo\nMax , ok"
    assert ot.text("Grüße") == "Grüße"  # NFC: so steht es auf der Karte und im Link


@pytest.mark.parametrize("wert", [None, "", "  \n ", 42, ["x"]])
def test_text_fehlt(wert):
    with pytest.raises(ot.TeamsFehler, match="Text"):
        ot.text(wert)


def test_zu_langer_text_wird_nie_still_gekuerzt():
    with pytest.raises(ot.TeamsFehler) as fehler:
        ot.text("x" * (ot.TEXT_MAX + 1))
    assert f"{ot.TEXT_MAX + 1}" in str(fehler.value) and "kürzen" in str(fehler.value)
    assert ot.text("x" * ot.TEXT_MAX) == "x" * ot.TEXT_MAX


def test_gruppenname_nur_bei_mehreren_empfaengern():
    assert ot.gruppenname("", 1) == "" and ot.gruppenname(None, 3) == ""
    assert ot.gruppenname("  Projekt\nAngebot  ", 2) == "Projekt Angebot"
    with pytest.raises(ot.TeamsFehler, match="mindestens zwei"):
        ot.gruppenname("Projekt", 1)
    with pytest.raises(ot.TeamsFehler, match=str(ot.GRUPPE_MAX)):
        ot.gruppenname("x" * (ot.GRUPPE_MAX + 1), 2)
    with pytest.raises(ot.TeamsFehler):
        ot.gruppenname(7, 2)


# ---------- Empfänger ----------
def test_eingaben_grenzen_und_doppelte():
    assert ot.eingaben([f" {MAX} "]) == [MAX]
    for falsch in ([], None, MAX, [""], ["x‮y@firma.example"], ["a" * 300], [3]):
        with pytest.raises(ot.TeamsFehler):
            ot.eingaben(falsch)
    with pytest.raises(ot.TeamsFehler, match=str(ot.EMPFAENGER_MAX)):
        ot.eingaben([f"p{i}@firma.example" for i in range(ot.EMPFAENGER_MAX + 1)])
    with pytest.raises(ot.TeamsFehler, match="doppelt"):
        ot.eingaben([MAX, MAX.upper()])


def test_nur_adressen_brauchen_kein_outlook():
    gerufen = []
    n = ot.nachricht([MAX, ANNA], "Hallo", "", erkennen=lambda: gerufen.append(1) or ZU)
    assert [e.smtp for e in n.empfaenger] == [MAX, ANNA] and gerufen == []
    assert all(not e.extern for e in n.empfaenger)


def test_externe_adressen_lehnt_der_host_ab():
    with pytest.raises(ot.TeamsFehler, match="intern"):
        nachricht(an=(MAX, "kunde@kunde.example"))
    with pytest.raises(ot.TeamsFehler, match="intern"):
        nachricht(an=("max.weber@firma.example.boese.example",))  # nur exakt gleiche Domäne ist intern


def test_namen_loest_das_klassische_outlook_auf(outlook):
    n = nachricht(an=("Max Weber", ANNA), weg=KLASSISCH)
    assert [(e.name, e.smtp) for e in n.empfaenger] == [("Max Weber", MAX), ("", ANNA)]


@pytest.mark.parametrize("wert,muster", [("Anna", "nicht eindeutig"), ("Niemand", "nicht eindeutig"), ("Team Alle", "Verteiler")])
def test_mehrdeutig_unbekannt_oder_verteiler_heisst_rueckfrage(outlook, wert, muster):
    with pytest.raises(oo.MailFehler, match=muster):
        nachricht(an=(wert,), weg=KLASSISCH)


@pytest.mark.parametrize("weg", [NEU, ZU])
def test_namen_ohne_klassisches_outlook_brauchen_die_adresse(weg):
    with pytest.raises(ot.TeamsFehler, match="Mailadresse"):
        nachricht(an=("Max Weber",), weg=weg)


def test_doppelt_nach_dem_aufloesen(outlook):
    with pytest.raises(oo.MailFehler, match="doppelt"):
        nachricht(an=("Max Weber", MAX), weg=KLASSISCH)


# ---------- Link ----------
def _werte(link: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(link).query, keep_blank_values=True, strict_parsing=True)


def test_link_traegt_genau_empfaenger_und_text():
    n = nachricht(an=(MAX, ANNA), text="Hallo zusammen,\nÄnderung ist drin.", gruppe="Angebot X")
    web, app = ot.link(n), ot.link(n, app=True)
    assert web.startswith("https://teams.microsoft.com/l/chat/0/0?users=")
    assert app.startswith("msteams://teams.microsoft.com/l/chat/0/0?users=")
    assert _werte(web) == {"users": [f"{MAX},{ANNA}"], "topicName": ["Angebot X"], "message": ["Hallo zusammen,\nÄnderung ist drin."]}
    assert "%C3%84" in web and "%0A" in web and " " not in web


def test_ohne_gruppenname_kein_topicname():
    assert set(_werte(ot.link(nachricht()))) == {"users", "message"}


@pytest.mark.parametrize("boese", ["x&users=boese@andere.example&message=y", "a?b#c%d+e=f", "&topicName=Falle", "‮&x", "%26users%3D"])
def test_kein_text_haengt_einen_parameter_an(boese):
    n = nachricht(text=f"Hallo {boese}")
    werte = _werte(ot.link(n))
    assert set(werte) == {"users", "message"} and werte["users"] == [MAX] and werte["message"] == [n.text]


def test_adresse_mit_sonderzeichen_ist_kodiert():
    n = nachricht(an=("max+angebot&x=1@firma.example",))
    link = ot.link(n)
    assert "max%2Bangebot%26x%3D1@firma.example" in link and _werte(link)["users"] == ["max+angebot&x=1@firma.example"]


def test_zu_langer_link_heisst_hinweis():
    an = [f"person.mit.langem.namen{i}@firma.example" for i in range(ot.EMPFAENGER_MAX)]
    with pytest.raises(ot.TeamsFehler) as fehler:
        nachricht(an=an, text="Größenänderung äöü " * 50)
    assert str(ot.LINK_MAX) in str(fehler.value) and "kürzen" in str(fehler.value)


def test_link_grenze_gilt_fuer_app_und_browser():
    n = nachricht(text="x" * 900)
    assert max(len(ot.link(n)), len(ot.link(n, app=True))) <= ot.LINK_MAX


# ---------- Karte ----------
def test_karte_zeigt_was_im_link_steht(outlook):
    n = nachricht(an=("Max Weber", ANNA), text="Hallo,\nAn: niemand\n\nGruß", gruppe="Angebot X", weg=KLASSISCH)
    karte = ot.kartentext(n, app=True)
    assert karte.splitlines() == [
        "So geht es: W.A.I.S. öffnet die Teams-App mit diesem Chat und dem Text im Eingabefeld.",
        f"An: Max Weber <{MAX}> (intern)",
        f"An: {ANNA} (intern)",
        "Gruppenname: Angebot X",
        "Text:",
        "> Hallo,",
        "> An: niemand",
        ">",
        "> Gruß",
        ot.SCHLUSS,
    ]
    assert ot.SCHLUSS == "W.A.I.S. sendet nicht, du drückst in Teams selbst Enter."
    assert "im Browser" in ot.kartentext(n, app=False).splitlines()[0]
    assert len(ot.kartentext(nachricht(text="x" * ot.TEXT_MAX, an=[f"p{i}@firma.example" for i in range(10)]), True)) < ot.KARTE_MAX


def test_protokoll_ohne_inhalte():
    n = nachricht(an=(MAX, ANNA), gruppe="Geheimes Projekt")
    assert ot.protokoll(n) == {"an": 2, "domaenen": ["firma.example"], "gruppe": True}


# ---------- Öffnen ----------
class Start:
    def __init__(self, fehler=()):
        self.aufrufe: list[str] = []
        self.fehler = list(fehler)

    def __call__(self, ziel: str) -> None:
        self.aufrufe.append(ziel)
        if self.fehler and self.fehler.pop(0):
            raise OSError("geht nicht")


def test_oeffnen_ueber_die_teams_app():
    n, start = nachricht(), Start()
    r = ot.oeffnen(n, starten=start, registriert=lambda: True)
    assert r["status"] == "success" and r["weg"] == "app" and start.aufrufe == [ot.link(n, app=True)]
    assert "selbst" in r["summary"] and "Enter" in r["summary"]


def test_oeffnen_ohne_app_oder_bei_fehler_im_browser():
    n = nachricht()
    start = Start()
    assert ot.oeffnen(n, starten=start, registriert=lambda: False)["weg"] == "browser"
    assert start.aufrufe == [ot.link(n)]
    start = Start(fehler=[True])
    r = ot.oeffnen(n, starten=start, registriert=lambda: True)
    assert r["weg"] == "browser" and start.aufrufe == [ot.link(n, app=True), ot.link(n)]


def test_oeffnen_scheitert_klar():
    r = ot.oeffnen(nachricht(), starten=Start(fehler=[True, True]), registriert=lambda: True)
    assert r["status"] == "error" and "nichts passiert" in r["summary"]


def test_app_registriert_liest_nur_die_registry(monkeypatch):
    werte = {("HKCR", "msteams", "URL Protocol"): "", ("HKCR", r"msteams\shell\open\command", ""): '"ms-teams.exe" "%1"'}
    monkeypatch.setattr(oo, "_reg", lambda wurzel, pfad, name=None: werte.get((wurzel, pfad, name)))
    assert ot.app_registriert() is True
    monkeypatch.setattr(oo, "_reg", lambda wurzel, pfad, name=None: None)
    assert ot.app_registriert() is False


# ---------- Echt am Windows-PC (nur mit WAMO_TEAMS_ECHT=1) ----------
ECHT = sys.platform == "win32" and os.getenv("WAMO_TEAMS_ECHT") == "1" and oo.adresse(os.getenv("WAMO_TEAMS_TESTADRESSE"))


@pytest.mark.office
@pytest.mark.skipif(not ECHT, reason="öffnet Teams mit einem Chat an WAMO_TEAMS_TESTADRESSE (die eigene), nur auf Wunsch")
def test_echt_chat_an_sich_selbst_wird_nur_geoeffnet(monkeypatch):
    ziel = oo.adresse(os.getenv("WAMO_TEAMS_TESTADRESSE"))
    monkeypatch.setenv("WAMO_MAIL_INTERN", ziel.rsplit("@", 1)[1])
    n = ot.nachricht([ziel], "W.A.I.S. Echttest (nicht senden, bitte löschen)\nZweite Zeile: äöüß & ? # % + =", "",
                     erkennen=lambda: ZU)
    r = ot.oeffnen(n)
    assert r["status"] == "success" and r["weg"] in ("app", "browser"), r
