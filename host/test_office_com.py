"""Tests für office_com.py: PDF über eine eigene, unsichtbare Word-Instanz.

Word ist hier eine Attrappe (Aufrufe werden mitgeschrieben). Der markierte Integrationstest am Ende läuft nur unter Windows mit
installiertem Word und WAMO_OFFICE_ECHT=1: Er erzeugt eine echte Word-Datei in einem Wegwerfordner, wandelt sie mit Word um und
räumt alles wieder ab. Dokumente der Person berührt er nie.
"""

import io
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import office_com as oc


class Dokument:
    def __init__(self, app):
        self.app = app

    def ExportAsFixedFormat(self, OutputFileName, ExportFormat, **kw):  # noqa: N802,N803 (COM-Namen)
        self.app.aufrufe.append(("export", ExportFormat, kw.get("OpenAfterExport")))
        if self.app.warten:
            self.app.warten.wait(5)
        Path(OutputFileName).write_bytes(self.app.pdf)

    def Close(self, SaveChanges):  # noqa: N802,N803
        self.app.aufrufe.append(("close", SaveChanges))


class Dokumente:
    def __init__(self, app):
        self.app = app

    def Open(self, FileName, **kw):  # noqa: N802,N803
        self.app.aufrufe.append(("open", Path(FileName).suffix, kw.get("ReadOnly"), kw.get("AddToRecentFiles"),
                                 kw.get("Visible"), kw.get("ConfirmConversions")))
        return Dokument(self.app)


class WordAttrappe:
    def __init__(self, pdf=b"%PDF-1.7 attrappe", warten=None):
        self.aufrufe: list = []
        self.pdf = pdf
        self.warten = warten
        self.Documents = Dokumente(self)
        self.einstellungen: dict = {}

    def __setattr__(self, name, wert):
        if name[0].isupper() and name != "Documents":
            self.__dict__.setdefault("einstellungen", {})[name] = wert
        object.__setattr__(self, name, wert)

    def Quit(self, SaveChanges=0):  # noqa: N802,N803
        self.aufrufe.append(("quit", SaveChanges))


def _pids(*folge):
    """Liefert nacheinander die Mengen der Word-Prozesse (vorher, nachher)."""
    werte = list(folge)
    return lambda: werte.pop(0) if len(werte) > 1 else werte[0]


AUTOMATION = '"C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE" /Automation -Embedding'
VON_HAND = '"C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE" /n "C:\\Users\\niko\\Angebot.docx"'


def _zeilen(**je_pid):
    """Befehlszeilen je Kennung (p7=... für Kennung 7); unbekannte Kennungen: None."""
    return lambda pid: je_pid.get(f"p{pid}")


@pytest.fixture(autouse=True)
def _keine_haengende_umwandlung():
    """Jede Umwandlung gibt ihre Sperre am Ende ihres Threads frei; vor jedem Test darf keine mehr laufen."""
    assert oc._UMWANDLUNG.acquire(timeout=10), "eine Umwandlung aus einem früheren Test läuft noch"
    oc._UMWANDLUNG.release()
    yield


def test_pdf_in_eigener_unsichtbarer_instanz():
    word = WordAttrappe()
    beendet = []
    pdf = oc.pdf_aus_docx(b"PK docx", word=lambda: word, pids=_pids({1}, {1, 2}), beenden=beendet.append)
    assert pdf == b"%PDF-1.7 attrappe"
    assert word.einstellungen["Visible"] is False
    assert word.einstellungen["DisplayAlerts"] == 0
    assert word.einstellungen["AutomationSecurity"] == 3  # Makros in programmatisch geöffneten Dateien aus
    assert ("open", ".docx", True, False, False, False) in word.aufrufe
    assert ("export", 17, False) in word.aufrufe
    assert ("close", 0) in word.aufrufe and ("quit", 0) in word.aufrufe
    assert beendet == []  # sauber beendet: kein Prozess wird abgeschossen


def test_zeitgrenze_beendet_nur_die_eigene_instanz():
    halt = threading.Event()
    word = WordAttrappe(warten=halt)
    beendet = []
    start = time.monotonic()
    with pytest.raises(oc.PdfFehler, match="Zeit"):
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids({11, 12}, {11, 12, 99}), beenden=beendet.append, timeout=0.3,
                        befehlszeile=_zeilen(p11=VON_HAND, p12=AUTOMATION, p99=AUTOMATION))
    halt.set()
    assert time.monotonic() - start < 3
    assert beendet == [99]  # nie 11 oder 12: das sind Word-Fenster der Person


