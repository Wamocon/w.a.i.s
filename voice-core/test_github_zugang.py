"""Tests des persönlichen GitHub-Zugangs (github_zugang.py, Plan C, C.3, C.4, C.7): Formen, Prüfung bei GitHub (401, Typ, Weiterleitung,
Größe), Rechte im strengen Standard und mit Ausnahmen je Person, Ablauf, Drosselung, Labor, Zulassung, Schalter, Löschen, Übergabe an den
Dispatcher und dass der Wert nie in einer Antwort, einer Zeile von actions oder im Log steht. GitHub und Datenbank sind Attrappen."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from loguru import logger

import entwicklung_betrieb as eb
import github_zugang as gz
from auth_gate import Identity
from schluessel import GITHUB, Tresor, kek_erzeugen
from test_kernkanal_vertrag import SCOPE_FAELLE

PERSON = "3a1f0c2e-7b4d-4e8a-9c6f-0d2b4e6a8c10"
ADMIN = "5c2e4a6b-8d0f-4a1c-9e3b-7f5d1a3c5e70"
LABOR = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c60"
FREMD = "1b2c3d4e-5f60-4718-9a0b-c1d2e3f40516"
KLASSISCH = "ghp_" + "Kx7" * 12
FEIN = "github_pat_" + "Fg8_" * 20 + "Q9"
JETZT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
IN_90_TAGEN = JETZT + timedelta(days=90)


class FakeDb:
    """Die Anweisungen des Kerns an github_zugang, github_rechte, profiles und actions, im Speicher."""

    configured = True

    def __init__(self, ohne_tabelle: bool = False):
        self.zugang: dict[str, dict] = {}
        self.rechte: dict[str, dict] = {}
        self.profile: dict[str, dict] = {
            PERSON: {"display_name": "Person Eins", "rolle": "mitglied", "aktiv": True, "labor_art": None},
            ADMIN: {"display_name": "Admin Eins", "rolle": "admin", "aktiv": True, "labor_art": None},
            LABOR: {"display_name": "Platz 1", "rolle": "mitglied", "aktiv": False, "labor_art": "platz"},
        }
        self.aktionen: list[tuple] = []
        self.sql: list[str] = []
        self.ohne_tabelle = ohne_tabelle

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    def _pruefen(self, sql: str) -> None:
        self.sql.append(sql)
        if self.ohne_tabelle and "github_" in sql:
            raise asyncpg.UndefinedTableError("relation does not exist")

    async def fetchrow(self, sql: str, *args):
        self._pruefen(sql)
        uid = args[0]
        if sql.startswith("select g.art, g.token"):
            z = self.zugang.get(uid)
            return {**z, "labor_art": self.profile[uid]["labor_art"]} if z else None
        if sql.startswith("select art, token_ende"):
            return dict(self.zugang[uid]) if uid in self.zugang else None
        if sql.startswith("select scopes_ausnahmen from wamo_test.github_rechte"):
            return {"scopes_ausnahmen": list(self.rechte[uid]["scopes_ausnahmen"])} if uid in self.rechte else None
        if sql.startswith("select labor_art from wamo_test.profiles"):
            p = self.profile.get(uid)
            return {"labor_art": p["labor_art"]} if p else None
        raise AssertionError(sql)

    async def fetch(self, sql: str, *args):
        self._pruefen(sql)
        assert sql.startswith("select p.user_id::text as user_id")
        zeilen = []
        for uid, p in sorted(self.profile.items(), key=lambda e: e[1]["display_name"]):
            if p["labor_art"] is not None:
                continue
            g = self.zugang.get(uid, {})
            zeilen.append({"user_id": uid, "display_name": p["display_name"], "rolle": p["rolle"], "aktiv": p["aktiv"],
                           "scopes_ausnahmen": list(self.rechte.get(uid, {}).get("scopes_ausnahmen", [])), "art": g.get("art"),
                           "login": g.get("login"), "ablauf": g.get("ablauf")})
        return zeilen

    async def execute(self, sql: str, *args):
        self._pruefen(sql)
        if sql.startswith("insert into wamo_test.actions"):
            self.aktionen.append(args)
            return "INSERT 0 1"
        uid = args[0]
        if sql.startswith("insert into wamo_test.github_zugang"):
            if self.profile[uid]["labor_art"] is not None:
                raise asyncpg.InsufficientPrivilegeError("github_zugang: nur für Profile ohne labor_art")
            alt = self.zugang.get(uid, {})
            self.zugang[uid] = {"art": args[1], "token": args[2], "token_ende": args[3], "login": args[4], "konto_id": args[5],
                                "scopes": list(args[6]), "ablauf": args[7], "geprueft_at": JETZT,
                                "angelegt_at": JETZT if alt.get("token") != args[2] else alt["angelegt_at"]}
            return "INSERT 0 1"
        if sql.startswith("update wamo_test.github_zugang"):
            self.zugang[uid].update(login=args[1], konto_id=args[2], scopes=list(args[3]), ablauf=args[4], geprueft_at=JETZT)
            return "UPDATE 1"
        if sql.startswith("delete from wamo_test.github_zugang"):
            return f"DELETE {1 if self.zugang.pop(uid, None) else 0}"
        if sql.startswith("insert into wamo_test.github_rechte"):
            admin = self.profile.get(args[2]) or {}
            if admin.get("rolle") != "admin" or self.profile[uid]["labor_art"] is not None:
                raise asyncpg.InsufficientPrivilegeError("github_rechte: ändern nur durch einen aktiven Admin")
            self.rechte[uid] = {"scopes_ausnahmen": list(args[1]), "geaendert_von": args[2]}
            return "INSERT 0 1"
        raise AssertionError(sql)


def _pruefer(art: str = gz.ART_KLASSISCH, scopes=("repo",), ablauf=IN_90_TAGEN, login="person-eins", konto=4711,
             fehler: str | None = None, gesehen: list | None = None):
    async def pruefen(token: str) -> gz.Pruefung:
        if gesehen is not None:
            gesehen.append(token)
        if fehler:
            raise gz.ZugangFehler(fehler)
        return gz.Pruefung(art, login, konto, tuple(scopes) if art == gz.ART_KLASSISCH else (), ablauf)

    return pruefen


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture
def tresor():
    return Tresor(base64.urlsafe_b64decode(kek_erzeugen()))


@pytest.fixture(autouse=True)
def _frisch(monkeypatch):
    gz._versuche.clear()
    gz._rechte_versuche.clear()
    monkeypatch.setenv(gz.ENV_SCHALTER, "an")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_PROFILE", f"{PERSON},{ADMIN}")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_MITGLIEDER", "an")


@pytest.fixture
def log():
    zeilen: list[str] = []
    senke = logger.add(lambda m: zeilen.append(str(m)), level="DEBUG")
    yield zeilen
    logger.remove(senke)


def _identitaet(uid: str = PERSON, rolle: str = "mitglied", labor_art: str | None = None) -> Identity:
    return Identity(user_id=uid, name="Person", rolle=rolle, anrede="du", anmeldung=1.0, labor_art=labor_art,
                    labor_platz=1 if labor_art == "platz" else None)


async def _nachricht(identity, data, db, tresor, pruefen=None) -> dict:
    antworten: list[dict] = []

    async def senden(n: dict) -> None:
        antworten.append(n)

    await gz.github_zugang_nachricht(identity, data, senden, db=db, tresor=tresor, pruefen=pruefen or _pruefer())
    assert len(antworten) == 1
    return antworten[0]


def _ohne_token(*werte: object) -> None:
    for wert in werte:
        text = json.dumps(wert, default=str) if not isinstance(wert, str) else wert
        for token in (KLASSISCH, FEIN):
            assert token not in text
            assert token[4:20] not in text and token[-12:] not in text


# ---------- Formen ----------
@pytest.mark.parametrize("token, art", [(KLASSISCH, "klassisch"), (FEIN, "fein"), (f"  {KLASSISCH}\n", "klassisch")])
def test_formen_klassisch_und_fein(token, art):
    assert gz.art_von(token) == art


@pytest.mark.parametrize("token", ["gho_" + "a" * 36, "ghu_" + "b" * 36, "ghs_" + "c" * 36, "ghr_" + "d" * 36])
def test_app_und_oauth_tokens_mit_eigenem_satz(token):
    with pytest.raises(gz.ZugangFehler, match="kein persönliches Zugriffstoken") as info:
        gz.art_von(token)
    assert token not in str(info.value)


@pytest.mark.parametrize("token", ["", None, 42, "ghp_kurz", KLASSISCH + "x", "github_pat_" + "a" * 81, "sk-ant-api03-xyz", "ghp_" + "ä" * 36])
def test_fremde_formen(token):
    with pytest.raises(gz.ZugangFehler, match="kein GitHub-Token"):
        gz.art_von(token)


# ---------- Rechte ----------
def test_rechte_strenger_standard():
    assert gz.scopes_problem(("repo",)) is None
    assert gz.scopes_problem(("public_repo", "read:org", "notifications")) is None
    assert "repo" in gz.scopes_problem(("read:org",))
    for scope in ("workflow", "gist", "write:org", "write:packages", "read:packages", "delete:packages", "user",
                  "user:email", "admin:org", "admin:repo_hook", "admin:neu_erfunden", "codespace", "codespace:secrets",
                  "manage_runners:org", "manage_billing:enterprise", "read:enterprise", "write:public_key", "ganz_neu"):
        assert scope in (gz.scopes_problem(("repo", scope)) or ""), scope
    assert "nicht kennt" in gz.scopes_problem(("repo", "ganz_neu"))
    assert "eine unbekannte Angabe" in gz.scopes_problem(("repo", "Repo"))  # Werte von GitHub nur geprüft im Satz
    assert gz.scopes_problem(("repo", "read:user", "notifications", "project")) is None


@pytest.mark.parametrize("scope", gz.SCOPES_NIE)
def test_nie_erlaubt_auch_nicht_mit_ausnahme(scope):
    assert "nie erlaubt" in gz.scopes_problem(("repo", scope), (scope, *gz.SCOPES_AUSNAHMEN))
    with pytest.raises(gz.ZugangFehler, match="nie erlaubt"):
        gz.ausnahmen_pruefen([scope])


def test_ausnahmen_je_person():
    assert gz.scopes_problem(("repo", "workflow", "gist"), ("workflow",)) is not None
    assert gz.scopes_problem(("repo", "workflow", "gist"), ("workflow", "gist")) is None
    # nur Ausnahmen aus der festen Liste wirken; ein neues admin:-Recht bleibt gesperrt
    assert gz.scopes_problem(("repo", "admin:neu_erfunden"), ("admin:neu_erfunden",)) is not None
    assert gz.ausnahmen_normal(["workflow", "gist", "gist", "delete_repo", 3, "unbekannt", "read:org"]) == ("gist", "workflow")
    assert gz.ausnahmen_normal("workflow") == ()
    assert set(gz.SCOPES_AUSNAHMEN).isdisjoint(gz.SCOPES_NIE)
    assert all(gz.standard_abgelehnt(s) for s in (*gz.SCOPES_AUSNAHMEN, *gz.SCOPES_NIE, "ganz_neu"))
    assert not any(gz.standard_abgelehnt(s) for s in gz.SCOPES_UNBEDENKLICH)


@pytest.mark.parametrize("scopes, ausnahmen, erwartet", SCOPE_FAELLE)
def test_regel_wie_die_schnittstelle(scopes, ausnahmen, erwartet):
    """C.2.8: dieselbe Entscheidung wie token_rechte im Dispatcher (Wertetabelle aus Paket S)."""
    assert (gz.scopes_problem(scopes, ausnahmen) is None) == (erwartet is None)


@pytest.mark.parametrize("kopf, erwartet", [("repo", ("repo",)), ("repo, gist", ("repo", "gist")), (" repo ,, read:org ", ("repo", "read:org")),
                                            ("", ()), (" , ", ())])
def test_kopfzeile_wie_die_schnittstelle(kopf, erwartet):
    assert gz.scopes_lesen(kopf) == erwartet


def test_konstanten_aus_der_schnittstelle():
    assert gz.ENV_SCHALTER == eb.ENV_GITHUB == "WAMO_ENTWICKLUNG_GITHUB"
    assert gz.ABLAUF_MAX_TAGE == eb.GITHUB_ABLAUF_MAX_TAGE and gz.MAX_SCOPES == eb.SCOPES_MAX
    assert {a: m.pattern for a, m in gz._FORMEN.items()} == dict(eb.GITHUB_TOKEN_FORMEN)
    assert gz.SCOPES_PFLICHT == eb.SCOPES_PFLICHT_EINER and gz.SCOPES_UNBEDENKLICH == eb.SCOPES_UNBEDENKLICH


@pytest.mark.parametrize("werte", ["workflow", [1], ["unbekannt"], ["repo"], ["read:org"], ["gist", "gist"], ["workflow"] * 31])
def test_ausnahmen_pruefen_lehnt_fremdes_ab(werte):
    with pytest.raises(gz.ZugangFehler):
        gz.ausnahmen_pruefen(werte)


def test_scopes_lesen():
    assert gz.scopes_lesen("repo, workflow,  read:org") == ("repo", "workflow", "read:org")
    assert gz.scopes_lesen("Repo") == ("Repo",)  # lesen ja, erlaubt nein (scopes_problem)
    with pytest.raises(gz.ZugangFehler, match="nennt die Rechte"):
        gz.scopes_lesen(None)


# ---------- Ablauf ----------
def test_ablauf_lesen_und_regeln():
    assert gz.ablauf_lesen("2026-12-31 23:59:59 UTC") == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert gz.ablauf_lesen("2026-12-31 23:59:59 +0100").utcoffset() == timedelta(hours=1)
    assert gz.ablauf_lesen(None) is None and gz.ablauf_lesen("morgen") is None
    assert gz.ablauf_lesen("2026-12-31 23:59:59 CET") is None  # nur UTC als Name, sonst ein Versatz
    assert "kein Ablaufdatum" in gz.ablauf_problem(None, JETZT)
    assert "abgelaufen" in gz.ablauf_problem(JETZT - timedelta(seconds=1), JETZT)
    assert gz.ablauf_problem(JETZT + timedelta(days=366, hours=23), JETZT) is None  # Tagesende in einer anderen Zeitzone
    assert "366" in gz.ablauf_problem(JETZT + timedelta(days=368), JETZT)


# ---------- Prüfung bei GitHub (HTTP) ----------
def _transport(status=200, body=None, kopf=None, gesehen: list | None = None):
    def antwort(anfrage: httpx.Request) -> httpx.Response:
        if gesehen is not None:
            gesehen.append(anfrage)
        inhalt = json.dumps(body if body is not None else {"login": "person-eins", "id": 4711, "type": "User"}).encode()
        return httpx.Response(status, content=inhalt, headers=kopf if kopf is not None else {
            "X-OAuth-Scopes": "repo", "GitHub-Authentication-Token-Expiration": "2027-01-31 10:00:00 UTC"})

    return httpx.MockTransport(antwort)


async def test_pruefung_bei_github_klassisch():
    gesehen: list[httpx.Request] = []
    p = await gz.bei_github_pruefen(KLASSISCH, transport=_transport(gesehen=gesehen))
    assert p == gz.Pruefung("klassisch", "person-eins", 4711, ("repo",), datetime(2027, 1, 31, 10, tzinfo=UTC))
    assert str(gesehen[0].url) == "https://api.github.com/user" and gesehen[0].method == "GET"
    assert gesehen[0].headers["authorization"] == f"Bearer {KLASSISCH}"
    assert KLASSISCH not in str(gesehen[0].url)


async def test_pruefung_fein_ignoriert_scopes():
    p = await gz.bei_github_pruefen(FEIN, transport=_transport(kopf={"X-OAuth-Scopes": "admin:org",
                                                                     "GitHub-Authentication-Token-Expiration": "2027-01-31 10:00:00 UTC"}))
    assert p.art == "fein" and p.scopes == ()


@pytest.mark.parametrize("status, body, satz", [
    (401, None, "401"),
    (403, None, "403"),
    (302, None, "Weiterleitung"),
    (500, None, "HTTP 500"),
    (200, {"login": "org-konto", "id": 5, "type": "Organization"}, "Personenkonto"),
    (200, {"login": "-falsch", "id": 5, "type": "User"}, "unbekannten Form"),
    (200, {"login": "gut", "id": True, "type": "User"}, "unbekannten Form"),
    (200, {"login": "gut", "id": 0, "type": "User"}, "unbekannten Form"),
    (200, [1, 2], "Personenkonto"),
])
async def test_pruefung_fehlerfaelle(status, body, satz):
    with pytest.raises(gz.ZugangFehler, match=satz) as info:
        await gz.bei_github_pruefen(KLASSISCH, transport=_transport(status, body))
    _ohne_token(str(info.value))


async def test_pruefung_klassisch_ohne_scopes_kopf_und_zu_lange_antwort():
    with pytest.raises(gz.ZugangFehler, match="nennt die Rechte"):
        await gz.bei_github_pruefen(KLASSISCH, transport=_transport(kopf={}))

    def riesig(_anfrage):
        return httpx.Response(200, content=b"x" * (gz.ANTWORT_MAX_BYTES + 10))

    with pytest.raises(gz.ZugangFehler, match="zu lang"):
        await gz.bei_github_pruefen(KLASSISCH, transport=httpx.MockTransport(riesig))


async def test_pruefung_zeitlimit_und_netz():
    def zeit(_a):
        raise httpx.ReadTimeout("zu langsam")

    def netz(_a):
        raise httpx.ConnectError(f"kaputt {KLASSISCH}")

    with pytest.raises(gz.ZugangFehler, match="nicht rechtzeitig"):
        await gz.bei_github_pruefen(KLASSISCH, transport=httpx.MockTransport(zeit))
    with pytest.raises(gz.ZugangFehler, match="nicht erreichbar") as info:
        await gz.bei_github_pruefen(KLASSISCH, transport=httpx.MockTransport(netz))
    _ohne_token(str(info.value))


async def test_pruefung_folgt_keiner_weiterleitung():
    gesehen: list[httpx.Request] = []

    def weiter(anfrage):
        gesehen.append(anfrage)
        return httpx.Response(301, headers={"Location": "https://fremd.example/user"})

    with pytest.raises(gz.ZugangFehler, match="Weiterleitung"):
        await gz.bei_github_pruefen(KLASSISCH, transport=httpx.MockTransport(weiter))
    assert len(gesehen) == 1


# ---------- Speichern ----------
async def test_speichern_verschluesselt_und_ohne_wert_in_antwort_log_und_actions(db, tresor, log):
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    assert (n["type"], n["aktion"], n["hinterlegt"], n["art"], n["login"], n["ende"], n["bereit"]) == (
        "github_zugang", "speichern", True, "klassisch", "person-eins", KLASSISCH[-4:], True)
    assert n["scopes"] == ["repo"] and n["ablauf"] == IN_90_TAGEN.date().isoformat() and "fehler" not in n
    gespeichert = db.zugang[PERSON]["token"]
    assert KLASSISCH.encode() not in gespeichert and tresor.entschluesseln(PERSON, gespeichert, GITHUB) == KLASSISCH
    assert db.aktionen and db.aktionen[0][1] == gz.WERKZEUG
    assert json.loads(db.aktionen[0][2]) == {"aktion": "speichern", "art": "klassisch", "login": "person-eins",
                                             "ablauf": IN_90_TAGEN.date().isoformat()}
    _ohne_token(n, db.aktionen, "\n".join(log), db.sql)


async def test_speichern_fein_granular_mit_hinweis(db, tresor):
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": FEIN}, db, tresor, _pruefer(art="fein"))
    assert n["art"] == "fein" and n["scopes"] == [] and "Contents" in n["hinweis_fein"]
    assert db.zugang[PERSON]["scopes"] == []


@pytest.mark.parametrize("pruefer, satz", [
    (_pruefer(fehler="GitHub lehnt das Token ab (401): Es ist ungültig, abgelaufen oder widerrufen."), "401"),
    (_pruefer(scopes=("repo", "workflow")), "workflow"),
    (_pruefer(scopes=("repo", "delete_repo")), "nie erlaubt"),
    (_pruefer(scopes=("read:org",)), "braucht das Recht repo"),
    (_pruefer(ablauf=None), "kein Ablaufdatum"),
    (_pruefer(ablauf=datetime.now(UTC) + timedelta(days=400)), "366"),
    (_pruefer(ablauf=datetime.now(UTC) - timedelta(days=1)), "abgelaufen"),
])
async def test_speichern_abgelehnt_ohne_zeile(db, tresor, pruefer, satz, log):
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor, pruefer)
    assert satz in n["fehler"] and n["hinterlegt"] is False
    assert not db.zugang and not db.aktionen
    _ohne_token(n, "\n".join(log))


async def test_ausnahme_des_admins_erlaubt_das_recht(db, tresor):
    db.rechte[PERSON] = {"scopes_ausnahmen": ["workflow"], "geaendert_von": ADMIN}
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor,
                         _pruefer(scopes=("repo", "workflow")))
    assert n["hinterlegt"] is True and n["bereit"] is True and n["scopes_ausnahmen"] == ["workflow"]


async def test_form_falsch_ohne_versuch_bei_github(db, tresor):
    gesehen: list = []
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": "gho_" + "a" * 36}, db, tresor, _pruefer(gesehen=gesehen))
    assert "kein persönliches Zugriffstoken" in n["fehler"] and gesehen == []


async def test_drosselung_fuenf_versuche_je_zehn_minuten(db, tresor):
    for _ in range(gz.VERSUCHE_JE_FENSTER):
        n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor, _pruefer(fehler="nein"))
        assert n["fehler"] == "nein"
    gesehen: list = []
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor, _pruefer(gesehen=gesehen))
    assert "Zu viele Versuche" in n["fehler"] and gesehen == []
    assert gz._versuch_erlaubt(PERSON, jetzt=10**9)  # nach dem Fenster wieder


async def test_labor_bekommt_nur_einen_satz_ohne_datenbank(db, tresor):
    n = await _nachricht(_identitaet(LABOR, labor_art="platz"), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    assert n["fehler"] == gz.SATZ_LABOR and n["verfuegbar"] is False and db.sql == []


async def test_nicht_zugelassen_oder_schalter_aus_aber_loeschen_geht(db, tresor, monkeypatch):
    db.zugang[PERSON] = {"art": "klassisch", "token": b"x" * 50, "token_ende": "abcd", "login": "p", "konto_id": 1, "scopes": ["repo"],
                         "ablauf": IN_90_TAGEN, "geprueft_at": JETZT, "angelegt_at": JETZT}
    monkeypatch.setenv("WAMO_ENTWICKLUNG_MITGLIEDER", "aus")
    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    assert n["fehler"] == gz.SATZ_NICHT_ZUGELASSEN and n["verfuegbar"] is False and n["bereit"] is False
    monkeypatch.setenv("WAMO_ENTWICKLUNG_MITGLIEDER", "an")
    monkeypatch.setenv(gz.ENV_SCHALTER, "aus")
    n = await _nachricht(_identitaet(), {"aktion": "pruefen"}, db, tresor)
    assert n["fehler"] == gz.SATZ_SCHALTER_AUS
    n = await _nachricht(_identitaet(), {"aktion": "loeschen"}, db, tresor)
    assert n["hinterlegt"] is False and "fehler" not in n and "widerrufen" in n["ok"] and PERSON not in db.zugang
    assert json.loads(db.aktionen[-1][2]) == {"aktion": "loeschen"}


async def test_admin_ohne_profil_in_der_liste_ist_nicht_zugelassen(db, tresor, monkeypatch):
    monkeypatch.setenv("WAMO_ENTWICKLUNG_PROFILE", PERSON)
    n = await _nachricht(_identitaet(ADMIN, "admin"), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    assert n["fehler"] == gz.SATZ_NICHT_ZUGELASSEN


async def test_stand_ohne_tabelle_mit_klarem_satz(tresor):
    n = await _nachricht(_identitaet(), {"aktion": "stand"}, FakeDb(ohne_tabelle=True), tresor)
    assert n["verfuegbar"] is False and "0027" in n["grund"]


async def test_unbekannte_aktion_ist_stand_und_unerwarteter_fehler_ohne_text(db, tresor, log):
    n = await _nachricht(_identitaet(), {"aktion": "ausgeben"}, db, tresor)
    assert n["aktion"] == "stand" and n["hinterlegt"] is False

    async def kaputt(_token):
        raise RuntimeError(f"geheim {KLASSISCH}")

    n = await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor, kaputt)
    assert n["fehler"] == "Unerwarteter Fehler, bitte später noch einmal."
    _ohne_token(n, "\n".join(log))


# ---------- Prüfen und Stand ----------
async def test_erneut_pruefen_schreibt_angaben_neu_und_meldet_neue_rechte(db, tresor):
    await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    gesehen: list = []
    n = await _nachricht(_identitaet(), {"aktion": "pruefen"}, db, tresor, _pruefer(scopes=("repo", "gist"), gesehen=gesehen))
    assert gesehen == [KLASSISCH]  # frisch entschlüsselt
    assert "gist" in n["fehler"] and n["bereit"] is False and "gist" in n["problem"]
    assert db.zugang[PERSON]["scopes"] == ["repo", "gist"]
    assert json.loads(db.aktionen[-1][2])["ok"] is False
    n = await _nachricht(_identitaet(), {"aktion": "pruefen"}, db, tresor, _pruefer())
    assert n["ok"] == "Das Token ist gültig." and n["bereit"] is True


async def test_pruefen_ohne_hinterlegtes_token(db, tresor):
    n = await _nachricht(_identitaet(), {"aktion": "pruefen"}, db, tresor)
    assert "kein GitHub-Zugang hinterlegt" in n["fehler"]


async def test_stand_zeigt_problem_wenn_der_admin_die_ausnahme_zuruecknimmt(db, tresor):
    db.rechte[PERSON] = {"scopes_ausnahmen": ["workflow"], "geaendert_von": ADMIN}
    await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor, _pruefer(scopes=("repo", "workflow")))
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) == {"typ": "github", "wert": KLASSISCH}
    db.rechte[PERSON]["scopes_ausnahmen"] = []
    n = await _nachricht(_identitaet(), {"aktion": "stand"}, db, tresor)
    assert n["bereit"] is False and "workflow" in n["problem"]
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) is None


# ---------- Übergabe an den Dispatcher ----------
async def test_zugang_fuer_den_dispatcher(db, tresor, monkeypatch, log):
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) is None  # nichts hinterlegt
    await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) == {"typ": "github", "wert": KLASSISCH}
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor, jetzt=IN_90_TAGEN + timedelta(seconds=1)) is None
    assert await gz.github_zugang_fuer("keine-uuid", db=db, tresor=tresor) is None
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=Tresor(base64.urlsafe_b64decode(kek_erzeugen()))) is None
    monkeypatch.setenv(gz.ENV_SCHALTER, "aus")
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) is None
    monkeypatch.setenv(gz.ENV_SCHALTER, "vielleicht")
    assert await gz.github_zugang_fuer(PERSON, db=db, tresor=tresor) is None
    _ohne_token("\n".join(log))


async def test_zugang_fuer_ein_laborprofil_nie(db, tresor):
    db.zugang[LABOR] = {"art": "klassisch", "token": tresor.verschluesseln(LABOR, KLASSISCH, GITHUB), "token_ende": "abcd", "login": "p",
                        "konto_id": 1, "scopes": ["repo"], "ablauf": IN_90_TAGEN, "geprueft_at": JETZT, "angelegt_at": JETZT}
    assert await gz.github_zugang_fuer(LABOR, db=db, tresor=tresor) is None


async def test_chiffrat_eines_anderen_profils_wird_nicht_genutzt(db, tresor):
    await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    db.profile[FREMD] = {"display_name": "Fremd", "rolle": "mitglied", "aktiv": True, "labor_art": None}
    db.zugang[FREMD] = dict(db.zugang[PERSON])
    assert await gz.github_zugang_fuer(FREMD, db=db, tresor=tresor) is None


# ---------- Admin: Rechte je Person ----------
async def test_admin_setzt_rechte_mit_audit_ohne_namen(db, log):
    assert await gz.rechte_setzen(ADMIN, PERSON, ["workflow", "gist"], db=db) == ("gist", "workflow")
    assert db.rechte[PERSON] == {"scopes_ausnahmen": ["gist", "workflow"], "geaendert_von": ADMIN}
    zeile = db.aktionen[-1]
    assert zeile[0] == ADMIN and zeile[1] == gz.WERKZEUG_RECHTE
    assert json.loads(zeile[2]) == {"profil": PERSON.replace("-", "")[:8], "scopes_ausnahmen": ["gist", "workflow"], "vorher": []}
    assert "Person Eins" not in json.dumps(db.aktionen)
    # keine Änderung: kein Schreiben, keine Zeile
    anzahl = len(db.aktionen)
    assert await gz.rechte_setzen(ADMIN, PERSON, ["gist", "workflow"], db=db) == ("gist", "workflow")
    assert len(db.aktionen) == anzahl


async def test_admin_rechte_ablehnungen(db):
    with pytest.raises(gz.ZugangFehler, match="nie erlaubt"):
        await gz.rechte_setzen(ADMIN, PERSON, ["delete_repo"], db=db)
    with pytest.raises(gz.ZugangFehler, match="Labor"):
        await gz.rechte_setzen(ADMIN, LABOR, ["gist"], db=db)
    with pytest.raises(gz.ZugangFehler, match="gibt es nicht"):
        await gz.rechte_setzen(ADMIN, FREMD, ["gist"], db=db)
    with pytest.raises(gz.ZugangFehler, match="ungültig"):
        await gz.rechte_setzen(ADMIN, "nicht-uuid", ["gist"], db=db)
    with pytest.raises(gz.ZugangFehler, match="nur aktive Admins"):
        await gz.rechte_setzen(PERSON, ADMIN, ["gist"], db=db)  # die Datenbank lehnt einen Nicht-Admin ab
    assert not db.rechte


async def test_admin_rechte_drosselung(db):
    werte = (["gist"], ["workflow"])
    for i in range(gz.RECHTE_JE_FENSTER):
        await gz.rechte_setzen(ADMIN, PERSON, werte[i % 2], db=db)
    with pytest.raises(gz.ZugangFehler, match="Zu viele"):
        await gz.rechte_setzen(ADMIN, PERSON, werte[gz.RECHTE_JE_FENSTER % 2], db=db)


async def test_admin_liste_ohne_labor_und_ohne_wert(db, tresor):
    await _nachricht(_identitaet(), {"aktion": "speichern", "token": KLASSISCH}, db, tresor)
    await gz.rechte_setzen(ADMIN, PERSON, ["gist"], db=db)
    liste = [p.daten() for p in await gz.rechte_liste(db=db)]
    assert [p["user_id"] for p in liste] == [ADMIN, PERSON]
    person = liste[1]
    assert person == {"user_id": PERSON, "name": "Person Eins", "rolle": "mitglied", "aktiv": True, "scopes_ausnahmen": ["gist"],
                      "hinterlegt": True, "art": "klassisch", "login": "person-eins", "ablauf": IN_90_TAGEN.date().isoformat()}
    _ohne_token(liste)


def test_anweisungen_nennen_immer_das_profil():
    for vorlage in (gz._ZEILE, gz._TOKEN, gz._GEPRUEFT, gz._LOESCHEN, gz._RECHTE, gz._ZIEL):
        assert "user_id = $1::uuid" in vorlage, vorlage
    assert gz._SPEICHERN.startswith("insert into {g} (user_id,") and gz._RECHTE_SETZEN.startswith("insert into {r} (user_id,")
    assert "where p.labor_art is null" in gz._RECHTE_LISTE and "token" not in gz._RECHTE_LISTE
    assert "token" not in gz._ZEILE.replace("token_ende", "")


def test_die_oberflaeche_beschriftet_jede_ausnahme():
    """ui/src/lib/githubZugang.ts: RECHTE_TEXTE nennt jeden Scope aus SCOPES_AUSNAHMEN (sonst stünde er unter "Weitere")."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parent.parent / "ui" / "src" / "lib" / "githubZugang.ts").read_text(encoding="utf-8")
    block = quelle.split("export const RECHTE_TEXTE", 1)[1].split("};", 1)[0]
    for scope in gz.SCOPES_AUSNAHMEN:
        assert re.search(rf'^\s+(?:"{re.escape(scope)}"|{re.escape(scope)}): \{{', block, re.M), scope
    for scope in gz.SCOPES_NIE:
        assert f'"{scope}"' not in block and f"\n  {scope}:" not in block, scope
