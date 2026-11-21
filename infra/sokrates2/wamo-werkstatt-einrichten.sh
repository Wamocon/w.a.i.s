#!/usr/bin/env bash
# W.A.I.S. Werkstatt (Admin-Panel) auf Sokrates-2 einrichten oder aktualisieren: Dienst wamo-werkstatt (FastAPI, 127.0.0.1:18095), Brücke zu Caddy über einen
# Unix-Socket, Caddy-Site auf HTTPS 55448, Port 55448 in den Admin-Quellen der Firewall, Sammler für Betriebsstand und Protokolle (jede Minute).
# Nur als root (sudo), wie die übrigen Einrichtungsskripte. Wiederholbar (idempotent). Beschreibung, Grenzen und Rückweg: infra/sokrates2/README.md, Abschnitt 23.
#
# Voraussetzungen (der Hauptagent oder Niko erledigt sie vorher):
#   1. Die Migration 0031_werkstatt ist im Schema angewendet (das Skript prüft die Funktion werkstatt_labor_stand).
#   2. Die Login-Rolle und die Zugangsdatei bestehen:  python scripts/wamo_dienst_db.py einrichten werkstatt   (legt /etc/wamo-werkstatt/db.zugang und wamo-ca.crt an;
#      das Passwort erscheint nirgends). Dieses Skript setzt danach Besitzer und Rechte (root:wamo-werkstatt 0440), es liest die Datei nie.
#   3. Der Code des Dienstes (Ordner werkstatt/ aus dem Repo) liegt am Server.
#
# Ablage: Der Ordner liegt im Home von wamocon, nie in /tmp. Vom PC aus (Repo-Wurzel):
#   ssh sokrates2 "rm -rf ~/wamo-infra ~/wamo-werkstatt-quelle" && scp -r infra/sokrates2 sokrates2:wamo-infra && scp -r werkstatt sokrates2:wamo-werkstatt-quelle
#   ssh sokrates2 "chmod -R go-w ~/wamo-infra ~/wamo-werkstatt-quelle"
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-werkstatt-einrichten.sh einrichten --trocken"
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-werkstatt-einrichten.sh einrichten"
#
#   bash wamo-werkstatt-einrichten.sh [einrichten|status|pruefen] [--trocken] [--quelle ORDNER] [--schema wamo_dev|wamo_test|wamo_prod] [--lan-offen]
#
#   einrichten  (Standard) in dieser Reihenfolge: Vorprüfung, Sicherung, Benutzer, Ordner und Konfiguration, Programme, venv, Firewall, Dienst, Caddy, Sammler, Prüfung
#   status      zeigt Namen und Zustände (Units, Dateien, Rechte, Schema, Firewall-Regel), nie Werte
#   pruefen     Rauchtest gegen den Betrieb (wamo_werkstatt_rauchtest.py --produktiv)
#   --trocken   Lesen und Prüfen wie sonst, aber jede Änderung (Dateien, systemctl, docker, Caddy, Firewall) nur anzeigen
#   --quelle    Ordner mit dem Code des Dienstes (Standard /home/wamocon/wamo-werkstatt-quelle: wamo_werkstatt/ und requirements.txt mit Prüfsummen)
#   --schema    Datenbankschema des Dienstes beim ERSTEN Einrichten (Standard: WAMO_DB_SCHEMA des Kerns, sonst wamo_dev). Danach gilt die Zeile in werkstatt.env.
#   --lan-offen Erlaubt das Einrichten auch ohne Einträge in /etc/wamo/admin-quellen (dann erreicht das ganze Büro-LAN den Port 55448, am Labortag sitzen dort Gäste).
#               Ohne diese Option bricht das Skript in diesem Fall ab.
#
# Was einrichten tut (vor jeder Änderung eine Sicherung unter /var/backups/wamo-werkstatt/<JJJJMMTT-HHMMSS>/ ohne db.zugang und ohne Erlaubnisliste):
#   Benutzer    wamo-werkstatt (System, Shell /usr/sbin/nologin, kein Home, keine weiteren Gruppen)
#   Ordner      /opt/wamo-werkstatt (root, 0755), /etc/wamo-werkstatt (root, 0755), /var/lib/wamo-werkstatt (root:wamo-werkstatt 0750, darin protokolle/ ebenso und zustand/
#               nur root), /run/wamo-werkstatt (2750 root:wamocon per tmpfiles.d, Caddy bindet ihn lesend ein; der Socket darin gehört wamo-werkstatt)
#   Dateien     werkstatt.env (root:root 0644, aus der Vorlage, nur wenn sie fehlt), admins (root:wamo-werkstatt 0640, Vorlage nur mit Kommentaren, nur wenn sie fehlt: ohne Einträge
#               kommt niemand hinein), db.zugang (root:wamo-werkstatt 0440, Inhalt unberührt), wamo-ca.crt (root:root 0644)
#   Programme   /opt/wamo-werkstatt/app (root:root 0755): das Paket wamo_werkstatt, der Sammler, der Rauchtest, die Ausgangsregel und SHA256SUMS (ExecStartPre prüft sie vor jedem
#               Start). Der bisherige Baum liegt bis zur bestandenen Prüfung als app.vorher daneben.
#   venv        /opt/wamo-werkstatt/venv (root:root): Bibliotheken NUR aus werkstatt/requirements.txt (aus pyproject.toml mit uv pip compile --generate-hashes erzeugt), nur Binärpakete,
#               immer mit --require-hashes --no-deps; fehlt die Datei oder eine Prüfsumme, bricht das Skript ab. Der Code kommt über eine .pth-Datei auf den Pfad. Die Import-Probe
#               läuft nicht als root, sondern als wamo-werkstatt.
#   Firewall    wamo-firewall-einrichten.sh (Port 55448 in LAN_PORTS_ADMIN), nur wenn die Regel fehlt
#   Dienst      wamo-werkstatt.service (127.0.0.1:18095), wamo-werkstatt-ausgang.service (nft-Tabelle wamo_werkstatt_ausgang), wamo-werkstatt-bruecke.socket und .service
#   Caddy       Site wamo-werkstatt.caddy, vorher in einem Wegwerf-Container ohne Netz geprüft (caddy adapt), Reload ohne Ausfall. Das Compose von wamo-caddy bekommt Port 55448 und den
#               Ordner /run/wamo-werkstatt: Ändert es sich, wird wamo-caddy EINMAL neu angelegt (55443 bis 55447 sind dann wenige Sekunden weg), und zwar nur ohne laufende Sitzung des Kerns.
#   Sammler     wamo-werkstatt-sammler.service und .timer (jede Minute, root), ein erster Lauf gleich danach
#
# Fehler: Schritte mit Änderung (Caddy, Dienst) werden bei einem Fehler zurückgenommen (alte Site und altes Compose; der Dienst wird gestoppt, wenn er vorher nicht lief).
# Benutzer, Ordner, Dateien, Firewall-Regel und der Code bleiben, sie schaden ohne laufenden Dienst nicht. Rückweg: wamo-werkstatt-rueckweg.sh.
#
# Das Skript legt keine Geheimnisse an und gibt keine aus. Es startet den Kern nie neu. Der Kern, die Oberfläche und der Labor-Dienst bleiben unberührt.
#
# Probelauf ohne root (nur für Tests): WAMO_WERKSTATT_WURZEL=/pfad/zu/einem/wegwerf/ordner stellt allen Pfaden unter /etc, /var, /opt, /run und /usr diesen Ordner voran.
# Dann gibt es weder Benutzer noch chown noch systemd noch pip noch Firewall noch Rauchtest; WAMO_WERKSTATT_CADDY_DIR nennt den Ordner von wamo-caddy (Standard unter der Wurzel).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
W="${WAMO_WERKSTATT_WURZEL:-}"
BASIS="$W/opt/wamo-werkstatt"
APP="$BASIS/app"
VENV="$BASIS/venv"
ETC="$W/etc/wamo-werkstatt"
AUSGANG_DIR="$W/etc/wamo-werkstatt-ausgang"
UNITS="$W/etc/systemd/system"
DATEN="$W/var/lib/wamo-werkstatt"
RUN="$W/run/wamo-werkstatt"
TMPFILES="$W/etc/tmpfiles.d/wamo-werkstatt.conf"
SICHERUNG="$W/var/backups/wamo-werkstatt"
FIREWALL_BIN="$W/usr/local/sbin/wamo-firewall"
CADDY_DIR="${WAMO_WERKSTATT_CADDY_DIR:-$W/home/wamocon/wamo-tls/caddy}"
CA="${WAMO_WERKSTATT_CA:-$W/home/wamocon/wamo-tls/ca/wamo-ca.crt}"
QUELLE="${WAMO_WERKSTATT_QUELLE:-/home/wamocon/wamo-werkstatt-quelle}"
PYTHON="${WAMO_WERKSTATT_PYTHON:-/usr/bin/python3}"
SITE_DATEI="$CADDY_DIR/etc/kern/wamo-werkstatt.caddy"
CADDY_COMPOSE="$CADDY_DIR/docker-compose.yml"
BENUTZER=wamo-werkstatt
DB_CONTAINER=wamo-supabase-db
PORT=55448
DIENST_PORT=18095
URL="https://192.168.178.136:$PORT"
UNIT_NAMEN=(wamo-werkstatt-ausgang.service wamo-werkstatt.service wamo-werkstatt-bruecke.socket wamo-werkstatt-bruecke.service wamo-werkstatt-sammler.service wamo-werkstatt-sammler.timer)
MODULE_DATEIEN=(werkstatt/wamo_werkstatt_sammler.py wamo_werkstatt_rauchtest.py werkstatt/wamo-werkstatt-ausgang.nft)

