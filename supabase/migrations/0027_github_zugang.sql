-- WAMO 0027: Persönliche GitHub-Zugänge für Entwicklungsaufträge (Plan C, docs/persoenliche-zugaenge.md, C.3 und Entscheidung vom
-- 18.11.2026 zu den Rechten je Person). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, ein zweiter Lauf ändert nichts):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0027_github_zugang.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0027_github_zugang.down.sql. Test: supabase/tests/0027_github_zugang_test.sql. Hängt von 0001 (profiles, schema_migrations,
-- Rollen wamo_core und wamo_admin) und 0018 (profiles.labor_art) ab; 0026 muss dafür nicht angewendet sein.
-- wamo_prod nur nach ausdrücklicher Freigabe und nach dem Agenten database-reviewer.
--
-- Was hier entsteht:
--   * github_zugang  eine Zeile je Profil mit dem persönlichen GitHub-Token als Chiffrat (AES-256-GCM, Hauptschlüssel nur beim Kern,
--                    Zweck github in voice-core/schluessel.py) und den Angaben, die der Kern beim Speichern bei GitHub geprüft hat: Art,
--                    die letzten vier Zeichen, Login, Konto-ID, Rechte (nur bei klassischen Tokens) und Ablauf. Der Kern
--                    (voice-core/github_zugang.py) schreibt sie nur nach der Prüfung, entschlüsselt das Token je Entwicklungsauftrag frisch
--                    und gibt es dem Dispatcher nur über stdin. Kein Weg gibt den Wert an die Oberfläche zurück.
--   * github_rechte  je Profil die Scopes eines klassischen Tokens, die ein Admin über den strengen Standard hinaus erlaubt hat
--                    (Spalte scopes_ausnahmen, C.2.8). Standard ist eine Erlaubnisliste: nur SCOPES_UNBEDENKLICH (repo, public_repo und
--                    lesende Rechte), alles andere ist abgelehnt, auch jeder unbekannte Scope. Der Admin kann je Person einzelne Scopes aus
--                    SCOPES_AUSNAHMEN erlauben (die feste Liste unten, gleich mit voice-core/entwicklung_betrieb.py), nie einen aus
--                    SCOPES_NIE (delete_repo, site_admin, admin:enterprise und dessen Teilrechte). Geschrieben nur über die Admin-Route des
--                    Kerns (voice-core/github_zugang_api.py), gelesen nur vom Kern, der die Liste sortiert im Feld scopes_ausnahmen an den
--                    Dispatcher schickt; jede Änderung steht zusätzlich als Zeile in actions (Werkzeug github_rechte). Die Tabelle ist von
--                    github_zugang getrennt, damit die Einstellung einen Widerruf des Tokens übersteht.
--
-- Besitzer: user_id verweist auf profiles(user_id) (wie 0010 und 0026), nie auf auth.users. Wird ein Profil gelöscht, gehen Token und
-- Rechte mit. Laborprofile bekommen nie eine Zeile (Trigger github_zugang_guard und github_rechte_guard, zusätzlich sperrt der Kern sie).
--
-- Zeitpunkte setzt die Datenbank (Trigger): angelegt_at beim Einfügen und bei einem neuen Token, geprueft_at bei jedem Schreiben,
-- geaendert_at in github_rechte bei jedem Schreiben. Der Kern kann nichts zurückdatieren.
--
-- Rechte (CLAUDE.md, C.3):
--   github_zugang  wamo_core liest, fügt in die Spalten des Kerns ein, ändert gezielt und löscht (delete ist begründet: Die Person
--                  widerruft ihren Zugang selbst). wamo_admin liest nur user_id, art, login, ablauf und geprueft_at, nie das Chiffrat,
--                  das Ende, die Konto-ID oder die Rechte.
--   github_rechte  nur wamo_core: lesen, einfügen und ändern (kein delete: eine leere Liste ist der Standard). wamo_admin nichts.
--   anon, authenticated, service_role, public, wamo_release und wamo_anker haben auf beiden Tabellen keine Rechte. Vor dem Vergeben
--   wird auch wamo_core und wamo_admin alles entzogen, damit ein Nachlauf nach geänderten Rechten wieder zum selben Stand führt.
set local lock_timeout = '5s';

