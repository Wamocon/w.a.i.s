"""Tests für scripts/wamo_labor_last.py (Befehlszeile des Lasttests: Trockenlauf, Echtlauf mit zwei Schlössern, Clips, Ausgabe).

Aufruf (aus scripts, mit der Python-Umgebung von voice-core):
  D:\\IDEA\\Projekt\\wamo\\voice-core\\.venv\\Scripts\\python.exe -m pytest -q test_wamo_labor_last.py

Kein ssh, kein Browser, kein Dienst, nie die echte Umschlag-Datei: Der Echtlauf bekommt Attrappen (Umgebungsfabrik), der Trockenlauf ruft nie eine
Umgebungsfabrik auf. Eine Falle bricht jeden Test ab, der einen Prozess starten würde.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_labor_last as cli  # noqa: E402
import wamo_labor_last_attrappe as at  # noqa: E402
import wamo_labor_last_audio as au  # noqa: E402
import wamo_labor_last_plan as pl  # noqa: E402
import wamo_labor_last_server as sv  # noqa: E402
import wamo_labor_last_umgebung as um  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def keine_echten_aufrufe(monkeypatch, tmp_path):
    def falle(*args, **kw):
        raise AssertionError("Der Test hat versucht, einen Prozess zu starten")
    monkeypatch.setattr(subprocess, "Popen", falle)
    monkeypatch.setattr(subprocess, "run", falle)
    heim = tmp_path / "heim"
    heim.mkdir()
    monkeypatch.setenv("USERPROFILE", str(heim))
    monkeypatch.setenv("HOME", str(heim))
    monkeypatch.delenv("WAMO_SSH_HOST", raising=False)


@pytest.fixture
def clips(tmp_path) -> Path:
    ordner = tmp_path / "clips"
    ordner.mkdir()
    for i, name in enumerate(sorted(au.SPRECHPROBEN)):
        au.schreibe_wav(ordner / f"{name}.wav", 8000, [0.4 * math.sin(2 * math.pi * (150 + 20 * i) * k / 8000) for k in range(4000)])
    return ordner


class Fabrik:
    """Umgebungsfabrik des Echtlaufs: baut die Attrappen und merkt sich den Aufruf."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.aufrufe = 0
        self.welt = None

    def __call__(self, ein, args):
        self.aufrufe += 1
        self.ein = ein
        uhr = at.Zeitraffer()
        protokoll = at.Protokoll()
        verhalten = at.Verhalten()
        treiber = {}
        self.protokoll, self.verhalten = protokoll, verhalten

        def fabrik(i):
            treiber[i] = at.TreiberAttrappe(i, uhr, protokoll, verhalten, lambda: sum(1 for t in treiber.values() if t.gespraech))
            return treiber[i]

        def temp():
            ordner = self.tmp_path / "temp"
            ordner.mkdir(exist_ok=True)
            return ordner

        return um.Umgebung(uhr=uhr, treiber_fabrik=fabrik, server=at.ServerAttrappe(uhr, protokoll, aktive=lambda: sum(1 for t in treiber.values() if t.gespraech)), dienst=at.DienstAttrappe(protokoll),
                           kern=at.KernAttrappe(protokoll), umschlag=at.UmschlagAttrappe(), tempordner_fabrik=temp, ausgabe=print, speichern=lambda e: None)


class SlotQuelle:
    """Attrappe für die Ermittlung des aktiven Kern-Slots am Server (sv.aktiven_slot_ermitteln)."""

    def __init__(self, slot: str = "a", fehler: str = ""):
        self.slot, self.fehler = slot, fehler
        self.aufrufe: list[str] = []

    def __call__(self, host: str) -> str:
        self.aufrufe.append(host)
        if self.fehler:
            raise sv.ServerFehler(self.fehler)
        return self.slot


