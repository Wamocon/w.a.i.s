#!/usr/bin/env python3
"""Sammler der W.A.I.S. Werkstatt: schreibt jede Minute den Stand des Betriebs und gefilterte Protokollzeilen für den Dienst wamo-werkstatt.

Läuft als root (wamo-werkstatt-sammler.service, Zeitgeber jede Minute), nur Standardbibliothek. Er schreibt ausschließlich in den Datenordner (Standard
/var/lib/wamo-werkstatt), atomar (Zwischendatei, fsync, rename), root:wamo-werkstatt 0640:

  betrieb.json              zeit, kern {slot, release, aktiv}, oberflaeche {farbe, version}, installer {version}, kanal {zustand}, labor_dienst {zustand}
  protokolle/<marke>.jsonl  je Zeile genau {zeit, marke, stufe, code, zahlen}

Grundsatz "nie Rohzeilen": Eine Journalzeile wird nur gelesen, wenn sie einem festen Muster der Liste MUSTER unten vollständig entspricht. Aus ihr entsteht
nichts Wörtliches: Der Code kommt aus der festen Liste CODES, die Stufe aus der festen Liste STUFEN, und die Zahlen sind ganze Zahlen aus benannten
Gruppen des Musters (Namen aus ZAHLEN_NAMEN). Namen, Adressen, E-Mails, Hashes und Fehlertexte, die in einer Zeile stehen, werden vom Muster nur
verbraucht und nie ausgegeben. Passt eine Zeile zu keinem Muster, verschwindet sie. Vor dem Schreiben prüft eintrag_pruefen jede Zeile noch einmal, und
betrieb_pruefen den Betriebsstand: Was nicht genau dem Schema entspricht, wird nicht geschrieben.

Je Marke höchstens 2000 Zeilen und höchstens 30 Tage (Entscheidung A4). Der Lesezeiger je Marke (journalctl --cursor-file) liegt in zustand/ (nur root).
Aufruf:  python3 -I -B wamo_werkstatt_sammler.py [--daten ORDNER] [--caddy-dir ORDNER] [--ohne-netz]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone

try:
    import fcntl
except ImportError:  # nur unter Windows (Tests der reinen Funktionen); der Sammler selbst läuft unter Linux
    fcntl = None

sys.dont_write_bytecode = True

DATEN_STANDARD = "/var/lib/wamo-werkstatt"
CADDY_STANDARD = "/home/wamocon/wamo-tls/caddy"
CA_STANDARD = "/etc/wamo-werkstatt/wamo-ca.crt"
GRUPPE = "wamo-werkstatt"
MAX_ZEILEN = 2000
MAX_TAGE = 30
ERSTER_LAUF_STUNDEN = 24
MAX_JOURNAL_BYTES = 4_000_000
MAX_DATEI_BYTES = 65536
SERVER = "https://192.168.178.136"
UMGEBUNG = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}

STUFEN = ("info", "warnung", "fehler")
ZAHLEN_NAMEN = frozenset({"rueckgabe", "trocken", "schritt", "major", "minor", "patch", "ziel", "geloescht", "fehler", "verblieben"})

# ---------------------------------------------------------------------------------------------------- feste Muster-Liste
# Regel: muster (vollständig passend, benannte Gruppen z_<name> für Zahlen), code (fest), stufe (fest) oder eine Funktion Match -> Stufe
Regel = namedtuple("Regel", "muster code stufe")


def _r(muster: str, code: str, stufe) -> Regel:
    return Regel(re.compile(muster), code, stufe)


def _stufe_rueckgabe(m: re.Match) -> str:
    return "info" if m.group("z_rueckgabe") == "0" else "fehler"


def _stufe_ergebnis(m: re.Match) -> str:
    return "info" if m.group("ergebnis") == "ok" else "fehler"


def _stufe_nachweis(m: re.Match) -> str:
    return "info" if m.group("nachweis") == "ok" else "warnung"


BEFEHLE_AUSROLLEN = "pruefen-stand|verteilen|test-kern|test-oberflaeche|prod-kern|prod-oberflaeche|ausleiten|rueckweg|rauchtest|status"
AKTIONEN_NUTZER = "anlegen|freischalten|zuruecksetzen|passwort|umbenennen|sperren|austreten|liste"

MUSTER: dict[str, tuple[Regel, ...]] = {
    # logger -t wais-deploy "befehl=... commit=... teil=... trocken=... rueckgabe=..." (infra/sokrates2/wais-deploy.sh); der Befehl bestimmt den Code
    "wais-deploy": tuple(
        _r(rf"befehl={b} commit=\S{{1,64}} teil=\S{{1,64}} trocken=(?P<trocken>ja|nein) rueckgabe=(?P<z_rueckgabe>\d{{1,3}})", f"ausrollen_{b.replace('-', '_')}", _stufe_rueckgabe)
        for b in BEFEHLE_AUSROLLEN.split("|")),
    # logger -t wamo-job-kern "aktion=... ergebnis=..." (wamo-job-kern-einrichten.sh, wamo-job-kern-rueckweg.sh)
    "wamo-job-kern": (
        _r(r"aktion=schluessel ergebnis=(?P<ergebnis>ok|fehler)", "kern_kanal_schluessel", _stufe_ergebnis),
        _r(r"aktion=kanal ergebnis=(?P<ergebnis>ok|fehler)", "kern_kanal_kanal", _stufe_ergebnis),
        _r(r"aktion=schalter ergebnis=(?P<ergebnis>ok|fehler)", "kern_kanal_schalter", _stufe_ergebnis),
        _r(r"aktion=notaus ergebnis=(?P<ergebnis>ok|fehler)", "kern_kanal_notaus", "warnung"),
    ),
    # logger -t wamo-nutzer "aktion=... schema=... email=... ergebnis=ok|fehler schritt=N" (scripts/wamo_nutzer.py); die E-Mail wird nur verbraucht
    "wamo-nutzer": tuple(
        _r(rf"aktion={a} schema=wamo_(?:dev|test|prod) email=\S{{1,100}} ergebnis=(?P<ergebnis>ok|fehler)(?: schritt=(?P<z_schritt>\d{{1,3}}))?", f"nutzer_{a}", _stufe_ergebnis)
        for a in AKTIONEN_NUTZER.split("|")),
    # logger -t wamo-auth (wamo-auth-einrichten.sh)
    "wamo-auth": (
        _r(r"einrichten: wamo_auth angewendet", "auth_eingerichtet", "info"),
        _r(r"rueckweg: Trigger entfernt, Rechte entzogen", "auth_rueckweg", "warnung"),
    ),
    # logger -t wamo-verteilung (wamo-verteilung-einrichten.sh); Version nur als drei Zahlen, Hashes und Pfade werden nur verbraucht
    "wamo-verteilung": (
        _r(r"einsetzen version=(?P<z_major>\d{1,3})\.(?P<z_minor>\d{1,3})\.(?P<z_patch>\d{1,3})\S{0,40} sha256=\S{1,128} signatur=\S{1,64} vorher=\S{1,64}",
           "verteilung_einsetzen", "info"),
        _r(r"rueckweg aktuell=\S{1,64} zuvor=\S{1,64} signatur=\S{1,64}", "verteilung_rueckweg", "warnung"),
    ),
    # logger -t wamo-labor-geraete (wamo-labor-geraete-aktualisieren.sh); Gerätenamen und Adressen werden nur verbraucht
    "wamo-labor-geraete": (
        _r(r"Gerät \S{1,80}: \S{1,60} zugelassen", "geraet_zugelassen", "info"),
        _r(r"Gerät \S{1,80}: \S{1,60} entfernt \([^()]{0,80}\)", "geraet_entfernt", "info"),
        _r(r"WARNUNG Gerät .{0,300}", "geraet_warnung", "warnung"),
    ),
    # logger -t wamo-labor-loeschen (infra/sokrates2/wamo_labor_konten_loeschen.py); Auswahl und Adressen werden nur verbraucht
    "wamo-labor-loeschen": (
        _r(r"echtlauf start ziel=(?P<z_ziel>\d{1,6})(?: .{0,200})?", "labor_loeschen_start", "info"),
        _r(r"echtlauf ziel=(?P<z_ziel>\d{1,6}) geloescht=(?P<z_geloescht>\d{1,6}) fehler=(?P<z_fehler>\d{1,6}) verblieben=(?P<z_verblieben>\d{1,6}) "
           r"nachweis=(?P<nachweis>ok|offen)(?: .{0,200})?", "labor_loeschen_ende", _stufe_nachweis),
        _r(r"echtlauf abgebrochen .{0,300}", "labor_loeschen_abbruch", "fehler"),
    ),
}
MARKEN = tuple(MUSTER)
CODES = frozenset(r.code for regeln in MUSTER.values() for r in regeln)
CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,47}")
ZEIT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
VERSION_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+.][A-Za-z0-9.+-]{1,20})?")
RELEASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def zeile_auswerten(marke: str, nachricht, prioritaet: int = 6) -> dict | None:
    """Eine Journalzeile -> {code, stufe, zahlen} oder None. Aus der Zeile selbst entsteht nur, was das Muster vorgibt."""
    if marke not in MUSTER or not isinstance(nachricht, str) or len(nachricht) > 600 or "\n" in nachricht or "\r" in nachricht:
        return None
    for regel in MUSTER[marke]:
        m = regel.muster.fullmatch(nachricht)
        if m is None:
            continue
        stufe = regel.stufe(m) if callable(regel.stufe) else regel.stufe
        if prioritaet <= 3:
            stufe = "fehler"
        zahlen = {name[2:]: int(wert) for name, wert in m.groupdict().items() if name.startswith("z_") and wert is not None}
        if "trocken" in m.groupdict() and m.group("trocken") is not None:
            zahlen["trocken"] = 1 if m.group("trocken") == "ja" else 0
        return {"code": regel.code, "stufe": stufe, "zahlen": zahlen}
    return None


def eintrag_pruefen(e) -> bool:
    """Genau {zeit, marke, stufe, code, zahlen}, jedes Feld aus seiner festen Menge: die letzte Sperre vor dem Schreiben und beim Lesen alter Zeilen."""
    if not isinstance(e, dict) or set(e) != {"zeit", "marke", "stufe", "code", "zahlen"}:
        return False
    z = e["zahlen"]
    return (isinstance(e["zeit"], str) and ZEIT_RE.fullmatch(e["zeit"]) is not None and e["marke"] in MARKEN and e["stufe"] in STUFEN
            and isinstance(e["code"], str) and CODE_RE.fullmatch(e["code"]) is not None and e["code"] in CODES
            and isinstance(z, dict) and len(z) <= 6
            and all(k in ZAHLEN_NAMEN and type(v) is int and 0 <= v <= 10**12 for k, v in z.items()))


def zeit_text(sekunden: float) -> str:
    return datetime.fromtimestamp(int(sekunden), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def zeit_sekunden(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------------------------------------------- Dateien atomar schreiben
def atomar_schreiben(pfad: str, inhalt: bytes, gid: int | None) -> None:
    """Zwischendatei im selben Ordner (0640, root:wamo-werkstatt), fsync, rename: Leser sehen immer die alte oder die neue Datei ganz."""
    ordner = os.path.dirname(pfad)
    tmp = os.path.join(ordner, f".{os.path.basename(pfad)}.neu")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o640)
    try:
        if gid is not None:
            os.fchown(fd, 0, gid)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o640)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(inhalt)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pfad)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def jsonl_fortschreiben(pfad: str, neue: list[dict], jetzt: float, gid: int | None) -> int:
    """Hängt die neuen Zeilen an, behält höchstens MAX_ZEILEN und MAX_TAGE; kaputte oder fremde Zeilen der Datei fallen weg. Rückgabe: Zeilen danach."""
    alt: list[dict] = []
    try:
        with open(pfad, "rb") as f:
            for roh in f.read(8_000_000).splitlines():
                try:
                    e = json.loads(roh)
                except ValueError:
                    continue
                if eintrag_pruefen(e):
                    alt.append(e)
    except FileNotFoundError:
        pass
    grenze = jetzt - MAX_TAGE * 86400
    alle = [e for e in alt + [n for n in neue if eintrag_pruefen(n)] if zeit_sekunden(e["zeit"]) >= grenze]
    alle.sort(key=lambda e: e["zeit"])
    alle = alle[-MAX_ZEILEN:]
    inhalt = "".join(json.dumps(e, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n" for e in alle).encode("ascii")
    atomar_schreiben(pfad, inhalt, gid)
    return len(alle)


# ---------------------------------------------------------------------------------------------------- Journal lesen
def journal_lesen(marke: str, zustand: str, lauf=subprocess.run) -> list[dict]:
    """Neue Zeilen der Marke seit dem Lesezeiger, bereits ausgewertet (nie wörtlich). Fehler: Lesezeiger weg, nächster Lauf beginnt neu."""
    zeiger = os.path.join(zustand, f"{marke}.zeiger")
    befehl = ["/usr/bin/journalctl", "-t", marke, "-o", "json", "--no-pager", "--quiet", f"--cursor-file={zeiger}", f"--since=-{ERSTER_LAUF_STUNDEN}h"]
    try:
        r = lauf(befehl, capture_output=True, timeout=20, env=UMGEBUNG, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        try:
            os.unlink(zeiger)
        except OSError:
            pass
        return []
    ergebnis: list[dict] = []
    for roh in r.stdout[:MAX_JOURNAL_BYTES].splitlines()[:5000]:
        try:
            j = json.loads(roh)
            sekunden = int(j["__REALTIME_TIMESTAMP"]) / 1_000_000
            prioritaet = int(j.get("PRIORITY", 6))
        except (ValueError, KeyError, TypeError):
            continue
        auswertung = zeile_auswerten(marke, j.get("MESSAGE"), prioritaet)
        if auswertung is not None:
            e = {"zeit": zeit_text(sekunden), "marke": marke, **auswertung}
            if eintrag_pruefen(e):
                ergebnis.append(e)
    return ergebnis


# ---------------------------------------------------------------------------------------------------- Betriebsstand
def datei_lesen(pfad: str) -> str | None:
    try:
        with open(pfad, "rb") as f:
            return f.read(MAX_DATEI_BYTES).decode("utf-8", "replace")
    except OSError:
        return None


def befehl_ausgabe(befehl: list[str], lauf=subprocess.run) -> str:
    try:
        r = lauf(befehl, capture_output=True, timeout=10, env=UMGEBUNG, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.decode("utf-8", "replace").strip()[:200]


def kern_stand(caddy_dir: str, opt_core: str = "/opt/wamo-core", lauf=subprocess.run) -> dict:
    text = datei_lesen(os.path.join(caddy_dir, "etc", "kern", "slot.inc")) or ""
    m = re.search(r"Aktiver Slot: ([ab])\.", text)
    slot = m.group(1) if m else ("alt" if "core.sock" in text else "unbekannt")
    release = None
    if slot in ("a", "b"):
        try:
            name = os.path.basename(os.readlink(os.path.join(opt_core, "slots", slot)).rstrip("/"))
            release = name if RELEASE_RE.fullmatch(name) else None
        except OSError:
            release = None
    einheit = {"a": "wamo-core@a.service", "b": "wamo-core@b.service", "alt": "wamo-core.service"}.get(slot)
    aktiv = einheit is not None and befehl_ausgabe(["/usr/bin/systemctl", "is-active", einheit], lauf) == "active"
    return {"slot": slot, "release": release, "aktiv": aktiv}


def tls_kontext(ca: str) -> ssl.SSLContext:
    """TLS 1.2 oder neuer, Zertifikat und Name werden gegen die WAMO-CA geprüft, nie ohne Prüfung."""
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    kontext.check_hostname = True
    kontext.verify_mode = ssl.CERT_REQUIRED
    kontext.load_verify_locations(cafile=ca)
    return kontext


def http_json(url: str, ca: str, ohne_netz: bool) -> dict | None:
    if ohne_netz:
        return None
    try:
        kontext = tls_kontext(ca)
        with urllib.request.urlopen(url, timeout=3, context=kontext) as antwort:
            daten = json.loads(antwort.read(MAX_DATEI_BYTES))
        return daten if isinstance(daten, dict) else None
    except (OSError, ValueError, ssl.SSLError):
        return None


def oberflaeche_stand(caddy_dir: str, ca: str, ohne_netz: bool) -> dict:
    text = datei_lesen(os.path.join(caddy_dir, "etc", "kern", "wamo-ui-aktiv.inc")) or ""
    m = re.match(r"# live=(blau|gruen|alt|keine) ", text)
    farbe = m.group(1) if m else "unbekannt"
    version = None
    if farbe in ("blau", "gruen"):
        j = http_json(f"{SERVER}:55445/version.json", ca, ohne_netz)
        v = j.get("version") if j else None
        version = v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None
    return {"farbe": farbe, "version": version}


def installer_stand(pfad: str = "/var/lib/wamo-verteilung/staende/aktuell/aktuell.json") -> dict:
    try:
        v = json.loads(datei_lesen(pfad) or "")["version"]
    except (ValueError, KeyError, TypeError):
        return {"version": None}
    return {"version": v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None}


def kanal_stand(konfig: str = "/etc/wamo/kernkanal.conf", notaus: str = "/etc/wamo/kernkanal.notaus") -> dict:
    if os.path.lexists(notaus):
        return {"zustand": "notaus"}
    text = datei_lesen(konfig)
    if text is None:
        return {"zustand": "keiner"}
    werte = re.findall(r"^\s*KANAL\s*=\s*[\"']?(zu|offen)[\"']?\s*(?:#.*)?$", text, re.M)
    return {"zustand": werte[-1] if werte else "ungueltig"}


def labor_dienst_stand(ca: str, ohne_netz: bool) -> dict:
    j = http_json(f"{SERVER}:55447/gesundheit", ca, ohne_netz)
    z = j.get("zustand") if j else None
    return {"zustand": z if z in ("ok", "gestoert") else "nicht_erreichbar"}


def betrieb_pruefen(b) -> bool:
    """Genau das Schema des Vertrags; jeder Wert aus einer festen Menge oder einem engen Muster."""
    def genau(d, felder):
        return isinstance(d, dict) and set(d) == set(felder)
    try:
        return (genau(b, ("zeit", "kern", "oberflaeche", "installer", "kanal", "labor_dienst")) and ZEIT_RE.fullmatch(b["zeit"]) is not None
                and genau(b["kern"], ("slot", "release", "aktiv")) and b["kern"]["slot"] in ("a", "b", "alt", "unbekannt")
                and (b["kern"]["release"] is None or RELEASE_RE.fullmatch(b["kern"]["release"]) is not None) and type(b["kern"]["aktiv"]) is bool
                and genau(b["oberflaeche"], ("farbe", "version")) and b["oberflaeche"]["farbe"] in ("blau", "gruen", "alt", "keine", "unbekannt")
                and (b["oberflaeche"]["version"] is None or VERSION_RE.fullmatch(b["oberflaeche"]["version"]) is not None)
                and genau(b["installer"], ("version",)) and (b["installer"]["version"] is None or VERSION_RE.fullmatch(b["installer"]["version"]) is not None)
                and genau(b["kanal"], ("zustand",)) and b["kanal"]["zustand"] in ("zu", "offen", "notaus", "keiner", "ungueltig")
                and genau(b["labor_dienst"], ("zustand",)) and b["labor_dienst"]["zustand"] in ("ok", "gestoert", "nicht_erreichbar"))
    except (TypeError, KeyError):
        return False


def betrieb_bauen(jetzt: float, caddy_dir: str, ca: str, ohne_netz: bool) -> dict:
    return {"zeit": zeit_text(jetzt), "kern": kern_stand(caddy_dir), "oberflaeche": oberflaeche_stand(caddy_dir, ca, ohne_netz),
            "installer": installer_stand(), "kanal": kanal_stand(), "labor_dienst": labor_dienst_stand(ca, ohne_netz)}


# ---------------------------------------------------------------------------------------------------- Lauf
def gruppen_id() -> int | None:
    try:
        import grp
        return grp.getgrnam(GRUPPE).gr_gid
    except (ImportError, KeyError):
        return None


def lauf_einmal(daten: str, caddy_dir: str, ca: str, ohne_netz: bool, jetzt: float | None = None, gid: int | None = None) -> int:
    jetzt = time.time() if jetzt is None else jetzt
    protokolle, zustand = os.path.join(daten, "protokolle"), os.path.join(daten, "zustand")
    os.makedirs(protokolle, mode=0o750, exist_ok=True)
    os.makedirs(zustand, mode=0o700, exist_ok=True)
    if gid is not None:  # der Dienst (Gruppe wamo-werkstatt) liest betrieb.json und protokolle/, nie zustand/
        for ordner in (daten, protokolle):
            os.chown(ordner, 0, gid)
            os.chmod(ordner, 0o750)
    sperre = os.open(os.path.join(zustand, "sammler.lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        if fcntl is not None:
            try:
                fcntl.flock(sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                print("Ein anderer Lauf des Sammlers läuft noch, nichts zu tun.")
                return 0
        return _sammeln(daten, protokolle, zustand, caddy_dir, ca, ohne_netz, jetzt, gid)
    finally:
        os.close(sperre)


def _sammeln(daten: str, protokolle: str, zustand: str, caddy_dir: str, ca: str, ohne_netz: bool, jetzt: float, gid: int | None) -> int:
    betrieb = betrieb_bauen(jetzt, caddy_dir, ca, ohne_netz)
    if not betrieb_pruefen(betrieb):
        print("Betriebsstand entspricht nicht dem Schema, nichts geschrieben.", file=sys.stderr)
        return 1
    atomar_schreiben(os.path.join(daten, "betrieb.json"), (json.dumps(betrieb, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"), gid)
    zusammen = []
    for marke in MARKEN:
        neue = journal_lesen(marke, zustand)
        gesamt = jsonl_fortschreiben(os.path.join(protokolle, f"{marke}.jsonl"), neue, jetzt, gid)
        zusammen.append(f"{marke} +{len(neue)}/{gesamt}")
    print("Betrieb geschrieben; Protokolle (neu/gesamt): " + ", ".join(zusammen))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sammler der W.A.I.S. Werkstatt")
    ap.add_argument("--daten", default=DATEN_STANDARD)
    ap.add_argument("--caddy-dir", default=CADDY_STANDARD)
    ap.add_argument("--ca", default=CA_STANDARD)
    ap.add_argument("--ohne-netz", action="store_true", help="keine HTTPS-Abrufe (Probelauf)")
    a = ap.parse_args(argv)
    if os.geteuid() != 0 and a.daten == DATEN_STANDARD:
        print("Der Sammler schreibt nach /var/lib/wamo-werkstatt und läuft als root.", file=sys.stderr)
        return 1
    return lauf_einmal(a.daten, a.caddy_dir, a.ca, a.ohne_netz, gid=gruppen_id())


if __name__ == "__main__":
    sys.exit(main())
