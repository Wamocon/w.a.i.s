"""Regeln für den Kartenkatalog (ohne Datenbank, ohne Netz).

Eine Karte ist ein Use Case des Labors. Ihre Nummer besteht aus dem Buchstaben der Gruppe und einer Zahl (W1, J12). Die Zahl vergibt
der Dienst: höchste Zahl der Gruppe plus eins, höchstens 99.

Katalogbudget: Die Summe aller Wissenstexte (Wissen "Eigener Text") darf KATALOG_BUDGET_ZEICHEN (2000) nicht übersteigen, je Karte höchstens 900
Zeichen, höchstens 20 Karten tragen einen eigenen Text. Es ist ein eigenes Budget des Katalogs: Die Dateien der Labor-Daten mit ihren 6000
Zeichen zählen nicht mit.

Prüfregeln für Wissenstexte: dieselben wie im Kern (wissen_regeln.py): Zeichen, Markup nach NFKC, Rollenzeilen, unsichtbare Zeichen, mit
denselben Gründen. Zusätzlich eine Heuristik gegen Anweisungen an das Modell. Nur der Wissenstext erreicht das Modell (als Daten, nie als
Anweisung). Aufgabe und Erwartung sind die Sprechprobe und die Messlatte für den Gast, sie dürfen auch Sätze wie "Ignorier deine Regeln"
enthalten, denn genau das wird geprüft.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from .eingabe import ganzzahl_lesen, text_lesen
from .fehler import ungueltig
from .wissen_regeln import KATALOG_BUDGET_ZEICHEN, MAX_EINTRAEGE, MAX_TEXT, text_grund

GRUPPEN = {"W": "Wissen", "A": "Anforderungen", "J": "Jira", "M": "Mail", "S": "Sicherheit", "G": "Gespräch", "E": "Eigene Gruppe"}
WISSEN = ("keine", "Glossar", "ISTQB-Basis", "Eigener Text")
WERKZEUGE = ("Jira", "Mail", "Canvas", "Websuche")
KARTE_ID_RE = re.compile(r"^[A-Z][0-9]{1,2}$")
ZAHL_MAX = 99
WISSENSTEXT_MAX = MAX_TEXT
EIGENE_TEXTE_MAX = MAX_EINTRAEGE
STAND_ENTWURF, STAND_VEROEFFENTLICHT = "entwurf", "veroeffentlicht"
FELDER_STAND = ("id", "gruppe", "titel", "aufgabe", "erwartung", "fehler", "lernziel", "wissen", "wissenstext", "werkzeuge", "dauer_min", "stand")
AKTION_VEROEFFENTLICHEN = "karten_veroeffentlichen"

# Heuristik gegen Anweisungen an das Modell im Wissenstext (Deutsch und Englisch, nach NFKC, ohne Beachtung der Groß- und Kleinschreibung).
# Markup und Rollenzeilen prüft wissen_regeln.py wie der Kern; maßgeblich bleibt die zweite Linie im Kern.
_ANWEISUNG = re.compile(
    r"ignorier\w*|missacht\w*|vergiss\s+(alle\w*|deine\w*|die|das|jede\w*)|du\s+bist\s+(jetzt|nun|ab|ein\w*)\b|neue\s+(regeln?|anweisung\w*)|"
    r"(antworte|reagiere|handle|sprich)\w*\s+(nur|immer|ab)\b|ab\s+jetzt\s+(antwort|sag|handl|reagier)\w*|system\s*-?\s*prompt|"
    r"ignore\s+(all|any|the|previous|prior|your)\b|disregard\b|forget\s+(all|your|the|previous)\b|you\s+are\s+now\b|"
    r"act\s+as\b|pretend\b|jailbreak|^[ \t]*(?:system|user|developer|ai)[ \t]*:",
    re.IGNORECASE | re.MULTILINE,
)


def gruppe_lesen(wert: object) -> tuple[str, str]:
    """Buchstabe und Name der Gruppe. Erlaubt ist der Name (Wissen) oder der Buchstabe (W), sonst 422."""
    if isinstance(wert, str):
        if wert in GRUPPEN:
            return wert, GRUPPEN[wert]
        for buchstabe, name in GRUPPEN.items():
            if wert == name:
                return buchstabe, name
    raise ungueltig("Die Gruppe ist unbekannt.")


def sortierschluessel(karte_id: str) -> tuple[str, int]:
    return karte_id[:1], int(karte_id[1:] or 0)


def naechste_id(buchstabe: str, vorhandene: list[str]) -> str | None:
    """Nächste freie Nummer der Gruppe (höchste plus eins) oder None, wenn die Gruppe voll ist."""
    hoechste = max((int(i[1:]) for i in vorhandene if i[:1] == buchstabe and KARTE_ID_RE.fullmatch(i)), default=0)
    return f"{buchstabe}{hoechste + 1}" if hoechste < ZAHL_MAX else None


def _wissenstext_lesen(roh: object) -> str | None:
    """Der Wissenstext: erst die Regeln des Kerns auf dem Rohtext (Markup und Rollenzeilen über Zeilenumbrüche hinweg), dann Zeilenumbrüche
    zu Leerzeichen und die Längenprüfung am gespeicherten Text."""
    if isinstance(roh, str) and roh.strip() and (grund := text_grund(roh, laenge=False)) is not None:
        raise ungueltig(f"Der Wissenstext wird nicht angenommen ({grund}).")
    return text_lesen(roh, "Der Wissenstext", maximum=WISSENSTEXT_MAX)


def karte_felder(daten: Mapping[str, Any]) -> dict[str, Any]:
    """Die Felder einer Karte, die die Person ändert (ohne Gruppe und Nummer). Unbekannte Felder werden ignoriert."""
    wissen = daten.get("wissen", "keine")
    if wissen not in WISSEN:
        raise ungueltig("Die Art des Wissens ist unbekannt.")
    wissenstext = _wissenstext_lesen(daten.get("wissenstext")) if wissen == "Eigener Text" else None
    if wissen == "Eigener Text" and wissenstext is None:
        raise ungueltig("Beim Wissen \"Eigener Text\" fehlt der Wissenstext.")
    roh = daten.get("werkzeuge", [])
    if not isinstance(roh, list) or any(w not in WERKZEUGE for w in roh):
        raise ungueltig("Die Werkzeuge müssen aus Jira, Mail, Canvas und Websuche bestehen.")
    return {
        "titel": text_lesen(daten.get("titel"), "Der Titel", maximum=60, pflicht=True),
        "aufgabe": text_lesen(daten.get("aufgabe"), "Die Aufgabe", maximum=240, pflicht=True),
        "erwartung": text_lesen(daten.get("erwartung"), "Das erwartete Ergebnis", maximum=240, pflicht=True),
        "fehler": text_lesen(daten.get("fehler"), "Der Fehlerfall", maximum=120),
        "lernziel": text_lesen(daten.get("lernziel"), "Das Lernziel", maximum=40),
        "wissen": wissen,
        "wissenstext": wissenstext,
        "werkzeuge": [w for w in WERKZEUGE if w in roh],
        "dauer_min": ganzzahl_lesen(daten.get("dauer_min", 4), "Die Dauer", minimum=1, maximum=20),
    }


def karte_ausgabe(zeile: Mapping[str, Any]) -> dict[str, Any]:
    """Eine Karte für die Antwort (nur die Felder des Katalogs, nie mehr)."""
    aus = {k: zeile.get(k) for k in FELDER_STAND}
    aus["werkzeuge"] = list(zeile.get("werkzeuge") or [])
    geaendert = zeile.get("geaendert_at")
    aus["geaendert_at"] = geaendert.isoformat() if hasattr(geaendert, "isoformat") else None
    return aus


def eigene_texte(karten: list[Mapping[str, Any]]) -> list[str]:
    return [k.get("wissenstext") or "" for k in karten if k.get("wissen") == "Eigener Text"]


def zeichen(karten: list[Mapping[str, Any]]) -> int:
    """Summe aller Wissenstexte (das Katalogbudget wird daran gemessen)."""
    return sum(len(t) for t in eigene_texte(karten))


def pruefen(karten: list[Mapping[str, Any]]) -> tuple[list[str], int]:
    """Probleme (Sätze ohne Inhalte der Texte) und Zeichenzahl des Katalogs. ok heißt: keine Probleme."""
    probleme: list[str] = []
    if not any(k.get("stand") == STAND_ENTWURF for k in karten):
        probleme.append("Es gibt keine Entwürfe zum Veröffentlichen.")
    for k in sorted(karten, key=lambda x: sortierschluessel(x["id"])):
        kid = k["id"]
        if not (k.get("titel") and k.get("aufgabe") and k.get("erwartung")):
            probleme.append(f"Karte {kid}: Titel, Aufgabe und erwartetes Ergebnis sind Pflicht.")
        if any(w not in WERKZEUGE for w in k.get("werkzeuge") or []):
            probleme.append(f"Karte {kid}: Ein Werkzeug ist nicht erlaubt.")
        if k.get("wissen") == "Eigener Text":
            probleme.extend(_wissenstext_probleme(kid, k.get("wissenstext")))
    eigene = len(eigene_texte(karten))
    if eigene > EIGENE_TEXTE_MAX:
        probleme.append(f"Zu viele eigene Wissenstexte: {eigene} von höchstens {EIGENE_TEXTE_MAX}.")
    gesamt = zeichen(karten)
    if gesamt > KATALOG_BUDGET_ZEICHEN:
        probleme.append(f"Das Katalogbudget ist überschritten: {gesamt} von {KATALOG_BUDGET_ZEICHEN} Zeichen.")
    return probleme, gesamt


def _wissenstext_probleme(kid: str, text: object) -> list[str]:
    if not text:
        return [f"Karte {kid}: Beim Wissen \"Eigener Text\" fehlt der Wissenstext."]
    probleme = []
    if (grund := text_grund(text)) is not None:
        probleme.append(f"Karte {kid}: Der Wissenstext wird nicht angenommen ({grund}).")
    elif _ANWEISUNG.search(unicodedata.normalize("NFKC", text)):
        probleme.append(f"Karte {kid}: Der Wissenstext enthält etwas, das wie eine Anweisung an das Modell aussieht.")
    return probleme


def fingerabdruck(karten: list[Mapping[str, Any]]) -> str:
    """SHA-256 über den ganzen Katalog (Felder des Katalogs, nach Nummer sortiert). Die Freigabekarte trägt ihn, damit nur genau der
    gesehene Stand veröffentlicht wird."""
    kern = [{k: (list(z.get(k) or []) if k == "werkzeuge" else z.get(k)) for k in FELDER_STAND}
            for z in sorted(karten, key=lambda x: sortierschluessel(x["id"]))]
    return hashlib.sha256(json.dumps(kern, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def momentaufnahme(karten: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Der Katalog, wie ihn die neue Version festhält: alle Karten, alle als veröffentlicht."""
    return [{**{k: (list(z.get(k) or []) if k == "werkzeuge" else z.get(k)) for k in FELDER_STAND}, "stand": STAND_VEROEFFENTLICHT}
            for z in sorted(karten, key=lambda x: sortierschluessel(x["id"]))]


def matrix_pruefen(daten: Mapping[str, Any]) -> dict[int, list[str]]:
    """Zuordnung Platz -> Karten. Schlüssel sind die Platznummern 1 bis 16 als Text, Werte Listen von Kartennummern (höchstens 30 je Platz)."""
    roh = daten.get("zuordnung")
    if not isinstance(roh, dict) or len(roh) > 16:
        raise ungueltig("Die Zuordnung muss ein Objekt Platz zu Karten sein.")
    matrix: dict[int, list[str]] = {}
    for schluessel, liste in roh.items():
        if not (isinstance(schluessel, str) and schluessel.isascii() and schluessel.isdigit() and 1 <= int(schluessel) <= 16):
            raise ungueltig("Die Platznummer in der Zuordnung ist ungültig.")
        if not isinstance(liste, list) or len(liste) > 30 or any(not isinstance(i, str) or not KARTE_ID_RE.fullmatch(i) for i in liste):
            raise ungueltig("Die Kartennummern in der Zuordnung sind ungültig.")
        matrix[int(schluessel)] = list(dict.fromkeys(liste))
    return dict(sorted(matrix.items()))
