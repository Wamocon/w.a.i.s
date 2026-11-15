"""OneNote per COM (Paket 4 von docs/office-und-versand.md): eine neue Seite aus einem Canvas-Inhalt im eigenen Notizbuch NOTIZBUCH
("W.A.I.S.") im OneDrive der Firma, Abschnitt ABSCHNITT.

* Erkennung ohne Start (onenote_vorhanden): OneNote.Application ist registriert und ihr lokaler Server ist ONENOTE.EXE, die es gibt.
  OneNote für Windows 10 und OneNote im Web haben keine COM-Schnittstelle; dann schlägt der Kern eine Word-Datei vor.
* Zugriff über comtypes mit der Typbibliothek von OneNote (die späte Bindung von pywin32 findet GetHierarchy nicht).
* Jeder Zugriff läuft in einem eigenen Faden mit eigener COM-Anmeldung, mit Zeitgrenze und immer nur einer zur Zeit (_SPERRE). OneNote
  ist die Instanz der Person: Der Host beendet sie nie und schließt kein Fenster.
* Ziel (Entscheidung von Niko): nie ein vorhandenes fremdes Notizbuch. Das OneDrive der Firma ist das einzige OneDrive-for-Business-Konto
  am PC (HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\Business*), auf Wunsch eingegrenzt über WAMO_ONENOTE_DOMAENE; kein oder mehr als
  ein Konto heißt Rückfall auf Word. Ein offenes Notizbuch "W.A.I.S." in diesem OneDrive wird genutzt; fehlt es, legt der Host es erst
  nach dem Klick an (OpenHierarchy auf die Adresse im OneDrive, Ordner NOTIZBUCH_ORDNER, Anzeigename NOTIZBUCH). Ein Notizbuch dieses
  Namens anderswo zählt nicht. SharePoint erlaubt keinen Punkt am Ende eines Ordnernamens und macht aus "W.A.I.S..one" "W.A.I.S_":
  deshalb Ordner "W.A.I.S" mit Anzeigenamen "W.A.I.S." und Abschnitt "W.A.I.S" (am Gerät geprüft).
* Die Karte nennt Konto, Notizbuch und Abschnitt (mit "wird neu angelegt"); vor dem Anlegen prüft der Host, dass alles noch dasselbe
  ist. Geändert wird nur die neue Seite, Notizbuch und Abschnitt werden höchstens angelegt. Gelöscht wird nur die eigene, eben angelegte
  Seite, wenn ihr Inhalt nicht geschrieben werden konnte.
* Seiten-XML im Namensraum 2013, gebaut mit ElementTree: Jeder Text aus dem Canvas steht HTML-maskiert in one:T (OneNote liest one:T
  als HTML), Auszeichnungen (fett, Überschrift, Festbreite) setzt nur dieser Code. Keine Links, keine Bilder, keine Dateien.
"""

from __future__ import annotations

import html
import os
import re
import sys
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import office_dateien
import uia_control
from office_dateien import Inhalt, InhaltFehler

NS = "http://schemas.microsoft.com/office/onenote/2013/onenote"
NOTIZBUCH = "W.A.I.S."  # Anzeigename (nickname) des Notizbuchs
NOTIZBUCH_ORDNER = "W.A.I.S"  # Ordner im OneDrive: SharePoint erlaubt keinen Punkt am Ende eines Ordnernamens
ABSCHNITT = "W.A.I.S"  # Datei W.A.I.S.one; aus "W.A.I.S..one" macht SharePoint "W.A.I.S_"
DOMAENE_ENV = "WAMO_ONENOTE_DOMAENE"  # optional: Domänen des Firmenkontos (Komma), wenn mehrere OneDrive-for-Business-Konten da sind
KONTEN_SCHLUESSEL = r"Software\Microsoft\OneDrive\Accounts"
TITEL_MAX = 120
TITEL_EINGABE_MAX = 300
SEITEN_JE_STUNDE = 10
LESEN_TIMEOUT_SECS = 30
SCHREIBEN_TIMEOUT_SECS = 90  # ein neues Notizbuch im OneDrive braucht etwas länger
SYNC_WARTEN_SECS = 20  # so lange darf ein frischer Abschnitt "noch nicht synchronisiert" melden
SPERRE_WARTEN_SECS = 2.0
TYPBIBLIOTHEK = ("{0EA692EE-BB50-4E3C-AEF0-356D91732725}", 1, 1)  # Microsoft OneNote 15.0 Object Library
HS_NOTIZBUECHER, HS_ABSCHNITTE = 2, 3
XS_2013 = 2
CFT_NOTIZBUCH, CFT_ABSCHNITT = 1, 3
NICHT_SYNCHRON = 0x8004201D  # OneNote: Inhalt noch nicht synchronisiert
OHNE_DATUM = 0.0  # dateExpectedLastModified: ohne Prüfung; muss mitgehen, der Standard der Typbibliothek passt nicht zu c_double
ZIEL_NAME_MAX = 36  # drei Namen auf der Karte, das Ziel bleibt unter 200 Zeichen
KEIN_FIRMENKONTO = ("An diesem PC ist kein OneDrive der Firma (OneDrive for Business) angemeldet. Firmeninhalte gehen nur in das "
                    "Notizbuch W.A.I.S. dort.")