def test_zeitgrenze_ohne_erkennbare_eigene_instanz_beendet_nichts():
    halt = threading.Event()
    word = WordAttrappe(warten=halt)
    beendet = []
    with pytest.raises(oc.PdfFehler):
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids({5}, {5}), beenden=beendet.append, timeout=0.2,
                        befehlszeile=_zeilen(p5=AUTOMATION))
    halt.set()
    assert beendet == []


def test_neues_word_der_person_wird_nie_beendet():
    """Startet die Person in derselben Sekunde selbst Word, ist auch das eine neue Kennung: beendet wird nur, was mit
    /Automation -Embedding lief (so startet COM Word); ist die Befehlszeile nicht lesbar, nichts."""
    halt = threading.Event()
    word = WordAttrappe(warten=halt)
    beendet = []
    with pytest.raises(oc.PdfFehler, match="Zeit"):
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids({1}, {1, 7, 8, 9}), beenden=beendet.append, timeout=0.2,
                        befehlszeile=_zeilen(p7=VON_HAND, p8=AUTOMATION))
    halt.set()
    assert beendet == [8]


def test_haenger_beim_start_von_word():
    """Hängt schon DispatchEx, gibt es noch kein Word-Objekt: nach der Frist zählen die Kennungen, die seit dem Start dazukamen."""
    halt = threading.Event()

    def haengt():
        halt.wait(5)
        raise OSError("Start abgebrochen")

    beendet = []
    start = time.monotonic()
    with pytest.raises(oc.PdfFehler, match="Zeit"):
        oc.pdf_aus_docx(b"PK", word=haengt, pids=_pids({1}, {1, 7, 8}), beenden=beendet.append, timeout=0.3,
                        befehlszeile=_zeilen(p1=AUTOMATION, p7=AUTOMATION, p8=VON_HAND))
    halt.set()
    assert time.monotonic() - start < 3
    assert beendet == [7]


def test_nur_eine_umwandlung_gleichzeitig(monkeypatch):
    monkeypatch.setattr(oc, "SPERRE_WARTEN_SECS", 0.1)
    halt = threading.Event()
    erste_laeuft = threading.Event()

    def langsam():
        erste_laeuft.set()
        return WordAttrappe(warten=halt)

    ergebnis: list = []
    faden = threading.Thread(target=lambda: ergebnis.append(
        oc.pdf_aus_docx(b"PK", word=langsam, pids=_pids(set()), beenden=lambda p: None, timeout=5)))
    faden.start()
    assert erste_laeuft.wait(5)
    with pytest.raises(oc.PdfFehler, match="gerade"):
        oc.pdf_aus_docx(b"PK", word=WordAttrappe, pids=_pids(set()), beenden=lambda p: None, timeout=5)
    halt.set()
    faden.join(10)
    assert ergebnis == [b"%PDF-1.7 attrappe"]
    assert oc.pdf_aus_docx(b"PK", word=WordAttrappe, pids=_pids(set()), beenden=lambda p: None) == b"%PDF-1.7 attrappe"


class ComFehler(Exception):
    """Wie pywintypes.com_error: hresult und excepinfo als Felder."""

    def __init__(self, hresult, excepinfo=None):
        super().__init__(hresult, "Ausnahmefehler", excepinfo, None)
        self.hresult, self.excepinfo = hresult, excepinfo


def test_hresult_hexadezimal_in_der_meldung():
    def kaputt():
        raise ComFehler(-2147221005)  # 0x800401F3: ungültige Klassenzeichenfolge

    with pytest.raises(oc.PdfFehler, match="0x800401F3"):
        oc.pdf_aus_docx(b"PK", word=kaputt, pids=_pids(set()), beenden=lambda p: None)
    innen = (0, "Microsoft Word", "Befehl misslungen", None, 0, -2146824090)

    class OeffnenKaputt(Dokumente):
        def Open(self, FileName, **kw):  # noqa: N802,N803
            raise ComFehler(-2147352567, innen)  # 0x80020009 mit dem Fehler von Word 0x800A1066

    word = WordAttrappe()
    word.Documents = OeffnenKaputt(word)
    with pytest.raises(oc.PdfFehler, match="0x80020009/0x800A1066"):
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids(set()), beenden=lambda p: None)


