-- WAMO 0021: Kein gewöhnliches Profil wird ohne Erstanmeldung aktiv (Planpapier docs/ausrollen-neue-nutzer.md, Abschnitt 4.1, Paket P1a).
--
-- Ein Wechsel von profiles.aktiv von false auf true braucht für ein Profil ohne labor_art einen Merker in wamo_auth.erstanmeldungen
-- (gleich welcher Stand). So öffnet eine alte Kopie von "wamo_nutzer.py anlegen" (setzte bei jedem Lauf aktiv = true) keines der
-- gesperrten Konten mehr; Freischalten geht nur noch über "wamo_nutzer.py freischalten", das zuerst den Merker schreibt.
-- Nicht betroffen: Profile, die schon aktiv sind (zum Beispiel das von Niko), Laborprofile (labor_art gesetzt, eigene Freischaltung über
-- labor_aktiv), Sperren (true auf false) und neue Profile. Ein neues Profil mit aktiv = true bleibt möglich: Das neue Skript legt jedes
-- Profil inaktiv an, und eine alte Kopie trifft die sieben vorhandenen Profile nur über den Weg "on conflict do update" (also über
-- diesen Trigger). Die Tests der älteren Migrationen legen weiter aktive Testprofile an. Restpunkt (Reviews vom 15.11.2026, MEDIUM):
-- Ein NEUES Konto mit aktivem Profil ohne Merker (alte Kopie von anlegen oder ein Insert als wamo_admin) hat den Stand "keine" und muss
-- sein Passwort nicht wechseln; das ist das Verhalten vor P1a und setzt ein Passwort voraus, das der Admin selbst vergeben hat.
-- Re-Aktivieren nach einem Sperren braucht ebenfalls einen Merker (wamo_nutzer.py freischalten), auch für Admin-Profile.
-- Fehlt wamo_auth (falsche Reihenfolge beim Ausrollen), scheitert jedes Aktivieren (fail closed).
--
-- Außerdem zwei neue Hinweisarten für die Karten der Admins: erstanmeldung_begonnen und erstanmeldung_erledigt (geschrieben von
-- wamo_auth.erstanmeldung_begonnen und vom Trigger auf auth.users, infra/sokrates2/supabase-wamo/wamo_auth.sql).
--
-- Reihenfolge: zuerst wamo_auth (infra/sokrates2/wamo-auth-einrichten.sh), dann diese Migration je Schema. Anwenden als postgres:
--   bash scripts/render-migration.sh <schema> supabase/migrations/0021_profil_freischaltung.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0021_profil_freischaltung.down.sql. Test: supabase/tests/0021_profil_freischaltung_test.sql.

set local lock_timeout = '5s';

do $$ begin
  if (select count(*) from __SCHEMA__.schema_migrations where version in ('0001_wamo_init', '0002_wamo_geraete', '0018_labor_profile')) <> 3 then
    raise exception '0021 braucht 0001, 0002 und 0018';
  end if;
end $$;

-- ---------- Hinweisarten (drop davor: ein zweiter Lauf bricht nicht ab) ----------
alter table __SCHEMA__.hinweise drop constraint if exists hinweise_art_chk;
alter table __SCHEMA__.hinweise add constraint hinweise_art_chk check (art in ('geraet_gebunden','geraet_beantragt','geraet_konflikt',
    'geraet_gesperrt','geraet_entsperrt','geraet_widerrufen','teilung_erhalten','teilung_geaendert',
    'teilung_widerrufen','scan_fertig','system','erstanmeldung_begonnen','erstanmeldung_erledigt'));

-- ---------- Trigger: Aktivieren nur mit Merker ----------
-- security definer: Auch wamo_admin (darf aktiv ändern, 0001) liest so den Merker, ohne selbst Rechte auf wamo_auth zu bekommen.
create or replace function __SCHEMA__.profiles_freischaltung_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.labor_art is not null or not new.aktiv or old.aktiv then
    return new;
  end if;
  if pg_catalog.to_regclass('wamo_auth.erstanmeldungen') is null then
    raise exception 'profiles: aktivieren nur mit Erstanmeldung (wamo_auth fehlt, zuerst wamo-auth-einrichten.sh)' using errcode = '42501';
  end if;
  if not exists (select 1 from wamo_auth.erstanmeldungen e where e.user_id = new.user_id) then
    raise exception 'profiles: aktivieren nur mit Erstanmeldung (wamo_nutzer.py freischalten)' using errcode = '42501';
  end if;
  return new;
end $$;
revoke all on function __SCHEMA__.profiles_freischaltung_guard() from public, wamo_core, wamo_admin;
drop trigger if exists profiles_freischaltung_guard on __SCHEMA__.profiles;
create trigger profiles_freischaltung_guard before update of aktiv on __SCHEMA__.profiles
  for each row when (new.aktiv and not old.aktiv) execute function __SCHEMA__.profiles_freischaltung_guard();

insert into __SCHEMA__.schema_migrations (version) values ('0021_profil_freischaltung') on conflict do nothing;
