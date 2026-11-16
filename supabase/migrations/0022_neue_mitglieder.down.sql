-- Rückweg zu 0022 (Admin-Übersicht "Neue Mitglieder"): entfernt nur die Lesefunktion. Daten gibt es keine; die Oberfläche zeigt
-- die Übersicht danach als nicht erreichbar.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
drop function if exists __SCHEMA__.neue_mitglieder(uuid);
delete from __SCHEMA__.schema_migrations where version = '0022_neue_mitglieder';
