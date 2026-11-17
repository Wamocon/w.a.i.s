-- WAMO 0025: Persönliche Schwelle der Stimme (Kalibrierung vom 17.11.2026). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0025_stimme_schwelle.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0025_stimme_schwelle.down.sql. Hängt nur von 0001 ab (Tabelle speakers, Policy core_all, Rechte des Kerns).
--
-- Wozu: Im Modus streng wurden über 70 % der kurzen eigenen Äußerungen verworfen, weil eine feste Schwelle (0,5) für kurze Äußerungen zu
-- hoch war. Seit der Kalibrierung lernt der Kern in Stücken von 1,5 s ein und misst dabei, wie ähnlich ein Stück der Person ihrem Abdruck ist
-- (je Stück gegen den Mittelpunkt der übrigen, 10-%-Quantil minus 0,03, begrenzt auf 0,30 bis 0,50; voice-core/stimme_modell.py,
-- schwelle_einlernen). Diese persönliche Schwelle gilt als Schwelle für kurze Äußerungen (voice-core/stimme_gate.py, schwelle_fuer).
--
-- Neue Spalte voice_threshold (real) in speakers, NULL heißt: keine persönliche Schwelle, es gilt WAMO_STIMME_EIGEN_MIN_KURZ (so bleibt jede
-- vorhandene Zeile unverändert, und ein Abdruck aus der Zeit vor 0025 läuft weiter). Die Datenbank erlaubt 0,2 bis 0,8 (etwas weiter als die
-- Grenzen beim Einlernen, damit eine spätere Messung keine neue Migration braucht); der Kern prüft beim Laden noch einmal und nimmt nur
-- endliche Zahlen in diesem Bereich. Die Schwelle ist eine Zahl über die Stimme, kein Abdruck; sie gehört trotzdem zur Zeile des Abdrucks
-- und verschwindet mit ihr (Löschen der Zeile, DSGVO Art. 17).
-- Rechte: Der Kern (wamo_core) hat auf speakers seit 0001 select, insert, update und delete für die ganze Tabelle, das gilt auch für die neue
-- Spalte. Damit das nicht nur an der Tabelle hängt, bekommt er hier genau select, insert und update auf voice_threshold; alle anderen Rollen
-- nichts (die Verwaltung wamo_admin, anon, authenticated und service_role haben auf speakers ohnehin kein Recht). Kein neues delete, keine
-- neue Policy (core_all aus 0001 bleibt). Laborprofile haben keinen Abdruck und keine Stimmsitzung (voice-core/stimme_sitzung.py), für sie
-- schreibt der Kern hier nie.
set local lock_timeout = '5s';  -- ALTER TABLE sperrt speakers kurz; hängt es, bricht die Migration ab statt zu stauen

do $$ begin
  if to_regclass('__SCHEMA__.speakers') is null then
    raise exception '0025 braucht 0001 (Tabelle __SCHEMA__.speakers fehlt)';
  end if;
end $$;

alter table __SCHEMA__.speakers
  add column if not exists voice_threshold real;

alter table __SCHEMA__.speakers
  drop constraint if exists speakers_voice_threshold_chk,
  add constraint speakers_voice_threshold_chk check (voice_threshold is null or voice_threshold between 0.2 and 0.8);

comment on column __SCHEMA__.speakers.voice_threshold is
  'Persönliche Schwelle der Stimme für kurze Äußerungen (Kosinus, vom Einlernen), NULL = WAMO_STIMME_EIGEN_MIN_KURZ; nur der Kern';

-- ---------- Rechte: nur der Kern, nur diese Spalte ----------
-- Erst zurücksetzen (ein zweiter Lauf nimmt so später nachgezogene Spaltenrechte zurück), dann genau das Nötige vergeben.
revoke all (voice_threshold) on __SCHEMA__.speakers from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (voice_threshold) on __SCHEMA__.speakers to wamo_core;
grant insert (voice_threshold) on __SCHEMA__.speakers to wamo_core;
grant update (voice_threshold) on __SCHEMA__.speakers to wamo_core;

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_column_privilege mit mehreren Rechten wäre schon bei einem
-- davon wahr).
do $$
declare
  recht text;
  rolle text;
begin
  foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'voice_threshold', recht) then
      raise exception 'speakers (0025): wamo_core braucht % auf voice_threshold', recht using errcode = '42501';
    end if;
    foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
      if has_column_privilege(rolle, '__SCHEMA__.speakers', 'voice_threshold', recht) then
        raise exception 'speakers (0025): % darf % auf voice_threshold nicht haben', rolle, recht using errcode = '42501';
      end if;
    end loop;
  end loop;
  -- Voraussetzungen des Upserts im Kern (voice-core/stimme_speicher.py): user_id und voiceprint lesen, einfügen und ändern, die Zeile
  -- löschen (DSGVO Art. 17), Policy core_all
  foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'voiceprint', recht)
       or not has_column_privilege('wamo_core', '__SCHEMA__.speakers', 'user_id', recht) then
      raise exception 'speakers (0025): wamo_core braucht % auf user_id und voiceprint', recht using errcode = '42501';
    end if;
  end loop;
  if not has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'DELETE') then
    raise exception 'speakers (0025): wamo_core braucht DELETE (Löschen des Abdrucks)' using errcode = '42501';
  end if;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'speakers' and policyname = 'core_all') then
    raise exception 'speakers (0025): Policy core_all fehlt' using errcode = '42501';
  end if;
  -- die Prüfung des Bereichs hängt an der Tabelle und ist geprüft (nicht NOT VALID)
  if not exists (select 1 from pg_constraint where conrelid = '__SCHEMA__.speakers'::regclass and contype = 'c' and convalidated
                   and conname = 'speakers_voice_threshold_chk') then
    raise exception 'speakers (0025): Prüfung des Bereichs fehlt' using errcode = '23514';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
     and not has_column_privilege('wamo_core_s2', '__SCHEMA__.speakers', 'voice_threshold', 'UPDATE') then
    raise exception 'speakers (0025): wamo_core_s2 erbt UPDATE auf voice_threshold nicht' using errcode = '42501';
  end if;
  if has_table_privilege('wamo_core', '__SCHEMA__.speakers', 'TRUNCATE')
     or not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.speakers'::regclass)
  then
    raise exception 'speakers (0025): unzulässige Rechte oder RLS aus' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0025_stimme_schwelle') on conflict do nothing;
