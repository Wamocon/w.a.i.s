-- Test für wamo_auth.sql (Erstanmeldung je Konto). Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird.
-- Aufruf über "wamo-auth-einrichten.sh test" (setzt ON_ERROR_STOP). Voraussetzung: wamo_auth ist eingerichtet. Erfolg: letzte Zeile
-- "wamo_auth OK". Gibt es das Schema wamo_test mit Migration 0021, prüft der Test dort zusätzlich die Hinweise an die Admins.
-- Geprüft wird (Planpapier Abschnitt 6.1, P1a):
--   1. Rechte: RLS an, keine Rechte für anon, authenticated, service_role; wamo_core nur execute auf Stand und Beginn
--   2. Stände keine, offen, abgelaufen, erledigt; abgelaufen bleibt, auch wenn sich der Hash später ändert
--   3. Trigger nur bei echter Änderung des Hashes, nicht bei anderen Spalten, nicht beim Startwert
--   4. Trigger blockiert GoTrue nie (auch nicht, wenn seine Tabelle fehlt)
--   5. Beginn genau einmal; Anlegen ersetzt den Merker; Option Ü (erledigt sofort); Löschen des Kontos löscht den Merker
\set ON_ERROR_STOP 1
begin;
set local lock_timeout = '2s';

grant wamo_core to postgres;
create schema wamo_authtest;
create function wamo_authtest.fehler(p_sql text, p_code text) returns void language plpgsql as $f$
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
create function wamo_authtest.gleich(p_ist anyelement, p_soll anyelement, p_was text) returns void language plpgsql as $f$
begin
  if p_ist is distinct from p_soll then raise exception '%: ist %, soll %', p_was, p_ist, p_soll; end if;
end $f$;
grant usage on schema wamo_authtest to wamo_core;
grant execute on all functions in schema wamo_authtest to wamo_core;

-- ---------- 1. Rechte ----------
do $$
declare
  r text;
begin
  perform wamo_authtest.gleich((select relrowsecurity from pg_class where oid = 'wamo_auth.erstanmeldungen'::regclass), true, 'RLS an');
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    perform wamo_authtest.gleich(has_schema_privilege(r, 'wamo_auth', 'usage'), false, r || ' usage auf wamo_auth');
    perform wamo_authtest.gleich(has_table_privilege(r, 'wamo_auth.erstanmeldungen', 'select,insert,update,delete'), false,
                                 r || ' Rechte auf erstanmeldungen');
    perform wamo_authtest.gleich(has_function_privilege(r, 'wamo_auth.erstanmeldung_stand(uuid)', 'execute'), false, r || ' stand');
    perform wamo_authtest.gleich(has_function_privilege(r, 'wamo_auth.erstanmeldung_begonnen(uuid)', 'execute'), false, r || ' begonnen');
    perform wamo_authtest.gleich(has_function_privilege(r, 'wamo_auth.erstanmeldung_anlegen(uuid,integer,text,boolean)', 'execute'), false,
                                 r || ' anlegen');
  end loop;
  perform wamo_authtest.gleich(has_schema_privilege('wamo_core', 'wamo_auth', 'usage'), true, 'wamo_core usage');
  perform wamo_authtest.gleich(has_function_privilege('wamo_core', 'wamo_auth.erstanmeldung_stand(uuid)', 'execute'), true, 'wamo_core stand');
  perform wamo_authtest.gleich(has_function_privilege('wamo_core', 'wamo_auth.erstanmeldung_begonnen(uuid)', 'execute'), true,
                               'wamo_core begonnen');
  perform wamo_authtest.gleich(has_function_privilege('wamo_core', 'wamo_auth.erstanmeldung_anlegen(uuid,integer,text,boolean)', 'execute'),
                               false, 'wamo_core anlegen');
  perform wamo_authtest.gleich(has_function_privilege('wamo_core', 'wamo_auth.erstanmeldung_uebersicht()', 'execute'), false,
                               'wamo_core uebersicht');
  perform wamo_authtest.gleich(has_function_privilege('wamo_core', 'wamo_auth.hinweis_senden(uuid,text)', 'execute'), false,
                               'wamo_core hinweis_senden');
  perform wamo_authtest.gleich(has_table_privilege('wamo_core', 'wamo_auth.erstanmeldungen', 'select,insert,update,delete'), false,
                               'wamo_core Tabelle');
  perform wamo_authtest.gleich((select count(*)::int from pg_trigger where tgname = 'wamo_auth_passwort_geaendert'
                                 and tgrelid = 'auth.users'::regclass and tgenabled = 'O'), 1, 'Trigger aktiv');
  -- katalogweit: PUBLIC nirgends, wamo_core nur execute auf Stand und Beginn, auf der Tabelle niemand außer dem Besitzer
  perform wamo_authtest.gleich((select count(*)::int from pg_proc p, aclexplode(p.proacl) a
                                 where p.pronamespace = 'wamo_auth'::regnamespace and a.grantee = 0), 0, 'PUBLIC auf Funktionen');
  perform wamo_authtest.gleich((select string_agg(p.proname, ',' order by p.proname) from pg_proc p, aclexplode(p.proacl) a
                                 where p.pronamespace = 'wamo_auth'::regnamespace and a.grantee <> p.proowner),
                               'erstanmeldung_begonnen,erstanmeldung_stand', 'Rechte auf Funktionen nur für wamo_core');
  perform wamo_authtest.gleich((select count(*)::int from pg_class c, aclexplode(c.relacl) a
                                 where c.oid = 'wamo_auth.erstanmeldungen'::regclass and a.grantee <> c.relowner), 0,
                               'Rechte auf der Tabelle');
