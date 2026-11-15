"""Tests für das OneNote-Werkzeug im Host (wamo_host.py): onenote_seite_anfragen (critical, nur per Freigabekarte) und die Ausführung
nach dem Klick (freigabe_entscheiden, Art onenote).

Das Werkzeug ruft nur der Kern (nie das Sprachmodell). Geprüft wird, was der Host selbst erzwingt: Schalter office.aus, Inhalt und
Länge, Ratengrenze, Rückfall ohne OneNote, Karte mit Titel und ganzem Inhalt, genau einmal ausführen, Audit ohne Inhalte. OneNote ist
eine Attrappe (office_onenote.ziel_pruefen und seite_anlegen).
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import office_onenote
import wamo_host as host

SCHLUESSEL = "k" * 43
GEHEIM = "Vertrauliche Zeile im Angebot"
DOKUMENT = {"art": "dokument", "titel": "Angebot", "text": f"# Angebot\n- {GEHEIM}"}
# Erfundenes Konto: Das Notizbuch W.A.I.S. fehlt noch und entsteht erst nach dem Klick
ZIEL = office_onenote.Ziel(konto="anna@firma.example", notizbuch_url="https://firma-my.sharepoint.com/personal/anna/Documents/W.A.I.S",
                           notizbuch_id="", notizbuch="W.A.I.S.", abschnitt="W.A.I.S", abschnitt_id="")
ANGELEGT = {"seite_id": "{seite-1}", "abschnitt_id": "{ab-1}", "abschnitt_neu": True, "notizbuch_neu": True, "notizbuch": "W.A.I.S.",
            "abschnitt": "W.A.I.S"}


class _Basis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.schalter = Path(self._tmp.name) / "WAMO" / "office.aus"
        self.audit: list[dict] = []
        self.vorhanden = mock.Mock(return_value=True)
        self.ziel = mock.Mock(return_value=ZIEL)
        self.anlegen = mock.Mock(return_value=dict(ANGELEGT))
        for p in (
            mock.patch.object(host, "_audit", side_effect=self.audit.append),
            mock.patch.object(host, "OFFICE_AUS", self.schalter),
            mock.patch.object(host, "_ist_gesperrt", return_value=False),
            mock.patch.object(host, "FREIGABE_SCHLUESSEL", SCHLUESSEL),
            mock.patch.object(host, "ONENOTE_BREMSE", office_onenote.Bremse(office_onenote.SEITEN_JE_STUNDE, 3600)),
            mock.patch.object(office_onenote, "onenote_vorhanden", self.vorhanden),
            mock.patch.object(office_onenote, "ziel_pruefen", self.ziel),
            mock.patch.object(office_onenote, "seite_anlegen", self.anlegen),
        ):
            p.start()
            self.addCleanup(p.stop)
        host.PENDING.clear()
        self.addCleanup(host.PENDING.clear)

    def anfragen(self, inhalt=None, titel="", anlass=""):
        return asyncio.run(host.onenote_seite_anfragen(inhalt or DOKUMENT, titel, anlass))

    def audit_text(self) -> str:
        return json.dumps(self.audit, ensure_ascii=False, default=str)


class Faehigkeiten(_Basis):
    def test_meldet_ob_onenote_da_ist(self):
        self.assertIs(host.office_faehigkeiten()["onenote"], True)
        self.vorhanden.return_value = False
        self.assertIs(host.office_faehigkeiten()["onenote"], False)


class Anfrage(_Basis):
    def test_karte_mit_titel_ganzem_inhalt_notizbuch_und_abschnitt(self):
        antwort = self.anfragen(anlass="Niko will es in OneNote")
        self.assertEqual(antwort["status"], "needs_approval", antwort)
        self.assertEqual(antwort["aktion"], "onenote")
        self.assertEqual(antwort["grund"], "Seite in OneNote anlegen")
        self.assertEqual(antwort["detail"], f"Seite: Angebot\nInhalt:\n> Angebot\n> • {GEHEIM}")
        self.assertEqual(antwort["ziel"], "OneNote, Notizbuch W.A.I.S. (wird neu angelegt), Abschnitt W.A.I.S (wird angelegt), "
                                          "OneDrive der Firma (anna@firma.example)")
        self.assertEqual(antwort["gueltig_s"], host.FREIGABE_GUELTIG_SECS)  # wie powershell und webseite (300 s)
        self.assertNotIn("onenote", host.EINGABE_ARTEN)
        self.assertEqual(antwort["anlass"], "Niko will es in OneNote")
        eintrag = host.PENDING[antwort["approval_id"]]
        self.assertEqual((eintrag["art"], eintrag["ziel"], eintrag["seite"].titel), ("onenote", ZIEL, "Angebot"))
        self.assertNotIn(GEHEIM, self.audit_text())
        self.anlegen.assert_not_called()  # vor dem Klick entsteht nichts

    def test_gleiche_anfrage_gibt_keine_zweite_karte(self):
        erste = self.anfragen()
        with mock.patch.object(host, "_eingabe_vorab", return_value=None):  # sonst ruht alles, solange die erste offen ist
            zweite = self.anfragen()
        self.assertEqual(erste["approval_id"], zweite["approval_id"])
        self.assertEqual(len(host.PENDING), 1)

    def test_eingaben_ruhen_solange_die_karte_offen_ist(self):
        self.anfragen()
        self.assertEqual(host._eingabe_vorab("tastatur_tippen")["status"], "wartet")

    def test_ohne_onenote_rueckfall_auf_word_ohne_karte(self):
        self.vorhanden.return_value = False
        antwort = self.anfragen()
        self.assertEqual((antwort["status"], antwort["rueckfall"]), ("rejected", "word"))
        self.assertIn("OneNote", antwort["summary"])
        self.ziel.assert_not_called()
        self.assertEqual(host.PENDING, {})

    def test_ohne_eindeutiges_firmenkonto_rueckfall_auf_word(self):
        self.ziel.side_effect = office_onenote.OneNoteFehler(office_onenote.KEIN_FIRMENKONTO, rueckfall=True)
        antwort = self.anfragen()
        self.assertEqual((antwort["status"], antwort["rueckfall"]), ("rejected", "word"))
        self.assertIn("kein OneDrive der Firma", antwort["summary"])
        self.assertEqual(host.PENDING, {})

    def test_onenote_nicht_bereit_rueckfall_auf_word(self):
        self.ziel.side_effect = office_onenote.OneNoteFehler("In OneNote ist kein Notizbuch geöffnet.", rueckfall=True)
        antwort = self.anfragen()
        self.assertEqual((antwort["status"], antwort["rueckfall"]), ("rejected", "word"))
        self.assertIn("kein Notizbuch", antwort["summary"])
        self.assertEqual(host.PENDING, {})

    def test_beschaeftigt_oder_zu_langsam_ohne_rueckfall(self):
        self.ziel.side_effect = office_onenote.OneNoteFehler("OneNote ist noch mit dem vorigen Auftrag beschäftigt.")
        antwort = self.anfragen()
        self.assertEqual(antwort["status"], "rejected")
        self.assertNotIn("rueckfall", antwort)

    def test_fehlversuche_verbrauchen_die_ratengrenze_nicht(self):
        self.ziel.side_effect = office_onenote.OneNoteFehler("beschäftigt")
        for _ in range(office_onenote.SEITEN_JE_STUNDE + 2):
            self.anfragen()
        self.ziel.side_effect = None
        self.assertEqual(self.anfragen()["status"], "needs_approval")

    def test_zu_lang_fuer_die_karte_ohne_onenote_zu_fragen(self):
        antwort = self.anfragen({"art": "dokument", "titel": "Lang", "text": "\n".join(["Zeile mit Text"] * 200)})
        self.assertEqual(antwort["status"], "rejected")
        self.assertNotIn("rueckfall", antwort)
        self.assertIn("Word", antwort["summary"])
        self.ziel.assert_not_called()

    def test_kaputter_inhalt_und_titel_werden_abgelehnt(self):
        for inhalt, titel in (({"art": "bild", "titel": "x", "text": "y"}, ""), (DOKUMENT, "x" * 301), ("kein dict", "")):
            antwort = self.anfragen(inhalt, titel)
            self.assertEqual(antwort["status"], "rejected", antwort)
        self.ziel.assert_not_called()

    def test_schalter_office_aus_sperrt_auch_onenote(self):
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(self.anfragen()["status"], "blocked")
        self.ziel.assert_not_called()

    def test_bildschirm_gesperrt(self):
        with mock.patch.object(host, "_ist_gesperrt", return_value=True):
            self.assertEqual(self.anfragen()["status"], "locked")

    def test_ratengrenze_zehn_seiten_je_stunde(self):
        for i in range(office_onenote.SEITEN_JE_STUNDE):
            antwort = self.anfragen({**DOKUMENT, "text": f"Text {i}"})
            self.assertEqual(antwort["status"], "needs_approval")
            host.PENDING.clear()
        self.assertEqual(self.anfragen()["status"], "rejected")


class Ausfuehren(_Basis):
    def test_nach_dem_klick_genau_einmal_mit_dem_inhalt_der_karte(self):
        antrag = self.anfragen(titel="Neuer Titel")
        ergebnis = host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)
        self.assertEqual(ergebnis["status"], "success", ergebnis)
        self.assertIn("Neuer Titel", ergebnis["summary"])
        self.assertIn("Notizbuch W.A.I.S. (neu angelegt), Abschnitt W.A.I.S (neu angelegt)", ergebnis["summary"])
        seite, ziel = self.anlegen.call_args.args
        self.assertEqual((seite.titel, seite.inhalt.text, ziel), ("Neuer Titel", DOKUMENT["text"], ZIEL))
        self.assertEqual(self.anlegen.call_args.kwargs, {"zeigen": True})
        self.assertEqual(host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)["status"], "error")  # nicht noch einmal
        self.assertEqual(self.anlegen.call_count, 1)
        self.assertNotIn(GEHEIM, self.audit_text())
        self.assertIn("{seite-1}", self.audit_text())

    def test_ablehnen_und_falscher_schluessel_fuehren_nichts_aus(self):
        antrag = self.anfragen()
        self.assertEqual(host.entscheiden(antrag["approval_id"], True, "falsch")["status"], "blocked")
        self.assertEqual(host.entscheiden(antrag["approval_id"], False, SCHLUESSEL)["status"], "rejected")
        self.anlegen.assert_not_called()

    def test_office_aus_nach_der_anfrage_sperrt_auch_die_ausfuehrung(self):
        antrag = self.anfragen()
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)["status"], "blocked")
        self.anlegen.assert_not_called()

    def test_fehler_von_onenote_wird_gemeldet(self):
        self.anlegen.side_effect = office_onenote.OneNoteFehler("OneNote hat nicht in der Zeit geantwortet.")
        antrag = self.anfragen()
        ergebnis = host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)
        self.assertEqual(ergebnis, {"status": "error", "summary": "OneNote hat nicht in der Zeit geantwortet."})

    def test_bei_gesperrtem_bildschirm_bleibt_die_anfrage_offen(self):
        antrag = self.anfragen()
        with mock.patch.object(host, "_ist_gesperrt", return_value=True):
            self.assertEqual(host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)["status"], "locked")
        self.anlegen.assert_not_called()
        self.assertEqual(host.entscheiden(antrag["approval_id"], True, SCHLUESSEL)["status"], "success")


class NieFuerDasModell(unittest.TestCase):
    def test_onenote_werkzeug_steht_nicht_in_llm_tools(self):
        quelle = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_host.py").read_text(encoding="utf-8")
        block = quelle.split("LLM_TOOLS = [", 1)[1].split("]", 1)[0]
        self.assertNotIn("onenote_seite_anfragen", block)
