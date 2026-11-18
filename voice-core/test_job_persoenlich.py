"""Tests für Paket D-a von Plan C (persönliche GitHub-Zugänge, docs/persoenliche-zugaenge.md): die Dispatcher-Seite (Kopffeld github,
GitHub-Zeile mit dem Bytes-Leser, neue Befehle, Umgebung, Schwärzung, ping, Aufräumen), der Credential-Helfer wamo-git-zugang, die
Sandbox-Modi klon, ausgabe und pruefung in wamo-job.sh mit ihren festen Skripten und die Einrichtung (Timer, Rückweg).

Die GitHub-Logik selbst (API, Klon, Bereinigung, Regeln, Commit, Einreichen) ist Paket D-b (test_job_github.py). Läuft unter Windows und
Linux; was echte Pipes zwischen Prozessen, bwrap oder Dateirechte braucht, wird unter Windows übersprungen. Die echten Sandbox-Proben
macht wamo-job-rauchtest --persoenlich am Server.

Ausführen (im Ordner voice-core/):  python -m pytest -q test_job_persoenlich.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

INFRA = Path(__file__).resolve().parent.parent / "infra" / "sokrates2"
LINUX = sys.platform.startswith("linux")
TOKEN = "ghp_" + "A1b2C3d4E5" * 3 + "abcdef"  # Attrappe: 36 Zeichen nach ghp_
TOKEN_FEIN = "github_pat_" + "Ab1_" * 20 + "xy"  # Attrappe: 82 Zeichen nach github_pat_
JOB = "abc1234567890def"
PROFIL = "1a2b3c4d"


def _laden(name: str, datei: str):
    pfad = INFRA / datei
    lader = importlib.machinery.SourceFileLoader(name, str(pfad))
    spec = importlib.util.spec_from_loader(name, lader)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    lader.exec_module(modul)
    return modul


H = _laden("wamo_git_zugang", "wamo-git-zugang")
D = _laden("wamo_job_dispatch_persoenlich", "wamo_job_dispatch.py")  # eigene Kopie: Patches anderer Testdateien stören nicht
self_test_assert_token_len = (len(TOKEN) - 4, len(TOKEN_FEIN) - 11)


def _bash() -> str | None:
    kandidaten = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"] if os.name == "nt" else []
    kandidaten.append(shutil.which("bash") if os.name != "nt" else None)
    return next((k for k in kandidaten if k and Path(k).exists()), None)


BASH = _bash()


# ---------------------------------------------------------------- Credential-Helfer wamo-git-zugang
class HelferTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(self_test_assert_token_len, (36, 82))

    def _aufruf(self, aktion: str, anfrage: bytes, zugang: bytes | None = None) -> bytes:
        r, w = os.pipe()
        if zugang is not None:
            os.write(w, zugang)
        os.close(w)
        aus_r, aus_w = os.pipe()
        code = H.main(["wamo-git-zugang", str(r), aktion], eingabe=io.BytesIO(anfrage), ausgabe_fd=aus_w)
        os.close(aus_w)
        ausgabe = b""
        while True:
            stueck = os.read(aus_r, 4096)
            if not stueck:
                break
            ausgabe += stueck
        os.close(aus_r)
        self.assertEqual(code, 0)
        with self.assertRaises(OSError):  # der Helfer schließt den Deskriptor immer
            os.fstat(r)
        return ausgabe

    def test_get_fuer_github_antwortet_genau_mit_dem_zugang(self):
        zugang = f"username=x-access-token\npassword={TOKEN}\n".encode()
        aus = self._aufruf("get", b"protocol=https\nhost=github.com\n\n", zugang)
        self.assertEqual(aus, zugang)
        fein = f"username=octo-cat\npassword={TOKEN_FEIN}\n".encode()
        self.assertEqual(self._aufruf("get", b"capability[]=authtype\nprotocol=https\nhost=github.com\npath=a/b.git\n", fein), fein)

    def test_store_erase_und_fremde_hosts_antworten_nie(self):
        zugang = f"username=x-access-token\npassword={TOKEN}\n".encode()
        for aktion, anfrage in (("store", b"protocol=https\nhost=github.com\nusername=x\npassword=y\n\n"),
                                ("erase", b"protocol=https\nhost=github.com\n\n"),
                                ("get", b"protocol=https\nhost=evil.example\n\n"),
                                ("get", b"protocol=http\nhost=github.com\n\n"),
                                ("get", b"protocol=https\nhost=github.com:443\n\n"),
                                ("get", b"protocol=https\nhost=api.github.com\n\n"),
                                ("get", b"host=github.com\n\n"),
                                ("capability", b"protocol=https\nhost=github.com\n\n")):
            with self.subTest(aktion=aktion, anfrage=anfrage):
                self.assertEqual(self._aufruf(aktion, anfrage, zugang), b"")

    def test_falsche_form_des_zugangs_ergibt_keine_antwort(self):
        for zugang in (f"username=x-access-token\npassword={TOKEN}".encode(),  # ohne Zeilenende
                       f"username=x-access-token\npassword={TOKEN}\nextra=1\n".encode(),
                       f"username=x;rm\npassword={TOKEN}\n".encode(),
                       b"username=x-access-token\npassword=gho_" + b"a" * 36 + b"\n",
                       f"password={TOKEN}\nusername=x-access-token\n".encode(),
                       b"x" * 600, b""):
            with self.subTest(zugang=zugang[:30]):
                self.assertEqual(self._aufruf("get", b"protocol=https\nhost=github.com\n\n", zugang), b"")

    def test_falsche_aufrufform(self):
        for argv in (["h"], ["h", "3"], ["h", "x", "get"], ["h", "0", "get"], ["h", "1", "get"], ["h", "2", "get"],
                     ["h", "-3", "get"], ["h", "3", "get", "mehr"]):
            with self.subTest(argv=argv):
                self.assertEqual(H.main(argv, eingabe=io.BytesIO(b"")), 2)

    def test_kein_token_in_texten_und_kein_protokoll(self):
        text = (INFRA / "wamo-git-zugang").read_text(encoding="utf-8")
        self.assertNotIn("print(", text)
        self.assertNotIn("sys.stderr", text)
        self.assertIn("prctl(4, 0, 0, 0, 0)", text)
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"))
        self.assertNotIn("\r", text)

    @unittest.skipUnless(LINUX, "Deskriptoren an Kindprozesse weiterreichen nur unter Linux")
    def test_eine_datei_statt_einer_pipe_wird_nie_gelesen(self):
        with tempfile.TemporaryFile() as f:
            f.write(f"username=x-access-token\npassword={TOKEN}\n".encode())
            f.seek(0)
            p = subprocess.run([sys.executable, "-I", str(INFRA / "wamo-git-zugang"), str(f.fileno()), "get"],
                               input=b"protocol=https\nhost=github.com\n\n", capture_output=True, pass_fds=(f.fileno(),))
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"", b""))

    @unittest.skipUnless(LINUX and shutil.which("git"), "git credential fill mit geerbtem Deskriptor nur unter Linux")
    def test_git_reicht_den_deskriptor_an_den_helfer_weiter(self):
        r, w = os.pipe()
        os.write(w, f"username=x-access-token\npassword={TOKEN}\n".encode())
        os.close(w)
        helfer = f"{sys.executable} -I {INFRA / 'wamo-git-zugang'} {r}"
        env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false"}
        p = subprocess.run(["git", "-c", "credential.helper=", "-c", f"credential.helper=!{helfer}", "credential", "fill"],
                           input=b"protocol=https\nhost=github.com\n\n", capture_output=True, env=env, pass_fds=(r,), cwd="/")
        os.close(r)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"password={TOKEN}".encode(), p.stdout)


# ---------------------------------------------------------------- Hilfen für die Dispatcher-Tests
import contextlib  # noqa: E402
import inspect  # noqa: E402

G = sys.modules.get("wamo_job_github") or _laden("wamo_job_github", "wamo_job_github.py")
K = sys.modules.get("wamo_job_kernkanal") or _laden("wamo_job_kernkanal", "wamo_job_kernkanal.py")


def github_zeile(token: str = TOKEN) -> bytes:
    return b'{"typ":"github","wert":"' + token.encode() + b'"}\n'


def leser_mit(daten: bytes):
    """Ein StdinLeser über einer Pipe, in die daten schon geschrieben sind (Schreibende zu: EOF nach den Daten)."""
    r, w = os.pipe()
    os.write(w, daten)
    os.close(w)
    return D.StdinLeser(r)


def geheimnis_aus(token: str = TOKEN):
    leser = leser_mit(github_zeile(token))
    geheimnis = D.github_zeile_pruefen(leser, leser.zeile(300, "GitHub-Zeile"))
    os.close(leser.fd)
    return geheimnis


class _Sperre:
    def __init__(self, pfad):
        self.pfad, self.datei = pfad, None

    def versuchen(self):
        return True


class _BelegteSperre(_Sperre):
    def versuchen(self):
        return False


class DispatcherBasis(unittest.TestCase):
    """Wegwerf-Ordner für JOBS und PROJEKTE, Protokoll und Ereignisse als Listen, Sperren ohne fcntl (auch unter Windows)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        wurzel = Path(self.tmp.name)
        self.jobs, self.projekte, self.heim = wurzel / "jobs", wurzel / "projekte", wurzel / "heim"
        for pfad in (self.jobs, self.projekte, self.heim):
            pfad.mkdir()
        self.logzeilen: list[str] = []
        self.ereignisse: list[dict] = []
        self.patches = [mock.patch.object(D, "log", side_effect=lambda t, pflicht=False: self.logzeilen.append(t)),
                        mock.patch.object(D, "JOBS", self.jobs), mock.patch.object(D, "PROJEKTE", self.projekte),
                        mock.patch.object(D, "HEIM", self.heim),
                        mock.patch.object(D, "emit", side_effect=lambda ev: self.ereignisse.append(ev) or True),
                        mock.patch.object(D, "Sperre", _Sperre), mock.patch.object(D, "aufraeumen"),
                        mock.patch.object(D, "exklusiv", lambda pfad: contextlib.nullcontext()),
                        mock.patch.object(D, "exklusiv_mit_frist", lambda pfad, frist: contextlib.nullcontext()),
                        mock.patch.object(D, "LESER", None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def auftrag(self, job: str = JOB, github: str | None = "persoenlich", profil: str = PROFIL, projekt: str = "kern-1a2b3c4d-demo",
                status: str | None = None) -> Path:
        jobdir = self.jobs / job
        jobdir.mkdir(exist_ok=True)
        meta = {"job": job, "projekt": projekt, "art": "umsetzung", "repo": "octo/demo", "kanal": "kern", "profil": profil}
        if github:
            meta["github"] = github
        (jobdir / "auftrag.json").write_text(json.dumps(meta), encoding="utf-8")
        if status is not None:
            (jobdir / "aenderung.json").write_text(json.dumps({"job": job, "status": status}), encoding="utf-8")
        return jobdir

    def github_json(self, jobdir: Path, **extra) -> None:
        (jobdir / "github.json").write_text(json.dumps({"v": 1, "repo": "octo/demo", "repo_id": 7, "login": "octo-cat", "konto_id": 4242,
                                                        "basis": "b" * 40, "standardzweig": "main", "privat": True, "schreiben": True,
                                                        **extra}), encoding="utf-8")

    def ereignis(self, name: str) -> list[dict]:
        return [e for e in self.ereignisse if e.get("ereignis") == name]

    def alles(self) -> str:
        text = "\n".join(self.logzeilen) + json.dumps(self.ereignisse)
        for ordner, _, dateien in os.walk(self.tmp.name):
            for name in dateien:
                text += (Path(ordner) / name).read_bytes().decode("utf-8", "replace")
        return text


# ---------------------------------------------------------------- Namen aus Paket S (wamo_job_github.py, wamo_job_kernkanal.py)
class SchnittstelleTests(unittest.TestCase):
    def test_die_werte_des_dispatchers_sind_die_der_schnittstelle(self):
        self.assertEqual(D.GITHUB_WEG, G.GITHUB_PERSOENLICH)
        self.assertEqual(D.GITHUB_ZEILE_RE.pattern, G.GITHUB_ZEILE_RE.pattern)
        self.assertEqual(D.MAX_GITHUB_ZEILE, G.GITHUB_ZEILE_MAX_BYTES)
        self.assertEqual(D.MAX_EINREICHEN_ZEILE, G.EINREICHEN_ZEILE_MAX_BYTES)
        self.assertEqual(D.ZUSTAENDE, G.AENDERUNG_STATUS)
        self.assertEqual(D.BEFEHLE_PERSOENLICH, G.BEFEHLE_GITHUB)
        self.assertEqual(tuple(D.SCHRITT_PROGRAMME), G.SANDBOX_MODI_NETZLOS)
        self.assertTrue(set(D.GITHUB_DATEIEN) <= set(G.AUFTRAG_DATEIEN))
        self.assertTrue(set(D.VERWERFEN_AUS) <= set(G.AENDERUNG_STATUS) and set(D.LAUF_ERLAUBT) <= set(G.AENDERUNG_STATUS))
        self.assertEqual(set(G.EINREICHEN_FELDER), {"commit_id", "tree_id", "bestaetigt", "scopes_ausnahmen"})
        self.assertEqual(set(K.BEFEHLE_KERN) & set(G.BEFEHLE_GITHUB), set(G.BEFEHLE_GITHUB))
        self.assertEqual(set(K.BEFEHLE_GESCHLOSSEN) & set(G.BEFEHLE_GITHUB), set(G.BEFEHLE_GITHUB_GESCHLOSSEN))
        self.assertNotIn("einreichen", K.BEFEHLE_GESCHLOSSEN)
        self.assertEqual(K.BEFEHLE_NOTAUS, ("ping", "status"))

    def test_die_werkzeuge_erfuellen_das_protokoll_mit_denselben_signaturen(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobdir = Path(tmp) / JOB
            jobdir.mkdir()
            w = D.DispatcherWerkzeuge(JOB, "kern-1a2b3c4d-demo", jobdir)
            self.assertIsInstance(w, G.Werkzeuge)
        for name, wert in vars(G.Werkzeuge).items():
            if name.startswith("_") or not callable(wert):
                continue
            soll = inspect.signature(wert)
            ist = inspect.signature(getattr(D.DispatcherWerkzeuge, name))
            self.assertEqual([(p.name, p.kind) for p in soll.parameters.values()], [(p.name, p.kind) for p in ist.parameters.values()], name)

    def test_jeder_code_des_dispatchers_steht_in_einer_liste_der_schnittstelle(self):
        text = (INFRA / "wamo_job_dispatch.py").read_text(encoding="utf-8")
        rumpf = text[text.index("# ---------------------------------------------------------------- Persönlicher GitHub-Weg"):
                     text.index("def cmd_start(")]
        bekannt = set(K.KANAL_GRUENDE) | set(K.GITHUB_GRUENDE) | set(K.AENDERUNG_GRUENDE) | set(K.EINREICHEN_GRUENDE)
        for code in re.findall(r'GithubAbgelehnt\("([a-z_]+)"\)|_einreichen_fehler\(job, "([a-z_]+)"\)|fehler="([a-z_]+)"', rumpf):
            code = next(c for c in code if c)
            self.assertIn(code, bekannt)
        for code in ("persoenlich_aus", "grenze_einreichen"):
            self.assertGreaterEqual((INFRA / "wamo_job_kernkanal.py").read_text(encoding="utf-8").count(f'"{code}"'), 2, code)


# ---------------------------------------------------------------- Bytes-Leser und GitHub-Zeile (C.2.2)
class LeserTests(unittest.TestCase):
    def test_zeilen_kommen_aus_einem_puffer_ohne_readline(self):
        kopf = b'{"auftrag": "x", "github": "persoenlich"}\n'
        leser = leser_mit(kopf + b'{"typ": "oauth"}\n' + github_zeile())
        self.assertEqual(bytes(leser.zeile(D.MAX_HEADER_BYTES + 1, "Kopfzeile")), kopf)
        self.assertEqual(bytes(leser.zeile(D.MAX_ZUGANG_BYTES + 1, "Zugangszeile")), b'{"typ": "oauth"}\n')
        geheimnis = D.github_zeile_pruefen(leser, leser.zeile(D.MAX_GITHUB_ZEILE + 1, "GitHub-Zeile"))
        ansicht = geheimnis.ansicht()
        self.assertEqual(ansicht.tobytes(), TOKEN.encode())
        ansicht.release()
        self.assertIs(leser.puffer, geheimnis._puffer)  # das Token ist ein Ausschnitt des Lesepuffers, keine Kopie
        geheimnis.ueberschreiben()
        self.assertNotIn(TOKEN.encode(), bytes(leser.puffer))
        self.assertFalse(geheimnis.gueltig)
        os.close(leser.fd)

    def test_feingranulares_token(self):
        geheimnis = geheimnis_aus(TOKEN_FEIN)
        ansicht = geheimnis.ansicht()
        self.assertEqual(ansicht.tobytes(), TOKEN_FEIN.encode())
        ansicht.release()

    def test_jede_andere_form_wird_abgewiesen_und_ueberschrieben(self):
        schlecht = [b'{"typ": "github", "wert": "' + TOKEN.encode() + b'"}\n',  # Leerzeichen
                    b'{"typ":"github","wert":"' + TOKEN.encode() + b'","x":1}\n',
                    b'{"wert":"' + TOKEN.encode() + b'","typ":"github"}\n',
                    github_zeile("gho_" + "a" * 36), github_zeile("ghp_" + "a" * 35), github_zeile("ghp_" + "a" * 37),
                    github_zeile("github_pat_" + "a" * 81), github_zeile(TOKEN)[:-1],  # ohne Zeilenende
                    b'{"typ":"github","wert":"' + TOKEN.encode() + b'"}\r\n', b"\n", b"x" * 300 + b"\n"]
        for zeile in schlecht:
            with self.subTest(zeile=zeile[:40]):
                leser = leser_mit(zeile)
                with self.assertRaises(D.GithubZeileFehlt) as fehler:
                    D.github_zeile_pruefen(leser, leser.zeile(D.MAX_GITHUB_ZEILE + 1, "GitHub-Zeile"))
                self.assertNotIn("ghp_", str(fehler.exception))
                self.assertNotIn(TOKEN.encode()[:20], bytes(leser.puffer))
                os.close(leser.fd)

    def test_fehlende_zeile_und_eof(self):
        leser = leser_mit(b"")
        with mock.patch.object(D, "LESER", leser), self.assertRaises(D.GithubZeileFehlt):
            D._githubzeile_lesen()
        os.close(leser.fd)

    @unittest.skipUnless(LINUX, "select auf Pipes nur unter Linux")
    def test_frist_ohne_daten(self):
        r, w = os.pipe()
        leser = D.StdinLeser(r)
        beginn = time.monotonic()
        with self.assertRaises(D.GithubZeileFehlt):
            leser.zeile(300, "GitHub-Zeile", D.GithubZeileFehlt, frist_s=0.3)
        self.assertLess(time.monotonic() - beginn, 5)
        os.close(r)
        os.close(w)

    def test_geheimnis_ist_nicht_darstellbar_und_nicht_kopierbar(self):
        import copy
        import pickle
        geheimnis = geheimnis_aus()
        for darstellung in (repr(geheimnis), str(geheimnis), f"{geheimnis}"):
            self.assertNotIn("ghp_", darstellung)
        for kopieren in (lambda: bytes(geheimnis), lambda: pickle.dumps(geheimnis), lambda: copy.copy(geheimnis),
                         lambda: copy.deepcopy(geheimnis), lambda: json.dumps(geheimnis)):
            with self.assertRaises(TypeError):
                kopieren()
        self.assertFalse(hasattr(geheimnis, "__dict__"))

    def test_pipe_fuer_den_helfer_und_kopfzeile(self):
        geheimnis = geheimnis_aus()
        r = geheimnis.in_pipe()
        daten = os.read(r, 4096)
        self.assertEqual(os.read(r, 10), b"")  # Schreibende ist zu
        os.close(r)
        self.assertEqual(daten, f"username=x-access-token\npassword={TOKEN}\n".encode())
        self.assertTrue(H.ZUGANG_RE.fullmatch(daten))  # genau die Form, die der Helfer annimmt
        kopf = geheimnis.kopfzeile()
        self.assertEqual(bytes(kopf), b"Bearer " + TOKEN.encode())
        self.assertIsInstance(kopf, bytearray)

    def test_rest_verwerfen_und_lebenslinie(self):
        leser = leser_mit(b'{"auftrag": "x"}\n' + github_zeile() + b"weiter\n")
        leser.zeile(1000, "Kopfzeile")
        leser.rest_verwerfen()
        self.assertNotIn(b"ghp_", bytes(leser.puffer))
        leser.bis_eof()
        self.assertTrue(leser.eof)
        os.close(leser.fd)

    def test_dispatcher_liest_stdin_im_start_nie_ueber_sys_stdin(self):
        text = (INFRA / "wamo_job_dispatch.py").read_text(encoding="utf-8")
        rumpf = text[text.index("def _kopfzeile_lesen"):text.index("def _lebenslinie_warten")]
        self.assertNotIn("sys.stdin", rumpf)
        self.assertNotIn("readline", rumpf)
        self.assertIn('\nVERSION = "10"\n', text)
        pruefen = text[text.index("def github_zeile_pruefen"):text.index("def _githubzeile_lesen")]
        self.assertNotIn(".group(", pruefen)  # nur fullmatch und Positionen (Schnittstelle C.2.2)


# ---------------------------------------------------------------- Kopfzeile, Bindung, Umgebung, Schwärzung
class KopfzeileTests(unittest.TestCase):
    def kopf(self, **felder) -> bytes:
        return json.dumps({"auftrag": "Baue etwas", "repo": "octo/demo", "profil": PROFIL, "zugang": "folgt", **felder}).encode() + b"\n"

    def test_github_nur_im_kern_kanal_mit_repo_und_profil(self):
        with mock.patch.object(D, "KANAL", "kern"):
            self.assertEqual(D.parse_header(self.kopf(github="persoenlich")).github, "persoenlich")
            self.assertIsNone(D.parse_header(self.kopf()).github)
            for schlecht in (self.kopf(github="app"), self.kopf(github=True), self.kopf(github="Persoenlich"),
                             json.dumps({"auftrag": "x", "profil": PROFIL, "zugang": "folgt", "github": "persoenlich"}).encode() + b"\n",
                             json.dumps({"auftrag": "x", "repo": "octo/demo", "github": "persoenlich"}).encode() + b"\n"):
                with self.subTest(kopf=schlecht), self.assertRaises(D.Abgewiesen):
                    D.parse_header(schlecht)
        for kanal in ("pc", "lokal"):
            with self.subTest(kanal=kanal), mock.patch.object(D, "KANAL", kanal), self.assertRaises(D.Abgewiesen) as fehler:
                D.parse_header(self.kopf(github="persoenlich"))
            self.assertIn("nur im Kern-Kanal", str(fehler.exception))

    def test_scopes_ausnahmen_nur_mit_github_und_nur_aus_der_festen_liste(self):
        with mock.patch.object(D, "KANAL", "kern"):
            self.assertEqual(D.parse_header(self.kopf(github="persoenlich", scopes_ausnahmen=["gist", "workflow"])).scopes_ausnahmen,
                             ("gist", "workflow"))
            self.assertEqual(D.parse_header(self.kopf(github="persoenlich", scopes_ausnahmen=[])).scopes_ausnahmen, ())
            self.assertEqual(D.parse_header(self.kopf(github="persoenlich")).scopes_ausnahmen, ())
            for schlecht in (["workflow", "gist"], ["gist", "gist"], ["delete_repo"], ["site_admin"], ["repo"], ["neu_bei_github"],
                             "gist", [1], [None], {"gist": True}, ["gist "], ["Gist"]):
                with self.subTest(scopes=schlecht), self.assertRaises(D.Abgewiesen):
                    D.parse_header(self.kopf(github="persoenlich", scopes_ausnahmen=schlecht))
            with self.assertRaises(D.Abgewiesen):
                D.parse_header(self.kopf(scopes_ausnahmen=["gist"]))  # ohne github
        with mock.patch.object(D, "KANAL", "pc"), self.assertRaises(D.Abgewiesen):
            D.parse_header(self.kopf(scopes_ausnahmen=["gist"]))

    def test_kopf_ohne_github_bleibt_wie_bisher(self):
        kopf = D.Kopf("a", "s", None, None, None, None)
        self.assertIsNone(kopf.github)
        self.assertEqual(kopf.scopes_ausnahmen, ())


class BindungTests(DispatcherBasis):
    def test_github_ist_an_den_auftrag_gebunden(self):
        jobdir = self.jobs / JOB
        jobdir.mkdir()
        p = "kern-1a2b3c4d-demo"
        with mock.patch.object(D, "claude_konfiguration"), mock.patch.object(D, "lese_geheimnisse", return_value={}):
            D.vorbereiten(jobdir, JOB, p, "umsetzung", "octo/demo", "kern", PROFIL, "persoenlich")
            self.assertEqual(json.loads((jobdir / "auftrag.json").read_text())["github"], "persoenlich")
            D.vorbereiten(jobdir, JOB, p, "umsetzung", "octo/demo", "kern", PROFIL, "persoenlich")
            with self.assertRaises(D.GithubWechsel):
                D.vorbereiten(jobdir, JOB, p, "umsetzung", "octo/demo", "kern", PROFIL)
            app = self.jobs / "0123456789abcdef"
            app.mkdir()
            D.vorbereiten(app, "0123456789abcdef", "kern-1a2b3c4d-app", "umsetzung", "octo/demo", "kern", PROFIL)
            self.assertNotIn("github", json.loads((app / "auftrag.json").read_text()))
            with self.assertRaises(D.GithubWechsel):
                D.vorbereiten(app, "0123456789abcdef", "kern-1a2b3c4d-app", "umsetzung", "octo/demo", "kern", PROFIL, "persoenlich")
            pc = self.jobs / "fedcba9876543210"
            pc.mkdir()
            D.vorbereiten(pc, "fedcba9876543210", "demo-app", "umsetzung", "octo/demo", "pc", None, "persoenlich")
            self.assertNotIn("github", json.loads((pc / "auftrag.json").read_text()))  # nur der Kern-Kanal bindet github


class UmgebungTests(unittest.TestCase):
    GEHEIM = {"ANTHROPIC_API_KEY": "sk-ant-api03-Server0123456789abcdef", "GH_TOKEN": "ghp_" + "c" * 36, "VERCEL_TOKEN": "vercel-x" * 3,
              "SUPABASE_ACCESS_TOKEN": "sbp_" + "d" * 40, "JIRA_API_TOKEN": "jira" * 8}

    def lauf(self):
        return D.PersoenlicherLauf(JOB, "octo-cat", 4242, "octo/demo", "a" * 40)

    def test_genau_die_sechs_namen_und_kein_dienst_token(self):
        zugang = D.ClaudeZugang("oauth", "sk-ant-oat01-" + "Z" * 40, None, PROFIL)
        for art in ("umsetzung", "datenbank", "review"):
            with self.subTest(art=art):
                env = D.sandbox_env(art, self.GEHEIM, zugang=zugang, persoenlich=self.lauf())
                for name in ("GH_TOKEN", "VERCEL_TOKEN", "SUPABASE_ACCESS_TOKEN", "JIRA_API_TOKEN", "GH_TOKEN_LESEN", "ANTHROPIC_API_KEY"):
                    self.assertNotIn(name, env)
                self.assertEqual({k: env[k] for k in D.PERSOENLICH_VARIABLEN}, {
                    "GIT_AUTHOR_NAME": "octo-cat", "GIT_COMMITTER_NAME": "octo-cat",
                    "GIT_AUTHOR_EMAIL": "4242+octo-cat@users.noreply.github.com",
                    "GIT_COMMITTER_EMAIL": "4242+octo-cat@users.noreply.github.com", "WAMO_GITHUB": "persoenlich",
                    "WAMO_ZWEIG": f"wamo/{JOB}"})
                self.assertNotIn("credential", json.dumps(env))  # kein Helfer für GitHub in der Sandbox
                self.assertEqual(D.zugangs_quellen(art, self.GEHEIM, zugang=zugang, persoenlich=True), {f"CLAUDE_CODE_OAUTH_TOKEN@{PROFIL}"})
        ohne = D.sandbox_env("umsetzung", self.GEHEIM, zugang=zugang)
        self.assertEqual(ohne["GH_TOKEN"], self.GEHEIM["GH_TOKEN"])  # ohne persönlichen Weg wie bisher
        self.assertFalse(set(D.PERSOENLICH_VARIABLEN) & set(ohne))

    def test_werte_aus_github_json_werden_geprueft(self):
        for login, konto, repo, basis in (("octo cat", 1, "o/r", "a" * 40), ("-octo", 1, "o/r", "a" * 40), ("o" * 40, 1, "o/r", "a" * 40),
                                          ("octo", 0, "o/r", "a" * 40), ("octo", "1", "o/r", "a" * 40), ("octo", True, "o/r", "a" * 40),
                                          ("octo", 1, "o r/x", "a" * 40), ("octo", 1, "o/r", "A" * 40), ("octo", 1, "o/r", "a" * 39),
                                          (None, 1, "o/r", "a" * 40)):
            with self.subTest(login=login, konto=konto), self.assertRaises(ValueError):
                D.PersoenlicherLauf(JOB, login, konto, repo, basis)

    def test_schwaerzen_kennt_alle_github_formen_und_das_exakte_token(self):
        daten = f"a {TOKEN} b {TOKEN_FEIN} c gho_12345678 d ghs_abcdefgh e ghu_ABCDEFGH1 f ghr_00000000 g ghp_kurz".encode()
        aus = D.schwaerzen(daten, [])
        for wert in (TOKEN, TOKEN_FEIN, "gho_1234", "ghs_abcd", "ghu_ABCD", "ghr_0000"):
            self.assertNotIn(wert.encode(), aus)
        self.assertIn(b"ghp_kurz", aus)  # unter 8 Zeichen nach dem Präfix bleibt Text Text
        puffer = bytearray(b"xx" + TOKEN.encode())
        ansicht = memoryview(puffer)[2:]
        self.assertEqual(D.schwaerzen(b"<" + TOKEN.encode() + b">", [(ansicht, b"[EXAKT]")]), b"<[EXAKT]>")
        ansicht.release()
        self.assertEqual(D.schwaerzen(b"[GH_TOKEN] ghs_" + b"x" * 30, [(b"ghs_" + b"x" * 30, b"[GH_TOKEN]")]), b"[GH_TOKEN] [GH_TOKEN]")

    def test_systemtext_des_persoenlichen_wegs(self):
        text = D.github_hinweis_persoenlich(JOB)
        for teil in (f"wamo/{JOB}", f"WAIS-Auftrag: {JOB}", "Nicht pushen", "keinen GitHub-Zugang"):
            self.assertIn(teil, text)


# ---------------------------------------------------------------- Befehle und Kanäle (C.2.3)
class BefehleTests(DispatcherBasis):
    def test_befehlsform_und_kanaele(self):
        for befehl in ("aenderung", "einreichen", "verwerfen"):
            self.assertEqual(D.parse_command(f"{befehl} {JOB} {PROFIL}"), (befehl, [JOB, PROFIL]))
            for schlecht in (f"{befehl} {JOB}", f"{befehl} {JOB} 1A2B3C4D", f"{befehl} {JOB} {PROFIL} x", f"{befehl} {JOB} 1a2b3c4"):
                with self.subTest(befehl=schlecht), self.assertRaises(D.Abgewiesen):
                    D.parse_command(schlecht)
        self.assertEqual(D.parse_command("aufraeumen"), ("aufraeumen", []))
        self.assertEqual(D.parse_command("aufraeumen alle"), ("aufraeumen", ["alle"]))
        with self.assertRaises(D.Abgewiesen):
            D.parse_command("aufraeumen jetzt")

    def test_im_pc_kanal_sind_die_neuen_befehle_gesperrt_und_aufraeumen_nur_lokal(self):
        for roh, kanal in ((f"aenderung {JOB} {PROFIL}", "pc"), (f"einreichen {JOB} {PROFIL}", "pc"), ("aufraeumen", "pc"),
                           ("aufraeumen alle", "kern")):
            self.ereignisse.clear()
            with self.subTest(roh=roh, kanal=kanal), mock.patch.object(D, "kanal_ermitteln", return_value=kanal), \
                    mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": roh}), \
                    mock.patch.object(D, "kern_befehl_pruefen", return_value=None):
                self.assertEqual(D.main(), D.EXIT_ABGEWIESEN)
                self.assertEqual(self.ereignis("kanal_gesperrt"), [{"type": "wamo", "ereignis": "kanal_gesperrt", "grund": "befehl"}])

    def test_im_kern_kanal_gilt_regel_4_mit_profil(self):
        self.auftrag(profil="99999999")
        zustand = K.KernZustand(notaus=False, konfig=K.Konfig(kanal="offen"), grund=None)
        with mock.patch.object(D, "KANAL", "kern"), mock.patch.object(D, "kern_zustand", return_value=zustand), \
                mock.patch.object(D, "kern_modul", return_value=K):
            self.assertEqual(D.kern_befehl_pruefen("aenderung", [JOB, PROFIL]), "fremd")
            self.assertIsNone(D.kern_befehl_pruefen("aenderung", [JOB, "99999999"]))
            self.assertEqual(D.kern_befehl_pruefen("verwerfen", ["0123456789abcdef", "99999999"]), "fremd")  # unbekannter Auftrag
            zu = K.KernZustand(notaus=False, konfig=K.Konfig(kanal="zu"), grund="kanal_zu")
            with mock.patch.object(D, "kern_zustand", return_value=zu):
                self.assertIsNone(D.kern_befehl_pruefen("aenderung", [JOB, "99999999"]))  # auch bei geschlossenem Kanal
                self.assertIsNone(D.kern_befehl_pruefen("verwerfen", [JOB, "99999999"]))
                self.assertEqual(D.kern_befehl_pruefen("einreichen", [JOB, "99999999"]), "kanal_zu")
            with mock.patch.object(D, "kern_zustand", return_value=K.KernZustand(notaus=True, konfig=None, grund="notaus")):
                for befehl in ("aenderung", "einreichen", "verwerfen"):
                    self.assertEqual(D.kern_befehl_pruefen(befehl, [JOB, "99999999"]), "notaus")

    def test_aenderung_liest_nur_die_datei_und_filtert_die_felder(self):
        jobdir = self.auftrag()
        (jobdir / "aenderung.json").write_text(json.dumps({"job": "x", "status": "bereit", "commit_id": "c" * 40, "dateien": 2,
                                                            "geheim": "nie", "liste": [{"pfad": "a.py"}]}), encoding="utf-8")
        self.assertEqual(D.cmd_aenderung(JOB, PROFIL), D.EXIT_OK)
        ereignis = self.ereignis("aenderung")[0]
        self.assertEqual(ereignis["job"], JOB)
        self.assertEqual(ereignis["status"], "bereit")
        self.assertNotIn("geheim", ereignis)
        (jobdir / "aenderung.json").write_text(json.dumps({"status": "fertig"}), encoding="utf-8")
        D.cmd_aenderung(JOB, PROFIL)
        self.assertEqual(self.ereignis("aenderung")[-1]["status"], "keine")
        for job, profil, github in ((JOB, "99999999", "persoenlich"), ("0123456789abcdef", PROFIL, None)):
            self.auftrag(job=job, github=github)
            with self.subTest(job=job), self.assertRaises(D.Abgewiesen):
                D.cmd_aenderung(job, profil)

    def test_verwerfen_nur_aus_erlaubten_zustaenden_und_nie_der_projektordner(self):
        projekt = self.projekte / "kern-1a2b3c4d-demo"
        projekt.mkdir()
        (projekt / "datei.txt").write_text("bleibt", encoding="utf-8")
        for status in ("keine", "gesperrt", "nur_lesen", "bereit"):
            with self.subTest(status=status):
                jobdir = self.auftrag(status=status)
                for name in ("basis.git", "aus.git", "ausgabe", "ergebnis"):
                    (jobdir / name).mkdir(exist_ok=True)
                    (jobdir / name / "x").write_text("x", encoding="utf-8")
                (jobdir / "bundle.ein").write_bytes(b"bundle")
                self.assertEqual(D.cmd_verwerfen(JOB, PROFIL), D.EXIT_OK)
                for name in D.GITHUB_DATEIEN:
                    self.assertFalse(os.path.lexists(jobdir / name), name)
                self.assertEqual(json.loads((jobdir / "aenderung.json").read_text())["status"], "verworfen")
                self.assertEqual(self.ereignis("verworfen")[-1], {"type": "wamo", "ereignis": "verworfen", "job": JOB})
        self.assertEqual((projekt / "datei.txt").read_text(encoding="utf-8"), "bleibt")
        for status in ("einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen"):
            with self.subTest(status=status):
                jobdir = self.auftrag(status=status)
                (jobdir / "aus.git").mkdir(exist_ok=True)
                self.assertEqual(D.cmd_verwerfen(JOB, PROFIL), D.EXIT_ABGEWIESEN)
                self.assertTrue((jobdir / "aus.git").exists())
                self.assertEqual(self.ereignis("einreichen_fehler")[-1]["grund"], "zustand")

    def test_verwerfen_waehrend_eines_laufs_geht_nicht(self):
        jobdir = self.auftrag(status="bereit")
        (jobdir / "aus.git").mkdir()
        with mock.patch.object(D, "Sperre", _BelegteSperre):
            self.assertEqual(D.cmd_verwerfen(JOB, PROFIL), D.EXIT_ABGEWIESEN)
        self.assertTrue((jobdir / "aus.git").exists())


# ---------------------------------------------------------------- Werkzeuge (Protokoll, C.9)
class WerkzeugeTests(DispatcherBasis):
    def setUp(self):
        super().setUp()
        self.jobdir = self.auftrag()
        self.github_json(self.jobdir)

    def werkzeuge(self, zugang=None, **kw):
        return D.DispatcherWerkzeuge(JOB, "kern-1a2b3c4d-demo", self.jobdir, platz=2, zugang=zugang, **kw)

    def _popen(self, aufrufe, code=0, stderr=b"", haengt=False):
        test = self

        class Prozess:
            def __init__(self, argv, **kw):
                aufrufe.append((argv, kw))
                self.pid, self.returncode, self.laeufe = 4242, code, 0
                if kw.get("pass_fds"):
                    test.assertIsNotNone(os.fstat(kw["pass_fds"][0]))  # das Leseende lebt beim Start noch

            def communicate(self, eingabe=None, timeout=None):
                self.laeufe += 1
                if haengt and self.laeufe == 1:
                    raise subprocess.TimeoutExpired("git", timeout)
                return b"aus", stderr

            def kill(self):
                pass
        return Prozess

    def test_git_ohne_netz_mit_netz_und_ohne_token(self):
        aufrufe = []
        geheimnis = geheimnis_aus()
        w = self.werkzeuge(zugang=geheimnis)
        with mock.patch.object(D.subprocess, "Popen", self._popen(aufrufe, stderr=b"fehler " + TOKEN.encode() + b"\nzweite Zeile")):
            ergebnis = w.git(("rev-parse", "HEAD"), git_dir=w.pfad("basis.git"))
            self.assertIsInstance(ergebnis, G.GitErgebnis)
            self.assertEqual((ergebnis.code, ergebnis.stdout), (0, b"aus"))
            self.assertNotIn("ghp_", ergebnis.stderr)
            self.assertNotIn("\n", ergebnis.stderr)
            argv, kw = aufrufe[-1]
            self.assertIn("protocol.https.allow=never", argv)  # ohne netz auch kein https
            self.assertEqual(kw["env"]["GIT_ALLOW_PROTOCOL"], "kein-protokoll")
            self.assertFalse(any("wamo-git-zugang" in a for a in argv))
            self.assertEqual(kw["pass_fds"], ())
            self.assertTrue(kw["start_new_session"])
            w.git(("ls-remote", "--", "https://github.com/octo/demo.git", "refs/heads/wamo/" + JOB), git_dir=w.pfad("aus.git"), netz=True)
            argv, kw = aufrufe[-1]
            helfer = [a for a in argv if a.startswith("credential.helper=")]
            self.assertEqual(helfer[0], "credential.helper=")  # erst die Liste leeren, dann genau der feste Helfer
            self.assertEqual(helfer[-1], f"credential.helper={D.HELFER} {kw['pass_fds'][0]}")
            self.assertIn("protocol.https.allow=always", argv)
            self.assertEqual(kw["env"]["GIT_ALLOW_PROTOCOL"], "https")
            self.assertEqual(kw["cwd"], "/")
            for teil in argv:
                self.assertNotIn(TOKEN, teil)
            self.assertNotIn(TOKEN, json.dumps(kw["env"]))
            self.assertEqual(kw["env"]["GIT_CEILING_DIRECTORIES"], "/")
            self.assertEqual(kw["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
            for schluessel in ("core.hooksPath=/dev/null", "core.fsmonitor=false", "gc.auto=0", "maintenance.auto=false",
                               "http.followRedirects=false", "transfer.fsckObjects=true", "protocol.allow=never"):
                self.assertIn(schluessel, argv)
        with self.assertRaises(OSError):  # das Leseende der Pipe ist nach dem Aufruf zu
            os.fstat(kw["pass_fds"][0])
        ohne = self.werkzeuge()
        with self.assertRaises(G.KeinToken):
            ohne.git(("push", "--", "https://github.com/octo/demo.git", f"{'c' * 40}:refs/heads/wamo/{JOB}"), git_dir=ohne.pfad("aus.git"),
                     netz=True)
        geheimnis.ueberschreiben()

    def test_git_argv_regeln(self):
        aufrufe = []
        w = self.werkzeuge(zugang=geheimnis_aus())
        url = "https://github.com/octo/demo.git"
        erlaubt = [((("clone", "--bare", "--single-branch", "--branch", "main", "--no-tags", "--template=", "--", url,
                       str(w.pfad("basis.git")))), None, True),
                   (("push", "--no-verify", "--porcelain", "--", url, f"{'c' * 40}:refs/heads/wamo/{JOB}"), "aus.git", True),
                   (("ls-remote", "--", url, f"refs/heads/wamo/{JOB}"), "basis.git", True),
                   (("hash-object", "-w", "--no-filters", "--stdin"), "aus.git", False),
                   (("commit-tree", "-F", "-", "d" * 40, "-p", "b" * 40), "aus.git", False)]
        verboten = [(("clone", "--upload-pack=/tmp/x", "--", url, str(w.pfad("basis.git"))), None, True),
                    (("clone", "-u", "/tmp/x", "--", url, str(w.pfad("basis.git"))), None, True),
                    (("clone", "--template=/tmp/vorlage", "--", url, str(w.pfad("basis.git"))), None, True),
                    (("clone", "-c", "core.hooksPath=/tmp", "--", url, str(w.pfad("basis.git"))), None, True),
                    (("clone", "--config=core.sshCommand=x", "--", url, str(w.pfad("basis.git"))), None, True),
                    (("clone", "--", "https://evil.example/octo/demo.git", str(w.pfad("basis.git"))), None, True),
                    (("clone", "--", "https://github.com/octo/anders.git", str(w.pfad("basis.git"))), None, True),
                    (("clone", "--", url, "/tmp/irgendwo"), None, True),
                    (("clone", url, str(w.pfad("basis.git"))), None, True),  # ohne --
                    (("push", "--force", "--", url, f"{'c' * 40}:refs/heads/wamo/{JOB}"), "aus.git", True),
                    (("push", "-f", "--", url, f"{'c' * 40}:refs/heads/wamo/{JOB}"), "aus.git", True),
                    (("push", "--", url, f"+{'c' * 40}:refs/heads/wamo/{JOB}"), "aus.git", True),
                    (("push", "--", url, f"{'c' * 40}:refs/heads/main"), "aus.git", True),
                    (("push", "--", url, f"{'c' * 40}:refs/heads/wamo/{JOB}", "refs/tags/x"), "aus.git", True),
                    (("push", "--receive-pack=x", "--", url, f"{'c' * 40}:refs/heads/wamo/{JOB}"), "aus.git", True),
                    (("ls-remote", "--", url, "refs/heads/main"), "aus.git", True),
                    (("ls-remote", "--", url, f"refs/heads/wamo/{JOB}"), "aus.git", False),  # ohne netz
                    (("fetch", "--", url), "aus.git", True), (("config", "remote.x.url", url), "aus.git", False),
                    (("rev-parse", "HEAD"), "basis.git", True), (("rev-parse", "HEAD"), None, False),
                    (("rev-parse", "$(id)"), "aus.git", False), (("rev-parse", "a b"), "aus.git", False),
                    (("-c", "x=y", "rev-parse"), "aus.git", False), (("cat-file", "--batch", "file:///etc/passwd"), "aus.git", False)]
        # Die Regeln je Aufruf (_git_regeln); unter Windows enthält der Pfad von basis.git Laufwerk und Backslash, die GIT_ARG_RE in
        # git_aufruf ablehnt, am Server ist er immer POSIX. Die Zeichenregel prüft der Test danach eigens.
        for args, git_dir, netz in erlaubt:
            with self.subTest(args=args):
                w._git_regeln(args, w.pfad(git_dir) if git_dir else None, netz)
        for args, git_dir, netz in verboten:
            with self.subTest(args=args), self.assertRaises(ValueError):
                if git_dir is None and args[0] != "clone":
                    raise ValueError("ohne git_dir nur clone")  # prüft git() vor den Regeln
                w._git_regeln(args, w.pfad(git_dir) if git_dir else None, netz)
                if any(not D.GIT_ARG_RE.fullmatch(a) for a in args):
                    raise ValueError("Zeichen")
        with mock.patch.object(D.subprocess, "Popen", self._popen(aufrufe)):
            w.git(("hash-object", "-w", "--no-filters", "--stdin"), git_dir=w.pfad("aus.git"))
            for args in (("rev-parse", "$(id)"), ("rev-parse", "a b"), ("rev-parse", "a\nb")):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    w.git(args, git_dir=w.pfad("aus.git"))
            with self.assertRaises(ValueError):
                w.git(("rev-parse", "HEAD"), git_dir=None)
        self.assertEqual(len(aufrufe), 1)
        with self.assertRaises(ValueError):
            w.git(("rev-parse", "HEAD"), git_dir=self.projekte)  # nie ein Repo außerhalb der eigenen

    def test_git_am_zeitlimit_endet_die_ganze_prozessgruppe(self):
        aufrufe = []
        getoetet = []
        w = self.werkzeuge(zugang=geheimnis_aus())
        with mock.patch.object(D.subprocess, "Popen", self._popen(aufrufe, haengt=True)), \
                mock.patch.object(D.os, "killpg", side_effect=lambda pid, sig: getoetet.append(pid), create=True):
            ergebnis = w.git(("ls-remote", "--", "https://github.com/octo/demo.git", f"refs/heads/wamo/{JOB}"), git_dir=w.pfad("aus.git"),
                             netz=True, zeitlimit_s=5)
        self.assertEqual(ergebnis.code, D.EXIT_ZEITLIMIT)
        self.assertEqual(getoetet, [4242])
        with self.assertRaises(OSError):
            os.fstat(aufrufe[0][1]["pass_fds"][0])

    def test_http_mit_kopfzeilen_und_ueberschriebener_anmeldung(self):
        gesehen = {}

        def https(methode, pfad, kopf, koerper=None):
            gesehen["kopf"] = kopf["Authorization"]
            gesehen["wert"] = bytes(kopf["Authorization"])
            return 200, {"x-oauth-scopes": "repo"}, b'{"login": "octo-cat"}'
        geheimnis = geheimnis_aus()
        w = self.werkzeuge(zugang=geheimnis)
        with mock.patch.object(D, "_https_voll", side_effect=https):
            antwort = w.http("GET", "/user")
        self.assertIsInstance(antwort, G.HttpAntwort)
        self.assertEqual((antwort.status, antwort.daten, antwort.kopf["x-oauth-scopes"]), (200, {"login": "octo-cat"}, "repo"))
        self.assertEqual(gesehen["wert"], b"Bearer " + TOKEN.encode())
        self.assertEqual(bytes(gesehen["kopf"]), bytes(len(gesehen["kopf"])))  # danach überschrieben
        with mock.patch.object(D, "_https_voll", side_effect=OSError("weg")), self.assertRaises(G.NetzFehler):
            w.http("GET", "/user")
        with mock.patch.object(D, "_https_voll", return_value=(200, {}, b"x" * (D.MAX_GITHUB_ANTWORT + 1))), \
                self.assertRaises(G.NetzFehler):
            w.http("GET", "/user")
        with mock.patch.object(D, "_https_voll", return_value=(200, {}, b"kein json")):
            self.assertIsNone(w.http("GET", "/user").daten)
        for methode, pfad in (("DELETE", "/user"), ("GET", "user"), ("GET", "/a b"), ("GET", "/../x")):
            with self.subTest(pfad=pfad), self.assertRaises(ValueError):
                w.http(methode, pfad)
        with self.assertRaises(G.KeinToken):
            self.werkzeuge().http("GET", "/user")
        geheimnis.ueberschreiben()

    def test_geheimnis_in_kennt_token_base64_und_claude_werte(self):
        import base64
        geheimnis = geheimnis_aus()
        w = self.werkzeuge(zugang=geheimnis, werte=(b"sk-ant-oat01-" + b"Q" * 30,))
        self.assertTrue(w.geheimnis_in(b"x" + TOKEN.encode() + b"y"))
        self.assertTrue(w.geheimnis_in(bytearray(b"Authorization: Basic " + base64.b64encode(b"x-access-token:" + TOKEN.encode()))))
        self.assertTrue(w.geheimnis_in(memoryview(b"..sk-ant-oat01-" + b"Q" * 30)))
        self.assertFalse(w.geheimnis_in(b"nichts davon ghp_kurz"))
        for laenge in range(0, 7):
            self.assertEqual(bytes(D._b64_in(b"a" * laenge)), base64.b64encode(b"a" * laenge))
        geheimnis.ueberschreiben()
        self.assertFalse(w.geheimnis_in(TOKEN.encode()))  # nach dem Überschreiben gibt es nichts mehr zu finden

    def test_pfad_sperre_uhr_und_log(self):
        w = self.werkzeuge(zugang=geheimnis_aus(), gehalten=(".lauf",))
        self.assertEqual(w.pfad("basis.git"), self.jobdir / "basis.git")
        for name in ("auftrag.json", "../x", "claude", "zustand"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                w.pfad(name)
        with w.sperre(".lauf") as gehalten:
            self.assertTrue(gehalten)  # hält der Dispatcher schon
        with w.sperre(".einreichen") as gehalten:
            self.assertTrue(gehalten)
        with mock.patch.object(D, "Sperre", _BelegteSperre), w.sperre(".einreichen") as gehalten:
            self.assertFalse(gehalten)
        with self.assertRaises(ValueError), w.sperre("projekt-x"):
            pass
        self.assertAlmostEqual(w.uhr(), time.time(), delta=5)
        w.log(f"Antwort mit {TOKEN} und\nZeile")
        self.assertNotIn("ghp_", self.logzeilen[-1])
        self.assertNotIn("\n", self.logzeilen[-1])

    def test_sandbox_nur_netzlos_fuer_diesen_auftrag(self):
        aufrufe = []
        with mock.patch.object(D, "sandbox_schritt", side_effect=lambda *a, **k: aufrufe.append(a) or D.SchrittErgebnis(0, b"", b"")):
            ergebnis = self.werkzeuge().sandbox("ausgabe", job=JOB, projekt="kern-1a2b3c4d-demo", zeitlimit_s=60)
        self.assertIsInstance(ergebnis, G.SandboxErgebnis)
        self.assertEqual((ergebnis.code, ergebnis.zeitlimit), (0, False))
        self.assertEqual(aufrufe[0][:5], ("ausgabe", JOB, "kern-1a2b3c4d-demo", 2, ["--auftrag", JOB, "--basis", "b" * 40]))
        w = self.werkzeuge()
        for modus, job, projekt, zeit in (("lauf", JOB, "kern-1a2b3c4d-demo", 60), ("pruefen", JOB, "kern-1a2b3c4d-demo", 60),
                                          ("ausgabe", "0123456789abcdef", "kern-1a2b3c4d-demo", 60), ("ausgabe", JOB, "kern-x-y", 60),
                                          ("ausgabe", JOB, "kern-1a2b3c4d-demo", 61), ("klon", JOB, "kern-1a2b3c4d-demo", 301)):
            with self.subTest(modus=modus, job=job, zeit=zeit), self.assertRaises(ValueError):
                w.sandbox(modus, job=job, projekt=projekt, zeitlimit_s=zeit)


class SchrittTests(DispatcherBasis):
    def test_argv_umgebung_und_vorbereitung_je_modus(self):
        jobdir = self.auftrag()
        (self.projekte / "kern-1a2b3c4d-demo").mkdir()
        (jobdir / "ausgabe").mkdir()
        (jobdir / "ausgabe" / "alt.bundle").write_bytes(b"alt")
        aufrufe = []

        def lauf(argv, **kw):
            aufrufe.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        entschaerft = []
        with mock.patch.object(D.subprocess, "run", side_effect=lauf), \
                mock.patch.object(D, "projekt_entschaerfen", side_effect=lambda p: entschaerft.append(p) or []):
            D.sandbox_schritt("ausgabe", JOB, "kern-1a2b3c4d-demo", 3, ["--auftrag", JOB, "--basis", "b" * 40])
            self.assertEqual(list((jobdir / "ausgabe").iterdir()), [])  # vorher geleert
            self.assertEqual(len(entschaerft), 1)  # vor ausgabe entschärft (C.5 Laufende 1)
            argv, kw = aufrufe[-1]
            self.assertEqual(argv[:13], [str(D.RUNNER), "--auftrag", JOB, "--projekt", "kern-1a2b3c4d-demo", "--platz", "3", "--modus",
                                         "ausgabe", "--zeitlimit", "60", "--einheit-zusatz", "ausgabe"])
            self.assertEqual(argv[13:], ["--", str(D.WAECHTER / "wamo-job-ausgabe.sh"), "--auftrag", JOB, "--basis", "b" * 40])
            self.assertEqual(kw["stdin"], subprocess.DEVNULL)
            self.assertEqual(set(kw["env"]) - {"PATH", "LANG", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"},
                             {"GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_KEY_1", "GIT_CONFIG_VALUE_1"})
            D.sandbox_schritt("klon", JOB, "kern-1a2b3c4d-demo", 3, ["--repo", "octo/demo", "--auftrag", JOB, "--basis", "b" * 40])
            self.assertEqual(len(entschaerft), 2)  # nach klon entschärft (C.5 Start 6)
            self.assertEqual(D.eigner_lesen("kern-1a2b3c4d-demo"), JOB)
            D.sandbox_schritt("pruefung", JOB, "kern-1a2b3c4d-demo", 3, ["--auftrag", JOB, "--basis", "b" * 40])
            self.assertEqual(aufrufe[-1][0][14:17], ["/usr/bin/python3", "-I", str(D.WAECHTER / "wamo_job_auszug.py")])
            self.assertTrue((jobdir / "ergebnis").is_dir())
        for modus, argumente in (("lauf", []), ("pruefen", []), ("klon", ["--repo", "a b"]), ("klon", ["$(id)"]), ("klon", ["-x"])):
            with self.subTest(modus=modus, argumente=argumente), self.assertRaises(ValueError):
                D.sandbox_schritt(modus, JOB, "kern-1a2b3c4d-demo", 3, argumente)

    def test_ein_gescheiterter_klon_schreibt_keinen_eigner(self):
        self.auftrag()
        (self.projekte / "kern-1a2b3c4d-demo").mkdir()
        with mock.patch.object(D.subprocess, "run", return_value=subprocess.CompletedProcess([], 70, b"", b"kaputt")), \
                mock.patch.object(D, "projekt_entschaerfen", return_value=[]):
            self.assertEqual(D.sandbox_schritt("klon", JOB, "kern-1a2b3c4d-demo", 3, []).rc, 70)
        self.assertIsNone(D.eigner_lesen("kern-1a2b3c4d-demo"))


# ---------------------------------------------------------------- Vorlauf, Nachlauf und Start mit github=persoenlich
class VorlaufTests(DispatcherBasis):
    def setUp(self):
        super().setUp()
        self.jobdir = self.auftrag()
        (self.projekte / "kern-1a2b3c4d-demo").mkdir()
        self.kopf = D.Kopf("Baue etwas", "", None, "octo/demo", "folgt", PROFIL, "persoenlich", ("workflow",))
        self.schritte = []
        self.patches.append(mock.patch.object(D, "sandbox_schritt", side_effect=self._schritt))
        self.patches[-1].start()

    def _schritt(self, modus, job, projekt, platz, argumente=(), zeitlimit_s=None):
        self.schritte.append((modus, list(argumente)))
        D.eigner_schreiben(projekt, job)
        return D.SchrittErgebnis(0, b"", b"")

    def test_erster_lauf_klont_ueber_die_logik_sendet_github_und_baut_die_arbeitskopie(self):
        aufrufe = []

        def start(w, **kw):
            aufrufe.append((w, kw))
            self.assertIsInstance(w, G.Werkzeuge)
            self.assertTrue(w._zugang.gueltig)  # das Token lebt noch während der Prüfung bei GitHub
            with mock.patch.object(D, "Sperre", _BelegteSperre), w.sperre(".lauf") as gehalten:
                self.assertTrue(gehalten)  # die Sperre des Laufs hält der Dispatcher schon
            self.github_json(self.jobdir)
            (self.jobdir / "basis.git").mkdir()
        geheimnis = geheimnis_aus()
        with mock.patch.object(G, "start", side_effect=start, create=True):
            lauf = D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, geheimnis)
        self.assertEqual(aufrufe[0][1], {"job": JOB, "repo": "octo/demo", "art": "umsetzung", "profil": PROFIL,
                                         "scopes_ausnahmen": ("workflow",), "max_klon_mb": 2048})
        self.assertFalse(geheimnis.gueltig)  # danach überschrieben, vor dem Lauf
        self.assertEqual((lauf.login, lauf.konto_id, lauf.basis), ("octo-cat", 4242, "b" * 40))
        self.assertEqual(self.ereignis("github"), [{"type": "wamo", "ereignis": "github", "repo": "octo/demo", "konto": "octo-cat",
                                                    "basis": "b" * 40, "standardzweig": "main", "privat": True, "schreiben": True}])
        self.assertEqual(self.schritte, [("klon", ["--repo", "octo/demo", "--auftrag", JOB, "--basis", "b" * 40])])
        self.assertNotIn(TOKEN, self.alles())

    def test_ein_fehler_der_logik_hinterlaesst_keinen_halben_klon(self):
        class Abgelehnt(Exception):
            grund = "eigenes_repo"

        def start(w, **kw):
            (self.jobdir / "basis.git").mkdir()
            self.github_json(self.jobdir)
            raise Abgelehnt("Text mit " + TOKEN)
        for fehler, erwartet in ((Abgelehnt, "eigenes_repo"), (RuntimeError("x " + TOKEN), "klon_fehler")):
            with self.subTest(erwartet=erwartet), mock.patch.object(G, "start", side_effect=fehler if fehler is not Abgelehnt else start,
                                                                     create=True), self.assertRaises(D.GithubAbgelehnt) as e:
                D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, geheimnis_aus())
            self.assertEqual(e.exception.grund, erwartet)
            self.assertFalse((self.jobdir / "basis.git").exists())
            self.assertFalse((self.jobdir / "github.json").exists())
        self.assertEqual(self.schritte, [])
        self.assertNotIn(TOKEN, self.alles())
        with mock.patch.object(G, "start", side_effect=lambda w, **kw: None, create=True), self.assertRaises(D.GithubAbgelehnt) as e:
            D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, geheimnis_aus())
        self.assertEqual(e.exception.grund, "klon_fehler")  # ohne github.json kein Lauf

    def test_folgelauf_eigener_ordner_fremder_ordner_mit_und_ohne_bundle(self):
        self.github_json(self.jobdir)
        (self.jobdir / "basis.git").mkdir()
        D.eigner_schreiben("kern-1a2b3c4d-demo", JOB)
        D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, None)
        self.assertEqual(self.schritte, [])  # der Ordner stammt aus dem eigenen Klon
        D.eigner_schreiben("kern-1a2b3c4d-demo", "0123456789abcdef")
        D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, None)
        self.assertEqual(self.schritte[-1][0], "klon")  # noch nie ausgewertet: neu aus basis.git, nichts geht verloren
        (self.jobdir / "aenderung.json").write_text(json.dumps({"job": JOB, "status": "bereit"}), encoding="utf-8")
        D.eigner_schreiben("kern-1a2b3c4d-demo", "0123456789abcdef")
        with self.assertRaises(D.GithubAbgelehnt) as e:
            D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, None)
        self.assertEqual(e.exception.grund, "projekt_gewechselt")
        (self.jobdir / "bundle.ein").write_bytes(b"bundle")
        D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, None)
        self.assertEqual(self.schritte[-1], ("klon", ["--repo", "octo/demo", "--auftrag", JOB, "--basis", "b" * 40, "--bundle"]))
        for status in ("einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen"):
            (self.jobdir / "aenderung.json").write_text(json.dumps({"job": JOB, "status": status}), encoding="utf-8")
            for geheimnis in (None, geheimnis_aus()):
                with self.subTest(status=status), self.assertRaises(D.GithubAbgelehnt) as e:
                    D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, geheimnis)
                self.assertEqual(e.exception.grund, "schon_eingereicht")

    def test_klon_scheitert(self):
        self.github_json(self.jobdir)
        (self.jobdir / "basis.git").mkdir()
        with mock.patch.object(D, "sandbox_schritt", return_value=D.SchrittErgebnis(70, b"", b"kaputt")), \
                self.assertRaises(D.KlonFehlgeschlagen):
            D.github_vorlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", self.kopf, 2, None)

    def test_nachlauf_schreibt_gesperrt_bei_fehlern_und_sendet_immer_aenderung(self):
        env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "W" * 30}

        def laufende(w, **kw):
            self.assertEqual(kw["lauf"], "zeitlimit")
            self.assertTrue(w.geheimnis_in(env["CLAUDE_CODE_OAUTH_TOKEN"].encode()))  # die exakten Werte des Laufs für die Suche
            (self.jobdir / "aenderung.json").write_text(json.dumps({"job": JOB, "status": "bereit", "dateien": 1}), encoding="utf-8")
        with mock.patch.object(G, "laufende", side_effect=laufende, create=True):
            D.github_nachlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", 2, D.EXIT_ZEITLIMIT, self.kopf, env)
        self.assertEqual(self.ereignis("aenderung")[-1]["status"], "bereit")
        with mock.patch.object(G, "laufende", side_effect=RuntimeError("kaputt"), create=True):
            D.github_nachlauf(self.jobdir, JOB, "kern-1a2b3c4d-demo", "umsetzung", 2, D.EXIT_OK, self.kopf, env)
        self.assertEqual(self.ereignis("aenderung")[-1]["status"], "gesperrt")
        self.assertEqual(self.ereignis("aenderung")[-1]["gruende"], ["pruefung_fehler"])


