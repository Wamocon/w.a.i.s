"""Prüft Migration 0029 (ein Stimmabdruck je Mikrofon) als Text: Regeln aus CLAUDE.md für Migrationen, nur die nötigen Rechte, Trigger und
Funktion wiederholbar, Rückweg ohne Rest, und der Zusammenhang mit dem Kern (was stimme_mikrofon.py, stimme_einwilligung.py und
stimme_speicher.py schreiben, passt in die Regeln der Datenbank). Die Wirkung in der Datenbank prüft supabase/tests/0029_stimme_mikrofone_test.sql
gegen wamo_test."""

from __future__ import annotations

import re
from pathlib import Path

import stimme_einwilligung
import stimme_mikrofon
import stimme_speicher

WURZEL = Path(__file__).resolve().parent.parent
MIGRATIONEN = WURZEL / "supabase" / "migrations"
SQL = (MIGRATIONEN / "0029_stimme_mikrofone.sql").read_text(encoding="utf-8")
DOWN = (MIGRATIONEN / "0029_stimme_mikrofone.down.sql").read_text(encoding="utf-8")
TEST = (WURZEL / "supabase" / "tests" / "0029_stimme_mikrofone_test.sql").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _eine_zeile(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_nummer_frei_hoechste_und_beide_dateien():
    nummern = [int(p.name[:4]) for p in MIGRATIONEN.glob("[0-9][0-9][0-9][0-9]_*.sql") if not p.name.endswith(".down.sql")]
    assert nummern.count(29) == 1 and max(nummern) == 29
    assert (MIGRATIONEN / "0028_stimme_schatten.sql").is_file()  # 0029 ändert die Regel des Schattens aus 0028


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_spalten_mit_vorgabe_fuer_den_bestand_und_regeln():
    """Jede vorhandene Zeile wird zum unbekannten Mikrofon (kein Datenverlust), neue Spalten wiederholbar, Regeln mit drop davor."""
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert f"add column if not exists mikrofon text not null default '{stimme_mikrofon.UNBEKANNT}'" in code
    assert "add column if not exists mikrofon_name text" in code
    for regel in ("speakers_mikrofon_chk", "speakers_mikrofon_name_chk", "speakers_shadow_consent_chk"):
        assert f"drop constraint if exists {regel}" in code and f"add constraint {regel}" in code
    assert f"char_length(mikrofon_name) between 1 and {stimme_mikrofon.MAX_NAME}" in code
    assert "mikrofon_name !~ '[[:cntrl:]]'" in code
    assert "set local lock_timeout" in code
    assert "on conflict do nothing" in code and "'0029_stimme_mikrofone'" in code


def test_regeln_passen_zum_kern():
    muster = re.search(r"mikrofon ~ '(\^[^']+\$)'", SQL).group(1)
    assert muster == stimme_mikrofon.KENNUNG_RE.pattern
    assert re.fullmatch(muster, stimme_mikrofon.mikrofon_aus("Headset (Jabra)").kennung)
    assert re.fullmatch(muster, stimme_mikrofon.UNBEKANNT)
    assert f">= {stimme_mikrofon.MAX_ABDRUECKE} then" in _ohne_kommentare(SQL)
    versionen = (stimme_einwilligung.EINWILLIGUNG_VERSION_SCHATTEN, stimme_einwilligung.EINWILLIGUNG_VERSION_MIKROFONE)
    assert f"check (voiceprint_shadow is null or consent_text_version in ('{versionen[0]}', '{versionen[1]}'))" in _ohne_kommentare(SQL)
    quelle = Path(stimme_speicher.__file__).read_text(encoding="utf-8")
    assert "on conflict (user_id, mikrofon) where is_owner do update set" in quelle
    assert "asyncpg.UndefinedColumnError" in quelle  # ohne 0029 läuft der Kern mit einem Abdruck wie vorher


def test_eindeutig_je_person_und_mikrofon_statt_je_person():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert "create unique index if not exists speakers_owner_mikrofon_idx on __SCHEMA__.speakers (user_id, mikrofon) where is_owner" in code
    assert "drop index if exists __SCHEMA__.speakers_one_owner_idx" in code
    assert code.index("speakers_owner_mikrofon_idx on") < code.index("drop index if exists __SCHEMA__.speakers_one_owner_idx")


def test_grenze_als_trigger_wiederholbar_mit_sperre_je_person():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert "create or replace function __SCHEMA__.speakers_mikrofon_grenze() returns trigger" in code
    assert "set search_path = ''" in code
    assert "security definer" not in code
    assert "pg_catalog.pg_advisory_xact_lock(" in code  # zwei gleichzeitige Einlernvorgänge derselben Person zählen nacheinander
    assert "s.mikrofon <> new.mikrofon" in code and "s.id <> new.id" in code  # ein Upsert auf ein vorhandenes Mikrofon zählt nicht doppelt
    assert "using errcode = '23514'" in code
    assert "drop trigger if exists speakers_mikrofon_grenze on __SCHEMA__.speakers;" in code
    assert re.search(r"create trigger speakers_mikrofon_grenze before insert or update of is_owner, user_id, mikrofon on __SCHEMA__\.speakers "
                     r"for each row execute function __SCHEMA__\.speakers_mikrofon_grenze\(\);", code)
    assert "revoke all on function __SCHEMA__.speakers_mikrofon_grenze() from public" in code


def test_nur_die_noetigen_rechte_und_selbsttest():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert ("revoke all (mikrofon, mikrofon_name) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, "
            "wamo_admin;") in code
    assert "grant select (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;" in code
    assert "grant insert (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;" in code
    assert "grant update (mikrofon_name) on __SCHEMA__.speakers to wamo_core;" in code
    assert "grant update (mikrofon)" not in code and "grant delete" not in code
    assert "has_column_privilege" in code and "errcode = '42501'" in code
    assert "pg_policies" in code and "relrowsecurity" in code
    assert "create table" not in code and "create policy" not in code  # keine neue Tabelle: die Löschliste der Labore bleibt, wie sie ist


def test_rueckweg_behaelt_je_person_den_neuesten_und_stellt_0028_wieder_her():
    code = _eine_zeile(_ohne_kommentare(DOWN))
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "row_number() over (partition by user_id order by enrolled_at desc, id desc)" in code
    assert code.index("delete from __SCHEMA__.speakers") < code.index("create unique index if not exists speakers_one_owner_idx")
    assert "set voiceprint_shadow = null, shadow_model = null" in code and "consent_text_version = 'stimme-3'" in code
    assert "add constraint speakers_shadow_consent_chk check (voiceprint_shadow is null or consent_text_version = 'stimme-2')" in code
    for weg in ("drop trigger if exists speakers_mikrofon_grenze", "drop function if exists __SCHEMA__.speakers_mikrofon_grenze()",
                "drop index if exists __SCHEMA__.speakers_owner_mikrofon_idx", "drop column if exists mikrofon,",
                "drop column if exists mikrofon_name", "delete from __SCHEMA__.schema_migrations where version = '0029_stimme_mikrofone'"):
        assert weg in code, weg


def test_sql_test_deckt_grenze_regeln_rechte_und_bestand_ab():
    assert "begin;" in TEST and re.search(r"^rollback;", TEST, re.M) and "Test nie in wamo_prod" in TEST
    assert "0029 OK" in TEST
    for code in ("'23514'", "'23505'", "'42501'"):
        assert code in TEST
    for teil in ("Bestand als unbekanntes Mikrofon", "viertes Mikrofon abgelehnt", "Upsert auf ein vorhandenes Mikrofon",
                 "Schatten mit stimme-3", "andere Person unberührt", "alle gelöscht", "on conflict (user_id, mikrofon) where is_owner"):
        assert teil in TEST, teil
    assert "0.8::real" not in TEST and "0.2::real" not in TEST  # real 0.8 liegt als Gleitkommazahl über 0,8 (Befund 18.11.2026)


def test_alte_sql_tests_brauchen_den_alten_index_nicht_mehr():
    """0025 und 0028 schrieben mit on conflict (user_id) where is_owner; das gibt es seit 0029 nicht mehr, ihre Tests laufen auch danach."""
    for name in ("0025_stimme_schwelle_test.sql", "0028_stimme_schatten_test.sql"):
        text = (WURZEL / "supabase" / "tests" / name).read_text(encoding="utf-8")
        assert "on conflict (user_id) where is_owner" not in _ohne_kommentare(text), name


def test_keine_gedankenstriche_in_den_kommentaren():
    for text in (SQL, DOWN, TEST):
        kommentare = " ".join(z.split("--", 1)[1] for z in text.splitlines() if "--" in z)
        assert "–" not in kommentare and "—" not in kommentare and " - " not in kommentare
