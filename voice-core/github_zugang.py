"""Persönlicher GitHub-Zugang je Profil für Entwicklungsaufträge (Plan C, docs/persoenliche-zugaenge.md C.3, C.4, C.7; Migration 0027).

Die Person hinterlegt ihr eigenes GitHub-Token (fein-granular github_pat_ oder klassisch ghp_) einmal in der Oberfläche. Der Kern prüft es
sofort bei GitHub (GET /user, Zeitlimit 10 s, keine Weiterleitung), speichert es nur als Chiffrat (AES-256-GCM mit WAMO_SCHLUESSEL_KEK,
Zweck schluessel.GITHUB) und gibt danach nur Art, Login, Rechte, Ablauf und die letzten vier Zeichen zurück, nie den Wert. Für genau einen
Aufruf des Dispatchers entschlüsselt github_zugang_fuer() das Token frisch; der Wert steht in keinem Objekt, keinem Log, nie in actions,
turns oder im Gedächtnis.

Regeln beim Speichern (C5, C.4, C.2.8 und Entscheidung vom 18.11.2026):
  * Form nach entwicklung_betrieb.GITHUB_TOKEN_FORMEN (ghp_ plus 36 Zeichen, github_pat_ plus 82 Zeichen); gho_, ghu_, ghs_ und ghr_ werden
    mit eigenem Satz abgewiesen.
  * GitHub antwortet mit 200, login, id und type User; 401 heißt ungültig.
  * Ablauf (Kopfzeile GitHub-Authentication-Token-Expiration) ist Pflicht, liegt in der Zukunft und höchstens GITHUB_ABLAUF_MAX_TAGE entfernt.
  * Klassisch: die Erlaubnisliste aus C.2.8 (Schnittstelle Paket S, Listen in entwicklung_betrieb.py). Ein Scope aus SCOPES_PFLICHT_EINER
    ist Pflicht, jeder Scope muss in SCOPES_UNBEDENKLICH oder in den Ausnahmen der Person stehen, höchstens SCOPES_MAX; ein Scope, den keine
    Liste kennt, ist abgelehnt. Die Ausnahmen setzt nur ein Admin je Person (Tabelle github_rechte, Admin-Route in github_zugang_api.py),
    nur aus SCOPES_AUSNAHMEN, nie aus SCOPES_NIE. Der Dispatcher prüft bei jedem Start und Einreichen dieselbe Regel mit den Ausnahmen, die
    der Kern im Feld scopes_ausnahmen mitschickt (sortiert, rechte_laden).
  * Fein-granular: keine Scopes in diesem Sinn; die Karte nennt, welche Rechte am Repo nötig sind.

Wer darf: nur Profile mit Zulassung für Entwicklungsaufträge im Büro (entwicklung_betrieb.zulassung_fuer), nie Laborprofile (die Erlaubnis-
listen in labor.py nennen weder Pfad noch Nachricht, dieses Modul lehnt zusätzlich ab, die Datenbank auch). Alles steht hinter dem Schalter
WAMO_ENTWICKLUNG_GITHUB (entwicklung_betrieb.github_schalter, Standard aus); Löschen geht immer. Je Profil und Prozess höchstens 5 Prüfungen
bei GitHub in 10 Minuten.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
from loguru import logger

import entwicklung_betrieb as eb
from memory import DB_ERRORS, Database, DatabaseUnavailable, normalize_uuid, shared_database
from schluessel import GITHUB, SchluesselFehler, Tresor, ende

ENV_SCHALTER = eb.ENV_GITHUB
ART_FEIN, ART_KLASSISCH = "fein", "klassisch"
ARTEN = (ART_FEIN, ART_KLASSISCH)
_FORMEN = {art: re.compile(muster) for art, muster in eb.GITHUB_TOKEN_FORMEN.items()}
_FREMDE_ART = re.compile(r"gh[ousr]_[A-Za-z0-9_]{8,}")
LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
SCOPE_RE = re.compile(r"[a-z][a-z0-9_:]{0,39}")  # Form jedes bekannten Scopes (Prüfregel der Spalte scopes in 0027)
API_URL = "https://api.github.com"
PRUEF_TIMEOUT_SECS = 10.0
ANTWORT_MAX_BYTES = 256 * 1024
ABLAUF_MAX_TAGE = eb.GITHUB_ABLAUF_MAX_TAGE
# GitHub legt das Ende auf das Tagesende in der Zeitzone der Person; ein Token mit genau 366 Tagen liegt deshalb bis zu einem Tag darüber
ABLAUF_TOLERANZ = timedelta(days=1)
VERSUCHE_JE_FENSTER = 5
VERSUCHE_FENSTER_SECS = 600.0
RECHTE_JE_FENSTER = 20  # Änderungen der Rechte je Admin im Zeitfenster
AKTIONEN = ("stand", "speichern", "pruefen", "loeschen")
WERKZEUG = "github_zugang"  # Zeile in actions je Speichern, Prüfen und Löschen (nie der Wert)
WERKZEUG_RECHTE = "github_rechte"  # Zeile in actions je Änderung der erlaubten Rechte durch einen Admin

# ---------- Rechte klassischer Tokens (C.2.8; die Listen gehören der Schnittstelle, hier nur Kurznamen) ----------
SCOPES_PFLICHT = eb.SCOPES_PFLICHT_EINER
SCOPES_UNBEDENKLICH = eb.SCOPES_UNBEDENKLICH
SCOPES_AUSNAHMEN = eb.SCOPES_AUSNAHMEN  # dieselbe Liste steht in der Migration 0027 (github_rechte_liste_chk)
SCOPES_NIE = eb.SCOPES_NIE
MAX_SCOPES = eb.SCOPES_MAX

SATZ_SCHALTER_AUS = "Persönliche GitHub-Zugänge sind noch nicht eingeschaltet."
SATZ_NICHT_ZUGELASSEN = "Entwicklungsaufträge mit eigenem GitHub-Zugang sind für dein Profil nicht freigegeben."
SATZ_LABOR = "Im Labor gibt es keine GitHub-Zugänge."
SATZ_FEIN_RECHTE = ("Fein-granulares Token: Nötig sind Contents (lesen und schreiben), Pull requests (lesen und schreiben) und Metadata "
                    "(lesen). Bitte keine weiteren Rechte vergeben, besonders nicht Administration, Secrets und Workflows; GitHub zeigt "
                    "W.A.I.S. diese Rechte nicht an.")
SATZ_NICHT_EINGERICHTET = ("Persönliche GitHub-Zugänge sind in dieser Datenbank noch nicht eingerichtet (Migration 0027); "
                           "bitte an den Admin wenden.")

_versuche: dict[str, list[float]] = {}
_rechte_versuche: dict[str, list[float]] = {}


class ZugangFehler(Exception):
    """Speichern, Prüfen oder Löschen geht nicht. Der Text ist für die Person gedacht und enthält nie das Token."""


# ---------- Schalter und Zulassung ----------
def schalter() -> str:
    """WAMO_ENTWICKLUNG_GITHUB als "an", "aus" (Standard) oder "ungueltig" (entwicklung_betrieb.github_schalter)."""
    return eb.github_schalter()


def schalter_an() -> bool:
    return eb.github_an()


def _ist_labor(identity: object) -> bool:
    import labor

    return labor.ist_labor(identity)


def verfuegbar_grund(identity: object) -> str | None:
    """Warum Speichern und Prüfen für diese geprüfte Identität nicht gehen (Labor, Schalter, Zulassung), sonst None."""
    if _ist_labor(identity):
        return SATZ_LABOR
    if not schalter_an():
        return SATZ_SCHALTER_AUS
    if eb.zulassung_fuer(identity) is None:
        return SATZ_NICHT_ZUGELASSEN
    return None


# ---------- Formen, Rechte, Ablauf ----------
def art_von(token: object) -> str:
    """ART_KLASSISCH oder ART_FEIN, wenn das Token die Form hat; sonst ZugangFehler (ohne das Token im Text)."""
    wert = token.strip() if isinstance(token, str) else ""
    for art, muster in _FORMEN.items():
        if muster.fullmatch(wert):
            return art
    if _FREMDE_ART.fullmatch(wert):
        raise ZugangFehler("Das ist kein persönliches Zugriffstoken (es gehört zu einer App oder einer Anmeldung). Bitte ein "
                           "fein-granulares Token (github_pat_) oder ein klassisches Token (ghp_) erzeugen.")
    raise ZugangFehler("Das ist kein GitHub-Token: Es beginnt mit github_pat_ (fein-granular) oder ghp_ (klassisch).")


def standard_abgelehnt(scope: str) -> bool:
    """Gilt dieses Recht im strengen Standard als abgelehnt (also nicht in SCOPES_UNBEDENKLICH, auch jeder unbekannte Scope)?"""
    return scope not in SCOPES_UNBEDENKLICH


def ausnahmen_normal(werte: object) -> tuple[str, ...]:
    """Erlaubte Ausnahmen einer Person aus der Datenbank, noch einmal gegen SCOPES_AUSNAHMEN geprüft, ohne Doppel, sortiert (so gehen sie
    auch im Feld scopes_ausnahmen an den Dispatcher). Alles andere fällt weg."""
    menge = {w for w in werte if isinstance(w, str)} if isinstance(werte, (list, tuple, set, frozenset)) else set()
    return tuple(sorted(s for s in menge if s in SCOPES_AUSNAHMEN and s not in SCOPES_NIE))


def scopes_lesen(kopf: str | None) -> tuple[str, ...]:
    """X-OAuth-Scopes wie in C.2.8: am Komma getrennt, Leerzeichen am Rand weg, leere Einträge übergangen, Groß- und Kleinschreibung
    zählt. Ob die Werte erlaubt sind, entscheidet scopes_problem. Fehlt die Kopfzeile, ZugangFehler (nie stillschweigend leer)."""
    if kopf is None:
        raise ZugangFehler("GitHub nennt die Rechte des Tokens nicht; ein klassisches Token lässt sich so nicht prüfen.")
    return tuple(s.strip(" ") for s in kopf.split(",") if s.strip(" "))


def _namen(scopes: Iterable[str]) -> str:
    """Höchstens fünf Scopes für einen Satz; was nicht wie ein Scope aussieht, nur als Hinweis (Werte von GitHub nie ungeprüft)."""
    liste = list(dict.fromkeys(scopes))
    lesbar = [s for s in liste if SCOPE_RE.fullmatch(s)][:5]
    rest = len(liste) - len(lesbar)
    if not lesbar:
        return "eine unbekannte Angabe"
    return ", ".join(lesbar) + (f" und {rest} weitere" if rest > 0 else "")


def scopes_problem(scopes: Iterable[str], ausnahmen: Iterable[str] = ()) -> str | None:
    """Die Regel aus C.2.8 als Satz für die Person, sonst None: dieselbe Entscheidung wie token_rechte im Dispatcher (geprüft gegen
    SCOPE_FAELLE in test_kernkanal_vertrag.py). ausnahmen: die vom Admin erlaubten Scopes der Person."""
    liste = tuple(scopes)
    erlaubt = set(SCOPES_UNBEDENKLICH) | set(ausnahmen_normal(tuple(ausnahmen)))
    if len(liste) > MAX_SCOPES:
        return f"Das Token hat mehr als {MAX_SCOPES} Rechte. Bitte ein Token nur mit repo (oder public_repo) erzeugen."
    if not set(liste) & set(SCOPES_PFLICHT):
        return "Das Token braucht das Recht repo (oder public_repo, wenn nur öffentliche Repos gemeint sind)."
    nie = [s for s in liste if s in SCOPES_NIE]
    if nie:
        return (f"Das Token hat das Recht {_namen(nie)}. Das ist bei W.A.I.S. nie erlaubt; bitte ein neues Token ohne dieses Recht "
                "erzeugen.")
    zu_weit = [s for s in liste if s not in erlaubt and s in SCOPES_AUSNAHMEN]
    if zu_weit:
        return (f"Das Token hat Rechte, die für dein Profil nicht freigegeben sind: {_namen(zu_weit)}. Bitte ein neues Token ohne "
                "diese Rechte erzeugen oder einen Admin bitten, sie für dich zu erlauben.")
    unbekannt = [s for s in liste if s not in erlaubt]
    if unbekannt:
        return (f"Das Token hat Rechte, die W.A.I.S. nicht kennt: {_namen(unbekannt)}. Bitte ein neues Token nur mit den nötigen "
                "Rechten erzeugen.")
    return None


def ablauf_lesen(kopf: str | None) -> datetime | None:
    """GitHub-Authentication-Token-Expiration (etwa "2026-12-31 23:59:59 UTC" oder "... +0100") als Zeitpunkt mit Zeitzone, sonst None."""
    if not kopf:
        return None
    text = kopf.strip()
    try:
        if text.endswith(" UTC"):  # nur das Literal UTC, keine anderen Zonennamen (%Z nähme auch CET als naive Zeit)
            return datetime.strptime(text[:-4], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        zeit = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None
    return zeit if zeit.tzinfo is not None else None


def ablauf_problem(ablauf: datetime | None, jetzt: datetime | None = None) -> str | None:
    jetzt = jetzt or datetime.now(UTC)
    if ablauf is None:
        return ("Das Token hat kein Ablaufdatum. Bitte ein Token mit Ablauf erzeugen (höchstens 366 Tage); W.A.I.S. nimmt keine Tokens "
                "ohne Ablauf.")
    if ablauf <= jetzt:
        return "Das Token ist abgelaufen. Bitte ein neues erzeugen und hier hinterlegen."
    if ablauf - jetzt > timedelta(days=ABLAUF_MAX_TAGE) + ABLAUF_TOLERANZ:
        return f"Das Token läuft erst in mehr als {ABLAUF_MAX_TAGE} Tagen ab. Bitte ein Token mit kürzerem Ablauf erzeugen."
    return None


# ---------- Prüfung bei GitHub ----------
@dataclass(frozen=True)
class Pruefung:
    """Was GitHub über das Token sagt. Enthält nie das Token."""

    art: str
    login: str
    konto_id: int
    scopes: tuple[str, ...]
    ablauf: datetime | None


Pruefer = Callable[[str], Awaitable[Pruefung]]


def _kopfzeilen(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "wais-kern"}


async def bei_github_pruefen(token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> Pruefung:
    """GET https://api.github.com/user mit dem Token (Zeitlimit 10 s, keine Weiterleitung, Antwort höchstens 256 KiB). Wirft ZugangFehler
    mit einem Satz für die Person; weder Token noch Antworttext landen in einer Meldung."""
    art = art_von(token)
    try:
        async with httpx.AsyncClient(base_url=API_URL, transport=transport, follow_redirects=False, trust_env=False,
                                     timeout=httpx.Timeout(PRUEF_TIMEOUT_SECS, connect=5.0)) as client:
            async with client.stream("GET", "/user", headers=_kopfzeilen(token)) as antwort:
                status = antwort.status_code
                kopf = antwort.headers
                roh = bytearray()
                if status == 200:
                    async for stueck in antwort.aiter_bytes():
                        roh += stueck
                        if len(roh) > ANTWORT_MAX_BYTES:
                            raise ZugangFehler("GitHub antwortet zu lang; das Token wird nicht gespeichert.")
    except httpx.TimeoutException:
        raise ZugangFehler(f"GitHub hat nicht rechtzeitig geantwortet (nach {PRUEF_TIMEOUT_SECS:.0f} s). Bitte später noch einmal.") from None
    except httpx.HTTPError:
        raise ZugangFehler("GitHub ist gerade nicht erreichbar. Bitte später noch einmal.") from None
    if status == 401:
        raise ZugangFehler("GitHub lehnt das Token ab (401): Es ist ungültig, abgelaufen oder widerrufen.")
    if status == 403:
        raise ZugangFehler("GitHub verweigert die Prüfung (403). Bei Tokens einer Organisation mit SSO bitte das Token dort freigeben.")
    if 300 <= status < 400:
        raise ZugangFehler("GitHub antwortet mit einer Weiterleitung; das Token wird nicht gespeichert.")
    if status != 200:
        raise ZugangFehler(f"GitHub antwortet mit HTTP {status}. Bitte später noch einmal.")
    try:
        daten = json.loads(bytes(roh).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ZugangFehler("GitHub antwortet in einer unbekannten Form; das Token wird nicht gespeichert.") from None
    login, konto, typ = (daten.get("login"), daten.get("id"), daten.get("type")) if isinstance(daten, dict) else (None, None, None)
    if typ != "User":
        raise ZugangFehler("Das Token gehört zu keinem Personenkonto bei GitHub.")
    if not (isinstance(login, str) and LOGIN_RE.fullmatch(login)) or not (isinstance(konto, int) and not isinstance(konto, bool)
                                                                            and konto > 0):
        raise ZugangFehler("GitHub nennt Login oder Konto in einer unbekannten Form; das Token wird nicht gespeichert.")
    scopes = scopes_lesen(kopf.get("x-oauth-scopes")) if art == ART_KLASSISCH else ()
    return Pruefung(art, login, konto, scopes, ablauf_lesen(kopf.get("github-authentication-token-expiration")))


# ---------- Datenbank ----------
_ZEILE = ("select art, token_ende, login, konto_id, scopes, ablauf, geprueft_at, angelegt_at from {g} "
          "where user_id = $1::uuid")
_TOKEN = ("select g.art, g.token, g.scopes, g.ablauf, p.labor_art from {g} g join {p} p on p.user_id = g.user_id "
          "where g.user_id = $1::uuid")
_SPEICHERN = ("insert into {g} (user_id, art, token, token_ende, login, konto_id, scopes, ablauf) "
              "values ($1::uuid, $2, $3, $4, $5, $6, $7::text[], $8) on conflict (user_id) do update set art = excluded.art, "
              "token = excluded.token, token_ende = excluded.token_ende, login = excluded.login, konto_id = excluded.konto_id, "
              "scopes = excluded.scopes, ablauf = excluded.ablauf")
_GEPRUEFT = "update {g} set login = $2, konto_id = $3, scopes = $4::text[], ablauf = $5 where user_id = $1::uuid"
_LOESCHEN = "delete from {g} where user_id = $1::uuid"
_RECHTE = "select scopes_ausnahmen from {r} where user_id = $1::uuid"
_RECHTE_SETZEN = ("insert into {r} (user_id, scopes_ausnahmen, geaendert_von) values ($1::uuid, $2::text[], $3::uuid) "
                  "on conflict (user_id) do update set scopes_ausnahmen = excluded.scopes_ausnahmen, "
                  "geaendert_von = excluded.geaendert_von")
_ZIEL = "select labor_art from {p} where user_id = $1::uuid"
_RECHTE_LISTE = ("select p.user_id::text as user_id, p.display_name, p.rolle::text as rolle, p.aktiv, "
                 "coalesce(r.scopes_ausnahmen, array[]::text[]) as scopes_ausnahmen, g.art, g.login, g.ablauf from {p} p "
                 "left join {r} r on r.user_id = p.user_id left join {g} g on g.user_id = p.user_id "
                 "where p.labor_art is null order by p.display_name limit 200")


def _sql(db: Database, vorlage: str) -> str:
    return vorlage.format(g=db.t("github_zugang"), r=db.t("github_rechte"), p=db.t("profiles"))


def _db(db: Database | None) -> Database:
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: der GitHub-Zugang ist gerade nicht verfügbar.")
    return db


def _tresor(tresor: Tresor | None) -> Tresor:
    if tresor is not None:
        return tresor
    try:
        geladen = Tresor.from_env()
    except SchluesselFehler as e:
        logger.error("Hauptschlüssel unbrauchbar: {}", e)
        geladen = None
    if geladen is None:
        raise ZugangFehler("Der Kern hat keinen Hauptschlüssel (WAMO_SCHLUESSEL_KEK); bitte an den Admin wenden.")
    return geladen


async def rechte_laden(db: Database, uid: str) -> tuple[str, ...]:
    """Die vom Admin erlaubten Ausnahmen der Person; ohne Zeile, ohne Tabelle oder bei einem Fehler der strenge Standard (keine)."""
    try:
        zeile = await db.fetchrow(_sql(db, _RECHTE), uid)
    except (asyncpg.UndefinedTableError, asyncpg.InsufficientPrivilegeError):
        return ()
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("GitHub-Rechte von Profil {} nicht lesbar ({}): strenger Standard", uid[:8], type(e).__name__)
        return ()
    return ausnahmen_normal(zeile["scopes_ausnahmen"]) if zeile else ()


def _bremse(speicher: dict[str, list[float]], schluessel: str, grenze: int, jetzt: float | None = None) -> bool:
    jetzt = time.monotonic() if jetzt is None else jetzt
    liste = [t for t in speicher.get(schluessel, []) if jetzt - t < VERSUCHE_FENSTER_SECS]
    if len(liste) >= grenze:
        speicher[schluessel] = liste
        return False
    speicher[schluessel] = [*liste, jetzt]
    if len(speicher) > 500:
        for k in [k for k, v in speicher.items() if not v or jetzt - v[-1] > VERSUCHE_FENSTER_SECS]:
            del speicher[k]
    return True


def _versuch_erlaubt(uid: str, jetzt: float | None = None) -> bool:
    return _bremse(_versuche, uid, VERSUCHE_JE_FENSTER, jetzt)


async def _protokollieren(db: Database, uid: str, werkzeug: str, params: dict, grund: str) -> None:
    """Zeile in actions (Risiko change, Status done), nur mit Metadaten, nie mit dem Wert. Wirft nie: die Änderung ist schon gespeichert."""
    try:
        await db.execute(
            f"insert into {db.t('actions')} (user_id, tool, params, reason, risk, status, result, finished_at) "
            f"values ($1::uuid, $2, $3::text::jsonb, $4, 'change'::{db.t('risk_class')}, 'done'::{db.t('action_status')}, "
            "'{}'::jsonb, now())",
            uid, werkzeug, json.dumps(params), grund,
        )
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("{} für Profil {} nicht protokolliert ({})", werkzeug, uid[:8], type(e).__name__)


def _zeit(wert: object) -> str | None:
    return wert.isoformat(timespec="minutes") if isinstance(wert, datetime) else None


def _datum(wert: object) -> str | None:
    return wert.date().isoformat() if isinstance(wert, datetime) else None


# ---------- Stand für die Oberfläche ----------
@dataclass(frozen=True)
class Stand:
    """Was die Oberfläche über den GitHub-Zugang erfährt. Enthält nie das Token."""

    verfuegbar: bool
    grund: str | None = None  # warum Speichern und Prüfen nicht gehen
    hinterlegt: bool = False
    art: str | None = None
    login: str | None = None
    ende: str | None = None
    scopes: tuple[str, ...] = ()
    ablauf: str | None = None
    geprueft: str | None = None
    angelegt: str | None = None
    scopes_ausnahmen: tuple[str, ...] = ()  # vom Admin erlaubte Ausnahmen (C.2.8), sortiert
    problem: str | None = None  # warum ein hinterlegtes Token gerade nicht benutzt wird

    def nachricht(self, *, aktion: str = "stand", fehler: str | None = None, ok: str | None = None) -> dict:
        n: dict[str, object] = {
            "type": "github_zugang", "aktion": aktion, "verfuegbar": self.verfuegbar, "grund": self.grund,
            "hinterlegt": self.hinterlegt, "art": self.art, "login": self.login, "ende": self.ende, "scopes": list(self.scopes),
            "ablauf": self.ablauf, "geprueft": self.geprueft, "angelegt": self.angelegt, "scopes_ausnahmen": list(self.scopes_ausnahmen),
            "problem": self.problem, "bereit": self.hinterlegt and self.problem is None and self.verfuegbar,
            "hinweis_fein": SATZ_FEIN_RECHTE, "ablauf_max_tage": ABLAUF_MAX_TAGE,
        }
        if fehler:
            n["fehler"] = fehler
        if ok:
            n["ok"] = ok
        return n


async def stand_laden(user_id: str, *, grund: str | None = None, db: Database | None = None,
                      jetzt: datetime | None = None) -> Stand:
    """Stand des eigenen Zugangs (ohne Entschlüsseln). grund: Ergebnis von verfuegbar_grund (None heißt verfügbar)."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = _db(db)
    try:
        zeile = await db.fetchrow(_sql(db, _ZEILE), uid)
    except asyncpg.UndefinedTableError:
        return Stand(verfuegbar=False, grund=SATZ_NICHT_EINGERICHTET)
    ausnahmen = await rechte_laden(db, uid)
    if not zeile:
        return Stand(verfuegbar=grund is None, grund=grund, scopes_ausnahmen=ausnahmen)
    scopes = tuple(zeile["scopes"] or ())
    problem = ablauf_problem(zeile["ablauf"], jetzt)
    if problem is None and zeile["art"] == ART_KLASSISCH:
        problem = scopes_problem(scopes, ausnahmen)
    return Stand(verfuegbar=grund is None, grund=grund, hinterlegt=True, art=zeile["art"], login=zeile["login"],
                 ende=zeile["token_ende"], scopes=scopes, ablauf=_datum(zeile["ablauf"]), geprueft=_zeit(zeile["geprueft_at"]),
                 angelegt=_zeit(zeile["angelegt_at"]), scopes_ausnahmen=ausnahmen, problem=problem)


