"""Tests für scripts/wamo_nutzer.py (Nutzer verwalten: anlegen, freischalten, zuruecksetzen, passwort, umbenennen, sperren, austreten, liste).

Aufruf (im Arbeitsbaum):  python -m pytest scripts/test_wamo_nutzer.py -q
Kein ssh, kein Server, keine Datenbank, kein GoTrue: der Weg zum Server (run_remote) wird durch eine Attrappe ersetzt, und das
Programm, das auf dem Server läuft (REMOTE), wird in-process mit exec in einem eigenen Namensraum ausgeführt. psql und der
Admin-Aufruf an GoTrue sind Parameter von verarbeite(); die Attrappen schreiben jeden Aufruf in ein gemeinsames Protokoll, sodass die
Reihenfolge der Schritte exakt geprüft werden kann.
"""
from __future__ import annotations

import base64
import builtins
import io
import json
import re
import subprocess
import sys
import types
import urllib.error
import urllib.request
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wamo_nutzer as wn  # noqa: E402

UID = "00000000-0000-4000-8000-0000000000a1"
NEUE_UID = "00000000-0000-4000-8000-0000000000a2"
FAKTOR_1 = "00000000-0000-4000-8000-0000000000f1"
FAKTOR_2 = "00000000-0000-4000-8000-0000000000f2"
EMAIL = "anna.beispiel@example.invalid"
PASSWORT = "Geheim-4711-Nie-Ausgeben"
FRIST_TEXT = "18.11.2026 14:05"


# ---------- Attrappen für das Programm auf dem Server ----------

class Wirf:
    """Antwort einer Attrappe, die einen Fehler des Serverprogramms auslöst."""

    def __init__(self, text: str):
        self.text = text


STANDARD_SQL = {
    "konto_suchen": UID,
    "labor_schemas": "wamo_dev\nwamo_test",
    "labor_zaehlen": "0",
    "profil_lesen": "normal|inaktiv|mitglied",
    "sitzungen_loeschen": "2",
    "refresh_zaehlen": "0",
    "einmalig_vorhanden": "true|true",
    "ott_loeschen": "0\n0",
    "flow_loeschen": "0\n0",
    "passwort_hash": ["hash-vorher", "hash-nachher"],
    "faktoren_liste": "",
    "faktoren_zaehlen": "0",
    "merker_anlegen": FRIST_TEXT,
    "profil_aktivieren": UID,
    "profil_deaktivieren": UID,
    "profil_umbenennen": UID,
    "profil_upsert": "inaktiv",
    "geraete_widerrufen": "pc-anna",
    "geraete_offen_zaehlen": "0",
    "zugang_loeschen": UID,
    "zugang_zaehlen": "0",
    "stand_vorhanden": "t",
    "offene_liste": f"{UID}|{EMAIL}",
    "liste_mit_stand": f"Anna | mitglied | aktiv | {EMAIL} | offen | {FRIST_TEXT} | 1 | Konto frei",
    "liste_ohne_stand": f"Anna | mitglied | aktiv | {EMAIL} | - | - | 0 | Konto frei",
}

STANDARD_GOTRUE = {
    "anlegen": {"id": NEUE_UID},
    "sperren": {"id": UID, "banned_until": "2126-01-01T00:00:00Z"},
    "entsperren": {"id": UID},
    "passwort": {"id": UID},
    "faktor_loeschen": {},
}


def gotrue_art(methode: str, pfad: str, daten: dict | None) -> str:
    if methode == "POST" and pfad == "/admin/users":
        return "anlegen"
    if methode == "DELETE" and "/factors/" in pfad:
        return "faktor_loeschen"
    if methode == "PUT" and daten:
        if "password" in daten:
            return "passwort"
        if daten.get("ban_duration") == "none":
            return "entsperren"
        if "ban_duration" in daten:
            return "sperren"
    raise AssertionError(f"unerwarteter GoTrue-Aufruf: {methode} {pfad} {daten}")


def remote_namensraum() -> dict:
    ns: dict = {"__name__": "remote_test"}  # nicht "__main__": der Rumpf ruft main() nur als Programm auf
    exec(compile(wn.REMOTE, "<remote>", "exec"), ns)  # noqa: S102 (das ist das Programm, das auf dem Server läuft)
    return ns


class Welt:
    """psql und GoTrue als Attrappen mit gemeinsamem Protokoll (Einträge wie sql:konto_suchen und gotrue:sperren)."""

    def __init__(self, fehler_bei: int | None = None, **sql_antworten):
        self.ns = remote_namensraum()
        self.Fehler = self.ns["Fehler"]
        self.log: list[str] = []
        self.sql: list[tuple[str, dict, str]] = []
        self.gotrue: list[tuple[str, str, str, dict | None]] = []
        self.gedruckt: list[str] = []
        self.protokoll: list[str] = []
        self.fehler_bei = fehler_bei
        antworten = {**STANDARD_SQL, **sql_antworten}
        self.sql_antworten = {k: (list(v) if isinstance(v, list) else v) for k, v in antworten.items()}
        self.gotrue_antworten = dict(STANDARD_GOTRUE)

    def _eintrag(self, text: str):
        self.log.append(text)
        if self.fehler_bei is not None and len(self.log) - 1 == self.fehler_bei:
            raise self.Fehler("simulierter Fehler")

    def psql(self, sql: str, **vars):
        name = next(n for n, s in self.ns["SQL"].items() if s == sql)
        self.sql.append((name, dict(vars), sql))
        self._eintrag("sql:" + name)
        antwort = self.sql_antworten[name]
        if isinstance(antwort, list):
            antwort = antwort.pop(0) if len(antwort) > 1 else antwort[0]
        if isinstance(antwort, Wirf):
            raise self.Fehler(antwort.text)
        return antwort

    def gotrue_aufruf(self, methode: str, pfad: str, daten: dict | None = None):
        art = gotrue_art(methode, pfad, daten)
        self.gotrue.append((art, methode, pfad, daten))
        self._eintrag("gotrue:" + art)
        antwort = self.gotrue_antworten[art]
        if isinstance(antwort, list):
            antwort = antwort.pop(0) if len(antwort) > 1 else antwort[0]
        if isinstance(antwort, Wirf):
            raise self.Fehler(antwort.text)
        return antwort

    def lauf(self, d: dict) -> tuple[int, str, str]:
        echtes_print = builtins.print

        def spion(*args, **kwargs):
            self.gedruckt.append(" ".join(str(a) for a in args))
            echtes_print(*args, **kwargs)

        self.ns["print"] = spion
        aus, fehl = io.StringIO(), io.StringIO()
        with redirect_stdout(aus), redirect_stderr(fehl):
            code = self.ns["verarbeite"](d, self.psql, self.gotrue_aufruf, self.protokoll.append)
        return code, aus.getvalue(), fehl.getvalue()

    def sql_von(self, name: str) -> list[tuple[dict, str]]:
        return [(v, s) for n, v, s in self.sql if n == name]


def auftrag(aktion: str, **extra) -> dict:
    d = {"aktion": aktion, "schema": "wamo_dev", "email": EMAIL}
    if aktion in ("freischalten", "zuruecksetzen", "passwort"):
        d["password"] = PASSWORT
    if aktion in ("freischalten", "zuruecksetzen"):
        d["frist"] = 72
    d.update(extra)
    return d


PRUEFEN = ["sql:konto_suchen", "sql:labor_schemas", "sql:labor_zaehlen", "sql:labor_zaehlen", "sql:profil_lesen"]
SITZUNGEN = ["sql:sitzungen_loeschen", "sql:refresh_zaehlen", "sql:einmalig_vorhanden", "sql:ott_loeschen", "sql:flow_loeschen"]
FAKTOR_LOESCHEN = ["gotrue:faktor_loeschen", "gotrue:faktor_loeschen", "sql:faktoren_zaehlen"]
# Nach der Sperre sofort ein vorläufiger Merker (M2), das Passwort wird mit Hash vorher und nachher geprüft (M3)
FOLGE_UEBERGABE = (PRUEFEN + ["gotrue:sperren", "sql:merker_anlegen"] + SITZUNGEN + ["sql:faktoren_liste"]
                   + ["sql:passwort_hash", "gotrue:passwort", "sql:passwort_hash"]
                   + ["sql:merker_anlegen", "sql:profil_aktivieren", "gotrue:entsperren"])
FOLGE_UEBERGABE_MIT_FAKTOREN = (PRUEFEN + ["gotrue:sperren", "sql:merker_anlegen"] + SITZUNGEN + ["sql:faktoren_liste"] + FAKTOR_LOESCHEN
                                + ["sql:passwort_hash", "gotrue:passwort", "sql:passwort_hash"]
                                + ["sql:merker_anlegen", "sql:profil_aktivieren", "gotrue:entsperren"])
FAKTOREN_ANTWORT = f"{FAKTOR_1}\n{FAKTOR_2}"


# ---------- freischalten: feste Reihenfolge, jeder Schritt geprüft ----------

def test_freischalten_reihenfolge_exakt():
    welt = Welt()
    code, aus, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 0, fehl
    assert welt.log == FOLGE_UEBERGABE
    # Sperre, dann sofort der vorläufige Merker, dann Sitzungen; endgültiger Merker erst nach dem Passwort; Entsperren zuletzt
    erster_merker = welt.log.index("sql:merker_anlegen")
    letzter_merker = len(welt.log) - 1 - welt.log[::-1].index("sql:merker_anlegen")
    assert welt.log.index("gotrue:sperren") + 1 == erster_merker < welt.log.index("sql:sitzungen_loeschen")
    assert welt.log.index("sql:sitzungen_loeschen") < welt.log.index("gotrue:passwort") < letzter_merker < welt.log.index("sql:profil_aktivieren")
    assert welt.log[-1] == "gotrue:entsperren" and welt.log.count("sql:merker_anlegen") == 2
    assert FRIST_TEXT in aus and "Willkommensblatt" in aus


