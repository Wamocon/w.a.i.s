"""Tests für office_dateien.py: echte Dateien aus jeder Canvas-Art, wieder geöffnet mit denselben Bibliotheken.

Geprüft werden Inhalt, Firmendesign (Kopfzeile mit Anschrift und Logo, Fußzeile mit Seitenzahl), Grenzen und die Schutzregeln:
keine Formel in Excel, Präfix gegen Formeln in CSV, keine externen Beziehungen, keine Vorlage, keine Makros.
"""

import csv
import io
import zipfile

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import office_dateien as od

STEUER = chr(7)  # Steuerzeichen bewusst über chr, nie als Escape im Quelltext
DOKUMENT = {
    "art": "dokument",
    "titel": "Angebot Kunde X",
    "text": "# Angebot\nEinleitung mit **fett** und `code`.\n## Leistungen\n- Testplanung\n- Testdurchführung\n### Details\nSchluss" + STEUER,
}
TABELLE = {
    "art": "tabelle",
    "titel": "Projekte & Termine",
    "spalten": ["Projekt", "Formel", "Betrag"],
    "zeilen": [["Alpha", "=1+1", "-5"], ["Beta", "@SUMME(A1)", "+7"], ["Gamma", "harmlos"]],
}
CODE = {"art": "code", "titel": "Abfrage", "text": "select *\n  from projekte;", "sprache": "sql"}
MERMAID = {"art": "mermaid", "titel": "Ablauf", "text": "flowchart LR\n  A --> B"}
ALLE = {"dokument": DOKUMENT, "tabelle": TABELLE, "code": CODE, "mermaid": MERMAID}


def _bauen(roh: dict, fmt: str) -> bytes:
    return od.erzeugen(od.pruefen(roh), fmt)


