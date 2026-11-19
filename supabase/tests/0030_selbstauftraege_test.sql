-- Test für 0030_selbstauftraege. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile, Aufträge
-- und vorübergehende Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev, nach dem Anwenden von 0030.
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0030_selbstauftraege_test.sql \
--     | ssh sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Erfolg: letzte Zeile "0030 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
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
-- wirklich an den Tabellenrechten scheitert und nicht schon am Schema
grant usage on schema __SCHEMA__ to anon, authenticated, service_role;

insert into auth.users (id, email) values ('00000000-0000-4000-8000-0000000030a1', 'selbst1@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv)
  values ('00000000-0000-4000-8000-0000000030a1', 'Selbst Eins', 'admin', true);

-- 1. Migration eingetragen, Tabelle da
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations where version = '0030_selbstauftraege'), 1::bigint,
                                'Migration eingetragen');
  perform wamo_testhilfe.gleich(to_regclass('__SCHEMA__.selbstauftraege') is not null, true, 'Tabelle');
end $$;

-- 2. Der Kern fügt ein wie voice-core/selbstauftraege.py (nur seine Spalten): die Datenbank vergibt nr, id, status und Zeiten
set role wamo_core;
do $$
declare
  a record;
  b record;
begin
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung, art, abnahme, prioritaet, quelle, unsicher, erstellt_von)
    values ('Mikrofon im Log', 'Die Mikrofonvorgaben in den Kern-Log schreiben.', 'umsetzung', '["Zeile im Log"]'::jsonb, 1, 'sprache', false,
            '00000000-0000-4000-8000-0000000030a1')
    returning * into a;
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('Zweiter', 'Zweite Beschreibung') returning * into b;
  perform wamo_testhilfe.gleich(a.status, 'offen', 'Status vorgegeben');
  perform wamo_testhilfe.gleich(b.prioritaet, 2::smallint, 'Priorität normal');
  perform wamo_testhilfe.gleich(b.art, 'umsetzung', 'Art vorgegeben');
  perform wamo_testhilfe.gleich(b.quelle, 'sprache', 'Quelle vorgegeben');
  perform wamo_testhilfe.gleich(b.unsicher, false, 'unsicher vorgegeben');
  perform wamo_testhilfe.gleich(b.nr > a.nr, true, 'nr zählt fort');
  perform wamo_testhilfe.gleich(a.bearbeiter is null and a.ergebnis is null and a.bearbeitet_at is null, true, 'noch niemand dran');
  perform wamo_testhilfe.gleich(a.erstellt_at is not null and a.geaendert_at is not null, true, 'Zeiten gesetzt');
end $$;
reset role;

-- 2b. Die Anweisungen des Kerns (voice-core/selbstauftraege.py) wörtlich, mit eingesetzten Werten statt $1 bis $8. Einfügen unter der
--     Tagesgrenze je Person, Liste, Verwerfen und Wieder öffnen. Ändert sich selbstauftraege.py, muss dieser Abschnitt mit
--     (voice-core/test_migration_0030.py prüft das).
set role wamo_core;
with neu as (
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung, art, abnahme, prioritaet, quelle, unsicher, erstellt_von)
  select 'Kern-Titel'::text, 'Kern-Beschreibung'::text, 'umsetzung'::text, '["Eine Zeile im Log"]'::text::jsonb, 1::smallint,
         'sprache'::text, false::boolean, '00000000-0000-4000-8000-0000000030a1'::uuid
  where (select count(*) from __SCHEMA__.selbstauftraege where erstellt_von = '00000000-0000-4000-8000-0000000030a1'::uuid
         and erstellt_at >= now() - interval '1 day') < 30
  returning nr
)
select wamo_testhilfe.gleich((select count(*) from neu), 1::bigint, 'Einfügen des Kerns legt eine Zeile an');
select wamo_testhilfe.gleich((select count(*) from (
  select nr, titel, art, prioritaet, status, quelle, unsicher, erstellt_at, bearbeiter, left(ergebnis, 300) as ergebnis, geaendert_at from __SCHEMA__.selbstauftraege where status in ('offen', 'in_arbeit') or nr in (select nr from __SCHEMA__.selbstauftraege where status in ('erledigt', 'verworfen') order by geaendert_at desc limit 10)
) liste), 3::bigint, 'Liste des Kerns');
-- Verwerfen und Wiedereröffnen: der Kern hat kein update und ruft die beiden Funktionen auf (Ergebnis die Nummer, null: nichts getroffen)
select wamo_testhilfe.gleich((select z.nr from (select __SCHEMA__.selbstauftrag_verwerfen((select max(nr) from __SCHEMA__.selbstauftraege)::bigint) as nr) z),
                             (select max(nr) from __SCHEMA__.selbstauftraege), 'Verwerfen des Kerns');