def test_freischalten_sendet_die_richtigen_daten_an_gotrue():
    welt = Welt()
    welt.lauf(auftrag("freischalten"))
    sperre, passwort, entsperre = [(m, p, d) for a, m, p, d in welt.gotrue if a in ("sperren", "passwort", "entsperren")]
    assert sperre == ("PUT", f"/admin/users/{UID}", {"ban_duration": "876000h"})
    assert passwort == ("PUT", f"/admin/users/{UID}", {"password": PASSWORT})
    assert entsperre == ("PUT", f"/admin/users/{UID}", {"ban_duration": "none"})


def test_freischalten_schreibt_den_merker_zweimal_ohne_erledigt_und_mit_frist():
    welt = Welt()
    welt.lauf(auftrag("freischalten", frist=24))
    vorlaeufig, endgueltig = welt.sql_von("merker_anlegen")
    assert "wamo_auth.erstanmeldung_anlegen" in vorlaeufig[1]
    erwartet = {"uid": UID, "frist": "24", "durch": "freischalten", "erledigt": "false"}
    assert vorlaeufig[0] == erwartet and endgueltig[0] == erwartet


def test_freischalten_mit_faktoren_loeschen_entfernt_jeden_faktor_und_zaehlt_danach():
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT)
    code, _, fehl = welt.lauf(auftrag("freischalten", faktoren_loeschen=True))
    assert code == 0, fehl
    assert welt.log == FOLGE_UEBERGABE_MIT_FAKTOREN
    pfade = [p for a, m, p, d in welt.gotrue if a == "faktor_loeschen"]
    assert pfade == [f"/admin/users/{UID}/factors/{FAKTOR_1}", f"/admin/users/{UID}/factors/{FAKTOR_2}"]


def test_freischalten_bricht_bei_vorhandenen_faktoren_ohne_schalter_ab():
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT)
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1
    assert "fremde Einrichtung" in fehl and "Schritt 3" in fehl
    for verboten in ("gotrue:passwort", "sql:profil_aktivieren", "gotrue:entsperren", "gotrue:faktor_loeschen"):
        assert verboten not in welt.log
    assert welt.log.count("sql:merker_anlegen") == 1, "nur der vorläufige Merker, der endgültige entsteht erst nach dem Passwort"
    assert welt.log[-1] == "sql:faktoren_liste" and "gesperrt" in fehl


def test_freischalten_bricht_ab_wenn_nach_dem_loeschen_faktoren_uebrig_sind():
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT, faktoren_zaehlen="1")
    code, _, fehl = welt.lauf(auftrag("freischalten", faktoren_loeschen=True))
    assert code == 1 and "Schritt 3" in fehl
    assert "gotrue:passwort" not in welt.log and "gotrue:entsperren" not in welt.log


def test_freischalten_bricht_ab_wenn_noch_refresh_tokens_gueltig_sind():
    welt = Welt(refresh_zaehlen="2")
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Schritt 2" in fehl
    assert welt.log[-1] == "sql:refresh_zaehlen"


def test_freischalten_bricht_ab_wenn_gotrue_die_sperre_nicht_bestaetigt():
    welt = Welt()
    welt.gotrue_antworten["sperren"] = {"id": UID}  # kein banned_until
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Schritt 1" in fehl and "banned_until" in fehl
    assert welt.log == FOLGE_UEBERGABE[:len(PRUEFEN) + 1], "nach der unbestätigten Sperre kein weiterer Schritt"


@pytest.mark.parametrize("aktion,faktoren,folge", [
    ("freischalten", False, FOLGE_UEBERGABE),
    ("freischalten", True, FOLGE_UEBERGABE_MIT_FAKTOREN),
    ("zuruecksetzen", False, FOLGE_UEBERGABE_MIT_FAKTOREN),
    ("passwort", False, FOLGE_UEBERGABE),
    ("passwort", True, FOLGE_UEBERGABE_MIT_FAKTOREN),
])
def test_ein_fehler_an_jeder_stelle_bricht_sofort_ab_und_entsperrt_nie(aktion, faktoren, folge):
    """Bei JEDEM Fehler vor dem letzten Schritt: Abbruch, kein weiterer Aufruf, nie die Sperre aufheben."""
    for k in range(len(folge) - 1):
        antworten = {"faktoren_liste": FAKTOREN_ANTWORT} if "gotrue:faktor_loeschen" in folge else {}
        welt = Welt(fehler_bei=k, **antworten)
        code, _, fehl = welt.lauf(auftrag(aktion, faktoren_loeschen=faktoren))
        assert code == 1, (aktion, k)
        assert welt.log == folge[:k + 1], (aktion, k)
        assert "gotrue:entsperren" not in welt.log, (aktion, k)
        assert "simulierter Fehler" in fehl


@pytest.mark.parametrize("quelle,name,antwort,schritt", [
    ("gotrue", "passwort", Wirf("GoTrue PUT: HTTP 422 weak_password"), "Schritt 4"),
    ("sql", "merker_anlegen", Wirf("Datenbankfehler: Konto fehlt"), "Schritt 1b"),          # vorläufiger Merker
    ("sql", "merker_anlegen", "", "Schritt 1b"),
    ("sql", "merker_anlegen", [FRIST_TEXT, Wirf("Datenbankfehler: Konto fehlt")], "Schritt 5"),  # endgültiger Merker
    ("sql", "merker_anlegen", [FRIST_TEXT, ""], "Schritt 5"),
    ("sql", "profil_aktivieren", Wirf("Datenbankfehler: profiles: aktivieren nur mit Erstanmeldung"), "Schritt 6"),
    ("sql", "profil_aktivieren", "", "Schritt 6"),
])
def test_fehler_in_schritt_4_5_oder_6_fuehrt_nie_zum_entsperren(quelle, name, antwort, schritt):
    welt = Welt()
    if quelle == "gotrue":
        welt.gotrue_antworten[name] = antwort
    else:
        welt.sql_antworten[name] = antwort
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and schritt in fehl
    assert "gotrue:entsperren" not in welt.log
    assert "Konto bleibt gesperrt" in fehl


def test_ein_fehler_beim_entsperren_wird_laut_gemeldet():
    welt = Welt()
    welt.gotrue_antworten["entsperren"] = {"id": UID, "banned_until": "2126-01-01T00:00:00Z"}
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Schritt 7" in fehl and "liste" in fehl


def test_freischalten_lehnt_ein_zu_kurzes_passwort_ab_bevor_etwas_passiert():
    for passwort in ("", "kurz", "x" * 11, None, "y" * 73):
        welt = Welt()
        d = auftrag("freischalten")
        d["password"] = passwort
        code, _, _ = welt.lauf(d)
        assert code == 1 and welt.log == [], passwort


def test_freischalten_ohne_konto_aendert_nichts():
    welt = Welt(konto_suchen="")
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Kein Konto" in fehl and welt.log == ["sql:konto_suchen"]


def test_freischalten_ohne_profil_im_schema_aendert_nichts():
    welt = Welt(profil_lesen="")
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Profil" in fehl and welt.log == PRUEFEN


def test_rolle_ist_beim_freischalten_egal():
    for rolle in ("admin", "mitglied"):
        welt = Welt(profil_lesen=f"normal|inaktiv|{rolle}")
        code, _, fehl = welt.lauf(auftrag("freischalten"))
        assert code == 0, fehl


# ---------- zuruecksetzen und passwort ----------

def test_zuruecksetzen_loescht_faktoren_immer():
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT)
    code, _, fehl = welt.lauf(auftrag("zuruecksetzen"))  # ohne faktoren_loeschen
    assert code == 0, fehl
    assert welt.log == FOLGE_UEBERGABE_MIT_FAKTOREN
    for vars_, _ in welt.sql_von("merker_anlegen"):
        assert vars_["durch"] == "zuruecksetzen" and vars_["erledigt"] == "false"


def test_zuruecksetzen_ohne_faktoren_laeuft_ohne_loeschen():
    welt = Welt()
    code, _, fehl = welt.lauf(auftrag("zuruecksetzen"))
    assert code == 0, fehl
    assert welt.log == FOLGE_UEBERGABE


def test_passwort_schreibt_den_endgueltigen_merker_mit_erledigt_den_vorlaeufigen_ohne():
    welt = Welt()
    code, aus, fehl = welt.lauf(auftrag("passwort"))
    assert code == 0, fehl
    assert welt.log == FOLGE_UEBERGABE
    vorlaeufig, endgueltig = welt.sql_von("merker_anlegen")
    assert vorlaeufig[0]["durch"] == "passwort" and vorlaeufig[0]["erledigt"] == "false"
    assert endgueltig[0]["durch"] == "passwort" and endgueltig[0]["erledigt"] == "true"
    assert "erstanmeldung_anlegen" in endgueltig[1]
    assert PASSWORT not in aus


def test_passwort_bricht_bei_vorhandenen_faktoren_ohne_schalter_ab():
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT)
    code, _, fehl = welt.lauf(auftrag("passwort"))
    assert code == 1 and "fremde Einrichtung" in fehl
    assert "gotrue:passwort" not in welt.log and "gotrue:entsperren" not in welt.log


# ---------- Laborprofile werden nie angefasst ----------

