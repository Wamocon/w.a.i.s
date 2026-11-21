-- WAMO 0032: Claude-Zugang des Testlabors (Entscheidung von Niko vom 21.11.2026: der Claude-Schlüssel für die Laborprofile soll im Admin-Panel
-- gesetzt werden können, statt in /etc/wamo/core.env zu stehen). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, ein zweiter Lauf ändert nichts):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0032_labor_zugang.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0032_labor_zugang.down.sql. Test: supabase/tests/0032_labor_zugang_test.sql. Hängt nur von 0001 ab (profiles, schema_migrations,
-- Rolle wamo_core). wamo_prod nur nach ausdrücklicher Freigabe und nach dem Agenten database-reviewer.
--
-- Was hier entsteht: eine Tabelle labor_zugang mit genau einer Zeile, dem Anthropic-API-Schlüssel, über den alle Laborprofile (Testlabor,
-- Gäste) ihr Gespräch führen. Bisher kam er aus ANTHROPIC_API_KEY in /etc/wamo/core.env; nun kann ein Admin ihn in der Werkstatt setzen,
-- prüfen und entfernen. Ist die Zeile leer oder fehlt sie, gilt wie bisher der Schlüssel des Servers, danach die Hausmodelle.
--
-- Spalten:
--   id                 immer true: die Tabelle hat höchstens eine Zeile
--   claude_schluessel  das Chiffrat des Kerns (voice-core/schluessel.py, AES-256-GCM, Hauptschlüssel WAMO_SCHLUESSEL_KEK nur beim Kern); die
--                      Datenbank sieht nie den Klartext. Gebunden an eine feste Kennung statt an ein Profil, ein Chiffrat aus model_access
--                      lässt sich hier nicht einsetzen und umgekehrt
--   claude_workspace   Workspace-ID (wrkspc_...), wenn der Schlüssel zu keinem Workspace gehört, sonst leer
--   endet_auf          die letzten vier Zeichen, für die Anzeige "endet auf ...abcd" (der einzige Teil, den die Oberfläche je sieht)
--   gesetzt_von        der Admin, der den Schlüssel gesetzt hat; wird sein Profil gelöscht, bleibt die Zeile (on delete set null)
--   gesetzt_am         Zeitpunkt des Setzens
--   geprueft_am        Zeitpunkt der Testanfrage bei Anthropic, die dem Speichern vorausging
--
-- Das ist Konfiguration, keine Gastdaten: Die Zeile gehört keinem Laborprofil, labor_loeschen berührt sie nie (voice-core/labor_loeschliste.py
-- führt die Tabelle in AUSNAHMEN, weil gesetzt_von auf profiles verweist). Laborprofile erreichen die Tabelle nicht, nur der Kern liest sie
-- beim Beginn einer Laborsitzung und höchstens alle 30 Sekunden je Prozess.
--
-- Rechte (CLAUDE.md): nur wamo_core (lesen, einfügen, ändern, löschen), keine Spaltenrechte nötig, die ganze Zeile gehört dem Kern. Nichts für
-- anon, authenticated, service_role, wamo_admin und wamo_werkstatt: Der Werkstatt-Dienst bleibt ohne Geheimnisse, die Oberfläche spricht für
-- diese Funktion mit dem Kern. Vor dem Vergeben wird auch wamo_core alles entzogen, damit ein Nachlauf nach geänderten Rechten zum selben
-- Stand führt.
set local lock_timeout = '5s';

do $$ begin
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0001_wamo_init') then
    raise exception '0032 braucht 0001';
  end if;
end $$;

