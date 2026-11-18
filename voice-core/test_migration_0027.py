"""Prüft Migration 0027 (persönliche GitHub-Zugänge, Plan C, C.3) als Text: Regeln aus CLAUDE.md für Migrationen (RLS, Policy core_all für
wamo_core, nur die nötigen Grants mit begründetem delete, keine Rechte für anon, authenticated, service_role, wamo_release und wamo_anker,
Spaltenrechte für wamo_admin ohne Chiffrat, partieller Index für den optionalen Fremdschlüssel, drop vor create policy und trigger,
Platzhalter), dass die Grenzen und die Liste der erlaubbaren Rechte zu github_zugang.py passen und dass der SQL-Test die Anweisungen des
Kerns wörtlich enthält. Die Wirkung in der Datenbank prüft supabase/tests/0027_github_zugang_test.sql gegen wamo_test oder wamo_dev."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import entwicklung_betrieb as eb
import github_zugang as gz
import labor_loeschliste as ll
from schluessel import _KENNUNG_LAENGE, _NONCE_LAENGE, KOPF

SUPABASE = Path(__file__).resolve().parent.parent / "supabase"
SQL = (SUPABASE / "migrations" / "0027_github_zugang.sql").read_text(encoding="utf-8")
DOWN = (SUPABASE / "migrations" / "0027_github_zugang.down.sql").read_text(encoding="utf-8")
TEST = (SUPABASE / "tests" / "0027_github_zugang_test.sql").read_text(encoding="utf-8")
FREMDE = ("anon", "authenticated", "service_role", "public")
TABELLEN = {"g": "__SCHEMA__.github_zugang", "r": "__SCHEMA__.github_rechte", "p": "__SCHEMA__.profiles"}


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _anweisungen(text: str, wort: str) -> list[str]:
    return [" ".join(a.split()) for a in re.split(r";\s*\n", _ohne_kommentare(text)) if re.match(rf"\s*{wort}\b", a, re.I)]


def _eine_zeile(text: str) -> str:
    return " ".join(text.split())


def test_naechste_nummer_und_beide_dateien():
    nummern = sorted(int(p.name[:4]) for p in (SUPABASE / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
                     if not p.name.endswith(".down.sql"))
    assert 27 in nummern and nummern.count(27) == 1 and 26 in nummern
    assert (SUPABASE / "migrations" / "0027_github_zugang.down.sql").is_file()


def test_schema_platzhalter_und_keine_festen_schemas():
    for text in (SQL, DOWN, TEST):
        code = _ohne_kommentare(text)
        assert "__SCHEMA__" in code
        assert not re.search(r"\bwamo_(dev|test|prod)\.", code)


def test_keine_gedankenstriche_und_echte_umlaute_in_den_kommentaren():
    for text in (SQL, DOWN, TEST):
        assert chr(0x2013) not in text and chr(0x2014) not in text
        kommentare = [z for z in text.splitlines() if z.lstrip().startswith("--")]
        for zeile in kommentare:
            assert " - " not in zeile, zeile
        assert not re.search(r"\b(fuer|ueber|Pruefung|Rueckweg|koennen|waehrend|aendern|Aenderung|loeschen|geloescht)\b",
                             " ".join(kommentare)), "Ersatzschreibweise für Umlaute im Kommentar"


def test_tabellen_mit_den_vereinbarten_spalten_und_fremdschluesseln():
    code = _ohne_kommentare(SQL)
    zugang = re.search(r"create table if not exists __SCHEMA__\.github_zugang \((.*?)\n\);", code, re.S).group(1)
    for spalte in ("user_id", "art", "token", "token_ende", "login", "konto_id", "scopes", "ablauf", "geprueft_at", "angelegt_at"):
        assert re.search(rf"^\s+{spalte}\s", zugang, re.M), spalte
    assert re.search(r"user_id\s+uuid primary key references __SCHEMA__\.profiles\(user_id\) on delete cascade", zugang)
    assert re.search(r"ablauf\s+timestamptz not null", zugang) and re.search(r"token\s+bytea not null", zugang)
    rechte = re.search(r"create table if not exists __SCHEMA__\.github_rechte \((.*?)\n\);", code, re.S).group(1)
    assert re.search(r"user_id\s+uuid primary key references __SCHEMA__\.profiles\(user_id\) on delete cascade", rechte)
    assert re.search(r"geaendert_von\s+uuid references __SCHEMA__\.profiles\(user_id\) on delete set null", rechte)
    assert re.search(r"scopes_ausnahmen\s+text\[\] not null default", rechte)
    assert "auth.users" not in code
    assert ("create index if not exists github_rechte_geaendert_von_idx on __SCHEMA__.github_rechte (geaendert_von) "
            "where geaendert_von is not null") in _eine_zeile(code)
    kopf = SQL.split("set local lock_timeout", 1)[0]
    assert "0001" in kopf and "0018" in kopf and "0026 muss dafür nicht angewendet sein" in kopf


def test_grenzen_der_datenbank_passen_zum_kern():
    code = _ohne_kommentare(SQL)
    assert "art in ('fein', 'klassisch')" in code and set(gz.ARTEN) == {"fein", "klassisch"}
    assert f"login ~ '^{gz.LOGIN_RE.pattern[:11]}({gz.LOGIN_RE.pattern[11:]})$'" in code
    assert f"cardinality(scopes) <= {gz.MAX_SCOPES}" in code and f"cardinality(scopes_ausnahmen) <= {gz.MAX_SCOPES}" in code
    assert gz.MAX_SCOPES == eb.SCOPES_MAX
    scope = gz.SCOPE_RE.pattern
    assert f"'^({scope}( {scope})*)?$'" in code
    assert "token_ende ~ '^[A-Za-z0-9_]{4}$'" in code
    # das Chiffrat des längsten Tokens (github_pat_ plus 82 Zeichen) passt, das kürzeste (ghp_ plus 36) liegt über der Untergrenze
    rahmen = len(KOPF) + _KENNUNG_LAENGE + _NONCE_LAENGE + 16
    unten, oben = map(int, re.search(r"octet_length\(token\) between (\d+) and (\d+)", code).groups())
    assert unten <= rahmen + 40 and rahmen + 93 <= oben


def test_liste_der_erlaubbaren_rechte_ist_die_des_kerns():
    code = _ohne_kommentare(SQL)
    liste = re.search(r"scopes_ausnahmen <@ array\[(.*?)\]::text\[\]", code, re.S).group(1)
    assert re.findall(r"'([^']+)'", liste) == list(eb.SCOPES_AUSNAHMEN) == list(gz.SCOPES_AUSNAHMEN)
    nie = re.search(r"not \(scopes_ausnahmen && array\[(.*?)\]::text\[\]\)", code, re.S).group(1)
    assert re.findall(r"'([^']+)'", nie) == list(eb.SCOPES_NIE) == list(gz.SCOPES_NIE)
    assert all(gz.SCOPE_RE.fullmatch(s) for s in (*eb.SCOPES_UNBEDENKLICH, *eb.SCOPES_AUSNAHMEN, *eb.SCOPES_NIE))
    # der SQL-Test legt einmal alle erlaubbaren Rechte an
    alle = re.search(r"values \('00000000-0000-4000-8000-0000000027a2', array\[\n(.*?)\], '00000000", TEST, re.S).group(1)
    assert re.findall(r"'([^']+)'", alle) == list(eb.SCOPES_AUSNAHMEN)
    for scope in eb.SCOPES_NIE:  # jeder nie erlaubte Scope einmal als Ausnahme abgewiesen
        assert f"array['{scope}'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514'" in TEST, scope


def test_trigger_wiederholbar_ohne_definer_mit_drop_davor():
    code = _ohne_kommentare(SQL)
    assert "security definer" not in code.lower()
    assert code.count("set search_path = ''") == 2
    for name in ("github_zugang_guard", "github_rechte_guard"):
        tabelle = name.removesuffix("_guard")
        assert f"create or replace function __SCHEMA__.{name}() returns trigger" in code
        drop = code.index(f"drop trigger if exists {name} on __SCHEMA__.{tabelle}")
        anlegen = code.index(f"create trigger {name} before insert or update on __SCHEMA__.{tabelle}")
        assert drop < anlegen
    assert code.count("p.labor_art is null") >= 2 and "a.rolle = 'admin' and a.aktiv and a.labor_art is null" in code
    for spalte in ("angelegt_at", "geprueft_at", "geaendert_at"):
        assert f"new.{spalte} := pg_catalog.now()" in code, spalte
    revoke = [a for a in _anweisungen(code, "revoke") if "function" in a]
    assert len(revoke) == 2 and all("wamo_core" in a and "public" in a and "wamo_admin" in a for a in revoke)


def test_rls_und_policies_mit_drop_davor():
    code = _ohne_kommentare(SQL)
    for tabelle in ("github_zugang", "github_rechte"):
        assert f"alter table __SCHEMA__.{tabelle} enable row level security" in code
        drop = code.index(f"drop policy if exists core_all on __SCHEMA__.{tabelle}")
        anlegen = code.index(f"create policy core_all on __SCHEMA__.{tabelle} for all to wamo_core using (true) with check (true)")
        assert drop < anlegen
    assert code.index("drop policy if exists admin_lesen on __SCHEMA__.github_zugang") < code.index(
        "create policy admin_lesen on __SCHEMA__.github_zugang for select to wamo_admin using (true)")
    assert len(re.findall(r"create policy", code, re.I)) == 3


def test_rechte_geringst_moeglich():
    code = _ohne_kommentare(SQL)
    grants = _anweisungen(code, "grant")
    assert set(grants) == {
        "grant select, delete on __SCHEMA__.github_zugang to wamo_core",
        "grant insert (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) on __SCHEMA__.github_zugang to wamo_core",
        "grant update (art, token, token_ende, login, konto_id, scopes, ablauf) on __SCHEMA__.github_zugang to wamo_core",
        "grant select (user_id, art, login, ablauf, geprueft_at) on __SCHEMA__.github_zugang to wamo_admin",
        "grant select on __SCHEMA__.github_rechte to wamo_core",
        "grant insert (user_id, scopes_ausnahmen, geaendert_von) on __SCHEMA__.github_rechte to wamo_core",
        "grant update (scopes_ausnahmen, geaendert_von) on __SCHEMA__.github_rechte to wamo_core",
    }
    revoke = " ".join(a for a in _anweisungen(code, "revoke") if "function" not in a)
    assert "revoke all on __SCHEMA__.github_zugang, __SCHEMA__.github_rechte from" in revoke
    for rolle in (*FREMDE, "wamo_admin", "wamo_core"):
        assert re.search(rf"\b{rolle}\b", revoke), rolle
    assert "from wamo_release" in code and "from wamo_anker" in code
    assert code.index("revoke all on __SCHEMA__.github_zugang, __SCHEMA__.github_rechte") < code.index("grant select, delete on")
    kopf = "\n".join(z for z in SQL.splitlines() if z.startswith("--"))
    assert "delete ist begründet" in kopf and "kein delete" in kopf


def test_voraussetzung_selbsttest_und_eintrag():
    code = _ohne_kommentare(SQL)
    assert "set local lock_timeout" in code
    assert "version = '0001_wamo_init'" in code and "version = '0018_labor_profile'" in code
    assert not re.search(r"^\s*(begin|commit)\s*;", code, re.I | re.M)
    for rolle in ("anon", "authenticated", "service_role", "wamo_release", "wamo_anker", "wamo_core_s2"):
        assert f"'{rolle}'" in code, rolle
    assert "relrowsecurity" in code and "policyname = 'core_all'" in code and "tgname = tabelle || '_guard'" in code
    assert "insert into __SCHEMA__.schema_migrations (version) values ('0027_github_zugang') on conflict do nothing" in code


def test_rueckweg_gesperrt_in_prod_und_bei_folgemigrationen_und_wiederholbar():
    code = _ohne_kommentare(DOWN)
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "version > '0027_github_zugang'" in code and "wamo.down_trotz_folgemigration" in code
    for anweisung in ("drop table if exists __SCHEMA__.github_rechte", "drop table if exists __SCHEMA__.github_zugang",
                      "drop function if exists __SCHEMA__.github_rechte_guard()", "drop function if exists __SCHEMA__.github_zugang_guard()",
                      "delete from __SCHEMA__.schema_migrations where version = '0027_github_zugang'"):
        assert anweisung in code, anweisung
        assert anweisung in _ohne_kommentare(TEST), f"der SQL-Test prüft den Rückweg nicht wörtlich: {anweisung}"
    assert "cascade" not in code.lower()


def test_sql_test_ist_eine_zurueckgerollte_transaktion_nie_in_prod_und_prueft_die_kernpunkte():
    code = _ohne_kommentare(TEST)
    assert code.index("begin;") < code.rindex("rollback;")
    assert "\\echo 0027 OK" in TEST
    assert "Test nie in wamo_prod" in code and "savepoint rueckweg" in code and "rollback to savepoint rueckweg" in code
    for rolle in ("wamo_core", "wamo_admin", "anon", "authenticated", "service_role"):
        assert f"set role {rolle}" in code, rolle
    for punkt in ("select token from __SCHEMA__.github_zugang", "'schaufenster'", "'23514'", "'42501'", "'23502'", "'delete_repo'",
                  "'site_admin'", "'admin:enterprise'", "delete from __SCHEMA__.profiles", "null::uuid"):
        assert punkt in code, punkt
    assert "zweimal" in TEST.split("\\set ON_ERROR_STOP", 1)[0]


def _teile(sql: str) -> list[str]:
    """Die Teile einer Anweisung des Kerns zwischen den Platzhaltern ($1::uuid, $7::text[] ...), je ohne Rand."""
    return [t.strip() for t in re.split(r"\$\d+(?:::[a-z]+(?:\[\])?)*", _eine_zeile(sql)) if t.strip()]


def test_sql_test_enthaelt_die_anweisungen_des_kerns_woertlich():
    sql_test = _eine_zeile(_ohne_kommentare(TEST))
    for vorlage in (gz._ZEILE, gz._TOKEN, gz._SPEICHERN, gz._GEPRUEFT, gz._LOESCHEN, gz._RECHTE, gz._RECHTE_SETZEN, gz._ZIEL,
                    gz._RECHTE_LISTE):
        for teil in _teile(vorlage.format(**TABELLEN)):
            assert teil in sql_test, teil


def test_spalten_des_kerns_passen_zu_den_rechten():
    """Was der Kern einfügt und ändert, darf wamo_core; mehr nicht."""
    einfuegen = re.search(r"\((.*?)\) values", gz._SPEICHERN).group(1).replace(" ", "").split(",")
    assert einfuegen == ["user_id", "art", "token", "token_ende", "login", "konto_id", "scopes", "ablauf"]
    gesetzt = set(re.findall(r"(\w+) = excluded\.\w+", gz._SPEICHERN)) | set(re.findall(r"(\w+) = \$\d", gz._GEPRUEFT)) - {"user_id"}
    assert gesetzt == {"art", "token", "token_ende", "login", "konto_id", "scopes", "ablauf"}
    assert re.search(r"\((.*?)\) values", gz._RECHTE_SETZEN).group(1) == "user_id, scopes_ausnahmen, geaendert_von"


def test_labor_loeschliste_kennt_beide_tabellen():
    assert "github_zugang" in ll.AUSNAHMEN and "github_rechte" in ll.AUSNAHMEN
    for tabelle in ("github_zugang", "github_rechte"):
        assert "0027" in ll.AUSNAHMEN[tabelle] and "labor" in ll.AUSNAHMEN[tabelle].lower()


def test_migrations_lint_der_pruefstrecke_findet_nichts():
    pruefer = SUPABASE.parent / "infra" / "sokrates2" / "release" / "pruefer"
    sys.path.insert(0, str(pruefer))
    try:
        import migration_lint as ml
        from pruefer_scans import Datei
    finally:
        sys.path.remove(str(pruefer))
    wurzel = SUPABASE.parent
    pfade = ("supabase/migrations/0027_github_zugang.sql", "supabase/migrations/0027_github_zugang.down.sql")
    dateien = [Datei(p, (wurzel / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(wurzel).as_posix() for p in (SUPABASE / "migrations").glob("*.sql") if int(p.name[:4]) <= 27)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []
