-- WAMO 0031: Datenbank des Werkstatt-Panels (Dienst wamo-werkstatt, Plan docs/adminpanel-werkstatt.md und docs/adminpanel-bauplan.md).
-- __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, ein zweiter Lauf ändert nichts):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0031_werkstatt.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0031_werkstatt.down.sql. Test: supabase/tests/0031_werkstatt_test.sql. Hängt ab von 0001 (profiles, sessions, turns, actions,
-- touch_updated_at, Rollen wamo_core und wamo_admin) und 0018 (labor_zaehlen). Nach dem Anwenden 0018 noch einmal anwenden: Der Selbsttest
-- dort muss weiter grün sein, weil wamo_werkstatt weder labor_loeschen noch labor_zaehlen ausführen darf.
-- wamo_prod nur nach ausdrücklicher Freigabe und nach dem Agenten database-reviewer.
--
-- Was hier entsteht (Stufe 1 des Panels: Laborplanung, Kartenkatalog, Kennzahlen; kein Schreiben an Laborprofilen, Konten oder Faktoren):
--   Rolle         wamo_werkstatt, Gruppenrolle ohne Anmeldung. Die Anmelde-Rolle (Mitglied dieser Gruppe) legt die Infrastruktur an,
--                 nie diese Migration. Die Rolle bekommt KEIN execute auf labor_loeschen und labor_zaehlen und keinerlei Schreibrecht auf
--                 profiles. Wegen der Prüfpflicht der Prüfstrecke (Lint pflicht_rolle_aendern meldet jede Rollenänderung in einer
--                 Migration) steht die Anlage in einer dynamischen Anweisung; der Vertrag der Werkstatt sieht sie hier ausdrücklich vor
--                 (Muster wie 0013). Einstellungen wie statement_timeout gehören an die Anmelde-Rolle, sie erbt von der Gruppe nichts.
--   Labor         labor_termine (Labortag, Zeiten, Einwilligungsversion, Stand, Aufbewahrung bis), labor_plaetze (Plätze 1 bis 16 je
--                 Termin, Zweck, Kennung, Pseudonym des Gasts), labor_checkliste, labor_zuordnung (Karten je Platz).
--   Katalog       labor_karten (Arbeitsstand der Karten, Entwurf oder veröffentlicht), labor_karten_versionen (unveränderliche
--                 Momentaufnahme aller Karten je Veröffentlichung, genau eine aktive), werkstatt_karten (Freigabekarten, fünf Minuten
--                 gültig, einmalig).
--   Kern          Zwei Ansichten, die einzigen Objekte, die wamo_core aus dieser Migration lesen darf (nur select):
--                 labor_karten_aktive_version (die Nummer der aktiven Version, leer ohne aktive) und labor_wissen_aktiv (je Karte der
--                 aktiven Version mit wissen = 'Eigener Text': version, karte_id, wissenstext). Die Ansichten lesen nur die
--                 Momentaufnahme, nie den Arbeitsstand: Was ein Entwurf ist, sieht der Kern nie.
--   Lesen         werkstatt_sitzungen, werkstatt_latenz, werkstatt_aktionen (je Tag oder je Werkzeug, nur Zahlen, nie Text, params oder
--                 result), werkstatt_labor_stand (Wrapper um labor_zaehlen, ohne Namen und E-Mail) und werkstatt_aufraeumen.
--
-- Form der Momentaufnahme (labor_karten_versionen.karten): ein JSON-Array mit je einem Objekt je Karte, Schlüssel gleich den Spalten von
-- labor_karten (id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min). Verlangt und von
-- der Datenbank geprüft werden id (Form A1 bis Z99), wissen (eine der vier Stufen) und bei wissen = 'Eigener Text' ein wissenstext von
-- 1 bis 900 Zeichen ohne Steuerzeichen. wissen_zeichen ist das Katalogbudget der Version (mindestens die Summe aller Wissenstexte, höchstens 2000; ein eigenes Budget, die Dateien des Kerns zählen nicht mit).
--
-- Die Tabellen haben je zwei Policies: core_all für wamo_core verbietet alles (using false), denn der Kern liest nur die Ansichten (die
-- laufen mit den Rechten des Eigentümers); werkstatt_all für wamo_werkstatt lässt zu, was die Spaltenrechte erlauben. Zusätzlich:
--   profiles  wamo_werkstatt liest genau user_id, rolle, aktiv und labor_art (Prüfung des Zugangs), nie Namen oder Einstellungen.
--   actions   wamo_werkstatt schreibt Audit-Zeilen und liest sie zurück, aber nur mit einem Werkzeug, das mit werkstatt_ beginnt
--             (Policies werkstatt_audit_insert und werkstatt_audit_lesen), und nie ändern oder löschen.
--
-- Befund zur Latenz: turns.latency_ms wird vom Kern heute nicht geschrieben (der Insert in memory.py lässt die Spalte aus). Die Funktion
-- werkstatt_latenz liefert deshalb Zeilen ohne Werte, bis der Kern die Spalte füllt oder der Sammler die Latenz anders liefert.
set local lock_timeout = '5s';

do $$ begin
  if (select count(*) from __SCHEMA__.schema_migrations where version in ('0001_wamo_init', '0018_labor_profile')) <> 2 then
    raise exception '0031 braucht 0001 und 0018';
  end if;
end $$;

-- ---------- Rolle ----------
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'wamo_werkstatt') then
    execute 'create role wamo_werkstatt nologin nosuperuser nocreatedb nocreaterole nobypassrls';
  end if;
end $$;
grant usage on schema __SCHEMA__ to wamo_werkstatt;

