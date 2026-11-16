"""Modellzugang je Profil: eigener Claude-Schlüssel oder nur Hausmodelle (Tabelle model_access, Migrationen 0010, 0011).

  claude  Die Person hat ihren eigenen Anthropic-API-Schlüssel hinterlegt. Standardmodell Haiku (ein Admin kann ein
          anderes festlegen). Fällt Claude aus, übernehmen die Hausmodelle mit Hinweis (llm_anbieter.py).
  haus    Ohne eigenen Schlüssel, vom Admin festgelegt (nur_haus) oder von der Person gewählt (modell_modus
          nur_haus): alles über LiteLLM und SearXNG, kein Aufruf an Anthropic, auch nicht als Rückfall. Der Zwang
          des Admins ist stärker als die Wahl der Person.

Zwei Schlüsseltypen, getrennt gespeichert und verwendet:
  API-Schlüssel      sk-ant-api…  Gespräch, Lernen, Bildschirm (Anthropic Messages API, bezahlt nach Verbrauch).
  Claude-Code-Token  sk-ant-oat…  aus `claude setup-token` (Max-Tarif); gilt nur für Entwicklungsaufträge mit Claude
                     Code, die Messages-API nimmt ihn nicht. Er wird nur auf sein Format geprüft (eine Testanfrage
                     würde Verbrauch des Max-Kontingents erzeugen) und über claude_code_zugang_fuer() nur dem
                     Entwicklungs-Agenten dieser Sitzung für genau einen Lauf übergeben.

Der Schlüssel des Kerns (ANTHROPIC_API_KEY) gehört einer Person. Er gilt nur für das Profil in
WAMO_CLAUDE_SCHLUESSEL_PROFIL (Übergang, bis sie ihn selbst hinterlegt hat) und für Laborprofile (Testlabor, Quelle
"labor": nur das Gespräch, Standardmodell Haiku, nie für Entwicklungsaufträge), nie für andere.

Schlüssel und Token liegen nur verschlüsselt in der Datenbank (schluessel.py, Hauptschlüssel WAMO_SCHLUESSEL_KEK nur
beim Kern). Sie werden nie geloggt, nie an die Oberfläche zurückgegeben (nur "hinterlegt, endet auf …abcd") und nie
in actions, turns oder im Gedächtnis gespeichert. Eine Änderung gilt ab der nächsten Sitzung.

Für Phase P5 trägt jedes Profil stt und tts (soniox oder haus). Der Strang "Stimme" liest sie aus dem Zugang der
Sitzung (Zugang.stt, Zugang.tts) und baut danach Spracherkennung und Sprachausgabe (sprache_anbieter.py). Seit Paket H5
wählt die Person beides selbst (stimme_setzen, Aktion "stimme", Migration 0023), Soniox bleibt Standard; jede Wahl steht
als Zeile in actions (Werkzeug stimme_wahl, nur die Werte). Laborprofile erreichen die Wahl nie und hören immer über Soniox.

Seit Migration 0024 (Wunsch von Niko vom 16.11.2026) wählt die Person auch ihre Modelle: je Bereich Gespräch, Bildschirm und Bilder,
Lernen und Zusammenfassung "automatisch" oder ein Modell aus der festen Liste (modellwahl.py), dazu die Stimme im Haus (eine der neun
freigegebenen Stimmen, sprache_anbieter.HAUS_STIMMEN). Der Kern prüft jede Wahl selbst (Aktion "modell" und "haus_stimme"): ein Hausprofil bekommt
nie ein Claude-Modell, eine Claude-Wahl prüft eine kleine Anfrage mit dem eigenen Schlüssel, ein vom Admin festgelegtes Profil ist für
die Modellwahl gesperrt (die Stimme bleibt wählbar), ein vom Admin gesetztes Claude-Modell ist das einzige Claude-Modell. Jede Wahl
steht als Zeile in actions (Werkzeug modell_wahl bzw. stimme_wahl) und gilt ab der nächsten Sitzung (Zugang.modell_wahl,
Zugang.tts_stimme). Beim Laden prüft der Kern die gespeicherten Werte noch einmal; was nicht mehr in der Liste steht, gilt nicht.

Kommandozeile für den Betrieb (im Ordner voice-core/, mit der Umgebung des Kerns):
  uv run python modellzugang.py kek-erzeugen          # neuer Hauptschlüssel für WAMO_SCHLUESSEL_KEK
  uv run python modellzugang.py hinterlegen --user-id <uuid> [--workspace wrkspc_...]   # liest den Schlüssel verdeckt
  uv run python modellzugang.py status --user-id <uuid>
  uv run python modellzugang.py loeschen --user-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace

import anthropic
import asyncpg
from loguru import logger

import modellwahl as mw
from llm_anbieter import STANDARD_CLAUDE, Zugang, lesbarer_modellname
from memory import DB_ERRORS, Database, DatabaseUnavailable, admin_database, normalize_uuid, shared_database
from schluessel import CODE_TOKEN, SCHLUESSEL, SchluesselFehler, Tresor, ende, format_pruefen, token_format_pruefen

ZUORDNUNG_ENV = "WAMO_CLAUDE_SCHLUESSEL_PROFIL"
LABOR_ARTEN = ("platz", "schaufenster")  # profiles.labor_art (Migration 0018); nur diese Werte geben den Server-Schlüssel frei
TEST_TIMEOUT_SECS = 10.0
VERSUCHE_JE_FENSTER = 5  # Testanfragen je Profil und Zeitfenster (Schutz vor Durchprobieren)
VERSUCHE_FENSTER_SECS = 600.0
MODI = ("automatisch", "nur_haus")
SCHLUESSELARTEN = ("api", "code")
STIMMEN = ("soniox", "haus")  # Werte für stt und tts (wie sprache_anbieter.ANBIETER und der check in Migration 0010)
STIMME_WERKZEUG = "stimme_wahl"  # Zeile in actions, wenn die Person Hören und Stimme wählt
STIMME_JE_FENSTER = 10  # Wechsel von Hören und Stimme je Profil und Zeitfenster (schützt actions vor Fluten)
MODELL_WERKZEUG = "modell_wahl"  # Zeile in actions, wenn die Person ein Modell wählt
WAHL_JE_FENSTER = 10  # Modellwahlen je Profil und Zeitfenster (schützt actions und die Testanfragen bei Anthropic)
STANDARD_STIMME = "standard"  # Aktion haus_stimme: zurück auf die Stimme des Kerns
AKTIONEN = ("hinterlegen", "loeschen", "status", "modus", "stimme", "modell", "haus_stimme")
SATZ_FESTGELEGT = "Ein Admin hat dein Profil auf Hausmodelle festgelegt. Die Modellwahl ist gesperrt."
SATZ_NICHT_FREI = ("Die eigene Wahl ist in dieser Datenbank noch nicht freigeschaltet; die Wahl gilt bis dahin automatisch. "
                   "Bitte an den Admin wenden")
_WORKSPACE = re.compile(r"wrkspc_[A-Za-z0-9]{6,60}")
_SPALTEN_ALT = ("nur_haus, claude_schluessel, claude_schluessel_ende, claude_workspace, claude_modell, "
                "claude_geprueft_at, stt, tts")
# Ab Migration 0011: Wahl der Person und Angaben zum Claude-Code-Token (das Chiffrat selbst liest nur
# claude_code_zugang_fuer, nie diese Abfrage)
_SPALTEN_0011 = _SPALTEN_ALT + ", modell_modus, claude_code_token_ende, claude_code_token_at"
# Ab Migration 0024: Modellwahl je Bereich und Stimme im Haus
_SPALTEN = _SPALTEN_0011 + ", " + ", ".join(mw.SPALTEN.values()) + ", tts_stimme"
_versuche: dict[str, list[float]] = {}
_stimme_versuche: dict[str, list[float]] = {}
_wahl_versuche: dict[str, list[float]] = {}


class ZugangFehler(Exception):
    """Hinterlegen oder Löschen ist nicht möglich. Der Text ist für die Person gedacht, ohne Schlüssel."""


@dataclass(frozen=True)
class Stand:
    """Was die Oberfläche über den Zugang erfährt. Enthält nie den Schlüssel."""

    art: str  # claude | haus (wirksam: nach Zwang des Admins und Wahl der Person)
    quelle: str  # profil | zuordnung | festgelegt | wahl | keiner
    hinterlegt: bool
    ende: str | None
    geprueft: str | None
    festgelegt: bool  # der Admin hat nur Hausmodelle festgelegt: die Wahl der Person ist gesperrt
    modell: str
    stt: str
    tts: str
    modus: str = "automatisch"  # Wahl der Person (automatisch | nur_haus), unabhängig vom Zwang des Admins
    code_hinterlegt: bool = False  # Claude-Code-Token für Entwicklungsaufträge
    code_ende: str | None = None
    code_gesetzt: str | None = None
    stimme_haus: str = "bereit"  # "bereit" oder ein Satz, warum Hören und Stimme im Haus in diesem Kern nicht gehen
    # Modellwahl (0024): je Bereich {"wahl": "automatisch" | Modell, "optionen": [...], "hinweis"?}; modell_sperre: warum gesperrt
    modelle: dict[str, dict] = field(default_factory=dict)
    modell_sperre: str | None = None
    haus_stimme: str | None = None  # Wahl der Person, None: Standard des Kerns
    haus_stimme_standard: str | None = None

    def nachricht(self, *, fehler: str | None = None, aktion: str = "status") -> dict:
        from sprache_anbieter import STIMMEN_HINWEIS, haus_stimmen  # spät, wie in stand_laden

        n = {"type": "modellzugang", "aktion": aktion, "art": self.art, "quelle": self.quelle,
             "hinterlegt": self.hinterlegt, "ende": self.ende, "geprueft": self.geprueft,
             "festgelegt": self.festgelegt, "modell": self.modell, "stt": self.stt, "tts": self.tts,
             "modus": self.modus, "code_hinterlegt": self.code_hinterlegt, "code_ende": self.code_ende,
             "code_gesetzt": self.code_gesetzt, "stimme_haus": self.stimme_haus, "wirksam": "ab der nächsten Sitzung",
             "modelle": self.modelle, "modell_sperre": self.modell_sperre, "haus_stimme": self.haus_stimme,
             "haus_stimme_standard": self.haus_stimme_standard, "haus_stimmen": haus_stimmen(),
             "haus_stimmen_hinweis": STIMMEN_HINWEIS}
        if fehler:
            n["fehler"] = fehler
        return n


def kern_zuordnung(user_id: str) -> bool:
    """Gilt der Schlüssel des Kerns (ANTHROPIC_API_KEY) für dieses Profil? Nur für genau die eine UUID in
    WAMO_CLAUDE_SCHLUESSEL_PROFIL, nie für andere."""
    ziel = normalize_uuid(os.getenv(ZUORDNUNG_ENV) or "")
    return bool(ziel) and ziel == normalize_uuid(user_id) and bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


# Fehlt eine Migration, gilt der Stand davor: der Kern darf deshalb nie alle Profile auf Hausmodelle werfen. Je Stufe die Spalten und der
# Hinweis, der einmal je Prozess ins Log geht (nicht bei jeder Abfrage)
_STUFEN = (
    (_SPALTEN, "model_access ohne Migration 0024: Modellwahl und Stimme im Haus der Person stehen nicht zur Verfügung"),
    (_SPALTEN_0011, "model_access ohne Migration 0011: Wahl der Person und Claude-Code-Token stehen nicht zur Verfügung"),
    (_SPALTEN_ALT, ""),
)
_gemeldet: set[str] = set()


async def _zeile(db: Database, user_id: str):
    for spalten, hinweis in _STUFEN:
        try:
            return await db.fetchrow(f"select {spalten} from {db.t('model_access')} where user_id = $1::uuid", user_id)
        except asyncpg.UndefinedColumnError:
            if not hinweis:
                raise
            if hinweis not in _gemeldet:
                _gemeldet.add(hinweis)
                logger.warning(hinweis)
    return None  # nicht erreichbar: die letzte Stufe gibt zurück oder wirft


def _verletzt(fehler: Exception, constraint: str) -> bool:
    """Hat die Datenbank genau diese Prüfung (check constraint) abgelehnt?"""
    return constraint == (getattr(fehler, "constraint_name", None) or "") or constraint in str(fehler)


def _modus(zeile) -> str:
    wert = zeile.get("modell_modus") if zeile else None
    return wert if wert in MODI else "automatisch"


def _hat_code_token(zeile) -> bool:
    return bool(zeile and zeile.get("claude_code_token_ende"))


async def zugang_laden(user_id: str, *, db: Database | None = None, tresor: Tresor | None = None,
                       labor_art: str | None = None) -> Zugang:
    """Zugang der Sitzung aus dem Profil. Jede Unsicherheit führt zu nur Hausmodellen (nie zu Kosten auf einem
    fremden Schlüssel): fehlende Tabelle, Datenbankfehler, fehlender Hauptschlüssel, unlesbares Chiffrat.
    Reihenfolge: Zwang des Admins (nur_haus), dann die Wahl der Person (modell_modus), dann der eigene Schlüssel, dann
    der Server-Schlüssel für Laborprofile (labor_art), dann der Schlüssel des Kerns für das zugeordnete Profil.
    labor_art kommt allein aus der Identität des Kerns (profiles.labor_art, Middleware), nie aus dem Gespräch, und ist
    deshalb nur als Schlüsselwort möglich. Nur platz und schaufenster zählen; jeder andere Wert ist kein Laborprofil."""
    uid = normalize_uuid(user_id)
    if uid is None:
        return Zugang.haus(str(user_id), "fehler", "Profil-ID ungültig")
    db = db or shared_database()
    zeile = None
    if db.configured:
        try:
            zeile = await _zeile(db, uid)
        except (DatabaseUnavailable, *DB_ERRORS) as e:
            logger.error("Modellzugang für Profil {} nicht lesbar ({}): nur Hausmodelle", uid[:8], type(e).__name__)
            return Zugang.haus(uid, "fehler", "Modellzugang nicht lesbar")
    zugang = _zugang_aus_zeile(uid, zeile, tresor, labor_art)
    return zugang if labor_art in LABOR_ARTEN else _wahl_anhaengen(zugang, zeile)


def _wahl_anhaengen(zugang: Zugang, zeile) -> Zugang:
    """Modellwahl und Stimme im Haus der Person (0024) an den Zugang hängen, beide noch einmal gegen die feste Liste geprüft: ein
    Hausprofil bekommt nie ein Claude-Modell, ein vom Admin gesetztes Claude-Modell ist das einzige, unbekannte Werte gelten nicht.
    Nie für Laborprofile (zugang_laden ruft es für sie gar nicht auf, Quelle labor zusätzlich hier) und nie bei einem Fehler."""
    if not zeile or zugang.quelle in ("labor", "fehler"):
        return zugang
    from sprache_anbieter import stimme_normal

    claude = zugang.art == "claude"
    # Hat ein Admin das Profil festgelegt, gilt keine Modellwahl der Person (auch keine von vor der Sperre); die Stimme bleibt (D3)
    wahl = () if zugang.quelle == "festgelegt" else tuple(
        (b, w) for b in mw.BEREICHE
        if (w := zeile.get(mw.SPALTEN[b])) and mw.gueltig(b, w, claude=claude, claude_fest=zugang.claude_modell))
    stimme = stimme_normal(zeile.get("tts_stimme"))
    return replace(zugang, modell_wahl=wahl, tts_stimme=stimme) if wahl or stimme else zugang


def _zugang_aus_zeile(uid: str, zeile, tresor: Tresor | None, labor_art: str | None) -> Zugang:
    """Zugang ohne Wahl der Person (zugang_laden hängt sie danach an)."""
    stt = zeile["stt"] if zeile else "soniox"
    tts = zeile["tts"] if zeile else "soniox"
    if zeile and zeile["nur_haus"]:
        return Zugang.haus(uid, "festgelegt", stt=stt, tts=tts)
    if _modus(zeile) == "nur_haus":
        # Die Person hat nur Hausmodelle gewählt: ohne Schlüssel im Zugang, ohne Claude Code (nichts geht in die Cloud)
        return Zugang.haus(uid, "wahl", stt=stt, tts=tts)
    code = _hat_code_token(zeile)
    modell = (zeile["claude_modell"] if zeile else None) or None
    if zeile and zeile["claude_schluessel"] is not None:
        tresor = tresor if tresor is not None else _tresor_oder_none()
        if tresor is None:
            logger.error("WAMO_SCHLUESSEL_KEK fehlt: Schlüssel von Profil {} nicht nutzbar, nur Hausmodelle", uid[:8])
            return Zugang.haus(uid, "fehler", "Hauptschlüssel fehlt", stt=stt, tts=tts)
        try:
            schluessel = tresor.entschluesseln(uid, zeile["claude_schluessel"])
        except SchluesselFehler as e:
            logger.error("Schlüssel von Profil {} nicht lesbar ({}): nur Hausmodelle", uid[:8], e)
            return Zugang.haus(uid, "fehler", "Schlüssel nicht lesbar", stt=stt, tts=tts)
        return Zugang(uid, "claude", "profil", claude_modell=modell, claude_schluessel=schluessel,
                      claude_workspace=zeile["claude_workspace"], stt=stt, tts=tts, claude_code=code)
    server_schluessel = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if labor_art in LABOR_ARTEN and server_schluessel:
        # Testlabor: Laborprofile führen das Gespräch über den Server-Schlüssel (ANTHROPIC_API_KEY), Standardmodell Haiku
        # (oder das vom Admin gesetzte Modell des Profils). Nur das Gespräch: kein Claude-Code-Token (claude_code bleibt
        # falsch) und boss.entwicklung_quelle liefert für labor immer "keine". Ohne Schlüssel bleibt es bei Hausmodellen.
        return Zugang(uid, "claude", "labor", claude_modell=modell, claude_schluessel=server_schluessel,
                      claude_workspace=(os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip() or None, stt=stt, tts=tts)
    if kern_zuordnung(uid):
        return Zugang(uid, "claude", "zuordnung", claude_modell=modell,
                      claude_schluessel=(os.getenv("ANTHROPIC_API_KEY") or "").strip(),
                      claude_workspace=(os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip() or None, stt=stt, tts=tts,
                      claude_code=code)
    return Zugang.haus(uid, "keiner", stt=stt, tts=tts, claude_code=code)


def _tresor_oder_none() -> Tresor | None:
    try:
        return Tresor.from_env()
    except SchluesselFehler as e:
        logger.error("Hauptschlüssel unbrauchbar: {}", e)
        return None


async def stand_laden(user_id: str, *, db: Database | None = None) -> Stand:
    """Stand für die Oberfläche (ohne Entschlüsseln: es geht nur um "hinterlegt" und die letzten Zeichen)."""
    uid = normalize_uuid(user_id) or ""
    db = db or shared_database()
    zeile = await _zeile(db, uid) if db.configured and uid else None
    festgelegt = bool(zeile and zeile["nur_haus"])
    modus = _modus(zeile)
    wahl_haus = modus == "nur_haus" and not festgelegt
    hinterlegt = bool(zeile and zeile["claude_schluessel"] is not None)
    zuordnung = not hinterlegt and not festgelegt and kern_zuordnung(uid)
    art = "claude" if (hinterlegt or zuordnung) and not festgelegt and not wahl_haus else "haus"
    modell = (zeile["claude_modell"] if zeile else None) or os.getenv("CLAUDE_MODEL_FAST") or STANDARD_CLAUDE
    zeitpunkt = zeile["claude_geprueft_at"] if zeile else None
    geprueft = zeitpunkt.isoformat(timespec="minutes") if zeitpunkt else None
    code = _hat_code_token(zeile)
    code_zeit = zeile.get("claude_code_token_at") if zeile else None
    from sprache_anbieter import anzeige_grund, haus_problem_statisch, haus_stimme_standard, stimme_normal  # spät, wie bisher

    modelle = _modelle_stand(zeile, art == "claude", (zeile["claude_modell"] if zeile else None) or None, gesperrt=festgelegt)
    gespraech = modelle["gespraech"]["wahl"]
    stimme = zeile.get("tts_stimme") if zeile else None
    return Stand(
        art=art,
        quelle=("festgelegt" if festgelegt else "wahl" if wahl_haus else "profil" if hinterlegt
                else "zuordnung" if zuordnung else "keiner"),
        hinterlegt=hinterlegt, ende=zeile["claude_schluessel_ende"] if hinterlegt else None, geprueft=geprueft,
        festgelegt=festgelegt,
        modell=(mw.anzeige(gespraech) if gespraech != mw.AUTOMATISCH
                else lesbarer_modellname(modell) if art == "claude" else "Hausmodelle"),
        stt=zeile["stt"] if zeile else "soniox", tts=zeile["tts"] if zeile else "soniox",
        modus=modus, code_hinterlegt=code, code_ende=zeile["claude_code_token_ende"] if code else None,
        code_gesetzt=code_zeit.isoformat(timespec="minutes") if code and code_zeit else None,
        stimme_haus=anzeige_grund(haus_problem_statisch()) or "bereit",
        modelle=modelle, modell_sperre=SATZ_FESTGELEGT if festgelegt else None,
        haus_stimme=stimme_normal(stimme), haus_stimme_standard=haus_stimme_standard(),
    )


def _modelle_stand(zeile: Mapping[str, object] | None, claude: bool, claude_fest: str | None, *,
                   gesperrt: bool = False) -> dict[str, dict[str, object]]:
    """Je Bereich die wählbaren Modelle für diesen Zugang und die gültige Wahl. Ein gespeicherter Wert, der gerade nicht gilt (etwa
    Claude im Modus Nur Hausmodelle, oder jede Wahl, solange ein Admin das Profil festgelegt hat: gesperrt), erscheint als automatisch,
    mit einem Satz warum."""
    stand: dict[str, dict[str, object]] = {}
    for bereich in mw.BEREICHE:
        optionen = mw.optionen(bereich, claude=claude, claude_fest=claude_fest)
        gespeichert = zeile.get(mw.SPALTEN[bereich]) if zeile else None
        gilt = not gesperrt and isinstance(gespeichert, str) and any(o.id == gespeichert for o in optionen)
        eintrag: dict[str, object] = {"wahl": gespeichert if gilt else mw.AUTOMATISCH, "optionen": [o.daten() for o in optionen]}
        if isinstance(gespeichert, str) and gespeichert and not gilt:
            warum = "Solange ein Admin dein Profil festgelegt hat" if gesperrt else "Mit deinem Zugang gilt das gerade nicht"
            eintrag["hinweis"] = f"Gespeichert ist {mw.anzeige(gespeichert)}. {warum}, deshalb wählt W.A.I.S. automatisch."
        stand[bereich] = eintrag
    return stand


async def schluessel_testen(schluessel: str, workspace: str | None = None) -> str | None:
    """Kurze Testanfrage (ein Ausgabe-Token mit Haiku). None, wenn der Schlüssel funktioniert; sonst ein Grund
    für die Person, ohne Schlüssel."""
    return await _testanfrage(schluessel, workspace, os.getenv("CLAUDE_MODEL_FAST") or STANDARD_CLAUDE)


async def modell_testen(schluessel: str, workspace: str | None, modell: str) -> str | None:
    """Darf der Schlüssel der Person dieses Claude-Modell nutzen? Eine Anfrage mit einem Ausgabe-Token (kostet fast nichts).
    None, wenn ja; sonst ein Grund für die Person, ohne Schlüssel."""
    return await _testanfrage(schluessel, workspace, modell)


async def _testanfrage(schluessel: str, workspace: str | None, modell: str) -> str | None:
    kopf = {"anthropic-workspace-id": workspace} if workspace else None
    client = anthropic.AsyncAnthropic(api_key=schluessel, default_headers=kopf, max_retries=0,
                                      timeout=anthropic.Timeout(TEST_TIMEOUT_SECS, connect=3.0))
    try:
        await client.messages.create(model=modell, max_tokens=1, messages=[{"role": "user", "content": "ping"}])
        return None
    except anthropic.NotFoundError:
        return "Anthropic bietet dieses Modell für deinen Schlüssel nicht an (404)"
    except anthropic.AuthenticationError:
        return ("Anthropic lehnt den Schlüssel ab (401): Er ist ungültig, widerrufen oder gehört zu einem anderen "
                "Konto. Bitte in der Anthropic-Konsole prüfen oder einen neuen erzeugen")
    except anthropic.PermissionDeniedError:
        return "Der Schlüssel darf dieses Modell nicht nutzen (403): Workspace oder Berechtigung prüfen"
    except anthropic.APIStatusError as e:
        return f"Anthropic antwortet mit HTTP {e.status_code}"
    except anthropic.APITimeoutError:
        return f"Anthropic hat nicht rechtzeitig geantwortet (Zeitüberschreitung nach {TEST_TIMEOUT_SECS:.0f} s)"
    except anthropic.APIConnectionError:
        return "Anthropic ist gerade nicht erreichbar"
    except anthropic.APIError as e:
        return f"Anthropic-Fehler ({type(e).__name__})"
    finally:
        await client.close()


def _bremse(speicher: dict[str, list[float]], uid: str, grenze: int, jetzt: float | None = None) -> bool:
    """Höchstens grenze Versuche je Profil im Zeitfenster (je Prozess, im Speicher). True: dieser Versuch zählt und ist erlaubt."""
    jetzt = time.monotonic() if jetzt is None else jetzt
    liste = [t for t in speicher.get(uid, []) if jetzt - t < VERSUCHE_FENSTER_SECS]
    if len(liste) >= grenze:
        speicher[uid] = liste
        return False
    speicher[uid] = [*liste, jetzt]
    return True


def _stimme_erlaubt(uid: str, jetzt: float | None = None) -> bool:
    return _bremse(_stimme_versuche, uid, STIMME_JE_FENSTER, jetzt)


def _wahl_erlaubt(uid: str, jetzt: float | None = None) -> bool:
    return _bremse(_wahl_versuche, uid, WAHL_JE_FENSTER, jetzt)


def _versuch_erlaubt(uid: str, jetzt: float | None = None) -> bool:
    return _bremse(_versuche, uid, VERSUCHE_JE_FENSTER, jetzt)


async def hinterlegen(user_id: str, schluessel_roh: object, workspace_roh: object = None, *,
                      db: Database | None = None, tresor: Tresor | None = None,
                      testen: Callable[[str, str | None], Awaitable[str | None]] = schluessel_testen) -> Stand:
    # Ein Claude-Code-Token gehört ins andere Feld: format_pruefen sagt es der Person in einem Satz
    """Prüft, verschlüsselt und speichert den eigenen Schlüssel. Wirft ZugangFehler mit einem Grund für die
    Person. Der Schlüssel verlässt diese Funktion nur als Chiffrat."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: der Schlüssel kann nicht gespeichert werden")
    tresor = tresor if tresor is not None else _tresor_oder_none()
    if tresor is None:
        raise ZugangFehler("Der Kern hat keinen Hauptschlüssel (WAMO_SCHLUESSEL_KEK); bitte an den Admin wenden")
    try:
        schluessel = format_pruefen(schluessel_roh)
    except SchluesselFehler as e:
        raise ZugangFehler(str(e)) from None
    workspace = str(workspace_roh or "").strip() or None
    if workspace and not _WORKSPACE.fullmatch(workspace):
        raise ZugangFehler("Die Workspace-ID beginnt mit wrkspc_")
    zeile = await _zeile(db, uid)
    if zeile and zeile["nur_haus"]:
        raise ZugangFehler("Ein Admin hat dieses Profil auf nur Hausmodelle festgelegt")
    if not _versuch_erlaubt(uid):
        raise ZugangFehler("Zu viele Versuche, bitte in zehn Minuten noch einmal")
    if grund := await testen(schluessel, workspace):
        raise ZugangFehler(grund)
    chiffre = tresor.verschluesseln(uid, schluessel)
    try:
        await db.execute(
            f"insert into {db.t('model_access')} (user_id, claude_schluessel, claude_schluessel_ende, "
            "claude_workspace, claude_geprueft_at) values ($1::uuid, $2, $3, $4, now()) on conflict (user_id) "
            "do update set claude_schluessel = excluded.claude_schluessel, "
            "claude_schluessel_ende = excluded.claude_schluessel_ende, claude_workspace = excluded.claude_workspace, "
            "claude_geprueft_at = excluded.claude_geprueft_at",
            uid, chiffre, ende(schluessel), workspace,
        )
    except asyncpg.CheckViolationError as e:
        if _verletzt(e, "model_access_nur_haus_ohne_schluessel"):
            # Ein Admin hat das Profil zwischen Prüfung und Speichern auf nur Hausmodelle festgelegt
            raise ZugangFehler("Ein Admin hat dieses Profil auf nur Hausmodelle festgelegt") from None
        raise ZugangFehler("Die Datenbank hat den Schlüssel abgelehnt (Länge, Format oder Workspace)") from None
    logger.info("Claude-Schlüssel für Profil {} hinterlegt", uid[:8])  # nie auch nur Teile des Schlüssels loggen
    return await stand_laden(uid, db=db)


