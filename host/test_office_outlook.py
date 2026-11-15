"""Tests für office_outlook.py und office_outlook_com.py: welches Outlook aktiv ist, Mail über das klassische Outlook (COM) und
Entwurf im neuen Outlook.

Outlook, Prozesse, Registry und Fenster sind Attrappen, Adressen nur aus Beispieldomänen. Die markierten Echttests am Ende laufen nur unter
Windows mit WAMO_OUTLOOK_ECHT=1: Der erste liest nur (Erkennung, nie ein Start), der zweite öffnet mit WAMO_OUTLOOK_ENTWURF=1 zusätzlich
einen Entwurf an die Adresse aus WAMO_OUTLOOK_TESTADRESSE im neuen Outlook (danach in Outlook verwerfen). Gesendet wird in keinem Test.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import office_outlook as oo
import office_outlook_com as oc

INTERN = "max.weber@firma.example"
KONTO = "konto@firma.example"
TEST_BETREFF = "W.A.I.S. Test, bitte löschen"


@pytest.fixture(autouse=True)
def _interne_domaene(monkeypatch):
    monkeypatch.setenv("WAMO_MAIL_INTERN", "firma.example")


# ---------- Attrappen für das klassische Outlook (COM) ----------
class Liste:
    """COM-Sammlung: Count und Item(i) ab 1."""

    def __init__(self, elemente=()):
        self.e = list(elemente)

    @property
    def Count(self):  # noqa: N802 (COM-Namen)
        return len(self.e)

    def Item(self, i):  # noqa: N802
        return self.e[i - 1]


class Eintrag:
    """AddressEntry: art 0 Exchange-Benutzer, 1 Verteiler, 30 SMTP."""

    def __init__(self, name, smtp, art=0):
        self.Name, self._smtp, self.AddressEntryUserType = name, smtp, art
        self.Type = "SMTP" if art == 30 else "EX"
        self.Address = smtp if art == 30 else "/o=ExchangeLabs/cn=Recipients/cn=x"

    def GetExchangeUser(self):  # noqa: N802
        return SimpleNamespace(PrimarySmtpAddress=self._smtp)


MEHRDEUTIG = object()


class Empfaenger:
    def __init__(self, adressbuch, wert):
        self._ab, self._wert, self.Type, self.AddressEntry = adressbuch, wert, 1, None

    def Resolve(self):  # noqa: N802
        e = self._ab.get(self._wert.lower())
        if e is MEHRDEUTIG:
            return False
        if e is None and "@" in self._wert:
            e = Eintrag(self._wert, self._wert, art=30)
        self.AddressEntry = e
        return e is not None


class Empfaengerliste(Liste):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def Add(self, wert):  # noqa: N802
        r = Empfaenger(self.app.adressbuch, wert)
        self.e.append(r)
        return r


class Anlagen(Liste):
    def Add(self, pfad):  # noqa: N802
        daten = Path(pfad).read_bytes()
        a = SimpleNamespace(FileName=Path(pfad).name, Size=len(daten), daten=daten)
        self.e.append(a)
        return a


class Mail:
    def __init__(self, app):
        self.app, self.Subject, self.Sent, self.EntryID = app, "", False, ""
        self.HTMLBody, self.Body = "<html><head></head><body lang=DE></body></html>", ""
        self.Recipients, self.Attachments = Empfaengerliste(app), Anlagen()
        self.Parent, self._insp, self.Session = SimpleNamespace(StoreID="store-1"), False, app.Session
        self._konto, self._konto_gilt, self.gesendet_mit = None, True, None

    @property
    def SendUsingAccount(self):  # noqa: N802 (am Gerät: nach GetItemFromID liest sich das Konto des Entwurfs leer)
        return self._konto if self._konto_gilt else None

    @SendUsingAccount.setter
    def SendUsingAccount(self, wert):  # noqa: N802
        self._konto, self._konto_gilt = wert, True

    def wieder_geoeffnet(self):
        self._konto_gilt = False

    @property
    def GetInspector(self):  # noqa: N802 (Zugriff fügt wie in Outlook die Standardsignatur ein und öffnet einen Inspector)
        if not any(i.CurrentItem is self for i in self.app.Inspectors.e):
            self.app.Inspectors.e.append(SimpleNamespace(CurrentItem=self))
        if not self._insp and self.app.signatur:
            self._insp = True
            self.HTMLBody = f"<html><head></head><body lang=DE><div id=sig>{self.app.signatur}</div></body></html>"
            self.Body = self.app.signatur
        return object()

    def Save(self):  # noqa: N802 (am Gerät: die Anhänge sind nach dem Speichern größer, MAPI-Verwaltungsdaten)
        self.EntryID = self.EntryID or f"entry-{len(self.app.gespeichert) + 1}"
        self.app.gespeichert[self.EntryID] = self
        for a in self.Attachments.e:
            a.Size = len(a.daten) + 8065

    def Send(self):  # noqa: N802 (wie am Gerät: mit offenem Inspector scheitert Send mit "Falscher Parameter")
        if self.app.send_fehler is not None:
            raise self.app.send_fehler
        if any(i.CurrentItem is self for i in self.app.Inspectors.e):
            raise RuntimeError("Falscher Parameter")
        if self.app.send_dauer:
            time.sleep(self.app.send_dauer)
        self.Sent = True
        self.gesendet_mit = self.SendUsingAccount.SmtpAddress if self.SendUsingAccount is not None else None
        self.app.gesendet.append(self)

    def Display(self, modal=False):  # noqa: N802
        self.app.angezeigt.append(self)

    def Close(self, art):  # noqa: N802
        self.app.geschlossen.append(art)
        self.app.Inspectors.e = [i for i in self.app.Inspectors.e if i.CurrentItem is not self]


class Outlook:
    def __init__(self, adressbuch=None, konten=None, signatur="-- \nMit freundlichen Grüßen\nTestperson"):
        self.adressbuch = {k.lower(): v for k, v in (adressbuch or {}).items()}
        self.signatur, self.mails, self.gespeichert, self.gesendet, self.angezeigt, self.geschlossen = signatur, [], {}, [], [], []
        self.Inspectors, self.send_fehler, self.send_dauer, self.lese_dauer = Liste(), None, 0.0, 0.0
        konten = konten or [SimpleNamespace(SmtpAddress=KONTO, DisplayName="Konto", DeliveryStore=SimpleNamespace(StoreID="store-1"))]
        self.Session = SimpleNamespace(
            Accounts=Liste(konten), DefaultStore=SimpleNamespace(StoreID="store-1"), CurrentUser=SimpleNamespace(Name="Konto Test"),
            CreateRecipient=lambda wert: Empfaenger(self.adressbuch, wert),
            GetItemFromID=self._holen)

    def _holen(self, entry, store):
        if self.lese_dauer:
            time.sleep(self.lese_dauer)
        item = self.gespeichert[entry]
        item.wieder_geoeffnet()
        return item

    def CreateItem(self, art):  # noqa: N802
        assert art == 0
        m = Mail(self)
        self.mails.append(m)
        return m


@pytest.fixture
def outlook(monkeypatch):
    o = Outlook(adressbuch={"Max Weber": Eintrag("Max Weber", INTERN), "Anna": MEHRDEUTIG,
                            "Alle": Eintrag("Alle", "alle@firma.example", art=1)})
    monkeypatch.setattr(oc, "_outlook_app", lambda: o)
    return o


def anhang(tmp_path, name="2026-11-15 Angebot.pdf", daten=b"%PDF-1.7 Angebot"):
    p = tmp_path / name
    p.write_bytes(daten)
    return oo.Anhang(kennung="0123456789abcdef", name=name, pfad=p, groesse=len(daten), sha256=hashlib.sha256(daten).hexdigest())


def mail(tmp_path=None, an=(("an", "Max Weber", INTERN, False),), text="Hallo Max,\n\nanbei das Angebot.", betreff="Angebot",
         mit_anhang=True):
    empf = tuple(oo.Empfaenger(art=a, name=n, smtp=s, extern=x) for a, n, s, x in an)
    anh = (anhang(tmp_path),) if (mit_anhang and tmp_path is not None) else ()
    return oo.Mail(empfaenger=empf, betreff=betreff, text=text, anhaenge=anh)


# ---------- Eingaben ----------
@pytest.mark.parametrize("wert,erwartet", [
    (INTERN, INTERN), (" Max.Weber@FIRMA.example ", "Max.Weber@firma.example"),
    ("anna@müller.example", "anna@xn--mller-kva.example"), ("a@b", None), ("kein at", None), ("a@@b.de", None), ("a b@c.de", None),
    ("x@localhost", None), ("x@-b.de", None), ("x@b.de\r\nBcc: y@z.de", None), ("ä@b.de", None), (5, None), ("", None)])
def test_adresse(wert, erwartet):
    assert oo.adresse(wert) == erwartet


def test_eingaben_grenzen_und_doppelte():
    assert oo.eingaben(["Max Weber", "a@b.example"], ["c@d.example"]) == [
        ("an", "Max Weber"), ("an", "a@b.example"), ("cc", "c@d.example")]
    for an, cc in ((["a@b.example"] * 2, []), ([], []), ("a@b.example", []),
                   ([f"x{i}@b.example" for i in range(8)], ["y@b.example", "z@b.example", "w@b.example"]),
                   (["a@b.example"], ["A@B.example"]), (["Zeile\nzwei"], []), ([5], []), (["x" * 255], [])):
        with pytest.raises(oo.MailFehler):
            oo.eingaben(an, cc)


def test_betreff_und_text_werden_wie_auf_der_karte_bereinigt():
    assert oo.betreff("  Angebot\u200b  Kunde  ") == "Angebot Kunde"
    for kaputt in ("", "   ", "x" * 201, 5):
        with pytest.raises(oo.MailFehler):
            oo.betreff(kaputt)
    # unsichtbare und Richtungszeichen werden zu Leerzeichen, Zeilenenden einheitlich, Zeilenenden ohne Leerzeichen am Ende
    assert oo.text("Hallo\u202eMax  \r\nzwei\tdrei\r\n\r\n") == "Hallo Max\nzwei drei"
    with pytest.raises(oo.MailFehler):
        oo.text("x" * (oo.TEXT_MAX + 1))


def test_nur_adressen_im_neuen_outlook_und_extern_markiert(monkeypatch):
    empf = oo.empfaenger_adressen([("an", "Max@FIRMA.example"), ("cc", "anna@kunde.example")], oo.interne_domaenen())
    assert [(e.art, e.smtp, e.extern) for e in empf] == [("an", "Max@firma.example", False), ("cc", "anna@kunde.example", True)]
    with pytest.raises(oo.MailFehler, match="Mailadresse"):
        oo.empfaenger_adressen([("an", "Max Weber")], oo.interne_domaenen())
    monkeypatch.setenv("WAMO_MAIL_INTERN", "firma.example, firma2.example")
    assert oo.interne_domaenen("konto@partner.example") == {"firma.example", "firma2.example", "partner.example"}
    monkeypatch.delenv("WAMO_MAIL_INTERN")
    assert oo.interne_domaenen() == set(oo.INTERN_STANDARD)


# ---------- Erkennung ----------
def lage(**kw):
    basis = dict(klassisch_laeuft=False, neu_laeuft=False, umschalter_neu=False, com_registriert=True, profil=True, olk_alias=True,
                 mailto="Outlook.URL.mailto.15", eml="Outlook.File.eml.15")
    return oo.Lage(**{**basis, **kw})


def test_neues_outlook_aktiv_heisst_entwurf_auch_wenn_das_klassische_installiert_ist():
    gefragt = []
    w = oo.erkennen(lage(neu_laeuft=True), com_ok=lambda: gefragt.append(1) or True)
    assert (w.weg, w.programm) == ("entwurf", "neu")
    assert gefragt == []  # COM wird nicht einmal gefragt
    w = oo.erkennen(lage(neu_laeuft=True, klassisch_laeuft=True), com_ok=lambda: True)
    assert (w.weg, w.programm) == ("entwurf", "neu")  # beide offen: im Zweifel der Entwurf


def test_klassisch_aktiv_heisst_senden():
    w = oo.erkennen(lage(klassisch_laeuft=True), com_ok=lambda: True)
    assert (w.weg, w.programm) == ("senden", "klassisch")
    assert "30 Sekunden" in w.grund


@pytest.mark.parametrize("abweichung,weg", [
    ({"umschalter_neu": True}, ("entwurf", "klassisch")), ({"com_registriert": False}, ("keiner", "")),
    ({"profil": False}, ("keiner", "")), ({"_com": False}, ("keiner", ""))])
def test_klassisch_im_zweifel_nie_senden(abweichung, weg):
    com = abweichung.pop("_com", True)
    w = oo.erkennen(lage(klassisch_laeuft=True, **abweichung), com_ok=lambda: com)
    assert (w.weg, w.programm) == weg
    assert w.grund


def test_nichts_offen_oder_kein_alias():
    gefragt = []
    w = oo.erkennen(lage(), com_ok=lambda: gefragt.append(1) or True)
    assert w.weg == "keiner" and "nicht geöffnet" in w.grund
    assert gefragt == []  # nie ein Start des klassischen Outlooks über COM
    assert oo.erkennen(lage(neu_laeuft=True, olk_alias=False), com_ok=lambda: True).weg == "keiner"


def test_erkennung_ausserhalb_von_windows(monkeypatch):
    monkeypatch.setattr(oo.sys, "platform", "linux")
    assert oo.erkennen().weg == "keiner"


def test_lage_aus_prozessen_und_registry(monkeypatch):
    werte = {("HKCU", oo.PFAD_PREFERENCES, "UseNewOutlook"): 1, ("HKCR", r"Outlook.Application\CLSID", None): True,
             ("HKCU", oo.PFAD_MAILTO, "ProgId"): "AppX1scw7cgxcz9hmq03sd8qajzg3s9t7901"}
    monkeypatch.setattr(oo, "laufende_programme", lambda: {"olk.exe", "explorer.exe"})
    monkeypatch.setattr(oo, "_reg", lambda wurzel, pfad, name=None: werte.get((wurzel, pfad, name)))
    monkeypatch.setattr(oo, "_unterschluessel", lambda pfad: 1)
    monkeypatch.setattr(oo.os.path, "lexists", lambda p: True)
    lg = oo.lage_lesen()
    assert lg.neu_laeuft and not lg.klassisch_laeuft and lg.umschalter_neu and lg.com_registriert and lg.profil and lg.olk_alias
    assert lg.mailto.startswith("AppX")


def test_programme_aus_tasklist():
    text = ('"System Idle Process","0","Services","0","8 K"\r\n"olk.exe","5368","Console","1","120.000 K"\r\n'
            '"OUTLOOK.EXE","9","C","1","1 K"\r\n')
    assert oo._programme_aus_tasklist(text) >= {"olk.exe", "outlook.exe"}


# ---------- Karte ----------
def test_karte_zeigt_alles_was_rausgeht(tmp_path):
    m = mail(tmp_path, an=(("an", "Max Weber", INTERN, False), ("cc", "", "anna@xn--mller-kva.example", True)),
             text="Hallo Max,\nAn: boese@x.example\n\nGruß")
    w = oo.Weg("senden", "klassisch", "Outlook (klassisch) läuft: W.A.I.S. sendet nach deinem Klick, 30 Sekunden lang zurückholbar.")
    karte = oo.kartentext(m, w, {"smtp": KONTO, "name": "Konto Test"}, "-- \nMit freundlichen Grüßen\nTestperson")
    zeilen = karte.split("\n")
    assert zeilen[0].startswith("So geht es: Outlook (klassisch)")
    assert f"Von: Konto Test <{KONTO}>" in zeilen
    assert f"An: Max Weber <{INTERN}> (intern)" in zeilen
    assert "Cc: anna@xn--mller-kva.example (EXTERN, Domäne in Punycode)" in zeilen
    assert "Betreff: Angebot" in zeilen
    assert any(z.startswith("Anhang: 2026-11-15 Angebot.pdf (") and "Prüfsumme" in z for z in zeilen)
    # jede Zeile des Textes mit Präfix: "An: boese@x.example" im Text sieht nie wie ein Kopf aus
    assert "> An: boese@x.example" in zeilen and "An: boese@x.example" not in zeilen
    assert "Signatur aus Outlook:" in zeilen and "> Mit freundlichen Grüßen" in zeilen


def test_karte_im_neuen_outlook(tmp_path):
    w = oo.Weg("entwurf", "neu", "Das neue Outlook läuft: W.A.I.S. öffnet einen fertigen Entwurf, du sendest selbst.")
    karte = oo.kartentext(mail(tmp_path), w, None, None)
    assert "du sendest selbst" in karte and "Von:" not in karte
    assert "Signatur: fügt das neue Outlook selbst an" in karte


# ---------- Neues Outlook: Entwurf als .eml ----------
def test_eml_traegt_empfaenger_betreff_text_html_und_anhang(tmp_path):
    m = mail(tmp_path, an=(("an", "", INTERN, False), ("cc", "", "anna@kunde.example", True)), text="Hallo <b>Max</b>,\n\nGruß & Dank")
    roh = oo.eml(m, oo.anhaenge_lesen(m.anhaenge))
    nachricht = email.message_from_bytes(roh, policy=email.policy.default)
    assert nachricht["To"] == INTERN and nachricht["Cc"] == "anna@kunde.example"
    assert nachricht["Subject"] == "Angebot" and nachricht["X-Unsent"] == "1"
    assert nachricht["From"] is None and nachricht["Bcc"] is None
    assert nachricht.get_body(("plain",)).get_content().startswith("Hallo <b>Max</b>,")
    html_teil = nachricht.get_body(("html",)).get_content()
    assert "&lt;b&gt;Max&lt;/b&gt;" in html_teil and "<b>" not in html_teil and "Gruß &amp; Dank" in html_teil
    anlagen = list(nachricht.iter_attachments())
    assert [(a.get_filename(), a.get_content_type(), a.get_content()) for a in anlagen] == [
        ("2026-11-15 Angebot.pdf", "application/pdf", b"%PDF-1.7 Angebot")]
    assert b"\r\n" in roh


def test_eml_mit_umlaut_im_betreff_und_dateinamen(tmp_path):
    m = oo.Mail(empfaenger=(oo.Empfaenger("an", "", INTERN, False),), betreff=TEST_BETREFF, text="Grüße",
                anhaenge=(anhang(tmp_path, name="2026-11-15 Übersicht Müller.docx", daten=b"PK\x03\x04x"),))
    nachricht = email.message_from_bytes(oo.eml(m, oo.anhaenge_lesen(m.anhaenge)), policy=email.policy.default)
    assert nachricht["Subject"] == TEST_BETREFF
    a = next(nachricht.iter_attachments())
    assert a.get_filename() == "2026-11-15 Übersicht Müller.docx"
    assert a.get_content_type() == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_anhang_geaendert_heisst_abbruch(tmp_path):
    m = mail(tmp_path)
    m.anhaenge[0].pfad.write_bytes(b"%PDF-1.7 anders")
    with pytest.raises(oo.MailFehler, match="geändert"):
        oo.anhaenge_lesen(m.anhaenge)
    m.anhaenge[0].pfad.unlink()
    with pytest.raises(oo.MailFehler):
        oo.anhaenge_lesen(m.anhaenge)


def test_mailto_ist_kodiert_und_ohne_anhang(tmp_path):
    m = mail(tmp_path, betreff="A&B ?=#", text="Zeile 1\nZeile & 2")
    ziel = oo.mailto(m)
    assert ziel.startswith(f"mailto:{INTERN}?")
    assert "subject=A%26B%20%3F%3D%23" in ziel and "body=Zeile%201%0D%0AZeile%20%26%202" in ziel
    assert "attach" not in ziel


class Start:
    def __init__(self, fehler=None):
        self.aufrufe, self.fehler = [], fehler

    def __call__(self, argv):
        self.aufrufe.append(list(argv))
        if self.fehler and argv[1].lower().endswith(".eml"):
            raise self.fehler


def test_neuer_entwurf_ueber_eml_und_alias(tmp_path):
    m = mail(tmp_path)
    start = Start()
    fenster = [[], [{"programm": "olk.exe", "titel": "Angebot"}]]
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=tmp_path / "entwuerfe", starten=start,
                       fenster=lambda: fenster.pop(0) if len(fenster) > 1 else fenster[0], alias=Path("C:/olk.exe"), warten=2)
    assert r["status"] == "success" and r["weg"] == "eml" and r["anhang"] is True and r["fenster"] is True
    (argv,) = start.aufrufe
    assert argv[0] == str(Path("C:/olk.exe")) and argv[1].endswith(".eml")
    roh = Path(argv[1]).read_bytes()
    assert b"X-Unsent: 1" in roh
    assert "Entwurf" in r["summary"] and "selbst" in r["summary"]


def test_neuer_entwurf_ohne_fenster_meldet_das_klar(tmp_path):
    m = mail(tmp_path)
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=tmp_path / "e", starten=Start(), fenster=lambda: [],
                       alias=Path("C:/olk.exe"), warten=0.2)
    assert r["status"] == "success" and r["fenster"] is False and "Entwürfe" in r["summary"]


def test_rueckfall_mailto_ohne_anhang_und_explorer(tmp_path):
    m = mail(tmp_path)
    start = Start(fehler=OSError("kaputt"))
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=tmp_path / "e", starten=start, fenster=lambda: [],
                       alias=Path("C:/olk.exe"), warten=0.1)
    assert r["status"] == "success" and r["weg"] == "mailto" and r["anhang"] is False
    assert "ohne Anhang" in r["summary"] and "Explorer" in r["summary"]
    assert start.aufrufe[1][1].startswith("mailto:")
    assert start.aufrufe[2][0].lower().endswith("explorer.exe") and start.aufrufe[2][1].startswith("/select,")


def test_rueckfall_scheitert_bei_zu_langem_text(tmp_path):
    m = mail(tmp_path, text="ä" * oo.TEXT_MAX)
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=tmp_path / "e", starten=Start(fehler=OSError("x")),
                       fenster=lambda: [], alias=Path("C:/olk.exe"), warten=0.1)
    assert r["status"] == "error"


def test_entwurfsdatei_wird_spaeter_geloescht(tmp_path):
    m = mail(tmp_path)
    geplant = []
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=tmp_path / "e", starten=Start(), fenster=lambda: [],
                       alias=Path("C:/olk.exe"), warten=0.05, loeschen_planen=geplant.append)
    assert r["status"] == "success"
    (pfad,) = geplant
    assert pfad.suffix == ".eml" and pfad.parent == tmp_path / "e"
    oo._entfernen(pfad)
    assert not pfad.exists()
    oo._entfernen(pfad)  # schon weg: kein Fehler


def test_alte_entwurfsdateien_werden_aufgeraeumt(tmp_path):
    ordner = tmp_path / "e"
    ordner.mkdir()
    alt = ordner / "alt.eml"
    alt.write_bytes(b"x")
    os.utime(alt, (time.time() - 3600, time.time() - 3600))
    m = mail(tmp_path)
    oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=ordner, starten=Start(), fenster=lambda: [], alias=Path("C:/olk.exe"),
                   warten=0.05)
    assert not alt.exists() and len(list(ordner.glob("*.eml"))) == 1


# ---------- Klassisches Outlook (COM als Attrappe) ----------
def test_aufloesen_konto_und_signatur(outlook):
    konto, empf, signatur = oc.com_lauf(lambda app: oc.klassisch_vorbereiten(app, [("an", "Max Weber"), ("cc", "x@kunde.example")]))
    assert konto == {"smtp": KONTO, "name": "Konto Test"}
    assert [(e.art, e.name, e.smtp, e.extern) for e in empf] == [
        ("an", "Max Weber", INTERN, False), ("cc", "", "x@kunde.example", True)]
    assert "Mit freundlichen Grüßen" in signatur
    assert outlook.gespeichert == {} and outlook.geschlossen == [1]  # Signatur nur gelesen, kein Entwurf gespeichert


@pytest.mark.parametrize("wert,muster", [("Anna", "nicht eindeutig"), ("Alle", "Verteiler"), ("Niemand", "nicht eindeutig")])
def test_aufloesen_lehnt_ab(outlook, wert, muster):
    with pytest.raises(oo.MailFehler, match=muster):
        oc.com_lauf(lambda app: oc.klassisch_vorbereiten(app, [("an", wert)]))


def test_com_haengt_wird_zur_klaren_meldung(monkeypatch):
    halt = threading.Event()
    monkeypatch.setattr(oc, "_outlook_app", lambda: halt.wait(5) or object())
    with pytest.raises(oo.MailFehler, match="antwortet nicht"):
        oc.com_lauf(lambda app: app, timeout=0.2)
    halt.set()


def test_mail_bauen_mit_signatur_konto_und_anhang(outlook, tmp_path):
    m = mail(tmp_path, an=(("an", "Max Weber", INTERN, False),), text="Hallo <Max>")
    with oo.anhang_dateien(oo.anhaenge_lesen(m.anhaenge)) as pfade:
        item = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, pfade))
    assert item.Subject == "Angebot" and item.SendUsingAccount.SmtpAddress == KONTO
    assert item.HTMLBody.index("Hallo &lt;Max&gt;") < item.HTMLBody.index("<div id=sig>")  # Text vor der Signatur
    assert [(r.Type, r.AddressEntry._smtp) for r in item.Recipients.e] == [(1, INTERN)]
    assert [(a.FileName, a.daten) for a in item.Attachments.e] == [("2026-11-15 Angebot.pdf", b"%PDF-1.7 Angebot")]
    assert not item.Sent and outlook.gesendet == []


def test_mail_bauen_falsches_konto(outlook, tmp_path):
    with pytest.raises(oo.MailFehler, match="Konto"):
        oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), "fremd@x.example", []))


class TraegesKonto(Mail):
    """Späte Bindung in pywin32: SendUsingAccount = ... wirkt manchmal nicht, nur der Aufruf über die DISPID 64209."""

    def __init__(self, app, invoke_wirkt=True):
        super().__init__(app)
        self._konto, self.invokes = None, []
        self._oleobj_ = SimpleNamespace(Invoke=self._invoke)
        self._invoke_wirkt = invoke_wirkt

    def wieder_geoeffnet(self):
        self._konto = None

    @property
    def SendUsingAccount(self):  # noqa: N802
        return self._konto

    @SendUsingAccount.setter
    def SendUsingAccount(self, wert):  # noqa: N802 (Zuweisung geht verloren)
        pass

    def _invoke(self, dispid, lcid, flags, ergebnis, wert):
        self.invokes.append(dispid)
        if self._invoke_wirkt:
            self._konto = wert


@pytest.mark.parametrize("invoke_wirkt", [True, False])
def test_konto_wird_nachgeprueft_und_sonst_per_dispid_gesetzt(outlook, tmp_path, monkeypatch, invoke_wirkt):
    items = []
    monkeypatch.setattr(outlook, "CreateItem", lambda art: items.append(TraegesKonto(outlook, invoke_wirkt)) or items[-1])
    m = mail(tmp_path, mit_anhang=False)
    if invoke_wirkt:
        item = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, []))
        assert item.SendUsingAccount.SmtpAddress == KONTO and item.invokes == [64209]
    else:
        with pytest.raises(oo.MailFehler, match="Konto"):
            oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, []))


# ---------- Versand mit 30 Sekunden zum Zurückholen ----------
def test_versand_nach_der_frist():
    gesendet = []
    liste = oc.Versandliste(senden=lambda v: gesendet.append(v.id))
    v = liste.planen({"entry_id": "e1", "store_id": "s"}, {"p": 1}, verzoegerung=0.05)
    assert liste.status(v.id)["zustand"] == "wartet"
    v.faden.join(2)
    assert gesendet == [v.id] and liste.status(v.id)["zustand"] == "gesendet"
    assert liste.zurueckholen(v.id)["zustand"] == "zu_spaet"


def test_zurueckholen_in_der_frist_sendet_nie():
    gesendet = []
    liste = oc.Versandliste(senden=lambda v: gesendet.append(v.id))
    v = liste.planen({"entry_id": "e1", "store_id": "s"}, {}, verzoegerung=5)
    r = liste.zurueckholen(v.id)
    assert r["zustand"] == "zurueckgeholt" and "Entwürfe" in r["summary"]
    v.faden.join(2)
    assert gesendet == [] and liste.status(v.id)["zustand"] == "zurueckgeholt"
    assert liste.zurueckholen(v.id)["zustand"] == "zurueckgeholt"  # zweiter Klick: gleiche Antwort, nichts passiert


def test_versand_fehler_und_sperre():
    def kaputt(v):
        raise oo.MailFehler("Die Mail wurde in Outlook verändert.")

    liste = oc.Versandliste(senden=kaputt)
    v = liste.planen({}, {}, verzoegerung=0.01)
    v.faden.join(2)
    assert liste.status(v.id)["zustand"] == "fehler" and "verändert" in liste.status(v.id)["summary"]
    gesendet = []
    gesperrt = oc.Versandliste(senden=lambda v: gesendet.append(v), gesperrt=lambda: True)
    v = gesperrt.planen({}, {}, verzoegerung=0.01)
    v.faden.join(2)
    assert gesendet == [] and gesperrt.status(v.id)["zustand"] == "fehler"


def test_unbekannte_kennungen():
    liste = oc.Versandliste(senden=lambda v: None)
    for kennung in ("", "x", "../a", 5, "0" * 17):
        assert liste.zurueckholen(kennung)["zustand"] == "unbekannt"
        assert liste.status(kennung) is None


def test_klassisch_senden_prueft_den_entwurf(outlook, tmp_path):
    m = mail(tmp_path, mit_anhang=False)
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, []))
    ort, pruef = oc.speichern(item)
    oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == [item]
    item2 = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, []))
    ort2, pruef2 = oc.speichern(item2)
    item2.Subject = "geändert in Outlook"
    with pytest.raises(oo.MailFehler, match="verändert"):
        oc.klassisch_senden(ort2, pruef2, konto=KONTO)
    assert outlook.gesendet == [item]
    with pytest.raises(oo.MailFehler, match="Konto"):  # ohne Konto der Karte nie senden
        oc.klassisch_senden(ort, pruef)


def test_klassischer_entwurf_wird_nur_angezeigt(outlook, tmp_path):
    m = mail(tmp_path, mit_anhang=False)
    r = oc.com_lauf(lambda app: oc.klassisch_entwurf(app, m, "", []))
    assert r["status"] == "success" and len(outlook.angezeigt) == 1 and outlook.gesendet == []


# ---------- Echt am Windows-PC (nur mit WAMO_OUTLOOK_ECHT=1) ----------
ECHT = sys.platform == "win32" and os.getenv("WAMO_OUTLOOK_ECHT") == "1"


@pytest.mark.office
@pytest.mark.skipif(not ECHT, reason="nur am Windows-PC mit Outlook und WAMO_OUTLOOK_ECHT=1")
def test_echt_erkennung_liest_nur():
    vorher = "outlook.exe" in oo.laufende_programme()
    w = oo.erkennen()
    assert w.weg in ("senden", "entwurf", "keiner") and w.grund
    assert ("outlook.exe" in oo.laufende_programme()) == vorher  # nie ein Start des klassischen Outlooks


@pytest.mark.office
@pytest.mark.skipif(not (ECHT and os.getenv("WAMO_OUTLOOK_ENTWURF") == "1" and oo.adresse(os.getenv("WAMO_OUTLOOK_TESTADRESSE"))),
                    reason="öffnet einen Entwurf an WAMO_OUTLOOK_TESTADRESSE, nur auf Wunsch")
def test_echt_entwurf_im_neuen_outlook(tmp_path):
    w = oo.erkennen()
    if w.programm != "neu":
        pytest.skip("das neue Outlook ist nicht aktiv")
    ziel = oo.adresse(os.getenv("WAMO_OUTLOOK_TESTADRESSE"))
    m = oo.Mail(empfaenger=(oo.Empfaenger("an", "", ziel, False),), betreff=TEST_BETREFF,
                text="Test von W.A.I.S. (Entwurf, bitte nicht senden, bitte löschen).\nUmlaute: äöüß",
                anhaenge=(anhang(tmp_path, name="WAIS-Testanhang Übersicht.txt", daten="Testanhang äöü\n".encode()),))
    r = oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge))
    assert r["status"] == "success" and r["weg"] == "eml" and r["fenster"] is True, r


# ---------- Befunde aus dem Echttest und dem Review (15.11.2026) ----------
def test_speichern_schliesst_den_inspector_dann_geht_senden(outlook, tmp_path):
    """Echttest: Der unsichtbare Inspector aus GetInspector blieb offen, Send() über GetItemFromID scheiterte mit "Falscher Parameter"."""
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    assert len(outlook.Inspectors.e) == 1
    ort, pruef = oc.speichern(item)
    assert outlook.Inspectors.e == [] and outlook.geschlossen[-1] == 0  # olSave
    oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == [item] and item.gesendet_mit == KONTO


def test_offene_mail_in_outlook_wird_nicht_gesendet(outlook, tmp_path):
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    item.GetInspector  # noqa: B018 (die Person öffnet den Entwurf in Outlook)
    with pytest.raises(oo.MailFehler, match="in Outlook geöffnet"):
        oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == []


def test_fehler_beim_senden_ist_eine_klare_meldung_nie_ein_erfolg(outlook, tmp_path):
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    outlook.send_fehler = RuntimeError("com_error -2147024809")
    with pytest.raises(oo.MailFehler, match="nicht rausgegangen"):
        oc.klassisch_senden(ort, pruef, konto=KONTO)
    liste = oc.Versandliste(senden=lambda v: oc.klassisch_senden(ort, pruef, konto=KONTO))
    v = liste.planen(ort, pruef, verzoegerung=0.01)
    v.faden.join(3)
    assert liste.status(v.id)["zustand"] == "fehler" and outlook.gesendet == []


def test_mail_bauen_verwirft_bei_einem_fehler(outlook, tmp_path):
    m = mail(tmp_path, an=(("an", "", "anna-gibt-es-nicht", False),), mit_anhang=False)
    with pytest.raises(oo.MailFehler):
        oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, []))
    assert outlook.geschlossen[-1] == 1 and outlook.Inspectors.e == [] and outlook.gespeichert == {}


def test_konto_der_karte_wird_direkt_vor_dem_senden_gesetzt(outlook, tmp_path):
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    assert "konto" not in pruef  # nach dem Wiederöffnen liest sich das Konto leer: kein Prüfwert, sondern neu setzen
    with pytest.raises(oo.MailFehler, match="Konto"):
        oc.klassisch_senden(ort, pruef, konto="anderes@firma.example")  # das Konto der Karte gibt es nicht
    item.SendUsingAccount = SimpleNamespace(SmtpAddress="anderes@firma.example")  # in Outlook umgestellt
    oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == [item] and item.gesendet_mit == KONTO  # gesendet mit dem Konto der Karte


def test_konto_laesst_sich_vor_dem_senden_nicht_setzen(outlook, tmp_path, monkeypatch):
    items = []
    monkeypatch.setattr(outlook, "CreateItem", lambda art: items.append(TraegesKonto(outlook)) or items[-1])
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    item._invoke_wirkt = False  # jetzt greift weder die Zuweisung noch die DISPID
    with pytest.raises(oo.MailFehler, match="Konto"):
        oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == []


def test_wie_am_geraet_anhang_groesse_schwankt_und_konto_liest_sich_leer(outlook, tmp_path):
    """Echttest 15.11.2026: SendUsingAccount liest sich nach GetItemFromID leer, und Attachment.Size schwankt ohne jede Änderung (im
    selben Ablauf die Dateigröße, nach dem Neuladen in einem anderen Faden mit MAPI-Verwaltungsdaten: 35373 gegen 43438 Byte). Die Größe
    ist deshalb kein Prüfwert, das Konto wird vor dem Senden neu gesetzt: Die unveränderte Mail geht raus."""
    m = mail(tmp_path)
    with oo.anhang_dateien(oo.anhaenge_lesen(m.anhaenge)) as pfade:
        item = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, pfade))
    ort, pruef = oc.speichern(item)
    assert pruef["anhaenge"] == ["2026-11-15 Angebot.pdf"]
    item.Attachments.e[0].Size += 8065  # neu geladen: andere Größe, derselbe Inhalt
    oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == [item] and item.gesendet_mit == KONTO


def test_anderer_oder_zusaetzlicher_anhang_wird_nicht_gesendet(outlook, tmp_path):
    m = mail(tmp_path)
    with oo.anhang_dateien(oo.anhaenge_lesen(m.anhaenge)) as pfade:
        item = oc.com_lauf(lambda app: oc.mail_bauen(app, m, KONTO, pfade))
    ort, pruef = oc.speichern(item)
    item.Attachments.e.append(SimpleNamespace(FileName="zusatz.exe", Size=10, daten=b"x"))
    with pytest.raises(oo.MailFehler, match="verändert"):
        oc.klassisch_senden(ort, pruef, konto=KONTO)
    item.Attachments.e.pop()
    item.Attachments.e[0].FileName = "anders.pdf"
    with pytest.raises(oo.MailFehler, match="verändert"):
        oc.klassisch_senden(ort, pruef, konto=KONTO)
    assert outlook.gesendet == []


def test_zeitgrenze_vor_dem_senden_sendet_nie(outlook, tmp_path):
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    outlook.lese_dauer = 0.4  # Outlook hängt schon beim Holen des Entwurfs
    with pytest.raises(oo.MailFehler, match="nicht rausgegangen") as fehler:
        oc.klassisch_senden(ort, pruef, konto=KONTO, timeout=0.1)
    assert not isinstance(fehler.value, oc.VersandUnklar)
    time.sleep(0.6)  # der Faden läuft weiter, sieht die Sperre und sendet nicht
    assert outlook.gesendet == []


def test_zeitgrenze_waehrend_des_sendens_ist_unklar(outlook, tmp_path):
    item = oc.com_lauf(lambda app: oc.mail_bauen(app, mail(tmp_path, mit_anhang=False), KONTO, []))
    ort, pruef = oc.speichern(item)
    outlook.send_dauer = 0.4
    with pytest.raises(oc.VersandUnklar, match="Gesendete Elemente"):
        oc.klassisch_senden(ort, pruef, konto=KONTO, timeout=0.1)

    def unklar(v):
        raise oc.VersandUnklar("Ob die Mail rausging, ist unklar.")

    liste = oc.Versandliste(senden=unklar)
    v = liste.planen({}, {}, verzoegerung=0.01)
    v.faden.join(3)
    assert liste.status(v.id)["zustand"] == "unklar"


def test_lange_ueberschrittene_frist_sendet_nicht():
    """Ruhezustand in der Frist: Wacht der PC viel später auf, geht die Mail nicht mehr raus."""
    gesendet, uhrzeiten = [], iter([1000.0, 1000.0 + 30 + oc.SPAET_SECS + 5])
    liste = oc.Versandliste(senden=lambda v: gesendet.append(v.id), wand=lambda: next(uhrzeiten))
    v = liste.planen({}, {}, verzoegerung=0.01)
    v.faden.join(3)
    s = liste.status(v.id)
    assert gesendet == [] and s["zustand"] == "fehler" and "Entwürfe" in s["summary"]


def test_exchange_verteiler_auch_ueber_getexchangedistributionlist(outlook):
    verteiler = Eintrag("Projekt", "projekt@firma.example", art=0)
    verteiler.GetExchangeDistributionList = lambda: object()
    outlook.adressbuch["projekt"] = verteiler
    with pytest.raises(oo.MailFehler, match="Verteiler"):
        oc.com_lauf(lambda app: oc.klassisch_vorbereiten(app, [("an", "Projekt")]))


def test_eml_wird_bei_einem_startfehler_entfernt(tmp_path):
    m = mail(tmp_path)
    ordner = tmp_path / "e"
    oo.neu_entwurf(m, oo.anhaenge_lesen(m.anhaenge), ordner=ordner, starten=Start(fehler=OSError("x")), fenster=lambda: [],
                   alias=Path("C:/olk.exe"), warten=0.05, loeschen_planen=lambda p: None)
    assert list(ordner.glob("*.eml")) == []


def test_aufraeumen_beim_hoststart(tmp_path):
    ordner = tmp_path / "e"
    ordner.mkdir()
    alt, neu = ordner / "alt.eml", ordner / "neu.eml"
    for p in (alt, neu):
        p.write_bytes(b"x")
    os.utime(alt, (time.time() - 3600, time.time() - 3600))
    geplant = []
    oo.beim_start_aufraeumen(ordner, loeschen_planen=lambda p, rest: geplant.append((p, rest)))
    assert not alt.exists() and neu.exists()
    assert [p for p, _ in geplant] == [neu] and 0 < geplant[0][1] <= oo.ENTWURF_AUFBEWAHREN_SECS
    oo.beim_start_aufraeumen(tmp_path / "gibt-es-nicht")  # fehlt der Ordner: nichts zu tun
