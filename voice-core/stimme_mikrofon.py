"""Mikrofon eines Stimmabdrucks (seit 18.11.2026): je eingelerntem Mikrofon ein Abdruck, höchstens MAX_ABDRUECKE je Person.

Befund vom 17. und 18.11.2026: Der wichtigste Faktor der Stimmprüfung ist das Mikrofon. Mit dem Laptop-Mikrofon eingelernt lagen kurze
eigene Sätze am selben Gerät bei 0,53 bis 0,71, mit einem anderen Gerät bei 0,14 bis 0,49. Deshalb lernt die Person jedes ihrer Mikrofone
einmal ein, und die Prüfung nimmt den besten Wert über ihre Abdrücke (stimme_gate.StimmGate.vergleichen).

Die Oberfläche schickt beim Einlernen den Namen des Mikrofons, das im Gespräch läuft (Name der Spur im Browser oder in der App). Hier wird
er noch einmal bereinigt (mikrofon_name: nur Text, ohne Steuer- und Formatzeichen, ohne den Vorsatz, den Chrome den Aliasen voranstellt,
Leerraum zusammengezogen, höchstens MAX_NAME Zeichen) und daraus die Kennung gebildet (mikrofon_kennung: die ersten 32 Hexzeichen des
SHA-256 des Namens in Kleinschrift). Die Kennung unterscheidet die Abdrücke einer Person in speakers.mikrofon (Migration 0029), der Name
steht zur Anzeige in speakers.mikrofon_name. Ohne Namen gilt das unbekannte Mikrofon (UNBEKANNT): So heißen auch alle Abdrücke, die vor
0029 eingelernt wurden. Nur Standardbibliothek.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

UNBEKANNT = "unbekannt"
MAX_NAME = 120  # wie die Oberfläche (lib/mikrofon.ts geraeteName) und die Regel speakers_mikrofon_name_chk
MAX_ABDRUECKE = 3  # je Person, Entscheidung vom 18.11.2026; die Datenbank erzwingt es selbst (Trigger speakers_mikrofon_grenze)
KENNUNG_RE = re.compile(r"^(unbekannt|[0-9a-f]{32})$")
# Vorsatz, den Chrome den Aliasen voranstellt ("Standard - Headset", "Kommunikation - Headset"), wie ALIAS_VORSATZ in ui/src/lib/mikrofon.ts
_VORSATZ = re.compile(r"^(standard|default|kommunikation|communications)\s*[-\u2013]\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Mikrofon:
    """Ein Mikrofon, für das ein Abdruck gilt: kennung (UNBEKANNT oder 32 Hexzeichen), name zur Anzeige (None: unbekannt)."""

    kennung: str = UNBEKANNT
    name: str | None = None


UNBEKANNTES_MIKROFON = Mikrofon()


_WEG = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})  # Steuer-, Format- (auch Bidi), Surrogat-, private und nicht vergebene Zeichen


def mikrofon_name(roh: object) -> str | None:
    """Der bereinigte Name oder None, wenn nichts Brauchbares bleibt (kein Text, leer, nur Steuerzeichen). Immer gültiges UTF-8 (ein
    einzelnes Surrogat aus JSON fällt weg), in Normalform NFC."""
    if not isinstance(roh, str):
        return None
    roh = unicodedata.normalize("NFC", "".join(z for z in roh[: MAX_NAME * 4] if unicodedata.category(z) != "Cs"))
    ohne = "".join(" " if z.isspace() else z for z in roh if unicodedata.category(z) not in _WEG or z.isspace())
    name = " ".join(ohne.split())
    name = _VORSATZ.sub("", name).strip()[:MAX_NAME].strip()
    return name or None


def mikrofon_kennung(name: str | None) -> str:
    """Kennung zum bereinigten Namen: UNBEKANNT ohne Namen, sonst 32 Hexzeichen (SHA-256 der Kleinschrift)."""
    if not name:
        return UNBEKANNT
    return hashlib.sha256(name.lower().encode("utf-8", "ignore")).hexdigest()[:32]


def mikrofon_aus(roh: object) -> Mikrofon:
    """Das Mikrofon zur Angabe der Oberfläche (Feld mikrofon der Client-Nachricht stimmabdruck)."""
    name = mikrofon_name(roh)
    return Mikrofon(mikrofon_kennung(name), name) if name else UNBEKANNTES_MIKROFON


def kennung_gueltig(kennung: object) -> bool:
    """Sieht der Wert aus wie eine Kennung (für das Löschen eines einzelnen Abdrucks aus der Oberfläche)?"""
    return isinstance(kennung, str) and KENNUNG_RE.fullmatch(kennung) is not None