class StartTests(DispatcherBasis):
    """cmd_start mit github=persoenlich im Kern-Kanal: Prüfungen des Kanals, Sperren, Selbsttest und Lauf sind Attrappen."""

    def setUp(self):
        super().setUp()
        (self.projekte / "kern-1a2b3c4d-demo").mkdir()
        self.laeufe: list[tuple] = []
        konfig = types_ns(max_turns=40, max_budget_usd="2.00")

        @contextlib.contextmanager
        def buchung(job, profil=None, pruefung=None):
            yield None, konfig
        for patch in (mock.patch.object(D, "KANAL", "kern"), mock.patch.object(D, "kern_start_pruefen", return_value=(None, konfig)),
                      mock.patch.object(D, "kern_versuch_buchen", return_value=True), mock.patch.object(D, "kern_buchung", buchung),
                      mock.patch.object(D, "parallel_grenzen", return_value=(6, 3)),
                      mock.patch.object(D, "plaetze_belegen", return_value=([], 2, None)), mock.patch.object(D, "platz_reste_beenden"),
                      mock.patch.object(D, "selbsttest", return_value=(True, "ok")), mock.patch.object(D, "projekt_entschaerfen", return_value=[]),
                      mock.patch.object(D, "lese_geheimnisse", return_value={"GH_TOKEN": "ghp_" + "s" * 36, "VERCEL_TOKEN": "v" * 30}),
                      mock.patch.object(D, "nicht_dumpbar", return_value=True), mock.patch.object(D, "claude_konfiguration"),
                      mock.patch.object(D, "_ausfuehren", side_effect=lambda argv, env, *a: self.laeufe.append((argv, env)) or D.EXIT_OK),
                      mock.patch.object(D, "sandbox_schritt", side_effect=self._schritt)):
            self.patches.append(patch)
            patch.start()

    def _schritt(self, modus, job, projekt, platz, argumente=(), zeitlimit_s=None):
        if modus == "klon":
            D.eigner_schreiben(projekt, job)
        return D.SchrittErgebnis(0, b"", b"")

    def start(self, kopf: dict, zeilen: bytes) -> int:
        r, w = os.pipe()
        os.write(w, json.dumps({"auftrag": "Baue etwas", "system": "", "repo": "octo/demo", "zugang": "folgt", "profil": PROFIL,
                                **kopf}).encode() + b"\n" + zeilen)
        os.close(w)
        leser = D.StdinLeser(r)
        try:
            with mock.patch.object(D, "LESER", leser):
                return D.cmd_start(JOB, "kern-1a2b3c4d-demo", "umsetzung")
        finally:
            self.letzter_puffer = bytes(leser.puffer)
            os.close(r)

    def claude_zeile(self) -> bytes:
        return json.dumps({"typ": "oauth", "wert": "sk-ant-oat01-" + "K" * 40}).encode() + b"\n"

    def test_erster_lauf_bis_zum_ereignis_aenderung(self):
        def start(w, **kw):
            self.github_json(self.jobs / JOB)
            (self.jobs / JOB / "basis.git").mkdir()

        def laufende(w, **kw):
            (self.jobs / JOB / "aenderung.json").write_text(json.dumps({"job": JOB, "status": "keine"}), encoding="utf-8")
        with mock.patch.object(G, "start", side_effect=start, create=True), mock.patch.object(G, "laufende", side_effect=laufende, create=True):
            code = self.start({"github": "persoenlich"}, self.claude_zeile() + github_zeile())
        self.assertEqual(code, D.EXIT_OK)
        argv, env = self.laeufe[0]
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("VERCEL_TOKEN", env)
        self.assertEqual(env["WAMO_GITHUB"], "persoenlich")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "4242+octo-cat@users.noreply.github.com")
        self.assertIn(f"WAIS-Auftrag: {JOB}", argv[argv.index("--append-system-prompt") + 1])
        namen = [e["ereignis"] for e in self.ereignisse if e.get("type") == "wamo"]
        self.assertEqual(namen, ["github", "selbsttest_ok", "aenderung"])
        self.assertEqual(json.loads((self.jobs / JOB / "auftrag.json").read_text())["github"], "persoenlich")
        self.assertNotIn(TOKEN.encode(), self.letzter_puffer)  # der Lesepuffer ist am Ende überschrieben
        self.assertNotIn(TOKEN, self.alles())
        self.assertNotIn(TOKEN, json.dumps(env))
        self.assertTrue(any("github=persoenlich" in z for z in self.logzeilen))

    def test_ohne_github_zeile_kein_lauf(self):
        code = self.start({"github": "persoenlich"}, self.claude_zeile())
        self.assertEqual(code, D.EXIT_GITHUB)
        self.assertEqual(self.ereignis("start_abgelehnt"), [{"type": "wamo", "ereignis": "start_abgelehnt", "grund": "github_zeile"}])
        self.assertEqual(self.laeufe, [])

    def test_folgelauf_liest_keine_zeile_und_wechsel_wird_abgewiesen(self):
        jobdir = self.auftrag()
        self.github_json(jobdir)
        (jobdir / "basis.git").mkdir()
        D.eigner_schreiben("kern-1a2b3c4d-demo", JOB)
        with mock.patch.object(G, "start", side_effect=AssertionError("kein Klon im Folgelauf"), create=True), \
                mock.patch.object(G, "laufende", side_effect=lambda w, **kw: None, create=True):
            self.assertEqual(self.start({"github": "persoenlich"}, self.claude_zeile() + github_zeile()), D.EXIT_OK)
        self.assertNotIn(TOKEN.encode(), self.letzter_puffer)  # die mitgeschickte Zeile ist ungelesen überschrieben
        self.ereignisse.clear()
        self.assertEqual(self.start({}, self.claude_zeile()), D.EXIT_GITHUB)  # derselbe Auftrag ohne github
        self.assertEqual(self.ereignis("start_abgelehnt")[0]["grund"], "github_wechsel")

    def test_ein_dumpbarer_prozess_liest_das_token_nie(self):
        with mock.patch.object(D, "nicht_dumpbar", return_value=False), self.assertRaises(RuntimeError):
            self.start({"github": "persoenlich"}, self.claude_zeile() + github_zeile())
        self.assertEqual(self.laeufe, [])

    def test_ohne_github_entfernt_ein_lauf_den_eigner(self):
        D.eigner_schreiben("kern-1a2b3c4d-demo", "0123456789abcdef")
        self.assertEqual(self.start({}, self.claude_zeile()), D.EXIT_OK)
        self.assertIsNone(D.eigner_lesen("kern-1a2b3c4d-demo"))


