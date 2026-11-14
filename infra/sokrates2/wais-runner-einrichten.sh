#!/usr/bin/env bash
# W.A.I.S.: selbst gehosteten GitHub-Runner auf Sokrates-2 einrichten. Der Runner läuft als eigener Benutzer wais-deploy ohne root und
# darf per sudo genau die Aufrufe des Ausroll-Einstiegs /usr/local/sbin/wais-deploy (aus wais-deploy.sh neben diesem Skript).
# Nur als root. Wiederholbar. Anleitung für Niko: docs/runner-einrichten.md.
#
#   sudo bash ~/wamo-infra/wais-runner-einrichten.sh einrichten [--trocken] [--url URL] [--gruppe NAME] [--ohne-registrierung]
#   sudo bash ~/wamo-infra/wais-runner-einrichten.sh status
#   sudo bash ~/wamo-infra/wais-runner-einrichten.sh rueckweg [--trocken] [--abmelden] [--alles]
#   bash wais-runner-einrichten.sh sudoers-text | unit-text      gibt nur den Text aus (ohne root, für Tests und zum Lesen)
#
# einrichten:
#   0 Vorprüfung: root, aarch64, sudo ab 1.9.10 (Regeln mit regulären Ausdrücken), Werkzeuge, libicu, Herkunft dieses Ordners
#   1 Benutzer wais-deploy: Systembenutzer, Shell /usr/sbin/nologin, Passwort gesperrt, keine weitere Gruppe (kein docker, kein sudo),
#     Home /var/lib/wais-runner
#   2 Ordner: /opt/wais-runner (root:wais-deploy 1770 mit Sticky-Bit: der Runner legt dort seine Dateien an, kann aber die Programme
#     von root weder ändern noch ersetzen), /var/lib/wais-runner/arbeit (Arbeitsordner der Jobs), /var/lib/wais-deploy (root:wamocon
#     0750, darin staende root:wamocon 0750 und zustand root 0700), /var/log/wais-deploy (root:adm 0750), /etc/wais-deploy (root 0755)
#   3 Runner-Software actions-runner-linux-arm64 in der festen Version unten; die SHA-256 wird vor dem Entpacken geprüft
#   4 Einstieg /usr/local/sbin/wais-deploy (root 0755) aus wais-deploy.sh
#   5 Quelle: /etc/wais-deploy/quelle.conf, Hostschlüssel von GitHub (known_hosts), Lese-Schlüssel deploy_key (nur wenn er fehlt;
#     der öffentliche Teil wird angezeigt und kommt als Deploy-Key ohne Schreibrecht ins Repo)
#   6 sudoers /etc/sudoers.d/wais-deploy (vor und nach dem Einsetzen mit visudo -c geprüft, danach Proben mit sudo -l -U wais-deploy)
#   7 Dienst wais-runner.service (User=wais-deploy)
#   8 Registrierung bei GitHub, nur wenn noch keine besteht. Das Registrierungstoken kommt nur über stdin (Eingabe ohne Anzeige oder
#     eine Pipe), nie als Argument und nie in eine Datei; config.sh bekommt es über ACTIONS_RUNNER_INPUT_TOKEN in seiner Umgebung.
#   9 Dienst starten
# rueckweg: sudoers entfernen (sofort keine root-Aufrufe mehr), Dienst stoppen und entfernen, mit --abmelden beim Repo abmelden
#   (Entfernungstoken über stdin), Runner-Software, Home, Benutzer und Einstieg entfernen. Mit --alles auch /etc/wais-deploy (Schlüssel)
#   und /var/lib/wais-deploy (Spiegel, Stände, Zustand). Das Protokoll /var/log/wais-deploy bleibt. Bricht ab, solange ein Ausrollen läuft.
#
# Neue Runner-Version: RUNNER_VERSION und RUNNER_SHA256 gemeinsam ändern (Release-Seite github.com/actions/runner/releases, Zeile
# actions-runner-linux-arm64-<Version>.tar.gz), dann einrichten erneut. Ohne automatische Updates verlangt GitHub ein Update innerhalb
# von 30 Tagen nach einer neuen Version, sonst bekommt der Runner keine Jobs mehr.
# Probelauf ohne root (Tests): WAIS_RUNNER_WURZEL=/tmp/probe, Programme aus $WURZEL/attrappen; WAIS_RUNNER_PROBE_ARCHIV und
# WAIS_RUNNER_PROBE_SHA256 ersetzen dort Archiv und Prüfsumme.
set -euo pipefail
umask 022

