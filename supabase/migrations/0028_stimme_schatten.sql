-- WAMO 0028: Abdruck des zweiten Sprechermodells im Schattenbetrieb (18.11.2026). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0028_stimme_schatten.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0028_stimme_schatten.down.sql. Hängt von 0001 (Tabelle speakers, Policy core_all, Rechte des Kerns) und 0025 (Spalte
-- voice_threshold, die der Kern im selben Upsert schreibt) ab. Die Nummer 0027 ist für eine andere Änderung vergeben.
--
-- Wozu: TitaNet trennt bei kurzen Äußerungen schwach. Ein zweites Modell (WeSpeaker ResNet34, voice-core/stimme_schatten.py) rechnet im
-- Schattenbetrieb mit (Schalter WAMO_STIMME_SCHATTEN, Standard aus): Beim Einlernen entsteht aus denselben Stücken ein zweiter Abdruck, bei
-- jeder Prüfung schreibt der Kern nur Zahlen ins Log. Entscheiden tut er nie. Ob umgestellt wird, entscheidet die Auswertung.
--
-- Neue Spalten in speakers, beide NULL ohne Vorgabe (jede vorhandene Zeile bleibt unverändert, der Schatten fehlt dort bis zum neuen
-- Einlernen):
--   voiceprint_shadow  extensions.vector ohne feste Länge (das Modell im Schatten kann wechseln, heute 256 Werte), 64 bis 1024 Werte
--   shadow_model       Name des Modells, von dem der Schatten stammt (heute wespeaker-resnet34-cmn); der Kern nimmt nur seinen eigenen
-- Regeln in der Tabelle: beide zusammen oder keiner, ein Schatten nur zu einem Abdruck (der selbst Einwilligung und Profilinhaber verlangt,
-- 0001) und nur mit der Einwilligung stimme-2 (Entscheidung vom 18.11.2026: nur sie nennt den zweiten Abdruck aus 256 Zahlen; ein Abdruck
-- mit stimme-1 bekommt keinen Schatten, bis die Person neu einlernt; voice-core/stimme_einwilligung.py), Name aus a-z, 0-9 und ._+- mit
-- höchstens 60 Zeichen. Der Schatten ist biometrisch wie der Abdruck (DSGVO Art. 9) und verschwindet mit
-- der Zeile (Löschen des Abdrucks, DSGVO Art. 17; für Laborprofile über die Löschliste, voice-core/labor_loeschliste.py, Eintrag speakers).
--
-- Trigger speakers_schatten_verwerfen: Wird voiceprint ersetzt (neu einlernen) und setzt dieselbe Anweisung keinen neuen Schatten, setzt die
-- Datenbank den alten Schatten auf NULL. So gehört ein Schatten immer zum gespeicherten Abdruck, auch wenn ohne Schatten neu eingelernt wird
-- oder das zweite Speichern scheitert. Verglichen wird über ::text (die Ausgabe von pgvector), damit die Funktion mit leerem search_path
-- keinen Operator aus dem Schema extensions braucht. Keine security definer, die Funktion ändert nur die eigene Zeile. Grenze: Eine Anweisung,
-- die den Abdruck ändert und den alten Schatten unverändert mitschreibt (set voiceprint_shadow = voiceprint_shadow), behält ihn; der Kern
-- schreibt so nie, ein Verwaltungswerkzeug soll es auch nicht.
--
-- Rechte: Der Kern (wamo_core) hat auf speakers seit 0001 select, insert, update und delete für die ganze Tabelle; dieses Tabellenrecht gilt
-- auch für die neuen Spalten und bleibt wirksam (ein Widerruf auf Spalten nimmt es nicht zurück). Die Spaltenrechte hier halten fest, was der
-- Kern braucht (select und update, er schreibt den Schatten mit einem update nach dem Upsert, nie mit insert), damit es nicht nur am
-- Tabellenrecht hängt; alle anderen Rollen bekommen nichts. Kein neues delete, keine neue Policy (core_all aus 0001 bleibt), keine neue Tabelle. Laborprofile haben keinen
-- Abdruck und keine Stimmsitzung (voice-core/stimme_sitzung.py), für sie schreibt der Kern hier nie.
set local lock_timeout = '5s';  -- ALTER TABLE sperrt speakers kurz; hängt es, bricht die Migration ab statt zu stauen

do $$ begin
  if to_regclass('__SCHEMA__.speakers') is null then
    raise exception '0028 braucht 0001 (Tabelle __SCHEMA__.speakers fehlt)';
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
                   and column_name = 'voice_threshold') then
    raise exception '0028 braucht 0025 (Spalte __SCHEMA__.speakers.voice_threshold fehlt)';
  end if;
end $$;

alter table __SCHEMA__.speakers
  add column if not exists voiceprint_shadow extensions.vector,
  add column if not exists shadow_model text;

