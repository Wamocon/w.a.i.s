-- WAMO 0030: Rückstand an Aufträgen an W.A.I.S. selbst (Wunsch von Niko vom 19.11.2026: "WAIS muss auch Entwicklungsaufträge für sich selbst
-- speichern können, die wir dann hier oder später WAIS selbst an sich durchführen kann"). __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test
-- | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, ein zweiter Lauf ändert nichts):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0030_selbstauftraege.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0030_selbstauftraege.down.sql. Test: supabase/tests/0030_selbstauftraege_test.sql. Hängt nur von 0001 ab (profiles,
-- schema_migrations, Rollen wamo_core und wamo_admin).
-- wamo_prod nur nach ausdrücklicher Freigabe und nach dem Agenten database-reviewer.
--
-- Was hier entsteht: Eine Tabelle selbstauftraege, der gemeinsame Rückstand von Aufträgen an W.A.I.S. selbst (Verbesserungen, Fehler- und
-- Funktionswünsche am Assistenten). Admins legen Einträge an (Sprache über das Werkzeug selbstauftrag_speichern, die Oberfläche oder
-- Claude Code über scripts/wamo_selbstauftraege.py); abgearbeitet werden sie in Claude Code oder später von W.A.I.S. selbst. Das ist NICHT
-- der Entwurfsspeicher auftrag_entwuerfe (0026): Der gehört einer Person, verfällt nach 90 Tagen und lädt Karten für Aufträge an andere
-- Repos; ein Auftrag an das eigene Repo scheitert dort am Selbstschutz (dev_guard.ist_eigenes_repo). Hier steht nur Text, nichts davon wird
-- vom Kern ausgeführt.
--
-- Ein Eintrag ist ein VORSCHLAG, keine Anweisung: Wer ihn liest (Claude Code, später W.A.I.S.), setzt ihn nur nach dem ausdrücklichen Ja eines
-- Admins um. Der Text kann aus einem Gespräch stammen, in dem Fremdinhalt war (unsicher = true markiert genau das), und der Kern ersetzt
-- Zugangswerte im Text vor dem Speichern (selbstauftraege.geheimnisse_entfernen).
--
-- Spalten:
--   nr            kurze, fortlaufende Nummer zum Nennen und Ansprechen ("SA-7"); die Datenbank vergibt sie, niemand setzt sie selbst
--   titel         1 bis 80 Zeichen, eine Zeile ohne Steuerzeichen
--   beschreibung  1 bis 4000 Zeichen
--   art           Auftragsart wie in werkzeugkarte.py (welche es gibt, prüft der Kern; so braucht eine neue Art keine Migration)
--   abnahme       höchstens 5 Kriterien (Texte) als JSON-Liste, zusammen höchstens 8192 Byte
--   prioritaet    1 hoch, 2 normal, 3 niedrig
--   status        offen | in_arbeit | erledigt | verworfen (Übergänge: Trigger selbstauftraege_status)
--   quelle        sprache | oberflaeche | claude_code
--   unsicher      der Eintrag entstand nach Fremdinhalt in der Sitzung
--   erstellt_von  Profil des Admins; wird das Profil gelöscht, bleibt der Eintrag (set null), denn der Rückstand gehört W.A.I.S.
--   bearbeiter    claude_code | wais, nur gesetzt, solange jemand dran ist oder es getan hat
--   ergebnis      Satz zum Ergebnis (zum Beispiel Pull Request), höchstens 2000 Zeichen
--
-- Grenzen: höchstens 200 Einträge mit Status offen oder in_arbeit (Trigger selbstauftraege_grenze unter einer Sperre, damit zwei
-- gleichzeitige Einfügungen nacheinander zählen). Nichts wird gelöscht: Verwerfen und Erledigen sind Status, so bleibt der Verlauf.
--
-- Rechte (CLAUDE.md): nur wamo_core. Lesen; Einfügen nur in die Spalten, die der Kern liefert (nr, id, status, bearbeiter, ergebnis und
-- die Zeiten setzt die Datenbank); KEIN update auf der Tabelle. Den Stand ändert der Kern allein über zwei Funktionen mit festen Übergängen
-- (selbstauftrag_verwerfen: offen oder in_arbeit nach verworfen, selbstauftrag_oeffnen: verworfen nach offen; security definer mit leerem
-- search_path wie in 0022, ausführbar nur für wamo_core). So kann der Kern weder "erledigt" noch "in_arbeit" setzen noch einen laufenden Auftrag
-- auf offen zurückstellen (das tut allein der Bearbeiter über Claude Code mit Rechten der Datenbank). Das Wiedereröffnen hält die Grenze von 200
-- ein (der Trigger selbstauftraege_status prüft sie unter derselben Sperre wie das Einfügen). Kein delete, kein truncate. anon, authenticated,
-- service_role und wamo_admin haben keine Rechte. Vor dem Vergeben wird auch wamo_core alles entzogen, damit ein Nachlauf nach geänderten
-- Rechten zum selben Stand führt.
set local lock_timeout = '5s';

