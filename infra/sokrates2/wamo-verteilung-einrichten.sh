#!/usr/bin/env bash
# Installer vom Server: Ablage der Installationsdatei der Desktop-App auf Sokrates-2 (Paket P2, docs/ausrollen-neue-nutzer.md, Abschnitt 4.2).
# Der Kern (Benutzer wamo-core) liest die Ablage nur. Dieses Skript setzt neue Stände ein, zeigt den Zustand und stellt den vorigen Stand wieder her.
# Es startet nichts neu, gibt dem Kern keine Einstellung und kennt keine Geheimnisse. Nur als root (sudo). Die Prüfregel des Manifests steht in
# wamo_verteilung_manifest.py (dieselbe Regel nutzt das lokale Werkzeug scripts/wamo_installer_sokrates2.py), die Signatur prüft openssl.
#
#   wamo-verteilung-einrichten.sh einsetzen <eingangsordner> [--trocken]
#       Der Eingang (aktuell.json, optional aktuell.json.sig, WAIS-Setup-<Version>.exe, sonst nichts und keine Links) gehört dem Benutzer wamocon.
#       Das Skript kopiert ihn zuerst in einen eigenen Zwischenordner und prüft nur die Kopien: Manifest, Dateiname, Größe, SHA-256, Signatur und eine
#       streng steigende Version gegenüber aktuell. Dann legt es staende/<Version>/ an (gibt es den Ordner schon mit gleichem Inhalt, wird er
#       wiederverwendet), stellt vorher auf den bisherigen und aktuell auf den neuen Stand (je atomar) und löscht ältere Stände, sodass höchstens drei
#       bleiben (aktuell, vorher und einer mehr). Eine Zeile geht ins Journal (logger -t wamo-verteilung). --trocken prüft alles und ändert nichts.
#   wamo-verteilung-einrichten.sh status [--json]
#       Version, SHA-256, Signatur und Zustand der Datei von aktuell und vorher, alle Stände, ob es die Schlüsselliste gibt. --json gibt genau eine
#       Zeile JSON aus (für das lokale Werkzeug).
#   wamo-verteilung-einrichten.sh rueckweg [--trocken] [--ohne-signatur]
#       Stellt aktuell atomar auf vorher. Danach gibt es kein vorher mehr, der bisherige Stand bleibt liegen. Ohne vorher bricht es ab. Liegt die
#       Schlüsselliste und ist der vorige Stand nicht gültig signiert (etwa 0.2.0), bricht es ab; nur mit --ohne-signatur geht es dann (bewusst,
#       mit Warnung und Eintrag im Journal).
#
# Signatur: Liegt die Schlüsselliste /etc/wamo-verteilung/update-schluessel.json (root:root 0644, JSON-Liste von Base64-Texten zu je 32 Byte Ed25519),
# ist eine gültige Signatur Pflicht, sie muss zu einem Schlüssel der Liste passen. Fehlt die Liste, geht ein unsignierter Stand mit einer deutlichen
# Warnung durch (Übergang für 0.2.0). Eine vorhandene, aber kaputte Liste hält alles an.
#
# Aufbau auf dem Server:
#   /var/lib/wamo-verteilung/                             root:wamo-core 0750
#   /var/lib/wamo-verteilung/staende/                     root:wamo-core 0750
#   /var/lib/wamo-verteilung/staende/<Version>/           root:wamo-core 0750, darin aktuell.json, [aktuell.json.sig], WAIS-Setup-<Version>.exe (je 0640)
#   /var/lib/wamo-verteilung/aktuell -> staende/<Version> relativer Link auf den ausgelieferten Stand
#   /var/lib/wamo-verteilung/vorher  -> staende/<Version> relativer Link auf den vorigen Stand (fehlt nach einem Rückweg)
#   /run/wamo-verteilung/lock                             Sperre gegen parallele Läufe von einsetzen und rueckweg (flock)
# Exit-Codes: 0 ok, 1 Fehler (nichts an der Ablage geändert), 2 falsche Aufrufform, 3 Vorbedingung nicht erfüllt.
#
#   ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wamo-verteilung-einrichten.sh einsetzen ~/wamo-verteilung-eingang/0.3.0 --trocken"
#   ssh wamo-sokrates2 "sudo bash ~/wamo-infra/wamo-verteilung-einrichten.sh status"
#
# Probelauf ohne root in einem Wegwerf-Ordner (kein chown, keine Prüfung von Benutzer und Gruppe; unter Git Bash mit echten Links über
# MSYS=winsymlinks:nativestrict, dort Rechte 0755 und 0644, weil Git Bash 0750 nicht setzen kann):
#   WAMO_VERTEILUNG_WURZEL=/tmp/probe WAMO_VERTEILUNG_PYTHON=python3 bash wamo-verteilung-einrichten.sh status
set -euo pipefail
umask 077
export LC_ALL=C