do $$ begin
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0001_wamo_init') then
    raise exception '0027 braucht 0001';
  end if;
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0018_labor_profile') then
    raise exception '0027 braucht 0018 (profiles.labor_art)';
  end if;
end $$;

-- ---------- Tabelle github_zugang ----------
create table if not exists __SCHEMA__.github_zugang (
  user_id     uuid primary key references __SCHEMA__.profiles(user_id) on delete cascade,
  art         text not null,
  token       bytea not null,
  token_ende  text not null,
  login       text not null,
  konto_id    bigint not null,
  scopes      text[] not null default '{}'::text[],
  ablauf      timestamptz not null,
  geprueft_at timestamptz not null default now(),
  angelegt_at timestamptz not null default now(),
  constraint github_zugang_art_chk check (art in ('fein', 'klassisch')),
  constraint github_zugang_token_chk check (octet_length(token) between 40 and 1024),
  constraint github_zugang_token_ende_chk check (token_ende ~ '^[A-Za-z0-9_]{4}$'),
  constraint github_zugang_login_chk check (login ~ '^[A-Za-z0-9]([A-Za-z0-9-]{0,38})$'),
  constraint github_zugang_konto_chk check (konto_id > 0),
  -- höchstens 30 Rechte, keine leeren oder fremden Zeichen (array_to_string lässt null weg, deshalb array_position extra)
  constraint github_zugang_scopes_chk check (cardinality(scopes) <= 30 and coalesce(array_ndims(scopes), 1) = 1
    and array_position(scopes, null) is null
    and array_to_string(scopes, ' ') ~ '^([a-z][a-z0-9_:]{0,39}( [a-z][a-z0-9_:]{0,39})*)?$'),
  -- fein-granulare Tokens haben keine abfragbaren Scopes
  constraint github_zugang_fein_chk check (art = 'klassisch' or cardinality(scopes) = 0)
);
comment on table __SCHEMA__.github_zugang is
  'Persönliches GitHub-Token je Profil, nur als Chiffrat (Zweck github), mit geprüftem Login, Art, Rechten und Ablauf. Nie für Laborprofile, nur der Kern.';

-- ---------- Tabelle github_rechte ----------
create table if not exists __SCHEMA__.github_rechte (
  user_id          uuid primary key references __SCHEMA__.profiles(user_id) on delete cascade,
  scopes_ausnahmen text[] not null default '{}'::text[],
  geaendert_von    uuid references __SCHEMA__.profiles(user_id) on delete set null,
  geaendert_at     timestamptz not null default now(),
  constraint github_rechte_anzahl_chk check (cardinality(scopes_ausnahmen) <= 30 and coalesce(array_ndims(scopes_ausnahmen), 1) = 1
    and array_position(scopes_ausnahmen, null) is null),
  -- nie, auch nicht vom Admin (SCOPES_NIE). Bewusst doppelt: die feste Liste darunter schließt diese Scopes schon aus; die Prüfung bleibt,
  -- falls die Liste je um einen davon wächst
  constraint github_rechte_nie_chk check (not (scopes_ausnahmen && array[
    'delete_repo', 'site_admin', 'admin:enterprise', 'manage_runners:enterprise', 'manage_billing:enterprise',
    'read:enterprise'
  ]::text[])),
  -- nur aus SCOPES_AUSNAHMEN (voice-core/entwicklung_betrieb.py, gleich gehalten von test_migration_0027.py)
  constraint github_rechte_liste_chk check (scopes_ausnahmen <@ array[
    'admin:org', 'write:org', 'admin:org_hook', 'admin:repo_hook', 'write:repo_hook', 'admin:public_key',
    'write:public_key', 'admin:gpg_key', 'write:gpg_key', 'admin:ssh_signing_key', 'write:ssh_signing_key',
    'write:packages', 'read:packages', 'delete:packages', 'user', 'user:email', 'user:follow', 'workflow', 'gist',
    'codespace', 'codespace:secrets', 'copilot', 'manage_billing:copilot', 'manage_runners:org',
    'write:network_configurations', 'audit_log', 'read:audit_log'
  ]::text[])
);
comment on table __SCHEMA__.github_rechte is
  'Je Profil die Scopes klassischer GitHub-Tokens, die ein Admin über die Erlaubnisliste hinaus zulässt (nur aus SCOPES_AUSNAHMEN). Nur der Kern, nie für Laborprofile.';