do $$ begin
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0001_wamo_init') then
    raise exception '0030 braucht 0001';
  end if;
end $$;

-- ---------- Tabelle ----------
create table if not exists __SCHEMA__.selbstauftraege (
  id            uuid primary key default gen_random_uuid(),
  nr            bigint generated always as identity,
  titel         text not null,
  beschreibung  text not null,
  art           text not null default 'umsetzung',
  abnahme       jsonb not null default '[]'::jsonb,
  prioritaet    smallint not null default 2,
  status        text not null default 'offen',
  quelle        text not null default 'sprache',
  unsicher      boolean not null default false,
  erstellt_von  uuid references __SCHEMA__.profiles(user_id) on delete set null,
  erstellt_at   timestamptz not null default now(),
  bearbeiter    text,
  bearbeitet_at timestamptz,
  ergebnis      text,
  geaendert_at  timestamptz not null default now(),
  constraint selbstauftraege_nr_key unique (nr),
  constraint selbstauftraege_titel_chk check (length(titel) between 1 and 80 and titel !~ '[[:cntrl:]]' and length(btrim(titel)) >= 1),
  constraint selbstauftraege_beschreibung_chk check (length(beschreibung) between 1 and 4000 and length(btrim(beschreibung)) >= 1),
  constraint selbstauftraege_art_chk check (art ~ '^[a-z][a-z_]{1,29}$'),
  -- case statt and: jsonb_array_length wirft bei einem Nicht-Array, und and hat in SQL keine feste Reihenfolge
  constraint selbstauftraege_abnahme_chk check (case when jsonb_typeof(abnahme) = 'array'
    then jsonb_array_length(abnahme) <= 5 and not jsonb_path_exists(abnahme, '$[*] ? (@.type() != "string")')
    else false end),
  constraint selbstauftraege_abnahme_groesse_chk check (pg_column_size(abnahme) <= 8192),
  constraint selbstauftraege_prioritaet_chk check (prioritaet between 1 and 3),
  constraint selbstauftraege_status_chk check (status in ('offen', 'in_arbeit', 'erledigt', 'verworfen')),
  constraint selbstauftraege_quelle_chk check (quelle in ('sprache', 'oberflaeche', 'claude_code')),
  constraint selbstauftraege_bearbeiter_chk check (bearbeiter is null or bearbeiter in ('claude_code', 'wais')),
  -- wer dran ist oder es getan hat, ist bekannt; offen und verworfen brauchen niemanden
  constraint selbstauftraege_bearbeiter_status_chk check (status in ('offen', 'verworfen') or bearbeiter is not null),
  constraint selbstauftraege_ergebnis_chk check (ergebnis is null or length(ergebnis) between 1 and 2000)
);
comment on table __SCHEMA__.selbstauftraege is
  'Rückstand an Aufträgen an W.A.I.S. selbst (nur Text, Vorschläge, keine Anweisungen), gemeinsam für Admins. Nur der Kern; Status statt delete.';