-- ---------- Tabellen ----------
create table if not exists __SCHEMA__.labor_termine (
  id                   uuid primary key default gen_random_uuid(),
  tag                  date not null,
  beginn               time,
  ende                 time,
  einwilligung_version smallint not null default 1,
  status               text not null default 'entwurf',
  aufbewahrung_bis     date not null,
  erstellt_von         uuid references __SCHEMA__.profiles(user_id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint labor_termine_tag_key unique (tag),
  constraint labor_termine_version_chk check (einwilligung_version between 1 and 99),
  constraint labor_termine_status_chk check (status in ('entwurf', 'freigegeben', 'laufend', 'nachlauf', 'abgeschlossen')),
  constraint labor_termine_frist_chk check (aufbewahrung_bis >= tag and aufbewahrung_bis <= tag + 14)
);
comment on table __SCHEMA__.labor_termine is
  'Labortage des Testlabors (Werkstatt-Panel). Der Löschlauf beginnt einen Tag nach aufbewahrung_bis und wird nur berechnet, nie gespeichert.';

create table if not exists __SCHEMA__.labor_plaetze (
  termin_id uuid not null references __SCHEMA__.labor_termine(id) on delete cascade,
  platz     smallint not null,
  zweck     text not null default 'besucher',
  kennung   text,
  gast      text,
  primary key (termin_id, platz),
  constraint labor_plaetze_platz_chk check (platz between 1 and 16),
  constraint labor_plaetze_zweck_chk check (zweck in ('besucher', 'reserve', 'abnahme')),
  constraint labor_plaetze_abnahme_chk check (zweck <> 'abnahme' or platz in (15, 16)),
  constraint labor_plaetze_kennung_chk check (kennung is null or kennung ~ '^labor-[a-z0-9]{2,8}$'),
  -- Pseudonym wie "Gast 1", nie ein Name
  constraint labor_plaetze_gast_chk check (gast is null or (length(gast) <= 20 and gast !~ '[[:cntrl:]]'))
);
comment on table __SCHEMA__.labor_plaetze is 'Plätze 1 bis 16 je Labortermin. Kein Gerätename, kein Name: der Gast ist ein Pseudonym.';

create table if not exists __SCHEMA__.labor_checkliste (
  id           bigint generated always as identity primary key,
  termin_id    uuid not null references __SCHEMA__.labor_termine(id) on delete cascade,
  titel        text not null,
  quelle       text,
  faellig      date,
  erledigt_at  timestamptz,
  erledigt_von uuid references __SCHEMA__.profiles(user_id) on delete set null,
  constraint labor_checkliste_titel_chk check (length(titel) between 1 and 120 and titel !~ '[[:cntrl:]]' and length(btrim(titel)) >= 1),
  constraint labor_checkliste_quelle_chk check (quelle is null or (length(quelle) <= 80 and quelle !~ '[[:cntrl:]]'))
);
comment on table __SCHEMA__.labor_checkliste is 'Checkliste je Labortermin (quelle: Abschnitt im Runbook).';

create table if not exists __SCHEMA__.labor_karten (
  id            text primary key,
  gruppe        text not null,
  titel         text not null,
  aufgabe       text not null,
  erwartung     text not null,
  fehler        text,
  lernziel      text,
  wissen        text not null default 'keine',
  wissenstext   text,
  werkzeuge     text[] not null default '{}',
  dauer_min     smallint not null,
  stand         text not null default 'entwurf',
  geaendert_von uuid references __SCHEMA__.profiles(user_id) on delete set null,
  geaendert_at  timestamptz not null default now(),
  constraint labor_karten_id_chk check (id ~ '^[A-Z][0-9]{1,2}$'),
  constraint labor_karten_gruppe_chk check (length(gruppe) between 1 and 30 and length(btrim(gruppe)) >= 1),
  constraint labor_karten_titel_chk check (length(titel) between 1 and 60 and length(btrim(titel)) >= 1),
  constraint labor_karten_aufgabe_chk check (length(aufgabe) between 1 and 240 and length(btrim(aufgabe)) >= 1),
  constraint labor_karten_erwartung_chk check (length(erwartung) between 1 and 240 and length(btrim(erwartung)) >= 1),
  -- null heißt: kein Fehlerfall
  constraint labor_karten_fehler_chk check (fehler is null or length(fehler) <= 120),
  constraint labor_karten_lernziel_chk check (lernziel is null or length(lernziel) <= 40),
  constraint labor_karten_wissen_chk check (wissen in ('keine', 'Glossar', 'ISTQB-Basis', 'Eigener Text')),
  -- der Text ist Pflicht genau bei 'Eigener Text', sonst null
  constraint labor_karten_wissenstext_chk check ((wissen = 'Eigener Text') = (wissenstext is not null)
                                                 and (wissenstext is null or length(wissenstext) between 1 and 900)),
  constraint labor_karten_werkzeuge_chk check (werkzeuge <@ array['Jira', 'Mail', 'Canvas', 'Websuche']::text[] and cardinality(werkzeuge) <= 4),
  constraint labor_karten_dauer_chk check (dauer_min between 1 and 20),
  constraint labor_karten_stand_chk check (stand in ('entwurf', 'veroeffentlicht')),
  -- keine Steuerzeichen in keinem Textfeld
  constraint labor_karten_zeichen_chk check ((gruppe || titel || aufgabe || erwartung || coalesce(fehler, '') || coalesce(lernziel, '')
                                              || coalesce(wissenstext, '')) !~ '[[:cntrl:]]')
);
comment on table __SCHEMA__.labor_karten is
  'Arbeitsstand der Karten des Testlabors. Der Kern liest ihn nie, nur die Momentaufnahme einer veröffentlichten Version.';

create table if not exists __SCHEMA__.labor_zuordnung (
  termin_id uuid not null references __SCHEMA__.labor_termine(id) on delete cascade,
  platz     smallint not null,
  karte_id  text not null references __SCHEMA__.labor_karten(id) on delete cascade,
  primary key (termin_id, platz, karte_id),
  constraint labor_zuordnung_platz_chk check (platz between 1 and 16)
);
comment on table __SCHEMA__.labor_zuordnung is 'Welche Karten ein Platz an einem Labortag bekommt.';

create table if not exists __SCHEMA__.labor_karten_versionen (
  version            integer generated always as identity primary key,
  erstellt_at        timestamptz not null default now(),
  erstellt_von       uuid references __SCHEMA__.profiles(user_id) on delete set null,
  anzahl_aenderungen integer not null,
  wissen_zeichen     integer not null,
  karten             jsonb not null,
  aktiv              boolean not null default false,
  constraint labor_karten_versionen_aenderungen_chk check (anzahl_aenderungen >= 0),
  constraint labor_karten_versionen_zeichen_chk check (wissen_zeichen between 0 and 2000)
);
comment on table __SCHEMA__.labor_karten_versionen is
  'Veröffentlichte Stände des Kartenkatalogs: unveränderliche Momentaufnahme, genau eine Version ist aktiv.';

create table if not exists __SCHEMA__.werkstatt_karten (
  id             uuid primary key default gen_random_uuid(),
  admin          uuid not null references __SCHEMA__.profiles(user_id) on delete cascade,
  aktion         text not null,
  ziel           jsonb not null,
  gilt_bis       timestamptz not null,
  ausgefuehrt_at timestamptz,
  created_at     timestamptz not null default now(),
  constraint werkstatt_karten_aktion_chk check (aktion in ('karten_veroeffentlichen')),
  -- nur Zahlen und Kennungen, nie Texte
  constraint werkstatt_karten_ziel_chk check (jsonb_typeof(ziel) = 'object' and pg_column_size(ziel) <= 16384),
  constraint werkstatt_karten_gilt_chk check (gilt_bis > created_at and gilt_bis <= created_at + interval '5 minutes')
);
comment on table __SCHEMA__.werkstatt_karten is
  'Freigabekarten des Werkstatt-Panels: fünf Minuten gültig, einmalig, an einen Admin gebunden. Nur Zahlen und Kennungen im Ziel.';

-- ---------- Indizes ----------
-- Fremdschlüssel (partiell, wo die Spalte optional ist)
create index if not exists labor_termine_von_idx on __SCHEMA__.labor_termine (erstellt_von) where erstellt_von is not null;
create index if not exists labor_checkliste_termin_idx on __SCHEMA__.labor_checkliste (termin_id);
create index if not exists labor_checkliste_von_idx on __SCHEMA__.labor_checkliste (erledigt_von) where erledigt_von is not null;
create index if not exists labor_karten_von_idx on __SCHEMA__.labor_karten (geaendert_von) where geaendert_von is not null;
create index if not exists labor_zuordnung_karte_idx on __SCHEMA__.labor_zuordnung (karte_id);
create index if not exists labor_karten_versionen_von_idx on __SCHEMA__.labor_karten_versionen (erstellt_von) where erstellt_von is not null;
create index if not exists werkstatt_karten_admin_idx on __SCHEMA__.werkstatt_karten (admin);
-- genau eine aktive Version
create unique index if not exists labor_karten_versionen_aktiv_uni on __SCHEMA__.labor_karten_versionen (aktiv) where aktiv;

-- ---------- Trigger ----------
drop trigger if exists labor_termine_touch on __SCHEMA__.labor_termine;
create trigger labor_termine_touch before update on __SCHEMA__.labor_termine
  for each row execute function __SCHEMA__.touch_updated_at();

-- Karten: Eine inhaltliche Änderung stempelt geaendert_at und macht aus einer veröffentlichten Karte wieder einen Entwurf, damit
-- keine Änderung am Katalog unbemerkt bleibt. Das Veröffentlichen ändert nur den Stand und zählt nicht als Änderung.
create or replace function __SCHEMA__.labor_karten_pflege() returns trigger
language plpgsql set search_path = '' as $$
begin
  if row(new.gruppe, new.titel, new.aufgabe, new.erwartung, new.fehler, new.lernziel, new.wissen, new.wissenstext, new.werkzeuge,
         new.dauer_min)
     is distinct from
     row(old.gruppe, old.titel, old.aufgabe, old.erwartung, old.fehler, old.lernziel, old.wissen, old.wissenstext, old.werkzeuge,
         old.dauer_min) then
    new.geaendert_at := pg_catalog.now();
    if old.stand = 'veroeffentlicht' and new.stand = 'veroeffentlicht' then
      new.stand := 'entwurf';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists labor_karten_pflege on __SCHEMA__.labor_karten;
create trigger labor_karten_pflege before update on __SCHEMA__.labor_karten
  for each row execute function __SCHEMA__.labor_karten_pflege();

-- Versionen: Beim Einfügen wird die Momentaufnahme geprüft (Array, höchstens 500 Karten, höchstens 1 MiB, je Karte id und wissen, bei
-- 'Eigener Text' ein Text von 1 bis 900 Zeichen ohne Steuerzeichen, Summe der Texte höchstens wissen_zeichen). Danach ändert sich nur aktiv.
create or replace function __SCHEMA__.labor_karten_versionen_schutz() returns trigger
language plpgsql set search_path = '' as $$
declare
  k     jsonb;
  t     text;
  summe integer := 0;
begin
  if tg_op = 'UPDATE' then
    if new.version is distinct from old.version or new.erstellt_at is distinct from old.erstellt_at
       or (new.erstellt_von is distinct from old.erstellt_von and new.erstellt_von is not null)  -- null setzt on delete set null beim Löschen des Profils
       or new.anzahl_aenderungen is distinct from old.anzahl_aenderungen
       or new.wissen_zeichen is distinct from old.wissen_zeichen or new.karten is distinct from old.karten then
      raise exception 'labor_karten_versionen: eine Version ist unveränderlich, nur aktiv wechselt' using errcode = '42501';
    end if;
    return new;
  end if;
  if jsonb_typeof(new.karten) is distinct from 'array' then
    raise exception 'labor_karten_versionen: karten muss ein Array sein' using errcode = '23514', constraint = 'labor_karten_versionen_karten';
  end if;
  if jsonb_array_length(new.karten) > 500 or pg_column_size(new.karten) > 1048576 then
    raise exception 'labor_karten_versionen: zu viele oder zu große Karten' using errcode = '23514', constraint = 'labor_karten_versionen_karten';
  end if;
  for k in select e.value from jsonb_array_elements(new.karten) as e loop
    if jsonb_typeof(k) is distinct from 'object'
       or jsonb_typeof(k -> 'id') is distinct from 'string' or (k ->> 'id') !~ '^[A-Z][0-9]{1,2}$'
       or jsonb_typeof(k -> 'wissen') is distinct from 'string'
       or (k ->> 'wissen') not in ('keine', 'Glossar', 'ISTQB-Basis', 'Eigener Text') then
      raise exception 'labor_karten_versionen: eine Karte der Momentaufnahme hat keine gültige id oder wissen'
        using errcode = '23514', constraint = 'labor_karten_versionen_karten';
    end if;
    if (k ->> 'wissen') = 'Eigener Text' then
      if jsonb_typeof(k -> 'wissenstext') is distinct from 'string' then
        raise exception 'labor_karten_versionen: Eigener Text ohne wissenstext' using errcode = '23514', constraint = 'labor_karten_versionen_karten';
      end if;
      t := k ->> 'wissenstext';
      if length(t) not between 1 and 900 or t ~ '[[:cntrl:]]' then
        raise exception 'labor_karten_versionen: wissenstext ist leer, zu lang oder enthält Steuerzeichen'
          using errcode = '23514', constraint = 'labor_karten_versionen_karten';
      end if;
      summe := summe + length(t);
    end if;
  end loop;
  if summe > new.wissen_zeichen then
    raise exception 'labor_karten_versionen: wissen_zeichen ist kleiner als die Summe der Wissenstexte'
      using errcode = '23514', constraint = 'labor_karten_versionen_zeichen';
  end if;
  return new;
end $$;
drop trigger if exists labor_karten_versionen_schutz on __SCHEMA__.labor_karten_versionen;
create trigger labor_karten_versionen_schutz before insert or update on __SCHEMA__.labor_karten_versionen
  for each row execute function __SCHEMA__.labor_karten_versionen_schutz();

-- Freigabekarten: Inhalt unveränderlich, ausgefuehrt_at nur einmal setzbar, und nur, solange die Karte gilt. Der Kern der Regel steht
-- im Dienst; das hier ist die zweite Linie. Verbraucht und abgelaufen erkennt der Dienst am Namen der Prüfung.
create or replace function __SCHEMA__.werkstatt_karten_schutz() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.id is distinct from old.id or new.admin is distinct from old.admin or new.aktion is distinct from old.aktion
     or new.ziel is distinct from old.ziel or new.gilt_bis is distinct from old.gilt_bis or new.created_at is distinct from old.created_at then
    raise exception 'werkstatt_karten: eine Karte ist unveränderlich, nur ausgefuehrt_at wird einmal gesetzt' using errcode = '42501';
  end if;
  if old.ausgefuehrt_at is not null then
    raise exception 'werkstatt_karten: die Karte ist schon verbraucht' using errcode = '23514', constraint = 'werkstatt_karten_verbraucht';
  end if;
  if new.ausgefuehrt_at is not null and pg_catalog.clock_timestamp() > old.gilt_bis then
    raise exception 'werkstatt_karten: die Karte ist abgelaufen' using errcode = '23514', constraint = 'werkstatt_karten_abgelaufen';
  end if;
  return new;
end $$;
drop trigger if exists werkstatt_karten_schutz on __SCHEMA__.werkstatt_karten;
create trigger werkstatt_karten_schutz before update on __SCHEMA__.werkstatt_karten
  for each row execute function __SCHEMA__.werkstatt_karten_schutz();

-- ---------- Ansichten für den Kern ----------
-- Sie laufen mit den Rechten des Eigentümers (der Kern hat auf die Tabellen kein Recht); security_barrier verhindert, dass ein Filter
-- des Aufrufers vor die Bedingung der Ansicht rutscht. Das Schema ist nicht in PostgREST.
create or replace view __SCHEMA__.labor_karten_aktive_version with (security_barrier = true) as
  select v.version from __SCHEMA__.labor_karten_versionen v where v.aktiv;

create or replace view __SCHEMA__.labor_wissen_aktiv with (security_barrier = true) as
  select v.version, k.karte ->> 'id' as karte_id, k.karte ->> 'wissenstext' as wissenstext
    from __SCHEMA__.labor_karten_versionen v
   cross join lateral jsonb_array_elements(v.karten) as k(karte)
   where v.aktiv and k.karte ->> 'wissen' = 'Eigener Text';

-- ---------- Lesefunktionen für das Panel ----------
-- security definer mit leerem search_path (alles mit Schema davor), ausführbar nur für wamo_werkstatt. Nur Zahlen. Tage nach
-- Berliner Zeit; p_tage von 1 bis 30, sonst Fehler 22023. Die Abfragen laufen ohne eigenen Index über started_at, created_at: bei dem
-- heutigen Umfang genügt ein Durchlauf.
create or replace function __SCHEMA__.werkstatt_sitzungen(p_tage integer)
returns table (tag date, anzahl bigint, dauer_p50_s integer, dauer_p95_s integer, offen bigint)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare
  v_heute date := (pg_catalog.now() at time zone 'Europe/Berlin')::date;
begin
  if p_tage is null or p_tage < 1 or p_tage > 30 then
    raise exception 'werkstatt_sitzungen: p_tage muss zwischen 1 und 30 liegen' using errcode = '22023';
  end if;
  return query
  select d.tag,
         count(s.id),
         round(percentile_cont(0.5) within group (order by extract(epoch from (s.ended_at - s.started_at))::double precision))::integer,
         round(percentile_cont(0.95) within group (order by extract(epoch from (s.ended_at - s.started_at))::double precision))::integer,
         count(s.id) filter (where s.ended_at is null)
    from (select v_heute - i as tag from generate_series(0, p_tage - 1) as i) d
    left join __SCHEMA__.sessions s on (s.started_at at time zone 'Europe/Berlin')::date = d.tag
   group by d.tag
   order by d.tag;
end $$;

create or replace function __SCHEMA__.werkstatt_latenz(p_tage integer)
returns table (tag date, zuege bigint, p50_ms integer, p95_ms integer)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare
  v_heute date := (pg_catalog.now() at time zone 'Europe/Berlin')::date;
begin
  if p_tage is null or p_tage < 1 or p_tage > 30 then
    raise exception 'werkstatt_latenz: p_tage muss zwischen 1 und 30 liegen' using errcode = '22023';
  end if;
  return query
  select d.tag,
         count(t.id),
         round(percentile_cont(0.5) within group (order by t.latency_ms::double precision))::integer,
         round(percentile_cont(0.95) within group (order by t.latency_ms::double precision))::integer
    from (select v_heute - i as tag from generate_series(0, p_tage - 1) as i) d
    left join __SCHEMA__.turns t on (t.created_at at time zone 'Europe/Berlin')::date = d.tag and t.latency_ms is not null
   group by d.tag
   order by d.tag;
end $$;

create or replace function __SCHEMA__.werkstatt_aktionen(p_tage integer)
returns table (tool text, status text, anzahl bigint)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare
  v_von timestamptz;
begin
  if p_tage is null or p_tage < 1 or p_tage > 30 then
    raise exception 'werkstatt_aktionen: p_tage muss zwischen 1 und 30 liegen' using errcode = '22023';
  end if;
  v_von := ((pg_catalog.now() at time zone 'Europe/Berlin')::date - (p_tage - 1))::timestamp at time zone 'Europe/Berlin';
  return query
  select a.tool, a.status::text, count(*)
    from __SCHEMA__.actions a
   where a.created_at >= v_von
   group by a.tool, a.status
   order by count(*) desc, a.tool, a.status::text
   limit 500;
end $$;

-- Laborstand: ein Wrapper um labor_zaehlen (0018). Das Panel führt labor_zaehlen und labor_loeschen nie selbst aus, die Funktion läuft
-- mit den Rechten des Eigentümers. Liefert je Laborprofil Art, Platz, Freischaltung und die Summe der Zeilen, keine Kennung, keinen Namen.
create or replace function __SCHEMA__.werkstatt_labor_stand()
returns table (art text, platz smallint, aktiv boolean, zeilen bigint)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare
  r record;
begin
  for r in select p.user_id as uid, p.labor_art as a, p.labor_platz as pl, p.labor_aktiv as ak
             from __SCHEMA__.profiles p
            where p.labor_art is not null
            order by p.labor_art, p.labor_platz nulls last loop
    art := r.a;
    platz := r.pl;
    aktiv := r.ak;
    zeilen := (select coalesce(sum(z.value::bigint), 0) from jsonb_each_text(__SCHEMA__.labor_zaehlen(r.uid)) z);
    return next;
  end loop;
end $$;

-- Aufräumen: Freigabekarten, die älter sind als ein Tag (der Nachweis steht in actions).
create or replace function __SCHEMA__.werkstatt_aufraeumen() returns bigint
language plpgsql security definer set search_path = '' as $$
declare
  n bigint;
begin
  delete from __SCHEMA__.werkstatt_karten k where k.created_at < pg_catalog.now() - interval '1 day';
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------- Rechte (geringste Rechte) ----------
-- Funktionen: neu angelegte sind für PUBLIC ausführbar, das wird zuerst entzogen. Triggerfunktionen führt niemand aus.
revoke all on function __SCHEMA__.labor_karten_pflege() from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.labor_karten_versionen_schutz()
  from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_karten_schutz() from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_sitzungen(integer) from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_latenz(integer) from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_aktionen(integer) from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_labor_stand() from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on function __SCHEMA__.werkstatt_aufraeumen() from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
grant execute on function __SCHEMA__.werkstatt_sitzungen(integer) to wamo_werkstatt;
grant execute on function __SCHEMA__.werkstatt_latenz(integer) to wamo_werkstatt;
grant execute on function __SCHEMA__.werkstatt_aktionen(integer) to wamo_werkstatt;
grant execute on function __SCHEMA__.werkstatt_labor_stand() to wamo_werkstatt;
grant execute on function __SCHEMA__.werkstatt_aufraeumen() to wamo_werkstatt;

-- Tabellen und Ansichten: erst alles entziehen, damit ein Nachlauf nach geänderten Rechten zum selben Stand führt.
revoke all on __SCHEMA__.labor_termine from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_plaetze from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_checkliste from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_karten from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_zuordnung from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_karten_versionen from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.werkstatt_karten from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_karten_aktive_version from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;
revoke all on __SCHEMA__.labor_wissen_aktiv from public, anon, authenticated, service_role, wamo_core, wamo_admin, wamo_werkstatt;

-- Der Kern: nur die zwei Ansichten, nur lesen
grant select on __SCHEMA__.labor_karten_aktive_version to wamo_core;
grant select on __SCHEMA__.labor_wissen_aktiv to wamo_core;

-- Das Panel: Lesen überall, Schreiben nur in den Spalten, die der Dienst braucht. Löschen nur, wo der Ablauf es verlangt.
grant select on __SCHEMA__.labor_termine, __SCHEMA__.labor_plaetze, __SCHEMA__.labor_checkliste, __SCHEMA__.labor_karten,
                __SCHEMA__.labor_zuordnung, __SCHEMA__.labor_karten_versionen, __SCHEMA__.werkstatt_karten to wamo_werkstatt;
grant insert (id, tag, beginn, ende, einwilligung_version, status, aufbewahrung_bis, erstellt_von) on __SCHEMA__.labor_termine to wamo_werkstatt;
grant update (tag, beginn, ende, einwilligung_version, status, aufbewahrung_bis) on __SCHEMA__.labor_termine to wamo_werkstatt;
grant delete on __SCHEMA__.labor_termine to wamo_werkstatt;
grant insert (termin_id, platz, zweck, kennung, gast) on __SCHEMA__.labor_plaetze to wamo_werkstatt;
grant update (zweck, kennung, gast) on __SCHEMA__.labor_plaetze to wamo_werkstatt;
grant delete on __SCHEMA__.labor_plaetze to wamo_werkstatt;
grant insert (termin_id, titel, quelle, faellig) on __SCHEMA__.labor_checkliste to wamo_werkstatt;
grant update (titel, quelle, faellig, erledigt_at, erledigt_von) on __SCHEMA__.labor_checkliste to wamo_werkstatt;
grant insert (id, gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min, stand, geaendert_von)
  on __SCHEMA__.labor_karten to wamo_werkstatt;
grant update (gruppe, titel, aufgabe, erwartung, fehler, lernziel, wissen, wissenstext, werkzeuge, dauer_min, stand, geaendert_von)
  on __SCHEMA__.labor_karten to wamo_werkstatt;
grant delete on __SCHEMA__.labor_karten to wamo_werkstatt;
grant insert (termin_id, platz, karte_id) on __SCHEMA__.labor_zuordnung to wamo_werkstatt;
grant delete on __SCHEMA__.labor_zuordnung to wamo_werkstatt;
grant insert (erstellt_von, anzahl_aenderungen, wissen_zeichen, karten, aktiv) on __SCHEMA__.labor_karten_versionen to wamo_werkstatt;
grant update (aktiv) on __SCHEMA__.labor_karten_versionen to wamo_werkstatt;
grant insert (id, admin, aktion, ziel, gilt_bis) on __SCHEMA__.werkstatt_karten to wamo_werkstatt;
grant update (ausgefuehrt_at) on __SCHEMA__.werkstatt_karten to wamo_werkstatt;

-- Zugang prüfen: genau diese vier Spalten von profiles, kein Schreibrecht (Namen, Einstellungen und Laborfelder außer labor_art bleiben zu)
grant select (user_id, rolle, aktiv, labor_art) on __SCHEMA__.profiles to wamo_werkstatt;
-- Audit: Zeilen mit werkstatt_ als Werkzeug anlegen und lesen (die Policies unten begrenzen das auf diese Zeilen)
grant insert (user_id, tool, params, reason, risk, status, result, decided_at, finished_at) on __SCHEMA__.actions to wamo_werkstatt;
grant select (id, user_id, tool, risk, status, created_at, finished_at) on __SCHEMA__.actions to wamo_werkstatt;

-- ---------- Row Level Security ----------
alter table __SCHEMA__.labor_termine enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_termine;
create policy core_all on __SCHEMA__.labor_termine for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_termine;
create policy werkstatt_all on __SCHEMA__.labor_termine for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.labor_plaetze enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_plaetze;
create policy core_all on __SCHEMA__.labor_plaetze for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_plaetze;
create policy werkstatt_all on __SCHEMA__.labor_plaetze for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.labor_checkliste enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_checkliste;
create policy core_all on __SCHEMA__.labor_checkliste for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_checkliste;
create policy werkstatt_all on __SCHEMA__.labor_checkliste for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.labor_karten enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_karten;
create policy core_all on __SCHEMA__.labor_karten for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_karten;
create policy werkstatt_all on __SCHEMA__.labor_karten for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.labor_zuordnung enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_zuordnung;
create policy core_all on __SCHEMA__.labor_zuordnung for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_zuordnung;
create policy werkstatt_all on __SCHEMA__.labor_zuordnung for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.labor_karten_versionen enable row level security;
drop policy if exists core_all on __SCHEMA__.labor_karten_versionen;
create policy core_all on __SCHEMA__.labor_karten_versionen for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.labor_karten_versionen;
create policy werkstatt_all on __SCHEMA__.labor_karten_versionen for all to wamo_werkstatt using (true) with check (true);

alter table __SCHEMA__.werkstatt_karten enable row level security;
drop policy if exists core_all on __SCHEMA__.werkstatt_karten;
create policy core_all on __SCHEMA__.werkstatt_karten for all to wamo_core using (false) with check (false);
drop policy if exists werkstatt_all on __SCHEMA__.werkstatt_karten;
create policy werkstatt_all on __SCHEMA__.werkstatt_karten for all to wamo_werkstatt using (true) with check (true);

-- vorhandene Tabellen: je eine Policy für wamo_werkstatt (RLS ist dort seit 0001 an)
drop policy if exists werkstatt_lesen on __SCHEMA__.profiles;
create policy werkstatt_lesen on __SCHEMA__.profiles for select to wamo_werkstatt using (true);
drop policy if exists werkstatt_audit_insert on __SCHEMA__.actions;
create policy werkstatt_audit_insert on __SCHEMA__.actions for insert to wamo_werkstatt with check (tool like 'werkstatt\_%');
drop policy if exists werkstatt_audit_lesen on __SCHEMA__.actions;
create policy werkstatt_audit_lesen on __SCHEMA__.actions for select to wamo_werkstatt using (tool like 'werkstatt\_%');

-- Selbsttest: bricht die Transaktion bei Rechtedrift ab. Jedes Recht einzeln (has_table_privilege mit mehreren Rechten wäre schon bei
-- einem davon wahr).
do $$
declare
  rolle     text;
  tab       text;
  recht     text;
  fn        text;
  spalte    text;
  tabellen  text[] := array['labor_termine', 'labor_plaetze', 'labor_checkliste', 'labor_karten', 'labor_zuordnung',
                            'labor_karten_versionen', 'werkstatt_karten'];
  ansichten text[] := array['labor_karten_aktive_version', 'labor_wissen_aktiv'];
  lesefn    text[] := array['werkstatt_sitzungen(integer)', 'werkstatt_latenz(integer)', 'werkstatt_aktionen(integer)',
                            'werkstatt_labor_stand()', 'werkstatt_aufraeumen()'];
  triggerfn text[] := array['labor_karten_pflege()', 'labor_karten_versionen_schutz()', 'werkstatt_karten_schutz()'];
  fremde    text[] := array['anon', 'authenticated', 'service_role', 'wamo_admin'];
  loeschen  text[] := array['labor_termine', 'labor_plaetze', 'labor_karten', 'labor_zuordnung'];
begin
  -- 1. die Rolle: Gruppe ohne Anmeldung und ohne Sonderrechte
  if not exists (select 1 from pg_roles where rolname = 'wamo_werkstatt' and not rolcanlogin and not rolsuper and not rolbypassrls
                    and not rolcreaterole and not rolcreatedb) then
    raise exception 'werkstatt (0031): wamo_werkstatt fehlt oder hat zu viele Rechte (Anmeldung, Superuser, bypassrls)' using errcode = '42501';
  end if;
  -- 2. Tabellen und Ansichten: Fremde und PUBLIC haben nichts
  foreach tab in array tabellen || ansichten loop
    foreach rolle in array fremde loop
      if has_any_column_privilege(rolle, '__SCHEMA__.' || tab, 'SELECT,INSERT,UPDATE,REFERENCES')
         or has_table_privilege(rolle, '__SCHEMA__.' || tab, 'DELETE')
         or has_table_privilege(rolle, '__SCHEMA__.' || tab, 'TRUNCATE')
         or has_table_privilege(rolle, '__SCHEMA__.' || tab, 'TRIGGER') then
        raise exception 'werkstatt (0031): % darf keine Rechte auf % haben', rolle, tab using errcode = '42501';
      end if;
    end loop;
    if exists (select 1 from pg_class c, aclexplode(c.relacl) x where c.oid = ('__SCHEMA__.' || tab)::regclass and x.grantee = 0)
       or exists (select 1 from pg_attribute a, aclexplode(a.attacl) x where a.attrelid = ('__SCHEMA__.' || tab)::regclass and x.grantee = 0) then
      raise exception 'werkstatt (0031): PUBLIC hat Rechte auf %', tab using errcode = '42501';
    end if;
  end loop;
  -- 3. der Kern: auf die Tabellen nichts, auf die Ansichten genau select
  foreach tab in array tabellen loop
    if has_any_column_privilege('wamo_core', '__SCHEMA__.' || tab, 'SELECT,INSERT,UPDATE,REFERENCES')
       or has_table_privilege('wamo_core', '__SCHEMA__.' || tab, 'DELETE')
       or has_table_privilege('wamo_core', '__SCHEMA__.' || tab, 'TRUNCATE')
       or has_table_privilege('wamo_core', '__SCHEMA__.' || tab, 'TRIGGER') then
      raise exception 'werkstatt (0031): wamo_core darf % nicht lesen oder schreiben', tab using errcode = '42501';
    end if;
  end loop;
  foreach tab in array ansichten loop
    if not has_table_privilege('wamo_core', '__SCHEMA__.' || tab, 'SELECT') then
      raise exception 'werkstatt (0031): wamo_core braucht select auf %', tab using errcode = '42501';
    end if;
    foreach recht in array array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
      if has_table_privilege('wamo_core', '__SCHEMA__.' || tab, recht) then
        raise exception 'werkstatt (0031): wamo_core darf % auf % nicht haben', recht, tab using errcode = '42501';
      end if;
    end loop;
    if has_any_column_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, 'SELECT,INSERT,UPDATE,REFERENCES') then
      raise exception 'werkstatt (0031): wamo_werkstatt braucht die Ansicht % nicht', tab using errcode = '42501';
    end if;
  end loop;
  -- 4. das Panel: kein TRUNCATE, TRIGGER, REFERENCES; Löschen nur dort, wo der Ablauf es verlangt
  foreach tab in array tabellen loop
    if not has_table_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, 'SELECT') then
      raise exception 'werkstatt (0031): wamo_werkstatt braucht select auf %', tab using errcode = '42501';
    end if;
    foreach recht in array array['TRUNCATE', 'TRIGGER', 'REFERENCES'] loop
      if has_table_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, recht) then
        raise exception 'werkstatt (0031): wamo_werkstatt darf % auf % nicht haben', recht, tab using errcode = '42501';
      end if;
    end loop;
    if has_table_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, 'INSERT') or has_table_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, 'UPDATE') then
      raise exception 'werkstatt (0031): wamo_werkstatt hat ein Tabellenrecht zum Schreiben auf %, nur Spaltenrechte sind vorgesehen', tab
        using errcode = '42501';
    end if;
    if has_table_privilege('wamo_werkstatt', '__SCHEMA__.' || tab, 'DELETE') <> (tab = any(loeschen)) then
      raise exception 'werkstatt (0031): das Löschrecht von wamo_werkstatt auf % weicht vom Plan ab', tab using errcode = '42501';
    end if;
  end loop;
  -- Spalten, die das Panel nie ändert oder setzt: Schlüssel, Zeitstempel und Stempel der Datenbank
  foreach spalte in array array['labor_termine.id', 'labor_termine.created_at', 'labor_termine.updated_at', 'labor_termine.erstellt_von',
                                'labor_karten.id', 'labor_karten.geaendert_at', 'labor_karten_versionen.version',
                                'labor_karten_versionen.erstellt_at', 'labor_karten_versionen.karten', 'labor_karten_versionen.wissen_zeichen',
                                'labor_karten_versionen.anzahl_aenderungen', 'labor_karten_versionen.erstellt_von',
                                'werkstatt_karten.id', 'werkstatt_karten.admin', 'werkstatt_karten.aktion', 'werkstatt_karten.ziel',
                                'werkstatt_karten.gilt_bis', 'werkstatt_karten.created_at', 'labor_checkliste.id', 'labor_checkliste.termin_id',
                                'labor_plaetze.termin_id', 'labor_plaetze.platz'] loop
    if has_column_privilege('wamo_werkstatt', '__SCHEMA__.' || split_part(spalte, '.', 1), split_part(spalte, '.', 2), 'UPDATE') then
      raise exception 'werkstatt (0031): wamo_werkstatt darf % nicht ändern', spalte using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['labor_termine.created_at', 'labor_termine.updated_at', 'labor_karten.geaendert_at', 'labor_karten_versionen.version',
                                'labor_karten_versionen.erstellt_at', 'werkstatt_karten.created_at', 'werkstatt_karten.ausgefuehrt_at',
                                'labor_checkliste.id'] loop
    if has_column_privilege('wamo_werkstatt', '__SCHEMA__.' || split_part(spalte, '.', 1), split_part(spalte, '.', 2), 'INSERT') then
      raise exception 'werkstatt (0031): wamo_werkstatt darf % nicht selbst setzen', spalte using errcode = '42501';
    end if;
  end loop;
  -- 5. Funktionen: security definer, leerer search_path, ausführbar nur für den Eigentümer und (die Lesefunktionen) wamo_werkstatt
  foreach fn in array lesefn || triggerfn loop
    if not exists (select 1 from pg_proc p where p.oid = ('__SCHEMA__.' || fn)::regprocedure
                      and (p.prosecdef or fn = any(triggerfn)) and p.proconfig @> array['search_path=""']) then
      raise exception 'werkstatt (0031): % hat nicht die vorgesehene Form (security definer, search_path leer)', fn using errcode = '42501';
    end if;
    if exists (select 1 from pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                where p.oid = ('__SCHEMA__.' || fn)::regprocedure and a.privilege_type = 'EXECUTE' and a.grantee <> p.proowner
                  and (fn = any(triggerfn) or a.grantee is distinct from (select r.oid from pg_roles r where r.rolname = 'wamo_werkstatt'))) then
      raise exception 'werkstatt (0031): % ist für eine fremde Rolle ausführbar', fn using errcode = '42501';
    end if;
    if (fn = any(lesefn)) and not has_function_privilege('wamo_werkstatt', ('__SCHEMA__.' || fn)::regprocedure, 'EXECUTE') then
      raise exception 'werkstatt (0031): wamo_werkstatt braucht execute auf %', fn using errcode = '42501';
    end if;
  end loop;
  -- 6. nie die Laborfunktionen von 0018 und kein Schreibrecht auf profiles (sonst bricht der Selbsttest von 0018, mit Recht)
  if has_function_privilege('wamo_werkstatt', '__SCHEMA__.labor_loeschen(uuid, timestamptz, timestamptz)', 'EXECUTE')
     or has_function_privilege('wamo_werkstatt', '__SCHEMA__.labor_zaehlen(uuid)', 'EXECUTE') then
    raise exception 'werkstatt (0031): wamo_werkstatt darf labor_loeschen oder labor_zaehlen nicht ausführen' using errcode = '42501';
  end if;
  if has_any_column_privilege('wamo_werkstatt', '__SCHEMA__.profiles', 'INSERT,UPDATE,REFERENCES')
     or has_table_privilege('wamo_werkstatt', '__SCHEMA__.profiles', 'DELETE')
     or has_table_privilege('wamo_werkstatt', '__SCHEMA__.profiles', 'TRUNCATE')
     or has_table_privilege('wamo_werkstatt', '__SCHEMA__.profiles', 'TRIGGER') then
    raise exception 'werkstatt (0031): wamo_werkstatt darf profiles nicht schreiben' using errcode = '42501';
  end if;
  foreach spalte in array array['user_id', 'rolle', 'aktiv', 'labor_art'] loop
    if not has_column_privilege('wamo_werkstatt', '__SCHEMA__.profiles', spalte, 'SELECT') then
      raise exception 'werkstatt (0031): wamo_werkstatt braucht select auf profiles.%', spalte using errcode = '42501';
    end if;
  end loop;
  foreach spalte in array array['display_name', 'settings', 'voice_id', 'labor_platz', 'labor_aktiv', 'anrede'] loop
    if has_column_privilege('wamo_werkstatt', '__SCHEMA__.profiles', spalte, 'SELECT') then
      raise exception 'werkstatt (0031): wamo_werkstatt darf profiles.% nicht lesen', spalte using errcode = '42501';
    end if;
  end loop;
  -- 7. actions: nur anlegen und lesen, nie ändern oder löschen
  if has_table_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'DELETE') or has_table_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'TRUNCATE')
     or has_any_column_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'UPDATE')
     or has_column_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'params', 'SELECT')
     or has_column_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'result', 'SELECT')
     or not has_column_privilege('wamo_werkstatt', '__SCHEMA__.actions', 'tool', 'INSERT') then
    raise exception 'werkstatt (0031): wamo_werkstatt hat falsche Rechte auf actions' using errcode = '42501';
  end if;
  -- 8. RLS an, je neue Tabelle genau zwei Policies, core_all verbietet alles
  foreach tab in array tabellen loop
    if not (select c.relrowsecurity from pg_class c where c.oid = ('__SCHEMA__.' || tab)::regclass)
       or (select count(*) from pg_policies where schemaname = '__SCHEMA__' and tablename = tab) <> 2
       or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = tab and policyname = 'core_all'
                         and qual = 'false' and with_check = 'false')
       or not exists (select 1 from pg_policies where schemaname = '__SCHEMA__' and tablename = tab and policyname = 'werkstatt_all') then
      raise exception 'werkstatt (0031): RLS oder Policies von % stimmen nicht', tab using errcode = '42501';
    end if;
  end loop;
  foreach tab in array array['profiles', 'actions'] loop
    if not (select c.relrowsecurity from pg_class c where c.oid = ('__SCHEMA__.' || tab)::regclass) then
      raise exception 'werkstatt (0031): RLS auf % ist aus', tab using errcode = '42501';
    end if;
  end loop;
  if (select count(*) from pg_policies where schemaname = '__SCHEMA__' and policyname in
        ('werkstatt_lesen', 'werkstatt_audit_insert', 'werkstatt_audit_lesen')) <> 3 then
    raise exception 'werkstatt (0031): Policies auf profiles oder actions fehlen' using errcode = '42501';
  end if;
  -- 9. Trigger und die Form der Ansichten
  if (select count(*) from pg_trigger where not tgisinternal and tgenabled = 'O' and tgname in
        ('labor_termine_touch', 'labor_karten_pflege', 'labor_karten_versionen_schutz', 'werkstatt_karten_schutz')
        and tgrelid in ('__SCHEMA__.labor_termine'::regclass, '__SCHEMA__.labor_karten'::regclass,
                        '__SCHEMA__.labor_karten_versionen'::regclass, '__SCHEMA__.werkstatt_karten'::regclass)) <> 4 then
    raise exception 'werkstatt (0031): ein Trigger fehlt' using errcode = '42501';
  end if;
  foreach tab in array ansichten loop
    if not exists (select 1 from pg_class c where c.oid = ('__SCHEMA__.' || tab)::regclass and c.relkind = 'v'
                      and c.reloptions @> array['security_barrier=true']) then
      raise exception 'werkstatt (0031): die Ansicht % fehlt oder ist nicht security_barrier', tab using errcode = '42501';
    end if;
  end loop;
  if not exists (select 1 from pg_indexes where schemaname = '__SCHEMA__' and tablename = 'labor_karten_versionen'
                    and indexname = 'labor_karten_versionen_aktiv_uni' and indexdef like '%UNIQUE%WHERE aktiv%') then
    raise exception 'werkstatt (0031): der Index für die eine aktive Version fehlt' using errcode = '42501';
  end if;
  -- Die Anmelde-Rolle der Infrastruktur erbt die Gruppe (INHERIT); fehlt sie, gibt es nichts zu prüfen
  if exists (select 1 from pg_roles where rolname = 'wamo_werkstatt_login')
     and (not has_function_privilege('wamo_werkstatt_login', '__SCHEMA__.werkstatt_sitzungen(integer)', 'EXECUTE')
          or has_function_privilege('wamo_werkstatt_login', '__SCHEMA__.labor_loeschen(uuid, timestamptz, timestamptz)', 'EXECUTE')) then
    raise exception 'werkstatt (0031): wamo_werkstatt_login erbt die Rechte der Gruppe nicht oder hat zu viele' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0031_werkstatt') on conflict do nothing;
