-- wamo_auth: Erstanmeldung auf der Ebene des Kontos (Planpapier docs/ausrollen-neue-nutzer.md, Abschnitt 4.1, Paket P1a).
--
-- Konten sind für alle drei Schemas dieselben (auth.users). Der Merker "Startpasswort noch nicht gewechselt" gehört deshalb zum Konto
-- und liegt in diesem eigenen kleinen Schema, nicht in der Migrationskette je Schema (scripts/render-migration.sh). Ein Rückweg von
-- wamo_test baut es nie ab.
--
-- Einrichten nur über infra/sokrates2/wamo-auth-einrichten.sh (als postgres, in EINER Transaktion, wiederholbar):
--   bash ~/wamo-infra/wamo-auth-einrichten.sh einrichten --trocken   # alles anwenden und zurückrollen
--   bash ~/wamo-infra/wamo-auth-einrichten.sh einrichten
--   bash ~/wamo-infra/wamo-auth-einrichten.sh test
-- Rückweg: wamo_auth.down.sql über "wamo-auth-einrichten.sh rueckweg" (Trigger weg, Rechte entzogen, die Tabelle der Merker bleibt).
--
-- Gemessen in P0 (Wegwerf-Stack mit supabase/gotrue v2.196.0 und supabase/postgres 17.6.1.136, Ergebnis im Planpapier):
--   * postgres ist kein Superuser, darf aber einen Trigger auf auth.users (Besitzer supabase_auth_admin) anlegen.
--   * Der Trigger feuert beim Wechsel durch die Person (PUT /user) und durch die Admin-Schnittstelle; Anmelden ändert den Hash nicht.
--
-- Stände (wamo_auth.erstanmeldung_stand):
--   keine       kein Merker (Konten von vor P1a, zum Beispiel das von Niko, und Laborkonten)
--   offen       Merker da, Frist läuft, Passwort noch nicht gewechselt
--   abgelaufen  Frist vorbei, bevor gewechselt wurde; bleibt so, auch wenn sich der Hash später ändert. Nur ein neues Freischalten hilft.
--   erledigt    GoTrue hat das Passwort innerhalb der Frist geändert (Trigger) oder der Admin hat den Merker als erledigt angelegt
--
-- Wer schreibt: nur das Admin-Skript scripts/wamo_nutzer.py als postgres (erstanmeldung_anlegen) und der Trigger. Der Kern (wamo_core)
-- darf nur lesen (erstanmeldung_stand) und den Beginn melden (erstanmeldung_begonnen); er kann den Stand weder setzen noch zurücksetzen.
-- anon, authenticated und service_role haben keine Rechte. Das Schema ist nicht in PostgREST.
--
-- Achtung bei einem Update von GoTrue: Eine Migration von GoTrue, die den Typ von auth.users.encrypted_password ändert, scheitert an
-- diesem Trigger (Spalte in der Triggerdefinition), eine Änderung an auth.users.id oder users_pkey am Fremdschlüssel der Tabelle der
-- Merker. Dann vorher "wamo-auth-einrichten.sh rueckweg" (der Fremdschlüssel bleibt, die Tabelle notfalls von Hand sichern und löschen),
-- danach erneut "einrichten". Nach jedem Update von GoTrue die P0-Probe wiederholen: Anmelden mit dem Startpasswort lässt den Stand
-- offen (ein Rehash beim Anmelden zählte sonst als Wechsel, siehe Planpapier S5).

set local lock_timeout = '2s';

do $$ begin
  if to_regclass('auth.users') is null then
    raise exception 'wamo_auth: auth.users fehlt (falsche Datenbank?)' using errcode = '55000';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'wamo_core') then
    raise exception 'wamo_auth: Rolle wamo_core fehlt (zuerst scripts/wamo_db_rolle.py)' using errcode = '55000';
  end if;
end $$;

create schema if not exists wamo_auth;
comment on schema wamo_auth is 'W.A.I.S.: Erstanmeldung je Konto (Merker Startpasswort). Nur postgres schreibt, wamo_core liest über zwei Funktionen.';
revoke all on schema wamo_auth from public;