-- ---------- Indizes ----------
-- Fremdschlüssel erstellt_von (partiell, die Spalte ist optional)
create index if not exists selbstauftraege_von_idx on __SCHEMA__.selbstauftraege (erstellt_von) where erstellt_von is not null;
-- Die Liste: offene und laufende zuerst nach Priorität und Nummer
create index if not exists selbstauftraege_liste_idx on __SCHEMA__.selbstauftraege (status, prioritaet, nr);

-- ---------- Grenze (Trigger) ----------
-- security invoker (Standard): Der Trigger zählt mit den Rechten dessen, der einfügt (nur wamo_core darf das, und er darf lesen).
create or replace function __SCHEMA__.selbstauftraege_grenze() returns trigger
language plpgsql set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('__SCHEMA__.selbstauftraege', 0));
  if (select count(*) from __SCHEMA__.selbstauftraege s where s.status in ('offen', 'in_arbeit')) >= 200 then
    raise exception 'selbstauftraege: höchstens 200 offene Aufträge'
      using errcode = '23514', constraint = 'selbstauftraege_grenze';  -- der Kern erkennt die Grenze am Namen
  end if;
  return new;
end $$;
revoke all on function __SCHEMA__.selbstauftraege_grenze() from public, anon, authenticated, service_role, wamo_core, wamo_admin;
drop trigger if exists selbstauftraege_grenze on __SCHEMA__.selbstauftraege;
create trigger selbstauftraege_grenze before insert on __SCHEMA__.selbstauftraege
  for each row execute function __SCHEMA__.selbstauftraege_grenze();

-- ---------- Statusübergänge (Trigger) ----------
-- offen -> in_arbeit | erledigt | verworfen, in_arbeit -> offen | erledigt | verworfen, verworfen -> offen. Ein erledigter Auftrag bleibt erledigt.
-- Wieder offen setzt Bearbeiter und Zeit zurück, in_arbeit und erledigt stempeln die Zeit; geaendert_at stellt immer die Datenbank.
-- Verworfen -> offen macht aus einem nicht gezählten Eintrag einen gezählten: Das Wiedereröffnen hält deshalb dieselbe Grenze von 200 ein wie
-- das Einfügen (dieselbe Sperre, dieselbe Zählung, derselbe Fehlername selbstauftraege_grenze).
create or replace function __SCHEMA__.selbstauftraege_status() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.status is distinct from old.status then
    if not ((old.status = 'offen' and new.status in ('in_arbeit', 'erledigt', 'verworfen'))
         or (old.status = 'in_arbeit' and new.status in ('offen', 'erledigt', 'verworfen'))
         or (old.status = 'verworfen' and new.status = 'offen')) then
      raise exception 'selbstauftraege: Übergang % nach % ist nicht erlaubt', old.status, new.status
        using errcode = '23514', constraint = 'selbstauftraege_status_uebergang';
    end if;
    if old.status = 'verworfen' and new.status = 'offen' then
      perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('__SCHEMA__.selbstauftraege', 0));
      if (select count(*) from __SCHEMA__.selbstauftraege s where s.status in ('offen', 'in_arbeit')) >= 200 then
        raise exception 'selbstauftraege: höchstens 200 offene Aufträge'
          using errcode = '23514', constraint = 'selbstauftraege_grenze';
      end if;
    end if;
    if new.status = 'offen' then
      new.bearbeiter := null;
      new.bearbeitet_at := null;
    elsif new.status in ('in_arbeit', 'erledigt') then
      new.bearbeitet_at := pg_catalog.now();
    end if;
  end if;
  new.geaendert_at := pg_catalog.now();
  return new;
