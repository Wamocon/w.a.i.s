-- Rückweg zu 0024: entfernt die Modellwahl und die Stimme im Haus der Personen. Danach wählt für jedes Profil wieder der Boss
-- (automatisch), und die Sprachausgabe im Haus spricht mit der Stimme des Kerns (WAMO_TTS_HAUS_STIMME). Hören und Stimme (stt, tts),
-- Modus, Schlüssel und Token bleiben unberührt. Der Kern liest die fehlenden Spalten als "keine Wahl" (modellzugang._zeile) und meldet
-- beim Setzen einen klaren Satz; ein Neustart des Kerns ist nicht nötig. Die gewählten Werte gehen verloren (in actions steht jede Wahl).
-- Reihenfolge: erst diese Datei, dann gegebenenfalls ältere Rückwege.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
set local lock_timeout = '5s';

alter table if exists __SCHEMA__.model_access
  drop constraint if exists model_access_modell_gespraech_form,
  drop constraint if exists model_access_modell_bilder_form,
  drop constraint if exists model_access_modell_hintergrund_form,
  drop constraint if exists model_access_tts_stimme_form,
  drop column if exists modell_gespraech,
  drop column if exists modell_bilder,
  drop column if exists modell_hintergrund,
  drop column if exists tts_stimme;

do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'model_access'
               and column_name in ('modell_gespraech', 'modell_bilder', 'modell_hintergrund', 'tts_stimme')) then
    raise exception 'model_access (0024 zurück): Spalten der Modellwahl noch vorhanden';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0024_modellwahl_selbst';
