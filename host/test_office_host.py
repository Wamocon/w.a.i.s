"""Tests für die Office-Werkzeuge im Host (wamo_host.py): office_faehigkeiten, office_datei_erstellen, office_datei_oeffnen.

Die Werkzeuge ruft nur der Kern (nie das Sprachmodell). Geprüft wird hier, was der Host selbst erzwingt: Schalter office.aus,
Grenzen und Formate, Ratengrenze, nur Registerdateien öffnen, Audit ohne Inhalte. Word und das Öffnen sind Attrappen.
"""

import asyncio
import json
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import office_ablage
import office_com
import wamo_host as host

GEHEIMER_SATZ = "Vertrauliche Zeile im Angebot"
DOKUMENT = {"art": "dokument", "titel": "Angebot", "text": f"# Angebot\n{GEHEIMER_SATZ}"}
TABELLE = {"art": "tabelle", "titel": "Liste", "spalten": ["a"], "zeilen": [["=1+1"]]}


class _Basis(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)
        (wurzel / "Dokumente").mkdir()
        self.ablage = office_ablage.Ablage(wurzel / "Dokumente", wurzel / "WAMO" / "ablage.json")
        self.schalter = wurzel / "WAMO" / "office.aus"
        self.audit: list[dict] = []
        self.geoeffnet: list[Path] = []
        for p in (
            mock.patch.object(host, "_audit", side_effect=self.audit.append),
            mock.patch.object(host, "_office_ablage", return_value=self.ablage),
            mock.patch.object(host, "OFFICE_AUS", self.schalter),
            mock.patch.object(host, "_datei_oeffnen", side_effect=self.geoeffnet.append),
            mock.patch.object(host, "_ist_gesperrt", return_value=False),
            mock.patch.object(office_com, "word_vorhanden", return_value=True),
        ):
            p.start()
            self.addCleanup(p.stop)
        host._rate_zeiten.clear()
        self.addCleanup(host._rate_zeiten.clear)
        host._recent_actions.clear()

    def erstellen(self, fmt, inhalt, oeffnen=True, canvas_id=""):
        return asyncio.run(host.office_datei_erstellen(fmt, inhalt, oeffnen, canvas_id))

    def audit_text(self) -> str:
        return json.dumps(self.audit, ensure_ascii=False)


class Faehigkeiten(_Basis):
    def test_meldet_formate_und_ordner(self):
        antwort = host.office_faehigkeiten()
        self.assertEqual(antwort["status"], "success")
        self.assertIn("pdf", antwort["formate"])
        self.assertEqual(antwort["ordner"], "Dokumente\\WAIS")

    def test_ohne_word_kein_pdf(self):
        with mock.patch.object(office_com, "word_vorhanden", return_value=False):
            self.assertNotIn("pdf", host.office_faehigkeiten()["formate"])

    def test_schalter_office_aus_sperrt_alles(self):
        self.schalter.parent.mkdir(parents=True, exist_ok=True)
        self.schalter.write_text("", encoding="utf-8")
        self.assertEqual(host.office_faehigkeiten()["formate"], [])
        self.assertEqual(self.erstellen("word", DOKUMENT)["status"], "blocked")
        self.assertEqual(host.office_datei_oeffnen("0123456789abcdef")["status"], "blocked")
        self.assertEqual(list(self.ablage.wurzel.iterdir()), [])  # nichts angelegt
        self.assertEqual(self.geoeffnet, [])


