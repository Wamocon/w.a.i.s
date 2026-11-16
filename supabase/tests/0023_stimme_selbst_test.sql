-- Test für 0023_stimme_selbst. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten,
-- Profile und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0023.
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0023_stimme_selbst_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0023 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_core, wamo_admin to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
create function wamo_testhilfe.fehler(p_sql text, p_code text) returns void
language plpgsql as $f$
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
-- wirklich an den Spaltenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000023a1', 'stimme1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000023a2', 'stimme2@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000023a3', 'stimme3@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000023a1', 'Stimme Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000023a2', 'Stimme Zwei', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000023a3', 'Stimme Drei', 'mitglied', true);
-- Profil Drei: vom Admin auf Hausmodelle festgelegt (als postgres angelegt, wie über wamo_admin.py)
insert into __SCHEMA__.model_access (user_id, nur_haus) values ('00000000-0000-4000-8000-0000000023a3', true);

-- 1. Migration eingetragen
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations
                                  where version = '0023_stimme_selbst'), 1::bigint, 'Migration eingetragen');
end $$;

-- 2. Der Kern setzt Hören und Stimme (neue Zeile und vorhandene Zeile, wie modellzugang.stimme_setzen), nur soniox oder haus
set role wamo_core;
do $$ begin
  insert into __SCHEMA__.model_access (user_id, stt, tts) values ('00000000-0000-4000-8000-0000000023a1', 'haus', 'haus')
    on conflict (user_id) do update set stt = excluded.stt, tts = excluded.tts;
  perform wamo_testhilfe.gleich((select stt || '/' || tts from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000023a1'), 'haus/haus', 'neue Zeile');
  insert into __SCHEMA__.model_access (user_id, stt, tts) values ('00000000-0000-4000-8000-0000000023a1', 'soniox', 'haus')
    on conflict (user_id) do update set stt = excluded.stt, tts = excluded.tts;
  perform wamo_testhilfe.gleich((select stt || '/' || tts from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000023a1'), 'soniox/haus', 'vorhandene Zeile');
  -- die Standardwerte einer Zeile ohne Wahl
  insert into __SCHEMA__.model_access (user_id) values ('00000000-0000-4000-8000-0000000023a2');
  perform wamo_testhilfe.gleich((select stt || '/' || tts from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000023a2'), 'soniox/soniox', 'Standard');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set stt = 'cloud'
    where user_id = '00000000-0000-4000-8000-0000000023a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts = null
    where user_id = '00000000-0000-4000-8000-0000000023a1'$s$, '23502');
  -- alles andere bleibt wie vor 0023: kein nur_haus, kein Modell, kein Löschen
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set nur_haus = true
    where user_id = '00000000-0000-4000-8000-0000000023a1'$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set claude_modell = 'claude-sonnet-5-5'
    where user_id = '00000000-0000-4000-8000-0000000023a1'$s$, '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.model_access
    where user_id = '00000000-0000-4000-8000-0000000023a1'$s$, '42501');
  -- der gefährlichste Weg: nur_haus über den Upsert des Kerns
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.model_access (user_id, nur_haus)
    values ('00000000-0000-4000-8000-0000000023a1', false)
    on conflict (user_id) do update set nur_haus = excluded.nur_haus$s$, '42501');
  -- Zwang des Admins: Hören und Stimme bleiben wählbar, nur_haus bleibt stehen
  insert into __SCHEMA__.model_access (user_id, stt, tts) values ('00000000-0000-4000-8000-0000000023a3', 'haus', 'haus')
    on conflict (user_id) do update set stt = excluded.stt, tts = excluded.tts;
  perform wamo_testhilfe.gleich((select nur_haus::text || '/' || stt || '/' || tts from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000023a3'), 'true/haus/haus', 'Zwang bleibt');
end $$;
reset role;

-- 2b. Zweiter Lauf der Rechte ändert nichts
grant insert (stt, tts) on __SCHEMA__.model_access to wamo_core;
grant update (stt, tts) on __SCHEMA__.model_access to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'stt', 'UPDATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'nur_haus', 'UPDATE') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

-- 3. Die Verwaltung setzt weiter wie bisher (Rechte aus 0010 unverändert)
set role wamo_admin;
do $$ begin
  update __SCHEMA__.model_access set stt = 'haus' where user_id = '00000000-0000-4000-8000-0000000023a2';
  perform wamo_testhilfe.gleich((select stt from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000023a2'), 'haus', 'Verwaltung');
end $$;
reset role;

-- 4. Fremde Rollen schreiben nichts (mit usage auf dem Schema, also an den Spaltenrechten gescheitert)
set role anon;
select wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set stt = 'haus'$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts = 'haus'$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.model_access (user_id, stt) values
  ('00000000-0000-4000-8000-0000000023a2', 'haus')$s$, '42501');
reset role;

rollback;
\echo 0023 OK
