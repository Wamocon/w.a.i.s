"""Bringt den Installer der Desktop-App (WAIS-Setup-<Version>.exe) vom PC in die Ablage auf Sokrates-2 (Paket P2, docs/ausrollen-neue-nutzer.md,
Abschnitt 4.2; Ablage und Skript am Server: infra/sokrates2/README.md, Abschnitt 22). Kennt keine Geheimnisse und gibt keine aus.

Befehle (im Repo-Hauptordner, mit der Python-Umgebung von voice-core, dort liegt cryptography):
  python scripts/wamo_installer_sokrates2.py pruefen <exe> [--manifest P] [--signatur P] [--schluessel P]
        nur lokal: Manifest (Standard: aktuell.json neben der exe), Dateiname, Größe, SHA-256 und Signatur (Standard: <Manifest>.sig, falls es sie
        gibt) gegen die Schlüsselliste (Standard: desktop/update-schluessel.json, falls es sie gibt). Mit Schlüsselliste ist eine gültige Signatur
        Pflicht, ohne Liste gibt es nur einen Hinweis.
  python scripts/wamo_installer_sokrates2.py manifest <exe> --commit <40 hex> [--bauzeit ISO] --aus <ordner>
        schreibt <ordner>/aktuell.json für einen Stand ohne Signatur (zum Beispiel 0.2.0): kompakt, ohne Zeilenende, Felder in fester Reihenfolge.
        Ein vorhandenes aktuell.json oder aktuell.json.sig wird nie überschrieben.
  python scripts/wamo_installer_sokrates2.py verteilen <exe> [--manifest P] [--signatur P] [--trocken]
        prüft wie pruefen, fragt am Server "status --json" ab und bricht ohne streng steigende Version ab, bevor etwas kopiert wird. Dann kopiert es
        Manifest, Signatur und exe per scp nach ~/wamo-verteilung-eingang/<Version>/ und ruft dort
        "sudo bash ~/wamo-infra/wamo-verteilung-einrichten.sh einsetzen ~/wamo-verteilung-eingang/<Version> [--trocken]" auf. Nach einem
        erfolgreichen Lauf wird der Eingang am Server geleert, nach einem Fehler bleibt er zur Prüfung liegen.
  python scripts/wamo_installer_sokrates2.py status
  python scripts/wamo_installer_sokrates2.py rueckweg [--trocken] [--ohne-signatur]

Die Prüfregel des Manifests kommt aus infra/sokrates2/wamo_verteilung_manifest.py, dieselbe Datei prüft am Server. Das Skript am Server muss dort
schon liegen (python scripts/wamo_kern_sokrates2.py verteilen bringt infra/sokrates2 nach ~/wamo-infra). scripts/wamo-dist-pruefen.cjs prüft nur
den entpackten Ordner win-unpacked und nicht die fertige exe, es gehört deshalb zum Bau (npm run dist:pruefen in desktop/) und wird hier nicht
aufgerufen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODUL = ROOT / "infra" / "sokrates2" / "wamo_verteilung_manifest.py"
_spec = importlib.util.spec_from_file_location("wamo_verteilung_manifest", MODUL)
regel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regel)

HOST = os.environ.get("WAMO_SSH_HOST", "wamo-sokrates2")  # SSH-Alias des Dienstkontos wamocon (~/.ssh/config), per WAMO_SSH_HOST änderbar
SKRIPT = "~/wamo-infra/wamo-verteilung-einrichten.sh"
EINGANG = "wamo-verteilung-eingang"  # relativ zum Home von wamocon
SCHLUESSEL_DATEI = ROOT / "desktop" / "update-schluessel.json"
SSH_OPTIONEN = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15"]
SSH_ZEIT = 300    # Sekunden für einen Befehl am Server (einsetzen rechnet die SHA-256 von etwa 117 MB zweimal)
SCP_ZEIT = 1800   # Sekunden für das Kopieren einer Datei
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
EXE_RE = re.compile(r"WAIS-Setup-(.{5,14})\.exe")


class Abbruch(Exception):
    """Ein Grund, vor der nächsten Änderung aufzuhören (ein deutscher Satz)."""


@dataclass(frozen=True)
class Lieferung:
    exe: Path
    manifest_pfad: Path
    manifest: dict
    signatur_pfad: Path | None
    signatur: str  # gueltig, ungeprueft (keine Schlüsselliste) oder keine


def _lesen(pfad: Path, grenze: int) -> bytes:
    try:
        return regel.datei_lesen(pfad, grenze)
    except ValueError as e:
        raise Abbruch(str(e)) from None


def ed25519_gueltig(schluessel: list[bytes], signatur: bytes, daten: bytes) -> bool:
    """True, wenn die Signatur über die exakten Bytes zu irgendeinem Schlüssel der Liste passt."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    for roh in schluessel:
        try:
            Ed25519PublicKey.from_public_bytes(roh).verify(signatur, daten)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