RUNNER_VERSION=2.338.2
RUNNER_SHA256=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
BENUTZER=wais-deploy
RUNNER_NAME=sokrates2-wais-deploy
RUNNER_LABEL=wais-deploy
STANDARD_URL=https://github.com/Wamocon/w.a.i.s
STANDARD_QUELLE=git@github.com:Wamocon/w.a.i.s.git
SUDO_MIN=1.9.10
EINSTIEG_PFAD=/usr/local/sbin/wais-deploy
# Hostschlüssel von GitHub (https://api.github.com/meta, Feld ssh_keys; Fingerabdruck ed25519 SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU)
GITHUB_HOSTKEYS=(
  "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
  "github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg="
  "github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk="
)

HERE="$(cd "$(dirname "$0")" && pwd)"

fehler() { echo "wais-runner-einrichten: $*" >&2; exit 1; }
aufruf_fehler() {
  echo "wais-runner-einrichten: $*" >&2
  echo "Aufruf: einrichten [--trocken] [--url URL] [--gruppe NAME] [--ohne-registrierung] | status | rueckweg [--trocken] [--abmelden] [--alles] | sudoers-text | unit-text" >&2
  exit 2
}

# ---------- Texte (ohne root, ohne Wurzel: so stehen sie auf dem Server)
sudoers_text() {
  local e="$EINSTIEG_PFAD" b t i z=()
  z+=("$e status" "$e rauchtest" "$e ausleiten" "$e ausleiten --trocken")
  for t in kern oberflaeche beides; do z+=("$e rueckweg $t" "$e rueckweg $t --trocken"); done
  z+=("$e ^pruefen-stand [0-9a-f]{40}\$")
  for b in verteilen test-kern test-oberflaeche prod-kern prod-oberflaeche; do
    z+=("$e ^$b [0-9a-f]{40}\$" "$e ^$b [0-9a-f]{40} --trocken\$")
  done
  echo "# W.A.I.S.: erzeugt von wais-runner-einrichten.sh, nicht von Hand ändern (Rückweg: wais-runner-einrichten.sh rueckweg)."
  echo "# Der Runner-Benutzer $BENUTZER darf als root genau diese Aufrufe des Ausroll-Einstiegs, sonst nichts. Argumente der Form ^...\$"
  echo "# sind reguläre Ausdrücke über die ganze Argumentzeile (sudo ab 1.9.10); ein Commit hat genau 40 Hexzeichen."
  echo "Defaults:$BENUTZER !requiretty, env_reset, !lecture"
  echo "Cmnd_Alias WAIS_DEPLOY = \\"
  for i in "${!z[@]}"; do
    if [ "$i" -lt $(( ${#z[@]} - 1 )) ]; then echo "  ${z[$i]}, \\"; else echo "  ${z[$i]}"; fi
  done
  echo "$BENUTZER ALL=(root) NOPASSWD: WAIS_DEPLOY"
}

unit_text() {
  cat <<EOF
# W.A.I.S.: erzeugt von wais-runner-einrichten.sh, nicht von Hand ändern.
# Selbst gehosteter GitHub-Runner für das Ausrollen (Label $RUNNER_LABEL). Er läuft als $BENUTZER ohne root; root-Rechte gibt es nur
# über sudo für die Aufrufe in /etc/sudoers.d/$BENUTZER. Keine Namensräume (ProtectSystem, PrivateTmp, NoNewPrivileges): sudo erbt sie
# sonst, und der Einstieg könnte die Betriebsskripte nicht ausführen. KillMode=process wie beim Dienst von GitHub: ein Stopp des Runners
# bricht ein laufendes Ausrollen nicht mitten im Schalten ab.
[Unit]
Description=W.A.I.S. GitHub-Runner fuer das Ausrollen ($BENUTZER)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BENUTZER
Group=$BENUTZER
WorkingDirectory=/opt/wais-runner
Environment=HOME=/var/lib/wais-runner
ExecStart=/opt/wais-runner/run.sh
Restart=always
RestartSec=15s
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=5min
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
}

# ---------- Aufruf
BEFEHL="${1:-}"
[ $# -eq 0 ] || shift
TROCKEN=nein; URL="$STANDARD_URL"; GRUPPE=""; REGISTRIEREN=ja; ABMELDEN=nein; ALLES=nein; URL_GESETZT=nein
while [ $# -gt 0 ]; do
  case "$1" in
    --trocken) TROCKEN=ja ;;
    --url) [ $# -ge 2 ] || aufruf_fehler "--url braucht einen Wert."; URL="$2"; URL_GESETZT=ja; shift ;;
    --gruppe) [ $# -ge 2 ] || aufruf_fehler "--gruppe braucht einen Wert."; GRUPPE="$2"; shift ;;
    --ohne-registrierung) REGISTRIEREN=nein ;;
    --abmelden) ABMELDEN=ja ;;
    --alles) ALLES=ja ;;
    *) aufruf_fehler "Unbekannte Angabe: $1" ;;
  esac
  shift
done
case "$BEFEHL" in
  einrichten) [ "$ABMELDEN$ALLES" = neinnein ] || aufruf_fehler "--abmelden und --alles gelten nur für rueckweg." ;;
  rueckweg) [ "$URL_GESETZT" = nein ] && [ -z "$GRUPPE" ] && [ "$REGISTRIEREN" = ja ] || aufruf_fehler "rueckweg kennt nur --trocken, --abmelden und --alles." ;;
  status) [ "$TROCKEN$ABMELDEN$ALLES$URL_GESETZT" = neinneinneinnein ] && [ -z "$GRUPPE" ] && [ "$REGISTRIEREN" = ja ] \
            || aufruf_fehler "status kennt keine Optionen." ;;
  sudoers-text) sudoers_text; exit 0 ;;
  unit-text) unit_text; exit 0 ;;
  *) aufruf_fehler "Unbekannter Befehl." ;;
