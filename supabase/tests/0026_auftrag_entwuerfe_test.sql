-- Test für 0026_auftrag_entwuerfe. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile und
-- Entwürfe verschwinden wieder). Nur für wamo_test oder wamo_dev. Wird von Hand ausgeführt, nicht von der CI:
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0026_auftrag_entwuerfe_test.sql \
--     | ssh wamo-sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Voraussetzung: 0001 und 0026 sind im Schema angewendet.
-- Der Nachlauf der Migration (zweimal anwenden, der zweite Lauf ändert nichts) ist NICHT Teil dieses Tests: Wer ihn prüfen will, wendet
-- 0026_auftrag_entwuerfe.sql vorher zweimal nacheinander an (Aufruf im Kopf der Migration); der zweite Lauf muss ohne Fehler durchgehen.
-- Erfolg: letzte Zeile "0026 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
-- Die Anweisungen des Kerns (Einfügen, Liste, Holen, Löschen, Aufräumen aus voice-core/auftrag_entwuerfe.py) stehen hier wörtlich, die
-- Platzhalter $n durch Werte ersetzt; voice-core/test_migration_0026.py prüft, dass sie mit denen des Kerns übereinstimmen. Aufräumen wirkt
-- auf das ganze Schema, die Ergebnisse werden deshalb nur an eigenen Kennungen geprüft; echte Zeilen bleiben unberührt (Rollback).
-- Zwei gleichzeitige Einfügungen lassen sich in einer Sitzung nicht nachstellen; geprüft wird, dass der Trigger die Sperre je Person hält.
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_core, wamo_admin to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- erwartet einen Fehler mit genau diesem SQLSTATE
create function wamo_testhilfe.fehler(p_sql text, p_code text) returns void language plpgsql as $f$
begin
  begin
    execute p_sql;
  exception when others then
    if sqlstate <> p_code then
      raise exception 'erwartet %, bekam % (%) bei: %', p_code, sqlstate, sqlerrm, p_sql;
    end if;
    return;
  end;
  raise exception 'erwartet Fehler %, aber gelungen: %', p_code, p_sql;
end $f$;
create function wamo_testhilfe.gleich(p_ist anyelement, p_soll anyelement, p_was text) returns void language plpgsql as $f$
begin
  if p_ist is distinct from p_soll then raise exception '%: ist %, soll %', p_was, p_ist, p_soll; end if;
end $f$;
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre
-- wirklich an den Tabellenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

-- Testkonten mit Profilen (user_id verweist auf profiles)
insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000026a1', 'entwurf-eins@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000026a2', 'entwurf-zwei@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000026a3', 'entwurf-drei@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name) values
  ('00000000-0000-4000-8000-0000000026a1', 'Entwurf Eins'),
  ('00000000-0000-4000-8000-0000000026a2', 'Entwurf Zwei'),
  ('00000000-0000-4000-8000-0000000026a3', 'Entwurf Drei');

-- 1. Migration eingetragen, Tabelle mit Zeilensicherheit und Policy core_all, Index, Fremdschlüssel, Prüfungen, Trigger
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations where version = '0026_auftrag_entwuerfe'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.auftrag_entwuerfe'::regclass), true, 'RLS an (relrowsecurity)');
  perform wamo_testhilfe.gleich((select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'auftrag_entwuerfe' and policyname = 'core_all'), 1::bigint, 'Policy core_all');
  perform wamo_testhilfe.gleich((select count(*) from pg_indexes where schemaname = '__SCHEMA__' and tablename = 'auftrag_entwuerfe'
                                   and indexname = 'auftrag_entwuerfe_user_idx'), 1::bigint, 'Index für den Fremdschlüssel');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.auftrag_entwuerfe'::regclass
                                   and contype = 'f' and confrelid = '__SCHEMA__.profiles'::regclass), 1::bigint, 'Fremdschlüssel user_id auf profiles');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.auftrag_entwuerfe'::regclass
                                   and confrelid = 'auth.users'::regclass), 0::bigint, 'kein Fremdschlüssel auf auth.users');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.auftrag_entwuerfe'::regclass
                                   and contype = 'c' and convalidated and conname like 'auftrag_entwuerfe_%_chk'), 8::bigint, 'acht Prüfungen');
  perform wamo_testhilfe.gleich((select count(*) from pg_trigger where tgrelid = '__SCHEMA__.auftrag_entwuerfe'::regclass
                                   and tgname = 'auftrag_entwuerfe_grenze' and not tgisinternal), 1::bigint, 'Trigger der Grenze');
  perform wamo_testhilfe.gleich(has_function_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe_grenze()', 'EXECUTE'), false,
                                'Triggerfunktion nicht direkt aufrufbar');
