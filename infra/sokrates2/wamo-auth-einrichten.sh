#!/usr/bin/env bash
# Erstanmeldung je Konto (Schema wamo_auth) im WAMO-Supabase einrichten, prüfen und zurücknehmen.
# Planpapier docs/ausrollen-neue-nutzer.md, Abschnitt 4.1 und 9 (Paket P1a).
#
# Ausführen auf Sokrates-2 als wamocon (Mitglied der docker-Gruppe, kein sudo nötig), aus ~/wamo-infra:
#   bash wamo-auth-einrichten.sh einrichten --trocken   # alles anwenden, Test laufen lassen, zurückrollen
#   bash wamo-auth-einrichten.sh einrichten             # anwenden (eine Transaktion, wiederholbar)
#   bash wamo-auth-einrichten.sh test                   # SQL-Test (rollt immer zurück), letzte Zeile "wamo_auth OK"
#   bash wamo-auth-einrichten.sh status                 # Schema, Trigger, Rechte, Anzahl je Stand (ohne Namen und Kennungen)
#   bash wamo-auth-einrichten.sh rueckweg [--trocken]   # Trigger weg, Rechte entzogen, Tabelle der Merker bleibt
#
# Reihenfolge beim Ausrollen (Abschnitt 9): erst dieses Skript, dann Migration 0021 je Schema, dann die GoTrue-Ergänzung (Mindestlänge
# 12, supabase-wamo-einrichten.sh mit NUR_SITZUNGSGRENZEN=1), danach der Kern. Rückweg umgekehrt: Kern zuerst zurück, dann dieses Skript.
# Ändert nur das eigene Schema wamo_auth und genau einen Trigger auf auth.users; startet keinen Dienst neu.
#
# Umgebung für Proben auf einem Wegwerf-Stack: WAMO_AUTH_DB_CONTAINER (Standard wamo-supabase-db), WAMO_AUTH_SQL_DIR (Standard
# supabase-wamo neben diesem Skript).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_DIR="${WAMO_AUTH_SQL_DIR:-$HERE/supabase-wamo}"
DB="${WAMO_AUTH_DB_CONTAINER:-wamo-supabase-db}"
AUF="$SQL_DIR/wamo_auth.sql"
AB="$SQL_DIR/wamo_auth.down.sql"
TEST="$SQL_DIR/wamo_auth_test.sql"

fehler() { echo "FEHLER: $*" >&2; exit 1; }
nutzung() { sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

psql_db() { docker exec -i "$DB" psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }
spur() { command -v logger >/dev/null 2>&1 && logger -t wamo-auth "$*" || true; }

vorab() {
  for f in "$AUF" "$AB" "$TEST"; do
    [ -f "$f" ] || fehler "$f fehlt (~/wamo-infra neu kopieren)"
  done
  [ "$(docker inspect --format '{{.State.Running}}' "$DB" 2>/dev/null || true)" = true ] || fehler "Container $DB läuft nicht"
}

# SQL-Datei in einer Transaktion anwenden und zurückrollen (Trockenlauf)
trocken_anwenden() {
  { echo 'begin;'; echo 'set local client_min_messages = warning;'; cat "$1"; echo 'rollback;'; } | psql_db -tA >/dev/null
}

# SQL-Datei in einer Transaktion anwenden (ohne die Hinweise "already exists, skipping")
anwenden() {
  { echo 'set client_min_messages = warning;'; cat "$1"; } | psql_db --single-transaction -tA >/dev/null
}

status() {
  psql_db -tA <<'SQL'
select 'Schema wamo_auth: ' || case when to_regnamespace('wamo_auth') is null then 'fehlt' else 'da' end;
select 'Trigger auf auth.users: ' || coalesce((select case tgenabled when 'O' then 'aktiv' else 'abgeschaltet' end from pg_trigger
         where tgname = 'wamo_auth_passwort_geaendert' and tgrelid = 'auth.users'::regclass), 'fehlt');
select 'wamo_core darf Stand lesen: ' || case when to_regprocedure('wamo_auth.erstanmeldung_stand(uuid)') is null then 'Funktion fehlt'
         when has_function_privilege('wamo_core', 'wamo_auth.erstanmeldung_stand(uuid)', 'execute') then 'ja' else 'nein' end;
SQL
  if [ "$(echo "select to_regprocedure('wamo_auth.erstanmeldung_uebersicht()') is not null;" | psql_db -tA)" = t ]; then
    psql_db -tA <<'SQL'
select 'Merker je Stand: ' || coalesce((select string_agg(stand || ' ' || n, ', ' order by stand)
         from (select stand, count(*) as n from wamo_auth.erstanmeldung_uebersicht() group by 1) x), 'keine');
SQL
  fi
}

test_lauf() {
  local aus
  aus="$(psql_db -tA < "$TEST" 2>&1)" || { echo "$aus" | tail -5 >&2; fehler "SQL-Test gescheitert"; }
  echo "$aus" | grep -qx 'wamo_auth OK' || { echo "$aus" | tail -5 >&2; fehler "SQL-Test ohne Erfolgszeile"; }
  echo "$aus" | grep -i 'notice' | sed 's/^/  /' || true
  echo "  SQL-Test: wamo_auth OK"
}

befehl="${1:-}"; shift || true
trocken=0
for a in "$@"; do
  case "$a" in
    --trocken) trocken=1 ;;
    *) fehler "unbekannte Option $a" ;;
  esac
done

case "$befehl" in
  einrichten)
    vorab
    if [ "$trocken" = 1 ]; then
      echo "== Trockenlauf: wamo_auth.sql zweimal anwenden und den Test laufen lassen, alles in einer Transaktion, danach zurückrollen"
      { echo 'begin;'; echo 'set local client_min_messages = warning;'; cat "$AUF"; cat "$AUF"; sed -e '/^begin;$/d' -e '/^rollback;$/d' -e '/^\\set /d' "$TEST"; echo 'rollback;'; } \
        | psql_db -tA | grep -x 'wamo_auth OK' >/dev/null || fehler "Trockenlauf gescheitert"
      echo "  Trockenlauf in Ordnung, nichts verändert"
      exit 0
    fi
    echo "== wamo_auth anwenden (eine Transaktion)"
    anwenden "$AUF"
    spur "einrichten: wamo_auth angewendet"
    test_lauf
    status
    ;;
  test)
    vorab
    test_lauf
    ;;
  status)
    vorab
    status
    ;;
  rueckweg)
    vorab
    if [ "$trocken" = 1 ]; then
      trocken_anwenden "$AB"
      echo "  Trockenlauf des Rückwegs in Ordnung, nichts verändert"
      exit 0
    fi
    echo "== Rückweg: Trigger weg, Rechte von wamo_core entzogen (Tabelle der Merker bleibt)"
    anwenden "$AB"
    spur "rueckweg: Trigger entfernt, Rechte entzogen"
    status
    ;;
  ""|-h|--hilfe|hilfe) nutzung ;;
  *) fehler "unbekannter Befehl $befehl (einrichten, test, status, rueckweg)" ;;
esac
