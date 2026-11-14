"""Tests für office_com.py: PDF über eine eigene, unsichtbare Word-Instanz.

Word ist hier eine Attrappe (Aufrufe werden mitgeschrieben). Der markierte Integrationstest am Ende läuft nur unter Windows mit
installiertem Word und WAMO_OFFICE_ECHT=1: Er erzeugt eine echte Word-Datei in einem Wegwerfordner, wandelt sie mit Word um und
räumt alles wieder ab. Dokumente der Person berührt er nie.
"""

import io
import os
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
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids({11, 12}, {11, 12, 99}), beenden=beendet.append, timeout=0.3)
    halt.set()
    assert time.monotonic() - start < 3
    assert beendet == [99]  # nie 11 oder 12: das sind Word-Fenster der Person


def test_zeitgrenze_ohne_erkennbare_eigene_instanz_beendet_nichts():
    halt = threading.Event()
    word = WordAttrappe(warten=halt)
    beendet = []
    with pytest.raises(oc.PdfFehler):
        oc.pdf_aus_docx(b"PK", word=lambda: word, pids=_pids({5}, {5}), beenden=beendet.append, timeout=0.2)
    halt.set()
    assert beendet == []


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