class Erstellen(_Basis):
    def test_word_wird_gespeichert_registriert_und_geoeffnet(self):
        antwort = self.erstellen("word", DOKUMENT, canvas_id="11111111-1111-4111-8111-111111111111")
        self.assertEqual(antwort["status"], "success", antwort)
        datei = antwort["datei"]
        self.assertTrue(datei["name"].endswith(" Angebot.docx"))
        pfad = self.ablage.pfad(datei["kennung"])
        self.assertEqual(self.geoeffnet, [pfad])
        self.assertTrue(antwort["geoeffnet"])
        self.assertEqual(datei["ordner"], "Dokumente\\WAIS")
        self.assertEqual(datei["pfad"], str(pfad))
        eintrag = next(a for a in self.audit if a.get("tool") == "office_datei_erstellen" and a.get("risk") == "change")
        self.assertEqual(eintrag["format"], "word")
        self.assertEqual(len(eintrag["sha256"]), 64)
        self.assertNotIn(GEHEIMER_SATZ, self.audit_text())  # Audit ohne Inhalte

    def test_ohne_oeffnen(self):
        antwort = self.erstellen("markdown", DOKUMENT, oeffnen=False)
        self.assertEqual(antwort["status"], "success")
        self.assertFalse(antwort["geoeffnet"])
        self.assertEqual(self.geoeffnet, [])

    def test_bei_gesperrtem_bildschirm_gespeichert_aber_nicht_geoeffnet(self):
        with mock.patch.object(host, "_ist_gesperrt", return_value=True):
            antwort = self.erstellen("word", DOKUMENT)
        self.assertEqual(antwort["status"], "success")
        self.assertFalse(antwort["geoeffnet"])
        self.assertEqual(self.geoeffnet, [])
        self.assertIn("gesperrt", antwort["summary"])

    def test_pdf_ueber_word(self):
        with mock.patch.object(office_com, "pdf_aus_docx", return_value=b"%PDF-1.7 x") as umwandeln:
            antwort = self.erstellen("pdf", DOKUMENT)
        self.assertEqual(antwort["status"], "success", antwort)
        self.assertTrue(umwandeln.call_args.args[0].startswith(b"PK"))  # aus der selbst gebauten Word-Datei
        self.assertEqual(self.ablage.pfad(antwort["datei"]["kennung"]).read_bytes(), b"%PDF-1.7 x")

    def test_pdf_fehler_wird_gemeldet_und_nichts_gespeichert(self):
        with mock.patch.object(office_com, "pdf_aus_docx", side_effect=office_com.PdfFehler("Word antwortet nicht")):
            antwort = self.erstellen("pdf", DOKUMENT)
        self.assertEqual(antwort["status"], "error")
        self.assertIn("Word", antwort["summary"])
        self.assertEqual(self.ablage.eintraege(), [])

    def test_unpassendes_format_und_kaputte_inhalte_werden_abgelehnt(self):
        for fmt, inhalt in (("excel", DOKUMENT), ("exe", DOKUMENT), ("word", {"art": "bild"}), ("word", "text"),
                            ("word", {"art": "dokument", "titel": "x", "text": "a" * 100_001})):
            self.assertEqual(self.erstellen(fmt, inhalt)["status"], "rejected", (fmt, str(inhalt)[:40]))
        self.assertEqual(self.ablage.eintraege(), [])

    def test_fremde_canvas_kennung_wird_nicht_uebernommen(self):
        antwort = self.erstellen("csv", TABELLE, canvas_id="../../x")
        self.assertEqual(antwort["status"], "success")
        self.assertIsNone(self.ablage.eintraege()[-1]["canvas_id"])

    def test_ratengrenze(self):
        for _ in range(host.OFFICE_PRO_MINUTE):
            self.assertEqual(self.erstellen("markdown", DOKUMENT, oeffnen=False)["status"], "success")
        self.assertEqual(self.erstellen("markdown", DOKUMENT, oeffnen=False)["status"], "rejected")

    def test_nie_ueberschreiben_auch_ueber_das_werkzeug(self):
        a = self.erstellen("csv", TABELLE, oeffnen=False)["datei"]["name"]
        b = self.erstellen("csv", TABELLE, oeffnen=False)["datei"]["name"]
        self.assertNotEqual(a, b)


class Oeffnen(_Basis):
    def test_nur_registerdateien(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        self.assertEqual(host.office_datei_oeffnen(datei["kennung"])["status"], "success")
        self.assertEqual(self.geoeffnet, [self.ablage.pfad(datei["kennung"])])
        for kennung in ("fedcba9876543210", "../x", "", "C:\\Windows\\notepad.exe"):
            self.assertEqual(host.office_datei_oeffnen(kennung)["status"], "rejected", kennung)
        self.assertEqual(len(self.geoeffnet), 1)

    def test_gesperrter_bildschirm(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        with mock.patch.object(host, "_ist_gesperrt", return_value=True):
            self.assertEqual(host.office_datei_oeffnen(datei["kennung"])["status"], "locked")
        self.assertEqual(self.geoeffnet, [])


class NieFuerDasModell(unittest.TestCase):
    def test_office_werkzeuge_stehen_nicht_in_llm_tools(self):
        quelle = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_host.py").read_text(encoding="utf-8")
        block = quelle.split("LLM_TOOLS = [", 1)[1].split("]", 1)[0]
        for name in ("office_faehigkeiten", "office_datei_erstellen", "office_datei_oeffnen"):
            self.assertNotIn(name, block)

    def test_datum_im_dateinamen_ist_heute(self):
        self.assertEqual(office_ablage.dateiname("x", "word", date(2026, 1, 2)), "2026-01-02 x.docx")
