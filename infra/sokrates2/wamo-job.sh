#!/usr/bin/env bash
# WAMO-Auftragsläufer auf Sokrates-2: führt einen Befehl (Claude Code oder den Wächter-Selbsttest) für
# genau einen Projektordner in einer bubblewrap-Sandbox aus, als Benutzer wamo, mit Zeit- und
# Ressourcengrenzen. Installiert als /opt/wamo/bin/wamo-job.sh (root:wamo 0750, /opt/wamo gehört root).
#
# Aufruf (durch wamo-job-dispatch oder den Rauchtest, immer als wamo):
#   wamo-job.sh --auftrag <job> --projekt <name> --platz <0-9> [--modus lauf|pruefen|klon|ausgabe|pruefung] [--zeitlimit <s>]
#               [--einheit-zusatz <wort>] -- befehl ...
#
# --platz (Pflicht, Dispatcher 9): der Platz, den der Dispatcher für diesen Lauf hält (Sperre platz-<n>). Er bestimmt den eigenen Teil der
# Entwicklungsports: 20000 + n*100 bis 20000 + n*100 + 99 (platz_ports). Nur dort darf der Lauf binden und verbinden (Landlock); in der
# Sandbox stehen die Grenzen in WAMO_PORT_VON und WAMO_PORT_BIS (nur im Auftragslauf; im Modus pruefen gibt es kein Netz).
#
# Modus pruefen (Befehl pruefen des Dispatchers, ein Befehl der Abnahme im Projekt): dieselbe Sandbox, nur ENGER. Eigener
# Netz-Namensraum ohne Netz (nichts hinein, nichts hinaus, auch nicht zum Loopback des Hosts), kein Claude (weder die
# Konfiguration des Auftrags noch Claude Code noch Plugins), kein Zustand des Auftrags (keine Freigaben, kein Socket), nur
# die Umgebungsnamen ERLAUBT_PRUEFEN_RE (Git-Hooks aus, nie ein Token), Zeitlimit höchstens 120 s, engere Grenzen für
# Speicher, Prozesse, CPU und Platz. Beschreibbar bleiben das Projekt, /tmp, .npm und .cache. Seccomp, Landlock, keine
# Capabilities und die Ausgangsregeln gelten unverändert. .npm und .cache sind dort nie die Ordner der Auftragsläufe (Auftragsordner,
# dauerhaft, je Auftrag geteilt mit Läufen mit Token), sondern je Lauf eigenes, leeres tmpfs mit Größengrenze (PRUEFEN_CACHE_MB):
# nichts bleibt zurück, nichts kommt aus einem früheren Lauf. Jede Grenze des Modus gilt nur, wenn sie enger ist als die des
# Auftragslaufs aus wamo-job.conf (von beiden der kleinere Wert, nie weiter).
#
# Modi klon, ausgabe und pruefung (Dispatcher 10, persönlicher GitHub-Weg, docs/persoenliche-zugaenge.md C.5.2): Sandbox-Schritte ohne Netz
# (immer --unshare-net), ohne Claude, ohne Werkzeuge aus dem Home (nur /usr: git, bash, python3), ohne Zustand des Auftrags, mit der engen
# Umgebung von pruefen (nur Git-Hooks aus, nie ein Token) und den engeren Grenzen von pruefen. Jeder Modus startet genau sein festes
# Programm aus /opt/wamo/waechter, sonst nichts (zusätzlich in allen drei Modi die Probe "wamo-job-klon.sh --probe" für den Rauchtest):
#   klon      wamo-job-klon.sh: Projekt beschreibbar, basis.git und das letzte Bundle (bundle.ein) nur lesend; Zeitlimit 300 s
#   ausgabe   wamo-job-ausgabe.sh: Projekt NUR LESEND, ausgabe/ beschreibbar; Zeitlimit 60 s, Dateien höchstens SCHRITT_DATEI_MAX_MB
#   pruefung  python3 -I wamo_job_auszug.py: kein Projekt, bundle.ein und basis.git nur lesend, ergebnis/ beschreibbar; 60 s, wie ausgabe
# In der Sandbox liegen diese Ordner unter /run/wamo (basis.git, letztes.bundle, bundle.ein, ausgabe, ergebnis). Die Zeitlimits stehen fest
# im Skript, wamo-job.conf kann sie nicht verlängern.
#
# Persönlicher GitHub-Weg im Auftragslauf (WAMO_GITHUB=persoenlich): die Sandbox bekommt keinen GitHub-Zugang. Der Läufer lässt dann genau die
# sechs Namen GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME, GIT_COMMITTER_EMAIL, WAMO_GITHUB und WAMO_ZWEIG zu (geprüft: Login und
# noreply-Adresse von GitHub, Zweig wamo/<job>) und entfernt zusätzlich zum Dispatcher jedes Dienst-Token (GH_TOKEN, Vercel, Supabase, Jira).
# Ohne WAMO_GITHUB fehlen alle sechs Namen, der Lauf ist genau wie in Dispatcher 9.
#
# Der Auftragsordner /srv/wamo/jobs/<job> muss vom Dispatcher vorbereitet sein (claude/, zustand/,
# zustand/approvals.json, etc/passwd, etc/group). Die Umgebung kommt vom Aufrufer; nur die Namen in
# ERLAUBT_RE gelangen in die Sandbox (Token nie über argv).
#
# Was die Sandbox sieht (alles andere existiert darin nicht):
#   /usr (ohne /usr/local/lib/wamo), /etc nur aus einer Allowlist (eigene passwd/group), /proc (eigener
#   PID-Namensraum), /dev (nur null, zero, random, tty usw.), /tmp (tmpfs), /srv/wamo als tmpfs mit:
#     .local/bin .local/share/claude         nur lesbar (Claude Code, uv, Werkzeuge aus uv tool)
#     .local/share/uv/tools .fnm .npm-global nur lesbar (mcp-atlassian, Node, MCP-Server aus npm -g)
#     .gitconfig                             nur lesbar
#     .npm .cache                            je Auftrag eigener Ordner auf der Platte (Modus pruefen: je Lauf eigenes,
#                                            leeres tmpfs, das mit dem Lauf verschwindet)
#     .claude                                je Auftrag (Sitzungen für --resume); Plugins aus
#                                            /opt/wamo/claude-plugins (ECC ohne Hooks, root-eigen, nur lesbar),
#                                            Plugin-Daten je Auftrag
#     projekte                               eigenes, schreibgeschütztes tmpfs; darin nur projekte/<projekt>,
#                                            beschreibbar, der einzige dauerhafte Arbeitsort
#   /opt/wamo/waechter                       Wächter und Abschottung, nur lesbar (derselbe Pfad wie auf dem Host)
#   /etc/claude-code/managed-settings.json   root-eigen, nur lesbar: Wächter-Hooks, Sperrliste, nur verwaltete Hooks
#   /run/wamo/zustand                        pending.jsonl beschreibbar, approvals.json nur lesbar
#   /run/wamo/projekt                        Verweis auf den Projektordner (für den Wächter)
#   Nicht sichtbar: /etc/wamo, /srv/wamo/.ssh, die echte Konfiguration von wamo (.claude.json, .config,
#   Vercel-Anmeldung), /home, /root, andere Aufträge und Projekte, Geräte (GPU, Platten), Prozesse außerhalb.
#   Alle Pfade, die Hooks und Wächter nutzen, liegen auf Mountpunkten oder der schreibgeschützten Wurzel; sie
#   lassen sich in der Sandbox weder umbenennen noch ersetzen (der Selbsttest prüft das bei jedem Lauf).
#
# Netz: bleibt an (Claude-API, GitHub, npm), aber ohne Wege ins Innere:
#   * Ausgangsfilter (wamo-egress.nft, Tabelle inet wamo_egress für uid wamo): Internet nur auf TCP 80 und 443,
#     DNS an 127.0.0.53, auf Loopback nur 127.0.0.1:20000-20999 (Entwicklungsserver der Aufträge) und 127.0.0.1:18090
#     (Proxy der Hausmodelle, für Landlock nur bei Zugangsart haus offen); IPv6, LAN,
#     Docker-Netze, private Netze und eigene Adressen sind abgewiesen. UDP nur zu 127.0.0.53:53.
#   * Landlock (abschottung.py): kein TCP zu Ports, auf denen der Host beim Start lauscht, und zu
#     NETZ_SPERRPORTS; im Bereich 20000-20999 binden und verbinden nur im eigenen Teil des Platzes (--platz);
#     keine abstrakten Unix-Sockets und keine Signale außerhalb der eigenen Landlock-Domäne (X11, andere Aufträge).
#   * seccomp (abschottung.py --seccomp-bpf, Pflicht): socket() mit MPTCP oder SCTP (umgingen Landlock) sowie
#     AF_PACKET, AF_VSOCK, AF_ALG; io_uring, keyctl, bpf, perf_event_open, userfaultfd, process_vm_*, mount und
#     Verwandte, unshare, setns, kexec, Kernelmodule; TCP Fast Open (MSG_FASTOPEN). clone3 bekommt ENOSYS.
#   Gleichzeitige Aufträge (Dispatcher 9, bis zu sechs, auch verschiedener Personen) teilen sich Benutzer und Netz-Namensraum. Getrennt
#   sind sie so: jeder Platz hat einen eigenen Teil der Entwicklungsports (Landlock, siehe oben; der Ausgangsfilter kennt nur die uid);
#   UDP auf Loopback weist der Ausgangsfilter ab; abstrakte Unix-Sockets und Signale sperrt Landlock (Scope je Domäne); eigene PID-,
#   IPC-, UTS-Namensräume; /tmp, /dev/shm (in /dev) und /srv/wamo sind je Sandbox eigene tmpfs; Zustand, Projekt und Caches je Auftrag.
#   Nicht getrennt: /proc/net zeigt die Sockets des gemeinsamen Netz-Namensraums (Portnummern, keine Inhalte), CPU, Speicher und Platte
#   teilen sich alle (Grenzen je Einheit, siehe unten).
#   Im Modus pruefen gilt das alles nicht: dort gibt es kein Netz (eigener Netz-Namensraum, siehe oben).
#
# Grenzen (systemd-run --user, Lingering für wamo): MemoryMax, MemorySwapMax=0, TasksMax, CPUQuota,
# niedrigere CPU- und IO-Gewichtung, RuntimeMaxSec; prlimit für offene Dateien, Dateigröße, keine
# Core-Dateien; timeout für das harte Zeitlimit. Werte in /opt/wamo/wamo-job.conf (root-eigen). Dort steht
# auch CLAUDE_VERSION: weicht die installierte Claude-Code-Version ab (Update), startet nichts, bis
# wamo-job-einrichten.sh erneut lief und der Rauchtest bestanden ist.
#
# Was die Sandbox nicht leistet: Die Token der Auftragsart liegen darin in der Umgebung. Ein feindlicher
# Agent kann sie lesen und mit curl oder einem eigenen Programm nutzen; der Wächter bremst das nur.
# Eine Plattenquote fehlt weiterhin: prlimit --fsize begrenzt nur die Größe einzelner Dateien, nicht den Platz, den ein Projekt,
# .npm oder .cache zusammen belegen. Im Modus pruefen sind .npm und .cache ein tmpfs mit Grenze; das Projekt bleibt ohne Quote. Als
# Eintrittsprüfung (keine Quote) misst der Dispatcher vor jedem Aufruf von pruefen den freien Platz (mindestens 2 GiB) und die
# Größe des Projekts (höchstens 2 GiB); ein einzelner Lauf kann in seinen 120 Sekunden trotzdem weiter Platz füllen.
set -euo pipefail
umask 077

