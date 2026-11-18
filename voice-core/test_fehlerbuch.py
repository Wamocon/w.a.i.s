"""Tests für fehlerbuch.py: Was in einer Sitzung nicht ging, sammelt der Kern im Speicher, und fehler_erklaeren gibt es dem Modell
(Wunsch von Niko vom 18.11.2026). Dazu die Verdrahtung in bot.py (statisch) und die Persona-Regel."""

import asyncio
import json
from pathlib import Path
from unittest import mock

from pipecat.frames.frames import FunctionCallResultFrame

import fehlerbuch as fb
import labor
import stimme_gate

HIER = Path(__file__).parent


class Uhr:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_werkzeugfehler_werden_eingetragen_erfolge_nicht():
    buch = fb.Fehlerbuch(uhr=Uhr())
    assert buch.aus_ergebnis("canvas_exportieren", json.dumps({"status": "success", "gespeichert": True})) is False
    assert buch.aus_ergebnis("programm_oeffnen", {"status": "duplicate", "summary": "schon"}) is False
    assert buch.aus_ergebnis("programm_oeffnen", "kein JSON") is False
    assert buch.aus_ergebnis("entwicklung_vorbereiten", json.dumps(
        {"status": "blocked", "grund": "Stimmprüfung: Stimme nicht sicher erkannt", "hinweis": "Nicht erneut versuchen."})) is True
    assert buch.aus_ergebnis("office", {"status": "error", "summary": "Der PC antwortet nicht."}) is True
    eintraege = buch.antwort()["eintraege"]
    assert [e["was"] for e in eintraege] == ["office", "entwicklung_vorbereiten"]  # neueste zuerst
    assert eintraege[1]["grund"] == "Stimmprüfung: Stimme nicht sicher erkannt"  # grund vor hinweis
    assert eintraege[0]["status"] == "error" and eintraege[0]["quelle"] == "werkzeug"


def test_derselbe_aufruf_zaehlt_einmal():
    buch = fb.Fehlerbuch()
    fehler = {"status": "error", "summary": "x"}
    assert buch.aus_ergebnis("a", fehler, "call-1") is True
    assert buch.aus_ergebnis("a", fehler, "call-1") is False
    assert len(buch.antwort()["eintraege"]) == 1


def test_gescheiterte_klicks_und_verworfene_aeusserungen():
    uhr = Uhr()
    buch = fb.Fehlerbuch(uhr=uhr)
    assert buch.aus_meldung({"type": "auftrag_quittung", "job": "j1", "ok": False,
                             "grund": "Diese Auftragsart ist im Kanal nicht erlaubt."}) is True
    assert buch.aus_meldung({"type": "auftrag_quittung", "job": "j2", "ok": True}) is False
    assert buch.aus_meldung({"type": "datei", "ok": False}) is True  # ohne Grund: trotzdem eingetragen
    assert buch.aus_meldung({"type": "canvas", "item": {}}) is False
    assert buch.aus_meldung("kein dict") is False
    for _ in range(3):
        assert buch.aus_meldung({"type": "stimme", "ignoriert": True, "zeit": 1}) is False
    buch.aus_meldung({"type": "stimme", "ignoriert": False})
    antwort = buch.antwort()
    assert [e["was"] for e in antwort["eintraege"]] == ["datei", "auftrag_quittung"]
    assert antwort["eintraege"][0]["grund"] == fb.OHNE_GRUND
    assert antwort["eintraege"][1]["grund"] == "Diese Auftragsart ist im Kanal nicht erlaubt."
    assert antwort["verworfene_aeusserungen_10_min"] == 3
    uhr.t += fb.VERWORFEN_FENSTER_SECS + 1
    assert buch.antwort()["verworfene_aeusserungen_10_min"] == 0


