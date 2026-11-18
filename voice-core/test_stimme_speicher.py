"""Tests für stimme_einwilligung.py und stimme_speicher.py ohne Datenbank (Attrappe wie in test_memory.py).

Ausführen:  python -m pytest -q test_stimme_speicher.py   (im Ordner voice-core/)
"""

import unittest
from datetime import datetime, timezone
from unittest import mock

import asyncpg
import numpy as np

import memory as m
import stimme_einwilligung as se
import stimme_speicher as ss
from stimme_modell import DIM, als_vektor, kosinus

USER_A = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
USER_B = "5b3f1c2d-8e7a-4b6c-9d0e-1f2a3b4c5d6e"
ABDRUCK = np.eye(DIM, dtype=np.float32)[3]


class FakeDb:
    """speakers als Wörterbuch. ohne_0025: die Spalte voice_threshold fehlt (Migration 0025 noch nicht angewandt)."""

    configured = True
    schema = "wamo_test"

    def __init__(self, zeilen: dict | None = None, fehler: Exception | None = None, schwellen: dict | None = None,
                 ohne_0025: bool = False):
        self.zeilen = zeilen if zeilen is not None else {}  # user_id -> Text des Abdrucks
        self.schwellen = schwellen if schwellen is not None else {}  # user_id -> voice_threshold
        self.fehler = fehler
        self.ohne_0025 = ohne_0025
        self.calls: list[tuple] = []
        # Stand vor Migration 0029: die Spalte mikrofon fehlt, der Kern liest und schreibt einen Abdruck wie bisher (MikrofonDb: mit 0029)

    def t(self, name):
        return f"wamo_test.{name}"

    def _pruefen(self, sql):
        if self.fehler:
            raise self.fehler
        if "mikrofon" in sql:
            raise asyncpg.UndefinedColumnError('column "mikrofon" does not exist')
        if self.ohne_0025 and "voice_threshold" in sql:
            raise asyncpg.UndefinedColumnError('column "voice_threshold" does not exist')

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        self._pruefen(sql)
        return []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        self._pruefen(sql)
        return self.zeilen.get(args[0])

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        self._pruefen(sql)
        if args[0] not in self.zeilen:
            return None
        return {"abdruck": self.zeilen[args[0]], "schwelle": self.schwellen.get(args[0]) if "voice_threshold" in sql else None}

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        self._pruefen(sql)
        if sql.startswith("delete"):
            self.schwellen.pop(args[0], None)
            return f"DELETE {1 if self.zeilen.pop(args[0], None) is not None else 0}"
        self.zeilen[args[0]] = args[2]
        if "voice_threshold" in sql:
            self.schwellen[args[0]] = args[5]
        return "INSERT 0 1"


def speicher(user: str, db: FakeDb | None) -> m.MemoryStore:
    return m.MemoryStore(user, db)


class EinwilligungTests(unittest.TestCase):
    def test_version_und_nachricht(self):
        self.assertEqual(se.EINWILLIGUNG_VERSION, "stimme-1")
        self.assertEqual(
            se.einwilligung_nachricht(),
            {"type": "stimmabdruck_einwilligung", "version": "stimme-1", "text": se.EINWILLIGUNG_TEXT},
        )

    def test_nur_genau_diese_version_gilt(self):
        self.assertTrue(se.einwilligung_gilt("stimme-1"))
        for falsch in ("stimme-0", "stimme-2", "Stimme-1", " stimme-1", "", None, 1, True, ["stimme-1"]):
            self.assertFalse(se.einwilligung_gilt(falsch), falsch)

    def test_text_nennt_den_kern_der_einwilligung_und_hat_keinen_gedankenstrich(self):
        text = se.EINWILLIGUNG_TEXT
        for teil in ("192 Zahlen", "keine Aufnahme", "freiwillig", "jederzeit", "Einstellungen", "Widerruf", "Artikel 9"):
            self.assertIn(teil, text)
        self.assertNotIn("–", text)
        self.assertNotIn("—", text)
        self.assertNotIn(" - ", text)
        self.assertRegex(text, "[äöüß]")  # echte Umlaute