TROCKEN=nein
BEFEHL=einrichten
SCHEMA=""
LAN_OFFEN=nein
ARBEIT=""
CADDY_OWNER=""
CADDY_GROUP=""
CADDY_UNDO=nein
CADDY_SITE_ALT=""
CADDY_COMPOSE_ALT=""
CADDY_COMPOSE_NEU=nein
DIENST_WAR_AKTIV=nein
UNDO=()
OWN_ROOT=(-o root -g root)
[ -z "$W" ] || OWN_ROOT=()   # im Probelauf gibt es kein chown

usage() {
  echo "Aufruf: $0 [einrichten|status|pruefen] [--trocken] [--quelle ORDNER] [--schema wamo_dev|wamo_test|wamo_prod] [--lan-offen]" >&2
  exit 2
}
fehler() { echo "$*" >&2; exit 1; }
# Im Trockenlauf wird eine Vorbedingung nur gemeldet (im Echtlauf bricht das Skript ab)
muss() {
  if [ "$TROCKEN" = ja ]; then echo "  WARNUNG (im Echtlauf Abbruch): $*" >&2; else fehler "$*"; fi
}
# Jede Änderung läuft über tu: im Trockenlauf wird sie nur angezeigt
tu() {
  if [ "$TROCKEN" = ja ]; then printf '  [trocken] %s\n' "$*"; else "$@"; fi
}
# schritt "Überschrift" "Beschreibung" funktion: führt die Funktion aus, im Trockenlauf nur Überschrift und Beschreibung zeigen
schritt() {
  echo "== $1"
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] $2"; else "$3"; fi
}
ipt() { iptables -w 5 "$@"; }
crlf_weg() { sed -i 's/\r$//' "$@"; }

