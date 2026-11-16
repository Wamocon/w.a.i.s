"""PC-Steuerung für Mitglieder (Paket P4, Plan docs/ausrollen-neue-nutzer.md 4.5, 6.1 P4, Befund H1, Entscheidung N10, Befund S15).

Geprüft wird:
  * die Pflichtstufe der Stimme (stimme_gate.StimmGate.pflicht_grund): ohne Abdruck nur getippt, in jedem Modus, und nur bis wieder
    gesprochen wird; mit bereiter Prüfung dieselbe Regel wie sonst,
  * der Schutz vor jedem PC-Werkzeug eines Mitglieds (pc_mitglied.MitgliedSchutz): Liste, Stimme, Karte nach Fremdinhalt,
  * die Freigabe des Kerns (pc_freigaben.PcFreigaben.kern_vormerken): Karte über activity.py, Ausführung erst nach dem Ja, genau einmal,
  * die Sitzung (bot.py): ein freigeschaltetes Mitglied bekommt genau LLM_TOOLS_MITGLIED (auch nachgeholt), keinen Bildschirm, den Prompt
    für Mitglieder und eigene Freigabekarten; ohne Freischaltung bleibt der Schalter aus.

Ausführen:  python -m pytest -q test_pc_mitglied.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import json
import types
from unittest import mock

import numpy as np
import pytest

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregator

import activity
import pc_host
import pc_mitglied
import persona
from auth_gate import Identity
import pc_freigaben
from pc_freigaben import PcFreigaben
from stimme_gate import EIGEN, FREMD, StimmGate
from test_pc_freigaben import SCHLUESSEL, Client, Gedaechtnis, Host
from test_pc_nachverbinden import (  # noqa: F401 (buero ist eine Fixture)
    USER,
    Lage,
    abwarten,
    bauen,
    betrieb,
    bot,
    buero,
    gesendet,
    klick,
    kontext_namen,
    pc_zugang_test,
)

ADMIN_WERKZEUGE_NIE = ("powershell_lesen", "git_klonen", "github_repo_anlegen", "bildschirm_ansehen", "auf_bildschirm_klicken")


class Uhr:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def gate(modus: str = "streng", abdruck: bool = False) -> StimmGate:
    g = StimmGate(modus=modus, uhr=Uhr())
    g.setze_abdruck(np.ones(4) if abdruck else None)
    g.modell_ok = True
    return g


# ---------- Pflichtstufe der Stimme ----------
@pytest.mark.parametrize("modus", ["aus", "beobachten", "streng"])
def test_ohne_abdruck_nur_getippt_in_jedem_modus(modus):
    g = gate(modus)
    assert g.pflicht_grund() is not None  # noch nichts getippt
    g.getippt()
    assert g.pflicht_grund() is None
    g.uhr.t += 1
    g.gesprochen()  # danach spricht jemand: das Getippte trägt nicht mehr
    assert g.pflicht_grund() is not None
    g.uhr.t += 1
    g.getippt()
    assert g.pflicht_grund() is None
    g.uhr.t += g.schwellen.vertrauen_secs + 1  # getippt gilt nur so lange wie eine erkannte Stimme
    assert g.pflicht_grund() is not None


@pytest.mark.parametrize("modus", ["beobachten", "streng"])
def test_mit_abdruck_gilt_die_erkannte_stimme(modus):
    g = gate(modus, abdruck=True)
    assert g.status == "bereit"
    g.eintragen(EIGEN)
    assert g.pflicht_grund() is None
    g.eintragen(FREMD)
    assert g.pflicht_grund() == "fremde Stimme"


def test_abdruck_aber_modus_aus_heisst_nur_getippt():
    g = gate("aus", abdruck=True)
    g.eintragen(EIGEN)  # im Modus aus prüft niemand; ein Eintrag zählt dort nicht
    assert g.pflicht_grund() == "Stimmprüfung ist aus, PC-Befehle nur getippt"
    g.getippt()
    assert g.pflicht_grund() is None


async def test_pflicht_pruefen_liefert_eine_klare_ablehnung():
    g = gate("beobachten")  # beobachten sperrt sonst nichts: die Pflichtstufe schon
    assert await g.pruefen("programm_oeffnen") is None
    ergebnis = await g.pflicht_pruefen("programm_oeffnen")
    assert ergebnis["status"] == "blocked" and "Stimmabdruck" in ergebnis["grund"]
    g.getippt()
    assert await g.pflicht_pruefen("programm_oeffnen") is None


# ---------- Schutz vor jedem Werkzeug ----------
class Vormerken:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.aufrufe: list[tuple[str, str, dict]] = []

    def __call__(self, kennung, werkzeug, argumente):
        self.aufrufe.append((kennung, werkzeug, argumente))
        return self.ok


def schutz(fremd: bool = False, ok: bool = True, mit_gate: bool = True):
    g = gate()
    g.getippt()
    v = Vormerken(ok)
    s = pc_mitglied.MitgliedSchutz(gate=g if mit_gate else None, fremd=lambda: fremd, vormerken=v,
                                   kennung=lambda: "00112233aabbccdd")
    return s, v, g


@pytest.mark.parametrize("werkzeug", ["powershell_lesen", "git_klonen", "github_repo_anlegen", "bildschirm_ansehen",
                                      "auf_bildschirm_klicken", "maus_klicken", "freigabe_entscheiden", "unbekannt"])
async def test_nur_die_werkzeuge_der_mitglieder(werkzeug):
    s, v, _g = schutz()
    ergebnis = await s.vorab(werkzeug, {})
    assert ergebnis["status"] == "blocked" and v.aufrufe == []


async def test_ohne_gate_geht_nichts():
    s, _v, _g = schutz(mit_gate=False)
    assert (await s.vorab("programm_oeffnen", {"name": "notepad"}))["status"] == "blocked"


async def test_gesprochen_ohne_abdruck_wird_gesperrt():
    s, v, g = schutz()
    g.uhr.t += 1
    g.gesprochen()
    ergebnis = await s.vorab("programm_oeffnen", {"name": "notepad"})
    assert ergebnis["status"] == "blocked" and "Stimmabdruck" in ergebnis["grund"] and v.aufrufe == []


async def test_ohne_fremdinhalt_ohne_karte():
    s, v, _g = schutz(fremd=False)
    for werkzeug in pc_host.LLM_TOOLS_MITGLIED:
        assert await s.vorab(werkzeug, {}) is None
    assert v.aufrufe == []


async def test_nach_fremdinhalt_karte_fuer_jedes_aendernde_werkzeug():
    for werkzeug in sorted(pc_mitglied.AENDERN_MITGLIED):
        s, v, _g = schutz(fremd=True)
        ergebnis = await s.vorab(werkzeug, {"text": "Hallo\nWelt", "zahl": 3})
        assert ergebnis["status"] == "needs_approval" and ergebnis["aktion"] == "aendern", werkzeug
        assert ergebnis["approval_id"] == "00112233aabbccdd"
        assert ergebnis["detail"] == f"Werkzeug: {werkzeug}\ntext: Hallo⏎\nWelt\nzahl: 3"  # jedes Enter sichtbar
        assert v.aufrufe == [("00112233aabbccdd", werkzeug, {"text": "Hallo\nWelt", "zahl": 3})]
        # activity.py macht daraus eine Karte (die ändernden Werkzeuge der Mitglieder stehen in FREIGABE_WERKZEUGE)
        anfrage = activity.freigabe_anfrage(werkzeug, {}, ergebnis, "call-1")
        assert anfrage["id"] == "00112233aabbccdd" and anfrage["aktion"] == "aendern", werkzeug


async def test_lesende_werkzeuge_brauchen_auch_nach_fremdinhalt_keine_karte():
    assert pc_mitglied.LESEN_MITGLIED <= set(pc_host.LLM_TOOLS_MITGLIED)
    assert pc_mitglied.AENDERN_MITGLIED | pc_mitglied.LESEN_MITGLIED == set(pc_host.LLM_TOOLS_MITGLIED)
    for werkzeug in pc_mitglied.LESEN_MITGLIED:
        s, v, _g = schutz(fremd=True)
        assert await s.vorab(werkzeug, {}) is None and v.aufrufe == []


async def test_zu_lang_oder_voll_heisst_nicht_ausgefuehrt():
    s, v, _g = schutz(fremd=True)
    ergebnis = await s.vorab("tastatur_tippen", {"text": "x" * (pc_mitglied.MAX_WERT_ZEICHEN + 1)})
    assert ergebnis["status"] == "blocked" and v.aufrufe == []
    s, v, _g = schutz(fremd=True, ok=False)
    assert (await s.vorab("tastatur_tippen", {"text": "x"}))["status"] == "blocked"


@pytest.mark.parametrize("wert", ["Hallo\u202e Welt", "a\x07b", "a\u200bb", "Tab\tTab", "a\x1bb", "a\rb", "Tag\U000e0041",
                                  {"verschachtelt": "x\u202ey"}])
async def test_was_die_karte_nicht_zeigen_kann_wird_nicht_ausgefuehrt(wert):
    """Befund H1 aus dem Sicherheitsreview: Die Karte muss genau das zeigen, was nach dem Klick läuft."""
    assert pc_mitglied.karten_detail("tastatur_tippen", {"text": wert}) is None
    s, v, _g = schutz(fremd=True)
    ergebnis = await s.vorab("tastatur_tippen", {"text": wert})
    assert ergebnis["status"] == "blocked" and v.aufrufe == []


def test_zeilenumbrueche_gehen_und_stehen_als_enter_auf_der_karte():
    erwartet = "Werkzeug: tastatur_tippen\ntext: Hallo⏎\nWelt⏎\n"
    assert pc_mitglied.karten_detail("tastatur_tippen", {"text": "Hallo\r\nWelt\n"}) == erwartet


async def test_waehrend_eine_karte_wartet_ruhen_alle_pc_werkzeuge():
    g = gate()
    g.getippt()
    s = pc_mitglied.MitgliedSchutz(gate=g, fremd=lambda: False, vormerken=Vormerken(), karte_offen=lambda: True)
    for werkzeug in pc_host.LLM_TOOLS_MITGLIED:
        assert (await s.vorab(werkzeug, {}))["status"] == "wartet", werkzeug


def test_faerben_wirkt_nur_bei_lesenden_werkzeugen_nach():
    from tools import TurnState

    turn = TurnState()
    s = pc_mitglied.MitgliedSchutz(gate=None, fremd=lambda: False, vormerken=Vormerken(),
                                   faerben=lambda nachwirkend: turn.taint(nachwirkend=nachwirkend))
    n = pc_mitglied.NACHWIRKUNG_ZUEGE
    turn.new_user_turn("Öffne Notepad")
    s.faerben("programm_oeffnen")
    assert turn.tainted and turn.fremd_fuer_karte(n)  # im selben Zug: Karte
    turn.new_user_turn("Tippe Hallo")
    assert not turn.fremd_fuer_karte(n)  # das Ergebnis eines ändernden Werkzeugs wirkt nicht nach
    s.faerben("browser_lesen")
    for _ in range(n):
        turn.new_user_turn("Mach weiter")
        assert turn.fremd_fuer_karte(n)  # Befund M1: ein "mach weiter" nach einer Webseite
    turn.new_user_turn("Und jetzt?")
    assert not turn.fremd_fuer_karte(n)
    turn.taint()  # jede andere Quelle (Websuche, Boss, Freigabe) wirkt nach
    turn.new_user_turn("weiter")
    assert turn.fremd_fuer_karte(n)


async def test_gate_pc_tools_faerbt_je_werkzeug_und_ruft_bei_ablehnung_nichts():
    aufrufe, gefaerbt, fremd = [], [], []

    async def original(params):
        aufrufe.append(params.function_name)
        await params.result_callback({"status": "success"})

    async def vorab(name, _args):
        return {"status": "blocked"} if name == "tastatur_tippen" else None

    schemas = [FunctionSchema(n, "PC", {}, [], handler=original) for n in ("browser_lesen", "tastatur_tippen")]
    gated = bot.gate_pc_tools(schemas, lambda: True, lambda: fremd.append(1), vorab=vorab, faerben=gefaerbt.append)
    ergebnisse = []

    async def merken(ergebnis, **_kw):
        ergebnisse.append(ergebnis)

    for s in gated:
        await s.handler(types.SimpleNamespace(function_name=s.name, arguments={}, result_callback=merken, tool_call_id="c"))
    assert aufrufe == ["browser_lesen"] and gefaerbt == ["browser_lesen"] and fremd == []
    assert ergebnisse[1] == {"status": "blocked"}


# ---------- Freigabe des Kerns (pc_freigaben.py) ----------
AID = "00112233aabbccdd"


class Aufbau:
    def __init__(self, monkeypatch, antwort=None):
        self.host = Host(antwort)
        monkeypatch.setattr(pc_host, "call_host_tool", self.host)
        self.client = Client()
        pc_host._FREIGABE_SCHLUESSEL[self.client] = SCHLUESSEL
        self.gedaechtnis = Gedaechtnis()
        self.meldungen: list[str] = []
        self.karten: list[dict] = []
        self.uhr = [1000.0]

        async def melden(text):
            self.meldungen.append(text)

        async def senden(k):
            self.karten.append(k)

        self.freigaben = PcFreigaben(self.gedaechtnis, client=lambda: self.client, darf=lambda: True, melden=melden,
                                     fremdinhalt=lambda: None, senden=senden, von="Erika", uhr=lambda: self.uhr[0],
                                     kern_erlaubt=pc_mitglied.AENDERN_MITGLIED, knapp=True)

    def karte(self, werkzeug="programm_oeffnen", argumente=None):
        argumente = argumente if argumente is not None else {"name": "notepad"}
        assert self.freigaben.kern_vormerken(AID, werkzeug, argumente)
        ergebnis = {"status": "needs_approval", "approval_id": AID, "aktion": "aendern", "grund": pc_mitglied.GRUND_KARTE,
                    "detail": pc_mitglied.karten_detail(werkzeug, argumente), "gueltig_s": 300}
        return self.freigaben.anfrage(activity.freigabe_anfrage(werkzeug, {}, ergebnis, "call-1"))


async def test_ja_fuehrt_das_vorgemerkte_werkzeug_genau_einmal_aus(monkeypatch):
    t = Aufbau(monkeypatch)
    karte = t.karte()
    assert karte["items"][0]["id"] == AID and "notepad" in karte["items"][0]["detail"]
    assert t.host.aufrufe == []  # vor dem Klick passiert am Laptop nichts
    await t.freigaben.entscheiden({"job": "pc", "id": AID, "entscheidung": "ja"})
    await t.freigaben.entscheiden({"job": "pc", "id": AID, "entscheidung": "ja"})  # Doppelklick
    assert t.host.aufrufe == [("programm_oeffnen", {"name": "notepad"})]
    protokoll = t.gedaechtnis.protokoll[0]
    assert protokoll["risk"] == "change" and protokoll["params"] == {"approval_id": AID, "aktion": "aendern",
                                                                    "werkzeug": "programm_oeffnen"}
    assert "freigegeben" in t.meldungen[-1]


async def test_nein_fragt_den_host_gar_nicht(monkeypatch):
    t = Aufbau(monkeypatch)
    t.karte()
    await t.freigaben.entscheiden({"job": "pc", "id": AID, "entscheidung": "nein"})
    assert t.host.aufrufe == []
    assert ("aktion-1", "rejected") in t.gedaechtnis.aktionen


async def test_sitzungsende_verwirft_ohne_host(monkeypatch):
    t = Aufbau(monkeypatch)
    t.karte()
    assert t.freigaben.kern_vormerken("ffeeddccbbaa0099", "tastatur_tippen", {"text": "x"})
    await t.freigaben.schliessen()
    assert t.host.aufrufe == []
    assert t.freigaben._vorgemerkt == {}


async def test_aendern_ohne_vormerkung_oder_mit_anderem_werkzeug_gibt_keine_karte(monkeypatch):
    t = Aufbau(monkeypatch)
    ergebnis = {"status": "needs_approval", "approval_id": AID, "aktion": "aendern", "grund": "g", "detail": "d"}
    assert t.freigaben.anfrage(activity.freigabe_anfrage("programm_oeffnen", {}, ergebnis)) is None  # etwa vom Host behauptet
    assert t.freigaben.kern_vormerken(AID, "ordner_anlegen", {"pfad": "x"})
    assert t.freigaben.anfrage(activity.freigabe_anfrage("programm_oeffnen", {}, ergebnis)) is None
    # und eine Vormerkung macht keine Anfrage des Hosts mit anderer Aktion zur Freigabe des Kerns
    assert t.freigaben.kern_vormerken("ffeeddccbbaa0099", "tastatur_tippen", {"text": "x"})
    host = dict(ergebnis, approval_id="ffeeddccbbaa0099", aktion="senden")
    assert t.freigaben.anfrage(activity.freigabe_anfrage("tastatur_tippen", {}, host)) is None


async def test_vormerkung_verfaellt_und_ist_begrenzt(monkeypatch):
    t = Aufbau(monkeypatch)
    assert not t.freigaben.kern_vormerken("kein-hex", "programm_oeffnen", {})
    for i in range(pc_freigaben.MAX_OFFEN):
        assert t.freigaben.kern_vormerken(f"{i:016x}", "programm_oeffnen", {})
    assert not t.freigaben.kern_vormerken(f"{9:016x}", "programm_oeffnen", {})  # MAX_OFFEN
    t.uhr[0] += 301
    assert t.freigaben.kern_vormerken(f"{9:016x}", "programm_oeffnen", {})  # die alten sind verfallen
    assert len(t.freigaben._vorgemerkt) == 1


async def test_verlangt_der_host_danach_selbst_eine_freigabe_gibt_es_eine_zweite_karte(monkeypatch):
    zweite = "aaaaaaaaaaaaaaaa"
    t = Aufbau(monkeypatch, antwort={"status": "needs_approval", "approval_id": zweite, "aktion": "senden",
                                     "grund": "Senden", "detail": "Hallo\n", "ziel": "Chat", "gueltig_s": 300})
    t.karte("tastatur_tippen", {"text": "Hallo\n"})
    ergebnis = await t.freigaben.entscheiden({"job": "pc", "id": AID, "entscheidung": "ja"})
    assert ergebnis["status"] == "wartet"  # Befund M4: kein Fehler, die zweite Karte wartet
    assert [k["items"][0]["id"] for k in t.karten if k.get("type") == "freigaben"] == [zweite]
    assert ("aktion-1", "done") in t.gedaechtnis.aktionen and ("aktion-1", "failed") not in t.gedaechtnis.aktionen
    assert {"type": "aktivitaet", "id": "call-1", "name": "tastatur_tippen", "detail": "", "status": "wartet"} in t.karten
    assert t.freigaben.kern_offen() is False  # die zweite ist eine Karte des Hosts: dort ruhen die Eingaben
    await t.freigaben.entscheiden({"job": "pc", "id": zweite, "entscheidung": "ja"})
    assert [n for n, _a in t.host.aufrufe] == ["tastatur_tippen", "freigabe_entscheiden"]
    zweites = t.gedaechtnis.protokoll[1]["params"]  # Befund M3: kein Wortlaut und kein Fenstertitel in actions
    assert zweites == {"approval_id": zweite, "aktion": "senden", "werkzeug": "tastatur_tippen", "detail_zeichen": 6, "ziel_zeichen": 4}


async def test_nur_erlaubte_werkzeuge_und_tief_kopiert(monkeypatch):
    t = Aufbau(monkeypatch)
    for werkzeug in ("powershell_lesen", "maus_klicken", "browser_lesen", "git_klonen"):
        assert not t.freigaben.kern_vormerken(AID, werkzeug, {})  # nur die ändernden Werkzeuge der Mitglieder
    argumente = {"text": {"teil": "Hallo"}}
    assert t.freigaben.kern_vormerken(AID, "element_text_setzen", argumente)
    argumente["text"]["teil"] = "anders"  # eine spätere Änderung am Objekt wirkt nicht auf die Vormerkung
    assert t.freigaben._vorgemerkt[AID][2] == {"text": {"teil": "Hallo"}}
    assert t.freigaben.kern_offen() is True


async def test_ohne_erlaubte_werkzeuge_gibt_es_keine_freigabe_des_kerns(monkeypatch):
    t = Aufbau(monkeypatch)
    admin = PcFreigaben(t.gedaechtnis, client=lambda: t.client, darf=lambda: True, melden=mock.AsyncMock(),
                        fremdinhalt=lambda: None, senden=mock.AsyncMock(), von="Niko")
    assert not admin.kern_vormerken(AID, "programm_oeffnen", {})


# ---------- Prompt ----------
def test_prompt_eines_mitglieds_nennt_keine_werkzeuge_der_admins():
    for schalter in (True, False):
        text = persona.build_system_prompt("Erika", "du", pc_werkzeuge=True, pc_stufe="mitglied", rueckfragen=schalter,
                                           pc_ordner=schalter, browser=schalter, tab=schalter)
        for name in ADMIN_WERKZEUGE_NIE + ("bildschirm_senden", "office_", "outlook_", "teams_", "live_bild"):
            assert name not in text, name
        assert "Stimmabdruck" in text and "elemente_auflisten" in text
    admin = persona.build_system_prompt("Niko", "du", pc_werkzeuge=True, pc_stufe="admin")
    assert "powershell_lesen" in admin and "bildschirm_ansehen" in admin
    assert persona.build_system_prompt("Niko", "du", pc_werkzeuge=True) == admin  # ohne Stufe wie bisher


# ---------- Die Sitzung (bot.py) ----------
def alle_host_werkzeuge() -> ToolsSchema:
    async def ok(params):
        await params.result_callback({"status": "success"})

    return ToolsSchema(standard_tools=[FunctionSchema(n, "PC", {}, [], handler=ok) for n in pc_host.LLM_TOOLS])


def mitglied(uid: str = USER) -> Identity:
    return Identity(uid, "Erika", "mitglied", "sie")


def pc_namen(stufen) -> set[str]:
    return kontext_namen(stufen) & (set(pc_host.LLM_TOOLS) | {"bildschirm_ansehen", "auf_bildschirm_klicken"})


@pytest.fixture
def freigeschaltet(buero):  # noqa: F811
    buero.setenv("WAMO_PC_MITGLIEDER_PROFILE", USER)
    return buero


async def test_freigeschaltetes_mitglied_bekommt_genau_seine_liste(freigeschaltet):
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"
    Lage(freigeschaltet, [zugang])
    freigeschaltet.setattr(bot, "host_tools", mock.AsyncMock(return_value=alle_host_werkzeuge()))
    session, stufen, llm = await bauen(mitglied())
    assert pc_namen(stufen) == set(pc_host.LLM_TOOLS_MITGLIED)
    for name in ADMIN_WERKZEUGE_NIE:
        assert name not in llm._functions, name
    assert betrieb(session)["pc_stufe"] == "mitglied"
    await klick(session, True)
    assert betrieb(session)["pc_steuerung"] == "an"
    await session.cleanup()


async def test_auch_nachgeholt_nur_die_liste_der_mitglieder(freigeschaltet):
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"
    lage = Lage(freigeschaltet, [None, zugang])
    freigeschaltet.setattr(bot, "host_tools", mock.AsyncMock(return_value=alle_host_werkzeuge()))
    session, stufen, _llm = await bauen(mitglied())
    assert betrieb(session)["pc"] == "verbindet"
    await klick(session, True)
    lage.host_client.assert_called_once_with(zugang)
    assert pc_namen(stufen) == set(pc_host.LLM_TOOLS_MITGLIED)
    assert betrieb(session)["pc_steuerung"] == "an"
    await session.cleanup()


async def test_ohne_freischaltung_bleibt_der_schalter_aus(buero):  # noqa: F811
    buero.setenv("WAMO_PC_MITGLIEDER_PROFILE", "33333333-3333-4333-8333-333333333333")
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"  # selbst wenn ein Zugang käme: der Handler prüft die Stufe der Sitzung
    Lage(buero, [zugang])
    session, _stufen, _llm = await bauen(mitglied())
    await klick(session, True)
    assert betrieb(session)["pc_steuerung"] == "aus"
    assert "pc_stufe" not in betrieb(session)
    await session.cleanup()


async def test_prompt_der_sitzung_ist_der_fuer_mitglieder(freigeschaltet):
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"
    Lage(freigeschaltet, [zugang])
    with mock.patch.object(bot, "build_system_prompt", wraps=bot.build_system_prompt) as prompt:
        session, _stufen, _llm = await bauen(mitglied())
    assert prompt.call_args.kwargs["pc_stufe"] == "mitglied"
    await session.cleanup()


async def test_karte_nach_fremdinhalt_und_ausfuehrung_erst_nach_dem_klick(freigeschaltet):
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"
    Lage(freigeschaltet, [zugang])
    host = Host()
    freigeschaltet.setattr(pc_host, "call_host_tool", host)
    session, stufen, _llm = await bauen(mitglied())
    await klick(session, True)
    nutzer = next(p for p in stufen if isinstance(p, LLMUserAggregator))
    schema = next(s for s in nutzer.context.tools.standard_tools if isinstance(s, FunctionSchema) and s.name == "programm_oeffnen")
    session.stimme.gate.getippt()
    session.turn.taint()  # etwa eine Websuche im selben Zug
    ergebnisse = []

    async def merken(ergebnis, **_kw):
        ergebnisse.append(ergebnis)

    params = types.SimpleNamespace(function_name="programm_oeffnen", arguments={"name": "notepad"}, result_callback=merken,
                                   tool_call_id="call-1")
    await schema.handler(params)
    assert ergebnisse[0]["status"] == "needs_approval" and host.aufrufe == []
    reporter = next(p for p in stufen if isinstance(p, activity.ActivityReporter))
    karte = reporter.on_freigabe(activity.freigabe_anfrage("programm_oeffnen", params.arguments, ergebnisse[0], "call-1"))
    assert karte is not None and karte["items"][0]["id"] == ergebnisse[0]["approval_id"]
    await session.task.rtvi._call_event_handler("on_client_message", types.SimpleNamespace(
        type="freigabe", data={"job": "pc", "id": ergebnisse[0]["approval_id"], "entscheidung": "ja"}))
    await abwarten()
    assert host.aufrufe == [("programm_oeffnen", {"name": "notepad"})]
    await session.cleanup()


async def test_gesprochener_befehl_ohne_abdruck_wird_nicht_ausgefuehrt(freigeschaltet):
    zugang = pc_zugang_test()
    zugang.stufe = "mitglied"
    Lage(freigeschaltet, [zugang])
    session, stufen, _llm = await bauen(mitglied())
    await klick(session, True)
    nutzer = next(p for p in stufen if isinstance(p, LLMUserAggregator))
    schema = next(s for s in nutzer.context.tools.standard_tools if isinstance(s, FunctionSchema) and s.name == "programm_oeffnen")
    ergebnisse = []

    async def merken(ergebnis, **_kw):
        ergebnisse.append(ergebnis)

    await schema.handler(types.SimpleNamespace(function_name="programm_oeffnen", arguments={}, result_callback=merken,
                                               tool_call_id="call-2"))
    assert ergebnisse[0]["status"] == "blocked" and "Stimmabdruck" in ergebnisse[0]["grund"]
    await session.cleanup()


async def test_admin_bleibt_wie_bisher(buero):  # noqa: F811
    zugang = pc_zugang_test()
    zugang.stufe = "admin"
    Lage(buero, [zugang])
    buero.setattr(bot, "host_tools", mock.AsyncMock(return_value=alle_host_werkzeuge()))
    session, stufen, llm = await bauen(Identity(USER, "Niko", "admin", "du"))
    assert set(pc_host.LLM_TOOLS) <= kontext_namen(stufen)
    assert "bildschirm_ansehen" in llm._functions
    assert betrieb(session)["pc_stufe"] == "admin"
    assert json.dumps(gesendet(session))  # nur Daten, die sich senden lassen
    await session.cleanup()
