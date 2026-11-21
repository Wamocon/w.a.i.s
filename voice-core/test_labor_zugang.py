"""Tests des Claude-Zugangs des Testlabors (labor_zugang.py, Migration 0032): Reihenfolge für Laborprofile (gespeicherter Schlüssel, Schlüssel des
Servers, Hausmodelle), Zwischenspeicher von 30 Sekunden, Verschlüsselung mit fester Bindung, Setzen nur nach erfolgreicher Testanfrage, Entfernen,
Protokollzeile ohne Wert, und dass kein Schlüssel in Log, Antwort oder Protokoll landet. Datenbank und Anthropic sind Attrappen."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import anthropic
import asyncpg
import httpx
import pytest
from loguru import logger

import labor_zugang as lz
import modellzugang as mz
from schluessel import SCHLUESSEL, SchluesselFehler, Tresor, kek_erzeugen

ADMIN = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
GAST = "7d3e9c1a-2b4f-4e6a-8c0d-1f2a3b4c5d6e"
# Marker: ein Wert, der in keiner Antwort, keinem Log und keiner actions-Zeile vorkommen darf
MARKER = "MARKERgeheim0815"
SCHLUESSEL_NEU = f"sk-ant-api03-{MARKER}-0123456789abcdefghij-Zq77"
SCHLUESSEL_ALT = "sk-ant-api03-ALTalt-0123456789abcdefghij-Al99"
SERVER = "sk-ant-api03-SERVERserver-0123456789abcdefghij-Sv11"


class FakeDb:
    """Eine Zeile labor_zugang und die Protokollzeilen (actions); versteht genau die drei Anweisungen von labor_zugang.py."""

    configured = True

    def __init__(self):
        self.zeile: dict | None = None
        self.aktionen: list[tuple] = []  # (user_id, tool, params, reason)
        self.sql: list[str] = []
        self.lesen = 0
        self.fehler: Exception | None = None  # wird beim nächsten Lesen oder Schreiben geworfen

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    async def fetchrow(self, sql: str, *args):
        self.sql.append(sql)
        self.lesen += 1
        if self.fehler:
            raise self.fehler
        return dict(self.zeile) if self.zeile else None

    async def fetchval(self, sql: str, *args):
        self.sql.append(sql)
        if self.fehler:
            raise self.fehler
        if sql.startswith("with neu"):
            chiffre, workspace, ende, uid, tool, grund = args
            self.zeile = {"claude_schluessel": chiffre, "claude_workspace": workspace, "endet_auf": ende, "gesetzt_von": uid,
                          "gesetzt_am": SimpleNamespace(isoformat=lambda timespec="seconds": "2026-11-21T09:30:00+00:00"),
                          "geprueft_am": SimpleNamespace(isoformat=lambda timespec="seconds": "2026-11-21T09:30:00+00:00")}
            self.aktionen.append((uid, tool, {"endet_auf": ende}, grund))
            return 1
        if sql.startswith("with weg"):
            uid, tool, grund = args
            if self.zeile is None:
                return None
            ende, self.zeile = self.zeile["endet_auf"], None
            self.aktionen.append((uid, tool, {"endet_auf": ende}, grund))
            return 1
        raise AssertionError(f"unbekannte Anweisung: {sql}")


async def _ok(schluessel, workspace):
    return None


@pytest.fixture
def tresor():
    return Tresor(base64.urlsafe_b64decode(kek_erzeugen()))


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture
def log():
    zeilen: list[str] = []
    senke = logger.add(lambda m: zeilen.append(str(m)), level="DEBUG")
    yield zeilen
    logger.remove(senke)


@pytest.fixture
def uhr(monkeypatch):
    """Eine Uhr, die der Test vorstellt (nur für das Modul labor_zugang)."""
    jetzt = [1000.0]
    monkeypatch.setattr(lz, "time", SimpleNamespace(monotonic=lambda: jetzt[0]))
    return jetzt


def _gespeichert(db, tresor, schluessel=SCHLUESSEL_ALT, workspace=None):
    db.zeile = {"claude_schluessel": tresor.verschluesseln(lz.BINDUNG, schluessel, SCHLUESSEL), "claude_workspace": workspace,
                "endet_auf": schluessel[-4:], "gesetzt_am": None, "geprueft_am": None}


# --- Setzen -----------------------------------------------------------------------------------------------------------


async def test_setzen_speichert_nur_ein_chiffrat_und_protokolliert_ohne_wert(db, tresor):
    stand = await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor, testen=_ok)
    assert (stand.quelle, stand.endet_auf) == ("gespeichert", SCHLUESSEL_NEU[-4:])
    chiffre = db.zeile["claude_schluessel"]
    assert SCHLUESSEL_NEU.encode() not in chiffre and MARKER.encode() not in chiffre
    assert tresor.entschluesseln(lz.BINDUNG, chiffre, SCHLUESSEL) == SCHLUESSEL_NEU
    assert db.zeile["gesetzt_von"] == ADMIN
    assert db.aktionen == [(ADMIN, lz.WERKZEUG_SETZEN, {"endet_auf": SCHLUESSEL_NEU[-4:]}, lz.GRUND_SETZEN)]
    assert MARKER not in repr(db.aktionen) and MARKER not in repr(stand.daten())


async def test_das_chiffrat_ist_an_die_feste_kennung_gebunden(db, tresor):
    """Ein Chiffrat aus model_access (an ein Profil gebunden) lässt sich hier nicht einsetzen, und dieses nicht dort."""
    await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor, testen=_ok)
    with pytest.raises(SchluesselFehler):
        tresor.entschluesseln(ADMIN, db.zeile["claude_schluessel"], SCHLUESSEL)
    fremdes = tresor.verschluesseln(ADMIN, SCHLUESSEL_ALT, SCHLUESSEL)  # so liegt ein persönlicher Schlüssel in model_access
    db.zeile["claude_schluessel"] = fremdes
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None


async def test_workspace_wird_mitgespeichert_und_geprueft(db, tresor):
    stand = await lz.setzen(ADMIN, SCHLUESSEL_NEU, " wrkspc_Test123456 ", db=db, tresor=tresor, testen=_ok)
    assert stand.workspace == "wrkspc_Test123456"
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, "workspace", db=db, tresor=tresor, testen=_ok)
    assert e.value.code == "workspace_ungueltig" and e.value.status == 400


async def test_gespeichert_wird_nur_nach_erfolgreicher_testanfrage(db, tresor):
    async def abgelehnt(schluessel, workspace):
        raise lz.LaborZugangFehler("schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401).")

    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor, testen=abgelehnt)
    assert e.value.code == "schluessel_abgelehnt"
    assert db.zeile is None and db.aktionen == [] and not any("insert" in s for s in db.sql)


@pytest.mark.parametrize("roh", [None, "", "   ", 5, "kein-schluessel", "sk-ant-oat01-" + "x" * 40, "sk-ant-", ["sk-ant-api03-" + "x" * 30]])
async def test_format_wird_vor_der_testanfrage_geprueft(db, tresor, roh):
    aufgerufen = []

    async def test_(schluessel, workspace):
        aufgerufen.append(schluessel)

    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, roh, None, db=db, tresor=tresor, testen=test_)
    assert e.value.code == "schluessel_ungueltig" and aufgerufen == [] and db.zeile is None


async def test_ohne_hauptschluessel_gibt_es_nichts_zu_speichern(db, monkeypatch):
    monkeypatch.delenv("WAMO_SCHLUESSEL_KEK", raising=False)
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, testen=_ok)
    assert (e.value.code, e.value.status) == ("kein_hauptschluessel", 503) and db.zeile is None


@pytest.mark.parametrize("fehler, code", [
    (asyncpg.UndefinedTableError("relation wamo_test.labor_zugang does not exist"), "nicht_eingerichtet"),
    (asyncpg.InsufficientPrivilegeError("permission denied"), "nicht_eingerichtet"),
    (asyncpg.CheckViolationError("check"), "schluessel_ungueltig"),
    (asyncpg.PostgresError("irgendwas"), "datenbank"),
])
async def test_datenbankfehler_werden_zu_saetzen_ohne_meldung_der_datenbank(db, tresor, log, fehler, code):
    db.fehler = fehler
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor, testen=_ok)
    assert e.value.code == code and "relation" not in e.value.text and "permission" not in e.value.text
    assert MARKER not in "\n".join(log) + e.value.text


async def test_ungueltiges_profil_und_keine_datenbank(tresor):
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen("kein-uuid", SCHLUESSEL_NEU, None, db=FakeDb(), tresor=tresor, testen=_ok)
    assert e.value.status == 401
    ohne = FakeDb()
    ohne.configured = False
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=ohne, tresor=tresor, testen=_ok)
    assert e.value.code == "datenbank"


# --- Entfernen --------------------------------------------------------------------------------------------------------


async def test_entfernen_loescht_protokolliert_und_der_server_schluessel_gilt_wieder(db, tresor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor, testen=_ok)
    stand = await lz.entfernen(ADMIN, db=db, tresor=tresor)
    assert (stand.quelle, stand.endet_auf) == ("server", SERVER[-4:]) and db.zeile is None
    assert db.aktionen[-1] == (ADMIN, lz.WERKZEUG_ENTFERNEN, {"endet_auf": SCHLUESSEL_NEU[-4:]}, lz.GRUND_ENTFERNEN)
    anzahl = len(db.aktionen)
    await lz.entfernen(ADMIN, db=db, tresor=tresor)  # nichts mehr da: keine zweite Zeile
    assert len(db.aktionen) == anzahl


async def test_entfernen_leert_den_zwischenspeicher_sofort(db, tresor):
    _gespeichert(db, tresor)
    assert (await lz.schluessel_fuer_labor(db=db, tresor=tresor))[0] == SCHLUESSEL_ALT
    await lz.entfernen(ADMIN, db=db, tresor=tresor)
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None


# --- Stand ------------------------------------------------------------------------------------------------------------


async def test_stand_nennt_die_quelle_und_nie_den_schluessel(db, tresor, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert (await lz.stand(db=db, tresor=tresor)).quelle == "keiner"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    s = await lz.stand(db=db, tresor=tresor)
    assert (s.quelle, s.endet_auf) == ("server", SERVER[-4:]) and SERVER not in repr(s)
    _gespeichert(db, tresor, workspace="wrkspc_Test123456")
    s = await lz.stand(db=db, tresor=tresor)
    assert (s.quelle, s.endet_auf, s.workspace) == ("gespeichert", SCHLUESSEL_ALT[-4:], "wrkspc_Test123456")
    assert SCHLUESSEL_ALT not in repr(s) and SCHLUESSEL_ALT not in repr(s.daten())
    assert set(s.daten()) == {"quelle", "endet_auf", "workspace", "gesetzt_am", "geprueft_am", "hinweis"}


async def test_unlesbarer_gespeicherter_schluessel_zaehlt_nicht_und_hat_einen_hinweis(db, tresor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    _gespeichert(db, tresor)
    anderer = Tresor(base64.urlsafe_b64decode(kek_erzeugen()))
    s = await lz.stand(db=db, tresor=anderer)
    assert s.quelle == "server" and "nicht lesen" in (s.hinweis or "")


async def test_stand_ohne_datenbank_und_mit_defekter_datenbank(db, tresor):
    db.fehler = asyncpg.PostgresError("kaputt")
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.stand(db=db, tresor=tresor)
    assert (e.value.code, e.value.status) == ("datenbank", 503)


async def test_fehlt_die_tabelle_gilt_der_schluessel_des_servers(db, tresor, log):
    db.fehler = asyncpg.UndefinedTableError("fehlt")
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None
    assert any("0032" in z for z in log)


# --- Zwischenspeicher -------------------------------------------------------------------------------------------------


async def test_gelesen_wird_hoechstens_alle_30_sekunden(db, tresor, uhr):
    _gespeichert(db, tresor, workspace="wrkspc_Test123456")
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) == (SCHLUESSEL_ALT, "wrkspc_Test123456")
    for _ in range(5):
        uhr[0] += 5
        assert (await lz.schluessel_fuer_labor(db=db, tresor=tresor))[0] == SCHLUESSEL_ALT
    assert db.lesen == 1  # 25 Sekunden, nie je Sitzung
    _gespeichert(db, tresor, schluessel=SCHLUESSEL_NEU)
    uhr[0] += 6  # 31 Sekunden seit dem Lesen
    assert (await lz.schluessel_fuer_labor(db=db, tresor=tresor))[0] == SCHLUESSEL_NEU
    assert db.lesen == 2


async def test_gleichzeitige_sitzungen_teilen_sich_eine_abfrage(db, tresor):
    _gespeichert(db, tresor)
    antworten = await asyncio.gather(*(lz.schluessel_fuer_labor(db=db, tresor=tresor) for _ in range(20)))
    assert {a[0] for a in antworten} == {SCHLUESSEL_ALT} and db.lesen == 1


async def test_auch_kein_schluessel_wird_gemerkt(db, tresor):
    for _ in range(3):
        assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None
    assert db.lesen == 1


async def test_lesefehler_wirft_nie_und_gilt_nur_kurz(db, tresor, uhr, log):
    _gespeichert(db, tresor)
    db.fehler = asyncpg.PostgresError("weg")
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None
    uhr[0] += 2
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None and db.lesen == 1  # noch im kurzen Fehlerfenster
    db.fehler = None
    uhr[0] += 4  # 6 Sekunden: das Fehlerfenster (5 s) ist vorbei
    assert (await lz.schluessel_fuer_labor(db=db, tresor=tresor))[0] == SCHLUESSEL_ALT
    assert sum("nicht lesbar" in z for z in log) == 1  # einmal im Log, nicht bei jeder Sitzung


async def test_ohne_hauptschluessel_und_bei_beschaedigtem_chiffrat_gilt_der_server(db, tresor, monkeypatch, log):
    _gespeichert(db, tresor)
    monkeypatch.delenv("WAMO_SCHLUESSEL_KEK", raising=False)
    assert await lz.schluessel_fuer_labor(db=db) is None
    lz.cache_leeren()
    db.zeile["claude_schluessel"] = b"w1" + b"\x00" * 60
    assert await lz.schluessel_fuer_labor(db=db, tresor=tresor) is None
    assert SCHLUESSEL_ALT not in "\n".join(log)


async def test_ohne_datenbank_keine_abfrage(tresor):
    ohne = FakeDb()
    ohne.configured = False
    assert await lz.schluessel_fuer_labor(db=ohne, tresor=tresor) is None and ohne.lesen == 0


# --- Reihenfolge im Zugang der Sitzung ---------------------------------------------------------------------------------


def _profil(**werte) -> dict:
    basis = {"nur_haus": False, "claude_schluessel": None, "claude_schluessel_ende": None, "claude_workspace": None, "claude_modell": None,
             "claude_geprueft_at": None, "stt": "soniox", "tts": "soniox", "modell_modus": "automatisch", "claude_code_token": None,
             "claude_code_token_ende": None, "claude_code_token_at": None}
    return basis | werte


class ZugangsDb(FakeDb):
    """Zusätzlich die Tabelle model_access (eine Zeile je Profil) für zugang_laden."""

    def __init__(self):
        super().__init__()
        self.profile: dict[str, dict] = {}

    async def fetchrow(self, sql: str, *args):
        if "model_access" in sql:
            z = self.profile.get(args[0])
            return dict(z) if z is not None else None
        return await super().fetchrow(sql, *args)


@pytest.mark.parametrize("art", ["platz", "schaufenster"])
async def test_laborprofil_nimmt_zuerst_den_gespeicherten_schluessel(tresor, monkeypatch, art):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    d = ZugangsDb()
    d.profile[GAST] = _profil()
    _gespeichert(d, tresor, workspace="wrkspc_Test123456")
    z = await mz.zugang_laden(GAST, db=d, tresor=tresor, labor_art=art)
    assert (z.art, z.quelle, z.claude_schluessel, z.claude_workspace) == ("claude", "labor", SCHLUESSEL_ALT, "wrkspc_Test123456")
    assert z.claude_code is False and SCHLUESSEL_ALT not in repr(z)


async def test_ohne_gespeicherten_schluessel_gilt_der_des_servers(tresor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_Server1234")
    d = ZugangsDb()
    d.profile[GAST] = _profil()
    z = await mz.zugang_laden(GAST, db=d, tresor=tresor, labor_art="platz")
    assert (z.quelle, z.claude_schluessel, z.claude_workspace) == ("labor", SERVER, "wrkspc_Server1234")


async def test_ohne_beides_hausmodelle(tresor, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = ZugangsDb()
    d.profile[GAST] = _profil()
    z = await mz.zugang_laden(GAST, db=d, tresor=tresor, labor_art="platz")
    assert (z.art, z.quelle, z.claude_schluessel) == ("haus", "keiner", None)


async def test_ein_festgelegtes_laborprofil_bleibt_bei_hausmodellen(tresor):
    d = ZugangsDb()
    d.profile[GAST] = _profil(nur_haus=True)
    _gespeichert(d, tresor)
    z = await mz.zugang_laden(GAST, db=d, tresor=tresor, labor_art="platz")
    assert (z.art, z.quelle, z.claude_schluessel) == ("haus", "festgelegt", None)


async def test_jedes_andere_profil_bekommt_den_labor_schluessel_nie(tresor, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = ZugangsDb()
    d.profile[ADMIN] = _profil()
    _gespeichert(d, tresor)
    for art in (None, "unbekannt"):
        z = await mz.zugang_laden(ADMIN, db=d, tresor=tresor, labor_art=art)
        assert (z.art, z.quelle, z.claude_schluessel) == ("haus", "keiner", None), art
    assert d.lesen == 0  # für sie wird die Tabelle nicht einmal gelesen


async def test_der_labor_schluessel_gilt_nicht_fuer_die_zuordnung_des_kerns(tresor, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SERVER)
    monkeypatch.setenv(mz.ZUORDNUNG_ENV, ADMIN)
    d = ZugangsDb()
    d.profile[ADMIN] = _profil()
    _gespeichert(d, tresor)
    z = await mz.zugang_laden(ADMIN, db=d, tresor=tresor)
    assert (z.quelle, z.claude_schluessel) == ("zuordnung", SERVER)


# --- Testanfrage bei Anthropic -----------------------------------------------------------------------------------------


def _antwort(status: int, text: str = "x"):
    anfrage = httpx.Request("GET", "https://api.anthropic.test/v1/models")
    return httpx.Response(status, request=anfrage, json={"error": {"message": text}})


class FakeAnthropic:
    """Ersetzt anthropic.AsyncAnthropic: models.list wirft, was der Test vorgibt, und nichts geht ins Netz."""

    wirft: Exception | None = None
    zuletzt: dict = {}

    def __init__(self, **kw):
        FakeAnthropic.zuletzt = kw
        self.models = SimpleNamespace(list=self._list)

    async def _list(self, **kw):
        if FakeAnthropic.wirft:
            raise FakeAnthropic.wirft
        return SimpleNamespace(data=[])

    async def close(self):
        return None


@pytest.fixture
def anthropic_attrappe(monkeypatch):
    FakeAnthropic.wirft = None
    monkeypatch.setattr(lz.anthropic, "AsyncAnthropic", FakeAnthropic)
    return FakeAnthropic


async def test_testanfrage_ohne_wiederholen_und_mit_workspace(anthropic_attrappe):
    await lz.schluessel_pruefen(SCHLUESSEL_NEU, "wrkspc_Test123456")
    kw = anthropic_attrappe.zuletzt
    assert kw["max_retries"] == 0 and kw["api_key"] == SCHLUESSEL_NEU
    assert kw["default_headers"] == {"anthropic-workspace-id": "wrkspc_Test123456"}


@pytest.mark.parametrize("fehler, code, status, wort", [
    (anthropic.AuthenticationError("Marker " + SCHLUESSEL_NEU, response=_antwort(401), body=None), "schluessel_abgelehnt", 400, "401"),
    (anthropic.PermissionDeniedError("Marker " + SCHLUESSEL_NEU, response=_antwort(403), body=None), "schluessel_abgelehnt", 400, "403"),
    (anthropic.BadRequestError("workspace fehlt " + SCHLUESSEL_NEU, response=_antwort(400), body=None), "schluessel_abgelehnt", 400, "Workspace"),
    (anthropic.BadRequestError("sonst " + SCHLUESSEL_NEU, response=_antwort(400), body=None), "schluessel_abgelehnt", 400, "400"),
    (anthropic.APITimeoutError(request=httpx.Request("GET", "https://x.test")), "anthropic_nicht_erreichbar", 502, "rechtzeitig"),
    (anthropic.APIConnectionError(request=httpx.Request("GET", "https://x.test")), "anthropic_nicht_erreichbar", 502, "erreichbar"),
    (anthropic.InternalServerError("Marker " + SCHLUESSEL_NEU, response=_antwort(500), body=None), "anthropic_fehler", 502, "500"),
    (anthropic.APIError("Marker " + SCHLUESSEL_NEU, request=httpx.Request("GET", "https://x.test"), body=None), "anthropic_fehler", 502, "fehlgeschlagen"),
])
async def test_fehler_von_anthropic_werden_zu_saetzen_ohne_schluessel_und_ohne_kette(anthropic_attrappe, fehler, code, status, wort):
    anthropic_attrappe.wirft = fehler
    with pytest.raises(lz.LaborZugangFehler) as e:
        await lz.schluessel_pruefen(SCHLUESSEL_NEU, None)
    assert (e.value.code, e.value.status) == (code, status) and wort in e.value.text
    assert MARKER not in e.value.text and SCHLUESSEL_NEU not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__  # die Ausnahme der Bibliothek hängt nicht dran


# --- Der Schlüssel erscheint nirgends ----------------------------------------------------------------------------------


async def test_marker_in_keinem_log_keiner_antwort_und_keiner_protokollzeile(db, tresor, log, anthropic_attrappe):
    anthropic_attrappe.wirft = anthropic.AuthenticationError("Marker " + SCHLUESSEL_NEU, response=_antwort(401), body=None)
    with pytest.raises(lz.LaborZugangFehler):
        await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor)
    anthropic_attrappe.wirft = None
    stand = await lz.setzen(ADMIN, SCHLUESSEL_NEU, None, db=db, tresor=tresor)
    await lz.stand(db=db, tresor=tresor)
    assert (await lz.schluessel_fuer_labor(db=db, tresor=tresor))[0] == SCHLUESSEL_NEU
    await lz.entfernen(ADMIN, db=db, tresor=tresor)
    gesamt = "\n".join(log) + repr(stand) + repr(stand.daten()) + repr(db.aktionen) + "\n".join(db.sql)
    assert MARKER not in gesamt and SCHLUESSEL_NEU not in gesamt
