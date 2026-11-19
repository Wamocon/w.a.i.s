-- Rückweg zu 0030 (Rückstand an Aufträgen an W.A.I.S. selbst): entfernt die Tabelle selbstauftraege samt allen Einträgen, den Trigger der
-- Grenze und den der Statusübergänge. Wiederholbar. Bricht in wamo_prod ohne ausdrückliche Freigabe ab und solange spätere Migrationen
-- angewendet sind (erst diese zurücknehmen). Der Kern liest danach keinen Rückstand mehr: Liste, Speichern und Verwerfen melden einen Satz
-- (Datenbank nicht erreichbar), alle übrigen Funktionen laufen unverändert weiter. Die Einträge gehen verloren; wer sie behalten will,
-- sichert die Tabelle vorher (pg_dump -t <schema>.selbstauftraege).
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Backup: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0030_selbstauftraege')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0030 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;
set local lock_timeout = '5s';

drop table if exists __SCHEMA__.selbstauftraege;  -- nimmt die Trigger, die Indizes und die Identität von nr mit
drop function if exists __SCHEMA__.selbstauftraege_grenze();
drop function if exists __SCHEMA__.selbstauftraege_status();
drop function if exists __SCHEMA__.selbstauftrag_verwerfen(bigint);
drop function if exists __SCHEMA__.selbstauftrag_oeffnen(bigint);

do $$ begin
  if to_regclass('__SCHEMA__.selbstauftraege') is not null
     or to_regprocedure('__SCHEMA__.selbstauftraege_grenze()') is not null
     or to_regprocedure('__SCHEMA__.selbstauftraege_status()') is not null
     or to_regprocedure('__SCHEMA__.selbstauftrag_verwerfen(bigint)') is not null
     or to_regprocedure('__SCHEMA__.selbstauftrag_oeffnen(bigint)') is not null then
    raise exception 'selbstauftraege (0030 zurück): Tabelle oder Funktion noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0030_selbstauftraege';
