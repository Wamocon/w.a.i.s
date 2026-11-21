"""Tests für den Betrieb der W.A.I.S. Werkstatt (Admin-Panel) auf Sokrates-2, nur statische Prüfungen und Probeläufe:

  infra/sokrates2/wamo-werkstatt-einrichten.sh, wamo-werkstatt-rueckweg.sh     Skripte (Probelauf in einem Wegwerf-Ordner, WAMO_WERKSTATT_WURZEL)
  infra/sokrates2/werkstatt/                                                  Units, Ausgangsregel, Brücke, Sammler, Vorlagen
  infra/sokrates2/wamo-caddy/kern/wamo-werkstatt.caddy                         Site auf HTTPS 55448
  infra/sokrates2/wamo-caddy/docker-compose.yml                                Port 55448 und Ordner /run/wamo-werkstatt
  infra/sokrates2/wamo-firewall.sh                                             55448 in LAN_PORTS_ADMIN
  infra/sokrates2/wamo_werkstatt_rauchtest.py                                  Rauchtest (nur Syntax und Aufbau, die Proben laufen am Server)

Nichts hier läuft gegen ein System. Der Sammler wird als Modul geladen und mit Markerzeilen geprüft: Kein Marker, keine E-Mail und kein Gerätename darf in einer
Ausgabe stehen. Die Probeläufe der Skripte brauchen eine Bash (unter Windows die Git-Bash ohne Startdatei) und laufen nie als root. Was root, systemd, Docker,
den Benutzer wamo-werkstatt, die nft-Tabelle oder pip braucht, ist nur am Server prüfbar (infra/sokrates2/wamo_werkstatt_rauchtest.py).

Ausführen:  python -m pytest -q -p no:cacheprovider test_werkstatt_skripte.py   (im Ordner voice-core/)
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOKRATES2 = REPO / "infra" / "sokrates2"
WERKSTATT = SOKRATES2 / "werkstatt"
CADDY = SOKRATES2 / "wamo-caddy"
SITE = CADDY / "kern" / "wamo-werkstatt.caddy"
EINRICHTEN = SOKRATES2 / "wamo-werkstatt-einrichten.sh"
RUECKWEG = SOKRATES2 / "wamo-werkstatt-rueckweg.sh"
RAUCHTEST = SOKRATES2 / "wamo_werkstatt_rauchtest.py"
SAMMLER = WERKSTATT / "wamo_werkstatt_sammler.py"
FIREWALL = SOKRATES2 / "wamo-firewall.sh"
UNITS = ("wamo-werkstatt.service", "wamo-werkstatt-ausgang.service", "wamo-werkstatt-bruecke.socket", "wamo-werkstatt-bruecke.service",
         "wamo-werkstatt-sammler.service", "wamo-werkstatt-sammler.timer")
ALLE_DATEIEN = [EINRICHTEN, RUECKWEG, RAUCHTEST, SAMMLER, SITE, CADDY / "docker-compose.yml", FIREWALL,
                *[WERKSTATT / u for u in UNITS], WERKSTATT / "wamo-werkstatt-ausgang.nft", WERKSTATT / "werkstatt.env.vorlage", WERKSTATT / "admins.vorlage"]
# rückwärts geschrieben, damit die Wörter selbst nirgends im Repo stehen (keine Verweise auf andere Systeme)
VERBOTENE_WOERTER = tuple(w[::-1] for w in ("ikeeein", "sivraj", "lortnoctpmorp", "nocimad"))
MARKER = "MARKER-4f9c1e"


def _bash():
    # Unter Windows zuerst die Bash ohne Startdatei (Git\usr\bin), wie in test_labor_betrieb_skripte.py
    kandidaten = [r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe"] if os.name == "nt" else []
    kandidaten.append(shutil.which("bash") if os.name != "nt" else None)
    return next((k for k in kandidaten if k and os.path.exists(k)), None)


BASH = _bash()


def lies(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def code(pfad: Path) -> list[str]:
    return [z.strip() for z in lies(pfad).splitlines() if z.strip() and not z.strip().startswith("#")]


def posix(p) -> str:
    """Pfad in der Schreibweise der Bash (unter Git für Windows: C:\\x wird /c/x)."""
    s = str(p).replace("\\", "/")
    if os.name == "nt" and re.match(r"^[A-Za-z]:/", s):
        s = "/" + s[0].lower() + s[2:]
    return s


def _lade_sammler():
    spec = importlib.util.spec_from_file_location("wamo_werkstatt_sammler", SAMMLER)
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_werkstatt_sammler"] = modul
    spec.loader.exec_module(modul)
    return modul


S = _lade_sammler()


# ====================================================================================== Allgemeine Textprüfungen
class AllgemeinTests(unittest.TestCase):
    def test_alle_dateien_sind_da(self):
        for f in ALLE_DATEIEN:
            self.assertTrue(f.is_file(), f)

    def test_ohne_gedankenstriche_cr_und_verbotene_woerter(self):
        for f in ALLE_DATEIEN:
            roh = f.read_bytes()
            self.assertNotIn(b"\r", roh, f.name)
            text = roh.decode("utf-8")
            self.assertNotIn(chr(0x2014), text, f.name)
            self.assertNotIn(chr(0x2013), text, f.name)
            for wort in VERBOTENE_WOERTER:
                self.assertNotIn(wort, text.lower(), f.name)
            if f.suffix == ".sh":
                self.assertIn("set -euo pipefail", text, f.name)
                self.assertNotIn("eval ", text, f.name)

    def test_keine_langen_zufallszeichenfolgen_als_literal(self):
        """Die Secret-Prüfung (gitleaks) schlägt bei Token-ähnlichen Literalen an: Es darf keines im Betrieb stehen."""
        for f in ALLE_DATEIEN:
            for zeile in code(f):
                for wort in re.findall(r"[A-Za-z0-9_+/=-]{40,}", zeile):
                    self.assertTrue("/" in wort or "$" in wort or re.fullmatch(r"[a-z0-9-]+|[A-Za-z_]+[_-][A-Za-z_-]+", wort), f"{f.name}: {wort[:20]}")

    def test_tls_nur_mit_pruefung_und_mindestens_version_1_2(self):
        """CodeQL: ssl.create_default_context lässt TLS 1.0 und 1.1 zu. Beide Python-Dateien bauen den Kontext selbst (tls_kontext) und prüfen immer das Zertifikat."""
        for f in (RAUCHTEST, SAMMLER):
            text = lies(f)
            self.assertNotIn("create_default_context", text, f.name)
            self.assertNotIn("CERT_NONE", text, f.name)
            self.assertNotIn("check_hostname = False", text, f.name)
            self.assertIn("minimum_version = ssl.TLSVersion.TLSv1_2", text, f.name)
            self.assertIn("verify_mode = ssl.CERT_REQUIRED", text, f.name)

    def test_skripte_sind_ausfuehrbar_formuliert_und_in_der_syntax_fehlerfrei(self):
        for f in (EINRICHTEN, RUECKWEG):
            self.assertTrue(lies(f).startswith("#!/usr/bin/env bash\n"), f.name)
        for f in (RAUCHTEST, SAMMLER):
            ast_text = lies(f)
            compile(ast_text, str(f), "exec")
        if BASH:
            for f in (EINRICHTEN, RUECKWEG):
                r = subprocess.run([BASH, "-n", str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
        if shutil.which("shellcheck"):
            for f in (EINRICHTEN, RUECKWEG):
                r = subprocess.run(["shellcheck", "-S", "warning", str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)


# ====================================================================================== Units und Ausgangsregel
class UnitTests(unittest.TestCase):
    def zeilen(self, name: str) -> list[str]:
        return code(WERKSTATT / name)

    def test_dienst_ist_gehaertet_und_fest_verdrahtet(self):
        z = self.zeilen("wamo-werkstatt.service")
        for soll in ("User=wamo-werkstatt", "Group=wamo-werkstatt", "CapabilityBoundingSet=", "AmbientCapabilities=", "NoNewPrivileges=yes", "ProtectSystem=strict",
                     "ProtectHome=yes", "PrivateTmp=yes", "PrivateDevices=yes", "MemoryDenyWriteExecute=yes", "RestrictAddressFamilies=AF_UNIX AF_INET", "IPAddressDeny=any",
                     "IPAddressAllow=127.0.0.1/32 192.168.178.136/32 172.23.0.0/16 172.24.0.0/24", "SystemCallFilter=@system-service", "SystemCallFilter=~@privileged",
                     "SystemCallArchitectures=native", "RestrictNamespaces=yes", "LockPersonality=yes", "RestrictSUIDSGID=yes", "ProtectKernelTunables=yes", "LimitCORE=0",
                     "Requires=wamo-werkstatt-ausgang.service", "After=wamo-werkstatt-ausgang.service", "EnvironmentFile=/etc/wamo-werkstatt/werkstatt.env",
                     "LoadCredential=db.zugang:/etc/wamo-werkstatt/db.zugang", "Environment=WAMO_WERKSTATT_DB_ZUGANG=%d/db.zugang",
                     "ExecStartPre=/usr/bin/sha256sum -c --quiet SHA256SUMS", "ExecStart=/opt/wamo-werkstatt/venv/bin/python -I -B -m wamo_werkstatt",
                     "WorkingDirectory=/opt/wamo-werkstatt/app", "ConditionPathExists=/opt/wamo-werkstatt/app/SHA256SUMS", "UMask=0077", "SyslogIdentifier=wamo-werkstatt"):
            self.assertIn(soll, z)
        self.assertEqual(len([x for x in z if x.startswith(("ExecStart=", "ExecStop", "ExecReload"))]), 1)
        for verboten in ("ReadWritePaths", "ExecStartPre=+", "ExecStart=+", "AmbientCapabilities=CAP", "AF_INET6", "AF_NETLINK", "AF_PACKET", "User=root", "PermissionsStartOnly",
                         "Environment=WAMO_WERKSTATT_DB_ZUGANG=/", "password", "PASSWORD"):
            self.assertFalse(any(verboten in x for x in z), verboten)   # der Dienst schreibt in keine Datei; der Zugang kommt nur als Credential
        sperren = next(x for x in z if x.startswith("InaccessiblePaths="))
        for geheim in ("/etc/wamo", "/etc/wamo-anker", "/etc/wamo-freigabe", "/etc/wamo-labor", "/etc/wamo-release", "/etc/wamo-geraete", "/etc/wamo-haus-proxy"):
            self.assertIn("-" + geheim + " ", sperren + " ")

    def test_ausgangsregel_erlaubt_genau_drei_wege(self):
        regeln = self.zeilen("wamo-werkstatt-ausgang.nft")
        self.assertIn("meta skuid wamo-werkstatt jump wamo_werkstatt", regeln)
        erlaubt = [r for r in regeln if " accept" in r and "policy" not in r]
        self.assertEqual(len(erlaubt), 3)
        self.assertTrue(erlaubt[0].startswith('oifname "lo" ip daddr 127.0.0.1 tcp dport 18095 '), erlaubt[0])
        self.assertTrue(erlaubt[1].startswith('oifname "lo" ip saddr 127.0.0.1 tcp sport 18095 '), erlaubt[1])
        self.assertTrue(erlaubt[2].startswith("ct original ip daddr 192.168.178.136 ct original proto-dst { 55322, 55443 } "), erlaubt[2])
        self.assertTrue(any(r.startswith("counter drop") for r in regeln))
        self.assertLess(max(i for i, r in enumerate(regeln) if " accept" in r and "policy" not in r), [i for i, r in enumerate(regeln) if r.startswith("counter drop")][0])
        einheit = lies(WERKSTATT / "wamo-werkstatt-ausgang.service")
        self.assertIn("ExecStart=/usr/sbin/nft -f /etc/wamo-werkstatt-ausgang/regeln.nft", einheit)
        self.assertIn("ExecStop=/usr/sbin/nft delete table inet wamo_werkstatt_ausgang", einheit)
        self.assertIn("Before=wamo-werkstatt.service wamo-werkstatt-bruecke.service", einheit)

    def test_bruecke_reicht_nur_bytes_auf_loopback_weiter(self):
        sock = self.zeilen("wamo-werkstatt-bruecke.socket")
        for soll in ("ListenStream=/run/wamo-werkstatt/werkstatt.sock", "SocketUser=wamo-werkstatt", "SocketGroup=wamocon", "SocketMode=0660", "Accept=no"):
            self.assertIn(soll, sock)
        dienst = self.zeilen("wamo-werkstatt-bruecke.service")
        self.assertIn("ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:18095", dienst)
        for soll in ("User=wamo-werkstatt", "IPAddressDeny=any", "IPAddressAllow=127.0.0.1/32", "CapabilityBoundingSet=", "NoNewPrivileges=yes", "ProtectSystem=strict",
                     "RestrictAddressFamilies=AF_UNIX AF_INET", "Requires=wamo-werkstatt.service wamo-werkstatt-bruecke.socket"):
            self.assertIn(soll, dienst)
        self.assertFalse(any("ReadWritePaths" in x for x in dienst))

    def test_sammler_laeuft_als_root_aber_eng_gefasst(self):
        z = self.zeilen("wamo-werkstatt-sammler.service")
        for soll in ("Type=oneshot", "ExecStartPre=/usr/bin/sha256sum -c --quiet SHA256SUMS",
                     "ExecStart=/usr/bin/python3 -I -B /opt/wamo-werkstatt/app/wamo_werkstatt_sammler.py --caddy-dir __CADDY_DIR__", "NoNewPrivileges=yes", "ProtectSystem=strict",
                     "ReadWritePaths=/var/lib/wamo-werkstatt", "RestrictAddressFamilies=AF_UNIX AF_INET", "IPAddressDeny=any", "IPAddressAllow=127.0.0.0/8 192.168.178.136/32 172.24.0.0/24",
                     "CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_DAC_READ_SEARCH CAP_FOWNER", "UMask=0027"):
            self.assertIn(soll, z)
        self.assertFalse(any(x.startswith("User=") for x in z))   # root
        sperren = next(x for x in z if x.startswith("InaccessiblePaths="))
        for geheim in ("/etc/wamo/geheim.env", "/etc/wamo/core.env", "/etc/wamo-labor/kern-token", "/etc/wamo-labor/betreuer-token", "/etc/wamo-werkstatt/db.zugang"):
            self.assertIn("-" + geheim + " ", sperren + " ")
        self.assertEqual([x for x in z if x.startswith("ReadWritePaths")], ["ReadWritePaths=/var/lib/wamo-werkstatt"])   # nur der eigene Datenordner
        timer = self.zeilen("wamo-werkstatt-sammler.timer")
        for soll in ("OnUnitActiveSec=1min", "Unit=wamo-werkstatt-sammler.service", "WantedBy=timers.target"):
            self.assertIn(soll, timer)

    def test_vorlagen_haben_keine_geheimnisse(self):
        env = self.zeilen("werkstatt.env.vorlage")
        schluessel = {z.split("=", 1)[0] for z in env}
        self.assertEqual(schluessel, {"WAMO_WERKSTATT_HOST", "WAMO_WERKSTATT_PORT", "WAMO_WERKSTATT_SCHEMA", "WAMO_WERKSTATT_ADMINS", "WAMO_WERKSTATT_DATEN", "WAMO_WERKSTATT_CA",
                                      "WAMO_WERKSTATT_JWKS_URL", "WAMO_WERKSTATT_ISS", "WAMO_WERKSTATT_AUD", "WAMO_WERKSTATT_HERKUNFT", "WAMO_WERKSTATT_WISSEN_BASIS"})
        text = "\n".join(env).lower()
        for verboten in ("password", "passwort", "secret", "token", "apikey", "key="):
            self.assertNotIn(verboten, text)
        self.assertIn("WAMO_WERKSTATT_HOST=127.0.0.1", env)
        self.assertIn("WAMO_WERKSTATT_PORT=18095", env)
        self.assertIn("WAMO_WERKSTATT_SCHEMA=__SCHEMA__", env)
        self.assertEqual(self.zeilen("admins.vorlage"), [])   # nur Kommentare: ohne Einträge kommt niemand hinein


# ====================================================================================== Caddy, Compose, Firewall
class CaddyTests(unittest.TestCase):
    def setUp(self):
        self.text = lies(SITE)
        self.z = code(SITE)

    def muster(self) -> re.Pattern:
        return re.compile(re.search(r"@api_pfad \{\s+path_regexp (\S+)", self.text)[1])

    def test_site_adressen_und_grenzen(self):
        self.assertIn("https://192.168.178.136:55448, https://sokrates2:55448, https://spark-651f.local:55448 {", self.z)
        self.assertIn("tls internal", self.z)
        self.assertIn("max_size 256KB", self.z)
        self.assertIn("not method GET HEAD POST PUT PATCH DELETE OPTIONS", self.z)
        self.assertEqual([x for x in self.z if "reverse_proxy" in x], ["reverse_proxy unix//run/wamo-werkstatt/werkstatt.sock {"])
        self.assertEqual(self.text.count("{8}"), 0)   # geschweifte Klammern im Muster läse Caddy als Platzhalter

    def test_positivliste_der_pfade(self):
        m = self.muster()
        for gut in ("/werkstatt/api/ich", "/werkstatt/api/betrieb", "/werkstatt/api/dashboard/sitzungen", "/werkstatt/api/labor/termine/0b9f2c1e-4a6d-4f0e-9a1b-2c3d4e5f6a7b/checkliste/3",
                    "/werkstatt/api/karten/A12", "/werkstatt/api/karten/karte/0b9f2c1e-4a6d-4f0e-9a1b-2c3d4e5f6a7b/ausfuehren", "/werkstatt/api/zuordnung"):
            self.assertTrue(m.search(gut), gut)
        for fremd in ("/", "/werkstatt", "/werkstatt/api", "/werkstatt/api/", "/werkstatt/api/ich/", "/werkstatt/api//ich", "/werkstatt/api/../ich", "/werkstatt/api/ich%2e",
                      "/werkstatt/api/ich.json", "/werkstatt/apix/ich", "/x/werkstatt/api/ich", "/Werkstatt/api/ich", "/werkstatt/api/ich?x=1", "/gesundheit", "/werkstatt/api/ich\n/x"):
            self.assertIsNone(m.search(fremd), fremd)

    def test_caddy_setzt_keine_eigenen_cors_koepfe_und_keine_ausnahmen(self):
        self.assertNotIn("Access-Control", self.text)   # CORS (nur die Herkunft der Oberfläche) setzt der Dienst, Caddy überschreibt keinen Kopf
        self.assertNotIn("remote_ip", self.text)        # die Quellen bestimmt die Firewall (Kette WAMO-FW-ADMIN), die Anmeldung der Dienst
        self.assertEqual(self.z.count("import werkstatt_koepfe"), 3)   # 405, 404 und Fehler von Caddy selbst
        self.assertEqual(self.z.count("handle {"), 1)
        self.assertIn('respond "Nicht gefunden." 404', self.z)

    def test_compose_veroeffentlicht_55448_und_bindet_den_ordner_nur_lesend_ein(self):
        c = code(CADDY / "docker-compose.yml")
        self.assertIn('- "0.0.0.0:55448:55448"', c)
        self.assertEqual(len(re.findall(r'"0\.0\.0\.0:\d+:\d+"', "\n".join(c))), 6)
        self.assertIn("- /run/wamo-werkstatt:/run/wamo-werkstatt:ro", c)
        self.assertIn("- /run/wamo-freigabe:/run/wamo-freigabe:ro", c)   # unverändert
        self.assertIn('user: "1000:1000"', c)                               # deshalb die Gruppe wamocon am Ordner

    def test_firewall_nimmt_55448_in_die_admin_quellen(self):
        text = lies(FIREWALL)
        self.assertRegex(text, r'(?m)^LAN_PORTS_ADMIN="55446 55322 56543 55448" ')
        self.assertRegex(text, r'(?m)^LAN_PORTS="55443 55444 55445" ')   # die offenen Ports bleiben, 55448 hängt nicht daran
        self.assertNotRegex(text, r'LAN_PORTS="[^"]*55448')

    @unittest.skipUnless(BASH, "keine Bash vorhanden")
    def test_firewall_regeln_schicken_55448_in_die_admin_kette(self):
        with tempfile.TemporaryDirectory() as t:
            env = dict(os.environ, WAMO_FW_ADMIN_QUELLEN=posix(Path(t) / "keine"), WAMO_FW_LABOR_QUELLEN=posix(Path(t) / "keine2"), WAMO_FW_CONF=posix(Path(t) / "keine3"))
            r = subprocess.run([BASH, str(FIREWALL), "regeln"], capture_output=True, text=True, env=env, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-A WAMO-FW -p tcp -m conntrack --ctdir ORIGINAL --ctorigdstport 55448 -j WAMO-FW-ADMIN", r.stdout)
        self.assertNotIn("--ctorigdstport 55448 -j WAMO-FW-LAN", r.stdout)


# ====================================================================================== Sammler
def journal_zeile(marke_text: str, prioritaet: int = 6, sekunden: float | None = None) -> bytes:
    zeit = int((time.time() if sekunden is None else sekunden) * 1_000_000)
    return json.dumps({"MESSAGE": marke_text, "PRIORITY": str(prioritaet), "__REALTIME_TIMESTAMP": str(zeit)}).encode()


class SammlerMusterTests(unittest.TestCase):
    POSITIV = (
        ("wais-deploy", "befehl=verteilen commit=0123abc teil=keiner trocken=nein rueckgabe=0", "ausrollen_verteilen", "info", {"rueckgabe": 0, "trocken": 0}),
        ("wais-deploy", "befehl=prod-kern commit=keiner teil=keiner trocken=ja rueckgabe=3", "ausrollen_prod_kern", "fehler", {"rueckgabe": 3, "trocken": 1}),
        ("wamo-job-kern", "aktion=kanal ergebnis=ok", "kern_kanal_kanal", "info", {}),
        ("wamo-job-kern", "aktion=schluessel ergebnis=ok", "kern_kanal_schluessel", "info", {}),
        ("wamo-job-kern", "aktion=notaus ergebnis=ok", "kern_kanal_notaus", "warnung", {}),
        ("wamo-job-kern", "aktion=schalter ergebnis=fehler", "kern_kanal_schalter", "fehler", {}),
        ("wamo-nutzer", "aktion=anlegen schema=wamo_dev email=a.b@c.test ergebnis=ok", "nutzer_anlegen", "info", {}),
        ("wamo-nutzer", "aktion=sperren schema=wamo_prod email=x@y.test ergebnis=fehler schritt=4", "nutzer_sperren", "fehler", {"schritt": 4}),
        ("wamo-auth", "einrichten: wamo_auth angewendet", "auth_eingerichtet", "info", {}),
        ("wamo-auth", "rueckweg: Trigger entfernt, Rechte entzogen", "auth_rueckweg", "warnung", {}),
        ("wamo-verteilung", "einsetzen version=0.7.1 sha256=" + "ab" * 32 + " signatur=ok vorher=0.7.0", "verteilung_einsetzen", "info", {"major": 0, "minor": 7, "patch": 1}),
        ("wamo-verteilung", "rueckweg aktuell=0.7.0 zuvor=0.7.1 signatur=ok", "verteilung_rueckweg", "warnung", {}),
        ("wamo-labor-geraete", "Gerät LAPTOP-07: 192.168.178.57 zugelassen", "geraet_zugelassen", "info", {}),
        ("wamo-labor-geraete", "Gerät LAPTOP-07: 192.168.178.57 entfernt (nicht mehr erreichbar)", "geraet_entfernt", "info", {}),
        ("wamo-labor-geraete", "WARNUNG Gerät LAPTOP-07: 3 Antworten im Büro-LAN", "geraet_warnung", "warnung", {}),
        ("wamo-labor-loeschen", "echtlauf start ziel=12", "labor_loeschen_start", "info", {"ziel": 12}),
        ("wamo-labor-loeschen", "echtlauf ziel=12 geloescht=12 fehler=0 verblieben=0 nachweis=ok", "labor_loeschen_ende", "info",
         {"ziel": 12, "geloescht": 12, "fehler": 0, "verblieben": 0}),
        ("wamo-labor-loeschen", "echtlauf ziel=12 geloescht=11 fehler=1 verblieben=1 nachweis=offen auswahl=a,b", "labor_loeschen_ende", "warnung",
         {"ziel": 12, "geloescht": 11, "fehler": 1, "verblieben": 1}),
        ("wamo-labor-loeschen", "echtlauf abgebrochen ziel=12 bearbeitet=3 geloescht=2 nachweis=fehlt", "labor_loeschen_abbruch", "fehler", {}),
    )

    def test_jede_marke_hat_muster_und_jeder_code_wird_von_einem_fall_erreicht(self):
        self.assertEqual({p[0] for p in self.POSITIV}, set(S.MARKEN))
        erreicht = {p[2] for p in self.POSITIV}
        # die Befehle des Ausrollens und die Aktionen der Nutzerverwaltung entstehen aus derselben Regelform: Jeder einzelne wird hier erzeugt
        for befehl in S.BEFEHLE_AUSROLLEN.split("|"):
            e = S.zeile_auswerten("wais-deploy", f"befehl={befehl} commit=keiner teil=keiner trocken=nein rueckgabe=0")
            self.assertEqual(e["code"], "ausrollen_" + befehl.replace("-", "_"))
            erreicht.add(e["code"])
        for aktion in S.AKTIONEN_NUTZER.split("|"):
            e = S.zeile_auswerten("wamo-nutzer", f"aktion={aktion} schema=wamo_test email=a@b.test ergebnis=ok")
            self.assertEqual(e["code"], "nutzer_" + aktion)
            erreicht.add(e["code"])
        self.assertEqual(S.CODES - erreicht, set())

    def test_positive_zeilen(self):
        for marke, zeile, soll_code, soll_stufe, soll_zahlen in self.POSITIV:
            with self.subTest(marke=marke, zeile=zeile[:50]):
                e = S.zeile_auswerten(marke, zeile)
                self.assertEqual(e, {"code": soll_code, "stufe": soll_stufe, "zahlen": soll_zahlen})

    def test_hohe_prioritaet_hebt_die_stufe_auf_fehler(self):
        self.assertEqual(S.zeile_auswerten("wamo-auth", "einrichten: wamo_auth angewendet", 3)["stufe"], "fehler")
        self.assertEqual(S.zeile_auswerten("wamo-auth", "einrichten: wamo_auth angewendet", 6)["stufe"], "info")

    def test_fremde_zeilen_verschwinden(self):
        for marke, zeile in (("wamo-nutzer", f"irgendein Text {MARKER}"), ("wamo-nutzer", f"aktion=loeschen schema=wamo_dev email=a@b.test ergebnis=ok"),
                             ("wamo-nutzer", "aktion=anlegen schema=wamo_xyz email=a@b.test ergebnis=ok"), ("wais-deploy", f"befehl=anderes commit=x teil=y trocken=nein rueckgabe=0 {MARKER}"),
                             ("wais-deploy", "befehl=verteilen commit=x teil=y trocken=nein rueckgabe=0\nzweite Zeile"), ("wamo-auth", "einrichten: wamo_auth angewendet "),
                             ("unbekannte-marke", "aktion=kanal ergebnis=ok"), ("wamo-job-kern", "aktion=kanal ergebnis=ok " + "x" * 700), ("wamo-job-kern", 12345),
                             ("wamo-job-kern", ["a", "b"]), ("wamo-job-kern", None), ("wamo-labor-geraete", f"Gerät {MARKER}"), ("wamo-verteilung", "einsetzen version=abc")):
            with self.subTest(marke=marke, zeile=str(zeile)[:40]):
                self.assertIsNone(S.zeile_auswerten(marke, zeile))

    def test_kein_marker_in_der_ausgabe(self):
        """Namen, Adressen, E-Mails, Hashes und Auswahl stecken in Zeilen, die das Muster verbraucht; keiner davon darf in einem Eintrag landen."""
        faelle = (("wamo-nutzer", f"aktion=anlegen schema=wamo_dev email={MARKER}@x.test ergebnis=ok"),
                  ("wais-deploy", f"befehl=verteilen commit={MARKER} teil={MARKER} trocken=nein rueckgabe=0"),
                  ("wamo-verteilung", f"einsetzen version=1.0.0 sha256={MARKER} signatur={MARKER} vorher={MARKER}"),
                  ("wamo-labor-geraete", f"Gerät {MARKER}: {MARKER} entfernt ({MARKER})"),
                  ("wamo-labor-geraete", f"WARNUNG Gerät {MARKER}: {MARKER}"),
                  ("wamo-labor-loeschen", f"echtlauf ziel=1 geloescht=1 fehler=0 verblieben=0 nachweis=ok auswahl={MARKER}"),
                  ("wamo-labor-loeschen", f"echtlauf abgebrochen {MARKER}"))
        for marke, zeile in faelle:
            e = S.zeile_auswerten(marke, zeile)
            self.assertIsNotNone(e, zeile)
            self.assertNotIn(MARKER, json.dumps(e))
            self.assertTrue(S.eintrag_pruefen({"zeit": "2026-11-20T10:00:00Z", "marke": marke, **e}))

    def test_eintrag_pruefen_ist_streng(self):
        gut = {"zeit": "2026-11-20T10:00:00Z", "marke": "wais-deploy", "stufe": "info", "code": "ausrollen_status", "zahlen": {"rueckgabe": 0}}
        self.assertTrue(S.eintrag_pruefen(gut))
        for aenderung in ({"extra": 1}, {"zeit": "20.11.2026"}, {"marke": "wamo-nutzer-x"}, {"stufe": "debug"}, {"code": "frei erfunden"}, {"code": "ausrollen_nie"},
                          {"zahlen": {"email": 1}}, {"zahlen": {"rueckgabe": "0"}}, {"zahlen": {"rueckgabe": True}}, {"zahlen": {"rueckgabe": -1}}, {"zahlen": []}):
            e = dict(gut, **aenderung)
            self.assertFalse(S.eintrag_pruefen(e), aenderung)
        self.assertFalse(S.eintrag_pruefen({k: v for k, v in gut.items() if k != "zahlen"}))
        self.assertFalse(S.eintrag_pruefen("zeile"))


class SammlerDateienTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="werkstatt-sammler-")
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)

    def eintrag(self, sekunden: float, nr: int = 0) -> dict:
        return {"zeit": S.zeit_text(sekunden), "marke": "wais-deploy", "stufe": "info", "code": "ausrollen_status", "zahlen": {"rueckgabe": nr % 5}}

    def test_aufbewahrung_zeilen_und_tage(self):
        jetzt = 1_800_000_000.0
        pfad = str(self.t / "wais-deploy.jsonl")
        neue = [self.eintrag(jetzt - 60 + i * 0.001 * 0, i) for i in range(10)]
        self.assertEqual(S.jsonl_fortschreiben(pfad, neue, jetzt, None), 10)
        # 2100 weitere in der Gegenwart: höchstens 2000 bleiben, die ältesten fallen weg
        viele = [self.eintrag(jetzt - 3000 + i) for i in range(2100)]
        self.assertEqual(S.jsonl_fortschreiben(pfad, viele, jetzt, None), S.MAX_ZEILEN)
        zeilen = Path(pfad).read_text(encoding="ascii").splitlines()
        self.assertEqual(len(zeilen), 2000)
        # eine Zeile älter als 30 Tage und eine kaputte Zeile fallen beim nächsten Lauf weg
        with open(pfad, "a", encoding="ascii") as f:
            f.write(json.dumps(self.eintrag(jetzt - 31 * 86400)) + "\n")
            f.write("das ist kein json\n")
            f.write(json.dumps({"zeit": "2026-11-20T10:00:00Z", "marke": "wais-deploy", "stufe": "info", "code": "ausrollen_status", "zahlen": {}, "extra": MARKER}) + "\n")
        self.assertEqual(S.jsonl_fortschreiben(pfad, [], jetzt, None), 2000)
        inhalt = Path(pfad).read_text(encoding="ascii")
        self.assertNotIn(MARKER, inhalt)
        self.assertNotIn("kein json", inhalt)
        self.assertEqual(sorted(p.name for p in self.t.iterdir()), ["wais-deploy.jsonl"])   # keine Zwischendatei bleibt liegen

    def test_ungueltige_neue_eintraege_werden_nie_geschrieben(self):
        pfad = str(self.t / "x.jsonl")
        schlecht = {"zeit": "2026-11-20T10:00:00Z", "marke": "wais-deploy", "stufe": "info", "code": "ausrollen_status", "zahlen": {}, "roh": "Zeile mit " + MARKER}
        self.assertEqual(S.jsonl_fortschreiben(pfad, [schlecht], 1_800_000_000.0, None), 0)
        self.assertNotIn(MARKER, Path(pfad).read_text(encoding="ascii"))

    def test_atomar_schreiben_ersetzt_ganz_und_raeumt_auf(self):
        pfad = str(self.t / "betrieb.json")
        S.atomar_schreiben(pfad, b'{"a":1}\n', None)
        S.atomar_schreiben(pfad, b'{"a":2}\n', None)
        self.assertEqual(Path(pfad).read_bytes(), b'{"a":2}\n')
        self.assertEqual([p.name for p in self.t.iterdir()], ["betrieb.json"])
        if os.name != "nt":
            self.assertEqual(oct(os.stat(pfad).st_mode & 0o777), "0o640")

    def test_betrieb_schema(self):
        gut = {"zeit": "2026-11-20T10:00:00Z", "kern": {"slot": "a", "release": "v0.7.1-3fb4443", "aktiv": True}, "oberflaeche": {"farbe": "blau", "version": "0.7.1"},
               "installer": {"version": "0.7.1"}, "kanal": {"zustand": "zu"}, "labor_dienst": {"zustand": "ok"}}
        self.assertTrue(S.betrieb_pruefen(gut))
        for pfad, wert in ((("kern", "slot"), "c"), (("kern", "release"), "../x"), (("kern", "aktiv"), "ja"), (("oberflaeche", "farbe"), "rot"), (("oberflaeche", "version"), "v1"),
                           (("installer", "version"), "1.2"), (("kanal", "zustand"), "vielleicht"), (("labor_dienst", "zustand"), "kaputt"), (("zeit",), "gestern")):
            kopie = json.loads(json.dumps(gut))
            ziel = kopie
            for teil in pfad[:-1]:
                ziel = ziel[teil]
            ziel[pfad[-1]] = wert
            self.assertFalse(S.betrieb_pruefen(kopie), pfad)
        zusatz = json.loads(json.dumps(gut))
        zusatz["kern"]["name"] = "x"
        self.assertFalse(S.betrieb_pruefen(zusatz))
        self.assertFalse(S.betrieb_pruefen({**gut, "extra": 1}))

    def test_quellen_des_betriebsstands(self):
        caddy = self.t / "caddy"
        (caddy / "etc" / "kern").mkdir(parents=True)
        (caddy / "etc" / "kern" / "slot.inc").write_text("# Erzeugt von wamo-core-slots.sh. Aktiver Slot: b. Eingebunden von x\nhandle {\n}\n", encoding="utf-8")
        (caddy / "etc" / "kern" / "wamo-ui-aktiv.inc").write_text("# live=gruen vorige=blau\n# seit=1\n", encoding="utf-8")
        k = S.kern_stand(str(caddy), str(self.t / "kein-opt"), lauf=lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"active\n", b""))
        self.assertEqual(k, {"slot": "b", "release": None, "aktiv": True})
        (caddy / "etc" / "kern" / "slot.inc").write_text("handle {\n\timport kern_weiter /run/wamo-core/core.sock\n}\n", encoding="utf-8")
        self.assertEqual(S.kern_stand(str(caddy), str(self.t), lauf=lambda *a, **kw: subprocess.CompletedProcess(a, 3, b"inactive\n", b""))["slot"], "alt")
        self.assertEqual(S.kern_stand(str(self.t / "gibt-es-nicht"), str(self.t))["slot"], "unbekannt")
        self.assertEqual(S.oberflaeche_stand(str(caddy), "ca", True), {"farbe": "gruen", "version": None})   # ohne Netz keine Version
        (caddy / "etc" / "kern" / "wamo-ui-aktiv.inc").write_text("# live=Tarnkappe vorige=blau\n", encoding="utf-8")
        self.assertEqual(S.oberflaeche_stand(str(caddy), "ca", True)["farbe"], "unbekannt")
        inst = self.t / "aktuell.json"
        inst.write_text(json.dumps({"version": "0.7.1", "datei": MARKER}), encoding="utf-8")
        self.assertEqual(S.installer_stand(str(inst)), {"version": "0.7.1"})
        inst.write_text(json.dumps({"version": f"0.7.1; {MARKER}"}), encoding="utf-8")
        self.assertEqual(S.installer_stand(str(inst)), {"version": None})
        self.assertEqual(S.installer_stand(str(self.t / "fehlt.json")), {"version": None})
        konf, notaus = self.t / "kernkanal.conf", self.t / "kernkanal.notaus"
        self.assertEqual(S.kanal_stand(str(konf), str(notaus)), {"zustand": "keiner"})
        konf.write_text("# Kommentar\nKANAL=offen\nMAX_BUDGET_USD=5\n", encoding="utf-8")
        self.assertEqual(S.kanal_stand(str(konf), str(notaus)), {"zustand": "offen"})
        konf.write_text("KANAL=zu # Standard\n", encoding="utf-8")
        self.assertEqual(S.kanal_stand(str(konf), str(notaus)), {"zustand": "zu"})
        konf.write_text("KANAL=weit offen\n", encoding="utf-8")
        self.assertEqual(S.kanal_stand(str(konf), str(notaus)), {"zustand": "ungueltig"})
        notaus.write_text("", encoding="utf-8")
        self.assertEqual(S.kanal_stand(str(konf), str(notaus)), {"zustand": "notaus"})
        self.assertEqual(S.labor_dienst_stand("ca", True), {"zustand": "nicht_erreichbar"})

    def test_journal_lesen_wertet_nur_passende_zeilen_aus(self):
        jetzt = time.time()
        zeilen = [journal_zeile("befehl=verteilen commit=abc teil=keiner trocken=nein rueckgabe=0", 6, jetzt),
                  journal_zeile(f"Fremde Zeile mit {MARKER}", 6, jetzt), b"kein json", journal_zeile("befehl=status commit=x teil=y trocken=nein rueckgabe=2", 3, jetzt),
                  json.dumps({"MESSAGE": [1, 2, 3], "__REALTIME_TIMESTAMP": "1"}).encode(), json.dumps({"MESSAGE": "x"}).encode()]
        befehle = []

        def lauf(befehl, **kw):
            befehle.append((befehl, kw))
            return subprocess.CompletedProcess(befehl, 0, b"\n".join(zeilen), b"")

        e = S.journal_lesen("wais-deploy", str(self.t), lauf=lauf)
        self.assertEqual([x["code"] for x in e], ["ausrollen_verteilen", "ausrollen_status"])
        self.assertEqual(e[1]["stufe"], "fehler")
        self.assertNotIn(MARKER, json.dumps(e))
        argv = befehle[0][0]
        self.assertEqual(argv[:3], ["/usr/bin/journalctl", "-t", "wais-deploy"])
        self.assertIn("-o", argv)
        self.assertIn("json", argv)
        self.assertTrue(any(a.startswith("--cursor-file=") for a in argv))
        self.assertIs(befehle[0][1].get("shell", False), False)
        self.assertEqual(befehle[0][1]["env"], S.UMGEBUNG)

    def test_journal_fehler_loescht_den_lesezeiger(self):
        zeiger = self.t / "wais-deploy.zeiger"
        zeiger.write_text("s=abc\n", encoding="utf-8")
        e = S.journal_lesen("wais-deploy", str(self.t), lauf=lambda b, **kw: subprocess.CompletedProcess(b, 1, b"", b"Failed to seek"))
        self.assertEqual(e, [])
        self.assertFalse(zeiger.exists())
        self.assertEqual(S.journal_lesen("wais-deploy", str(self.t), lauf=lambda b, **kw: (_ for _ in ()).throw(OSError("kein journalctl"))), [])

    def test_ein_lauf_schreibt_nur_schemagerechtes(self):
        daten = self.t / "daten"
        original = S.journal_lesen
        jetzt = time.time()

        def falsches_journal(marke, zustand, lauf=subprocess.run):
            roh = journal_zeile(f"aktion=anlegen schema=wamo_dev email={MARKER}@x.test ergebnis=ok", 6, jetzt) if marke == "wamo-nutzer" else journal_zeile("nichts", 6, jetzt)
            return original(marke, zustand, lauf=lambda b, **kw: subprocess.CompletedProcess(b, 0, roh, b""))

        S.journal_lesen = falsches_journal
        try:
            self.assertEqual(S.lauf_einmal(str(daten), str(self.t / "caddy"), "ca", True, jetzt=jetzt), 0)
            self.assertEqual(S.lauf_einmal(str(daten), str(self.t / "caddy"), "ca", True, jetzt=jetzt + 60), 0)
        finally:
            S.journal_lesen = original
        betrieb = json.loads((daten / "betrieb.json").read_text(encoding="ascii"))
        self.assertTrue(S.betrieb_pruefen(betrieb))
        self.assertEqual(sorted(p.name for p in (daten / "protokolle").iterdir()), sorted(f"{m}.jsonl" for m in S.MARKEN))
        zeilen = (daten / "protokolle" / "wamo-nutzer.jsonl").read_text(encoding="ascii").splitlines()
        self.assertEqual(len(zeilen), 2)   # zwei Läufe, je eine neue Zeile (das Journal ist hier eine Attrappe ohne Lesezeiger)
        for datei in (daten / "protokolle").iterdir():
            self.assertNotIn(MARKER, datei.read_text(encoding="ascii"))
            self.assertNotIn("x.test", datei.read_text(encoding="ascii"))
        self.assertNotIn(MARKER, (daten / "betrieb.json").read_text(encoding="ascii"))
        self.assertEqual(sorted(p.name for p in daten.iterdir()), ["betrieb.json", "protokolle", "zustand"])


# ====================================================================================== Probelauf der Skripte
@unittest.skipUnless(BASH and (os.name == "nt" or os.geteuid() != 0), "Probelauf braucht eine Bash und läuft nie als root")
class ProbelaufTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="werkstatt-skripte-")
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.wurzel = self.t / "w"
        self.quelle = self.t / "quelle"
        (self.quelle / "wamo_werkstatt").mkdir(parents=True)
        (self.quelle / "wamo_werkstatt" / "__init__.py").write_text("NAME = 'wamo_werkstatt'\n", encoding="utf-8")
        (self.quelle / "wamo_werkstatt" / "__pycache__").mkdir()
        (self.quelle / "wamo_werkstatt" / "__pycache__" / "x.pyc").write_bytes(b"\0")
        (self.quelle / "pyproject.toml").write_text('[project]\nname = "wamo-werkstatt"\ndependencies = ["fastapi>=0.115"]\n', encoding="utf-8")

    def lauf(self, skript: Path, *args: str, wurzel: str | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({"WAMO_WERKSTATT_WURZEL": posix(self.wurzel) if wurzel is None else wurzel, "WAMO_WERKSTATT_PYTHON": posix(sys.executable), "HOME": posix(self.t),
                    "LC_ALL": "C.UTF-8"})
        return subprocess.run([BASH, str(skript), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120, stdin=subprocess.DEVNULL)

    def einrichten(self, *args: str) -> subprocess.CompletedProcess:
        return self.lauf(EINRICHTEN, "einrichten", "--quelle", posix(self.quelle), *args)

    def p(self, *teile) -> Path:
        return self.wurzel.joinpath(*teile)

    def alle_dateien(self) -> list[str]:
        return sorted(str(p.relative_to(self.wurzel)).replace("\\", "/") for p in self.wurzel.rglob("*") if p.is_file()) if self.wurzel.exists() else []

    def test_trockenlauf_legt_nichts_an(self):
        for skript, args in ((EINRICHTEN, ("einrichten", "--quelle", posix(self.quelle), "--trocken")), (RUECKWEG, ("--trocken",)), (RUECKWEG, ("--entfernen", "--trocken"))):
            r = self.lauf(skript, *args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("[trocken]", r.stdout)
        self.assertFalse(self.wurzel.exists())

    def test_einrichten_baut_den_baum_und_ist_wiederholbar(self):
        r = self.einrichten()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        app = self.p("opt", "wamo-werkstatt", "app")
        self.assertEqual(sorted(str(p.relative_to(app)).replace("\\", "/") for p in app.rglob("*") if p.is_file()),
                         ["SHA256SUMS", "wamo-werkstatt-ausgang.nft", "wamo_werkstatt/__init__.py", "wamo_werkstatt_rauchtest.py", "wamo_werkstatt_sammler.py"])
        for zeile in (app / "SHA256SUMS").read_text(encoding="utf-8").splitlines():   # das Format von sha256sum
            m = re.fullmatch(r"([0-9a-f]{64}) [ *](?:\./)?(.+)", zeile)   # Linux: "Summe  ./Pfad", die Bash unter Windows: "Summe *./Pfad"
            self.assertIsNotNone(m, zeile)
            self.assertEqual(hashlib.sha256((app / m[2]).read_bytes()).hexdigest(), m[1], m[2])
        self.assertFalse(any("__pycache__" in str(p) for p in self.wurzel.rglob("*")))
        caddy_dir = posix(self.wurzel / "home" / "wamocon" / "wamo-tls" / "caddy")
        for u in UNITS:   # jede Unit wird unverändert installiert, nur der Platzhalter des Ordners von wamo-caddy wird ersetzt
            self.assertEqual(self.p("etc", "systemd", "system", u).read_text(encoding="utf-8"), lies(WERKSTATT / u).replace("__CADDY_DIR__", caddy_dir), u)
        self.assertIn("--caddy-dir " + posix(self.wurzel / "home" / "wamocon" / "wamo-tls" / "caddy"), self.p("etc", "systemd", "system", "wamo-werkstatt-sammler.service").read_text(encoding="utf-8"))
        self.assertEqual(self.p("etc", "wamo-werkstatt-ausgang", "regeln.nft").read_text(encoding="utf-8"), lies(WERKSTATT / "wamo-werkstatt-ausgang.nft"))
        self.assertEqual(self.p("home", "wamocon", "wamo-tls", "caddy", "etc", "kern", "wamo-werkstatt.caddy").read_text(encoding="utf-8"), lies(SITE))
        self.assertIn("d /run/wamo-werkstatt 2750 wamo-werkstatt wamocon -", self.p("etc", "tmpfiles.d", "wamo-werkstatt.conf").read_text(encoding="utf-8"))
        env = self.p("etc", "wamo-werkstatt", "werkstatt.env").read_text(encoding="utf-8")
        self.assertIn("WAMO_WERKSTATT_SCHEMA=wamo_dev", env)
        self.assertNotIn("__SCHEMA__", env)
        self.assertEqual(self.p("etc", "wamo-werkstatt", "admins").read_text(encoding="utf-8"), lies(WERKSTATT / "admins.vorlage"))
        self.assertTrue(self.p("var", "lib", "wamo-werkstatt", "zustand").is_dir())
        self.assertTrue(self.p("var", "lib", "wamo-werkstatt", "protokolle").is_dir())
        self.assertTrue(self.p("run", "wamo-werkstatt").is_dir())
        zweiter = self.einrichten()
        self.assertEqual(zweiter.returncode, 0, zweiter.stdout + zweiter.stderr)
        self.assertIn("werkstatt.env vorhanden (unverändert)", zweiter.stdout)

    def test_vorhandene_konfiguration_bleibt_unveraendert(self):
        self.assertEqual(self.einrichten().returncode, 0)
        admins = self.p("etc", "wamo-werkstatt", "admins")
        admins.write_text("123e4567-e89b-12d3-a456-426614174000\n", encoding="utf-8")
        env = self.p("etc", "wamo-werkstatt", "werkstatt.env")
        env.write_text(env.read_text(encoding="utf-8").replace("wamo_dev", "wamo_test"), encoding="utf-8")
        r = self.einrichten()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(admins.read_text(encoding="utf-8"), "123e4567-e89b-12d3-a456-426614174000\n")
        self.assertIn("WAMO_WERKSTATT_SCHEMA=wamo_test", env.read_text(encoding="utf-8"))
        self.assertIn("Schema: wamo_test", r.stdout)
        self.assertNotIn("keine Einträge", r.stdout)
        widerspruch = self.einrichten("--schema", "wamo_prod")
        self.assertEqual(widerspruch.returncode, 1)
        self.assertIn("werkstatt.env nennt das Schema wamo_test", widerspruch.stderr)

    def test_schema_option_beim_ersten_einrichten(self):
        r = self.einrichten("--schema", "wamo_test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WAMO_WERKSTATT_SCHEMA=wamo_test", self.p("etc", "wamo-werkstatt", "werkstatt.env").read_text(encoding="utf-8"))
        self.assertEqual(self.lauf(EINRICHTEN, "einrichten", "--quelle", posix(self.quelle), "--schema", "wamo_x; reboot", "--trocken").returncode, 1)
        self.assertEqual(self.lauf(EINRICHTEN, "einrichten", "--quelle", posix(self.quelle), "--schema", "wamo_x; reboot", "--trocken").stdout.count("reboot"), 0)

    def test_schema_des_kerns_wird_uebernommen_aber_nur_diese_zeile_gelesen(self):
        kern = self.p("etc", "wamo", "core.env")
        kern.parent.mkdir(parents=True)
        kern.write_text(f"ANTHROPIC_API_KEY=sk-{MARKER}\nWAMO_DB_SCHEMA=wamo_prod\n", encoding="utf-8")
        r = self.einrichten()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WAMO_WERKSTATT_SCHEMA=wamo_prod", self.p("etc", "wamo-werkstatt", "werkstatt.env").read_text(encoding="utf-8"))
        self.assertNotIn(MARKER, r.stdout + r.stderr)
        for datei in self.alle_dateien():
            if datei != "etc/wamo/core.env":
                self.assertNotIn(MARKER, self.p(*datei.split("/")).read_text(encoding="utf-8", errors="replace"), datei)

    def test_fehlerfaelle_der_quelle_brechen_ab(self):
        schlecht = self.quelle / "wamo_werkstatt" / "kaputt.py"
        schlecht.write_text("def kaputt(:\n", encoding="utf-8")
        r = self.einrichten()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Syntaxfehler", r.stderr)
        self.assertFalse(self.wurzel.exists())
        schlecht.unlink()
        for name in (".env", "geheim.env", "x.pem", "x.key"):
            datei = self.quelle / "wamo_werkstatt" / name
            datei.write_text("X=1\n", encoding="utf-8")
            r = self.einrichten()
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("Geheimnisdatei", r.stderr)
            datei.unlink()
        (self.quelle / "pyproject.toml").unlink()
        r = self.einrichten()
        self.assertEqual(r.returncode, 1)
        self.assertIn("pyproject.toml fehlt", r.stderr)
        self.assertFalse(self.wurzel.exists())

    def test_aufruf_und_wurzel_werden_geprueft(self):
        self.assertEqual(self.lauf(EINRICHTEN, "--unsinn").returncode, 2)
        self.assertEqual(self.lauf(RUECKWEG, "--unsinn").returncode, 2)
        for wurzel in ("relativ", "/tmp/a b", "/tmp/x;y", "/tmp/$(id)", "/tmp/a'b"):
            with self.subTest(wurzel=wurzel):
                self.assertEqual(self.lauf(EINRICHTEN, "einrichten", wurzel=wurzel).returncode, 1)
                self.assertEqual(self.lauf(RUECKWEG, "--entfernen", wurzel=wurzel).returncode, 1)

    def test_rueckweg_ohne_entfernen_laesst_dateien_stehen(self):
        self.assertEqual(self.einrichten().returncode, 0)
        r = self.lauf(RUECKWEG)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.p("home", "wamocon", "wamo-tls", "caddy", "etc", "kern", "wamo-werkstatt.caddy").exists())   # die Site ist weg
        self.assertTrue(self.p("opt", "wamo-werkstatt", "app", "SHA256SUMS").exists())
        self.assertTrue(self.p("etc", "wamo-werkstatt", "werkstatt.env").exists())

    def test_rueckweg_entfernt_nur_die_eigenen_ordner_und_ist_wiederholbar(self):
        self.assertEqual(self.einrichten().returncode, 0)
        fremd = self.p("opt", "anderes")
        fremd.mkdir(parents=True)
        (fremd / "datei").write_text("bleibt", encoding="utf-8")
        (self.p("etc", "wamo-labor")).mkdir(parents=True)
        (self.p("etc", "wamo-labor", "kern-token")).write_text("bleibt", encoding="utf-8")
        r = self.lauf(RUECKWEG, "--entfernen")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for weg in (("opt", "wamo-werkstatt"), ("etc", "wamo-werkstatt"), ("etc", "wamo-werkstatt-ausgang"), ("var", "lib", "wamo-werkstatt")):
            self.assertFalse(self.p(*weg).exists(), weg)
        for u in UNITS:
            self.assertFalse(self.p("etc", "systemd", "system", u).exists(), u)
        self.assertEqual((fremd / "datei").read_text(encoding="utf-8"), "bleibt")
        self.assertEqual(self.p("etc", "wamo-labor", "kern-token").read_text(encoding="utf-8"), "bleibt")
        self.assertTrue(self.p("etc", "tmpfiles.d", "wamo-werkstatt.conf").exists())   # der Ordner /run/wamo-werkstatt bleibt, solange wamo-caddy ihn einbindet
        self.assertTrue(self.p("home", "wamocon", "wamo-tls", "caddy", "docker-compose.yml").exists())   # das Compose von wamo-caddy bleibt unberührt
        self.assertEqual(self.lauf(RUECKWEG, "--entfernen").returncode, 0)

    @unittest.skipIf(os.name == "nt", "symbolische Links brauchen unter Windows besondere Rechte")
    def test_rueckweg_und_einrichten_folgen_keinem_link(self):
        self.assertEqual(self.einrichten().returncode, 0)
        ziel = self.t / "wichtig"
        ziel.mkdir()
        (ziel / "datei").write_text("bleibt", encoding="utf-8")
        shutil.rmtree(self.p("etc", "wamo-werkstatt"))
        os.symlink(ziel, self.p("etc", "wamo-werkstatt"))
        self.assertNotEqual(self.lauf(RUECKWEG, "--entfernen").returncode, 0)
        self.assertEqual((ziel / "datei").read_text(encoding="utf-8"), "bleibt")
        self.assertEqual(self.einrichten().returncode, 1)


# ====================================================================================== Rauchtest, Dokumentation
class RauchtestUndDokuTests(unittest.TestCase):
    def test_rauchtest_hat_alle_teile_und_gibt_nie_ein_token_aus(self):
        text = lies(RAUCHTEST)
        for soll in ("def teil_a", "def teil_b", "def teil_c", "def teil_d", "--produktiv", "--nach-rueckweg", "--token-admin", "--token-mitglied", "--token-labor", "--token-aal1",
                     "aal2_alter_s", "nicht_angemeldet", "WAMO-FW-ADMIN", "wamo_werkstatt_ausgang", "Cache-Control", "no-store"):
            self.assertIn(soll, text)
        for zeile in code(RAUCHTEST):
            self.assertNotRegex(zeile, r"print\([^)]*\btoken\b(?!_|-)", zeile)   # nie ein Token in die Ausgabe
        self.assertNotIn("password", text.lower())

    def test_namensvertrag_in_claude_md(self):
        zeile = next((z for z in lies(REPO / "CLAUDE.md").splitlines() if z.startswith("| Werkstatt (Betrieb) |")), None)
        self.assertIsNotNone(zeile, "Zeile Werkstatt (Betrieb) fehlt in der Tabelle")
        for soll in ("wamo-werkstatt", "/opt/wamo-werkstatt/app", "/etc/wamo-werkstatt", "/var/lib/wamo-werkstatt", "127.0.0.1:18095", "/run/wamo-werkstatt/werkstatt.sock", "55448",
                     "wamo-werkstatt-einrichten.sh", "wamo-werkstatt-rueckweg.sh", "wamo_werkstatt_rauchtest.py", "wamo_werkstatt_sammler.py", "wamo-werkstatt-sammler.timer",
                     "LAN_PORTS_ADMIN", "test_werkstatt_skripte.py"):
            self.assertIn(soll, zeile, soll)
        self.assertNotIn(chr(0x2014), zeile)
        self.assertNotIn(chr(0x2013), zeile)

    def test_namensvertrag_nennt_den_schalter_des_kerns(self):
        zeile = next((z for z in lies(REPO / "CLAUDE.md").splitlines() if z.startswith("| Labor-Karten nachladen (Kern) |")), None)
        self.assertIsNotNone(zeile, "Zeile Labor-Karten nachladen (Kern) fehlt in der Tabelle")
        for soll in ("WAMO_LABOR_KARTEN_NACHLADEN", "wamo-core-env", "AUS_ENV", "voice-core/labor_karten_db.py", "30 Sekunden", "labor_karten_aktive_version", "labor_wissen_aktiv",
                     "2000 Zeichen", "höchstens 20 Einträge", "letzte gültige Version", "ausgeschaltetem Schalter"):
            self.assertIn(soll, zeile, soll)
        self.assertNotIn(chr(0x2014), zeile)
        self.assertNotIn(chr(0x2013), zeile)
        self.assertIn("MIT ausgeschaltetem Schalter", lies(SOKRATES2 / "README.md"))   # der Rollout-Plan nennt den Kern-Release vor dem Zuschalten

    def test_abschnitt_im_readme_von_sokrates2(self):
        text = lies(SOKRATES2 / "README.md")
        self.assertIn("## 23. Werkstatt (Admin-Panel", text)
        abschnitt = text.split("## 23. Werkstatt (Admin-Panel", 1)[1]
        for soll in ("wamo-werkstatt-einrichten.sh", "wamo-werkstatt-rueckweg.sh", "wamo_werkstatt_rauchtest.py", "wamo_werkstatt_sammler.py", "55448", "127.0.0.1:18095",
                     "wamo-werkstatt-bruecke.socket", "/etc/wamo-werkstatt/admins", "db.zugang", "wamo_dienst_db.py einrichten werkstatt", "--trocken", "WAMO_WERKSTATT_WURZEL",
                     "test_werkstatt_skripte.py", "pg/requirements-werkstatt.lock"):
            self.assertIn(soll, abschnitt, soll)
        self.assertNotIn(chr(0x2014), abschnitt)
        self.assertNotIn(chr(0x2013), abschnitt)


if __name__ == "__main__":
    unittest.main()
