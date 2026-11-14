#!/usr/bin/env bash
# W.A.I.S.: Einstieg für das Ausrollen auf Sokrates-2 über den selbst gehosteten GitHub-Runner (Benutzer wais-deploy).
# Installiert als /usr/local/sbin/wais-deploy (root 0755) durch wais-runner-einrichten.sh. Der Runner darf per sudoers genau die
# Aufrufe unten (/etc/sudoers.d/wais-deploy), sonst nichts. Dieses Skript baut keine Betriebslogik nach: Es ruft die vorhandenen
# Skripte des Standes (wamo-core-slots.sh, wamo-ui-umschalten.sh, wamo-labor-einrichten.sh) in der richtigen Reihenfolge auf.
#
#   wais-deploy pruefen-stand <commit>                 origin/main frisch holen, nur dort enthaltene Commits, Release-Name nennen
#   wais-deploy verteilen <commit> [--trocken]         Stand aus dem eigenen Spiegel nach /var/lib/wais-deploy/staende/<commit> legen
#                                                      (wie "verteilen" vom PC: infra/sokrates2, kern/, ui/, wamo-ui/bau.info)
#   wais-deploy test-kern <commit> [--trocken]         Kern-Release bauen (release) und im freien Slot starten (bereiten), ohne Umschalten
#   wais-deploy test-oberflaeche <commit> [--trocken]  neue Fassung in der freien Farbe bauen und prüfen (bauen), ohne Umschalten
#   wais-deploy prod-kern <commit> [--trocken]         Caddy auf den Slot des Release schalten (schalten), Bewährung 30 Minuten
#   wais-deploy prod-oberflaeche <commit> [--trocken]  auf die gebaute Farbe umschalten (umschalten --ohne-bau), Bewährung 120 Sekunden
#   wais-deploy ausleiten [--trocken]                  alte Kern-Instanz beenden (nur ohne Sitzung, frühestens 30 Minuten nach dem Schalten)
#   wais-deploy rueckweg kern|oberflaeche|beides [--trocken]   zurück auf den Stand, der vor dem letzten prod-Lauf live war
#   wais-deploy rauchtest                              Probe des aktiven Kern-Slots, live Farbe der Oberfläche, Labor-Dienst (falls eingerichtet)
#   wais-deploy status                                 Zustand anzeigen (nur lesend)
#
# Stufen: dev = pruefen-stand + verteilen | test = test-kern + test-oberflaeche + rauchtest | prod = prod-kern + prod-oberflaeche +
# rauchtest + ausleiten, Rückweg bei Fehlern. test verlangt einen verteilten Stand, prod einen Stand mit bestandenem test (Marken in
# zustand/). Jeder Befehl mit Commit holt origin/main frisch und nimmt nur Commits, die dort enthalten sind (die Prüfung steht hier,
# nicht nur im Workflow). Reihenfolge wie beim Ausrollen von Hand: Kern zuerst, dann Oberfläche; beim Rückweg umgekehrt.
#
# Sperren: /run/wais-deploy/lock (ein Lauf zur Zeit, sonst Exit 3). Für jedes Schalten von Caddy zusätzlich die gemeinsame Sperre
# /run/wamo-labor-geraete/lock (dieselbe wie Aktualisierer und Einrichtung der Labor-Dienste, höchstens 120 Sekunden warten). Der
# automatische Rückweg innerhalb der Bewährung des Kerns läuft ohne diese Sperre (wamo-core-slots.sh nimmt sie nicht).
# Protokoll: /var/log/wais-deploy/protokoll.log (root:adm 0640, alle Ausgaben) und je Lauf eine Zeile im Journal (logger -t wais-deploy).
# Rückgabewerte: 0 in Ordnung | 1 Fehler | 2 Aufruf ungültig | 3 Vorbedingung nicht erfüllt, nichts geändert | 4 nach dem Umschalten
# automatisch zurückgenommen | 5 Rückweg nicht möglich oder fehlgeschlagen (Handarbeit; Notanker: sudo wamo-anker status).
# Ausgabe für Maschinen: Zeilen "WAIS schluessel=wert" (commit, release, slot, farbe, vorher, kopf, ergebnis).
#
# Quelle: /etc/wais-deploy/quelle.conf (eine Zeile QUELLE_URL=git@github.com:Wamocon/<repo>.git oder https://github.com/Wamocon/<repo>.git),
# Lese-Schlüssel (Deploy-Key ohne Schreibrecht) /etc/wais-deploy/deploy_key, Hostschlüssel von GitHub /etc/wais-deploy/known_hosts.
# Spiegel /var/lib/wais-deploy/repo.git (root 0700), Stände /var/lib/wais-deploy/staende (root:wamocon 0750, die fünf neuesten
# bleiben), Zustand /var/lib/wais-deploy/zustand (root 0700). Die Oberfläche baut und schaltet als wamocon (wie vom PC), der Kern als root.
# Probelauf ohne root (Tests): WAIS_DEPLOY_WURZEL=/tmp/probe; Programme und Betriebsskripte kommen dann aus $WURZEL/attrappen.
set -euo pipefail
umask 022

AUFRUF="Aufruf: wais-deploy pruefen-stand <commit>
  | wais-deploy verteilen|test-kern|test-oberflaeche|prod-kern|prod-oberflaeche <commit> [--trocken]
  | wais-deploy ausleiten [--trocken] | wais-deploy rueckweg kern|oberflaeche|beides [--trocken]
  | wais-deploy rauchtest | wais-deploy status          (<commit>: genau 40 Hexzeichen, klein)"

fehler() { echo "wais-deploy: $*" >&2; exit 1; }
aufruf_fehler() { echo "wais-deploy: $*" >&2; echo "$AUFRUF" >&2; exit 2; }
vorbedingung() { echo "wais-deploy: Vorbedingung nicht erfüllt: $*" >&2; exit 3; }
handarbeit() { echo "wais-deploy: $*" >&2; exit 5; }

# ---------- Aufruf (streng, bevor irgendetwas angefasst wird)
COMMIT_RE='^[0-9a-f]{40}$'
BEFEHL="${1:-}"
[ $# -eq 0 ] || shift
COMMIT=""; TEIL=""; TROCKEN=nein
trocken_option() {
  if [ $# -eq 0 ]; then return 0; fi
  if [ $# -ne 1 ] || [ "$1" != --trocken ]; then aufruf_fehler "Unbekannte Angabe nach $BEFEHL."; fi
  TROCKEN=ja
}
case "$BEFEHL" in
  pruefen-stand)
    [ $# -eq 1 ] || aufruf_fehler "pruefen-stand braucht genau einen Commit."
    COMMIT="$1" ;;
  verteilen|test-kern|test-oberflaeche|prod-kern|prod-oberflaeche)
    [ $# -ge 1 ] || aufruf_fehler "$BEFEHL braucht einen Commit."
    COMMIT="$1"; shift
    trocken_option "$@" ;;
  ausleiten)
    trocken_option "$@" ;;
  rueckweg)
    [ $# -ge 1 ] || aufruf_fehler "rueckweg braucht kern, oberflaeche oder beides."
    case "$1" in kern|oberflaeche|beides) TEIL="$1" ;; *) aufruf_fehler "rueckweg: kern, oberflaeche oder beides." ;; esac
    shift
    trocken_option "$@" ;;
  rauchtest|status)
    [ $# -eq 0 ] || aufruf_fehler "$BEFEHL kennt keine weiteren Angaben." ;;
  *) aufruf_fehler "Unbekannter Befehl." ;;