def _zip_text(daten: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        return "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".rels")))


# ---------- Formate je Art ----------
def test_formate_je_art_wie_im_plan():
    assert od.FORMATE == ("word", "excel", "powerpoint", "pdf", "csv", "markdown")
    assert set(od.FORMATE_JE_ART["tabelle"]) == set(od.FORMATE)
    for art in ("dokument", "code", "mermaid"):
        assert set(od.FORMATE_JE_ART[art]) == {"word", "powerpoint", "pdf", "markdown"}


@pytest.mark.parametrize("art", ["dokument", "code", "mermaid"])
@pytest.mark.parametrize("fmt", ["excel", "csv"])
def test_excel_und_csv_nur_fuer_tabellen(art, fmt):
    with pytest.raises(od.InhaltFehler):
        _bauen(ALLE[art], fmt)


def test_pdf_entsteht_nicht_hier():
    with pytest.raises(od.InhaltFehler):
        _bauen(DOKUMENT, "pdf")


@pytest.mark.parametrize("fmt", ["docx", "", None, "exe", "WORD "])
def test_unbekanntes_format(fmt):
    with pytest.raises(od.InhaltFehler):
        od.format_pruefen(fmt)


# ---------- Word ----------
def test_word_dokument_rundlauf_mit_firmendesign():
    doc = Document(io.BytesIO(_bauen(DOKUMENT, "word")))
    texte = [p.text for p in doc.paragraphs]
    assert "Angebot Kunde X" in texte
    assert "Angebot" in texte and "Leistungen" in texte and "Testplanung" in texte and "Details" in texte
    absatz = next(p for p in doc.paragraphs if p.text.startswith("Einleitung"))
    assert absatz.text == "Einleitung mit fett und code."
    assert any(r.bold for r in absatz.runs if r.text == "fett")
    assert next(p for p in doc.paragraphs if p.text == "Leistungen").style.name == "Heading 2"
    assert next(p for p in doc.paragraphs if p.text == "Testplanung").style.name == "List Bullet"
    assert all(STEUER not in t for t in texte)
    kopf = doc.sections[0].header
    assert od.ANSCHRIFT in kopf.tables[0].cell(0, 0).text
    assert any("image" in r.reltype for r in kopf.part.rels.values()), "Logo fehlt in der Kopfzeile"
    assert "PAGE" in doc.sections[0].footer._element.xml
    assert doc.styles["Normal"].font.name == "Arial Narrow"
    assert doc.core_properties.author == "WAMOCON GmbH"
    assert doc.core_properties.title == "Angebot Kunde X"


def test_word_tabelle_mit_kopfzeile_und_allen_zellen():
    doc = Document(io.BytesIO(_bauen(TABELLE, "word")))
    tabelle = doc.tables[0]
    assert [c.text for c in tabelle.rows[0].cells] == ["Projekt", "Formel", "Betrag"]
    assert [c.text for c in tabelle.rows[1].cells] == ["Alpha", "=1+1", "-5"]
    assert [c.text for c in tabelle.rows[3].cells] == ["Gamma", "harmlos", ""]  # fehlende Zelle bleibt leer
    assert "w:tblHeader" in tabelle._tbl.xml


@pytest.mark.parametrize("art", ["code", "mermaid"])
def test_word_code_in_festbreitenschrift(art):
    doc = Document(io.BytesIO(_bauen(ALLE[art], "word")))
    zeilen = [p for p in doc.paragraphs if p.runs and p.runs[0].font.name == "Consolas"]
    assert [p.text for p in zeilen] == ALLE[art]["text"].split("\n")


# ---------- Excel ----------
def test_excel_rundlauf_zellen_als_text_ohne_formel():
    daten = _bauen(TABELLE, "excel")
    ws = load_workbook(io.BytesIO(daten)).active
    assert [c.value for c in ws[1]] == ["Projekt", "Formel", "Betrag"]
    assert ws["B2"].value == "=1+1" and ws["B2"].data_type == "s"
    assert ws["B3"].value == "@SUMME(A1)" and ws["C2"].value == "-5"
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:C4"
    assert all(c.font.bold for c in ws[1])
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        blatt = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in blatt and "<f " not in blatt


def test_excel_druckkopf_mit_anschrift_und_maskiertem_titel():
    ws = load_workbook(io.BytesIO(_bauen(TABELLE, "excel"))).active
    assert ws.oddHeader.left.text == od.ANSCHRIFT
    assert ws.oddHeader.center.text == "Projekte && Termine"  # & ist im Druckkopf ein Steuerzeichen
    assert "&P" in ws.oddFooter.center.text


# ---------- CSV ----------
def test_csv_mit_bom_semikolon_und_praefix():
    daten = _bauen(TABELLE, "csv")
    assert daten.startswith(b"\xef\xbb\xbf")
    zeilen = list(csv.reader(io.StringIO(daten.decode("utf-8-sig")), delimiter=";"))
    assert zeilen[0] == ["Projekt", "Formel", "Betrag"]
    assert zeilen[1] == ["Alpha", "'=1+1", "'-5"]
    assert zeilen[2] == ["Beta", "'@SUMME(A1)", "'+7"]
    assert zeilen[3] == ["Gamma", "harmlos", ""]


@pytest.mark.parametrize("wert,erwartet", [("=A1", "'=A1"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"),
                                           ("\tx", "'\tx"), ("\rx", "'\rx"), ("a=b", "a=b"), ("", "")])
def test_csv_zelle(wert, erwartet):
    assert od.csv_zelle(wert) == erwartet


# ---------- PowerPoint ----------
def _folien_texte(prs) -> list[str]:
    texte = []
    for folie in prs.slides:
        for form in folie.shapes:
            if form.has_text_frame:
                texte.append(form.text_frame.text)
            if form.has_table:
                texte.extend(c.text for r in form.table.rows for c in r.cells)
    return texte


def test_powerpoint_dokument_folie_je_ueberschrift_mit_logo_und_fusszeile():
    prs = Presentation(io.BytesIO(_bauen(DOKUMENT, "powerpoint")))
    assert len(prs.slides) == 3  # Titel, "Angebot", "Leistungen"
    texte = "\n".join(_folien_texte(prs))
    assert "Angebot Kunde X" in texte and "Testplanung" in texte and "Testdurchführung" in texte
    for folie in prs.slides:
        assert any(f.shape_type == MSO_SHAPE_TYPE.PICTURE for f in folie.shapes), "Logo fehlt"
        assert any(f.has_text_frame and od.ANSCHRIFT in f.text_frame.text for f in folie.shapes)
    assert prs.core_properties.author == "WAMOCON GmbH"


def test_powerpoint_tabelle_hoechstens_12_zeilen_je_folie():
    roh = {"art": "tabelle", "titel": "Viele", "spalten": ["Nr"], "zeilen": [[str(i)] for i in range(30)]}
    prs = Presentation(io.BytesIO(_bauen(roh, "powerpoint")))
    tabellen = [f.table for folie in prs.slides for f in folie.shapes if f.has_table]
    assert len(tabellen) == 3
    assert all(len(t.rows) <= 13 for t in tabellen)  # Kopfzeile plus 12
    assert [t.cell(0, 0).text for t in tabellen] == ["Nr"] * 3
    assert sorted(t.cell(r, 0).text for t in tabellen for r in range(1, len(t.rows))) == sorted(str(i) for i in range(30))


@pytest.mark.parametrize("art", ["code", "mermaid"])
def test_powerpoint_code(art):
    texte = "\n".join(_folien_texte(Presentation(io.BytesIO(_bauen(ALLE[art], "powerpoint")))))
    assert ALLE[art]["text"].split("\n")[0] in texte


# ---------- Markdown ----------
def test_markdown_je_art():
    assert _bauen(DOKUMENT, "markdown").decode() == DOKUMENT["text"].replace(STEUER, "") + "\n"
    tab = _bauen({"art": "tabelle", "titel": "T", "spalten": ["a|b", "c"], "zeilen": [["1\n2", "x"]]}, "markdown").decode()
    assert "| a\\|b | c |" in tab and "| 1 2 | x |" in tab
    code = _bauen({"art": "code", "titel": "C", "text": "a ``` b", "sprache": "py"}, "markdown").decode()
    assert code.startswith("````py\n") and code.rstrip().endswith("````")
    assert _bauen(MERMAID, "markdown").decode().startswith("```mermaid\n")


# ---------- Schutz: keine Vorlage, keine externen Beziehungen, keine Makros ----------
@pytest.mark.parametrize("art,fmt", [("dokument", "word"), ("tabelle", "word"), ("tabelle", "excel"),
                                     ("dokument", "powerpoint"), ("tabelle", "powerpoint")])
def test_keine_externen_verweise_keine_vorlage_keine_makros(art, fmt):
    daten = _bauen(ALLE[art], fmt)
    xml = _zip_text(daten)
    assert 'TargetMode="External"' not in xml
    assert "attachedTemplate" not in xml
    assert "vbaProject" not in xml and "macroEnabled" not in xml
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        assert not any(n.lower().endswith(".bin") for n in z.namelist())


def test_text_mit_links_bleibt_text():
    roh = {"art": "dokument", "titel": "L", "text": "Siehe https://example.com und file:///C:/x"}
    assert 'TargetMode="External"' not in _zip_text(_bauen(roh, "word"))
    assert 'TargetMode="External"' not in _zip_text(_bauen(roh, "powerpoint"))


# ---------- Prüfung der Eingabe ----------
@pytest.mark.parametrize("roh", [
    None, [], "text", {"art": "bild", "titel": "x", "text": "y"}, {"art": "dokument", "titel": "x"},
    {"art": "dokument", "titel": "x", "text": ""}, {"art": "dokument", "titel": 5, "text": "y"},
    {"art": "tabelle", "titel": "x", "spalten": [], "zeilen": [["a"]]},
    {"art": "tabelle", "titel": "x", "spalten": ["a"], "zeilen": "a"},
    {"art": "tabelle", "titel": "x", "spalten": ["a"], "zeilen": [[1]]},
    {"art": "code", "titel": "x", "text": "y", "sprache": "py; rm"},
])
def test_ungueltige_inhalte(roh):
    with pytest.raises(od.InhaltFehler):
        od.pruefen(roh)


def test_grenzen():
    with pytest.raises(od.InhaltFehler):
        od.pruefen({"art": "dokument", "titel": "x", "text": "a" * (od.TEXT_MAX + 1)})
    with pytest.raises(od.InhaltFehler):
        od.pruefen({"art": "tabelle", "titel": "x", "spalten": ["a"], "zeilen": [["1"]] * (od.ZEILEN_MAX + 1)})
    with pytest.raises(od.InhaltFehler):
        od.pruefen({"art": "tabelle", "titel": "x", "spalten": ["a"] * (od.SPALTEN_MAX + 1), "zeilen": [["1"]]})
    with pytest.raises(od.InhaltFehler):
        od.pruefen({"art": "tabelle", "titel": "x", "spalten": ["a"], "zeilen": [["x" * (od.ZELLE_MAX + 1)]]})
    assert od.pruefen({"art": "dokument", "titel": "x", "text": "a" * od.TEXT_MAX}).text
    riesig = {"art": "tabelle", "titel": "x", "spalten": ["a"] * od.SPALTEN_MAX,
              "zeilen": [["x" * od.ZELLE_MAX] * od.SPALTEN_MAX] * 20}  # jede Zelle erlaubt, zusammen zu viel
    with pytest.raises(od.InhaltFehler, match="insgesamt"):
        od.pruefen(riesig)


def test_steuerzeichen_und_titel_werden_bereinigt():
    inhalt = od.pruefen({"art": "dokument", "titel": "  T" + STEUER + "itel\r\n ", "text": "a\r\nb" + chr(0) + "c"})
    assert inhalt.titel == "Titel"
    assert inhalt.text == "a\nbc"
    assert od.pruefen({"art": "dokument", "titel": "   ", "text": "a"}).titel == "Canvas"


def test_grosse_tabelle_in_vertretbarer_zeit():
    import time

    roh = {"art": "tabelle", "titel": "Groß", "spalten": [f"S{i}" for i in range(20)],
           "zeilen": [[f"{r}-{c}" for c in range(20)] for r in range(od.ZEILEN_MAX)]}
    inhalt = od.pruefen(roh)
    for fmt in ("excel", "word", "csv"):
        start = time.perf_counter()
        daten = od.erzeugen(inhalt, fmt)
        assert len(daten) < od.DATEI_MAX
        assert time.perf_counter() - start < 20, fmt
