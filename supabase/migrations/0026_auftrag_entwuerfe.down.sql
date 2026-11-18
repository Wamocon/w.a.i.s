-- Rückweg zu 0026 (Entwicklungsaufträge für später): entfernt die Tabelle auftrag_entwuerfe samt allen gespeicherten Aufträgen und den
-- Trigger der Grenze. Wiederholbar. Bricht in wamo_prod ohne ausdrückliche Freigabe ab und solange spätere Migrationen angewendet sind (erst
-- diese zurücknehmen). Der Kern liest danach keine Entwürfe mehr: Liste, Speichern und Laden melden einen Satz (Datenbank nicht erreichbar),
-- Entwicklungsaufträge selbst laufen unverändert weiter. Die Entwürfe gehen verloren; wer sie behalten will, sichert die Tabelle vorher
-- (pg_dump -t <schema>.auftrag_entwuerfe).
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Backup: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0026_auftrag_entwuerfe')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0026 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;
set local lock_timeout = '5s';

drop table if exists __SCHEMA__.auftrag_entwuerfe;  -- nimmt den Trigger auftrag_entwuerfe_grenze mit
drop function if exists __SCHEMA__.auftrag_entwuerfe_grenze();

do $$ begin
  if to_regclass('__SCHEMA__.auftrag_entwuerfe') is not null
     or to_regprocedure('__SCHEMA__.auftrag_entwuerfe_grenze()') is not null then
    raise exception 'auftrag_entwuerfe (0026 zurück): Tabelle oder Funktion noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0026_auftrag_entwuerfe';