esac
if [ -n "$COMMIT" ] && ! [[ "$COMMIT" =~ $COMMIT_RE ]]; then aufruf_fehler "Commit: genau 40 Hexzeichen, klein."; fi

# ---------- Umgebung: echtes System (root über sudo) oder Probelauf
WURZEL="${WAIS_DEPLOY_WURZEL:-}"
if [ -z "$WURZEL" ]; then
  [ "$(id -u)" -eq 0 ] || fehler "Bitte als root ausführen (der Runner ruft sudo -n /usr/local/sbin/wais-deploy ...)."
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
else
  [ "$(id -u)" -ne 0 ] || fehler "Der Probelauf (WAIS_DEPLOY_WURZEL) läuft nie als root."
  case "$WURZEL" in
    /|*//*|*/..|*/../*|*/.|*/./*|*[!A-Za-z0-9._/-]*|[!/]*)
      fehler "WAIS_DEPLOY_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich und Schrägstrich sein." ;;
  esac
  PATH="$WURZEL/attrappen:$PATH"
  # Nur im Probelauf: Dateisysteme ohne Unix-Rechte (Git Bash unter Windows) lassen chmod scheitern; das ist dort kein Fehler
  chmod() { command chmod "$@" 2>/dev/null || true; }
  install() { if [ "$1" = -d ]; then shift; if [ "$1" = -m ]; then shift 2; fi; mkdir -p "$@"; else command install "$@"; fi; }
fi
export PATH
ROOT_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ETC="$WURZEL/etc/wais-deploy"
QUELLE_CONF="$ETC/quelle.conf"
DEPLOY_KEY="$ETC/deploy_key"
KNOWN_HOSTS="$ETC/known_hosts"
DATEN="$WURZEL/var/lib/wais-deploy"
REPO="$DATEN/repo.git"
STAENDE="$DATEN/staende"
ZUSTAND="$DATEN/zustand"
LOGORDNER="$WURZEL/var/log/wais-deploy"
PROTOKOLL="$LOGORDNER/protokoll.log"
RUN="$WURZEL/run/wais-deploy"
SPERRE="$RUN/lock"
CADDY_SPERRE="$WURZEL/run/wamo-labor-geraete/lock"
KERN_APP="$WURZEL/opt/wamo-core"
SLOT_INC="$WURZEL/home/wamocon/wamo-tls/caddy/etc/kern/slot.inc"
KERN_RUN="$WURZEL/run/wamo-core"
LABOR_TOKEN="$WURZEL/etc/wamo-labor/kern-token"
UI_BENUTZER=wamocon
STAND_GRUPPE=wamocon
STANDARD_QUELLE="git@github.com:Wamocon/w.a.i.s.git"
BEHALTEN=5
KERN_BEWAEHRUNG_MIN=30
UI_BEWAEHRUNG_S=120
UI_FEHLERQUOTE=5
CADDY_WARTEN_S=120
PROBE_PAUSE_S=2
if [ -n "$WURZEL" ]; then PROBE_PAUSE_S=0; fi
STAND=""
if [ -n "$COMMIT" ]; then STAND="$STAENDE/$COMMIT"; fi
SKRIPTE=""
ARBEIT=""
AUSGABE_DATEI=""
AUSGABE=""
START_S="$(date +%s)"

# ---------- Protokoll und Abschluss
protokoll_starten() {
  install -d -m 0750 "$LOGORDNER"
  if [ -z "$WURZEL" ]; then chgrp adm "$LOGORDNER" 2>/dev/null || true; fi
  [ ! -L "$PROTOKOLL" ] || fehler "$PROTOKOLL ist ein symbolischer Link: abgelehnt."
  touch "$PROTOKOLL"
  chmod 0640 "$PROTOKOLL"
  if [ -z "$WURZEL" ]; then chgrp adm "$PROTOKOLL" 2>/dev/null || true; fi
  # stdout und stderr bleiben getrennt (der Runner zeigt beide), beide landen im Protokoll
  exec > >(tee -a "$PROTOKOLL") 2> >(tee -a "$PROTOKOLL" >&2)
  local zusatz=""
  if [ "$TROCKEN" = ja ]; then zusatz=" --trocken"; fi
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) wais-deploy $BEFEHL${COMMIT:+ $COMMIT}${TEIL:+ $TEIL}$zusatz (Aufrufer: ${SUDO_USER:-$(id -un)})"
}

abschluss() {
  local rc=$?
  set +e
  if [ -n "$AUSGABE_DATEI" ]; then rm -f "$AUSGABE_DATEI"; fi
  if [ -n "$ARBEIT" ]; then rm -rf "$ARBEIT"; fi
  echo "==== Ende $BEFEHL: Rückgabe $rc nach $(( $(date +%s) - START_S )) s"
  logger -t wais-deploy "befehl=$BEFEHL commit=${COMMIT:-keiner} teil=${TEIL:-keiner} trocken=$TROCKEN rueckgabe=$rc" 2>/dev/null
  exit "$rc"
}

ergebnis() { local kv; for kv in "$@"; do echo "WAIS $kv"; done; }

# ---------- Sperren
sperre() {
  install -d -m 0700 "$RUN"
  [ ! -L "$SPERRE" ] || fehler "$SPERRE ist ein symbolischer Link: abgelehnt."
  exec 8>"$SPERRE"
  flock -n 8 || vorbedingung "Ein anderer Lauf von wais-deploy hält die Sperre $SPERRE."
}

caddy_sperre_nehmen() {
  mkdir -p "$(dirname "$CADDY_SPERRE")"
  [ ! -L "$CADDY_SPERRE" ] || fehler "$CADDY_SPERRE ist ein symbolischer Link: abgelehnt."
  exec 9>"$CADDY_SPERRE"
  if ! flock -w "$CADDY_WARTEN_S" 9; then
    exec 9>&-
    vorbedingung "Die gemeinsame Caddy-Sperre $CADDY_SPERRE war $CADDY_WARTEN_S Sekunden belegt (Labor-Dienste): nichts geschaltet, bitte wiederholen."
  fi
}
caddy_sperre_loesen() { exec 9>&-; }

