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
        self.im_ordner: list[Path] = []
        for p in (
            mock.patch.object(host, "_audit", side_effect=self.audit.append),
            mock.patch.object(host, "_office_ablage", return_value=self.ablage),
            mock.patch.object(host, "OFFICE_AUS", self.schalter),
            mock.patch.object(host, "_datei_oeffnen", side_effect=self.geoeffnet.append),
            mock.patch.object(host, "_ordner_zeigen", side_effect=self.im_ordner.append),
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

    def oeffnen(self, kennung, im_ordner=False):
        return asyncio.run(host.office_datei_oeffnen(kennung, im_ordner))

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
        self.assertEqual(self.oeffnen("0123456789abcdef")["status"], "blocked")
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

    def test_pfad_kommt_aus_dem_speichern(self):
        """Kein zweites Nachschlagen im Register zwischen Speichern und Öffnen."""
        with mock.patch.object(self.ablage, "pfad", side_effect=AssertionError("nicht noch einmal nachschlagen")):
            antwort = self.erstellen("word", DOKUMENT)
        self.assertEqual(antwort["status"], "success", antwort)
        self.assertEqual(self.geoeffnet, [Path(antwort["datei"]["pfad"])])

    def test_bei_offener_freigabe_gespeichert_aber_nicht_geoeffnet(self):
        with mock.patch.object(host, "_eingabe_vorab", return_value=dict(host.WARTET)) as vorab:
            antwort = self.erstellen("word", DOKUMENT)
        vorab.assert_called_once_with("office_datei_erstellen")
        self.assertEqual(antwort["status"], "success")
        self.assertFalse(antwort["geoeffnet"])
        self.assertEqual(self.geoeffnet, [])
        self.assertIn("Freigabe", antwort["summary"])

    def test_ohne_oeffnen_keine_vorabpruefung(self):
        with mock.patch.object(host, "_eingabe_vorab", side_effect=AssertionError("nicht nötig")):
            self.assertEqual(self.erstellen("markdown", DOKUMENT, oeffnen=False)["status"], "success")

    def test_hoechstens_ein_bau_gleichzeitig(self):
        self.assertTrue(host._OFFICE_BAU.acquire(blocking=False))
        try:
            antwort = self.erstellen("word", DOKUMENT)
        finally:
            host._OFFICE_BAU.release()
        self.assertEqual(antwort["status"], "rejected")
        self.assertIn("gerade", antwort["summary"])
        self.assertEqual(self.ablage.eintraege(), [])
        self.assertEqual(self.erstellen("word", DOKUMENT)["status"], "success")  # danach wieder frei

    def test_bau_ueber_der_frist_wird_verworfen(self):
        with mock.patch.object(host, "OFFICE_FRIST_SECS", -1):
            antwort = self.erstellen("word", DOKUMENT)
        self.assertEqual(antwort["status"], "error")
        self.assertIn("zu lange", antwort["summary"])
        self.assertEqual(self.ablage.eintraege(), [])  # nichts gespeichert
        self.assertEqual(list(self.ablage.wurzel.rglob("*.docx")), [])
        self.assertEqual(self.geoeffnet, [])
        self.assertTrue(any(a.get("grund") == "Frist" for a in self.audit))
        self.assertEqual(self.erstellen("word", DOKUMENT)["status"], "success")  # die Sperre ist wieder frei

    def test_frist_liegt_vor_dem_abbruch_im_tunnel(self):
        tunnel = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_tunnel.py").read_text(encoding="utf-8")
        self.assertIn('"office_datei_erstellen": 80', tunnel)
        self.assertLess(host.OFFICE_FRIST_SECS, 80 - 5)
        self.assertGreater(host.OFFICE_FRIST_SECS, office_com.PDF_TIMEOUT_SECS + 20)


class Oeffnen(_Basis):
    def test_nur_registerdateien(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        self.assertEqual(self.oeffnen(datei["kennung"])["status"], "success")
        self.assertEqual(self.geoeffnet, [self.ablage.pfad(datei["kennung"])])
        for kennung in ("fedcba9876543210", "../x", "", "C:\\Windows\\notepad.exe"):
            self.assertEqual(self.oeffnen(kennung)["status"], "rejected", kennung)
        self.assertEqual(len(self.geoeffnet), 1)

    def test_gesperrter_bildschirm(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        with mock.patch.object(host, "_ist_gesperrt", return_value=True):
            self.assertEqual(self.oeffnen(datei["kennung"])["status"], "locked")
        self.assertEqual(self.geoeffnet, [])

    def test_offene_freigabe(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        with mock.patch.object(host, "_eingabe_vorab", return_value=dict(host.WARTET)):
            self.assertEqual(self.oeffnen(datei["kennung"])["status"], "wartet")
        self.assertEqual(self.geoeffnet, [])

    def test_doppelklick_bekommt_eine_freundliche_meldung(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        self.assertEqual(self.oeffnen(datei["kennung"])["status"], "success")
        zweiter = self.oeffnen(datei["kennung"])
        self.assertEqual(zweiter["status"], "duplicate")
        self.assertEqual(zweiter["summary"], host.OFFICE_SCHON_GEOEFFNET)
        self.assertIn("geöffnet", zweiter["summary"])  # für Menschen, mit Umlauten, nicht der Satz für das Modell
        self.assertEqual(len(self.geoeffnet), 1)

    def test_im_ordner_zeigt_den_explorer_statt_die_datei_zu_oeffnen(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        antwort = self.oeffnen(datei["kennung"], im_ordner=True)
        self.assertEqual(antwort["status"], "success", antwort)
        self.assertIn("Dokumente\\WAIS", antwort["summary"])
        self.assertEqual(self.im_ordner, [self.ablage.pfad(datei["kennung"])])
        self.assertEqual(self.geoeffnet, [])
        self.assertTrue(any(e.get("im_ordner") is True for e in self.audit))
        # Ordner und Datei sind zwei verschiedene Aktionen: kein falscher Doppelklick
        self.assertEqual(self.oeffnen(datei["kennung"])["status"], "success")
        self.assertEqual(self.oeffnen(datei["kennung"], im_ordner=True)["status"], "duplicate")

    def test_im_ordner_nur_mit_echtem_wahrheitswert(self):
        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        self.assertEqual(self.oeffnen(datei["kennung"], im_ordner="ja")["status"], "success")
        self.assertEqual(self.im_ordner, [])
        self.assertEqual(len(self.geoeffnet), 1)

    def test_haengendes_oeffnen_blockiert_den_host_nicht(self):
        """Befund 17.11.2026: os.startfile wartete 6 s auf Word, der ganze Host stand still. Jetzt läuft es im Thread."""
        import threading
        import time

        datei = self.erstellen("word", DOKUMENT, oeffnen=False)["datei"]
        frei = threading.Event()

        def haengt(_pfad):
            frei.wait(5)

        async def ablauf():
            with mock.patch.object(host, "_datei_oeffnen", side_effect=haengt):
                aufgabe = asyncio.create_task(host.office_datei_oeffnen(datei["kennung"]))
                start = time.monotonic()
                await asyncio.sleep(0.05)  # der Hauptfaden kommt sofort wieder dran
                frei_nach = time.monotonic() - start
                frei.set()
                return frei_nach, await aufgabe

        frei_nach, antwort = asyncio.run(ablauf())
        self.assertLess(frei_nach, 1.0)
        self.assertEqual(antwort["status"], "success")


class DateiOeffnen(unittest.TestCase):
    """_datei_oeffnen selbst: nur die sechs festen Endungen gehen an das Standardprogramm."""

    def test_nur_feste_endungen(self):
        with mock.patch.object(host.platform, "system", return_value="Windows"), \
             mock.patch.object(host.os, "startfile", create=True) as starten:
            for name in ("a.exe", "a.lnk", "a.docm", "a.html", "a", "a.docx."):
                with self.assertRaises(RuntimeError, msg=name):
                    host._datei_oeffnen(Path("C:/WAIS") / name)
            starten.assert_not_called()
            for endung in (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".md"):
                host._datei_oeffnen(Path("C:/WAIS") / f"a{endung}")
            self.assertEqual(starten.call_count, 6)


class OrdnerZeigen(unittest.TestCase):
    """_ordner_zeigen selbst: fester Explorer mit /select, nur die sechs Endungen, nie ein Anführungszeichen im Pfad."""

    def test_explorer_mit_markierter_datei(self):
        pfad = Path("C:/Users/x/Dokumente/WAIS/2026-11-17 Typischer Tag.docx")
        with mock.patch.object(host.platform, "system", return_value="Windows"), \
             mock.patch.dict(host.os.environ, {"SystemRoot": "C:\\Windows"}), \
             mock.patch.object(host.subprocess, "Popen") as popen:
            host._ordner_zeigen(pfad)
        befehl = popen.call_args.args[0]
        self.assertEqual(befehl, f'"{Path("C:/Windows") / "explorer.exe"}" /select,"{pfad}"')

    def test_nur_feste_endungen_und_kein_anfuehrungszeichen(self):
        with mock.patch.object(host.platform, "system", return_value="Windows"), \
             mock.patch.object(host.subprocess, "Popen") as popen:
            for name in ("a.exe", "a.lnk", "a", "a.docx."):
                with self.assertRaises(RuntimeError, msg=name):
                    host._ordner_zeigen(Path("C:/WAIS") / name)
            with self.assertRaises(RuntimeError):
                host._ordner_zeigen(Path('C:/WAIS/a" & calc & ".docx'))
            popen.assert_not_called()

    def test_ohne_windows_nichts(self):
        with mock.patch.object(host.platform, "system", return_value="Linux"), \
             mock.patch.object(host.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                host._ordner_zeigen(Path("C:/WAIS/a.docx"))
            popen.assert_not_called()


class Einmalig(unittest.TestCase):
    def test_ablage_wird_nur_einmal_angelegt_auch_aus_threads(self):
        import threading
        import time

        aufrufe = []

        def langsam():
            aufrufe.append(1)
            time.sleep(0.05)
            return object()

        vorher = host._OFFICE_ABLAGE
        host._OFFICE_ABLAGE = None
        try:
            ergebnisse = []
            with mock.patch.object(office_ablage.Ablage, "standard", side_effect=langsam):
                faeden = [threading.Thread(target=lambda: ergebnisse.append(host._office_ablage())) for _ in range(8)]
                for f in faeden:
                    f.start()
                for f in faeden:
                    f.join(5)
        finally:
            host._OFFICE_ABLAGE = vorher
        self.assertEqual(len(aufrufe), 1)
        self.assertEqual(len({id(e) for e in ergebnisse}), 1)
        self.assertEqual(len(ergebnisse), 8)


class NieFuerDasModell(unittest.TestCase):
    def test_office_werkzeuge_stehen_nicht_in_llm_tools(self):
        quelle = (Path(__file__).resolve().parent.parent / "voice-core" / "pc_host.py").read_text(encoding="utf-8")
        block = quelle.split("LLM_TOOLS = [", 1)[1].split("]", 1)[0]
        for name in ("office_faehigkeiten", "office_datei_erstellen", "office_datei_oeffnen"):
            self.assertNotIn(name, block)

    def test_datum_im_dateinamen_ist_heute(self):
        self.assertEqual(office_ablage.dateiname("x", "word", date(2026, 1, 2)), "2026-01-02 x.docx")
