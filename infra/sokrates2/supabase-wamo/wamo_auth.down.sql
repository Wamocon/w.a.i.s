-- Rückweg zu wamo_auth.sql (Erstanmeldung je Konto). Wiederholbar, über "wamo-auth-einrichten.sh rueckweg" (als postgres, eine Transaktion).
--
-- Entfernt den Trigger auf auth.users samt Funktion und entzieht wamo_core alle Rechte. Die Tabelle der Merker und die übrigen
-- Funktionen BLEIBEN (ohne Rechte für irgendwen außer postgres): Migration 0021 (Sperre gegen Aktivieren ohne Merker) liest die Tabelle
-- weiter, und ein erneutes Einrichten findet die Merker unverändert vor.
--
-- Reihenfolge (Planpapier Abschnitt 9, P1a und P1b): Zuerst den Kern auf einen Stand ohne Erstanmeldung zurückstellen. Ein Kern mit
-- Erstanmeldung antwortet nach diesem Rückweg für jedes gewöhnliche Profil mit 503 (fail closed, gewollt). Konten im Stand offen oder
-- abgelaufen vorher sperren: python scripts/wamo_nutzer.py sperren --schema <Schema> --offene.

set local lock_timeout = '5s';

drop trigger if exists wamo_auth_passwort_geaendert on auth.users;
drop function if exists wamo_auth.passwort_geaendert();

do $$ begin
  if to_regnamespace('wamo_auth') is not null and exists (select 1 from pg_roles where rolname = 'wamo_core') then
    revoke all on all functions in schema wamo_auth from wamo_core;
    revoke all on all tables in schema wamo_auth from wamo_core;
    revoke all on schema wamo_auth from wamo_core;
  end if;
end $$;
