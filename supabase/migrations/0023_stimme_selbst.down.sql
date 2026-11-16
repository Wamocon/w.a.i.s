-- Rückweg zu 0023: Der Kern darf stt und tts wieder nicht schreiben, die Wahl in der Oberfläche endet mit einem klaren Satz
-- ("noch nicht freigeschaltet"). Gewählte Werte bleiben stehen und gelten weiter; alle Sitzungen zurück auf Soniox ohne Datenänderung:
-- WAMO_STT_ANBIETER=soniox und WAMO_TTS_ANBIETER=soniox über wamo-core-env. Keine Daten gehen verloren.
-- Reihenfolge: erst diese Datei, dann gegebenenfalls 0010_modellzugang.down.sql (die löscht die Tabelle; danach bräche das revoke ab).
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
set local lock_timeout = '5s';

revoke insert (stt, tts), update (stt, tts) on __SCHEMA__.model_access from wamo_core;

comment on column __SCHEMA__.model_access.stt is null;
comment on column __SCHEMA__.model_access.tts is null;

do $$ begin
  if has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'stt', 'UPDATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'tts', 'UPDATE')
     or has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'stt', 'INSERT')
     or has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'tts', 'INSERT')
     or not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'stt', 'SELECT')
  then
    raise exception 'model_access (0023 zurück): Rechte von wamo_core auf stt und tts nicht wie vor 0023' using errcode = '42501';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0023_stimme_selbst';