-- ---------- Indizes ----------
-- user_id ist in beiden Tabellen der Primärschlüssel (Index vorhanden); geaendert_von ist optional, deshalb partiell
create index if not exists github_rechte_geaendert_von_idx on __SCHEMA__.github_rechte (geaendert_von) where geaendert_von is not null;

-- ---------- Trigger: nie für Laborprofile, Zeitpunkte von der Datenbank ----------
-- security invoker (Standard): wamo_core darf profiles lesen (0001). search_path leer, alle Namen voll qualifiziert.
create or replace function __SCHEMA__.github_zugang_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if not exists (select 1 from __SCHEMA__.profiles p where p.user_id = new.user_id and p.labor_art is null) then
    raise exception 'github_zugang: nur für Profile ohne labor_art' using errcode = '42501', constraint = 'github_zugang_guard';
  end if;
  if tg_op = 'INSERT' then
    new.angelegt_at := pg_catalog.now();
  elsif new.user_id is distinct from old.user_id then
    raise exception 'github_zugang: user_id ist unveränderlich' using errcode = '42501', constraint = 'github_zugang_guard';
  elsif new.token is distinct from old.token then
    new.angelegt_at := pg_catalog.now();  -- ein neues Token
  else
    new.angelegt_at := old.angelegt_at;
  end if;
  new.geprueft_at := pg_catalog.now();
  return new;
end $$;
revoke all on function __SCHEMA__.github_zugang_guard() from public, anon, authenticated, service_role, wamo_core, wamo_admin;
drop trigger if exists github_zugang_guard on __SCHEMA__.github_zugang;
create trigger github_zugang_guard before insert or update on __SCHEMA__.github_zugang
  for each row execute function __SCHEMA__.github_zugang_guard();

-- Die Datenbank kennt den Aufrufer nicht. Sie prüft, was sie sehen kann: das Zielprofil ist kein Laborprofil, und geaendert_von ist ein
-- aktiver Admin ohne labor_art (der Kern trägt dort die Kennung des Admins aus der geprüften Anmeldung ein).
create or replace function __SCHEMA__.github_rechte_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  -- Wird das Profil des Admins gelöscht, setzt der Fremdschlüssel geaendert_von auf null (on delete set null). Das ist ein UPDATE ohne
  -- neue Rechte: durchlassen, Zeitpunkt bleibt. Diese Prüfung steht zuerst, denn hat sich ein Admin selbst Rechte gegeben, kann das
  -- Profil beim Löschen schon unsichtbar sein (Cascade und Set null in beliebiger Reihenfolge). Jede andere Änderung braucht einen
  -- aktiven Admin. Die Datenbank kennt den Aufrufer nicht: geaendert_von setzt der Kern bei jedem Schreiben neu (_RECHTE_SETZEN).
  if tg_op = 'UPDATE' and new.user_id = old.user_id and new.geaendert_von is null and old.geaendert_von is not null
     and new.scopes_ausnahmen is not distinct from old.scopes_ausnahmen then
    new.geaendert_at := old.geaendert_at;
    return new;
  end if;
  if not exists (select 1 from __SCHEMA__.profiles p where p.user_id = new.user_id and p.labor_art is null) then
    raise exception 'github_rechte: nur für Profile ohne labor_art' using errcode = '42501', constraint = 'github_rechte_guard';
  end if;
  if tg_op = 'UPDATE' and new.user_id is distinct from old.user_id then
    raise exception 'github_rechte: user_id ist unveränderlich' using errcode = '42501', constraint = 'github_rechte_guard';
  end if;
  if new.geaendert_von is null or not exists (
       select 1 from __SCHEMA__.profiles a
        where a.user_id = new.geaendert_von and a.rolle = 'admin' and a.aktiv and a.labor_art is null) then
    raise exception 'github_rechte: ändern nur durch einen aktiven Admin' using errcode = '42501', constraint = 'github_rechte_guard';
  end if;
  new.geaendert_at := pg_catalog.now();
  return new;