# ---------- Zustand (Dateien key=wert, nie gesourct)
zustand_schreiben() {   # $1 Name, danach key=wert
  local name="$1" tmp
  shift
  install -d -m 0700 "$ZUSTAND"
  tmp="$(mktemp "$ZUSTAND/.$name.XXXXXX")"
  printf '%s\n' "$@" "zeit=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$ZUSTAND/$name"
}

zustand_wert() {   # $1 Name, $2 Schlüssel: gibt den Wert aus oder nichts
  local datei="$ZUSTAND/$1" zeile
  if [ ! -f "$datei" ]; then return 0; fi
  while IFS= read -r zeile || [ -n "$zeile" ]; do
    [[ "$zeile" =~ ^([a-z]+)=([A-Za-z0-9._:-]*)$ ]] || fehler "$datei: ungültige Zeile."
    if [ "${BASH_REMATCH[1]}" = "$2" ]; then echo "${BASH_REMATCH[2]}"; return 0; fi
  done < "$datei"
}

# ---------- Quelle: eigener Spiegel, nur origin/main zählt
QUELLE_URL=""; QUELLE_ART=""
quelle_lesen() {
  local zeile besitzer modus
  QUELLE_URL="$STANDARD_QUELLE"
  if [ -f "$QUELLE_CONF" ]; then
    if [ -z "$WURZEL" ]; then
      read -r besitzer modus < <(stat -c '%u %a' "$QUELLE_CONF")
      if [ "$besitzer" != 0 ] || (( 8#$modus & 8#022 )); then
        fehler "$QUELLE_CONF muss root gehören und darf für Gruppe und andere nicht beschreibbar sein."
      fi
    fi
    while IFS= read -r zeile || [ -n "$zeile" ]; do
      zeile="${zeile%$'\r'}"
      case "$zeile" in
        ''|'#'*) ;;
        QUELLE_URL=*) QUELLE_URL="${zeile#QUELLE_URL=}" ;;
        *) fehler "$QUELLE_CONF: unbekannte Zeile (erlaubt ist nur QUELLE_URL=...)." ;;
      esac
    done < "$QUELLE_CONF"
  fi
  if [[ "$QUELLE_URL" =~ ^git@github\.com:Wamocon/[A-Za-z0-9._-]{1,100}\.git$ ]]; then QUELLE_ART=ssh
  elif [[ "$QUELLE_URL" =~ ^https://github\.com/Wamocon/[A-Za-z0-9._-]{1,100}\.git$ ]]; then QUELLE_ART=https
  elif [ -n "$WURZEL" ] && [[ "$QUELLE_URL" =~ ^/[A-Za-z0-9._/-]{1,200}$ ]]; then QUELLE_ART=lokal
  else fehler "QUELLE_URL ist ungültig (erlaubt: git@github.com:Wamocon/<repo>.git oder https://github.com/Wamocon/<repo>.git)."
  fi
}

git_umgebung() {   # Umgebung für git: keine Konfiguration des Systems oder eines Benutzers, keine Rückfragen
  if [ -z "$WURZEL" ]; then
    GIT_UMG=(env -i "PATH=$ROOT_PATH" "HOME=$DATEN" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0)
  else
    GIT_UMG=(env "HOME=$DATEN" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0)
  fi
  if [ "$QUELLE_ART" = ssh ]; then
    GIT_UMG+=("GIT_SSH_COMMAND=ssh -F /dev/null -i $DEPLOY_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null")
  fi
}
git_q() { "${GIT_UMG[@]}" git -C "$REPO" "$@"; }

quelle_holen() {
  quelle_lesen
  git_umgebung
  if [ "$QUELLE_ART" = ssh ]; then
    [ -f "$DEPLOY_KEY" ] || vorbedingung "$DEPLOY_KEY fehlt (wais-runner-einrichten.sh einrichten legt ihn an; danach als Deploy-Key in GitHub eintragen)."
    [ -s "$KNOWN_HOSTS" ] || vorbedingung "$KNOWN_HOSTS fehlt (wais-runner-einrichten.sh einrichten)."
  fi
  install -d -m 0750 "$DATEN"
  if [ -z "$WURZEL" ]; then chgrp "$STAND_GRUPPE" "$DATEN"; fi
  if [ ! -d "$REPO" ]; then
    "${GIT_UMG[@]}" git init --bare -q "$REPO"
    chmod 0700 "$REPO"
  fi
  if git_q remote get-url origin >/dev/null 2>&1; then git_q remote set-url origin "$QUELLE_URL"; else git_q remote add origin "$QUELLE_URL"; fi
  echo "== Quelle: origin/main frisch holen ($QUELLE_URL)"
  git_q fetch --quiet --prune --no-tags origin '+refs/heads/main:refs/remotes/origin/main' \
    || vorbedingung "origin ist nicht erreichbar oder verweigert den Zugang (Deploy-Key in GitHub eingetragen?)."
  echo "  origin/main steht auf $(git_q rev-parse refs/remotes/origin/main)"
}

commit_pruefen() {
  git_q cat-file -e "$COMMIT^{commit}" 2>/dev/null || vorbedingung "Commit $COMMIT gibt es in origin/main nicht."
  git_q merge-base --is-ancestor "$COMMIT" refs/remotes/origin/main \
    || vorbedingung "Commit $COMMIT ist nicht in origin/main enthalten: ausgerollt werden nur gemergte Stände."
  echo "  Commit $COMMIT ist in origin/main enthalten"
}

VERSION_RE='^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$'
version_aus() {   # stdin: pyproject.toml des Kerns, Ausgabe X.Y.Z
  local v
  v="$(tr -d '\r' | sed -n 's/^version = "\([0-9.]*\)"$/\1/p' | head -n 1)"
  [[ "$v" =~ $VERSION_RE ]] || fehler "voice-core/pyproject.toml: Version fehlt oder ist ungültig."
  echo "$v"
}
release_von_git() { local v; v="$(git_q show "$COMMIT:voice-core/pyproject.toml" | version_aus)"; echo "v$v-${COMMIT:0:7}"; }
release_von_stand() { local v; v="$(version_aus < "$STAND/kern/pyproject.toml")"; echo "v$v-${COMMIT:0:7}"; }

# Für test-* und prod-*: Commit frisch in origin/main und als Stand verteilt
stand_pruefen() {
  quelle_holen
  commit_pruefen
  [ -d "$STAND" ] || vorbedingung "Stand $COMMIT ist nicht verteilt: erst die Stufe dev (verteilen)."
  SKRIPTE="$STAND"
}

# Für ausleiten, rueckweg, rauchtest, status: die Betriebsskripte des letzten prod-Laufs, sonst des zuletzt verteilten Standes
skripte_letzter() {
  local c
  c="$(zustand_wert letzter-prod commit)"
  if [ -z "$c" ] || [ ! -d "$STAENDE/$c" ]; then c="$(zustand_wert letzter-verteilt commit)"; fi
  if [ -z "$c" ] || [ ! -d "$STAENDE/$c" ]; then vorbedingung "Noch kein Stand verteilt (Stufe dev)."; fi
  SKRIPTE="$STAENDE/$c"
}

# ---------- Aufrufe der Betriebsskripte (leere Umgebung, ohne die Dateikennungen der Sperren)
slots() {
  if [ -n "$WURZEL" ]; then bash "$WURZEL/attrappen/wamo-core-slots.sh" "$@" 8>&- 9>&-; return; fi
  ( cd / && env -i "PATH=$ROOT_PATH" HOME=/root LANG=C.UTF-8 bash "$SKRIPTE/wamo-core-slots.sh" "$@" ) 8>&- 9>&-
}
oberflaeche() {   # als wamocon, wie vom PC aus (das Skript lehnt andere Benutzer ab)
  if [ -n "$WURZEL" ]; then bash "$WURZEL/attrappen/wamo-ui-umschalten.sh" "$@" 8>&- 9>&-; return; fi
  ( cd / && runuser -u "$UI_BENUTZER" -- env -i PATH=/usr/local/bin:/usr/bin:/bin "HOME=/home/$UI_BENUTZER" LANG=C.UTF-8 \
      bash "$SKRIPTE/wamo-ui-umschalten.sh" "$@" ) 8>&- 9>&-
}
labor() {
  if [ -n "$WURZEL" ]; then bash "$WURZEL/attrappen/wamo-labor-einrichten.sh" "$@" 8>&- 9>&-; return; fi
  ( cd / && env -i "PATH=$ROOT_PATH" HOME=/root LANG=C.UTF-8 bash "$SKRIPTE/wamo-labor-einrichten.sh" "$@" ) 8>&- 9>&-
}

mit_ausgabe() {   # führt "$@" aus, zeigt die Ausgabe sofort und hält sie in $AUSGABE fest
  local rc=0
  "$@" 2>&1 | tee "$AUSGABE_DATEI" || rc=$?
  AUSGABE="$(cat "$AUSGABE_DATEI")"
  return "$rc"
}
slot_aus_ausgabe() { grep -E '^SLOT [ab]$' <<<"$AUSGABE" | tail -n 1 | cut -d' ' -f2 || true; }

# ---------- Kern: Slots lesen
anderer() { if [ "$1" = a ]; then echo b; else echo a; fi; }

aktiver_slot() {   # aus "probe" (letzte Zeile SLOT a|b, auch wenn der Slot gerade nicht gesund ist)
  local aus s
  aus="$(slots probe 2>/dev/null || true)"
  s="$(grep -E '^SLOT [ab]$' <<<"$aus" | tail -n 1 | cut -d' ' -f2 || true)"
  [ -n "$s" ] || fehler "Der aktive Slot ist nicht lesbar (wamo-core-slots.sh probe; slot.inc fehlt oder zeigt noch auf die alte Unit)."
  echo "$s"
}

# shellcheck disable=SC2034  # gelesen über ${!v} in rel_von und laeuft
REL_a="" REL_b="" LAEUFT_a=nein LAEUFT_b=nein
slots_lesen() {   # aus "status": "Slot a: /opt/wamo-core/releases/<name>  active"
  local aus s zeile ziel zustand
  aus="$(slots status)" || fehler "wamo-core-slots.sh status ist fehlgeschlagen."
  for s in a b; do
    zeile="$(grep -E "^Slot $s: " <<<"$aus" | head -n 1 || true)"
    [ -n "$zeile" ] || fehler "Slot $s fehlt in der Ausgabe von wamo-core-slots.sh status."
    zeile="${zeile#"Slot $s: "}"
    ziel="${zeile%%  *}"
    zustand="${zeile##*  }"
    if [ "$ziel" = "(leer)" ]; then ziel=""; else ziel="${ziel##*/}"; fi
    printf -v "REL_$s" '%s' "$ziel"
    case "$zustand" in
      active|activating|reloading|deactivating) printf -v "LAEUFT_$s" '%s' ja ;;
      *) printf -v "LAEUFT_$s" '%s' nein ;;
    esac
  done
}
rel_von() { local v="REL_$1"; echo "${!v}"; }
laeuft() { local v="LAEUFT_$1"; [ "${!v}" = ja ]; }
ist_auslaufend() { [ -f "$SLOT_INC" ] && grep -q "^handle /i/$1/start {" "$SLOT_INC"; }