MEHRERE_FIRMENKONTEN = ("An diesem PC sind mehrere OneDrive-for-Business-Konten angemeldet; welches der Firma gehört, ist nicht "
                        "eindeutig (WAMO_ONENOTE_DOMAENE grenzt es ein).")
CODE_STIL = "font-family:Consolas;font-size:10.0pt"
UEBERSCHRIFT_GROESSE = {1: "16.0", 2: "13.0", 3: "12.0"}
FETT = "<span style='font-weight:bold'>{}</span>"
CODE_INLINE = "<span style='font-family:Consolas'>{}</span>"
_CLSID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_ABSCHNITT_RE = re.compile(r'[^\\/:*?"<>|#%\x00-\x1f]{1,50}')
_SITE_RE = re.compile(r"(https://[a-z0-9-]+-my\.sharepoint\.[a-z]{2,3}/personal/[a-z0-9_.-]+)/_api", re.IGNORECASE)
_MAIL_RE = re.compile(r"[^@\s]{1,64}@([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.IGNORECASE)
# Wie persona.sichtbar im Kern, das die Karte bereinigt: Steuer-, Format-, Richtungs- und unsichtbare Zeichen, Variantenwähler. Der Host
# entfernt sie schon im Inhalt, damit Karte und Seite zeichengleich sind (ein U+202E könnte sonst den Text auf der Seite umdrehen).
_UNSICHTBAR = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_UNSICHTBAR_EXTRA = frozenset({0x034F, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)})
_SPERRE = threading.Lock()
ET.register_namespace("one", NS)  # Seiten-XML und Änderungen am Notizbuch mit dem Präfix one


class OneNoteFehler(RuntimeError):
    """OneNote ist nicht bereit oder hat einen Fehler gemeldet (Text ist für Menschen gedacht). rueckfall: Eine Word-Datei ist der
    richtige Ersatz (OneNote fehlt, startet nicht oder hat kein Notizbuch), nicht bei "beschäftigt", Zeitüberschreitung oder Schutz."""

    def __init__(self, text: str, *, rueckfall: bool = False):
        super().__init__(text)
        self.rueckfall = rueckfall


@dataclass(frozen=True)
class Firmenkonto:
    konto: str  # Anmeldename des Kontos (nur für die Karte)
    site: str  # persönliche OneDrive-Site des Kontos


@dataclass(frozen=True)
class Ziel:
    konto: str
    notizbuch_url: str  # Adresse des Notizbuchs im OneDrive der Firma (zum Anlegen)
    notizbuch_id: str  # leer: Notizbuch fehlt und wird erst nach dem Klick angelegt
    notizbuch: str
    abschnitt: str
    abschnitt_id: str  # leer: Abschnitt fehlt und wird beim Anlegen der Seite angelegt


@dataclass(frozen=True)
class Seite:
    inhalt: Inhalt
    titel: str


# ---------- Erkennung ohne Start ----------
def _registrierung_lesen(pfad: str) -> str | None:
    """Standardwert eines Schlüssels unter HKEY_CLASSES_ROOT oder None; erst die 64-Bit-Sicht, dann die 32-Bit-Sicht (32-Bit-Office)."""
    import winreg

    for sicht in (0, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, pfad, 0, winreg.KEY_READ | sicht) as schluessel:
                return winreg.QueryValue(schluessel, None)
        except OSError:
            continue
    return None


def _programm(server: str) -> Path | None:
    """Programmpfad aus LocalServer32 ("C:\\...\\ONENOTE.EXE" /Embedding oder ohne Anführungszeichen)."""
    server = (server or "").strip()
    if server.startswith('"'):
        return Path(server[1:].split('"', 1)[0]) if '"' in server[1:] else None
    treffer = re.match(r"(?i)(.+?\.exe)\b", server)
    return Path(treffer.group(1)) if treffer else None