class LadenTests(unittest.IsolatedAsyncioTestCase):
    async def test_laedt_den_abdruck_des_eigenen_profils(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK)})
        ok, abdruck = await ss.abdruck_laden(speicher(USER_A, db))
        self.assertTrue(ok)
        self.assertAlmostEqual(kosinus(abdruck, ABDRUCK), 1.0, places=5)
        sql, args = db.calls[0][1], db.calls[0][2]
        self.assertIn("wamo_test.speakers", sql)
        self.assertIn("is_owner", sql)
        self.assertEqual(args, (USER_A,))

    async def test_kein_abdruck_ist_ok_und_leer(self):
        self.assertEqual(await ss.abdruck_laden(speicher(USER_A, FakeDb())), (True, None))

    async def test_zwei_profile_in_einem_prozess_bekommen_je_ihren_abdruck(self):
        andere = np.eye(DIM, dtype=np.float32)[7]
        db = FakeDb({USER_A: als_vektor(ABDRUCK), USER_B: als_vektor(andere)})
        _, a = await ss.abdruck_laden(speicher(USER_A, db))
        _, b = await ss.abdruck_laden(speicher(USER_B, db))
        self.assertAlmostEqual(kosinus(a, ABDRUCK), 1.0, places=5)
        self.assertAlmostEqual(kosinus(b, andere), 1.0, places=5)
        self.assertLess(kosinus(a, b), 0.01)
        _, drittes = await ss.abdruck_laden(speicher("11111111-2222-4333-8444-555555555555", db))
        self.assertIsNone(drittes)

    async def test_falsches_format_ist_ein_fehler_kein_abdruck(self):
        db = FakeDb({USER_A: "[0.1,0.2]"})
        self.assertEqual(await ss.abdruck_laden(speicher(USER_A, db)), (False, None))

    async def test_datenbankfehler_ist_ein_fehler_und_wirft_nicht(self):
        db = FakeDb(fehler=asyncpg.PostgresError("kaputt"))
        self.assertEqual(await ss.abdruck_laden(speicher(USER_A, db)), (False, None))

    async def test_ohne_datenbank_oder_profil_wird_nichts_gefragt(self):
        for store in (speicher(USER_A, None), speicher(None, FakeDb()), speicher("keine-uuid", FakeDb())):
            self.assertEqual(await ss.abdruck_laden(store), (False, None))
            self.assertEqual(await ss.abdruck_mit_schwelle_laden(store), (False, None, None))