def basis(tmp_path, clips, *zusatz) -> list[str]:
    return ["lauf", "--lauf", "last-t", "--clips-ordner", str(clips), "--ausgabe-ordner", str(tmp_path / "aus"),
            "--umschlag-datei", str(tmp_path / "umschlag.txt"), *zusatz]


# ---------- Trockenlauf ----------

def test_standard_ist_ein_trockenlauf_ohne_umgebung(tmp_path, clips, capsys):
    fabrik = Fabrik(tmp_path)
    assert cli.main(basis(tmp_path, clips), umgebung_bauen=fabrik) == 0
    aus = capsys.readouterr().out
    assert fabrik.aufrufe == 0
    assert "Trockenlauf" in aus and "nichts wird gestartet" in aus
    assert not (tmp_path / "aus").exists()


def test_der_plan_nennt_profile_stufen_dauer_kosten_grenzen_und_das_schloss(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path))
    aus = capsys.readouterr().out
    for teil in ("labor-01 bis labor-08", "8 Profile", "Plätze 1 bis 8", "1 Sitzung, 15 Minuten", "8 Sitzungen, 15 Minuten", "Dauer", "1 Stunde 20 Minuten",
                 "Kosten", "nicht geschätzt", "Annahmen", "17000", "429", "mehr als 2 Abbrüche", "3 GiB", "der aktive Slot", "192.168.178.136:55445",
                 "--ausfuehren --bestaetigung LASTTEST", "Seed 1"):
        assert teil in aus, teil


def test_kosten_in_dollar_nur_mit_beiden_preisen(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips, "--preis-eingabe", "1.0", "--preis-ausgabe", "5.0"), umgebung_bauen=Fabrik(tmp_path))
    aus = capsys.readouterr().out
    assert "USD" in aus and "nicht geschätzt" not in aus.split("Kosten")[1].splitlines()[0]
    assert cli.main(basis(tmp_path, clips, "--preis-eingabe", "1.0"), umgebung_bauen=Fabrik(tmp_path)) == 2


def test_kostenobergrenze_lehnt_zu_teuren_plan_auch_im_trockenlauf_ab(tmp_path, clips, capsys):
    zusatz = ("--preis-eingabe", "3.0", "--preis-ausgabe", "15.0", "--kosten-obergrenze", "1.0")
    assert cli.main(basis(tmp_path, clips, *zusatz), umgebung_bauen=Fabrik(tmp_path)) == 2
    assert "Kostenobergrenze" in capsys.readouterr().err


def test_lokale_befunde_im_trockenlauf_ohne_geheimnisse(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path), umschlag_oeffnen=lambda pfad: at.UmschlagAttrappe(ohne_seed={"labor-03"}))
    aus = capsys.readouterr().out
    assert "Sprechproben: alle 12 vorhanden" in aus
    assert "labor-03: Seed fehlt" in aus and "labor-01: Seed vorhanden" in aus
    assert "Pw-labor" not in aus and at.SEED_B32 not in aus


def test_fehlende_clips_stehen_im_befund_und_der_trockenlauf_bleibt_ein_erfolg(tmp_path, capsys):
    assert cli.main(basis(tmp_path, tmp_path / "leer"), umgebung_bauen=Fabrik(tmp_path)) == 0
    assert "fehlen" in capsys.readouterr().out


def test_murmeln_und_sitzungen_aendern_den_plan(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips, "--sitzungen", "1,2", "--minuten", "10", "--murmeln", "20,10,5"), umgebung_bauen=Fabrik(tmp_path))
    aus = capsys.readouterr().out
    assert "1 Sitzung, 10 Minuten" in aus and "8 Sitzungen, Murmeln 5 dB, 10 Minuten" in aus and "Plätze 1 bis 8" in aus


# ---------- zwei Schlösser ----------

def test_ausfuehren_ohne_bestaetigung_ist_ein_fehler_und_startet_nichts(tmp_path, clips, capsys):
    fabrik = Fabrik(tmp_path)
    assert cli.main(basis(tmp_path, clips, "--ausfuehren"), umgebung_bauen=fabrik) == 2
    assert "LASTTEST" in capsys.readouterr().err and fabrik.aufrufe == 0


