"""Prüft Migration 0026 (Entwicklungsaufträge für später) als Text: Regeln aus CLAUDE.md für Migrationen (RLS, Policy core_all für
wamo_core, nur die nötigen Grants mit begründetem delete, keine Rechte für anon, authenticated, service_role und wamo_admin, Index für den
Fremdschlüssel, drop vor create policy und trigger, Platzhalter), dass die Grenzen zu auftrag_entwuerfe.py passen und dass der SQL-Test die
Anweisungen des Kerns wörtlich enthält. Die Wirkung in der Datenbank prüft supabase/tests/0026_auftrag_entwuerfe_test.sql gegen wamo_test
oder wamo_dev; sie läuft nicht in diesem Test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import auftrag_entwuerfe as ae

SUPABASE = Path(__file__).resolve().parent.parent / "supabase"
SQL = (SUPABASE / "migrations" / "0026_auftrag_entwuerfe.sql").read_text(encoding="utf-8")
DOWN = (SUPABASE / "migrations" / "0026_auftrag_entwuerfe.down.sql").read_text(encoding="utf-8")
TEST = (SUPABASE / "tests" / "0026_auftrag_entwuerfe_test.sql").read_text(encoding="utf-8")
FREMDE = ("anon", "authenticated", "service_role", "public", "wamo_admin")
SPALTEN = ("id", "user_id", "projekt", "art", "repo", "auftrag", "abnahme", "max_runden", "zeitlimit_min", "erstellt_at")
EINFUEGBAR = {"user_id", "projekt", "art", "repo", "auftrag", "abnahme", "max_runden", "zeitlimit_min"}
TABELLE = "__SCHEMA__.auftrag_entwuerfe"


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _anweisungen(text: str, wort: str) -> list[str]:
    return [" ".join(a.split()) for a in re.split(r";\s*\n", _ohne_kommentare(text)) if re.match(rf"\s*{wort}\b", a, re.I)]


def _eine_zeile(text: str) -> str:
    return " ".join(text.split())


def test_naechste_nummer_und_beide_dateien():
    nummern = sorted(int(p.name[:4]) for p in (SUPABASE / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
                     if not p.name.endswith(".down.sql"))
    assert nummern.count(26) == 1 and nummern[-1] >= 26  # spätere Nummern (ab 0027) dürfen folgen
    assert (SUPABASE / "migrations" / "0025_stimme_schwelle.sql").is_file()


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_keine_gedankenstriche_und_nur_echte_umlaute_in_den_kommentaren():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
        kommentare = [z for z in text.splitlines() if z.lstrip().startswith("--")]
        for zeile in kommentare:
            assert " - " not in zeile, zeile
        assert not re.search(r"\b(fuer|ueber|Pruefung|Rueckweg|koennen|waehrend|aendern|Aenderung|loeschen|Entwuerfe)\b",
                             " ".join(kommentare)), "Ersatzschreibweise für Umlaute im Kommentar"


def test_tabelle_idempotent_mit_den_vereinbarten_spalten():
    koerper = re.search(r"create table if not exists __SCHEMA__\.auftrag_entwuerfe \((.*?)\n\);", SQL, re.S)
    assert koerper
    for spalte in SPALTEN:
        assert re.search(rf"^\s+{spalte}\s", koerper.group(1), re.M), spalte
    assert re.search(r"id\s+uuid primary key default gen_random_uuid\(\)", SQL)
    assert re.search(r"erstellt_at\s+timestamptz not null default now\(\)", SQL)
    for wort in ("token", "schluessel", "zugang", "wert", "secret"):  # nie ein Zugangswert
        assert not re.search(rf"^\s+\w*{wort}\w*\s", koerper.group(1), re.M | re.I), wort


def test_fremdschluessel_zeigt_auf_profiles_nicht_auf_auth_users_mit_index():
    code = _ohne_kommentare(SQL)
    assert re.search(r"user_id\s+uuid not null references __SCHEMA__\.profiles\(user_id\) on delete cascade", code)
    assert "auth.users" not in code
    assert re.search(r"create index if not exists auftrag_entwuerfe_user_idx on __SCHEMA__\.auftrag_entwuerfe \(user_id, erstellt_at desc\)",
                     code)
    kopf = SQL.split("set local lock_timeout", 1)[0]
    assert "profiles" in kopf and "0001" in kopf and "0025" in kopf


def test_grenzen_der_datenbank_passen_zum_kern():
    code = _ohne_kommentare(SQL)
    assert f"projekt ~ '{ae.PROJEKT_RE.pattern}'" in code
    assert f"art ~ '^{ae.ART_RE.pattern}$'" in code
    assert f"repo ~ '^{ae.REPO_RE.pattern}$'" in code and "length(repo) <= 140" in code
    assert f"length(auftrag) between 1 and {ae.AUFTRAG_ZEICHEN}" in code
    assert f"jsonb_array_length(abnahme) <= {ae.KRITERIEN_MAX}" in code
    assert f"max_runden between 1 and {ae.RUNDEN_MAX}" in code
    assert f"zeitlimit_min between 1 and {ae.ZEITLIMIT_MAX_MIN}" in code
    groesse = int(re.search(r"pg_column_size\(abnahme\) <= (\d+)", code).group(1))
    assert ae.KRITERIEN_MAX * ae.KRITERIUM_ZEICHEN * 4 + 200 < groesse  # fünf Kriterien zu 300 Zeichen zu 4 Byte passen
    assert f">= {ae.MAX_JE_PERSON} then" in code  # Trigger der Grenze
    assert f"interval '{ae.AUFBEWAHRUNG_TAGE} days'" in code
    kopf = "\n".join(z for z in SQL.splitlines() if z.startswith("--"))
    assert f"{ae.AUFBEWAHRUNG_TAGE} Tage" in kopf and f"{ae.MAX_JE_PERSON} Entwürfe je Person" in kopf


def test_trigger_der_grenze_wiederholbar_ohne_definer_mit_sperre_je_person():
    code = _ohne_kommentare(SQL)
    assert "create or replace function __SCHEMA__.auftrag_entwuerfe_grenze() returns trigger" in code
    assert "security definer" not in code.lower()
    assert "set search_path = ''" in code
    assert "pg_advisory_xact_lock" in code and "new.user_id" in code
    assert "errcode = '23514'" in code
    drop = code.index("drop trigger if exists auftrag_entwuerfe_grenze on __SCHEMA__.auftrag_entwuerfe")
    anlegen = code.index("create trigger auftrag_entwuerfe_grenze before insert on __SCHEMA__.auftrag_entwuerfe")
    assert drop < anlegen
    revoke = [a for a in _anweisungen(code, "revoke") if "function" in a]
    assert len(revoke) == 1 and "wamo_core" in revoke[0] and "public" in revoke[0]


def test_rls_policy_core_all_mit_drop_davor():
    code = _ohne_kommentare(SQL)
    assert "alter table __SCHEMA__.auftrag_entwuerfe enable row level security" in code
    drop = code.index("drop policy if exists core_all on __SCHEMA__.auftrag_entwuerfe")
    anlegen = code.index("create policy core_all on __SCHEMA__.auftrag_entwuerfe for all to wamo_core using (true) with check (true)")
    assert drop < anlegen
    assert len(re.findall(r"create policy", code, re.I)) == 1


def test_rechte_nur_der_kern_lesen_loeschen_und_einfuegen_in_gezielte_spalten():
    code = _ohne_kommentare(SQL)
    grants = _anweisungen(code, "grant")
    assert len(grants) == 2
    for g in grants:
        assert g.endswith("to wamo_core"), g
        assert not any(re.search(rf"\b{f}\b", g, re.I) for f in FREMDE), g
        assert not re.search(r"\bupdate\b|\ball\b|\btruncate\b|\breferences\b|\btrigger\b", g, re.I), g
    assert "grant select, delete on __SCHEMA__.auftrag_entwuerfe to wamo_core" in grants
    einfuegen = [g for g in grants if g.startswith("grant insert (")]
    assert len(einfuegen) == 1
    assert set(re.findall(r"\b[a-z_]+\b", einfuegen[0].split("(", 1)[1].split(")", 1)[0])) == EINFUEGBAR
    revoke = " ".join(a for a in _anweisungen(code, "revoke") if "function" not in a)
    assert "revoke all on __SCHEMA__.auftrag_entwuerfe from" in revoke
    for rolle in (*FREMDE, "wamo_core"):
        assert re.search(rf"\b{rolle}\b", revoke), rolle
    assert code.index("revoke all on __SCHEMA__.auftrag_entwuerfe") < code.index("grant select, delete on")
    kopf = "\n".join(z for z in SQL.splitlines() if z.startswith("--"))
    assert "delete ist begründet" in kopf


def test_voraussetzung_selbsttest_und_eintrag():
    code = _ohne_kommentare(SQL)
    assert "set local lock_timeout" in code
    assert "version = '0001_wamo_init'" in code and "0026 braucht 0001" in code
    assert not re.search(r"^\s*(begin|commit)\s*;", code, re.I | re.M)
    for rolle in ("wamo_admin", "anon", "authenticated", "service_role"):
        assert f"'{rolle}'" in code, rolle
    assert "relrowsecurity" in code and "policyname = 'core_all'" in code and "tgname = 'auftrag_entwuerfe_grenze'" in code
    assert "insert into __SCHEMA__.schema_migrations (version) values ('0026_auftrag_entwuerfe') on conflict do nothing" in code


def test_rueckweg_gesperrt_in_prod_und_bei_folgemigrationen_und_wiederholbar():
    code = _ohne_kommentare(DOWN)
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "version > '0026_auftrag_entwuerfe'" in code and "wamo.down_trotz_folgemigration" in code
    assert "drop table if exists __SCHEMA__.auftrag_entwuerfe" in code
    assert "drop function if exists __SCHEMA__.auftrag_entwuerfe_grenze()" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0026_auftrag_entwuerfe'" in code
    assert "cascade" not in code.lower()


def test_sql_test_ist_eine_zurueckgerollte_transaktion_nie_in_prod_und_prueft_die_kernpunkte():
    code = _ohne_kommentare(TEST)
    assert code.index("begin;") < code.index("rollback;")
    assert "\\echo 0026 OK" in TEST
    assert "Test nie in wamo_prod" in code and "set role wamo_core" in code
    for rolle in ("anon", "authenticated", "service_role", "wamo_admin"):
        assert f"set role {rolle}" in code, rolle
    for punkt in ("truncate __SCHEMA__.auftrag_entwuerfe", "update __SCHEMA__.auftrag_entwuerfe set", "generate_series(1, 48)",
                  "interval '100 days'", "delete from auth.users", "delete from __SCHEMA__.profiles", "relrowsecurity", "'23514'",
                  "'23503'", "'42501'", "repeat(chr(128512), 4000)", "8::bigint"):
        assert punkt in code, punkt
    assert "zweimal" in TEST.split("\\set ON_ERROR_STOP", 1)[0]


def _teile(sql: str) -> list[str]:
    """Die Teile einer Anweisung des Kerns zwischen den Platzhaltern ($1::uuid, $2 ...), je ohne Rand."""
    return [t.strip() for t in re.split(r"\$\d+(?:::[a-z]+)*", _eine_zeile(sql)) if t.strip()]


def test_sql_test_enthaelt_die_anweisungen_des_kerns_woertlich():
    """Der SQL-Test prüft, was der Kern wirklich schickt: ändert sich auftrag_entwuerfe.py, muss der SQL-Test mit."""
    sql_test = _eine_zeile(_ohne_kommentare(TEST))
    for anweisung in (ae._EINFUEGEN, ae._LISTE, ae._HOLEN, ae._LOESCHEN, ae._AUFRAEUMEN):
        for teil in _teile(anweisung.format(t=TABELLE)):
            assert teil in sql_test, teil


def test_migrations_lint_der_pruefstrecke_findet_nichts():
    """Dieselbe Prüfung wie der Job Migrationen in CI (scripts/wamo_migrationen_pruefen.py), hier auf genau diese beiden Dateien, mit dem
    Baum dieses Zweigs (spätere Migrationen gab es hier noch nicht)."""
    pruefer = SUPABASE.parent / "infra" / "sokrates2" / "release" / "pruefer"
    sys.path.insert(0, str(pruefer))
    try:
        import migration_lint as ml
        from pruefer_scans import Datei
    finally:
        sys.path.remove(str(pruefer))
    wurzel = SUPABASE.parent
    pfade = ("supabase/migrations/0026_auftrag_entwuerfe.sql", "supabase/migrations/0026_auftrag_entwuerfe.down.sql")
    dateien = [Datei(p, (wurzel / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(wurzel).as_posix() for p in (SUPABASE / "migrations").glob("*.sql") if int(p.name[:4]) <= 26)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_anweisungen_des_kerns_nennen_immer_das_profil():
    for anweisung in (ae._EINFUEGEN, ae._LISTE, ae._HOLEN, ae._LOESCHEN):
        assert "user_id = $" in anweisung or anweisung.startswith("insert into {t} (user_id,"), anweisung
    assert "user_id" not in ae._AUFRAEUMEN and "erstellt_at < now()" in ae._AUFRAEUMEN
    for anweisung in (ae._LISTE, ae._HOLEN, ae._EINFUEGEN):
        assert f"erstellt_at >= now() - interval '{ae.AUFBEWAHRUNG_TAGE} days'" in anweisung
