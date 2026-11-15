"""PC-Steuerung für Mitglieder: Schutz vor jedem PC-Werkzeug (Plan docs/ausrollen-neue-nutzer.md 4.5 und S15, Paket P4).

Gilt nur für die Stufe "mitglied" (rechte.pc_stufe). bot.gate_pc_tools fragt vorab() nach der Prüfung "PC-Steuerung an" und vor dem Aufruf am
Laptop; davor liegt wie bei allen Werkzeugen das Gate der Stimmprüfung (stimme_gate.schemas_absichern). Die Prüfungen im Kern, in dieser
Reihenfolge, jede fail closed:

  1. Nur Werkzeuge aus pc_host.LLM_TOOLS_MITGLIED. Die Liste filtert schon der Host-Client (PcZugang.stufe); hier noch einmal, damit ein
     Fehler an anderer Stelle nie ein Admin-Werkzeug öffnet.
  2. Wartet eine Karte des Kerns noch auf den Klick, ruhen alle PC-Werkzeuge dieser Sitzung (status=wartet), wie am Host bei dessen Karten.
     So bleibt das, worauf die Karte zeigt (etwa die Nummer eines Elements oder das Fenster vorne), bis zum Klick unverändert.
  3. Pflichtstufe der Stimme (Entscheidung N10): Sprache nur mit eingelerntem Stimmabdruck und sicher erkannter Stimme, sonst nur getippt,
     unabhängig vom Modus WAMO_STIMME_PRUEFUNG (stimme_gate.StimmGate.pflicht_pruefen). Ohne Gate (darf es für Mitglieder nicht geben): nie.
  4. Fremdinhalt (Befund S15 aus dem Sicherheitsreview): Kamen im laufenden Zug Inhalte von außen ins Gespräch (Webseite, Websuche, Ergebnis
     vom Laptop, Boss, turn.tainted) oder in den letzten NACHWIRKUNG_ZUEGE Beiträgen der Person Inhalte aus echten Fremdquellen (alles außer
     den Ergebnissen ändernder Werkzeuge der Mitglieder, siehe faerben), braucht jedes ändernde Werkzeug eine Freigabekarte. Der Host führt
     die Klasse change ohne Karte aus; deshalb legt der Kern die Karte selbst an: Er merkt Werkzeug und Argumente unter einer eigenen
     Kennung vor (pc_freigaben.PcFreigaben.kern_vormerken) und gibt dem Modell status=needs_approval zurück. Die Karte baut activity.py wie
     bei Anfragen des Hosts, den Klick nimmt PcFreigaben.entscheiden an und ruft erst dann das Werkzeug am Laptop auf. Die Karte zeigt jedes
     Argument vollständig; enthält ein Argument Zeichen, die sie nicht zeigen kann (Steuer-, Format- und unsichtbare Zeichen), wird nichts
     ausgeführt. Jedes Enter steht als ⏎ da. Lesende Werkzeuge (LESEN_MITGLIED) brauchen keine Karte: Sie ändern nichts.

Jeder zugelassene Aufruf steht mit Präfix WAMO-MITGLIED, Kurzkennung des Profils und Werkzeugname im Journal des Kerns (ohne Argumente).
Kritische Aktionen, die der Host selbst zur Freigabe vorlegt (Senden mit Enter, Klick auf Senden usw.), gibt das Mitglied in seiner eigenen
Sitzung frei, nie ein Admin für einen fremden Laptop (bot.darf_pc_freigeben).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable

from loguru import logger

from activity import FREIGABE_DETAIL_ZEICHEN, karten_text
from pc_host import LLM_TOOLS_MITGLIED
from persona import sichtbar

# Werkzeuge der Mitglieder, die nur lesen (Host: Klasse read). Alles andere aus LLM_TOOLS_MITGLIED gilt als ändernd.
LESEN_MITGLIED = frozenset({"system_info", "fenster_auflisten", "elemente_auflisten", "element_lesen", "browser_lesen"})
AENDERN_MITGLIED = frozenset(w for w in LLM_TOOLS_MITGLIED if w not in LESEN_MITGLIED)
AKTION = "aendern"
GRUND_KARTE = "Änderung am Laptop nach Inhalten von außen"
GUELTIG_SECS = 300
MAX_WERT_ZEICHEN = 1500  # so viel eines einzelnen Arguments zeigt die Karte; länger heißt keine Karte und nicht ausgeführt
NACHWIRKUNG_ZUEGE = 2  # so viele weitere Beiträge der Person gilt Inhalt aus echten Fremdquellen noch für die Karte
ENTER = "⏎"
WARTET = {"status": "wartet", "summary": "Eine Freigabe wartet noch in der Oberfläche. Am Laptop passiert erst nach der Entscheidung dort "
                                         "wieder etwas."}


def _gesperrt(grund: str, hinweis: str = "Nicht erneut versuchen.") -> dict:
    return {"status": "blocked", "grund": grund, "hinweis": hinweis}


def _darstellbar(text: str) -> bool:
    """Zeigt die Karte diesen Text Zeichen für Zeichen? Nur Zeilenumbrüche (auch \\r\\n) sind erlaubt, sonst nichts, was persona.sichtbar
    verändern würde."""
    return all(sichtbar(zeile) == zeile for zeile in text.replace("\r\n", "\n").split("\n"))


def karten_detail(werkzeug: str, argumente: dict) -> str | None:
    """Was die Karte zeigt: das Werkzeug und jedes Argument in eigenen Zeilen, jedes Enter als ⏎. None, wenn etwas zu lang ist oder Zeichen
    enthält, die die Karte nicht zeigen kann: freigegeben wird nur, was ganz und genau so zu sehen ist."""
    zeilen = [f"Werkzeug: {werkzeug}"]
    for name in sorted(argumente):
        wert = argumente[name]
        text = wert if isinstance(wert, str) else json.dumps(wert, ensure_ascii=False)
        if len(text) > MAX_WERT_ZEICHEN or not _darstellbar(str(name)) or not _darstellbar(text):
            return None
        zeilen.append(f"{str(name)[:40]}: {text.replace(chr(13) + chr(10), chr(10)).replace(chr(10), ENTER + chr(10))}")
    return karten_text("\n".join(zeilen), FREIGABE_DETAIL_ZEICHEN, zeilen=True) or None


class MitgliedSchutz:
    """Schutz der PC-Werkzeuge einer Mitgliedssitzung.

    gate: das StimmGate der Sitzung (oder None, dann geht nichts); fremd(): gilt Fremdinhalt für die Karte (turn.fremd_fuer_karte);
    vormerken(kennung, werkzeug, argumente) -> bool: Freigabe des Kerns vormerken (PcFreigaben.kern_vormerken, False heißt keine Karte);
    karte_offen(): wartet eine Karte des Kerns noch (PcFreigaben.kern_offen); faerben(nachwirkend): den Zug färben (turn.taint);
    profil: Kurzkennung des Profils für das Journal (nie die volle user_id)."""

    def __init__(self, *, gate, fremd: Callable[[], bool], vormerken: Callable[[str, str, dict], bool],
                 karte_offen: Callable[[], bool] = lambda: False, faerben: Callable[[bool], None] = lambda _n: None,
                 profil: str = "?", kennung: Callable[[], str] = lambda: secrets.token_hex(8)):
        self._gate = gate
        self._fremd = fremd
        self._vormerken = vormerken
        self._karte_offen = karte_offen
        self._faerben = faerben
        self._profil = profil
        self._kennung = kennung

    def faerben(self, werkzeug: str) -> None:
        """Vor jedem Aufruf am Laptop (bot.gate_pc_tools): Das Ergebnis färbt den laufenden Zug immer. Über den Zug hinaus wirkt es nur bei
        lesenden Werkzeugen nach; die Ergebnisse ändernder Werkzeuge (Status, Fenstertitel) gelten nur im selben Zug."""
        self._faerben(werkzeug in LESEN_MITGLIED)

    async def vorab(self, werkzeug: str, argumente: dict | None) -> dict | None:
        """Vor dem Aufruf am Laptop: None = ausführen, sonst das Ergebnis für das Modell (blocked, wartet oder needs_approval)."""
        if werkzeug not in LLM_TOOLS_MITGLIED:
            logger.warning("WAMO-MITGLIED Werkzeug {} ist für Mitglieder nicht freigeschaltet (Profil {})", str(werkzeug)[:60], self._profil)
            return _gesperrt("Dieses Werkzeug ist für dein Profil nicht freigeschaltet.")
        if self._karte_offen():
            return dict(WARTET)
        if self._gate is None:
            logger.warning("WAMO-MITGLIED {} ohne Stimmprüfung gesperrt (Profil {})", werkzeug, self._profil)
            return _gesperrt("Stimmprüfung fehlt in dieser Sitzung.")
        gesperrt = await self._gate.pflicht_pruefen(werkzeug)
        if gesperrt is not None:
            return gesperrt
        if werkzeug in LESEN_MITGLIED or not self._fremd():
            logger.info("WAMO-MITGLIED Profil {} Werkzeug {}", self._profil, werkzeug)
            return None
        return self._karte(werkzeug, argumente)

    def _karte(self, werkzeug: str, argumente: dict | None) -> dict:
        args = dict(argumente) if isinstance(argumente, dict) else {}
        detail = karten_detail(werkzeug, args)
        if detail is None:
            return _gesperrt("Die Aktion ist zu lang für die Freigabekarte oder enthält Zeichen, die die Karte nicht zeigen kann.",
                             "Kürzer und nur mit sichtbaren Zeichen fassen, oder in mehreren Schritten.")
        kennung = self._kennung()
        if not self._vormerken(kennung, werkzeug, args):
            return _gesperrt("Zu viele offene Freigaben.", "Erst die offenen Karten in der Oberfläche entscheiden.")
        logger.info("WAMO-MITGLIED Profil {} Werkzeug {} nach Fremdinhalt: Freigabekarte {}", self._profil, werkzeug, kennung)
        return {
            "status": "needs_approval", "approval_id": kennung, "aktion": AKTION, "grund": GRUND_KARTE, "detail": detail,
            "gueltig_s": GUELTIG_SECS,
            "summary": "Kurz davor kamen Inhalte von außen. Diese Änderung am Laptop muss in der Oberfläche freigegeben werden.",
        }
