-- Test für 0027_github_zugang. Läuft als postgres in EINER Transaktion, die am Ende immer zurückgerollt wird (Testkonten, Profile, Tokens
-- und Rechte verschwinden wieder). Nur für wamo_test oder wamo_dev. Wird von Hand ausgeführt, nicht von der CI:
--   sed "s/__SCHEMA__/wamo_test/g" supabase/tests/0027_github_zugang_test.sql \
--     | ssh wamo-sokrates2 "docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 -q"
-- Voraussetzung: 0001, 0018 und 0027 sind im Schema angewendet.
-- Der Nachlauf der Migration (zweimal anwenden, der zweite Lauf ändert nichts) ist NICHT Teil dieses Tests: Wer ihn prüfen will, wendet
-- 0027_github_zugang.sql vorher zweimal nacheinander an (Aufruf im Kopf der Migration); der zweite Lauf muss ohne Fehler durchgehen. Der
-- Rückweg läuft am Ende in einem Sicherungspunkt mit den Anweisungen aus 0027_github_zugang.down.sql und wird zurückgerollt.
-- Erfolg: letzte Zeile "0027 OK", Exit-Code 0. Jeder Fehlschlag bricht mit einer Meldung ab.
-- Die Anweisungen des Kerns (voice-core/github_zugang.py) stehen hier wörtlich, die Platzhalter $n durch Werte ersetzt;
-- voice-core/test_migration_0027.py prüft, dass sie mit denen des Kerns übereinstimmen. Das Chiffrat ist hier eine Attrappe (48 Byte).
\set ON_ERROR_STOP 1
begin;
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' then raise exception 'Test nie in wamo_prod'; end if;
end $$;

grant wamo_core, wamo_admin to postgres;
create schema wamo_testhilfe;
grant usage on schema wamo_testhilfe to wamo_core, wamo_admin, anon, authenticated, service_role;
-- erwartet einen Fehler mit genau diesem SQLSTATE
create function wamo_testhilfe.fehler(p_sql text, p_code text) returns void language plpgsql as $f$
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

-- Testkonten mit Profilen: a1 Mitglied, a2 aktiver Admin, a3 gesperrter Admin, a4 Schau-Profil des Labors (ohne Platz, kein Konflikt mit
-- echten Plätzen)
insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000027a1', 'github-eins@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000027a2', 'github-admin@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000027a3', 'github-gesperrt@wamo-test.invalid'),
  ('00000000-0000-4000-8000-0000000027a4', 'github-labor@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values
  ('00000000-0000-4000-8000-0000000027a1', 'GitHub Eins', 'mitglied', true),
  ('00000000-0000-4000-8000-0000000027a2', 'GitHub Admin', 'admin', true),
  ('00000000-0000-4000-8000-0000000027a3', 'GitHub Gesperrt', 'admin', false);
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv, labor_art, labor_platz) values
  ('00000000-0000-4000-8000-0000000027a4', 'Gast', 'mitglied', false, 'schaufenster', null);