-- ---------- Merker ----------
create table if not exists wamo_auth.erstanmeldungen (
  user_id        uuid primary key references auth.users (id) on delete cascade,
  start_hash     text not null,
  angelegt_at    timestamptz not null default now(),
  frist_bis      timestamptz not null,
  begonnen_at    timestamptz,
  erledigt_at    timestamptz,
  angelegt_durch text not null,
  constraint erstanmeldungen_hash_chk check (start_hash ~ '^[0-9a-f]{64}$'),
  constraint erstanmeldungen_frist_chk check (frist_bis > angelegt_at and frist_bis <= angelegt_at + interval '168 hours'),
  constraint erstanmeldungen_begonnen_chk check (begonnen_at is null or begonnen_at >= angelegt_at),
  constraint erstanmeldungen_erledigt_chk check (erledigt_at is null or erledigt_at >= angelegt_at),
  constraint erstanmeldungen_durch_chk check (angelegt_durch in ('freischalten', 'zuruecksetzen', 'passwort'))
);
comment on table wamo_auth.erstanmeldungen is
  'Ein Merker je Konto: Startpasswort, Frist, Beginn und Erledigung der Erstanmeldung. start_hash ist SHA-256 des Hashes, nie der Hash selbst.';
do $$ begin
  if not (select relrowsecurity from pg_class where oid = 'wamo_auth.erstanmeldungen'::regclass) then
    alter table wamo_auth.erstanmeldungen enable row level security;
  end if;
end $$;
revoke all on wamo_auth.erstanmeldungen from public, anon, authenticated, service_role, wamo_core;

-- SHA-256 (hex) des Werts von encrypted_password; null wird zum leeren Text
create or replace function wamo_auth.hash_von(p_wert text) returns text
language sql immutable set search_path = '' as $$
  select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(p_wert, ''), 'UTF8')), 'hex')
$$;

-- ---------- Stand ----------
create or replace function wamo_auth.erstanmeldung_stand(p_user uuid) returns text
language plpgsql stable security definer set search_path = '' as $$
declare
  e record;
begin
  if p_user is null then
    raise exception 'erstanmeldung_stand: p_user fehlt' using errcode = '22004';
  end if;
  select m.frist_bis, m.erledigt_at into e from wamo_auth.erstanmeldungen m where m.user_id = p_user;
  if not found then
    return 'keine';
  end if;
  if e.erledigt_at is not null then
    return 'erledigt';
  end if;
  if pg_catalog.now() > e.frist_bis then
    return 'abgelaufen';
  end if;
  return 'offen';
end $$;

-- ---------- Hinweise an die Admins (je Schema, in dem das Konto ein gewöhnliches Profil hat) ----------
-- Jedes Schema in einem eigenen Block: Fehlt dort 0021 (Hinweisart) oder eine Spalte, geht nur dieser Hinweis verloren (Warnung im Log).
create or replace function wamo_auth.hinweis_senden(p_user uuid, p_art text) returns void
language plpgsql volatile security definer set search_path = '' as $$
declare
  s text;
  v_name text;
  v_titel text;
  v_text text;