aufraeumen() {
  local rc=$? i
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "${#UNDO[@]}" -gt 0 ]; then
    for ((i = ${#UNDO[@]} - 1; i >= 0; i--)); do "${UNDO[$i]}" || true; done
  fi
  case "$ARBEIT" in */.arbeit.*) rm -rf "$ARBEIT" ;; esac
  rm -rf -- "$BASIS"/.app.neu.* "$BASIS"/.venv.neu 2>/dev/null || true
  exit "$rc"
}
trap aufraeumen EXIT

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

# Ruhe: keine Sitzung im Kern (wie wamo-labor-einrichten.sh): Ein Neustart von wamo-caddy unterbräche das Gespräch kurz
kern_ruhig() {
  local unit pid udp log roh_ss roh_log
  for unit in wamo-core wamo-core@a wamo-core@b; do
    pid="$(systemctl show "$unit" -p MainPID --value 2>/dev/null || echo 0)"
    if [ -z "$pid" ] || [ "$pid" = 0 ]; then continue; fi
    # Fail-closed: Lässt sich der Zustand nicht lesen, gilt der Kern als nicht ruhig
    roh_ss="$(ss -uanpH 2>/dev/null)" || { echo "  Kern nicht prüfbar: ss fehlgeschlagen" >&2; return 1; }
    udp="$(grep -c "pid=$pid," <<<"$roh_ss" || true)"
    roh_log="$(journalctl -u "$unit" --since '-5 min' --no-pager -q 2>/dev/null)" \
      || { echo "  Kern nicht prüfbar: journalctl fehlgeschlagen" >&2; return 1; }
    # abgewiesene Anfragen ohne Anmeldung (401) und die Hintergrundabfrage einer offenen Oberfläche sind keine Sitzung
    log="$(grep -vE 'Zugang abgelehnt|401 Unauthorized|/wamo/api/hinweise|^$' <<<"$roh_log" | wc -l || true)"
    if [ "${udp:-0}" != 0 ] || [ "${log:-0}" != 0 ]; then
      echo "  Kern nicht ruhig ($unit): UDP-Sockets $udp, Journalzeilen der letzten 5 Minuten $log" >&2
      return 1
    fi
  done
  return 0
}

verbindungen_offen() {
  local roh
  if roh="$(docker exec wamo-caddy netstat -tn 2>/dev/null)"; then
    awk '$6 == "ESTABLISHED" && $4 ~ /:5544[3-8]$/' <<<"$roh" | wc -l
  else
    ss -tn state established 2>/dev/null | awk '$3 ~ /:5544[3-8]$/' | wc -l
  fi
}

ruhe_pruefen() {
  local n
  kern_ruhig || return 1
  n="$(verbindungen_offen)"
  if [ "${n:-0}" != 0 ]; then
    echo "  Es bestehen $n Verbindungen an 55443 bis 55448 (wamo-caddy würde sie trennen)" >&2
    return 1
  fi
  echo "  ruhig: keine Sitzung im Kern, keine offene Verbindung an 55443 bis 55448"
}

# ---------- Vorprüfung
dateien_pruefen() {
  local f
  for f in werkstatt/wamo-werkstatt.service werkstatt/wamo-werkstatt-ausgang.service werkstatt/wamo-werkstatt-ausgang.nft werkstatt/wamo-werkstatt-bruecke.socket \
    werkstatt/wamo-werkstatt-bruecke.service werkstatt/wamo-werkstatt-sammler.service werkstatt/wamo-werkstatt-sammler.timer werkstatt/wamo_werkstatt_sammler.py \
    werkstatt/werkstatt.env.vorlage werkstatt/admins.vorlage wamo_werkstatt_rauchtest.py wamo-caddy/kern/wamo-werkstatt.caddy wamo-caddy/docker-compose.yml \
    wamo-firewall.sh wamo-firewall-einrichten.sh wamo-labor-site.sh; do
    [ -f "$HERE/$f" ] || fehler "$HERE/$f fehlt (infra/sokrates2 vollständig verteilen)."
  done
  for f in werkstatt/wamo_werkstatt_sammler.py wamo_werkstatt_rauchtest.py; do
    "$PYTHON" -I -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$HERE/$f" || fehler "Syntaxfehler in $f"
  done
}

quelle_pruefen() {
  local py
  [ -d "$QUELLE/wamo_werkstatt" ] && [ -f "$QUELLE/requirements.txt" ] \
    || { muss "$QUELLE/wamo_werkstatt oder $QUELLE/requirements.txt fehlt (werkstatt/ aus dem Repo nach $QUELLE kopieren)."; return 0; }
  # Die Sperrdatei muss Prüfsummen tragen (uv pip compile --generate-hashes): Jedes angeheftete Paket hat mindestens eine --hash=sha256 in seinem Block
  "$PYTHON" -I -c 'import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
blocks = re.split(r"(?m)^(?=[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^]]*\])?==)", text)[1:]
sys.exit(0 if blocks and all("--hash=sha256:" in b for b in blocks) and not re.search(r"(?m)^\s*(-e|git\+|https?://)", text) else 1)' "$QUELLE/requirements.txt" \
    || muss "$QUELLE/requirements.txt hat keine Prüfsummen für jedes Paket (uv pip compile pyproject.toml --generate-hashes)."
  if find "$QUELLE/wamo_werkstatt" -type l | grep -q .; then muss "Im Code liegt ein symbolischer Link ($QUELLE/wamo_werkstatt), Abbruch."; fi
  if find "$QUELLE/wamo_werkstatt" \( -name '.env*' -o -name 'geheim*' -o -name '*.pem' -o -name '*.key' -o -name '*.env' \) | grep -q .; then
    muss "Im Code liegt eine Geheimnisdatei ($QUELLE/wamo_werkstatt), Abbruch."
  fi
  while IFS= read -r py; do
    "$PYTHON" -I -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$py" || muss "Syntaxfehler in $py"
  done < <(find "$QUELLE/wamo_werkstatt" -name '*.py' -not -path '*/__pycache__/*')
}

# Port 55448 hängt an /etc/wamo/admin-quellen (Kette WAMO-FW-ADMIN). Ohne gültigen Eintrag gilt das ganze Büro-LAN, am Labortag sitzen dort Gäste:
# Das Skript richtet die Werkstatt dann nur mit --lan-offen ein.
admin_quellen_pruefen() {
  local datei="$W/etc/wamo/admin-quellen" n=0 zeile
  if [ -r "$datei" ]; then
    while IFS= read -r zeile || [ -n "$zeile" ]; do
      zeile="${zeile%%#*}"
      if [[ "$zeile" =~ [^[:space:]] ]]; then n=$((n + 1)); fi
    done < "$datei"
  fi
  if [ "$n" -gt 0 ]; then echo "  Admin-Quellen: $n Einträge in /etc/wamo/admin-quellen"; return 0; fi
  if [ "$LAN_OFFEN" = ja ]; then
    echo "  WARNUNG: /etc/wamo/admin-quellen hat keinen Eintrag: Das ganze Büro-LAN erreicht den Port $PORT (--lan-offen)." >&2
    return 0
  fi
  muss "/etc/wamo/admin-quellen hat keinen Eintrag: Das ganze Büro-LAN erreichte den Port $PORT (Gäste am Labortag). Quellen eintragen (README Abschnitt 6.1) oder bewusst --lan-offen setzen."
}

# Das Schema: Option, sonst die Zeile in werkstatt.env, sonst WAMO_DB_SCHEMA des Kerns (nur diese eine Zeile), sonst wamo_dev
schema_bestimmen() {
  local aus_datei="" kern=""
  if [ -f "$ETC/werkstatt.env" ]; then
    aus_datei="$(grep -E '^WAMO_WERKSTATT_SCHEMA=' "$ETC/werkstatt.env" | tail -n1 | cut -d= -f2 | tr -d '[:space:]"' || true)"
  fi
  if [ -z "$SCHEMA" ] && [ -z "$aus_datei" ] && [ -r "$W/etc/wamo/core.env" ]; then
    kern="$(grep -E '^WAMO_DB_SCHEMA=' "$W/etc/wamo/core.env" | tail -n1 | cut -d= -f2 | tr -d '[:space:]"' || true)"
  fi
  if [ -n "$aus_datei" ]; then
    [ -z "$SCHEMA" ] || [ "$SCHEMA" = "$aus_datei" ] || fehler "werkstatt.env nennt das Schema $aus_datei, --schema nennt $SCHEMA (die Datei von Hand ändern)."
    SCHEMA="$aus_datei"
  fi
  SCHEMA="${SCHEMA:-${kern:-wamo_dev}}"
  [[ "$SCHEMA" =~ ^wamo_(dev|test|prod)$ ]] || fehler "Das Schema '$SCHEMA' ist ungültig (erlaubt: wamo_dev, wamo_test, wamo_prod)."
  echo "  Schema: $SCHEMA"
}

migration_pruefen() {
  [ -z "$W" ] || { echo "  (Probelauf: keine Prüfung der Datenbank)"; return 0; }
  local ergebnis
  ergebnis="$(docker exec "$DB_CONTAINER" psql -U postgres -At -c "select to_regproc('$SCHEMA.werkstatt_labor_stand') is not null" 2>/dev/null || true)"
  [ "$ergebnis" = t ] || { muss "Die Migration 0031_werkstatt ist im Schema $SCHEMA nicht angewendet (Funktion werkstatt_labor_stand fehlt)."; return 0; }
  echo "  Migration 0031 vorhanden"
}

# Ein Port muss frei sein oder dem eigenen Stack gehören
port_frei_caddy() {
  local belegt eigener
  belegt="$(ss -tlnH "sport = :$PORT" 2>/dev/null || true)"
  [ -n "$belegt" ] || return 0
  eigener="$(docker port wamo-caddy 2>/dev/null || true)"
  case "$eigener" in *":$PORT"*) return 0 ;; esac
  muss "Port $PORT ist schon belegt (nicht von wamo-caddy)."
}

