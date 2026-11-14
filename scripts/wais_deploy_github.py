"""Hilfen der Ausroll-Workflows (.github/workflows/deploy*.yml), die auf einem Runner von GitHub laufen, nie auf Sokrates-2.

Nur Standardbibliothek. Liest die REST-API von GitHub mit dem Token des Laufs (GH_TOKEN), schreibt nichts in das Repository.

  python3 scripts/wais_deploy_github.py stand --eingabe <commit|v<version>-<commit7>|leer>
        löst die Eingabe zu genau einem Commit (40 Zeichen) auf und prüft, dass er in main enthalten ist. Ausgabe commit=... und
        kopf=ja|nein (auch nach GITHUB_OUTPUT). Leer heißt: der Commit des Laufs (GITHUB_SHA).
  python3 scripts/wais_deploy_github.py pruefungen --commit <sha40> [--pflicht <pfad,pfad>] [--frist <minuten>]
        wartet, bis die Prüf-Workflows des Commits fertig sind, und verlangt, dass alle bestanden haben. Die eigenen Ausroll-Workflows
        (.github/workflows/deploy*) zählen nicht. Mit --pflicht (Repository-Variable WAIS_PRUEF_WORKFLOWS) muss jeder genannte
        Workflow einen Lauf für den Commit haben. Ohne Pflichtliste gilt: alle vorhandenen Läufe grün, frühestens 90 Sekunden nach dem Start.
  python3 scripts/wais_deploy_github.py umgebung --name prod
        prüft, dass das Environment Pflicht-Prüfer und eine Regel für die Zweige hat. Sonst Abbruch: ohne diesen Schutz liefe prod
        ohne Freigabe.

Rückgabe: 0 in Ordnung, 1 nicht bestanden oder Fehler, 2 Aufruf ungültig.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
KURZ_RE = re.compile(r"[0-9a-f]{7,40}")
RELEASE_RE = re.compile(r"v(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})-([0-9a-f]{7})")
PFAD_RE = re.compile(r"\.github/workflows/[A-Za-z0-9._-]{1,100}\.ya?ml")
EIGENE_PRAEFIX = ".github/workflows/deploy"
GUT = {"success", "skipped", "neutral"}
MINDEST_WARTEN_S = 90
TAKT_S = 30


class Abbruch(Exception):
    """Nicht bestanden oder nicht prüfbar; die Meldung geht an den Lauf."""


# ---------------------------------------------------------------- reine Logik (getestet ohne Netz)
def eingabe_zu_ref(eingabe: str, standard: str) -> str:
    """Commit (7 bis 40 Hexzeichen, klein), Release-Name v<version>-<commit7> oder leer (dann standard). Sonst Abbruch."""
    text = (eingabe or "").strip()
    if not text:
        text = standard
    if KURZ_RE.fullmatch(text):
        return text
    treffer = RELEASE_RE.fullmatch(text)
    if treffer:
        return treffer.group(1)
    raise Abbruch("Stand ungültig: erwartet ein Commit (7 bis 40 Hexzeichen, klein) oder ein Release-Name v<version>-<commit7>.")


def in_main(vergleich_status: str) -> bool:
    """Status von compare/{commit}...main: ahead oder identical heißt, main enthält den Commit."""
    return vergleich_status in {"ahead", "identical"}


def pflicht_lesen(text: str) -> list[str]:
    """Kommagetrennte Workflow-Pfade aus der Repository-Variable; jeder muss wie .github/workflows/<datei>.yml aussehen."""
    pfade = [p.strip() for p in (text or "").split(",") if p.strip()]
    for pfad in pfade:
        if not PFAD_RE.fullmatch(pfad):
            raise Abbruch(f"WAIS_PRUEF_WORKFLOWS enthält einen ungültigen Pfad: {pfad!r}")
        if pfad.startswith(EIGENE_PRAEFIX):
            raise Abbruch(f"WAIS_PRUEF_WORKFLOWS darf keinen Ausroll-Workflow nennen: {pfad}")
    return pfade


@dataclass(frozen=True)
class Bewertung:
    zustand: str  # ok | warten | fehler
    meldung: str


def neueste_je_workflow(laeufe: list[dict]) -> dict[str, dict]:
    """Je Workflow-Pfad der neueste Lauf (höchste run_number, dann id); die eigenen Ausroll-Workflows fallen heraus."""
    neueste: dict[str, dict] = {}
    for lauf in laeufe:
        pfad = str(lauf.get("path", "")).split("@", 1)[0]
        if not pfad or pfad.startswith(EIGENE_PRAEFIX):
            continue
        schluessel = (int(lauf.get("run_number") or 0), int(lauf.get("id") or 0))
        bisher = neueste.get(pfad)
        if bisher is None or schluessel > (int(bisher.get("run_number") or 0), int(bisher.get("id") or 0)):
            neueste[pfad] = lauf
    return neueste


def bewerten(laeufe: list[dict], pflicht: list[str], vergangen_s: float, mindest_s: float = MINDEST_WARTEN_S) -> Bewertung:
    """Entscheidet über die Prüf-Workflows eines Commits. Ein fehlgeschlagener Lauf beendet das Warten sofort."""
    neueste = neueste_je_workflow(laeufe)
    rot = sorted(f"{pfad} ({lauf.get('conclusion')})" for pfad, lauf in neueste.items()
                 if lauf.get("status") == "completed" and lauf.get("conclusion") not in GUT)
    if rot:
        return Bewertung("fehler", "Nicht bestanden: " + ", ".join(rot))
    fehlend = [p for p in pflicht if p not in neueste]
    laufend = sorted(pfad for pfad, lauf in neueste.items() if lauf.get("status") != "completed")
    if fehlend or laufend:
        teile = []
        if fehlend:
            teile.append("noch ohne Lauf: " + ", ".join(fehlend))
        if laufend:
            teile.append("laufen noch: " + ", ".join(laufend))
        return Bewertung("warten", "; ".join(teile))
    if not pflicht and vergangen_s < mindest_s:
        return Bewertung("warten", f"warte, ob weitere Prüf-Workflows starten ({int(vergangen_s)} von {int(mindest_s)} s)")
    if not neueste:
        return Bewertung("fehler", "Für diesen Commit gibt es keinen Prüf-Workflow. Die Prüfungen müssen auch bei push auf main "
                                   "laufen; die Pflichtliste steht in der Repository-Variable WAIS_PRUEF_WORKFLOWS.")
    return Bewertung("ok", "Bestanden: " + ", ".join(f"{p} ({neueste[p].get('conclusion')})" for p in sorted(neueste)))


def umgebung_bewerten(daten: dict) -> list[str]:
    """Mängel des Environments: ohne Pflicht-Prüfer oder ohne Regel für Zweige liefe prod ohne Freigabe oder von jedem Zweig."""
    maengel = []
    regeln = daten.get("protection_rules") or []
    pruefer = [r for r in regeln if r.get("type") == "required_reviewers" and r.get("reviewers")]
    if not pruefer:
        maengel.append("keine Pflicht-Prüfer (Required reviewers)")
    if not daten.get("deployment_branch_policy"):
        maengel.append("keine Regel für Zweige (Deployment branches: nur main)")
    return maengel


# ---------------------------------------------------------------- GitHub
def api(pfad: str) -> dict:
    basis = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise Abbruch("GH_TOKEN fehlt.")
    anfrage = urllib.request.Request(basis + pfad, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "wais-deploy"})
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:  # noqa: S310 (feste https-Adresse von GitHub)
            return json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as fehler:
        raise Abbruch(f"GitHub antwortet auf {pfad} mit {fehler.code}") from None
    except urllib.error.URLError as fehler:
        raise Abbruch(f"GitHub nicht erreichbar: {fehler.reason}") from None


def repo() -> str:
    name = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", name):
        raise Abbruch("GITHUB_REPOSITORY fehlt oder ist ungültig.")
    return name


def ausgabe(**werte: str) -> None:
    for schluessel, wert in werte.items():
        print(f"{schluessel}={wert}")
    ziel = os.environ.get("GITHUB_OUTPUT")
    if ziel:
        with open(ziel, "a", encoding="utf-8") as datei:
            for schluessel, wert in werte.items():
                datei.write(f"{schluessel}={wert}\n")


def zusammenfassung(text: str) -> None:
    ziel = os.environ.get("GITHUB_STEP_SUMMARY")
    if ziel:
        with open(ziel, "a", encoding="utf-8") as datei:
            datei.write(text + "\n")


def cmd_stand(args) -> None:
    ref = eingabe_zu_ref(args.eingabe, os.environ.get("GITHUB_SHA", ""))
    commit = str(api(f"/repos/{repo()}/commits/{urllib.parse.quote(ref)}").get("sha", ""))
    if not COMMIT_RE.fullmatch(commit):
        raise Abbruch(f"Zu {ref} gibt es keinen eindeutigen Commit.")
    vergleich = api(f"/repos/{repo()}/compare/{commit}...main")
    if not in_main(str(vergleich.get("status", ""))):
        raise Abbruch(f"Commit {commit} ist nicht in main enthalten (Vergleich: {vergleich.get('status')}). Ausgerollt wird nur Gemergtes.")
    kopf = "ja" if vergleich.get("status") == "identical" else "nein"
    ausgabe(commit=commit, kopf=kopf)
    zusammenfassung(f"Stand: `{commit}` (Kopf von main: {kopf})")


def cmd_pruefungen(args) -> None:
    if not COMMIT_RE.fullmatch(args.commit or ""):
        raise Abbruch("--commit: genau 40 Hexzeichen, klein.")
    pflicht = pflicht_lesen(args.pflicht)
    start = time.monotonic()
    ende = start + args.frist * 60
    while True:
        daten = api(f"/repos/{repo()}/actions/runs?head_sha={args.commit}&per_page=100")
        bewertung = bewerten(list(daten.get("workflow_runs") or []), pflicht, time.monotonic() - start)
        print(f"[{int(time.monotonic() - start):>5} s] {bewertung.zustand}: {bewertung.meldung}", flush=True)
        if bewertung.zustand == "ok":
            zusammenfassung(f"Prüfungen: {bewertung.meldung}")
            return
        if bewertung.zustand == "fehler":
            raise Abbruch(bewertung.meldung)
        if time.monotonic() + TAKT_S > ende:
            raise Abbruch(f"Frist von {args.frist} Minuten abgelaufen: {bewertung.meldung}")
        time.sleep(TAKT_S)


def cmd_umgebung(args) -> None:
    if not re.fullmatch(r"[a-z]{1,20}", args.name):
        raise Abbruch("--name ungültig.")
    try:
        daten = api(f"/repos/{repo()}/environments/{args.name}")
    except Abbruch as fehler:
        raise Abbruch(f"Environment {args.name} nicht lesbar ({fehler}). Es muss in den Einstellungen des Repos angelegt sein.") from None
    maengel = umgebung_bewerten(daten)
    if maengel:
        raise Abbruch(f"Environment {args.name} ist nicht geschützt: " + "; ".join(maengel) + ". Einstellungen: docs/runner-einrichten.md")
    print(f"Environment {args.name}: Pflicht-Prüfer und Regel für Zweige vorhanden.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hilfen der Ausroll-Workflows (nur lesend gegen GitHub)")
    unter = parser.add_subparsers(dest="befehl", required=True)
    p = unter.add_parser("stand")
    p.add_argument("--eingabe", default="")
    p = unter.add_parser("pruefungen")
    p.add_argument("--commit", required=True)
    p.add_argument("--pflicht", default="")
    p.add_argument("--frist", type=int, default=60, choices=range(1, 181), metavar="MINUTEN")
    p = unter.add_parser("umgebung")
    p.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    try:
        {"stand": cmd_stand, "pruefungen": cmd_pruefungen, "umgebung": cmd_umgebung}[args.befehl](args)
    except Abbruch as fehler:
        print(f"::error::{fehler}", file=sys.stderr)
        zusammenfassung(f"**Abbruch:** {fehler}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
