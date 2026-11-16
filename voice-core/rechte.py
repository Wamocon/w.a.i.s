"""Rechte für die PC-Steuerung an einer Stelle (Plan docs/ausrollen-neue-nutzer.md 4.5, Befund H1, Paket P4).

pc_stufe(identity) liefert "admin", "mitglied" oder None. Jede Stelle, die über PC-Werkzeuge entscheidet, fragt diese Funktion:
pc_geraet.pc_zugang_fuer (und damit der Host-Client über PcZugang.stufe), pc_nachverbinden.nachholen_moeglich, bot.py (Handler
pc_steuerung, darf_pc_freigeben, Freigabekarten, Prompt, Bildschirm, Live-Bild, Schutz der Mitglieder in pc_mitglied.py),
office_werkzeuge.pc_person (Dateien, Outlook, Teams, OneNote) und bild_fern.py (Fernanfrage des Live-Bilds).

  * None für jedes Laborprofil (ausdrücklich: Laborprofile haben die Rolle mitglied), für Mitglieder ohne Freischaltung und für jede
    unbekannte Rolle.
  * "admin" für die Rolle admin.
  * "mitglied" nur mit der eigenen user_id in WAMO_PC_MITGLIEDER_PROFILE (durch Komma getrennt, höchstens MAX_PC_MITGLIEDER Einträge).
    Ein einziger ungültiger Eintrag macht die ganze Liste ungültig: dann niemand (fail closed, eine Zeile im Journal). Die Liste kommt nur
    vom Server (wamo-core-env, wirkt mit dem nächsten Kern-Release); Standard leer heißt aus, so geht auch ein Pilot mit einer Person.
    Der frühere kernweite Schalter WAMO_PC_MITGLIEDER wirkt nicht mehr.

Werkzeuge: Seit dem 16.11.2026 (Entscheidung Niko zu N10) bekommt ein freigeschaltetes Mitglied für seinen eigenen Laptop dieselben
PC-Werkzeuge wie ein Admin (pc_host.werkzeuge_fuer): PowerShell lesen, Git und GitHub, Bildschirm, Live-Bild (mit Einwilligung und rotem
Rahmen am Laptop) und Office, jeweils nur mit dem Schalter am Server. Enger als bei Admins bleibt der Schutz (pc_mitglied.py): gesprochene
PC-Befehle nur mit eingelerntem Stimmabdruck (stimme_gate.pflicht_pruefen), nach Fremdinhalt eine Karte für jede Änderung am Laptop,
in actions kein Wortlaut. Admin-Rechte am Server (Geräte freigeben, Gedächtnis, Konten) hängen nie an pc_stufe, sondern an der Rolle.
"""

from __future__ import annotations

import os

from loguru import logger

import labor
from memory import normalize_uuid

ADMIN = "admin"
MITGLIED = "mitglied"
ENV_PC_MITGLIEDER = "WAMO_PC_MITGLIEDER_PROFILE"
MAX_PC_MITGLIEDER = 64  # so viele Tunnelplätze gibt es (wamo-t-01 bis wamo-t-64)
_GEMELDET: set[str] = set()


def pc_mitglieder_profile() -> frozenset[str]:
    """Die user_id der Mitglieder mit PC-Steuerung (WAMO_PC_MITGLIEDER_PROFILE), kanonisch. Leer bei fehlendem oder ungültigem Wert."""
    roh = (os.getenv(ENV_PC_MITGLIEDER) or "").strip()
    if not roh:
        return frozenset()
    gefunden: set[str] = set()
    for teil in roh.split(","):
        teil = teil.strip()
        uid = normalize_uuid(teil) if teil else None
        if uid is None:
            _einmal_melden(roh, "enthält einen ungültigen Eintrag")
            return frozenset()
        gefunden.add(uid)
    if len(gefunden) > MAX_PC_MITGLIEDER:
        _einmal_melden(roh, f"hat mehr als {MAX_PC_MITGLIEDER} Einträge")
        return frozenset()
    return frozenset(gefunden)


def _einmal_melden(roh: str, was: str) -> None:
    if roh not in _GEMELDET:
        _GEMELDET.add(roh)
        logger.error("{} {}: PC-Steuerung für Mitglieder bleibt aus", ENV_PC_MITGLIEDER, was)


def pc_stufe(identity: object) -> str | None:
    """Stufe der PC-Steuerung für eine geprüfte Identität: "admin", "mitglied" oder None (keine PC-Werkzeuge). Wirft nie."""
    if labor.ist_labor(identity):
        return None
    rolle = getattr(identity, "rolle", None)
    if rolle == ADMIN:
        return ADMIN
    if rolle == MITGLIED:
        uid = normalize_uuid(str(getattr(identity, "user_id", "") or ""))
        if uid is not None and uid in pc_mitglieder_profile():
            return MITGLIED
    return None

