"""Ablage der Office-Dateien am PC: Ordner WAIS im bekannten Ordner Dokumente, Dateinamen und Register.

* Der Ordner Dokumente kommt aus dem bekannten Ordner von Windows (SHGetKnownFolderPath), nicht aus HOME\\Documents: Ist er auf
  OneDrive umgeleitet (am PC von Niko der Fall, Prüfauftrag P0), liegt er woanders. Nur wenn die Shell nicht antwortet, gilt
  HOME\\Documents.
* Der Unterordner heißt WAIS (Windows streicht den Schlusspunkt von "W.A.I.S."). Er darf weder Verknüpfung noch Abzweigpunkt
  sein (Reparse-Punkt mit Namensersatz); Platzhalter von OneDrive (Cloud-Reparse-Punkte ohne Namensersatz) sind erlaubt.
* Dateiname: "JJJJ-MM-TT <Titel>.<Endung>", Titel ohne die von Windows verbotenen Zeichen, ohne Steuer- und Richtungszeichen,
  höchstens TITEL_MAX Zeichen, ohne Punkt oder Leerzeichen am Rand. Gibt es die Datei schon, folgt " (2)", nie Überschreiben
  (exklusives Anlegen, auch gegen gleichzeitige Aufrufe).
* Register %LOCALAPPDATA%\\WAMO\\ablage.json: je Datei Kennung, Name, Format, Größe, SHA-256, Zeit, Canvas-Kennung, nie Inhalte;
  höchstens REGISTER_MAX Einträge. Nur Dateien aus dem Register öffnet der Host (office_datei_oeffnen).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ORDNER_NAME = "WAIS"
ORDNER_ANZEIGE = "Dokumente\\WAIS"
REGISTER_MAX = 500
TITEL_MAX = 80
NAMEN_VERSUCHE = 99
ENDUNGEN = {"word": ".docx", "excel": ".xlsx", "powerpoint": ".pptx", "pdf": ".pdf", "csv": ".csv", "markdown": ".md"}
KENNUNG_RE = re.compile(r"[0-9a-f]{16}")
# Steuer-, Richtungs- und Nullbreitenzeichen (könnten eine Endung vortäuschen) fallen weg, von Windows verbotene Zeichen werden
# zu Leerzeichen.
_UNSICHTBAR = re.compile("[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
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
        """Einträge des Registers (älteste zuerst). Fehlt oder ist es kaputt, gilt es als leer."""
        try:
            daten = json.loads(self.register.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        dateien = daten.get("dateien") if isinstance(daten, dict) else None
        return [e for e in dateien if isinstance(e, dict) and isinstance(e.get("kennung"), str)] if isinstance(dateien, list) else []

    def _schreiben(self, eintraege: list[dict]) -> None:
        self.register.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.register.with_name(f".{self.register.name}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps({"version": 1, "dateien": eintraege[-self.max_eintraege:]}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.register)

    # ---------- Speichern ----------
    def speichern(self, daten: bytes, titel: object, fmt: str, canvas_id: str | None = None,
                  datum: date | None = None) -> dict:
        """Legt die Datei neu an (nie überschreiben) und trägt sie ins Register ein. Liefert den Eintrag."""
        name = dateiname(titel, fmt, datum or date.today())
        stamm, endung = name[: -len(ENDUNGEN[fmt])], ENDUNGEN[fmt]
        with self._lock:
            ordner = self.ordner()
            for nr in range(1, NAMEN_VERSUCHE + 1):
                kandidat = name if nr == 1 else f"{stamm} ({nr}){endung}"
                pfad = ordner / kandidat
                try:
                    with open(pfad, "xb") as f:
                        f.write(daten)
                except FileExistsError:
                    continue
                except OSError as e:
                    raise AblageFehler(f"Die Datei ließ sich nicht speichern ({type(e).__name__})") from e
                break
            else:
                raise AblageFehler("Zu viele Dateien mit diesem Titel an diesem Tag")
            eintrag = {"kennung": secrets.token_hex(8), "name": kandidat, "format": fmt, "groesse": len(daten),
                       "sha256": hashlib.sha256(daten).hexdigest(), "zeit": datetime.now(timezone.utc).isoformat(),
                       "canvas_id": canvas_id}
            self._schreiben([*self.eintraege(), eintrag])
        return eintrag

    # ---------- Öffnen ----------
    def pfad(self, kennung: object) -> Path:
        """Pfad einer Datei aus dem Register: gültige Kennung, Name ohne Pfadteile, im Ordner WAIS, vorhanden, kein Verweis."""
        if not isinstance(kennung, str) or not KENNUNG_RE.fullmatch(kennung):
            raise AblageFehler("Unbekannte Datei")
        eintrag = next((e for e in reversed(self.eintraege()) if e.get("kennung") == kennung), None)
        if eintrag is None:
            raise AblageFehler("Diese Datei kennt W.A.I.S. nicht (nur selbst erzeugte Dateien)")
        name = eintrag.get("name")
        if not isinstance(name, str) or Path(name).name != name or _UNERLAUBT.search(name) or name in ("", ".", ".."):
            raise AblageFehler("Der Eintrag im Register ist ungültig")
        ordner = self.ordner()
        pfad = ordner / name
        if ist_verweis(pfad) or not pfad.is_file() or not _gleich(pfad.resolve().parent, ordner):
            raise AblageFehler("Die Datei liegt nicht mehr im Ordner WAIS")
        return pfad