def test_quit_fehler_wird_protokolliert(caplog):
    class QuitKaputt(WordAttrappe):
        def Quit(self, SaveChanges=0):  # noqa: N802,N803
            raise ComFehler(-2147023174)  # RPC-Server nicht verfügbar

    caplog.set_level(logging.DEBUG, logger="office_com")
    assert oc.pdf_aus_docx(b"PK", word=QuitKaputt, pids=_pids(set()), beenden=lambda p: None).startswith(b"%PDF-")
    assert any("Quit" in r.getMessage() and "0x800706BA" in r.getMessage() for r in caplog.records)


def test_tasklist_und_taskkill_mit_vollem_pfad(monkeypatch):
    aufrufe = []

    def run(argv, **kw):
        aufrufe.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(oc.subprocess, "run", run)
    oc._word_pids()
    oc._beenden(4711)
    assert [Path(a[0]).name.lower() for a in aufrufe] == ["tasklist.exe", "taskkill.exe"]
    for argv in aufrufe:
        assert Path(argv[0]).is_absolute() and Path(argv[0]).parent.name.lower() == "system32"


@pytest.mark.parametrize("zeile,erwartet", [(AUTOMATION, True), (VON_HAND, False), (None, False), ("", False),
                                            ('"WINWORD.EXE" -Embedding', False), ('"winword.exe" /automation -embedding', True)])
def test_automation_erkannt(zeile, erwartet):
    assert oc._ist_automation(zeile) is erwartet


@pytest.mark.skipif(sys.platform != "win32", reason="Befehlszeile anderer Prozesse nur unter Windows")
def test_befehlszeile_des_eigenen_prozesses():
    zeile = oc._befehlszeile(os.getpid())
    assert zeile and "python" in zeile.lower()
    assert oc._befehlszeile(0) is None  # Leerlaufprozess: nicht lesbar, also nie beendet


def test_keine_pdf_ausgabe_ist_ein_fehler():
    with pytest.raises(oc.PdfFehler):
        oc.pdf_aus_docx(b"PK", word=lambda: WordAttrappe(pdf=b"kein pdf"), pids=_pids(set()), beenden=lambda p: None)


def test_word_fehlt_ist_ein_fehler():
    def kaputt():
        raise OSError("Klasse nicht registriert")

    with pytest.raises(oc.PdfFehler):
        oc.pdf_aus_docx(b"PK", word=kaputt, pids=_pids(set()), beenden=lambda p: None)


def test_faehigkeiten_pdf_nur_mit_word(monkeypatch):
    monkeypatch.setattr(oc, "word_vorhanden", lambda: False)
    assert "pdf" not in oc.faehigkeiten()["formate"]
    monkeypatch.setattr(oc, "word_vorhanden", lambda: True)
    f = oc.faehigkeiten()
    assert f["formate"] == ["word", "excel", "powerpoint", "pdf", "csv", "markdown"]
    assert f["word"] is True


def test_word_pids_liest_nur_winword():
    text = '"WINWORD.EXE","4711","Console","1","100 K"\r\n"winword.exe","815","Console","1","1 K"\r\n'
    assert oc._pids_aus_tasklist(text) == {4711, 815}
    assert oc._pids_aus_tasklist("INFO: Keine Tasks") == set()


# ---------- Integrationstest am Gerät ----------
@pytest.mark.office
@pytest.mark.skipif(sys.platform != "win32" or os.getenv("WAMO_OFFICE_ECHT") != "1",
                    reason="nur am Windows-PC mit Word und WAMO_OFFICE_ECHT=1")
def test_echtes_word_wandelt_in_pdf():
    import office_dateien as od

    if not oc.word_vorhanden():
        pytest.skip("Word ist nicht installiert")
    inhalt = od.pruefen({"art": "dokument", "titel": "Prüfung", "text": "# Prüfung\n- eins\n- zwei mit **fett**"})
    start = time.monotonic()
    pdf = oc.pdf_aus_docx(od.erzeugen(inhalt, "word"))
    dauer = time.monotonic() - start
    assert pdf.startswith(b"%PDF-")
    assert dauer < oc.PDF_TIMEOUT_SECS
    print(f"PDF über Word: {dauer:.1f} s, {len(pdf)} Bytes")
    assert io.BytesIO(pdf).getbuffer().nbytes > 1000