slot_antwortet() {   # $1 Slot: dreimal 401 auf /start über den eigenen Socket (wie die Gesundheitsprobe von wamo-core-slots.sh)
  local i code
  for i in 1 2 3; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 --unix-socket "$KERN_RUN/core-$1.sock" http://localhost/start || true)"
    if [ "$code" != 401 ]; then echo "  Probe $i: Slot $1 antwortet mit ${code:-nichts} statt 401" >&2; return 1; fi
    if [ "$i" != 3 ]; then sleep "$PROBE_PAUSE_S"; fi
  done
  echo "  Slot $1 antwortet dreimal mit 401 (lebt, Zugangskontrolle geladen)"
}

release_vergleichen() {   # ein vorhandenes Release muss genau die Dateien des Standes tragen (Releases werden nie überschrieben)
  local ziel="$KERN_APP/releases/$1/voice-core" a b f
  [ -d "$ziel" ] && [ -x "$KERN_APP/releases/$1/venv/bin/python" ] \
    || fehler "Release $1 gibt es, aber unvollständig: von Hand prüfen (wamo-core-slots.sh status)."
  a="$(cd "$STAND/kern" && ls -1 | sort)"
  b="$(cd "$ziel" && ls -1 | sort)"
  [ "$a" = "$b" ] || fehler "Release $1 gibt es schon mit anderen Dateien: nicht aus diesem Stand gebaut, von Hand prüfen."
  while IFS= read -r f; do
    cmp -s "$STAND/kern/$f" "$ziel/$f" || fehler "Release $1 gibt es schon mit anderem Inhalt ($f): nicht aus diesem Stand gebaut."
  done <<<"$a"
  echo "  Release $1 ist schon gebaut und gleicht dem Stand (wird nicht neu gebaut)"
}

# ---------- Oberfläche: Zustand lesen
UI_LIVE=""; UI_VORIGE=""; UI_COMMIT=""
UI_JSON_RE='^\{"live":"(blau|gruen|alt|keine|leer)","vorige":"(blau|gruen|alt|keine|leer)","seit":"[0-9TZ:-]*","version":"(v[0-9.]+)?","commit":"([0-9a-f]{40})?"\}$'
ui_zustand_lesen() {
  local aus
  aus="$(oberflaeche status --json 2>/dev/null | tail -n 1)" || fehler "wamo-ui-umschalten.sh status --json ist fehlgeschlagen."
  [[ "$aus" =~ $UI_JSON_RE ]] || fehler "Antwort von wamo-ui-umschalten.sh status --json ist nicht lesbar."
  UI_LIVE="${BASH_REMATCH[1]}"; UI_VORIGE="${BASH_REMATCH[2]}"; UI_COMMIT="${BASH_REMATCH[4]}"
}