@pytest.mark.parametrize("wort", ["lasttest", "LASTTEST ", "ja", ""])
def test_falsches_bestaetigungswort_wird_abgelehnt(tmp_path, clips, wort):
    fabrik = Fabrik(tmp_path)
    assert cli.main(basis(tmp_path, clips, "--ausfuehren", "--bestaetigung", wort), umgebung_bauen=fabrik) == 2 and fabrik.aufrufe == 0


@pytest.mark.parametrize("abkuerzung", [("--ausf", "--bestaetigung", "LASTTEST"), ("--ausfuehren", "--best", "LASTTEST")])
def test_abgekuerzte_schalter_gelten_nie(tmp_path, clips, abkuerzung, capsys):
    fabrik = Fabrik(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(basis(tmp_path, clips, *abkuerzung), umgebung_bauen=fabrik)
    assert e.value.code == 2 and fabrik.aufrufe == 0


def test_kerndaten_behalten_steht_im_plan(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path))
    assert "Gesprächstexte im Kern ab Beginn des Laufs löschen" in capsys.readouterr().out
    cli.main(basis(tmp_path, clips, "--kerndaten-behalten"), umgebung_bauen=Fabrik(tmp_path))
    assert "BLEIBEN" in capsys.readouterr().out


def test_bestaetigung_allein_bleibt_ein_trockenlauf(tmp_path, clips, capsys):
    fabrik = Fabrik(tmp_path)
    assert cli.main(basis(tmp_path, clips, "--bestaetigung", "LASTTEST"), umgebung_bauen=fabrik) == 0
    assert fabrik.aufrufe == 0 and "Trockenlauf" in capsys.readouterr().out


def test_echtlauf_mit_beiden_schloessern_laeuft_und_schreibt_json_und_bericht(tmp_path, clips, capsys, monkeypatch):
    monkeypatch.setattr(cli.wl, "admin_passwort", lambda: "x")
    fabrik = Fabrik(tmp_path)
    code = cli.main(basis(tmp_path, clips, "--sitzungen", "1", "--minuten", "1", "--ausfuehren", "--bestaetigung", "LASTTEST"),
                    umgebung_bauen=fabrik, umschlag_oeffnen=lambda pfad: at.UmschlagAttrappe(), slot_ermitteln=SlotQuelle("b"))
    assert code in (0, 3) and fabrik.aufrufe == 1
    daten = json.loads((tmp_path / "aus" / "last-t.json").read_text(encoding="utf-8"))
    assert daten["lauf"] == "last-t" and daten["stufen"] and daten["ausfuehrung"] == "echt"
    bericht = (tmp_path / "aus" / "last-t.md").read_text(encoding="utf-8")
    assert "# Lasttest last-t" in bericht
    assert "Pw-labor" not in json.dumps(daten) + bericht
    assert "Ergebnis" in capsys.readouterr().out


def test_ohne_admin_anmeldung_startet_der_echtlauf_nicht(tmp_path, clips, capsys, monkeypatch):
    def fehlt():
        raise cli.wl.Fehler("WAMO_ADMIN_DATABASE_URL ist nicht gesetzt")
    monkeypatch.setattr(cli.wl, "admin_passwort", fehlt)
    fabrik = Fabrik(tmp_path)
    assert cli.main(basis(tmp_path, clips, "--ausfuehren", "--bestaetigung", "LASTTEST"), umgebung_bauen=fabrik) == 2
    assert fabrik.aufrufe == 0 and "WAMO_ADMIN_DATABASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize("zustand,code", [({"abbruchgrund": "429 im Journal des Kerns", "gesamt": "durchgefallen", "aufraeumen": [], "von_aussen": False}, 1),
                                          ({"abbruchgrund": "", "gesamt": "durchgefallen", "aufraeumen": [], "von_aussen": False}, 1),
                                          ({"abbruchgrund": "", "gesamt": "offen", "aufraeumen": [], "von_aussen": False}, 3),
                                          ({"abbruchgrund": "", "gesamt": "bestanden", "aufraeumen": [], "von_aussen": False}, 0),
                                          ({"abbruchgrund": "", "gesamt": "bestanden", "aufraeumen": [{"schritt": "x", "ok": False, "text": ""}], "von_aussen": False}, 1),
                                          ({"abbruchgrund": "Strg+C", "gesamt": "offen", "aufraeumen": [], "von_aussen": True}, 130)])
