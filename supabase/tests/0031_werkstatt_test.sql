-- Test für 0031_werkstatt. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile, Termine,
-- Karten, Versionen und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0031:
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0031_werkstatt_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0031 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
-- Damit die Zahlen stimmen, leert der Test INNERHALB der Transaktion die sieben Tabellen dieser Migration und sessions (mit turns); alles
-- wird zurückgerollt. Er hält dafür kurz Zeilensperren: nicht während eines Lasttests oder eines Labortags ausführen.
-- Was geprüft wird: Regeln und Trigger der Tabellen, die Ansichten für den Kern (nur die aktive Version, nur Eigener Text), die
-- Lesefunktionen mit festen Zahlen, die Freigabekarten (einmalig, fünf Minuten), das Aufräumen und die Rechte je Rolle (wamo_werkstatt,
-- wamo_core, anon, authenticated, service_role, wamo_admin). Dass die Migration zweimal läuft und 0018 danach weiter grün ist, prüft der
-- Aufrufer, indem er 0031 und 0018 vorher noch einmal anwendet.
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_core, wamo_admin, wamo_werkstatt to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core, wamo_admin, wamo_werkstatt, anon, authenticated, service_role;
-- erwartet einen Fehler mit genau diesem SQLSTATE
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
-- erwartet einen Fehler mit SQLSTATE und dem Namen der verletzten Prüfung (so erkennt der Dienst die Fälle)
create function wamo_testhilfe.fehler_name(p_sql text, p_code text, p_name text) returns void
language plpgsql as $f$
declare
  v_name text;
begin
  begin
    execute p_sql;
  exception when others then
    get stacked diagnostics v_name = constraint_name;
    if sqlstate <> p_code or v_name is distinct from p_name then
      raise exception 'erwartet % (%), bekam % (%) (%) bei: %', p_code, p_name, sqlstate, v_name, sqlerrm, p_sql;
    end if;
    return;
  end;
  raise exception 'erwartet Fehler % (%), aber gelungen: %', p_code, p_name, p_sql;
end $f$;
create function wamo_testhilfe.gleich(p_ist anyelement, p_soll anyelement, p_was text) returns void language plpgsql as $f$
begin
  if p_ist is distinct from p_soll then raise exception '%: ist %, soll %', p_was, p_ist, p_soll; end if;
end $f$;
grant execute on all functions in schema wamo_testhilfe to wamo_core, wamo_admin, wamo_werkstatt, anon, authenticated, service_role;
-- anon, authenticated und service_role haben auf dem Schema kein usage (0001): hier vorübergehend, damit die Sperre wirklich an den
-- Tabellenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

delete from __SCHEMA__.labor_zuordnung;
delete from __SCHEMA__.labor_checkliste;
delete from __SCHEMA__.labor_plaetze;
delete from __SCHEMA__.labor_termine;
delete from __SCHEMA__.labor_karten_versionen;
delete from __SCHEMA__.labor_karten;
delete from __SCHEMA__.werkstatt_karten;
delete from __SCHEMA__.sessions;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000031a1', 'werk1@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000031a2', 'werk2@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000031a3', 'werk3@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000031a1', 'Werk Admin', 'admin', true),
  ('00000000-0000-4000-8000-0000000031a2', 'Werk Mitglied', 'mitglied', true);

-- 1. Migration eingetragen, Objekte da, die Gruppenrolle meldet sich nicht an
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations where version = '0031_werkstatt'), 1::bigint,
                                'Migration eingetragen');
  perform wamo_testhilfe.gleich((select count(*) from pg_class c where c.relnamespace = '__SCHEMA__'::regnamespace and c.relkind = 'r'
                                  and c.relname in ('labor_termine', 'labor_plaetze', 'labor_checkliste', 'labor_karten', 'labor_zuordnung',
                                                    'labor_karten_versionen', 'werkstatt_karten')), 7::bigint, 'sieben Tabellen');
  perform wamo_testhilfe.gleich((select count(*) from pg_class c where c.relnamespace = '__SCHEMA__'::regnamespace and c.relkind = 'v'
                                  and c.relname in ('labor_wissen_aktiv', 'labor_karten_aktive_version')), 2::bigint, 'zwei Ansichten');
  perform wamo_testhilfe.gleich((select not rolcanlogin from pg_roles where rolname = 'wamo_werkstatt'), true, 'Gruppenrolle ohne Anmeldung');
  perform wamo_testhilfe.gleich(pg_get_function_result('__SCHEMA__.werkstatt_sitzungen(integer)'::regprocedure),
    'TABLE(tag date, anzahl bigint, dauer_p50_s integer, dauer_p95_s integer, offen bigint)', 'Spalten von werkstatt_sitzungen');
  perform wamo_testhilfe.gleich(pg_get_function_result('__SCHEMA__.werkstatt_latenz(integer)'::regprocedure),
    'TABLE(tag date, zuege bigint, p50_ms integer, p95_ms integer)', 'Spalten von werkstatt_latenz');
  perform wamo_testhilfe.gleich(pg_get_function_result('__SCHEMA__.werkstatt_aktionen(integer)'::regprocedure),
    'TABLE(tool text, status text, anzahl bigint)', 'Spalten von werkstatt_aktionen (nie params oder result)');
  perform wamo_testhilfe.gleich(pg_get_function_result('__SCHEMA__.werkstatt_labor_stand()'::regprocedure),
    'TABLE(art text, platz smallint, aktiv boolean, zeilen bigint)', 'Spalten von werkstatt_labor_stand (keine Kennung, kein Name)');
