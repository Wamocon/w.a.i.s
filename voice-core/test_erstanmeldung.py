"""Tests der Erstanmeldung im Kern (Ausrollen P1b, Zweig A): Stand in der Entscheidung der Zugangskontrolle, Sperre in der Middleware
(Pfadliste mit raw_path), in identitaet() und bei jedem anderen Aufrufer von authorize, Route GET /wamo/api/erstanmeldung, SessionGuard.

Ohne Netz und ohne Datenbank: die Funktionen aus wamo_auth stehen als Attrappe im Profilverzeichnis.

Ausführen:  python -m pytest -q test_erstanmeldung.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import re
import types
import unittest
from unittest import mock

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from loguru import logger

import auth_gate
import bild_fern
import bot
import erstanmeldung_api
import labor_limit
import wamo_api
from auth_gate import AccessGate, AccessMiddleware, Identity
from memory import DatabaseUnavailable, ErstanmeldungFehlt, Profile, ProfileDirectory
from test_auth_gate import USER, token, verifier
from test_labor_sperre import SITZUNG, ZUSATZ, kern_routen, pipecat_routen

PFAD = "/wamo/api/erstanmeldung"
PASSWORT_PFAD = "/wamo/api/erstanmeldung/passwort"
SATZ_OFFEN = "Bitte ändere zuerst dein Startpasswort."
SATZ_ABGELAUFEN = "Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko."
CODES = {"offen": "passwort_wechsel_noetig", "abgelaufen": "startpasswort_abgelaufen"}
SAETZE = {"offen": SATZ_OFFEN, "abgelaufen": SATZ_ABGELAUFEN}
HINWEIS = "wamo-auth-einrichten.sh"


def profil(rolle="mitglied", aktiv=True, **kw) -> Profile:
    return Profile(user_id=USER, name="Erika Muster", rolle=rolle, aktiv=aktiv, anrede="du", **kw)


def laborprofil() -> Profile:
    return Profile(user_id=USER, name="Gast", rolle="mitglied", aktiv=False, anrede="du", labor_art="platz", labor_platz=3,
                   labor_aktiv=True)


class Verzeichnis:
    """Attrappe für memory.ProfileDirectory: Profil plus die beiden Funktionen aus wamo_auth (mit Zählern)."""

    def __init__(self, profil_=None, stand="keine", *, stand_fehler=None, begonnen=True, begonnen_fehler=None):
        self.profil = profil() if profil_ is None else profil_
        self.stand, self.stand_fehler = stand, stand_fehler
        self.begonnen, self.begonnen_fehler = begonnen, begonnen_fehler
        self.calls = self.stand_calls = self.begonnen_calls = 0

    async def get(self, user_id):
        self.calls += 1
        return self.profil

    async def erstanmeldung_stand(self, user_id):
        self.stand_calls += 1
        if self.stand_fehler is not None:
            raise self.stand_fehler
        return self.stand

    async def erstanmeldung_begonnen(self, user_id):
        self.begonnen_calls += 1
        if self.begonnen_fehler is not None:
            raise self.begonnen_fehler
        return self.begonnen


class Uhr:
    def __init__(self):
        self.jetzt = 1000.0

    def __call__(self):
        return self.jetzt


def tor(verzeichnis: Verzeichnis, uhr: Uhr | None = None) -> AccessGate:
    return AccessGate(verifier(), verzeichnis, **({"clock": uhr} if uhr else {}))


class Protokoll:
    """Fängt die Logzeilen von loguru (eine Zeile je Aufruf). Setzt die Drossel der Logzeile zu fehlendem wamo_auth zurück, damit jeder
    Mitschnitt mit einem frischen Prozess beginnt."""

    def __enter__(self):
        auth_gate._hinweis_um = None
        self.zeilen: list[str] = []
        self._id = logger.add(lambda m: self.zeilen.append(str(m).rstrip("\n")), level="DEBUG", format="{message}")
        return self

    def __exit__(self, *exc):
        logger.remove(self._id)

    def mit(self, text: str) -> list[str]:
        return [z for z in self.zeilen if text in z]


# ---------- Datenbank: ProfileDirectory ----------
class Db:
    configured = True
    schema = "wamo_test"

    def __init__(self, wert=None, fehler=None):
        self.wert, self.fehler, self.sql = wert, fehler, []

    def t(self, name):
        return f"wamo_test.{name}"

    async def fetchval(self, sql, *args):
        self.sql.append((sql, args))
        if self.fehler is not None:
            raise self.fehler
        return self.wert


class VerzeichnisTests(unittest.IsolatedAsyncioTestCase):
    async def test_stand_ruft_die_funktion_in_wamo_auth(self):
        db = Db("offen")
        self.assertEqual(await ProfileDirectory(db).erstanmeldung_stand(USER.upper()), "offen")
        sql, args = db.sql[0]
        self.assertIn("wamo_auth.erstanmeldung_stand($1::uuid)", sql)
        self.assertEqual(args, (USER,))  # kanonische UUID, nie der Rohwert

    async def test_begonnen_ruft_die_funktion_und_liefert_bool(self):
        for wert, erwartet in ((True, True), (False, False), (None, False)):
            with self.subTest(wert=wert):
                db = Db(wert)
                self.assertIs(await ProfileDirectory(db).erstanmeldung_begonnen(USER), erwartet)
                self.assertIn("wamo_auth.erstanmeldung_begonnen($1::uuid)", db.sql[0][0])

    async def test_fehlendes_schema_funktion_oder_recht_heisst_erstanmeldung_fehlt(self):
        for fehler in (asyncpg.UndefinedFunctionError("function wamo_auth.erstanmeldung_stand(uuid) does not exist"),
                       asyncpg.InvalidSchemaNameError('schema "wamo_auth" does not exist'),
                       asyncpg.InsufficientPrivilegeError("permission denied for schema wamo_auth")):
            for methode in ("erstanmeldung_stand", "erstanmeldung_begonnen"):
                with self.subTest(fehler=type(fehler).__name__, methode=methode):
                    with self.assertRaises(ErstanmeldungFehlt) as ctx:
                        await getattr(ProfileDirectory(Db(fehler=fehler)), methode)(USER)
                    self.assertNotIn("wamo_auth", str(ctx.exception))  # nur der Fehlertyp, nie die Meldung der Datenbank

    async def test_andere_datenbankfehler_bleiben_datenbank_nicht_erreichbar(self):
        for fehler in (asyncpg.UndefinedColumnError("x"), OSError("weg"), asyncio.TimeoutError()):
            with self.subTest(fehler=type(fehler).__name__):
                with self.assertRaises(DatabaseUnavailable) as ctx:
                    await ProfileDirectory(Db(fehler=fehler)).erstanmeldung_stand(USER)
                self.assertNotIsInstance(ctx.exception, ErstanmeldungFehlt)


# ---------- Zugangskontrolle: Stand in der Entscheidung ----------
class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_keine_und_erledigt_lassen_durch_wie_bisher(self):
        for stand in ("keine", "erledigt"):
            with self.subTest(stand=stand):
                d = await tor(Verzeichnis(stand=stand)).authorize(token())
                self.assertEqual((d.status, d.erstanmeldung), (200, stand))
                self.assertEqual(d.identity, Identity(USER, "Erika Muster", "mitglied", "du"))

    async def test_offen_und_abgelaufen_sind_403_mit_code_und_satz(self):
        for stand in ("offen", "abgelaufen"):
            with self.subTest(stand=stand):
                d = await tor(Verzeichnis(stand=stand)).authorize(token())
                self.assertIsNone(d.identity)
                self.assertEqual((d.status, d.code, d.reason, d.erstanmeldung), (403, CODES[stand], SAETZE[stand], stand))

    async def test_nur_mit_ausdruecklichem_schluesselwort_kommt_die_identitaet(self):
        for stand in ("offen", "abgelaufen"):
            with self.subTest(stand=stand):
                d = await tor(Verzeichnis(stand=stand)).authorize(token(), weg_frei=True)
                self.assertEqual((d.identity.user_id, d.erstanmeldung, d.status), (USER, stand, 200))

    async def test_admin_wird_ebenso_gesperrt(self):
        d = await tor(Verzeichnis(profil(rolle="admin"), stand="offen")).authorize(token())
        self.assertEqual((d.identity, d.code), (None, "passwort_wechsel_noetig"))

    async def test_laborprofil_fragt_den_stand_nie_ab(self):
        # auch wenn die Funktion fehlt: ein Laborprofil darf nie auf 503 gehen
        v = Verzeichnis(laborprofil(), stand_fehler=ErstanmeldungFehlt("UndefinedFunctionError"))
        for frei in (False, True):
            d = await tor(v).authorize(token(), weg_frei=frei)
            self.assertEqual((d.status, d.identity.labor_art, d.erstanmeldung), (200, "platz", None))
        self.assertEqual(v.stand_calls, 0)

    async def test_inaktives_oder_fehlendes_profil_fragt_den_stand_nicht_ab(self):
        for p in (profil(aktiv=False), None):
            v = Verzeichnis(stand="offen")
            v.profil = p
            d = await tor(v).authorize(token())
            self.assertEqual(d.status, 403)
            self.assertNotEqual(d.code, "passwort_wechsel_noetig")
            self.assertEqual(v.stand_calls, 0)

    async def test_fehlende_funktion_ist_503_mit_genau_einer_logzeile(self):
        for fehler in (asyncpg.UndefinedFunctionError("x"), asyncpg.InvalidSchemaNameError("x"),
                       asyncpg.InsufficientPrivilegeError("x")):
            with self.subTest(fehler=type(fehler).__name__):
                db = Db(fehler=fehler)

                class Echt(Verzeichnis):
                    async def erstanmeldung_stand(self, user_id):
                        return await ProfileDirectory(db).erstanmeldung_stand(user_id)

                with Protokoll() as log:
                    d = await tor(Echt()).authorize(token())
                self.assertEqual((d.identity, d.status), (None, 503))
                self.assertEqual(len(log.mit(HINWEIS)), 1, log.zeilen)
                self.assertIn("wamo_auth fehlt: zuerst wamo-auth-einrichten.sh", log.mit(HINWEIS)[0])
                self.assertNotIn(HINWEIS, d.reason)

    async def test_unbekannter_wert_ist_503_fail_closed(self):
        for wert in (None, "", "OFFEN", "offen ", "gesperrt", 5, True, b"keine", ["keine"]):
            with self.subTest(wert=wert):
                with Protokoll() as log:
                    d = await tor(Verzeichnis(stand=wert)).authorize(token(), weg_frei=True)
                self.assertEqual((d.identity, d.status), (None, 503))
                self.assertEqual(len(log.mit(HINWEIS)), 1, log.zeilen)

    async def test_datenbank_weg_ist_503_ohne_hinweis(self):
        with Protokoll() as log:
            d = await tor(Verzeichnis(stand_fehler=DatabaseUnavailable("weg"))).authorize(token())
        self.assertEqual((d.identity, d.status), (None, 503))
        self.assertEqual(log.mit(HINWEIS), [])

    async def test_unerwarteter_fehler_ist_503(self):
        d = await tor(Verzeichnis(stand_fehler=RuntimeError("kaputt"))).authorize(token())
        self.assertEqual((d.identity, d.status), (None, 503))

    async def test_fehler_werden_nicht_gecacht(self):
        v = Verzeichnis(stand_fehler=ErstanmeldungFehlt("UndefinedFunctionError"))
        g = tor(v)
        self.assertEqual((await g.authorize(token())).status, 503)
        v.stand_fehler = None
        self.assertIsNotNone((await g.authorize(token())).identity)
        self.assertEqual(v.stand_calls, 2)

    async def test_cache_offen_und_abgelaufen_10_sekunden(self):
        for stand in ("offen", "abgelaufen"):
            with self.subTest(stand=stand):
                uhr, v = Uhr(), Verzeichnis(stand=stand)
                g = tor(v, uhr)
                await g.authorize(token())
                uhr.jetzt += 9
                await g.authorize(token())
                self.assertEqual(v.stand_calls, 1)
                uhr.jetzt += 2
                await g.authorize(token())
                self.assertEqual(v.stand_calls, 2)

    async def test_cache_keine_und_erledigt_wie_das_profil(self):
        for stand in ("keine", "erledigt"):
            with self.subTest(stand=stand):
                uhr, v = Uhr(), Verzeichnis(stand=stand)
                g = tor(v, uhr)
                await g.authorize(token())
                uhr.jetzt += auth_gate.PROFILE_HIT_SECS - 1
                await g.authorize(token())
                self.assertEqual(v.stand_calls, 1)
                uhr.jetzt += 2
                await g.authorize(token())
                self.assertEqual(v.stand_calls, 2)

    async def test_langsamer_alter_leser_ueberschreibt_den_neuen_stand_nicht(self):
        # Leser A liest vor dem Wechsel (offen) und hängt; dann leert die Route den Cache und liest erledigt. A darf danach nicht
        # "offen" in den Cache schreiben, sonst wäre die Person nach dem Wechsel noch bis zu 10 Sekunden gesperrt.
        class Langsam(Verzeichnis):
            def __init__(self):
                super().__init__(stand="offen")
                self.freigabe = asyncio.Event()

            async def erstanmeldung_stand(self, user_id):
                wert = self.stand
                self.stand_calls += 1
                if self.stand_calls == 1:
                    await self.freigabe.wait()
                return wert

        v = Langsam()
        g = tor(v)
        leser_a = asyncio.create_task(g.erstanmeldung_stand(USER))
        await asyncio.sleep(0)
        v.stand = "erledigt"
        g.stand_vergessen(USER)
        self.assertEqual(await g.erstanmeldung_stand(USER), "erledigt")
        v.freigabe.set()
        self.assertEqual(await leser_a, "offen")  # A bekommt seinen Wert, schreibt ihn aber nicht in den Cache
        self.assertEqual(await g.erstanmeldung_stand(USER), "erledigt")
        self.assertEqual(v.stand_calls, 2)  # der dritte Aufruf kam aus dem Cache

    async def test_fehlendes_wamo_auth_hoechstens_eine_logzeile_je_zehn_sekunden(self):
        zeit = [100.0]
        v = Verzeichnis(stand_fehler=ErstanmeldungFehlt("UndefinedFunctionError"))
        with Protokoll() as log, mock.patch.object(auth_gate, "_uhr_hinweis", lambda: zeit[0]):
            for _ in range(3):
                self.assertEqual((await tor(v).authorize(token())).status, 503)
            zeit[0] += 9
            self.assertEqual((await tor(v).authorize(token())).status, 503)
            self.assertEqual(len(log.mit(HINWEIS)), 1)
            zeit[0] += 2
            self.assertEqual((await tor(v).authorize(token())).status, 503)
            self.assertEqual(len(log.mit(HINWEIS)), 2)
        self.assertEqual(v.stand_calls, 5)  # nichts gecacht

    async def test_stand_vergessen_leert_nur_dieses_profil(self):
        uhr, v = Uhr(), Verzeichnis(stand="offen")
        g = tor(v, uhr)
        await g.authorize(token())
        g.stand_vergessen("7d1e9c42-3b6a-4f8e-8c2d-5a9b0e1f2c3d")
        await g.authorize(token())
        self.assertEqual(v.stand_calls, 1)
        g.stand_vergessen(USER)
        await g.authorize(token())
        self.assertEqual(v.stand_calls, 2)


# ---------- Zentrale Sperre (erstanmeldung_sperre) ----------
class SperreTests(unittest.TestCase):
    ICH = Identity(USER, "Erika", "admin", "du", anmeldung=1.0)
    LABOR = Identity(USER, "Gast", "mitglied", "du", anmeldung=1.0, labor_art="platz", labor_platz=3, labor_aktiv=True)

    def test_identitaet_ohne_laborart_und_ohne_stand_ist_503(self):
        # Eine Entscheidung ohne Stand (fremdes oder altes Tor) ist nie frei: fail-closed
        for e in (types.SimpleNamespace(identity=self.ICH), auth_gate.Decision(self.ICH)):
            with self.subTest(e=type(e).__name__):
                d = auth_gate.erstanmeldung_sperre(e)
                self.assertEqual((d.identity, d.status), (None, 503))

    def test_frei_bleiben_labor_abgelehnte_und_erledigte(self):
        for e in (auth_gate.Decision(self.LABOR), types.SimpleNamespace(identity=self.LABOR), auth_gate.Decision(None, 401, "x"),
                  auth_gate.Decision(self.ICH, erstanmeldung="keine"), auth_gate.Decision(self.ICH, erstanmeldung="erledigt")):
            with self.subTest(e=e):
                self.assertIsNone(auth_gate.erstanmeldung_sperre(e))

    def test_gesperrt_und_unbekannt(self):
        for stand, status in (("offen", 403), ("abgelaufen", 403), ("vielleicht", 503), (5, 503)):
            with self.subTest(stand=stand):
                d = auth_gate.erstanmeldung_sperre(auth_gate.Decision(self.ICH, erstanmeldung=stand))
                self.assertEqual((d.identity, d.status), (None, status))

    def test_weg_frei_laesst_alles_durch(self):
        for stand in ("offen", "abgelaufen", None):
            self.assertIsNone(auth_gate.erstanmeldung_sperre(auth_gate.Decision(self.ICH, erstanmeldung=stand), weg_frei=True))


# ---------- Pfad der Erstanmeldung (exakt, raw_path) ----------
class PfadTests(unittest.TestCase):
    def test_nur_get_auf_dem_exakten_pfad(self):
        self.assertTrue(auth_gate.erstanmeldung_pfad("GET", PFAD, PFAD.encode()))
        self.assertTrue(auth_gate.erstanmeldung_pfad("GET", PFAD, None))  # Server ohne raw_path: der Pfad allein entscheidet
        self.assertTrue(auth_gate.erstanmeldung_pfad("GET", PFAD, PFAD.encode(), b""))

    def test_varianten_sind_gesperrt(self):
        faelle = [
            ("POST", PFAD, PFAD.encode(), b""), ("HEAD", PFAD, PFAD.encode(), b""), ("PUT", PFAD, PFAD.encode(), b""),
            ("get", PFAD, PFAD.encode(), b""), ("GET ", PFAD, PFAD.encode(), b""),
            ("GET", PFAD + "/", (PFAD + "/").encode(), b""), ("GET", PFAD, (PFAD + "/").encode(), b""),
            ("GET", PFAD, PFAD.encode(), b"x"), ("GET", PFAD, (PFAD + "?x").encode(), b""), ("GET", PFAD, (PFAD + "?").encode(), b""),
            ("GET", PFAD, b"/wamo/api%2Ferstanmeldung", b""), ("GET", PFAD, b"/wamo/api%2ferstanmeldung", b""),
            ("GET", PFAD, b"/wamo%2Fapi/erstanmeldung", b""), ("GET", PFAD, b"/wamo/api/erstanmeldun%67", b""),
            ("GET", PFAD, b"/wamo/api/erstanmeldung%2F", b""), ("GET", PFAD, b"//wamo/api/erstanmeldung", b""),
            ("GET", PFAD, b"/wamo/api//erstanmeldung", b""), ("GET", PFAD, b"/wamo/api/./erstanmeldung", b""),
            ("GET", PFAD, b"/wamo/api/x/../erstanmeldung", b""), ("GET", PFAD, b"/WAMO/api/erstanmeldung", b""),
            ("GET", PFAD, b"/wamo/api/erstanmeldung;x", b""), ("GET", PFAD, PFAD, b""),  # raw_path muss Bytes sein
            ("GET", PFAD + "/code", (PFAD + "/code").encode(), b""), ("GET", PFAD + "x", (PFAD + "x").encode(), b""),
            ("GET", "/wamo/api/erstanmeldun", b"/wamo/api/erstanmeldun", b""), ("GET", "/wamo/api", b"/wamo/api", b""),
            ("GET", "/wamo/api/Erstanmeldung", b"/wamo/api/Erstanmeldung", b""), ("GET", PFAD + "\x00", PFAD.encode() + b"\x00", b""),
            ("GET", "//wamo/api/erstanmeldung", b"//wamo/api/erstanmeldung", b""), (None, PFAD, PFAD.encode(), b""),
            ("GET", None, PFAD.encode(), b""), ("GET", PFAD, "ä".encode(), b""),
        ]
        for methode, pfad, roh, query in faelle:
            with self.subTest(methode=methode, pfad=pfad, roh=roh, query=query):
                self.assertFalse(auth_gate.erstanmeldung_pfad(methode, pfad, roh, query))

    def test_fremde_query_typen_sind_gesperrt(self):
        self.assertFalse(auth_gate.erstanmeldung_pfad("GET", PFAD, PFAD.encode(), "x"))

    def test_passwortweg_nur_post_auf_dem_exakten_pfad(self):
        self.assertTrue(auth_gate.erstanmeldung_pfad("POST", PASSWORT_PFAD, PASSWORT_PFAD.encode(), b""))
        self.assertTrue(auth_gate.erstanmeldung_pfad("POST", PASSWORT_PFAD, None))
        p = PASSWORT_PFAD
        faelle = [
            ("GET", p, p.encode(), b""), ("PUT", p, p.encode(), b""), ("PATCH", p, p.encode(), b""), ("post", p, p.encode(), b""),
            ("POST", PFAD, PFAD.encode(), b""), ("POST", p, p.encode(), b"x=1"), ("POST", p, (p + "?").encode(), b""),
            ("POST", p + "/", (p + "/").encode(), b""), ("POST", p, (p + "/").encode(), b""),
            ("POST", p, b"/wamo/api/erstanmeldung%2Fpasswort", b""), ("POST", p, b"/wamo/api/erstanmeldung%2fpasswort", b""),
            ("POST", p, b"/wamo/api/erstanmeldung/passwor%74", b""), ("POST", p, b"//wamo/api/erstanmeldung/passwort", b""),
            ("POST", p, b"/wamo/api/erstanmeldung/./passwort", b""), ("POST", p, b"/wamo/api/erstanmeldung//passwort", b""),
            ("POST", p, b"/wamo/api/erstanmeldung/passwort;x", b""), ("POST", p, p, b""),
            ("POST", "/wamo/api/erstanmeldung/Passwort", b"/wamo/api/erstanmeldung/Passwort", b""),
            ("POST", p + "x", (p + "x").encode(), b""), ("POST", "/wamo/api/erstanmeldung/passwor", b"/wamo/api/erstanmeldung/passwor", b""),
        ]
        for methode, pfad, roh, query in faelle:
            with self.subTest(methode=methode, pfad=pfad, roh=roh, query=query):
                self.assertFalse(auth_gate.erstanmeldung_pfad(methode, pfad, roh, query))


# ---------- Middleware: alles außer der Erstanmeldung ist gesperrt ----------
async def middleware(methode, pfad, verzeichnis, *, raw_path=None, query=b"", body=b"{}"):
    gerufen, gesendet = [], []

    async def app(scope, receive, send):
        gerufen.append((scope["method"], scope["path"]))
        await receive()

    queue = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        gesendet.append(message)

    scope = {"type": "http", "method": methode, "path": pfad, "query_string": query,
             "headers": [(b"authorization", f"Bearer {token()}".encode()), (b"content-length", str(len(body)).encode())]}
    if raw_path is not None:
        scope["raw_path"] = raw_path
    await AccessMiddleware(app, tor(verzeichnis))(scope, receive, send)
    return gerufen, gesendet


def kern_routen_wirksam() -> set[tuple[str, str]]:
    """Alle Routen unter /wamo/api, dynamisch aus den Modulen. Anders als test_labor_sperre.kern_routen auch mit FastAPI ab 0.14x, das
    eingehängte Router nur noch als _IncludedRouter mit effective_route_contexts zeigt (dort fände isinstance(APIRoute) nichts)."""
    app = FastAPI()
    wamo_api.installieren(app, None)
    routen: set[tuple[str, str]] = set()
    for route in app.routes:
        wirksam = getattr(route, "effective_route_contexts", None)
        kontexte = [route] if isinstance(route, APIRoute) else list((wirksam() if callable(wirksam) else wirksam) or [])
        for k in kontexte:
            pfad = re.sub(r"\{[^}]+\}", "abc", k.path)
            routen |= {(m, pfad) for m in set(k.methods or ()) | {"GET", "POST", "PUT", "PATCH", "DELETE"}}
    return routen


def alle_routen() -> set[tuple[str, str]]:
    kern = kern_routen_wirksam()
    assert len({p for _, p in kern}) >= 30, kern  # die Module sind wirklich eingehängt (nicht still leer)
    routen = set(pipecat_routen()) | set(kern_routen()) | kern | set(ZUSATZ)
    routen |= {("POST", "/start"), ("POST", "/api/offer"), ("PATCH", "/api/offer"), ("POST", f"/sessions/{SITZUNG}/api/offer"),
               ("PATCH", f"/sessions/{SITZUNG}/api/offer"), ("POST", "/wamo/api/geraet/binden"), ("GET", "/wamo/api/installer"),
               ("GET", "/wamo/api/modellzugang"), ("POST", "/wamo/api/modellzugang"), ("POST", PFAD + "/code"),
               ("GET", PASSWORT_PFAD), ("PUT", PASSWORT_PFAD)}
    return routen


ERLAUBT = {("GET", PFAD), ("POST", PASSWORT_PFAD)}


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_offen_und_abgelaufen_lassen_nur_die_erstanmeldung_durch(self):
        routen = alle_routen()
        self.assertGreater(len(routen), 100)
        self.assertLessEqual(ERLAUBT, routen)  # beide Routen sind eingehängt (ROUTEN_MODULE)
        for stand in ("offen", "abgelaufen"):
            for methode, pfad in sorted(routen):
                with self.subTest(stand=stand, methode=methode, pfad=pfad):
                    gerufen, gesendet = await middleware(methode, pfad, Verzeichnis(stand=stand), raw_path=pfad.encode())
                    if (methode, pfad) in ERLAUBT:
                        self.assertEqual(gerufen, [(methode, pfad)])
                        continue
                    self.assertEqual(gerufen, [])
                    self.assertEqual(gesendet[0]["status"], 403)
                    self.assertIn((b"cache-control", b"no-store"), gesendet[0]["headers"])
                    antwort = json.loads(gesendet[1]["body"])
                    self.assertEqual(antwort, {"error": "nicht berechtigt", "detail": SAETZE[stand], "code": CODES[stand]})

    async def test_start_und_offer_sind_gesperrt_ohne_den_body_zu_lesen(self):
        for pfad in ("/start", "/api/offer", f"/sessions/{SITZUNG}/api/offer"):
            with self.subTest(pfad=pfad):
                body = json.dumps({"sdp": "v=0", "type": "offer"}).encode()
                gerufen, gesendet = await middleware("POST", pfad, Verzeichnis(stand="offen"), body=body)
                self.assertEqual((gerufen, gesendet[0]["status"]), ([], 403))

    async def test_kodierungstricks_auf_dem_pfad_der_erstanmeldung_sind_gesperrt(self):
        for roh, query in ((b"/wamo/api%2Ferstanmeldung", b""), (b"/wamo/api/erstanmeldung%2f", b""), (PFAD.encode(), b"x"),
                           ((PFAD + "/").encode(), b""), (b"//wamo/api/erstanmeldung", b"")):
            with self.subTest(roh=roh, query=query):
                gerufen, gesendet = await middleware("GET", PFAD, Verzeichnis(stand="offen"), raw_path=roh, query=query)
                self.assertEqual((gerufen, gesendet[0]["status"]), ([], 403))
                self.assertEqual(json.loads(gesendet[1]["body"])["code"], "passwort_wechsel_noetig")

    async def test_keine_und_erledigt_lassen_alles_durch_wie_bisher(self):
        for stand in ("keine", "erledigt"):
            for methode, pfad in (("POST", "/start"), ("POST", "/api/offer"), ("GET", "/wamo/api/hinweise"), ("GET", PFAD),
                                  ("POST", "/wamo/api/geraet/binden"), ("GET", "/status")):
                with self.subTest(stand=stand, pfad=pfad):
                    gerufen, _ = await middleware(methode, pfad, Verzeichnis(stand=stand), raw_path=pfad.encode())
                    self.assertEqual(gerufen, [(methode, pfad)])

    async def test_laborprofil_kommt_nie_an_die_erstanmeldung_und_der_stand_wird_nie_gelesen(self):
        v = Verzeichnis(laborprofil(), stand="offen")
        gerufen, gesendet = await middleware("GET", PFAD, v, raw_path=PFAD.encode())
        self.assertEqual((gerufen, gesendet[0]["status"]), ([], 403))
        self.assertEqual(json.loads(gesendet[1]["body"])["code"], "labor_pfad_gesperrt")
        self.assertEqual(v.stand_calls, 0)

    async def test_fehlende_funktion_ist_503_auch_fuer_die_erstanmeldung(self):
        for pfad in (PFAD, "/start"):
            with self.subTest(pfad=pfad):
                v = Verzeichnis(stand_fehler=ErstanmeldungFehlt("UndefinedFunctionError"))
                gerufen, gesendet = await middleware("GET" if pfad == PFAD else "POST", pfad, v, raw_path=pfad.encode())
                self.assertEqual((gerufen, gesendet[0]["status"]), ([], 503))


# ---------- identitaet() und andere Aufrufer von authorize ----------
def anfrage(tok: str | None = None) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/x", "query_string": b"",
                             "headers": [(b"authorization", f"Bearer {tok or token()}".encode())]})


class IdentitaetTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        wamo_api.gate_setzen(None)

    async def test_ohne_schluesselwort_lehnt_offen_und_abgelaufen_ab(self):
        for stand in ("offen", "abgelaufen"):
            with self.subTest(stand=stand):
                wamo_api.gate_setzen(tor(Verzeichnis(stand=stand)))
                with self.assertRaises(HTTPException) as ctx:
                    await wamo_api.identitaet(anfrage())
                self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (403, SAETZE[stand]))
                self.assertEqual(ctx.exception.code, CODES[stand])
                self.assertEqual(ctx.exception.headers, {"Cache-Control": "no-store"})

    async def test_jede_ablehnung_aus_identitaet_ist_no_store(self):
        for g in (None, tor(Verzeichnis(stand_fehler=DatabaseUnavailable("weg")))):
            wamo_api.gate_setzen(g)
            with self.assertRaises(HTTPException) as ctx:
                await wamo_api.identitaet(anfrage())
            self.assertEqual((ctx.exception.status_code, ctx.exception.headers), (503, {"Cache-Control": "no-store"}))
        with self.assertRaises(HTTPException) as ctx:
            await wamo_api.identitaet(anfrage("kein.gueltiges.token"))
        self.assertEqual((ctx.exception.status_code, ctx.exception.headers["Cache-Control"]), (401, "no-store"))

    async def test_mit_schluesselwort_kommt_die_identitaet(self):
        for stand in ("offen", "abgelaufen", "keine", "erledigt"):
            with self.subTest(stand=stand):
                wamo_api.gate_setzen(tor(Verzeichnis(stand=stand)))
                self.assertEqual((await wamo_api.identitaet(anfrage(), weg_frei=True)).user_id, USER)

    async def test_keine_und_erledigt_ohne_schluesselwort_wie_bisher(self):
        for stand in ("keine", "erledigt"):
            with self.subTest(stand=stand):
                wamo_api.gate_setzen(tor(Verzeichnis(stand=stand)))
                self.assertEqual((await wamo_api.identitaet(anfrage())).user_id, USER)

    async def test_gesperrte_entscheidung_wird_auch_bei_fremdem_tor_abgelehnt(self):
        # Zweite Sicherung: liefert ein Tor trotz gesperrtem Stand eine Identität, lehnt identitaet() trotzdem ab
        class Offen:
            async def authorize(self, tok, *, weg_frei=False):
                return auth_gate.Decision(Identity(USER, "Erika", "mitglied", "du", anmeldung=1.0), erstanmeldung="offen")

        wamo_api.gate_setzen(Offen())
        with self.assertRaises(HTTPException) as ctx:
            await wamo_api.identitaet(anfrage())
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_bild_fern_bekommt_die_sperre(self):
        for stand, erwartet in (("offen", bild_fern.TEXT_FALSCH), ("abgelaufen", bild_fern.TEXT_FALSCH), ("erledigt", None)):
            with self.subTest(stand=stand):
                g = tor(Verzeichnis(profil(rolle="admin"), stand=stand))
                self.assertEqual(await bild_fern.pruefer(USER, lambda g=g: g)(token()), erwartet)

    async def test_bild_fern_lehnt_gesperrte_entscheidung_auch_bei_fremdem_tor_ab(self):
        class Offen:
            async def authorize(self, tok):
                return auth_gate.Decision(Identity(USER, "Erika", "admin", "du", anmeldung=1.0), erstanmeldung="abgelaufen")

        self.assertEqual(await bild_fern.pruefer(USER, lambda: Offen())(token()), bild_fern.TEXT_FALSCH)

    def test_jeder_aufrufer_von_authorize_ist_bekannt(self):
        # Neue Aufrufer müssen die Sperre bekommen (authorize sperrt ohne Schlüsselwort selbst); diese Liste zwingt zum Nachsehen
        aufrufer = set()
        for datei in pathlib.Path(__file__).parent.glob("*.py"):
            if datei.name.startswith(("test_", "conftest")):
                continue
            if re.search(r"\.authorize\(", datei.read_text(encoding="utf-8")):
                aufrufer.add(datei.name)
        self.assertEqual(aufrufer, {"auth_gate.py", "wamo_api.py", "bild_fern.py"})


# ---------- Route GET /wamo/api/erstanmeldung ----------
def app_mit(verzeichnis: Verzeichnis, uhr: Uhr | None = None) -> tuple[TestClient, AccessGate]:
    g = tor(verzeichnis, uhr)
    app = FastAPI()
    app.include_router(erstanmeldung_api.router, prefix="/wamo/api")

    @app.get("/wamo/api/hinweise")
    async def hinweise(request: Request):  # steht für jede andere Route
        await wamo_api.identitaet(request)
        return {"ok": True}

    app.add_middleware(AccessMiddleware, gate=g)
    wamo_api.gate_setzen(g)
    return TestClient(app), g


def kopf() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}"}


def nur_route(v: Verzeichnis) -> TestClient:
    """Die Routen der Erstanmeldung ohne Middleware (prüft, was die Routen selbst ablehnen)."""
    app = FastAPI()
    app.include_router(erstanmeldung_api.router, prefix="/wamo/api")
    wamo_api.gate_setzen(tor(v))
    return TestClient(app)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self._fenster = mock.patch.object(erstanmeldung_api, "_abfragen", labor_limit.AnfragenFenster(30, 600.0))
        self._fenster.start()

    def tearDown(self):
        self._fenster.stop()
        wamo_api.gate_setzen(None)

    def json_fehler(self, r, status: int, code: str) -> None:
        self.assertEqual((r.status_code, r.json().get("code")), (status, code), r.text)
        self.assertTrue(r.json().get("detail"))
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_fehler_des_get_als_json_mit_code_und_no_store(self):
        self.json_fehler(nur_route(Verzeichnis(laborprofil())).get(PFAD, headers=kopf()), 403, "labor_pfad_gesperrt")
        self.json_fehler(nur_route(Verzeichnis()).get(PFAD), 401, "nicht_angemeldet")
        self.json_fehler(nur_route(Verzeichnis(stand_fehler=DatabaseUnavailable("weg"))).get(PFAD, headers=kopf()), 503,
                         "nicht_pruefbar")
        self.json_fehler(nur_route(Verzeichnis(profil(aktiv=False))).get(PFAD, headers=kopf()), 403, "nicht_berechtigt")

    def test_ablehnung_der_middleware_ist_no_store(self):
        client, _ = app_mit(Verzeichnis(stand_fehler=DatabaseUnavailable("weg")))
        r = client.get(PFAD, headers=kopf())
        self.assertEqual((r.status_code, r.headers.get("cache-control")), (503, "no-store"))

    def test_ratengrenze_des_get(self):
        client, _ = app_mit(Verzeichnis(stand="offen"))
        for _ in range(30):
            self.assertEqual(client.get(PFAD, headers=kopf()).status_code, 200)
        self.json_fehler(client.get(PFAD, headers=kopf()), 429, "zu_oft")

    def test_haengender_vermerk_haelt_die_antwort_nicht_auf(self):
        class Haengt(Verzeichnis):
            async def erstanmeldung_begonnen(self, user_id):
                self.begonnen_calls += 1
                await asyncio.sleep(30)

        v = Haengt(stand="offen")
        client, _ = app_mit(v)
        with mock.patch.object(erstanmeldung_api, "BEGONNEN_ZEIT_SECS", 0.2), Protokoll() as log:
            r = client.get(PFAD, headers=kopf())
        self.assertEqual((r.status_code, r.json()["stand"], v.begonnen_calls), (200, "offen", 1))
        self.assertTrue(log.mit("begonnen"))

    def test_modul_ist_eingehaengt(self):
        self.assertIn("erstanmeldung_api", wamo_api.ROUTEN_MODULE)

    def test_antwort_mit_stand_mindestlaenge_und_no_store(self):
        for stand in ("keine", "offen", "abgelaufen", "erledigt"):
            with self.subTest(stand=stand):
                client, _ = app_mit(Verzeichnis(stand=stand))
                r = client.get(PFAD, headers=kopf())
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), {"stand": stand, "mindestlaenge": 12})
                self.assertEqual(r.headers["cache-control"], "no-store")

    def test_begonnen_nur_im_stand_offen(self):
        for stand, aufrufe in (("offen", 1), ("abgelaufen", 0), ("keine", 0), ("erledigt", 0)):
            with self.subTest(stand=stand):
                v = Verzeichnis(stand=stand)
                client, _ = app_mit(v)
                client.get(PFAD, headers=kopf())
                self.assertEqual(v.begonnen_calls, aufrufe)

    def test_fehler_bei_begonnen_wird_nur_geloggt(self):
        for fehler in (ErstanmeldungFehlt("UndefinedFunctionError"), DatabaseUnavailable("weg"), RuntimeError("kaputt")):
            with self.subTest(fehler=type(fehler).__name__):
                client, _ = app_mit(Verzeichnis(stand="offen", begonnen_fehler=fehler))
                with Protokoll() as log:
                    r = client.get(PFAD, headers=kopf())
                self.assertEqual((r.status_code, r.json()["stand"]), (200, "offen"))
                self.assertTrue(log.mit("begonnen"), log.zeilen)

    def test_route_leert_den_cache_und_liest_den_stand_neu(self):
        uhr, v = Uhr(), Verzeichnis(stand="offen")
        client, _ = app_mit(v, uhr)
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 403)
        v.stand = "erledigt"  # Passwort gewechselt, der Cache kennt noch "offen" (10 Sekunden)
        uhr.jetzt += 5
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 403)
        r = client.get(PFAD, headers=kopf())
        self.assertEqual(r.json()["stand"], "erledigt")
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 200)

    def test_ohne_route_gilt_der_cache_10_sekunden(self):
        uhr, v = Uhr(), Verzeichnis(stand="offen")
        client, _ = app_mit(v, uhr)
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 403)
        v.stand = "erledigt"
        uhr.jetzt += 11
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 200)

    def test_andere_route_bekommt_403_mit_code(self):
        client, _ = app_mit(Verzeichnis(stand="abgelaufen"))
        r = client.get("/wamo/api/hinweise", headers=kopf())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {"error": "nicht berechtigt", "detail": SATZ_ABGELAUFEN, "code": "startpasswort_abgelaufen"})

    def test_varianten_ueber_den_echten_client_sind_gesperrt(self):
        client, _ = app_mit(Verzeichnis(stand="offen"))
        for methode, pfad in (("GET", PFAD + "?x=1"), ("GET", "/wamo/api%2Ferstanmeldung"), ("POST", PFAD), ("HEAD", PFAD),
                              ("GET", PFAD + "/"), ("POST", PASSWORT_PFAD + "/"), ("POST", PASSWORT_PFAD + "?x=1"),
                              ("POST", "/wamo/api/erstanmeldung%2Fpasswort"), ("GET", PASSWORT_PFAD), ("PUT", PASSWORT_PFAD)):
            with self.subTest(methode=methode, pfad=pfad):
                r = client.request(methode, pfad, headers=kopf())
                self.assertEqual(r.status_code, 403, r.text)

    def test_fehlende_funktion_ist_503(self):
        client, _ = app_mit(Verzeichnis(stand_fehler=ErstanmeldungFehlt("InvalidSchemaNameError")))
        self.assertEqual(client.get(PFAD, headers=kopf()).status_code, 503)

    def test_laborprofil_wird_auch_in_der_route_abgelehnt(self):
        # Die Middleware lässt ein Laborprofil nie bis hierher; die Route prüft trotzdem selbst (ohne Middleware aufgerufen)
        v = Verzeichnis(laborprofil(), stand="offen")
        g = tor(v)
        app = FastAPI()
        app.include_router(erstanmeldung_api.router, prefix="/wamo/api")
        wamo_api.gate_setzen(g)
        r = TestClient(app).get(PFAD, headers=kopf())
        self.assertEqual(r.status_code, 403)
        self.assertEqual((v.stand_calls, v.begonnen_calls), (0, 0))


# ---------- Route POST /wamo/api/erstanmeldung/passwort (Weiterleitung an GoTrue) ----------
PW = "Neues-Passwort-7xQ!"  # 19 Bytes
KEY = "sb_publishable_test"
GOTRUE = "http://127.0.0.1:55321/auth/v1/user"


class GoTrue:
    """Attrappe für GoTrue hinter dem Envoy (httpx.MockTransport): merkt sich jede Anfrage und antwortet wie eingestellt."""

    def __init__(self, status=200, daten=None, *, fehler=None, nachher=None, kopf=None):
        self.status, self.daten, self.fehler, self.nachher, self.kopf = status, daten, fehler, nachher, kopf or {}
        self.anfragen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.anfragen.append(request)
        if self.fehler is not None:
            raise self.fehler
        if self.nachher is not None:
            self.nachher()
        if isinstance(self.daten, (bytes, str)):
            return httpx.Response(self.status, content=self.daten, headers=self.kopf)
        return httpx.Response(self.status, json=self.daten if self.daten is not None else {"id": USER}, headers=self.kopf)


class Mitschnitt:
    """Alle Logzeilen aus loguru und logging (auch httpx), um zu zeigen, dass das Passwort nirgends steht."""

    def __enter__(self):
        self.zeilen: list[str] = []
        self._id = logger.add(lambda m: self.zeilen.append(str(m)), level="TRACE", format="{message} {exception}", diagnose=True)

        class Senke(logging.Handler):
            def emit(s, record):
                self.zeilen.append(record.getMessage() + repr(record.args))

        self._senke = Senke(level=logging.DEBUG)
        self._vorher = logging.getLogger().level
        logging.getLogger().addHandler(self._senke)
        logging.getLogger().setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc):
        logger.remove(self._id)
        logging.getLogger().removeHandler(self._senke)
        logging.getLogger().setLevel(self._vorher)


class PasswortTests(unittest.TestCase):
    def setUp(self):
        self.gotrue = GoTrue()
        self._patches = [
            mock.patch.object(erstanmeldung_api, "_transport", httpx.MockTransport(lambda r: self.gotrue(r))),
            mock.patch.object(erstanmeldung_api, "_versuche", labor_limit.AnfragenFenster(5, 600.0)),
            mock.patch.dict(os.environ, {"SUPABASE_PUBLISHABLE_KEY": KEY}),
        ]
        for p in self._patches:
            p.start()
        os.environ.pop("WAMO_GOTRUE_INTERN_URL", None)  # patch.dict stellt die Umgebung danach wieder her

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        wamo_api.gate_setzen(None)

    fenster_neu = True  # je Aufruf ein frisches Ratenfenster; die Tests der Ratengrenze schalten das ab

    def senden(self, v: Verzeichnis, daten: object = None, *, roh: bytes | None = None, client: TestClient | None = None):
        if self.fenster_neu:
            erstanmeldung_api._versuche = labor_limit.AnfragenFenster(5, 600.0)  # patch.object stellt das Original danach wieder her
        client = client or app_mit(v)[0]
        self.kopf = {**kopf(), "Content-Type": "application/json"}
        inhalt = roh if roh is not None else json.dumps({"passwort": PW} if daten is None else daten).encode()
        return client.post(PASSWORT_PFAD, content=inhalt, headers=self.kopf)

    def fehler(self, r, status: int, code: str) -> None:
        self.assertEqual((r.status_code, r.json().get("code")), (status, code), r.text)
        self.assertEqual(r.headers.get("cache-control"), "no-store")
        self.assertTrue(r.json().get("detail"))

    def test_offen_wird_weitergereicht_und_der_stand_neu_gelesen(self):
        v = Verzeichnis(stand="offen")
        self.gotrue = GoTrue(200, nachher=lambda: setattr(v, "stand", "erledigt"))  # der Trigger setzt erledigt_at
        r = self.senden(v)
        self.assertEqual((r.status_code, r.json()), (200, {"stand": "erledigt"}))
        self.assertEqual(r.headers["cache-control"], "no-store")
        [anfrage] = self.gotrue.anfragen
        self.assertEqual((anfrage.method, str(anfrage.url)), ("PUT", GOTRUE))
        self.assertEqual(anfrage.headers["authorization"], self.kopf["Authorization"])  # unverändert weitergereicht
        self.assertEqual(anfrage.headers["apikey"], KEY)
        self.assertEqual(json.loads(anfrage.content), {"password": PW})

    def test_nach_erfolg_ohne_lesbaren_stand_bleibt_es_200(self):
        v = Verzeichnis(stand="offen")
        self.gotrue = GoTrue(200, nachher=lambda: setattr(v, "stand_fehler", DatabaseUnavailable("weg")))
        r = self.senden(v)
        self.assertEqual((r.status_code, r.json()), (200, {"stand": None}))

    def test_ohne_offenen_stand_keine_weiterleitung(self):
        for stand, status, code in (("abgelaufen", 403, "startpasswort_abgelaufen"), ("keine", 409, "kein_wechsel_noetig"),
                                    ("erledigt", 409, "kein_wechsel_noetig")):
            with self.subTest(stand=stand):
                self.fehler(self.senden(Verzeichnis(stand=stand)), status, code)
        self.assertEqual(self.gotrue.anfragen, [])

    def test_der_stand_wird_frisch_gelesen_nicht_aus_dem_cache(self):
        uhr, v = Uhr(), Verzeichnis(stand="offen")
        client, g = app_mit(v, uhr)
        self.assertEqual(client.get("/wamo/api/hinweise", headers=kopf()).status_code, 403)  # Cache kennt "offen" (10 s)
        v.stand = "abgelaufen"
        self.fehler(self.senden(v, client=client), 403, "startpasswort_abgelaufen")
        self.assertEqual(self.gotrue.anfragen, [])

    def test_laborprofil_nie_weitergereicht(self):
        v = Verzeichnis(laborprofil(), stand="offen")
        r = self.senden(v)  # mit Middleware: die Pfadliste des Labors kennt den Weg nicht
        self.assertEqual((r.status_code, r.json()["code"]), (403, "labor_pfad_gesperrt"))
        app = FastAPI()  # ohne Middleware: die Route lehnt selbst ab
        app.include_router(erstanmeldung_api.router, prefix="/wamo/api")
        wamo_api.gate_setzen(tor(v))
        self.fehler(self.senden(v, client=TestClient(app)), 403, "labor_pfad_gesperrt")
        self.assertEqual((self.gotrue.anfragen, v.stand_calls), ([], 0))

    def test_ungueltige_passwoerter_bleiben_im_kern(self):
        faelle = [{"passwort": "kurz"}, {"passwort": "a" * 11}, {"passwort": "a" * 73}, {"passwort": "ä" * 37},
                  {"passwort": "ä" * 6}, {"passwort": "ä" * 11}, {"passwort": "€" * 25}, {"passwort": "😀" * 19},
                  {"passwort": 123456789012345}, {"passwort": None}, {"passwort": ["a" * 20]}, {}, [], "a" * 20,
                  {"password": PW}, {"passwort": "\ud800" + "a" * 20}]
        for daten in faelle:
            with self.subTest(daten=repr(daten)[:40]):
                self.fehler(self.senden(Verzeichnis(stand="offen"), daten), 400, "passwort_ungueltig")
        for roh in (b"kein json", b"\xff\xfe", b"", b'{"passwort": "' + b"a" * 20):
            with self.subTest(roh=roh[:20]):
                self.fehler(self.senden(Verzeichnis(stand="offen"), roh=roh), 400, "passwort_ungueltig")
        self.assertEqual(self.gotrue.anfragen, [])

    def test_grenzen_der_laenge_gehen_durch(self):
        # mindestens 12 Zeichen (Codepunkte) und höchstens 72 Bytes in UTF-8
        for pw in ("a" * 12, "a" * 72, "ä" * 36, "ä" * 12, "€" * 24, "😀" * 12, "😀" * 18):
            with self.subTest(pw=pw[:3], laenge=len(pw.encode())):
                self.assertEqual(self.senden(Verzeichnis(stand="offen"), {"passwort": pw}).status_code, 200)
        self.assertEqual(len(self.gotrue.anfragen), 7)

    def test_zu_grosser_body_ist_413(self):
        self.fehler(self.senden(Verzeichnis(stand="offen"), {"passwort": "a" * 2000}), 413, "zu_gross")
        self.assertEqual(self.gotrue.anfragen, [])

    def test_ratengrenze_fuenf_versuche_je_zehn_minuten(self):
        self.fenster_neu = False
        self.gotrue = GoTrue(422, {"code": 422, "error_code": "weak_password", "msg": "x"})
        v = Verzeichnis(stand="offen")
        for _ in range(5):
            self.fehler(self.senden(v), 422, "weak_password")
        self.fehler(self.senden(v), 429, "zu_oft")
        self.assertEqual(len(self.gotrue.anfragen), 5)

    def test_ratengrenze_zaehlt_auch_abgelehnte_versuche(self):
        self.fenster_neu = False
        v = Verzeichnis(stand="offen")
        for _ in range(5):
            self.fehler(self.senden(v, {"passwort": "kurz"}), 400, "passwort_ungueltig")
        self.fehler(self.senden(v), 429, "zu_oft")
        self.assertEqual(self.gotrue.anfragen, [])

    def test_abbildung_der_antworten_von_gotrue(self):
        faelle = [
            (422, {"error_code": "same_password"}, 422, "same_password"),
            (422, {"error_code": "weak_password"}, 422, "weak_password"),
            (401, {"error_code": "insufficient_aal"}, 401, "insufficient_aal"),
            (400, {"error_code": "reauthentication_needed"}, 401, "reauthentication_needed"),
            (401, {"error_code": "reauthentication_needed"}, 401, "reauthentication_needed"),
            (403, {"error_code": "session_not_found"}, 401, "sitzung_ungueltig"),
            (401, {"error_code": "bad_jwt"}, 401, "sitzung_ungueltig"),
            (401, b"kein json", 401, "sitzung_ungueltig"),
            (403, {"error_code": "user_banned"}, 502, "anmeldedienst"),
            (422, {"error_code": "validation_failed"}, 502, "anmeldedienst"),
            (422, b"kein json", 502, "anmeldedienst"),
            (400, {"error_code": "same_password"}, 502, "anmeldedienst"),
            (500, {"error_code": "unexpected_failure"}, 502, "anmeldedienst"),
            (404, b"", 502, "anmeldedienst"),
            (201, {"id": USER}, 502, "anmeldedienst"),
            (422, {"error_code": ["same_password"]}, 502, "anmeldedienst"),
        ]
        for gs, daten, status, code in faelle:
            with self.subTest(gotrue=gs, daten=daten):
                self.gotrue = GoTrue(gs, daten)
                self.fehler(self.senden(Verzeichnis(stand="offen")), status, code)

    def test_netzfehler_zeitlimit_und_umleitung_sind_502(self):
        for gotrue in (GoTrue(fehler=httpx.ConnectError("weg")), GoTrue(fehler=httpx.ReadTimeout("zu langsam")),
                       GoTrue(302, b"", kopf={"location": "https://anderswo.example/auth/v1/user"})):
            with self.subTest(gotrue=gotrue.fehler or gotrue.status):
                self.gotrue = gotrue
                self.fehler(self.senden(Verzeichnis(stand="offen")), 502, "anmeldedienst")
                self.assertEqual(len(gotrue.anfragen), 1)  # keiner Umleitung gefolgt

    def test_passwort_nie_im_log_und_nie_in_der_antwort(self):
        gotrues = [GoTrue(200), GoTrue(422, {"error_code": "weak_password", "msg": f"zu schwach: {PW}"}),
                   GoTrue(500, f"kaputt {PW}"), GoTrue(fehler=httpx.ConnectError(f"weg {PW}")),
                   GoTrue(fehler=RuntimeError(f"unerwartet {PW}")), GoTrue(401, {"error_code": "bad_jwt", "msg": PW})]
        with Mitschnitt() as log:
            for gotrue in gotrues:
                self.gotrue = gotrue
                r = self.senden(Verzeichnis(stand="offen"))
                self.assertNotIn(PW, r.text)
            for daten in ({"passwort": PW + "x" * 80}, {"passwort": "\ud800" + PW}):  # auch abgelehnte Werte nie im Log
                self.assertNotIn(PW, self.senden(Verzeichnis(stand="offen"), daten).text)
        self.assertTrue(log.zeilen)
        self.assertFalse([z for z in log.zeilen if PW in z], log.zeilen)
        self.assertTrue([z for z in log.zeilen if "Passwort" in z and USER[:8] in z])  # Ergebnis mit gekürzter Profilkennung

    def test_interne_url_nur_loopback_oder_https_zum_stack(self):
        stack = "https://192.168.178.136:55443"
        gut = {None: GOTRUE, "": GOTRUE, "  ": GOTRUE, "http://127.0.0.1:55321": GOTRUE, "http://127.0.0.1:55321/": GOTRUE,
               "http://localhost:55321": "http://localhost:55321/auth/v1/user", "http://[::1]:55321": "http://[::1]:55321/auth/v1/user",
               "https://192.168.178.136:55443": "https://192.168.178.136:55443/auth/v1/user",
               "https://192.168.178.136:8443": "https://192.168.178.136:8443/auth/v1/user"}
        for wert, erwartet in gut.items():
            with self.subTest(wert=wert):
                self.assertEqual(erstanmeldung_api.gotrue_url(wert, stack), erwartet)
        for wert in ("http://192.168.178.136:55321", "http://127.0.0.1.example.com:55321", "http://127.0.0.2:55321",
                     "ftp://127.0.0.1:55321", "127.0.0.1:55321", "http://user:pw@127.0.0.1:55321", "http://@127.0.0.1:55321",
                     "http://127.0.0.1:55321/pfad", "http://127.0.0.1:55321?x=1", "http://127.0.0.1:55321#x",
                     "http://127.0.0.1:abc", "https://", "http://", "https:///auth", "http://0.0.0.0:55321", "file:///etc/passwd",
                     "https://gotrue.intern", "https://192.168.178.13:55443", "https://192.168.178.136.example.com",
                     "https://user@192.168.178.136:55443"):
            with self.subTest(wert=wert):
                self.assertIsNone(erstanmeldung_api.gotrue_url(wert, stack))
        for stack_ohne in (None, "", "http://127.0.0.1:55321", "kein url"):  # https nur, wenn SUPABASE_URL einen Host nennt
            with self.subTest(stack=stack_ohne):
                self.assertIsNone(erstanmeldung_api.gotrue_url("https://192.168.178.136:55443", stack_ohne))
                self.assertEqual(erstanmeldung_api.gotrue_url(None, stack_ohne), GOTRUE)

    def test_falsche_einrichtung_ist_503_ohne_weiterleitung(self):
        for umgebung in ({"WAMO_GOTRUE_INTERN_URL": "http://192.168.178.136:55321"},
                         {"WAMO_GOTRUE_INTERN_URL": "https://anderer.host", "SUPABASE_URL": "https://192.168.178.136:55443"}):
            with self.subTest(umgebung=umgebung), mock.patch.dict(os.environ, umgebung):
                self.fehler(self.senden(Verzeichnis(stand="offen")), 503, "anmeldedienst")
        os.environ.pop("SUPABASE_PUBLISHABLE_KEY")
        self.fehler(self.senden(Verzeichnis(stand="offen")), 503, "anmeldedienst")
        self.assertEqual(self.gotrue.anfragen, [])

    def test_https_ziel_nur_zum_host_des_stacks(self):
        with mock.patch.dict(os.environ, {"WAMO_GOTRUE_INTERN_URL": "https://gotrue.intern:8443",
                                          "SUPABASE_URL": "https://GoTrue.intern:55443"}):
            self.assertEqual(self.senden(Verzeichnis(stand="offen")).status_code, 200)
        self.assertEqual(str(self.gotrue.anfragen[0].url), "https://gotrue.intern:8443/auth/v1/user")

    def test_haengender_anmeldedienst_ist_502_nach_dem_gesamtlimit(self):
        class Haengt:
            def __init__(self):
                self.anfragen: list[httpx.Request] = []

            async def __call__(self, request):
                self.anfragen.append(request)
                await asyncio.sleep(30)

        self.gotrue = Haengt()
        with mock.patch.object(erstanmeldung_api, "GOTRUE_ZEIT_SECS", 0.2):
            self.fehler(self.senden(Verzeichnis(stand="offen")), 502, "anmeldedienst")
        self.assertEqual(len(self.gotrue.anfragen), 1)

    def test_satz_nennt_die_grenzen(self):
        r = self.senden(Verzeichnis(stand="offen"), {"passwort": "kurz"})
        self.assertIn("12 Zeichen", r.json()["detail"])
        self.assertIn("72 Bytes", r.json()["detail"])


# ---------- SessionGuard: Ende nach zuruecksetzen ----------
class GuardTests(unittest.IsolatedAsyncioTestCase):
    def guard(self, v: Verzeichnis, identity: Identity | None = None) -> bot.SessionGuard:
        ident = identity or Identity(USER, "Erika Muster", "mitglied", "du", anmeldung=1.0)
        return bot.SessionGuard(ident, v, interval=60, max_secs=120 * 60, wanduhr=lambda: 2.0)

    async def test_keine_und_erledigt_laufen_weiter(self):
        for stand in ("keine", "erledigt"):
            with self.subTest(stand=stand):
                v = Verzeichnis(stand=stand)
                self.assertIsNone(await self.guard(v).check())
                self.assertEqual(v.stand_calls, 1)

    async def test_zuruecksetzen_beendet_die_sitzung_und_verlangt_neue_anmeldung(self):
        v = Verzeichnis(stand="erledigt")
        g = self.guard(v)
        self.assertIsNone(await g.check())
        v.stand = "offen"  # der Admin hat zuruecksetzen ausgeführt
        self.assertEqual(await g.check(), SATZ_OFFEN)
        self.assertTrue(g.neu_anmelden)

    async def test_abgelaufen_beendet_die_sitzung(self):
        g = self.guard(Verzeichnis(stand="abgelaufen"))
        self.assertEqual(await g.check(), SATZ_ABGELAUFEN)
        self.assertTrue(g.neu_anmelden)

    async def test_fehler_beim_stand_werden_wie_beim_profil_toleriert(self):
        for fehler in (ErstanmeldungFehlt("UndefinedFunctionError"), DatabaseUnavailable("weg"), RuntimeError("x")):
            with self.subTest(fehler=type(fehler).__name__):
                g = self.guard(Verzeichnis(stand_fehler=fehler))
                self.assertIsNone(await g.check())
                self.assertIsNone(await g.check())
                self.assertIn("nicht mehr prüfen", await g.check())

    async def test_unbekannter_stand_zaehlt_als_fehler(self):
        g = self.guard(Verzeichnis(stand="vielleicht"))
        self.assertIsNone(await g.check())
        self.assertIsNone(await g.check())
        self.assertIn("nicht mehr prüfen", await g.check())

    async def test_ein_guter_lauf_setzt_die_fehler_zurueck(self):
        v = Verzeichnis(stand_fehler=DatabaseUnavailable("weg"))
        g = self.guard(v)
        await g.check()
        await g.check()
        v.stand_fehler = None
        self.assertIsNone(await g.check())
        v.stand_fehler = DatabaseUnavailable("weg")
        self.assertIsNone(await g.check())
        self.assertIsNone(await g.check())

    async def test_laborsitzung_fragt_den_stand_nie_ab(self):
        v = Verzeichnis(laborprofil(), stand="offen", stand_fehler=ErstanmeldungFehlt("UndefinedFunctionError"))
        ident = Identity(USER, "Gast", "mitglied", "du", anmeldung=1.0, labor_art="platz", labor_platz=3, labor_aktiv=True)
        self.assertIsNone(await self.guard(v, ident).check())
        self.assertEqual(v.stand_calls, 0)

    async def test_inaktives_profil_endet_vor_dem_stand(self):
        v = Verzeichnis(profil(aktiv=False), stand="offen")
        self.assertIn("nicht mehr aktiv", await self.guard(v).check())
        self.assertEqual(v.stand_calls, 0)


if __name__ == "__main__":
    unittest.main()
