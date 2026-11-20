"""Datenbankschicht (pg.py) ohne Datenbank: Abfragen gegen eine Attrappe der asyncpg-Verbindung. Geprüft werden Schemaname, Parameter statt
Texteinsetzung, Fehlerabbildung und der Ablauf einer Transaktion. Gegen eine echte Datenbank prüft der Rauchtest am Server."""

from __future__ import annotations

import contextlib
import json
from datetime import date, datetime, time, timezone

import asyncpg
import pytest

from wamo_werkstatt import pg
from wamo_werkstatt.daten import DatenbankFehler, KonfliktFehler, PruefFehler
from wamo_werkstatt.konfig import DbZugang

ADMIN = "11111111-1111-4111-8111-111111111111"


class FakeConn:
    def __init__(self, **antworten):
        self.aufrufe: list[tuple] = []
        self.antworten = antworten
        self.fehler: Exception | None = None
        self.ereignisse: list[str] = []

    async def _lauf(self, art, sql, args):
        self.aufrufe.append((art, " ".join(sql.split()), args))
        if self.fehler is not None:
            raise self.fehler
        antwort = self.antworten.get(art, [] if art == "fetch" else "OK" if art == "execute" else None)
        return antwort(sql, args) if callable(antwort) else antwort

    async def fetch(self, sql, *args):
        return await self._lauf("fetch", sql, args)

    async def fetchrow(self, sql, *args):
        return await self._lauf("fetchrow", sql, args)

    async def fetchval(self, sql, *args):
        return await self._lauf("fetchval", sql, args)

    async def execute(self, sql, *args):
        return await self._lauf("execute", sql, args)

    def transaction(self):
        conn = self

        @contextlib.asynccontextmanager
        async def kontext():
            conn.ereignisse.append("begin")
            try:
                yield
            except BaseException:
                conn.ereignisse.append("rollback")
                raise
            conn.ereignisse.append("commit")

        return kontext()


def ops(conn: FakeConn | None = None, schema: str = "wamo_dev") -> tuple[pg._Ops, FakeConn]:
    conn = conn or FakeConn()
    return pg._Ops(pg._Sicher(conn), schema), conn


async def test_profil():
    o, c = ops(FakeConn(fetchrow={"rolle": "admin", "aktiv": True, "labor_art": None}))
    p = await o.profil(ADMIN)
    assert (p.user_id, p.rolle, p.aktiv, p.labor_art) == (ADMIN, "admin", True, None)
    art, sql, args = c.aufrufe[0]
    assert "from wamo_dev.profiles where user_id = $1::uuid" in sql and args == (ADMIN,)
    o, _ = ops(FakeConn(fetchrow=None))
    assert await o.profil(ADMIN) is None
    o, _ = ops(FakeConn(fetchrow={"rolle": "mitglied", "aktiv": None, "labor_art": "platz"}))
    assert (await o.profil(ADMIN)).aktiv is False


async def test_lesefunktionen_mit_parametern():
    o, c = ops(FakeConn(fetch=[{"tag": date(2026, 11, 20), "anzahl": 1}]))
    assert await o.sitzungen(7) == [{"tag": date(2026, 11, 20), "anzahl": 1}]
    await o.latenz(14)
    await o.aktionen(30)
    await o.labor_stand()
    sqls = [a[1] for a in c.aufrufe]
    assert sqls == ["select * from wamo_dev.werkstatt_sitzungen($1::int)", "select * from wamo_dev.werkstatt_latenz($1::int)",
                    "select * from wamo_dev.werkstatt_aktionen($1::int)", "select * from wamo_dev.werkstatt_labor_stand()"]
    assert [a[2] for a in c.aufrufe] == [(7,), (14,), (30,), ()]