def _regeln(pruefung: Pruefung, ausnahmen: tuple[str, ...], jetzt: datetime | None) -> str | None:
    return ablauf_problem(pruefung.ablauf, jetzt) or (
        scopes_problem(pruefung.scopes, ausnahmen) if pruefung.art == ART_KLASSISCH else None)


async def speichern(user_id: str, token_roh: object, *, grund: str | None = None, db: Database | None = None,
                    tresor: Tresor | None = None, pruefen: Pruefer | None = None, jetzt: datetime | None = None) -> Stand:
    """Prüft das Token bei GitHub, verschlüsselt und speichert es (ersetzt ein vorhandenes). Wirft ZugangFehler mit einem Satz für die
    Person; das Token verlässt diese Funktion nur als Chiffrat."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if grund:
        raise ZugangFehler(grund)
    token = token_roh.strip() if isinstance(token_roh, str) else ""
    art_von(token)  # Form zuerst, ohne Netz und ohne Versuch zu verbrauchen
    db = _db(db)
    tresor = _tresor(tresor)
    if not _versuch_erlaubt(uid):
        raise ZugangFehler("Zu viele Versuche, bitte in zehn Minuten noch einmal.")
    pruefung = await (pruefen or bei_github_pruefen)(token)
    if problem := _regeln(pruefung, await rechte_laden(db, uid), jetzt):
        raise ZugangFehler(problem)
    chiffre = tresor.verschluesseln(uid, token, GITHUB)
    try:
        await db.execute(_sql(db, _SPEICHERN), uid, pruefung.art, chiffre, ende(token), pruefung.login, pruefung.konto_id,
                         list(pruefung.scopes), pruefung.ablauf)
    except asyncpg.UndefinedTableError:
        raise ZugangFehler(SATZ_NICHT_EINGERICHTET) from None
    except asyncpg.InsufficientPrivilegeError:
        raise ZugangFehler("Für dieses Profil lässt die Datenbank keinen GitHub-Zugang zu.") from None
    except asyncpg.CheckViolationError:
        raise ZugangFehler("Die Datenbank hat die Angaben zum Token abgelehnt (Form von Login, Rechten oder Länge).") from None
    del token
    logger.info("GitHub-Zugang für Profil {} hinterlegt ({}, {})", uid[:8], pruefung.art, pruefung.login)
    await _protokollieren(db, uid, WERKZEUG, {"aktion": "speichern", "art": pruefung.art, "login": pruefung.login,
                                              "ablauf": _datum(pruefung.ablauf)}, "Eigenen GitHub-Zugang hinterlegt")
    return await stand_laden(uid, grund=grund, db=db, jetzt=jetzt)


async def erneut_pruefen(user_id: str, *, grund: str | None = None, db: Database | None = None, tresor: Tresor | None = None,
                         pruefen: Pruefer | None = None, jetzt: datetime | None = None) -> tuple[Stand, str | None]:
    """Prüft das hinterlegte Token noch einmal bei GitHub und schreibt Login, Rechte und Ablauf neu. Liefert den Stand und einen Satz,
    wenn das Token jetzt nicht mehr passt (dann bleibt es gespeichert, wird aber nicht benutzt)."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if grund:
        raise ZugangFehler(grund)
    db = _db(db)
    try:
        zeile = await db.fetchrow(_sql(db, _TOKEN), uid)
    except asyncpg.UndefinedTableError:
        raise ZugangFehler(SATZ_NICHT_EINGERICHTET) from None
    if not zeile:
        raise ZugangFehler("Es ist kein GitHub-Zugang hinterlegt.")
    tresor = _tresor(tresor)
    try:
        token = tresor.entschluesseln(uid, zeile["token"], GITHUB)
    except SchluesselFehler as e:
        logger.error("GitHub-Zugang von Profil {} nicht lesbar ({})", uid[:8], e)
        raise ZugangFehler("Das gespeicherte Token ist nicht lesbar. Bitte löschen und neu hinterlegen.") from None
    if not _versuch_erlaubt(uid):
        raise ZugangFehler("Zu viele Versuche, bitte in zehn Minuten noch einmal.")
    pruefung = await (pruefen or bei_github_pruefen)(token)
    del token
    await db.execute(_sql(db, _GEPRUEFT), uid, pruefung.login, pruefung.konto_id, list(pruefung.scopes), pruefung.ablauf)
    problem = _regeln(pruefung, await rechte_laden(db, uid), jetzt)
    await _protokollieren(db, uid, WERKZEUG, {"aktion": "pruefen", "art": pruefung.art, "login": pruefung.login,
                                              "ablauf": _datum(pruefung.ablauf), "ok": problem is None},
                          "Eigenen GitHub-Zugang erneut geprüft")
    return await stand_laden(uid, grund=grund, db=db, jetzt=jetzt), problem