def types_ns(**werte):
    import types
    return types.SimpleNamespace(**werte)


# ---------------------------------------------------------------- Einreichen (Ablauf auf Dispatcher-Seite)
class EinreichenTests(DispatcherBasis):
    def setUp(self):
        super().setUp()
        self.jobdir = self.auftrag(status="bereit")
        self.github_json(self.jobdir)
        for patch in (mock.patch.object(D, "nicht_dumpbar", return_value=True),):
            self.patches.append(patch)
            patch.start()

    def einreichen(self, zeile1: dict | bytes, github: bytes | None = None, kanal: str = "lokal") -> int:
        roh = zeile1 if isinstance(zeile1, bytes) else json.dumps(zeile1).encode() + b"\n"
        r, w = os.pipe()
        os.write(w, roh + (github_zeile() if github is None else github))
        os.close(w)
        leser = D.StdinLeser(r)
        try:
            with mock.patch.object(D, "LESER", leser), mock.patch.object(D, "KANAL", kanal):
                return D.cmd_einreichen(JOB, PROFIL)
        finally:
            self.letzter_puffer = bytes(leser.puffer)
            os.close(r)

    ZEILE = {"commit_id": "c" * 40, "tree_id": "d" * 40, "bestaetigt": ["b.lock", "a.lock", "a.lock"]}

    def test_erfolg_mit_geprueften_feldern(self):
        gesehen = {}

        def einreichen(w, **kw):
            gesehen.update(kw)
            self.assertTrue(w._zugang.gueltig)
            with w.sperre(".einreichen") as gehalten:
                self.assertTrue(gehalten)
            self.assertIsNone(kw["kanal"](True))
            return {"zweig": f"wamo/{JOB}", "pr": 12, "adresse": "https://github.com/octo/demo/pull/12"}
        with mock.patch.object(G, "einreichen", side_effect=einreichen, create=True):
            self.assertEqual(self.einreichen(self.ZEILE), D.EXIT_OK)
        self.assertEqual(gesehen["eingabe"], {"commit_id": "c" * 40, "tree_id": "d" * 40, "bestaetigt": ("a.lock", "b.lock"),
                                              "scopes_ausnahmen": ()})
        self.assertEqual(self.ereignis("eingereicht"), [{"type": "wamo", "ereignis": "eingereicht", "job": JOB, "zweig": f"wamo/{JOB}",
                                                         "pr": 12, "adresse": "https://github.com/octo/demo/pull/12"}])
        self.assertNotIn(TOKEN.encode(), self.letzter_puffer)
        self.assertNotIn(TOKEN, self.alles())

    def test_falsche_antworten_der_logik_und_fehlercodes(self):
        for ergebnis in ({"zweig": "main", "pr": 12, "adresse": "https://github.com/octo/demo/pull/12"},
                         {"zweig": f"wamo/{JOB}", "pr": 12, "adresse": "https://evil.example/octo/demo/pull/12"},
                         {"zweig": f"wamo/{JOB}", "pr": True, "adresse": "https://github.com/octo/demo/pull/1"}, None):
            self.ereignisse.clear()
            with self.subTest(ergebnis=ergebnis), mock.patch.object(G, "einreichen", return_value=ergebnis, create=True):
                self.assertEqual(self.einreichen(self.ZEILE), D.EXIT_ABGEWIESEN)
                self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], "github_fehler")

        class Fehler(Exception):
            grund = "zweig_belegt"
        for fehler, erwartet in ((Fehler("x"), "zweig_belegt"), (RuntimeError(TOKEN), "github_fehler")):
            self.ereignisse.clear()
            with self.subTest(erwartet=erwartet), mock.patch.object(G, "einreichen", side_effect=fehler, create=True):
                self.assertEqual(self.einreichen(self.ZEILE), D.EXIT_ABGEWIESEN)
                self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], erwartet)
        self.assertNotIn(TOKEN, self.alles())

    def test_zeile_1_und_github_zeile_werden_streng_geprueft(self):
        with mock.patch.object(G, "einreichen", side_effect=AssertionError("darf nicht laufen"), create=True):
            for zeile, erwartet in ((dict(self.ZEILE, commit_id="C" * 40), "veraltet"), (dict(self.ZEILE, x=1), "bestaetigung"),
                                    ({"commit_id": "c" * 40, "tree_id": "d" * 40}, "bestaetigung"), (b"kein json\n", "bestaetigung"),
                                    (dict(self.ZEILE, bestaetigt="a"), "bestaetigung"),
                                    (dict(self.ZEILE, scopes_ausnahmen=["delete_repo"]), "token_rechte")):
                self.ereignisse.clear()
                with self.subTest(zeile=zeile):
                    self.assertEqual(self.einreichen(zeile), D.EXIT_ABGEWIESEN)
                    self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], erwartet)
            self.ereignisse.clear()
            self.assertEqual(self.einreichen(self.ZEILE, github=b"kaputt\n"), D.EXIT_ABGEWIESEN)
            self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], "github_fehler")
            with mock.patch.object(D, "Sperre", _BelegteSperre):
                self.ereignisse.clear()
                self.assertEqual(self.einreichen(self.ZEILE), D.EXIT_ABGEWIESEN)
                self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], "zustand")

    def test_kern_kanal_prueft_persoenlich_versuche_und_bucht(self):
        tmp = Path(self.tmp.name)
        pfade = K.Pfade(kern_schluessel=tmp / "k", pc_schluessel=tmp / "p", konfig=tmp / "c", notaus=tmp / "n", zaehler=tmp / "z.jsonl",
                        platz=tmp)
        for persoenlich, erwartet in ((False, "persoenlich_aus"), (True, None)):
            zustand = K.KernZustand(notaus=False, konfig=K.Konfig(kanal="offen", persoenlich=persoenlich, max_einreichen_tag_profil=1),
                                    grund=None)
            self.ereignisse.clear()

            def einreichen(w, **kw):
                self.assertIsNone(kw["kanal"](False))
                self.assertIsNone(kw["kanal"](True))
                self.assertEqual(kw["kanal"](True), "grenze_einreichen")  # MAX_EINREICHEN_TAG_PROFIL 1
                return {"zweig": f"wamo/{JOB}", "pr": 3, "adresse": "https://github.com/octo/demo/pull/3"}
            with self.subTest(persoenlich=persoenlich), mock.patch.object(D, "kern_modul", return_value=K), \
                    mock.patch.object(D, "KERN_PFADE", pfade), mock.patch.object(D, "kern_zustand", return_value=zustand), \
                    mock.patch.object(G, "einreichen", side_effect=einreichen, create=True):
                code = self.einreichen(self.ZEILE, kanal="kern")
                if erwartet:
                    self.assertEqual((code, self.ereignis("einreichen_fehler")[0]["grund"]), (D.EXIT_ABGEWIESEN, erwartet))
                else:
                    self.assertEqual(code, D.EXIT_OK)
        arten = [e["ereignis"] for e in K.zaehler_lesen(pfade.zaehler)]
        self.assertEqual(arten, ["versuch", "einreichen", "eingereicht"])
        self.assertEqual(K.zaehler_lesen(pfade.zaehler)[-1]["pr"], 3)
        self.assertNotIn(TOKEN, pfade.zaehler.read_text())