# ---------- dev
cmd_pruefen_stand() {
  sperre
  quelle_holen
  commit_pruefen
  local name main kopf=nein
  name="$(release_von_git)"
  main="$(git_q rev-parse refs/remotes/origin/main)"
  if [ "$main" = "$COMMIT" ]; then kopf=ja; fi
  echo "Stand $COMMIT ist ausrollbar (Kern-Release $name, Kopf von main: $kopf)."
  ergebnis "commit=$COMMIT" "release=$name" "kopf=$kopf" "ergebnis=ok"
}

alte_staende_entfernen() {   # die fünf neuesten Stände bleiben, dazu der zuletzt verteilte und der des letzten prod-Laufs
  local s n=0 c_prod c_vert m
  c_prod="$(zustand_wert letzter-prod commit)"
  c_vert="$(zustand_wert letzter-verteilt commit)"
  while IFS= read -r s; do
    [[ "$s" =~ $COMMIT_RE ]] || continue
    if [ "$s" = "$c_prod" ] || [ "$s" = "$c_vert" ]; then continue; fi
    n=$((n + 1))
    if [ "$n" -gt "$BEHALTEN" ]; then rm -rf "${STAENDE:?}/$s"; echo "  alter Stand $s entfernt"; fi
  done < <(ls -1t "$STAENDE")
  for m in "$ZUSTAND"/test-kern-* "$ZUSTAND"/test-oberflaeche-*; do
    [ -f "$m" ] || continue
    s="${m##*-}"
    if [ ! -d "$STAENDE/$s" ]; then rm -f "$m"; fi
  done
}

cmd_verteilen() {
  sperre
  quelle_holen
  commit_pruefen
  local name tmp f n
  name="$(release_von_git)"
  if [ -d "$STAND" ]; then
    echo "Stand $COMMIT ist schon verteilt ($STAND)."
    if [ "$TROCKEN" = nein ]; then zustand_schreiben letzter-verteilt "commit=$COMMIT"; fi
    ergebnis "commit=$COMMIT" "release=$name" "ergebnis=ok"
    return 0
  fi
  if [ "$TROCKEN" = ja ]; then
    echo "Trockenlauf: würde infra/sokrates2, die Laufzeitdateien von voice-core (kern/) und ui/ aus $COMMIT nach $STAND legen."
    ergebnis "commit=$COMMIT" "release=$name" "ergebnis=trocken"
    return 0
  fi
  echo "== Stand $COMMIT ablegen"
  install -d -m 0750 "$STAENDE"
  if [ -z "$WURZEL" ]; then chown "root:$STAND_GRUPPE" "$STAENDE"; fi
  find "$STAENDE" -mindepth 1 -maxdepth 1 -name '.neu.*' -exec rm -rf {} +
  tmp="$(mktemp -d "$STAENDE/.neu.XXXXXX")"
  ARBEIT="$tmp"
  mkdir "$tmp/roh" "$tmp/stand"
  git_q archive --format=tar "$COMMIT" -- infra/sokrates2 voice-core ui | tar -x -C "$tmp/roh" --no-same-owner
  # Betriebsskripte wie ~/wamo-infra, Kern-Dateien wie "verteilen" vom PC (voice-core/*.py ohne Tests, pyproject.toml, uv.lock)
  cp -R "$tmp/roh/infra/sokrates2/." "$tmp/stand/"
  mkdir -p "$tmp/stand/kern"
  for f in "$tmp/roh/voice-core/"*.py; do
    n="$(basename "$f")"
    case "$n" in test_*|conftest.py) continue ;; esac
    cp "$f" "$tmp/stand/kern/$n"
  done
  cp "$tmp/roh/voice-core/pyproject.toml" "$tmp/roh/voice-core/uv.lock" "$tmp/stand/kern/"
  mv "$tmp/roh/ui" "$tmp/stand/ui"
  # Ausschlüsse wie scripts/wamo_ui_sokrates2.py (nichts Gebautes, keine Abhängigkeiten, nie eine .env)
  find "$tmp/stand/ui" -type d \( -name node_modules -o -name .next -o -name out -o -name coverage -o -name .git \
    -o -name .vscode -o -name __pycache__ \) -prune -exec rm -rf {} +
  find "$tmp/stand/ui" -type f \( -name '.env*' -o -name '*.log' -o -name '*.tsbuildinfo' -o -name next-env.d.ts \) -exec rm -f {} +
  find "$tmp/stand" -type d -name __pycache__ -prune -exec rm -rf {} +
  [ -z "$(find "$tmp/stand" -type l -print -quit)" ] || fehler "Der Stand enthält symbolische Links: abgelehnt."
  for f in wamo-core-slots.sh wamo-ui-umschalten.sh wamo-labor-einrichten.sh wamo-ui/Dockerfile kern/bot.py kern/uv.lock ui/package.json; do
    [ -f "$tmp/stand/$f" ] || fehler "Im Stand fehlt $f."
  done
  printf 'WAMO_COMMIT=%s\nWAMO_SAUBER=ja\n' "$COMMIT" > "$tmp/stand/wamo-ui/bau.info"
  chmod -R u=rwX,go=rX "$tmp/stand"
  if [ -z "$WURZEL" ]; then chown -R root:root "$tmp/stand"; fi
  mv -T "$tmp/stand" "$STAND"
  rm -rf "$tmp"
  ARBEIT=""
  zustand_schreiben letzter-verteilt "commit=$COMMIT"
  echo "  abgelegt: $(find "$STAND/kern" -type f | wc -l) Kern-Dateien, $(find "$STAND/ui" -type f | wc -l) Dateien der Oberfläche"
  alte_staende_entfernen
  ergebnis "commit=$COMMIT" "release=$name" "ergebnis=ok"
}