-- 1. Migration eingetragen, Tabellen mit Zeilensicherheit, Policies, Fremdschlüssel, Index, Prüfungen, Trigger
do $$ begin
  perform wamo_testhilfe.gleich((select count(*) from __SCHEMA__.schema_migrations where version = '0027_github_zugang'), 1::bigint, 'Migration eingetragen');
  perform wamo_testhilfe.gleich((select count(*) from pg_class c where c.oid in ('__SCHEMA__.github_zugang'::regclass, '__SCHEMA__.github_rechte'::regclass)
                                   and c.relrowsecurity), 2::bigint, 'RLS an (relrowsecurity)');
  perform wamo_testhilfe.gleich((select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'github_zugang'), 2::bigint,
                                'zwei Policies auf github_zugang (core_all, admin_lesen)');
  perform wamo_testhilfe.gleich((select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'github_rechte'
                                   and policyname = 'core_all'), 1::bigint, 'Policy core_all auf github_rechte');
  perform wamo_testhilfe.gleich((select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'github_rechte'), 1::bigint,
                                'nur eine Policy auf github_rechte');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.github_zugang'::regclass
                                   and contype = 'f' and confrelid = '__SCHEMA__.profiles'::regclass), 1::bigint, 'Fremdschlüssel github_zugang');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.github_rechte'::regclass
                                   and contype = 'f' and confrelid = '__SCHEMA__.profiles'::regclass), 2::bigint, 'zwei Fremdschlüssel github_rechte');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid in ('__SCHEMA__.github_zugang'::regclass, '__SCHEMA__.github_rechte'::regclass)
                                   and confrelid = 'auth.users'::regclass), 0::bigint, 'kein Fremdschlüssel auf auth.users');
  perform wamo_testhilfe.gleich((select count(*) from pg_indexes where schemaname = '__SCHEMA__' and tablename = 'github_rechte'
                                   and indexname = 'github_rechte_geaendert_von_idx'), 1::bigint, 'partieller Index für geaendert_von');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.github_zugang'::regclass
                                   and contype = 'c' and convalidated and conname like 'github_zugang_%_chk'), 7::bigint, 'sieben Prüfungen github_zugang');
  perform wamo_testhilfe.gleich((select count(*) from pg_constraint where conrelid = '__SCHEMA__.github_rechte'::regclass
                                   and contype = 'c' and convalidated and conname like 'github_rechte_%_chk'), 3::bigint, 'drei Prüfungen github_rechte');
  perform wamo_testhilfe.gleich((select count(*) from pg_trigger where tgname in ('github_zugang_guard', 'github_rechte_guard') and not tgisinternal
                                   and tgrelid in ('__SCHEMA__.github_zugang'::regclass, '__SCHEMA__.github_rechte'::regclass)), 2::bigint, 'zwei Trigger');
  perform wamo_testhilfe.gleich(has_function_privilege('wamo_core', '__SCHEMA__.github_zugang_guard()', 'EXECUTE'), false,
                                'Triggerfunktion nicht direkt aufrufbar');
end $$;

-- 2. wamo_core: die Anweisungen des Kerns. Speichern (Einfügen und Ersetzen), Stand, Token für genau einen Aufruf, erneut geprüft, Löschen
set role wamo_core;
insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a1'::uuid, 'klassisch', decode(repeat('ab', 48), 'hex'), 'Zz99', 'github-eins', 4711, array['repo','read:org']::text[], now() + interval '90 days') on conflict (user_id) do update set art = excluded.art, token = excluded.token, token_ende = excluded.token_ende, login = excluded.login, konto_id = excluded.konto_id, scopes = excluded.scopes, ablauf = excluded.ablauf;
select wamo_testhilfe.gleich((select login from (
  select art, token_ende, login, konto_id, scopes, ablauf, geprueft_at, angelegt_at from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a1'::uuid
) s), 'github-eins', 'Stand des Kerns');
select wamo_testhilfe.gleich((select labor_art from (
  select g.art, g.token, g.scopes, g.ablauf, p.labor_art from __SCHEMA__.github_zugang g join __SCHEMA__.profiles p on p.user_id = g.user_id where g.user_id = '00000000-0000-4000-8000-0000000027a1'::uuid
) s), null::text, 'Token mit labor_art für genau einen Aufruf');
select wamo_testhilfe.gleich((select octet_length(token) from (
  select g.art, g.token, g.scopes, g.ablauf, p.labor_art from __SCHEMA__.github_zugang g join __SCHEMA__.profiles p on p.user_id = g.user_id where g.user_id = '00000000-0000-4000-8000-0000000027a1'::uuid
) s), 48, 'Chiffrat lesbar für den Kern');
reset role;
-- Zeitpunkte setzt die Datenbank: zurückdatieren als postgres, dann sieht man, dass der Kern sie nicht festhalten kann
alter table __SCHEMA__.github_zugang disable trigger github_zugang_guard;
update __SCHEMA__.github_zugang set angelegt_at = now() - interval '5 days', geprueft_at = now() - interval '5 days'
 where user_id = '00000000-0000-4000-8000-0000000027a1';
