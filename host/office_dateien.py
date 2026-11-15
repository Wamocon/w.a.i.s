"""Office-Dateien aus Canvas-Inhalten: Word, Excel, PowerPoint, CSV und Markdown, gebaut im Host ohne Office.

Der Kern schickt nie Dateibytes, nur die feste Struktur eines Canvas-Elements:
  {"art": "dokument" | "code" | "mermaid", "titel", "text", "sprache"?}  oder  {"art": "tabelle", "titel", "spalten", "zeilen"}
pruefen() prüft Typen, Längen und Zeichen selbst (der Host vertraut dem Kern nicht blind), erzeugen() baut die Datei.

Schutzregeln (Planpapier docs/office-und-versand.md, Abschnitt 8):
  * Nur selbst gebaute, makrofreie Formate (.docx, .xlsx, .pptx), keine Vorlage aus dem Profil des PCs, keine externen Beziehungen:
    Links im Text bleiben Text.
  * Excel: jede Zelle ist Text (Typ s, Zahlenformat @, Präfix-Markierung), nie eine Formel. CSV: Zellen, die mit = + - @ Tab oder
    Wagenrücklauf beginnen, bekommen ein Hochkomma davor.
  * Grenzen: Text TEXT_MAX Zeichen, Tabelle ZEILEN_MAX Zeilen und SPALTEN_MAX Spalten, Zelle ZELLE_MAX Zeichen, Datei DATEI_MAX.
    Laufzeit (python-docx wird mit jedem Absatz langsamer): Word und PDF höchstens ABSAETZE_MAX Absätze, Tabellen je Format höchstens
    ZELLEN_MAX Zellen, PowerPoint höchstens PPTX_SPALTEN_MAX Spalten; so bleibt jeder Bau unter etwa 20 s (gemessen in den Tests).
  * Firmendesign im Code: Kopfzeile mit Anschrift und Logo (vorlagen/wmc-logo.png), Fußzeile mit Seitenzahl, Arial Narrow, Rot
    #F40E0E, Schwarz und Grautöne.
PDF entsteht nicht hier, sondern über Word aus der Word-Datei (office_com.py).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

FORMATE = ("word", "excel", "powerpoint", "pdf", "csv", "markdown")
ARTEN = ("dokument", "tabelle", "code", "mermaid")
_TEXTFORMATE = ("word", "powerpoint", "pdf", "markdown")
FORMATE_JE_ART = {"dokument": _TEXTFORMATE, "code": _TEXTFORMATE, "mermaid": _TEXTFORMATE, "tabelle": FORMATE}
TEXT_MAX = 100_000
ZEILEN_MAX = 2000
SPALTEN_MAX = 50
ZELLE_MAX = 2000
TABELLE_ZEICHEN_MAX = 1_000_000
TITEL_EINGABE_MAX = 300
TITEL_MAX = 200
DATEI_MAX = 20 * 1024 * 1024
FOLIEN_MAX = 300
# Laufzeit: Word mit 5000 Aufzählungspunkten rund 3 s, mit 25 000 rund 50 s (wächst quadratisch); Tabellen an der Grenze 2 bis 4 s
ABSAETZE_MAX = 5000
ZELLEN_MAX = {"word": 50_000, "pdf": 50_000, "powerpoint": 12_000}
PPTX_SPALTEN_MAX = 12
KOPF_TITEL_MAX = 150  # Druckkopf in Excel: alle Teile zusammen höchstens 255 Zeichen
SPRACHE_MAX = 20
ANSCHRIFT = "WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn"
FIRMA = "WAMOCON GmbH"
LOGO = Path(__file__).resolve().parent / "vorlagen" / "wmc-logo.png"
SCHRIFT = "Arial Narrow"
CODESCHRIFT = "Consolas"
ROT, SCHWARZ, GRAU_HELL, GRAU_MITTEL, GRAU_DUNKEL = "F40E0E", "000000", "F3F3F3", "D9D9D9", "6B6B6B"


def _klasse(*bereiche: tuple[int, int]) -> str:
    """Zeichenklasse aus Codepunkt-Bereichen (ohne Escape-Folgen im Quelltext)."""
    return "[" + "".join(re.escape(chr(a)) + "-" + re.escape(chr(b)) for a, b in bereiche) + "]"


# In XML nicht erlaubt (und in Office-Dateien kaputt): Steuerzeichen außer Tab und Zeilenumbruch, einzelne Ersatzzeichen
_XML_UNGUELTIG = re.compile(_klasse((0, 8), (11, 12), (14, 31), (0xD800, 0xDFFF), (0xFFFE, 0xFFFF)))
# Im Titel zusätzlich: Richtungs-, Nullbreiten- und weitere unsichtbare Zeichen (weiches Trennzeichen, Wortverbinder, arabisches
# Richtungszeichen, mongolischer Vokaltrenner), einzelne Ersatzzeichen, Tab und Zeilenumbruch
_TITEL_WEG = re.compile(_klasse((0, 31), (127, 159), (0xAD, 0xAD), (0x061C, 0x061C), (0x180E, 0x180E), (0x200B, 0x200F),
                                (0x202A, 0x202E), (0x2060, 0x2069), (0xD800, 0xDFFF), (0xFEFF, 0xFEFF)))
_SPRACHE_WEG = re.compile(r"[^a-z0-9+#._-]")
_UEBERSCHRIFT = re.compile(r"^(#{1,3})\s+(.*)$")
_PUNKT = re.compile(r"^\s*[-*]\s+(.*)$")
_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
CSV_GEFAEHRLICH = ("=", "+", "-", "@", "\t", "\r")


class InhaltFehler(ValueError):
    """Inhalt oder Format passt nicht (Text ist für Menschen gedacht und geht an das Sprachmodell)."""


@dataclass(frozen=True)
class Inhalt:
    art: str
    titel: str
    text: str = ""
    sprache: str = ""
    spalten: tuple[str, ...] = ()
    zeilen: tuple[tuple[str, ...], ...] = ()


# ---------- Prüfung ----------
def _text(wert: object, grenze: int, feld: str) -> str:
    if not isinstance(wert, str):
        raise InhaltFehler(f"{feld} muss Text sein")
    text = _XML_UNGUELTIG.sub("", wert.replace("\r\n", "\n").replace("\r", "\n"))
    if len(text) > grenze:
        raise InhaltFehler(f"{feld} ist zu lang (höchstens {grenze} Zeichen)")
    return text


def _titel(wert: object) -> str:
    if not isinstance(wert, str):
        raise InhaltFehler("titel muss Text sein")
    titel = " ".join(_TITEL_WEG.sub("", wert[:TITEL_EINGABE_MAX]).split())[:TITEL_MAX]
    return titel or "Canvas"


def pruefen(roh: object) -> Inhalt:
    """Prüft die Struktur eines Canvas-Elements und gibt sie bereinigt zurück. Wirft InhaltFehler."""
    if not isinstance(roh, dict):
        raise InhaltFehler("Inhalt fehlt")
    art = roh.get("art")
    if art not in ARTEN:
        raise InhaltFehler("Unbekannte Art des Inhalts")
    titel = _titel(roh.get("titel", ""))
    if art == "tabelle":
        spalten, zeilen = roh.get("spalten"), roh.get("zeilen")
        if not isinstance(spalten, list) or not spalten or not isinstance(zeilen, list):
            raise InhaltFehler("Eine Tabelle braucht spalten und zeilen")
        if len(spalten) > SPALTEN_MAX or len(zeilen) > ZEILEN_MAX:
            raise InhaltFehler(f"Tabelle zu groß (höchstens {ZEILEN_MAX} Zeilen und {SPALTEN_MAX} Spalten)")
        kopf = tuple(_text(s, ZELLE_MAX, "Spalte") for s in spalten)
        koerper = []
        zeichen = sum(len(s) for s in kopf)
        for nr, zeile in enumerate(zeilen, start=1):
            if not isinstance(zeile, list) or len(zeile) > SPALTEN_MAX:
                raise InhaltFehler("Jede Zeile ist eine Liste von Texten")
            if len(zeile) > len(kopf):  # nicht still kürzen: Werte gingen verloren
                raise InhaltFehler(f"Zeile {nr} hat mehr Werte ({len(zeile)}) als die Tabelle Spalten ({len(kopf)}). Bitte die "
                                   "Tabelle im Canvas korrigieren.")
            werte = [_text(z, ZELLE_MAX, "Zelle") for z in zeile]
            zeichen += sum(len(w) for w in werte)
            if zeichen > TABELLE_ZEICHEN_MAX:  # 2000 Zeilen mal 50 Spalten mal 2000 Zeichen wären 200 Millionen Zeichen
                raise InhaltFehler(f"Tabelle zu groß (höchstens {TABELLE_ZEICHEN_MAX} Zeichen insgesamt)")
            koerper.append(tuple(werte + [""] * (len(kopf) - len(werte))))
        return Inhalt(art, titel, spalten=kopf, zeilen=tuple(koerper))
    text = _text(roh.get("text"), TEXT_MAX, "text")
    if not text.strip():
        raise InhaltFehler("Der Inhalt ist leer")
    return Inhalt(art, titel, text=text, sprache=_sprache(roh.get("sprache")) if art == "code" else "")


def _sprache(wert: object) -> str:
    """Sprache des Codes (vom Modell): nicht ablehnen, sondern auf erlaubte Zeichen kürzen. Ohne Backtick und Zeilenumbruch bleibt
    der Zaun in Markdown dicht."""
    return _SPRACHE_WEG.sub("", wert.strip().lower())[:SPRACHE_MAX] if isinstance(wert, str) else ""


def format_pruefen(fmt: object) -> str:
    if not isinstance(fmt, str) or fmt not in FORMATE:
        raise InhaltFehler("Unbekanntes Format (word, excel, powerpoint, pdf, csv, markdown)")
    return fmt


def passt(inhalt: Inhalt, fmt: str) -> None:
    """Passt der Inhalt zum Format, auch in der Größe (Laufzeit des Baus)? Wirft InhaltFehler mit einem Hinweis auf ein besseres
    Format."""
    if fmt not in FORMATE_JE_ART[inhalt.art]:
        raise InhaltFehler(f"Als {fmt} geht nur eine Tabelle" if fmt in ("excel", "csv") else f"{fmt} passt nicht zu {inhalt.art}")
    if inhalt.art == "tabelle":
        if fmt == "powerpoint" and len(inhalt.spalten) > PPTX_SPALTEN_MAX:
            raise InhaltFehler(f"Für PowerPoint hat die Tabelle zu viele Spalten (höchstens {PPTX_SPALTEN_MAX}). Bitte als Excel "
                               "speichern.")
        if fmt in ZELLEN_MAX and len(inhalt.zeilen) * len(inhalt.spalten) > ZELLEN_MAX[fmt]:
            raise InhaltFehler(f"Die Tabelle ist für {fmt} zu groß (höchstens {ZELLEN_MAX[fmt]} Zellen). Bitte als Excel speichern.")
    elif fmt in ("word", "pdf") and _absaetze(inhalt) > ABSAETZE_MAX:
        raise InhaltFehler(f"Der Text hat für {fmt} zu viele Absätze (höchstens {ABSAETZE_MAX}). Bitte als Markdown speichern.")


def _absaetze(inhalt: Inhalt) -> int:
    """Absätze, die Word anlegt: ein Block je Zeile im Dokument, eine Zeile je Codezeile."""
    return len(bloecke(inhalt.text)) if inhalt.art == "dokument" else inhalt.text.count("\n") + 1


def erzeugen(inhalt: Inhalt, fmt: str) -> bytes:
    """Baut die Datei im Speicher. PDF entsteht über Word (office_com.pdf_aus_docx aus erzeugen(..., "word"))."""
    fmt = format_pruefen(fmt)
    passt(inhalt, fmt)
    if fmt == "pdf":
        raise InhaltFehler("PDF entsteht über Word aus der Word-Datei")
    daten = {"word": _word, "excel": _excel, "powerpoint": _powerpoint, "csv": _csv, "markdown": _markdown}[fmt](inhalt)
    if len(daten) > DATEI_MAX:
        raise InhaltFehler("Die Datei wäre größer als 20 MB")
    return daten


def _logo() -> str:
    if not LOGO.is_file():
        raise InhaltFehler("Das Firmenlogo fehlt im Host (vorlagen/wmc-logo.png)")
    return str(LOGO)


def _stand() -> str:
    return f"Stand: {date.today():%d.%m.%Y}"


def _jetzt() -> datetime:
    """Erstellt und geändert in Word und PowerPoint: jetzt in UTC ohne Zeitzone (sonst stünde das Datum der Bibliotheksvorlage
    darin)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# ---------- Markdown des Canvas ----------