class SchwelleLadenTests(unittest.IsolatedAsyncioTestCase):
    """Persönliche Schwelle (speakers.voice_threshold, Migration 0025) mit dem Abdruck in einer Abfrage. Fehlt die Spalte, gilt der Stand
    davor: der Abdruck ohne Schwelle, ohne Fehler."""

    def setUp(self):
        ss._GEMELDET.clear()
        ss._schwelle_spalte(True)

    async def test_laedt_abdruck_und_schwelle(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK)}, schwellen={USER_A: 0.42})
        ok, abdruck, schwelle = await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
        self.assertTrue(ok)
        self.assertAlmostEqual(kosinus(abdruck, ABDRUCK), 1.0, places=5)
        self.assertAlmostEqual(schwelle, 0.42)
        art, sql, args = db.calls[0]
        self.assertEqual(art, "fetchrow")
        self.assertIn("voice_threshold", sql)
        self.assertIn("wamo_test.speakers", sql)
        self.assertIn("is_owner", sql)
        self.assertEqual(args, (USER_A,))
        self.assertEqual(len(db.calls), 1)

    async def test_ohne_schwelle_gilt_keine(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK)})
        ok, abdruck, schwelle = await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
        self.assertTrue(ok and abdruck is not None)
        self.assertIsNone(schwelle)
        self.assertEqual(await ss.abdruck_mit_schwelle_laden(speicher(USER_B, db)), (True, None, None))

    async def test_unbrauchbare_schwelle_gilt_nicht(self):
        for falsch in (0.95, 0.1, float("nan"), "0.4"):
            db = FakeDb({USER_A: als_vektor(ABDRUCK)}, schwellen={USER_A: falsch})
            ok, abdruck, schwelle = await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
            self.assertTrue(ok and abdruck is not None, falsch)
            self.assertIsNone(schwelle, falsch)

    async def test_ohne_migration_0025_wie_vorher_und_einmal_gemeldet(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK)}, ohne_0025=True)
        with mock.patch.object(ss.logger, "warning") as warnung:
            ok, abdruck, schwelle = await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
            await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
        self.assertTrue(ok)
        self.assertAlmostEqual(kosinus(abdruck, ABDRUCK), 1.0, places=5)
        self.assertIsNone(schwelle)
        self.assertNotIn("voice_threshold", db.calls[1][1])  # zweiter Versuch ohne die Spalte
        self.assertEqual(warnung.call_count, 1)
        self.assertIn("0025", warnung.call_args.args[0])
        self.assertFalse(ss.schwelle_speicherbar())
        db.ohne_0025 = False  # die Migration ist inzwischen angewandt
        await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db))
        self.assertTrue(ss.schwelle_speicherbar())

    async def test_datenbankfehler_bleibt_ein_fehler(self):
        db = FakeDb(fehler=asyncpg.PostgresError("kaputt"))
        self.assertEqual(await ss.abdruck_mit_schwelle_laden(speicher(USER_A, db)), (False, None, None))
        self.assertEqual(len(db.calls), 1)


class SpeichernTests(unittest.IsolatedAsyncioTestCase):
    async def test_speichert_mit_einwilligung_und_version(self):
        db = FakeDb()
        am = datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc)
        ok = await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="Erika", einwilligung_am=am)
        self.assertTrue(ok)
        art, sql, args = db.calls[0]
        self.assertIn("wamo_test.speakers", sql)
        self.assertIn("on conflict (user_id) where is_owner do update", sql)
        self.assertIn("extensions.vector", sql)
        self.assertEqual(args[0], USER_A)
        self.assertEqual(args[1], "Erika")
        self.assertEqual(args[2], als_vektor(ABDRUCK))
        self.assertEqual(args[3], "stimme-1")
        self.assertEqual(args[4], am)
        self.assertIn(USER_A, db.zeilen)

    async def test_ohne_gueltige_einwilligung_wird_nichts_gespeichert(self):
        db = FakeDb()
        am = datetime.now(timezone.utc)
        for version in ("", "stimme-0", None):
            self.assertFalse(await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version=version, name="E", einwilligung_am=am))
        self.assertFalse(await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="E", einwilligung_am=None))
        self.assertEqual(db.calls, [])

    async def test_name_wird_auf_die_erlaubte_laenge_gebracht(self):
        db = FakeDb()
        am = datetime.now(timezone.utc)
        await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="x" * 200, einwilligung_am=am)
        self.assertEqual(len(db.calls[0][2][1]), 60)
        await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="  ", einwilligung_am=am)
        self.assertTrue(db.calls[1][2][1])

    async def test_datenbankfehler_ist_kein_erfolg(self):
        db = FakeDb(fehler=asyncpg.PostgresError("kaputt"))
        am = datetime.now(timezone.utc)
        self.assertFalse(await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="E", einwilligung_am=am))

    async def test_ohne_datenbank_kein_erfolg(self):
        am = datetime.now(timezone.utc)
        self.assertFalse(await ss.abdruck_speichern(speicher(USER_A, None), ABDRUCK, version="stimme-1", name="E", einwilligung_am=am))


class SchwelleSpeichernTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ss._GEMELDET.clear()
        ss._schwelle_spalte(True)
        self.am = datetime(2026, 11, 17, 9, 30, tzinfo=timezone.utc)

    async def test_speichert_die_persoenliche_schwelle(self):
        db = FakeDb()
        ok = await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="Erika", einwilligung_am=self.am,
                                        schwelle=0.42)
        self.assertTrue(ok)
        _, sql, args = db.calls[0]
        self.assertIn("voice_threshold", sql)
        self.assertIn("voice_threshold = excluded.voice_threshold", sql)  # neu einlernen ersetzt auch die Schwelle
        self.assertEqual(args[:5], (USER_A, "Erika", als_vektor(ABDRUCK), "stimme-1", self.am))
        self.assertEqual(args[5], 0.42)
        self.assertEqual(db.schwellen[USER_A], 0.42)

    async def test_ohne_oder_mit_unbrauchbarer_schwelle_wird_null_gespeichert(self):
        for schwelle in (None, float("nan"), 0.95):
            db = FakeDb(schwellen={USER_A: 0.42})
            await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="E", einwilligung_am=self.am,
                                       schwelle=schwelle)
            self.assertIsNone(db.schwellen[USER_A], schwelle)  # die alte Schwelle gilt für den neuen Abdruck nicht

    async def test_ohne_migration_0025_wird_ohne_schwelle_gespeichert(self):
        db = FakeDb(ohne_0025=True)
        with mock.patch.object(ss.logger, "warning") as warnung:
            ok = await ss.abdruck_speichern(speicher(USER_A, db), ABDRUCK, version="stimme-1", name="E", einwilligung_am=self.am,
                                            schwelle=0.42)
        self.assertTrue(ok)
        self.assertEqual(len(db.calls), 2)
        self.assertNotIn("voice_threshold", db.calls[1][1])
        self.assertEqual(len(db.calls[1][2]), 5)
        self.assertIn(USER_A, db.zeilen)
        self.assertEqual(warnung.call_count, 1)
        self.assertFalse(ss.schwelle_speicherbar())  # die Sitzung lässt die nicht gespeicherte Schwelle dann weg


class LoeschenTests(unittest.IsolatedAsyncioTestCase):
    async def test_loescht_nur_den_eigenen_abdruck_vollstaendig(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK), USER_B: als_vektor(ABDRUCK)})
        self.assertTrue(await ss.abdruck_loeschen(speicher(USER_A, db)))
        sql, args = db.calls[0][1], db.calls[0][2]
        self.assertTrue(sql.startswith("delete from wamo_test.speakers"))
        self.assertIn("is_owner", sql)
        self.assertEqual(args, (USER_A,))
        self.assertNotIn(USER_A, db.zeilen)
        self.assertIn(USER_B, db.zeilen)

    async def test_nichts_zu_loeschen_ist_auch_in_ordnung(self):
        self.assertTrue(await ss.abdruck_loeschen(speicher(USER_A, FakeDb())))

    async def test_datenbankfehler_ist_kein_erfolg(self):
        self.assertFalse(await ss.abdruck_loeschen(speicher(USER_A, FakeDb(fehler=asyncpg.PostgresError("kaputt")))))

    async def test_ohne_datenbank_kein_erfolg(self):
        self.assertFalse(await ss.abdruck_loeschen(speicher(USER_A, None)))


# ---------- Ein Abdruck je Mikrofon (Migration 0029, Wunsch vom 18.11.2026) ----------

from stimme_gate import Abdruck  # noqa: E402
from stimme_mikrofon import UNBEKANNT, Mikrofon, mikrofon_aus  # noqa: E402

HEADSET = mikrofon_aus("Headset (Jabra)")
LAPTOP = mikrofon_aus("Mikrofonarray (Realtek)")
AM = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)


