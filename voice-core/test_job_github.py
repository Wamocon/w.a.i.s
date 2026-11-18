"""Tests für die GitHub-Logik des persönlichen Wegs (infra/sokrates2/wamo_job_github.py, Plan C, Paket D-b).

Kein echter GitHub-Aufruf: GitHub ist eine Attrappe über die Protokoll-Klasse Werkzeuge. Die Attrappe führt git echt aus, aber nur lokal:
https://github.com/<repo>.git zeigt über url.insteadOf auf ein bare Repo im Testordner. Die Sandbox-Schritte ausgabe und pruefung laufen
als Python in der Attrappe (Bundle mit echtem git, Auszug mit wamo_job_auszug.py). Ohne git werden diese Tests übersprungen.
Ausführen (im Ordner voice-core/):  python -m pytest -q test_job_github.py
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"
GIT = shutil.which("git")
mit_git = pytest.mark.skipif(GIT is None, reason="git fehlt")


def _lade(name: str, datei: str):
    spec = importlib.util.spec_from_file_location(name, INFRA / datei)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


G = _lade("wamo_job_github", "wamo_job_github.py")
A = G._auszug()
R = G._regeln()

JOB = "0123456789abcdef"
PROFIL = "a1b2c3d4"
REPO = "beispiel/projekt"
REPO_ID = 4242
KONTO_ID = 4711
LOGIN = "niko-test"
JETZT = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc).timestamp()
ABLAUF = "2026-12-31 23:59:59 UTC"
TOKEN = b"ghp_" + b"T" * 36  # zusammengesetzt, kein Tokenwert als Text in der Datei
ZEIT = "1700000000 +0000"
GIT_ARG_RE = re.compile(r"[A-Za-z0-9_@%+=:,./^~-]{1,4096}")  # wie GIT_ARG_RE im Dispatcher (D-a): sonst lehnt er den Aufruf ab


def antwort(status: int = 200, daten: object = None, kopf: dict | None = None):
    return G.HttpAntwort(status=status, kopf=kopf or {}, daten=daten)


def user_antwort(scopes: str | None = "repo", ablauf: str | None = ABLAUF, konto: int = KONTO_ID):
    kopf = {}
    if scopes is not None:
        kopf["x-oauth-scopes"] = scopes
    if ablauf is not None:
        kopf["github-authentication-token-expiration"] = ablauf
    return antwort(200, {"login": LOGIN, "id": konto, "type": "User"}, kopf)


def repo_daten(**anders) -> dict:
    daten = {"full_name": REPO, "id": REPO_ID, "fork": False, "private": True, "size": 100, "default_branch": "main",
             "permissions": {"pull": True, "push": True, "admin": False}}
    daten.update(anders)
    return daten


def _git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "T",
                "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x", "GIT_AUTHOR_DATE": ZEIT,
                "GIT_COMMITTER_DATE": ZEIT})
    return env


def git(git_dir: Path, *args: str, eingabe: bytes | None = None) -> bytes:
    erg = subprocess.run([GIT, f"--git-dir={git_dir}", *args], input=eingabe, capture_output=True, env=_git_env())
    assert erg.returncode == 0, erg.stderr.decode(errors="replace")
    return erg.stdout


def importieren(git_dir: Path, ref: str, staende: tuple[dict, ...], von: str | None) -> str:
    """Commits mit fast-import (jeder Stand ist der ganze Baum); Ergebnis: Commit-ID der Spitze."""
    strom = []
    for i, stand in enumerate(staende, start=1):
        strom.append(f"commit {ref}\nmark :{i}\ncommitter T <t@x> {ZEIT}\ndata 1\nm\n".encode())
        if i == 1 and von:
            strom.append(f"from {von}\n".encode())
        strom.append(b"deleteall\n")
        for pfad, (modus, inhalt) in stand.items():
            strom.append(f"M {modus} inline ".encode() + pfad.encode() + b"\n" + b"data %d\n" % len(inhalt) + inhalt + b"\n")
    strom.append(f"get-mark :{len(staende)}\n".encode())
    # core.ignorecase aus: git unter Windows legte sonst zwei Pfade, die sich nur in der Schreibweise unterscheiden, zusammen
    return git(git_dir, "-c", "core.ignorecase=false", "fast-import", "--quiet", "--done",
               eingabe=b"".join(strom) + b"done\n").decode().strip()


BASIS = {
    "README.md": ("100644", b"hallo\n"),
    "alt.txt": ("100644", b"weg\n"),
    "src/app.py": ("100644", b"print(1)\n"),
    "package.json": ("100644", b"{}\n"),
    ".mcp.json": ("100644", b"{}\n"),
    ".claude/settings.json": ("100644", b"{}\n"),
    "bin/tool": ("100755", b"#!/bin/sh\n"),
}


def stand(aenderungen: dict | None = None) -> dict:
    out = dict(BASIS)
    for pfad, wert in (aenderungen or {}).items():
        if wert is None:
            out.pop(pfad, None)
        else:
            out[pfad] = wert
    return out


@pytest.fixture(scope="module")
def vorrat(tmp_path_factory):
    """Einmal je Modul: das Repo auf "GitHub" mit dem Stand BASIS auf main."""
    if GIT is None:
        pytest.skip("git fehlt")
    ordner = tmp_path_factory.mktemp("github")
    ziel = ordner / "beispiel" / "projekt.git"
    ziel.parent.mkdir(parents=True)
    subprocess.run([GIT, "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(ziel)], check=True, env=_git_env())
    basis = importieren(ziel, "refs/heads/main", (BASIS,), None)
    return ordner, basis


class Attrappe:
    """Werkzeuge für die Tests. git läuft echt, aber nur gegen lokale Repos; jeder Aufruf wird mitgeschrieben."""

    def __init__(self, tmp: Path, remote: Path, basis: str):
        self.tmp, self.remote, self.basis = tmp, remote, basis
        self.jobdir = tmp / "jobs" / JOB
        self.jobdir.mkdir(parents=True)
        self.token: bytes | None = TOKEN
        self.antworten: dict = {("GET", "/user"): user_antwort(), ("GET", f"/repos/{REPO}"): antwort(200, repo_daten())}
        self.http_aufrufe: list = []
        self.git_aufrufe: list = []
        self.sandbox_aufrufe: list = []
        self.logs: list = []
        self.werte: list[bytes] = []
        self.nach_klon = None  # Rückruf nach clone (für gepflanzte Reste)
        self.sandbox_git = tmp / "sandbox.git"  # die Arbeitskopie der Sandbox als bare Repo
        self.schritte = {"ausgabe": Attrappe.ausgabe_standard, "pruefung": Attrappe.pruefung_standard}
        self.status_json = b"0\n"
        self.nach_auszug = None
        self.zaehler = 0

    # -------- Werkzeuge
    def log(self, text: str, *, pflicht: bool = False) -> None:
        self.logs.append(text)

    def http(self, methode: str, pfad: str, daten=None):
        self.http_aufrufe.append((methode, pfad, daten))
        if self.token is None:
            raise G.KeinToken()
        wert = self.antworten.get((methode, pfad))
        if isinstance(wert, list):
            wert = wert.pop(0) if len(wert) > 1 else wert[0]
        if callable(wert):
            wert = wert(daten)
        if wert is None or isinstance(wert, Exception):
            raise wert if isinstance(wert, Exception) else G.NetzFehler("keine Antwort")
        return wert

    def git(self, args, *, git_dir, eingabe=None, netz=False, zeitlimit_s=60.0):
        args = tuple(args)
        assert args and befehl_von(args) in {"clone", "init", "rev-parse", "cat-file", "ls-tree", "read-tree", "hash-object",
                                             "update-index", "write-tree", "diff-tree", "update-ref", "ls-remote", "push"}, args
        if netz:
            assert befehl_von(args) in {"clone", "ls-remote", "push"}, args
        self.git_aufrufe.append({"args": args, "git_dir": git_dir, "netz": netz, "eingabe": eingabe})
        wurzel = str(self.tmp)
        for a in args:
            assert GIT_ARG_RE.fullmatch(a.replace(wurzel, "/w").replace("\\", "/")) or a == "--template=", a
        if netz and self.token is None:
            raise G.KeinToken()
        argv = [GIT, "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", "-c", "gc.auto=0", "-c",
                "protocol.allow=never", "-c", "protocol.file.allow=always", "-c", "transfer.fsckObjects=true"]
        if netz:
            argv += ["-c", f"url.{self.remote.as_posix()}/.insteadOf=https://github.com/"]
        if git_dir is not None:
            argv.append(f"--git-dir={git_dir}")
        erg = subprocess.run(argv + list(args), input=eingabe, capture_output=True, env=_git_env(), timeout=120)
        if befehl_von(args) == "clone" and erg.returncode == 0 and self.nach_klon:
            self.nach_klon(Path(args[-1]))
        return G.GitErgebnis(code=erg.returncode, stdout=erg.stdout, stderr=erg.stderr.decode("utf-8", "replace")[:500])

    def sandbox(self, modus, *, job, projekt, zeitlimit_s):
        assert modus in G.SANDBOX_MODI_NETZLOS and job == JOB
        self.sandbox_aufrufe.append(modus)
        return self.schritte[modus](self)

    @contextlib.contextmanager
    def sperre(self, name):
        yield True

    def pfad(self, name: str) -> Path:
        if name not in G.AUFTRAG_DATEIEN:
            raise ValueError(name)
        return self.jobdir / name

    def uhr(self) -> float:
        return JETZT

    def geheimnis_in(self, daten) -> bool:
        roh = bytes(daten)
        if self.token and (self.token in roh or base64.b64encode(b"x-access-token:" + self.token) in roh):
            return True
        return any(w in roh for w in self.werte)

    # -------- Sandbox-Schritte der Attrappe
    def ausgabe_standard(self) -> object:
        ausgabe = self.pfad("ausgabe")
        (ausgabe / "status.json").write_bytes(self.status_json)
        if self.sandbox_git.exists():
            ref = f"refs/heads/wamo/{JOB}"
            erg = subprocess.run([GIT, f"--git-dir={self.sandbox_git}", "rev-parse", "--verify", "--quiet", ref], capture_output=True,
                                 env=_git_env())
            if erg.returncode == 0 and erg.stdout.strip().decode() != self.basis:
                git(self.sandbox_git, "bundle", "create", "-q", str(ausgabe / "aenderung.bundle"), ref, f"^{self.basis}")
        return G.SandboxErgebnis(code=0, zeitlimit=False)

    def pruefung_standard(self) -> object:
        self.zaehler += 1
        arbeit = self.tmp / f"arbeit-{self.zaehler}"
        arbeit.mkdir()
        A.auszug(JOB, self.basis, basis_git=self.pfad("basis.git"), bundle=self.pfad("bundle.ein"), ergebnis=self.pfad("ergebnis"),
                 arbeit=arbeit)
        if self.nach_auszug:
            self.nach_auszug(self.pfad("ergebnis"))
        return G.SandboxErgebnis(code=0, zeitlimit=False)

    # -------- Hilfen der Tests
    def arbeit(self, *staende: dict) -> str:
        """Commits der Sandbox auf wamo/<job> über der Basis (im echten Lauf macht das der Agent in der Arbeitskopie)."""
        if not self.sandbox_git.exists():
            subprocess.run([GIT, "init", "-q", "--bare", str(self.sandbox_git)], check=True, env=_git_env())
            (self.sandbox_git / "objects" / "info" / "alternates").write_bytes(
                (self.pfad("basis.git") / "objects").as_posix().encode() + b"\n")
        return importieren(self.sandbox_git, f"refs/heads/wamo/{JOB}", staende, self.basis)

    def git_args(self, befehl: str) -> list[tuple]:
        return [a["args"] for a in self.git_aufrufe if befehl_von(a["args"]) == befehl]


def befehl_von(args: tuple) -> str:
    """Der git-Befehl hinter führenden -c-Einstellungen."""
    i = 0
    while i < len(args) and args[i] == "-c":
        i += 2
    return args[i] if i < len(args) else ""


@pytest.fixture
def att(tmp_path, vorrat):
    ordner, basis = vorrat
    shutil.copytree(ordner, tmp_path / "github")
    return Attrappe(tmp_path, tmp_path / "github", basis)


def starten(att, **anders) -> dict:
    kw = {"job": JOB, "repo": REPO, "art": "umsetzung", "profil": PROFIL, "token_art": "klassisch"}
    kw.update(anders)
    return G.start(att, **kw)


def laufende(att, auftrag: str = "Login-Seite bauen", lauf: str = "fertig", art: str = "umsetzung") -> dict:
    return G.laufende(att, job=JOB, projekt="kern-a1b2c3d4-projekt", art=art, profil=PROFIL, auftrag=auftrag, lauf=lauf)


def bereit(att, aenderungen: dict | None = None) -> dict:
    starten(att)
    att.arbeit(stand(aenderungen if aenderungen is not None else {"src/app.py": ("100644", b"print(2)\n"),
                                                                     "neu.txt": ("100644", b"neu\n"), "alt.txt": None,
                                                                     ".mcp.json": None, "deploy.sh": ("100755", b"echo\n")}))
    erg = laufende(att)
    assert erg["status"] == "bereit", erg
    return erg


def einreichen(att, aenderung: dict, *, bestaetigt=None, kanal=lambda: None, zaehlen=lambda: None, **anders) -> dict:
    eingabe = {"commit_id": aenderung["commit_id"], "tree_id": aenderung["tree_id"],
               "bestaetigt": bestaetigt if bestaetigt is not None else [e["pfad"] for e in aenderung["liste"] if e["klasse"] == "sensibel"]}
    eingabe.update(anders.pop("eingabe", {}))
    kw = {"job": JOB, "profil": PROFIL, "eingabe": eingabe, "token_art": "klassisch", "kanal": kanal, "zaehlen": zaehlen}
    kw.update(anders)
    return G.einreichen(att, **kw)


def mit_pr(att, nummer: int = 7) -> None:
    att.antworten[("GET", f"/repos/{REPO}/pulls?head=beispiel:wamo/{JOB}&state=open&per_page=10")] = antwort(200, [])
    att.antworten[("POST", f"/repos/{REPO}/pulls")] = antwort(201, {"number": nummer, "html_url": f"https://github.com/{REPO}/pull/{nummer}"})


def remote_zweig(att) -> str | None:
    erg = subprocess.run([GIT, f"--git-dir={att.remote / 'beispiel' / 'projekt.git'}", "rev-parse", "--verify", "--quiet",
                          f"refs/heads/wamo/{JOB}"], capture_output=True, env=_git_env())
    return erg.stdout.decode().strip() or None


def abgelehnt(grund: str):
    return pytest.raises(G.GithubAbgelehnt, match=f"^{grund}$")


# ================================================================== Schnittstelle
def test_attrappe_erfuellt_das_protokoll(tmp_path):
    assert isinstance(Attrappe.__new__(Attrappe), G.Werkzeuge)


def test_eigene_repo_ids_wie_im_dispatcher():
    text = (INFRA / "wamo_job_dispatch.py").read_text(encoding="utf-8")
    treffer = re.search(r"^SELF_REPO_IDS = frozenset\(\{([0-9, ]+)\}\)", text, flags=re.M)
    assert treffer and G.SELF_REPO_IDS == frozenset(int(x) for x in treffer.group(1).split(","))


def test_gruende_der_ausnahmen_sind_aus_den_listen():
    """Jeder feste Code im Modul: direkt in GithubAbgelehnt, als Argument grund, ungueltig oder fehler, oder als Rückgabe von repo_lesen."""
    import ast
    baum = ast.parse((INFRA / "wamo_job_github.py").read_text(encoding="utf-8"))
    codes = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Call):
            for arg in [*knoten.args[:1]] if getattr(knoten.func, "id", None) == "GithubAbgelehnt" else []:
                if isinstance(arg, ast.Constant):
                    codes.add(arg.value)
            for kw in knoten.keywords:
                if kw.arg in ("grund", "ungueltig", "fehler") and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
        if isinstance(knoten, ast.FunctionDef) and knoten.name == "repo_lesen":
            codes |= {r.value.value for r in ast.walk(knoten) if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant)}
    kk = G._kernkanal()
    erlaubt = set(kk.GITHUB_GRUENDE) | set(kk.AENDERUNG_GRUENDE) | set(kk.EINREICHEN_GRUENDE)
    assert codes and codes <= erlaubt, codes - erlaubt


def test_import_ohne_nebenwirkung():
    """Nachbarmodule lädt die Logik erst beim ersten Gebrauch; der Modulkörper hat nur Konstanten, Klassen und Funktionen."""
    import ast
    baum = ast.parse((INFRA / "wamo_job_github.py").read_text(encoding="utf-8"))
    for knoten in baum.body:
        assert isinstance(knoten, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef, ast.Expr))
    namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(baum) if isinstance(n, ast.Attribute)}
    assert not namen & {"subprocess", "socket", "urlopen", "HTTPSConnection", "environ", "system", "popen", "Popen"}


# ================================================================== reine Prüfungen
@pytest.mark.parametrize("scopes, ausnahmen, erwartet", [
    (("repo",), (), None), (("public_repo", "read:org"), (), None), ((), (), "token_rechte"), (("repo", "workflow"), (), "token_rechte"),
    (("repo", "workflow"), ("workflow",), None), (("repo", "delete_repo"), ("delete_repo",), "token_rechte"),
    (("repo", "site_admin"), ("site_admin",), "token_rechte"), (("repo", "admin:enterprise"), ("admin:enterprise",), "token_rechte"),
    (("repo", "ganz_neu"), (), "token_rechte"), (("repo", "Repo"), (), "token_rechte"), (("repo",) * 31, (), "token_rechte"),
])
def test_scope_regel(scopes, ausnahmen, erwartet):
    assert G.scope_grund(scopes, ausnahmen) == erwartet


@pytest.mark.parametrize("wert", [["delete_repo"], ["workflow", "workflow"], "workflow", [1], ["admin:neu"]])
def test_ausnahmen_nur_aus_der_liste(wert):
    with abgelehnt("token_rechte"):
        G.ausnahmen_pruefen(wert)


def test_ausnahmen_gueltig():
    assert G.ausnahmen_pruefen(["workflow", "gist"]) == ("gist", "workflow")
    assert G.ausnahmen_pruefen(None) == ()


@pytest.mark.parametrize("ablauf, erwartet", [
    (None, "token_abgelaufen"), ("", "token_abgelaufen"), ("morgen", "token_abgelaufen"), ("2026-11-18 11:59:59 UTC", "token_abgelaufen"),
    ("2026-11-18 12:00:01 UTC", None), ("2026-11-18 14:00:01 +0100", None), ("2026-11-18 12:30:00 +0100", "token_abgelaufen"),
    ((datetime.fromtimestamp(JETZT, timezone.utc) + timedelta(days=366)).strftime("%Y-%m-%d %H:%M:%S UTC"), None),
    ((datetime.fromtimestamp(JETZT, timezone.utc) + timedelta(days=366, seconds=1)).strftime("%Y-%m-%d %H:%M:%S UTC"),
     "token_abgelaufen"),
    ("2026-13-40 12:00:00 UTC", "token_abgelaufen"),
])
def test_ablaufpflicht(ablauf, erwartet):
    assert G.ablauf_grund(ablauf, JETZT) == erwartet


def test_token_art_und_kopfzeile():
    gut = {"github-authentication-token-expiration": ABLAUF}
    assert G.token_grund({**gut, "x-oauth-scopes": "repo"}, "klassisch", (), JETZT) is None
    assert G.token_grund(gut, "klassisch", (), JETZT) == "token_rechte"  # klassisch ohne Kopfzeile: nicht prüfbar
    assert G.token_grund(gut, "fein", (), JETZT) is None
    assert G.token_grund({**gut, "x-oauth-scopes": ""}, "fein", (), JETZT) is None
    assert G.token_grund({**gut, "x-oauth-scopes": "repo"}, "fein", (), JETZT) == "token_rechte"  # Art passt nicht zum Token
    assert G.token_grund({**gut, "x-oauth-scopes": "repo"}, "oauth", (), JETZT) == "token_rechte"


@pytest.mark.parametrize("name, gueltig", [
    ("main", True), ("release/2026.11", True), ("dev_1-x", True), ("-x", False), ("a..b", False), (".versteckt", False),
    ("x.lock", False), ("a//b", False), ("a/", False), ("a b", False), ("a:b", False), ("x" * 101, False), ("main.", False), (5, False),
])
def test_standardzweig_geprueft(name, gueltig):
    assert G.zweig_gueltig(name) is gueltig


@pytest.mark.parametrize("anders, erwartet", [
    ({"full_name": "beispiel/umbenannt"}, "repo_nicht_erreichbar"),
    ({"id": 1425139508}, "eigenes_repo"),
    ({"full_name": "beispiel/projekt", "fork": True, "parent": {"id": 1425139508, "full_name": "x/anders"},
      "source": {"id": 1425139508, "full_name": "x/anders"}}, "eigenes_repo"),
    ({"fork": True, "parent": {"id": 9, "full_name": "Wamocon/w.a.i.s"}, "source": {"id": 9, "full_name": "Wamocon/w.a.i.s"}},
     "eigenes_repo"),
    ({"fork": True, "parent": {"id": 9, "full_name": "x/y"}, "source": {"id": 9, "full_name": "Wamocon/WAMO"}}, "eigenes_repo"),
    ({"template_repository": {"id": 1425139508, "full_name": "x/vorlage"}}, "eigenes_repo"),
    ({"template_repository": "kaputt"}, "eigenes_repo"),
    ({"fork": True}, "eigenes_repo"),  # Fork ohne lesbaren Ursprung: fail closed
    ({"fork": None}, "eigenes_repo"),
    ({"default_branch": "-x"}, "repo_nicht_erreichbar"),
    ({"default_branch": "a..b"}, "repo_nicht_erreichbar"),
    ({"size": "100"}, "repo_nicht_erreichbar"),
    ({"private": None}, "repo_nicht_erreichbar"),
    ({"permissions": None}, "repo_nicht_erreichbar"),
])
def test_repo_antwort(anders, erwartet):
    assert G.repo_lesen(repo_daten(**anders), REPO) == erwartet


def test_repo_antwort_gut_und_fork_fremd():
    daten = G.repo_lesen(repo_daten(full_name="Beispiel/Projekt"), REPO)
    assert daten.repo_id == REPO_ID and daten.schreiben and daten.lesen and daten.standardzweig == "main"
    fork = G.repo_lesen(repo_daten(fork=True, parent={"id": 1, "full_name": "a/b"}, source={"id": 1, "full_name": "a/b"}), REPO)
    assert isinstance(fork, G.RepoDaten)


@pytest.mark.parametrize("text, erwartet", [
    ("Login-Seite bauen", "Login-Seite bauen"),
    ("Fixes #12: Login reparieren", "12 Login reparieren"),
    ("closes #3 und resolved #4, fix it", "3 und 4, it"),
    ("Siehe https://evil.example/x?y=1 und www.evil.example bitte", "Siehe und bitte"),
    ("@niko bitte prüfen", "niko bitte pruefen"),
    ("Größe ändern: Über/Unter", "Groesse aendern Ueber Unter"),
    ("Zeile eins\nZeile zwei", "Zeile eins"),
    ("", "Änderung aus W.A.I.S."),
    ("###", "Änderung aus W.A.I.S."),
    ("fix", "Änderung aus W.A.I.S."),
    (None, "Änderung aus W.A.I.S."),
    ("`rm -rf /` <script>", "rm -rf script"),
])
def test_titel_allowlist(text, erwartet):
    titel = G.titel_bereinigen(text)
    assert titel == erwartet
    assert not re.search(r"[@#/:`<>]", titel)


def test_titel_hoechstens_72_zeichen_an_wortgrenze():
    titel = G.titel_bereinigen("Wort " * 30)
    assert len(titel) <= 72 and titel.endswith("Wort")
    assert len(G.titel_bereinigen("x" * 100)) == 72


def test_pr_text_vorlage():
    pfade = [f"src/datei{i}@x.py" for i in range(60)]
    text = G.pr_text(JOB, "umsetzung", LOGIN, 75, 10, 3, pfade[:50])
    assert f"Entwicklungsauftrag {JOB}" in text and "- Art: umsetzung" in text and f"- Konto: {LOGIN}" in text
    assert "- Dateien: 75, Zeilen: +10 -3" in text and "und 25 weitere" in text and "Nicht gemergt, bitte prüfen." in text
    assert "@" not in text and "#" not in text
    assert text.count("src/datei") == 50


def test_commit_objekt_aus_vorlage():
    nachricht = G.commit_nachricht("Titel", JOB, "umsetzung", LOGIN, PROFIL)
    objekt = G.commit_objekt("1" * 40, "2" * 40, LOGIN, KONTO_ID, 1800000000, nachricht)
    assert objekt.startswith(b"tree " + b"1" * 40 + b"\nparent " + b"2" * 40 + b"\n")
    assert f"author {LOGIN} <{KONTO_ID}+{LOGIN}@users.noreply.github.com> 1800000000 +0000\n".encode() in objekt
    assert b"committer W.A.I.S. <wais@wamocon.invalid> 1800000000 +0000\n" in objekt
    for zeile in (f"WAIS-Auftrag: {JOB}", "WAIS-Art: umsetzung", f"WAIS-Beauftragt-von: {LOGIN}", f"WAIS-Profil: {PROFIL}"):
        assert zeile.encode() in nachricht


C = "c" * 40


@pytest.mark.parametrize("ausgabe, ok", [
    (f"To https://github.com/{REPO}.git\n*\t{C}:refs/heads/wamo/{JOB}\t[new branch]\nDone\n", True),
    (f"=\t{C}:refs/heads/wamo/{JOB}\t[up to date]\nDone\n", True),
    (f"+\t{C}:refs/heads/wamo/{JOB}\tforced update\nDone\n", False),
    (f"!\t{C}:refs/heads/wamo/{JOB}\t[rejected]\nDone\n", False),
    (f" \t{C}:refs/heads/wamo/{JOB}\tabc..def\nDone\n", False),
    (f"*\t{C}:refs/heads/main\t[new branch]\nDone\n", False),
    (f"*\t{C}:refs/heads/wamo/{JOB}\t[new branch]\n*\t{C}:refs/tags/x\t[new tag]\nDone\n", False),
    ("Done\n", False),
])
def test_push_ausgabe_genau_eine_zeile(ausgabe, ok):
    assert G.push_ausgabe_ok(ausgabe.encode(), C, JOB) is ok


@pytest.mark.parametrize("ausgabe, erwartet", [
    ("", None), (f"{C}\trefs/heads/wamo/{JOB}\n", C), (f"{C}\trefs/heads/wamo/{JOB}x\n", False),
    (f"{C}\trefs/heads/wamo/{JOB}\n{C}\trefs/heads/main\n", False), ("kaputt\n", False),
])
def test_ls_remote(ausgabe, erwartet):
    assert G.ls_remote_lesen(ausgabe.encode(), JOB) == erwartet


# ================================================================== Start
@mit_git
def test_start_klont_bereinigt_und_schreibt_github_json(att):
    ereignis = starten(att)
    assert ereignis == {"repo": REPO, "konto": LOGIN, "basis": att.basis, "standardzweig": "main", "privat": True, "schreiben": True}
    basis_git = att.pfad("basis.git")
    assert att.git_args("clone") == [("clone", "--bare", "--single-branch", "--branch=main", "--no-tags", "--template=", "--",
                                      f"https://github.com/{REPO}.git", str(basis_git))]
    assert [a["netz"] for a in att.git_aufrufe if befehl_von(a["args"]) == "clone"] == [True]
    assert all(not a["netz"] for a in att.git_aufrufe if befehl_von(a["args"]) != "clone")
    assert not (basis_git / "hooks").exists() and not (basis_git / "info").exists() and not (basis_git / "logs").exists()
    konfig = (basis_git / "config").read_text()
    assert f"url = https://github.com/{REPO}.git" in konfig and "hooksPath" not in konfig and "credential" not in konfig
    daten = json.loads(att.pfad("github.json").read_text())
    assert daten == {"v": 1, "repo": REPO, "repo_id": REPO_ID, "login": LOGIN, "konto_id": KONTO_ID, "basis": att.basis,
                     "standardzweig": "main", "privat": True, "schreiben": True, "geklont_at": int(JETZT)}
    assert [(m, p) for m, p, _ in att.http_aufrufe] == [("GET", "/user"), ("GET", f"/repos/{REPO}")]


@mit_git
def test_start_lesende_art_oder_ohne_push(att):
    assert starten(att, art="review")["schreiben"] is False
    att2 = att
    att2.antworten[("GET", f"/repos/{REPO}")] = antwort(200, repo_daten(permissions={"pull": True, "push": False}))
    assert starten(att2)["schreiben"] is False


@pytest.mark.parametrize("user, grund", [
    (antwort(401), "token_ungueltig"),
    (antwort(403), "token_ungueltig"),
    (antwort(502), "klon_fehler"),
    (antwort(200, {"login": LOGIN, "id": KONTO_ID, "type": "Organization"}, {"x-oauth-scopes": "repo"}), "token_ungueltig"),
    (antwort(200, {"login": "bös", "id": KONTO_ID, "type": "User"}), "token_ungueltig"),
    (user_antwort(scopes="repo, workflow"), "token_rechte"),
    (user_antwort(scopes="repo, delete_repo"), "token_rechte"),
    (user_antwort(scopes=None), "token_rechte"),
    (user_antwort(ablauf=None), "token_abgelaufen"),
    (user_antwort(ablauf="2026-11-01 00:00:00 UTC"), "token_abgelaufen"),
    (user_antwort(ablauf="2028-01-01 00:00:00 UTC"), "token_abgelaufen"),
])
def test_start_token_pruefung(att, user, grund):
    att.antworten[("GET", "/user")] = user
    with abgelehnt(grund):
        starten(att)
    assert not att.git_aufrufe and not att.pfad("github.json").exists()


@mit_git
def test_start_ausnahmen_der_person(att):
    att.antworten[("GET", "/user")] = user_antwort(scopes="repo, workflow")
    assert starten(att, scopes_ausnahmen=["workflow"])["repo"] == REPO
    with abgelehnt("token_rechte"):
        starten(att, scopes_ausnahmen=["delete_repo"])


def test_start_fein_granular_ohne_scopes(att):
    att.antworten[("GET", "/user")] = user_antwort(scopes=None)
    att.antworten[("GET", f"/repos/{REPO}")] = antwort(404)
    with abgelehnt("repo_nicht_erreichbar"):  # die Token-Prüfung ist bestanden, das Repo ist nicht lesbar
        starten(att, token_art="fein")


@pytest.mark.parametrize("repo", ["Wamocon/w.a.i.s", "irgendwer/WAMO", "x/w-a-i-s.git", "x/wais"])
def test_start_eigenes_repo_vor_jedem_aufruf(att, repo):
    with abgelehnt("eigenes_repo"):
        starten(att, repo=repo)
    assert not att.http_aufrufe and not att.git_aufrufe


@pytest.mark.parametrize("anders, grund", [
    ({"id": 1425139508}, "eigenes_repo"),
    ({"fork": True, "parent": {"id": 1425139508, "full_name": "a/b"}, "source": {"id": 1425139508, "full_name": "a/b"}}, "eigenes_repo"),
    ({"template_repository": {"id": 77, "full_name": "Wamocon/w.a.i.s"}}, "eigenes_repo"),
    ({"full_name": "beispiel/neu"}, "repo_nicht_erreichbar"),
    ({"permissions": {"pull": False, "push": False}}, "repo_nicht_erreichbar"),
    ({"default_branch": "--upload-pack=x"}, "repo_nicht_erreichbar"),
])
def test_start_repo_pruefung(att, anders, grund):
    att.antworten[("GET", f"/repos/{REPO}")] = antwort(200, repo_daten(**anders))
    with abgelehnt(grund):
        starten(att)
    assert not att.git_aufrufe


@pytest.mark.parametrize("status, grund", [(404, "repo_nicht_erreichbar"), (301, "repo_nicht_erreichbar"), (503, "klon_fehler")])
def test_start_repo_status(att, status, grund):
    att.antworten[("GET", f"/repos/{REPO}")] = antwort(status)
    with abgelehnt(grund):
        starten(att)


def test_start_groesse_in_kb(att, monkeypatch):
    monkeypatch.setattr(G, "_git", lambda *a, **k: (_ for _ in ()).throw(G.GithubAbgelehnt("klon_fehler")))
    att.antworten[("GET", f"/repos/{REPO}")] = antwort(200, repo_daten(size=100 * 1024 + 1))
    with abgelehnt("repo_zu_gross"):
        starten(att, max_klon_mb=100)
    att.antworten[("GET", f"/repos/{REPO}")] = antwort(200, repo_daten(size=100 * 1024))
    with abgelehnt("klon_fehler"):  # genau an der Grenze geht es weiter bis zum Klon
        starten(att, max_klon_mb=100)
    with abgelehnt("repo_zu_gross"):
        starten(att, max_klon_mb=99)


def test_start_ohne_token(att):
    att.token = None
    with abgelehnt("klon_fehler"):
        starten(att)


@mit_git
@pytest.mark.parametrize("rest", ["roh", "base64", "dateiname"])
def test_start_findet_gepflanzten_token_rest(att, rest):
    def pflanzen(ziel: Path):
        if rest == "roh":
            (ziel / "packed-refs").write_bytes(b"# " + TOKEN + b"\n")
        elif rest == "base64":
            (ziel / "refs" / "heads" / "notiz").write_bytes(base64.b64encode(b"x-access-token:" + TOKEN) + b"\n")
        else:
            (ziel / "refs" / TOKEN.decode()).write_bytes(b"x")
    att.nach_klon = pflanzen
    with abgelehnt("bereinigung"):
        starten(att)
    assert not att.pfad("basis.git").exists() and not att.pfad("github.json").exists()
    assert not any(TOKEN.decode() in z for z in att.logs)


@mit_git
def test_start_alternates_im_klon(att):
    att.nach_klon = lambda ziel: (ziel / "objects" / "info").mkdir(exist_ok=True) or \
        (ziel / "objects" / "info" / "alternates").write_bytes(b"/etc\n")
    with abgelehnt("bereinigung"):
        starten(att)
    assert not att.pfad("basis.git").exists()


@mit_git
def test_start_hooks_im_klon_werden_entfernt(att):
    def pflanzen(ziel: Path):
        (ziel / "hooks").mkdir(exist_ok=True)
        (ziel / "hooks" / "post-checkout").write_bytes(b"#!/bin/sh\necho x\n")
        with open(ziel / "config", "ab") as f:
            f.write(b"[core]\n\tfsmonitor = /bin/boese\n")
    att.nach_klon = pflanzen
    starten(att)
    assert not (att.pfad("basis.git") / "hooks").exists()
    assert b"fsmonitor" not in (att.pfad("basis.git") / "config").read_bytes()


@mit_git
def test_start_klon_scheitert(att):
    G.entfernen(att.remote / "beispiel")
    with abgelehnt("klon_fehler"):
        starten(att)
    assert not att.pfad("basis.git").exists()


def test_start_nie_nach_dem_einreichen(att):
    att.pfad("aenderung.json").write_text(json.dumps({"job": JOB, "status": "eingereicht"}))
    with abgelehnt("schon_eingereicht"):
        starten(att)
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == "eingereicht"


# ================================================================== Laufende
@mit_git
def test_laufende_baut_einen_commit_aus_den_bytes(att):
    erg = bereit(att)
    aus = att.pfad("aus.git")
    commit = erg["commit_id"]
    assert git(aus, "rev-parse", G.KANDIDAT_REF).decode().strip() == commit
    roh = git(aus, "cat-file", "commit", commit).decode()
    assert f"parent {att.basis}\n" in roh and f"tree {erg['tree_id']}\n" in roh
    assert f"author {LOGIN} <{KONTO_ID}+{LOGIN}@users.noreply.github.com> {int(JETZT)} +0000" in roh
    assert f"committer W.A.I.S. <wais@wamocon.invalid> {int(JETZT)} +0000" in roh
    assert roh.endswith(f"WAIS-Profil: {PROFIL}\n") and "Login-Seite bauen\n" in roh
    baum = git(aus, "ls-tree", "-r", "--name-only", commit).decode().split("\n")
    assert ".mcp.json" in baum and ".claude/settings.json" in baum  # entschärfte Pfade kommen aus der Basis
    assert "alt.txt" not in baum and "neu.txt" in baum
    assert git(aus, "cat-file", "blob", f"{commit}:src/app.py") == b"print(2)\n"
    assert git(aus, "ls-tree", commit, "deploy.sh").startswith(b"100755 blob ")
    assert erg["dateien"] == 4 and erg["plus"] >= 2 and erg["minus"] >= 2 and erg["zweig"] == f"wamo/{JOB}"
    assert erg["liste"][0] == {"pfad": "deploy.sh", "art": "neu", "klasse": "sensibel", "plus": 1, "minus": 0}
    gespeichert = json.loads(att.pfad("aenderung.json").read_text())
    assert gespeichert == erg and set(erg) == {"job", "status", "commit_id", "tree_id", "basis", "zweig", "dateien", "plus", "minus",
                                              "liste", "nicht_gelistet", "gruende", "ungesichert", "lauf", "titel", "pr", "adresse"}
    e = json.loads(att.pfad("einreichen.json").read_text())
    assert e["markiert"] == ["deploy.sh"] and e["commit_id"] == commit and e["profil"] == PROFIL
    assert att.sandbox_aufrufe == ["ausgabe", "pruefung"]
    assert not att.pfad("ausgabe").exists()
    # der Commit entsteht nur im eigenen aus.git; keine Objekte der Sandbox: die Sandbox kennt den Commit nicht
    erg_sandbox = subprocess.run([GIT, f"--git-dir={att.sandbox_git}", "cat-file", "-e", commit], capture_output=True, env=_git_env())
    assert erg_sandbox.returncode != 0


@mit_git
def test_laufende_gleiche_uhr_gleicher_commit(att):
    erste = bereit(att)
    zweite = laufende(att)
    assert zweite["status"] == "bereit" and zweite["commit_id"] == erste["commit_id"]


@mit_git
def test_laufende_nur_ein_commit_auch_bei_mehreren_der_sandbox(att):
    starten(att)
    att.arbeit(stand({"geheim.txt": ("100644", b"zwischenstand\n")}), stand({"neu.txt": ("100644", b"neu\n")}))
    erg = laufende(att)
    assert erg["status"] == "bereit" and [e["pfad"] for e in erg["liste"]] == ["neu.txt"]
    assert git(att.pfad("aus.git"), "rev-list", "--count", f"{att.basis}..{erg['commit_id']}").strip() == b"1"


@mit_git
@pytest.mark.parametrize("aenderung, grund", [
    ({".github/workflows/x.yml": ("100644", b"on: push\n")}, "pfad_gesperrt"),
    ({".claude/settings.json": ("100644", b'{"hooks": 1}\n')}, "pfad_gesperrt"),
    ({"src/Readme.md": ("100644", b"x"), "src/README.md": ("100644", b"y")}, "pfad_gesperrt"),
    ({"link": ("120000", b"../../etc/passwd")}, "symlink"),
    ({"conf.py": ("100644", b"KEY = 'sk-ant-api03-" + b"A" * 40 + b"'\n")}, "geheimnis"),
])
def test_laufende_regeln_sperren(att, aenderung, grund):
    starten(att)
    att.arbeit(stand(aenderung))
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and grund in erg["gruende"] and erg["commit_id"] is None
    assert not att.pfad("einreichen.json").exists() and not att.pfad("aus.git").exists()
    assert erg["liste"] and erg["liste"][0]["klasse"] == "sensibel"


@mit_git
def test_laufende_exakter_wert_des_laufs(att):
    starten(att)
    att.werte = [b"claude-zugang-des-laufs-123"]
    att.arbeit(stand({"notiz.txt": ("100644", b"x claude-zugang-des-laufs-123 y")}))
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["geheimnis"]


@mit_git
def test_laufende_ohne_commits(att):
    starten(att)
    att.status_json = b"3\n"
    erg = laufende(att)
    assert erg["status"] == "keine" and erg["ungesichert"] == 3 and att.sandbox_aufrufe == ["ausgabe"]


@mit_git
def test_laufende_lesende_art(att):
    starten(att, art="review")
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))
    erg = laufende(att, art="review")
    assert erg["status"] == "nur_lesen" and att.sandbox_aufrufe == []


@mit_git
@pytest.mark.parametrize("inhalt", [b"", b"-1\n", b"3 4\n", b"x", b"12345678\n", b"3\n\n"])
def test_laufende_status_json_ungueltig(att, inhalt):
    starten(att)
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))
    att.status_json = inhalt
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"]


def _links_moeglich(tmp_path: Path) -> bool:
    try:
        (tmp_path / "linkprobe").symlink_to(tmp_path)
        return True
    except OSError:
        return False


@mit_git
def test_laufende_bundle_als_link(att, tmp_path):
    if not _links_moeglich(tmp_path):
        pytest.skip("Links nicht erlaubt")
    starten(att)
    geheim = tmp_path / "geheim"
    geheim.write_bytes(b"# v2 git bundle\n")

    def ausgabe(self):
        (self.pfad("ausgabe") / "status.json").write_bytes(b"0\n")
        (self.pfad("ausgabe") / "aenderung.bundle").symlink_to(geheim)
        return G.SandboxErgebnis(code=0, zeitlimit=False)
    att.schritte["ausgabe"] = ausgabe
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["bundle_ungueltig"]
    assert not att.pfad("bundle.ein").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="nur unter Linux")
@mit_git
def test_laufende_bundle_als_fifo(att):
    starten(att)

    def ausgabe(self):
        (self.pfad("ausgabe") / "status.json").write_bytes(b"0\n")
        os.mkfifo(self.pfad("ausgabe") / "aenderung.bundle")
        return G.SandboxErgebnis(code=0, zeitlimit=False)
    att.schritte["ausgabe"] = ausgabe
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["bundle_ungueltig"]


def test_bundle_uebernehmen_grenze(tmp_path):
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    quelle.write_bytes(b"x" * 10)
    assert G.bundle_uebernehmen(quelle, ziel, limit=10) and ziel.read_bytes() == b"x" * 10
    with pytest.raises(OSError):
        G.bundle_uebernehmen(quelle, tmp_path / "z2", limit=9)
    assert not (tmp_path / "z2").exists()
    assert G.bundle_uebernehmen(tmp_path / "fehlt", ziel) is False


@mit_git
def test_laufende_schritt_scheitert(att):
    starten(att)
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))
    att.schritte["pruefung"] = lambda self: G.SandboxErgebnis(code=2, zeitlimit=False)
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"]


@mit_git
def test_laufende_auszug_meldet_fremde_basis(att):
    starten(att)
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))

    def pruefung(self):
        (self.pfad("ergebnis") / "liste.json").write_text(json.dumps({"v": 1, "status": "fehler", "grund": "basis_fehlt"}))
        return G.SandboxErgebnis(code=0, zeitlimit=False)
    att.schritte["pruefung"] = pruefung
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["basis_fehlt"]


@mit_git
def test_laufende_auszug_luegt_ueber_die_basis(att):
    """Der Auszug meldet README.md als neu, obwohl sie in der Basis steht: der Abgleich mit dem eigenen basis.git sperrt."""
    starten(att)
    att.arbeit(stand({"README.md": ("100644", b"anders\n")}))

    def luege(ergebnis: Path):
        liste = json.loads((ergebnis / "liste.json").read_text())
        e = liste["eintraege"][0]
        e.update(art="neu", alt_modus="000000", alt_oid="0" * 40)
        (ergebnis / "liste.json").write_text(json.dumps(liste))
    att.nach_auszug = luege
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"]


@mit_git
def test_laufende_auszug_vertauscht_inhalt(att):
    starten(att)
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))
    att.nach_auszug = lambda ergebnis: (ergebnis / "dateien" / "0").write_bytes(b"bos\n")
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"]


@mit_git
@pytest.mark.parametrize("zustand", ["einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen"])
def test_laufende_ueberschreibt_spaete_zustaende_nie(att, zustand):
    starten(att)
    att.pfad("aenderung.json").write_text(json.dumps({"job": JOB, "status": zustand, "pr": 7}))
    erg = laufende(att)
    assert erg["status"] == zustand and att.sandbox_aufrufe == []
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == zustand


def test_laufende_ohne_github_json(att):
    with abgelehnt("pruefung_fehler"):
        laufende(att)


# ================================================================== Einreichen
@mit_git
def test_einreichen_pusht_genau_den_zweig_und_oeffnet_den_pr(att):
    erg = bereit(att)
    mit_pr(att)
    gezaehlt = []
    ergebnis = einreichen(att, erg, zaehlen=lambda: gezaehlt.append(1))
    assert ergebnis == {"job": JOB, "zweig": f"wamo/{JOB}", "pr": 7, "adresse": f"https://github.com/{REPO}/pull/7"}
    assert remote_zweig(att) == erg["commit_id"] and gezaehlt == [1]
    pushes = att.git_args("push")
    assert pushes == [("-c", "push.negotiate=true", "push", "--no-verify", "--no-follow-tags", "--porcelain", "--",
                       f"https://github.com/{REPO}.git", f"{erg['commit_id']}:refs/heads/wamo/{JOB}")]
    assert not any(a.startswith("+") or a in ("--force", "-f", "--tags", "--mirror", "--all") for a in pushes[0])
    assert {befehl_von(a["args"]) for a in att.git_aufrufe if a["netz"]} == {"clone", "ls-remote", "push"}
    post = [d for m, p, d in att.http_aufrufe if m == "POST"]
    assert post == [{"title": "W.A.I.S.: Login-Seite bauen", "head": f"wamo/{JOB}", "base": "main", "body": post[0]["body"],
                     "draft": True, "maintainer_can_modify": False}]
    assert "@" not in post[0]["body"] and "#" not in post[0]["body"] and "deploy.sh" in post[0]["body"]
    gespeichert = json.loads(att.pfad("aenderung.json").read_text())
    assert gespeichert["status"] == "eingereicht" and gespeichert["pr"] == 7
    # das Token steht nie in einem Argument, einer Eingabe, einem Protokoll oder einer Datei des Auftrags
    for a in att.git_aufrufe:
        assert not any(TOKEN.decode() in x for x in a["args"]) and TOKEN not in (a["eingabe"] or b"")
    assert not any(TOKEN.decode() in z for z in att.logs)
    for p in att.jobdir.rglob("*"):
        if p.is_file() and not p.is_symlink():
            assert TOKEN not in p.read_bytes(), p


@mit_git
def test_einreichen_zweimal_ist_zustand(att):
    erg = bereit(att)
    mit_pr(att)
    einreichen(att, erg)
    with abgelehnt("zustand"):
        einreichen(att, erg)


@mit_git
def test_einreichen_fehler_vor_dem_netz(att):
    erg = bereit(att)
    mit_pr(att)
    with abgelehnt("veraltet"):
        einreichen(att, {**erg, "commit_id": "1" * 40})
    with abgelehnt("veraltet"):
        einreichen(att, {**erg, "tree_id": "1" * 40})
    with abgelehnt("bestaetigung"):
        einreichen(att, erg, bestaetigt=[])
    with abgelehnt("bestaetigung"):
        einreichen(att, erg, eingabe={"unbekannt": 1})
    with abgelehnt("zustand"):
        einreichen(att, erg, profil="ffffffff")
    with abgelehnt("token_rechte"):
        einreichen(att, erg, eingabe={"scopes_ausnahmen": ["site_admin"]})
    assert len(att.http_aufrufe) == 2 and not att.git_args("push") and not att.git_args("ls-remote")  # nur die zwei des Starts


@mit_git
def test_einreichen_kandidat_im_repo_ersetzt(att):
    erg = bereit(att)
    git(att.pfad("aus.git"), "update-ref", G.KANDIDAT_REF, att.basis)
    with abgelehnt("veraltet"):
        einreichen(att, erg)


@mit_git
@pytest.mark.parametrize("user, grund", [
    (user_antwort(konto=999), "konto"),
    (user_antwort(scopes="repo, gist"), "token_rechte"),
    (user_antwort(ablauf="2026-11-01 00:00:00 UTC"), "token_abgelaufen"),
    (antwort(401), "token_abgelaufen"),
    (antwort(500), "github_fehler"),
])
def test_einreichen_token_erneut_geprueft(att, user, grund):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("GET", "/user")] = user
    with abgelehnt(grund):
        einreichen(att, erg)
    assert not att.git_args("push") and remote_zweig(att) is None
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == "bereit"


@mit_git
def test_einreichen_ausnahme_von_jetzt(att):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("GET", "/user")] = user_antwort(scopes="repo, gist")
    assert einreichen(att, erg, eingabe={"scopes_ausnahmen": ["gist"]})["pr"] == 7


@mit_git
@pytest.mark.parametrize("repo_antwort, grund", [
    (antwort(200, repo_daten(id=REPO_ID + 1)), "repo_geaendert"),
    (antwort(200, repo_daten(full_name="beispiel/anders")), "repo_geaendert"),
    (antwort(404), "repo_geaendert"),
    (antwort(200, repo_daten(fork=True, parent={"id": 1425139508, "full_name": "a/b"}, source={"id": 1, "full_name": "a/b"})),
     "repo_geaendert"),
    (antwort(200, repo_daten(permissions={"pull": True, "push": False})), "keine_schreibrechte"),
])
def test_einreichen_repo_erneut_geprueft(att, repo_antwort, grund):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("GET", f"/repos/{REPO}")] = repo_antwort
    with abgelehnt(grund):
        einreichen(att, erg)
    assert not att.git_args("push")


@mit_git
def test_laufende_sperrt_github_token_nach_muster(att):
    starten(att)
    att.arbeit(stand({"notiz.txt": ("100644", b"token=ghp_" + b"Z" * 36 + b"\n")}))  # ein fremdes Token: nur das Muster findet es
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["geheimnis"]


@mit_git
def test_einreichen_geheimnis_nur_beim_einreichen_erkennbar(att):
    starten(att)
    att.arbeit(stand({"notiz.txt": ("100644", b"wert=nur-beim-einreichen-bekannt\n")}))
    erg = laufende(att)
    assert erg["status"] == "bereit"
    mit_pr(att)
    att.werte = [b"nur-beim-einreichen-bekannt"]  # etwa das GitHub-Token in einer Form ohne Muster
    with abgelehnt("geheimnis"):
        einreichen(att, erg, bestaetigt=[])
    assert not att.git_args("push") and not att.git_args("ls-remote")


@mit_git
def test_einreichen_ergebnis_nachtraeglich_veraendert(att):
    erg = bereit(att)
    mit_pr(att)
    (att.pfad("ergebnis") / "dateien" / "0").write_bytes(b"anders")
    with abgelehnt("veraltet"):
        einreichen(att, erg)


@mit_git
def test_einreichen_zweig_belegt(att):
    erg = bereit(att)
    mit_pr(att)
    git(att.remote / "beispiel" / "projekt.git", "update-ref", f"refs/heads/wamo/{JOB}", att.basis)
    with abgelehnt("zweig_belegt"):
        einreichen(att, erg)
    assert remote_zweig(att) == att.basis and not att.git_args("push")


@mit_git
def test_einreichen_grenze(att):
    erg = bereit(att)
    mit_pr(att)
    with abgelehnt("grenze_einreichen"):
        einreichen(att, erg, zaehlen=lambda: "grenze_einreichen")
    assert not att.git_args("push") and json.loads(att.pfad("aenderung.json").read_text())["status"] == "bereit"


@mit_git
@pytest.mark.parametrize("notaus_bei, zustand, gepusht", [(1, "bereit", False), (2, "bereit", False), (3, "branch_gepusht", True)])
def test_einreichen_notaus_in_jeder_phase(att, notaus_bei, zustand, gepusht):
    erg = bereit(att)
    mit_pr(att)
    aufrufe = []

    def kanal():
        aufrufe.append(1)
        return "notaus" if len(aufrufe) == notaus_bei else None
    with abgelehnt("notaus"):
        einreichen(att, erg, kanal=kanal)
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == zustand
    assert (remote_zweig(att) == erg["commit_id"]) is gepusht
    assert not [m for m, _p, _d in att.http_aufrufe if m == "POST"]


@mit_git
def test_einreichen_pr_scheitert_und_wird_nachgeholt(att):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("POST", f"/repos/{REPO}/pulls")] = [antwort(500), antwort(201, {"number": 8, "html_url": f"https://github.com/{REPO}/pull/8"})]
    with abgelehnt("github_fehler"):
        einreichen(att, erg)
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == "branch_gepusht"
    gezaehlt = []
    assert einreichen(att, erg, zaehlen=lambda: gezaehlt.append(1))["pr"] == 8
    assert len(att.git_args("push")) == 1 and gezaehlt == []  # das Nachholen pusht nicht erneut und zählt nicht


@mit_git
@pytest.mark.parametrize("gepusht", [True, False])
def test_einreichen_nach_absturz_klaert_ls_remote(att, gepusht):
    erg = bereit(att)
    mit_pr(att)
    if gepusht:
        aus = att.pfad("aus.git")
        subprocess.run([GIT, f"--git-dir={aus}", "push", "-q", str(att.remote / "beispiel" / "projekt.git"),
                        f"{erg['commit_id']}:refs/heads/wamo/{JOB}"], check=True, env=_git_env(), capture_output=True)
    daten = json.loads(att.pfad("aenderung.json").read_text())
    att.pfad("aenderung.json").write_text(json.dumps({**daten, "status": "einreichen_laeuft"}))
    assert einreichen(att, erg)["pr"] == 7
    assert len(att.git_args("push")) == (0 if gepusht else 1)


@mit_git
def test_einreichen_pr_wiederverwenden_nur_mit_gleichem_kopf(att):
    erg = bereit(att)
    mit_pr(att, nummer=9)
    fremd = {"number": 5, "html_url": f"https://github.com/{REPO}/pull/5", "state": "open",
             "head": {"sha": "1" * 40, "ref": f"wamo/{JOB}", "repo": {"id": REPO_ID}}}
    gleich = {"number": 6, "html_url": f"https://github.com/{REPO}/pull/6", "state": "open",
              "head": {"sha": erg["commit_id"], "ref": f"wamo/{JOB}", "repo": {"id": REPO_ID}}}
    anderes_repo = {**gleich, "number": 4, "html_url": f"https://github.com/{REPO}/pull/4",
                    "head": {**gleich["head"], "repo": {"id": 1}}}
    att.antworten[("GET", f"/repos/{REPO}/pulls?head=beispiel:wamo/{JOB}&state=open&per_page=10")] = antwort(200, [fremd, anderes_repo, gleich])
    assert einreichen(att, erg)["pr"] == 6
    assert not [m for m, _p, _d in att.http_aufrufe if m == "POST"]


@mit_git
def test_einreichen_ohne_entwurf_bei_422(att):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("POST", f"/repos/{REPO}/pulls")] = lambda daten: antwort(422) if daten.get("draft") else \
        antwort(201, {"number": 3, "html_url": f"https://github.com/{REPO}/pull/3"})
    assert einreichen(att, erg)["pr"] == 3


@mit_git
@pytest.mark.parametrize("adresse", ["https://evil.example/pull/7", f"https://github.com/{REPO}/pull/8", "javascript:alert(1)"])
def test_einreichen_adresse_des_pr_geprueft(att, adresse):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("POST", f"/repos/{REPO}/pulls")] = antwort(201, {"number": 7, "html_url": adresse})
    with abgelehnt("github_fehler"):
        einreichen(att, erg)
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == "branch_gepusht"


@mit_git
def test_einreichen_push_verweigert(att):
    erg = bereit(att)
    mit_pr(att)
    original = att.git

    def git_403(args, **kw):
        if befehl_von(tuple(args)) == "push":
            return G.GitErgebnis(code=128, stdout=b"", stderr="remote: Permission to beispiel/projekt.git denied (403)")
        return original(args, **kw)
    att.git = git_403
    with abgelehnt("keine_schreibrechte"):
        einreichen(att, erg)
    assert json.loads(att.pfad("aenderung.json").read_text())["status"] == "bereit"


# ================================================================== Dateien ohne Links
def test_datei_lesen_regeln(tmp_path):
    (tmp_path / "a").write_bytes(b"123")
    assert G.datei_lesen(tmp_path / "a", 3) == b"123"
    assert G.datei_lesen(tmp_path / "fehlt", 3) is None
    with pytest.raises(OSError):
        G.datei_lesen(tmp_path / "a", 2)
    (tmp_path / "ordner").mkdir()
    with pytest.raises(OSError):
        G.datei_lesen(tmp_path / "ordner", 10)
    try:
        (tmp_path / "link").symlink_to(tmp_path / "a")
    except OSError:
        return
    with pytest.raises(OSError):
        G.datei_lesen(tmp_path / "link", 10)


def test_entfernen_folgt_keinem_link(tmp_path):
    if not _links_moeglich(tmp_path):
        pytest.skip("Links nicht erlaubt")
    draussen = tmp_path / "draussen"
    draussen.mkdir()
    (draussen / "wichtig").write_text("x")
    baum = tmp_path / "baum"
    (baum / "a" / "b").mkdir(parents=True)
    (baum / "a" / "b" / "f").write_text("y")
    (baum / "a" / "verweis").symlink_to(draussen, target_is_directory=True)
    if hasattr(os, "geteuid"):
        (baum / "a" / "b").chmod(0o000)
    G.entfernen(baum)
    assert not baum.exists() and (draussen / "wichtig").exists()


# ================================================================== Nachträge aus den Reviews
@pytest.mark.parametrize("repo, gueltig", [("a/b", True), ("a/b.git", False), ("a/..", False), ("a/.", False), ("a/b/c", False),
                                           ("-a/b", False), ("a b/c", False)])
def test_repo_name_streng(repo, gueltig):
    assert G.repo_gueltig(repo) is gueltig


def test_titel_der_wie_ein_schluessel_aussieht():
    assert G.titel_bereinigen("ghp_" + "A" * 36) == G.TITEL_ERSATZ
    assert G.titel_bereinigen("sk-ant-api03-" + "x" * 30) == G.TITEL_ERSATZ


@mit_git
@pytest.mark.parametrize("aendern", [
    lambda e: e.update(markiert=[{"x": 1}]), lambda e: e.update(pfade=[1]), lambda e: e.update(titel="Hallo @alle #1"),
    lambda e: e.update(art="Umsetzung!"), lambda e: e.update(v=True), lambda e: e.update(commit_id="x"), lambda e: e.pop("zeit"),
])
def test_einreichen_json_streng(att, aendern):
    erg = bereit(att)
    mit_pr(att)
    daten = json.loads(att.pfad("einreichen.json").read_text())
    aendern(daten)
    att.pfad("einreichen.json").write_text(json.dumps(daten))
    with abgelehnt("zustand"):
        einreichen(att, erg)


@mit_git
def test_github_json_mit_wahrheitswert_als_version(att):
    starten(att)
    daten = json.loads(att.pfad("github.json").read_text())
    att.pfad("github.json").write_text(json.dumps({**daten, "v": True}))
    with abgelehnt("pruefung_fehler"):
        laufende(att)


@mit_git
def test_erneuter_push_nach_geloeschtem_zweig_zaehlt(att):
    erg = bereit(att)
    mit_pr(att)
    att.antworten[("POST", f"/repos/{REPO}/pulls")] = [antwort(500), antwort(201, {"number": 8, "html_url": f"https://github.com/{REPO}/pull/8"})]
    with abgelehnt("github_fehler"):
        einreichen(att, erg)
    git(att.remote / "beispiel" / "projekt.git", "update-ref", "-d", f"refs/heads/wamo/{JOB}")
    with abgelehnt("grenze_einreichen"):
        einreichen(att, erg, zaehlen=lambda: "grenze_einreichen")
    assert remote_zweig(att) is None and len(att.git_args("push")) == 1


@mit_git
def test_laufende_schreibfehler_beim_kandidaten(att, monkeypatch):
    erste = bereit(att)
    original = G.json_schreiben

    def kaputt(pfad, obj):
        if pfad.name == "einreichen.json":
            raise OSError("voll")
        return original(pfad, obj)
    monkeypatch.setattr(G, "json_schreiben", kaputt)
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"] and erste["status"] == "bereit"
    assert not att.pfad("aus.git").exists() and json.loads(att.pfad("aenderung.json").read_text())["status"] == "gesperrt"


@mit_git
def test_laufende_tief_verschachteltes_ergebnis(att):
    starten(att)
    att.arbeit(stand({"neu.txt": ("100644", b"neu\n")}))
    att.nach_auszug = lambda ergebnis: (ergebnis / "liste.json").write_bytes(b"[" * 200000 + b"]" * 200000)
    erg = laufende(att)
    assert erg["status"] == "gesperrt" and erg["gruende"] == ["pruefung_fehler"]