@pytest.mark.parametrize("aktion,extra", [
    ("freischalten", {}), ("zuruecksetzen", {}), ("passwort", {}), ("austreten", {}),
    ("umbenennen", {"name": "Anna"}), ("sperren", {}),
])
def test_laborprofil_wird_abgelehnt(aktion, extra):
    welt = Welt(profil_lesen="labor|inaktiv|mitglied")
    code, _, fehl = welt.lauf(auftrag(aktion, **extra))
    assert code == 1 and "Laborprofil" in fehl
    assert welt.log == PRUEFEN, "kein einziger ändernder Aufruf"


def test_anlegen_lehnt_ein_vorhandenes_laborprofil_ab():
    welt = Welt(profil_upsert="")  # der Upsert trifft wegen labor_art is null keine Zeile
    code, _, fehl = welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
    assert code == 1 and "Laborprofil" in fehl


def test_alle_aendernden_profil_sql_schliessen_laborprofile_aus():
    sql = remote_namensraum()["SQL"]
    for name in ("profil_aktivieren", "profil_deaktivieren", "profil_umbenennen", "profil_upsert"):
        assert "labor_art is null" in sql[name], name


def test_nur_profil_aktivieren_setzt_aktiv_auf_true():
    sql = remote_namensraum()["SQL"]
    setzt_true = [n for n, s in sql.items() if re.search(r"aktiv\s*=\s*true", s)]
    assert setzt_true == ["profil_aktivieren"]


# ---------- anlegen ----------

def test_anlegen_neues_konto_ist_gesperrt_und_das_profil_inaktiv():
    welt = Welt(konto_suchen="")
    code, aus, fehl = welt.lauf(auftrag("anlegen", name="Anna Beispiel", rolle="mitglied", anrede="du"))
    assert code == 0, fehl
    assert welt.log == ["sql:konto_suchen", "gotrue:anlegen", "gotrue:sperren", "sql:profil_upsert"]
    anlegen = next(g for g in welt.gotrue if g[0] == "anlegen")
    daten = anlegen[3]
    assert daten["email"] == EMAIL and daten["email_confirm"] is True
    assert len(daten["password"]) >= 24 and daten["password"] != PASSWORT, "Zufallspasswort, nicht vom Aufrufer"
    sperre = next(g for g in welt.gotrue if g[0] == "sperren")
    assert sperre[2:] == (f"/admin/users/{NEUE_UID}", {"ban_duration": "876000h"})
    (vars_, sql), = welt.sql_von("profil_upsert")
    assert vars_["uid"] == NEUE_UID and vars_["name"] == "Anna Beispiel"
    assert re.search(r"values\s*\([^)]*,\s*false\s*\)", sql), "Profil wird inaktiv eingefügt"
    assert daten["password"] not in aus and daten["password"] not in fehl and daten["password"] not in " ".join(welt.gedruckt)
    assert "freischalten" in aus and EMAIL in aus


def test_anlegen_zufallspasswort_ist_bei_jedem_lauf_ein_anderes():
    passwoerter = set()
    for _ in range(5):
        welt = Welt(konto_suchen="")
        welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
        passwoerter.add(next(g for g in welt.gotrue if g[0] == "anlegen")[3]["password"])
    assert len(passwoerter) == 5


def test_anlegen_bricht_ab_wenn_gotrue_die_sperre_nicht_bestaetigt():
    welt = Welt(konto_suchen="")
    welt.gotrue_antworten["sperren"] = {"id": NEUE_UID}  # kein banned_until
    code, aus, fehl = welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
    assert code == 1 and "banned_until" in fehl
    assert "sql:profil_upsert" not in welt.log, "kein Profil ohne bestätigte Sperre"
    kennwort = next(g for g in welt.gotrue if g[0] == "anlegen")[3]["password"]
    assert kennwort not in aus + fehl


def test_anlegen_vorhandenes_konto_setzt_aktiv_nie_und_aendert_weder_passwort_noch_sperre():
    welt = Welt(profil_upsert="aktiv")  # das Profil war schon aktiv und bleibt es
    code, aus, fehl = welt.lauf(auftrag("anlegen", name="Anna", rolle="admin", anrede="sie"))
    assert code == 0, fehl
    assert welt.log == PRUEFEN[:4] + ["sql:profil_upsert"], "nur die Laborprüfung, kein GoTrue-Aufruf bei vorhandenem Konto"
    (vars_, sql), = welt.sql_von("profil_upsert")
    nur_update = sql.split("do update set", 1)[1].split("returning", 1)[0]
    assert "aktiv" not in nur_update, "der Upsert ändert aktiv nie"
    assert (vars_["name"], vars_["rolle"], vars_["anrede"], vars_["uid"]) == ("Anna", "admin", "sie", UID)
    assert "unverändert" in aus


def test_anlegen_ungueltige_eingaben_werden_vor_dem_ersten_aufruf_abgelehnt():
    for extra in ({"rolle": "root"}, {"anrede": "ihr"}, {"name": ""}, {"name": "x" * 61}, {"name": "Ann\na"}, {"email": "kein-at"}):
        welt = Welt()
        d = auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du")
        d.update(extra)
        code, _, _ = welt.lauf(d)
        assert code == 1 and welt.log == [], extra


# ---------- umbenennen ----------

def test_umbenennen_aendert_nur_den_namen_und_aktiv_nie():
    welt = Welt()
    code, aus, fehl = welt.lauf(auftrag("umbenennen", name="Anna Maria Beispiel"))
    assert code == 0, fehl
    assert welt.log == PRUEFEN + ["sql:profil_umbenennen"]
    (vars_, sql), = welt.sql_von("profil_umbenennen")
    assert "aktiv" not in sql and "rolle" not in sql
    assert vars_["name"] == "Anna Maria Beispiel" and vars_["uid"] == UID
    assert welt.gotrue == []


def test_umbenennen_verlangt_einen_namen_von_1_bis_60_zeichen():
    for name in ("", "   ", "x" * 61):
        welt = Welt()
        code, _, _ = welt.lauf(auftrag("umbenennen", name=name))
        assert code == 1 and welt.log == [], name
    welt = Welt()
    assert welt.lauf(auftrag("umbenennen", name="x" * 60))[0] == 0


# ---------- sperren ----------

FOLGE_SPERREN_EINER = PRUEFEN + ["sql:profil_deaktivieren", "gotrue:sperren"] + SITZUNGEN


def test_sperren_mit_email_sperrt_profil_konto_und_sitzungen():
    welt = Welt(profil_lesen="normal|aktiv|mitglied")
    code, aus, fehl = welt.lauf(auftrag("sperren"))
    assert code == 0, fehl
    assert welt.log == FOLGE_SPERREN_EINER
    (_, sql), = welt.sql_von("profil_deaktivieren")
    assert re.search(r"aktiv\s*=\s*false", sql) and "labor_art is null" in sql
    assert "gotrue:entsperren" not in welt.log
    assert "gesperrt" in aus


def test_sperren_ohne_konto_bricht_ab():
    welt = Welt(konto_suchen="")
    code, _, fehl = welt.lauf(auftrag("sperren"))
    assert code == 1 and "Kein Konto" in fehl


ZWEITE_UID = "00000000-0000-4000-8000-0000000000b2"
ZWEITE_EMAIL = "zweite@example.invalid"
OFFENE_AUFTRAG = {"aktion": "sperren", "schema": "wamo_prod", "offene": True}
JE_KONTO = ["sql:labor_zaehlen", "sql:labor_zaehlen", "sql:profil_deaktivieren", "gotrue:sperren"] + SITZUNGEN


def test_sperren_offene_sperrt_nur_offene_oder_abgelaufene_nichtlaborprofile():
    welt = Welt(offene_liste=f"{UID}|{EMAIL}\n{ZWEITE_UID}|{ZWEITE_EMAIL}")
    code, aus, fehl = welt.lauf(OFFENE_AUFTRAG)
    assert code == 0, fehl
    assert welt.log == ["sql:stand_vorhanden", "sql:offene_liste", "sql:labor_schemas"] + JE_KONTO + JE_KONTO
    (_, sql), = welt.sql_von("offene_liste")
    assert "labor_art is null" in sql and "erstanmeldung_stand" in sql
    assert "'offen'" in sql and "'abgelaufen'" in sql and "'erledigt'" not in sql
    ziele = [p for a, m, p, d in welt.gotrue if a == "sperren"]
    assert ziele == [f"/admin/users/{UID}", f"/admin/users/{ZWEITE_UID}"]
    assert EMAIL in aus and ZWEITE_EMAIL in aus
    assert [v["uid"] for v, _ in welt.sql_von("profil_deaktivieren")] == [UID, ZWEITE_UID]
    assert all(v["schema"] == "wamo_prod" for v, _ in welt.sql_von("profil_deaktivieren"))


def test_sperren_offene_ohne_treffer_aendert_nichts():
    welt = Welt(offene_liste="")
    code, aus, _ = welt.lauf({"aktion": "sperren", "schema": "wamo_dev", "offene": True})
    assert code == 0 and welt.log == ["sql:stand_vorhanden", "sql:offene_liste"] and "Keine" in aus


def test_sperren_offene_braucht_die_funktion_erstanmeldung_stand():
    welt = Welt(stand_vorhanden="f")
    code, _, fehl = welt.lauf({"aktion": "sperren", "schema": "wamo_dev", "offene": True})
    assert code == 1 and "erstanmeldung_stand" in fehl and welt.log == ["sql:stand_vorhanden"]


