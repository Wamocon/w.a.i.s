"""OneNote-Seite aus dem Canvas (Paket 4 von docs/office-und-versand.md, Teil OneNote): Werkzeug onenote_seite und der Klick
"Als OneNote-Seite" im Canvas (Client-Nachricht onenote_seite).

Wer: nur admin, nie in einer Laborsitzung (fuer_sitzung, dazu prüft der Konstruktor selbst), nur mit WAMO_OFFICE (Teil "onenote",
Standard leer = aus), nur bei eingeschalteter PC-Steuerung mit gehaltener Sperre (darf) und nur, wenn der Host das Werkzeug kennt
(office_faehigkeiten meldet "onenote"). Das Werkzeug wird am LLM registriert, nachdem werkzeuge_absichern das Stimmabdruck-Gate
eingehängt hat; es steht nicht in OFFENE_WERKZEUGE.

Was: Der Kern liest das eigene Canvas-Element (canvas_quelle.py) und schickt dem Host nur dessen feste Struktur
(onenote_seite_anfragen, nie in LLM_TOOLS). Der Host prüft selbst, bestimmt das OneDrive der Firma und das Notizbuch W.A.I.S. darin
und legt eine Freigabe-Anfrage an (needs_approval, Aktion onenote). Per Sprache macht activity.py daraus die Karte, per Klick dieses
Modul über karte (pc_freigaben.PcFreigaben.anfrage); beide Wege zeigen Konto, Notizbuch, Abschnitt, Titel und den ganzen Inhalt.
Angelegt wird erst nach dem Klick eines Admins auf die Karte (pc_freigaben.py, freigabe_entscheiden im Host), genau einmal; fehlt das
Notizbuch, legt der Host es erst dann an.

Rückfall: Fehlt OneNote für den Desktop, gibt es kein eindeutiges OneDrive der Firma oder ist OneNote nicht bereit (Fähigkeiten oder
rueckfall "word" vom Host), speichert der Kern die Seite als Word-Datei in Dokumente\\WAIS (office_werkzeuge.OfficeDateien.exportieren,
ohne Karte wie in Paket 1) und sagt, dass sie sich über "An OneNote senden" in OneNote einfügen lässt.

Oberfläche: betrieb trägt "onenote": true, solange der Knopf gehen kann (anzeige). Nach einem Klick meldet der Kern
{"type": "onenote", "ok", "text"}: Karte liegt bereit, Rückfall als Word-Datei oder der Grund, warum nicht.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema

import labor
from activity import APPROVAL_ID_RE, freigabe_anfrage
from canvas_quelle import CanvasNichtErreichbar, canvas_lesen, kennung_gueltig
from office_werkzeuge import (CANVAS_NICHT_ERREICHBAR, ERSTELLEN_TIMEOUT_SECS, FAEHIGKEITEN_TIMEOUT_SECS, KEIN_CANVAS, PC_AUS,
                              OfficeDateien, office_teile)
from pc_host import call_host_tool, pc_freigabe_entscheiden
from persona import clean_inline

TEIL = "onenote"
WERKZEUG = "onenote_seite"
NACHRICHT = "onenote_seite"  # Klick "Als OneNote-Seite" im Canvas, {"canvas_id"}
AKTION = "onenote"
ANFRAGEN_TIMEOUT_SECS = 50.0  # Host: Notizbücher lesen bis 30 s, Tunnel 45 s (pc_tunnel.LANGE_WERKZEUGE)
WERKZEUG_TIMEOUT_SECS = ANFRAGEN_TIMEOUT_SECS + ERSTELLEN_TIMEOUT_SECS + 5  # Anfrage, danach höchstens der Rückfall als Word-Datei
KARTEN_FELDER = ("status", "approval_id", "aktion", "grund", "detail", "ziel", "gueltig_s", "summary", "anlass")
STATUS = ("success", "rejected", "blocked", "locked", "wartet", "error")
KEINE_ANTWORT = {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
ONENOTE_FEHLT = "OneNote für den Desktop ist an diesem PC nicht installiert."
LAEUFT_SCHON = "Eine OneNote-Seite wird gerade schon vorbereitet. Bitte einen Moment warten."
RUECKFALL = ("{grund} Stattdessen liegt die Seite als Word-Datei {name} im Ordner {ordner}. Über „An OneNote senden“ lässt sie "
             "sich in OneNote einfügen.")
KARTE_BEREIT = "Die OneNote-Seite liegt zur Freigabe bereit. Erst nach deinem Klick auf der Karte wird sie angelegt."
KEINE_KARTE = "Die Freigabekarte ließ sich nicht anzeigen. Am PC ist nichts passiert."


def fuer_sitzung(identity) -> bool:
    """Bekommt diese Sitzung OneNote-Seiten? Nur admin, nie ein Laborprofil, nur mit WAMO_OFFICE=onenote."""
    return bool(getattr(identity, "is_admin", False)) and not labor.ist_labor(identity) and TEIL in office_teile()


def schema() -> FunctionSchema:
    return FunctionSchema(
        name=WERKZEUG,
        description=(
            "Legt ein Canvas-Element als neue Seite in OneNote an, im Notizbuch W.A.I.S. im OneDrive der Firma (nie in einem anderen "
            "Notizbuch). Ohne canvas gilt das zuletzt gezeigte Element. Die Seite entsteht erst, wenn ein Admin die Freigabekarte in "
            "der Oberfläche bestätigt: Sag danach nur, dass die Karte bereitliegt, nie, dass die Seite schon angelegt ist. Geht "
            "OneNote am PC nicht, speichert das Werkzeug stattdessen eine Word-Datei im Ordner WAIS; sag dann den Grund und dass sie "
            "sich über „An OneNote senden“ einfügen lässt."
        ),
        properties={
            "canvas": {"type": "string", "description": "Titel des Canvas-Elements, leer = das zuletzt gezeigte"},
            "titel": {"type": "string", "description": "Seitentitel, leer = Titel des Canvas (höchstens 120 Zeichen)"},
        },
        required=[],
    )


class OneNoteSeiten:
    """karte(anfrage) registriert eine Freigabe-Anfrage für diese Sitzung und liefert die Karte für die Oberfläche oder None
    (pc_freigaben.PcFreigaben.anfrage); ohne karte gibt es den Klickweg nicht."""

    def __init__(self, identity, memory, *, client: Callable[[], object], darf: Callable[[], bool],
                 senden: Callable[[dict], Awaitable[None]] | None, karte: Callable[[dict], dict | None] | None = None):
        if not getattr(identity, "is_admin", False) or labor.ist_labor(identity):
            raise ValueError("OneNote-Seiten gibt es nur für Admins und nie im Labor")
        self.memory, self._client, self._darf, self._senden, self._karte_fuer = memory, client, darf, senden, karte
        self._dateien = OfficeDateien(identity, memory, client=client, darf=darf, senden=senden)  # nur für den Rückfall
        self.onenote = self.word = False
        self._laeuft = False  # je Sitzung höchstens eine Anfrage zur Zeit

    # ---------- Fähigkeiten und Registrierung ----------
    async def schemas(self) -> list[FunctionSchema]:
        """Fragt den Host, ob OneNote (oder als Rückfall Word) geht, und liefert das Schema oder nichts. Wirft nie."""
        self.onenote = self.word = False
        self._dateien.formate = ()
        client = self._client()
        if client is None:
            return []
        antwort = await self._host(client, "office_faehigkeiten", {}, FAEHIGKEITEN_TIMEOUT_SECS)
        if antwort.get("status") != "success" or not isinstance(antwort.get("onenote"), bool):
            return []  # älterer Host ohne OneNote-Werkzeug, office.aus oder Tunnel weg
        self.onenote = antwort["onenote"]
        self.word = isinstance(antwort.get("formate"), list) and "word" in antwort["formate"]
        self._dateien.formate = ("word",) if self.word else ()
        logger.info("OneNote-Seiten: OneNote {}, Rückfall Word {}", self.onenote, self.word)
        return [schema()] if self.onenote or self.word else []

    def register(self, llm) -> None:
        # Kein Abbruch bei einem Einwurf: Sonst legt der Host die Anfrage an, aber die Karte erscheint nie, und am PC ruhen die Eingaben
        # bis zum Ablauf der Anfrage (wie canvas_exportieren)
        llm.register_function(WERKZEUG, self._werkzeug, cancel_on_interruption=False, timeout_secs=WERKZEUG_TIMEOUT_SECS)

    def anzeige(self) -> bool:
        """Knopf "Als OneNote-Seite" (Feld onenote in betrieb): nur mit OneNote am PC, Klickweg für Karten und PC-Steuerung an."""
        return self.onenote and self._karte_fuer is not None and self._darf()

    # ---------- Werkzeug ----------
    async def _werkzeug(self, params) -> None:
        a = params.arguments if isinstance(params.arguments, dict) else {}
        canvas = a.get("canvas") if isinstance(a.get("canvas"), str) and a.get("canvas").strip() else None
        titel = a.get("titel") if isinstance(a.get("titel"), str) else ""
        await params.result_callback(await self.anlegen(canvas=canvas, titel=titel))

    async def anlegen(self, *, canvas: str | None = None, titel: str = "", canvas_id: str | None = None) -> dict:
        """Freigabe-Anfrage im Host (needs_approval wird zur Karte), Rückfall als Word-Datei oder eine Ablehnung. Läuft schon eine
        Anfrage dieser Sitzung, kommt eine Ablehnung."""
        if self._laeuft:
            return {"status": "rejected", "summary": LAEUFT_SCHON}
        self._laeuft = True  # ohne await dazwischen gesetzt: kein zweiter Aufruf kommt vorbei
        try:
            return await self._anlegen(canvas, titel, canvas_id)
        finally:
            self._laeuft = False

    async def _anlegen(self, canvas: str | None, titel: str, canvas_id: str | None) -> dict:
        if not self._darf():
            return {"status": "rejected", "summary": PC_AUS}
        client = self._client()
        if client is None:
            return {"status": "error", "summary": "Kein Zugriff auf den PC."}
        try:
            gefunden = await canvas_lesen(self.memory, canvas_id=canvas_id, titel=canvas)
        except CanvasNichtErreichbar:
            return {"status": "error", "summary": CANVAS_NICHT_ERREICHBAR}
        if gefunden is None:
            return {"status": "rejected", "summary": KEIN_CANVAS}
        if not self.onenote:
            return await self._rueckfall(gefunden, ONENOTE_FEHLT)
        argumente = {"inhalt": gefunden["inhalt"], "titel": titel, "canvas_id": gefunden["id"]}
        antwort = await self._host(client, "onenote_seite_anfragen", argumente, ANFRAGEN_TIMEOUT_SECS)
        if antwort.get("status") == "needs_approval":
            return self._karte(antwort)
        grund = clean_inline(antwort.get("summary", ""), 300)
        if antwort.get("rueckfall") == "word":
            return await self._rueckfall(gefunden, grund or ONENOTE_FEHLT)
        return {"status": antwort.get("status") if antwort.get("status") in STATUS else "error", "summary": grund}

    @staticmethod
    def _karte(antwort: dict) -> dict:
        """Nur die Felder der Freigabe-Anfrage, nur mit gültiger Kennung und Aktion onenote; activity.py prüft den Rest."""
        if not (isinstance(antwort.get("approval_id"), str) and APPROVAL_ID_RE.fullmatch(antwort["approval_id"])
                and antwort.get("aktion") == AKTION):
            logger.warning("OneNote: Freigabe-Anfrage des Hosts passt nicht")
            return dict(KEINE_ANTWORT)
        return {k: antwort[k] for k in KARTEN_FELDER if k in antwort}

    async def _rueckfall(self, gefunden: dict, grund: str) -> dict:
        """Ohne OneNote: dieselbe Seite als Word-Datei in Dokumente\\WAIS (wie canvas_exportieren, Meldung an die Oberfläche inklusive)."""
        if not self.word:
            return {"status": "rejected", "summary": f"{grund} Eine Word-Datei als Ersatz geht an diesem PC auch nicht."}
        ergebnis = await self._dateien.exportieren("word", canvas_id=gefunden["id"], quelle=TEIL)
        if ergebnis.get("status") != "success":
            return {"status": ergebnis.get("status", "error"), "summary": f"{grund} Auch die Word-Datei ging nicht: "
                    f"{ergebnis.get('summary', '')}".strip()}
        datei = ergebnis["datei"]
        return {"status": "success", "onenote": False, "gespeichert": True, "datei": datei["name"], "ordner": datei["ordner"],
                "geoeffnet": ergebnis["geoeffnet"], "summary": RUECKFALL.format(grund=grund, name=datei["name"],
                                                                               ordner=datei["ordner"] or "WAIS")}

    # ---------- Klick "Als OneNote-Seite" ----------
    async def client_nachricht(self, daten: object) -> None:
        """Klick im Canvas: dieselbe Anfrage wie per Sprache, die Karte entsteht hier statt in activity.py."""
        kennung = kennung_gueltig(daten.get("canvas_id")) if isinstance(daten, dict) else None
        if kennung is None:
            await self._melden(False, "Ungültige Anfrage.")
            return
        ergebnis = await self.anlegen(canvas_id=kennung)
        if ergebnis.get("status") == "needs_approval":
            await self._karte_zeigen(ergebnis)
        elif ergebnis.get("status") == "success":
            await self._melden(True, ergebnis.get("summary", ""))
        else:
            await self._melden(False, ergebnis.get("summary") or "Nicht angelegt.")

    async def _karte_zeigen(self, ergebnis: dict) -> None:
        anfrage = freigabe_anfrage(WERKZEUG, {}, ergebnis, "")
        karte = self._karte_fuer(anfrage) if anfrage is not None and self._karte_fuer is not None else None
        if karte is None:  # keine Karte, die jemand bestätigen könnte: die Anfrage am PC sofort ablehnen, sonst ruhen dort die Eingaben
            logger.warning("OneNote: Karte für den Klick nicht anzeigbar, Anfrage am PC abgelehnt")
            client = self._client()
            if client is not None and isinstance(ergebnis.get("approval_id"), str):
                await pc_freigabe_entscheiden(client, ergebnis["approval_id"], False)
            await self._melden(False, KEINE_KARTE)
            return
        await self._ui(karte)
        await self._melden(True, KARTE_BEREIT)

    # ---------- Ausgaben ----------
    async def _melden(self, ok: bool, text: str) -> None:
        await self._ui({"type": "onenote", "ok": ok, "text": clean_inline(text, 400)})

    async def _ui(self, nachricht: dict) -> None:
        if self._senden is not None:
            try:
                await self._senden(nachricht)
            except Exception as e:  # noqa: BLE001 (Oberfläche weg: das Gespräch läuft weiter)
                logger.debug("OneNote: Meldung an die Oberfläche fehlgeschlagen ({})", type(e).__name__)

    @staticmethod
    async def _host(client, name: str, argumente: dict, frist: float) -> dict:
        """Ein Aufruf im Host; jede Störung (Tunnel, Zeitgrenze, kaputte Antwort) wird zu einer festen Fehlermeldung."""
        try:
            antwort = json.loads(await asyncio.wait_for(call_host_tool(client, name, argumente), frist))
        except Exception as e:  # noqa: BLE001 (älterer Host ohne Werkzeug, Tunnel weg)
            logger.info("OneNote: {} ohne verwertbare Antwort ({})", name, type(e).__name__)
            return dict(KEINE_ANTWORT)
        return antwort if isinstance(antwort, dict) else dict(KEINE_ANTWORT)