HERE="$(cd "$(dirname "$0")" && pwd)"
WURZEL="${WAMO_VERTEILUNG_WURZEL:-}"   # nur für den Probelauf; leer ist das echte System
MODUL="$HERE/wamo_verteilung_manifest.py"
BASIS="$WURZEL/var/lib/wamo-verteilung"
STAENDE="$BASIS/staende"
SCHLUESSEL="$WURZEL/etc/wamo-verteilung/update-schluessel.json"
ZWISCHEN_ORT="$WURZEL/var/tmp"
SPERR_ORDNER="$WURZEL/run/wamo-verteilung"
KERN_GRUPPE=wamo-core
PYTHON=/usr/bin/python3
PY_OPT=(-X utf8 -B -I)   # UTF-8, keine Bytecode-Dateien, isoliert (keine Umgebungsvariablen, der Ordner des Moduls nicht im Suchpfad)
VERSION_RE='^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$'
EXE_RE='^WAIS-Setup-[0-9.]{5,14}\.exe$'
MAX_GROESSE=536870912
MAX_STAENDE=3
ORDNER_MODUS=0750
DATEI_MODUS=0640
SPERR_MODUS=0700
BESITZ=(-o root -g "$KERN_GRUPPE")
ROOT_BESITZ=(-o root -g root)
if [ -n "$WURZEL" ]; then
  BESITZ=()
  ROOT_BESITZ=()
  PYTHON="${WAMO_VERTEILUNG_PYTHON:-python3}"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      ORDNER_MODUS=0755
      DATEI_MODUS=0644
      SPERR_MODUS=0755
      export MSYS="${MSYS:+$MSYS }winsymlinks:nativestrict" ;;
  esac
fi

BEFEHL="${1:-}"
[ "$#" -eq 0 ] || shift
EINGANG=""
TROCKEN=nein
OHNE_SIGNATUR=nein
JSON=nein
ZWISCHEN=""
NEU=""
EXE=""
VERSION=""
SHA=""
SIG_STAND=""
SCHLUESSEL_DA=nein
LINK_VERSION=""
STAND_JSON=null
STATUS_FEHLER=nein

fehler() { echo "wamo-verteilung: $*" >&2; exit 1; }
vorbedingung() { echo "wamo-verteilung: Vorbedingung nicht erfüllt: $*" >&2; exit 3; }
aufruf() {
  echo "wamo-verteilung: $*" >&2
  echo "Aufruf: $0 einsetzen <eingangsordner> [--trocken] | status [--json] | rueckweg [--trocken] [--ohne-signatur]" >&2
  exit 2
}
hinweis() { echo "$*" >&2; }
warnung() { echo "WARNUNG: $*" >&2; }
plan() { printf '  [trocken] %s\n' "$*"; }