def test_sperren_offene_sammelt_fehler_je_konto_macht_weiter_und_nennt_die_gescheiterten():
    """M1: Ein Fehler bei einem Konto lässt die übrigen nicht ungesperrt."""
    welt = Welt(offene_liste=f"{UID}|{EMAIL}\n{ZWEITE_UID}|{ZWEITE_EMAIL}")
    welt.gotrue_antworten["sperren"] = [Wirf("GoTrue PUT: HTTP 500 unerwartet"), {"id": ZWEITE_UID, "banned_until": "2126-01-01T00:00:00Z"}]
    code, aus, fehl = welt.lauf(OFFENE_AUFTRAG)
    assert code == 1
    assert welt.log.count("gotrue:sperren") == 2, "das zweite Konto wird trotzdem gesperrt"
    assert [v["uid"] for v, _ in welt.sql_von("profil_deaktivieren")] == [UID, ZWEITE_UID]
    assert EMAIL in fehl and ZWEITE_EMAIL not in fehl and "HTTP 500" in fehl and "Schritt 2" in fehl
    assert ZWEITE_EMAIL in aus and "Gesperrt" in aus


def test_sperren_offene_meldet_alle_gescheiterten_konten():
    welt = Welt(offene_liste=f"{UID}|{EMAIL}\n{ZWEITE_UID}|{ZWEITE_EMAIL}", refresh_zaehlen="1")
    code, _, fehl = welt.lauf(OFFENE_AUFTRAG)
    assert code == 1 and EMAIL in fehl and ZWEITE_EMAIL in fehl
    assert welt.log.count("gotrue:sperren") == 2


def test_sperren_offene_fasst_ein_konto_mit_laborprofil_in_einem_anderen_schema_nicht_an():
    welt = Welt(offene_liste=f"{UID}|{EMAIL}\n{ZWEITE_UID}|{ZWEITE_EMAIL}", labor_zaehlen=["0", "1", "0", "0"])
    code, aus, fehl = welt.lauf(OFFENE_AUFTRAG)
    assert code == 1 and EMAIL in fehl and "Laborprofil" in fehl
    assert [v["uid"] for v, _ in welt.sql_von("profil_deaktivieren")] == [ZWEITE_UID], "das Laborkonto bleibt unangetastet"
    assert [p for a, m, p, d in welt.gotrue if a == "sperren"] == [f"/admin/users/{ZWEITE_UID}"]
    assert ZWEITE_EMAIL in aus


def test_sperren_offene_lehnt_ein_laborkonto_nach_der_adresse_ab():
    welt = Welt(offene_liste=f"{UID}|labor-03@wamo.test")
    code, _, fehl = welt.lauf(OFFENE_AUFTRAG)
    assert code == 1 and "labor-03@wamo.test" in fehl and "Laborkonto" in fehl
    assert "sql:profil_deaktivieren" not in welt.log and "gotrue:sperren" not in welt.log


# ---------- austreten ----------

# zuerst abriegeln (Profil inaktiv, Sperre, Sitzungen), erst dann Faktoren, Geräte und Schlüssel
FOLGE_AUSTRETEN = (PRUEFEN + ["sql:profil_deaktivieren", "gotrue:sperren"] + SITZUNGEN
                   + ["sql:faktoren_liste"] + FAKTOR_LOESCHEN
                   + ["sql:geraete_widerrufen", "sql:geraete_offen_zaehlen", "sql:zugang_loeschen", "sql:zugang_zaehlen"])


def test_austreten_sperrt_loescht_widerruft_und_fasst_zusammen():
    welt = Welt(profil_lesen="normal|aktiv|mitglied", faktoren_liste=FAKTOREN_ANTWORT)
    code, aus, fehl = welt.lauf(auftrag("austreten"))
    assert code == 0, fehl
    assert welt.log == FOLGE_AUSTRETEN
    assert "gotrue:entsperren" not in welt.log and "gotrue:passwort" not in welt.log
    # das Profil ist vor dem Widerruf inaktiv (sonst verlangt der Gerätewächter einen Admin als Akteur)
    assert welt.log.index("sql:profil_deaktivieren") < welt.log.index("sql:geraete_widerrufen")
    (vars_, sql), = welt.sql_von("geraete_widerrufen")
    assert "'widerrufen'" in sql and "art = 'persoenlich'" in sql and "user_id = :'uid'" in sql
    assert vars_["uid"] == UID and vars_["schema"] == "wamo_dev"
    (_, zugang), = welt.sql_von("zugang_loeschen")
    assert "claude_schluessel = null" in zugang and "claude_code_token = null" in zugang and "model_access" in zugang
    for erwartet in (EMAIL, "pc-anna", "Sitzungen", "Faktoren", "Claude"):
        assert erwartet in aus, erwartet


def test_austreten_ohne_faktoren_und_geraete_laeuft_durch():
    welt = Welt(geraete_widerrufen="", zugang_loeschen="")
    code, aus, fehl = welt.lauf(auftrag("austreten"))
    assert code == 0, fehl
    assert "gotrue:faktor_loeschen" not in welt.log


@pytest.mark.parametrize("name,antwort,schritt", [
    ("geraete_offen_zaehlen", "1", "Geräte"),
    ("zugang_zaehlen", "1", "Schlüssel"),
    ("refresh_zaehlen", "3", "Schritt 3"),
])
def test_austreten_bricht_laut_ab_wenn_eine_pruefung_fehlschlaegt(name, antwort, schritt):
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT, **{name: antwort})
    code, _, fehl = welt.lauf(auftrag("austreten"))
    assert code == 1 and schritt in fehl


def test_austreten_ein_fehler_stoppt_alle_weiteren_schritte():
    for k in range(len(FOLGE_AUSTRETEN) - 1):
        welt = Welt(fehler_bei=k, faktoren_liste=FAKTOREN_ANTWORT)
        code, _, _ = welt.lauf(auftrag("austreten"))
        assert code == 1 and welt.log == FOLGE_AUSTRETEN[:k + 1], k


# ---------- liste ----------

def test_liste_zeigt_stand_frist_und_sperre_wenn_die_funktion_existiert():
    welt = Welt()
    code, aus, fehl = welt.lauf({"aktion": "liste", "schema": "wamo_dev"})
    assert code == 0, fehl
    assert welt.log == ["sql:stand_vorhanden", "sql:liste_mit_stand"]
    (_, sql), = welt.sql_von("liste_mit_stand")
    assert "wamo_auth.erstanmeldung_stand" in sql and "frist_bis" in sql and "banned_until > now()" in sql
    assert "auth.mfa_factors" in sql and "'verified'" in sql, "Anzahl der bestätigten Faktoren"
    assert "offen" in aus and FRIST_TEXT in aus and "Konto frei" in aus and "Faktoren" in aus


def test_liste_ohne_funktion_zeigt_einen_strich_statt_des_standes():
    welt = Welt(stand_vorhanden="f")
    code, aus, _ = welt.lauf({"aktion": "liste", "schema": "wamo_dev"})
    assert code == 0 and welt.log == ["sql:stand_vorhanden", "sql:liste_ohne_stand"]
    (_, sql), = welt.sql_von("liste_ohne_stand")
    assert "wamo_auth" not in sql and "banned_until > now()" in sql
    assert "auth.mfa_factors" in sql and "'verified'" in sql
    assert "| - | - |" in aus


def test_stand_vorhanden_prueft_die_funktion_mit_to_regprocedure():
    sql = remote_namensraum()["SQL"]["stand_vorhanden"]
    assert "to_regprocedure('wamo_auth.erstanmeldung_stand(uuid)')" in sql


def test_liste_ohne_profile():
    welt = Welt(liste_mit_stand="")
    code, aus, _ = welt.lauf({"aktion": "liste", "schema": "wamo_dev"})
    assert code == 0 and "Keine Profile" in aus


# ---------- M2: vorläufiger Merker nach der Sperre ----------

@pytest.mark.parametrize("aktion", ["freischalten", "zuruecksetzen", "passwort"])
def test_direkt_nach_der_sperre_steht_ein_vorlaeufiger_merker_vor_allem_anderen(aktion):
    """Alte Access-Tokens erreichen am Kern dann sofort nur noch die Erstanmeldung (Stand offen)."""
    welt = Welt(faktoren_liste=FAKTOREN_ANTWORT if aktion == "zuruecksetzen" else "")
    welt.lauf(auftrag(aktion))
    i = welt.log.index("gotrue:sperren")
    assert welt.log[i + 1] == "sql:merker_anlegen", "der vorläufige Merker folgt der Sperre unmittelbar"
    assert welt.log[i + 2] == "sql:sitzungen_loeschen"
    erster, _ = welt.sql_von("merker_anlegen")[0]
    assert erster["erledigt"] == "false" and erster["durch"] == aktion and erster["frist"] == "72"


@pytest.mark.parametrize("aktion", ["freischalten", "passwort"])
def test_scheitert_ein_spaeterer_schritt_bleibt_der_vorlaeufige_merker_und_das_konto_gesperrt(aktion):
    welt = Welt()
    welt.gotrue_antworten["passwort"] = Wirf("GoTrue PUT: HTTP 500 unerwartet")
    code, _, _ = welt.lauf(auftrag(aktion))
    assert code == 1 and welt.log.count("sql:merker_anlegen") == 1
    assert "gotrue:entsperren" not in welt.log and "sql:profil_aktivieren" not in welt.log


def test_der_vorlaeufige_merker_ist_nie_erledigt_auch_nicht_bei_passwort():
    welt = Welt()
    welt.lauf(auftrag("passwort"))
    assert [v["erledigt"] for v, _ in welt.sql_von("merker_anlegen")] == ["false", "true"]


# ---------- M3: Passwortwechsel prüfen ----------

def test_das_passwort_wird_mit_dem_hash_vor_und_nach_dem_setzen_geprueft():
    welt = Welt()
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 0, fehl
    i = welt.log.index("gotrue:passwort")
    assert welt.log[i - 1] == "sql:passwort_hash" and welt.log[i + 1] == "sql:passwort_hash"
    _, sql = welt.sql_von("passwort_hash")[0]
    assert "md5(encrypted_password)" in sql and "auth.users" in sql and "id = :'uid'" in sql
    assert all(v == {"uid": UID} for v, _ in welt.sql_von("passwort_hash"))


