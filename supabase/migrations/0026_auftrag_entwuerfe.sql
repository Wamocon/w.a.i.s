-- WAMO 0026: Entwicklungsaufträge für später (Wunsch von Niko vom 18.11.2026: "Mache auch möglich ein Entwicklungsauftrag zu speichern für
-- später!"). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, ein zweiter Lauf ändert nichts):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0026_auftrag_entwuerfe.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0026_auftrag_entwuerfe.down.sql. Test: supabase/tests/0026_auftrag_entwuerfe_test.sql. Hängt nur von 0001 ab (profiles,
-- schema_migrations, Rollen wamo_core und wamo_admin); 0025 muss dafür nicht angewendet sein.
-- wamo_prod nur nach ausdrücklicher Freigabe und nach dem Agenten database-reviewer.
--
-- Was hier entsteht: Eine Tabelle auftrag_entwuerfe mit einer Zeile je gespeichertem Auftrag einer Person. Der Kern
-- (voice-core/auftrag_entwuerfe.py) schreibt sie, wenn die Person auf einer noch nicht gestarteten Auftragskarte "Für später speichern"
-- klickt oder W.A.I.S. darum bittet (Werkzeug entwicklung_speichern), liest sie für die Liste "Gespeicherte Aufträge" und für "Laden"
-- (der Kern legt daraus eine neue Karte an, mit allen Prüfungen von entwicklung_vorbereiten; gestartet wird nur per Klick) und löscht sie,
-- wenn die Person "Löschen" klickt. Gespeichert werden nur Projekt, Art, Repo, Auftragstext, Abnahmekriterien, Runden und Zeitlimit, nie
-- der Claude-Zugang der Person; Schlüssel und Token, die jemand in den Auftragstext geschrieben hat, ersetzt der Kern vorher
-- (auftrag_entwuerfe.geheimnisse_entfernen).
--
-- Besitzer: user_id verweist auf profiles(user_id), nicht auf auth.users (wie 0003, 0010, 0013, 0015 und 0017). Ein Fremdschlüssel auf
-- auth.users würde die Tabelle der Anmeldung sperren und GoTrue stauen. Wird ein Profil gelöscht, gehen seine Entwürfe mit. Der Kern
-- nimmt die user_id allein aus der geprüften Sitzung, und jede seiner Anfragen nennt sie, auch Laden und Löschen.
--
-- Grenzen: Projekt, Art und Repo in der Form, die der Kern beim Vorbereiten verlangt (dev_agent.PROJECT_NAME, REPO_RE; welche Art es gibt,
-- prüft der Kern beim Laden, damit eine neue Auftragsart keine Migration braucht), Auftragstext 1 bis 4000 Zeichen, höchstens 5 Kriterien
-- als JSON-Liste von Texten (zusammen höchstens 8192 Byte), Runden 1 bis 5, Zeitlimit 1 bis 60 Minuten. Höchstens 50 Entwürfe je Person:
-- Der Kern fügt nur unter der Grenze ein (insert ... select ... where count < 50), der Trigger auftrag_entwuerfe_grenze erzwingt sie
-- zusätzlich; eine Sperre je Person (pg_advisory_xact_lock) lässt zwei gleichzeitige Einfügungen nacheinander zählen.
--
-- Aufbewahrung 90 Tage: Ältere Entwürfe liest der Kern nie mehr (jede Abfrage filtert nach erstellt_at), zählen nicht zur Grenze und werden
-- vom Kern gelöscht (auftrag_entwuerfe.DatenbankEntwuerfe, höchstens einmal je Stunde und Prozess aus dem Weg der Liste, für alle
-- Profile). Die Tabelle bleibt klein (höchstens 50 Zeilen je Person); ein eigener Index auf erstellt_at lohnt nicht.
--
-- Rechte (CLAUDE.md): nur wamo_core. Lesen und Löschen auf der Tabelle, Einfügen nur in die Spalten, die der Kern liefert (id und
-- erstellt_at setzt die Datenbank, kein Rückdatieren). delete ist begründet: Die Person löscht ihre Entwürfe selbst, und der Kern räumt
-- nach 90 Tagen auf; der Kern löscht nur mit Kennung und user_id oder nach dem Alter. Kein update (ein Entwurf wird nie geändert, nur neu
-- gespeichert oder gelöscht), kein truncate. anon, authenticated, service_role und wamo_admin haben keine Rechte. Vor dem Vergeben wird
-- auch wamo_core alles entzogen, damit ein Nachlauf nach geänderten Rechten wieder zum selben Stand führt.
set local lock_timeout = '5s';

