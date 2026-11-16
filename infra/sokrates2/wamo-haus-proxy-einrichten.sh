#!/usr/bin/env bash
# Richtet den Proxy für Entwicklungsaufträge mit Hausmodellen ein (wamo-haus-proxy, Paket P6a, docs/ausrollen-neue-nutzer.md 4.7 und 9).
#
# Aufruf auf Sokrates-2 (als root, aus dem Ordner mit den Dateien aus infra/sokrates2):
#   sudo bash wamo-haus-proxy-einrichten.sh einrichten [--trocken]   Benutzer, Code, Konfiguration, tmpfiles, Unit; startet nur mit Schlüssel
#   sudo bash wamo-haus-proxy-einrichten.sh schluessel               Schlüssel für LiteLLM verdeckt eingeben (stdin, nie als Argument)
#   sudo bash wamo-haus-proxy-einrichten.sh status
# Probelauf ohne root (Tests): WAMO_HAUS_PROXY_WURZEL=/tmp/probe bash wamo-haus-proxy-einrichten.sh einrichten
#
# Was entsteht:
#   Benutzer wamo-haus-proxy (System, ohne Anmeldung, ohne Home)
#   /opt/wamo-haus-proxy/app/wamo_haus_proxy.py und SHA256SUMS (root:root, nur lesbar)
#   /etc/wamo-haus-proxy/proxy.env (root:root 0644, LISTEN, ZIEL, MODELLE, PARALLEL, TAG_TOKEN_MAX; keine Geheimnisse)
#   /etc/wamo-haus-proxy/litellm.key (root:root 0400, nur mit dem Befehl schluessel; systemd reicht ihn als Credential durch)
#   /etc/tmpfiles.d/wamo-haus.conf und /run/wamo-haus (2750 wamo:wamo-haus-proxy, Tokendateien des Dispatchers)
#   /etc/systemd/system/wamo-haus-proxy.service, /var/lib/wamo-haus-proxy (StateDirectory, Buchung der Token)
#   Sicherungen vorhandener Dateien unter /var/backups/wamo-haus-proxy/<JJJJMMTT-HHMMSS>/
# Was es nicht tut: wamo-job.sh und wamo-egress.nft (Ausnahme der Sandbox) installiert wamo-job-einrichten.sh; den Schalter WAMO_HAUS
# in geheim.env und WAMO_ENTWICKLUNG_HAUS im Drop-in setzt der Betreiber zuletzt (Paket P6b). Kein Kern, kein anderer Dienst wird neu
# gestartet. Der Schlüssel des Kerns kommt nie hierher.
set -euo pipefail
umask 022

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WURZEL="${WAMO_HAUS_PROXY_WURZEL:-}"
DIENST=wamo-haus-proxy
BENUTZER=wamo-haus-proxy
APP="$WURZEL/opt/wamo-haus-proxy/app"
ETC="$WURZEL/etc/wamo-haus-proxy"
UNIT="$WURZEL/etc/systemd/system/wamo-haus-proxy.service"
TMPFILES="$WURZEL/etc/tmpfiles.d/wamo-haus.conf"
SICHERUNG="$WURZEL/var/backups/wamo-haus-proxy/$(date +%Y%m%d-%H%M%S)"
LISTEN=127.0.0.1:18090
ZIEL=http://192.168.178.75:4000
MODELLE=wamo-haus-coder,qwen3.6-35b
PARALLEL=2
TAG_TOKEN_MAX=30000000

fehler() { echo "wamo-haus-proxy-einrichten: $*" >&2; exit 1; }

if [ -n "$WURZEL" ]; then
  [[ $WURZEL =~ ^/[A-Za-z0-9._/-]+$ ]] || fehler "WAMO_HAUS_PROXY_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich und Schrägstrich sein"
  [ "$(id -u)" -ne 0 ] || fehler "der Probelauf läuft nicht als root"
  echo "Probelauf unter $WURZEL (kein root, kein systemd, kein Benutzer)"