def onenote_vorhanden(*, lesen: Callable[[str], str | None] | None = None, datei_da: Callable[[Path], bool] | None = None,
                      plattform: str | None = None) -> bool:
    """Ist OneNote für den Desktop per COM erreichbar? Nur die Registrierung und die Datei, OneNote wird dafür nicht gestartet."""
    if (plattform or sys.platform) != "win32":
        return False
    lesen, datei_da = lesen or _registrierung_lesen, datei_da or Path.is_file
    clsid = lesen(r"OneNote.Application\CLSID") or ""
    if not _CLSID_RE.fullmatch(clsid):
        return False
    exe = _programm(lesen(rf"CLSID\{clsid}\LocalServer32") or "")
    return exe is not None and exe.name.lower() == "onenote.exe" and datei_da(exe)


# ---------- Inhalt prüfen ----------
def _sauber(text: str) -> str:
    """Ohne die Zeichen, die die Karte nicht zeigt (_UNSICHTBAR); Zeilenumbrüche bleiben, ein Tab wird zu vier Leerzeichen."""
    return "".join(c for c in text.replace("\t", "    ")
                   if c == "\n" or (unicodedata.category(c) not in _UNSICHTBAR and ord(c) not in _UNSICHTBAR_EXTRA))


def _zelle(wert: str) -> str:
    return " ".join(_sauber(wert).split("\n"))


def _inhalt_sauber(inhalt: Inhalt) -> Inhalt:
    """Text und Zellen so, wie Karte und Seite sie zeigen. Wirft InhaltFehler, wenn danach nichts bleibt."""
    if inhalt.art == "tabelle":
        return replace(inhalt, spalten=tuple(_zelle(s) for s in inhalt.spalten),
                       zeilen=tuple(tuple(_zelle(w) for w in z) for z in inhalt.zeilen))
    text = _sauber(inhalt.text)
    if not text.strip():
        raise InhaltFehler("Der Inhalt ist leer")
    return replace(inhalt, text=text)


def seite_pruefen(roh: object, titel: object = "") -> Seite:
    """Inhalt wie bei den Office-Dateien (office_dateien.pruefen), ohne unsichtbare Zeichen, dazu der Seitentitel: vom Modell oder aus
    dem Canvas, höchstens TITEL_MAX Zeichen, ohne Steuer- und unsichtbare Zeichen. Wirft InhaltFehler."""
    inhalt = _inhalt_sauber(office_dateien.pruefen(roh))
    if titel is None:
        titel = ""
    if not isinstance(titel, str):
        raise InhaltFehler("titel muss Text sein")
    if len(titel) > TITEL_EINGABE_MAX:
        raise InhaltFehler(f"Der Seitentitel ist zu lang (höchstens {TITEL_MAX} Zeichen)")
    gewaehlt = uia_control.sicherer_text(titel, TITEL_MAX) or uia_control.sicherer_text(inhalt.titel, TITEL_MAX)
    return Seite(inhalt, gewaehlt or "Canvas")


# ---------- OneDrive der Firma ----------
def _wert(schluessel, name: str) -> str:
    import winreg

    try:
        wert = winreg.QueryValueEx(schluessel, name)[0]
    except OSError:
        return ""
    return wert if isinstance(wert, str) else ""


def _konten_lesen() -> list[dict]:
    """OneDrive-for-Business-Konten des Benutzers (Business1, Business2, ...): Anmeldename und Dienstadresse, sonst nichts."""
    import winreg

    konten = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KONTEN_SCHLUESSEL) as wurzel:
            for i in range(64):
                try:
                    name = winreg.EnumKey(wurzel, i)
                except OSError:
                    break
                if re.fullmatch(r"Business\d{1,2}", name):
                    with winreg.OpenKey(wurzel, name) as k:
                        konten.append({"UserEmail": _wert(k, "UserEmail"), "ServiceEndpointUri": _wert(k, "ServiceEndpointUri")})
    except OSError:
        return []
    return konten


def firmenkonto(*, konten: list[dict] | None = None, domaenen: str | None = None) -> Firmenkonto:
    """Das OneDrive der Firma: das einzige OneDrive-for-Business-Konto mit gültiger persönlicher Site, eingegrenzt auf die Domänen aus
    WAMO_ONENOTE_DOMAENE, wenn gesetzt. Kein oder mehr als ein Konto: OneNoteFehler mit rueckfall (dann eine Word-Datei)."""
    if konten is None:
        konten = _konten_lesen() if sys.platform == "win32" else []
    roh = os.getenv(DOMAENE_ENV, "") if domaenen is None else domaenen
    erlaubt = {d.strip().lower().lstrip("@") for d in re.split(r"[\s,;]+", roh or "") if d.strip()}
    passend = []
    for konto in konten:
        mail = _MAIL_RE.fullmatch(str(konto.get("UserEmail") or ""))
        site = _SITE_RE.fullmatch(str(konto.get("ServiceEndpointUri") or ""))
        if mail and site and (not erlaubt or mail.group(1).lower() in erlaubt):
            passend.append(Firmenkonto(mail.group(0), site.group(1)))
    if len(passend) != 1:
        raise OneNoteFehler(MEHRERE_FIRMENKONTEN if passend else KEIN_FIRMENKONTO, rueckfall=True)
    return passend[0]


