"""Tests für infra/sokrates2/wamo_labor_konten_loeschen.py (Laborkonten löschen, Entscheidung Q11, Befund 11, Löschfrist E12).

Aufruf (im Ordner infra/sokrates2, die Umgebung von voice-core genügt):
  D:/IDEA/Projekt/wamo/voice-core/.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q test_wamo_labor_konten_loeschen.py
Kein Netz und kein Server: Eine Attrappe im Prozess (lokaler HTTP-Server auf 127.0.0.1) spielt die Admin-Schnittstelle von GoTrue, eine zweite
Attrappe die Datenbank (dieselben Anweisungsnamen wie SQL im Werkzeug, Antworten im Format von psql -tA). Beide teilen einen Zustand ("Welt"):
Konten, Profile je Schema, Zeilen je Verweis, Sitzungen, Refresh-Tokens, Anmeldeprotokoll und laufende Sitzungen im Kern. Das Löschen in GoTrue
spielt die Kaskaden der Datenbank nach, ein Verweis mit Löschsperre lässt es scheitern wie am Server (HTTP 500, nichts geändert).
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_labor_konten_loeschen as lk  # noqa: E402

BESTAETIGT = ["--ausfuehren", "--bestaetigung", lk.BESTAETIGUNG]
# Verweise, wie sie der Katalog am Server liefern könnte: Konto, Profile, Gesprächstext, ein fremder Verweis (set null), ein Protokoll mit Sperre
FK_LISTE = (
    ("auth.identities", "user_id", "c"),
    ("auth.mfa_factors", "user_id", "c"),
    ("auth.sessions", "user_id", "c"),
    ("wamo_auth.erstanmeldungen", "user_id", "c"),
    ("wamo_dev.devices", "freigegeben_von", "n"),
    ("wamo_dev.profiles", "user_id", "c"),
    ("wamo_dev.release_anfragen", "angefordert_von", "r"),
    ("wamo_dev.turns", "user_id", "c"),
    ("wamo_prod.profiles", "user_id", "c"),
    ("wamo_test.profiles", "user_id", "c"),
)
ART = {(t, s): a for t, s, a in FK_LISTE}
SCHEMAS = ("wamo_dev", "wamo_prod", "wamo_test")
LABOR_SCHEMAS = ("wamo_dev", "wamo_test")  # wamo_prod ohne Spalte labor_art (Migration 0018 dort noch nicht angewandt)
MUSTER = re.compile(r"labor-(0[1-9]|1[0-6]|schau)@wamo\.test")


class Welt:
    """Gemeinsamer Zustand der beiden Attrappen und alles, was sie gesehen haben."""

    def __init__(self, tmp_path: Path):
        self.schluessel = "SRK-" + secrets.token_hex(16)
        self.geheim = [self.schluessel, "ANON-" + secrets.token_hex(16), "PGPW-" + secrets.token_hex(16), "JWTS-" + secrets.token_hex(16)]
        self.env = tmp_path / "supabase-wamo.env"
        self.env.write_text(f"# Testdatei\nSERVICE_ROLE_KEY={self.geheim[0]}\nANON_KEY='{self.geheim[1]}'\nPOSTGRES_PASSWORD=\"{self.geheim[2]}\"\n"
                            f"JWT_SECRET={self.geheim[3]}\nSITE_URL=https://localhost:55443\n", encoding="utf-8")
        self.konten: dict[str, dict] = {}
        self.profile: dict[str, dict[str, dict]] = {s: {} for s in SCHEMAS}
        self.zeilen: dict[str, dict[tuple[str, str], int]] = {}
        self.refresh: dict[str, int] = {}
        self.protokoll: dict[str, int] = {}
        self.kern: dict[tuple[str, str], int] = {}
        self.frisch: set[str] = set()  # Konten, deren Profil vor weniger als der Sperrfrist geändert wurde
        self.unlesbare_schemas: list[str] = []
        self.opt: dict[str, set] = {k: set() for k in ("loeschen_500", "sperre_ohne_banned", "fremde_adresse", "rest_nach_loeschen",
                                                        "sitzungen_rest", "unlesbar", "db_fehler_protokoll")}
        self.db_aufrufe: list[tuple[str, dict]] = []
        self.http: list[tuple[str, str, object, str | None, str | None]] = []
        self.ereignisse: list[tuple[str, str, str]] = []
        self.journal: list[str] = []
        self.warten: list[float] = []
        self.basis = ""

    # ---------- Bestand anlegen ----------
    def laborkonto(self, platz: int | None = None, *, art: str = "platz", email: str | None = None, schema: str = "wamo_dev",
                   labor_aktiv: bool = False, uid: str | None = None) -> str:
        kennung = "labor-schau" if art == "schaufenster" else f"labor-{platz:02d}"
        uid = uid or str(uuid.uuid4())
        self.konten.setdefault(uid, {"email": email or f"{kennung}@wamo.test", "letzte": "28.11.2026 08:15", "gesperrt": False})
        self.profile[schema][uid] = {"art": art, "platz": platz if art == "platz" else None, "labor_aktiv": labor_aktiv, "rolle": "mitglied",
                                     "aktiv": False}
        z = self.zeilen.setdefault(uid, {})
        z.update({("auth.identities", "user_id"): 1, ("auth.mfa_factors", "user_id"): 2, ("auth.sessions", "user_id"): 2,
                  (f"{schema}.profiles", "user_id"): 1, ("wamo_dev.turns", "user_id"): 4})
        self.refresh[uid] = 3
        self.protokoll[uid] = 12
        return uid

    def normales_konto(self, email: str, *, rolle: str = "mitglied", schema: str = "wamo_dev") -> str:
        uid = str(uuid.uuid4())
        self.konten[uid] = {"email": email, "letzte": None, "gesperrt": False}
        self.profile[schema][uid] = {"art": None, "platz": None, "labor_aktiv": False, "rolle": rolle, "aktiv": True}
        self.zeilen[uid] = {("auth.identities", "user_id"): 1, (f"{schema}.profiles", "user_id"): 1, ("wamo_dev.turns", "user_id"): 9}
        self.refresh[uid] = 1
        self.protokoll[uid] = 5
        return uid

    def kennung_von(self, uid: str) -> str:
        for schema in LABOR_SCHEMAS:
            p = self.profile[schema].get(uid)
            if p and p["art"]:
                return "labor-schau" if p["art"] == "schaufenster" else f"labor-{p['platz']:02d}"
        return ""

    def schnappschuss(self) -> tuple:
        return copy.deepcopy((self.konten, self.profile, self.zeilen, self.refresh, self.protokoll, self.kern))

    def schreibende(self) -> list[str]:
        return [n for n, _ in self.db_aufrufe if n in lk.SCHREIBEND]

    def http_aendernd(self) -> list[tuple]:
        return [e for e in self.http if e[0] in ("PUT", "DELETE", "POST")]

    # ---------- Datenbank (Attrappe von psql -tA) ----------
    @staticmethod
    def _uids(wert: str) -> list[str]:
        assert re.fullmatch(r"\{([0-9a-f-]{36}(,[0-9a-f-]{36})*)?\}", wert), wert
        return [u for u in wert.strip("{}").split(",") if u]

    def sql(self, name: str, **werte: str) -> str:
        assert name in lk.SQL, name
        for k, v in werte.items():
            assert k in ("uid", "uids", "schema"), k
            if k == "uid":
                assert lk.UUID_RE.fullmatch(v), v
            if k == "schema":
                assert lk.SCHEMA_RE.fullmatch(v), v
        self.db_aufrufe.append((name, dict(werte)))
        if "uid" in werte:
            self.ereignisse.append(("db", name, werte["uid"]))
        return getattr(self, "_sql_" + name)(**werte)

    def _sql_schemas(self) -> str:
        return json.dumps({"profile": list(SCHEMAS), "labor": list(LABOR_SCHEMAS), "unlesbar": self.unlesbare_schemas})

    def _sql_laborprofile(self, schema: str) -> str:
        assert schema in LABOR_SCHEMAS
        return json.dumps([{"uid": u, "art": p["art"], "platz": p["platz"], "labor_aktiv": p["labor_aktiv"], "rolle": p["rolle"], "aktiv": p["aktiv"]}
                           for u, p in sorted(self.profile[schema].items()) if p["art"]])

    def _sql_andere_profile(self, schema: str, uids: str) -> str:
        assert schema in LABOR_SCHEMAS
        return json.dumps([u for u in self._uids(uids) if u in self.profile[schema] and not self.profile[schema][u]["art"]])

    def _sql_profile_ohne_laborspalte(self, schema: str, uids: str) -> str:
        assert schema not in LABOR_SCHEMAS
        return json.dumps([u for u in self._uids(uids) if u in self.profile[schema]])

    def _sql_konten(self, uids: str) -> str:
        return json.dumps([{"uid": u, **self.konten[u]} for u in self._uids(uids) if u in self.konten])

    def _sql_muster_konten(self) -> str:
        return json.dumps(sorted(u for u, k in self.konten.items() if MUSTER.fullmatch(k["email"].lower())))

    def _sql_kernsitzungen(self, schema: str, uid: str) -> str:
        return str(self.kern.get((schema, uid), 0))

    def _sql_zaehlen(self, uid: str) -> str:
        z = self.zeilen.get(uid, {})
        # wie psql -tA mit \gexec: eine Zeile je Verweis (Format von json_build_object), zuletzt die Summenzeile
        werte = [(t, s, a, z.get((t, s), 0)) for t, s, a in FK_LISTE]
        werte += [("auth.audit_log_entries", "payload", "-", self.protokoll.get(uid, 0)), ("auth.refresh_tokens", "user_id", "-", self.refresh.get(uid, 0))]
        zeilen = [json.dumps({"tabelle": t, "spalte": s, "art": a, "n": None if t in self.opt["unlesbar"] else n}, separators=(" , ", " : "))
                  for t, s, a, n in sorted(werte)]
        zeilen.append(json.dumps({"konto": int(uid in self.konten)}))
        return "\n".join(zeilen)

    def _sql_sperrfrist(self, schema: str, uids: str) -> str:
        frisch = [u for u in self._uids(uids) if u in self.frisch and (self.profile[schema].get(u) or {}).get("art")]
        return str(lk.SPERRFRIST_S if frisch else 0)

    def _sql_profil_sperren(self, schema: str, uid: str) -> str:
        p = self.profile[schema].get(uid)
        if p and p["art"] and p["labor_aktiv"]:
            p["labor_aktiv"] = False
            self.frisch.add(uid)
            return "1"
        return "0"

    def _sql_sitzungen_widerrufen(self, uid: str) -> str:
        z = self.zeilen.setdefault(uid, {})
        sitzungen, refresh = z.get(("auth.sessions", "user_id"), 0), self.refresh.get(uid, 0)
        rest = 1 if uid in self.opt["sitzungen_rest"] else 0
        z[("auth.sessions", "user_id")] = rest
        self.refresh[uid] = 0
        return f"{sitzungen - rest}\n{refresh}\n{rest}"

    def _sql_protokoll_loeschen(self, uid: str) -> str:
        if uid in self.opt["db_fehler_protokoll"]:
            raise lk.Fehler("Datenbankfehler: ERROR:  permission denied for table audit_log_entries")
        n = self.protokoll.get(uid, 0)
        self.protokoll[uid] = 0
        return str(n)

    # ---------- GoTrue (Attrappe, über HTTP angesprochen) ----------
    def nutzer_json(self, uid: str) -> dict:
        k = self.konten[uid]
        email = "jemand-anderes@wamo.test" if uid in self.opt["fremde_adresse"] else k["email"]
        return {"id": uid, "email": email, "banned_until": "2126-01-01T00:00:00Z" if k["gesperrt"] else None}

    def gotrue_loeschen(self, uid: str, koerper: object) -> tuple[int, dict]:
        assert koerper == {"should_soft_delete": False}, koerper
        if uid in self.opt["loeschen_500"] or any(n for key, n in self.zeilen.get(uid, {}).items() if ART.get(key) in ("r", "a")):
            # der Fehlertext von GoTrue darf nie in die Ausgabe: er enthält hier absichtlich Geheimnisse
            return 500, {"code": 500, "error_code": "unexpected_failure", "msg": f"Database error deleting user {self.geheim[0]} {self.geheim[2]}"}
        del self.konten[uid]
        for schema in SCHEMAS:
            self.profile[schema].pop(uid, None)
        rest = {("wamo_dev.turns", "user_id"): 1} if uid in self.opt["rest_nach_loeschen"] else {}
        self.zeilen[uid] = {k: rest.get(k, 0) for k in self.zeilen.get(uid, {})}
        self.refresh[uid] = 0
        for schluessel in [s for s in self.kern if s[1] == uid]:
            del self.kern[schluessel]
        return 200, {}


def _handler(w: Welt):
    class Attrappe(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # noqa: D401
            return

        def _koerper(self) -> object:
            n = int(self.headers.get("Content-Length") or 0)
            roh = self.rfile.read(n) if n else b""
            try:
                return json.loads(roh) if roh else None
            except ValueError:
                return None

        def _senden(self, status: int, objekt: object = None) -> None:
            roh = json.dumps({} if objekt is None else objekt).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

        def _bearbeiten(self, methode: str) -> None:
            koerper = self._koerper()
            w.http.append((methode, self.path, koerper, self.headers.get("apikey"), self.headers.get("Authorization")))
            if self.headers.get("apikey") != w.schluessel or self.headers.get("Authorization") != "Bearer " + w.schluessel:
                return self._senden(401, {"error_code": "no_authorization"})
            m = re.fullmatch(r"/auth/v1/admin/users/([0-9a-f-]{36})", self.path)
            if not m:
                return self._senden(404, {})
            uid = m.group(1)
            w.ereignisse.append(("http", methode, uid))
            if uid not in w.konten:
                return self._senden(404, {"code": 404, "error_code": "user_not_found", "msg": "User not found"})
            if methode == "GET":
                return self._senden(200, w.nutzer_json(uid))
            if methode == "PUT":
                assert koerper == {"ban_duration": lk.SPERRE_DAUER}, koerper
                w.konten[uid]["gesperrt"] = True
                antwort = w.nutzer_json(uid)
                if uid in w.opt["sperre_ohne_banned"]:
                    antwort["banned_until"] = None
                return self._senden(200, antwort)
            if methode == "DELETE":
                return self._senden(*w.gotrue_loeschen(uid, koerper))
            return self._senden(405, {})

        def do_GET(self):  # noqa: N802
            self._bearbeiten("GET")

        def do_PUT(self):  # noqa: N802
            self._bearbeiten("PUT")

        def do_DELETE(self):  # noqa: N802
            self._bearbeiten("DELETE")

        def do_POST(self):  # noqa: N802
            self._bearbeiten("POST")

    return Attrappe


@pytest.fixture
def welt(tmp_path):
    w = Welt(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(w))
    faden = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    faden.start()
    w.basis = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield w
    finally:
        server.shutdown()
        server.server_close()


def laufen(w: Welt, capsys, *argumente: str, env: str | None = None) -> tuple[int, str]:
    code = lk.lauf([*argumente, "--basis", w.basis, "--env-datei", env or str(w.env)], db=w, journal=w.journal.append, warte=w.warten.append)
    return code, capsys.readouterr().out


def pruefe_ohne_geheimnisse(w: Welt, text: str) -> None:
    for g in w.geheim:
        assert g not in text
    assert not lk.JWT_RE.search(text)


# ---------------------------------------------------------------------------------------------------------------------------------
# Trockenlauf
# ---------------------------------------------------------------------------------------------------------------------------------

def test_trockenlauf_aendert_nichts_und_liest_keinen_schluessel(welt, capsys, tmp_path):
    welt.laborkonto(1)
    welt.laborkonto(2, labor_aktiv=True)
    welt.laborkonto(art="schaufenster")
    welt.normales_konto("kollege@firma.example")
    vorher = welt.schnappschuss()
    code, out = laufen(welt, capsys, env=str(tmp_path / "gibt-es-nicht.env"))
    assert code == lk.EXIT_OK
    assert welt.schnappschuss() == vorher
    assert welt.schreibende() == []
    assert welt.http == []  # GoTrue wird im Trockenlauf nie gerufen
    assert welt.journal == [] and welt.warten == []
    assert "Trockenlauf" in out and "Ziel (3 Konten):" in out
    for kennung in ("labor-01", "labor-02", "labor-schau"):
        assert kennung in out
    assert "l***1@wamo.test" in out and "labor-01@wamo.test" not in out  # Adressen nur maskiert
    assert "kollege" not in out
    assert "Plan (nur mit --ausfuehren --bestaetigung LABORKONTEN-LOESCHEN)" in out
    assert "wamo_dev.turns.user_id 4" in out and "Anmeldeprotokoll 12" in out  # Zählung vorher, nur Zahlen


def test_trockenlauf_zeigt_sperre_kernsitzung_und_unlesbares(welt, capsys):
    a = welt.laborkonto(1)
    b = welt.laborkonto(2)
    welt.zeilen[a][("wamo_dev.release_anfragen", "angefordert_von")] = 2
    welt.kern[("wamo_dev", b)] = 1
    welt.opt["unlesbar"].add("wamo_auth.erstanmeldungen")
    code, out = laufen(welt, capsys)
    assert code == lk.EXIT_OK
    assert "Achtung: Verweis mit Löschsperre: wamo_dev.release_anfragen.angefordert_von 2" in out
    assert "Achtung: laufende Sitzung im Kern (Schema wamo_dev)" in out
    assert "wamo_auth.erstanmeldungen.user_id nicht lesbar" in out
    assert welt.schreibende() == [] and welt.http == []


# ---------------------------------------------------------------------------------------------------------------------------------
# Auswahl: nur Laborprofil UND @wamo.test
# ---------------------------------------------------------------------------------------------------------------------------------

def test_nur_konten_mit_laborprofil_und_wamo_test_werden_geloescht(welt, capsys):
    ziel = welt.laborkonto(1)
    fremde_domain = welt.laborkonto(2, email="gast02@example.org")
    mitglied = welt.normales_konto("kollegin@wamo.test")
    admin = welt.normales_konto("chef@firma.example", rolle="admin")
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert ziel not in welt.konten
    assert {e[2] for e in welt.ereignisse if e[0] == "http"} == {ziel}  # GoTrue sieht nur das Ziel
    for uid in (fremde_domain, mitglied, admin):
        assert uid in welt.konten
        assert not any(w.get("uid") == uid for n, w in welt.db_aufrufe if n in lk.SCHREIBEND)
    assert welt.profile["wamo_dev"][fremde_domain]["art"] == "platz"
    assert "Nicht angefasst (1 Konto mit Laborprofil):" in out and "Adresse endet nicht auf @wamo.test" in out
    assert "verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): 1" in out
    assert code == lk.EXIT_FEHLER  # ein Laborprofil bleibt, der Nachweis ist nicht erbracht


def test_mitgliedskonto_mit_wamo_test_ohne_laborprofil_bleibt(welt, capsys):
    ziel = welt.laborkonto(1)
    mitglied = welt.normales_konto("labor-05@wamo.test")  # Laboradresse, aber kein Laborprofil
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK
    assert ziel not in welt.konten and mitglied in welt.konten
    assert welt.profile["wamo_dev"][mitglied]["aktiv"] is True
    assert welt.zeilen[mitglied][("wamo_dev.turns", "user_id")] == 9
    assert "Konten mit Laboradresse ohne Laborprofil: 1 (nicht angefasst, von Hand prüfen)" in out
    assert "verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): 0" in out


def test_laborprofil_ohne_passende_adresse_bleibt(welt, capsys):
    ziel = welt.laborkonto(1)
    falsch = welt.laborkonto(3, email="labor-04@wamo.test")  # richtige Domäne, aber nicht die Kennung des Profils
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert ziel not in welt.konten and falsch in welt.konten
    assert "Adresse passt nicht zur Kennung" in out
    assert code == lk.EXIT_FEHLER


def test_konto_mit_profil_ohne_laborkennzeichen_in_anderem_schema_bleibt(welt, capsys):
    uid = welt.laborkonto(1)
    welt.profile["wamo_prod"][uid] = {"art": None, "platz": None, "labor_aktiv": False, "rolle": "mitglied", "aktiv": True}
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert uid in welt.konten
    assert "hat ein Profil ohne Laborkennzeichen (Schema wamo_prod)" in out
    assert welt.http_aendernd() == []
    assert code == lk.EXIT_FEHLER


def test_admin_mit_laborprofil_bleibt(welt, capsys):
    uid = welt.laborkonto(1)
    welt.profile["wamo_dev"][uid]["rolle"] = "admin"
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert uid in welt.konten and "Rolle ist nicht mitglied" in out and welt.http_aendernd() == []
    assert code == lk.EXIT_FEHLER


# ---------------------------------------------------------------------------------------------------------------------------------
# Bestätigungswort, Höchstgrenze, Basis, Schlüssel
# ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("argumente", [
    ["--ausfuehren"],
    ["--ausfuehren", "--bestaetigung", "ja"],
    ["--ausfuehren", "--bestaetigung", "laborkonten-loeschen"],
    ["--bestaetigung", lk.BESTAETIGUNG],
])
def test_bestaetigungswort_ist_pflicht(welt, capsys, argumente):
    welt.laborkonto(1)
    vorher = welt.schnappschuss()
    code, out = laufen(welt, capsys, *argumente)
    assert code == lk.EXIT_EINGABE
    assert welt.db_aufrufe == [] and welt.http == []  # nicht einmal gelesen
    assert welt.schnappschuss() == vorher
    assert "Es wurde nichts geändert." in out


def test_hoechstgrenze_bricht_ohne_aenderung_ab(welt, capsys):
    for platz in range(1, 14):  # 13 Laborkonten, eins mehr als erlaubt
        welt.laborkonto(platz)
    vorher = welt.schnappschuss()
    code, out = laufen(welt, capsys)
    assert code == lk.EXIT_EINGABE and "Höchstgrenze ist 12" in out
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_EINGABE and "Höchstgrenze ist 12" in out
    assert welt.schnappschuss() == vorher
    assert welt.schreibende() == [] and welt.http == []
    assert welt.journal == ["echtlauf abgebrochen ohne Änderung: Höchstgrenze überschritten"]


def test_zwoelf_konten_liegen_noch_in_der_grenze(welt, capsys):
    for platz in range(1, 13):
        welt.laborkonto(platz)
    code, out = laufen(welt, capsys)
    assert code == lk.EXIT_OK and "Ziel (12 Konten):" in out


@pytest.mark.parametrize("basis", ["http://192.168.178.136:55321", "https://localhost:55321", "http://localhost:55321/auth", "ftp://localhost",
                                   "http://nutzer:pw@localhost:55321"])
def test_basis_nur_loopback_ohne_zusaetze(welt, capsys, basis):
    welt.laborkonto(1)
    code = lk.lauf([*BESTAETIGT, "--basis", basis, "--env-datei", str(welt.env)], db=welt, journal=welt.journal.append, warte=welt.warten.append)
    out = capsys.readouterr().out
    assert code == lk.EXIT_EINGABE and welt.db_aufrufe == [] and welt.http == []
    assert "nutzer:pw" not in out


def test_echtlauf_ohne_lesbare_env_datei_aendert_nichts(welt, capsys, tmp_path):
    welt.laborkonto(1)
    code, out = laufen(welt, capsys, *BESTAETIGT, env=str(tmp_path / "fehlt.env"))
    assert code == lk.EXIT_EINGABE and "nicht lesbar" in out
    assert welt.db_aufrufe == [] and welt.http == []
    leer = tmp_path / "leer.env"
    leer.write_text("ANON_KEY=x\n", encoding="utf-8")
    code, out = laufen(welt, capsys, *BESTAETIGT, env=str(leer))
    assert code == lk.EXIT_EINGABE and "SERVICE_ROLE_KEY fehlt" in out and welt.db_aufrufe == []


def test_kein_schluessel_in_ausgabe_und_journal(welt, capsys, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # ein Proxy aus der Umgebung gilt nie
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    ok = welt.laborkonto(1)
    scheitert = welt.laborkonto(2)
    welt.opt["loeschen_500"].add(scheitert)  # GoTrue antwortet mit einem Fehlertext, der Geheimnisse enthält
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert ok not in welt.konten  # der Aufruf ging ohne Proxy an GoTrue
    assert any(h[3] == welt.schluessel for h in welt.http)  # GoTrue hat den Schlüssel bekommen, die Prüfung ist also aussagekräftig
    pruefe_ohne_geheimnisse(welt, out)
    pruefe_ohne_geheimnisse(welt, "\n".join(welt.journal))
    assert "GoTrue HTTP 500 unexpected_failure" in out and "Database error" not in out
    assert code == lk.EXIT_FEHLER


def test_geheimnisse_werden_auch_aus_eigenen_texten_entfernt(welt, capsys):
    welt.laborkonto(1)
    welt.opt["db_fehler_protokoll"] = set(welt.konten)

    def mit_geheimnis(uid: str) -> str:
        raise lk.Fehler("Datenbankfehler: " + welt.geheim[2] + " " + welt.geheim[3])

    welt._sql_protokoll_loeschen = mit_geheimnis
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    pruefe_ohne_geheimnisse(welt, out)
    assert "FEHLER Schritt 5 (Anmeldeprotokoll): Datenbankfehler: *** ***" in out


# ---------------------------------------------------------------------------------------------------------------------------------
# Echtlauf: Ablauf, Teilfehler, Nachweis
# ---------------------------------------------------------------------------------------------------------------------------------

def test_nachweis_zaehlt_null_und_journal_ohne_adressen(welt, capsys):
    uids = [welt.laborkonto(p) for p in (1, 2, 9)] + [welt.laborkonto(art="schaufenster")]
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK
    assert not any(u in welt.konten for u in uids)
    assert all(not any(p["art"] for p in welt.profile[s].values()) for s in SCHEMAS)
    assert all(n == 0 for u in uids for n in welt.zeilen[u].values())
    assert all(welt.refresh[u] == 0 and welt.protokoll[u] == 0 for u in uids)
    assert "verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): 0" in out
    assert "Ergebnis: Nachweis erbracht." in out and "Nachweis (" in out
    assert out.count(": gelöscht (Sitzungen widerrufen 2, Protokolleinträge gelöscht 12)") == 4
    assert welt.journal == ["echtlauf start ziel=4", "echtlauf ziel=4 geloescht=4 fehler=0 verblieben=0 nachweis=ok"]
    assert "@" not in "".join(welt.journal)


def test_reihenfolge_je_konto_und_hartes_loeschen(welt, capsys):
    uid = welt.laborkonto(1)
    code, _ = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK
    schritte = [(art, name) for art, name, u in welt.ereignisse if u == uid and (art == "http" or name in lk.SCHREIBEND)]
    assert schritte == [("db", "profil_sperren"), ("http", "GET"), ("http", "PUT"), ("db", "sitzungen_widerrufen"), ("db", "protokoll_loeschen"),
                        ("http", "DELETE"), ("http", "GET")]
    loeschen = [h for h in welt.http if h[0] == "DELETE"]
    assert loeschen and all(h[2] == {"should_soft_delete": False} for h in loeschen)  # hart, nicht soft


def test_teilfehler_wird_gemeldet_und_der_rest_laeuft_weiter(welt, capsys):
    a, b, c = welt.laborkonto(1), welt.laborkonto(2), welt.laborkonto(3)
    welt.opt["loeschen_500"].add(b)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    assert a not in welt.konten and c not in welt.konten and b in welt.konten
    assert welt.konten[b]["gesperrt"] is True and welt.zeilen[b][("auth.sessions", "user_id")] == 0  # gesperrt und ohne Sitzungen
    assert "labor-02: FEHLER Schritt 6 (Konto löschen): GoTrue HTTP 500 unexpected_failure, das Konto bleibt gesperrt und ohne Sitzungen" in out
    assert "labor-01: gelöscht" in out and "labor-03: gelöscht" in out
    assert "verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): 1" in out
    assert "Ergebnis: Nachweis NICHT erbracht." in out
    assert welt.journal == ["echtlauf start ziel=3", "echtlauf ziel=3 geloescht=2 fehler=1 verblieben=1 nachweis=offen"]


def test_wiederholung_nach_teilfehler_findet_nur_den_rest(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.opt["loeschen_500"].add(b)
    assert laufen(welt, capsys, *BESTAETIGT)[0] == lk.EXIT_FEHLER
    assert a not in welt.konten and b in welt.konten
    welt.opt["loeschen_500"].clear()
    welt.http.clear()
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK and b not in welt.konten
    assert {h[1].rsplit("/", 1)[1] for h in welt.http} == {b}
    assert "Ziel (1 Konto):" in out


def test_sperre_ohne_bestaetigung_stoppt_vor_dem_widerruf(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.opt["sperre_ohne_banned"].add(a)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    assert "labor-01: FEHLER Schritt 3 (Konto sperren): Sperre nicht bestätigt" in out
    assert a in welt.konten and welt.zeilen[a][("auth.sessions", "user_id")] == 2
    assert not any(h[0] == "DELETE" and h[1].endswith(a) for h in welt.http)
    assert b not in welt.konten


def test_rest_nach_dem_widerruf_stoppt_vor_dem_loeschen(welt, capsys):
    a = welt.laborkonto(1)
    welt.opt["sitzungen_rest"].add(a)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER and a in welt.konten
    assert "FEHLER Schritt 4 (Sitzungen widerrufen): noch 1 Sitzungen oder Refresh-Tokens des Kontos vorhanden" in out
    assert not any(h[0] == "DELETE" for h in welt.http)


def test_laufende_kernsitzung_stoppt_nur_dieses_konto(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.kern[("wamo_dev", a)] = 1
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    assert "labor-01: FEHLER Schritt 2 (Vorprüfung): es läuft noch eine Sitzung im Kern (Schema wamo_dev)" in out
    assert a in welt.konten and welt.konten[a]["gesperrt"] is False
    assert not any(h[0] in ("PUT", "DELETE") and h[1].endswith(a) for h in welt.http)
    assert b not in welt.konten


def test_verweis_mit_loeschsperre_stoppt_vor_der_sperre(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.zeilen[a][("wamo_dev.release_anfragen", "angefordert_von")] = 1
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    assert "labor-01: FEHLER Schritt 2 (Vorprüfung): Verweis mit Löschsperre: wamo_dev.release_anfragen.angefordert_von 1" in out
    assert a in welt.konten and not any(h[0] in ("PUT", "DELETE") and h[1].endswith(a) for h in welt.http)
    assert b not in welt.konten


def test_gotrue_mit_anderer_adresse_wird_nicht_angefasst(welt, capsys):
    a = welt.laborkonto(1)
    welt.opt["fremde_adresse"].add(a)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER and a in welt.konten
    assert "GoTrue nennt ein anderes Konto oder eine andere Adresse" in out
    assert welt.http_aendernd() == [] and welt.konten[a]["gesperrt"] is False


def test_neues_profil_seit_der_suche_stoppt_das_konto(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.zeilen[a][("wamo_prod.profiles", "user_id")] = 1  # erscheint erst in der Zählung, nicht in der Suche
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER
    assert "labor-01: FEHLER Schritt 2 (Vorprüfung): die Profile des Kontos haben sich seit der Suche geändert" in out
    assert a in welt.konten and not any(h[0] in ("PUT", "DELETE") and h[1].endswith(a) for h in welt.http)
    assert b not in welt.konten


@pytest.mark.parametrize("argumente", [[], BESTAETIGT])
def test_unerwarteter_fehler_ohne_traceback_und_ohne_werte(welt, capsys, argumente):
    welt.laborkonto(1)

    def kaputt() -> str:
        raise ValueError("labor-01@wamo.test " + welt.geheim[0])

    welt._sql_schemas = kaputt
    code, out = laufen(welt, capsys, *argumente)
    assert code == lk.EXIT_FEHLER and "FEHLER unerwarteter Fehler (ValueError)" in out
    assert "Traceback" not in out and "labor-01@wamo.test" not in out
    pruefe_ohne_geheimnisse(welt, out)
    assert welt.journal == (["echtlauf abgebrochen ohne Änderung: Bestand nicht lesbar"] if argumente else [])


def test_freigeschaltetes_profil_wird_gesperrt_und_die_sperrfrist_abgewartet(welt, capsys):
    a = welt.laborkonto(1, labor_aktiv=True)
    welt.laborkonto(2)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK
    assert welt.warten == [lk.SPERRFRIST_S + 1]
    assert "Schritt 1: jetzt gesperrt: 1 Profile. Ein Ziel-Profil wurde vor weniger als 185 Sekunden geändert" in out
    gesperrt = [i for i, e in enumerate(welt.ereignisse) if e == ("db", "profil_sperren", a)]
    erste_aenderung = min(i for i, e in enumerate(welt.ereignisse) if e[0] == "http" and e[1] in ("PUT", "DELETE"))
    assert gesperrt and gesperrt[0] < erste_aenderung


def test_ohne_freigeschaltete_profile_keine_wartezeit(welt, capsys):
    welt.laborkonto(1)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK and welt.warten == [] and "die Sperrfrist ist bei allen Ziel-Profilen abgelaufen" in out


def test_nachpruefung_offen_bei_resten_und_unlesbarem(welt, capsys):
    a = welt.laborkonto(1)
    welt.opt["rest_nach_loeschen"].add(a)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER and a not in welt.konten
    assert "labor-01: gelöscht (Sitzungen widerrufen 2, Protokolleinträge gelöscht 12), Nachprüfung offen: wamo_dev.turns.user_id 1" in out
    assert welt.journal == ["echtlauf start ziel=1", "echtlauf ziel=1 geloescht=1 fehler=1 verblieben=0 nachweis=offen"]


@pytest.mark.parametrize("tabelle, name", [("wamo_auth.erstanmeldungen", "wamo_auth.erstanmeldungen.user_id"),
                                           ("auth.refresh_tokens", "auth.refresh_tokens"), ("auth.audit_log_entries", "Anmeldeprotokoll")])
def test_nicht_lesbare_tabelle_stoppt_vor_jeder_aenderung(welt, capsys, tabelle, name):
    a = welt.laborkonto(1)
    welt.opt["unlesbar"].add(tabelle)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER and a in welt.konten
    assert f"labor-01: FEHLER Schritt 2 (Vorprüfung): Zählung unvollständig, nicht lesbar oder nicht prüfbar: {name}" in out
    assert welt.http_aendernd() == [] and welt.schreibende() == ["profil_sperren"]


def test_verweis_der_nur_auf_null_gesetzt_wuerde_stoppt_vor_der_sperre(welt, capsys):
    a, b = welt.laborkonto(1), welt.laborkonto(2)
    welt.zeilen[a][("wamo_dev.devices", "freigegeben_von")] = 1
    code, out = laufen(welt, capsys)
    assert code == lk.EXIT_OK
    assert "Achtung: Verweis, den das Löschen nur auf null setzen würde (die Zeile bliebe stehen): wamo_dev.devices.freigegeben_von 1" in out
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_FEHLER and a in welt.konten and b not in welt.konten
    assert "labor-01: FEHLER Schritt 2 (Vorprüfung): Verweis, den das Löschen nur auf null setzen würde" in out
    assert "Erst den Nachlauf laufen lassen (labor_loeschen)" in out
    assert not any(h[0] in ("PUT", "DELETE") and h[1].endswith(a) for h in welt.http)


def test_sperrfrist_gilt_auch_nach_einem_abgebrochenen_lauf(welt, capsys):
    a = welt.laborkonto(1)
    welt.frisch.add(a)  # ein voriger Lauf hat das Profil gerade gesperrt und wurde in der Wartezeit abgebrochen
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK and welt.warten == [lk.SPERRFRIST_S + 1]
    assert "Schritt 1: jetzt gesperrt: 0 Profile. Ein Ziel-Profil wurde vor weniger als 185 Sekunden geändert" in out


def test_nach_der_sperrfrist_wird_neu_gesucht(welt, capsys):
    a, b = welt.laborkonto(1, labor_aktiv=True), welt.laborkonto(2)

    def warte(sekunden: float) -> None:
        welt.warten.append(sekunden)
        # während der Wartezeit bekommt das Konto ein Profil ohne Laborkennzeichen in einem anderen Schema
        welt.profile["wamo_prod"][a] = {"art": None, "platz": None, "labor_aktiv": False, "rolle": "mitglied", "aktiv": True}
        welt.zeilen[a][("wamo_prod.profiles", "user_id")] = 1

    code = lk.lauf([*BESTAETIGT, "--basis", welt.basis, "--env-datei", str(welt.env)], db=welt, journal=welt.journal.append, warte=warte)
    out = capsys.readouterr().out
    assert code == lk.EXIT_FEHLER and a in welt.konten and b not in welt.konten
    assert "labor-01: FEHLER Schritt 2 (Vorprüfung): nach der Sperrfrist kein Ziel mehr, nicht angefasst" in out
    assert not any(h[1].endswith(a) for h in welt.http)


def test_unlesbare_profiltabelle_bricht_ohne_aenderung_ab(welt, capsys):
    welt.laborkonto(1)
    welt.unlesbare_schemas = ["wamo_prod"]
    vorher = welt.schnappschuss()
    for argumente in ([], BESTAETIGT):
        code, out = laufen(welt, capsys, *argumente)
        assert code == lk.EXIT_FEHLER and "Profiltabelle im Schema wamo_prod für postgres nicht vollständig lesbar" in out
    assert welt.schnappschuss() == vorher and welt.http == [] and welt.schreibende() == []
    assert welt.journal == ["echtlauf abgebrochen ohne Änderung: Bestand nicht lesbar"]


def test_profil_in_zwei_laborschemas_wird_einmal_geloescht(welt, capsys):
    uid = welt.laborkonto(4)
    welt.laborkonto(4, schema="wamo_test", uid=uid)
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK and uid not in welt.konten
    assert sum(1 for h in welt.http if h[0] == "DELETE") == 1
    assert "wamo_dev platz 4 gesperrt; wamo_test platz 4 gesperrt" in out


def test_keine_laborkonten_ist_ein_erbrachter_nachweis(welt, capsys):
    welt.normales_konto("kollege@firma.example")
    code, out = laufen(welt, capsys, *BESTAETIGT)
    assert code == lk.EXIT_OK and "Ziel: kein Konto." in out and welt.http == []
    assert welt.journal == ["echtlauf ziel=0 geloescht=0 fehler=0 verblieben=0 nachweis=ok"]  # ohne Ziel keine Startzeile


# ---------------------------------------------------------------------------------------------------------------------------------
# Auswahl mit --kennung
# ---------------------------------------------------------------------------------------------------------------------------------

def test_kennung_loescht_nur_die_gewaehlten(welt, capsys):
    a, reserve = welt.laborkonto(1), welt.laborkonto(9)
    code, out = laufen(welt, capsys, *BESTAETIGT, "--kennung", "labor-09")
    assert code == lk.EXIT_OK
    assert reserve not in welt.konten and a in welt.konten
    assert welt.profile["wamo_dev"][a]["art"] == "platz"
    assert "Nicht gewählt (--kennung): labor-01" in out
    assert "verbliebene Laborkonten (Konten mit Laborprofil in einem Schema): 1, davon gewählt: 0" in out
    assert welt.journal == ["echtlauf start ziel=1 auswahl=labor-09",
                            "echtlauf ziel=1 geloescht=1 fehler=0 verblieben=1 nachweis=ok auswahl=labor-09"]


def test_kennung_mit_komma_und_fehlender_kennung(welt, capsys):
    welt.laborkonto(1)
    welt.laborkonto(2)
    code, out = laufen(welt, capsys, "--kennung", "labor-01,LABOR-07")
    assert code == lk.EXIT_OK
    assert "Ziel (1 Konto):" in out and "labor-07: kein Konto mit diesem Laborprofil gefunden (schon gelöscht?)" in out


@pytest.mark.parametrize("wert", ["admin", "labor-17", "labor-1", "labor-schau2"])
def test_ungueltige_kennung_wird_abgelehnt(welt, capsys, wert):
    welt.laborkonto(1)
    code, out = laufen(welt, capsys, "--kennung", wert)
    assert code == lk.EXIT_EINGABE and welt.db_aufrufe == [] and "keine Laborkennung" in out


# ---------------------------------------------------------------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("email, erwartet", [("labor-01@wamo.test", "l***1@wamo.test"), ("x@wamo.test", "x***@wamo.test"), ("", "***"),
                                              ("ohne-at", "***")])
def test_maskiert(email, erwartet):
    assert lk.maskiert(email) == erwartet


def test_datenbank_reicht_werte_nur_als_psql_variablen(monkeypatch):
    gesehen: dict = {}

    def run(befehl, **kw):
        gesehen.update(befehl=befehl, **kw)
        return subprocess.CompletedProcess(befehl, 0, stdout="7\n", stderr="")

    monkeypatch.setattr(lk.subprocess, "run", run)
    uid = str(uuid.uuid4())
    assert lk.Datenbank().sql("protokoll_loeschen", uid=uid) == "7"
    befehl = gesehen["befehl"]
    assert befehl[:5] == ["docker", "exec", "-i", "wamo-supabase-db", "psql"]
    assert ["-U", "postgres"] == befehl[befehl.index("-U"):befehl.index("-U") + 2]
    assert "ON_ERROR_STOP=1" in befehl and "--single-transaction" in befehl and f"uid={uid}" in befehl
    assert gesehen["input"] == lk.SQL["protokoll_loeschen"]
    assert "PGOPTIONS=-c default_transaction_read_only=on" not in befehl  # schreibende Anweisung
    lk.Datenbank().sql("zaehlen", uid=uid)
    befehl = gesehen["befehl"]
    assert befehl[:6] == ["docker", "exec", "-i", "-e", "PGOPTIONS=-c default_transaction_read_only=on", "wamo-supabase-db"]
    for name in set(lk.SQL) - lk.SCHREIBEND:
        lk.Datenbank().sql(name)
        assert "PGOPTIONS=-c default_transaction_read_only=on" in gesehen["befehl"], name


def test_sighup_und_sigterm_gelten_als_abbruch():
    with pytest.raises(KeyboardInterrupt):
        lk._als_abbruch(1, None)


def test_datenbankfehler_nennt_nur_die_erste_zeile_ohne_adressen(monkeypatch):
    def run(befehl, **kw):
        return subprocess.CompletedProcess(befehl, 1, stdout="", stderr="ERROR:  kaputt bei labor-01@wamo.test\nDETAIL:  Zeile mit Inhalt\n")

    monkeypatch.setattr(lk.subprocess, "run", run)
    with pytest.raises(lk.Fehler) as e:
        lk.Datenbank().sql("muster_konten")
    assert str(e.value) == "Datenbankfehler: ERROR:  kaputt bei ***"


def test_datenbank_ohne_docker(monkeypatch):
    def run(befehl, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(lk.subprocess, "run", run)
    with pytest.raises(lk.Fehler, match="nicht erreichbar"):
        lk.Datenbank().sql("schemas")


def test_journal_ruft_logger_ohne_adressen(monkeypatch):
    gesehen: list = []
    monkeypatch.setattr(lk.subprocess, "run", lambda befehl, **kw: gesehen.append(befehl))
    lk.journal_schreiben("echtlauf ziel=1 adresse labor-01@wamo.test")
    assert gesehen == [["logger", "-t", "wamo-labor-loeschen", "--", "echtlauf ziel=1 adresse ***"]]
    monkeypatch.setattr(lk.subprocess, "run", lambda befehl, **kw: (_ for _ in ()).throw(OSError("kein logger")))
    lk.journal_schreiben("geht trotzdem weiter")  # Fehler von logger werden ignoriert


def test_sql_nutzt_nur_bekannte_variablen_und_schreibt_nur_wo_erklaert():
    for name, text in lk.SQL.items():
        variablen = set(re.findall(r":'(\w+)'", text)) | set(re.findall(r':"(\w+)"', text))
        assert variablen <= {"uid", "uids", "schema"}, name
        schreibt = bool(re.search(r"\b(update|delete|insert|truncate|drop|alter)\b", text, re.IGNORECASE))
        assert schreibt == (name in lk.SCHREIBEND), name
    assert "should_soft_delete" not in "".join(lk.SQL.values())


def test_kopfkommentar_nennt_aufrufe_und_grenzen():
    kopf = lk.__doc__ or ""
    for teil in ("--ausfuehren --bestaetigung LABORKONTEN-LOESCHEN", "--kennung labor-09", "Höchstgrenze", "Grenzen, ehrlich", "Ausgänge",
                 "DELETE /auth/v1/admin/users/<id>", "PUT /auth/v1/admin/users/<id>", "python3 -E -s"):
        assert teil in kopf, teil
    assert lk.MAX_KONTEN == 12 and lk.BESTAETIGUNG == "LABORKONTEN-LOESCHEN"
    assert Path(lk.__file__).read_text(encoding="utf-8").startswith("#!/usr/bin/python3 -E -s\n")