# ---------- test
cmd_test_kern() {
  sperre
  stand_pruefen
  local name akt frei
  name="$(release_von_stand)"
  akt="$(aktiver_slot)"
  frei="$(anderer "$akt")"
  slots_lesen
  echo "== Kern-Release $name: aktiv ist Slot $akt ($(rel_von "$akt")), frei ist Slot $frei ($(rel_von "$frei"), läuft: $(laeuft "$frei" && echo ja || echo nein))"
  if [ "$(rel_von "$akt")" = "$name" ]; then
    echo "Release $name ist schon aktiv (Slot $akt): nichts zu bauen oder zu starten."
    if [ "$TROCKEN" = nein ]; then zustand_schreiben "test-kern-$COMMIT" "release=$name" "slot=$akt"; fi
    ergebnis "commit=$COMMIT" "release=$name" "slot=$akt" "ergebnis=schon-aktiv"
    return 0
  fi
  if [ "$TROCKEN" = ja ]; then
    if [ -d "$KERN_APP/releases/$name" ]; then echo "Trockenlauf: Release $name ist schon gebaut (würde mit dem Stand verglichen)."
    else echo "Trockenlauf: würde Release $name aus $STAND/kern bauen (wamo-core-slots.sh release)."; fi
    if laeuft "$frei" && [ "$(rel_von "$frei")" != "$name" ]; then
      if ist_auslaufend "$frei"; then echo "  Slot $frei läuft noch als auslaufende Instanz: test-kern bräche mit Exit 3 ab (erst ausleiten)."
      else echo "  Slot $frei trägt einen nie geschalteten Test-Stand: würde ausgeleitet (wamo-core-slots.sh ausleiten)."; fi
    fi
    echo "  würde $name auf Slot $frei starten (bereiten), ohne Umschalten, und den Slot dreimal prüfen"
    ergebnis "commit=$COMMIT" "release=$name" "slot=$frei" "ergebnis=trocken"
    return 0
  fi
  if laeuft "$frei" && [ "$(rel_von "$frei")" != "$name" ] && ist_auslaufend "$frei"; then
    vorbedingung "Slot $frei läuft noch als auslaufende Instanz ($(rel_von "$frei")) des letzten prod-Laufs: erst ausleiten (Workflow Ausrollen prod, Aktion ausleiten), frühestens 30 Minuten nach dem Schalten."
  fi
  if [ -d "$KERN_APP/releases/$name" ]; then
    release_vergleichen "$name"
  else
    echo "== Release $name bauen (eigenes venv aus uv.lock, Import-Probe)"
    slots release "$name" "$STAND/kern"
  fi
  if laeuft "$frei" && [ "$(rel_von "$frei")" != "$name" ]; then
    echo "== Slot $frei trägt den nie geschalteten Stand $(rel_von "$frei"): ausleiten"
    slots ausleiten || vorbedingung "Slot $frei ließ sich noch nicht ausleiten (Meldung oben): später erneut versuchen."
  fi
  echo "== Release $name im freien Slot $frei starten (ohne Umschalten)"
  mit_ausgabe slots bereiten "$name" || fehler "bereiten ist fehlgeschlagen: nichts umgeschaltet, Slot $akt bedient weiter."
  [ "$(slot_aus_ausgabe)" = "$frei" ] || fehler "bereiten meldet einen anderen Slot als $frei."
  echo "== Rauchtest des neuen Slots $frei"
  slot_antwortet "$frei" || fehler "Slot $frei antwortet nicht stabil: nichts umgeschaltet."
  zustand_schreiben "test-kern-$COMMIT" "release=$name" "slot=$frei"
  ergebnis "commit=$COMMIT" "release=$name" "slot=$frei" "ergebnis=ok"
}

cmd_test_oberflaeche() {
  sperre
  stand_pruefen
  local zeile farbe
  ui_zustand_lesen
  if [ "$UI_COMMIT" = "$COMMIT" ]; then
    # Nie die vorige Farbe mit demselben Stand überbauen: sie ist der schnelle Rückweg der live Fassung
    echo "Die live Farbe $UI_LIVE trägt schon $COMMIT: nichts zu bauen."
    if [ "$TROCKEN" = nein ]; then zustand_schreiben "test-oberflaeche-$COMMIT" "farbe=$UI_LIVE"; fi
    ergebnis "commit=$COMMIT" "farbe=$UI_LIVE" "ergebnis=schon-live"
    return 0
  fi
  if [ "$TROCKEN" = ja ]; then
    oberflaeche bauen --commit "$COMMIT" --sauber ja --trocken
    ergebnis "commit=$COMMIT" "ergebnis=trocken"
    return 0
  fi
  echo "== Oberfläche in der freien Farbe bauen und prüfen (ohne Umschalten)"
  mit_ausgabe oberflaeche bauen --commit "$COMMIT" --sauber ja || fehler "Bau oder Prüfung der Oberfläche fehlgeschlagen: die live Farbe ist unverändert."
  zeile="$(grep -E '^BEREIT farbe=(blau|gruen) version=[0-9.]+ commit=[0-9a-f]{40}$' <<<"$AUSGABE" | tail -n 1 || true)"
  [ -n "$zeile" ] || fehler "bauen meldet keine Zeile BEREIT."
  [ "${zeile##*commit=}" = "$COMMIT" ] || fehler "Die gebaute Farbe trägt nicht den Commit $COMMIT."
  farbe="${zeile#BEREIT farbe=}"; farbe="${farbe%% *}"
  zustand_schreiben "test-oberflaeche-$COMMIT" "farbe=$farbe"
  ergebnis "commit=$COMMIT" "farbe=$farbe" "ergebnis=ok"
}

# ---------- prod
cmd_prod_kern() {
  sperre
  stand_pruefen
  local name akt neu vorher
  name="$(release_von_stand)"
  [ -f "$ZUSTAND/test-kern-$COMMIT" ] || vorbedingung "Stand $COMMIT hat die Stufe test für den Kern nicht bestanden: erst Ausrollen test."
  akt="$(aktiver_slot)"
  slots_lesen
  vorher="$(rel_von "$akt")"
  if [ "$vorher" = "$name" ]; then
    echo "Release $name ist schon aktiv (Slot $akt): nichts umzuschalten."
    slots probe >/dev/null || fehler "Der aktive Slot $akt ist nicht gesund (wamo-core-slots.sh probe)."
    if [ "$TROCKEN" = nein ]; then zustand_schreiben letzter-prod "commit=$COMMIT"; fi
    ergebnis "commit=$COMMIT" "release=$name" "slot=$akt" "ergebnis=schon-aktiv"
    return 0
  fi
  neu="$(anderer "$akt")"
  if ! laeuft "$neu" || [ "$(rel_von "$neu")" != "$name" ]; then
    vorbedingung "Slot $neu läuft nicht mit $name (er trägt $(rel_von "$neu")): zuerst Ausrollen test für diesen Stand."
  fi
  if [ "$TROCKEN" = ja ]; then
    echo "Trockenlauf: würde neue Sitzungen von Slot $akt ($vorher) auf Slot $neu ($name) schalten (Nachlauf 60 Sekunden),"
    echo "  dann $KERN_BEWAEHRUNG_MIN Minuten bewähren (dreimal ungesund: automatisch zurück auf Slot $akt)."
    ergebnis "commit=$COMMIT" "release=$name" "slot=$neu" "vorher=$vorher" "ergebnis=trocken"
    return 0
  fi
  zustand_schreiben prod-vorher-kern "slot=$akt" "release=$vorher" "neu=$name" "commit=$COMMIT"
  echo "== Caddy auf Slot $neu schalten (Release $name), danach nimmt Slot $akt keine neue Sitzung mehr an"
  caddy_sperre_nehmen
  if ! mit_ausgabe slots schalten "$name"; then
    caddy_sperre_loesen
    fehler "Schalten fehlgeschlagen (Meldung oben). Zustand: wais-deploy status."
  fi
  caddy_sperre_loesen
  [ "$(slot_aus_ausgabe)" = "$neu" ] || fehler "schalten meldet einen anderen Slot als $neu."
  echo "== Bewährung $KERN_BEWAEHRUNG_MIN Minuten (dreimal nicht gesund heißt automatisch zurück auf Slot $akt)"
  if ! slots bewaehren "$KERN_BEWAEHRUNG_MIN"; then
    if [ "$(aktiver_slot 2>/dev/null || echo unbekannt)" = "$akt" ]; then
      ergebnis "commit=$COMMIT" "release=$name" "slot=$akt" "vorher=$vorher" "ergebnis=zurueckgenommen"
      echo "wais-deploy: Bewährung nicht bestanden, der Kern ist automatisch auf Slot $akt ($vorher) zurück." >&2
      exit 4
    fi
    handarbeit "Bewährung abgebrochen und der Kern ist nicht auf Slot $akt zurück: wais-deploy status, dann wais-deploy rueckweg kern."
  fi
  [ "$(aktiver_slot)" = "$neu" ] || fehler "Nach der Bewährung ist nicht Slot $neu aktiv."
  slots probe >/dev/null || fehler "Die Probe nach der Bewährung ist fehlgeschlagen."
  zustand_schreiben letzter-prod "commit=$COMMIT"
  ergebnis "commit=$COMMIT" "release=$name" "slot=$neu" "vorher=$vorher" "ergebnis=ok"
}