port_frei_dienst() {
  local belegt
  belegt="$(ss -tlnH "sport = :$DIENST_PORT" 2>/dev/null || true)"
  [ -n "$belegt" ] || return 0
  [ "$(systemctl is-active wamo-werkstatt.service 2>/dev/null || true)" = active ] && return 0
  muss "Port $DIENST_PORT ist schon belegt (nicht vom Dienst wamo-werkstatt)."
}

vorpruefung() {
  echo "== Vorprüfung"
  local w
  dateien_pruefen
  quelle_pruefen
  schema_bestimmen
  "$PYTHON" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || muss "Python 3.11 oder neuer nötig ($PYTHON)."
  admin_quellen_pruefen
  if [ -n "$W" ]; then echo "  Vorprüfung der Programme und Dienste entfällt im Probelauf"; return 0; fi
  for w in docker curl ss journalctl flock systemctl nft systemd-analyze useradd getent; do
    command -v "$w" >/dev/null 2>&1 || muss "$w fehlt."
  done
  docker compose version >/dev/null 2>&1 || muss "docker compose fehlt."
  "$PYTHON" -I -c 'import venv, ensurepip' >/dev/null 2>&1 || muss "Das Paket python3-venv fehlt."
  "$PYTHON" -I -m pip --version >/dev/null 2>&1 || muss "pip fehlt für $PYTHON (Paket python3-pip)."
  [ -x /usr/lib/systemd/systemd-socket-proxyd ] || muss "/usr/lib/systemd/systemd-socket-proxyd fehlt (Brücke zu Caddy)."
  getent group wamocon >/dev/null || muss "Gruppe wamocon fehlt (Zugang von Caddy zum Socket)."
  [ -n "$(docker ps -q -f name=^wamo-caddy$ 2>/dev/null || true)" ] || muss "wamo-caddy läuft nicht (zuerst wamo-tls-einrichten.sh)."
  [ -d "$CADDY_DIR/etc" ] && [ -f "$CADDY_COMPOSE" ] || muss "$CADDY_DIR fehlt oder ist unvollständig (zuerst wamo-tls-einrichten.sh)."
  [ -x "$FIREWALL_BIN" ] || muss "Die WAMO-Firewall ist nicht eingerichtet (zuerst wamo-firewall-einrichten.sh)."
  [ -f "$ETC/db.zugang" ] || muss "$ETC/db.zugang fehlt (python scripts/wamo_dienst_db.py einrichten werkstatt)."
  [ -f "$ETC/wamo-ca.crt" ] || muss "$ETC/wamo-ca.crt fehlt (python scripts/wamo_dienst_db.py einrichten werkstatt)."
  if [ -f "$ETC/db.zugang" ]; then echo "  Zugangsdatei $ETC/db.zugang vorhanden (Inhalt wird nicht gelesen)"; fi
  migration_pruefen
  port_frei_caddy
  port_frei_dienst
  docker compose -f "$HERE/wamo-caddy/docker-compose.yml" --project-directory "$CADDY_DIR" config -q >/dev/null \
    || muss "docker compose config -q schlägt für wamo-caddy/docker-compose.yml fehl."
  if ! cmp -s "$HERE/wamo-caddy/docker-compose.yml" "$CADDY_COMPOSE"; then
    ruhe_pruefen || muss "Abbruch: Gerade ist Betrieb (siehe oben). wamo-caddy wird neu angelegt, sobald niemand spricht (Skript erneut ausführen)."
  fi
}

# ---------- Sicherung
kopie() { if [ -f "$1" ]; then cp -p "$1" "$2"; fi; }

sichern() {
  echo "== Sicherung (vor jeder Änderung, ohne db.zugang und ohne Erlaubnisliste)"
  local zeit ziel n=1 u
  zeit="$(date +%Y%m%d-%H%M%S)"
  ziel="$SICHERUNG/$zeit"
  while [ -e "$ziel" ]; do n=$((n + 1)); ziel="$SICHERUNG/$zeit-$n"; done
  if [ "$TROCKEN" = ja ]; then
    echo "  [trocken] Sicherung nach $ziel: Compose, Caddyfile und Site von wamo-caddy, Firewall-Skript, Units, werkstatt.env, iptables-save"
    return 0
  fi
  mkdir -p "$SICHERUNG" "$ziel"
  chmod 0700 "$SICHERUNG" "$ziel"
  kopie "$CADDY_COMPOSE" "$ziel/wamo-caddy-compose.vorher"
  kopie "$CADDY_DIR/etc/Caddyfile" "$ziel/Caddyfile.vorher"
  kopie "$SITE_DATEI" "$ziel/wamo-werkstatt.caddy.vorher"
  kopie "$FIREWALL_BIN" "$ziel/wamo-firewall.vorher"
  kopie "$ETC/werkstatt.env" "$ziel/werkstatt.env.vorher"
  for u in "${UNIT_NAMEN[@]}"; do kopie "$UNITS/$u" "$ziel/$u.vorher"; done
  if [ -z "$W" ]; then iptables-save > "$ziel/iptables-save.txt" 2>/dev/null || true; fi
  echo "  $ziel"
}

# ---------- Benutzer, Ordner, Konfiguration
benutzer_anlegen() {
  echo "== Benutzer $BENUTZER"
  if [ -n "$W" ]; then echo "  (Probelauf: kein Benutzer)"; return 0; fi
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] legt den Systembenutzer $BENUTZER an (nologin, keine weiteren Gruppen), falls er fehlt"; return 0; fi
  if ! id "$BENUTZER" >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --comment "W.A.I.S. Werkstatt" "$BENUTZER"
    echo "  angelegt"
  fi
  local gruppen
  gruppen="$(id -nG "$BENUTZER")"
  [ "$gruppen" = "$BENUTZER" ] || fehler "$BENUTZER ist in weiteren Gruppen ($gruppen), Abbruch."
  passwd -l "$BENUTZER" >/dev/null 2>&1 || true
  echo "  $(id "$BENUTZER")"
}

