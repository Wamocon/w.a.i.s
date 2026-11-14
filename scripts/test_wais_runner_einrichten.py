"""Tests für die Einrichtung des eigenen GitHub-Runners: infra/sokrates2/wais-runner-einrichten.sh (Benutzer, Runner-Software, sudoers,
Dienst, Registrierung, Rückweg) und die sudoers-Regeln für den Einstieg /usr/local/sbin/wais-deploy.

Das Skript läuft im Probelauf (WAIS_RUNNER_WURZEL) in einem Wegwerf-Ordner ohne root; useradd, systemctl, visudo, sudo, curl, runuser
und ssh-keygen sind Attrappen, die jeden Aufruf in aufrufe.log schreiben. Die sudoers-Regeln werden mit einer Nachbildung der Prüfung
von sudo (Argumente als eine Zeile, ^...$ als regulärer Ausdruck) gegen erlaubte und verbotene Aufrufe geprüft. visudo und sudo -l
selbst sind nur am Server prüfbar (einrichten macht dort zehn Proben).

Aufruf (aus voice-core, dort liegt die Python-Umgebung):  python -m pytest -q -p no:cacheprovider ../scripts/test_wais_runner_einrichten.py
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_wais_deploy import ATTRAPPE_FLOCK, BASH, DEPLOY, RUNNER, SHA, _ok, _schreiben, braucht_bash  # noqa: E402


# ---------------------------------------------------------------- sudoers
def _sudoers() -> str:
    if BASH is None:
        pytest.skip("bash fehlt")
    r = subprocess.run([BASH, str(RUNNER), "sudoers-text"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _regeln(text: str) -> list[tuple[str, str]]:
    zusammen = text.replace("\\\n", " ")
    m = re.search(r"^Cmnd_Alias WAIS_DEPLOY = (.*)$", zusammen, re.M)
    assert m, "Cmnd_Alias fehlt"
    regeln = []
    for eintrag in (e.strip() for e in m.group(1).split(", ")):
        befehl, _, args = eintrag.partition(" ")
        regeln.append((befehl, args))
    return regeln


def _erlaubt(regeln: list[tuple[str, str]], argv: list[str]) -> bool:
    """Nachbildung der Prüfung von sudo: die Argumente als eine Zeile; ^...$ als regulärer Ausdruck, sonst genau gleich."""
    zeile = " ".join(argv[1:])
    for befehl, args in regeln:
        if befehl != argv[0]:
            continue
        if args.startswith("^") and args.endswith("$"):
            if re.fullmatch(args[1:-1], zeile):
                return True
        elif args == zeile:
            return True
    return False


E = "/usr/local/sbin/wais-deploy"


@pytest.mark.parametrize("argv", [
    [E, "status"], [E, "rauchtest"], [E, "ausleiten"], [E, "ausleiten", "--trocken"], [E, "rueckweg", "kern"],
    [E, "rueckweg", "beides", "--trocken"], [E, "pruefen-stand", SHA], [E, "verteilen", SHA], [E, "verteilen", SHA, "--trocken"],
    [E, "test-kern", SHA], [E, "test-oberflaeche", SHA, "--trocken"], [E, "prod-kern", SHA], [E, "prod-oberflaeche", SHA],
])
def test_sudoers_erlaubt_genau_die_aufrufe_der_workflows(argv):
    assert _erlaubt(_regeln(_sudoers()), argv)


@pytest.mark.parametrize("argv", [
    [E], [E, "status", "--json"], [E, "verteilen", SHA[:39]], [E, "verteilen", SHA.upper()], [E, "verteilen", SHA, "--sofort"],
    [E, "verteilen", SHA + ";", "id"], [E, "pruefen-stand", SHA, "--trocken"], [E, "rueckweg", "alles"], [E, "einrichten"],
    [E, "verteilen", SHA, "--trocken", "--trocken"], ["/bin/bash"], ["/usr/bin/systemctl", "restart", "wamo-core"],
    ["/home/wamocon/wamo-infra/wais-deploy.sh", "status"], [E, "verteilen", "\n" + SHA],
])
def test_sudoers_verbietet_alles_andere(argv):
    assert not _erlaubt(_regeln(_sudoers()), argv)


def test_sudoers_aufbau():
    text = _sudoers()
    zeilen = [z for z in text.splitlines() if z and not z.startswith("#")]
    assert zeilen[0] == "Defaults:wais-deploy !requiretty, env_reset, !lecture"
    assert zeilen[-1] == "wais-deploy ALL=(root) NOPASSWD: WAIS_DEPLOY"
    assert "SETENV" not in text and "ALL, " not in text and "*" not in text
    assert sum("NOPASSWD" in z for z in zeilen) == 1
    for befehl, args in _regeln(text):
        assert befehl == E and args, (befehl, args)  # nie ein Befehl ohne Argumente (das hieße: alle Argumente erlaubt)
        assert not re.search(r"[,:=()\\]", args), args  # Zeichen, die sudoers anders liest


def test_sudoers_deckt_jeden_befehl_des_einstiegs_ab():
    text = DEPLOY.read_text(encoding="utf-8")
    block = text[text.index("# ---------- Ablauf"):]
    befehle = set(re.findall(r"^  ([a-z-]+)\) cmd_", block, re.M))
    assert befehle == {"pruefen-stand", "verteilen", "test-kern", "test-oberflaeche", "prod-kern", "prod-oberflaeche", "ausleiten",
                       "rueckweg", "rauchtest", "status"}
    regeln = _regeln(_sudoers())
    for befehl in befehle:
        assert any(args.lstrip("^").split(" ")[0] == befehl for _, args in regeln), befehl


# ---------------------------------------------------------------- wais-runner-einrichten.sh
def test_runner_version_und_pruefsumme_sind_festgenagelt():
    text = RUNNER.read_text(encoding="utf-8")
    assert re.search(r"^RUNNER_VERSION=\d+\.\d+\.\d+$", text, re.M)
    assert re.search(r"^RUNNER_SHA256=[0-9a-f]{64}$", text, re.M)
    assert "actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz" in text
    assert "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/" in text
    assert "sha256sum --check --strict" in text
    assert "--disableupdate" in text and "--token" not in text  # das Token nie als Argument
    assert "ACTIONS_RUNNER_INPUT_TOKEN" in text


def test_dienst_laeuft_als_runner_benutzer():
    if BASH is None:
        pytest.skip("bash fehlt")
    text = subprocess.run([BASH, str(RUNNER), "unit-text"], capture_output=True, text=True, encoding="utf-8").stdout
    einstellungen = [z for z in text.splitlines() if z and not z.startswith("#")]
    assert "User=wais-deploy" in einstellungen and "Group=wais-deploy" in einstellungen
    assert "ExecStart=/opt/wais-runner/run.sh" in einstellungen and "KillMode=process" in einstellungen
    assert not [z for z in einstellungen if z.startswith(("User=root", "AmbientCapabilities", "NoNewPrivileges", "ProtectSystem"))]


RUNNER_ATTRAPPEN = {
    "getent": 'if [ "$1" = passwd ] && [ -e "$L/attrappen/benutzer" ]; then echo "wais-deploy:x:900:900::/var/lib/wais-runner:/usr/sbin/nologin"; exit 0; fi\nexit 2\n',
    "id": 'if [ "${1:-}" = -nG ]; then echo wais-deploy; exit 0; fi\nexec /usr/bin/id "$@"\n',
    "useradd": 'touch "$L/attrappen/benutzer"\n',
    "userdel": 'rm -f "$L/attrappen/benutzer"\n',
    "usermod": "exit 0\n",
    "pkill": "exit 0\n",
    "systemctl": 'case "$*" in "enable --now"*) touch "$L/attrappen/aktiv" ;; "is-active --quiet"*) [ -e "$L/attrappen/aktiv" ] || exit 3 ;;'
                 ' "disable --now"*) rm -f "$L/attrappen/aktiv" ;; esac\nexit 0\n',
    "systemd-analyze": "exit 0\n",
    "visudo": "exit 0\n",
    "sudo": 'if [ "$1" = -V ]; then echo "Sudo version 1.9.15p5"; fi\nexit 0\n',
    "uname": "echo aarch64\n",
    "curl": 'while [ $# -gt 0 ]; do if [ "$1" = -o ]; then cp "$WAIS_RUNNER_PROBE_ARCHIV" "$2"; fi; shift; done\n',
    "ssh-keygen": 'f=""; while [ $# -gt 0 ]; do if [ "$1" = -f ]; then f="$2"; fi; shift; done\n'
                  'if [ -n "$f" ] && [ ! -e "$f" ] && [ "${f%.pub}" = "$f" ]; then echo privat > "$f"; echo "ssh-ed25519 AAAAprobe wais-deploy@sokrates2" > "$f.pub"; else echo "256 SHA256:probe"; fi\n',
    "runuser": 'echo "runuser $* token_gesetzt=${ACTIONS_RUNNER_INPUT_TOKEN:+ja}" >> "$L/aufrufe.log"\nwhile [ "$1" != -- ]; do shift; done\nshift\nexec "$@"\n',
}

CONFIG_SH = r"""#!/bin/bash
echo "config.sh $* token_laenge=${#ACTIONS_RUNNER_INPUT_TOKEN}" >> "$WAIS_RUNNER_WURZEL/aufrufe.log"
if [ "$1" = remove ]; then rm -f .runner; exit 0; fi
echo '{"agentName":"sokrates2-wais-deploy","gitHubUrl":"https://github.com/Wamocon/w.a.i.s"}' > .runner
echo 'LANG=C.UTF-8' > .env
"""

# Test-Token wird berechnet, nie als langes Literal geschrieben (sonst schlägt der Geheimnis-Scan an): 26 Großbuchstaben und 3 Ziffern
TOKEN = "".join(chr(65 + i // 2) for i in range(26)) + "".join(str(i) for i in range(1, 4))


@pytest.fixture
def runner_probe():
    if BASH is None:
        pytest.skip("bash fehlt")
    ordner = Path(tempfile.mkdtemp(prefix="wais-runner-"))
    shell = f"/tmp/{ordner.name}" if os.name == "nt" else str(ordner)
    for name, rumpf in RUNNER_ATTRAPPEN.items():
        kopf = '#!/bin/bash\nL="$WAIS_RUNNER_WURZEL"\n'
        protokoll = "" if name in ("runuser", "id") else f'echo "{name} $*" >> "$L/aufrufe.log"\n'
        _schreiben(ordner / "attrappen" / name, kopf + protokoll + rumpf, True)
    _schreiben(ordner / "attrappen" / "flock", ATTRAPPE_FLOCK, True)
    puffer = io.BytesIO()
    with tarfile.open(fileobj=puffer, mode="w:gz") as tar:
        for name, daten, modus in (("./config.sh", CONFIG_SH.encode(), 0o755), ("./run.sh", b"#!/bin/bash\n", 0o755),
                                   ("./bin/Runner.Listener", b"probe", 0o755), ("./externals/node/x", b"x", 0o644)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(daten), modus
            tar.addfile(info, io.BytesIO(daten))
    archiv = ordner / "archiv" / "runner.tar.gz"
    archiv.parent.mkdir()
    archiv.write_bytes(puffer.getvalue())
    archiv_shell = f"{shell}/archiv/runner.tar.gz"

    class P:
        pass

    p = P()
    p.w, p.shell = ordner, shell
    p.sha = hashlib.sha256(puffer.getvalue()).hexdigest()

    def lauf(*args: str, eingabe: str = "", sha: str | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "WAIS_RUNNER_WURZEL": shell, "WAIS_RUNNER_PROBE_ARCHIV": archiv_shell,
               "WAIS_RUNNER_PROBE_SHA256": sha or p.sha}
        return subprocess.run([BASH, str(RUNNER), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, input=eingabe, timeout=180)

    def aufrufe() -> list[str]:
        datei = ordner / "aufrufe.log"
        return datei.read_text(encoding="utf-8").splitlines() if datei.exists() else []

    p.lauf, p.aufrufe = lauf, aufrufe
    try:
        yield p
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


@braucht_bash
@pytest.mark.parametrize("args", [
    ["einrichten", "--abmelden"], ["einrichten", "--url", "https://github.com/Fremd/w.a.i.s"], ["einrichten", "--url", "http://github.com/Wamocon"],
    ["einrichten", "--gruppe", "deploy"], ["einrichten", "--gruppe", "a b", "--url", "https://github.com/Wamocon"],
    ["rueckweg", "--ohne-registrierung"], ["status", "--trocken"], ["einrichten", "--token", TOKEN], ["unbekannt"], [],
])
def test_runner_ungueltige_aufrufe(args):
    r = subprocess.run([BASH, str(RUNNER), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "WAIS_RUNNER_WURZEL": "/tmp/wais-gibt-es-nicht"})
    assert r.returncode == 2, r.stdout + r.stderr


def _alle_dateien(ordner: Path):
    for pfad in ordner.rglob("*"):
        if pfad.is_file():
            yield pfad


@braucht_bash
def test_runner_trockenlauf_aendert_nichts(runner_probe):
    aus = _ok(runner_probe.lauf("einrichten", "--trocken"))
    assert "Trockenlauf: nichts geändert." in aus and "[trocken]" in aus
    assert not (runner_probe.w / "opt").exists() and not (runner_probe.w / "etc").exists()
    assert not [z for z in runner_probe.aufrufe() if z.startswith(("useradd", "config.sh", "systemctl enable"))]


@braucht_bash
def test_runner_einrichten_mit_token_nur_ueber_stdin(runner_probe):
    p = runner_probe
    aus = _ok(p.lauf("einrichten", eingabe=TOKEN + "\n"))
    alle = p.aufrufe()
    assert any(z.startswith("useradd --system --user-group --home-dir /var/lib/wais-runner --no-create-home --shell /usr/sbin/nologin")
               for z in alle)
    config = [z for z in alle if z.startswith("config.sh ")]
    assert len(config) == 1
    assert f"--unattended --url https://github.com/Wamocon/w.a.i.s --name sokrates2-wais-deploy --labels wais-deploy --work {p.shell}/var/lib/wais-runner/arbeit --disableupdate --replace" in config[0]
    assert config[0].endswith(f"token_laenge={len(TOKEN)}")
    assert any(z.startswith("runuser -u wais-deploy -- ./config.sh") and z.endswith("token_gesetzt=ja") for z in alle)
    # das Token steht in keiner Datei und in keinem Aufruf
    for pfad in _alle_dateien(p.w):
        assert TOKEN not in pfad.read_text(encoding="utf-8", errors="replace"), pfad
    assert TOKEN not in aus
    # Ergebnis
    assert (p.w / "etc" / "sudoers.d" / "wais-deploy").read_text(encoding="utf-8") == _sudoers()
    assert "User=wais-deploy" in (p.w / "etc" / "systemd" / "system" / "wais-runner.service").read_text(encoding="utf-8")
    einstieg = (p.w / "usr" / "local" / "sbin" / "wais-deploy").read_bytes()
    assert einstieg == DEPLOY.read_bytes().replace(b"\r", b"")
    assert (p.w / "opt" / "wais-runner" / "bin" / "Runner.Listener").is_file()
    assert (p.w / "opt" / "wais-runner" / ".wais-version").read_text(encoding="utf-8").startswith("2.")
    known = (p.w / "etc" / "wais-deploy" / "known_hosts").read_text(encoding="utf-8")
    assert "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" in known
    assert "QUELLE_URL=git@github.com:Wamocon/w.a.i.s.git" in (p.w / "etc" / "wais-deploy" / "quelle.conf").read_text(encoding="utf-8")
    assert "ssh-ed25519 AAAAprobe" in aus  # der öffentliche Teil des Lese-Schlüssels wird angezeigt
    assert "systemctl enable --now wais-runner.service" in alle
    # zweiter Lauf: nichts neu registriert, keine neue Software
    _ok(p.lauf("einrichten"))
    assert len([z for z in p.aufrufe() if z.startswith("config.sh ")]) == 1
    assert len([z for z in p.aufrufe() if z.startswith("curl ")]) == 1


@braucht_bash
def test_runner_falsche_pruefsumme_entpackt_nichts(runner_probe):
    r = runner_probe.lauf("einrichten", eingabe=TOKEN + "\n", sha="0" * 64)
    assert r.returncode == 1 and "Prüfsumme" in r.stderr
    assert not (runner_probe.w / "opt" / "wais-runner" / "bin").exists()
    assert not [z for z in runner_probe.aufrufe() if z.startswith("config.sh")]


@braucht_bash
@pytest.mark.parametrize("eingabe", ["", "kurz\n", "mit leer zeichen und mehr als zwanzig\n", "$(id)AAAAAAAAAAAAAAAAAAAA\n"])
def test_runner_ungueltiges_token_registriert_nicht(runner_probe, eingabe):
    r = runner_probe.lauf("einrichten", eingabe=eingabe)
    assert r.returncode == 1 and "Registrierungstoken" in r.stderr
    assert not [z for z in runner_probe.aufrufe() if z.startswith("config.sh")]


@braucht_bash
def test_runner_rueckweg(runner_probe):
    p = runner_probe
    _ok(p.lauf("einrichten", eingabe=TOKEN + "\n"))
    (p.w / "var" / "log" / "wais-deploy" / "protokoll.log").write_text("bleibt\n", encoding="utf-8")
    p_belegt = p.w / "attrappen" / "belegt.8"
    sperre = p.w / "run" / "wais-deploy" / "lock"
    sperre.parent.mkdir(parents=True)
    sperre.write_text("", encoding="utf-8")
    p_belegt.write_text("", encoding="utf-8")
    r = p.lauf("rueckweg")
    assert r.returncode == 1 and "Ausrollen läuft" in r.stderr
    assert (p.w / "etc" / "sudoers.d" / "wais-deploy").exists()
    p_belegt.unlink()
    _ok(p.lauf("rueckweg", "--trocken"))
    assert (p.w / "etc" / "sudoers.d" / "wais-deploy").exists()
    aus = _ok(p.lauf("rueckweg", "--abmelden", eingabe="RRSSTTUUVVWWXXYYZZ0011223\n"))
    for weg in ("etc/sudoers.d/wais-deploy", "etc/systemd/system/wais-runner.service", "opt/wais-runner", "var/lib/wais-runner",
                "usr/local/sbin/wais-deploy"):
        assert not (p.w / weg).exists(), weg
    assert any(z.startswith("config.sh remove") for z in p.aufrufe())
    assert "userdel wais-deploy" in p.aufrufe()
    assert (p.w / "etc" / "wais-deploy" / "deploy_key").exists()  # ohne --alles bleibt der Schlüssel
    assert (p.w / "var" / "log" / "wais-deploy" / "protokoll.log").exists()
    assert "Deploy-Key" in aus
    _ok(p.lauf("rueckweg", "--alles"))
    assert not (p.w / "etc" / "wais-deploy").exists() and not (p.w / "var" / "lib" / "wais-deploy").exists()
    assert (p.w / "var" / "log" / "wais-deploy" / "protokoll.log").exists()