def test_grenzen_kuerzen_und_zeit():
    uhr = Uhr()
    buch = fb.Fehlerbuch(uhr=uhr, max_eintraege=3)
    for i in range(5):
        buch.eintragen("werkzeug", f"w{i}", "error", "x" * 1000 + "‮")
        uhr.t += 10
    antwort = buch.antwort()
    assert [e["was"] for e in antwort["eintraege"]] == ["w4", "w3", "w2"]
    assert len(antwort["eintraege"][0]["grund"]) <= fb.MAX_GRUND and "‮" not in antwort["eintraege"][0]["grund"]
    assert antwort["eintraege"][0]["vor_sekunden"] == 10
    assert len(buch.antwort(anzahl=1)["eintraege"]) == 1
    for unsinn in (0, 99, "3", True, None):
        assert len(buch.antwort(anzahl=unsinn)["eintraege"]) == 3
    assert antwort["hinweis"] == fb.HINWEIS and antwort["status"] == "success"


def test_beobachter_liest_das_ergebnis_und_wirft_nie():
    buch = fb.Fehlerbuch()
    beobachter = fb.FehlerBeobachter(buch)

    def gedrueckt(frame):
        return mock.Mock(frame=frame)

    frame = FunctionCallResultFrame(function_name="websuche", tool_call_id="t1", arguments={},
                                    result=json.dumps({"status": "error", "summary": "Suche nicht erreichbar"}))
    asyncio.run(beobachter.on_push_frame(gedrueckt(frame)))
    asyncio.run(beobachter.on_push_frame(gedrueckt(frame)))  # derselbe Frame an einem zweiten Prozessor
    assert [e["grund"] for e in buch.antwort()["eintraege"]] == ["Suche nicht erreichbar"]
    with mock.patch.object(buch, "aus_ergebnis", side_effect=RuntimeError("kaputt")):
        asyncio.run(beobachter.on_push_frame(gedrueckt(frame)))  # wirft nicht


def test_werkzeug_liefert_eintraege_zustand_und_markiert_fremdinhalt():
    buch = fb.Fehlerbuch()
    buch.aus_meldung({"type": "auftrag_quittung", "ok": False, "grund": "Kanal gesperrt"})
    llm, markiert, ergebnisse = mock.Mock(), [], []
    schema = fb.registrieren(llm, buch, zustand=lambda: {"pc_steuerung": "aus"}, on_foreign_content=lambda: markiert.append(1))
    assert schema.name == fb.NAME and llm.register_function.call_args.args[0] == fb.NAME
    handler = llm.register_function.call_args.args[1]

    async def rueckruf(ergebnis):
        ergebnisse.append(ergebnis)

    asyncio.run(handler(mock.Mock(arguments={"anzahl": 5}, result_callback=rueckruf)))
    assert markiert == [1]
    assert ergebnisse[0]["zustand"] == {"pc_steuerung": "aus"}
    assert ergebnisse[0]["eintraege"][0]["grund"] == "Kanal gesperrt"

    def kaputt():
        raise RuntimeError("weg")

    fb.registrieren(llm, buch, zustand=kaputt)
    asyncio.run(llm.register_function.call_args.args[1](mock.Mock(arguments=None, result_callback=rueckruf)))
    assert ergebnisse[1]["zustand"] == {} and ergebnisse[1]["eintraege"]


def test_offen_fuer_das_gate_aber_nie_im_labor():
    assert fb.NAME in stimme_gate.OFFENE_WERKZEUGE
    assert fb.NAME not in labor.WERKZEUGE_BASIS
    bot = (HIER / "bot.py").read_text(encoding="utf-8")
    assert bot.count("fehlerbuch.registrieren(") == 1
    davor = bot.split("fehlerbuch.registrieren(", 1)[0].rsplit("\n", 2)[-2]
    assert "if not labor_sitzung:" in davor
    assert "fehlerbuch.FehlerBeobachter(fehler)" in bot and "fehler.aus_meldung(data)" in bot
    send = bot.split("    async def send(data: dict) -> None:", 1)[1].split("\n\n", 1)[0]
    assert "fehler.aus_meldung(data)" in send and "except Exception" in send  # das Senden geht immer weiter


def test_persona_nennt_das_werkzeug():
    persona = (HIER / "persona.py").read_text(encoding="utf-8")
    assert "fehler_erklaeren" in persona and "Rate nie einen Grund" in persona
    assert "fehler_erklaeren" not in (HIER / "labor_prompt.py").read_text(encoding="utf-8")