begin
  if p_art not in ('erstanmeldung_begonnen', 'erstanmeldung_erledigt') then
    raise exception 'hinweis_senden: unbekannte Art' using errcode = '22023';
  end if;
  foreach s in array array['wamo_dev', 'wamo_test', 'wamo_prod'] loop
    begin
      if pg_catalog.to_regprocedure(pg_catalog.format('%I.hinweis_an_admins(text,text,text,uuid,jsonb)', s)) is null then
        continue;
      end if;
      v_name := null;
      execute pg_catalog.format('select p.display_name from %I.profiles p where p.user_id = $1 and p.labor_art is null', s)
        into v_name using p_user;
      if v_name is null then
        continue;
      end if;
      if p_art = 'erstanmeldung_begonnen' then
        v_titel := 'Erstanmeldung begonnen: ' || v_name;
        v_text := 'Startpasswort und zweiter Faktor sind bestätigt, jetzt folgt der Passwortwechsel. War das nicht die Person selbst, '
                  || 'sofort sperren: python scripts/wamo_nutzer.py sperren --schema ' || s || ' --email <E-Mail der Person>.';
      else
        v_titel := 'Erstanmeldung abgeschlossen: ' || v_name;
        v_text := 'Das Startpasswort ist gewechselt. War das nicht die Person selbst, sofort sperren: '
                  || 'python scripts/wamo_nutzer.py sperren --schema ' || s || ' --email <E-Mail der Person>.';
      end if;
      execute pg_catalog.format('select %I.hinweis_an_admins($1, $2, $3, $4, $5)', s)
        using p_art, v_titel, v_text, p_user, pg_catalog.jsonb_build_object('profil', p_user);
    exception when others then
      raise warning 'wamo_auth: Hinweis % in % nicht geschrieben (SQLSTATE %)', p_art, s, sqlstate;
    end;
  end loop;
end $$;

-- ---------- Beginn melden (Kern, nach aal2 im Stand offen) ----------
-- Setzt begonnen_at genau einmal und schickt dann den Hinweis. true nur beim ersten Mal.
create or replace function wamo_auth.erstanmeldung_begonnen(p_user uuid) returns boolean
language plpgsql volatile security definer set search_path = '' as $$
declare
  v boolean := false;
begin
  if p_user is null then
    raise exception 'erstanmeldung_begonnen: p_user fehlt' using errcode = '22004';
  end if;
  update wamo_auth.erstanmeldungen m set begonnen_at = pg_catalog.now()
   where m.user_id = p_user and m.begonnen_at is null and m.erledigt_at is null and pg_catalog.now() <= m.frist_bis
  returning true into v;
  if coalesce(v, false) then
    perform wamo_auth.hinweis_senden(p_user, 'erstanmeldung_begonnen');
    return true;
  end if;
  return false;
end $$;

-- ---------- Merker anlegen (nur das Admin-Skript als postgres) ----------
-- Liest den aktuellen Hash des Kontos als Startwert. Deshalb erst NACH dem Setzen des Startpassworts aufrufen (Reihenfolge in
-- wamo_nutzer.py freischalten). Ein vorhandener Merker wird ersetzt (neue Frist, Beginn und Erledigung leer). p_erledigt: Option Ü
-- (wamo_nutzer.py passwort), die Person hat ihr Passwort selbst gewählt.
create or replace function wamo_auth.erstanmeldung_anlegen(p_user uuid, p_frist_stunden integer, p_durch text,
                                                           p_erledigt boolean default false) returns timestamptz
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_hash text;
  v_jetzt timestamptz := pg_catalog.now();
  v_frist timestamptz;
begin
  if p_user is null or p_frist_stunden is null or p_durch is null or p_erledigt is null then
    raise exception 'erstanmeldung_anlegen: Angabe fehlt' using errcode = '22004';
  end if;
  if p_frist_stunden not between 1 and 168 then
    raise exception 'erstanmeldung_anlegen: Frist 1 bis 168 Stunden' using errcode = '22023';
  end if;
  select wamo_auth.hash_von(u.encrypted_password) into v_hash from auth.users u where u.id = p_user;
  if v_hash is null then
    raise exception 'erstanmeldung_anlegen: Konto fehlt' using errcode = 'P0002';
  end if;
  v_frist := v_jetzt + pg_catalog.make_interval(hours => p_frist_stunden);
  insert into wamo_auth.erstanmeldungen (user_id, start_hash, angelegt_at, frist_bis, begonnen_at, erledigt_at, angelegt_durch)
  values (p_user, v_hash, v_jetzt, v_frist, null, case when p_erledigt then v_jetzt end, p_durch)
  on conflict (user_id) do update
    set start_hash = excluded.start_hash, angelegt_at = excluded.angelegt_at, frist_bis = excluded.frist_bis,
        begonnen_at = null, erledigt_at = excluded.erledigt_at, angelegt_durch = excluded.angelegt_durch;
  return v_frist;
