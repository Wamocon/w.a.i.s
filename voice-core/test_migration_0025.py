"""Prüft Migration 0025 (persönliche Schwelle der Stimme) als Text: Regeln aus CLAUDE.md für Migrationen, nur die nötigen Rechte und der
Zusammenhang mit dem Kern (was das Einlernen speichert und das Gate annimmt, passt in die Prüfung der Datenbank). Die Wirkung in der
Datenbank prüft supabase/tests/0025_stimme_schwelle_test.sql gegen wamo_test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import stimme_gate
import stimme_modell
import stimme_speicher

WURZEL = Path(__file__).resolve().parent.parent
SQL = (WURZEL / "supabase" / "migrations" / "0025_stimme_schwelle.sql").read_text(encoding="utf-8")
DOWN = (WURZEL / "supabase" / "migrations" / "0025_stimme_schwelle.down.sql").read_text(encoding="utf-8")
TEST = (WURZEL / "supabase" / "tests" / "0025_stimme_schwelle_test.sql").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_spalte_ohne_vorgabe_wiederholbar_und_mit_bereich():
    code = _ohne_kommentare(SQL)
    assert "add column if not exists voice_threshold real;" in code
    assert "drop constraint if exists speakers_voice_threshold_chk" in code
    assert "check (voice_threshold is null or voice_threshold between 0.2 and 0.8)" in code
    assert "set local lock_timeout" in code
    assert "on conflict do nothing" in code and "'0025_stimme_schwelle'" in code
    assert "not null" not in code.split("comment on")[0]  # NULL heißt: Schwelle aus der Umgebung, keine Zeile muss nachgefüllt werden
    assert "default" not in code.split("comment on")[0]


def test_bereich_passt_zu_kern_und_einlernen():
    """Die Datenbank nimmt alles, was das Einlernen speichert (0,30 bis 0,50), und das Gate nimmt beim Laden genau ihren Bereich an."""
    assert (stimme_gate.PERSOENLICH_MIN, stimme_gate.PERSOENLICH_MAX) == (0.2, 0.8)
    assert stimme_gate.PERSOENLICH_MIN <= stimme_modell.SCHWELLE_MIN < stimme_modell.SCHWELLE_MAX <= stimme_gate.PERSOENLICH_MAX


def test_nur_der_kern_liest_und_schreibt_die_spalte():
    code = _ohne_kommentare(SQL)
    grants = sorted(" ".join(g.split()) for g in re.findall(r"^\s*grant\b[^;]*;", code, re.M | re.I))
    assert grants == [f"grant {recht} (voice_threshold) on __SCHEMA__.speakers to wamo_core;" for recht in ("insert", "select", "update")]
    revokes = [" ".join(r.split()) for r in re.findall(r"^\s*revoke\b[^;]*;", code, re.M | re.I)]
    assert revokes == ["revoke all (voice_threshold) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, "
                       "wamo_admin;"]
    assert not re.search(r"^\s*(drop\s+(table|column)|delete|truncate|create\s+policy)\b", code, re.I | re.M)


def test_selbsttest_prueft_jedes_recht_einzeln():
    code = _ohne_kommentare(SQL)
    assert "array['SELECT', 'INSERT', 'UPDATE']" in code
    assert "array['wamo_admin', 'anon', 'authenticated', 'service_role']" in code
    assert "policyname = 'core_all'" in code and "'DELETE'" in code
    assert "relrowsecurity" in code and "convalidated" in code and "wamo_core_s2" in code


def test_rueckweg_nimmt_nur_die_spalte_und_ist_in_prod_gesperrt():
    code = _ohne_kommentare(DOWN)
    assert "drop column if exists voice_threshold" in code
    assert "drop constraint if exists speakers_voice_threshold_chk" in code
    assert "alter table if exists __SCHEMA__.speakers" in code
    assert "wamo.allow_drop" in code and "'__SCHEMA__' = 'wamo_prod'" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0025_stimme_schwelle'" in code
    assert len(re.findall(r"drop column", code)) == 1  # Abdruck, Einwilligung und alles andere bleiben


def test_sql_test_rollt_zurueck_und_nie_in_prod():
    assert "begin;" in TEST and re.search(r"^rollback;", TEST, re.M) and "Test nie in wamo_prod" in TEST
    assert "0025 OK" in TEST
    for code in ("'23514'", "'42501'"):
        assert code in TEST
    for wert in ("0.19", "0.81", "'NaN'", "'Infinity'"):
        assert wert in TEST


def test_kern_schreibt_genau_diese_spalte():
    quelle = Path(stimme_speicher.__file__).read_text(encoding="utf-8")
    assert "voice_threshold = excluded.voice_threshold" in quelle
    assert "$6::real" in quelle
    assert "asyncpg.UndefinedColumnError" in quelle  # ohne 0025 läuft der Kern wie vorher


def test_migrations_lint_der_pruefstrecke_findet_nichts():
    """Dieselbe Prüfung wie der Job Migrationen in CI (scripts/wamo_migrationen_pruefen.py), hier auf genau diese drei Dateien."""
    pruefer = WURZEL / "infra" / "sokrates2" / "release" / "pruefer"
    sys.path.insert(0, str(pruefer))
    try:
        import migration_lint as ml
        from pruefer_scans import Datei
    finally:
        sys.path.remove(str(pruefer))
    pfade = ("supabase/migrations/0025_stimme_schwelle.sql", "supabase/migrations/0025_stimme_schwelle.down.sql")
    dateien = [Datei(p, (WURZEL / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(WURZEL).as_posix() for p in (WURZEL / "supabase" / "migrations").glob("*.sql"))
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_keine_gedankenstriche():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
