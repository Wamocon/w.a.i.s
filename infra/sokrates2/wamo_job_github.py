"""Persönliche GitHub-Zugänge für Entwicklungsaufträge, Seite des Dispatchers (Plan C, docs/persoenliche-zugaenge.md).

Paket S: die Konstanten der Schnittstelle Kern zu Dispatcher (C.2) und die Protokoll-Klasse Werkzeuge. Paket D-b: die GitHub-Logik
(Prüfung von Token und Repo, Klon, Bereinigung, Übernahme der Sandbox-Ausgaben, Pfadregeln, Commit aus Bytes, Einreichen, Pull Request)
mit den Einstiegen start, laufende und einreichen (Abschnitt "Einstiege" unten). Über Werkzeuge nutzt sie die Dienste, die Paket D-a im
Dispatcher bereitstellt. Installiert wird die Datei wie das Modul des Kern-Kanals nach /opt/wamo/waechter/wamo_job_github.py
(root:wamo 0640, Paket D-a), daneben wamo_job_pfadregeln.py und wamo_job_auszug.py.

Die Datei ist bewusst länger als 800 Zeilen: Schnittstelle (S) und Logik (D-b) bleiben ein installiertes Modul, damit Dispatcher und
Kern-Kanal genau eine Fassung laden und prüfen; die Pfadregeln und der Auszug stehen in eigenen Modulen.

Wie wamo_job_kernkanal.py: keine Nebenwirkung beim Import, nur Standardbibliothek und die Nachbarmodule aus /opt/wamo/waechter, kein
Netz und keine Prozesse außer über Werkzeuge, keine Geheimnisse. Das Token sieht der Code dieser Datei nie: Werkzeuge.http und
Werkzeuge.git benutzen das Token des Aufrufs, das der Dispatcher als bytearray hält, und Werkzeuge.geheimnis_in sucht danach. Die Gründe (GITHUB_GRUENDE, AENDERUNG_GRUENDE, EINREICHEN_GRUENDE) stehen im Modul des
Kern-Kanals. Gegenstücke im Kern (voice-core/entwicklung_betrieb.py): FELD_GITHUB, GITHUB_PERSOENLICH, FELD_SCOPES_AUSNAHMEN,
GITHUB_TOKEN_FORMEN, GITHUB_ABLAUF_MAX_TAGE und die Listen SCOPES_*, je mit demselben Wert; voice-core/test_kernkanal_vertrag.py hält
beide Seiten gleich.

Rechte klassischer Tokens je Person (Entscheidung von Niko vom 18.11.2026, Plan C.2.8). Jeder bekannte klassische Scope steht in genau
einer von drei Listen: SCOPES_UNBEDENKLICH (immer erlaubt), SCOPES_AUSNAHMEN (standardmäßig abgelehnt, der Admin kann sie je Person
einzeln erlauben) und SCOPES_NIE (nie erlaubt). SCOPES_STANDARD_ABGELEHNT ist die strenge Liste für alle, genau SCOPES_NIE und
SCOPES_AUSNAHMEN zusammen. Ein klassisches Token ist ungültig mit dem Grund token_rechte, wenn
    keiner der Scopes aus SCOPES_PFLICHT_EINER dabei ist, oder
    ein Scope weder in SCOPES_UNBEDENKLICH noch in den Ausnahmen der Person steht.
Ein Scope, den keine Liste kennt (etwa ein neuer bei GitHub), ist damit abgelehnt und auch je Person nicht erlaubbar, bis er hier steht
(fail closed). Die Scopes kommen aus der Kopfzeile X-OAuth-Scopes von GET /user: am Komma getrennt, Leerzeichen am Rand entfernt, leere
Einträge übergangen, Groß- und Kleinschreibung zählt, höchstens SCOPES_MAX Einträge (sonst token_rechte). Die Ausnahmen der Person setzt
nur der Admin in der Oberfläche (Paket K), nur aus SCOPES_AUSNAHMEN. Der Kern schickt sie im Feld FELD_SCOPES_AUSNAHMEN der Kopfzeile von
start und der ersten Zeile von einreichen (eine JSON-Liste, sortiert, ohne Doppel; fehlt das Feld, gilt die strenge Liste). Ein Eintrag
außerhalb von SCOPES_AUSNAHMEN, ein Doppel oder ein Wert, der keine Liste von Texten ist, macht die ganze Zeile ungültig (Abgewiesen,
fail closed). Beim Speichern (Kern, C.4), bei jedem Start und bei jedem Einreichen (Dispatcher, D-b) gilt dieselbe Regel mit den
Ausnahmen von jetzt. Fein-granulare Tokens (github_pat_) haben keine Scopes in diesem Sinn: Für sie gilt das Feld nicht, sondern die
Prüfung der Rechte am Repo (permissions.pull, permissions.push) und der Hinweis auf der Karte (C.4 Schritt 3). Für beide Arten gilt die
Ablaufpflicht (GITHUB_ABLAUF_MAX_TAGE).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------- Kopfzeile von start (C.2.1) und erste Zeile von einreichen (C.2.3)
FELD_GITHUB = "github"  # einziger Wert GITHUB_PERSOENLICH, nur im Kern-Kanal, gebunden in auftrag.json
GITHUB_PERSOENLICH = "persoenlich"
FELD_SCOPES_AUSNAHMEN = "scopes_ausnahmen"  # Ausnahmen der Person von der strengen Liste (C.2.8), nur mit github=persoenlich
EINREICHEN_FELDER = ("commit_id", "tree_id", "bestaetigt", FELD_SCOPES_AUSNAHMEN)
EINREICHEN_ZEILE_MAX_BYTES = 64 * 1024

# ---------------------------------------------------------------- GitHub-Zeile auf stdin (C.2.2)
# Genau {"typ":"github","wert":"<token>"} ohne Leerzeichen, mit Zeilenende höchstens GITHUB_ZEILE_MAX_BYTES. Der Dispatcher prüft die
# Zeile ohne das Zeilenende mit GITHUB_ZEILE_RE.fullmatch auf einem memoryview seines bytearray und wandelt sie nie in str oder bytes
# (nur fullmatch(...) is not None und Positionen, nie group()). Überschreiben lässt sich das bytearray erst, wenn memoryview und
# Treffer freigegeben sind (memoryview.release(), Treffer verwerfen); das gehört zum Bytes-Leser von D-a.
GITHUB_TOKEN_FORMEN = MappingProxyType({"klassisch": "ghp_[A-Za-z0-9]{36}", "fein": "github_pat_[A-Za-z0-9_]{82}"})
GITHUB_ZEILE_RE = re.compile(rb'\{"typ":"github","wert":"(?:' + "|".join(GITHUB_TOKEN_FORMEN.values()).encode("ascii") + rb')"\}')
GITHUB_ZEILE_MAX_BYTES = 256
GITHUB_ABLAUF_MAX_TAGE = 366  # Kopfzeile GitHub-Authentication-Token-Expiration: Pflicht, höchstens so viele Tage in der Zukunft (C5)

# ---------------------------------------------------------------- Rechte klassischer Tokens je Person (C.2.8, Regel im Modultext)
SCOPES_PFLICHT_EINER = ("repo", "public_repo")
SCOPES_MAX = 30  # wie die Spalte scopes in 0027 (C.3)
# Immer erlaubt: Repo-Rechte (die Pflicht) und nur lesende oder harmlose Rechte
SCOPES_UNBEDENKLICH = ("repo", "repo:status", "repo_deployment", "public_repo", "repo:invite", "security_events", "read:org", "read:user",
                       "read:repo_hook", "read:public_key", "read:gpg_key", "read:ssh_signing_key", "read:project", "project",
                       "read:discussion", "write:discussion", "read:network_configurations", "notifications")
# Nie erlaubt, auch nicht je Person: Entscheidung vom 18.11.2026 (delete_repo, site_admin, admin:enterprise) und die Teilrechte von
# admin:enterprise
SCOPES_NIE = ("delete_repo", "site_admin", "admin:enterprise", "manage_runners:enterprise", "manage_billing:enterprise", "read:enterprise")
# Standardmäßig abgelehnt, je Person einzeln erlaubbar (die Auswahl in der Oberfläche): Entscheidung vom 18.11.2026 (admin, Pakete,
# user, workflow, gist, write:org), dazu read:packages und codespace aus C.4 Schritt 3 und nach dem Review die Rechte, die Code ausführen
# oder dauerhaften Zugriff schaffen (Runner, Hooks, Schlüssel auf dem Konto, Netzwerk, Copilot, Abrechnung, Audit-Log)
SCOPES_AUSNAHMEN = ("admin:org", "write:org", "admin:org_hook", "admin:repo_hook", "write:repo_hook", "admin:public_key", "write:public_key",
                    "admin:gpg_key", "write:gpg_key", "admin:ssh_signing_key", "write:ssh_signing_key", "write:packages", "read:packages",
                    "delete:packages", "user", "user:email", "user:follow", "workflow", "gist", "codespace", "codespace:secrets",
                    "copilot", "manage_billing:copilot", "manage_runners:org", "write:network_configurations", "audit_log",
                    "read:audit_log")
SCOPES_STANDARD_ABGELEHNT = SCOPES_NIE + SCOPES_AUSNAHMEN  # die strenge Liste für alle

# ---------------------------------------------------------------- Befehle, Ereignisse, Zustände (C.2.3, C.2.4, C.5.1)
BEFEHLE_GITHUB = ("aenderung", "einreichen", "verwerfen")  # nur im Kern-Kanal (BEFEHLE_KERN), immer mit <job> <profil>
BEFEHLE_GITHUB_GESCHLOSSEN = ("aenderung", "verwerfen")  # auch bei geschlossenem Kanal (BEFEHLE_GESCHLOSSEN), nie bei Notaus
# Ereignisse im Datenstrom ({"type": "wamo", "ereignis": ...}); dazu start_abgelehnt mit grund aus GITHUB_GRUENDE
EREIGNISSE_GITHUB = ("github", "aenderung", "eingereicht", "einreichen_fehler", "verworfen")
AENDERUNG_STATUS = ("keine", "gesperrt", "nur_lesen", "bereit", "einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen")

# ---------------------------------------------------------------- Sandbox und Sperren (C.5, C.5.2)
SANDBOX_MODI = ("lauf", "pruefen", "klon", "ausgabe", "pruefung")  # Modi von wamo-job.sh (case mit Ablehnung als Standard)
SANDBOX_MODI_NETZLOS = ("klon", "ausgabe", "pruefung")  # nur diese startet D-b über Werkzeuge.sandbox
SPERREN = (".lauf", ".einreichen", "kernkanal")  # .lauf und .einreichen im Auftragsordner, kernkanal im Sperrordner
# Einträge im Auftragsordner (für die Sandbox unsichtbar außer über die Mounts aus C.5.2), die D-b über Werkzeuge.pfad bekommt
AUFTRAG_DATEIEN = ("basis.git", "aus.git", "bundle.ein", "ausgabe", "ergebnis", "github.json", "aenderung.json", "einreichen.json")


# ---------------------------------------------------------------- Ergebnisse und Fehler der Werkzeuge
class KeinToken(Exception):
    """Der Aufruf hat kein Token (etwa am Laufende): http und git mit netz=True gehen dann nicht."""


class NetzFehler(Exception):
    """GitHub nicht erreichbar, Zeitlimit oder Antwort zu groß. Die Meldung nennt nie Werte aus Anfrage oder Antwort."""


@dataclass(frozen=True)
class HttpAntwort:
    status: int
    kopf: Mapping[str, str]  # Kopfzeilen der Antwort, Namen klein (x-oauth-scopes, github-authentication-token-expiration)
    daten: object  # JSON-Körper; None bei leerem Körper, ungültigem JSON oder zu tiefer Schachtelung


@dataclass(frozen=True)
class GitErgebnis:
    code: int
    stdout: bytes
    stderr: str  # schon geschwärzt, ohne Zeilenumbrüche, gekürzt


@dataclass(frozen=True)
class SandboxErgebnis:
    code: int
    zeitlimit: bool  # True: wamo-job.sh hat den Schritt am Zeitlimit beendet


@runtime_checkable
class Werkzeuge(Protocol):
    """Was der Dispatcher (Paket D-a) beim Aufruf der GitHub-Logik (Paket D-b) hineinreicht, je Aufruf eines Befehls ein Objekt.

    Die Umsetzung hält das Token dieses Aufrufs (bytearray, aus der GitHub-Zeile) und überschreibt es am Ende; D-b bekommt es nie zu
    sehen. Werte aus GitHub oder Sandbox gibt D-b nur geprüft weiter (C.5, gemeinsam für alle git-Aufrufe). Ereignisse schreibt D-a:
    D-b liefert ihre Felder als Ergebnis zurück."""

    def log(self, text: str, *, pflicht: bool = False) -> None:
        """Eine Zeile ins Audit-Protokoll des Dispatchers (auftraege.log). Die Umsetzung schwärzt (GH_PAT_RE, sk-ant-, die exakten Werte des
        Aufrufs), ersetzt Zeilenumbrüche und kürzt. pflicht=True: Ein Schreibfehler wirft OSError (wie log im Dispatcher)."""
        ...

    def http(self, methode: str, pfad: str, daten: Mapping[str, object] | None = None) -> HttpAntwort:
        """Eine Anfrage an api.github.com mit dem Token des Aufrufs als Bearer: methode GET oder POST, pfad beginnt mit "/" (nur druckbares
        ASCII ohne Leerraum), daten als JSON-Körper. Zertifikat geprüft, keine Weiterleitung, kein Proxy, Zeitlimit, Antwort höchstens
        256 KiB (wie die Aufrufe der App). NetzFehler bei Netz, Zeitlimit oder Größe; KeinToken ohne Token."""
        ...

    def git(self, args: tuple[str, ...], *, git_dir: Path | None, eingabe: bytes | None = None, netz: bool = False,
            zeitlimit_s: float = 60.0) -> GitErgebnis:
        """git mit der gemeinsamen Umgebung aus C.5: --git-dir=<git_dir> vor args, cwd="/", GIT_CEILING_DIRECTORIES=/, ohne System- und
        Benutzerkonfiguration, Hooks und fsmonitor aus, gc und maintenance aus, rlimits, Zeitlimit. git_dir ist ein eigenes Repo des
        Dispatchers (basis.git, aus.git), nie eines, das die Sandbox beschrieben hat; None nur für clone (das Ziel steht in args).
        args enthalten nur geprüfte Werte (Repo nach REPO_RE, Job nach JOB_RE, Commit-IDs mit 40 Hexzeichen, Zweig als refs/heads/... nach
        --end-of-options). netz=True nur für clone, ls-remote und push: mit dem festen Helfer wamo-git-zugang und dem Token des Aufrufs
        über eine Pipe, nur https zu github.com, keine Weiterleitung (KeinToken ohne Token). stderr kommt geschwärzt und gekürzt."""
        ...

    def sandbox(self, modus: str, *, job: str, projekt: str, zeitlimit_s: int) -> SandboxErgebnis:
        """Startet wamo-job.sh im Modus modus mit den Mounts aus C.5.2 und wartet auf das Ende. Nur SANDBOX_MODI_NETZLOS: lauf und
        pruefen startet der Dispatcher selbst, die Umsetzung weist sie hier ab (ValueError). Ausgaben stehen nur in den Ordnern des
        Modus (ausgabe/, ergebnis/), nie im Rückgabewert; D-b liest sie mit lstat, O_NOFOLLOW und Größengrenzen."""
        ...

    def sperre(self, name: str) -> AbstractContextManager[bool]:
        """Sperre ohne Warten (flock) für name aus SPERREN; im with-Block heißt True gehalten, False belegt. Freigabe am Ende des Blocks."""
        ...

    def pfad(self, name: str) -> Path:
        """Pfad eines Eintrags aus AUFTRAG_DATEIEN im Auftragsordner dieses Aufrufs (den Ordner prüft die Umsetzung ohne Links zu folgen,
        wie job_ordner im Dispatcher). Jeder andere Name: ValueError. Lesen und Schreiben darin übernimmt D-b mit lstat, O_NOFOLLOW und
        Größengrenzen; git_dir für Werkzeuge.git ist pfad("basis.git") oder pfad("aus.git")."""
        ...

    def uhr(self) -> float:
        """Sekunden seit der Epoche (time.time); Tests speisen eine feste Uhr ein."""
        ...

    def geheimnis_in(self, daten: bytes | bytearray | memoryview) -> bool:
        """True, wenn ein exakter Wert dieses Aufrufs in daten steht: das GitHub-Token, auch als Base64 von <benutzername>:<token> mit dem
        tatsächlich benutzten Benutzernamen (C.5 Start 4), und die Claude-Zugänge des Laufs (schwaerzungen). So prüft D-b Reste im Klon und
        die Bytes der Änderung (C.5 Laufende 4, Einreichen 4), ohne das Token zu sehen. Muster wie ghp_ oder sk-ant- prüft D-b selbst.
        daten ist ein ganzer Dateiinhalt (die Suche läuft nicht über Grenzen zwischen zwei Aufrufen)."""
        ...


# ================================================================== Paket D-b: GitHub-Logik
# Einstiege für den Dispatcher (Paket D-a), je mit einem Werkzeuge-Objekt des Aufrufs:
#   start(w, job=, repo=, art=, profil=, token_art=, scopes_ausnahmen=(), max_klon_mb=2048) -> Felder des Ereignisses github
#       C.5 Start 2 bis 4: GET /user und GET /repos/<repo> mit dem Token, Klon als bare Repo nach basis.git, Bereinigung, Prüfung auf
#       Token-Reste, github.json. Der Sandbox-Schritt klon, die Entschärfung und der Folgelauf bleiben beim Dispatcher.
#   laufende(w, job=, projekt=, art=, profil=, auftrag=, lauf=) -> Felder des Ereignisses aenderung (und aenderung.json)
#       C.5 Laufende 1 bis 5, ohne Token: Sandbox-Schritt ausgabe, Übernahme des Bundles, Sandbox-Schritt pruefung, Übernahme des
#       Ergebnisses, Pfadregeln, Commit aus geprüften Bytes in aus.git. Der Dispatcher entschärft den Projektordner vorher.
#   einreichen(w, job=, profil=, eingabe=, token_art=, kanal=, zaehlen=) -> Felder des Ereignisses eingereicht
#       C.5 Einreichen 2 bis 8 mit dem Token: Zustand, Bindung, Konto, Rechte, Repo, Geheimnissuche, ls-remote, Push mit fester Refspec,
#       Pull Request aus der Vorlage.
# Vorbedingungen, die der Dispatcher hält: Regeln 1 bis 4 des Kern-Kanals; während laufende und einreichen die Sperren .lauf und
# .einreichen dieses Auftrags (die Logik nimmt sie nicht selbst, ein zweites flock im selben Prozess wäre belegt). Jeder Fehler endet mit
# GithubAbgelehnt(grund): grund aus GITHUB_GRUENDE (start), AENDERUNG_GRUENDE (laufende, nur pruefung_fehler), EINREICHEN_GRUENDE oder
# KANAL_GRUENDE (einreichen). Andere Ausnahmen behandelt der Dispatcher als fail closed.

SELF_REPO_IDS = frozenset({1425139508})  # GitHub-ID des eigenen Repos, gleich wie im Dispatcher (test_job_github.py hält beide gleich)
API_HOST = "https://github.com"
MAX_KLON_MB_STANDARD = 2048
MAX_KLON_MB_GRENZEN = (100, 4096)  # wie MAX_KLON_MB in kernkanal.conf (C.2.7)
KLON_ZEIT_S = 300
PUSH_ZEIT_S = 120
GIT_ZEIT_S = 60
SCHRITT_ZEIT_S = 60  # Sandbox-Schritte ausgabe und pruefung
TOKEN_ARTEN = ("klassisch", "fein")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
ZWEIG_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
OID_RE = re.compile(r"[0-9a-f]{40}")
ART_RE = re.compile(r"[a-z][a-z_]{1,29}")
ABLAUF_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) (UTC|[+-][0-9]{4})")
UNGESICHERT_RE = re.compile(rb"(0|[1-9][0-9]{0,6})\n?")
KANDIDAT_REF = "refs/wamo/kandidat"
COMMITTER = b"W.A.I.S. <wais@wamocon.invalid>"
MAX_JSON_BYTES = 512 * 1024
MAX_BUNDLE_BYTES = 200 * 1024 * 1024
MAX_STATUS_BYTES = 4 * 1024
MAX_BASIS_DATEI = 16 * 1024 * 1024  # Dateien außerhalb von objects/ in basis.git (HEAD, config, packed-refs, refs/...)
MAX_BASIS_EINTRAEGE = 20_000
MAX_BAUM_TIEFE = 256
PR_PFADE_MAX = 50
TITEL_MAX = 72
TITEL_ERSATZ = "Änderung aus W.A.I.S."
# Schließwörter von GitHub (Issues schließen); sie fallen aus dem Titel, auch ohne folgendes #
SCHLIESSWOERTER_RE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b")
URL_RE = re.compile(r"(?i)\S*://\S*|\bwww\.\S+")
TITEL_ZEICHEN_RE = re.compile(r"[^A-Za-z0-9 .,;()_+-]")
UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
STATUS_LAUF = ("keine", "gesperrt", "nur_lesen", "bereit")  # aus diesen Zuständen darf laufende einen neuen Stand schreiben
STATUS_EINREICHEN = ("bereit", "einreichen_laeuft", "branch_gepusht")
LAEUFE = ("fertig", "zeitlimit", "fehler")
GITHUB_JSON_FELDER = ("v", "repo", "repo_id", "login", "konto_id", "basis", "standardzweig", "privat", "schreiben", "geklont_at")
EINREICHEN_JSON_FELDER = ("v", "job", "profil", "art", "commit_id", "tree_id", "basis", "markiert", "pfade", "dateien", "plus",
                          "minus", "titel", "zeit")

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
MIT_DIR_FD = os.open in os.supports_dir_fd and bool(O_DIRECTORY)  # Linux; unter Windows nur der Weg über Pfade (Tests)


class GithubAbgelehnt(Exception):
    """Ein Schritt des persönlichen Wegs ist gescheitert. args[0] ist genau ein Code aus den Listen der Gründe, nie ein Text mit Inhalt."""

    def __init__(self, grund: str):
        super().__init__(grund)

    @property
    def grund(self) -> str:
        return str(self.args[0])


# ---------------------------------------------------------------- Nachbarmodule (in /opt/wamo/waechter, im Repo neben dieser Datei)
def _nachbar(name: str):
    """Lädt ein Nachbarmodul erst beim ersten Gebrauch: aus sys.modules, aus dem Ordner dieser Datei oder über sys.path. So hat der
    Import dieses Moduls keine Nebenwirkung."""
    geladen = sys.modules.get(name)
    if geladen is not None:
        return geladen
    datei = Path(__file__).resolve().with_name(f"{name}.py")
    if not datei.is_file():
        return importlib.import_module(name)
    spec = importlib.util.spec_from_file_location(name, datei)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    try:
        spec.loader.exec_module(modul)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return modul


def _kernkanal():
    return _nachbar("wamo_job_kernkanal")


def _regeln():
    return _nachbar("wamo_job_pfadregeln")


def _auszug():
    return _nachbar("wamo_job_auszug")


# ---------------------------------------------------------------- Prüfungen ohne Nebenwirkung
def scopes_aus_kopf(wert: object) -> tuple[str, ...] | None:
    """X-OAuth-Scopes nach C.2.8: am Komma getrennt, Leerzeichen am Rand weg, leere Einträge übergangen. None, wenn die Kopfzeile fehlt
    oder kein Text ist."""
    if not isinstance(wert, str):
        return None
    return tuple(s.strip(" ") for s in wert.split(",") if s.strip(" "))


def ausnahmen_pruefen(wert: object) -> tuple[str, ...]:
    """Die Ausnahmen der Person (FELD_SCOPES_AUSNAHMEN): eine Liste von Texten, jeder aus SCOPES_AUSNAHMEN, ohne Doppel. Alles andere ist
    token_rechte (fail closed; der Dispatcher weist dieselbe Zeile schon vorher ab)."""
    if wert is None:
        return ()
    if not isinstance(wert, (list, tuple)) or not all(isinstance(s, str) for s in wert) or len(set(wert)) != len(wert) \
            or not set(wert) <= set(SCOPES_AUSNAHMEN):
        raise GithubAbgelehnt("token_rechte")
    return tuple(sorted(wert))


def scope_grund(scopes: Sequence[str], ausnahmen: Sequence[str] = ()) -> str | None:
    """Regel aus C.2.8 für klassische Tokens: None oder token_rechte. Ausnahmen gelten nur aus SCOPES_AUSNAHMEN, SCOPES_NIE nie."""
    erlaubt = set(SCOPES_UNBEDENKLICH) | (set(ausnahmen) & set(SCOPES_AUSNAHMEN))
    if len(scopes) > SCOPES_MAX or not set(scopes) & set(SCOPES_PFLICHT_EINER):
        return "token_rechte"
    if any(s not in erlaubt for s in scopes):
        return "token_rechte"
    return None


def ablauf_lesen(wert: object) -> datetime | None:
    """GitHub-Authentication-Token-Expiration, etwa "2026-12-31 23:59:59 UTC" oder "2026-12-31 23:59:59 +0100"; sonst None."""
    if not isinstance(wert, str):
        return None
    treffer = ABLAUF_RE.fullmatch(wert.strip())
    if treffer is None:
        return None
    zone = "+0000" if treffer.group(2) == "UTC" else treffer.group(2)
    try:
        return datetime.strptime(f"{treffer.group(1)} {zone}", "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def ablauf_grund(wert: object, jetzt: float) -> str | None:
    """Ablaufpflicht (C5): fehlt das Datum, ist es unlesbar, vorbei oder mehr als GITHUB_ABLAUF_MAX_TAGE entfernt: token_abgelaufen."""
    ablauf = ablauf_lesen(wert)
    zeit = datetime.fromtimestamp(jetzt, tz=timezone.utc)
    if ablauf is None or ablauf <= zeit or ablauf > zeit + timedelta(days=GITHUB_ABLAUF_MAX_TAGE):
        return "token_abgelaufen"
    return None


def token_grund(kopf: Mapping[str, str], token_art: str, ausnahmen: Sequence[str], jetzt: float) -> str | None:
    """Ablauf und Rechte aus den Kopfzeilen von GET /user (C.4 Schritt 3, bei jedem Start und Einreichen erneut)."""
    grund = ablauf_grund(kopf.get("github-authentication-token-expiration"), jetzt)
    if grund:
        return grund
    scopes = scopes_aus_kopf(kopf.get("x-oauth-scopes"))
    if token_art == "klassisch":
        return "token_rechte" if scopes is None else scope_grund(scopes, ausnahmen)
    if token_art == "fein":
        return "token_rechte" if scopes else None  # fein-granulare Tokens haben keine Scopes; die Rechte zeigt das Repo (permissions)
    return "token_rechte"


def konto_lesen(daten: object) -> tuple[str, int] | None:
    """(login, id) aus GET /user, nur für ein Personenkonto mit gültigem Login und ID."""
    if not isinstance(daten, dict) or daten.get("type") != "User":
        return None
    login, kennung = daten.get("login"), daten.get("id")
    if not isinstance(login, str) or not LOGIN_RE.fullmatch(login) or type(kennung) is not int or not 0 < kennung < 10 ** 12:
        return None
    return login, kennung


def zweig_gueltig(name: object) -> bool:
    """default_branch aus GitHub: [A-Za-z0-9._/-]{1,100}, ohne führendes -, ohne .., keine leeren Teile, kein Teil mit Punkt am Anfang,
    mit Punkt oder .lock am Ende (git check-ref-format)."""
    if not isinstance(name, str) or not ZWEIG_RE.fullmatch(name) or name.startswith("-") or ".." in name:
        return False
    return all(t and not t.startswith(".") and not t.endswith((".lock", ".")) for t in name.split("/"))


def _eintrag_eigen(eintrag: object) -> bool:
    """True, wenn ein Repo-Eintrag (das Repo, parent, source, template_repository) das eigene Repo ist; fail closed bei unlesbarem Eintrag."""
    if not isinstance(eintrag, dict):
        return True
    kennung = eintrag.get("id")
    if type(kennung) is int and kennung in SELF_REPO_IDS:
        return True
    return _kernkanal().ist_eigenes_repo(eintrag.get("full_name"))


def ist_eigenes_repo_antwort(daten: Mapping[str, object]) -> bool:
    """Das eigene Repo unter jedem Namen und jeder ID, auch als Fork (parent, source) oder aus der Vorlage (template_repository). Ein
    Fork ohne lesbaren Ursprung gilt als eigenes Repo (fail closed)."""
    if _eintrag_eigen(daten):
        return True
    for feld in ("parent", "source", "template_repository"):
        if daten.get(feld) is not None and _eintrag_eigen(daten[feld]):
            return True
    return daten.get("fork") is not False and (daten.get("parent") is None or daten.get("source") is None)


@dataclass(frozen=True)
class RepoDaten:
    repo_id: int
    standardzweig: str
    privat: bool
    lesen: bool
    schreiben: bool
    groesse_kb: int


def repo_lesen(daten: object, repo: str) -> RepoDaten | str:
    """GET /repos/<repo> (C.5 Start 2): RepoDaten oder ein Code (repo_nicht_erreichbar, eigenes_repo). full_name muss das Repo sein
    (GitHub vergleicht ohne Groß- und Kleinschreibung), so fällt eine Umbenennung auf."""
    if not isinstance(daten, dict) or not isinstance(daten.get("full_name"), str) or daten["full_name"].lower() != repo.lower():
        return "repo_nicht_erreichbar"
    if ist_eigenes_repo_antwort(daten):
        return "eigenes_repo"
    kennung, zweig, privat, groesse = daten.get("id"), daten.get("default_branch"), daten.get("private"), daten.get("size")
    rechte = daten.get("permissions")
    if type(kennung) is not int or not 0 < kennung < 10 ** 12 or not zweig_gueltig(zweig) or type(privat) is not bool \
            or type(groesse) is not int or groesse < 0 or not isinstance(rechte, dict):
        return "repo_nicht_erreichbar"
    return RepoDaten(repo_id=kennung, standardzweig=zweig, privat=privat, lesen=rechte.get("pull") is True,
                     schreiben=rechte.get("push") is True, groesse_kb=groesse)


def titel_bereinigen(text: object) -> str:
    """Titel aus der ersten Zeile des Auftragstexts (C.5 Laufende 5): Umlaute umschrieben, Adressen entfernt, nur ASCII-Buchstaben,
    Ziffern, Leerzeichen und . , ; ( ) - _ +, ohne Schließwörter, höchstens TITEL_MAX Zeichen; sonst TITEL_ERSATZ."""
    if not isinstance(text, str) or not text.strip():
        return TITEL_ERSATZ
    zeile = text.strip().splitlines()[0].translate(UMLAUTE)
    zeile = URL_RE.sub(" ", zeile)
    zeile = TITEL_ZEICHEN_RE.sub(" ", zeile)
    zeile = SCHLIESSWOERTER_RE.sub(" ", zeile)
    zeile = " ".join(zeile.split()).strip(" .,;-_+")
    if len(zeile) > TITEL_MAX:
        kurz = zeile[:TITEL_MAX + 1]
        zeile = (kurz.rsplit(" ", 1)[0] if " " in kurz else kurz[:TITEL_MAX]).rstrip(" .,;-_+")
    if not re.search(r"[A-Za-z0-9]", zeile) or _regeln().geheimnis_regeln(zeile.encode("ascii"), ()):
        return TITEL_ERSATZ  # ein Titel, der wie ein Schlüssel aussieht, kommt nie auf Karte, Commit oder Pull Request
    return zeile


def commit_nachricht(titel: str, job: str, art: str, login: str, profil: str) -> bytes:
    """Nachricht nur aus der Vorlage; kein Text des Agenten."""
    return (f"{titel}\n\nErstellt von W.A.I.S. im Entwicklungsauftrag {job}.\n\nWAIS-Auftrag: {job}\nWAIS-Art: {art}\n"
            f"WAIS-Beauftragt-von: {login}\nWAIS-Profil: {profil}\n").encode("utf-8")


def commit_objekt(tree: str, basis: str, login: str, konto_id: int, zeit: int, nachricht: bytes) -> bytes:
    """Rohes Commit-Objekt für hash-object -t commit: Autor die Person (noreply-Adresse aus github.json), Committer W.A.I.S., die Zeit
    einmal gesetzt. Keine Umgebung eines git-Aufrufs bestimmt Autor oder Zeit."""
    autor = f"{login} <{konto_id}+{login}@users.noreply.github.com>".encode("ascii")
    return (b"tree " + tree.encode("ascii") + b"\nparent " + basis.encode("ascii") + b"\nauthor " + autor + b" %d +0000\n" % zeit
            + b"committer " + COMMITTER + b" %d +0000\n\n" % zeit + nachricht)


def _pfad_fuer_text(pfad: str) -> str:
    return pfad.replace("@", "(at)").replace("#", "(nr)").replace("`", "'")


def pr_text(job: str, art: str, login: str, dateien: int, plus: int, minus: int, pfade: Sequence[str]) -> str:
    """Text des Pull Requests aus der Vorlage (C.5 Einreichen 7): Auftrags-ID, Art, Konto, Zahlen, höchstens PR_PFADE_MAX Pfade im
    Codeblock, nie der Auftragstext oder Text des Agenten, kein @ und kein #."""
    gezeigt = [_pfad_fuer_text(p) for p in pfade[:PR_PFADE_MAX]]
    rest = max(0, dateien - len(gezeigt))
    zaun = "`" * 3
    teile = [f"Erstellt von W.A.I.S. im Entwicklungsauftrag {job}.", "", f"- Art: {art}", f"- Konto: {login}",
             f"- Dateien: {dateien}, Zeilen: +{plus} -{minus}", "", zaun + "text", *gezeigt, zaun]
    if rest:
        teile.append(f"und {rest} weitere")
    teile += ["", "Nicht gemergt, bitte prüfen."]
    return "\n".join(teile) + "\n"