def bloecke(text: str) -> list[tuple[str, int, str]]:
    """Blöcke wie die Oberfläche (Canvas.tsx): ("ueberschrift", 1..3, text), ("punkt", 0, text), ("absatz", 0, text)."""
    aus: list[tuple[str, int, str]] = []
    for roh in text.split("\n"):
        zeile = roh.rstrip()
        if m := _PUNKT.match(zeile):
            aus.append(("punkt", 0, m.group(1)))
        elif m := _UEBERSCHRIFT.match(zeile):
            aus.append(("ueberschrift", len(m.group(1)), m.group(2)))
        elif zeile.strip():
            aus.append(("absatz", 0, zeile.strip()))
    return aus


def teile(zeile: str) -> list[tuple[str, str]]:
    """Inline-Teile: ("text" | "fett" | "code", inhalt)."""
    aus = []
    for teil in _INLINE.split(zeile):
        if not teil:
            continue
        if teil.startswith("**") and teil.endswith("**") and len(teil) > 4:
            aus.append(("fett", teil[2:-2]))
        elif teil.startswith("`") and teil.endswith("`") and len(teil) > 2:
            aus.append(("code", teil[1:-1]))
        else:
            aus.append(("text", teil))
    return aus


def klartext(zeile: str) -> str:
    return "".join(t for _, t in teile(zeile))


