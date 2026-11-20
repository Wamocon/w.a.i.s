"""Regeln für den Kartenkatalog (ohne Datenbank, ohne Netz).

Eine Karte ist ein Use Case des Labors. Ihre Nummer besteht aus dem Buchstaben der Gruppe und einer Zahl (W1, J12). Die Zahl vergibt
der Dienst: höchste Zahl der Gruppe plus eins, höchstens 99.

Zeichenbudget: Der Kern lädt die Wissenstexte der aktiven Version zusammen mit den Dateien der Labor-Daten (BASIS_ZEICHEN, Umgebung
WAMO_WERKSTATT_WISSEN_BASIS) und lehnt mehr als 6000 Zeichen ab. Die Prüfung hier warnt vorher: BASIS plus die Summe aller Wissenstexte
(Wissen "Eigener Text") darf 6000 nicht übersteigen, höchstens 20 Karten tragen einen eigenen Text.

Anweisungen an das Modell: Nur der Wissenstext erreicht das Modell (als Daten, nie als Anweisung). Aufgabe und Erwartung sind die
Sprechprobe und die Messlatte für den Gast, sie dürfen auch Sätze wie "Ignorier deine Regeln" enthalten, denn genau das wird geprüft.
Im Wissenstext lehnt die Prüfung Muster ab, die wie eine Anweisung an das Modell aussehen (Heuristik, die zweite Linie ist der Kern).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .eingabe import ganzzahl_lesen, text_lesen
from .fehler import ungueltig

GRUPPEN = {"W": "Wissen", "A": "Anforderungen", "J": "Jira", "M": "Mail", "S": "Sicherheit", "G": "Gespräch", "E": "Eigene Gruppe"}
WISSEN = ("keine", "Glossar", "ISTQB-Basis", "Eigener Text")
WERKZEUGE = ("Jira", "Mail", "Canvas", "Websuche")
KARTE_ID_RE = re.compile(r"^[A-Z][0-9]{1,2}$")
ZAHL_MAX = 99
WISSEN_MAX = 6000
WISSENSTEXT_MAX = 900
EIGENE_TEXTE_MAX = 20
STAND_ENTWURF, STAND_VEROEFFENTLICHT = "entwurf", "veroeffentlicht"
FELDER_STAND = ("id", "gruppe", "titel", "aufgabe", "erwartung", "fehler", "lernziel", "wissen", "wissenstext", "werkzeuge", "dauer_min", "stand")
AKTION_VEROEFFENTLICHEN = "karten_veroeffentlichen"

# Heuristik gegen Anweisungen an das Modell im Wissenstext (Deutsch und Englisch, ohne Beachtung der Groß- und Kleinschreibung)
_ANWEISUNG = re.compile(
    r"ignorier\w*|vergiss\s+(alle|deine|die|das)\b|du\s+bist\s+(jetzt|nun|ab)\b|neue\s+(regeln?|anweisung\w*)|"
    r"(antworte|reagiere|handle|sprich)\s+(nur|immer|ab)\b|system\s*-?\s*prompt|"
    r"ignore\s+(all|any|the|previous|prior|your)\b|disregard\b|forget\s+(all|your|the|previous)\b|you\s+are\s+now\b|"
    r"act\s+as\b|pretend\b|jailbreak|"
    r"<[^>]{0,80}>|\[/?(inst|system)\]|^\s*(system|assistant|human|user|developer|ai)\s*:",
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


def karte_felder(daten: Mapping[str, Any]) -> dict[str, Any]:
    """Die Felder einer Karte, die die Person ändert (ohne Gruppe und Nummer). Unbekannte Felder werden ignoriert."""
    wissen = daten.get("wissen", "keine")
    if wissen not in WISSEN:
        raise ungueltig("Die Art des Wissens ist unbekannt.")
    wissenstext = text_lesen(daten.get("wissenstext"), "Der Wissenstext", maximum=WISSENSTEXT_MAX) if wissen == "Eigener Text" else None
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


def zeichen(karten: list[Mapping[str, Any]], basis: int) -> int:
    return basis + sum(len(k.get("wissenstext") or "") for k in karten if k.get("wissen") == "Eigener Text")


def pruefen(karten: list[Mapping[str, Any]], basis: int) -> tuple[list[str], int]:
    """Probleme (Sätze ohne Inhalte der Texte) und Zeichenzahl des Katalogs. ok heißt: keine Probleme."""
    probleme: list[str] = []
    entwuerfe = [k["id"] for k in karten if k.get("stand") == STAND_ENTWURF]
    if not entwuerfe:
        probleme.append("Es gibt keine Entwürfe zum Veröffentlichen.")
    for k in sorted(karten, key=lambda x: sortierschluessel(x["id"])):
        kid = k["id"]
        if not (k.get("titel") and k.get("aufgabe") and k.get("erwartung")):
            probleme.append(f"Karte {kid}: Titel, Aufgabe und erwartetes Ergebnis sind Pflicht.")
        if k.get("wissen") == "Eigener Text" and not k.get("wissenstext"):
            probleme.append(f"Karte {kid}: Beim Wissen \"Eigener Text\" fehlt der Wissenstext.")
        if any(w not in WERKZEUGE for w in k.get("werkzeuge") or []):
            probleme.append(f"Karte {kid}: Ein Werkzeug ist nicht erlaubt.")
        if k.get("wissen") == "Eigener Text" and _ANWEISUNG.search(k.get("wissenstext") or ""):
            probleme.append(f"Karte {kid}: Der Wissenstext enthält etwas, das wie eine Anweisung an das Modell aussieht.")
    eigene = sum(1 for k in karten if k.get("wissen") == "Eigener Text")
    if eigene > EIGENE_TEXTE_MAX:
        probleme.append(f"Zu viele eigene Wissenstexte: {eigene} von höchstens {EIGENE_TEXTE_MAX}.")
    gesamt = zeichen(karten, basis)
    if gesamt > WISSEN_MAX:
        probleme.append(f"Das Zeichenbudget ist überschritten: {gesamt} von {WISSEN_MAX}.")
    return probleme, gesamt


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
