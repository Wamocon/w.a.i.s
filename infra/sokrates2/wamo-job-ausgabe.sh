#!/bin/bash
# Sandbox-Schritt ausgabe des persönlichen GitHub-Wegs (Plan C, docs/persoenliche-zugaenge.md C.5 Laufende 1, C.5.2).
# Installiert als /opt/wamo/waechter/wamo-job-ausgabe.sh (root:wamo 0750) durch wamo-job-einrichten.sh. Läuft NUR in der Sandbox
# (wamo-job.sh --modus ausgabe): ohne Netz, ohne Token, Projektordner NUR LESEND, /run/wamo/ausgabe beschreibbar (vom Dispatcher geleert).
# Vorher hat der Dispatcher das Projekt entschärft (Hooks, .git/config nur mit Allowlist).
#
#   wamo-job-ausgabe.sh --auftrag <job> --basis <40 Hex>
#       schreibt die Commits des Zweigs wamo/<job> seit der Basis als /run/wamo/ausgabe/aenderung.bundle (höchstens 201 Commits: mehr weist
#       die Prüfung mit zu_viele_commits ab) und /run/wamo/ausgabe/status.json mit genau einer ganzen Zahl (Dateien, die nicht committet
#       sind, wamo_job_github._status_lesen). Kein Bundle heißt Status keine (der Zweig fehlt oder hat keine Commits über der Basis). Fehlt die Basis im Repo
#       (etwa eine umgeschriebene Geschichte), geht der Zweig ohne Untergrenze ins Bundle; die Prüfung meldet dann basis_fehlt.
# Exit 0 ok (auch ohne Bundle), 2 falsche Aufrufform, 70 Fehler.
set -euo pipefail
umask 077

fehler() { echo "wamo-job-ausgabe.sh: $*" >&2; exit 70; }
aufruf() { echo "wamo-job-ausgabe.sh: $*" >&2; exit 2; }

JOB="" BASIS=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --auftrag) JOB=${2-}; shift 2 || aufruf "--auftrag braucht einen Wert" ;;
    --basis) BASIS=${2-}; shift 2 || aufruf "--basis braucht einen Wert" ;;
    *) aufruf "unbekanntes Argument" ;;
  esac
done
[[ $JOB =~ ^[0-9a-f]{16,32}$ ]] || aufruf "Auftrags-ID ungültig"
[[ $BASIS =~ ^[0-9a-f]{40}$ ]] || aufruf "Basis ungültig (40 Hexzeichen)"

A=/run/wamo/ausgabe
P=$PWD
[ "$P" = "$(readlink /run/wamo/projekt)" ] && [[ $P == /srv/wamo/projekte/* ]] || fehler "nicht im Projektordner der Sandbox"
[ -d "$A" ] && [ ! -L "$A" ] || fehler "der Ordner ausgabe fehlt"
[ -z "$(find -P "$A" -mindepth 1 -maxdepth 1 -print -quit)" ] || fehler "der Ordner ausgabe ist nicht leer"

# git ohne Hooks, fsmonitor, Wartung und optionale Sperren (das Projekt ist ohnehin nur lesend)
G=(git --no-optional-locks -c core.hooksPath=/dev/null -c core.fsmonitor=false -c gc.auto=0 -c maintenance.auto=false
   -c protocol.allow=never -c credential.helper= -c submodule.recurse=false -c core.untrackedCache=false)
ZWEIG="refs/heads/wamo/$JOB"

ungesichert=0
if "${G[@]}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Nicht committete Dateien (geänderte, neue und gelöschte), gezählt über die NUL-getrennten Einträge der Kurzform
  ungesichert=$("${G[@]}" status --porcelain=v1 -z --untracked-files=all 2>/dev/null | tr -cd '\0' | wc -c) || ungesichert=0
fi
[[ $ungesichert =~ ^[0-9]{1,9}$ ]] || ungesichert=0

if "${G[@]}" rev-parse -q --verify "$ZWEIG^{commit}" >/dev/null 2>&1; then
  if "${G[@]}" cat-file -e "$BASIS^{commit}" 2>/dev/null; then
    neu=$("${G[@]}" rev-list --count "$ZWEIG" "^$BASIS")
    if [ "$neu" -gt 0 ]; then
      "${G[@]}" bundle create --quiet "$A/aenderung.bundle" --max-count=201 "$ZWEIG" "^$BASIS" || fehler "Bundle nicht erstellbar"
    fi
  else
    "${G[@]}" bundle create --quiet "$A/aenderung.bundle" --max-count=201 "$ZWEIG" || fehler "Bundle nicht erstellbar"
  fi
fi
printf '%d\n' "$ungesichert" > "$A/status.json"
echo "ausgabe ok"