end $$;

-- 2. Termine: Regeln, Frist, Spaltenrechte
set role wamo_werkstatt;
do $$
declare
  t record;
begin
  insert into __SCHEMA__.labor_termine (tag, beginn, ende, einwilligung_version, status, aufbewahrung_bis, erstellt_von)
    values ('2037-03-14', '09:00', '17:00', 2, 'freigegeben', '2037-03-27', '00000000-0000-4000-8000-0000000031a1')
    returning * into t;
  perform wamo_testhilfe.gleich(t.id is not null and t.created_at is not null and t.updated_at is not null, true, 'Termin angelegt');
  -- Rand der Frist: am Labortag selbst und 14 Tage danach gehen
  insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-15', '2037-03-15');
  insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-16', '2037-03-30');
  perform wamo_testhilfe.gleich((select einwilligung_version from __SCHEMA__.labor_termine where tag = '2037-03-15'), 1::smallint,
                                'Einwilligungsversion Standard 1');
  perform wamo_testhilfe.gleich((select status from __SCHEMA__.labor_termine where tag = '2037-03-15'), 'entwurf', 'Stand Standard entwurf');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-14', '2037-03-20')$s$, '23505');
  insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-17', '2037-03-31');  -- genau tag + 14
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-19', '2037-04-03')$s$, '23514');  -- tag + 15
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-03-17', '2037-03-16')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis, status) values ('2037-03-18', '2037-03-20', 'fertig')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis, einwilligung_version) values ('2037-03-18', '2037-03-20', 0)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis, einwilligung_version) values ('2037-03-18', '2037-03-20', 100)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis, erstellt_von)
    values ('2037-03-18', '2037-03-20', '00000000-0000-4000-8000-00000000ffff')$s$, '23503');
  -- die Datenbank stempelt: das Panel setzt weder Zeiten noch den Ersteller nachträglich
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis, created_at) values ('2037-03-18', '2037-03-20', now())$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_termine set updated_at = now()$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_termine set created_at = now()$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_termine set erstellt_von = null$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_termine set id = gen_random_uuid()$s$, '42501');
  update __SCHEMA__.labor_termine set status = 'laufend', beginn = '08:30' where tag = '2037-03-14';
  perform wamo_testhilfe.gleich((select status from __SCHEMA__.labor_termine where tag = '2037-03-14'), 'laufend', 'Stand geändert');
end $$;
reset role;
-- der Trigger setzt updated_at selbst, auch wenn jemand einen anderen Wert schreibt
update __SCHEMA__.labor_termine set updated_at = '2000-01-01' where tag = '2037-03-14';
select wamo_testhilfe.gleich((select updated_at > '2001-01-01'::timestamptz from __SCHEMA__.labor_termine where tag = '2037-03-14'), true,
                             'updated_at vom Trigger gesetzt');

-- 3. Plätze
set role wamo_werkstatt;
do $$
declare
  v_t uuid := (select id from __SCHEMA__.labor_termine where tag = '2037-03-14');
begin
  insert into __SCHEMA__.labor_plaetze (termin_id, platz, zweck, kennung, gast)
    values (v_t, 1, 'besucher', 'labor-ab', 'Gast 1'), (v_t, 2, 'reserve', null, null),
           (v_t, 15, 'abnahme', 'labor-abcdefgh', repeat('G', 20)), (v_t, 16, 'abnahme', null, null);
  insert into __SCHEMA__.labor_plaetze (termin_id, platz) values (v_t, 3);
  perform wamo_testhilfe.gleich((select zweck from __SCHEMA__.labor_plaetze where termin_id = v_t and platz = 3), 'besucher', 'Zweck Standard besucher');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, zweck) values (%L, 4, 'abnahme')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz) values (%L, 0)$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz) values (%L, 17)$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, zweck) values (%L, 5, 'gast')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, kennung) values (%L, 5, 'labor-a')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, kennung) values (%L, 5, 'labor-abcdefghi')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, kennung) values (%L, 5, 'Labor-ab')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, kennung) values (%L, 5, 'labor-a_')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, gast) values (%L, 5, repeat('G', 21))$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz, gast) values (%L, 5, E'a\nb')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz) values (%L, 1)$s$, v_t), '23505');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_plaetze (termin_id, platz) values ('00000000-0000-4000-8000-00000000ffff', 1)$s$, '23503');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_plaetze set platz = 9 where termin_id = %L and platz = 1$s$, v_t), '42501');
  update __SCHEMA__.labor_plaetze set gast = 'Gast 2', zweck = 'reserve' where termin_id = v_t and platz = 1;
  perform wamo_testhilfe.gleich((select gast from __SCHEMA__.labor_plaetze where termin_id = v_t and platz = 1), 'Gast 2', 'Platz geändert');
  -- ein Platz lässt sich löschen (PUT der Plätze ersetzt die Liste)
  delete from __SCHEMA__.labor_plaetze where termin_id = v_t and platz = 3;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_plaetze where termin_id = v_t), 4::bigint, 'vier Plätze');
end $$;

-- 4. Checkliste
do $$
declare
  v_t uuid := (select id from __SCHEMA__.labor_termine where tag = '2037-03-14');
  c record;
