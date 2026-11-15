"""Tests für das Teams-Werkzeug im Host (wamo_host.py): teams_chat_anfragen und die Freigabeart teams.

Das Werkzeug ruft nur der Kern. Geprüft wird, was der Host selbst erzwingt: Schalter office.aus, Ratengrenze, nur aufgelöste interne
Adressen, Text und Länge, Karte mit genau dem Inhalt des Links, genau einmal nach dem Klick mit Schlüssel, Audit ohne Inhalt (nur Anzahl
und Prüfsumme) und nie ein Senden. Das Öffnen von Teams und das klassische Outlook sind Attrappen.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import office_outlook as oo
import office_outlook_com as oc
import office_teams as ot
import wamo_host as host
from test_office_outlook import MEHRDEUTIG, Eintrag, Outlook

SCHLUESSEL = "k" * 43
GEHEIM = "Vertraulicher Satz zum Angebot"
MAX = "max.weber@firma.example"
ANNA = "anna.schmidt@firma.example"


class _Basis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.schalter = Path(self._tmp.name) / "WAMO" / "office.aus"
        self.audit: list[dict] = []
        self.geoeffnet: list[str] = []
        self.weg = oo.Weg("entwurf", "neu", oo.NEU_GRUND)
        self.outlook = Outlook(adressbuch={"Max Weber": Eintrag("Max Weber", MAX), "Anna": MEHRDEUTIG})
        for p in (
            mock.patch.object(host, "_audit", side_effect=self.audit.append),
            mock.patch.object(host, "OFFICE_AUS", self.schalter),
            mock.patch.object(host, "FREIGABE_SCHLUESSEL", SCHLUESSEL),
            mock.patch.object(host, "_ist_gesperrt", return_value=False),
            mock.patch.object(oo, "erkennen", side_effect=lambda *a, **k: self.weg),
            mock.patch.object(oc, "_outlook_app", return_value=self.outlook),
            mock.patch.object(ot, "app_registriert", return_value=True),
            mock.patch.object(ot, "_starten", side_effect=self.geoeffnet.append),
            mock.patch.dict("os.environ", {"WAMO_MAIL_INTERN": "firma.example"}),
        ):
            p.start()
            self.addCleanup(p.stop)
        host.PENDING.clear()
        self.addCleanup(host.PENDING.clear)
        host._rate_zeiten.clear()
        self.addCleanup(host._rate_zeiten.clear)

    def anfragen(self, an=(MAX,), text=f"Hallo Max,\n{GEHEIM}", gruppenname="", anlass=""):
        return asyncio.run(host.teams_chat_anfragen(list(an), text, gruppenname, anlass))

    def freigeben(self, antwort, ja=True):
        return host.entscheiden(antwort["approval_id"], ja, SCHLUESSEL)

    def audit_text(self) -> str:
        return json.dumps(self.audit, ensure_ascii=False, default=str)


class Anfrage(_Basis):
    def test_karte_mit_empfaenger_und_text(self):
        a = self.anfragen(an=(MAX, ANNA), gruppenname="Angebot X", anlass="Die Person möchte Bescheid geben")
        self.assertEqual(a["status"], "needs_approval", a)
        self.assertEqual((a["aktion"], a["grund"], a["ziel"]), ("teams", ot.GRUND, ot.ZIEL))
        self.assertIn("W.A.I.S. öffnet die Teams-App", a["detail"])
        self.assertIn(f"An: {MAX} (intern)", a["detail"])
        self.assertIn("Gruppenname: Angebot X", a["detail"])
        self.assertIn(f"> {GEHEIM}", a["detail"])
        self.assertTrue(a["detail"].endswith(ot.SCHLUSS))
        self.assertEqual(a["protokoll"], {"an": 2, "domaenen": ["firma.example"], "gruppe": True})
        self.assertEqual(host.PENDING[a["approval_id"]]["art"], "teams")
        self.assertEqual(self.geoeffnet, [])  # vor dem Klick passiert am PC nichts

    def test_audit_nur_mit_anzahl_und_pruefsumme(self):
        a = self.anfragen(an=(MAX, ANNA), gruppenname="Geheimes Projekt")
        self.freigeben(a)
        for verboten in (GEHEIM, MAX, ANNA, "Geheimes Projekt", "teams.microsoft.com"):
            self.assertNotIn(verboten, self.audit_text())
        eintrag = next(x for x in self.audit if x.get("tool") == "teams_chat_anfragen")
        self.assertEqual(eintrag["risk"], "critical")
        self.assertEqual(eintrag["an"], 2)
        self.assertEqual(set(eintrag["text"]), {"zeichen", "sha256"})
        self.assertEqual(set(eintrag["empfaenger"]), {"zeichen", "sha256"})

    def test_namen_ueber_das_klassische_outlook(self):
        self.weg = oo.Weg("senden", "klassisch", oo.SENDEN_GRUND)
        a = self.anfragen(an=("Max Weber",))
        self.assertEqual(a["status"], "needs_approval", a)
        self.assertIn(f"An: Max Weber <{MAX}> (intern)", a["detail"])

    def test_ablehnungen_ohne_anfrage(self):
        self.weg = oo.Weg("senden", "klassisch", oo.SENDEN_GRUND)
        for an, text, gruppe, muster in (
            (("Anna",), "Hallo", "", "nicht eindeutig"),
            (("kunde@kunde.example",), "Hallo", "", "intern"),
            ((MAX,), "x" * (ot.TEXT_MAX + 1), "", "kürzen"),
            ((MAX,), "", "", "Text"),
            ((MAX,), "Hallo", "Gruppe", "mindestens zwei"),
            ((), "Hallo", "", "Empfänger"),
        ):
            a = self.anfragen(an=an, text=text, gruppenname=gruppe)
            self.assertEqual(a["status"], "rejected", (an, a))
            self.assertIn(muster, a["summary"])
        self.assertEqual(host.PENDING, {})

    def test_namen_im_neuen_outlook_brauchen_die_adresse(self):
        a = self.anfragen(an=("Max Weber",))
        self.assertEqual(a["status"], "rejected")
        self.assertIn("Mailadresse", a["summary"])

    def test_office_aus_und_ratengrenze(self):
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(self.anfragen()["status"], "blocked")
        self.schalter.unlink()
        with mock.patch.object(host, "TEAMS_PRO_STUNDE", 2):
            self.assertEqual(self.anfragen(text="eins")["status"], "needs_approval")
            self.assertEqual(self.anfragen(text="zwei")["status"], "needs_approval")
            r = self.anfragen(text="drei")
        self.assertEqual(r["status"], "rejected")
        self.assertIn("je Stunde", r["summary"])

    def test_gleiche_nachricht_gibt_dieselbe_anfrage(self):
        self.assertEqual(self.anfragen()["approval_id"], self.anfragen()["approval_id"])
        self.assertEqual(len(host.PENDING), 1)


class Freigabe(_Basis):
    def test_nach_dem_klick_genau_einmal_geoeffnet(self):
        a = self.anfragen(an=(MAX, ANNA), gruppenname="Angebot X")
        r = self.freigeben(a)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["weg"], "app")
        self.assertIn("selbst mit Enter", r["summary"])
        self.assertEqual(len(self.geoeffnet), 1)
        self.assertTrue(self.geoeffnet[0].startswith("msteams://teams.microsoft.com/l/chat/0/0?users="))
        self.assertEqual(self.freigeben(a), host.UNBEKANNT)
        self.assertEqual(len(self.geoeffnet), 1)

    def test_nein_oeffnet_nichts(self):
        self.assertEqual(self.freigeben(self.anfragen(), ja=False)["status"], "rejected")
        self.assertEqual(self.geoeffnet, [])

    def test_ohne_schluessel_nichts(self):
        a = self.anfragen()
        self.assertEqual(host.entscheiden(a["approval_id"], True, "falsch" * 8)["status"], "blocked")
        self.assertEqual(self.geoeffnet, [])

    def test_office_aus_nach_der_karte(self):
        a = self.anfragen()
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(self.freigeben(a)["status"], "blocked")
        self.assertEqual(self.geoeffnet, [])

    def test_ohne_app_im_browser(self):
        a = self.anfragen()
        with mock.patch.object(ot, "app_registriert", return_value=False):
            r = self.freigeben(a)
        self.assertEqual(r["weg"], "browser")
        self.assertTrue(self.geoeffnet[0].startswith("https://teams.microsoft.com/l/chat/0/0?users="))


class Faehigkeiten(_Basis):
    def test_office_faehigkeiten_meldet_teams(self):
        for verfuegbar in (True, False):
            with mock.patch.object(host.office_com, "faehigkeiten", return_value={"formate": ["word"]}), \
                    mock.patch.object(ot, "verfuegbar", return_value=verfuegbar):
                self.assertIs(host.office_faehigkeiten()["teams"], verfuegbar)

    def test_teams_werkzeug_steht_nicht_in_llm_tools(self):
        quelle = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_host.py").read_text(encoding="utf-8")
        block = quelle.split("LLM_TOOLS = [", 1)[1].split("]", 1)[0]
        self.assertNotIn("teams_chat_anfragen", block)

    def test_kein_werkzeug_kann_in_teams_senden(self):
        quelle = (Path(__file__).resolve().parent / "office_teams.py").read_text(encoding="utf-8")
        for verboten in ("SendKeys", "send_keys", "keybd_event", "SendInput", "graph.microsoft.com"):
            self.assertNotIn(verboten, quelle)


if __name__ == "__main__":
    unittest.main()