def lieferung_pruefen(exe: Path, manifest_pfad: Path | None = None, signatur_pfad: Path | None = None,
                      schluessel_pfad: Path | None = None) -> Lieferung:
    """Manifest, Dateiname, Größe, SHA-256 und Signatur einer Lieferung. Wirft Abbruch."""
    exe = Path(exe)
    manifest_pfad = Path(manifest_pfad) if manifest_pfad else exe.parent / "aktuell.json"
    roh = _lesen(manifest_pfad, regel.MAX_MANIFEST)
    try:
        manifest = regel.manifest_pruefen(roh)
        regel.datei_pruefen(manifest, exe)
    except ValueError as e:
        raise Abbruch(str(e)) from None
    if signatur_pfad is None:
        kandidat = Path(str(manifest_pfad) + ".sig")
        signatur_pfad = kandidat if kandidat.exists() else None
    signatur = None
    if signatur_pfad is not None:
        try:
            signatur = regel.signatur_lesen(_lesen(Path(signatur_pfad), regel.MAX_SIGNATUR))
        except ValueError as e:
            raise Abbruch(f"{signatur_pfad}: {e}") from None
    if schluessel_pfad is None and SCHLUESSEL_DATEI.exists():
        schluessel_pfad = SCHLUESSEL_DATEI
    if schluessel_pfad is None:
        stand = "ungeprueft" if signatur is not None else "keine"
        try:
            anzeige = SCHLUESSEL_DATEI.relative_to(ROOT).as_posix()
        except ValueError:
            anzeige = str(SCHLUESSEL_DATEI)
        print(f"Hinweis: {anzeige} fehlt, die Signatur wird lokal nicht geprüft"
              f" ({'Signatur vorhanden' if signatur is not None else 'unsignierter Stand, nur als Übergang für 0.2.0'}).", file=sys.stderr)
    else:
        try:
            liste = regel.schluessel_lesen(_lesen(Path(schluessel_pfad), regel.MAX_SCHLUESSELLISTE))
        except ValueError as e:
            raise Abbruch(f"{schluessel_pfad}: {e}") from None
        if signatur is None:
            raise Abbruch(f"Die Signatur fehlt. Mit der Schlüsselliste {schluessel_pfad} ist eine gültige Signatur Pflicht.")
        if not ed25519_gueltig(liste, signatur, roh):
            raise Abbruch(f"Die Signatur passt zu keinem Schlüssel der Liste {schluessel_pfad}.")
        stand = "gueltig"
    return Lieferung(exe, manifest_pfad, manifest, Path(signatur_pfad) if signatur_pfad else None, stand)


def zeigen(lief: Lieferung) -> None:
    m = lief.manifest
    signatur = {"gueltig": "gültig", "ungeprueft": "vorhanden, nicht geprüft", "keine": "keine"}[lief.signatur]
    print(f"Lieferung geprüft: {m['datei']}, Version {m['version']}, {m['groesse']} Byte")
    print(f"  SHA-256 {m['sha256']}")
    print(f"  Commit {m['commit']}, Bauzeit {m['bauzeit']}, Signatur: {signatur}")


# ---------------------------------------------------------------- manifest
def jetzt() -> str:
    t = dt.datetime.now(dt.timezone.utc)
    return f"{t:%Y-%m-%dT%H:%M:%S}.{t.microsecond // 1000:03d}Z"


