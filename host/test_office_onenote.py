"""Tests für OneNote per COM (office_onenote.py): Erkennung, OneDrive der Firma, Notizbuch W.A.I.S., Abschnitt, Seiten-XML,
Kartentext, Ablauf mit einer Attrappe von OneNote, Zeitgrenze und Sperre. Konten und Adressen sind erfunden.

OneNote läuft hier nie wirklich. Nur der letzte Test spricht mit dem echten OneNote am PC (WAMO_OFFICE_ECHT=1): Im vorhandenen Notizbuch
W.A.I.S. im OneDrive der Firma legt er einen eigenen Test-Abschnitt an, schreibt Seiten hinein, liest sie zurück und löscht danach genau
diesen Abschnitt wieder. Fehlt das Notizbuch, überspringt er sich; er legt es nie an.
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


KONTO = on.Firmenkonto("anna@firma.example", "https://firma-my.sharepoint.com/personal/anna_firma_example")
FIRMA_NB = f"{KONTO.site}/Documents/W.A.I.S/"
ADRESSE = f"{KONTO.site}/Documents/W.A.I.S"


def hierarchie(*buecher: tuple[str, str, str, str]) -> str:
    """Antwort von GetHierarchy für die Notizbücher: (ID, Name, Anzeigename, Pfad)."""
    innen = "".join(f'<one:Notebook name="{n}" nickname="{k}" ID="{i}" path="{p}" />' for i, n, k, p in buecher)
    return f'<?xml version="1.0"?><one:Notebooks xmlns:one="{on.NS}">{innen}</one:Notebooks>'


def abschnitte(nb_id: str, *eintraege: str) -> str:
    return f'<one:Notebook xmlns:one="{on.NS}" ID="{nb_id}" name="x">{"".join(eintraege)}</one:Notebook>'


def abschnitt(name: str, sid: str = AB_ID, **attr) -> str:
    extra = "".join(f' {k}="{v}"' for k, v in attr.items())
    return f'<one:Section name="{name}" ID="{sid}" path="p"{extra} />'


FREMD = (NB2_ID, "Hochschule", "Hochschule", "https://d.docs.live.net/abc/Dokumente/Hochschule/")
BUECHER = hierarchie((NB_ID, "W.A.I.S", "W.A.I.S.", FIRMA_NB), FREMD)
OHNE_WAIS = hierarchie(FREMD)


def ziel(notizbuch_id: str = NB_ID, abschnitt_id: str = AB_ID) -> on.Ziel:
    return on.Ziel(konto=KONTO.konto, notizbuch_url=ADRESSE, notizbuch_id=notizbuch_id, notizbuch="W.A.I.S.", abschnitt="W.A.I.S",
                   abschnitt_id=abschnitt_id)


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


# ---------- OneDrive der Firma und Notizbuch W.A.I.S. ----------
FIRMA = {"UserEmail": "anna@firma.example", "ServiceEndpointUri": f"{KONTO.site}/_api"}
SCHULE = {"UserEmail": "anna@hochschule.example",
          "ServiceEndpointUri": "https://hochschule-my.sharepoint.com/personal/anna_hochschule_example/_api"}


def test_firmenkonto_ist_das_einzige_onedrive_for_business():
    assert on.firmenkonto(konten=[FIRMA], domaenen="") == KONTO
    assert on.notizbuch_adresse(KONTO) == ADRESSE


@pytest.mark.parametrize("konten, domaenen, text", [
    ([], "", "kein OneDrive der Firma"),
    ([FIRMA, SCHULE], "", "mehrere"),
    ([SCHULE], "firma.example", "kein OneDrive der Firma"),
    ([{**FIRMA, "ServiceEndpointUri": "https://boese.example/personal/x/_api"}], "", "kein OneDrive der Firma"),
    ([{**FIRMA, "UserEmail": "ohne-domaene"}], "", "kein OneDrive der Firma"),
])
def test_kein_eindeutiges_firmenkonto_heisst_rueckfall(konten, domaenen, text):
    with pytest.raises(on.OneNoteFehler, match=text) as fehler:
        on.firmenkonto(konten=konten, domaenen=domaenen)
    assert fehler.value.rueckfall is True


def test_domaene_grenzt_mehrere_konten_ein(monkeypatch):
    assert on.firmenkonto(konten=[FIRMA, SCHULE], domaenen="@Firma.example, andere.example") == KONTO
    monkeypatch.setenv(on.DOMAENE_ENV, "firma.example")
    assert on.firmenkonto(konten=[SCHULE, FIRMA]) == KONTO


def test_notizbuch_nur_im_onedrive_der_firma():
    assert on.notizbuch_finden(BUECHER, KONTO) == NB_ID
    assert on.notizbuch_finden(OHNE_WAIS, KONTO) == ""  # fehlt: wird erst nach dem Klick angelegt
    nur_name = hierarchie((NB_ID, "W.A.I.S.", "Anders", FIRMA_NB))
    assert on.notizbuch_finden(nur_name, KONTO) == NB_ID
    praefix = hierarchie((NB_ID, "W.A.I.S", "W.A.I.S.", "https://firma-my.sharepoint.com/personal/anna_firma_example2/x/"))
    with pytest.raises(on.OneNoteFehler, match="nicht im OneDrive der Firma"):
        on.notizbuch_finden(praefix, KONTO)


def test_notizbuch_w_a_i_s_anderswo_oder_doppelt_heisst_rueckfall():
    woanders = hierarchie((NB2_ID, "W.A.I.S.", "W.A.I.S.", "https://d.docs.live.net/abc/W.A.I.S./"))
    with pytest.raises(on.OneNoteFehler, match="nicht im OneDrive der Firma") as fehler:
        on.notizbuch_finden(woanders, KONTO)
    assert fehler.value.rueckfall is True
    doppelt = hierarchie((NB_ID, "W.A.I.S", "W.A.I.S.", FIRMA_NB), (NB2_ID, "W.A.I.S 2", "W.A.I.S.", f"{KONTO.site}/Documents/x/"))
    with pytest.raises(on.OneNoteFehler, match="mehrere"):
        on.notizbuch_finden(doppelt, KONTO)
    with pytest.raises(on.OneNoteFehler):
        on.notizbuch_finden("kein xml", KONTO)


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


def test_ziel_der_karte_nennt_notizbuch_abschnitt_und_konto():
    assert on.karten_ziel(ziel()) == "OneNote, Notizbuch W.A.I.S., Abschnitt W.A.I.S, OneDrive der Firma (anna@firma.example)"
    neu = on.karten_ziel(ziel("", ""))
    assert "Notizbuch W.A.I.S. (wird neu angelegt), Abschnitt W.A.I.S (wird angelegt)" in neu
    lang = on.karten_ziel(on.Ziel("k" * 300, ADRESSE, "", "N" * 300, "W.A.I.S", ""))
    assert len(lang) <= 200


# ---------- Ablauf mit einer Attrappe von OneNote ----------
class App:
    """Attrappe der COM-Schnittstelle: merkt sich jeden Aufruf."""

    def __init__(self, buecher=BUECHER, vorhanden=(), fehler_bei=None, nicht_synchron=0):
        self.aufrufe: list[tuple] = []
        self.buecher, self.vorhanden, self.fehler_bei, self.nicht_synchron = buecher, list(vorhanden), fehler_bei, nicht_synchron

    def _merken(self, *aufruf):
        self.aufrufe.append(aufruf)
        if self.fehler_bei == aufruf[0]:
            fehler = OSError("COM")
            fehler.hresult = -2147213311  # 0x80042001: XML ungültig
            raise fehler

    def GetHierarchy(self, start, scope, xsSchema):  # noqa: N802, N803 (Namen der COM-Schnittstelle)
        self._merken("GetHierarchy", start, scope, xsSchema)
        return self.buecher if start == "" else abschnitte(start, *self.vorhanden)

    def OpenHierarchy(self, pfad, relativ, cftIfNotExist):  # noqa: N802, N803
        self._merken("OpenHierarchy", pfad, relativ, cftIfNotExist)
        return "{nb-neu}" if cftIfNotExist == on.CFT_NOTIZBUCH else "{ab-neu}"

    def UpdateHierarchy(self, xml, xsSchema):  # noqa: N802, N803
        self._merken("UpdateHierarchy", xml, xsSchema)

    def SyncHierarchy(self, objekt):  # noqa: N802
        self._merken("SyncHierarchy", objekt)

    def CreateNewPage(self, abschnitt_id):  # noqa: N802
        self._merken("CreateNewPage", abschnitt_id)
        if self.nicht_synchron:
            self.nicht_synchron -= 1
            fehler = OSError("noch nicht synchronisiert")
            fehler.hresult = on.NICHT_SYNCHRON - (1 << 32)  # wie comtypes: vorzeichenbehaftet
            raise fehler
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


def anlegen(app, erwartet=None, **kw):
    return on.seite_anlegen(SEITE, erwartet or ziel(), konto=KONTO, fabrik=lambda: app, **kw)


def test_ziel_lesen_aendert_nichts():
    app = App(vorhanden=[abschnitt("W.A.I.S")])
    assert on.ziel_pruefen(konto=KONTO, fabrik=lambda: app) == ziel()
    assert {a[0] for a in app.aufrufe} == {"GetHierarchy"}
    assert all(a[-1] == on.XS_2013 for a in app.aufrufe)


def test_fehlendes_notizbuch_wird_nur_angekuendigt():
    app = App(buecher=OHNE_WAIS)
    assert on.ziel_pruefen(konto=KONTO, fabrik=lambda: app) == ziel("", "")
    assert [a[0] for a in app.aufrufe] == ["GetHierarchy"]  # nichts angelegt, keine Abschnitte gelesen


def test_seite_im_vorhandenen_abschnitt():
    app = App(vorhanden=[abschnitt("W.A.I.S")])
    ergebnis = anlegen(app)
    assert ergebnis == {"seite_id": SEITE_ID, "abschnitt_id": AB_ID, "abschnitt_neu": False, "notizbuch_neu": False,
                        "notizbuch": "W.A.I.S.", "abschnitt": "W.A.I.S"}
    namen = [a[0] for a in app.aufrufe]
    assert not {"OpenHierarchy", "UpdateHierarchy", "DeleteHierarchy"} & set(namen)
    assert ("CreateNewPage", AB_ID) in app.aufrufe
    update = next(a for a in app.aufrufe if a[0] == "UpdatePageContent")
    assert update[2] == on.XS_2013 and ET.fromstring(update[1]).get("ID") == SEITE_ID and GEHEIM in update[1]
    assert app.aufrufe[-1] == ("NavigateTo", SEITE_ID)


def test_fehlender_abschnitt_wird_angelegt_und_nichts_gezeigt():
    app = App()
    ergebnis = anlegen(app, ziel(NB_ID, ""), zeigen=False)
    assert ergebnis["abschnitt_neu"] is True and ergebnis["abschnitt_id"] == "{ab-neu}"
    assert ("OpenHierarchy", "W.A.I.S.one", NB_ID, on.CFT_ABSCHNITT) in app.aufrufe
    assert ("SyncHierarchy", "{ab-neu}") in app.aufrufe
    assert ("CreateNewPage", "{ab-neu}") in app.aufrufe
    assert "NavigateTo" not in [a[0] for a in app.aufrufe]


def test_fehlendes_notizbuch_entsteht_erst_nach_dem_klick_im_onedrive_der_firma():
    app = App(buecher=OHNE_WAIS)
    ergebnis = anlegen(app, ziel("", ""), zeigen=False)
    assert ergebnis["notizbuch_neu"] is True and ergebnis["abschnitt_neu"] is True
    assert ("OpenHierarchy", ADRESSE, "", on.CFT_NOTIZBUCH) in app.aufrufe
    nickname = next(a for a in app.aufrufe if a[0] == "UpdateHierarchy")
    knoten = ET.fromstring(nickname[1]).find(f"{NS}Notebook")
    assert (knoten.get("ID"), knoten.get("nickname")) == ("{nb-neu}", "W.A.I.S.")
    assert ("OpenHierarchy", "W.A.I.S.one", "{nb-neu}", on.CFT_ABSCHNITT) in app.aufrufe


def test_frischer_abschnitt_wartet_auf_den_abgleich():
    app = App(nicht_synchron=2)
    ergebnis = anlegen(app, ziel(NB_ID, ""), zeigen=False)
    assert ergebnis["seite_id"] == SEITE_ID
    assert [a[0] for a in app.aufrufe].count("CreateNewPage") == 3


def test_anderes_notizbuch_oder_konto_seit_der_anfrage_bricht_ab():
    app = App(buecher=hierarchie((NB2_ID, "W.A.I.S", "W.A.I.S.", FIRMA_NB)))
    with pytest.raises(on.OneNoteFehler, match="Notizbuch W.A.I.S. hat sich"):
        anlegen(app)
    anders = on.Firmenkonto("max@firma.example", "https://firma-my.sharepoint.com/personal/max_firma_example")
    with pytest.raises(on.OneNoteFehler, match="OneDrive der Firma hat sich"):
        on.seite_anlegen(SEITE, ziel(), konto=anders, fabrik=lambda: app)
    assert not {"OpenHierarchy", "CreateNewPage", "UpdatePageContent"} & {a[0] for a in app.aufrufe}


def test_fehler_beim_schreiben_raeumt_nur_die_eigene_neue_seite_weg():
    app = App(vorhanden=[abschnitt("W.A.I.S")], fehler_bei="UpdatePageContent")
    with pytest.raises(on.OneNoteFehler, match="0x80042001"):
        anlegen(app)
    loeschen = [a for a in app.aufrufe if a[0] == "DeleteHierarchy"]
    assert loeschen == [("DeleteHierarchy", SEITE_ID, True)]


@pytest.mark.parametrize("abschnitt_name, notizbuch_name, ordner", [("W.A.I.S.", "W.A.I.S.", "W.A.I.S"),
                                                                    ("W.A.I.S", "W.A.I.S.", "W.A.I.S."), ("a/b", "x", "y")])
def test_namen_mit_punkt_am_ende_oder_trennern_gehen_nicht(abschnitt_name, notizbuch_name, ordner):
    with pytest.raises(on.OneNoteFehler, match="Ungültiger Name"):
        on.ziel_pruefen(abschnitt_name, notizbuch=notizbuch_name, ordner=ordner, konto=KONTO, fabrik=lambda: App())


def test_zeitgrenze_und_nur_ein_zugriff_zur_zeit():
    los = threading.Event()

    def haengt():
        los.wait(5)
        return App()

    start = time.monotonic()
    with pytest.raises(on.OneNoteFehler, match="nicht in der Zeit"):
        on.ziel_pruefen(konto=KONTO, fabrik=haengt, timeout=0.2)
    assert time.monotonic() - start < 2
    with pytest.raises(on.OneNoteFehler, match="beschäftigt"):
        on.ziel_pruefen(konto=KONTO, fabrik=lambda: App(), timeout=0.2, warten=0.05)
    los.set()
    _warten_bis_frei()
    assert on.ziel_pruefen(konto=KONTO, fabrik=lambda: App(), timeout=2).notizbuch_id == NB_ID


def _warten_bis_frei() -> None:
    for _ in range(50):  # der hängende Faden gibt die Sperre frei, sobald er endet
        if not on._SPERRE.locked():
            return
        time.sleep(0.05)


def test_start_von_onenote_scheitert_lesbar():
    def kaputt():
        raise OSError("Klasse nicht registriert")

    with pytest.raises(on.OneNoteFehler, match="OneNote"):
        on.ziel_pruefen(konto=KONTO, fabrik=kaputt, timeout=2)
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
    app = App(buecher=OHNE_WAIS)
    with pytest.raises(on.OneNoteFehler, match="nachsehen"):
        on._schreiben(app, SEITE, ziel("", ""), False, abbruch, KONTO)
    assert not {"OpenHierarchy", "CreateNewPage"} & {a[0] for a in app.aufrufe}  # auch kein Notizbuch


def test_zeitgrenze_waehrend_des_anlegens_raeumt_die_eigene_seite_weg():
    abbruch = threading.Event()

    class Langsam(App):
        def CreateNewPage(self, abschnitt_id):  # noqa: N802
            abbruch.set()  # so, als wäre die Zeitgrenze genau jetzt abgelaufen
            return super().CreateNewPage(abschnitt_id)

    app = Langsam(vorhanden=[abschnitt("W.A.I.S")])
    with pytest.raises(on.OneNoteFehler):
        on._schreiben(app, SEITE, ziel(), False, abbruch, KONTO)
    assert [a[0] for a in app.aufrufe][-2:] == ["CreateNewPage", "DeleteHierarchy"]
    assert "UpdatePageContent" not in [a[0] for a in app.aufrufe]


def test_schreib_zeitgrenze_warnt_vor_doppelter_seite():
    los = threading.Event()

    def haengt():
        los.wait(5)
        return App()

    with pytest.raises(on.OneNoteFehler, match="bevor du sie noch einmal anlegst"):
        on.seite_anlegen(SEITE, ziel(), konto=KONTO, fabrik=haengt, timeout=0.2)
    los.set()
    _warten_bis_frei()


def test_anderer_abschnitt_gleichen_namens_bricht_ab():
    app = App(vorhanden=[abschnitt("W.A.I.S", "{anderer}")])
    with pytest.raises(on.OneNoteFehler, match="Abschnitt W.A.I.S hat sich"):
        anlegen(app)
    assert "CreateNewPage" not in [a[0] for a in app.aufrufe]


def test_rueckfall_nur_wenn_onenote_nicht_taugt():
    def nicht_registriert():
        raise OSError("nicht registriert")

    with pytest.raises(on.OneNoteFehler, match="startet nicht") as fehlt:
        on.ziel_pruefen(konto=KONTO, fabrik=nicht_registriert, timeout=2)
    assert fehlt.value.rueckfall is True
    with pytest.raises(on.OneNoteFehler) as geschuetzt:
        on.ziel_pruefen(konto=KONTO, fabrik=lambda: App(vorhanden=[abschnitt("W.A.I.S", locked="true")]), timeout=2)
    assert geschuetzt.value.rueckfall is False
    on._SPERRE.acquire()
    try:
        with pytest.raises(on.OneNoteFehler) as belegt:
            on.ziel_pruefen(konto=KONTO, fabrik=lambda: App(), timeout=2, warten=0.05)
        assert belegt.value.rueckfall is False
    finally:
        on._SPERRE.release()


def test_ohne_firmenkonto_wird_onenote_gar_nicht_gefragt(monkeypatch):
    monkeypatch.setattr(on, "_konten_lesen", lambda: [])
    monkeypatch.delenv(on.DOMAENE_ENV, raising=False)
    app = App()
    with pytest.raises(on.OneNoteFehler, match="kein OneDrive der Firma") as fehler:
        on.ziel_pruefen(fabrik=lambda: app)
    assert fehler.value.rueckfall is True and app.aufrufe == []


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
    """Nur im vorhandenen Notizbuch W.A.I.S. im OneDrive der Firma; der Test legt das Notizbuch nie an."""
    if not on.onenote_vorhanden():
        pytest.skip("OneNote für den Desktop ist nicht installiert")
    try:
        konto = on.firmenkonto()
    except on.OneNoteFehler as e:
        pytest.skip(f"Kein eindeutiges OneDrive der Firma: {e}")
    name = f"Test {secrets.token_hex(3)} W.A.I.S"  # wie der echte Abschnitt, ohne Punkt am Ende (SharePoint)
    ziel_echt = on.ziel_pruefen(abschnitt=name, konto=konto)
    if not ziel_echt.notizbuch_id:
        pytest.skip("Das Notizbuch W.A.I.S. ist im OneDrive der Firma nicht offen; der Test legt es nie an")
    assert ziel_echt.abschnitt_id == "", "Den Test-Abschnitt gibt es schon, der Test ändert nie Vorhandenes"
    try:
        _echte_seiten(ziel_echt, konto, name)
    finally:
        _test_abschnitt_loeschen(ziel_echt.notizbuch_id, name)


def _echte_seiten(ziel_echt: on.Ziel, konto: on.Firmenkonto, name: str) -> None:
    seite = on.seite_pruefen({"art": "dokument", "titel": "Prüfung W.A.I.S.", "text": f"# Kopf\n- eins\n{BOESE} **fett**"})
    ergebnis = on.seite_anlegen(seite, ziel_echt, zeigen=False, konto=konto)
    assert ergebnis["abschnitt_neu"] is True and ergebnis["notizbuch_neu"] is False
    baum = ET.fromstring(_seite_lesen(ergebnis["seite_id"]))
    assert baum.find(f"{NS}Title/{NS}OE/{NS}T").text.strip() == "Prüfung W.A.I.S."
    alles = "".join(t.text or "" for t in baum.iter(NS + "T"))
    assert "&lt;a href=" in alles and "&lt;b&gt;fett&lt;/b&gt;" in alles and "eins" in alles
    assert baum.find(f".//{NS}Image") is None
    for inhalt, pruefen in ((TABELLE_ECHT, lambda b: len(b.findall(f".//{NS}Row")) == 3), (CODE_ECHT, _code_ok)):
        weitere = on.seite_anlegen(on.seite_pruefen(inhalt), ziel_echt, zeigen=False, konto=konto)
        assert weitere["abschnitt_id"] == ergebnis["abschnitt_id"]
        xml = _seite_lesen(weitere["seite_id"])
        assert pruefen(ET.fromstring(xml)), xml[:2000]
    print(f"OneNote: Seiten im Notizbuch W.A.I.S., Abschnitt {name!r} angelegt und gelesen")


def _seite_lesen(seiten_id: str) -> str:
    return on._im_faden(lambda app: app.GetPageContent(seiten_id, xsSchema=on.XS_2013), on.LESEN_TIMEOUT_SECS)


TABELLE_ECHT = {"art": "tabelle", "titel": "Tabelle", "spalten": ["Name", "Wert"], "zeilen": [["<b>", "=1+1"], ["ä", ""]]}
CODE_ECHT = {"art": "code", "titel": "Code", "text": "def f():\n    return '<x>'", "sprache": "python"}


def _code_ok(baum: ET.Element) -> bool:
    texte = [t.text or "" for t in baum.iter(NS + "T")]
    return any("return" in t and "&lt;x&gt;" in t for t in texte) and any("Consolas" in (oe.get("style") or "") + "".join(
        t.get("style") or "" for t in oe.iter(NS + "T")) for oe in baum.iter(NS + "OE"))


def _test_abschnitt_loeschen(notizbuch_id: str, name: str) -> None:
    """Löscht genau den Abschnitt, den dieser Test angelegt hat: Name mit Zufallsteil, vor dem Test gab es ihn nicht (oben geprüft).
    Läuft auch, wenn das Anlegen mittendrin scheiterte."""
    assert re.fullmatch(r"Test [0-9a-f]{6} W\.A\.I\.S", name)

    def loeschen(app):
        abschnitt_id = on.abschnitt_suchen(app.GetHierarchy(notizbuch_id, on.HS_ABSCHNITTE, xsSchema=on.XS_2013), notizbuch_id, name)
        if abschnitt_id:
            app.DeleteHierarchy(abschnitt_id, dateExpectedLastModified=on.OHNE_DATUM, deletePermanently=True)
        return on.abschnitt_suchen(app.GetHierarchy(notizbuch_id, on.HS_ABSCHNITTE, xsSchema=on.XS_2013), notizbuch_id, name)

    assert on._im_faden(loeschen, on.SCHREIBEN_TIMEOUT_SECS) == "", "Test-Abschnitt nicht gelöscht, bitte in OneNote entfernen"
    print(f"OneNote: Test-Abschnitt {name!r} wieder gelöscht")