if [ "$BEFEHL" = einsetzen ]; then
  case "${1:-}" in
    "") aufruf "einsetzen verlangt den Eingangsordner" ;;
    /*) EINGANG="$1"; shift ;;
    *) aufruf "der Eingangsordner muss ein absoluter Pfad sein" ;;
  esac
fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    --trocken) [ "$BEFEHL" = einsetzen ] || [ "$BEFEHL" = rueckweg ] || aufruf "--trocken gibt es nur bei einsetzen und rueckweg"; TROCKEN=ja ;;
    --json) [ "$BEFEHL" = status ] || aufruf "--json gibt es nur bei status"; JSON=ja ;;
    --ohne-signatur) [ "$BEFEHL" = rueckweg ] || aufruf "--ohne-signatur gibt es nur bei rueckweg"; OHNE_SIGNATUR=ja ;;
    *) aufruf "unbekannte Angabe: $1" ;;
  esac
  shift
done
case "$BEFEHL" in einsetzen|status|rueckweg) ;; *) aufruf "Unterbefehl fehlt oder ist unbekannt" ;; esac
ZUSATZ=""
[ "$TROCKEN" = nein ] || ZUSATZ=" (Trockenlauf)"

# Schutz gegen untergeschobene Dateien (wie in den übrigen Einrichtungsskripten): Der Ordner dieses Skripts, sein Elternordner und alles darin
# (auch wamo_verteilung_manifest.py, das hier als root läuft) müssen dem Aufrufer, bei sudo dem aufrufenden Benutzer, oder root gehören und dürfen
# weder für die Gruppe noch für alle beschreibbar sein. Symbolische Links sind nicht erlaubt.
pruefe_herkunft() {
  local erlaubt uid modus pfad
  erlaubt=" 0 $(id -u) ${SUDO_UID:-} "
  while read -r uid modus pfad; do
    if [[ "$erlaubt" != *" $uid "* ]] || (( 8#$modus & 8#022 )); then
      echo "Unsicherer Ablageort: $pfad (Besitzer $uid, Rechte $modus). Ordner im eigenen Home ablegen und" \
        "mit chmod -R go-w schützen." >&2
      exit 1
    fi
  done < <(stat -c '%u %a %n' "$(dirname "$HERE")"; find "$HERE" \( -type l -printf '%U 777 %p\n' \) -o -printf '%U %m %p\n')
}

if [ -z "$WURZEL" ]; then
  [ "$(id -u)" -eq 0 ] || fehler "Bitte als root ausführen (sudo)."
  pruefe_herkunft
  getent group "$KERN_GRUPPE" >/dev/null || vorbedingung "Die Gruppe $KERN_GRUPPE fehlt (zuerst den Kern einrichten)."
  [ -x "$PYTHON" ] || vorbedingung "$PYTHON fehlt."
else
  # Der Probelauf schreibt nur in einen Wegwerf-Ordner und läuft nie als root (sonst könnte eine gesetzte Variable das Skript auf fremde Pfade lenken).
  [ "$(id -u)" -ne 0 ] || fehler "Der Probelauf (WAMO_VERTEILUNG_WURZEL) läuft nicht als root."
  case "$WURZEL" in
    /|*//*|*/..|*/../*|*/.|*/./*|*[!A-Za-z0-9._/-]*|[!/]*)
      fehler "WAMO_VERTEILUNG_WURZEL muss ein absoluter Ordner aus A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich und Schrägstrich ohne // und ohne . oder .. sein." ;;
  esac
  hinweis "Probelauf unter $WURZEL (kein root, kein chown, Rechte der Testmaschine)"
  mkdir -p "$ZWISCHEN_ORT"
fi
[ -f "$MODUL" ] && [ ! -L "$MODUL" ] || vorbedingung "$MODUL fehlt (infra/sokrates2 vollständig nach ~/wamo-infra verteilen)."

aufraeumen() {
  case "$ZWISCHEN" in "$ZWISCHEN_ORT"/wamo-verteilung.*) rm -rf -- "$ZWISCHEN" ;; esac
  case "$NEU" in "$STAENDE"/.neu-*) rm -rf -- "$NEU" ;; esac
  rm -f -- "$BASIS/.aktuell.neu" "$BASIS/.vorher.neu" 2>/dev/null || true
}
trap aufraeumen EXIT

py() { "$PYTHON" "${PY_OPT[@]}" "$MODUL" "$@"; }

journal() {   # eine Zeile ins Journal (Kennung wamo-verteilung), nie Inhalte
  if command -v logger >/dev/null 2>&1; then
    logger -t wamo-verteilung -- "$*" || hinweis "Hinweis: logger meldet einen Fehler, die Zeile fehlt im Journal."
  else
    hinweis "Hinweis: logger fehlt, die Zeile fehlt im Journal: $*"
  fi
}

nur_root_schreibbar() {   # jeder Pfad gehört root und ist weder für die Gruppe noch für alle beschreibbar
  local p uid modus
  for p in "$@"; do
    read -r uid modus < <(stat -c '%u %a' "$p") || return 1
    if [ "$uid" != 0 ] || (( 8#$modus & 8#022 )); then return 1; fi
  done
}

zwischen_anlegen() {   # root-eigener Zwischenordner (mktemp -d, 0700) für die Kopie der Lieferung, Schlüssel und Signatur
  [ -z "$ZWISCHEN" ] || return 0
  [ -d "$ZWISCHEN_ORT" ] && [ ! -L "$ZWISCHEN_ORT" ] || vorbedingung "$ZWISCHEN_ORT fehlt oder ist ein Link."
  ZWISCHEN="$(mktemp -d "$ZWISCHEN_ORT/wamo-verteilung.XXXXXX")"
}

sperre_nehmen() {   # gegen parallele Läufe von einsetzen und rueckweg; die Sperre endet mit dem Prozess
  if ! command -v flock >/dev/null 2>&1; then
    [ -n "$WURZEL" ] || vorbedingung "flock fehlt (Paket util-linux)."
    hinweis "Probelauf: flock fehlt, der Lauf nimmt keine Sperre."
    return 0
  fi
  [ ! -L "$SPERR_ORDNER" ] || vorbedingung "$SPERR_ORDNER ist ein Link: nichts angefasst."
  install -d -m "$SPERR_MODUS" "${ROOT_BESITZ[@]}" "$SPERR_ORDNER"
  exec 9>>"$SPERR_ORDNER/lock"
  flock -n 9 || fehler "Ein anderer Lauf hält die Sperre $SPERR_ORDNER/lock. Später noch einmal versuchen. Nichts wurde geändert."
}

# ---------------------------------------------------------------- Ablage lesen
ablage_pruefen() {   # nie in einen Link oder an die falsche Stelle schreiben
  local p
  for p in "$BASIS" "$STAENDE"; do
    [ ! -L "$p" ] || vorbedingung "$p ist ein Link: nichts angefasst."
    [ ! -e "$p" ] || [ -d "$p" ] || vorbedingung "$p ist kein Ordner: nichts angefasst."
  done
}

link_lesen() {   # $1 aktuell oder vorher: setzt LINK_VERSION (leer ohne Link); alles andere als ein Link auf staende/<Version> hält an
  local pfad="$BASIS/$1" ziel v
  LINK_VERSION=""
  if [ ! -L "$pfad" ]; then
    [ ! -e "$pfad" ] || vorbedingung "$pfad ist kein Link: nichts angefasst."
    return 0
  fi
  ziel="$(readlink -- "$pfad")"
  v="${ziel#staende/}"
  if [ "$ziel" != "staende/$v" ] || ! [[ "$v" =~ $VERSION_RE ]]; then
    vorbedingung "$pfad zeigt nicht auf einen Stand (staende/<Version>): nichts angefasst."
  fi
  [ -d "$STAENDE/$v" ] && [ ! -L "$STAENDE/$v" ] || vorbedingung "$pfad zeigt auf den fehlenden Stand $v: nichts angefasst."
  LINK_VERSION="$v"
}

schluessel_pruefen() {   # setzt SCHLUESSEL_DA; eine vorhandene Liste muss root gehören und gültig sein, sonst hält alles an
  SCHLUESSEL_DA=nein
  if [ ! -e "$SCHLUESSEL" ] && [ ! -L "$SCHLUESSEL" ]; then return 0; fi
  [ -f "$SCHLUESSEL" ] && [ ! -L "$SCHLUESSEL" ] || fehler "Die Schlüsselliste $SCHLUESSEL ist keine reguläre Datei (Links sind nicht erlaubt)."
  if [ -z "$WURZEL" ] && ! nur_root_schreibbar "$(dirname "$SCHLUESSEL")" "$SCHLUESSEL"; then
    fehler "Die Schlüsselliste $SCHLUESSEL und ihr Ordner müssen root gehören und dürfen nur für root beschreibbar sein."
  fi
  command -v openssl >/dev/null 2>&1 || vorbedingung "openssl fehlt, ohne openssl lässt sich die Signatur nicht prüfen."
  zwischen_anlegen
  mkdir "$ZWISCHEN/schluessel"
  py pem "$SCHLUESSEL" "$ZWISCHEN/schluessel" >/dev/null \
    || fehler "Die Schlüsselliste $SCHLUESSEL ist ungültig (siehe oben), an der Ablage wurde nichts geändert."
  SCHLUESSEL_DA=ja
}

signatur_stand() {   # $1 Ordner mit aktuell.json: setzt SIG_STAND auf keine, ungeprueft (keine Liste), gueltig oder ungueltig
  local ordner="$1" pem ausgabe
  if [ ! -e "$ordner/aktuell.json.sig" ] && [ ! -L "$ordner/aktuell.json.sig" ]; then SIG_STAND=keine; return 0; fi
  zwischen_anlegen
  rm -f -- "$ZWISCHEN/signatur.bin"
  if ! py signatur "$ordner/aktuell.json.sig" "$ZWISCHEN/signatur.bin"; then SIG_STAND=ungueltig; return 0; fi
  if [ "$SCHLUESSEL_DA" != ja ]; then SIG_STAND=ungeprueft; return 0; fi
  for pem in "$ZWISCHEN"/schluessel/schluessel-*.pem; do
    if ausgabe="$(openssl pkeyutl -verify -pubin -inkey "$pem" -rawin -in "$ordner/aktuell.json" -sigfile "$ZWISCHEN/signatur.bin" 2>/dev/null)" \
      && [ "${ausgabe%$'\r'}" = "Signature Verified Successfully" ]; then
      SIG_STAND=gueltig
      return 0
    fi
  done
  SIG_STAND=ungueltig
}

# ---------------------------------------------------------------- Einsetzen
eingang_kopieren() {   # nur reguläre Dateien mit erlaubtem Namen; kopiert ohne Links zu folgen, geprüft werden danach nur die Kopien
  local name groesse
  [ -d "$EINGANG" ] && [ ! -L "$EINGANG" ] || fehler "Der Eingang $EINGANG ist kein Ordner oder ist ein Link. Nichts wurde geändert."
  while IFS= read -r -d '' name; do
    case "$name" in
      aktuell.json|aktuell.json.sig) ;;
      *)
        if [[ "$name" =~ $EXE_RE ]] && [ -z "$EXE" ]; then
          EXE="$name"
        else
          fehler "Fremde Datei im Eingang: $(printf '%q' "$name"). Erlaubt sind nur aktuell.json, aktuell.json.sig und genau eine" \
            "WAIS-Setup-<Version>.exe. Nichts wurde geändert."
        fi ;;
    esac
    [ -f "$EINGANG/$name" ] && [ ! -L "$EINGANG/$name" ] \
      || fehler "Im Eingang ist $name keine reguläre Datei (Links und Ordner sind nicht erlaubt). Nichts wurde geändert."
  done < <(find "$EINGANG" -mindepth 1 -maxdepth 1 -printf '%f\0')
  [ -f "$EINGANG/aktuell.json" ] || fehler "Im Eingang fehlt aktuell.json. Nichts wurde geändert."
  [ -n "$EXE" ] || fehler "Im Eingang fehlt die Installationsdatei WAIS-Setup-<Version>.exe. Nichts wurde geändert."
  groesse="$(stat -c %s -- "$EINGANG/$EXE")"
  [ "$groesse" -le "$MAX_GROESSE" ] || fehler "Die Installationsdatei ist größer als $MAX_GROESSE Byte. Nichts wurde geändert."
  mkdir "$ZWISCHEN/lieferung"
  for name in aktuell.json aktuell.json.sig "$EXE"; do
    [ -e "$EINGANG/$name" ] || [ -L "$EINGANG/$name" ] || continue
    [ -f "$EINGANG/$name" ] && [ ! -L "$EINGANG/$name" ] \
      || fehler "$name war beim Kopieren keine reguläre Datei mehr. Nichts wurde geändert."
    # höchstens ein Byte mehr als erlaubt kopieren: eine nachwachsende Datei im Eingang füllt so nie den Zwischenordner
    head -c "$((MAX_GROESSE + 1))" -- "$EINGANG/$name" >"$ZWISCHEN/lieferung/$name"
    [ "$(stat -c %s -- "$ZWISCHEN/lieferung/$name")" -le "$MAX_GROESSE" ] \
      || fehler "$name ist beim Kopieren über $MAX_GROESSE Byte gewachsen. Nichts wurde geändert."
  done
}

lieferung_pruefen() {   # Manifest, Dateiname, Größe und SHA-256 der Kopie; setzt VERSION und SHA
  local ausgabe zeile commit zustand
  ausgabe="$(py pruefen "$ZWISCHEN/lieferung/aktuell.json" "$ZWISCHEN/lieferung/$EXE")" \
    || fehler "Die Lieferung besteht die Prüfung nicht (siehe oben). Nichts wurde geändert."
  echo "  $ausgabe"
  zeile="$(py stand "$ZWISCHEN/lieferung")" || fehler "Das Manifest der Lieferung ist ungültig. Nichts wurde geändert."
  read -r VERSION SHA _ commit zustand <<<"$zeile"
  [[ "$VERSION" =~ $VERSION_RE ]] && [[ "$SHA" =~ ^[0-9a-f]{64}$ ]] && [ "$zustand" = ok ] \
    || fehler "Die Lieferung besteht die Prüfung nicht (Version $VERSION, Datei $zustand). Nichts wurde geändert."
  echo "  Commit $commit"
}

signatur_regel() {   # Lieferung im Zwischenordner: mit Schlüsselliste ist eine gültige Signatur Pflicht, ohne Liste geht es mit Warnung durch
  signatur_stand "$ZWISCHEN/lieferung"
  case "$SIG_STAND:$SCHLUESSEL_DA" in
    gueltig:ja) echo "  Signatur: gültig (passt zu einem Schlüssel der Liste $SCHLUESSEL)" ;;
    keine:ja) fehler "Die Signatur fehlt. Mit der Schlüsselliste $SCHLUESSEL ist eine gültige Signatur Pflicht. Nichts wurde geändert." ;;
    ungueltig:ja) fehler "Die Signatur passt zu keinem Schlüssel der Liste $SCHLUESSEL. Nichts wurde geändert." ;;
    ungueltig:nein) fehler "Die Signaturdatei aktuell.json.sig ist ungültig (siehe oben). Nichts wurde geändert." ;;
    ungeprueft:nein)
      warnung "Signatur vorhanden, aber nicht geprüft: Es gibt keine Schlüsselliste ($SCHLUESSEL). Der Stand geht nur als Übergang durch."
      echo "  Signatur: vorhanden, nicht geprüft (keine Schlüsselliste)" ;;
    *)
      warnung "unsignierter Stand. Es gibt keine Schlüsselliste ($SCHLUESSEL), deshalb geht er nur als Übergang (0.2.0) durch."
      echo "  Signatur: keine (unsigniert)" ;;
  esac
}

gleicher_stand() {   # $1 vorhandener Ordner: dieselben Dateien wie die Lieferung, Manifest und Signatur Byte für Byte gleich, Datei mit gleicher Prüfsumme
  local d="$1" name
  for name in aktuell.json aktuell.json.sig "$EXE"; do
    if [ -e "$ZWISCHEN/lieferung/$name" ]; then
      [ -f "$d/$name" ] && [ ! -L "$d/$name" ] || return 1
    elif [ -e "$d/$name" ] || [ -L "$d/$name" ]; then
      return 1
    fi
  done
  [ "$(find "$d" -mindepth 1 -maxdepth 1 | wc -l)" -eq "$(find "$ZWISCHEN/lieferung" -mindepth 1 -maxdepth 1 | wc -l)" ] || return 1
  cmp -s "$ZWISCHEN/lieferung/aktuell.json" "$d/aktuell.json" || return 1
  if [ -e "$ZWISCHEN/lieferung/aktuell.json.sig" ]; then cmp -s "$ZWISCHEN/lieferung/aktuell.json.sig" "$d/aktuell.json.sig" || return 1; fi
  py pruefen "$d/aktuell.json" "$d/$EXE" >/dev/null 2>&1
}

link_setzen() {   # $1 aktuell oder vorher, $2 Ziel (staende/<Version>): neuen Link anlegen, dann mit mv -T atomar tauschen
  local neu="$BASIS/.$1.neu"
  rm -f -- "$neu"
  ln -s -- "$2" "$neu"
  [ -L "$neu" ] || fehler "$neu ist kein symbolischer Link geworden (unter Git Bash fehlt MSYS=winsymlinks:nativestrict)."
  mv -T -- "$neu" "$BASIS/$1"
}

staende_aufraeumen() {   # $1 neue aktuelle Version, $2 vorige oder leer, $3 ja: nur zeigen. Behält aktuell, vorher und den jüngsten weiteren Stand.
  local neu="$1" vor="$2" zeigen="$3" frei v liste=()
  frei=$((MAX_STAENDE - 1))
  [ -z "$vor" ] || frei=$((frei - 1))
  [ -d "$STAENDE" ] || return 0
  while IFS= read -r -d '' v; do
    [[ "$v" =~ $VERSION_RE ]] && [ "$v" != "$neu" ] && [ "$v" != "$vor" ] || continue
    [ -d "$STAENDE/$v" ] && [ ! -L "$STAENDE/$v" ] || continue
    liste+=("$v")
  done < <(find "$STAENDE" -mindepth 1 -maxdepth 1 -printf '%f\0')
  [ "${#liste[@]}" -gt 0 ] || return 0
  while IFS= read -r v; do
    if [ "$frei" -gt 0 ]; then frei=$((frei - 1)); continue; fi
    if [ "$zeigen" = ja ]; then
      plan "Stand $v entfernen (höchstens $MAX_STAENDE Stände bleiben)"
    else
      rm -rf -- "${STAENDE:?}/$v"
      echo "  Stand $v entfernt (höchstens $MAX_STAENDE Stände bleiben)"
    fi
  done < <(py sortieren "${liste[@]}")
}

einsetzen() {
  local alt vor ziel wieder=nein name
  echo "== Installer einsetzen$ZUSATZ"
  ablage_pruefen
  sperre_nehmen
  link_lesen aktuell
  alt="$LINK_VERSION"
  link_lesen vorher
  vor="$LINK_VERSION"
  [ -n "$alt" ] || [ -z "$vor" ] || vorbedingung "vorher gibt es, aktuell nicht: unerwarteter Zustand, nichts angefasst."
  if [ -n "$alt" ] && [ "$(py version "$STAENDE/$alt/aktuell.json")" != "$alt" ]; then
    vorbedingung "Der aktuelle Stand $alt passt nicht zu seinem Manifest: nichts angefasst."
  fi
  schluessel_pruefen
  zwischen_anlegen
  echo "== Lieferung aus $EINGANG (geprüft wird nur die Kopie im Zwischenordner)"
  eingang_kopieren
  lieferung_pruefen
  signatur_regel
  if [ -n "$alt" ]; then
    [ "$(py vergleich "$VERSION" "$alt")" = groesser ] \
      || fehler "Version $VERSION ist nicht neuer als der aktuelle Stand $alt. Einsetzen geht nur mit streng steigender Version. Nichts wurde geändert."
    echo "  Version $VERSION, bisher $alt"
  else
    echo "  Version $VERSION, bisher kein Stand"
  fi
  ziel="$STAENDE/$VERSION"
  if [ -e "$ziel" ] || [ -L "$ziel" ]; then
    [ -d "$ziel" ] && [ ! -L "$ziel" ] || vorbedingung "$ziel ist kein Ordner: nichts angefasst."
    gleicher_stand "$ziel" || fehler "Unter $ziel liegt schon ein Stand $VERSION mit anderem Inhalt. Nichts wurde geändert."
    wieder=ja
    echo "  Stand $VERSION liegt schon mit gleicher Prüfsumme in $ziel und wird wiederverwendet."
  fi
  if [ "$TROCKEN" = ja ]; then
    [ "$wieder" = ja ] || plan "Ordner $ziel anlegen (root:$KERN_GRUPPE 0750), Dateien root:$KERN_GRUPPE 0640"
    [ -z "$alt" ] || plan "vorher -> staende/$alt (atomar)"
    plan "aktuell -> staende/$VERSION (atomar)"
    staende_aufraeumen "$VERSION" "$alt" ja
    echo "  Trockenlauf: es wurde nichts geändert."
    return 0
  fi
  [ -z "$WURZEL" ] || mkdir -p "$WURZEL/var/lib"
  install -d -m "$ORDNER_MODUS" "${BESITZ[@]}" "$BASIS" "$STAENDE"
  if [ "$wieder" = nein ]; then
    NEU="$STAENDE/.neu-$VERSION"
    rm -rf -- "$NEU"
    install -d -m "$ORDNER_MODUS" "${BESITZ[@]}" "$NEU"
    for name in aktuell.json aktuell.json.sig "$EXE"; do
      [ -e "$ZWISCHEN/lieferung/$name" ] || continue
      install -m "$DATEI_MODUS" "${BESITZ[@]}" "$ZWISCHEN/lieferung/$name" "$NEU/$name"
    done
    py pruefen "$NEU/aktuell.json" "$NEU/$EXE" >/dev/null || fehler "Die Kopie in $NEU besteht die Prüfung nicht. aktuell ist unverändert."
    mv -T -- "$NEU" "$ziel"
    NEU=""
    echo "  Stand $VERSION abgelegt: $ziel"
  fi
  [ -z "$alt" ] || link_setzen vorher "staende/$alt"
  link_setzen aktuell "staende/$VERSION"
  echo "  aktuell -> staende/$VERSION${alt:+, vorher -> staende/$alt}"
  staende_aufraeumen "$VERSION" "$alt" nein
  journal "einsetzen version=$VERSION sha256=$SHA signatur=$SIG_STAND vorher=${alt:-keiner}"
  echo "  Eingesetzt. Der Kern liest die Ablage nur, er wird hier nie neu gestartet."
}

# ---------------------------------------------------------------- Rückweg
rueckweg() {
  local alt ziel zeile v s g c z
  echo "== Rückweg$ZUSATZ"
  ablage_pruefen
  sperre_nehmen
  link_lesen aktuell
  alt="$LINK_VERSION"
  link_lesen vorher
  ziel="$LINK_VERSION"
  [ -n "$ziel" ] || vorbedingung "kein voriger Stand vorhanden (vorher fehlt), ein Rückweg ist nicht möglich."
  [ -n "$alt" ] || vorbedingung "vorher gibt es, aktuell nicht: unerwarteter Zustand, nichts angefasst."
  zeile="$(py stand "$STAENDE/$ziel")" || fehler "Der vorige Stand $ziel hat kein gültiges Manifest (siehe oben). Nichts wurde geändert."
  read -r v s g c z <<<"$zeile"
  [ "$v" = "$ziel" ] || fehler "Der vorige Stand $ziel passt nicht zu seinem Manifest. Nichts wurde geändert."
  [ "$z" = ok ] || fehler "Die Installationsdatei des vorigen Stands $ziel ist $z (Größe oder SHA-256). Nichts wurde geändert."
  schluessel_pruefen
  signatur_stand "$STAENDE/$ziel"
  if [ "$SCHLUESSEL_DA" = ja ] && [ "$SIG_STAND" != gueltig ]; then
    [ "$OHNE_SIGNATUR" = ja ] || fehler "Der vorige Stand $ziel ist nicht gültig signiert (Signatur: $SIG_STAND), die Schlüsselliste liegt" \
      "aber. Nur bewusst mit --ohne-signatur. Nichts wurde geändert."
    warnung "Der vorige Stand $ziel ist nicht gültig signiert (Signatur: $SIG_STAND), Rückweg auf ausdrücklichen Wunsch (--ohne-signatur)."
  fi
  echo "  aktuell: $alt, zurück auf: $ziel (SHA-256 $s, $g Byte, Commit $c)"
  if [ "$TROCKEN" = ja ]; then
    plan "aktuell -> staende/$ziel (atomar)"
    plan "vorher entfernen, der Stand $alt bleibt liegen"
    echo "  Trockenlauf: es wurde nichts geändert."
    return 0
  fi
  link_setzen aktuell "staende/$ziel"
  rm -f -- "$BASIS/vorher"
  journal "rueckweg aktuell=$ziel zuvor=$alt signatur=$SIG_STAND"
  echo "  Zurückgesetzt: aktuell -> staende/$ziel. Es gibt jetzt kein vorher mehr, der Stand $alt bleibt liegen."
}

# ---------------------------------------------------------------- Status
datei_text() {
  case "$1" in
    ok) echo "geprüft (Größe und SHA-256 stimmen)" ;;
    fehlt) echo "FEHLT" ;;
    *) echo "ABWEICHEND (Größe oder SHA-256)" ;;
  esac
}

stand_zeigen() {   # $1 aktuell oder vorher, $2 Version oder leer: eine Zeile Text oder STAND_JSON
  local name="$1" v="$2" zeile s g c z signiert
  STAND_JSON=null
  if [ -z "$v" ]; then
    [ "$JSON" = ja ] || echo "  $name: keiner"
    return 0
  fi
  if ! zeile="$(py stand "$STAENDE/$v")"; then
    [ "$JSON" = nein ] || fehler "Der Stand $v ($name) hat kein gültiges Manifest."
    echo "  $name: $v, UNGÜLTIG (Manifest, siehe oben)"
    STATUS_FEHLER=ja
    return 0
  fi
  read -r _ s g c z <<<"$zeile"
  [[ "$s" =~ ^[0-9a-f]{64}$ ]] && [[ "$g" =~ ^[1-9][0-9]{0,8}$ ]] && [[ "$c" =~ ^[0-9a-f]{40}$ ]] \
    && [[ "$z" =~ ^(ok|fehlt|abweichend)$ ]] || fehler "Unerwartete Antwort der Prüfregel zum Stand $v."
  signatur_stand "$STAENDE/$v"
  if [ "$JSON" = ja ]; then
    STAND_JSON="$(printf '{"version":"%s","sha256":"%s","groesse":%s,"commit":"%s","signatur":"%s","datei":"%s"}' "$v" "$s" "$g" "$c" "$SIG_STAND" "$z")"
    return 0
  fi
  case "$SIG_STAND" in
    gueltig) signiert="ja (gültig)" ;;
    ungeprueft) signiert="ja (nicht geprüft, keine Schlüsselliste)" ;;
    ungueltig) signiert="UNGÜLTIG" ;;
    *) signiert="nein" ;;
  esac
  echo "  $name: $v, SHA-256 $s, $g Byte, Commit $c, signiert: $signiert, Datei: $(datei_text "$z")"
}

status() {
  local a vo aktuell_json vorher_json v liste=() staende_json="" staende_text=""
  [ "$JSON" = ja ] || echo "== Status der Ablage $BASIS"
  ablage_pruefen
  link_lesen aktuell
  a="$LINK_VERSION"
  link_lesen vorher
  vo="$LINK_VERSION"
  schluessel_pruefen
  if [ "$JSON" = nein ]; then
    if [ -d "$BASIS" ]; then echo "  Ordner: $(stat -c 'Rechte %a, Besitzer %U:%G' "$BASIS")"; else echo "  Die Ablage gibt es noch nicht (noch nichts eingesetzt)."; fi
  fi
  stand_zeigen aktuell "$a"
  aktuell_json="$STAND_JSON"
  stand_zeigen vorher "$vo"
  vorher_json="$STAND_JSON"
  if [ -d "$STAENDE" ]; then
    while IFS= read -r -d '' v; do
      if [[ "$v" =~ $VERSION_RE ]]; then liste+=("$v"); fi
    done < <(find "$STAENDE" -mindepth 1 -maxdepth 1 -type d -printf '%f\0')
  fi
  if [ "${#liste[@]}" -gt 0 ]; then
    while IFS= read -r v; do
      staende_json="$staende_json${staende_json:+,}\"$v\""
      staende_text="$staende_text${staende_text:+, }$v"
    done < <(py sortieren "${liste[@]}")
  fi
  if [ "$JSON" = ja ]; then
    printf '{"v":1,"aktuell":%s,"vorher":%s,"staende":[%s],"schluesselliste":%s}\n' "$aktuell_json" "$vorher_json" "$staende_json" \
      "$([ "$SCHLUESSEL_DA" = ja ] && echo true || echo false)"
    return 0
  fi
  echo "  Stände: ${staende_text:-keine}"
  if [ "$SCHLUESSEL_DA" = ja ]; then
    echo "  Schlüsselliste: $SCHLUESSEL (eine gültige Signatur ist Pflicht)"
  else
    echo "  Schlüsselliste: fehlt (unsignierte Stände gehen mit Warnung durch, Übergang für 0.2.0)"
  fi
  [ "$STATUS_FEHLER" = nein ] || fehler "Mindestens ein Stand ist ungültig (siehe oben)."
}

case "$BEFEHL" in
  einsetzen) einsetzen ;;
  status) status ;;
  rueckweg) rueckweg ;;
esac
[ "$JSON" = ja ] || echo "Fertig."
