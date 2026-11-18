-- Test für 0028_stimme_schatten. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten,
-- Profile, Abdrücke und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nachdem 0028 zweimal hintereinander
-- angewandt wurde (so ist auch die Wiederholbarkeit von Regeln, Trigger und Rechten belegt).
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0028_stimme_schatten_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0028 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
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
-- ein gültiger Vektor mit p_n Werten als Text, wie der Kern ihn schickt (stimme_modell.als_vektor): 192 für TitaNet, 256 für den Schatten
create function wamo_testhilfe.vektor(p_n int, p_wert numeric) returns text language sql immutable as $f$
  select '[' || array_to_string(array_fill(p_wert, array[p_n]), ',') || ']'
$f$;
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre
-- wirklich an den Spaltenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000028a1', 'schatten1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000028a2', 'schatten2@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000028a1', 'Schatten Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000028a2', 'Schatten Zwei', 'mitglied', true);
-- Profil Zwei: Abdruck aus der Zeit vor 0028 (ohne Schatten, als postgres angelegt)
insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version)
  values ('00000000-0000-4000-8000-0000000028a2', 'Schatten Zwei', true, wamo_testhilfe.vektor(192, 0.072)::extensions.vector, now(),
          'stimme-1');

-- 1. Migration eingetragen, Spalten nullbar ohne Vorgabe, Bestand unverändert, Trigger aktiv
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations
                                  where version = '0028_stimme_schatten'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select count(*) from information_schema.columns
                                  where table_schema = '__SCHEMA__' and table_name = 'speakers'
                                    and column_name in ('voiceprint_shadow', 'shadow_model')
                                    and is_nullable = 'YES' and column_default is null), 2::bigint, 'Spalten');
  perform wamo_testhilfe.gleich((select voiceprint_shadow::text from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000028a2'), null::text, 'Bestand ohne Schatten');
  perform wamo_testhilfe.gleich((select count(*) from pg_trigger where tgrelid = '__SCHEMA__.speakers'::regclass
                                  and tgname = 'speakers_schatten_verwerfen' and tgenabled = 'O'), 1::bigint, 'Trigger');
end $$;

-- 2. Der Kern speichert und liest den Schatten wie voice-core/stimme_speicher.py (Upsert des Abdrucks, danach update des Schattens)
set role wamo_core;
do $$ begin
  insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, voice_threshold)
    values ('00000000-0000-4000-8000-0000000028a1', 'Schatten Eins', true, wamo_testhilfe.vektor(192, 0.072)::extensions.vector, now(),
            'stimme-2', now(), 0.33::real)
    on conflict (user_id) where is_owner do update set name = excluded.name, voiceprint = excluded.voiceprint,
      consent_at = excluded.consent_at, consent_text_version = excluded.consent_text_version, enrolled_at = excluded.enrolled_at,
      voice_threshold = excluded.voice_threshold;
  update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.0625)::text::extensions.vector,
      shadow_model = 'wespeaker-resnet34-cmn'
    where user_id = '00000000-0000-4000-8000-0000000028a1'::uuid and is_owner and voiceprint is not null;
  perform wamo_testhilfe.gleich((select extensions.vector_dims(voiceprint_shadow) || ' ' || shadow_model from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000028a1' and is_owner and voiceprint is not null),
                                '256 wespeaker-resnet34-cmn', 'Schatten gespeichert');
  -- ein update nur des Schattens oder anderer Spalten lässt ihn stehen
  update __SCHEMA__.speakers set voice_threshold = 0.34 where user_id = '00000000-0000-4000-8000-0000000028a1';
  update __SCHEMA__.speakers set voiceprint = voiceprint where user_id = '00000000-0000-4000-8000-0000000028a1';
  perform wamo_testhilfe.gleich((select shadow_model from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000028a1'),
                                'wespeaker-resnet34-cmn', 'derselbe Abdruck behält den Schatten');
  -- neu einlernen ohne Schatten: der Trigger verwirft den alten
  insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, voice_threshold)
    values ('00000000-0000-4000-8000-0000000028a1', 'Schatten Eins', true, wamo_testhilfe.vektor(192, 0.05)::extensions.vector, now(),
            'stimme-2', now(), null)
    on conflict (user_id) where is_owner do update set voiceprint = excluded.voiceprint, voice_threshold = excluded.voice_threshold;
  perform wamo_testhilfe.gleich((select coalesce(voiceprint_shadow::text, '') || coalesce(shadow_model, '') from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000028a1'), '', 'alter Schatten verworfen');
  -- neuer Abdruck und neuer Schatten in einer Anweisung: der neue bleibt
  update __SCHEMA__.speakers set voiceprint = wamo_testhilfe.vektor(192, 0.06)::extensions.vector,
      voiceprint_shadow = wamo_testhilfe.vektor(256, 0.05)::extensions.vector, shadow_model = 'wespeaker-resnet34-cmn'
    where user_id = '00000000-0000-4000-8000-0000000028a1';
  perform wamo_testhilfe.gleich((select shadow_model from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000028a1'),
                                'wespeaker-resnet34-cmn', 'neuer Schatten mit neuem Abdruck');
  -- Regeln: beide zusammen, nur zu einem Abdruck, 64 bis 1024 Werte, Name nur aus a-z, 0-9 und ._+-
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set shadow_model = null
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voiceprint_shadow = null
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(32, 0.1)::extensions.vector
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(1100, 0.01)::extensions.vector
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set shadow_model = 'WeSpeaker ResNet34'
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set shadow_model = repeat('a', 61)
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  -- der Schatten braucht die Einwilligung stimme-2: zurück auf stimme-1 geht nicht, solange er da ist
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set consent_text_version = 'stimme-1'
    where user_id = '00000000-0000-4000-8000-0000000028a1'$s$, '23514');
  -- beide auf NULL ist erlaubt (kein Schatten)
  update __SCHEMA__.speakers set voiceprint_shadow = null, shadow_model = null where user_id = '00000000-0000-4000-8000-0000000028a1';
  -- Löschen des Abdrucks nimmt den Schatten mit (DSGVO Art. 17, wie stimme_speicher.abdruck_loeschen)
  update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.05)::extensions.vector,
      shadow_model = 'wespeaker-resnet34-cmn' where user_id = '00000000-0000-4000-8000-0000000028a1';
  delete from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000028a1' and is_owner;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000028a1'), 0::bigint, 'gelöscht');