end $$;

-- ---------- Übersicht (Admin-Skript, liste) ----------
create or replace function wamo_auth.erstanmeldung_uebersicht()
returns table (user_id uuid, stand text, frist_bis timestamptz, begonnen_at timestamptz, erledigt_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select m.user_id, wamo_auth.erstanmeldung_stand(m.user_id), m.frist_bis, m.begonnen_at, m.erledigt_at
    from wamo_auth.erstanmeldungen m order by m.angelegt_at
$$;

-- ---------- Trigger auf auth.users: der Merker erledigt sich selbst ----------
-- Feuert nur, wenn sich encrypted_password wirklich ändert (Bedingung im Trigger). Setzt erledigt_at nur bei offenem Merker, in der Frist
-- und wenn der neue Hash nicht der Startwert ist. Jeder eigene Fehler wird abgefangen und nur geloggt: GoTrue wird nie blockiert.
-- Ein Wechsel, während das Konto in GoTrue gesperrt ist, zählt nicht: Das ist das Admin-Skript (freischalten und zuruecksetzen sperren
-- zuerst und löschen alle Sitzungen, die Person selbst kommt dann nicht an PUT /user). So meldet ein neues Startpasswort für ein Konto mit
-- offenem Merker nie fälschlich "abgeschlossen".
create or replace function wamo_auth.passwort_geaendert() returns trigger
language plpgsql volatile security definer set search_path = '' set lock_timeout = '1s' as $$
declare
  v boolean := false;
begin
  -- Der ganze Rumpf steht in einem Ausnahmeblock: auch eine fehlende Spalte nach einem Update von GoTrue, eine Sperre (lock_timeout,
  -- 55P03) oder ein Deadlock führen nur zu einer Warnung, nie zu einem Fehler im Passwortwechsel.
  begin
    if new.banned_until is not null and new.banned_until > pg_catalog.now() then
      return null;
    end if;
    update wamo_auth.erstanmeldungen m set erledigt_at = pg_catalog.now()
     where m.user_id = new.id and m.erledigt_at is null and pg_catalog.now() <= m.frist_bis
       and m.start_hash <> wamo_auth.hash_von(new.encrypted_password)
    returning true into v;
    if coalesce(v, false) then
      begin
        perform wamo_auth.hinweis_senden(new.id, 'erstanmeldung_erledigt');
      exception when others then
        raise warning 'wamo_auth: Hinweis nach Passwortwechsel nicht geschrieben (SQLSTATE %)', sqlstate;
      end;
    end if;
  exception when others then
    raise warning 'wamo_auth: Merker nach Passwortwechsel nicht gesetzt (SQLSTATE %)', sqlstate;
  end;
  return null;
end $$;

-- create or replace trigger (PostgreSQL 14 und neuer) nimmt nur SHARE ROW EXCLUSIVE auf auth.users statt ACCESS EXCLUSIVE wie drop trigger
create or replace trigger wamo_auth_passwort_geaendert
  after update of encrypted_password on auth.users
  for each row when (old.encrypted_password is distinct from new.encrypted_password)
  execute function wamo_auth.passwort_geaendert();

-- ---------- Rechte ----------
revoke all on function wamo_auth.hash_von(text), wamo_auth.erstanmeldung_stand(uuid), wamo_auth.hinweis_senden(uuid, text),
  wamo_auth.erstanmeldung_begonnen(uuid), wamo_auth.erstanmeldung_anlegen(uuid, integer, text, boolean),
  wamo_auth.erstanmeldung_uebersicht(), wamo_auth.passwort_geaendert()
  from public, anon, authenticated, service_role, wamo_core;
grant usage on schema wamo_auth to wamo_core;
grant execute on function wamo_auth.erstanmeldung_stand(uuid), wamo_auth.erstanmeldung_begonnen(uuid) to wamo_core;
