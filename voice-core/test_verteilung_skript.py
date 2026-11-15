"""Tests für die Ablage des Installers am Server (Paket P2, docs/ausrollen-neue-nutzer.md, Abschnitt 4.2):
infra/sokrates2/wamo_verteilung_manifest.py (Prüfregel des Manifests) und infra/sokrates2/wamo-verteilung-einrichten.sh.

Das Skript läuft hier NICHT gegen ein System. Es läuft im Probelauf (WAMO_VERTEILUNG_WURZEL) in einem Wegwerf-Ordner, ohne root, ohne chown und mit dem
Interpreter dieser Testumgebung. Signaturen entstehen mit cryptography (Ed25519), geprüft werden sie im Skript mit dem echten openssl. Das geht unter Linux und
mit Git Bash unter Windows (dort mit echten Symlinks über MSYS=winsymlinks:nativestrict). Rechte und Besitz prüft nur Linux. Was root, die Gruppe wamo-core,
den Herkunftsschutz mit fremdem Besitzer oder das Journal braucht, ist nur am Server prüfbar.

Ausführen:  python -m pytest -p no:cacheprovider -q test_verteilung_skript.py   (im Ordner voice-core/)
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

VOICE_CORE = Path(__file__).resolve().parent
REPO = VOICE_CORE.parent
INFRA = REPO / "infra" / "sokrates2"
SKRIPT = INFRA / "wamo-verteilung-einrichten.sh"
MODUL_PFAD = INFRA / "wamo_verteilung_manifest.py"
LINUX = sys.platform.startswith("linux")
COMMIT = "0123456789abcdef0123456789abcdef01234567"
BAUZEIT = "2026-11-20T10:00:00.000Z"
ENTFERNEN = object()


def _modul():
    spec = importlib.util.spec_from_file_location("wamo_verteilung_manifest", MODUL_PFAD)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


regel = _modul()


def _bash() -> str | None:
    kandidaten = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"] if os.name == "nt" else []
    kandidaten.append(shutil.which("bash") if os.name != "nt" else None)
    return next((k for k in kandidaten if k and Path(k).exists()), None)


BASH = _bash()


def _hat_openssl() -> bool:
    if BASH is None:
        return False
    r = subprocess.run([BASH, "-c", "openssl version"], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.startswith("OpenSSL 3")


OPENSSL = _hat_openssl()
braucht_bash = pytest.mark.skipif(BASH is None, reason="bash fehlt")
braucht_openssl = pytest.mark.skipif(not OPENSSL, reason="openssl 3 fehlt in der Bash")
braucht_linux = pytest.mark.skipif(not LINUX, reason="Dateirechte und Besitz nur unter Linux prüfbar")


def lies(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def code(text: str) -> str:
    """Das Skript ohne Kommentarzeilen."""
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


def sha(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def manifest_daten(version: str = "0.3.0", inhalt: bytes = b"MZ installer", **aenderungen) -> dict:
    d = {"v": 1, "produkt": "wais-desktop", "version": version, "datei": f"WAIS-Setup-{version}.exe", "groesse": len(inhalt),
         "sha256": sha(inhalt), "bauzeit": BAUZEIT, "commit": COMMIT}
    for name, wert in aenderungen.items():
        if wert is ENTFERNEN:
            d.pop(name, None)
        else:
            d[name] = wert
    return d


def manifest_roh(version: str = "0.3.0", inhalt: bytes = b"MZ installer", **aenderungen) -> bytes:
    return json.dumps(manifest_daten(version, inhalt, **aenderungen), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- Schlüssel (cryptography, im voice-core-venv vorhanden)


def schluesselpaar():
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    ser = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    privat = ed.Ed25519PrivateKey.generate()
    roh = privat.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    return privat, roh


def signatur_text(privat, daten: bytes) -> bytes:
    return base64.b64encode(privat.sign(daten)) + b"\n"


def schluesselliste(*oeffentlich: bytes) -> bytes:
    return json.dumps([base64.b64encode(k).decode("ascii") for k in oeffentlich]).encode("utf-8")


# ---------------------------------------------------------------- Prüfregel (Modul)


class TestManifest:
    def test_das_beispiel_ist_gueltig(self):
        roh = manifest_roh()
        d = regel.manifest_pruefen(roh)
        assert d["version"] == "0.3.0" and d["datei"] == "WAIS-Setup-0.3.0.exe" and d["groesse"] == len(b"MZ installer")
        assert tuple(d) == regel.SCHLUESSEL
        beispiel = ('{"v":1,"produkt":"wais-desktop","version":"0.3.0","datei":"WAIS-Setup-0.3.0.exe","groesse":123,"sha256":"' + "a" * 64
                    + '","bauzeit":"2026-11-20T10:00:00.000Z","commit":"' + "b" * 40 + '"}')
        assert regel.manifest_pruefen(beispiel.encode("utf-8"))["groesse"] == 123

    def test_leerzeichen_und_zeilenende_aussen_sind_erlaubt(self):
        assert regel.manifest_pruefen(manifest_roh() + b"\n")["version"] == "0.3.0"

    @pytest.mark.parametrize("roh", [
        b"",
        b"\xef\xbb\xbf" + manifest_roh(),                                   # BOM
        manifest_roh() + b" " * 4096,                                       # größer als 4096 Byte
        b"[" + manifest_roh() + b"]",                                       # kein Objekt
        manifest_roh() + manifest_roh(),                                    # zwei Objekte
        manifest_roh()[:-1],                                                # abgeschnitten
        manifest_roh().replace(b"wais-desktop", b"wais-d\xe9sktop"),        # kein UTF-8
        manifest_roh().replace(b'"v":1', b'"v":1,"v":1'),                   # doppelter Schlüssel
        manifest_roh().replace(b'"v":1', b'"v":NaN'),                       # Konstante
        b"[" * 3000 + b"]" * 3000,                                          # tief verschachtelt
    ])
    def test_ungueltige_bytes(self, roh):
        with pytest.raises(ValueError):
            regel.manifest_pruefen(roh)

    @pytest.mark.parametrize("aenderung", [
        {"extra": "x"},
        {"signatur": "abc"},
        {"bauzeit": ENTFERNEN},
        {"commit": ENTFERNEN},
        {"v": True}, {"v": 1.0}, {"v": "1"}, {"v": 2}, {"v": 0},
        {"produkt": "wais"}, {"produkt": "WAIS-desktop"}, {"produkt": 1},
        {"version": "01.0.0"}, {"version": "1.2"}, {"version": "1.2.3.4"}, {"version": "12345.0.0"}, {"version": "v1.2.3"},
        {"version": "1.2.3\n"}, {"version": "1.2.\u0663"}, {"version": "1.2.3-rc1"}, {"version": 3},
        {"datei": "WAIS-Setup-0.3.1.exe"}, {"datei": "../WAIS-Setup-0.3.0.exe"}, {"datei": "wais-setup-0.3.0.exe"},
        {"groesse": 0}, {"groesse": -1}, {"groesse": 536870913}, {"groesse": True}, {"groesse": 12.0}, {"groesse": "12"},
        {"sha256": "A" * 64}, {"sha256": "a" * 63}, {"sha256": "a" * 65}, {"sha256": "g" * 64}, {"sha256": "a" * 64 + "\n"},
        {"bauzeit": "2026-11-20T10:00:00"}, {"bauzeit": "2026-11-20 10:00:00Z"}, {"bauzeit": "2026-11-20T10:00:00.1234Z"},
        {"bauzeit": "2026-11-20T10:00:00+01:00"}, {"bauzeit": "2026-11-20T10:00:00Z\n"}, {"bauzeit": "\u0662026-11-20T10:00:00Z"},
        {"commit": "0" * 39}, {"commit": "0" * 41}, {"commit": COMMIT.upper()},
    ], ids=lambda a: repr(a)[:50])
    def test_ungueltige_felder(self, aenderung):
        with pytest.raises(ValueError):
            regel.manifest_pruefen(manifest_roh(**aenderung))

    def test_grenzen_und_formen_die_gelten(self):
        for version in ("0.0.0", "9999.9999.9999", "0.10.0", "1.2.3"):
            regel.manifest_pruefen(manifest_roh(version))
        regel.manifest_pruefen(manifest_roh(groesse=536870912))
        for bauzeit in ("2026-11-20T10:00:00Z", "2026-11-20T10:00:00.1Z", "2026-11-20T10:00:00.12Z"):
            regel.manifest_pruefen(manifest_roh(bauzeit=bauzeit))

    def test_die_fehlermeldung_ist_ein_deutscher_satz_ohne_rohe_steuerzeichen(self):
        with pytest.raises(ValueError) as e:
            regel.manifest_pruefen(manifest_roh(**{"\x1b[31mfrech": 1}))
        assert "\x1b" not in str(e.value) and str(e.value).endswith(".")

    def test_versionen_werden_je_teil_numerisch_verglichen(self):
        assert regel.version_tupel("0.10.0") == (0, 10, 0)
        assert regel.version_groesser("0.10.0", "0.9.9")
        assert regel.version_groesser("1.0.0", "0.9999.9999")
        assert not regel.version_groesser("0.3.0", "0.3.0")
        assert not regel.version_groesser("0.2.9", "0.3.0")
        for schlecht in ("1.2", "01.2.3", "a.b.c", "", "1.2.3 ", None):
            with pytest.raises(ValueError):
                regel.version_tupel(schlecht)


class TestSignaturUndSchluessel:
    def test_signatur_mit_und_ohne_zeilenende(self):
        roh = bytes(range(64))
        text = base64.b64encode(roh)
        assert regel.signatur_lesen(text) == roh
        assert regel.signatur_lesen(text + b"\n") == roh

    @pytest.mark.parametrize("text", [
        base64.b64encode(bytes(64)) + b"\r\n",
        base64.b64encode(bytes(64)) + b"\n\n",
        base64.b64encode(bytes(63)),
        base64.b64encode(bytes(65)),
        base64.urlsafe_b64encode(bytes([0xFB] * 64)),
        base64.b64encode(bytes(64)).rstrip(b"="),
        b" " + base64.b64encode(bytes(64)),
        base64.b64encode(bytes(64))[:-3] + b"B==",                    # nicht kanonisch (Füllbits gesetzt)
        b"",
    ])
    def test_ungueltige_signaturen(self, text):
        with pytest.raises(ValueError):
            regel.signatur_lesen(text)

    def test_schluesselliste(self):
        a, b = bytes(range(32)), bytes(range(1, 33))
        assert regel.schluessel_lesen(schluesselliste(a, b)) == [a, b]

    @pytest.mark.parametrize("roh", [
        b"[]", b"{}", b'"abc"', b"", b"\xef\xbb\xbf" + schluesselliste(bytes(32)),
        json.dumps([base64.b64encode(bytes(31)).decode()]).encode(),
        json.dumps([base64.b64encode(bytes(33)).decode()]).encode(),
        json.dumps([1]).encode(),
        json.dumps([base64.b64encode(bytes(32)).decode() + "\n"]).encode(),
        json.dumps([base64.b64encode(bytes(32)).decode()] * 17).encode(),
    ])
    def test_ungueltige_schluessellisten(self, roh):
        with pytest.raises(ValueError):
            regel.schluessel_lesen(roh)

    def test_pem_hat_das_der_praefix_fuer_ed25519(self):
        pem = regel.pem_text(bytes(range(32)))
        assert pem.startswith("-----BEGIN PUBLIC KEY-----\n") and pem.endswith("\n-----END PUBLIC KEY-----\n")
        der = base64.b64decode("".join(pem.splitlines()[1:-1]))
        assert der == bytes.fromhex("302a300506032b6570032100") + bytes(range(32))

    def test_pem_wird_von_cryptography_als_ed25519_gelesen(self):
        privat, oeffentlich = schluesselpaar()
        ser = pytest.importorskip("cryptography.hazmat.primitives.serialization")
        geladen = ser.load_pem_public_key(regel.pem_text(oeffentlich).encode("ascii"))
        geladen.verify(privat.sign(b"x"), b"x")


class TestKommandozeile:
    def lauf(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", "-B", str(MODUL_PFAD), *map(str, args)], capture_output=True)

    def test_pruefen_version_und_stand(self, tmp_path):
        inhalt = b"MZ" + bytes(5000)
        (tmp_path / "aktuell.json").write_bytes(manifest_roh("0.3.0", inhalt))
        (tmp_path / "WAIS-Setup-0.3.0.exe").write_bytes(inhalt)
        r = self.lauf("pruefen", tmp_path / "aktuell.json", tmp_path / "WAIS-Setup-0.3.0.exe")
        assert r.returncode == 0, r.stderr.decode("utf-8")
        r = self.lauf("version", tmp_path / "aktuell.json")
        assert r.returncode == 0 and r.stdout == b"0.3.0\n"  # nur LF, auch unter Windows
        r = self.lauf("stand", tmp_path)
        assert r.stdout.decode("ascii") == f"0.3.0 {sha(inhalt)} {len(inhalt)} {COMMIT} ok\n"
        (tmp_path / "WAIS-Setup-0.3.0.exe").write_bytes(inhalt[:-1] + b"X")
        assert self.lauf("stand", tmp_path).stdout.decode("ascii").endswith(" abweichend\n")
        assert self.lauf("pruefen", tmp_path / "aktuell.json", tmp_path / "WAIS-Setup-0.3.0.exe").returncode == 1
        (tmp_path / "WAIS-Setup-0.3.0.exe").unlink()
        assert self.lauf("stand", tmp_path).stdout.decode("ascii").endswith(" fehlt\n")

    def test_pruefen_nennt_den_grund_auf_deutsch(self, tmp_path):
        (tmp_path / "aktuell.json").write_bytes(manifest_roh("0.3.0", b"abc"))
        (tmp_path / "WAIS-Setup-0.3.0.exe").write_bytes(b"abd")
        r = self.lauf("pruefen", tmp_path / "aktuell.json", tmp_path / "WAIS-Setup-0.3.0.exe")
        assert r.returncode == 1 and "SHA-256" in r.stderr.decode("utf-8")
        (tmp_path / "WAIS-Setup-0.3.0.exe").write_bytes(b"abcd")
        r = self.lauf("pruefen", tmp_path / "aktuell.json", tmp_path / "WAIS-Setup-0.3.0.exe")
        assert r.returncode == 1 and "Größe" in r.stderr.decode("utf-8")
        (tmp_path / "WAIS-Setup-0.3.1.exe").write_bytes(b"abc")
        r = self.lauf("pruefen", tmp_path / "aktuell.json", tmp_path / "WAIS-Setup-0.3.1.exe")
        assert r.returncode == 1 and "Dateiname" in r.stderr.decode("utf-8")

    def test_vergleich_und_sortieren(self):
        assert self.lauf("vergleich", "0.10.0", "0.9.9").stdout == b"groesser\n"
        assert self.lauf("vergleich", "0.3.0", "0.3.0").stdout == b"gleich\n"
        assert self.lauf("vergleich", "0.2.0", "0.3.0").stdout == b"kleiner\n"
        assert self.lauf("vergleich", "0.2", "0.3.0").returncode == 1
        assert self.lauf("sortieren", "0.2.0", "0.10.0", "0.9.0").stdout == b"0.10.0\n0.9.0\n0.2.0\n"

    def test_signatur_und_pem(self, tmp_path):
        (tmp_path / "s.sig").write_bytes(base64.b64encode(bytes(range(64))) + b"\n")
        assert self.lauf("signatur", tmp_path / "s.sig", tmp_path / "s.bin").returncode == 0
        assert (tmp_path / "s.bin").read_bytes() == bytes(range(64))
        (tmp_path / "k.json").write_bytes(schluesselliste(bytes(32), bytes(range(32))))
        (tmp_path / "pem").mkdir()
        r = self.lauf("pem", tmp_path / "k.json", tmp_path / "pem")
        assert r.returncode == 0 and r.stdout == b"2\n"
        assert sorted(p.name for p in (tmp_path / "pem").iterdir()) == ["schluessel-1.pem", "schluessel-2.pem"]
        assert (tmp_path / "pem" / "schluessel-2.pem").read_text(encoding="ascii") == regel.pem_text(bytes(range(32)))

    def test_falsche_aufrufe(self):
        for args in ((), ("frech",), ("version",), ("vergleich", "1.0.0"), ("pruefen", "a")):
            assert self.lauf(*args).returncode == 2, args

    def test_der_link_als_manifest_wird_abgelehnt(self, tmp_path):
        (tmp_path / "echt.json").write_bytes(manifest_roh())
        try:
            os.symlink(tmp_path / "echt.json", tmp_path / "aktuell.json")
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks sind auf dieser Maschine nicht erlaubt")
        assert self.lauf("version", tmp_path / "aktuell.json").returncode == 1

    def test_nur_standardbibliothek(self):
        text = lies(MODUL_PFAD)
        importe = set(re.findall(r"^(?:import|from) ([a-zA-Z_][\w.]*)", text, re.M))
        assert importe <= {"__future__", "base64", "hashlib", "json", "os", "re", "stat", "sys"}, importe


# ---------------------------------------------------------------- Textprüfungen des Skripts


@pytest.fixture(scope="module")
def text() -> str:
    return lies(SKRIPT)


def test_zeilenenden_lf_keine_gedankenstriche_kein_eval(text):
    for pfad in (SKRIPT, MODUL_PFAD):
        roh = pfad.read_bytes()
        assert b"\r" not in roh, pfad.name
        for strich in (chr(0x2014), chr(0x2013)):
            assert strich not in roh.decode("utf-8"), pfad.name
    assert text.startswith("#!/usr/bin/env bash\n") and "set -euo pipefail" in text
    assert not re.search(r"\beval\b", code(text))
    assert "sh -c" not in code(text) and "source " not in code(text)


@braucht_bash
def test_bash_n():
    r = subprocess.run([BASH, "-n", str(SKRIPT)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck nicht vorhanden")
def test_shellcheck():
    r = subprocess.run(["shellcheck", "-S", "warning", str(SKRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_feste_orte_python_isoliert_und_openssl_fuer_die_signatur(text):
    ohne = code(text)
    assert 'BASIS="$WURZEL/var/lib/wamo-verteilung"' in ohne
    assert 'SCHLUESSEL="$WURZEL/etc/wamo-verteilung/update-schluessel.json"' in ohne
    assert "PYTHON=/usr/bin/python3" in ohne and "PY_OPT=(-X utf8 -B -I)" in ohne
    assert "openssl pkeyutl -verify -pubin" in ohne and "-rawin" in ohne
    assert "logger -t wamo-verteilung" in ohne and "flock -n" in ohne
    assert "mv -T" in ohne and "head -c \"$((MAX_GROESSE + 1))\"" in ohne
    for verboten in ("systemctl", "docker", "restart", "wamo-core-env"):
        assert verboten not in ohne, verboten  # nichts wird neu gestartet, der Kern bekommt keine Einstellung


def test_nur_root_und_der_herkunftsschutz_kommen_vor_jedem_zugriff(text):
    root = text.index('[ "$(id -u)" -eq 0 ] || fehler "Bitte als root ausführen (sudo)."')
    herkunft = text.index("\n  pruefe_herkunft\n")
    befehle = text.index('case "$BEFEHL" in\n  einsetzen) einsetzen ;;')
    assert root < herkunft < befehle
    funktion = re.search(r"^pruefe_herkunft\(\) \{.*?^\}", text, re.M | re.S).group(0)
    for muss in ("-type l", "8#022", "SUDO_UID", "Unsicherer Ablageort"):
        assert muss in funktion, muss


# ---------------------------------------------------------------- Probelauf


class Welt:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.w = ordner / "w"
        self.infra = ordner / "infra"
        self.basis = self.w / "var" / "lib" / "wamo-verteilung"
        self.staende = self.basis / "staende"
        self.schluessel_datei = self.w / "etc" / "wamo-verteilung" / "update-schluessel.json"
        self.att = ordner / "att"
        self.journal = ordner / "journal.log"

    def bash_pfad(self, pfad: Path) -> str:
        """Der Pfad so, wie ihn die Bash sieht (unter Windows liegt der Temp-Ordner unter /tmp)."""
        if os.name == "nt":
            return "/tmp/" + pfad.relative_to(Path(tempfile.gettempdir())).as_posix()
        return str(pfad)

    def lauf(self, *args: str, extra: dict | None = None, wurzel: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "WAMO_VERTEILUNG_PYTHON": Path(sys.executable).as_posix(), "MSYS": "winsymlinks:nativestrict",
               "PATH": f"{self.att}{os.pathsep}{os.environ['PATH']}", "JOURNAL_LOG": self.bash_pfad(self.journal)}
        if wurzel:
            env["WAMO_VERTEILUNG_WURZEL"] = self.bash_pfad(self.w)
        else:
            env.pop("WAMO_VERTEILUNG_WURZEL", None)
        env.update(extra or {})
        return subprocess.run([BASH, self.bash_pfad(self.infra / SKRIPT.name), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=180)

    @staticmethod
    def ausgabe(r: subprocess.CompletedProcess) -> str:
        return r.stdout + r.stderr

    def lieferung(self, version: str = "0.3.0", inhalt: bytes | None = None, *, manifest: bytes | None = None, signatur: bytes | None = None,
                  exe_name: str | None = None, name: str | None = None) -> str:
        """Ein Eingangsordner wie nach dem Kopieren mit scp: aktuell.json, optional aktuell.json.sig, die exe."""
        inhalt = inhalt if inhalt is not None else f"MZ Installer {version}".encode("ascii") + bytes(2000)
        ordner = self.ordner / "eingang" / (name or version)
        ordner.mkdir(parents=True)
        (ordner / "aktuell.json").write_bytes(manifest if manifest is not None else manifest_roh(version, inhalt))
        (ordner / (exe_name or f"WAIS-Setup-{version}.exe")).write_bytes(inhalt)
        if signatur is not None:
            (ordner / "aktuell.json.sig").write_bytes(signatur)
        return self.bash_pfad(ordner)

    def signierte_lieferung(self, privat, version: str = "0.3.0", inhalt: bytes | None = None) -> str:
        inhalt = inhalt if inhalt is not None else f"MZ signiert {version}".encode("ascii") + bytes(1000)
        roh = manifest_roh(version, inhalt)
        return self.lieferung(version, inhalt, manifest=roh, signatur=signatur_text(privat, roh))

    def schluessel_setzen(self, *oeffentlich: bytes) -> None:
        self.schluessel_datei.parent.mkdir(parents=True, exist_ok=True)
        self.schluessel_datei.write_bytes(schluesselliste(*oeffentlich))

    def zustand(self) -> dict[str, object]:
        """Alles unter der Ablage: Links mit Ziel, Dateien mit Inhalt, Ordner (ohne Links zu folgen)."""
        aus: dict[str, object] = {}
        if not self.basis.exists() and not self.basis.is_symlink():
            return aus

        def gehen(ordner: Path) -> None:
            for e in sorted(os.scandir(ordner), key=lambda e: e.name):
                rel = Path(e.path).relative_to(self.basis).as_posix()
                if e.is_symlink():
                    aus[rel] = ("link", os.readlink(e.path).replace("\\", "/"))
                elif e.is_dir():
                    aus[rel] = ("ordner",)
                    gehen(Path(e.path))
                else:
                    aus[rel] = ("datei", Path(e.path).read_bytes())

        gehen(self.basis)
        return aus

    def link(self, name: str) -> str | None:
        p = self.basis / name
        return os.readlink(p).replace("\\", "/") if p.is_symlink() else None

    def staende_namen(self) -> list[str]:
        return sorted(p.name for p in self.staende.iterdir()) if self.staende.is_dir() else []

    def journal_zeilen(self) -> list[str]:
        return lies(self.journal).splitlines() if self.journal.exists() else []


@pytest.fixture
def welt():
    ordner = Path(tempfile.mkdtemp(prefix="wamo-verteilung-probe-"))
    w = Welt(ordner)
    w.infra.mkdir()
    shutil.copy2(SKRIPT, w.infra / SKRIPT.name)
    shutil.copy2(MODUL_PFAD, w.infra / MODUL_PFAD.name)
    (w.w / "var" / "tmp").mkdir(parents=True)
    w.att.mkdir()
    logger = w.att / "logger"  # schreibt die Zeile für das Journal in ein Protokoll außerhalb der Wurzel
    logger.write_bytes(b'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$JOURNAL_LOG"\n')
    logger.chmod(0o755)
    try:
        yield w
        reste = list((w.w / "var" / "tmp").glob("*"))
        assert not reste, f"der Zwischenordner bleibt liegen: {reste}"
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def flock_attrappe(welt: Welt, belegt: bool) -> None:
    datei = welt.att / "flock"
    datei.write_bytes(b"#!/bin/sh\nexit 1\n" if belegt else b"#!/bin/sh\nexit 0\n")
    datei.chmod(0o755)


@braucht_bash
class TestEinsetzen:
    def test_einsetzen_unsigniert_ohne_schluesselliste_mit_warnung(self, welt):
        eingang = welt.lieferung("0.2.0")
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 0, welt.ausgabe(r)
        assert "WARNUNG" in r.stderr and "unsigniert" in r.stderr
        assert welt.staende_namen() == ["0.2.0"]
        assert sorted(p.name for p in (welt.staende / "0.2.0").iterdir()) == ["WAIS-Setup-0.2.0.exe", "aktuell.json"]
        quelle = welt.ordner / "eingang" / "0.2.0"
        for name in ("aktuell.json", "WAIS-Setup-0.2.0.exe"):
            assert (welt.staende / "0.2.0" / name).read_bytes() == (quelle / name).read_bytes()
        assert welt.link("aktuell") == "staende/0.2.0" and welt.link("vorher") is None
        assert (welt.basis / "aktuell" / "aktuell.json").read_bytes() == (quelle / "aktuell.json").read_bytes()
        (zeile,) = welt.journal_zeilen()
        assert zeile.startswith("-t wamo-verteilung") and "einsetzen" in zeile and "version=0.2.0" in zeile and "signatur=keine" in zeile
        assert not [p for p in welt.basis.iterdir() if p.name.startswith(".")], "keine Zwischenreste in der Ablage"

    @braucht_openssl
    def test_einsetzen_signiert_mit_schluesselliste_und_vorher(self, welt):
        privat, oeffentlich = schluesselpaar()
        _, anderer = schluesselpaar()
        welt.schluessel_setzen(anderer, oeffentlich)  # passt zu irgendeinem Schlüssel der Liste
        assert welt.lauf("einsetzen", welt.signierte_lieferung(privat, "0.3.0")).returncode == 0
        r = welt.lauf("einsetzen", welt.signierte_lieferung(privat, "0.10.0"))
        assert r.returncode == 0, welt.ausgabe(r)
        assert "WARNUNG" not in welt.ausgabe(r) and "gültig" in r.stdout
        assert welt.link("aktuell") == "staende/0.10.0" and welt.link("vorher") == "staende/0.3.0"
        assert sorted(p.name for p in (welt.staende / "0.10.0").iterdir()) == ["WAIS-Setup-0.10.0.exe", "aktuell.json", "aktuell.json.sig"]
        assert "signatur=gueltig" in welt.journal_zeilen()[-1] and "vorher=0.3.0" in welt.journal_zeilen()[-1]

    def test_falsche_pruefsumme(self, welt):
        inhalt = b"MZ" + bytes(100)
        eingang = welt.lieferung("0.3.0", inhalt, manifest=manifest_roh("0.3.0", inhalt, sha256="f" * 64))
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 1 and "SHA-256" in welt.ausgabe(r) and "Nichts wurde geändert" in welt.ausgabe(r)
        assert welt.zustand() == {} and welt.journal_zeilen() == []

    def test_falsche_groesse(self, welt):
        inhalt = b"MZ" + bytes(100)
        eingang = welt.lieferung("0.3.0", inhalt, manifest=manifest_roh("0.3.0", inhalt, groesse=103))
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 1 and "Größe" in welt.ausgabe(r) and welt.zustand() == {}

    def test_falscher_dateiname(self, welt):
        eingang = welt.lieferung("0.3.0", exe_name="WAIS-Setup-0.3.1.exe")
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 1 and "Dateiname" in welt.ausgabe(r) and welt.zustand() == {}

    def test_manifest_mit_zusatzfeld(self, welt):
        inhalt = b"MZ" + bytes(10)
        eingang = welt.lieferung("0.3.0", inhalt, manifest=manifest_roh("0.3.0", inhalt, kanal="beta"))
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 1 and "Unbekannte Felder" in welt.ausgabe(r) and welt.zustand() == {}

    def test_sinkende_und_gleiche_version(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        vorher = welt.zustand()
        for version, name in (("0.2.9", None), ("0.3.0", "0.3.0-nochmal")):
            r = welt.lauf("einsetzen", welt.lieferung(version, name=name))
            assert r.returncode == 1, welt.ausgabe(r)
            assert "nicht neuer als der aktuelle Stand 0.3.0" in welt.ausgabe(r)
            assert welt.zustand() == vorher
        assert len(welt.journal_zeilen()) == 1

    @braucht_openssl
    def test_signatur_ist_pflicht_bei_vorhandener_schluesselliste(self, welt):
        _, oeffentlich = schluesselpaar()
        welt.schluessel_setzen(oeffentlich)
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0"))
        assert r.returncode == 1 and "Signatur" in welt.ausgabe(r) and "Pflicht" in welt.ausgabe(r)
        assert welt.zustand() == {}

    @braucht_openssl
    def test_falsche_signatur(self, welt):
        privat, oeffentlich = schluesselpaar()
        welt.schluessel_setzen(oeffentlich)
        inhalt = b"MZ" + bytes(10)
        roh = manifest_roh("0.3.0", inhalt)
        eingang = welt.lieferung("0.3.0", inhalt, manifest=roh, signatur=signatur_text(privat, roh + b" "))
        r = welt.lauf("einsetzen", eingang)
        assert r.returncode == 1 and "passt zu keinem Schlüssel" in welt.ausgabe(r) and welt.zustand() == {}

    @braucht_openssl
    def test_fremder_schluessel(self, welt):
        privat, _ = schluesselpaar()
        _, oeffentlich = schluesselpaar()
        welt.schluessel_setzen(oeffentlich)
        r = welt.lauf("einsetzen", welt.signierte_lieferung(privat))
        assert r.returncode == 1 and "passt zu keinem Schlüssel" in welt.ausgabe(r) and welt.zustand() == {}

    def test_kaputte_signaturdatei_wird_auch_ohne_schluesselliste_abgelehnt(self, welt):
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0", signatur=b"keine-signatur\n"))
        assert r.returncode == 1 and "Signatur" in welt.ausgabe(r) and welt.zustand() == {}

    def test_signiert_ohne_schluesselliste_geht_mit_warnung_durch(self, welt):
        privat, _ = schluesselpaar()
        r = welt.lauf("einsetzen", welt.signierte_lieferung(privat))
        assert r.returncode == 0, welt.ausgabe(r)
        assert "WARNUNG" in r.stderr and "nicht geprüft" in r.stderr
        assert (welt.staende / "0.3.0" / "aktuell.json.sig").is_file()

    def test_kaputte_schluesselliste_haelt_alles_an(self, welt):
        welt.schluessel_datei.parent.mkdir(parents=True)
        welt.schluessel_datei.write_bytes(b"[]")
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0"))
        assert r.returncode == 1 and "Schlüsselliste" in welt.ausgabe(r) and welt.zustand() == {}

    def test_trocken_aendert_nichts(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        vorher, journal = welt.zustand(), welt.journal_zeilen()
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0"), "--trocken")
        assert r.returncode == 0, welt.ausgabe(r)
        assert "[trocken]" in r.stdout and "Trockenlauf: es wurde nichts geändert." in r.stdout
        assert welt.zustand() == vorher and welt.journal_zeilen() == journal
        r = welt.lauf("einsetzen", welt.lieferung("0.1.0"), "--trocken")  # auch der Trockenlauf prüft die Version
        assert r.returncode == 1 and welt.zustand() == vorher

    def test_trocken_beim_ersten_mal_legt_keine_ablage_an(self, welt):
        r = welt.lauf("einsetzen", welt.lieferung("0.2.0"), "--trocken")
        assert r.returncode == 0, welt.ausgabe(r)
        assert not welt.basis.exists()

    def test_aufraeumen_auf_drei_staende(self, welt):
        for version in ("0.2.0", "0.3.0", "0.4.0"):
            assert welt.lauf("einsetzen", welt.lieferung(version)).returncode == 0
        assert welt.staende_namen() == ["0.2.0", "0.3.0", "0.4.0"]
        r = welt.lauf("einsetzen", welt.lieferung("0.10.0"))
        assert r.returncode == 0, welt.ausgabe(r)
        assert welt.staende_namen() == ["0.10.0", "0.3.0", "0.4.0"]
        assert welt.link("aktuell") == "staende/0.10.0" and welt.link("vorher") == "staende/0.4.0"
        assert "0.2.0" in r.stdout and "entfernt" in r.stdout

    def test_symlink_im_eingang_wird_abgelehnt(self, welt):
        geheim = welt.ordner / "geheim.txt"
        geheim.write_text("GEHEIMER-WERT", encoding="utf-8")
        eingang = welt.ordner / "eingang" / "0.3.0"
        welt.lieferung("0.3.0")
        (eingang / "WAIS-Setup-0.3.0.exe").unlink()
        try:
            os.symlink(geheim, eingang / "WAIS-Setup-0.3.0.exe")
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks sind auf dieser Maschine nicht erlaubt")
        r = welt.lauf("einsetzen", welt.bash_pfad(eingang))
        assert r.returncode == 1 and "keine reguläre Datei" in welt.ausgabe(r)
        assert "GEHEIMER-WERT" not in welt.ausgabe(r) and welt.zustand() == {}

    def test_eingang_als_symlink_wird_abgelehnt(self, welt):
        welt.lieferung("0.3.0")
        link = welt.ordner / "eingang" / "link"
        try:
            os.symlink(welt.ordner / "eingang" / "0.3.0", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks sind auf dieser Maschine nicht erlaubt")
        r = welt.lauf("einsetzen", welt.bash_pfad(link))
        assert r.returncode == 1 and "Link" in welt.ausgabe(r) and welt.zustand() == {}

    @pytest.mark.parametrize("fremd", ["notiz.txt", ".versteckt", "WAIS-Setup-0.2.0.exe", "unterordner"])
    def test_fremde_dateien_im_eingang_werden_abgelehnt(self, welt, fremd):
        eingang = welt.ordner / "eingang" / "0.3.0"
        welt.lieferung("0.3.0")
        if fremd == "unterordner":
            (eingang / fremd).mkdir()
        else:
            (eingang / fremd).write_bytes(b"x")
        r = welt.lauf("einsetzen", welt.bash_pfad(eingang))
        assert r.returncode == 1 and welt.zustand() == {}
        assert "Fremde Datei" in welt.ausgabe(r) or "keine reguläre Datei" in welt.ausgabe(r)

    def test_fehlende_dateien_im_eingang(self, welt):
        eingang = welt.ordner / "eingang" / "0.3.0"
        welt.lieferung("0.3.0")
        (eingang / "aktuell.json").unlink()
        r = welt.lauf("einsetzen", welt.bash_pfad(eingang))
        assert r.returncode == 1 and "aktuell.json" in welt.ausgabe(r)
        r = welt.lauf("einsetzen", welt.bash_pfad(welt.ordner / "gibt-es-nicht"))
        assert r.returncode == 1 and welt.zustand() == {}

    def test_ein_vorhandener_stand_mit_gleicher_pruefsumme_wird_wiederverwendet(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        assert welt.lauf("rueckweg").returncode == 0
        vorher_inhalt = (welt.staende / "0.3.0" / "WAIS-Setup-0.3.0.exe").read_bytes()
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0", name="0.3.0-wieder"))
        assert r.returncode == 0, welt.ausgabe(r)
        assert "wiederverwendet" in r.stdout
        assert welt.link("aktuell") == "staende/0.3.0" and welt.link("vorher") == "staende/0.2.0"
        assert (welt.staende / "0.3.0" / "WAIS-Setup-0.3.0.exe").read_bytes() == vorher_inhalt

    def test_ein_vorhandener_stand_mit_anderem_inhalt_bricht_ab(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        assert welt.lauf("rueckweg").returncode == 0
        vorher = welt.zustand()
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0", b"MZ anders" + bytes(10), name="0.3.0-anders"))
        assert r.returncode == 1 and "anderem Inhalt" in welt.ausgabe(r) and welt.zustand() == vorher

    def test_eine_belegte_sperre_haelt_den_lauf_an(self, welt):
        flock_attrappe(welt, belegt=True)
        r = welt.lauf("einsetzen", welt.lieferung("0.3.0"))
        assert r.returncode == 1 and "Sperre" in welt.ausgabe(r) and not welt.staende.exists()
        r = welt.lauf("rueckweg")
        assert r.returncode == 1 and "Sperre" in welt.ausgabe(r)

    @braucht_linux
    def test_rechte_ordner_0750_dateien_0640_links_relativ(self, welt):
        privat, _ = schluesselpaar()
        assert welt.lauf("einsetzen", welt.signierte_lieferung(privat, "0.3.0")).returncode == 0
        for ordner in (welt.basis, welt.staende, welt.staende / "0.3.0"):
            assert stat.S_IMODE(ordner.stat().st_mode) == 0o750, ordner
        for datei in (welt.staende / "0.3.0").iterdir():
            assert stat.S_IMODE(datei.lstat().st_mode) == 0o640, datei
        assert os.readlink(welt.basis / "aktuell") == "staende/0.3.0"


@braucht_bash
class TestRueckwegUndStatus:
    def test_rueckweg_stellt_vorher_her_und_danach_gibt_es_kein_vorher(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        r = welt.lauf("rueckweg")
        assert r.returncode == 0, welt.ausgabe(r)
        assert welt.link("aktuell") == "staende/0.2.0" and welt.link("vorher") is None
        assert welt.staende_namen() == ["0.2.0", "0.3.0"], "der Rückweg löscht keinen Stand"
        assert "rueckweg" in welt.journal_zeilen()[-1] and "aktuell=0.2.0" in welt.journal_zeilen()[-1]
        r = welt.lauf("rueckweg")
        assert r.returncode == 3 and "kein voriger Stand" in welt.ausgabe(r)

    def test_rueckweg_trocken_aendert_nichts(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        vorher = welt.zustand()
        r = welt.lauf("rueckweg", "--trocken")
        assert r.returncode == 0 and "[trocken]" in r.stdout and welt.zustand() == vorher

    def test_rueckweg_ohne_ablage(self, welt):
        r = welt.lauf("rueckweg")
        assert r.returncode == 3 and "kein voriger Stand" in welt.ausgabe(r)

    def test_rueckweg_auf_einen_beschaedigten_stand_bricht_ab(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        (welt.staende / "0.2.0" / "WAIS-Setup-0.2.0.exe").write_bytes(b"kaputt")
        vorher = welt.zustand()
        r = welt.lauf("rueckweg")
        assert r.returncode == 1 and welt.zustand() == vorher

    def test_rueckweg_auf_unsignierten_stand_nur_bewusst_wenn_die_liste_liegt(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0")).returncode == 0
        privat, oeffentlich = schluesselpaar()
        welt.schluessel_setzen(oeffentlich)
        assert welt.lauf("einsetzen", welt.signierte_lieferung(privat, "0.3.0")).returncode == 0
        vorher = welt.zustand()
        r = welt.lauf("rueckweg")
        assert r.returncode == 1 and "--ohne-signatur" in welt.ausgabe(r) and welt.zustand() == vorher
        r = welt.lauf("rueckweg", "--ohne-signatur")
        assert r.returncode == 0, welt.ausgabe(r)
        assert "WARNUNG" in r.stderr and welt.link("aktuell") == "staende/0.2.0"
        assert "signatur=keine" in welt.journal_zeilen()[-1]

    def test_ohne_signatur_gibt_es_nur_beim_rueckweg(self, welt):
        r = welt.lauf("status", "--ohne-signatur")
        assert r.returncode == 2

    def test_status_json(self, welt):
        r = welt.lauf("status", "--json")
        assert r.returncode == 0, welt.ausgabe(r)
        assert json.loads(r.stdout) == {"v": 1, "aktuell": None, "vorher": None, "staende": [], "schluesselliste": False}
        inhalt2, inhalt3 = b"MZ zwei" + bytes(50), b"MZ drei" + bytes(70)
        assert welt.lauf("einsetzen", welt.lieferung("0.2.0", inhalt2)).returncode == 0
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0", inhalt3)).returncode == 0
        r = welt.lauf("status", "--json")
        assert r.returncode == 0, welt.ausgabe(r)
        assert r.stdout.count("\n") == 1, "auf stdout steht nur das JSON"
        d = json.loads(r.stdout)
        assert d["aktuell"] == {"version": "0.3.0", "sha256": sha(inhalt3), "groesse": len(inhalt3), "commit": COMMIT, "signatur": "keine",
                                "datei": "ok"}
        assert d["vorher"]["version"] == "0.2.0" and d["vorher"]["sha256"] == sha(inhalt2)
        assert d["staende"] == ["0.3.0", "0.2.0"] and d["schluesselliste"] is False

    @braucht_openssl
    def test_status_zeigt_signatur_und_schluesselliste(self, welt):
        privat, oeffentlich = schluesselpaar()
        welt.schluessel_setzen(oeffentlich)
        assert welt.lauf("einsetzen", welt.signierte_lieferung(privat, "0.3.0")).returncode == 0
        d = json.loads(welt.lauf("status", "--json").stdout)
        assert d["aktuell"]["signatur"] == "gueltig" and d["schluesselliste"] is True
        r = welt.lauf("status")
        assert r.returncode == 0 and "signiert: ja (gültig)" in r.stdout and "0.3.0" in r.stdout and "Fertig." in r.stdout

    def test_status_meldet_eine_beschaedigte_datei(self, welt):
        assert welt.lauf("einsetzen", welt.lieferung("0.3.0")).returncode == 0
        (welt.staende / "0.3.0" / "WAIS-Setup-0.3.0.exe").write_bytes(b"kaputt")
        d = json.loads(welt.lauf("status", "--json").stdout)
        assert d["aktuell"]["datei"] == "abweichend"
        assert "ABWEICHEND" in welt.lauf("status").stdout

    def test_falsche_aufrufe(self, welt):
        eingang = welt.lieferung("0.3.0")
        for args in ((), ("frech",), ("einsetzen",), ("einsetzen", "--trocken"), ("einsetzen", "relativ/pfad"),
                     ("einsetzen", eingang, "--json"), ("einsetzen", eingang, "extra"), ("status", "--trocken"), ("rueckweg", "--json"),
                     ("rueckweg", "0.2.0"), ("--trocken",)):
            r = welt.lauf(*args)
            assert r.returncode == 2, (args, welt.ausgabe(r))
        assert welt.zustand() == {}

    @pytest.mark.parametrize("wurzel", ["relativ", "/", "/tmp/../etc", "/tmp/a b"])
    def test_eine_ungueltige_probewurzel_wird_abgelehnt(self, welt, wurzel):
        r = welt.lauf("status", extra={"WAMO_VERTEILUNG_WURZEL": wurzel})
        assert r.returncode == 1 and "WAMO_VERTEILUNG_WURZEL" in r.stderr

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="als root würde der Lauf das echte System anfassen")
    def test_ohne_probelauf_und_ohne_root_wird_nichts_getan(self, welt):
        r = welt.lauf("status", wurzel=False)
        assert r.returncode == 1 and "als root" in r.stderr
