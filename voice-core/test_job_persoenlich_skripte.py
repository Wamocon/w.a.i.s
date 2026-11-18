"""Tests für die Skripte des persönlichen GitHub-Wegs (Plan C, Paket D-a): wamo-job.sh in den Modi klon, ausgabe und pruefung (Aufbau),
die festen Programme wamo-job-klon.sh und wamo-job-ausgabe.sh (mit echtem git, ohne Sandbox), wamo-job-einrichten.sh und wamo-job-rueckweg.sh
(Timer, Aufräumen, Sperre der Schlüssel) und wamo-job-kern-einrichten.sh (kanal --persoenlich, schalter --github) im Probelauf.

Die Welt der Kern-Skripte kommt aus test_job_kern_skripte.py (dieselben Fixtures). Die Proben in der echten Sandbox (kein Netz, keine Token,
Helfer) macht wamo-job-rauchtest --persoenlich am Server. Ausführen (im Ordner voice-core/):  python -m pytest -q test_job_persoenlich_skripte.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from test_job_kern_skripte import (BASH, DROPIN_REL, PROFIL, RELEASE, _gemerkte_staende_aufraeumen, braucht_bash, einr,  # noqa: F401
                                   hostschluessel, lauf, schluessel_einrichten, welt, wurzel)

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"
JOB = "abc1234567890def"
LAEUFER = (INFRA / "wamo-job.sh").read_text(encoding="utf-8")


def lies(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- wamo-job.sh: Aufbau der drei Schritte
def test_die_modi_sind_ein_case_mit_ablehnung_und_die_schritte_haben_nie_netz():
    assert re.search(r'^case "\$MODUS" in\n  lauf\|pruefen\|klon\|ausgabe\|pruefung\) ;;\n  \*\) fehler', LAEUFER, flags=re.M)
    assert '[ "$MODUS" = lauf ] || NETZ_OPTION=--unshare-net' in LAEUFER
    assert '[ "$MODUS" = lauf ] || ERLAUBT_RE=$ERLAUBT_PRUEFEN_RE' in LAEUFER  # kein Token, nichts von Claude
    assert "ZEITLIMIT_KLON_S=300\n" in LAEUFER and "ZEITLIMIT_SCHRITT_S=60\n" in LAEUFER and "SCHRITT_DATEI_MAX_MB=256\n" in LAEUFER
    # Claude, Plugins und Zustand gibt es nur im Auftragslauf; die Werkzeuge im Home nur außerhalb der Schritte
    assert LAEUFER.count('if [ "$MODUS" = lauf ]; then\n  ARGS+=(--ro-bind "$HEIM/.local/share/claude"') == 1
    assert '[ "$SCHRITT" = 1 ] || ARGS+=(--ro-bind "$HEIM/.local/bin" "$HEIM/.local/bin")' in LAEUFER


def test_die_zeitlimits_der_schritte_gelten_nach_den_engeren_grenzen_und_nie_ueber_dem_hoechstwert():
    aufruf = LAEUFER.index("\n  pruefen_grenzen\n")
    assert aufruf < LAEUFER.index("ZEIT_HOECHSTENS=$(kleiner_zahl \"$ZEITLIMIT_KLON_S\" \"$ZEITLIMIT_MAX_S\")")
    assert 'ausgabe|pruefung) ZEIT_HOECHSTENS=$(kleiner_zahl "$ZEITLIMIT_SCHRITT_S" "$ZEITLIMIT_MAX_S")' in LAEUFER
    assert '(( ZEIT <= ZEIT_HOECHSTENS )) || fehler "Zeitlimit im Modus $MODUS' in LAEUFER
    assert aufruf < LAEUFER.index("ZEIT=${ZEIT:-$ZEITLIMIT_PRUEFEN_S}") < LAEUFER.index("(( ZEIT <= ZEITLIMIT_PRUEFEN_S ))") < LAEUFER.index("ARGS=(")


def test_jeder_schritt_startet_nur_sein_festes_programm():
    for teil in ('klon) [ "$1" = "$WAECHTER_INNEN/wamo-job-klon.sh" ] || fehler',
                 'ausgabe) [ "$1" = "$WAECHTER_INNEN/wamo-job-ausgabe.sh" ] || fehler',
                 '[ "$1" = /usr/bin/python3 ] && [ "$2" = -I ] && [ "$3" = "$WAECHTER_INNEN/wamo_job_auszug.py" ]',
                 'if [ "$#" -eq 2 ] && [ "$1" = "$WAECHTER_INNEN/wamo-job-klon.sh" ] && [ "$2" = --probe ]; then'):
        assert teil in LAEUFER, teil


def test_mounts_der_schritte():
    assert 'ausgabe) ARGS+=(--ro-bind "$PROJDIR" "$PROJEKTE/$PROJEKT") ;;' in LAEUFER  # Projekt nur lesend
    assert "  pruefung) ;;\n" in LAEUFER  # kein Projekt
    assert 'ARGS+=("$BINDE_RO" "$JOBDIR/basis.git" /run/wamo/basis.git)' in LAEUFER
    assert 'ARGS+=(--ro-bind "$JOBDIR/bundle.ein" /run/wamo/letztes.bundle)' in LAEUFER
    assert 'ausgabe) ARGS+=("$BINDE" "$JOBDIR/ausgabe" /run/wamo/ausgabe) ;;' in LAEUFER
    assert '"$BINDE_RO" "$JOBDIR/bundle.ein" /run/wamo/bundle.ein "$BINDE_RO" "$JOBDIR/basis.git" /run/wamo/basis.git' in LAEUFER
    assert '"$BINDE" "$JOBDIR/ergebnis" /run/wamo/ergebnis' in LAEUFER
    assert 'ARGS+=(--remount-ro / --chdir /tmp)' in LAEUFER
    for pruefung in ("klon) schritt_ordner basis.git", "ausgabe) schritt_ordner ausgabe",
                     "pruefung) schritt_ordner basis.git; schritt_datei bundle.ein; schritt_ordner ergebnis"):
        assert pruefung in LAEUFER, pruefung


def test_der_lauf_im_persoenlichen_weg_bekommt_nur_die_sechs_namen_und_kein_dienst_token():
    erlaubt = set(re.search(r"ERLAUBT_RE='\^\(([^)]*)\)\$'", LAEUFER).group(1).split("|"))
    assert {"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "WAMO_GITHUB", "WAMO_ZWEIG"} <= erlaubt
    pruefen = set(re.search(r"ERLAUBT_PRUEFEN_RE='\^\(([^)]*)\)\$'", LAEUFER).group(1).split("|"))
    assert not pruefen & {"WAMO_GITHUB", "GH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
    block = LAEUFER[LAEUFER.index('if [ "$MODUS" = lauf ] && [ -n "${WAMO_GITHUB-}" ]; then'):]
    block = block[:block.index("\nfi\n")]
    assert "unset GH_TOKEN VERCEL_TOKEN VERCEL_ORG_ID SUPABASE_ACCESS_TOKEN JIRA_URL JIRA_EMAIL JIRA_API_KEY JIRA_API_TOKEN" in block
    assert '[ "${WAMO_ZWEIG-}" = "wamo/$JOB" ]' in block
    assert "unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL WAMO_GITHUB WAMO_ZWEIG" in LAEUFER


@braucht_bash
@pytest.mark.parametrize("skript", ["wamo-job.sh", "wamo-job-klon.sh", "wamo-job-ausgabe.sh", "wamo-job-einrichten.sh", "wamo-job-rueckweg.sh",
                                    "wamo-job-kern-einrichten.sh", "wamo-job-kern-rueckweg.sh"])
def test_bash_syntax_und_zeilenenden(skript):
    p = subprocess.run([BASH, "-n", str(INFRA / skript)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    text = lies(skript)
    assert "\r" not in text and "—" not in text and "–" not in text


def test_einheiten_und_helfer_haben_lf_und_feste_regeln():
    dienst = lies("wamo-job-aufraeumen.service")
    for zeile in ("User=wamo", "ExecStart=/opt/wamo/bin/wamo-job-dispatch aufraeumen", "PrivateNetwork=yes", "ProtectSystem=strict",
                  "NoNewPrivileges=yes", "ReadWritePaths=/srv/wamo/jobs /srv/wamo/projekte /srv/wamo/logs", "CapabilityBoundingSet="):
        assert zeile in dienst.splitlines(), zeile
    assert "OnCalendar=" in lies("wamo-job-aufraeumen.timer") and "Persistent=true" in lies("wamo-job-aufraeumen.timer")
    attribute = (INFRA.parent.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "infra/sokrates2/wamo-git-zugang text eol=lf" in attribute and "*.timer text eol=lf" in attribute


# ---------------------------------------------------------------- wamo-job-klon.sh und wamo-job-ausgabe.sh mit echtem git
def _shell_pfad(pfad: Path) -> str:
    if os.name != "nt":
        return str(pfad)
    laufwerk, rest = str(pfad).split(":", 1)
    return f"/{laufwerk.lower()}{rest}".replace("\\", "/")


def _kopie(name: str, ziel: Path, ersetzungen: dict[str, str]) -> Path:
    """Das Skript mit Pfaden im Wegwerf-Ordner statt /run/wamo (außerhalb der Sandbox gibt es /run/wamo nicht); die Prüfung, dass es im
    Projektordner der Sandbox läuft, entfällt dort."""
    text = lies(name)
    pruefung = '[ "$P" = "$(readlink /run/wamo/projekt)" ] && [[ $P == /srv/wamo/projekte/* ]] || fehler "nicht im Projektordner der Sandbox"'
    assert text.count(pruefung) == 1
    text = text.replace(pruefung, "true")
    for alt, neu in ersetzungen.items():
        assert alt in text, alt
        text = text.replace(alt, neu)
    pfad = ziel / name
    pfad.write_text(text, encoding="utf-8", newline="\n")
    return pfad


def _git(*args: str, cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env).stdout.strip()


@pytest.fixture
def repos():
    if not shutil.which("git") or BASH is None:
        pytest.skip("git oder bash fehlt")
    ordner = Path(tempfile.mkdtemp(prefix="wamo-klon-"))
    try:
        quelle = ordner / "quelle"
        quelle.mkdir()
        _git("init", "-q", "-b", "main", str(quelle))
        (quelle / "app.py").write_text("print(1)\n", encoding="utf-8")
        _git("add", ".", cwd=quelle)
        _git("commit", "-q", "-m", "Basis", cwd=quelle)
        basis = _git("rev-parse", "HEAD", cwd=quelle)
        _git("clone", "-q", "--bare", str(quelle), str(ordner / "basis.git"))
        projekt = ordner / "projekt"
        projekt.mkdir()
        (projekt / "alt.txt").write_text("vom Vorgänger", encoding="utf-8")
        (projekt / "ordner").mkdir()
        (projekt / "ordner" / "x").write_text("x", encoding="utf-8")
        (ordner / "ausgabe").mkdir()
        sh = _shell_pfad(ordner)
        klon = _kopie("wamo-job-klon.sh", ordner, {"/run/wamo/basis.git": f"{sh}/basis.git", "/run/wamo/letztes.bundle": f"{sh}/letztes.bundle"})
        ausgabe = _kopie("wamo-job-ausgabe.sh", ordner, {"/run/wamo/ausgabe": f"{sh}/ausgabe"})
        yield {"ordner": ordner, "projekt": projekt, "basis": basis, "klon": klon, "ausgabe": ausgabe}
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _weg(pfad: Path) -> None:
    """Löscht auch die schreibgeschützten Objekte von git (unter Windows sonst Zugriff verweigert)."""
    import stat

    def frei(funktion, p, _exc):
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        funktion(p)
    if pfad.is_dir() and not pfad.is_symlink():
        shutil.rmtree(pfad, onerror=frei)
    else:
        pfad.unlink()


def _skript(pfad: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run([BASH, _shell_pfad(pfad), *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=120)


def test_klon_leert_den_ordner_und_legt_den_zweig_auf_der_basis_an(repos):
    p = _skript(repos["klon"], "--repo", "octo/demo", "--auftrag", JOB, "--basis", repos["basis"], cwd=repos["projekt"])
    assert p.returncode == 0, p.stdout + p.stderr
    projekt = repos["projekt"]
    assert not (projekt / "alt.txt").exists() and not (projekt / "ordner").exists()
    assert (projekt / "app.py").read_text(encoding="utf-8") == "print(1)\n"
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=projekt) == f"wamo/{JOB}"
    assert _git("rev-parse", "HEAD", cwd=projekt) == repos["basis"]
    assert _git("remote", "get-url", "origin", cwd=projekt) == "https://github.com/octo/demo.git"
    assert not list((projekt / ".git" / "hooks").glob("*")) if (projekt / ".git" / "hooks").exists() else True  # ohne Vorlage


def test_ausgabe_und_folgelauf_aus_dem_bundle(repos):
    projekt = repos["projekt"]
    assert _skript(repos["klon"], "--repo", "octo/demo", "--auftrag", JOB, "--basis", repos["basis"], cwd=projekt).returncode == 0
    p = _skript(repos["ausgabe"], "--auftrag", JOB, "--basis", repos["basis"], cwd=projekt)
    assert p.returncode == 0, p.stderr
    assert not (repos["ordner"] / "ausgabe" / "aenderung.bundle").exists()  # keine Commits: kein Bundle (Status keine)
    assert (repos["ordner"] / "ausgabe" / "status.json").read_bytes() == b"0\n"  # nur eine ganze Zahl (wamo_job_github._status_lesen)
    (projekt / "neu.py").write_text("print(2)\n", encoding="utf-8")
    _git("add", "neu.py", cwd=projekt)
    _git("commit", "-q", "-m", f"Neu\n\nWAIS-Auftrag: {JOB}", cwd=projekt)
    (projekt / "offen.txt").write_text("nicht committet", encoding="utf-8")
    for alt in (repos["ordner"] / "ausgabe").iterdir():
        alt.unlink()
    assert _skript(repos["ausgabe"], "--auftrag", JOB, "--basis", repos["basis"], cwd=projekt).returncode == 0
    bundle = repos["ordner"] / "ausgabe" / "aenderung.bundle"
    assert bundle.is_file()
    assert (repos["ordner"] / "ausgabe" / "status.json").read_bytes() == b"1\n"
    # Folgelauf in einem Ordner, den inzwischen ein anderer Auftrag gebaut hat: neu aus basis.git und dem letzten Bundle
    shutil.copy(bundle, repos["ordner"] / "letztes.bundle")
    for kind in list(projekt.iterdir()):
        _weg(kind)
    (projekt / "fremd.txt").write_text("anderer Auftrag", encoding="utf-8")
    p = _skript(repos["klon"], "--repo", "octo/demo", "--auftrag", JOB, "--basis", repos["basis"], "--bundle", cwd=projekt)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (projekt / "fremd.txt").exists() and (projekt / "neu.py").read_text(encoding="utf-8") == "print(2)\n"
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=projekt) == f"wamo/{JOB}"


def test_ausgabe_verlangt_einen_leeren_ordner_und_gueltige_werte(repos):
    projekt = repos["projekt"]
    (repos["ordner"] / "ausgabe" / "gepflanzt").write_text("x", encoding="utf-8")
    assert _skript(repos["ausgabe"], "--auftrag", JOB, "--basis", repos["basis"], cwd=projekt).returncode == 70
    for args in (["--auftrag", "XYZ", "--basis", repos["basis"]], ["--auftrag", JOB, "--basis", "abc"], ["--auftrag", JOB], ["--frei"]):
        assert _skript(repos["ausgabe"], *args, cwd=projekt).returncode == 2, args
    for args in (["--repo", "a b/c", "--auftrag", JOB, "--basis", repos["basis"]], ["--repo", "o/..", "--auftrag", JOB, "--basis", repos["basis"]],
                 ["--repo", "o/r", "--auftrag", JOB, "--basis", repos["basis"], "--extra"]):
        assert _skript(repos["klon"], *args, cwd=projekt).returncode == 2, args
    assert (projekt / "alt.txt").exists()  # ungültige Werte: nichts geleert


def test_probe_meldet_namen_und_netz_als_json(repos):
    p = _skript(repos["klon"], "--probe", cwd=repos["projekt"])
    assert p.returncode == 0
    antwort = json.loads(p.stdout.strip().splitlines()[-1])
    assert set(antwort) == {"modus", "umgebung", "netz", "github"} and isinstance(antwort["umgebung"], list)
    assert antwort["netz"] in ("zu", "offen") and antwort["github"] in ("zu", "offen")


# ---------------------------------------------------------------- wamo-job-einrichten.sh und wamo-job-rueckweg.sh
def test_die_einrichtung_installiert_helfer_skripte_modul_und_timer():
    text = lies("wamo-job-einrichten.sh")
    for teil in ('install -o root -g "$WAMO_USER" -m 0750 "$HERE/wamo-git-zugang" "$APP/bin/wamo-git-zugang"',
                 'install -o root -g "$WAMO_USER" -m 0750 "$HERE/wamo-job-klon.sh" "$HERE/wamo-job-ausgabe.sh" "$APP/waechter/"',
                 'install -o root -g "$WAMO_USER" -m 0640 "$HERE/wamo_job_github.py" "$APP/waechter/"',
                 '"bin/wamo-git-zugang:wamo-git-zugang"', '"waechter/wamo_job_github.py:wamo_job_github.py"',
                 '"waechter/wamo-job-klon.sh:wamo-job-klon.sh"', '"waechter/wamo-job-ausgabe.sh:wamo-job-ausgabe.sh"',
                 "systemctl enable --now wamo-job-aufraeumen.timer", "GITHUB_LOGIK=(wamo_job_pfadregeln.py wamo_job_auszug.py)"):
        assert teil in text, teil
    assert "wamo_job_github.py wamo_job_pfadregeln.py wamo_job_auszug.py wamo-git-zugang wamo-job-klon.sh wamo-job-ausgabe.sh" in text
    for datei in ("wamo_job_github.py", "wamo_job_pfadregeln.py", "wamo_job_auszug.py", "wamo-git-zugang", "wamo-job-klon.sh"):
        assert (INFRA / datei).is_file(), datei  # alles, was die Einrichtung verlangt, liegt im Repo


def _sicherung(w: Path, dispatcher: str, neu: str = "") -> Path:
    app = w / "opt" / "wamo"
    (app / "bin").mkdir(parents=True)
    alt = app / "vorher" / "20261118T100000Z"
    (alt / "bin").mkdir(parents=True)
    (alt / "bin" / "wamo-job-dispatch").write_text(dispatcher, encoding="utf-8")
    (alt / "NEU.txt").write_bytes(neu.encode())
    (app / "bin" / "wamo-job-dispatch").write_text('VERSION = "10"\n', encoding="utf-8")
    return app


@braucht_bash
def test_rueckweg_auf_dispatcher_9_verlangt_erst_das_entfernen_der_schluessel(wurzel):
    w, shell = wurzel
    app = _sicherung(w, 'VERSION = "9"\n', "bin/wamo-git-zugang\n")
    konf = w / "etc" / "wamo" / "kernkanal.conf"
    konf.parent.mkdir(parents=True)
    konf.write_text("KANAL=offen\nPERSOENLICH=aus\nMAX_KLON_MB=2048\n", encoding="utf-8")
    einheiten = w / "etc" / "systemd" / "system"
    einheiten.mkdir(parents=True)
    for name in ("wamo-job-aufraeumen.timer", "wamo-job-aufraeumen.service"):
        (einheiten / name).write_text("[Unit]\n", encoding="utf-8")
    p = lauf(INFRA / "wamo-job-rueckweg.sh", shell_wurzel=shell, variable="WAMO_JOB_WURZEL")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "kanal --persoenlich entfernen" in p.stderr
    assert (app / "bin" / "wamo-job-dispatch").read_text() == 'VERSION = "10"\n'  # nichts zurückgespielt
    konf.write_text("KANAL=offen\n", encoding="utf-8")
    p = lauf(INFRA / "wamo-job-rueckweg.sh", shell_wurzel=shell, variable="WAMO_JOB_WURZEL")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (app / "bin" / "wamo-job-dispatch").read_text() == 'VERSION = "9"\n'
    assert not (einheiten / "wamo-job-aufraeumen.timer").exists() and not (einheiten / "wamo-job-aufraeumen.service").exists()


@braucht_bash
def test_rueckweg_innerhalb_von_dispatcher_10_laesst_den_weg_stehen(wurzel):
    w, shell = wurzel
    _sicherung(w, 'VERSION = "10"\n')
    einheiten = w / "etc" / "systemd" / "system"
    einheiten.mkdir(parents=True)
    (einheiten / "wamo-job-aufraeumen.timer").write_text("[Unit]\n", encoding="utf-8")
    konf = w / "etc" / "wamo" / "kernkanal.conf"
    konf.parent.mkdir(parents=True)
    konf.write_text("KANAL=offen\nPERSOENLICH=an\n", encoding="utf-8")
    p = lauf(INFRA / "wamo-job-rueckweg.sh", shell_wurzel=shell, variable="WAMO_JOB_WURZEL")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (einheiten / "wamo-job-aufraeumen.timer").exists()


# ---------------------------------------------------------------- wamo-job-kern-einrichten.sh: kanal --persoenlich, schalter --github
def _konf(welt) -> dict[str, str]:
    text = (welt["w"] / "etc" / "wamo" / "kernkanal.conf").read_text(encoding="utf-8")
    return dict(z.split("=", 1) for z in text.splitlines() if z and not z.startswith("#"))


def _weg_bereit(welt, version: str = "10") -> None:
    pfad = welt["w"] / "opt" / "wamo" / "bin" / "wamo-job-dispatch"
    text = pfad.read_text(encoding="utf-8")
    pfad.write_text(re.sub(r'^VERSION = "\d+"$', f'VERSION = "{version}"', text, flags=re.M), encoding="utf-8")
    welt["schreibe"]("opt/wamo/waechter/wamo_job_github.py", (INFRA / "wamo_job_github.py").read_bytes())
    for modul in ("wamo_job_pfadregeln.py", "wamo_job_auszug.py"):  # die GitHub-Logik von Paket D-b (hier Attrappen)
        welt["schreibe"](f"opt/wamo/waechter/{modul}", "# Attrappe\n")


@braucht_bash
def test_kanal_persoenlich_an_aus_und_entfernen(welt):
    schluessel_einrichten(welt)
    assert "PERSOENLICH" not in _konf(welt)  # nie ungefragt: Dispatcher 9 schlösse sonst den Kanal
    _weg_bereit(welt)
    kanal_vorher = _konf(welt)["KANAL"]
    p = einr(welt, "kanal", "--persoenlich", "an", "--max-klon-mb", "1024")
    assert p.returncode == 0, p.stdout + p.stderr
    k = _konf(welt)
    assert (k["PERSOENLICH"], k["MAX_EINREICHEN_TAG"], k["MAX_EINREICHEN_TAG_PROFIL"], k["MAX_KLON_MB"]) == ("an", "10", "5", "1024")
    assert k["KANAL"] == kanal_vorher  # ohne --arten bleibt der Rest der Datei
    assert einr(welt, "kanal", "--persoenlich", "aus").returncode == 0
    assert _konf(welt)["PERSOENLICH"] == "aus" and _konf(welt)["MAX_KLON_MB"] == "1024"
    p = einr(welt, "kanal", "--persoenlich", "an", "--max-einreichen-tag", "3", "--max-einreichen-tag-profil", "4")
    assert p.returncode == 3 and _konf(welt)["PERSOENLICH"] == "aus"  # je Person nie mehr als gesamt
    assert einr(welt, "kanal", "--persoenlich", "entfernen").returncode == 0
    assert not set(_konf(welt)) & {"PERSOENLICH", "MAX_EINREICHEN_TAG", "MAX_EINREICHEN_TAG_PROFIL", "MAX_KLON_MB"}


@braucht_bash
def test_kanal_persoenlich_verlangt_die_github_logik(welt):
    schluessel_einrichten(welt)
    _weg_bereit(welt)
    (welt["w"] / "opt" / "wamo" / "waechter" / "wamo_job_auszug.py").unlink()
    p = einr(welt, "kanal", "--persoenlich", "an")
    assert p.returncode == 3 and "wamo_job_auszug.py fehlt" in p.stderr, p.stdout + p.stderr


@braucht_bash
def test_kanal_persoenlich_verlangt_dispatcher_10(welt):
    schluessel_einrichten(welt)
    _weg_bereit(welt, version="9")
    for wert in ("an", "aus"):
        p = einr(welt, "kanal", "--persoenlich", wert)
        assert p.returncode == 3 and "Version 10" in p.stderr, p.stdout + p.stderr
    assert "PERSOENLICH" not in _konf(welt)
    assert einr(welt, "kanal", "--persoenlich", "entfernen").returncode == 0  # entfernen geht immer (vor dem Rückweg)


@braucht_bash
@pytest.mark.parametrize("args", [["kanal", "--persoenlich", "ja"], ["kanal", "--persoenlich"], ["kanal", "--max-klon-mb", "2048"],
                                  ["kanal", "--persoenlich", "an", "--max-klon-mb", "50"], ["kanal", "--persoenlich", "an", "--repos", "a/b"],
                                  ["kanal", "--persoenlich", "entfernen", "--max-klon-mb", "200"],
                                  ["schalter", "an", RELEASE, "--profil", PROFIL, "--github", "ja"], ["schalter", "aus", RELEASE, "--github", "aus"]])
def test_falsche_aufrufformen_des_persoenlichen_wegs(welt, args):
    assert einr(welt, *args).returncode == 2, args


@braucht_bash
def test_schalter_github_nur_mit_option_und_ab_schranken_4(welt):
    schluessel_einrichten(welt)
    _weg_bereit(welt)
    ziel = f"opt/wamo-core/releases/{RELEASE}/voice-core/entwicklung_betrieb.py"
    p = einr(welt, "schalter", "an", RELEASE, "--profil", PROFIL, "--github", "an")
    assert p.returncode == 3 and "SCHRANKEN_VERSION" in p.stderr, p.stdout + p.stderr
    welt["schreibe"](ziel, "SCHRANKEN_VERSION = 4\n")
    p = einr(welt, "schalter", "an", RELEASE, "--profil", PROFIL, "--github", "an")
    assert p.returncode == 0, p.stdout + p.stderr
    zeilen = (welt["w"] / DROPIN_REL).read_text(encoding="utf-8").splitlines()
    assert zeilen[-1] == "Environment=WAMO_ENTWICKLUNG_GITHUB=an" and zeilen[-2] == "Environment=WAMO_ENTWICKLUNG_HAUS=aus"
    assert "PERSOENLICH nicht auf an" in p.stdout  # Hinweis: im Kanal noch aus
    p = einr(welt, "schalter", "an", RELEASE, "--profil", PROFIL)
    zeilen = (welt["w"] / DROPIN_REL).read_text(encoding="utf-8").splitlines()
    assert p.returncode == 0 and zeilen[-1] == "Environment=WAMO_ENTWICKLUNG_GITHUB=aus"  # ohne die Option: aus, die Zeile steht immer
    assert "GitHub-Weg ist danach aus" in p.stdout
