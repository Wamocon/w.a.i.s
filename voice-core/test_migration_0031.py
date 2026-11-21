"""Prüft Migration 0031 (Werkstatt-Panel) als Text: Regeln aus CLAUDE.md für Migrationen (RLS, Policy core_all für wamo_core, nur die nötigen
Grants, keine Rechte für anon, authenticated, service_role und wamo_admin, Index je Fremdschlüssel, drop vor create policy und trigger,
Platzhalter), die Form der Tabellen nach dem Vertrag der Werkstatt (docs/adminpanel-bauplan.md, Abschnitt 4), die Ansichten für den Kern,
die Lesefunktionen, die Rolle wamo_werkstatt (nie execute auf labor_loeschen und labor_zaehlen, nie Schreibrecht auf profiles) und dass der
SQL-Test die Kernpunkte enthält. Die Wirkung in der Datenbank prüft supabase/tests/0031_werkstatt_test.sql gegen wamo_test oder wamo_dev;
sie läuft nicht in diesem Test."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import labor_loeschliste as ll

SUPABASE = Path(__file__).resolve().parent.parent / "supabase"
SQL = (SUPABASE / "migrations" / "0031_werkstatt.sql").read_text(encoding="utf-8")
DOWN = (SUPABASE / "migrations" / "0031_werkstatt.down.sql").read_text(encoding="utf-8")
TEST = (SUPABASE / "tests" / "0031_werkstatt_test.sql").read_text(encoding="utf-8")
FREMDE = ("anon", "authenticated", "service_role", "public", "wamo_admin")
TABELLEN = ("labor_termine", "labor_plaetze", "labor_checkliste", "labor_karten", "labor_zuordnung", "labor_karten_versionen",
            "werkstatt_karten")
ANSICHTEN = ("labor_karten_aktive_version", "labor_wissen_aktiv")
LESEFUNKTIONEN = ("werkstatt_sitzungen(integer)", "werkstatt_latenz(integer)", "werkstatt_aktionen(integer)", "werkstatt_labor_stand()",
                  "werkstatt_aufraeumen()")
TRIGGERFUNKTIONEN = ("labor_karten_pflege()", "labor_karten_versionen_schutz()", "werkstatt_karten_schutz()")
SPALTEN = {
    "labor_termine": ("id", "tag", "beginn", "ende", "einwilligung_version", "status", "aufbewahrung_bis", "erstellt_von", "created_at",
                      "updated_at"),
    "labor_plaetze": ("termin_id", "platz", "zweck", "kennung", "gast"),
    "labor_checkliste": ("id", "termin_id", "titel", "quelle", "faellig", "erledigt_at", "erledigt_von"),
    "labor_karten": ("id", "gruppe", "titel", "aufgabe", "erwartung", "fehler", "lernziel", "wissen", "wissenstext", "werkzeuge", "dauer_min",
                     "stand", "geaendert_von", "geaendert_at"),
    "labor_zuordnung": ("termin_id", "platz", "karte_id"),
    "labor_karten_versionen": ("version", "erstellt_at", "erstellt_von", "anzahl_aenderungen", "wissen_zeichen", "karten", "aktiv"),
    "werkstatt_karten": ("id", "admin", "aktion", "ziel", "gilt_bis", "ausgefuehrt_at", "created_at"),
}
# Tabellen mit einem Verweis auf profiles: sie stehen mit Grund in labor_loeschliste.AUSNAHMEN (test_labor_loeschen.py verlangt es)
MIT_PROFILVERWEIS = ("labor_termine", "labor_checkliste", "labor_karten", "labor_karten_versionen", "werkstatt_karten")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("--", 1)[0] for z in text.splitlines())


def _eine_zeile(text: str) -> str:
    return " ".join(text.split())


def _anweisungen(text: str, wort: str) -> list[str]:
    return [_eine_zeile(a) for a in re.split(r";\s*\n", _ohne_kommentare(text)) if re.match(rf"\s*{wort}\b", a, re.I)]


def _tabelle(name: str) -> str:
    treffer = re.search(rf"create table if not exists __SCHEMA__\.{name} \((.*?)\n\);", _ohne_kommentare(SQL), re.S)
    assert treffer, name
    return treffer.group(1)


def _funktion(name: str) -> str:
    code = _ohne_kommentare(SQL)
    anfang = code.index(f"create or replace function __SCHEMA__.{name}")
    ende = code.index("end $$;", anfang)
    return code[anfang:ende]


def test_naechste_nummer_und_beide_dateien():
    nummern = sorted(int(p.name[:4]) for p in (SUPABASE / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql") if not p.name.endswith(".down.sql"))
    assert nummern.count(31) == 1 and all(n > 31 for n in nummern[nummern.index(31) + 1:])
    assert (SUPABASE / "migrations" / "0030_selbstauftraege.sql").is_file()


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
    assert "'0001_wamo_init', '0018_labor_profile'" in code and "<> 2" in code and "0031 braucht 0001 und 0018" in code
    assert not re.search(r"^\s*(begin|commit)\s*;", code, re.I | re.M)
    assert "insert into __SCHEMA__.schema_migrations (version) values ('0031_werkstatt') on conflict do nothing" in code


def test_die_rolle_ist_eine_gruppe_ohne_anmeldung_und_wird_nur_dynamisch_angelegt():
    code = _ohne_kommentare(SQL)
    assert "if not exists (select 1 from pg_roles where rolname = 'wamo_werkstatt') then" in code
    assert "execute 'create role wamo_werkstatt nologin nosuperuser nocreatedb nocreaterole nobypassrls'" in code
    # die Anlage steht nur als Zeichenkette in execute (Lint pflicht_rolle_aendern), nie als eigene Anweisung; kein alter role
    ohne_zeichenketten = re.sub(r"'[^']*'", "''", code)
    assert not re.search(r"\b(create|alter|drop)\s+(role|user)\b", ohne_zeichenketten, re.I)
    assert "grant usage on schema __SCHEMA__ to wamo_werkstatt" in code
    assert "login" not in " ".join(re.findall(r"create role [^']*", code)).replace("nologin", "")


def test_alle_tabellen_idempotent_mit_den_vertraglichen_spalten():
    code = _ohne_kommentare(SQL)
    assert len(re.findall(r"create table\b", code, re.I)) == len(TABELLEN)
    for name in TABELLEN:
        koerper = _tabelle(name)
        for spalte in SPALTEN[name]:
            assert re.search(rf"^\s+{spalte}\s", koerper, re.M), (name, spalte)
        # nie ein Zugangswert, nie Gesprächstext
        for wort in ("token", "schluessel", "zugang", "secret", "password", "email", "content"):
            assert not re.search(rf"^\s+\w*{wort}\w*\s", koerper, re.M | re.I), (name, wort)


def test_labor_termine_nach_vertrag():
    t = _eine_zeile(_tabelle("labor_termine"))
    assert "id uuid primary key default gen_random_uuid()" in t
    assert "tag date not null" in t and "constraint labor_termine_tag_key unique (tag)" in t
    assert "einwilligung_version smallint not null default 1" in t and "einwilligung_version between 1 and 99" in t
    assert "status text not null default 'entwurf'" in t
    assert "status in ('entwurf', 'freigegeben', 'laufend', 'nachlauf', 'abgeschlossen')" in t
    assert "aufbewahrung_bis date not null" in t
    assert "aufbewahrung_bis >= tag and aufbewahrung_bis <= tag + 14" in t
    assert "erstellt_von uuid references __SCHEMA__.profiles(user_id) on delete set null" in t
    assert re.search(r"created_at timestamptz not null default now\(\)", t) and re.search(r"updated_at timestamptz not null default now\(\)", t)
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert "create trigger labor_termine_touch before update on __SCHEMA__.labor_termine for each row execute function __SCHEMA__.touch_updated_at()" in code
    assert code.index("drop trigger if exists labor_termine_touch") < code.index("create trigger labor_termine_touch")


def test_labor_plaetze_nach_vertrag():
    t = _eine_zeile(_tabelle("labor_plaetze"))
    assert "termin_id uuid not null references __SCHEMA__.labor_termine(id) on delete cascade" in t
    assert "primary key (termin_id, platz)" in t and "platz between 1 and 16" in t
    assert "zweck in ('besucher', 'reserve', 'abnahme')" in t
    assert "zweck <> 'abnahme' or platz in (15, 16)" in t
    assert "kennung ~ '^labor-[a-z0-9]{2,8}$'" in t
    assert "length(gast) <= 20" in t and "[[:cntrl:]]" in t  # Pseudonym, nie ein Name, keine Steuerzeichen


def test_labor_checkliste_nach_vertrag():
    t = _eine_zeile(_tabelle("labor_checkliste"))
    assert "id bigint generated always as identity primary key" in t
    assert "termin_id uuid not null references __SCHEMA__.labor_termine(id) on delete cascade" in t
    assert "length(titel) between 1 and 120" in t and "length(quelle) <= 80" in t
    assert "erledigt_von uuid references __SCHEMA__.profiles(user_id) on delete set null" in t
    assert "erledigt_at timestamptz" in t and "faellig date" in t


def test_labor_karten_nach_vertrag():
    t = _eine_zeile(_tabelle("labor_karten"))
    assert "id text primary key" in t and "id ~ '^[A-Z][0-9]{1,2}$'" in t
    for spalte, bis in (("gruppe", 30), ("titel", 60), ("aufgabe", 240), ("erwartung", 240)):
        assert f"length({spalte}) between 1 and {bis}" in t, spalte
    assert "length(fehler) <= 120" in t and "length(lernziel) <= 40" in t
    assert "wissen text not null default 'keine'" in t
    assert "wissen in ('keine', 'Glossar', 'ISTQB-Basis', 'Eigener Text')" in t
    assert "(wissen = 'Eigener Text') = (wissenstext is not null)" in t and "length(wissenstext) between 1 and 900" in t
    assert "werkzeuge text[] not null default '{}'" in t
    assert "werkzeuge <@ array['Jira', 'Mail', 'Canvas', 'Websuche']::text[]" in t
    assert "dauer_min smallint not null" in t and "dauer_min between 1 and 20" in t
    assert "stand in ('entwurf', 'veroeffentlicht')" in t
    assert "geaendert_von uuid references __SCHEMA__.profiles(user_id) on delete set null" in t
    assert "!~ '[[:cntrl:]]'" in t  # keine Steuerzeichen in keinem Textfeld


def test_labor_zuordnung_und_versionen_und_freigabekarten_nach_vertrag():
    z = _eine_zeile(_tabelle("labor_zuordnung"))
    assert "primary key (termin_id, platz, karte_id)" in z and "platz between 1 and 16" in z
    assert "karte_id text not null references __SCHEMA__.labor_karten(id) on delete cascade" in z
    v = _eine_zeile(_tabelle("labor_karten_versionen"))
    assert "version integer generated always as identity primary key" in v
    assert "karten jsonb not null" in v and "aktiv boolean not null default false" in v
    assert "wissen_zeichen between 0 and 6000" in v and "anzahl_aenderungen >= 0" in v
    assert "erstellt_von uuid references __SCHEMA__.profiles(user_id) on delete set null" in v
    k = _eine_zeile(_tabelle("werkstatt_karten"))
    assert "admin uuid not null references __SCHEMA__.profiles(user_id) on delete cascade" in k
    assert "aktion in ('karten_veroeffentlichen')" in k
    assert "ziel jsonb not null" in k and "jsonb_typeof(ziel) = 'object'" in k
    assert "gilt_bis <= created_at + interval '5 minutes'" in k
    assert "ausgefuehrt_at timestamptz" in k


def test_indizes_je_fremdschluessel_und_genau_eine_aktive_version():
    code = _eine_zeile(_ohne_kommentare(SQL))
    for name, spalte in (("labor_termine", "erstellt_von"), ("labor_checkliste", "termin_id"), ("labor_checkliste", "erledigt_von"),
                         ("labor_karten", "geaendert_von"), ("labor_zuordnung", "karte_id"), ("labor_karten_versionen", "erstellt_von"),
                         ("werkstatt_karten", "admin")):
        assert re.search(rf"create index if not exists \w+ on __SCHEMA__\.{name} \({spalte}\)", code), (name, spalte)
    # optionale Fremdschlüssel: partiell
    for name, spalte in (("labor_termine", "erstellt_von"), ("labor_checkliste", "erledigt_von"), ("labor_karten", "geaendert_von"),
                         ("labor_karten_versionen", "erstellt_von")):
        assert f"on __SCHEMA__.{name} ({spalte}) where {spalte} is not null" in code
    assert "create unique index if not exists labor_karten_versionen_aktiv_uni on __SCHEMA__.labor_karten_versionen (aktiv) where aktiv" in code
    assert not re.search(r"create (unique )?index (?!if not exists)", code)


def test_trigger_wiederholbar_und_ohne_definer():
    code = _ohne_kommentare(SQL)
    for trigger, tabelle in (("labor_termine_touch", "labor_termine"), ("labor_karten_pflege", "labor_karten"),
                             ("labor_karten_versionen_schutz", "labor_karten_versionen"), ("werkstatt_karten_schutz", "werkstatt_karten")):
        drop = code.index(f"drop trigger if exists {trigger} on __SCHEMA__.{tabelle}")
        anlegen = code.index(f"create trigger {trigger} before")
        assert drop < anlegen
    for funktion in TRIGGERFUNKTIONEN:
        name = funktion.split("(")[0]
        kopf = _funktion(name)
        assert f"create or replace function __SCHEMA__.{name}() returns trigger" in kopf
        assert "security definer" not in kopf.lower()  # Triggerfunktionen laufen mit den Rechten dessen, der schreibt
        assert "set search_path = ''" in kopf
    assert not re.search(r"\bcreate\s+function\b", code, re.I)


def test_trigger_der_karten_und_der_freigabekarten_tun_was_der_vertrag_sagt():
    code = _eine_zeile(_ohne_kommentare(SQL))
    # Karten: inhaltliche Änderung stempelt und macht aus einer veröffentlichten Karte einen Entwurf
    assert "new.geaendert_at := pg_catalog.now()" in code
    assert "if old.stand = 'veroeffentlicht' and new.stand = 'veroeffentlicht' then new.stand := 'entwurf'" in code
    # Versionen: Momentaufnahme geprüft, danach nur aktiv änderbar
    assert "jsonb_array_length(new.karten) > 500" in code and "pg_column_size(new.karten) > 1048576" in code
    assert "'^[A-Z][0-9]{1,2}$'" in code and "length(t) not between 1 and 900" in code and "summe > new.wissen_zeichen" in code
    assert "constraint = 'labor_karten_versionen_karten'" in code and "constraint = 'labor_karten_versionen_zeichen'" in code
    assert "eine Version ist unveränderlich, nur aktiv wechselt" in code
    # Freigabekarten: einmalig, unveränderlich, nur bis gilt_bis
    assert "if old.ausgefuehrt_at is not null then" in code and "constraint = 'werkstatt_karten_verbraucht'" in code
    assert "pg_catalog.clock_timestamp() > old.gilt_bis" in code and "constraint = 'werkstatt_karten_abgelaufen'" in code
    assert "new.ziel is distinct from old.ziel" in code and "new.gilt_bis is distinct from old.gilt_bis" in code


def test_ansichten_fuer_den_kern_nur_die_aktive_version_nur_eigener_text():
    code = _eine_zeile(_ohne_kommentare(SQL))
    assert ("create or replace view __SCHEMA__.labor_karten_aktive_version with (security_barrier = true) as "
            "select v.version from __SCHEMA__.labor_karten_versionen v where v.aktiv") in code
    wissen = code[code.index("create or replace view __SCHEMA__.labor_wissen_aktiv"):]
    wissen = wissen[:wissen.index(";")]
    assert "with (security_barrier = true)" in wissen
    assert "select v.version, k.karte ->> 'id' as karte_id, k.karte ->> 'wissenstext' as wissenstext" in wissen
    assert "from __SCHEMA__.labor_karten_versionen v" in wissen and "jsonb_array_elements(v.karten)" in wissen
    assert "where v.aktiv and k.karte ->> 'wissen' = 'Eigener Text'" in wissen
    assert "labor_karten " not in wissen.replace("labor_karten_versionen", "")  # nie der Arbeitsstand
    assert not re.search(r"\bcreate\s+view\b", code)  # nur "create or replace" (wiederholbar)


def test_lesefunktionen_definer_leerer_search_path_nur_zahlen_und_grenzen():
    code = _ohne_kommentare(SQL)
    for sig in LESEFUNKTIONEN:
        name = sig.split("(")[0]
        text = _eine_zeile(_funktion(name))
        assert "security definer set search_path = ''" in text, name
    for name in ("werkstatt_sitzungen", "werkstatt_latenz", "werkstatt_aktionen"):
        text = _eine_zeile(_funktion(name))
        assert "p_tage is null or p_tage < 1 or p_tage > 30" in text and "errcode = '22023'" in text, name
        assert "'Europe/Berlin'" in text
    sitzungen = _eine_zeile(_funktion("werkstatt_sitzungen"))
    assert "returns table (tag date, anzahl bigint, dauer_p50_s integer, dauer_p95_s integer, offen bigint)" in sitzungen
    assert "percentile_cont(0.5)" in sitzungen and "percentile_cont(0.95)" in sitzungen and "s.ended_at is null" in sitzungen
    assert "summary" not in sitzungen and "user_id" not in sitzungen
    latenz = _eine_zeile(_funktion("werkstatt_latenz"))
    assert "returns table (tag date, zuege bigint, p50_ms integer, p95_ms integer)" in latenz and "t.latency_ms" in latenz
    assert "content" not in latenz and "meta" not in latenz
    aktionen = _eine_zeile(_funktion("werkstatt_aktionen"))
    assert "returns table (tool text, status text, anzahl bigint)" in aktionen
    assert "params" not in aktionen and "result" not in aktionen  # nie die Parameter, nie das Ergebnis
    stand = _eine_zeile(_funktion("werkstatt_labor_stand"))
    assert "returns table (art text, platz smallint, aktiv boolean, zeilen bigint)" in stand
    assert "__SCHEMA__.labor_zaehlen(r.uid)" in stand
    assert "display_name" not in stand and "email" not in stand and "user_id as" in stand  # die Kennung bleibt in der Funktion
    assert "return next" in stand and "r.uid" in stand and "uid" not in stand.split("returns table")[1].split("language")[0]
    aufraeumen = _eine_zeile(_funktion("werkstatt_aufraeumen"))
    assert "delete from __SCHEMA__.werkstatt_karten k where k.created_at < pg_catalog.now() - interval '1 day'" in aufraeumen
    assert "returns bigint" in aufraeumen
    # labor_loeschen kommt nur im Selbsttest vor (als Verbot), nie in einer Funktion oder einem Grant
    selbsttest_ab = code.index("rolle     text;")
    assert code.count("labor_loeschen") >= 1 and code.index("labor_loeschen") > selbsttest_ab


def test_rls_je_tabelle_core_all_verbietet_alles_werkstatt_all_mit_drop_davor():
    code = _eine_zeile(_ohne_kommentare(SQL))
    for name in TABELLEN:
        assert f"alter table __SCHEMA__.{name} enable row level security" in code, name
        d1 = code.index(f"drop policy if exists core_all on __SCHEMA__.{name}")
        c1 = code.index(f"create policy core_all on __SCHEMA__.{name} for all to wamo_core using (false) with check (false)")
        d2 = code.index(f"drop policy if exists werkstatt_all on __SCHEMA__.{name}")
        c2 = code.index(f"create policy werkstatt_all on __SCHEMA__.{name} for all to wamo_werkstatt using (true) with check (true)")
        assert d1 < c1 and d2 < c2, name
    # profiles und actions: je eine schmale Policy für wamo_werkstatt, nur lesen beziehungsweise nur anlegen und lesen
    assert code.index("drop policy if exists werkstatt_lesen on __SCHEMA__.profiles") < code.index(
        "create policy werkstatt_lesen on __SCHEMA__.profiles for select to wamo_werkstatt using (true)")
    assert code.index("drop policy if exists werkstatt_audit_insert on __SCHEMA__.actions") < code.index(
        "create policy werkstatt_audit_insert on __SCHEMA__.actions for insert to wamo_werkstatt with check (tool like 'werkstatt\\_%')")
    assert code.index("drop policy if exists werkstatt_audit_lesen on __SCHEMA__.actions") < code.index(
        "create policy werkstatt_audit_lesen on __SCHEMA__.actions for select to wamo_werkstatt using (tool like 'werkstatt\\_%')")
    assert len(re.findall(r"create policy", code, re.I)) == len(TABELLEN) * 2 + 3
    assert "disable row level security" not in code and "force row level security" not in code


def test_rechte_nur_wamo_core_auf_zwei_ansichten_und_wamo_werkstatt_gezielt():
    code = _ohne_kommentare(SQL)
    grants = _anweisungen(code, "grant")
    for g in grants:
        assert not any(re.search(rf"\b{f}\b", g, re.I) for f in FREMDE), g
        assert g.endswith("to wamo_werkstatt") or g.endswith("to wamo_core"), g
        assert not re.search(r"\ball\b|\btruncate\b|\breferences\b|\btrigger\b", g, re.I), g
    # der Kern: genau select auf die zwei Ansichten
    kern = [g for g in grants if g.endswith("to wamo_core")]
    assert sorted(kern) == sorted(f"grant select on __SCHEMA__.{a} to wamo_core" for a in ANSICHTEN)
    # das Panel liest nie die Ansichten des Kerns
    assert not any(a in g for a in ANSICHTEN for g in grants if g.endswith("to wamo_werkstatt"))
    # Löschen nur an vier Tabellen
    geloescht = {re.search(r"on __SCHEMA__\.(\w+) to", g).group(1) for g in grants if g.startswith("grant delete")}
    assert geloescht == {"labor_termine", "labor_plaetze", "labor_karten", "labor_zuordnung"}
    # kein Tabellenrecht zum Schreiben, nur Spaltenrechte
    for g in grants:
        if g.startswith(("grant insert", "grant update")):
            assert re.match(r"grant (insert|update) \(", g), g
    # profiles: genau vier Spalten lesen, nie schreiben
    profiles = [g for g in grants if "__SCHEMA__.profiles" in g]
    assert profiles == ["grant select (user_id, rolle, aktiv, labor_art) on __SCHEMA__.profiles to wamo_werkstatt"]
    # actions: anlegen und eine Handvoll Spalten lesen, nie ändern oder löschen
    actions = [g for g in grants if "__SCHEMA__.actions" in g]
    assert len(actions) == 2 and all(g.startswith(("grant insert (", "grant select (")) for g in actions)
    lesen = next(g for g in actions if g.startswith("grant select ("))
    assert "params" not in lesen and "result" not in lesen and "reason" not in lesen
    # nie die Laborfunktionen von 0018
    assert not any("labor_loeschen" in g or "labor_zaehlen" in g for g in grants)
    # Spalten, die die Datenbank stempelt, setzt das Panel nie
    for g in grants:
        if g.startswith("grant insert (") and "labor_termine" in g:
            assert "created_at" not in g and "updated_at" not in g
        if g.startswith("grant update (") and "labor_karten_versionen" in g:
            assert g == "grant update (aktiv) on __SCHEMA__.labor_karten_versionen to wamo_werkstatt"
        if g.startswith("grant update (") and "werkstatt_karten" in g:
            assert g == "grant update (ausgefuehrt_at) on __SCHEMA__.werkstatt_karten to wamo_werkstatt"


def test_vorab_alles_entziehen_und_funktionsrechte_nur_fuer_wamo_werkstatt():
    code = _ohne_kommentare(SQL)
    revoke = _anweisungen(code, "revoke")
    tabellen_revoke = [r for r in revoke if "function" not in r]
    assert len(tabellen_revoke) == len(TABELLEN) + len(ANSICHTEN)
    for r in tabellen_revoke:
        assert r.endswith("from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt"), r
    funktions_revoke = [r for r in revoke if "function" in r]
    assert len(funktions_revoke) == len(LESEFUNKTIONEN) + len(TRIGGERFUNKTIONEN)
    for r in funktions_revoke:
        assert r.endswith("from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt"), r
        assert "labor_loeschen" not in r and "labor_zaehlen" not in r  # an den Laborfunktionen von 0018 ändert diese Datei nichts
    ausfuehren = [g for g in _anweisungen(code, "grant") if g.startswith("grant execute")]
    assert sorted(ausfuehren) == sorted(f"grant execute on function __SCHEMA__.{f} to wamo_werkstatt" for f in LESEFUNKTIONEN)
    # erst entziehen, dann vergeben
    assert code.index("revoke all on __SCHEMA__.labor_termine") < code.index("grant select on __SCHEMA__.labor_karten_aktive_version")


def test_selbsttest_prueft_rechte_rls_funktionen_trigger_und_die_grenze_zu_0018():
    code = _eine_zeile(_ohne_kommentare(SQL))
    selbsttest = code[code.index("declare rolle text;"):code.index("insert into __SCHEMA__.schema_migrations")]
    for muster in ("rolcanlogin", "rolsuper", "rolbypassrls", "has_any_column_privilege", "has_table_privilege", "has_column_privilege",
                   "has_function_privilege", "aclexplode", "relrowsecurity", "pg_policies", "qual = 'false' and with_check = 'false'",
                   "tgenabled = 'O'", "security_barrier=true", "labor_karten_versionen_aktiv_uni", "prosecdef", "search_path=\"\"",
                   "wamo_werkstatt_login"):
        assert muster in selbsttest, muster
    for rolle in ("anon", "authenticated", "service_role", "wamo_admin", "wamo_core"):
        assert f"'{rolle}'" in selbsttest, rolle
    # die Grenze zu 0018: keine Laborfunktion, kein Schreibrecht auf profiles
    assert "'__SCHEMA__.labor_loeschen(uuid, timestamptz, timestamptz)', 'EXECUTE'" in selbsttest
    assert "'__SCHEMA__.labor_zaehlen(uuid)', 'EXECUTE'" in selbsttest
    assert "'__SCHEMA__.profiles', 'INSERT,UPDATE,REFERENCES'" in selbsttest
    assert "errcode = '42501'" in selbsttest


def test_rueckweg_gesperrt_in_prod_und_bei_folgemigrationen_und_wiederholbar():
    code = _ohne_kommentare(DOWN)
    assert "'__SCHEMA__' = 'wamo_prod'" in code and "wamo.allow_drop" in code
    assert "version > '0031_werkstatt'" in code and "wamo.down_trotz_folgemigration" in code
    for name in ANSICHTEN:
        assert f"drop view if exists __SCHEMA__.{name}" in code
    for name in TABELLEN:
        assert f"drop table if exists __SCHEMA__.{name}" in code, name
    for sig in (*LESEFUNKTIONEN, *TRIGGERFUNKTIONEN):
        assert f"drop function if exists __SCHEMA__.{sig}" in code, sig
    for politik in ("werkstatt_lesen on __SCHEMA__.profiles", "werkstatt_audit_insert on __SCHEMA__.actions",
                    "werkstatt_audit_lesen on __SCHEMA__.actions"):
        assert f"drop policy if exists {politik}" in code
    # die Ansichten fallen vor der Tabelle, auf der sie stehen
    assert code.index("drop view if exists __SCHEMA__.labor_wissen_aktiv") < code.index("drop table if exists __SCHEMA__.labor_karten_versionen")
    assert "delete from __SCHEMA__.schema_migrations where version = '0031_werkstatt'" in code
    # Rollen gelten je Cluster: der Rückweg lässt sie stehen (wie 0013)
    assert not re.search(r"\bdrop\s+role\b", code, re.I)
    assert "cascade" not in code.lower()
    assert "if exists (select 1 from pg_roles where rolname = 'wamo_werkstatt')" in code  # Rechte nur, wenn die Rolle da ist


def test_sql_test_ist_eine_zurueckgerollte_transaktion_nie_in_prod_und_prueft_die_kernpunkte():
    code = _ohne_kommentare(TEST)
    assert code.index("begin;") < code.index("rollback;")
    assert "\\echo 0031 OK" in TEST
    assert "Test nie in wamo_prod" in code
    for rolle in ("wamo_werkstatt", "wamo_core"):
        assert f"set role {rolle}" in code, rolle
    for rolle in ("'anon'", "'authenticated'", "'service_role'", "'wamo_admin'"):
        assert rolle in code, rolle
    for punkt in ("'23505'", "'23514'", "'23503'", "'42501'", "'428C9'", "'22023'", "'55000'",
                  "werkstatt_karten_verbraucht", "werkstatt_karten_abgelaufen", "labor_karten_versionen_karten", "labor_karten_versionen_zeichen",
                  "werkstatt_aufraeumen()", "werkstatt_labor_stand()", "labor_wissen_aktiv", "labor_karten_aktive_version",
                  "Marker-Text-31", "'A1:Text zwei|C3:Text drei'", "552", "2900",
                  "labor_zaehlen('00000000-0000-4000-8000-0000000031a3'::uuid)", "labor_loeschen('00000000-0000-4000-8000-0000000031a3'::uuid)",
                  "has_schema_privilege('wamo_werkstatt'", "tool not like 'werkstatt\\_%'"):
        assert punkt in code, punkt


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
    pfade = ("supabase/migrations/0031_werkstatt.sql", "supabase/migrations/0031_werkstatt.down.sql")
    dateien = [Datei(p, (wurzel / p).read_bytes(), None) for p in pfade]
    baum = tuple(p.relative_to(wurzel).as_posix() for p in (SUPABASE / "migrations").glob("*.sql") if int(p.name[:4]) <= 31)
    befund = ml.migration_lint(dateien, baum)
    assert [(t.pfad, t.zeile, t.art) for t in befund.treffer] == []


def test_neue_tabellen_mit_profilverweis_stehen_mit_grund_in_der_loeschliste():
    """Tabellen mit Verweis auf profiles(user_id) gehören entweder in LOESCHLISTE oder mit Grund in AUSNAHMEN (test_labor_loeschen.py). Das
    Panel ist nur für Admins ohne labor_art, ein Laborprofil kommt dort nie vor: alle fünf stehen in AUSNAHMEN."""
    loesch = {o.tabelle for o in ll.LOESCHLISTE}
    for name in MIT_PROFILVERWEIS:
        assert name in ll.AUSNAHMEN and ll.AUSNAHMEN[name].strip(), name
        assert name not in loesch, name
        assert re.search(rf"^\s+\w+\s+uuid\b[^,\n]*\breferences __SCHEMA__\.profiles\(user_id\)", _tabelle(name), re.M), name
    for name in set(TABELLEN) - set(MIT_PROFILVERWEIS):
        assert name not in ll.AUSNAHMEN
        assert "profiles" not in _tabelle(name)