do $$ begin
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0001_wamo_init') then
    raise exception '0026 braucht 0001';
  end if;
end $$;

-- ---------- Tabelle ----------
create table if not exists __SCHEMA__.auftrag_entwuerfe (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references __SCHEMA__.profiles(user_id) on delete cascade,
  projekt       text not null,
  art           text not null,
  repo          text,
  auftrag       text not null,
  abnahme       jsonb not null default '[]'::jsonb,
  max_runden    smallint,
  zeitlimit_min smallint,
  erstellt_at   timestamptz not null default now(),
  constraint auftrag_entwuerfe_projekt_chk check (projekt ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'),
  constraint auftrag_entwuerfe_art_chk check (art ~ '^[a-z][a-z_]{1,29}$'),
  constraint auftrag_entwuerfe_repo_chk check (repo is null or (length(repo) <= 140
    and repo ~ '^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$')),
  constraint auftrag_entwuerfe_auftrag_chk check (length(auftrag) between 1 and 4000),
  -- case statt and: jsonb_array_length wirft bei einem Nicht-Array, und and hat in SQL keine feste Reihenfolge
  constraint auftrag_entwuerfe_abnahme_chk check (case when jsonb_typeof(abnahme) = 'array'
    then jsonb_array_length(abnahme) <= 5 and not jsonb_path_exists(abnahme, '$[*] ? (@.type() != "string")')
    else false end),
  constraint auftrag_entwuerfe_abnahme_groesse_chk check (pg_column_size(abnahme) <= 8192),
  constraint auftrag_entwuerfe_runden_chk check (max_runden is null or max_runden between 1 and 5),
  constraint auftrag_entwuerfe_zeitlimit_chk check (zeitlimit_min is null or zeitlimit_min between 1 and 60)
);
comment on table __SCHEMA__.auftrag_entwuerfe is
  'Für später gespeicherte Entwicklungsaufträge je Person (Projekt, Art, Repo, Text, Kriterien), nie ein Zugangswert. 90 Tage, höchstens 50 je Person, nur der Kern.';

-- ---------- Indizes ----------
-- Fremdschlüssel user_id und zugleich die Liste je Person (neueste zuerst)
create index if not exists auftrag_entwuerfe_user_idx on __SCHEMA__.auftrag_entwuerfe (user_id, erstellt_at desc);

-- ---------- Grenze je Person (Trigger) ----------
-- security invoker (Standard): Der Trigger zählt mit den Rechten dessen, der einfügt (nur wamo_core darf das, und er darf lesen). Gezählt
-- werden wie im Kern nur Entwürfe der letzten 90 Tage.
create or replace function __SCHEMA__.auftrag_entwuerfe_grenze() returns trigger
language plpgsql set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('__SCHEMA__.auftrag_entwuerfe:' || new.user_id::text, 0));
  if (select count(*) from __SCHEMA__.auftrag_entwuerfe e
        where e.user_id = new.user_id and e.erstellt_at >= pg_catalog.now() - interval '90 days') >= 50 then
    raise exception 'auftrag_entwuerfe: höchstens 50 Entwürfe je Person'
      using errcode = '23514', constraint = 'auftrag_entwuerfe_grenze';  -- der Kern erkennt die Grenze am Namen
  end if;
  return new;
end $$;
revoke all on function __SCHEMA__.auftrag_entwuerfe_grenze() from public, anon, authenticated, service_role, wamo_core, wamo_admin;
drop trigger if exists auftrag_entwuerfe_grenze on __SCHEMA__.auftrag_entwuerfe;
create trigger auftrag_entwuerfe_grenze before insert on __SCHEMA__.auftrag_entwuerfe
  for each row execute function __SCHEMA__.auftrag_entwuerfe_grenze();

