-- Test für 0032_labor_zugang. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile und
-- vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0032 (und 0031: die Rolle wamo_werkstatt).
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0032_labor_zugang_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0032 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_core, wamo_admin, wamo_werkstatt to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core, wamo_admin, wamo_werkstatt, anon, authenticated, service_role;
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
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, wamo_werkstatt, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre
-- wirklich an den Tabellenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values ('00000000-0000-4000-8000-0000000032a1', 'laborzugang1@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv)
  values ('00000000-0000-4000-8000-0000000032a1', 'Labor Zugang Eins', 'admin', true);

-- 1. Migration eingetragen, Tabelle da, noch leer
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations where version = '0032_labor_zugang'), 1::bigint,
                                'Migration eingetragen');
  perform wamo_testhilfe.gleich(to_regclass('__SCHEMA__.labor_zugang') is not null, true, 'Tabelle');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zugang), 0::bigint, 'am Anfang leer');
end $$;

-- 2. Die Anweisungen des Kerns (voice-core/labor_zugang.py) wörtlich, mit eingesetzten Werten statt $1 bis $6. Ändert sich labor_zugang.py,
--    muss dieser Abschnitt mit (voice-core/test_migration_0032.py prüft das). Setzen schreibt Schlüssel und Protokollzeile in EINER Anweisung.
set role wamo_core;
select wamo_testhilfe.gleich((select count(*) from (
  select claude_schluessel, claude_workspace, endet_auf, gesetzt_am, geprueft_am from __SCHEMA__.labor_zugang where id = true::boolean
) leer), 0::bigint, 'Lesen des Kerns ohne Zeile');
with neu as (insert into __SCHEMA__.labor_zugang (id, claude_schluessel, claude_workspace, endet_auf, gesetzt_von, gesetzt_am, geprueft_am)
  values (true, decode(repeat('ab', 60), 'hex'), null, 'Ab12', '00000000-0000-4000-8000-0000000032a1'::uuid, now(), now())
  on conflict (id) do update set claude_schluessel = excluded.claude_schluessel, claude_workspace = excluded.claude_workspace,
  endet_auf = excluded.endet_auf, gesetzt_von = excluded.gesetzt_von, gesetzt_am = excluded.gesetzt_am,
  geprueft_am = excluded.geprueft_am returning endet_auf)
insert into __SCHEMA__.actions (user_id, tool, params, reason, risk, status, result, finished_at)
select '00000000-0000-4000-8000-0000000032a1'::uuid, 'labor_zugang_setzen', jsonb_build_object('endet_auf', neu.endet_auf),
       'Claude-Zugang des Labors von einem Admin gesetzt', 'change'::__SCHEMA__.risk_class, 'done'::__SCHEMA__.action_status, '{}'::jsonb, now()
from neu;
-- noch einmal setzen (anderer Schlüssel, mit Workspace): ersetzt die eine Zeile, es gibt nie zwei
with neu as (insert into __SCHEMA__.labor_zugang (id, claude_schluessel, claude_workspace, endet_auf, gesetzt_von, gesetzt_am, geprueft_am)
  values (true, decode(repeat('cd', 60), 'hex'), 'wrkspc_Test123456', 'Cd34', '00000000-0000-4000-8000-0000000032a1'::uuid, now(), now())
  on conflict (id) do update set claude_schluessel = excluded.claude_schluessel, claude_workspace = excluded.claude_workspace,
  endet_auf = excluded.endet_auf, gesetzt_von = excluded.gesetzt_von, gesetzt_am = excluded.gesetzt_am,
  geprueft_am = excluded.geprueft_am returning endet_auf)
insert into __SCHEMA__.actions (user_id, tool, params, reason, risk, status, result, finished_at)
select '00000000-0000-4000-8000-0000000032a1'::uuid, 'labor_zugang_setzen', jsonb_build_object('endet_auf', neu.endet_auf),
       'Claude-Zugang des Labors von einem Admin gesetzt', 'change'::__SCHEMA__.risk_class, 'done'::__SCHEMA__.action_status, '{}'::jsonb, now()
from neu;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zugang), 1::bigint, 'genau eine Zeile');
select wamo_testhilfe.gleich((select endet_auf from __SCHEMA__.labor_zugang), 'Cd34', 'der zweite Schlüssel gilt');
select wamo_testhilfe.gleich((select claude_workspace from __SCHEMA__.labor_zugang), 'wrkspc_Test123456', 'Workspace gespeichert');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.actions where tool = 'labor_zugang_setzen'
                              and user_id = '00000000-0000-4000-8000-0000000032a1'), 2::bigint, 'zwei Protokollzeilen');
-- das Protokoll nennt nur die letzten vier Zeichen, nie den Wert
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.actions where tool = 'labor_zugang_setzen'
                              and params = jsonb_build_object('endet_auf', params ->> 'endet_auf')
                              and params ->> 'endet_auf' in ('Ab12', 'Cd34')), 2::bigint, 'Protokoll nur mit endet_auf');
