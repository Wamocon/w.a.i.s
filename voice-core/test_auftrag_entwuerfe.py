"""Entwicklungsaufträge für später speichern (auftrag_entwuerfe.py und die Einhängepunkte in dev_agent.py).

Geprüft wird: was gespeichert wird (nur Projekt, Art, Repo, Auftragstext, Kriterien, Runden, Zeitlimit; nie ein Zugangswert, Schlüssel
geschwärzt), dass Speichern nur für eine noch nicht gestartete Karte geht, dass Laden dieselben Prüfungen durchläuft wie
entwicklung_vorbereiten und nur eine Karte anlegt (Start bleibt ein Klick), dass jede Anfrage nur das eigene Profil trifft, dass Fehler mit
ok false und einem Satz als grund zurückkommen (Fehlerbuch) und dass die beiden Werkzeuge dem Stimm-Gate unterliegen.
Alle Tests laufen ohne Netz und ohne Datenbank (Attrappen).

Ausführen:  python -m pytest -q test_auftrag_entwuerfe.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import asyncio
import base64
import os
import unittest
from pathlib import PurePosixPath
from unittest import mock

import abnahme
import auftrag_entwuerfe as ae
import dev_agent
import entwicklung_betrieb as eb
import fehlerbuch
import stimme_gate
import test_entwicklung_betrieb as tb
from test_dev_agent_sokrates2 import FakeTask

NIKO = tb.NIKO
ANDERE = tb.ANDERE
SCHLUESSEL = "sk-ant-api03-" + "GEHEIMentwurf" * 4
ID1 = "11111111-2222-4333-8444-555555555555"


# ---------------------------------------------------------------- Attrappen
class FakeSpeicher:
    """Speicher im Speicher, mit derselben Schnittstelle wie DatenbankEntwuerfe. user_id ist die der Sitzung."""

    def __init__(self, user_id=NIKO):
        self.user_id = user_id
        self.zeilen: dict[str, tuple[str, ae.Entwurf, int]] = {}  # id -> (user_id, entwurf, gespeichert_ms)
        self.fehler: str | None = None  # Satz, mit dem jede Anfrage scheitert (Datenbank weg)
        self.aufrufe: list[str] = []
        self._n = 0

    async def speichern(self, entwurf):
        self.aufrufe.append("speichern")
        if self.fehler:
            return None, self.fehler
        if sum(1 for u, _, _ in self.zeilen.values() if u == self.user_id) >= ae.MAX_JE_PERSON:
            return None, ae.SATZ_VOLL
        self._n += 1
        kennung = f"00000000-0000-4000-8000-{self._n:012d}"
        self.zeilen[kennung] = (self.user_id, entwurf, 1_763_000_000_000 + self._n)
        return kennung, None

    async def liste(self):
        self.aufrufe.append("liste")
        if self.fehler:
            return None, self.fehler
        eigene = [(k, e, ms) for k, (u, e, ms) in self.zeilen.items() if u == self.user_id]
        return [ae.eintrag(k, e.projekt, e.art, e.repo, e.auftrag, ms) for k, e, ms in reversed(eigene)], None

    async def holen(self, entwurf_id):
        self.aufrufe.append("holen")
        if self.fehler:
            return None, self.fehler
        zeile = self.zeilen.get(entwurf_id)
        if zeile is None or zeile[0] != self.user_id:
            return None, ae.SATZ_NICHT_GEFUNDEN
        return zeile[1], None

    async def loeschen(self, entwurf_id):
        self.aufrufe.append("loeschen")
        if self.fehler:
            return False, self.fehler
        zeile = self.zeilen.get(entwurf_id)
        if zeile is None or zeile[0] != self.user_id:
            return False, ae.SATZ_NICHT_GEFUNDEN
        del self.zeilen[entwurf_id]
        return True, None


class FakeDb:
    """Database-Attrappe: merkt SQL und Argumente, liefert vorgegebene Antworten oder wirft."""

    def __init__(self):
        self.aufrufe: list[tuple[str, str, tuple]] = []
        self.wert: object = ID1
        self.zeilen: list[dict] = []
        self.zeile: dict | None = None
        self.status = "DELETE 1"
        self.fehler: BaseException | None = None

    def t(self, name):
        return f"wamo_test.{name}"

    async def _rufen(self, art, sql, args, antwort):
        self.aufrufe.append((art, sql, args))
        if self.fehler is not None:
            raise self.fehler
        return antwort

    async def fetchval(self, sql, *args):
        return await self._rufen("fetchval", sql, args, self.wert)

    async def fetch(self, sql, *args):
        return await self._rufen("fetch", sql, args, self.zeilen)

    async def fetchrow(self, sql, *args):
        return await self._rufen("fetchrow", sql, args, self.zeile)

    async def execute(self, sql, *args):
        return await self._rufen("execute", sql, args, self.status)


class Params:
    def __init__(self, **arguments):
        self.arguments = arguments
        self.ergebnis: dict | None = None
        self.function_name = "test"

    async def result_callback(self, r):
        self.ergebnis = r


def entwurf(**extra) -> ae.Entwurf:
    werte = {"projekt": "rezepte-app", "art": "umsetzung", "auftrag": "Baue die Rezepte-App", "repo": "acme/rezepte-app",
             "abnahme": ("Die README erklärt die Installation",), "max_runden": 4, "zeitlimit_min": 20}
    werte.update(extra)
    return ae.Entwurf(**werte)


# ---------------------------------------------------------------- Modul: Form und Bereinigung
class EntwurfFormTests(unittest.TestCase):
    def test_grenzen_passen_zum_kern(self):
        self.assertEqual(ae.AUFTRAG_ZEICHEN, dev_agent.MAX_TASK_CHARS)
        self.assertEqual(ae.KRITERIEN_MAX, abnahme.MAX_KRITERIEN)
        self.assertEqual(ae.KRITERIUM_ZEICHEN, abnahme.KRITERIUM_ZEICHEN)
        self.assertEqual(ae.RUNDEN_MAX, dev_agent.RUNDEN_MAX)
        self.assertEqual(ae.ZEITLIMIT_MAX_MIN, dev_agent.ZEITLIMIT_MAX_MIN)
        self.assertEqual(ae.PROJEKT_RE.pattern, dev_agent.PROJECT_NAME.pattern)
        self.assertEqual(ae.REPO_RE.pattern, dev_agent.REPO_RE.pattern)
        self.assertEqual(ae.MAX_JE_PERSON, 50)
        self.assertEqual(ae.AUFBEWAHRUNG_TAGE, 90)

    def test_gueltiger_entwurf_bleibt_unveraendert(self):
        e = entwurf()
        self.assertEqual(ae.entwurf_pruefen(e), e)

    def test_schluessel_im_text_und_in_kriterien_werden_geschwaerzt(self):
        e = ae.entwurf_pruefen(entwurf(auftrag=f"Nutze {SCHLUESSEL} für die Tests", abnahme=(f"Kein {SCHLUESSEL} im Log",)))
        self.assertNotIn("GEHEIM", e.auftrag)
        self.assertNotIn("GEHEIM", " ".join(e.abnahme))
        self.assertIn("sk-ant-…", e.auftrag)

    def test_ungueltige_formen_werden_abgelehnt(self):
        for falsch in ({"projekt": "Rezepte App"}, {"projekt": "ab"}, {"art": "Umsetzung!"}, {"repo": "kein-repo"},
                       {"repo": "acme/" + "x" * 101}, {"auftrag": "   "}, {"max_runden": 0}, {"max_runden": 6},
                       {"zeitlimit_min": 61}, {"abnahme": ("a",) * 6}, {"abnahme": ("x" * 301,)}, {"max_runden": True}):
            with self.subTest(falsch=falsch), self.assertRaises(ValueError):
                ae.entwurf_pruefen(entwurf(**falsch))

    def test_auch_andere_zugangswerte_werden_entfernt(self):
        geheim = {
            "github": "ghp_" + "A1b2C3d4" * 5,
            "feingranular": "github_pat_" + "11ABCDEFG_" * 4,
            "gitlab": "glpat-" + "abcDEF123_" * 3,
            # Attrappe zur Laufzeit gebaut ({"alg":"HS256"}, {"sub":"1234567890"}, Signatur "signature-wert"), damit der Secret-Scan
            # kein Literal sieht
            "jwt": ".".join(base64.urlsafe_b64encode(s).decode().rstrip("=")
                            for s in (b'{"alg":"HS256"}', b'{"sub":"1234567890"}', b"signature-wert")),
            "andere": "sk-" + "proj" * 8,
            "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
        }
        for art, wert in geheim.items():
            with self.subTest(art=art):
                self.assertEqual(ae.geheimnisse_entfernen(f"Nutze {wert} bitte"), f"Nutze {ae.MARKE} bitte")
        self.assertEqual(ae.geheimnisse_entfernen("postgres://admin:Sehr-Geheim1@db.local:5432/x"),
                         f"postgres://admin:{ae.MARKE}@db.local:5432/x")
        self.assertEqual(ae.geheimnisse_entfernen("Header Authorization: Bearer abcdefghijklmnop1234"),
                         f"Header Authorization: Bearer {ae.MARKE}")
        self.assertEqual(ae.geheimnisse_entfernen("Baue github.com/acme/rezepte-app mit Tests\x00"), "Baue github.com/acme/rezepte-app mit Tests")
        e = ae.entwurf_pruefen(entwurf(auftrag=f"Token {geheim['github']}", abnahme=(f"Kein {geheim['jwt']} im Log",)))
        self.assertNotIn("ghp_", e.auftrag)
        self.assertNotIn("eyJ", e.abnahme[0])
        self.assertEqual(ae.titel_aus(f"Token {geheim['github']}"), f"Token {ae.MARKE}")

    def test_zu_langer_text_wird_gekuerzt_nicht_abgelehnt(self):
        e = ae.entwurf_pruefen(entwurf(auftrag="a" * 5000))
        self.assertEqual(len(e.auftrag), ae.AUFTRAG_ZEICHEN)

    def test_titel_ist_die_erste_zeile_gekuerzt(self):
        self.assertEqual(ae.titel_aus("\n  Baue die App  \nmit Tests"), "Baue die App")
        lang = ae.titel_aus("Wort " * 40)
        self.assertLessEqual(len(lang), ae.TITEL_ZEICHEN)
        self.assertTrue(lang.endswith("…"))
        self.assertEqual(ae.titel_aus(""), "Auftrag")

    def test_projektwort_ohne_eigene_kennung_im_buero(self):
        self.assertEqual(ae.projekt_wort("kern-0f6c2b1e-rezepte", "0f6c2b1e"), "rezepte")
        self.assertEqual(ae.projekt_wort("kern-7d3e9c1a-rezepte", "0f6c2b1e"), "kern-7d3e9c1a-rezepte")  # fremde Kennung bleibt
        self.assertEqual(ae.projekt_wort("rezepte-app", None), "rezepte-app")
        self.assertEqual(ae.projekt_wort("kern-0f6c2b1e-rezepte", None), "kern-0f6c2b1e-rezepte")

    def test_eintrag_fuer_die_liste(self):
        eintrag = ae.eintrag(ID1, "rezepte-app", "umsetzung", None, "Baue die App\nmit Tests", 1_763_000_000_000)
        self.assertEqual(eintrag, {"id": ID1, "titel": "Baue die App", "projekt": "rezepte-app", "art": "umsetzung",
                                   "gespeichert_ms": 1_763_000_000_000})
        mit_repo = ae.eintrag(ID1, "rezepte-app", "umsetzung", "acme/rezepte-app", "x", 0)
        self.assertEqual(mit_repo["repo"], "acme/rezepte-app")


# ---------------------------------------------------------------- Modul: Datenbank
class DatenbankTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDb()
        self.speicher = ae.DatenbankEntwuerfe(self.db, NIKO)
        ae._aufraeumen_zuletzt = None

    async def test_speichern_liefert_die_kennung_und_bindet_an_das_profil(self):
        kennung, grund = await self.speicher.speichern(entwurf())
        self.assertEqual((kennung, grund), (ID1, None))
        art, sql, args = self.db.aufrufe[-1]
        self.assertEqual(art, "fetchval")
        self.assertTrue(sql.startswith("insert into wamo_test.auftrag_entwuerfe "))
        self.assertEqual(args[0], NIKO)
        self.assertIn('"Die README erklärt die Installation"', args[5])  # Kriterien als JSON-Liste
        self.assertEqual(args[6:], (4, 20))

    async def test_volle_liste_ergibt_den_satz(self):
        self.db.wert = None  # die Bedingung "weniger als 50" griff
        self.assertEqual(await self.speicher.speichern(entwurf()), (None, ae.SATZ_VOLL))

    async def test_grenze_des_triggers_ergibt_ebenfalls_voll(self):
        import asyncpg

        fehler = asyncpg.CheckViolationError("auftrag_entwuerfe: höchstens 50 Entwürfe je Person")
        fehler.constraint_name = ae.GRENZE_TRIGGER  # so setzt asyncpg das Feld aus der Antwort der Datenbank
        self.db.fehler = fehler
        self.assertEqual(await self.speicher.speichern(entwurf()), (None, ae.SATZ_VOLL))
        andere = asyncpg.CheckViolationError("andere Prüfung")
        andere.constraint_name = "auftrag_entwuerfe_projekt_chk"
        self.db.fehler = andere
        self.assertEqual(await self.speicher.speichern(entwurf()), (None, ae.SATZ_DATENBANK))

    async def test_datenbankfehler_ergibt_einen_satz_ohne_text_der_ausnahme(self):
        self.db.fehler = OSError("geheime adresse 192.168.178.136")
        for aufruf in (self.speicher.speichern(entwurf()), self.speicher.liste(), self.speicher.holen(ID1),
                       self.speicher.loeschen(ID1)):
            ergebnis = await aufruf
            self.assertEqual(ergebnis[1], ae.SATZ_DATENBANK)
            self.assertNotIn("192.168", ergebnis[1])

    async def test_ungueltiger_entwurf_geht_nie_in_die_datenbank(self):
        kennung, grund = await self.speicher.speichern(entwurf(projekt="Kein Name"))
        self.assertIsNone(kennung)
        self.assertEqual(grund, ae.SATZ_UNGUELTIG)
        self.assertEqual(self.db.aufrufe, [])

    async def test_ohne_gueltiges_profil_keine_anfrage(self):
        speicher = ae.DatenbankEntwuerfe(self.db, "kein-profil")
        self.assertEqual(await speicher.liste(), (None, ae.SATZ_OHNE_SPEICHER))
        self.assertEqual(self.db.aufrufe, [])

    async def test_liste_nur_eigene_junge_eintraege_neueste_zuerst(self):
        from datetime import datetime, timezone
        self.db.zeilen = [{"id": ID1, "projekt": "rezepte-app", "art": "umsetzung", "repo": None, "anfang": "Baue die App",
                           "erstellt_at": datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)}]
        liste, grund = await self.speicher.liste()
        self.assertIsNone(grund)
        self.assertEqual(liste[0]["titel"], "Baue die App")
        self.assertEqual(liste[0]["gespeichert_ms"], int(datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc).timestamp() * 1000))
        abfrage = next(a for a in self.db.aufrufe if a[0] == "fetch")
        self.assertIn("where user_id = $1::uuid", abfrage[1])
        self.assertIn(f"interval '{ae.AUFBEWAHRUNG_TAGE} days'", abfrage[1])
        self.assertIn("order by erstellt_at desc", abfrage[1])
        self.assertIn(f"limit {ae.MAX_JE_PERSON}", abfrage[1])
        self.assertEqual(abfrage[2], (NIKO,))

    async def test_liste_ueberspringt_zeilen_die_nicht_passen(self):
        from datetime import datetime, timezone
        zeit = datetime(2026, 11, 18, tzinfo=timezone.utc)
        self.db.zeilen = [{"id": ID1, "projekt": "Kaputt", "art": "umsetzung", "repo": None, "anfang": "x", "erstellt_at": zeit},
                          {"id": ID1, "projekt": "gut-ok", "art": "umsetzung", "repo": None, "anfang": "y", "erstellt_at": zeit}]
        liste, _ = await self.speicher.liste()
        self.assertEqual([e["projekt"] for e in liste], ["gut-ok"])

    async def test_aufraeumen_hoechstens_einmal_je_stunde(self):
        await self.speicher.liste()
        await self.speicher.liste()
        loeschungen = [a for a in self.db.aufrufe if a[0] == "execute"]
        self.assertEqual(len(loeschungen), 1)
        self.assertEqual(loeschungen[0][1], ae._AUFRAEUMEN.format(t="wamo_test.auftrag_entwuerfe"))
        self.assertIn(f"interval '{ae.AUFBEWAHRUNG_TAGE} days'", loeschungen[0][1])

    async def test_holen_nur_eigene_und_gueltige_kennung(self):
        self.assertEqual(await self.speicher.holen("keine-uuid"), (None, ae.SATZ_NICHT_GEFUNDEN))
        self.assertEqual(self.db.aufrufe, [])
        self.db.zeile = None
        self.assertEqual(await self.speicher.holen(ID1), (None, ae.SATZ_NICHT_GEFUNDEN))
        _, sql, args = self.db.aufrufe[-1]
        self.assertIn("where id = $1::uuid and user_id = $2::uuid", sql)
        self.assertEqual(args, (ID1, NIKO))
        self.db.zeile = {"projekt": "rezepte-app", "art": "umsetzung", "repo": "acme/rezepte-app", "auftrag": "Baue",
                         "abnahme": '["Die README erklärt die Installation"]', "max_runden": 4, "zeitlimit_min": 20}
        e, grund = await self.speicher.holen(ID1)
        self.assertIsNone(grund)
        self.assertEqual(e.abnahme, ("Die README erklärt die Installation",))
        self.assertEqual((e.max_runden, e.zeitlimit_min), (4, 20))

    async def test_holen_einer_kaputten_zeile_ergibt_einen_satz(self):
        self.db.zeile = {"projekt": "rezepte-app", "art": "umsetzung", "repo": None, "auftrag": "Baue", "abnahme": "{kein json",
                         "max_runden": None, "zeitlimit_min": None}
        self.assertEqual(await self.speicher.holen(ID1), (None, ae.SATZ_UNGUELTIG))

    async def test_loeschen_nur_eigene(self):
        self.assertEqual(await self.speicher.loeschen(ID1), (True, None))
        _, sql, args = self.db.aufrufe[-1]
        self.assertEqual(sql, ae._LOESCHEN.format(t="wamo_test.auftrag_entwuerfe"))
        self.assertIn("user_id = $2::uuid", sql)
        self.assertEqual(args, (ID1, NIKO))
        self.db.status = "DELETE 0"
        self.assertEqual(await self.speicher.loeschen(ID1), (False, ae.SATZ_NICHT_GEFUNDEN))

    def test_fuer_gibt_ohne_datenbank_none(self):
        self.assertIsNone(ae.fuer(object()))
        memory = type("M", (), {"enabled": False, "user_id": NIKO})()
        self.assertIsNone(ae.fuer(memory))


# ---------------------------------------------------------------- DevAgent außerhalb des Büros (Admin)
class AgentFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = mock.patch.dict(os.environ, {"WAMO_BETRIEB": "", "WAMO_ENTWICKLUNG_ORT": "sokrates2"})
        self.env.start()
        self.speicher = FakeSpeicher()
        self.memory = tb.AuditMemory()
        self.agent = dev_agent.DevAgent(memory=self.memory, auftraggeber="Niko", beurteiler=lambda *a: None,
                                        entwuerfe=self.speicher)
        self.task = FakeTask()
        self.agent.attach(self.task)
        self.fremd: list[bool] = []
        self.agent.on_result = lambda: self.fremd.append(True)

    async def asyncTearDown(self):
        self.env.stop()

    async def vorbereiten(self, **argumente) -> dict:
        p = Params(**{"auftrag": "Baue die Rezepte-App", "projekt": "rezepte-app", "art": "umsetzung",
                      "repo": "acme/rezepte-app", "abnahme": ["Die README erklärt die Installation"], **argumente})
        await self.agent._vorbereiten(p)
        return p.ergebnis

    def nachrichten(self, typ):
        return [m for m in self.task.messages() if m.get("type") == typ]

    async def klick(self, **data):
        await self.agent.on_client_message("auftrag_entwurf", data)
        return self.nachrichten("auftrag_entwuerfe")[-1]


class SpeichernTests(AgentFlow):
    async def test_speichern_legt_den_entwurf_ab_und_nimmt_die_karte_weg(self):
        ergebnis = await self.vorbereiten(max_runden=4, zeitlimit_min=20)
        job = ergebnis["auftrag_id"]
        antwort = await self.klick(aktion="speichern", job=job)
        self.assertEqual(antwort["ok"], True)
        self.assertEqual(antwort["aktion"], "speichern")
        self.assertEqual(antwort["job"], job)
        self.assertEqual(antwort["text"], ae.SATZ_GESPEICHERT)
        self.assertEqual(len(antwort["entwuerfe"]), 1)
        self.assertEqual(antwort["max"], ae.MAX_JE_PERSON)
        (_, gespeichert, _), = self.speicher.zeilen.values()
        self.assertEqual(gespeichert, ae.Entwurf(projekt="rezepte-app", art="umsetzung", auftrag="Baue die Rezepte-App",
                                                 repo="acme/rezepte-app", abnahme=("Die README erklärt die Installation",),
                                                 max_runden=4, zeitlimit_min=20))
        self.assertNotIn(job, self.agent._jobs)  # die Karte ist weg, ein Start danach ist unbekannt

    async def test_ohne_kriterien_keine_runden_und_kein_zeitlimit(self):
        ergebnis = await self.vorbereiten(abnahme=None)
        await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        (_, gespeichert, _), = self.speicher.zeilen.values()
        self.assertEqual((gespeichert.abnahme, gespeichert.max_runden, gespeichert.zeitlimit_min), ((), None, None))

    async def test_nie_ein_zugangswert_und_schluessel_geschwaerzt(self):
        ergebnis = await self.vorbereiten(auftrag=f"Baue die App, Schlüssel {SCHLUESSEL}")
        antwort = await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        self.assertTrue(antwort["ok"])
        (_, gespeichert, _), = self.speicher.zeilen.values()
        self.assertNotIn("GEHEIM", repr(gespeichert))
        self.assertNotIn("GEHEIM", repr(self.task.messages()[-1]))

    async def test_gestarteter_auftrag_laesst_sich_nicht_speichern(self):
        ergebnis = await self.vorbereiten()
        self.agent._jobs[ergebnis["auftrag_id"]].started = True
        antwort = await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_GESTARTET))
        self.assertEqual(self.speicher.zeilen, {})
        self.assertIn(ergebnis["auftrag_id"], self.agent._jobs)

    async def test_unbekannte_karte(self):
        antwort = await self.klick(aktion="speichern", job="gibtesnicht")
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_KARTE_FEHLT))
        self.assertEqual(antwort["job"], "gibtesnicht")

    async def test_fehler_beim_speichern_laesst_die_karte_stehen(self):
        ergebnis = await self.vorbereiten()
        self.speicher.fehler = ae.SATZ_DATENBANK
        antwort = await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_DATENBANK))
        self.assertIn(ergebnis["auftrag_id"], self.agent._jobs)
        self.assertTrue(fehlerbuch.Fehlerbuch().aus_meldung(antwort))  # landet im Fehlerbuch

    async def test_waehrend_des_speicherns_startet_die_karte_nicht(self):
        ergebnis = await self.vorbereiten()
        job = ergebnis["auftrag_id"]
        tor = asyncio.Event()
        original = self.speicher.speichern

        async def langsam(e):
            await tor.wait()
            return await original(e)

        self.speicher.speichern = langsam
        speichern = asyncio.create_task(self.klick(aktion="speichern", job=job))
        await asyncio.sleep(0)
        self.assertIn(job, self.agent._jobs)  # die Karte bleibt während des Speicherns in der Sitzung, in derselben Reihenfolge
        await self.agent.on_client_message("auftrag_start", {"job": job, "entscheidung": "ja"})
        zweites = await self.agent._entwurf_speichern(job)  # ein zweites Speichern derselben Karte geht nicht
        tor.set()
        await speichern
        quittung = self.nachrichten("auftrag_quittung")
        self.assertEqual((quittung[-1]["ok"], quittung[-1]["grund"]), (False, ae.SATZ_WIRD_GESPEICHERT))
        self.assertEqual(zweites, ae.SATZ_WIRD_GESPEICHERT)
        self.assertIsNone(self.agent._running)
        self.assertEqual(len(self.speicher.zeilen), 1)
        self.assertNotIn(job, self.agent._jobs)
        self.assertEqual(self.agent._speichert, set())

    async def test_unerwartete_ausnahme_ergibt_einen_festen_satz(self):
        ergebnis = await self.vorbereiten()

        async def kaputt(*_a):
            raise RuntimeError("geheimer Text")

        self.speicher.liste = kaputt
        antwort = await self.klick(aktion="liste")
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_INTERN))
        self.speicher.speichern = kaputt
        antwort = await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_DATENBANK))
        self.assertIn(ergebnis["auftrag_id"], self.agent._jobs)
        for werkzeug in (self.agent._werkzeug_speichern, self.agent._werkzeug_gespeichert):
            p = Params()
            await werkzeug(p)
            self.assertFalse(p.ergebnis["ok"])
            self.assertNotIn("geheim", repr(p.ergebnis))

    async def test_ohne_speicher_ein_satz(self):
        self.agent._entwuerfe = None
        for daten in ({"aktion": "liste"}, {"aktion": "speichern", "job": "x"}, {"aktion": "laden", "id": ID1},
                      {"aktion": "loeschen", "id": ID1}):
            with self.subTest(daten=daten):
                antwort = await self.klick(**daten)
                self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_OHNE_SPEICHER))

    async def test_unbekannte_aktion_bleibt_still(self):
        vorher = len(self.task.messages())
        await self.agent.on_client_message("auftrag_entwurf", {"aktion": "update"})
        await self.agent.on_client_message("auftrag_entwurf", "kein dict")
        self.assertEqual(len(self.task.messages()), vorher)


class LadenTests(AgentFlow):
    async def gespeichert(self, **extra) -> str:
        kennung, _ = await self.speicher.speichern(entwurf(**extra))
        return kennung

    async def test_laden_legt_eine_neue_karte_an_und_startet_nichts(self):
        kennung = await self.gespeichert()
        antwort = await self.klick(aktion="laden", id=kennung)
        self.assertTrue(antwort["ok"])
        self.assertEqual(antwort["text"], ae.SATZ_GELADEN)
        (karte,) = self.nachrichten("auftrag")
        self.assertEqual((karte["projekt"], karte["art"], karte["auftrag"], karte["repo"], karte["abnahme"]),
                         ("rezepte-app", "umsetzung", "Baue die Rezepte-App", "acme/rezepte-app",
                          ["Die README erklärt die Installation"]))
        self.assertEqual(antwort["job"], karte["job"])
        job = self.agent._jobs[karte["job"]]
        self.assertEqual((job.max_runden, job.zeitlimit_s), (4, 20 * 60))
        self.assertFalse(job.started)
        self.assertIsNone(self.agent._running)
        self.assertIn(kennung, self.speicher.zeilen)  # der Entwurf bleibt, bis die Person ihn löscht

    async def test_zweites_laden_legt_keine_zweite_offene_karte_an(self):
        kennung = await self.gespeichert()
        erste = await self.klick(aktion="laden", id=kennung)
        zweite = await self.klick(aktion="laden", id=kennung.upper())
        self.assertEqual((zweite["ok"], zweite["text"], zweite["job"]), (True, ae.SATZ_SCHON_GELADEN, erste["job"]))
        self.assertEqual(len(self.nachrichten("auftrag")), 1)
        await self.agent.on_client_message("auftrag_start", {"job": erste["job"], "entscheidung": "nein"})  # verworfen
        dritte = await self.klick(aktion="laden", id=kennung)
        self.assertEqual(dritte["text"], ae.SATZ_GELADEN)
        self.assertNotEqual(dritte["job"], erste["job"])

    async def test_laden_prueft_wie_vorbereiten(self):
        for kaputt, satz in (({"art": "unbekannt"}, "Unbekannte Auftragsart"),
                             ({"abnahme": ("befehl: pytest -q",)}, "befehl"),
                             ({"repo": "acme/wamo"}, "WAMO-Repo")):
            with self.subTest(kaputt=kaputt):
                kennung = await self.gespeichert(**kaputt)
                antwort = await self.klick(aktion="laden", id=kennung)
                self.assertFalse(antwort["ok"])
                self.assertIn(satz, antwort["grund"])
        self.assertEqual(self.nachrichten("auftrag"), [])

    async def test_fremder_oder_fehlender_entwurf(self):
        fremd = FakeSpeicher(ANDERE)
        kennung, _ = await fremd.speichern(entwurf())
        self.speicher.zeilen.update(fremd.zeilen)
        antwort = await self.klick(aktion="laden", id=kennung)
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_NICHT_GEFUNDEN))
        antwort = await self.klick(aktion="loeschen", id=kennung)
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_NICHT_GEFUNDEN))
        self.assertIn(kennung, self.speicher.zeilen)

    async def test_loeschen_und_liste(self):
        kennung = await self.gespeichert()
        liste = await self.klick(aktion="liste")
        self.assertEqual((liste["ok"], [e["id"] for e in liste["entwuerfe"]]), (True, [kennung]))
        antwort = await self.klick(aktion="loeschen", id=kennung)
        self.assertEqual((antwort["ok"], antwort["text"], antwort["entwuerfe"]), (True, ae.SATZ_GELOESCHT, []))

    async def test_liste_mit_fehler_ohne_eintraege(self):
        self.speicher.fehler = ae.SATZ_DATENBANK
        antwort = await self.klick(aktion="liste")
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, ae.SATZ_DATENBANK))
        self.assertNotIn("entwuerfe", antwort)


class WerkzeugTests(AgentFlow):
    async def test_schemas_und_registrierung(self):
        namen = [s.name for s in self.agent.schemas()]
        self.assertIn("entwicklung_speichern", namen)
        self.assertIn("entwicklung_gespeichert", namen)
        registriert = {}
        llm = type("L", (), {"register_function": lambda _s, n, h: registriert.__setitem__(n, h)})()
        self.agent.register(llm)
        self.assertIn("entwicklung_speichern", registriert)
        self.assertIn("entwicklung_gespeichert", registriert)

    async def test_speichern_per_sprache_nimmt_die_juengste_offene_karte(self):
        await self.vorbereiten(auftrag="Erster Auftrag")
        zweiter = await self.vorbereiten(auftrag="Zweiter Auftrag")
        p = Params()
        await self.agent._werkzeug_speichern(p)
        self.assertTrue(p.ergebnis["ok"])
        (_, gespeichert, _), = self.speicher.zeilen.values()
        self.assertEqual(gespeichert.auftrag, "Zweiter Auftrag")
        self.assertEqual(self.nachrichten("auftrag_entwuerfe")[-1]["job"], zweiter["auftrag_id"])  # die Karte verschwindet auch

    async def test_speichern_per_sprache_ohne_karte_meldet_einen_fehler_fuers_fehlerbuch(self):
        p = Params()
        await self.agent._werkzeug_speichern(p)
        self.assertEqual((p.ergebnis["ok"], p.ergebnis["status"], p.ergebnis["grund"]), (False, "failed", ae.SATZ_KEINE_KARTE))
        buch = fehlerbuch.Fehlerbuch()
        self.assertTrue(buch.aus_ergebnis("entwicklung_speichern", p.ergebnis))

    async def test_fehler_per_sprache_geht_nur_an_das_modell(self):
        await self.vorbereiten()
        self.speicher.fehler = ae.SATZ_DATENBANK
        p = Params()
        await self.agent._werkzeug_speichern(p)
        self.assertEqual(p.ergebnis["grund"], ae.SATZ_DATENBANK)
        self.assertEqual(self.nachrichten("auftrag_entwuerfe"), [])  # nicht doppelt im Fehlerbuch

    async def test_auflisten_per_sprache_als_daten_und_fremdinhalt(self):
        await self.speicher.speichern(entwurf(auftrag="Baue die Rezepte-App\nmit Tests"))
        p = Params()
        await self.agent._werkzeug_gespeichert(p)
        self.assertTrue(p.ergebnis["ok"])
        self.assertEqual(p.ergebnis["anzahl"], 1)
        self.assertEqual(p.ergebnis["entwuerfe"][0]["titel"], "Baue die Rezepte-App")
        self.assertIn("Daten", p.ergebnis["hinweis"])
        self.assertEqual(self.fremd, [True])

    async def test_beide_werkzeuge_laufen_durch_das_stimm_gate(self):
        self.assertNotIn("entwicklung_speichern", stimme_gate.OFFENE_WERKZEUGE)
        self.assertNotIn("entwicklung_gespeichert", stimme_gate.OFFENE_WERKZEUGE)
        registriert = {}

        class Llm:
            def register_function(self, name, handler):
                registriert[name] = handler

        class Gate:
            async def pruefen(self, werkzeug):
                return {"status": "blocked", "grund": "Stimmprüfung: fremde Stimme"}

        llm = Llm()
        stimme_gate.werkzeuge_absichern(llm, Gate())
        self.agent.register(llm)
        await self.vorbereiten()
        for name in ("entwicklung_speichern", "entwicklung_gespeichert"):
            p = Params()
            await registriert[name](p)
            self.assertEqual(p.ergebnis["status"], "blocked")
        self.assertEqual(self.speicher.aufrufe, [])


# ---------------------------------------------------------------- Büro: Zulassung, Mitglieder, Projektname
class BueroTests(tb.BueroFlow):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.speicher = FakeSpeicher()
        self.agent._entwuerfe = self.speicher

    async def klick(self, agent=None, **data):
        await (agent or self.agent).on_client_message("auftrag_entwurf", data)
        return [m for m in self.task.messages() if m.get("type") == "auftrag_entwuerfe"][-1]

    async def test_recherche_ohne_repo_kommt_mit_demselben_kern_projekt_zurueck(self):
        ergebnis = await self.vorbereiten(art="recherche", repo="", projekt="Marktanalyse")
        projekt = self.agent._jobs[ergebnis["auftrag_id"]].projekt.name
        self.assertEqual(projekt, "kern-0f6c2b1e-marktanalyse")
        await self.klick(aktion="speichern", job=ergebnis["auftrag_id"])
        kennung = next(iter(self.speicher.zeilen))
        antwort = await self.klick(aktion="laden", id=kennung)
        self.assertTrue(antwort["ok"], antwort)
        karte = [m for m in self.task.messages() if m.get("type") == "auftrag"][-1]
        self.assertEqual(karte["projekt"], projekt)

    async def test_ohne_zulassung_geht_keine_aktion(self):
        agent = self.ohne_zulassung()
        agent._entwuerfe = self.speicher
        for daten in ({"aktion": "liste"}, {"aktion": "laden", "id": ID1}, {"aktion": "loeschen", "id": ID1},
                      {"aktion": "speichern", "job": "x"}):
            with self.subTest(daten=daten):
                antwort = await self.klick(agent, **daten)
                self.assertEqual((antwort["ok"], antwort["grund"]), (False, eb.SATZ_KEINE_ZULASSUNG))
        self.assertEqual(self.speicher.aufrufe, [])

    async def test_mitglied_ohne_schalter_verliert_die_zulassung(self):
        with tb.buero(WAMO_ENTWICKLUNG_MITGLIEDER="an"):
            agent = dev_agent.DevAgent(memory=self.memory, auftraggeber="Erika", zulassung=eb.BueroZulassung(NIKO, mitglied=True),
                                       entwuerfe=self.speicher)
            agent.attach(self.task)
            self.assertTrue((await self.klick(agent, aktion="liste"))["ok"])
        with tb.buero(WAMO_ENTWICKLUNG_MITGLIEDER="aus"):
            antwort = await self.klick(agent, aktion="liste")
        self.assertEqual((antwort["ok"], antwort["grund"]), (False, eb.SATZ_KEINE_ZULASSUNG))


class StandardSpeicherTests(unittest.TestCase):
    def test_devagent_baut_den_speicher_aus_dem_gedaechtnis(self):
        db = FakeDb()
        memory = type("M", (), {"enabled": True, "user_id": NIKO, "db": db})()
        with mock.patch.dict(os.environ, {"WAMO_BETRIEB": ""}):
            agent = dev_agent.DevAgent(memory=memory, auftraggeber="Niko")
        self.assertIsInstance(agent._entwuerfe, ae.DatenbankEntwuerfe)
        with mock.patch.dict(os.environ, {"WAMO_BETRIEB": ""}):
            ohne = dev_agent.DevAgent(memory=tb.AuditMemory(), auftraggeber="Niko")
        self.assertIsNone(ohne._entwuerfe)

    def test_job_pfad_als_projektname(self):
        job = dev_agent.Job(id="ab12cd34ef56ab12", auftrag="x", projekt=PurePosixPath("/srv/wamo/projekte/rezepte-app"), art="analyse")
        self.assertEqual(ae.entwurf_aus_job(job).projekt, "rezepte-app")


if __name__ == "__main__":
    unittest.main()
