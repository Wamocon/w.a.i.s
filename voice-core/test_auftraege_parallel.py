"""Gleichzeitige Entwicklungsaufträge (Dispatcher 9, Entscheidung von Niko 16.11.2026: sechs gesamt, je Person drei).

Geprüft wird alles, was früher stillschweigend von genau einem laufenden Auftrag ausging:
  * Grenzen: harte Obergrenze im Dispatcher, MAX_PARALLEL und MAX_PARALLEL_PROFIL in kernkanal.conf (nur senken), Plätze und Grenze je
    Person über Sperren (PC-Kanal und lokal zählen je als eine Person), Ereignis belegt mit einem Code aus BELEGT_GRENZEN.
  * Trennung gleichzeitiger Sandboxes: jeder Platz bekommt einen eigenen Teil der Entwicklungsports, Landlock (abschottung.py) erlaubt
    Binden und Verbinden im Bereich 20000 bis 20999 nur dort; wamo-job.sh reicht den Bereich durch, der Selbsttest prüft ihn.
  * Laufzeit je Tag: ein laufender Auftrag reserviert sein Zeitlimit (zwei gleichzeitige Starts überschreiten die Grenze nicht gemeinsam).
  * Kern: Sätze je Grenze, Kosten je Profil (Prüfen und Anlegen je Profil hintereinander, kein gemeinsames Überschreiten der Tagesgrenze).

Ausführen (im Ordner voice-core/):  python -m pytest -q test_auftraege_parallel.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import entwicklung_betrieb as eb

VOICE_CORE = Path(__file__).resolve().parent
INFRA = VOICE_CORE.parent / "infra" / "sokrates2"


def _lade(name: str, datei: str):
    spec = importlib.util.spec_from_file_location(name, INFRA / datei)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


K = _lade("wamo_job_kernkanal", "wamo_job_kernkanal.py")
D = _lade("wamo_job_dispatch_parallel", "wamo_job_dispatch.py")
A = _lade("abschottung_parallel", "abschottung.py")
JETZT = 1_800_000_000.0
JOB = "abc1234567890def"
PROFIL_A, PROFIL_B = "1a2b3c4d", "9f8e7d6c"


def _bash() -> str | None:
    kandidaten = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"]
    return next((k for k in kandidaten if k and Path(k).is_file()), None)


BASH = _bash()


def _text(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8").replace("\r\n", "\n")


# ================================================================== Konfiguration und Grenzen (Modul des Kern-Kanals)
def _attrappe(text: str):
    import os
    daten = text.encode("utf-8")
    return lambda pfad, limit: (daten, os.stat_result((0o100640, 0, 0, 1, 0, 0, len(daten), 0, 0, 0)))  # root, 0640


def lese(text: str) -> "K.Konfig":
    return K.konfig_lesen("/t/kernkanal.conf", jetzt=JETZT, lesen=_attrappe(text))


def test_die_harte_obergrenze_ist_sechs_auf_beiden_seiten_und_die_konfiguration_kann_sie_nur_senken():
    assert K.PARALLEL_HART == D.PARALLEL_MAX == 6
    assert K.ZAHLEN["MAX_PARALLEL"] == (1, 6) and K.ZAHLEN["MAX_PARALLEL_PROFIL"] == (1, 6)
    std = K.Konfig()
    # fehlen die Schlüssel, gilt einer gleichzeitig (Befund des Sicherheitsreviews: Dispatcher 9 allein schaltet nichts frei); die Standards
    # 6 und 3 (Entscheidung: sechs gesamt, je Person drei) schreibt das Skript mit schluessel oder kanal
    assert (std.max_parallel, std.max_parallel_profil) == (1, 1)
    sechs = lese("MAX_PARALLEL=6\nMAX_PARALLEL_PROFIL=3\n")
    assert (sechs.max_parallel, sechs.max_parallel_profil) == (6, 3)
    assert (lese("MAX_PARALLEL=2\nMAX_PARALLEL_PROFIL=1\n").max_parallel, lese("MAX_PARALLEL=2\n").max_parallel_profil) == (2, 1)
    for schlecht in ("MAX_PARALLEL=7\n", "MAX_PARALLEL=0\n", "MAX_PARALLEL_PROFIL=0\n", "MAX_PARALLEL_PROFIL=7\n", "MAX_PARALLEL=x\n"):
        with pytest.raises(K.KonfigFehler):
            lese(schlecht)


def test_je_person_nie_mehr_als_gesamt():
    with pytest.raises(K.KonfigFehler, match="MAX_PARALLEL_PROFIL"):
        lese("MAX_PARALLEL=2\nMAX_PARALLEL_PROFIL=3\n")  # der Standard 3 je Person liegt über 2 gesamt: der Betreiber muss ihn senken
    assert lese("MAX_PARALLEL=3\nMAX_PARALLEL_PROFIL=3\n").max_parallel_profil == 3


def _zustand(text: str | None):
    if text is None:
        return K.KernZustand(False, None, "konfig_ungueltig")
    return K.KernZustand(False, lese(text), None)


def test_die_wirksamen_grenzen_ohne_konfiguration_ist_es_einer_wie_bisher():
    assert K.parallel_grenzen(None) == (1, 1)
    assert K.parallel_grenzen(_zustand(None)) == (1, 1)  # fehlt oder fehlerhaft: fail closed wie bis Dispatcher 8
    assert K.parallel_grenzen(_zustand("")) == (1, 1)  # gültige Datei ohne die Schlüssel: einer wie bisher
    assert K.parallel_grenzen(_zustand("MAX_PARALLEL=6\nMAX_PARALLEL_PROFIL=3\n")) == (6, 3)
    assert K.parallel_grenzen(_zustand("MAX_PARALLEL=4\nMAX_PARALLEL_PROFIL=2\n")) == (4, 2)
    assert K.parallel_grenzen(_zustand("MAX_PARALLEL=6\nMAX_PARALLEL_PROFIL=3\n"), hart=2) == (2, 2)  # die harte Grenze gewinnt
    notaus = K.KernZustand(True, lese("MAX_PARALLEL=2\nMAX_PARALLEL_PROFIL=2\n"), "notaus")
    assert K.parallel_grenzen(notaus) == (2, 2)  # der Notaus sperrt den Kern-Kanal selbst, die Plätze des PC-Kanals bleiben


@pytest.mark.parametrize("kanal, profil, erwartet", [
    ("kern", PROFIL_A, PROFIL_A), ("kern", None, None), ("kern", "1A2B3C4D", None), ("kern", "../x", None),
    ("pc", None, "pc"), ("pc", PROFIL_A, "pc"),  # der PC-Kanal zählt als eine Person, auch wenn die Kopfzeile ein Profil nennt
    ("lokal", None, "lokal"), ("lokal", PROFIL_A, "lokal"), ("unklar", PROFIL_A, None), (None, None, None),
])
def test_wer_als_person_zaehlt(kanal, profil, erwartet):
    assert K.person_schluessel(kanal, profil) == erwartet
    if erwartet is not None:
        assert K.PERSON_RE.fullmatch(erwartet)


def test_die_codes_im_ereignis_belegt():
    assert K.BELEGT_GRENZEN == ("auftrag", "projekt", "gesamt", "profil")


# ---------------------------------------------------------------- Laufzeit: laufende Aufträge reservieren ihr Zeitlimit
def _start(alter_s: float, job: str, profil: str | None = PROFIL_A) -> dict:
    return {"t": int(JETZT - alter_s), "job": job, "ereignis": "start", **({"profil": profil} if profil else {})}


def _ende(alter_s: float, dauer: int, job: str, profil: str | None = PROFIL_A) -> dict:
    return {"t": int(JETZT - alter_s), "job": job, "ereignis": "ende", "dauer_s": dauer, **({"profil": profil} if profil else {})}


def test_offene_starts_ein_ende_schliesst_den_juengsten_start_desselben_auftrags():
    a, b = "a" * 16, "b" * 16
    ereignisse = [_start(900, a), _ende(800, 100, a), _start(700, a), _start(600, b)]
    assert [(e["job"], e["t"]) for e in K.offene_starts(ereignisse)] == [(a, int(JETZT - 700)), (b, int(JETZT - 600))]
    verloren = [_start(900, a), _start(500, a), _ende(400, 100, a)]  # der erste Lauf endete nie (SIGKILL), der zweite schon
    assert [e["t"] for e in K.offene_starts(verloren)] == [int(JETZT - 900)]
    assert K.offene_starts([_ende(10, 5, a)]) == []


def _konfig(**werte) -> "K.Konfig":
    return lese("".join(f"{k}={v}\n" for k, v in {"MIN_ABSTAND_S": "0", "MAX_START_STUNDE": "60", "MAX_START_TAG": "200",
                                                    "MAX_NEU_STUNDE_PROFIL": "60", "MAX_NEU_TAG_PROFIL": "200", **werte}.items()))


def test_ein_laufender_auftrag_reserviert_sein_zeitlimit_in_der_laufzeit_je_tag():
    konfig = _konfig(MAX_LAUFZEIT_TAG_S="7200", MAX_LAUFZEIT_TAG_S_PROFIL="7200")
    laufend = [_start(60, "a" * 16)]
    assert K.pruefe_grenzen(konfig, laufend, JOB, JETZT, 50_000, PROFIL_A, laufzeit_reserve_s=3600) is None
    zwei = laufend + [_start(30, "b" * 16, PROFIL_B)]  # zwei gleichzeitige Läufe zweier Personen: 2 x 3600 erreicht die Gesamtgrenze
    assert K.pruefe_grenzen(konfig, zwei, JOB, JETZT, 50_000, "0a0b0c0d", laufzeit_reserve_s=3600) == "grenze_laufzeit"
    beendet = [_start(4000, "a" * 16), _ende(3000, 1000, "a" * 16)]  # nach dem Ende zählt die echte Dauer statt der Reserve
    assert K.pruefe_grenzen(konfig, beendet + [_start(30, "b" * 16, PROFIL_B)], JOB, JETZT, 50_000, "0a0b0c0d",
                            laufzeit_reserve_s=3600) is None


def test_die_laufzeit_je_profil_zaehlt_die_eigenen_laufenden_auftraege():
    konfig = _konfig(MAX_LAUFZEIT_TAG_S_PROFIL="5400")
    eigen = [_start(60, "a" * 16), _start(50, "b" * 16)]
    assert K.pruefe_grenzen(konfig, eigen, JOB, JETZT, 50_000, PROFIL_A, laufzeit_reserve_s=1800) is None  # 3600 < 5400
    drei = eigen + [_start(40, "c" * 16)]
    assert K.pruefe_grenzen(konfig, drei, JOB, JETZT, 50_000, PROFIL_A, laufzeit_reserve_s=1800) == "grenze_profil"
    assert K.pruefe_grenzen(konfig, drei, JOB, JETZT, 50_000, PROFIL_B, laufzeit_reserve_s=1800) is None  # andere Person
    assert K.pruefe_grenzen(konfig, [_start(90000, "a" * 16)] * 4, JOB, JETZT, 50_000, PROFIL_A, laufzeit_reserve_s=1800) is None  # älter als ein Tag


def test_ohne_angabe_reserviert_die_pruefung_das_standardzeitlimit():
    konfig = _konfig(MAX_LAUFZEIT_TAG_S="3600", MAX_LAUFZEIT_TAG_S_PROFIL="3600")
    assert K.LAUFZEIT_RESERVE_STANDARD_S == 1800
    assert K.pruefe_grenzen(konfig, [_start(10, "a" * 16)], JOB, JETZT, 50_000, PROFIL_A) is None
    assert K.pruefe_grenzen(konfig, [_start(10, "a" * 16), _start(10, "b" * 16, PROFIL_B)], JOB, JETZT, 50_000, "0a0b0c0d") \
        == "grenze_laufzeit"
    with pytest.raises(ValueError):
        K.pruefe_grenzen(konfig, [], JOB, JETZT, 50_000, PROFIL_A, laufzeit_reserve_s=-1)


# ================================================================== Landlock: eigene Entwicklungsports je Platz
def test_der_bereich_eines_platzes():
    assert A.parse_bereich("20100-20199") == range(20100, 20200)
    for schlecht in ("20000-21000", "19999-20050", "20100-20099", "20000-20100", "x", "20100", "20100-", "-20199", " 20100-20199",
                     "020100-20199", "20050-20149", "20100-20150", "20101-20199"):  # nie über die Grenze zweier Plätze, immer volle Breite
        with pytest.raises(ValueError):
            A.parse_bereich(schlecht)


def test_landlock_erlaubt_im_entwicklungsbereich_nur_den_eigenen_teil():
    eigen = range(20100, 20200)
    z = A.port_zugriff({22, 55322, 20150}, eigen)
    beides = A.LANDLOCK_ACCESS_NET_BIND_TCP | A.LANDLOCK_ACCESS_NET_CONNECT_TCP
    assert z[20100] == z[20199] == beides
    assert z[20150] == A.LANDLOCK_ACCESS_NET_BIND_TCP  # auf dem Host belegt: verbinden gesperrt, binden erlaubt
    for fremd in (20000, 20099, 20200, 20500, 20999):  # Ports gleichzeitiger Aufträge: weder binden noch verbinden
        assert fremd not in z, fremd
    assert z[443] == z[80] == A.LANDLOCK_ACCESS_NET_CONNECT_TCP  # außerhalb des Entwicklungsbereichs: verbinden wie bisher
    assert 22 not in z and 55322 not in z
    assert not [p for p, a in z.items() if a & A.LANDLOCK_ACCESS_NET_BIND_TCP and p not in eigen]


def test_die_abschottung_startet_nur_mit_dem_eigenen_bereich():
    assert A.parse_args(["--sperrports", "1,2", "--entwicklungsports", "20000-20099", "--", "claude", "-p"]) \
        == ({1, 2}, range(20000, 20100), ["claude", "-p"])
    for schlecht in (["--sperrports", "1", "--", "x"], ["--entwicklungsports", "20000-20099", "--sperrports", "1", "--", "x"],
                     ["--sperrports", "1", "--entwicklungsports", "20000-21000", "--", "x"],
                     ["--sperrports", "1", "--entwicklungsports", "20000-20099", "--"]):
        with pytest.raises(ValueError):
            A.parse_args(schlecht)
    with mock.patch.object(A, "abschotten") as abschotten, mock.patch.object(A.os, "execvp") as execvp, mock.patch("sys.stderr"):
        assert A.main(["--sperrports", "22", "--", "claude"]) == A.EXIT_FEHLER  # ohne Bereich: fail closed
    abschotten.assert_not_called()
    execvp.assert_not_called()


# ================================================================== Läufer wamo-job.sh
@pytest.fixture(scope="module")
def runner() -> str:
    return _text(INFRA / "wamo-job.sh")


def _bash_funktion(skript: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", skript, re.M | re.S)
    assert m, f"Funktion {name} fehlt im Läufer"
    return m.group(0)


@pytest.mark.skipif(BASH is None, reason="bash fehlt")
@pytest.mark.parametrize("platz, erwartet", [("0", "20000 20099"), ("1", "20100 20199"), ("5", "20500 20599"), ("9", "20900 20999")])
def test_der_laeufer_berechnet_den_bereich_des_platzes(runner, platz, erwartet):
    kopf = "set -euo pipefail\nfehler() { echo \"wamo-job.sh: $*\" >&2; exit 70; }\n"
    p = subprocess.run([BASH, "-c", kopf + _bash_funktion(runner, "platz_ports") + f'\nplatz_ports {platz}\necho "$PORT_VON $PORT_BIS"\n'],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stdout.strip() == erwartet, p.stderr


@pytest.mark.skipif(BASH is None, reason="bash fehlt")
@pytest.mark.parametrize("platz", ["", "10", "-1", "a", "1 ", "01", "$(id)"])
def test_der_laeufer_lehnt_einen_unbekannten_platz_ab(runner, platz):
    kopf = "set -euo pipefail\nfehler() { echo \"wamo-job.sh: $*\" >&2; exit 70; }\n"
    p = subprocess.run([BASH, "-c", kopf + _bash_funktion(runner, "platz_ports") + '\nplatz_ports "$1"\necho erreicht\n', "probe", platz],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 70 and "erreicht" not in p.stdout, (platz, p.stdout, p.stderr)


def test_der_laeufer_braucht_den_platz_und_gibt_den_bereich_an_landlock_und_die_sandbox(runner):
    assert "--platz) PLATZ=${2-}; shift 2 ;;" in runner
    assert 'platz_ports "$PLATZ"' in runner
    assert '--entwicklungsports "$PORT_VON-$PORT_BIS"' in runner
    lauf_env = runner[runner.index("SETENV_LAUF=("):]
    lauf_env = lauf_env[:lauf_env.index("\n)\n")]
    assert '--setenv WAMO_PORT_VON "$PORT_VON" --setenv WAMO_PORT_BIS "$PORT_BIS"' in lauf_env
    pruefen_env = runner[runner.index("SETENV_PRUEFEN=("):]
    assert "WAMO_" not in pruefen_env[:pruefen_env.index("\n)\n")]  # der Selbsttest im Modus pruefen verlangt eine Umgebung ohne WAMO_*
    kopf = runner[:runner.index("set -euo pipefail")]
    assert "höchstens einer gleichzeitig" not in kopf and "eigenen Teil der Entwicklungsports" in kopf


# ================================================================== Dispatcher: Plätze und Grenze je Person
class SimSperre:
    """flock wie zwischen Prozessen: ein Pfad gehört höchstens einem Objekt, bis dessen Datei geschlossen ist."""

    gehalten: dict[str, "SimSperre"] = {}
    versucht: list[str] = []

    class _Datei:
        def __init__(self, sperre: "SimSperre"):
            self.sperre = sperre

        def close(self) -> None:
            if SimSperre.gehalten.get(self.sperre.pfad) is self.sperre:
                del SimSperre.gehalten[self.sperre.pfad]

    def __init__(self, pfad):
        self.pfad, self.datei = str(pfad), None

    def versuchen(self) -> bool:
        SimSperre.versucht.append(Path(self.pfad).name)
        inhaber = SimSperre.gehalten.get(self.pfad)
        if inhaber is not None and inhaber is not self:
            return False
        SimSperre.gehalten[self.pfad] = self
        self.datei = SimSperre._Datei(self)
        return True


@pytest.fixture()
def sperren(tmp_path, monkeypatch):
    SimSperre.gehalten, SimSperre.versucht = {}, []
    monkeypatch.setattr(D, "Sperre", SimSperre)
    return tmp_path


def freigeben(gehalten: list) -> None:
    for s in gehalten:
        D._sperre_freigeben(s)


def test_jeder_platz_hat_einen_eigenen_teil_der_entwicklungsports():
    bereiche = [D.platz_ports(i) for i in range(D.PARALLEL_MAX)]
    assert bereiche[0] == range(20000, 20100) and bereiche[5] == range(20500, 20600)
    alle = [p for b in bereiche for p in b]
    assert len(alle) == len(set(alle)) and set(alle) <= set(D.ENTWICKLUNGS_PORTS)
    assert D.PORTS_JE_PLATZ == 100 and D.PARALLEL_MAX * D.PORTS_JE_PLATZ <= len(D.ENTWICKLUNGS_PORTS)


def test_sechs_plaetze_gesamt_und_drei_je_person(sperren):
    laeufe = []
    for person in (PROFIL_A, PROFIL_A, PROFIL_A):
        gehalten, platz, grenze = D.plaetze_belegen(sperren, person, 6, 3)
        assert grenze is None and len(gehalten) == 2
        laeufe.append((gehalten, platz))
    assert [p for _, p in laeufe] == [0, 1, 2]
    assert D.plaetze_belegen(sperren, PROFIL_A, 6, 3) == ([], None, "profil")  # die vierte eigene: Grenze je Person
    for person in (PROFIL_B, "pc", "lokal"):
        gehalten, platz, grenze = D.plaetze_belegen(sperren, person, 6, 3)
        assert grenze is None
        laeufe.append((gehalten, platz))
    assert [p for _, p in laeufe] == [0, 1, 2, 3, 4, 5]
    assert D.plaetze_belegen(sperren, "0a0b0c0d", 6, 3) == ([], None, "gesamt")  # alle Plätze belegt
    freigeben(laeufe[1][0])  # ein Auftrag endet: sein Platz und sein Platz je Person werden frei
    gehalten, platz, grenze = D.plaetze_belegen(sperren, PROFIL_A, 6, 3)
    assert (platz, grenze) == (1, None)
    assert not [p for p in SimSperre.gehalten if Path(p).name == D.PLAETZE_SPERRE]  # die Sperre zum Zählen ist wieder frei


def test_eine_gesenkte_grenze_zaehlt_auch_plaetze_ueber_der_neuen_grenze(sperren):
    """Läufe auf Platz 4 und 5 (vor dem Senken gestartet) zählen gegen eine neue Grenze von 2: ein dritter Start wartet."""
    hoch = []
    for i in range(6):
        gehalten, platz, _ = D.plaetze_belegen(sperren, f"{i:x}" * 8, 6, 3)
        hoch.append(gehalten)
    for gehalten in hoch[:4]:
        freigeben(gehalten)
    assert D.plaetze_belegen(sperren, PROFIL_A, 2, 2) == ([], None, "gesamt")
    freigeben(hoch[4])
    assert D.plaetze_belegen(sperren, PROFIL_A, 2, 2)[1:] == (0, None)


def test_eine_ungueltige_person_wird_abgewiesen(sperren):
    for person in ("", "../x", "PC", "1a2b3c4d/", None):
        with pytest.raises(D.Abgewiesen):
            D.plaetze_belegen(sperren, person, 6, 3)
    assert SimSperre.versucht == []


def test_der_dispatcher_liest_die_grenzen_aus_der_konfiguration_und_faellt_geschlossen_zurueck(monkeypatch):
    monkeypatch.setattr(D, "kern_modul", lambda: K)  # andere Testdateien laden ein eigenes Exemplar des Moduls unter demselben Namen
    monkeypatch.setattr(D, "kern_zustand", lambda: _zustand("MAX_PARALLEL=4\nMAX_PARALLEL_PROFIL=2\n"))
    assert D.parallel_grenzen() == (4, 2)
    monkeypatch.setattr(D, "kern_zustand", lambda: _zustand(None))
    assert D.parallel_grenzen() == (1, 1)

    def kaputt():
        raise RuntimeError("Modul defekt")
    monkeypatch.setattr(D, "kern_zustand", kaputt)
    assert D.parallel_grenzen() == (1, 1)


@pytest.mark.parametrize("grenze, n, teil", [("gesamt", 6, "6 Aufträge"), ("gesamt", 1, "ein Auftrag"), ("profil", 3, "3 eigene"),
                                             ("profil", 1, "ein eigener"), ("auftrag", None, "Dieser Auftrag"),
                                             ("projekt", None, "Im Projekt")])
def test_das_ereignis_belegt_traegt_code_und_grenze(monkeypatch, grenze, n, teil):
    ereignisse = []
    monkeypatch.setattr(D, "emit", lambda ev: ereignisse.append(ev) or True)
    D.belegt_melden(grenze, n)
    (ev,) = ereignisse
    assert ev["ereignis"] == "belegt" and ev["grenze"] == grenze and teil in ev["grund"]
    assert ev.get("max") == n


def test_der_hinweis_fuer_claude_code_nennt_den_eigenen_bereich():
    hinweis = D.port_hinweis(2)
    assert "20200" in hinweis and "20299" in hinweis and "WAMO_PORT_VON" in hinweis and "127.0.0.1" in hinweis
    assert not re.search(r"[–—]| - ", hinweis)


# ---------------------------------------------------------------- Selbsttest: der eigene Bereich offen, ein fremder zu
def test_der_selbsttest_prueft_eigenen_und_fremden_bereich(monkeypatch, tmp_path):
    aufrufe = []
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "/opt/wamo/hook"}]}]}}), encoding="utf-8")

    class Probe:
        def __init__(self, port):
            self.port = port

        def getsockname(self):
            return ("127.0.0.1", self.port)

        def close(self):
            pass

    def lauscher(platz):
        aufrufe.append(("lauscher", platz))
        return Probe(D.platz_ports(platz)[7])

    def run(argv, **kw):
        aufrufe.append(("run", argv))
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setattr(D, "MANAGED", managed)
    monkeypatch.setattr(D, "probe_lauscher", lauscher)
    monkeypatch.setattr(D, "docker_bruecke", lambda: "172.17.0.1")
    monkeypatch.setattr(D.subprocess, "run", run)
    ok, grund = D.selbsttest(JOB, "rezepte-app", "lauf", 2)
    assert not ok  # die Attrappe der Sandbox liefert nichts: der Test gilt als nicht bestanden
    (_, argv), = [a for a in aufrufe if a[0] == "run"]
    assert argv[argv.index("--platz") + 1] == "2"
    skript = argv[-1]
    assert " 20207 172.17.0.1 " in skript and " 20299 20399" in skript  # Lauscher, eigener Probeport, fremder Platz
    assert ("lauscher", 2) in aufrufe
    assert D.selbsttest(JOB, "rezepte-app", "lauf", None)[0] is False  # ohne Platz kein Start
    assert {"platz_eigen": "offen", "platz_fremd": "zu", "platz_fremd_bind": "zu"}.items() <= D.NETZ_ERWARTET.items()
    assert D.NETZ_ERWARTET_PRUEFEN["platz_eigen"] == ("offen",) and D.NETZ_ERWARTET_PRUEFEN["platz_fremd"] == ("zu",)


def test_der_probelauscher_liegt_im_eigenen_bereich_ohne_den_probeport():
    s = D.probe_lauscher(3)
    try:
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port in D.platz_ports(3) and port != D.platz_ports(3)[-1]


# ---------------------------------------------------------------- Aufräumen hält die Auftragssperre
def test_aufraeumen_fasst_einen_auftrag_nur_unter_seiner_sperre_an(sperren, monkeypatch):
    import os
    jobs = sperren / "jobs"
    for job in ("a" * 16, "b" * 16):
        (jobs / job / "npm").mkdir(parents=True)
        os.utime(jobs / job / "npm", (0, 0))  # sehr alt
    monkeypatch.setattr(D, "JOBS", jobs)
    laeuft = SimSperre(jobs / ("a" * 16) / ".lauf")
    assert laeuft.versuchen()  # ein anderer Dispatcher hält den Auftrag a (er startet gerade)
    D.aufraeumen()
    assert (jobs / ("a" * 16) / "npm").is_dir() and not (jobs / ("b" * 16) / "npm").exists()
    assert str(jobs / ("b" * 16) / ".lauf") not in SimSperre.gehalten  # wieder frei


# ================================================================== Kern: Sätze je Grenze
def test_der_kern_nennt_die_erreichte_grenze():
    g = eb.ablehn_grund
    gesamt = g(4, {"belegt": {"grund": "Es laufen schon 6 Aufträge (alle Plätze belegt)", "grenze": "gesamt", "max": 6}})
    assert "sechs" in gesamt and "Plätze" in gesamt and "in ein paar Minuten" in gesamt
    profil = g(4, {"belegt": {"grund": "x", "grenze": "profil", "max": 3}})
    assert "drei" in profil and "von dir" in profil
    assert "ein Auftrag von dir" in g(4, {"belegt": {"grenze": "profil", "max": 1}})
    assert "Projekt" in g(4, {"belegt": {"grenze": "projekt"}}) and "Dieser Auftrag" in g(4, {"belegt": {"grenze": "auftrag"}})
    for kaputt in ({"grenze": "gesamt", "max": 99}, {"grenze": "gesamt", "max": "6"}, {"grenze": "gesamt", "max": True},
                   {"grenze": "gesamt"}):
        satz = g(4, {"belegt": kaputt})
        assert "Plätze" in satz and not re.search(r"\d", satz), kaputt  # ohne gültige Zahl: der Satz ohne Zahl
    assert g(4, {"belegt": {"grenze": "unbekannt"}}) == eb.SATZ_BELEGT
    for satz in (gesamt, profil, *eb.BELEGT_SAETZE.values()):
        assert not re.search(r"[–—]| - ", satz)


def test_ein_anderer_auftrag_nur_noch_bei_einem_alten_dispatcher():
    """Ein Dispatcher bis Version 8 kennt nur einen Platz für alle (PARALLEL_MAX = 1) und schickt keinen Code: dann ist wirklich die
    Gesamtgrenze erreicht. Ein Dispatcher 9 nennt die Grenze immer, der alte Satz kommt dann nie."""
    g = eb.ablehn_grund
    assert g(4, {"belegt": {"grund": "Es läuft schon ein Auftrag"}}) == eb.SATZ_ANDERER_AUFTRAG
    for grenze in K.BELEGT_GRENZEN:
        assert g(4, {"belegt": {"grund": "Es läuft schon ein Auftrag", "grenze": grenze, "max": 1}}) != eb.SATZ_ANDERER_AUFTRAG


def test_jede_grenze_des_dispatchers_hat_im_kern_einen_satz():
    assert tuple(eb.BELEGT_SAETZE) == K.BELEGT_GRENZEN


# ================================================================== Kern: Kosten je Profil bei gleichzeitigen Starts
NIKO = "0f6c2b1e-5d1a-4c3e-9a7b-2e8d4f6a1b3c"
MITGLIED = "3c5e7a9b-1d2f-4a6c-8e0b-9d8c7b6a5f4e"


class LangsamerSpeicher:
    """Die Tabelle actions einer Datenbank, auf die mehrere Sitzungen zugleich zugreifen: jeder Aufruf gibt die Ereignisschleife ab (wie
    eine echte Abfrage), laufende Zeilen zählen mindestens mit laufend_usd (wie MemoryStore.tageskosten)."""

    AUTOMAT = {"approved": "pending", "rejected": "pending", "running": "approved", "done": "running", "failed": "running"}

    def __init__(self):
        self.zeilen: dict[str, dict] = {}

    async def _warten(self):
        for _ in range(3):
            await asyncio.sleep(0)

    async def veraltete_schliessen(self, user_id=None, nach_stunden=2, kosten_usd=0.0):
        await self._warten()
        return 0

    async def tageskosten(self, user_id=None, laufend_usd=0.0):
        await self._warten()
        return sum(laufend_usd for z in self.zeilen.values() if z["status"] == "running" and z["user"] == self._user)

    async def log_action(self, tool, params, reason, risk):
        await self._warten()
        aktion = f"a{len(self.zeilen) + 1}"
        self.zeilen[aktion] = {"status": "pending", "user": self._user}
        return aktion

    async def update_action(self, action_id, status):
        await self._warten()
        zeile = self.zeilen[action_id]
        if zeile["status"] != self.AUTOMAT[status]:
            return False
        zeile["status"] = status
        return True

    async def aktion_abschliessen(self, action_id, status, result):
        await self._warten()
        return True


class Sitzung(LangsamerSpeicher):
    """Der Speicher einer Sitzung (MemoryStore je Sitzung, gemeinsame Tabelle): user_id steckt im Objekt."""

    def __init__(self, tabelle: LangsamerSpeicher, user_id: str):
        self.zeilen, self._user = tabelle.zeilen, user_id


async def _zwei_starts(user_a: str, user_b: str) -> list[str | None]:
    tabelle = LangsamerSpeicher()
    buecher = [eb.AuftragsBuch(Sitzung(tabelle, u), eb.BueroZulassung(u)) for u in (user_a, user_b)]
    ergebnisse = await asyncio.gather(*(b.beginnen(f"{i:x}" * 16, "recherche", "kern-x", None, False) for i, b in enumerate(buecher, 1)))
    return [satz for _aktion, satz in ergebnisse]


def test_zwei_gleichzeitige_starts_desselben_profils_ueberschreiten_die_tagesgrenze_nicht_gemeinsam(monkeypatch):
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD", "3")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_TAG_USD", "3")  # Platz für genau einen laufenden Auftrag (0 < 3, danach 3 nicht mehr)
    saetze = asyncio.run(_zwei_starts(NIKO, NIKO))
    assert sorted(saetze, key=lambda s: s or "") == [None, eb.SATZ_TAGESGRENZE]


def test_verschiedene_profile_warten_nicht_aufeinander(monkeypatch):
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD", "3")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_TAG_USD", "3")
    assert asyncio.run(_zwei_starts(NIKO, MITGLIED)) == [None, None]  # jedes Profil hat seine eigene Tagesgrenze


def test_die_sperre_je_profil_gilt_je_ereignisschleife(monkeypatch):
    """asyncio.Lock gehört zu einer Ereignisschleife: ein zweiter Lauf von asyncio.run (Tests, Neustart) bekommt eine neue."""
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD", "3")
    monkeypatch.setenv("WAMO_ENTWICKLUNG_KOSTEN_TAG_USD", "3")
    for _ in range(2):
        assert sorted(asyncio.run(_zwei_starts(NIKO, NIKO)), key=lambda s: s or "") == [None, eb.SATZ_TAGESGRENZE]


# ================================================================== Befunde des Sicherheitsreviews
def test_wer_einen_platz_belegt_beendet_zuerst_die_reste_auf_ihm(monkeypatch):
    """Stirbt ein Dispatcher hart, läuft seine Sandbox weiter, seine Sperren sind frei. Der nächste auf demselben Platz beendet sie, bevor er
    startet: sonst nutzte die Waise den Portbereich des Platzes weiter."""
    aufrufe = []
    monkeypatch.setattr(D.subprocess, "run", lambda argv, **kw: aufrufe.append(list(argv)))
    D.platz_reste_beenden(3)
    assert aufrufe == [["/usr/bin/systemctl", "--user", "stop", "wamo-job-*-p3-*.scope"]]
    for schlecht in (-1, 10, True, "3", None):
        with pytest.raises(ValueError):
            D.platz_reste_beenden(schlecht)
    quelle = _text(INFRA / "wamo_job_dispatch.py")
    for stelle in ("    gehalten += plaetze\n    platz_reste_beenden(platz)", "    platz_reste_beenden(platz)  # Reste eines hart beendeten Vorgängers"
                   " auf diesem Platz\n    return gehalten + plaetze, None, platz"):
        assert stelle in quelle, stelle
    assert 'EINHEIT="wamo-job-$JOB-$ZUSATZ-p$PLATZ-$(date +%s%N)"' in _text(INFRA / "wamo-job.sh")


@pytest.mark.parametrize("inhalt, erwartet", [("32768\t60999\n", True), ("1024 19999\n", True), ("21000 60999", True),
                                               ("10000 30000\n", False), ("20500 20600\n", False), ("x y", False), ("", False)])
def test_der_ephemere_portbereich_darf_die_entwicklungsports_nicht_schneiden(tmp_path, inhalt, erwartet):
    datei = tmp_path / "ip_local_port_range"
    datei.write_text(inhalt, encoding="ascii")
    assert D.ephemere_ports_getrennt(datei) is erwartet


def test_der_rauchtest_platz_liegt_ueber_allen_plaetzen_des_dispatchers():
    quelle = _text(INFRA / "wamo_job_rauchtest.py")
    platz = int(re.search(r"^RAUCHTEST_PLATZ = (\d+)$", quelle, flags=re.M).group(1))
    assert D.PARALLEL_MAX <= platz < len(D.ENTWICKLUNGS_PORTS) // D.PORTS_JE_PLATZ