async def test_termine():
    zeile = {"id": "t1", "tag": date(2026, 12, 5), "beginn": time(10), "ende": None, "einwilligung_version": 1, "status": "entwurf",
             "aufbewahrung_bis": date(2026, 12, 18)}
    daten = {k: zeile[k] for k in ("tag", "beginn", "ende", "einwilligung_version", "status", "aufbewahrung_bis")}
    o, c = ops(FakeConn(fetch=[zeile], fetchrow=zeile, fetchval=1))
    assert await o.termine() == [zeile] and await o.termin("t1") == zeile
    assert await o.termin_anlegen(daten, ADMIN) == zeile and await o.termin_aendern("t1", daten) == zeile and await o.termin_loeschen("t1") is True
    sqls = [a[1] for a in c.aufrufe]
    assert "from wamo_dev.labor_termine order by tag desc" in sqls[0]
    assert sqls[2].startswith("insert into wamo_dev.labor_termine (tag, beginn, ende, einwilligung_version, status, aufbewahrung_bis, erstellt_von) values")
    assert c.aufrufe[2][2] == (date(2026, 12, 5), time(10), None, 1, "entwurf", date(2026, 12, 18), ADMIN)
    assert sqls[3].startswith("update wamo_dev.labor_termine set") and c.aufrufe[3][2][0] == "t1"
    assert sqls[4].startswith("delete from wamo_dev.labor_termine where id = $1::uuid")
    o, _ = ops(FakeConn(fetchrow=None, fetchval=None))
    assert await o.termin("x") is None and await o.termin_aendern("x", daten) is None and await o.termin_loeschen("x") is False


async def test_plaetze_und_checkliste():
    o, c = ops(FakeConn(fetch=[{"platz": 1}], fetchrow={"nr": 5, "titel": "t"}))
    assert await o.plaetze("t1") == [{"platz": 1}]
    await o.plaetze_setzen("t1", [{"platz": 1, "zweck": "besucher", "kennung": "labor-01", "gast": None}, {"platz": 2, "zweck": "reserve", "kennung": None, "gast": "G"}])
    assert [a[0] for a in c.aufrufe] == ["fetch", "execute", "execute", "execute"]
    assert c.aufrufe[1][1] == "delete from wamo_dev.labor_plaetze where termin_id = $1::uuid"
    assert c.aufrufe[3][2] == ("t1", 2, "reserve", None, "G")
    assert await o.checkliste("t1") == [{"platz": 1}]
    assert (await o.checkliste_anlegen("t1", {"titel": "t", "quelle": None, "faellig": None}))["nr"] == 5
    assert (await o.checkliste_abhaken("t1", 5, True, ADMIN))["nr"] == 5
    assert "set erledigt_at = case when $3::boolean then now() else null end" in c.aufrufe[-1][1] and c.aufrufe[-1][2] == ("t1", 5, True, ADMIN)
    o, _ = ops(FakeConn(fetchrow=None))
    assert await o.checkliste_abhaken("t1", 5, True, ADMIN) is None


async def test_karten():
    zeile = {"id": "W1", "titel": "t"}
    daten = {"gruppe": "Wissen", "titel": "t", "aufgabe": "a", "erwartung": "e", "fehler": None, "lernziel": None, "wissen": "keine",
             "wissenstext": None, "werkzeuge": ["Jira"], "dauer_min": 3}
    o, c = ops(FakeConn(fetch=[zeile], fetchrow=zeile, fetchval=1))
    assert await o.karten() == [zeile] and await o.karten(sperren=True) == [zeile]
    assert not c.aufrufe[0][1].endswith("for update") and c.aufrufe[1][1].endswith("order by id for update")
    assert await o.karte("W1") == zeile and await o.karte_anlegen("W1", daten, ADMIN) == zeile and await o.karte_aendern("W1", daten, ADMIN) == zeile
    assert await o.karte_loeschen("W1") is True
    assert c.aufrufe[3][2] == ("W1", "Wissen", "t", "a", "e", None, None, "keine", None, ["Jira"], 3, ADMIN)
    assert "stand = 'entwurf'" in c.aufrufe[4][1] and c.aufrufe[4][2][-1] == ADMIN
    assert c.aufrufe[5][1].startswith("delete from wamo_dev.labor_karten where id = $1 and stand = 'entwurf'")
    o, _ = ops(FakeConn(fetchrow=None, fetchval=None))
    assert await o.karte("x") is None and await o.karte_aendern("x", daten, ADMIN) is None and await o.karte_loeschen("x") is False


async def test_zuordnung_versionen():
    o, c = ops(FakeConn(fetch=[{"platz": 1, "karte_id": "W1"}, {"platz": 1, "karte_id": "J1"}, {"platz": 2, "karte_id": "W1"}], fetchval=4))
    assert await o.zuordnung("t1") == {1: ["W1", "J1"], 2: ["W1"]}
    await o.zuordnung_setzen("t1", {1: ["W1", "J1"], 2: []})
    assert [a[0] for a in c.aufrufe[1:]] == ["execute"] * 3
    assert c.aufrufe[3][2] == ("t1", 1, "J1")
    assert await o.aktive_version() == 4
    await o.versionen(10)
    assert c.aufrufe[-1][2] == (10,) and "order by version desc limit $1" in c.aufrufe[-1][1]


