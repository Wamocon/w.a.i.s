"""Datenbank der Werkstatt über asyncpg (Rolle wamo_werkstatt, Migration 0031).

Der Schemaname kommt aus der Konfiguration und ist auf wamo_dev, wamo_test und wamo_prod beschränkt. Alle Werte gehen als Parameter
($1, $2, ...) an die Datenbank, nie in den SQL-Text. Fehler der Datenbank werden in drei feste Arten übersetzt (DatenbankFehler,
KonfliktFehler, PruefFehler), ihr Text verlässt diese Datei nie.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import ssl
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import asyncpg

from .daten import DatenbankFehler, FreigabeKarte, KonfliktFehler, Profil, PruefFehler, Verbindung
from .konfig import SCHEMA_RE, DbZugang

POOL_MIN, POOL_MAX = 1, 4
VERBINDEN_S, BEFEHL_S = 5.0, 15.0

_KONFLIKT = (asyncpg.UniqueViolationError, asyncpg.ForeignKeyViolationError, asyncpg.SerializationError, asyncpg.DeadlockDetectedError)
_PRUEFUNG = (asyncpg.CheckViolationError, asyncpg.NotNullViolationError, asyncpg.DataError, asyncpg.RaiseError)
_AUSFALL = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, asyncio.TimeoutError)


def abbilden(e: BaseException) -> Exception:
    """Übersetzt einen Fehler von asyncpg in eine der drei festen Arten (nur der Typ, nie der Text)."""
    if isinstance(e, _KONFLIKT):
        return KonfliktFehler()
    if isinstance(e, _PRUEFUNG):
        return PruefFehler()
    return DatenbankFehler(type(e).__name__)


class _Sicher:
    """Umhüllt Pool oder Verbindung: jeder Fehler der Datenbank wird übersetzt."""

    def __init__(self, c: Any):
        self._c = c

    async def _lauf(self, name: str, sql: str, args: tuple) -> Any:
        try:
            return await getattr(self._c, name)(sql, *args)
        except (*_KONFLIKT, *_PRUEFUNG, *_AUSFALL) as e:
            raise abbilden(e) from None

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return await self._lauf("fetch", sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return await self._lauf("fetchrow", sql, args)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return await self._lauf("fetchval", sql, args)

    async def execute(self, sql: str, *args: Any) -> str:
        return await self._lauf("execute", sql, args)


def _zeile(r: Any) -> dict[str, Any] | None:
    return None if r is None else dict(r)


def _json(wert: Any) -> str:
    return json.dumps(wert, ensure_ascii=False, default=str, separators=(",", ":"))


def _betroffen(status: str) -> int:
    """'UPDATE 3' ergibt 3."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0


_TERMIN = "id::text as id, tag, beginn, ende, einwilligung_version, status::text as status, aufbewahrung_bis"
_KARTE = ("id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min, "
          "stand, geaendert_at")
_FREIGABE = "id::text as id, admin::text as admin, aktion, ziel::text as ziel, gilt_bis, ausgefuehrt_at, (gilt_bis < now()) as abgelaufen"
_PUNKT = "id as nr, titel, quelle, faellig, erledigt_at"