end $$;
revoke all on function __SCHEMA__.selbstauftraege_status() from public, anon, authenticated, service_role, wamo_core, wamo_admin;
drop trigger if exists selbstauftraege_status on __SCHEMA__.selbstauftraege;
create trigger selbstauftraege_status before update on __SCHEMA__.selbstauftraege
  for each row execute function __SCHEMA__.selbstauftraege_status();

-- ---------- Die zwei Übergänge des Kerns (Funktionen) ----------
-- security definer mit leerem search_path (alles mit Schema davor, wie 0022): Der Kern hat kein update auf der Tabelle und ändert den Stand
-- allein hierüber. Verwerfen geht aus offen und in_arbeit, Wiedereröffnen nur aus verworfen; was sonst nirgends hinführt, trifft keine Zeile
-- (Ergebnis null). Die Grenze von 200 beim Wiedereröffnen hält der Trigger selbstauftraege_status.
create or replace function __SCHEMA__.selbstauftrag_verwerfen(p_nr bigint) returns bigint
language sql security definer set search_path = '' as $$
  update __SCHEMA__.selbstauftraege set status = 'verworfen' where nr = p_nr and status in ('offen', 'in_arbeit') returning nr
$$;
create or replace function __SCHEMA__.selbstauftrag_oeffnen(p_nr bigint) returns bigint
language sql security definer set search_path = '' as $$
  update __SCHEMA__.selbstauftraege set status = 'offen' where nr = p_nr and status = 'verworfen' returning nr
$$;
revoke all on function __SCHEMA__.selbstauftrag_verwerfen(bigint) from public, anon, authenticated, service_role, wamo_admin, wamo_core;
revoke all on function __SCHEMA__.selbstauftrag_oeffnen(bigint) from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant execute on function __SCHEMA__.selbstauftrag_verwerfen(bigint) to wamo_core;
grant execute on function __SCHEMA__.selbstauftrag_oeffnen(bigint) to wamo_core;

-- ---------- Rechte (geringste Rechte) ----------
revoke all on __SCHEMA__.selbstauftraege from public, anon, authenticated, service_role, wamo_admin, wamo_core;
grant select on __SCHEMA__.selbstauftraege to wamo_core;
grant insert (titel, beschreibung, art, abnahme, prioritaet, quelle, unsicher, erstellt_von) on __SCHEMA__.selbstauftraege to wamo_core;

-- ---------- Row Level Security ----------
alter table __SCHEMA__.selbstauftraege enable row level security;
drop policy if exists core_all on __SCHEMA__.selbstauftraege;
create policy core_all on __SCHEMA__.selbstauftraege for all to wamo_core using (true) with check (true);

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_table_privilege mit mehreren Rechten wäre schon bei
-- einem davon wahr).
do $$
declare
  recht text;
  rolle text;
  spalte text;