alter table __SCHEMA__.github_zugang enable trigger github_zugang_guard;
set role wamo_core;
-- erneut geprüft: geprueft_at neu, angelegt_at bleibt (gleiches Token)
update __SCHEMA__.github_zugang set login = 'github-eins', konto_id = 4711, scopes = array['repo']::text[], ablauf = now() + interval '80 days' where user_id = '00000000-0000-4000-8000-0000000027a1'::uuid;
select wamo_testhilfe.gleich((select geprueft_at > now() - interval '1 minute' and angelegt_at < now() - interval '4 days'
                                from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a1'), true,
                             'Prüfen setzt geprueft_at, angelegt_at bleibt');
-- ersetzt mit neuem Token: angelegt_at neu
insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a1'::uuid, 'fein', decode(repeat('cd', 48), 'hex'), 'Q9Q9', 'github-eins', 4711, array[]::text[], now() + interval '30 days') on conflict (user_id) do update set art = excluded.art, token = excluded.token, token_ende = excluded.token_ende, login = excluded.login, konto_id = excluded.konto_id, scopes = excluded.scopes, ablauf = excluded.ablauf;
select wamo_testhilfe.gleich((select angelegt_at > now() - interval '1 minute' and art = 'fein' and cardinality(scopes) = 0
                                from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a1'), true,
                             'neues Token: angelegt_at neu, Art fein ohne Rechte');
-- nicht erlaubt: Zeitpunkte setzen, user_id ändern, leeren
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_zugang set geprueft_at = now() - interval '1 year'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_zugang set angelegt_at = now() - interval '1 year'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_zugang set user_id = '00000000-0000-4000-8000-0000000027a2'$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf, angelegt_at) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, now() + interval '1 day', now() - interval '1 year')$s$, '42501');
select wamo_testhilfe.fehler($s$truncate __SCHEMA__.github_zugang$s$, '42501');
-- Laborprofil: kein Einfügen (Trigger)
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a4', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'gast', 1, now() + interval '1 day')$s$, '42501');
reset role;

-- 3. Prüfregeln (als wamo_core, wie der Kern einfügt; Profil a2 ist noch frei)
set role wamo_core;
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'oauth', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 10), 'hex'), 'abcd', 'admin', 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 1100), 'hex'), 'abcd', 'admin', 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'ab-d', 'admin', 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', '-admin', 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', repeat('a', 40), 1, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 0, now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, array['repo'], now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, array['Repo'], now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, array['repo', ''], now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, array['repo', null], now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, array[array['repo'], array['gist']], now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, (select array_agg('s' || g) from generate_series(1, 31) g), now() + interval '1 day')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id) values ('00000000-0000-4000-8000-0000000027a2', 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1)$s$, '23502');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, ablauf) values (gen_random_uuid(), 'fein', decode(repeat('ab', 48), 'hex'), 'abcd', 'admin', 1, now() + interval '1 day')$s$, '42501');
-- die Grenzen des Kerns passen: 30 Rechte zu 40 Zeichen, Login mit 39 Zeichen, Chiffrat eines 93 Zeichen langen Tokens (2 + 4 + 12 + 93 + 16 Byte)
insert into __SCHEMA__.github_zugang (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) values
  ('00000000-0000-4000-8000-0000000027a2', 'klassisch', decode(repeat('ab', 127), 'hex'), 'a_1Z', 'a' || repeat('-b', 19),
   9007199254740993, (select array_agg('a' || repeat('b', 37) || lpad(g::text, 2, '0')) from generate_series(1, 30) g), now() + interval '366 days');
reset role;

-- 4. wamo_admin liest nur Kennung, Art, Login, Ablauf und Prüfzeit; anon, authenticated und service_role nichts
set role wamo_admin;
select wamo_testhilfe.gleich((select count(*) from (select user_id, art, login, ablauf, geprueft_at from __SCHEMA__.github_zugang) a), 2::bigint,
                             'wamo_admin liest die erlaubten Spalten');
select wamo_testhilfe.fehler($s$select token from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select token_ende from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select scopes from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select konto_id from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select * from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_zugang set login = 'x'$s$, '42501');
select wamo_testhilfe.fehler($s$select scopes_ausnahmen from __SCHEMA__.github_rechte$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a1', array['gist'], '00000000-0000-4000-8000-0000000027a2')$s$, '42501');
reset role;
set role anon;
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_rechte$s$, '42501');
reset role;
set role authenticated;
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_rechte$s$, '42501');
reset role;
set role service_role;
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_zugang$s$, '42501');
select wamo_testhilfe.fehler($s$select user_id from __SCHEMA__.github_rechte$s$, '42501');
reset role;