begin
  insert into __SCHEMA__.labor_checkliste (termin_id, titel, quelle, faellig)
    values (v_t, 'Räume vorbereiten', 'Runbook 3.2', '2037-03-13') returning * into c;
  perform wamo_testhilfe.gleich(c.id is not null and c.erledigt_at is null and c.erledigt_von is null, true, 'Eintrag offen');
  update __SCHEMA__.labor_checkliste set erledigt_at = now(), erledigt_von = '00000000-0000-4000-8000-0000000031a1' where id = c.id;
  perform wamo_testhilfe.gleich((select erledigt_at is not null from __SCHEMA__.labor_checkliste where id = c.id), true, 'erledigt');
  update __SCHEMA__.labor_checkliste set erledigt_at = null, erledigt_von = null where id = c.id;
  perform wamo_testhilfe.gleich((select erledigt_at is null from __SCHEMA__.labor_checkliste where id = c.id), true, 'wieder offen');
  insert into __SCHEMA__.labor_checkliste (termin_id, titel) values (v_t, repeat('t', 120));
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel) values (%L, '')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel) values (%L, '   ')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel) values (%L, repeat('t', 121))$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel) values (%L, E'a\nb')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel, quelle) values (%L, 't', repeat('q', 81))$s$, v_t), '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_checkliste (termin_id, titel) values ('00000000-0000-4000-8000-00000000ffff', 't')$s$, '23503');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_checkliste (id, termin_id, titel) values (99, %L, 't')$s$, v_t), '428C9');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_checkliste set erledigt_von = '00000000-0000-4000-8000-00000000ffff' where id = %s$s$, c.id), '23503');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_checkliste set id = 77 where id = %s$s$, c.id), '428C9');  -- generated always: schon die Spalte lehnt ab
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_checkliste set termin_id = %L where id = %s$s$, v_t, c.id), '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.labor_checkliste$s$, '42501');
end $$;

-- 5. Karten: Regeln, Trigger, Zuordnung
do $$
begin
  insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min, stand, geaendert_von)
    values ('A1', 'Grundlagen', 'Ticket anlegen', 'Lege ein Ticket an.', 'Das Ticket ist angelegt.', null, 'K2', 'Eigener Text',
            'Ein Ticket beschreibt eine Aufgabe.', array['Jira', 'Mail'], 5, 'entwurf', '00000000-0000-4000-8000-0000000031a1'),
           ('B12', 'Fehler', 'Mail senden', 'Sende eine Mail.', 'Die Mail ist raus.', 'Adresse fehlt', null, 'keine', null, '{}', 10, 'entwurf', null);
  -- Standardwerte und Ränder
  insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('C3', 'G', 't', 'a', 'e', 1);
  perform wamo_testhilfe.gleich((select wissen || '/' || stand || '/' || cardinality(werkzeuge) from __SCHEMA__.labor_karten where id = 'C3'),
                                'keine/entwurf/0', 'Standardwerte der Karte');
  insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min)
    values ('D4', repeat('g', 30), repeat('t', 60), repeat('a', 240), repeat('e', 240), repeat('f', 120), repeat('l', 40), 'Eigener Text',
            repeat('w', 900), array['Jira', 'Mail', 'Canvas', 'Websuche'], 20);
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('a1', 'G', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('AA1', 'G', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('A100', 'G', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('A', 'G', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('1A', 'G', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', '', 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', repeat('g', 31), 't', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', repeat('t', 61), 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', '   ', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', E'a\tb', 'a', 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', 't', repeat('a', 241), 'e', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', 't', 'a', repeat('e', 241), 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, fehler, dauer_min) values ('E5', 'G', 't', 'a', 'e', repeat('f', 121), 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, lernziel, dauer_min) values ('E5', 'G', 't', 'a', 'e', repeat('l', 41), 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'Lexikon', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'Eigener Text', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, wissenstext, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'keine', 'x', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, wissenstext, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'Eigener Text', '', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, wissenstext, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'Eigener Text', repeat('w', 901), 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, wissen, wissenstext, dauer_min) values ('E5', 'G', 't', 'a', 'e', 'Eigener Text', E'a\nb', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, werkzeuge, dauer_min) values ('E5', 'G', 't', 'a', 'e', '{Excel}', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, werkzeuge, dauer_min)
    values ('E5', 'G', 't', 'a', 'e', '{Jira,Mail,Canvas,Websuche,Jira}', 1)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', 't', 'a', 'e', 0)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('E5', 'G', 't', 'a', 'e', 21)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min, stand) values ('E5', 'G', 't', 'a', 'e', 1, 'fertig')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min) values ('A1', 'G', 't', 'a', 'e', 1)$s$, '23505');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min, geaendert_von)
    values ('E5', 'G', 't', 'a', 'e', 1, '00000000-0000-4000-8000-00000000ffff')$s$, '23503');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten (id, gruppe, titel, aufgabe, erwartung, dauer_min, geaendert_at)
    values ('E5', 'G', 't', 'a', 'e', 1, now())$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten set id = 'Z9' where id = 'A1'$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten set geaendert_at = now() where id = 'A1'$s$, '42501');
end $$;
reset role;
update __SCHEMA__.labor_karten set geaendert_at = '2000-01-01';
set role wamo_werkstatt;
do $$
declare
  v_t uuid := (select id from __SCHEMA__.labor_termine where tag = '2037-03-14');
begin
  -- Veröffentlichen ändert nur den Stand: kein Inhalt, kein neuer Zeitstempel
  update __SCHEMA__.labor_karten set stand = 'veroeffentlicht' where id in ('A1', 'B12');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_karten where stand = 'veroeffentlicht'), 2::bigint, 'zwei veröffentlicht');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_karten where geaendert_at > '2001-01-01'::timestamptz), 0::bigint,
                                'Veröffentlichen stempelt nichts');
  -- eine inhaltliche Änderung macht aus einer veröffentlichten Karte wieder einen Entwurf, auch wenn der Aufrufer den Stand mitschickt
  update __SCHEMA__.labor_karten set titel = 'Ticket neu anlegen', stand = 'veroeffentlicht' where id = 'A1';
  perform wamo_testhilfe.gleich((select stand from __SCHEMA__.labor_karten where id = 'A1'), 'entwurf', 'geänderte Karte ist wieder Entwurf');
  perform wamo_testhilfe.gleich((select geaendert_at > '2001-01-01'::timestamptz from __SCHEMA__.labor_karten where id = 'A1'), true,
                                'geaendert_at gestempelt');
  perform wamo_testhilfe.gleich((select stand from __SCHEMA__.labor_karten where id = 'B12'), 'veroeffentlicht', 'unveränderte Karte bleibt');
  -- ein ausdrücklicher Wechsel von Entwurf auf veröffentlicht mit Änderung gilt
  update __SCHEMA__.labor_karten set titel = 'Ticket anlegen', stand = 'veroeffentlicht' where id = 'A1';
  perform wamo_testhilfe.gleich((select stand from __SCHEMA__.labor_karten where id = 'A1'), 'veroeffentlicht', 'Wechsel auf veröffentlicht');

  -- Zuordnung
  insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id) values (v_t, 1, 'A1'), (v_t, 1, 'B12'), (v_t, 2, 'A1'), (v_t, 2, 'D4');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id) values (%L, 0, 'A1')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id) values (%L, 17, 'A1')$s$, v_t), '23514');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id) values (%L, 3, 'Z9')$s$, v_t), '23503');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id)
    values ('00000000-0000-4000-8000-00000000ffff', 3, 'A1')$s$, '23503');
  perform wamo_testhilfe.fehler(format($s$insert into __SCHEMA__.labor_zuordnung (termin_id, platz, karte_id) values (%L, 1, 'A1')$s$, v_t), '23505');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_zuordnung set platz = 5 where termin_id = %L$s$, v_t), '42501');
  delete from __SCHEMA__.labor_zuordnung where termin_id = v_t and platz = 2 and karte_id = 'A1';
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zuordnung where termin_id = v_t), 3::bigint, 'drei Zuordnungen');
  -- eine gelöschte Karte nimmt ihre Zuordnung mit
  delete from __SCHEMA__.labor_karten where id = 'D4';
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zuordnung where karte_id = 'D4'), 0::bigint, 'Zuordnung der gelöschten Karte weg');
  -- ein gelöschter Termin nimmt Plätze, Checkliste und Zuordnung mit
  delete from __SCHEMA__.labor_termine where id = v_t;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_plaetze where termin_id = v_t), 0::bigint, 'Plätze weg');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_checkliste where termin_id = v_t), 0::bigint, 'Checkliste weg');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_zuordnung where termin_id = v_t), 0::bigint, 'Zuordnung weg');
