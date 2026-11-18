-- WAMO 0029: ein Stimmabdruck je Mikrofon (18.11.2026). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0029_stimme_mikrofone.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0029_stimme_mikrofone.down.sql. Hängt von 0001 (Tabelle speakers, Policy core_all, Rechte des Kerns), 0025 (voice_threshold)
-- und 0028 (Regel speakers_shadow_consent_chk, die hier um stimme-3 erweitert wird) ab.
-- Reihenfolge im Betrieb: erst der Kern mit diesem Stand (er arbeitet ohne 0029 mit einem Abdruck wie bisher, voice-core/stimme_speicher.py),
-- dann diese Migration. Ein älterer Kern kann nach 0029 Abdrücke lesen, aber keine mehr speichern (sein Upsert braucht den alten Index);
-- vor einem Rückweg des Kerns auf einen Stand ohne 0029 deshalb erst 0029_stimme_mikrofone.down.sql anwenden.
--
-- Wozu: Der wichtigste Faktor der Stimmprüfung ist das Mikrofon (Befund 17. und 18.11.2026: mit dem Laptop-Mikrofon eingelernt lagen kurze
-- eigene Sätze am selben Gerät bei 0,53 bis 0,71, mit einem anderen Gerät bei 0,14 bis 0,49). Jede Person lernt deshalb jedes ihrer
-- Mikrofone einmal ein, höchstens drei, und die Prüfung nimmt den besten Wert über ihre Abdrücke (je Modell getrennt, TitaNet für das
-- Urteil, der Schatten nur für das Protokoll). Einlernen mit einem Mikrofon, für das es schon einen Abdruck gibt, ersetzt nur diesen.
--
-- Entwurf: keine neue Tabelle. speakers trägt seit 0001 genau einen Abdruck je Zeile mit Einwilligung, Schwelle (0025) und Schatten (0028);
-- jetzt gibt es je Person eine Zeile je Mikrofon (is_owner, wie bisher). Die Löschliste der Labore (voice-core/labor_loeschliste.py, 0018)
-- bleibt deshalb, wie sie ist: Sie löscht speakers je user_id, also alle Abdrücke; Laborprofile bekommen ohnehin nie einen.
--   mikrofon       Kennung des Mikrofons: 'unbekannt' oder 32 Hexzeichen (SHA-256 des bereinigten Namens in Kleinschrift,
--                  voice-core/stimme_mikrofon.py). Vorgabe 'unbekannt': jede vorhandene Zeile (ein Abdruck aus der Zeit vor 0029) wird
--                  zum unbekannten Mikrofon, ohne Datenverlust.
--   mikrofon_name  Name des Mikrofons, wie Browser oder App ihn nennen, zur Anzeige in den Einstellungen; 1 bis 120 Zeichen ohne
--                  Steuerzeichen, NULL beim unbekannten Mikrofon.
-- Eindeutig ist jetzt (user_id, mikrofon) unter is_owner statt user_id allein (Index speakers_owner_mikrofon_idx ersetzt
-- speakers_one_owner_idx). Höchstens drei Zeilen mit is_owner je Person erzwingt der Trigger speakers_mikrofon_grenze: Er zählt die übrigen
-- Mikrofone der Person (ohne das eigene, so geht ein Upsert auf ein vorhandenes Mikrofon durch) unter einer Sperre je Person
-- (pg_advisory_xact_lock), damit zwei gleichzeitige Einlernvorgänge nicht beide durchrutschen. Keine security definer, die Funktion liest
-- nur Zeilen derselben Person unter den Rechten des Aufrufers; das genügt, weil nur wamo_core schreibt (Policy core_all sieht alle Zeilen)
-- und unter READ COMMITTED (jede Anweisung sieht nach der Sperre den bestätigten Stand). Eine Rolle ohne Sicht auf die Zeilen oder
-- REPEATABLE READ bräuchte eine andere Lösung. Dieselbe Funktion hält die Kennung einer Zeile fest: ein update auf ein anderes Mikrofon lehnt
-- sie ab, denn ein Abdruck gehört zu dem Mikrofon, mit dem er eingelernt wurde. Der unbekannte Abdruck zählt zu den drei Plätzen; die
-- Oberfläche bietet ihn zum Löschen an, sobald das Mikrofon neu eingelernt ist.
-- Der Schatten (0028) gilt jetzt mit stimme-2 und stimme-3 (voice-core/stimme_einwilligung.py: stimme-3 nennt je eingelerntem Mikrofon einen
-- Abdruck aus 192 und einen aus 256 Zahlen, höchstens drei Mikrofone). Biometrisch bleibt jede Zeile wie bisher (DSGVO Art. 9): Löschen
-- aller Abdrücke einer Person ist weiter delete ... where user_id = ... and is_owner, Löschen eines Mikrofons dazu and mikrofon = ...
--
-- Rechte: Der Kern (wamo_core) hat auf speakers seit 0001 select, insert, update und delete für die ganze Tabelle; dieses Tabellenrecht gilt
-- auch für die neuen Spalten und bleibt wirksam (ein Widerruf auf Spalten nimmt es nicht zurück, wamo_core dürfte also auch mikrofon
-- ändern; das verhindert der Trigger, nicht das Recht). Die Spaltenrechte hier halten fest, was der Kern braucht (select und insert beider
-- Spalten, update nur des Namens), damit es nicht nur am Tabellenrecht hängt; alle anderen Rollen bekommen nichts. Kein neues delete, keine
-- neue Policy (core_all aus 0001 bleibt).
set local lock_timeout = '5s';  -- ALTER TABLE und der neue Index sperren speakers kurz; hängt es, bricht die Migration ab statt zu stauen