async def test_freigabekarte_und_version():
    zeile = {"id": "k1", "admin": ADMIN, "aktion": "karten_veroeffentlichen", "ziel": json.dumps({"stand": "abc"}),
             "gilt_bis": datetime(2026, 11, 20, tzinfo=timezone.utc), "ausgefuehrt_at": None, "abgelaufen": False}
    o, c = ops(FakeConn(fetchrow=zeile, fetchval=3))
    karte = await o.freigabekarte_anlegen(ADMIN, "karten_veroeffentlichen", {"stand": "abc"}, 295)
    assert karte.ziel == {"stand": "abc"} and karte.abgelaufen is False and karte.ausgefuehrt is False
    sql, args = c.aufrufe[0][1], c.aufrufe[0][2]
    assert "now() + ($5::int * interval '1 second')" in sql and args[1:] == (ADMIN, "karten_veroeffentlichen", '{"stand":"abc"}', 295)
    assert len(args[0]) == 36  # die Kennung vergibt der Dienst
    gesperrt = await o.freigabekarte_sperren("k1")
    assert gesperrt.id == "k1" and c.aufrufe[1][1].endswith("where id = $1::uuid for update")
    c.antworten["fetchval"] = 1
    assert await o.freigabekarte_verbrauchen("k1") is True
    c.antworten["fetchval"] = 3
    assert (await o.version_anlegen(ADMIN, 2, 4200, [{"id": "W1", "titel": "Ä"}])) == 3
    assert c.aufrufe[3][1] == "update wamo_dev.labor_karten_versionen set aktiv = false where aktiv"
    assert c.aufrufe[4][2][3] == '[{"id":"W1","titel":"Ä"}]'
    o, _ = ops(FakeConn(fetchrow={**zeile, "ziel": {"x": 1}, "ausgefuehrt_at": datetime.now(timezone.utc), "abgelaufen": True}))
    verbraucht = await o.freigabekarte_sperren("k1")
    assert verbraucht.ausgefuehrt is True and verbraucht.abgelaufen is True and verbraucht.ziel == {"x": 1}
    o, _ = ops(FakeConn(fetchrow=None, fetchval=None))
    assert await o.freigabekarte_sperren("k1") is None and await o.freigabekarte_verbrauchen("k1") is False


async def test_entwuerfe_buchung_aufraeumen():
    o, c = ops(FakeConn(execute="UPDATE 3"))
    assert await o.entwuerfe_veroeffentlichen() == 3
    await o.aktion_buchen(ADMIN, "werkstatt_x", "critical", {"karte": "k"}, {"ok": True})
    sql, args = c.aufrufe[1][1], c.aufrufe[1][2]
    assert sql.startswith("insert into wamo_dev.actions (user_id, tool, params, risk, status, result, decided_at, finished_at)")
    assert "$4::text::wamo_dev.risk_class" in sql and "'done'::wamo_dev.action_status" in sql
    assert args == (ADMIN, "werkstatt_x", '{"karte":"k"}', "critical", '{"ok":true}')
    await o.aufraeumen()
    assert c.aufrufe[2][1] == "select wamo_dev.werkstatt_aufraeumen()"
    assert pg._betroffen("kaputt") == 0 and pg._betroffen(None) == 0


async def test_schema_steht_nie_aus_eingaben():
    o, c = ops(schema="wamo_test")
    await o.termine()
    assert "wamo_test.labor_termine" in c.aufrufe[0][1]
    with pytest.raises(ValueError):
        pg.AsyncpgDatenbank(DbZugang("h", 5432, "d", "u", "/ca", "passwortpasswort"), "wamo_dev; drop schema")


@pytest.mark.parametrize("fehler, erwartet", [
    (asyncpg.UniqueViolationError("x"), KonfliktFehler), (asyncpg.ForeignKeyViolationError("x"), KonfliktFehler),
    (asyncpg.SerializationError("x"), KonfliktFehler), (asyncpg.CheckViolationError("x"), PruefFehler),
    (asyncpg.NotNullViolationError("x"), PruefFehler), (asyncpg.DataError("x"), PruefFehler),
    (asyncpg.InsufficientPrivilegeError("Passwort geheim"), DatenbankFehler), (asyncpg.InterfaceError("x"), DatenbankFehler),
    (OSError("x"), DatenbankFehler), (TimeoutError("x"), DatenbankFehler),
])
async def test_fehlerabbildung(fehler, erwartet):
    c = FakeConn()
    c.fehler = fehler
    o, _ = ops(c)
    with pytest.raises(erwartet) as e:
        await o.termine()
    assert "geheim" not in str(e.value)


