-- Test für 0022_neue_mitglieder. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten in
-- auth.users, Profile, Faktoren, Modellzugang und Stimmabdruck verschwinden wieder). Nur für wamo_test oder wamo_dev.
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0022_neue_mitglieder_test.sql \
--     | ssh wamo-sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Voraussetzung: 0001, 0002, 0010, 0011, 0018 und 0022 sind im Schema angewendet.
-- Erfolg: letzte Zeile "0022 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0022_neue_mitglieder') then
    raise exception '0022 ist in __SCHEMA__ nicht angewendet';
  end if;
end $$;

grant wamo_core to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core;
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
grant execute on all functions in schema wamo_testhilfe to wamo_core;

-- Testkonten: Admin, Person A (Token und Schlüssel, Faktor, Abdruck), Person B (nur Hausmodelle), Laborprofil, inaktiver Admin
insert into auth.users (id, email, last_sign_in_at) values
  ('00000000-0000-4000-8000-0000000022a1', 'admin@wamo-test.invalid', now()),
  ('00000000-0000-4000-8000-0000000022b1', 'person-a@wamo-test.invalid', now() - interval '1 day'),
  ('00000000-0000-4000-8000-0000000022b2', 'person-b@wamo-test.invalid', null),
  ('00000000-0000-4000-8000-0000000022c1', 'labor@wamo-test.invalid', now()),
  ('00000000-0000-4000-8000-0000000022d1', 'inaktiv@wamo-test.invalid', null);
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000022a1', 'Admin Test', 'admin', true),
  ('00000000-0000-4000-8000-0000000022b1', 'Person A', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000022b2', 'Person B', 'mitglied', false),
  ('00000000-0000-4000-8000-0000000022d1', 'Admin Inaktiv', 'admin', false);
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv, labor_art, labor_platz) values
  ('00000000-0000-4000-8000-0000000022c1', 'Gast', 'mitglied', false, 'schaufenster', null);
insert into auth.mfa_factors (id, user_id, friendly_name, factor_type, status, created_at, updated_at) values
  (gen_random_uuid(), '00000000-0000-4000-8000-0000000022b1', 'Test', 'totp', 'verified', now(), now());
insert into __SCHEMA__.model_access (user_id, claude_schluessel, claude_schluessel_ende, claude_code_token, claude_code_token_ende,
                                     claude_code_token_at) values
  ('00000000-0000-4000-8000-0000000022b1', decode(repeat('00', 48), 'hex'), 'abcd', decode(repeat('00', 48), 'hex'), 'wxyz', now());
insert into __SCHEMA__.model_access (user_id, nur_haus) values ('00000000-0000-4000-8000-0000000022b2', true);
-- Person C: nur API-Schlüssel, ein unbestätigter TOTP-Faktor zählt nicht
insert into auth.users (id, email, last_sign_in_at) values ('00000000-0000-4000-8000-0000000022b3', 'person-c@wamo-test.invalid', now());
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values ('00000000-0000-4000-8000-0000000022b3', 'Person C', 'mitglied', true);
insert into auth.mfa_factors (id, user_id, friendly_name, factor_type, status, created_at, updated_at) values
  (gen_random_uuid(), '00000000-0000-4000-8000-0000000022b3', 'Test', 'totp', 'unverified', now(), now());
insert into __SCHEMA__.model_access (user_id, claude_schluessel, claude_schluessel_ende) values
  ('00000000-0000-4000-8000-0000000022b3', decode(repeat('00', 48), 'hex'), 'efgh');
insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version) values
  ('00000000-0000-4000-8000-0000000022b1', 'Person A', true, array_fill(0.1::real, array[192])::extensions.vector, now(), 'stimme-1');

-- 1. Form und Rechte
do $$
declare
  v_fn regprocedure := '__SCHEMA__.neue_mitglieder(uuid)'::regprocedure;
begin
  perform wamo_testhilfe.gleich((select p.prosecdef from pg_proc p where p.oid = v_fn), true, 'SECURITY DEFINER');
  perform wamo_testhilfe.gleich((select p.proconfig from pg_proc p where p.oid = v_fn), array['search_path=""'], 'leerer search_path');
  perform wamo_testhilfe.gleich(has_function_privilege('wamo_core', v_fn, 'EXECUTE'), true, 'wamo_core darf');
  perform wamo_testhilfe.gleich(has_function_privilege('anon', v_fn, 'EXECUTE'), false, 'anon nicht');
  perform wamo_testhilfe.gleich(has_function_privilege('authenticated', v_fn, 'EXECUTE'), false, 'authenticated nicht');
  perform wamo_testhilfe.gleich(has_function_privilege('service_role', v_fn, 'EXECUTE'), false, 'service_role nicht');
  perform wamo_testhilfe.gleich(has_function_privilege('wamo_admin', v_fn, 'EXECUTE'), false, 'wamo_admin nicht');
  perform wamo_testhilfe.gleich((select count(*) from pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                                  where p.oid = v_fn and a.grantee = 0), 0::bigint, 'PUBLIC nicht');
  -- genau diese Spalten, keine Geheimnisspalte
  perform wamo_testhilfe.gleich(
    (select array_agg(n order by o) from pg_proc p, unnest(p.proargnames, p.proargmodes) with ordinality as a(n, m, o)
      where p.oid = v_fn and m = 't'),
    array['user_id', 'anzeigename', 'rolle', 'aktiv', 'angelegt', 'letzte_anmeldung', 'faktor_bestaetigt', 'passwort_stand',
          'geraet_stand', 'modellzugang', 'stimmabdruck']::text[], 'Spalten exakt');
end $$;

-- 2. Inhalt als wamo_core mit einem aktiven Admin
set role wamo_core;
do $$
declare
  r record;
begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022a1')
                                  where user_id = '00000000-0000-4000-8000-0000000022c1'), 0::bigint, 'Laborprofil fehlt');
  select * into r from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022a1')
   where user_id = '00000000-0000-4000-8000-0000000022b1';
  perform wamo_testhilfe.gleich(r.anzeigename, 'Person A', 'Name');
  perform wamo_testhilfe.gleich(r.faktor_bestaetigt, true, 'Faktor bestätigt');
  perform wamo_testhilfe.gleich(r.modellzugang, 'token_und_schluessel', 'Token und Schlüssel');
  perform wamo_testhilfe.gleich(r.stimmabdruck, true, 'Stimmabdruck');
  perform wamo_testhilfe.gleich(r.geraet_stand, 'keins', 'kein Gerät');
  perform wamo_testhilfe.gleich(r.letzte_anmeldung is not null, true, 'letzte Anmeldung');
  select * into r from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022a1')
   where user_id = '00000000-0000-4000-8000-0000000022b2';
  perform wamo_testhilfe.gleich(r.faktor_bestaetigt, false, 'ohne Faktor');
  perform wamo_testhilfe.gleich(r.modellzugang, 'haus', 'nur Hausmodelle');
  perform wamo_testhilfe.gleich(r.stimmabdruck, false, 'ohne Abdruck');
  perform wamo_testhilfe.gleich(r.aktiv, false, 'gesperrtes Profil erscheint als gesperrt');
  perform wamo_testhilfe.gleich(r.letzte_anmeldung, null::date, 'nie angemeldet');
  select * into r from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022a1')
   where user_id = '00000000-0000-4000-8000-0000000022b3';
  perform wamo_testhilfe.gleich(r.modellzugang, 'schluessel', 'nur Schlüssel');
  perform wamo_testhilfe.gleich(r.faktor_bestaetigt, false, 'unbestätigter Faktor zählt nicht');
end $$;

-- 2b. Ältere Profile (vor mehr als 90 Tagen angelegt) erscheinen nicht
reset role;
update __SCHEMA__.profiles set created_at = now() - interval '100 days' where user_id = '00000000-0000-4000-8000-0000000022b2';
set role wamo_core;
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022a1')
                                  where user_id = '00000000-0000-4000-8000-0000000022b2'), 0::bigint, 'altes Profil fehlt');
end $$;

-- 3. Nur ein aktiver Admin ruft auf
select wamo_testhilfe.fehler($$select * from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022b1')$$, '42501');
select wamo_testhilfe.fehler($$select * from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022d1')$$, '42501');
select wamo_testhilfe.fehler($$select * from __SCHEMA__.neue_mitglieder('00000000-0000-4000-8000-0000000022c1')$$, '42501');
select wamo_testhilfe.fehler($$select * from __SCHEMA__.neue_mitglieder(null)$$, '42501');
-- wamo_core liest auth.users und auth.mfa_factors weiter nicht direkt
select wamo_testhilfe.fehler($$select count(*) from auth.users$$, '42501');
reset role;

-- 4. Passwortstand aus wamo_auth (P1a). Fehlt das Schema, legt der Test in der zurückgerollten Transaktion eine Attrappe an:
--    erst ohne Funktion (null), dann mit gültigem Wert, mit unbekanntem Wert (null), mit Fehler (null, kein Abbruch) und für PUBLIC
--    ausführbar (wird nicht aufgerufen).
do $$
declare
  v_admin constant uuid := '00000000-0000-4000-8000-0000000022a1';
  v_a     constant uuid := '00000000-0000-4000-8000-0000000022b1';
  stand   text;
begin
  if to_regprocedure('wamo_auth.erstanmeldung_stand(uuid)') is not null then
    select passwort_stand into stand from __SCHEMA__.neue_mitglieder(v_admin) where user_id = v_a;
    perform wamo_testhilfe.gleich(stand is null or stand in ('keine', 'offen', 'abgelaufen', 'erledigt'), true, 'echter Stand');
    return;
  end if;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.neue_mitglieder(v_admin) where passwort_stand is not null),
                                0::bigint, 'ohne wamo_auth kein Passwortstand');
  create schema wamo_auth;
  create function wamo_auth.erstanmeldung_stand(uuid) returns text language sql as $f$ select 'offen' $f$;
  revoke all on function wamo_auth.erstanmeldung_stand(uuid) from public;
  select passwort_stand into stand from __SCHEMA__.neue_mitglieder(v_admin) where user_id = v_a;
  perform wamo_testhilfe.gleich(stand, 'offen', 'Stand aus wamo_auth');
  create or replace function wamo_auth.erstanmeldung_stand(uuid) returns text language sql as $f$ select 'irgendwas' $f$;
  select passwort_stand into stand from __SCHEMA__.neue_mitglieder(v_admin) where user_id = v_a;
  perform wamo_testhilfe.gleich(stand, null::text, 'unbekannter Wert wird null');
  create or replace function wamo_auth.erstanmeldung_stand(uuid) returns text language plpgsql as $f$
    begin raise exception 'kaputt'; end $f$;
  select passwort_stand into stand from __SCHEMA__.neue_mitglieder(v_admin) where user_id = v_a;
  perform wamo_testhilfe.gleich(stand, null::text, 'Fehler in wamo_auth bricht nicht ab');
  create or replace function wamo_auth.erstanmeldung_stand(uuid) returns text language sql as $f$ select 'offen' $f$;
  grant execute on function wamo_auth.erstanmeldung_stand(uuid) to public;
  select passwort_stand into stand from __SCHEMA__.neue_mitglieder(v_admin) where user_id = v_a;
  perform wamo_testhilfe.gleich(stand, null::text, 'für PUBLIC ausführbare Fremdfunktion wird nicht gerufen');
end $$;

select '0022 OK';
rollback;
