"""OneNote per COM (Paket 4 von docs/office-und-versand.md): eine neue Seite aus einem Canvas-Inhalt im Standard-Notizbuch der Person,
Abschnitt ABSCHNITT ("W.A.I.S.", angelegt, wenn er fehlt).

* Erkennung ohne Start (onenote_vorhanden): OneNote.Application ist registriert und ihr lokaler Server ist ONENOTE.EXE, die es gibt.
  OneNote für Windows 10 und OneNote im Web haben keine COM-Schnittstelle; dann schlägt der Kern eine Word-Datei vor.
* Zugriff über comtypes mit der Typbibliothek von OneNote (die späte Bindung von pywin32 findet GetHierarchy nicht).
* Jeder Zugriff läuft in einem eigenen Faden mit eigener COM-Anmeldung, mit Zeitgrenze und immer nur einer zur Zeit (_SPERRE). OneNote
  ist die Instanz der Person: Der Host beendet sie nie und schließt kein Fenster.
* Standard-Notizbuch: das Notizbuch, in dem der Abschnitt für schnelle Notizen liegt (Einstellung in OneNote), sonst das erste der
  Liste. Die Karte nennt es; vor dem Anlegen prüft der Host, dass es noch dasselbe ist. Geändert wird nur die neue Seite, der Abschnitt
  wird höchstens angelegt. Gelöscht wird nur die eigene, eben angelegte Seite, wenn ihr Inhalt nicht geschrieben werden konnte.
* Seiten-XML im Namensraum 2013, gebaut mit ElementTree: Jeder Text aus dem Canvas steht HTML-maskiert in one:T (OneNote liest one:T
  als HTML), Auszeichnungen (fett, Überschrift, Festbreite) setzt nur dieser Code. Keine Links, keine Bilder, keine Dateien.
"""

from __future__ import annotations

import html
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
ABSCHNITT = "W.A.I.S."
TITEL_MAX = 120
TITEL_EINGABE_MAX = 300
SEITEN_JE_STUNDE = 10
LESEN_TIMEOUT_SECS = 30
SCHREIBEN_TIMEOUT_SECS = 60
SPERRE_WARTEN_SECS = 2.0
TYPBIBLIOTHEK = ("{0EA692EE-BB50-4E3C-AEF0-356D91732725}", 1, 1)  # Microsoft OneNote 15.0 Object Library
HS_NOTIZBUECHER, HS_ABSCHNITTE = 2, 3
XS_2013 = 2
CFT_ABSCHNITT = 3
OHNE_DATUM = 0.0  # dateExpectedLastModified: ohne Prüfung; muss mitgehen, der Standard der Typbibliothek passt nicht zu c_double
SL_SCHNELLE_NOTIZEN = 1
ZIEL_NAME_MAX = 60
CODE_STIL = "font-family:Consolas;font-size:10.0pt"
UEBERSCHRIFT_GROESSE = {1: "16.0", 2: "13.0", 3: "12.0"}
FETT = "<span style='font-weight:bold'>{}</span>"
CODE_INLINE = "<span style='font-family:Consolas'>{}</span>"
_CLSID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_ABSCHNITT_RE = re.compile(r'[^\\/:*?"<>|#%\x00-\x1f]{1,50}')
# Wie persona.sichtbar im Kern, das die Karte bereinigt: Steuer-, Format-, Richtungs- und unsichtbare Zeichen, Variantenwähler. Der Host
# entfernt sie schon im Inhalt, damit Karte und Seite zeichengleich sind (ein U+202E könnte sonst den Text auf der Seite umdrehen).
_UNSICHTBAR = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_UNSICHTBAR_EXTRA = frozenset({0x034F, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)})
_SPERRE = threading.Lock()


class OneNoteFehler(RuntimeError):
    """OneNote ist nicht bereit oder hat einen Fehler gemeldet (Text ist für Menschen gedacht). rueckfall: Eine Word-Datei ist der
    richtige Ersatz (OneNote fehlt, startet nicht oder hat kein Notizbuch), nicht bei "beschäftigt", Zeitüberschreitung oder Schutz."""

    def __init__(self, text: str, *, rueckfall: bool = False):
        super().__init__(text)
        self.rueckfall = rueckfall


@dataclass(frozen=True)
class Ziel:
    notizbuch_id: str
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


# ---------- Standard-Notizbuch und Abschnitt ----------
def _q(name: str) -> str:
    return f"{{{NS}}}{name}"


def _xml(text: object) -> ET.Element:
    try:
        return ET.fromstring(text if isinstance(text, str) else "")
    except ET.ParseError as e:
        raise OneNoteFehler("OneNote hat eine unlesbare Übersicht der Notizbücher geliefert.", rueckfall=True) from e


def _pfad_vergleich(pfad: str) -> str:
    return (pfad or "").replace("\\", "/").rstrip("/").casefold()


