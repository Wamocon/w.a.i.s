-- WAMO 0024: Die Person wählt ihre Modelle und die Stimme im Haus selbst (Wunsch von Niko vom 16.11.2026: "alle Anbieter und Modelle
-- umschaltbar in der UI"). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0024_modellwahl_selbst.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0024_modellwahl_selbst.down.sql. Hängt nur von 0010 ab (Tabelle model_access, Policy core_all).
--
-- Neue Spalten, je NULL heißt "automatisch" bzw. "Standard des Kerns" (so bleibt jede vorhandene Zeile unverändert):
--   modell_gespraech    Gesprächsmodell der Person
--   modell_bilder       Modell für Bildschirm und Bilder
--   modell_hintergrund  Modell für Lernen und Zusammenfassung
--   tts_stimme          Stimme der Sprachausgabe im Haus (eine der neun Stimmen des Dienstes)
-- Welche Werte gelten, entscheidet allein der Kern aus festen Listen (voice-core/modellwahl.py aus der Modellkarte, für die Stimme
-- voice-core/sprache_anbieter.py, HAUS_STIMMEN), beim Setzen und noch einmal beim Laden: Ein Hausprofil bekommt nie ein Claude-Modell,
-- ein vom Admin festgelegtes Profil (nur_haus) ist für die Modellwahl gesperrt, ein vom Admin gesetztes Claude-Modell (claude_modell)
-- ist das einzige Claude-Modell. Die Datenbank prüft nur die Form (Kleinbuchstaben, Ziffern, Punkt, Bindestrich bzw. Unterstrich), damit
-- eine neue Messung in der Modellkarte keine neue Migration braucht. Spracherkennung und Sprachausgabe (stt, tts) sind seit 0010 getrennte
-- Spalten und seit 0023 vom Kern schreibbar; hier ändert sich daran nichts.
-- Rechte: nur der Kern (wamo_core) liest, fügt ein und ändert diese vier Spalten, immer nur für das Profil der geprüften Anfrage
-- (voice-core/modellzugang.py, modell_setzen und haus_stimme_setzen: user_id aus der Identität, nie aus dem Body; jede Wahl als Zeile in
-- actions). Die Verwaltung (wamo_admin) bekommt nichts (sie legt weiter nur nur_haus, claude_modell, stt und tts fest). Kein delete;
-- keine Rechte für anon, authenticated und service_role. Laborprofile: Der Kern schreibt für sie nie (labor.py, modellzugang_api.py)
-- und beachtet beim Laden für sie keine Wahl.
-- Wichtig: 0010 danach nie erneut anwenden; ihr revoke all nähme auch diese Rechte und die aus 0011, 0012 und 0023 wieder weg (wenn
-- doch geschehen: 0011, 0012, 0023 und 0024 der Reihe nach erneut anwenden).
set local lock_timeout = '5s';  -- ALTER TABLE sperrt model_access kurz; hängt es, bricht die Migration ab statt zu stauen

do $$ begin
  if to_regclass('__SCHEMA__.model_access') is null then
    raise exception '0024 braucht 0010 (Tabelle __SCHEMA__.model_access fehlt)';
  end if;
end $$;

alter table __SCHEMA__.model_access
  add column if not exists modell_gespraech text,
  add column if not exists modell_bilder text,
  add column if not exists modell_hintergrund text,
  add column if not exists tts_stimme text;

-- Je Spalte eine Prüfung (die Fehlermeldung nennt dann die Spalte, eine spätere Lockerung trifft nur sie). Länge 2 bis 63 bzw. 2 bis 32.
alter table __SCHEMA__.model_access
  drop constraint if exists model_access_modell_gespraech_form,
  drop constraint if exists model_access_modell_bilder_form,
  drop constraint if exists model_access_modell_hintergrund_form,
  drop constraint if exists model_access_tts_stimme_form,
  add constraint model_access_modell_gespraech_form
    check (modell_gespraech is null or modell_gespraech ~ '^[a-z0-9][a-z0-9.-]{1,62}$'),
  add constraint model_access_modell_bilder_form
    check (modell_bilder is null or modell_bilder ~ '^[a-z0-9][a-z0-9.-]{1,62}$'),
  add constraint model_access_modell_hintergrund_form
    check (modell_hintergrund is null or modell_hintergrund ~ '^[a-z0-9][a-z0-9.-]{1,62}$'),
  add constraint model_access_tts_stimme_form check (tts_stimme is null or tts_stimme ~ '^[a-z][a-z0-9_]{1,31}$');

comment on column __SCHEMA__.model_access.modell_gespraech is
  'Gesprächsmodell der Person (Alias der Modellkarte oder Claude-ID), NULL = automatisch; gültige Werte prüft der Kern (modellwahl.py)';
comment on column __SCHEMA__.model_access.modell_bilder is
  'Modell der Person für Bildschirm und Bilder, NULL = automatisch; gültige Werte prüft der Kern (modellwahl.py)';
comment on column __SCHEMA__.model_access.modell_hintergrund is
  'Modell der Person für Lernen und Zusammenfassung, NULL = automatisch; gültige Werte prüft der Kern (modellwahl.py)';
comment on column __SCHEMA__.model_access.tts_stimme is
  'Stimme der Sprachausgabe im Haus, NULL = Standard des Kerns (WAMO_TTS_HAUS_STIMME); gültige Werte prüft der Kern';

-- ---------- Rechte: nur der Kern, nur diese Spalten ----------
-- Erst zurücksetzen (ein zweiter Lauf nimmt so später nachgezogene Rechte zurück), dann genau das Nötige vergeben.
revoke all (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme)
  on __SCHEMA__.model_access from public, anon, authenticated, service_role, wamo_core, wamo_admin;
grant select (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;
grant insert (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;
grant update (modell_gespraech, modell_bilder, modell_hintergrund, tts_stimme) on __SCHEMA__.model_access to wamo_core;

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht und jede Spalte einzeln (has_column_privilege mit mehreren
-- Rechten wäre schon bei einem davon wahr).
do $$
declare
  spalte text;
  recht text;
  rolle text;
begin
  foreach spalte in array array['modell_gespraech', 'modell_bilder', 'modell_hintergrund', 'tts_stimme'] loop
    foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
      if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', spalte, recht) then
        raise exception 'model_access (0024): wamo_core braucht % auf %', recht, spalte using errcode = '42501';
      end if;
      foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
        if has_column_privilege(rolle, '__SCHEMA__.model_access', spalte, recht) then
          raise exception 'model_access (0024): % darf % auf % nicht haben', rolle, recht, spalte using errcode = '42501';
        end if;
      end loop;
    end loop;
  end loop;
  -- Was der Kern weiter nicht darf: nur_haus und claude_modell setzen (Zwang und Modell des Admins)
  foreach spalte in array array['nur_haus', 'claude_modell'] loop
    foreach recht in array array['INSERT', 'UPDATE'] loop
      if has_column_privilege('wamo_core', '__SCHEMA__.model_access', spalte, recht) then
        raise exception 'model_access (0024): wamo_core darf % auf % nicht haben', recht, spalte using errcode = '42501';
      end if;
    end loop;
  end loop;
  -- Voraussetzungen des Upserts im Kern: user_id einfügen und lesen (Konfliktziel), Policy core_all
  foreach recht in array array['SELECT', 'INSERT'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'user_id', recht) then
      raise exception 'model_access (0024): wamo_core braucht % auf user_id', recht using errcode = '42501';
    end if;
  end loop;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'model_access'
                   and policyname = 'core_all') then
    raise exception 'model_access (0024): Policy core_all fehlt' using errcode = '42501';
  end if;
  -- die vier Prüfungen der Form hängen an der Tabelle und sind geprüft (nicht NOT VALID)
  if (select count(*) from pg_constraint where conrelid = '__SCHEMA__.model_access'::regclass and contype = 'c' and convalidated
        and conname in ('model_access_modell_gespraech_form', 'model_access_modell_bilder_form',
                        'model_access_modell_hintergrund_form', 'model_access_tts_stimme_form')) <> 4 then
    raise exception 'model_access (0024): Prüfungen der Form fehlen' using errcode = '23514';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2') then
    foreach spalte in array array['modell_gespraech', 'modell_bilder', 'modell_hintergrund', 'tts_stimme'] loop
      if not has_column_privilege('wamo_core_s2', '__SCHEMA__.model_access', spalte, 'UPDATE') then
        raise exception 'model_access (0024): wamo_core_s2 erbt UPDATE auf % nicht', spalte using errcode = '42501';
      end if;
    end loop;
  end if;
  if has_table_privilege('wamo_core', '__SCHEMA__.model_access', 'DELETE')
     or has_table_privilege('wamo_core', '__SCHEMA__.model_access', 'TRUNCATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.model_access', 'claude_schluessel', 'SELECT')
     or not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.model_access'::regclass)
  then
    raise exception 'model_access (0024): unzulässige Rechte oder RLS aus' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0024_modellwahl_selbst') on conflict do nothing;
