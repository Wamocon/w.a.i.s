"""Prüfliste der Ersteinrichtung für den Abschnitt "Erste Schritte" der Oberfläche (Planpapier docs/ausrollen-neue-nutzer.md 4.3).

  GET /wamo/api/einrichtung/stand   Stand der Einrichtung des eigenen Profils, nur lesen

Antwort: {"punkte": [{"id": ..., "stufe": "gruen" | "rot" | "hinweis", "text": ...}, ...], "geprueft": "<ISO-8601 UTC>"}, die Punkte
immer vollständig und in der Reihenfolge von PUNKTE. Jeder Punkt trägt einen kurzen Satz für Menschen, auch wenn er grün ist. Was die
App selbst prüft (Version, Host-Umgebung, Mikrofon, Tunnelstatus am Laptop), steht nicht hier.

Sicherheit
  * Wie alle Routen unter /wamo/api: Token mit zweitem Faktor (aal2), Höchstalter der Anmeldung, aktives Profil
    (wamo_api.identitaet). Das Profil kommt nur aus der geprüften Identität, nie aus Body oder Headern.
  * Laborprofile bekommen 403, bevor irgendeine Quelle gefragt wird (die Middleware lässt den Pfad für sie ohnehin nicht durch).
  * Nur lesen. Die Tunnelprüfung liest Gerät, Ordner, Dateien und Fingerabdruck wie pc_geraet.pc_zugang_fuer, aber ohne dessen
    Rechteprüfung, und nur für das eigene Gerät. Mit dem Socket verbindet sie sich allein, um per SO_PEERCRED zu prüfen, dass genau
    der Tunnelbenutzer lauscht, und schließt ihn sofort: kein Byte an den Laptop, kein MCP-Start, kein Werkzeugaufruf, keine
    PC-Sperre, keine Aufrufgrenze, kein Zugang für eine Sitzung. Die gelesenen Geheimnisse verlassen dateien_pruefen nie.
    Der connect auf pc.sock öffnet über den SSH-Rücktunnel am Laptop kurz eine TCP-Verbindung zum Host, die sofort wieder endet
    (kein Byte auf Anwendungsebene).
  * Antworten nennen nie Werte, Schlüssel, Pfade oder Datenbankmeldungen. Wirft eine Quelle oder fehlt etwas, das nur am Server
    prüfbar ist, wird der Punkt rot mit einem ehrlichen Satz; nach außen geht keine Ausnahme. Im Log steht nur der Fehlertyp.
  * Fristen: jede Quelle höchstens QUELLE_SECS, die ganze Prüfung höchstens GESAMT_SECS. Was dann offen ist oder trotz eigener
    Absicherung wirft, wird rot mit dem Satz "lässt sich gerade nicht prüfen" (UNKLAR).
  * Drosselung: Ein Ergebnis gilt je Profil 10 Sekunden (Knopf "Erneut prüfen"), auch ein unvollständiges; gleichzeitige Aufrufe
    teilen sich eine Prüfung. Cache-Control: no-store.

Quellen (Funktionen auf Modulebene, die Tests ersetzen): erstanmeldung_stand (Paket P1b dockt nur dort an), aktives_geraet und
geraete_status (Register devices), dateien_pruefen und gegenstelle_pruefen (Tunnel), modellzugang_stand (model_access),
soniox_gesetzt, entwicklung_problem und abdruck_vorhanden (speakers). Rechte nach heutigem Stand (WAMO_PC_MITGLIEDER,
entwicklung_betrieb); mit rechte.py (P4, P5) fragt die Prüfliste dort.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal, TypedDict

from fastapi import APIRouter, HTTPException, Request, Response
from loguru import logger

import boss
import dev_agent
import entwicklung_betrieb
import labor
import modellzugang as mz
import pc_geraet
import pc_host
import pc_tunnel
import sprache_anbieter
import stimme_speicher
from auth_gate import Identity
from geraete_register import Geraet, GeraeteRegister, RegisterFehler
from memory import DatabaseUnavailable, MemoryStore, normalize_uuid, shared_database
from wamo_api import identitaet

router = APIRouter()

Stufe = Literal["gruen", "rot", "hinweis"]


class Punkt(TypedDict):
    id: str
    stufe: Stufe
    text: str


class StandAntwort(TypedDict):
    punkte: list[Punkt]
    geprueft: str


PUNKTE = ("passwort", "geraet", "tunnel", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc")
GRUEN: Stufe = "gruen"
ROT: Stufe = "rot"
HINWEIS: Stufe = "hinweis"
ZWISCHENSPEICHER_SECS = 10.0
MAX_ZWISCHENSPEICHER = 500
QUELLE_SECS = 5.0  # eine Abfrage der Datenbank oder das Lesen der Dateien des Geräts
GESAMT_SECS = 8.0  # die ganze Prüfung
SOCKET_SECS = pc_tunnel.CONNECT_TIMEOUT_SECS
NO_STORE = {"Cache-Control": "no-store"}
GEGENSTELLE = pc_tunnel.GegenstellenPruefung  # Backend mit Prüfung per SO_PEERCRED (Tests ersetzen nur das Lesen der uid)

SATZ_PASSWORT_OK = "Passwort gewechselt."
SATZ_PASSWORT_KEINE = "Kein Passwortwechsel nötig."
SATZ_PASSWORT_ROT = "Bitte zuerst dein Passwort ändern."
SATZ_PASSWORT_UNKLAR = "Der Stand deines Passworts lässt sich gerade nicht prüfen."
SATZ_GERAET_OK = "Dein Laptop ist gebunden und freigegeben."
SATZ_GERAET_WARTET = "Dein Laptop wartet auf die Freigabe durch einen Admin."
SATZ_GERAET_GESPERRT = "Dein Laptop ist gesperrt, bitte wende dich an einen Admin."
SATZ_GERAET_FEHLT = "Dein Laptop ist noch nicht eingerichtet. Melde dich in der Desktop-App an."
SATZ_GERAET_FEHLER = "Das Geräteregister ist gerade nicht erreichbar."
SATZ_TUNNEL_OK = "Der Tunnel zu deinem Laptop steht."
SATZ_TUNNEL_ROT = "Der Tunnel steht nicht. Bist du im Büronetz?"
SATZ_TUNNEL_OHNE_GERAET = "Ohne freigegebenen Laptop gibt es keinen Tunnel."
SATZ_TUNNEL_UNKLAR = "Der Tunnel lässt sich gerade nicht prüfen."
SATZ_TUNNEL_AUS = "Der Tunnel je Laptop ist am Server nicht eingeschaltet."
SATZ_STIMME_OK = "Die Stimme läuft über Soniox."
SATZ_STIMME_FEHLT = "Die Stimme ist am Server nicht eingerichtet."
SATZ_STIMME_HAUS = "Dein Profil nutzt für die Stimme die Hausmodelle statt Soniox."
SATZ_STIMME_UNKLAR = "Die Einstellung deiner Stimme lässt sich gerade nicht lesen."
SATZ_GESPRAECH_OK = "Dein eigener Claude-Schlüssel ist hinterlegt."
SATZ_GESPRAECH_HAUS = "Ohne eigenen Schlüssel spricht W.A.I.S. mit den Hausmodellen."
SATZ_GESPRAECH_WAHL = "Du hast die Hausmodelle gewählt, W.A.I.S. spricht ohne Claude."
SATZ_GESPRAECH_FESTGELEGT = "Ein Admin hat für dein Profil die Hausmodelle festgelegt."
SATZ_GESPRAECH_ZUORDNUNG = "W.A.I.S. nutzt übergangsweise den Claude-Schlüssel des Servers."
SATZ_GESPRAECH_UNKLAR = "Dein Modellzugang lässt sich gerade nicht lesen."
SATZ_ENT_OK = "Entwicklungsaufträge sind für dein Profil freigeschaltet."
SATZ_ENT_MITGLIED = "Entwicklungsaufträge sind für dein Profil noch nicht freigeschaltet."
SATZ_ENT_AUS = "Entwicklungsaufträge sind am Server ausgeschaltet."
SATZ_ENT_PROBLEM = "Die Einstellungen für Entwicklungsaufträge am Server sind nicht in Ordnung."
SATZ_ENT_KEIN_ZUGANG = "Für Entwicklungsaufträge fehlt dein eigener Zugang zu Claude Code (Karte Modellzugang)."
SATZ_ENT_UNKLAR = "Entwicklungsaufträge lassen sich gerade nicht prüfen."
SATZ_ABDRUCK_OK = "Dein Stimmabdruck ist eingelernt."
SATZ_ABDRUCK_FEHLT = "Ohne Stimmabdruck nimmt W.A.I.S. PC-Befehle nur getippt an."
SATZ_ABDRUCK_UNKLAR = "Der Stimmabdruck lässt sich gerade nicht prüfen."
SATZ_PC_OK = "PC-Steuerung ist für dein Profil bereit."
SATZ_PC_NICHT_FREI = "PC-Steuerung ist für dein Profil noch nicht freigeschaltet."
SATZ_PC_AUS = "PC-Steuerung ist am Server ausgeschaltet."
SATZ_PC_NICHT_ERREICHBAR = "PC-Steuerung geht erst, wenn der Tunnel zu deinem Laptop steht."
SATZ_PC_UNKLAR = "Die PC-Steuerung lässt sich gerade nicht prüfen."

# Satz für einen Punkt, der bis zur Frist offen blieb oder an einem unerwarteten Fehler scheiterte
UNKLAR = {"passwort": SATZ_PASSWORT_UNKLAR, "geraet": SATZ_GERAET_FEHLER, "tunnel": SATZ_TUNNEL_UNKLAR,
          "stimme": SATZ_STIMME_UNKLAR, "gespraech": SATZ_GESPRAECH_UNKLAR, "entwicklung": SATZ_ENT_UNKLAR,
          "stimmabdruck": SATZ_ABDRUCK_UNKLAR, "pc": SATZ_PC_UNKLAR}
# Quelle des Modellzugangs (modellzugang.Stand.quelle) -> Stufe und Satz; "profil" mit Claude ist grün
GESPRAECH: dict[str, tuple[Stufe, str]] = {
    "keiner": (HINWEIS, SATZ_GESPRAECH_HAUS), "wahl": (HINWEIS, SATZ_GESPRAECH_WAHL),
    "festgelegt": (HINWEIS, SATZ_GESPRAECH_FESTGELEGT), "zuordnung": (HINWEIS, SATZ_GESPRAECH_ZUORDNUNG)}

_uhr = time.monotonic
_zwischenspeicher: dict[tuple[str, str], tuple[float, StandAntwort]] = {}
_laufend: dict[tuple[str, str], asyncio.Future[StandAntwort]] = {}


# ---------- Quellen (Tests ersetzen sie) ----------
def erstanmeldung_stand(identity: Identity) -> object:
    """Stand der Erstanmeldung (Paket P1b: erledigt, keine, offen, ...). Bis P1b ihn an die Identität hängt, fehlt er: None."""
    return getattr(identity, "erstanmeldung", None)


async def aktives_geraet(user_id: str) -> Geraet | None:
    """Das eine aktive persönliche Gerät des Profils (Leseweg des Kerns, geraete_register.py). Wirft RegisterFehler."""
    return await GeraeteRegister(shared_database()).aktives_geraet(user_id)


async def geraete_status(user_id: str) -> frozenset[str]:
    """Status der persönlichen Geräte des Profils (beantragt, gesperrt, widerrufen), nur wenn kein aktives da ist."""
    db, uid = shared_database(), normalize_uuid(user_id)
    if not db.configured or uid is None:
        raise RegisterFehler("Register nicht verfügbar")
    zeilen = await db.fetch(f"select distinct d.status::text as status from {db.t('devices')} d "
                            f"where d.user_id = $1::uuid and d.art = 'persoenlich' limit 8", uid)
    return frozenset(z["status"] for z in zeilen)


async def dateien_pruefen(geraet: Geraet) -> tuple[str, int]:
    """Wurzel, Ordner, Dateien und Fingerabdruck des eigenen Geräts, gelesen wie pc_geraet.pc_zugang_fuer, ohne dessen
    Rechteprüfung. Liefert Socket und uid des Tunnelbenutzers; die Geheimnisse werden verworfen. Wirft bei jeder Abweichung."""
    wurzel = pc_geraet.socket_wurzel()
    uid = pc_geraet._uid_von(geraet.benutzer)
    await asyncio.wait_for(asyncio.to_thread(pc_geraet.lies_geheimnisse, geraet, wurzel, uid=uid), QUELLE_SECS)
    return f"{wurzel}/{geraet.ordner}/pc.sock", uid


async def gegenstelle_pruefen(pfad: str, uid: int) -> None:
    """Verbindet mit dem Socket, prüft per SO_PEERCRED, dass genau der Tunnelbenutzer lauscht (pc_tunnel.pruefe_gegenstelle),
    und schließt sofort, auch bei Abbruch. Sendet und liest kein Byte. Wirft, wenn der Socket fehlt, die Gegenstelle nicht passt
    oder SOCKET_SECS ablaufen (eine einzige Frist)."""
    strom = None
    try:
        async with asyncio.timeout(SOCKET_SECS):
            strom = await GEGENSTELLE(uid).connect_unix_socket(pfad)
    finally:
        if strom is not None:
            await asyncio.shield(strom.aclose())


async def modellzugang_stand(user_id: str) -> mz.Stand:
    """Stand des Modellzugangs ohne Entschlüsseln (modellzugang.stand_laden). Wirft, wenn die Datenbank fehlt."""
    db = shared_database()
    if not db.configured:
        raise DatabaseUnavailable("Datenbank nicht eingerichtet")
    return await mz.stand_laden(user_id, db=db)


def soniox_gesetzt() -> bool:
    """Ist der Soniox-Schlüssel am Server gesetzt? Nur ob, nie der Wert."""
    return bool((os.getenv("SONIOX_API_KEY") or "").strip())


def entwicklung_problem() -> str | None:
    """Grund aus den Einstellungen des Servers (dev_agent.entwicklung_problem, liest Dateien). Der Text geht nie in die Antwort."""
    return dev_agent.entwicklung_problem()


async def abdruck_vorhanden(user_id: str) -> bool | None:
    """Ist ein Stimmabdruck eingelernt (Leseweg stimme_speicher.abdruck_laden)? None, wenn das unklar ist."""
    ok, abdruck = await stimme_speicher.abdruck_laden(MemoryStore.from_env(user_id))
    return (abdruck is not None) if ok else None


# ---------- Punkte ----------
def _punkt(punkt_id: str, stufe: Stufe, text: str) -> Punkt:
    return {"id": punkt_id, "stufe": stufe, "text": text}


def _fehler(punkt_id: str, satz: str, fehler: BaseException) -> Punkt:
    logger.warning("Einrichtung: Punkt {} nicht prüfbar ({})", punkt_id, type(fehler).__name__)
    return _punkt(punkt_id, ROT, satz)


def _satz(text: str) -> str:
    return " ".join(text.split()).rstrip(".") + "."


def _passwort(ich: Identity) -> Punkt:
    try:
        stand = erstanmeldung_stand(ich)
        if stand is None or stand == "keine":
            return _punkt("passwort", GRUEN, SATZ_PASSWORT_KEINE)
        if stand == "erledigt":
            return _punkt("passwort", GRUEN, SATZ_PASSWORT_OK)
    except Exception as e:  # noqa: BLE001 (jede Quelle darf scheitern, der Punkt wird rot)
        return _fehler("passwort", SATZ_PASSWORT_UNKLAR, e)
    return _punkt("passwort", ROT, SATZ_PASSWORT_ROT)


async def _geraet_fehlt(user_id: str) -> Punkt:
    try:
        status = await asyncio.wait_for(geraete_status(user_id), QUELLE_SECS)
    except Exception as e:  # noqa: BLE001
        return _fehler("geraet", SATZ_GERAET_FEHLER, e)
    if "beantragt" in status:
        return _punkt("geraet", ROT, SATZ_GERAET_WARTET)
    if "gesperrt" in status:
        return _punkt("geraet", ROT, SATZ_GERAET_GESPERRT)
    return _punkt("geraet", ROT, SATZ_GERAET_FEHLT)


async def _tunnel(geraet: Geraet) -> tuple[Punkt, bool]:
    if not pc_geraet.register_modus():
        return _punkt("tunnel", ROT, SATZ_TUNNEL_AUS), False
    try:
        pfad, uid = await dateien_pruefen(geraet)
        await gegenstelle_pruefen(pfad, uid)
    except Exception as e:  # noqa: BLE001 (Ordner, Dateien, Fingerabdruck, Socket oder Gegenstelle passen nicht)
        if isinstance(e, (pc_geraet.PcGeraetFehler, pc_tunnel.GegenstelleFalsch)):  # beide Texte nennen nie Werte
            logger.warning("WAMO-GERAET Einrichtung: Tunnel von Gerät {} steht nicht: {}", geraet.kennung, e)
        else:
            logger.info("WAMO-GERAET Einrichtung: Tunnel von Gerät {} steht nicht ({})", geraet.kennung, type(e).__name__)
        return _punkt("tunnel", ROT, SATZ_TUNNEL_ROT), False
    return _punkt("tunnel", GRUEN, SATZ_TUNNEL_OK), True


async def _geraet_und_tunnel(user_id: str, fertig: dict[str, Punkt]) -> bool:
    """Trägt geraet und tunnel ein, sobald sie feststehen. Liefert, ob der eigene Laptop erreichbar ist."""
    try:
        geraet = await asyncio.wait_for(aktives_geraet(user_id), QUELLE_SECS)
    except Exception as e:  # noqa: BLE001
        fertig["geraet"] = _fehler("geraet", SATZ_GERAET_FEHLER, e)
        fertig["tunnel"] = _punkt("tunnel", ROT, SATZ_TUNNEL_UNKLAR)
        return False
    if geraet is None:
        fertig["geraet"] = await _geraet_fehlt(user_id)
        fertig["tunnel"] = _punkt("tunnel", ROT, SATZ_TUNNEL_OHNE_GERAET)
        return False
    fertig["geraet"] = _punkt("geraet", GRUEN, SATZ_GERAET_OK)
    fertig["tunnel"], erreichbar = await _tunnel(geraet)
    return erreichbar


async def _modellzugang(user_id: str) -> mz.Stand | None:
    try:
        return await asyncio.wait_for(modellzugang_stand(user_id), QUELLE_SECS)
    except Exception as e:  # noqa: BLE001 (gespraech, stimme und entwicklung werden dann ehrlich rot)
        logger.warning("Einrichtung: Modellzugang nicht lesbar ({})", type(e).__name__)
        return None


def _stimme(stand: mz.Stand | None) -> Punkt:
    """Erst die Wahl (Umgebung vor Profil, wie die Sitzung), den Soniox-Schlüssel nur verlangen, wenn Soniox gewählt ist."""
    if stand is None:
        return _punkt("stimme", ROT, SATZ_STIMME_UNKLAR)
    try:
        wahl = {sprache_anbieter.gewuenscht(b, getattr(stand, b)) for b in ("stt", "tts")}
        schluessel_fehlt = "soniox" in wahl and not soniox_gesetzt()
    except Exception as e:  # noqa: BLE001
        return _fehler("stimme", SATZ_STIMME_UNKLAR, e)
    if schluessel_fehlt:
        return _punkt("stimme", ROT, SATZ_STIMME_FEHLT)
    return _punkt("stimme", GRUEN, SATZ_STIMME_OK) if wahl == {"soniox"} else _punkt("stimme", HINWEIS, SATZ_STIMME_HAUS)


def _gespraech(stand: mz.Stand | None) -> Punkt:
    if stand is None:
        return _punkt("gespraech", ROT, SATZ_GESPRAECH_UNKLAR)
    if stand.art == "claude" and stand.quelle == "profil":
        return _punkt("gespraech", GRUEN, SATZ_GESPRAECH_OK)
    return _punkt("gespraech", *GESPRAECH.get(stand.quelle, (HINWEIS, SATZ_GESPRAECH_HAUS)))


async def _entwicklung_grund(ich: Identity, stand: mz.Stand | None) -> str | None:
    """Warum Entwicklungsaufträge für dieses Admin-Profil aus sind, oder None. Dieselbe Folge wie bot.build_session: Schalter,
    Einstellungen, Profilbindung (entwicklung_betrieb.grund_vorab im Büro), dann der eigene Zugang (boss.entwicklung_quelle)."""
    im_buero, an = pc_host.buero(), dev_agent.entwicklung_enabled()
    problem = await asyncio.wait_for(asyncio.to_thread(entwicklung_problem), QUELLE_SECS) if an else None
    if im_buero:
        grund = entwicklung_betrieb.grund_vorab(ich.user_id, True, problem)
        if grund is not None:
            return SATZ_ENT_PROBLEM if grund == problem else _satz(grund)  # das Problem nennt Variablen, nie in die Antwort
    elif not an:
        return SATZ_ENT_AUS
    elif problem:
        return SATZ_ENT_PROBLEM
    if stand is None:
        return SATZ_ENT_UNKLAR
    quelle = boss.entwicklung_quelle(SimpleNamespace(art=stand.art, quelle=stand.quelle, claude_code=stand.code_hinterlegt))
    fehlt = entwicklung_betrieb.grund_quelle(quelle) is not None if im_buero else quelle == "keine"
    return SATZ_ENT_KEIN_ZUGANG if fehlt else None


async def _entwicklung(ich: Identity, stand: mz.Stand | None) -> Punkt:
    if not ich.is_admin:  # heute nur Admins (P5: rechte.entwicklung_erlaubt)
        return _punkt("entwicklung", HINWEIS, SATZ_ENT_MITGLIED)
    try:
        grund = await _entwicklung_grund(ich, stand)
    except Exception as e:  # noqa: BLE001
        return _fehler("entwicklung", SATZ_ENT_UNKLAR, e)
    return _punkt("entwicklung", ROT, grund) if grund else _punkt("entwicklung", GRUEN, SATZ_ENT_OK)


async def _stimmabdruck(user_id: str) -> Punkt:
    try:
        da = await asyncio.wait_for(abdruck_vorhanden(user_id), QUELLE_SECS)
    except Exception as e:  # noqa: BLE001
        return _fehler("stimmabdruck", SATZ_ABDRUCK_UNKLAR, e)
    if da is None:
        return _punkt("stimmabdruck", ROT, SATZ_ABDRUCK_UNKLAR)
    return _punkt("stimmabdruck", GRUEN, SATZ_ABDRUCK_OK) if da else _punkt("stimmabdruck", HINWEIS, SATZ_ABDRUCK_FEHLT)


def _pc(ich: Identity, erreichbar: bool) -> Punkt:
    """Heute: Admins, Mitglieder nur mit WAMO_PC_MITGLIEDER (wie pc_geraet.pc_zugang_fuer; P4: rechte.pc_stufe)."""
    try:
        if not (ich.is_admin or pc_geraet.mitglieder_erlaubt()):
            return _punkt("pc", ROT, SATZ_PC_NICHT_FREI)
        if not pc_host.pc_host_enabled():
            return _punkt("pc", ROT, SATZ_PC_AUS)
    except Exception as e:  # noqa: BLE001
        return _fehler("pc", SATZ_PC_UNKLAR, e)
    return _punkt("pc", GRUEN, SATZ_PC_OK) if erreichbar else _punkt("pc", ROT, SATZ_PC_NICHT_ERREICHBAR)


async def _alle_punkte(ich: Identity, fertig: dict[str, Punkt]) -> None:
    """Trägt jeden Punkt in fertig ein, sobald er feststeht. Wirft eine Teilprüfung, bricht die TaskGroup die anderen ab."""
    fertig["passwort"] = _passwort(ich)
    erreichbar = False

    async def geraet_und_tunnel() -> None:
        nonlocal erreichbar
        erreichbar = await _geraet_und_tunnel(ich.user_id, fertig)

    async def zugang() -> None:
        stand = await _modellzugang(ich.user_id)
        fertig["stimme"], fertig["gespraech"] = _stimme(stand), _gespraech(stand)
        fertig["entwicklung"] = await _entwicklung(ich, stand)

    async def abdruck() -> None:
        fertig["stimmabdruck"] = await _stimmabdruck(ich.user_id)

    async with asyncio.TaskGroup() as gruppe:
        gruppe.create_task(geraet_und_tunnel())
        gruppe.create_task(zugang())
        gruppe.create_task(abdruck())
    fertig["pc"] = _pc(ich, erreichbar)


async def _pruefen(ich: Identity) -> StandAntwort:
    """Alle Punkte in fester Reihenfolge, höchstens GESAMT_SECS lang. Wirft nie: Offene Punkte werden rot (UNKLAR)."""
    fertig: dict[str, Punkt] = {}
    try:
        async with asyncio.timeout(GESAMT_SECS):
            await _alle_punkte(ich, fertig)
    except TimeoutError:
        logger.warning("Einrichtung: Frist von {} s abgelaufen (offen: {})", GESAMT_SECS,
                       ", ".join(p for p in PUNKTE if p not in fertig))
    except Exception as e:  # noqa: BLE001 (Auffangschutz: eine Teilprüfung warf trotz eigener Absicherung)
        teile = e.exceptions if isinstance(e, BaseExceptionGroup) else (e,)
        logger.error("Einrichtung: Prüfung abgebrochen ({})", ", ".join(type(t).__name__ for t in teile))
    punkte = [fertig.get(pid) or _punkt(pid, ROT, UNKLAR[pid]) for pid in PUNKTE]
    rot = [p["id"] for p in punkte if p["stufe"] == ROT]
    logger.info("Einrichtung: Stand geprüft (Profil {}, rot: {})", ich.user_id[:8], ", ".join(rot) or "nichts")
    return {"punkte": punkte, "geprueft": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}


# ---------- Zwischenspeicher und Route ----------
def _merken(schluessel: tuple[str, str], lauf: asyncio.Future[StandAntwort]) -> None:
    """Rückruf am Ende einer Prüfung: aus _laufend nehmen und das Ergebnis speichern. Beim Schreiben fallen abgelaufene Einträge
    weg; ist der Speicher dann noch voll, nur der älteste."""
    if _laufend.get(schluessel) is lauf:
        del _laufend[schluessel]
    if lauf.cancelled() or lauf.exception() is not None:
        return
    jetzt = _uhr()
    for k in [k for k, (t, _) in _zwischenspeicher.items() if jetzt - t >= ZWISCHENSPEICHER_SECS]:
        del _zwischenspeicher[k]
    if schluessel not in _zwischenspeicher and len(_zwischenspeicher) >= MAX_ZWISCHENSPEICHER:
        del _zwischenspeicher[min(_zwischenspeicher, key=lambda k: _zwischenspeicher[k][0])]
    _zwischenspeicher[schluessel] = (jetzt, lauf.result())


async def stand_fuer(ich: Identity) -> StandAntwort:
    """Stand für diese geprüfte Identität: aus dem Zwischenspeicher (10 Sekunden je Profil und Rolle), aus einer schon laufenden
    Prüfung oder neu geprüft."""
    schluessel = (ich.user_id, ich.rolle)
    treffer = _zwischenspeicher.get(schluessel)
    if treffer is not None and 0 <= _uhr() - treffer[0] < ZWISCHENSPEICHER_SECS:
        return treffer[1]
    lauf = _laufend.get(schluessel)
    if lauf is None:
        lauf = asyncio.create_task(_pruefen(ich))
        _laufend[schluessel] = lauf
        lauf.add_done_callback(lambda f: _merken(schluessel, f))
    return await asyncio.shield(lauf)  # bricht die Anfrage ab, läuft die Prüfung für die anderen weiter


@router.get("/einrichtung/stand")
async def stand(request: Request, response: Response) -> dict:  # dict: eine TypedDict-Annotation nähme FastAPI als Antwortmodell
    ich = await identitaet(request)
    response.headers["Cache-Control"] = "no-store"
    if labor.ist_labor(ich):
        raise HTTPException(403, "Die Prüfliste der Einrichtung gibt es für Laborprofile nicht", headers=NO_STORE)
    return dict(await stand_fuer(ich))