async def loeschen(user_id: str, *, grund: str | None = None, db: Database | None = None) -> Stand:
    """Löscht den eigenen Zugang (geht immer, auch bei ausgeschaltetem Schalter). Das Token bei GitHub widerruft die Person selbst."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = _db(db)
    try:
        ergebnis = await db.execute(_sql(db, _LOESCHEN), uid)
    except asyncpg.UndefinedTableError:
        raise ZugangFehler(SATZ_NICHT_EINGERICHTET) from None
    if str(ergebnis).strip() != "DELETE 0":
        logger.info("GitHub-Zugang für Profil {} gelöscht", uid[:8])
        await _protokollieren(db, uid, WERKZEUG, {"aktion": "loeschen"}, "Eigenen GitHub-Zugang gelöscht")
    return await stand_laden(uid, grund=grund, db=db)


async def github_zugang_fuer(user_id: str, *, db: Database | None = None, tresor: Tresor | None = None,
                             jetzt: datetime | None = None) -> dict[str, str] | None:
    """Das Token des Profils für GENAU EINEN Aufruf des Dispatchers, entschlüsselt: {"typ": "github", "wert": ...}, sonst None.
    None, wenn der Schalter aus ist, nichts hinterlegt ist, das Profil ein Laborprofil ist, das Token abgelaufen ist, seine Rechte nach den
    heutigen Regeln (mit den Ausnahmen der Person) nicht passen, der Hauptschlüssel fehlt oder das Chiffrat nicht lesbar ist. Ein
    abgelaufenes Token setzt keinen Rückfall auf die App. Aufruf nur im Kern durch den Entwicklungs-Agenten der Sitzung dieses Profils,
    kurz vor dem Aufruf; der Wert wird in keinem Objekt gehalten und nie geloggt."""
    uid = normalize_uuid(user_id)
    if uid is None or not schalter_an():
        return None
    db = db or shared_database()
    if not db.configured:
        return None
    try:
        zeile = await db.fetchrow(_sql(db, _TOKEN), uid)
    except asyncpg.UndefinedTableError:
        return None
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.error("GitHub-Zugang von Profil {} nicht lesbar ({})", uid[:8], type(e).__name__)
        return None
    if not zeile or zeile["labor_art"] is not None:
        return None
    if problem := ablauf_problem(zeile["ablauf"], jetzt):
        logger.info("GitHub-Zugang von Profil {} nicht benutzt: {}", uid[:8], problem)
        return None
    if zeile["art"] == ART_KLASSISCH and (problem := scopes_problem(tuple(zeile["scopes"] or ()), await rechte_laden(db, uid))):
        logger.info("GitHub-Zugang von Profil {} nicht benutzt: Rechte passen nicht", uid[:8])
        return None
    try:
        tresor = _tresor(tresor)
        return {"typ": "github", "wert": tresor.entschluesseln(uid, zeile["token"], GITHUB)}
    except (ZugangFehler, SchluesselFehler) as e:
        logger.error("GitHub-Zugang von Profil {} nicht nutzbar ({})", uid[:8], type(e).__name__)
        return None


# ---------- Nachricht aus der Oberfläche (Datenkanal und HTTP) ----------
async def github_zugang_nachricht(identity: object, data: Mapping[str, object], senden: Callable[[dict], Awaitable[None]], *,
                                  db: Database | None = None, tresor: Tresor | None = None,
                                  pruefen: Pruefer | None = None) -> None:
    """Klick aus der Oberfläche (Client-Nachricht oder POST /wamo/api/github-zugang). Aktionen: stand, speichern (Feld token), pruefen,
    loeschen. Die Antwort enthält nie das Token, der Inhalt der Nachricht wird nie geloggt. Laborprofile bekommen nur einen Satz."""
    aktion = data.get("aktion") if data.get("aktion") in AKTIONEN else "stand"
    uid = str(getattr(identity, "user_id", "") or "")
    if _ist_labor(identity):
        await senden({"type": "github_zugang", "aktion": aktion, "verfuegbar": False, "grund": SATZ_LABOR, "fehler": SATZ_LABOR})
        return
    grund = verfuegbar_grund(identity)
    try:
        ok = None
        if aktion == "speichern":
            stand = await speichern(uid, data.get("token"), grund=grund, db=db, tresor=tresor, pruefen=pruefen)
            ok = f"Gespeichert. Konto {stand.login}, gültig bis {stand.ablauf}."
        elif aktion == "pruefen":
            stand, problem = await erneut_pruefen(uid, grund=grund, db=db, tresor=tresor, pruefen=pruefen)
            if problem:
                await senden(stand.nachricht(aktion=aktion, fehler=problem))
                return
            ok = "Das Token ist gültig."
        elif aktion == "loeschen":
            stand = await loeschen(uid, grund=grund, db=db)
            ok = "Gelöscht. Bitte das Token auch bei GitHub widerrufen."
        else:
            stand = await stand_laden(uid, grund=grund, db=db)
        await senden(stand.nachricht(aktion=aktion, ok=ok))
    except ZugangFehler as e:
        logger.info("GitHub-Zugang {} für Profil {} abgelehnt: {}", aktion, uid[:8], e)
        try:
            stand = await stand_laden(uid, grund=grund, db=db)
            await senden(stand.nachricht(aktion=aktion, fehler=str(e)))
        except (ZugangFehler, DatabaseUnavailable, *DB_ERRORS):
            await senden({"type": "github_zugang", "aktion": aktion, "verfuegbar": False, "grund": grund, "fehler": str(e)})
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.error("GitHub-Zugang {} für Profil {}: Datenbank ({})", aktion, uid[:8], type(e).__name__)
        await senden({"type": "github_zugang", "aktion": aktion, "verfuegbar": False, "grund": grund,
                      "fehler": "Datenbank gerade nicht erreichbar."})
    except Exception as e:  # nie ohne Antwort an die Oberfläche, nie mit dem Text der Ausnahme
        logger.error("GitHub-Zugang {} für Profil {}: unerwarteter Fehler ({})", aktion, uid[:8], type(e).__name__)
        await senden({"type": "github_zugang", "aktion": aktion, "verfuegbar": False, "grund": grund,
                      "fehler": "Unerwarteter Fehler, bitte später noch einmal."})


# ---------- Admin: erlaubte Rechte je Person ----------
@dataclass(frozen=True)
class Person:
    """Eine Zeile der Admin-Übersicht. Enthält nie das Token, das Ende oder die Konto-ID."""

    user_id: str
    name: str
    rolle: str | None
    aktiv: bool
    scopes_ausnahmen: tuple[str, ...]
    art: str | None
    login: str | None
    ablauf: str | None

    def daten(self) -> dict[str, object]:
        return {"user_id": self.user_id, "name": self.name, "rolle": self.rolle, "aktiv": self.aktiv,
                "scopes_ausnahmen": list(self.scopes_ausnahmen),
                "hinterlegt": self.art is not None, "art": self.art, "login": self.login, "ablauf": self.ablauf}


def _person(z: Mapping[str, object]) -> Person | None:
    uid = normalize_uuid(z["user_id"])
    if uid is None:
        return None
    name = z["display_name"] if isinstance(z["display_name"], str) else ""
    name = "".join(c for c in name[:240] if c.isprintable())[:60]
    login = z["login"] if isinstance(z["login"], str) and LOGIN_RE.fullmatch(z["login"]) else None
    return Person(uid, name, z["rolle"] if z["rolle"] in ("admin", "mitglied") else None, z["aktiv"] is True,
                  ausnahmen_normal(z["scopes_ausnahmen"]), z["art"] if z["art"] in ARTEN else None, login, _datum(z["ablauf"]))


async def rechte_liste(*, db: Database | None = None) -> list[Person]:
    """Alle Profile ohne Laborprofile mit ihren erlaubten Ausnahmen und dem Stand des Zugangs (ohne Wert). Nur für die Admin-Route."""
    db = _db(db)
    try:
        zeilen = await db.fetch(_sql(db, _RECHTE_LISTE))
    except asyncpg.UndefinedTableError:
        raise ZugangFehler(SATZ_NICHT_EINGERICHTET) from None
    return [p for p in (_person(z) for z in zeilen) if p is not None]


def ausnahmen_pruefen(werte: object) -> tuple[str, ...]:
    """Die Liste aus der Admin-Route: nur Texte aus SCOPES_AUSNAHMEN, nie SCOPES_NIE, ohne Doppel; sonst ZugangFehler. Ergebnis sortiert."""
    if not isinstance(werte, list) or len(werte) > MAX_SCOPES or not all(isinstance(w, str) for w in werte):
        raise ZugangFehler("Die Liste der Rechte hat eine unbekannte Form.")
    if len(set(werte)) != len(werte):
        raise ZugangFehler("Ein Recht steht doppelt in der Liste.")
    nie = [w for w in werte if w in SCOPES_NIE]
    if nie:
        raise ZugangFehler(f"{_namen(nie)} ist nie erlaubt, auch nicht durch einen Admin.")
    fremd = [w for w in werte if w not in SCOPES_AUSNAHMEN]
    if fremd:
        raise ZugangFehler("Unbekanntes Recht in der Liste; erlaubbar sind nur die angebotenen Rechte.")
    return ausnahmen_normal(werte)


def _rechte_erlaubt(admin: str, jetzt: float | None = None) -> bool:
    return _bremse(_rechte_versuche, admin, RECHTE_JE_FENSTER, jetzt)


async def rechte_setzen(admin_id: str, ziel_id: object, werte: object, *, db: Database | None = None) -> tuple[str, ...]:
    """Ein Admin legt fest, welche strengen Rechte ein klassisches Token der Person zusätzlich haben darf. Prüft Liste und Zielprofil
    (vorhanden, kein Laborprofil), schreibt nur bei einer Änderung und protokolliert sie in actions (beim Admin, mit der Kurzkennung der
    Person, nie Namen). Die Rolle des Aufrufers prüft die Route; die Datenbank prüft zusätzlich, dass geaendert_von ein aktiver Admin ist."""
    admin = normalize_uuid(admin_id)
    ziel = normalize_uuid(ziel_id)
    if admin is None or ziel is None:
        raise ZugangFehler("Profil ungültig")
    ausnahmen = ausnahmen_pruefen(werte)
    db = _db(db)
    try:
        profil = await db.fetchrow(_sql(db, _ZIEL), ziel)
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("GitHub-Rechte: Zielprofil nicht lesbar ({})", type(e).__name__)
        raise ZugangFehler("Die Datenbank ist gerade nicht erreichbar.") from None
    if not profil:
        raise ZugangFehler("Dieses Profil gibt es nicht.")
    if profil["labor_art"] is not None:
        raise ZugangFehler(SATZ_LABOR)
    vorher = await rechte_laden(db, ziel)
    if vorher == ausnahmen:
        return vorher
    if not _rechte_erlaubt(admin):
        raise ZugangFehler("Zu viele Änderungen, bitte in zehn Minuten noch einmal.")
    try:
        await db.execute(_sql(db, _RECHTE_SETZEN), ziel, list(ausnahmen), admin)
    except asyncpg.UndefinedTableError:
        raise ZugangFehler(SATZ_NICHT_EINGERICHTET) from None
    except asyncpg.InsufficientPrivilegeError:
        raise ZugangFehler("Die Datenbank lässt diese Änderung nicht zu (nur aktive Admins, keine Laborprofile).") from None
    except asyncpg.CheckViolationError:
        raise ZugangFehler("Die Datenbank hat die Liste der Rechte abgelehnt.") from None
    kennung = ziel.replace("-", "")[:8]
    logger.info("GitHub-Rechte für Profil {} durch Admin {}: {}", kennung, admin[:8], ", ".join(ausnahmen) or "Standard")
    await _protokollieren(db, admin, WERKZEUG_RECHTE,
                          {"profil": kennung, "scopes_ausnahmen": list(ausnahmen), "vorher": list(vorher)},
                          "Erlaubte Rechte eines GitHub-Tokens für eine Person festgelegt")
    return ausnahmen


# ---------- Für den Entwicklungs-Agenten (dev_agent.py) ----------
async def ausnahmen_fuer(user_id: str, *, db: Database | None = None) -> tuple[str, ...]:
    """Die vom Admin erlaubten Ausnahmen der Person, sortiert, für das Feld scopes_ausnahmen (C.2.8). Jeder Fehler heißt keine."""
    uid = normalize_uuid(user_id)
    db = db or shared_database()
    if uid is None or not db.configured:
        return ()
    return await rechte_laden(db, uid)


async def konto_bereit(user_id: str, *, db: Database | None = None) -> str | None:
    """Login des hinterlegten Tokens, wenn es nach den heutigen Regeln nutzbar ist (Schalter an, hinterlegt, nicht abgelaufen, Rechte
    passen), sonst None. Ohne Entschlüsseln: für die Auftragskarte vor dem Start."""
    if not schalter_an():
        return None
    try:
        stand = await stand_laden(user_id, db=db)
    except (ZugangFehler, DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("GitHub-Zugang von Profil {} nicht lesbar ({})", str(user_id)[:8], type(e).__name__)
        return None
    return stand.login if stand.hinterlegt and stand.problem is None else None