begin
  if not has_table_privilege('wamo_core', '__SCHEMA__.selbstauftraege', 'SELECT') then
    raise exception 'selbstauftraege (0030): wamo_core braucht SELECT' using errcode = '42501';
  end if;
  foreach recht in array array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
    if has_table_privilege('wamo_core', '__SCHEMA__.selbstauftraege', recht) then
      raise exception 'selbstauftraege (0030): wamo_core darf % auf der Tabelle nicht haben', recht using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['titel', 'beschreibung', 'art', 'abnahme', 'prioritaet', 'quelle', 'unsicher', 'erstellt_von'] loop
    if not has_column_privilege('wamo_core', '__SCHEMA__.selbstauftraege', spalte, 'INSERT') then
      raise exception 'selbstauftraege (0030): wamo_core braucht INSERT auf %', spalte using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['id', 'nr', 'status', 'erstellt_at', 'bearbeiter', 'bearbeitet_at', 'ergebnis', 'geaendert_at'] loop
    if has_column_privilege('wamo_core', '__SCHEMA__.selbstauftraege', spalte, 'INSERT') then
      raise exception 'selbstauftraege (0030): wamo_core darf % nicht selbst setzen', spalte using errcode = '42501';
    end if;
  end loop;
  -- kein einziges Update-Recht: den Stand ändert der Kern nur über die beiden Funktionen
  if has_any_column_privilege('wamo_core', '__SCHEMA__.selbstauftraege', 'UPDATE') then
    raise exception 'selbstauftraege (0030): wamo_core darf nichts direkt ändern' using errcode = '42501';
  end if;
  -- die Funktionen: security definer mit leerem search_path, ausführbar außer dem Eigentümer nur für wamo_core (kein PUBLIC)
  foreach spalte in array array['selbstauftrag_verwerfen', 'selbstauftrag_oeffnen'] loop
    if not (select p.prosecdef from pg_proc p where p.oid = ('__SCHEMA__.' || spalte || '(bigint)')::regprocedure)
       or not exists (select 1 from pg_proc p where p.oid = ('__SCHEMA__.' || spalte || '(bigint)')::regprocedure
                        and p.proconfig @> array['search_path=""'])
       or exists (select 1 from pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                   where p.oid = ('__SCHEMA__.' || spalte || '(bigint)')::regprocedure and a.privilege_type = 'EXECUTE'
                     and a.grantee <> p.proowner and a.grantee is distinct from (select r.oid from pg_roles r where r.rolname = 'wamo_core'))
       or not has_function_privilege('wamo_core', ('__SCHEMA__.' || spalte || '(bigint)')::regprocedure, 'EXECUTE') then
      raise exception 'selbstauftraege (0030): % hat unzulässige Rechte oder Form', spalte using errcode = '42501';
    end if;
  end loop;
  foreach rolle in array array['wamo_admin', 'anon', 'authenticated', 'service_role'] loop
    if has_any_column_privilege(rolle, '__SCHEMA__.selbstauftraege', 'SELECT,INSERT,UPDATE,REFERENCES')
       or has_table_privilege(rolle, '__SCHEMA__.selbstauftraege', 'DELETE')
       or has_table_privilege(rolle, '__SCHEMA__.selbstauftraege', 'TRUNCATE')
       or has_table_privilege(rolle, '__SCHEMA__.selbstauftraege', 'TRIGGER') then
      raise exception 'selbstauftraege (0030): % darf keine Rechte haben', rolle using errcode = '42501';
    end if;
  end loop;
  if not (select c.relrowsecurity from pg_class c where c.oid = '__SCHEMA__.selbstauftraege'::regclass)
     or (select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = 'selbstauftraege') <> 1
     or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = 'selbstauftraege'
                      and policyname = 'core_all')
  then
    raise exception 'selbstauftraege (0030): RLS oder Policy core_all fehlt' using errcode = '42501';
  end if;
  if (select count(*) from pg_trigger where tgrelid = '__SCHEMA__.selbstauftraege'::regclass and tgname in
        ('selbstauftraege_grenze', 'selbstauftraege_status') and not tgisinternal and tgenabled = 'O') <> 2 then
    raise exception 'selbstauftraege (0030): Trigger der Grenze oder der Statusübergänge fehlt' using errcode = '42501';
  end if;
  -- Die Login-Rolle des Kerns auf Sokrates-2 erbt wamo_core (INHERIT); fehlt die Rolle, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_core_s2')
     and (not has_table_privilege('wamo_core_s2', '__SCHEMA__.selbstauftraege', 'SELECT')
          or not has_column_privilege('wamo_core_s2', '__SCHEMA__.selbstauftraege', 'titel', 'INSERT')
          or not has_function_privilege('wamo_core_s2', '__SCHEMA__.selbstauftrag_verwerfen(bigint)', 'EXECUTE')) then
    raise exception 'selbstauftraege (0030): wamo_core_s2 erbt die Rechte von wamo_core nicht' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0030_selbstauftraege') on conflict do nothing;