# ---------------------------------------------------------------- Aufräumen (C.10.4)
class AufraeumenTests(DispatcherBasis):
    def test_alter_zustand_und_projektordner(self):
        jetzt = time.time()
        faelle = {"0000000000000001": ("eingereicht", 2 * 86400, True), "0000000000000002": ("verworfen", 3600, False),
                  "0000000000000003": ("bereit", 2 * 86400, False), "0000000000000004": ("bereit", 8 * 86400, True),
                  "0000000000000005": ("keine", 8 * 86400, True)}
        for job, (status, alter, _) in faelle.items():
            jobdir = self.auftrag(job=job, status=status, projekt=f"kern-1a2b3c4d-p{job[-1]}")
            (jobdir / "basis.git").mkdir()
            (jobdir / "bundle.ein").write_bytes(b"x")
            for name in ("aenderung.json", "auftrag.json"):
                os.utime(jobdir / name, (jetzt - alter, jetzt - alter))
            projekt = self.projekte / f"kern-1a2b3c4d-p{job[-1]}"
            projekt.mkdir()
            (projekt / "code.py").write_text("privat", encoding="utf-8")
            D.eigner_schreiben(projekt.name, job)
        app = self.auftrag(job="0000000000000009", github=None, projekt="kern-1a2b3c4d-app")
        (app / "basis.git").mkdir()
        os.utime(app / "auftrag.json", (jetzt - 30 * 86400, jetzt - 30 * 86400))
        ergebnis = D.github_aufraeumen(jetzt=jetzt)
        for job, (status, _, weg) in faelle.items():
            with self.subTest(job=job, status=status):
                self.assertEqual(not (self.jobs / job / "basis.git").exists(), weg)
                self.assertEqual(not (self.jobs / job / "bundle.ein").exists(), weg)
                self.assertEqual(not (self.projekte / f"kern-1a2b3c4d-p{job[-1]}" / "code.py").exists(), weg)
                if weg and status != "eingereicht":
                    self.assertEqual(json.loads((self.jobs / job / "aenderung.json").read_text())["status"], "verworfen")
        self.assertTrue((app / "basis.git").exists())  # Aufträge ohne persönlichen Weg bleiben unberührt
        self.assertEqual((ergebnis["auftraege"], ergebnis["projekte"]), (3, 3))
        alles = D.github_aufraeumen(alle=True, jetzt=jetzt)
        self.assertEqual(alles["auftraege"], 2)
        for job in faelle:
            self.assertFalse((self.jobs / job / "basis.git").exists())

    def test_aktive_auftraege_bleiben(self):
        jobdir = self.auftrag(status="eingereicht")
        (jobdir / "basis.git").mkdir()
        with mock.patch.object(D, "Sperre", _BelegteSperre):
            self.assertEqual(D.github_aufraeumen(alle=True)["uebersprungen"], 1)
        self.assertTrue((jobdir / "basis.git").exists())

    def test_nur_lokal(self):
        for kanal in ("pc", "kern"):
            with mock.patch.object(D, "KANAL", kanal), self.assertRaises(D.Abgewiesen):
                D.cmd_aufraeumen("alle")
        with mock.patch.object(D, "KANAL", "lokal"):
            self.assertEqual(D.cmd_aufraeumen(), D.EXIT_OK)
        self.assertTrue(self.ereignisse[-1]["ok"])