async def loeschen(user_id: str, *, db: Database | None = None) -> Stand:
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank")
    await db.execute(
        f"update {db.t('model_access')} set claude_schluessel = null, claude_schluessel_ende = null, "
        "claude_workspace = null, claude_geprueft_at = null where user_id = $1::uuid", uid,
    )
    logger.info("Claude-Schlüssel für Profil {} gelöscht", uid[:8])
    return await stand_laden(uid, db=db)


async def code_token_hinterlegen(user_id: str, token_roh: object, *, db: Database | None = None,
                                 tresor: Tresor | None = None) -> Stand:
    """Prüft das Format, verschlüsselt und speichert den Claude-Code-Token (nur für Entwicklungsaufträge). Es gibt
    keine Testanfrage: sie würde Verbrauch des Max-Kontingents erzeugen. Wirft ZugangFehler mit einem Grund für die
    Person; der Token verlässt diese Funktion nur als Chiffrat."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: der Token kann nicht gespeichert werden")
    tresor = tresor if tresor is not None else _tresor_oder_none()
    if tresor is None:
        raise ZugangFehler("Der Kern hat keinen Hauptschlüssel (WAMO_SCHLUESSEL_KEK); bitte an den Admin wenden")
    try:
        token = token_format_pruefen(token_roh)
    except SchluesselFehler as e:
        raise ZugangFehler(str(e)) from None
    zeile = await _zeile(db, uid)
    if zeile and zeile["nur_haus"]:
        raise ZugangFehler("Ein Admin hat dieses Profil auf nur Hausmodelle festgelegt")
    chiffre = tresor.verschluesseln(uid, token, CODE_TOKEN)
    try:
        await db.execute(
            f"insert into {db.t('model_access')} (user_id, claude_code_token, claude_code_token_ende, "
            "claude_code_token_at) values ($1::uuid, $2, $3, now()) on conflict (user_id) "
            "do update set claude_code_token = excluded.claude_code_token, "
            "claude_code_token_ende = excluded.claude_code_token_ende, "
            "claude_code_token_at = excluded.claude_code_token_at",
            uid, chiffre, ende(token),
        )
    except asyncpg.CheckViolationError as e:
        if _verletzt(e, "model_access_nur_haus_ohne_codetoken"):
            raise ZugangFehler("Ein Admin hat dieses Profil auf nur Hausmodelle festgelegt") from None
        raise ZugangFehler("Die Datenbank hat den Token abgelehnt (Länge oder Format)") from None
    except asyncpg.UndefinedColumnError:
        raise ZugangFehler("Der Claude-Code-Token ist in dieser Datenbank noch nicht vorgesehen (Migration 0011)") from None
    logger.info("Claude-Code-Token für Profil {} hinterlegt", uid[:8])  # nie auch nur Teile des Tokens loggen
    return await stand_laden(uid, db=db)


async def code_token_loeschen(user_id: str, *, db: Database | None = None) -> Stand:
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank")
    await db.execute(
        f"update {db.t('model_access')} set claude_code_token = null, claude_code_token_ende = null, "
        "claude_code_token_at = null where user_id = $1::uuid", uid,
    )
    logger.info("Claude-Code-Token für Profil {} gelöscht", uid[:8])
    return await stand_laden(uid, db=db)


async def modus_setzen(user_id: str, modus_roh: object, *, db: Database | None = None) -> Stand:
    """Die Wahl der Person: automatisch (der Boss wählt unter allen erlaubten Modellen) oder nur_haus. Sie gilt ab
    der nächsten Sitzung und lässt hinterlegte Schlüssel unberührt. Hat ein Admin das Profil auf nur Hausmodelle
    festgelegt, ist die Wahl gesperrt (der Zwang ist stärker)."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if modus_roh not in MODI:
        raise ZugangFehler("Unbekannte Wahl (automatisch oder nur_haus)")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: die Wahl kann nicht gespeichert werden")
    zeile = await _zeile(db, uid)
    if zeile and zeile["nur_haus"]:
        raise ZugangFehler("Ein Admin hat dieses Profil auf nur Hausmodelle festgelegt; die Wahl ist gesperrt")
    try:
        await db.execute(
            f"insert into {db.t('model_access')} (user_id, modell_modus) values ($1::uuid, $2) "
            "on conflict (user_id) do update set modell_modus = excluded.modell_modus",
            uid, modus_roh,
        )
    except asyncpg.UndefinedColumnError:
        raise ZugangFehler("Die Wahl ist in dieser Datenbank noch nicht vorgesehen (Migration 0011)") from None
    logger.info("Modellwahl für Profil {}: {}", uid[:8], modus_roh)
    return await stand_laden(uid, db=db)


