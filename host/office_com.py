"""Office per COM, nur wo es ohne nicht geht. In Paket 1: PDF über Word aus der selbst gebauten Word-Datei.

* Eigene, unsichtbare Word-Instanz (DispatchEx), nie das offene Word der Person: DisplayAlerts aus, Makros in programmatisch geöffneten
  Dateien aus (AutomationSecurity), Datei nur lesend und nicht in "Zuletzt verwendet", danach Close und Quit ohne Speichern.
* Eigener Thread mit CoInitialize, Zeitgrenze PDF_TIMEOUT_SECS. Hängt Word, beendet der Host genau die Prozesse, die beim Start
  dieser Instanz neu dazukamen (Vergleich der WINWORD.EXE-Kennungen vorher und nachher, Prüfauftrag P0); ist keine neue Kennung
  erkennbar, beendet er nichts.
* Ein- und Ausgabe liegen in einem eigenen Wegwerfordner im Temp-Ordner des Benutzers, nie im Ordner WAIS.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

PDF_TIMEOUT_SECS = 45
PDF_MAX = 20 * 1024 * 1024
WD_EXPORT_PDF = 17
WD_NICHT_SPEICHERN = 0
WD_KEINE_MELDUNGEN = 0
MAKROS_AUS = 3  # msoAutomationSecurityForceDisable
FORMATE_OHNE_WORD = ["word", "excel", "powerpoint", "csv", "markdown"]


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
    formate = list(FORMATE_OHNE_WORD)
    if word:
        formate.insert(3, "pdf")
    return {"formate": formate, "word": word}


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
        p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/FO", "CSV", "/NH"], capture_output=True,
                           timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return set()
    # Meldungen von tasklist kommen in der OEM-Codepage (Umlaute): als Bytes lesen, Kennungen sind reine Ziffern
    return _pids_aus_tasklist((p.stdout or b"").decode("ascii", "replace"))


def _beenden(pid: int) -> None:
    """Genau diesen Prozess beenden (ohne Kindprozesse anderer Programme)."""
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _word_starten():
    import win32com.client

    return win32com.client.DispatchEx("Word.Application")


def _umwandeln(quelle: Path, ziel: Path, word_fabrik: Callable, pids: Callable[[], set[int]], stand: dict) -> None:
    """Im eigenen Thread: Word starten, Datei lesend öffnen, als PDF ausgeben, schließen, beenden."""
    com = None
    if sys.platform == "win32":
        try:
            import pythoncom

            com = pythoncom
            com.CoInitialize()
        except ImportError:
            com = None
    word = dokument = None
    try:
        vorher = pids()
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
        stand["fehler"] = type(e).__name__
    finally:
        if word is not None:
            try:
                word.Quit(SaveChanges=WD_NICHT_SPEICHERN)
            except Exception:  # noqa: BLE001 (Word schon weg)
                pass
        dokument = word = None  # Verweise vor CoUninitialize freigeben
        if com is not None:
            com.CoUninitialize()


def pdf_aus_docx(docx: bytes, *, timeout: float = PDF_TIMEOUT_SECS, word: Callable | None = None,
                 pids: Callable[[], set[int]] | None = None, beenden: Callable[[int], None] | None = None) -> bytes:
    """PDF aus einer Word-Datei (Bytes). word, pids und beenden sind für Tests ersetzbar. Wirft PdfFehler."""
    word, pids, beenden = word or _word_starten, pids or _word_pids, beenden or _beenden
    with tempfile.TemporaryDirectory(prefix="wais-pdf-", ignore_cleanup_errors=True) as ordner:
        quelle, ziel = Path(ordner) / "dokument.docx", Path(ordner) / "dokument.pdf"
        quelle.write_bytes(docx)
        stand: dict = {}
        faden = threading.Thread(target=_umwandeln, args=(quelle, ziel, word, pids, stand), name="wais-pdf", daemon=True)
        faden.start()
        faden.join(timeout)
        if faden.is_alive():
            for pid in sorted(stand.get("eigene", set())):
                try:
                    beenden(pid)
                except Exception:  # noqa: BLE001 (Prozess schon weg)
                    pass
            raise PdfFehler("Word hat die PDF nicht in der Zeit erzeugt. Bitte als Word speichern und dort als PDF sichern.")
        if not stand.get("fertig"):
            raise PdfFehler(f"Word konnte die PDF nicht erzeugen ({stand.get('fehler', 'unbekannt')}). Ist Word installiert?")
        try:
            daten = ziel.read_bytes()
        except OSError as e:
            raise PdfFehler("Word hat keine PDF geschrieben") from e
    if not daten.startswith(b"%PDF-") or len(daten) > PDF_MAX:
        raise PdfFehler("Die PDF von Word ist unbrauchbar")
    return daten