select wamo_testhilfe.gleich((select z.nr from (select __SCHEMA__.selbstauftrag_verwerfen((select max(nr) from __SCHEMA__.selbstauftraege)::bigint) as nr) z),
                             null::bigint, 'ein verworfener Auftrag lässt sich nicht noch einmal verwerfen');
select wamo_testhilfe.gleich((select z.nr from (select __SCHEMA__.selbstauftrag_oeffnen((select max(nr) from __SCHEMA__.selbstauftraege)::bigint) as nr) z),
                             (select max(nr) from __SCHEMA__.selbstauftraege), 'Wieder öffnen des Kerns');
select wamo_testhilfe.gleich((select z.nr from (select __SCHEMA__.selbstauftrag_oeffnen((select max(nr) from __SCHEMA__.selbstauftraege)::bigint) as nr) z),
                             null::bigint, 'ein offener Auftrag lässt sich nicht "wieder öffnen"');
select wamo_testhilfe.gleich((select z.nr from (select __SCHEMA__.selbstauftrag_verwerfen(999999999::bigint) as nr) z), null::bigint,
                             'eine unbekannte Nummer trifft nichts');
-- Tagesgrenze: 28 weitere Einträge dieser Person (zusammen 30 in 24 Stunden), dann findet der Einfügebefehl des Kerns nichts mehr
insert into __SCHEMA__.selbstauftraege (titel, beschreibung, erstellt_von)
  select 'Tageszähler ' || i, 'Text ' || i, '00000000-0000-4000-8000-0000000030a1'::uuid from generate_series(1, 28) i;
with neu as (
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung, art, abnahme, prioritaet, quelle, unsicher, erstellt_von)
  select 'Zu viel'::text, 'Zu viel'::text, 'umsetzung'::text, '[]'::text::jsonb, 2::smallint,
         'sprache'::text, false::boolean, '00000000-0000-4000-8000-0000000030a1'::uuid
  where (select count(*) from __SCHEMA__.selbstauftraege where erstellt_von = '00000000-0000-4000-8000-0000000030a1'::uuid
         and erstellt_at >= now() - interval '1 day') < 30
  returning nr
)
select wamo_testhilfe.gleich((select count(*) from neu), 0::bigint, 'am Tag höchstens 30 Einträge je Person');
reset role;

-- 3. Prüfregeln (als postgres, damit sie an der Regel scheitern und nicht an den Rechten)
do $$ begin
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('', 'x')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('   ', 'x')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values (repeat('T', 81), 'x')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values (E'zwei\nZeilen', 'x')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('t', '')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('t', repeat('b', 4001))$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, art) values ('t', 'b', 'Umsetzung')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, art) values ('t', 'b', 'a')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, prioritaet) values ('t', 'b', 0)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, prioritaet) values ('t', 'b', 4)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, quelle) values ('t', 'b', 'mail')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, status) values ('t', 'b', 'fertig')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, abnahme) values ('t', 'b', '{"a":1}'::jsonb)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, abnahme) values ('t', 'b', '[1]'::jsonb)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, abnahme)
    values ('t', 'b', '["1","2","3","4","5","6"]'::jsonb)$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, bearbeiter) values ('t', 'b', 'mensch')$s$, '23514');
  -- in Arbeit oder erledigt ohne Bearbeiter gibt es nicht
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, status) values ('t', 'b', 'in_arbeit')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, ergebnis) values ('t', 'b', '')$s$, '23514');
  perform wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, erstellt_von)
    values ('t', 'b', '00000000-0000-4000-8000-00000000ffff')$s$, '23503');
  -- genau 80 Zeichen und 4000 Zeichen gehen
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values (repeat('T', 80), repeat('b', 4000));
end $$;

-- 4. Der Kern darf nur seine Spalten einfügen und nur den Status ändern, nichts löschen
set role wamo_core;
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, status) values ('t', 'b', 'erledigt')$s$, '42501');
-- nr ist "generated always": schon die Spalte selbst lehnt einen eigenen Wert ab (428C9), vor jeder Rechteprüfung
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, nr) values ('t', 'b', 99)$s$, '428C9');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, bearbeiter) values ('t', 'b', 'wais')$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung, erstellt_at) values ('t', 'b', now() - interval '1 day')$s$, '42501');
-- kein einziges update auf der Tabelle, auch nicht auf den Stand: Den ändert der Kern nur über die beiden Funktionen (Abschnitt 2b und 5)
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set status = 'verworfen'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set status = 'erledigt'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set status = 'offen'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set titel = 'neu'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set beschreibung = 'neu'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set bearbeiter = 'wais'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set ergebnis = 'fertig'$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.selbstauftraege$s$, '42501');
select wamo_testhilfe.fehler($s$truncate __SCHEMA__.selbstauftraege$s$, '42501');
reset role;

