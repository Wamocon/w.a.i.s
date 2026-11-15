"""Office per COM, nur wo es ohne nicht geht. In Paket 1: PDF über Word aus der selbst gebauten Word-Datei.

* Eigene, unsichtbare Word-Instanz (DispatchEx), nie das offene Word der Person: DisplayAlerts aus, Makros in programmatisch geöffneten
  Dateien aus (AutomationSecurity), Datei nur lesend und nicht in "Zuletzt verwendet", danach Close und Quit ohne Speichern.
* Höchstens eine Umwandlung gleichzeitig (Sperre über die ganze Lebenszeit der Instanz, freigegeben erst am Ende ihres Threads).
* Eigener Thread mit CoInitialize, Zeitgrenze PDF_TIMEOUT_SECS. Hängt Word, auch schon beim Start, beendet der Host nur Prozesse, die
  seit dem Start dieser Umwandlung neu dazukamen (Vergleich der WINWORD.EXE-Kennungen, Prüfauftrag P0) und deren Befehlszeile
  "/Automation -Embedding" trägt (so startet COM Word). Ein Word, das die Person selbst geöffnet hat, und jede Kennung, deren
  Befehlszeile nicht lesbar ist, bleiben unberührt. tasklist und taskkill kommen mit vollem Pfad aus System32. Hängt eine Instanz,
  die der Host so nicht sicher als eigene erkennt, bleibt PDF bis zu ihrem Ende gesperrt (lieber keine PDF als ein fremdes Word
  beenden); Word, Excel, PowerPoint, CSV und Markdown gehen weiter.
* Fehler von COM nennen HRESULT hexadezimal (Meldung und Audit des Hosts).
* Ein- und Ausgabe liegen in einem eigenen Wegwerfordner im Temp-Ordner des Benutzers, nie im Ordner WAIS.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

import office_dateien

PDF_TIMEOUT_SECS = 45
PDF_MAX = 20 * 1024 * 1024
SPERRE_WARTEN_SECS = 5.0
WD_EXPORT_PDF = 17
WD_NICHT_SPEICHERN = 0
WD_KEINE_MELDUNGEN = 0
MAKROS_AUS = 3  # msoAutomationSecurityForceDisable
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_COMMAND_LINE_INFORMATION = 60  # ab Windows 8.1
_UMWANDLUNG = threading.Lock()
_log = logging.getLogger(__name__)


class PdfFehler(RuntimeError):
    """PDF ließ sich nicht erzeugen (Text ist für Menschen gedacht)."""


def word_vorhanden() -> bool:
    """Ist Word für COM registriert? Nur die Registrierung, Word wird dafür nicht gestartet."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID").Close()
        return True
    except OSError:
        return False


def faehigkeiten() -> dict:
    """Was am PC geht: alle Dateiformate über die Bibliotheken, PDF nur mit Word."""
    word = word_vorhanden()
    return {"formate": [f for f in office_dateien.FORMATE if f != "pdf" or word], "word": word}


def _system32(programm: str) -> str:
    """Voller Pfad eines Windows-Programms (nie über PATH)."""
    return str(Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / programm)


def _pids_aus_tasklist(text: str) -> set[int]:
    pids = set()
    for zeile in text.splitlines():
        teile = [t.strip('"') for t in zeile.split('","')]
        if len(teile) >= 2 and teile[0].strip('"').lower() == "winword.exe" and teile[1].isdigit():
            pids.add(int(teile[1]))
    return pids