async def stimme_setzen(user_id: str, stt_roh: object, tts_roh: object, *, db: Database | None = None) -> Stand:
    """Die Person wählt Spracherkennung (stt) und Sprachausgabe (tts): soniox (Standard) oder haus. Gilt ab der nächsten
    Sitzung. Der Zwang des Admins auf Hausmodelle (nur_haus) betrifft nur die Sprachmodelle, nicht die Stimme (D3): Beides
    bleibt wählbar. Laborprofile erreichen diese Funktion nie (labor.py sperrt Pfad und Nachricht, modellzugang_api.py lehnt
    zusätzlich ab), und eine Laborsitzung hört immer über Soniox (sprache_anbieter.sprach_wahl). Schreibrecht des Kerns auf stt
    und tts erst ab Migration 0023; davor ein klarer Satz statt "Datenbank nicht erreichbar"."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if not (isinstance(stt_roh, str) and stt_roh in STIMMEN and isinstance(tts_roh, str) and tts_roh in STIMMEN):
        raise ZugangFehler("Unbekannte Wahl für Hören und Stimme (soniox oder haus)")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: die Wahl kann nicht gespeichert werden")
    vorher = await _zeile(db, uid)
    bisher = (vorher["stt"], vorher["tts"]) if vorher else ("soniox", "soniox")
    if bisher == (stt_roh, tts_roh):
        return await stand_laden(uid, db=db)  # nichts geändert: kein Schreiben, keine Zeile in actions
    if not _stimme_erlaubt(uid):
        raise ZugangFehler("Zu viele Wechsel, bitte in zehn Minuten noch einmal")
    try:
        await db.execute(
            f"insert into {db.t('model_access')} (user_id, stt, tts) values ($1::uuid, $2, $3) "
            "on conflict (user_id) do update set stt = excluded.stt, tts = excluded.tts",
            uid, stt_roh, tts_roh,
        )
    except asyncpg.InsufficientPrivilegeError:
        logger.error("Hören und Stimme für Profil {}: kein Schreibrecht auf stt und tts (Migration 0023 fehlt?)", uid[:8])
        raise ZugangFehler("Die eigene Wahl von Hören und Stimme ist in dieser Datenbank noch nicht freigeschaltet; "
                           "bitte an den Admin wenden") from None
    except asyncpg.CheckViolationError:
        raise ZugangFehler("Die Datenbank hat die Wahl abgelehnt (soniox oder haus)") from None
    logger.info("Hören und Stimme für Profil {}: Spracherkennung {}, Sprachausgabe {}", uid[:8], stt_roh, tts_roh)
    await _stimme_protokollieren(db, uid, stt_roh, tts_roh, vorher)
    return await stand_laden(uid, db=db)


async def _stimme_protokollieren(db: Database, uid: str, stt: str, tts: str, vorher: asyncpg.Record | dict | None) -> None:
    """Zeile in actions (Werkzeug stimme_wahl, Risiko change, Status done), nur mit den Werten. Wirft nie: Der Eintrag ist Protokoll,
    keine Freigabe; die Wahl ist dann schon gespeichert."""
    params: dict[str, object] = {"stt": stt, "tts": tts}
    if vorher:
        params["vorher"] = {"stt": vorher["stt"], "tts": vorher["tts"]}
    try:
        await db.execute(
            f"insert into {db.t('actions')} (user_id, tool, params, reason, risk, status, result, finished_at) "
            f"values ($1::uuid, $2, $3::text::jsonb, $4, 'change'::{db.t('risk_class')}, 'done'::{db.t('action_status')}, "
            "'{}'::jsonb, now())",
            uid, STIMME_WERKZEUG, json.dumps(params), "Hören und Stimme selbst gewählt, gilt ab der nächsten Sitzung",
        )
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("Wahl von Hören und Stimme für Profil {} nicht protokolliert ({})", uid[:8], type(e).__name__)


ModellPruefer = Callable[[str, str | None, str], Awaitable[str | None]]


async def modell_setzen(user_id: str, bereich_roh: object, wert_roh: object, *, db: Database | None = None,
                        tresor: Tresor | None = None, testen: ModellPruefer = modell_testen) -> Stand:
    """Die Person wählt das Modell eines Bereichs (gespraech, bilder, hintergrund): "automatisch" oder ein Modell aus der festen Liste
    (modellwahl.py) für ihren Zugang. Gilt ab der nächsten Sitzung. Gesperrt, wenn ein Admin das Profil auf Hausmodelle festgelegt hat.
    Ein Claude-Modell nur mit Claude-Zugang und erst nach einer kleinen Anfrage mit dem eigenen Schlüssel (der Kernschlüssel nur für das
    zugeordnete Profil). Jede Änderung steht als Zeile in actions (Werkzeug modell_wahl, nur Bereich und Werte). Laborprofile erreichen
    diese Funktion nie (labor.py sperrt Pfad und Nachricht, modellzugang_api.py lehnt zusätzlich ab)."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if not (isinstance(bereich_roh, str) and bereich_roh in mw.BEREICHE):
        raise ZugangFehler("Unbekannter Bereich (gespraech, bilder oder hintergrund)")
    if not isinstance(wert_roh, str) or not wert_roh:
        raise ZugangFehler("Unbekanntes Modell")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: die Wahl kann nicht gespeichert werden")
    zeile = await _zeile(db, uid)
    if zeile and zeile["nur_haus"]:
        raise ZugangFehler(SATZ_FESTGELEGT)
    zugang = await zugang_laden(uid, db=db, tresor=tresor)
    if zugang.quelle == "fehler":
        raise ZugangFehler("Der Modellzugang ist gerade nicht lesbar; die Wahl ist erst danach möglich")
    claude = zugang.art == "claude"
    wert = None if wert_roh == mw.AUTOMATISCH else wert_roh
    if wert is not None and not mw.gueltig(bereich_roh, wert, claude=claude, claude_fest=zugang.claude_modell):
        raise ZugangFehler("Dieses Modell ist für dein Profil nicht wählbar"
                           + ("" if claude or not wert.startswith("claude-") else " (Claude nur mit eigenem API-Schlüssel)"))
    spalte = mw.SPALTEN[bereich_roh]  # aus der festen Liste, nie aus der Anfrage
    vorher = (zeile.get(spalte) if zeile else None) or None
    if vorher == wert:
        return await stand_laden(uid, db=db)  # nichts geändert: kein Schreiben, keine Zeile in actions
    if not _wahl_erlaubt(uid):
        raise ZugangFehler("Zu viele Wechsel, bitte in zehn Minuten noch einmal")
    if wert is not None and wert.startswith("claude-"):
        if grund := await testen(zugang.claude_schluessel or "", zugang.claude_workspace, wert):
            raise ZugangFehler(grund)
    await _spalte_schreiben(db, uid, spalte, wert)
    logger.info("Modellwahl für Profil {}: {} = {}", uid[:8], bereich_roh, wert or mw.AUTOMATISCH)
    await _protokollieren(db, uid, MODELL_WERKZEUG,
                          {"bereich": bereich_roh, "modell": wert or mw.AUTOMATISCH, "vorher": vorher or mw.AUTOMATISCH},
                          "Modell selbst gewählt, gilt ab der nächsten Sitzung")
    return await stand_laden(uid, db=db)


