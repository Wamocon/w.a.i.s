"""Persönlicher GitHub-Weg eines Entwicklungsauftrags, Seite des Kerns (Plan C, docs/persoenliche-zugaenge.md C.2, C.6, C.7).

Reine Hilfen ohne Netz, Datenbank und Prozesse, damit dev_agent.py nur dünne Einhängepunkte braucht:

  * Kopfzeile von start: kopffelder() setzt github=persoenlich und die vom Admin erlaubten Ausnahmen (sortiert, C.2.8).
  * stdin: github_zeile() baut genau {"typ":"github","wert":"<token>"} ohne Leerzeichen (C.2.2), einreichen_zeile() die erste Zeile von
    einreichen (C.2.3). Beide nur aus geprüften Werten; das Token steht nie in argv, nie im Log und in keinem Rückgabewert außer der Zeile.
  * Ereignisse des Dispatchers (C.2.4): github_info(), aenderung_pruefen() und eingereicht_pruefen() lesen nur bekannte Felder mit festen
    Formen; Pfade, Titel und Adressen gehen nie an das Sprachmodell, nur auf Canvas und Karte (adresse nur nach ADRESSE_RE mit dem Repo).
  * Karte "Einreichen" (C.6): karte() baut den Eintrag der Freigaben mit id "einreichen" und dem Zusatzfeld einreichen.
  * Sätze zu den Codes aus Paket S (entwicklung_betrieb.GITHUB_SAETZE, AENDERUNG_SAETZE, EINREICHEN_SAETZE, GRUND_SAETZE).

Die Listen EREIGNISSE_GITHUB und AENDERUNG_STATUS sind Gegenstücke derselben Namen in infra/sokrates2/wamo_job_github.py; der
Vertragstest hält beide gleich.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

import entwicklung_betrieb as eb

EREIGNISSE_GITHUB = ("github", "aenderung", "eingereicht", "einreichen_fehler", "verworfen")
AENDERUNG_STATUS = ("keine", "gesperrt", "nur_lesen", "bereit", "einreichen_laeuft", "branch_gepusht", "eingereicht", "verworfen")
STATUS_KARTE = ("bereit", "gesperrt", "branch_gepusht", "einreichen_laeuft")  # mit diesen Zuständen gibt es eine Karte
STATUS_EINREICHEN = ("bereit", "branch_gepusht", "einreichen_laeuft")  # aus diesen nimmt der Dispatcher einreichen an
STATUS_VERWERFEN = ("keine", "gesperrt", "nur_lesen", "bereit")  # aus diesen nimmt er verwerfen an (C.2.3)
KARTE_ID = "einreichen"
WERKZEUG_EINREICHEN = "auftrag_einreichen"  # Zeile in actions (Repo, Zweig, Commit, Pull Request), nie ein Token
EINREICHEN_ZEILE_MAX_BYTES = 64 * 1024  # wie wamo_job_github.EINREICHEN_ZEILE_MAX_BYTES
GITHUB_ZEILE_MAX_BYTES = 256  # wie wamo_job_github.GITHUB_ZEILE_MAX_BYTES
MAX_LISTE = 200
PFAD_ZEICHEN = 300
TITEL_ZEICHEN = 100
ZAHL_MAX = 10_000_000

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
ZWEIG_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
_TOKEN = {art: re.compile(muster) for art, muster in eb.GITHUB_TOKEN_FORMEN.items()}
ARTEN_LISTE = ("neu", "geaendert", "geloescht")
KLASSEN = ("normal", "sensibel")
LAUF = ("fertig", "zeitlimit", "fehler")

SATZ_TOKEN_FEHLT = ("Dein GitHub-Token ist gerade nicht nutzbar (nicht hinterlegt, abgelaufen oder mit Rechten, die nicht passen). Bitte "
                    "in den Einstellungen unter GitHub-Zugang prüfen.")
SATZ_EINGEREICHT = "Die Änderung ist als Pull Request eingereicht. Gemergt wird nicht durch W.A.I.S."
SATZ_VERWORFEN = "Die Änderung ist verworfen."
SATZ_UNBEKANNT = "Der Server hat das Einreichen nicht bestätigt, bitte später noch einmal versuchen."
SATZ_LAEUFT = "Es läuft gerade schon ein Einreichen oder ein Lauf dieses Auftrags."
SATZ_VERALTET = eb.EINREICHEN_SAETZE["veraltet"]
SATZ_BESTAETIGUNG = eb.EINREICHEN_SAETZE["bestaetigung"]
SATZ_ZUSTAND = eb.EINREICHEN_SAETZE["zustand"]


def _text(wert: object, grenze: int) -> str:
    """Ein Text aus dem Dispatcher ohne Steuer- und Formatzeichen, gekürzt; kein Text wird leer."""
    if not isinstance(wert, str):
        return ""
    sauber = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Cs", "Zl", "Zp") else c for c in wert[: 4 * grenze])
    return " ".join(sauber.split())[:grenze]


def _zahl(wert: object) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and 0 <= wert <= ZAHL_MAX else None


def _commit(wert: object) -> str | None:
    return wert if isinstance(wert, str) and COMMIT_RE.fullmatch(wert) else None


def adresse_ok(adresse: object, repo: str | None) -> str | None:
    """Die Adresse eines Pull Requests nur in der Form https://github.com/<repo>/pull/<Nummer> mit genau diesem Repo (C.2.4)."""
    if not (isinstance(adresse, str) and repo and REPO_RE.fullmatch(repo)):
        return None
    return adresse if re.fullmatch(rf"https://github\.com/{re.escape(repo)}/pull/[0-9]{{1,9}}", adresse, re.IGNORECASE) else None


# ---------------------------------------------------------------- Kopfzeile und stdin
def kopffelder(ausnahmen: tuple[str, ...] | list[str]) -> dict[str, object]:
    """Felder der Kopfzeile von start für den persönlichen Weg (C.2.1, C.2.8): die Ausnahmen sortiert, ohne Doppel, nur aus SCOPES_AUSNAHMEN."""
    liste = sorted({s for s in ausnahmen if isinstance(s, str) and s in eb.SCOPES_AUSNAHMEN})
    return {eb.FELD_GITHUB: eb.GITHUB_PERSOENLICH, eb.FELD_SCOPES_AUSNAHMEN: liste}


def token_form_ok(token: object) -> bool:
    return isinstance(token, str) and any(m.fullmatch(token) for m in _TOKEN.values())


def github_zeile(token: str) -> bytes:
    """Die GitHub-Zeile auf stdin (C.2.2): genau diese Form, ohne Leerzeichen, Zeilenende LF. ValueError ohne den Wert im Text."""
    if not token_form_ok(token):
        raise ValueError("GitHub-Zeile: das Token hat keine bekannte Form")
    zeile = (json.dumps({"typ": "github", "wert": token}, separators=(",", ":")) + "\n").encode("utf-8")
    if len(zeile) > GITHUB_ZEILE_MAX_BYTES:
        raise ValueError("GitHub-Zeile zu lang")
    return zeile


