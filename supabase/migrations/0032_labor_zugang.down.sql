-- Rückweg zu 0032 (Claude-Zugang des Testlabors): entfernt die Tabelle labor_zugang samt dem gespeicherten Chiffrat. Wiederholbar. Bricht in
-- wamo_prod ohne ausdrückliche Freigabe ab und solange spätere Migrationen angewendet sind (erst diese zurücknehmen). Der Kern liest danach
-- keinen gespeicherten Labor-Schlüssel mehr und nimmt wie vor 0032 den Schlüssel des Servers (ANTHROPIC_API_KEY), sonst die Hausmodelle; alle
-- übrigen Funktionen laufen unverändert weiter. Wer den Schlüssel behalten will, setzt ihn danach neu (er lässt sich nicht auslesen).
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Backup: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
  if exists (select 1 from __SCHEMA__.schema_migrations where version > '0032_labor_zugang')
     and coalesce(current_setting('wamo.down_trotz_folgemigration', true), '') <> 'ja' then
    raise exception '0032 down: erst die späteren Migrationen zurücknehmen';
  end if;
end $$;
set local lock_timeout = '5s';

drop table if exists __SCHEMA__.labor_zugang;  -- nimmt Index, Policy und Fremdschlüssel mit

do $$ begin
  if to_regclass('__SCHEMA__.labor_zugang') is not null then
    raise exception 'labor_zugang (0032 zurück): Tabelle noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0032_labor_zugang';