-- ---------- Rechte (geringste Rechte) ----------
-- wamo_core zuerst entziehen, dann neu vergeben: auch ein Nachlauf nach geänderten Rechten (etwa Spaltenrechten) konvergiert.
revoke all on __SCHEMA__.auftrag_entwuerfe from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant select, delete on __SCHEMA__.auftrag_entwuerfe to wamo_core;
grant insert (user_id, projekt, art, repo, auftrag, abnahme, max_runden, zeitlimit_min) on __SCHEMA__.auftrag_entwuerfe to wamo_core;

-- ---------- Row Level Security ----------
alter table __SCHEMA__.auftrag_entwuerfe enable row level security;
drop policy if exists core_all on __SCHEMA__.auftrag_entwuerfe;
create policy core_all on __SCHEMA__.auftrag_entwuerfe for all to wamo_core using (true) with check (true);

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_table_privilege mit mehreren Rechten wäre schon bei
-- einem davon wahr).
do $$
declare
  recht text;
  rolle text;
  spalte text;
begin
  foreach recht in array array['SELECT', 'DELETE'] loop
    if not has_table_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', recht) then
      raise exception 'auftrag_entwuerfe (0026): wamo_core braucht %', recht using errcode = '42501';
    end if;
  end loop;
  foreach recht in array array['INSERT', 'UPDATE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
    if has_table_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', recht) then
      raise exception 'auftrag_entwuerfe (0026): wamo_core darf % auf der Tabelle nicht haben', recht using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['user_id', 'projekt', 'art', 'repo', 'auftrag', 'abnahme', 'max_runden', 'zeitlimit_min'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', spalte, 'INSERT') then
      raise exception 'auftrag_entwuerfe (0026): wamo_core braucht INSERT auf %', spalte using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['id', 'erstellt_at'] loop
    if has_column_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', spalte, 'INSERT') then
      raise exception 'auftrag_entwuerfe (0026): wamo_core darf % nicht selbst setzen', spalte using errcode = '42501';
    end if;
  end loop;
  if has_any_column_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', 'UPDATE') then
    raise exception 'auftrag_entwuerfe (0026): wamo_core darf nichts ändern' using errcode = '42501';
  end if;
  foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
    if has_any_column_privilege(rolle, '__SCHEMA__.auftrag_entwuerfe', 'SELECT,INSERT,UPDATE,REFERENCES')
       or has_table_privilege(rolle, '__SCHEMA__.auftrag_entwuerfe', 'DELETE')
       or has_table_privilege(rolle, '__SCHEMA__.auftrag_entwuerfe', 'TRUNCATE')
       or has_table_privilege(rolle, '__SCHEMA__.auftrag_entwuerfe', 'TRIGGER') then
      raise exception 'auftrag_entwuerfe (0026): % darf keine Rechte haben', rolle using errcode = '42501';
    end if;
  end loop;
  if not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.auftrag_entwuerfe'::regclass)
     or (select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'auftrag_entwuerfe') <> 1
     or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'auftrag_entwuerfe'
                      and policyname = 'core_all')
  then
    raise exception 'auftrag_entwuerfe (0026): RLS oder Policy core_all fehlt' using errcode = '42501';
  end if;
  if not exists (select 1 from pg_trigger where tgrelid = '__SCHEMA__.auftrag_entwuerfe'::regclass
                   and tgname = 'auftrag_entwuerfe_grenze' and not tgisinternal and tgenabled = 'O') then
    raise exception 'auftrag_entwuerfe (0026): Trigger der Grenze fehlt' using errcode = '42501';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
     and (not has_table_privilege('wamo_core_s2', '__SCHEMA__.auftrag_entwuerfe', 'SELECT')
          or not has_table_privilege('wamo_core_s2', '__SCHEMA__.auftrag_entwuerfe', 'DELETE')
          or not has_column_privilege('wamo_core_s2', '__SCHEMA__.auftrag_entwuerfe', 'auftrag', 'INSERT')) then
    raise exception 'auftrag_entwuerfe (0026): wamo_core_s2 erbt die Rechte von wamo_core nicht' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0026_auftrag_entwuerfe') on conflict do nothing;