def push_ausgabe_ok(stdout: bytes, commit: str, job: str) -> bool:
    """git push --porcelain: genau eine Zeile für <commit>:refs/heads/wamo/<job>, neu (*) oder schon gleich (=); jede andere Zeile heißt
    Fehler."""
    zeilen = [z for z in stdout.decode("utf-8", "replace").splitlines() if z and not z.startswith("To ") and z != "Done"]
    if len(zeilen) != 1:
        return False
    teile = zeilen[0].split("\t")
    return len(teile) == 3 and teile[0] in ("*", "=") and teile[1] == f"{commit}:refs/heads/wamo/{job}"


def ls_remote_lesen(stdout: bytes, job: str) -> str | None | bool:
    """Ausgabe von ls-remote für refs/heads/wamo/<job>: None (fehlt), die Commit-ID, oder False (unerwartete Ausgabe)."""
    zeilen = [z for z in stdout.decode("ascii", "replace").splitlines() if z]
    if not zeilen:
        return None
    if len(zeilen) != 1:
        return False
    oid, _, ref = zeilen[0].partition("\t")
    return oid if OID_RE.fullmatch(oid) and ref == f"refs/heads/wamo/{job}" else False


# ---------------------------------------------------------------- Dateien im Auftragsordner (ohne Links zu folgen)
def datei_lesen(pfad: Path, limit: int) -> bytes | None:
    """Eine reguläre Datei ohne Link (letzter Teil), ohne an einer FIFO zu hängen, höchstens limit Bytes. None, wenn es sie nicht gibt;
    OSError bei Link, Sonderdatei, Hardlink oder Übergröße."""
    try:
        st = os.lstat(pfad)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise OSError("keine reguläre Datei")
    fd = os.open(pfad, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
            raise OSError("keine reguläre Datei oder zu groß")
        teile, gelesen = [], 0
        while gelesen <= limit:
            stueck = os.read(fd, min(limit + 1 - gelesen, 1024 * 1024))
            if not stueck:
                break
            teile.append(stueck)
            gelesen += len(stueck)
        if gelesen > limit:
            raise OSError("zu groß")
        return b"".join(teile)
    finally:
        os.close(fd)


def datei_schreiben(pfad: Path, daten: bytes, modus: int = 0o640) -> None:
    """Atomar: neue Datei mit zufälligem Namen (O_EXCL, folgt keinem Link), dann rename über das Ziel."""
    tmp = pfad.with_name(f".{pfad.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC | O_BINARY, modus)
    try:
        try:
            ansicht = memoryview(daten)
            while ansicht:
                ansicht = ansicht[os.write(fd, ansicht):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, pfad)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def json_lesen(pfad: Path, limit: int = MAX_JSON_BYTES) -> object:
    """JSON aus einer regulären Datei; None, wenn sie fehlt oder kein gültiges JSON ist. OSError bei Link oder Übergröße."""
    daten = datei_lesen(pfad, limit)
    if daten is None:
        return None
    try:
        return json.loads(daten.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def json_schreiben(pfad: Path, obj: object) -> None:
    datei_schreiben(pfad, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _baum_weg_fd(eltern_fd: int, name: str, tiefe: int) -> None:
    if tiefe > MAX_BAUM_TIEFE:
        raise OSError("zu tief")
    st = os.stat(name, dir_fd=eltern_fd, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode):
        os.unlink(name, dir_fd=eltern_fd)
        return
    flags = os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    try:
        fd = os.open(name, flags, dir_fd=eltern_fd)
    except PermissionError:  # Ordner mit 0000 aus der Sandbox: erst Rechte, dann öffnen (kein Link, siehe stat oben)
        os.chmod(name, 0o700, dir_fd=eltern_fd)
        fd = os.open(name, flags, dir_fd=eltern_fd)
    try:
        os.fchmod(fd, 0o700)  # 0555 ließe das Löschen der Einträge nicht zu
        for kind in os.listdir(fd):
            _baum_weg_fd(fd, kind, tiefe + 1)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=eltern_fd)


def _baum_weg_pfad(pfad: Path, tiefe: int) -> None:
    if tiefe > MAX_BAUM_TIEFE:
        raise OSError("zu tief")
    st = os.lstat(pfad)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        if not stat.S_ISLNK(st.st_mode):
            os.chmod(pfad, 0o600)  # Windows: schreibgeschützte Dateien (Pack-Dateien von git) lassen sich sonst nicht löschen
        os.unlink(pfad)
        return
    os.chmod(pfad, 0o700)
    for kind in os.listdir(pfad):
        _baum_weg_pfad(pfad / kind, tiefe + 1)
    os.rmdir(pfad)


def entfernen(pfad: Path) -> None:
    """Löscht eine Datei oder einen Baum im Auftragsordner, ohne einem Link zu folgen (ein Link wird nur selbst gelöscht)."""
    pfad = Path(pfad)
    try:
        os.lstat(pfad)
    except FileNotFoundError:
        return
    if MIT_DIR_FD:
        eltern = os.open(pfad.parent, os.O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        try:
            _baum_weg_fd(eltern, pfad.name, 0)
        finally:
            os.close(eltern)
    else:
        _baum_weg_pfad(pfad, 0)


def leerer_ordner(pfad: Path) -> None:
    """Ordner neu und leer (für ausgabe/ und ergebnis/ vor einem Sandbox-Schritt)."""
    entfernen(pfad)
    os.mkdir(pfad, 0o700)


# ---------------------------------------------------------------- Aufrufe über Werkzeuge
def _http(w: Werkzeuge, methode: str, pfad: str, daten: Mapping[str, object] | None = None) -> HttpAntwort | None:
    """Eine Anfrage; None bei NetzFehler oder ohne Token (das Protokoll nennt nur Methode und Pfad ohne Abfrage)."""
    try:
        return w.http(methode, pfad, daten)
    except (NetzFehler, KeinToken) as e:
        w.log(f"github http {methode} {pfad.split('?', 1)[0]} {type(e).__name__}")
        return None


def _git(w: Werkzeuge, args: tuple[str, ...], git_dir: Path | None, *, eingabe: bytes | None = None, netz: bool = False,
         zeit: float = GIT_ZEIT_S, grund: str = "pruefung_fehler") -> GitErgebnis:
    """git über Werkzeuge; ein Fehlercode oder KeinToken endet mit GithubAbgelehnt(grund)."""
    try:
        erg = w.git(args, git_dir=git_dir, eingabe=eingabe, netz=netz, zeitlimit_s=zeit)
    except KeinToken:
        raise GithubAbgelehnt(grund) from None
    if erg.code != 0:
        w.log(f"github git {args[0]} rc={erg.code} {erg.stderr[:200]}")
        raise GithubAbgelehnt(grund)
    return erg


def _oid(stdout: bytes, grund: str) -> str:
    wert = stdout.decode("ascii", "replace").strip()
    if not OID_RE.fullmatch(wert):
        raise GithubAbgelehnt(grund)
    return wert


def _ref_commit(w: Werkzeuge, git_dir: Path, ref: str, grund: str) -> str:
    """Commit-ID hinter einem Ref (rev-parse nach --end-of-options, dann der Typ mit cat-file -t)."""
    oid = _oid(_git(w, ("rev-parse", "--verify", "--quiet", "--end-of-options", ref), git_dir, grund=grund).stdout, grund)
    if _git(w, ("cat-file", "-t", oid), git_dir, grund=grund).stdout.strip() != b"commit":
        raise GithubAbgelehnt(grund)
    return oid


def _commit_tree(w: Werkzeuge, git_dir: Path, commit: str, grund: str) -> str:
    roh = _git(w, ("cat-file", "commit", commit), git_dir, grund=grund).stdout
    kopf = roh.split(b"\n", 1)[0]
    if not kopf.startswith(b"tree "):
        raise GithubAbgelehnt(grund)
    return _oid(kopf[5:], grund)


def _url(repo: str) -> str:
    return f"{API_HOST}/{repo}.git"


def repo_gueltig(repo: object) -> bool:
    """owner/name nach REPO_RE, genau ein Schrägstrich, Name weder . noch .. und ohne .git am Ende (wie _repos im Kern-Kanal)."""
    if not isinstance(repo, str) or not _kernkanal().REPO_RE.fullmatch(repo) or repo.count("/") != 1:
        return False
    name = repo.split("/", 1)[1]
    return name not in (".", "..") and not name.lower().endswith(".git")


def _pruefe_kennungen(job: object, profil: object, grund: str) -> None:
    kk = _kernkanal()
    if not isinstance(job, str) or not kk.JOB_RE.fullmatch(job) or not isinstance(profil, str) or not kk.PROFIL_RE.fullmatch(profil):
        raise GithubAbgelehnt(grund)


def _schreibend(w: Werkzeuge, art: str) -> bool:
    """Ob die Art schreibt (GitHub-Stufe schreiben in werkzeugkarte); unbekannt oder ein Fehler: nein (dann nur_lesen, mit Protokoll)."""
    try:
        return _nachbar("werkzeugkarte").github_stufe(art) == "schreiben"
    except Exception as e:  # noqa: BLE001 (fail closed: nur lesen)
        w.log(f"github werkzeugkarte für {art} nicht lesbar ({type(e).__name__}), nur lesen")
        return False


def _user_pruefen(w: Werkzeuge, token_art: str, ausnahmen: Sequence[str], *, ungueltig: str, fehler: str) -> tuple[str, int]:
    """GET /user: Konto, Ablauf und Rechte. 401 und unlesbare Konten heißen ungueltig, Netz und 5xx heißen fehler."""
    antwort = _http(w, "GET", "/user")
    if antwort is not None and antwort.status in (401, 403, 404):
        raise GithubAbgelehnt(ungueltig)
    if antwort is None or antwort.status != 200:
        raise GithubAbgelehnt(fehler)
    konto = konto_lesen(antwort.daten)
    if konto is None:
        raise GithubAbgelehnt(ungueltig)
    grund = token_grund(antwort.kopf, token_art, ausnahmen, w.uhr())
    if grund:
        raise GithubAbgelehnt(grund)
    return konto


def github_json_lesen(w: Werkzeuge, grund: str) -> dict:
    """github.json mit allen Feldern in der festen Form, sonst GithubAbgelehnt(grund)."""
    kk = _kernkanal()
    try:
        obj = json_lesen(w.pfad("github.json"), 64 * 1024)
    except OSError:
        obj = None
    if not isinstance(obj, dict) or set(obj) != set(GITHUB_JSON_FELDER) or type(obj["v"]) is not int or obj["v"] != 1:
        raise GithubAbgelehnt(grund)
    ganz = all(type(obj[k]) is int and 0 < obj[k] < 10 ** 12 for k in ("repo_id", "konto_id")) and type(obj["geklont_at"]) is int
    if not ganz or not repo_gueltig(obj["repo"]) or not isinstance(obj["login"], str) \
            or not LOGIN_RE.fullmatch(obj["login"]) or not isinstance(obj["basis"], str) or not OID_RE.fullmatch(obj["basis"]) \
            or not zweig_gueltig(obj["standardzweig"]) or type(obj["privat"]) is not bool or type(obj["schreiben"]) is not bool:
        raise GithubAbgelehnt(grund)
    return obj


def aenderung_lesen(w: Werkzeuge) -> dict:
    """aenderung.json; fehlt sie oder ist sie ungültig, gilt der Zustand keine."""
    try:
        obj = json_lesen(w.pfad("aenderung.json"))
    except OSError:
        obj = None
    if not isinstance(obj, dict) or obj.get("status") not in AENDERUNG_STATUS:
        return {"status": "keine"}
    return obj


# ---------------------------------------------------------------- Start (C.5 Start 2 bis 4)
def _basis_bereinigen(w: Werkzeuge, basis_git: Path, repo: str, zweig: str) -> None:
    """config neu, hooks/, logs/, info/, FETCH_HEAD und Verwandtes weg, keine Alternates; dann jede Datei außerhalb von objects/ auf das
    Token durchsuchen (Werkzeuge.geheimnis_in kennt auch Base64 von <benutzer>:<token>). Ein Treffer oder ein Link: bereinigung."""
    konfig = (f"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = true\n[remote \"origin\"]\n\turl = {_url(repo)}\n"
              f"\tfetch = +refs/heads/{zweig}:refs/heads/{zweig}\n").encode("ascii")
    datei_schreiben(basis_git / "config", konfig, 0o640)
    for name in ("hooks", "logs", "info", "branches", "FETCH_HEAD", "ORIG_HEAD", "description", "index"):
        entfernen(basis_git / name)
    for name in ("alternates", "http-alternates"):
        if os.path.lexists(basis_git / "objects" / "info" / name):
            raise GithubAbgelehnt("bereinigung")
    zahl = 0
    for wurzel, ordner, dateien in os.walk(basis_git, followlinks=False):
        if Path(wurzel).relative_to(basis_git).parts[:1] == ("objects",):
            ordner[:] = []
            continue
        for name in ordner + dateien:
            zahl += 1
            p = Path(wurzel) / name
            if stat.S_ISLNK(os.lstat(p).st_mode) or zahl > MAX_BASIS_EINTRAEGE:
                raise GithubAbgelehnt("bereinigung")
            if w.geheimnis_in(name.encode("utf-8", "surrogateescape")):
                raise GithubAbgelehnt("bereinigung")
            if name in dateien:
                daten = datei_lesen(p, MAX_BASIS_DATEI)
                if daten is None or w.geheimnis_in(daten):
                    raise GithubAbgelehnt("bereinigung")


def _groesse(pfad: Path) -> int:
    gesamt = 0
    for wurzel, _ordner, dateien in os.walk(pfad, followlinks=False):
        for name in dateien:
            gesamt += os.lstat(Path(wurzel) / name).st_size
    return gesamt


def _repo_holen(w: Werkzeuge, repo: str, max_klon_mb: int) -> RepoDaten:
    antwort = _http(w, "GET", f"/repos/{repo}")
    if antwort is not None and antwort.status in (301, 401, 403, 404):
        raise GithubAbgelehnt("repo_nicht_erreichbar")
    if antwort is None or antwort.status != 200:
        raise GithubAbgelehnt("klon_fehler")
    daten = repo_lesen(antwort.daten, repo)
    if isinstance(daten, str):
        raise GithubAbgelehnt(daten)
    if not daten.lesen:
        raise GithubAbgelehnt("repo_nicht_erreichbar")
    if daten.groesse_kb > max_klon_mb * 1024:  # size liefert GitHub in KB
        raise GithubAbgelehnt("repo_zu_gross")
    return daten


def start(w: Werkzeuge, *, job: str, repo: str, art: str, profil: str, token_art: str, scopes_ausnahmen: object = (),
          max_klon_mb: int = MAX_KLON_MB_STANDARD) -> dict:
    """Erster Lauf eines Auftrags mit github=persoenlich (C.5 Start 2 bis 4). Ergebnis: die Felder des Ereignisses github. Danach liegen
    basis.git (bare, bereinigt) und github.json im Auftragsordner; bei jedem Fehler ist basis.git gelöscht und github.json fehlt.
    token_art ("klassisch" oder "fein") bestimmt der Dispatcher aus dem Anfang der GitHub-Zeile (ghp_ oder github_pat_)."""
    _pruefe_kennungen(job, profil, "github_zeile")
    kk = _kernkanal()
    if isinstance(repo, str) and kk.ist_eigenes_repo(repo):  # zuerst: auch x/wais.git ist das eigene Repo, nicht nur ungültig
        raise GithubAbgelehnt("eigenes_repo")
    if not repo_gueltig(repo):
        raise GithubAbgelehnt("repo_nicht_erreichbar")
    if token_art not in TOKEN_ARTEN:
        raise GithubAbgelehnt("github_zeile")
    ausnahmen = ausnahmen_pruefen(scopes_ausnahmen)
    if type(max_klon_mb) is not int or not MAX_KLON_MB_GRENZEN[0] <= max_klon_mb <= MAX_KLON_MB_GRENZEN[1]:
        raise GithubAbgelehnt("repo_zu_gross")
    if aenderung_lesen(w)["status"] not in STATUS_LAUF:  # nie einen eingereichten Auftrag neu anfangen
        raise GithubAbgelehnt("schon_eingereicht")
    for name in ("github.json", "aenderung.json", "einreichen.json", "basis.git", "aus.git", "bundle.ein", "ausgabe", "ergebnis"):
        entfernen(w.pfad(name))
    login, konto_id = _user_pruefen(w, token_art, ausnahmen, ungueltig="token_ungueltig", fehler="klon_fehler")
    daten = _repo_holen(w, repo, max_klon_mb)
    basis_git = w.pfad("basis.git")
    try:
        _git(w, ("clone", "--bare", "--single-branch", f"--branch={daten.standardzweig}", "--no-tags", "--template=", "--",
                 _url(repo), str(basis_git)), None, netz=True, zeit=KLON_ZEIT_S, grund="klon_fehler")
        _basis_bereinigen(w, basis_git, repo, daten.standardzweig)
        basis = _ref_commit(w, basis_git, f"refs/heads/{daten.standardzweig}", "klon_fehler")
        if _groesse(basis_git) > max_klon_mb * 1024 * 1024:
            raise GithubAbgelehnt("repo_zu_gross")
        schreiben = daten.schreiben and _schreibend(w, art)
        json_schreiben(w.pfad("github.json"), {"v": 1, "repo": repo, "repo_id": daten.repo_id, "login": login, "konto_id": konto_id,
                                               "basis": basis, "standardzweig": daten.standardzweig, "privat": daten.privat,
                                               "schreiben": schreiben, "geklont_at": int(w.uhr())})
    except OSError:
        entfernen(basis_git)
        raise GithubAbgelehnt("klon_fehler") from None
    except BaseException:
        entfernen(basis_git)
        raise
    w.log(f"github start {job} repo={repo} konto={login} basis={basis} schreiben={schreiben}", pflicht=True)
    return {"repo": repo, "konto": login, "basis": basis, "standardzweig": daten.standardzweig, "privat": daten.privat,
            "schreiben": schreiben}


# ---------------------------------------------------------------- Laufende (C.5 Laufende 1 bis 5, ohne Token)
def _status_lesen(pfad: Path) -> int | None:
    """ausgabe/status.json: nur eine ganze Zahl (nicht committete Dateien), höchstens 4 KiB; sonst None."""
    try:
        daten = datei_lesen(pfad, MAX_STATUS_BYTES)
    except OSError:
        return None
    if daten is None or not UNGESICHERT_RE.fullmatch(daten):
        return None
    return int(daten)


def bundle_uebernehmen(quelle: Path, ziel: Path, limit: int = MAX_BUNDLE_BYTES) -> bool:
    """Kopiert ausgabe/aenderung.bundle nach bundle.ein (C.5 Laufende 2): lstat, O_NOFOLLOW|O_NONBLOCK, nur eine reguläre Datei mit einem
    Namen, höchstens limit Bytes. False, wenn es kein Bundle gibt; OSError bei Link, FIFO, Hardlink oder Übergröße."""
    try:
        st = os.lstat(quelle)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
        raise OSError("Bundle ungültig")
    fd = os.open(quelle, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
            raise OSError("Bundle ungültig")
        tmp = ziel.with_name(f".{ziel.name}.{secrets.token_hex(8)}.tmp")
        aus = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC | O_BINARY, 0o640)
        try:
            kopiert = 0
            try:
                while True:
                    stueck = os.read(fd, 1024 * 1024)
                    if not stueck:
                        break
                    kopiert += len(stueck)
                    if kopiert > limit:
                        raise OSError("Bundle zu groß")
                    ansicht = memoryview(stueck)
                    while ansicht:
                        ansicht = ansicht[os.write(aus, ansicht):]
            finally:
                os.close(aus)
            os.replace(tmp, ziel)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)
    return True


def _basis_baum(w: Werkzeuge, basis_git: Path, basis: str) -> dict[bytes, tuple[str, str]]:
    """Alle Einträge des Basis-Trees aus dem eigenen basis.git: Pfad (Bytes) -> (Modus, ID)."""
    roh = _git(w, ("ls-tree", "-r", "-z", "--full-tree", basis), basis_git).stdout
    out: dict[bytes, tuple[str, str]] = {}
    for eintrag in roh.split(b"\x00"):
        if not eintrag:
            continue
        kopf, tab, pfad = eintrag.partition(b"\t")
        felder = kopf.split(b" ")
        if not tab or len(felder) != 3 or not pfad or pfad in out:
            raise GithubAbgelehnt("pruefung_fehler")
        modus, oid = felder[0].decode("ascii", "replace"), felder[2].decode("ascii", "replace")
        if not re.fullmatch(r"[0-7]{6}", modus) or not OID_RE.fullmatch(oid):
            raise GithubAbgelehnt("pruefung_fehler")
        out[pfad] = (modus, oid)
    return out


def _gegen_basis(eintraege, basis: Mapping[bytes, tuple[str, str]]) -> None:
    """Die Angaben des Auszugs über die Basis müssen zum eigenen basis.git passen: neue Pfade fehlen dort, geänderte und gelöschte stehen
    dort mit genau dem alten Modus und der alten ID."""
    for e in eintraege:
        if e.art == "neu":
            stimmt = e.pfad not in basis
        else:
            stimmt = basis.get(e.pfad) == (e.alt_modus, e.alt_oid)
        if not stimmt:
            raise GithubAbgelehnt("pruefung_fehler")


def _numstat(roh: bytes) -> dict[bytes, tuple[int, int]]:
    """diff-tree -r -z --numstat: je Eintrag "<plus>\\t<minus>\\t<pfad>" mit NUL am Ende; Binärdateien (-) zählen 0."""
    out: dict[bytes, tuple[int, int]] = {}
    for eintrag in roh.split(b"\x00"):
        if not eintrag:
            continue
        teile = eintrag.split(b"\t", 2)
        if len(teile) != 3:
            raise GithubAbgelehnt("pruefung_fehler")
        zahlen = [0 if t == b"-" else int(t) if t.isdigit() else -1 for t in teile[:2]]
        if min(zahlen) < 0:
            raise GithubAbgelehnt("pruefung_fehler")
        out[teile[2]] = (zahlen[0], zahlen[1])
    return out


def _kandidat_bauen(w: Werkzeuge, g: Mapping, job: str, art: str, profil: str, titel: str, befunde, oids: Mapping[bytes, str]):
    """Commit aus geprüften Bytes in aus.git (C.5 Laufende 5): read-tree der Basis in den eigenen Index, je Datei hash-object mit den
    Bytes, update-index -z --index-info (Pfade nur über stdin, Löschungen mit Modus 0), write-tree, Abgleich mit diff-tree gegen die
    erwartete Liste, das Commit-Objekt aus der Vorlage, Ref refs/wamo/kandidat. Ergebnis: (commit, tree, numstat, zeit)."""
    regeln, auszug = _regeln(), _auszug()
    aus, basis_git, basis = w.pfad("aus.git"), w.pfad("basis.git"), g["basis"]
    entfernen(aus)
    _git(w, ("init", "--bare", "--quiet", "--template="), aus)
    os.makedirs(aus / "objects" / "info", exist_ok=True)
    datei_schreiben(aus / "objects" / "info" / "alternates", (Path(basis_git).resolve() / "objects").as_posix().encode("utf-8") + b"\n")
    _git(w, ("read-tree", basis), aus)
    loeschen, setzen, erwartet = [], [], set()
    for b in befunde:
        e = b.eintrag
        if e.art == "geloescht":
            loeschen.append(b"0 " + b"0" * 40 + b"\t" + e.pfad + b"\x00")
            erwartet.add((e.pfad, e.art, regeln.MODUS_LEER, e.alt_modus, "0" * 40))
            continue
        oid = _oid(_git(w, ("hash-object", "-w", "--no-filters", "--stdin"), aus, eingabe=e.inhalt).stdout, "pruefung_fehler")
        if oid != regeln.blob_id(e.inhalt) or oid != oids[e.pfad]:
            raise GithubAbgelehnt("pruefung_fehler")
        setzen.append(e.modus.encode("ascii") + b" " + oid.encode("ascii") + b"\t" + e.pfad + b"\x00")
        erwartet.add((e.pfad, e.art, e.modus, e.alt_modus, oid))
    _git(w, ("update-index", "-z", "--index-info"), aus, eingabe=b"".join(loeschen + setzen))
    tree = _oid(_git(w, ("write-tree",), aus).stdout, "pruefung_fehler")
    roh = _git(w, ("diff-tree", "-r", "-z", "--raw", "--no-abbrev", "--no-renames", basis, tree), aus).stdout
    try:
        gespeichert = {(d["pfad"], d["art"], d["modus"], d["alt_modus"], d["oid"]) for d in auszug.diff_lesen(roh, auszug.Grenzen())}
    except auszug.AuszugFehler:
        raise GithubAbgelehnt("pruefung_fehler") from None
    if gespeichert != erwartet:  # nur was git wirklich gespeichert hat, zählt (FP1 3.1.3, Befund 2)
        raise GithubAbgelehnt("pruefung_fehler")
    numstat = _numstat(_git(w, ("diff-tree", "-r", "-z", "--numstat", "--no-renames", basis, tree), aus).stdout)
    zeit = int(w.uhr())
    nachricht = commit_nachricht(titel, job, art, g["login"], profil)
    objekt = commit_objekt(tree, basis, g["login"], g["konto_id"], zeit, nachricht)
    commit = _oid(_git(w, ("hash-object", "-t", "commit", "-w", "--stdin"), aus, eingabe=objekt).stdout, "pruefung_fehler")
    if commit != hashlib.sha1(b"commit %d\x00" % len(objekt) + objekt).hexdigest():
        raise GithubAbgelehnt("pruefung_fehler")
    _git(w, ("update-ref", KANDIDAT_REF, commit), aus)
    return commit, tree, numstat, zeit


def _aenderung_schreiben(w: Werkzeuge, kopf: Mapping, status: str, **felder) -> dict:
    daten = {"job": kopf["job"], "status": status, "commit_id": None, "tree_id": None, "basis": kopf["basis"], "zweig": kopf["zweig"],
             "dateien": 0, "plus": 0, "minus": 0, "liste": [], "nicht_gelistet": 0, "gruende": [], "ungesichert": 0,
             "lauf": kopf["lauf"], "titel": kopf["titel"], "pr": None, "adresse": None}
    daten.update(felder)
    json_schreiben(w.pfad("aenderung.json"), daten)
    w.log(f"aenderung {kopf['job']} status={status} dateien={daten['dateien']} gruende={','.join(daten['gruende']) or '-'}")
    return daten


def _ausgabe_uebernehmen(w: Werkzeuge, job: str, projekt: str) -> tuple[bool, int]:
    """Sandbox-Schritt ausgabe und Übernahme: (Bundle vorhanden, Zahl nicht committeter Dateien). GithubAbgelehnt mit dem Grund, der im
    Ereignis steht (pruefung_fehler, bundle_ungueltig)."""
    ausgabe = w.pfad("ausgabe")
    leerer_ordner(ausgabe)
    try:
        erg = w.sandbox("ausgabe", job=job, projekt=projekt, zeitlimit_s=SCHRITT_ZEIT_S)
        if erg.code != 0 or erg.zeitlimit:
            raise GithubAbgelehnt("pruefung_fehler")
        ungesichert = _status_lesen(ausgabe / "status.json")
        if ungesichert is None:
            raise GithubAbgelehnt("pruefung_fehler")
        try:
            vorhanden = bundle_uebernehmen(ausgabe / "aenderung.bundle", w.pfad("bundle.ein"))
        except OSError:
            raise GithubAbgelehnt("bundle_ungueltig") from None
        if not vorhanden:
            entfernen(w.pfad("bundle.ein"))  # keine Commits auf wamo/<job>: auch kein früheres Bundle mehr
        return vorhanden, ungesichert
    finally:
        entfernen(ausgabe)


def _pruefung(w: Werkzeuge, job: str, projekt: str, basis: str):
    """Sandbox-Schritt pruefung und Übernahme des Ergebnisses (wamo_job_auszug.ergebnis_lesen)."""
    auszug = _auszug()
    leerer_ordner(w.pfad("ergebnis"))
    erg = w.sandbox("pruefung", job=job, projekt=projekt, zeitlimit_s=SCHRITT_ZEIT_S)
    if erg.code != 0 or erg.zeitlimit:
        raise GithubAbgelehnt("pruefung_fehler")
    try:
        ergebnis = auszug.ergebnis_lesen(w.pfad("ergebnis"), job=job, basis=basis)
    except auszug.AuszugFehler:
        raise GithubAbgelehnt("pruefung_fehler") from None
    if ergebnis.status != "ok":
        raise GithubAbgelehnt(ergebnis.grund if ergebnis.grund in _kernkanal().AENDERUNG_GRUENDE else "pruefung_fehler")
    return ergebnis


def _regeln_anwenden(w: Werkzeuge, ergebnis, basis_eintraege):
    regeln = _regeln()
    eintraege = [regeln.Eintrag(pfad=e.pfad, art=e.art, modus=e.modus, alt_modus=e.alt_modus, inhalt=e.inhalt) for e in ergebnis.eintraege]
    try:
        return regeln.pruefen(eintraege, basis_eintraege.keys(), geheimnis_in=w.geheimnis_in)
    except regeln.PruefFehler:
        raise GithubAbgelehnt("pruefung_fehler") from None


def laufende(w: Werkzeuge, *, job: str, projekt: str, art: str, profil: str, auftrag: object, lauf: str) -> dict:
    """Am Laufende ohne Token (C.5 Laufende 1 bis 5). Ergebnis: die Felder des Ereignisses aenderung, genauso in aenderung.json. Ein Regel-
    verstoß ergibt den Status gesperrt mit Gründen, nie einen Kandidaten. Aus einreichen_laeuft, branch_gepusht, eingereicht und
    verworfen ändert sich nichts (der Zustand wird nie überschrieben). Vorbedingung: der Dispatcher hat den Projektordner entschärft."""
    _pruefe_kennungen(job, profil, "pruefung_fehler")
    if not isinstance(art, str) or not ART_RE.fullmatch(art) or not isinstance(projekt, str):
        raise GithubAbgelehnt("pruefung_fehler")
    g = github_json_lesen(w, "pruefung_fehler")
    vorher = aenderung_lesen(w)
    if vorher["status"] not in STATUS_LAUF:
        w.log(f"aenderung {job}: Zustand {vorher['status']} bleibt")
        return vorher
    kopf = {"job": job, "basis": g["basis"], "zweig": f"wamo/{job}", "lauf": lauf if lauf in LAEUFE else "fehler",
            "titel": titel_bereinigen(auftrag)}
    for name in ("einreichen.json", "aus.git"):  # ein früherer Kandidat gilt ab jetzt nicht mehr
        entfernen(w.pfad(name))
    if not g["schreiben"]:
        return _aenderung_schreiben(w, kopf, "nur_lesen")
    ungesichert = 0
    try:
        vorhanden, ungesichert = _ausgabe_uebernehmen(w, job, projekt)
        if not vorhanden:
            return _aenderung_schreiben(w, kopf, "keine", ungesichert=ungesichert)
        ergebnis = _pruefung(w, job, projekt, g["basis"])
        basis_eintraege = _basis_baum(w, w.pfad("basis.git"), g["basis"])
        _gegen_basis(ergebnis.eintraege, basis_eintraege)
        pruefung = _regeln_anwenden(w, ergebnis, basis_eintraege)
    except GithubAbgelehnt as e:
        return _aenderung_schreiben(w, kopf, "gesperrt", gruende=[e.grund], ungesichert=ungesichert)
    except OSError:
        return _aenderung_schreiben(w, kopf, "gesperrt", gruende=["pruefung_fehler"], ungesichert=ungesichert)
    try:
        return _kandidat_und_karte(w, g, kopf, art, profil, pruefung, ergebnis, ungesichert)
    except (GithubAbgelehnt, OSError) as e:
        for name in ("einreichen.json", "aus.git"):
            entfernen(w.pfad(name))
        grund = e.grund if isinstance(e, GithubAbgelehnt) else "pruefung_fehler"
        return _aenderung_schreiben(w, kopf, "gesperrt", gruende=[grund], ungesichert=ungesichert)


def _kandidat_und_karte(w: Werkzeuge, g: Mapping, kopf: Mapping, art: str, profil: str, pruefung, ergebnis, ungesichert: int) -> dict:
    regeln = _regeln()
    job = kopf["job"]
    if pruefung.gesperrt:
        liste, nicht_gelistet = regeln.liste_bauen(pruefung, {})
        return _aenderung_schreiben(w, kopf, "gesperrt", gruende=list(pruefung.gruende), dateien=len(pruefung.befunde), liste=liste,
                                    nicht_gelistet=nicht_gelistet, ungesichert=ungesichert)
    if not pruefung.befunde:
        return _aenderung_schreiben(w, kopf, "keine", ungesichert=ungesichert)
    oids = {e.pfad: e.oid for e in ergebnis.eintraege}
    commit, tree, numstat, zeit = _kandidat_bauen(w, g, job, art, profil, kopf["titel"], pruefung.befunde, oids)
    zahlen = {regeln.pfad_anzeige(p): z for p, z in numstat.items()}
    liste, nicht_gelistet = regeln.liste_bauen(pruefung, zahlen)
    plus, minus = sum(z[0] for z in numstat.values()), sum(z[1] for z in numstat.values())
    geordnet = [e["pfad"] for e in liste]
    json_schreiben(w.pfad("einreichen.json"), {"v": 1, "job": job, "profil": profil, "art": art, "commit_id": commit, "tree_id": tree,
                                               "basis": g["basis"], "markiert": regeln.sensible_pfade(pruefung),
                                               "pfade": geordnet[:PR_PFADE_MAX], "dateien": len(pruefung.befunde), "plus": plus,
                                               "minus": minus, "titel": kopf["titel"], "zeit": zeit})
    return _aenderung_schreiben(w, kopf, "bereit", commit_id=commit, tree_id=tree, dateien=len(pruefung.befunde), plus=plus,
                                minus=minus, liste=liste, nicht_gelistet=nicht_gelistet, ungesichert=ungesichert)


# ---------------------------------------------------------------- Einreichen (C.5 Einreichen 2 bis 8)
def _einreichen_json_lesen(w: Werkzeuge) -> dict:
    try:
        obj = json_lesen(w.pfad("einreichen.json"), 256 * 1024)
    except OSError:
        obj = None
    def texte(wert: object, hoechstens: int) -> bool:
        return isinstance(wert, list) and len(wert) <= hoechstens and all(isinstance(x, str) and 0 < len(x) <= 4096 for x in wert)

    if not isinstance(obj, dict) or set(obj) != set(EINREICHEN_JSON_FELDER) or type(obj["v"]) is not int or obj["v"] != 1 \
            or not texte(obj["markiert"], _regeln().MAX_LISTE) or not texte(obj["pfade"], PR_PFADE_MAX) \
            or not all(isinstance(obj[k], str) and OID_RE.fullmatch(obj[k]) for k in ("commit_id", "tree_id", "basis")) \
            or not isinstance(obj["art"], str) or not ART_RE.fullmatch(obj["art"]) or not isinstance(obj["titel"], str) \
            or (obj["titel"] != TITEL_ERSATZ and titel_bereinigen(obj["titel"]) != obj["titel"]) \
            or not all(type(obj[k]) is int and obj[k] >= 0 for k in ("dateien", "plus", "minus", "zeit")):
        raise GithubAbgelehnt("zustand")
    return obj


def _status_setzen(w: Werkzeuge, aenderung: dict, status: str, **felder) -> dict:
    neu = {**aenderung, "status": status, **felder}
    json_schreiben(w.pfad("aenderung.json"), neu)
    w.log(f"einreichen {aenderung.get('job')} status={status}")
    return neu


def _eingabe_lesen(eingabe: object) -> tuple[str, str, set[str], tuple[str, ...]]:
    if not isinstance(eingabe, Mapping) or not set(eingabe) <= set(EINREICHEN_FELDER):
        raise GithubAbgelehnt("bestaetigung")
    commit, tree, bestaetigt = eingabe.get("commit_id"), eingabe.get("tree_id"), eingabe.get("bestaetigt")
    if not isinstance(commit, str) or not OID_RE.fullmatch(commit) or not isinstance(tree, str) or not OID_RE.fullmatch(tree):
        raise GithubAbgelehnt("veraltet")
    if not isinstance(bestaetigt, (list, tuple)) or not all(isinstance(p, str) for p in bestaetigt):
        raise GithubAbgelehnt("bestaetigung")
    return commit, tree, set(bestaetigt), ausnahmen_pruefen(eingabe.get(FELD_SCOPES_AUSNAHMEN))


def _kandidat_pruefen(w: Werkzeuge, job: str, profil: str, commit: str, tree: str, bestaetigt: set[str]):
    """Schritt 2: Zustand, Bindung an Auftrag und Profil, Kandidat in aus.git gleich der Karte, alle markierten Pfade bestätigt."""
    aenderung = aenderung_lesen(w)
    if aenderung["status"] not in STATUS_EINREICHEN:
        raise GithubAbgelehnt("zustand")
    e = _einreichen_json_lesen(w)
    if e["job"] != job or e["profil"] != profil:
        raise GithubAbgelehnt("zustand")
    if not (commit == aenderung.get("commit_id") == e["commit_id"] and tree == aenderung.get("tree_id") == e["tree_id"]):
        raise GithubAbgelehnt("veraltet")
    aus = w.pfad("aus.git")
    if _ref_commit(w, aus, KANDIDAT_REF, "veraltet") != commit or _commit_tree(w, aus, commit, "veraltet") != tree:
        raise GithubAbgelehnt("veraltet")
    if not set(e["markiert"]) <= bestaetigt:
        raise GithubAbgelehnt("bestaetigung")
    return aenderung, e


def _konto_und_repo(w: Werkzeuge, g: Mapping, token_art: str, ausnahmen: Sequence[str]) -> RepoDaten:
    """Schritt 3: GET /user (dasselbe Konto, Ablauf, Rechte von jetzt) und GET /repos/<repo> (dieselbe ID, nicht das eigene Repo,
    Schreibrecht)."""
    antwort = _http(w, "GET", "/user")
    if antwort is not None and antwort.status in (401, 403, 404):
        raise GithubAbgelehnt("token_abgelaufen")  # abgelaufen oder widerrufen
    if antwort is None or antwort.status != 200:
        raise GithubAbgelehnt("github_fehler")
    konto = konto_lesen(antwort.daten)
    if konto is None or konto[1] != g["konto_id"]:
        raise GithubAbgelehnt("konto")
    grund = token_grund(antwort.kopf, token_art, ausnahmen, w.uhr())
    if grund:
        raise GithubAbgelehnt(grund)
    antwort = _http(w, "GET", f"/repos/{g['repo']}")
    if antwort is not None and antwort.status in (301, 401, 403, 404):
        raise GithubAbgelehnt("repo_geaendert")
    if antwort is None or antwort.status != 200:
        raise GithubAbgelehnt("github_fehler")
    daten = repo_lesen(antwort.daten, g["repo"])
    if isinstance(daten, str) or daten.repo_id != g["repo_id"]:
        raise GithubAbgelehnt("repo_geaendert")
    if not daten.schreiben:
        raise GithubAbgelehnt("keine_schreibrechte")
    return daten


def _geheimnis_pruefen(w: Werkzeuge, g: Mapping, job: str, commit: str) -> None:
    """Schritt 4: erneute Geheimnissuche über die Bytes aus ergebnis/, jetzt auch mit dem GitHub-Token (Werkzeuge.geheimnis_in). Die
    Bytes müssen genau die Blobs des Kandidaten sein; dazu die Nachricht des Kandidaten."""
    regeln, auszug = _regeln(), _auszug()
    aus, basis = w.pfad("aus.git"), g["basis"]
    try:
        ergebnis = auszug.ergebnis_lesen(w.pfad("ergebnis"), job=job, basis=basis)
        roh = _git(w, ("diff-tree", "-r", "-z", "--raw", "--no-abbrev", "--no-renames", basis, commit), aus, grund="veraltet").stdout
        kandidat = {d["pfad"]: d["oid"] for d in auszug.diff_lesen(roh, auszug.Grenzen()) if d["art"] != "geloescht"}
    except auszug.AuszugFehler:
        raise GithubAbgelehnt("veraltet") from None
    bytes_je_pfad = {e.pfad: e.inhalt for e in ergebnis.eintraege if e.inhalt is not None}
    for pfad, oid in kandidat.items():
        if regeln.pfad_regeln(pfad):  # nur was git gespeichert hat, zählt (FP1 3.1.3)
            raise GithubAbgelehnt("veraltet")
        inhalt = bytes_je_pfad.get(pfad)
        if inhalt is None or regeln.blob_id(inhalt) != oid:
            raise GithubAbgelehnt("veraltet")
        if regeln.geheimnis_regeln(inhalt, (), w.geheimnis_in) or regeln.geheimnis_regeln(pfad, (), w.geheimnis_in):
            raise GithubAbgelehnt("geheimnis")
    nachricht = _git(w, ("cat-file", "commit", commit), aus, grund="veraltet").stdout
    if regeln.geheimnis_regeln(nachricht, (), w.geheimnis_in):
        raise GithubAbgelehnt("geheimnis")


def _zweig_stand(w: Werkzeuge, repo: str, job: str) -> str | None:
    erg = _git(w, ("ls-remote", "--", _url(repo), f"refs/heads/wamo/{job}"), w.pfad("aus.git"), netz=True, grund="github_fehler")
    stand = ls_remote_lesen(erg.stdout, job)
    if stand is False:
        raise GithubAbgelehnt("github_fehler")
    return stand


def _pushen(w: Werkzeuge, aenderung: dict, repo: str, job: str, commit: str) -> dict:
    """Schritt 6: Zustand einreichen_laeuft, Push genau <commit>:refs/heads/wamo/<job> (nie Force, nie ein anderer Ref, nie Tags), dann
    branch_gepusht; jeder Fehler setzt bereit zurück."""
    aenderung = _status_setzen(w, aenderung, "einreichen_laeuft")
    try:
        erg = w.git(("-c", "push.negotiate=true", "push", "--no-verify", "--no-follow-tags", "--porcelain", "--", _url(repo),
                     f"{commit}:refs/heads/wamo/{job}"),
                    git_dir=w.pfad("aus.git"), netz=True, zeitlimit_s=PUSH_ZEIT_S)
    except KeinToken:
        _status_setzen(w, aenderung, "bereit")
        raise GithubAbgelehnt("github_fehler") from None
    except BaseException:
        _status_setzen(w, aenderung, "bereit")
        raise
    if erg.code != 0 or not push_ausgabe_ok(erg.stdout, commit, job):
        _status_setzen(w, aenderung, "bereit")
        w.log(f"einreichen {job} push rc={erg.code} {erg.stderr[:200]}")
        verweigert = re.search(r"(?i)\b403\b|permission|denied|not allowed", erg.stderr)
        raise GithubAbgelehnt("keine_schreibrechte" if verweigert else "github_fehler")
    return _status_setzen(w, aenderung, "branch_gepusht")


def _pr_gueltig(eintrag: object, repo: str, job: str, commit: str, repo_id: int) -> tuple[int, str] | None:
    """Ein offener Pull Request darf nur mit demselben Kopf (Zweig, SHA, Repo) wiederverwendet werden; Nummer und Adresse geprüft."""
    if not isinstance(eintrag, dict) or eintrag.get("state", "open") != "open":
        return None
    kopf = eintrag.get("head")
    if not isinstance(kopf, dict) or kopf.get("sha") != commit or kopf.get("ref") != f"wamo/{job}":
        return None
    if not isinstance(kopf.get("repo"), dict) or kopf["repo"].get("id") != repo_id:
        return None
    return _pr_nummer(eintrag, repo)


def _pr_nummer(eintrag: object, repo: str) -> tuple[int, str] | None:
    if not isinstance(eintrag, dict):
        return None
    nummer, adresse = eintrag.get("number"), eintrag.get("html_url")
    if type(nummer) is not int or not 0 < nummer < 10 ** 9 or not isinstance(adresse, str):
        return None
    erwartet = f"https://github.com/{repo}/pull/{nummer}"
    return (nummer, erwartet) if adresse.lower() == erwartet.lower() else None


def _pull_request(w: Werkzeuge, repo: str, job: str, commit: str, g: Mapping, daten: RepoDaten, e: Mapping) -> tuple[int, str]:
    """Schritt 7: offenen Pull Request mit gleichem Kopf wiederverwenden, sonst neu als Entwurf (bei 422 ohne), maintainer_can_modify aus,
    Basis der Standardzweig dieses Repos (bei einem Fork dessen eigener)."""
    besitzer = repo.split("/", 1)[0]
    antwort = _http(w, "GET", f"/repos/{repo}/pulls?head={besitzer}:wamo/{job}&state=open&per_page=10")
    if antwort is None or antwort.status != 200 or not isinstance(antwort.daten, list):
        raise GithubAbgelehnt("github_fehler")
    for eintrag in antwort.daten:
        treffer = _pr_gueltig(eintrag, repo, job, commit, g["repo_id"])
        if treffer:
            return treffer
    koerper = {"title": f"W.A.I.S.: {e['titel']}", "head": f"wamo/{job}", "base": daten.standardzweig,
               "body": pr_text(job, e["art"], g["login"], e["dateien"], e["plus"], e["minus"], e["pfade"]), "draft": True,
               "maintainer_can_modify": False}
    antwort = _http(w, "POST", f"/repos/{repo}/pulls", koerper)
    if antwort is not None and antwort.status == 422:
        antwort = _http(w, "POST", f"/repos/{repo}/pulls", {k: v for k, v in koerper.items() if k != "draft"})
    treffer = _pr_nummer(antwort.daten, repo) if antwort is not None and antwort.status == 201 else None
    if treffer is None:
        raise GithubAbgelehnt("github_fehler")
    return treffer


def einreichen(w: Werkzeuge, *, job: str, profil: str, eingabe: Mapping[str, object], token_art: str,
               kanal: Callable[[], str | None], zaehlen: Callable[[], str | None]) -> dict:
    """Einreichen nach dem Klick (C.5 Einreichen 2 bis 8). eingabe: die erste Zeile (commit_id, tree_id, bestaetigt, scopes_ausnahmen).
    kanal: zweite Prüfung des Kern-Kanals (None oder ein Code aus KANAL_GRUENDE), vor dem Zweig-Abgleich, vor dem Push und vor dem Pull
    Request. zaehlen: bucht den Versuch in kernkanal.jsonl (None oder grenze_einreichen), nur für einen neuen Push. Ergebnis: die Felder
    des Ereignisses eingereicht."""
    _pruefe_kennungen(job, profil, "zustand")
    if token_art not in TOKEN_ARTEN:
        raise GithubAbgelehnt("token_rechte")
    commit, tree, bestaetigt, ausnahmen = _eingabe_lesen(eingabe)
    g = github_json_lesen(w, "zustand")
    repo = g["repo"]
    aenderung, e = _kandidat_pruefen(w, job, profil, commit, tree, bestaetigt)
    daten = _konto_und_repo(w, g, token_art, ausnahmen)
    _geheimnis_pruefen(w, g, job, commit)
    grund = kanal()  # zweite Prüfung des Kanals (Notaus, Konfiguration), noch ohne Wirkung nach außen
    if grund:
        raise GithubAbgelehnt(grund)
    stand = _zweig_stand(w, repo, job)
    if stand is not None and stand != commit:
        raise GithubAbgelehnt("zweig_belegt")
    status = aenderung["status"]
    if status == "einreichen_laeuft":  # nach einem Absturz: der Zweig auf GitHub entscheidet
        aenderung = _status_setzen(w, aenderung, "branch_gepusht" if stand == commit else "bereit")
        status = aenderung["status"]
    if stand is None or status == "bereit":
        grund = zaehlen()  # jeder Push zählt, auch ein erneuter nach einem auf GitHub gelöschten Zweig
        if grund:
            raise GithubAbgelehnt(grund)
        grund = kanal()
        if grund:
            raise GithubAbgelehnt(grund)
        if stand is None:
            aenderung = _pushen(w, aenderung, repo, job, commit)
        else:
            aenderung = _status_setzen(w, aenderung, "branch_gepusht")
    grund = kanal()
    if grund:
        raise GithubAbgelehnt(grund)
    nummer, adresse = _pull_request(w, repo, job, commit, g, daten, e)
    _status_setzen(w, aenderung, "eingereicht", pr=nummer, adresse=adresse)
    w.log(f"eingereicht {job} repo={repo} pr={nummer} commit={commit}", pflicht=True)
    return {"job": job, "zweig": f"wamo/{job}", "pr": nummer, "adresse": adresse}
