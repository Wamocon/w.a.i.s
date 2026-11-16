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
            "grenze_profil")

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
    assert _zeilen_im_muster(muster, EB_QUELLE) == ["SCHRANKEN_VERSION = 3"]  # 3: gleichzeitige Aufträge (Dispatcher 9)
    assert eb.SCHRANKEN_VERSION == 3
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
               "MAX_LAUFZEIT_TAG_S_PROFIL": (60, 86400), "MAX_PARALLEL": (1, 6), "MAX_PARALLEL_PROFIL": (1, 6)}
I2_SCHLUESSEL = {"KANAL", "ABLAUF", "ARTEN", "REPOS", "DIENSTE", "MAX_BUDGET_USD", *I2_BEREICHE}


def _std_werte(skript: str) -> dict[str, str]:
    return dict(re.findall(r"^STD_([A-Z_]+)=(\S+)$", skript, flags=re.M))


def test_i2_standardwerte_des_skripts():
    std = _std_werte(SKRIPT)
    for schluessel, wert in I2_STANDARD.items():
        assert std.get(schluessel) == wert, schluessel
    assert std.get("ABLAUF_TAGE") == str(I2_ABLAUF_TAGE)


def test_i2_der_dispatcher_kennt_dieselben_schluessel_und_bereiche():
    schluessel = re.search(r"^KONFIG_SCHLUESSEL=\(([^)]*)\)", SKRIPT, flags=re.M | re.S)
    assert schluessel
    assert set(schluessel.group(1).split()) == set(K.BEKANNTE_SCHLUESSEL) == I2_SCHLUESSEL
    assert dict(K.ZAHLEN) == I2_BEREICHE
    assert K.MAX_ABLAUF_TAGE == 400 and K.MAX_REPOS == 10 and K.MAX_VERSUCH_STUNDE_FEST == 60


def test_i2_die_standardwerte_des_dispatchers_gleichen_denen_des_skripts():
    standard = K.Konfig()
    assert standard.kanal is None  # fehlt der Schlüssel, gilt der Kanal als zu
    # Ausnahme mit Absicht (Dispatcher 9, Befund des Sicherheitsreviews): fehlen MAX_PARALLEL und MAX_PARALLEL_PROFIL in der Datei, gilt einer
    # gleichzeitig; die Standards 6 und 3 schreibt das Skript (schluessel, kanal) ausdrücklich
    assert (standard.max_parallel, standard.max_parallel_profil) == (1, 1)
    for schluessel in I2_BEREICHE:
        if schluessel in ("MAX_PARALLEL", "MAX_PARALLEL_PROFIL"):
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
             **{schluessel: std[schluessel] for schluessel in (*I2_BEREICHE, "MAX_BUDGET_USD")}}
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
    assert set(eb.ALLE_VARIABLEN) - set(namen) == {eb.ENV_BEFEHLE}


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
    "infra/sokrates2/wamo-core-slots.sh": "e725f4e515dda4ce6f72fa39a5346ba132b19f39f8babc3867be590fc577f150",
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
    fehlen = sorted(n for n in gefunden - VORHANDENE_VARIABLEN if n not in NAMENSVERTRAG)
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
    assert re.search(r"^MIN_DISPATCHER=9\b", SKRIPT, flags=re.M) and D.VERSION == "9"
    assert ">= 9" in (INFRA / "wamo_job_kern_rauchtest.py").read_text(encoding="utf-8")
    assert re.search(r"^PARALLEL_HART=6\b", SKRIPT, flags=re.M) and K.PARALLEL_HART == 6
    assert "grenze_profil" in K.KANAL_GRUENDE  # das Skript prüft das installierte Modul auf diesen Code