end $$;
reset role;

-- 6. Versionen: Prüfung der Momentaufnahme, genau eine aktive, unveränderlich
set role wamo_werkstatt;
do $$
declare
  v1 integer;
  v2 integer;
begin
  insert into __SCHEMA__.labor_karten_versionen (erstellt_von, anzahl_aenderungen, wissen_zeichen, karten, aktiv)
    values ('00000000-0000-4000-8000-0000000031a1', 1, 4200,
            '[{"id":"A1","wissen":"Eigener Text","wissenstext":"Text eins","titel":"x"},{"id":"B12","wissen":"keine"}]'::jsonb, false)
    returning version into v1;
  insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten, aktiv)
    values (2, 4300, '[{"id":"A1","wissen":"Eigener Text","wissenstext":"Text zwei"},{"id":"C3","wissen":"Eigener Text","wissenstext":"Text drei"},
                      {"id":"B12","wissen":"keine"},{"id":"D4","wissen":"Glossar"}]'::jsonb, false)
    returning version into v2;
  insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten, aktiv)
    values (3, 6000, jsonb_build_array(jsonb_build_object('id', 'A1', 'wissen', 'Eigener Text', 'wissenstext', repeat('x', 900))), false);
  perform wamo_testhilfe.gleich(v2 > v1, true, 'Versionsnummer zählt fort');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_karten_versionen where aktiv), 0::bigint, 'noch keine aktive Version');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '{}'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[1]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"a1","wissen":"keine"}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"A1","wissen":"Lexikon"}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"A1"}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"A1","wissen":"Eigener Text"}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"A1","wissen":"Eigener Text","wissenstext":""}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 100, '[{"id":"A1","wissen":"Eigener Text","wissenstext":5}]'::jsonb)$s$, '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 6000, jsonb_build_array(jsonb_build_object('id', 'A1', 'wissen', 'Eigener Text', 'wissenstext', repeat('x', 901))))$s$,
    '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 6000, jsonb_build_array(jsonb_build_object('id', 'A1', 'wissen', 'Eigener Text', 'wissenstext', E'a\nb')))$s$,
    '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 6000, (select jsonb_agg(jsonb_build_object('id', 'A1', 'wissen', 'keine')) from generate_series(1, 501)))$s$,
    '23514', 'labor_karten_versionen_karten');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 3, '[{"id":"A1","wissen":"Eigener Text","wissenstext":"Text eins"}]'::jsonb)$s$, '23514', 'labor_karten_versionen_zeichen');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (1, 6001, '[]'::jsonb)$s$, '23514', 'labor_karten_versionen_zeichen_chk');
  perform wamo_testhilfe.fehler_name($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten)
    values (-1, 10, '[]'::jsonb)$s$, '23514', 'labor_karten_versionen_aenderungen_chk');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten_versionen (version, anzahl_aenderungen, wissen_zeichen, karten)
    values (99, 1, 10, '[]'::jsonb)$s$, '428C9');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten_versionen (erstellt_at, anzahl_aenderungen, wissen_zeichen, karten)
    values (now(), 1, 10, '[]'::jsonb)$s$, '42501');
  -- eine Version ist unveränderlich: nur aktiv, nie die Karten, nie löschen
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten_versionen set karten = '[]'::jsonb$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten_versionen set wissen_zeichen = 1$s$, '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.labor_karten_versionen$s$, '42501');
end $$;
reset role;
-- auch der Eigentümer ändert eine Momentaufnahme nicht (Trigger)
select wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten_versionen set karten = '[]'::jsonb$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.labor_karten_versionen set anzahl_aenderungen = 9$s$, '42501');