@pytest.mark.parametrize("hashes", [["gleich", "gleich"], ["", ""], ["hash-vorher", ""]])
def test_unveraenderter_oder_fehlender_hash_nach_dem_setzen_bricht_ab_und_das_konto_bleibt_gesperrt(hashes):
    welt = Welt(passwort_hash=hashes)
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Schritt 4" in fehl and "Konto bleibt gesperrt" in fehl
    assert welt.log[-1] == "sql:passwort_hash"
    for danach in ("sql:merker_anlegen", "sql:profil_aktivieren", "gotrue:entsperren"):
        assert welt.log.count(danach) == (1 if danach == "sql:merker_anlegen" else 0), danach


def test_der_hash_vor_dem_setzen_darf_leer_sein_wenn_danach_einer_da_ist():
    welt = Welt(passwort_hash=["", "hash-nachher"])
    assert welt.lauf(auftrag("freischalten"))[0] == 0


# ---------- M6: Laborprüfung über alle Schemas, Adressen ----------

LABOR_AKTIONEN = [("freischalten", {}), ("zuruecksetzen", {}), ("passwort", {}), ("austreten", {}),
                  ("umbenennen", {"name": "Anna"}), ("sperren", {})]


@pytest.mark.parametrize("aktion,extra", LABOR_AKTIONEN)
def test_ein_laborprofil_in_einem_anderen_schema_lehnt_den_befehl_ab(aktion, extra):
    """Konten gelten für alle Schemas: Die Sperre in GoTrue träfe auch das Laborprofil, das in einem anderen Schema liegt."""
    welt = Welt(labor_zaehlen=["0", "1"])
    code, _, fehl = welt.lauf(auftrag(aktion, schema="wamo_prod", **extra))
    assert code == 1 and "Laborprofil" in fehl and "wamo_test" in fehl
    assert welt.log == PRUEFEN[:4], "nur Konto, Schemas und Zählungen, nichts Ändernde"
    assert [v["schema"] for v, _ in welt.sql_von("labor_zaehlen")] == ["wamo_dev", "wamo_test"]
    assert all(v["uid"] == UID for v, _ in welt.sql_von("labor_zaehlen"))


def test_anlegen_prueft_ein_vorhandenes_konto_gegen_alle_schemas():
    welt = Welt(labor_zaehlen=["1", "0"])
    code, _, fehl = welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
    assert code == 1 and "Laborprofil" in fehl and "sql:profil_upsert" not in welt.log


def test_anlegen_eines_neuen_kontos_braucht_keine_laborpruefung():
    welt = Welt(konto_suchen="")
    welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
    assert "sql:labor_schemas" not in welt.log


def test_nur_schemas_mit_der_spalte_labor_art_werden_geprueft():
    sql = remote_namensraum()["SQL"]
    assert "information_schema.columns" in sql["labor_schemas"]
    assert "table_name = 'profiles'" in sql["labor_schemas"] and "column_name = 'labor_art'" in sql["labor_schemas"]
    assert "'wamo_dev'" in sql["labor_schemas"] and "'wamo_test'" in sql["labor_schemas"] and "'wamo_prod'" in sql["labor_schemas"]
    assert "labor_art is not null" in sql["labor_zaehlen"] and ':"schema"' in sql["labor_zaehlen"]


def test_ohne_schema_mit_laborspalte_gibt_es_nichts_zu_zaehlen():
    welt = Welt(labor_schemas="")
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 0, fehl
    assert "sql:labor_zaehlen" not in welt.log and welt.log.count("sql:labor_schemas") == 1


def test_eine_unerwartete_schemaliste_bricht_ab():
    welt = Welt(labor_schemas="wamo_dev\npublic")
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and welt.log == ["sql:konto_suchen", "sql:labor_schemas"] and "Schema" in fehl


@pytest.mark.parametrize("email", ["labor-03@wamo.test", "labor-01@wamo.test", "labor-16@wamo.test", "labor-schau@wamo.test",
                                   "LABOR-09@WAMO.TEST"])
def test_adressen_der_laborkonten_werden_bei_jedem_befehl_abgelehnt(email):
    for aktion, extra in LABOR_AKTIONEN + [("anlegen", {"name": "Anna", "rolle": "mitglied", "anrede": "du"})]:
        welt = Welt()
        code, _, fehl = welt.lauf(auftrag(aktion, email=email, **extra))
        assert code == 1 and "Laborkonto" in fehl and welt.log == [], (aktion, email)


@pytest.mark.parametrize("email", ["labor-17@wamo.test", "labor-00@wamo.test", "labor-03@wamocon.com", "laborant@wamo.test",
                                   "labor-03@wamo.test.example.invalid", "x-labor-03@wamo.test"])
def test_andere_adressen_sind_keine_laborkonten(email):
    assert Welt().lauf(auftrag("freischalten", email=email))[0] == 0, email


# ---------- L1: einmalige Tokens und Flow-State ----------

def test_sitzungen_beenden_loescht_auch_einmalige_tokens_und_flow_state_mit_zaehlprobe():
    welt = Welt(ott_loeschen="2\n0", flow_loeschen="1\n0")
    assert welt.lauf(auftrag("freischalten"))[0] == 0
    sql = welt.ns["SQL"]
    assert "delete from auth.one_time_tokens where user_id = :'uid'" in sql["ott_loeschen"]
    assert "delete from auth.flow_state where user_id = :'uid'" in sql["flow_loeschen"]
    assert "to_regclass('auth.one_time_tokens')" in sql["einmalig_vorhanden"] and "to_regclass('auth.flow_state')" in sql["einmalig_vorhanden"]
    assert welt.log.index("sql:einmalig_vorhanden") < welt.log.index("sql:ott_loeschen") < welt.log.index("sql:flow_loeschen")
    assert welt.log.index("sql:refresh_zaehlen") < welt.log.index("sql:einmalig_vorhanden")


@pytest.mark.parametrize("name", ["ott_loeschen", "flow_loeschen"])
def test_bleibt_nach_dem_loeschen_ein_einmaliger_token_oder_flow_state_bricht_der_schritt_2_ab(name):
    welt = Welt(**{name: "2\n1"})
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 1 and "Schritt 2" in fehl and "Konto bleibt gesperrt" in fehl
    assert "gotrue:passwort" not in welt.log and "gotrue:entsperren" not in welt.log


@pytest.mark.parametrize("vorhanden,erwartet", [("true|false", ["sql:ott_loeschen"]), ("false|true", ["sql:flow_loeschen"]), ("false|false", [])])
def test_fehlende_tabellen_werden_uebersprungen(vorhanden, erwartet):
    welt = Welt(einmalig_vorhanden=vorhanden)
    code, _, fehl = welt.lauf(auftrag("freischalten"))
    assert code == 0, fehl
    assert [e for e in welt.log if e in ("sql:ott_loeschen", "sql:flow_loeschen")] == erwartet


def test_auch_sperren_und_austreten_raeumen_einmalige_tokens_ab():
    for aktion in ("sperren", "austreten"):
        welt = Welt()
        assert welt.lauf(auftrag(aktion))[0] == 0
        assert "sql:ott_loeschen" in welt.log and "sql:flow_loeschen" in welt.log, aktion


# ---------- L4: Passwortregeln auch auf dem Server ----------

@pytest.mark.parametrize("passwort", ["a" * 16, "abababababab", "abcdeabcdeabcde", "anna.beispiel", "ANNA.BEISPIEL"])
def test_schwache_passwoerter_werden_auf_dem_server_abgelehnt(passwort):
    welt = Welt()
    code, _, fehl = welt.lauf(auftrag("passwort", password=passwort))
    assert code == 1 and welt.log == [] and passwort not in fehl


# ---------- Eingaben, Schema ----------

@pytest.mark.parametrize("schema", ["wamo_x", "wamo_dev; drop table x", "", "WAMO_DEV", "wamo_dev\n", "public", None])
def test_ungueltiges_schema_wird_abgelehnt_bevor_etwas_passiert(schema):
    for aktion in ("liste", "freischalten", "sperren", "austreten", "umbenennen", "anlegen"):
        welt = Welt()
        d = auftrag(aktion, name="Anna", rolle="mitglied", anrede="du")
        d["schema"] = schema
        code, _, fehl = welt.lauf(d)
        assert code == 1 and "Schema" in fehl and welt.log == [], (aktion, schema)


def test_unbekannte_aktion_wird_abgelehnt():
    welt = Welt()
    code, _, fehl = welt.lauf({"aktion": "loeschen", "schema": "wamo_dev", "email": EMAIL})
    assert code == 1 and "Aktion" in fehl and welt.log == []


def test_frist_ausserhalb_von_1_bis_168_stunden_wird_abgelehnt():
    for frist in (0, -1, 169, "72", None, True):
        welt = Welt()
        code, _, _ = welt.lauf(auftrag("freischalten", frist=frist))
        assert code == 1 and welt.log == [], frist
    for frist in (1, 72, 168):
        assert Welt().lauf(auftrag("freischalten", frist=frist))[0] == 0


# ---------- Die entfernte Seite gibt das Passwort nie aus ----------