def test_ausgangscodes(zustand, code):
    assert cli.ausgangscode(zustand) == code


# ---------- Eingaben ----------

@pytest.mark.parametrize("zusatz", [("--sitzungen", "3"), ("--sitzungen", "9"), ("--minuten", "21"), ("--minuten", "0"), ("--murmeln", "99"),
                                    ("--lauf", "../x"), ("--freigabe", "immer"), ("--host", "-oProxyCommand=x"), ("--schema", "public"),
                                    ("--seed", "x"), ("--einwilligung", "0")])
def test_ungueltige_eingaben_enden_mit_2_und_ohne_traceback(tmp_path, clips, capsys, zusatz):
    args = basis(tmp_path, clips)
    if zusatz[0] == "--lauf":
        args = [a for a in args if a not in ("--lauf", "last-t")]
    try:
        code = cli.main([*args, *zusatz], umgebung_bauen=Fabrik(tmp_path))
    except SystemExit as e:  # argparse meldet falsche Typen selbst
        code = e.code
    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_ausgabe_und_umschlag_duerfen_nicht_im_repo_liegen(tmp_path, clips, capsys):
    args = basis(tmp_path, clips)
    args[args.index("--ausgabe-ordner") + 1] = str(WURZEL / "scripts" / "aus")
    assert cli.main(args, umgebung_bauen=Fabrik(tmp_path)) == 2
    assert "Repo" in capsys.readouterr().err
    args = basis(tmp_path, clips)
    args[args.index("--umschlag-datei") + 1] = str(WURZEL / "umschlag.txt")
    assert cli.main(args, umgebung_bauen=Fabrik(tmp_path)) == 2


def test_standardorte_liegen_im_heimordner(tmp_path, monkeypatch):
    args = cli._parser().parse_args(["lauf"])
    assert Path(args.clips_ordner).parts[-3:] == (".wamo-labor", "last", "clips") if args.clips_ordner else True
    ein_orte = cli.standardorte()
    assert ein_orte["umschlag"].name == "umschlag-labor.txt" and ".wamo-labor" in ein_orte["umschlag"].parts


def test_host_aus_der_umgebung_wird_geprueft(tmp_path, clips, monkeypatch, capsys):
    monkeypatch.setenv("WAMO_SSH_HOST", "-oProxyCommand=x")
    assert cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path)) == 2


# ---------- Clips ----------

def test_clips_erzeugt_nur_fehlende_mit_der_uebergebenen_stimme(tmp_path, capsys):
    ziel = tmp_path / "c"
    ziel.mkdir()
    au.schreibe_wav(ziel / "a1.wav", 8000, [0.0, 0.1])
    gesprochen = []

    def sprechen(text, datei):
        gesprochen.append(datei.name)
        au.schreibe_wav(datei, 8000, [0.0, 0.2])

    assert cli.main(["clips", "--clips-ordner", str(ziel)], sprechen=sprechen) == 0
    assert "a1.wav" not in gesprochen and len(gesprochen) == len(au.SPRECHPROBEN) - 1
    assert "11 neu erzeugt" in capsys.readouterr().out