end $$;

-- 2. wamo_core: die Anweisungen des Kerns. Einfügen unter der Grenze, Liste, Holen, Löschen nur mit Kennung und Profil
set role wamo_core;
with neu as (
  insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag, abnahme, max_runden, zeitlimit_min)
  select '00000000-0000-4000-8000-0000000026a1'::uuid, 'rezepte-app', 'umsetzung', 'acme/rezepte-app', 'Baue die Rezepte-App',
         '["Die README erklärt die Installation"]'::text::jsonb, 4::smallint, 20::smallint
  where (select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'::uuid and erstellt_at >= now() - interval '90 days') < 50
  returning id::text
)
select wamo_testhilfe.gleich((select count(*) from neu), 1::bigint, 'Einfügen des Kerns legt eine Zeile an');
-- ohne Repo, Kriterien, Runden und Zeitlimit (Recherche)
with neu as (
  insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag, abnahme, max_runden, zeitlimit_min)
  select '00000000-0000-4000-8000-0000000026a1'::uuid, 'marktanalyse', 'recherche', null, 'Recherchiere den Markt', '[]'::text::jsonb,
         null::smallint, null::smallint
  where (select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'::uuid and erstellt_at >= now() - interval '90 days') < 50
  returning id::text
)
select wamo_testhilfe.gleich((select count(*) from neu), 1::bigint, 'Entwurf ohne Repo und Kriterien');
-- Liste: nur eigene, neueste zuerst
select wamo_testhilfe.gleich((select count(*) from (
  select id::text as id, projekt, art, repo, left(auftrag, 400) as anfang, erstellt_at from __SCHEMA__.auftrag_entwuerfe
  where user_id = '00000000-0000-4000-8000-0000000026a1'::uuid and erstellt_at >= now() - interval '90 days' order by erstellt_at desc limit 50
) l), 2::bigint, 'Liste der eigenen Entwürfe');
select wamo_testhilfe.gleich((select count(*) from (
  select id::text as id, projekt, art, repo, left(auftrag, 400) as anfang, erstellt_at from __SCHEMA__.auftrag_entwuerfe
  where user_id = '00000000-0000-4000-8000-0000000026a2'::uuid and erstellt_at >= now() - interval '90 days' order by erstellt_at desc limit 50
) l), 0::bigint, 'ein anderes Profil sieht nichts');
reset role;
-- feste Kennungen für Holen und Löschen (id setzt sonst die Datenbank, wamo_core darf sie nicht wählen)
insert into __SCHEMA__.auftrag_entwuerfe (id, user_id, projekt, art, auftrag, abnahme) values
  ('00000000-0000-4000-8000-0000000026c1', '00000000-0000-4000-8000-0000000026a2', 'zwei-app', 'analyse', 'Prüfe die App',
   '["Die Tests laufen"]');
set role wamo_core;
select wamo_testhilfe.gleich((
  select abnahme::text from (
    select projekt, art, repo, auftrag, abnahme::text as abnahme, max_runden, zeitlimit_min from __SCHEMA__.auftrag_entwuerfe
    where id = '00000000-0000-4000-8000-0000000026c1'::uuid and user_id = '00000000-0000-4000-8000-0000000026a2'::uuid and erstellt_at >= now() - interval '90 days'
  ) h), '["Die Tests laufen"]', 'Holen des eigenen Entwurfs');
select wamo_testhilfe.gleich((select count(*) from (
    select projekt, art, repo, auftrag, abnahme::text as abnahme, max_runden, zeitlimit_min from __SCHEMA__.auftrag_entwuerfe
    where id = '00000000-0000-4000-8000-0000000026c1'::uuid and user_id = '00000000-0000-4000-8000-0000000026a1'::uuid and erstellt_at >= now() - interval '90 days'
  ) h), 0::bigint, 'ein fremder Entwurf ist nicht zu holen');
