-- Rückweg zu 0031 (Werkstatt-Panel): entfernt die Ansichten für den Kern, die sieben Tabellen mit allen Einträgen (Labortermine, Plätze,
-- Checkliste, Zuordnung, Karten, Versionen, Freigabekarten), die Triggerfunktionen, die Lesefunktionen, die Policies und die Rechte von
-- wamo_werkstatt auf profiles und actions. Wiederholbar. Bricht in wamo_prod ohne ausdrückliche Freigabe ab und solange spätere
-- Migrationen angewendet sind (erst diese zurücknehmen). Der Kern liest danach die Ansichten nicht mehr: Er bleibt bei dem Stand, den
-- er zuletzt geladen hat, beziehungsweise bei den Dateien, wenn das Nachladen aus ist. Die Daten gehen verloren; wer sie behalten will,
-- sichert die Tabellen vorher (pg_dump -t <schema>.labor_karten und so weiter).
-- Die Rolle wamo_werkstatt bleibt bestehen: Rollen gelten je Cluster, nicht je Schema (wie bei 0013). Die Anmelde-Rolle entfernt die
-- Infrastruktur mit ihrem Rückweg.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Backup: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0031_werkstatt')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0031 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;
set local lock_timeout = '5s';

-- Ansichten zuerst (sie hängen an labor_karten_versionen)
drop view if exists __SCHEMA__.labor_wissen_aktiv;
drop view if exists __SCHEMA__.labor_karten_aktive_version;

-- Policies auf den vorhandenen Tabellen
drop policy if exists werkstatt_lesen on __SCHEMA__.profiles;
drop policy if exists werkstatt_audit_insert on __SCHEMA__.actions;
drop policy if exists werkstatt_audit_lesen on __SCHEMA__.actions;

-- Tabellen (nehmen Trigger, Indizes, Policies und die Rechte auf sich selbst mit)
drop table if exists __SCHEMA__.labor_zuordnung;
drop table if exists __SCHEMA__.labor_checkliste;
drop table if exists __SCHEMA__.labor_plaetze;
drop table if exists __SCHEMA__.labor_termine;
drop table if exists __SCHEMA__.labor_karten_versionen;
drop table if exists __SCHEMA__.labor_karten;
drop table if exists __SCHEMA__.werkstatt_karten;

-- Funktionen
drop function if exists __SCHEMA__.labor_karten_pflege();
drop function if exists __SCHEMA__.labor_karten_versionen_schutz();
drop function if exists __SCHEMA__.werkstatt_karten_schutz();
drop function if exists __SCHEMA__.werkstatt_sitzungen(integer);
drop function if exists __SCHEMA__.werkstatt_latenz(integer);
drop function if exists __SCHEMA__.werkstatt_aktionen(integer);
drop function if exists __SCHEMA__.werkstatt_labor_stand();
drop function if exists __SCHEMA__.werkstatt_aufraeumen();

-- Rechte auf vorhandene Objekte zurücknehmen (nur, wenn die Rolle da ist)
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'wamo_werkstatt') then
    revoke select (user_id, rolle, aktiv, labor_art) on __SCHEMA__.profiles from wamo_werkstatt;
    revoke insert (user_id, tool, params, reason, risk, status, result, decided_at, finished_at) on __SCHEMA__.actions from wamo_werkstatt;
    revoke select (id, user_id, tool, risk, status, created_at, finished_at) on __SCHEMA__.actions from wamo_werkstatt;
    revoke usage on schema __SCHEMA__ from wamo_werkstatt;
  end if;
end $$;

do $$ begin
  if to_regclass('__SCHEMA__.labor_termine') is not null
     or to_regclass('__SCHEMA__.labor_plaetze') is not null
     or to_regclass('__SCHEMA__.labor_checkliste') is not null
     or to_regclass('__SCHEMA__.labor_karten') is not null
     or to_regclass('__SCHEMA__.labor_zuordnung') is not null
     or to_regclass('__SCHEMA__.labor_karten_versionen') is not null
     or to_regclass('__SCHEMA__.werkstatt_karten') is not null
     or to_regclass('__SCHEMA__.labor_wissen_aktiv') is not null
     or to_regclass('__SCHEMA__.labor_karten_aktive_version') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_sitzungen(integer)') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_latenz(integer)') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_aktionen(integer)') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_labor_stand()') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_aufraeumen()') is not null
     or to_regprocedure('__SCHEMA__.labor_karten_pflege()') is not null
     or to_regprocedure('__SCHEMA__.labor_karten_versionen_schutz()') is not null
     or to_regprocedure('__SCHEMA__.werkstatt_karten_schutz()') is not null then
    raise exception 'werkstatt (0031 zurück): Tabelle, Ansicht oder Funktion noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0031_werkstatt';
