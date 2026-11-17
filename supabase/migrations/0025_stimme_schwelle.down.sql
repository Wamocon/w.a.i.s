-- Rückweg zu 0025: entfernt die persönliche Schwelle der Stimme. Danach gilt für jedes Profil wieder die kurze Schwelle aus der Umgebung
-- (WAMO_STIMME_EIGEN_MIN_KURZ, Standard 0,35); Abdrücke, Einwilligungen und alle anderen Spalten von speakers bleiben unberührt. Der Kern
-- liest und schreibt dann ohne die Spalte weiter (voice-core/stimme_speicher.py, Hinweis einmal je Prozess im Log); ein Neustart ist nicht
-- nötig. Die gespeicherten Schwellen gehen verloren, ein neues Einlernen nach erneutem Anwenden von 0025 misst sie neu.
-- Reihenfolge: erst diese Datei, dann gegebenenfalls ältere Rückwege.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
set local lock_timeout = '5s';

alter table if exists __SCHEMA__.speakers
  drop constraint if exists speakers_voice_threshold_chk,
  drop column if exists voice_threshold;

do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
               and column_name = 'voice_threshold') then
    raise exception 'speakers (0025 zurück): Spalte voice_threshold noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0025_stimme_schwelle';