# ---------- Word ----------
def _word_schrift(element, name: str) -> None:
    """Schrift fest setzen, Themenschriften der Vorlage entfernen (sonst gewinnt die Themenschrift)."""
    from docx.oxml.ns import qn

    rpr = element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        fonts.attrib.pop(qn(attr), None)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attr), name)


def _word_stile(doc) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = SCHRIFT, Pt(11)
    _word_schrift(normal.element, SCHRIFT)
    for name, groesse, farbe in (("Title", 26, SCHWARZ), ("Heading 1", 18, ROT), ("Heading 2", 14, SCHWARZ),
                                 ("Heading 3", 12, GRAU_DUNKEL)):
        stil = doc.styles[name]
        stil.font.name, stil.font.size, stil.font.bold = SCHRIFT, Pt(groesse), name != "Title"
        stil.font.color.rgb = RGBColor.from_string(farbe)
        _word_schrift(stil.element, SCHRIFT)
    titel_ppr = doc.styles["Title"].element.get_or_add_pPr()
    for rand in titel_ppr.findall(qn("w:pBdr")):  # blaue Linie der Vorlage durch eine rote ersetzen
        titel_ppr.remove(rand)
    from docx.oxml import OxmlElement

    rand = OxmlElement("w:pBdr")
    unten = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "12"), ("w:space", "4"), ("w:color", ROT)):
        unten.set(qn(k), v)
    rand.append(unten)
    titel_ppr.append(rand)