else
  [ "$(id -u)" -eq 0 ] || fehler "bitte als root (sudo) ausführen"
fi

sichern() {  # vorhandene Datei vor dem Überschreiben sichern
  local pfad=$1
  [ -e "$pfad" ] || return 0
  mkdir -p "$SICHERUNG"
  cp -p "$pfad" "$SICHERUNG/$(basename "$pfad")"
}

einrichten() {
  local trocken=${1:-}
  for datei in wamo_haus_proxy.py wamo-haus-proxy.service wamo-haus.tmpfiles wamo_haus_proxy_rauchtest.py; do
    [ -f "$HERE/$datei" ] || fehler "$HERE/$datei fehlt"
  done
  if [ "$trocken" = --trocken ]; then
    echo "Trocken: es würde eingerichtet:"
    echo "  Benutzer $BENUTZER (System, nologin), Code nach $APP mit SHA256SUMS"
    echo "  $ETC/proxy.env: LISTEN=$LISTEN ZIEL=$ZIEL MODELLE=$MODELLE PARALLEL=$PARALLEL TAG_TOKEN_MAX=$TAG_TOKEN_MAX"
    echo "  $TMPFILES (/run/wamo-haus 2750 wamo:$BENUTZER), $UNIT (enable; start nur mit $ETC/litellm.key)"
    echo "  Schlüssel: $([ -s "$ETC/litellm.key" ] && echo vorhanden || echo 'fehlt (danach: schluessel)')"
    return 0
  fi
  echo "== 1. Benutzer $BENUTZER"
  if [ -z "$WURZEL" ]; then
    id -u wamo >/dev/null 2>&1 || fehler "Benutzer wamo fehlt (wamo-job-einrichten.sh zuerst)"
    id -u "$BENUTZER" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$BENUTZER"
    [ "$(id -Gn "$BENUTZER")" = "$BENUTZER" ] || fehler "$BENUTZER hat weitere Gruppen: $(id -Gn "$BENUTZER")"
  else
    echo "  (Probelauf: kein Benutzer)"
  fi
  echo "== 2. Code nach $APP"
  mkdir -p "$APP"
  sichern "$APP/wamo_haus_proxy.py"
  install -m 0644 "$HERE/wamo_haus_proxy.py" "$APP/wamo_haus_proxy.py"
  install -m 0644 "$HERE/wamo_haus_proxy_rauchtest.py" "$APP/wamo_haus_proxy_rauchtest.py"
  sed -i 's/\r$//' "$APP/wamo_haus_proxy.py" "$APP/wamo_haus_proxy_rauchtest.py"
  (cd "$APP" && sha256sum wamo_haus_proxy.py > SHA256SUMS)
  if [ -z "$WURZEL" ]; then chown -R root:root "$WURZEL/opt/wamo-haus-proxy"; chmod 0755 "$WURZEL/opt/wamo-haus-proxy" "$APP"; fi
  echo "== 3. Konfiguration $ETC/proxy.env (keine Geheimnisse)"
  mkdir -p "$ETC"
  chmod 0755 "$ETC"
  sichern "$ETC/proxy.env"
  printf 'LISTEN=%s\nZIEL=%s\nMODELLE=%s\nPARALLEL=%s\nTAG_TOKEN_MAX=%s\n' "$LISTEN" "$ZIEL" "$MODELLE" "$PARALLEL" "$TAG_TOKEN_MAX" > "$ETC/proxy.env.neu"
  chmod 0644 "$ETC/proxy.env.neu"
  mv "$ETC/proxy.env.neu" "$ETC/proxy.env"
  echo "== 4. tmpfiles $TMPFILES"
  mkdir -p "$(dirname "$TMPFILES")"
  sichern "$TMPFILES"
  install -m 0644 "$HERE/wamo-haus.tmpfiles" "$TMPFILES"
  sed -i 's/\r$//' "$TMPFILES"
  if [ -z "$WURZEL" ]; then systemd-tmpfiles --create "$TMPFILES"; ls -ld /run/wamo-haus; fi
  echo "== 5. Unit $UNIT"
  mkdir -p "$(dirname "$UNIT")"
  sichern "$UNIT"
  install -m 0644 "$HERE/wamo-haus-proxy.service" "$UNIT"
  sed -i 's/\r$//' "$UNIT"
  if [ -n "$WURZEL" ]; then
    echo "  (Probelauf: kein systemd)"
    return 0
  fi
  systemctl daemon-reload
  systemctl enable "$DIENST" >/dev/null 2>&1
  if [ -s "$ETC/litellm.key" ]; then
    systemctl restart "$DIENST"
    sleep 1
    systemctl is-active --quiet "$DIENST" || fehler "$DIENST läuft nicht (journalctl -u $DIENST)"
    echo "== 6. Rauchtest"
    /usr/bin/python3 -I "$APP/wamo_haus_proxy_rauchtest.py"
  else
    echo "Schlüssel fehlt: zuerst 'sudo bash $0 schluessel', dann startet der Dienst."
    echo "== 6. Rauchtest nur mit Attrappe"
    /usr/bin/python3 -I "$APP/wamo_haus_proxy_rauchtest.py" --nur-attrappe
  fi
}