class FakePool:
    def __init__(self):
        self.conn = FakeConn()
        self.zu = False
        self.erworben = 0

    @contextlib.asynccontextmanager
    async def acquire(self):
        self.erworben += 1
        yield self.conn

    def is_closing(self):
        return self.zu

    async def close(self):
        self.zu = True

    async def fetch(self, sql, *a):
        return await self.conn.fetch(sql, *a)

    async def fetchrow(self, sql, *a):
        return await self.conn.fetchrow(sql, *a)

    async def fetchval(self, sql, *a):
        return await self.conn.fetchval(sql, *a)

    async def execute(self, sql, *a):
        return await self.conn.execute(sql, *a)


class FakeKontext:
    def __init__(self, *_a, **_k):
        self.check_hostname = False
        self.minimum_version = None
        self.geladen = None

    def load_verify_locations(self, cafile=None):
        self.geladen = cafile


@pytest.fixture
def db_mit_pool(monkeypatch):
    pool = FakePool()
    aufrufe = []

    async def create_pool(**kw):
        aufrufe.append(kw)
        return pool

    monkeypatch.setattr(pg.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(pg.ssl, "SSLContext", FakeKontext)
    return pg.AsyncpgDatenbank(DbZugang("db.test", 55322, "wamo", "wamo_werkstatt_login", "/etc/ca.crt", "geheimgeheim12"), "wamo_dev"), pool, aufrufe


async def test_pool_wird_einmal_mit_geprueftem_tls_geoeffnet(db_mit_pool):
    db, pool, aufrufe = db_mit_pool
    await db.termine()
    await db.termine()
    assert len(aufrufe) == 1
    kw = aufrufe[0]
    assert (kw["host"], kw["port"], kw["user"], kw["database"]) == ("db.test", 55322, "wamo_werkstatt_login", "wamo")
    assert kw["ssl"].check_hostname is True and kw["ssl"].geladen == "/etc/ca.crt" and kw["statement_cache_size"] == 0
    assert "geheimgeheim12" not in repr(db._zugang)
    await db.schliessen()
    assert pool.zu is True and db._pool is None
    await db.schliessen()


async def test_transaktion_commit_und_rollback(db_mit_pool):
    db, pool, _ = db_mit_pool
    async with db.transaktion() as tx:
        await tx.aufraeumen()
    assert pool.conn.ereignisse == ["begin", "commit"]
    with pytest.raises(RuntimeError):
        async with db.transaktion():
            raise RuntimeError("Fehler im Block")
    assert pool.conn.ereignisse[-2:] == ["begin", "rollback"]
    with pytest.raises(KonfliktFehler):
        async with db.transaktion() as tx:
            pool.conn.fehler = asyncpg.UniqueViolationError("x")
            await tx.aufraeumen()
    assert pool.conn.ereignisse[-1] == "rollback"


async def test_pool_nicht_erreichbar(monkeypatch):
    async def create_pool(**_kw):
        raise OSError("Passwort steht hier: geheim")

    monkeypatch.setattr(pg.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(pg.ssl, "SSLContext", FakeKontext)
    db = pg.AsyncpgDatenbank(DbZugang("db.test", 5432, "wamo", "u", "/ca", "passwortpasswort"), "wamo_dev")
    with pytest.raises(DatenbankFehler) as e:
        await db.termine()
    assert str(e.value) == "OSError"
    with pytest.raises(DatenbankFehler):
        async with db.transaktion():
            pass


async def test_ca_datei_nicht_lesbar(monkeypatch):
    class Kaputt(FakeKontext):
        def load_verify_locations(self, cafile=None):
            raise pg.ssl.SSLError("kaputt")

    monkeypatch.setattr(pg.ssl, "SSLContext", Kaputt)
    db = pg.AsyncpgDatenbank(DbZugang("db.test", 5432, "wamo", "u", "/ca", "passwortpasswort"), "wamo_dev")
    with pytest.raises(DatenbankFehler):
        await db.termine()
