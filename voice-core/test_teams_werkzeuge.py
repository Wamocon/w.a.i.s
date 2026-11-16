"""Teams-Nachricht im Kern (teams_werkzeuge.py) mit Karte (activity.py, pc_freigaben.py): teams_nachricht per Sprache und der Klick
teams_vorbereiten.

Geprüft wird: nur admin, nie im Labor, nur mit WAMO_OFFICE=teams, PC-Steuerung und Fähigkeit des Hosts, Stimmabdruck-Gate, Text vom
Modell oder aus dem eigenen Canvas als Klartext, Karte mit Warnung bei Fremdinhalt, das Modell bekommt keine Freigabe-Kennung und hört
nie "gesendet", actions ohne Adressen und Text. Host, Datenbank und Oberfläche sind Attrappen, Adressen nur aus Beispieldomänen.
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
import pc_host
import teams_werkzeuge as tw
from canvas_quelle import CanvasNichtErreichbar
from pc_freigaben import AKTION_TEXT, PcFreigaben
from test_office_werkzeuge import ADMIN, MITGLIED, LLM, TAB, LaborIdentity, Memory, Params, UID, zeile

AID = "0123456789abcdef"
GEHEIM = "Vertraulicher Satz zum Angebot"
MAX = "max.weber@firma.example"
SCHLUESSEL = "k" * 43
CLIENT = object.__new__(type("Client", (), {}))
NEEDS = {
    "status": "needs_approval", "approval_id": AID, "aktion": "teams", "grund": "Teams-Chat mit vorbereitetem Text öffnen",
    "detail": ("So geht es: W.A.I.S. öffnet die Teams-App mit diesem Chat und dem Text im Eingabefeld.\n"
               f"An: {MAX} (intern)\nText:\n> {GEHEIM}\nW.A.I.S. sendet nicht, du drückst in Teams selbst Enter."),
    "ziel": "Microsoft Teams", "gueltig_s": 300, "summary": "Die Teams-Nachricht liegt als Karte in der Oberfläche.",
    "protokoll": {"an": 1, "domaenen": ["firma.example"], "gruppe": False},
}


class Host:
    def __init__(self, **antworten):
        self.aufrufe: list[tuple[str, dict]] = []
        self.antworten = {
            "office_faehigkeiten": {"status": "success", "formate": ["word"], "mail": True, "teams": True},
            "teams_chat_anfragen": NEEDS,
            "freigabe_entscheiden": {"status": "success", "weg": "app",
                                     "summary": "Teams ist offen, der Text steht im Eingabefeld. Prüfen und selbst mit Enter senden."},
            **antworten}

    async def __call__(self, client, name, arguments):
        self.aufrufe.append((name, arguments))
        antwort = self.antworten[name]
        if isinstance(antwort, Exception):
            raise antwort
        return json.dumps(antwort)

    def namen(self):
        return [n for n, _ in self.aufrufe]


@pytest.fixture
def host(monkeypatch):
    h = Host()
    monkeypatch.setattr(tw, "call_host_tool", h)
    monkeypatch.setattr(pc_host, "call_host_tool", h)
    pc_host._FREIGABE_SCHLUESSEL[CLIENT] = SCHLUESSEL
    return h


def teams(memory=None, darf=True, fremd=False):
    gesendet, karten = [], []

    async def senden(d):
        gesendet.append(d)

    t = tw.TeamsNachricht(ADMIN, memory or Memory(), client=lambda: CLIENT, darf=lambda: darf, senden=senden, fremd=lambda: fremd)
    t.karte_anlegen = lambda a: karten.append(a) or {"type": "freigaben", "job": "pc", "projekt": "PC", "items": [a]}
    t.verfuegbar = True
    t.gesendet, t.karten = gesendet, karten
    return t


# ---------- Schalter, Zugang, Namen ----------
@pytest.mark.parametrize("wert,an", [("teams", True), ("dateien, outlook, teams", True), ("outlook", False), ("", False), (None, False),
                                     ("team", False)])
def test_schalter_fail_closed(wert, an, monkeypatch):
    monkeypatch.delenv("WAMO_OFFICE", raising=False)
    if wert is not None:
        monkeypatch.setenv("WAMO_OFFICE", wert)
    assert tw.teams_an() is an
    assert tw.fuer_sitzung(ADMIN) is an
    assert not tw.fuer_sitzung(MITGLIED)


def test_freigeschaltetes_mitglied_bekommt_teams(monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", "teams")
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", UID)
    assert tw.fuer_sitzung(MITGLIED)
    tw.TeamsNachricht(MITGLIED, Memory(), client=lambda: CLIENT, darf=lambda: True, senden=None, fremd=lambda: False)
    assert not tw.fuer_sitzung(LaborIdentity(UID, "Gast", "mitglied", "du"))


def test_nie_im_labor_und_nie_fuer_mitglieder_ohne_freischaltung(monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", "teams")
    monkeypatch.delenv("WAMO_PC_MITGLIEDER_PROFILE", raising=False)
    for art in ("platz", "schaufenster", "unbekannt"):
        assert not tw.fuer_sitzung(LaborIdentity(UID, "Gast", "admin", "du", labor_art=art))
    for identitaet in (MITGLIED, LaborIdentity(UID, "Gast", "admin", "du")):
        with pytest.raises(ValueError):
            tw.TeamsNachricht(identitaet, Memory(), client=lambda: CLIENT, darf=lambda: True, senden=None, fremd=lambda: False)


def test_namen_und_listen():
    import labor
    import pc_tunnel
    import stimme_gate

    assert tw.WERKZEUG == "teams_nachricht"
    assert tw.WERKZEUG not in stimme_gate.OFFENE_WERKZEUGE and tw.WERKZEUG not in labor.WERKZEUGE_BASIS
    assert "teams_chat_anfragen" not in pc_host.LLM_TOOLS
    assert pc_tunnel.LANGE_WERKZEUGE["teams_chat_anfragen"] >= 45
    assert "teams" in activity.FREIGABE_AKTIONEN and "teams_nachricht" in activity.FREIGABE_WERKZEUGE
    assert AKTION_TEXT["teams"] == "das Öffnen des Teams-Chats"


def test_zeitleiste_zeigt_nur_die_zahl_der_empfaenger():
    assert activity._detail("teams_nachricht", {"an": [MAX, "anna@firma.example"], "text": GEHEIM}) == "2 Empfänger"
    assert activity._detail("teams_nachricht", {"an": f"{MAX}, anna@firma.example", "text": GEHEIM}) == "2 Empfänger"


# ---------- Karte (activity.py) ----------
def test_karte_lang_und_protokoll_ohne_inhalte():
    a = activity.freigabe_anfrage("teams_nachricht", {}, json.dumps(dict(NEEDS, detail="Text:\n> " + "x" * 3000)), "call-1")
    assert a is not None and a["aktion"] == "teams" and len(a["detail"]) > 2000
    assert activity.freigabe_anfrage("teams_nachricht", {}, json.dumps(dict(NEEDS, detail="x" * 8001)), "c") is None
    assert activity.freigabe_anfrage("teams_nachricht", {}, json.dumps(NEEDS), "c")["protokoll"] == NEEDS["protokoll"]
    boese = dict(NEEDS, protokoll={"an": 99, "domaenen": ["<b>", "firma.example"], "gruppe": "ja", "text": GEHEIM, "adressen": [MAX]})
    assert activity.freigabe_anfrage("teams_nachricht", {}, json.dumps(boese), "c")["protokoll"] == {"domaenen": ["firma.example"]}
    assert activity.freigabe_anfrage("outlook_senden", {}, json.dumps(NEEDS), "c")["aktion"] == "teams"  # Aktion kommt vom Host


# ---------- Klartext aus dem Canvas ----------
def test_klartext_aus_dokument_tabelle_und_code():
    dok = {"art": "dokument", "titel": "Angebot",
           "text": "# Angebot\n\n**Wichtig:** der `Termin` steht.\n- Punkt [Link](https://firma.example/a)\n```\ncode\n```"}
    assert tw.klartext(dok) == "Angebot\n\nWichtig: der Termin steht.\n- Punkt Link (https://firma.example/a)\ncode"
    tab = {"art": "tabelle", "titel": "Liste", "spalten": ["Name", "Stand"], "zeilen": [["A", "fertig"], ["B", "offen"]]}
    assert tw.klartext(tab) == "Liste\nName | Stand\nA | fertig\nB | offen"
    assert tw.klartext({"art": "code", "titel": "x", "text": "a **b**"}) == "a **b**"


# ---------- Werkzeug ----------
async def test_registrierung_durch_das_stimmabdruck_gate(host):
    import stimme_gate

    llm = LLM()
    gate = stimme_gate.StimmGate()
    stimme_gate.werkzeuge_absichern(llm, gate)
    teams().register(llm)
    handler, kwargs = llm.handler["teams_nachricht"]
    assert getattr(handler, stimme_gate.MARKE) is gate
    assert kwargs["timeout_secs"] >= 60 and kwargs["cancel_on_interruption"] is False


async def test_schema_nur_mit_faehigkeit_des_hosts(host, monkeypatch):
    t = teams()
    t.verfuegbar = False
    (s,) = await t.schemas()
    assert s.name == "teams_nachricht" and t.verfuegbar and t.anzeige() is True
    assert set(s.properties) == {"an", "text", "canvas", "gruppenname"} and s.required == ["an"]
    assert "sendet nie" in s.description and "Enter" in s.description
    monkeypatch.setattr(tw, "call_host_tool", Host(office_faehigkeiten={"status": "success", "formate": [], "mail": True}))
    t2 = teams()
    assert await t2.schemas() == [] and not t2.verfuegbar and t2.anzeige() is False


async def test_sprache_legt_die_karte_an_und_das_modell_sieht_keine_kennung(host):
    t = teams()
    p = Params(an=[MAX], text=f"Hallo Max,\n{GEHEIM}")
    p.tool_call_id = "call-7"
    await t._werkzeug(p)
    assert p.ergebnis["status"] == "wartet_auf_klick"
    assert AID not in json.dumps(p.ergebnis) and "Freigabe" in p.ergebnis["summary"] and "Enter" in p.ergebnis["summary"]
    assert "gesendet" not in p.ergebnis["summary"]
    assert host.aufrufe[-1] == ("teams_chat_anfragen", {"an": [MAX], "text": f"Hallo Max,\n{GEHEIM}", "gruppenname": ""})
    (karte,) = t.karten
    assert karte["aktion"] == "teams" and karte["aktivitaet_id"] == "call-7" and "warnung" not in karte


async def test_empfaenger_als_text_und_gruppenname(host):
    await teams().vorbereiten(an=f"{MAX}; anna@firma.example", text="Hallo", gruppenname="Angebot", quelle="sprache")
    assert host.aufrufe[-1][1] == {"an": [MAX, "anna@firma.example"], "text": "Hallo", "gruppenname": "Angebot"}


async def test_text_aus_dem_canvas_als_klartext(host):
    memory = Memory([zeile(text=f"# Angebot\n**{GEHEIM}**")])
    p = Params(an=[MAX], canvas="Angebot")
    await teams(memory)._werkzeug(p)
    assert p.ergebnis["status"] == "wartet_auf_klick"
    assert host.aufrufe[-1][1]["text"] == f"Angebot\n{GEHEIM}"
    sql, args = memory.db.abfragen[0]
    assert args == (UID, "Angebot")  # nur eigene Elemente (canvas_quelle)


async def test_leerer_canvas_titel_nimmt_das_zuletzt_gezeigte(host):
    memory = Memory([TAB])
    await teams(memory)._werkzeug(Params(an=[MAX], canvas=""))
    assert host.aufrufe[-1][1]["text"] == "Liste\na | b\n1 | 2"


async def test_ohne_text_und_canvas_oder_canvas_fehlt(host):
    r = await teams().vorbereiten(an=[MAX], text="  ", quelle="sprache")
    assert r["status"] == "rejected" and "Text" in r["summary"]
    p = Params(an=[MAX], canvas="Gibt es nicht")
    await teams(Memory([]))._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "Canvas" in p.ergebnis["summary"]
    with mock.patch.object(tw, "canvas_lesen", side_effect=CanvasNichtErreichbar("x")):
        p = Params(an=[MAX], canvas="")
        await teams()._werkzeug(p)
    assert p.ergebnis["status"] == "error"
    assert "teams_chat_anfragen" not in host.namen()


async def test_fremdinhalt_im_zug_gibt_eine_warnung(host):
    t = teams(fremd=True)
    await t.vorbereiten(an=[MAX], text="Hallo", quelle="sprache")
    assert t.karten[0]["warnung"] == tw.WARNUNG


async def test_ablehnung_des_hosts_und_pc_aus(host, monkeypatch):
    zu_lang = "Der Text hat 1200 Zeichen, für Teams gehen höchstens 1000. Bitte kürzen oder als Mail schicken."
    monkeypatch.setattr(tw, "call_host_tool", Host(teams_chat_anfragen={"status": "rejected", "summary": zu_lang}))
    r = await teams().vorbereiten(an=[MAX], text="x", quelle="sprache")
    assert r == {"status": "rejected", "summary": zu_lang}
    r = await teams(darf=False).vorbereiten(an=[MAX], text="x", quelle="sprache")
    assert r["status"] == "rejected" and "PC-Steuerung" in r["summary"]
    monkeypatch.setattr(tw, "call_host_tool", Host(teams_chat_anfragen=TimeoutError()))
    assert (await teams().vorbereiten(an=[MAX], text="x", quelle="sprache"))["status"] == "error"


async def test_ungueltige_empfaenger_fragen_den_host_nicht(host):
    for an in (None, [], [3], "", [""] * 2):
        r = await teams().vorbereiten(an=an, text="Hallo", quelle="sprache")
        assert r["status"] == "rejected", an
    assert "teams_chat_anfragen" not in host.namen()


async def test_gleiche_anfrage_zweimal_und_volle_kartenliste(host):
    t = teams()
    await t.vorbereiten(an=[MAX], text="Hallo", quelle="sprache")
    t.karte_anlegen = lambda a: None
    r = await t.vorbereiten(an=[MAX], text="Hallo", quelle="sprache")
    assert r["status"] == "wartet_auf_klick" and "schon" in r["summary"]
    t2 = teams()
    t2.karte_anlegen = lambda a: None
    r = await t2.vorbereiten(an=[MAX], text="Hallo", quelle="sprache")
    assert r["status"] == "error" and host.aufrufe[-1][0] == "freigabe_entscheiden"


async def test_nur_eine_vorbereitung_zur_zeit(host):
    t = teams()
    halt = asyncio.Event()

    async def langsam(client, name, arguments):
        await halt.wait()
        return json.dumps(NEEDS)

    with mock.patch.object(tw, "call_host_tool", langsam):
        erste = asyncio.ensure_future(t.vorbereiten(an=[MAX], text="Hallo", quelle="klick"))
        await asyncio.sleep(0)
        zweite = await t.vorbereiten(an=[MAX], text="Hallo", quelle="klick")
        halt.set()
        assert (await erste)["status"] == "wartet_auf_klick"
    assert zweite["status"] == "rejected" and "schon" in zweite["summary"]


# ---------- Klick aus der Oberfläche ----------
async def test_klick_teams_vorbereiten(host):
    t = teams()
    await t.client_nachricht("teams_vorbereiten", {"an": [MAX], "gruppenname": "", "text": "Hallo"})
    assert host.aufrufe[-1] == ("teams_chat_anfragen", {"an": [MAX], "text": "Hallo", "gruppenname": ""})
    assert t.gesendet[-1] == {"type": "teams_antwort", "ok": True}


@pytest.mark.parametrize("daten", [
    {}, "kaputt", {"an": [], "text": "x"}, {"an": [MAX], "text": ""}, {"an": [MAX], "text": "x" * 1001},
    {"an": [MAX] * 11, "text": "x"}, {"an": [MAX], "text": "x", "gruppenname": "g" * 101}, {"an": [MAX], "text": 5},
])
async def test_klick_ungueltig(host, daten):
    t = teams()
    await t.client_nachricht("teams_vorbereiten", daten)
    assert t.gesendet[-1]["type"] == "teams_antwort" and t.gesendet[-1]["ok"] is False
    assert "teams_chat_anfragen" not in host.namen()


async def test_klick_mit_grund_vom_host(host, monkeypatch):
    monkeypatch.setattr(tw, "call_host_tool", Host(teams_chat_anfragen={"status": "rejected", "summary": "Nur interne Adressen."}))
    t = teams()
    await t.client_nachricht("teams_vorbereiten", {"an": ["kunde@kunde.example"], "text": "Hallo"})
    assert t.gesendet[-1] == {"type": "teams_antwort", "ok": False, "grund": "Nur interne Adressen."}


# ---------- Freigabe (pc_freigaben.py) ----------
def freigaben_mit(t):
    gedaechtnis = type("G", (), {})()
    gedaechtnis.protokoll, gedaechtnis.status, meldungen = [], [], []

    async def log_action(tool, params, reason, risk):
        gedaechtnis.protokoll.append({"tool": tool, "params": params, "reason": reason, "risk": risk})
        return "aktion-1"

    async def update_action(action_id, status):
        gedaechtnis.status.append(status)
        return True

    async def melden(text):
        meldungen.append(text)

    gedaechtnis.log_action, gedaechtnis.update_action = log_action, update_action
    f = PcFreigaben(gedaechtnis, client=lambda: CLIENT, darf=lambda: True, melden=melden, fremdinhalt=lambda: None, senden=t._senden,
                    von="Admin")
    t.karte_anlegen = f.anfrage
    return f, gedaechtnis, meldungen


async def test_freigabe_protokolliert_ohne_inhalte_und_oeffnet_nur(host):
    t = teams(fremd=True)
    f, g, meldungen = freigaben_mit(t)
    await t.vorbereiten(an=[MAX], text=GEHEIM, gruppenname="", quelle="sprache")
    await asyncio.sleep(0)  # das Protokoll schreibt PcFreigaben im Hintergrund
    karte = t.gesendet[-1]
    assert karte["items"][0]["warnung"] == tw.WARNUNG and karte["items"][0]["detail"].count(GEHEIM) == 1
    assert g.protokoll[0]["params"] == {"approval_id": AID, "aktion": "teams", "ziel": "Microsoft Teams", "teams": NEEDS["protokoll"]}
    assert g.protokoll[0]["risk"] == "critical"
    await f.entscheiden({"job": "pc", "id": AID, "entscheidung": "ja"})
    assert ("freigabe_entscheiden", {"approval_id": AID, "ja": True, "schluessel": SCHLUESSEL}) in host.aufrufe
    assert any("das Öffnen des Teams-Chats freigegeben" in m for m in meldungen)
    gesamt = json.dumps(g.protokoll, ensure_ascii=False)
    assert GEHEIM not in gesamt and MAX not in gesamt


# ---------- Vertrag mit Host und Oberfläche (beide Seiten halten ihre Grenzen selbst) ----------
WURZEL = Path(__file__).resolve().parent.parent


def _konstante(datei: str, name: str) -> str:
    import re

    ende = "".join(map(chr, (59, 10, 35)))  # Semikolon, Zeilenende, Raute: dort endet der Wert
    treffer = re.search(rf"^(?:export const )?{name}\s*=\s*([^{ende}]+)", (WURZEL / datei).read_text(encoding="utf-8"), re.M)
    assert treffer, (datei, name)
    return treffer.group(1).strip()


def test_grenzen_gleich_in_kern_host_und_oberflaeche():
    for host_name, kern in (("EMPFAENGER_MAX", tw.EMPFAENGER_MAX), ("TEXT_MAX", tw.TEXT_MAX), ("GRUPPE_MAX", tw.GRUPPE_MAX)):
        assert int(_konstante("host/office_teams.py", host_name)) == kern
    assert int(_konstante("host/office_teams.py", "KARTE_MAX").split()[0]) <= activity.FREIGABE_DETAIL_ZEICHEN_MAIL
    assert int(_konstante("ui/src/lib/teams.ts", "TEAMS_EMPFAENGER_MAX")) == tw.EMPFAENGER_MAX
    assert int(_konstante("ui/src/lib/teams.ts", "TEAMS_TEXT_MAX")) == tw.TEXT_MAX
    assert int(_konstante("ui/src/lib/teams.ts", "TEAMS_GRUPPE_MAX")) == tw.GRUPPE_MAX


# ---------- Verdrahtung in bot.py (statisch, die Sitzung braucht Netz und Modelle) ----------
BOT = (Path(__file__).with_name("bot.py")).read_text(encoding="utf-8")


def test_bot_baut_teams_nur_fuer_admin_ohne_labor():
    assert BOT.count("TeamsNachricht(") == 1
    zeile_ = next(z for z in BOT.splitlines() if "TeamsNachricht(" in z)
    block = BOT[BOT.index(zeile_) - 300: BOT.index(zeile_) + 500]
    assert "teams_werkzeuge.fuer_sitzung(identity)" in block
    assert "pc_person" in block and "not labor_sitzung" in block and "pc_teile and pc_person" in block
    assert "is_admin" not in block  # die Stufe der PC-Steuerung entscheidet, nicht die Rolle allein
    # pc_teile: mit Client oder solange der Zugang zum Laptop nachgeholt werden kann (pc_nachverbinden.py), sonst nie
    assert "pc_teile = pc_client is not None or pc_nachholen" in BOT
    assert "darf=pc_allowed" in block and "fremd=lambda: turn.tainted" in block


def test_bot_verdrahtet_karte_schemas_klicks_und_betrieb():
    assert "teams.karte_anlegen = freigaben.anfrage" in BOT
    assert "await teams.schemas()" in BOT and "teams.register(llm)" in BOT
    assert "msg.type in teams_werkzeuge.NACHRICHTEN" in BOT
    assert "teams=teams.anzeige() if teams is not None else False" in BOT
    baum = ast.parse(BOT)
    assert any(isinstance(k, ast.Import) and any(a.name == "teams_werkzeuge" for a in k.names) for k in ast.walk(baum))
    assert BOT.index("msg.type in teams_werkzeuge.NACHRICHTEN") < BOT.index("elif dev:\n            await dev.on_client_message")
    # die Registrierung steht nach werkzeuge_absichern: auch dieses Werkzeug fragt vorher das Gate der Stimmprüfung
    assert BOT.index("werkzeuge_absichern(llm, stimme.gate)") < BOT.index("teams.register(llm)")


@pytest.fixture(scope="module")
def bot():
    umgebung = {"SONIOX_API_KEY": "dummy-soniox", "ANTHROPIC_API_KEY": "dummy-anthropic", "WAMO_DATABASE_URL": "",
                "WAMO_DB_SCHEMA": "wamo_test", "WAMO_PC_HOST": "off"}
    with mock.patch.dict(os.environ, umgebung):
        import bot as modul
    return modul


def test_betrieb_nennt_teams(bot):
    assert "teams" not in bot.betrieb_message("verbunden")
    assert bot.betrieb_message("verbunden", teams=True)["teams"] is True