class PingTests(DispatcherBasis):
    def test_ping_meldet_version_und_persoenlich(self):
        for persoenlich in (False, True):
            zustand = K.KernZustand(notaus=False, konfig=K.Konfig(kanal="offen", persoenlich=persoenlich), grund=None)
            self.ereignisse.clear()
            with mock.patch.object(D, "kern_zustand", return_value=zustand), mock.patch.object(D, "lese_geheimnisse", return_value={}):
                D.cmd_ping()
            self.assertEqual(self.ereignisse[0]["version"], "10")
            self.assertIs(self.ereignisse[0]["persoenlich"], persoenlich)
        with mock.patch.object(D, "kern_zustand", side_effect=RuntimeError), mock.patch.object(D, "lese_geheimnisse", return_value={}):
            D.cmd_ping()
        self.assertIs(self.ereignisse[-1]["persoenlich"], False)


# ---------------------------------------------------------------- Befunde der Reviews (Absturz, falsche Reihenfolge, Felder, Zähler)
class ReviewTests(DispatcherBasis):
    def test_halber_klon_nach_absturz_gilt_als_erster_lauf(self):
        jobdir = self.auftrag()
        (jobdir / "basis.git").mkdir()
        self.assertFalse(D.klon_vorhanden(JOB, "octo/demo"))  # basis.git ohne github.json
        self.github_json(jobdir)
        self.assertTrue(D.klon_vorhanden(JOB, "octo/demo"))
        self.assertFalse(D.klon_vorhanden(JOB, "octo/anders"))
        (jobdir / "github.json").write_text("{kaputt", encoding="utf-8")
        self.assertFalse(D.klon_vorhanden(JOB, "octo/demo"))

    def test_github_zeile_an_falscher_stelle_wird_nie_zu_bytes(self):
        for lesen, fehler in ((D._kopfzeile_lesen, D.Abgewiesen), (D._zugangszeile_lesen, D.ZugangUngueltig),
                              (D._einreichen_zeile_lesen, D.Abgewiesen)):
            leser = leser_mit(github_zeile())
            with self.subTest(lesen=lesen.__name__), mock.patch.object(D, "LESER", leser), self.assertRaises(fehler):
                lesen()
            self.assertNotIn(b"ghp_", bytes(leser.puffer))
            os.close(leser.fd)

    def test_einreichen_ohne_erste_zeile_meldet_einen_fehler(self):
        self.auftrag(status="bereit")
        leser = leser_mit(b"")
        with mock.patch.object(D, "LESER", leser), mock.patch.object(D, "KANAL", "lokal"):
            self.assertEqual(D.cmd_einreichen(JOB, PROFIL), D.EXIT_ABGEWIESEN)
        os.close(leser.fd)
        self.assertEqual(self.ereignis("einreichen_fehler")[0]["grund"], "bestaetigung")

    def test_aenderung_gibt_nur_gepruefte_felder_weiter(self):
        jobdir = self.auftrag()
        roh = {"job": JOB, "status": "bereit", "commit_id": "c" * 40, "tree_id": "kein hex", "zweig": "main", "dateien": -1, "plus": 3,
               "pr": 7, "adresse": "https://github.com/octo/demo/pull/7", "lauf": "irgendwie", "gruende": ["pfad_gesperrt", "erfunden"],
               "titel": "Titel mit " + TOKEN + "\u202e", "liste": [{"pfad": "a/" + TOKEN, "art": "neu", "klasse": "sensibel", "plus": 1},
                                                              {"pfad": "b", "art": "kaputt", "klasse": "normal"}, "kein dict"]}
        (jobdir / "aenderung.json").write_text(json.dumps(roh), encoding="utf-8")
        feld = D.aenderung_lesen(jobdir)
        self.assertEqual(feld["commit_id"], "c" * 40)
        for weg in ("tree_id", "zweig", "dateien", "lauf"):
            self.assertNotIn(weg, feld)
        self.assertEqual((feld["plus"], feld["pr"], feld["adresse"]), (3, 7, "https://github.com/octo/demo/pull/7"))
        self.assertEqual(feld["gruende"], ["pfad_gesperrt"])
        self.assertNotIn("ghp_", json.dumps(feld))
        self.assertNotIn("\u202e", feld["titel"])
        self.assertEqual([e["art"] for e in feld["liste"]], ["neu"])
        roh["adresse"] = "https://evil.example/pull/7"
        (jobdir / "aenderung.json").write_text(json.dumps(roh), encoding="utf-8")
        self.assertNotIn("adresse", D.aenderung_lesen(jobdir))

    def test_versuche_von_einreichen_zaehlen_nur_je_profil(self):
        jetzt = time.time()
        konfig = K.Konfig(kanal="offen", max_versuch_stunde=2, max_start_stunde=50, max_start_tag=50, min_abstand_s=0)
        einreichen = [{"t": int(jetzt) - 10, "job": "0" * 16, "ereignis": "versuch", "profil": "99999999", "befehl": "einreichen"}] * 5
        self.assertIsNone(K.pruefe_grenzen(konfig, einreichen, JOB, jetzt, 100000, PROFIL))  # andere Personen bleibt der Start
        with tempfile.TemporaryDirectory() as tmp:
            zaehler = Path(tmp) / "z.jsonl"
            K.zaehler_schreiben(zaehler, JOB, "versuch", jetzt, profil=PROFIL, befehl="einreichen")
            self.assertEqual(K.zaehler_lesen(zaehler)[0]["befehl"], "einreichen")
            with self.assertRaises(ValueError):
                K.zaehler_schreiben(zaehler, JOB, "start", jetzt, befehl="einreichen")
        zustand = K.KernZustand(notaus=False, konfig=K.Konfig(kanal="offen", persoenlich=True, max_versuch_stunde_profil=3), grund=None)
        eigene = [{"t": int(jetzt) - 10, "job": "0" * 16, "ereignis": "versuch", "profil": PROFIL, "befehl": "einreichen"}] * 3
        self.assertEqual(K.pruefe_einreichen(zustand, ereignisse=eigene, jetzt=jetzt, profil=PROFIL), "grenze_profil")

    def test_aufraeumen_liest_den_zustand_unter_den_sperren_neu_und_behaelt_den_eigner_bei_misserfolg(self):
        jetzt = time.time()
        jobdir = self.auftrag(status="bereit", projekt="kern-1a2b3c4d-p1")
        (jobdir / "basis.git").mkdir()
        for name in ("aenderung.json", "auftrag.json"):
            os.utime(jobdir / name, (jetzt - 8 * 86400, jetzt - 8 * 86400))
        projekt = self.projekte / "kern-1a2b3c4d-p1"
        projekt.mkdir()
        (projekt / "x").write_text("x", encoding="utf-8")
        D.eigner_schreiben(projekt.name, JOB)

        class SperreMitEinreichen(_Sperre):  # während auf die Sperre gewartet wird, wird der Auftrag eingereicht (frische Datei)
            def versuchen(self):
                (jobdir / "aenderung.json").write_text(json.dumps({"job": JOB, "status": "eingereicht"}), encoding="utf-8")
                return True
        with mock.patch.object(D, "Sperre", SperreMitEinreichen):
            D.github_aufraeumen(jetzt=jetzt)
        self.assertTrue((jobdir / "basis.git").exists())
        self.assertEqual(json.loads((jobdir / "aenderung.json").read_text())["status"], "eingereicht")
        with mock.patch.object(D, "projekt_leeren_ganz", return_value=False):
            D.github_aufraeumen(alle=True, jetzt=jetzt)
        self.assertEqual(D.eigner_lesen(projekt.name), JOB)  # nicht leer: der nächste Lauf versucht es erneut
        D.github_aufraeumen(alle=True, jetzt=jetzt)
        self.assertIsNone(D.eigner_lesen(projekt.name))
        self.assertEqual(list(projekt.iterdir()), [])

    @unittest.skipUnless(LINUX, "Rechte 000 nur unter Linux prüfbar")
    def test_ordner_mit_entzogenen_rechten_halten_das_loeschen_nicht_auf(self):
        projekt = self.projekte / "kern-1a2b3c4d-p2"
        (projekt / "a" / "b").mkdir(parents=True)
        (projekt / "a" / "b" / "c.txt").write_text("privat", encoding="utf-8")
        os.chmod(projekt / "a" / "b", 0)
        os.chmod(projekt / "a", 0)
        self.assertTrue(D.projekt_leeren_ganz(projekt))
        jobdir = self.auftrag()
        (jobdir / "basis.git" / "objects").mkdir(parents=True)
        os.chmod(jobdir / "basis.git" / "objects", 0)
        D.github_dateien_entfernen(jobdir)
        self.assertFalse((jobdir / "basis.git").exists())

    def test_main_setzt_den_leser_zurueck(self):
        leser = leser_mit(b"")
        with mock.patch.object(D, "LESER", leser), mock.patch.object(D, "kanal_ermitteln", return_value="lokal"), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSH_CONNECTION", None)
            os.environ.pop("SSH_ORIGINAL_COMMAND", None)
            D.main(["ping"])
            self.assertIsNone(D.LESER)
        os.close(leser.fd)


if __name__ == "__main__":
    unittest.main()
