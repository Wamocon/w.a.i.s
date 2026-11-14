"""Office-Dateien aus dem Canvas (Paket 1 von docs/office-und-versand.md): Werkzeug canvas_exportieren und die Klicks canvas_export
und datei_oeffnen.

Wer: nur admin, nie in einer Laborsitzung (fuer_sitzung, dazu prüft der Konstruktor selbst), nur mit WAMO_OFFICE (Teil "dateien",
Standard leer = aus), nur bei eingeschalteter PC-Steuerung mit gehaltener Sperre (darf) und nur in den Formaten, die der Host meldet
(office_faehigkeiten). Das Werkzeug wird am LLM registriert, nachdem werkzeuge_absichern das Stimmabdruck-Gate eingehängt hat; es
steht nicht in OFFENE_WERKZEUGE.

Was: Der Kern liest das eigene Canvas-Element aus canvas_items (canvas_quelle.py) und schickt dem Host nur dessen feste Struktur, nie
Dateibytes. Der Host prüft, baut, legt die Datei in Dokumente\\WAIS ab und öffnet sie (office_datei_erstellen, nie in LLM_TOOLS).
Speichern braucht keine Freigabekarte (Entscheidung vom 14.11.2026: nichts verlässt den PC).

Rückmeldung: Das Modell bekommt nur gespeichert, Dateiname, geöffnet und den Ordner, nie den vollen Pfad. Die Oberfläche bekommt die
Nachricht {"type": "datei", "ok", "kennung", "name", "format", "ordner", "pfad", "geoeffnet"} oder {"type": "datei", "ok": false,
"grund"}. In actions stehen Werkzeug, Format, Canvas-Kennung, Quelle, Dateiname, Größe und Prüfsummenanfang, nie der Inhalt.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema

import labor
from canvas_quelle import canvas_lesen, kennung_gueltig
from memory import DB_ERRORS
from pc_host import call_host_tool
from persona import clean_inline

SCHALTER = "WAMO_OFFICE"
TEILE = ("dateien", "outlook", "teams", "onenote")
WERKZEUG = "canvas_exportieren"
NACHRICHTEN = ("canvas_export", "datei_oeffnen")
FORMATE = ("word", "excel", "powerpoint", "pdf", "csv", "markdown")
_TEXTFORMATE = ("word", "powerpoint", "pdf", "markdown")
FORMATE_JE_ART = {"dokument": _TEXTFORMATE, "code": _TEXTFORMATE, "mermaid": _TEXTFORMATE, "tabelle": FORMATE}  # wie host/office_dateien.py
FORMAT_NAMEN = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint", "pdf": "PDF", "csv": "CSV", "markdown": "Markdown"}
FAEHIGKEITEN_TIMEOUT_SECS = 5.0
ERSTELLEN_TIMEOUT_SECS = 85.0  # PDF über Word bis 45 s am PC, dazu Bau und Tunnel (pc_tunnel.LANGE_WERKZEUGE: 80 s)
OEFFNEN_TIMEOUT_SECS = 15.0
KENNUNG_RE = re.compile(r"[0-9a-f]{16}")
PC_AUS = "Die PC-Steuerung ist aus. Sie lässt sich in der Oberfläche einschalten."  # wie screen.PC_OFF
KEIN_CANVAS = ("Kein eigenes Canvas-Element gefunden. Speichern geht nur für Inhalte, die W.A.I.S. für dich auf das Canvas gelegt "
               "hat.")


def office_teile(wert: str | None = None) -> set[str]:
    """Teile aus WAMO_OFFICE (Komma oder Leerzeichen getrennt). Leer, unbekannt oder ein Tippfehler heißt: dieser Teil ist aus."""
    roh = os.getenv(SCHALTER, "") if wert is None else wert
    teile = {t for t in re.split(r"[\s,;]+", (roh or "").strip().lower()) if t}
    if unbekannt := teile - set(TEILE):
        logger.warning("{} kennt {} nicht (erlaubt: {})", SCHALTER, sorted(unbekannt), ", ".join(TEILE))
    return teile & set(TEILE)


def dateien_an(wert: str | None = None) -> bool:
    return "dateien" in office_teile(wert)


def fuer_sitzung(identity) -> bool:
    """Bekommt diese Sitzung Office-Dateien? Nur admin, nie ein Laborprofil, nur mit Schalter."""
    return bool(getattr(identity, "is_admin", False)) and not labor.ist_labor(identity) and dateien_an()


def schema(formate: tuple[str, ...]) -> FunctionSchema:
    return FunctionSchema(
        name=WERKZEUG,
        description=(
            "Speichert ein Canvas-Element als Datei auf dem PC im Ordner WAIS in Dokumente und öffnet sie (Word, Excel, PowerPoint, PDF, "
            "CSV oder Markdown, nur die hier angebotenen). Excel und CSV gibt es nur für Tabellen. Ohne canvas gilt das zuletzt "
            "gezeigte Element. Es braucht keine Freigabe, die Datei verlässt den PC nicht. Sag danach in einem Satz, dass sie im Ordner "
            "WAIS liegt und offen ist. Senden oder Teilen kann dieses Werkzeug nicht."
        ),
        properties={
            "format": {"type": "string", "enum": list(formate)},
            "canvas": {"type": "string", "description": "Titel des Canvas-Elements, leer = das zuletzt gezeigte"},
            "oeffnen": {"type": "boolean", "description": "Datei danach öffnen (Standard ja)"},
        },
        required=["format"],
    )


class OfficeDateien:
    def __init__(self, identity, memory, *, client: Callable[[], object], darf: Callable[[], bool],
                 senden: Callable[[dict], Awaitable[None]] | None):
        if not getattr(identity, "is_admin", False) or labor.ist_labor(identity):
            raise ValueError("Office-Dateien gibt es nur für Admins und nie im Labor")
        self.identity, self.memory = identity, memory
        self._client, self._darf, self._senden = client, darf, senden
        self.formate: tuple[str, ...] = ()

    # ---------- Fähigkeiten und Registrierung ----------
    async def schemas(self) -> list[FunctionSchema]:
        """Fragt den Host, welche Formate gehen, und liefert das Schema (oder nichts, wenn keins geht). Wirft nie."""
        self.formate = ()
        client = self._client()
        if client is None:
            return []
        try:
            antwort = json.loads(await asyncio.wait_for(call_host_tool(client, "office_faehigkeiten", {}), FAEHIGKEITEN_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001 (älterer Host ohne Werkzeug, Tunnel weg: ohne Office-Dateien weiter)
            logger.info("Office-Dateien: Host meldet keine Fähigkeiten ({})", type(e).__name__)
            return []
        if not isinstance(antwort, dict) or antwort.get("status") != "success" or not isinstance(antwort.get("formate"), list):
            return []
        self.formate = tuple(f for f in FORMATE if f in antwort["formate"])
        logger.info("Office-Dateien: {}", ", ".join(self.formate) or "keine Formate")
        return [schema(self.formate)] if self.formate else []

    def register(self, llm) -> None:
        llm.register_function(WERKZEUG, self._werkzeug, timeout_secs=ERSTELLEN_TIMEOUT_SECS + 5)

    def anzeige(self) -> list[str]:
        """Formate für die Oberfläche (Feld office in betrieb): nur, solange die PC-Steuerung an ist."""
        return list(self.formate) if self.formate and self._darf() else []

    # ---------- Werkzeug ----------
    async def _werkzeug(self, params) -> None:
        a = params.arguments if isinstance(params.arguments, dict) else {}
        titel = a.get("canvas") if isinstance(a.get("canvas"), str) and a.get("canvas").strip() else None
        ergebnis = await self.exportieren(a.get("format"), titel=titel, oeffnen=a.get("oeffnen") is not False, quelle="sprache")
        if ergebnis.get("status") == "success":
            datei = ergebnis.get("datei") or {}
            await params.result_callback({"status": "success", "gespeichert": True, "datei": datei.get("name", ""),
                                          "geoeffnet": bool(ergebnis.get("geoeffnet")), "ordner": datei.get("ordner", "")})
            return
        await params.result_callback({"status": ergebnis.get("status", "error"), "summary": ergebnis.get("summary", "")})

    async def exportieren(self, fmt: object, *, canvas_id: object = None, titel: str | None = None, oeffnen: bool = True,
                          quelle: str) -> dict:
        """Gemeinsamer Weg für Sprache und Klick. Liefert das Ergebnis des Hosts oder eine Ablehnung des Kerns."""
        if not self._darf():
            return {"status": "rejected", "summary": PC_AUS}
        client = self._client()
        if client is None:
            return {"status": "error", "summary": "Kein Zugriff auf den PC."}
        if not isinstance(fmt, str) or fmt not in self.formate:
            verfuegbar = ", ".join(FORMAT_NAMEN[f] for f in self.formate) or "keins"
            return {"status": "rejected", "summary": f"Dieses Format geht an diesem PC nicht (möglich: {verfuegbar})."}
        gefunden = await canvas_lesen(self.memory, canvas_id=canvas_id, titel=titel) if canvas_id is not None or titel else \
            await canvas_lesen(self.memory)
        if gefunden is None:
            return {"status": "rejected", "summary": KEIN_CANVAS}
        inhalt = gefunden["inhalt"]
        if fmt not in FORMATE_JE_ART[inhalt["art"]]:
            return {"status": "rejected", "summary": "Als Excel oder CSV geht nur eine Tabelle." if fmt in ("excel", "csv")
                    else f"{FORMAT_NAMEN[fmt]} passt nicht zu diesem Inhalt."}
        argumente = {"format": fmt, "inhalt": inhalt, "oeffnen": bool(oeffnen), "canvas_id": gefunden["id"]}
        try:
            roh = await asyncio.wait_for(call_host_tool(client, "office_datei_erstellen", argumente), ERSTELLEN_TIMEOUT_SECS)
            ergebnis = json.loads(roh)
        except Exception as e:  # noqa: BLE001 (Tunnel weg, Zeitgrenze, kaputte Antwort)
            logger.warning("Office-Datei: Host antwortet nicht verwertbar ({})", type(e).__name__)
            ergebnis = {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        if not isinstance(ergebnis, dict):
            ergebnis = {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        ergebnis = self._bereinigen(ergebnis)
        await self._protokoll(fmt, gefunden["id"], quelle, ergebnis)
        if ergebnis["status"] == "success":
            await self._melden({"type": "datei", "ok": True, **ergebnis["datei"], "geoeffnet": ergebnis["geoeffnet"]})
        return ergebnis

    @staticmethod
    def _bereinigen(ergebnis: dict) -> dict:
        """Nur bekannte Felder vom Host, gekürzt und ohne unsichtbare Zeichen (die Antwort sind Daten)."""
        status = ergebnis.get("status") if ergebnis.get("status") in ("success", "rejected", "blocked", "locked", "error") else "error"
        summary = clean_inline(ergebnis.get("summary", ""), 300)
        datei = ergebnis.get("datei") if isinstance(ergebnis.get("datei"), dict) else {}
        if status == "success" and not (isinstance(datei.get("kennung"), str) and KENNUNG_RE.fullmatch(datei["kennung"])):
            return {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        if status != "success":
            return {"status": status, "summary": summary}
        sauber = {"kennung": datei["kennung"], "name": clean_inline(datei.get("name", ""), 200),
                  "format": datei.get("format") if datei.get("format") in FORMATE else "",
                  "ordner": clean_inline(datei.get("ordner", ""), 80), "pfad": clean_inline(datei.get("pfad", ""), 400),
                  "groesse": datei.get("groesse") if isinstance(datei.get("groesse"), int) else 0,
                  "sha256": datei.get("sha256") if isinstance(datei.get("sha256"), str) else ""}
        return {"status": "success", "summary": summary, "geoeffnet": ergebnis.get("geoeffnet") is True, "datei": sauber}

    # ---------- Klicks aus der Oberfläche ----------
    async def client_nachricht(self, typ: str, daten: object) -> None:
        d = daten if isinstance(daten, dict) else {}
        if typ == "canvas_export":
            kennung = kennung_gueltig(d.get("canvas_id"))
            if kennung is None or d.get("format") not in FORMATE:
                await self._melden({"type": "datei", "ok": False, "grund": "Ungültige Anfrage."})
                return
            ergebnis = await self.exportieren(d["format"], canvas_id=kennung, quelle="klick")
            if ergebnis["status"] != "success":
                await self._melden({"type": "datei", "ok": False, "grund": ergebnis.get("summary") or "Nicht gespeichert."})
        elif typ == "datei_oeffnen":
            await self._oeffnen(d.get("kennung"))

    async def _oeffnen(self, kennung: object) -> None:
        if not isinstance(kennung, str) or not KENNUNG_RE.fullmatch(kennung):
            await self._melden({"type": "datei", "ok": False, "grund": "Unbekannte Datei."})
            return
        client = self._client()
        if not self._darf() or client is None:
            await self._melden({"type": "datei", "ok": False, "grund": PC_AUS})
            return
        try:
            ergebnis = json.loads(await asyncio.wait_for(call_host_tool(client, "office_datei_oeffnen", {"kennung": kennung}),
                                                         OEFFNEN_TIMEOUT_SECS))
        except Exception as e:  # noqa: BLE001
            logger.warning("Office-Datei öffnen: Host antwortet nicht verwertbar ({})", type(e).__name__)
            ergebnis = {"status": "error", "summary": "Der PC hat keine verwertbare Antwort geliefert."}
        if not isinstance(ergebnis, dict) or ergebnis.get("status") != "success":
            grund = clean_inline(ergebnis.get("summary", "") if isinstance(ergebnis, dict) else "", 300) or "Nicht geöffnet."
            await self._melden({"type": "datei", "ok": False, "grund": grund})

    # ---------- Ausgaben ----------
    async def _melden(self, nachricht: dict) -> None:
        if self._senden is not None:
            try:
                await self._senden(nachricht)
            except Exception as e:  # noqa: BLE001 (Oberfläche weg: das Gespräch läuft weiter)
                logger.debug("Office-Datei: Meldung an die Oberfläche fehlgeschlagen ({})", type(e).__name__)

    async def _protokoll(self, fmt: str, canvas_id: str, quelle: str, ergebnis: dict) -> None:
        """Abgeschlossener Aufruf in actions (done oder failed), ohne Inhalte."""
        if not getattr(self.memory, "enabled", False):
            return
        datei = ergebnis.get("datei") or {}
        params = {"format": fmt, "canvas_id": canvas_id, "quelle": quelle}
        resultat = {"status": ergebnis["status"], "datei": datei.get("name", ""), "groesse": datei.get("groesse", 0),
                    "sha256": str(datei.get("sha256", ""))[:16]}
        db = self.memory.db
        try:
            await db.execute(
                f"insert into {db.t('actions')} (user_id, session_id, tool, params, reason, risk, status, result, decided_at, "
                f"finished_at) values ($1::uuid, $2::uuid, $3, $4::text::jsonb, $5, $6::text::{db.t('risk_class')}, "
                f"$7::text::{db.t('action_status')}, $8::text::jsonb, now(), now())",
                self.memory.user_id, self.memory.session_id, WERKZEUG, json.dumps(params), "Office-Datei", "change",
                "done" if ergebnis["status"] == "success" else "failed", json.dumps(resultat, ensure_ascii=False))
        except DB_ERRORS as e:
            logger.warning("Office-Datei: Protokoll nicht geschrieben ({})", type(e).__name__)