def test_sprechen_windows_gibt_text_und_ziel_nur_ueber_die_umgebung(tmp_path, monkeypatch):
    gesehen = {}

    def run(cmd, **kw):
        gesehen["cmd"], gesehen["env"] = cmd, kw["env"]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    cli.sprechen_windows("Text mit 'Anführungszeichen'", tmp_path / "x.wav")
    assert "Anführungszeichen" not in " ".join(gesehen["cmd"]) and str(tmp_path) not in " ".join(gesehen["cmd"])
    assert gesehen["env"]["WAMO_SPRECH_TEXT"] == "Text mit 'Anführungszeichen'" and gesehen["env"]["WAMO_SPRECH_ZIEL"].endswith("x.wav")


def test_sprechen_windows_meldet_fehler_der_stimme(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Stimme nicht gefunden"))
    with pytest.raises(pl.EingabeFehler, match="Stimme"):
        cli.sprechen_windows("x", tmp_path / "x.wav")


# ---------- Ausgabe ----------

def test_ergebnis_wird_atomar_geschrieben_und_ueberschreibt_nur_den_eigenen_lauf(tmp_path):
    ziel = tmp_path / "aus"
    cli.ergebnis_schreiben(ziel, "last-a", {"lauf": "last-a", "stufen": [], "kriterien": [], "gesamt": "offen", "abbruchgrund": "", "ausfuehrung": "echt",
                                           "seed": 1, "schema": "s", "slot": "b", "beginn": "", "ende": "", "annahmen": {"eingabe_tokens_je_zug": 1,
                                           "ausgabe_tokens_je_zug": 1, "anfragen_je_zug": 1.0}, "kosten_schaetzung": {"zuege": 1, "eingabe_tokens": 1,
                                           "ausgabe_tokens": 1, "anfragen": 1.0, "usd": None}, "aufraeumen": []})
    assert sorted(p.name for p in ziel.iterdir()) == ["last-a.json", "last-a.md"]
    assert not list(ziel.glob(".*tmp*"))


# ---------- Kern-Slot (R8: ohne --slot misst der Lasttest den aktiven Slot, nicht fest b) ----------

def test_trockenlauf_fragt_den_slot_nicht_ab_und_nennt_den_weg(tmp_path, clips, capsys):
    quelle = SlotQuelle()
    assert cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path), slot_ermitteln=quelle) == 0
    out = capsys.readouterr().out
    assert quelle.aufrufe == []   # der Trockenlauf ruft nie den Server an
    assert "aktive Slot" in out and "im Echtlauf am Server ermittelt" in out and "--slot" in out
    assert "wamo-core@b" not in out


def test_trockenlauf_mit_slot_nennt_die_vorgabe(tmp_path, clips, capsys):
    assert cli.main(basis(tmp_path, clips, "--slot", "a"), umgebung_bauen=Fabrik(tmp_path), slot_ermitteln=SlotQuelle()) == 0
    out = capsys.readouterr().out
    assert "wamo-core@a" in out and "vorgegeben mit --slot" in out


def _echtlauf(tmp_path, clips, quelle, *zusatz):
    fabrik = Fabrik(tmp_path)
    code = cli.main(basis(tmp_path, clips, "--sitzungen", "1", "--minuten", "1", *zusatz, "--ausfuehren", "--bestaetigung", "LASTTEST"),
                    umgebung_bauen=fabrik, umschlag_oeffnen=lambda pfad: at.UmschlagAttrappe(), slot_ermitteln=quelle)
    return code, fabrik


def test_echtlauf_ohne_slot_misst_den_aktiven_slot_des_servers(tmp_path, clips, capsys, monkeypatch):
    monkeypatch.setattr(cli.wl, "admin_passwort", lambda: "x")
    quelle = SlotQuelle("a")
    code, fabrik = _echtlauf(tmp_path, clips, quelle)
    assert code in (0, 3) and quelle.aufrufe == ["wamo-sokrates2"] and fabrik.ein.slot == "a"
    assert json.loads((tmp_path / "aus" / "last-t.json").read_text(encoding="utf-8"))["slot"] == "a"
    out = capsys.readouterr().out
    assert "wamo-core@a" in out and "am Server ermittelt" in out


