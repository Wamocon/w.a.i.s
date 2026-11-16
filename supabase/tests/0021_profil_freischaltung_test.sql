-- Test für 0021_profil_freischaltung. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird. Nur für wamo_test
-- oder wamo_dev. Wird von Hand ausgeführt, nicht von der CI:
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0021_profil_freischaltung_test.sql \
--     | ssh wamo-sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Voraussetzung: 0001 bis 0021 sind im Schema angewendet. Den Nachlauf (zweimal anwenden, runter, hoch) vorher von Hand.
-- Erfolg: letzte Zeile "0021 OK". Läuft mit und ohne wamo_auth: Fehlt das Schema, prüft der Test zuerst "fail closed" und legt dann in
-- der zurückgerollten Transaktion einen Ersatz der Tabelle an, damit auch der Weg mit Merker geprüft wird.
-- Geprüft wird (Planpapier Abschnitt 6.1, P1a):
--   1. Aktivieren ohne Merker scheitert (42501), auch über den Weg einer alten Kopie von anlegen (insert ... on conflict do update)
--   2. mit Merker (gleich welcher Stand) gelingt es, auch als wamo_admin
--   3. aktive Profile, Sperren, andere Spalten, neue Profile und Laborprofile sind unberührt
--   4. die neuen Hinweisarten sind erlaubt
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_admin to postgres;
create schema wamo_testhilfe21;
grant usage on schema wamo_testhilfe21 to wamo_core, wamo_admin;
create function wamo_testhilfe21.fehler(p_sql text, p_code text, p_text text default null) returns void language plpgsql as $f$
begin
  begin
    execute p_sql;
  exception when others then
    if sqlstate <> p_code then
      raise exception 'erwartet %, bekam % (%) bei: %', p_code, sqlstate, sqlerrm, p_sql;
    end if;
    if p_text is not null and position(p_text in sqlerrm) = 0 then
      raise exception 'erwartet eine Meldung mit "%", bekam "%" bei: %', p_text, sqlerrm, p_sql;
    end if;
    return;
  end;
  raise exception 'erwartet Fehler %, aber gelungen: %', p_code, p_sql;
end $f$;
create function wamo_testhilfe21.gleich(p_ist anyelement, p_soll anyelement, p_was text) returns void language plpgsql as $f$
begin
  if p_ist is distinct from p_soll then raise exception '%: ist %, soll %', p_was, p_ist, p_soll; end if;
end $f$;
grant execute on all functions in schema wamo_testhilfe21 to wamo_core, wamo_admin;

-- Testkonten: gesperrtes Mitglied M (wie die sieben neuen Konten), aktives Profil N (wie Niko), Laborprofil L, neues Konto Q
insert into auth.users (id, email, encrypted_password) values
  ('00000000-0000-4000-8000-0000000021a1', 'frei-m@wamo-test.invalid', 'h-m'),
  ('00000000-0000-4000-8000-0000000021a2', 'frei-n@wamo-test.invalid', 'h-n'),
  ('00000000-0000-4000-8000-0000000021a3', 'frei-l@wamo-test.invalid', 'h-l'),
  ('00000000-0000-4000-8000-0000000021a4', 'frei-q@wamo-test.invalid', 'h-q');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000021a1', 'Test M 0021', 'mitglied', false),
  ('00000000-0000-4000-8000-0000000021a2', 'Test N 0021', 'admin', true);

do $$ begin
  perform wamo_testhilfe21.gleich((select count(*)::int from pg_trigger where tgname = 'profiles_freischaltung_guard'
                                    and tgrelid = '__SCHEMA__.profiles'::regclass and tgenabled = 'O'), 1, 'Trigger aktiv');
  perform wamo_testhilfe21.gleich((select prosecdef from pg_proc where oid = '__SCHEMA__.profiles_freischaltung_guard()'::regprocedure),
                                  true, 'security definer');
  perform wamo_testhilfe21.gleich(has_function_privilege('anon', '__SCHEMA__.profiles_freischaltung_guard()', 'execute'), false,
                                  'anon execute');
end $$;

-- ---------- fail closed ohne wamo_auth, danach Ersatz der Tabelle (nur in dieser Transaktion) ----------
do $$ begin
  if to_regclass('wamo_auth.erstanmeldungen') is null then
    perform wamo_testhilfe21.fehler($q$update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a1'$q$,
                                    '42501', 'wamo_auth fehlt');
    create schema wamo_auth;
    create table wamo_auth.erstanmeldungen (user_id uuid primary key);
    raise notice 'wamo_auth fehlt: fail closed geprüft, Ersatz der Tabelle für den Rest des Tests';
  end if;
end $$;

