"""Teams-Nachricht am PC aus dem Gespräch oder dem Canvas (Paket 4 von docs/office-und-versand.md, Teil Teams): Werkzeug teams_nachricht
und der Klick teams_vorbereiten.

Entscheidung (Niko, 15.11.2026): Teams öffnet den Chat vorbefüllt per Deep Link, die Person drückt selbst Enter. W.A.I.S. sendet in
Teams nie selbst, und geöffnet wird erst nach der Freigabe in W.A.I.S. (Karte mit Empfängern und Text, Job pc, Aktion teams).

Wer: nur mit Stufe der PC-Steuerung (rechte.pc_stufe: Admin oder, seit dem 16.11.2026, freigeschaltetes Mitglied am eigenen Laptop;
office_werkzeuge.pc_person), nie in einer Laborsitzung, nur mit WAMO_OFFICE (Teil "teams", Standard leer = aus, unbekannte Teile zählen nicht), nur
bei eingeschalteter PC-Steuerung mit gehaltener Sperre (darf) und nur, wenn der Host Teams öffnen kann (office_faehigkeiten meldet
teams). Registriert wird nach werkzeuge_absichern: das Stimmabdruck-Gate gilt, das Werkzeug steht nicht in OFFENE_WERKZEUGE.

Was: Den Text nennt das Modell, oder er kommt aus einem eigenen Canvas-Element (canvas_quelle, als Klartext). Der Kern fragt den Host
(teams_chat_anfragen, nie in LLM_TOOLS); der Host löst Empfänger auf (nur Adressen oder Namen aus dem Adressbuch, nie geraten), prüft
Text und Länge selbst und baut die Karte mit genau dem Inhalt des Links. Das Modell bekommt nur "liegt zur Freigabe bereit", nie die
Kennung der Freigabe. In actions steht die Karte ohne Adressen und Text (pc_freigaben.py, Aktion teams).

Nachricht an die Oberfläche: {"type": "teams_antwort", "ok", "grund"?} nach teams_vorbereiten.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema

from activity import freigabe_anfrage
from canvas_quelle import CanvasNichtErreichbar, canvas_lesen
from office_werkzeuge import office_teile, pc_person
from outlook_werkzeuge import WARNUNG, _als_liste
from pc_host import call_host_tool, pc_freigabe_entscheiden
from persona import clean_inline

TEIL = "teams"
WERKZEUG = "teams_nachricht"
NACHRICHTEN = ("teams_vorbereiten",)
FAEHIGKEITEN_TIMEOUT_SECS = 5.0
ANFRAGE_TIMEOUT_SECS = 60.0  # Auflösen im Adressbuch am PC (pc_tunnel.LANGE_WERKZEUGE)
EMPFAENGER_MAX = 10  # wie host/office_teams.py; der Host prüft selbst
TEXT_MAX = 1000
GRUPPE_MAX = 100
EINGABE_MAX = 254
PC_AUS = "Die PC-Steuerung ist aus. Sie lässt sich in der Oberfläche einschalten."
BEREIT = ("Die Teams-Nachricht liegt als Karte zur Freigabe bereit. Nach dem Klick öffnet sich Teams mit dem Text im Eingabefeld; "
          "senden muss die Person dort selbst mit Enter.")


def teams_an(wert: str | None = None) -> bool:
    return TEIL in office_teile(wert)


def fuer_sitzung(identity) -> bool:
    """Bekommt diese Sitzung Teams-Nachrichten? Nur mit Stufe der PC-Steuerung, nie ein Laborprofil, nur mit Schalter."""
    return pc_person(identity) and teams_an()


def schema() -> FunctionSchema:
    return FunctionSchema(
        name=WERKZEUG,
        description=(
            "Bereitet eine Teams-Nachricht am PC vor. Es geht nichts raus ohne Klick: W.A.I.S. zeigt eine Freigabekarte mit Empfängern "
            "und Text; nach dem Klick öffnet sich Teams mit dem Text im Eingabefeld, und die Person sendet selbst mit Enter. W.A.I.S. "
            "sendet nie. Adressen nie raten: nur Adressen oder Namen, die die Person genannt hat. Text als Klartext ohne Markdown, "
            "höchstens 1000 Zeichen; ist er zu lang, kürzen oder eine Mail vorschlagen. Sag danach nur, dass die Nachricht zur Freigabe "
            "bereitliegt, nie 'gesendet'."
        ),
        properties={
            "an": {"type": "array", "items": {"type": "string"},
                   "description": "interne Mailadressen oder Namen aus dem Adressbuch (nur mit klassischem Outlook), höchstens 10"},
            "text": {"type": "string", "description": "der Text für das Eingabefeld"},
            "canvas": {"type": "string", "description": "statt text: Titel eines eigenen Canvas-Elements als Text, leer = das zuletzt gezeigte"},
            "gruppenname": {"type": "string", "description": "Name des Gruppenchats, nur bei mindestens zwei Empfängern, optional"},
        },
        required=["an"],
    )


# ---------- Klartext aus dem Canvas ----------
_UEBERSCHRIFT = re.compile(r"^\s{0,3}#{1,6}\s+")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def _markdown_zeile(zeile: str) -> str:
    zeile = _UEBERSCHRIFT.sub("", zeile)
    zeile = _LINK.sub(r"\1 (\2)", zeile)
    return zeile.replace("**", "").replace("__", "").replace("`", "")


def klartext(inhalt: dict) -> str:
    """Canvas-Inhalt (canvas_quelle) als Klartext für Teams: Dokumente ohne Markdown-Zeichen, Tabellen als Zeilen mit " | ", Code und
    Diagramme wie sie sind."""
    if inhalt.get("art") == "tabelle":
        zeilen = [inhalt.get("spalten", []), *inhalt.get("zeilen", [])]
        return "\n".join([str(inhalt.get("titel", "")), *(" | ".join(z) for z in zeilen)]).strip()
    text = str(inhalt.get("text", ""))
    if inhalt.get("art") != "dokument":
        return text
    return "\n".join(_markdown_zeile(z) for z in text.split("\n") if not z.strip().startswith("```")).strip()


def _empfaenger(wert: object) -> list[str] | None:
    liste = _als_liste(wert)
    if not liste or len(liste) > EMPFAENGER_MAX or not all(0 < len(w.strip()) <= EINGABE_MAX for w in liste):
        return None
    return [w.strip() for w in liste]


class TeamsNachricht:
    """Teams-Nachricht für eine Sitzung. client(): MCP-Client des Hosts; darf(): Rolle, Schalter, PC-Sperre; senden(nachricht): an die
    Oberfläche; fremd(): kamen im Zug Fremdinhalte vor (turn.tainted). karte_anlegen setzt bot.py (PcFreigaben.anfrage)."""

    def __init__(self, identity, memory, *, client: Callable[[], object], darf: Callable[[], bool],
                 senden: Callable[[dict], Awaitable[None]] | None, fremd: Callable[[], bool]):
        if not pc_person(identity):
            raise ValueError("Teams-Nachrichten gibt es nur mit PC-Steuerung am eigenen Laptop und nie im Labor")
        self.identity, self.memory = identity, memory
        self._client, self._darf, self._senden, self._fremd = client, darf, senden, fremd
        self.karte_anlegen: Callable[[dict], dict | None] | None = None
        self.verfuegbar = False
        self._laeuft = False  # je Sitzung höchstens eine Vorbereitung (Doppelklick, doppelter Werkzeugaufruf)
        self._karten: set[str] = set()

    async def schemas(self) -> list[FunctionSchema]:
        """Fragt den Host, ob er Teams öffnen kann. Wirft nie."""
        self.verfuegbar = False
        client = self._client()
        if client is None:
            return []
        try:
            antwort = json.loads(await asyncio.wait_for(call_host_tool(client, "office_faehigkeiten", {}), FAEHIGKEITEN_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001 (älterer Host, Tunnel weg: ohne Teams weiter)
            logger.info("Teams: Host meldet keine Fähigkeiten ({})", type(e).__name__)
            return []
        if not isinstance(antwort, dict) or antwort.get("status") != "success" or antwort.get("teams") is not True:
            return []
        self.verfuegbar = True
        return [schema()]

    def register(self, llm) -> None:
        # Kein Abbruch bei einem Einwurf: Sonst hielte der PC eine Anfrage ohne Karte, und dort ruhten die Eingaben bis zum Ablauf
        llm.register_function(WERKZEUG, self._werkzeug, cancel_on_interruption=False, timeout_secs=ANFRAGE_TIMEOUT_SECS + 10)

    def anzeige(self) -> bool:
        """Für die Oberfläche (Feld teams in betrieb): Knopf "Als Teams-Nachricht" nur, solange es geht."""
        return bool(self.verfuegbar and self._darf())

    async def _werkzeug(self, params) -> None:
        a = params.arguments if isinstance(params.arguments, dict) else {}
        canvas = a.get("canvas")
        ergebnis = await self.vorbereiten(
            an=a.get("an"), text=a.get("text"), gruppenname=a.get("gruppenname") or "", quelle="sprache",
            aus_canvas=isinstance(canvas, str), canvas_titel=(canvas.strip() or None) if isinstance(canvas, str) else None,
            aktivitaet_id=str(getattr(params, "tool_call_id", "") or ""))
        await params.result_callback(ergebnis)

    async def vorbereiten(self, *, an: object, text: object, gruppenname: object = "", aus_canvas: bool = False,
                          canvas_titel: str | None = None, quelle: str, aktivitaet_id: str = "") -> dict:
        """Gemeinsamer Weg für Sprache und Klick: Text bestimmen, Host fragen, Karte anlegen. Liefert die Antwort für das Modell."""
        if self._laeuft:
            return {"status": "rejected", "summary": "Eine Teams-Nachricht wird gerade schon vorbereitet. Bitte einen Moment warten."}
        self._laeuft = True  # ohne await dazwischen gesetzt: kein zweiter Aufruf kommt vorbei
        logger.info("Teams: Vorbereitung ({})", quelle)  # nur woher, nie Empfänger oder Text
        try:
            return await self._vorbereiten(an, text, gruppenname, aus_canvas, canvas_titel, aktivitaet_id)
        finally:
            self._laeuft = False

    async def _text(self, text: object, aus_canvas: bool, canvas_titel: str | None) -> tuple[str | None, dict | None]:
        """Der Text vom Modell oder, ohne ihn, aus dem eigenen Canvas (als Klartext). Sonst eine Antwort für das Modell."""
        if isinstance(text, str) and text.strip():
            return text, None
        if not aus_canvas:
            return None, {"status": "rejected", "summary": "Der Text fehlt: bitte den Text nennen oder das Canvas angeben."}
        try:
            gefunden = await canvas_lesen(self.memory, titel=canvas_titel)
        except CanvasNichtErreichbar:
            return None, {"status": "error", "summary": "Das Canvas ist gerade nicht lesbar. Bitte gleich noch einmal."}
        if gefunden is None or not klartext(gefunden["inhalt"]):
            return None, {"status": "rejected", "summary": "Kein passendes eigenes Canvas-Element gefunden."}
        return klartext(gefunden["inhalt"]), None

    async def _vorbereiten(self, an: object, text: object, gruppenname: object, aus_canvas: bool, canvas_titel: str | None,
                           aktivitaet_id: str) -> dict:
        if not self._darf():
            return {"status": "rejected", "summary": PC_AUS}
        client = self._client()
        if client is None or self.karte_anlegen is None:
            return {"status": "error", "summary": "Kein Zugriff auf den PC."}
        if not self.verfuegbar:
            return {"status": "rejected", "summary": "Teams geht an diesem PC nicht."}
        empfaenger = _empfaenger(an)
        if empfaenger is None:
            return {"status": "rejected", "summary": f"Empfänger fehlen oder sind ungültig: 1 bis {EMPFAENGER_MAX} Adressen oder Namen."}
        wert, fehler = await self._text(text, aus_canvas, canvas_titel)
        if fehler is not None:
            return fehler
        argumente = {"an": empfaenger, "text": wert, "gruppenname": gruppenname if isinstance(gruppenname, str) else ""}
        try:
            host = json.loads(await asyncio.wait_for(call_host_tool(client, "teams_chat_anfragen", argumente), ANFRAGE_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001 (Tunnel weg, Zeitgrenze, kaputte Antwort)
            logger.warning("Teams: Host antwortet nicht verwertbar ({})", type(e).__name__)
            return {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        return await self._karte(client, host, aktivitaet_id)

    async def _karte(self, client, host: object, aktivitaet_id: str) -> dict:
        anfrage = freigabe_anfrage(WERKZEUG, {}, host, aktivitaet_id) if isinstance(host, dict) else None
        if anfrage is None or anfrage.get("aktion") != "teams":
            status = host.get("status") if isinstance(host, dict) and host.get("status") in ("rejected", "blocked", "locked") else "error"
            summary = clean_inline(host.get("summary", "") if isinstance(host, dict) else "", 300)
            return {"status": status, "summary": summary or "Die Teams-Nachricht ließ sich nicht vorbereiten."}
        if self._fremd():
            anfrage["warnung"] = WARNUNG
        karte = self.karte_anlegen(anfrage)
        if karte is None and anfrage["id"] in self._karten:  # dieselbe Nachricht noch einmal: der Host gibt dieselbe Anfrage zurück
            return {"status": "wartet_auf_klick", "summary": "Diese Teams-Nachricht liegt schon als Karte zur Freigabe bereit."}
        if karte is None:  # zu viele offene Karten: am PC nichts offen lassen
            await pc_freigabe_entscheiden(client, anfrage["id"], False)
            return {"status": "error", "summary": "Es warten schon zu viele Freigaben. Erst entscheiden, dann neu anfragen."}
        self._karten.add(anfrage["id"])
        await self._melden(karte)
        return {"status": "wartet_auf_klick", "summary": BEREIT}

    # ---------- Klick aus der Oberfläche ----------
    async def client_nachricht(self, typ: str, daten: object) -> None:
        if typ == "teams_vorbereiten":
            await self._klick_vorbereiten(daten if isinstance(daten, dict) else {})

    async def _klick_vorbereiten(self, d: dict) -> None:
        an, text, gruppe = d.get("an"), d.get("text"), d.get("gruppenname", "")
        gueltig = (isinstance(an, list) and _empfaenger(an) is not None and isinstance(text, str) and 0 < len(text.strip())
                   and len(text) <= TEXT_MAX and isinstance(gruppe, str) and len(gruppe) <= GRUPPE_MAX)
        if not gueltig:
            await self._melden({"type": "teams_antwort", "ok": False, "grund": "Ungültige Angaben für die Teams-Nachricht."})
            return
        ergebnis = await self.vorbereiten(an=an, text=text, gruppenname=gruppe, quelle="klick")
        if ergebnis.get("status") == "wartet_auf_klick":
            await self._melden({"type": "teams_antwort", "ok": True})
        else:
            await self._melden({"type": "teams_antwort", "ok": False, "grund": ergebnis.get("summary") or "Nicht vorbereitet."})

    async def _melden(self, nachricht: dict) -> None:
        if self._senden is not None:
            try:
                await self._senden(nachricht)
            except Exception as e:  # noqa: BLE001 (Oberfläche weg: das Gespräch läuft weiter)
                logger.debug("Teams: Meldung an die Oberfläche fehlgeschlagen ({})", type(e).__name__)