cmd_prod_oberflaeche() {
  sperre
  stand_pruefen
  local rc=0 farbe
  [ -f "$ZUSTAND/test-oberflaeche-$COMMIT" ] || vorbedingung "Stand $COMMIT hat die Stufe test für die Oberfläche nicht bestanden: erst Ausrollen test."
  farbe="$(zustand_wert "test-oberflaeche-$COMMIT" farbe)"
  ui_zustand_lesen
  if [ "$UI_COMMIT" = "$COMMIT" ]; then
    echo "Die live Farbe $UI_LIVE trägt schon $COMMIT: nichts umzuschalten."
    if [ "$TROCKEN" = nein ]; then zustand_schreiben letzter-prod "commit=$COMMIT"; fi
    ergebnis "commit=$COMMIT" "farbe=$UI_LIVE" "ergebnis=schon-live"
    return 0
  fi
  [ "$farbe" != "$UI_LIVE" ] || vorbedingung "Die in test gebaute Farbe $farbe ist schon live, trägt aber nicht $COMMIT: erst Ausrollen test erneut."
  if [ "$TROCKEN" = ja ]; then
    oberflaeche umschalten --ohne-bau --commit "$COMMIT" --bewaehrung "$UI_BEWAEHRUNG_S" --fehlerquote "$UI_FEHLERQUOTE" --trocken
    ergebnis "commit=$COMMIT" "farbe=$farbe" "vorher=$UI_LIVE" "ergebnis=trocken"
    return 0
  fi
  zustand_schreiben prod-vorher-oberflaeche "farbe=$UI_LIVE" "commit=$UI_COMMIT" "neu=$farbe"
  echo "== Oberfläche umschalten: live $UI_LIVE -> $farbe (Bewährung $UI_BEWAEHRUNG_S Sekunden, Fehlerquote höchstens $UI_FEHLERQUOTE Prozent)"
  caddy_sperre_nehmen
  oberflaeche umschalten --ohne-bau --commit "$COMMIT" --bewaehrung "$UI_BEWAEHRUNG_S" --fehlerquote "$UI_FEHLERQUOTE" || rc=$?
  caddy_sperre_loesen
  case "$rc" in
    0) ;;
    3) fehler "Prüfung vor dem Umschalten fehlgeschlagen: nichts umgeschaltet, $UI_LIVE bleibt live." ;;
    4) ergebnis "commit=$COMMIT" "farbe=$UI_LIVE" "ergebnis=zurueckgenommen"
       echo "wais-deploy: Bewährung der Oberfläche nicht bestanden, automatisch zurück auf $UI_LIVE." >&2
       exit 4 ;;
    5|6) handarbeit "Umschalten und Rückweg der Oberfläche fehlgeschlagen: wais-deploy status, Notanker: sudo wamo-anker rueckweg ui." ;;
    *) fehler "wamo-ui-umschalten.sh umschalten endete mit $rc." ;;
  esac
  ui_zustand_lesen
  [ "$UI_COMMIT" = "$COMMIT" ] || fehler "Nach dem Umschalten trägt die live Farbe $UI_LIVE den Commit ${UI_COMMIT:-keinen} statt $COMMIT."
  zustand_schreiben letzter-prod "commit=$COMMIT"
  ergebnis "commit=$COMMIT" "farbe=$UI_LIVE" "ergebnis=ok"
}

cmd_ausleiten() {
  sperre
  skripte_letzter
  if [ "$TROCKEN" = ja ]; then
    slots status
    echo "Trockenlauf: würde wamo-core-slots.sh ausleiten aufrufen (beendet die auslaufende Instanz nur ohne Sitzung,"
    echo "  frühestens 30 Minuten nach dem Schalten und nach 15 Minuten Ruhe in ihrem Journal)."
    ergebnis "ergebnis=trocken"
    return 0
  fi
  if ! slots ausleiten; then
    ergebnis "ergebnis=spaeter"
    vorbedingung "Die alte Instanz lässt sich jetzt noch nicht ausleiten (Meldung oben): später erneut versuchen, nichts erzwingen."
  fi
  ergebnis "ergebnis=ok"
}

rueckweg_oberflaeche() {
  local ziel rc=0
  ziel="$(zustand_wert prod-vorher-oberflaeche farbe)"
  [[ "$ziel" =~ ^(blau|gruen|alt)$ ]] || vorbedingung "Für die Oberfläche ist kein früherer Stand vermerkt (noch kein prod-Lauf)."
  ui_zustand_lesen
  if [ "$UI_LIVE" = "$ziel" ]; then echo "Oberfläche: $ziel ist schon live, nichts zu tun."; ergebnis "farbe=$ziel" "oberflaeche=schon"; return 0; fi
  [ "$UI_VORIGE" = "$ziel" ] \
    || handarbeit "Oberfläche: vermerkt ist $ziel, die vorige Farbe ist aber $UI_VORIGE: kein schneller Rückweg (Notanker: sudo wamo-anker rueckweg ui)."
  if [ "$TROCKEN" = ja ]; then oberflaeche zurueck --trocken; ergebnis "farbe=$ziel" "oberflaeche=trocken"; return 0; fi
  echo "== Oberfläche zurück: live $UI_LIVE -> $ziel"
  caddy_sperre_nehmen
  oberflaeche zurueck || rc=$?
  caddy_sperre_loesen
  [ "$rc" = 0 ] || handarbeit "Rückweg der Oberfläche fehlgeschlagen ($rc): Notanker sudo wamo-anker rueckweg ui."
  ui_zustand_lesen
  [ "$UI_LIVE" = "$ziel" ] || handarbeit "Nach dem Rückweg ist $UI_LIVE live statt $ziel."
  ergebnis "farbe=$ziel" "oberflaeche=zurueck"
}