APP=/opt/wamo
HEIM=/srv/wamo
JOBS=$HEIM/jobs
PROJEKTE=$HEIM/projekte
BWRAP=/usr/local/lib/wamo/bwrap
KONF=$APP/wamo-job.conf
WAECHTER_INNEN=/opt/wamo/waechter
SECCOMP=$APP/waechter/seccomp.bpf
PLUGINS=$APP/claude-plugins

# Standardwerte; wamo-job.conf (root:wamo 0640) darf sie überschreiben
ZEITLIMIT_S=1800
ZEITLIMIT_MAX_S=7200
SPEICHER_MAX=8G
CPU_QUOTA=400%
PROZESSE_MAX=1024
TMP_MB=4096
HEIM_TMP_MB=1024
DATEI_MAX_MB=4096
OFFENE_DATEIEN=8192
NETZ_SPERRPORTS="4000 8000 8001 11434"
NETZ_IMMER_ERLAUBT="53 80 443"
ABSCHOTTUNG=an
CLAUDE_VERSION=""
# Modus pruefen: engere Grenzen als der Auftragslauf (wamo-job.conf darf sie anpassen)
PRUEFEN_SPEICHER_MAX=4G
PRUEFEN_PROZESSE_MAX=256
PRUEFEN_CPU_QUOTA=200%
PRUEFEN_TMP_MB=1024
PRUEFEN_DATEI_MAX_MB=1024
PRUEFEN_CACHE_MB=256
if [ -r "$KONF" ]; then
  # shellcheck source=/dev/null
  . "$KONF"
