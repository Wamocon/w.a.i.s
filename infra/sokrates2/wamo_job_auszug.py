#!/usr/bin/env python3
"""Auszug im netzlosen Sandbox-Schritt `pruefung` (Plan C, C.5 Laufende 3, docs/persoenliche-zugaenge.md).

Die Sandbox hat am Laufende ihre Commits auf `refs/heads/wamo/<job>` als Bundle exportiert (Schritt `ausgabe`), der Dispatcher hat es
nach `JOBDIR/bundle.ein` kopiert. Dieses Programm läuft danach in einer eigenen Sandbox ohne Netz, ohne Projektordner und ohne
`/etc/wamo`; sichtbar sind nur `basis.git` und `bundle.ein` (nur lesend) und `ergebnis/` (beschreibbar). Es

1. prüft den Kopf des Bundles selbst (genau ein Kopf `refs/heads/wamo/<job>`, nur SHA-1, kein Filter),
2. legt ein leeres bare Repo ohne Vorlage mit Alternates auf `basis.git` an und holt das Bundle mit fsck,
3. prüft `merge-base --is-ancestor <basis> <spitze>` und höchstens 200 Commits,
4. liest die Änderungen mit `diff-tree -r -z --no-renames` und prüft alle Größen mit `cat-file --batch-check` vor dem Lesen,
5. schreibt `ergebnis/liste.json` (je Änderung Pfad als Bytes in Base64, Modi, IDs, Art, Größe) und je neue oder geänderte Datei
   ihren Inhalt als `ergebnis/dateien/<n>` (für Links das Ziel).

Nie läuft ein Hook, nie wirkt eine Konfiguration aus Umgebung, Vorlage oder einem fremden Repo: jeder git-Aufruf bekommt eine feste
Umgebung, `--git-dir`, `cwd="/"` und `core.hooksPath` auf das Nullgerät. Der Dispatcher liest das Ergebnis mit `ergebnis_lesen`
(dasselbe Modul, damit der Vertrag an einer Stelle steht) und prüft die Bytes danach mit wamo_job_pfadregeln.py.

Aufruf in der Sandbox (wamo-job.sh, Modus pruefung):
    python3 -I /opt/wamo/waechter/wamo_job_auszug.py --job <job> --basis <40 Hex>
Feste Pfade: /run/wamo/basis.git, /run/wamo/bundle.ein, /run/wamo/ergebnis; Arbeitsordner unter $TMPDIR (tmpfs der Sandbox).
Exit 0: liste.json geschrieben (Status ok oder fehler mit Grund). Exit 2: Aufruf oder Ergebnisordner ungültig, nichts geschrieben.
Nur Standardbibliothek, läuft mit `python3 -I` (ohne Skriptordner in sys.path).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VERSION = 1
BASIS_GIT = "/run/wamo/basis.git"
BUNDLE = "/run/wamo/bundle.ein"
ERGEBNIS = "/run/wamo/ergebnis"
LISTE = "liste.json"
DATEIEN = "dateien"

JOB_RE = re.compile(r"[0-9a-f]{16,32}")  # wie JOB_RE im Dispatcher
OID_RE = re.compile(r"[0-9a-f]{40}")
OID_BYTES_RE = re.compile(rb"[0-9a-f]{40}")
MODUS_RE = re.compile(r"[0-7]{6}")
DATEI_RE = re.compile(r"dateien/(0|[1-9][0-9]{0,5})")
NULL_OID = "0" * 40
MODUS_LEER = "000000"
MODI_INHALT = ("100644", "100755", "120000")  # nur diese Modi bekommen eine Inhaltsdatei
ARTEN = {"A": "neu", "M": "geaendert", "T": "geaendert", "D": "geloescht"}

# Gründe, die der Auszug meldet; jeder Code steht in AENDERUNG_GRUENDE (C.2.6)
GRUND_BUNDLE = "bundle_ungueltig"
GRUND_BASIS = "basis_fehlt"
GRUND_COMMITS = "zu_viele_commits"
GRUND_GROESSE = "zu_gross"
GRUND_FEHLER = "pruefung_fehler"
GRUENDE = (GRUND_BUNDLE, GRUND_BASIS, GRUND_COMMITS, GRUND_GROESSE, GRUND_FEHLER)

MAX_KOPF_BYTES = 64 * 1024
MAX_LISTE_BYTES = 4 * 1024 * 1024
MAX_GIT_AUSGABE = 64 * 1024 * 1024
GIT_ZEIT_MAX_S = 60.0

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)
MIT_DIR_FD = os.open in os.supports_dir_fd and bool(O_DIRECTORY)  # Linux; unter Windows nur der Weg über Pfade (Tests)


@dataclass(frozen=True)
class Grenzen:
    commits: int = 200
    dateien: int = 300  # Einträge mit Inhalt
    eintraege: int = 2000  # alle Einträge, auch Löschungen (entschärfte Löschungen fallen erst im Dispatcher weg)
    datei_bytes: int = 5 * 1024 * 1024
    gesamt_bytes: int = 20 * 1024 * 1024
    bundle_bytes: int = 200 * 1024 * 1024
    zeit_s: float = 60.0


class AuszugFehler(Exception):
    def __init__(self, grund: str, detail: str = ""):
        super().__init__(f"{grund}: {detail}" if detail else grund)
        self.grund = grund if grund in GRUENDE else GRUND_FEHLER
        self.detail = detail


@dataclass(frozen=True)
class AuszugEintrag:
    pfad: bytes
    art: str
    modus: str
    alt_modus: str
    oid: str
    alt_oid: str
    inhalt: bytes | None


@dataclass(frozen=True)
class Ergebnis:
    status: str  # ok oder fehler
    grund: str | None
    spitze: str | None
    commits: int
    eintraege: tuple[AuszugEintrag, ...]


# ---------------------------------------------------------------- git mit fester Umgebung
def _git_programm() -> str:
    if os.name == "posix" and os.path.exists("/usr/bin/git"):
        return "/usr/bin/git"  # nie über PATH: ein früherer Lauf könnte ein eigenes git ins Home gelegt haben
    gefunden = shutil.which("git")
    if gefunden is None:
        raise AuszugFehler(GRUND_FEHLER, "git fehlt")
    return gefunden


def git_umgebung() -> dict[str, str]:
    """Die einzige Umgebung der git-Aufrufe: nichts aus der Umgebung des Aufrufers außer dem, was Windows zum Starten braucht."""
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": "/", "GIT_TERMINAL_PROMPT": "0",
           "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_PROTOCOL_FROM_USER": "0", "GIT_NO_LAZY_FETCH": "1"}
    if os.name == "nt":  # nur für die Tests auf der Entwicklungsmaschine
        for name in ("SYSTEMROOT", "TEMP", "TMP"):
            if name in os.environ:
                env[name] = os.environ[name]
        env["PATH"] = os.path.dirname(_git_programm())
    return env


GIT_KONFIG = ("core.hooksPath=" + os.devnull, "core.fsmonitor=false", "core.untrackedCache=false", "core.commitGraph=false",
              "gc.auto=0", "maintenance.auto=false", "protocol.allow=never", "protocol.file.allow=always",
              "fetch.fsckObjects=true", "transfer.fsckObjects=true", "fetch.unpackLimit=1", "fetch.writeCommitGraph=false",
              "submodule.recurse=false")


def git_argv(git_dir: str | os.PathLike, *args: str) -> list[str]:
    argv = [_git_programm(), f"--git-dir={os.fspath(git_dir)}"]
    for paar in GIT_KONFIG:
        argv += ["-c", paar]
    return argv + list(args)


def _git(git_dir, *args: str, eingabe: bytes | None = None, frist: Callable[[], float],
         pruefen: bool = True) -> subprocess.CompletedProcess:
    try:
        erg = subprocess.run(git_argv(git_dir, *args), input=eingabe, capture_output=True, env=git_umgebung(), cwd="/",
                             timeout=min(frist(), GIT_ZEIT_MAX_S))
    except subprocess.TimeoutExpired as e:
        raise AuszugFehler(GRUND_FEHLER, "git Zeitlimit") from e
    except OSError as e:
        raise AuszugFehler(GRUND_FEHLER, f"git nicht startbar ({e.strerror})") from e
    if len(erg.stdout) > MAX_GIT_AUSGABE:
        raise AuszugFehler(GRUND_FEHLER, "git Ausgabe zu groß")
    if pruefen and erg.returncode != 0:
        raise AuszugFehler(GRUND_FEHLER, f"git {args[0]} rc={erg.returncode}")
    return erg


# ---------------------------------------------------------------- Bundle
def _regulaere_datei_lesen(pfad, limit: int, *, nur_anfang: bool = False) -> bytes:
    """Liest eine reguläre Datei ohne Link zu folgen und ohne an einer FIFO zu hängen; größer als limit: Fehler, außer nur_anfang."""
    try:
        st = os.lstat(pfad)
        if not stat.S_ISREG(st.st_mode):
            raise AuszugFehler(GRUND_BUNDLE, "keine reguläre Datei")
        fd = os.open(pfad, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY)
    except OSError as e:
        raise AuszugFehler(GRUND_BUNDLE, "nicht lesbar") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise AuszugFehler(GRUND_BUNDLE, "keine reguläre Datei")
        if st.st_size > limit and not nur_anfang:
            raise AuszugFehler(GRUND_BUNDLE, "zu groß")
        teile, rest = [], limit
        while rest > 0:
            stueck = os.read(fd, min(rest, 1024 * 1024))
            if not stueck:
                break
            teile.append(stueck)
            rest -= len(stueck)
        return b"".join(teile)
    finally:
        os.close(fd)


def bundle_kopf(pfad, job: str, grenzen: Grenzen) -> str:
    """Prüft das Bundle vor git: reguläre Datei, Größe, Format v2 oder v3 (nur object-format=sha1), genau ein Kopf und der heißt
    refs/heads/wamo/<job>. Ergebnis: die Commit-ID der Spitze."""
    try:
        st = os.lstat(pfad)
    except OSError as e:
        raise AuszugFehler(GRUND_BUNDLE, "fehlt") from e
    if not stat.S_ISREG(st.st_mode) or st.st_size > grenzen.bundle_bytes:
        raise AuszugFehler(GRUND_BUNDLE, "keine reguläre Datei oder zu groß")
    daten = _regulaere_datei_lesen(pfad, MAX_KOPF_BYTES, nur_anfang=True)
    ende = daten.find(b"\n\n")
    if ende < 0:
        raise AuszugFehler(GRUND_BUNDLE, "Kopf ohne Ende")
    zeilen = daten[:ende].split(b"\n")
    if zeilen[0] not in (b"# v2 git bundle", b"# v3 git bundle"):
        raise AuszugFehler(GRUND_BUNDLE, "Format")
    koepfe = []
    for zeile in zeilen[1:]:
        if zeile.startswith(b"@"):
            if zeilen[0] != b"# v3 git bundle" or zeile != b"@object-format=sha1":
                raise AuszugFehler(GRUND_BUNDLE, "Fähigkeit")
        elif zeile.startswith(b"-"):
            if not OID_BYTES_RE.fullmatch(zeile[1:41]) or (len(zeile) > 41 and zeile[41:42] != b" "):
                raise AuszugFehler(GRUND_BUNDLE, "Voraussetzung")
        else:
            oid, _, ref = zeile.partition(b" ")
            if not OID_BYTES_RE.fullmatch(oid):
                raise AuszugFehler(GRUND_BUNDLE, "Kopfzeile")
            koepfe.append((oid.decode("ascii"), ref))
    if len(koepfe) != 1 or koepfe[0][1] != f"refs/heads/wamo/{job}".encode("ascii"):
        raise AuszugFehler(GRUND_BUNDLE, "Köpfe")
    return koepfe[0][0]


# ---------------------------------------------------------------- Ergebnisordner
def _ergebnis_vorbereiten(ergebnis: Path) -> None:
    """Der Ordner muss existieren, ein echter Ordner (kein Link) und leer sein; dann entsteht dateien/."""
    try:
        st = os.lstat(ergebnis)
    except OSError as e:
        raise AuszugFehler(GRUND_FEHLER, "Ergebnisordner fehlt") from e
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise AuszugFehler(GRUND_FEHLER, "Ergebnisordner ist kein Ordner")
    if os.listdir(ergebnis):
        raise AuszugFehler(GRUND_FEHLER, "Ergebnisordner nicht leer")


def _neue_datei(pfad: Path, daten: bytes) -> None:
    fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC | O_BINARY, 0o600)
    try:
        ansicht = memoryview(daten)
        while ansicht:
            n = os.write(fd, ansicht)
            ansicht = ansicht[n:]
    finally:
        os.close(fd)


def _liste_schreiben(ergebnis: Path, daten: dict) -> None:
    """Atomar: zuerst eine neue Datei, dann rename. Erst mit liste.json gilt der Auszug als fertig."""
    tmp = ergebnis / f".{LISTE}.{os.getpid()}.tmp"
    _neue_datei(tmp, json.dumps(daten, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
    os.replace(tmp, ergebnis / LISTE)


# ---------------------------------------------------------------- Auszug
def diff_lesen(roh: bytes, grenzen: Grenzen) -> list[dict]:
    """Ausgabe von `diff-tree -r -z --raw --no-abbrev --no-renames`: je Änderung `:<alt> <neu> <altid> <neuid> <S>` NUL Pfad NUL."""
    teile = roh.split(b"\x00")
    if teile and teile[-1] == b"":
        teile.pop()
    if len(teile) % 2:
        raise AuszugFehler(GRUND_FEHLER, "diff-tree Format")
    out, gesehen = [], set()
    for i in range(0, len(teile), 2):
        kopf, pfad = teile[i], teile[i + 1]
        felder = kopf.split(b" ")
        if len(felder) != 5 or not felder[0].startswith(b":") or not pfad:
            raise AuszugFehler(GRUND_FEHLER, "diff-tree Zeile")
        alt_modus, modus = felder[0][1:].decode("ascii", "replace"), felder[1].decode("ascii", "replace")
        alt_oid, oid, status = (f.decode("ascii", "replace") for f in felder[2:])
        if (not MODUS_RE.fullmatch(alt_modus) or not MODUS_RE.fullmatch(modus) or not OID_RE.fullmatch(alt_oid)
                or not OID_RE.fullmatch(oid) or status not in ARTEN or pfad in gesehen):
            raise AuszugFehler(GRUND_FEHLER, "diff-tree Werte")
        gesehen.add(pfad)
        out.append({"pfad": pfad, "art": ARTEN[status], "modus": modus, "alt_modus": alt_modus, "oid": oid, "alt_oid": alt_oid})
        if len(out) > grenzen.eintraege:
            raise AuszugFehler(GRUND_GROESSE, "zu viele Einträge")
    return out


def _groessen_pruefen(repo: Path, oids: list[str], grenzen: Grenzen, frist) -> dict[str, int]:
    """Typ und Größe jedes Blobs mit cat-file --batch-check, bevor ein Byte Inhalt gelesen wird."""
    if len(oids) > grenzen.dateien:
        raise AuszugFehler(GRUND_GROESSE, "zu viele Dateien")
    if not oids:
        return {}
    erg = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
               eingabe="".join(o + "\n" for o in oids).encode("ascii"), frist=frist)
    zeilen = erg.stdout.decode("ascii", "replace").splitlines()
    if len(zeilen) != len(oids):
        raise AuszugFehler(GRUND_FEHLER, "batch-check Zahl")
    groessen: dict[str, int] = {}
    for oid, zeile in zip(oids, zeilen):
        felder = zeile.split(" ")
        if len(felder) != 3 or felder[0] != oid or felder[1] != "blob" or not felder[2].isdigit():
            raise AuszugFehler(GRUND_FEHLER, "batch-check Zeile")
        groesse = int(felder[2])
        if groesse > grenzen.datei_bytes:
            raise AuszugFehler(GRUND_GROESSE, "Datei zu groß")
        groessen[oid] = groesse
    if sum(groessen.values()) > grenzen.gesamt_bytes:
        raise AuszugFehler(GRUND_GROESSE, "zusammen zu groß")
    return groessen


def _inhalte_lesen(repo: Path, groessen: dict[str, int], frist) -> dict[str, bytes]:
    """Inhalte mit cat-file --batch; jede Länge muss der geprüften Größe entsprechen, jede ID der SHA-1 der Bytes."""
    oids = list(groessen)
    if not oids:
        return {}
    erg = _git(repo, "cat-file", "--batch", eingabe="".join(o + "\n" for o in oids).encode("ascii"), frist=frist)
    daten, pos, out = erg.stdout, 0, {}
    for oid in oids:
        ende = daten.find(b"\n", pos)
        if ende < 0 or daten[pos:ende] != f"{oid} blob {groessen[oid]}".encode("ascii"):
            raise AuszugFehler(GRUND_FEHLER, "batch Kopf")
        anfang = ende + 1
        inhalt = daten[anfang:anfang + groessen[oid]]
        if len(inhalt) != groessen[oid] or daten[anfang + groessen[oid]:anfang + groessen[oid] + 1] != b"\n":
            raise AuszugFehler(GRUND_FEHLER, "batch Inhalt")
        if hashlib.sha1(b"blob %d\x00" % len(inhalt) + inhalt).hexdigest() != oid:
            raise AuszugFehler(GRUND_FEHLER, "batch Prüfsumme")
        out[oid] = inhalt
        pos = anfang + groessen[oid] + 1
    if pos != len(daten):
        raise AuszugFehler(GRUND_FEHLER, "batch Rest")
    return out


def _repo_anlegen(arbeit: Path, basis_git: Path, frist) -> Path:
    leer = arbeit / "vorlage-leer"
    leer.mkdir(mode=0o700)
    repo = arbeit / "auszug.git"
    try:
        erg = subprocess.run([_git_programm(), "-c", "init.defaultBranch=wamo", "init", "--bare", "--quiet", f"--template={leer}",
                              os.fspath(repo)], capture_output=True, env=git_umgebung(), cwd="/",
                             timeout=min(frist(), GIT_ZEIT_MAX_S))
    except (subprocess.TimeoutExpired, OSError) as e:
        raise AuszugFehler(GRUND_FEHLER, "git init") from e
    if erg.returncode != 0:
        raise AuszugFehler(GRUND_FEHLER, "git init")
    info = repo / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    _neue_datei(info / "alternates", (Path(basis_git).resolve() / "objects").as_posix().encode("utf-8") + b"\n")
    return repo


def _schritte(job: str, basis: str, basis_git: Path, bundle: Path, ergebnis: Path, arbeit: Path, grenzen: Grenzen,
              frist) -> dict:
    spitze = bundle_kopf(bundle, job, grenzen)
    repo = _repo_anlegen(arbeit, basis_git, frist)
    if _git(repo, "cat-file", "-e", f"{basis}^{{commit}}", frist=frist, pruefen=False).returncode != 0:
        raise AuszugFehler(GRUND_BASIS, "Basis fehlt in basis.git")
    ref = f"refs/heads/wamo/{job}"
    holen = _git(repo, "fetch", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules", "--quiet", "--end-of-options",
                 os.fspath(bundle), f"{ref}:{ref}", frist=frist, pruefen=False)
    if holen.returncode != 0:
        raise AuszugFehler(GRUND_BUNDLE, "fetch")
    erhalten = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", frist=frist, pruefen=False)
    if erhalten.returncode != 0 or erhalten.stdout.decode("ascii", "replace").strip() != spitze:
        raise AuszugFehler(GRUND_BUNDLE, "Spitze")
    vorfahr = _git(repo, "merge-base", "--is-ancestor", basis, spitze, frist=frist, pruefen=False)
    if vorfahr.returncode == 1:
        raise AuszugFehler(GRUND_BASIS, "Basis ist kein Vorfahr")
    if vorfahr.returncode != 0:
        raise AuszugFehler(GRUND_FEHLER, "merge-base")
    zahl = _git(repo, "rev-list", "--count", f"{basis}..{spitze}", frist=frist).stdout.decode("ascii", "replace").strip()
    if not zahl.isdigit():
        raise AuszugFehler(GRUND_FEHLER, "rev-list")
    commits = int(zahl)
    if commits > grenzen.commits:
        raise AuszugFehler(GRUND_COMMITS, "zu viele Commits")
    diff = _git(repo, "diff-tree", "-r", "-z", "--raw", "--no-abbrev", "--no-renames", "--no-ext-diff", "--no-textconv", basis,
                spitze, frist=frist)
    eintraege = diff_lesen(diff.stdout, grenzen)
    for e in eintraege:
        e["mit_inhalt"] = e["art"] != "geloescht" and e["modus"] in MODI_INHALT
    oids = list(dict.fromkeys(e["oid"] for e in eintraege if e["mit_inhalt"]))
    if sum(1 for e in eintraege if e["mit_inhalt"]) > grenzen.dateien:
        raise AuszugFehler(GRUND_GROESSE, "zu viele Dateien")
    groessen = _groessen_pruefen(repo, oids, grenzen, frist)
    if sum(groessen[e["oid"]] for e in eintraege if e["mit_inhalt"]) > grenzen.gesamt_bytes:
        raise AuszugFehler(GRUND_GROESSE, "zusammen zu groß")
    inhalte = _inhalte_lesen(repo, groessen, frist)
    frist()
    (ergebnis / DATEIEN).mkdir(mode=0o700)
    liste, n = [], 0
    for e in eintraege:
        datei = None
        groesse = 0
        if e["mit_inhalt"]:
            datei = f"{DATEIEN}/{n}"
            n += 1
            inhalt = inhalte[e["oid"]]
            _neue_datei(ergebnis / datei, inhalt)
            groesse = len(inhalt)
        liste.append({"pfad": base64.b64encode(e["pfad"]).decode("ascii"), "art": e["art"], "modus": e["modus"],
                      "alt_modus": e["alt_modus"], "oid": e["oid"], "alt_oid": e["alt_oid"], "groesse": groesse, "datei": datei})
    return {"v": VERSION, "status": "ok", "job": job, "basis": basis, "spitze": spitze, "commits": commits, "eintraege": liste}


def auszug(job: str, basis: str, *, basis_git, bundle, ergebnis, arbeit, grenzen: Grenzen = Grenzen(),
           uhr: Callable[[], float] = time.monotonic) -> dict:
    """Führt den Auszug aus und schreibt ergebnis/liste.json. Ein ungültiger Aufruf oder ein unbrauchbarer Ergebnisordner wirft
    AuszugFehler (dann steht nichts im Ordner); jeder andere Fehler steht als Status fehler mit Grund in liste.json."""
    if not isinstance(job, str) or not JOB_RE.fullmatch(job) or not isinstance(basis, str) or not OID_RE.fullmatch(basis):
        raise AuszugFehler(GRUND_FEHLER, "Aufruf")
    ergebnis, arbeit = Path(ergebnis), Path(arbeit)
    _ergebnis_vorbereiten(ergebnis)
    ende = uhr() + grenzen.zeit_s

    def frist() -> float:
        rest = ende - uhr()
        if rest <= 0:
            raise AuszugFehler(GRUND_FEHLER, "Zeitbudget")
        return rest

    try:
        daten = _schritte(job, basis, Path(basis_git), Path(bundle), ergebnis, arbeit, grenzen, frist)
    except AuszugFehler as e:
        daten = {"v": VERSION, "status": "fehler", "grund": e.grund}
    except OSError:
        daten = {"v": VERSION, "status": "fehler", "grund": GRUND_FEHLER}
    _liste_schreiben(ergebnis, daten)
    return daten


# ---------------------------------------------------------------- Dispatcher: Ergebnis lesen
class _Ordner:
    """Lesender Zugriff auf ergebnis/ ohne einem Link zu folgen: unter Linux über Verzeichnis-Deskriptoren, sonst (nur Tests unter
    Windows) über Pfade mit lstat je Teil."""

    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.fd = None
        try:
            if MIT_DIR_FD:
                self.fd = os.open(self.pfad, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            else:
                st = os.lstat(self.pfad)
                if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                    raise AuszugFehler(GRUND_FEHLER, "Ergebnis ist kein Ordner")
        except OSError as e:
            raise AuszugFehler(GRUND_FEHLER, "Ergebnis nicht lesbar") from e

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def namen(self, unter: str | None = None) -> list[str]:
        try:
            if self.fd is None:
                ziel = self.pfad / unter if unter else self.pfad
                if unter:
                    st = os.lstat(ziel)
                    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                        raise AuszugFehler(GRUND_FEHLER, "kein Ordner")
                return os.listdir(ziel)
            if not unter:
                return os.listdir(self.fd)
            fd = os.open(unter, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=self.fd)
            try:
                return os.listdir(fd)
            finally:
                os.close(fd)
        except OSError as e:
            raise AuszugFehler(GRUND_FEHLER, "Ordner nicht lesbar") from e

    def lesen(self, rel: str, limit: int, genau: int | None = None) -> bytes:
        """Eine reguläre Datei (kein Link, keine FIFO, ein einziger Name), höchstens limit Bytes, mit genau: exakt diese Länge."""
        teile = rel.split("/")
        fds: list[int] = []
        try:
            flags = os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY
            if self.fd is None:
                pfad = self.pfad
                for teil in teile:
                    pfad = pfad / teil
                    st = os.lstat(pfad)
                    if stat.S_ISLNK(st.st_mode):
                        raise AuszugFehler(GRUND_FEHLER, "Link im Ergebnis")
                fd = os.open(pfad, flags)
            else:
                eltern = self.fd
                for teil in teile[:-1]:
                    eltern = os.open(teil, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=eltern)
                    fds.append(eltern)
                fd = os.open(teile[-1], flags, dir_fd=eltern)
            fds.append(fd)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
                raise AuszugFehler(GRUND_FEHLER, "keine reguläre Datei oder zu groß")
            if genau is not None and st.st_size != genau:
                raise AuszugFehler(GRUND_FEHLER, "Größe weicht ab")
            daten = b""
            while len(daten) <= limit:
                stueck = os.read(fd, min(limit + 1 - len(daten), 1024 * 1024))
                if not stueck:
                    break
                daten += stueck
            if len(daten) > limit or (genau is not None and len(daten) != genau):
                raise AuszugFehler(GRUND_FEHLER, "Länge weicht ab")
            return daten
        except OSError as e:
            raise AuszugFehler(GRUND_FEHLER, "Datei nicht lesbar") from e
        finally:
            for fd in reversed(fds):
                os.close(fd)


FELDER_OK = {"v", "status", "job", "basis", "spitze", "commits", "eintraege"}
FELDER_FEHLER = {"v", "status", "grund"}
FELDER_EINTRAG = {"pfad", "art", "modus", "alt_modus", "oid", "alt_oid", "groesse", "datei"}


def _ganz(wert: object, hoechstens: int) -> int:
    if not isinstance(wert, int) or isinstance(wert, bool) or not 0 <= wert <= hoechstens:
        raise AuszugFehler(GRUND_FEHLER, "Zahl")
    return wert


def _eintrag_pruefen(roh: object, n_datei: int, grenzen: Grenzen) -> tuple[AuszugEintrag, str | None, int]:
    if not isinstance(roh, dict) or set(roh) != FELDER_EINTRAG:
        raise AuszugFehler(GRUND_FEHLER, "Eintrag Felder")
    try:
        pfad = base64.b64decode(roh["pfad"], validate=True) if isinstance(roh["pfad"], str) else b""
    except (binascii.Error, ValueError) as e:
        raise AuszugFehler(GRUND_FEHLER, "Pfad") from e
    art, modus, alt_modus, oid, alt_oid = (roh[k] for k in ("art", "modus", "alt_modus", "oid", "alt_oid"))
    if (not pfad or b"\x00" in pfad or art not in ARTEN.values() or not all(isinstance(x, str) for x in (modus, alt_modus, oid, alt_oid))
            or not MODUS_RE.fullmatch(modus) or not MODUS_RE.fullmatch(alt_modus) or not OID_RE.fullmatch(oid)
            or not OID_RE.fullmatch(alt_oid)):
        raise AuszugFehler(GRUND_FEHLER, "Eintrag Werte")
    if art == "geloescht":
        stimmig = modus == MODUS_LEER and oid == NULL_OID and alt_modus != MODUS_LEER and alt_oid != NULL_OID
    elif art == "neu":
        stimmig = alt_modus == MODUS_LEER and alt_oid == NULL_OID and modus != MODUS_LEER and oid != NULL_OID
    else:
        stimmig = MODUS_LEER not in (modus, alt_modus) and NULL_OID not in (oid, alt_oid)
    if not stimmig:
        raise AuszugFehler(GRUND_FEHLER, "Art und Modus")
    groesse = _ganz(roh["groesse"], grenzen.datei_bytes)
    braucht_datei = art != "geloescht" and modus in MODI_INHALT
    datei = roh["datei"]
    if braucht_datei:
        if datei != f"{DATEIEN}/{n_datei}" or not DATEI_RE.fullmatch(datei):
            raise AuszugFehler(GRUND_FEHLER, "Dateiname")
    elif datei is not None or groesse != 0:
        raise AuszugFehler(GRUND_FEHLER, "Datei ohne Inhalt")
    return AuszugEintrag(pfad=pfad, art=art, modus=modus, alt_modus=alt_modus, oid=oid, alt_oid=alt_oid, inhalt=None), datei, groesse


def ergebnis_lesen(ordner, *, job: str, basis: str, grenzen: Grenzen = Grenzen()) -> Ergebnis:
    """Liest ergebnis/ des Schritts pruefung im Dispatcher: nur liste.json und dateien/, nur reguläre Dateien ohne Link, jede Größe
    wie angegeben, jede ID gleich dem SHA-1 der Bytes, job und basis wie im Auftrag. Jede Abweichung wirft AuszugFehler mit Grund
    pruefung_fehler; ein Fehler des Auszugs kommt als Ergebnis mit Status fehler und seinem Grund zurück."""
    o = _Ordner(Path(ordner))
    try:
        roh = o.lesen(LISTE, MAX_LISTE_BYTES)
        try:
            liste = json.loads(roh.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as e:  # tiefe Schachtelung aus der Sandbox: RecursionError
            raise AuszugFehler(GRUND_FEHLER, "liste.json") from e
        if not isinstance(liste, dict) or type(liste.get("v")) is not int or liste.get("v") != VERSION:
            raise AuszugFehler(GRUND_FEHLER, "Version")
        namen = set(o.namen())
        if liste.get("status") == "fehler":
            if set(liste) != FELDER_FEHLER or liste["grund"] not in GRUENDE or not namen <= {LISTE, DATEIEN}:
                raise AuszugFehler(GRUND_FEHLER, "Fehlerliste")
            return Ergebnis(status="fehler", grund=liste["grund"], spitze=None, commits=0, eintraege=())
        if liste.get("status") != "ok" or set(liste) != FELDER_OK:
            raise AuszugFehler(GRUND_FEHLER, "Status")
        if liste["job"] != job or liste["basis"] != basis or not isinstance(liste["spitze"], str) \
                or not OID_RE.fullmatch(liste["spitze"]):
            raise AuszugFehler(GRUND_FEHLER, "Auftrag")
        commits = _ganz(liste["commits"], grenzen.commits)
        roh_eintraege = liste["eintraege"]
        if not isinstance(roh_eintraege, list) or len(roh_eintraege) > grenzen.eintraege:
            raise AuszugFehler(GRUND_FEHLER, "Einträge")
        eintraege, dateien, gesehen, gesamt = [], [], set(), 0
        for roh_eintrag in roh_eintraege:
            eintrag, datei, groesse = _eintrag_pruefen(roh_eintrag, len(dateien), grenzen)
            if eintrag.pfad in gesehen:
                raise AuszugFehler(GRUND_FEHLER, "Pfad doppelt")
            gesehen.add(eintrag.pfad)
            if datei is not None:
                inhalt = o.lesen(datei, grenzen.datei_bytes, genau=groesse)
                if hashlib.sha1(b"blob %d\x00" % len(inhalt) + inhalt).hexdigest() != eintrag.oid:
                    raise AuszugFehler(GRUND_FEHLER, "Prüfsumme")
                gesamt += len(inhalt)
                dateien.append(datei.split("/", 1)[1])
                eintrag = dataclasses.replace(eintrag, inhalt=inhalt)
            eintraege.append(eintrag)
        if len(dateien) > grenzen.dateien or gesamt > grenzen.gesamt_bytes:
            raise AuszugFehler(GRUND_FEHLER, "Grenzen")
        erwartet = {LISTE, DATEIEN} if dateien or DATEIEN in namen else {LISTE}
        if namen != erwartet or (DATEIEN in namen and sorted(o.namen(DATEIEN)) != sorted(dateien)):
            raise AuszugFehler(GRUND_FEHLER, "fremde Einträge im Ergebnis")
        return Ergebnis(status="ok", grund=None, spitze=liste["spitze"], commits=commits, eintraege=tuple(eintraege))
    finally:
        o.close()


# ---------------------------------------------------------------- Programm
def _grenzen_setzen() -> None:
    """Zusätzlich zu ulimit in wamo-job.sh: Speicher, Dateigröße, Zahl offener Dateien und CPU-Zeit (nur Linux)."""
    try:
        import resource
    except ImportError:
        return
    for name, wert in (("RLIMIT_AS", 2 * 1024 ** 3), ("RLIMIT_FSIZE", 256 * 1024 ** 2), ("RLIMIT_NOFILE", 256),
                       ("RLIMIT_CPU", 120), ("RLIMIT_CORE", 0)):
        art = getattr(resource, name, None)
        if art is None:
            continue
        try:
            weich, hart = resource.getrlimit(art)
            ziel = wert if hart == resource.RLIM_INFINITY else min(wert, hart)
            resource.setrlimit(art, (ziel, hart))
        except (ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auszug einer Änderung aus dem Bundle der Sandbox (Plan C, Schritt pruefung)")
    parser.add_argument("--job", required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--basis-git", default=BASIS_GIT)
    parser.add_argument("--bundle", default=BUNDLE)
    parser.add_argument("--ergebnis", default=ERGEBNIS)
    parser.add_argument("--arbeit", default=None)
    args = parser.parse_args(argv)
    _grenzen_setzen()
    os.umask(0o077)
    try:
        arbeit = args.arbeit or tempfile.mkdtemp(prefix="wamo-auszug-")
        daten = auszug(args.job, args.basis, basis_git=args.basis_git, bundle=args.bundle, ergebnis=args.ergebnis,
                       arbeit=tempfile.mkdtemp(prefix="lauf-", dir=arbeit))
    except AuszugFehler as e:
        print(f"wamo-auszug: {e.grund}", file=sys.stderr)
        return 2
    except OSError as e:  # Ergebnis- oder Arbeitsordner nicht nutzbar: wie ein ungültiger Aufruf, der Dispatcher meldet pruefung_fehler
        print(f"wamo-auszug: Ordner nicht nutzbar ({type(e).__name__})", file=sys.stderr)
        return 2
    print(f"wamo-auszug: {daten['status']}" + (f" {daten['grund']}" if daten["status"] != "ok" else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