def notizbuch_adresse(konto: Firmenkonto, ordner: str = NOTIZBUCH_ORDNER) -> str:
    return f"{konto.site}/Documents/{ordner}"


# ---------- Notizbuch und Abschnitt ----------
def _q(name: str) -> str:
    return f"{{{NS}}}{name}"


def _xml(text: object) -> ET.Element:
    try:
        return ET.fromstring(text if isinstance(text, str) else "")
    except ET.ParseError as e:
        raise OneNoteFehler("OneNote hat eine unlesbare Übersicht der Notizbücher geliefert.", rueckfall=True) from e


def _pfad_vergleich(pfad: str) -> str:
    return (pfad or "").replace("\\", "/").rstrip("/").casefold()


def notizbuch_finden(hierarchie: str, konto: Firmenkonto, name: str = NOTIZBUCH) -> str:
    """Kennung des offenen Notizbuchs name (Anzeige- oder Ordnername, genau) im OneDrive der Firma oder "", wenn es fehlt. Liegt eines
    dieses Namens nur woanders oder gibt es mehrere: OneNoteFehler mit rueckfall (Firmeninhalte nie in ein fremdes Notizbuch)."""
    treffer = [nb for nb in _xml(hierarchie).iter(_q("Notebook")) if name in (nb.get("nickname"), nb.get("name")) and nb.get("ID")]
    site = _pfad_vergleich(konto.site)
    in_firma = [nb for nb in treffer if _pfad_vergleich(nb.get("path", "")).startswith(site + "/")]
    if len(in_firma) > 1:
        raise OneNoteFehler(f"Im OneDrive der Firma sind mehrere Notizbücher {name} geöffnet. Bitte eines davon schließen.",
                            rueckfall=True)
    if not in_firma and treffer:
        raise OneNoteFehler(f"Das geöffnete Notizbuch {name} liegt nicht im OneDrive der Firma. Firmeninhalte gehen nur dorthin.",
                            rueckfall=True)
    return in_firma[0].get("ID") if in_firma else ""


def abschnitt_suchen(hierarchie: str, notizbuch_id: str, name: str) -> str:
    """Kennung des Abschnitts name direkt im Notizbuch (nicht in Gruppen, nicht im Papierkorb) oder "". Geschützt: OneNoteFehler."""
    wurzel = _xml(hierarchie)
    notizbuch = wurzel if wurzel.get("ID") == notizbuch_id else next(
        (nb for nb in wurzel.iter(_q("Notebook")) if nb.get("ID") == notizbuch_id), None)
    if notizbuch is None:
        return ""
    for abschnitt in notizbuch.findall(_q("Section")):
        if abschnitt.get("name", "").casefold() != name.casefold() or abschnitt.get("isInRecycleBin") == "true":
            continue
        if any(abschnitt.get(a) == "true" for a in ("locked", "readOnly", "encrypted")):
            raise OneNoteFehler(f"Der Abschnitt {name} ist geschützt oder schreibgeschützt. Bitte in OneNote freigeben.")
        return abschnitt.get("ID", "")
    return ""


# ---------- Seiten-XML ----------
def _html(text: str) -> str:
    return html.escape(text, quote=True)


def _inline(zeile: str) -> str:
    teile = []
    for art, text in office_dateien.teile(zeile):
        teile.append(FETT.format(_html(text)) if art == "fett" else CODE_INLINE.format(_html(text)) if art == "code" else _html(text))
    return "".join(teile)


def _oe(eltern: ET.Element, text: str, *, stil: str = "", punkt: bool = False) -> ET.Element:
    oe = ET.SubElement(eltern, _q("OE"), {"style": stil} if stil else {})
    if punkt:
        ET.SubElement(ET.SubElement(oe, _q("List")), _q("Bullet"), {"bullet": "2"})
    ET.SubElement(oe, _q("T")).text = text
    return oe


