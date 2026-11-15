"""Tests für die Mail-Werkzeuge im Host (wamo_host.py): outlook_mail_anfragen, Freigabeart mail, outlook_zurueckholen und
outlook_versand_status.

Die Werkzeuge ruft nur der Kern. Geprüft wird, was der Host selbst erzwingt: Schalter office.aus, Ratengrenze, Anhänge nur aus dem
Register mit unveränderter Prüfsumme, lange Karte bis 8000 Zeichen, genau einmal nach dem Klick mit Schlüssel, nie senden, wenn Outlook
seit der Karte gewechselt hat, Zurückholen nur mit Schlüssel, Audit ohne Betreff und Text im Klartext. Outlook, Erkennung und Entwurf
sind Attrappen.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import office_ablage
import office_outlook as oo
import office_outlook_com as oc
import wamo_host as host
from test_office_outlook import MEHRDEUTIG, Eintrag, Outlook

SCHLUESSEL = "k" * 43
GEHEIM = "Vertraulicher Satz im Angebot"
BETREFF = "Angebot Kunde X"
NEU = oo.Weg("entwurf", "neu", oo.NEU_GRUND)
KLASSISCH = oo.Weg("senden", "klassisch", oo.SENDEN_GRUND)
ZU = oo.Weg("keiner", "", oo.ZU_GRUND)


class _Basis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)
        (wurzel / "Dokumente").mkdir()
        self.ablage = office_ablage.Ablage(wurzel / "Dokumente", wurzel / "WAMO" / "ablage.json")
        self.schalter = wurzel / "WAMO" / "office.aus"
        self.audit: list[dict] = []
        self.weg = NEU
        self.entwuerfe: list[tuple] = []
        self.outlook = Outlook(adressbuch={"Max Weber": Eintrag("Max Weber", "max.weber@firma.example"), "Anna": MEHRDEUTIG})
        for p in (
            mock.patch.object(host, "_audit", side_effect=self.audit.append),
            mock.patch.object(host, "_office_ablage", return_value=self.ablage),
            mock.patch.object(host, "OFFICE_AUS", self.schalter),
            mock.patch.object(host, "FREIGABE_SCHLUESSEL", SCHLUESSEL),
            mock.patch.object(host, "_ist_gesperrt", return_value=False),
            mock.patch.object(host, "MAIL_VERZOEGERUNG_SECS", 5),
            mock.patch.object(host, "_VERSAND", None),
            mock.patch.object(oo, "erkennen", side_effect=lambda *a, **k: self.weg),
            mock.patch.object(oo, "neu_entwurf", side_effect=self._neu_entwurf),
            mock.patch.object(oc, "_outlook_app", return_value=self.outlook),
            mock.patch.dict("os.environ", {"WAMO_MAIL_INTERN": "firma.example"}),
        ):
            p.start()
            self.addCleanup(p.stop)
        host.PENDING.clear()
        self.addCleanup(host.PENDING.clear)
        host._rate_zeiten.clear()
        self.addCleanup(host._rate_zeiten.clear)

    def _neu_entwurf(self, mail, daten, **_kw):
        self.entwuerfe.append((mail, daten))
        return {"status": "success", "weg": "eml", "anhang": bool(daten), "fenster": True,
                "summary": "Der Entwurf ist im neuen Outlook offen. Prüfen und selbst auf Senden drücken."}

    def datei(self, name="Angebot", daten=b"%PDF-1.7 Angebot") -> dict:
        eintrag, _pfad = self.ablage.speichern(daten, name, "pdf")
        return eintrag

    def anfragen(self, an=("max.weber@firma.example",), cc=None, betreff=BETREFF, text=f"Hallo Max,\n{GEHEIM}", anhaenge=None):
        return asyncio.run(host.outlook_mail_anfragen(list(an), betreff, text, list(cc) if cc else None, anhaenge))

    def freigeben(self, antwort, ja=True):
        return host.entscheiden(antwort["approval_id"], ja, SCHLUESSEL)

    def audit_text(self) -> str:
        return json.dumps(self.audit, ensure_ascii=False, default=str)


class Anfrage(_Basis):
    def test_entwurf_im_neuen_outlook_wird_zur_langen_karte(self):
        k = self.datei()
        a = self.anfragen(cc=["anna@kunde.example"], anhaenge=[k["kennung"]])
        self.assertEqual(a["status"], "needs_approval", a)
        self.assertEqual(a["aktion"], "mail")
        self.assertEqual(a["grund"], "Mail-Entwurf an EXTERNE Empfänger öffnen")
        self.assertIn("Neues Outlook", a["ziel"])
        self.assertIn("So geht es: Das neue Outlook läuft", a["detail"])
        self.assertIn("An: max.weber@firma.example (intern)", a["detail"])
        self.assertIn("Cc: anna@kunde.example (EXTERN)", a["detail"])
        self.assertIn(f"> {GEHEIM}", a["detail"])
        self.assertIn(f"Anhang: {k['name']}", a["detail"])
        self.assertEqual(a["protokoll"], {"an": 1, "cc": 1, "domaenen": ["firma.example", "kunde.example"], "extern": True,
                                          "anhaenge": 1, "weg": "entwurf", "programm": "neu"})
        self.assertEqual(host.PENDING[a["approval_id"]]["art"], "mail")
        self.assertNotIn(GEHEIM, self.audit_text())
        self.assertNotIn(BETREFF, self.audit_text())
        eintrag = next(x for x in self.audit if x.get("tool") == "outlook_mail_anfragen")
        self.assertEqual(eintrag["risk"], "change")  # Entwurf ist change, kommt aber trotzdem nur nach der Karte

    def test_klassisch_loest_namen_auf_und_zeigt_konto_und_signatur(self):
        self.weg = KLASSISCH
        a = self.anfragen(an=("Max Weber",))
        self.assertEqual(a["status"], "needs_approval", a)
        self.assertEqual(a["grund"], "Mail über Outlook senden")
        self.assertIn("Outlook (klassisch), Konto konto@firma.example", a["ziel"])
        self.assertIn("An: Max Weber <max.weber@firma.example> (intern)", a["detail"])
        self.assertIn("Signatur aus Outlook:", a["detail"])
        self.assertEqual(self.outlook.gespeichert, {})  # vor dem Klick kein Entwurf
        eintrag = next(x for x in self.audit if x.get("tool") == "outlook_mail_anfragen")
        self.assertEqual(eintrag["risk"], "critical")

    def test_ablehnungen(self):
        self.assertEqual(self.anfragen(an=("Max Weber",))["status"], "rejected")  # neues Outlook: nur Adressen
        self.weg = KLASSISCH
        self.assertIn("nicht eindeutig", self.anfragen(an=("Anna",))["summary"])
        self.weg = ZU
        r = self.anfragen()
        self.assertEqual(r["status"], "rejected")
        self.assertIn("nicht geöffnet", r["summary"])
        self.weg = NEU
        for kaputt in ({"betreff": ""}, {"an": ()}, {"an": [f"x{i}@firma.example" for i in range(11)]}, {"anhaenge": ["fedcba9876543210"]},
                       {"anhaenge": ["../../x"]}, {"text": "x\n" * 3000}):
            self.assertEqual(self.anfragen(**kaputt)["status"], "rejected", kaputt)
        self.assertEqual(host.PENDING, {})

    def test_zu_lang_fuer_die_karte(self):
        r = self.anfragen(text="x\n" * 2900)
        self.assertEqual(r["status"], "rejected")
        self.assertIn("Anhang", r["summary"])

    def test_geaenderte_datei_wird_nicht_angehaengt(self):
        k = self.datei()
        self.ablage.pfad(k["kennung"]).write_bytes(b"%PDF-1.7 anders")
        r = self.anfragen(anhaenge=[k["kennung"]])
        self.assertEqual(r["status"], "rejected")
        self.assertIn("geändert", r["summary"])

    def test_office_aus_und_ratengrenze(self):
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(self.anfragen()["status"], "blocked")
        self.schalter.unlink()
        for i in range(host.MAIL_PRO_STUNDE):
            self.assertEqual(self.anfragen(betreff=f"Nr {i}")["status"], "needs_approval")
            host.PENDING.clear()
        self.assertEqual(self.anfragen(betreff="eine zu viel")["status"], "rejected")

    def test_eingaben_ruhen_solange_die_mailkarte_offen_ist(self):
        self.anfragen()
        self.assertEqual(host._eingabe_vorab("tastatur_tippen")["status"], "wartet")

    def test_faehigkeiten_melden_mail(self):
        with mock.patch.object(oo, "verfuegbar", return_value=True), mock.patch.object(host.office_com, "faehigkeiten",
                                                                                          return_value={"formate": ["word"], "word": True}):
            self.assertTrue(host.office_faehigkeiten()["mail"])


class Ausfuehren(_Basis):
    def test_entwurf_genau_einmal_nach_dem_klick(self):
        k = self.datei()
        a = self.anfragen(anhaenge=[k["kennung"]])
        r = self.freigeben(a)
        self.assertEqual(r["status"], "success", r)
        (mail, daten), = self.entwuerfe
        self.assertEqual(mail.betreff, BETREFF)
        self.assertEqual([(x.name, d) for x, d in daten], [(k["name"], b"%PDF-1.7 Angebot")])
        self.assertEqual(self.freigeben(a)["status"], "error")  # nicht noch einmal
        self.assertEqual(len(self.entwuerfe), 1)
        self.assertNotIn(GEHEIM, self.audit_text())

    def test_nein_tut_nichts(self):
        self.assertEqual(self.freigeben(self.anfragen(), ja=False)["status"], "rejected")
        self.assertEqual(self.entwuerfe, [])

    def test_ohne_schluessel_nichts(self):
        a = self.anfragen()
        self.assertEqual(host.entscheiden(a["approval_id"], True, "falsch")["status"], "blocked")
        self.assertEqual(self.entwuerfe, [])

    def test_klassisch_senden_erst_nach_der_frist_und_zurueckholbar(self):
        self.weg = KLASSISCH
        a = self.anfragen(an=("Max Weber",))
        r = self.freigeben(a)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["versand"]["frist_s"], 5)
        self.assertEqual(len(self.outlook.gespeichert), 1)  # unter Entwürfe gespeichert
        self.assertEqual(self.outlook.gesendet, [])  # noch nicht gesendet
        vid = r["versand"]["id"]
        self.assertEqual(host.outlook_versand_status(vid)["zustand"], "wartet")
        self.assertEqual(host.outlook_zurueckholen(vid, "falsch")["status"], "blocked")
        z = host.outlook_zurueckholen(vid, SCHLUESSEL)
        self.assertEqual((z["status"], z["zustand"]), ("success", "zurueckgeholt"))
        host._versand()._eintraege[vid].faden.join(2)
        self.assertEqual(self.outlook.gesendet, [])
        self.assertEqual(host.outlook_versand_status(vid)["zustand"], "zurueckgeholt")

    def test_klassisch_sendet_nach_der_frist_genau_einmal(self):
        self.weg = KLASSISCH
        with mock.patch.object(host, "MAIL_VERZOEGERUNG_SECS", 0.05):
            r = self.freigeben(self.anfragen(an=("Max Weber",)))
        vid = r["versand"]["id"]
        host._versand()._eintraege[vid].faden.join(3)
        self.assertEqual(len(self.outlook.gesendet), 1)
        self.assertEqual(host.outlook_versand_status(vid)["zustand"], "gesendet")
        self.assertEqual(host.outlook_zurueckholen(vid, SCHLUESSEL)["zustand"], "zu_spaet")

    def test_outlook_gewechselt_heisst_nie_senden(self):
        self.weg = KLASSISCH
        a = self.anfragen(an=("max.weber@firma.example",))
        self.weg = NEU  # zwischen Karte und Klick: jetzt läuft das neue Outlook
        r = self.freigeben(a)
        self.assertEqual(r["status"], "success")
        self.assertIn("sendet W.A.I.S. nicht", r["summary"])
        self.assertNotIn("versand", r)
        self.assertEqual(len(self.entwuerfe), 1)
        self.assertEqual(self.outlook.gesendet, [])

    def test_karte_entwurf_bleibt_entwurf_auch_wenn_jetzt_senden_ginge(self):
        a = self.anfragen()
        self.weg = KLASSISCH
        r = self.freigeben(a)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(len(self.outlook.angezeigt), 1)  # klassischer Entwurf, nur angezeigt
        self.assertEqual(self.outlook.gesendet, [])
        self.assertNotIn("versand", r)

    def test_anhang_zwischen_karte_und_klick_geaendert(self):
        k = self.datei()
        a = self.anfragen(anhaenge=[k["kennung"]])
        self.ablage.pfad(k["kennung"]).write_bytes(b"%PDF-1.7 anders")
        r = self.freigeben(a)
        self.assertEqual(r["status"], "error")
        self.assertIn("geändert", r["summary"])
        self.assertEqual(self.entwuerfe, [])

    def test_office_aus_nach_der_karte(self):
        a = self.anfragen()
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(self.freigeben(a)["status"], "blocked")
        self.assertEqual(self.entwuerfe, [])

    def test_office_aus_in_der_frist_stoppt_den_versand(self):
        self.weg = KLASSISCH
        with mock.patch.object(host, "MAIL_VERZOEGERUNG_SECS", 0.1):
            r = self.freigeben(self.anfragen(an=("Max Weber",)))
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        host._versand()._eintraege[r["versand"]["id"]].faden.join(3)
        self.assertEqual(self.outlook.gesendet, [])
        self.assertEqual(host.outlook_versand_status(r["versand"]["id"])["zustand"], "fehler")

    def test_unbekannter_versand(self):
        self.assertEqual(host.outlook_versand_status("0123456789abcdef")["status"], "rejected")
        self.assertEqual(host.outlook_zurueckholen("../x", SCHLUESSEL)["zustand"], "unbekannt")


class Befunde(_Basis):
    """Echttest und Review vom 15.11.2026."""

    def test_karte_zaehlt_wie_die_oberflaeche_in_utf16(self):
        emoji = chr(0x1F600)  # zwei UTF-16-Einheiten, ein Codepunkt
        r = self.anfragen(text=emoji * 4000)  # 4000 Zeichen erlaubt, auf der Karte aber über 8000 Einheiten
        self.assertEqual(r["status"], "rejected")
        self.assertIn("Anhang", r["summary"])
        self.assertEqual(host.PENDING, {})

    def test_registerfehler_werden_abgelehnt_und_protokolliert(self):
        k = self.datei()
        with mock.patch.object(self.ablage, "eintraege", side_effect=office_ablage.AblageFehler("Register kaputt")):
            r = self.anfragen(anhaenge=[k["kennung"]])
        self.assertEqual(r["status"], "rejected")
        with mock.patch.object(self.ablage, "eintraege", return_value=[]):  # Datei da, Eintrag inzwischen weg
            r = self.anfragen(anhaenge=[k["kennung"]])
        self.assertEqual(r["status"], "rejected")
        abgelehnt = [a for a in self.audit if a.get("tool") == "outlook_mail_anfragen" and a.get("risk") == "rejected"]
        self.assertEqual(len(abgelehnt), 2)
        self.assertEqual(host.PENDING, {})

    def test_konto_der_karte_geht_bis_zum_senden_mit(self):
        self.weg = KLASSISCH
        r = self.freigeben(self.anfragen(an=("Max Weber",)))
        v = host._versand()._eintraege[r["versand"]["id"]]
        self.assertEqual(v.ort["konto"], "konto@firma.example")
        self.assertEqual(v.pruef["konto"], "konto@firma.example")
        host._versand().zurueckholen(v.id)

    def test_hoststart_raeumt_entwurfsdateien_auf(self):
        quelle = Path(host.__file__).read_text(encoding="utf-8")
        start = quelle.split('if __name__ == "__main__":', 1)[1]
        self.assertIn("office_outlook.beim_start_aufraeumen()", start)


class NieFuerDasModell(unittest.TestCase):
    def test_mail_werkzeuge_stehen_nicht_in_llm_tools(self):
        quelle = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_host.py").read_text(encoding="utf-8")
        block = quelle.split("LLM_TOOLS = [", 1)[1].split("]", 1)[0]
        for name in ("outlook_mail_anfragen", "outlook_zurueckholen", "outlook_versand_status"):
            self.assertNotIn(name, block)
