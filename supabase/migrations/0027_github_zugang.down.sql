-- Rückweg zu 0027 (persönliche GitHub-Zugänge): entfernt die Tabellen github_zugang und github_rechte samt allen gespeicherten Tokens
-- (nur Chiffrate) und den Rechten je Person, dazu die Trigger und ihre Funktionen. Wiederholbar. Bricht in wamo_prod ohne ausdrückliche
-- Freigabe ab und solange spätere Migrationen angewendet sind (erst diese zurücknehmen). Vorher den Schalter WAMO_ENTWICKLUNG_GITHUB auf
-- aus stellen (docs/persoenliche-zugaenge.md, C.10): Der Kern meldet danach "nicht eingerichtet", Entwicklungsaufträge über die App laufen
-- unverändert weiter. Die Personen widerrufen ihre Tokens bei GitHub selbst; dieser Rückweg löscht nur die Kopie bei W.A.I.S.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Backup: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0027_github_zugang')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0027 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;
set local lock_timeout = '5s';

drop table if exists __SCHEMA__.github_rechte;  -- nimmt den Trigger github_rechte_guard mit
drop table if exists __SCHEMA__.github_zugang;  -- nimmt den Trigger github_zugang_guard mit
drop function if exists __SCHEMA__.github_rechte_guard();
drop function if exists __SCHEMA__.github_zugang_guard();

do $$ begin
  if to_regclass('__SCHEMA__.github_zugang') is not null or to_regclass('__SCHEMA__.github_rechte') is not null
     or to_regprocedure('__SCHEMA__.github_zugang_guard()') is not null
     or to_regprocedure('__SCHEMA__.github_rechte_guard()') is not null then
    raise exception 'github_zugang (0027 zurück): Tabelle oder Funktion noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0027_github_zugang';
