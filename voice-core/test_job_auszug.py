"""Tests für den Auszug im netzlosen Sandbox-Schritt pruefung (infra/sokrates2/wamo_job_auszug.py, Plan C, C.5 Laufende 3).

Der Auszug liest das Bundle der Sandbox gegen basis.git und gibt nur eine Dateiliste mit den Inhalten nach ergebnis/; der
Dispatcher liest dieses Ergebnis mit ergebnis_lesen. Die Tests bauen Repos mit dem echten git (nur lokal, kein Netz) über
Plumbing (mktree, commit-tree), damit auch Bäume entstehen, die porcelain nie schreiben würde. Ohne git werden sie übersprungen.
Ausführen (im Ordner voice-core/):  python -m pytest -q test_job_auszug.py
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git fehlt")


def _lade():
    spec = importlib.util.spec_from_file_location("wamo_job_auszug", INFRA / "wamo_job_auszug.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules["wamo_job_auszug"] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


A = _lade()

JOB = "0123456789abcdef"
NULL = "0" * 40
ZEIT = "1700000000 +0000"


def _git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
                "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x", "GIT_AUTHOR_DATE": ZEIT, "GIT_COMMITTER_DATE": ZEIT})
    return env


class Repo:
    """Ein bare Repo für die Tests. Normale Stände entstehen mit fast-import (ein Aufruf), gefährliche Bäume, die fast-import
    ablehnt, mit mktree und commit-tree."""

    def __init__(self, pfad: Path, *, anlegen: bool = True):
        self.pfad = pfad
        if anlegen:
            subprocess.run([GIT, "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(pfad)], check=True, env=_git_env())

    def alternates(self, ziel: Path) -> None:
        (self.pfad / "objects" / "info" / "alternates").write_bytes((ziel / "objects").as_posix().encode() + b"\n")

    def git(self, *args: str, eingabe: bytes | None = None) -> bytes:
        erg = subprocess.run([GIT, f"--git-dir={self.pfad}", *args], input=eingabe, capture_output=True, env=_git_env())
        assert erg.returncode == 0, erg.stderr.decode(errors="replace")
        return erg.stdout

    def importieren(self, ref: str, staende: tuple[dict, ...], von: str | None) -> str:
        """Commits nacheinander auf ref (jeder Stand ist der ganze Baum); Ergebnis: Commit-ID der Spitze."""
        strom = []
        for i, stand in enumerate(staende, start=1):
            strom.append(f"commit {ref}\nmark :{i}\ncommitter T <t@x> {ZEIT}\ndata 1\nm\n".encode())
            if i == 1 and von:
                strom.append(f"from {von}\n".encode())
            strom.append(b"deleteall\n")
            for pfad, (modus, inhalt) in stand.items():
                roh = pfad if isinstance(pfad, bytes) else pfad.encode("utf-8")
                if modus == "160000":
                    strom.append(f"M 160000 {inhalt} ".encode() + roh + b"\n")
                else:
                    strom.append(f"M {modus} inline ".encode() + roh + b"\n" + b"data %d\n" % len(inhalt) + inhalt + b"\n")
        strom.append(f"get-mark :{len(staende)}\n".encode())
        return self.git("fast-import", "--quiet", "--done", eingabe=b"".join(strom) + b"done\n").decode().strip()

    def blob(self, daten: bytes) -> str:
        return self.git("hash-object", "-w", "--stdin", eingabe=daten).decode().strip()

    def baum(self, dateien: dict) -> str:
        """Mit mktree, auch für Bäume, die fast-import ablehnt. dateien: Pfad -> (Modus, Inhalt)."""
        wurzel: dict = {}
        for pfad, wert in dateien.items():
            roh = pfad if isinstance(pfad, bytes) else pfad.encode("utf-8")
            teile = roh.split(b"/")
            knoten = wurzel
            for teil in teile[:-1]:
                knoten = knoten.setdefault(teil, {})
            knoten[teile[-1]] = wert
        return self._baum(wurzel)

    def _baum(self, knoten: dict) -> str:
        zeilen = []
        for name, wert in sorted(knoten.items()):
            if isinstance(wert, dict):
                zeilen.append(b"040000 tree " + self._baum(wert).encode() + b"\t" + name)
            else:
                modus, inhalt = wert
                zeilen.append(modus.encode() + b" blob " + self.blob(inhalt).encode() + b"\t" + name)
        return self.git("mktree", "-z", eingabe=b"".join(z + b"\x00" for z in zeilen)).decode().strip()

    def commit(self, baum: str, *eltern: str) -> str:
        args = ["commit-tree", baum]
        for e in eltern:
            args += ["-p", e]
        return self.git(*args, eingabe=b"m").decode().strip()

    def ref(self, name: str, oid: str) -> None:
        self.git("update-ref", name, oid)

    def bundle(self, ziel: Path, *revs: str) -> Path:
        self.git("bundle", "create", "-q", str(ziel), *revs)
        return ziel


BASIS_DATEIEN = {
    "README.md": ("100644", b"hallo\n"),
    "alt.txt": ("100644", b"weg\n"),
    "src/app.py": ("100644", b"print(1)\n"),
    ".mcp.json": ("100644", b"{}\n"),
    ".claude/settings.json": ("100644", b"{}\n"),
    "bin/tool": ("100755", b"#!/bin/sh\n"),
    "verweis": ("120000", b"src/app.py"),
}


@pytest.fixture(scope="module")
def vorrat(tmp_path_factory):
    """Einmal je Modul: basis.git mit dem Basis-Stand und ein leeres Repo; jede Welt kopiert beide."""
    ordner = tmp_path_factory.mktemp("vorrat")
    basis = Repo(ordner / "basis.git")
    oid = basis.importieren("refs/heads/main", (BASIS_DATEIEN,), None)
    Repo(ordner / "leer.git")
    return ordner, oid


class Welt:
    def __init__(self, tmp: Path, vorrat):
        ordner, self.basis = vorrat
        self.tmp = tmp
        shutil.copytree(ordner / "basis.git", tmp / "basis.git")
        shutil.copytree(ordner / "leer.git", tmp / "quelle.git")
        self.quelle = Repo(tmp / "quelle.git", anlegen=False)
        self.quelle.alternates(tmp / "basis.git")
        self.ergebnis = tmp / "ergebnis"
        self.ergebnis.mkdir()
        self.arbeit = tmp / "arbeit"
        self.arbeit.mkdir()

    def zweig(self, *staende: dict, ref: str = f"refs/heads/wamo/{JOB}", von: str | None = None) -> str:
        return self.quelle.importieren(ref, staende, von or self.basis)

    def bundle(self, *revs: str) -> Path:
        return self.quelle.bundle(self.tmp / "bundle.ein", *(revs or (f"refs/heads/wamo/{JOB}", f"^{self.basis}")))

    def auszug(self, bundle: Path | None = None, grenzen=None, **kw) -> dict:
        return A.auszug(JOB, kw.pop("basis", self.basis), basis_git=self.tmp / "basis.git", bundle=bundle or self.bundle(),
                        ergebnis=self.ergebnis, arbeit=kw.pop("arbeit", self.arbeit), grenzen=grenzen or A.Grenzen(), **kw)

    def liste(self) -> dict:
        return json.loads((self.ergebnis / "liste.json").read_text(encoding="utf-8"))


@pytest.fixture
def welt(tmp_path, vorrat):
    return Welt(tmp_path, vorrat)


def stand(aenderungen: dict | None = None, **kurz) -> dict:
    """Basis mit Änderungen: Pfad -> (Modus, Inhalt) oder None zum Löschen."""
    out = dict(BASIS_DATEIEN)
    for pfad, wert in {**(aenderungen or {}), **kurz}.items():
        if wert is None:
            out.pop(pfad, None)
        else:
            out[pfad] = wert
    return out


def blob_id(daten: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(daten) + daten).hexdigest()


def nach_pfad(liste: dict) -> dict:
    return {base64.b64decode(e["pfad"]): e for e in liste["eintraege"]}


# ---------------------------------------------------------------- Normalfall
def test_auszug_liefert_liste_und_inhalte(welt):
    welt.zweig(stand({"src/app.py": ("100644", b"print(2)\n")}),
               stand({"src/app.py": ("100644", b"print(2)\n"), "neu.txt": ("100644", b"neu\n"), "alt.txt": None,
                      "bin/tool": ("100644", b"#!/bin/sh\n"), "bild.png": ("100644", b"\x89PNG\x00\x00"),
                      "verweis2": ("120000", b"README.md")}))
    ergebnis = welt.auszug()
    assert ergebnis["status"] == "ok"
    liste = welt.liste()
    assert liste == ergebnis
    assert liste["v"] == 1 and liste["job"] == JOB and liste["basis"] == welt.basis and liste["commits"] == 2
    eintraege = nach_pfad(liste)
    assert set(eintraege) == {b"src/app.py", b"neu.txt", b"alt.txt", b"bin/tool", b"bild.png", b"verweis2"}
    assert eintraege[b"alt.txt"]["art"] == "geloescht" and eintraege[b"alt.txt"]["datei"] is None
    assert eintraege[b"alt.txt"]["modus"] == "000000" and eintraege[b"alt.txt"]["oid"] == NULL
    assert eintraege[b"neu.txt"]["art"] == "neu" and eintraege[b"neu.txt"]["alt_modus"] == "000000"
    assert eintraege[b"bin/tool"]["art"] == "geaendert"
    assert (eintraege[b"bin/tool"]["alt_modus"], eintraege[b"bin/tool"]["modus"]) == ("100755", "100644")
    assert eintraege[b"verweis2"]["modus"] == "120000"
    for pfad, inhalt in ((b"src/app.py", b"print(2)\n"), (b"bild.png", b"\x89PNG\x00\x00"), (b"verweis2", b"README.md")):
        e = eintraege[pfad]
        assert (welt.ergebnis / e["datei"]).read_bytes() == inhalt
        assert e["groesse"] == len(inhalt) and e["oid"] == blob_id(inhalt)


def test_ergebnis_hat_nur_regulaere_dateien(welt):
    welt.zweig(stand(neu_txt=("100644", b"neu\n")))
    welt.auszug()
    for wurzel, ordner, dateien in os.walk(welt.ergebnis):
        for name in ordner + dateien:
            p = Path(wurzel) / name
            assert not p.is_symlink()
    assert sorted(p.name for p in welt.ergebnis.iterdir()) == ["dateien", "liste.json"]


def test_basis_git_bleibt_unveraendert(welt):
    def abdruck():
        return sorted((str(p.relative_to(welt.tmp / "basis.git")), p.stat().st_size)
                      for p in (welt.tmp / "basis.git").rglob("*") if p.is_file())
    vorher = abdruck()
    welt.zweig(stand(neu_txt=("100644", b"neu\n")))
    welt.auszug()
    assert abdruck() == vorher


def test_pfad_als_rohe_bytes(welt):
    welt.zweig(stand(**{"x": ("100644", b"1")}) | {b"bad\xffname": ("100644", b"2")})
    eintraege = nach_pfad(welt.auszug())
    assert b"bad\xffname" in eintraege


def test_gitlink_ohne_inhalt(welt):
    welt.zweig(stand() | {"vendor/lib": ("160000", "1" * 40)})
    e = nach_pfad(welt.auszug())[b"vendor/lib"]
    assert e["modus"] == "160000" and e["datei"] is None and e["groesse"] == 0


def test_keine_aenderung_ergibt_leere_liste(welt):
    welt.zweig(stand(), stand())  # zwei Commits ohne Änderung am Baum
    ergebnis = welt.auszug()
    assert ergebnis["status"] == "ok" and ergebnis["eintraege"] == [] and ergebnis["commits"] == 2


# ---------------------------------------------------------------- Bundle ungültig
def test_zwei_koepfe(welt):
    welt.zweig(stand(a=("100644", b"a")))
    welt.zweig(stand(b=("100644", b"b")), ref="refs/heads/wamo/fedcba9876543210")
    bundle = welt.bundle(f"refs/heads/wamo/{JOB}", "refs/heads/wamo/fedcba9876543210", f"^{welt.basis}")
    assert welt.auszug(bundle) == {"v": 1, "status": "fehler", "grund": "bundle_ungueltig"}
    assert welt.liste()["grund"] == "bundle_ungueltig"


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/wamo/fedcba9876543210", f"refs/tags/wamo/{JOB}"])
def test_falscher_kopf(welt, ref):
    welt.zweig(stand(a=("100644", b"a")), ref=ref)
    assert welt.auszug(welt.bundle(ref, f"^{welt.basis}"))["grund"] == "bundle_ungueltig"


def test_voraussetzung_fehlt_in_der_basis(welt):
    zwischen = welt.zweig(stand(a=("100644", b"a")), ref="refs/heads/zwischen")
    welt.zweig(stand(a=("100644", b"a"), b=("100644", b"b")), von=zwischen)
    assert welt.auszug(welt.bundle(f"refs/heads/wamo/{JOB}", f"^{zwischen}"))["grund"] == "bundle_ungueltig"


def test_fremde_basis(welt):
    fremd = welt.quelle.commit(welt.quelle.baum({"x": ("100644", b"x")}))
    welt.zweig(stand(a=("100644", b"a")), von=fremd)
    assert welt.auszug(welt.bundle(f"refs/heads/wamo/{JOB}"))["grund"] == "basis_fehlt"


def test_basis_unbekannt(welt):
    welt.zweig(stand(a=("100644", b"a")))
    assert welt.auszug(basis="1" * 40)["grund"] == "basis_fehlt"


def test_fsck_weist_gefaehrlichen_baum_ab(welt):
    spitze = welt.quelle.commit(welt.quelle.baum(stand() | {".GIT/config": ("100644", b"[core]\n")}), welt.basis)
    welt.quelle.ref(f"refs/heads/wamo/{JOB}", spitze)
    assert welt.auszug()["grund"] == "bundle_ungueltig"


@pytest.mark.parametrize("kopf", [b"", b"kein bundle\n", b"# v2 git bundle\n", b"# v9 git bundle\n\n",
                                  b"# v3 git bundle\n@filter=blob:none\n" + b"1" * 40 + b" refs/heads/wamo/" + JOB.encode() + b"\n\n",
                                  b"# v3 git bundle\n@object-format=sha256\n" + b"1" * 40 + b" refs/heads/wamo/" + JOB.encode() + b"\n\n",
                                  b"# v2 git bundle\n" + b"1" * 40 + b" refs/heads/wamo/" + JOB.encode()])
def test_kaputter_kopf(tmp_path, kopf):
    p = tmp_path / "kaputt.bundle"
    p.write_bytes(kopf)
    with pytest.raises(A.AuszugFehler) as fehler:
        A.bundle_kopf(p, JOB, A.Grenzen())
    assert fehler.value.grund == "bundle_ungueltig"


def test_kopf_mit_voraussetzung_und_v3(tmp_path):
    p = tmp_path / "gut.bundle"
    p.write_bytes(b"# v3 git bundle\n@object-format=sha1\n-" + b"2" * 40 + b" Betreff mit Leerzeichen\n" + b"1" * 40
                  + b" refs/heads/wamo/" + JOB.encode() + b"\n\nPACK")
    assert A.bundle_kopf(p, JOB, A.Grenzen()) == "1" * 40


def test_bundle_ist_ordner(welt):
    (welt.tmp / "ordner.bundle").mkdir()
    assert welt.auszug(welt.tmp / "ordner.bundle")["grund"] == "bundle_ungueltig"


def test_bundle_zu_gross(welt):
    welt.zweig(stand(a=("100644", b"a" * 1000)))
    assert welt.auszug(grenzen=A.Grenzen(bundle_bytes=100))["grund"] == "bundle_ungueltig"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="nur unter Linux")
def test_bundle_als_fifo(welt):
    os.mkfifo(welt.tmp / "fifo.bundle")
    assert welt.auszug(welt.tmp / "fifo.bundle")["grund"] == "bundle_ungueltig"


def test_bundle_als_link(welt):
    welt.zweig(stand(a=("100644", b"a")))
    echt = welt.bundle()
    link = welt.tmp / "link.bundle"
    try:
        link.symlink_to(echt)
    except OSError:
        pytest.skip("Links nicht erlaubt")
    assert welt.auszug(link)["grund"] == "bundle_ungueltig"


# ---------------------------------------------------------------- Grenzen
def test_zu_viele_commits(welt):
    welt.zweig(*(stand(a=("100644", str(i).encode())) for i in range(4)))
    assert welt.auszug(grenzen=A.Grenzen(commits=3))["grund"] == "zu_viele_commits"
    welt2_ergebnis = welt.tmp / "e2"
    welt2_ergebnis.mkdir()
    arbeit2 = welt.tmp / "a2"
    arbeit2.mkdir()
    erg = A.auszug(JOB, welt.basis, basis_git=welt.tmp / "basis.git", bundle=welt.tmp / "bundle.ein", ergebnis=welt2_ergebnis,
                   arbeit=arbeit2, grenzen=A.Grenzen(commits=4))
    assert erg["status"] == "ok"


def test_groesse_wird_vor_dem_lesen_geprueft(welt, monkeypatch):
    welt.zweig(stand(gross=("100644", b"x" * 11)))
    gelesen = []
    monkeypatch.setattr(A, "_inhalte_lesen", lambda *a, **k: gelesen.append(1) or {})
    assert welt.auszug(grenzen=A.Grenzen(datei_bytes=10))["grund"] == "zu_gross"
    assert gelesen == []
    assert not (welt.ergebnis / "dateien").exists()


def test_datei_am_rand_der_groesse(welt):
    welt.zweig(stand(gross=("100644", b"x" * 10)))
    assert welt.auszug(grenzen=A.Grenzen(datei_bytes=10))["status"] == "ok"


def test_gesamtgroesse(welt):
    welt.zweig(stand(a=("100644", b"x" * 8), b=("100644", b"y" * 8)))
    assert welt.auszug(grenzen=A.Grenzen(datei_bytes=10, gesamt_bytes=15))["grund"] == "zu_gross"


def test_zu_viele_dateien(welt):
    welt.zweig(stand(a=("100644", b"1"), b=("100644", b"2"), c=("100644", b"3")))
    assert welt.auszug(grenzen=A.Grenzen(dateien=2))["grund"] == "zu_gross"


def test_zu_viele_eintraege(welt):
    welt.zweig(stand({"alt.txt": None, "README.md": None, "src/app.py": None}))
    assert welt.auszug(grenzen=A.Grenzen(eintraege=2))["grund"] == "zu_gross"


def test_zeitbudget(welt):
    welt.zweig(stand(a=("100644", b"1")))
    zeiten = iter([0.0, 0.0, 1000.0])
    assert welt.auszug(uhr=lambda: next(zeiten, 1000.0))["grund"] == "pruefung_fehler"


# ---------------------------------------------------------------- Ergebnisordner
def test_ergebnis_nicht_leer(welt):
    (welt.ergebnis / "alt").write_text("x")
    welt.zweig(stand(a=("100644", b"1")))
    with pytest.raises(A.AuszugFehler) as fehler:
        welt.auszug()
    assert fehler.value.grund == "pruefung_fehler"


def test_ergebnis_als_link(welt, tmp_path):
    ziel = tmp_path / "anderswo"
    ziel.mkdir()
    link = tmp_path / "ergebnis-link"
    try:
        link.symlink_to(ziel, target_is_directory=True)
    except OSError:
        pytest.skip("Links nicht erlaubt")
    welt.zweig(stand(a=("100644", b"1")))
    with pytest.raises(A.AuszugFehler):
        A.auszug(JOB, welt.basis, basis_git=welt.tmp / "basis.git", bundle=welt.bundle(), ergebnis=link, arbeit=welt.arbeit,
                 grenzen=A.Grenzen())
    assert list(ziel.iterdir()) == []


@pytest.mark.parametrize("job,basis", [("abc", "1" * 40), (JOB, "xyz"), (JOB + "/../x", "1" * 40), (JOB, "1" * 39)])
def test_argumente_geprueft(welt, job, basis):
    with pytest.raises(A.AuszugFehler):
        A.auszug(job, basis, basis_git=welt.tmp / "basis.git", bundle=welt.tmp / "x", ergebnis=welt.ergebnis, arbeit=welt.arbeit,
                 grenzen=A.Grenzen())


# ---------------------------------------------------------------- keine Hooks, keine Konfiguration aus Umgebung oder Repo
def test_umgebung_und_vorlagen_wirken_nicht(welt, monkeypatch, tmp_path):
    marke = tmp_path / "marke"
    vorlage = tmp_path / "vorlage" / "hooks"
    vorlage.mkdir(parents=True)
    for hook in ("reference-transaction", "post-index-change", "post-checkout"):
        (vorlage / hook).write_text(f"#!/bin/sh\necho x > '{marke.as_posix()}'\n")
        (vorlage / hook).chmod(0o755)
    konfig = tmp_path / "global.gitconfig"
    konfig.write_text(f"[core]\n\thooksPath = {vorlage.as_posix()}\n\tfsmonitor = echo > '{marke.as_posix()}'\n")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tmp_path / "vorlage"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(konfig))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.hooksPath'='{vorlage.as_posix()}'")
    monkeypatch.setenv("GIT_DIR", str(welt.tmp / "quelle.git"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(welt.tmp / "quelle.git" / "objects"))
    # Hooks und Konfiguration auch in basis.git (dort schreibt nur der Dispatcher, aber der Auszug liest dessen Konfiguration nie)
    (welt.tmp / "basis.git" / "hooks").mkdir(exist_ok=True)
    (welt.tmp / "basis.git" / "hooks" / "reference-transaction").write_text(f"#!/bin/sh\necho x > '{marke.as_posix()}'\n")
    with open(welt.tmp / "basis.git" / "config", "a") as f:
        f.write(f"[core]\n\thooksPath = {vorlage.as_posix()}\n")
    welt.zweig(stand(a=("100644", b"1")))
    bundle = welt.bundle()
    for name in ("GIT_TEMPLATE_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        assert name in os.environ
    assert welt.auszug(bundle)["status"] == "ok"
    assert not marke.exists()
    hooks = welt.arbeit / "auszug.git" / "hooks"
    assert not hooks.exists() or list(hooks.iterdir()) == []


def test_umgebung_der_git_aufrufe_ist_fest():
    env = A.git_umgebung()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert not any(k in env for k in ("GIT_DIR", "GIT_TEMPLATE_DIR", "GIT_CONFIG_PARAMETERS", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                                      "ANTHROPIC_API_KEY", "GH_TOKEN"))
    argv = A.git_argv("/x.git", "status")
    assert argv[1] == "--git-dir=/x.git"
    for paar in ("core.hooksPath=" + os.devnull, "core.fsmonitor=false", "protocol.allow=never", "protocol.file.allow=always",
                 "fetch.fsckObjects=true", "transfer.fsckObjects=true", "fetch.unpackLimit=1", "gc.auto=0"):
        assert paar in argv


# ---------------------------------------------------------------- Dispatcher liest das Ergebnis
def _gelesen(welt):
    return A.ergebnis_lesen(welt.ergebnis, job=JOB, basis=welt.basis, grenzen=A.Grenzen())


def test_ergebnis_lesen_rundweg(welt):
    spitze = welt.zweig(stand({"src/app.py": ("100644", b"print(2)\n"), "alt.txt": None, "l": ("120000", b"README.md")}))
    welt.auszug()
    erg = _gelesen(welt)
    assert erg.status == "ok" and erg.spitze == spitze and erg.commits == 1
    eintraege = {e.pfad: e for e in erg.eintraege}
    assert eintraege[b"src/app.py"].inhalt == b"print(2)\n"
    assert eintraege[b"alt.txt"].inhalt is None and eintraege[b"alt.txt"].art == "geloescht"
    assert eintraege[b"l"].inhalt == b"README.md" and eintraege[b"l"].modus == "120000"
    assert eintraege[b"src/app.py"].alt_oid == blob_id(b"print(1)\n")


def test_ergebnis_lesen_fehler_mit_grund(welt):
    welt.zweig(*(stand(a=("100644", str(i).encode())) for i in range(3)))
    welt.auszug(grenzen=A.Grenzen(commits=2))
    erg = _gelesen(welt)
    assert erg.status == "fehler" and erg.grund == "zu_viele_commits" and erg.eintraege == ()


@pytest.fixture(scope="module")
def fertig(tmp_path_factory, vorrat):
    """Einmal je Modul: ein gültiges Ergebnis mit einer neuen Datei; jeder Test bekommt eine eigene Kopie (Fixture kopie)."""
    w = Welt(tmp_path_factory.mktemp("fertig"), vorrat)
    w.zweig(stand(neu_txt=("100644", b"neu\n")))
    assert w.auszug()["status"] == "ok"
    return w


class Kopie:
    def __init__(self, fertig: Welt, tmp: Path):
        self.tmp, self.basis, self.ergebnis = tmp, fertig.basis, tmp / "ergebnis"
        shutil.copytree(fertig.ergebnis, self.ergebnis)

    def liste(self) -> dict:
        return json.loads((self.ergebnis / "liste.json").read_text(encoding="utf-8"))


@pytest.fixture
def kopie(fertig, tmp_path):
    return Kopie(fertig, tmp_path)


def _manipuliere_liste(k, aendern):
    liste = k.liste()
    aendern(liste)
    (k.ergebnis / "liste.json").write_text(json.dumps(liste), encoding="utf-8")


def test_kopie_ist_lesbar(kopie):
    assert _gelesen(kopie).status == "ok"


@pytest.mark.parametrize("aendern", [
    lambda l: l.update(job="fedcba9876543210"),
    lambda l: l.update(basis="1" * 40),
    lambda l: l.update(v=2),
    lambda l: l.update(v=True),
    lambda l: l.update(v=1.0),
    lambda l: l.update(status="vielleicht"),
    lambda l: l.update(extra=1),
    lambda l: l.update(commits=-1),
    lambda l: l.update(spitze="xyz"),
    lambda l: l["eintraege"][0].update(pfad="kein base64!"),
    lambda l: l["eintraege"][0].update(art="umbenannt"),
    lambda l: l["eintraege"][0].update(modus="1006444"),
    lambda l: l["eintraege"][0].update(oid="1" * 40),
    lambda l: l["eintraege"][0].update(groesse=999),
    lambda l: l["eintraege"][0].update(datei="../liste.json"),
    lambda l: l["eintraege"][0].update(datei="dateien/7"),
    lambda l: l["eintraege"][0].pop("alt_oid"),
    lambda l: l["eintraege"].append(dict(l["eintraege"][0])),
])
def test_ergebnis_lesen_weist_manipulation_ab(kopie, aendern):
    _manipuliere_liste(kopie, aendern)
    with pytest.raises(A.AuszugFehler) as fehler:
        _gelesen(kopie)
    assert fehler.value.grund == "pruefung_fehler"


def test_ergebnis_lesen_unbekannter_grund(welt):
    (welt.ergebnis / "liste.json").write_text(json.dumps({"v": 1, "status": "fehler", "grund": "irgendwas"}))
    with pytest.raises(A.AuszugFehler):
        _gelesen(welt)


def test_ergebnis_lesen_inhalt_vertauscht(kopie):
    datei = kopie.ergebnis / kopie.liste()["eintraege"][0]["datei"]
    datei.write_bytes(b"bos\n")  # gleiche Länge, anderer Inhalt
    with pytest.raises(A.AuszugFehler):
        _gelesen(kopie)


def test_ergebnis_lesen_zusaetzliche_datei(kopie):
    (kopie.ergebnis / "dateien" / "99").write_bytes(b"x")
    with pytest.raises(A.AuszugFehler):
        _gelesen(kopie)


def test_ergebnis_lesen_fremder_eintrag_im_ordner(kopie):
    (kopie.ergebnis / "extra.txt").write_bytes(b"x")
    with pytest.raises(A.AuszugFehler):
        _gelesen(kopie)


def test_ergebnis_lesen_datei_als_link(kopie):
    datei = kopie.ergebnis / kopie.liste()["eintraege"][0]["datei"]
    geheim = kopie.tmp / "geheim"
    geheim.write_bytes(b"neu\n")
    datei.unlink()
    try:
        datei.symlink_to(geheim)
    except OSError:
        pytest.skip("Links nicht erlaubt")
    with pytest.raises(A.AuszugFehler):
        _gelesen(kopie)


def test_ergebnis_lesen_hardlink(kopie):
    datei = kopie.ergebnis / kopie.liste()["eintraege"][0]["datei"]
    try:
        os.link(datei, kopie.tmp / "zweiter-name")
    except OSError:
        pytest.skip("Hardlinks nicht möglich")
    with pytest.raises(A.AuszugFehler):
        _gelesen(kopie)


def test_ergebnis_lesen_liste_zu_gross(welt):
    (welt.ergebnis / "liste.json").write_bytes(b" " * (A.MAX_LISTE_BYTES + 1))
    with pytest.raises(A.AuszugFehler):
        _gelesen(welt)


def test_ergebnis_lesen_ohne_liste(welt):
    with pytest.raises(A.AuszugFehler):
        _gelesen(welt)


# ---------------------------------------------------------------- Aufruf als Programm (so startet ihn wamo-job.sh)
def test_programm_aufruf(welt):
    welt.zweig(stand(neu_txt=("100644", b"neu\n")))
    bundle = welt.bundle()
    erg = subprocess.run([sys.executable, "-I", str(INFRA / "wamo_job_auszug.py"), "--job", JOB, "--basis", welt.basis,
                          "--basis-git", str(welt.tmp / "basis.git"), "--bundle", str(bundle), "--ergebnis", str(welt.ergebnis),
                          "--arbeit", str(welt.arbeit)], capture_output=True, timeout=60)
    assert erg.returncode == 0, erg.stderr
    assert welt.liste()["status"] == "ok"


def test_programm_aufruf_mit_fehler_im_argument(welt):
    erg = subprocess.run([sys.executable, "-I", str(INFRA / "wamo_job_auszug.py"), "--job", "kaputt", "--basis", welt.basis,
                          "--ergebnis", str(welt.ergebnis)], capture_output=True, timeout=60)
    assert erg.returncode == 2
    assert not (welt.ergebnis / "liste.json").exists()


def test_feste_pfade_der_sandbox():
    assert (A.BASIS_GIT, A.BUNDLE, A.ERGEBNIS) == ("/run/wamo/basis.git", "/run/wamo/bundle.ein", "/run/wamo/ergebnis")
    assert A.Grenzen() == A.Grenzen(commits=200, dateien=300, eintraege=2000, datei_bytes=5 * 1024 * 1024,
                                    gesamt_bytes=20 * 1024 * 1024, bundle_bytes=200 * 1024 * 1024, zeit_s=60.0)


def test_ergebnis_lesen_tiefe_schachtelung(kopie):
    (kopie.ergebnis / "liste.json").write_bytes(b"[" * 200000 + b"]" * 200000)
    with pytest.raises(A.AuszugFehler) as fehler:
        _gelesen(kopie)
    assert fehler.value.grund == "pruefung_fehler"
