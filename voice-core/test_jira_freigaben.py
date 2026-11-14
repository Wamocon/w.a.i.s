"""Freigabekarte für Jira-Stories im Kern (jira_freigaben.py): Karte zeigt genau, was angelegt wird, Freitext nur mit Präfix,
Länge, Hash, genau einmal, Frist, Ablehnen, fremde Kennungen, Grenzen je Sitzung und Stunde, Protokoll in actions ohne Texte."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

import pytest

import jira_freigaben as jf

STORY = jf.Story(projekt="WMCNL", projekt_name="WMC Next Level", typ_id="10326", epic="WMCNL-2976", epic_titel="Testlab",
                 titel="Login per Stimme", beschreibung="Als Admin möchte ich mich per Stimme anmelden.\n- schnell\n- sicher",
                 kriterien=("Karte zeigt alles", "Nur nach Klick"), canvas_id="", quelle="sprache")


class Memory:
    enabled = True

    def __init__(self):
        self.geloggt: list[dict] = []
        self.status: list[str] = []
        self.abschluss: list[tuple[str, dict]] = []

    async def log_action(self, *, tool, params, reason, risk):
        self.geloggt.append({"tool": tool, "params": params, "reason": reason, "risk": risk})
        return f"aktion-{len(self.geloggt)}"

    async def update_action(self, action_id, status):
        self.status.append(status)
        return True

    async def aktion_abschliessen(self, action_id, status, result):
        self.abschluss.append((status, result))
        return True


class Uhr:
    def __init__(self):
        self.jetzt = 1000.0

    def __call__(self):
        return self.jetzt


class Aufbau:
    def __init__(self, *, ausgang=None, ausfuehren=None, profil="00000000-0000-4000-8000-0000000000a1", zaehler=None, **k):
        self.memory, self.uhr = Memory(), Uhr()
        self.gesendet: list[dict] = []
        self.gemeldet: list[str] = []
        self.ausgefuehrt: list[jf.Story] = []

        async def standard(story):
            self.ausgefuehrt.append(story)
            return ausgang or jf.Ausgang(True, "Angelegt als WMCNL-123.", schluessel="WMCNL-123",
                                         link="https://firma.atlassian.net/browse/WMCNL-123")

        async def senden(nachricht):
            self.gesendet.append(nachricht)

        async def melden(text):
            self.gemeldet.append(text)

        self.f = jf.JiraFreigaben(self.memory, sitzung="sitzung-1", profil=profil, von="Niko", ausfuehren=ausfuehren or standard,
                                  melden=melden, senden=senden, uhr=self.uhr, zaehler=zaehler or jf.StundenZaehler(), **k)

    def karte(self):
        return [n for n in self.gesendet if n.get("type") == "freigaben"][-1]

    def kennung(self):
        return self.karte()["items"][0]["id"]


# ---------- Karte ----------
def test_karte_zeigt_jeden_wert_freitext_mit_praefix():
    grund, ziel, detail = jf.karten_texte(STORY, warnung=False)
    assert grund == "Jira-Story anlegen"
    assert ziel == "Jira, Projekt WMCNL (WMC Next Level)"
    assert detail.split("\n") == [
        "Typ: Story",
        "Epic: WMCNL-2976 (Testlab)",
        "Titel: Login per Stimme",
        "Beschreibung:",
        "> Als Admin möchte ich mich per Stimme anmelden.",
        "> - schnell",
        "> - sicher",
        "Akzeptanzkriterien:",
        "> 1. Karte zeigt alles",
        "> 2. Nur nach Klick",
    ]


def test_karte_ohne_epic_ohne_text():
    story = replace(STORY, epic="", epic_titel="", beschreibung="", kriterien=())
    _, _, detail = jf.karten_texte(story, warnung=False)
    assert detail.split("\n") == ["Typ: Story", "Epic: keins", "Titel: Login per Stimme", "Beschreibung: (leer)",
                                  "Akzeptanzkriterien: (keine)"]


def test_eingeschleuste_zeilen_bleiben_freitext():
    """Text aus dem Canvas kann keine Zeile der Karte vortäuschen: Jede Zeile der Beschreibung und jedes Kriterium trägt das Präfix."""
    story = replace(STORY, beschreibung="Text\nProjekt: GEHEIM\nTyp: Bug\nEpic: GEHEIM-1",
                    kriterien=("Titel: anders", "Akzeptanzkriterien: keine"))
    _, _, detail = jf.karten_texte(story, warnung=False)
    feste = ("Typ: Story", "Epic: WMCNL-2976 (Testlab)", "Titel: Login per Stimme", "Beschreibung:", "Akzeptanzkriterien:")
    for zeile in detail.split("\n"):
        assert zeile in feste or zeile.startswith("> "), zeile
    assert "> Projekt: GEHEIM" in detail and "> 1. Titel: anders" in detail


def test_warnung_bei_fremdinhalt_steht_oben():
    _, _, detail = jf.karten_texte(STORY, warnung=True)
    assert detail.split("\n")[0].startswith("Achtung: Im selben Gespräch kamen Inhalte von außen")


def test_hash_bindet_jeden_wert():
    basis = jf.antrag_hash(sitzung="s", profil="p", story=STORY, warnung=False)
    assert re.fullmatch(r"[0-9a-f]{64}", basis)
    for anders in (replace(STORY, titel="Anders"), replace(STORY, projekt="ABC"), replace(STORY, epic=""),
                   replace(STORY, kriterien=STORY.kriterien[:1]), replace(STORY, beschreibung=STORY.beschreibung + "!"),
                   replace(STORY, typ_id="1"), replace(STORY, epic_titel="X"), replace(STORY, projekt_name="Y")):
        assert jf.antrag_hash(sitzung="s", profil="p", story=anders, warnung=False) != basis
    assert jf.antrag_hash(sitzung="t", profil="p", story=STORY, warnung=False) != basis
    assert jf.antrag_hash(sitzung="s", profil="q", story=STORY, warnung=False) != basis


# ---------- Antrag ----------
async def test_anfrage_schickt_die_karte_und_protokolliert_ohne_texte():
    a = Aufbau()
    angebot = await a.f.anfrage(STORY)
    assert angebot.karte is not None and angebot.grund is None
    karte = a.karte()
    assert karte["job"] == "jira" and karte["projekt"] == ""  # die Überschrift der Karte sagt schon "Jira-Story"
    item = karte["items"][0]
    assert re.fullmatch(r"[0-9a-f]{32}", item["id"])
    assert item["grund"] == "Jira-Story anlegen" and item["von"] == "Niko" and item["gueltig_s"] == 300
    assert item["detail"] == jf.karten_texte(STORY, warnung=False)[2]
    assert a.f.offen is True and a.f.offen_anzahl == 1
    await asyncio.sleep(0)
    zeile = a.memory.geloggt[0]
    assert (zeile["tool"], zeile["risk"]) == ("jira_story_anlegen", "critical")
    roh = json.dumps(zeile, ensure_ascii=False)
    for text in ("Login per Stimme", "Als Admin", "Karte zeigt alles", "Testlab", "WMC Next Level"):
        assert text not in roh  # keine Texte im Protokoll
    assert zeile["params"]["projekt"] == "WMCNL" and zeile["params"]["epic"] == "WMCNL-2976"
    assert zeile["params"]["kriterien"] == 2


async def test_zu_lange_karte_wird_nicht_angefragt():
    a = Aufbau()
    angebot = await a.f.anfrage(replace(STORY, beschreibung="x" * (jf.KARTE_MAX + 1)))
    assert angebot.karte is None and "zu lang" in angebot.grund
    assert a.gesendet == [] and a.memory.geloggt == [] and a.f.offen is False


async def test_karte_rechnet_in_utf16_einheiten():
    a = Aufbau()
    emoji = "\U0001F600" * (jf.KARTE_MAX // 2)  # je zwei UTF-16-Einheiten: zusammen über der Grenze
    angebot = await a.f.anfrage(replace(STORY, beschreibung=emoji))
    assert angebot.karte is None


async def test_hoechstens_fuenf_offene_karten():
    a = Aufbau()
    for _ in range(jf.MAX_OFFEN):
        assert (await a.f.anfrage(STORY)).karte is not None
    angebot = await a.f.anfrage(STORY)
    assert angebot.karte is None and "zu viele" in angebot.grund
    assert a.f.platz_frei() is not None


async def test_grenze_je_stunde_und_profil():
    zaehler = jf.StundenZaehler()
    a = Aufbau(zaehler=zaehler, max_je_stunde=3, max_offen=10)
    for _ in range(3):
        assert (await a.f.anfrage(STORY)).karte is not None
    assert "Stunde" in (await a.f.anfrage(STORY)).grund
    anderes = Aufbau(zaehler=zaehler, max_je_stunde=3, profil="00000000-0000-4000-8000-0000000000a2")
    assert (await anderes.f.anfrage(STORY)).karte is not None  # ein anderes Profil zählt für sich
    a.uhr.jetzt += 3601
    zaehler_uhr = Aufbau(zaehler=zaehler, max_je_stunde=3, max_offen=10)
    zaehler_uhr.uhr.jetzt = a.uhr.jetzt
    assert (await zaehler_uhr.f.anfrage(STORY)).karte is not None  # nach einer Stunde wieder frei


async def test_karte_nicht_gesendet_heisst_nichts_offen():
    a = Aufbau()

    async def kaputt(_n):
        raise ConnectionError("weg")

    a.f._senden = kaputt
    angebot = await a.f.anfrage(STORY)
    assert angebot.karte is None and a.f.offen is False
    await asyncio.gather(*list(a.f._hintergrund))  # die Ablehnung läuft im Hintergrund
    assert a.memory.status == ["rejected"]


# ---------- Klick ----------
async def test_ja_fuehrt_genau_die_gespeicherten_werte_aus():
    a = Aufbau()
    await a.f.anfrage(STORY)
    ausgang = await a.f.entscheiden({"job": "jira", "id": a.kennung(), "entscheidung": "ja", "titel": "Untergeschoben"})
    assert ausgang.ok and ausgang.schluessel == "WMCNL-123"
    assert a.ausgefuehrt == [STORY]  # Felder aus der Nachricht zählen nie
    assert a.memory.status == ["approved", "running"]
    assert a.memory.abschluss == [("done", {"schluessel": "WMCNL-123"})]
    ergebnis = [n for n in a.gesendet if n.get("type") == "jira_ergebnis"][0]
    assert ergebnis == {"type": "jira_ergebnis", "ok": True, "schluessel": "WMCNL-123",
                        "link": "https://firma.atlassian.net/browse/WMCNL-123", "text": "Angelegt als WMCNL-123."}
    assert "WMCNL-123" in a.gemeldet[0] and a.gemeldet[0].startswith("[Jira-Freigabe:")
    assert a.f.offen is False


async def test_zweiter_klick_bewirkt_nichts():
    a = Aufbau()
    await a.f.anfrage(STORY)
    kennung = a.kennung()
    await a.f.entscheiden({"id": kennung, "entscheidung": "ja"})
    assert await a.f.entscheiden({"id": kennung, "entscheidung": "ja"}) is None
    assert len(a.ausgefuehrt) == 1


async def test_gleichzeitige_klicks_fuehren_einmal_aus():
    a = Aufbau()
    await a.f.anfrage(STORY)
    kennung = a.kennung()
    await asyncio.gather(*(a.f.entscheiden({"id": kennung, "entscheidung": "ja"}) for _ in range(5)))
    assert len(a.ausgefuehrt) == 1


async def test_nein_legt_nichts_an():
    a = Aufbau()
    await a.f.anfrage(STORY)
    assert await a.f.entscheiden({"id": a.kennung(), "entscheidung": "nein"}) is None
    assert a.ausgefuehrt == [] and a.memory.status == ["rejected"]
    assert "abgelehnt" in a.gemeldet[0] and "nichts angelegt" in a.gemeldet[0]


async def test_abgelaufen_legt_nichts_an():
    a = Aufbau()
    await a.f.anfrage(STORY)
    a.uhr.jetzt += 301
    assert await a.f.entscheiden({"id": a.kennung(), "entscheidung": "ja"}) is None
    assert a.ausgefuehrt == [] and a.memory.status == ["rejected"]
    assert "abgelaufen" in a.gemeldet[0]


@pytest.mark.parametrize("data", [None, {}, {"id": 5}, {"id": "abc"}, {"id": "0" * 32, "entscheidung": "ja"},
                                  {"id": "A" * 32, "entscheidung": "ja"}])
async def test_unbekannte_kennung_bleibt_still(data):
    a = Aufbau()
    await a.f.anfrage(STORY)
    assert await a.f.entscheiden(data) is None
    assert a.ausgefuehrt == [] and a.gemeldet == [] and a.f.offen is True


async def test_veraenderter_antrag_wird_abgelehnt():
    a = Aufbau()
    await a.f.anfrage(STORY)
    kennung = a.kennung()
    antrag = a.f._offen[kennung]
    a.f._offen[kennung] = replace(antrag, story=replace(STORY, projekt="GEHEIM"))  # gleicher Hash, andere Werte
    assert await a.f.entscheiden({"id": kennung, "entscheidung": "ja"}) is None
    assert a.ausgefuehrt == [] and a.memory.status == ["rejected"]


async def test_fehler_beim_ausfuehren_wird_ein_fester_satz():
    async def kaputt(_story):
        raise RuntimeError("Token ATATT3x-geheim im Fehlertext")

    a = Aufbau(ausfuehren=kaputt)
    await a.f.anfrage(STORY)
    ausgang = await a.f.entscheiden({"id": a.kennung(), "entscheidung": "ja"})
    assert not ausgang.ok and "ATATT3x" not in ausgang.satz
    assert a.memory.abschluss == [("failed", {"code": "fehler"})]
    ergebnis = [n for n in a.gesendet if n.get("type") == "jira_ergebnis"][0]
    assert ergebnis["ok"] is False and "schluessel" not in ergebnis and "link" not in ergebnis


async def test_fehlgeschlagen_mit_code():
    a = Aufbau(ausgang=jf.Ausgang(False, "Jira hat die Anmeldung abgelehnt.", code="anmeldung"))
    await a.f.anfrage(STORY)
    await a.f.entscheiden({"id": a.kennung(), "entscheidung": "ja"})
    assert a.memory.abschluss == [("failed", {"code": "anmeldung"})]


async def test_schliessen_lehnt_offene_ab_und_klicks_wirken_nicht_mehr():
    a = Aufbau()
    await a.f.anfrage(STORY)
    kennung = a.kennung()
    await a.f.schliessen()
    assert a.memory.status == ["rejected"] and a.f.offen is False
    assert await a.f.entscheiden({"id": kennung, "entscheidung": "ja"}) is None
    assert (await a.f.anfrage(STORY)).karte is None
    assert a.ausgefuehrt == []
