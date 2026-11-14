"""Tests für den Einstieg des Ausrollens am Server: infra/sokrates2/wais-deploy.sh (aufgerufen vom eigenen GitHub-Runner per sudo).
Die Einrichtung des Runners und die sudoers-Regeln prüft scripts/test_wais_runner_einrichten.py.

Das Skript läuft im Probelauf (WAIS_DEPLOY_WURZEL) in einem Wegwerf-Ordner ohne root und ohne systemd. Die Betriebsskripte
(wamo-core-slots.sh, wamo-ui-umschalten.sh, wamo-labor-einrichten.sh) und Programme wie flock und curl sind Attrappen, die jeden Aufruf
in aufrufe.log schreiben. git ist echt: ein lokales Repo spielt origin. Was echte Rechte braucht (Besitzer, echte Slots und Container),
ist nur am Server prüfbar. Unter Windows laufen die Skripte in Git Bash; die echte Sperre mit flock prüft ein Test nur unter Linux.

Aufruf (aus voice-core, dort liegt die Python-Umgebung):  python -m pytest -q -p no:cacheprovider ../scripts/test_wais_deploy.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
INFRA = WURZEL / "infra" / "sokrates2"
DEPLOY = INFRA / "wais-deploy.sh"
RUNNER = INFRA / "wais-runner-einrichten.sh"
LINUX = sys.platform.startswith("linux")


def _bash() -> str | None:
    kandidaten = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"] if os.name == "nt" else []
    kandidaten.append(shutil.which("bash") if os.name != "nt" else None)
    return next((k for k in kandidaten if k and Path(k).exists()), None)


BASH = _bash()
GIT = shutil.which("git")
braucht_bash = pytest.mark.skipif(BASH is None, reason="bash fehlt")
braucht_git = pytest.mark.skipif(BASH is None or GIT is None, reason="bash oder git fehlt")


def _schreiben(pfad: Path, text: str, ausfuehrbar: bool = False) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(text)
    if ausfuehrbar:
        pfad.chmod(0o755)


def _git(ordner: Path, *args: str) -> str:
    r = subprocess.run([GIT, "-c", "user.name=Probe", "-c", "user.email=probe@labor.test", "-c", "core.autocrlf=false",
                        "-c", "init.defaultBranch=main", *args], cwd=ordner, capture_output=True, text=True, check=True)
    return r.stdout.strip()


# ---------------------------------------------------------------- Attrappen für wais-deploy.sh
ATTRAPPE_SLOTS = r"""#!/bin/bash
W="$WAIS_DEPLOY_WURZEL"; Z="$W/attrappen/kern"
echo "slots $*" >> "$W/aufrufe.log"
lies() { cat "$Z/$1" 2>/dev/null || echo "${2:-}"; }
akt="$(lies aktiv a)"; if [ "$akt" = a ]; then frei=b; else frei=a; fi
case "$1" in
  probe) echo "SLOT $akt"; exit "$(lies probe.rc 0)" ;;
  status)
    echo "Releases:"
    for s in a b; do r="$(lies rel_$s)"; if [ -n "$r" ]; then z="/opt/wamo-core/releases/$r"; else z="(leer)"; fi
      echo "Slot $s: $z  $(lies zust_$s inactive)"; done
    echo "Alte Unit wamo-core.service: inactive" ;;
  release)
    d="$W/opt/wamo-core/releases/$2"; mkdir -p "$d/voice-core" "$d/venv/bin"; cp "$3"/* "$d/voice-core/"
    printf '#!/bin/sh\n' > "$d/venv/bin/python"; chmod +x "$d/venv/bin/python"; echo "Release $2 angelegt" ;;
  bereiten) echo "$2" > "$Z/rel_$frei"; echo active > "$Z/zust_$frei"; echo "Release $2 läuft auf Slot $frei"; echo "SLOT $frei" ;;
  schalten)
    z=""; for s in a b; do if [ "$(lies rel_$s)" = "$2" ] && [ "$(lies zust_$s)" = active ]; then z=$s; fi; done
    [ -n "$z" ] || exit 1; echo "$z" > "$Z/aktiv"; echo "SLOT $z" ;;
  bewaehren) rc="$(lies bewaehren.rc 0)"; if [ "$rc" != 0 ]; then echo "$frei" > "$Z/aktiv"; fi; exit "$rc" ;;
  ausleiten) rc="$(lies ausleiten.rc 0)"; if [ "$rc" = 0 ]; then echo inactive > "$Z/zust_$frei"; fi; exit "$rc" ;;
  rueckweg-kern) echo "$frei" > "$Z/aktiv"; echo "Zurück auf Slot $frei" ;;
  *) exit 9 ;;
esac
"""

ATTRAPPE_UI = r"""#!/bin/bash
W="$WAIS_DEPLOY_WURZEL"; Z="$W/attrappen/ui"
echo "ui $*" >> "$W/aufrufe.log"
lies() { cat "$Z/$1" 2>/dev/null || echo "${2:-}"; }
live="$(lies live blau)"; vorige="$(lies vorige gruen)"; if [ "$live" = blau ]; then neu=gruen; else neu=blau; fi
trocken=nein; for a in "$@"; do if [ "$a" = --trocken ]; then trocken=ja; fi; done
case "$1" in
  status)
    if [ "${2:-}" = --json ]; then c="$(lies commit_$live)"; v=""; if [ -n "$c" ]; then v=v0.1.0; fi
      printf '{"live":"%s","vorige":"%s","seit":"2026-11-14T10:00:00Z","version":"%s","commit":"%s"}\n' "$live" "$vorige" "$v" "$c"
    else echo "== Oberfläche: live $live"; fi ;;
  bauen)
    c=""; while [ $# -gt 0 ]; do if [ "$1" = --commit ]; then c="$2"; fi; shift; done
    if [ "$trocken" = ja ]; then echo "Trockenlauf: baut $neu"; exit 0; fi
    echo "$c" > "$Z/commit_$neu"; echo "BEREIT farbe=$neu version=0.1.0 commit=$c" ;;
  umschalten)
    if [ "$trocken" = ja ]; then echo "Trockenlauf: live $live -> $neu"; exit 0; fi
    rc="$(lies umschalten.rc 0)"; if [ "$rc" = 0 ]; then echo "$neu" > "$Z/live"; echo "$live" > "$Z/vorige"; fi; exit "$rc" ;;
  zurueck)
    if [ "$trocken" = ja ]; then exit 0; fi
    echo "$vorige" > "$Z/live"; echo "$live" > "$Z/vorige" ;;
  *) exit 9 ;;
esac
"""

ATTRAPPE_LABOR = r"""#!/bin/bash
echo "labor $*" >> "$WAIS_DEPLOY_WURZEL/aufrufe.log"
exit "$(cat "$WAIS_DEPLOY_WURZEL/attrappen/labor.rc" 2>/dev/null || echo 0)"
"""

ATTRAPPE_FLOCK = r"""#!/bin/bash
L="${WAIS_DEPLOY_WURZEL:-$WAIS_RUNNER_WURZEL}"
echo "flock $*" >> "$L/aufrufe.log"
for a in "$@"; do
  case "$a" in
    8|9) if [ -e "$L/attrappen/belegt.$a" ]; then exit 1; fi ;;
    */run/wais-deploy/lock) if [ -e "$L/attrappen/belegt.8" ]; then exit 1; fi ;;
  esac
