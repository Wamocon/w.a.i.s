"""Jira-Stories in der Sitzung (bot.py): Die Werkzeuge aus jira_werkzeuge.py hängen nur in Büro-Sitzungen eines Admins, nie im Labor,
laufen durch das Gate der Stimmprüfung, der Klick auf die Karte (job "jira") und der Knopf am Canvas (jira_story) gehen an die Sitzung,
offene Karten halten den Ja-Wächter zurück und werden beim Ende abgelehnt. Statisch gelesen wie test_bot_geraete.py."""

from __future__ import annotations

import ast
from pathlib import Path

import jira_werkzeuge as jw

QUELLE = Path(__file__).with_name("bot.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)


def test_bot_importiert_das_modul():
    assert any(isinstance(k, ast.Import) and any(a.name == "jira_werkzeuge" for a in k.names) for k in ast.walk(BAUM))


def test_aufbau_nur_ohne_laborsitzung_mit_buero_und_zug():
    zeile = next(z for z in QUELLE.splitlines() if "jira_story = jira_werkzeuge.sitzung_bauen(" in z)
    assert "im_buero=im_buero" in zeile and "ist_fremd=lambda: turn.tainted" in zeile
    assert zeile.rstrip().endswith("if not labor_sitzung else None")
    assert "jira_story.anbinden(senden=send, melden=melde_llm)" in QUELLE


def test_werkzeuge_laufen_durch_das_gate_der_stimmpruefung():
    assert "schemas_absichern(jira_story.schemas(), stimme.gate)" in QUELLE


def test_die_endpruefung_der_laborsitzung_steht_danach():
    assert QUELLE.index("jira_story = jira_werkzeuge.sitzung_bauen(") < QUELLE.index("labor_sitzung.werkzeuge_pruefen(")


def test_klick_auf_karte_und_knopf_gehen_an_die_sitzung():
    assert 'data.get("job") == jira_werkzeuge.JOB' in QUELLE
    assert "await jira_story.entscheiden(data)" in QUELLE
    assert "msg.type == jira_werkzeuge.NACHRICHT_KLICK" in QUELLE
    assert "jira_story.klick_starten(data)" in QUELLE
    for zweig in ('data.get("job") == jira_werkzeuge.JOB', "msg.type == jira_werkzeuge.NACHRICHT_KLICK"):
        start = QUELLE.index(zweig)
        assert "jira_story is None" in QUELLE[start: start + 300]
        assert start < QUELLE.index("await dev.on_client_message(msg.type, data)")
    assert jw.JOB == "jira" and jw.NACHRICHT_KLICK == "jira_story"


def test_ja_waechter_und_ende():
    assert QUELLE.count("jira_story: jira_werkzeuge.JiraStory | None = None") == 1
    assert QUELLE.index("jira_story: jira_werkzeuge.JiraStory | None = None") < QUELLE.index("def freigabe_offen")
    assert "jira_story is not None and jira_story.offen" in QUELLE
    assert "await asyncio.wait_for(jira_story.schliessen(), CLEANUP_DB_TIMEOUT_SECS)" in QUELLE


def test_oberflaeche_erfaehrt_die_projekte_beim_start():
    start = QUELLE.index('@task.rtvi.event_handler("on_client_ready")')
    assert "await jira_story.client_bereit()" in QUELLE[start: start + 900]