alter table __SCHEMA__.speakers
  drop constraint if exists speakers_shadow_pair_chk,
  add constraint speakers_shadow_pair_chk check ((voiceprint_shadow is null) = (shadow_model is null)),
  drop constraint if exists speakers_shadow_voiceprint_chk,
  add constraint speakers_shadow_voiceprint_chk check (voiceprint_shadow is null or voiceprint is not null),
  drop constraint if exists speakers_shadow_consent_chk,
  add constraint speakers_shadow_consent_chk check (voiceprint_shadow is null or consent_text_version = 'stimme-2'),
  drop constraint if exists speakers_shadow_dims_chk,
  add constraint speakers_shadow_dims_chk
    check (voiceprint_shadow is null or extensions.vector_dims(voiceprint_shadow) between 64 and 1024),
  drop constraint if exists speakers_shadow_model_chk,
  add constraint speakers_shadow_model_chk check (shadow_model is null or shadow_model ~ '^[a-z0-9][a-z0-9_.+-]{0,59}$');

comment on column __SCHEMA__.speakers.voiceprint_shadow is
  'Biometrisch (DSGVO Art. 9). Abdruck des Sprechermodells im Schattenbetrieb, nur zum Messen, nie zum Entscheiden; nur der Kern';
comment on column __SCHEMA__.speakers.shadow_model is
  'Name des Modells, von dem voiceprint_shadow stammt (zum Beispiel wespeaker-resnet34-cmn); nur der Kern';

-- ---------- Ein neuer Abdruck verwirft den alten Schatten ----------
create or replace function __SCHEMA__.speakers_schatten_verwerfen() returns trigger
language plpgsql
set search_path = ''
as $f$
begin
  if new.voiceprint::text is distinct from old.voiceprint::text
     and new.voiceprint_shadow::text is not distinct from old.voiceprint_shadow::text then
    new.voiceprint_shadow := null;
    new.shadow_model := null;
  end if;
  return new;
end
$f$;
revoke all on function __SCHEMA__.speakers_schatten_verwerfen() from public, anon, authenticated, service_role, wamo_admin;

drop trigger if exists speakers_schatten_verwerfen on __SCHEMA__.speakers;
create trigger speakers_schatten_verwerfen
  before update of voiceprint on __SCHEMA__.speakers
  for each row execute function __SCHEMA__.speakers_schatten_verwerfen();

-- ---------- Rechte: nur der Kern, nur diese Spalten ----------
-- Erst zurücksetzen (ein zweiter Lauf nimmt so später nachgezogene Spaltenrechte zurück), dann genau das Nötige vergeben.
revoke all (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers to wamo_core;
grant update (voiceprint_shadow, shadow_model) on __SCHEMA__.speakers to wamo_core;

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht und jede Spalte einzeln (has_column_privilege mit mehreren Rechten wäre
-- schon bei einem davon wahr).
do $$
declare
  recht text;
  rolle text;
  spalte text;
begin
  foreach spalte in array array['voiceprint_shadow', 'shadow_model'] loop
    foreach recht in array array['SELECT', 'UPDATE'] loop
      if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', spalte, recht) then
        raise exception 'speakers (0028): wamo_core braucht % auf %', recht, spalte using errcode = '42501';
      end if;
    end loop;
    foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
      foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
        if has_column_privilege(rolle, '__SCHEMA__.speakers', spalte, recht) then
          raise exception 'speakers (0028): % darf % auf % nicht haben', rolle, recht, spalte using errcode = '42501';
        end if;
      end loop;
    end loop;
    -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
    if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
       and not has_column_privilege('wamo_core_s2', '__SCHEMA__.speakers', spalte, 'UPDATE') then
      raise exception 'speakers (0028): wamo_core_s2 erbt UPDATE auf % nicht', spalte using errcode = '42501';
    end if;
  end loop;
  -- Voraussetzungen im Kern (voice-core/stimme_speicher.py): Löschen der Zeile (DSGVO Art. 17), Policy core_all, RLS an
  if not has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'DELETE') then
    raise exception 'speakers (0028): wamo_core braucht DELETE (Löschen des Abdrucks)' using errcode = '42501';
  end if;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'speakers' and policyname = 'core_all') then
    raise exception 'speakers (0028): Policy core_all fehlt' using errcode = '42501';
  end if;
  if has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'TRUNCATE')
     or not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.speakers'::regclass)
  then
    raise exception 'speakers (0028): unzulässige Rechte oder RLS aus' using errcode = '42501';
  end if;
  -- die Regeln hängen an der Tabelle und sind geprüft (nicht NOT VALID), der Trigger ist aktiv
  if (select count(*) from pg_constraint where conrelid = '__SCHEMA__.speakers'::regclass and contype = 'c' and convalidated
        and conname in ('speakers_shadow_pair_chk', 'speakers_shadow_voiceprint_chk', 'speakers_shadow_consent_chk',
                        'speakers_shadow_dims_chk', 'speakers_shadow_model_chk')) <> 5 then
    raise exception 'speakers (0028): Regeln für den Schatten fehlen' using errcode = '23514';
  end if;
  if not exists (select 1 from pg_trigger where tgrelid = '__SCHEMA__.speakers'::regclass and tgname = 'speakers_schatten_verwerfen'
                   and tgenabled = 'O' and not tgisinternal) then
    raise exception 'speakers (0028): Trigger speakers_schatten_verwerfen fehlt' using errcode = '42704';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0028_stimme_schatten') on conflict do nothing;
