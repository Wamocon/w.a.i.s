"""Tests für scripts/wamo_labor_ssh.py: der kurze, sichere ssh-Befehl für die Serverprogramme (Kern, Dienst, Messung).

Aufruf (aus scripts, mit der Python-Umgebung von voice-core):
  D:\\IDEA\\Projekt\\wamo\\voice-core\\.venv\\Scripts\\python.exe -m pytest -q test_wamo_labor_ssh.py

Kein ssh, kein Server: ssh wird nie gestartet, geprüft wird nur die Befehlszeile, die ein Aufruf bauen würde.

Hintergrund (Fehler am 20.11.2026): Das ssh aus Git für Windows (MSYS, in Git Bash vor dem Windows-ssh im Suchpfad) schneidet Befehlszeilen bei etwa 8191
Zeichen ab. Der Befehl für den Kern war ungepackt über 13000 Zeichen lang, dem fernen Befehl fehlte das schließende Anführungszeichen, und der Nachlauf
brach in Schritt 1 mit "Dateiende beim Suchen nach" ab. Diese Tests halten jede Stelle, die ein Serverprogramm startet, unter der Grenze.
"""
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_labor as wl  # noqa: E402
import wamo_labor_last_server as sv  # noqa: E402
import wamo_labor_nachlauf as na  # noqa: E402
import wamo_labor_ssh as ws  # noqa: E402

GIT_SSH_GRENZE = 8191   # Länge der Befehlszeile, bei der das ssh aus Git für Windows abschneidet
SICHERHEIT = 1000       # Platz für den Pfad von ssh, die Optionen, den Host und das Maskieren der Anführungszeichen
GEHEIM = "Admin-Geheimnis-1234"

PROGRAMME = {"kern": wl.remote_programm, "nachlauf-dienst": lambda: na.REMOTE_DIENST, "messung": lambda: sv.REMOTE_MESSUNG,
             "lasttest-dienst": lambda: sv.REMOTE_DIENST}


def kommandozeile(argv: list[str]) -> int:
    """So lang wird die Befehlszeile des Prozesses unter Windows (subprocess baut sie mit list2cmdline)."""
    return len(subprocess.list2cmdline(argv))


class Fang:
    """Ersetzt subprocess.run: merkt sich die Befehlszeile, startet nie einen Prozess."""

    def __init__(self, stdout: str = ""):
        self.aufrufe: list[tuple[list[str], dict]] = []
        self.stdout = stdout

    def __call__(self, cmd, **kw):
        self.aufrufe.append((list(cmd), kw))
        return subprocess.CompletedProcess(cmd, 0, self.stdout, "")


# ---------- der Befehl selbst ----------

@pytest.mark.parametrize("name", sorted(PROGRAMME))
@pytest.mark.parametrize("sudo,isoliert", [(False, False), (False, True), (True, True)])
def test_befehl_ist_kurz_traegt_das_programm_gepackt_und_laesst_sich_zurueckholen(name, sudo, isoliert):
    programm = PROGRAMME[name]()
    befehl = ws.server_befehl(programm, sudo=sudo, isoliert=isoliert)
    assert len(befehl) <= ws.BEFEHL_MAX < GIT_SSH_GRENZE - SICHERHEIT
    assert befehl.startswith(("sudo -n " if sudo else "") + "python3 " + ("-I " if isoliert else "") + '-c "import base64,zlib;exec(')
    assert ws.programm_lesen(befehl) == programm
    assert not any(zeichen in ws.programm_code(programm) for zeichen in ws.IN_ANFUEHRUNGSZEICHEN_VERBOTEN)


def test_die_alte_befehlsform_war_zu_lang_der_kern_befehl_lag_ueber_der_grenze():
    """Die Ursache des Fehlers als Rechnung: ungepackt (nur base64) waren der Kern und die Messung über der Grenze, gepackt sind es alle nicht."""
    zu_lang = []
    for name, programm in PROGRAMME.items():
        alt = f"python3 -I -c \"import base64;exec(base64.b64decode('{base64.b64encode(programm().encode()).decode()}').decode('utf-8'))\""
        if len(alt) > GIT_SSH_GRENZE - 200:
            zu_lang.append(name)
    assert {"kern", "messung"} <= set(zu_lang)


def test_der_ferne_befehl_zerfaellt_in_der_shell_in_genau_die_erwarteten_woerter():
    programm = "print(1)"
    teile = shlex.split(ws.server_befehl(programm, sudo=True, isoliert=True))   # so zerlegt eine POSIX-Shell den Befehl am Server
    assert teile == ["sudo", "-n", "python3", "-I", "-c", ws.programm_code(programm)]
    assert shlex.split(ws.server_befehl(programm)) == ["python3", "-c", ws.programm_code(programm)]


def test_der_code_fuehrt_das_programm_mit_dem_echten_interpreter_aus_und_reicht_stdin_durch():
    programm = "import json, sys\nd = json.load(sys.stdin)\nprint(json.dumps({'summe': d['a'] + d['b'], 'name': __name__}))\n"
    r = subprocess.run([sys.executable, "-I", "-c", ws.programm_code(programm)], input=json.dumps({"a": 2, "b": 3}), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"summe": 5, "name": "__main__"}   # __main__: der Zweig "if __name__ == '__main__'" der Serverprogramme läuft


def test_ein_zu_grosses_programm_scheitert_laut_statt_still_abgeschnitten_zu_werden():
    gross = os.urandom(20000).hex()   # lässt sich kaum packen
    with pytest.raises(ws.BefehlFehler, match="8191"):
        ws.server_befehl(f"x = '{gross}'")


# ---------- jede Stelle, die ein Serverprogramm startet ----------

