"""Prüfregel für das Manifest des Installers (Ablage wamo-verteilung, Paket P2 in docs/ausrollen-neue-nutzer.md, Abschnitt 4.2).

Eine Regel für beide Seiten: Das Einrichtungsskript am Server (wamo-verteilung-einrichten.sh) ruft dieses Modul als Kommandozeile auf
(python3 -X utf8 -B -I), das lokale Werkzeug scripts/wamo_installer_sokrates2.py importiert es über den Pfad. Nur Standardbibliothek,
Python 3.10 oder neuer. Geprüft werden immer die exakten Bytes von aktuell.json, nie eine neu serialisierte Fassung. Die Ed25519-Prüfung
macht dieses Modul nicht (am Server fehlt womöglich cryptography): Am Server prüft openssl (dafür gibt es den Befehl pem), lokal das
Paket cryptography.

Format von aktuell.json: genau ein JSON-Objekt, UTF-8 ohne BOM, höchstens 4096 Byte, genau die Schlüssel v, produkt, version, datei,
groesse, sha256, bauzeit, commit. aktuell.json.sig: eine Zeile Base64 (Standardalphabet, mit Auffüllung) der 64 Byte Ed25519-Signatur
über die exakten Bytes von aktuell.json, optional mit LF am Ende. Schlüsselliste: JSON-Liste von Base64-Texten zu je 32 rohen Byte.

Befehle (Exit 0 ok, 1 Prüfung fehlgeschlagen, 2 falscher Aufruf; Meldungen deutsch auf stderr, Ausgaben mit LF auf stdout):
  pruefen <manifest> <exe>        Manifest gültig, Dateiname, Größe und SHA-256 der Datei wie im Manifest
  version <manifest>              Manifest gültig, gibt die Version aus
  vergleich <a> <b>               gibt groesser, gleich oder kleiner aus (a gegenüber b, numerisch je Teil)
  sortieren <version> ...         gibt die Versionen absteigend aus, eine je Zeile
  stand <ordner>                  <ordner>/aktuell.json gültig, gibt "version sha256 groesse commit datei" aus (datei: ok, fehlt, abweichend)
  signatur <sig> <ausgabe>        Signaturdatei prüfen, die 64 rohen Byte nach <ausgabe> schreiben
  pem <schluessel.json> <ordner>  je Schlüssel der Liste eine Datei schluessel-<n>.pem in <ordner> schreiben, gibt die Zahl aus
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys

PRODUKT = "wais-desktop"
SCHLUESSEL = ("v", "produkt", "version", "datei", "groesse", "sha256", "bauzeit", "commit")
MAX_MANIFEST = 4096
MAX_GROESSE = 536_870_912
MAX_SIGNATUR = 128
MAX_SCHLUESSELLISTE = 16_384
MAX_SCHLUESSEL = 16
DER_PRAEFIX = bytes.fromhex("302a300506032b6570032100")  # SubjectPublicKeyInfo für Ed25519, danach die 32 rohen Byte

# Nur ASCII-Ziffern ([0-9] statt \d) und fullmatch statt $ (kein Zeilenende am Schluss)
VERSION_RE = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
BAUZEIT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z")
SIGNATUR_RE = re.compile(rb"[A-Za-z0-9+/]{86}==")
SCHLUESSEL_RE = re.compile(r"[A-Za-z0-9+/]{43}=")


class _Fehler(ValueError):
    """Ein Prüffehler aus den Hooks des JSON-Lesers, damit er nicht als allgemeiner JSON-Fehler endet."""


def _zeige(wert: object) -> str:
    """Ein Wert aus der Eingabe für eine Meldung: nur ASCII, ohne Steuerzeichen, gekürzt."""
    text = ascii(wert)
    return text if len(text) <= 60 else text[:57] + "..."


def dateiname(version: str) -> str:
    return f"WAIS-Setup-{version}.exe"


def _ohne_doppelte(paare: list[tuple[str, object]]) -> dict:
    d: dict = {}
    for name, wert in paare:
        if name in d:
            raise _Fehler(f"Das Feld {_zeige(name)} kommt doppelt vor.")
        d[name] = wert
    return d


def _keine_konstante(name: str) -> object:
    raise _Fehler(f"Der Wert {_zeige(name)} ist in JSON nicht erlaubt.")


def _json_lesen(roh: bytes, was: str) -> object:
    if roh.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{was} beginnt mit einer Bytereihenfolge-Marke (BOM), erlaubt ist UTF-8 ohne BOM.")
    try:
        text = roh.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{was} ist kein gültiges UTF-8.") from None
    try:
        return json.loads(text, object_pairs_hook=_ohne_doppelte, parse_constant=_keine_konstante)
    except _Fehler as e:
        raise ValueError(f"{was}: {e}") from None
    except (ValueError, RecursionError):
        raise ValueError(f"{was} ist kein gültiges JSON.") from None


def version_tupel(text: object) -> tuple[int, int, int]:
    """Die drei Teile einer Version als Zahlen; wirft ValueError bei jeder anderen Form."""
    m = VERSION_RE.fullmatch(text) if isinstance(text, str) else None
    if m is None:
        raise ValueError(f"Die Version {_zeige(text)} hat nicht die Form Zahl.Zahl.Zahl (je 0 bis 9999, ohne führende Null).")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def version_groesser(a: str, b: str) -> bool:
    """True, wenn a numerisch je Teil größer ist als b (0.10.0 > 0.9.9)."""
    return version_tupel(a) > version_tupel(b)


def manifest_pruefen(roh: bytes) -> dict:
    """Prüft die exakten Bytes von aktuell.json und gibt das Objekt zurück. Wirft ValueError mit einem deutschen Satz."""
    if not isinstance(roh, (bytes, bytearray)):
        raise ValueError("Das Manifest muss als Bytes vorliegen.")
    roh = bytes(roh)
    if not roh:
        raise ValueError("Das Manifest ist leer.")
    if len(roh) > MAX_MANIFEST:
        raise ValueError(f"Das Manifest ist größer als {MAX_MANIFEST} Byte.")
    daten = _json_lesen(roh, "Das Manifest")
    if not isinstance(daten, dict):
        raise ValueError("Das Manifest ist kein JSON-Objekt.")
    unbekannt = sorted(set(daten) - set(SCHLUESSEL))
    if unbekannt:
        raise ValueError(f"Unbekannte Felder im Manifest: {', '.join(_zeige(n) for n in unbekannt[:5])}.")
    fehlend = [n for n in SCHLUESSEL if n not in daten]
    if fehlend:
        raise ValueError(f"Im Manifest fehlen Felder: {', '.join(fehlend)}.")
    if type(daten["v"]) is not int or daten["v"] != 1:
        raise ValueError("Das Feld v muss die ganze Zahl 1 sein.")
    if daten["produkt"] != PRODUKT:
        raise ValueError(f"Das Feld produkt muss {PRODUKT} sein.")
    version = daten["version"]
    version_tupel(version)
    if daten["datei"] != dateiname(version):
        raise ValueError(f"Das Feld datei muss {dateiname(version)} sein.")
    groesse = daten["groesse"]
    if type(groesse) is not int or not 1 <= groesse <= MAX_GROESSE:
        raise ValueError(f"Das Feld groesse muss eine ganze Zahl von 1 bis {MAX_GROESSE} sein.")
    if not isinstance(daten["sha256"], str) or not SHA256_RE.fullmatch(daten["sha256"]):
        raise ValueError("Das Feld sha256 muss aus 64 Zeichen 0 bis 9 und a bis f bestehen.")
    if not isinstance(daten["bauzeit"], str) or not BAUZEIT_RE.fullmatch(daten["bauzeit"]):
        raise ValueError("Das Feld bauzeit muss die Form JJJJ-MM-TTTHH:MM:SS mit optional bis zu drei Nachkommastellen und Z haben.")
    if not isinstance(daten["commit"], str) or not COMMIT_RE.fullmatch(daten["commit"]):
        raise ValueError("Das Feld commit muss aus 40 Zeichen 0 bis 9 und a bis f bestehen.")
    return {n: daten[n] for n in SCHLUESSEL}


def signatur_lesen(roh: bytes) -> bytes:
    """Die 64 rohen Byte einer Signaturdatei (eine Zeile Base64, optional mit LF am Ende). Wirft ValueError."""
    roh = bytes(roh)
    if len(roh) > MAX_SIGNATUR:
        raise ValueError("Die Signaturdatei ist zu groß.")
    if roh.endswith(b"\n"):
        roh = roh[:-1]
    if not SIGNATUR_RE.fullmatch(roh):
        raise ValueError("Die Signatur ist keine Zeile Base64 für 64 Byte (Standardalphabet mit Auffüllung).")
    sig = base64.b64decode(roh, validate=True)
    if len(sig) != 64 or base64.b64encode(sig) != roh:
        raise ValueError("Die Signatur ist nicht in der kanonischen Base64-Form.")
    return sig


def schluessel_lesen(roh: bytes) -> list[bytes]:
    """Die öffentlichen Schlüssel einer Liste (JSON-Liste von Base64-Texten zu je 32 rohen Byte). Wirft ValueError."""
    roh = bytes(roh)
    if len(roh) > MAX_SCHLUESSELLISTE:
        raise ValueError("Die Schlüsselliste ist zu groß.")
    daten = _json_lesen(roh, "Die Schlüsselliste")
    if not isinstance(daten, list) or not daten:
        raise ValueError("Die Schlüsselliste muss eine nicht leere JSON-Liste sein.")
    if len(daten) > MAX_SCHLUESSEL:
        raise ValueError(f"Die Schlüsselliste hat mehr als {MAX_SCHLUESSEL} Einträge.")
    aus = []
    for nr, eintrag in enumerate(daten, 1):
        if not isinstance(eintrag, str) or not SCHLUESSEL_RE.fullmatch(eintrag):
            raise ValueError(f"Eintrag {nr} der Schlüsselliste ist kein Base64-Text für 32 Byte.")
        schluessel = base64.b64decode(eintrag, validate=True)
        if len(schluessel) != 32 or base64.b64encode(schluessel).decode("ascii") != eintrag:
            raise ValueError(f"Eintrag {nr} der Schlüsselliste ist nicht in der kanonischen Base64-Form.")
        aus.append(schluessel)
    return aus


def pem_text(schluessel: bytes) -> str:
    """Ein roher Ed25519-Schlüssel (32 Byte) als PEM (SubjectPublicKeyInfo), so wie ihn openssl pkeyutl -pubin liest."""
    if len(schluessel) != 32:
        raise ValueError("Ein Ed25519-Schlüssel hat genau 32 Byte.")
    return "-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(DER_PRAEFIX + schluessel).decode("ascii") + "\n-----END PUBLIC KEY-----\n"


def _oeffnen(pfad: str, flags: int, modus: int = 0o600) -> int:
    return os.open(pfad, flags | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), modus)


def datei_lesen(pfad: str | os.PathLike, grenze: int) -> bytes:
    """Liest eine reguläre Datei (kein Link) mit höchstens grenze Byte. Wirft ValueError."""
    pfad = os.fspath(pfad)
    try:
        if stat.S_ISLNK(os.lstat(pfad).st_mode):
            raise ValueError(f"{pfad} ist ein Link, erlaubt ist nur eine reguläre Datei.")
        fd = _oeffnen(pfad, os.O_RDONLY)
    except FileNotFoundError:
        raise ValueError(f"{pfad} fehlt.") from None
    except OSError:
        raise ValueError(f"{pfad} ist nicht lesbar.") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError(f"{pfad} ist keine reguläre Datei.")
        roh = f.read(grenze + 1)
    if len(roh) > grenze:
        raise ValueError(f"{pfad} ist größer als {grenze} Byte.")
    return roh


def sha256_datei(pfad: str | os.PathLike) -> tuple[str, int]:
    """SHA-256 (hex) und Zahl der gelesenen Byte einer regulären Datei, ohne einem Link zu folgen."""
    h = hashlib.sha256()
    n = 0
    fd = _oeffnen(os.fspath(pfad), os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError(f"{os.fspath(pfad)} ist keine reguläre Datei.")
        while block := f.read(1 << 20):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def datei_pruefen(manifest: dict, pfad: str | os.PathLike) -> None:
    """Dateiname, Größe und SHA-256 der Installationsdatei wie im Manifest. Wirft ValueError."""
    pfad = os.fspath(pfad)
    if os.path.basename(pfad) != manifest["datei"]:
        raise ValueError(f"Der Dateiname passt nicht zum Manifest (erwartet {manifest['datei']}).")
    try:
        st = os.lstat(pfad)
    except FileNotFoundError:
        raise ValueError(f"Die Installationsdatei {manifest['datei']} fehlt.") from None
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Die Installationsdatei {manifest['datei']} ist keine reguläre Datei (Links sind nicht erlaubt).")
    if st.st_size != manifest["groesse"]:
        raise ValueError(f"Die Größe stimmt nicht: {st.st_size} Byte, im Manifest {manifest['groesse']} Byte.")
    summe, n = sha256_datei(pfad)
    if n != manifest["groesse"] or summe != manifest["sha256"]:
        raise ValueError("Die SHA-256-Prüfsumme der Installationsdatei stimmt nicht mit dem Manifest überein.")


def datei_zustand(manifest: dict, pfad: str | os.PathLike) -> str:
    """ok, fehlt oder abweichend (für den Status)."""
    if not os.path.lexists(pfad):
        return "fehlt"
    try:
        datei_pruefen(manifest, pfad)
    except (ValueError, OSError):
        return "abweichend"
    return "ok"


# ---------------------------------------------------------------- Kommandozeile


def _aus(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))  # immer LF, auch unter Windows
    sys.stdout.buffer.flush()


def _meldung(text: str) -> None:
    sys.stderr.buffer.write(("wamo-verteilung: " + text + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()


def _schreiben(pfad: str, daten: bytes) -> None:
    fd = _oeffnen(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "wb") as f:
        f.write(daten)


AUFRUF = ("Aufruf: wamo_verteilung_manifest.py pruefen <manifest> <exe> | version <manifest> | vergleich <a> <b> | sortieren <version> ... | "
          "stand <ordner> | signatur <sig> <ausgabe> | pem <schluessel.json> <ordner>")
STELLEN = {"pruefen": 2, "version": 1, "vergleich": 2, "stand": 1, "signatur": 2, "pem": 2}


def _befehl(name: str, args: list[str]) -> None:
    if name == "pruefen":
        manifest = manifest_pruefen(datei_lesen(args[0], MAX_MANIFEST))
        datei_pruefen(manifest, args[1])
        _aus(f"Manifest gültig: {manifest['datei']}, Version {manifest['version']}, {manifest['groesse']} Byte, SHA-256 {manifest['sha256']}")
    elif name == "version":
        _aus(manifest_pruefen(datei_lesen(args[0], MAX_MANIFEST))["version"])
    elif name == "vergleich":
        a, b = version_tupel(args[0]), version_tupel(args[1])
        _aus("groesser" if a > b else "gleich" if a == b else "kleiner")
    elif name == "sortieren":
        for version in sorted(args, key=version_tupel, reverse=True):
            _aus(version)
    elif name == "stand":
        manifest = manifest_pruefen(datei_lesen(os.path.join(args[0], "aktuell.json"), MAX_MANIFEST))
        zustand = datei_zustand(manifest, os.path.join(args[0], manifest["datei"]))
        _aus(f"{manifest['version']} {manifest['sha256']} {manifest['groesse']} {manifest['commit']} {zustand}")
    elif name == "signatur":
        _schreiben(args[1], signatur_lesen(datei_lesen(args[0], MAX_SIGNATUR)))
    elif name == "pem":
        liste = schluessel_lesen(datei_lesen(args[0], MAX_SCHLUESSELLISTE))
        if not os.path.isdir(args[1]) or os.path.islink(args[1]):
            raise ValueError(f"{args[1]} ist kein Ordner.")
        for nr, schluessel in enumerate(liste, 1):
            _schreiben(os.path.join(args[1], f"schluessel-{nr}.pem"), pem_text(schluessel).encode("ascii"))
        _aus(str(len(liste)))


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in (*STELLEN, "sortieren"):
        _meldung(AUFRUF)
        return 2
    name, args = argv[0], argv[1:]
    if (name == "sortieren" and not args) or (name != "sortieren" and len(args) != STELLEN[name]):
        _meldung(AUFRUF)
        return 2
    try:
        _befehl(name, args)
    except ValueError as e:
        _meldung(str(e))
        return 1
    except OSError as e:
        _meldung(f"Datei nicht lesbar oder nicht schreibbar: {_zeige(e.filename)}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