async def haus_stimme_setzen(user_id: str, stimme_roh: object, *, db: Database | None = None) -> Stand:
    """Die Person wählt die Stimme der Sprachausgabe im Haus: eine der freigegebenen Stimmen (sprache_anbieter.HAUS_STIMMEN, eine
    Konstante) oder "standard". Die Standardstimme selbst wird als "standard" gespeichert (NULL). Gilt ab der nächsten Sitzung und nur, wenn
    die Sprachausgabe im Haus läuft. Der Zwang des Admins auf Hausmodelle sperrt sie nicht (wie Hören und Stimme, D3). Jede Änderung steht
    als Zeile in actions (Werkzeug stimme_wahl). Jeder Wert außerhalb der Liste wird abgelehnt."""
    from sprache_anbieter import HAUS_STIMMEN_IDS, haus_stimme_standard

    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("Profil ungültig")
    if not (isinstance(stimme_roh, str) and (stimme_roh in HAUS_STIMMEN_IDS or stimme_roh == STANDARD_STIMME)):
        raise ZugangFehler(f"Unbekannte Stimme (erlaubt: {', '.join(HAUS_STIMMEN_IDS)} oder {STANDARD_STIMME})")
    db = db or shared_database()
    if not db.configured:
        raise ZugangFehler("Keine Datenbank: die Wahl kann nicht gespeichert werden")
    wert = None if stimme_roh in (STANDARD_STIMME, haus_stimme_standard()) else stimme_roh
    zeile = await _zeile(db, uid)
    from sprache_anbieter import stimme_normal

    vorher = stimme_normal(zeile.get("tts_stimme") if zeile else None)
    if vorher == wert:
        return await stand_laden(uid, db=db)
    if not _stimme_erlaubt(uid):
        raise ZugangFehler("Zu viele Wechsel, bitte in zehn Minuten noch einmal")
    await _spalte_schreiben(db, uid, "tts_stimme", wert)
    logger.info("Stimme im Haus für Profil {}: {}", uid[:8], wert or STANDARD_STIMME)
    await _protokollieren(db, uid, STIMME_WERKZEUG, {"haus_stimme": wert, "vorher": vorher},
                          "Stimme im Haus selbst gewählt, gilt ab der nächsten Sitzung")
    return await stand_laden(uid, db=db)


