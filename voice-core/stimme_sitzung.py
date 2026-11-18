"""Stimmabdruck einer Sitzung: Laden, Client-Nachrichten, Einwilligung, Löschen. Der Klebstoff zwischen bot.py und den Teilen der Stimmprüfung.

Eine StimmSitzung gehört genau einer Sitzung, also einem Profil: eigenes Gate (Abdruck, Prüfzustand), eigener Prüfer und Wächter in der Pipeline.
Der Rechner (stimme_modell.MODELL) ist je Prozess einmal da und wird von allen Sitzungen geteilt; einen Abdruck-Zwischenspeicher über Profile hinweg
gibt es nicht. Laborprofile (labor.py) bekommen nie eine StimmSitzung (fuer gibt None), die Client-Nachricht stimmabdruck ist für sie zusätzlich
von der Laborsperre abgewiesen (labor_rtvi.py, labor.client_nachricht_erlaubt).

Ablauf in bot.py: fuer (beim Aufbau der Sitzung) -> werkzeuge_absichern und tippen_beobachten (stimme_gate.py) -> pruefer vor die Spracherkennung,
waechter vor den Aggregator des Nutzers -> laden_bis_bekannt (im Hintergrund nach dem Verbinden: vorbereiten, bei unbekanntem Stand mit
wachsender Pause erneut) -> client_bereit (Status und Einwilligung an die Oberfläche) -> nachricht (Client-Nachricht stimmabdruck) ->
nicht_sicher_eigen (in on_user_turn_stopped; einen vom Wächter verworfenen, also leeren Zug übergeht bot.py schon vorher).

Nachricht der Oberfläche: {"aktion": "start", "einwilligung": "stimme-1"} | {"aktion": "abbrechen"} | {"aktion": "loeschen"}. Start nur mit genau der
aktuellen Version der Einwilligung (stimme_einwilligung.py), nur auf Klick, nie per Sprache. Löschen entfernt den Abdruck vollständig (DSGVO
Art. 17); ein laufendes Einlernen wird vorher beendet, damit danach nichts mehr gespeichert wird. Löschen, Ersetzen und das neue Einlernen
nach einem Löschen in derselben Sitzung brauchen (außer im Modus aus, dort geht Löschen immer) einen Nachweis: die Person ist gerade sicher
an der Stimme erkannt oder die Anmeldung mit zweitem Faktor ist jünger als 10 Minuten (nachweis_ok). Sonst meldet die Sitzung einen Fehler
und nennt die neue Anmeldung. Ohne Abdruck (nie einer da gewesen) braucht es keinen Nachweis.
Ohne Datenbank oder im Modus aus ist die Stimmprüfung aus (Status aus); ohne Abdruck wird nie geprüft oder gesperrt.

Schattenbetrieb (stimme_schatten.py): Mit WAMO_STIMME_SCHATTEN=an bekommt die Sitzung das Schattenmodell des Prozesses (schatten), liest beim
Laden den Schatten-Abdruck mit (nur mit Abdruck und Einwilligung stimme-2) und wärmt das Modell im Hintergrund vor. Gezeigt und verlangt
wird dann die Einwilligung stimme-2 (zwei Abdrücke), ohne Schalter weiter stimme-1 (stimme_einwilligung.py). Laborprofile bekommen weiterhin keine Sitzung.

Ein Abdruck je Mikrofon (Wunsch vom 18.11.2026, Migration 0029, stimme_mikrofon.py): Die Sitzung lädt alle Abdrücke des Profils
(höchstens drei) und weiß danach, ob die Datenbank mehrere kann (mehrere). Dann zeigt und verlangt sie die Einwilligung stimme-3, mit und ohne
Schatten. Die Oberfläche schickt beim Start den Namen des Mikrofons, das im Gespräch läuft ({"aktion": "start", "einwilligung": "stimme-3",
"mikrofon": "<Name>"}); daraus werden Kennung und Name (stimme_mikrofon.mikrofon_aus), und das Einlernen ersetzt nur den Abdruck dieses
Mikrofons. Löschen mit {"aktion": "loeschen", "mikrofon": "<Kennung>"} entfernt nur einen Abdruck, ohne mikrofon alle (der Widerruf). Nach
dem Laden, Einlernen und Löschen geht die Liste der eingelernten Mikrofone an die Oberfläche (StimmGate.mikrofone_nachricht). Ohne 0029
bleibt alles wie vorher: ein Abdruck, das unbekannte Mikrofon, stimme-1 oder stimme-2.

Mikrofontest (Wunsch vom 18.11.2026): Die Client-Nachricht {"type": "mikrofontest", "data": {"aktion": "start"}} unterbricht eine laufende
Antwort von W.A.I.S. (mikrofontest, Stimmpruefer.ausgabe_unterbrechen). Die Oberfläche schaltet die Wiedergabe für die Dauer des Tests stumm
und wertet den Test als ungültig, wenn W.A.I.S. trotzdem spricht. Laborsitzungen bekommen keine Stimmsitzung, die Nachricht wirkt dort nicht.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import numpy as np
from loguru import logger

import labor
from memory import MemoryStore
from stimme_einwilligung import einwilligung_gilt, einwilligung_nachricht
from stimme_gate import StimmGate, stand_nachricht
from stimme_mikrofon import MAX_ABDRUECKE, UNBEKANNTES_MIKROFON, Mikrofon, kennung_gueltig, mikrofon_aus
from stimme_modell import MODELL, ModellQuelle
from stimme_pruefer import Stimmpruefer
from stimme_schatten import SCHATTEN, SCHATTEN_DIM, SCHATTEN_MODELL, schatten_an, vorwaermen
from stimme_speicher import abdruck_loeschen, abdruck_speichern, abdruecke_laden, schatten_alle_laden, schwelle_speicherbar
from stimme_waechter import StimmWaechter

LADE_VERSUCHE = 3  # der Abdruck wird beim Start der Sitzung gelesen; ein kurzer Ausfall der Datenbank soll nicht gleich "kaputt" heißen
LADE_PAUSE_SECS = 0.5
NACHLADEN_SECS = (30.0, 60.0, 120.0, 300.0)  # Stand weiter unbekannt: Pausen vor jedem neuen Laden, danach bleibt es bei der letzten
EINWILLIGUNG_FEHLT = "Die Einwilligung fehlt oder gehört zu einem älteren Text. Bitte lies sie noch einmal und bestätige sie."
ABGESCHALTET = "Die Stimmerkennung ist abgeschaltet."
STAND_UNKLAR = "Ich kann gerade nicht lesen, ob schon ein Stimmabdruck gespeichert ist. Bitte versuch es gleich noch einmal."
NICHT_GELOESCHT = "Ich konnte den Stimmabdruck nicht löschen. Bitte versuch es später noch einmal."
MIKROFON_FEHLT = "Für dieses Mikrofon gibt es keinen Stimmabdruck mehr."
SCHATTEN_LADEN_SECS = 5.0  # so lange darf das Lesen des Schatten-Abdrucks dauern (stimme_schatten.py), danach misst die Sitzung ohne ihn
ANMELDUNG_FRISCH_SECS = 600.0  # so jung muss die Anmeldung mit zweitem Faktor sein, wenn die Stimme nicht als Nachweis dient
LOESCHEN_NACHWEIS = (
    "Zum Löschen deines Stimmabdrucks muss ich dich erst an der Stimme erkennen: Sag kurz etwas in einem ganzen Satz. "
    "Oder bitte neu anmelden, mit zweitem Faktor, dann geht es auch."
)
SPRECHER_UNSICHER = "stimme-unsicher"  # Markierung (Spalte speaker_label) im Gesprächsprotokoll: nicht sicher die Stimme des Profils


def nachricht_aus() -> dict:
    """Stand für die Oberfläche, wo es keine Stimmprüfung gibt (Laborprofile): die Bedienelemente bleiben weg."""
    return stand_nachricht("aus", "aus")


def jetzt_utc() -> datetime:
    return datetime.now(timezone.utc)


class StimmSitzung:
    def __init__(
        self,
        identity,
        memory: MemoryStore,
        gate: StimmGate,
        modell: ModellQuelle,
        *,
        senden: Callable[[dict], Awaitable[None]],
        sagen: Callable[[str], Awaitable[None]],
        uhr: Callable[[], float] | None = None,
        wanduhr: Callable[[], float] = time.time,
        schatten: ModellQuelle | None = None,
    ):
        self._identity = identity
        self.schatten = schatten  # Schattenmodell (stimme_schatten.py) oder None: nur messen, nie entscheiden
        self._wanduhr = wanduhr  # Unix-Zeit wie der Zeitstempel der Anmeldung im Token (Identity.anmeldung)
        self._memory = memory
        self._modell = modell
        self._senden = senden
        self.gate = gate
        # Kann die Datenbank einen Abdruck je Mikrofon speichern (Migration 0029)? None, bis das erste Laden es zeigt
        self.mehrere: bool | None = None
        self._client_bereit = False  # die Oberfläche ist verbunden (client_bereit): eine geänderte Einwilligung geht dann gleich hinaus
        self._einwilligung_gesendet: str | None = None
        if not memory.enabled and gate.modus != "aus":
            logger.info("Stimmprüfung aus: keine Datenbank für das Profil")
            gate.modus = "aus"  # ohne Datenbank gibt es keinen Abdruck, nichts zu prüfen und nichts einzulernen
        kwargs = {"uhr": uhr} if uhr is not None else {}
        self.pruefer = Stimmpruefer(gate, modell, speichern=self._speichern, sagen=sagen, nachweis=self.nachweis_ok, schatten=schatten,
                                    **kwargs)
        self.waechter = StimmWaechter(gate, self.pruefer)

    @classmethod
    def fuer(
        cls,
        identity,
        memory: MemoryStore,
        *,
        senden: Callable[[dict], Awaitable[None]],
        sagen: Callable[[str], Awaitable[None]],
        modell: ModellQuelle = MODELL,
        gate: StimmGate | None = None,
        uhr: Callable[[], float] | None = None,
        schatten: ModellQuelle | None = None,
    ) -> StimmSitzung | None:
        """Die Stimmsitzung dieser Identität, oder None für ein Laborprofil: dort gibt es nie Stimmprüfung und nie Einlernen. schatten: das
        Schattenmodell; ohne Angabe das des Prozesses, wenn WAMO_STIMME_SCHATTEN an ist, sonst keins."""
        if labor.ist_labor(identity):
            return None
        if schatten is None and schatten_an():
            schatten = SCHATTEN
        return cls(identity, memory, gate or StimmGate.aus_umgebung(), modell, senden=senden, sagen=sagen, uhr=uhr, schatten=schatten)

    # ---------- Laden und Stand ----------

    async def vorbereiten(self) -> None:
        """Abdruck des Profils lesen und, wenn es einen gibt, das Modell laden. Läuft im Hintergrund, das Gespräch wartet nicht. Wirft nie."""
        try:
            if self.gate.modus != "aus":
                await self._laden()
        except Exception as e:  # unbekannter Stand heißt kaputt: streng sperrt dann Werkzeuge, getippter Text geht
            logger.warning("Stimmprüfung: Vorbereitung gescheitert ({})", type(e).__name__)
            if self.gate.zustand in ("laedt", "kaputt"):
                self.gate.setze_abdruck(None, ok=False)
        logger.info("Stimmprüfung: {} ({})", self.gate.status, self.gate.modus)
        await self.status_melden()

    async def laden_bis_bekannt(self) -> None:
        """vorbereiten, und ist der Stand danach unbekannt (kaputt: die Datenbank war nicht lesbar), mit wachsender Pause neu laden, bis er
        bekannt ist. Sonst sperrte der Modus streng Werkzeuge per Sprache bis zum Ende der Sitzung, auch für ein Profil ohne Abdruck. Läuft in
        bot.py als Hintergrundaufgabe, die beim Aufräumen abgebrochen wird. Wirft nie."""
        await self.vorbereiten()
        versuch = 0
        while self.gate.zustand == "kaputt" and self.gate.modus != "aus":
            await asyncio.sleep(NACHLADEN_SECS[min(versuch, len(NACHLADEN_SECS) - 1)])
            versuch += 1
            if self.gate.zustand != "kaputt":
                break  # in der Pause gelöscht: der Stand ist bekannt
            logger.info("Stimmprüfung: Stand des Abdrucks unbekannt, neuer Versuch ({})", versuch)
            await self.vorbereiten()

    async def _laden(self) -> None:
        vorher = self.gate.zustand  # laedt oder kaputt
        ok, abdruecke, mehrere = False, [], None
        for versuch in range(LADE_VERSUCHE):
            ok, abdruecke, mehrere = await abdruecke_laden(self._memory)
            if ok:
                break
            if versuch + 1 < LADE_VERSUCHE:
                await asyncio.sleep(LADE_PAUSE_SECS * (versuch + 1))
        if self.gate.zustand != vorher:
            return  # während des Lesens gelöscht: das Gelesene ist veraltet
        if mehrere is not None:
            self.mehrere = mehrere
        self.gate.max_abdruecke = MAX_ABDRUECKE if self.mehrere else 1
        self.gate.schwelle_erlaubt = schwelle_speicherbar()
        self.gate.setze_abdruecke(abdruecke, ok)
        if self.schatten is not None and self.gate.abdruecke:
            await self._schatten_laden()
        for nr, a in enumerate(self.gate.abdruecke, start=1):
            logger.info("Stimmprüfung: Abdruck {} von {}, Schwelle für kurze Äußerungen {:.2f} ({})", nr, len(self.gate.abdruecke),
                        self.gate.schwelle_fuer(0.0, a), "persönlich" if a.schwelle is not None else "Umgebung")
        if self.gate.abdruecke:
            self.gate.modell_ok = await self._modell.get() is not None

    async def _schatten_laden(self) -> None:
        """Erst nach den Abdrücken von TitaNet (die Prüfung wartet nie darauf): Schatten-Abdrücke je Mikrofon lesen, höchstens
        SCHATTEN_LADEN_SECS, und nur setzen, wenn die Abdrücke inzwischen dieselben sind. Das Schattenmodell lädt im Hintergrund vor."""
        vorwaermen(self.schatten)
        stand = self.gate.abdruecke
        try:
            schatten = await asyncio.wait_for(
                schatten_alle_laden(self._memory, SCHATTEN_MODELL, SCHATTEN_DIM, mehrere=bool(self.mehrere)), SCHATTEN_LADEN_SECS)
        except asyncio.TimeoutError:
            logger.info("Stimmschatten: Abdruck nicht rechtzeitig gelesen, diese Sitzung misst ohne Schatten")
            return
        if self.gate.abdruecke is stand and schatten:
            self.gate.schatten_setzen(schatten)

    async def status_melden(self) -> None:
        """Stand der Stimmprüfung, dazu (mit bekanntem Stand) die eingelernten Mikrofone. Nach dem ersten Laden auch eine Einwilligung, deren
        Fassung sich geändert hat (die Datenbank kann einen Abdruck je Mikrofon: stimme-3)."""
        await self._senden(self.gate.stand())
        await self._mikrofone_melden()
        if self._client_bereit and self.gate.modus != "aus" and self._einwilligung_gesendet != self._einwilligung()["version"]:
            await self._einwilligung_senden()

    async def _mikrofone_melden(self) -> None:
        if self.gate.modus != "aus" and self.gate.zustand in ("da", "fehlt"):
            await self._senden(self.gate.mikrofone_nachricht())

    def _einwilligung(self) -> dict:
        return einwilligung_nachricht(schatten=self.schatten is not None, mikrofone=bool(self.mehrere))

    async def _einwilligung_senden(self) -> None:
        nachricht = self._einwilligung()
        self._einwilligung_gesendet = nachricht["version"]
        await self._senden(nachricht)

    async def client_bereit(self) -> None:
        """Die Oberfläche ist verbunden: Stand der Stimmprüfung, der Text der Einwilligung und die eingelernten Mikrofone."""
        self._client_bereit = True
        await self._senden(self.gate.stand())
        if self.gate.modus != "aus":
            await self._einwilligung_senden()
            await self._mikrofone_melden()

    def anmeldung_frisch(self) -> bool:
        """Ist die Anmeldung mit zweitem Faktor jünger als ANMELDUNG_FRISCH_SECS? Der Zeitpunkt kommt aus dem Token (auth_gate.anmeldezeit,
        frühester Eintrag in amr, also Passwort und Code zusammen). Ohne Zeitpunkt gilt sie nicht als frisch."""
        anmeldung = getattr(self._identity, "anmeldung", None)
        return anmeldung is not None and 0 <= self._wanduhr() - anmeldung <= ANMELDUNG_FRISCH_SECS

    def nachweis_ok(self) -> bool:
        """Darf die Person ihren Abdruck ersetzen oder löschen? Wenn sie gerade sicher an der Stimme erkannt ist oder frisch angemeldet."""
        return self.gate.stimme_vertraut() or self.anmeldung_frisch()

    def nicht_sicher_eigen(self) -> bool:
        """Der Zug stammt nicht sicher von der Person (stimme_gate.StimmGate.nicht_sicher_eigen): bot.py färbt ihn wie Fremdinhalte."""
        return self.gate.nicht_sicher_eigen()

    # ---------- Client-Nachricht stimmabdruck ----------

    async def nachricht(self, daten: object) -> None:
        if not isinstance(daten, dict):
            return
        aktion = daten.get("aktion")
        if aktion == "start":
            await self._start(daten.get("einwilligung"), daten.get("mikrofon"))
        elif aktion == "abbrechen":
            await self.pruefer.einlernen_abbrechen()
        elif aktion == "loeschen":
            await self._loeschen(daten.get("mikrofon"))
        else:
            logger.warning("Stimmabdruck: unbekannte Aktion {!r}", str(aktion)[:40])

    async def _fehler(self, text: str) -> None:
        await self._senden({"type": "stimmabdruck", "status": "fehler", "text": text})

    async def _start(self, einwilligung: object, mikrofon: object = None) -> None:
        # mit Abdrücken je Mikrofon nur stimme-3, sonst im Schattenbetrieb nur stimme-2 und ohne ihn stimme-1
        if self.gate.modus == "aus":
            await self._fehler(ABGESCHALTET)
        elif not einwilligung_gilt(einwilligung, schatten=self.schatten is not None, mikrofone=bool(self.mehrere)):
            await self._fehler(EINWILLIGUNG_FEHLT)
        elif self.gate.zustand in ("laedt", "kaputt"):
            await self._fehler(STAND_UNKLAR)  # nicht blind einen vielleicht vorhandenen Abdruck ersetzen
        else:
            # ohne Migration 0029 gibt es nur einen Abdruck: das unbekannte Mikrofon, er wird ersetzt wie bisher
            geraet = mikrofon_aus(mikrofon) if self.mehrere else UNBEKANNTES_MIKROFON
            await self.pruefer.einlernen_starten(einwilligung, jetzt_utc(), geraet)

    async def _speichern(self, abdruck: np.ndarray, version: str, einwilligung_am: datetime, *, schwelle: float | None = None,
                         schatten: np.ndarray | None = None, mikrofon: Mikrofon = UNBEKANNTES_MIKROFON) -> bool:
        gespeichert = await abdruck_speichern(
            self._memory, abdruck, version=version, name=getattr(self._identity, "name", ""), einwilligung_am=einwilligung_am,
            schwelle=schwelle, schatten=schatten, schatten_modell=SCHATTEN_MODELL if schatten is not None else None,
            mikrofon=mikrofon if self.mehrere else None,
        )
        # Ohne Spalte für die Schwelle (Migration 0025) wirkt sie auch in dieser Sitzung nicht: das Einlernen setzt sie danach im Gate
        self.gate.schwelle_erlaubt = schwelle_speicherbar()
        return gespeichert

    async def _loeschen(self, mikrofon: object = None) -> None:
        """Ohne mikrofon alle Abdrücke (der Widerruf), mit der Kennung eines eingelernten Mikrofons nur dessen Abdruck."""
        gate = self.gate
        if mikrofon is not None and (not kennung_gueltig(mikrofon) or mikrofon not in gate.kennungen):
            logger.warning("Stimmabdruck: Löschen eines Mikrofons, das nicht eingelernt ist, abgewiesen")
            await self._fehler(MIKROFON_FEHLT)
            await self.status_melden()  # die Oberfläche bekommt die aktuelle Liste
            return
        if gate.sperrt and (gate.abdruck_geschuetzt or gate.zustand in ("laedt", "kaputt")) and not self.nachweis_ok():
            await self._fehler(LOESCHEN_NACHWEIS)  # vielleicht gibt es einen Abdruck: nicht ohne Nachweis löschen
            return
        # Erst das Einlernen beenden und ein schon laufendes Speichern abwarten, sonst käme der Abdruck nach dem Löschen wieder
        await self.pruefer.einlernen_abbrechen()
        await self.pruefer.einlernen_warten()
        einzeln = mikrofon if (self.mehrere and isinstance(mikrofon, str)) else None  # ohne 0029 gibt es nur einen: alle
        if not await abdruck_loeschen(self._memory, mikrofon=einzeln):
            await self._fehler(NICHT_GELOESCHT)
            return
        meldung = {"type": "stimmabdruck", "status": "geloescht"}
        if einzeln is None:
            self.gate.setze_abdruck(None, geloescht=True)
        else:
            self.gate.abdruck_entfernen(einzeln)
            meldung["mikrofon"] = einzeln
        await self._senden(meldung)
        await self.status_melden()

    # ---------- Client-Nachricht mikrofontest ----------

    async def mikrofontest(self, daten: object) -> None:
        """Die Oberfläche beginnt den Mikrofontest: eine laufende Antwort von W.A.I.S. unterbrechen (die Wiedergabe schaltet die Oberfläche
        selbst stumm). Andere Aktionen wirken nicht."""
        if isinstance(daten, dict) and daten.get("aktion") == "start":
            await self.pruefer.ausgabe_unterbrechen()
