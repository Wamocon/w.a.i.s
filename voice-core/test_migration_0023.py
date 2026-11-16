"""Prüft Migration 0023 (Hören und Stimme selbst wählen) als Text: Regeln aus CLAUDE.md für Migrationen, nur die nötigen Rechte und
der Zusammenhang mit dem Kern. Die Wirkung in der Datenbank prüft supabase/tests/0023_stimme_selbst_test.sql gegen wamo_test."""

from __future__ import annotations

import re
from pathlib import Path

import modellzugang

WURZEL = Path(__file__).resolve().parent.parent / "supabase"
SQL = (WURZEL / "migrations" / "0023_stimme_selbst.sql").read_text(encoding="utf-8")
DOWN = (WURZEL / "migrations" / "0023_stimme_selbst.down.sql").read_text(encoding="utf-8")
TEST = (WURZEL / "tests" / "0023_stimme_selbst_test.sql").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_nur_einfuegen_und_aendern_von_stt_und_tts_fuer_den_kern():
    code = _ohne_kommentare(SQL)
    grants = re.findall(r"^\s*grant\b[^;]*;", code, re.M | re.I)
    assert sorted(" ".join(g.split()) for g in grants) == [
        "grant insert (stt, tts) on __SCHEMA__.model_access to wamo_core;",
        "grant update (stt, tts) on __SCHEMA__.model_access to wamo_core;",
    ]
    # die Migration nimmt und löscht nichts (keine Anweisung dieser Art am Zeilenanfang)
    assert not re.search(r"^\s*(revoke|drop|alter|delete|truncate)\b", code, re.I | re.M)
    assert "on conflict do nothing" in code and "'0023_stimme_selbst'" in code


def test_selbsttest_prueft_jedes_recht_einzeln():
    code = _ohne_kommentare(SQL)
    assert "foreach spalte in array array['stt', 'tts']" in code
    assert "array['SELECT', 'INSERT', 'UPDATE']" in code
    assert "array['anon', 'authenticated', 'service_role']" in code
    assert "array['nur_haus', 'claude_modell']" in code
    assert "policyname = 'core_all'" in code and "'user_id', recht" in code
    assert "relrowsecurity" in code


def test_rueckweg_nimmt_genau_diese_rechte_und_ist_in_prod_gesperrt():
    code = _ohne_kommentare(DOWN)
    assert "revoke insert (stt, tts), update (stt, tts) on __SCHEMA__.model_access from wamo_core;" in code
    assert "wamo.allow_drop" in code and "'__SCHEMA__' = 'wamo_prod'" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0023_stimme_selbst'" in code


def test_sql_test_rollt_zurueck_und_nie_in_prod():
    assert "begin;" in TEST and re.search(r"^rollback;", TEST, re.M) and "Test nie in wamo_prod" in TEST
    assert "0023 OK" in TEST
    for code in ("'23514'", "'23502'", "'42501'"):
        assert code in TEST


def test_kern_schreibt_genau_stt_und_tts():
    quelle = Path(modellzugang.__file__).read_text(encoding="utf-8")
    assert "(user_id, stt, tts) values ($1::uuid, $2, $3)" in quelle
    assert "do update set stt = excluded.stt, tts = excluded.tts" in quelle


def test_keine_gedankenstriche():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
