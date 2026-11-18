"""Persönliche GitHub-Zugänge für Entwicklungsaufträge, Seite des Dispatchers (Plan C, docs/persoenliche-zugaenge.md).

Stand Paket S: nur die Konstanten der Schnittstelle Kern zu Dispatcher (C.2) und die Protokoll-Klasse Werkzeuge. Über Werkzeuge nutzt
Paket D-b (GitHub-Logik, Klon, Übernahme der Sandbox-Ausgaben, Commit aus Bytes, Einreichen) die Dienste, die Paket D-a im Dispatcher
bereitstellt; die Logik von D-b folgt in dieser Datei. Installiert wird sie wie das Modul des Kern-Kanals nach
/opt/wamo/waechter/wamo_job_github.py (root:wamo 0640, Paket D-a).

Wie wamo_job_kernkanal.py: keine Nebenwirkung beim Import, nur Standardbibliothek, kein Netz, keine Prozesse, keine Geheimnisse. Das Token
sieht der Code dieser Datei nie: Werkzeuge.http und Werkzeuge.git benutzen das Token des Aufrufs, das der Dispatcher als bytearray hält,
und Werkzeuge.geheimnis_in sucht danach. Die Gründe (GITHUB_GRUENDE, AENDERUNG_GRUENDE, EINREICHEN_GRUENDE) stehen im Modul des
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

import re
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
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