def _word_pids() -> set[int]:
    """Kennungen aller laufenden WINWORD.EXE dieses Benutzers."""
    try:
        p = subprocess.run([_system32("tasklist.exe"), "/FI", "IMAGENAME eq WINWORD.EXE", "/FO", "CSV", "/NH"],
                           capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return set()
    # Meldungen von tasklist kommen in der OEM-Codepage (Umlaute): als Bytes lesen, Kennungen sind reine Ziffern
    return _pids_aus_tasklist((p.stdout or b"").decode("ascii", "replace"))


def _beenden(pid: int) -> None:
    """Genau diesen Prozess beenden (ohne Kindprozesse anderer Programme)."""
    subprocess.run([_system32("taskkill.exe"), "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _befehlszeile(pid: int) -> str | None:
    """Befehlszeile eines Prozesses (NtQueryInformationProcess, Klasse ProcessCommandLineInformation) oder None."""
    if sys.platform != "win32" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    class _UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG
    griff = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not griff:
        return None
    try:
        laenge = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess(griff, _PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(laenge))
        if not 0 < laenge.value <= 1 << 20:
            return None
        puffer = ctypes.create_string_buffer(laenge.value)
        if ntdll.NtQueryInformationProcess(griff, _PROCESS_COMMAND_LINE_INFORMATION, puffer, laenge, ctypes.byref(laenge)) != 0:
            return None
        text = _UnicodeString.from_buffer(puffer)
        return ctypes.wstring_at(text.Buffer, text.Length // 2) if text.Buffer else ""
    finally:
        kernel32.CloseHandle(griff)


def _ist_automation(befehlszeile: str | None) -> bool:
    """Lief Word über COM (Befehlszeile mit /Automation und -Embedding)? Unbekannt heißt nein."""
    zeile = (befehlszeile or "").lower()
    return "/automation" in zeile and "-embedding" in zeile


def _fehlername(e: BaseException) -> str:
    """Typ des Fehlers, bei COM mit HRESULT (und dem Code von Word) hexadezimal, z. B. "com_error 0x80020009/0x800A1066"."""
    codes = []
    hresult = getattr(e, "hresult", None)
    if isinstance(hresult, int):
        codes.append(f"0x{hresult & 0xFFFFFFFF:08X}")
    innen = getattr(e, "excepinfo", None)
    if isinstance(innen, tuple) and len(innen) > 5 and isinstance(innen[5], int) and innen[5]:
        codes.append(f"0x{innen[5] & 0xFFFFFFFF:08X}")
    return f"{type(e).__name__} {'/'.join(codes)}" if codes else type(e).__name__


def _word_starten():
    import win32com.client

    return win32com.client.DispatchEx("Word.Application")


def _umwandeln(quelle: Path, ziel: Path, word_fabrik: Callable, pids: Callable[[], set[int]], vorher: set[int],
               stand: dict) -> None:
    """Im eigenen Thread: Word starten, Datei lesend öffnen, als PDF ausgeben, schließen, beenden. Gibt am Ende die Sperre frei."""
    com = None
    word = dokument = None
    try:
        if sys.platform == "win32":
            try:
                import pythoncom

                com = pythoncom
                com.CoInitialize()
            except ImportError:
                com = None
        word = word_fabrik()
        stand["eigene"] = pids() - vorher
        word.Visible = False
        word.DisplayAlerts = WD_KEINE_MELDUNGEN
        word.AutomationSecurity = MAKROS_AUS
        dokument = word.Documents.Open(FileName=str(quelle), ConfirmConversions=False, ReadOnly=True,
                                       AddToRecentFiles=False, Visible=False, NoEncodingDialog=True)
        try:
            dokument.ExportAsFixedFormat(OutputFileName=str(ziel), ExportFormat=WD_EXPORT_PDF, OpenAfterExport=False)
        finally:
            dokument.Close(SaveChanges=WD_NICHT_SPEICHERN)
        stand["fertig"] = True
    except Exception as e:  # noqa: BLE001 (COM-Fehler aller Art: nur melden)
        stand["fehler"] = _fehlername(e)
    finally:
        if word is not None:
            try:
                word.Quit(SaveChanges=WD_NICHT_SPEICHERN)
            except Exception as e:  # noqa: BLE001 (Word schon weg oder hängt: der Aufrufer räumt nach der Frist auf)
                _log.debug("Word: Quit nach der PDF fehlgeschlagen (%s)", _fehlername(e))
        dokument = word = None  # Verweise vor CoUninitialize freigeben
        try:
            if com is not None:
                com.CoUninitialize()
        finally:
            _UMWANDLUNG.release()


def _haengende_beenden(stand: dict, vorher: set[int], pids: Callable[[], set[int]], beenden: Callable[[int], None],
                       befehlszeile: Callable[[int], str | None]) -> None:
    """Nach der Frist: nur neue Word-Prozesse mit COM-Befehlszeile beenden. Hing schon der Start, zählen alle seit vorher neuen."""
    eigene = stand["eigene"] if "eigene" in stand else pids() - vorher
    for pid in sorted(eigene):
        try:
            if _ist_automation(befehlszeile(pid)):
                beenden(pid)
        except Exception:  # noqa: BLE001 (Prozess schon weg)
            _log.debug("Word: Prozess %s ließ sich nicht beenden", pid)


def pdf_aus_docx(docx: bytes, *, timeout: float = PDF_TIMEOUT_SECS, word: Callable | None = None,
                 pids: Callable[[], set[int]] | None = None, beenden: Callable[[int], None] | None = None,
                 befehlszeile: Callable[[int], str | None] | None = None) -> bytes:
    """PDF aus einer Word-Datei (Bytes). word, pids, beenden und befehlszeile sind für Tests ersetzbar. Wirft PdfFehler."""
    word, pids, beenden = word or _word_starten, pids or _word_pids, beenden or _beenden
    befehlszeile = befehlszeile or _befehlszeile
    if not _UMWANDLUNG.acquire(timeout=SPERRE_WARTEN_SECS):
        raise PdfFehler("Word erzeugt gerade noch eine andere PDF. Bitte gleich noch einmal versuchen oder als Word speichern.")
    gestartet = False
    try:
        with tempfile.TemporaryDirectory(prefix="wais-pdf-", ignore_cleanup_errors=True) as ordner:
            quelle, ziel = Path(ordner) / "dokument.docx", Path(ordner) / "dokument.pdf"
            quelle.write_bytes(docx)
            stand: dict = {}
            vorher = pids()
            faden = threading.Thread(target=_umwandeln, args=(quelle, ziel, word, pids, vorher, stand), name="wais-pdf",
                                     daemon=True)
            faden.start()
            gestartet = True  # ab hier gibt der Thread die Sperre frei
            faden.join(timeout)
            if faden.is_alive():
                _haengende_beenden(stand, vorher, pids, beenden, befehlszeile)
                raise PdfFehler("Word hat die PDF nicht in der Zeit erzeugt. Bitte als Word speichern und dort als PDF sichern.")
            if not stand.get("fertig"):
                raise PdfFehler(f"Word konnte die PDF nicht erzeugen ({stand.get('fehler', 'unbekannt')}). Ist Word installiert?")
            try:
                daten = ziel.read_bytes()
            except OSError as e:
                raise PdfFehler("Word hat keine PDF geschrieben") from e
    finally:
        if not gestartet:
            _UMWANDLUNG.release()
    if not daten.startswith(b"%PDF-") or len(daten) > PDF_MAX:
        raise PdfFehler("Die PDF von Word ist unbrauchbar")
    return daten