def _dokument(kinder: ET.Element, text: str) -> None:
    for art, ebene, zeile in office_dateien.bloecke(text):
        if art == "ueberschrift":
            groesse = UEBERSCHRIFT_GROESSE.get(ebene, "12.0")
            _oe(kinder, f"<span style='font-weight:bold;font-size:{groesse}pt'>{_inline(zeile)}</span>")
        else:
            _oe(kinder, _inline(zeile), punkt=art == "punkt")


def _code(kinder: ET.Element, text: str) -> None:
    """Jede Zeile ein Absatz in Festbreitenschrift; Leerzeichen als geschützte Leerzeichen, damit Einrückungen bleiben."""
    for zeile in text.rstrip("\n").split("\n"):
        _oe(kinder, _html(zeile.replace("\t", "    ")).replace(" ", "\u00a0"), stil=CODE_STIL)


def _tabelle(kinder: ET.Element, inhalt: Inhalt) -> None:
    tabelle = ET.SubElement(ET.SubElement(kinder, _q("OE")), _q("Table"), {"bordersVisible": "true"})
    spalten = ET.SubElement(tabelle, _q("Columns"))
    for i, kopf in enumerate(inhalt.spalten):
        laengste = max([len(kopf), *(len(z[i]) for z in inhalt.zeilen)])
        ET.SubElement(spalten, _q("Column"), {"index": str(i), "width": f"{min(max(60, 40 + 6 * laengste), 260)}.0"})
    for nummer, werte in enumerate((inhalt.spalten, *inhalt.zeilen)):
        zeile = ET.SubElement(tabelle, _q("Row"))
        for wert in werte:
            zelle = ET.SubElement(ET.SubElement(zeile, _q("Cell")), _q("OEChildren"))
            _oe(zelle, FETT.format(_html(wert)) if nummer == 0 else _html(wert))


def seiten_xml(seite: Seite, seiten_id: str) -> str:
    """Inhalt der neuen Seite für UpdatePageContent (Namensraum 2013). Text nur maskiert, eigene Auszeichnungen nur als span."""
    wurzel = ET.Element(_q("Page"), {"ID": seiten_id})
    ET.SubElement(ET.SubElement(ET.SubElement(wurzel, _q("Title")), _q("OE")), _q("T")).text = _html(seite.titel)
    kinder = ET.SubElement(ET.SubElement(wurzel, _q("Outline")), _q("OEChildren"))
    inhalt = seite.inhalt
    if inhalt.art == "tabelle":
        _tabelle(kinder, inhalt)
    elif inhalt.art in ("code", "mermaid"):
        _code(kinder, inhalt.text)
    else:
        _dokument(kinder, inhalt.text)
    return ET.tostring(wurzel, encoding="unicode")


# ---------- Kartentext ----------
def text_zeilen(inhalt: Inhalt) -> list[str]:
    """Inhalt als Klartext, Zeile für Zeile, wie er auf der Seite steht (ohne Auszeichnungen)."""
    if inhalt.art == "tabelle":
        return [" | ".join(z) for z in (inhalt.spalten, *inhalt.zeilen)]
    if inhalt.art in ("code", "mermaid"):
        return [z.rstrip() for z in inhalt.text.rstrip("\n").split("\n")]
    return [("• " if art == "punkt" else "") + office_dateien.klartext(z) for art, _, z in office_dateien.bloecke(inhalt.text)]


def karten_detail(seite: Seite) -> str:
    """Was die Karte zeigt: Titel und der ganze Inhalt, jede Inhaltszeile mit "> " davor (wie bei den Labor-Karten)."""
    zeilen = [f"> {z}" if z else ">" for z in text_zeilen(seite.inhalt)]
    return "\n".join([f"Seite: {seite.titel}", "Inhalt:", *zeilen])


def _kurz(text: str) -> str:
    return text if len(text) <= ZIEL_NAME_MAX else text[: ZIEL_NAME_MAX - 1] + "…"


def karten_ziel(ziel: Ziel) -> str:
    """Ziel der Karte: Notizbuch und Abschnitt (mit "wird neu angelegt") und das Konto, dessen OneDrive es ist."""
    notizbuch = f"Notizbuch {_kurz(ziel.notizbuch)}" + ("" if ziel.notizbuch_id else " (wird neu angelegt)")
    abschnitt = f"Abschnitt {_kurz(ziel.abschnitt)}" + ("" if ziel.abschnitt_id else " (wird angelegt)")
    return f"OneNote, {notizbuch}, {abschnitt}, OneDrive der Firma ({_kurz(ziel.konto)})"


# ---------- COM ----------
def _com_text(fehler: BaseException) -> str:
    hresult = getattr(fehler, "hresult", None)
    if isinstance(hresult, int):
        return f"0x{hresult & 0xFFFFFFFF:08X}"
    return type(fehler).__name__