async def _spalte_schreiben(db: Database, uid: str, spalte: str, wert: str | None) -> None:
    """Upsert genau einer Spalte aus 0024 für das Profil der Anfrage. spalte kommt nur aus festen Listen (mw.SPALTEN, tts_stimme)."""
    if spalte not in (*mw.SPALTEN.values(), "tts_stimme"):
        raise ValueError(f"Spalte {spalte!r} ist nicht erlaubt")
    try:
        await db.execute(
            f"insert into {db.t('model_access')} (user_id, {spalte}) values ($1::uuid, $2) "
            f"on conflict (user_id) do update set {spalte} = excluded.{spalte}",
            uid, wert,
        )
    except (asyncpg.UndefinedColumnError, asyncpg.InsufficientPrivilegeError) as e:
        logger.error("Wahl für Profil {}: {} nicht schreibbar ({}; Migration 0024 fehlt?)", uid[:8], spalte, type(e).__name__)
        raise ZugangFehler(SATZ_NICHT_FREI) from None
    except asyncpg.CheckViolationError:
        raise ZugangFehler("Die Datenbank hat die Wahl abgelehnt") from None


async def _protokollieren(db: Database, uid: str, werkzeug: str, params: dict, grund: str) -> None:
    """Zeile in actions (Risiko change, Status done), nur mit den Werten. Wirft nie: der Eintrag ist Protokoll, die Wahl ist schon
    gespeichert."""
    try:
        await db.execute(
            f"insert into {db.t('actions')} (user_id, tool, params, reason, risk, status, result, finished_at) "
            f"values ($1::uuid, $2, $3::text::jsonb, $4, 'change'::{db.t('risk_class')}, 'done'::{db.t('action_status')}, "
            "'{}'::jsonb, now())",
            uid, werkzeug, json.dumps(params), grund,
        )
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.warning("Wahl ({}) für Profil {} nicht protokolliert ({})", werkzeug, uid[:8], type(e).__name__)


