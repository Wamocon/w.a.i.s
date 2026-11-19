"""Prüft Migration 0030 (Rückstand an Aufträgen an W.A.I.S. selbst) als Text: Regeln aus CLAUDE.md für Migrationen (RLS, Policy core_all für
wamo_core, nur die nötigen Grants ohne delete, keine Rechte für anon, authenticated, service_role und wamo_admin, Index für den
Fremdschlüssel, drop vor create policy und trigger, Platzhalter), dass die Grenzen zu selbstauftraege.py passen und dass der SQL-Test die
Anweisungen des Kerns wörtlich enthält. Die Wirkung in der Datenbank prüft supabase/tests/0030_selbstauftraege_test.sql gegen wamo_test
oder wamo_dev; sie läuft nicht in diesem Test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import selbstauftraege as sa

SUPABASE = Path(__file__).resolve().parent.parent / "supabase"
SQL = (SUPABASE / "migrations" / "0030_selbstauftraege.sql").read_text(encoding="utf-8")
DOWN = (SUPABASE / "migrations" / "0030_selbstauftraege.down.sql").read_text(encoding="utf-8")
TEST = (SUPABASE / "tests" / "0030_selbstauftraege_test.sql").read_text(encoding="utf-8")
FREMDE = ("anon", "authenticated", "service_role", "public", "wamo_admin")
SPALTEN = ("id", "nr", "titel", "beschreibung", "art", "abnahme", "prioritaet", "status", "quelle", "unsicher", "erstellt_von", "erstellt_at",
           "bearbeiter", "bearbeitet_at", "ergebnis", "geaendert_at")
EINFUEGBAR = {"titel", "beschreibung", "art", "abnahme", "prioritaet", "quelle", "unsicher", "erstellt_von"}
TABELLE = "__SCHEMA__.selbstauftraege"


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _anweisungen(text: str, wort: str) -> list[str]:
    return [" ".join(a.split()) for a in re.split(r";\s*\n", _ohne_kommentare(text)) if re.match(rf"\s*{wort}\b", a, re.I)]


def _eine_zeile(text: str) -> str:
    return " ".join(text.split())


def test_naechste_nummer_und_beide_dateien():
    nummern = sorted(int(p.name[:4]) for p in (SUPABASE / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
                     if not p.name.endswith(".down.sql"))
    assert 30 in nummern and nummern.count(30) == 1 and all(n > 30 for n in nummern[nummern.index(30) + 1:])
    assert (SUPABASE / "migrations" / "0029_stimme_mikrofone.sql").is_file()


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
        assert not re.search(r"\b(fuer|ueber|Pruefung|Rueckweg|koennen|waehrend|aendern|Aenderung|loeschen|Auftraege)\b",
                             " ".join(kommentare)), "Ersatzschreibweise für Umlaute im Kommentar"


def test_tabelle_idempotent_mit_den_vereinbarten_spalten():
    koerper = re.search(r"create table if not exists __SCHEMA__\.selbstauftraege \((.*?)\n\);", SQL, re.S)
    assert koerper
    for spalte in SPALTEN:
        assert re.search(rf"^\s+{spalte}\s", koerper.group(1), re.M), spalte
    assert re.search(r"id\s+uuid primary key default gen_random_uuid\(\)", SQL)
    assert re.search(r"nr\s+bigint generated always as identity", SQL)  # niemand setzt die Nummer selbst
    assert re.search(r"erstellt_at\s+timestamptz not null default now\(\)", SQL)
    for wort in ("token", "schluessel", "zugang", "wert", "secret"):  # nie ein Zugangswert
        assert not re.search(rf"^\s+\w*{wort}\w*\s", koerper.group(1), re.M | re.I), wort


def test_fremdschluessel_zeigt_auf_profiles_mit_set_null_und_partiellem_index():
    code = _ohne_kommentare(SQL)
    assert re.search(r"erstellt_von\s+uuid references __SCHEMA__\.profiles\(user_id\) on delete set null", code)
    assert "auth.users" not in code
    assert re.search(r"create index if not exists selbstauftraege_von_idx on __SCHEMA__\.selbstauftraege \(erstellt_von\) "
                     r"where erstellt_von is not null", code)
    assert re.search(r"create index if not exists selbstauftraege_liste_idx on __SCHEMA__\.selbstauftraege \(status, prioritaet, nr\)", code)
    kopf = SQL.split("set local lock_timeout", 1)[0]
    assert "profiles" in kopf and "0001" in kopf


def test_grenzen_der_datenbank_passen_zum_kern():
    code = _ohne_kommentare(SQL)
    assert f"length(titel) between 1 and {sa.TITEL_ZEICHEN}" in code
    assert f"length(beschreibung) between 1 and {sa.BESCHREIBUNG_ZEICHEN}" in code
    assert f"art ~ '^{sa.ART_RE.pattern}$'" in code
    assert f"jsonb_array_length(abnahme) <= {sa.KRITERIEN_MAX}" in code
    assert "prioritaet between 1 and 3" in code
    assert "status in ('" + "', '".join(sa.STATUS) + "')" in code
    assert "quelle in ('" + "', '".join(sa.QUELLEN) + "')" in code
    assert "bearbeiter in ('" + "', '".join(sa.BEARBEITER) + "')" in code
    groesse = int(re.search(r"pg_column_size\(abnahme\) <= (\d+)", code).group(1))
    assert sa.KRITERIEN_MAX * sa.KRITERIUM_ZEICHEN * 4 + 200 < groesse  # fünf Kriterien zu 300 Zeichen zu 4 Byte passen
    assert f">= {sa.MAX_OFFEN} then" in code  # Trigger der Grenze
    assert sa.GRENZE_TRIGGER in code
    assert f"< {sa.MAX_JE_TAG}" in sa._EINFUEGEN  # Tagesgrenze im Kern, die SQL-Test prüft sie mit
    assert f"{sa.MAX_OFFEN} Einträge" in "\n".join(z for z in SQL.splitlines() if z.startswith("--"))


def test_trigger_wiederholbar_ohne_definer_grenze_mit_sperre_und_status_mit_uebergaengen():
    code = _ohne_kommentare(SQL)
    for funktion in ("selbstauftraege_grenze", "selbstauftraege_status"):
        assert f"create or replace function __SCHEMA__.{funktion}() returns trigger" in code
        drop = code.index(f"drop trigger if exists {funktion} on __SCHEMA__.selbstauftraege")
        anlegen = code.index(f"create trigger {funktion} before")
        assert drop < anlegen
        # die Triggerfunktionen laufen mit den Rechten dessen, der schreibt (nie security definer)
        text = code[code.index(f"create or replace function __SCHEMA__.{funktion}()"):]
        assert "security definer" not in text.split("$$;", 1)[0].lower()
    assert "pg_advisory_xact_lock" in code and "errcode = '23514'" in code
    assert "selbstauftraege_status_uebergang" in code
    # die Grenze von 200 gilt beim Einfügen UND beim Wiedereröffnen (Befund der Prüfung vom 19.11.2026): dieselbe Sperre, dieselbe Zählung,
    # derselbe Name der Grenze
    status = code[code.index("create or replace function __SCHEMA__.selbstauftraege_status()"):code.index("revoke all on function __SCHEMA__.selbstauftraege_status()")]
    assert "old.status = 'verworfen' and new.status = 'offen'" in status
    assert "pg_advisory_xact_lock" in status and ">= 200" in status and "constraint = 'selbstauftraege_grenze'" in status
    revoke = [a for a in _anweisungen(code, "revoke") if "function" in a]
    assert len(revoke) == 4 and all("wamo_core" in r and "public" in r for r in revoke)


def test_die_zwei_funktionen_des_kerns_sind_definer_mit_leerem_search_path_und_festen_uebergaengen():
    code = _ohne_kommentare(SQL)
    for name, setzen, wo in (("selbstauftrag_verwerfen", "status = 'verworfen'", "status in ('offen', 'in_arbeit')"),
                             ("selbstauftrag_oeffnen", "status = 'offen'", "status = 'verworfen'")):
        kopf = f"create or replace function __SCHEMA__.{name}(p_nr bigint) returns bigint"
        assert kopf in code, name
        teil = code[code.index(kopf):]
        teil = teil[:teil.index("$$;")]
        assert "language sql security definer set search_path = ''" in " ".join(teil.split()), name
        assert f"update __SCHEMA__.selbstauftraege set {setzen} where nr = p_nr and {wo} returning nr" in " ".join(teil.split()), name
        assert f"grant execute on function __SCHEMA__.{name}(bigint) to wamo_core" in code
        assert f"revoke all on function __SCHEMA__.{name}(bigint) from public, anon, authenticated, service_role, wamo_admin, wamo_core" in code
    assert "'erledigt'" not in code.split("create or replace function __SCHEMA__.selbstauftrag_verwerfen", 1)[1].split("revoke all on function", 1)[0]
    assert "prosecdef" in code and "search_path=\"\"" in code  # der Selbsttest prüft Form und Rechte der Funktionen


def test_rls_policy_core_all_mit_drop_davor():
    code = _ohne_kommentare(SQL)
    assert "alter table __SCHEMA__.selbstauftraege enable row level security" in code
    drop = code.index("drop policy if exists core_all on __SCHEMA__.selbstauftraege")
    anlegen = code.index("create policy core_all on __SCHEMA__.selbstauftraege for all to wamo_core using (true) with check (true)")
    assert drop < anlegen
    assert len(re.findall(r"create policy", code, re.I)) == 1


def test_rechte_nur_der_kern_lesen_gezielt_einfuegen_kein_update_kein_delete_stand_nur_ueber_funktionen():
    code = _ohne_kommentare(SQL)
    grants = _anweisungen(code, "grant")
    assert len(grants) == 4  # select, insert in acht Spalten und execute auf die zwei Funktionen
    for g in grants:
        assert g.endswith("to wamo_core"), g
        assert not any(re.search(rf"\b{f}\b", g, re.I) for f in FREMDE), g
        assert not re.search(r"\bdelete\b|\ball\b|\btruncate\b|\breferences\b|\btrigger\b|\bupdate\b", g, re.I), g
    assert "grant select on __SCHEMA__.selbstauftraege to wamo_core" in grants
    einfuegen = [g for g in grants if g.startswith("grant insert (")]
    assert len(einfuegen) == 1
    assert set(re.findall(r"\b[a-z_]+\b", einfuegen[0].split("(", 1)[1].split(")", 1)[0])) == EINFUEGBAR
    assert [g for g in grants if g.startswith("grant execute on function")] == [
        "grant execute on function __SCHEMA__.selbstauftrag_verwerfen(bigint) to wamo_core",
        "grant execute on function __SCHEMA__.selbstauftrag_oeffnen(bigint) to wamo_core"]
    assert "grant update" not in code  # der Kern ändert nichts direkt (Befund der Prüfung vom 19.11.2026)
    revoke = " ".join(a for a in _anweisungen(code, "revoke") if "function" not in a)
    assert "revoke all on __SCHEMA__.selbstauftraege from" in revoke
    for rolle in (*FREMDE, "wamo_core"):
        assert re.search(rf"\b{rolle}\b", revoke), rolle
    assert code.index("revoke all on __SCHEMA__.selbstauftraege") < code.index("grant select on")


def test_voraussetzung_selbsttest_und_eintrag():
    code = _ohne_kommentare(SQL)
    assert "set local lock_timeout" in code
    assert "version = '0001_wamo_init'" in code and "0030 braucht 0001" in code
    assert not re.search(r"^\s*(begin|commit)\s*;", code, re.I | re.M)
    for rolle in ("wamo_admin", "anon", "authenticated", "service_role"):
        assert f"'{rolle}'" in code, rolle
    assert "relrowsecurity" in code and "policyname = 'core_all'" in code
    assert "'selbstauftraege_grenze', 'selbstauftraege_status'" in code
    assert "insert into __SCHEMA__.schema_migrations (version) values ('0030_selbstauftraege') on conflict do nothing" in code


def test_rueckweg_gesperrt_in_prod_und_bei_folgemigrationen_und_wiederholbar():
    code = _ohne_kommentare(DOWN)
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "version > '0030_selbstauftraege'" in code and "wamo.down_trotz_folgemigration" in code
    assert "drop table if exists __SCHEMA__.selbstauftraege" in code
    assert "drop function if exists __SCHEMA__.selbstauftraege_grenze()" in code
    assert "drop function if exists __SCHEMA__.selbstauftraege_status()" in code
    assert "drop function if exists __SCHEMA__.selbstauftrag_verwerfen(bigint)" in code
    assert "drop function if exists __SCHEMA__.selbstauftrag_oeffnen(bigint)" in code
    assert "delete from __SCHEMA__.schema_migrations where version = '0030_selbstauftraege'" in code
    assert "cascade" not in code.lower()


def test_sql_test_ist_eine_zurueckgerollte_transaktion_nie_in_prod_und_prueft_die_kernpunkte():
    code = _ohne_kommentare(TEST)
    assert code.index("begin;") < code.index("rollback;")
    assert "\\echo 0030 OK" in TEST
    assert "Test nie in wamo_prod" in code and "set role wamo_core" in code
    for rolle in ("anon", "authenticated", "service_role", "wamo_admin"):
        assert f"set role {rolle}" in code, rolle
    for punkt in ("truncate __SCHEMA__.selbstauftraege", "delete from __SCHEMA__.selbstauftraege", "update __SCHEMA__.selbstauftraege set titel",
                  "selbstauftraege_grenze", "'23514'", "'23503'", "'42501'", "'428C9'", "generate_series(1, 28)", "delete from __SCHEMA__.profiles",
                  "'in_arbeit'", "'erledigt'"):
        assert punkt in code, punkt


def _teile(sql: str) -> list[str]:
    """Die Teile einer Anweisung des Kerns zwischen den Platzhaltern ($1::uuid, $2 ...), je ohne Rand."""
    return [t.strip() for t in re.split(r"\$\d+(?:::[a-z]+)*", _eine_zeile(sql)) if t.strip()]


def test_sql_test_enthaelt_die_anweisungen_des_kerns_woertlich():
    """Der SQL-Test prüft, was der Kern wirklich schickt: ändert sich selbstauftraege.py, muss der SQL-Test mit."""
    sql_test = _eine_zeile(_ohne_kommentare(TEST))
    aufrufe = [sa._AUFRUF.format(f=f"__SCHEMA__.{name}") for name in (sa.FUNKTION_VERWERFEN, sa.FUNKTION_OEFFNEN)]
    for anweisung in (sa._EINFUEGEN.format(t=TABELLE), sa._LISTE.format(t=TABELLE), *aufrufe):
        for teil in _teile(anweisung):
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
    pfade = ("supabase/migrations/0030_selbstauftraege.sql", "supabase/migrations/0030_selbstauftraege.down.sql")
    dateien = [Datei(p, (wurzel / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(wurzel).as_posix() for p in (SUPABASE / "migrations").glob("*.sql") if int(p.name[:4]) <= 30)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_der_kern_aendert_nichts_direkt_nur_funktionsaufrufe_mit_einer_nummer():
    assert sa._AUFRUF == "select {f}($1::bigint) as nr"
    assert (sa.FUNKTION_VERWERFEN, sa.FUNKTION_OEFFNEN) == ("selbstauftrag_verwerfen", "selbstauftrag_oeffnen")
    alle = (sa._EINFUEGEN + sa._LISTE + sa._AUFRUF).lower()
    assert "delete" not in alle and "update" not in alle  # kein update in einer Anweisung des Kerns (er hat auch kein Recht darauf)
    for name in (sa.FUNKTION_VERWERFEN, sa.FUNKTION_OEFFNEN):
        assert f"create or replace function __SCHEMA__.{name}(p_nr bigint)" in SQL