def notizbuch_waehlen(hierarchie: str, schnell_pfad: str) -> tuple[str, str]:
    """(Kennung, Name) des Standard-Notizbuchs: das mit dem Abschnitt für schnelle Notizen, sonst das erste der Liste."""
    buecher = [nb for nb in _xml(hierarchie).iter(_q("Notebook")) if nb.get("ID")]
    if not buecher:
        raise OneNoteFehler("In OneNote ist kein Notizbuch geöffnet. Bitte in OneNote ein Notizbuch öffnen.", rueckfall=True)
    schnell = _pfad_vergleich(schnell_pfad)
    gewaehlt = next((nb for nb in buecher if _pfad_vergleich(nb.get("path", "")) and
                     schnell.startswith(_pfad_vergleich(nb.get("path", "")) + "/")), buecher[0])
    return gewaehlt.get("ID"), uia_control.sicherer_text(gewaehlt.get("nickname") or gewaehlt.get("name") or "", 200)


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
    ET.register_namespace("one", NS)
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


def karten_ziel(ziel: Ziel) -> str:
    name = ziel.notizbuch if len(ziel.notizbuch) <= ZIEL_NAME_MAX else ziel.notizbuch[: ZIEL_NAME_MAX - 1] + "…"
    return f"OneNote, Notizbuch {name}, Abschnitt {ziel.abschnitt}" + ("" if ziel.abschnitt_id else " (wird angelegt)")


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


def _ziel_lesen(app, abschnitt: str) -> Ziel:
    hierarchie = app.GetHierarchy("", HS_NOTIZBUECHER, xsSchema=XS_2013)
    try:
        schnell = app.GetSpecialLocation(SL_SCHNELLE_NOTIZEN) or ""
    except Exception:  # noqa: BLE001 (ohne Abschnitt für schnelle Notizen gilt das erste Notizbuch)
        schnell = ""
    notizbuch_id, name = notizbuch_waehlen(hierarchie, schnell)
    abschnitte = app.GetHierarchy(notizbuch_id, HS_ABSCHNITTE, xsSchema=XS_2013)
    return Ziel(notizbuch_id, name, abschnitt, abschnitt_suchen(abschnitte, notizbuch_id, abschnitt))


def ziel_pruefen(abschnitt: str = ABSCHNITT, *, fabrik: Callable | None = None, timeout: float = LESEN_TIMEOUT_SECS,
                 warten: float = SPERRE_WARTEN_SECS) -> Ziel:
    """Nur lesen: Standard-Notizbuch und ob der Abschnitt schon da ist (für die Karte). Wirft OneNoteFehler."""
    if not _ABSCHNITT_RE.fullmatch(abschnitt):
        raise OneNoteFehler("Ungültiger Name für den Abschnitt")
    return _im_faden(lambda app: _ziel_lesen(app, abschnitt), timeout, fabrik, warten)


def _ziel_wie_erwartet(app, erwartet: Ziel) -> Ziel:
    """Notizbuch und Abschnitt direkt vor dem Anlegen noch einmal lesen: Sie müssen die der Karte sein."""
    ziel = _ziel_lesen(app, erwartet.abschnitt)
    if ziel.notizbuch_id != erwartet.notizbuch_id:
        raise OneNoteFehler("Das Standard-Notizbuch in OneNote hat sich seit der Anfrage geändert. Es wurde nichts angelegt.")
    if erwartet.abschnitt_id and ziel.abschnitt_id != erwartet.abschnitt_id:
        raise OneNoteFehler(f"Der Abschnitt {erwartet.abschnitt} hat sich seit der Anfrage geändert. Es wurde nichts angelegt.")
    return ziel


def _leere_seite_weg(app, seiten_id: str) -> str:
    """Nur die eigene, eben angelegte Seite wieder entfernen; liefert einen Zusatz für die Meldung, wenn sie bleibt."""
    try:
        app.DeleteHierarchy(seiten_id, dateExpectedLastModified=OHNE_DATUM, deletePermanently=True)
        return ""
    except Exception:  # noqa: BLE001 (dann bleibt die leere Seite, die Meldung sagt es)
        return " Eine leere Seite ist im Abschnitt geblieben, bitte von Hand löschen."


def _schreiben(app, seite: Seite, erwartet: Ziel, zeigen: bool, abbruch: threading.Event) -> dict:
    seiten_xml(seite, "{}")  # vor dem Anlegen bauen: Ein Fehler im Inhalt hinterlässt so keine leere Seite
    ziel = _ziel_wie_erwartet(app, erwartet)
    if abbruch.is_set():
        raise OneNoteFehler(ZU_SPAET_SCHREIBEN)
    abschnitt_id = ziel.abschnitt_id or app.OpenHierarchy(f"{erwartet.abschnitt}.one", ziel.notizbuch_id,
                                                           cftIfNotExist=CFT_ABSCHNITT)
    seiten_id = app.CreateNewPage(abschnitt_id)
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
            "notizbuch": ziel.notizbuch, "abschnitt": erwartet.abschnitt}


def seite_anlegen(seite: Seite, erwartet: Ziel, *, zeigen: bool = True, fabrik: Callable | None = None,
                  timeout: float = SCHREIBEN_TIMEOUT_SECS) -> dict:
    """Nach der Freigabe: Seite im Abschnitt des erwarteten Notizbuchs anlegen (Abschnitt bei Bedarf auch), danach zeigen."""
    if not _ABSCHNITT_RE.fullmatch(erwartet.abschnitt):
        raise OneNoteFehler("Ungültiger Name für den Abschnitt")
    abbruch = threading.Event()
    return _im_faden(lambda app: _schreiben(app, seite, erwartet, zeigen, abbruch), timeout, fabrik, abbruch=abbruch,
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