# Ein Ordner mit Modus und Eigentümer (nur im echten Lauf): verz MODUS BESITZER GRUPPE ORDNER
verz() {
  local modus="$1" besitzer="$2" gruppe="$3" ordner="$4"
  [ ! -L "$ordner" ] || fehler "$ordner ist ein Link, Abbruch."
  mkdir -p "$ordner"
  chmod "$modus" "$ordner"
  if [ -z "$W" ]; then chown "$besitzer:$gruppe" "$ordner"; fi
}

konfig_aus_vorlage() {
  local vorlage="$1" ziel="$2" modus="$3" gruppe="$4"
  if [ -f "$ziel" ]; then echo "  $(basename "$ziel") vorhanden (unverändert)"; return 0; fi
  sed -e "s|__SCHEMA__|$SCHEMA|g" -e 's/\r$//' "$vorlage" > "$ziel"
  chmod "$modus" "$ziel"
  if [ -z "$W" ]; then chown "root:$gruppe" "$ziel"; fi
  echo "  $(basename "$ziel") aus der Vorlage angelegt"
}

ordner_und_konfig() {
  local datei
  verz 0755 root root "$BASIS"
  verz 0755 root root "$ETC"
  verz 0750 root "$BENUTZER" "$DATEN"
  verz 0750 root "$BENUTZER" "$DATEN/protokolle"
  verz 0700 root root "$DATEN/zustand"
  mkdir -p "$(dirname "$TMPFILES")"
  printf '%s\n' "# W.A.I.S. Werkstatt: Ordner des Sockets. 2750 root:wamocon: nur root legt dort an, die Gruppe wamocon (der Container wamo-caddy) erreicht den" \
    "# Socket werkstatt.sock (0660); das Setgid-Bit vererbt die Gruppe. Der Ordner bleibt bestehen, solange wamo-caddy ihn einbindet (Compose von wamo-caddy)." \
    "d /run/wamo-werkstatt 2750 root wamocon -" > "$TMPFILES"
  chmod 0644 "$TMPFILES"
  if [ -z "$W" ]; then
    systemd-tmpfiles --create "$TMPFILES"
  else
    mkdir -p "$RUN"
  fi
  konfig_aus_vorlage "$HERE/werkstatt/werkstatt.env.vorlage" "$ETC/werkstatt.env" 0644 root
  konfig_aus_vorlage "$HERE/werkstatt/admins.vorlage" "$ETC/admins" 0640 "$BENUTZER"
  if [ -z "$W" ]; then
    for datei in admins db.zugang; do
      [ ! -L "$ETC/$datei" ] || fehler "$ETC/$datei ist ein Link, Abbruch."
    done
    # Besitzer und Rechte in einem Zug, der Inhalt wird nie gelesen oder angezeigt
    chown "root:$BENUTZER" "$ETC/admins" "$ETC/db.zugang"
    chmod 0640 "$ETC/admins"
    chmod 0440 "$ETC/db.zugang"
    chmod 0644 "$ETC/wamo-ca.crt"
    stat -c '  %n %U:%G %a' "$ETC/werkstatt.env" "$ETC/admins" "$ETC/db.zugang" "$ETC/wamo-ca.crt"
  fi
  if [ -z "$(grep -vE '^[[:space:]]*(#|$)' "$ETC/admins" || true)" ]; then
    echo "  HINWEIS: Die Erlaubnisliste $ETC/admins hat noch keine Einträge: Niemand kommt in die Werkstatt (user_id je Zeile eintragen, dann den Dienst neu starten)."
  fi
}

# ---------- Programme und venv
programme() {
  local neu m
  rm -rf -- "$BASIS"/.app.neu.*
  neu="$(mktemp -d "$BASIS/.app.neu.XXXXXX")"
  cp -a "$QUELLE/wamo_werkstatt" "$neu/wamo_werkstatt"
  find "$neu" -name '__pycache__' -prune -exec rm -rf {} +
  find "$neu" -type l -exec rm -f {} +
  for m in "${MODULE_DATEIEN[@]}"; do
    install -m 0644 "$HERE/$m" "$neu/$(basename "$m")"
  done
  find "$neu" -type f \( -name '*.py' -o -name '*.nft' \) -exec sed -i 's/\r$//' {} +
  find "$neu" -type d -exec chmod 0755 {} +
  find "$neu" -type f -exec chmod 0644 {} +
  if [ -z "$W" ]; then chown -R root:root "$neu"; fi
  ( cd "$neu" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > "$neu.summen" )
  mv "$neu.summen" "$neu/SHA256SUMS"
  chmod 0644 "$neu/SHA256SUMS"
  if [ -z "$W" ]; then chown root:root "$neu/SHA256SUMS"; fi
  ( cd "$neu" && sha256sum -c --quiet SHA256SUMS ) || { rm -rf "$neu"; fehler "Prüfsumme des neuen Baums stimmt nicht."; }
  rm -rf "$APP.vorher"
  if [ -e "$APP" ]; then mv "$APP" "$APP.vorher"; fi
  if ! mv "$neu" "$APP"; then
    if [ -e "$APP.vorher" ]; then mv "$APP.vorher" "$APP"; fi
    fehler "Austausch von $APP fehlgeschlagen, bisheriger Stand wiederhergestellt."
  fi
  echo "  $(wc -l < "$APP/SHA256SUMS") Dateien, Prüfsumme geprüft"
}