-- Löschen mit dem falschen Profil trifft nichts, mit dem richtigen genau die eine Zeile
with weg as (delete from __SCHEMA__.auftrag_entwuerfe where id = '00000000-0000-4000-8000-0000000026c1'::uuid and user_id = '00000000-0000-4000-8000-0000000026a1'::uuid returning 1)
select wamo_testhilfe.gleich((select count(*) from weg), 0::bigint, 'fremden Entwurf nicht gelöscht');
with weg as (delete from __SCHEMA__.auftrag_entwuerfe where id = '00000000-0000-4000-8000-0000000026c1'::uuid and user_id = '00000000-0000-4000-8000-0000000026a2'::uuid returning 1)
select wamo_testhilfe.gleich((select count(*) from weg), 1::bigint, 'eigenen Entwurf gelöscht');
-- nicht erlaubt: ändern, leeren, Kennung oder Zeitpunkt selbst setzen
select wamo_testhilfe.fehler($s$update __SCHEMA__.auftrag_entwuerfe set auftrag = 'anders'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.auftrag_entwuerfe set user_id = '00000000-0000-4000-8000-0000000026a2'$s$, '42501');
select wamo_testhilfe.fehler($s$truncate __SCHEMA__.auftrag_entwuerfe$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (id, user_id, projekt, art, auftrag) values (gen_random_uuid(), '00000000-0000-4000-8000-0000000026a1', 'neu-app', 'analyse', 'T')$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, erstellt_at) values ('00000000-0000-4000-8000-0000000026a1', 'neu-app', 'analyse', 'T', now() - interval '1 year')$s$, '42501');
reset role;

-- 3. Prüfungen der Werte (als wamo_core, wie der Kern einfügt)
set role wamo_core;
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'Rezepte App', 'analyse', 'T')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'ab', 'analyse', 'T')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'Analyse!', 'T')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'kein-repo', 'T')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'acme/' || repeat('x', 136), 'T')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', '')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', repeat('x', 4001))$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, abnahme) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', '{"x": 1}')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, abnahme) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', '["a","b","c","d","e","f"]')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, abnahme) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', '["a", 1]')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, abnahme) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', jsonb_build_array(repeat(md5('a'), 300)))$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, max_runden) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', 0)$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, max_runden) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', 6)$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, zeitlimit_min) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T', 61)$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values (gen_random_uuid(), 'neu-app', 'analyse', 'T')$s$, '23503');
-- die Obergrenzen des Kerns passen: 4000 Zeichen zu je 4 Byte, fünf Kriterien zu je 300 Zeichen zu je 4 Byte
insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, abnahme, max_runden, zeitlimit_min) values
  ('00000000-0000-4000-8000-0000000026a3', 'gross-app', 'analyse', repeat(chr(128512), 4000),
   jsonb_build_array(repeat(chr(128512), 300), repeat(chr(128513), 300), repeat(chr(128514), 300), repeat(chr(128515), 300),
                     repeat(chr(128516), 300)), 5, 60);
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a3'),
                             1::bigint, 'größter Entwurf des Kerns gespeichert');
reset role;

-- 4. Grenze: höchstens 50 junge Entwürfe je Person. Das Einfügen des Kerns legt dann nichts mehr an, jedes andere Einfügen scheitert am
-- Trigger; alte Entwürfe (über 90 Tage) zählen nicht
set role wamo_core;
insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag)
  select '00000000-0000-4000-8000-0000000026a1', 'p-' || g, 'analyse', 'Entwurf ' || g from generate_series(1, 48) g;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'),
                             50::bigint, 'fünfzig Entwürfe');
with neu as (
  insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag, abnahme, max_runden, zeitlimit_min)
  select '00000000-0000-4000-8000-0000000026a1'::uuid, 'zu-viel', 'analyse', null, 'Einer zu viel', '[]'::text::jsonb, null::smallint, null::smallint
  where (select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'::uuid and erstellt_at >= now() - interval '90 days') < 50
  returning id::text
)
select wamo_testhilfe.gleich((select count(*) from neu), 0::bigint, 'das Einfügen des Kerns legt über der Grenze nichts an');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a1', 'zu-viel', 'analyse', 'T')$s$, '23514');
-- auch in einer einzigen Anweisung mit vielen Zeilen: der Trigger sieht die Zeilen davor (das dritte Profil hat schon einen Entwurf)
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) select '00000000-0000-4000-8000-0000000026a3', 'm-' || g, 'analyse', 'M' from generate_series(1, 50) g$s$, '23514');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a3'),
                             1::bigint, 'die abgewiesene Anweisung legt nichts an');
reset role;
-- auch postgres hält die Grenze ein, und der Fehler nennt sie mit Namen (der Kern meldet dann "voll" statt eines Datenbankfehlers)
do $$
declare
  v_name text;
begin
  begin
    insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a1', 'zu-viel', 'analyse', 'T');
    raise exception 'erwartet 23514 an der Grenze';
  exception when check_violation then
    get stacked diagnostics v_name = constraint_name;
    perform wamo_testhilfe.gleich(v_name, 'auftrag_entwuerfe_grenze', 'Name der Grenze im Fehler');
  end;