def _anmelden() -> Callable[[], None] | None:
    """COM für diesen Faden anmelden; liefert die Abmeldung oder None (kein Windows, kein comtypes)."""
    if sys.platform != "win32":
        return None
    try:
        import comtypes
    except ImportError:
        return None
    comtypes.CoInitialize()
    return comtypes.CoUninitialize


def _onenote():
    """Die OneNote-Instanz der Person (lokaler Server) über die Typbibliothek."""
    import comtypes
    import comtypes.client

    modul = comtypes.client.GetModule(TYPBIBLIOTHEK)
    return comtypes.CoCreateInstance(modul.Application._reg_clsid_, interface=modul.IApplication,
                                     clsctx=comtypes.CLSCTX_LOCAL_SERVER)


ZU_SPAET_LESEN = "OneNote hat nicht in der Zeit geantwortet. Ist dort ein Dialog offen? Bitte in OneNote nachsehen."
ZU_SPAET_SCHREIBEN = ("OneNote hat nicht in der Zeit geantwortet. Die Seite kann trotzdem noch entstehen: Bitte erst in OneNote "
                      "nachsehen, bevor du sie noch einmal anlegst.")


def _lauf(arbeit: Callable, fabrik: Callable, stand: dict) -> None:
    """Im eigenen Faden: anmelden, OneNote holen, arbeiten, abmelden, Sperre freigeben (auch nach einer Zeitüberschreitung). Fehler
    landen als frische OneNoteFehler ohne Traceback in stand: So hält kein Rahmen einen COM-Zeiger über die Abmeldung hinaus."""
    abmelden = app = None
    try:
        abmelden = _anmelden()
        try:
            app = fabrik()
        except Exception as e:  # noqa: BLE001 (nicht registriert, Start verweigert)
            raise OneNoteFehler(f"OneNote für den Desktop startet nicht ({_com_text(e)}).", rueckfall=True) from None
        stand["ergebnis"] = arbeit(app)
    except OneNoteFehler as e:
        stand["fehler"] = OneNoteFehler(str(e), rueckfall=e.rueckfall)
    except Exception as e:  # noqa: BLE001 (COM-Fehler aller Art: nur melden)
        stand["fehler"] = OneNoteFehler(f"OneNote meldet einen Fehler ({_com_text(e)}). Ist OneNote für den Desktop eingerichtet?",
                                        rueckfall=True)
    finally:
        app = None  # Verweis vor der Abmeldung freigeben
        try:
            if abmelden is not None:
                abmelden()
        finally:
            _SPERRE.release()


def _im_faden(arbeit: Callable, timeout: float, fabrik: Callable | None = None, warten: float = SPERRE_WARTEN_SECS, *,
              abbruch: threading.Event | None = None, zu_spaet: str = ZU_SPAET_LESEN):
    """arbeit(app) in einem eigenen Faden mit Zeitgrenze; immer nur ein Zugriff zur Zeit. Nach der Zeitgrenze wird abbruch gesetzt
    (die Arbeit prüft es vor jedem Schritt, der etwas anlegt). Wirft OneNoteFehler."""
    if not _SPERRE.acquire(timeout=warten):
        raise OneNoteFehler("OneNote ist noch mit dem vorigen Auftrag beschäftigt. Bitte gleich noch einmal.")
    stand: dict = {}
    faden = threading.Thread(target=_lauf, args=(arbeit, fabrik or _onenote, stand), name="wais-onenote", daemon=True)
    try:
        faden.start()
    except RuntimeError:
        _SPERRE.release()
        raise
    faden.join(timeout)
    if faden.is_alive():
        if abbruch is not None:
            abbruch.set()
        raise OneNoteFehler(zu_spaet)
    if "fehler" in stand:
        raise stand["fehler"]
    return stand["ergebnis"]


def _ziel_lesen(app, konto: Firmenkonto, notizbuch: str, adresse: str, abschnitt: str) -> Ziel:
    notizbuch_id = notizbuch_finden(app.GetHierarchy("", HS_NOTIZBUECHER, xsSchema=XS_2013), konto, notizbuch)
    abschnitt_id = (abschnitt_suchen(app.GetHierarchy(notizbuch_id, HS_ABSCHNITTE, xsSchema=XS_2013), notizbuch_id, abschnitt)
                    if notizbuch_id else "")
    return Ziel(konto.konto, adresse, notizbuch_id, notizbuch, abschnitt, abschnitt_id)