-- 7. Die Ansichten für den Kern: ohne aktive Version leer
set role wamo_core;
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_wissen_aktiv), 0::bigint, 'ohne aktive Version keine Zeile');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_karten_aktive_version), 0::bigint, 'ohne aktive Version keine Nummer');
end $$;
reset role;
set role wamo_werkstatt;
do $$
declare
  v1 integer := (select version from __SCHEMA__.labor_karten_versionen where anzahl_aenderungen = 1);
  v2 integer := (select version from __SCHEMA__.labor_karten_versionen where anzahl_aenderungen = 2);
  v3 integer := (select version from __SCHEMA__.labor_karten_versionen where anzahl_aenderungen = 3);
begin
  update __SCHEMA__.labor_karten_versionen set aktiv = true where version = v1;
  -- genau eine aktive Version
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_karten_versionen set aktiv = true where version = %s$s$, v2), '23505');
  update __SCHEMA__.labor_karten_versionen set aktiv = false where version = v1;
  update __SCHEMA__.labor_karten_versionen set aktiv = true where version = v2;
  perform set_config('wamo.t31_v2', v2::text, false);
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.labor_karten_versionen set aktiv = true where version = %s$s$, v3), '23505');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_karten_versionen (anzahl_aenderungen, wissen_zeichen, karten, aktiv)
    values (4, 10, '[]'::jsonb, true)$s$, '23505');
end $$;
reset role;
set role wamo_core;
do $$
declare
  v2 integer := current_setting('wamo.t31_v2')::integer;
begin
  perform wamo_testhilfe.gleich((select version from __SCHEMA__.labor_karten_aktive_version), v2, 'die aktive Version');
  perform wamo_testhilfe.gleich((select string_agg(karte_id || ':' || wissenstext, '|' order by karte_id) from __SCHEMA__.labor_wissen_aktiv),
                                'A1:Text zwei|C3:Text drei', 'nur die Karten mit Eigener Text der aktiven Version');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_wissen_aktiv where version = v2), 2::bigint, 'Nummer je Zeile');
  -- der Kern liest nie den Arbeitsstand und nie die Tabellen
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_karten$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_karten_versionen$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_termine$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_plaetze$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_checkliste$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.labor_zuordnung$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_karten$s$, '42501');
  -- labor_wissen_aktiv entfaltet JSON und ist gar nicht änderbar (55000); die einfache Ansicht scheitert am Recht (42501)
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_wissen_aktiv (version, karte_id, wissenstext) values (1, 'A1', 'x')$s$, '55000');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.labor_wissen_aktiv set wissenstext = 'x'$s$, '55000');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.labor_karten_aktive_version$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_sitzungen(7)$s$, '42501');
  perform wamo_testhilfe.fehler($s$select __SCHEMA__.werkstatt_aufraeumen()$s$, '42501');
end $$;
reset role;
-- ohne aktive Version ist es wieder leer
update __SCHEMA__.labor_karten_versionen set aktiv = false;
set role wamo_core;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.labor_wissen_aktiv), 0::bigint, 'wieder leer');
reset role;

-- 8. Freigabekarten: fünf Minuten, einmalig, Inhalt unveränderlich
set role wamo_werkstatt;
do $$
declare
  k uuid;
begin
  insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{"anzahl":3,"karten":["A1","B12"]}'::jsonb, now() + interval '4 minutes')
    returning id into k;
  -- genau fünf Minuten gehen, eine Sekunde mehr nicht
  insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{}'::jsonb, now() + interval '5 minutes');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{}'::jsonb, now() + interval '5 minutes 1 second')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{}'::jsonb, now())$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'labor_loeschen', '{}'::jsonb, now() + interval '1 minute')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '[]'::jsonb, now() + interval '1 minute')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '"text"'::jsonb, now() + interval '1 minute')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis)
    values ('00000000-0000-4000-8000-00000000ffff', 'karten_veroeffentlichen', '{}'::jsonb, now() + interval '1 minute')$s$, '23503');
  -- die Zeit der Karte setzt die Datenbank, nicht der Dienst; verbraucht wird sie erst durch die Ausführung
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis, created_at)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{}'::jsonb, now() + interval '1 minute', now())$s$, '42501');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis, ausgefuehrt_at)
    values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{}'::jsonb, now() + interval '1 minute', now())$s$, '42501');
  update __SCHEMA__.werkstatt_karten set ausgefuehrt_at = now() where id = k;
  perform wamo_testhilfe.gleich((select ausgefuehrt_at is not null from __SCHEMA__.werkstatt_karten where id = k), true, 'Karte ausgeführt');
  perform wamo_testhilfe.fehler_name(format($s$update __SCHEMA__.werkstatt_karten set ausgefuehrt_at = now() where id = %L$s$, k),
                                     '23514', 'werkstatt_karten_verbraucht');
  perform wamo_testhilfe.fehler_name(format($s$update __SCHEMA__.werkstatt_karten set ausgefuehrt_at = null where id = %L$s$, k),
                                     '23514', 'werkstatt_karten_verbraucht');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set ziel = '{}'::jsonb where id = %L$s$, k), '42501');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set gilt_bis = now() + interval '1 hour' where id = %L$s$, k), '42501');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set admin = '00000000-0000-4000-8000-0000000031a2' where id = %L$s$, k), '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.werkstatt_karten$s$, '42501');
