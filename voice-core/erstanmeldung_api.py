"""Erstanmeldung (Ausrollen P1b, Zweig A): Stand der Erstanmeldung und Wechsel des Startpassworts.

  GET  /wamo/api/erstanmeldung            {"stand": "keine" | "offen" | "abgelaufen" | "erledigt", "mindestlaenge": 12}
  POST /wamo/api/erstanmeldung/passwort   Body {"passwort": "<neu>"}, Antwort {"stand": <Stand nach dem Wechsel oder null>}

Das sind die einzigen Wege, die ein Profil im Stand offen oder abgelaufen erreicht (auth_gate.erstanmeldung_pfad, exakt über raw_path,
ohne Query). Die Oberfläche fragt den Stand nach aal2 (LoginGate) und nach dem Passwortwechsel erneut ab.

Allgemein
  * Anmeldung wie bei allen Routen, aber mit identitaet(request, weg_frei=True): nur hier gilt die Sperre nicht.
  * Laborprofile: 403. Die Middleware lässt sie nie bis hierher (die Pfadliste in labor.py bleibt unverändert); ihr Stand wird nie gelesen.
  * Vor dem Lesen vergisst die Zugangskontrolle den gecachten Stand dieses Profils: nach dem Wechsel gilt "erledigt" sofort.
  * Alle Antworten mit Cache-Control: no-store; Fehler als {"detail": <Satz>, "code": <Code>}. Lehnt schon die Anmeldung ab, ist der
    Code der der Zugangskontrolle, sonst nicht_angemeldet (401), nicht_berechtigt (403) oder nicht_pruefbar (503).

GET: Ratengrenze je Profil (30 Abfragen in 10 Minuten, im Prozess), sonst 429 zu_oft. Im Stand offen vermerkt
wamo_auth.erstanmeldung_begonnen den Beginn (einmal; die Datenbank schickt selbst den Hinweis an die Admins), höchstens 2 Sekunden;
Fehler dort werden nur geloggt. Fehlen Schema, Funktion oder Recht oder ist die Datenbank weg: 503 nicht_pruefbar (fail-closed).

POST (Passwortwechsel über den Kern): Caddy auf 55443 weist jedes PUT und PATCH auf .../auth/.../user ab (Laborschutz), der Browser
kann den Wechsel also nicht selbst an GoTrue schicken. Der Kern reicht ihn weiter, aber nur im Stand offen:
  * Ratengrenze je Profil (5 Versuche in 10 Minuten, im Prozess; jeder Versuch zählt, auch ein abgelehnter): sonst 429 zu_oft.
  * Body höchstens 1024 Bytes (413 zu_gross). Passwort als Text mit mindestens 12 Zeichen und höchstens 72 Bytes in UTF-8 (bcrypt nimmt
    höchstens 72): sonst 400 passwort_ungueltig. Stand abgelaufen 403 startpasswort_abgelaufen, keine oder erledigt 409 kein_wechsel_noetig.
  * PUT {WAMO_GOTRUE_INTERN_URL}/auth/v1/user (Standard http://127.0.0.1:55321, der Envoy des Stacks; erlaubt nur http über Loopback
    oder https zum Host aus SUPABASE_URL, sonst 503) mit dem Authorization-Kopf der Anfrage (unverändert) und apikey =
    SUPABASE_PUBLISHABLE_KEY. Gesamtzeitlimit 10 s, kein Proxy aus der Umgebung, keine Umleitung. GoTrue prüft selbst aal2 und
    Mindestlänge; wechselt die Person ihr Passwort, beendet GoTrue alle anderen Sitzungen.
  * Von der Antwort liest der Kern nur Status und error_code (abbilden), nie den Text. Das Passwort steht in keiner Logzeile und in keiner
    Antwort; das Log nennt nur die gekürzte Profilkennung und das Ergebnis. Ausnahmen werden nur mit ihrem Typ geloggt; der eigentliche
    Schutz gegen Werte lokaler Variablen in Tracebacks ist diagnose=False in der Logkonfiguration des Kerns (bot.py), und
    test_erstanmeldung.py prüft mit einem Mitschnitt aller Logzeilen, dass das Passwort nirgends erscheint.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

import labor
import labor_limit
from auth_gate import CODE_STARTPASSWORT_ABGELAUFEN, ERSTANMELDUNG_SPERRE, GRUND_ERSTANMELDUNG, AccessGate
from wamo_api import gate_holen, identitaet, lies_bytes
from wamo_tls import https_context

router = APIRouter()

MINDESTLAENGE = 12  # Zeichen, wie GOTRUE_PASSWORD_MIN_LENGTH; die Admin-Schnittstelle von GoTrue prüft die Länge nicht
KOPF = {"Cache-Control": "no-store"}

PASSWORT_MAX_BODY = 1024
PASSWORT_MAX_BYTES = 72  # bcrypt
VERSUCHE_MAX, VERSUCHE_SECS = 5, 600.0  # POST je Profil
ABFRAGEN_MAX, ABFRAGEN_SECS = 30, 600.0  # GET je Profil
GOTRUE_INTERN_STANDARD = "http://127.0.0.1:55321"
GOTRUE_ZEIT_SECS = 10.0  # die ganze Weiterleitung, nicht nur einzelne Schritte
BEGONNEN_ZEIT_SECS = 2.0
LOOPBACK = ("127.0.0.1", "::1", "localhost")
ERSATZ_CODES = {401: "nicht_angemeldet", 403: "nicht_berechtigt"}  # sonst nicht_pruefbar

SAETZE = {
    "zu_oft": "Zu viele Versuche. Bitte warte ein paar Minuten.",
    "zu_gross": "Anfrage zu groß.",
    "passwort_ungueltig": f"Das neue Passwort braucht mindestens {MINDESTLAENGE} Zeichen und darf höchstens {PASSWORT_MAX_BYTES} Bytes "
                          "lang sein.",
    "kein_wechsel_noetig": "Dein Passwort muss nicht mehr geändert werden.",
    CODE_STARTPASSWORT_ABGELAUFEN: ERSTANMELDUNG_SPERRE["abgelaufen"][1],
    "same_password": "Das neue Passwort muss sich vom Startpasswort unterscheiden.",
    "weak_password": "Das Passwort ist zu schwach. Bitte wähle ein längeres Passwort.",
    "insufficient_aal": "Bitte bestätige zuerst den Code deiner Authenticator-App.",
    "reauthentication_needed": "Bitte melde dich neu an.",
    "sitzung_ungueltig": "Deine Anmeldung gilt nicht mehr. Bitte melde dich neu an.",
    "anmeldedienst": "Der Anmeldedienst ist gerade nicht erreichbar. Bitte versuche es später noch einmal.",
    "nicht_pruefbar": GRUND_ERSTANMELDUNG,
    labor.CODE_PFAD_GESPERRT: "Dieser Weg ist für dieses Profil gesperrt.",
}

_versuche = labor_limit.AnfragenFenster(VERSUCHE_MAX, VERSUCHE_SECS)
_abfragen = labor_limit.AnfragenFenster(ABFRAGEN_MAX, ABFRAGEN_SECS)
_transport: httpx.AsyncBaseTransport | None = None  # nur für Tests


def _antwort(status: int, code: str, detail: str | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail or SAETZE[code], "code": code}, status_code=status, headers=KOPF)


def _abgelehnt(e: HTTPException) -> JSONResponse:
    """Ablehnung aus identitaet als JSON mit Code (der der Zugangskontrolle oder einer nach dem Status) und no-store."""
    code = getattr(e, "code", None) or ERSATZ_CODES.get(e.status_code, "nicht_pruefbar")
    return _antwort(e.status_code, code, str(e.detail))


def _host(url: str | None) -> str | None:
    try:
        return urlsplit((url or "").strip()).hostname or None
    except ValueError:
        return None


def gotrue_url(roh: str | None, supabase_url: str | None) -> str | None:
    """Adresse von PUT /auth/v1/user aus WAMO_GOTRUE_INTERN_URL (leer: Standard). Nur http mit Host 127.0.0.1, ::1 oder localhost oder
    https mit dem Host aus SUPABASE_URL (dem eigenen Stack); ohne Zugangsdaten, Pfad, Query und Fragment. Sonst None (503)."""
    wert = (roh or "").strip() or GOTRUE_INTERN_STANDARD
    try:
        teile = urlsplit(wert)
        teile.port  # noqa: B018 (wirft bei einem ungültigen Port)
    except ValueError:
        return None
    host = teile.hostname or ""
    if "@" in teile.netloc or teile.path not in ("", "/") or teile.query or teile.fragment or "?" in wert or "#" in wert:
        return None
    stack = _host(supabase_url)
    if not ((teile.scheme == "https" and host and host == stack) or (teile.scheme == "http" and host in LOOPBACK)):
        return None
    return f"{teile.scheme}://{teile.netloc}/auth/v1/user"


def passwort_aus(roh: bytes) -> str | None:
    """Das neue Passwort aus dem Body oder None: Text mit mindestens MINDESTLAENGE Zeichen (Codepunkten) und höchstens
    PASSWORT_MAX_BYTES Bytes in UTF-8. Keine Ausnahme verlässt diese Funktion (sie trügen den Wert in sich)."""
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    passwort = daten.get("passwort") if isinstance(daten, dict) else None
    if not isinstance(passwort, str):
        return None
    try:
        laenge = len(passwort.encode("utf-8"))
    except UnicodeEncodeError:  # einzelne Surrogate aus dem JSON
        return None
    return passwort if len(passwort) >= MINDESTLAENGE and laenge <= PASSWORT_MAX_BYTES else None


def abbilden(status: int, fehlercode: str | None) -> tuple[int, str] | None:
    """Antwort von GoTrue (nur Status und error_code) auf Status und Code des Kerns. None heißt Erfolg."""
    if status == 200:
        return None
    if fehlercode == "reauthentication_needed" and status in (400, 401):
        return 401, "reauthentication_needed"
    if status == 422 and fehlercode in ("same_password", "weak_password"):
        return 422, fehlercode
    if status == 401 and fehlercode == "insufficient_aal":
        return 401, "insufficient_aal"
    if status == 401 or (status == 403 and fehlercode == "session_not_found"):
        return 401, "sitzung_ungueltig"
    return 502, "anmeldedienst"


async def _gotrue_put(url: str, autorisierung: str, apikey: str, passwort: str) -> tuple[int, str | None]:
    """PUT an GoTrue. Liefert Status und error_code; den Text der Antwort liest niemand weiter."""
    inhalt = json.dumps({"password": passwort}).encode("ascii")
    verify = (https_context() or True) if url.startswith("https://") else True
    async with httpx.AsyncClient(timeout=GOTRUE_ZEIT_SECS, transport=_transport, verify=verify, follow_redirects=False,
                                 trust_env=False) as client:
        antwort = await client.put(url, content=inhalt, headers={"Authorization": autorisierung, "apikey": apikey,
                                                                 "Content-Type": "application/json"})
    try:
        daten = antwort.json()
    except (ValueError, RecursionError):
        daten = None
    fehlercode = daten.get("error_code") if isinstance(daten, dict) else None
    return antwort.status_code, fehlercode if isinstance(fehlercode, str) else None


async def _stand_frisch(gate: AccessGate, user_id: str) -> str:
    gate.stand_vergessen(user_id)
    return await gate.erstanmeldung_stand(user_id)  # meldet fehlendes wamo_auth selbst im Log


async def _begonnen(gate: AccessGate, user_id: str) -> None:
    """Beginn der Erstanmeldung vermerken, höchstens BEGONNEN_ZEIT_SECS. Jeder Fehler wird nur geloggt (nie mit Datenbankmeldung)."""
    try:
        if await asyncio.wait_for(gate.begonnen(user_id), BEGONNEN_ZEIT_SECS):
            logger.info("Erstanmeldung begonnen: Profil {}…", user_id[:8])
    except Exception as e:  # noqa: BLE001 (der Vermerk darf die Antwort nie aufhalten)
        logger.warning("Erstanmeldung: Beginn nicht vermerkt, erstanmeldung_begonnen fehlgeschlagen ({})", type(e).__name__)


@router.get("/erstanmeldung", response_model=None)
async def erstanmeldung(request: Request) -> JSONResponse:
    try:
        ich = await identitaet(request, weg_frei=True)
    except HTTPException as e:
        return _abgelehnt(e)
    if labor.ist_labor(ich):
        return _antwort(403, labor.CODE_PFAD_GESPERRT)
    gate = gate_holen()
    if gate is None:
        return _antwort(503, "nicht_pruefbar")
    if not _abfragen.zulassen(ich.user_id):
        logger.warning("Erstanmeldung: Abfrage des Stands für Profil {}… abgelehnt (zu_oft)", ich.user_id[:8])
        return _antwort(429, "zu_oft")
    try:
        stand = await _stand_frisch(gate, ich.user_id)
    except Exception as e:  # noqa: BLE001 (fail-closed: jeder Fehler heißt 503)
        logger.warning("Erstanmeldung: Stand nicht lesbar ({})", type(e).__name__)
        return _antwort(503, "nicht_pruefbar")
    if stand == "offen":
        await _begonnen(gate, ich.user_id)
    return JSONResponse({"stand": stand, "mindestlaenge": MINDESTLAENGE}, headers=KOPF)


@router.post("/erstanmeldung/passwort", response_model=None)
async def passwort_wechseln(request: Request) -> JSONResponse:
    try:
        ich = await identitaet(request, weg_frei=True)
    except HTTPException as e:
        return _abgelehnt(e)
    kurz = ich.user_id[:8]
    if labor.ist_labor(ich):
        return _antwort(403, labor.CODE_PFAD_GESPERRT)
    gate = gate_holen()
    url = gotrue_url(os.getenv("WAMO_GOTRUE_INTERN_URL"), os.getenv("SUPABASE_URL"))
    apikey = (os.getenv("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if gate is None or url is None or not apikey:
        logger.error("Erstanmeldung: Passwortwechsel nicht eingerichtet (WAMO_GOTRUE_INTERN_URL, SUPABASE_URL oder SUPABASE_PUBLISHABLE_KEY)")
        return _antwort(503, "anmeldedienst", "Der Passwortwechsel ist auf diesem Server nicht eingerichtet.")
    if not _versuche.zulassen(ich.user_id):
        logger.warning("Erstanmeldung: Passwortwechsel für Profil {}… abgelehnt (zu_oft)", kurz)
        return _antwort(429, "zu_oft")
    try:
        roh = await lies_bytes(request, PASSWORT_MAX_BODY)
    except HTTPException:
        return _antwort(413, "zu_gross")
    try:
        stand = await _stand_frisch(gate, ich.user_id)
    except Exception as e:  # noqa: BLE001 (fail-closed)
        logger.warning("Erstanmeldung: Stand nicht lesbar ({})", type(e).__name__)
        return _antwort(503, "nicht_pruefbar")
    if stand == "abgelaufen":
        return _antwort(403, CODE_STARTPASSWORT_ABGELAUFEN)
    if stand != "offen":
        return _antwort(409, "kein_wechsel_noetig")
    passwort = passwort_aus(roh)
    if passwort is None:
        logger.info("Erstanmeldung: Passwortwechsel für Profil {}… abgelehnt (passwort_ungueltig)", kurz)
        return _antwort(400, "passwort_ungueltig")
    try:
        async with asyncio.timeout(GOTRUE_ZEIT_SECS):
            status, fehlercode = await _gotrue_put(url, request.headers.get("authorization", ""), apikey, passwort)
    except Exception as e:  # noqa: BLE001 (Netz, Zeitlimit, TLS: nur der Fehlertyp ins Log)
        logger.warning("Erstanmeldung: Passwortwechsel für Profil {}… gescheitert (anmeldedienst, {})", kurz, type(e).__name__)
        return _antwort(502, "anmeldedienst")
    if (abbild := abbilden(status, fehlercode)) is not None:
        logger.warning("Erstanmeldung: Passwortwechsel für Profil {}… abgelehnt ({}, GoTrue {})", kurz, abbild[1], status)
        return _antwort(*abbild)
    try:
        neu: str | None = await _stand_frisch(gate, ich.user_id)
    except Exception as e:  # noqa: BLE001 (das Passwort ist gewechselt; die Oberfläche holt den Stand ohnehin neu)
        logger.warning("Erstanmeldung: Stand nach dem Wechsel nicht lesbar ({})", type(e).__name__)
        neu = None
    logger.info("Erstanmeldung: Passwort für Profil {}… gewechselt, Stand {}", kurz, neu)
    return JSONResponse({"stand": neu}, headers=KOPF)
