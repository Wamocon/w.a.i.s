#!/usr/bin/env python3
"""Rauchtest der W.A.I.S. Werkstatt (Admin-Panel). Läuft auf Sokrates-2, nur Standardbibliothek:

    sudo python3 -E -s -B /opt/wamo-werkstatt/app/wamo_werkstatt_rauchtest.py --produktiv [--ca DATEI]
    sudo python3 -E -s -B /opt/wamo-werkstatt/app/wamo_werkstatt_rauchtest.py --produktiv --token-admin DATEI [--token-mitglied DATEI] [--token-labor DATEI] [--token-aal1 DATEI]
    sudo python3 -E -s -B /opt/wamo-werkstatt/app/wamo_werkstatt_rauchtest.py --nach-rueckweg [--ca DATEI]

Teil A (immer, ohne Server): Der Sammler wird mit Markerzeilen gefüttert; kein Marker, keine E-Mail und kein Name darf in einer Ausgabe erscheinen, kein Feld
außerhalb des Schemas.
Teil B (--produktiv, als root): Die echte Installation wird nur gelesen und angesprochen: Prüfsummen und Rechte der Dateien, Units aktiv, Dienstprozess ohne
Capabilities und als wamo-werkstatt, Ausgangsregel geladen, betrieb.json und Protokolldateien nach Schema, Antworten ohne Token (401, no-store) direkt am Dienst, über die
Brücke und über Caddy (HTTPS 55448), Positivliste der Pfade und Methoden in Caddy, die Regel für 55448 in der Firewall (nur Admin-Quellen), und als wamo-werkstatt
(runuser): Datenbank und Schlüsselsatz erreichbar, SSH, Router und Internet gesperrt.
Teil C (mit Token-Dateien): echte Zugangstoken aus Dateien (nur lesbar für root, der Inhalt wird nie ausgegeben). Mit --token-admin: GET /ich, GET /betrieb und die
Dashboards antworten, ein erfundener Aufruf der Karte wird nie mit 200 beantwortet. Mit --token-mitglied, --token-labor und --token-aal1: Abweisung mit 403.
Die Token holt der Betreiber vor dem Lauf (zum Beispiel aus einer angemeldeten Sitzung im Browser) und löscht die Dateien danach.
Teil D (--nach-rueckweg): Nach wamo-werkstatt-rueckweg.sh: kein Dienst, keine Brücke, kein Socket, 55448 antwortet nicht, 55443 bis 55446 antworten.
Exit 0 nur, wenn alles bestanden ist. Nie in der Ausgabe: Token, Zugangsdaten, Namen, Gesprächstext.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # als root nie .pyc in den geschützten Programmordner schreiben (sonst schlägt die Prüfsumme an)

import argparse
import http.client
import json
import os
import pwd
import re
import socket
import ssl
import stat
import subprocess
import time

HIER = os.path.dirname(os.path.realpath(__file__))
if HIER not in sys.path:
    sys.path.append(HIER)
for _kandidat in (os.path.join(HIER, "werkstatt"),):  # im Repo liegt der Sammler in werkstatt/, installiert neben dem Rauchtest
    if os.path.isdir(_kandidat) and _kandidat not in sys.path:
        sys.path.append(_kandidat)

ERGEBNIS = {"ok": 0, "fehler": 0}
APP = "/opt/wamo-werkstatt/app"
ETC = "/etc/wamo-werkstatt"
DATEN = "/var/lib/wamo-werkstatt"
SOCKET = "/run/wamo-werkstatt/werkstatt.sock"
BENUTZER = "wamo-werkstatt"
DIENST = ("127.0.0.1", 18095)
SERVER = "192.168.178.136"
PORT = 55448
API = "/werkstatt/api"
CA_STANDARD = "/home/wamocon/wamo-tls/ca/wamo-ca.crt"
EINHEITEN = ("wamo-werkstatt-ausgang.service", "wamo-werkstatt.service", "wamo-werkstatt-bruecke.socket", "wamo-werkstatt-sammler.timer")
MARKER = "RAUCHTEST-MARKER-7f3a"


def pruefe(name: str, ok: bool, detail: str = "") -> bool:
    ERGEBNIS["ok" if ok else "fehler"] += 1
    print(f"  {'OK    ' if ok else 'FEHLER'} {name}" + ("" if ok else f": {detail}"))
    return ok


def ausfuehren(*befehl: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(befehl), capture_output=True, text=True, timeout=60, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})


def als_benutzer(name: str, code: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["runuser", "-u", name, "--", sys.executable, "-E", "-s", "-B", "-c", code, *argv], capture_output=True, text=True, timeout=60, cwd="/")


# ---------------------------------------------------------------------------------------------------- HTTP-Hilfen
def roh_anfrage(verbinden, methode: str, pfad: str, token: str | None = None, koerper: bytes = b"") -> tuple[int, dict, bytes]:
    """Eine HTTP/1.1-Anfrage über eine fertige Verbindung (Unix-Socket oder TCP). Gibt Status, Köpfe (klein geschrieben) und Rumpf zurück."""
    kopf = f"{methode} {pfad} HTTP/1.1\r\nHost: wamo-werkstatt\r\nConnection: close\r\nContent-Length: {len(koerper)}\r\n"
    if token:
        kopf += f"Authorization: Bearer {token}\r\n"
    if koerper:
        kopf += "Content-Type: application/json\r\n"
    with verbinden() as s:
        s.settimeout(15)
        s.sendall(kopf.encode() + b"\r\n" + koerper)
        daten = b""
        while teil := s.recv(65536):
            daten += teil
            if len(daten) > 4_000_000:
                break
    kopf_roh, _, rumpf = daten.partition(b"\r\n\r\n")
    zeilen = kopf_roh.decode("latin-1").split("\r\n")
    status = int(zeilen[0].split(" ", 2)[1])
    koepfe = {z.split(":", 1)[0].strip().lower(): z.split(":", 1)[1].strip() for z in zeilen[1:] if ":" in z}
    return status, koepfe, rumpf


def ueber_unix(methode: str, pfad: str, token: str | None = None, koerper: bytes = b"") -> tuple[int, dict, bytes]:
    def verbinden():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCKET)
        return s
    return roh_anfrage(verbinden, methode, pfad, token, koerper)


def direkt(methode: str, pfad: str, token: str | None = None, koerper: bytes = b"") -> tuple[int, dict, bytes]:
    return roh_anfrage(lambda: socket.create_connection(DIENST, timeout=10), methode, pfad, token, koerper)


def ueber_caddy(ca: str, methode: str, pfad: str, token: str | None = None, koerper: bytes = b"", herkunft: str | None = None) -> tuple[int, dict, bytes]:
    kontext = ssl.create_default_context(cafile=ca)
    verbindung = http.client.HTTPSConnection(SERVER, PORT, timeout=15, context=kontext)
    kopf = {"Connection": "close"}
    if token:
        kopf["Authorization"] = f"Bearer {token}"
    if koerper:
        kopf["Content-Type"] = "application/json"
    if herkunft:
        kopf["Origin"] = herkunft
    try:
        verbindung.request(methode, pfad, body=koerper or None, headers=kopf)
        antwort = verbindung.getresponse()
        return antwort.status, {k.lower(): v for k, v in antwort.getheaders()}, antwort.read(1_000_000)
    finally:
        verbindung.close()


def json_rumpf(rumpf: bytes) -> dict:
    try:
        wert = json.loads(rumpf)
        return wert if isinstance(wert, dict) else {}
    except ValueError:
        return {}


def token_lesen(pfad: str) -> str | None:
    """Das Token aus einer Datei, die nur root lesen darf; der Wert verlässt diese Funktion nur Richtung Authorization-Kopf."""
    try:
        st = os.stat(pfad)
        if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o077:
            pruefe(f"Token-Datei {os.path.basename(pfad)} gehört root und ist nur für root lesbar", False, oct(stat.S_IMODE(st.st_mode)))
            return None
        with open(pfad, encoding="ascii") as f:
            wert = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        pruefe(f"Token-Datei {os.path.basename(pfad)} lesbar", False, type(e).__name__)
        return None
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{20,4000}", wert):
        pruefe(f"Token-Datei {os.path.basename(pfad)} hat die Form eines Tokens", False, "ungültig")
        return None
    return wert


# ---------------------------------------------------------------------------------------------------- Teil A
def teil_a() -> None:
    print("== A. Sammler mit Markerzeilen (ohne Server)")
    import wamo_werkstatt_sammler as S

    faelle = (
        ("wamo-nutzer", f"aktion=anlegen schema=wamo_dev email={MARKER}@beispiel.test ergebnis=ok"),
        ("wais-deploy", f"befehl=verteilen commit={MARKER} teil=keiner trocken=nein rueckgabe=0"),
        ("wamo-labor-geraete", f"Gerät {MARKER}: 192.168.178.77 zugelassen"),
        ("wamo-verteilung", f"einsetzen version=1.2.3 sha256={MARKER} signatur=ok vorher=1.2.2"),
        ("wamo-labor-loeschen", f"echtlauf ziel=2 geloescht=2 fehler=0 verblieben=0 nachweis=ok auswahl={MARKER}"),
    )
    for marke, zeile in faelle:
        e = S.zeile_auswerten(marke, zeile)
        text = json.dumps(e)
        pruefe(f"Zeile der Marke {marke} wird ausgewertet", e is not None and e["code"] in S.CODES, text[:100])
        pruefe(f"Marke {marke}: kein Marker in der Ausgabe", MARKER not in text and "beispiel.test" not in text and "192.168" not in text, text[:100])
    for marke, zeile in (("wamo-nutzer", f"irgendein Text {MARKER}"), ("wais-deploy", f"befehl=anderes commit=x teil=y trocken=nein rueckgabe=0 {MARKER}"),
                         ("unbekannte-marke", "aktion=anlegen"), ("wamo-auth", "einrichten: wamo_auth angewendet\nzweite Zeile")):
        pruefe(f"Fremde Zeile der Marke {marke} verschwindet", S.zeile_auswerten(marke, zeile) is None)
    kaputt = {"zeit": "2026-11-20T10:00:00Z", "marke": "wais-deploy", "stufe": "info", "code": "ausrollen_verteilen", "zahlen": {"x": 1}, "extra": MARKER}
    pruefe("Eintrag mit Zusatzfeld oder fremder Zahl wird nicht geschrieben", S.eintrag_pruefen(kaputt) is False)


# ---------------------------------------------------------------------------------------------------- Teil B
def teil_b_dateien_und_dienste() -> None:
    print("== B1. Dateien, Rechte, Units, Prozess")
    r = subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=APP, capture_output=True, text=True)
    pruefe("Prüfsummen des Codes stimmen", r.returncode == 0, r.stdout[:150] + r.stderr[:150])
    uid_wama = pwd.getpwnam(BENUTZER).pw_uid
    for pfad, soll_modus, soll_gruppe in ((f"{ETC}/db.zugang", 0o440, True), (f"{ETC}/admins", 0o640, True), (f"{DATEN}/betrieb.json", 0o640, True)):
        try:
            st = os.lstat(pfad)
            gruppe = ausfuehren("stat", "-c", "%G", pfad).stdout.strip()
            pruefe(f"{pfad}: root:{BENUTZER} {oct(soll_modus)}", st.st_uid == 0 and stat.S_IMODE(st.st_mode) == soll_modus and gruppe == BENUTZER,
                   f"{st.st_uid} {oct(stat.S_IMODE(st.st_mode))} {gruppe}")
        except OSError as e:
            pruefe(f"{pfad} vorhanden", False, str(e))
    for pfad, modus in ((f"{DATEN}/zustand", 0o700), (f"{DATEN}", 0o750), (f"{DATEN}/protokolle", 0o750)):
        try:
            st = os.lstat(pfad)
            pruefe(f"{pfad}: {oct(modus)}", stat.S_IMODE(st.st_mode) == modus and st.st_uid == 0, oct(stat.S_IMODE(st.st_mode)))
        except OSError as e:
            pruefe(f"{pfad} vorhanden", False, str(e))
    for einheit in EINHEITEN:
        r = ausfuehren("systemctl", "is-active", einheit)
        pruefe(f"{einheit} aktiv", r.stdout.strip() == "active", r.stdout.strip())
    pid = ausfuehren("systemctl", "show", "-p", "MainPID", "--value", "wamo-werkstatt.service").stdout.strip()
    if pid.isdigit() and int(pid) > 0:
        feld = {z.split(":")[0]: z.split(":", 1)[1].strip() for z in open(f"/proc/{pid}/status", encoding="utf-8").read().splitlines() if ":" in z}
        pruefe("Dienstprozess ohne Capabilities", feld.get("CapEff", "x").strip("0") == "", feld.get("CapEff", ""))
        pruefe("Dienstprozess ohne neue Rechte", feld.get("NoNewPrivs") == "1", feld.get("NoNewPrivs", ""))
        pruefe(f"Dienstprozess läuft als {BENUTZER}", int(feld["Uid"].split()[0]) == uid_wama, feld["Uid"])
    else:
        pruefe("Hauptprozess des Dienstes bekannt", False, pid)
    try:
        st = os.lstat(SOCKET)
        pruefe(f"Socket 0660 {BENUTZER}:wamocon", stat.S_ISSOCK(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o660 and st.st_uid == uid_wama
               and ausfuehren("stat", "-c", "%G", SOCKET).stdout.strip() == "wamocon", f"{oct(stat.S_IMODE(st.st_mode))} {st.st_uid}")
    except OSError as e:
        pruefe("Socket vorhanden", False, str(e))
    r = ausfuehren("nft", "list", "table", "inet", "wamo_werkstatt_ausgang")
    pruefe("nft-Tabelle wamo_werkstatt_ausgang geladen mit Drop-Regel", r.returncode == 0 and "drop" in r.stdout, r.stderr[:150])


def teil_b_sammler() -> None:
    print("== B2. Ausgaben des Sammlers")
    import wamo_werkstatt_sammler as S

    try:
        with open(f"{DATEN}/betrieb.json", encoding="ascii") as f:
            betrieb = json.load(f)
        pruefe("betrieb.json entspricht dem Schema", S.betrieb_pruefen(betrieb), json.dumps(betrieb)[:150])
        alter = time.time() - S.zeit_sekunden(betrieb["zeit"])
        pruefe("betrieb.json ist höchstens drei Minuten alt", 0 <= alter < 180, f"{int(alter)} s")
    except (OSError, ValueError, KeyError) as e:
        pruefe("betrieb.json lesbar und gültig", False, type(e).__name__)
    ordner = f"{DATEN}/protokolle"
    for name in sorted(os.listdir(ordner)) if os.path.isdir(ordner) else []:
        marke = name[:-6] if name.endswith(".jsonl") else ""
        zeilen = open(os.path.join(ordner, name), encoding="ascii").read().splitlines() if marke else []
        gut = marke in S.MARKEN and len(zeilen) <= S.MAX_ZEILEN
        for z in zeilen:
            try:
                gut = gut and S.eintrag_pruefen(json.loads(z)) and json.loads(z)["marke"] == marke
            except ValueError:
                gut = False
        pruefe(f"protokolle/{name}: nur gültige Zeilen, höchstens {S.MAX_ZEILEN}", gut, f"{len(zeilen)} Zeilen")


def teil_b_http(ca: str) -> None:
    print("== B3. Antworten ohne Token (Dienst, Brücke, Caddy)")
    wege = (("direkt am Dienst", direkt), ("über die Brücke", ueber_unix), ("über Caddy (HTTPS 55448)", lambda m, p, t=None: ueber_caddy(ca, m, p, t)))
    for name, weg in wege:
        try:
            status, koepfe, rumpf = weg("GET", f"{API}/ich")
            j = json_rumpf(rumpf)
            pruefe(f"{name}: ohne Token 401 nicht_angemeldet", status == 401 and j.get("code") == "nicht_angemeldet", f"{status} {rumpf[:80]!r}")
            pruefe(f"{name}: Cache-Control no-store", "no-store" in koepfe.get("cache-control", ""), koepfe.get("cache-control", ""))
            status, _, _ = weg("GET", f"{API}/ich", "x" * 30 + ".yy.zz")
            pruefe(f"{name}: ungültiges Token 401", status == 401, str(status))
        except (OSError, ValueError, IndexError) as e:
            pruefe(f"{name} erreichbar", False, type(e).__name__)
    try:
        for methode, pfad, soll, was in (("GET", "/", 404, "Wurzel"), ("GET", "/gesundheit", 404, "fremder Pfad"), ("GET", f"{API}/../x", 404, "Pfad mit Punkten"),
                                         ("GET", f"{API}/ich%2e", 404, "Pfad mit Prozentzeichen"), ("POST", "/", 404, "POST auf die Wurzel"), ("TRACE", f"{API}/ich", 405, "Methode TRACE")):
            status, koepfe, _ = ueber_caddy(ca, methode, pfad)
            pruefe(f"Caddy: {was} gibt {soll}", status == soll, str(status))
            if soll in (404, 405):
                pruefe(f"Caddy: {was} mit nosniff", koepfe.get("x-content-type-options") == "nosniff", koepfe.get("x-content-type-options", ""))
    except (OSError, ValueError) as e:
        pruefe("Caddy auf 55448 erreichbar", False, type(e).__name__)


def teil_b_firewall() -> None:
    print("== B4. Firewall: Port 55448 nur aus den Admin-Quellen")
    r = ausfuehren("iptables", "-w", "5", "-S", "WAMO-FW")
    pruefe("Regel: 55448 geht in die Kette WAMO-FW-ADMIN", f"--ctorigdstport {PORT} -j WAMO-FW-ADMIN" in r.stdout, r.stdout[-150:] + r.stderr[:100])
    r = ausfuehren("iptables", "-w", "5", "-S", "WAMO-FW-ADMIN")
    zeilen = r.stdout.splitlines()
    pruefe("Kette WAMO-FW-ADMIN endet mit Protokoll und DROP", len(zeilen) >= 3 and zeilen[-1] == "-A WAMO-FW-ADMIN -j DROP" and "LOG" in zeilen[-2], r.stdout[-150:])
    pruefe("Kette WAMO-FW-ADMIN erlaubt Loopback", any(z.startswith("-A WAMO-FW-ADMIN -s 127.0.0.0/8") for z in zeilen))
    pruefe("Kette WAMO-FW-ADMIN lässt kein Netz außerhalb von RFC 1918 zu", all(re.match(r"-A WAMO-FW-ADMIN -s (127\.|10\.|192\.168\.)", z) for z in zeilen if z.endswith("RETURN")), r.stdout[-200:])


def teil_b_als_dienstbenutzer() -> None:
    print(f"== B5. Als {BENUTZER}: Netz")
    netz = ("import socket, sys\ns = socket.socket(); s.settimeout(3)\ntry:\n s.connect((sys.argv[1], int(sys.argv[2]))); print('VERBUNDEN')\n"
            "except OSError:\n print('ABGELEHNT')\n")
    for ziel, port, name, erwartet in ((SERVER, 55322, "die Datenbank (Supavisor 55322)", "VERBUNDEN"), (SERVER, 55443, "den Schlüsselsatz (55443)", "VERBUNDEN"),
                                       (SERVER, 22, "SSH auf Sokrates-2", "ABGELEHNT"), ("192.168.178.1", 80, "den Router im LAN", "ABGELEHNT"),
                                       ("1.1.1.1", 443, "das Internet", "ABGELEHNT"), ("127.0.0.1", 18765, "den Labor-Dienst auf Loopback", "ABGELEHNT")):
        r = als_benutzer(BENUTZER, netz, ziel, str(port))
        pruefe(f"{BENUTZER} {'erreicht' if erwartet == 'VERBUNDEN' else 'erreicht nicht'} {name}", erwartet in r.stdout, (r.stdout + r.stderr)[:150])
    r = als_benutzer(BENUTZER, "import os, sys\ntry:\n open(sys.argv[1] + '/probe', 'w'); print('SCHREIBT')\nexcept OSError:\n print('GESPERRT')\n", DATEN)
    pruefe("Dienstbenutzer kann in den Datenordner nicht schreiben", "GESPERRT" in r.stdout, (r.stdout + r.stderr)[:150])
    r = als_benutzer("nobody", "import socket,sys\ns=socket.socket(socket.AF_UNIX)\ntry:\n s.connect(sys.argv[1]);print('VERBUNDEN')\nexcept OSError:\n print('ABGELEHNT')\n", SOCKET)
    pruefe("Socket für den Benutzer nobody abgewiesen", "ABGELEHNT" in r.stdout, (r.stdout + r.stderr)[:150])


def teil_b(ca: str) -> None:
    if os.geteuid() != 0:
        pruefe("Teil B läuft als root", False, "bitte mit sudo")
        return
    teil_b_dateien_und_dienste()
    teil_b_sammler()
    teil_b_http(ca)
    teil_b_firewall()
    teil_b_als_dienstbenutzer()


# ---------------------------------------------------------------------------------------------------- Teil C
def teil_c(ca: str, a: argparse.Namespace) -> None:
    print("== C. Mit echten Token aus Dateien")

    def abruf(token: str, pfad: str, methode: str = "GET", koerper: bytes = b"", herkunft: str | None = None):
        return ueber_caddy(ca, methode, f"{API}{pfad}", token, koerper, herkunft)

    token = token_lesen(a.token_admin) if a.token_admin else None
    if token:
        status, _, rumpf = abruf(token, "/ich")
        j = json_rumpf(rumpf)
        pruefe("Admin: GET /ich gibt 200 mit rolle, aal2_alter_s und erlaubt", status == 200 and {"rolle", "aal2_alter_s", "erlaubt"} <= set(j), f"{status} {sorted(j)}")
        pruefe("Admin: erlaubt ist wahr", j.get("erlaubt") is True, str(j.get("erlaubt")))
        status, koepfe, rumpf = abruf(token, "/betrieb")
        pruefe("Admin: GET /betrieb gibt 200 und no-store", status == 200 and "no-store" in koepfe.get("cache-control", ""), str(status))
        for pfad in ("sitzungen", "latenz", "aktionen"):
            status, _, _ = abruf(token, f"/dashboard/{pfad}?tage=14")
            pruefe(f"Admin: GET /dashboard/{pfad} gibt 200", status == 200, str(status))
        status, _, _ = abruf(token, "/dashboard/sitzungen?tage=99")
        pruefe("Admin: tage=99 wird abgewiesen (nie 200)", status in (400, 422), str(status))
        status, _, _ = abruf(token, "/protokolle?marke=gibt-es-nicht&stunden=1")
        pruefe("Admin: unbekannte Marke wird abgewiesen oder bleibt leer", status in (200, 400, 422), str(status))
        status, _, _ = abruf(token, "/karten/karte/00000000-0000-4000-8000-000000000000/ausfuehren", "POST", b"{}")
        pruefe("Admin: erfundene Karte wird nie ausgeführt", status in (403, 404, 409, 410, 422), str(status))
        status, koepfe, _ = abruf(token, "/ich", herkunft="https://evil.example")
        pruefe("Fremde Herkunft bekommt keine CORS-Freigabe", koepfe.get("access-control-allow-origin") not in ("*", "https://evil.example"), koepfe.get("access-control-allow-origin", ""))
    for datei, was, erlaubte in ((a.token_mitglied, "Mitglied", (403,)), (a.token_labor, "Laborprofil", (403,)), (a.token_aal1, "Token ohne zweiten Faktor", (403,))):
        t = token_lesen(datei) if datei else None
        if t:
            for pfad in ("/ich", "/betrieb", "/labor/stand"):
                status, _, rumpf = abruf(t, pfad)
                pruefe(f"{was}: GET {pfad} wird mit 403 abgewiesen", status in erlaubte, f"{status} {json_rumpf(rumpf).get('code', '')}")
    if not any((a.token_admin, a.token_mitglied, a.token_labor, a.token_aal1)):
        print("  übersprungen: keine Token-Dateien angegeben (--token-admin, --token-mitglied, --token-labor, --token-aal1)")


# ---------------------------------------------------------------------------------------------------- Teil D
def teil_d(ca: str) -> None:
    print("== D. Nach dem Rückweg")
    for einheit in EINHEITEN + ("wamo-werkstatt-bruecke.service",):
        r = ausfuehren("systemctl", "is-active", einheit)
        pruefe(f"{einheit} nicht aktiv", r.stdout.strip() != "active", r.stdout.strip())
    pruefe("Socket werkstatt.sock entfernt", not os.path.exists(SOCKET))
    r = ausfuehren("nft", "list", "table", "inet", "wamo_werkstatt_ausgang")
    pruefe("nft-Tabelle wamo_werkstatt_ausgang entfernt", r.returncode != 0)
    try:
        status, _, _ = ueber_caddy(ca, "GET", f"{API}/ich")
        pruefe("55448 liefert ohne Site keine Antwort des Dienstes", status not in (200, 401, 403), str(status))
    except (OSError, ssl.SSLError):
        pruefe("55448 antwortet nicht", True)
    for port in (55443, 55444, 55445, 55446):
        try:
            kontext = ssl.create_default_context(cafile=ca)
            with socket.create_connection((SERVER, port), timeout=5) as roh, kontext.wrap_socket(roh, server_hostname=SERVER):
                pruefe(f"{port} antwortet", True)
        except (OSError, ssl.SSLError) as e:
            pruefe(f"{port} antwortet", False, type(e).__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rauchtest der W.A.I.S. Werkstatt")
    ap.add_argument("--produktiv", action="store_true", help="die echte Installation prüfen (als root)")
    ap.add_argument("--nach-rueckweg", action="store_true", help="prüfen, dass der Rückweg nichts übrig ließ")
    ap.add_argument("--ca", default=CA_STANDARD, help="Zertifikat der WAMO-CA für HTTPS auf 55448")
    ap.add_argument("--token-admin", help="Datei mit dem Zugangstoken eines Admins aus der Erlaubnisliste (aal2, frisch)")
    ap.add_argument("--token-mitglied", help="Datei mit dem Zugangstoken eines Mitglieds")
    ap.add_argument("--token-labor", help="Datei mit dem Zugangstoken eines Laborprofils")
    ap.add_argument("--token-aal1", help="Datei mit einem Zugangstoken ohne zweiten Faktor")
    a = ap.parse_args()
    if not sys.platform.startswith("linux"):
        print("Der Rauchtest läuft nur unter Linux.", file=sys.stderr)
        return 1
    print(f"Werkstatt-Rauchtest, Code aus {HIER}, {'root' if os.geteuid() == 0 else 'Benutzer-ID ' + str(os.geteuid())}")
    if a.nach_rueckweg:
        teil_d(a.ca)
    else:
        teil_a()
        if a.produktiv:
            teil_b(a.ca)
            teil_c(a.ca, a)
    print(f"Ergebnis: {ERGEBNIS['ok']} bestanden, {ERGEBNIS['fehler']} fehlgeschlagen")
    return 0 if ERGEBNIS["fehler"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