fi
# Das Zeitlimit im Modus pruefen steht fest im Skript: wamo-job.conf kann es nicht verlängern
ZEITLIMIT_PRUEFEN_S=120
# Sandbox-Schritte des persönlichen GitHub-Wegs: ebenso fest (klon 300 s, ausgabe und pruefung je 60 s), Dateigröße bei ausgabe und pruefung
ZEITLIMIT_KLON_S=300
ZEITLIMIT_SCHRITT_S=60
SCHRITT_DATEI_MAX_MB=256

fehler() { echo "wamo-job.sh: $*" >&2; exit 70; }  # nie 2: das hieße "Hook sperrt"

# Größen und Quoten aus wamo-job.conf vergleichbar machen, damit der Modus pruefen nie weiter ist als der Auftragslauf
# (die Funktionen werden im Test einzeln in bash ausgeführt: jede steht mit ihrer ersten Zeile am Zeilenanfang und endet mit } allein)
in_bytes() {
  local n e
  [[ $1 =~ ^([0-9]{1,6})([KMGT]?)$ ]] || fehler "wamo-job.conf: Größe ungültig: $1"
  n=$((10#${BASH_REMATCH[1]})) e=${BASH_REMATCH[2]}
  case $e in
    K) n=$((n * 1024)) ;;
    M) n=$((n * 1024 * 1024)) ;;
    G) n=$((n * 1024 * 1024 * 1024)) ;;
    T) n=$((n * 1024 * 1024 * 1024 * 1024)) ;;
  esac
  echo "$n"
}
kleinere_groesse() {
  local a b
  a=$(in_bytes "$1") || exit 70
  b=$(in_bytes "$2") || exit 70
  if (( a <= b )); then echo "$1"; else echo "$2"; fi
}
kleinere_quote() {
  local a b
  [[ $1 =~ ^([0-9]{1,5})%$ ]] || fehler "wamo-job.conf: CPU-Quote ungültig: $1"
  a=$((10#${BASH_REMATCH[1]}))
  [[ $2 =~ ^([0-9]{1,5})%$ ]] || fehler "wamo-job.conf: CPU-Quote ungültig: $2"
  b=$((10#${BASH_REMATCH[1]}))
  if (( a <= b )); then echo "$1"; else echo "$2"; fi
}
kleiner_zahl() {
  [[ $1 =~ ^[0-9]{1,9}$ && $2 =~ ^[0-9]{1,9}$ ]] || fehler "wamo-job.conf: Zahl ungültig: $1 $2"
  if (( 10#$1 <= 10#$2 )); then echo "$1"; else echo "$2"; fi
}
# Modus pruefen: von jedem Wert aus wamo-job.conf (Auftragslauf) und dem festen Wert des Modus (PRUEFEN_*) gilt der kleinere. Die
# Standardwerte des Modus sind enger als die des Auftragslaufs; stellt die Konfiguration den Auftragslauf noch enger, gilt das auch hier.
pruefen_grenzen() {
  SPEICHER_MAX=$(kleinere_groesse "$SPEICHER_MAX" "$PRUEFEN_SPEICHER_MAX") || exit 70
  CPU_QUOTA=$(kleinere_quote "$CPU_QUOTA" "$PRUEFEN_CPU_QUOTA") || exit 70
  PROZESSE_MAX=$(kleiner_zahl "$PROZESSE_MAX" "$PRUEFEN_PROZESSE_MAX") || exit 70
  TMP_MB=$(kleiner_zahl "$TMP_MB" "$PRUEFEN_TMP_MB") || exit 70
  DATEI_MAX_MB=$(kleiner_zahl "$DATEI_MAX_MB" "$PRUEFEN_DATEI_MAX_MB") || exit 70
  PRUEFEN_CACHE_MB=$(kleiner_zahl "$PRUEFEN_CACHE_MB" "$HEIM_TMP_MB") || exit 70
  ZEITLIMIT_PRUEFEN_S=$(kleiner_zahl "$ZEITLIMIT_PRUEFEN_S" "$ZEITLIMIT_MAX_S") || exit 70
}

# Der eigene Teil der Entwicklungsports eines Platzes (0 bis 9, je 100 Ports): setzt PORT_VON und PORT_BIS
platz_ports() {
  [[ $1 =~ ^[0-9]$ ]] || fehler "Platz ungültig (0 bis 9)"
  PORT_VON=$((20000 + $1 * 100))
  PORT_BIS=$((PORT_VON + 99))
}

JOB="" PROJEKT="" ZEIT="" ZUSATZ="" MODUS="lauf" PLATZ=""
while [ $# -gt 0 ]; do
  case "$1" in
    --auftrag) JOB=${2-}; shift 2 ;;
    --projekt) PROJEKT=${2-}; shift 2 ;;
    --platz) PLATZ=${2-}; shift 2 ;;
    --modus) MODUS=${2-}; shift 2 ;;
    --zeitlimit) ZEIT=${2-}; shift 2 ;;
    --einheit-zusatz) ZUSATZ=${2-}; shift 2 ;;
    --) shift; break ;;
    *) fehler "unbekanntes Argument" ;;
  esac