esac
[[ "$URL" =~ ^https://github\.com/Wamocon(/[A-Za-z0-9._-]{1,100})?$ ]] || aufruf_fehler "--url: https://github.com/Wamocon oder https://github.com/Wamocon/<repo>."
if [ -n "$GRUPPE" ]; then
  [[ "$GRUPPE" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || aufruf_fehler "--gruppe: Buchstaben, Ziffern, Punkt, Strich, Unterstrich."
  [ "$URL" = https://github.com/Wamocon ] || aufruf_fehler "--gruppe gilt nur für die Organisation (--url https://github.com/Wamocon)."
fi

# ---------- Umgebung: echtes System oder Probelauf
WURZEL="${WAIS_RUNNER_WURZEL:-}"
if [ -z "$WURZEL" ]; then
  [ "$(id -u)" -eq 0 ] || fehler "Bitte mit sudo ausführen."
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
else
  [ "$(id -u)" -ne 0 ] || fehler "Der Probelauf (WAIS_RUNNER_WURZEL) läuft nie als root."
  case "$WURZEL" in
    /|*//*|*/..|*/../*|*/.|*/./*|*[!A-Za-z0-9._/-]*|[!/]*)
      fehler "WAIS_RUNNER_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich und Schrägstrich sein." ;;
  esac
  PATH="$WURZEL/attrappen:$PATH"
  # Nur im Probelauf: Dateisysteme ohne Unix-Rechte (Git Bash unter Windows) lassen chmod scheitern; das ist dort kein Fehler
  chmod() { command chmod "$@" 2>/dev/null || true; }
  install() { if [ "$1" = -d ]; then shift; if [ "$1" = -m ]; then shift 2; fi; mkdir -p "$@"; else command install "$@"; fi; }
  echo "Probelauf unter $WURZEL (kein root, keine Dienste, keine sudo-Proben)"
fi
export PATH

RUNNER_DIR="$WURZEL/opt/wais-runner"
HOME_DIR="$WURZEL/var/lib/wais-runner"
ARBEIT="$HOME_DIR/arbeit"
EINSTIEG="$WURZEL$EINSTIEG_PFAD"
SUDOERS="$WURZEL/etc/sudoers.d/wais-deploy"
UNIT="$WURZEL/etc/systemd/system/wais-runner.service"
ETC="$WURZEL/etc/wais-deploy"
DATEN="$WURZEL/var/lib/wais-deploy"
LOGORDNER="$WURZEL/var/log/wais-deploy"
DEPLOY_SPERRE="$WURZEL/run/wais-deploy/lock"
TMP_ORT="$WURZEL/var/tmp"
TOKEN=""
AUFRAEUMEN=""
trap 'TOKEN=""; if [ -n "$AUFRAEUMEN" ]; then rm -rf "$AUFRAEUMEN"; fi' EXIT

schritt() { echo "== $*"; }
plan() { echo "  [trocken] $*"; }
besitz() { if [ -z "$WURZEL" ]; then chown "$@"; fi; }   # Eigentümer nur im echten Betrieb

# Schutz gegen untergeschobene Dateien (wie in den übrigen Einrichtungsskripten): dieser Ordner, sein Elternordner und alles darin
# gehören root oder dem Aufrufer und sind weder für die Gruppe noch für alle beschreibbar.
pruefe_herkunft() {
  local erlaubt uid modus pfad
  erlaubt=" 0 $(id -u) ${SUDO_UID:-} "
  while read -r uid modus pfad; do
    if [[ "$erlaubt" != *" $uid "* ]] || (( 8#$modus & 8#022 )); then
      fehler "Unsicherer Ablageort: $pfad (Besitzer $uid, Rechte $modus). Ordner im eigenen Home ablegen und mit chmod -R go-w schützen."
    fi
  done < <(stat -c '%u %a %n' "$(dirname "$HERE")"; find "$HERE" \( -type l -printf '%U 777 %p\n' \) -o -printf '%U %m %p\n')
}

# Token nur über stdin: an der Tastatur ohne Anzeige, sonst eine Zeile aus der Pipe. Nie aus Argumenten, Dateien oder der Umgebung.
token_lesen() {   # $1 Bezeichnung
  local t=""
  if [ -t 0 ]; then
    printf '%s (wird nicht angezeigt): ' "$1" >&2
    IFS= read -rs t || true
    echo >&2
  else
    IFS= read -r t || true
  fi
  t="${t%$'\r'}"
  [[ "$t" =~ ^[A-Za-z0-9_-]{20,200}$ ]] || fehler "$1 fehlt oder hat nicht die erwartete Form: nichts geändert."
  TOKEN="$t"
}

runner_info() {   # Name und Adresse aus .runner (enthält kein Geheimnis; .credentials wird nie gelesen)
  local d="$RUNNER_DIR/.runner"
  if [ ! -f "$d" ]; then echo "nicht registriert"; return 0; fi
  printf 'Name %s, %s' "$(tr -d '\r\n' < "$d" | sed -n 's/.*"agentName": *"\([^"]*\)".*/\1/p')" \
    "$(tr -d '\r\n' < "$d" | sed -n 's/.*"gitHubUrl": *"\([^"]*\)".*/\1/p')"
}

# ---------- einrichten
vorpruefung() {
  schritt "0. Vorprüfung"
  local w v
  for w in curl sha256sum tar visudo systemctl sudo runuser useradd ssh-keygen git flock getent; do
    command -v "$w" >/dev/null || fehler "$w fehlt."
  done
  [ "$(uname -m)" = aarch64 ] || fehler "Dieser Runner ist für arm64 (aarch64) bestimmt, gefunden: $(uname -m)."
  v="$(sudo -V | sed -n '1s/^Sudo version \([0-9][0-9.]*\).*/\1/p')"
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fehler "sudo-Version nicht lesbar."
  [ "$(printf '%s\n' "$SUDO_MIN" "$v" | sort -V | head -n 1)" = "$SUDO_MIN" ] \
    || fehler "sudo $v ist zu alt: die Regeln brauchen reguläre Ausdrücke (ab $SUDO_MIN)."
  [ -f "$HERE/wais-deploy.sh" ] || fehler "$HERE/wais-deploy.sh fehlt (infra/sokrates2 vollständig ablegen)."
  if [ -z "$WURZEL" ]; then
    ldconfig -p | grep -q 'libicuuc\.so' || fehler "libicu fehlt (der Runner braucht sie): sudo apt-get install libicu74"
    pruefe_herkunft
  fi
  echo "  sudo $v, $(uname -m), Werkzeuge vollständig"
}

benutzer() {
  schritt "1. Benutzer $BENUTZER"
  local home shell gruppen
  if getent passwd "$BENUTZER" >/dev/null; then
    IFS=: read -r _ _ _ _ _ home shell < <(getent passwd "$BENUTZER")
    gruppen="$(id -nG "$BENUTZER")"
    [ "$shell" = /usr/sbin/nologin ] || fehler "$BENUTZER hat die Shell $shell (erwartet /usr/sbin/nologin): von Hand prüfen."
    [ "$home" = /var/lib/wais-runner ] || fehler "$BENUTZER hat das Home $home (erwartet /var/lib/wais-runner): von Hand prüfen."
    [ "$gruppen" = "$BENUTZER" ] || fehler "$BENUTZER ist in weiteren Gruppen ($gruppen): von Hand entfernen, dann erneut."
    echo "  vorhanden (nologin, nur Gruppe $BENUTZER)"
  elif [ "$TROCKEN" = ja ]; then
    plan "useradd --system --user-group --home-dir /var/lib/wais-runner --shell /usr/sbin/nologin $BENUTZER"
    return 0
  else
    useradd --system --user-group --home-dir /var/lib/wais-runner --no-create-home --shell /usr/sbin/nologin \
      --comment "W.A.I.S. GitHub-Runner" "$BENUTZER"
    echo "  angelegt (nologin, nur Gruppe $BENUTZER)"
  fi
  if [ "$TROCKEN" = nein ]; then usermod -L "$BENUTZER"; fi
}

ordner() {
  schritt "2. Ordner"
  if [ "$TROCKEN" = ja ]; then
    plan "/var/lib/wais-runner und arbeit ($BENUTZER 0750), /opt/wais-runner (root:$BENUTZER 1770), /var/lib/wais-deploy (root:wamocon 0750),"
    plan "/var/log/wais-deploy (root:adm 0750), /etc/wais-deploy (root 0755)"
    return 0
  fi
  install -d -m 0750 "$HOME_DIR" "$ARBEIT"
  besitz "$BENUTZER:$BENUTZER" "$HOME_DIR" "$ARBEIT"
  install -d "$RUNNER_DIR"
  besitz "root:$BENUTZER" "$RUNNER_DIR"
  chmod 1770 "$RUNNER_DIR"
  install -d -m 0750 "$DATEN" "$DATEN/staende"
  besitz root:wamocon "$DATEN" "$DATEN/staende"
  install -d -m 0700 "$DATEN/zustand"
  install -d -m 0750 "$LOGORDNER"
  besitz root:adm "$LOGORDNER"
  install -d -m 0755 "$ETC"
  echo "  angelegt oder geprüft"
}

runner_software() {
  schritt "3. Runner-Software $RUNNER_VERSION (linux-arm64)"
  local marke="$RUNNER_DIR/.wais-version" soll="$RUNNER_VERSION $RUNNER_SHA256" sha="$RUNNER_SHA256" tmp f neu_starten=nein
  if [ -f "$marke" ] && [ "$(cat "$marke")" = "$soll" ]; then echo "  vorhanden"; return 0; fi
  if [ "$TROCKEN" = ja ]; then plan "lädt $RUNNER_URL, prüft SHA-256 $RUNNER_SHA256, entpackt nach /opt/wais-runner (Programme root)"; return 0; fi
  if [ -n "$WURZEL" ]; then sha="${WAIS_RUNNER_PROBE_SHA256:-$sha}"; fi
  install -d -m 0700 "$TMP_ORT"
  tmp="$(mktemp -d "$TMP_ORT/wais-runner.XXXXXX")"
  AUFRAEUMEN="$tmp"
  curl -fsSL --proto '=https' --tlsv1.2 -o "$tmp/runner.tar.gz" "$RUNNER_URL"
  echo "$sha  $tmp/runner.tar.gz" | sha256sum --check --strict --quiet \
    || fehler "Die Prüfsumme des Runner-Archivs stimmt nicht: nichts entpackt."
  echo "  Prüfsumme stimmt"
  if systemctl is-active --quiet wais-runner.service; then systemctl stop wais-runner.service; neu_starten=ja; fi
  rm -rf "${RUNNER_DIR:?}/bin" "${RUNNER_DIR:?}/externals"
  tar -xzf "$tmp/runner.tar.gz" -C "$RUNNER_DIR" --no-same-owner
  # Alles aus dem Archiv gehört root und ist für andere nicht beschreibbar: der Runner kann seine Programme nicht ändern
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    besitz -R root:root "$RUNNER_DIR/$f"
    chmod -R go-w "$RUNNER_DIR/$f"
  done < <(tar -tzf "$tmp/runner.tar.gz" | sed -e 's#^\./##' -e 's#/.*##' | grep -v '^$' | sort -u)
  echo "$soll" > "$marke"
  besitz root:root "$marke"
  chmod 0644 "$marke"
  rm -rf "$tmp"
  AUFRAEUMEN=""
  echo "  entpackt"
  if [ "$neu_starten" = ja ]; then systemctl start wais-runner.service; fi
}

einstieg() {
  schritt "4. Einstieg $EINSTIEG_PFAD"
  local tmp
  if [ "$TROCKEN" = ja ]; then plan "installiert $HERE/wais-deploy.sh als $EINSTIEG_PFAD (root 0755)"; return 0; fi
  install -d -m 0755 "$(dirname "$EINSTIEG")"
  tmp="$(mktemp "$(dirname "$EINSTIEG")/.wais-deploy.XXXXXX")"
  tr -d '\r' < "$HERE/wais-deploy.sh" > "$tmp"
  bash -n "$tmp" || { rm -f "$tmp"; fehler "wais-deploy.sh hat einen Syntaxfehler: nichts installiert."; }
  chmod 0755 "$tmp"
  besitz root:root "$tmp"
  mv -f "$tmp" "$EINSTIEG"
  echo "  installiert (SHA-256 $(sha256sum "$EINSTIEG" | cut -d' ' -f1))"
}

quelle() {
  schritt "5. Quelle und Lese-Schlüssel"
  if [ "$TROCKEN" = ja ]; then
    plan "$ETC/quelle.conf (QUELLE_URL=$STANDARD_QUELLE, nur wenn sie fehlt), known_hosts mit den Hostschlüsseln von GitHub,"
    plan "deploy_key (ed25519, root 0600, nur wenn er fehlt)"
    return 0
  fi
  install -d -m 0755 "$ETC"
  if [ ! -f "$ETC/quelle.conf" ]; then
    { echo "# Quelle des Ausroll-Einstiegs wais-deploy (gelesen wird nur diese eine Zeile)"; echo "QUELLE_URL=$STANDARD_QUELLE"; } > "$ETC/quelle.conf"
    chmod 0644 "$ETC/quelle.conf"
    besitz root:root "$ETC/quelle.conf"
  fi
  printf '%s\n' "${GITHUB_HOSTKEYS[@]}" > "$ETC/.known_hosts.neu"
  chmod 0644 "$ETC/.known_hosts.neu"
  besitz root:root "$ETC/.known_hosts.neu"
  mv -f "$ETC/.known_hosts.neu" "$ETC/known_hosts"
  if [ ! -f "$ETC/deploy_key" ]; then
    ssh-keygen -q -t ed25519 -N '' -C "wais-deploy@sokrates2" -f "$ETC/deploy_key"
    echo "  Lese-Schlüssel neu erzeugt"
  fi
  chmod 0600 "$ETC/deploy_key"
  besitz root:root "$ETC/deploy_key" "$ETC/deploy_key.pub"
  echo "  Quelle: $(grep '^QUELLE_URL=' "$ETC/quelle.conf")"
  echo "  Öffentlicher Teil des Lese-Schlüssels (in GitHub als Deploy-Key OHNE Schreibrecht eintragen, Titel $RUNNER_NAME):"
  sed 's/^/    /' "$ETC/deploy_key.pub"
}

sudo_proben() {
  local c=0123456789abcdef0123456789abcdef01234567 e="$EINSTIEG_PFAD"
  erlaubt() { sudo -n -l -U "$BENUTZER" "$@" >/dev/null 2>&1; }
  erlaubt "$e" status || fehler "Probe: status ist nicht erlaubt."
  erlaubt "$e" verteilen "$c" || fehler "Probe: verteilen <commit> ist nicht erlaubt."
  erlaubt "$e" prod-kern "$c" --trocken || fehler "Probe: prod-kern <commit> --trocken ist nicht erlaubt."
  erlaubt "$e" rueckweg beides || fehler "Probe: rueckweg beides ist nicht erlaubt."
  if erlaubt "$e" verteilen "${c:0:39}"; then fehler "Probe: ein Commit mit 39 Zeichen ist erlaubt."; fi
  if erlaubt "$e" verteilen "$c" --sofort; then fehler "Probe: eine fremde Option ist erlaubt."; fi
  if erlaubt "$e" status --json; then fehler "Probe: status mit Argument ist erlaubt."; fi
  if erlaubt "$e"; then fehler "Probe: der Einstieg ohne Befehl ist erlaubt."; fi
  if erlaubt /bin/bash; then fehler "Probe: /bin/bash ist erlaubt."; fi
  if erlaubt /usr/bin/systemctl restart wamo-core; then fehler "Probe: systemctl ist erlaubt."; fi
  echo "  sudo -l -U $BENUTZER: 4 erlaubte und 6 verbotene Proben wie erwartet"
}

sudoers() {
  schritt "6. sudoers /etc/sudoers.d/wais-deploy"
  local tmp
  if [ "$TROCKEN" = ja ]; then sudoers_text | sed 's/^/    /'; return 0; fi
  install -d -m 0750 "$(dirname "$SUDOERS")"
  # Dateien mit Punkt im Namen liest sudo nicht: die Probe liegt bis zur Prüfung unwirksam daneben
  tmp="$(mktemp "$(dirname "$SUDOERS")/.wais-deploy.XXXXXX")"
  sudoers_text > "$tmp"
  chmod 0440 "$tmp"
  besitz root:root "$tmp"
  visudo -c -q -f "$tmp" || { rm -f "$tmp"; fehler "visudo lehnt die Regeln ab: nichts installiert."; }
  mv -f "$tmp" "$SUDOERS"
  if ! visudo -c -q; then rm -f "$SUDOERS"; fehler "visudo -c meldet nach dem Einsetzen einen Fehler: Datei wieder entfernt."; fi
  echo "  installiert, visudo -c in Ordnung"
  if [ -z "$WURZEL" ]; then sudo_proben; fi
}

dienst_datei() {
  schritt "7. Dienst wais-runner.service"
  local tmp
  if [ "$TROCKEN" = ja ]; then plan "schreibt $UNIT (User=$BENUTZER, ExecStart=/opt/wais-runner/run.sh)"; return 0; fi
  install -d -m 0755 "$(dirname "$UNIT")"
  tmp="$(mktemp "$(dirname "$UNIT")/.wais-runner.XXXXXX")"
  unit_text > "$tmp"
  chmod 0644 "$tmp"
  besitz root:root "$tmp"
  mv -f "$tmp" "$UNIT"
  systemd-analyze verify "$UNIT" 2>&1 | sed 's/^/  verify: /' || true
  systemctl daemon-reload
  echo "  geschrieben"
}

haerten() {   # Dateien, die der Runner nur liest, gehören root: ein Job kann sie weder ändern noch ersetzen (Sticky-Bit des Ordners)
  local f
  for f in .env .path; do
    if [ -f "$RUNNER_DIR/$f" ]; then besitz root:root "$RUNNER_DIR/$f"; chmod 0644 "$RUNNER_DIR/$f"; fi
  done
}

registrierung() {
  schritt "8. Registrierung bei GitHub ($URL${GRUPPE:+, Gruppe $GRUPPE})"
  if [ -f "$RUNNER_DIR/.runner" ]; then echo "  besteht schon ($(runner_info)); neu nur nach rueckweg --abmelden"; return 0; fi
  if [ "$REGISTRIEREN" = nein ]; then echo "  übersprungen (--ohne-registrierung)"; return 0; fi
  if [ "$TROCKEN" = ja ]; then
    plan "liest das Registrierungstoken von stdin und ruft als $BENUTZER config.sh --unattended --url $URL --name $RUNNER_NAME"
    plan "--labels $RUNNER_LABEL --work /var/lib/wais-runner/arbeit --disableupdate --replace${GRUPPE:+ --runnergroup $GRUPPE} auf"
    return 0
  fi
  token_lesen "Registrierungstoken"
  local args=(--unattended --url "$URL" --name "$RUNNER_NAME" --labels "$RUNNER_LABEL" --work "$ARBEIT" --disableupdate --replace)
  if [ -n "$GRUPPE" ]; then args+=(--runnergroup "$GRUPPE"); fi
  # Das Token steht nur in der Umgebung dieser Unterschale (export ist eingebaut, kein Prozessargument); config.sh nimmt es aus
  # ACTIONS_RUNNER_INPUT_TOKEN und entfernt es dort aus seiner Umgebung.
  if ! ( export ACTIONS_RUNNER_INPUT_TOKEN="$TOKEN"; cd "$RUNNER_DIR" && runuser -u "$BENUTZER" -- ./config.sh "${args[@]}" ); then
    TOKEN=""
    fehler "config.sh ist fehlgeschlagen (Token abgelaufen? Es gilt eine Stunde): nichts gestartet."
  fi
  TOKEN=""
  haerten
  echo "  registriert: $(runner_info)"
}

starten() {
  schritt "9. Dienst starten"
  if [ "$TROCKEN" = ja ]; then plan "systemctl enable --now wais-runner.service"; return 0; fi
  if [ ! -f "$RUNNER_DIR/.runner" ]; then echo "  nicht gestartet: noch nicht registriert (einrichten ohne --ohne-registrierung)"; return 0; fi
  systemctl enable --now wais-runner.service
  if [ -z "$WURZEL" ]; then sleep 3; fi
  systemctl is-active --quiet wais-runner.service || fehler "wais-runner.service läuft nicht: journalctl -u wais-runner -n 50"
  echo "  läuft"
}

cmd_einrichten() {
  vorpruefung
  benutzer
  ordner
  runner_software
  einstieg
  quelle
  sudoers
  dienst_datei
  registrierung
  starten
  if [ "$TROCKEN" = ja ]; then echo "Trockenlauf: nichts geändert."; else echo "Fertig. Nächste Schritte: docs/runner-einrichten.md (Deploy-Key, Environments, erster Trockenlauf)."; fi
}

# ---------- status (nur lesend)
cmd_status() {
  local e_ist e_soll
  echo "== Runner"
  if getent passwd "$BENUTZER" >/dev/null; then echo "  Benutzer: $(getent passwd "$BENUTZER" | cut -d: -f1,6,7), Gruppen: $(id -nG "$BENUTZER")"; else echo "  Benutzer: fehlt"; fi
  if [ -f "$RUNNER_DIR/.wais-version" ]; then echo "  Software: $(cut -d' ' -f1 "$RUNNER_DIR/.wais-version") (Soll $RUNNER_VERSION)"; else echo "  Software: fehlt"; fi
  echo "  Registrierung: $(runner_info)"
  echo "  Dienst: $(systemctl is-enabled wais-runner.service 2>/dev/null || true), $(systemctl is-active wais-runner.service 2>/dev/null || true)"
  if [ -f "$SUDOERS" ]; then
    echo "  sudoers: vorhanden ($(stat -c '%a %U' "$SUDOERS")), visudo: $(visudo -c -q -f "$SUDOERS" >/dev/null 2>&1 && echo in Ordnung || echo FEHLER)"
  else
    echo "  sudoers: fehlt"
  fi
  if [ -f "$EINSTIEG" ]; then
    e_ist="$(sha256sum "$EINSTIEG" | cut -d' ' -f1)"
    e_soll="$(tr -d '\r' < "$HERE/wais-deploy.sh" | sha256sum | cut -d' ' -f1)"
    echo "  Einstieg: vorhanden, $([ "$e_ist" = "$e_soll" ] && echo "gleich dem Stand in $HERE" || echo "ANDERS als $HERE/wais-deploy.sh (einrichten erneut)")"
  else
    echo "  Einstieg: fehlt"
  fi
  if [ -f "$ETC/quelle.conf" ]; then echo "  Quelle: $(grep '^QUELLE_URL=' "$ETC/quelle.conf" || echo ungültig)"; else echo "  Quelle: fehlt"; fi
  if [ -f "$ETC/deploy_key.pub" ]; then echo "  Lese-Schlüssel: $(ssh-keygen -l -f "$ETC/deploy_key.pub" 2>/dev/null || echo nicht lesbar)"; else echo "  Lese-Schlüssel: fehlt"; fi
  if [ -z "$WURZEL" ] && [ -f "$SUDOERS" ] && [ -x "$EINSTIEG" ]; then sudo_proben || true; fi
}

# ---------- rueckweg
cmd_rueckweg() {
  schritt "Rückweg des Runners"
  if [ -e "$DEPLOY_SPERRE" ] && ! flock -n "$DEPLOY_SPERRE" true; then fehler "Ein Ausrollen läuft gerade (Sperre $DEPLOY_SPERRE): erst abwarten."; fi
  if [ "$TROCKEN" = ja ]; then
    plan "entfernt /etc/sudoers.d/wais-deploy, stoppt und entfernt wais-runner.service"
    if [ "$ABMELDEN" = ja ]; then plan "liest das Entfernungstoken von stdin und meldet den Runner mit config.sh remove ab"; fi
    plan "entfernt /opt/wais-runner, /var/lib/wais-runner, den Benutzer $BENUTZER und $EINSTIEG_PFAD"
    if [ "$ALLES" = ja ]; then plan "entfernt auch /etc/wais-deploy (Lese-Schlüssel) und /var/lib/wais-deploy (Spiegel, Stände, Zustand)"; fi
    echo "Trockenlauf: nichts geändert."
    return 0
  fi
  if [ -f "$SUDOERS" ]; then rm -f "$SUDOERS"; visudo -c -q || echo "  Hinweis: visudo -c meldet einen Fehler in anderen Dateien" >&2; echo "  sudoers entfernt"; fi
  if [ -f "$UNIT" ]; then
    systemctl disable --now wais-runner.service >/dev/null 2>&1 || true
    rm -f "$UNIT"
    systemctl daemon-reload
    echo "  Dienst gestoppt und entfernt"
  fi
  if [ "$ABMELDEN" = ja ]; then
    if [ -f "$RUNNER_DIR/.runner" ] && getent passwd "$BENUTZER" >/dev/null; then
      token_lesen "Entfernungstoken"
      if ( export ACTIONS_RUNNER_INPUT_TOKEN="$TOKEN"; cd "$RUNNER_DIR" && runuser -u "$BENUTZER" -- ./config.sh remove ); then
        echo "  bei GitHub abgemeldet"
      else
        echo "  Abmelden fehlgeschlagen: den Runner $RUNNER_NAME in GitHub unter Settings, Actions, Runners entfernen" >&2
      fi
      TOKEN=""
    else
      echo "  nicht registriert, nichts abzumelden"
    fi
  fi
  if getent passwd "$BENUTZER" >/dev/null; then
    pkill -u "$BENUTZER" 2>/dev/null || true
    if [ -z "$WURZEL" ]; then sleep 2; fi
    userdel "$BENUTZER"
    echo "  Benutzer $BENUTZER entfernt"
  fi
  rm -rf "${RUNNER_DIR:?}" "${HOME_DIR:?}"
  rm -f "$EINSTIEG"
  echo "  Runner-Software, Home und Einstieg entfernt"
  if [ "$ALLES" = ja ]; then
    rm -rf "${ETC:?}" "${DATEN:?}"
    echo "  /etc/wais-deploy und /var/lib/wais-deploy entfernt"
  fi
  echo "Fertig. Das Protokoll /var/log/wais-deploy bleibt. In GitHub: Deploy-Key $RUNNER_NAME löschen und, falls nicht abgemeldet, den Runner entfernen."
}

case "$BEFEHL" in
  einrichten) cmd_einrichten ;;
  status) cmd_status ;;
  rueckweg) cmd_rueckweg ;;
esac
