"""Ablage der Office-Dateien am PC: Ordner WAIS im bekannten Ordner Dokumente, Dateinamen und Register.

* Der Ordner Dokumente kommt aus dem bekannten Ordner von Windows (SHGetKnownFolderPath), nicht aus HOME\\Documents: Ist er auf
  OneDrive umgeleitet (am PC von Niko der Fall, Prüfauftrag P0), liegt er woanders. Nur wenn die Shell nicht antwortet, gilt
  HOME\\Documents.
* Der Unterordner heißt WAIS (Windows streicht den Schlusspunkt von "W.A.I.S."). Er darf weder Verknüpfung noch Abzweigpunkt
  sein (Reparse-Punkt mit Namensersatz); Platzhalter von OneDrive (Cloud-Reparse-Punkte ohne Namensersatz) sind erlaubt.
* Dateiname: "JJJJ-MM-TT <Titel>.<Endung>", Titel ohne die von Windows verbotenen Zeichen, ohne Steuer-, Richtungs- und andere
  unsichtbare Zeichen, höchstens TITEL_MAX Zeichen, ohne Punkt oder Leerzeichen am Rand. Gibt es die Datei schon (auch als
  hängender Verweis), folgt " (2)", nie Überschreiben (exklusives Anlegen, auch gegen gleichzeitige Aufrufe). Windows folgt beim
  exklusiven Anlegen einem hängenden Verweis; deshalb muss der Endpfad der neuen Datei danach im Ordner WAIS liegen, sonst wird sie
  wieder entfernt.
* Register %LOCALAPPDATA%\\WAMO\\ablage.json: je Datei Kennung, Name, Format, Größe, SHA-256, Zeit, Canvas-Kennung, nie Inhalte;
  höchstens REGISTER_MAX Einträge. Nur Dateien aus dem Register mit der festen Endung ihres Formats öffnet der Host
  (office_datei_oeffnen). Fehlt das Register, ist es leer; ist es kaputt, wird es als .kaputt beiseitegelegt; ist es gesperrt
  (Virenscanner, Indexdienst), wird kurz wiederholt, dann gilt das als Fehler (nie ein neues Register ohne die alten Einträge).
  Lesen und Schreiben laufen unter einer Sperre je Ablage.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ORDNER_NAME = "WAIS"
ORDNER_ANZEIGE = "Dokumente\\WAIS"
REGISTER_MAX = 500
TITEL_MAX = 80
NAMEN_VERSUCHE = 99
VERSUCHE = 4  # Register lesen oder ersetzen, solange ein anderer Prozess (Virenscanner, Indexdienst) es kurz offen hat
WARTEN_SECS = 0.05
ENDUNGEN ={"word": ".docx", "excel": ".xlsx", "powerpoint": ".pptx", "pdf": ".pdf", "csv": ".csv", "markdown": ".md"}
KENNUNG_RE = re.compile(r"[0-9a-f]{16}")
# Steuer-, Richtungs-, Nullbreiten- und weitere unsichtbare Zeichen (könnten eine Endung vortäuschen) fallen weg, ebenso einzelne
# Ersatzzeichen; von Windows verbotene Zeichen werden zu Leerzeichen. Bereiche als Codepunkte, ohne Escape-Folgen im Quelltext.
_UNSICHTBAR = re.compile("[" + "".join(re.escape(chr(a)) + "-" + re.escape(chr(b)) for a, b in (
    (0x00, 0x1F), (0x7F, 0x9F), (0xAD, 0xAD), (0x061C, 0x061C), (0x180E, 0x180E), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x2069), (0xD800, 0xDFFF), (0xFEFF, 0xFEFF))) + "]")
_VERBOTEN = re.compile(r'[<>:"/\\|?*]')
_UNERLAUBT = re.compile(_UNSICHTBAR.pattern[:-1] + r'<>:"/\\|?*]')
_FOLDERID_DOCUMENTS = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
_REPARSE_NAMENSERSATZ = 0x20000000  # IsReparseTagNameSurrogate: Verknüpfung oder Abzweigpunkt
_REPARSE_PUNKT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


class AblageFehler(ValueError):
    """Die Datei kann nicht sicher abgelegt oder geöffnet werden (Text ist für Menschen gedacht)."""


def _bekannter_ordner() -> Path | None:
    """Pfad des bekannten Ordners Dokumente über die Shell oder None (kein Windows, Shell antwortet nicht)."""
    if sys.platform != "win32":
        return None

    class _Guid(ctypes.Structure):
        _fields_ = [("daten", ctypes.c_ubyte * 16)]

    guid = _Guid()
    ctypes.memmove(ctypes.byref(guid), _FOLDERID_DOCUMENTS.bytes_le, 16)
    zeiger = ctypes.c_wchar_p()
    try:
        ergebnis = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(zeiger))
        try:
            pfad = zeiger.value if ergebnis == 0 else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(zeiger)
    except (OSError, AttributeError):
        return None
    return Path(pfad) if pfad else None


def dokumente_ordner() -> Path:
    """Der Ordner Dokumente der angemeldeten Person (folgt einer Umleitung auf OneDrive)."""
    pfad = _bekannter_ordner()
    if pfad is not None:
        return pfad
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents"


def ist_verweis(pfad: Path) -> bool:
    """Verknüpfung oder Abzweigpunkt (Reparse-Punkt mit Namensersatz)? Fehlt der Pfad: False."""
    try:
        st = os.lstat(pfad)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attribute = getattr(st, "st_file_attributes", 0)
    marke = getattr(st, "st_reparse_tag", 0)
    return bool(attribute & _REPARSE_PUNKT and marke & _REPARSE_NAMENSERSATZ)


def _titel(titel: object) -> str:
    text = unicodedata.normalize("NFC", titel if isinstance(titel, str) else "")
    text = " ".join(_VERBOTEN.sub(" ", _UNSICHTBAR.sub("", text)).split())
    text = text[:TITEL_MAX].strip(" .")
    return text or "Canvas"


def dateiname(titel: object, fmt: str, datum: date) -> str:
    """Dateiname aus Datum, bereinigtem Titel und der Endung des Formats."""
    if fmt not in ENDUNGEN:
        raise AblageFehler("Unbekanntes Format")
    return f"{datum.isoformat()} {_titel(titel)}{ENDUNGEN[fmt]}"


def _gleich(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _existiert(pfad: Path) -> bool:
    """Gibt es den Namen schon, auch als hängenden Verweis?"""
    return os.path.lexists(pfad)


def _endpfad_entfernen(pfad: Path) -> None:
    """Die eben exklusiv angelegte Datei wieder entfernen, dort, wo sie wirklich liegt (nie den Verweis selbst)."""
    with contextlib.suppress(OSError):
        os.remove(os.path.realpath(pfad))


def _endpfad_pruefen(pfad: Path) -> None:
    """Die neue Datei muss genau unter ihrem Namen im Ordner WAIS liegen: kein Verweis, dem das Anlegen gefolgt ist (Wettlauf
    mit der Vorprüfung). Sonst wird sie entfernt."""
    if ist_verweis(pfad) or not _gleich(Path(os.path.realpath(pfad)), pfad):
        _endpfad_entfernen(pfad)
        raise AblageFehler("Im Ordner WAIS liegt ein Verweis mit diesem Namen; dort legt W.A.I.S. nichts ab")


class Ablage:
    """Ordner und Register. wurzel: der Ordner Dokumente; register: Pfad der Registerdatei."""

    def __init__(self, wurzel: Path, register: Path, max_eintraege: int = REGISTER_MAX):
        self.wurzel = Path(wurzel)
        self.register = Path(register)
        self.max_eintraege = max_eintraege
        self._lock = threading.Lock()

    @classmethod
    def standard(cls) -> Ablage:
        lokal = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return cls(dokumente_ordner(), Path(lokal) / "WAMO" / "ablage.json")

    # ---------- Ordner ----------
    def ordner(self) -> Path:
        """Ordner WAIS: anlegen, wenn er fehlt; nie über eine Verknüpfung oder einen Abzweigpunkt."""
        if not self.wurzel.is_dir():
            raise AblageFehler("Den Ordner Dokumente gibt es auf diesem PC nicht")
        try:
            basis = self.wurzel.resolve(strict=True)
        except OSError as e:
            raise AblageFehler("Der Ordner Dokumente ist nicht erreichbar") from e
        ziel = basis / ORDNER_NAME
        if ist_verweis(ziel):
            raise AblageFehler("Der Ordner WAIS ist eine Verknüpfung; dort legt W.A.I.S. nichts ab")
        try:
            ziel.mkdir(exist_ok=True)
        except FileExistsError as e:
            raise AblageFehler("WAIS in Dokumente ist eine Datei, kein Ordner") from e
        except OSError as e:
            raise AblageFehler(f"Der Ordner WAIS lässt sich nicht anlegen ({type(e).__name__})") from e
        if not ziel.is_dir() or ist_verweis(ziel) or not _gleich(ziel.resolve(), ziel):
            raise AblageFehler("Der Ordner WAIS zeigt woandershin; dort legt W.A.I.S. nichts ab")
        return ziel

    # ---------- Register ----------
    def eintraege(self) -> list[dict]:
        """Einträge des Registers (älteste zuerst). Fehlt es, ist es leer; kaputt wird es beiseitegelegt. Wirft AblageFehler,
        wenn es sich auch nach kurzem Warten nicht lesen lässt."""
        with self._lock:
            return self._lesen()

    def _lesen(self) -> list[dict]:
        """Wie eintraege, ohne Sperre (der Aufrufer hält sie)."""
        text = None
        for versuch in range(VERSUCHE):
            try:
                text = self.register.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                return []
            except UnicodeDecodeError:
                break  # kaputt, unten beiseitelegen
            except OSError as e:  # gesperrt (Virenscanner, Indexdienst): kurz warten, nie still als leer werten
                if versuch == VERSUCHE - 1:
                    raise AblageFehler(f"Das Register der Dateien ist gerade nicht lesbar ({type(e).__name__})") from e
                time.sleep(WARTEN_SECS * (versuch + 1))
        try:
            daten = json.loads(text) if text is not None else None
        except ValueError:
            daten = None
        dateien = daten.get("dateien") if isinstance(daten, dict) else None
        if not isinstance(dateien, list):
            self._beiseitelegen()
            return []
        return [e for e in dateien if isinstance(e, dict) and isinstance(e.get("kennung"), str)]

    def _beiseitelegen(self) -> None:
        """Kaputtes Register als <Name>.<Zeit>.kaputt aufheben (nichts still verwerfen), danach gilt es als leer."""
        ziel = self.register.with_name(f"{self.register.name}.{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}.kaputt")
        try:
            os.replace(self.register, ziel)
        except FileNotFoundError:
            return
        except OSError as e:
            raise AblageFehler(f"Das Register der Dateien ist kaputt und lässt sich nicht beiseitelegen ({type(e).__name__})") from e

    def _schreiben(self, eintraege: list[dict]) -> None:
        """Register atomar ersetzen; ist es gerade offen (PermissionError unter Windows), kurz wiederholen. Keine Reste."""
        tmp = self.register.with_name(f".{self.register.name}.{secrets.token_hex(4)}.tmp")
        try:
            self.register.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"version": 1, "dateien": eintraege[-self.max_eintraege:]}, ensure_ascii=False),
                           encoding="utf-8")
            for versuch in range(VERSUCHE):
                try:
                    os.replace(tmp, self.register)
                    return
                except PermissionError:
                    if versuch == VERSUCHE - 1:
                        raise
                    time.sleep(WARTEN_SECS * (versuch + 1))
        except OSError as e:
            raise AblageFehler(f"Das Register der Dateien ließ sich nicht schreiben ({type(e).__name__})") from e
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)

    # ---------- Speichern ----------
    def speichern(self, daten: bytes, titel: object, fmt: str, canvas_id: str | None = None,
                  datum: date | None = None) -> tuple[dict, Path]:
        """Legt die Datei neu an (nie überschreiben) und trägt sie ins Register ein. Liefert Eintrag und Pfad. Scheitert das
        Register, wird die neue Datei wieder entfernt."""
        name = dateiname(titel, fmt, datum or date.today())
        with self._lock:
            ordner = self.ordner()
            bisher = self._lesen()  # vor dem Anlegen: ist das Register nicht lesbar, entsteht keine Datei
            pfad = self._anlegen(ordner, name, ENDUNGEN[fmt], daten)
            eintrag = {"kennung": secrets.token_hex(8), "name": pfad.name, "format": fmt, "groesse": len(daten),
                       "sha256": hashlib.sha256(daten).hexdigest(), "zeit": datetime.now(timezone.utc).isoformat(),
                       "canvas_id": canvas_id}
            try:
                self._schreiben([*bisher, eintrag])
            except AblageFehler:
                with contextlib.suppress(OSError):
                    pfad.unlink()
                raise
        return eintrag, pfad

    @staticmethod
    def _anlegen(ordner: Path, name: str, endung: str, daten: bytes) -> Path:
        """Neue Datei exklusiv anlegen: name, sonst "<Stamm> (2)<Endung>" usw. Was es schon gibt, auch als hängender Verweis,
        bleibt unberührt."""
        stamm = name[: -len(endung)]
        for nr in range(1, NAMEN_VERSUCHE + 1):
            pfad = ordner / (name if nr == 1 else f"{stamm} ({nr}){endung}")
            if _existiert(pfad):  # Windows folgte einem hängenden Verweis beim exklusiven Anlegen
                continue
            try:
                datei = open(pfad, "xb")  # noqa: SIM115 (Fehler beim Schreiben räumt unten auf)
            except FileExistsError:
                continue
            except OSError as e:
                raise AblageFehler(f"Die Datei ließ sich nicht speichern ({type(e).__name__})") from e
            try:
                with datei:
                    datei.write(daten)
            except OSError as e:
                _endpfad_entfernen(pfad)
                raise AblageFehler(f"Die Datei ließ sich nicht speichern ({type(e).__name__})") from e
            _endpfad_pruefen(pfad)
            return pfad
        raise AblageFehler("Zu viele Dateien mit diesem Titel an diesem Tag")

    # ---------- Öffnen ----------
    def pfad(self, kennung: object) -> Path:
        """Pfad einer Datei aus dem Register: gültige Kennung, Name ohne Pfadteile mit der festen Endung seines Formats, im Ordner
        WAIS, vorhanden, kein Verweis."""
        if not isinstance(kennung, str) or not KENNUNG_RE.fullmatch(kennung):
            raise AblageFehler("Unbekannte Datei")
        with self._lock:
            eintraege = self._lesen()
        eintrag = next((e for e in reversed(eintraege) if e.get("kennung") == kennung), None)
        if eintrag is None:
            raise AblageFehler("Diese Datei kennt W.A.I.S. nicht (nur selbst erzeugte Dateien)")
        name, fmt = eintrag.get("name"), eintrag.get("format")
        if not isinstance(name, str) or Path(name).name != name or _UNERLAUBT.search(name) or name in ("", ".", ".."):
            raise AblageFehler("Der Eintrag im Register ist ungültig")
        if not isinstance(fmt, str) or fmt not in ENDUNGEN or not name.endswith(ENDUNGEN[fmt]):
            raise AblageFehler("Der Eintrag im Register ist ungültig (Endung passt nicht zum Format)")
        ordner = self.ordner()
        pfad = ordner / name
        if ist_verweis(pfad) or not pfad.is_file() or not _gleich(pfad.resolve().parent, ordner):
            raise AblageFehler("Die Datei liegt nicht mehr im Ordner WAIS")
        return pfad