@pytest.mark.parametrize("aktion", ["freischalten", "zuruecksetzen", "passwort"])
def test_die_entfernte_ausgabe_enthaelt_nie_das_passwort(aktion):
    folge_laenge = len(FOLGE_UEBERGABE_MIT_FAKTOREN if aktion == "zuruecksetzen" else FOLGE_UEBERGABE)
    for fehler_bei in [None] + list(range(folge_laenge)):
        welt = Welt(fehler_bei=fehler_bei, faktoren_liste=FAKTOREN_ANTWORT if aktion == "zuruecksetzen" else "")
        code, aus, fehl = welt.lauf(auftrag(aktion))
        gesehen = aus + fehl + "\n".join(welt.gedruckt)
        assert PASSWORT not in gesehen, (aktion, fehler_bei)
        for name, vars_, _ in welt.sql:
            assert PASSWORT not in json.dumps(vars_), "das Passwort geht nie an psql"
        assert all(g[0] == "passwort" for g in welt.gotrue if PASSWORT in json.dumps(g[3] or {})), "nur der Passwort-Aufruf trägt es"


def test_ein_fehlertext_mit_dem_passwort_wird_geschwaerzt():
    for quelle in ("gotrue", "sql"):
        welt = Welt()
        text = f"Fehler mit {PASSWORT} im Text"
        if quelle == "gotrue":
            welt.gotrue_antworten["passwort"] = Wirf(text)
        else:
            welt.sql_antworten["merker_anlegen"] = Wirf(text)
        code, aus, fehl = welt.lauf(auftrag("freischalten"))
        assert code == 1
        assert PASSWORT not in aus + fehl + "\n".join(welt.gedruckt)
        assert "***" in fehl


def test_der_zufallswert_beim_anlegen_wird_nie_ausgegeben():
    welt = Welt(konto_suchen="")
    welt.sql_antworten["profil_upsert"] = Wirf("Datenbankfehler: kaputt")
    code, aus, fehl = welt.lauf(auftrag("anlegen", name="Anna", rolle="mitglied", anrede="du"))
    zufall = next(g for g in welt.gotrue if g[0] == "anlegen")[3]["password"]
    assert code == 1 and zufall not in aus + fehl + "\n".join(welt.gedruckt)


# ---------- Echte Hilfsfunktionen des Serverprogramms: GoTrue-Aufruf und psql ----------

def proxylos(monkeypatch, urlopen):
    """Der GoTrue-Aufruf muss über einen eigenen Opener laufen (L2): urllib.request.urlopen würde Proxy-Variablen der Umgebung nutzen."""
    gebaut: list[tuple] = []

    def build_opener(*handler):
        gebaut.append(handler)
        return types.SimpleNamespace(open=urlopen)

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("urlopen nutzt die Proxy-Umgebung"))
    return gebaut