-- Merker schreiben: über die echte Funktion, sonst in den Ersatz
create function wamo_testhilfe21.merker(p_user uuid) returns void language plpgsql as $f$
begin
  if to_regprocedure('wamo_auth.erstanmeldung_anlegen(uuid,integer,text,boolean)') is not null then
    perform wamo_auth.erstanmeldung_anlegen(p_user, 72, 'freischalten', false);
  else
    insert into wamo_auth.erstanmeldungen (user_id) values (p_user);
  end if;
end $f$;

-- ---------- 1. ohne Merker scheitert ----------
do $$ begin
  perform wamo_testhilfe21.fehler($q$update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a1'$q$,
                                  '42501', 'aktivieren nur mit Erstanmeldung');
  -- alte Kopie von anlegen
  perform wamo_testhilfe21.fehler($q$insert into __SCHEMA__.profiles (user_id, display_name, rolle, anrede, aktiv)
      values ('00000000-0000-4000-8000-0000000021a1', 'Test M 0021', 'mitglied', 'du', true)
      on conflict (user_id) do update set display_name = excluded.display_name, rolle = excluded.rolle, anrede = excluded.anrede,
      aktiv = true$q$, '42501', 'aktivieren nur mit Erstanmeldung');
  perform wamo_testhilfe21.gleich((select aktiv from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000021a1'), false,
                                  'bleibt gesperrt');
end $$;

-- als wamo_admin ebenso
set local role wamo_admin;
select wamo_testhilfe21.fehler($q$update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a1'$q$,
                               '42501', 'aktivieren nur mit Erstanmeldung');
reset role;

-- ---------- 3. unberührt: aktive Profile, Sperren, andere Spalten, neue Profile ----------
do $$ begin
  update __SCHEMA__.profiles set display_name = 'Test M 0021 neu' where user_id = '00000000-0000-4000-8000-0000000021a1';
  update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a2';   -- war schon aktiv
  update __SCHEMA__.profiles set aktiv = false where user_id = '00000000-0000-4000-8000-0000000021a2';  -- sperren geht immer
  perform wamo_testhilfe21.fehler($q$update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a2'$q$,
                                  '42501', 'aktivieren nur mit Erstanmeldung');   -- gesperrt ist gesperrt, auch für ein Admin-Profil
  insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv)
    values ('00000000-0000-4000-8000-0000000021a4', 'Test Q 0021', 'mitglied', true);   -- neues Profil: bewusst erlaubt
  -- Laborprofil: eigene Freischaltung über labor_aktiv, der Trigger greift nicht
  insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv, labor_art)
    values ('00000000-0000-4000-8000-0000000021a3', 'Test L 0021', 'mitglied', false, 'schaufenster');
  update __SCHEMA__.profiles set labor_aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a3';
  perform wamo_testhilfe21.gleich((select labor_aktiv from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000021a3'), true,
                                  'Labor freigeschaltet');
  perform wamo_testhilfe21.fehler($q$update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a3'$q$,
                                  '23514');   -- Laborprofile bleiben aktiv = false (0018), nicht wegen 0021
end $$;

-- ---------- 2. mit Merker gelingt es ----------
select wamo_testhilfe21.merker('00000000-0000-4000-8000-0000000021a1');
set local role wamo_admin;
update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a1';
reset role;
select wamo_testhilfe21.merker('00000000-0000-4000-8000-0000000021a2');
update __SCHEMA__.profiles set aktiv = true where user_id = '00000000-0000-4000-8000-0000000021a2';
do $$ begin
  perform wamo_testhilfe21.gleich((select count(*)::int from __SCHEMA__.profiles where aktiv
                                    and user_id in ('00000000-0000-4000-8000-0000000021a1', '00000000-0000-4000-8000-0000000021a2')), 2,
                                  'mit Merker aktiv');
end $$;

-- ---------- 4. neue Hinweisarten ----------
do $$ begin
  perform __SCHEMA__.hinweis_an_admins('erstanmeldung_begonnen', 'Test', 'Test', '00000000-0000-4000-8000-0000000021a1', '{}'::jsonb);
  perform __SCHEMA__.hinweis_an_admins('erstanmeldung_erledigt', 'Test', 'Test', '00000000-0000-4000-8000-0000000021a1', '{}'::jsonb);
  perform wamo_testhilfe21.gleich((select count(*)::int from __SCHEMA__.hinweise where empfaenger = '00000000-0000-4000-8000-0000000021a2'
                                    and art like 'erstanmeldung_%'), 2, 'Hinweise an das aktive Admin-Profil');
  perform wamo_testhilfe21.fehler($q$insert into __SCHEMA__.hinweise (empfaenger, art, titel, text)
      values ('00000000-0000-4000-8000-0000000021a2', 'erstanmeldung_unbekannt', 't', 't')$q$, '23514');
end $$;

select '0021 OK';
rollback;