-- 5. Statusübergänge. Verwerfen und wieder öffnen tut der Kern über die beiden Funktionen, in Arbeit und erledigt setzt der Bearbeiter (hier
--    postgres). Der Kern kann einen laufenden Auftrag weder zurückstellen noch abschließen (Befund der Prüfung vom 19.11.2026).
set role wamo_core;
do $$
declare
  nr_a bigint := (select min(nr) from __SCHEMA__.selbstauftraege);
  r bigint;
  z record;
begin
  r := __SCHEMA__.selbstauftrag_verwerfen(nr_a);
  perform wamo_testhilfe.gleich(r, nr_a, 'Verwerfen liefert die Nummer');
  select * into z from __SCHEMA__.selbstauftraege where nr = nr_a;
  perform wamo_testhilfe.gleich(z.status, 'verworfen', 'verworfen');
  r := __SCHEMA__.selbstauftrag_oeffnen(nr_a);
  select * into z from __SCHEMA__.selbstauftraege where nr = nr_a;
  perform wamo_testhilfe.gleich(z.status, 'offen', 'wieder offen');
  perform wamo_testhilfe.gleich(z.bearbeiter is null and z.bearbeitet_at is null, true, 'wieder offen ohne Bearbeiter');
  -- der Kern kann nichts direkt setzen
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'erledigt', nr_a), '42501');
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'in_arbeit', nr_a), '42501');
end $$;
reset role;
do $$
declare
  nr_a bigint := (select min(nr) from __SCHEMA__.selbstauftraege);
  z record;
begin
  update __SCHEMA__.selbstauftraege set status = 'in_arbeit', bearbeiter = 'claude_code' where nr = nr_a returning * into z;
  perform wamo_testhilfe.gleich(z.bearbeitet_at is not null, true, 'in Arbeit gestempelt');
end $$;
-- Der Auftrag ist in Arbeit: Der Kern kann ihn nicht öffnen, nicht abschließen und nicht zurückstellen, nur verwerfen (das darf er)
set role wamo_core;
do $$
declare
  nr_a bigint := (select min(nr) from __SCHEMA__.selbstauftraege);
  r bigint;
  z record;
begin
  r := __SCHEMA__.selbstauftrag_oeffnen(nr_a);
  perform wamo_testhilfe.gleich(r, null::bigint, 'ein laufender Auftrag lässt sich vom Kern nicht öffnen');
  select * into z from __SCHEMA__.selbstauftraege where nr = nr_a;
  perform wamo_testhilfe.gleich(z.status, 'in_arbeit', 'Stand unverändert');
  perform wamo_testhilfe.gleich(z.bearbeiter, 'claude_code', 'Bearbeiter unverändert');
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'offen', nr_a), '42501');
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'erledigt', nr_a), '42501');
end $$;
reset role;
do $$
declare
  nr_a bigint := (select min(nr) from __SCHEMA__.selbstauftraege);
  nr_z bigint := (select max(nr) from __SCHEMA__.selbstauftraege);
  z record;
begin
  update __SCHEMA__.selbstauftraege set status = 'erledigt', ergebnis = 'Pull Request 1' where nr = nr_a returning * into z;
  perform wamo_testhilfe.gleich(z.status, 'erledigt', 'erledigt');
  perform wamo_testhilfe.gleich(z.bearbeiter, 'claude_code', 'Bearbeiter bleibt');
  -- ein erledigter Auftrag bleibt erledigt: weder offen noch verworfen noch in Arbeit
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'offen', nr_a), '23514');
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'verworfen', nr_a), '23514');
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L where nr = %s', 'in_arbeit', nr_a), '23514');
  perform wamo_testhilfe.gleich(__SCHEMA__.selbstauftrag_verwerfen(nr_a), null::bigint, 'ein erledigter Auftrag lässt sich nicht verwerfen');
  -- verworfen -> in_arbeit gibt es nicht (erst wieder öffnen)
  update __SCHEMA__.selbstauftraege set status = 'verworfen' where nr = nr_z;
  perform wamo_testhilfe.fehler(format('update __SCHEMA__.selbstauftraege set status = %L, bearbeiter = %L where nr = %s', 'in_arbeit',
                                       'wais', nr_z), '23514');