# Die Bibliotheken nur aus requirements.txt der Quelle (mit Prüfsummen), nur Binärpakete: pip führt dabei keinen Code aus
venv_bauen() {
  if [ -n "$W" ]; then echo "  (Probelauf: kein venv, kein pip, kein Netz)"; return 0; fi
  local neu="$BASIS/.venv.neu" purelib
  rm -rf -- "$neu"
  "$PYTHON" -I -m venv --without-pip "$neu"
  purelib="$("$neu/bin/python" -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  # Saubere Umgebung: keine PIP_*-Einstellungen, kein Benutzerordner. --require-hashes lehnt jede Datei ab, deren Prüfsumme nicht in der Sperrdatei steht,
  # --no-deps, weil die Sperrdatei alles nennt, --only-binary, damit nie ein Quellpaket als root gebaut wird.
  env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8 HOME=/nonexistent PIP_CONFIG_FILE=/dev/null \
    "$PYTHON" -I -m pip install --require-hashes --no-deps --only-binary=:all: --no-cache-dir --no-compile --disable-pip-version-check --root-user-action=ignore --quiet \
    --target "$purelib" -r "$QUELLE/requirements.txt" \
    || { rm -rf "$neu"; fehler "pip-Installation aus $QUELLE/requirements.txt fehlgeschlagen (Prüfsumme, Architektur?), Abbruch."; }
  find "$purelib" -name '__pycache__' -prune -exec rm -rf {} +
  find "$purelib" -type l -exec rm -f {} +                                 # nichts, was aus dem Ordner herauszeigt
  printf '%s\n' "$APP" > "$purelib/wamo_werkstatt_app.pth"
  chown -R root:root "$neu"
  chmod -R go-w,a+rX "$neu"
  # Import-Probe mit genau dem Interpreter des Dienstes, aber NICHT als root: Ein Import führt den Code der Pakete und der .pth-Dateien aus.
  ( cd / && runuser -u "$BENUTZER" -- "$neu/bin/python" -I -B -c 'import wamo_werkstatt' ) \
    || { rm -rf "$neu"; fehler "Das Paket wamo_werkstatt lässt sich nicht laden (Abhängigkeiten?), Abbruch."; }
  rm -rf "$VENV.vorher"
  if [ -e "$VENV" ]; then mv "$VENV" "$VENV.vorher"; fi
  if ! mv "$neu" "$VENV"; then
    if [ -e "$VENV.vorher" ]; then mv "$VENV.vorher" "$VENV"; fi
    fehler "Austausch von $VENV fehlgeschlagen, bisheriger Stand wiederhergestellt."
  fi
  rm -rf "$VENV.vorher"
  echo "  venv bereit, das Paket lädt"
}

# ---------- Firewall
firewall_steht() {
  ipt -S WAMO-FW 2>/dev/null | grep -q "ctorigdstport $PORT"
}

firewall() {
  echo "== Firewall: Port $PORT (Kette WAMO-FW-ADMIN, Quellen aus /etc/wamo/admin-quellen)"
  grep -q "LAN_PORTS_ADMIN=\"[0-9 ]*$PORT" "$HERE/wamo-firewall.sh" || fehler "$HERE/wamo-firewall.sh ohne den Port $PORT in LAN_PORTS_ADMIN (infra/sokrates2 vollständig verteilen)."
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] bash $HERE/wamo-firewall-einrichten.sh (nur wenn die Regel fehlt)"; return 0; fi
  if [ -n "$W" ]; then echo "  (Probelauf: keine Änderung der Firewall)"; return 0; fi
  if firewall_steht; then echo "  Regel steht bereits"; return 0; fi
  bash "$HERE/wamo-firewall-einrichten.sh"
  firewall_steht || fehler "Die Firewall-Regel für $PORT ist nicht aktiv."
  echo "  Regel aktiv (per systemctl reload, ohne Lücke)"
}

# ---------- Dienst
unit_installieren() {
  local u
  mkdir -p "$UNITS" "$AUSGANG_DIR"
  install -m 0644 "${OWN_ROOT[@]}" "$HERE/werkstatt/wamo-werkstatt-ausgang.nft" "$AUSGANG_DIR/regeln.nft"
  crlf_weg "$AUSGANG_DIR/regeln.nft"
  for u in "${UNIT_NAMEN[@]}"; do
    install -m 0644 "${OWN_ROOT[@]}" "$HERE/werkstatt/$u" "$UNITS/$u"
    crlf_weg "$UNITS/$u"
  done
  sed -i "s|__CADDY_DIR__|$CADDY_DIR|g" "$UNITS/wamo-werkstatt-sammler.service"
}

undo_dienst() {
  [ "$DIENST_WAR_AKTIV" = nein ] || return 0
  echo "  FEHLER: Der Dienst wamo-werkstatt und die Brücke werden wieder gestoppt (Dateien und Daten bleiben)" >&2
  systemctl disable --now wamo-werkstatt-sammler.timer wamo-werkstatt-bruecke.socket wamo-werkstatt-bruecke.service wamo-werkstatt.service >&2 || true
}

dienst_warten() {
  local runden="${WAMO_WERKSTATT_WARTE_RUNDEN:-30}" sek="${WAMO_WERKSTATT_WARTE_SEKUNDEN:-1}" i code=000
  [[ "$runden" =~ ^[0-9]+$ ]] || runden=30
  [[ "$sek" =~ ^[0-9]+$ ]] || sek=1
  for ((i = 0; i < runden; i++)); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$DIENST_PORT/werkstatt/api/ich" || true)"
    [ "$code" != 000 ] && { echo "  Dienst antwortet auf 127.0.0.1:$DIENST_PORT (ohne Token HTTP $code)"; return 0; }
    sleep "$sek"
  done
  journalctl -u wamo-werkstatt -n 30 --no-pager >&2 || true
  fehler "Der Dienst antwortet nach $((runden * sek)) Sekunden nicht auf 127.0.0.1:$DIENST_PORT (journalctl -u wamo-werkstatt)."
}

dienst() {
  echo "== Dienst: wamo-werkstatt, Ausgangsregel, Brücke"
  if [ "$TROCKEN" = ja ]; then
    echo "  [trocken] Units nach $UNITS, Ausgangsregel nach $AUSGANG_DIR/regeln.nft (nft -c prüft sie), systemctl daemon-reload, enable und restart"
    echo "  [trocken] wamo-werkstatt-ausgang, wamo-werkstatt, dann wamo-werkstatt-bruecke.socket; Probe auf 127.0.0.1:$DIENST_PORT"
    return 0
  fi
  unit_installieren
  if [ -n "$W" ]; then echo "  (Probelauf: kein systemd, keine nft-Tabelle)"; return 0; fi
  nft -c -f "$AUSGANG_DIR/regeln.nft" || fehler "Die Ausgangsregel ist ungültig (nft -c), Abbruch."
  systemd-analyze verify "$UNITS/wamo-werkstatt-ausgang.service" "$UNITS/wamo-werkstatt.service" "$UNITS/wamo-werkstatt-bruecke.socket" \
    "$UNITS/wamo-werkstatt-bruecke.service" "$UNITS/wamo-werkstatt-sammler.service" "$UNITS/wamo-werkstatt-sammler.timer" 2>&1 \
    | grep -v '^$' | sed 's/^/  verify: /' || true
  [ "$(systemctl is-active wamo-werkstatt.service 2>/dev/null || true)" != active ] || DIENST_WAR_AKTIV=ja
  UNDO+=(undo_dienst)
  systemctl daemon-reload
  systemctl enable wamo-werkstatt-ausgang.service wamo-werkstatt.service wamo-werkstatt-bruecke.socket >/dev/null 2>&1
  systemctl restart wamo-werkstatt-ausgang.service
  nft list table inet wamo_werkstatt_ausgang >/dev/null || fehler "Die Tabelle wamo_werkstatt_ausgang fehlt, Abbruch."
  systemctl restart wamo-werkstatt.service
  dienst_warten
  systemctl restart wamo-werkstatt-bruecke.socket
  for _ in 1 2 3 4 5 6 7 8 9 10; do [ -S "$RUN/werkstatt.sock" ] && break; sleep 1; done
  [ -S "$RUN/werkstatt.sock" ] || fehler "Der Socket $RUN/werkstatt.sock fehlt (journalctl -u wamo-werkstatt-bruecke.socket)."
  stat -c '  Socket %n %U:%G %a' "$RUN/werkstatt.sock"
  systemctl is-active wamo-werkstatt.service | sed 's/^/  Dienst: /' || true
}

