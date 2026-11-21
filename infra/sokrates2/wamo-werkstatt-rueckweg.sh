#!/usr/bin/env bash
# Rückweg zu wamo-werkstatt-einrichten.sh: W.A.I.S. Werkstatt auf Sokrates-2 abschalten. Nur als root (sudo), wie die übrigen Rückwege. Wiederholbar.
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-werkstatt-rueckweg.sh --trocken"     # zeigt nur an, was geschehen würde
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-werkstatt-rueckweg.sh"               # Dienst, Brücke und Sammler aus, Caddy-Site weg; alle Dateien bleiben
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-werkstatt-rueckweg.sh --entfernen"   # entfernt zusätzlich Programme, venv, Konfiguration, Units, Daten des Sammlers
#
# Was geschieht ohne --entfernen:
#   1. Zeitgeber, Sammler, Brücke, Dienst und Ausgangsregel stoppen und deaktivieren (die nft-Tabelle wamo_werkstatt_ausgang verschwindet mit ihrer Unit)
#   2. Caddy-Site wamo-werkstatt.caddy entfernen und Caddy neu laden (55443 bis 55447 bleiben unberührt); danach müssen sie wieder antworten (Zeitgrenze, Meldung, Ausgang
#      ungleich 0), die Dauer wird genannt. Das geschieht unter derselben Sperre wie der Lauf des Aktualisierers der Betreuer-Geräte.
# Was immer bleibt (es schadet ohne Dienst nicht): Port 55448 und der Ordner /run/wamo-werkstatt im Compose von wamo-caddy (ohne Site lauscht Caddy auf 55448 nicht; würde der
# Ordner fehlen, könnte wamo-caddy nach einem Neustart nicht starten, darum bleibt er samt tmpfiles-Eintrag), die Regel für 55448 in der Firewall, der Benutzer
# wamo-werkstatt, die Sicherungen unter /var/backups/wamo-werkstatt und die Datenbankrolle (Sperren: python scripts/wamo_dienst_db.py sperren werkstatt).
# Mit --entfernen fallen zusätzlich weg: /opt/wamo-werkstatt (Programme und venv), /etc/wamo-werkstatt (werkstatt.env, admins, db.zugang, CA-Kopie),
# /etc/wamo-werkstatt-ausgang, die Units und /var/lib/wamo-werkstatt (verdichtete Kennzahlen und Protokollzeilen, nur abgeleitete Daten). Die Tabellen der Werkstatt in
# der Datenbank (Termine, Karten, Versionen) bleiben: Sie gehören der Migration 0031 und ihrem .down.sql.
#
# Probelauf ohne root (nur für Tests): WAMO_WERKSTATT_WURZEL=/pfad/zu/einem/wegwerf/ordner (siehe wamo-werkstatt-einrichten.sh).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
W="${WAMO_WERKSTATT_WURZEL:-}"
BASIS="$W/opt/wamo-werkstatt"
ETC="$W/etc/wamo-werkstatt"
AUSGANG_DIR="$W/etc/wamo-werkstatt-ausgang"
UNITS="$W/etc/systemd/system"
DATEN="$W/var/lib/wamo-werkstatt"
RUN="$W/run/wamo-werkstatt"
CADDY_DIR="${WAMO_WERKSTATT_CADDY_DIR:-$W/home/wamocon/wamo-tls/caddy}"
SITE_DATEI="$CADDY_DIR/etc/kern/wamo-werkstatt.caddy"
SPERRE="$W/run/wamo-labor-geraete/lock"   # die gemeinsame Sperre mit dem Aktualisierer der Betreuer-Geräte (wamo-labor-geraete-aktualisieren.sh)
UNIT_NAMEN=(wamo-werkstatt-sammler.timer wamo-werkstatt-sammler.service wamo-werkstatt-bruecke.socket wamo-werkstatt-bruecke.service wamo-werkstatt.service wamo-werkstatt-ausgang.service)
START=""
TROCKEN=nein
ENTFERNEN=nein

