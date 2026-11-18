-- Rückweg zu 0028: entfernt den Abdruck des Sprechermodells im Schattenbetrieb (Spalten voiceprint_shadow und shadow_model, ihre Regeln
-- und den Trigger speakers_schatten_verwerfen). Abdrücke von TitaNet, Schwellen, Einwilligungen und alle anderen Spalten von speakers bleiben
-- unberührt. Der Kern liest und schreibt danach ohne Schatten weiter (voice-core/stimme_speicher.py, Hinweis einmal je Prozess im Log, die
-- Prüfung mit TitaNet ändert sich nicht); ein Neustart ist nicht nötig. Vorher WAMO_STIMME_SCHATTEN auf aus stellen. Die Schatten-Abdrücke
-- gehen verloren, nach erneutem Anwenden von 0028 entstehen sie beim nächsten Einlernen neu.
-- Reihenfolge: erst diese Datei, dann gegebenenfalls ältere Rückwege.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
set local lock_timeout = '5s';

drop trigger if exists speakers_schatten_verwerfen on __SCHEMA__.speakers;
drop function if exists __SCHEMA__.speakers_schatten_verwerfen();

alter table if exists __SCHEMA__.speakers
  drop constraint if exists speakers_shadow_pair_chk,
  drop constraint if exists speakers_shadow_voiceprint_chk,
  drop constraint if exists speakers_shadow_consent_chk,
  drop constraint if exists speakers_shadow_dims_chk,
  drop constraint if exists speakers_shadow_model_chk,
  drop column if exists voiceprint_shadow,
  drop column if exists shadow_model;

do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
               and column_name in ('voiceprint_shadow', 'shadow_model')) then
    raise exception 'speakers (0028 zurück): Spalten des Schattens noch vorhanden';
  end if;
  if exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
               where n.nspname = '__SCHEMA__' and p.proname = 'speakers_schatten_verwerfen') then
    raise exception 'speakers (0028 zurück): Funktion speakers_schatten_verwerfen noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0028_stimme_schatten';