class _Ops:
    def __init__(self, c: _Sicher, schema: str):
        self._c, self._s = c, schema

    def _t(self, name: str) -> str:
        return f"{self._s}.{name}"

    # Anmeldung
    async def profil(self, user_id: str) -> Profil | None:
        r = await self._c.fetchrow(f"select rolle::text as rolle, aktiv, labor_art::text as labor_art from {self._t('profiles')} "
                                   "where user_id = $1::uuid", user_id)
        return None if r is None else Profil(user_id, r["rolle"], r["aktiv"] is True, r["labor_art"])

    # Kennzahlen
    async def _funktion(self, name: str, *args: Any) -> list[Mapping[str, Any]]:
        platz = ", ".join(f"${i + 1}::int" for i in range(len(args)))
        return [dict(r) for r in await self._c.fetch(f"select * from {self._t(name)}({platz})", *args)]

    async def sitzungen(self, tage: int) -> list[Mapping[str, Any]]:
        return await self._funktion("werkstatt_sitzungen", tage)

    async def latenz(self, tage: int) -> list[Mapping[str, Any]]:
        return await self._funktion("werkstatt_latenz", tage)

    async def aktionen(self, tage: int) -> list[Mapping[str, Any]]:
        return await self._funktion("werkstatt_aktionen", tage)

    async def labor_stand(self) -> list[Mapping[str, Any]]:
        return await self._funktion("werkstatt_labor_stand")

    # Termine, Plätze, Checkliste
    async def termine(self) -> list[dict[str, Any]]:
        return [dict(r) for r in await self._c.fetch(f"select {_TERMIN} from {self._t('labor_termine')} order by tag desc")]

    async def termin(self, termin_id: str) -> dict[str, Any] | None:
        return _zeile(await self._c.fetchrow(f"select {_TERMIN} from {self._t('labor_termine')} where id = $1::uuid", termin_id))

    async def termin_anlegen(self, daten: Mapping[str, Any], admin: str) -> dict[str, Any]:
        r = await self._c.fetchrow(
            f"insert into {self._t('labor_termine')} (tag, beginn, ende, einwilligung_version, status, aufbewahrung_bis, erstellt_von) "
            f"values ($1, $2, $3, $4, $5, $6, $7::uuid) returning {_TERMIN}",
            daten["tag"], daten["beginn"], daten["ende"], daten["einwilligung_version"], daten["status"], daten["aufbewahrung_bis"], admin)
        return dict(r)

    async def termin_aendern(self, termin_id: str, daten: Mapping[str, Any]) -> dict[str, Any] | None:
        return _zeile(await self._c.fetchrow(
            f"update {self._t('labor_termine')} set tag = $2, beginn = $3, ende = $4, einwilligung_version = $5, status = $6, "
            f"aufbewahrung_bis = $7 where id = $1::uuid returning {_TERMIN}",
            termin_id, daten["tag"], daten["beginn"], daten["ende"], daten["einwilligung_version"], daten["status"], daten["aufbewahrung_bis"]))

    async def termin_loeschen(self, termin_id: str) -> bool:
        return await self._c.fetchval(f"delete from {self._t('labor_termine')} where id = $1::uuid returning 1", termin_id) == 1

    async def plaetze(self, termin_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in await self._c.fetch(
            f"select platz, zweck, kennung, gast from {self._t('labor_plaetze')} where termin_id = $1::uuid order by platz", termin_id)]

    async def plaetze_setzen(self, termin_id: str, plaetze: list[dict[str, Any]]) -> None:
        await self._c.execute(f"delete from {self._t('labor_plaetze')} where termin_id = $1::uuid", termin_id)
        for p in plaetze:
            await self._c.execute(f"insert into {self._t('labor_plaetze')} (termin_id, platz, zweck, kennung, gast) "
                                  "values ($1::uuid, $2, $3, $4, $5)", termin_id, p["platz"], p["zweck"], p["kennung"], p["gast"])

    async def checkliste(self, termin_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in await self._c.fetch(
            f"select {_PUNKT} from {self._t('labor_checkliste')} where termin_id = $1::uuid order by id", termin_id)]

    async def checkliste_anlegen(self, termin_id: str, daten: Mapping[str, Any]) -> dict[str, Any]:
        r = await self._c.fetchrow(
            f"insert into {self._t('labor_checkliste')} (termin_id, titel, quelle, faellig) values ($1::uuid, $2, $3, $4) returning {_PUNKT}",
            termin_id, daten["titel"], daten["quelle"], daten["faellig"])
        return dict(r)

    async def checkliste_abhaken(self, termin_id: str, nr: int, erledigt: bool, admin: str) -> dict[str, Any] | None:
        return _zeile(await self._c.fetchrow(
            f"update {self._t('labor_checkliste')} set erledigt_at = case when $3::boolean then now() else null end, "
            f"erledigt_von = case when $3::boolean then $4::uuid else null end "
            f"where termin_id = $1::uuid and id = $2::bigint returning {_PUNKT}", termin_id, nr, erledigt, admin))

    # Karten, Zuordnung, Versionen
    async def karten(self, *, sperren: bool = False) -> list[dict[str, Any]]:
        sperre = " for update" if sperren else ""
        return [dict(r) for r in await self._c.fetch(f"select {_KARTE} from {self._t('labor_karten')} order by id{sperre}")]

    async def karte(self, karte_id: str) -> dict[str, Any] | None:
        return _zeile(await self._c.fetchrow(f"select {_KARTE} from {self._t('labor_karten')} where id = $1", karte_id))

    async def karte_anlegen(self, karte_id: str, daten: Mapping[str, Any], admin: str) -> dict[str, Any]:
        r = await self._c.fetchrow(
            f"insert into {self._t('labor_karten')} (id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, "
            f"werkzeuge, dauer_min, stand, geaendert_von) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text[], $11, 'entwurf', $12::uuid) "
            f"returning {_KARTE}",
            karte_id, daten["gruppe"], daten["titel"], daten["aufgabe"], daten["erwartung"], daten["fehler"], daten["lernziel"],
            daten["wissen"], daten["wissenstext"], list(daten["werkzeuge"]), daten["dauer_min"], admin)
        return dict(r)

    async def karte_aendern(self, karte_id: str, daten: Mapping[str, Any], admin: str) -> dict[str, Any] | None:
        return _zeile(await self._c.fetchrow(
            f"update {self._t('labor_karten')} set titel = $2, aufgabe = $3, erwartung = $4, fehler = $5, lernziel = $6, wissen = $7, "
            f"wissenstext = $8, werkzeuge = $9::text[], dauer_min = $10, stand = 'entwurf', geaendert_von = $11::uuid, geaendert_at = now() "
            f"where id = $1 returning {_KARTE}",
            karte_id, daten["titel"], daten["aufgabe"], daten["erwartung"], daten["fehler"], daten["lernziel"], daten["wissen"],
            daten["wissenstext"], list(daten["werkzeuge"]), daten["dauer_min"], admin))

    async def karte_loeschen(self, karte_id: str) -> bool:
        return await self._c.fetchval(f"delete from {self._t('labor_karten')} where id = $1 and stand = 'entwurf' returning 1", karte_id) == 1

    async def zuordnung(self, termin_id: str) -> dict[int, list[str]]:
        matrix: dict[int, list[str]] = {}
        for r in await self._c.fetch(f"select platz, karte_id from {self._t('labor_zuordnung')} where termin_id = $1::uuid "
                                     "order by platz, karte_id", termin_id):
            matrix.setdefault(r["platz"], []).append(r["karte_id"])
        return matrix

    async def zuordnung_setzen(self, termin_id: str, matrix: dict[int, list[str]]) -> None:
        await self._c.execute(f"delete from {self._t('labor_zuordnung')} where termin_id = $1::uuid", termin_id)
        for platz, ids in matrix.items():
            for karte_id in ids:
                await self._c.execute(f"insert into {self._t('labor_zuordnung')} (termin_id, platz, karte_id) values ($1::uuid, $2, $3)",
                                      termin_id, platz, karte_id)

    async def versionen(self, grenze: int) -> list[dict[str, Any]]:
        return [dict(r) for r in await self._c.fetch(
            f"select version, erstellt_at, anzahl_aenderungen, wissen_zeichen, aktiv from {self._t('labor_karten_versionen')} "
            "order by version desc limit $1", grenze)]

    async def aktive_version(self) -> int | None:
        return await self._c.fetchval(f"select version from {self._t('labor_karten_versionen')} where aktiv")

    # Veröffentlichen
    @staticmethod
    def _karte_aus(r: Any) -> FreigabeKarte:
        ziel = json.loads(r["ziel"]) if isinstance(r["ziel"], str) else dict(r["ziel"] or {})
        return FreigabeKarte(r["id"], r["admin"], r["aktion"], ziel, r["gilt_bis"], r["abgelaufen"] is True, r["ausgefuehrt_at"] is not None)

    async def freigabekarte_anlegen(self, admin: str, aktion: str, ziel: Mapping[str, Any], gilt_s: int) -> FreigabeKarte:
        # Die Gültigkeit rechnet die Datenbank mit ihrer Uhr, damit die Prüfung "höchstens fünf Minuten" nie an einer Uhrendifferenz scheitert.
        r = await self._c.fetchrow(
            f"insert into {self._t('werkstatt_karten')} (id, admin, aktion, ziel, gilt_bis) "
            f"values ($1::uuid, $2::uuid, $3, $4::text::jsonb, now() + ($5::int * interval '1 second')) returning {_FREIGABE}",
            str(uuid.uuid4()), admin, aktion, _json(ziel), gilt_s)
        return self._karte_aus(r)

    async def freigabekarte_sperren(self, karte_id: str) -> FreigabeKarte | None:
        r = await self._c.fetchrow(f"select {_FREIGABE} from {self._t('werkstatt_karten')} where id = $1::uuid for update", karte_id)
        return None if r is None else self._karte_aus(r)

    async def freigabekarte_verbrauchen(self, karte_id: str) -> bool:
        return await self._c.fetchval(f"update {self._t('werkstatt_karten')} set ausgefuehrt_at = now() "
                                      "where id = $1::uuid and ausgefuehrt_at is null returning 1", karte_id) == 1

    async def version_anlegen(self, admin: str, aenderungen: int, zeichen: int, karten: list[dict[str, Any]]) -> int:
        await self._c.execute(f"update {self._t('labor_karten_versionen')} set aktiv = false where aktiv")
        return await self._c.fetchval(
            f"insert into {self._t('labor_karten_versionen')} (erstellt_von, anzahl_aenderungen, wissen_zeichen, karten, aktiv) "
            "values ($1::uuid, $2, $3, $4::text::jsonb, true) returning version", admin, aenderungen, zeichen, _json(karten))

    async def entwuerfe_veroeffentlichen(self, ids: list[str]) -> int:
        return _betroffen(await self._c.execute(
            f"update {self._t('labor_karten')} set stand = 'veroeffentlicht' where stand = 'entwurf' and id = any($1::text[])", list(ids)))

    # Prüfspur und Pflege
    async def aktion_buchen(self, user_id: str, tool: str, risiko: str, params: Mapping[str, Any], ergebnis: Mapping[str, Any]) -> None:
        await self._c.execute(
            f"insert into {self._t('actions')} (user_id, tool, params, risk, status, result, decided_at, finished_at) "
            f"values ($1::uuid, $2, $3::text::jsonb, $4::text::{self._t('risk_class')}, 'done'::{self._t('action_status')}, "
            "$5::text::jsonb, now(), now())", user_id, tool, _json(params), risiko, _json(ergebnis))

    async def aufraeumen(self) -> None:
        await self._c.execute(f"select {self._t('werkstatt_aufraeumen')}()")


