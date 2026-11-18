"""Prüft Migration 0028 (Abdruck des Sprechermodells im Schattenbetrieb) als Text: Regeln aus CLAUDE.md für Migrationen, nur die nötigen
Rechte, Trigger und Funktion wiederholbar, und der Zusammenhang mit dem Kern (was stimme_schatten.py und stimme_speicher.py schreiben, passt
in die Regeln der Datenbank). Die Wirkung in der Datenbank prüft supabase/tests/0028_stimme_schatten_test.sql gegen wamo_test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import stimme_einwilligung
import stimme_schatten
import stimme_speicher

WURZEL = Path(__file__).resolve().parent.parent
SQL = (WURZEL / "supabase" / "migrations" / "0028_stimme_schatten.sql").read_text(encoding="utf-8")
DOWN = (WURZEL / "supabase" / "migrations" / "0028_stimme_schatten.down.sql").read_text(encoding="utf-8")
TEST = (WURZEL / "supabase" / "tests" / "0028_stimme_schatten_test.sql").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def test_nummer_frei_und_beide_dateien():
    nummern = [int(p.name[:4]) for p in (WURZEL / "supabase" / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
               if not p.name.endswith(".down.sql")]
    assert nummern.count(28) == 1
    assert (WURZEL / "supabase" / "migrations" / "0025_stimme_schwelle.sql").is_file()  # 0028 baut auf voice_threshold auf


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_spalten_ohne_vorgabe_wiederholbar_und_mit_regeln():
    code = _ohne_kommentare(SQL)
    assert "add column if not exists voiceprint_shadow extensions.vector," in code
    assert "add column if not exists shadow_model text;" in code
    vor_kommentar = code.split("comment on")[0]
    assert "not null" not in vor_kommentar.replace("is not null", "")  # NULL heißt: kein Schatten, keine Zeile muss nachgefüllt werden
    assert "default" not in vor_kommentar
    for regel in ("speakers_shadow_pair_chk", "speakers_shadow_voiceprint_chk", "speakers_shadow_consent_chk", "speakers_shadow_dims_chk",
                  "speakers_shadow_model_chk"):
        assert f"drop constraint if exists {regel}" in code and f"add constraint {regel}" in code
    assert "check ((voiceprint_shadow is null) = (shadow_model is null))" in code
    assert "check (voiceprint_shadow is null or voiceprint is not null)" in code
    assert "extensions.vector_dims(voiceprint_shadow) between 64 and 1024" in code
    assert "set local lock_timeout" in code
    assert "on conflict do nothing" in code and "'0028_stimme_schatten'" in code


def test_schatten_nur_mit_der_fassung_stimme_2():
    """Die Datenbank erzwingt, was stimme_einwilligung.schatten_erlaubt im Kern prüft (Entscheidung vom 18.11.2026)."""
    version = stimme_einwilligung.EINWILLIGUNG_VERSION_SCHATTEN
    assert f"check (voiceprint_shadow is null or consent_text_version = '{version}')" in _ohne_kommentare(SQL)
    assert "drop constraint if exists speakers_shadow_consent_chk" in _ohne_kommentare(DOWN)
    assert "set consent_text_version = 'stimme-1'" in TEST  # zurück auf stimme-1 scheitert, solange ein Schatten da ist


def test_regeln_passen_zum_kern():
    assert 64 <= stimme_schatten.SCHATTEN_DIM <= 1024
    muster = re.search(r"shadow_model ~ '(\^[^']+\$)'", SQL).group(1)
    assert re.fullmatch(muster, stimme_schatten.SCHATTEN_MODELL)
    quelle = Path(stimme_speicher.__file__).read_text(encoding="utf-8")
    assert "set voiceprint_shadow = $2::text::extensions.vector, shadow_model = $3" in quelle
    assert "voiceprint_shadow::text as schatten, shadow_model as modell" in quelle
    assert "asyncpg.UndefinedColumnError" in quelle  # ohne 0028 läuft der Kern wie vorher


def test_trigger_verwirft_den_alten_schatten_und_ist_wiederholbar():
    code = _ohne_kommentare(SQL)
    assert "create or replace function __SCHEMA__.speakers_schatten_verwerfen() returns trigger" in code
    assert "set search_path = ''" in code
    assert "security definer" not in code
    assert "drop trigger if exists speakers_schatten_verwerfen on __SCHEMA__.speakers;" in code
    assert re.search(r"create trigger speakers_schatten_verwerfen\s+before update of voiceprint on __SCHEMA__\.speakers\s+"
                     r"for each row execute function __SCHEMA__\.speakers_schatten_verwerfen\(\);", code)
    assert "new.voiceprint::text is distinct from old.voiceprint::text" in code
    assert "new.voiceprint_shadow::text is not distinct from old.voiceprint_shadow::text" in code


def test_nur_der_kern_liest_und_schreibt_die_spalten():
    code = _ohne_kommentare(SQL)
    grants = sorted(" ".join(g.split()) for g in re.findall(r"^\s*grant\b[^;]*;", code, re.M | re.I))
    assert grants == [f"grant {recht} (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers to wamo_core;" for recht in ("select", "update")]
    revokes = sorted(" ".join(r.split()) for r in re.findall(r"^\s*revoke\b[^;]*;", code, re.M | re.I))
    assert revokes == [
        "revoke all (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, "
        "wamo_admin;",
        "revoke all on function __SCHEMA__.speakers_schatten_verwerfen() from public, anon, authenticated, service_role, wamo_admin;",
    ]
    assert not re.search(r"^\s*(drop\s+(table|column)|delete|truncate|create\s+policy|create\s+table)\b", code, re.I | re.M)


def test_selbsttest_prueft_jedes_recht_einzeln():
    code = _ohne_kommentare(SQL)
    assert "array['voiceprint_shadow', 'shadow_model']" in code
    assert "array['SELECT', 'INSERT', 'UPDATE']" in code
    assert "array['wamo_admin', 'anon', 'authenticated', 'service_role']" in code
    assert "policyname = 'core_all'" in code and "'DELETE'" in code
    assert "relrowsecurity" in code and "convalidated" in code and "wamo_core_s2" in code and "pg_trigger" in code


def test_rueckweg_nimmt_nur_den_schatten_und_ist_in_prod_gesperrt():
    code = _ohne_kommentare(DOWN)
    for teil in ("drop column if exists voiceprint_shadow", "drop column if exists shadow_model",
                 "drop trigger if exists speakers_schatten_verwerfen on __SCHEMA__.speakers",
                 "drop function if exists __SCHEMA__.speakers_schatten_verwerfen()", "alter table if exists __SCHEMA__.speakers"):
        assert teil in code, teil
    assert "wamo.allow_drop" in code and "'__SCHEMA__' = 'wamo_prod'" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0028_stimme_schatten'" in code
    assert len(re.findall(r"drop column", code)) == 2  # Abdruck, Schwelle, Einwilligung und alles andere bleiben


def test_sql_test_rollt_zurueck_und_nie_in_prod():
    assert "begin;" in TEST and re.search(r"^rollback;", TEST, re.M) and "Test nie in wamo_prod" in TEST
    assert "0028 OK" in TEST
    for code in ("'23514'", "'42501'"):
        assert code in TEST
    assert "alter Schatten verworfen" in TEST  # der Trigger
    assert "set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.0625)::text::extensions.vector" in TEST  # wie der Kern


def test_migrations_lint_der_pruefstrecke_findet_nichts():
    """Dieselbe Prüfung wie der Job Migrationen in CI (scripts/wamo_migrationen_pruefen.py), hier auf genau diese Dateien."""
    pruefer = WURZEL / "infra" / "sokrates2" / "release" / "pruefer"
    sys.path.insert(0, str(pruefer))
    try:
        import migration_lint as ml
        from pruefer_scans import Datei
    finally:
        sys.path.remove(str(pruefer))
    pfade = ("supabase/migrations/0028_stimme_schatten.sql", "supabase/migrations/0028_stimme_schatten.down.sql")
    dateien = [Datei(p, (WURZEL / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(WURZEL).as_posix() for p in (WURZEL / "supabase" / "migrations").glob("*.sql") if int(p.name[:4]) <= 28)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_keine_gedankenstriche_und_echte_umlaute():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
        kommentare = [z for z in text.splitlines() if z.lstrip().startswith("--")]
        for zeile in kommentare:
            assert " - " not in zeile, zeile
        assert not re.search(r"\b(fuer|ueber|Pruefung|Rueckweg|koennen|waehrend|aendern|loeschen|Abdruecke)\b", " ".join(kommentare))