async def claude_code_zugang_fuer(user_id: str, *, db: Database | None = None,
                                  tresor: Tresor | None = None) -> dict[str, str] | None:
    """Der Zugang des Profils für GENAU EINEN Lauf eines Entwicklungsauftrags mit Claude Code, entschlüsselt:
    {"typ": "oauth" | "api", "wert": "<Token oder Schlüssel>"}, sonst None.
      oauth  Der Claude-Code-Token (Max-Tarif, Kontingent des Abos, Standardmodell Sonnet). Hat Vorrang.
      api    Der eigene API-Schlüssel (geht vom Guthaben ab, Standardmodell Haiku), wenn kein Token hinterlegt ist.
    Aufruf nur im Kern und nur durch den Entwicklungs-Agenten der Sitzung dieses Profils (bot.py bindet die Profil-ID
    fest), kurz vor dem Start eines Laufs; der Wert wird nicht im Zugang, in keinem Objekt und nie im Log gehalten.
    None, wenn nichts hinterlegt ist, der Admin oder die Person nur Hausmodelle verlangt (nichts geht in die Cloud),
    der Hauptschlüssel fehlt oder ein Chiffrat nicht lesbar ist: dann startet kein Lauf. Der Schlüssel des Kerns
    (ANTHROPIC_API_KEY) gehört nicht dazu: Das Profil mit der Zuordnung nutzt weiter den Zugang der Sandbox."""
    uid = normalize_uuid(user_id)
    if uid is None:
        return None
    db = db or shared_database()
    if not db.configured:
        return None
    try:
        zeile = await db.fetchrow(
            f"select nur_haus, modell_modus, claude_code_token, claude_schluessel from {db.t('model_access')} "
            "where user_id = $1::uuid", uid)
    except asyncpg.UndefinedColumnError:
        return None
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.error("Zugang für Entwicklungsauftrag von Profil {} nicht lesbar ({})", uid[:8], type(e).__name__)
        return None
    if not zeile or zeile["nur_haus"] or _modus(zeile) == "nur_haus":
        return None
    tresor = tresor if tresor is not None else _tresor_oder_none()
    if tresor is None:
        logger.error("WAMO_SCHLUESSEL_KEK fehlt: Zugang von Profil {} für Entwicklungsaufträge nicht nutzbar", uid[:8])
        return None
    for typ, spalte, zweck in (("oauth", "claude_code_token", CODE_TOKEN), ("api", "claude_schluessel", SCHLUESSEL)):
        if zeile[spalte] is None:
            continue
        try:
            return {"typ": typ, "wert": tresor.entschluesseln(uid, zeile[spalte], zweck)}
        except SchluesselFehler as e:
            # nicht stillschweigend auf den anderen Typ ausweichen: ein kaputtes Chiffrat soll auffallen
            logger.error("Zugang ({}) von Profil {} nicht lesbar ({})", typ, uid[:8], e)
            return None
    return None