def _namen_pruefen(notizbuch: str, ordner: str, abschnitt: str) -> None:
    """Gültige Namen; Ordner und Abschnitt ohne Punkt am Ende (SharePoint)."""
    if not all(_ABSCHNITT_RE.fullmatch(n) for n in (notizbuch, ordner, abschnitt)) or ordner.endswith(".") or abschnitt.endswith("."):
        raise OneNoteFehler("Ungültiger Name für Notizbuch oder Abschnitt")


def ziel_pruefen(abschnitt: str = ABSCHNITT, *, notizbuch: str = NOTIZBUCH, ordner: str = NOTIZBUCH_ORDNER,
                 konto: Firmenkonto | None = None, fabrik: Callable | None = None, timeout: float = LESEN_TIMEOUT_SECS,
                 warten: float = SPERRE_WARTEN_SECS) -> Ziel:
    """Nur lesen: das OneDrive der Firma, ob das Notizbuch dort offen ist und ob der Abschnitt da ist (für die Karte). Wirft
    OneNoteFehler (rueckfall, wenn es kein eindeutiges Firmenkonto gibt oder OneNote nicht taugt)."""
    _namen_pruefen(notizbuch, ordner, abschnitt)
    konto = konto or firmenkonto()
    adresse = notizbuch_adresse(konto, ordner)
    return _im_faden(lambda app: _ziel_lesen(app, konto, notizbuch, adresse, abschnitt), timeout, fabrik, warten)


def _ziel_wie_erwartet(app, erwartet: Ziel, konto: Firmenkonto) -> Ziel:
    """Konto, Notizbuch und Abschnitt direkt vor dem Anlegen noch einmal lesen: Sie müssen die der Karte sein."""
    if konto.konto != erwartet.konto or not erwartet.notizbuch_url.startswith(konto.site + "/"):
        raise OneNoteFehler("Das OneDrive der Firma hat sich seit der Anfrage geändert. Es wurde nichts angelegt.")
    ziel = _ziel_lesen(app, konto, erwartet.notizbuch, erwartet.notizbuch_url, erwartet.abschnitt)
    if erwartet.notizbuch_id and ziel.notizbuch_id != erwartet.notizbuch_id:
        raise OneNoteFehler(f"Das Notizbuch {erwartet.notizbuch} hat sich seit der Anfrage geändert. Es wurde nichts angelegt.")
    if erwartet.abschnitt_id and ziel.abschnitt_id != erwartet.abschnitt_id:
        raise OneNoteFehler(f"Der Abschnitt {erwartet.abschnitt} hat sich seit der Anfrage geändert. Es wurde nichts angelegt.")
    return ziel


def _notizbuch_anlegen(app, ziel: Ziel) -> str:
    """Erst nach dem Klick: das Notizbuch an seiner Adresse im OneDrive der Firma anlegen und ihm den Anzeigenamen geben."""
    notizbuch_id = app.OpenHierarchy(ziel.notizbuch_url, "", cftIfNotExist=CFT_NOTIZBUCH)
    aenderung = ET.Element(_q("Notebooks"))
    ET.SubElement(aenderung, _q("Notebook"), {"ID": notizbuch_id, "nickname": ziel.notizbuch})
    try:
        app.UpdateHierarchy(ET.tostring(aenderung, encoding="unicode"), xsSchema=XS_2013)
    except Exception:  # noqa: BLE001 (dann trägt es den Namen seines Ordners, die Seite geht trotzdem hinein)
        pass
    return notizbuch_id


def _abschnitt_anlegen(app, notizbuch_id: str, name: str) -> str:
    abschnitt_id = app.OpenHierarchy(f"{name}.one", notizbuch_id, cftIfNotExist=CFT_ABSCHNITT)
    try:
        app.SyncHierarchy(abschnitt_id)  # ein frischer Abschnitt im OneDrive nimmt erst nach dem Abgleich Seiten an
    except Exception:  # noqa: BLE001 (dann wartet _neue_seite)
        pass
    return abschnitt_id


def _neue_seite(app, abschnitt_id: str, abbruch: threading.Event) -> str:
    """CreateNewPage; meldet OneNote "noch nicht synchronisiert", noch einmal, höchstens SYNC_WARTEN_SECS lang."""
    frist = time.monotonic() + SYNC_WARTEN_SECS
    while True:
        try:
            return app.CreateNewPage(abschnitt_id)
        except Exception as e:  # noqa: BLE001 (nur "noch nicht synchronisiert" wird wiederholt)
            hresult = getattr(e, "hresult", None)
            if not isinstance(hresult, int) or hresult & 0xFFFFFFFF != NICHT_SYNCHRON or abbruch.is_set() or time.monotonic() > frist:
                raise
        time.sleep(1)


