"""Mail über Outlook am PC aus dem Canvas (Paket 2 von docs/office-und-versand.md): Werkzeug outlook_senden und die Klicks mail_vorbereiten
und mail_zurueckholen.

Wer: nur admin, nie in einer Laborsitzung (das Labor hat eigene Werkzeuge wie mail_senden; dieses heißt bewusst anders), nur mit
WAMO_OFFICE (Teil "outlook", Standard leer = aus), nur bei eingeschalteter PC-Steuerung mit gehaltener Sperre (darf) und nur, wenn der
Host Mails vorbereiten kann (office_faehigkeiten meldet mail). Registriert wird nach werkzeuge_absichern: das Stimmabdruck-Gate gilt, das
Werkzeug steht nicht in OFFENE_WERKZEUGE.

Was: Auf Wunsch hängt der Kern das Canvas als Datei an (Export über office_werkzeuge.OfficeDateien, die Datei bleibt in Dokumente\\WAIS)
und fragt dann den Host (outlook_mail_anfragen, nie in LLM_TOOLS). Der Host erkennt das aktive Outlook und baut die Karte mit genau dem
Inhalt, der rausgeht. Die Karte geht über PcFreigaben (Job pc, Aktion mail); kamen im selben Zug Fremdinhalte vor (Web, Mail,
Bildschirm), trägt sie eine Warnung. Das Modell bekommt nur "liegt zur Freigabe bereit", nie die Kennung der Freigabe: Freigeben kann
nur der Klick in der Oberfläche.

Nach dem Klick (nach_freigabe, von PcFreigaben gerufen): Klassisches Outlook sendet nach 30 Sekunden; bis dahin zeigt die Oberfläche
"Zurückholen" (mail_zurueckholen, nur für Versände dieser Sitzung, mit dem Freigabe-Schlüssel). Den Endstand fragt der Kern beim Host
ab (outlook_versand_status) und zeigt ihn an; einen Fehler hört die Person zusätzlich vom Modell. Neues Outlook: der Entwurf ist offen,
die Person sendet selbst.

Nachrichten an die Oberfläche: {"type": "mail_antwort", "ok", "grund"?} nach mail_vorbereiten, {"type": "mail_versand", "id", "zustand",
"rest_s"?, "text"} für Versand und Entwurf. In actions steht die Karte (PcFreigaben, ohne Betreff und Text) und der Endstand eines
Versands als eigene Zeile (Werkzeug outlook_versand, nur die Kennung und der Zustand).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema

import labor
from activity import freigabe_anfrage
from canvas_quelle import kennung_gueltig
from memory import DB_ERRORS
from office_werkzeuge import FORMATE, office_teile
from pc_host import call_host_tool, freigabe_schluessel, pc_freigabe_entscheiden
from persona import clean_inline

TEIL = "outlook"
WERKZEUG = "outlook_senden"
NACHRICHTEN = ("mail_vorbereiten", "mail_zurueckholen")
FAEHIGKEITEN_TIMEOUT_SECS = 5.0
ANFRAGE_TIMEOUT_SECS = 60.0  # Erkennung und Auflösen im Adressbuch am PC (pc_tunnel.LANGE_WERKZEUGE)
EXPORT_TIMEOUT_SECS = 90.0  # PDF über Word, wie office_werkzeuge
ZURUECK_TIMEOUT_SECS = 10.0
STATUS_TIMEOUT_SECS = 5.0
STATUS_VERSUCHE = 10
EMPFAENGER_MAX = 10  # wie host/office_outlook.py; der Host prüft selbst
EINGABE_MAX = 254
BETREFF_MAX = 200
TEXT_MAX = 6000
VERSAND_RE = re.compile(r"[0-9a-f]{16}")
PC_AUS = "Die PC-Steuerung ist aus. Sie lässt sich in der Oberfläche einschalten."
WARNUNG = ("Im selben Gespräch kamen Inhalte aus Web, Mail oder Bildschirm. Prüfe Empfänger und Text besonders genau.")
ENDE = ("gesendet", "zurueckgeholt", "fehler", "unbekannt")


def outlook_an(wert: str | None = None) -> bool:
    return TEIL in office_teile(wert)


def fuer_sitzung(identity) -> bool:
    """Bekommt diese Sitzung Mails über Outlook? Nur admin, nie ein Laborprofil, nur mit Schalter."""
    return bool(getattr(identity, "is_admin", False)) and not labor.ist_labor(identity) and outlook_an()


def schema(formate: tuple[str, ...]) -> FunctionSchema:
    eigenschaften = {
        "an": {"type": "array", "items": {"type": "string"},
               "description": "Empfänger: Mailadressen oder Namen aus dem Adressbuch (im neuen Outlook nur Adressen), mit cc höchstens 10"},
        "cc": {"type": "array", "items": {"type": "string"}, "description": "Kopie, optional"},
        "betreff": {"type": "string"},
        "text": {"type": "string", "description": "Mailtext ohne Signatur, die Signatur kommt aus Outlook"},
    }
    if formate:
        eigenschaften["anhang"] = {"type": "string", "enum": list(formate),
                                   "description": "das Canvas als Datei in diesem Format anhängen; weglassen heißt ohne Anhang"}
        eigenschaften["canvas"] = {"type": "string", "description": "Titel des Canvas-Elements für den Anhang, leer = das zuletzt gezeigte"}
    return FunctionSchema(
        name=WERKZEUG,
        description=(
            "Bereitet eine E-Mail über Outlook am PC vor, auf Wunsch mit dem Canvas als Anhang. Es geht nichts raus ohne Klick: W.A.I.S. "
            "zeigt eine Freigabekarte mit genau dem Inhalt. Läuft das klassische Outlook, sendet W.A.I.S. nach dem Klick (30 Sekunden "
            "zurückholbar); läuft das neue Outlook, öffnet W.A.I.S. einen fertigen Entwurf und die Person sendet selbst. Adressen nie raten: "
            "nur Adressen oder Namen, die die Person genannt hat. Sag danach nur, dass die Mail zur Freigabe bereitliegt, nie 'gesendet'."
        ),
        properties=eigenschaften,
        required=["an", "betreff", "text"],
    )


def _als_liste(wert: object) -> list[str] | None:
    """Empfänger vom Modell: eine Liste aus Texten oder ein Text mit Komma oder Semikolon (wird geteilt); sonst None."""
    if wert is None:
        return []
    if isinstance(wert, str):
        return [t.strip() for t in re.split(r"[,;]", wert) if t.strip()]
    if isinstance(wert, list) and all(isinstance(w, str) for w in wert):
        return list(wert)
    return None


def _textliste(wert: object) -> list[str] | None:
    if wert is None:
        return []
    if not isinstance(wert, list) or not all(isinstance(w, str) and 0 < len(w.strip()) <= EINGABE_MAX for w in wert):
        return None
    return [w.strip() for w in wert]


class OutlookMail:
    """Mail über Outlook für eine Sitzung. client(): MCP-Client des Hosts; darf(): Rolle, Schalter, PC-Sperre; senden(nachricht): an
    die Oberfläche; melden(text): an das Modell; fremd(): kamen im Zug Fremdinhalte vor (turn.tainted); exportieren: OfficeDateien.exportieren
    für den Anhang (oder None, dann ohne Anhang); formate(): die Formate, die der Host als Datei erzeugen kann. karte_anlegen setzt bot.py
    (PcFreigaben.anfrage), ohne sie gibt es keine Mail."""

    def __init__(self, identity, memory, *, client: Callable[[], object], darf: Callable[[], bool],
                 senden: Callable[[dict], Awaitable[None]] | None, fremd: Callable[[], bool],
                 melden: Callable[[str], Awaitable[None]] | None = None, exportieren: Callable[..., Awaitable[dict]] | None = None,
                 formate: Callable[[], tuple[str, ...]] = lambda: ()):
        if not getattr(identity, "is_admin", False) or labor.ist_labor(identity):
            raise ValueError("Mail über Outlook gibt es nur für Admins und nie im Labor")
        self.identity, self.memory = identity, memory
        self._client, self._darf, self._senden, self._melden_llm = client, darf, senden, melden
        self._fremd, self._exportieren, self._formate = fremd, exportieren, formate
        self.karte_anlegen: Callable[[dict], dict | None] | None = None
        self.verfuegbar = False
        self.status_nach_secs: float | None = None  # None: Frist plus 2 Sekunden (Tests setzen 0)
        self.status_abstand_secs = 3.0
        self._laeuft = False  # je Sitzung höchstens eine Vorbereitung (Doppelklick, doppelter Werkzeugaufruf)
        self._karten: set[str] = set()  # Freigaben, deren Karte diese Sitzung schon gezeigt hat
        self._eigene: set[str] = set()  # Versände dieser Sitzung (nur sie lassen sich zurückholen)
        self._erledigt: set[str] = set()  # Endstand schon gemeldet
        self._aufgaben: set[asyncio.Task] = set()

    # ---------- Fähigkeiten und Registrierung ----------
    def _anhang_formate(self) -> tuple[str, ...]:
        if self._exportieren is None:
            return ()
        return tuple(f for f in FORMATE if f in (self._formate() or ()))

    async def schemas(self) -> list[FunctionSchema]:
        """Fragt den Host, ob er Mails vorbereiten kann. Wirft nie."""
        self.verfuegbar = False
        client = self._client()
        if client is None:
            return []
        try:
            antwort = json.loads(await asyncio.wait_for(call_host_tool(client, "office_faehigkeiten", {}), FAEHIGKEITEN_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001 (älterer Host, Tunnel weg: ohne Mail weiter)
            logger.info("Mail über Outlook: Host meldet keine Fähigkeiten ({})", type(e).__name__)
            return []
        if not isinstance(antwort, dict) or antwort.get("status") != "success" or antwort.get("mail") is not True:
            return []
        self.verfuegbar = True
        return [schema(self._anhang_formate())]

    def register(self, llm) -> None:
        # Kein Abbruch bei einem Einwurf: Sonst hielte der PC eine Anfrage ohne Karte, und dort ruhten die Eingaben bis zum Ablauf
        llm.register_function(WERKZEUG, self._werkzeug, cancel_on_interruption=False,
                              timeout_secs=ANFRAGE_TIMEOUT_SECS + EXPORT_TIMEOUT_SECS)

    def anzeige(self) -> bool:
        """Für die Oberfläche (Feld mail in betrieb): Knopf "Als E-Mail" nur, solange es geht."""
        return bool(self.verfuegbar and self._darf())

    # ---------- Werkzeug ----------
    async def _werkzeug(self, params) -> None:
        a = params.arguments if isinstance(params.arguments, dict) else {}
        titel = a.get("canvas") if isinstance(a.get("canvas"), str) and a.get("canvas").strip() else None
        ergebnis = await self.vorbereiten(an=a.get("an"), cc=a.get("cc"), betreff=a.get("betreff"), text=a.get("text"),
                                          anhang=a.get("anhang"), canvas_titel=titel, quelle="sprache",
                                          aktivitaet_id=str(getattr(params, "tool_call_id", "") or ""))
        await params.result_callback(ergebnis)

    async def vorbereiten(self, *, an: object, cc: object, betreff: object, text: object, anhang: object = None,
                          canvas_id: str | None = None, canvas_titel: str | None = None, quelle: str, aktivitaet_id: str = "") -> dict:
        """Gemeinsamer Weg für Sprache und Klick: Anhang exportieren, Host fragen, Karte anlegen. Liefert die Antwort für das Modell.
        Läuft schon eine Vorbereitung dieser Sitzung, kommt eine Ablehnung (keine zweite Datei, keine zweite Karte)."""
        if self._laeuft:
            return {"status": "rejected", "summary": "Eine Mail wird gerade schon vorbereitet. Bitte einen Moment warten."}
        self._laeuft = True  # ohne await dazwischen gesetzt: kein zweiter Aufruf kommt vorbei
        logger.info("Mail über Outlook: Vorbereitung ({})", quelle)  # nur woher, nie Empfänger, Betreff oder Text
        try:
            return await self._vorbereiten(an=an, cc=cc, betreff=betreff, text=text, anhang=anhang, canvas_id=canvas_id,
                                           canvas_titel=canvas_titel, aktivitaet_id=aktivitaet_id)
        finally:
            self._laeuft = False

    async def _vorbereiten(self, *, an: object, cc: object, betreff: object, text: object, anhang: object, canvas_id: str | None,
                           canvas_titel: str | None, aktivitaet_id: str) -> dict:
        if not self._darf():
            return {"status": "rejected", "summary": PC_AUS}
        client = self._client()
        if client is None or self.karte_anlegen is None:
            return {"status": "error", "summary": "Kein Zugriff auf den PC."}
        if not self.verfuegbar:
            return {"status": "rejected", "summary": "Mail über Outlook geht an diesem PC nicht."}
        an_liste, cc_liste = _als_liste(an), _als_liste(cc)
        if not an_liste or cc_liste is None:
            return {"status": "rejected", "summary": "Empfänger fehlen oder sind ungültig: bitte Adressen oder Namen als Liste angeben."}
        kennungen: list[str] = []
        if anhang not in (None, "", "keiner", "ohne"):
            if anhang not in self._anhang_formate():
                return {"status": "rejected", "summary": "Dieses Format geht als Anhang nicht."}
            try:
                datei = await asyncio.wait_for(self._exportieren(anhang, canvas_id=canvas_id, titel=canvas_titel, oeffnen=False,
                                                                 quelle="mail"), EXPORT_TIMEOUT_SECS)
            except Exception as e:  # noqa: BLE001
                logger.warning("Mail über Outlook: Anhang nicht erstellt ({})", type(e).__name__)
                datei = {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
            if datei.get("status") != "success" or not isinstance(datei.get("datei"), dict):
                return {"status": datei.get("status", "error") if datei.get("status") in ("rejected", "blocked", "locked") else "error",
                        "summary": f"Ohne Anhang keine Mail: {clean_inline(datei.get('summary', ''), 300)}"}
            kennungen.append(datei["datei"]["kennung"])
        argumente = {"an": an_liste, "cc": cc_liste, "betreff": betreff if isinstance(betreff, str) else "",
                     "text": text if isinstance(text, str) else "", "anhaenge": kennungen}
        try:
            host = json.loads(await asyncio.wait_for(call_host_tool(client, "outlook_mail_anfragen", argumente), ANFRAGE_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001 (Tunnel weg, Zeitgrenze, kaputte Antwort)
            logger.warning("Mail über Outlook: Host antwortet nicht verwertbar ({})", type(e).__name__)
            return {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        anfrage = freigabe_anfrage(WERKZEUG, {}, host, aktivitaet_id) if isinstance(host, dict) else None
        if anfrage is None or anfrage.get("aktion") != "mail":
            status = host.get("status") if isinstance(host, dict) and host.get("status") in ("rejected", "blocked", "locked") else "error"
            summary = clean_inline(host.get("summary", "") if isinstance(host, dict) else "", 300)
            return {"status": status, "summary": summary or "Die Mail ließ sich nicht vorbereiten."}
        if self._fremd():
            anfrage["warnung"] = WARNUNG
        karte = self.karte_anlegen(anfrage)
        if karte is None and anfrage["id"] in self._karten:  # dieselbe Mail noch einmal: der Host gibt dieselbe Anfrage zurück
            return {"status": "wartet_auf_klick", "summary": "Diese Mail liegt schon als Karte zur Freigabe bereit."}
        if karte is None:  # zu viele offene Karten: am PC nichts offen lassen
            await pc_freigabe_entscheiden(client, anfrage["id"], False)
            return {"status": "error", "summary": "Es warten schon zu viele Freigaben. Erst entscheiden, dann neu anfragen."}
        self._karten.add(anfrage["id"])
        await self._melden(karte)
        return {"status": "wartet_auf_klick",
                "summary": "Die Mail liegt als Karte zur Freigabe bereit. Erst nach dem Klick in der Oberfläche passiert etwas."}

    # ---------- Klicks aus der Oberfläche ----------
    async def client_nachricht(self, typ: str, daten: object) -> None:
        d = daten if isinstance(daten, dict) else {}
        if typ == "mail_vorbereiten":
            await self._klick_vorbereiten(d)
        elif typ == "mail_zurueckholen":
            await self._zurueckholen(d.get("id"))

    async def _klick_vorbereiten(self, d: dict) -> None:
        an, cc = _textliste(d.get("an")), _textliste(d.get("cc"))
        betreff, text, anhang = d.get("betreff"), d.get("text", ""), d.get("anhang")
        kennung = kennung_gueltig(d.get("canvas_id")) if anhang else None
        gueltig = (an and cc is not None and len(an) + len(cc) <= EMPFAENGER_MAX and isinstance(betreff, str)
                   and 0 < len(betreff.strip()) <= BETREFF_MAX and isinstance(text, str) and len(text) <= TEXT_MAX
                   and (anhang is None or (anhang in FORMATE and kennung is not None)))
        if not gueltig:
            await self._melden({"type": "mail_antwort", "ok": False, "grund": "Ungültige Angaben für die Mail."})
            return
        ergebnis = await self.vorbereiten(an=an, cc=cc, betreff=betreff, text=text, anhang=anhang, canvas_id=kennung, quelle="klick")
        if ergebnis.get("status") == "wartet_auf_klick":
            await self._melden({"type": "mail_antwort", "ok": True})
        else:
            await self._melden({"type": "mail_antwort", "ok": False, "grund": ergebnis.get("summary") or "Nicht vorbereitet."})

    # ---------- Nach dem Klick auf der Karte (PcFreigaben.nach_ergebnis) ----------
    async def nach_freigabe(self, anfrage: dict, ergebnis: dict) -> None:
        if anfrage.get("werkzeug") != WERKZEUG or anfrage.get("aktion") != "mail" or not isinstance(ergebnis, dict):
            return
        if ergebnis.get("status") != "success":
            return  # der Fehler geht über PcFreigaben an das Modell
        versand = ergebnis.get("versand")
        if not isinstance(versand, dict) or not (isinstance(versand.get("id"), str) and VERSAND_RE.fullmatch(versand["id"])):
            await self._melden({"type": "mail_versand", "id": None, "zustand": "entwurf",
                                "text": clean_inline(ergebnis.get("summary", ""), 300) or "Der Entwurf ist offen."})
            return
        vid = versand["id"]
        frist = versand.get("frist_s")
        frist = frist if isinstance(frist, int) and not isinstance(frist, bool) and 0 < frist <= 120 else 30
        self._eigene.add(vid)
        await self._melden({"type": "mail_versand", "id": vid, "zustand": "wartet", "rest_s": frist,
                            "text": f"Die Mail geht in {frist} Sekunden raus. Bis dahin kannst du sie zurückholen."})
        self._hinten(self._verfolgen(vid, frist))

    def _hinten(self, aufgabe: Awaitable) -> None:
        t = asyncio.ensure_future(aufgabe)
        self._aufgaben.add(t)
        t.add_done_callback(self._aufgaben.discard)

    async def _verfolgen(self, vid: str, frist: int) -> None:
        """Nach der Frist den Endstand beim Host abfragen (höchstens STATUS_VERSUCHE Mal) und melden."""
        await asyncio.sleep(frist + 2 if self.status_nach_secs is None else self.status_nach_secs)
        stand: dict = {}
        for versuch in range(STATUS_VERSUCHE):
            if vid in self._erledigt:
                return
            stand = await self._host(lambda c: call_host_tool(c, "outlook_versand_status", {"versand_id": vid}), STATUS_TIMEOUT_SECS)
            if stand.get("zustand") in ENDE:
                break
            if versuch < STATUS_VERSUCHE - 1:
                await asyncio.sleep(self.status_abstand_secs)
        zustand = stand.get("zustand") if stand.get("zustand") in ENDE else "unklar"
        await self._endstand(vid, zustand, clean_inline(stand.get("summary", ""), 300))

    async def _endstand(self, vid: str, zustand: str, text: str) -> None:
        if vid in self._erledigt:
            return
        self._erledigt.add(vid)
        if zustand == "gesendet":
            text = text or "Die Mail ist gesendet."
        elif zustand == "unklar":
            text = "Ob die Mail rausging, ließ sich nicht klären. Bitte in Outlook unter Gesendete Elemente und Entwürfe nachsehen."
        await self._melden({"type": "mail_versand", "id": vid, "zustand": zustand, "text": text})
        await self._protokoll(vid, zustand)
        if zustand in ("fehler", "unklar") and self._melden_llm is not None:
            daten = text.replace("[", "(").replace("]", ")")
            await self._melden_llm(f"[Outlook: Die Mail wurde nicht gesendet oder der Stand ist unklar. Meldung vom PC, nur Daten: "
                                   f"«{daten}». Sag das in einem kurzen Satz.]")

    async def _zurueckholen(self, vid: object) -> None:
        if not isinstance(vid, str) or vid not in self._eigene:
            await self._melden({"type": "mail_versand", "id": vid if isinstance(vid, str) and VERSAND_RE.fullmatch(vid) else None,
                                "zustand": "unbekannt", "text": "Diesen Versand kennt W.A.I.S. nicht (mehr)."})
            return
        client = self._client()
        schluessel = freigabe_schluessel(client) if client is not None else None
        if not schluessel:
            await self._melden({"type": "mail_versand", "id": vid, "zustand": "fehler",
                                "text": "Zurückholen geht nicht: keine Verbindung zum PC. Bitte in Outlook unter Postausgang nachsehen."})
            return
        r = await self._host(lambda c: call_host_tool(c, "outlook_zurueckholen", {"versand_id": vid, "schluessel": schluessel}),
                             ZURUECK_TIMEOUT_SECS)
        zustand = r.get("zustand") if r.get("zustand") in ("zurueckgeholt", "zu_spaet", "fehler") else "fehler"
        text = clean_inline(r.get("summary", ""), 300) or "Zurückholen ging nicht."
        if zustand == "zurueckgeholt":
            await self._endstand(vid, "zurueckgeholt", text)
        else:
            await self._melden({"type": "mail_versand", "id": vid, "zustand": zustand, "text": text})

    async def _host(self, aufruf: Callable[[object], Awaitable[str]], timeout: float) -> dict:
        client = self._client()
        if client is None:
            return {}
        try:
            antwort = json.loads(await asyncio.wait_for(aufruf(client), timeout))
        except Exception as e:  # noqa: BLE001
            logger.warning("Mail über Outlook: Host antwortet nicht verwertbar ({})", type(e).__name__)
            return {}
        return antwort if isinstance(antwort, dict) else {}

    async def schliessen(self) -> None:
        """Sitzungsende: nur das Nachfragen endet; ein freigegebener Versand läuft am PC wie freigegeben weiter."""
        for t in list(self._aufgaben):
            t.cancel()

    # ---------- Ausgaben ----------
    async def _melden(self, nachricht: dict) -> None:
        if self._senden is not None:
            try:
                await self._senden(nachricht)
            except Exception as e:  # noqa: BLE001 (Oberfläche weg: das Gespräch läuft weiter)
                logger.debug("Mail über Outlook: Meldung an die Oberfläche fehlgeschlagen ({})", type(e).__name__)

    async def _protokoll(self, vid: str, zustand: str) -> None:
        """Endstand eines Versands in actions, ohne Inhalte."""
        if not getattr(self.memory, "enabled", False):
            return
        status = {"gesendet": "done", "zurueckgeholt": "rejected"}.get(zustand, "failed")
        db = self.memory.db
        try:
            await db.execute(
                f"insert into {db.t('actions')} (user_id, session_id, tool, params, reason, risk, status, result, decided_at, "
                f"finished_at) values ($1::uuid, $2::uuid, $3, $4::text::jsonb, $5, $6::text::{db.t('risk_class')}, "
                f"$7::text::{db.t('action_status')}, $8::text::jsonb, now(), now())",
                self.memory.user_id, self.memory.session_id, "outlook_versand", json.dumps({"versand_id": vid}), "Mail über Outlook",
                "critical", status, json.dumps({"zustand": zustand}))
        except DB_ERRORS as e:
            logger.warning("Mail über Outlook: Protokoll nicht geschrieben ({})", type(e).__name__)