end $$;
reset role;
-- der Eigentümer ändert den Inhalt einer Karte ebenfalls nicht (Trigger), auch nicht einer offenen
do $$
declare
  k uuid := (select id from __SCHEMA__.werkstatt_karten where ausgefuehrt_at is null and ziel = '{}'::jsonb limit 1);
begin
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set ziel = '{"x":1}'::jsonb where id = %L$s$, k), '42501');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set admin = '00000000-0000-4000-8000-0000000031a2' where id = %L$s$, k), '42501');
  perform wamo_testhilfe.fehler(format($s$update __SCHEMA__.werkstatt_karten set created_at = now() - interval '1 hour' where id = %L$s$, k), '42501');
end $$;
-- eine abgelaufene Karte lässt sich nicht mehr ausführen (die Karte ist zehn Minuten alt und galt fünf)
insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis, created_at)
  values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{"abgelaufen":1}'::jsonb, now() - interval '6 minutes', now() - interval '10 minutes');
set role wamo_werkstatt;
select wamo_testhilfe.fehler_name($s$update __SCHEMA__.werkstatt_karten set ausgefuehrt_at = now() where ziel = '{"abgelaufen":1}'::jsonb$s$,
                                  '23514', 'werkstatt_karten_abgelaufen');
reset role;
-- Aufräumen: nur Karten, die älter sind als ein Tag
insert into __SCHEMA__.werkstatt_karten (admin, aktion, ziel, gilt_bis, created_at, ausgefuehrt_at)
  values ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{"alt":1}'::jsonb, now() - interval '2 days' + interval '1 minute',
          now() - interval '2 days', now() - interval '2 days' + interval '30 seconds'),
         ('00000000-0000-4000-8000-0000000031a1', 'karten_veroeffentlichen', '{"alt":2}'::jsonb, now() - interval '30 hours' + interval '1 minute',
          now() - interval '30 hours', null);
set role wamo_werkstatt;
do $$
declare
  n_alt bigint := (select count(*) from __SCHEMA__.werkstatt_karten where created_at < now() - interval '1 day');
  n_neu bigint := (select count(*) from __SCHEMA__.werkstatt_karten where created_at >= now() - interval '1 day');
begin
  perform wamo_testhilfe.gleich(n_alt, 2::bigint, 'zwei alte Karten');
  perform wamo_testhilfe.gleich(__SCHEMA__.werkstatt_aufraeumen(), n_alt, 'Aufräumen meldet die gelöschten Karten');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.werkstatt_karten), n_neu, 'die jungen Karten bleiben');
  perform wamo_testhilfe.gleich(__SCHEMA__.werkstatt_aufraeumen(), 0::bigint, 'zweiter Lauf löscht nichts');
end $$;
reset role;

-- 9. Lesefunktionen mit festen Zahlen (Tage nach Berliner Zeit)
do $$
declare
  heute date := (now() at time zone 'Europe/Berlin')::date;
  u uuid := '00000000-0000-4000-8000-0000000031a1';
  t0 timestamptz := ((heute + time '12:00') at time zone 'Europe/Berlin');
  t2 timestamptz := (((heute - 2) + time '12:00') at time zone 'Europe/Berlin');
  s1 uuid;
begin
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values (u, t0, t0 + interval '60 seconds') returning id into s1;
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values (u, t0, t0 + interval '120 seconds');
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values (u, t0, t0 + interval '600 seconds');
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values (u, t0, null);
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values (u, t2, t2 + interval '100 seconds');
  insert into __SCHEMA__.turns (session_id, user_id, role, content, latency_ms, created_at)
    values (s1, u, 'assistant', 'x', 1000, t0), (s1, u, 'assistant', 'x', 2000, t0), (s1, u, 'assistant', 'x', 3000, t0), (s1, u, 'user', 'x', null, t0);
  insert into __SCHEMA__.actions (user_id, tool, risk, status, created_at) values
    (u, 'werkstatt_test_a', 'change', 'done', now()), (u, 'werkstatt_test_a', 'change', 'done', now()),
    (u, 'werkstatt_test_a', 'change', 'failed', now()), (u, 'jira_test', 'read', 'done', now()),
    (u, 'werkstatt_test_a', 'change', 'done', now() - interval '40 days');
end $$;
set role wamo_werkstatt;
do $$
declare
  heute date := (now() at time zone 'Europe/Berlin')::date;
  r record;
begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.werkstatt_sitzungen(14)), 14::bigint, 'vierzehn Tage');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.werkstatt_sitzungen(1)), 1::bigint, 'ein Tag');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.werkstatt_sitzungen(30)), 30::bigint, 'dreißig Tage');
  select * into r from __SCHEMA__.werkstatt_sitzungen(14) s where s.tag = heute;
  perform wamo_testhilfe.gleich(r.anzahl, 4::bigint, 'Sitzungen heute');
  perform wamo_testhilfe.gleich(r.dauer_p50_s, 120, 'Dauer p50');
  perform wamo_testhilfe.gleich(r.dauer_p95_s, 552, 'Dauer p95');
  perform wamo_testhilfe.gleich(r.offen, 1::bigint, 'offene Sitzungen');
  select * into r from __SCHEMA__.werkstatt_sitzungen(14) s where s.tag = heute - 2;
  perform wamo_testhilfe.gleich(r.anzahl, 1::bigint, 'Sitzungen vor zwei Tagen');
  perform wamo_testhilfe.gleich(r.dauer_p50_s, 100, 'Dauer p50 vor zwei Tagen');
  perform wamo_testhilfe.gleich(r.offen, 0::bigint, 'keine offene vor zwei Tagen');
  select * into r from __SCHEMA__.werkstatt_sitzungen(14) s where s.tag = heute - 1;
  perform wamo_testhilfe.gleich(r.anzahl, 0::bigint, 'ein leerer Tag zählt null');
  perform wamo_testhilfe.gleich(r.dauer_p50_s is null, true, 'ein leerer Tag hat keine Dauer');
  select * into r from __SCHEMA__.werkstatt_latenz(14) l where l.tag = heute;
  perform wamo_testhilfe.gleich(r.zuege, 3::bigint, 'Züge mit Latenz heute');
  perform wamo_testhilfe.gleich(r.p50_ms, 2000, 'Latenz p50');
  perform wamo_testhilfe.gleich(r.p95_ms, 2900, 'Latenz p95');
  select * into r from __SCHEMA__.werkstatt_latenz(14) l where l.tag = heute - 1;
  perform wamo_testhilfe.gleich(r.zuege, 0::bigint, 'kein Zug ohne Latenz');
  perform wamo_testhilfe.gleich((select a.anzahl from __SCHEMA__.werkstatt_aktionen(14) a where a.tool = 'werkstatt_test_a' and a.status = 'done'),
                                2::bigint, 'Aktionen fertig (die von vor 40 Tagen zählt nicht)');
  perform wamo_testhilfe.gleich((select a.anzahl from __SCHEMA__.werkstatt_aktionen(14) a where a.tool = 'werkstatt_test_a' and a.status = 'failed'),
                                1::bigint, 'Aktionen gescheitert');
  perform wamo_testhilfe.gleich((select a.anzahl from __SCHEMA__.werkstatt_aktionen(30) a where a.tool = 'jira_test'), 1::bigint, 'andere Werkzeuge zählen mit');
  -- p_tage von 1 bis 30
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_sitzungen(0)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_sitzungen(31)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_sitzungen(null)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_latenz(0)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_latenz(31)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_aktionen(-1)$s$, '22023');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_aktionen(31)$s$, '22023');
end $$;
-- Laborstand: Wrapper um labor_zaehlen, ein Laborprofil mehr heißt eine Zeile mehr und die Zeilen des Profils dazu
do $$
begin
  perform set_config('wamo.t31_zeilen_vorher', (select count(*) || '/' || coalesce(sum(zeilen), 0) from __SCHEMA__.werkstatt_labor_stand()), false);
end $$;
reset role;
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv, labor_art)
  values ('00000000-0000-4000-8000-0000000031a3', 'Schau', 'mitglied', false, 'schaufenster');
do $$
declare
  s uuid;
begin
  insert into __SCHEMA__.sessions (user_id, started_at, ended_at) values ('00000000-0000-4000-8000-0000000031a3', now() - interval '3 hours', now() - interval '2 hours')
    returning id into s;
  insert into __SCHEMA__.turns (session_id, user_id, role, content) values (s, '00000000-0000-4000-8000-0000000031a3', 'user', 'Marker-Text-31');
end $$;
set role wamo_werkstatt;
do $$
declare
  vorher text := current_setting('wamo.t31_zeilen_vorher');
  nachher text := (select count(*) || '/' || coalesce(sum(zeilen), 0) from __SCHEMA__.werkstatt_labor_stand());
  r record;
begin
  perform wamo_testhilfe.gleich(split_part(nachher, '/', 1)::bigint - split_part(vorher, '/', 1)::bigint, 1::bigint, 'ein Laborprofil mehr');
  perform wamo_testhilfe.gleich(split_part(nachher, '/', 2)::bigint - split_part(vorher, '/', 2)::bigint, 2::bigint, 'zwei Zeilen mehr (Sitzung und Zug)');
  select * into r from __SCHEMA__.werkstatt_labor_stand() where art = 'schaufenster' and zeilen = 2 limit 1;
  perform wamo_testhilfe.gleich(r.aktiv, false, 'Laborprofil nicht freigeschaltet');
  perform wamo_testhilfe.gleich(r.platz is null, true, 'das Schaufenster hat keinen Platz');
  -- das Panel führt die Laborfunktionen nie selbst aus
  perform wamo_testhilfe.fehler($s$select __SCHEMA__.labor_zaehlen('00000000-0000-4000-8000-0000000031a3'::uuid)$s$, '42501');
  perform wamo_testhilfe.fehler($s$select __SCHEMA__.labor_loeschen('00000000-0000-4000-8000-0000000031a3'::uuid)$s$, '42501');
end $$;
-- kein Text aus Gesprächen: die Ausgabe der Lesefunktionen enthält den Marker nirgends
do $$
declare
  alles text;