Pruefer = Callable[[str, str | None], Awaitable[str | None]]


async def modellzugang_nachricht(user_id: str, data: dict, senden: Callable[[dict], Awaitable[None]], *,
                                 db: Database | None = None, tresor: Tresor | None = None,
                                 testen: Pruefer = schluessel_testen, testen_modell: ModellPruefer = modell_testen) -> None:
    """Klick aus der Oberfläche (RTVI-Nachricht "modellzugang"). Aktionen: status, modus (Wahl der Person),
    stimme (Hören und Stimme der Person, Felder stt und tts, getrennt wählbar), modell (Felder bereich und modell), haus_stimme
    (Feld stimme), hinterlegen und loeschen (mit schluesselart api oder code).
    Die Antwort enthält nie einen Schlüssel oder Token; der Inhalt der Nachricht wird nie geloggt."""
    aktion = data.get("aktion") if data.get("aktion") in AKTIONEN else "status"
    art = data.get("schluesselart") if data.get("schluesselart") in SCHLUESSELARTEN else "api"
    try:
        if aktion == "modus":
            stand = await modus_setzen(user_id, data.get("modus"), db=db)
        elif aktion == "stimme":
            stand = await stimme_setzen(user_id, data.get("stt"), data.get("tts"), db=db)
        elif aktion == "modell":
            stand = await modell_setzen(user_id, data.get("bereich"), data.get("modell"), db=db, tresor=tresor,
                                        testen=testen_modell)
        elif aktion == "haus_stimme":
            stand = await haus_stimme_setzen(user_id, data.get("stimme"), db=db)
        elif aktion == "hinterlegen" and art == "code":
            stand = await code_token_hinterlegen(user_id, data.get("schluessel"), db=db, tresor=tresor)
        elif aktion == "hinterlegen":
            stand = await hinterlegen(user_id, data.get("schluessel"), data.get("workspace"), db=db, tresor=tresor,
                                      testen=testen)
        elif aktion == "loeschen" and art == "code":
            stand = await code_token_loeschen(user_id, db=db)
        elif aktion == "loeschen":
            stand = await loeschen(user_id, db=db)
        else:
            aktion, stand = "status", await stand_laden(user_id, db=db)
        await senden(stand.nachricht(aktion=aktion))
    except ZugangFehler as e:
        logger.info("Modellzugang {} für Profil {} abgelehnt: {}", aktion, str(user_id)[:8], e)
        try:
            stand = await stand_laden(user_id, db=db)
            await senden(stand.nachricht(aktion=aktion, fehler=str(e)))
        except (DatabaseUnavailable, *DB_ERRORS):
            await senden({"type": "modellzugang", "aktion": aktion, "fehler": str(e)})
    except (DatabaseUnavailable, *DB_ERRORS) as e:
        logger.error("Modellzugang {} für Profil {}: Datenbank ({})", aktion, str(user_id)[:8], type(e).__name__)
        await senden({"type": "modellzugang", "aktion": aktion, "fehler": "Datenbank gerade nicht erreichbar"})
    except Exception as e:  # nie ohne Antwort an die Oberfläche (sie wartet sonst bis zur Zeitgrenze)
        logger.error("Modellzugang {} für Profil {}: unerwarteter Fehler ({})", aktion, str(user_id)[:8],
                     type(e).__name__)
        await senden({"type": "modellzugang", "aktion": aktion, "fehler": "Unerwarteter Fehler, bitte später noch einmal"})


