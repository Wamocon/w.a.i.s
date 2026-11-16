"""Tests für das lokale Werkzeug des Installers vom Server: scripts/wamo_installer_sokrates2.py (Paket P2, docs/ausrollen-neue-nutzer.md, 4.2).

ssh und scp sind immer gemockt: Eine Attrappe für subprocess.run zeichnet jeden Aufruf auf und antwortet auf "status --json" mit einem Stand,
den der Test vorgibt. Kein Test spricht mit Sokrates-2. Signaturen entstehen mit cryptography (Ed25519).

Aufruf (aus dem Repo-Hauptordner, mit der Python-Umgebung von voice-core):
  voice-core/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider scripts/test_wamo_installer_sokrates2.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_installer_sokrates2 as w  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
MODUL = WURZEL / "infra" / "sokrates2" / "wamo_verteilung_manifest.py"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
BAUZEIT = "2026-11-20T10:00:00.000Z"
SKRIPT = "sudo bash ~/wamo-infra/wamo-verteilung-einrichten.sh"
LEER = {"v": 1, "aktuell": None, "vorher": None, "staende": [], "schluesselliste": False}

ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")


def schluesselpaar():
    privat = ed25519.Ed25519PrivateKey.generate()
    return privat, privat.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def stand(version: str) -> dict:
    return {"version": version, "sha256": "a" * 64, "groesse": 10, "commit": COMMIT, "signatur": "keine", "datei": "ok"}


class Server:
    """Attrappe für subprocess.run: zeichnet ssh- und scp-Aufrufe auf, nie ein echter Aufruf."""

    def __init__(self, status: dict | None = None, rc_einsetzen: int = 0, rc_status: int = 0, status_roh: bytes | None = None):
        self.aufrufe: list[list[str]] = []
        self.status = status if status is not None else LEER
        self.rc_einsetzen, self.rc_status, self.status_roh = rc_einsetzen, rc_status, status_roh

    def __call__(self, argv, **_kw):
        argv = [str(a) for a in argv]
        self.aufrufe.append(argv)
        if argv[0] == "ssh":
            befehl = argv[-1]
            if befehl.endswith("status --json"):
                roh = self.status_roh if self.status_roh is not None else json.dumps(self.status).encode("utf-8")
                return subprocess.CompletedProcess(argv, self.rc_status, roh, b"")
            if " einsetzen " in befehl:
                return subprocess.CompletedProcess(argv, self.rc_einsetzen, b"== Installer einsetzen\n", b"")
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if argv[0] == "scp":
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        raise AssertionError(f"unerwarteter Aufruf: {argv}")


@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(w.subprocess, "run", s)
    monkeypatch.setattr(w, "HOST", "wamo-sokrates2")
    return s


@pytest.fixture
def ohne_schluesselliste(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "SCHLUESSEL_DATEI", tmp_path / "gibt-es-nicht.json")


def ssh(befehl: str) -> list[str]:
    return ["ssh", *w.SSH_OPTIONEN, "wamo-sokrates2", befehl]


def scp(lokal: Path, ziel: str) -> list[str]:
    return ["scp", "-q", *w.SSH_OPTIONEN, str(lokal), f"wamo-sokrates2:{ziel}"]


def bauen(ordner: Path, version: str = "0.3.0", inhalt: bytes | None = None, privat=None, manifest_aendern=None) -> tuple[Path, Path]:
    """Ein Bauordner wie dist/: WAIS-Setup-<Version>.exe, aktuell.json und (mit privat) aktuell.json.sig."""
    ordner.mkdir(parents=True, exist_ok=True)
    inhalt = inhalt if inhalt is not None else b"MZ" + version.encode("ascii") + bytes(3000)
    exe = ordner / f"WAIS-Setup-{version}.exe"
    exe.write_bytes(inhalt)
    d = {"v": 1, "produkt": "wais-desktop", "version": version, "datei": exe.name, "groesse": len(inhalt),
         "sha256": hashlib.sha256(inhalt).hexdigest(), "bauzeit": BAUZEIT, "commit": COMMIT}
    if manifest_aendern:
        manifest_aendern(d)
    roh = json.dumps(d, separators=(",", ":")).encode("utf-8")
    (ordner / "aktuell.json").write_bytes(roh)
    if privat is not None:
        (ordner / "aktuell.json.sig").write_bytes(base64.b64encode(privat.sign(roh)) + b"\n")
    return exe, ordner / "aktuell.json"


def schluessel_datei(pfad: Path, *oeffentlich: bytes) -> Path:
    pfad.write_text(json.dumps([base64.b64encode(k).decode("ascii") for k in oeffentlich]), encoding="utf-8")
    return pfad


# ---------------------------------------------------------------- eine Prüfregel


def test_die_pruefregel_kommt_aus_infra():
    assert Path(w.regel.__file__).resolve() == MODUL.resolve()
    quelle = Path(w.__file__).read_text(encoding="utf-8")
    assert "def manifest_pruefen" not in quelle and "VERSION_RE" not in quelle  # keine zweite Regel im Werkzeug


def test_texte_ohne_gedankenstriche_und_ohne_geheimnisse():
    for pfad in (Path(w.__file__), Path(__file__)):
        text = pfad.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, pfad.name
        assert not re.search(r"sk-ant-[A-Za-z0-9]|BEGIN [A-Z ]*PRIVATE KEY", text), pfad.name


# ---------------------------------------------------------------- manifest


class TestManifest:
    def test_erzeugt_das_vereinbarte_format(self, tmp_path, server, ohne_schluesselliste):
        exe = tmp_path / "dist" / "WAIS-Setup-0.2.0.exe"
        exe.parent.mkdir()
        inhalt = b"MZ" + bytes(4096)
        exe.write_bytes(inhalt)
        assert w.main(["manifest", str(exe), "--commit", COMMIT, "--bauzeit", BAUZEIT, "--aus", str(tmp_path / "dist")]) == 0
        roh = (tmp_path / "dist" / "aktuell.json").read_bytes()
        soll = ('{"v":1,"produkt":"wais-desktop","version":"0.2.0","datei":"WAIS-Setup-0.2.0.exe","groesse":4098,"sha256":"'
                + hashlib.sha256(inhalt).hexdigest() + '","bauzeit":"2026-11-20T10:00:00.000Z","commit":"' + COMMIT + '"}')
        assert roh == soll.encode("utf-8")  # kompakt, ohne Zeilenende, Felder in der festen Reihenfolge
        assert w.regel.manifest_pruefen(roh)["version"] == "0.2.0"
        assert not (tmp_path / "dist" / "aktuell.json.sig").exists()
        assert w.main(["pruefen", str(exe)]) == 0, "das erzeugte Manifest besteht die eigene Prüfung"
        assert server.aufrufe == [], "manifest und pruefen sprechen nie mit dem Server"

    def test_ohne_bauzeit_gilt_jetzt_in_utc_mit_millisekunden(self, tmp_path):
        exe = tmp_path / "WAIS-Setup-0.2.0.exe"
        exe.write_bytes(b"MZ")
        assert w.main(["manifest", str(exe), "--commit", COMMIT, "--aus", str(tmp_path)]) == 0
        bauzeit = json.loads((tmp_path / "aktuell.json").read_bytes())["bauzeit"]
        assert re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", bauzeit)

    def test_ueberschreibt_nie_ein_vorhandenes_manifest_oder_eine_signatur(self, tmp_path):
        exe = tmp_path / "WAIS-Setup-0.2.0.exe"
        exe.write_bytes(b"MZ")
        for name in ("aktuell.json", "aktuell.json.sig"):
            (tmp_path / name).write_bytes(b"alt")
            assert w.main(["manifest", str(exe), "--commit", COMMIT, "--aus", str(tmp_path)]) == 1
            assert (tmp_path / name).read_bytes() == b"alt"
            (tmp_path / name).unlink()

    @pytest.mark.parametrize("args", [
        ["--commit", COMMIT.upper()], ["--commit", COMMIT[:39]], ["--commit", "$(id)" + "0" * 35],
        ["--commit", COMMIT, "--bauzeit", "2026-11-20 10:00:00Z"], ["--commit", COMMIT, "--bauzeit", "gestern"],
    ])
    def test_falsche_angaben_sind_ein_aufruffehler(self, tmp_path, args):
        exe = tmp_path / "WAIS-Setup-0.2.0.exe"
        exe.write_bytes(b"MZ")
        with pytest.raises(SystemExit) as e:
            w.main(["manifest", str(exe), *args, "--aus", str(tmp_path)])
        assert e.value.code == 2 and not (tmp_path / "aktuell.json").exists()

    @pytest.mark.parametrize("name", ["WAIS-Setup.exe", "WAIS-Setup-0.2.exe", "WAIS-Setup-01.2.0.exe", "wais-setup-0.2.0.exe", "WAIS-Setup-0.2.0.msi"])
    def test_der_dateiname_muss_die_version_tragen(self, tmp_path, name):
        exe = tmp_path / name
        exe.write_bytes(b"MZ")
        assert w.main(["manifest", str(exe), "--commit", COMMIT, "--aus", str(tmp_path)]) == 1
        assert not (tmp_path / "aktuell.json").exists()


# ---------------------------------------------------------------- pruefen (nur lokal)


class TestPruefen:
    def test_unsigniert_ohne_schluesselliste_mit_hinweis(self, tmp_path, server, ohne_schluesselliste, capsys):
        exe, _ = bauen(tmp_path)
        assert w.main(["pruefen", str(exe)]) == 0
        aus = capsys.readouterr()
        assert "Hinweis" in aus.out + aus.err and "unsigniert" in aus.out + aus.err
        assert server.aufrufe == []

    def test_signiert_mit_schluesselliste(self, tmp_path, server, capsys):
        privat, oeffentlich = schluesselpaar()
        _, anderer = schluesselpaar()
        exe, _ = bauen(tmp_path, privat=privat)
        liste = schluessel_datei(tmp_path / "schluessel.json", anderer, oeffentlich)
        assert w.main(["pruefen", str(exe), "--schluessel", str(liste)]) == 0
        assert "gültig" in capsys.readouterr().out and server.aufrufe == []

    def test_die_schluesselliste_im_repo_gilt_ohne_angabe(self, tmp_path, server, monkeypatch):
        privat, oeffentlich = schluesselpaar()
        monkeypatch.setattr(w, "SCHLUESSEL_DATEI", schluessel_datei(tmp_path / "update-schluessel.json", oeffentlich))
        exe, _ = bauen(tmp_path / "dist", privat=privat)
        assert w.main(["pruefen", str(exe)]) == 0
        (tmp_path / "dist" / "aktuell.json.sig").unlink()
        assert w.main(["pruefen", str(exe)]) == 1, "mit Schlüsselliste ist die Signatur Pflicht"

    def test_falsche_pruefsumme(self, tmp_path, server, ohne_schluesselliste, capsys):
        exe, _ = bauen(tmp_path, manifest_aendern=lambda d: d.update(sha256="f" * 64))
        assert w.main(["pruefen", str(exe)]) == 1
        assert "SHA-256" in capsys.readouterr().err

    def test_falsche_groesse(self, tmp_path, server, ohne_schluesselliste, capsys):
        exe, _ = bauen(tmp_path, manifest_aendern=lambda d: d.update(groesse=d["groesse"] + 1))
        assert w.main(["pruefen", str(exe)]) == 1
        assert "Größe" in capsys.readouterr().err

    def test_manifest_mit_zusatzfeld(self, tmp_path, server, ohne_schluesselliste):
        exe, _ = bauen(tmp_path, manifest_aendern=lambda d: d.update(kanal="beta"))
        assert w.main(["pruefen", str(exe)]) == 1

    def test_falsche_signatur(self, tmp_path, server, capsys):
        privat, oeffentlich = schluesselpaar()
        exe, manifest = bauen(tmp_path, privat=privat)
        manifest.write_bytes(manifest.read_bytes() + b"\n")  # gültiges Manifest, aber nicht die signierten Bytes
        liste = schluessel_datei(tmp_path / "schluessel.json", oeffentlich)
        assert w.main(["pruefen", str(exe), "--schluessel", str(liste)]) == 1
        assert "passt zu keinem Schlüssel" in capsys.readouterr().err

    def test_fremder_schluessel(self, tmp_path, server, capsys):
        privat, _ = schluesselpaar()
        _, fremd = schluesselpaar()
        exe, _ = bauen(tmp_path, privat=privat)
        liste = schluessel_datei(tmp_path / "schluessel.json", fremd)
        assert w.main(["pruefen", str(exe), "--schluessel", str(liste)]) == 1
        assert "passt zu keinem Schlüssel" in capsys.readouterr().err

    def test_kaputte_signaturdatei(self, tmp_path, server, ohne_schluesselliste):
        exe, _ = bauen(tmp_path)
        (tmp_path / "aktuell.json.sig").write_bytes(b"kaputt\n")
        assert w.main(["pruefen", str(exe)]) == 1

    def test_ausdruecklich_genannte_dateien_muessen_da_sein(self, tmp_path, server, ohne_schluesselliste):
        exe, manifest = bauen(tmp_path)
        assert w.main(["pruefen", str(exe), "--schluessel", str(tmp_path / "fehlt.json")]) == 1
        assert w.main(["pruefen", str(exe), "--signatur", str(tmp_path / "fehlt.sig")]) == 1
        anders = tmp_path / "anders"
        anders.mkdir()
        (anders / "m.json").write_bytes(manifest.read_bytes())
        assert w.main(["pruefen", str(exe), "--manifest", str(anders / "m.json")]) == 0


# ---------------------------------------------------------------- verteilen


class TestVerteilen:
    def erwartet(self, exe: Path, manifest: Path, signatur: Path | None, version: str, trocken: bool) -> list[list[str]]:
        ordner = f"wamo-verteilung-eingang/{version}"
        aufrufe = [
            ssh(f"{SKRIPT} status --json"),
            ssh(f"mkdir -p -m 0700 ~/wamo-verteilung-eingang && rm -rf ~/{ordner} && mkdir -m 0700 ~/{ordner}"),
            scp(manifest, f"{ordner}/aktuell.json"),
        ]
        if signatur is not None:
            aufrufe.append(scp(signatur, f"{ordner}/aktuell.json.sig"))
        aufrufe += [
            scp(exe, f"{ordner}/WAIS-Setup-{version}.exe"),
            ssh(f"{SKRIPT} einsetzen ~/{ordner}" + (" --trocken" if trocken else "")),
            ssh(f"rm -rf ~/{ordner}"),
        ]
        return aufrufe

    def test_trocken_ruft_einsetzen_mit_trocken(self, tmp_path, server, monkeypatch):
        privat, oeffentlich = schluesselpaar()
        monkeypatch.setattr(w, "SCHLUESSEL_DATEI", schluessel_datei(tmp_path / "update-schluessel.json", oeffentlich))
        exe, manifest = bauen(tmp_path / "dist", privat=privat)
        server.status = {**LEER, "aktuell": stand("0.2.0"), "staende": ["0.2.0"], "schluesselliste": True}
        assert w.main(["verteilen", str(exe), "--trocken"]) == 0
        assert server.aufrufe == self.erwartet(exe, manifest, tmp_path / "dist" / "aktuell.json.sig", "0.3.0", trocken=True)

    def test_echt_ohne_trocken_und_unsigniert_beim_ersten_mal(self, tmp_path, server, ohne_schluesselliste):
        exe, manifest = bauen(tmp_path / "dist", "0.2.0")
        assert w.main(["verteilen", str(exe)]) == 0
        assert server.aufrufe == self.erwartet(exe, manifest, None, "0.2.0", trocken=False)

    def test_eigene_pfade_fuer_manifest_und_signatur(self, tmp_path, server, ohne_schluesselliste):
        privat, _ = schluesselpaar()
        exe, manifest = bauen(tmp_path / "dist", "0.10.0", privat=privat)
        anders = tmp_path / "anders"
        anders.mkdir()
        (anders / "m.json").write_bytes(manifest.read_bytes())
        (anders / "m.sig").write_bytes((tmp_path / "dist" / "aktuell.json.sig").read_bytes())
        server.status = {**LEER, "aktuell": stand("0.9.9")}
        assert w.main(["verteilen", str(exe), "--manifest", str(anders / "m.json"), "--signatur", str(anders / "m.sig")]) == 0
        assert server.aufrufe == self.erwartet(exe, anders / "m.json", anders / "m.sig", "0.10.0", trocken=False)

    @pytest.mark.parametrize("am_server", ["0.4.0", "0.3.0", "0.10.0"])
    def test_sinkende_oder_gleiche_version_bricht_vor_dem_kopieren_ab(self, tmp_path, server, ohne_schluesselliste, am_server, capsys):
        exe, _ = bauen(tmp_path, "0.3.0")
        server.status = {**LEER, "aktuell": stand(am_server)}
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == [ssh(f"{SKRIPT} status --json")], "nur der Status, kein scp und kein einsetzen"
        assert "nicht neuer" in capsys.readouterr().err

    def test_falsche_pruefsumme_bricht_ohne_jeden_serveraufruf_ab(self, tmp_path, server, ohne_schluesselliste):
        exe, _ = bauen(tmp_path, manifest_aendern=lambda d: d.update(sha256="0" * 64))
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == []

    def test_falsche_signatur_bricht_ohne_jeden_serveraufruf_ab(self, tmp_path, server, monkeypatch):
        privat, oeffentlich = schluesselpaar()
        monkeypatch.setattr(w, "SCHLUESSEL_DATEI", schluessel_datei(tmp_path / "update-schluessel.json", oeffentlich))
        exe, _ = bauen(tmp_path / "dist", privat=privat)
        sig = tmp_path / "dist" / "aktuell.json.sig"
        sig.write_bytes(base64.b64encode(privat.sign(b"anderes")) + b"\n")
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == []

    def test_fremder_schluessel_bricht_ohne_jeden_serveraufruf_ab(self, tmp_path, server, monkeypatch):
        privat, _ = schluesselpaar()
        _, fremd = schluesselpaar()
        monkeypatch.setattr(w, "SCHLUESSEL_DATEI", schluessel_datei(tmp_path / "update-schluessel.json", fremd))
        exe, _ = bauen(tmp_path / "dist", privat=privat)
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == []

    def test_schluesselliste_am_server_verlangt_eine_signatur(self, tmp_path, server, ohne_schluesselliste, capsys):
        exe, _ = bauen(tmp_path)
        server.status = {**LEER, "schluesselliste": True}
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == [ssh(f"{SKRIPT} status --json")]
        assert "Signatur" in capsys.readouterr().err

    @pytest.mark.parametrize("roh,rc", [
        (b"kein json", 0), (b"[]", 0), (json.dumps({**LEER, "v": True}).encode(), 0), (json.dumps({**LEER, "schluesselliste": "nein"}).encode(), 0),
        (json.dumps({**LEER, "aktuell": {"version": "0.3"}}).encode(), 0), (json.dumps({**LEER, "aktuell": "0.3.0"}).encode(), 0),
        (json.dumps(LEER).encode(), 1), (json.dumps({k: v for k, v in LEER.items() if k != "aktuell"}).encode(), 0),
    ])
    def test_ein_unklarer_status_bricht_vor_dem_kopieren_ab(self, tmp_path, server, ohne_schluesselliste, roh, rc):
        exe, _ = bauen(tmp_path)
        server.status_roh, server.rc_status = roh, rc
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == [ssh(f"{SKRIPT} status --json")]

    def test_scheitert_einsetzen_bleibt_der_eingang_liegen(self, tmp_path, server, ohne_schluesselliste):
        exe, manifest = bauen(tmp_path)
        server.rc_einsetzen = 1
        assert w.main(["verteilen", str(exe)]) == 1
        assert server.aufrufe == self.erwartet(exe, manifest, None, "0.3.0", trocken=False)[:-1], "kein rm nach einem Fehler"


# ---------------------------------------------------------------- status und rueckweg


@pytest.mark.parametrize("argv,befehl", [
    (["status"], f"{SKRIPT} status"),
    (["rueckweg"], f"{SKRIPT} rueckweg"),
    (["rueckweg", "--trocken"], f"{SKRIPT} rueckweg --trocken"),
    (["rueckweg", "--trocken", "--ohne-signatur"], f"{SKRIPT} rueckweg --trocken --ohne-signatur"),
])
def test_status_und_rueckweg_gehen_an_das_skript_am_server(server, argv, befehl):
    assert w.main(argv) == 0
    assert server.aufrufe == [ssh(befehl)]


@pytest.mark.parametrize("argv", [[], ["frech"], ["status", "--trocken"], ["verteilen"], ["manifest", "x.exe", "--commit", COMMIT],
                                  ["pruefen", "x.exe", "--trocken"]])
def test_falsche_aufrufe(server, argv):
    with pytest.raises(SystemExit) as e:
        w.main(argv)
    assert e.value.code == 2 and server.aufrufe == []


def test_zeitgrenzen_fuer_ssh_und_scp(monkeypatch, tmp_path):
    gesehen: list[float] = []

    def langsam(argv, **kw):
        gesehen.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 0)

    monkeypatch.setattr(w.subprocess, "run", langsam)
    assert w.main(["status"]) == 1
    with pytest.raises(w.Abbruch):
        w.scp(tmp_path / "x", "ziel")
    assert gesehen == [w.SSH_ZEIT, w.SCP_ZEIT]


def test_unsigniert_nur_ausdruecklich_wenn_die_schluesselliste_liegt(tmp_path, server, capsys):
    exe, _ = bauen(tmp_path)
    assert w.SCHLUESSEL_DATEI.exists(), "desktop/update-schluessel.json liegt im Repo"
    assert w.main(["pruefen", str(exe)]) == 1
    assert "--unsigniert" in capsys.readouterr().err
    assert w.main(["pruefen", str(exe), "--unsigniert"]) == 0
    assert "WARNUNG" in capsys.readouterr().err
    assert w.main(["verteilen", str(exe), "--trocken", "--unsigniert"]) == 0
    assert any(" einsetzen " in a[-1] and a[-1].endswith(" --trocken") for a in server.aufrufe if a[0] == "ssh")