-- 5. github_rechte: nur ein aktiver Admin als geaendert_von, nur Scopes aus SCOPES_AUSNAHMEN, nie einer aus SCOPES_NIE
set role wamo_core;
select wamo_testhilfe.gleich((select count(*) from (select scopes_ausnahmen from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a1'::uuid) r),
                             0::bigint, 'ohne Zeile gilt der Standard');
insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a1'::uuid, array['workflow','gist']::text[], '00000000-0000-4000-8000-0000000027a2'::uuid) on conflict (user_id) do update set scopes_ausnahmen = excluded.scopes_ausnahmen, geaendert_von = excluded.geaendert_von;
insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a1'::uuid, array['workflow']::text[], '00000000-0000-4000-8000-0000000027a2'::uuid) on conflict (user_id) do update set scopes_ausnahmen = excluded.scopes_ausnahmen, geaendert_von = excluded.geaendert_von;
select wamo_testhilfe.gleich((select scopes_ausnahmen from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a1'::uuid),
                             array['workflow']::text[], 'Rechte ersetzt');
select wamo_testhilfe.gleich((select count(*) from (select labor_art from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000027a4'::uuid) z
                                where z.labor_art is not null), 1::bigint, 'Zielprofil des Labors erkannt');
select wamo_testhilfe.gleich((select scopes_ausnahmen from (
  select p.user_id::text as user_id, p.display_name, p.rolle::text as rolle, p.aktiv, coalesce(r.scopes_ausnahmen, array[]::text[]) as scopes_ausnahmen, g.art, g.login, g.ablauf from __SCHEMA__.profiles p left join __SCHEMA__.github_rechte r on r.user_id = p.user_id left join __SCHEMA__.github_zugang g on g.user_id = p.user_id where p.labor_art is null order by p.display_name limit 200
) l where l.user_id = '00000000-0000-4000-8000-0000000027a1'), array['workflow']::text[], 'Admin-Liste des Kerns');
select wamo_testhilfe.gleich((select count(*) from (
  select p.user_id::text as user_id, p.display_name, p.rolle::text as rolle, p.aktiv, coalesce(r.scopes_ausnahmen, array[]::text[]) as scopes_ausnahmen, g.art, g.login, g.ablauf from __SCHEMA__.profiles p left join __SCHEMA__.github_rechte r on r.user_id = p.user_id left join __SCHEMA__.github_zugang g on g.user_id = p.user_id where p.labor_art is null order by p.display_name limit 200
) l where l.user_id = '00000000-0000-4000-8000-0000000027a4'), 0::bigint, 'Laborprofile fehlen in der Admin-Liste');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['gist'], '00000000-0000-4000-8000-0000000027a1')$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['gist'], '00000000-0000-4000-8000-0000000027a3')$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['gist'], null)$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a4', array['gist'], '00000000-0000-4000-8000-0000000027a2')$s$, '42501');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['delete_repo'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['site_admin'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['admin:enterprise'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['manage_runners:enterprise'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['manage_billing:enterprise'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['read:enterprise'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
-- unbedenkliche und unbekannte Scopes sind keine Ausnahme (die Erlaubnisliste kennt sie schon bzw. nie)
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['read:org'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['admin:neu_bei_github'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['repo'], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array['gist', null], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array[array['gist'], array['workflow']], '00000000-0000-4000-8000-0000000027a2')$s$, '23514');
select wamo_testhilfe.fehler($s$insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von, geaendert_at) values ('00000000-0000-4000-8000-0000000027a2', array['gist'], '00000000-0000-4000-8000-0000000027a2', now() - interval '1 year')$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_rechte set geaendert_at = now() - interval '1 year'$s$, '42501');
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_rechte set user_id = '00000000-0000-4000-8000-0000000027a2'$s$, '42501');
select wamo_testhilfe.fehler($s$delete from __SCHEMA__.github_rechte$s$, '42501');
select wamo_testhilfe.fehler($s$truncate __SCHEMA__.github_rechte$s$, '42501');
-- alle erlaubbaren Scopes zusammen gehen (SCOPES_AUSNAHMEN)
insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values ('00000000-0000-4000-8000-0000000027a2', array[
  'admin:org', 'write:org', 'admin:org_hook', 'admin:repo_hook', 'write:repo_hook', 'admin:public_key',
  'write:public_key', 'admin:gpg_key', 'write:gpg_key', 'admin:ssh_signing_key', 'write:ssh_signing_key',
  'write:packages', 'read:packages', 'delete:packages', 'user', 'user:email', 'user:follow', 'workflow', 'gist',
  'codespace', 'codespace:secrets', 'copilot', 'manage_billing:copilot', 'manage_runners:org',
  'write:network_configurations', 'audit_log', 'read:audit_log'], '00000000-0000-4000-8000-0000000027a2');
