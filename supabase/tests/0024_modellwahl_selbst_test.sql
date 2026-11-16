-- Test für 0024_modellwahl_selbst. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten,
-- Profile und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0024.
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0024_modellwahl_selbst_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0024 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
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
  ('00000000-0000-4000-8000-0000000024a1', 'wahl1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000024a2', 'wahl2@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000024a3', 'wahl3@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000024a1', 'Wahl Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000024a2', 'Wahl Zwei', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000024a3', 'Wahl Drei', 'mitglied', true);
-- Profil Drei: vom Admin auf Hausmodelle festgelegt, mit Claude-Modell (als postgres angelegt, wie über wamo_admin.py)
insert into __SCHEMA__.model_access (user_id, nur_haus, claude_modell)
  values ('00000000-0000-4000-8000-0000000024a3', true, 'claude-haiku-5-5');

-- 1. Migration eingetragen, Spalten ohne Vorgabe (NULL heißt automatisch), Bestand unverändert
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations
                                  where version = '0024_modellwahl_selbst'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select count(*) from information_schema.columns
                                  where table_schema = '__SCHEMA__' and table_name = 'model_access'
                                    and column_name in ('modell_gespraech', 'modell_bilder', 'modell_hintergrund', 'tts_stimme')
                                    and is_nullable = 'YES' and column_default is null), 4::bigint, 'vier Spalten, nullbar');
  perform wamo_testhilfe.gleich((select coalesce(modell_gespraech, 'automatisch') from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000024a3'), 'automatisch', 'Bestand');
end $$;

-- 2. Der Kern setzt die Wahl (neue Zeile und vorhandene Zeile, wie modellzugang._spalte_schreiben), nur in der erlaubten Form
set role wamo_core;
do $$ begin
  insert into __SCHEMA__.model_access (user_id, modell_gespraech) values ('00000000-0000-4000-8000-0000000024a1', 'gemma4-31b')
    on conflict (user_id) do update set modell_gespraech = excluded.modell_gespraech;
  insert into __SCHEMA__.model_access (user_id, modell_bilder) values ('00000000-0000-4000-8000-0000000024a1', 'claude-sonnet-5-5')
    on conflict (user_id) do update set modell_bilder = excluded.modell_bilder;
  insert into __SCHEMA__.model_access (user_id, modell_hintergrund) values ('00000000-0000-4000-8000-0000000024a1', 'qwen3.6-35b')
    on conflict (user_id) do update set modell_hintergrund = excluded.modell_hintergrund;
  insert into __SCHEMA__.model_access (user_id, tts_stimme) values ('00000000-0000-4000-8000-0000000024a1', 'uncle_fu')
    on conflict (user_id) do update set tts_stimme = excluded.tts_stimme;
  perform wamo_testhilfe.gleich((select modell_gespraech || '/' || modell_bilder || '/' || modell_hintergrund || '/' || tts_stimme
                                  from __SCHEMA__.model_access where user_id = '00000000-0000-4000-8000-0000000024a1'),
                                'gemma4-31b/claude-sonnet-5-5/qwen3.6-35b/uncle_fu', 'Wahl gespeichert');
  -- zurück auf automatisch
  insert into __SCHEMA__.model_access (user_id, modell_gespraech) values ('00000000-0000-4000-8000-0000000024a1', null)
    on conflict (user_id) do update set modell_gespraech = excluded.modell_gespraech;
  perform wamo_testhilfe.gleich((select modell_gespraech from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000024a1'), null::text, 'automatisch');
  -- falsche Form: Großbuchstaben, Leerzeichen, Anführung, Schrägstrich, zu lang, Stimme mit Ziffer
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_gespraech = 'Gemma4'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_bilder = 'gemma4 31b'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_hintergrund = 'x''; drop'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_bilder = 'bedrock/claude'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_gespraech = repeat('a', 64)
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_gespraech = ''
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_bilder = 'gemma4' || chr(10)
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts_stimme = 'Ryan'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts_stimme = '1ryan'
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '23514');
  -- Grenze: 63 Zeichen gehen, eine Stimme mit Ziffer in der Mitte geht
  update __SCHEMA__.model_access set modell_gespraech = repeat('a', 63), tts_stimme = 'stimme2'
    where user_id = '00000000-0000-4000-8000-0000000024a1';
  perform wamo_testhilfe.gleich((select length(modell_gespraech) from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000024a1'), 63, '63 Zeichen');
  -- Zwang des Admins: die Stimme im Haus bleibt wählbar (Upsert wie im Kern), nur_haus und Modell des Admins bleiben stehen
  insert into __SCHEMA__.model_access (user_id, tts_stimme) values ('00000000-0000-4000-8000-0000000024a3', 'ryan')
    on conflict (user_id) do update set tts_stimme = excluded.tts_stimme;
  perform wamo_testhilfe.gleich((select nur_haus::text || '/' || claude_modell || '/' || tts_stimme from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000024a3'), 'true/claude-haiku-5-5/ryan',
                                'Zwang bleibt');
  -- alles andere bleibt wie vor 0024: kein nur_haus, kein Claude-Modell, kein Löschen
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set nur_haus = false
    where user_id = '00000000-0000-4000-8000-0000000024a3'$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set claude_modell = 'claude-opus-5-5'
    where user_id = '00000000-0000-4000-8000-0000000024a3'$s$, '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.model_access
    where user_id = '00000000-0000-4000-8000-0000000024a1'$s$, '42501');
  -- der gefährlichste Weg: nur_haus über den Upsert des Kerns
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.model_access (user_id, modell_gespraech)
    values ('00000000-0000-4000-8000-0000000024a3', 'gemma4-31b')
    on conflict (user_id) do update set nur_haus = false$s$, '42501');
end $$;
reset role;

-- 2b. Zweiter Lauf der Rechte ändert nichts (revoke und grant wie in der Migration)
revoke all (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme)
  on __SCHEMA__.model_access from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;
grant insert (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;
grant update (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'tts_stimme', 'UPDATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'nur_haus', 'UPDATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.model_access', 'modell_gespraech', 'SELECT')
     or not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'stt', 'UPDATE') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

-- 3. Die Verwaltung sieht und setzt die Wahl der Person nicht (Rechte aus 0010 sonst unverändert)
set role wamo_admin;
select wamo_testhilfe.fehler($s$select modell_gespraech from __SCHEMA__.model_access$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts_stimme = 'ryan'
  where user_id = '00000000-0000-4000-8000-0000000024a2'$s$, '42501');
do $$ begin
  update __SCHEMA__.model_access set stt = 'haus' where user_id = '00000000-0000-4000-8000-0000000024a3';
  perform wamo_testhilfe.gleich((select stt from __SCHEMA__.model_access
                                  where user_id = '00000000-0000-4000-8000-0000000024a3'), 'haus', 'Verwaltung setzt stt');
end $$;
reset role;

-- 4. Fremde Rollen lesen und schreiben nichts (mit usage auf dem Schema, also an den Spaltenrechten gescheitert)
set role anon;
select wamo_testhilfe.fehler($s$select modell_gespraech from __SCHEMA__.model_access$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set modell_gespraech = 'gemma4-31b'$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$update __SCHEMA__.model_access set tts_stimme = 'ryan'$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.model_access (user_id, modell_bilder) values
  ('00000000-0000-4000-8000-0000000024a2', 'gemma4-31b')$s$, '42501');
reset role;

rollback;
\echo 0024 OK
