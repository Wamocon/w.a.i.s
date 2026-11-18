"""Kern-Kanal des WAMO-Auftragsdispatchers auf Sokrates-2 (Dispatcher Version 9).

Installiert als /opt/wamo/waechter/wamo_job_kernkanal.py (root:wamo 0640) durch wamo-job-einrichten.sh. Der Dispatcher
(wamo_job_dispatch.py) lädt dieses Modul erst, wenn er es braucht, und ruft nur die Funktionen von hier auf. Hier steht
alles, was den Kern-Kanal betrifft, damit der Dispatcher (fast 3000 Zeilen) nur dünne Einhängepunkte bekommt.

Der Kern des Sprachassistenten ruft den Dispatcher über ssh mit einem eigenen Schlüssel auf (eigene Datei
/etc/ssh/authorized_keys.d/wamo-kern). Der Dispatcher erkennt den Kanal am benutzten Schlüssel, nie an der Quelladresse:

    lokal   weder SSH_CONNECTION noch SSH_ORIGINAL_COMMAND (Betreiber, Rauchtests, Notaus)
    pc      Schlüssel aus /etc/ssh/authorized_keys.d/wamo (der Weg wie in Version 6)
    kern    Schlüssel aus /etc/ssh/authorized_keys.d/wamo-kern, gewinnt vor pc
    unklar  im strikten Modus alles andere: herkunft_unklar

Strikt heißt: die Schlüsseldatei des Kerns oder /etc/wamo/kernkanal.conf existiert (auch leer, unlesbar oder fehlerhaft).
Ohne beide Dateien kann niemand als Kern ankommen, dann gilt jeder ssh-Aufruf als pc (Verhalten wie Version 6).

Dieses Modul liest keine Geheimnisse, startet keine Prozesse und spricht kein Netz. Es hat keine Nebenwirkung beim
Import. Pfade, Dateizugriff, Uhr und freier Platz werden eingespeist (Tests). Jede Prüfung liefert None (erlaubt) oder
einen Code aus KANAL_GRUENDE; unbekannt, fehlend oder unklar heißt gesperrt (fail-closed, der Dispatcher antwortet mit
Exit 2 und dem Ereignis kanal_gesperrt). Die Codes bilden die feste Liste der Schnittstelle zum Kern.

Regeln des Kern-Kanals, in dieser Reihenfolge (jeder Verstoß ist ein Code):
    1  Notaus-Datei vorhanden                                   notaus (nur ping und status gehen noch)
    2  Konfiguration fehlerhaft, Kanal zu, Ablauf überschritten  konfig_ungueltig, kanal_zu, abgelaufen
    3  Befehlsliste (ping start status pending approve cancel)   befehl; bei geschlossenem Kanal nur ping status pending cancel
    4  nur eigene Aufträge (auftrag.json mit kanal=kern)         fremd
    5  Art, Repo, Dienste aus der Konfiguration                  art, repo, repo_fehlt, dienst
    6  Projektname kern-<Kennung>-<Name>, bei Repo genau daraus projekt
       abgeleitet; Kennung = Profil der Kopfzeile; kein Ordner
       eines anderen Profils
    7  Zugang nur "folgt" oder "haus", je mit Profil             zugang (ZUGAENGE_KERN; haus: Hausmodell über den Proxy,
                                                                der Dispatcher braucht dafür zusätzlich WAMO_HAUS=an)
    8  Fork-Prüfung beim ersten Zugriff je Lauf (fork_pruefen)   fork
    9  Grenzen je Stunde und Tag, Folgen, Abstand, Platz         grenze_start, grenze_laufzeit, grenze_folgen, abstand, platz
       und je Profil (neue Aufträge, Versuche, Laufzeit)          grenze_profil
       Auch jeder Start, der die erste Prüfung besteht, zählt als Versuch (höchstens MAX_VERSUCH_STUNDE je Stunde, fest 20, nur nach unten
       einstellbar), damit Aufträge, die an einer Sperre scheitern, nicht unbegrenzt Ordner und Logzeilen erzeugen. Der Abstand gilt nicht
       für Folgen desselben Auftrags (Abnahme-Runden), MAX_FOLGEN begrenzt sie. Ein Projektordner, den kein Auftrag mit kanal=kern angelegt
       hat, ein Ordner, den ein anderes Repo belegt hat, und ein Ordner, den ein Auftrag eines anderen Profils (oder einer ohne Profil)
       angelegt hat, sind gesperrt (projekt).

Trennung je Profil (Ausrollen P5): Die Kennung (8 Hexzeichen, die Kurzkennung der user_id, die der Kern als profil in der Kopfzeile
schickt) steht im Projektnamen (kern-<Kennung>-<Name>) und in auftrag.json. Die Grenzen je Profil (Schlüssel MAX_*_PROFIL in
kernkanal.conf, mit Standard und Bereich wie die übrigen) gelten zusätzlich zu den Gesamtgrenzen und für jedes Profil, auch für Admins;
sie zählen nur Zählerzeilen mit derselben Kennung. Die Kennung schützt gegen Fehler und Verwechslungen, nicht gegen einen kompromittierten
Kern: Der Kern setzt profil selbst, der Dispatcher kann es nicht unabhängig prüfen.

Die Fenster der Zähler gleiten (Stunde = 3600 s, Tag = 86400 s). Die Zähler stehen in /srv/wamo/logs/kernkanal.jsonl,
je Start und je Ende eine Zeile {"t", "job", "ereignis", "dauer_s" (nur bei ende), "profil" (Kennung, wenn bekannt)}.

Gleichzeitige Aufträge (Dispatcher 9, Entscheidung von Niko 16.11.2026: sechs gesamt, je Person drei). MAX_PARALLEL (1 bis PARALLEL_HART,
6 schreibt das Skript) begrenzt die gleichzeitig laufenden Aufträge aller Kanäle zusammen, MAX_PARALLEL_PROFIL (1 bis MAX_PARALLEL, 3 schreibt
das Skript; fehlen die Schlüssel in der Datei, gilt je einer) die einer
Person. Die harte Obergrenze PARALLEL_HART steht fest im Code (der Dispatcher hält dieselbe Zahl als PARALLEL_MAX), die Datei kann sie nur
senken. Person heißt: im Kern-Kanal die Kennung des Profils, im PC-Kanal (ohne Profil) alle Aufträge des PC-Kanals zusammen ("pc"), lokale
Aufrufe (Betreiber, Rauchtests) zusammen ("lokal"); alle zählen gegen die Gesamtgrenze. Ohne gültige kernkanal.conf (Stufe 0, fehlerhaft)
gilt wie bis Dispatcher 8 höchstens ein Auftrag gleichzeitig (fail closed). Ein Start an einer dieser Grenzen endet mit dem Ereignis belegt
und einem Code aus BELEGT_GRENZEN (nicht mit kanal_gesperrt: dieselbe Sperre gilt in jedem Kanal).
Bei gleichzeitigen Läufen zählt die Laufzeit je Tag (gesamt und je Profil) jeden Start ohne eigenes Ende mit dem vollen Zeitlimit eines Laufs
(laufzeit_reserve_s): ein laufender Auftrag reserviert seine Zeit, zwei gleichzeitige Starts überschreiten die Grenze so nicht gemeinsam.
Ein Start, dessen Ende nie gebucht wurde (Dispatcher mit SIGKILL beendet), zählt ebenso (fail closed), bis er aus dem Tagesfenster fällt.
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import os
import re
import shutil
import stat
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Mapping

# Feste Liste der Gründe (Schnittstelle zum Kern: voice-core/entwicklung_betrieb.py hält GRUND_SAETZE mit denselben Schlüsseln).
# Plan C (docs/persoenliche-zugaenge.md, C.2.6): persoenlich_aus (Regel 5 bei github=persoenlich ohne PERSOENLICH=an) und
# grenze_einreichen (MAX_EINREICHEN_TAG und MAX_EINREICHEN_TAG_PROFIL) liefert Paket D-a; bis dahin stehen sie nur hier.
KANAL_GRUENDE = ("notaus", "konfig_ungueltig", "kanal_zu", "abgelaufen", "befehl", "fremd", "art", "repo", "repo_fehlt",
                 "dienst", "projekt", "zugang", "fork", "herkunft_unklar", "grenze_start", "grenze_laufzeit", "grenze_folgen",
                 "abstand", "platz", "grenze_profil", "persoenlich_aus", "grenze_einreichen")
# Persönliche GitHub-Zugänge (Plan C, C.2.6), je eine feste Liste; der Kern hält GITHUB_SAETZE, AENDERUNG_SAETZE und EINREICHEN_SAETZE
# mit denselben Schlüsseln, test_kernkanal_vertrag.py hält beide Seiten gleich. Ein Code, der in zwei Listen steht, bedeutet dasselbe.
#   GITHUB_GRUENDE      Feld grund im Ereignis start_abgelehnt (Exit 8), wenn der GitHub-Teil eines Starts scheitert
#   AENDERUNG_GRUENDE   Feld gruende im Ereignis aenderung (Regeln über die Änderung, Status gesperrt)
#   EINREICHEN_GRUENDE  Feld grund im Ereignis einreichen_fehler (dort sonst nur ein Code aus KANAL_GRUENDE, beide ohne Überschneidung)
GITHUB_GRUENDE = ("github_zeile", "token_ungueltig", "token_abgelaufen", "token_rechte", "repo_nicht_erreichbar", "eigenes_repo",
                  "repo_zu_gross", "klon_fehler", "bereinigung", "projekt_gewechselt", "github_wechsel")
AENDERUNG_GRUENDE = ("pfad_gesperrt", "geheimnis", "zu_gross", "zu_viele_commits", "symlink", "sonderdatei", "basis_fehlt",
                     "bundle_ungueltig", "pruefung_fehler", "schon_eingereicht")
EINREICHEN_GRUENDE = ("zustand", "veraltet", "bestaetigung", "konto", "token_rechte", "repo_geaendert", "keine_schreibrechte",
                      "zweig_belegt", "geheimnis", "token_abgelaufen", "github_fehler")

BEFEHLE_KERN = ("ping", "start", "status", "pending", "approve", "cancel")
# Regel 7: Zugangsarten des Kerns (folgt: der eigene Zugang des Profils als zweite Zeile; haus: Hausmodell über den Proxy, kein Wert vom
# Kern). Nie server: der Zugang des Servers gilt im Kern-Kanal nicht. test_kernkanal_vertrag.py hält die Liste mit dem Dispatcher gleich.
ZUGAENGE_KERN = ("folgt", "haus")
BEFEHLE_GESCHLOSSEN = ("ping", "status", "pending", "cancel")  # bei geschlossenem oder fehlerhaftem Kanal
BEFEHLE_NOTAUS = ("ping", "status")

PRAEFIX = "kern-"
# Jeder Name, den das eigene Repo je getragen hat (bis 14.11.2026 wamo, seitdem w.a.i.s), nur ergänzen. Dieselbe Liste steht im Kern
# (voice-core/dev_guard.py) und im Dispatcher; geprüft wird allein mit ist_eigenes_repo, test_kernkanal_vertrag.py hält alle drei gleich.
SELF_REPOS = ("wamo", "w.a.i.s")
SELF_REPO = SELF_REPOS[0]  # Alias für ältere Verweise, nie zum Vergleichen
MAX_PROJEKT_ZEICHEN = 50
MAX_REPOS = 10
MAX_ABLAUF_TAGE = 400
# Versuche je Stunde für alle Profile zusammen (jeder Start, der die erste Prüfung besteht, auch wenn er später an Sperren scheitert).
# 60 seit Dispatcher 8: mit mehreren Profilen dürfen zwei Personen mit je ihrer Grenze den Admin nicht aussperren. Nur nach unten einstellbar.
MAX_VERSUCH_STUNDE_FEST = 60
# Gleichzeitige Aufträge: harte Obergrenze (wie PARALLEL_MAX im Dispatcher), kernkanal.conf kann sie nur senken. Mehr als zehn gingen nie:
# jeder Platz hat 100 eigene Entwicklungsports, der Ausgangsfilter lässt auf Loopback genau 20000 bis 20999 zu.
PARALLEL_HART = 6
# Codes im Ereignis belegt (Feld grenze; Schnittstelle zum Kern: BELEGT_SAETZE in voice-core/entwicklung_betrieb.py hat dieselben Schlüssel).
# auftrag: dieser Auftrag läuft schon, projekt: im Projekt läuft ein anderer, gesamt: alle Plätze belegt, profil: Grenze je Person erreicht.
BELEGT_GRENZEN = ("auftrag", "projekt", "gesamt", "profil")
PERSON_RE = re.compile(r"[0-9a-f]{8}|pc|lokal")  # Schlüssel der Grenze je Person: Kennung des Profils, PC-Kanal oder lokal
LAUFZEIT_RESERVE_STANDARD_S = 1800  # wie ZEITLIMIT_S in wamo-job.sh; der Dispatcher gibt das Zeitlimit aus wamo-job.conf mit
MAX_SCHLUESSELDATEI_BYTES = 256 * 1024
MAX_AUTH_BYTES = 16 * 1024
MAX_KONFIG_BYTES = 64 * 1024
MAX_ZAEHLER_BYTES = 2 * 1024 * 1024  # größere Dateien: nur das Ende wird gelesen
EREIGNISSE = ("start", "ende", "versuch")  # versuch: ein Start, der die erste Prüfung bestand (auch wenn er später an einer Sperre scheitert)
STUNDE_S = 3600
TAG_S = 86400
MIB = 1024 * 1024

JOB_RE = re.compile(r"[0-9a-f]{16,32}")
PROFIL_RE = re.compile(r"[0-9a-f]{8}")  # wie PROFIL_RE im Dispatcher und BueroZulassung.kennung im Kern
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")  # wie REPO_RE im Dispatcher
SCHLUESSEL_RE = re.compile(r"[A-Z][A-Z_]*")
ART_RE = re.compile(r"[a-z][a-z_]{1,29}")
DIENST_RE = re.compile(r"[a-z][a-z0-9_]{1,29}")
WERT_RE = re.compile(r"[ -~]*")  # druckbares ASCII
ABLAUF_RE = re.compile(r"[0-9]{8}")
GANZ_RE = re.compile(r"0|[1-9][0-9]{0,8}")
BUDGET_RE = re.compile(r"(0|[1-9][0-9]?)(\.[0-9]{1,2})?")
KEY_TYP_RE = re.compile(r"ssh-[a-z0-9-]+|ecdsa-sha2-[a-z0-9]+|sk-[a-z0-9@.-]+")
BASE64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
NORMAL_RE = re.compile(r"[^a-z0-9-]")

# Schlüssel der Konfiguration: (kleinster Wert, größter Wert) für Zahlen; Standard wie beim Anlegen durch das Skript
ZAHLEN = {"MAX_TURNS": (1, 200), "MAX_START_STUNDE": (1, 60), "MAX_START_TAG": (1, 200), "MAX_LAUFZEIT_TAG_S": (60, 86400),
          "MAX_FOLGEN": (0, 20), "MIN_ABSTAND_S": (0, 3600), "MIN_PLATZ_MB": (100, 1000000),
          "MAX_VERSUCH_STUNDE": (1, MAX_VERSUCH_STUNDE_FEST),  # Versuche je Stunde: der Wert darf den festen nur senken
          # je Profil (Dispatcher 8): neue Aufträge je Stunde und Tag (Folgen zählen nicht), Versuche je Stunde, Laufzeit je Tag
          "MAX_NEU_STUNDE_PROFIL": (1, 60), "MAX_NEU_TAG_PROFIL": (1, 200), "MAX_VERSUCH_STUNDE_PROFIL": (1, MAX_VERSUCH_STUNDE_FEST),
          "MAX_LAUFZEIT_TAG_S_PROFIL": (60, 86400),
          # gleichzeitige Aufträge (Dispatcher 9): gesamt und je Person, nie über PARALLEL_HART; je Person nie über gesamt (konfig_lesen)
          "MAX_PARALLEL": (1, PARALLEL_HART), "MAX_PARALLEL_PROFIL": (1, PARALLEL_HART)}
LISTEN = ("ARTEN", "REPOS", "DIENSTE")
BEKANNTE_SCHLUESSEL = frozenset({"KANAL", "ABLAUF", "MAX_BUDGET_USD", *ZAHLEN, *LISTEN})


@dataclass(frozen=True)
class Pfade:
    """Alle Dateien des Kern-Kanals (einspeisbar, damit Tests nie ein echtes System berühren)."""

    kern_schluessel: Path = Path("/etc/ssh/authorized_keys.d/wamo-kern")
    pc_schluessel: Path = Path("/etc/ssh/authorized_keys.d/wamo")
    konfig: Path = Path("/etc/wamo/kernkanal.conf")
    notaus: Path = Path("/etc/wamo/kernkanal.notaus")
    zaehler: Path = Path("/srv/wamo/logs/kernkanal.jsonl")
    platz: Path = Path("/srv/wamo")  # hier wird der freie Platz gemessen


PFADE = Pfade()


@dataclass(frozen=True)
class KanalErgebnis:
    kanal: str | None  # lokal, pc, kern oder None (unklar)
    strikt: bool
    grund: str | None = None  # herkunft_unklar, wenn kanal None ist


@dataclass(frozen=True)
class Konfig:
    """Regeln aus /etc/wamo/kernkanal.conf. Fehlende Zahlen gelten mit dem Standard, fehlende Listen sind leer (nichts erlaubt)."""

    kanal: str | None = None  # zu, offen oder None (fehlt: gilt als zu)
    ablauf: date | None = None
    arten: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()  # klein geschrieben
    dienste: tuple[str, ...] = ()
    max_turns: int = 40
    max_budget_usd: str = "2.00"
    max_start_stunde: int = 4
    max_start_tag: int = 8
    max_laufzeit_tag_s: int = 14400
    max_folgen: int = 5
    max_versuch_stunde: int = MAX_VERSUCH_STUNDE_FEST
    max_neu_stunde_profil: int = 3
    max_neu_tag_profil: int = 8
    max_versuch_stunde_profil: int = 10
    max_laufzeit_tag_s_profil: int = 7200
    # Fehlen die Schlüssel in der Datei (etwa nach dem Einspielen von Dispatcher 9 mit einer alten kernkanal.conf), gilt einer gleichzeitig.
    # Die Standards 6 und 3 (Entscheidung von Niko 16.11.2026) schreibt erst schluessel oder kanal (STD_MAX_PARALLEL* im Skript), also ein
    # ausdrücklicher Schritt nach Kern-Release und Rauchtest (Befund des Sicherheitsreviews).
    max_parallel: int = 1
    max_parallel_profil: int = 1
    min_abstand_s: int = 60
    min_platz_mb: int = 2048


@dataclass(frozen=True)
class KernZustand:
    """Zustand des Kanals: grund ist None, wenn er offen ist, sonst der erste Code der Regeln 1 und 2."""

    notaus: bool
    konfig: Konfig | None
    grund: str | None
    tage_rest: int | None = None


@dataclass(frozen=True)
class StartAnfrage:
    """Was ein Start im Kern-Kanal verlangt (aus Befehl und Kopfzeile; github und dienste stammen aus der Werkzeugkarte)."""

    job: str
    projekt: str
    art: str
    repo: str | None
    zugang: str | None
    profil: str | None
    github: bool  # die Art hat eine GitHub-Stufe
    dienste: tuple[str, ...]  # Dienste der Art außer GitHub
    app_modus: bool  # die GitHub-App ist eingerichtet (kein Rückfall auf einen persönlichen Token)
    # Die Lage des Auftrags und des Projektordners hat keine Vorgabe: wer eine Anfrage baut, muss sie ermitteln (nie still "frei")
    fremd: bool  # der Auftrag besteht schon und gehört nicht dem Kern-Kanal (Regel 4)
    projekt_fremd: bool  # der Projektordner besteht schon und stammt aus keinem Auftrag mit kanal=kern
    projekt_kollision: bool  # ein Kern-Auftrag hat denselben Projektordner mit einem anderen Repo belegt
    projekt_profil_fremd: bool  # ein Kern-Auftrag eines anderen Profils (oder ohne Profil) hat den Projektordner angelegt


class KonfigFehler(Exception):
    """kernkanal.conf ist unbrauchbar. Der Text nennt Schlüsselnamen, nie Werte."""

    grund = "konfig_ungueltig"


class ProjektnameFehler(ValueError):
    """Projektname nicht ableitbar: grund ist repo oder projekt."""

    def __init__(self, grund: str, text: str = ""):
        super().__init__(text or grund)
        self.grund = grund


# ---------------------------------------------------------------- Dateizugriff
def datei_lesen(pfad, limit: int) -> tuple[bytes, os.stat_result]:
    """Liest höchstens limit Bytes einer regulären Datei ohne einem Link zu folgen und ohne an einer FIFO zu hängen.
    Liefert den Inhalt und os.fstat der geöffneten Datei (Eigentümer und Rechte gehören zu genau dieser Datei)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(pfad, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(errno.EINVAL, "keine reguläre Datei")
        daten = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(daten) > limit:
        raise OSError(errno.EFBIG, "Datei zu groß")
    return daten, st


def existiert(pfad) -> bool:
    """Gibt es den Eintrag? Ein Fehler, der etwas anderes als Fehlen meldet (Rechte, Ein-/Ausgabe), gilt als vorhanden."""
    try:
        os.lstat(pfad)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return True


def _nur_eigene_datei(st: os.stat_result, uid: int | None) -> bool:
    """Gehört die Datei dem eigenen Benutzer und ist sie für Gruppe und andere nicht beschreibbar?"""
    return uid is not None and st.st_uid == uid and not (st.st_mode & 0o022)


# ---------------------------------------------------------------- Schlüssel lesen und vergleichen
def _woerter(zeile: str) -> list[str]:
    """Teilt eine Zeile an Leerraum außerhalb von Anführungszeichen (Optionen wie command="..." enthalten Leerzeichen)."""
    woerter: list[str] = []
    aktuell: list[str] = []
    in_quote = False
    for zeichen in zeile:
        if zeichen == '"':
            in_quote = not in_quote
            aktuell.append(zeichen)
        elif zeichen in " \t" and not in_quote:
            if aktuell:
                woerter.append("".join(aktuell))
                aktuell = []
        else:
            aktuell.append(zeichen)
    if aktuell:
        woerter.append("".join(aktuell))
    return woerter


def _schluessel_aus_woertern(woerter: list[str]) -> tuple[str, str] | None:
    """Das erste Paar (Typ, Base64-Teil) in einer Zeile; Optionen davor und Kommentar danach bleiben unbeachtet."""
    for i, wort in enumerate(woerter[:-1]):
        if KEY_TYP_RE.fullmatch(wort) and BASE64_RE.fullmatch(woerter[i + 1]):
            try:
                base64.b64decode(woerter[i + 1], validate=True)
            except (binascii.Error, ValueError):
                return None
            return wort, woerter[i + 1]
    return None


def schluessel_aus_text(text: str) -> set[tuple[str, str]]:
    """Alle Schlüssel einer authorized_keys-Datei als (Typ, Base64-Teil), tolerant gegenüber Optionen, Kommentaren, Leer- und
    Kommentarzeilen und kaputten Zeilen (diese zählen nicht)."""
    menge: set[tuple[str, str]] = set()
    for zeile in text.split("\n"):
        zeile = zeile.strip(" \t\r")
        if not zeile or zeile.startswith("#"):
            continue
        paar = _schluessel_aus_woertern(_woerter(zeile))
        if paar is not None:
            menge.add(paar)
    return menge


def schluessel_aus_auth(text: str) -> tuple[str, str] | None:
    """Der Schlüsselteil der Zeile "publickey <Typ> <Base64>" aus der Datei in SSH_USER_AUTH, oder None."""
    for zeile in text.split("\n"):
        woerter = zeile.strip("\r").split(" ")
        if len(woerter) >= 3 and woerter[0] == "publickey":
            paar = _schluessel_aus_woertern(woerter[1:3])
            if paar is not None:
                return paar
    return None


def _schluesselmenge(pfad, lesen: Callable) -> set[tuple[str, str]]:
    """Schlüssel einer Datei; eine fehlende Datei hat keine, jeder andere Lesefehler wird weitergegeben."""
    try:
        daten, _st = lesen(pfad, MAX_SCHLUESSELDATEI_BYTES)
    except FileNotFoundError:
        return set()
    return schluessel_aus_text(daten.decode("utf-8", "replace"))


def _benutzter_schluessel(umgebung: Mapping[str, str], lesen: Callable, uid: int | None) -> tuple[str, str] | None:
    pfad = umgebung.get("SSH_USER_AUTH")
    if not pfad:
        return None
    daten, st = lesen(pfad, MAX_AUTH_BYTES)
    if not _nur_eigene_datei(st, uid):
        return None
    return schluessel_aus_auth(daten.decode("ascii", "replace"))


def kanal_bestimmen(umgebung: Mapping[str, str], pfade: Pfade = PFADE, *, lesen: Callable = datei_lesen,
                    vorhanden: Callable = existiert, eigene_uid: int | None = None) -> KanalErgebnis:
    """Kanal der Verbindung nach der Falltabelle (siehe Kopf). umgebung ist die Umgebung des Dispatchers (nur lesend,
    dieses Modul greift nie selbst auf die Prozessumgebung zu). eigene_uid ist die Benutzerkennung des Dispatchers;
    ohne sie gibt es keine vertrauenswürdige SSH_USER_AUTH."""
    strikt = vorhanden(pfade.kern_schluessel) or vorhanden(pfade.konfig)
    if "SSH_CONNECTION" not in umgebung and "SSH_ORIGINAL_COMMAND" not in umgebung:
        return KanalErgebnis("lokal", strikt)
    if not strikt:
        return KanalErgebnis("pc", False)
    unklar = KanalErgebnis(None, True, "herkunft_unklar")
    try:
        benutzt = _benutzter_schluessel(umgebung, lesen, eigene_uid)
        kern = _schluesselmenge(pfade.kern_schluessel, lesen)
        pc = _schluesselmenge(pfade.pc_schluessel, lesen)
    except (OSError, ValueError):
        return unklar
    if benutzt is None:
        return unklar
    if benutzt in kern:
        return KanalErgebnis("kern", True)
    if benutzt in pc:
        return KanalErgebnis("pc", True)
    return unklar


# ---------------------------------------------------------------- Konfiguration
def _zahl(name: str, wert: str) -> int:
    kleinst, groesst = ZAHLEN[name]
    if not GANZ_RE.fullmatch(wert) or not kleinst <= int(wert) <= groesst:
        raise KonfigFehler(f"{name} ausserhalb des Bereichs {kleinst} bis {groesst}")
    return int(wert)


def _budget(wert: str) -> str:
    if not BUDGET_RE.fullmatch(wert):
        raise KonfigFehler("MAX_BUDGET_USD ist keine Dezimalzahl mit Punkt und höchstens zwei Stellen")
    zahl = float(wert)
    if not 0.01 <= zahl <= 20:
        raise KonfigFehler("MAX_BUDGET_USD ausserhalb des Bereichs 0.01 bis 20")
    return wert


def _liste(name: str, wert: str) -> list[str]:
    if not wert:
        return []
    teile = wert.split(",")
    if len(set(t.lower() for t in teile)) != len(teile):
        raise KonfigFehler(f"{name} enthält einen Eintrag doppelt")
    return teile


def _repos(wert: str) -> tuple[str, ...]:
    teile = _liste("REPOS", wert)
    if len(teile) > MAX_REPOS:
        raise KonfigFehler(f"REPOS hat mehr als {MAX_REPOS} Einträge")
    for repo in teile:
        name = repo.split("/", 1)[-1]
        if (not REPO_RE.fullmatch(repo) or repo.count("/") != 1 or name in (".", "..") or name.lower().endswith(".git")
                or ist_eigenes_repo(name)):
            raise KonfigFehler("REPOS enthält ein ungültiges Repo (owner/name, kein Platzhalter, nie das WAMO-Repo)")
    return tuple(r.lower() for r in teile)


def _arten(wert: str, bekannte: Iterable[str] | None) -> tuple[str, ...]:
    teile = _liste("ARTEN", wert)
    for art in teile:
        if not ART_RE.fullmatch(art) or (bekannte is not None and art not in tuple(bekannte)):
            raise KonfigFehler("ARTEN enthält eine unbekannte Art")
    return tuple(teile)


def _dienste(wert: str) -> tuple[str, ...]:
    teile = _liste("DIENSTE", wert)
    for dienst in teile:
        if not DIENST_RE.fullmatch(dienst) or dienst == "supabase":
            raise KonfigFehler("DIENSTE enthält einen unzulässigen Dienst (supabase nie)")
    return tuple(teile)


def _ablauf(wert: str, heute: date) -> date:
    if not ABLAUF_RE.fullmatch(wert):
        raise KonfigFehler("ABLAUF ist kein Datum der Form JJJJMMTT")
    try:
        tag = datetime.strptime(wert, "%Y%m%d").date()
    except ValueError:
        raise KonfigFehler("ABLAUF ist kein gültiges Datum") from None
    if tag > heute + timedelta(days=MAX_ABLAUF_TAGE):
        raise KonfigFehler(f"ABLAUF liegt mehr als {MAX_ABLAUF_TAGE} Tage voraus")
    return tag


def _heute(jetzt: float | None) -> date:
    return datetime.fromtimestamp(time.time() if jetzt is None else jetzt).date()


def konfig_lesen(pfad, *, jetzt: float | None = None, lesen: Callable = datei_lesen,
                 bekannte_arten: Iterable[str] | None = None) -> Konfig:
    """Liest und prüft die Konfiguration: Eigentümer root, für Gruppe und andere nicht beschreibbar, nur bekannte und je einmal
    vorkommende Schlüssel, alle Werte im Bereich nach I2. Jeder Mangel wirft KonfigFehler (konfig_ungueltig)."""
    try:
        daten, st = lesen(pfad, MAX_KONFIG_BYTES)
    except OSError:
        raise KonfigFehler("kernkanal.conf fehlt oder ist nicht lesbar") from None
    if len(daten) > MAX_KONFIG_BYTES:
        raise KonfigFehler("kernkanal.conf ist zu groß")
    if st.st_uid != 0:
        raise KonfigFehler("kernkanal.conf gehört nicht root")
    if st.st_mode & 0o022:
        raise KonfigFehler("kernkanal.conf ist für Gruppe oder andere beschreibbar")
    try:
        text = daten.decode("utf-8")
    except UnicodeDecodeError:
        raise KonfigFehler("kernkanal.conf ist kein UTF-8") from None
    werte: dict[str, str] = {}
    for zeile in text.split("\n"):
        zeile = zeile.strip(" \t\r")
        if not zeile or zeile.startswith("#"):
            continue
        name, gleich, wert = zeile.partition("=")
        if not gleich or not SCHLUESSEL_RE.fullmatch(name) or not WERT_RE.fullmatch(wert):
            raise KonfigFehler("kernkanal.conf hat eine Zeile ohne die Form SCHLUESSEL=wert")
        if name not in BEKANNTE_SCHLUESSEL:
            raise KonfigFehler(f"unbekannter Schlüssel {name[:40]}")
        if name in werte:
            raise KonfigFehler(f"Schlüssel {name} kommt doppelt vor")
        werte[name] = wert.strip()
    kanal = werte.get("KANAL")
    if "KANAL" in werte and kanal not in ("zu", "offen"):
        raise KonfigFehler("KANAL ist weder zu noch offen")
    standard = Konfig()
    zahlen = {n.lower(): _zahl(n, werte[n]) if n in werte else getattr(standard, n.lower()) for n in ZAHLEN}
    if "MAX_PARALLEL_PROFIL" not in werte:  # der Standard je Person gilt höchstens bis zur Gesamtgrenze
        zahlen["max_parallel_profil"] = min(zahlen["max_parallel_profil"], zahlen["max_parallel"])
    elif zahlen["max_parallel_profil"] > zahlen["max_parallel"]:
        raise KonfigFehler("MAX_PARALLEL_PROFIL ist größer als MAX_PARALLEL")
    return Konfig(
        kanal=kanal,
        ablauf=_ablauf(werte["ABLAUF"], _heute(jetzt)) if "ABLAUF" in werte else None,
        arten=_arten(werte.get("ARTEN", ""), bekannte_arten),
        repos=_repos(werte.get("REPOS", "")),
        dienste=_dienste(werte.get("DIENSTE", "")),
        max_budget_usd=_budget(werte["MAX_BUDGET_USD"]) if "MAX_BUDGET_USD" in werte else standard.max_budget_usd,
        **zahlen)


def kanal_zustand(pfade: Pfade = PFADE, *, jetzt: float | None = None, lesen: Callable = datei_lesen,
                  vorhanden: Callable = existiert, bekannte_arten: Iterable[str] | None = None) -> KernZustand:
    """Zustand des Kern-Kanals aus Notaus-Datei und Konfiguration: der erste zutreffende Grund der Regeln 1 und 2."""
    notaus = bool(vorhanden(pfade.notaus))
    try:
        konfig = konfig_lesen(pfade.konfig, jetzt=jetzt, lesen=lesen, bekannte_arten=bekannte_arten)
    except KonfigFehler:
        return KernZustand(notaus, None, "notaus" if notaus else "konfig_ungueltig")
    tage = (konfig.ablauf - _heute(jetzt)).days if konfig.ablauf is not None else None
    if notaus:
        grund = "notaus"
    elif konfig.kanal != "offen":
        grund = "kanal_zu"
    elif tage is None or tage < 0:
        grund = "abgelaufen"
    else:
        grund = None
    return KernZustand(notaus, konfig, grund, tage)


def kernkanal_bericht(zustand: KernZustand, strikt: bool) -> dict:
    """Das Objekt kernkanal der ping-Antwort. Ohne eingerichteten Kern-Kanal (nicht strikt) gibt es keinen Grund."""
    konfig = zustand.konfig
    return {"strikt": bool(strikt), "offen": bool(strikt) and zustand.grund is None,
            "grund": zustand.grund if strikt else None,
            "arten": list(konfig.arten) if konfig else [], "repos": list(konfig.repos) if konfig else [],
            "ablauf": konfig.ablauf.strftime("%Y%m%d") if konfig and konfig.ablauf else None,
            "tage_rest": zustand.tage_rest}


# ---------------------------------------------------------------- Befehle und Aufträge (Regeln 1 bis 4)
def pruefe_befehl(name: str, zustand: KernZustand) -> str | None:
    """Regeln 1 bis 3 für einen Befehl aus dem Kern-Kanal."""
    if zustand.notaus:
        return None if name in BEFEHLE_NOTAUS else "notaus"
    if zustand.grund is not None and name not in BEFEHLE_GESCHLOSSEN:
        return zustand.grund
    if name not in BEFEHLE_KERN:
        return "befehl"
    return None


def pruefe_eigener_auftrag(meta: object) -> str | None:
    """Regel 4: nur Aufträge mit kanal=kern gehören dem Kern-Kanal. Ein Auftrag ohne das Feld gehört nie dazu."""
    if isinstance(meta, dict) and meta.get("kanal") == "kern":
        return None
    return "fremd"


# ---------------------------------------------------------------- Selbstschutz: das eigene Repo unter jedem Namen
def repo_vergleichsname(wert: str) -> str:
    """Vergleichsform eines Repo-Namens: Unicode NFKC, klein (casefold), nur der Teil nach dem letzten Schrägstrich, ohne .git am
    Ende, nur a-z und 0-9. So sind w.a.i.s, W-A-I-S, w_a_i_s, wais und https://github.com/Wamocon/w.a.i.s.git gleich."""
    text = unicodedata.normalize("NFKC", wert).casefold().strip().rstrip("/")
    text = text.rsplit("/", 1)[-1]
    while text.endswith(".git"):
        text = text[:-4]
    return re.sub(r"[^a-z0-9]", "", text)


SELF_REPO_VERGLEICH = frozenset(repo_vergleichsname(n) for n in SELF_REPOS)


def ist_eigenes_repo(wert: object) -> bool:
    """True, wenn wert das eigene Repo benennt: Name, owner/name oder GitHub-Adresse, in jeder Schreibweise und unter jedem Namen aus
    SELF_REPOS. Fail-closed: was kein Text ist, gilt als das eigene Repo. Andere Namen mit demselben Anfang (wamo-extra) sind fremd."""
    if not isinstance(wert, str):
        return True
    return repo_vergleichsname(wert) in SELF_REPO_VERGLEICH


# ---------------------------------------------------------------- Projektname (I5, Regel 6)
def _normal(name: str) -> str:
    """klein, Punkt und Unterstrich zu Bindestrich, alles außerhalb a-z0-9- verwerfen, Bindestriche zusammenfassen und am Rand streichen."""
    text = NORMAL_RE.sub("", name.lower().replace(".", "-").replace("_", "-"))
    return re.sub(r"-{2,}", "-", text).strip("-")


def kern_projektname(repo: str | None, wort: str | None = None, kennung: str | None = None) -> str:
    """Projektname im Kern-Kanal: kern- plus Name, mit kennung (8 Hexzeichen, das Profil) kern-<kennung>-<Name>. Der Name kommt aus
    dem Repo (Teil nach dem Schrägstrich), sonst aus dem Projektwort. ProjektnameFehler mit grund repo (ungültiges Repo, nie das
    WAMO-Repo) oder projekt (kein Name ableitbar, ungültige Kennung, länger als 50 Zeichen mit Präfix). Dieselbe Regel und dieselbe
    Wertetabelle wie voice-core/entwicklung_betrieb.py."""
    if kennung is not None and (not isinstance(kennung, str) or not PROFIL_RE.fullmatch(kennung)):
        raise ProjektnameFehler("projekt", "Kennung des Profils ungültig")
    praefix = PRAEFIX + (f"{kennung}-" if kennung else "")
    if repo:
        if not REPO_RE.fullmatch(repo) or repo.count("/") != 1:
            raise ProjektnameFehler("repo", "Repo ungültig")
        roh = repo.split("/", 1)[1]
        name = _normal(roh)
        if ist_eigenes_repo(roh) or ist_eigenes_repo(name):
            raise ProjektnameFehler("repo", "das WAMO-Repo selbst ist gesperrt")
    else:
        name = _normal(wort or "")
        if ist_eigenes_repo(name):  # auch ohne Repo kein Projekt kern-wamo oder kern-w-a-i-s (der Kern lehnt es ebenfalls ab)
            raise ProjektnameFehler("projekt", "der Name des eigenen Repos ist gesperrt")
    if not name or len(praefix) + len(name) > MAX_PROJEKT_ZEICHEN:
        raise ProjektnameFehler("projekt", "Projektname nicht ableitbar")
    return praefix + name


def projekt_pruefen(projekt: str, repo: str | None, profil: str | None = None) -> str | None:
    """Regel 6: das Projekt beginnt mit kern-, mit gesetztem Repo ist es genau kern-<abgeleiteter Name>. Mit profil (die Kennung aus
    der Kopfzeile) gehört die Kennung dazu: kern-<profil>-<Name>; eine ungültige Kennung ist projekt. Ohne profil gilt die Regel ohne
    Kennung (ein Start ohne Profil scheitert ohnehin an Regel 7)."""
    if not projekt.startswith(PRAEFIX):
        return "projekt"
    if profil is not None and (not isinstance(profil, str) or not PROFIL_RE.fullmatch(profil)):
        return "projekt"
    if repo:
        try:
            erwartet = kern_projektname(repo, kennung=profil)
        except ProjektnameFehler as e:
            return e.grund
        return None if projekt == erwartet else "projekt"
    praefix = PRAEFIX + (f"{profil}-" if profil else "")
    if not projekt.startswith(praefix):
        return "projekt"
    rest = projekt[len(praefix):]
    if rest and not ist_eigenes_repo(rest) and _normal(rest) == rest and len(projekt) <= MAX_PROJEKT_ZEICHEN:
        return None
    return "projekt"


def profil_fremd(profil: str | None, vorhandene: Iterable[object]) -> bool:
    """Hat ein Kern-Auftrag eines anderen Profils denselben Projektordner angelegt? vorhandene: die Werte profil aus auftrag.json der
    Kern-Aufträge mit diesem Projekt. Ein Eintrag ohne gültige Kennung zählt als fremd (fail closed), ohne profil ist jeder fremd."""
    return any(not isinstance(v, str) or not PROFIL_RE.fullmatch(v) or v != profil for v in vorhandene)


def repo_kollision(repo: str | None, vorhandene: Iterable[str | None]) -> bool:
    """Teilen sich zwei verschiedene Repos einen Projektordner (my_repo und my-repo ergeben beide kern-my-repo)? True, wenn ein
    Kern-Auftrag denselben Ordner mit einem anderen, gesetzten Repo belegt hat (Vergleich ohne Groß- und Kleinschreibung)."""
    if not repo:
        return False
    return any(v and v.lower() != repo.lower() for v in vorhandene)


def pc_projekt_erlaubt(projekt: str) -> bool:
    """Der PC-Kanal darf den Namensraum kern- nicht öffnen: beide Kanäle teilen sich keinen Projektordner."""
    return not projekt.startswith(PRAEFIX)


# ---------------------------------------------------------------- Zähler (Regel 9)
def zaehler_lesen(pfad) -> list[dict]:
    """Gültige Zeilen des Zählers. Fehlt die Datei, ist er leer. Sehr große Dateien: nur das Ende (die angeschnittene erste Zeile
    fällt weg). Kaputte Zeilen zählen nicht; ein anderer Lesefehler wird weitergegeben (die Grenzen sind dann nicht prüfbar)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(pfad, flags)
    except FileNotFoundError:
        return []
    try:
        groesse = os.fstat(fd).st_size
        angeschnitten = groesse > MAX_ZAEHLER_BYTES
        if angeschnitten:
            os.lseek(fd, groesse - MAX_ZAEHLER_BYTES, os.SEEK_SET)
        daten = os.read(fd, MAX_ZAEHLER_BYTES)
    finally:
        os.close(fd)
    zeilen = daten.decode("utf-8", "replace").split("\n")
    if angeschnitten and zeilen:
        zeilen = zeilen[1:]
    ereignisse: list[dict] = []
    for zeile in zeilen:
        try:
            e = json.loads(zeile)
        except (ValueError, RecursionError):
            continue
        if not isinstance(e, dict) or not isinstance(e.get("t"), int) or isinstance(e.get("t"), bool):
            continue
        job, art, dauer = e.get("job"), e.get("ereignis"), e.get("dauer_s")
        if not isinstance(job, str) or not JOB_RE.fullmatch(job) or art not in EREIGNISSE:
            continue
        if art == "ende" and (not isinstance(dauer, int) or isinstance(dauer, bool) or dauer < 0):
            continue
        profil = e.get("profil")
        ereignisse.append({"t": e["t"], "job": job, "ereignis": art, **({"dauer_s": dauer} if art == "ende" else {}),
                           **({"profil": profil} if isinstance(profil, str) and PROFIL_RE.fullmatch(profil) else {})})
    return ereignisse


def zaehler_schreiben(pfad, job: str, ereignis: str, jetzt: float, dauer_s: int | None = None, profil: str | None = None) -> None:
    """Hängt eine Zeile an den Zähler (eine Zeile je Schreibaufruf, atomar genug für zwei Prozesse). OSError, wenn es nicht geht.
    profil: die Kennung (8 Hexzeichen) für die Grenzen je Profil, nie eine volle user_id."""
    if not JOB_RE.fullmatch(job) or ereignis not in EREIGNISSE:
        raise ValueError("Auftrag oder Ereignis ungültig")
    zeile: dict = {"t": int(jetzt), "job": job, "ereignis": ereignis}
    if dauer_s is not None:
        if not isinstance(dauer_s, int) or dauer_s < 0:
            raise ValueError("dauer_s ungültig")
        zeile["dauer_s"] = dauer_s
    if profil is not None:
        if not isinstance(profil, str) or not PROFIL_RE.fullmatch(profil):
            raise ValueError("profil ungültig")
        zeile["profil"] = profil
    daten = (json.dumps(zeile) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(pfad, flags, 0o640)
    try:
        os.write(fd, daten)
    finally:
        os.close(fd)


def freier_platz_mb(pfad) -> int | None:
    """Freier Platz in MiB, None wenn er sich nicht messen lässt."""
    try:
        return shutil.disk_usage(pfad).free // MIB
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- Gleichzeitige Aufträge (Dispatcher 9)
def parallel_grenzen(zustand: KernZustand | None, hart: int = PARALLEL_HART) -> tuple[int, int]:
    """(gesamt, je Person) für gleichzeitig laufende Aufträge aller Kanäle: aus kernkanal.conf, nie über hart. Ohne gültige Konfiguration
    (fehlt, fehlerhaft) höchstens einer gleichzeitig wie bis Dispatcher 8 (fail closed). Ein Notaus ändert die Plätze nicht: er sperrt den
    Kern-Kanal selbst, der PC-Kanal bleibt bei seinen Grenzen."""
    konfig = zustand.konfig if isinstance(zustand, KernZustand) else None
    if konfig is None:
        return 1, 1
    gesamt = max(1, min(int(hart), konfig.max_parallel))
    return gesamt, max(1, min(gesamt, konfig.max_parallel_profil))


def person_schluessel(kanal: str | None, profil: str | None) -> str | None:
    """Wer für die Grenze je Person zählt: im Kern-Kanal die Kennung des Profils (ohne gültige Kennung None, der Start scheitert), im
    PC-Kanal alle seine Aufträge zusammen (pc, auch wenn die Kopfzeile ein Profil nennt: der PC-Kanal kann es nicht belegen), lokal (Betreiber,
    Rauchtests) zusammen. Jeder andere Kanal: None."""
    if kanal == "kern":
        return profil if isinstance(profil, str) and PROFIL_RE.fullmatch(profil) else None
    return kanal if kanal in ("pc", "lokal") else None


def offene_starts(ereignisse: list[dict]) -> list[dict]:
    """Starts ohne eigenes Ende, in der Reihenfolge des Zählers: ein Ende schließt den jüngsten offenen Start desselben Auftrags (ein Auftrag
    läuft nie zweimal gleichzeitig). Übrig bleiben laufende Läufe und solche, deren Ende nie gebucht wurde (Dispatcher mit SIGKILL beendet)."""
    offen: dict[str, list[dict]] = {}
    for e in ereignisse:
        if e["ereignis"] == "start":
            offen.setdefault(e["job"], []).append(e)
        elif e["ereignis"] == "ende" and offen.get(e["job"]):
            offen[e["job"]].pop()
    return [e for liste in offen.values() for e in liste]


def laufzeit_tag(ereignisse: list[dict], jetzt: float, reserve_s: int) -> int:
    """Laufzeit des gleitenden Tages: die Dauer jedes Endes im Fenster plus reserve_s (das Zeitlimit eines Laufs) für jeden Start ohne Ende
    im Fenster. So reserviert ein laufender Auftrag seine Zeit, bis sein Ende die echte Dauer bringt."""
    if not isinstance(reserve_s, int) or isinstance(reserve_s, bool) or reserve_s < 0:
        raise ValueError("laufzeit_reserve_s ungültig")
    beendet = sum(e.get("dauer_s", 0) for e in ereignisse if e["ereignis"] == "ende" and e["t"] > jetzt - TAG_S)
    return beendet + sum(reserve_s for e in offene_starts(ereignisse) if e["t"] > jetzt - TAG_S)


def pruefe_grenzen_profil(konfig: Konfig, ereignisse: list[dict], job: str, jetzt: float, profil: str | None,
                          laufzeit_reserve_s: int = LAUFZEIT_RESERVE_STANDARD_S) -> str | None:
    """Die Grenzen je Profil (grenze_profil) aus kernkanal.conf: neue Aufträge je Stunde und Tag (gezählt wird je Auftrag nur sein erster
    Start, eine Folge ist kein neuer Auftrag), Versuche je Stunde (gilt nicht für die Folge eines eigenen Auftrags, die begrenzt MAX_FOLGEN),
    Laufzeit je Tag (laufende eigene Aufträge mit ihrem Zeitlimit, laufzeit_tag). Gezählt werden nur Zeilen mit derselben Kennung. Ohne
    gültige Kennung: grenze_profil (fail closed)."""
    if not isinstance(profil, str) or not PROFIL_RE.fullmatch(profil):
        return "grenze_profil"
    eigene = [e for e in ereignisse if e.get("profil") == profil]
    erste: dict[str, int] = {}  # Auftrag -> sein erster Start
    for e in eigene:
        if e["ereignis"] == "start":
            erste[e["job"]] = min(e["t"], erste.get(e["job"], e["t"]))
    folge = job in erste
    if not folge:
        neu_stunde = sum(1 for t in erste.values() if t > jetzt - STUNDE_S)
        neu_tag = sum(1 for t in erste.values() if t > jetzt - TAG_S)
        if neu_stunde >= konfig.max_neu_stunde_profil or neu_tag >= konfig.max_neu_tag_profil:
            return "grenze_profil"
        if sum(1 for e in eigene if e["ereignis"] == "versuch" and e["t"] > jetzt - STUNDE_S) >= konfig.max_versuch_stunde_profil:
            return "grenze_profil"
    if laufzeit_tag(eigene, jetzt, laufzeit_reserve_s) >= konfig.max_laufzeit_tag_s_profil:
        return "grenze_profil"
    return None


def pruefe_grenzen(konfig: Konfig, ereignisse: list[dict], job: str, jetzt: float, platz_mb: int | None,
                   profil: str | None, laufzeit_reserve_s: int = LAUFZEIT_RESERVE_STANDARD_S) -> str | None:
    """Regel 9 in der Reihenfolge grenze_start, grenze_laufzeit, grenze_profil, grenze_folgen, abstand, platz. Der n-te Start im
    Fenster geht, der (n+1)-te nicht (n ist die Grenze). Fenster gleiten: Stunde 3600 s, Tag 86400 s. profil: die Kennung aus der
    Kopfzeile für die Grenzen je Profil. laufzeit_reserve_s: das Zeitlimit eines Laufs (wamo-job.conf), mit dem jeder laufende Auftrag in
    der Laufzeit je Tag zählt (gleichzeitige Läufe)."""
    starts = [e for e in ereignisse if e["ereignis"] == "start"]
    in_stunde = sum(1 for e in starts if e["t"] > jetzt - STUNDE_S)
    am_tag = sum(1 for e in starts if e["t"] > jetzt - TAG_S)
    versuche = sum(1 for e in ereignisse if e["ereignis"] == "versuch" and e["t"] > jetzt - STUNDE_S)
    if in_stunde >= konfig.max_start_stunde or am_tag >= konfig.max_start_tag or versuche >= konfig.max_versuch_stunde:
        return "grenze_start"
    if laufzeit_tag(ereignisse, jetzt, laufzeit_reserve_s) >= konfig.max_laufzeit_tag_s:
        return "grenze_laufzeit"
    grund = pruefe_grenzen_profil(konfig, ereignisse, job, jetzt, profil, laufzeit_reserve_s)
    if grund is not None:
        return grund
    folge = any(e["job"] == job for e in starts)  # eine Folge desselben Auftrags (Abnahme-Runde): MAX_FOLGEN begrenzt sie, der Abstand nicht
    if sum(1 for e in starts if e["job"] == job) >= konfig.max_folgen + 1:
        return "grenze_folgen"
    laeufe = [e["t"] for e in ereignisse if e["ereignis"] in ("start", "ende")]
    if not folge and laeufe and konfig.min_abstand_s > 0 and jetzt - max(laeufe) < konfig.min_abstand_s:
        return "abstand"
    if platz_mb is None or platz_mb < konfig.min_platz_mb:
        return "platz"
    return None


# ---------------------------------------------------------------- Start: Regeln 1 bis 9
def pruefe_start(anfrage: StartAnfrage, zustand: KernZustand, *, ereignisse: list[dict] | None, jetzt: float,
                 freier_platz_mb: int | None, laufzeit_reserve_s: int = LAUFZEIT_RESERVE_STANDARD_S) -> str | None:
    """Alle Regeln, die ein Start im Kern-Kanal vor dem ersten GitHub-Zugriff erfüllen muss (Regel 8 folgt mit fork_pruefen,
    sobald es Repo-Daten gibt). ereignisse None heißt: der Zähler ist nicht lesbar. Der Dispatcher ruft das vor dem Lesen der Geheimnisse und ein zweites Mal unmittelbar vor der
    Erzeugung des GitHub-Tokens, damit eine Notaus-Datei oder eine Konfigurationsänderung dazwischen noch greift. Die zweite Prüfung und das
    Buchen des Starts laufen im Dispatcher unter einer gemeinsamen Sperre (gleichzeitige Starts sehen einander). laufzeit_reserve_s: das
    Zeitlimit eines Laufs, mit dem laufende Aufträge in der Laufzeit je Tag zählen."""
    grund = pruefe_befehl("start", zustand)
    if grund is not None:
        return grund
    konfig = zustand.konfig
    if konfig is None:  # kann nicht sein, wenn der Zustand offen ist; unklar heißt gesperrt
        return "konfig_ungueltig"
    if anfrage.fremd:
        return "fremd"
    if anfrage.art not in konfig.arten:
        return "art"
    repo = anfrage.repo
    if anfrage.github:
        if not repo:
            return "repo_fehlt"
        if repo.lower() not in konfig.repos or not anfrage.app_modus:
            return "repo"
    elif repo and repo.lower() not in konfig.repos:
        return "repo"
    for dienst in anfrage.dienste:
        if dienst == "supabase" or dienst not in konfig.dienste:
            return "dienst"
    grund = projekt_pruefen(anfrage.projekt, repo, anfrage.profil)
    if grund is not None:
        return grund
    if anfrage.projekt_fremd or anfrage.projekt_kollision or anfrage.projekt_profil_fremd:
        return "projekt"
    if anfrage.zugang not in ZUGAENGE_KERN or not anfrage.profil:
        return "zugang"
    if ereignisse is None:  # der Zähler ist nicht lesbar: die Grenzen lassen sich nicht prüfen
        return "grenze_start"
    return pruefe_grenzen(konfig, ereignisse, anfrage.job, jetzt, freier_platz_mb, anfrage.profil, laufzeit_reserve_s)


# ---------------------------------------------------------------- Regel 8: Fork-Prüfung
def _herkunft_wamo(eintrag: object) -> bool | None:
    """True, wenn ein Eintrag (parent, source, template_repository) das WAMO-Repo benennt (jeder Name aus SELF_REPOS); None, wenn er
    nicht lesbar ist."""
    if not isinstance(eintrag, dict) or not isinstance(eintrag.get("full_name"), str):
        return None
    return ist_eigenes_repo(eintrag["full_name"])


def fork_pruefen(antwort: object, repo: str | None = None) -> str | None:
    """Regel 8 über die Antwort von GitHub zu einem Repo (GET /repos/<owner>/<name>): ein Fork, ein Repo aus einer Vorlage oder
    ein Ursprung (parent, source, Vorlage) mit dem Namen wamo ist fork, ebenso jede unklare Antwort. Mit repo muss die Antwort
    zu genau diesem Repo gehören (klein verglichen)."""
    if not isinstance(antwort, dict):
        return "fork"
    voll = antwort.get("full_name")
    if not isinstance(voll, str) or (repo is not None and voll.lower() != repo.lower()):
        return "fork"
    if antwort.get("fork") is not False:  # True ist ein Fork, alles andere unklar
        return "fork"
    if antwort.get("template_repository") is not None:
        return "fork"
    for feld in ("parent", "source"):
        if antwort.get(feld) is not None and _herkunft_wamo(antwort[feld]) is not False:
            return "fork"
    return None