# ---------- Caddy (zwei Stufen wie beim Labor-Dienst; die Bausteine stehen in wamo-labor-site.sh)
caddy_pruefen() {
  local image
  image="$(caddy_image_laufend)"
  [ -n "$image" ] || fehler "Das Image von wamo-caddy ist nicht zu ermitteln."
  arbeit_anlegen "$CADDY_DIR"
  mkdir -p "$ARBEIT/etc/kern"
  install -m 0644 "$HERE/wamo-caddy/kern/wamo-werkstatt.caddy" "$ARBEIT/etc/kern/wamo-werkstatt.caddy"
  crlf_weg "$ARBEIT/etc/kern/wamo-werkstatt.caddy"
  arbeit_pruefen "$image"
  echo "  Konfiguration gültig"
}

undo_caddy() {
  [ "$CADDY_UNDO" = aktiv ] || return 0
  local start
  echo "  FEHLER: Caddy-Änderung wird zurückgenommen" >&2
  start="$(date +%s)"
  if [ -n "$CADDY_SITE_ALT" ]; then caddy_installieren 644 "$CADDY_SITE_ALT" "$SITE_DATEI"; else rm -f "$SITE_DATEI"; fi
  if [ "$CADDY_COMPOSE_NEU" = ja ] && [ -n "$CADDY_COMPOSE_ALT" ]; then
    caddy_installieren 644 "$CADDY_COMPOSE_ALT" "$CADDY_COMPOSE"
    ( cd "$CADDY_DIR" && docker compose up -d ) >&2 || true
  else
    caddy_neu_laden >&2 || true
  fi
  caddy_ports_pruefen "$start" >&2 || echo "  FEHLER: Nach der Rücknahme antworten die Ports von wamo-caddy nicht, bitte sofort ansehen (docker logs wamo-caddy)." >&2
  echo "  Zurückgenommen. Bitte das Protokoll prüfen (docker logs wamo-caddy)." >&2
}

# Stufe 1: Site installieren und Caddy neu laden (prüft die Konfiguration atomar und ohne Ausfall). Solange 55448 im Container nicht veröffentlicht ist, gilt die Site nur dort.
caddy_stufe1() {
  local start
  caddy_installieren 644 "$ARBEIT/etc/kern/wamo-werkstatt.caddy" "$SITE_DATEI"
  start="$(date +%s)"
  caddy_neu_laden
  echo "  Stufe 1: Site geladen"
  caddy_ports_pruefen "$start"
}

# Stufe 2 (nur wenn sich das Compose von wamo-caddy ändert): Port 55448 und der Ordner /run/wamo-werkstatt, wamo-caddy wird EINMAL neu angelegt
caddy_stufe2() {
  local start
  ruhe_pruefen || fehler "Abbruch: Gerade ist Betrieb (siehe oben). wamo-caddy wird neu angelegt, sobald niemand spricht (Skript erneut ausführen)."
  CADDY_COMPOSE_NEU=ja
  caddy_installieren 644 "$HERE/wamo-caddy/docker-compose.yml" "$CADDY_COMPOSE"
  echo "  Stufe 2: Compose von wamo-caddy geändert (Port $PORT, Ordner /run/wamo-werkstatt): Container wird neu angelegt"
  start="$(date +%s)"
  ( cd "$CADDY_DIR" && docker compose up -d )
  caddy_ports_pruefen "$start"
}

caddy_anwenden() {
  local compose_neu="$1"
  CADDY_COMPOSE_NEU=nein
  if [ -f "$SITE_DATEI" ]; then CADDY_SITE_ALT="$ARBEIT/site.vorher"; cp -a "$SITE_DATEI" "$CADDY_SITE_ALT"; fi
  CADDY_COMPOSE_ALT="$ARBEIT/compose.vorher"
  cp -a "$CADDY_COMPOSE" "$CADDY_COMPOSE_ALT"
  CADDY_UNDO=aktiv
  UNDO+=(undo_caddy)
  caddy_stufe1
  if [ "$compose_neu" = ja ]; then caddy_stufe2; fi
  antwortet "$URL/werkstatt/api/ich" || fehler "Keine Antwort von $URL nach der Caddy-Änderung."
  CADDY_UNDO=fertig
}

caddy() {
  echo "== Caddy: Site $URL (in zwei Stufen)"
  local compose_neu=nein
  cmp -s "$HERE/wamo-caddy/docker-compose.yml" "$CADDY_COMPOSE" || compose_neu=ja
  if [ "$TROCKEN" = ja ]; then
    echo "  [trocken] Konfiguration prüfen (caddy adapt in einem Wegwerf-Container ohne Netz)"
    echo "  [trocken] Stufe 1: Site-Datei $SITE_DATEI installieren und caddy reload (ohne Ausfall)"
    [ "$compose_neu" = nein ] || echo "  [trocken] Stufe 2: Ruhe prüfen, Compose von wamo-caddy ändern (Port $PORT, Ordner /run/wamo-werkstatt), Container neu anlegen, dann die Ports von wamo-caddy prüfen"
    return 0
  fi
  if [ -n "$W" ]; then
    mkdir -p "$CADDY_DIR/etc/kern"
    install -m 0644 "$HERE/wamo-caddy/kern/wamo-werkstatt.caddy" "$SITE_DATEI"
    install -m 0644 "$HERE/wamo-caddy/docker-compose.yml" "$CADDY_COMPOSE"
    echo "  (Probelauf: Site und Compose abgelegt, kein docker)"
    return 0
  fi
  # CADDY_OWNER und CADDY_GROUP liest caddy_installieren in wamo-labor-site.sh (Besitzer der Dateien im Ordner von wamo-caddy)
  # shellcheck disable=SC2034
  CADDY_OWNER="$(stat -c %U "$CADDY_DIR")"
  # shellcheck disable=SC2034
  CADDY_GROUP="$(stat -c %G "$CADDY_DIR")"
  # Die gemeinsame Sperre mit dem Aktualisierer der Betreuer-Geräte (er lädt Caddy ebenfalls neu und prüft die ganze Konfiguration samt dieser Site)
  sperre_nehmen "$W/run/wamo-labor-geraete/lock" 120 || fehler "Ein Lauf des Aktualisierers der Betreuer-Geräte hält die Sperre (nach 120 Sekunden aufgegeben): Die Site wurde nicht geändert. Bitte einrichten erneut ausführen."
  caddy_pruefen
  caddy_anwenden "$compose_neu"
  sperre_loesen
}

