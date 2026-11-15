"""Mail über Outlook im Kern (outlook_werkzeuge.py) mit Karte (activity.py, pc_freigaben.py): outlook_senden per Sprache und die Klicks
mail_vorbereiten und mail_zurueckholen.

Geprüft wird: nur admin, nie im Labor (dort heißt das Werkzeug mail_senden, dieses bewusst anders), nur mit WAMO_OFFICE=outlook, PC-Steuerung
und Fähigkeit des Hosts, Stimmabdruck-Gate, Anhang nur als Export des eigenen Canvas, Karte mit Warnung bei Fremdinhalt, das Modell bekommt
keine Freigabe-Kennung, lange Karte bis 8000 Zeichen, actions ohne Betreff und Text, Versand mit Zurückholen und Endstand. Host, Datenbank
und Oberfläche sind Attrappen, Adressen nur aus Beispieldomänen.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import activity
import outlook_werkzeuge as om
import pc_host
from pc_freigaben import AKTION_TEXT, PcFreigaben
from test_office_werkzeuge import ADMIN, CID, MITGLIED, LLM, LaborIdentity, Memory, Params, UID

AID = "0123456789abcdef"
VID = "fedcba9876543210"
KENNUNG = "00112233445566aa"
GEHEIM = "Vertraulicher Satz im Angebot"
SCHLUESSEL = "k" * 43
CLIENT = object.__new__(type("Client", (), {}))
NEEDS = {
    "status": "needs_approval", "approval_id": AID, "aktion": "mail", "grund": "Mail-Entwurf in Outlook öffnen",
    "detail": ("So geht es: Das neue Outlook läuft: W.A.I.S. öffnet einen fertigen Entwurf, du sendest selbst.\n"
               "An: max@firma.example (intern)\nBetreff: Angebot\nAnhang: keiner\nText:\n> " + GEHEIM + "\n"
               "Signatur: fügt das neue Outlook selbst an, wenn du eine eingerichtet hast"),
    "ziel": "Neues Outlook, dein Standardkonto", "gueltig_s": 300, "summary": "Die Mail liegt als Karte in der Oberfläche.",
    "protokoll": {"an": 1, "cc": 0, "domaenen": ["firma.example"], "extern": False, "anhaenge": 0, "weg": "entwurf", "programm": "neu"},
}


class Host:
    def __init__(self, **antworten):
        self.aufrufe: list[tuple[str, dict]] = []
        self.antworten = {
            "office_faehigkeiten": {"status": "success", "formate": ["word", "pdf"], "mail": True},
            "outlook_mail_anfragen": NEEDS,
            "outlook_versand_status": {"status": "success", "zustand": "gesendet", "rest_s": 0, "summary": "Die Mail ist gesendet."},
            "outlook_zurueckholen": {"status": "success", "zustand": "zurueckgeholt",
                                     "summary": "Zurückgeholt: Die Mail ist nicht rausgegangen und liegt in Outlook unter Entwürfe."},
            "freigabe_entscheiden": {"status": "success", "weg": "senden", "summary": "Die Mail geht in 30 Sekunden raus.",
                                     "versand": {"id": VID, "frist_s": 30}},
            **antworten}

    async def __call__(self, client, name, arguments):
        self.aufrufe.append((name, arguments))
        antwort = self.antworten[name]
        if isinstance(antwort, list):
            antwort = antwort.pop(0) if len(antwort) > 1 else antwort[0]
        if isinstance(antwort, Exception):
            raise antwort
        return json.dumps(antwort)

    def namen(self):
        return [n for n, _ in self.aufrufe]


class Export:
    def __init__(self, ergebnis=None):
        self.aufrufe: list[dict] = []
        self.ergebnis = ergebnis or {"status": "success", "geoeffnet": False, "summary": "liegt in Dokumente\\WAIS",
                                     "datei": {"kennung": KENNUNG, "name": "2026-11-15 Angebot.pdf", "format": "pdf"}}

    async def __call__(self, fmt, *, canvas_id=None, titel=None, oeffnen=True, quelle):
        self.aufrufe.append({"format": fmt, "canvas_id": canvas_id, "titel": titel, "oeffnen": oeffnen, "quelle": quelle})
        return self.ergebnis


@pytest.fixture
def host(monkeypatch):
    h = Host()
    monkeypatch.setattr(om, "call_host_tool", h)
    monkeypatch.setattr(pc_host, "call_host_tool", h)
    pc_host._FREIGABE_SCHLUESSEL[CLIENT] = SCHLUESSEL
    return h


def mail(memory=None, darf=True, fremd=False, exportieren=None, formate=("word", "pdf")):
    gesendet, karten, meldungen = [], [], []

    async def senden(d):
        gesendet.append(d)

    async def melden(t):
        meldungen.append(t)

    m = om.OutlookMail(ADMIN, memory or Memory(), client=lambda: CLIENT, darf=lambda: darf, senden=senden, melden=melden,
                       fremd=lambda: fremd, exportieren=exportieren, formate=lambda: formate)
    m.karte_anlegen = lambda a: karten.append(a) or {"type": "freigaben", "job": "pc", "projekt": "PC", "items": [a]}
    m.verfuegbar = True
    m.status_nach_secs = m.status_abstand_secs = 0
    m.gesendet, m.karten, m.meldungen = gesendet, karten, meldungen
    return m


async def fertig(m):
    while m._aufgaben:
        await asyncio.gather(*list(m._aufgaben))


# ---------- Schalter, Zugang, Namen ----------
@pytest.mark.parametrize("wert,an", [("outlook", True), ("dateien, outlook", True), ("dateien", False), ("", False), (None, False)])
def test_schalter(wert, an, monkeypatch):
    monkeypatch.delenv("WAMO_OFFICE", raising=False)
    if wert is not None:
        monkeypatch.setenv("WAMO_OFFICE", wert)
    assert om.outlook_an() is an
    assert om.fuer_sitzung(ADMIN) is an
    assert not om.fuer_sitzung(MITGLIED)


def test_nie_im_labor_und_nie_fuer_mitglieder(monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", "outlook")
    for art in ("platz", "schaufenster", "unbekannt"):
        assert not om.fuer_sitzung(LaborIdentity(UID, "Gast", "admin", "du", labor_art=art))
    for identitaet in (MITGLIED, LaborIdentity(UID, "Gast", "admin", "du")):
        with pytest.raises(ValueError):
            om.OutlookMail(identitaet, Memory(), client=lambda: CLIENT, darf=lambda: True, senden=None, fremd=lambda: False)


def test_namen_und_listen():
    import labor
    import pc_tunnel
    import stimme_gate

    assert om.WERKZEUG == "outlook_senden" and om.WERKZEUG != "mail_senden"
    assert om.WERKZEUG not in stimme_gate.OFFENE_WERKZEUGE and om.WERKZEUG not in labor.WERKZEUGE_BASIS
    assert not {"outlook_mail_anfragen", "outlook_zurueckholen", "outlook_versand_status"} & set(pc_host.LLM_TOOLS)
    assert pc_tunnel.LANGE_WERKZEUGE["outlook_mail_anfragen"] >= 45
    assert "mail" in activity.FREIGABE_AKTIONEN and "outlook_senden" in activity.FREIGABE_WERKZEUGE
    assert AKTION_TEXT["mail"] == "die Mail"


def test_zeitleiste_zeigt_nur_die_zahl_der_empfaenger():
    detail = activity._detail("outlook_senden", {"an": ["max@firma.example", "x@y.example"], "cc": ["z@y.example"], "text": GEHEIM})
    assert detail == "3 Empfänger"


# ---------- Karte (activity.py) ----------
def test_lange_karte_und_protokoll_ohne_inhalte():
    lang = dict(NEEDS, detail="Text:\n" + "> " + "x" * 7000)
    a = activity.freigabe_anfrage("outlook_senden", {}, json.dumps(lang), "call-1")
    assert a is not None and a["aktion"] == "mail" and len(a["detail"]) > 2000
    assert activity.freigabe_anfrage("outlook_senden", {}, json.dumps(dict(NEEDS, detail="x" * 8001)), "c") is None
    assert activity.freigabe_anfrage("tastatur_tippen", {}, json.dumps(dict(NEEDS, aktion="senden", detail="x" * 2500)), "c") is None
    a = activity.freigabe_anfrage("outlook_senden", {}, json.dumps(NEEDS), "call-1")
    assert a["protokoll"] == NEEDS["protokoll"]
    boese = dict(NEEDS, protokoll={"an": "alle", "domaenen": ["<script>", "firma.example"], "extern": "ja", "weg": "senden", "x": GEHEIM})
    p = activity.freigabe_anfrage("outlook_senden", {}, json.dumps(boese), "c")["protokoll"]
    assert p == {"domaenen": ["firma.example"], "weg": "senden"}


# ---------- Werkzeug ----------
async def test_registrierung_durch_das_stimmabdruck_gate(host):
    import stimme_gate

    llm = LLM()
    gate = stimme_gate.StimmGate()
    stimme_gate.werkzeuge_absichern(llm, gate)
    mail().register(llm)
    handler, kwargs = llm.handler["outlook_senden"]
    assert getattr(handler, stimme_gate.MARKE) is gate
    assert kwargs["timeout_secs"] >= 60
    # ein Einwurf bricht nicht ab: sonst hielte der PC eine Anfrage ohne Karte, und Eingaben ruhten bis zu 5 Minuten
    assert kwargs["cancel_on_interruption"] is False


async def test_schema_nur_mit_faehigkeit_des_hosts(host, monkeypatch):
    m = mail(exportieren=Export())
    m.verfuegbar = False
    (s,) = await m.schemas()
    assert s.name == "outlook_senden" and m.verfuegbar
    assert s.properties["anhang"]["enum"] == ["word", "pdf"]
    assert set(s.required) == {"an", "betreff", "text"}
    ohne_export = await mail().schemas()
    assert "anhang" not in ohne_export[0].properties
    monkeypatch.setattr(om, "call_host_tool", Host(office_faehigkeiten={"status": "success", "formate": ["word"]}))
    m2 = mail()
    assert await m2.schemas() == [] and not m2.verfuegbar and m2.anzeige() is False


async def test_sprache_legt_die_karte_an_und_das_modell_sieht_keine_kennung(host):
    m = mail()
    p = Params(an=["max@firma.example"], betreff="Angebot", text=f"Hallo Max,\n{GEHEIM}")
    p.tool_call_id = "call-7"
    await m._werkzeug(p)
    assert p.ergebnis["status"] == "wartet_auf_klick"
    assert AID not in json.dumps(p.ergebnis) and "Freigabe" in p.ergebnis["summary"]
    name, args = host.aufrufe[-1]
    assert name == "outlook_mail_anfragen"
    assert args == {"an": ["max@firma.example"], "cc": [], "betreff": "Angebot", "text": f"Hallo Max,\n{GEHEIM}", "anhaenge": []}
    (anfrage,) = m.karten
    assert anfrage["id"] == AID and anfrage["aktion"] == "mail" and anfrage["aktivitaet_id"] == "call-7"
    assert "warnung" not in anfrage
    assert m.gesendet[-1]["type"] == "freigaben"


async def test_empfaenger_als_text_werden_zur_liste(host):
    m = mail()
    p = Params(an="max@firma.example, anna@kunde.example", cc="x@kunde.example", betreff="Angebot", text="x")
    await m._werkzeug(p)
    assert p.ergebnis["status"] == "wartet_auf_klick"
    args = host.aufrufe[-1][1]
    assert args["an"] == ["max@firma.example", "anna@kunde.example"] and args["cc"] == ["x@kunde.example"]
    for kaputt in ({"an": [5]}, {"an": {"x": 1}}, {"an": None}, {"cc": [None]}):
        p = Params(**{"an": ["a@firma.example"], "betreff": "B", "text": "T", **kaputt})
        await m._werkzeug(p)
        assert p.ergebnis["status"] == "rejected" and "Empfänger" in p.ergebnis["summary"], kaputt
    assert len([n for n in host.namen() if n == "outlook_mail_anfragen"]) == 1


async def test_fremdinhalt_im_zug_gibt_eine_warnung(host):
    m = mail(fremd=True)
    await m.vorbereiten(an=["max@firma.example"], cc=None, betreff="Angebot", text="x", quelle="sprache")
    assert "Fremd" in m.karten[0]["warnung"] or "Web" in m.karten[0]["warnung"]


async def test_anhang_ist_der_export_des_canvas(host):
    export = Export()
    m = mail(exportieren=export)
    r = await m.vorbereiten(an=["max@firma.example"], cc=["anna@kunde.example"], betreff="Angebot", text="Anbei.", anhang="pdf",
                            canvas_titel="Angebot", quelle="sprache")
    assert r["status"] == "wartet_auf_klick"
    assert export.aufrufe == [{"format": "pdf", "canvas_id": None, "titel": "Angebot", "oeffnen": False, "quelle": "mail"}]
    assert host.aufrufe[-1][1]["anhaenge"] == [KENNUNG]


async def test_anhang_scheitert_oder_format_nicht_moeglich(host):
    m = mail(exportieren=Export({"status": "rejected", "summary": "Kein eigenes Canvas-Element gefunden."}))
    r = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", anhang="pdf", quelle="sprache")
    assert r["status"] == "rejected" and "Canvas" in r["summary"]
    r = await mail(exportieren=Export()).vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", anhang="exe", quelle="sprache")
    assert r["status"] == "rejected"
    r = await mail().vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", anhang="pdf", quelle="sprache")
    assert r["status"] == "rejected"  # ohne Export kein Anhang
    assert "outlook_mail_anfragen" not in host.namen()


async def test_ablehnung_des_hosts_und_pc_aus(host, monkeypatch):
    monkeypatch.setattr(om, "call_host_tool", Host(outlook_mail_anfragen={"status": "rejected", "summary": "Outlook ist nicht geöffnet."}))
    m = mail()
    r = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="sprache")
    assert r == {"status": "rejected", "summary": "Outlook ist nicht geöffnet."} and m.karten == []
    aus = mail(darf=False)
    r = await aus.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="sprache")
    assert r["status"] == "rejected" and "PC-Steuerung" in r["summary"]


async def test_gleiche_anfrage_zweimal_laesst_die_karte_stehen(host):
    m = mail()
    karten = []
    m.karte_anlegen = lambda a: None if any(k["id"] == a["id"] for k in karten) else (karten.append(a) or {"items": [a]})
    erste = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="sprache")
    zweite = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="sprache")
    assert erste["status"] == zweite["status"] == "wartet_auf_klick" and "schon" in zweite["summary"]
    assert "freigabe_entscheiden" not in host.namen()  # die offene Anfrage am PC bleibt gültig


async def test_nur_eine_vorbereitung_zur_zeit(host):
    m = mail()
    halt = asyncio.Event()

    async def langsam(client, name, arguments):
        await halt.wait()
        return json.dumps(NEEDS)

    m_call = om.call_host_tool
    om.call_host_tool = langsam
    try:
        erste = asyncio.ensure_future(m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="klick"))
        await asyncio.sleep(0)
        zweite = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="klick")
        assert zweite["status"] == "rejected" and "gerade" in zweite["summary"]
        halt.set()
        assert (await erste)["status"] == "wartet_auf_klick"
    finally:
        om.call_host_tool = m_call


async def test_volle_kartenliste_lehnt_beim_host_ab(host):
    m = mail()
    m.karte_anlegen = lambda a: None
    r = await m.vorbereiten(an=["a@firma.example"], cc=None, betreff="B", text="T", quelle="sprache")
    assert r["status"] == "error"
    assert ("freigabe_entscheiden", {"approval_id": AID, "ja": False, "schluessel": SCHLUESSEL}) in host.aufrufe


# ---------- Klicks ----------
async def test_klick_mail_vorbereiten(host):
    m = mail(exportieren=Export())
    await m.client_nachricht("mail_vorbereiten", {"canvas_id": CID, "an": ["max@firma.example"], "cc": [], "betreff": "Angebot",
                                                  "text": "Anbei.", "anhang": "pdf"})
    assert m.gesendet[-1] == {"type": "mail_antwort", "ok": True}
    assert host.aufrufe[-1][0] == "outlook_mail_anfragen"


@pytest.mark.parametrize("daten", [{"an": "max@firma.example", "betreff": "B", "text": "T"}, {"an": [5], "betreff": "B", "text": "T"},
                                    {"an": ["a@b.example"] * 11, "betreff": "B", "text": "T"}, {"an": ["a@b.example"], "betreff": 5},
                                    {"an": ["a@b.example"], "betreff": "B", "text": "T", "canvas_id": "x", "anhang": "pdf"}, "kaputt"])
async def test_klick_mail_vorbereiten_ungueltig(host, daten):
    m = mail(exportieren=Export())
    await m.client_nachricht("mail_vorbereiten", daten)
    assert "outlook_mail_anfragen" not in host.namen()
    assert m.gesendet[-1]["type"] == "mail_antwort" and m.gesendet[-1]["ok"] is False


# ---------- Nach dem Klick auf der Karte ----------
def freigaben_mit(m, memory):
    gedaechtnis = type("G", (), {})()
    gedaechtnis.protokoll, gedaechtnis.status = [], []

    async def log_action(tool, params, reason, risk):
        gedaechtnis.protokoll.append({"tool": tool, "params": params, "reason": reason, "risk": risk})
        return "aktion-1"

    async def update_action(action_id, status):
        gedaechtnis.status.append(status)
        return True

    gedaechtnis.log_action, gedaechtnis.update_action = log_action, update_action

    async def melden(t):
        m.meldungen.append(t)

    f = PcFreigaben(gedaechtnis, client=lambda: CLIENT, darf=lambda: True, melden=melden, fremdinhalt=lambda: None,
                    senden=m._senden, von="Admin")
    m.karte_anlegen = f.anfrage
    f.nach_ergebnis = m.nach_freigabe
    return f, gedaechtnis


async def test_freigabe_protokolliert_ohne_inhalte_und_zeigt_die_warnung(host):
    m = mail(fremd=True)
    f, g = freigaben_mit(m, Memory())
    await m.vorbereiten(an=["max@firma.example"], cc=None, betreff="Angebot", text=GEHEIM, quelle="sprache")
    await asyncio.sleep(0)  # das Protokoll schreibt PcFreigaben im Hintergrund
    karte = m.gesendet[-1]
    assert karte["items"][0]["warnung"] and karte["items"][0]["detail"].count(GEHEIM) == 1
    assert GEHEIM not in json.dumps(g.protokoll) and "Angebot" not in json.dumps(g.protokoll)
    assert g.protokoll[0]["params"]["mail"] == NEEDS["protokoll"]
    assert g.protokoll[0]["risk"] == "change"  # Entwurf ist change (Senden wäre critical), die Karte gibt es trotzdem


async def test_versand_mit_zurueckholen_und_endstand(host):
    memory = Memory()
    m = mail(memory)
    f, _ = freigaben_mit(m, memory)
    m.status_nach_secs = 30  # der Endstand kommt erst nach der Frist: vorher holt der Klick zurück
    await m.vorbereiten(an=["max@firma.example"], cc=None, betreff="Angebot", text="x", quelle="sprache")
    await f.entscheiden({"job": "pc", "id": AID, "entscheidung": "ja"})
    wartet = next(x for x in m.gesendet if x.get("type") == "mail_versand")
    assert wartet == {"type": "mail_versand", "id": VID, "zustand": "wartet", "rest_s": 30,
                      "text": "Die Mail geht in 30 Sekunden raus. Bis dahin kannst du sie zurückholen."}
    assert any("die Mail freigegeben" in t for t in m.meldungen)
    await m.client_nachricht("mail_zurueckholen", {"id": VID})
    assert ("outlook_zurueckholen", {"versand_id": VID, "schluessel": SCHLUESSEL}) in host.aufrufe
    assert m.gesendet[-1]["zustand"] == "zurueckgeholt" and "Entwürfe" in m.gesendet[-1]["text"]
    for t in list(m._aufgaben):
        t.cancel()
    sql, werte = memory.db.geschrieben[-1]
    assert "insert into wamo_test.actions" in sql and werte[2] == "outlook_versand"
    assert json.loads(werte[3]) == {"versand_id": VID} and werte[6] == "rejected"


async def test_endstand_gesendet_und_fehler(host, monkeypatch):
    memory = Memory()
    m = mail(memory)
    await m.nach_freigabe({"aktion": "mail", "werkzeug": "outlook_senden"}, {"status": "success", "versand": {"id": VID, "frist_s": 30}})
    await fertig(m)
    assert m.gesendet[-1] == {"type": "mail_versand", "id": VID, "zustand": "gesendet", "text": "Die Mail ist gesendet."}
    assert memory.db.geschrieben[-1][1][6] == "done" and m.meldungen == []
    monkeypatch.setattr(om, "call_host_tool", Host(outlook_versand_status=[
        {"status": "success", "zustand": "wartet", "rest_s": 0}, {"status": "success", "zustand": "fehler",
                                                                 "summary": "Die Mail wurde in Outlook verändert."}]))
    m2 = mail(Memory())
    await m2.nach_freigabe({"aktion": "mail", "werkzeug": "outlook_senden"}, {"status": "success", "versand": {"id": VID, "frist_s": 5}})
    await fertig(m2)
    assert m2.gesendet[-1]["zustand"] == "fehler" and "verändert" in m2.gesendet[-1]["text"]
    assert m2.meldungen and "nicht gesendet" in m2.meldungen[-1]


async def test_entwurf_meldet_nur_den_hinweis(host):
    m = mail()
    await m.nach_freigabe({"aktion": "mail", "werkzeug": "outlook_senden"},
                          {"status": "success", "weg": "eml", "summary": "Der Entwurf ist im neuen Outlook offen, mit Anhang."})
    assert m.gesendet[-1] == {"type": "mail_versand", "id": None, "zustand": "entwurf",
                              "text": "Der Entwurf ist im neuen Outlook offen, mit Anhang."}
    assert m._aufgaben == set()
    await m.nach_freigabe({"aktion": "github", "werkzeug": "github_repo_anlegen"}, {"status": "success"})
    assert len(m.gesendet) == 1


async def test_zurueckholen_nur_fuer_eigene_versaende(host):
    m = mail()
    for daten in ({"id": VID}, {"id": "../x"}, {}, "kaputt"):
        await m.client_nachricht("mail_zurueckholen", daten)
    assert "outlook_zurueckholen" not in host.namen()
    assert m.gesendet[-1]["type"] == "mail_versand" and m.gesendet[-1]["zustand"] == "unbekannt"


# ---------- Vertrag mit Host und Oberfläche (beide Seiten halten ihre Grenzen selbst) ----------
WURZEL = Path(__file__).resolve().parent.parent


def _konstante(datei: str, name: str) -> str:
    import re

    ende = "".join(map(chr, (59, 10, 35)))  # Semikolon, Zeilenende, Raute: dort endet der Wert
    treffer = re.search(rf"^(?:export const )?{name}\s*=\s*([^{ende}]+)", (WURZEL / datei).read_text(encoding="utf-8"), re.M)
    assert treffer, (datei, name)
    return treffer.group(1).strip()


def test_grenzen_gleich_in_kern_host_und_oberflaeche():
    assert int(_konstante("host/office_outlook.py", "EMPFAENGER_MAX").split()[0]) == om.EMPFAENGER_MAX
    assert int(_konstante("host/office_outlook.py", "BETREFF_MAX")) == om.BETREFF_MAX
    assert int(_konstante("host/office_outlook.py", "TEXT_MAX")) == om.TEXT_MAX
    assert int(_konstante("host/office_outlook.py", "KARTE_MAX").split()[0]) == activity.FREIGABE_DETAIL_ZEICHEN_MAIL
    assert int(_konstante("ui/src/lib/nachrichten.ts", "FREIGABE_DETAIL_MAX")) == activity.FREIGABE_DETAIL_ZEICHEN_MAIL
    assert int(_konstante("ui/src/lib/nachrichten.ts", "FREIGABE_DETAIL_KURZ")) == activity.FREIGABE_DETAIL_ZEICHEN
    assert int(_konstante("ui/src/lib/mail.ts", "MAIL_EMPFAENGER_MAX")) == om.EMPFAENGER_MAX
    assert int(_konstante("ui/src/lib/mail.ts", "MAIL_BETREFF_MAX")) == om.BETREFF_MAX
    assert int(_konstante("ui/src/lib/mail.ts", "MAIL_TEXT_MAX")) == om.TEXT_MAX
    assert _konstante("host/office_outlook_com.py", "VERSAND_ID_RE") == f're.compile(r"{om.VERSAND_RE.pattern}")'


# ---------- Verdrahtung in bot.py (statisch, die Sitzung braucht Netz und Modelle) ----------
BOT = (Path(__file__).with_name("bot.py")).read_text(encoding="utf-8")


def test_bot_baut_outlook_nur_fuer_admin_ohne_labor():
    assert BOT.count("OutlookMail(") == 1
    zeile = next(z for z in BOT.splitlines() if "OutlookMail(" in z)
    block = BOT[BOT.index(zeile) - 300: BOT.index(zeile) + 700]
    assert "outlook_werkzeuge.fuer_sitzung(identity)" in block
    assert "is_admin" in block and "not labor_sitzung" in block and "pc_teile and is_admin" in block
    # pc_teile: mit Client oder solange der Zugang zum Laptop nachgeholt werden kann (pc_nachverbinden.py), sonst nie
    assert "pc_teile = pc_client is not None or pc_nachholen" in BOT
    assert "darf=pc_allowed" in block and "fremd=lambda: turn.tainted" in block


def test_bot_verdrahtet_karte_schemas_klicks_und_betrieb():
    assert "mail.karte_anlegen = freigaben.anfrage" in BOT
    assert "freigaben.nach_ergebnis = mail.nach_freigabe" in BOT
    assert "await mail.schemas()" in BOT and "mail.register(llm)" in BOT
    assert "msg.type in outlook_werkzeuge.NACHRICHTEN" in BOT
    assert "mail=mail.anzeige() if mail is not None else False" in BOT
    assert "mail.schliessen()" in BOT
    baum = ast.parse(BOT)
    assert any(isinstance(k, ast.Import) and any(a.name == "outlook_werkzeuge" for a in k.names) for k in ast.walk(baum))
    assert BOT.index("msg.type in outlook_werkzeuge.NACHRICHTEN") < BOT.index("elif dev:\n            await dev.on_client_message")


@pytest.fixture(scope="module")
def bot():
    umgebung = {"SONIOX_API_KEY": "dummy-soniox", "ANTHROPIC_API_KEY": "dummy-anthropic", "WAMO_DATABASE_URL": "",
                "WAMO_DB_SCHEMA": "wamo_test", "WAMO_PC_HOST": "off"}
    with mock.patch.dict(os.environ, umgebung):
        import bot as modul
    return modul


def test_betrieb_nennt_mail(bot):
    assert "mail" not in bot.betrieb_message("verbunden")
    assert bot.betrieb_message("verbunden", mail=True)["mail"] is True


# ---------- Echttest und Review vom 15.11.2026 ----------
def test_lange_karte_zaehlt_utf16_wie_die_oberflaeche():
    emoji = chr(0x1F600)  # ein Zeichen, zwei UTF-16-Einheiten
    detail = "Text:\n> " + emoji * 4100  # 4108 Zeichen, aber mehr als 8000 Einheiten
    assert activity.freigabe_anfrage("outlook_senden", {}, json.dumps(dict(NEEDS, detail=detail)), "c") is None
    passt = "Text:\n> " + emoji * 3900
    assert activity.freigabe_anfrage("outlook_senden", {}, json.dumps(dict(NEEDS, detail=passt)), "c") is not None


async def test_unklar_ist_ein_endstand_mit_dem_satz_vom_pc(monkeypatch):
    satz = "Outlook hat beim Senden nicht rechtzeitig geantwortet. Ob die Mail rausging, ist unklar."
    h = Host(outlook_versand_status={"status": "success", "zustand": "unklar", "rest_s": 0, "summary": satz})
    monkeypatch.setattr(om, "call_host_tool", h)
    m = mail(Memory())
    await m.nach_freigabe({"aktion": "mail", "werkzeug": "outlook_senden"}, {"status": "success", "versand": {"id": VID, "frist_s": 5}})
    await fertig(m)
    assert h.namen().count("outlook_versand_status") == 1  # kein Nachfragen mehr nach einem Endstand
    assert m.gesendet[-1] == {"type": "mail_versand", "id": VID, "zustand": "unklar", "text": satz}
    assert m.meldungen and "unklar" in m.meldungen[-1]


async def test_sitzungsende_holt_wartende_versaende_zurueck(host):
    m = mail()
    andere = "0123456789abcdef"
    m._eigene.update({VID, andere})
    m._erledigt.add(andere)  # schon gesendet oder zurückgeholt: nichts mehr zu tun
    await m.schliessen()
    assert [a for n, a in host.aufrufe if n == "outlook_zurueckholen"] == [{"versand_id": VID, "schluessel": SCHLUESSEL}]
    assert m._aufgaben == set()


def test_bot_begrenzt_das_aufraeumen_beim_sitzungsende():
    assert "asyncio.wait_for(mail.schliessen(), CLEANUP_DB_TIMEOUT_SECS)" in BOT
