"""Aufträge an W.A.I.S. selbst (selbstauftraege.py, dev_agent_selbst.py und die Einhängepunkte in dev_agent.py und bot.py).

Geprüft wird: was gespeichert wird (nur Text, Art, Priorität, Kriterien; Schlüssel geschwärzt), dass jede Zeile der Liste den Regeln der
Migration 0030 entspricht, dass der Kern nur anlegt, liest und zwischen offen und verworfen wechselt, dass es die Werkzeuge und die
Nachricht nur für Admins gibt (nie für Mitglieder, nie ohne Zulassung im Büro, nie ohne Datenbank), dass ein Eintrag nach Fremdinhalt als
unsicher gilt und die Liste als Fremdinhalt zurückgeht, dass Fehler mit ok false und einem Satz als grund zurückkommen (Fehlerbuch) und dass
der Sperrsatz für das eigene Repo auf den Rückstand verweist. Alle Tests laufen ohne Netz und ohne Datenbank (Attrappen).

Ausführen:  python -m pytest -q test_selbstauftraege.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import dev_agent
import entwicklung_betrieb as eb
import fehlerbuch
import selbstauftraege as sa
import test_entwicklung_betrieb as tb
from test_auftrag_entwuerfe import FakeDb, Params
from test_dev_agent_sokrates2 import FakeTask

NIKO = tb.NIKO
SCHLUESSEL = "sk-ant-api03-" + "GEHEIMselbst" * 4
ZEIT = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


def zeile(nr=7, **extra) -> dict:
    werte = {"nr": nr, "titel": "Mikrofon im Log", "art": "umsetzung", "prioritaet": 2, "status": "offen", "quelle": "sprache",
             "unsicher": False, "erstellt_at": ZEIT, "bearbeiter": None, "ergebnis": None, "geaendert_at": ZEIT}
    werte.update(extra)
    return werte


def auftrag(**extra) -> sa.Selbstauftrag:
    werte = {"titel": "Mikrofon im Log", "beschreibung": "Die Mikrofonvorgaben in den Kern-Log schreiben.", "art": "umsetzung",
             "prioritaet": 1, "abnahme": ("Eine Zeile im Log",), "quelle": "sprache", "unsicher": False}
    werte.update(extra)
    return sa.Selbstauftrag(**werte)


# ---------------------------------------------------------------- Attrappe des Speichers
class FakeSelbst:
    """Speicher im Speicher, mit derselben Schnittstelle wie DatenbankSelbstauftraege."""

    def __init__(self):
        self.eintraege: list[dict] = []
        self.gespeichert: list[sa.Selbstauftrag] = []
        self.fehler: str | None = None  # Satz, mit dem jede Anfrage scheitert (Datenbank weg)
        self.wirft: BaseException | None = None
        self.aufrufe: list[str] = []

    def _pruefen(self, name: str):
        self.aufrufe.append(name)
        if self.wirft is not None:
            raise self.wirft

    async def speichern(self, a):
        self._pruefen("speichern")
        if self.fehler:
            return None, self.fehler
        try:
            geprueft = sa.auftrag_pruefen(a)
        except ValueError:
            return None, sa.SATZ_UNGUELTIG
        self.gespeichert.append(geprueft)
        nr = len(self.eintraege) + 1
        self.eintraege.append({"nr": nr, "titel": geprueft.titel, "art": geprueft.art, "prioritaet": geprueft.prioritaet, "status": "offen",
                               "quelle": geprueft.quelle, "unsicher": geprueft.unsicher, "erstellt_ms": 1})
        return nr, None

    async def liste(self):
        self._pruefen("liste")
        return (None, self.fehler) if self.fehler else (list(self.eintraege), None)

    async def verwerfen(self, nr):
        self._pruefen("verwerfen")
        if self.fehler:
            return self.fehler
        for e in self.eintraege:
            if e["nr"] == nr and e["status"] in ("offen", "in_arbeit"):
                e["status"] = "verworfen"
                return None
        return sa.SATZ_NICHT_GEFUNDEN

    async def oeffnen(self, nr):
        self._pruefen("oeffnen")
        if self.fehler:
            return self.fehler
        for e in self.eintraege:
            if e["nr"] == nr and e["status"] == "verworfen":
                e["status"] = "offen"
                return None
        return sa.SATZ_NICHT_GEFUNDEN


# ---------------------------------------------------------------- Modul: Form und Bereinigung
class FormTests(unittest.TestCase):
    def test_gueltiger_auftrag_bleibt_wie_er_ist(self):
        a = sa.auftrag_pruefen(auftrag())
        self.assertEqual((a.titel, a.art, a.prioritaet, a.abnahme, a.quelle, a.unsicher),
                         ("Mikrofon im Log", "umsetzung", 1, ("Eine Zeile im Log",), "sprache", False))

    def test_schluessel_in_titel_beschreibung_und_kriterien_werden_ersetzt(self):
        a = sa.auftrag_pruefen(auftrag(titel=f"Nutze {SCHLUESSEL}", beschreibung=f"Der Schlüssel {SCHLUESSEL} gehört nicht hierher",
                                       abnahme=(f"Kein {SCHLUESSEL}",)))
        for text in (a.titel, a.beschreibung, *a.abnahme):
            self.assertNotIn("GEHEIMselbst", text)

    def test_titel_wird_auf_80_zeichen_gekuerzt_und_bleibt_eine_zeile(self):
        a = sa.auftrag_pruefen(auftrag(titel="T" * 200))
        self.assertEqual(len(a.titel), sa.TITEL_ZEICHEN)
        self.assertEqual(sa.auftrag_pruefen(auftrag(titel="Zwei\nZeilen  hier")).titel, "Zwei Zeilen hier")

    def test_beschreibung_wird_auf_4000_gekuerzt(self):
        self.assertEqual(len(sa.auftrag_pruefen(auftrag(beschreibung="b" * 5000)).beschreibung), sa.BESCHREIBUNG_ZEICHEN)

    def test_ungueltige_angaben_werfen(self):
        for name, extra in (("Titel", {"titel": "  "}), ("Titel", {"titel": 5}), ("Beschreibung", {"beschreibung": ""}),
                            ("Art", {"art": "Umsetzung"}), ("Art", {"art": ""}), ("Priorität", {"prioritaet": 0}),
                            ("Priorität", {"prioritaet": 4}), ("Priorität", {"prioritaet": True}), ("Priorität", {"prioritaet": "2"}),
                            ("Quelle", {"quelle": "mail"}), ("unsicher", {"unsicher": 1}), ("Abnahme", {"abnahme": ("a",) * 6}),
                            ("Abnahme", {"abnahme": "text"}), ("Kriterium", {"abnahme": ("",)}), ("Kriterium", {"abnahme": (5,)}),
                            ("Kriterium", {"abnahme": ("k" * 301,)})):
            with self.subTest(name=name, extra=extra):
                with self.assertRaises(ValueError) as e:
                    sa.auftrag_pruefen(auftrag(**extra))
                self.assertEqual(str(e.exception), name)

    def test_eintrag_aus_einer_gueltigen_zeile(self):
        e = sa.eintrag(zeile(bearbeiter="claude_code", ergebnis="Pull Request 12", status="in_arbeit", unsicher=True))
        self.assertEqual(e, {"nr": 7, "titel": "Mikrofon im Log", "art": "umsetzung", "prioritaet": 2, "status": "in_arbeit",
                             "quelle": "sprache", "unsicher": True, "erstellt_ms": int(ZEIT.timestamp() * 1000),
                             "bearbeiter": "claude_code", "ergebnis": "Pull Request 12"})

    def test_eintrag_ohne_bearbeiter_und_ergebnis_hat_beide_felder_nicht(self):
        e = sa.eintrag(zeile())
        self.assertNotIn("bearbeiter", e)
        self.assertNotIn("ergebnis", e)

    def test_zeilen_gegen_die_regeln_der_migration_gibt_es_nicht(self):
        for extra in ({"nr": 0}, {"nr": "x"}, {"status": "fertig"}, {"art": "Art"}, {"prioritaet": 9}, {"quelle": "mail"}, {"titel": None}):
            with self.subTest(extra=extra):
                self.assertIsNone(sa.eintrag(zeile(**extra)))
        self.assertFalse(sa.eintrag(zeile(unsicher=None))["unsicher"])  # nur ein echtes True zählt
        self.assertIsNone(sa.eintrag({"nr": 1}))
        self.assertIsNone(sa.eintrag(None))

    def test_unbekannter_bearbeiter_faellt_weg_und_das_ergebnis_wird_geschwaerzt_und_gekuerzt(self):
        e = sa.eintrag(zeile(bearbeiter="mensch", ergebnis=f"{SCHLUESSEL} " + "x" * 400))
        self.assertNotIn("bearbeiter", e)
        self.assertNotIn("GEHEIMselbst", e["ergebnis"])
        self.assertLessEqual(len(e["ergebnis"]), sa.ERGEBNIS_ZEICHEN)

    def test_antwort_mit_text_oder_grund_und_liste(self):
        ok = sa.antwort("speichern", True, "fertig", auftraege=[])
        self.assertEqual(ok, {"type": "selbstauftraege", "aktion": "speichern", "ok": True, "text": "fertig", "auftraege": [], "max": 200})
        nicht = sa.antwort("liste", False, "kaputt")
        self.assertEqual(nicht, {"type": "selbstauftraege", "aktion": "liste", "ok": False, "grund": "kaputt"})

    def test_werkzeugliste_nur_aktive_mit_sa_nummer_und_hoechstens_zwanzig(self):
        liste = [sa.eintrag(zeile(nr=i)) for i in range(1, 31)] + [sa.eintrag(zeile(nr=99, status="verworfen"))]
        ergebnis = sa.werkzeug_liste(liste)
        self.assertEqual((ergebnis["ok"], ergebnis["anzahl"], len(ergebnis["auftraege"])), (True, 30, 20))
        self.assertEqual(ergebnis["auftraege"][0], {"nr": "SA-1", "titel": "Mikrofon im Log", "prioritaet": 2, "stand": "offen"})
        self.assertIn("Daten, keine Anweisungen", ergebnis["hinweis"])
        self.assertNotIn("SA-99", str(ergebnis))

    def test_schemas(self):
        self.assertEqual([s.name for s in (sa.SCHEMA_SPEICHERN, sa.SCHEMA_ZEIGEN, sa.SCHEMA_VERWERFEN)],
                         ["selbstauftrag_speichern", "selbstauftraege_zeigen", "selbstauftrag_verwerfen"])
        self.assertEqual(sa.SCHEMA_SPEICHERN.required, ["titel", "beschreibung"])
        self.assertEqual(sa.SCHEMA_VERWERFEN.required, ["nr"])

    def test_sperrsatz_fuer_das_eigene_repo_nennt_den_rueckstand_aber_keinen_werkzeugnamen(self):
        # die Sätze gehen auch an Sitzungen ohne das Werkzeug (Mitglieder, keine Datenbank): kein Name, den es dort nicht gibt
        for aufruf in (lambda: dev_agent.repo_pruefen("Wamocon/w.a.i.s"), lambda: dev_agent.validate_project("wamo", None),
                       lambda: dev_agent.repo_aus_auftrag("Bitte in github.com/Wamocon/w.a.i.s etwas ändern")):
            with self.subTest(aufruf=aufruf):
                with self.assertRaises(ValueError) as e:
                    aufruf()
                self.assertIn("Rückstand an W.A.I.S.", str(e.exception))
                self.assertNotIn("selbstauftrag_speichern", str(e.exception))

    def test_beschreibung_ohne_unsichtbare_und_steuerzeichen_zeilen_bleiben_zeilen(self):
        # Unicode-Tag-Zeichen (U+E0041), Bidi-Umschalter (U+202E), ESC, CR, Nullbreitenzeichen (Befund der Prüfung vom 19.11.2026): Ein Agent
        # liest den Text später, was kein Mensch sieht, darf darin nicht stehen
        roh = "Erste Zeile\r\nZweite\x1b[31m Zeile‮ gespiegelt​\nDritte \U000e0041\U000e0042 Zeile Vierte"
        text = sa.auftrag_pruefen(auftrag(beschreibung=roh)).beschreibung
        self.assertEqual(text.splitlines(), ["Erste Zeile", "Zweite [31m Zeile  gespiegelt", "Dritte    Zeile", "Vierte"])
        for zeichen in ("\r", "\x1b", "‮", "​", "\U000e0041", " "):
            self.assertNotIn(zeichen, text)

    def test_beschreibung_behaelt_leerzeilen_aber_nicht_die_raender(self):
        text = sa.auftrag_pruefen(auftrag(beschreibung="\n\nAbsatz eins\n\nAbsatz zwei  \n\n")).beschreibung
        self.assertEqual(text, "Absatz eins\n\nAbsatz zwei")

    def test_beschreibung_nur_aus_unsichtbarem_ist_leer_und_ungueltig(self):
        with self.assertRaises(ValueError):
            sa.auftrag_pruefen(auftrag(beschreibung="​‮\x1b \U000e0041"))


# ---------------------------------------------------------------- Modul: Datenbank
class DatenbankTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDb()
        self.db.wert = 7
        self.speicher = sa.DatenbankSelbstauftraege(self.db, NIKO)

    async def test_speichern_liefert_die_nummer_und_bindet_an_das_profil(self):
        self.assertEqual(await self.speicher.speichern(auftrag()), (7, None))
        art, sql, args = self.db.aufrufe[-1]
        self.assertEqual(art, "fetchval")
        self.assertTrue(sql.startswith("insert into wamo_test.selbstauftraege "))
        self.assertIn("returning nr", sql)
        self.assertEqual(args[0:3], ("Mikrofon im Log", "Die Mikrofonvorgaben in den Kern-Log schreiben.", "umsetzung"))
        self.assertIn('"Eine Zeile im Log"', args[3])  # Kriterien als JSON-Liste
        self.assertEqual(args[4:], (1, "sprache", False, NIKO))

    async def test_der_kern_setzt_nie_status_nummer_oder_bearbeiter(self):
        await self.speicher.speichern(auftrag())
        spalten = self.db.aufrufe[-1][1].split("(", 1)[1].split(")", 1)[0]
        self.assertEqual([s.strip() for s in spalten.split(",")],
                         ["titel", "beschreibung", "art", "abnahme", "prioritaet", "quelle", "unsicher", "erstellt_von"])

    async def test_zu_viele_heute_ergibt_den_satz(self):
        self.db.wert = None  # die Bedingung "weniger als 30 am Tag" griff
        self.assertEqual(await self.speicher.speichern(auftrag()), (None, sa.SATZ_ZU_OFT))

    async def test_grenze_des_triggers_ergibt_voll(self):
        import asyncpg

        fehler = asyncpg.CheckViolationError("selbstauftraege: höchstens 200 offene Aufträge")
        fehler.constraint_name = sa.GRENZE_TRIGGER
        self.db.fehler = fehler
        self.assertEqual(await self.speicher.speichern(auftrag()), (None, sa.SATZ_VOLL))

    async def test_ein_anderer_datenbankfehler_ergibt_den_satz_ohne_text_aus_der_anfrage(self):
        import asyncpg

        self.db.fehler = asyncpg.PostgresError(f"geheim {SCHLUESSEL}")
        with mock.patch.object(sa.logger, "warning") as warnung:
            self.assertEqual(await self.speicher.speichern(auftrag()), (None, sa.SATZ_DATENBANK))
        self.assertNotIn("GEHEIMselbst", str(warnung.call_args_list))

    async def test_ungueltiges_erreicht_die_datenbank_nie(self):
        self.assertEqual(await self.speicher.speichern(auftrag(titel="")), (None, sa.SATZ_UNGUELTIG))
        self.assertEqual(self.db.aufrufe, [])

    async def test_ohne_profil_gibt_es_keinen_speicher(self):
        speicher = sa.DatenbankSelbstauftraege(self.db, None)
        self.assertEqual(await speicher.speichern(auftrag()), (None, sa.SATZ_OHNE_SPEICHER))
        self.assertEqual(await speicher.verwerfen(1), sa.SATZ_OHNE_SPEICHER)
        self.assertEqual(self.db.aufrufe, [])

    async def test_liste_aktive_nach_prioritaet_und_nummer_dann_abgeschlossene_neueste_zuerst(self):
        spaeter = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.db.zeilen = [zeile(nr=5, status="erledigt", bearbeiter="claude_code", geaendert_at=ZEIT),
                          zeile(nr=4, prioritaet=3), zeile(nr=3, prioritaet=1), zeile(nr=6, status="verworfen", geaendert_at=spaeter),
                          zeile(nr=2, prioritaet=1, status="in_arbeit", bearbeiter="wais"), zeile(nr=99, status="kaputt")]
        liste, grund = await self.speicher.liste()
        self.assertIsNone(grund)
        self.assertEqual([e["nr"] for e in liste], [2, 3, 4, 6, 5])  # die ungültige Zeile 99 fehlt
        sql = self.db.aufrufe[-1][1]
        self.assertTrue(sql.startswith("select nr, titel,"))
        self.assertNotIn("beschreibung", sql)  # nie der ganze Text in der Liste
        self.assertIn("limit 10", sql)  # nur die zuletzt abgeschlossenen

    async def test_liste_bei_datenbankfehler(self):
        import asyncpg

        self.db.fehler = asyncpg.PostgresError("weg")
        self.assertEqual(await self.speicher.liste(), (None, sa.SATZ_DATENBANK))

    async def test_verwerfen_und_oeffnen_rufen_nur_die_funktionen_der_datenbank_auf(self):
        # der Kern hat kein update auf der Tabelle (Migration 0030): den Stand ändern allein diese zwei Funktionen mit festen Übergängen
        self.db.wert = 7
        self.assertIsNone(await self.speicher.verwerfen(7))
        art, sql, args = self.db.aufrufe[-1]
        self.assertEqual((art, sql, args), ("fetchval", "select wamo_test.selbstauftrag_verwerfen($1::bigint) as nr", (7,)))
        self.assertIsNone(await self.speicher.oeffnen(7))
        self.assertEqual(self.db.aufrufe[-1][1], "select wamo_test.selbstauftrag_oeffnen($1::bigint) as nr")
        for _, sql, _ in self.db.aufrufe:
            self.assertNotIn("update", sql.lower())

    async def test_verwerfen_ohne_treffer_heisst_nicht_gefunden(self):
        self.db.wert = None  # die Funktion findet keine Zeile in einem passenden Stand (null)
        self.assertEqual(await self.speicher.verwerfen(7), sa.SATZ_NICHT_GEFUNDEN)
        self.assertEqual(await self.speicher.oeffnen(7), sa.SATZ_NICHT_GEFUNDEN)

    async def test_wieder_oeffnen_ueber_der_grenze_von_200_ergibt_voll(self):
        import asyncpg

        fehler = asyncpg.CheckViolationError("selbstauftraege: höchstens 200 offene Aufträge")
        fehler.constraint_name = sa.GRENZE_TRIGGER  # der Trigger der Statusübergänge nennt dieselbe Grenze wie der des Einfügens
        self.db.fehler = fehler
        self.assertEqual(await self.speicher.oeffnen(7), sa.SATZ_VOLL)
        self.assertEqual(await self.speicher.verwerfen(7), sa.SATZ_VOLL)  # derselbe Weg, nie ein anderer Satz für denselben Fehler

    async def test_ungueltige_nummern_erreichen_die_datenbank_nie(self):
        for nr in (0, -1, "7", 7.0, True, None, 2**63, 2**62 + 1):
            with self.subTest(nr=nr):
                self.assertEqual(await self.speicher.verwerfen(nr), sa.SATZ_NICHT_GEFUNDEN)
        self.assertEqual(self.db.aufrufe, [])

    async def test_datenbankfehler_beim_status(self):
        import asyncpg

        self.db.fehler = asyncpg.PostgresError("weg")
        self.assertEqual(await self.speicher.verwerfen(7), sa.SATZ_DATENBANK)


class StandardSpeicherTests(unittest.TestCase):
    def test_ohne_datenbank_gibt_es_keinen_speicher(self):
        self.assertIsNone(sa.fuer(type("M", (), {"enabled": False})()))
        self.assertIsNone(sa.fuer(object()))

    def test_mit_datenbank_der_speicher_dieses_profils(self):
        memory = type("M", (), {"enabled": True, "user_id": NIKO, "db": FakeDb()})()
        self.assertIsInstance(sa.fuer(memory), sa.DatenbankSelbstauftraege)

    def test_devagent_baut_den_speicher_aus_dem_gedaechtnis(self):
        memory = type("M", (), {"enabled": True, "user_id": NIKO, "db": FakeDb()})()
        with mock.patch.dict(os.environ, {"WAMO_BETRIEB": ""}):
            agent = dev_agent.DevAgent(memory=memory, auftraggeber="Niko")
        self.assertIsInstance(agent._selbst, sa.DatenbankSelbstauftraege)


# ---------------------------------------------------------------- DevAgent außerhalb des Büros (nur Admins haben dort einen)
class AgentFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = mock.patch.dict(os.environ, {"WAMO_BETRIEB": "", "WAMO_ENTWICKLUNG_ORT": "sokrates2"})
        self.env.start()
        self.selbst = FakeSelbst()
        self.memory = tb.AuditMemory()
        self.agent = dev_agent.DevAgent(memory=self.memory, auftraggeber="Niko", beurteiler=lambda *a: None, selbst=self.selbst)
        self.task = FakeTask()
        self.agent.attach(self.task)
        self.fremd = False
        self.agent.ist_fremd = lambda: self.fremd
        self.tainted: list[bool] = []
        self.agent.on_result = lambda: self.tainted.append(True)

    async def asyncTearDown(self):
        self.env.stop()

    def antworten(self):
        return [m for m in self.task.messages() if m.get("type") == "selbstauftraege"]

    async def klick(self, agent=None, **data):
        await (agent or self.agent).on_client_message("selbstauftrag", data)
        return self.antworten()[-1]


class NachrichtTests(AgentFlow):
    async def test_liste_ohne_eintraege(self):
        antwort = await self.klick(aktion="liste")
        self.assertEqual((antwort["ok"], antwort["auftraege"], antwort["max"]), (True, [], 200))

    async def test_speichern_aus_der_oberflaeche_ist_nicht_unsicher_und_bekommt_die_standards(self):
        antwort = await self.klick(aktion="speichern", titel="Neuer Titel", beschreibung="Eine Beschreibung")
        self.assertEqual((antwort["ok"], antwort["text"]), (True, sa.SATZ_GESPEICHERT))
        self.assertEqual([e["titel"] for e in antwort["auftraege"]], ["Neuer Titel"])
        a = self.selbst.gespeichert[0]
        self.assertEqual((a.art, a.prioritaet, a.quelle, a.unsicher), ("umsetzung", 2, "oberflaeche", False))

    async def test_speichern_aus_der_oberflaeche_auch_nach_fremdinhalt_nicht_unsicher(self):
        self.fremd = True  # der Klick ist die Person selbst, kein Text aus dem Gespräch
        await self.klick(aktion="speichern", titel="T", beschreibung="B")
        self.assertFalse(self.selbst.gespeichert[0].unsicher)

    async def test_speichern_mit_art_prioritaet_und_kriterien(self):
        await self.klick(aktion="speichern", titel="T", beschreibung="B", art="fehlerbehebung", prioritaet=1, abnahme=["a", "b"])
        a = self.selbst.gespeichert[0]
        self.assertEqual((a.art, a.prioritaet, a.abnahme), ("fehlerbehebung", 1, ("a", "b")))

    async def test_unbekannte_art_und_ungueltige_prioritaet_sind_ungueltig(self):
        for extra in ({"art": "zauberei"}, {"prioritaet": 7}, {"prioritaet": "hoch"}, {"titel": ""}):
            with self.subTest(extra=extra):
                daten = {"titel": "T", "beschreibung": "B", **extra}
                antwort = await self.klick(aktion="speichern", **daten)
                self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_UNGUELTIG))
        self.assertEqual(self.selbst.gespeichert, [])

    async def test_verwerfen_und_wieder_oeffnen(self):
        await self.klick(aktion="speichern", titel="T", beschreibung="B")
        antwort = await self.klick(aktion="verwerfen", nr=1)
        self.assertEqual((antwort["ok"], antwort["text"], antwort["auftraege"][0]["status"]), (True, sa.SATZ_VERWORFEN, "verworfen"))
        antwort = await self.klick(aktion="oeffnen", nr=1)
        self.assertEqual((antwort["ok"], antwort["auftraege"][0]["status"]), (True, "offen"))

    async def test_unbekannter_auftrag_ist_ein_fehler_mit_grund(self):
        antwort = await self.klick(aktion="verwerfen", nr=42)
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_NICHT_GEFUNDEN))
        self.assertNotIn("auftraege", antwort)

    async def test_unbekannte_aktion_oder_form_bleibt_ohne_antwort(self):
        for daten in ({"aktion": "loeschen", "nr": 1}, {"aktion": None}, {}):
            await self.agent.on_client_message("selbstauftrag", daten)
        await self.agent.on_client_message("selbstauftrag", "kaputt")  # type: ignore[arg-type]
        self.assertEqual(self.antworten(), [])

    async def test_datenbankfehler_kommt_als_grund_zurueck(self):
        self.selbst.fehler = sa.SATZ_DATENBANK
        for daten in ({"aktion": "liste"}, {"aktion": "speichern", "titel": "T", "beschreibung": "B"}, {"aktion": "verwerfen", "nr": 1}):
            with self.subTest(daten=daten):
                antwort = await self.klick(**daten)
                self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_DATENBANK))

    async def test_eine_ausnahme_im_speicher_erreicht_das_gespraech_nie(self):
        self.selbst.wirft = RuntimeError(f"geheim {SCHLUESSEL}")
        antwort = await self.klick(aktion="liste")
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_INTERN))
        self.assertNotIn("GEHEIMselbst", str(antwort))

    async def test_gescheiterte_antwort_landet_im_fehlerbuch(self):
        antwort = await self.klick(aktion="verwerfen", nr=42)
        buch = fehlerbuch.Fehlerbuch()
        self.assertTrue(buch.aus_meldung(antwort))


class WerkzeugTests(AgentFlow):
    async def test_schemas_und_registrierung(self):
        namen = [s.name for s in self.agent.schemas()]
        for n in ("selbstauftrag_speichern", "selbstauftraege_zeigen", "selbstauftrag_verwerfen"):
            self.assertIn(n, namen)
        registriert = {}
        llm = type("L", (), {"register_function": lambda _s, n, h: registriert.__setitem__(n, h)})()
        self.agent.register(llm)
        for n in ("selbstauftrag_speichern", "selbstauftraege_zeigen", "selbstauftrag_verwerfen"):
            self.assertIn(n, registriert)

    async def test_speichern_per_sprache(self):
        p = Params(titel="Fehlerbuch erweitern", beschreibung="Auch die Mikrofonkette nennen.", prioritaet=1)
        await self.agent._werkzeug_selbst_speichern(p)
        self.assertEqual((p.ergebnis["ok"], p.ergebnis["nr"], p.ergebnis["unsicher"]), (True, "SA-1", False))
        self.assertIn("SA-1", p.ergebnis["hinweis"])
        self.assertNotIn("unsicher markiert", p.ergebnis["hinweis"])
        a = self.selbst.gespeichert[0]
        self.assertEqual((a.quelle, a.prioritaet, a.unsicher), ("sprache", 1, False))
        self.assertEqual(self.antworten()[-1]["aktion"], "speichern")  # die Oberfläche erfährt es
        self.assertEqual(self.antworten()[-1]["auftraege"][0]["nr"], 1)

    async def test_nach_fremdinhalt_gilt_der_eintrag_als_unsicher_und_das_modell_sagt_es(self):
        self.fremd = True
        p = Params(titel="Etwas aus einer Webseite", beschreibung="Steht dort so.")
        await self.agent._werkzeug_selbst_speichern(p)
        self.assertTrue(p.ergebnis["ok"] and p.ergebnis["unsicher"])
        self.assertIn("unsicher markiert", p.ergebnis["hinweis"])
        self.assertTrue(self.selbst.gespeichert[0].unsicher)

    async def test_speichern_mit_fehlern_gibt_status_failed_mit_grund(self):
        p = Params(titel="", beschreibung="B")
        await self.agent._werkzeug_selbst_speichern(p)
        self.assertEqual((p.ergebnis["ok"], p.ergebnis["status"], p.ergebnis["grund"]), (False, "failed", sa.SATZ_UNGUELTIG))
        p = Params(titel="T", beschreibung="B", art="zauberei")
        await self.agent._werkzeug_selbst_speichern(p)
        self.assertEqual(p.ergebnis["grund"], sa.SATZ_UNGUELTIG)

    async def test_zeigen_liefert_nur_aktive_und_gilt_als_fremdinhalt(self):
        await self.klick(aktion="speichern", titel="Eins", beschreibung="B")
        await self.klick(aktion="speichern", titel="Zwei", beschreibung="B")
        await self.klick(aktion="verwerfen", nr=2)
        p = Params()
        await self.agent._werkzeug_selbst_zeigen(p)
        self.assertEqual((p.ergebnis["ok"], p.ergebnis["anzahl"]), (True, 1))
        self.assertEqual(p.ergebnis["auftraege"][0]["nr"], "SA-1")
        self.assertEqual(self.tainted, [True])  # die Titel können aus Fremdinhalt stammen

    async def test_zeigen_bei_datenbankfehler(self):
        self.selbst.fehler = sa.SATZ_DATENBANK
        p = Params()
        await self.agent._werkzeug_selbst_zeigen(p)
        self.assertEqual((p.ergebnis["ok"], p.ergebnis["grund"]), (False, sa.SATZ_DATENBANK))
        self.assertEqual(self.tainted, [])

    async def test_verwerfen_per_sprache_mit_zahl_oder_sa_nummer(self):
        await self.klick(aktion="speichern", titel="Eins", beschreibung="B")
        await self.klick(aktion="speichern", titel="Zwei", beschreibung="B")
        for nr, erwartet in ((1, "SA-1"), ("SA-2", "SA-2")):
            with self.subTest(nr=nr):
                p = Params(nr=nr)
                await self.agent._werkzeug_selbst_verwerfen(p)
                self.assertEqual((p.ergebnis["ok"], p.ergebnis["nr"]), (True, erwartet))
        self.assertEqual([e["status"] for e in self.selbst.eintraege], ["verworfen", "verworfen"])

    async def test_verwerfen_mit_unbrauchbarer_nummer(self):
        for nr in ("irgendwas", "", None, True, "SA-", "²", "SA-²", "٣", "1" * 19, "7; drop"):  # nur ASCII-Ziffern: "²".isdigit() ist wahr
            with self.subTest(nr=nr):
                p = Params(nr=nr)
                await self.agent._werkzeug_selbst_verwerfen(p)
                self.assertEqual((p.ergebnis["ok"], p.ergebnis["grund"]), (False, sa.SATZ_NICHT_GEFUNDEN))
        self.assertNotIn("verwerfen", self.selbst.aufrufe)

    async def test_eine_ausnahme_erreicht_das_gespraech_nie(self):
        self.selbst.wirft = RuntimeError("kaputt")
        for werkzeug, p in ((self.agent._werkzeug_selbst_speichern, Params(titel="T", beschreibung="B")),
                            (self.agent._werkzeug_selbst_zeigen, Params()), (self.agent._werkzeug_selbst_verwerfen, Params(nr=1))):
            await werkzeug(p)
            self.assertEqual((p.ergebnis["ok"], p.ergebnis["grund"]), (False, sa.SATZ_INTERN))


class FremdinhaltVerdrahtungTests(unittest.TestCase):
    """Befund der Prüfung vom 19.11.2026: turn.tainted gilt nur für den Zug mit Fremdinhalt. Eine Webseite im Zug 1, die Frage "Soll ich das
    speichern?" und das Ja der Person im Zug 2 ergäben einen Eintrag, der nicht als unsicher gilt. Der Bot nutzt deshalb fremd_fuer_karte(None)
    (Fremdinhalt im Zug oder nachwirkend bis zum Ende der Sitzung)."""

    def test_der_bot_haengt_fremd_fuer_karte_ein_nicht_tainted(self):
        quelle = (Path(__file__).with_name("bot.py")).read_text(encoding="utf-8")
        self.assertIn("dev.ist_fremd = lambda: turn.fremd_fuer_karte(None)", quelle)
        self.assertNotIn("dev.ist_fremd = lambda: turn.tainted", quelle)

    def test_ein_neuer_zug_nach_einer_nachwirkenden_fremdquelle_gilt_weiter_als_fremd(self):
        from tools import TurnState

        turn = TurnState()
        turn.new_user_turn("Lies diese Webseite")
        turn.taint()  # nachwirkend: Websuche, Bildschirm, Ergebnis vom Laptop
        self.assertTrue(turn.tainted and turn.fremd_fuer_karte(None))
        turn.new_user_turn("Ja, speichere das")  # der nächste Zug: tainted ist zurückgesetzt, die Nachwirkung bleibt
        self.assertFalse(turn.tainted)
        self.assertTrue(turn.fremd_fuer_karte(None))

    def test_ohne_fremdinhalt_gilt_der_zug_nie_als_fremd(self):
        from tools import TurnState

        turn = TurnState()
        turn.new_user_turn("Speichere das als Auftrag")
        self.assertFalse(turn.fremd_fuer_karte(None))


class OhneSpeicherTests(unittest.IsolatedAsyncioTestCase):
    async def test_ohne_datenbank_gibt_es_weder_werkzeuge_noch_antworten(self):
        with mock.patch.dict(os.environ, {"WAMO_BETRIEB": ""}):
            agent = dev_agent.DevAgent(memory=tb.AuditMemory(), auftraggeber="Niko")
        self.assertIsNone(agent._selbst)
        self.assertFalse(agent.selbst_aktiv())
        self.assertFalse({"selbstauftrag_speichern", "selbstauftraege_zeigen", "selbstauftrag_verwerfen"} & {s.name for s in agent.schemas()})
        task = FakeTask()
        agent.attach(task)
        await agent.on_client_message("selbstauftrag", {"aktion": "liste"})
        antwort = [m for m in task.messages() if m.get("type") == "selbstauftraege"][-1]
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_OHNE_SPEICHER))


# ---------------------------------------------------------------- Büro: nur Admins mit Zulassung
class BueroTests(tb.BueroFlow):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.selbst = FakeSelbst()
        self.agent._selbst = self.selbst

    def antworten(self):
        return [m for m in self.task.messages() if m.get("type") == "selbstauftraege"]

    async def klick(self, agent=None, **data):
        await (agent or self.agent).on_client_message("selbstauftrag", data)
        return self.antworten()[-1]

    async def test_admin_im_buero_hat_werkzeuge_und_nachricht(self):
        self.assertTrue(self.agent.selbst_aktiv())
        self.assertIn("selbstauftrag_speichern", [s.name for s in self.agent.schemas()])
        self.assertTrue((await self.klick(aktion="liste"))["ok"])

    async def test_ohne_zulassung_geht_keine_aktion(self):
        agent = self.ohne_zulassung()
        agent._selbst = self.selbst
        for daten in ({"aktion": "liste"}, {"aktion": "speichern", "titel": "T", "beschreibung": "B"}, {"aktion": "verwerfen", "nr": 1},
                      {"aktion": "oeffnen", "nr": 1}):
            with self.subTest(daten=daten):
                antwort = await self.klick(agent, **daten)
                self.assertEqual((antwort["ok"], antwort["grund"]), (False, eb.SATZ_KEINE_ZULASSUNG))
        self.assertEqual(self.selbst.aufrufe, [])

    async def test_mitglieder_haben_weder_werkzeuge_noch_nachricht(self):
        with tb.buero(WAMO_ENTWICKLUNG_MITGLIEDER="an"):
            agent = dev_agent.DevAgent(memory=self.memory, auftraggeber="Erika", zulassung=eb.BueroZulassung(NIKO, mitglied=True),
                                       selbst=self.selbst)
            agent.attach(self.task)
            self.assertFalse(agent.selbst_aktiv())
            self.assertFalse({"selbstauftrag_speichern", "selbstauftraege_zeigen", "selbstauftrag_verwerfen"}
                             & {s.name for s in agent.schemas()})
            for daten in ({"aktion": "liste"}, {"aktion": "speichern", "titel": "T", "beschreibung": "B"}):
                with self.subTest(daten=daten):
                    antwort = await self.klick(agent, **daten)
                    self.assertEqual((antwort["ok"], antwort["grund"]), (False, sa.SATZ_NUR_ADMIN))
            p = Params(titel="T", beschreibung="B")
            await agent._werkzeug_selbst_speichern(p)
            self.assertEqual((p.ergebnis["ok"], p.ergebnis["grund"]), (False, sa.SATZ_NUR_ADMIN))
        self.assertEqual(self.selbst.aufrufe, [])