def test_echtlauf_mit_slot_uebersteuert_ohne_abfrage(tmp_path, clips, capsys, monkeypatch):
    monkeypatch.setattr(cli.wl, "admin_passwort", lambda: "x")
    quelle = SlotQuelle("a")
    code, fabrik = _echtlauf(tmp_path, clips, quelle, "--slot", "b")
    assert code in (0, 3) and quelle.aufrufe == [] and fabrik.ein.slot == "b"
    assert "vorgegeben mit --slot" in capsys.readouterr().out


@pytest.mark.parametrize("fehler", ["Beide Kern-Slots laufen (a und b aktiv)", "Kein Kern-Slot ist aktiv (a: inactive, b: inactive)"])
def test_echtlauf_ohne_eindeutigen_slot_startet_nicht(tmp_path, clips, capsys, monkeypatch, fehler):
    monkeypatch.setattr(cli.wl, "admin_passwort", lambda: "x")
    code, fabrik = _echtlauf(tmp_path, clips, SlotQuelle(fehler=fehler))
    assert code == 2 and fabrik.aufrufe == 0
    gesehen = capsys.readouterr()
    assert fehler in gesehen.err and "ECHTLAUF" not in gesehen.out   # vor dem Plan des Echtlaufs, nichts angefasst


@pytest.mark.parametrize("slot", ["c", "", "b;id"])
def test_unerwarteter_slot_vom_server_startet_nicht(tmp_path, clips, capsys, monkeypatch, slot):
    monkeypatch.setattr(cli.wl, "admin_passwort", lambda: "x")
    code, fabrik = _echtlauf(tmp_path, clips, SlotQuelle(slot))
    assert code == 2 and fabrik.aufrufe == 0 and "unerwartet" in capsys.readouterr().err


def test_trockenlauf_mit_den_echten_wegen_startet_keinen_prozess(tmp_path, clips, capsys):
    # die Falle aus keine_echten_aufrufe bricht ab, sobald ssh gestartet würde; hier gilt die echte Ermittlung als Standard
    assert cli.main(basis(tmp_path, clips)) == 0
    assert "der aktive Slot" in capsys.readouterr().out


def test_standard_der_ermittlung_ist_der_lesende_weg_des_servers():
    import inspect
    assert inspect.signature(cli.main).parameters["slot_ermitteln"].default is sv.aktiven_slot_ermitteln
    assert cli._parser().parse_args(["lauf"]).slot is None


# ---------- --erlaube-haus ----------

def test_der_plan_nennt_die_modellpruefung_und_den_schalter_zum_erlauben(tmp_path, clips, capsys):
    cli.main(basis(tmp_path, clips), umgebung_bauen=Fabrik(tmp_path))
    aus = capsys.readouterr().out
    assert "Modellprüfung: Gleich nach dem Start der ersten Gespräche" in aus and "einem Hausmodell statt Claude im Gespräch" in aus and "--erlaube-haus" in aus
    cli.main(basis(tmp_path, clips, "--erlaube-haus"), umgebung_bauen=Fabrik(tmp_path))
    aus = capsys.readouterr().out
    assert "Hausmodell ERLAUBT (--erlaube-haus)" in aus and "einem Hausmodell statt Claude im Gespräch" not in aus


def test_erlaube_haus_ist_ein_schalter_ohne_abkuerzung_und_gilt_nur_im_lauf(tmp_path, clips, capsys):
    args = cli._parser().parse_args(basis(tmp_path, clips, "--erlaube-haus"))
    assert args.erlaube_haus is True and cli.einstellungen_bauen(args).haus_erlauben is True
    assert cli.einstellungen_bauen(cli._parser().parse_args(basis(tmp_path, clips))).haus_erlauben is False
    with pytest.raises(SystemExit) as e:
        cli.main(basis(tmp_path, clips, "--erlaube"), umgebung_bauen=Fabrik(tmp_path))
    assert e.value.code == 2