-- Entfernen: löschen und protokollieren in einer Anweisung; ohne Zeile entsteht keine Protokollzeile
with weg as (delete from __SCHEMA__.labor_zugang where id returning endet_auf)
insert into __SCHEMA__.actions (user_id, tool, params, reason, risk, status, result, finished_at)
select '00000000-0000-4000-8000-0000000032a1'::uuid, 'labor_zugang_entfernen', jsonb_build_object('endet_auf', weg.endet_auf),
       'Claude-Zugang des Labors von einem Admin entfernt, es gilt wieder der Schlüssel des Servers', 'change'::__SCHEMA__.risk_class,
       'done'::__SCHEMA__.action_status, '{}'::jsonb, now()
from weg;
with weg as (delete from __SCHEMA__.labor_zugang where id returning endet_auf)
insert into __SCHEMA__.actions (user_id, tool, params, reason, risk, status, result, finished_at)
select '00000000-0000-4000-8000-0000000032a1'::uuid, 'labor_zugang_entfernen', jsonb_build_object('endet_auf', weg.endet_auf),
       'Claude-Zugang des Labors von einem Admin entfernt, es gilt wieder der Schlüssel des Servers', 'change'::__SCHEMA__.risk_class,
       'done'::__SCHEMA__.action_status, '{}'::jsonb, now()
from weg;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zugang), 0::bigint, 'entfernt');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.actions where tool = 'labor_zugang_entfernen'), 1::bigint,
                             'eine Protokollzeile, die zweite Anweisung fand nichts');
reset role;

-- 3. Prüfregeln (als postgres, damit sie an der Regel scheitern und nicht an den Rechten)
do $$ begin
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (id, claude_schluessel, endet_auf)
    values (false, decode(repeat('ab', 60), 'hex'), 'Ab12')$s$, '23514');          -- id muss true sein
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 10), 'hex'), 'Ab12')$s$, '23514');                  -- Chiffrat zu kurz
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 600), 'hex'), 'Ab12')$s$, '23514');                 -- Chiffrat zu lang
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (null, 'Ab12')$s$, '23502');                                             -- Chiffrat Pflicht
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 60), 'hex'), 'Ab1')$s$, '23514');                   -- endet_auf genau vier Zeichen
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 60), 'hex'), 'Ab 2')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 60), 'hex'), null)$s$, '23502');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf, claude_workspace)
    values (decode(repeat('ab', 60), 'hex'), 'Ab12', 'workspace')$s$, '23514');     -- Workspace beginnt mit wrkspc_
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf, gesetzt_von)
    values (decode(repeat('ab', 60), 'hex'), 'Ab12', '00000000-0000-4000-8000-00000000ffff')$s$, '23503');
  -- eine Zeile geht, eine zweite nie (Primärschlüssel id)
  insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf, gesetzt_von)
    values (decode(repeat('ab', 60), 'hex'), 'Ab12', '00000000-0000-4000-8000-0000000032a1');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf)
    values (decode(repeat('ab', 60), 'hex'), 'Zz99')$s$, '23505');
end $$;

-- 4. Fremde Rollen lesen und schreiben nichts, auch nicht der Werkstatt-Dienst
set role wamo_admin;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select claude_schluessel from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zugang (claude_schluessel, endet_auf) values ('\x00', 'Ab12')$s$, '42501');
reset role;
set role wamo_werkstatt;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select endet_auf from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.labor_zugang set endet_auf = 'Zz99'$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.labor_zugang$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zugang$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.labor_zugang set endet_auf = 'Zz99'$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.labor_zugang$s$, '42501');
reset role;

-- 5. Der Kern darf lesen, ändern und löschen, aber weder leeren noch Trigger oder Verweise anlegen
set role wamo_core;
select wamo_testhilfe.fehler($s$truncate __SCHEMA__.labor_zugang$s$, '42501');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zugang), 1::bigint, 'der Kern sieht die Zeile');
reset role;

-- 6. Wird das Profil gelöscht, bleibt die Zeile (Konfiguration, kein Gastdatum), gesetzt_von wird leer
do $$ begin
  delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000032a1';
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zugang), 1::bigint, 'Zeile bleibt ohne Profil');
  perform wamo_testhilfe.gleich((select gesetzt_von is null from __SCHEMA__.labor_zugang), true, 'gesetzt_von ist leer');
end $$;

-- 7. Zweiter Lauf der Rechte ändert nichts
revoke all on __SCHEMA__.labor_zugang from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant select, insert, update, delete on __SCHEMA__.labor_zugang to wamo_core;
do $$ begin
  if not has_table_privilege('wamo_core', '__SCHEMA__.labor_zugang', 'DELETE')
     or has_table_privilege('wamo_core', '__SCHEMA__.labor_zugang', 'TRUNCATE')
     or has_table_privilege('wamo_werkstatt', '__SCHEMA__.labor_zugang', 'SELECT') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

rollback;
\echo 0032 OK
