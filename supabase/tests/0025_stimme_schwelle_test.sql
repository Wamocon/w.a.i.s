-- Test für 0025_stimme_schwelle. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten,
-- Profile, Abdrücke und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0025.
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0025_stimme_schwelle_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0025 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
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
-- ein gültiger Abdruck (192 Werte) als Text, wie der Kern ihn schickt (stimme_modell.als_vektor)
create function wamo_testhilfe.abdruck() returns text language sql immutable as $f$
  select '[' || array_to_string(array_fill(0.072::numeric, array[192]), ',') || ']'
$f$;
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre
-- wirklich an den Spaltenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000025a1', 'schwelle1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000025a2', 'schwelle2@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000025a1', 'Schwelle Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000025a2', 'Schwelle Zwei', 'mitglied', true);
-- Profil Zwei: Abdruck aus der Zeit vor 0025 (ohne Schwelle, als postgres angelegt)
insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version)
  values ('00000000-0000-4000-8000-0000000025a2', 'Schwelle Zwei', true, wamo_testhilfe.abdruck()::extensions.vector, now(), 'stimme-1');

-- 1. Migration eingetragen, Spalte nullbar ohne Vorgabe, Bestand unverändert (NULL heißt: Schwelle aus der Umgebung)
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations
                                  where version = '0025_stimme_schwelle'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select count(*) from information_schema.columns
                                  where table_schema = '__SCHEMA__' and table_name = 'speakers' and column_name = 'voice_threshold'
                                    and data_type = 'real' and is_nullable = 'YES' and column_default is null), 1::bigint, 'Spalte');
  perform wamo_testhilfe.gleich((select voice_threshold from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000025a2'), null::real, 'Bestand');
end $$;

-- 2. Der Kern speichert und liest die Schwelle wie voice-core/stimme_speicher.py (Upsert mit Abdruck, Lesen in einer Abfrage)
set role wamo_core;
do $$ begin
  insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, voice_threshold)
    values ('00000000-0000-4000-8000-0000000025a1', 'Schwelle Eins', true, wamo_testhilfe.abdruck()::extensions.vector, now(),
            'stimme-1', now(), 0.42::real)
    on conflict (user_id) where is_owner do update set name = excluded.name, voiceprint = excluded.voiceprint,
      consent_at = excluded.consent_at, consent_text_version = excluded.consent_text_version, enrolled_at = excluded.enrolled_at,
      voice_threshold = excluded.voice_threshold;
  perform wamo_testhilfe.gleich((select voice_threshold from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000025a1' and is_owner), 0.42::real, 'neue Zeile');
  -- neu einlernen ersetzt die Schwelle, auch durch NULL (eine alte Schwelle gilt für einen neuen Abdruck nie)
  insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, voice_threshold)
    values ('00000000-0000-4000-8000-0000000025a1', 'Schwelle Eins', true, wamo_testhilfe.abdruck()::extensions.vector, now(),
            'stimme-1', now(), null)
    on conflict (user_id) where is_owner do update set voiceprint = excluded.voiceprint, voice_threshold = excluded.voice_threshold;
  perform wamo_testhilfe.gleich((select voice_threshold from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000025a1'), null::real, 'ersetzt durch NULL');
  -- die Grenzen 0,2 und 0,8 gelten mit, alles außerhalb lehnt die Datenbank ab
  update __SCHEMA__.speakers set voice_threshold = 0.2 where user_id = '00000000-0000-4000-8000-0000000025a1';
  update __SCHEMA__.speakers set voice_threshold = 0.8 where user_id = '00000000-0000-4000-8000-0000000025a1';
  update __SCHEMA__.speakers set voice_threshold = 0.35 where user_id = '00000000-0000-4000-8000-0000000025a2';
  perform wamo_testhilfe.gleich((select voice_threshold from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000025a2'), 0.35::real, 'Bestand nachgetragen');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 0.19
    where user_id = '00000000-0000-4000-8000-0000000025a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 0.81
    where user_id = '00000000-0000-4000-8000-0000000025a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 'NaN'::real
    where user_id = '00000000-0000-4000-8000-0000000025a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 'Infinity'::real
    where user_id = '00000000-0000-4000-8000-0000000025a1'$s$, '23514');
  -- Löschen des Abdrucks nimmt die Schwelle mit (DSGVO Art. 17, wie stimme_speicher.abdruck_loeschen)
  delete from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000025a2' and is_owner;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000025a2'), 0::bigint, 'gelöscht');
end $$;
reset role;

-- 2b. Zweiter Lauf der Rechte ändert nichts
revoke all (voice_threshold) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (voice_threshold) on __SCHEMA__.speakers to wamo_core;
grant insert (voice_threshold) on __SCHEMA__.speakers to wamo_core;
grant update (voice_threshold) on __SCHEMA__.speakers to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'voice_threshold', 'UPDATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.speakers', 'voice_threshold', 'SELECT') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

-- 3. Die Verwaltung und fremde Rollen lesen und schreiben nichts (mit usage auf dem Schema, also an den Spaltenrechten gescheitert)
set role wamo_admin;
select wamo_testhilfe.fehler($s$select voice_threshold from __SCHEMA__.speakers$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 0.4$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select voice_threshold from __SCHEMA__.speakers$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voice_threshold = 0.4$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select voice_threshold from __SCHEMA__.speakers$s$, '42501');
reset role;

rollback;
\echo 0025 OK