end $$;
reset role;

-- 2a. Ein Schatten ohne Abdruck oder zu einem Abdruck mit stimme-1 ist auch für postgres unmöglich; ein Abdruck auf NULL nimmt den
-- Schatten mit
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint_shadow, shadow_model)
  values ('00000000-0000-4000-8000-0000000028a1', 'Ohne Abdruck', true, wamo_testhilfe.vektor(256, 0.05)::extensions.vector,
          'wespeaker-resnet34-cmn')$s$, '23514');
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.05)::extensions.vector,
  shadow_model = 'wespeaker-resnet34-cmn' where user_id = '00000000-0000-4000-8000-0000000028a2'$s$, '23514');
update __SCHEMA__.speakers set consent_text_version = 'stimme-2' where user_id = '00000000-0000-4000-8000-0000000028a2';
update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.05)::extensions.vector, shadow_model = 'wespeaker-resnet34-cmn'
  where user_id = '00000000-0000-4000-8000-0000000028a2';
update __SCHEMA__.speakers set voiceprint = null where user_id = '00000000-0000-4000-8000-0000000028a2';
do $$ begin
  perform wamo_testhilfe.gleich((select coalesce(shadow_model, '') from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000028a2'), '', 'Abdruck weg, Schatten weg');
end $$;

-- 2b. Zweiter Lauf der Rechte ändert nichts
revoke all (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers to wamo_core;
grant update (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'voiceprint_shadow', 'UPDATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.speakers', 'voiceprint_shadow', 'SELECT')
     or has_column_privilege('wamo_admin', '__SCHEMA__.speakers', 'shadow_model', 'SELECT') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

-- 3. Die Verwaltung und fremde Rollen lesen und schreiben nichts (mit usage auf dem Schema, also an den Spaltenrechten gescheitert)
set role wamo_admin;
select wamo_testhilfe.fehler($s$select voiceprint_shadow from __SCHEMA__.speakers$s$, '42501');
select wamo_testhilfe.fehler($s$select shadow_model from __SCHEMA__.speakers$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set shadow_model = null$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select voiceprint_shadow from __SCHEMA__.speakers$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set voiceprint_shadow = null$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select shadow_model from __SCHEMA__.speakers$s$, '42501');
reset role;

rollback;
\echo 0028 OK