# ---------- Sammler
sammler() {
  echo "== Sammler: wamo-werkstatt-sammler.timer (jede Minute)"
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] enable --now wamo-werkstatt-sammler.timer, ein erster Lauf, betrieb.json prüfen"; return 0; fi
  if [ -n "$W" ]; then echo "  (Probelauf: kein systemd)"; return 0; fi
  systemctl enable --now wamo-werkstatt-sammler.timer >/dev/null 2>&1
  systemctl start wamo-werkstatt-sammler.service || { journalctl -u wamo-werkstatt-sammler -n 20 --no-pager >&2 || true; fehler "Der erste Lauf des Sammlers ist fehlgeschlagen."; }
  [ -f "$DATEN/betrieb.json" ] || fehler "$DATEN/betrieb.json fehlt nach dem ersten Lauf des Sammlers."
  stat -c '  %n %U:%G %a' "$DATEN/betrieb.json"
}

pruefen() {
  echo "== Prüfung (Rauchtest gegen den Betrieb)"
  if [ "$TROCKEN" = ja ]; then echo "  [trocken] python3 $APP/wamo_werkstatt_rauchtest.py --produktiv --ca $CA"; return 0; fi
  if [ -n "$W" ]; then echo "  (Probelauf: kein Rauchtest)"; return 0; fi
  if ! "$PYTHON" -E -s -B "$APP/wamo_werkstatt_rauchtest.py" --produktiv --ca "$CA"; then
    echo "Der Rauchtest meldete einen Fehler. Der bisherige Baum liegt noch in $APP.vorher." >&2
    echo "Rückfall: sudo rm -rf $APP && sudo mv $APP.vorher $APP && sudo systemctl restart wamo-werkstatt" >&2
    exit 1
  fi
  rm -rf "$APP.vorher"
}

datei_status() {
  if [ -e "$2" ]; then echo "  $1: vorhanden ($(stat -c '%U:%G %a' "$2"))"; else echo "  $1: fehlt"; fi
}

status() {
  echo "== Status"
  local u
  schema_bestimmen
  for u in "${UNIT_NAMEN[@]}"; do
    echo "  $u: $(systemctl is-active "$u" 2>/dev/null || true) ($(systemctl is-enabled "$u" 2>/dev/null || true))"
  done
  datei_status "Programme" "$APP/SHA256SUMS"
  datei_status "venv" "$VENV/bin/python"
  datei_status "werkstatt.env" "$ETC/werkstatt.env"
  datei_status "admins" "$ETC/admins"
  datei_status "db.zugang" "$ETC/db.zugang"
  datei_status "betrieb.json" "$DATEN/betrieb.json"
  datei_status "Socket" "$RUN/werkstatt.sock"
  datei_status "Caddy-Site" "$SITE_DATEI"
  if ipt -S WAMO-FW 2>/dev/null | grep -q "ctorigdstport $PORT"; then echo "  Firewall: Port $PORT hat eine Regel"; else echo "  Firewall: Regel für $PORT fehlt (oder keine Berechtigung)"; fi
  nft list table inet wamo_werkstatt_ausgang >/dev/null 2>&1 && echo "  Ausgangsregel: geladen" || echo "  Ausgangsregel: nicht geladen"
  echo "  Einträge der Erlaubnisliste: $(grep -cvE '^[[:space:]]*(#|$)' "$ETC/admins" 2>/dev/null || echo 0)"
}

# ---------- Aufruf
while [ $# -gt 0 ]; do
  case "$1" in
    einrichten|status|pruefen) BEFEHL="$1" ;;
    --trocken) TROCKEN=ja ;;
    --quelle) [ $# -ge 2 ] || usage; QUELLE="$2"; shift ;;
    --schema) [ $# -ge 2 ] || usage; SCHEMA="$2"; shift ;;
    --lan-offen) LAN_OFFEN=ja ;;
    *) usage ;;
  esac
  shift
done

if [ -n "$W" ]; then
  [[ "$W" =~ ^/[A-Za-z0-9/_.:~-]+$ ]] || fehler "WAMO_WERKSTATT_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9 und / _ . : ~ - sein."
  [ "$(id -u)" -ne 0 ] || fehler "Der Probelauf (WAMO_WERKSTATT_WURZEL) läuft nicht als root."
  echo "Probelauf unter $W (kein root, kein systemd, kein Benutzer, kein pip, keine Firewall, kein Rauchtest)"
  [ "${WAMO_WERKSTATT_HERKUNFT:-}" != ja ] || pruefe_ordner "$HERE"   # nur für Tests: der Herkunftsschutz auch im Probelauf
elif [ "$TROCKEN" = nein ] && { [ "$BEFEHL" = einrichten ] || [ "$BEFEHL" = pruefen ]; }; then
  [ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
  pruefe_ordner "$HERE"
  [ "$BEFEHL" != einrichten ] || pruefe_ordner "$QUELLE"
fi

# Die gemeinsamen Bausteine der Caddy-Site (nach dem Herkunftsschutz geladen: Ein Skript allein in einem unsicheren Ordner bricht vorher ab)
[ -f "$HERE/wamo-labor-site.sh" ] || fehler "$HERE/wamo-labor-site.sh fehlt (infra/sokrates2 vollständig verteilen)."
# shellcheck source=wamo-labor-site.sh
. "$HERE/wamo-labor-site.sh"
# die Dienste hinter wamo-caddy, die ein Neuanlegen oder ein Fehler lahmlegen würde (55447 nur, wenn die Site des Labor-Dienstes besteht)
CADDY_PORTS="55443 55444 55445 55446"
[ ! -f "$CADDY_DIR/etc/kern/wamo-labor.caddy" ] || CADDY_PORTS="$CADDY_PORTS 55447"

case "$BEFEHL" in
  status) status ;;
  pruefen) pruefen ;;
  einrichten)
    vorpruefung
    sichern
    benutzer_anlegen
    schritt "Ordner und Konfiguration" "legt Ordner, die tmpfiles-Datei, werkstatt.env und admins (nur wenn sie fehlen) an und setzt Besitzer und Rechte von db.zugang" ordner_und_konfig
    schritt "Programme nach $APP (neuer Baum, Prüfsumme, dann Austausch)" "baut $APP neu aus $QUELLE/wamo_werkstatt, schreibt SHA256SUMS, prüft sie und tauscht dann aus" programme
    schritt "venv $VENV" "baut das venv aus $QUELLE/requirements.txt (nur Binärpakete, mit Prüfsummen), prüft den Import des Pakets als $BENUTZER und tauscht dann aus" venv_bauen
    firewall
    dienst
    caddy
    sammler
    pruefen
    ;;
esac
echo "Fertig."