class _PoolZiel:
    """Nicht-transaktionale Abfragen: jede läuft auf einer Verbindung aus dem Pool."""

    def __init__(self, db: AsyncpgDatenbank):
        self._db = db

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return await (await self._db._pool_holen()).fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return await (await self._db._pool_holen()).fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return await (await self._db._pool_holen()).fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any) -> str:
        return await (await self._db._pool_holen()).execute(sql, *args)


class AsyncpgDatenbank(_Ops):
    """Pool zur Datenbank. Der Pool entsteht beim ersten Zugriff (kein Start ohne Datenbank nötig, bis dahin antwortet der Dienst 503)."""

    def __init__(self, zugang: DbZugang, schema: str):
        if not SCHEMA_RE.fullmatch(schema):
            raise ValueError("Schema muss wamo_dev, wamo_test oder wamo_prod sein")
        super().__init__(_Sicher(_PoolZiel(self)), schema)
        self._zugang = zugang
        self._pool: asyncpg.Pool | None = None
        self._sperre: asyncio.Lock | None = None
        self._schleife: asyncio.AbstractEventLoop | None = None

    async def _pool_holen(self) -> asyncpg.Pool:
        schleife = asyncio.get_running_loop()
        if self._pool is not None and self._schleife is schleife and not self._pool.is_closing():
            return self._pool
        if self._sperre is None or self._schleife is not schleife:
            self._sperre = asyncio.Lock()
        async with self._sperre:
            if self._pool is not None and self._schleife is schleife and not self._pool.is_closing():
                return self._pool
            kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            kontext.minimum_version = ssl.TLSVersion.TLSv1_2
            kontext.check_hostname = True
            try:
                kontext.load_verify_locations(cafile=self._zugang.sslrootcert)
                self._pool = await asyncpg.create_pool(
                    host=self._zugang.host, port=self._zugang.port, user=self._zugang.user, password=self._zugang.password,
                    database=self._zugang.dbname, ssl=kontext, min_size=POOL_MIN, max_size=POOL_MAX, statement_cache_size=0,
                    timeout=VERBINDEN_S, command_timeout=BEFEHL_S, max_inactive_connection_lifetime=120)
            except (ssl.SSLError, *_AUSFALL) as e:  # nur der Typ: die Meldung könnte Verbindungsdaten enthalten
                raise DatenbankFehler(type(e).__name__) from None
            self._schleife = schleife
            return self._pool

    @contextlib.asynccontextmanager
    async def transaktion(self) -> AsyncIterator[Verbindung]:
        pool = await self._pool_holen()
        try:
            async with pool.acquire() as verbindung, verbindung.transaction():
                yield _Ops(_Sicher(verbindung), self._s)
        except (*_KONFLIKT, *_PRUEFUNG, *_AUSFALL) as e:  # Fehler beim Beginn oder beim Abschluss der Transaktion
            raise abbilden(e) from None

    async def schliessen(self) -> None:
        if self._pool is not None and not self._pool.is_closing():
            await self._pool.close()
        self._pool = None