def _word_schattierung(element_pr, farbe: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), farbe)
    element_pr.append(shd)


def _word_feld(absatz, anweisung: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    feld = OxmlElement("w:fldSimple")
    feld.set(qn("w:instr"), anweisung)
    lauf = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")  # wie der Text der Fußzeile: 8 pt, grau
    farbe, groesse = OxmlElement("w:color"), OxmlElement("w:sz")
    farbe.set(qn("w:val"), GRAU_DUNKEL)
    groesse.set(qn("w:val"), "16")
    rpr.append(farbe)
    rpr.append(groesse)
    lauf.append(rpr)
    text = OxmlElement("w:t")
    text.text = "1"
    lauf.append(text)
    feld.append(lauf)
    absatz._p.append(feld)


def _word_kopf_fuss(abschnitt) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    kopf = abschnitt.header
    kopf.is_linked_to_previous = False
    breite = abschnitt.page_width - abschnitt.left_margin - abschnitt.right_margin
    tabelle = kopf.add_table(1, 2, breite)
    links, rechts = tabelle.cell(0, 0), tabelle.cell(0, 1)
    links.width, rechts.width = int(breite * 0.65), int(breite * 0.35)
    lauf = links.paragraphs[0].add_run(ANSCHRIFT)
    lauf.font.size, lauf.font.color.rgb = Pt(8), RGBColor.from_string(GRAU_DUNKEL)
    rechts.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rechts.paragraphs[0].add_run().add_picture(_logo(), width=Cm(3.2))
    if kopf.paragraphs and not kopf.paragraphs[0].text:
        kopf.paragraphs[0].paragraph_format.space_after = Pt(0)
    fuss = abschnitt.footer
    fuss.is_linked_to_previous = False
    absatz = fuss.paragraphs[0]
    absatz.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for teil in ("Seite ", "PAGE", " von ", "NUMPAGES"):
        if teil in ("PAGE", "NUMPAGES"):
            _word_feld(absatz, teil)
        else:
            lauf = absatz.add_run(teil)
            lauf.font.size, lauf.font.color.rgb = Pt(8), RGBColor.from_string(GRAU_DUNKEL)


def _word_laeufe(absatz, zeile: str) -> None:
    from docx.shared import Pt

    for art, text in teile(zeile):
        lauf = absatz.add_run(text)
        if art == "fett":
            lauf.bold = True
        elif art == "code":
            lauf.font.name, lauf.font.size = CODESCHRIFT, Pt(10)


def _word_tabelle(doc, inhalt: Inhalt) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    from docx.table import _Cell

    tabelle = doc.add_table(rows=len(inhalt.zeilen) + 1, cols=len(inhalt.spalten))
    tabelle.style = doc.styles["Table Grid"]
    groesse = Pt(9 if len(inhalt.spalten) > 6 else 10)
    # Zellen direkt über das XML: Table.rows[i].cells rechnet je Zugriff die ganze Tabelle durch (bei 2000 Zeilen zu langsam)
    for nr, (tr, werte) in enumerate(zip(tabelle._tbl.tr_lst, (inhalt.spalten, *inhalt.zeilen))):
        for tc, wert in zip(tr.tc_lst, werte):
            zelle = _Cell(tc, tabelle)
            lauf = zelle.paragraphs[0].add_run(wert)
            lauf.font.size = groesse
            if nr == 0:
                lauf.bold = True
                _word_schattierung(tc.get_or_add_tcPr(), GRAU_HELL)
        if nr == 0:
            kopf = OxmlElement("w:tblHeader")
            kopf.set(qn("w:val"), "true")
            tr.get_or_add_trPr().append(kopf)


def _word_code(doc, inhalt: Inhalt) -> None:
    from docx.shared import Pt, RGBColor

    if inhalt.art == "mermaid":
        hinweis = doc.add_paragraph().add_run("Diagramm als Mermaid-Quelltext")
        hinweis.italic, hinweis.font.color.rgb = True, RGBColor.from_string(GRAU_DUNKEL)
    for zeile in inhalt.text.split("\n"):
        absatz = doc.add_paragraph()
        absatz.paragraph_format.space_after = Pt(0)
        absatz.paragraph_format.space_before = Pt(0)
        _word_schattierung(absatz._p.get_or_add_pPr(), GRAU_HELL)
        lauf = absatz.add_run(zeile)
        lauf.font.name, lauf.font.size = CODESCHRIFT, Pt(9)


def _word(inhalt: Inhalt) -> bytes:
    from docx import Document
    from docx.shared import Cm, Mm, Pt, RGBColor

    doc = Document()
    _word_stile(doc)
    abschnitt = doc.sections[0]
    abschnitt.page_width, abschnitt.page_height = Mm(210), Mm(297)
    abschnitt.left_margin = abschnitt.right_margin = Cm(2.2)
    abschnitt.top_margin, abschnitt.bottom_margin = Cm(3.0), Cm(2.2)
    _word_kopf_fuss(abschnitt)
    doc.add_heading(inhalt.titel, level=0)
    stand = doc.add_paragraph().add_run(_stand())
    stand.font.size, stand.font.color.rgb = Pt(9), RGBColor.from_string(GRAU_DUNKEL)
    if inhalt.art == "dokument":
        for art, stufe, zeile in bloecke(inhalt.text):
            if art == "ueberschrift":
                doc.add_heading(klartext(zeile), level=stufe)
            else:
                _word_laeufe(doc.add_paragraph(style="List Bullet" if art == "punkt" else None), zeile)
    elif inhalt.art == "tabelle":
        _word_tabelle(doc, inhalt)
    else:
        _word_code(doc, inhalt)
    eig = doc.core_properties
    eig.author = eig.last_modified_by = FIRMA
    eig.title, eig.comments, eig.keywords, eig.subject = inhalt.titel, "", "", ""
    eig.created = eig.modified = _jetzt()
    puffer = io.BytesIO()
    doc.save(puffer)
    return puffer.getvalue()


# ---------- Excel ----------
def _excel_kopftext(text: str, grenze: int = KOPF_TITEL_MAX) -> str:
    """& steuert Druckkopf und Fußzeile (&P, &D): im Text verdoppeln. Höchstens grenze Zeichen (der ganze Druckkopf darf nur 255
    haben), gekürzt nie mitten in einem verdoppelten &."""
    aus, laenge = [], 0
    for zeichen in text:
        stueck = "&&" if zeichen == "&" else zeichen
        if laenge + len(stueck) > grenze - 1:  # Platz für die Auslassungspunkte
            return "".join(aus).rstrip() + "…"
        aus.append(stueck)
        laenge += len(stueck)
    return "".join(aus)


def _blattname(titel: str) -> str:
    name = re.sub(r"[\[\]:*?/\\']", " ", titel).strip()[:31].strip()
    return name or "Tabelle"


def _excel(inhalt: Inhalt) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.properties import PageSetupProperties

    mappe = Workbook()
    blatt = mappe.active
    blatt.title = _blattname(inhalt.titel)
    kopf_font, font = Font(name=SCHRIFT, bold=True, size=11), Font(name=SCHRIFT, size=11)
    kopf_fill = PatternFill("solid", fgColor=GRAU_HELL)
    kopf_rand = Border(bottom=Side(style="medium", color=ROT))
    umbruch = Alignment(vertical="top", wrap_text=True)
    for nr, werte in enumerate((inhalt.spalten, *inhalt.zeilen), start=1):
        for spalte, wert in enumerate(werte, start=1):
            zelle = blatt.cell(row=nr, column=spalte)
            zelle.value = wert
            zelle.data_type = "s"  # immer Text: openpyxl machte aus "=..." sonst eine Formel
            zelle.number_format = "@"
            zelle.quotePrefix = True
            zelle.font = kopf_font if nr == 1 else font
            zelle.alignment = umbruch
            if nr == 1:
                zelle.fill, zelle.border = kopf_fill, kopf_rand
    letzte = get_column_letter(len(inhalt.spalten))
    blatt.auto_filter.ref = f"A1:{letzte}{len(inhalt.zeilen) + 1}"
    blatt.freeze_panes = "A2"
    for spalte in range(1, len(inhalt.spalten) + 1):
        laenge = max((len(z[spalte - 1]) for z in (inhalt.spalten, *inhalt.zeilen[:200])), default=8)
        blatt.column_dimensions[get_column_letter(spalte)].width = min(60, max(10, laenge * 1.1 + 2))
    blatt.oddHeader.left.text, blatt.oddHeader.left.size = ANSCHRIFT, 8
    blatt.oddHeader.center.text = _excel_kopftext(inhalt.titel)
    blatt.oddFooter.center.text = "Seite &P von &N"
    blatt.print_title_rows = "1:1"
    blatt.page_setup.orientation = "landscape" if len(inhalt.spalten) > 6 else "portrait"
    blatt.page_setup.fitToWidth, blatt.page_setup.fitToHeight = 1, 0
    blatt.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    mappe.properties.creator = mappe.properties.lastModifiedBy = FIRMA
    mappe.properties.title = inhalt.titel
    puffer = io.BytesIO()
    mappe.save(puffer)
    return puffer.getvalue()


# ---------- CSV ----------
def csv_zelle(wert: str) -> str:
    """Zellen, die eine Tabellenkalkulation als Formel lesen könnte, bekommen ein Hochkomma davor."""
    return "'" + wert if wert.startswith(CSV_GEFAEHRLICH) else wert


def _csv(inhalt: Inhalt) -> bytes:
    puffer = io.StringIO(newline="")
    schreiber = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for werte in (inhalt.spalten, *inhalt.zeilen):
        schreiber.writerow([csv_zelle(w) for w in werte])
    return puffer.getvalue().encode("utf-8-sig")


# ---------- Markdown ----------
def _zaun(text: str) -> str:
    laengste = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, laengste + 1)


