"""Teams am PC (Paket 4 von docs/office-und-versand.md, Teil Teams): Nach der Freigabe öffnet W.A.I.S. den Chat in Teams mit dem Text im
Eingabefeld, die Person drückt selbst Enter. W.A.I.S. sendet in Teams nie selbst; kein Microsoft Graph, nur ein Deep Link.

Deep Link (Microsoft Learn, "Deep link to a Teams chat", Stand 26.03.2026):
  https://teams.microsoft.com/l/chat/0/0?users=<adresse1>,<adresse2>&topicName=<Gruppenname>&message=<Text>
users nimmt nur den Benutzernamen (UPN) in Form einer Mailadresse, durch Komma getrennt; die Person selbst ist immer dabei. topicName
gilt nur für Chats mit drei oder mehr Teilnehmenden, message steht als Entwurf im Eingabefeld und wird nicht gesendet. Das Protokoll
msteams:// öffnet denselben Link direkt in der Teams-App (ohne Auswahlseite im Browser); ist es nicht registriert oder scheitert der Start,
öffnet W.A.I.S. den https-Link im Standardbrowser. Eine Längengrenze nennt Microsoft nicht; Windows reicht Adressen für Protokolle und
Browser sicher bis 2083 Zeichen weiter (INTERNET_MAX_URL_LENGTH). Deshalb gelten LINK_MAX für den ganzen Link und TEXT_MAX für den Text;
ist es länger, gibt es einen Hinweis zum Kürzen, nie einen still gekürzten Text.

Empfänger: nur Mailadressen, die nicht geraten sind. Eine Adresse gilt so, wie sie genannt wurde. Einen Namen löst nur das Adressbuch des
klassischen Outlooks auf (derselbe Weg wie bei Mails, office_outlook_com._aufloesen); ist er mehrdeutig oder unbekannt, kommt eine
Rückfrage nach der Adresse, nie der erste Treffer. Läuft das klassische Outlook nicht (am PC ist meist das neue Outlook aktiv, das kein
COM hat), braucht W.A.I.S. die Adresse. Nur interne Domänen (WAMO_MAIL_INTERN oder Standard wie bei Mails, exakt gleich), höchstens
EMPFAENGER_MAX, keine Verteiler.

Text: Klartext wie auf der Karte (office_outlook._bereinigt: unsichtbare und Steuerzeichen werden Leerzeichen), jeder Wert im Link ist
einzeln kodiert, damit kein Text einen weiteren Parameter anhängen kann. Geöffnet wird nur aus wamo_host._ausfuehren nach einer Freigabe
mit Schlüssel. Dieses Modul kennt weder das Modell noch den Kern.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import office_outlook as oo

EMPFAENGER_MAX = 10
TEXT_MAX = 1000
GRUPPE_MAX = 100
LINK_MAX = 2000  # unter INTERNET_MAX_URL_LENGTH (2083), für App und Browser
KARTE_MAX = 4000  # lange Freigabekarte (höchstens office_outlook.KARTE_MAX)
WEB = "https://teams.microsoft.com/l/chat/0/0"
APP = "msteams://teams.microsoft.com/l/chat/0/0"
GRUND = "Teams-Chat mit vorbereitetem Text öffnen"
ZIEL = "Microsoft Teams"
SCHLUSS = "W.A.I.S. sendet nicht, du drückst in Teams selbst Enter."
ZU_LANG = "Zu lang für die Karte: bitte den Text kürzen oder als Mail schicken."
# Am PC geprüft (15.11.2026): Liegt im Chat schon ein eigener Entwurf, öffnet Teams den Chat und lässt diesen Entwurf stehen; der Text aus
# dem Link erscheint dann nicht (nichts wird überschrieben, nichts gesendet).
ENTWURF_HINWEIS = " Lag in diesem Chat schon ein eigener Entwurf, lässt Teams ihn stehen: dann den Text von der Karte nehmen."


class TeamsFehler(oo.MailFehler):
    """Die Teams-Nachricht kann so nicht vorbereitet oder geöffnet werden (Text ist für Menschen gedacht)."""


@dataclass(frozen=True)
class Nachricht:
    empfaenger: tuple[oo.Empfaenger, ...]
    text: str
    gruppe: str = ""


# ---------- Text und Gruppenname ----------
def text(wert: object) -> str:
    if not isinstance(wert, str) or not oo._bereinigt(wert).strip():
        raise TeamsFehler("Der Text für Teams fehlt.")
    t = oo._bereinigt(wert)
    if len(t) > TEXT_MAX:
        raise TeamsFehler(f"Der Text hat {len(t)} Zeichen, für Teams gehen höchstens {TEXT_MAX}. Bitte kürzen oder als Mail "
                          "schicken; W.A.I.S. kürzt nicht selbst.")
    return t


def gruppenname(wert: object, anzahl: int) -> str:
    """Name eines Gruppenchats (topicName), eine Zeile; nur mit mindestens zwei Empfängern (dann sind es drei Teilnehmende)."""
    if wert is None:
        return ""
    if not isinstance(wert, str):
        raise TeamsFehler("Der Gruppenname ist kein Text.")
    g = oo._zeile(wert, GRUPPE_MAX + 1)
    if g and anzahl < 2:
        raise TeamsFehler("Einen Gruppennamen gibt es nur bei mindestens zwei Empfängern.")
    if len(g) > GRUPPE_MAX:
        raise TeamsFehler(f"Der Gruppenname ist länger als {GRUPPE_MAX} Zeichen.")
    return g


# ---------- Empfänger ----------
def eingaben(an: object) -> list[str]:
    """Namen oder Adressen als Liste, 1 bis EMPFAENGER_MAX, ohne Steuerzeichen und ohne Doppelte."""
    if not isinstance(an, list) or not an:
        raise TeamsFehler("Es fehlt mindestens ein Empfänger.")
    if len(an) > EMPFAENGER_MAX:
        raise TeamsFehler(f"Höchstens {EMPFAENGER_MAX} Empfänger je Teams-Chat.")
    ergebnis: list[str] = []
    for wert in an:
        roh = " ".join(wert.split()) if isinstance(wert, str) else ""
        if not roh or len(roh) > oo.EINGABE_MAX or any(unicodedata.category(c) in oo._UNSICHTBAR for c in wert):
            raise TeamsFehler("Ein Empfänger ist ungültig (leer, zu lang oder mit Steuerzeichen).")
        if roh.lower() in (e.lower() for e in ergebnis):
            raise TeamsFehler(f"{roh[:60]} steht doppelt in der Liste.")
        ergebnis.append(roh)
    return ergebnis


def _namen_aufloesen(namen: list[str], erkennen: Callable[[], oo.Weg]) -> dict[str, oo.Empfaenger]:
    """Namen nur über das Adressbuch des laufenden klassischen Outlooks (COM, nie ein Start); sonst Rückfrage nach der Adresse."""
    if not namen:
        return {}
    if erkennen().programm != "klassisch":
        raise TeamsFehler(f"Für Teams braucht W.A.I.S. die Mailadresse von „{namen[0][:60]}“: Namen löst nur das Adressbuch des "
                          "klassischen Outlooks auf, und das läuft gerade nicht.")
    import office_outlook_com as oc  # erst hier: COM nur, wenn wirklich ein Name aufzulösen ist

    def arbeit(app) -> dict[str, oo.Empfaenger]:
        ns = app.Session
        intern = oo.interne_domaenen(oc.konto_lesen(ns)["smtp"])
        return {name: oc._aufloesen(ns, "an", name, intern) for name in namen}

    return oc.com_lauf(arbeit)


def empfaenger(an: object, erkennen: Callable[[], oo.Weg] | None = None) -> tuple[oo.Empfaenger, ...]:
    """Aufgelöste Empfänger, alle intern. erkennen: welches Outlook läuft (Standard office_outlook.erkennen, erst beim Aufruf gelesen)."""
    werte = eingaben(an)
    intern = oo.interne_domaenen()
    namen = [w for w in werte if oo.adresse(w) is None]
    aufgeloest = _namen_aufloesen(namen, erkennen or oo.erkennen)
    liste = []
    for w in werte:
        if w in aufgeloest:
            liste.append(aufgeloest[w])
        else:
            smtp = oo.adresse(w)
            liste.append(oo.Empfaenger("an", "", smtp, oo._domaene(smtp) not in intern))
    oo._keine_doppelten(liste)
    if extern := [e.smtp for e in liste if e.extern]:
        raise TeamsFehler(f"Teams-Chats öffnet W.A.I.S. nur mit internen Adressen; {extern[0][:80]} ist extern. Für Externe bitte "
                          "eine Mail schicken.")
    return tuple(liste)


# ---------- Nachricht, Link, Karte ----------
def link(n: Nachricht, *, app: bool = False) -> str:
    """Deep Link mit einzeln kodierten Werten: Adressen (nur das @ bleibt), Gruppenname und Text vollständig kodiert."""
    teile = ["users=" + ",".join(quote(e.smtp, safe="@") for e in n.empfaenger)]
    if n.gruppe:
        teile.append("topicName=" + quote(n.gruppe, safe=""))
    teile.append("message=" + quote(n.text, safe=""))
    return (APP if app else WEB) + "?" + "&".join(teile)


def nachricht(an: object, text_roh: object, gruppe_roh: object = "", *,
              erkennen: Callable[[], oo.Weg] | None = None) -> Nachricht:
    """Prüft alles, was der Link tragen soll; zu lang heißt Hinweis (TeamsFehler), nie ein gekürzter Text."""
    t = text(text_roh)
    if not isinstance(an, list) or not an:
        raise TeamsFehler("Es fehlt mindestens ein Empfänger.")
    g = gruppenname(gruppe_roh, len(an))
    n = Nachricht(empfaenger(an, erkennen), t, g)
    laenge = max(len(link(n)), len(link(n, app=True)))
    if laenge > LINK_MAX:
        raise TeamsFehler(f"Der Link für Teams wäre {laenge} Zeichen lang, erlaubt sind {LINK_MAX} (Umlaute und Sonderzeichen zählen "
                          "mehrfach). Bitte den Text kürzen oder als Mail schicken; W.A.I.S. kürzt nicht selbst.")
    return n


def kartentext(n: Nachricht, app: bool) -> str:
    """Genau das, was im Link steht. Jede Textzeile trägt "> " (sie sieht so nie wie ein Kopf aus, etwa "An: ..." im Text)."""
    wie = "die Teams-App" if app else "Teams im Browser (die Teams-App ist nicht eingerichtet)"
    zeilen = [f"So geht es: W.A.I.S. öffnet {wie} mit diesem Chat und dem Text im Eingabefeld."]
    zeilen += [f"An: {oo._mit_name(e.name, e.smtp)} ({oo._marke(e)})" for e in n.empfaenger]
    if n.gruppe:
        zeilen.append(f"Gruppenname: {n.gruppe}")
    zeilen += ["Text:", *oo._zitiert(n.text), SCHLUSS]
    return "\n".join(zeilen)


def protokoll(n: Nachricht) -> dict:
    """Für actions im Kern: nur Zahl, Domänen und ob es ein Gruppenname gibt, nie Adressen oder Text."""
    return {"an": len(n.empfaenger), "domaenen": sorted({oo._domaene(e.smtp) for e in n.empfaenger}), "gruppe": bool(n.gruppe)}


# ---------- Öffnen ----------
def verfuegbar() -> bool:
    """Kann dieser Host Teams-Chats öffnen (Windows: Teams-App oder Browser)?"""
    return sys.platform == "win32"


def app_registriert() -> bool:
    """Ist das Protokoll msteams: registriert (neues Teams: "ms-teams.exe" "%1")? Nur lesen."""
    return (oo._reg("HKCR", "msteams", "URL Protocol") is not None
            and bool(oo._reg("HKCR", r"msteams\shell\open\command", "")))


def _starten(ziel: str) -> None:
    if sys.platform != "win32":
        raise OSError("nur unter Windows")
    os.startfile(ziel)  # noqa: S606 (ShellExecute: Protokoll msteams: oder Standardbrowser, der Link ist vollständig kodiert)


def oeffnen(n: Nachricht, *, starten: Callable[[str], None] | None = None, registriert: Callable[[], bool] | None = None) -> dict:
    """Chat in der Teams-App öffnen, sonst im Browser. Gesendet wird nie: Der Text steht nur im Eingabefeld."""
    starten, registriert = starten or _starten, registriert or app_registriert
    if registriert():
        try:
            starten(link(n, app=True))
            return {"status": "success", "weg": "app", "summary": "Teams ist offen, der Text steht im Eingabefeld. Prüfen und selbst "
                    "mit Enter senden; W.A.I.S. sendet nicht." + ENTWURF_HINWEIS}
        except OSError:
            pass  # dann der Browser
    try:
        starten(link(n))
    except OSError as e:
        return {"status": "error", "summary": f"Teams ließ sich nicht öffnen ({type(e).__name__}). Es ist nichts passiert."}
    return {"status": "success", "weg": "browser", "summary": "Teams ist im Browser offen; dort die App oder Teams im Web wählen. Der "
            "Text steht im Eingabefeld. Prüfen und selbst mit Enter senden; W.A.I.S. sendet nicht." + ENTWURF_HINWEIS}
