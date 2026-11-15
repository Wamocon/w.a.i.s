"""OneNote-Seite aus dem Canvas im Kern (onenote_werkzeuge.py): Werkzeug onenote_seite.

Geprüft wird: nur admin, nie im Labor, nur mit WAMO_OFFICE=onenote und PC-Steuerung, nur eigene Canvas-Elemente, Karte aus der Antwort
des Hosts (activity.py, Job pc, Aktion onenote), Rückfall als Word-Datei ohne OneNote, Stimmabdruck-Gate, Verdrahtung in bot.py. Host
und Datenbank sind Attrappen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import activity
import onenote_werkzeuge as onw
from pc_freigaben import AKTION_TEXT
from test_office_werkzeuge import ADMIN, CID, DOK, GEHEIM, LLM, MITGLIED, UID, LaborIdentity, Memory, Params

AID = "0123456789abcdef"
KARTE = {"status": "needs_approval", "approval_id": AID, "aktion": "onenote", "grund": "Seite in OneNote anlegen",
         "detail": f"Seite: Angebot\nInhalt:\n> Angebot\n> {GEHEIM}", "ziel": "OneNote, Notizbuch Arbeit, Abschnitt W.A.I.S.",
         "gueltig_s": 300, "summary": "Das legt eine Seite in deinem OneNote an.", "zusatz": "vom Host, nicht weiterreichen"}
DATEI = {"status": "success", "geoeffnet": True, "summary": "2026-11-15 Angebot.docx liegt in Dokumente\\WAIS und ist geöffnet.",
         "datei": {"kennung": "fedcba9876543210", "name": "2026-11-15 Angebot.docx", "format": "word", "groesse": 999,
                   "sha256": "cd" * 32, "ordner": "Dokumente\\WAIS", "pfad": "C:\\Users\\niko\\Dokumente\\WAIS\\2026-11-15 Angebot.docx"}}


class Host:
    def __init__(self, faehig=None, anfrage=None, datei=None):
        self.aufrufe: list[tuple[str, dict]] = []
        self.faehig = faehig if faehig is not None else {"status": "success", "formate": ["word", "pdf"], "onenote": True,
                                                          "ordner": "Dokumente\\WAIS"}
        self.anfrage = anfrage if anfrage is not None else KARTE
        self.datei = datei if datei is not None else DATEI

    async def __call__(self, client, name, arguments):
        self.aufrufe.append((name, arguments))
        if isinstance(self.anfrage, Exception) and name == "onenote_seite_anfragen":
            raise self.anfrage
        return json.dumps({"office_faehigkeiten": self.faehig, "onenote_seite_anfragen": self.anfrage,
                           "office_datei_erstellen": self.datei}[name])


@pytest.fixture
def host(monkeypatch):
    import office_werkzeuge

    h = Host()
    monkeypatch.setattr(onw, "call_host_tool", h)
    monkeypatch.setattr(office_werkzeuge, "call_host_tool", h)  # Rückfall über OfficeDateien.exportieren
    return h


def seiten(memory=None, darf=True, karte=None):
    gesendet: list[dict] = []

    async def senden(d):
        gesendet.append(d)

    s = onw.OneNoteSeiten(ADMIN, memory or Memory([DOK, DOK]), client=lambda: object(), darf=lambda: darf, senden=senden, karte=karte)
    s.gesendet = gesendet
    return s


def karten_sammler():
    """Wie PcFreigaben.anfrage: registriert die Anfrage und liefert die Karte für die Oberfläche."""
    gesammelt: list[dict] = []

    def anfrage(a: dict) -> dict:
        gesammelt.append(a)
        return {"type": "freigaben", "job": "pc", "projekt": "PC", "items": [a]}

    return anfrage, gesammelt


# ---------- Wer darf ----------
@pytest.mark.parametrize("wert, erwartet", [("", False), ("dateien", False), ("onenote", True), ("dateien, onenote", True),
                                            ("OneNote", True), ("onenot", False)])
def test_nur_mit_schalter(wert, erwartet, monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", wert)
    assert onw.fuer_sitzung(ADMIN) is erwartet


def test_nur_admin_nie_labor(monkeypatch):
    monkeypatch.setenv("WAMO_OFFICE", "onenote")
    assert onw.fuer_sitzung(MITGLIED) is False
    assert onw.fuer_sitzung(LaborIdentity(UID, "Gast", "admin", "du")) is False
    for identitaet in (MITGLIED, LaborIdentity(UID, "Gast", "admin", "du")):
        with pytest.raises(ValueError):
            onw.OneNoteSeiten(identitaet, Memory(), client=lambda: object(), darf=lambda: True, senden=None)


def test_nicht_offen_nicht_im_labor_und_host_werkzeug_nie_fuer_das_modell():
    import labor
    import pc_host
    import stimme_gate

    assert onw.WERKZEUG == "onenote_seite"
    assert onw.WERKZEUG not in stimme_gate.OFFENE_WERKZEUGE
    assert onw.WERKZEUG not in labor.WERKZEUGE_BASIS
    assert "onenote_seite_anfragen" not in pc_host.LLM_TOOLS


def test_karte_und_zeitgrenzen_sind_verdrahtet():
    import pc_tunnel

    assert "onenote" in activity.FREIGABE_AKTIONEN and onw.WERKZEUG in activity.FREIGABE_WERKZEUGE
    assert "onenote" not in AKTION_TEXT  # pc_freigaben.py bleibt fürs Labor unverändert (test_labor_pc_unveraendert.py)
    assert pc_tunnel.LANGE_WERKZEUGE["onenote_seite_anfragen"] > 30 + 5  # Lesen der Notizbücher bis 30 s am PC
    assert onw.ANFRAGEN_TIMEOUT_SECS > pc_tunnel.LANGE_WERKZEUGE["onenote_seite_anfragen"]
    assert activity._detail(onw.WERKZEUG, {"canvas": "Angebot", "titel": GEHEIM}) == ""  # Zeitleiste ohne Texte


# ---------- Fähigkeiten und Registrierung ----------
async def test_schema_nur_wenn_der_host_onenote_kennt(host):
    s = seiten()
    assert [x.name for x in await s.schemas()] == ["onenote_seite"]
    assert (s.onenote, s.word) == (True, True)


@pytest.mark.parametrize("faehig", [{"status": "success", "formate": ["word"]},  # älterer Host ohne OneNote-Werkzeug
                                    {"status": "blocked", "formate": [], "summary": "aus"},
                                    {"status": "success", "formate": [], "onenote": False}])
async def test_ohne_onenote_und_ohne_rueckfall_kein_werkzeug(monkeypatch, faehig):
    monkeypatch.setattr(onw, "call_host_tool", Host(faehig=faehig))
    assert await seiten().schemas() == []


async def test_registrierung_laeuft_durch_das_stimmabdruck_gate(host):
    import stimme_gate

    llm = LLM()
    gate = stimme_gate.StimmGate()
    stimme_gate.werkzeuge_absichern(llm, gate)
    seiten().register(llm)
    handler, kwargs = llm.handler["onenote_seite"]
    assert getattr(handler, stimme_gate.MARKE) is gate
    assert kwargs["timeout_secs"] >= onw.ANFRAGEN_TIMEOUT_SECS + 80
    assert kwargs["cancel_on_interruption"] is False  # sonst legt der Host die Anfrage an, aber die Karte erscheint nie


async def test_je_sitzung_nur_eine_anfrage_zur_zeit(host):
    s = seiten()
    await s.schemas()
    s._laeuft = True  # so, als liefe gerade eine Anfrage
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "gerade schon" in p.ergebnis["summary"]
    assert [n for n, _ in host.aufrufe] == ["office_faehigkeiten"]


async def test_datenbank_weg_ist_ein_fehler_kein_fremdes_canvas(host):
    import asyncpg

    s = seiten(Memory(fehler=asyncpg.PostgresConnectionError("weg")))
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "error" and "nicht erreichbar" in p.ergebnis["summary"]
    assert s._laeuft is False


# ---------- Werkzeug ----------
async def test_anfrage_wird_zur_karte(host):
    s = seiten()
    await s.schemas()
    p = Params(canvas="Angebot", titel="Neuer Titel")
    await s._werkzeug(p)
    name, args = host.aufrufe[-1]
    assert name == "onenote_seite_anfragen"
    assert args == {"inhalt": {"art": "dokument", "titel": "Angebot", "text": f"# Angebot\n{GEHEIM}"}, "titel": "Neuer Titel",
                    "canvas_id": CID}
    assert "zusatz" not in p.ergebnis
    karte = activity.freigabe_anfrage(onw.WERKZEUG, {}, p.ergebnis, "call-1")
    assert karte is not None and karte["aktion"] == "onenote" and karte["id"] == AID
    assert GEHEIM in karte["detail"] and "Abschnitt W.A.I.S." in karte["ziel"]  # was der Host anlegen wird
    assert activity._status(p.ergebnis) == "wartet"
    assert s.gesendet == []  # die Karte schickt activity.py über pc_freigaben, nicht dieses Modul


@pytest.mark.parametrize("anfrage", [{**KARTE, "aktion": "senden"}, {**KARTE, "approval_id": "x"}, OSError("Tunnel weg")])
async def test_fremde_oder_kaputte_antwort_wird_keine_karte(monkeypatch, anfrage):
    monkeypatch.setattr(onw, "call_host_tool", Host(anfrage=anfrage))
    s = seiten()
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "error"
    assert activity.freigabe_anfrage(onw.WERKZEUG, {}, p.ergebnis) is None


async def test_ohne_onenote_rueckfall_als_word_datei(host):
    host.anfrage = {"status": "rejected", "rueckfall": "word", "summary": "OneNote für den Desktop ist nicht installiert."}
    m = Memory([DOK, DOK])
    s = seiten(m)
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    name, args = host.aufrufe[-1]
    assert name == "office_datei_erstellen" and args["format"] == "word" and args["canvas_id"] == CID
    assert p.ergebnis["status"] == "success" and p.ergebnis["gespeichert"] is True and p.ergebnis["onenote"] is False
    assert p.ergebnis["datei"] == "2026-11-15 Angebot.docx"
    assert "An OneNote senden" in p.ergebnis["summary"] and "nicht installiert" in p.ergebnis["summary"]
    assert "pfad" not in json.dumps(p.ergebnis)
    assert s.gesendet[-1]["type"] == "datei" and s.gesendet[-1]["ok"] is True
    _sql, werte = m.db.geschrieben[-1]
    assert json.loads(werte[3]) == {"format": "word", "canvas_id": CID, "quelle": "onenote"}
    assert GEHEIM not in json.dumps(werte, default=str)
    assert activity.freigabe_anfrage(onw.WERKZEUG, {}, p.ergebnis) is None


async def test_ohne_onenote_fragt_der_kern_den_host_gar_nicht_erst(monkeypatch):
    h = Host(faehig={"status": "success", "formate": ["word"], "onenote": False})
    import office_werkzeuge

    monkeypatch.setattr(onw, "call_host_tool", h)
    monkeypatch.setattr(office_werkzeuge, "call_host_tool", h)
    s = seiten()
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert [n for n, _ in h.aufrufe] == ["office_faehigkeiten", "office_datei_erstellen"]
    assert p.ergebnis["gespeichert"] is True


async def test_rueckfall_ohne_word_sagt_es_klar(host):
    host.faehig = {"status": "success", "formate": [], "onenote": True}
    host.anfrage = {"status": "rejected", "rueckfall": "word", "summary": "In OneNote ist kein Notizbuch geöffnet."}
    s = seiten()
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "kein Notizbuch" in p.ergebnis["summary"]
    assert "office_datei_erstellen" not in [n for n, _ in host.aufrufe]


async def test_ablehnung_des_hosts_ohne_rueckfall(host):
    host.anfrage = {"status": "rejected", "summary": "Das ist zu lang für die Freigabekarte\u200b."}
    s = seiten()
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and set(p.ergebnis) == {"status", "summary"}
    assert p.ergebnis["summary"].startswith("Das ist zu lang für die Freigabekarte") and "​" not in p.ergebnis["summary"]


async def test_pc_steuerung_aus_oder_kein_eigenes_canvas(host):
    s = seiten(darf=False)
    await s.schemas()
    p = Params()
    await s._werkzeug(p)
    assert p.ergebnis["status"] == "rejected" and "PC-Steuerung" in p.ergebnis["summary"]
    s = seiten(Memory([]))
    await s.schemas()
    await s._werkzeug(p := Params(canvas="Fremd"))
    assert p.ergebnis["status"] == "rejected" and "Canvas" in p.ergebnis["summary"]
    assert [n for n, _ in host.aufrufe if n != "office_faehigkeiten"] == []


# ---------- Verdrahtung in bot.py (statisch) ----------
BOT = (Path(__file__).with_name("bot.py")).read_text(encoding="utf-8")


def test_bot_baut_onenote_nur_fuer_admin_ohne_labor_und_haengt_das_schema_an():
    assert BOT.count("OneNoteSeiten(") == 1
    zeile = next(z for z in BOT.splitlines() if "OneNoteSeiten(" in z)
    block = BOT[BOT.index(zeile) - 400: BOT.index(zeile) + 400]
    assert "onenote_werkzeuge.fuer_sitzung(identity)" in block
    assert "is_admin" in block and "not labor_sitzung" in block and "pc_client is not None" in block and "darf=pc_allowed" in block
    assert "onenote.register(llm)" in BOT and "await onenote.schemas()" in BOT
    assert BOT.index("werkzeuge_absichern(llm, stimme.gate)") < BOT.index("onenote.register(llm)")
    assert "*onenote_schemas" in BOT


# ---------- Klick im Canvas: "Als OneNote-Seite" ----------
async def test_klick_macht_die_karte_und_meldet_kurz(host):
    anfrage, gesammelt = karten_sammler()
    s = seiten(karte=anfrage)
    await s.schemas()
    await s.client_nachricht({"canvas_id": CID})
    name, args = host.aufrufe[-1]
    assert name == "onenote_seite_anfragen" and args["canvas_id"] == CID and args["titel"] == ""
    assert gesammelt[0]["aktion"] == "onenote" and gesammelt[0]["id"] == AID and gesammelt[0]["werkzeug"] == onw.WERKZEUG
    assert s.gesendet[0]["type"] == "freigaben" and s.gesendet[0]["items"][0]["detail"] == KARTE["detail"]
    assert s.gesendet[-1] == {"type": "onenote", "ok": True, "text": onw.KARTE_BEREIT}


async def test_klick_ohne_karte_lehnt_die_anfrage_am_host_ab(host, monkeypatch):
    abgelehnt: list[tuple] = []

    async def entscheiden(client, aid, ja):
        abgelehnt.append((aid, ja))
        return {"status": "rejected"}

    monkeypatch.setattr(onw, "pc_freigabe_entscheiden", entscheiden)
    s = seiten(karte=lambda a: None)  # zum Beispiel schon fünf Karten offen
    await s.schemas()
    await s.client_nachricht({"canvas_id": CID})
    assert abgelehnt == [(AID, False)]  # sonst ruhen am PC die Eingaben bis zum Ablauf einer Karte, die niemand sieht
    assert s.gesendet == [{"type": "onenote", "ok": False, "text": onw.KEINE_KARTE}]


@pytest.mark.parametrize("daten", [{}, {"canvas_id": "x"}, {"canvas_id": CID + "0"}, "kaputt"])
async def test_klick_ungueltig_fragt_den_host_nicht(host, daten):
    s = seiten(karte=karten_sammler()[0])
    await s.schemas()
    await s.client_nachricht(daten)
    assert [n for n, _ in host.aufrufe] == ["office_faehigkeiten"]
    assert s.gesendet == [{"type": "onenote", "ok": False, "text": "Ungültige Anfrage."}]


async def test_klick_mit_rueckfall_meldet_die_word_datei(host):
    host.anfrage = {"status": "rejected", "rueckfall": "word", "summary": "An diesem PC ist kein OneDrive der Firma angemeldet."}
    s = seiten(karte=karten_sammler()[0])
    await s.schemas()
    await s.client_nachricht({"canvas_id": CID})
    assert s.gesendet[0]["type"] == "datei" and s.gesendet[0]["ok"] is True
    assert s.gesendet[-1]["type"] == "onenote" and s.gesendet[-1]["ok"] is True
    assert "kein OneDrive der Firma" in s.gesendet[-1]["text"] and "An OneNote senden" in s.gesendet[-1]["text"]


async def test_klick_ablehnung_wird_gemeldet(host):
    host.anfrage = {"status": "rejected", "summary": "Das ist zu lang für die Freigabekarte."}
    s = seiten(karte=karten_sammler()[0])
    await s.schemas()
    await s.client_nachricht({"canvas_id": CID})
    assert s.gesendet == [{"type": "onenote", "ok": False, "text": "Das ist zu lang für die Freigabekarte."}]


async def test_anzeige_nur_mit_onenote_karte_und_pc_steuerung(host):
    karte = karten_sammler()[0]
    s = seiten(karte=karte)
    assert s.anzeige() is False  # vor den Fähigkeiten
    await s.schemas()
    assert s.anzeige() is True
    assert (await _mit(seiten(darf=False, karte=karte))).anzeige() is False
    assert (await _mit(seiten())).anzeige() is False  # ohne Karten kein Klickweg
    host.faehig = {"status": "success", "formate": ["word"], "onenote": False}
    assert (await _mit(seiten(karte=karte))).anzeige() is False  # ohne OneNote kein Knopf, per Sprache bleibt der Rückfall


async def _mit(s):
    await s.schemas()
    return s


def test_bot_leitet_den_klick_weiter_und_meldet_den_knopf(bot):
    assert "msg.type == onenote_werkzeuge.NACHRICHT" in BOT
    assert BOT.index("msg.type == onenote_werkzeuge.NACHRICHT") < BOT.index("elif dev:\n            await dev.on_client_message")
    zeile = next(z for z in BOT.splitlines() if "OneNoteSeiten(" in z)
    block = BOT[BOT.index(zeile): BOT.index(zeile) + 600]
    assert "karte=" in block and "freigaben.anfrage" in block
    assert "onenote=onenote is not None and onenote.anzeige()" in BOT
    assert bot.betrieb_message("verbunden", onenote=True)["onenote"] is True
    assert "onenote" not in bot.betrieb_message("verbunden")


@pytest.fixture(scope="module")
def bot():
    import os
    from unittest import mock

    umgebung = {"SONIOX_API_KEY": "dummy-soniox", "ANTHROPIC_API_KEY": "dummy-anthropic", "WAMO_DATABASE_URL": "",
                "WAMO_DB_SCHEMA": "wamo_test", "WAMO_PC_HOST": "off"}
    with mock.patch.dict(os.environ, umgebung):
        import bot as modul
    return modul