rueckweg_kern() {
  local zrel zslot akt andere
  zrel="$(zustand_wert prod-vorher-kern release)"
  zslot="$(zustand_wert prod-vorher-kern slot)"
  [ -n "$zrel" ] && [[ "$zslot" =~ ^[ab]$ ]] || vorbedingung "Für den Kern ist kein früherer Stand vermerkt (noch kein prod-Lauf)."
  akt="$(aktiver_slot)"
  slots_lesen
  if [ "$(rel_von "$akt")" = "$zrel" ]; then echo "Kern: $zrel ist schon aktiv (Slot $akt), nichts zu tun."; ergebnis "release=$zrel" "kern=schon"; return 0; fi
  andere="$(anderer "$akt")"
  if [ "$andere" != "$zslot" ] || ! laeuft "$andere" || [ "$(rel_von "$andere")" != "$zrel" ]; then
    handarbeit "Kern: $zrel läuft nicht mehr auf Slot $zslot (schon ausgeleitet?): kein schneller Rückweg. Notanker: sudo wamo-anker rueckweg kern, oder Ausrollen test und prod für den früheren Stand."
  fi
  if [ "$TROCKEN" = ja ]; then
    echo "Trockenlauf: würde neue Sitzungen von Slot $akt ($(rel_von "$akt")) zurück auf Slot $andere ($zrel) schalten (wamo-core-slots.sh rueckweg-kern)."
    ergebnis "release=$zrel" "kern=trocken"
    return 0
  fi
  echo "== Kern zurück: Slot $akt -> Slot $andere ($zrel)"
  caddy_sperre_nehmen
  if ! slots rueckweg-kern; then caddy_sperre_loesen; handarbeit "rueckweg-kern ist fehlgeschlagen: Notanker sudo wamo-anker rueckweg kern."; fi
  caddy_sperre_loesen
  [ "$(aktiver_slot)" = "$andere" ] || handarbeit "Nach dem Rückweg ist nicht Slot $andere aktiv."
  ergebnis "release=$zrel" "slot=$andere" "kern=zurueck"
}

cmd_rueckweg() {
  sperre
  skripte_letzter
  # Umgekehrt zum Ausrollen: erst die Oberfläche, dann der Kern (die Oberfläche zeigt nie, was der Kern nicht kennt)
  case "$TEIL" in
    oberflaeche) rueckweg_oberflaeche ;;
    kern) rueckweg_kern ;;
    beides) rueckweg_oberflaeche; rueckweg_kern ;;
  esac
  ergebnis "ergebnis=ok"
}

cmd_rauchtest() {
  sperre
  skripte_letzter
  local ok=ja
  echo "== Kern: Probe des aktiven Slots"
  if slots probe; then echo "  gesund"; else echo "  NICHT gesund" >&2; ok=nein; fi
  echo "== Oberfläche: live Farbe"
  if ( ui_zustand_lesen; [ -n "$UI_COMMIT" ] ); then
    ui_zustand_lesen
    echo "  live $UI_LIVE mit Commit $UI_COMMIT (vorige: $UI_VORIGE)"
  else
    echo "  Die live Farbe antwortet nicht mit einer Fassung." >&2; ok=nein
  fi
  echo "== Labor-Dienst"
  if [ -f "$LABOR_TOKEN" ]; then
    if labor pruefen; then echo "  in Ordnung"; else echo "  Rauchtest des Labor-Dienstes fehlgeschlagen" >&2; ok=nein; fi
  else
    echo "  nicht eingerichtet, übersprungen"
  fi
  if [ "$ok" = ja ]; then ergebnis "ergebnis=ok"; else ergebnis "ergebnis=fehler"; fehler "Rauchtest nicht bestanden."; fi
}

cmd_status() {
  local c m
  echo "== Ausroll-Einstieg (wais-deploy)"
  if [ -e "$SPERRE" ] && ! flock -n "$SPERRE" true 2>/dev/null; then echo "  Sperre: belegt (ein Lauf ist aktiv)"; else echo "  Sperre: frei"; fi
  echo "  zuletzt verteilt: $(zustand_wert letzter-verteilt commit)"
  echo "  letzter prod-Lauf: $(zustand_wert letzter-prod commit)"
  echo "  vor dem letzten prod-Lauf, Kern: $(zustand_wert prod-vorher-kern release) (Slot $(zustand_wert prod-vorher-kern slot))"
  echo "  vor dem letzten prod-Lauf, Oberfläche: $(zustand_wert prod-vorher-oberflaeche farbe) $(zustand_wert prod-vorher-oberflaeche commit)"
  for m in "$ZUSTAND"/test-kern-* "$ZUSTAND"/test-oberflaeche-*; do
    if [ -f "$m" ]; then echo "  test bestanden: ${m##*/}"; fi
  done
  if [ -d "$STAENDE" ]; then echo "  Stände: $(find "$STAENDE" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | wc -l)"; fi
  if [ -d "$REPO" ]; then
    quelle_lesen
    git_umgebung
    c="$(git_q rev-parse --verify --quiet refs/remotes/origin/main || true)"
    echo "  Spiegel: $QUELLE_URL, origin/main zuletzt geholt: ${c:-noch nie}"
  fi
  if ( skripte_letzter ) >/dev/null 2>&1; then
    skripte_letzter
    echo "== Kern (wamo-core-slots.sh status aus ${SKRIPTE##*/})"
    slots status || true
    echo "== Oberfläche"
    oberflaeche status || true
  fi
}

# ---------- Ablauf
trap abschluss EXIT
trap 'echo "wais-deploy: abgebrochen" >&2; exit 130' INT TERM
protokoll_starten
install -d -m 0700 "$RUN"
AUSGABE_DATEI="$(mktemp "$RUN/ausgabe.XXXXXX")"
case "$BEFEHL" in
  pruefen-stand) cmd_pruefen_stand ;;
  verteilen) cmd_verteilen ;;
  test-kern) cmd_test_kern ;;
  test-oberflaeche) cmd_test_oberflaeche ;;
  prod-kern) cmd_prod_kern ;;
  prod-oberflaeche) cmd_prod_oberflaeche ;;
  ausleiten) cmd_ausleiten ;;
  rueckweg) cmd_rueckweg ;;
  rauchtest) cmd_rauchtest ;;
  status) cmd_status ;;
esac