def test_kern_run_remote_baut_eine_kurze_befehlszeile_und_schickt_das_passwort_nur_per_stdin(monkeypatch):
    fang = Fang(stdout="Keine Laborprofile.\n")
    monkeypatch.setattr(wl.subprocess, "run", fang)
    monkeypatch.setattr(wl, "admin_passwort", lambda: GEHEIM)
    wl.run_remote("wamo-sokrates2", {"aktion": "status", "schema": "wamo_dev", "ausfuehren": False})
    argv, kw = fang.aufrufe[0]
    assert kommandozeile(argv) < GIT_SSH_GRENZE - SICHERHEIT
    assert ws.programm_lesen(argv[-1]) == wl.remote_programm() and GEHEIM not in " ".join(argv) and GEHEIM in kw["input"]


def test_kern_remote_des_lasttests_baut_eine_kurze_befehlszeile(monkeypatch):
    fang = Fang()
    monkeypatch.setattr(wl.subprocess, "run", fang)
    monkeypatch.setattr(sv.wl, "admin_passwort", lambda: GEHEIM)
    sv.kern_remote("wamo-sokrates2", {"aktion": "status", "schema": "wamo_dev"})
    argv, _ = fang.aufrufe[0]
    assert kommandozeile(argv) < GIT_SSH_GRENZE - SICHERHEIT and ws.programm_lesen(argv[-1]) == wl.remote_programm()


def test_dienst_remote_des_nachlaufs_baut_eine_kurze_befehlszeile(monkeypatch):
    fang = Fang(stdout='{"status": 200}')
    monkeypatch.setattr(na.subprocess, "run", fang)
    na.dienst_remote("wamo-sokrates2", {"aktion": "plaetze"})
    argv, _ = fang.aufrufe[0]
    assert kommandozeile(argv) < GIT_SSH_GRENZE - SICHERHEIT and argv[-1].startswith("sudo -n python3 -I -c ")


def test_ssh_aufrufe_des_lasttests_bauen_kurze_befehlszeilen(monkeypatch):
    fang = Fang(stdout='{"zeit": 1.0, "aktiv": true, "kerne": 4}')
    monkeypatch.setattr(sv.subprocess, "run", fang)
    sv.Server("wamo-sokrates2", slot="a").messen(None)
    sv.Dienst("wamo-sokrates2")   # baut den Befehl im Konstruktor, ein zu langer fiele hier auf
    argv, _ = fang.aufrufe[0]
    assert kommandozeile(argv) < GIT_SSH_GRENZE - SICHERHEIT and ws.programm_lesen(argv[-1]) == sv.REMOTE_MESSUNG
    assert kommandozeile(["ssh", "-o", "BatchMode=yes", "h", sv.Dienst("h")._befehl]) < GIT_SSH_GRENZE - SICHERHEIT


def test_zu_grosse_serverprogramme_scheitern_an_jeder_stelle_mit_klarer_meldung_und_ohne_ssh(monkeypatch):
    gross = f"x = '{os.urandom(20000).hex()}'"
    fang = Fang()
    monkeypatch.setattr(wl.subprocess, "run", fang)
    monkeypatch.setattr(wl, "admin_passwort", lambda: GEHEIM)
    monkeypatch.setattr(wl, "remote_programm", lambda: gross)
    with pytest.raises(wl.Fehler, match="8191"):
        wl.run_remote("h", {"aktion": "status"})
    kern = sv.kern_remote("h", {"aktion": "status"})
    assert kern.code == 1 and "8191" in kern.stderr
    monkeypatch.setattr(na, "REMOTE_DIENST", gross)
    e = na.dienst_remote("h", {"aktion": "plaetze"})
    assert e.code == 1 and "8191" in e.stderr
    with pytest.raises(sv.ServerFehler, match="8191"):
        sv.befehl_fuer(gross, sudo=True)
    assert fang.aufrufe == []   # nichts wurde gestartet


def test_der_nachlauf_scheitert_nicht_mehr_in_schritt_1_an_der_befehlszeile(monkeypatch, tmp_path):
    """Der Fall vom 20.11.2026: Schritt 1 (Zählung davor) ruft den Kern über wamo_labor.run_remote. Der Befehl hat jetzt die erwartete Länge."""
    fang = Fang(stdout="labor-01 | platz | gesperrt | 0 Zeilen\n")
    monkeypatch.setattr(wl.subprocess, "run", fang)
    monkeypatch.setattr(wl, "admin_passwort", lambda: GEHEIM)
    z = na.Zugriff("wamo-sokrates2", "wamo_dev", wl.run_remote, na.dienst_remote, lambda s: None)
    assert na.kern_stand_lesen(z.kern_aufruf("status", ausfuehren=False)).profile == 1
    assert kommandozeile(fang.aufrufe[0][0]) < GIT_SSH_GRENZE - SICHERHEIT


# ---------- die Zerlegung durch ein MSYS-Programm (nur mit Git für Windows, ohne ssh) ----------

GIT_PRINTF = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "printf.exe"


@pytest.mark.skipif(not (sys.platform == "win32" and GIT_PRINTF.is_file()), reason="nur mit Git für Windows (MSYS) prüfbar")
@pytest.mark.parametrize("name", sorted(PROGRAMME))
def test_msys_programm_bekommt_den_befehl_unversehrt(name):
    """printf.exe aus Git für Windows zerlegt seine Befehlszeile wie das ssh aus Git: Der Befehl muss vollständig ankommen (nicht abgeschnitten)."""
    befehl = ws.server_befehl(PROGRAMME[name](), sudo=True, isoliert=True)
    r = subprocess.run([str(GIT_PRINTF), "%s", befehl], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout == befehl
