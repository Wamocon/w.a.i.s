"""Klassisches Outlook per COM (Teil von office_outlook.py, Paket 2 von docs/office-und-versand.md): Empfänger im Adressbuch auflösen,
Konto und Signatur lesen, die Mail genau wie auf der Karte bauen, unter Entwürfe speichern und nach der Frist senden (Versandliste).

Jede COM-Arbeit läuft in com_lauf: eigener Thread mit CoInitialize, alle COM-Objekte bleiben darin, nach der Zeitgrenze kommt eine klare
Meldung statt eines hängenden Hosts. Angehängt wird nur an ein laufendes Outlook (GetActiveObject), gestartet wird es nie.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from office_outlook import (
    COM_TIMEOUT_SECS,
    VERZOEGERUNG_SECS,
    Empfaenger,
    Mail,
    MailFehler,
    _bereinigt,
    _domaene,
    _keine_doppelten,
    _zeile,
    adresse,
    html_text,
    interne_domaenen,
)

OL_MAIL, OL_TO, OL_CC, OL_SAVE, OL_DISCARD = 0, 1, 2, 0, 1
SPAET_SECS = 60  # so weit darf die Frist überschritten sein (zum Beispiel nach dem Ruhezustand), sonst wird nicht gesendet
NICHT_RAUS = "Die Mail ist nicht rausgegangen und liegt unter Entwürfe."
OL_EXCHANGE_NUTZER, OL_VERTEILER = (0, 5), (1, 11)
PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
ZURUECK_TEXT = "Zurückgeholt: Die Mail ist nicht rausgegangen und liegt in Outlook unter Entwürfe."
VERSAND_ID_RE = re.compile(r"[0-9a-f]{16}")


class ComZeitgrenze(MailFehler):
    """Outlook hat innerhalb der Zeitgrenze nicht geantwortet (der Faden kann noch laufen)."""


class VersandUnklar(MailFehler):
    """Beim Senden kam keine Antwort: Ob die Mail rausging, ist unklar."""


def _outlook_app():
    """Das laufende klassische Outlook (nur anhängen: GetActiveObject startet nie ein Outlook)."""
    import win32com.client

    return win32com.client.GetActiveObject("Outlook.Application")


def com_lauf(arbeit: Callable[[object], object], *, timeout: float = COM_TIMEOUT_SECS) -> object:
    """arbeit(app) in einem eigenen Thread mit CoInitialize; alle COM-Objekte bleiben in diesem Thread. Hängt Outlook (Dialog), meldet
    MailFehler nach timeout Sekunden. Zurück kommen nur Daten (bei Attrappen auch Objekte)."""
    stand: dict = {}

    def faden() -> None:
        com = None
        if sys.platform == "win32":
            try:
                import pythoncom

                com = pythoncom
                com.CoInitialize()
            except ImportError:
                com = None
        try:
            stand["wert"] = arbeit(_outlook_app())
        except MailFehler as e:
            stand["fehler"] = e
        except Exception as e:  # noqa: BLE001 (COM-Fehler aller Art: nur melden)
            stand["fehler"] = MailFehler(f"Outlook meldet einen Fehler ({type(e).__name__}). Es ist nichts passiert.")
        finally:
            if com is not None:
                com.CoUninitialize()

    t = threading.Thread(target=faden, name="wais-outlook", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise ComZeitgrenze("Outlook antwortet nicht (vielleicht ist dort ein Dialog offen). Es ist nichts passiert.")
    if "fehler" in stand:
        raise stand["fehler"]
    return stand.get("wert")


def _liste(sammlung) -> list:
    return [sammlung.Item(i) for i in range(1, int(sammlung.Count) + 1)]


def _konten(ns) -> list:
    return _liste(ns.Accounts)


def _konto(ns, gewuenscht: str = ""):
    konten = _konten(ns)
    if not konten:
        raise MailFehler("In Outlook ist kein Konto eingerichtet.")
    if gewuenscht:
        for k in konten:
            if (adresse(str(k.SmtpAddress or "")) or "").lower() == gewuenscht.lower():
                return k
        raise MailFehler("Das Outlook-Konto von der Karte gibt es nicht mehr. Es ist nichts passiert.")
    try:
        standard = ns.DefaultStore.StoreID
        for k in konten:
            if k.DeliveryStore.StoreID == standard:
                return k
    except Exception:  # noqa: BLE001 (ohne Standardspeicher: das erste Konto)
        pass
    return konten[0]


def konto_lesen(ns) -> dict:
    smtp = adresse(str(_konto(ns).SmtpAddress or ""))
    if smtp is None:
        raise MailFehler("Das Outlook-Konto hat keine gültige Mailadresse.")
    try:
        name = _zeile(ns.CurrentUser.Name, 100)
    except Exception:  # noqa: BLE001
        name = ""
    return {"smtp": smtp, "name": name}


def _smtp(eintrag) -> str:
    art = int(getattr(eintrag, "AddressEntryUserType", -1))
    try:  # auch Verteiler, die Outlook mit einer anderen Art meldet
        verteiler = eintrag.GetExchangeDistributionList()
    except Exception:  # noqa: BLE001 (SMTP-Einträge kennen die Methode nicht)
        verteiler = None
    if art in OL_VERTEILER or verteiler is not None:
        raise MailFehler("Verteilerlisten verschickt W.A.I.S. nicht (Schutz vor Massenversand). Bitte einzelne Empfänger nennen.")
    if art in OL_EXCHANGE_NUTZER:
        nutzer = eintrag.GetExchangeUser()
        roh = nutzer.PrimarySmtpAddress if nutzer is not None else ""
    elif str(getattr(eintrag, "Type", "")).upper() == "SMTP":
        roh = eintrag.Address
    else:
        roh = eintrag.PropertyAccessor.GetProperty(PR_SMTP)
    smtp = adresse(str(roh or ""))
    if smtp is None:
        raise MailFehler(f"Für {_zeile(getattr(eintrag, 'Name', ''), 60)} gibt es keine gültige Mailadresse.")
    return smtp


def _aufloesen(ns, art: str, wert: str, intern: set[str]) -> Empfaenger:
    r = ns.CreateRecipient(wert)
    if not r.Resolve():
        raise MailFehler(f"„{wert[:60]}“ ist im Adressbuch nicht eindeutig. Bitte die Mailadresse nennen.")
    eintrag = r.AddressEntry
    smtp = _smtp(eintrag)
    name = _zeile(getattr(eintrag, "Name", ""), 100)
    return Empfaenger(art, "" if name.lower() == smtp.lower() else name, smtp, _domaene(smtp) not in intern)


def signatur_lesen(app) -> str:
    """Standardsignatur für neue Mails als Text: Outlook setzt sie ein, sobald ein Element seinen Inspector bekommt. Das Element wird
    nie gespeichert, nur verworfen."""
    m = app.CreateItem(OL_MAIL)
    try:
        m.GetInspector  # noqa: B018 (der Zugriff löst das Einsetzen der Signatur aus)
        return _bereinigt(str(m.Body or ""))
    finally:
        try:
            m.Close(OL_DISCARD)
        except Exception:  # noqa: BLE001
            pass


def klassisch_vorbereiten(app, paare: list[tuple[str, str]]) -> tuple[dict, list[Empfaenger], str]:
    """Für die Karte: Konto, aufgelöste Empfänger (SMTP) und Signatur. Kein Entwurf."""
    ns = app.Session
    konto = konto_lesen(ns)
    intern = interne_domaenen(konto["smtp"])
    empf = [_aufloesen(ns, art, wert, intern) for art, wert in paare]
    _keine_doppelten(empf)
    return konto, empf, signatur_lesen(app)


def _mit_text(sig_html: str, text_html: str) -> str:
    m = re.search(r"<body[^>]*>", sig_html, re.IGNORECASE)
    if not m:
        return f"<html><body>{text_html}{sig_html}</body></html>"
    return sig_html[: m.end()] + text_html + sig_html[m.end():]


def mail_bauen(app, mail: Mail, konto_smtp: str, pfade: list[Path]):
    """Die Mail genau wie auf der Karte: Signatur von Outlook, Text davor, Empfänger als SMTP (aufgelöst muss dieselbe Adresse
    herauskommen), Anhänge aus den geprüften Kopien, festes Konto. Gespeichert oder gesendet wird hier nichts."""
    ns = app.Session
    konto = _konto(ns, konto_smtp)
    item = app.CreateItem(OL_MAIL)
    try:
        item.GetInspector  # noqa: B018 (Signatur einsetzen lassen; öffnet einen unsichtbaren Inspector, speichern schließt ihn)
        item.Subject = mail.betreff
        item.HTMLBody = _mit_text(str(item.HTMLBody or ""), html_text(mail.text))
        for e in mail.empfaenger:
            r = item.Recipients.Add(e.smtp)
            r.Type = OL_TO if e.art == "an" else OL_CC
            if not r.Resolve():
                raise MailFehler(f"{e.smtp} lässt sich in Outlook nicht auflösen. Es ist nichts passiert.")
            if _smtp(r.AddressEntry).lower() != e.smtp.lower():
                raise MailFehler("Outlook löst eine Adresse anders auf als auf der Karte. Es ist nichts passiert.")
        for p in pfade:
            item.Attachments.Add(str(p))
        _konto_setzen(item, konto)
    except BaseException:
        _schliessen(item, OL_DISCARD)  # nichts halb Gebautes liegen lassen
        raise
    return item


def _schliessen(item, art: int) -> None:
    try:
        item.Close(art)
    except Exception:  # noqa: BLE001 (schon zu)
        pass


def _konto_von(item) -> str:
    try:
        konto = item.SendUsingAccount
        return (adresse(str(konto.SmtpAddress or "")) or "").lower() if konto is not None else ""
    except Exception:  # noqa: BLE001
        return ""


DISPID_SEND_USING_ACCOUNT = 64209


def _konto_setzen(item, konto) -> None:
    """Festes Konto setzen und nachprüfen. Bei später Bindung (pywin32 ohne makepy) geht die Zuweisung manchmal verloren; dann hilft
    der Aufruf über die DISPID. Stimmt das Konto danach nicht, wird nichts gebaut (MailFehler)."""
    soll = (adresse(str(konto.SmtpAddress or "")) or "").lower()

    def stimmt() -> bool:
        ist = item.SendUsingAccount
        return ist is not None and (adresse(str(ist.SmtpAddress or "")) or "").lower() == soll

    item.SendUsingAccount = konto
    if stimmt():
        return
    try:
        item._oleobj_.Invoke(DISPID_SEND_USING_ACCOUNT, 0, 8, 0, konto)  # 8: DISPATCH_PROPERTYPUTREF
    except Exception:  # noqa: BLE001 (dann zählt nur die Prüfung)
        pass
    if not stimmt():
        raise MailFehler("Das Outlook-Konto ließ sich für diese Mail nicht festlegen. Es ist nichts passiert.")


def pruefwerte(item) -> dict:
    """Was sich zwischen Speichern und Senden nicht ändern darf."""
    return {"betreff": str(item.Subject),
            "empfaenger": sorted((int(r.Type), _smtp(r.AddressEntry).lower()) for r in _liste(item.Recipients)),
            "anhaenge": sorted((str(a.FileName), int(a.Size)) for a in _liste(item.Attachments)),
            "text": hashlib.sha256(str(item.Body or "").encode("utf-8", "replace")).hexdigest(),
            "konto": _konto_von(item)}


def speichern(item) -> tuple[dict, dict]:
    """Unter Entwürfe speichern; liefert den Ort (EntryID, StoreID) und die Prüfwerte. Danach schließt es den unsichtbaren Inspector
    (olSave): Bleibt er offen, scheitert Send() über GetItemFromID am Gerät mit "Falscher Parameter" (Echttest 15.11.2026)."""
    try:
        item.Save()
        ort, pruef = {"entry_id": str(item.EntryID), "store_id": str(item.Parent.StoreID)}, pruefwerte(item)
    except BaseException:
        _schliessen(item, OL_DISCARD)
        raise
    item.Close(OL_SAVE)
    return ort, pruef


def _inspector_offen(app, entry_id: str) -> bool:
    """Ist das Element in Outlook geöffnet (ein Inspector mit derselben EntryID)?"""
    for insp in _liste(app.Inspectors):
        try:
            if str(insp.CurrentItem.EntryID) == entry_id:
                return True
        except Exception:  # noqa: BLE001 (ein Fenster ohne Element)
            continue
    return False


class _Sendeschutz:
    """Zeitgrenze und Senden schließen sich aus: Läuft die Zeit ab, bevor Send() begonnen hat, beginnt es nie mehr; hat es begonnen,
    ist der Ausgang unklar."""

    def __init__(self):
        self._lock = threading.Lock()
        self.abgebrochen = self.sendet = False

    def vor_send(self) -> None:
        with self._lock:
            if self.abgebrochen:
                raise MailFehler("Zeitgrenze überschritten, nicht gesendet.")
            self.sendet = True

    def abbrechen(self) -> bool:
        with self._lock:
            self.abgebrochen = True
            return self.sendet


def klassisch_senden(ort: dict, pruef: dict, konto: str = "", timeout: float = COM_TIMEOUT_SECS) -> None:
    """Den gespeicherten Entwurf senden, nur wenn er noch derselbe ist, mit dem Konto der Karte und nicht in Outlook geöffnet (sonst
    MailFehler, er bleibt unter Entwürfe). Ein Fehler beim Senden ist nie ein Erfolg; läuft die Zeit während des Sendens ab, ist der
    Ausgang unklar (VersandUnklar)."""
    if konto and pruef.get("konto") != konto.lower():
        raise MailFehler(f"Das Konto der Mail passt nicht zur Karte. W.A.I.S. sendet sie deshalb nicht. {NICHT_RAUS}")
    schutz = _Sendeschutz()

    def arbeit(app) -> None:
        item = app.Session.GetItemFromID(ort["entry_id"], ort["store_id"])
        if bool(item.Sent):
            raise MailFehler("Die Mail ist schon gesendet.")
        if _inspector_offen(app, ort["entry_id"]):
            raise MailFehler("Die Mail ist in Outlook geöffnet. W.A.I.S. sendet sie deshalb nicht; sie liegt unter Entwürfe.")
        if pruefwerte(item) != pruef:
            raise MailFehler("Die Mail wurde in Outlook verändert. W.A.I.S. sendet sie deshalb nicht; sie liegt unter Entwürfe.")
        schutz.vor_send()
        try:
            item.Send()
        except Exception as e:  # noqa: BLE001 (com_error und Ähnliches: klare Meldung, nie ein Erfolg)
            raise MailFehler(f"Outlook hat das Senden abgelehnt ({type(e).__name__}). {NICHT_RAUS}") from e

    try:
        com_lauf(arbeit, timeout=timeout)
    except ComZeitgrenze as e:
        if schutz.abbrechen():
            raise VersandUnklar("Outlook hat beim Senden nicht rechtzeitig geantwortet. Ob die Mail rausging, ist unklar: bitte in "
                                "Outlook unter Gesendete Elemente und Postausgang nachsehen.") from e
        raise MailFehler(f"Outlook hat nicht rechtzeitig geantwortet. {NICHT_RAUS}") from e


def klassisch_entwurf(app, mail: Mail, konto_smtp: str, pfade: list[Path]) -> dict:
    """Im Zweifel nur zeigen: fertige Mail im klassischen Outlook öffnen, die Person sendet selbst."""
    mail_bauen(app, mail, konto_smtp, pfade).Display(False)
    return {"status": "success", "weg": "klassisch", "anhang": bool(pfade), "fenster": True,
            "summary": "Der Entwurf ist in Outlook (klassisch) offen, mit Signatur. Prüfen und selbst auf Senden drücken."}


# ---------- Versand nach der Frist ----------
@dataclass
class Versand:
    id: str
    frist: float
    ort: dict
    pruef: dict
    frist_wand: float = 0.0  # Ende der Frist nach der Uhrzeit (läuft auch im Ruhezustand weiter)
    zustand: str = "wartet"  # wartet, sendet, gesendet, zurueckgeholt, fehler, unklar
    meldung: str = ""
    ende: float | None = None
    abbruch: threading.Event = field(default_factory=threading.Event)
    faden: threading.Thread | None = None


class Versandliste:
    """Geplante Sendungen: genau einmal senden nach der Frist, vorher zurückholbar. senden(versand) sendet wirklich (klassisch_senden),
    gesperrt() ist der Schalter office.aus (dann geht nichts raus). Ist die Frist nach der Uhrzeit (wand) um mehr als SPAET_SECS
    überschritten, etwa nach dem Ruhezustand, wird nicht mehr gesendet."""

    def __init__(self, senden: Callable[[Versand], None], gesperrt: Callable[[], bool] | None = None,
                 uhr: Callable[[], float] = time.monotonic, behalten_secs: float = 3600, max_eintraege: int = 50,
                 wand: Callable[[], float] = time.time):
        self._senden, self._gesperrt, self._uhr, self._wand = senden, gesperrt or (lambda: False), uhr, wand
        self._behalten, self._max = behalten_secs, max_eintraege
        self._lock = threading.Lock()
        self._eintraege: dict[str, Versand] = {}

    def planen(self, ort: dict, pruef: dict, verzoegerung: float = VERZOEGERUNG_SECS) -> Versand:
        with self._lock:
            self._aufraeumen()
            v = Versand(secrets.token_hex(8), self._uhr() + verzoegerung, dict(ort), pruef, self._wand() + verzoegerung)
            self._eintraege[v.id] = v
        v.faden = threading.Thread(target=self._lauf, args=(v, verzoegerung), name="wais-versand", daemon=True)
        v.faden.start()
        return v

    def _lauf(self, v: Versand, verzoegerung: float) -> None:
        if v.abbruch.wait(verzoegerung):
            return  # zurückgeholt
        with self._lock:
            if v.zustand != "wartet":
                return
            if self._gesperrt():
                v.zustand, v.ende = "fehler", self._uhr()
                v.meldung = "Office ist an diesem PC ausgeschaltet (office.aus). Die Mail ist nicht rausgegangen und liegt unter Entwürfe."
                return
            if self._wand() - v.frist_wand > SPAET_SECS:
                v.zustand, v.ende = "fehler", self._uhr()
                v.meldung = ("Die Frist ist lange vorbei (zum Beispiel nach dem Ruhezustand). W.A.I.S. sendet die Mail deshalb nicht; "
                             "sie liegt unter Entwürfe.")
                return
            v.zustand = "sendet"
        try:
            self._senden(v)
            ergebnis = ("gesendet", "Die Mail ist gesendet.")
        except VersandUnklar as e:
            ergebnis = ("unklar", str(e))
        except MailFehler as e:
            ergebnis = ("fehler", str(e))
        except Exception as e:  # noqa: BLE001
            ergebnis = ("fehler", f"Senden ging nicht ({type(e).__name__}). Die Mail liegt unter Entwürfe.")
        with self._lock:
            v.zustand, v.meldung = ergebnis
            v.ende = self._uhr()

    def _holen(self, vid: object) -> Versand | None:
        if not isinstance(vid, str) or not VERSAND_ID_RE.fullmatch(vid):
            return None
        with self._lock:
            return self._eintraege.get(vid)

    def zurueckholen(self, vid: object) -> dict:
        v = self._holen(vid)
        if v is None:
            return {"zustand": "unbekannt", "summary": "Diesen Versand kennt W.A.I.S. nicht (mehr)."}
        with self._lock:
            if v.zustand == "wartet":
                v.zustand, v.meldung, v.ende = "zurueckgeholt", ZURUECK_TEXT, self._uhr()
                v.abbruch.set()
            zustand, meldung = v.zustand, v.meldung
        if zustand in ("sendet", "gesendet"):
            return {"zustand": "zu_spaet", "summary": "Zu spät: Die Mail ist schon unterwegs."}
        return {"zustand": zustand, "summary": meldung}

    def status(self, vid: object) -> dict | None:
        v = self._holen(vid)
        if v is None:
            return None
        with self._lock:
            rest = max(0, math.ceil(v.frist - self._uhr())) if v.zustand == "wartet" else 0
            meldung = v.meldung or ("Die Mail geht gleich raus." if v.zustand in ("wartet", "sendet") else "")
            return {"zustand": v.zustand, "rest_s": rest, "summary": meldung}

    def _aufraeumen(self) -> None:
        """Erledigte Einträge nach behalten_secs entfernen; nie einen, der noch wartet oder sendet."""
        jetzt = self._uhr()
        erledigt = sorted((v for v in self._eintraege.values() if v.ende is not None), key=lambda v: v.ende)
        for v in erledigt:
            if jetzt - v.ende > self._behalten or len(self._eintraege) >= self._max:
                self._eintraege.pop(v.id, None)