class MikrofonDb:
    """speakers mit Migration 0029: eine Zeile je (user_id, mikrofon)."""

    configured = True
    schema = "wamo_test"

    def __init__(self, fehler: Exception | None = None):
        self.zeilen: dict[tuple[str, str], dict] = {}
        self.fehler = fehler
        self.calls: list[tuple] = []

    def t(self, name):
        return f"wamo_test.{name}"

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        if self.fehler:
            raise self.fehler
        zeilen = [dict(z, mikrofon=k[1]) for k, z in self.zeilen.items() if k[0] == args[0]]
        if "voiceprint_shadow" in sql:
            return [z for z in zeilen if z.get("schatten") is not None and z["version"] in args[1]]
        return sorted(zeilen, key=lambda z: z["am"], reverse=True)[: args[1]]

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        if self.fehler:
            raise self.fehler
        if sql.startswith("delete"):
            weg = [k for k in self.zeilen if k[0] == args[0] and (len(args) == 1 or k[1] == args[1])]
            for k in weg:
                del self.zeilen[k]
            return f"DELETE {len(weg)}"
        if sql.startswith("update"):
            z = self.zeilen.get((args[0], args[4]))
            if z is None or z["version"] not in ("stimme-2", "stimme-3"):
                return "UPDATE 0"
            z.update(schatten=args[1], modell=args[2])
            return "UPDATE 1"
        self.zeilen[(args[0], args[6])] = {"abdruck": args[2], "version": args[3], "am": args[4], "schwelle": args[5], "name": args[7],
                                           "schatten": None, "modell": None}
        return "INSERT 0 1"


class MikrofonSpeicherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ss._GEMELDET.clear()

    async def speichern(self, db, mikrofon, abdruck=ABDRUCK, version="stimme-3", am=AM, **kw):
        return await ss.abdruck_speichern(speicher(USER_A, db), abdruck, version=version, name="Erika", einwilligung_am=am, schwelle=0.33,
                                          mikrofon=mikrofon, **kw)

    async def test_je_mikrofon_eine_zeile_und_upsert_ersetzt_nur_dieses(self):
        db = MikrofonDb()
        self.assertTrue(await self.speichern(db, HEADSET))
        self.assertTrue(await self.speichern(db, LAPTOP, am=datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)))
        anders = np.eye(DIM, dtype=np.float32)[5]
        self.assertTrue(await self.speichern(db, HEADSET, abdruck=anders, am=datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)))
        _, sql, args = db.calls[-1]
        self.assertIn("on conflict (user_id, mikrofon) where is_owner do update set", sql)
        self.assertIn("mikrofon_name = excluded.mikrofon_name", sql)
        self.assertEqual(args[6:], (HEADSET.kennung, "Headset (Jabra)"))
        ok, liste, mehrere = await ss.abdruecke_laden(speicher(USER_A, db))
        self.assertTrue(ok and mehrere)
        self.assertEqual([a.mikrofon for a in liste], [LAPTOP, HEADSET])  # älteste zuerst
        self.assertAlmostEqual(kosinus(liste[1].vektor, anders), 1.0, places=5)
        self.assertEqual([a.schwelle for a in liste], [0.33, 0.33])
        self.assertEqual(liste[0].am, datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc))
        _, sql, args = [c for c in db.calls if c[0] == "fetch"][-1]
        for teil in ("mikrofon", "mikrofon_name", "is_owner", "voiceprint is not null", "order by enrolled_at desc"):
            self.assertIn(teil, sql)
        self.assertEqual(args, (USER_A, 3))

    async def test_schatten_je_mikrofon(self):
        import stimme_schatten as sch

        db = MikrofonDb()
        schatten = np.ones(sch.SCHATTEN_DIM, dtype=np.float32)
        await self.speichern(db, HEADSET, schatten=schatten, schatten_modell=sch.SCHATTEN_MODELL)
        await self.speichern(db, LAPTOP, version="stimme-1", schatten=schatten, schatten_modell=sch.SCHATTEN_MODELL)  # stimme-1: keiner
        update = [c for c in db.calls if c[1].startswith("update")]
        self.assertEqual(len(update), 1)
        self.assertIn("and mikrofon = $5", update[0][1])
        self.assertEqual(update[0][2][4], HEADSET.kennung)
        geladen = await ss.schatten_alle_laden(speicher(USER_A, db), sch.SCHATTEN_MODELL, sch.SCHATTEN_DIM, mehrere=True)
        self.assertEqual(list(geladen), [HEADSET.kennung])
        self.assertAlmostEqual(kosinus(geladen[HEADSET.kennung], schatten), 1.0, places=5)
        self.assertEqual(await ss.schatten_alle_laden(speicher(USER_A, db), "anderes-modell", sch.SCHATTEN_DIM, mehrere=True), {})
        _, sql, args = [c for c in db.calls if c[0] == "fetch"][-1]
        self.assertIn("consent_text_version = any($2::text[])", sql)
        self.assertEqual(sorted(args[1]), ["stimme-2", "stimme-3"])

    async def test_einen_oder_alle_loeschen(self):
        db = MikrofonDb()
        await self.speichern(db, HEADSET)
        await self.speichern(db, LAPTOP)
        self.assertTrue(await ss.abdruck_loeschen(speicher(USER_A, db), mikrofon=HEADSET.kennung))
        _, sql, args = db.calls[-1]
        self.assertIn("and is_owner and mikrofon = $2", sql)
        self.assertEqual(args, (USER_A, HEADSET.kennung))
        self.assertEqual(list(db.zeilen), [(USER_A, LAPTOP.kennung)])
        self.assertTrue(await ss.abdruck_loeschen(speicher(USER_A, db)))
        self.assertEqual(db.zeilen, {})

    async def test_ohne_migration_0029_ein_abdruck_wie_bisher(self):
        db = FakeDb({USER_A: als_vektor(ABDRUCK)}, schwellen={USER_A: 0.31})
        ok, liste, mehrere = await ss.abdruecke_laden(speicher(USER_A, db))
        self.assertEqual((ok, mehrere, len(liste)), (True, False, 1))
        self.assertEqual((liste[0].mikrofon, liste[0].schwelle), (Mikrofon(UNBEKANNT, None), 0.31))
        self.assertEqual(await ss.abdruecke_laden(speicher(USER_B, db)), (True, [], False))
        # ein Abdruck je Mikrofon geht ohne 0029 nicht: nichts gespeichert, der alte Abdruck bleibt
        self.assertFalse(await self.speichern(db, HEADSET))
        self.assertEqual(db.zeilen[USER_A], als_vektor(ABDRUCK))
        self.assertFalse(await ss.abdruck_loeschen(speicher(USER_A, db), mikrofon=HEADSET.kennung))
        self.assertIn(USER_A, db.zeilen)

    async def test_fehler_kaputte_zeile_und_ohne_datenbank(self):
        self.assertEqual(await ss.abdruecke_laden(speicher(USER_A, MikrofonDb(fehler=asyncpg.PostgresError("weg")))), (False, [], None))
        self.assertEqual(await ss.abdruecke_laden(m.MemoryStore(USER_A, None)), (False, [], None))
        db = MikrofonDb()
        db.zeilen[(USER_A, HEADSET.kennung)] = {"abdruck": "[1,2]", "version": "stimme-3", "am": AM, "schwelle": None, "name": "Headset"}
        self.assertEqual(await ss.abdruecke_laden(speicher(USER_A, db)), (False, [], True))
        db.zeilen[(USER_A, HEADSET.kennung)] = {"abdruck": als_vektor(ABDRUCK), "version": "stimme-3", "am": AM, "schwelle": 7.0,
                                                "name": "Headset"}
        ok, liste, _ = await ss.abdruecke_laden(speicher(USER_A, db))
        self.assertTrue(ok)
        self.assertIsNone(liste[0].schwelle)  # unbrauchbare Schwelle: die aus der Umgebung
        self.assertFalse(await ss.abdruck_speichern(speicher(USER_A, MikrofonDb(fehler=asyncpg.PostgresError("weg"))), ABDRUCK,
                                                    version="stimme-3", name="A", einwilligung_am=AM, mikrofon=HEADSET))

    async def test_ergebnis_ist_ein_abdruck_des_gates(self):
        db = MikrofonDb()
        await self.speichern(db, HEADSET)
        _, liste, _ = await ss.abdruecke_laden(speicher(USER_A, db))
        self.assertIsInstance(liste[0], Abdruck)


if __name__ == "__main__":
    unittest.main()