done
[ $# -gt 0 ] || fehler "Befehl fehlt"
[[ $JOB =~ ^[0-9a-f]{16,32}$ ]] || fehler "Auftrags-ID ungültig"
[[ $PROJEKT =~ ^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$ && $PROJEKT != *--* && $PROJEKT != wamo ]] || fehler "Projektname ungültig"
# Modi als case mit Ablehnung als Standard (C.5.2); SCHRITT=1 für die drei Sandbox-Schritte ohne Netz
case "$MODUS" in
  lauf|pruefen|klon|ausgabe|pruefung) ;;
  *) fehler "Modus ungültig (lauf, pruefen, klon, ausgabe oder pruefung)" ;;
esac
SCHRITT=0
case "$MODUS" in klon|ausgabe|pruefung) SCHRITT=1 ;; esac
platz_ports "$PLATZ"
ZUSATZ=${ZUSATZ:-$MODUS}
[[ $ZUSATZ =~ ^[a-z]{1,12}$ ]] || fehler "Einheit ungültig"
for zahl in "$TMP_MB" "$HEIM_TMP_MB" "$DATEI_MAX_MB" "$OFFENE_DATEIEN" "$PROZESSE_MAX" "$ZEITLIMIT_S" "$ZEITLIMIT_MAX_S"; do
  [[ $zahl =~ ^[0-9]{1,9}$ ]] || fehler "wamo-job.conf: Zahl ungültig"
done
# Höchstes Zeitlimit des Modus (pruefen und die Schritte stehen fest im Skript)
case "$MODUS" in
  pruefen) ZEIT_HOECHSTENS=$ZEITLIMIT_PRUEFEN_S ;;
  klon) ZEIT_HOECHSTENS=$ZEITLIMIT_KLON_S ;;
  ausgabe|pruefung) ZEIT_HOECHSTENS=$ZEITLIMIT_SCHRITT_S ;;
  *) ZEIT_HOECHSTENS=$ZEITLIMIT_MAX_S ;;
esac
if [ "$MODUS" != lauf ]; then
  # Enger als der Auftragslauf, nie weiter: Speicher, Prozesse, CPU, Platz und das Zeitlimit (von jedem Paar der kleinere Wert; die
  # Werte PRUEFEN_* prüfen die Funktionen dabei selbst, ein Fehler dort betrifft nur diese Modi)
  pruefen_grenzen
  ZEIT=${ZEIT:-$ZEIT_HOECHSTENS}
else
  ZEIT=${ZEIT:-$ZEITLIMIT_S}
fi
case "$MODUS" in ausgabe|pruefung) DATEI_MAX_MB=$(kleiner_zahl "$DATEI_MAX_MB" "$SCHRITT_DATEI_MAX_MB") || exit 70 ;; esac
[[ $ZEIT =~ ^[0-9]{1,6}$ ]] && (( ZEIT >= 1 && ZEIT <= ZEITLIMIT_MAX_S )) || fehler "Zeitlimit ungültig"
if [ "$MODUS" != lauf ]; then
  (( ZEIT <= ZEIT_HOECHSTENS )) || fehler "Zeitlimit im Modus $MODUS höchstens $ZEIT_HOECHSTENS Sekunden"
fi

# Die drei Schritte starten nur ihr festes Programm (der Dispatcher ist der einzige Aufrufer; das hier ist die zweite Sicherung). Dazu in
# allen drei Modi die Probe des Rauchtests (wamo-job-klon.sh --probe: meldet nur Umgebungsnamen und ob Netz geht, schreibt nichts).
PROBE=0
if [ "$SCHRITT" = 1 ]; then
  if [ "$#" -eq 2 ] && [ "$1" = "$WAECHTER_INNEN/wamo-job-klon.sh" ] && [ "$2" = --probe ]; then
    PROBE=1
  else
    case "$MODUS" in
      klon) [ "$1" = "$WAECHTER_INNEN/wamo-job-klon.sh" ] || fehler "Modus klon startet nur $WAECHTER_INNEN/wamo-job-klon.sh" ;;
      ausgabe) [ "$1" = "$WAECHTER_INNEN/wamo-job-ausgabe.sh" ] || fehler "Modus ausgabe startet nur $WAECHTER_INNEN/wamo-job-ausgabe.sh" ;;
      pruefung) [ "$#" -ge 3 ] && [ "$1" = /usr/bin/python3 ] && [ "$2" = -I ] && [ "$3" = "$WAECHTER_INNEN/wamo_job_auszug.py" ] \
        || fehler "Modus pruefung startet nur /usr/bin/python3 -I $WAECHTER_INNEN/wamo_job_auszug.py" ;;
    esac
  fi
fi

JOBDIR=$JOBS/$JOB
PROJDIR=$PROJEKTE/$PROJEKT
for pfad in "$JOBDIR" "$JOBDIR/claude" "$JOBDIR/zustand" "$JOBDIR/etc" "$PROJDIR"; do
  [ -d "$pfad" ] && [ ! -L "$pfad" ] || fehler "Ordner fehlt oder ist ein Link: $pfad"
done
for pfad in "$JOBDIR/zustand/approvals.json" "$JOBDIR/etc/passwd" "$JOBDIR/etc/group"; do
  [ -f "$pfad" ] && [ ! -L "$pfad" ] || fehler "Datei fehlt oder ist ein Link: $pfad"