def _md_zelle(wert: str) -> str:
    return " ".join(wert.replace("\\", "\\\\").replace("|", "\\|").split())


def _markdown(inhalt: Inhalt) -> bytes:
    if inhalt.art == "dokument":
        text = inhalt.text
    elif inhalt.art == "tabelle":
        zeilen = [f"# {inhalt.titel}", "", "| " + " | ".join(_md_zelle(s) for s in inhalt.spalten) + " |",
                  "|" + "---|" * len(inhalt.spalten)]
        zeilen += ["| " + " | ".join(_md_zelle(w) for w in z) + " |" for z in inhalt.zeilen]
        text = "\n".join(zeilen)
    else:
        zaun = _zaun(inhalt.text)
        sprache = "mermaid" if inhalt.art == "mermaid" else inhalt.sprache
        text = f"{zaun}{sprache}\n{inhalt.text}\n{zaun}"
    return (text.rstrip("\n") + "\n").encode("utf-8")


# ---------- PowerPoint ----------
PUNKTE_JE_FOLIE = 8
ZEICHEN_JE_FOLIE = 900
TABELLENZEILEN_JE_FOLIE = 12
CODEZEILEN_JE_FOLIE = 18


class _Folien:
    """Foliensatz 16:9 im Firmendesign: roter Balken, Titel, Logo oben rechts, Fußzeile mit Anschrift und Foliennummer."""

    def __init__(self, titel: str):
        from pptx import Presentation
        from pptx.util import Emu

        self.prs = Presentation()
        # Die Standardvorlage bringt Druckereinstellungen als Binärteil mit: weglassen, die Datei enthält dann nur XML und das Logo
        for kennung, beziehung in list(self.prs.part.rels.items()):
            if beziehung.reltype.endswith("/printerSettings"):
                self.prs.part.rels.pop(kennung)
        self.prs.slide_width, self.prs.slide_height = Emu(12192000), Emu(6858000)
        self.leer = self.prs.slide_layouts[6]
        self.titel = titel
        self.logo = _logo()

    def _text(self, folie, links, oben, breite, hoehe, text, groesse, *, fett=False, farbe=SCHWARZ, schrift=SCHRIFT):
        from pptx.dml.color import RGBColor
        from pptx.util import Pt

        feld = folie.shapes.add_textbox(links, oben, breite, hoehe)
        rahmen = feld.text_frame
        rahmen.word_wrap = True
        lauf = rahmen.paragraphs[0].add_run()
        lauf.text = text
        lauf.font.size, lauf.font.bold, lauf.font.name = Pt(groesse), fett, schrift
        lauf.font.color.rgb = RGBColor.from_string(farbe)
        return feld

    def folie(self, titel: str, *, gross: bool = False):
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Cm

        if len(self.prs.slides) >= FOLIEN_MAX:
            raise InhaltFehler(f"Zu viele Folien (höchstens {FOLIEN_MAX}); als Word oder Excel speichern")
        folie = self.prs.slides.add_slide(self.leer)
        breite, hoehe = self.prs.slide_width, self.prs.slide_height
        balken = folie.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.5), Cm(6.2) if gross else Cm(1.2), Cm(1.6), Cm(0.25))
        balken.fill.solid()
        balken.fill.fore_color.rgb = RGBColor.from_string(ROT)
        balken.line.fill.background()
        folie.shapes.add_picture(self.logo, breite - Cm(1.5) - Cm(4.2), Cm(0.8), width=Cm(4.2))
        if gross:
            self._text(folie, Cm(1.5), Cm(6.7), breite - Cm(3), Cm(3.5), titel, 40, fett=True)
            self._text(folie, Cm(1.5), Cm(10.4), breite - Cm(3), Cm(1.2), _stand(), 16, farbe=GRAU_DUNKEL)
        else:
            self._text(folie, Cm(1.5), Cm(1.6), breite - Cm(8), Cm(2.0), titel, 28, fett=True)
        self._text(folie, Cm(1.5), hoehe - Cm(1.4), breite - Cm(6), Cm(0.8), ANSCHRIFT, 10, farbe=GRAU_DUNKEL)
        nummer = self._text(folie, breite - Cm(4.5), hoehe - Cm(1.4), Cm(3), Cm(0.8), str(len(self.prs.slides)), 10,
                            farbe=GRAU_DUNKEL)
        nummer.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
        return folie

    def koerper(self, folie):
        from pptx.util import Cm

        rahmen = folie.shapes.add_textbox(Cm(1.5), Cm(4.0), self.prs.slide_width - Cm(3), Cm(13.0)).text_frame
        rahmen.word_wrap = True
        return rahmen

    def bytes(self) -> bytes:
        eig = self.prs.core_properties
        eig.author = eig.last_modified_by = FIRMA
        eig.title, eig.subject, eig.keywords, eig.comments = self.titel, "", "", ""
        eig.created = eig.modified = _jetzt()
        puffer = io.BytesIO()
        self.prs.save(puffer)
        return puffer.getvalue()