end $$;

-- 6. Grenze: höchstens 200 offene oder laufende. Der Kern füllt bis 200, die nächste Einfügung scheitert am Trigger (der Kern erkennt die
--    Grenze am Namen), Verwerfen macht wieder Platz. Auch das Wiedereröffnen hält die Grenze (Befund der Prüfung vom 19.11.2026: sonst
--    ließen sich über verworfene Einträge beliebig viele offene schaffen).
set role wamo_core;
do $$
declare
  frei int := 200 - (select count(*) from __SCHEMA__.selbstauftraege where status in ('offen', 'in_arbeit'));
begin
  insert into __SCHEMA__.selbstauftraege (titel, beschreibung) select 'Auftrag ' || i, 'Text ' || i from generate_series(1, frei) i;
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.selbstauftraege where status in ('offen', 'in_arbeit')), 200::bigint, 'voll');
end $$;
reset role;
do $$
declare
  grenze text;
begin
  begin
    insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('zu viel', 'zu viel');
  exception when check_violation then
    get stacked diagnostics grenze = constraint_name;
    perform wamo_testhilfe.gleich(grenze, 'selbstauftraege_grenze', 'Name der Grenze');
    update __SCHEMA__.selbstauftraege set status = 'verworfen'
      where nr = (select max(nr) from __SCHEMA__.selbstauftraege where status = 'offen');
    insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('wieder Platz', 'wieder Platz');
    return;
  end;
  raise exception 'die 201. Einfügung ging durch';
end $$;
-- 200 offene, dazu verworfene Einträge: Wiedereröffnen durch den Kern scheitert mit demselben Namen der Grenze, nach einem Verwerfen geht es
set role wamo_core;
do $$
declare
  nr_v bigint := (select max(nr) from __SCHEMA__.selbstauftraege where status = 'verworfen');
  grenze text;
begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.selbstauftraege where status in ('offen', 'in_arbeit')), 200::bigint, 'noch voll');
  begin
    perform __SCHEMA__.selbstauftrag_oeffnen(nr_v);
  exception when check_violation then
    get stacked diagnostics grenze = constraint_name;
    perform wamo_testhilfe.gleich(grenze, 'selbstauftraege_grenze', 'Wiedereröffnen über der Grenze scheitert mit dem Namen der Grenze');
    perform wamo_testhilfe.gleich((select status from __SCHEMA__.selbstauftraege where nr = nr_v), 'verworfen', 'bleibt verworfen');
    perform __SCHEMA__.selbstauftrag_verwerfen((select max(nr) from __SCHEMA__.selbstauftraege where status = 'offen'));
    perform wamo_testhilfe.gleich(__SCHEMA__.selbstauftrag_oeffnen(nr_v), nr_v, 'mit freiem Platz geht das Wiedereröffnen');
    return;
  end;
  raise exception 'das Wiedereröffnen ging über der Grenze durch';
end $$;
reset role;

-- 7. Fremde Rollen lesen und schreiben nichts
set role wamo_admin;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.selbstauftraege$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.selbstauftraege (titel, beschreibung) values ('t', 'b')$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.selbstauftraege$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.selbstauftraege$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.selbstauftraege set status = 'verworfen'$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.selbstauftraege$s$, '42501');
reset role;

-- 8. Wird das Profil gelöscht, bleibt der Auftrag (der Rückstand gehört W.A.I.S.)
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.selbstauftraege
                                  where erstellt_von = '00000000-0000-4000-8000-0000000030a1'), 30::bigint, 'dreißig Aufträge des Profils');
  delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000030a1';
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.selbstauftraege where erstellt_von is null and titel = 'Mikrofon im Log'),
                                1::bigint, 'Auftrag bleibt ohne Profil');
end $$;

-- 9. Zweiter Lauf der Rechte ändert nichts
revoke all on __SCHEMA__.selbstauftraege from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant select on __SCHEMA__.selbstauftraege to wamo_core;
grant insert (titel, beschreibung, art, abnahme, prioritaet, quelle, unsicher, erstellt_von) on __SCHEMA__.selbstauftraege to wamo_core;
grant update (status) on __SCHEMA__.selbstauftraege to wamo_core;
do $$ begin
  if not has_column_privilege('wamo_core', '__SCHEMA__.selbstauftraege', 'status', 'UPDATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.selbstauftraege', 'titel', 'UPDATE')
     or has_table_privilege('wamo_core', '__SCHEMA__.selbstauftraege', 'DELETE') then
    raise exception 'Rechte nach zweitem Lauf falsch';
  end if;
end $$;

rollback;
\echo 0030 OK