def einreichen_zeile(commit_id: str, tree_id: str, bestaetigt: list[str], ausnahmen: tuple[str, ...] | list[str]) -> bytes:
    """Zeile 1 von einreichen (C.2.3, C.2.8): commit_id, tree_id, bestaetigt (Menge, sortiert) und scopes_ausnahmen (sortiert)."""
    if not (_commit(commit_id) and _commit(tree_id)):
        raise ValueError("einreichen: Commit oder Tree hat keine gültige Form")
    daten = {"commit_id": commit_id, "tree_id": tree_id, "bestaetigt": sorted(set(bestaetigt)),
             eb.FELD_SCOPES_AUSNAHMEN: kopffelder(ausnahmen)[eb.FELD_SCOPES_AUSNAHMEN]}
    zeile = (json.dumps(daten, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(zeile) > EINREICHEN_ZEILE_MAX_BYTES:
        raise ValueError("einreichen: Zeile zu lang")
    return zeile


# ---------------------------------------------------------------- Ereignisse
def github_info(ev: object, repo: str | None) -> dict[str, object] | None:
    """Ereignis github nach Klon und Prüfung: nur gültige Werte, das Repo muss das des Auftrags sein."""
    if not (isinstance(ev, dict) and isinstance(repo, str) and REPO_RE.fullmatch(repo) and isinstance(ev.get("repo"), str)):
        return None
    if ev["repo"].casefold() != repo.casefold():  # GitHub nennt die kanonische Schreibweise, gleich ohne Groß und Klein
        return None
    konto, basis, zweig = ev.get("konto"), _commit(ev.get("basis")), ev.get("standardzweig")
    if not (isinstance(konto, str) and LOGIN_RE.fullmatch(konto) and basis):
        return None
    zweig = zweig if isinstance(zweig, str) and ZWEIG_RE.fullmatch(zweig) and not zweig.startswith("-") and ".." not in zweig else None
    return {"repo": repo, "konto": konto, "basis": basis, "standardzweig": zweig, "privat": ev.get("privat") is True,
            "schreiben": ev.get("schreiben") is True}


@dataclass
class Aenderung:
    """Das geprüfte Ereignis aenderung eines Auftrags (C.2.4). Pfade und Titel nur für Karte und Canvas, nie für das Sprachmodell."""

    status: str
    commit_id: str | None
    tree_id: str | None
    basis: str | None
    zweig: str
    dateien: int
    plus: int
    minus: int
    markiert: list[str] = field(default_factory=list)  # sensible Pfade, je mit Kästchen auf der Karte
    pfade: list[str] = field(default_factory=list)  # alle gelisteten Pfade (sensible zuerst), nur zur Anzeige
    nicht_gelistet: int = 0
    gruende: list[str] = field(default_factory=list)  # Codes aus AENDERUNG_GRUENDE
    ungesichert: int = 0
    lauf: str | None = None
    titel: str = ""
    pr: int | None = None
    adresse: str | None = None

    def saetze(self) -> list[str]:
        return [eb.AENDERUNG_SAETZE[g] for g in self.gruende]


def aenderung_pruefen(ev: object, job_id: str, repo: str | None) -> Aenderung | None:
    """Ereignis aenderung: nur mit Job, Zweig wamo/<job> und bekanntem Status. Mit Kandidat (bereit und später) sind commit_id und tree_id
    Pflicht. Unbekannte Gründe fallen weg, Pfade werden bereinigt und auf MAX_LISTE begrenzt. None, wenn die Form nicht stimmt."""
    if not isinstance(ev, dict) or ev.get("job") != job_id:
        return None
    status = ev.get("status")
    if status not in AENDERUNG_STATUS or ev.get("zweig") != f"wamo/{job_id}":
        return None
    commit_id, tree_id = _commit(ev.get("commit_id")), _commit(ev.get("tree_id"))
    if status in ("bereit", "einreichen_laeuft", "branch_gepusht", "eingereicht") and not (commit_id and tree_id):
        return None
    markiert: list[str] = []
    pfade: list[str] = []
    liste = ev.get("liste") if isinstance(ev.get("liste"), list) else []
    for eintrag in liste[:MAX_LISTE]:
        if not isinstance(eintrag, dict) or eintrag.get("art") not in ARTEN_LISTE or eintrag.get("klasse") not in KLASSEN:
            continue
        pfad = _text(eintrag.get("pfad"), PFAD_ZEICHEN)
        if not pfad or pfad in pfade:
            continue
        pfade.append(pfad)
        if eintrag.get("klasse") == "sensibel":
            markiert.append(pfad)
    gruende = [g for g in (ev.get("gruende") if isinstance(ev.get("gruende"), list) else []) if isinstance(g, str)
               and g in eb.AENDERUNG_SAETZE]
    pr = _zahl(ev.get("pr"))
    return Aenderung(status=status, commit_id=commit_id, tree_id=tree_id, basis=_commit(ev.get("basis")), zweig=f"wamo/{job_id}",
                     dateien=_zahl(ev.get("dateien")) or 0, plus=_zahl(ev.get("plus")) or 0, minus=_zahl(ev.get("minus")) or 0,
                     markiert=markiert, pfade=pfade, nicht_gelistet=_zahl(ev.get("nicht_gelistet")) or 0,
                     gruende=list(dict.fromkeys(gruende)), ungesichert=_zahl(ev.get("ungesichert")) or 0,
                     lauf=ev.get("lauf") if ev.get("lauf") in LAUF else None, titel=_text(ev.get("titel"), TITEL_ZEICHEN),
                     pr=pr if pr else None, adresse=adresse_ok(ev.get("adresse"), repo))


def eingereicht_pruefen(ev: object, job_id: str, repo: str | None) -> tuple[int, str] | None:
    """Ereignis eingereicht: Nummer und geprüfte Adresse des Pull Requests, sonst None."""
    if not isinstance(ev, dict) or ev.get("job") != job_id or ev.get("zweig") != f"wamo/{job_id}":
        return None
    pr, adresse = _zahl(ev.get("pr")), adresse_ok(ev.get("adresse"), repo)
    if not pr or adresse is None or not adresse.endswith(f"/pull/{pr}"):
        return None
    return pr, adresse


def fehler_satz(ev: object) -> str:
    """Satz zum Ereignis einreichen_fehler (Grund aus EINREICHEN_GRUENDE oder KANAL_GRUENDE), nie ein freier Text des Dispatchers."""
    grund = ev.get("grund") if isinstance(ev, dict) else None
    if isinstance(grund, str):
        if grund in eb.EINREICHEN_SAETZE:
            return eb.EINREICHEN_SAETZE[grund]
        if grund in eb.GRUND_SAETZE:
            return eb.GRUND_SAETZE[grund]
    return SATZ_UNBEKANNT


def start_abgelehnt_satz(grund: object) -> str | None:
    """Satz zu start_abgelehnt mit einem Grund aus GITHUB_GRUENDE, sonst None (dann gilt der bisherige Weg)."""
    return eb.GITHUB_SAETZE.get(grund) if isinstance(grund, str) else None


def ereignisse(ausgabe: str) -> dict[str, dict]:
    """Die wamo-Ereignisse aus der Ausgabe eines kurzen Befehls (aenderung, einreichen, verwerfen), das letzte je Name."""
    gefunden: dict[str, dict] = {}
    for zeile in ausgabe.splitlines()[:200]:
        try:
            ev = json.loads(zeile)
        except (json.JSONDecodeError, RecursionError):
            continue
        if isinstance(ev, dict) and ev.get("type") == "wamo" and isinstance(ev.get("ereignis"), str):
            gefunden[ev["ereignis"]] = ev
    return gefunden


# ---------------------------------------------------------------- Karte
def karte(job_id: str, projekt: str, aenderung: Aenderung, info: dict | None, von: str, *, fehler: str | None = None) -> dict | None:
    """Servernachricht freigaben mit genau einem Eintrag id "einreichen" (C.6), oder None, wenn der Zustand keine Karte hat."""
    if aenderung.status not in STATUS_KARTE:
        return None
    gesperrt = aenderung.status == "gesperrt"
    nachholen = aenderung.status in ("branch_gepusht", "einreichen_laeuft")
    repo = info.get("repo") if info else None
    if gesperrt:
        grund = "Änderung lässt sich nicht einreichen"
    elif nachholen:
        grund = "Pull Request nachholen"
    else:
        grund = f"Änderung als Pull Request einreichen ({aenderung.dateien} Dateien, +{aenderung.plus} -{aenderung.minus})"
    detail = f"Repo {repo or 'unbekannt'}, Zweig {aenderung.zweig}" + (f", Konto {info['konto']}" if info else "")
    einreichen: dict[str, object] = {
        "status": aenderung.status, "repo": repo, "privat": bool(info and info.get("privat")), "zweig": aenderung.zweig,
        "konto": info.get("konto") if info else None, "commit_id": aenderung.commit_id, "tree_id": aenderung.tree_id,
        "dateien": aenderung.dateien, "plus": aenderung.plus, "minus": aenderung.minus, "markiert": list(aenderung.markiert),
        "pfade": list(aenderung.pfade[:50]), "weitere": max(0, len(aenderung.pfade) - 50) + aenderung.nicht_gelistet,
        "gesperrt": aenderung.saetze(), "ungesichert": aenderung.ungesichert, "lauf": aenderung.lauf, "titel": aenderung.titel,
        "nachholen": nachholen,
    }
    if fehler:
        einreichen["fehler"] = fehler
    return {"type": "freigaben", "job": job_id, "projekt": projekt,
            "items": [{"id": KARTE_ID, "grund": grund, "detail": detail, "von": von, "einreichen": einreichen}]}


def canvas_zeilen(aenderung: Aenderung | None, info: dict | None) -> list[str]:
    """Zeilen für den Canvas des Auftrags (Markdown): Repo, Zweig, Zustand, gesperrte Gründe, Link zum Pull Request."""
    if aenderung is None:
        return []
    zeilen = ["", "## Änderung", f"**Repo:** {info['repo'] if info else 'unbekannt'}" + (" (privat)" if info and info.get("privat") else ""),
              f"**Zweig:** `{aenderung.zweig}`", f"**Stand:** {aenderung.status}",
              f"**Dateien:** {aenderung.dateien} (+{aenderung.plus} -{aenderung.minus})"]
    zeilen += [f"- {s}" for s in aenderung.saetze()]
    if aenderung.ungesichert:
        zeilen.append(f"Nicht committet und nicht eingereicht: {aenderung.ungesichert} Dateien.")
    if aenderung.adresse:
        zeilen.append(f"**Pull Request:** {aenderung.adresse}")
    return zeilen