def _pptx_absatz(rahmen, art: str, zeile: str, erster: bool) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Pt

    absatz = rahmen.paragraphs[0] if erster else rahmen.add_paragraph()
    absatz.space_after = Pt(6)
    if art == "punkt":
        absatz.level = 0
        lauf = absatz.add_run()
        lauf.text = "• "
        lauf.font.size, lauf.font.name = Pt(18), SCHRIFT
        lauf.font.color.rgb = RGBColor.from_string(ROT)
    for teilart, text in teile(zeile):
        lauf = absatz.add_run()
        lauf.text = text
        lauf.font.size = Pt(18)
        lauf.font.name = CODESCHRIFT if teilart == "code" else SCHRIFT
        lauf.font.bold = teilart == "fett" or art == "unter"
        lauf.font.color.rgb = RGBColor.from_string(SCHWARZ)


def _abschnitte(inhalt: Inhalt) -> list[tuple[str, list[tuple[str, str]]]]:
    """Folie je Überschrift der Stufe 1 oder 2; Stufe 3 wird zur fetten Zeile."""
    abschnitte: list[tuple[str, list[tuple[str, str]]]] = []
    for art, stufe, zeile in bloecke(inhalt.text):
        if art == "ueberschrift" and stufe <= 2:
            abschnitte.append((klartext(zeile), []))
            continue
        if not abschnitte:
            abschnitte.append((inhalt.titel, []))
        abschnitte[-1][1].append(("unter" if art == "ueberschrift" else art, zeile))
    return abschnitte