usage() {
  echo "Aufruf: $0 [--trocken] [--entfernen]" >&2
  exit 2
}
fehler() { echo "$*" >&2; exit 1; }
# Jede Änderung läuft über tu: im Trockenlauf wird sie nur angezeigt
tu() {
  if [ "$TROCKEN" = ja ]; then printf '  [trocken] %s\n' "$*"; else "$@"; fi
}

# Schutz gegen untergeschobene Dateien (wie in den übrigen Einrichtungsskripten): alles gehört root oder dem aufrufenden Benutzer, nichts ist
# für die Gruppe oder alle beschreibbar, keine symbolischen Links
pruefe_ordner() {
  local ordner="$1" erlaubt uid modus pfad
  erlaubt=" 0 $(id -u) ${SUDO_UID:-} "
  while read -r uid modus pfad; do
    if [[ "$erlaubt" != *" $uid "* ]] || (( 8#$modus & 8#022 )); then
      echo "Unsicherer Ablageort: $pfad (Besitzer $uid, Rechte $modus). Ordner im eigenen Home ablegen und" \
        "mit chmod -R go-w schützen." >&2
      exit 1
    fi
  done < <(stat -c '%u %a %n' "$(dirname "$ordner")"; find "$ordner" \( -type l -printf '%U 777 %p\n' \) -o -printf '%U %m %p\n')
}

# Antwortet eine Adresse mit irgendeinem HTTP-Status (nur 000 heißt keine Antwort)? Je Adresse höchstens WARTE_RUNDEN mal WARTE_SEKUNDEN.
antwortet() {
  local url="$1" code runde runden="${WAMO_WERKSTATT_WARTE_RUNDEN:-60}" sek="${WAMO_WERKSTATT_WARTE_SEKUNDEN:-2}"
  [[ "$runden" =~ ^[0-9]+$ ]] || runden=60
  [[ "$sek" =~ ^[0-9]+$ ]] || sek=2
  for ((runde = 0; runde < runden; runde++)); do
    code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$url" || true)"
    [ "$code" != 000 ] && return 0
    sleep "$sek"
  done
  return 1
}

# Löschen nur für die festen Ordner der Werkstatt (nie ein leerer Pfad, nie die Wurzel, nie ein Link)
loesche_ordner() {
  case "$1" in
    "$BASIS"|"$ETC"|"$AUSGANG_DIR"|"$DATEN") ;;
    *) fehler "Unerwarteter Pfad zum Löschen: $1" ;;
  esac
  if [ -z "$1" ] || [ "$1" = / ] || [ -L "$1" ]; then fehler "Pfad nicht erlaubt: $1"; fi
  tu rm -rf -- "$1"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --trocken) TROCKEN=ja ;;
    --entfernen) ENTFERNEN=ja ;;
    *) usage ;;
  esac
  shift
done

if [ -n "$W" ]; then
  [[ "$W" =~ ^/[A-Za-z0-9/_.:~-]+$ ]] || fehler "WAMO_WERKSTATT_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9 und / _ . : ~ - sein."
  [ "$(id -u)" -ne 0 ] || fehler "Der Probelauf (WAMO_WERKSTATT_WURZEL) läuft nicht als root."
  echo "Probelauf unter $W (kein root, kein systemd)"
  [ "${WAMO_WERKSTATT_HERKUNFT:-}" != ja ] || pruefe_ordner "$HERE"   # nur für Tests: der Herkunftsschutz auch im Probelauf