end $$;

-- ---------- Testkonten ----------
insert into auth.users (id, email, encrypted_password) values
  ('00000000-0000-4000-8000-00000000a001', 'erst-a@wamo-test.invalid', 'start-a'),
  ('00000000-0000-4000-8000-00000000a002', 'erst-b@wamo-test.invalid', 'start-b'),
  ('00000000-0000-4000-8000-00000000a003', 'erst-c@wamo-test.invalid', 'start-c'),
  ('00000000-0000-4000-8000-00000000a004', 'erst-d@wamo-test.invalid', 'start-d'),
  ('00000000-0000-4000-8000-00000000a005', 'erst-e@wamo-test.invalid', null);

-- ---------- 2. Stände ----------
do $$
declare
  a uuid := '00000000-0000-4000-8000-00000000a001';
  b uuid := '00000000-0000-4000-8000-00000000a002';
  v timestamptz;
begin
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'keine', 'ohne Merker');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_stand(null)$q$, '22004');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_begonnen(null)$q$, '22004');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000afff', 72, 'freischalten')$q$, 'P0002');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000a001', 0, 'freischalten')$q$, '22023');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000a001', 169, 'freischalten')$q$, '22023');
  perform wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000a001', 72, 'kern')$q$, '23514');

  v := wamo_auth.erstanmeldung_anlegen(a, 72, 'freischalten');
  perform wamo_authtest.gleich(v, now() + interval '72 hours', 'Frist 72 Stunden');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'nach Anlegen');
  perform wamo_authtest.gleich((select start_hash from wamo_auth.erstanmeldungen where user_id = a),
                               encode(sha256(convert_to('start-a', 'UTF8')), 'hex'), 'start_hash ist SHA-256 des Hashes');

  -- abgelaufen: Frist in der Vergangenheit (angelegt_at mitziehen, sonst greift die Prüfung der Frist)
  perform wamo_auth.erstanmeldung_anlegen(b, 1, 'freischalten');
  update wamo_auth.erstanmeldungen set angelegt_at = now() - interval '3 hours', frist_bis = now() - interval '2 hours' where user_id = b;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(b), 'abgelaufen', 'Frist vorbei');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(b), false, 'begonnen nicht bei abgelaufen');
  update auth.users set encrypted_password = 'neu-b' where id = b;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(b), 'abgelaufen', 'abgelaufen bleibt nach spätem Wechsel');
end $$;

-- ---------- 3. Trigger und Beginn ----------
do $$
declare
  a uuid := '00000000-0000-4000-8000-00000000a001';
  c uuid := '00000000-0000-4000-8000-00000000a003';
begin
  -- andere Spalte, gleicher Hash: nichts
  update auth.users set last_sign_in_at = now() where id = a;
  update auth.users set encrypted_password = encrypted_password where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'kein Wechsel, bleibt offen');

  -- Wechsel während der Sperre in GoTrue (Admin-Skript): zählt nicht
  update auth.users set banned_until = now() + interval '876000 hours' where id = a;
  update auth.users set encrypted_password = 'admin-a' where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'Wechsel im gesperrten Konto zählt nicht');
  update auth.users set banned_until = null, encrypted_password = 'start-a' where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'zurück auf den Startwert ist kein Wechsel');

  -- Beginn genau einmal
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(a), true, 'begonnen erstes Mal');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(a), false, 'begonnen zweites Mal');
  perform wamo_authtest.gleich((select begonnen_at is not null from wamo_auth.erstanmeldungen where user_id = a), true, 'begonnen_at gesetzt');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(c), false, 'begonnen ohne Merker');

  -- echter Wechsel: erledigt
  update auth.users set encrypted_password = 'neu-a' where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'erledigt', 'nach Wechsel');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(a), false, 'begonnen nicht bei erledigt');

  -- Merker ersetzen: neuer Startwert, Beginn und Erledigung leer
  perform wamo_auth.erstanmeldung_anlegen(a, 24, 'zuruecksetzen');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'nach Zurücksetzen');
  perform wamo_authtest.gleich((select begonnen_at from wamo_auth.erstanmeldungen where user_id = a), null::timestamptz, 'begonnen geleert');
  -- zurück auf den alten Startwert zählt nicht, nur ein neuer Hash (der Startwert ist jetzt neu-a)
  update auth.users set encrypted_password = 'neu-a' where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'offen', 'gleicher Wert ist kein Wechsel');
  update auth.users set encrypted_password = 'start-a' where id = a;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(a), 'erledigt', 'anderer Wert ist ein Wechsel');

  -- Option Ü: sofort erledigt
  perform wamo_auth.erstanmeldung_anlegen(c, 72, 'passwort', true);
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(c), 'erledigt', 'Option Ü');

  -- Konto ohne Hash (null)
  perform wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000a005', 72, 'freischalten');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand('00000000-0000-4000-8000-00000000a005'), 'offen', 'ohne Hash offen');

  -- Übersicht
  perform wamo_authtest.gleich((select count(*)::int from wamo_auth.erstanmeldung_uebersicht()
                                 where user_id::text like '00000000-0000-4000-8000-00000000a00%'), 4, 'Übersicht');