def _zerlegen(zeile: str) -> list[str]:
    """Sehr lange Absätze an Wortgrenzen in Stücke von höchstens ZEICHEN_JE_FOLIE Zeichen teilen."""
    stuecke = []
    while len(zeile) > ZEICHEN_JE_FOLIE:
        schnitt = zeile.rfind(" ", 0, ZEICHEN_JE_FOLIE)
        schnitt = schnitt if schnitt > 0 else ZEICHEN_JE_FOLIE
        stuecke.append(zeile[:schnitt])
        zeile = zeile[schnitt:].lstrip()
    return [*stuecke, zeile]


def _stuecke(punkte: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Punkte auf Folien verteilen: höchstens PUNKTE_JE_FOLIE Punkte und rund ZEICHEN_JE_FOLIE Zeichen je Folie."""
    stuecke: list[list[tuple[str, str]]] = []
    aktuell: list[tuple[str, str]] = []
    zeichen = 0
    for art, zeile in punkte:
        for teil in _zerlegen(zeile):
            if aktuell and (len(aktuell) >= PUNKTE_JE_FOLIE or zeichen + len(teil) > ZEICHEN_JE_FOLIE):
                stuecke.append(aktuell)
                aktuell, zeichen = [], 0
            aktuell.append((art, teil))
            zeichen += len(teil)
    if aktuell or not stuecke:
        stuecke.append(aktuell)
    return stuecke


def _pptx_tabelle(satz: _Folien, inhalt: Inhalt) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Cm, Pt

    gruppen = [inhalt.zeilen[i:i + TABELLENZEILEN_JE_FOLIE] for i in range(0, len(inhalt.zeilen), TABELLENZEILEN_JE_FOLIE)] or [()]
    groesse = Pt(max(8, 14 - len(inhalt.spalten) // 2))
    for nr, gruppe in enumerate(gruppen, start=1):
        titel = inhalt.titel if len(gruppen) == 1 else f"{inhalt.titel} ({nr}/{len(gruppen)})"
        folie = satz.folie(titel)
        hoehe = Cm(0.9) * (len(gruppe) + 1)
        tabelle = folie.shapes.add_table(len(gruppe) + 1, len(inhalt.spalten), Cm(1.5), Cm(4.0),
                                         satz.prs.slide_width - Cm(3), hoehe).table
        for r, werte in enumerate((inhalt.spalten, *gruppe)):
            for c, wert in enumerate(werte):
                zelle = tabelle.cell(r, c)
                zelle.text = wert
                zelle.fill.solid()
                zelle.fill.fore_color.rgb = RGBColor.from_string(ROT if r == 0 else ("FFFFFF" if r % 2 else GRAU_HELL))
                for absatz in zelle.text_frame.paragraphs:
                    for lauf in absatz.runs:
                        lauf.font.size, lauf.font.name, lauf.font.bold = groesse, SCHRIFT, r == 0
                        lauf.font.color.rgb = RGBColor.from_string("FFFFFF" if r == 0 else SCHWARZ)


def _pptx_code(satz: _Folien, inhalt: Inhalt) -> None:
    from pptx.dml.color import RGBColor
    from pptx.util import Pt

    zeilen = inhalt.text.split("\n")
    gruppen = [zeilen[i:i + CODEZEILEN_JE_FOLIE] for i in range(0, len(zeilen), CODEZEILEN_JE_FOLIE)]
    for nr, gruppe in enumerate(gruppen, start=1):
        titel = inhalt.titel if len(gruppen) == 1 else f"{inhalt.titel} ({nr}/{len(gruppen)})"
        rahmen = satz.koerper(satz.folie(titel))
        for i, zeile in enumerate(gruppe):
            absatz = rahmen.paragraphs[0] if i == 0 else rahmen.add_paragraph()
            lauf = absatz.add_run()
            lauf.text = zeile
            lauf.font.name, lauf.font.size = CODESCHRIFT, Pt(14)
            lauf.font.color.rgb = RGBColor.from_string(SCHWARZ)


def _powerpoint(inhalt: Inhalt) -> bytes:
    satz = _Folien(inhalt.titel)
    satz.folie(inhalt.titel, gross=True)
    if inhalt.art == "dokument":
        for ueberschrift, punkte in _abschnitte(inhalt):
            stuecke = _stuecke(punkte)
            for nr, stueck in enumerate(stuecke):
                folie = satz.folie(ueberschrift if nr == 0 else f"{ueberschrift} (Fortsetzung)")
                if stueck:
                    rahmen = satz.koerper(folie)
                    for i, (art, zeile) in enumerate(stueck):
                        _pptx_absatz(rahmen, art, zeile, i == 0)
    elif inhalt.art == "tabelle":
        _pptx_tabelle(satz, inhalt)
    else:
        _pptx_code(satz, inhalt)
    return satz.bytes()