-- ---------- Tabelle ----------
create table if not exists __SCHEMA__.labor_zugang (
  id                boolean primary key default true,
  claude_schluessel bytea not null,
  claude_workspace  text,
  endet_auf         text not null,
  gesetzt_von       uuid references __SCHEMA__.profiles(user_id) on delete set null,
  gesetzt_am        timestamptz not null default now(),
  geprueft_am       timestamptz,
  constraint labor_zugang_eine_zeile_chk check (id),
  constraint labor_zugang_schluessel_chk check (octet_length(claude_schluessel) between 40 and 1024),
  constraint labor_zugang_workspace_chk check (claude_workspace is null or claude_workspace ~ '^wrkspc_[A-Za-z0-9]{6,60}$'),
  constraint labor_zugang_endet_auf_chk check (endet_auf ~ '^[A-Za-z0-9_-]{4}$')
);
comment on table __SCHEMA__.labor_zugang is
  'Claude-Zugang des Testlabors: eine Zeile, der Schlüssel nur als Chiffrat des Kerns. Konfiguration, kein Gastdatum. Nur der Kern.';

-- ---------- Index ----------
-- Fremdschlüssel gesetzt_von (partiell, die Spalte ist optional)
create index if not exists labor_zugang_von_idx on __SCHEMA__.labor_zugang (gesetzt_von) where gesetzt_von is not null;

-- ---------- Rechte (geringste Rechte) ----------
revoke all on __SCHEMA__.labor_zugang from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant select, insert, update, delete on __SCHEMA__.labor_zugang to wamo_core;
do $$ begin
  -- wamo_werkstatt gibt es erst ab 0031 und je Cluster nur einmal: fehlt die Rolle, gibt es nichts zu entziehen
  if exists (select 1 from pg_roles where rolname = 'wamo_werkstatt') then
    execute 'revoke all on __SCHEMA__.labor_zugang from wamo_werkstatt';
  end if;
end $$;

-- ---------- Row Level Security ----------
alter table __SCHEMA__.labor_zugang enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_zugang;
create policy core_all on __SCHEMA__.labor_zugang for all to wamo_core using (true) with check (true);

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_table_privilege mit mehreren Rechten wäre schon bei
-- einem davon wahr).
do $$
declare
  recht text;
  rolle text;
begin
  foreach recht in array array['SELECT', 'INSERT', 'UPDATE', 'DELETE'] loop
    if not has_table_privilege('wamo_core', '__SCHEMA__.labor_zugang', recht) then
      raise exception 'labor_zugang (0032): wamo_core braucht % auf der Tabelle', recht using errcode = '42501';
    end if;
  end loop;
  foreach recht in array array['TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
    if has_table_privilege('wamo_core', '__SCHEMA__.labor_zugang', recht) then
      raise exception 'labor_zugang (0032): wamo_core darf % auf der Tabelle nicht haben', recht using errcode = '42501';
    end if;
  end loop;
  foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role', 'wamo_werkstatt'] loop
    -- fehlt die Rolle (wamo_werkstatt gibt es nur mit 0031), gibt es nichts zu prüfen
    if not exists (select 1 from pg_roles where rolname = rolle) then continue; end if;
    if has_any_column_privilege(rolle, '__SCHEMA__.labor_zugang', 'SELECT,INSERT,UPDATE,REFERENCES')
       or has_table_privilege(rolle, '__SCHEMA__.labor_zugang', 'DELETE')
       or has_table_privilege(rolle, '__SCHEMA__.labor_zugang', 'TRUNCATE')
       or has_table_privilege(rolle, '__SCHEMA__.labor_zugang', 'TRIGGER') then
      raise exception 'labor_zugang (0032): % darf keine Rechte haben', rolle using errcode = '42501';
    end if;
  end loop;
  if not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.labor_zugang'::regclass)
     or (select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'labor_zugang') <> 1
     or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'labor_zugang'
                      and policyname = 'core_all') then
    raise exception 'labor_zugang (0032): RLS oder Policy core_all fehlt' using errcode = '42501';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
     and (not has_table_privilege('wamo_core_s2', '__SCHEMA__.labor_zugang', 'SELECT')
          or not has_table_privilege('wamo_core_s2', '__SCHEMA__.labor_zugang', 'INSERT')) then
    raise exception 'labor_zugang (0032): wamo_core_s2 erbt die Rechte von wamo_core nicht' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0032_labor_zugang') on conflict do nothing;
