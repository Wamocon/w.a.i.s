#!/bin/bash
# Sandbox-Schritt klon des persönlichen GitHub-Wegs (Plan C, docs/persoenliche-zugaenge.md C.5 Start 5 und Folgelauf, C.5.2).
# Installiert als /opt/wamo/waechter/wamo-job-klon.sh (root:wamo 0750) durch wamo-job-einrichten.sh. Läuft NUR in der Sandbox
# (wamo-job.sh --modus klon): ohne Netz, ohne Token, Projektordner beschreibbar (Arbeitsordner), /run/wamo/basis.git und
# /run/wamo/letztes.bundle nur lesend. Der Dispatcher entschärft den Projektordner danach (projekt_entschaerfen) und schreibt den Eigner.
#
#   wamo-job-klon.sh --repo <owner/name> --auftrag <job> --basis <40 Hex> [--bundle]
#       leert den Projektordner (Rechte vorher setzen, nie Links folgen), klont aus /run/wamo/basis.git ohne Hardlinks und ohne Vorlage,
#       setzt origin auf https://github.com/<repo>.git und legt den Zweig wamo/<job> an: auf <basis> oder, mit --bundle, aus dem letzten
#       Bundle dieses Auftrags (Folgelauf in einem Ordner, den inzwischen ein anderer Auftrag gebaut hat). Hooks und fsmonitor sind aus
#       (GIT_CONFIG_* vom Läufer und -c hier).
#   wamo-job-klon.sh --probe
#       nur für den Rauchtest (in allen drei Modi erlaubt): eine JSON-Zeile mit den Namen der Umgebung und ob Netz geht, schreibt nichts.
# Exit 0 ok, 2 falsche Aufrufform, 70 Fehler (nie ein Inhalt aus dem Repo in der Meldung außer der von git selbst).
set -euo pipefail
umask 077

fehler() { echo "wamo-job-klon.sh: $*" >&2; exit 70; }
aufruf() { echo "wamo-job-klon.sh: $*" >&2; exit 2; }

# Probe (Rauchtest): Umgebungsnamen und Netz (TCP zu 1.1.1.1:443 und github.com:443 je höchstens 3 Sekunden)
probe() {
  local namen netz=zu github=zu
  namen=$(compgen -e | sort | awk 'BEGIN { ORS = "" } { printf "%s\"%s\"", (NR > 1 ? "," : ""), $0 }')
  if timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/443' 2>/dev/null; then netz=offen; fi
  if timeout 3 bash -c 'exec 3<>/dev/tcp/github.com/443' 2>/dev/null; then github=offen; fi
  printf '{"modus":"%s","umgebung":[%s],"netz":"%s","github":"%s"}\n' "${WAMO_MODUS:-?}" "$namen" "$netz" "$github"
}

if [ "${1-}" = --probe ]; then
  [ "$#" -eq 1 ] || aufruf "--probe kennt keine weiteren Angaben"
  probe
  exit 0
fi

REPO="" JOB="" BASIS="" BUNDLE=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO=${2-}; shift 2 || aufruf "--repo braucht einen Wert" ;;
    --auftrag) JOB=${2-}; shift 2 || aufruf "--auftrag braucht einen Wert" ;;
    --basis) BASIS=${2-}; shift 2 || aufruf "--basis braucht einen Wert" ;;
    --bundle) BUNDLE=1; shift ;;
    *) aufruf "unbekanntes Argument" ;;
  esac
done
[[ $REPO =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$ && $REPO != */. && $REPO != */.. ]] || aufruf "Repo ungültig"
[[ $JOB =~ ^[0-9a-f]{16,32}$ ]] || aufruf "Auftrags-ID ungültig"
[[ $BASIS =~ ^[0-9a-f]{40}$ ]] || aufruf "Basis ungültig (40 Hexzeichen)"

QUELLE=/run/wamo/basis.git
LETZTES=/run/wamo/letztes.bundle
P=$PWD
# Der Läufer startet im Projektordner; /run/wamo/projekt zeigt auf genau ihn. Nichts anderes wird geleert.
[ "$P" = "$(readlink /run/wamo/projekt)" ] && [[ $P == /srv/wamo/projekte/* ]] || fehler "nicht im Projektordner der Sandbox"
[ -d "$QUELLE" ] && [ ! -L "$QUELLE" ] || fehler "basis.git fehlt"
if [ "$BUNDLE" = 1 ]; then [ -f "$LETZTES" ] && [ ! -L "$LETZTES" ] || fehler "das letzte Bundle fehlt"; fi

# git ohne Hooks, fsmonitor, Wartung und fremde Protokolle; file nur für die lokale Quelle (kein Netz in dieser Sandbox)
G=(git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c gc.auto=0 -c maintenance.auto=false -c protocol.allow=never
   -c protocol.file.allow=always -c transfer.fsckObjects=true -c fetch.fsckObjects=true -c credential.helper= -c submodule.recurse=false
   -c core.symlinks=true -c init.defaultBranch=wamo)

# 1. Projektordner leeren: erst die Rechte der Ordner setzen (ein früherer Lauf kann sie entzogen haben), dann alles löschen, ohne Links
#    zu folgen (find -P, -delete arbeitet von unten nach oben). Der Ordner selbst bleibt (Mountpunkt).
find -P "$P" -mindepth 1 -type d ! -perm -u=rwx -exec chmod u+rwx {} + 2>/dev/null || true
find -P "$P" -mindepth 1 -delete || fehler "Projektordner lässt sich nicht leeren"
[ -z "$(find -P "$P" -mindepth 1 -maxdepth 1 -print -quit)" ] || fehler "Projektordner ist nicht leer"

# 2. Arbeitskopie aus basis.git: über das git-Protokoll (--no-local: keine Hardlinks, keine Kopie fremder Dateien aus dem Repo-Ordner),
#    ohne Vorlage (keine Hooks aus /usr/share/git-core/templates), ohne Checkout (erst der eigene Zweig)
"${G[@]}" clone --quiet --no-local --no-hardlinks --template= --no-checkout --no-tags -- "$QUELLE" "$P" || fehler "Klon aus basis.git gescheitert"
cd "$P"
"${G[@]}" remote set-url origin "https://github.com/$REPO.git"
"${G[@]}" cat-file -e "$BASIS^{commit}" || fehler "die Basis fehlt in basis.git"

# 3. Zweig wamo/<job>: auf der Basis oder aus dem letzten Bundle dieses Auftrags (genau dieser Zweig, sonst nichts)
ZWEIG="wamo/$JOB"
if [ "$BUNDLE" = 1 ]; then
  "${G[@]}" bundle verify --quiet "$LETZTES" >/dev/null || fehler "das letzte Bundle passt nicht zu basis.git"
  "${G[@]}" fetch --quiet --no-tags --no-write-fetch-head "$LETZTES" "+refs/heads/$ZWEIG:refs/heads/$ZWEIG" || fehler "Zweig aus dem Bundle nicht holbar"
  "${G[@]}" merge-base --is-ancestor "$BASIS" "refs/heads/$ZWEIG" || fehler "der Zweig im Bundle baut nicht auf der Basis auf"
  "${G[@]}" checkout --quiet "$ZWEIG"
else
  "${G[@]}" checkout --quiet -b "$ZWEIG" "$BASIS"
fi
# Der Standardzweig bleibt nur als Ref aus basis.git, damit der Agent nie auf ihm arbeitet
"${G[@]}" symbolic-ref HEAD "refs/heads/$ZWEIG"
echo "klon ok: $ZWEIG"