end $$;
revoke all on function __SCHEMA__.github_rechte_guard() from public, anon, authenticated, service_role, wamo_core, wamo_admin;
drop trigger if exists github_rechte_guard on __SCHEMA__.github_rechte;
create trigger github_rechte_guard before insert or update on __SCHEMA__.github_rechte
  for each row execute function __SCHEMA__.github_rechte_guard();

-- ---------- Rechte (geringste Rechte) ----------
revoke all on __SCHEMA__.github_zugang, __SCHEMA__.github_rechte from public, anon, authenticated, service_role, wamo_admin, wamo_core;
do $$ begin
  -- wamo_release und wamo_anker gibt es erst ab 0013; fehlen sie, gibt es nichts zu entziehen
  if exists (select 1 from pg_roles where rolname = 'wamo_release') then
    execute 'revoke all on __SCHEMA__.github_zugang, __SCHEMA__.github_rechte from wamo_release';
  end if;
  if exists (select 1 from pg_roles where rolname = 'wamo_anker') then
    execute 'revoke all on __SCHEMA__.github_zugang, __SCHEMA__.github_rechte from wamo_anker';
  end if;
end $$;
grant select, delete on __SCHEMA__.github_zugang to wamo_core;
grant insert (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) on __SCHEMA__.github_zugang to wamo_core;
grant update (art, token, token_ende, login, konto_id, scopes, ablauf) on __SCHEMA__.github_zugang to wamo_core;
grant select (user_id, art, login, ablauf, geprueft_at) on __SCHEMA__.github_zugang to wamo_admin;
grant select on __SCHEMA__.github_rechte to wamo_core;
grant insert (user_id, scopes_ausnahmen, geaendert_von) on __SCHEMA__.github_rechte to wamo_core;
grant update (scopes_ausnahmen, geaendert_von) on __SCHEMA__.github_rechte to wamo_core;

-- ---------- Row Level Security ----------
alter table __SCHEMA__.github_zugang enable row level security;
drop policy if exists core_all on __SCHEMA__.github_zugang;
create policy core_all on __SCHEMA__.github_zugang for all to wamo_core using (true) with check (true);
-- wamo_admin liest nur die erlaubten Spalten (Spaltenrechte oben); die Zeilen sieht er über eine eigene Policy nur zum Lesen
drop policy if exists admin_lesen on __SCHEMA__.github_zugang;
create policy admin_lesen on __SCHEMA__.github_zugang for select to wamo_admin using (true);
alter table __SCHEMA__.github_rechte enable row level security;
drop policy if exists core_all on __SCHEMA__.github_rechte;
create policy core_all on __SCHEMA__.github_rechte for all to wamo_core using (true) with check (true);

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_table_privilege mit mehreren Rechten wäre schon bei
-- einem davon wahr).
do $$
declare
  recht text;
  rolle text;
  spalte text;
  tabelle text;
