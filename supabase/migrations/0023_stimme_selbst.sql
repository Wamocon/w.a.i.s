-- WAMO 0023: Die Person wählt Hören und Stimme selbst (Soniox oder im Haus, Paket H5, docs/hausmodelle-und-kikollege.md).
-- __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0023_stimme_selbst.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0023_stimme_selbst.down.sql. Hängt nur von 0010 ab (Spalten stt und tts mit check soniox oder haus).
--
-- Wozu: Entscheidung von Niko vom 16.11.2026: Soniox bleibt Standard, jede Person kann in der Oberfläche auf "Im Haus"
-- umschalten. Bisher setzte nur die Verwaltung (wamo_admin) stt und tts; 0010 gab dem Kern darauf bewusst kein Schreibrecht.
-- Ab hier darf der Kern (wamo_core) genau diese zwei Spalten schreiben, nur für das Profil der geprüften Anfrage
-- (voice-core/modellzugang.py, stimme_setzen: immer user_id aus der Identität, nie aus dem Body; jede Wahl als Zeile in actions).
-- Was sich nicht ändert: Werte nur soniox oder haus (check aus 0010); nur_haus, claude_modell, Schlüssel und Token bleiben wie
-- bisher; kein delete; keine Rechte für anon, authenticated und service_role; die Rechte der Verwaltung bleiben unverändert.
-- Laborprofile: Der Kern schreibt für sie nie (labor.py sperrt Pfad und Nachricht, modellzugang_api.py lehnt zusätzlich ab), und
-- eine Laborsitzung hört immer über Soniox (voice-core/sprache_anbieter.py, Entscheidung F4).
-- Wichtig: 0010 danach nie erneut anwenden; ihr revoke all nähme auch diese Rechte und die aus 0011 und 0012 wieder weg (wenn
-- doch geschehen: 0011, 0012 und 0023 der Reihe nach erneut anwenden).
set local lock_timeout = '5s';

do $$ begin
  if to_regclass('__SCHEMA__.model_access') is null then
    raise exception '0023 braucht 0010 (Tabelle __SCHEMA__.model_access fehlt)';
  end if;
end $$;

-- Rechte: nur der Kern, nur stt und tts, nur einfügen und ändern (insert auf user_id hat er seit 0010).
-- grant ist wiederholbar; ein zweiter Lauf ändert nichts.
grant insert (stt, tts) on __SCHEMA__.model_access to wamo_core;
grant update (stt, tts) on __SCHEMA__.model_access to wamo_core;

comment on column __SCHEMA__.model_access.stt is
  'Spracherkennung des Profils: soniox (Standard) oder haus. Setzen die Person selbst (Kern, ab 0023) und die Verwaltung';
comment on column __SCHEMA__.model_access.tts is
  'Sprachausgabe des Profils: soniox (Standard) oder haus. Setzen die Person selbst (Kern, ab 0023) und die Verwaltung';

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht und jede Spalte einzeln (has_column_privilege mit mehreren
-- Rechten wäre schon bei einem davon wahr).
do $$
declare
  spalte text;
  recht text;
  rolle text;
begin
  foreach spalte in array array['stt', 'tts'] loop
    foreach recht in array array['SELECT', 'INSERT', 'UPDATE'] loop
      if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', spalte, recht) then
        raise exception 'model_access (0023): wamo_core braucht % auf %', recht, spalte using errcode = '42501';
      end if;
      foreach rolle in array array['anon', 'authenticated', 'service_role'] loop
        if has_column_privilege(rolle, '__SCHEMA__.model_access', spalte, recht) then
          raise exception 'model_access (0023): % darf % auf % nicht haben', rolle, recht, spalte using errcode = '42501';
        end if;
      end loop;
    end loop;
  end loop;
  foreach spalte in array array['nur_haus', 'claude_modell'] loop
    foreach recht in array array['INSERT', 'UPDATE'] loop
      if has_column_privilege('wamo_core', '__SCHEMA__.model_access', spalte, recht) then
        raise exception 'model_access (0023): wamo_core darf % auf % nicht haben', recht, spalte using errcode = '42501';
      end if;
    end loop;
  end loop;
  -- Voraussetzungen des Upserts im Kern: user_id einfügen und lesen (Konfliktziel), Policy core_all; sonst käme 42501, und der
  -- Kern meldete fälschlich, 0023 fehle
  foreach recht in array array['SELECT', 'INSERT'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.model_access', 'user_id', recht) then
      raise exception 'model_access (0023): wamo_core braucht % auf user_id', recht using errcode = '42501';
    end if;
  end loop;
  if not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'model_access'
                   and policyname = 'core_all') then
    raise exception 'model_access (0023): Policy core_all fehlt' using errcode = '42501';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2') then
    foreach spalte in array array['stt', 'tts'] loop
      if not has_column_privilege('wamo_core_s2', '__SCHEMA__.model_access', spalte, 'UPDATE') then
        raise exception 'model_access (0023): wamo_core_s2 erbt UPDATE auf % nicht', spalte using errcode = '42501';
      end if;
    end loop;
  end if;
  if has_table_privilege('wamo_core', '__SCHEMA__.model_access', 'DELETE')
     or has_table_privilege('wamo_core', '__SCHEMA__.model_access', 'TRUNCATE')
     or has_column_privilege('wamo_admin', '__SCHEMA__.model_access', 'claude_schluessel', 'SELECT')
     or not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.model_access'::regclass)
  then
    raise exception 'model_access (0023): unzulässige Rechte oder RLS aus' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0023_stimme_selbst') on conflict do nothing;
