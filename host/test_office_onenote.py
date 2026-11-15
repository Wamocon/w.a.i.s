"""Tests für OneNote per COM (office_onenote.py): Erkennung, Wahl des Standard-Notizbuchs, Abschnitt, Seiten-XML, Kartentext,
Ablauf mit einer Attrappe von OneNote, Zeitgrenze und Sperre.

OneNote läuft hier nie wirklich. Nur der letzte Test spricht mit dem echten OneNote am PC (WAMO_OFFICE_ECHT=1): Er legt einen eigenen
Test-Abschnitt an, schreibt eine Seite hinein, liest sie zurück und löscht danach genau diesen Abschnitt wieder.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import threading
import time
import xml.etree.ElementTree as ET

import pytest

import office_dateien as od
import office_onenote as on

NS = "{" + on.NS + "}"
GEHEIM = "Vertrauliche Zeile im Angebot"
NB_ID, NB2_ID, AB_ID, SEITE_ID = "{nb-1}", "{nb-2}", "{ab-1}", "{seite-1}"


def hierarchie(*buecher: tuple[str, str, str]) -> str:
    """Antwort von GetHierarchy für die Notizbücher: (ID, Name, Pfad)."""
    innen = "".join(f'<one:Notebook name="{n}" nickname="{n}" ID="{i}" path="{p}" />' for i, n, p in buecher)
    return f'<?xml version="1.0"?><one:Notebooks xmlns:one="{on.NS}">{innen}</one:Notebooks>'


def abschnitte(nb_id: str, *eintraege: str) -> str:
    return f'<one:Notebook xmlns:one="{on.NS}" ID="{nb_id}" name="x">{"".join(eintraege)}</one:Notebook>'


def abschnitt(name: str, sid: str = AB_ID, **attr) -> str:
    extra = "".join(f' {k}="{v}"' for k, v in attr.items())
    return f'<one:Section name="{name}" ID="{sid}" path="p"{extra} />'


BUECHER = hierarchie((NB_ID, "Arbeit", "https://d.docs.live.net/abc/Dokumente/Arbeit/"),
                     (NB2_ID, "Privat", "C:\\Users\\n\\OneNote\\Privat"))


# ---------- Erkennung ohne Start ----------
def _registrierung(werte: dict):
    return lambda pfad: werte.get(pfad)


ONENOTE_EXE = r"C:\Program Files\Microsoft Office\Root\Office16\ONENOTE.EXE"
CLSID = "{DC67E480-C3CB-49F8-8232-60B0C2056C8E}"


@pytest.mark.parametrize("server, erwartet", [
    (ONENOTE_EXE, True),
    (f'"{ONENOTE_EXE}" /Embedding', True),
    (r"C:\Programme\Fremd\andere.exe", False),
    ("", False),
])
def test_erkennung_liest_nur_die_registrierung(server, erwartet):
    lesen = _registrierung({r"OneNote.Application\CLSID": CLSID, rf"CLSID\{CLSID}\LocalServer32": server})
    assert on.onenote_vorhanden(lesen=lesen, datei_da=lambda p: True, plattform="win32") is erwartet


def test_erkennung_ohne_eintrag_ohne_datei_oder_ohne_windows():
    voll = {r"OneNote.Application\CLSID": CLSID, rf"CLSID\{CLSID}\LocalServer32": ONENOTE_EXE}
    assert on.onenote_vorhanden(lesen=_registrierung({}), datei_da=lambda p: True, plattform="win32") is False
    assert on.onenote_vorhanden(lesen=_registrierung(voll), datei_da=lambda p: False, plattform="win32") is False
    assert on.onenote_vorhanden(lesen=_registrierung(voll), datei_da=lambda p: True, plattform="linux") is False
    kaputt = {r"OneNote.Application\CLSID": "..\\x", rf"CLSID\..\x\LocalServer32": ONENOTE_EXE}
    assert on.onenote_vorhanden(lesen=_registrierung(kaputt), datei_da=lambda p: True, plattform="win32") is False


# ---------- Standard-Notizbuch und Abschnitt ----------
def test_standard_ist_das_notizbuch_mit_den_schnellen_notizen():
    schnell = "C:\\Users\\n\\OneNote\\Privat\\Schnelle Notizen.one"
    assert on.notizbuch_waehlen(BUECHER, schnell) == (NB2_ID, "Privat")
    schnell_web = "https://d.docs.live.net/abc/Dokumente/Arbeit/Schnelle Notizen.one"
    assert on.notizbuch_waehlen(BUECHER, schnell_web) == (NB_ID, "Arbeit")


def test_ohne_schnelle_notizen_im_notizbuch_gilt_das_erste():
    assert on.notizbuch_waehlen(BUECHER, "") == (NB_ID, "Arbeit")
    # Präfix ohne Trenner zählt nicht: "Privat2" liegt nicht in "Privat"
    assert on.notizbuch_waehlen(BUECHER, "C:\\Users\\n\\OneNote\\Privat2\\Schnelle Notizen.one") == (NB_ID, "Arbeit")


def test_ohne_notizbuch_ein_klarer_fehler():
    with pytest.raises(on.OneNoteFehler, match="kein Notizbuch"):
        on.notizbuch_waehlen(hierarchie(), "")
    with pytest.raises(on.OneNoteFehler):
        on.notizbuch_waehlen("kein xml", "")


def test_abschnitt_nur_direkt_im_notizbuch_und_nicht_im_papierkorb():
    gruppe = f'<one:SectionGroup name="Gruppe" ID="g">{abschnitt("W.A.I.S.", "{in-gruppe}")}</one:SectionGroup>'
    papierkorb = abschnitt("W.A.I.S.", "{alt}", isInRecycleBin="true")
    xml = abschnitte(NB_ID, gruppe, papierkorb, abschnitt("Sonstiges", "{s}"))
    assert on.abschnitt_suchen(xml, NB_ID, "W.A.I.S.") == ""
    xml = abschnitte(NB_ID, papierkorb, abschnitt("w.a.i.s.", AB_ID))
    assert on.abschnitt_suchen(xml, NB_ID, "W.A.I.S.") == AB_ID


@pytest.mark.parametrize("attr", [{"locked": "true"}, {"readOnly": "true"}, {"encrypted": "true"}])
def test_geschuetzter_abschnitt_ist_ein_fehler(attr):
    with pytest.raises(on.OneNoteFehler, match="geschützt"):
        on.abschnitt_suchen(abschnitte(NB_ID, abschnitt("W.A.I.S.", **attr)), NB_ID, "W.A.I.S.")


# ---------- Seiten-XML ----------
BOESE = '<b>fett</b> <a href="https://boese.example/x">Link</a> <img src="https://boese.example/b.png"> ]]> &amp; <![CDATA['
HTML_TAG = re.compile(r"<[^>]*>")


def _t_texte(xml: str) -> list[str]:
    return [t.text or "" for t in ET.fromstring(xml).iter(NS + "T")]


def _seite(inhalt: dict, titel: str = "") -> on.Seite:
    return on.seite_pruefen(inhalt, titel)


def test_text_aus_dem_canvas_ist_immer_maskiert():
    seite = _seite({"art": "dokument", "titel": "Böse <i>", "text": f"# {BOESE}\n- {BOESE}\n{BOESE} **{BOESE}**"})
    xml = on.seiten_xml(seite, SEITE_ID)
    for text in _t_texte(xml):
        # In one:T liest OneNote HTML: Erlaubt sind nur die eigenen span-Auszeichnungen, nie ein Tag aus dem Canvas
        assert all(re.fullmatch(r"<span style='[A-Za-z0-9:;. -]+'>|</span>", tag) for tag in HTML_TAG.findall(text)), text
    alles = "".join(_t_texte(xml))
    assert "&lt;b&gt;fett&lt;/b&gt;" in alles and "&lt;a href=" in alles and "&lt;img" in alles and "]]&gt;" in alles
    assert "&amp;amp;" in alles  # schon maskierter Text bleibt Text
    baum = ET.fromstring(xml)
    for verboten in ("Image", "InsertedFile", "MediaFile", "Hyperlink"):
        assert baum.find(f".//{NS}{verboten}") is None
    assert "href=" not in xml.replace("&amp;lt;a href=", "")


def test_seite_mit_titel_ueberschrift_punkt_und_fett():
    xml = on.seiten_xml(_seite({"art": "dokument", "titel": "Angebot", "text": f"# Kopf\n- eins\n{GEHEIM} **fett**"}), SEITE_ID)
    baum = ET.fromstring(xml)
    assert baum.tag == NS + "Page" and baum.get("ID") == SEITE_ID
    assert baum.find(f"{NS}Title/{NS}OE/{NS}T").text == "Angebot"
    oes = baum.findall(f"{NS}Outline/{NS}OEChildren/{NS}OE")
    assert len(oes) == 3
    assert "font-weight:bold" in oes[0].find(NS + "T").text and "Kopf" in oes[0].find(NS + "T").text
    assert oes[1].find(f"{NS}List/{NS}Bullet") is not None and oes[1].find(NS + "T").text == "eins"
    assert oes[2].find(NS + "T").text == f"{GEHEIM} <span style='font-weight:bold'>fett</span>"


def test_code_ist_vorformatiert():
    xml = on.seiten_xml(_seite({"art": "code", "titel": "SQL", "text": "select 1\n\n    from x  -- <b>", "sprache": "sql"}),
                        SEITE_ID)
    oes = ET.fromstring(xml).findall(f"{NS}Outline/{NS}OEChildren/{NS}OE")
    assert len(oes) == 3
    assert all("Consolas" in oe.get("style", "") for oe in oes)
    assert (oes[1].find(NS + "T").text or "") == ""
    assert oes[2].find(NS + "T").text == "\u00a0" * 4 + "from\u00a0x\u00a0\u00a0--\u00a0&lt;b&gt;"


def test_tabelle_mit_kopfzeile():
    inhalt = {"art": "tabelle", "titel": "Liste", "spalten": ["Name", "Wert"], "zeilen": [["a", "=1+1"], ["<b>", ""]]}
    tabelle = ET.fromstring(on.seiten_xml(_seite(inhalt), SEITE_ID)).find(f".//{NS}Table")
    assert len(tabelle.findall(f"{NS}Columns/{NS}Column")) == 2
    zeilen = tabelle.findall(NS + "Row")
    assert len(zeilen) == 3
    kopf = [c.find(f".//{NS}T").text for c in zeilen[0].findall(NS + "Cell")]
    assert kopf == ["<span style='font-weight:bold'>Name</span>", "<span style='font-weight:bold'>Wert</span>"]
    assert [c.find(f".//{NS}T").text or "" for c in zeilen[2].findall(NS + "Cell")] == ["&lt;b&gt;", ""]


def test_titel_aus_dem_canvas_oder_vom_modell():
    assert _seite({"art": "dokument", "titel": "Angebot", "text": "x"}).titel == "Angebot"
    assert _seite({"art": "dokument", "titel": "Angebot", "text": "x"}, "  Neuer\u200b Titel\n ").titel == "Neuer Titel"
    lang = _seite({"art": "dokument", "titel": "T" * 200, "text": "x"})
    assert len(lang.titel) == on.TITEL_MAX
    with pytest.raises(od.InhaltFehler):
        _seite({"art": "dokument", "titel": "T", "text": "x"}, "x" * 301)
    with pytest.raises(od.InhaltFehler):
        _seite({"art": "dokument", "titel": "T", "text": "x"}, 5)
    with pytest.raises(od.InhaltFehler):
        _seite({"art": "bild", "titel": "T", "text": "x"})


# ---------- Kartentext ----------
def test_karte_zeigt_titel_und_den_ganzen_inhalt():
    seite = _seite({"art": "dokument", "titel": "Angebot", "text": f"# Kopf\n- eins\n{GEHEIM} **fett**"})
    assert on.karten_detail(seite) == f"Seite: Angebot\nInhalt:\n> Kopf\n> • eins\n> {GEHEIM} fett"
    tabelle = _seite({"art": "tabelle", "titel": "Liste", "spalten": ["a", "b"], "zeilen": [["1", "2"]]})
    assert on.karten_detail(tabelle) == "Seite: Liste\nInhalt:\n> a | b\n> 1 | 2"
    code = _seite({"art": "code", "titel": "SQL", "text": "select 1\n\nfrom x"})
    assert on.karten_detail(code) == "Seite: SQL\nInhalt:\n> select 1\n>\n> from x"


def test_ziel_der_karte_nennt_notizbuch_und_abschnitt():
    assert on.karten_ziel(on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID)) == "OneNote, Notizbuch Arbeit, Abschnitt W.A.I.S."
    neu = on.karten_ziel(on.Ziel(NB_ID, "N" * 300, "W.A.I.S.", ""))
    assert neu.endswith("Abschnitt W.A.I.S. (wird angelegt)") and len(neu) <= 200


# ---------- Ablauf mit einer Attrappe von OneNote ----------
class App:
    """Attrappe der COM-Schnittstelle: merkt sich jeden Aufruf."""

    def __init__(self, buecher=BUECHER, schnell="", vorhanden=(), fehler_bei=None):
        self.aufrufe: list[tuple] = []
        self.buecher, self.schnell, self.vorhanden, self.fehler_bei = buecher, schnell, list(vorhanden), fehler_bei

    def _merken(self, *aufruf):
        self.aufrufe.append(aufruf)
        if self.fehler_bei == aufruf[0]:
            fehler = OSError("COM")
            fehler.hresult = -2147213311  # 0x80042001: XML ungültig
            raise fehler

    def GetHierarchy(self, start, scope, xsSchema):  # noqa: N802, N803 (Namen der COM-Schnittstelle)
        self._merken("GetHierarchy", start, scope, xsSchema)
        return self.buecher if start == "" else abschnitte(start, *self.vorhanden)

    def GetSpecialLocation(self, art):  # noqa: N802
        self._merken("GetSpecialLocation", art)
        return self.schnell

    def OpenHierarchy(self, pfad, relativ, cftIfNotExist):  # noqa: N802, N803
        self._merken("OpenHierarchy", pfad, relativ, cftIfNotExist)
        return "{ab-neu}"

    def CreateNewPage(self, abschnitt_id):  # noqa: N802
        self._merken("CreateNewPage", abschnitt_id)
        return SEITE_ID

    def UpdatePageContent(self, xml, dateExpectedLastModified, xsSchema):  # noqa: N802, N803
        assert dateExpectedLastModified == 0.0  # ohne den Wert scheitert comtypes am Standard der Typbibliothek
        self._merken("UpdatePageContent", xml, xsSchema)

    def NavigateTo(self, objekt):  # noqa: N802
        self._merken("NavigateTo", objekt)

    def DeleteHierarchy(self, objekt, dateExpectedLastModified, deletePermanently):  # noqa: N802, N803
        assert dateExpectedLastModified == 0.0
        self._merken("DeleteHierarchy", objekt, deletePermanently)


SEITE = on.seite_pruefen({"art": "dokument", "titel": "Angebot", "text": f"# Kopf\n{GEHEIM}"})


def test_ziel_lesen_aendert_nichts():
    app = App(vorhanden=[abschnitt("W.A.I.S.")])
    ziel = on.ziel_pruefen(fabrik=lambda: app)
    assert ziel == on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID)
    assert {a[0] for a in app.aufrufe} == {"GetHierarchy", "GetSpecialLocation"}
    assert all(a[-1] == on.XS_2013 for a in app.aufrufe if a[0] == "GetHierarchy")


def test_seite_im_vorhandenen_abschnitt():
    app = App(vorhanden=[abschnitt("W.A.I.S.")])
    ergebnis = on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), fabrik=lambda: app)
    assert ergebnis == {"seite_id": SEITE_ID, "abschnitt_id": AB_ID, "abschnitt_neu": False, "notizbuch": "Arbeit",
                        "abschnitt": "W.A.I.S."}
    namen = [a[0] for a in app.aufrufe]
    assert "OpenHierarchy" not in namen and "DeleteHierarchy" not in namen
    assert ("CreateNewPage", AB_ID) in app.aufrufe
    update = next(a for a in app.aufrufe if a[0] == "UpdatePageContent")
    assert update[2] == on.XS_2013 and ET.fromstring(update[1]).get("ID") == SEITE_ID and GEHEIM in update[1]
    assert app.aufrufe[-1] == ("NavigateTo", SEITE_ID)


def test_fehlender_abschnitt_wird_angelegt_und_nichts_gezeigt():
    app = App()
    ergebnis = on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", ""), zeigen=False, fabrik=lambda: app)
    assert ergebnis["abschnitt_neu"] is True and ergebnis["abschnitt_id"] == "{ab-neu}"
    assert ("OpenHierarchy", "W.A.I.S..one", NB_ID, on.CFT_ABSCHNITT) in app.aufrufe
    assert ("CreateNewPage", "{ab-neu}") in app.aufrufe
    assert "NavigateTo" not in [a[0] for a in app.aufrufe]


def test_anderes_standard_notizbuch_seit_der_anfrage_bricht_ab():
    app = App(schnell="C:\\Users\\n\\OneNote\\Privat\\Schnelle Notizen.one")
    with pytest.raises(on.OneNoteFehler, match="geändert"):
        on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", ""), fabrik=lambda: app)
    assert not {"OpenHierarchy", "CreateNewPage", "UpdatePageContent"} & {a[0] for a in app.aufrufe}


def test_fehler_beim_schreiben_raeumt_nur_die_eigene_neue_seite_weg():
    app = App(vorhanden=[abschnitt("W.A.I.S.")], fehler_bei="UpdatePageContent")
    with pytest.raises(on.OneNoteFehler, match="0x80042001"):
        on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), fabrik=lambda: app)
    loeschen = [a for a in app.aufrufe if a[0] == "DeleteHierarchy"]
    assert loeschen == [("DeleteHierarchy", SEITE_ID, True)]


def test_zeitgrenze_und_nur_ein_zugriff_zur_zeit():
    los = threading.Event()

    def haengt():
        los.wait(5)
        return App()

    start = time.monotonic()
    with pytest.raises(on.OneNoteFehler, match="nicht in der Zeit"):
        on.ziel_pruefen(fabrik=haengt, timeout=0.2)
    assert time.monotonic() - start < 2
    with pytest.raises(on.OneNoteFehler, match="beschäftigt"):
        on.ziel_pruefen(fabrik=lambda: App(), timeout=0.2, warten=0.05)
    los.set()
    for _ in range(50):  # der hängende Faden gibt die Sperre frei, sobald er endet
        if not on._SPERRE.locked():
            break
        time.sleep(0.05)
    assert on.ziel_pruefen(fabrik=lambda: App(), timeout=2).notizbuch == "Arbeit"


def test_start_von_onenote_scheitert_lesbar():
    def kaputt():
        raise OSError("Klasse nicht registriert")

    with pytest.raises(on.OneNoteFehler, match="OneNote"):
        on.ziel_pruefen(fabrik=kaputt, timeout=2)
    assert not on._SPERRE.locked()


# ---------- Ratenbremse ----------
def test_bremse_zehn_je_stunde():
    jetzt = [1000.0]
    bremse = on.Bremse(10, 3600, uhr=lambda: jetzt[0])
    for _ in range(10):
        assert bremse.voll() is False
        bremse.zaehlen()
    assert bremse.voll() is True
    jetzt[0] += 3601
    assert bremse.voll() is False


# ---------- Befunde aus dem Review: unsichtbare Zeichen, späte Antwort, Abschnitt geändert, Rückfall ----------
def test_unsichtbare_zeichen_fehlen_auf_karte_und_seite_gleich():
    rlo, nullbreite, auswahl = chr(0x202E), chr(0x200B), chr(0xFE0F)
    seite = _seite({"art": "dokument", "titel": "T", "text": f"Preis {rlo}0001{nullbreite} Euro{auswahl}\tnetto"})
    assert seite.inhalt.text == "Preis 0001 Euro    netto"
    assert on.karten_detail(seite).endswith("> Preis 0001 Euro    netto")
    assert "Preis 0001 Euro    netto" in "".join(_t_texte(on.seiten_xml(seite, SEITE_ID)))
    tabelle = _seite({"art": "tabelle", "titel": "T", "spalten": [f"a{rlo}"], "zeilen": [["zwei\nZeilen"]]})
    assert (tabelle.inhalt.spalten, tabelle.inhalt.zeilen) == (("a",), (("zwei Zeilen",),))
    with pytest.raises(od.InhaltFehler, match="leer"):
        _seite({"art": "dokument", "titel": "T", "text": f"{nullbreite}{rlo}"})


def test_nach_der_zeitgrenze_entsteht_keine_seite_mehr():
    abbruch = threading.Event()
    abbruch.set()
    app = App(vorhanden=[abschnitt("W.A.I.S.")])
    with pytest.raises(on.OneNoteFehler, match="nachsehen"):
        on._schreiben(app, SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), False, abbruch)
    assert not {"OpenHierarchy", "CreateNewPage"} & {a[0] for a in app.aufrufe}


def test_zeitgrenze_waehrend_des_anlegens_raeumt_die_eigene_seite_weg():
    abbruch = threading.Event()

    class Langsam(App):
        def CreateNewPage(self, abschnitt_id):  # noqa: N802
            abbruch.set()  # so, als wäre die Zeitgrenze genau jetzt abgelaufen
            return super().CreateNewPage(abschnitt_id)

    app = Langsam(vorhanden=[abschnitt("W.A.I.S.")])
    with pytest.raises(on.OneNoteFehler):
        on._schreiben(app, SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), False, abbruch)
    assert [a[0] for a in app.aufrufe][-2:] == ["CreateNewPage", "DeleteHierarchy"]
    assert "UpdatePageContent" not in [a[0] for a in app.aufrufe]


def test_schreib_zeitgrenze_warnt_vor_doppelter_seite():
    los = threading.Event()

    def haengt():
        los.wait(5)
        return App()

    with pytest.raises(on.OneNoteFehler, match="bevor du sie noch einmal anlegst"):
        on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), fabrik=haengt, timeout=0.2)
    los.set()
    for _ in range(50):
        if not on._SPERRE.locked():
            break
        time.sleep(0.05)


def test_anderer_abschnitt_gleichen_namens_bricht_ab():
    app = App(vorhanden=[abschnitt("W.A.I.S.", "{anderer}")])
    with pytest.raises(on.OneNoteFehler, match="Abschnitt W.A.I.S. hat sich"):
        on.seite_anlegen(SEITE, on.Ziel(NB_ID, "Arbeit", "W.A.I.S.", AB_ID), fabrik=lambda: app)
    assert "CreateNewPage" not in [a[0] for a in app.aufrufe]


def test_rueckfall_nur_wenn_onenote_nicht_taugt():
    def nicht_registriert():
        raise OSError("nicht registriert")

    with pytest.raises(on.OneNoteFehler, match="startet nicht") as fehlt:
        on.ziel_pruefen(fabrik=nicht_registriert, timeout=2)
    assert fehlt.value.rueckfall is True
    with pytest.raises(on.OneNoteFehler) as leer:
        on.ziel_pruefen(fabrik=lambda: App(buecher=hierarchie()), timeout=2)
    assert leer.value.rueckfall is True
    with pytest.raises(on.OneNoteFehler) as geschuetzt:
        on.ziel_pruefen(fabrik=lambda: App(vorhanden=[abschnitt("W.A.I.S.", locked="true")]), timeout=2)
    assert geschuetzt.value.rueckfall is False
    on._SPERRE.acquire()
    try:
        with pytest.raises(on.OneNoteFehler) as belegt:
            on.ziel_pruefen(fabrik=lambda: App(), timeout=2, warten=0.05)
        assert belegt.value.rueckfall is False
    finally:
        on._SPERRE.release()


def test_fehler_aus_dem_faden_tragen_keine_com_rahmen():
    stand: dict = {}
    on._SPERRE.acquire()  # _lauf gibt die Sperre am Ende frei
    on._lauf(lambda app: app.CreateNewPage("{x}"), lambda: App(fehler_bei="CreateNewPage"), stand)
    assert isinstance(stand["fehler"], on.OneNoteFehler) and stand["fehler"].__traceback__ is None
    assert stand["fehler"].__cause__ is None and not on._SPERRE.locked()


# ---------- Integrationstest am Gerät ----------
@pytest.mark.office
@pytest.mark.skipif(sys.platform != "win32" or os.getenv("WAMO_OFFICE_ECHT") != "1",
                    reason="nur am Windows-PC mit OneNote und WAMO_OFFICE_ECHT=1")
def test_echtes_onenote_legt_seite_im_eigenen_test_abschnitt_an_und_raeumt_auf():
    if not on.onenote_vorhanden():
        pytest.skip("OneNote für den Desktop ist nicht installiert")
    name = f"Test {secrets.token_hex(3)} W.A.I.S."  # endet wie der echte Abschnitt mit dem Punkt
    ziel = on.ziel_pruefen(abschnitt=name)
    assert ziel.abschnitt_id == "", "Den Test-Abschnitt gibt es schon, der Test ändert nie Vorhandenes"
    seite = on.seite_pruefen({"art": "dokument", "titel": "Prüfung W.A.I.S.", "text": f"# Kopf\n- eins\n{BOESE} **fett**"})
    try:
        ergebnis = on.seite_anlegen(seite, ziel, zeigen=False)
        assert ergebnis["abschnitt_neu"] is True
        xml = on._im_faden(lambda app: app.GetPageContent(ergebnis["seite_id"], xsSchema=on.XS_2013), on.LESEN_TIMEOUT_SECS)
        baum = ET.fromstring(xml)
        assert baum.find(f"{NS}Title/{NS}OE/{NS}T").text.strip() == "Prüfung W.A.I.S."
        alles = "".join(t.text or "" for t in baum.iter(NS + "T"))
        assert "&lt;a href=" in alles and "&lt;b&gt;fett&lt;/b&gt;" in alles and "eins" in alles
        assert baum.find(f".//{NS}Image") is None
        namen = on._im_faden(lambda app: app.GetHierarchy(ziel.notizbuch_id, on.HS_ABSCHNITTE, xsSchema=on.XS_2013),
                             on.LESEN_TIMEOUT_SECS)
        assert on.abschnitt_suchen(namen, ziel.notizbuch_id, name) == ergebnis["abschnitt_id"]  # der Punkt am Ende bleibt
        for inhalt, pruefen in ((TABELLE_ECHT, lambda b: len(b.findall(f".//{NS}Row")) == 3), (CODE_ECHT, _code_ok)):
            weitere = on.seite_anlegen(on.seite_pruefen(inhalt), ziel, zeigen=False)
            assert weitere["abschnitt_neu"] is False and weitere["abschnitt_id"] == ergebnis["abschnitt_id"]
            xml = on._im_faden(lambda app, s=weitere["seite_id"]: app.GetPageContent(s, xsSchema=on.XS_2013), on.LESEN_TIMEOUT_SECS)
            assert pruefen(ET.fromstring(xml)), xml[:2000]
        print(f"OneNote: Seite in {ergebnis['notizbuch']!r}, Abschnitt {name!r} angelegt und gelesen")
    finally:
        _test_abschnitt_loeschen(ziel.notizbuch_id, name)


TABELLE_ECHT = {"art": "tabelle", "titel": "Tabelle", "spalten": ["Name", "Wert"], "zeilen": [["<b>", "=1+1"], ["ä", ""]]}
CODE_ECHT = {"art": "code", "titel": "Code", "text": "def f():\n    return '<x>'", "sprache": "python"}


def _code_ok(baum: ET.Element) -> bool:
    texte = [t.text or "" for t in baum.iter(NS + "T")]
    return any("return" in t and "&lt;x&gt;" in t for t in texte) and any("Consolas" in (oe.get("style") or "") + "".join(
        t.get("style") or "" for t in oe.iter(NS + "T")) for oe in baum.iter(NS + "OE"))


def _test_abschnitt_loeschen(notizbuch_id: str, name: str) -> None:
    """Löscht genau den Abschnitt, den dieser Test angelegt hat: Name mit Zufallsteil, vor dem Test gab es ihn nicht (oben geprüft).
    Läuft auch, wenn das Anlegen mittendrin scheiterte."""
    assert re.fullmatch(r"Test [0-9a-f]{6} W\.A\.I\.S\.", name)

    def loeschen(app):
        abschnitt_id = on.abschnitt_suchen(app.GetHierarchy(notizbuch_id, on.HS_ABSCHNITTE, xsSchema=on.XS_2013), notizbuch_id, name)
        if abschnitt_id:
            app.DeleteHierarchy(abschnitt_id, dateExpectedLastModified=on.OHNE_DATUM, deletePermanently=True)
        return on.abschnitt_suchen(app.GetHierarchy(notizbuch_id, on.HS_ABSCHNITTE, xsSchema=on.XS_2013), notizbuch_id, name)

    assert on._im_faden(loeschen, on.SCHREIBEN_TIMEOUT_SECS) == "", "Test-Abschnitt nicht gelöscht, bitte in OneNote entfernen"
    print(f"OneNote: Test-Abschnitt {name!r} wieder gelöscht")