do $$ begin
  if to_regclass('__SCHEMA__.speakers') is null then
    raise exception '0029 braucht 0001 (Tabelle __SCHEMA__.speakers fehlt)';
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = '__SCHEMA__' and table_name = 'speakers'
                   and column_name = 'voiceprint_shadow') then
    raise exception '0029 braucht 0028 (Spalte __SCHEMA__.speakers.voiceprint_shadow fehlt)';
  end if;
end $$;

alter table __SCHEMA__.speakers
  add column if not exists mikrofon text not null default 'unbekannt',
  add column if not exists mikrofon_name text;

alter table __SCHEMA__.speakers
  drop constraint if exists speakers_mikrofon_chk,
  add constraint speakers_mikrofon_chk check (mikrofon ~ '^(unbekannt|[0-9a-f]{32})$'),
  drop constraint if exists speakers_mikrofon_name_chk,
  add constraint speakers_mikrofon_name_chk
    check (mikrofon_name is null
           or (mikrofon <> 'unbekannt' and char_length(mikrofon_name) between 1 and 120 and mikrofon_name !~ '[[:cntrl:]]'
               and mikrofon_name !~ '[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')),
  drop constraint if exists speakers_shadow_consent_chk,
  add constraint speakers_shadow_consent_chk check (voiceprint_shadow is null or consent_text_version in ('stimme-2', 'stimme-3'));

comment on column __SCHEMA__.speakers.mikrofon is
  'Kennung des Mikrofons dieses Abdrucks: unbekannt oder 32 Hexzeichen (voice-core/stimme_mikrofon.py); je Person höchstens drei';
comment on column __SCHEMA__.speakers.mikrofon_name is
  'Name des Mikrofons, wie Browser oder App ihn nennen (zur Anzeige), NULL beim unbekannten Mikrofon; nur der Kern';

-- ---------- Eindeutig je Person und Mikrofon ----------
-- Erst der neue Index (er gilt für den Bestand: je Person höchstens eine Zeile mit is_owner, alle mit unbekannt), dann der alte weg
create unique index if not exists speakers_owner_mikrofon_idx on __SCHEMA__.speakers (user_id, mikrofon) where is_owner;
drop index if exists __SCHEMA__.speakers_one_owner_idx;

-- ---------- Höchstens drei Mikrofone je Person ----------
create or replace function __SCHEMA__.speakers_mikrofon_grenze() returns trigger
language plpgsql
set search_path = ''
as $f$
begin
  if tg_op = 'UPDATE' and new.mikrofon is distinct from old.mikrofon then
    raise exception 'speakers: die Kennung des Mikrofons ist fest, für ein anderes Mikrofon neu einlernen' using errcode = '23514';
  end if;
  if new.is_owner then
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('wamo.speakers.mikrofon.' || new.user_id::text, 0));
    if (select count(*) from __SCHEMA__.speakers s
         where s.user_id = new.user_id and s.is_owner and s.mikrofon <> new.mikrofon and s.id <> new.id) >= 3 then
      raise exception 'speakers: höchstens 3 Mikrofone je Profil' using errcode = '23514';
    end if;
  end if;
  return new;
