"""Freigabekarte für Jira-Stories im Kern (Job "jira"), nach dem geprüften Muster der Labor-Freigaben (labor_freigaben.py).

Ablauf
  1. jira_werkzeuge.py prüft die Angaben im Code, liest Projekt, Typ, Recht und Epic aus Jira und ruft anfrage(story). anfrage() baut die
     Karte, legt den Antrag an und schickt {"type": "freigaben", "job": "jira"} an die Oberfläche. Das Modell bekommt nur "wartet auf den
     Klick", nie die Kennung der Karte.
  2. Der Klick kommt als {"type": "freigabe", "data": {"job": "jira", "id", "entscheidung"}} über die angemeldete Verbindung (bot.py).
  3. entscheiden() nimmt den Antrag vor dem ersten await aus dem Speicher (genau einmal) und prüft Frist, Sitzung, Profil, Hash und genau "ja".
     Ausgeführt werden allein die gespeicherten Werte, nie Felder aus der Nachricht. Jeder Schritt steht in actions (pending, approved,
     running, done oder failed, oder rejected), ohne Texte: nur Projekt, Epic, Anzahl der Kriterien, Längen, Canvas-Kennung, Schlüssel.

Die Karte zeigt alles, was angelegt wird, oder es gibt keine Karte: Die Oberfläche kürzt ein Feld bei 2000 UTF-16-Einheiten, deshalb gilt für
alle Texte der Karte zusammen KARTE_MAX (1800, wie die Karten des Hosts), gemessen in UTF-16-Einheiten. Jede Zeile der Beschreibung und jedes
Kriterium steht mit dem Präfix "> " auf der Karte: So kann kein eingeschleuster Text eine Zeile wie "Projekt: ..." vortäuschen. Jira bekommt
genau diese Texte (jira_client.story_felder), Markdown-Zeichen werden dort zu Formaten.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from persona import clean_inline

JOB = "jira"
WERKZEUG = "jira_story_anlegen"
ID_RE = re.compile(r"[0-9a-f]{32}")  # 128 Bit
KARTE_MAX = 1800
FRIST_SECS = 300
MAX_OFFEN = 5
MAX_JE_STUNDE = 20
AUSFUEHREN_TIMEOUT_SECS = 60.0  # Anlegen und nach einer unklaren Antwort eine Suche (beide POST, je höchstens 20 Sekunden)
SCHLIESSEN_TIMEOUT_SECS = 3.0
TEXT_PREFIX = "> "
WARNUNG = ("Achtung: Im selben Gespräch kamen Inhalte von außen (Web, Mail, Bildschirm, Gerät). Prüfe Titel, Beschreibung und Kriterien "
           "besonders genau.")


@dataclass(frozen=True)
class Story:
    """Was angelegt wird, schon geprüft und normiert (jira_werkzeuge.py). epic leer heißt ohne Epic, canvas_id leer heißt ohne Canvas."""

    projekt: str
    projekt_name: str
    typ_id: str
    epic: str
    epic_titel: str
    titel: str
    beschreibung: str
    kriterien: tuple[str, ...]
    canvas_id: str
    quelle: str  # sprache | klick


@dataclass(frozen=True)
class Antrag:
    id: str
    story: Story
    warnung: bool
    sitzung: str
    profil: str
    hash: str
    erstellt: float
    gueltig: float


@dataclass(frozen=True)
class Angebot:
    """Ergebnis von anfrage(): die gesendete Karte oder ein fester Satz, warum es keine gibt."""

    karte: dict | None = None
    grund: str | None = None


@dataclass(frozen=True)
class Ausgang:
    """Ergebnis des Anlegens: fester Satz, ok, geprüfter Schlüssel und Verweis (nur bei ok), Fehlercode."""

    ok: bool
    satz: str
    schluessel: str | None = None
    link: str | None = None
    code: str | None = None


def utf16_len(text: str) -> int:
    """Länge in UTF-16-Einheiten wie JavaScript length: so kürzt die Oberfläche (ui/src/lib/nachrichten.ts)."""
    return len(text.encode("utf-16-le")) // 2


def karten_texte(story: Story, *, warnung: bool) -> tuple[str, str, str]:
    """(grund, ziel, detail): feste Zeilen für Typ, Epic und Titel, Freitext Zeile für Zeile mit Präfix, Kriterien nummeriert."""
    zeilen = [WARNUNG] if warnung else []
    zeilen.append("Typ: Story")
    zeilen.append(f"Epic: {story.epic} ({story.epic_titel})" if story.epic else "Epic: keins")
    zeilen.append(f"Titel: {story.titel}")
    if story.beschreibung:
        zeilen.append("Beschreibung:")
        zeilen.extend(TEXT_PREFIX + z for z in story.beschreibung.split("\n"))
    else:
        zeilen.append("Beschreibung: (leer)")
    if story.kriterien:
        zeilen.append("Akzeptanzkriterien:")
        zeilen.extend(f"{TEXT_PREFIX}{i}. {k}" for i, k in enumerate(story.kriterien, 1))
    else:
        zeilen.append("Akzeptanzkriterien: (keine)")
    return "Jira-Story anlegen", f"Jira, Projekt {story.projekt} ({story.projekt_name})", "\n".join(zeilen)


def antrag_hash(*, sitzung: str, profil: str, story: Story, warnung: bool) -> str:
    """SHA-256 über alles, woran ein Antrag gebunden ist (kanonisches JSON, kein Trennzeichen kann etwas verschieben)."""
    roh = json.dumps(["wamo-jira-antrag-1", sitzung, profil, story.projekt, story.projekt_name, story.typ_id, story.epic, story.epic_titel,
                      story.titel, story.beschreibung, list(story.kriterien), story.canvas_id, story.quelle, warnung],
                     ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


class StundenZaehler:
    """Anträge je Profil in der letzten Stunde, prozessweit (eine neue Verbindung setzt nichts zurück). Begrenzt im Speicher."""

    def __init__(self, hoechstens_profile: int = 256):
        self._hoechstens = hoechstens_profile
        self._z: OrderedDict[str, deque[float]] = OrderedDict()

    def stand(self, profil: str, jetzt: float) -> int:
        zeiten = self._z.get(profil)
        if zeiten is None:
            return 0
        while zeiten and jetzt - zeiten[0] > 3600:
            zeiten.popleft()
        return len(zeiten)

    def zaehle(self, profil: str, jetzt: float) -> None:
        self._z.setdefault(profil, deque()).append(jetzt)
        self._z.move_to_end(profil)
        while len(self._z) > self._hoechstens:
            self._z.popitem(last=False)


_ZAEHLER = StundenZaehler()


def _ohne_klammern(text: str) -> str:
    """Text für das Modell darf die Klammer der Meldung nicht schließen und keine eigene öffnen."""
    return text.replace("[", "(").replace("]", ")")


class JiraFreigaben:
    """Offene Jira-Karten einer Sitzung.

    memory: log_action, update_action, aktion_abschliessen (Tabelle actions); sitzung und profil binden den Antrag; von: Anzeigename;
    ausfuehren(story) -> Ausgang legt die gespeicherte Story an (jira_werkzeuge.py); melden(text): Nachricht an das Sprachmodell;
    senden(nachricht): an die Oberfläche; uhr: Zeit in Sekunden; zaehler: Anträge je Profil und Stunde.
    """

    def __init__(self, memory, *, sitzung: str, profil: str, von: str, ausfuehren: Callable[[Story], Awaitable[Ausgang]],
                 melden: Callable[[str], Awaitable[None]], senden: Callable[[dict], Awaitable[None]],
                 uhr: Callable[[], float] = time.monotonic, zaehler: StundenZaehler | None = None, frist_secs: int = FRIST_SECS,
                 max_offen: int = MAX_OFFEN, max_je_stunde: int = MAX_JE_STUNDE):
        self._memory = memory
        self._sitzung, self._profil = sitzung, profil
        self._von = _ohne_klammern(clean_inline(von, 60)) or "W.A.I.S."
        self._ausfuehren, self._melden, self._senden = ausfuehren, melden, senden
        self._uhr = uhr
        self._zaehler = zaehler if zaehler is not None else _ZAEHLER
        self.frist_secs, self.max_offen, self.max_je_stunde = frist_secs, max_offen, max_je_stunde
        self._offen: dict[str, Antrag] = {}
        self._protokoll: dict[str, asyncio.Future] = {}
        self._entschieden: deque[str] = deque(maxlen=100)
        self._hintergrund: set[asyncio.Future] = set()
        self._beendet = False

    @property
    def offen(self) -> bool:
        """Wartet eine Karte? (für den Ja-Wächter in bot.py)"""
        return bool(self._offen)

    @property
    def offen_anzahl(self) -> int:
        return len(self._offen)

    def platz_frei(self) -> str | None:
        """Vorprüfung vor den Lesezugriffen auf Jira: None oder der Satz, warum es gerade keine Karte geben kann."""
        self._aufraeumen()
        if self._beendet:
            return "Die Sitzung endet, es gibt keine neuen Karten."
        if len(self._offen) >= self.max_offen:
            return "Es warten schon zu viele Freigaben. Erst darüber entscheiden."
        if self._zaehler.stand(self._profil, self._uhr()) >= self.max_je_stunde:
            return f"In der letzten Stunde gab es schon {self.max_je_stunde} Stories. Später noch einmal."
        return None

    # ---------- 1. Antrag ----------
    async def anfrage(self, story: Story, *, warnung: bool = False) -> Angebot:
        """Neuer Antrag. Alles bis zum Eintrag in _offen geschieht ohne await: gleichzeitige Aufrufe überschreiten keine Grenze."""
        grund_voll = self.platz_frei()
        if grund_voll is not None:
            return Angebot(grund=grund_voll)
        grund, ziel, detail = karten_texte(story, warnung=warnung)
        if sum(utf16_len(t) for t in (grund, ziel, detail, self._von)) > KARTE_MAX:
            return Angebot(grund=f"Die Story ist zu lang für die Freigabekarte (höchstens {KARTE_MAX} Zeichen). Beschreibung oder "
                                 "Kriterien kürzen.")
        jetzt = self._uhr()
        self._zaehler.zaehle(self._profil, jetzt)
        aid = secrets.token_hex(16)
        antrag = Antrag(id=aid, story=story, warnung=warnung, sitzung=self._sitzung, profil=self._profil, erstellt=jetzt,
                        gueltig=float(self.frist_secs),
                        hash=antrag_hash(sitzung=self._sitzung, profil=self._profil, story=story, warnung=warnung))
        self._offen[aid] = antrag
        self._protokoll[aid] = self._protokollieren(antrag)
        logger.info("Jira-Freigabe {} angefragt (Projekt {})", aid[:8], story.projekt)
        karte = {"type": "freigaben", "job": JOB, "projekt": "", "items": [{
            "id": aid, "grund": grund, "detail": detail, "von": self._von, "ziel": ziel, "gueltig_s": self.frist_secs}]}
        try:
            await self._senden(karte)
        except Exception as e:  # noqa: BLE001 (ohne sichtbare Karte darf nichts offen bleiben)
            logger.warning("Jira-Freigabe: Karte nicht gesendet ({})", type(e).__name__)
            self._offen.pop(aid, None)
            self._hinten(self._abschliessen(antrag, "rejected"))
            return Angebot(grund="Die Freigabekarte konnte nicht angezeigt werden.")
        return Angebot(karte=karte)

    def _protokollieren(self, antrag: Antrag) -> asyncio.Future:
        """Zeile in actions (pending), ohne Texte."""
        s = antrag.story
        params = {"approval_id": antrag.id, "projekt": s.projekt, "epic": s.epic, "kriterien": len(s.kriterien),
                  "titel_zeichen": len(s.titel), "beschreibung_zeichen": len(s.beschreibung), "canvas_id": s.canvas_id,
                  "quelle": s.quelle, "warnung": antrag.warnung}
        return self._hinten(self._memory.log_action(tool=WERKZEUG, params=params, reason="Jira-Story anlegen", risk="critical"))

    def _hinten(self, aufgabe: Awaitable) -> asyncio.Future:
        future = asyncio.ensure_future(aufgabe)
        self._hintergrund.add(future)
        future.add_done_callback(self._hintergrund.discard)
        return future

    def _abgelaufen(self, antrag: Antrag) -> bool:
        return self._uhr() - antrag.erstellt > antrag.gueltig

    def _aufraeumen(self) -> None:
        for aid in [k for k, a in self._offen.items() if self._abgelaufen(a)]:
            self._entschieden.append(aid)
            self._hinten(self._abschliessen(self._offen.pop(aid), "rejected"))

    async def _abschliessen(self, antrag: Antrag, status: str) -> None:
        await self._status(await self._action_id(antrag), status)

    # ---------- 2. und 3. Klick ----------
    async def entscheiden(self, data: object) -> Ausgang | None:
        """Entscheidung aus der Oberfläche. Liefert den Ausgang, wenn angelegt wurde (oder es versucht wurde), sonst None."""
        aid = data.get("id") if isinstance(data, dict) else None
        if not isinstance(aid, str) or not ID_RE.fullmatch(aid):
            logger.warning("Jira-Freigabe mit ungültiger Kennung abgewiesen")
            return None
        if aid in self._entschieden:
            logger.info("Jira-Freigabe {}: schon entschieden (zweiter Klick)", aid[:8])
            return None
        antrag = self._offen.pop(aid, None)  # genau einmal, vor dem ersten await
        if antrag is None:
            # Nicht offen oder aus einer fremden Sitzung: nur loggen, ohne die Kennung, und nicht melden (jede Meldung ist ein Modellzug)
            logger.warning("Jira-Freigabe: Kennung ist nicht offen, nichts gemeldet")
            return None
        self._entschieden.append(aid)
        action_id = await self._action_id(antrag)
        if self._beendet or self._abgelaufen(antrag):
            await self._status(action_id, "rejected")
            await self._melden_kurz("Die Freigabe für die Jira-Story ist abgelaufen. Es wurde nichts angelegt.")
            return None
        erwartet = antrag_hash(sitzung=self._sitzung, profil=self._profil, story=antrag.story, warnung=antrag.warnung)
        if (antrag.sitzung, antrag.profil) != (self._sitzung, self._profil) or not secrets.compare_digest(erwartet, antrag.hash):
            logger.warning("Jira-Freigabe {}: Hash stimmt nicht", aid[:8])
            await self._status(action_id, "rejected")
            await self._melden_kurz("Die Freigabe passt nicht mehr zu den gespeicherten Werten. Es wurde nichts angelegt.")
            return None
        if (data or {}).get("entscheidung") != "ja":
            await self._status(action_id, "rejected")
            await self._melden_kurz(f"{self._von} hat das Anlegen der Jira-Story abgelehnt. Es wurde nichts angelegt.")
            return None
        await self._status(action_id, "approved")
        await self._status(action_id, "running")
        ausgang = await self._ausfuehren_sicher(antrag.story)
        ergebnis = {"schluessel": ausgang.schluessel} if ausgang.ok else {"code": ausgang.code or "fehler"}
        if action_id:
            await self._memory.aktion_abschliessen(action_id, "done" if ausgang.ok else "failed", ergebnis)
        logger.info("Jira-Freigabe {} ausgeführt: {}", aid[:8], ausgang.schluessel if ausgang.ok else (ausgang.code or "fehler"))
        nachricht = {"type": "jira_ergebnis", "ok": ausgang.ok, "text": ausgang.satz}
        if ausgang.ok:
            nachricht = {"type": "jira_ergebnis", "ok": True, "schluessel": ausgang.schluessel, "link": ausgang.link, "text": ausgang.satz}
        with contextlib.suppress(Exception):
            await self._senden(nachricht)
        await self._melden(f"[Jira-Freigabe: {_ohne_klammern(ausgang.satz)} Sag {self._von} das in einem kurzen Satz.]")
        return ausgang

    async def _ausfuehren_sicher(self, story: Story) -> Ausgang:
        """Die gespeicherte Story anlegen. Eine Ausnahme wird ein fester Satz, nie Einzelheiten."""
        try:
            ausgang = await asyncio.wait_for(self._ausfuehren(story), AUSFUEHREN_TIMEOUT_SECS)
            if isinstance(ausgang, Ausgang):
                return ausgang
        except TimeoutError:
            return Ausgang(False, "Jira hat nicht rechtzeitig geantwortet. Bitte in Jira nachsehen, bevor du es noch einmal versuchst.",
                           code="unklar")
        except Exception as e:  # noqa: BLE001
            logger.warning("Jira-Freigabe: Anlegen fehlgeschlagen ({})", type(e).__name__)
        return Ausgang(False, "Das Anlegen in Jira ist fehlgeschlagen. Bitte in Jira nachsehen, bevor du es noch einmal versuchst.",
                       code="fehler")

    # ---------- Ende ----------
    async def schliessen(self) -> None:
        """Sitzungsende: alle offenen Anträge ablehnen (actions), jeden mit kurzer Frist. Danach wirkt kein Klick mehr."""
        self._beendet = True
        offene, self._offen = list(self._offen.values()), {}
        self._entschieden.extend(a.id for a in offene)

        async def ablehnen(antrag: Antrag) -> None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._abschliessen(antrag, "rejected"), SCHLIESSEN_TIMEOUT_SECS)

        await asyncio.gather(*(ablehnen(a) for a in offene))

    # ---------- Hilfen ----------
    async def _action_id(self, antrag: Antrag) -> str | None:
        future = self._protokoll.pop(antrag.id, None)
        if future is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(future), 5)
        except Exception as e:  # noqa: BLE001 (Datenbank langsam oder weg: die Entscheidung gilt trotzdem)
            logger.warning("Jira-Freigabe: Protokoll nicht verfügbar ({})", type(e).__name__)
            return None

    async def _status(self, action_id: str | None, status: str) -> None:
        if action_id:
            await self._memory.update_action(action_id, status)

    async def _melden_kurz(self, text: str) -> None:
        await self._melden(f"[Jira-Freigabe: {text} Sag das in einem kurzen Satz.]")