# ---------- Verwaltung (wamo_admin, nur wamo_admin.py) ----------


async def admin_festlegen(user_id: str, *, nur_haus: bool | None = None, modell: str | None = None,
                          stt: str | None = None, tts: str | None = None, db: Database | None = None) -> None:
    """Admin: nur Hausmodelle an oder aus, Claude-Modell, Stimme. Der Wechsel auf nur_haus räumt den Schlüssel
    in der Datenbank (Trigger model_access_guard); die Verwaltung liest das Chiffrat nie."""
    uid = normalize_uuid(user_id)
    if uid is None:
        raise ZugangFehler("user_id ist keine UUID")
    if modell is not None and not re.fullmatch(r"claude-[a-z0-9-]{3,60}", modell):
        raise ZugangFehler("Modell muss eine Claude-ID sein, z. B. claude-haiku-5-5")
    for wert in (stt, tts):
        if wert is not None and wert not in ("soniox", "haus"):
            raise ZugangFehler("stt und tts: soniox oder haus")
    felder = {k: v for k, v in (("nur_haus", nur_haus), ("claude_modell", modell), ("stt", stt), ("tts", tts))
              if v is not None}
    if not felder:
        raise ZugangFehler("Nichts zu ändern")
    db = db or admin_database()
    spalten = ["user_id", *felder]
    platz = ", ".join(f"${i + 1}" for i in range(len(spalten)))
    setzen = ", ".join(f"{k} = excluded.{k}" for k in felder)
    await db.execute(
        f"insert into {db.t('model_access')} ({', '.join(spalten)}) values ({platz}) "
        f"on conflict (user_id) do update set {setzen}",
        uid, *felder.values(),
    )


async def admin_liste(db: Database | None = None) -> list[dict]:
    db = db or admin_database()
    zeilen = await db.fetch(
        f"select p.user_id::text as user_id, p.display_name, coalesce(m.nur_haus, false) as nur_haus, "
        "m.claude_schluessel_ende, m.claude_modell, coalesce(m.stt, 'soniox') as stt, "
        "coalesce(m.tts, 'soniox') as tts "
        f"from {db.t('profiles')} p left join {db.t('model_access')} m on m.user_id = p.user_id order by p.display_name"
    )
    return [dict(z) for z in zeilen]


# ---------- Kommandozeile für den Betrieb (Umgebung des Kerns) ----------


async def _cli(args: argparse.Namespace) -> int:
    db = shared_database()
    try:
        if args.befehl == "hinterlegen":
            schluessel = getpass.getpass("Anthropic-Schlüssel (wird nicht angezeigt): ")
            stand = await hinterlegen(args.user_id, schluessel, args.workspace, db=db)
            del schluessel
        elif args.befehl == "loeschen":
            stand = await loeschen(args.user_id, db=db)
        else:
            stand = await stand_laden(args.user_id, db=db)
        print(f"Zugang: {stand.art} ({stand.quelle}), Modell {stand.modell}, Wahl {stand.modus}, "
              + (f"Schlüssel hinterlegt, endet auf …{stand.ende}" if stand.hinterlegt else "kein eigener Schlüssel")
              + (f", Claude-Code-Token hinterlegt, endet auf …{stand.code_ende}" if stand.code_hinterlegt
                 else ", kein Claude-Code-Token"))
        return 0
    except ZugangFehler as e:
        print(f"Abgelehnt: {e}", file=sys.stderr)
        return 1
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="modellzugang", description="Modellzugang je Profil (Betrieb, Kern)")
    sub = p.add_subparsers(dest="befehl", required=True)
    sub.add_parser("kek-erzeugen", help="neuen Hauptschlüssel für WAMO_SCHLUESSEL_KEK ausgeben")
    for name in ("hinterlegen", "status", "loeschen"):
        b = sub.add_parser(name)
        b.add_argument("--user-id", required=True)
        if name == "hinterlegen":
            b.add_argument("--workspace", help="nur bei Organisationsschlüsseln: wrkspc_...")
    args = p.parse_args(argv)
    # diagnose=False: loguru schriebe sonst bei Ausnahmen die Werte lokaler Variablen (auch Schlüssel) aus
    logger.remove()
    logger.add(sys.stderr, level="INFO", backtrace=False, diagnose=False)
    if args.befehl == "kek-erzeugen":
        from schluessel import kek_erzeugen

        print(kek_erzeugen())
        return 0
    hier = os.path.dirname(os.path.abspath(__file__))
    for pfad in (os.path.join(hier, ".env"), os.path.join(hier, "..", ".env")):
        if os.path.isfile(pfad):
            load_dotenv(pfad, override=False)
    return asyncio.run(_cli(args))


if __name__ == "__main__":
    sys.exit(main())