end
$f$;
revoke all on function __SCHEMA__.speakers_mikrofon_grenze() from public, anon, authenticated, service_role, wamo_admin;

drop trigger if exists speakers_mikrofon_grenze on __SCHEMA__.speakers;
create trigger speakers_mikrofon_grenze
  before insert or update of is_owner, user_id, mikrofon on __SCHEMA__.speakers
  for each row execute function __SCHEMA__.speakers_mikrofon_grenze();

-- ---------- Rechte: nur der Kern, nur diese Spalten ----------
-- Erst zurücksetzen (ein zweiter Lauf nimmt so später nachgezogene Spaltenrechte zurück), dann genau das Nötige vergeben.
revoke all (mikrofon, mikrofon_name) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;
grant insert (mikrofon, mikrofon_name) on __SCHEMA__.speakers to wamo_core;
grant update (mikrofon_name) on __SCHEMA__.speakers to wamo_core;

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht und jede Spalte einzeln (has_column_privilege mit mehreren Rechten wäre
-- schon bei einem davon wahr).
do $$
declare
  recht text;
  rolle text;
  spalte text;
begin
  foreach spalte in array array['mikrofon', 'mikrofon_name'] loop
    foreach recht in array array['SELECT', 'INSERT'] loop
      if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', spalte, recht) then
        raise exception 'speakers (0029): wamo_core braucht % auf %', recht, spalte using errcode = '42501';
      end if;
    end loop;
    foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
      foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
        if has_column_privilege(rolle, '__SCHEMA__.speakers', spalte, recht) then
          raise exception 'speakers (0029): % darf % auf % nicht haben', rolle, recht, spalte using errcode = '42501';
        end if;
      end loop;
    end loop;
    -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
    if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
       and not has_column_privilege('wamo_core_s2', '__SCHEMA__.speakers', spalte, 'INSERT') then
      raise exception 'speakers (0029): wamo_core_s2 erbt INSERT auf % nicht', spalte using errcode = '42501';
    end if;
  end loop;
  if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'mikrofon_name', 'UPDATE') then
    raise exception 'speakers (0029): wamo_core braucht UPDATE auf mikrofon_name' using errcode = '42501';
  end if;
  -- Voraussetzungen im Kern (voice-core/stimme_speicher.py): Löschen der Zeilen (DSGVO Art. 17), Policy core_all, RLS an
  if not has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'DELETE') then
    raise exception 'speakers (0029): wamo_core braucht DELETE (Löschen der Abdrücke)' using errcode = '42501';
  end if;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'speakers' and policyname = 'core_all') then
    raise exception 'speakers (0029): Policy core_all fehlt' using errcode = '42501';
  end if;
  if has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'TRUNCATE')
     or not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.speakers'::regclass)
  then
    raise exception 'speakers (0029): unzulässige Rechte oder RLS aus' using errcode = '42501';
  end if;
  -- die Regeln hängen an der Tabelle und sind geprüft (nicht NOT VALID), Index und Trigger sind da, der alte Index ist weg
  if (select count(*) from pg_constraint where conrelid = '__SCHEMA__.speakers'::regclass and contype = 'c' and convalidated
        and conname in ('speakers_mikrofon_chk', 'speakers_mikrofon_name_chk', 'speakers_shadow_consent_chk')) <> 3 then
    raise exception 'speakers (0029): Regeln für das Mikrofon fehlen' using errcode = '23514';
  end if;
  if not exists (select 1 from pg_index i join pg_class c on c.oid = i.indexrelid
                  where i.indrelid = '__SCHEMA__.speakers'::regclass and c.relname = 'speakers_owner_mikrofon_idx'
                    and i.indisunique and i.indisvalid and i.indpred is not null)
     or to_regclass('__SCHEMA__.speakers_one_owner_idx') is not null then
    raise exception 'speakers (0029): Index je Person und Mikrofon fehlt oder der alte ist noch da' using errcode = '42704';
  end if;
  if not exists (select 1 from pg_trigger where tgrelid = '__SCHEMA__.speakers'::regclass and tgname = 'speakers_mikrofon_grenze'
                   and tgenabled = 'O' and not tgisinternal) then
    raise exception 'speakers (0029): Trigger speakers_mikrofon_grenze fehlt' using errcode = '42704';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0029_stimme_mikrofone') on conflict do nothing;