end $$;
-- alte Entwürfe (nur postgres kann rückdatieren) zählen nicht zur Grenze und erscheinen in keiner Abfrage des Kerns
insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag, erstellt_at)
  select '00000000-0000-4000-8000-0000000026a2', 'alt-' || g, 'analyse', 'Alt ' || g, now() - interval '100 days' from generate_series(1, 50) g;
set role wamo_core;
with neu as (
  insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, repo, auftrag, abnahme, max_runden, zeitlimit_min)
  select '00000000-0000-4000-8000-0000000026a2'::uuid, 'jung-app', 'analyse', null, 'Jung', '[]'::text::jsonb, null::smallint, null::smallint
  where (select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a2'::uuid and erstellt_at >= now() - interval '90 days') < 50
  returning id::text
)
select wamo_testhilfe.gleich((select count(*) from neu), 1::bigint, 'alte Entwürfe zählen nicht zur Grenze');
-- die Sperre je Person (pg_advisory_xact_lock im Trigger) gilt bis zum Ende der Transaktion: zwei gleichzeitige Einfügungen zählen nacheinander
select wamo_testhilfe.gleich((select count(*) from pg_locks where locktype = 'advisory' and pid = pg_backend_pid()
                                and ((classid::bigint << 32) | objid::bigint)
                                    = hashtextextended('__SCHEMA__.auftrag_entwuerfe:00000000-0000-4000-8000-0000000026a2', 0)),
                             1::bigint, 'Sperre je Person bis zum Ende der Transaktion');
select wamo_testhilfe.gleich((select count(*) from (
  select id::text as id, projekt, art, repo, left(auftrag, 400) as anfang, erstellt_at from __SCHEMA__.auftrag_entwuerfe
  where user_id = '00000000-0000-4000-8000-0000000026a2'::uuid and erstellt_at >= now() - interval '90 days' order by erstellt_at desc limit 50
) l), 1::bigint, 'alte Entwürfe stehen nicht in der Liste');

-- 5. Aufräumen des Kerns: löscht nur Entwürfe über 90 Tage, auch die anderer Profile
delete from __SCHEMA__.auftrag_entwuerfe where erstellt_at < now() - interval '90 days';
reset role;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a2'),
                             1::bigint, 'nur der junge Entwurf bleibt');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'),
                             50::bigint, 'junge Entwürfe des anderen Profils bleiben');

-- 6. Keine anderen Rollen: weder lesen noch schreiben noch löschen
set role wamo_admin;
select wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T')$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.auftrag_entwuerfe (user_id, projekt, art, auftrag) values ('00000000-0000-4000-8000-0000000026a3', 'neu-app', 'analyse', 'T')$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.auftrag_entwuerfe$s$, '42501');
reset role;

-- 7. Fremdschlüssel: Konto oder Profil weg nimmt die Entwürfe mit, die der anderen bleiben
delete from auth.users where id = '00000000-0000-4000-8000-0000000026a2';
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a2'), 0::bigint, 'Entwürfe des gelöschten Kontos entfernt');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a1'), 50::bigint, 'Entwürfe des anderen Kontos bleiben');
end $$;
delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000026a3';
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.auftrag_entwuerfe where user_id = '00000000-0000-4000-8000-0000000026a3'), 0::bigint, 'Entwürfe des gelöschten Profils entfernt');
end $$;

-- 8. Rechte als Zahlen: lesen und löschen auf der Tabelle, einfügen in genau acht Spalten, nichts ändern
do $$ begin
  perform wamo_testhilfe.gleich(has_table_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', 'SELECT')
                                and has_table_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', 'DELETE'), true, 'lesen und löschen');
  perform wamo_testhilfe.gleich(has_table_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', 'INSERT,UPDATE,TRUNCATE,REFERENCES,TRIGGER'),
                                false, 'kein weiteres Tabellenrecht');
  perform wamo_testhilfe.gleich((select count(*) from information_schema.columns c
                                   where c.table_schema = '__SCHEMA__' and c.table_name = 'auftrag_entwuerfe'
                                     and has_column_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', c.column_name, 'INSERT')), 8::bigint,
                                'acht Spalten zum Einfügen');
  perform wamo_testhilfe.gleich(has_any_column_privilege('wamo_core', '__SCHEMA__.auftrag_entwuerfe', 'UPDATE'), false, 'keine Spalte änderbar');
  perform wamo_testhilfe.gleich(has_any_column_privilege('wamo_admin', '__SCHEMA__.auftrag_entwuerfe', 'SELECT,INSERT,UPDATE'), false, 'wamo_admin ohne Rechte');
end $$;

rollback;
\echo 0026 OK
