"""Einwilligung in den Stimmabdruck (DSGVO Art. 9 Abs. 2 lit. a): Text und Version stehen hier, die Oberfläche zeigt sie nur an.

Der Kern schickt den Text beim Start der Sitzung an die Oberfläche (einwilligung_nachricht). Das Einlernen beginnt nur mit der Client-Nachricht
{"aktion": "start", "einwilligung": "stimme-1"} (genau diese Version, einwilligung_gilt). Gespeichert werden Zeitpunkt und Version
(speakers.consent_at, speakers.consent_text_version, siehe stimme_speicher.py).

Wer den Text ändert, vergibt eine neue Version: Ein Abdruck mit älterer Version bleibt gespeichert, die Einwilligung für ein neues Einlernen
gilt aber nur für die aktuelle. Derselbe Wortlaut steht im Abschnitt 4 (Stimmabdruck) von docs/labor-datenschutz-entwurf.md;
test_stimme_einwilligung_doku.py prüft, dass beide übereinstimmen.

Zwei Fassungen (Entscheidung von Niko vom 18.11.2026): stimme-1 gilt ohne Schattenbetrieb (ein Abdruck aus 192 Zahlen). Mit
WAMO_STIMME_SCHATTEN=an (stimme_schatten.py) zeigt der Kern stimme-2 und lernt nur damit ein: Sie nennt zwei Abdrücke, 192 Zahlen für die
Prüfung und 256 Zahlen für den Vergleich eines zweiten Modells. Nur zu einem Abdruck mit stimme-2 entsteht und gilt ein Schatten-Abdruck
(schatten_erlaubt, in der Datenbank zusätzlich speakers_shadow_consent_chk, Migration 0028); ein Abdruck mit stimme-1 bekommt keinen, bis
die Person neu einlernt. Beide Fassungen bleiben für gespeicherte Abdrücke gültig (einwilligung_bekannt).
"""

from __future__ import annotations

EINWILLIGUNG_VERSION = "stimme-1"
EINWILLIGUNG_TEXT = (
    "Ich willige ausdrücklich ein, dass W.A.I.S. aus einer kurzen Aufnahme meiner Stimme einen Stimmabdruck berechnet und in meinem Profil "
    "speichert. Der Stimmabdruck besteht nur aus 192 Zahlen, es wird keine Aufnahme gespeichert. Die Berechnung läuft im Kern von W.A.I.S. "
    "auf dem eigenen Server der WAMOCON GmbH. W.A.I.S. nutzt den Stimmabdruck allein, um meine Stimme von anderen Stimmen zu unterscheiden: "
    "Stimmen, die W.A.I.S. sicher als fremd erkennt, werden nicht verarbeitet und lösen nichts aus. Der Stimmabdruck ist ein biometrisches "
    "Datum nach Artikel 9 DSGVO, deshalb brauche ich diese ausdrückliche Einwilligung. Sie ist freiwillig: Ohne sie nutze ich W.A.I.S. ohne "
    "Nachteil weiter. Ich kann den Stimmabdruck jederzeit in den Einstellungen löschen. Das gilt zugleich als Widerruf meiner "
    "Einwilligung, er wirkt für die Zukunft."
)


EINWILLIGUNG_VERSION_SCHATTEN = "stimme-2"
EINWILLIGUNG_TEXT_SCHATTEN = (
    "Ich willige ausdrücklich ein, dass W.A.I.S. aus einer kurzen Aufnahme meiner Stimme zwei Stimmabdrücke berechnet und in meinem Profil "
    "speichert: einen aus 192 Zahlen für die Prüfung meiner Stimme und einen aus 256 Zahlen für den Vergleich mit einem zweiten Modell. Es "
    "wird keine Aufnahme gespeichert. Die Berechnung läuft im Kern von W.A.I.S. auf dem eigenen Server der WAMOCON GmbH. W.A.I.S. nutzt die "
    "Stimmabdrücke allein, um meine Stimme von anderen Stimmen zu unterscheiden und um zu messen, welches der beiden Modelle das besser kann: "
    "Stimmen, die W.A.I.S. sicher als fremd erkennt, werden nicht verarbeitet und lösen nichts aus. Für den Vergleich hält W.A.I.S. je Äußerung "
    "nur Zahlen im Protokoll des Servers fest, nie einen Ton oder einen Text. Die Stimmabdrücke sind biometrische Daten nach Artikel 9 DSGVO, "
    "deshalb brauche ich diese ausdrückliche Einwilligung. Sie ist freiwillig: Ohne sie nutze ich W.A.I.S. ohne Nachteil weiter. Ich kann den "
    "Stimmabdruck jederzeit in den Einstellungen löschen, damit werden beide Stimmabdrücke gelöscht. Das gilt zugleich als Widerruf meiner "
    "Einwilligung, er wirkt für die Zukunft."
)
TEXTE = {EINWILLIGUNG_VERSION: EINWILLIGUNG_TEXT, EINWILLIGUNG_VERSION_SCHATTEN: EINWILLIGUNG_TEXT_SCHATTEN}


def aktuelle_version(schatten: bool = False) -> str:
    """Die Fassung, die der Kern zeigt und für ein neues Einlernen verlangt: stimme-2 im Schattenbetrieb, sonst stimme-1."""
    return EINWILLIGUNG_VERSION_SCHATTEN if schatten else EINWILLIGUNG_VERSION


def einwilligung_nachricht(schatten: bool = False) -> dict:
    """Nachricht an die Oberfläche beim Start der Sitzung, mit der Fassung zum Betrieb (schatten: WAMO_STIMME_SCHATTEN an)."""
    version = aktuelle_version(schatten)
    return {"type": "stimmabdruck_einwilligung", "version": version, "text": TEXTE[version]}


def einwilligung_gilt(version: object, schatten: bool = False) -> bool:
    """Für ein neues Einlernen zählt nur genau die aktuelle Fassung (kein Vergleich ohne Typ: True oder 1 sind keine Einwilligung)."""
    return isinstance(version, str) and version == aktuelle_version(schatten)


def einwilligung_bekannt(version: object) -> bool:
    """Eine Fassung, mit der ein Abdruck gespeichert werden darf (stimme-1 oder stimme-2); welche gerade verlangt wird, prüft die Sitzung."""
    return isinstance(version, str) and version in TEXTE


def schatten_erlaubt(version: object) -> bool:
    """Deckt diese Fassung einen Schatten-Abdruck (nur stimme-2)?"""
    return isinstance(version, str) and version == EINWILLIGUNG_VERSION_SCHATTEN