done
# Die Ordner und Dateien der Schritte (vom Dispatcher angelegt, für die Sandbox sonst unsichtbar): nie ein Link, immer der richtige Typ
schritt_ordner() { [ -d "$JOBDIR/$1" ] && [ ! -L "$JOBDIR/$1" ] || fehler "Modus $MODUS: $1 fehlt oder ist ein Link"; }
schritt_datei() { [ -f "$JOBDIR/$1" ] && [ ! -L "$JOBDIR/$1" ] || fehler "Modus $MODUS: $1 fehlt oder ist ein Link"; }
if [ "$SCHRITT" = 1 ] && [ "$PROBE" = 0 ]; then
  case "$MODUS" in
    klon) schritt_ordner basis.git
      if [ -e "$JOBDIR/bundle.ein" ] || [ -L "$JOBDIR/bundle.ein" ]; then schritt_datei bundle.ein; fi ;;
    ausgabe) schritt_ordner ausgabe ;;
    pruefung) schritt_ordner basis.git; schritt_datei bundle.ein; schritt_ordner ergebnis ;;
  esac
fi
[ -x "$BWRAP" ] || fehler "$BWRAP fehlt (wamo-job-einrichten.sh ausführen)"
[ -r "$APP/claude-code/managed-settings.json" ] || fehler "managed-settings.json fehlt"
[ -s "$SECCOMP" ] || fehler "seccomp-Filter $SECCOMP fehlt (wamo-job-einrichten.sh ausführen)"
[ -f "$PLUGINS/installed_plugins.json" ] && [ -d "$PLUGINS/data" ] && [ ! -e "$PLUGINS/cache/ecc/ecc/ohne-hooks/hooks" ]   || fehler "ECC-Kopie ohne Hooks in $PLUGINS fehlt (wamo-job-einrichten.sh ausführen)"
case "$ABSCHOTTUNG" in an|aus) ;; *) fehler "wamo-job.conf: ABSCHOTTUNG muss an oder aus sein" ;; esac
CLAUDE_ECHT=$(readlink -f "$HEIM/.local/bin/claude" || true)
[[ -n $CLAUDE_VERSION && $CLAUDE_ECHT == "$HEIM/.local/share/claude/versions/$CLAUDE_VERSION" ]] \
  || fehler "Claude-Code-Version weicht ab (erwartet ${CLAUDE_VERSION:-?}): wamo-job-einrichten.sh und Rauchtest nötig"

# Umgebung als Allowlist (Token kommen vom Dispatcher, nie über argv). Im Modus pruefen eine eigene, engere: kein einziger
# Token, nichts von Claude, nichts von der Auftragsart; selbst wenn der Aufrufer eines mitschickte, käme es nicht hinein.
ERLAUBT_RE='^(ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_CUSTOM_HEADERS|ANTHROPIC_BASE_URL|ANTHROPIC_DEFAULT_HAIKU_MODEL|ANTHROPIC_DEFAULT_SONNET_MODEL|ANTHROPIC_DEFAULT_OPUS_MODEL|ANTHROPIC_SMALL_FAST_MODEL|CLAUDE_CODE_SUBAGENT_MODEL|CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC|DISABLE_TELEMETRY|DISABLE_ERROR_REPORTING|GH_TOKEN|VERCEL_TOKEN|VERCEL_ORG_ID|SUPABASE_ACCESS_TOKEN|JIRA_URL|JIRA_EMAIL|JIRA_API_KEY|JIRA_API_TOKEN|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]|GIT_CONFIG_VALUE_[0-9]|XDG_RUNTIME_DIR|GIT_AUTHOR_NAME|GIT_AUTHOR_EMAIL|GIT_COMMITTER_NAME|GIT_COMMITTER_EMAIL|WAMO_GITHUB|WAMO_ZWEIG)$'
ERLAUBT_PRUEFEN_RE='^(GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]|GIT_CONFIG_VALUE_[0-9]|XDG_RUNTIME_DIR)$'
[ "$MODUS" = lauf ] || ERLAUBT_RE=$ERLAUBT_PRUEFEN_RE  # pruefen und die drei Schritte: kein einziger Token, nichts von Claude
while IFS= read -r name; do
  [[ $name =~ $ERLAUBT_RE ]] || unset "$name" 2>/dev/null || true
done < <(compgen -e)
export PATH=/usr/bin:/bin
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Persönlicher GitHub-Weg (Plan C, C.5 Start 7): nur mit WAMO_GITHUB=persoenlich die Namen für Autor, Committer und Zweig, je geprüft; dann
# zusätzlich jedes Dienst-Token weg (der Dispatcher gibt keins mit, das hier ist die zweite Sicherung). Ohne WAMO_GITHUB keiner der sechs Namen.
if [ "$MODUS" = lauf ] && [ -n "${WAMO_GITHUB-}" ]; then
  [ "$WAMO_GITHUB" = persoenlich ] || fehler "WAMO_GITHUB ungültig (nur persoenlich)"
  [[ ${GIT_AUTHOR_NAME-} =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ && ${GIT_COMMITTER_NAME-} == "$GIT_AUTHOR_NAME" ]] \
    || fehler "persönlicher GitHub-Weg: Autor ungültig"
  [[ ${GIT_AUTHOR_EMAIL-} =~ ^[0-9]{1,12}\+[A-Za-z0-9][A-Za-z0-9-]{0,38}@users\.noreply\.github\.com$ && ${GIT_COMMITTER_EMAIL-} == "$GIT_AUTHOR_EMAIL" ]] \
    || fehler "persönlicher GitHub-Weg: Adresse ungültig"
  [ "${WAMO_ZWEIG-}" = "wamo/$JOB" ] || fehler "persönlicher GitHub-Weg: Zweig ungültig"
  unset GH_TOKEN VERCEL_TOKEN VERCEL_ORG_ID SUPABASE_ACCESS_TOKEN JIRA_URL JIRA_EMAIL JIRA_API_KEY JIRA_API_TOKEN
else
  unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL WAMO_GITHUB WAMO_ZWEIG
fi

