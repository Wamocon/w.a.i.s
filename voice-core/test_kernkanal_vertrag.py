"""Vertragstest zwischen dem Kern (voice-core) und dem Kern-Kanal des Dispatchers (infra/sokrates2), Paket R13.

Beide Seiten wurden getrennt gebaut und getestet. Dieser Test prüft sie gegeneinander und gegen die festgelegten
Schnittstellen der Arbeitsliste (docs/entwicklung-im-betrieb-arbeitsliste.md, Abschnitt 1). Die Tabellen unten stehen
bewusst als Wortlaut im Test: Weicht eine Seite ab, wird dieser Test rot, nicht erst der Betrieb.

    I2  Standardwerte und Bereiche der Datei kernkanal.conf (Skript und Dispatcher)
    I3  Büro-Variablen und Release-Nachweis SCHRANKEN_VERSION (Kern und Skript)
    I5  Projektname (Kern und Dispatcher, dieselbe Wertetabelle), seit Dispatcher 8 mit der Kennung des Profils
    I6  Grund-Codes des Ereignisses kanal_gesperrt (Dispatcher und Kern)
    ssh-Optionen des Rauchtests gegen dev_agent.ssh_argv
    unveränderte Dateien (Prüfsummen von Slot-Skript, Vorprüfung und Slot-Vorlage), Namensvertrag
    Selbstschutz: jeder Name des eigenen Repos (SELF_REPOS, ist_eigenes_repo) auf allen drei Seiten gleich
    Zugangsart haus (P6b): der Kern sendet nur, was Kern-Kanal und Dispatcher annehmen; das Skript erkennt alle drei Seiten
    Plan C, Paket S (docs/persoenliche-zugaenge.md, C.2.6 bis C.2.9): Gründe und Sätze, Rechte klassischer Tokens je Person,
        Token-Formen, Feldnamen und die Protokoll-Klasse Werkzeuge (infra/sokrates2/wamo_job_github.py)

Alles läuft ohne Netz, ohne Server, ohne ssh und ohne git. Ausführen (im Ordner voice-core/):  python -m pytest -q test_kernkanal_vertrag.py
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import dev_agent
import dev_guard
import entwicklung_betrieb as eb

VOICE_CORE = Path(__file__).resolve().parent
WURZEL = VOICE_CORE.parent
INFRA = WURZEL / "infra" / "sokrates2"


def _lade(name: str, datei: str):
    spec = importlib.util.spec_from_file_location(name, INFRA / datei)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul  # nötig für @dataclass
    spec.loader.exec_module(modul)
    return modul


K = _lade("wamo_job_kernkanal", "wamo_job_kernkanal.py")  # das Modul des Dispatchers
D = _lade("wamo_job_dispatch_vertrag", "wamo_job_dispatch.py")
R = _lade("wamo_job_kern_rauchtest_vertrag", "wamo_job_kern_rauchtest.py")


def _text(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8").replace("\r\n", "\n")


SKRIPT = _text(INFRA / "wamo-job-kern-einrichten.sh")
RUECKWEG = _text(INFRA / "wamo-job-kern-rueckweg.sh")
EB_QUELLE = _text(VOICE_CORE / "entwicklung_betrieb.py")
NAMENSVERTRAG = _text(WURZEL / "CLAUDE.md")

# Synthetische Kennung, keine echte user_id
PROFIL = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def test_geprueft_wird_der_code_dieses_arbeitsbaums():
    """Die Module kommen aus demselben Baum wie der Test (kein alter Stand aus einer anderen Installation)."""
    assert Path(eb.__file__).resolve() == VOICE_CORE / "entwicklung_betrieb.py"
    assert Path(dev_agent.__file__).resolve() == VOICE_CORE / "dev_agent.py"
    assert Path(K.__file__).resolve() == INFRA / "wamo_job_kernkanal.py"


# ================================================================== I6: Grund-Codes
I6_CODES = ("notaus", "konfig_ungueltig", "kanal_zu", "abgelaufen", "befehl", "fremd", "art", "repo", "repo_fehlt", "dienst",
            "projekt", "zugang", "fork", "herkunft_unklar", "grenze_start", "grenze_laufzeit", "grenze_folgen", "abstand", "platz",
            "grenze_profil",
            "persoenlich_aus", "grenze_einreichen")  # Plan C (C.2.6): persönlicher Weg aus, Grenze für Einreichen je Tag

# Funktionen von wamo_job_kernkanal.py, deren Rückgabe ein Code aus KANAL_GRUENDE ist
CODE_FUNKTIONEN = {"pruefe_befehl", "pruefe_eigener_auftrag", "projekt_pruefen", "pruefe_grenzen", "pruefe_start", "fork_pruefen",
                   "kanal_zustand", "kern_projektname", "pruefe_grenzen_profil"}


def test_i6_die_feste_liste_gilt_auf_beiden_seiten():
    assert K.KANAL_GRUENDE == I6_CODES
    assert tuple(eb.GRUND_SAETZE) == I6_CODES
    assert len(set(K.KANAL_GRUENDE)) == len(K.KANAL_GRUENDE)


def test_jeder_code_des_dispatchers_hat_im_kern_einen_satz():
    assert set(K.KANAL_GRUENDE) == set(eb.GRUND_SAETZE)
    for code, satz in eb.GRUND_SAETZE.items():
        assert isinstance(satz, str) and satz.strip(), code


def _konstanten(ausdruck: ast.AST) -> set[str]:
    if isinstance(ausdruck, ast.Constant) and isinstance(ausdruck.value, str):
        return {ausdruck.value}
    if isinstance(ausdruck, ast.IfExp):
        return _konstanten(ausdruck.body) | _konstanten(ausdruck.orelse)
    return set()


def _codes_der_regeln(quelle: str) -> set[str]:
    """Die Textwerte, die eine Regel zurückgibt (return, grund = ..., ProjektnameFehler("...")) in den Prüffunktionen."""
    codes: set[str] = set()
    for funktion in ast.walk(ast.parse(quelle)):
        if not (isinstance(funktion, ast.FunctionDef) and funktion.name in CODE_FUNKTIONEN):
            continue
        for knoten in ast.walk(funktion):
            if isinstance(knoten, ast.Return) and knoten.value is not None:
                codes |= _konstanten(knoten.value)
            elif isinstance(knoten, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "grund" for t in knoten.targets):
                codes |= _konstanten(knoten.value)
            elif isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "ProjektnameFehler" and knoten.args:
                codes |= _konstanten(knoten.args[0])
    return codes


def _abweisungen(quelle: str) -> set[str]:
    """Die Codes, die der Dispatcher selbst in kanal_abweisen("...") schreibt."""
    codes: set[str] = set()
    for knoten in ast.walk(ast.parse(quelle)):
        if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "kanal_abweisen" and knoten.args:
            codes |= _konstanten(knoten.args[0])
    return codes


def test_der_dispatcher_nennt_nur_codes_aus_der_festen_liste():
    regeln = _codes_der_regeln(_text(INFRA / "wamo_job_kernkanal.py"))
    abweisungen = _abweisungen(_text(INFRA / "wamo_job_dispatch.py"))
    assert len(regeln) >= 10 and len(abweisungen) >= 3, "die Quelltextprüfung findet nichts mehr (Aufbau geändert?)"
    assert regeln <= set(K.KANAL_GRUENDE), regeln - set(K.KANAL_GRUENDE)
    assert abweisungen <= set(K.KANAL_GRUENDE), abweisungen - set(K.KANAL_GRUENDE)
    assert not (regeln | abweisungen) - set(eb.GRUND_SAETZE)


@pytest.mark.parametrize("code", I6_CODES)
def test_das_ereignis_des_dispatchers_wird_im_kern_zum_satz(code, monkeypatch, capsys):
    """Der Weg einer Abweisung: kanal_abweisen schreibt die Zeile, der Kern macht daraus Quittung und Status (I6, Exit 2)."""
    zeilen: list[bytes] = []
    monkeypatch.setattr(D, "log", lambda *args, **kw: None)
    monkeypatch.setattr(D, "emit_raw", lambda zeile: zeilen.append(zeile) or True)
    assert D.kanal_abweisen(code) == D.EXIT_ABGEWIESEN == 2
    assert code in capsys.readouterr().err  # die Meldung auf stderr nennt nur den Code
    assert len(zeilen) == 1
    zeile = zeilen[0].decode("utf-8")
    ereignis = json.loads(zeile)
    assert ereignis == {"type": "wamo", "ereignis": "kanal_gesperrt", "grund": code}  # das Format aus I6, sonst nichts
    satz = eb.GRUND_SAETZE[code]
    assert eb.grund_aus_ausgabe(zeile) == satz
    assert eb.ablehn_grund(2, {"kanal_gesperrt": ereignis}) == satz
    status = dev_agent.remote_status(2, {"kanal_gesperrt": ereignis})
    assert status.startswith("nicht gestartet") and satz.rstrip(".") in status


def test_der_kern_bildet_kanal_gesperrt_ab_und_vertraegt_einen_neuen_code():
    assert dev_agent.REMOTE_EREIGNIS_STATUS["kanal_gesperrt"].startswith("nicht gestartet")
    assert eb.kanal_status({"grund": "ein_neuer_code"}).startswith("nicht gestartet")
    assert eb.grund_satz("ein_neuer_code") == eb.GRUND_UNBEKANNT


# ================================================================== I5: Projektname
# (Repo, Projektwort, Ergebnis). Die ersten Zeilen stehen so in der Arbeitsliste, die übrigen setzen dieselbe Regel fort:
# alles außerhalb von a-z0-9- wird verworfen, auch Umlaute, ß und Leerzeichen (keine Umschrift).
I5_GUT = (
    ("Acme/Test-Repo", None, "kern-test-repo"),
    ("acme/my_repo.js", None, "kern-my-repo-js"),
    ("acme/a__b", None, "kern-a-b"),
    ("acme/-x-", None, "kern-x"),
    (None, "Marktstudie", "kern-marktstudie"),
    (None, "Märkte", "kern-mrkte"),  # die Zeile mit Umlaut: kein ae, sondern verworfen
    (None, "Größe", "kern-gre"),
    (None, "Öl und Fuß", "kern-lundfu"),
    (None, "Markt Studie", "kern-marktstudie"),
    (None, "  Markt/Studie! ", "kern-marktstudie"),
    (None, "a..b__c", "kern-a-b-c"),
    ("acme/" + "a" * 45, None, "kern-" + "a" * 45),  # genau 50 Zeichen mit Präfix
    ("acme/x", "ignoriert", "kern-x"),  # mit Repo zählt nur das Repo
)
I5_ABGELEHNT = (
    ("acme/wamo", None, "repo"),
    ("acme/WAMO", None, "repo"),
    ("acme/Wamo", None, "repo"),
    ("acme/" + "a" * 46, None, "projekt"),  # länger als 50 mit Präfix
    ("acme/" + "a" * 80, None, "projekt"),
    (None, "äöü", "projekt"),  # nach dem Verwerfen bleibt nichts
    (None, "---", "projekt"),
    (None, "", "projekt"),
    (None, None, "projekt"),
    (None, "wamo", "projekt"),
    ("acme/w.a.i.s", None, "repo"),  # der Name des eigenen Repos seit dem 14.11.2026
    ("Wamocon/W.A.I.S", None, "repo"),
    ("acme/wais", None, "repo"),
    (None, "W.A.I.S", "projekt"),
    (None, "wais", "projekt"),
)


def seite_kern(repo, wort):
    try:
        return eb.kern_projektname(repo, wort)
    except eb.ProjektnameFehler as e:
        return ("abgelehnt", e.grund)


def seite_dispatcher(repo, wort):
    try:
        return K.kern_projektname(repo, wort)
    except K.ProjektnameFehler as e:
        return ("abgelehnt", e.grund)


SEITEN = {"kern": seite_kern, "dispatcher": seite_dispatcher}


@pytest.mark.parametrize("seite", SEITEN)
@pytest.mark.parametrize("repo, wort, erwartet", I5_GUT)
def test_i5_gute_zeilen_auf_beiden_seiten(seite, repo, wort, erwartet):
    assert SEITEN[seite](repo, wort) == erwartet


@pytest.mark.parametrize("seite", SEITEN)
@pytest.mark.parametrize("repo, wort, grund", I5_ABGELEHNT)
def test_i5_abgelehnte_zeilen_auf_beiden_seiten(seite, repo, wort, grund):
    assert SEITEN[seite](repo, wort) == ("abgelehnt", grund)


def _zufaellige_eingaben(anzahl: int = 2500) -> list[tuple[str | None, str | None]]:
    """Wörter mit Umlauten, Leerraum und Sonderzeichen sowie Repos in der Form, die beide Seiten vorher prüfen (REPO_RE, ohne
    .git und ohne . oder .. als Namen: check_repo im Dispatcher und repo_pruefen im Kern lassen nichts anderes durch)."""
    zufall = random.Random(20261111)
    wort_zeichen = "abcxyzABCXYZ0189-._ /!äöüÄÖÜßéñ\t €"
    repo_zeichen = "abcxyzABCXYZ0189-._"
    laengen = (1, 2, 3, 5, 8, 20, 44, 45, 46, 47, 60)
    eigene = ("wamo", "WAMO", "wamo_", "-wamo-", "Wamo-Extra", "wamo.", "w.a.i.s", "W.A.I.S", "wais", "w-a-i-s", "W_A_I_S", "w.a.i.s.2")
    eingaben: list[tuple[str | None, str | None]] = [(None, wort) for wort in (*eigene, "W A I S")]
    eingaben += [(f"acme/{name}", None) for name in (*eigene, "a.b-c_d", "..", "___", "-")]
    for _ in range(anzahl):
        if zufall.random() < 0.5:
            name = "".join(zufall.choice(repo_zeichen) for _ in range(zufall.choice(laengen)))
            if name in (".", "..") or name.lower().endswith(".git"):
                continue
            eingaben.append((f"acme/{name}", None))
        else:
            eingaben.append((None, "".join(zufall.choice(wort_zeichen) for _ in range(zufall.choice(laengen)))))
    return eingaben


def test_i5_beide_seiten_geben_bei_jeder_eingabe_dasselbe():
    """Das Ergebnis ist ein Name oder eine Ablehnung mit Grund (repo oder projekt); der Kern leitet ab, der Dispatcher erzwingt."""
    eingaben = _zufaellige_eingaben()
    for repo, _wort in eingaben:
        if repo:
            assert dev_agent.REPO_RE.fullmatch(repo) and K.REPO_RE.fullmatch(repo) and D.REPO_RE.fullmatch(repo), repo
    abweichungen = [(e, seite_kern(*e), seite_dispatcher(*e)) for e in eingaben if seite_kern(*e) != seite_dispatcher(*e)]
    assert not abweichungen, abweichungen[:5]


def test_i5_der_dispatcher_nimmt_jeden_namen_des_kerns_an():
    for repo, wort in _zufaellige_eingaben():
        name = seite_kern(repo, wort)
        if isinstance(name, tuple):
            continue
        assert K.projekt_pruefen(name, repo) is None, (repo, wort, name)
        assert K.pc_projekt_erlaubt(name) is False, name  # der Namensraum kern- gehört dem Kern-Kanal


def test_i5_praefix_und_laenge_sind_auf_allen_seiten_gleich():
    assert eb.KERN_PRAEFIX == K.PRAEFIX == D.KERN_PRAEFIX == "kern-"
    assert eb.PROJEKT_MAX == K.MAX_PROJEKT_ZEICHEN == 50
    assert dev_agent.REPO_RE.pattern == K.REPO_RE.pattern == D.REPO_RE.pattern


def test_i5_zeilen_mit_dem_praefix_kern():
    # Projekt test-repo aus dem Kern-Kanal: abgelehnt (projekt, Präfix fehlt)
    assert K.projekt_pruefen("test-repo", "acme/test-repo") == "projekt"
    assert K.projekt_pruefen("test-repo", None) == "projekt"
    # Projekt kern-test-repo aus dem PC-Kanal: abgelehnt (Regel im Dispatcher, Namensraum des Kern-Kanals)
    assert K.pc_projekt_erlaubt("kern-test-repo") is False
    assert 'KANAL == "pc" and projekt.startswith(KERN_PRAEFIX)' in _text(INFRA / "wamo_job_dispatch.py")
    # mit gesetztem Repo muss das Projekt genau kern-<abgeleiteter Name> sein
    assert K.projekt_pruefen("kern-test-repo", "Acme/Test-Repo") is None
    assert K.projekt_pruefen("kern-anderes", "acme/test-repo") == "projekt"


# ================================================================== I3: Release-Nachweis SCHRANKEN_VERSION
def _muster_von_schalter() -> str:
    treffer = re.findall(r"grep -Eq '(\^SCHRANKEN_VERSION[^']*)'", SKRIPT)
    assert len(treffer) == 1, "das Skript prüft den Release-Nachweis nicht mehr mit genau einem grep -Eq"
    return treffer[0]


def _zeilen_im_muster(muster: str, quelle: str) -> list[str]:
    return [zeile for zeile in quelle.split("\n") if re.search(muster, zeile)]


def test_i3_genau_eine_zeile_passt_zum_muster_von_schalter():
    muster = _muster_von_schalter()
    assert muster == "^SCHRANKEN_VERSION = [1-9][0-9]*$"
    # 3: gleichzeitige Aufträge (Dispatcher 9), 4: persönliche GitHub-Zugänge (Plan C, Paket K; schalter --github an verlangt sie)
    assert _zeilen_im_muster(muster, EB_QUELLE) == ["SCHRANKEN_VERSION = 4"]
    assert eb.SCHRANKEN_VERSION == 4
    assert "\r" not in (VOICE_CORE / "entwicklung_betrieb.py").read_bytes().decode("utf-8"), "ein Zeilenende mit CR bricht das $ im grep"


def test_i3_das_skript_liest_den_nachweis_im_zielrelease():
    assert '"$KERNAPP/releases/$RELEASE/voice-core/entwicklung_betrieb.py"' in SKRIPT
    assert 'KERNAPP="$WURZEL/opt/wamo-core"' in SKRIPT


@pytest.mark.parametrize("zeile", ["SCHRANKEN_VERSION = 0", "SCHRANKEN_VERSION = 01", "SCHRANKEN_VERSION = 1  # Stand",
                                   "SCHRANKEN_VERSION=1", " SCHRANKEN_VERSION = 1", "SCHRANKEN_VERSION = 1.5", "SCHRANKEN_VERSION = 'x'"])
def test_i3_das_muster_nimmt_nur_die_genaue_form_an(zeile):
    assert not _zeilen_im_muster(_muster_von_schalter(), zeile)


def test_i3_das_muster_nimmt_jede_spaetere_version_an():
    for zeile in ("SCHRANKEN_VERSION = 1", "SCHRANKEN_VERSION = 2", "SCHRANKEN_VERSION = 17"):
        assert _zeilen_im_muster(_muster_von_schalter(), zeile) == [zeile]


@pytest.mark.skipif(not shutil.which("grep"), reason="grep nicht vorhanden")
def test_i3_auch_das_echte_grep_nimmt_die_datei_an():
    muster = _muster_von_schalter()
    ergebnis = subprocess.run(["grep", "-Eq", muster, str(VOICE_CORE / "entwicklung_betrieb.py")], check=False)
    assert ergebnis.returncode == 0


# ================================================================== I2: Standardwerte und Bereiche der kernkanal.conf
I2_STANDARD = {"KANAL": "zu", "MAX_TURNS": "40", "MAX_BUDGET_USD": "2.00", "MAX_START_STUNDE": "4", "MAX_START_TAG": "8",
               "MAX_LAUFZEIT_TAG_S": "14400", "MAX_FOLGEN": "5", "MIN_ABSTAND_S": "60", "MIN_PLATZ_MB": "2048",
               "MAX_VERSUCH_STUNDE": "60",  # Versuche je Stunde, nur nach unten einstellbar (20 bis Dispatcher 7)
               # Dispatcher 8: Grenzen je Profil
               "MAX_NEU_STUNDE_PROFIL": "3", "MAX_NEU_TAG_PROFIL": "8", "MAX_VERSUCH_STUNDE_PROFIL": "10", "MAX_LAUFZEIT_TAG_S_PROFIL": "7200",
               # Dispatcher 9: gleichzeitige Aufträge gesamt und je Person (Entscheidung von Niko 16.11.2026)
               "MAX_PARALLEL": "6", "MAX_PARALLEL_PROFIL": "3"}
I2_ABLAUF_TAGE = 30
I2_BEREICHE = {"MAX_TURNS": (1, 200), "MAX_START_STUNDE": (1, 60), "MAX_START_TAG": (1, 200), "MAX_LAUFZEIT_TAG_S": (60, 86400),
               "MAX_FOLGEN": (0, 20), "MIN_ABSTAND_S": (0, 3600), "MIN_PLATZ_MB": (100, 1000000), "MAX_VERSUCH_STUNDE": (1, 60),
               "MAX_NEU_STUNDE_PROFIL": (1, 60), "MAX_NEU_TAG_PROFIL": (1, 200), "MAX_VERSUCH_STUNDE_PROFIL": (1, 60),
               "MAX_LAUFZEIT_TAG_S_PROFIL": (60, 86400), "MAX_PARALLEL": (1, 6), "MAX_PARALLEL_PROFIL": (1, 6),
               # Dispatcher 10 (Plan C, C.2.7): persönlicher GitHub-Weg
               "MAX_EINREICHEN_TAG": (1, 50), "MAX_EINREICHEN_TAG_PROFIL": (1, 50), "MAX_KLON_MB": (100, 4096)}
# Schlüssel, die das Skript nur schreibt, wenn kanal --persoenlich sie gesetzt hat (Dispatcher 9 schlösse sonst den Kanal)
I2_SCHLUESSEL_PERSOENLICH = {"PERSOENLICH", "MAX_EINREICHEN_TAG", "MAX_EINREICHEN_TAG_PROFIL", "MAX_KLON_MB"}
I2_SCHLUESSEL = {"KANAL", "ABLAUF", "ARTEN", "REPOS", "DIENSTE", "MAX_BUDGET_USD", "PERSOENLICH", *I2_BEREICHE}


def _std_werte(skript: str) -> dict[str, str]:
    return dict(re.findall(r"^STD_([A-Z_]+)=(\S+)$", skript, flags=re.M))


def test_i2_standardwerte_des_skripts():
    std = _std_werte(SKRIPT)
    for schluessel, wert in I2_STANDARD.items():
        assert std.get(schluessel) == wert, schluessel
    assert std.get("ABLAUF_TAGE") == str(I2_ABLAUF_TAGE)


def test_i2_der_dispatcher_kennt_dieselben_schluessel_und_bereiche():
    schluessel = re.search(r"^KONFIG_SCHLUESSEL=\(([^)]*)\)", SKRIPT, flags=re.M | re.S)
    persoenlich = re.search(r"^KONFIG_SCHLUESSEL_PERSOENLICH=\(([^)]*)\)", SKRIPT, flags=re.M | re.S)
    assert schluessel and persoenlich
    assert set(persoenlich.group(1).split()) == set(K.SCHLUESSEL_PERSOENLICH) == I2_SCHLUESSEL_PERSOENLICH
    assert set(schluessel.group(1).split()) | set(persoenlich.group(1).split()) == set(K.BEKANNTE_SCHLUESSEL) == I2_SCHLUESSEL
    assert not set(schluessel.group(1).split()) & I2_SCHLUESSEL_PERSOENLICH  # nie unbedingt geschrieben
    assert dict(K.ZAHLEN) == I2_BEREICHE
    assert K.MAX_ABLAUF_TAGE == 400 and K.MAX_REPOS == 10 and K.MAX_VERSUCH_STUNDE_FEST == 60


def test_i2_die_standardwerte_des_dispatchers_gleichen_denen_des_skripts():
    standard = K.Konfig()
    assert standard.kanal is None  # fehlt der Schlüssel, gilt der Kanal als zu
    # Ausnahme mit Absicht (Dispatcher 9, Befund des Sicherheitsreviews): fehlen MAX_PARALLEL und MAX_PARALLEL_PROFIL in der Datei, gilt einer
    # gleichzeitig; die Standards 6 und 3 schreibt das Skript (schluessel, kanal) ausdrücklich
    assert (standard.max_parallel, standard.max_parallel_profil) == (1, 1)
    for schluessel in I2_BEREICHE:
        if schluessel in ("MAX_PARALLEL", "MAX_PARALLEL_PROFIL") or schluessel in I2_SCHLUESSEL_PERSOENLICH:
            continue
        assert str(getattr(standard, schluessel.lower())) == I2_STANDARD[schluessel], schluessel
    assert standard.max_budget_usd == I2_STANDARD["MAX_BUDGET_USD"]


def _attrappe(text: str):
    daten = text.encode("utf-8")
    return lambda pfad, limit: (daten, os.stat_result((0o100640, 0, 0, 1, 0, 0, len(daten), 0, 0, 0)))  # root, 0640


def test_i2_die_angelegte_datei_wird_vom_dispatcher_angenommen():
    """Was das Skript beim Anlegen schreibt (Standardwerte, Kanal zu, Ablauf in 30 Tagen), liest der Dispatcher ohne Fehler."""
    jetzt = datetime(2026, 11, 11, 12, 0, 0).timestamp()
    std = _std_werte(SKRIPT)
    ablauf = (date(2026, 11, 11) + timedelta(days=int(std["ABLAUF_TAGE"]))).strftime("%Y%m%d")
    werte = {"KANAL": std["KANAL"], "ABLAUF": ablauf, "ARTEN": "", "REPOS": "", "DIENSTE": "",
             **{schluessel: std[schluessel] for schluessel in (*I2_BEREICHE, "MAX_BUDGET_USD") if schluessel not in I2_SCHLUESSEL_PERSOENLICH}}
    konfig = K.konfig_lesen("/t/kernkanal.conf", jetzt=jetzt, lesen=_attrappe("\n".join(f"{k}={v}" for k, v in werte.items()) + "\n"))
    # Dispatcher 9: das Skript schreibt die Standards 6 und 3 ausdrücklich (fehlende Schlüssel hießen einer)
    assert konfig == K.Konfig(kanal="zu", ablauf=date(2026, 12, 11), max_parallel=6, max_parallel_profil=3)
    zustand = K.kanal_zustand(K.Pfade(konfig=Path("/t/kernkanal.conf"), notaus=Path("/t/notaus")), jetzt=jetzt,
                              lesen=_attrappe("\n".join(f"{k}={v}" for k, v in werte.items()) + "\n"), vorhanden=lambda p: False)
    assert zustand.grund == "kanal_zu" and zustand.tage_rest == 30


@pytest.mark.parametrize("schluessel, wert", [("MAX_TURNS", "0"), ("MAX_TURNS", "201"), ("MAX_BUDGET_USD", "0.00"),
                                              ("MAX_BUDGET_USD", "20.01"), ("MAX_BUDGET_USD", "2.005"), ("MAX_START_STUNDE", "61"),
                                              ("MAX_VERSUCH_STUNDE", "61"), ("MAX_NEU_STUNDE_PROFIL", "61"), ("MAX_LAUFZEIT_TAG_S_PROFIL", "59"), ("MAX_FOLGEN", "21"), ("MIN_PLATZ_MB", "99")])
def test_i2_werte_ausserhalb_des_bereichs_lehnt_der_dispatcher_ab(schluessel, wert):
    with pytest.raises(K.KonfigFehler):
        K.konfig_lesen("/t/kernkanal.conf", lesen=_attrappe(f"{schluessel}={wert}\n"))


def test_i2_das_skript_prueft_dieselben_grenzen_wie_der_dispatcher():
    assert 'pruefe_zahl --max-turns "$2" 1 200' in SKRIPT
    assert 'pruefe_betrag --max-budget-usd "$2" 0.01 20' in SKRIPT
    assert '[ "$tage" -le 400 ]' in SKRIPT
    assert 'pruefe_zahl --max-turns' in SKRIPT and K.ZAHLEN["MAX_TURNS"] == (1, 200)


# ================================================================== Kostenvariablen im Büro (I3)
def _buero(monkeypatch, **extra):
    umgebung = {"WAMO_BETRIEB": "buero", "WAMO_ENTWICKLUNG_BUERO": "an", "WAMO_ENTWICKLUNG_ORT": "sokrates2",
                "WAMO_ENTWICKLUNG_PROFILE": PROFIL, "WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD": "3", "WAMO_ENTWICKLUNG_KOSTEN_TAG_USD": "10"}
    umgebung.update(extra)
    for name, wert in umgebung.items():
        if wert is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, wert)


@pytest.mark.parametrize("name", [eb.ENV_KOSTEN_AUFTRAG, eb.ENV_KOSTEN_TAG])
def test_im_buero_sind_die_kostenvariablen_pflicht(name, monkeypatch):
    _buero(monkeypatch)
    assert eb.buero_problem() is None
    _buero(monkeypatch, **{name: None})
    assert name in eb.buero_problem()
    _buero(monkeypatch, **{name: ""})
    assert name in eb.buero_problem()


def test_fehlende_kosten_heissen_im_buero_aus_auch_in_der_vorpruefung_des_kerns(monkeypatch):
    _buero(monkeypatch, WAMO_ENTWICKLUNG_KOSTEN_TAG_USD=None)
    monkeypatch.setattr(dev_agent, "ssh_problem", lambda: None)
    assert "WAMO_ENTWICKLUNG_KOSTEN_TAG_USD" in dev_agent.entwicklung_problem()
    _buero(monkeypatch)
    assert dev_agent.entwicklung_problem() is None


def _funktion(skript: str, name: str) -> str:
    treffer = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}$", skript, flags=re.M | re.S)
    assert treffer, f"Funktion {name} fehlt im Skript"
    return treffer.group(1)


def test_das_skript_schreibt_beide_kostenvariablen_immer():
    rumpf = _funktion(SKRIPT, "drop_in_text")
    assert "Environment=WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD=${KOSTEN_AUFTRAG:-$STD_KOSTEN_AUFTRAG_USD}" in rumpf
    assert "Environment=WAMO_ENTWICKLUNG_KOSTEN_TAG_USD=${KOSTEN_TAG:-$STD_KOSTEN_TAG_USD}" in rumpf
    assert not re.search(r"\bif\b|\[\s|&&|\|\|", rumpf), "die Zeilen des Drop-ins dürfen nicht an eine Bedingung hängen"
    std = _std_werte(SKRIPT)
    assert std["KOSTEN_AUFTRAG_USD"] and std["KOSTEN_TAG_USD"]


def test_die_standardkosten_des_skripts_nimmt_der_kern_an(monkeypatch):
    std = _std_werte(SKRIPT)
    _buero(monkeypatch, WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD=std["KOSTEN_AUFTRAG_USD"], WAMO_ENTWICKLUNG_KOSTEN_TAG_USD=std["KOSTEN_TAG_USD"])
    assert eb.buero_problem() is None
    assert eb.kosten_auftrag(None) == float(std["KOSTEN_AUFTRAG_USD"]) and eb.kosten_tag(None) == float(std["KOSTEN_TAG_USD"])


def test_das_dropin_setzt_genau_die_variablen_die_der_kern_liest():
    namen = re.findall(r"echo \"Environment=([A-Z_]+)=", _funktion(SKRIPT, "drop_in_text"))
    assert set(namen) == {eb.ENV_SCHALTER, eb.ENV_ORT, eb.ENV_PROFILE, eb.ENV_KOSTEN_AUFTRAG, eb.ENV_KOSTEN_TAG, eb.ENV_MITGLIEDER, eb.ENV_HAUS}
    assert len(namen) == len(set(namen))
    assert "WAMO_ENTWICKLUNG" not in namen and eb.ENV_BEFEHLE not in namen  # Standard aus, nie nebenbei an
    # WAMO_ENTWICKLUNG_GITHUB schreibt erst das Skript aus Paket D-a (schalter --github an|aus, C.2.7); bis dahin fehlt die Zeile, der Kern
    # liest dann aus (Standard). D-a nimmt ENV_GITHUB in die Menge oben auf und streicht ihn hier.
    assert set(eb.ALLE_VARIABLEN) - set(namen) <= {eb.ENV_BEFEHLE, eb.ENV_GITHUB} and eb.ENV_BEFEHLE not in namen


def test_das_dropin_schreibt_den_schalter_fuer_hausmodelle_immer_und_standardmaessig_aus():
    rumpf = _funktion(SKRIPT, "drop_in_text")
    assert "Environment=WAMO_ENTWICKLUNG_HAUS=${HAUS:-aus}" in rumpf


# ================================================================== Zugangsart haus (P6b)
def test_jede_zugangsart_des_kern_kanals_nimmt_der_dispatcher_an():
    assert set(K.ZUGAENGE_KERN) <= set(D.ZUGANG_MODI)
    assert "server" not in K.ZUGAENGE_KERN  # der Zugang des Servers gilt im Büro nie


@pytest.mark.parametrize("haus", [False, True])
def test_der_kern_sendet_im_buero_nur_was_kern_kanal_und_dispatcher_annehmen(haus, monkeypatch):
    _buero(monkeypatch, WAMO_CLAUDE_SCHLUESSEL_PROFIL=PROFIL, WAMO_ENTWICKLUNG_SERVERZUGANG_PROFIL=PROFIL)
    monkeypatch.setattr(dev_agent, "claude_code_zugang_fuer", lambda uid: None)  # weder Token noch API-Schlüssel

    class Memory:
        user_id = PROFIL

    agent = dev_agent.DevAgent(memory=Memory(), auftraggeber="Niko", zulassung=eb.BueroZulassung(PROFIL), haus=haus)
    ergebnis = asyncio.run(agent._remote_zugang())
    if not haus:
        assert ergebnis is None  # wie bisher: ohne eigenen Zugang startet im Büro nichts, auch nicht mit dem Zugang des Servers
        return
    kopf, zeile = ergebnis
    assert zeile is None  # nie eine zweite Zeile, nie ein Wert
    assert kopf == {"zugang": "haus", "profil": PROFIL.replace("-", "")[:8]}
    assert kopf["zugang"] in K.ZUGAENGE_KERN
    roh = (json.dumps({"auftrag": "x", **kopf}) + "\n").encode("utf-8")
    assert (D.parse_header(roh).zugang, D.parse_header(roh).profil) == ("haus", kopf["profil"])


def _skript_muster(name: str) -> re.Pattern:
    treffer = re.search(rf"^{name}='([^']+)'$", SKRIPT, flags=re.M)
    assert treffer, f"{name} fehlt im Skript"
    return re.compile(treffer.group(1), flags=re.M)


@pytest.mark.parametrize("name, datei", [
    ("HAUS_DISPATCHER_RE", INFRA / "wamo_job_dispatch.py"),
    ("HAUS_KANAL_RE", INFRA / "wamo_job_kernkanal.py"),
    ("HAUS_KERN_RE", VOICE_CORE / "entwicklung_betrieb.py"),
])
def test_schalter_mit_haus_erkennt_dispatcher_kern_kanal_und_release_an_genau_einer_zeile(name, datei):
    assert len(_skript_muster(name).findall(_text(datei))) == 1


def test_die_muster_fuer_haus_greifen_nicht_bei_einer_alten_fassung():
    alt = {"HAUS_DISPATCHER_RE": 'ZUGANG_MODI = ("folgt", "server")\n', "HAUS_KANAL_RE": "if anfrage.zugang != \"folgt\":\n",
           "HAUS_KERN_RE": "SCHRANKEN_VERSION = 1\n"}
    for name, text in alt.items():
        assert not _skript_muster(name).search(text), name


# ================================================================== ssh-Optionen des Rauchtests gegen dev_agent.ssh_argv
def test_die_ssh_optionen_des_rauchtests_gleichen_dev_agent_ssh_argv(monkeypatch):
    monkeypatch.setattr(dev_agent.shutil, "which", lambda name: "/usr/bin/ssh")
    for remote in (["ping"], ["start", "0123456789abcdef", "kern-x", "recherche"], ["status", "0123456789abcdef"]):
        erwartet = dev_agent.ssh_argv(remote)
        ist = R.ssh_argv(" ".join(remote), schluessel=dev_agent.ssh_schluessel(), known_hosts=dev_agent.ssh_known_hosts(),
                         ziel=dev_agent.ssh_ziel(), exe="/usr/bin/ssh")
        assert ist == erwartet, remote
    mit_tty = R.ssh_argv("ping", schluessel=dev_agent.ssh_schluessel(), known_hosts=dev_agent.ssh_known_hosts(), ziel=dev_agent.ssh_ziel(),
                         exe="/usr/bin/ssh", tty=True)
    assert [("-tt" if a == "-T" else a) for a in dev_agent.ssh_argv(["ping"])] == mit_tty


def test_ziel_schluessel_und_hostdatei_des_rauchtests_sind_die_standards_des_kerns(monkeypatch):
    kern_home = R.KERN_HOME.as_posix()  # /var/lib/wamo-core: das Home von wamo-core, in dem der Kern die Standards auflöst
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(kern_home)))
    monkeypatch.setenv("HOME", kern_home)
    monkeypatch.setenv("USERPROFILE", kern_home)
    for name in ("WAMO_ENTWICKLUNG_SSH_ZIEL", "WAMO_ENTWICKLUNG_SSH_SCHLUESSEL", "WAMO_ENTWICKLUNG_SSH_KNOWN_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    assert R.ZIEL == dev_agent.ssh_ziel() == dev_agent.SSH_ZIEL_STANDARD
    assert R.SCHLUESSEL.as_posix() == dev_agent.ssh_schluessel().as_posix()
    assert R.KNOWN_HOSTS.as_posix() == dev_agent.ssh_known_hosts().as_posix()
    assert R.HOST == re.search(r"^KERN_IP=(\S+)$", SKRIPT, flags=re.M).group(1) == R.ZIEL.split("@", 1)[1]


def test_die_pfade_des_rauchtests_gleichen_denen_der_skripte():
    pfade = {"KERN_DATEI": "etc/ssh/authorized_keys.d/wamo-kern", "PC_DATEI": "etc/ssh/authorized_keys.d/wamo",
             "KONFIG": "etc/wamo/kernkanal.conf", "NOTAUS": "etc/wamo/kernkanal.notaus", "RAUCHTEST": "opt/wamo-core/bin/wamo-job-kern-rauchtest"}
    for name, relativ in pfade.items():
        assert getattr(R, name).as_posix() == "/" + relativ, name
    assert f'KERN_DATEI="$WURZEL/{pfade["KERN_DATEI"]}"' in SKRIPT and f'KERN_DATEI="$WURZEL/{pfade["KERN_DATEI"]}"' in RUECKWEG
    assert f'KONFIG="$WURZEL/{pfade["KONFIG"]}"' in SKRIPT and f'NOTAUS="$WURZEL/{pfade["NOTAUS"]}"' in RUECKWEG
    assert f'PC_DATEI="$WURZEL/{pfade["PC_DATEI"]}"' in SKRIPT
    assert 'RAUCHTEST="$KERNAPP/bin/wamo-job-kern-rauchtest"' in SKRIPT and 'KERNAPP="$WURZEL/opt/wamo-core"' in SKRIPT
    assert K.PFADE.kern_schluessel.as_posix() == "/" + pfade["KERN_DATEI"] and K.PFADE.notaus.as_posix() == "/" + pfade["NOTAUS"]
    assert K.PFADE.konfig.as_posix() == "/" + pfade["KONFIG"] and K.PFADE.pc_schluessel.as_posix() == "/" + pfade["PC_DATEI"]


def test_die_schluesselzeile_hat_in_skript_und_rauchtest_dieselbe_form():
    treffer = re.search(r'^\s*zeile="(restrict,.*)"$', SKRIPT, flags=re.M)
    assert treffer, "die Schlüsselzeile steht nicht mehr als zeile=... im Skript"
    zeile = treffer.group(1).replace('\\"', '"')
    assert zeile == 'restrict,from="$KERN_IP",command="/opt/wamo/bin/wamo-job-dispatch" $typ $blob wamo-kern-jobs'  # I1, ohne expiry-time
    kern_ip = re.search(r"^KERN_IP=(\S+)$", SKRIPT, flags=re.M).group(1)
    kopf = zeile.replace("$KERN_IP", kern_ip).replace("$typ $blob wamo-kern-jobs", "ssh-ed25519 ")
    pruefung = _text(INFRA / "wamo_job_kern_rauchtest.py")
    assert f"startswith('{kopf}')" in pruefung and 'endswith(" wamo-kern-jobs")' in pruefung


# ================================================================== unveränderte Dateien (Prüfsummen)
# SHA256 der Dateien, die dieses Vorhaben nicht ändert: Der Anker prüft die Prüfsumme des Slot-Skripts (wamo_anker.py), Vorprüfung und
# Slot-Vorlage gehören zum selben Vertrag. Zeilenenden sind auf LF vereinheitlicht (ein Checkout unter Windows ändert die Summe nicht).
# Es gibt keinen Vergleich mit einem Git-Zweig: Nach dem Merge bliebe er leer, und jede spätere Änderung würde ihn rot färben.
PRUEFSUMMEN = {
    # 17.11.2026 bewusst geändert (R7): ausleiten übersteht einen Stopp in TimeoutStopSec (WARNUNG, reset-failed, Slot trotzdem abgewählt),
    # dazu WAMO_CADDY_ETC nur für den Probelauf. Die Kopien des Ankers (schritte/kern-slots, rueckweg-kern) folgen mit anker-einrichten.sh.
    "infra/sokrates2/wamo-core-slots.sh": "8dc56e54f686d36cc025a0e1d6741fd4b6b0e7f31800347b0f89c4661fbeceb6",
    "infra/sokrates2/wamo-core-vorpruefung.sh": "32235d048877a3e2626530537c60e03dabf1ee667ef85c01e6055b32c81673c6",
    "infra/sokrates2/wamo-core@.service": "46b22cc0bfdf9000eb08431a61537ede65b3b3d7ab15f452cf3deca3bf239953",
}


def _summe(inhalt: bytes) -> str:
    return hashlib.sha256(inhalt.replace(b"\r\n", b"\n")).hexdigest()


def test_die_pruefsumme_ignoriert_die_zeilenenden_aber_sonst_nichts():
    assert _summe(b"a\r\nb\r\n") == _summe(b"a\nb\n") != _summe(b"a\nb")
    assert _summe(b"a\nb\n") != _summe(b"a\nc\n")


@pytest.mark.parametrize("datei", sorted(PRUEFSUMMEN))
def test_der_anker_prueft_diese_dateien_ihre_pruefsumme_ist_festgeschrieben(datei):
    ist = _summe((WURZEL / datei).read_bytes())
    assert ist == PRUEFSUMMEN[datei], (
        f"{datei} hat sich geändert (SHA256 jetzt {ist}). Die Datei gehört zum Vertrag mit dem Anker (wamo_anker.py prüft die Prüfsumme des "
        "Slot-Skripts) und wird von diesem Vorhaben nie geändert. Ein bewusster Wechsel sieht so aus: die Datei ändern, die neue Prüfsumme in "
        "PRUEFSUMMEN dieses Tests und im Anker eintragen und die Begründung im selben Commit nennen. War es ein Versehen: die Datei zurücksetzen.")


def test_die_vorpruefung_und_die_slot_vorlage_kennen_den_buero_schalter_nicht():
    vorpruefung = _text(INFRA / "wamo-core-vorpruefung.sh")
    einheit = _text(INFRA / "wamo-core@.service")
    assert '[ "${WAMO_ENTWICKLUNG:-aus}" = aus ]' in vorpruefung
    assert "WAMO_ENTWICKLUNG=aus" in einheit
    assert "WAMO_ENTWICKLUNG_BUERO" not in vorpruefung + einheit


# ================================================================== Selbstschutz: jeder Name des eigenen Repos
# Das Repo hieß bis zum 14.11.2026 wamo und heißt seitdem w.a.i.s (GitHub leitet den alten Namen weiter). Kern (dev_guard.py), Dispatcher
# (wamo_job_dispatch.py) und Kern-Kanal (wamo_job_kernkanal.py) sind getrennt installierte Dateien und halten darum je eine Liste SELF_REPOS
# und eine Prüfung ist_eigenes_repo. Dieser Test hält alle drei gleich. SELF_REPO bleibt nur als Alias ("wamo"), verglichen wird nie damit.
SELF_REPOS = ("wamo", "w.a.i.s")
SELBST_SEITEN = {"kern": dev_guard, "dispatcher": D, "kern_kanal": K}
SELBST_DATEIEN = (VOICE_CORE / "dev_guard.py", INFRA / "wamo_job_dispatch.py", INFRA / "wamo_job_kernkanal.py")
EIGENE_NAMEN = (
    "wamo", "WAMO", "Wamo", "w.a.i.s", "W.A.I.S", "W.A.I.S.", "wais", "WAIS", "w-a-i-s", "W_A_I_S", "w.a.i.s.git", "Wamocon/w.a.i.s",
    "wamocon/W.A.I.S", "Wamocon/wamo", "Wamocon/wamo.git", "Wamocon/WAMO.GIT", "https://github.com/Wamocon/w.a.i.s",
    "https://github.com/Wamocon/w.a.i.s.git", "github.com/wamocon/wamo/", " Wamocon/w.a.i.s ", "x/Wamo", "acme/-wamo-", "acme/wamo_",
    "ｗａｉｓ",  # wais in Vollbreite: NFKC macht daraus wais
)
FREMDE_NAMEN = ("acme/test-repo", "Wamocon/wamo-extra", "wamocon/wamo-docs", "Wamocon/wais-docs", "acme/w.a.i.s.2", "acme/wamos",
                "acme/a.b-c_d", "wamo/app")  # nur der Name nach dem Schrägstrich zählt, nie der Besitzer
UNKLARE_WERTE = (None, 5, b"wamo", ["w.a.i.s"], {"name": "x"})


def test_self_repos_ist_auf_allen_drei_seiten_gleich_und_steht_je_datei_genau_einmal():
    for datei in SELBST_DATEIEN:
        zeilen = [z for z in _text(datei).split("\n") if re.match(r"SELF_REPOS?\s*=", z)]
        assert len(zeilen) == 2, (datei.name, zeilen)
        assert zeilen[0].startswith('SELF_REPOS = ("wamo", "w.a.i.s")'), (datei.name, zeilen)
        assert zeilen[1].startswith("SELF_REPO = SELF_REPOS[0]"), (datei.name, zeilen)
    for seite, modul in SELBST_SEITEN.items():
        assert modul.SELF_REPOS == SELF_REPOS, seite
        assert modul.SELF_REPO == "wamo", seite  # Alias für ältere Verweise
    assert dev_agent.ist_eigenes_repo is dev_guard.ist_eigenes_repo  # der Kern prüft nur über dev_guard


def test_kein_vergleich_mehr_mit_dem_alias_self_repo():
    """Nur ist_eigenes_repo entscheidet. Ein Vergleich mit SELF_REPO kennt den neuen Namen nicht (die Lücke vom 14.11.2026)."""
    dateien = (*SELBST_DATEIEN, VOICE_CORE / "dev_agent.py", VOICE_CORE / "entwicklung_betrieb.py", INFRA / "wamo_job_rauchtest.py")
    for datei in dateien:
        treffer = [z.strip() for z in _text(datei).split("\n") if re.search(r"\bSELF_REPO\b", z) and not z.startswith("SELF_REPO = SELF_REPOS[0]")]
        assert treffer == [], (datei.name, treffer)


@pytest.mark.parametrize("seite", SELBST_SEITEN)
@pytest.mark.parametrize("name", EIGENE_NAMEN)
def test_jeder_name_des_eigenen_repos_ist_auf_jeder_seite_das_eigene_repo(seite, name):
    assert SELBST_SEITEN[seite].ist_eigenes_repo(name) is True


@pytest.mark.parametrize("seite", SELBST_SEITEN)
@pytest.mark.parametrize("name", FREMDE_NAMEN)
def test_fremde_repos_sind_nie_das_eigene_repo(seite, name):
    assert SELBST_SEITEN[seite].ist_eigenes_repo(name) is False


@pytest.mark.parametrize("seite", SELBST_SEITEN)
@pytest.mark.parametrize("wert", UNKLARE_WERTE, ids=repr)
def test_im_zweifel_gilt_ein_wert_als_das_eigene_repo(seite, wert):
    assert SELBST_SEITEN[seite].ist_eigenes_repo(wert) is True


def test_alle_drei_seiten_entscheiden_bei_jeder_eingabe_gleich():
    zufall = random.Random(20261114)
    zeichen = "wamoisWAMOISxg.-_/ "
    eingaben = [*EIGENE_NAMEN, *FREMDE_NAMEN, *UNKLARE_WERTE]
    eingaben += ["".join(zufall.choice(zeichen) for _ in range(zufall.randint(1, 14))) for _ in range(3000)]
    gesperrt = 0
    for eingabe in eingaben:
        ergebnisse = {seite: modul.ist_eigenes_repo(eingabe) for seite, modul in SELBST_SEITEN.items()}
        assert len(set(ergebnisse.values())) == 1, (eingabe, ergebnisse)
        gesperrt += ergebnisse["kern"]
    assert 0 < gesperrt < len(eingaben)


# Aufträge, wie sie ankommen: der Kern prüft das Feld repo und Adressen im Auftragstext, der Dispatcher die Kopfzeile, der Kern-Kanal den Projektnamen
AUFTRAG_EIGEN = ("Wamocon/w.a.i.s", "Wamocon/W.A.I.S", "acme/w.a.i.s", "acme/wais", "acme/w-a-i-s", "Wamocon/wamo", "Wamocon/wamo.git")


@pytest.mark.parametrize("repo", AUFTRAG_EIGEN)
def test_ein_auftrag_mit_dem_eigenen_repo_wird_im_kern_abgelehnt(repo):
    with pytest.raises(ValueError, match="WAMO-Repo"):
        dev_agent.repo_pruefen(repo)
    with pytest.raises(ValueError, match="WAMO-Repo"):
        dev_agent.repo_pruefen(f"https://github.com/{repo}")
    with pytest.raises(ValueError, match="WAMO-Repo"):
        dev_agent.repo_aus_auftrag(f"Bitte https://github.com/{repo} prüfen.")
    assert seite_kern(repo, None) == ("abgelehnt", "repo")


@pytest.mark.parametrize("repo", AUFTRAG_EIGEN)
def test_ein_auftrag_mit_dem_eigenen_repo_wird_im_dispatcher_und_im_kern_kanal_abgelehnt(repo):
    with pytest.raises(D.Abgewiesen) as info:
        D.check_repo(repo)
    assert str(info.value) == D.WAMO_REPO_GESPERRT or repo.endswith(".git")  # .git lehnt die Form schon vorher ab
    assert seite_dispatcher(repo, None) == ("abgelehnt", "repo")
    assert K.projekt_pruefen("kern-x", repo) == "repo"


@pytest.mark.parametrize("name", ("wamo", "wais", "w-a-i-s"))
def test_ein_projekt_mit_dem_namen_des_eigenen_repos_wird_auf_allen_seiten_abgelehnt(name):
    with pytest.raises(ValueError, match="WAMO-Repo"):
        dev_agent.project_slug(name)
    with pytest.raises(D.Abgewiesen):
        D.check_project(name)
    assert K.projekt_pruefen(f"kern-{name}", None) == "projekt"
    for wort in (name, name.upper(), "W.A.I.S", "W A I S"):
        assert seite_kern(None, wort) == seite_dispatcher(None, wort) == ("abgelehnt", "projekt"), wort


@pytest.mark.parametrize("repo, projekt", [("Acme/Test-Repo", "kern-test-repo"), ("Wamocon/wamo-extra", "kern-wamo-extra"),
                                           ("Wamocon/wais-docs", "kern-wais-docs"), ("acme/w.a.i.s.2", "kern-w-a-i-s-2")])
def test_fremde_repos_bleiben_auf_allen_seiten_erlaubt(repo, projekt):
    assert dev_agent.repo_pruefen(repo) == repo
    assert D.check_repo(repo) == repo
    assert seite_kern(repo, None) == seite_dispatcher(repo, None) == projekt
    assert K.projekt_pruefen(projekt, repo) is None


def test_das_einrichtungsskript_des_kern_kanals_sperrt_dieselben_namen():
    """pruefe_repos in wamo-job-kern-einrichten.sh bildet dieselbe Vergleichsform (klein, nur a-z und 0-9) und sperrt dieselben Namen."""
    treffer = re.search(r'case "\$vergleich" in ([a-z0-9|]+)\)', SKRIPT)
    assert treffer, "die Prüfung auf das eigene Repo steht nicht mehr im Skript"
    assert set(treffer.group(1).split("|")) == {K.repo_vergleichsname(n) for n in SELF_REPOS} == {"wamo", "wais"}


# ================================================================== Namensvertrag (CLAUDE.md)
# Die Namen aus der Arbeitsliste (R13) und was die Umsetzung zusätzlich eingeführt hat
NAMEN_AUS_DER_ARBEITSLISTE = (
    "wamo-kern-jobs", "authorized_keys.d/wamo-kern", "kernkanal.conf", "kernkanal.notaus", "wamo-entwicklung-buero.conf",
    "wamo-job-kern-einrichten.sh", "wamo-job-kern-rueckweg.sh", "wamo_job_kern_rauchtest.py", "wamo_job_kernkanal.py",
    "WAMO_ENTWICKLUNG_BUERO", "WAMO_ENTWICKLUNG_PROFILE", "WAMO_ENTWICKLUNG_KOSTEN_AUFTRAG_USD", "WAMO_ENTWICKLUNG_KOSTEN_TAG_USD",
    "WAMO_ENTWICKLUNG_BEFEHLE_BUERO", "Dispatcher 8", "/var/backups/wamo-job-kern", "/var/log/wamo-job-kern", "kernkanal.jsonl",
)
NAMEN_DER_UMSETZUNG = (
    "MAX_VERSUCH_STUNDE", "`versuch`", ".notaus-", "als_kern", "wamo-job-kern-rauchtest", "entwicklung_betrieb.py", "SCHRANKEN_VERSION",
    "KANAL_GRUENDE", "GRUND_SAETZE", "kanal_gesperrt", "auftrag_quittung", "entwicklung_grund", "WAMO_JOB_KERN_WURZEL",
    "WAMO_JOB_KERN_PYTHON", "WAMO_JOB_KERN_SUCHFRIST_S", "auftragStart.ts", "entwicklungsauftrag", "aktionen.jsonl", "BueroZulassung",
    "ExposeAuthInfo", "%u-kern", "/opt/wamo/waechter", "WAMO_ENTWICKLUNG_ORT", "wamo.conf.vorher", "slot_betrieb",
    "test_kernkanal_vertrag.py", "test_entwicklung_betrieb.py", "test_kernkanal.py", "test_job_kern_skripte.py",
    "test_wamo_kern_sokrates2.py", "auftragStart.test.ts", "docs/entwicklung-im-betrieb.md",
    # Ausrollen P5: Mitglieder und Trennung je Profil
    "WAMO_ENTWICKLUNG_MITGLIEDER", "kern-<Kennung>-<Name>", "grenze_profil", "--mitglieder", "SATZ_ANDERER_AUFTRAG", "MAX_NEU_STUNDE_PROFIL",
)
# Variablen, die es schon vor dem Vorhaben gab (stehen in der README und in den .env.example, nicht im Namensvertrag)
VORHANDENE_VARIABLEN = {"WAMO_BETRIEB", "WAMO_ENTWICKLUNG", "WAMO_ABNAHME_BEFEHLE", "WAMO_CLAUDE_SCHLUESSEL_PROFIL"}
# Neu mit Plan C (Paket K); die Zeile im Namensvertrag von CLAUDE.md schreibt Paket R (C.9), danach fällt dieser Eintrag weg
VARIABLEN_BIS_PAKET_R = {"WAMO_ENTWICKLUNG_GITHUB"}


# Zugangsart haus (P6b, docs/ausrollen-neue-nutzer.md, Abschnitt 4.7)
NAMEN_HAUS = ("WAMO_ENTWICKLUNG_HAUS", "WAMO_HAUS", "WAMO_HAUS_MAX_TOKEN", "/run/wamo-haus", "ZUGAENGE_KERN", "Zugangsart `haus`",
              "wamo-haus-proxy")


@pytest.mark.parametrize("name", NAMEN_AUS_DER_ARBEITSLISTE + NAMEN_DER_UMSETZUNG + NAMEN_HAUS)
def test_der_namensvertrag_nennt_den_namen(name):
    assert name in NAMENSVERTRAG, f"{name} fehlt im Namensvertrag (CLAUDE.md)"


def test_jede_variable_der_neuen_dateien_steht_im_namensvertrag():
    neue_dateien = (VOICE_CORE / "entwicklung_betrieb.py", INFRA / "wamo-job-kern-einrichten.sh", INFRA / "wamo-job-kern-rueckweg.sh",
                    INFRA / "wamo_job_kern_rauchtest.py", INFRA / "wamo_job_kernkanal.py")
    gefunden = {n for datei in neue_dateien for n in re.findall(r"\bWAMO_[A-Z0-9]+(?:_[A-Z0-9]+)*\b", _text(datei))}
    assert len(gefunden) >= 8
    fehlen = sorted(n for n in gefunden - VORHANDENE_VARIABLEN - VARIABLEN_BIS_PAKET_R if n not in NAMENSVERTRAG)
    assert not fehlen, f"nicht im Namensvertrag: {fehlen}"


# ================================================================== Ausrollen P5: Trennung je Profil auf beiden Seiten
KENNUNG = eb.BueroZulassung(PROFIL).kennung  # "aaaaaaaa"


def seite_kern_k(repo, wort, kennung=KENNUNG):
    try:
        return eb.kern_projektname(repo, wort, kennung)
    except eb.ProjektnameFehler as e:
        return ("abgelehnt", e.grund)


def seite_dispatcher_k(repo, wort, kennung=KENNUNG):
    try:
        return K.kern_projektname(repo, wort, kennung)
    except K.ProjektnameFehler as e:
        return ("abgelehnt", e.grund)


def test_p5_die_kennung_ist_auf_allen_seiten_dieselbe_form():
    assert KENNUNG == "aaaaaaaa" and K.PROFIL_RE.fullmatch(KENNUNG) and D.PROFIL_RE.fullmatch(KENNUNG)
    assert K.PROFIL_RE.pattern == D.PROFIL_RE.pattern == eb.KENNUNG_RE.pattern == "[0-9a-f]{8}"
    assert eb.kennung_von(PROFIL) == KENNUNG  # Log und Audit


def test_p5_die_kopfzeile_des_kerns_traegt_die_kennung_des_projektnamens(monkeypatch):
    """Verhalten statt Quelltext: _remote_zugang baut die Kopfzeile, deren profil der Dispatcher mit dem Projektnamen vergleicht."""
    import asyncio
    from unittest import mock

    class Memory:
        user_id = PROFIL.upper()

    monkeypatch.delenv("WAMO_BETRIEB", raising=False)
    monkeypatch.setattr(dev_agent, "persoenlicher_zugang", mock.AsyncMock(return_value={"typ": "api", "wert": "x"}))
    kopf, _zeile = asyncio.run(dev_agent.DevAgent(memory=Memory(), auftraggeber="Test")._remote_zugang())
    assert kopf == {"zugang": "folgt", "profil": KENNUNG}
    name = eb.buero_projekt("recherche", None, "Marktstudie", eb.BueroZulassung(PROFIL))
    assert K.projekt_pruefen(name, None, kopf["profil"]) is None and D.PROFIL_RE.fullmatch(kopf["profil"])


def test_p5_beide_seiten_geben_mit_kennung_bei_jeder_eingabe_dasselbe():
    eingaben = _zufaellige_eingaben(1500)
    abweichungen = [(e, seite_kern_k(*e), seite_dispatcher_k(*e)) for e in eingaben if seite_kern_k(*e) != seite_dispatcher_k(*e)]
    assert not abweichungen, abweichungen[:5]
    for kennung in ("AAAAAAAA", "aaaaaaa", "aaaaaaaaa", "", "../aaaa"):
        assert seite_kern_k(None, "x", kennung) == seite_dispatcher_k(None, "x", kennung) == ("abgelehnt", "projekt")


def test_p5_der_dispatcher_nimmt_jeden_namen_des_kerns_nur_mit_demselben_profil_an():
    for repo, wort in _zufaellige_eingaben(1500):
        name = seite_kern_k(repo, wort)
        if isinstance(name, tuple):
            continue
        assert name.startswith(f"kern-{KENNUNG}-"), name
        assert K.projekt_pruefen(name, repo, KENNUNG) is None, (repo, wort, name)
        assert K.projekt_pruefen(name, repo, "bbbbbbbb") == "projekt", (repo, wort, name)


def test_p5_der_buero_auftrag_traegt_die_kennung_der_zulassung():
    z = eb.BueroZulassung(PROFIL)
    name = eb.buero_projekt("recherche", None, "Marktstudie", z)
    assert name == "kern-aaaaaaaa-marktstudie" and K.projekt_pruefen(name, None, z.kennung) is None


def test_p5_grenze_profil_hat_im_kern_einen_satz_und_belegt_den_satz_der_einfachen_warteschlange():
    assert "grenze_profil" in K.KANAL_GRUENDE and eb.GRUND_SAETZE["grenze_profil"].endswith(".")
    assert eb.ablehn_grund(4, {"belegt": {"grund": "Es läuft schon ein Auftrag"}}) == eb.SATZ_ANDERER_AUFTRAG
    # Dispatcher 9: belegt trägt die erreichte Grenze, der Satz "anderer Auftrag" gilt nur noch für ein Ereignis ohne Code (Dispatcher bis Version 8)
    assert eb.ablehn_grund(4, {"belegt": {"grund": "Es laufen schon 6 Aufträge", "grenze": "gesamt", "max": 6}}) != eb.SATZ_ANDERER_AUFTRAG
    assert D.PARALLEL_MAX == K.PARALLEL_HART == 6  # sechs gesamt (Entscheidung von Niko 16.11.2026)


def test_p5_das_skript_verlangt_fuer_mitglieder_die_schranken_version_des_kerns():
    std = _std_werte(SKRIPT)
    assert std["MITGLIEDER"] == "aus"
    assert re.search(r"^MIN_SCHRANKEN_MITGLIEDER=2\b", SKRIPT, flags=re.M)
    assert eb.SCHRANKEN_VERSION >= 2
    rumpf = _funktion(SKRIPT, "drop_in_text")
    assert f"Environment={eb.ENV_MITGLIEDER}=${{MITGLIEDER:-$STD_MITGLIEDER}}" in rumpf
    assert _an_aus_werte_gleich()


def _an_aus_werte_gleich() -> bool:
    """Das Skript schreibt nur an oder aus, und genau diese Werte versteht der Kern (alles andere heißt dort ungueltig, also aus)."""
    return eb._AN[0] == "an" and eb._AUS[0] == "aus" and 'an|aus) ;; *) aufruf "--mitglieder braucht an oder aus"' in SKRIPT


def test_p5_die_grenzen_je_profil_liegen_unter_den_gesamtgrenzen_und_das_skript_kann_sie_setzen():
    std = _std_werte(SKRIPT)
    assert int(std["MAX_NEU_STUNDE_PROFIL"]) <= int(std["MAX_START_STUNDE"]) and int(std["MAX_NEU_TAG_PROFIL"]) <= int(std["MAX_START_TAG"])
    assert int(std["MAX_VERSUCH_STUNDE_PROFIL"]) <= int(std["MAX_VERSUCH_STUNDE"]) <= K.MAX_VERSUCH_STUNDE_FEST
    assert int(std["MAX_LAUFZEIT_TAG_S_PROFIL"]) <= int(std["MAX_LAUFZEIT_TAG_S"])
    for option, schluessel in (("--max-neu-stunde-profil", "MAX_NEU_STUNDE_PROFIL"), ("--max-neu-tag-profil", "MAX_NEU_TAG_PROFIL"),
                               ("--max-versuch-stunde-profil", "MAX_VERSUCH_STUNDE_PROFIL"),
                               ("--max-laufzeit-tag-s-profil", "MAX_LAUFZEIT_TAG_S_PROFIL"), ("--max-versuch-stunde", "MAX_VERSUCH_STUNDE")):
        klein, gross = K.ZAHLEN[schluessel]
        assert re.search(rf'{option}\) optionswert "\$@"; GRENZE\[{schluessel}\]="\$2"; pruefe_zahl "\$1" "\$2" {klein} {gross};', SKRIPT), option


def test_p5_skript_und_rauchtest_verlangen_dispatcher_9():
    assert re.search(r"^MIN_DISPATCHER=9\b", SKRIPT, flags=re.M) and int(D.VERSION) >= 9
    assert re.search(r"^MIN_DISPATCHER_PERSOENLICH=10\b", SKRIPT, flags=re.M) and D.VERSION == "10"  # Plan C: kanal --persoenlich, --github
    assert ">= 9" in (INFRA / "wamo_job_kern_rauchtest.py").read_text(encoding="utf-8")
    assert re.search(r"^PARALLEL_HART=6\b", SKRIPT, flags=re.M) and K.PARALLEL_HART == 6
    assert "grenze_profil" in K.KANAL_GRUENDE  # das Skript prüft das installierte Modul auf diesen Code


# ================================================================== Plan C, Paket S: persönliche GitHub-Zugänge
# docs/persoenliche-zugaenge.md, C.2.6 bis C.2.9. Wie bei I6 stehen die Listen als Wortlaut im Test: Weicht eine Seite ab, wird er rot.
# Die Gründe hält der Kern-Kanal (K), Feldnamen, Token-Formen, Rechte-Regeln und das Protokoll Werkzeuge wamo_job_github.py (G),
# die Sätze und die Gegenstücke der Konstanten der Kern (eb).
G = _lade("wamo_job_github_vertrag", "wamo_job_github.py")

C26_GITHUB = ("github_zeile", "token_ungueltig", "token_abgelaufen", "token_rechte", "repo_nicht_erreichbar", "eigenes_repo",
              "repo_zu_gross", "klon_fehler", "bereinigung", "projekt_gewechselt", "github_wechsel")
C26_AENDERUNG = ("pfad_gesperrt", "geheimnis", "zu_gross", "zu_viele_commits", "symlink", "sonderdatei", "basis_fehlt",
                 "bundle_ungueltig", "pruefung_fehler", "schon_eingereicht")
C26_EINREICHEN = ("zustand", "veraltet", "bestaetigung", "konto", "token_rechte", "repo_geaendert", "keine_schreibrechte",
                  "zweig_belegt", "geheimnis", "token_abgelaufen", "github_fehler")
# Liste im Kern-Kanal: (Tabelle der Sätze im Kern, Wortlaut aus C.2.6)
C26_LISTEN = {"GITHUB_GRUENDE": ("GITHUB_SAETZE", C26_GITHUB), "AENDERUNG_GRUENDE": ("AENDERUNG_SAETZE", C26_AENDERUNG),
              "EINREICHEN_GRUENDE": ("EINREICHEN_SAETZE", C26_EINREICHEN)}
CODE_RE = re.compile(r"[a-z][a-z_]{1,29}")


def test_c26_die_neuen_codes_des_kanals_haben_im_kern_einen_satz():
    assert K.KANAL_GRUENDE[-2:] == ("persoenlich_aus", "grenze_einreichen")  # angehängt, die alten Codes bleiben in ihrer Reihenfolge
    assert eb.GRUND_SAETZE["persoenlich_aus"] == "Persönliche GitHub-Zugänge sind im Kanal nicht eingeschaltet."
    assert eb.GRUND_SAETZE["grenze_einreichen"] == "Für heute sind genug Änderungen eingereicht."


def test_c26_dauerhafte_gruende_sind_codes_des_kanals():
    """Nach einer dauerhaften Abweisung stellt der Kern eine Weile keine neue Karte. persoenlich_aus hängt nicht am einzelnen Auftrag,
    grenze_einreichen betrifft nur das Einreichen und sperrt keine Karte."""
    assert eb.GRUENDE_DAUERHAFT <= set(K.KANAL_GRUENDE)
    assert "persoenlich_aus" in eb.GRUENDE_DAUERHAFT and "grenze_einreichen" not in eb.GRUENDE_DAUERHAFT


@pytest.mark.parametrize("liste", C26_LISTEN)
def test_c26_jede_liste_gilt_auf_beiden_seiten(liste):
    saetze_name, wortlaut = C26_LISTEN[liste]
    assert getattr(K, liste) == wortlaut
    saetze = getattr(eb, saetze_name)
    assert tuple(saetze) == wortlaut, "jeder Code hat genau einen Satz, in derselben Reihenfolge"
    assert len(set(wortlaut)) == len(wortlaut)
    for code, satz in saetze.items():
        assert CODE_RE.fullmatch(code), code
        assert isinstance(satz, str) and satz.strip(), code


def test_c26_ein_code_in_mehreren_listen_hat_ueberall_denselben_satz():
    tabellen = [eb.GRUND_SAETZE, eb.GITHUB_SAETZE, eb.AENDERUNG_SAETZE, eb.EINREICHEN_SAETZE]
    gemeinsam: set[str] = set()
    for i, a in enumerate(tabellen):
        for b in tabellen[i + 1:]:
            for code in set(a) & set(b):
                assert a[code] == b[code], code
                gemeinsam.add(code)
    assert gemeinsam == {"token_rechte", "token_abgelaufen", "geheimnis"}  # ein neuer gemeinsamer Code braucht hier eine bewusste Zeile


def test_c26_einreichen_fehler_ist_eindeutig():
    """einreichen_fehler trägt einen Code aus EINREICHEN_GRUENDE oder KANAL_GRUENDE (C.2.4): beide Listen dürfen sich nicht überschneiden.
    start_abgelehnt trägt im persönlichen Weg einen Code aus GITHUB_GRUENDE, der Weg mit der App einen Text; auch hier keine Überschneidung."""
    assert not set(K.EINREICHEN_GRUENDE) & set(K.KANAL_GRUENDE)
    assert not set(K.GITHUB_GRUENDE) & set(K.KANAL_GRUENDE)
    assert not set(K.AENDERUNG_GRUENDE) & set(K.KANAL_GRUENDE)


def test_c26_unbekannte_gruende_bleiben_im_kern_beim_allgemeinen_satz():
    assert eb.grund_satz("persoenlich_aus") == eb.GRUND_SAETZE["persoenlich_aus"]
    assert eb.grund_satz("token_rechte") == eb.GRUND_UNBEKANNT  # kein Code des Kanals: der Kanal-Satz greift nicht nebenbei


# ---------------------------------------------------------------- C.2.8: Rechte klassischer Tokens je Person
SCOPE_KONSTANTEN = ("FELD_GITHUB", "GITHUB_PERSOENLICH", "FELD_SCOPES_AUSNAHMEN", "SCOPES_PFLICHT_EINER", "SCOPES_MAX", "SCOPES_UNBEDENKLICH",
                    "SCOPES_STANDARD_ABGELEHNT", "SCOPES_NIE", "SCOPES_AUSNAHMEN", "GITHUB_TOKEN_FORMEN", "GITHUB_ABLAUF_MAX_TAGE")
# Entscheidung von Niko vom 18.11.2026: diese lehnt die strenge Liste ab (dazu alle admin:- und user:-Rechte), diese erlaubt der Admin nie
NIKO_STRENG = ("delete_repo", "site_admin", "write:packages", "delete:packages", "user", "workflow", "gist", "write:org")
NIKO_NIE = ("delete_repo", "site_admin", "admin:enterprise")
# Die klassischen Scopes von GitHub (Stand 18.11.2026, docs.github.com "Scopes for OAuth apps"). Jeder steht in genau einer Liste.
# Kommt bei GitHub einer dazu, ist er abgelehnt (fail closed), bis er hier und in einer der drei Listen auf beiden Seiten steht.
BEKANNTE_SCOPES = (
    "repo", "repo:status", "repo_deployment", "public_repo", "repo:invite", "security_events",
    "admin:repo_hook", "write:repo_hook", "read:repo_hook", "admin:org", "write:org", "read:org",
    "admin:public_key", "write:public_key", "read:public_key", "admin:org_hook", "gist", "notifications",
    "user", "read:user", "user:email", "user:follow", "project", "read:project", "delete_repo",
    "write:packages", "read:packages", "delete:packages", "admin:gpg_key", "write:gpg_key", "read:gpg_key",
    "codespace", "codespace:secrets", "workflow", "copilot", "manage_billing:copilot",
    "write:network_configurations", "read:network_configurations", "manage_runners:org",
    "admin:enterprise", "manage_runners:enterprise", "manage_billing:enterprise", "read:enterprise",
    "audit_log", "read:audit_log", "admin:ssh_signing_key", "write:ssh_signing_key", "read:ssh_signing_key",
    "write:discussion", "read:discussion", "site_admin",
)
SCOPE_RE = re.compile(r"[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)?")
SCOPE_LISTEN = ("SCOPES_PFLICHT_EINER", "SCOPES_UNBEDENKLICH", "SCOPES_STANDARD_ABGELEHNT", "SCOPES_NIE", "SCOPES_AUSNAHMEN")


@pytest.mark.parametrize("name", SCOPE_KONSTANTEN)
def test_c28_kern_und_dispatcher_halten_dieselben_werte(name):
    assert getattr(eb, name) == getattr(G, name), name


def test_c28_feldnamen_und_werte():
    assert (G.FELD_GITHUB, G.GITHUB_PERSOENLICH, G.FELD_SCOPES_AUSNAHMEN) == ("github", "persoenlich", "scopes_ausnahmen")
    assert G.GITHUB_ABLAUF_MAX_TAGE == 366  # C5: höchstens 366 Tage in der Zukunft
    assert G.SCOPES_MAX == 30  # wie die Spalte scopes in 0027 (C.3)
    assert G.FELD_SCOPES_AUSNAHMEN in G.EINREICHEN_FELDER  # auch beim Einreichen gilt die Einstellung von jetzt (C.5 Einreichen 3)


@pytest.mark.parametrize("liste", SCOPE_LISTEN)
def test_c28_die_listen_haben_die_feste_form(liste):
    werte = getattr(G, liste)
    assert isinstance(werte, tuple) and werte and len(set(werte)) == len(werte), liste
    for scope in werte:
        assert SCOPE_RE.fullmatch(scope), (liste, scope)  # nur Namen, keine Muster


def test_c28_jeder_bekannte_scope_steht_in_genau_einer_liste():
    drei = (G.SCOPES_UNBEDENKLICH, G.SCOPES_AUSNAHMEN, G.SCOPES_NIE)
    for scope in BEKANNTE_SCOPES:
        assert sum(scope in liste for liste in drei) == 1, scope
    assert set().union(*drei) == set(BEKANNTE_SCOPES)
    assert set(G.SCOPES_STANDARD_ABGELEHNT) == set(G.SCOPES_NIE) | set(G.SCOPES_AUSNAHMEN)
    assert not set(G.SCOPES_STANDARD_ABGELEHNT) & set(G.SCOPES_UNBEDENKLICH)


def test_c28_die_entscheidung_steht_in_den_listen():
    assert set(NIKO_STRENG) <= set(G.SCOPES_STANDARD_ABGELEHNT)
    assert set(NIKO_NIE) <= set(G.SCOPES_NIE)
    for scope in G.SCOPES_UNBEDENKLICH:  # admin:* und user-Rechte: kein solcher Scope ist unbedenklich
        assert not scope.startswith(("admin:", "user:")) and scope != "user", scope
    for scope in ("read:packages", "codespace", "codespace:secrets"):  # C.4 Schritt 3
        assert scope in G.SCOPES_STANDARD_ABGELEHNT, scope
    for scope in ("manage_runners:org", "write:public_key", "write:gpg_key", "write:ssh_signing_key", "write:repo_hook"):  # Review
        assert scope in G.SCOPES_AUSNAHMEN, scope


def test_c28_die_pflichtrechte_sind_unbedenklich():
    assert G.SCOPES_PFLICHT_EINER == ("repo", "public_repo")
    assert set(G.SCOPES_PFLICHT_EINER) <= set(G.SCOPES_UNBEDENKLICH)


def _scopes_aus_kopf(wert: str) -> tuple[str, ...]:
    """Normalisierung der Kopfzeile X-OAuth-Scopes aus C.2.8: am Komma getrennt, Leerzeichen am Rand weg, leere Einträge übergangen."""
    return tuple(s.strip(" ") for s in wert.split(",") if s.strip(" "))


def _scope_grund(scopes: tuple[str, ...], ausnahmen: tuple[str, ...] = ()) -> str | None:
    """Die Regel aus C.2.8 als Referenz für K (Speichern) und D-b (Start und Einreichen): None oder token_rechte. Ausnahmen gelten nur aus
    SCOPES_AUSNAHMEN; ein anderer Wert im Feld macht die Zeile schon vorher ungültig (Abgewiesen), hier zählt er einfach nicht.
    Auftrag an K und D-b: ihre Prüfung zusätzlich gegen SCOPE_FAELLE laufen lassen (eigene Seiten wie bei I5)."""
    erlaubt = set(G.SCOPES_UNBEDENKLICH) | (set(ausnahmen) & set(G.SCOPES_AUSNAHMEN))
    if len(scopes) > G.SCOPES_MAX or not set(scopes) & set(G.SCOPES_PFLICHT_EINER):
        return "token_rechte"
    if any(s not in erlaubt for s in scopes):
        return "token_rechte"
    return None


# (Scopes aus X-OAuth-Scopes, Ausnahmen der Person, Ergebnis)
SCOPE_FAELLE = (
    (("repo",), (), None),
    (("public_repo", "read:org"), (), None),
    (("repo", "read:user", "notifications", "project"), (), None),  # lesende und harmlose Rechte
    ((), (), "token_rechte"),  # ohne repo oder public_repo geht nichts
    (("read:org",), (), "token_rechte"),
    (("repo", "workflow"), (), "token_rechte"),
    (("repo", "workflow"), ("workflow",), None),
    (("repo", "workflow", "gist"), ("workflow",), "token_rechte"),
    (("repo", "admin:org"), (), "token_rechte"),
    (("repo", "admin:org"), ("admin:org",), None),
    (("repo", "admin:repo_hook"), ("admin:org",), "token_rechte"),  # Ausnahmen gelten genau
    (("repo", "admin:neu_bei_github"), ("admin:neu_bei_github",), "token_rechte"),  # unbekannt: abgelehnt, auch nicht erlaubbar
    (("repo", "ganz_neu"), (), "token_rechte"),
    (("repo", "Repo"), (), "token_rechte"),  # Groß- und Kleinschreibung zählt
    (("repo", "admin:enterprise"), ("admin:enterprise",), "token_rechte"),  # nie erlaubt, auch wenn der Kern es schickte
    (("repo", "delete_repo"), ("delete_repo",), "token_rechte"),
    (("repo", "site_admin"), ("site_admin",), "token_rechte"),
    (("repo", "manage_runners:enterprise"), ("manage_runners:org",), "token_rechte"),
    (("repo", "manage_runners:org"), (), "token_rechte"),  # Runner führen Code aus (Review)
    (("repo", "manage_runners:org"), ("manage_runners:org",), None),
    (("repo", "write:public_key"), (), "token_rechte"),  # Schlüssel auf dem Konto schaffen dauerhaften Zugriff (Review)
    (("repo", "user:email"), ("user",), "token_rechte"),
    (("repo", "user", "user:email"), ("user", "user:email"), None),
    (("repo", "write:packages", "read:packages"), ("write:packages",), "token_rechte"),
    (("repo", "codespace:secrets"), ("codespace:secrets",), None),
    (("repo",) * 31, (), "token_rechte"),  # mehr als SCOPES_MAX Einträge
)


@pytest.mark.parametrize("kopf, erwartet", [("repo", ("repo",)), ("repo, gist", ("repo", "gist")), (" repo ,, read:org ", ("repo", "read:org")),
                                            ("", ()), (" , ", ())])
def test_c28_normalisierung_der_kopfzeile(kopf, erwartet):
    assert _scopes_aus_kopf(kopf) == erwartet


@pytest.mark.parametrize("scopes, ausnahmen, erwartet", SCOPE_FAELLE)
def test_c28_wertetabelle_der_regel(scopes, ausnahmen, erwartet):
    assert _scope_grund(scopes, ausnahmen) == erwartet
    assert erwartet is None or (erwartet in K.GITHUB_GRUENDE and erwartet in K.EINREICHEN_GRUENDE)


@pytest.mark.parametrize("kanal", ["pc", "lokal"])
@pytest.mark.parametrize("feld", ["github", "scopes_ausnahmen"])
def test_c28_dispatcher_10_nimmt_die_neuen_kopffelder_nur_im_kern_kanal(feld, kanal, monkeypatch):
    """Paket D-a: beide Felder nur im Kern-Kanal, scopes_ausnahmen nur mit github=persoenlich, Werte nur aus SCOPES_AUSNAHMEN, sortiert und
    ohne Doppel. Außerhalb des Kern-Kanals bleibt es fail closed."""
    wert = G.GITHUB_PERSOENLICH if feld == G.FELD_GITHUB else []
    roh = json.dumps({"auftrag": "x", "zugang": "haus", "profil": KENNUNG, "repo": "acme/demo", feld: wert}) + "\n"
    assert D.VERSION == "10"
    monkeypatch.setattr(D, "KANAL", kanal)
    with pytest.raises(D.Abgewiesen):
        D.parse_header(roh.encode("utf-8"))


def test_c28_im_kern_kanal_gelten_die_ausnahmen_aus_der_festen_liste(monkeypatch):
    monkeypatch.setattr(D, "KANAL", "kern")

    def kopf(**felder):
        return (json.dumps({"auftrag": "x", "zugang": "haus", "profil": KENNUNG, "repo": "acme/demo", **felder}) + "\n").encode("utf-8")
    alle = sorted(G.SCOPES_AUSNAHMEN)
    k = D.parse_header(kopf(**{G.FELD_GITHUB: G.GITHUB_PERSOENLICH, G.FELD_SCOPES_AUSNAHMEN: alle}))
    assert (k.github, k.scopes_ausnahmen) == (G.GITHUB_PERSOENLICH, tuple(alle))
    for schlecht in ([*G.SCOPES_NIE[:1]], [G.SCOPES_UNBEDENKLICH[0]], ["neu_bei_github"], [alle[1], alle[0]], [alle[0], alle[0]], "gist"):
        with pytest.raises(D.Abgewiesen):
            D.parse_header(kopf(**{G.FELD_GITHUB: G.GITHUB_PERSOENLICH, G.FELD_SCOPES_AUSNAHMEN: schlecht}))
    with pytest.raises(D.Abgewiesen):
        D.parse_header(kopf(**{G.FELD_SCOPES_AUSNAHMEN: []}))  # nur mit github


# ---------------------------------------------------------------- C.2.2: GitHub-Zeile und Token-Formen
def _token(art: str, zeichen: str = "A") -> str:
    # synthetisch zusammengesetzt, damit kein vollständiger Tokenwert als Text in der Datei steht
    return "ghp_" + zeichen * 36 if art == "klassisch" else "github_pat_" + (zeichen + "_") * 41


def _zeile_des_kerns(wert: str) -> bytes:
    """So baut der Kern die Zeile (C.2.2: genau diese Form, ohne Leerzeichen, Zeilenende LF). Paket K übernimmt genau das."""
    return (json.dumps({"typ": "github", "wert": wert}, separators=(",", ":")) + "\n").encode("utf-8")


@pytest.mark.parametrize("art", ["klassisch", "fein"])
def test_c22_die_zeile_des_kerns_nimmt_der_dispatcher_an(art):
    wert = _token(art)
    assert re.fullmatch(eb.GITHUB_TOKEN_FORMEN[art], wert)
    zeile = bytearray(_zeile_des_kerns(wert))
    assert len(zeile) <= G.GITHUB_ZEILE_MAX_BYTES and zeile.endswith(b"\n")
    assert G.GITHUB_ZEILE_RE.fullmatch(memoryview(zeile)[:-1]) is not None  # Bytes-Regel auf einem memoryview, ohne Kopie (C.2.2)


@pytest.mark.parametrize("wert", [
    "gho_" + "A" * 36, "ghu_" + "A" * 36, "ghs_" + "A" * 36, "ghr_" + "A" * 36,  # andere Formen weist schon der Kern ab (C.4 Schritt 1)
    "ghp_" + "A" * 35, "ghp_" + "A" * 37, "ghp_" + "A" * 35 + "_", "github_pat_" + "a" * 81, "github_pat_" + "a" * 83,
    "github_pat_" + "a" * 81 + "-", "", "ghp_" + "Ä" * 36])
def test_c22_falsche_formen_nimmt_keine_seite_an(wert):
    assert not any(re.fullmatch(form, wert) for form in eb.GITHUB_TOKEN_FORMEN.values())
    assert G.GITHUB_ZEILE_RE.fullmatch(_zeile_des_kerns(wert)[:-1]) is None


@pytest.mark.parametrize("zeile", [
    b'{"typ": "github", "wert": "%s"}', b'{"wert":"%s","typ":"github"}', b'{"typ":"github","wert":"%s","x":1}',
    b' {"typ":"github","wert":"%s"}', b'{"typ":"github","wert":"%s"} ', b'{"typ":"api","wert":"%s"}'])
def test_c22_nur_genau_die_feste_form_der_zeile_gilt(zeile):
    assert G.GITHUB_ZEILE_RE.fullmatch(zeile % _token("klassisch").encode("ascii")) is None


def test_c22_die_formen_sind_die_aus_dem_plan():
    assert G.GITHUB_TOKEN_FORMEN == {"klassisch": "ghp_[A-Za-z0-9]{36}", "fein": "github_pat_[A-Za-z0-9_]{82}"}
    assert G.GITHUB_ZEILE_MAX_BYTES == 256


# ---------------------------------------------------------------- C.2.3 bis C.5.2: Befehle, Zustände, Modi, Sperren
def test_c23_die_neuen_befehle_passen_zur_befehlsform_des_dispatchers():
    assert G.BEFEHLE_GITHUB == ("aenderung", "einreichen", "verwerfen")
    assert G.BEFEHLE_GITHUB_GESCHLOSSEN == ("aenderung", "verwerfen")  # auch bei geschlossenem Kanal (C.2.3), nie einreichen
    for befehl in G.BEFEHLE_GITHUB:
        roh = f"{befehl} {'0' * 16} {KENNUNG}"
        assert D.COMMAND_RE.fullmatch(roh) and len(roh) <= D.MAX_COMMAND_CHARS, befehl
    assert G.EINREICHEN_FELDER == ("commit_id", "tree_id", "bestaetigt", "scopes_ausnahmen")
    assert G.EINREICHEN_ZEILE_MAX_BYTES == 64 * 1024


def test_c24_ereignisse_und_zustaende():
    assert G.EREIGNISSE_GITHUB == ("github", "aenderung", "eingereicht", "einreichen_fehler", "verworfen")
    assert G.AENDERUNG_STATUS == ("keine", "gesperrt", "nur_lesen", "bereit", "einreichen_laeuft", "branch_gepusht", "eingereicht",
                                  "verworfen")


def test_c52_die_modi_der_sandbox_schliessen_die_heutigen_ein():
    treffer = re.search(r"^case \"\$MODUS\" in\n  ([a-z|]+)\) ;;\n  \*\) fehler", _text(INFRA / "wamo-job.sh"), flags=re.M)
    assert treffer, "wamo-job.sh: case mit Ablehnung als Standard (C.5.2)"
    assert tuple(treffer.group(1).split("|")) == G.SANDBOX_MODI
    assert G.SANDBOX_MODI == ("lauf", "pruefen", "klon", "ausgabe", "pruefung")
    assert G.SANDBOX_MODI_NETZLOS == ("klon", "ausgabe", "pruefung")
    assert G.SPERREN == (".lauf", ".einreichen", "kernkanal")
    assert G.AUFTRAG_DATEIEN == ("basis.git", "aus.git", "bundle.ein", "ausgabe", "ergebnis", "github.json", "aenderung.json",
                                 "einreichen.json")


# ---------------------------------------------------------------- C.9: Protokoll-Klasse Werkzeuge (Schnittstelle D-a zu D-b)
# Methode: Namen der Parameter ohne self. Ändert eine Seite die Form, wird dieser Test rot, bevor D-a und D-b auseinanderlaufen.
# Auftrag an D-a: die echte Umsetzung hier zusätzlich prüfen (isinstance und dieselben Signaturen wie Werkzeuge).
WERKZEUGE_FORM = {
    "log": ("text", "pflicht"),
    "http": ("methode", "pfad", "daten"),
    "git": ("args", "git_dir", "eingabe", "netz", "zeitlimit_s"),
    "sandbox": ("modus", "job", "projekt", "zeitlimit_s"),
    "sperre": ("name",),
    "pfad": ("name",),
    "uhr": (),
    "geheimnis_in": ("daten",),
}
WERKZEUGE_NUR_BENANNT = {"log": {"pflicht"}, "git": {"git_dir", "eingabe", "netz", "zeitlimit_s"},
                         "sandbox": {"job", "projekt", "zeitlimit_s"}}


def test_c9_das_protokoll_hat_genau_diese_methoden():
    import inspect
    import typing

    assert typing.Protocol in G.Werkzeuge.__mro__
    methoden = {n for n, v in vars(G.Werkzeuge).items() if callable(v) and not n.startswith("_")}
    assert methoden == set(WERKZEUGE_FORM)
    for name, parameter in WERKZEUGE_FORM.items():
        signatur = inspect.signature(getattr(G.Werkzeuge, name))
        assert tuple(signatur.parameters)[1:] == parameter, name
        benannt = {p.name for p in signatur.parameters.values() if p.kind is p.KEYWORD_ONLY}
        assert benannt == WERKZEUGE_NUR_BENANNT.get(name, set()), name


def test_c9_eine_attrappe_mit_allen_methoden_erfuellt_das_protokoll():
    class Attrappe:
        def log(self, text, *, pflicht=False): ...
        def http(self, methode, pfad, daten=None): ...
        def git(self, args, *, git_dir, eingabe=None, netz=False, zeitlimit_s=60.0): ...
        def sandbox(self, modus, *, job, projekt, zeitlimit_s): ...
        def sperre(self, name): ...
        def pfad(self, name): ...
        def uhr(self): ...
        def geheimnis_in(self, daten): ...

    class OhneSuche:  # eigene Klasse: isinstance merkt sich ein positives Ergebnis je Klasse
        log, http, git, sandbox, sperre, pfad, uhr = (Attrappe.log, Attrappe.http, Attrappe.git, Attrappe.sandbox, Attrappe.sperre,
                                                      Attrappe.pfad, Attrappe.uhr)

    assert isinstance(Attrappe(), G.Werkzeuge)
    assert not isinstance(OhneSuche(), G.Werkzeuge)


def test_c9_die_ergebnisse_sind_unveraenderlich():
    import dataclasses

    for klasse, felder in ((G.HttpAntwort, ("status", "kopf", "daten")), (G.GitErgebnis, ("code", "stdout", "stderr")),
                           (G.SandboxErgebnis, ("code", "zeitlimit"))):
        assert tuple(f.name for f in dataclasses.fields(klasse)) == felder, klasse.__name__
        assert klasse.__dataclass_params__.frozen, klasse.__name__
    assert issubclass(G.KeinToken, Exception) and issubclass(G.NetzFehler, Exception)


def test_c9_das_modul_ist_ohne_nebenwirkung_und_nur_mit_der_standardbibliothek():
    """Wie das Modul des Kern-Kanals: kein Netz, keine Prozesse, keine Geheimnisse beim Import (installiert unter /opt/wamo/waechter).
    Seit Paket D-b liest und schreibt die Logik Dateien im Auftragsordner selbst (lstat, O_NOFOLLOW, atomar) und lädt die Nachbarmodule
    erst beim Gebrauch; Netz, git und Sandbox gehen weiter nur über Werkzeuge."""
    baum = ast.parse(_text(INFRA / "wamo_job_github.py"))
    erlaubt = {"__future__", "collections.abc", "contextlib", "dataclasses", "pathlib", "re", "types", "typing",
               "datetime", "hashlib", "importlib", "importlib.util", "json", "os", "secrets", "stat", "sys"}
    for knoten in baum.body:
        if isinstance(knoten, ast.Import):
            assert {a.name for a in knoten.names} <= erlaubt, ast.dump(knoten)
        elif isinstance(knoten, ast.ImportFrom):
            assert knoten.module in erlaubt, knoten.module
        elif isinstance(knoten, ast.Expr):
            assert isinstance(knoten.value, ast.Constant) and isinstance(knoten.value.value, str), "nur der Modultext steht frei"
        else:
            assert isinstance(knoten, (ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef)), ast.dump(knoten)
    namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(baum) if isinstance(n, ast.Attribute)}
    assert not namen & {"subprocess", "socket", "environ", "system", "urlopen", "HTTPSConnection", "popen", "Popen", "exec", "eval"}


# ---------------------------------------------------------------- Paket K: die Seite des Kerns gegen die Schnittstelle
def test_k_der_kern_baut_die_zeilen_die_der_dispatcher_annimmt():
    import github_auftrag as ga

    for art in ("klassisch", "fein"):
        zeile = ga.github_zeile(_token(art))
        assert zeile == _zeile_des_kerns(_token(art)) and len(zeile) <= G.GITHUB_ZEILE_MAX_BYTES
        assert G.GITHUB_ZEILE_RE.fullmatch(memoryview(zeile)[:-1]) is not None
    einreichen = json.loads(ga.einreichen_zeile("a" * 40, "b" * 40, ["x"], ["gist", "workflow"]))
    assert tuple(einreichen) == G.EINREICHEN_FELDER
    assert einreichen[G.FELD_SCOPES_AUSNAHMEN] == sorted(einreichen[G.FELD_SCOPES_AUSNAHMEN])
    kopf = ga.kopffelder(("workflow", "gist", "gist", "delete_repo"))
    assert kopf == {G.FELD_GITHUB: G.GITHUB_PERSOENLICH, G.FELD_SCOPES_AUSNAHMEN: ["gist", "workflow"]}
    assert ga.EINREICHEN_ZEILE_MAX_BYTES == G.EINREICHEN_ZEILE_MAX_BYTES and ga.GITHUB_ZEILE_MAX_BYTES == G.GITHUB_ZEILE_MAX_BYTES


def test_k_ereignisse_zustaende_und_saetze_des_kerns():
    import github_auftrag as ga

    assert ga.EREIGNISSE_GITHUB == G.EREIGNISSE_GITHUB and ga.AENDERUNG_STATUS == G.AENDERUNG_STATUS
    assert set(ga.STATUS_KARTE) | set(ga.STATUS_EINREICHEN) | set(ga.STATUS_VERWERFEN) <= set(G.AENDERUNG_STATUS)
    for befehl in G.BEFEHLE_GITHUB:
        assert dev_agent.ssh_argv([befehl, "0" * 16, KENNUNG])[-1] == f"{befehl} {'0' * 16} {KENNUNG}"
    for code in K.EINREICHEN_GRUENDE:
        assert ga.fehler_satz({"grund": code}) == eb.EINREICHEN_SAETZE[code]
    for code in K.GITHUB_GRUENDE:
        assert ga.start_abgelehnt_satz(code) == eb.GITHUB_SAETZE[code]


@pytest.mark.parametrize("scopes, ausnahmen, erwartet", SCOPE_FAELLE)
def test_k_die_pruefung_beim_speichern_folgt_der_wertetabelle(scopes, ausnahmen, erwartet):
    import github_zugang as gz

    assert (gz.scopes_problem(scopes, ausnahmen) is None) == (erwartet is None)


@pytest.mark.parametrize("scopes, ausnahmen, erwartet", SCOPE_FAELLE)
def test_c28_die_regel_des_dispatchers_folgt_der_wertetabelle(scopes, ausnahmen, erwartet):
    """Seite D-b (Start und Einreichen): wamo_job_github.scope_grund gegen die Wertetabelle, wie es _scope_grund oben verlangt."""
    assert G.scope_grund(scopes, ausnahmen) == erwartet


@pytest.mark.parametrize("kopf, erwartet", [("repo", ("repo",)), ("repo, gist", ("repo", "gist")), (" repo ,, read:org ", ("repo", "read:org")),
                                            ("", ()), (" , ", ())])
def test_c28_der_dispatcher_liest_die_kopfzeile_gleich(kopf, erwartet):
    assert G.scopes_aus_kopf(kopf) == erwartet
