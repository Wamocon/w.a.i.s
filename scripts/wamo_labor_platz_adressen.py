"""Die festen Adressen des Testlabors für das Platz-Skript (scripts/wamo_labor_platz.py), nur Standardbibliothek.

Es gibt genau einen Server (Sokrates-2) und vier Herkünfte: Anmeldung 55443, Kern 55444, Oberfläche 55445 und der Labor-Dienst 55447
(Board). Alles läuft über https mit dem Zertifikat der WAMO-CA. Die einzige Ausnahme ist die Weiterleitung auf Loopback, mit der das
Platz-Token ohne Befehlszeile und ohne Datei ins Board-Fenster kommt (siehe wamo_labor_platz_start.py).

Wichtig für die Sicherheit: Das Platz-Token wird an die Board-Adresse gehängt. Deshalb ist `adresse_zulaessig` bewusst eng: Es gilt nur
die genaue Zeichenfolge aus einer festen Menge (die Oberfläche, das Board und die vier Prüfadressen), kein anderer Pfad auf denselben Ports.
Eine veränderte Platzdatei kann das Token also nie an einen anderen Ort schicken.

`VERBOTENE_ZIELE` ist die Gegenprobe der Netztrennung für `pruefen`: Ziele im Büronetz, die ein Platz NICHT erreichen darf.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HOST = "192.168.178.136"
PORT_ANMELDUNG, PORT_KERN, PORT_OBERFLAECHE, PORT_LABOR = 55443, 55444, 55445, 55447
PORTS = (PORT_ANMELDUNG, PORT_KERN, PORT_OBERFLAECHE, PORT_LABOR)
HERKUENFTE = tuple(f"https://{HOST}:{p}" for p in PORTS)
WAMO_URL = f"https://{HOST}:{PORT_OBERFLAECHE}"
BOARD_URL = f"https://{HOST}:{PORT_LABOR}/board"
# Die einzigen Adressen, die das Skript aufruft oder im Weg des Tokens benutzt (Gleichheit der Zeichenfolge)
FESTE_ADRESSEN = frozenset({WAMO_URL, WAMO_URL + "/", BOARD_URL, f"{HERKUENFTE[0]}/auth/v1/health", f"{HERKUENFTE[1]}/", f"{HERKUENFTE[2]}/"})
# Weiterleitung auf Loopback: fester Port und fester Pfad, damit die Chrome-Richtlinie genau diese Adresse erlauben kann
WEITER_PORT = 55489
WEITER_PFAD = "/weiter/"
WEITER_ADRESSE = f"http://127.0.0.1:{WEITER_PORT}{WEITER_PFAD}"
TOKEN_MUSTER = re.compile(r"[0-9a-f]{32}")  # Platz-Token: 128 Bit als 32 Hexzeichen (labor-dienst/README.md)


@dataclass(frozen=True)
class Ziel:
    host: str
    port: int
    name: str  # für die Ausgabe von `pruefen`


# Verbotene Ziele der Netzprobe (docs/testlabor-wamo.md 3.9, "Gerät, Zertifikat und Netz"): Ein Platz darf nur HOST auf PORTS (TCP)
# und den UDP-Bereich des Kerns erreichen. Hier stehen nur Server, die mit Adresse in CLAUDE.md oder docs/ stehen, und nur Ports aus
# diesen Quellen (Herkunft je Zeile). Die Liste ist eine Stichprobe, kein Beweis der Trennung.
SOKRATES1, CAESAR, ROUTER = "192.168.178.75", "192.168.178.64", "192.168.178.1"
VERBOTENE_ZIELE = (
    Ziel(HOST, 22, "Sokrates-2, SSH"),  # Kern-Kanal und Verwaltung über SSH (CLAUDE.md, Kern-Kanal des Dispatchers)
    Ziel(HOST, 55321, "Sokrates-2, Envoy"),  # CLAUDE.md, Architektur 1 und Erstanmeldung ("Envoy 55321 nicht aus dem LAN")
    Ziel(HOST, 55322, "Sokrates-2, Datenbank-Pooler Session"),  # CLAUDE.md, Architektur 1; infra/sokrates2/README.md
    Ziel(HOST, 56543, "Sokrates-2, Datenbank-Pooler Transaktion"),  # infra/sokrates2/README.md; docs/testlabor-wamo.md 2.1 und 3.9
    Ziel(HOST, 55446, "Sokrates-2, Remote-Desktop-Gateway"),  # CLAUDE.md, Remote Desktop (Gateway); docs/remote-desktop.md
    Ziel(HOST, 11434, "Sokrates-2, Ollama"),  # CLAUDE.md, Haus-Proxy (api_base http://192.168.178.136:11434)
    Ziel(SOKRATES1, 4000, "Sokrates-1, zentrales LiteLLM-Gateway"),  # CLAUDE.md, Architektur 5; docs/hausmodelle-und-kikollege.md 1.1
    Ziel(CAESAR, 4000, "Caesar, LiteLLM"),  # docs/hausmodelle-und-kikollege.md 1.1 (Caesar, Weiteres)
    Ziel(CAESAR, 11434, "Caesar, Ollama"),  # docs/hausmodelle-und-kikollege.md 1.1
    Ziel(CAESAR, 3389, "Caesar, Fernzugriff RDP"),  # docs/remote-desktop.md 2.3
    Ziel(ROUTER, 80, "Router, Weboberfläche http"),  # docs/remote-desktop.md (Standardroute über die Fritzbox 192.168.178.1)
    Ziel(ROUTER, 443, "Router, Weboberfläche https"),
)


def adresse_zulaessig(url: object) -> bool:
    """Nur genau diese Adressen (Zeichenfolge gleich), nichts sonst: weder ein anderer Pfad noch eine andere Schreibweise."""
    return isinstance(url, str) and url in FESTE_ADRESSEN


def token_gueltig(wert: object) -> bool:
    return isinstance(wert, str) and TOKEN_MUSTER.fullmatch(wert) is not None
