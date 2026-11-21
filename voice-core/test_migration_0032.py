"""Prüft Migration 0032 (Claude-Zugang des Testlabors) als Text: Regeln aus CLAUDE.md für Migrationen (RLS, Policy core_all für wamo_core, nur die
nötigen Grants, keine Rechte für anon, authenticated, service_role, wamo_admin und wamo_werkstatt, Index je Fremdschlüssel, drop vor create
policy, Platzhalter, Selbsttest), die Form der Tabelle, den Rückweg, die Verbindung zur Löschliste der Laborprofile (0018) und dass der SQL-Test
die Anweisungen des Kerns (labor_zugang.py) wörtlich enthält. Die Wirkung in der Datenbank prüft supabase/tests/0032_labor_zugang_test.sql gegen
wamo_test oder wamo_dev; sie läuft nicht in diesem Test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import labor_loeschliste as ll
import labor_zugang as lz

SUPABASE = Path(__file__).resolve().parent.parent / "supabase"
SQL = (SUPABASE / "migrations" / "0032_labor_zugang.sql").read_text(encoding="utf-8")
DOWN = (SUPABASE / "migrations" / "0032_labor_zugang.down.sql").read_text(encoding="utf-8")
TEST = (SUPABASE / "tests" / "0032_labor_zugang_test.sql").read_text(encoding="utf-8")
TEST_0018 = (SUPABASE / "tests" / "0018_labor_profile_test.sql").read_text(encoding="utf-8")
FREMDE = ("anon", "authenticated", "service_role", "public", "wamo_admin", "wamo_werkstatt")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _eine_zeile(text: str) -> str:
    return " ".join(text.split())


def _tabelle() -> str:
    treffer = re.search(r"create table if not exists __SCHEMA__\.labor_zugang \((.*?)\n\);", _ohne_kommentare(SQL), re.S)
    assert treffer
    return _eine_zeile(treffer.group(1))


def test_naechste_nummer_und_beide_dateien():
    nummern = sorted(int(p.name[:4]) for p in (SUPABASE / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql") if not p.name.endswith(".down.sql"))
    assert nummern.count(32) == 1 and all(n > 32 for n in nummern[nummern.index(32) + 1:])
    assert (SUPABASE / "migrations" / "0031_werkstatt.sql").is_file()


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
        assert not re.search(r"\b(fuer|ueber|Pruefung|Rueckweg|koennen|waehrend|aendern|Aenderung|loeschen|Aufraeumen|Zaehlen)\b",
                             " ".join(kommentare)), "Ersatzschreibweise für Umlaute im Kommentar"


def test_voraussetzung_lock_timeout_eine_transaktion_und_eintrag():
    code = _ohne_kommentare(SQL)
    assert "set local lock_timeout" in code
    assert "version = '0001_wamo_init'" in code and "0032 braucht 0001" in code
    assert not re.search(r"^\s*(begin|commit)\s*;", code, re.I | re.M)
    assert "insert into __SCHEMA__.schema_migrations (version) values ('0032_labor_zugang') on conflict do nothing" in code


def test_die_tabelle_hat_eine_zeile_und_speichert_nie_klartext():
    t = _tabelle()
    assert len(re.findall(r"create table\b", _ohne_kommentare(SQL), re.I)) == 1
    assert "id boolean primary key default true" in t and "check (id)" in t
    assert "claude_schluessel bytea not null" in t and "octet_length(claude_schluessel) between 40 and 1024" in t
    assert "claude_workspace text" in t and "'^wrkspc_[A-Za-z0-9]{6,60}$'" in t
    assert "endet_auf text not null" in t and "'^[A-Za-z0-9_-]{4}$'" in t
    assert "gesetzt_von uuid references __SCHEMA__.profiles(user_id) on delete set null" in t
    assert "gesetzt_am timestamptz not null default now()" in t and "geprueft_am timestamptz" in t
    # die Spalten, die es gibt: nie ein Klartext-Schlüssel, nie ein Token
    spalten = re.findall(r"^\s{2}(\w+)\s", "\n".join(z for z in SQL.splitlines() if not z.lstrip().startswith("--")).split(
        "create table if not exists __SCHEMA__.labor_zugang (")[1].split("\n);")[0], re.M)
    assert [s for s in spalten if s != "constraint"] == ["id", "claude_schluessel", "claude_workspace", "endet_auf", "gesetzt_von",
                                                          "gesetzt_am", "geprueft_am"]


def test_index_je_fremdschluessel_partiell_und_wiederholbar():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert "create index if not exists labor_zugang_von_idx on __SCHEMA__.labor_zugang (gesetzt_von) where gesetzt_von is not null" in code
    assert not re.search(r"create (unique )?index (?!if not exists)", code)


def test_rls_core_all_mit_drop_davor_und_keine_weitere_policy():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert "alter table __SCHEMA__.labor_zugang enable row level security" in code
    assert code.index("drop policy if exists core_all on __SCHEMA__.labor_zugang") < code.index(
        "create policy core_all on __SCHEMA__.labor_zugang for all to wamo_core using (true) with check (true)")
    assert len(re.findall(r"create policy", code, re.I)) == 1
    assert "disable row level security" not in code and "force row level security" not in code


def test_rechte_nur_wamo_core_nichts_fuer_fremde_und_nie_der_werkstatt_dienst():
    code = _ohne_kommentare(SQL)
    grants = [_eine_zeile(a) for a in re.split(r";\s*\n", code) if re.match(r"\s*grant\b", a, re.I)]
    assert grants == ["grant select, insert, update, delete on __SCHEMA__.labor_zugang to wamo_core"]
    for g in grants:
        assert not any(re.search(rf"\b{f}\b", g, re.I) for f in FREMDE), g
    revoke = [_eine_zeile(a) for a in re.split(r";\s*\n", code) if re.match(r"\s*revoke\b", a, re.I)]
    assert revoke == ["revoke all on __SCHEMA__.labor_zugang from public, anon, authenticated, service_role, wamo_admin, wamo_core"]
    # die Rolle wamo_werkstatt gibt es nur mit 0031: nur entziehen, wenn sie da ist, und nur dynamisch
    assert "if exists (select 1 from pg_roles where rolname = 'wamo_werkstatt') then" in _eine_zeile(code)
    assert "execute 'revoke all on __SCHEMA__.labor_zugang from wamo_werkstatt'" in _eine_zeile(code)
    assert code.index("revoke all on __SCHEMA__.labor_zugang") < code.index("grant select, insert, update, delete")


def test_selbsttest_prueft_rechte_rls_und_die_rolle_des_kerns():
    code = _eine_zeile(_ohne_kommentare(SQL))
    selbsttest = code[code.index("declare recht text;"):code.index("insert into __SCHEMA__.schema_migrations")]
    for muster in ("has_table_privilege", "has_any_column_privilege", "relrowsecurity", "pg_policies", "policyname = 'core_all'",
                   "wamo_core_s2", "errcode = '42501'", "'TRUNCATE'", "'REFERENCES'", "'TRIGGER'"):
        assert muster in selbsttest, muster
    for rolle in ("wamo_admin", "anon", "authenticated", "service_role", "wamo_werkstatt", "wamo_core"):
        assert f"'{rolle}'" in selbsttest, rolle


def test_rueckweg_gesperrt_in_prod_und_bei_folgemigrationen_und_wiederholbar():
    code = _ohne_kommentare(DOWN)
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "version > '0032_labor_zugang'" in code and "wamo.down_trotz_folgemigration" in code
    assert "drop table if exists __SCHEMA__.labor_zugang" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0032_labor_zugang'" in code
    assert "cascade" not in code.lower() and not re.search(r"\bdrop\s+role\b", code, re.I)


def test_sql_test_ist_eine_zurueckgerollte_transaktion_nie_in_prod_und_prueft_die_kernpunkte():
    code = _ohne_kommentare(TEST)
    assert code.index("begin;") < code.index("rollback;")
    assert "\\echo 0032 OK" in TEST and "Test nie in wamo_prod" in code
    for rolle in ("wamo_core", "wamo_admin", "wamo_werkstatt", "anon", "authenticated", "service_role"):
        assert f"set role {rolle}" in code, rolle
    for punkt in ("'23514'", "'23502'", "'23503'", "'23505'", "'42501'", "truncate __SCHEMA__.labor_zugang", "labor_zugang_setzen",
                  "labor_zugang_entfernen", "genau eine Zeile", "Zeile bleibt ohne Profil", "Protokoll nur mit endet_auf"):
        assert punkt in code, punkt


def test_der_sql_test_enthaelt_die_anweisungen_des_kerns_woertlich():
    """labor_zugang.py baut die drei Anweisungen aus Vorlagen; der SQL-Test führt sie mit eingesetzten Werten aus. Ändert sich eine,
    muss die andere mit (Fragmente, whitespace-unabhängig)."""
    test = _eine_zeile(_ohne_kommentare(TEST))
    for vorlage in (lz._SQL_SETZEN, lz._SQL_ENTFERNEN):
        text = _eine_zeile(vorlage.format(t="__SCHEMA__.labor_zugang", a="__SCHEMA__.actions", risk="__SCHEMA__.risk_class",
                                          status="__SCHEMA__.action_status")).removesuffix(" returning 1")  # der Kern fragt, ob etwas geschrieben wurde
        # nur die festen Teile: alles zwischen den Platzhaltern $1 bis $6
        for stueck in re.split(r"\$\d(?:::\w+)?", text):
            stueck = stueck.strip(" ,")
            if len(stueck) > 40:
                assert stueck in test, stueck
    lesen = _eine_zeile(lz._SQL_LESEN.format(t="__SCHEMA__.labor_zugang")).replace("$1::boolean", "true::boolean")
    assert lesen in test


def test_migrations_lint_der_pruefstrecke_findet_nichts():
    """Dieselbe Prüfung wie der Job Migrationen in CI (scripts/wamo_migrationen_pruefen.py), hier auf genau diese beiden Dateien."""
    pruefer = SUPABASE.parent / "infra" / "sokrates2" / "release" / "pruefer"
    sys.path.insert(0, str(pruefer))
    try:
        import migration_lint as ml
        from pruefer_scans import Datei
    finally:
        sys.path.remove(str(pruefer))
    wurzel = SUPABASE.parent
    pfade = ("supabase/migrations/0032_labor_zugang.sql", "supabase/migrations/0032_labor_zugang.down.sql")
    dateien = [Datei(p, (wurzel / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(wurzel).as_posix() for p in (SUPABASE / "migrations").glob("*.sql") if int(p.name[:4]) <= 32)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_die_tabelle_mit_profilverweis_steht_mit_grund_in_der_loeschliste_und_im_test_von_0018():
    """Eine Tabelle mit Verweis auf profiles(user_id) gehört in LOESCHLISTE oder mit Grund in AUSNAHMEN (test_labor_loeschen.py). Die Zeile
    gehört keinem Laborprofil, sie ist Konfiguration: AUSNAHMEN, und in beiden Ausnahmelisten des SQL-Tests von 0018."""
    assert "labor_zugang" in ll.AUSNAHMEN and ll.AUSNAHMEN["labor_zugang"].strip()
    assert "labor_zugang" not in {o.tabelle for o in ll.LOESCHLISTE}
    assert "gesetzt_von uuid references __SCHEMA__.profiles(user_id)" in _tabelle()
    assert TEST_0018.count("'labor_karten_versionen', 'werkstatt_karten', 'labor_zugang'];") == 2