def manifest_erzeugen(exe: Path, commit: str, bauzeit: str | None = None) -> bytes:
    """Die Bytes von aktuell.json für eine exe: kompakt, Felder in der Reihenfolge von regel.SCHLUESSEL. Wirft Abbruch."""
    exe = Path(exe)
    m = EXE_RE.fullmatch(exe.name)
    try:
        if m is None:
            raise ValueError("Der Dateiname muss WAIS-Setup-<Version>.exe sein.")
        version = m.group(1)
        regel.version_tupel(version)
        if not exe.is_file() or exe.is_symlink():
            raise ValueError(f"{exe} ist keine reguläre Datei.")
        summe, groesse = regel.sha256_datei(exe)
        daten = {"v": 1, "produkt": regel.PRODUKT, "version": version, "datei": regel.dateiname(version), "groesse": groesse,
                 "sha256": summe, "bauzeit": bauzeit or jetzt(), "commit": commit}
        roh = json.dumps({n: daten[n] for n in regel.SCHLUESSEL}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        regel.manifest_pruefen(roh)
    except (ValueError, OSError) as e:
        raise Abbruch(str(e)) from None
    return roh


def manifest_schreiben(ordner: Path, roh: bytes) -> Path:
    ziel = Path(ordner) / "aktuell.json"
    if not Path(ordner).is_dir():
        raise Abbruch(f"{ordner} ist kein Ordner.")
    for vorhanden in (ziel, Path(ordner) / "aktuell.json.sig"):
        if vorhanden.exists() or vorhanden.is_symlink():
            raise Abbruch(f"{vorhanden} gibt es schon. Nichts überschrieben (zuerst entfernen, eine alte Signatur passt nie zu einem neuen Manifest).")
    with open(ziel, "xb") as f:
        f.write(roh)
    return ziel


# ---------------------------------------------------------------- Server
def ssh(befehl: str, ausgabe: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        r = subprocess.run(["ssh", *SSH_OPTIONEN, HOST, befehl], capture_output=True, timeout=SSH_ZEIT)
    except subprocess.TimeoutExpired:
        raise Abbruch(f"Keine Antwort von {HOST} in {SSH_ZEIT} Sekunden.") from None
    if ausgabe and r.stdout:
        sys.stdout.buffer.write(r.stdout)
        sys.stdout.flush()
    if (ausgabe or r.returncode != 0) and r.stderr:
        sys.stderr.buffer.write(r.stderr)
        sys.stderr.flush()
    return r


def scp(lokal: Path, ziel: str) -> None:
    try:
        r = subprocess.run(["scp", "-q", *SSH_OPTIONEN, str(lokal), f"{HOST}:{ziel}"], capture_output=True, timeout=SCP_ZEIT)
    except subprocess.TimeoutExpired:
        raise Abbruch(f"Kopieren nach {HOST}:~/{ziel} dauerte länger als {SCP_ZEIT} Sekunden. Am Server wurde nichts eingesetzt.") from None
    if r.returncode != 0:
        sys.stderr.buffer.write(r.stderr)
        raise Abbruch(f"Kopieren nach {HOST}:~/{ziel} ist fehlgeschlagen. Am Server wurde nichts eingesetzt.")


def status_holen() -> dict:
    """Der Stand am Server (status --json). Alles Unklare ist ein Abbruch, bevor etwas kopiert wird."""
    r = ssh(f"sudo bash {SKRIPT} status --json", ausgabe=False)
    if r.returncode != 0:
        raise Abbruch("Der Stand am Server ließ sich nicht abfragen (siehe oben). Nichts wurde kopiert.")
    try:
        d = json.loads(r.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Abbruch("Der Server lieferte keinen lesbaren Stand (JSON). Nichts wurde kopiert.") from None
    if (not isinstance(d, dict) or type(d.get("v")) is not int or d["v"] != 1 or not isinstance(d.get("schluesselliste"), bool)
            or "aktuell" not in d):
        raise Abbruch("Der Stand vom Server hat nicht das erwartete Format. Nichts wurde kopiert.")
    aktuell = d.get("aktuell")
    if aktuell is not None:
        try:
            if not isinstance(aktuell, dict):
                raise ValueError("kein Objekt")
            regel.version_tupel(aktuell.get("version"))
        except ValueError:
            raise Abbruch("Die aktuelle Version am Server ist unklar. Nichts wurde kopiert.") from None
    return d


def verteilen(exe: Path, manifest_pfad: Path | None, signatur_pfad: Path | None, trocken: bool) -> int:
    lief = lieferung_pruefen(exe, manifest_pfad, signatur_pfad)
    zeigen(lief)
    version = lief.manifest["version"]
    stand = status_holen()
    alt = stand["aktuell"]["version"] if stand["aktuell"] else None
    if alt is not None and not regel.version_groesser(version, alt):
        raise Abbruch(f"Version {version} ist nicht neuer als der aktuelle Stand am Server ({alt}). Nichts wurde kopiert.")
    if stand["schluesselliste"] and lief.signatur_pfad is None:
        raise Abbruch("Am Server liegt eine Schlüsselliste, dort ist eine gültige Signatur Pflicht. Nichts wurde kopiert.")
    print(f"Am Server: {'aktuell ' + alt if alt else 'noch kein Stand'}, Schlüsselliste {'ja' if stand['schluesselliste'] else 'nein'}")
    ordner = f"{EINGANG}/{version}"
    r = ssh(f"mkdir -p -m 0700 ~/{EINGANG} && rm -rf ~/{ordner} && mkdir -m 0700 ~/{ordner}")
    if r.returncode != 0:
        raise Abbruch(f"Der Eingang ~/{ordner} ließ sich am Server nicht anlegen.")
    scp(lief.manifest_pfad, f"{ordner}/aktuell.json")
    if lief.signatur_pfad is not None:
        scp(lief.signatur_pfad, f"{ordner}/aktuell.json.sig")
    scp(lief.exe, f"{ordner}/{lief.manifest['datei']}")
    print(f"Kopiert nach {HOST}:~/{ordner}")
    rc = ssh(f"sudo bash {SKRIPT} einsetzen ~/{ordner}" + (" --trocken" if trocken else "")).returncode
    if rc != 0:
        print(f"Einsetzen am Server ist gescheitert (Exit {rc}). Der Eingang ~/{ordner} bleibt zur Prüfung liegen.", file=sys.stderr)
        return rc
    ssh(f"rm -rf ~/{ordner}", ausgabe=False)
    print("Trockenlauf am Server bestanden, nichts eingesetzt." if trocken else f"Version {version} ist am Server eingesetzt.")
    return 0


# ---------------------------------------------------------------- Kommandozeile
def _commit(text: str) -> str:
    if not COMMIT_RE.fullmatch(text):
        raise argparse.ArgumentTypeError("40 Zeichen 0 bis 9 und a bis f erwartet")
    return text


def _bauzeit(text: str) -> str:
    if not regel.BAUZEIT_RE.fullmatch(text):
        raise argparse.ArgumentTypeError("Form JJJJ-MM-TTTHH:MM:SS.mmmZ erwartet (UTC)")
    return text


def parser_bauen() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Installer der Desktop-App in die Ablage auf Sokrates-2 bringen (Paket P2)")
    befehle = p.add_subparsers(dest="befehl", required=True)
    a = befehle.add_parser("pruefen", help="nur lokal: Manifest, Datei und Signatur prüfen")
    a.add_argument("exe", type=Path)
    a.add_argument("--manifest", type=Path, help="Standard: aktuell.json neben der exe")
    a.add_argument("--signatur", type=Path, help="Standard: <Manifest>.sig, falls es sie gibt")
    a.add_argument("--schluessel", type=Path, help="Standard: desktop/update-schluessel.json, falls es sie gibt")
    m = befehle.add_parser("manifest", help="aktuell.json für einen Stand ohne Signatur schreiben")
    m.add_argument("exe", type=Path)
    m.add_argument("--commit", required=True, type=_commit)
    m.add_argument("--bauzeit", type=_bauzeit, help="Standard: jetzt (UTC, Millisekunden)")
    m.add_argument("--aus", required=True, type=Path, help="Ordner für aktuell.json")
    v = befehle.add_parser("verteilen", help="prüfen, per scp kopieren und am Server einsetzen")
    v.add_argument("exe", type=Path)
    v.add_argument("--manifest", type=Path)
    v.add_argument("--signatur", type=Path)
    v.add_argument("--trocken", action="store_true", help="am Server nur prüfen (einsetzen --trocken)")
    befehle.add_parser("status", help="Stand der Ablage am Server")
    r = befehle.add_parser("rueckweg", help="am Server aktuell auf vorher stellen")
    r.add_argument("--trocken", action="store_true")
    r.add_argument("--ohne-signatur", action="store_true",
                   help="bewusst auf einen nicht gültig signierten Stand zurück, obwohl am Server die Schlüsselliste liegt")
    return p


def main(argv: list[str] | None = None) -> int:
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8")
    args = parser_bauen().parse_args(argv)
    try:
        if args.befehl == "pruefen":
            zeigen(lieferung_pruefen(args.exe, args.manifest, args.signatur, args.schluessel))
            return 0
        if args.befehl == "manifest":
            ziel = manifest_schreiben(args.aus, manifest_erzeugen(args.exe, args.commit, args.bauzeit))
            print(f"Geschrieben: {ziel} (ohne Signatur)")
            return 0
        if args.befehl == "verteilen":
            return verteilen(args.exe, args.manifest, args.signatur, args.trocken)
        if args.befehl == "status":
            return ssh(f"sudo bash {SKRIPT} status").returncode
        return ssh(f"sudo bash {SKRIPT} rueckweg" + (" --trocken" if args.trocken else "")
                   + (" --ohne-signatur" if args.ohne_signatur else "")).returncode
    except Abbruch as e:
        print(f"Abbruch: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
