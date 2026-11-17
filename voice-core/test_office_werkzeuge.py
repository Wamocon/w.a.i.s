"""Office-Dateien aus dem Canvas im Kern (office_werkzeuge.py, canvas_quelle.py): canvas_exportieren per Sprache und die Klicks
canvas_export und datei_oeffnen.

Geprüft wird: nur admin, nie im Labor, nur mit Schalter WAMO_OFFICE und PC-Steuerung, nur eigene Canvas-Elemente aus der Datenbank,
nur Formate, die der Host meldet, Stimmabdruck-Gate, Ergebnis an das Modell ohne Pfad, Protokoll in actions ohne Inhalte. Host und
Datenbank sind Attrappen.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import canvas_quelle as cq
import office_werkzeuge as ow
from auth_gate import Identity

UID = "00000000-0000-4000-8000-0000000000a1"
CID = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
GEHEIM = "Vertrauliche Zeile im Angebot"
ADMIN = Identity(UID, "Niko", "admin", "du")
MITGLIED = Identity(UID, "Anna", "mitglied", "du")


@dataclass(frozen=True)
class LaborIdentity(Identity):
    labor_art: str | None = "platz"


class DB:
    def __init__(self, zeilen=(), fehler: Exception | None = None):
        self.zeilen = list(zeilen)
        self.abfragen: list[tuple[str, tuple]] = []
        self.geschrieben: list[tuple[str, tuple]] = []
        self.fehler = fehler

    def t(self, name: str) -> str:
        return f"wamo_test.{name}"

    async def fetchrow(self, sql, *args):
        self.abfragen.append((sql, args))
        if self.fehler:
            raise self.fehler
        return self.zeilen.pop(0) if self.zeilen else None

    async def execute(self, sql, *args):
        self.geschrieben.append((sql, args))
        return "INSERT 0 1"


class Memory:
    def __init__(self, zeilen=(), enabled=True, session_id=SID, fehler=None):
        self.enabled, self.user_id, self.session_id = enabled, UID, session_id
        self.db = DB(zeilen, fehler)


def zeile(kind="dokument", title="Angebot", **daten):
    return {"id": CID, "title": title, "data": json.dumps({"kind": kind, "title": title, **daten})}


DOK = zeile(text=f"# Angebot\n{GEHEIM}")
TAB = zeile("tabelle", "Liste", columns=["a", "b"], rows=[["1", "2"]])


# ---------- canvas_quelle ----------
def _filter(sql: str) -> str:
    """Bedingungen der äußeren Abfrage (auf der Wurzel), ohne den Teil der neuesten Fassung."""
    return sql.split(") n on true", 1)[1]


async def test_lesen_nach_kennung_nur_eigene():
    m = Memory([DOK])
    gefunden = await cq.canvas_lesen(m, canvas_id=CID)
    assert gefunden == {"id": CID, "inhalt": {"art": "dokument", "titel": "Angebot", "text": f"# Angebot\n{GEHEIM}"}}
    sql, args = m.db.abfragen[0]
    filt = _filter(sql)
    assert "w.user_id = $1::uuid" in filt and "w.parent_id is null" in filt and args == (UID, CID)
    assert "coalesce(k.parent_id, k.id)" in filt and "k.id = $2::uuid" in filt  # auch die Kennung einer Fassung führt zur Wurzel


@pytest.mark.parametrize("kennung", ["", "x", "../" + CID, CID + "0", "' or 1=1 --"])
async def test_ungueltige_kennung_fragt_die_datenbank_nicht(kennung):
    m = Memory([DOK])
    assert await cq.canvas_lesen(m, canvas_id=kennung) is None
    assert m.db.abfragen == []


async def test_export_liest_die_neueste_fassung_der_wurzel():
    """Bearbeitungen legen neue Zeilen an (parent_id = Wurzel, version + 1, session_id null): gelesen wird immer die höchste
    Fassung, gefiltert und gezählt wird über die Wurzel."""
    fassung = {"id": CID, "title": "Angebot", "data": json.dumps({"kind": "dokument", "title": "Angebot", "text": "Fassung 3"})}
    m = Memory([fassung])
    gefunden = await cq.canvas_lesen(m, canvas_id=CID)
    assert gefunden == {"id": CID, "inhalt": {"art": "dokument", "titel": "Angebot", "text": "Fassung 3"}}
    sql, _ = m.db.abfragen[0]
    kopf, rest = sql.split("join lateral", 1)
    assert "w.id::text as id" in kopf and "n.title" in kopf and "n.data" in kopf  # Kennung der Wurzel, Inhalt der Fassung
    neueste = rest.split(") n on true", 1)[0]
    assert "x.id = w.id or x.parent_id = w.id" in neueste
    assert "order by x.version desc" in neueste and "limit 1" in neueste
    assert "order by n.updated_at desc limit 1" in _filter(sql)


@pytest.mark.parametrize("titel", ["Test_Plan", "Umsatz in %", r"Pfad C:\Daten"])
async def test_lesen_nach_titel_ohne_platzhalter(titel):
    """Titel mit _ oder % treffen genau diesen Text: keine LIKE-Muster, nichts wird entfernt."""
    m = Memory([DOK])
    await cq.canvas_lesen(m, titel=f"  {titel} ")
    sql, args = m.db.abfragen[0]
    assert "strpos(lower(w.title), lower($2)) > 0" in _filter(sql) and "like" not in sql.lower()
    assert args == (UID, titel)


async def test_ohne_angabe_erst_diese_sitzung_dann_das_profil():
    m = Memory([None, TAB])
    gefunden = await cq.canvas_lesen(m)
    assert gefunden["inhalt"] == {"art": "tabelle", "titel": "Liste", "spalten": ["a", "b"], "zeilen": [["1", "2"]]}
    (sql1, args1), (sql2, args2) = m.db.abfragen
    assert "w.session_id = $2::uuid" in _filter(sql1) and args1 == (UID, SID)
    assert "session_id" not in _filter(sql2) and args2 == (UID,)
    assert all("order by n.updated_at desc limit 1" in s for s, _ in m.db.abfragen)


async def test_datenbankfehler_ist_nicht_nicht_gefunden():
    with pytest.raises(cq.CanvasNichtErreichbar):
        await cq.canvas_lesen(Memory(fehler=OSError("weg")), canvas_id=CID)
    assert await cq.canvas_lesen(Memory([None]), canvas_id=CID) is None


async def test_arten_und_kaputte_daten():
    code = zeile("code", "SQL", text="select 1", language="sql")
    assert (await cq.canvas_lesen(Memory([code]), canvas_id=CID))["inhalt"] == {
        "art": "code", "titel": "SQL", "text": "select 1", "sprache": "sql"}
    merm = zeile("mermaid", "Ablauf", text="flowchart LR")
    assert (await cq.canvas_lesen(Memory([merm]), canvas_id=CID))["inhalt"]["art"] == "mermaid"
    for kaputt in ({"id": CID, "title": "x", "data": "{kein json"}, zeile("bild", text="x"), zeile(text=5)):
        assert await cq.canvas_lesen(Memory([kaputt]), canvas_id=CID) is None
    assert await cq.canvas_lesen(Memory([DOK], enabled=False), canvas_id=CID) is None


# ---------- Schalter und Zugang ----------
@pytest.mark.parametrize("wert,erwartet", [("dateien", {"dateien"}), (" Dateien , outlook ", {"dateien", "outlook"}),
                                           ("", set()), ("alles", set()), ("an", set()), (None, set())])
def test_office_teile(wert, erwartet, monkeypatch):
    monkeypatch.delenv("WAMO_OFFICE", raising=False)
    assert ow.office_teile(wert) == erwartet


def test_standard_ist_aus(monkeypatch):
    monkeypatch.delenv("WAMO_OFFICE", raising=False)
    assert not ow.dateien_an()
    assert not ow.fuer_sitzung(ADMIN)


def test_nur_admin_nie_labor(monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", "dateien")
    assert ow.fuer_sitzung(ADMIN)
    assert not ow.fuer_sitzung(MITGLIED)  # Mitglied ohne Freischaltung (WAMO_PC_MITGLIEDER_PROFILE)
    for art in ("platz", "schaufenster", "unbekannt"):  # auch eine Laboridentität mit Admin-Rolle bekommt nichts
        assert not ow.fuer_sitzung(LaborIdentity(UID, "Gast", "admin", "du", labor_art=art))
    with pytest.raises(ValueError):
        ow.OfficeDateien(MITGLIED, Memory(), client=lambda: object(), darf=lambda: True, senden=None)
    with pytest.raises(ValueError):
        ow.OfficeDateien(LaborIdentity(UID, "Gast", "admin", "du"), Memory(), client=lambda: object(), darf=lambda: True,
                         senden=None)


def test_nicht_in_offenen_werkzeugen_und_nicht_im_labor():
    import labor
    import stimme_gate

    assert ow.WERKZEUG == "canvas_exportieren"
    assert ow.WERKZEUG not in stimme_gate.OFFENE_WERKZEUGE
    assert ow.WERKZEUG not in labor.WERKZEUGE_BASIS


def test_host_werkzeuge_nie_fuer_das_modell():
    import pc_host

    assert not {"office_faehigkeiten", "office_datei_erstellen", "office_datei_oeffnen"} & set(pc_host.LLM_TOOLS)


def test_zeitgrenze_im_tunnel_reicht_fuer_pdf():
    import pc_tunnel

    assert pc_tunnel.LANGE_WERKZEUGE["office_datei_erstellen"] >= 60


def test_zeitleiste_zeigt_nur_das_format():
    import activity

    assert activity.DETAIL_KEYS["canvas_exportieren"] == "format"


def _laden(name: str, pfad: Path):
    import importlib.util
    import sys
    import types

    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"grp": types.ModuleType("grp")}):
        spec.loader.exec_module(modul)
    return modul


def test_schalter_nur_vom_server():
    wurzel = Path(__file__).resolve().parent.parent
    env = _laden("wamo_core_env_office", wurzel / "infra" / "sokrates2" / "wamo_core_env.py")
    assert env.erlaubt("WAMO_OFFICE")
    skript = _laden("wamo_kern_sokrates2_office", wurzel / "scripts" / "wamo_kern_sokrates2.py")
    assert "WAMO_OFFICE" not in skript.AUS_ENV


# ---------- Werkzeug ----------
class Host:
    def __init__(self, faehig=None, ergebnis=None, oeffnen=None):
        self.aufrufe: list[tuple[str, dict]] = []
        self.faehig = faehig if faehig is not None else {"status": "success", "formate": ["word", "excel", "pdf", "csv"],
                                                          "ordner": "Dokumente\\WAIS"}
        self.ergebnis = ergebnis if ergebnis is not None else {
            "status": "success", "geoeffnet": True, "summary": "2026-11-14 Angebot.docx liegt in Dokumente\\WAIS und ist geöffnet.",
            "datei": {"kennung": "0123456789abcdef", "name": "2026-11-14 Angebot.docx", "format": "word", "groesse": 1234,
                      "sha256": "ab" * 32, "ordner": "Dokumente\\WAIS", "pfad": "C:\\Users\\niko\\Dokumente\\WAIS\\2026-11-14 Angebot.docx"}}
        self.oeffnen = oeffnen or {"status": "success", "summary": "geöffnet"}

    async def __call__(self, client, name, arguments):
        self.aufrufe.append((name, arguments))
        if isinstance(self.faehig, Exception) and name == "office_faehigkeiten":
            raise self.faehig
        antwort = {"office_faehigkeiten": self.faehig, "office_datei_erstellen": self.ergebnis,
                   "office_datei_oeffnen": self.oeffnen}[name]
        return json.dumps(antwort)


class Params:
    def __init__(self, **arguments):
        self.arguments = arguments
        self.function_name = ow.WERKZEUG
        self.ergebnis = None

    async def result_callback(self, ergebnis):
        self.ergebnis = ergebnis


class LLM:
    def __init__(self):
        self.handler: dict = {}

    def register_function(self, name, handler, *args, **kwargs):
        self.handler[name] = (handler, kwargs)


@pytest.fixture
def host(monkeypatch):
    h = Host()
    monkeypatch.setattr(ow, "call_host_tool", h)
    return h


def office(memory=None, darf=True, identitaet=ADMIN, knapp=False):
    gesendet: list[dict] = []

    async def senden(d):
        gesendet.append(d)

    o = ow.OfficeDateien(identitaet, memory or Memory([DOK]), client=lambda: object(), darf=lambda: darf, senden=senden, knapp=knapp)
    o.gesendet = gesendet
    return o


def test_freigeschaltetes_mitglied_bekommt_office_dateien(monkeypatch):
    """Entscheidung Niko vom 16.11.2026: Mitglieder mit Freischaltung (WAMO_PC_MITGLIEDER_PROFILE) auch für Office, nur mit Schalter."""
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", UID)
    monkeypatch.setenv("WAMO_OFFICE", "dateien")
    assert ow.pc_person(MITGLIED) and ow.fuer_sitzung(MITGLIED)
    ow.OfficeDateien(MITGLIED, Memory(), client=lambda: object(), darf=lambda: True, senden=None)
    for art in ("platz", "schaufenster"):  # ein Laborprofil auch dann nicht, wenn seine user_id in der Liste steht
        labor = LaborIdentity(UID, "Gast", "mitglied", "du", labor_art=art)
        assert not ow.pc_person(labor) and not ow.fuer_sitzung(labor)
        with pytest.raises(ValueError):
            ow.OfficeDateien(labor, Memory(), client=lambda: object(), darf=lambda: True, senden=None)
    monkeypatch.setenv("WAMO_OFFICE", "")
    assert not ow.fuer_sitzung(MITGLIED)  # ohne Schalter am Server nichts


async def test_mitglied_ohne_dateinamen_in_actions(host, monkeypatch):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", UID)
    m = Memory([DOK])
    o = office(m, identitaet=MITGLIED, knapp=True)
    await o.schemas()
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis["status"] == "success" and p.ergebnis["datei"] == "2026-11-14 Angebot.docx"  # das Modell nennt die Datei
    _sql, werte = m.db.geschrieben[-1]
    assert json.loads(werte[7]) == {"status": "success", "groesse": 1234, "sha256": "ab" * 8}  # kein Titel in actions
    assert "Angebot" not in json.dumps(werte, default=str)


async def test_nach_freigabe_derselbe_weg_mit_satz_fuer_das_modell(host, monkeypatch):
    monkeypatch.setenv("WAMO_PC_MITGLIEDER_PROFILE", UID)
    o = office(Memory([DOK]), identitaet=MITGLIED, knapp=True)
    await o.schemas()
    ergebnis = await o.nach_freigabe({"format": "word"})
    assert ergebnis["status"] == "success" and ergebnis["gespeichert"] is True
    assert ergebnis["summary"] == "2026-11-14 Angebot.docx im Ordner Dokumente\\WAIS gespeichert und geöffnet"
    assert [n for n, _a in host.aufrufe].count("office_datei_erstellen") == 1
    abgelehnt = await o.nach_freigabe({"format": "exe"})
    assert abgelehnt["status"] == "rejected" and "gespeichert" not in abgelehnt


async def test_schema_mit_den_formaten_des_hosts(host):
    o = office()
    schemas = await o.schemas()
    assert [s.name for s in schemas] == ["canvas_exportieren"]
    assert schemas[0].properties["format"]["enum"] == ["word", "excel", "pdf", "csv"]
    assert o.formate == ("word", "excel", "pdf", "csv")
    assert o.anzeige() == ["word", "excel", "pdf", "csv"]
    assert office(darf=False).anzeige() == []


@pytest.mark.parametrize("faehig", [{"status": "blocked", "formate": [], "summary": "aus"}, {"status": "success", "formate": ["exe"]},
                                    OSError("weg")])
async def test_ohne_faehigkeiten_kein_werkzeug(monkeypatch, faehig):
    monkeypatch.setattr(ow, "call_host_tool", Host(faehig=faehig))
    o = office()
    assert await o.schemas() == []
    assert o.anzeige() == []


async def test_registrierung_laeuft_durch_das_stimmabdruck_gate(host):
    import stimme_gate

    llm = LLM()
    gate = stimme_gate.StimmGate()
    stimme_gate.werkzeuge_absichern(llm, gate)
    office().register(llm)
    handler, kwargs = llm.handler["canvas_exportieren"]
    assert getattr(handler, stimme_gate.MARKE) is gate
    assert kwargs["timeout_secs"] >= 75
    # Ein Einwurf bricht den Aufruf nicht ab: Datei, Protokoll und Hinweis in der Oberfläche entfallen sonst, obwohl der PC
    # die Datei schon anlegt (Pipecat 1.x: asynchroner Aufruf, das Ergebnis kommt nach)
    assert kwargs["cancel_on_interruption"] is False


def test_pipecat_kennt_asynchrone_werkzeuge():
    import inspect

    from pipecat.services.llm_service import LLMService

    assert "cancel_on_interruption" in inspect.signature(LLMService.register_function).parameters


def test_beschreibung_sagt_wo_die_datei_liegt():
    text = ow.schema(("word",)).description
    assert "verlässt den PC nicht" not in text
    assert "Dokumente" in text and "OneDrive" in text


async def test_word_per_sprache(host):
    m = Memory([DOK])
    o = office(m)
    await o.schemas()
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "success", "gespeichert": True, "datei": "2026-11-14 Angebot.docx", "geoeffnet": True,
                          "ordner": "Dokumente\\WAIS"}
    name, args = host.aufrufe[-1]
    assert name == "office_datei_erstellen"
    assert args == {"format": "word", "inhalt": {"art": "dokument", "titel": "Angebot", "text": f"# Angebot\n{GEHEIM}"},
                    "oeffnen": True, "canvas_id": CID}
    datei = o.gesendet[-1]
    assert datei["type"] == "datei" and datei["ok"] is True and datei["kennung"] == "0123456789abcdef"
    assert datei["pfad"].endswith("Angebot.docx")
    assert "pfad" not in json.dumps(p.ergebnis)  # der Pfad geht nur an die Oberfläche, nie an das Modell
    sql, werte = m.db.geschrieben[-1]
    assert "insert into wamo_test.actions" in sql
    assert werte[2] == "canvas_exportieren" and json.loads(werte[3]) == {"format": "word", "canvas_id": CID, "quelle": "sprache"}
    assert json.loads(werte[7]) == {"status": "success", "datei": "2026-11-14 Angebot.docx", "groesse": 1234, "sha256": "ab" * 8}
    assert GEHEIM not in json.dumps(werte, default=str)
    assert werte[5:7] == ("change", "done")


async def test_pc_steuerung_aus(host):
    o = office(darf=False)
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "PC-Steuerung" in p.ergebnis["summary"]
    assert host.aufrufe == []


async def test_format_nicht_verfuegbar_oder_unpassend(host):
    o = office(Memory([DOK, DOK]))
    o.formate = ("word", "excel")
    p = Params(format="pdf")
    await o._werkzeug(p)
    assert p.ergebnis["status"] == "rejected"
    p = Params(format="excel")
    await o._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "Tabelle" in p.ergebnis["summary"]
    assert host.aufrufe == []


async def test_kein_eigenes_canvas(host):
    o = office(Memory([None, None]))
    o.formate = ("word",)
    p = Params(format="word", canvas="Gibt es nicht")
    await o._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "Canvas" in p.ergebnis["summary"]
    assert host.aufrufe == []


async def test_datenbank_weg_ist_eine_eigene_meldung(host):
    o = office(Memory(fehler=OSError("weg")))
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "error", "summary": ow.CANVAS_NICHT_ERREICHBAR}
    assert ow.CANVAS_NICHT_ERREICHBAR.startswith("Das Canvas ist gerade nicht erreichbar")
    assert ow.KEIN_CANVAS != ow.CANVAS_NICHT_ERREICHBAR
    assert host.aufrufe == []


async def test_ablehnung_des_hosts_wird_weitergegeben(monkeypatch):
    monkeypatch.setattr(ow, "call_host_tool", Host(ergebnis={"status": "blocked", "summary": "Office-Dateien sind aus."}))
    m = Memory([DOK])
    o = office(m)
    o.formate = ("word",)
    p = Params(format="word", oeffnen=False)
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "blocked", "summary": "Office-Dateien sind aus."}
    assert "failed" in m.db.geschrieben[-1][1]


async def test_host_nicht_erreichbar(monkeypatch):
    async def kaputt(*_a):
        raise OSError("Tunnel weg")

    monkeypatch.setattr(ow, "call_host_tool", kaputt)
    o = office()
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "error", "summary": ow.KEINE_ANTWORT}


async def test_host_zeitgrenze(monkeypatch):
    async def haengt(*_a):
        raise TimeoutError

    monkeypatch.setattr(ow, "call_host_tool", haengt)
    m = Memory([DOK])
    o = office(m)
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "error", "summary": ow.KEINE_ANTWORT}
    assert "failed" in m.db.geschrieben[-1][1]
    assert o.gesendet == []


@pytest.mark.parametrize("datei", [None, {}, {"kennung": "../x"}, {"kennung": "0123456789ABCDEF"}, "kaputt"])
async def test_erfolg_ohne_gueltige_datei_ist_ein_fehler(monkeypatch, datei):
    monkeypatch.setattr(ow, "call_host_tool", Host(ergebnis={"status": "success", "geoeffnet": True, "datei": datei}))
    o = office()
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis == {"status": "error", "summary": ow.KEINE_ANTWORT}
    assert o.gesendet == []
    assert ow.KEINE_ANTWORT == "Der PC hat keine verwertbare Antwort geliefert."


async def test_nicht_geoeffnet_nennt_dem_modell_den_grund(monkeypatch):
    ergebnis = {"status": "success", "geoeffnet": False,
                "summary": "2026-11-14 Angebot.docx liegt in Dokumente\\WAIS. Der Bildschirm ist gesperrt, deshalb ist sie noch "
                           "nicht geöffnet." + chr(0x202E),
                "datei": {"kennung": "0123456789abcdef", "name": "2026-11-14 Angebot.docx", "format": "word", "groesse": 1,
                          "sha256": "ab" * 32, "ordner": "Dokumente\\WAIS", "pfad": "C:\\Users\\niko\\x.docx"}}
    monkeypatch.setattr(ow, "call_host_tool", Host(ergebnis=ergebnis))
    o = office()
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert p.ergebnis["geoeffnet"] is False
    assert "gesperrt" in p.ergebnis["hinweis"] and chr(0x202E) not in p.ergebnis["hinweis"]
    assert "C:\\Users" not in json.dumps(p.ergebnis)


async def test_geoeffnet_ohne_hinweis(host):
    o = office()
    o.formate = ("word",)
    p = Params(format="word")
    await o._werkzeug(p)
    assert "hinweis" not in p.ergebnis


class LangsamerHost(Host):
    def __init__(self):
        super().__init__()
        import asyncio

        self.weiter = asyncio.Event()

    async def __call__(self, client, name, arguments):
        if name == "office_datei_erstellen":
            await self.weiter.wait()
        return await super().__call__(client, name, arguments)


async def test_doppelklick_erzeugt_keine_zweite_datei(monkeypatch):
    import asyncio

    h = LangsamerHost()
    monkeypatch.setattr(ow, "call_host_tool", h)
    o = office(Memory([TAB, TAB, TAB]))
    o.formate = ("excel",)
    erster = asyncio.create_task(o.client_nachricht("canvas_export", {"canvas_id": CID, "format": "excel"}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await o.client_nachricht("canvas_export", {"canvas_id": CID, "format": "excel"})
    assert o.gesendet[-1] == {"type": "datei", "ok": False, "grund": ow.LAEUFT_SCHON}
    h.weiter.set()
    await erster
    assert [n for n, _ in h.aufrufe].count("office_datei_erstellen") == 1
    assert o.gesendet[-1]["ok"] is True
    # danach geht es wieder
    await o.client_nachricht("canvas_export", {"canvas_id": CID, "format": "excel"})
    assert [n for n, _ in h.aufrufe].count("office_datei_erstellen") == 2


async def test_sperre_faellt_auch_nach_einem_fehler(monkeypatch):
    async def kaputt(*_a):
        raise OSError("weg")

    monkeypatch.setattr(ow, "call_host_tool", kaputt)
    o = office(Memory([DOK, DOK]))
    o.formate = ("word",)
    for _ in range(2):
        p = Params(format="word")
        await o._werkzeug(p)
        assert p.ergebnis["summary"] == ow.KEINE_ANTWORT


# ---------- Klicks aus der Oberfläche ----------
async def test_klick_export_nach_kennung(host):
    m = Memory([TAB])
    o = office(m)
    o.formate = ("excel",)
    await o.client_nachricht("canvas_export", {"canvas_id": CID, "format": "excel"})
    assert m.db.abfragen[0][1] == (UID, CID)
    assert host.aufrufe[-1][0] == "office_datei_erstellen"
    assert o.gesendet[-1]["ok"] is True


@pytest.mark.parametrize("daten", [{"canvas_id": "x", "format": "word"}, {"canvas_id": CID, "format": "exe"}, {}, "kaputt"])
async def test_klick_export_ungueltig(host, daten):
    o = office()
    o.formate = ("word",)
    await o.client_nachricht("canvas_export", daten)
    assert host.aufrufe == []
    assert o.gesendet[-1]["type"] == "datei" and o.gesendet[-1]["ok"] is False


async def test_klick_export_ohne_pc_steuerung(host):
    o = office(darf=False)
    o.formate = ("word",)
    await o.client_nachricht("canvas_export", {"canvas_id": CID, "format": "word"})
    assert host.aufrufe == [] and o.gesendet[-1]["ok"] is False


async def test_klick_oeffnen(host):
    o = office()
    await o.client_nachricht("datei_oeffnen", {"kennung": "0123456789abcdef"})
    assert host.aufrufe[-1] == ("office_datei_oeffnen", {"kennung": "0123456789abcdef"})
    for kaputt in ({"kennung": "../x"}, {"kennung": 5}, {}):
        await o.client_nachricht("datei_oeffnen", kaputt)
    assert len(host.aufrufe) == 1
    o_aus = office(darf=False)
    await o_aus.client_nachricht("datei_oeffnen", {"kennung": "0123456789abcdef"})
    assert len(host.aufrufe) == 1 and o_aus.gesendet[-1]["ok"] is False


async def test_klick_im_ordner_zeigen(host):
    """Wunsch von Niko vom 17.11.2026: Der Knopf zeigt die Datei im Explorer (Dokumente\\WAIS). Nur ein echtes true zählt."""
    o = office()
    await o.client_nachricht("datei_oeffnen", {"kennung": "0123456789abcdef", "ordner": True})
    assert host.aufrufe[-1] == ("office_datei_oeffnen", {"kennung": "0123456789abcdef", "im_ordner": True})
    await o.client_nachricht("datei_oeffnen", {"kennung": "0123456789abcdef", "ordner": "ja"})
    assert host.aufrufe[-1] == ("office_datei_oeffnen", {"kennung": "0123456789abcdef"})
    assert o.gesendet == []


async def test_doppelklick_beim_oeffnen_ist_kein_fehler(monkeypatch):
    """Befund 17.11.2026: Jeder weitere Klick bekam vom Host "duplicate" und zeigte einen roten Hinweis."""
    h = Host(oeffnen={"status": "duplicate", "summary": "Die Datei wird gerade schon geöffnet."})
    monkeypatch.setattr(ow, "call_host_tool", h)
    o = office()
    await o.client_nachricht("datei_oeffnen", {"kennung": "0123456789abcdef", "ordner": True})
    assert len(h.aufrufe) == 1 and o.gesendet == []


# ---------- Verdrahtung in bot.py (statisch, die Sitzung braucht Netz und Modelle) ----------
BOT = (Path(__file__).with_name("bot.py")).read_text(encoding="utf-8")


def test_bot_baut_office_nur_fuer_admin_ohne_labor():
    assert BOT.count("OfficeDateien(") == 1
    zeile = next(z for z in BOT.splitlines() if "OfficeDateien(" in z)
    block = BOT[BOT.index(zeile) - 400: BOT.index(zeile) + 400]
    assert "office_werkzeuge.fuer_sitzung(identity)" in block
    assert "pc_person" in block and "not labor_sitzung" in block and "pc_teile and pc_person" in block
    assert "is_admin" not in block  # die Stufe der PC-Steuerung entscheidet, nicht die Rolle allein
    # pc_teile: mit Client oder solange der Zugang zum Laptop nachgeholt werden kann (pc_nachverbinden.py), sonst nie
    assert "pc_teile = pc_client is not None or pc_nachholen" in BOT
    assert "darf=pc_allowed" in block


def test_bot_haengt_schemas_an_und_leitet_klicks_weiter():
    assert "await office.schemas()" in BOT
    assert "office.register(llm)" in BOT
    assert "msg.type in office_werkzeuge.NACHRICHTEN" in BOT
    baum = ast.parse(BOT)
    assert any(isinstance(k, ast.Import) and any(a.name == "office_werkzeuge" for a in k.names) for k in ast.walk(baum))
    weiter = BOT.index("msg.type in office_werkzeuge.NACHRICHTEN")
    assert weiter < BOT.index("elif dev:\n            await dev.on_client_message")
    assert "office=office.anzeige() if office is not None else None" in BOT


@pytest.fixture(scope="module")
def bot():
    umgebung = {"SONIOX_API_KEY": "dummy-soniox", "ANTHROPIC_API_KEY": "dummy-anthropic", "WAMO_DATABASE_URL": "",
                "WAMO_DB_SCHEMA": "wamo_test", "WAMO_PC_HOST": "off"}
    with mock.patch.dict(os.environ, umgebung):
        import bot as modul
    return modul


def test_betrieb_nennt_die_formate(bot):
    assert "office" not in bot.betrieb_message("verbunden")
    assert bot.betrieb_message("verbunden", office=["word", "pdf"])["office"] == ["word", "pdf"]
    assert "office" not in bot.betrieb_message("verbunden", office=[])


def test_namen_in_paketen_und_text_ohne_fremdes():
    assert ow.FORMATE == ("word", "excel", "powerpoint", "pdf", "csv", "markdown")
    assert set(ow.FORMATE_JE_ART["tabelle"]) == set(ow.FORMATE)
    assert SimpleNamespace(**ow.FORMAT_NAMEN).pdf == "PDF"
