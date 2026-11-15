-- WAMO 0022: Admin-Übersicht "Neue Mitglieder" (Paket P7, docs/ausrollen-neue-nutzer.md, Abschnitte 6 und 12).
-- __SCHEMA__ wird ersetzt durch wamo_dev | wamo_test | wamo_prod.
-- Anwenden (je Schema, in EINER Transaktion, zweimal hintereinander fehlerfrei):
--   bash scripts/render-migration.sh <schema> supabase/migrations/0022_neue_mitglieder.sql \
--     | docker exec -i wamo-supabase-db psql -U postgres -v ON_ERROR_STOP=1 --single-transaction
-- Rückweg: 0022_neue_mitglieder.down.sql. Hängt von 0001, 0002, 0010, 0011 und 0018 ab. Die Nummer 0021 ist für Paket P1a
-- (profil_freischaltung) vergeben; die Reihenfolge der beiden ist egal, sie berühren sich nicht.
--
-- Wozu: Niko sieht in der Oberfläche, wie weit jedes neue Mitglied mit der Einrichtung ist (Anmeldung, zweiter Faktor,
-- Passwortwechsel, Gerät, Modellzugang, Stimmabdruck), ohne SQL und ohne Zugriff auf auth.users für den Kern.
--
-- Entwurf: genau eine Lesefunktion neue_mitglieder(p_admin) als SECURITY DEFINER (Eigentümer postgres), nur für wamo_core
-- ausführbar. Sie liefert genau die Spalten unten und nichts sonst: keine E-Mail, keine Schlüssel, Token oder deren Enden,
-- keinen Fingerabdruck und keinen Stimmvektor, nur Ja oder Nein und Stände als Text. Laborprofile fehlen immer. Der Aufrufer
-- muss ein aktiver Admin ohne Laborkennung sein (die Datenbank prüft das selbst; Anmeldung und zweiten Faktor prüft der Kern
-- vorher, wie bei geraete_verwaltung_liste aus 0014).
--   passwort_stand   Text aus wamo_auth.erstanmeldung_stand(uuid), sobald Paket P1a das Schema wamo_auth eingerichtet hat;
--                    vorher null. Der Aufruf läuft dynamisch (EXECUTE), damit diese Migration ohne wamo_auth gilt.
--   geraet_stand     bestes Ergebnis der persönlichen Geräte: aktiv, beantragt, gesperrt, widerrufen oder keins.
--   modellzugang     token_und_schluessel, token, schluessel oder haus (nur die Art, nie ein Wert).
--   stimmabdruck     eingelernter Abdruck des Profilinhabers vorhanden.
-- Keine neue Tabelle, keine Schreibrechte, keine Rechte für anon, authenticated und service_role.
set local lock_timeout = '5s';

do $$ begin
  if not exists (select 1 from __SCHEMA__.schema_migrations where version = '0018_labor_profile')
     or not exists (select 1 from __SCHEMA__.schema_migrations where version = '0011_modellmodus_und_codetoken') then
    raise exception '0022 braucht 0011 und 0018';
  end if;
end $$;

create or replace function __SCHEMA__.neue_mitglieder(p_admin uuid)
returns table (user_id uuid, anzeigename text, rolle text, aktiv boolean, angelegt timestamptz, letzte_anmeldung timestamptz,
               faktor_bestaetigt boolean, passwort_stand text, geraet_stand text, modellzugang text, stimmabdruck boolean)
language plpgsql stable security definer set search_path = '' as $$
declare
  v_stand boolean := to_regprocedure('wamo_auth.erstanmeldung_stand(uuid)') is not null;
begin
  if p_admin is null or not exists (select 1 from __SCHEMA__.profiles p
                                    where p.user_id = p_admin and p.aktiv and p.rolle = 'admin' and p.labor_art is null) then
    raise exception 'neue_mitglieder: nur für einen aktiven Admin' using errcode = '42501';
  end if;
  for user_id, anzeigename, rolle, aktiv, angelegt, letzte_anmeldung, faktor_bestaetigt, geraet_stand, modellzugang, stimmabdruck in
    select p.user_id, p.display_name, p.rolle::text, p.aktiv, p.created_at, u.last_sign_in_at,
           exists (select 1 from auth.mfa_factors f
                    where f.user_id = p.user_id and f.factor_type::text = 'totp' and f.status::text = 'verified'),
           coalesce((select d.status::text from __SCHEMA__.devices d
                      where d.user_id = p.user_id and d.art = 'persoenlich'
                      order by case d.status::text when 'aktiv' then 1 when 'beantragt' then 2 when 'gesperrt' then 3 else 4 end
                      limit 1), 'keins'),
           case
             when m.claude_code_token is not null and m.claude_schluessel is not null then 'token_und_schluessel'
             when m.claude_code_token is not null then 'token'
             when m.claude_schluessel is not null then 'schluessel'
             else 'haus'
           end,
           exists (select 1 from __SCHEMA__.speakers s where s.user_id = p.user_id and s.is_owner and s.voiceprint is not null)
      from __SCHEMA__.profiles p
      join auth.users u on u.id = p.user_id
      left join __SCHEMA__.model_access m on m.user_id = p.user_id
     where p.labor_art is null
     order by p.created_at desc
     limit 200
  loop
    passwort_stand := null;
    if v_stand then
      execute 'select wamo_auth.erstanmeldung_stand($1)::text' into passwort_stand using user_id;
    end if;
    return next;
  end loop;
end $$;
comment on function __SCHEMA__.neue_mitglieder(uuid) is
  'Admin-Übersicht neuer Mitglieder (P7): nur Stände, nie E-Mail, Schlüssel, Token oder Stimmvektor; ohne Laborprofile.';

revoke all on function __SCHEMA__.neue_mitglieder(uuid) from public, anon, authenticated, service_role;
grant execute on function __SCHEMA__.neue_mitglieder(uuid) to wamo_core;

-- Abschlussprüfung: Funktion ist SECURITY DEFINER mit leerem search_path und nur für wamo_core ausführbar
do $$ begin
  if not (select p.prosecdef from pg_proc p where p.oid = '__SCHEMA__.neue_mitglieder(uuid)'::regprocedure)
     or not exists (select 1 from pg_proc p where p.oid = '__SCHEMA__.neue_mitglieder(uuid)'::regprocedure
                      and p.proconfig @> array['search_path=""'])
     or has_function_privilege('anon', '__SCHEMA__.neue_mitglieder(uuid)', 'EXECUTE')
     or has_function_privilege('authenticated', '__SCHEMA__.neue_mitglieder(uuid)', 'EXECUTE')
     or has_function_privilege('service_role', '__SCHEMA__.neue_mitglieder(uuid)', 'EXECUTE')
     or not has_function_privilege('wamo_core', '__SCHEMA__.neue_mitglieder(uuid)', 'EXECUTE')
  then
    raise exception 'neue_mitglieder: unzulässige Rechte oder Form' using errcode = '42501';
  end if;
end $$;

insert into __SCHEMA__.schema_migrations (version) values ('0022_neue_mitglieder') on conflict do nothing;