reset role;

-- 6. Löschen durch den Kern (Widerruf) und mit dem Profil: Zeilen gehen mit, geaendert_von wird null
set role wamo_core;
delete from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a2'::uuid;
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a2'), 0::bigint,
                             'Widerruf durch den Kern');
reset role;
delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000027a1';
delete from auth.users where id = '00000000-0000-4000-8000-0000000027a1';
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.github_zugang where user_id = '00000000-0000-4000-8000-0000000027a1'), 0::bigint,
                             'Token geht mit dem Profil');
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a1'), 0::bigint,
                             'Rechte gehen mit dem Profil');
-- geaendert_von ist kein Besitz: Wird der Admin gelöscht, bleibt die Zeile mit null; der Trigger lässt genau diese Änderung durch
insert into auth.users (id, email) values ('00000000-0000-4000-8000-0000000027a5', 'github-admin-zwei@wamo-test.invalid');
insert into __SCHEMA__.profiles (user_id, display_name, rolle, aktiv) values ('00000000-0000-4000-8000-0000000027a5', 'GitHub Admin Zwei', 'admin', true);
insert into __SCHEMA__.github_rechte (user_id, scopes_ausnahmen, geaendert_von) values
  ('00000000-0000-4000-8000-0000000027a3', array['gist'], '00000000-0000-4000-8000-0000000027a5');
delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000027a5';
select wamo_testhilfe.gleich((select geaendert_von from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a3'), null::uuid,
                             'geaendert_von null nach dem Löschen des Admins');
select wamo_testhilfe.gleich((select scopes_ausnahmen from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a3'),
                             array['gist']::text[], 'Rechte bleiben nach dem Löschen des Admins');
set role wamo_core;
-- ohne Admin keine neuen Rechte, auch nicht über eine Zeile mit geaendert_von null
select wamo_testhilfe.fehler($s$update __SCHEMA__.github_rechte set scopes_ausnahmen = array['gist', 'workflow'] where user_id = '00000000-0000-4000-8000-0000000027a3'$s$, '42501');
reset role;

-- Ein Admin, der sich selbst Rechte gegeben hat (a2, Zeile aus Abschnitt 5), lässt sich löschen: Cascade und Set null stören sich nicht
delete from __SCHEMA__.profiles where user_id = '00000000-0000-4000-8000-0000000027a2';
select wamo_testhilfe.gleich((select count(*) from __SCHEMA__.github_rechte where user_id = '00000000-0000-4000-8000-0000000027a2'), 0::bigint,
                             'Admin mit eigener Zeile gelöscht');
-- Die Policy admin_lesen gilt nur für wamo_admin und nur zum Lesen
select wamo_testhilfe.gleich((select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'github_zugang'
                                and policyname = 'admin_lesen' and cmd = 'SELECT' and roles = array['wamo_admin']::name[]), 1::bigint,
                             'Policy admin_lesen nur lesend für wamo_admin');

-- 7. Rückweg in einem Sicherungspunkt (Anweisungen aus 0027_github_zugang.down.sql), danach zurückgerollt
savepoint rueckweg;
drop table if exists __SCHEMA__.github_rechte;
drop table if exists __SCHEMA__.github_zugang;
drop function if exists __SCHEMA__.github_rechte_guard();
drop function if exists __SCHEMA__.github_zugang_guard();
delete from __SCHEMA__.schema_migrations where version = '0027_github_zugang';
do $$ begin
  perform wamo_testhilfe.gleich(to_regclass('__SCHEMA__.github_zugang') is null and to_regclass('__SCHEMA__.github_rechte') is null
                                and to_regprocedure('__SCHEMA__.github_zugang_guard()') is null
                                and to_regprocedure('__SCHEMA__.github_rechte_guard()') is null, true, 'Rückweg entfernt alles');
end $$;
rollback to savepoint rueckweg;

rollback;
\echo 0027 OK