elif [ "$TROCKEN" = nein ]; then
  [ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
  pruefe_ordner "$HERE"
fi
[ "$TROCKEN" = nein ] || echo "Trockenlauf: nichts wird geändert."

dienst_aus() {
  echo "== 1. Zeitgeber, Sammler, Brücke, Dienst und Ausgangsregel aus"
  if [ -n "$W" ]; then echo "  (Probelauf: kein systemd)"; return 0; fi
  local u
  for u in "${UNIT_NAMEN[@]}"; do
    tu systemctl disable --now "$u" || true
  done
  echo "  wamo-werkstatt: $(systemctl is-active wamo-werkstatt.service 2>/dev/null || true)"
  tu rm -f -- "$RUN/werkstatt.sock"
}

site_entfernen() {
  echo "== 2. Caddy-Site"
  if [ ! -f "$SITE_DATEI" ]; then echo "  keine Site vorhanden"; return 0; fi
  tu rm -f -- "$SITE_DATEI"
  if [ -n "$W" ]; then echo "  (Probelauf: Site-Datei entfernt, kein docker)"; return 0; fi
  if [ "$TROCKEN" = ja ] || [ -n "$(docker ps -q -f name=^wamo-caddy$ 2>/dev/null || true)" ]; then
    # Schlägt der Reload fehl, geht der Rückweg trotzdem weiter (die Site ist weg, Caddy übernimmt das beim nächsten Laden)
    if tu docker exec wamo-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
      echo "  Site entfernt, Caddy neu geladen"
    else
      echo "  WARNUNG: caddy reload fehlgeschlagen, die Site-Datei ist entfernt" >&2
    fi
  fi
}

# Nach jedem Rückweg müssen die Ports von wamo-caddy wieder antworten: Der Reload von Caddy hat sie berührt, und die Site ist weg
caddy_pruefen() {
  echo "== 3. Prüfung: 55443 bis 55446 (und 55447, wenn der Labor-Dienst eine Site hat) antworten"
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] curl gegen https://192.168.178.136:55443 bis 55446"; return 0; fi
  if [ -n "$W" ]; then echo "  (Probelauf: keine Prüfung)"; return 0; fi
  local p fehlt="" ports="55443 55444 55445 55446"
  [ ! -f "$CADDY_DIR/etc/kern/wamo-labor.caddy" ] || ports="$ports 55447"
  for p in $ports; do antwortet "https://192.168.178.136:$p/" || fehlt="$fehlt $p"; done
  [ -z "$fehlt" ] || fehler "FEHLER: Von wamo-caddy antworten die Ports$fehlt nicht, bitte sofort ansehen (docker logs wamo-caddy)."
  echo "  Ausfalldauer: $(( $(date +%s) - START )) Sekunden (Zeit zwischen Reload und erster Antwort aller Ports; am Server zu messen)"
}

entfernen() {
  echo "== 4. Programme, venv, Konfiguration, Units und Daten entfernen"
  loesche_ordner "$BASIS"
  loesche_ordner "$ETC"
  loesche_ordner "$AUSGANG_DIR"
  loesche_ordner "$DATEN"
  local u
  for u in "${UNIT_NAMEN[@]}"; do tu rm -f -- "$UNITS/$u"; done
  if [ -z "$W" ]; then tu systemctl daemon-reload; fi
  echo "  entfernt (der Benutzer, /run/wamo-werkstatt, die Firewall-Regel und die Datenbank bleiben)"
}

# Der Rückweg ändert die Site und lädt Caddy: Das geschieht unter derselben Sperre wie der Lauf des Aktualisierers (im Trockenlauf und im Probelauf keine Sperre)
if [ "$TROCKEN" = nein ] && [ -z "$W" ]; then
  mkdir -p "$(dirname "$SPERRE")"
  exec 9> "$SPERRE"
  flock -w 60 9 || fehler "Ein Lauf des Aktualisierers der Betreuer-Geräte hält die Sperre $SPERRE: Es wurde nichts geändert, bitte in einer Minute wiederholen."
fi
START="$(date +%s)"
dienst_aus
site_entfernen
caddy_pruefen
if [ "$ENTFERNEN" = ja ]; then
  entfernen
  echo "Fertig. Die Werkstatt ist entfernt. Datenbankrolle sperren: python scripts/wamo_dienst_db.py sperren werkstatt. Neu einrichten: sudo bash wamo-werkstatt-einrichten.sh"
else
  echo "Fertig. Programme, Konfiguration und Daten bleiben (--entfernen löscht sie). Neu einrichten: sudo bash wamo-werkstatt-einrichten.sh"
fi