def test_gotrue_http_fehler_nennt_status_und_kennung_aber_nie_schluessel_oder_passwort(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# Kommentar\nSERVICE_ROLE_KEY=\"SCHLUESSEL-WERT-123\"\nANDERES=1\n", encoding="utf-8")
    ns = remote_namensraum()
    gotrue = ns["gotrue_client"](str(env))

    def urlopen(req, timeout=None):
        assert req.get_header("Authorization") == "Bearer SCHLUESSEL-WERT-123" and req.get_header("Apikey") == "SCHLUESSEL-WERT-123"
        body = json.dumps({"code": 422, "error_code": "weak_password", "msg": f"zu kurz {PASSWORT} SCHLUESSEL-WERT-123"}).encode()
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable", {}, io.BytesIO(body))

    proxylos(monkeypatch, urlopen)
    with pytest.raises(ns["Fehler"]) as exc:
        gotrue("PUT", f"/admin/users/{UID}", {"password": PASSWORT})
    text = str(exc.value)
    assert "HTTP 422" in text and "weak_password" in text
    assert "SCHLUESSEL-WERT-123" not in text and PASSWORT not in text


@pytest.mark.parametrize("body", [b"", b"<html>kein json</html>", b'{"error_code": "mit Leerzeichen und \\n Zeilen"}', b'{"msg": "x"}'])
def test_gotrue_http_fehler_mit_unbrauchbarem_body_bekommt_eine_neutrale_kennung(tmp_path, monkeypatch, body):
    env = tmp_path / ".env"
    env.write_text("SERVICE_ROLE_KEY=k\n", encoding="utf-8")
    ns = remote_namensraum()
    gotrue = ns["gotrue_client"](str(env))

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Fehler", {}, io.BytesIO(body))

    proxylos(monkeypatch, urlopen)
    with pytest.raises(ns["Fehler"]) as exc:
        gotrue("PUT", "/admin/users/x", {"ban_duration": "none"})
    assert "HTTP 500" in str(exc.value) and "unbekannt" in str(exc.value)
    assert "Leerzeichen" not in str(exc.value) and "html" not in str(exc.value)


def test_gotrue_erfolg_gibt_das_json_zurueck_und_nutzt_loopback(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SERVICE_ROLE_KEY=k\n", encoding="utf-8")
    ns = remote_namensraum()
    gotrue = ns["gotrue_client"](str(env))
    gesehen = {}

    class Antwort(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        gesehen.update(url=req.full_url, methode=req.get_method(), daten=req.data, timeout=timeout)
        return Antwort(b'{"id": "x", "banned_until": "2126-01-01T00:00:00Z"}')

    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")  # eine Proxy-Variable der Umgebung darf nie gelten
    gebaut = proxylos(monkeypatch, urlopen)
    antwort = gotrue("PUT", f"/admin/users/{UID}", {"ban_duration": "876000h"})
    assert antwort["banned_until"].startswith("2126")
    proxies = [h for handler in gebaut for h in handler if isinstance(h, urllib.request.ProxyHandler)]
    assert len(proxies) == 1 and proxies[0].proxies == {}, "ProxyHandler({}): nie ein Proxy aus der Umgebung"
    assert gesehen["url"] == f"http://localhost:55321/auth/v1/admin/users/{UID}" and gesehen["methode"] == "PUT"
    assert json.loads(gesehen["daten"]) == {"ban_duration": "876000h"} and gesehen["timeout"]


def test_gotrue_ohne_schluessel_in_der_env_bricht_ab(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANDERES=1\n", encoding="utf-8")
    ns = remote_namensraum()
    with pytest.raises(ns["Fehler"]):
        ns["gotrue_client"](str(env))("PUT", "/admin/users/x", {})


def test_psql_ruft_docker_exec_als_postgres_mit_variablen_auf(monkeypatch):
    ns = remote_namensraum()
    aufrufe = []

    def run(cmd, **kw):
        aufrufe.append((cmd, kw))
        return type("R", (), {"returncode": 0, "stdout": " ergebnis \n", "stderr": ""})()

    monkeypatch.setattr(subprocess, "run", run)
    assert ns["psql_ausfuehren"]("select 1;", schema="wamo_dev", uid=UID) == "ergebnis"
    cmd, kw = aufrufe[0]
    assert cmd[:11] == ["docker", "exec", "-i", "wamo-supabase-db", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-tA", "-q"]
    assert ["-v", "schema=wamo_dev"] == cmd[11:13] and ["-v", f"uid={UID}"] == cmd[13:15]
    assert kw["input"] == "select 1;"


def test_psql_fehler_wird_zu_einem_datenbankfehler_ohne_eingabe(monkeypatch):
    ns = remote_namensraum()
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: type("R", (), {"returncode": 3, "stdout": "", "stderr": "ERROR: " + "x" * 500})())
    with pytest.raises(ns["Fehler"]) as exc:
        ns["psql_ausfuehren"]("select 1;")
    assert str(exc.value).startswith("Datenbankfehler: ") and len(str(exc.value)) <= len("Datenbankfehler: ") + 300


def test_der_rumpf_startet_main_nur_als_programm():
    ns = remote_namensraum()
    assert callable(ns["main"]) and callable(ns["verarbeite"])  # exec mit anderem Namen hat nichts gestartet (kein stdin gelesen)
    assert wn.REMOTE.rstrip().endswith('if __name__ == "__main__":\n    main()')


# ---------- Lokale Seite: Passwörter ----------

def test_startpasswort_hat_16_zeichen_aus_dem_alphabet_ohne_verwechselbare_zeichen():
    gesehen = set()
    for _ in range(300):
        pw = wn.startpasswort_erzeugen()
        assert len(pw) == 16 == wn.PASSWORT_LAENGE and wn.PASSWORT_LAENGE >= wn.MIN_PASSWORD >= 12
        assert set(pw) <= set(wn.PASSWORT_ALPHABET)
        assert any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw)
        gesehen.add(pw)
    assert len(gesehen) == 300
    assert all(len(set(pw)) >= 6 for pw in gesehen)
    assert not set("0O1lIo|") & set(wn.PASSWORT_ALPHABET), "keine verwechselbaren Zeichen"
    assert len(wn.PASSWORT_ALPHABET) == len(set(wn.PASSWORT_ALPHABET)) >= 50


def test_ask_password_verlangt_mindestlaenge_und_wiederholung(monkeypatch):
    eingaben = iter(["kurz"])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    with pytest.raises(SystemExit):
        wn.ask_password()
    eingaben = iter([PASSWORT, "anderes-Passwort-123"])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    with pytest.raises(SystemExit):
        wn.ask_password()
    eingaben = iter([PASSWORT, PASSWORT])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    assert wn.ask_password() == PASSWORT
    eingaben = iter(["a" * 73])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    with pytest.raises(SystemExit):
        wn.ask_password()


def test_ask_password_lehnt_wenige_verschiedene_zeichen_und_den_teil_vor_dem_at_ab(monkeypatch):
    for schlecht in ("a" * 16, "abababababab", "abcabcabcabc", "abcdeabcdeabcde"):  # 1, 2, 3 und 5 verschiedene Zeichen
        eingaben = iter([schlecht, schlecht])
        monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
        with pytest.raises(SystemExit) as exc:
            wn.ask_password(EMAIL)
        assert "verschiedene" in str(exc.value), schlecht
    teil = EMAIL.split("@")[0]  # anna.beispiel (13 Zeichen)
    for gleich in (teil, teil.upper()):
        eingaben = iter([gleich, gleich])
        monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
        with pytest.raises(SystemExit) as exc:
            wn.ask_password(EMAIL)
        assert "E-Mail" in str(exc.value)
    eingaben = iter([PASSWORT, PASSWORT])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    assert wn.ask_password(EMAIL) == PASSWORT


# ---------- Lokale Seite: Befehlszeile ----------

@pytest.fixture
def terminal(monkeypatch):
    """passwort verlangt ein echtes Terminal (L4); unter pytest ist stdin keines."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

class Ferne:
    """Attrappe für den ssh-Weg: merkt sich Host und Nutzlast und antwortet mit einem festen Ergebnis."""

    def __init__(self, stdout: str = "erledigt\n", stderr: str = "", returncode: int = 0):
        self.aufrufe: list[tuple[str, dict]] = []
        self.antwort = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    def __call__(self, host: str, nutzlast: dict):
        self.aufrufe.append((host, json.loads(json.dumps(nutzlast))))
        return self.antwort


def lokal(argv: list[str], ferne: Ferne | None = None):
    aus, fehl = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(aus), redirect_stderr(fehl):
        try:
            wn.main(argv, remote=ferne or Ferne())
        except SystemExit as e:
            code = e.code if e.code is not None else 0
    return code, aus.getvalue(), fehl.getvalue()


@pytest.mark.parametrize("argv", [
    ["anlegen", "--email", EMAIL, "--name", "Anna"],
    ["freischalten", "--email", EMAIL],
    ["zuruecksetzen", "--email", EMAIL],
    ["passwort", "--email", EMAIL],
    ["umbenennen", "--email", EMAIL, "--name", "Anna"],
    ["sperren", "--email", EMAIL],
    ["sperren", "--offene"],
    ["austreten", "--email", EMAIL],
])
def test_jeder_aendernde_befehl_verlangt_das_schema_ausdruecklich(argv):
    ferne = Ferne()
    code, _, fehl = lokal(argv, ferne)
    assert code == 2 and "--schema" in fehl
    assert ferne.aufrufe == []


def test_sperren_ohne_schema_bricht_ab_mit_systemexit():
    with pytest.raises(SystemExit) as exc:
        wn.main(["sperren", "--email", EMAIL], remote=Ferne())
    assert exc.value.code == 2


def test_liste_behaelt_das_standardschema():
    ferne = Ferne(stdout="Anna | ...\n")
    code, aus, _ = lokal(["liste"], ferne)
    assert code == 0 and ferne.aufrufe[0][1] == {"aktion": "liste", "schema": "wamo_dev"} and "Anna" in aus
    assert lokal(["liste", "--schema", "wamo_test"], ferne)[0] == 0 and ferne.aufrufe[1][1]["schema"] == "wamo_test"


@pytest.mark.parametrize("argv", [
    ["liste", "--schema", "wamo_x"],
    ["liste", "--schema", "wamo_dev; drop table x"],
    ["freischalten", "--email", "kein-at", "--schema", "wamo_dev"],
    ["freischalten", "--email", EMAIL, "--schema", "wamo_dev", "--frist-stunden", "0"],
    ["freischalten", "--email", EMAIL, "--schema", "wamo_dev", "--frist-stunden", "169"],
    ["freischalten", "--email", EMAIL, "--schema", "wamo_dev", "--frist-stunden", "viel"],
    ["anlegen", "--email", EMAIL, "--name", "", "--schema", "wamo_dev"],
    ["anlegen", "--email", EMAIL, "--name", "x" * 61, "--schema", "wamo_dev"],
    ["anlegen", "--email", EMAIL, "--name", "Anna", "--rolle", "root", "--schema", "wamo_dev"],
    ["anlegen", "--email", EMAIL, "--name", "Anna", "--anrede", "ihr", "--schema", "wamo_dev"],
    ["umbenennen", "--email", EMAIL, "--name", "  ", "--schema", "wamo_dev"],
    ["sperren", "--schema", "wamo_dev"],
    ["sperren", "--email", EMAIL, "--offene", "--schema", "wamo_dev"],
    ["unbekannt"],
])
def test_ungueltige_befehlszeilen_gehen_nie_zum_server(argv):
    ferne = Ferne()
    code, _, _ = lokal(argv, ferne)
    assert code != 0 and ferne.aufrufe == []


def test_anlegen_schickt_kein_passwort_und_den_standard_fuer_rolle_und_anrede():
    ferne = Ferne()
    code, _, _ = lokal(["anlegen", "--email", EMAIL, "--name", "  Anna Beispiel ", "--schema", "wamo_dev"], ferne)
    assert code == 0
    assert ferne.aufrufe[0][1] == {"aktion": "anlegen", "schema": "wamo_dev", "email": EMAIL, "name": "Anna Beispiel",
                                   "rolle": "mitglied", "anrede": "du"}


def test_freischalten_gibt_das_startpasswort_genau_einmal_nach_erfolg_aus(monkeypatch):
    monkeypatch.setattr(wn, "startpasswort_erzeugen", lambda: "Abcdefghjkmn2345")
    ferne = Ferne(stdout=f"Frist bis: {FRIST_TEXT}\n")
    code, aus, fehl = lokal(["freischalten", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code == 0
    nutzlast = ferne.aufrufe[0][1]
    assert nutzlast["password"] == "Abcdefghjkmn2345" and nutzlast["frist"] == 72 and nutzlast["faktoren_loeschen"] is False
    assert aus.count("Abcdefghjkmn2345") == 1 and "Abcdefghjkmn2345" not in fehl
    assert "nur auf das willkommensblatt" in aus.lower() and "72 Stunden gültig" in aus
    assert FRIST_TEXT in aus


def test_freischalten_mit_eigener_frist_und_faktorenschalter(monkeypatch):
    monkeypatch.setattr(wn, "startpasswort_erzeugen", lambda: "Abcdefghjkmn2345")
    ferne = Ferne()
    code, aus, _ = lokal(["freischalten", "--email", EMAIL, "--schema", "wamo_test", "--frist-stunden", "24", "--faktoren-loeschen"], ferne)
    nutzlast = ferne.aufrufe[0][1]
    assert code == 0 and nutzlast["frist"] == 24 and nutzlast["faktoren_loeschen"] is True and nutzlast["schema"] == "wamo_test"
    assert "24 Stunden gültig" in aus


def test_zuruecksetzen_gibt_das_startpasswort_einmal_aus(monkeypatch):
    monkeypatch.setattr(wn, "startpasswort_erzeugen", lambda: "Abcdefghjkmn2345")
    ferne = Ferne()
    code, aus, _ = lokal(["zuruecksetzen", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code == 0 and aus.count("Abcdefghjkmn2345") == 1
    assert ferne.aufrufe[0][1]["aktion"] == "zuruecksetzen" and ferne.aufrufe[0][1]["password"] == "Abcdefghjkmn2345"


def test_bei_einem_fehler_auf_dem_server_erscheint_das_startpasswort_nie(monkeypatch):
    monkeypatch.setattr(wn, "startpasswort_erzeugen", lambda: "Abcdefghjkmn2345")
    ferne = Ferne(stdout="Schritt 1 ok\n", stderr="Fehler: Schritt 4 (Startpasswort setzen): HTTP 500\n", returncode=1)
    code, aus, fehl = lokal(["freischalten", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code != 0 and "Abcdefghjkmn2345" not in aus + str(code) + fehl
    assert "Schritt 4" in str(code) + fehl


def test_lokal_wird_das_passwort_auch_aus_der_ferne_ausgabe_entfernt(monkeypatch):
    monkeypatch.setattr(wn, "startpasswort_erzeugen", lambda: "Abcdefghjkmn2345")
    ferne = Ferne(stdout="Leck: Abcdefghjkmn2345\n")
    code, aus, _ = lokal(["freischalten", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code == 0 and "Leck: ***" in aus and aus.count("Abcdefghjkmn2345") == 1


def test_passwort_fragt_verdeckt_schickt_es_nur_an_den_server_und_gibt_es_nie_aus(monkeypatch, terminal):
    eingaben = iter([PASSWORT, PASSWORT])
    fragen = []
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": fragen.append(prompt) or next(eingaben))
    ferne = Ferne(stdout="Merker als erledigt geschrieben.\n")
    code, aus, fehl = lokal(["passwort", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code == 0 and len(fragen) == 2
    nutzlast = ferne.aufrufe[0][1]
    assert nutzlast["password"] == PASSWORT and nutzlast["aktion"] == "passwort" and nutzlast["faktoren_loeschen"] is False
    assert PASSWORT not in aus + fehl


def test_passwort_mit_nicht_uebereinstimmender_eingabe_geht_nie_zum_server(monkeypatch, terminal):
    eingaben = iter([PASSWORT, "ein-anderes-Passwort-1"])
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": next(eingaben))
    ferne = Ferne()
    code, _, _ = lokal(["passwort", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code != 0 and ferne.aufrufe == []


def test_passwort_ohne_terminal_fragt_nichts_und_geht_nie_zum_server(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(wn.getpass, "getpass", lambda prompt="": pytest.fail("darf nicht fragen"))
    ferne = Ferne()
    code, _, _ = lokal(["passwort", "--email", EMAIL, "--schema", "wamo_dev"], ferne)
    assert code != 0 and "Terminal" in str(code) and ferne.aufrufe == []


def test_sperren_mit_offene_und_austreten_und_umbenennen_schicken_die_richtige_nutzlast():
    ferne = Ferne()
    assert lokal(["sperren", "--offene", "--schema", "wamo_prod"], ferne)[0] == 0
    assert lokal(["austreten", "--email", EMAIL, "--schema", "wamo_dev"], ferne)[0] == 0
    assert lokal(["umbenennen", "--email", EMAIL, "--name", "Anna Maria", "--schema", "wamo_dev"], ferne)[0] == 0
    sperren, austreten, umbenennen = (a[1] for a in ferne.aufrufe)
    assert sperren == {"aktion": "sperren", "schema": "wamo_prod", "offene": True}
    assert austreten == {"aktion": "austreten", "schema": "wamo_dev", "email": EMAIL}
    assert umbenennen == {"aktion": "umbenennen", "schema": "wamo_dev", "email": EMAIL, "name": "Anna Maria"}


def test_host_kommt_aus_dem_aufruf_oder_der_umgebung(monkeypatch):
    ferne = Ferne()
    monkeypatch.setenv("WAMO_SSH_HOST", "von-der-umgebung")
    lokal(["liste"], ferne)
    lokal(["liste", "--host", "explizit"], ferne)
    assert [a[0] for a in ferne.aufrufe] == ["von-der-umgebung", "explizit"]


# ---------- Der Weg per ssh ----------

def test_run_remote_schickt_das_passwort_nur_ueber_stdin(monkeypatch):
    gesehen = {}

    def run(args, **kw):
        gesehen.update(args=args, **kw)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    wn.run_remote("wamo-sokrates2", {"aktion": "freischalten", "schema": "wamo_dev", "email": EMAIL, "password": PASSWORT})
    args = gesehen["args"]
    assert args[0] == "ssh" and "wamo-sokrates2" in args and "BatchMode=yes" in args
    assert PASSWORT not in " ".join(args), "nie in der Befehlszeile"
    assert json.loads(gesehen["input"])["password"] == PASSWORT
    programm = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", args[-1]).group(1)
    assert zlib.decompress(base64.b64decode(programm)).decode("utf-8") == wn.REMOTE
    assert PASSWORT not in wn.REMOTE
    assert args[args.index("wamo-sokrates2") - 1] == "--", "vor dem Host steht --, damit er nie als Option gilt"


def test_remote_nutzlast_ist_ascii_sicher(monkeypatch):
    gesehen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: gesehen.update(input=kw["input"]) or subprocess.CompletedProcess(args, 0, "", ""))
    wn.run_remote("h", {"aktion": "umbenennen", "name": "Jörg Müller-Weiß"})
    assert gesehen["input"].isascii() and json.loads(gesehen["input"])["name"] == "Jörg Müller-Weiß"


def test_die_ssh_befehlszeile_ist_kurz_genug_fuer_windows(monkeypatch):
    """M4: Windows erlaubt 32767 Zeichen, das ungepackte Programm brauchte schon etwa 30800."""
    gesehen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: gesehen.update(args=args) or subprocess.CompletedProcess(args, 0, "", ""))
    wn.run_remote("wamo-sokrates2", {"aktion": "liste", "schema": "wamo_dev"})
    befehl = gesehen["args"][-1]
    assert len(befehl) < 20000, len(befehl)
    assert sum(len(a) for a in gesehen["args"]) < 20000
    assert "zlib.decompress" in befehl and befehl.startswith("python3 -c ")


def test_der_gepackte_befehl_laeuft_als_programm(tmp_path):
    """Der Befehl wird mit dem lokalen Python ausgeführt (ohne ssh): Entpacken und Start als Programm."""
    gesehen = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subprocess, "run", lambda args, **kw: gesehen.update(args=args) or subprocess.CompletedProcess(args, 0, "", ""))
        wn.run_remote("h", {})
    innen = re.fullmatch(r'python3 -c "(.*)"', gesehen["args"][-1], re.S).group(1)
    r = subprocess.run([sys.executable, "-c", innen], input=json.dumps({"aktion": "unbekannt"}), capture_output=True, text=True,
                       encoding="utf-8", timeout=60, cwd=str(tmp_path))
    assert r.returncode == 1 and "Unbekannte Aktion" in r.stderr


@pytest.mark.parametrize("host", ["-oProxyCommand=evil", "-x", "", "a b", "host;ls", "host\n", "ho$st", "a/b", "ü-host"])
def test_run_remote_lehnt_gefaehrliche_hostnamen_ab_bevor_ssh_startet(monkeypatch, host):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ssh darf nicht starten"))
    with pytest.raises(SystemExit):
        wn.run_remote(host, {"aktion": "liste", "schema": "wamo_dev"})


@pytest.mark.parametrize("host", ["wamo-sokrates2", "sokrates2", "192.168.178.136", "host.example.invalid", "a_b-1.c"])
def test_run_remote_akzeptiert_gewoehnliche_hostnamen(monkeypatch, host):
    gesehen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: gesehen.update(args=args) or subprocess.CompletedProcess(args, 0, "", ""))
    wn.run_remote(host, {})
    assert gesehen["args"][-3:-1] == ["--", host]


def test_ein_gefaehrlicher_host_in_der_befehlszeile_oder_umgebung_geht_nie_zum_server(monkeypatch):
    ferne = Ferne()
    code, _, _ = lokal(["liste", "--host=-oProxyCommand=evil"], ferne)
    assert code != 0 and ferne.aufrufe == []
    monkeypatch.setenv("WAMO_SSH_HOST", "-bad")
    code, _, _ = lokal(["liste"], ferne)
    assert code != 0 and ferne.aufrufe == []


@pytest.mark.parametrize("email", ["labor-03@wamo.test", "labor-schau@wamo.test", "LABOR-16@WAMO.TEST"])
def test_laborkonten_werden_lokal_abgelehnt(email):
    ferne = Ferne()
    for argv in (["anlegen", "--email", email, "--name", "Anna", "--schema", "wamo_dev"],
                 ["freischalten", "--email", email, "--schema", "wamo_dev"],
                 ["sperren", "--email", email, "--schema", "wamo_dev"],
                 ["austreten", "--email", email, "--schema", "wamo_dev"]):
        code, _, fehl = lokal(argv, ferne)
        assert code == 2 and "Laborkonto" in fehl, argv
    assert ferne.aufrufe == []


# ---------- Protokoll auf dem Server (L5) ----------

def test_protokollzeile_bei_erfolg_nennt_aktion_schema_und_email_aber_nie_das_passwort():
    welt = Welt()
    code, _, _ = welt.lauf(auftrag("freischalten"))
    assert code == 0
    assert welt.protokoll == [f"aktion=freischalten schema=wamo_dev email={EMAIL} ergebnis=ok"]
    assert PASSWORT not in " ".join(welt.protokoll)


def test_protokollzeile_bei_fehler_nennt_die_schrittnummer():
    welt = Welt()
    welt.gotrue_antworten["passwort"] = Wirf(f"HTTP 422 weak_password {PASSWORT}")
    code, _, _ = welt.lauf(auftrag("freischalten"))
    assert code == 1
    assert welt.protokoll == [f"aktion=freischalten schema=wamo_dev email={EMAIL} ergebnis=fehler schritt=4"]
    assert PASSWORT not in " ".join(welt.protokoll) and "weak_password" not in " ".join(welt.protokoll)


@pytest.mark.parametrize("name,antwort,schritt", [("merker_anlegen", Wirf("kaputt"), "1b"), ("refresh_zaehlen", "1", "2")])
def test_protokollzeile_traegt_auch_schritte_mit_buchstaben(name, antwort, schritt):
    welt = Welt(**{name: antwort})
    welt.lauf(auftrag("freischalten"))
    assert welt.protokoll == [f"aktion=freischalten schema=wamo_dev email={EMAIL} ergebnis=fehler schritt={schritt}"]


def test_protokollzeile_bei_abgelehnter_eingabe_und_ohne_email_ist_sauber():
    welt = Welt()
    welt.lauf({"aktion": "liste", "schema": "wamo_dev"})
    welt.lauf({"aktion": "sperren", "schema": "wamo_dev", "offene": True})
    welt.lauf(auftrag("freischalten", email="a b\nc@example.invalid", password=PASSWORT))
    assert welt.protokoll[0] == "aktion=liste schema=wamo_dev email=- ergebnis=ok"
    assert welt.protokoll[1].startswith("aktion=sperren schema=wamo_dev email=- ergebnis=")
    assert "\n" not in welt.protokoll[2] and "a b" not in welt.protokoll[2], "Leerraum und Umbrüche werden ersetzt"
    assert "ergebnis=fehler" in welt.protokoll[2] and PASSWORT not in "".join(welt.protokoll)


def test_ein_fehler_beim_protokollieren_stoert_den_auftrag_nie():
    welt = Welt()

    def kaputt(zeile):
        raise RuntimeError("logger kaputt")

    welt.ns["print"] = print
    code = welt.ns["verarbeite"](auftrag("freischalten"), welt.psql, welt.gotrue_aufruf, kaputt)
    assert code == 0


def test_protokoll_senden_ruft_logger_mit_dem_tag_auf_und_ignoriert_fehler(monkeypatch):
    ns = remote_namensraum()
    aufrufe = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: aufrufe.append(cmd) or types.SimpleNamespace(returncode=0))
    ns["protokoll_senden"]("aktion=liste schema=wamo_dev email=- ergebnis=ok")
    assert aufrufe == [["logger", "-t", "wamo-nutzer", "aktion=liste schema=wamo_dev email=- ergebnis=ok"]]

    def fehlt(cmd, **kw):
        raise FileNotFoundError("logger")

    monkeypatch.setattr(subprocess, "run", fehlt)
    ns["protokoll_senden"]("egal")  # kein Fehler
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 5)))
    ns["protokoll_senden"]("egal")
