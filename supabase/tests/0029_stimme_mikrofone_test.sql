-- Test für 0029_stimme_mikrofone. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile,
-- Abdrücke und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nachdem 0029 zweimal hintereinander angewandt
-- wurde (so ist auch die Wiederholbarkeit von Regeln, Index, Trigger und Rechten belegt).
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0029_stimme_mikrofone_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0029 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
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
-- Kennung eines Mikrofons wie voice-core/stimme_mikrofon.py (32 Hexzeichen)
create function wamo_testhilfe.kennung(p_name text) returns text language sql immutable as $f$
  select left(encode(sha256(convert_to(lower(p_name), 'UTF8')), 'hex'), 32)
$f$;
-- Einlernen wie der Kern (voice-core/stimme_speicher.py): Upsert je Person und Mikrofon
create function wamo_testhilfe.einlernen(p_user uuid, p_mikrofon text, p_name text, p_wert numeric, p_version text) returns void
language sql as $f$
  insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, voice_threshold,
                                   mikrofon, mikrofon_name)
    values (p_user, 'Mikro Test', true, wamo_testhilfe.vektor(192, p_wert)::extensions.vector, now(), p_version, now(), 0.33::real,
            p_mikrofon, p_name)
    on conflict (user_id, mikrofon) where is_owner do update set name = excluded.name, voiceprint = excluded.voiceprint,
      consent_at = excluded.consent_at, consent_text_version = excluded.consent_text_version, enrolled_at = excluded.enrolled_at,
      voice_threshold = excluded.voice_threshold, mikrofon_name = excluded.mikrofon_name
$f$;
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre
-- wirklich an den Spaltenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000029a1', 'mikro1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000029a2', 'mikro2@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000029a1', 'Mikro Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000029a2', 'Mikro Zwei', 'mitglied', true);
-- Profil Eins: Abdruck aus der Zeit vor 0029 (ohne Mikrofon, als postgres angelegt, mit Schatten und stimme-2)
insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, voiceprint_shadow, shadow_model)
  values ('00000000-0000-4000-8000-0000000029a1', 'Mikro Eins', true, wamo_testhilfe.vektor(192, 0.072)::extensions.vector, now(),
          'stimme-2', wamo_testhilfe.vektor(256, 0.0625)::extensions.vector, 'wespeaker-resnet34-cmn');

-- 1. Migration eingetragen, Bestand als unbekanntes Mikrofon ohne Datenverlust, alter Index weg, neuer da, Trigger aktiv
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations
                                  where version = '0029_stimme_mikrofone'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select mikrofon || '|' || coalesce(mikrofon_name, '-') || '|' || shadow_model from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000029a1'), 'unbekannt|-|wespeaker-resnet34-cmn',
                                'Bestand als unbekanntes Mikrofon');
  perform wamo_testhilfe.gleich(to_regclass('__SCHEMA__.speakers_one_owner_idx')::text, null::text, 'alter Index weg');
  perform wamo_testhilfe.gleich((select count(*) from pg_trigger where tgrelid = '__SCHEMA__.speakers'::regclass
                                  and tgname = 'speakers_mikrofon_grenze' and tgenabled = 'O'), 1::bigint, 'Trigger');
end $$;

