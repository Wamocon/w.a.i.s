-- Rückweg zu 0029: zurück zu einem Stimmabdruck je Person (Stand 0028). Je Person bleibt nur der zuletzt eingelernte Abdruck (mit seiner
-- Einwilligung, Schwelle und, mit stimme-2, seinem Schatten); die Abdrücke weiterer Mikrofone gehen verloren, denn ohne 0029 gibt es für sie
-- keinen Platz. Ein Schatten zu einem Abdruck mit stimme-3 fällt weg (0028 erlaubt ihn nur mit stimme-2), der Abdruck selbst bleibt; er
-- entsteht beim nächsten Einlernen neu. Danach sind Spalten mikrofon und mikrofon_name, Trigger und Index von 0029 weg, der alte Index
-- speakers_one_owner_idx ist wieder da.
-- Der Kern mit dem Stand von 0029 arbeitet danach mit einem Abdruck weiter (voice-core/stimme_speicher.py, Rückfall ohne die Spalte mikrofon,
-- Einwilligung wieder stimme-1 oder stimme-2); ein Neustart ist nicht nötig, eine laufende Sitzung prüft bis zu ihrem Ende mit den
-- geladenen Abdrücken. Ein älterer Kern braucht diesen Rückweg, bevor er wieder Abdrücke speichern kann.
-- Reihenfolge: erst diese Datei, dann gegebenenfalls ältere Rückwege.
-- In wamo_prod nur nach ausdrücklicher Freigabe:
--   docker exec -e PGOPTIONS='-c wamo.allow_drop=ja' -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
do $$ begin
  if '__SCHEMA__' = 'wamo_prod' and coalesce(current_setting('wamo.allow_drop', true), '') <> 'ja' then
    raise exception 'Down in wamo_prod gesperrt. Nach Freigabe: PGOPTIONS="-c wamo.allow_drop=ja"';
  end if;
end $$;
set local lock_timeout = '5s';

drop trigger if exists speakers_mikrofon_grenze on __SCHEMA__.speakers;
drop function if exists __SCHEMA__.speakers_mikrofon_grenze();

-- je Person nur der neueste Abdruck (DSGVO: die übrigen Zeilen verschwinden ganz, mit Schatten und Name des Mikrofons)
do $$
declare
  v_n bigint;
begin
  if exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
               and column_name = 'mikrofon') then
    delete from __SCHEMA__.speakers s
     using (select x.id, row_number() over (partition by user_id order by enrolled_at desc, id desc) as nr
              from __SCHEMA__.speakers x where x.is_owner) r
     where s.id = r.id and r.nr > 1;
    get diagnostics v_n = row_count;
    raise notice 'speakers (0029 zurück): % Abdrücke weiterer Mikrofone gelöscht', v_n;
  end if;
end $$;

update __SCHEMA__.speakers set voiceprint_shadow = null, shadow_model = null
 where voiceprint_shadow is not null and consent_text_version = 'stimme-3';

alter table if exists __SCHEMA__.speakers
  drop constraint if exists speakers_shadow_consent_chk,
  add constraint speakers_shadow_consent_chk check (voiceprint_shadow is null or consent_text_version = 'stimme-2');

create unique index if not exists speakers_one_owner_idx on __SCHEMA__.speakers (user_id) where is_owner;
drop index if exists __SCHEMA__.speakers_owner_mikrofon_idx;

alter table if exists __SCHEMA__.speakers
  drop constraint if exists speakers_mikrofon_chk,
  drop constraint if exists speakers_mikrofon_name_chk,
  drop column if exists mikrofon,
  drop column if exists mikrofon_name;

do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
               and column_name in ('mikrofon', 'mikrofon_name')) then
    raise exception 'speakers (0029 zurück): Spalten des Mikrofons noch vorhanden';
  end if;
  if exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
               where n.nspname = '__SCHEMA__' and p.proname = 'speakers_mikrofon_grenze') then
    raise exception 'speakers (0029 zurück): Funktion speakers_mikrofon_grenze noch vorhanden';
  end if;
  if to_regclass('__SCHEMA__.speakers_one_owner_idx') is null or to_regclass('__SCHEMA__.speakers_owner_mikrofon_idx') is not null then
    raise exception 'speakers (0029 zurück): Index je Person nicht wiederhergestellt';
  end if;
  if not exists (select 1 from pg_constraint where conrelid = '__SCHEMA__.speakers'::regclass and conname = 'speakers_shadow_consent_chk'
                   and convalidated and pg_get_constraintdef(oid) like '%stimme-2%' and pg_get_constraintdef(oid) not like '%stimme-3%') then
    raise exception 'speakers (0029 zurück): Regel speakers_shadow_consent_chk nicht wie in 0028';
  end if;
end $$;

delete from __SCHEMA__.schema_migrations where version = '0029_stimme_mikrofone';