schluessel() {
  # Der Wert kommt nur über stdin (verdeckt am Terminal), nie als Argument, nie in eine Ausgabe
  [ $# -eq 0 ] || fehler "der Schlüssel wird nie als Argument übergeben; nur über stdin"
  [ -d "$ETC" ] || fehler "$ETC fehlt (zuerst einrichten)"
  local wert=""
  if [ -t 0 ]; then
    read -r -s -p "Schlüssel für LiteLLM (virtueller Schlüssel wamo-haus-proxy): " wert
    echo
  else
    IFS= read -r wert || true
  fi
  [[ $wert =~ ^[[:graph:]]+$ ]] && (( ${#wert} >= 8 && ${#wert} <= 512 )) || fehler "Schlüssel leer, zu kurz, zu lang oder mit unerlaubten Zeichen"
  local neu="$ETC/.litellm.key.neu"
  ( umask 077; printf '%s\n' "$wert" > "$neu" )
  wert=""
  [ -n "$WURZEL" ] || chown root:root "$neu"
  chmod 0400 "$neu"
  # der alte Schlüssel wird bewusst nicht gesichert (keine Kopie unter /var/backups); in LiteLLM sperren, wenn er nicht mehr gilt
  mv -f "$neu" "$ETC/litellm.key"
  echo "Schlüssel abgelegt in $ETC/litellm.key (0400)."
  if [ -z "$WURZEL" ] && systemctl is-enabled --quiet "$DIENST" 2>/dev/null; then
    systemctl restart "$DIENST"
    sleep 1
    systemctl is-active --quiet "$DIENST" || fehler "$DIENST läuft nicht (journalctl -u $DIENST)"
    /usr/bin/python3 -I "$APP/wamo_haus_proxy_rauchtest.py"
  fi
}

status() {
  echo "Dienst: $(systemctl is-active "$DIENST" 2>/dev/null || true) / $(systemctl is-enabled "$DIENST" 2>/dev/null || true)"
  echo "Schlüssel: $([ -s "$ETC/litellm.key" ] && echo vorhanden || echo fehlt)"
  [ -f "$ETC/proxy.env" ] && sed 's/^/  /' "$ETC/proxy.env"
  ls -ld /run/wamo-haus 2>/dev/null || echo "/run/wamo-haus fehlt"
  ss -tlnH "sport = :18090" 2>/dev/null || true
}

befehl=${1:-}
shift || true
case "$befehl" in
  einrichten) einrichten "${1:-}" ;;
  schluessel) schluessel "$@" ;;
  status) status ;;
  *) echo "Aufruf: $0 einrichten [--trocken] | schluessel | status" >&2; exit 2 ;;
esac
