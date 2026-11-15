#!/usr/bin/env bash
# Rückweg für den Proxy der Hausmodelle (wamo-haus-proxy, Paket P6a, docs/ausrollen-neue-nutzer.md 9).
#
#   sudo bash wamo-haus-proxy-rueckweg.sh               Dienst stoppen und abschalten. Aufträge mit Hausmodellen scheitern danach
#                                                       geschlossen (kein Rückfall auf einen Claude-Zugang). Danach den Schalter
#                                                       WAMO_HAUS in geheim.env und WAMO_ENTWICKLUNG_HAUS im Drop-in auf aus setzen.
#   sudo bash wamo-haus-proxy-rueckweg.sh --entfernen   zusätzlich Unit, tmpfiles, Code, Konfiguration samt Schlüssel und Benutzer
#                                                       entfernen; die Buchung der Token wandert nach /var/backups/wamo-haus-proxy/.
# Die Ausnahme in wamo-job.sh und wamo-egress.nft bleibt: ohne Proxy lauscht dort niemand, und der Port verlangt ein Auftragstoken.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "bitte als root (sudo) ausführen" >&2; exit 1; }
DIENST=wamo-haus-proxy

systemctl disable --now "$DIENST" >/dev/null 2>&1 || true
echo "Dienst $DIENST gestoppt und abgeschaltet: $(systemctl is-active "$DIENST" 2>/dev/null || true)"
if [ "${1:-}" != --entfernen ]; then
  echo "Schalter zuletzt zurücknehmen: WAMO_HAUS in /etc/wamo/geheim.env entfernen, wamo-job-kern-einrichten.sh schalter --haus aus"
  exit 0
fi
ziel="/var/backups/wamo-haus-proxy/rueckweg-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ziel"
chmod 0700 "$ziel"
[ -f /var/lib/wamo-haus-proxy/verbrauch.jsonl ] && cp -p /var/lib/wamo-haus-proxy/verbrauch.jsonl "$ziel/"
rm -f /etc/systemd/system/wamo-haus-proxy.service /etc/tmpfiles.d/wamo-haus.conf
systemctl daemon-reload
rm -rf /opt/wamo-haus-proxy /etc/wamo-haus-proxy /var/lib/wamo-haus-proxy /run/wamo-haus
id -u wamo-haus-proxy >/dev/null 2>&1 && userdel wamo-haus-proxy
echo "Entfernt. Buchung gesichert unter $ziel."
