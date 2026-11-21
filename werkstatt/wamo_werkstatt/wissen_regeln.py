"""Prüfregeln für Wissenstexte: dieselben wie die des Kerns (voice-core/labor_karten_db.py, Funktion pruefen), mit denselben Gründen.

Was der Kern später ablehnt, soll hier gar nicht erst durchgehen. Die Regeln sind wegen des getrennten Dienstes DUPLIZIERT, nicht
importiert. Ein Vertragstest (tests/test_wissen_vertrag.py) hält beide Seiten mit denselben Beispielen zusammen und läuft gegen den echten
Kern, sobald dessen Modul importierbar ist.

Regeln für einen Text (der Kern lehnt eine ganze Version ab, wenn ein Text sie verletzt, er kürzt oder entfernt nie):
  * nicht leer, nach dem Kürzen von Rändern höchstens MAX_TEXT Zeichen (GRUND_LEER, GRUND_LANG)
  * nur Buchstaben, Zeichen mit Akzent, Ziffern, Satzzeichen, Symbole, Leerzeichen, Zeilenumbruch und Tabulator, dazu keines der
    unsichtbaren Zeichen aus UNSICHTBAR_BEREICHE (GRUND_ZEICHEN)
  * kein Markup nach NFKC (GRUND_MARKUP): Tags (auch über Zeilenumbrüche, Kommentare, Verarbeitungsanweisungen), Sondermarken der
    Chat-Vorlagen (<| und |>), eckige Marken älterer Vorlagen und Werkzeugmarken, Zeilen, die eine Gesprächsrolle (Human:, Assistant:) eröffnen
Zusammen höchstens MAX_EINTRAEGE Texte und KATALOG_BUDGET_ZEICHEN Zeichen (GRUND_VIELE, GRUND_GESAMT).
"""

from __future__ import annotations

import re
import unicodedata

MAX_EINTRAEGE = 20
MAX_TEXT = 900
KATALOG_BUDGET_ZEICHEN = 2000  # Summe aller Wissenstexte einer Version, unabhängig von den Dateien der Labor-Daten (Entscheidung 21.11.2026)

GRUND_LANG = "zu lang"
GRUND_GESAMT = "Gesamtumfang zu groß"
GRUND_VIELE = "zu viele Einträge"
GRUND_ZEICHEN = "Steuerzeichen"
GRUND_MARKUP = "Markup"
GRUND_LEER = "Text leer"

_ERLAUBTE_KATEGORIEN = "LMNPS"
# Markup, das ein Text nicht tragen darf (geprüft nach NFKC, damit vollbreite Zeichen nichts umgehen). [ \t] statt \s in den Klammern,
# damit die Suche linear bleibt. Ein Vergleich wie "a < b" bleibt erlaubt, "a<b und c>d" nicht.
_MARKUP = re.compile(r"<[/!?|A-Za-z][^<>]*>|<\||\|>|\[[ \t]*/?[ \t]*(?:INST|SYS|TOOL_CALLS|AVAILABLE_TOOLS|TOOL_RESULTS)[ \t]*\]"
                     r"|^[ \t]*(?:human|assistant)[ \t]*:", re.IGNORECASE | re.MULTILINE)
# Zeichen, die als Symbol oder Buchstabe durchgehen, obwohl kein Mensch sie sieht (Variation Selectors, Füllzeichen, Braille-Leerzeichen,
# kombinierender Graphem-Verbinder)
UNSICHTBAR_BEREICHE = ((0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180D), (0x2800, 0x2800), (0x3164, 0x3164),
                       (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0100, 0xE01EF))
_UNSICHTBAR = re.compile("[" + "".join(f"{chr(von)}-{chr(bis)}" for von, bis in UNSICHTBAR_BEREICHE) + "]")


def zeichen_ok(text: str) -> bool:
    return all(ch in "\n\t " or unicodedata.category(ch)[0] in _ERLAUBTE_KATEGORIEN for ch in text)


def text_grund(text: object, *, laenge: bool = True) -> str | None:
    """Der Grund, aus dem der Kern diesen Text ablehnt, oder None. laenge=False lässt die Längenprüfung weg (für die Eingabe, die danach
    Zeilenumbrüche zu Leerzeichen macht und die Länge am gespeicherten Text prüft)."""
    if not isinstance(text, str):
        return GRUND_LEER
    if laenge and len(text) > MAX_TEXT * 2:  # grob vorab, damit ein riesiger Text nicht erst durchsucht wird
        return GRUND_LANG
    sauber = text.replace("\r\n", "\n").strip()
    if not sauber:
        return GRUND_LEER
    if laenge and len(sauber) > MAX_TEXT:
        return GRUND_LANG
    if not zeichen_ok(sauber) or _UNSICHTBAR.search(sauber):
        return GRUND_ZEICHEN
    if _MARKUP.search(unicodedata.normalize("NFKC", sauber)):
        return GRUND_MARKUP
    return None


def katalog_grund(texte: list[str]) -> str | None:
    """Der Grund, aus dem der Kern die ganze Version ablehnt (Zahl der Texte, Gesamtumfang, jeder einzelne Text), oder None."""
    if len(texte) > MAX_EINTRAEGE:
        return GRUND_VIELE
    for text in texte:
        if (grund := text_grund(text)) is not None:
            return grund
    if sum(len(t.strip()) for t in texte) > KATALOG_BUDGET_ZEICHEN:
        return GRUND_GESAMT
    return None