begin
  select coalesce(string_agg(q.x, ' '), '') into alles from (
    select to_jsonb(s)::text as x from __SCHEMA__.werkstatt_sitzungen(30) s
    union all select to_jsonb(l)::text from __SCHEMA__.werkstatt_latenz(30) l
    union all select to_jsonb(a)::text from __SCHEMA__.werkstatt_aktionen(30) a
    union all select to_jsonb(z)::text from __SCHEMA__.werkstatt_labor_stand() z) q;
  perform wamo_testhilfe.gleich(position('Marker-Text-31' in alles), 0, 'kein Gesprächstext in den Lesefunktionen');
  perform wamo_testhilfe.gleich(position('werk1@' in alles), 0, 'keine E-Mail in den Lesefunktionen');
  perform wamo_testhilfe.gleich(position('Werk Admin' in alles), 0, 'kein Name in den Lesefunktionen');
end $$;
reset role;

-- 10. Rechte des Panels auf vorhandene Tabellen: nur der Zugang und das Audit, sonst nichts
set role wamo_werkstatt;
do $$
declare
  a uuid;
begin
  -- Zugang prüfen: genau diese vier Spalten
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000031a1' and rolle = 'admin'
                                  and aktiv and labor_art is null), 1::bigint, 'Zugang des Admins lesbar');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.profiles where labor_art is not null) >= 1, true, 'Laborprofil als solches erkennbar');
  perform wamo_testhilfe.fehler($s$select display_name from __SCHEMA__.profiles$s$, '42501');
  perform wamo_testhilfe.fehler($s$select settings from __SCHEMA__.profiles$s$, '42501');
  perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.profiles$s$, '42501');
  perform wamo_testhilfe.fehler($s$select labor_aktiv from __SCHEMA__.profiles$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.profiles set aktiv = false$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.profiles set rolle = 'admin'$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.profiles set labor_aktiv = true$s$, '42501');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.profiles (user_id, display_name) values ('00000000-0000-4000-8000-0000000031a2', 'x')$s$, '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.profiles$s$, '42501');
  -- Audit: nur Werkzeuge mit werkstatt_, anlegen und zurücklesen, nie ändern, nie löschen
  insert into __SCHEMA__.actions (user_id, tool, risk, status, params, result)
    values ('00000000-0000-4000-8000-0000000031a1', 'werkstatt_karten_veroeffentlichen', 'critical', 'done', '{}'::jsonb, '{"anzahl":2}'::jsonb)
    returning id into a;
  perform wamo_testhilfe.gleich(a is not null, true, 'Audit-Zeile mit id zurück');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.actions (user_id, tool, risk) values ('00000000-0000-4000-8000-0000000031a1', 'jira_story_anlegen', 'change')$s$, '42501');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.actions (user_id, tool, risk) values ('00000000-0000-4000-8000-0000000031a1', 'werkstatt', 'change')$s$, '42501');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.actions (user_id, tool, risk) values ('00000000-0000-4000-8000-0000000031a1', 'werkstattx_y', 'change')$s$, '42501');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.actions where tool not like 'werkstatt\_%'), 0::bigint, 'fremde Audit-Zeilen sind unsichtbar');
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.actions where tool = 'werkstatt_karten_veroeffentlichen') >= 1, true, 'eigene Audit-Zeile sichtbar');
  perform wamo_testhilfe.fehler($s$select params from __SCHEMA__.actions$s$, '42501');
  perform wamo_testhilfe.fehler($s$select result from __SCHEMA__.actions$s$, '42501');
  perform wamo_testhilfe.fehler($s$update __SCHEMA__.actions set status = 'failed'$s$, '42501');
  perform wamo_testhilfe.fehler($s$delete from __SCHEMA__.actions$s$, '42501');
  -- alles andere im Schema bleibt zu: Gespräche, Gedächtnis, Stimmen, Geräte
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.sessions$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.turns$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.memories$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.speakers$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.canvas_items$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.feedback$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.devices$s$, '42501');
  perform wamo_testhilfe.fehler($s$select count(*) from __SCHEMA__.schema_migrations$s$, '42501');
  perform wamo_testhilfe.fehler($s$create table __SCHEMA__.werkstatt_probe (a int)$s$, '42501');
  perform wamo_testhilfe.gleich(has_schema_privilege('wamo_werkstatt', '__SCHEMA__', 'CREATE'), false, 'kein create im Schema');
end $$;
reset role;

-- 11. Fremde Rollen lesen, schreiben und rufen nichts
do $$
declare
  rolle text;
  obj text;
  objekte text[] := array['labor_termine', 'labor_plaetze', 'labor_checkliste', 'labor_karten', 'labor_zuordnung', 'labor_karten_versionen',
                          'werkstatt_karten', 'labor_wissen_aktiv', 'labor_karten_aktive_version'];
begin
  foreach rolle in array array['anon', 'authenticated', 'service_role', 'wamo_admin'] loop
    execute format('set role %I', rolle);
    foreach obj in array objekte loop
      perform wamo_testhilfe.fehler(format('select * from __SCHEMA__.%I', obj), '42501');
    end loop;
    perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.labor_termine (tag, aufbewahrung_bis) values ('2037-05-01', '2037-05-02')$s$, '42501');
    perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_sitzungen(7)$s$, '42501');
    perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_latenz(7)$s$, '42501');
    perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_aktionen(7)$s$, '42501');
    perform wamo_testhilfe.fehler($s$select * from __SCHEMA__.werkstatt_labor_stand()$s$, '42501');
    perform wamo_testhilfe.fehler($s$select __SCHEMA__.werkstatt_aufraeumen()$s$, '42501');
    reset role;
  end loop;
end $$;

rollback;
\echo 0031 OK
