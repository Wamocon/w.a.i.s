"""Claude-Zugang des Testlabors: der gespeicherte Anthropic-API-Schlüssel, über den Laborprofile ihr Gespräch führen (Migration 0032).

Bisher führten die Laborprofile (Testlabor, Gäste, modellzugang.LABOR_ARTEN) ihr Gespräch über ANTHROPIC_API_KEY aus der Umgebung des Kerns.
Lehnt Anthropic diesen Schlüssel ab, fallen alle Gäste auf Hausmodelle zurück. Ein Admin kann den Schlüssel deshalb in der Werkstatt setzen:

  Reihenfolge für ein Laborprofil   1. der hier gespeicherte Schlüssel   2. der Schlüssel des Servers (ANTHROPIC_API_KEY)   3. Hausmodelle
  Setzen       Format prüfen, kleine Testanfrage bei Anthropic (Modellliste, kein Verbrauch, kein Wiederholen), nur bei Erfolg speichern
  Entfernen    löscht die Zeile, danach gilt wieder der Schlüssel des Servers
  Status       Quelle (gespeichert, server, keiner), die letzten vier Zeichen, Workspace und Zeiten, nie der Schlüssel

Sicherheit
  * Der Schlüssel liegt nur als Chiffrat in der Tabelle labor_zugang (schluessel.py, AES-256-GCM, Hauptschlüssel WAMO_SCHLUESSEL_KEK nur
    beim Kern). Als zusätzliche Daten dient eine feste Kennung (BINDUNG) statt einer Profil-ID: ein Chiffrat aus model_access lässt sich hier
    nicht einsetzen und umgekehrt.
  * Der Klartext lebt nur kurz im Speicher: für die Testanfrage und im Zwischenspeicher des Prozesses (höchstens 30 Sekunden alt). Er steht nie
    in Antworten, nie im Log (auch nicht in Ausnahmetexten der anthropic-Bibliothek: Fehler werden nur nach Art gemeldet und ohne Kette
    weitergereicht), nie in actions (dort höchstens "endet auf") und nie in einem Ausnahmetext dieses Moduls.
  * Pro Prozess wird höchstens alle 30 Sekunden gelesen, nie je Sitzung, nie im Audiopfad. Fehlt Tabelle, Hauptschlüssel oder lässt sich das
    Chiffrat nicht lesen, gilt der Schlüssel des Servers (und danach die Hausmodelle): ein Fehler hier darf keine Laborsitzung verhindern.
  * Jedes Setzen und Entfernen steht als Zeile in actions (Werkzeug labor_zugang_setzen und labor_zugang_entfernen), in derselben Anweisung wie
    die Änderung selbst: ohne Protokollzeile gibt es keine Änderung.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass

import anthropic
import asyncpg
from loguru import logger

from memory import DB_ERRORS, Database, DatabaseUnavailable, normalize_uuid, shared_database
from schluessel import SCHLUESSEL, SchluesselFehler, Tresor, ende, format_pruefen

BINDUNG = "00000000-0000-4000-8000-0000000032a1"  # feste Kennung als Bindung des Chiffrats (kein Profil, kein Konto)
WERKZEUG_SETZEN = "labor_zugang_setzen"
WERKZEUG_ENTFERNEN = "labor_zugang_entfernen"
CACHE_SECS = 30.0  # so lange gilt ein gelesener Schlüssel im Speicher des Prozesses
FEHLER_CACHE_SECS = 5.0  # so lange gilt ein Lesefehler (dann gilt kurz der Schlüssel des Servers)
TEST_TIMEOUT_SECS = 10.0
_WORKSPACE = re.compile(r"wrkspc_[A-Za-z0-9]{6,60}")

_SQL_LESEN = ("select claude_schluessel, claude_workspace, endet_auf, gesetzt_am, geprueft_am from {t} where id = $1::boolean")
_SQL_SETZEN = (
    "with neu as (insert into {t} (id, claude_schluessel, claude_workspace, endet_auf, gesetzt_von, gesetzt_am, geprueft_am) "
    "values (true, $1, $2, $3, $4::uuid, now(), now()) "
    "on conflict (id) do update set claude_schluessel = excluded.claude_schluessel, claude_workspace = excluded.claude_workspace, "
    "endet_auf = excluded.endet_auf, gesetzt_von = excluded.gesetzt_von, gesetzt_am = excluded.gesetzt_am, "
    "geprueft_am = excluded.geprueft_am returning endet_auf) "
    "insert into {a} (user_id, tool, params, reason, risk, status, result, finished_at) "
    "select $4::uuid, $5, jsonb_build_object('endet_auf', neu.endet_auf), $6, 'change'::{risk}, 'done'::{status}, '{{}}'::jsonb, now() "
    "from neu returning 1")
_SQL_ENTFERNEN = (
    "with weg as (delete from {t} where id returning endet_auf) "
    "insert into {a} (user_id, tool, params, reason, risk, status, result, finished_at) "
    "select $1::uuid, $2, jsonb_build_object('endet_auf', weg.endet_auf), $3, 'change'::{risk}, 'done'::{status}, '{{}}'::jsonb, now() "
    "from weg returning 1")
GRUND_SETZEN = "Claude-Zugang des Labors von einem Admin gesetzt, gilt für neue Laborsitzungen"
GRUND_ENTFERNEN = "Claude-Zugang des Labors von einem Admin entfernt, es gilt wieder der Schlüssel des Servers"


class LaborZugangFehler(Exception):
    """Setzen oder Entfernen ist nicht möglich. code ist maschinenlesbar, text ein Satz für die Person (ohne Schlüssel), status der HTTP-Status."""

    def __init__(self, code: str, text: str, status: int = 400):
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status


@dataclass(frozen=True)
class LaborStand:
    """Was die Oberfläche über den Zugang erfährt. Enthält nie den Schlüssel."""

    quelle: str  # gespeichert | server | keiner (wirksam: was die nächste Laborsitzung wirklich nimmt)
    endet_auf: str | None = None
    workspace: str | None = None
    gesetzt_am: str | None = None
    geprueft_am: str | None = None
    hinweis: str | None = None

    def daten(self) -> dict[str, str | None]:
        return {"quelle": self.quelle, "endet_auf": self.endet_auf, "workspace": self.workspace, "gesetzt_am": self.gesetzt_am,
                "geprueft_am": self.geprueft_am, "hinweis": self.hinweis}


# ---------- Zwischenspeicher (je Prozess) ----------
_cache: tuple[float, tuple[str, str | None] | None] | None = None
_sperre: asyncio.Lock | None = None
_sperre_loop: asyncio.AbstractEventLoop | None = None
_gemeldet: set[str] = set()


def cache_leeren() -> None:
    """Vergisst den gelesenen Schlüssel (nach Setzen und Entfernen, und in Tests)."""
    global _cache, _sperre, _sperre_loop
    _cache = None
    _sperre = _sperre_loop = None
    _gemeldet.clear()


def _lock() -> asyncio.Lock:
    global _sperre, _sperre_loop
    loop = asyncio.get_running_loop()
    if _sperre is None or _sperre_loop is not loop:
        _sperre, _sperre_loop = asyncio.Lock(), loop
    return _sperre


def _einmal(meldung: str) -> bool:
    """True beim ersten Mal je Prozess (und bis zum nächsten Leeren): Lesefehler stehen einmal im Log, nicht bei jeder Sitzung."""
    if meldung in _gemeldet:
        return False
    _gemeldet.add(meldung)
    return True


def _tresor_oder_none(tresor: Tresor | None) -> Tresor | None:
    if tresor is not None:
        return tresor
    try:
        return Tresor.from_env()
    except SchluesselFehler as e:
        if _einmal("kek"):
            logger.error("Hauptschlüssel unbrauchbar, Labor-Schlüssel nicht lesbar: {}", e)
        return None


def server_schluessel() -> str:
    """Der Schlüssel des Servers (ANTHROPIC_API_KEY), leer, wenn keiner gesetzt ist."""
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip()


def server_workspace() -> str | None:
    return (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip() or None


# ---------- Lesen ----------
async def _zeile(db: Database):
    """Die eine Zeile oder None. Fehlt die Tabelle (Migration 0032 nicht angewendet), gibt es keine Zeile."""
    try:
        return await db.fetchrow(_SQL_LESEN.format(t=db.t("labor_zugang")), True)
    except asyncpg.UndefinedTableError:
        if _einmal("tabelle"):
            logger.warning("labor_zugang fehlt (Migration 0032): Laborprofile nehmen den Schlüssel des Servers")
        return None


def _entschluesseln(zeile, tresor: Tresor | None) -> tuple[str, str | None] | None:
    """Schlüssel und Workspace der Zeile, None, wenn der Hauptschlüssel fehlt oder das Chiffrat nicht lesbar ist (Grund im Log, ohne Wert)."""
    tresor = _tresor_oder_none(tresor)
    if tresor is None:
        if _einmal("ohne_kek"):
            logger.error("WAMO_SCHLUESSEL_KEK fehlt: gespeicherter Labor-Schlüssel nicht nutzbar")
        return None
    try:
        return tresor.entschluesseln(BINDUNG, zeile["claude_schluessel"], SCHLUESSEL), zeile["claude_workspace"] or None
    except SchluesselFehler as e:
        if _einmal("chiffrat"):
            logger.error("Gespeicherter Labor-Schlüssel nicht lesbar ({}): es gilt der Schlüssel des Servers", e)
        return None


async def schluessel_fuer_labor(*, db: Database | None = None, tresor: Tresor | None = None) -> tuple[str, str | None] | None:
    """Der gespeicherte Schlüssel und sein Workspace für Laborsitzungen, sonst None (dann gilt der Schlüssel des Servers). Je Prozess
    höchstens alle CACHE_SECS Sekunden aus der Datenbank gelesen, gleichzeitige Aufrufe teilen sich eine Abfrage. Wirft nie: jeder Fehler
    heißt "kein gespeicherter Schlüssel" und gilt kurz (FEHLER_CACHE_SECS)."""
    global _cache
    jetzt = time.monotonic()
    if _cache is not None and jetzt - _cache[0] < CACHE_SECS:
        return _cache[1]
    try:
        db = db or shared_database()
    except ValueError:
        return None
    if not db.configured:
        return None
    async with _lock():
        jetzt = time.monotonic()
        if _cache is not None and jetzt - _cache[0] < CACHE_SECS:
            return _cache[1]
        wert: tuple[str, str | None] | None = None
        gemerkt = jetzt
        try:
            zeile = await _zeile(db)
            wert = _entschluesseln(zeile, tresor) if zeile is not None else None
        except (DatabaseUnavailable, *DB_ERRORS) as e:
            gemerkt = jetzt - CACHE_SECS + FEHLER_CACHE_SECS
            if _einmal("lesen"):
                logger.warning("Labor-Schlüssel nicht lesbar ({}): es gilt der Schlüssel des Servers", type(e).__name__)
        _cache = (gemerkt, wert)
        return wert


def _zeit(wert: object) -> str | None:
    return wert.isoformat(timespec="seconds") if hasattr(wert, "isoformat") else None


async def stand(*, db: Database | None = None, tresor: Tresor | None = None) -> LaborStand:
    """Der Stand für die Oberfläche, frisch aus der Datenbank (nie aus dem Zwischenspeicher): quelle ist das, was eine neue Laborsitzung
    wirklich nimmt. Ein gespeicherter Schlüssel, den der Kern nicht lesen kann, zählt nicht als gespeichert und bekommt einen Hinweis."""
    db = db or shared_database()
    if not db.configured:
        raise LaborZugangFehler("datenbank", "Keine Datenbank eingerichtet", 503)
    try:
        zeile = await _zeile(db)
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("Labor-Zugang: Stand nicht lesbar ({})", type(e).__name__)
        raise LaborZugangFehler("datenbank", "Die Datenbank antwortet gerade nicht", 503) from None
    hinweis = None
    if zeile is not None:
        if _entschluesseln(zeile, tresor) is not None:
            return LaborStand("gespeichert", zeile["endet_auf"], zeile["claude_workspace"], _zeit(zeile["gesetzt_am"]),
                              _zeit(zeile["geprueft_am"]))
        hinweis = ("Ein Schlüssel ist gespeichert, der Kern kann ihn aber nicht lesen (Hauptschlüssel oder Chiffrat prüfen). "
                   "Bis das gelöst ist, gilt der Schlüssel des Servers.")
    server = server_schluessel()
    if server:
        return LaborStand("server", ende(server), server_workspace(), hinweis=hinweis)
    return LaborStand("keiner", hinweis=hinweis or "Es gibt keinen Claude-Schlüssel für das Labor: Die Laborsitzungen laufen über Hausmodelle.")


# ---------- Prüfen, setzen, entfernen ----------
async def schluessel_pruefen(schluessel: str, workspace: str | None) -> None:
    """Kleine Testanfrage bei Anthropic (Modellliste, ohne Verbrauch, ohne Wiederholen). Wirft LaborZugangFehler mit einem Satz für die
    Person; kein Satz und kein Log enthält den Schlüssel, und die Ausnahme der Bibliothek wird nicht weitergereicht (from None)."""
    kopf = {"anthropic-workspace-id": workspace} if workspace else None
    client = anthropic.AsyncAnthropic(api_key=schluessel, default_headers=kopf, max_retries=0,
                                      timeout=anthropic.Timeout(TEST_TIMEOUT_SECS, connect=3.0))
    try:
        await client.models.list(limit=1)
    except anthropic.AuthenticationError:
        raise LaborZugangFehler("schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401): Er ist ungültig, widerrufen oder gehört "
                                "zu einem anderen Konto. Bitte in der Anthropic-Konsole prüfen oder einen neuen erzeugen.") from None
    except anthropic.PermissionDeniedError:
        raise LaborZugangFehler("schluessel_abgelehnt", "Der Schlüssel darf die Modelle nicht abfragen (403): Workspace oder "
                                "Berechtigung in der Anthropic-Konsole prüfen.") from None
    except anthropic.BadRequestError as e:
        if "workspace" in str(getattr(e, "message", "") or "").lower():
            raise LaborZugangFehler("schluessel_abgelehnt", "Dieser Schlüssel gehört zu keinem Workspace: Trag die Workspace-ID "
                                    "(beginnt mit wrkspc_) ein oder erzeuge einen Schlüssel innerhalb eines Workspace.") from None
        raise LaborZugangFehler("schluessel_abgelehnt", "Anthropic lehnt die Testanfrage ab (400): Schlüssel und Workspace-ID in der "
                                "Anthropic-Konsole prüfen.") from None
    except anthropic.APITimeoutError:
        raise LaborZugangFehler("anthropic_nicht_erreichbar", f"Anthropic hat nicht rechtzeitig geantwortet (Zeitüberschreitung nach "
                                f"{TEST_TIMEOUT_SECS:.0f} s). Bitte gleich noch einmal versuchen.", 502) from None
    except anthropic.APIConnectionError:
        raise LaborZugangFehler("anthropic_nicht_erreichbar", "Anthropic ist gerade nicht erreichbar. Bitte gleich noch einmal "
                                "versuchen.", 502) from None
    except anthropic.APIStatusError as e:
        raise LaborZugangFehler("anthropic_fehler", f"Anthropic antwortet mit HTTP {e.status_code}. Bitte später noch einmal "
                                "versuchen.", 502) from None
    except anthropic.APIError:
        raise LaborZugangFehler("anthropic_fehler", "Die Testanfrage bei Anthropic ist fehlgeschlagen. Bitte später noch einmal "
                                "versuchen.", 502) from None
    finally:
        await client.close()


def _sql(vorlage: str, db: Database) -> str:
    return vorlage.format(t=db.t("labor_zugang"), a=db.t("actions"), risk=db.t("risk_class"), status=db.t("action_status"))


def _db_fehler(e: Exception, was: str) -> LaborZugangFehler:
    """Datenbankfehler als Satz, ohne Meldung der Datenbank (sie könnte Parameter nennen)."""
    if isinstance(e, asyncpg.UndefinedTableError):
        return LaborZugangFehler("nicht_eingerichtet", "Die Datenbank kennt den Claude-Zugang des Labors noch nicht (Migration 0032).", 503)
    if isinstance(e, asyncpg.InsufficientPrivilegeError):
        return LaborZugangFehler("nicht_eingerichtet", "Der Kern darf den Claude-Zugang des Labors nicht schreiben (Migration 0032).", 503)
    if isinstance(e, asyncpg.CheckViolationError):
        return LaborZugangFehler("schluessel_ungueltig", "Die Datenbank hat den Schlüssel abgelehnt (Länge, Format oder Workspace).", 400)
    logger.warning("Labor-Zugang: {} fehlgeschlagen ({})", was, type(e).__name__)
    return LaborZugangFehler("datenbank", "Die Datenbank hat nicht sauber geantwortet. Bitte den Stand prüfen und noch einmal versuchen.", 503)


async def setzen(admin_id: str, schluessel_roh: object, workspace_roh: object = None, *, db: Database | None = None,
                 tresor: Tresor | None = None, testen=schluessel_pruefen) -> LaborStand:
    """Prüft das Format, fragt Anthropic (testen), verschlüsselt und speichert den Schlüssel samt Protokollzeile. Wirft LaborZugangFehler.
    Der Aufrufer (labor_zugang_api.py) hat Admin, zweiten Faktor und Bremse schon geprüft. Gespeichert wird nur nach erfolgreicher Testanfrage."""
    uid = normalize_uuid(admin_id)
    if uid is None:
        raise LaborZugangFehler("nicht_angemeldet", "Das Profil ist ungültig.", 401)
    db = db or shared_database()
    if not db.configured:
        raise LaborZugangFehler("datenbank", "Keine Datenbank: der Schlüssel kann nicht gespeichert werden.", 503)
    tresor = tresor if tresor is not None else _tresor_oder_none(None)
    if tresor is None:
        raise LaborZugangFehler("kein_hauptschluessel", "Der Kern hat keinen Hauptschlüssel (WAMO_SCHLUESSEL_KEK): Ein Schlüssel kann "
                                "nicht verschlüsselt gespeichert werden.", 503)
    try:
        schluessel = format_pruefen(schluessel_roh)
    except SchluesselFehler as e:
        raise LaborZugangFehler("schluessel_ungueltig", str(e)) from None
    workspace = str(workspace_roh or "").strip() or None
    if workspace and not _WORKSPACE.fullmatch(workspace):
        raise LaborZugangFehler("workspace_ungueltig", "Die Workspace-ID beginnt mit wrkspc_.")
    await testen(schluessel, workspace)
    chiffre = tresor.verschluesseln(BINDUNG, schluessel, SCHLUESSEL)
    try:
        geschrieben = await db.fetchval(_sql(_SQL_SETZEN, db), chiffre, workspace, ende(schluessel), uid, WERKZEUG_SETZEN, GRUND_SETZEN)
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        raise _db_fehler(e, "Setzen") from None
    if geschrieben is None:
        raise LaborZugangFehler("datenbank", "Die Datenbank hat nichts gespeichert. Bitte den Stand prüfen.", 503)
    cache_leeren()
    logger.info("Claude-Zugang des Labors von Admin {} gesetzt", uid[:8])  # nie auch nur Teile des Schlüssels loggen
    return await stand(db=db, tresor=tresor)


async def entfernen(admin_id: str, *, db: Database | None = None, tresor: Tresor | None = None) -> LaborStand:
    """Löscht den gespeicherten Schlüssel (samt Protokollzeile); danach gilt wieder der Schlüssel des Servers. Ohne gespeicherten Schlüssel
    ändert sich nichts und es entsteht keine Protokollzeile."""
    uid = normalize_uuid(admin_id)
    if uid is None:
        raise LaborZugangFehler("nicht_angemeldet", "Das Profil ist ungültig.", 401)
    db = db or shared_database()
    if not db.configured:
        raise LaborZugangFehler("datenbank", "Keine Datenbank eingerichtet", 503)
    try:
        weg = await db.fetchval(_sql(_SQL_ENTFERNEN, db), uid, WERKZEUG_ENTFERNEN, GRUND_ENTFERNEN)
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        raise _db_fehler(e, "Entfernen") from None
    cache_leeren()
    if weg is not None:
        logger.info("Claude-Zugang des Labors von Admin {} entfernt", uid[:8])
    return await stand(db=db, tresor=tresor)