# Hausmodelle (Paket P6a, docs/ausrollen-neue-nutzer.md 4.7): Ein Lauf mit Zugangsart haus spricht über den Proxy wamo-haus-proxy auf
# Loopback mit LiteLLM. ANTHROPIC_BASE_URL darf nur genau dessen Adresse sein (jede andere bricht ab, die Sandbox spricht sonst nur mit
# Anthropic), und nur dann ist sein Port in der Landlock-Sperre offen (sonst steht er immer darin, auch wenn der Proxy gerade nicht
# lauscht); der Ausgangsfilter (wamo-egress.nft) lässt ihn immer zu, ohne Auftragstoken antwortet der Proxy nur mit 401.
HAUS_PROXY_PORT=18090
HAUS_PROXY_URL="http://127.0.0.1:$HAUS_PROXY_PORT"
# Einzige zweite Ausnahme: der Rauchtest (wamo_job_rauchtest.py, RAUCHTEST_PLATZ) lässt Claude Code auf Platz 9 gegen eine Attrappe in
# der Sandbox laufen, genau http://127.0.0.1:<Port> im eigenen Portbereich dieses Platzes. Platz 9 vergibt der Dispatcher nie
# (PARALLEL_MAX 6); die Attrappe lauscht nur in der Sandbox selbst, ein Weg nach außen entsteht dadurch nicht.
RAUCHTEST_PLATZ=9
HAUS=aus
if [ -n "${ANTHROPIC_BASE_URL-}" ]; then
  if [ "$ANTHROPIC_BASE_URL" = "$HAUS_PROXY_URL" ]; then
    HAUS=an
  elif [ "${PLATZ-}" = "$RAUCHTEST_PLATZ" ] && [[ $ANTHROPIC_BASE_URL =~ ^http://127\.0\.0\.1:([0-9]{5})$ ]] \
    && [ "${BASH_REMATCH[1]}" -ge "${PORT_VON:-1}" ] && [ "${BASH_REMATCH[1]}" -le "${PORT_BIS:-0}" ]; then
    :
  else
    fehler "ANTHROPIC_BASE_URL ist nur für den Proxy der Hausmodelle erlaubt"
  fi
fi
# Zweite Sicherung neben dem Dispatcher: mit dem Proxy nur das Auftragstoken, nie ein Claude-Zugang; ohne Proxy keine Modellnamen fürs Haus
if [ "$HAUS" = an ]; then
  [[ ${ANTHROPIC_API_KEY-} =~ ^wh1-[0-9a-f]{16,32}-[0-9a-f]{64}$ ]] || fehler "Hausmodelle: Auftragstoken fehlt oder hat eine falsche Form"
  [ -z "${CLAUDE_CODE_OAUTH_TOKEN-}" ] && [ -z "${ANTHROPIC_CUSTOM_HEADERS-}" ] || fehler "Hausmodelle: kein Claude-Zugang neben dem Proxy"
else
  unset ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_SMALL_FAST_MODEL CLAUDE_CODE_SUBAGENT_MODEL
fi

# Gesperrte Ports: alles, worauf der Host gerade lauscht, plus feste Zusatzports, ohne die immer erlaubten.
# Fällt ss aus oder findet nichts (mindestens sshd lauscht immer), startet nichts: sonst wäre die Sperre still offen.
SS_AUSGABE=$(ss -tlnH) || fehler "ss fehlgeschlagen, lauschende Ports nicht bestimmbar"
HOST_PORTS=$(awk '{print $4}' <<<"$SS_AUSGABE" | sed -nE 's/.*:([0-9]+)$/\1/p' | sort -un)
[ -n "$HOST_PORTS" ] || fehler "keine lauschenden Ports gefunden, Portsperre nicht bestimmbar"
FREI_PORTS="$NETZ_IMMER_ERLAUBT"
[ "$HAUS" != an ] || FREI_PORTS="$FREI_PORTS $HAUS_PROXY_PORT"
SPERRPORTS=$(
  { printf '%s\n' $HOST_PORTS; printf '%s\n' $NETZ_SPERRPORTS; echo "$HAUS_PROXY_PORT"; } \
    | sort -un | grep -vxF -f <(printf '%s\n' $FREI_PORTS) | paste -sd, -
)

# Modus pruefen: kein Netz. Ein eigener Netz-Namensraum, darin nur lo (von bwrap angeschaltet, ohne Verbindung zum Host): nichts
# kommt hinein oder hinaus, auch nicht zum Loopback des Hosts. Ausgangsfilter und Landlock bleiben als zweite Schicht bestehen.
NETZ_OPTION=--share-net
[ "$MODUS" = lauf ] || NETZ_OPTION=--unshare-net  # pruefen, klon, ausgabe, pruefung: immer ohne Netz

ARGS=(
  --die-with-parent --new-session
  --unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup-try "$NETZ_OPTION"
  --disable-userns
  --uid "$(id -u)" --gid "$(id -g)" --hostname wamo-auftrag --cap-drop ALL
  --seccomp 9
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/sbin /sbin --symlink usr/lib /lib
  --tmpfs /usr/local/lib/wamo
  --proc /proc --dev /dev
  --perms 1777 --size $((TMP_MB * 1024 * 1024)) --tmpfs /tmp
  --dir /var --symlink ../tmp /var/tmp --dir /run --dir /run/wamo
)
[ -e /lib64 ] && ARGS+=(--symlink usr/lib64 /lib64)

# /etc als Allowlist: nur, was Shell, Node, Python, git, gh, npm, uv und Chrome brauchen
ETC_ERLAUBT="alternatives bash.bashrc ca-certificates ca-certificates.conf debian_version environment fonts gai.conf
  gdb gitconfig gnutls host.conf hostname hosts inputrc java-8-openjdk ld.so.cache ld.so.conf ld.so.conf.d
  locale.alias locale.conf localtime lsb-release machine-id magic magic.mime mime.types mtab netconfig networks
  nsswitch.conf os-release pki profile protocols python3 python3.12 resolv.conf rpc services shells ssl terminfo
  timezone wgetrc xattr.conf xml"
for name in $ETC_ERLAUBT; do
  pfad=/etc/$name
  if [ -L "$pfad" ]; then
    echt=$(readlink -f "$pfad" || true)
    case "$echt" in
      /usr/*|/proc/*) ARGS+=(--symlink "$(readlink "$pfad")" "$pfad") ;;
      /etc/*) ;;  # zeigt auf einen anderen Eintrag in /etc: nicht nötig
      *) [ -e "$echt" ] && ARGS+=(--ro-bind "$echt" "$pfad") ;;
    esac
  elif [ -e "$pfad" ]; then
    ARGS+=(--ro-bind "$pfad" "$pfad")
  fi
done
ARGS+=(--ro-bind "$JOBDIR/etc/passwd" /etc/passwd --ro-bind "$JOBDIR/etc/group" /etc/group)

# Home als tmpfs, darin nur das Nötige (die drei Schritte brauchen nichts daraus: git, bash und python3 kommen aus /usr)
ARGS+=(--perms 0700 --size $((HEIM_TMP_MB * 1024 * 1024)) --tmpfs "$HEIM")
[ "$SCHRITT" = 1 ] || ARGS+=(--ro-bind "$HEIM/.local/bin" "$HEIM/.local/bin")
# Claude Code gibt es nur im Auftragslauf; im Modus pruefen fehlt es in der Sandbox (der Verweis claude in .local/bin zeigt dann
# ins Leere)
if [ "$MODUS" = lauf ]; then
  ARGS+=(--ro-bind "$HEIM/.local/share/claude" "$HEIM/.local/share/claude")
fi
if [ "$SCHRITT" = 0 ]; then
  ARGS+=(
    --ro-bind-try "$HEIM/.local/share/uv/tools" "$HEIM/.local/share/uv/tools"
    --ro-bind-try "$HEIM/.local/share/uv/python" "$HEIM/.local/share/uv/python"
    --ro-bind "$HEIM/.fnm" "$HEIM/.fnm"
    --ro-bind "$HEIM/.npm-global" "$HEIM/.npm-global"
    --ro-bind-try "$HEIM/.gitconfig" "$HEIM/.gitconfig"
  )
fi
if [ "$MODUS" = lauf ]; then
  ARGS+=(--bind "$JOBDIR/claude" "$HEIM/.claude")
fi
# Caches und Plugin-Daten je Auftrag auf der Platte (kein gemeinsamer, vergiftbarer Cache zwischen
# Aufträgen). Plugins: nicht die von wamo, sondern die root-eigene Kopie des ECC-Plugins ohne Hooks
# (wamo-job-ecc.py); Skills, Agenten und Befehle heißen gleich, Hooks laufen keine.
# Modus pruefen: weder Plugins noch die Ordner des Auftrags. Diese Ordner (npm, cache) sind dauerhaft und dieselben, die ein Lauf mit
# Token und spätere Läufe lesen und schreiben; ein Prüflauf ohne Token darf dort nichts hinterlassen und nichts daraus lesen. Er
# bekommt je Lauf eigene, leere tmpfs-Ordner mit Größengrenze, die mit der Sandbox verschwinden.
if [ "$MODUS" = lauf ]; then
  for teil in npm cache plugin-daten; do
    [ ! -L "$JOBDIR/$teil" ] || fehler "$teil ist ein Link"
    mkdir -p "$JOBDIR/$teil"
  done
  ARGS+=(
    --bind "$JOBDIR/npm" "$HEIM/.npm"
    --bind "$JOBDIR/cache" "$HEIM/.cache"
    --ro-bind "$PLUGINS" "$HEIM/.claude/plugins"
    --bind "$JOBDIR/plugin-daten" "$HEIM/.claude/plugins/data"
  )
else
  ARGS+=(
    --perms 0700 --size $((PRUEFEN_CACHE_MB * 1024 * 1024)) --tmpfs "$HEIM/.npm"
    --perms 0700 --size $((PRUEFEN_CACHE_MB * 1024 * 1024)) --tmpfs "$HEIM/.cache"
  )
fi

# Sicherheitsrelevantes zuletzt: spätere Mounts überdecken alles, was frühere umgelenkt haben könnten.
# projekte ist ein eigenes tmpfs (Mountpunkt, nicht umbenennbar) und danach schreibgeschützt; Wächter,
# Managed-Settings und /run/wamo liegen auf der Wurzel, die zum Schluss schreibgeschützt wird.
# Projekt: beschreibbar (lauf, pruefen, klon), nur lesend (ausgabe) oder gar nicht (pruefung)
ARGS+=(--perms 0755 --size 1048576 --tmpfs "$PROJEKTE")
case "$MODUS" in
  ausgabe) ARGS+=(--ro-bind "$PROJDIR" "$PROJEKTE/$PROJEKT") ;;
  pruefung) ;;
  *) ARGS+=(--bind "$PROJDIR" "$PROJEKTE/$PROJEKT") ;;
esac
ARGS+=(
  --remount-ro "$PROJEKTE"
  --ro-bind "$APP/waechter" "$WAECHTER_INNEN"
  --ro-bind "$APP/claude-code" /etc/claude-code
)
# Die Ein- und Ausgaben der Schritte unter /run/wamo (C.5.2); die Probe des Rauchtests bekommt dieselben, soweit es sie gibt
BINDE=--bind BINDE_RO=--ro-bind
[ "$PROBE" = 0 ] || { BINDE=--bind-try; BINDE_RO=--ro-bind-try; }
case "$MODUS" in
  klon)
    ARGS+=("$BINDE_RO" "$JOBDIR/basis.git" /run/wamo/basis.git)
    [ ! -f "$JOBDIR/bundle.ein" ] || ARGS+=(--ro-bind "$JOBDIR/bundle.ein" /run/wamo/letztes.bundle) ;;
  ausgabe) ARGS+=("$BINDE" "$JOBDIR/ausgabe" /run/wamo/ausgabe) ;;
  pruefung)
    ARGS+=("$BINDE_RO" "$JOBDIR/bundle.ein" /run/wamo/bundle.ein "$BINDE_RO" "$JOBDIR/basis.git" /run/wamo/basis.git
           "$BINDE" "$JOBDIR/ergebnis" /run/wamo/ergebnis) ;;
esac
# Der Zustand des Auftrags (Freigaben, Anfragen, Socket) gehört nur zum Auftragslauf; im Modus pruefen gibt es ihn nicht
if [ "$MODUS" = lauf ]; then
  ARGS+=(
    --bind "$JOBDIR/zustand" /run/wamo/zustand
    --ro-bind "$JOBDIR/zustand/approvals.json" /run/wamo/zustand/approvals.json
  )
fi
if [ "$MODUS" = pruefung ]; then
  ARGS+=(--remount-ro / --chdir /tmp)
else
  ARGS+=(
    --symlink "$PROJEKTE/$PROJEKT" /run/wamo/projekt
    --remount-ro /
    --chdir "$PROJEKTE/$PROJEKT"
  )
fi
# Umgebung in der Sandbox. Auftragslauf: wie bisher. Modus pruefen: nur das Nötige, nichts von Claude, kein GH_*, kein Token
SETENV_LAUF=(
  --setenv HOME "$HEIM" --setenv USER wamo --setenv LOGNAME wamo --setenv SHELL /bin/bash
  --setenv PATH "$HEIM/.local/bin:$HEIM/.npm-global/bin:$HEIM/.fnm/aliases/default/bin:/usr/local/bin:/usr/bin:/bin"
  --setenv TMPDIR /tmp --setenv LANG C.UTF-8 --setenv TZ Europe/Berlin --setenv TERM dumb
  --setenv CLAUDE_CONFIG_DIR "$HEIM/.claude" --setenv DISABLE_AUTOUPDATER 1
  --setenv GIT_TERMINAL_PROMPT 0 --setenv GH_PROMPT_DISABLED 1 --setenv NO_UPDATE_NOTIFIER 1
  --setenv npm_config_update_notifier false
  --setenv WAMO_PORT_VON "$PORT_VON" --setenv WAMO_PORT_BIS "$PORT_BIS"
  --unsetenv XDG_RUNTIME_DIR
)
SETENV_PRUEFEN=(
  --setenv HOME "$HEIM" --setenv USER wamo --setenv LOGNAME wamo --setenv SHELL /bin/bash
  --setenv PATH "$HEIM/.local/bin:$HEIM/.npm-global/bin:$HEIM/.fnm/aliases/default/bin:/usr/local/bin:/usr/bin:/bin"
  --setenv TMPDIR /tmp --setenv LANG C.UTF-8 --setenv TZ Europe/Berlin --setenv TERM dumb
  --setenv CI 1 --setenv NO_COLOR 1 --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PYTHONIOENCODING utf-8
  --setenv GIT_TERMINAL_PROMPT 0 --setenv NO_UPDATE_NOTIFIER 1 --setenv npm_config_update_notifier false
  --unsetenv XDG_RUNTIME_DIR
)
# Die drei Schritte: Umgebung wie pruefen, dazu git ohne System- und Benutzerkonfiguration, ohne Rückfrage und ohne optionale Sperren
SETENV_SCHRITT=(
  --setenv HOME "$HEIM" --setenv USER wamo --setenv LOGNAME wamo --setenv SHELL /bin/bash --setenv PATH /usr/bin:/bin
  --setenv TMPDIR /tmp --setenv LANG C.UTF-8 --setenv LC_ALL C.UTF-8 --setenv TZ Europe/Berlin --setenv TERM dumb
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PYTHONIOENCODING utf-8
  --setenv GIT_CONFIG_NOSYSTEM 1 --setenv GIT_CONFIG_GLOBAL /dev/null --setenv GIT_TERMINAL_PROMPT 0 --setenv GIT_OPTIONAL_LOCKS 0
  --setenv GIT_CEILING_DIRECTORIES /srv/wamo/projekte --setenv WAMO_MODUS "$MODUS"
  --unsetenv XDG_RUNTIME_DIR
)
case "$MODUS" in
  lauf) ARGS+=("${SETENV_LAUF[@]}") ;;
  pruefen) ARGS+=("${SETENV_PRUEFEN[@]}") ;;
  *) ARGS+=("${SETENV_SCHRITT[@]}") ;;
esac

INNEN=()
if [ "$ABSCHOTTUNG" = an ]; then
  INNEN=(/usr/bin/python3 -I "$WAECHTER_INNEN/abschottung.py" --sperrports "$SPERRPORTS" --entwicklungsports "$PORT_VON-$PORT_BIS" --)
fi

# Der Platz steht im Namen (p<n>): ein Dispatcher, der den Platz belegt, beendet damit Reste eines hart beendeten Vorgängers auf diesem Platz
# (wamo_job_dispatch.platz_reste_beenden), die sonst den Portbereich des Platzes weiter nutzen könnten
EINHEIT="wamo-job-$JOB-$ZUSATZ-p$PLATZ-$(date +%s%N)"
# --as=unlimited: der Dispatcher begrenzt seinen eigenen Adressraum (weiche Grenze); Claude Code braucht mehr
exec /usr/bin/systemd-run --user --scope --quiet --collect --unit="$EINHEIT" \
  -p MemoryMax="$SPEICHER_MAX" -p MemorySwapMax=0 -p TasksMax="$PROZESSE_MAX" \
  -p CPUQuota="$CPU_QUOTA" -p CPUWeight=50 -p IOWeight=50 -p RuntimeMaxSec=$((ZEIT + 60)) \
  /usr/bin/prlimit --nofile="$OFFENE_DATEIEN" --core=0 --fsize=$((DATEI_MAX_MB * 1024 * 1024)) --as=unlimited \
  /usr/bin/timeout --kill-after=15 "$ZEIT" \
  /usr/bin/nice -n 10 "$BWRAP" "${ARGS[@]}" "${INNEN[@]}" "$@" 9<"$SECCOMP"
