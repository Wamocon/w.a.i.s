#!/usr/bin/env bash
# Rückweg zu wamo-firewall-einrichten.sh: WAMO-Firewall abschalten und ihre Regeln entfernen.
#
# Ausführen auf Sokrates-2 mit sudo (Ordner im Home, siehe wamo-firewall-einrichten.sh):
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-firewall-rueckweg.sh"             # abschalten, Dateien bleiben
#   ssh sokrates2 "sudo bash ~/wamo-infra/wamo-firewall-rueckweg.sh --entfernen" # zusätzlich Skript, Unit, Einstellungen löschen
#
# Entfernt werden nur die eigenen Ketten (WAMO-FW, WAMO-FW-HTTP, WAMO-FW-LAN, WAMO-FW-ADMIN und WAMO-FW-INTERN aus früheren
# Fassungen; die übrigen entfernt "wamo-firewall stop") und der Sprung aus DOCKER-USER. Mit --entfernen gehen auch
# /etc/wamo/firewall.conf und /etc/wamo/admin-quellen (Quellen der Admin-Ports, Q13), vorher je eine Sicherung mit Zeitstempel
# nach /var/backups/wamo-firewall (0600). Die Sicherungen bleiben liegen. Die Regelstände dort dienen zum Nachsehen und nicht
# zum blinden Einspielen: Docker ändert seine eigenen Regeln bei jedem Containerstart, ein altes iptables-restore würde diese
# Regeln überschreiben.
#
# Nur die Admin-Ports wieder für das ganze Büro-LAN öffnen, ohne die Firewall abzuschalten: in /etc/wamo/admin-quellen alle
# Einträge auskommentieren (oder die Datei löschen), dann  sudo systemctl reload wamo-firewall.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SICHERUNG=/var/backups/wamo-firewall
CONF=/etc/wamo/firewall.conf
ADMIN_QUELLEN=/etc/wamo/admin-quellen

# Schutz gegen untergeschobene Dateien (wie in wamo-firewall-einrichten.sh)
pruefe_herkunft() {
  local erlaubt=" 0 $(id -u) ${SUDO_UID:-} " uid modus pfad
  while read -r uid modus pfad; do
    if [[ "$erlaubt" != *" $uid "* ]] || (( 8#$modus & 8#022 )); then
      echo "Unsicherer Ablageort: $pfad (Besitzer $uid, Rechte $modus). Ordner im eigenen Home ablegen und" \
        "mit chmod -R go-w schützen." >&2
      exit 1
    fi
  done < <(stat -c '%u %a %n' "$(dirname "$HERE")"; find "$HERE" \( -type l -printf '%U 777 %p\n' \) -o -printf '%U %m %p\n')
}

[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
pruefe_herkunft

systemctl disable --now wamo-firewall.service >/dev/null 2>&1 || true
if [ -x /usr/local/sbin/wamo-firewall ]; then
  /usr/local/sbin/wamo-firewall stop || true
fi
# Unabhängig vom installierten Skript: dieselben Schritte direkt (wiederholbar)
while iptables -w 5 -C DOCKER-USER -j WAMO-FW 2>/dev/null; do iptables -w 5 -D DOCKER-USER -j WAMO-FW; done
for k in WAMO-FW WAMO-FW-HTTP WAMO-FW-LAN WAMO-FW-ADMIN WAMO-FW-INTERN; do iptables -w 5 -F "$k" 2>/dev/null || true; done
for k in WAMO-FW WAMO-FW-HTTP WAMO-FW-LAN WAMO-FW-ADMIN WAMO-FW-INTERN; do iptables -w 5 -X "$k" 2>/dev/null || true; done

if [ "${1:-}" = "--entfernen" ]; then
  zeit="$(date +%Y%m%d-%H%M%S)"
  install -d -m 700 "$SICHERUNG"
  for f in "$CONF" "$ADMIN_QUELLEN"; do
    if [ -f "$f" ]; then
      install -m 600 -o root -g root "$f" "$SICHERUNG/$(basename "$f")-$zeit"
      echo "Sicherung: $SICHERUNG/$(basename "$f")-$zeit"
    fi
  done
  rm -f /etc/systemd/system/wamo-firewall.service /usr/local/sbin/wamo-firewall "$CONF" "$ADMIN_QUELLEN"
  systemctl daemon-reload
  echo "Skript, Unit und Einstellungen ($CONF, $ADMIN_QUELLEN) entfernt."
fi

echo "DOCKER-USER jetzt:"
iptables -w 5 -S DOCKER-USER || true
echo "Sicherungen: $(ls -1 /var/backups/wamo-firewall 2>/dev/null | wc -l) Dateien in /var/backups/wamo-firewall"
