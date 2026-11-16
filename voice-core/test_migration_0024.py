"""Prüft Migration 0024 (Modellwahl und Stimme im Haus selbst wählen) als Text: Regeln aus CLAUDE.md für Migrationen, nur die nötigen
Rechte und der Zusammenhang mit dem Kern (jeder Wert, den der Kern je anbietet, passt in die Prüfung der Datenbank). Die Wirkung in der
Datenbank prüft supabase/tests/0024_modellwahl_selbst_test.sql gegen wamo_test."""

from __future__ import annotations

import re
from pathlib import Path

import modellwahl as mw
import modellzugang
import sprache_anbieter as sa

WURZEL = Path(__file__).resolve().parent.parent / "supabase"
SQL = (WURZEL / "migrations" / "0024_modellwahl_selbst.sql").read_text(encoding="utf-8")
DOWN = (WURZEL / "migrations" / "0024_modellwahl_selbst.down.sql").read_text(encoding="utf-8")
TEST = (WURZEL / "tests" / "0024_modellwahl_selbst_test.sql").read_text(encoding="utf-8")
SPALTEN = ("modell_gespraech", "modell_bilder", "modell_hintergrund", "tts_stimme")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _regel(spalte: str) -> re.Pattern[str]:
    treffer = re.search(rf"check \({spalte} is null or {spalte} ~ '([^']+)'\)", SQL)
    assert treffer, spalte
    return re.compile(treffer.group(1))


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_spalten_ohne_vorgabe_wiederholbar():
    code = _ohne_kommentare(SQL)
    for spalte in SPALTEN:
        assert f"add column if not exists {spalte} text," in code or f"add column if not exists {spalte} text;" in code
    for name in re.findall(r"add constraint (\w+)", code):
        assert f"drop constraint if exists {name}" in code
    assert "set local lock_timeout" in code
    assert "on conflict do nothing" in code and "'0024_modellwahl_selbst'" in code
    assert "not null" not in code.split("comment on")[0]  # NULL heißt automatisch, keine Zeile muss nachgefüllt werden


def test_nur_der_kern_liest_und_schreibt_genau_diese_spalten():
    code = _ohne_kommentare(SQL)
    grants = sorted(" ".join(g.split()) for g in re.findall(r"^\s*grant\b[^;]*;", code, re.M | re.I))
    liste = ", ".join(SPALTEN)
    assert grants == [f"grant {recht} ({liste}) on __SCHEMA__.model_access to wamo_core;" for recht in ("insert", "select", "update")]
    revokes = [" ".join(r.split()) for r in re.findall(r"^\s*revoke\b[^;]*;", code, re.M | re.I)]
    assert revokes == [f"revoke all ({liste}) on __SCHEMA__.model_access from public, anon, authenticated, service_role, wamo_core, "
                       "wamo_admin;"]
    assert not re.search(r"^\s*(drop\s+(table|column)|delete|truncate)\b", code, re.I | re.M)


def test_selbsttest_prueft_jedes_recht_einzeln_und_die_pruefungen():
    code = _ohne_kommentare(SQL)
    assert "array['modell_gespraech', 'modell_bilder', 'modell_hintergrund', 'tts_stimme']" in code
    assert "array['SELECT', 'INSERT', 'UPDATE']" in code
    assert "array['wamo_admin', 'anon', 'authenticated', 'service_role']" in code
    assert "array['nur_haus', 'claude_modell']" in code
    assert "policyname = 'core_all'" in code and "'user_id', recht" in code
    assert "relrowsecurity" in code and "convalidated" in code and "wamo_core_s2" in code


def test_jeder_wert_des_kerns_passt_in_die_pruefung_der_datenbank():
    """Was der Kern anbietet, muss die Datenbank speichern können (sonst käme beim Setzen nur ein Fehler)."""
    for bereich, spalte in mw.SPALTEN.items():
        regel = _regel(spalte)
        werte = {o.id for o in mw.optionen(bereich, claude=True)} | set(mw.CLAUDE_MODELLE)
        assert werte
        for wert in werte:
            assert regel.fullmatch(wert), (spalte, wert)
        for falsch in ("", "Gemma4", "gemma4 31b", "bedrock/claude", "a" * 64, "-x"):
            assert not regel.fullmatch(falsch), (spalte, falsch)
    stimme = _regel("tts_stimme")
    for wert in sa.HAUS_STIMMEN_IDS:
        assert stimme.fullmatch(wert), wert
    assert not stimme.fullmatch("standard ") and not stimme.fullmatch("Ryan")


def test_rueckweg_nimmt_genau_diese_spalten_und_ist_in_prod_gesperrt():
    code = _ohne_kommentare(DOWN)
    for spalte in SPALTEN:
        assert f"drop column if exists {spalte}" in code
    assert "alter table if exists __SCHEMA__.model_access" in code
    assert "wamo.allow_drop" in code and "'__SCHEMA__' = 'wamo_prod'" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0024_modellwahl_selbst'" in code
    for spalte in ("stt", "tts", "nur_haus", "modell_modus", "claude_modell"):
        assert not re.search(rf"drop column if exists {spalte}\b", code), spalte


def test_sql_test_rollt_zurueck_und_nie_in_prod():
    assert "begin;" in TEST and re.search(r"^rollback;", TEST, re.M) and "Test nie in wamo_prod" in TEST
    assert "0024 OK" in TEST and "Zwang bleibt" in TEST
    for code in ("'23514'", "'42501'"):
        assert code in TEST


def test_kern_schreibt_nur_spalten_aus_der_festen_liste():
    quelle = Path(modellzugang.__file__).read_text(encoding="utf-8")
    assert "if spalte not in (*mw.SPALTEN.values(), \"tts_stimme\"):" in quelle
    assert "(user_id, {spalte}) values ($1::uuid, $2)" in quelle
    assert set(mw.SPALTEN.values()) | {"tts_stimme"} == set(SPALTEN)


def test_keine_gedankenstriche():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