done
exit 0
"""

ATTRAPPE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$WAIS_DEPLOY_WURZEL/aufrufe.log"
printf '%s' "$(cat "$WAIS_DEPLOY_WURZEL/attrappen/curl.code" 2>/dev/null || echo 401)"
"""

ALT_UI = "1" * 40


@pytest.fixture
def probe():
    """Wegwerf-Wurzel mit Attrappen und einem lokalen origin (main mit zwei Commits). Liefert ein Objekt mit Pfaden und Helfern."""
    if BASH is None or GIT is None:
        pytest.skip("bash oder git fehlt")
    ordner = Path(tempfile.mkdtemp(prefix="wais-probe-"))
    shell = f"/tmp/{ordner.name}" if os.name == "nt" else str(ordner)

    class P:
        pass

    p = P()
    p.w, p.shell = ordner, shell
    att = ordner / "attrappen"
    _schreiben(att / "wamo-core-slots.sh", ATTRAPPE_SLOTS, True)
    _schreiben(att / "wamo-ui-umschalten.sh", ATTRAPPE_UI, True)
    _schreiben(att / "wamo-labor-einrichten.sh", ATTRAPPE_LABOR, True)
    _schreiben(att / "flock", ATTRAPPE_FLOCK, True)
    _schreiben(att / "curl", ATTRAPPE_CURL, True)
    _schreiben(att / "logger", "#!/bin/bash\nexit 0\n", True)
    for name, wert in {"aktiv": "a", "rel_a": "v0.1.0-aaaaaaa", "zust_a": "active", "zust_b": "inactive"}.items():
        _schreiben(att / "kern" / name, wert + "\n")
    for name, wert in {"live": "blau", "vorige": "gruen", "commit_blau": ALT_UI}.items():
        _schreiben(att / "ui" / name, wert + "\n")
    # origin: ein Arbeitsrepo mit den Dateien, die verteilen braucht, dazu Dinge, die nie auf den Server dürfen
    arbeit = ordner / "quelle-arbeit"
    dateien = {
        "infra/sokrates2/wamo-core-slots.sh": "echo echt\n", "infra/sokrates2/wamo-ui-umschalten.sh": "echo echt\n",
        "infra/sokrates2/wamo-labor-einrichten.sh": "echo echt\n", "infra/sokrates2/wamo-ui/Dockerfile": "FROM scratch\n",
        "infra/sokrates2/wamo-ui/docker-compose.yml": "services: {}\n",
        "voice-core/bot.py": "print('bot')\n", "voice-core/kern_dienst.py": "x = 1\n", "voice-core/test_bot.py": "def test(): pass\n",
        "voice-core/conftest.py": "\n", "voice-core/pyproject.toml": '[project]\nname = "wamo-voice-core"\nversion = "0.1.0"\n',
        "voice-core/uv.lock": "version = 1\n", "ui/package.json": '{\n  "name": "wamo-ui",\n  "version": "0.1.0"\n}\n',
        "ui/src/a.ts": "export const a = 1;\n", "ui/.env.local": "GEHEIM=nie\n", "ui/node_modules/x/index.js": "1\n",
        "ui/next-env.d.ts": "// erzeugt\n", "README.md": "probe\n",
    }
    for rel, text in dateien.items():
        _schreiben(arbeit / rel, text)
    arbeit.mkdir(exist_ok=True)
    _git(arbeit, "init", "-q")
    _git(arbeit, "add", "-A", "-f")
    _git(arbeit, "commit", "-q", "-m", "erster Stand")
    p.erster = _git(arbeit, "rev-parse", "HEAD")
    _schreiben(arbeit / "voice-core" / "bot.py", "print('bot 2')\n")
    _git(arbeit, "commit", "-q", "-am", "zweiter Stand")
    p.commit = _git(arbeit, "rev-parse", "HEAD")
    _git(arbeit, "checkout", "-q", "-b", "seite")
    _schreiben(arbeit / "voice-core" / "bot.py", "print('seite')\n")
    _git(arbeit, "commit", "-q", "-am", "nur auf einem Zweig")
    p.seite = _git(arbeit, "rev-parse", "HEAD")
    _git(arbeit, "checkout", "-q", "main")
    _git(ordner, "clone", "-q", "--bare", str(arbeit), "origin.git")
    p.origin = ordner / "origin.git"
    _schreiben(ordner / "etc" / "wais-deploy" / "quelle.conf", f"# Probe\nQUELLE_URL={shell}/origin.git\n")
    p.release = f"v0.1.0-{p.commit[:7]}"

    def lauf(*args: str, eingabe: str | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "WAIS_DEPLOY_WURZEL": shell}
        return subprocess.run([BASH, str(DEPLOY), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, input=eingabe, timeout=180)

    def aufrufe() -> list[str]:
        datei = ordner / "aufrufe.log"
        return datei.read_text(encoding="utf-8").splitlines() if datei.exists() else []

    def zustand(name: str) -> str:
        return (ordner / "var" / "lib" / "wais-deploy" / "zustand" / name).read_text(encoding="utf-8")

    def setze(pfad: str, wert: str) -> None:
        _schreiben(att / pfad, wert + "\n")

    p.lauf, p.aufrufe, p.zustand, p.setze = lauf, aufrufe, zustand, setze
    p.stand = ordner / "var" / "lib" / "wais-deploy" / "staende" / p.commit
    try:
        yield p
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, f"Rückgabe {r.returncode}\n{r.stdout}\n{r.stderr}"
    return r.stdout


def _wais(ausgabe: str) -> dict[str, str]:
    return dict(m.groups() for m in re.finditer(r"^WAIS ([a-z]+)=(\S*)$", ausgabe, re.M))


# ---------------------------------------------------------------- Syntax
@braucht_bash
@pytest.mark.parametrize("skript", [DEPLOY, RUNNER], ids=lambda p: p.name)
def test_syntax(skript):
    r = subprocess.run([BASH, "-n", str(skript)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("skript", [DEPLOY, RUNNER], ids=lambda p: p.name)
def test_nur_lf_und_keine_steuerzeichen(skript):
    daten = skript.read_bytes()
    assert b"\r" not in daten
    assert not [b for b in daten if b < 32 and b not in (9, 10)]


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck fehlt")
@pytest.mark.parametrize("skript", [DEPLOY, RUNNER], ids=lambda p: p.name)
def test_shellcheck(skript):
    r = subprocess.run(["shellcheck", "-S", "warning", str(skript)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ---------------------------------------------------------------- wais-deploy.sh: Aufruf
SHA = "0123456789abcdef0123456789abcdef01234567"


@braucht_bash
@pytest.mark.parametrize("args", [
    [], ["unbekannt"], ["verteilen"], ["verteilen", "abc1234"], ["verteilen", SHA.upper()], ["verteilen", SHA + "0"],
    ["verteilen", SHA, "--sofort"], ["verteilen", SHA, "--trocken", "--trocken"], ["pruefen-stand", SHA, "--trocken"],
    ["status", "--json"], ["rauchtest", "x"], ["rueckweg"], ["rueckweg", "alles"], ["rueckweg", "kern", "--x"],
    ["ausleiten", "--sofort"], ["verteilen", SHA + "; id"], ["verteilen", "$(id)"], ["verteilen", f"{SHA} --trocken"],
    ["prod-kern", "../" + SHA[:37]],
], ids=lambda a: " ".join(a) or "leer")
def test_ungueltige_aufrufe_enden_mit_2_und_aendern_nichts(args, tmp_path):
    r = subprocess.run([BASH, str(DEPLOY), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "WAIS_DEPLOY_WURZEL": "/tmp/wais-gibt-es-nicht"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Aufruf:" in r.stderr


@braucht_bash
@pytest.mark.parametrize("wurzel", ["relativ/pfad", "/tmp/../etc", "/tmp/a b", "/"])
def test_probelauf_lehnt_unsichere_wurzel_ab(wurzel):
    r = subprocess.run([BASH, str(DEPLOY), "status"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "WAIS_DEPLOY_WURZEL": wurzel})
    assert r.returncode == 1 and "WAIS_DEPLOY_WURZEL" in r.stderr


# ---------------------------------------------------------------- wais-deploy.sh: Stand aus origin/main
@braucht_git
def test_pruefen_stand_nimmt_den_kopf_von_main(probe):
    aus = _ok(probe.lauf("pruefen-stand", probe.commit))
    w = _wais(aus)
    assert w == {"commit": probe.commit, "release": probe.release, "kopf": "ja", "ergebnis": "ok"}


@braucht_git
def test_pruefen_stand_nimmt_auch_einen_aelteren_commit_aus_main(probe):
    w = _wais(_ok(probe.lauf("pruefen-stand", probe.erster)))
    assert w["kopf"] == "nein" and w["release"] == f"v0.1.0-{probe.erster[:7]}"


@braucht_git
@pytest.mark.parametrize("welcher", ["seite", "fremd"])
def test_commit_ausserhalb_von_main_wird_abgelehnt(probe, welcher):
    commit = probe.seite if welcher == "seite" else "f" * 40
    r = probe.lauf("pruefen-stand", commit)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "nicht" in r.stderr and "origin/main" in r.stderr


@braucht_git
def test_nach_force_push_gilt_ein_frueher_verteilter_commit_nicht_mehr(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    _git(probe.origin, "update-ref", "refs/heads/main", probe.erster)  # main zeigt nur noch auf den ersten Stand
    for befehl in ("pruefen-stand", "test-kern", "prod-kern"):
        r = probe.lauf(befehl, probe.commit)
        assert r.returncode == 3, befehl + r.stderr
        assert "nicht in origin/main enthalten" in r.stderr
    assert not any(z.startswith("slots ") for z in probe.aufrufe())


@braucht_git
@pytest.mark.parametrize("url", ["https://example.org/Wamocon/w.a.i.s.git", "git@github.com:Fremd/w.a.i.s.git",
                                 "https://github.com/Wamocon/w.a.i.s", "file:///tmp/x.git"])
def test_quelle_nur_vom_eigenen_github(probe, url):
    _schreiben(probe.w / "etc" / "wais-deploy" / "quelle.conf", f"QUELLE_URL={url}\n")
    r = probe.lauf("pruefen-stand", probe.commit)
    assert r.returncode == 1 and "QUELLE_URL ist ungültig" in r.stderr


@braucht_git
def test_quelle_conf_kennt_nur_eine_zeile(probe):
    _schreiben(probe.w / "etc" / "wais-deploy" / "quelle.conf", f"QUELLE_URL={probe.shell}/origin.git\nGIT_SSH_COMMAND=boese\n")
    r = probe.lauf("pruefen-stand", probe.commit)
    assert r.returncode == 1 and "unbekannte Zeile" in r.stderr


# ---------------------------------------------------------------- wais-deploy.sh: verteilen
@braucht_git
def test_verteilen_legt_den_stand_wie_vom_pc_ab(probe):
    w = _wais(_ok(probe.lauf("verteilen", probe.commit)))
    assert w["release"] == probe.release and w["ergebnis"] == "ok"
    s = probe.stand
    for da in ("wamo-core-slots.sh", "wamo-ui-umschalten.sh", "wamo-ui/Dockerfile", "kern/bot.py", "kern/kern_dienst.py",
               "kern/pyproject.toml", "kern/uv.lock", "ui/package.json", "ui/src/a.ts"):
        assert (s / da).is_file(), da
    for weg in ("kern/test_bot.py", "kern/conftest.py", "ui/.env.local", "ui/node_modules", "ui/next-env.d.ts", "README.md"):
        assert not (s / weg).exists(), weg
    assert (s / "kern" / "bot.py").read_text(encoding="utf-8") == "print('bot 2')\n"
    assert (s / "wamo-ui" / "bau.info").read_bytes() == f"WAMO_COMMIT={probe.commit}\nWAMO_SAUBER=ja\n".encode()
    assert f"commit={probe.commit}" in probe.zustand("letzter-verteilt")
    # wiederholbar: ein zweites verteilen ändert nichts
    assert "schon verteilt" in _ok(probe.lauf("verteilen", probe.commit))


@braucht_git
def test_verteilen_trocken_legt_nichts_ab(probe):
    w = _wais(_ok(probe.lauf("verteilen", probe.commit, "--trocken")))
    assert w["ergebnis"] == "trocken"
    assert not probe.stand.exists()


@braucht_git
def test_alte_staende_werden_abgeraeumt(probe):
    staende = probe.stand.parent
    staende.mkdir(parents=True)
    for i in range(7):
        (staende / f"{i:040x}").mkdir()
        os.utime(staende / f"{i:040x}", (1_000_000 + i, 1_000_000 + i))
    _ok(probe.lauf("verteilen", probe.commit))
    namen = sorted(p.name for p in staende.iterdir() if not p.name.startswith("."))
    assert probe.commit in namen and len(namen) == 6  # fünf neueste plus der zuletzt verteilte


# ---------------------------------------------------------------- wais-deploy.sh: test und prod
@braucht_git
def test_test_verlangt_einen_verteilten_stand(probe):
    for befehl in ("test-kern", "test-oberflaeche"):
        r = probe.lauf(befehl, probe.commit)
        assert r.returncode == 3 and "nicht verteilt" in r.stderr


@braucht_git
def test_prod_verlangt_die_bestandene_stufe_test(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    for befehl in ("prod-kern", "prod-oberflaeche"):
        r = probe.lauf(befehl, probe.commit)
        assert r.returncode == 3 and "Stufe test" in r.stderr, befehl
    assert not [z for z in probe.aufrufe() if z.startswith(("slots schalten", "ui umschalten"))]


@braucht_git
def test_der_ganze_ablauf_test_und_prod(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    w = _wais(_ok(probe.lauf("test-kern", probe.commit)))
    assert w == {"commit": probe.commit, "release": probe.release, "slot": "b", "ergebnis": "ok"}
    w = _wais(_ok(probe.lauf("test-oberflaeche", probe.commit)))
    assert w["farbe"] == "gruen" and w["ergebnis"] == "ok"
    _ok(probe.lauf("rauchtest"))
    test_aufrufe = probe.aufrufe()
    assert f"slots release {probe.release} {probe.shell}/var/lib/wais-deploy/staende/{probe.commit}/kern" in test_aufrufe
    assert f"slots bereiten {probe.release}" in test_aufrufe
    assert sum(z.startswith("curl ") and "core-b.sock" in z for z in test_aufrufe) == 3
    assert f"ui bauen --commit {probe.commit} --sauber ja" in test_aufrufe
    # test schaltet nie
    assert not [z for z in test_aufrufe if z.startswith(("slots schalten", "slots umschalten-kern", "ui umschalten", "slots inc"))]
    assert "labor pruefen" not in test_aufrufe  # Labor nicht eingerichtet

    w = _wais(_ok(probe.lauf("prod-kern", probe.commit)))
    assert w == {"commit": probe.commit, "release": probe.release, "slot": "b", "vorher": "v0.1.0-aaaaaaa", "ergebnis": "ok"}
    w = _wais(_ok(probe.lauf("prod-oberflaeche", probe.commit)))
    assert w == {"commit": probe.commit, "farbe": "gruen", "ergebnis": "ok"}
    alle = probe.aufrufe()
    schalten = alle.index(f"slots schalten {probe.release}")
    assert alle[schalten - 1] == "flock -w 120 9"  # gemeinsame Caddy-Sperre unmittelbar vor dem Schalten
    assert alle[schalten + 1] == "slots bewaehren 30"
    umschalten = alle.index(f"ui umschalten --ohne-bau --commit {probe.commit} --bewaehrung 120 --fehlerquote 5")
    assert alle[umschalten - 1] == "flock -w 120 9"
    assert schalten < umschalten  # Kern zuerst, dann Oberfläche
    assert "release=v0.1.0-aaaaaaa" in probe.zustand("prod-vorher-kern")
    assert "farbe=blau" in probe.zustand("prod-vorher-oberflaeche")
    assert f"commit={probe.commit}" in probe.zustand("letzter-prod")
    # wiederholbar: ein zweiter prod-Lauf schaltet nichts mehr
    assert _wais(_ok(probe.lauf("prod-kern", probe.commit)))["ergebnis"] == "schon-aktiv"
    assert _wais(_ok(probe.lauf("prod-oberflaeche", probe.commit)))["ergebnis"] == "schon-live"
    assert probe.aufrufe().count(f"slots schalten {probe.release}") == 1


def _bis_test(probe) -> None:
    _ok(probe.lauf("verteilen", probe.commit))
    _ok(probe.lauf("test-kern", probe.commit))
    _ok(probe.lauf("test-oberflaeche", probe.commit))


@braucht_git
def test_trockenlauf_test_und_prod_schaltet_und_baut_nichts(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    assert _wais(_ok(probe.lauf("test-kern", probe.commit, "--trocken")))["ergebnis"] == "trocken"
    assert _wais(_ok(probe.lauf("test-oberflaeche", probe.commit, "--trocken")))["ergebnis"] == "trocken"
    _bis_test(probe)
    vorher = len(probe.aufrufe())
    assert _wais(_ok(probe.lauf("prod-kern", probe.commit, "--trocken")))["ergebnis"] == "trocken"
    assert _wais(_ok(probe.lauf("prod-oberflaeche", probe.commit, "--trocken")))["ergebnis"] == "trocken"
    neu = probe.aufrufe()[vorher:]
    assert not [z for z in neu if z.startswith(("slots schalten", "slots bewaehren", "slots release", "slots bereiten"))]
    assert not [z for z in neu if z.startswith("ui ") and ("umschalten" in z or "bauen" in z) and "--trocken" not in z]


@braucht_git
def test_bewaehrung_faellt_durch_ergibt_4(probe):
    _bis_test(probe)
    probe.setze("kern/bewaehren.rc", "1")
    r = probe.lauf("prod-kern", probe.commit)
    assert r.returncode == 4, r.stdout + r.stderr
    assert _wais(r.stdout)["ergebnis"] == "zurueckgenommen"
    assert not (probe.w / "var" / "lib" / "wais-deploy" / "zustand" / "letzter-prod").exists()


@braucht_git
@pytest.mark.parametrize("rc, erwartet", [(3, 1), (4, 4), (5, 5)])
def test_rueckgaben_der_oberflaeche(probe, rc, erwartet):
    _bis_test(probe)
    probe.setze("ui/umschalten.rc", str(rc))
    r = probe.lauf("prod-oberflaeche", probe.commit)
    assert r.returncode == erwartet, r.stdout + r.stderr


@braucht_git
def test_rueckweg_geht_auf_den_vermerkten_stand_und_ist_wiederholbar(probe):
    r = probe.lauf("rueckweg", "beides")
    assert r.returncode == 3  # noch kein Stand verteilt
    _bis_test(probe)
    _ok(probe.lauf("prod-kern", probe.commit))
    _ok(probe.lauf("prod-oberflaeche", probe.commit))
    vorher = len(probe.aufrufe())
    _ok(probe.lauf("rueckweg", "beides", "--trocken"))
    assert not [z for z in probe.aufrufe()[vorher:] if z in ("ui zurueck", "slots rueckweg-kern")]
    aus = _ok(probe.lauf("rueckweg", "beides"))
    neu = probe.aufrufe()[vorher:]
    assert neu.index("ui zurueck") < neu.index("slots rueckweg-kern")  # Oberfläche zuerst, dann Kern
    assert "oberflaeche=zurueck" in aus and "kern=zurueck" in aus
    vorher = len(probe.aufrufe())
    aus = _ok(probe.lauf("rueckweg", "beides"))
    assert "oberflaeche=schon" in aus and "kern=schon" in aus
    assert not [z for z in probe.aufrufe()[vorher:] if z in ("ui zurueck", "slots rueckweg-kern")]


@braucht_git
def test_rueckweg_kern_ohne_laufende_alte_instanz_braucht_handarbeit(probe):
    _bis_test(probe)
    _ok(probe.lauf("prod-kern", probe.commit))
    _ok(probe.lauf("ausleiten"))
    r = probe.lauf("rueckweg", "kern")
    assert r.returncode == 5 and "kein schneller Rückweg" in r.stderr


@braucht_git
def test_test_kern_bricht_ab_solange_der_freie_slot_auslaeuft(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    probe.setze("kern/rel_b", "v0.1.0-bbbbbbb")
    probe.setze("kern/zust_b", "active")
    _schreiben(probe.w / "home/wamocon/wamo-tls/caddy/etc/kern/slot.inc", "handle /i/b/start {\n}\n")
    r = probe.lauf("test-kern", probe.commit)
    assert r.returncode == 3 and "auslaufende Instanz" in r.stderr
    assert not [z for z in probe.aufrufe() if z.startswith(("slots bereiten", "slots ausleiten"))]


@braucht_git
def test_test_kern_leitet_einen_nie_geschalteten_teststand_aus(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    probe.setze("kern/rel_b", "v0.1.0-bbbbbbb")
    probe.setze("kern/zust_b", "active")
    _ok(probe.lauf("test-kern", probe.commit))
    alle = probe.aufrufe()
    assert alle.index("slots ausleiten") < alle.index(f"slots bereiten {probe.release}")


@braucht_git
def test_ein_vorhandenes_release_mit_anderem_inhalt_wird_nie_ueberschrieben(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    rel = probe.w / "opt" / "wamo-core" / "releases" / probe.release
    for f in (probe.stand / "kern").iterdir():
        _schreiben(rel / "voice-core" / f.name, f.read_text(encoding="utf-8"))
    _schreiben(rel / "venv" / "bin" / "python", "#!/bin/sh\n", True)
    _schreiben(rel / "voice-core" / "bot.py", "print('anders')\n")
    r = probe.lauf("test-kern", probe.commit)
    assert r.returncode == 1 and "anderem Inhalt" in r.stderr
    assert not [z for z in probe.aufrufe() if z.startswith(("slots release", "slots bereiten"))]
    # gleicher Inhalt: wird übernommen statt neu gebaut
    _schreiben(rel / "voice-core" / "bot.py", (probe.stand / "kern" / "bot.py").read_text(encoding="utf-8"))
    assert "gleicht dem Stand" in _ok(probe.lauf("test-kern", probe.commit))
    assert not [z for z in probe.aufrufe() if z.startswith("slots release")]


@braucht_git
def test_sperren(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    probe.setze("belegt.8", "")
    r = probe.lauf("test-kern", probe.commit)
    assert r.returncode == 3 and "hält die Sperre" in r.stderr
    (probe.w / "attrappen" / "belegt.8").unlink()
    _ok(probe.lauf("test-kern", probe.commit))
    _ok(probe.lauf("test-oberflaeche", probe.commit))
    probe.setze("belegt.9", "")
    r = probe.lauf("prod-kern", probe.commit)
    assert r.returncode == 3 and "Caddy-Sperre" in r.stderr
    assert not [z for z in probe.aufrufe() if z.startswith("slots schalten")]


@pytest.mark.skipif(not LINUX or shutil.which("flock") is None or GIT is None, reason="echtes flock nur unter Linux")
def test_echte_sperre_unter_linux(probe):
    (probe.w / "attrappen" / "flock").unlink()
    sperre = probe.w / "run" / "wais-deploy" / "lock"
    sperre.parent.mkdir(parents=True)
    halter = subprocess.Popen(["flock", str(sperre), "sleep", "20"])
    try:
        import time
        time.sleep(0.5)
        r = probe.lauf("pruefen-stand", probe.commit)
        assert r.returncode == 3 and "hält die Sperre" in r.stderr
    finally:
        halter.kill()


@braucht_git
def test_ausleiten_spaeter_ergibt_3(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    probe.setze("kern/ausleiten.rc", "1")
    r = probe.lauf("ausleiten")
    assert r.returncode == 3 and _wais(r.stdout)["ergebnis"] == "spaeter"


@braucht_git
def test_rauchtest_prueft_das_labor_nur_wenn_eingerichtet(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    _ok(probe.lauf("rauchtest"))
    assert "labor pruefen" not in probe.aufrufe()
    _schreiben(probe.w / "etc" / "wamo-labor" / "kern-token", "x\n")
    _ok(probe.lauf("rauchtest"))
    assert "labor pruefen" in probe.aufrufe()
    probe.setze("labor.rc", "1")
    assert probe.lauf("rauchtest").returncode == 1
    probe.setze("labor.rc", "0")
    probe.setze("kern/probe.rc", "1")
    assert probe.lauf("rauchtest").returncode == 1


@braucht_git
def test_protokoll_und_status(probe):
    _ok(probe.lauf("verteilen", probe.commit))
    aus = _ok(probe.lauf("status"))
    assert "zuletzt verteilt: " + probe.commit in aus
    text = (probe.w / "var" / "log" / "wais-deploy" / "protokoll.log").read_text(encoding="utf-8")
    assert re.search(rf"^==== \d{{4}}-\d\d-\d\dT[\d:]+Z wais-deploy verteilen {probe.commit} \(Aufrufer: ", text, re.M)
    assert "==== Ende verteilen: Rückgabe 0" in text and "==== Ende status: Rückgabe 0" in text
    assert not [z for z in probe.aufrufe() if z.split(" ")[1:2] and z.split(" ")[1] in ("release", "bereiten", "schalten")]


# ---------------------------------------------------------------- wais-deploy.sh: feste Regeln im Text
def test_einstieg_nutzt_nur_die_vorhandenen_wege():
    text = DEPLOY.read_text(encoding="utf-8")
    assert "wamo-core-einrichten.sh" not in text and "systemctl restart" not in text
    assert "umschalten-kern" not in text  # test und prod trennen: bereiten (ohne Schalten), schalten, bewaehren
    for teil in ("slots release ", "slots bereiten ", "slots schalten ", 'slots bewaehren "$KERN_BEWAEHRUNG_MIN"', "slots ausleiten",
                 "slots rueckweg-kern", "oberflaeche bauen --commit", "oberflaeche umschalten --ohne-bau --commit", "oberflaeche zurueck",
                 "labor pruefen"):
        assert teil in text, teil
    assert "KERN_BEWAEHRUNG_MIN=30" in text
    assert 'runuser -u "$UI_BENUTZER"' in text and "UI_BENUTZER=wamocon" in text  # die Oberfläche baut und schaltet als wamocon
    assert text.count("env -i") >= 3  # Betriebsskripte ohne die Umgebung von sudo
    assert "merge-base --is-ancestor" in text and "+refs/heads/main:refs/remotes/origin/main" in text
