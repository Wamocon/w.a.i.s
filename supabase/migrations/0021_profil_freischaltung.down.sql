-- Rückweg zu 0021 (Aktivieren nur mit Erstanmeldung): entfernt den Trigger profiles_freischaltung_guard samt Funktion, stellt die
-- Hinweisarten von 0002 wieder her und löscht dafür die Hinweise der Arten erstanmeldung_begonnen und erstanmeldung_erledigt (nur Karten
-- der Admins, keine Nutzdaten). Danach lässt sich ein gesperrtes Profil wieder ohne Merker aktivieren. Wiederholbar.
-- Reihenfolge (Planpapier Abschnitt 9): ZUERST den Kern auf einen Stand ohne Erstanmeldung zurückstellen und Konten im Stand offen oder
-- abgelaufen sperren (python scripts/wamo_nutzer.py sperren --schema <Schema> --offene), dann diese Datei, danach erst wamo_auth zurück.
-- Spätere Migrationen vorher zurücknehmen.
-- Anwenden: bash scripts/render-migration.sh <schema> supabase/migrations/0021_profil_freischaltung.down.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
set local lock_timeout = '5s';

do $$ begin
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0021_profil_freischaltung')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0021 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;

drop trigger if exists profiles_freischaltung_guard on __SCHEMA__.profiles;
drop function if exists __SCHEMA__.profiles_freischaltung_guard();

delete from __SCHEMA__.hinweise where art in ('erstanmeldung_begonnen', 'erstanmeldung_erledigt');
alter table __SCHEMA__.hinweise drop constraint if exists hinweise_art_chk;
alter table __SCHEMA__.hinweise add constraint hinweise_art_chk check (art in ('geraet_gebunden','geraet_beantragt','geraet_konflikt',
    'geraet_gesperrt','geraet_entsperrt','geraet_widerrufen','teilung_erhalten','teilung_geaendert',
    'teilung_widerrufen','scan_fertig','system'));

delete from __SCHEMA__.schema_migrations where version = '0021_profil_freischaltung';