end $$;

-- ---------- wamo_core: nur Stand und Beginn ----------
set local role wamo_core;
select wamo_authtest.gleich(wamo_auth.erstanmeldung_stand('00000000-0000-4000-8000-00000000a003'), 'erledigt', 'Stand als wamo_core');
select wamo_authtest.fehler($q$select * from wamo_auth.erstanmeldungen$q$, '42501');
select wamo_authtest.fehler($q$update wamo_auth.erstanmeldungen set erledigt_at = null$q$, '42501');
select wamo_authtest.fehler($q$select wamo_auth.erstanmeldung_anlegen('00000000-0000-4000-8000-00000000a003', 72, 'freischalten')$q$, '42501');
select wamo_authtest.fehler($q$select wamo_auth.hinweis_senden('00000000-0000-4000-8000-00000000a003', 'erstanmeldung_erledigt')$q$, '42501');
select wamo_authtest.fehler($q$select * from wamo_auth.erstanmeldung_uebersicht()$q$, '42501');
reset role;

-- ---------- 4. Der Trigger blockiert GoTrue nie ----------
do $$
declare
  d uuid := '00000000-0000-4000-8000-00000000a004';
begin
  perform wamo_auth.erstanmeldung_anlegen(d, 72, 'freischalten');
  alter table wamo_auth.erstanmeldungen rename to erstanmeldungen_weg;
  update auth.users set encrypted_password = 'neu-d' where id = d;   -- darf nicht scheitern
  perform wamo_authtest.gleich((select encrypted_password from auth.users where id = d), 'neu-d', 'Wechsel trotz kaputtem Merker');
  alter table wamo_auth.erstanmeldungen_weg rename to erstanmeldungen;
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(d), 'offen', 'Merker unverändert, Wechsel wurde nicht gezählt');
end $$;

-- ---------- 5. Löschen des Kontos löscht den Merker ----------
delete from auth.users where id = '00000000-0000-4000-8000-00000000a004';
select wamo_authtest.gleich((select count(*)::int from wamo_auth.erstanmeldungen where user_id = '00000000-0000-4000-8000-00000000a004'), 0,
                            'Merker mit Konto gelöscht');

-- ---------- Hinweise an die Admins (nur wenn wamo_test mit 0021 da ist) ----------
do $$
declare
  e uuid := '00000000-0000-4000-8000-00000000a002';
  adm uuid := '00000000-0000-4000-8000-00000000a003';
begin
  if not exists (select 1 from information_schema.tables where table_schema = 'wamo_test' and table_name = 'schema_migrations') then
    raise notice 'ohne Schema wamo_test: Hinweise nicht geprüft';
    return;
  end if;
  if not exists (select 1 from wamo_test.schema_migrations where version = '0021_profil_freischaltung') then
    raise notice 'wamo_test ohne 0021: Hinweise nicht geprüft';
    return;
  end if;
  insert into wamo_test.profiles (user_id, display_name, rolle, aktiv) values (adm, 'Test-Admin A003', 'admin', false);
  perform wamo_auth.erstanmeldung_anlegen(adm, 72, 'freischalten');
  update wamo_test.profiles set aktiv = true where user_id = adm;
  insert into wamo_test.profiles (user_id, display_name, rolle, aktiv) values (e, 'Test-Mitglied A002', 'mitglied', false);
  perform wamo_auth.erstanmeldung_anlegen(e, 72, 'freischalten');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_begonnen(e), true, 'begonnen mit Profil');
  perform wamo_authtest.gleich((select count(*)::int from wamo_test.hinweise where empfaenger = adm and art = 'erstanmeldung_begonnen'
                                 and bezug = e), 1, 'Hinweis begonnen');
  update auth.users set encrypted_password = 'zweites-b' where id = e;
  perform wamo_authtest.gleich((select count(*)::int from wamo_test.hinweise where empfaenger = adm and art = 'erstanmeldung_erledigt'
                                 and bezug = e), 1, 'Hinweis erledigt');
  perform wamo_authtest.gleich(wamo_auth.erstanmeldung_stand(e), 'erledigt', 'erledigt mit Profil');
end $$;

select 'wamo_auth OK';
rollback;