begin
  foreach recht in array array['SELECT', 'DELETE'] loop
    if not has_table_privilege('wamo_core', '__SCHEMA__.github_zugang', recht) then
      raise exception 'github_zugang (0027): wamo_core braucht %', recht using errcode = '42501';
    end if;
  end loop;
  foreach recht in array array['INSERT', 'UPDATE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
    if has_table_privilege('wamo_core', '__SCHEMA__.github_zugang', recht) then
      raise exception 'github_zugang (0027): wamo_core darf % auf der Tabelle nicht haben', recht using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['geprueft_at', 'angelegt_at'] loop
    if has_column_privilege('wamo_core', '__SCHEMA__.github_zugang', spalte, 'INSERT')
       or has_column_privilege('wamo_core', '__SCHEMA__.github_zugang', spalte, 'UPDATE') then
      raise exception 'github_zugang (0027): wamo_core darf % nicht selbst setzen', spalte using errcode = '42501';
    end if;
  end loop;
  if has_column_privilege('wamo_core', '__SCHEMA__.github_zugang', 'user_id', 'UPDATE') then
    raise exception 'github_zugang (0027): wamo_core darf user_id nicht ändern' using errcode = '42501';
  end if;
  foreach spalte in array array['token', 'token_ende', 'konto_id', 'scopes', 'angelegt_at'] loop
    if has_column_privilege('wamo_admin', '__SCHEMA__.github_zugang', spalte, 'SELECT') then
      raise exception 'github_zugang (0027): wamo_admin darf % nicht lesen', spalte using errcode = '42501';
    end if;
  end loop;
  if has_any_column_privilege('wamo_admin', '__SCHEMA__.github_zugang', 'INSERT,UPDATE,REFERENCES')
     or has_table_privilege('wamo_admin', '__SCHEMA__.github_zugang', 'DELETE') then
    raise exception 'github_zugang (0027): wamo_admin darf nur lesen' using errcode = '42501';
  end if;
  if not has_table_privilege('wamo_core', '__SCHEMA__.github_rechte', 'SELECT')
     or has_table_privilege('wamo_core', '__SCHEMA__.github_rechte', 'DELETE')
     or has_table_privilege('wamo_core', '__SCHEMA__.github_rechte', 'TRUNCATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.github_rechte', 'geaendert_at', 'INSERT')
     or has_column_privilege('wamo_core', '__SCHEMA__.github_rechte', 'geaendert_at', 'UPDATE')
     or not has_column_privilege('wamo_core', '__SCHEMA__.github_rechte', 'scopes_ausnahmen', 'UPDATE') then
    raise exception 'github_rechte (0027): Rechte von wamo_core stimmen nicht' using errcode = '42501';
  end if;
  if has_any_column_privilege('wamo_admin', '__SCHEMA__.github_rechte', 'SELECT,INSERT,UPDATE,REFERENCES')
     or has_table_privilege('wamo_admin', '__SCHEMA__.github_rechte', 'DELETE') then
    raise exception 'github_rechte (0027): wamo_admin darf keine Rechte haben' using errcode = '42501';
  end if;
  foreach rolle in array array['anon', 'authenticated', 'service_role', 'wamo_release', 'wamo_anker'] loop
    if not exists (select 1 from pg_roles where rolname = rolle) then continue; end if;
    foreach tabelle in array array['__SCHEMA__.github_zugang', '__SCHEMA__.github_rechte'] loop
      if has_any_column_privilege(rolle, tabelle, 'SELECT,INSERT,UPDATE,REFERENCES')
         or has_table_privilege(rolle, tabelle, 'DELETE')
         or has_table_privilege(rolle, tabelle, 'TRUNCATE')
         or has_table_privilege(rolle, tabelle, 'TRIGGER') then
        raise exception '% (0027): % darf keine Rechte haben', tabelle, rolle using errcode = '42501';
      end if;
    end loop;
  end loop;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'github_zugang' and policyname = 'admin_lesen'
                   and cmd = 'SELECT' and roles = array['wamo_admin']::name[]) then
    raise exception 'github_zugang (0027): Policy admin_lesen fehlt oder ist zu weit' using errcode = '42501';
  end if;
  foreach tabelle in array array['github_zugang', 'github_rechte'] loop
    if not (select c.relrowsecurity from pg_class c where c.oid = ('__SCHEMA__.' || tabelle)::regclass)
       or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = tabelle and policyname = 'core_all')
       or not exists (select 1 from pg_trigger where tgrelid = ('__SCHEMA__.' || tabelle)::regclass
                        and tgname = tabelle || '_guard' and not tgisinternal and tgenabled = 'O') then
      raise exception '% (0027): RLS, Policy core_all oder Trigger fehlt', tabelle using errcode = '42501';
    end if;
  end loop;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
     and (not has_table_privilege('wamo_core_s2', '__SCHEMA__.github_zugang', 'SELECT')
          or not has_column_privilege('wamo_core_s2', '__SCHEMA__.github_zugang', 'token', 'INSERT')
          or not has_column_privilege('wamo_core_s2', '__SCHEMA__.github_rechte', 'scopes_ausnahmen', 'INSERT')) then
    raise exception 'github_zugang (0027): wamo_core_s2 erbt die Rechte von wamo_core nicht' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0027_github_zugang') on conflict do nothing;