-- 2. Der Kern lernt wie voice-core/stimme_speicher.py ein: je Mikrofon eine Zeile, höchstens drei
set role wamo_core;
do $$ begin
  perform wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a1', wamo_testhilfe.kennung('Headset (Jabra)'), 'Headset (Jabra)',
                                   0.05, 'stimme-3');
  perform wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a1', wamo_testhilfe.kennung('Mikrofonarray'), 'Mikrofonarray',
                                   0.06, 'stimme-3');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000029a1' and is_owner), 3::bigint, 'drei Mikrofone');
  -- Upsert auf ein vorhandenes Mikrofon ersetzt nur dieses (auch bei drei), der Schatten des unbekannten bleibt
  perform wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a1', wamo_testhilfe.kennung('Headset (Jabra)'), 'Headset (Jabra)',
                                   0.04, 'stimme-3');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000029a1' and is_owner), 3::bigint,
                                'Upsert auf ein vorhandenes Mikrofon');
  perform wamo_testhilfe.gleich((select shadow_model from __SCHEMA__.speakers
                                  where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = 'unbekannt'),
                                'wespeaker-resnet34-cmn', 'andere Mikrofone unberührt');
  -- viertes Mikrofon abgelehnt (Trigger speakers_mikrofon_grenze)
  perform wamo_testhilfe.fehler($s$select wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a1',
    wamo_testhilfe.kennung('Webcam'), 'Webcam', 0.03, 'stimme-3')$s$, '23514');
  -- zweimal dasselbe Mikrofon ohne Upsert verletzt den Index
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version,
    mikrofon, mikrofon_name) values ('00000000-0000-4000-8000-0000000029a1', 'Mikro Eins', true,
    wamo_testhilfe.vektor(192, 0.05)::extensions.vector, now(), 'stimme-3', wamo_testhilfe.kennung('Mikrofonarray'), 'Mikrofonarray')$s$,
    '23505');
  -- Schatten mit stimme-3 erlaubt (wie stimme_speicher.schatten_speichern je Mikrofon), mit stimme-1 nicht
  update __SCHEMA__.speakers set voiceprint_shadow = wamo_testhilfe.vektor(256, 0.05)::text::extensions.vector,
      shadow_model = 'wespeaker-resnet34-cmn'
    where user_id = '00000000-0000-4000-8000-0000000029a1'::uuid and is_owner and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')
      and voiceprint is not null;
  perform wamo_testhilfe.gleich((select shadow_model from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1'
                                  and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')), 'wespeaker-resnet34-cmn', 'Schatten mit stimme-3');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set consent_text_version = 'stimme-1'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  -- Regeln für Kennung und Name; die Kennung einer Zeile ist fest (Kennung fest, auch zu einer gültigen anderen)
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon = 'Headset'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = 'unbekannt'$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon = wamo_testhilfe.kennung('Webcam'), mikrofon_name = 'Webcam'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = 'Head' || chr(8238) || 'set'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = repeat('a', 121)
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = 'Head' || chr(10) || 'set'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = ''
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray')$s$, '23514');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = 'Name ohne Kennung'
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = 'unbekannt'$s$, '23514');
  update __SCHEMA__.speakers set mikrofon_name = repeat('ä', 120)
    where user_id = '00000000-0000-4000-8000-0000000029a1' and mikrofon = wamo_testhilfe.kennung('Mikrofonarray');
  -- die Grenze gilt je Person: Profil Zwei lernt unabhängig ein, Profil Eins bleibt bei drei (andere Person unberührt)
  perform wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a2', wamo_testhilfe.kennung('Webcam'), 'Webcam', 0.03, 'stimme-3');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1'),
                                3::bigint, 'andere Person unberührt');
  -- Großbuchstaben in der Kennung gelten nicht (der Kern schreibt nur Kleinbuchstaben)
  perform wamo_testhilfe.fehler($s$select wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a2',
    upper(wamo_testhilfe.kennung('Headset')), 'Headset', 0.03, 'stimme-3')$s$, '23514');
  -- mehrere Zeilen in einer Anweisung zählen einzeln: Profil Zwei hat eines, drei weitere wären vier
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.speakers (user_id, name, is_owner, voiceprint, consent_at, consent_text_version,
    mikrofon, mikrofon_name) select '00000000-0000-4000-8000-0000000029a2', 'Mikro Zwei', true,
    wamo_testhilfe.vektor(192, 0.05)::extensions.vector, now(), 'stimme-3', wamo_testhilfe.kennung('Mikro ' || n), 'Mikro ' || n
    from generate_series(1, 3) n$s$, '23514');
  -- auch ein Umzug zu einer Person mit drei Mikrofonen ist ein viertes
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set user_id = '00000000-0000-4000-8000-0000000029a1'
    where user_id = '00000000-0000-4000-8000-0000000029a2'$s$, '23514');
  -- ein Mikrofon löschen (stimme_speicher.abdruck_loeschen mit Kennung), danach geht ein neues
  delete from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1' and is_owner
    and mikrofon = wamo_testhilfe.kennung('Headset (Jabra)');
  perform wamo_testhilfe.einlernen('00000000-0000-4000-8000-0000000029a1', wamo_testhilfe.kennung('Webcam'), 'Webcam', 0.03, 'stimme-3');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1'),
                                3::bigint, 'nach dem Löschen wieder Platz');
  -- alle löschen (DSGVO Art. 17, stimme_speicher.abdruck_loeschen ohne Kennung): alle gelöscht, die andere Person behält ihren
  delete from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1' and is_owner;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1'),
                                0::bigint, 'alle gelöscht');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a2'),
                                1::bigint, 'die andere Person behält ihren');
end $$;
reset role;

-- 2a. Zeilen ohne is_owner (wie im Labortest 0018) zählen nicht zur Grenze und brauchen keine Kennung
insert into __SCHEMA__.speakers (user_id, name) select '00000000-0000-4000-8000-0000000029a1', 'Gast ' || n from generate_series(1, 4) n;
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.speakers where user_id = '00000000-0000-4000-8000-0000000029a1'
                                  and not is_owner and mikrofon = 'unbekannt'), 4::bigint, 'Gäste ohne Grenze');
end $$;

-- 2b. Zweiter Lauf der Rechte ändert nichts
revoke all (mikrofon, mikrofon_name) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;
grant insert (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;
grant update (mikrofon_name) on __SCHEMA__.speakers to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'mikrofon', 'INSERT')
     or not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'mikrofon_name', 'UPDATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.speakers', 'mikrofon', 'SELECT')
     or has_column_privilege('wamo_admin', '__SCHEMA__.speakers', 'mikrofon_name', 'SELECT') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

-- 3. Die Verwaltung und fremde Rollen lesen und schreiben nichts (mit usage auf dem Schema, also an den Spaltenrechten gescheitert)
set role wamo_admin;
select wamo_testhilfe.fehler($s$select mikrofon from __SCHEMA__.speakers$s$, '42501');
select wamo_testhilfe.fehler($s$select mikrofon_name from __SCHEMA__.speakers$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = null$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select mikrofon_name from __SCHEMA__.speakers$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$update __SCHEMA__.speakers set mikrofon_name = null$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select mikrofon from __SCHEMA__.speakers$s$, '42501');
reset role;

rollback;
\echo 0029 OK