def _leere_seite_weg(app, seiten_id: str) -> str:
    """Nur die eigene, eben angelegte Seite wieder entfernen; liefert einen Zusatz für die Meldung, wenn sie bleibt."""
    try:
        app.DeleteHierarchy(seiten_id, dateExpectedLastModified=OHNE_DATUM, deletePermanently=True)
        return ""
    except Exception:  # noqa: BLE001 (dann bleibt die leere Seite, die Meldung sagt es)
        return " Eine leere Seite ist im Abschnitt geblieben, bitte von Hand löschen."


def _schreiben(app, seite: Seite, erwartet: Ziel, zeigen: bool, abbruch: threading.Event, konto: Firmenkonto) -> dict:
    seiten_xml(seite, "{}")  # vor dem Anlegen bauen: Ein Fehler im Inhalt hinterlässt so keine leere Seite
    ziel = _ziel_wie_erwartet(app, erwartet, konto)
    if abbruch.is_set():
        raise OneNoteFehler(ZU_SPAET_SCHREIBEN)
    notizbuch_id = ziel.notizbuch_id or _notizbuch_anlegen(app, ziel)
    abschnitt_id = ziel.abschnitt_id or _abschnitt_anlegen(app, notizbuch_id, ziel.abschnitt)
    seiten_id = _neue_seite(app, abschnitt_id, abbruch)
    if abbruch.is_set():  # die Person hat schon "nicht in der Zeit" gehört: keine halbe Seite stehen lassen
        raise OneNoteFehler(ZU_SPAET_SCHREIBEN + _leere_seite_weg(app, seiten_id))
    try:
        app.UpdatePageContent(seiten_xml(seite, seiten_id), dateExpectedLastModified=OHNE_DATUM, xsSchema=XS_2013)
    except Exception as e:  # noqa: BLE001 (COM lehnt den Inhalt ab)
        raise OneNoteFehler(f"OneNote hat den Inhalt der Seite nicht angenommen ({_com_text(e)})."
                            + _leere_seite_weg(app, seiten_id)) from None
    if zeigen:
        try:
            app.NavigateTo(seiten_id)
        except Exception:  # noqa: BLE001 (Anzeigen ist nur Komfort, die Seite ist angelegt)
            pass
    return {"seite_id": seiten_id, "abschnitt_id": abschnitt_id, "abschnitt_neu": not ziel.abschnitt_id,
            "notizbuch_neu": not ziel.notizbuch_id, "notizbuch": ziel.notizbuch, "abschnitt": ziel.abschnitt}


def seite_anlegen(seite: Seite, erwartet: Ziel, *, zeigen: bool = True, konto: Firmenkonto | None = None,
                  fabrik: Callable | None = None, timeout: float = SCHREIBEN_TIMEOUT_SECS) -> dict:
    """Nach der Freigabe: Seite im Abschnitt des erwarteten Notizbuchs anlegen (Notizbuch und Abschnitt bei Bedarf auch), danach
    zeigen. Das Firmenkonto wird dafür neu bestimmt und muss das der Karte sein."""
    _namen_pruefen(erwartet.notizbuch, erwartet.notizbuch_url.rsplit("/", 1)[-1], erwartet.abschnitt)
    konto = konto or firmenkonto()
    abbruch = threading.Event()
    return _im_faden(lambda app: _schreiben(app, seite, erwartet, zeigen, abbruch, konto), timeout, fabrik, abbruch=abbruch,
                     zu_spaet=ZU_SPAET_SCHREIBEN)


# ---------- Ratenbremse ----------
class Bremse:
    """Höchstens anzahl gezählte Ereignisse im gleitenden Fenster von fenster_s Sekunden. voll() prüft, zaehlen() zählt; so zählen
    nur Anfragen, die wirklich eine Karte ergeben (Fehlversuche verbrauchen nichts)."""

    def __init__(self, anzahl: int, fenster_s: float, uhr: Callable[[], float] = time.monotonic):
        self._anzahl, self._fenster, self._uhr = anzahl, fenster_s, uhr
        self._zeiten: deque[float] = deque()
        self._lock = threading.Lock()

    def _aufraeumen(self) -> float:
        jetzt = self._uhr()
        while self._zeiten and jetzt - self._zeiten[0] >= self._fenster:
            self._zeiten.popleft()
        return jetzt

    def voll(self) -> bool:
        with self._lock:
            self._aufraeumen()
            return len(self._zeiten) >= self._anzahl

    def zaehlen(self) -> None:
        with self._lock:
            self._zeiten.append(self._aufraeumen())
