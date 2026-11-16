"""Installer der Desktop-App vom Kern (Paket P2, docs/ausrollen-neue-nutzer.md, Abschnitt 4.2).

  GET /wamo/api/installer        Stand der Ablage: {"manifest": exakter Text von aktuell.json, "signatur": Base64 oder null, dazu die
                                 geprüften Felder v, produkt, version, datei, groesse, sha256, bauzeit, commit}. Keine Pfade.
  GET /wamo/api/installer/datei  genau die Datei aus dem Manifest, als Anhang mit festem Namen, Range möglich.

Ablage (nur lesen, eingesetzt von infra/sokrates2/wamo-verteilung-einrichten.sh, root:wamo-core): /var/lib/wamo-verteilung/aktuell ist ein
relativer Link auf staende/<Version>/ mit aktuell.json, optional aktuell.json.sig und WAIS-Setup-<Version>.exe.

Format von aktuell.json (Vertrag mit dem Server, dem lokalen Werkzeug und der Desktop-App, Prüfregel gleich wie
infra/sokrates2/wamo_verteilung_manifest.py, test_verteilung_api.py prüft beide gegeneinander): ein JSON-Objekt, UTF-8 ohne BOM, höchstens
4096 Byte, genau die Felder v (1), produkt ("wais-desktop"), version (Zahl.Zahl.Zahl), datei ("WAIS-Setup-<version>.exe"), groesse (1 bis
512 MiB), sha256 (64 hex klein), bauzeit (UTC mit Z), commit (40 hex klein). aktuell.json.sig: eine Zeile Base64 der 64 Byte
Ed25519-Signatur über die exakten Bytes von aktuell.json. Der Kern prüft die Signatur nicht (er ist nicht der Vertrauensanker), er reicht
sie unverändert durch; die Desktop-App prüft sie mit ihrem festen Schlüssel.

Sicherheit
  * Wie alle Routen unter /wamo/api: Token mit zweitem Faktor (aal2), Höchstalter, aktives Profil (wamo_api.identitaet; ab P1b auch die
    erledigte Erstanmeldung). Laborprofile bekommen nichts (403, zusätzlich zur Pfadliste des Labors in der Middleware).
  * Kein Name und kein Pfad vom Client. Der Link aktuell muss innerhalb von staende/ enden, Manifest und Signatur sind reguläre Dateien
    (kein Link) mit Obergrenze, die exe ist eine reguläre Datei mit genau der Größe aus dem Manifest. Vor der ersten Auslieferung eines Stands
    rechnet der Kern die SHA-256 nach (einmal je Datei, gemerkt nach Gerät, Inode, Größe und Zeit); passt sie nicht, gibt es 503.
  * Ratengrenzen je Profil und Prozess: 3 ganze Downloads je Stunde, 20 Teilabrufe je Stunde, 30 Abrufe des Manifests je Minute. Als
    Teilabruf zählt nur genau ein Bereich, der nicht bei 0 beginnt, ohne If-Range; alles andere (auch "bytes=0-", mehrere Bereiche oder
    If-Range, die die ganze Datei liefern können) zählt als ganzer Download. Gezählt wird erst, wenn die Ablage geprüft ist (ein 503
    verbraucht nichts).
  * Jeder Download bekommt eine Zeile in actions (Werkzeug installer_download, nur Version und ob Teilabruf, nie Inhalt). Fällt die Datenbank
    aus, wird trotzdem ausgeliefert (der Eintrag ist Protokoll, keine Freigabe).
  * Antworten: Cache-Control no-store, X-Content-Type-Options nosniff, Content-Disposition attachment. Fehler als JSON {"detail", "code"}:
    403 installer_labor, 429 installer_zu_oft, 503 installer_fehlt. Fehler nennen nie Pfade; das Journal nennt nur den Grund.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import stat
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

import labor
from memory import DB_ERRORS, shared_database
from wamo_api import identitaet

router = APIRouter()

ORDNER = Path("/var/lib/wamo-verteilung")
PRODUKT = "wais-desktop"
SCHLUESSEL = ("v", "produkt", "version", "datei", "groesse", "sha256", "bauzeit", "commit")
MAX_MANIFEST = 4096
MAX_GROESSE = 536_870_912
MAX_SIGNATUR = 128
WERKZEUG = "installer_download"

# Nur ASCII-Ziffern ([0-9] statt \d) und fullmatch (kein Zeilenende am Schluss), gleich wie am Server
VERSION_RE = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
BAUZEIT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z")
SIGNATUR_RE = re.compile(r"[A-Za-z0-9+/]{86}==")

DATEI_GRENZE = (3, 3600.0)      # ganze Downloads je Profil und Stunde
TEIL_GRENZE = (20, 3600.0)      # Teilabrufe (Range) je Profil und Stunde
MANIFEST_GRENZE = (30, 60.0)    # Abrufe des Manifests je Profil und Minute
_versuche: dict[tuple[str, str], deque[float]] = {}
_pruefsummen: dict[tuple, bool] = {}
PROTOKOLL_SECS = 3.0  # höchstens so lange wartet ein Download auf die Zeile in actions

CODE_LABOR = "installer_labor"
CODE_FEHLT = "installer_fehlt"
CODE_ZU_OFT = "installer_zu_oft"
SATZ_LABOR = "Im Testlabor gibt es keinen Installer."
SATZ_FEHLT = "Der Installer ist am Server gerade nicht verfügbar. Bitte melde dich bei Niko."
SATZ_ZU_OFT = "Der Installer wurde in der letzten Stunde schon dreimal geladen. Bitte versuche es später noch einmal."
KOPF = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


class AblageFehler(ValueError):
    """Die Ablage fehlt oder ist unstimmig (Grund nur fürs Journal, nie für die Antwort)."""


# ---------- Prüfregel (gleich wie infra/sokrates2/wamo_verteilung_manifest.py) ----------
class _Doppelt(ValueError):
    pass


def _ohne_doppelte(paare: list[tuple[str, object]]) -> dict:
    d: dict = {}
    for name, wert in paare:
        if name in d:
            raise _Doppelt("Feld doppelt")
        d[name] = wert
    return d


def _keine_konstante(_name: str) -> object:
    raise _Doppelt("NaN oder Infinity")


def manifest_pruefen(roh: bytes) -> dict:
    """Prüft die exakten Bytes von aktuell.json und gibt die Felder zurück. Wirft ValueError."""
    if not isinstance(roh, (bytes, bytearray)) or not roh or len(roh) > MAX_MANIFEST:
        raise ValueError("Manifest leer oder zu groß")
    roh = bytes(roh)
    if roh.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Manifest mit BOM")
    try:
        daten = json.loads(roh.decode("utf-8"), object_pairs_hook=_ohne_doppelte, parse_constant=_keine_konstante)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise ValueError("Manifest ist kein gültiges JSON") from e
    if not isinstance(daten, dict) or set(daten) != set(SCHLUESSEL):
        raise ValueError("Manifest hat nicht genau die erwarteten Felder")
    if type(daten["v"]) is not int or daten["v"] != 1 or daten["produkt"] != PRODUKT:
        raise ValueError("v oder produkt falsch")
    version = daten["version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version) or daten["datei"] != f"WAIS-Setup-{version}.exe":
        raise ValueError("version oder datei falsch")
    if type(daten["groesse"]) is not int or not 1 <= daten["groesse"] <= MAX_GROESSE:
        raise ValueError("groesse falsch")
    for feld, muster in (("sha256", SHA256_RE), ("bauzeit", BAUZEIT_RE), ("commit", COMMIT_RE)):
        if not isinstance(daten[feld], str) or not muster.fullmatch(daten[feld]):
            raise ValueError(f"{feld} falsch")
    return {n: daten[n] for n in SCHLUESSEL}


def signatur_pruefen(roh: bytes) -> str:
    """Inhalt von aktuell.json.sig ohne Zeilenende (eine Zeile Base64 für 64 Byte, kanonisch). Wirft ValueError."""
    if len(roh) > MAX_SIGNATUR:
        raise ValueError("Signatur zu groß")
    if roh.endswith(b"\n"):
        roh = roh[:-1]
    try:
        text = roh.decode("ascii")
    except UnicodeDecodeError as e:
        raise ValueError("Signatur nicht ASCII") from e
    if not SIGNATUR_RE.fullmatch(text) or base64.b64encode(base64.b64decode(text, validate=True)).decode("ascii") != text:
        raise ValueError("Signatur nicht im Format")
    return text


# ---------- Ablage lesen ----------
@dataclass(frozen=True)
class Stand:
    manifest_text: str
    felder: dict
    signatur: str | None
    exe: Path
    exe_stat: os.stat_result


def _regulaer_lesen(pfad: Path, grenze: int) -> bytes:
    """Liest eine reguläre Datei (kein Link) mit höchstens grenze Byte. Wirft FileNotFoundError oder AblageFehler."""
    if stat.S_ISLNK(os.lstat(pfad).st_mode):
        raise AblageFehler(f"{pfad.name} ist ein Link")
    fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise AblageFehler(f"{pfad.name} ist keine reguläre Datei")
        roh = f.read(grenze + 1)
    if len(roh) > grenze:
        raise AblageFehler(f"{pfad.name} ist zu groß")
    return roh


def stand_lesen(ordner: Path | None = None) -> Stand:
    """Der ausgelieferte Stand der Ablage, ohne die Prüfsumme der exe. Wirft AblageFehler."""
    basis = Path(ordner if ordner is not None else ORDNER)
    try:
        staende = Path(os.path.realpath(basis / "staende"))
        ziel = Path(os.path.realpath(basis / "aktuell"))
        if ziel.parent != staende or not ziel.is_dir():
            raise AblageFehler("aktuell zeigt nicht auf einen Stand in staende/")
        manifest_roh = _regulaer_lesen(ziel / "aktuell.json", MAX_MANIFEST)
        try:
            felder = manifest_pruefen(manifest_roh)
        except ValueError as e:
            raise AblageFehler(f"Manifest: {e}") from None
        if ziel.name != felder["version"]:
            raise AblageFehler("Ordner und Version passen nicht zusammen")
        try:
            signatur = signatur_pruefen(_regulaer_lesen(ziel / "aktuell.json.sig", MAX_SIGNATUR))
        except FileNotFoundError:
            signatur = None
        except ValueError as e:
            raise AblageFehler(f"Signaturdatei: {e}") from None
        exe = ziel / felder["datei"]
        st = os.lstat(exe)
        if not stat.S_ISREG(st.st_mode):
            raise AblageFehler("die Installationsdatei ist keine reguläre Datei")
        if st.st_size != felder["groesse"]:
            raise AblageFehler("die Größe der Installationsdatei passt nicht zum Manifest")
    except FileNotFoundError:
        raise AblageFehler("Ablage oder Datei fehlt") from None
    except OSError as e:
        raise AblageFehler(f"Ablage nicht lesbar ({type(e).__name__})") from None
    return Stand(manifest_roh.decode("utf-8"), felder, signatur, exe, st)


def _sha256_datei(pfad: Path) -> str:
    h = hashlib.sha256()
    fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


async def _pruefsumme_stimmt(s: Stand) -> bool:
    """SHA-256 der exe wie im Manifest? Einmal je Datei gerechnet (in einem Thread), dann gemerkt. Ohne Sperre: Laufen zwei erste
    Abrufe gleichzeitig, rechnen beide (selten, nur direkt nach dem Einsetzen); eine Sperre auf Modulebene hinge an einer Ereignisschleife."""
    st = s.exe_stat
    schluessel = (str(s.exe), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, s.felder["sha256"])
    if schluessel in _pruefsummen:
        return _pruefsummen[schluessel]
    try:
        ok = await asyncio.to_thread(_sha256_datei, s.exe) == s.felder["sha256"]
    except OSError as e:
        logger.error("Installer: {} nicht lesbar ({}), nichts ausgeliefert", s.felder["datei"], type(e).__name__)
        return False
    if not ok:
        logger.error("Installer: SHA-256 von {} passt nicht zum Manifest, nichts ausgeliefert", s.felder["datei"])
    if len(_pruefsummen) > 16:
        _pruefsummen.clear()
    _pruefsummen[schluessel] = ok
    return ok


async def _stand_geprueft() -> Stand | None:
    try:
        s = await asyncio.to_thread(stand_lesen)
    except AblageFehler as e:
        logger.warning("Installer: Ablage nicht nutzbar ({})", e)
        return None
    return s if await _pruefsumme_stimmt(s) else None


TEIL_RE = re.compile(r"bytes=([1-9][0-9]{0,11})-([0-9]{0,12})")


def ist_teilabruf(request: Request) -> bool:
    """Nur genau ein Bereich, der nicht bei 0 beginnt, und kein If-Range zählt als Teilabruf. Alles andere kann die ganze Datei liefern
    (bytes=0-, mehrere Bereiche, ein nicht passendes If-Range) und zählt deshalb als ganzer Download."""
    werte = request.headers.getlist("range")
    return len(werte) == 1 and "if-range" not in request.headers and TEIL_RE.fullmatch(werte[0].strip()) is not None


# ---------- Grenzen, Antworten, Protokoll ----------
def _zulassen(user_id: str, art: str, grenze: tuple[int, float], jetzt: float | None = None) -> bool:
    anzahl, fenster = grenze
    jetzt = time.monotonic() if jetzt is None else jetzt
    q = _versuche.setdefault((user_id, art), deque())
    while q and jetzt - q[0] > fenster:
        q.popleft()
    if len(q) >= anzahl:
        return False
    q.append(jetzt)
    if len(_versuche) > 500:  # abgelaufene Profile aufräumen
        for k in [k for k, d in _versuche.items() if not d or jetzt - d[-1] > DATEI_GRENZE[1]]:
            del _versuche[k]
    return True


def _fehler(status: int, satz: str, code: str) -> JSONResponse:
    return JSONResponse({"detail": satz, "code": code}, status_code=status, headers=KOPF)


async def _protokollieren(user_id: str, version: str, teil: bool) -> None:
    """Zeile in actions (Werkzeug installer_download, Status done, ohne Inhalt). Wirft nie."""
    try:
        db = shared_database()
        if not db.configured:
            return
        async with asyncio.timeout(PROTOKOLL_SECS):
            await db.execute(
                f"insert into {db.t('actions')} (user_id, tool, params, reason, risk, status, result, finished_at) "
                f"values ($1::uuid, $2, $3::text::jsonb, $4, 'read'::{db.t('risk_class')}, 'done'::{db.t('action_status')}, "
                "'{}'::jsonb, now())",
                user_id, WERKZEUG, json.dumps({"version": version, "teil": teil}), "Installer der Desktop-App geladen",
            )
    except (*DB_ERRORS, TimeoutError, ValueError, TypeError) as e:
        logger.warning("Installer: Download nicht in actions protokolliert ({})", type(e).__name__)


# ---------- Routen ----------
@router.get("/installer")
async def installer(request: Request):
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _fehler(403, SATZ_LABOR, CODE_LABOR)
    if not _zulassen(ich.user_id, "manifest", MANIFEST_GRENZE):
        return _fehler(429, "Zu viele Anfragen, bitte in einer Minute noch einmal.", CODE_ZU_OFT)
    s = await _stand_geprueft()
    if s is None:
        return _fehler(503, SATZ_FEHLT, CODE_FEHLT)
    return JSONResponse({**s.felder, "manifest": s.manifest_text, "signatur": s.signatur}, headers=KOPF)


@router.get("/installer/datei")
async def installer_datei(request: Request):
    ich = await identitaet(request)
    if labor.ist_labor(ich):
        return _fehler(403, SATZ_LABOR, CODE_LABOR)
    s = await _stand_geprueft()
    if s is None:
        return _fehler(503, SATZ_FEHLT, CODE_FEHLT)
    teil = ist_teilabruf(request)
    if not _zulassen(ich.user_id, "teil" if teil else "datei", TEIL_GRENZE if teil else DATEI_GRENZE):
        return _fehler(429, SATZ_ZU_OFT, CODE_ZU_OFT)
    await _protokollieren(ich.user_id, s.felder["version"], teil)
    logger.info("Installer {} an Profil {} ({})", s.felder["version"], ich.user_id[:8], "Teil" if teil else "ganz")
    return FileResponse(s.exe, media_type="application/octet-stream", filename=s.felder["datei"], stat_result=s.exe_stat,
                        headers=KOPF)
