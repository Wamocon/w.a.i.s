"""Canvas-Reiter schließen und Bilder zeigen (Wunsch vom 18.11.2026): Werkzeug canvas_schliessen, typ bild in canvas_zeigen.

Schließen blendet nur aus: Das Element bleibt in der Datenbank und in der Historie der Oberfläche, die Sitzungsliste behält es (nach dem
Wiederöffnen lässt es sich weiter überarbeiten). Bilder kommen nur als https-Adresse; der Kern lädt sie nie (kein SSRF), die Oberfläche
zeigt sie als Verweis. Laborprofile bekommen weder das neue Werkzeug noch den typ bild.

Ausführen:  python -m pytest -q test_canvas_schliessen.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import asyncio
import types

import pytest

import canvas_sitzung as cs
import labor
import tools as T
from auth_gate import Identity

ADMIN = Identity("123e4567-e89b-12d3-a456-426614174000", "Erika", "admin", "du")
GEDANKENSTRICHE = (chr(0x2014), chr(0x2013))


class FakeLLM:
    def __init__(self):
        self.funktionen: dict = {}
        self.frames: list = []

    def register_function(self, name, fn, **kw):
        self.funktionen[name] = fn

    async def push_frame(self, frame):
        self.frames.append(frame)


class FakeMemory:
    def __init__(self):
        self.zeilen: list[tuple[str, str, dict]] = []

    async def save_canvas(self, type_: str, title: str, data: dict) -> str | None:
        self.zeilen.append((type_, title, dict(data)))
        return f"aaaaaaaa-0000-4000-8000-{len(self.zeilen):012d}"


def bauen(*, erlaubt=None, canvas: cs.CanvasSitzung | None = None, memory: FakeMemory | None = None):
    llm = FakeLLM()
    schema = T.register_tools(llm, memory=memory or FakeMemory(), identity=ADMIN, zugang=None, canvas=canvas, erlaubt=erlaubt)
    return llm, schema


async def aufrufen(llm: FakeLLM, name: str, **argumente) -> dict:
    ergebnisse: list[dict] = []

    async def rueck(r):
        ergebnisse.append(r)

    await llm.funktionen[name](types.SimpleNamespace(llm=llm, arguments=argumente, result_callback=rueck))
    return ergebnisse[-1]


# ---------- Sitzungsliste ----------
def test_schliessen_laesst_das_element_in_der_liste_und_vergisst_nur_den_offenen_reiter():
    s = cs.CanvasSitzung()
    s.neu("u1", "Plan")
    s.neu("u2", "Liste")
    s.geschlossen(s.finden("c2"))
    assert [e.kennung for e in s.elemente] == ["c1", "c2"]  # bleibt überarbeitbar, falls die Person es wieder öffnet
    assert "c1" in s.aktiv_melden("u1")  # die Oberfläche zeigt danach c1: das Modell erfährt es
    assert "c2" in s.aktiv_melden("u2")  # wieder geöffnet aus der Historie: das Modell erfährt auch das


def test_schliessen_eines_anderen_reiters_aendert_den_offenen_nicht():
    s = cs.CanvasSitzung()
    s.neu("u1", "Plan")
    s.neu("u2", "Liste")
    s.geschlossen(s.finden("c1"))
    assert s.aktiv_melden("u2") is None  # c2 war und bleibt offen


def test_alle_schliessen_vergisst_den_offenen_reiter():
    s = cs.CanvasSitzung()
    s.neu("u1", "Plan")
    s.geschlossen(None)
    assert "c1" in s.aktiv_melden("u1")


# ---------- Werkzeug canvas_schliessen ----------
def test_ohne_angabe_schliesst_die_oberflaeche_den_offenen_reiter():
    llm, _ = bauen()
    ergebnis = asyncio.run(aufrufen(llm, "canvas_schliessen"))
    assert ergebnis["geschlossen"] is True
    assert llm.frames[-1].data == {"type": "canvas_schliessen", "ziel": "offen"}
    assert "Historie" in ergebnis["hinweis"]


def test_mit_kennung_schliesst_genau_dieses_element_auch_mit_frueheren_kennungen_der_oberflaeche():
    s = cs.CanvasSitzung()
    llm, _ = bauen(canvas=s)

    async def ablauf():
        await aufrufen(llm, "canvas_zeigen", typ="dokument", titel="Plan", text="a")
        await aufrufen(llm, "canvas_zeigen", typ="dokument", titel="Plan", text="b", ersetzt="c1")
        await aufrufen(llm, "canvas_zeigen", typ="dokument", titel="Liste", text="c")
        return await aufrufen(llm, "canvas_schliessen", canvas_id=" C1 ")

    ergebnis = asyncio.run(ablauf())
    nachricht = llm.frames[-1].data
    assert ergebnis == {"geschlossen": True, "canvas_id": "c1", "hinweis": T.SCHLIESSEN_HINWEIS}
    assert nachricht["type"] == "canvas_schliessen" and nachricht["ziel"] == "ids"
    assert nachricht["ids"] == ["aaaaaaaa-0000-4000-8000-000000000002", "aaaaaaaa-0000-4000-8000-000000000001"]
    assert [e.kennung for e in s.elemente] == ["c1", "c2"]


def test_alle_schliesst_alle_reiter():
    llm, _ = bauen()
    ergebnis = asyncio.run(aufrufen(llm, "canvas_schliessen", alle=True))
    assert ergebnis["geschlossen"] is True and ergebnis["ziel"] == "alle"
    assert llm.frames[-1].data == {"type": "canvas_schliessen", "ziel": "alle"}


def test_eine_genannte_kennung_geht_vor_alle_und_eine_zahl_ist_eine_kennung():
    s = cs.CanvasSitzung()
    s.neu("u1", "Plan")
    s.neu("u2", "Liste")
    llm, _ = bauen(canvas=s)
    ergebnis = asyncio.run(aufrufen(llm, "canvas_schliessen", alle=True, canvas_id="c1"))
    assert ergebnis["canvas_id"] == "c1" and llm.frames[-1].data == {"type": "canvas_schliessen", "ziel": "ids", "ids": ["u1"]}
    ergebnis = asyncio.run(aufrufen(llm, "canvas_schliessen", canvas_id=2))
    assert ergebnis["canvas_id"] == "c2" and llm.frames[-1].data["ids"] == ["u2"]


@pytest.mark.parametrize("fremd", ["c7", "aaaaaaaa-0000-4000-8000-000000000099", 3, ["c1"], {"c1": 1}])
def test_unbekannte_kennung_schliesst_nichts_und_sagt_wie_es_geht(fremd):
    llm, _ = bauen()
    ergebnis = asyncio.run(aufrufen(llm, "canvas_schliessen", canvas_id=fremd))
    assert ergebnis["geschlossen"] is False
    assert "alle" in ergebnis["fehler"] and "offenen" in ergebnis["fehler"]
    assert llm.frames == []


@pytest.mark.parametrize(("wert", "ziel"), [(True, "alle"), ("ja", "alle"), (" TRUE ", "alle"), (1, "alle"), ("1", "alle"),
                                           (None, "offen"), (False, "offen"), ("nein", "offen"), (0, "offen"), (2, "offen"),
                                           ([True], "offen")])
def test_alle_auch_als_text_oder_zahl_wie_hausmodelle_es_schicken(wert, ziel):
    llm, _ = bauen()
    asyncio.run(aufrufen(llm, "canvas_schliessen", alle=wert))
    assert llm.frames[-1].data["ziel"] == ziel


def test_schema_canvas_schliessen_ist_kurz_optional_und_ohne_gedankenstriche():
    s = T.SCHLIESSEN_SCHEMA
    assert s.name == "canvas_schliessen" and s.required == []
    assert set(s.properties) == {"canvas_id", "alle"}
    assert s.properties["alle"]["type"] == "boolean"
    assert "Historie" in s.description and len(s.description) < 500
    for text in (s.description, *(p["description"] for p in s.properties.values())):
        for zeichen in GEDANKENSTRICHE:
            assert zeichen not in text


def test_volle_sitzung_hat_beide_werkzeuge_im_schema():
    llm, schema = bauen()
    namen = [f.name for f in schema.standard_tools]
    assert "canvas_schliessen" in namen and "canvas_zeigen" in namen
    assert "canvas_schliessen" in llm.funktionen


# ---------- Labor: nichts Neues ----------
def test_labor_bekommt_canvas_schliessen_nicht_und_canvas_zeigen_ohne_bild():
    llm, schema = bauen(erlaubt=labor.WERKZEUGE_BASIS)
    assert "canvas_schliessen" not in llm.funktionen
    assert "canvas_schliessen" not in labor.WERKZEUGE_BASIS
    zeigen = next(f for f in schema.standard_tools if f.name == "canvas_zeigen")
    assert zeigen is T.CANVAS_SCHEMA  # dasselbe Schema wie vorher, ohne neue Wahl
    assert "bild" not in zeigen.properties["typ"]["enum"] and "url" not in zeigen.properties


def test_labor_lehnt_typ_bild_ab_auch_wenn_das_modell_es_versucht():
    mem = FakeMemory()
    llm, _ = bauen(erlaubt=labor.WERKZEUGE_BASIS, memory=mem)
    ergebnis = asyncio.run(aufrufen(llm, "canvas_zeigen", typ="bild", titel="Logo", url="https://example.com/a.png"))
    assert ergebnis["angezeigt"] is False and llm.frames == [] and mem.zeilen == []


# ---------- typ bild ----------
def test_bild_mit_https_adresse_kommt_als_verweis_ohne_speichern_und_mit_hinweis_fuers_modell():
    mem = FakeMemory()
    s = cs.CanvasSitzung()
    llm, _ = bauen(memory=mem, canvas=s)
    ergebnis = asyncio.run(aufrufen(llm, "canvas_zeigen", typ="bild", titel=" Rathaus ", url=" https://example.com/bilder/rathaus.jpg?x=1 ",
                                    beschreibung="Das Rathaus von außen"))
    item = llm.frames[-1].data["item"]
    assert item["kind"] == "bild" and item["title"] == "Rathaus"
    assert item["url"] == "https://example.com/bilder/rathaus.jpg?x=1"
    assert item["alt"] == "Das Rathaus von außen"
    assert item["id"].startswith("lokal-")  # nie in canvas_items (dort gibt es keine Art für Bilder)
    assert mem.zeilen == []
    assert ergebnis["angezeigt"] is True and ergebnis["canvas_id"] == "c1"
    assert "Verweis" in ergebnis["hinweis"]
    assert s.finden("c1").ui_id == item["id"]  # ersetzbar und schließbar wie jedes Element


@pytest.mark.parametrize("url", [
    "http://example.com/a.png",
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "https://nutzer:geheim@example.com/a.png",
    "https://127.0.0.1/a.png",
    "https://192.168.178.136:55443/a.png",
    "https://[::1]/a.png",
    "https://localhost/a.png",
    "https://intern/a.png",
    "https://drucker.local/a.png",
    "https://example.com/a b.png",
    "https://example.com/a\n.png",
    "https://example.com/" + "a" * 2100,
    "",
    None,
    7,
    "//example.com/a.png",
    "https:///a.png",
    # Kurzformen von IP-Adressen, die ein Browser auflöst (127.0.0.1, 192.168.0.1, 10.0.0.1)
    "https://127.1/a.png",
    "https://0x7f.0.0.1/a.png",
    "https://0177.0.0.1/a.png",
    "https://10.1/a.png",
    "https://192.168.1/a.png",
    "https://2130706433/a.png",
    "https://server.corp/a.png",
    "https://nas.localdomain/a.png",
])
def test_bild_nur_mit_sauberer_oeffentlicher_https_adresse(url):
    llm, _ = bauen()
    ergebnis = asyncio.run(aufrufen(llm, "canvas_zeigen", typ="bild", titel="x", url=url))
    assert ergebnis["angezeigt"] is False and "https" in ergebnis["fehler"]
    assert llm.frames == []


def test_bild_beschreibung_wird_gekuerzt_und_bereinigt():
    llm, _ = bauen()
    asyncio.run(aufrufen(llm, "canvas_zeigen", typ="bild", titel="x", url="https://example.com/a.png",
                         beschreibung="Zeile\x00eins\n" + "y" * 500))
    alt = llm.frames[-1].data["item"]["alt"]
    assert "\x00" not in alt and "\n" not in alt and len(alt) <= T.BILD_ALT_MAX


def test_schema_mit_bild_nennt_url_und_bleibt_kurz():
    s = T.CANVAS_SCHEMA_BILD
    assert "bild" in s.properties["typ"]["enum"]
    assert s.properties["url"]["type"] == "string" and "url" not in s.required
    assert "https" in s.properties["url"]["description"]
    assert len(s.description) < 900
    for text in (s.description, s.properties["url"]["description"], s.properties["beschreibung"]["description"]):
        for zeichen in GEDANKENSTRICHE:
            assert zeichen not in text
    # alles Übrige wie im Schema ohne Bilder (ersetzt, Tabelle, Code)
    assert set(T.CANVAS_SCHEMA.properties) < set(s.properties)


@pytest.mark.parametrize("url", ["https://upload.wikimedia.org/a.png", "https://bilder.example.de:8443/x.webp?groesse=2",
                                 "https://xn--bcher-kva.example/a.png", "https://a-b.example.museum/c.gif"])
def test_bild_oeffentliche_namen_gehen(url):
    assert T.bild_url(url) == url
