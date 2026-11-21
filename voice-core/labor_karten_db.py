"""Labor-Karten aus der Datenbank nachladen (Werkstatt, Stufe 1, Vertrag Abschnitt 5).

Im Werkstatt-Panel pflegen die Betreuer Karten mit eigenen Wissenstexten und veröffentlichen sie als Version. Der Kern liest die AKTIVE
Version im Betrieb nach, ohne neues Release, und zeigt die Wissenstexte der Laborsitzung als eigenen, abgegrenzten Abschnitt "Wissen aus dem
Katalog" (labor_prompt.py), nie als Regel.

Schalter WAMO_LABOR_KARTEN_NACHLADEN (an oder aus, Standard AUS, ein Tippfehler bleibt aus; nur über wamo-core-env, nie aus der .env eines PCs).
Aus heißt: Der Kern liest nichts, fragt nichts und baut den Prompt genau wie ohne dieses Modul. Fehlen die Ansichten (Migration 0031 nicht
angewendet), läuft der Kern auch mit dem Schalter an unverändert weiter.

Gelesen werden nur zwei Ansichten, als wamo_core über die vorhandene Verbindung, nur mit select (der Kern hat hier keine Schreibrechte):
labor_karten_aktive_version (die Nummer der aktiven Version, leer ohne aktive Version) und labor_wissen_aktiv (je Karte der aktiven Version mit
dem Wissen "Eigener Text": version, karte_id, wissenstext). Beides in EINER Anweisung, damit Nummer und Texte zusammengehören.

Ein Zwischenspeicher je Prozess (nicht je Sitzung) hält den Stand höchstens TTL_SECS Sekunden. Beim Start einer Laborsitzung und danach in
ihrem Takt fragt eine Sitzung nur diesen Speicher, nie die Datenbank. Gleichzeitige Sitzungen lösen genau eine Lesung aus.

Prüfregeln (eine Version gilt ganz oder gar nicht, es wird nie gekürzt): höchstens MAX_EINTRAEGE Einträge, Kennung wie die Karten (A1 bis Z99), je Text
höchstens MAX_TEXT Zeichen, nur Zeichen wie in den Dateien der Labor-Daten (keine Steuer-, Format-, Bidi- und privaten Zeichen), kein Markup
(Tags, Sondermarken von Chat-Vorlagen), und alle Wissenstexte einer Version zusammen höchstens KATALOG_BUDGET_ZEICHEN Zeichen. Der Katalog hat
ein EIGENES Budget (Entscheidung vom 21.11.2026): Die Dateien aus labor_daten.py mit ihren 6000 Zeichen zählen nicht mit. Wird eine Version
abgelehnt oder lässt sich nicht lesen (Fehler, Zeitlimit), bleibt die zuletzt gültige Version, im Log steht nur die Versionsnummer und der Grund,
nie ein Text. Eine saubere leere Antwort ("keine aktive Version") ist dagegen keine Störung: Dann gilt kein Katalog mehr, ein zurückgezogener
Wissenstext bleibt nicht bis zum Neustart stehen. Der Zwischenspeicher setzt eine einzige Event-Loop voraus (wie der Kern); die Sperre ist je
Loop, nicht über Threads hinweg.

Die Texte sind DATEN, nie Anweisungen: Sie landen hinter einem Hinweis, der das ausspricht, zwischen Abschnittsmarken, die ein Text nicht
vortäuschen kann (labor_prompt.py), und nie im Regelteil. Mehr als das Sprachmodell kennt der Kern von ihnen nicht.
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

import labor_daten
from env_schalter import schalter_an

SCHALTER = "WAMO_LABOR_KARTEN_NACHLADEN"
ANSICHT_AKTIV = "labor_karten_aktive_version"
ANSICHT_WISSEN = "labor_wissen_aktiv"

TTL_SECS = 30.0  # so lange gilt eine Lesung für alle Sitzungen des Prozesses
SITZUNG_TAKT_SECS = 10.0  # so oft schaut eine laufende Sitzung in den Zwischenspeicher (nur Speicher, die Datenbank fragt allein TTL_SECS)
LESE_TIMEOUT_SECS = 3.0  # so lange wartet höchstens ein Sitzungsstart auf die Lesung (nur der eine, der sie auslöst, höchstens alle 30 s)
MAX_EINTRAEGE = 20
MAX_TEXT = 900
KATALOG_BUDGET_ZEICHEN = 2000  # Summe aller Wissenstexte der aktiven Version, unabhängig von den Dateien der Labor-Daten
ABFRAGE_GRENZE = MAX_EINTRAEGE + 5  # eine Zeile mehr als erlaubt genügt, um "zu viele" zu erkennen; nie unbegrenzt lesen

GRUND_LANG = "zu lang"
GRUND_GESAMT = "Gesamtumfang zu groß"
GRUND_VIELE = "zu viele Einträge"
GRUND_ZEICHEN = "Steuerzeichen"
GRUND_MARKUP = "Markup"
GRUND_KENNUNG = "Kennung ungültig"
GRUND_DOPPELT = "Kennung doppelt"
GRUND_VERSION = "Version ungültig"
GRUND_LEER = "Text leer"
GRUND_KEINE = "keine aktive Version"

KENNUNG_RE = re.compile(r"[A-Z][0-9]{1,2}")  # wie labor_karten.id in der Datenbank
# Markup, das ein Text nicht tragen darf (geprüft nach NFKC, damit vollbreite Zeichen nichts umgehen): Tags (auch Kommentare, Verarbeitungs-
# anweisungen und Tags über Zeilenumbrüche), jede Sondermarke der Chat-Vorlagen (<| und |>), eckige Marken älterer Vorlagen und Werkzeugmarken
# sowie Zeilen, die eine Gesprächsrolle ("Human:", "Assistant:") eröffnen. Ein Vergleich wie "a < b" bleibt erlaubt, "a<b und c>d" nicht
# (lieber ablehnen als still ändern). [ \t] statt \s in den Klammern, damit die Suche linear bleibt.
_MARKUP = re.compile(r"<[/!?|A-Za-z][^<>]*>|<\||\|>|\[[ \t]*/?[ \t]*(?:INST|SYS|TOOL_CALLS|AVAILABLE_TOOLS|TOOL_RESULTS)[ \t]*\]"
                     r"|^[ \t]*(?:human|assistant)[ \t]*:", re.IGNORECASE | re.MULTILINE)
# Zeichen, die zeichen_ok durchlässt, obwohl kein Mensch sie sieht: Variation Selectors (auch das Supplement mit Tag-Wirkung), Mongolische
# Variation Selectors, Füllzeichen (Hangul, Khmer), das Braille-Leerzeichen und der kombinierende Graphem-Verbinder
_UNSICHTBAR_BEREICHE = ((0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180D), (0x2800, 0x2800), (0x3164, 0x3164),
                        (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0100, 0xE01EF))
_UNSICHTBAR = re.compile("[" + "".join(f"{chr(von)}-{chr(bis)}" for von, bis in _UNSICHTBAR_BEREICHE) + "]")

_ABFRAGE = ("select v.version as version, w.karte_id as karte_id, w.wissenstext as wissenstext "
            "from {aktiv} v left join {wissen} w on w.version = v.version order by w.karte_id limit {grenze}")


class Abgelehnt(ValueError):
    """Eine gelesene Version erfüllt die Prüfregeln nicht. grund ist ein fester Satzteil, nie ein Stück Text."""

    def __init__(self, grund: str):
        super().__init__(grund)
        self.grund = grund


@dataclass(frozen=True)
class Gelesen:
    """Rohwerte aus den Ansichten, noch ungeprüft (version und die Paare karte_id, wissenstext)."""

    version: object
    texte: tuple[tuple[object, object], ...] = ()


@dataclass(frozen=True)
class Stand:
    """Eine geprüfte Version: (Kennung, Text) der Karten mit eigenem Wissenstext, nach Kennung geordnet."""

    version: int
    eintraege: tuple[tuple[str, str], ...] = ()

    @property
    def zeichen(self) -> int:
        return sum(len(text) for _, text in self.eintraege)


class KartenLeser(Protocol):
    """Quelle der aktiven Version. None heißt: es gibt keine aktive Version. Fehler der Quelle werfen einfach."""

    async def lesen(self) -> Gelesen | None: ...


def an(wert: str | None = None) -> bool:
    """Ist das Nachladen eingeschaltet? Standard aus; ein unbekannter Wert bleibt aus."""
    return schalter_an(SCHALTER, wert, standard=False)


def _reihenfolge(eintrag: tuple[str, str]) -> tuple[str, int]:
    return eintrag[0][0], int(eintrag[0][1:])


def pruefen(gelesen: Gelesen) -> Stand:
    """Die geprüfte Version oder Abgelehnt."""
    version = gelesen.version
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise Abgelehnt(GRUND_VERSION)
    if len(gelesen.texte) > MAX_EINTRAEGE:
        raise Abgelehnt(GRUND_VIELE)
    eintraege: dict[str, str] = {}
    for kennung, text in gelesen.texte:
        if not isinstance(kennung, str) or not KENNUNG_RE.fullmatch(kennung):
            raise Abgelehnt(GRUND_KENNUNG)
        if kennung in eintraege:
            raise Abgelehnt(GRUND_DOPPELT)
        if not isinstance(text, str):
            raise Abgelehnt(GRUND_LEER)
        if len(text) > MAX_TEXT * 2:  # grob vorab, damit ein riesiger Text nicht erst durchsucht wird
            raise Abgelehnt(GRUND_LANG)
        sauber = text.replace("\r\n", "\n").strip()
        if not sauber:
            raise Abgelehnt(GRUND_LEER)
        if len(sauber) > MAX_TEXT:
            raise Abgelehnt(GRUND_LANG)
        if not labor_daten.zeichen_ok(sauber) or _UNSICHTBAR.search(sauber):
            raise Abgelehnt(GRUND_ZEICHEN)
        if _MARKUP.search(unicodedata.normalize("NFKC", sauber)):
            raise Abgelehnt(GRUND_MARKUP)
        eintraege[kennung] = sauber
    stand = Stand(version, tuple(sorted(eintraege.items(), key=_reihenfolge)))
    if stand.zeichen > KATALOG_BUDGET_ZEICHEN:
        raise Abgelehnt(GRUND_GESAMT)
    return stand


class Datenbank(Protocol):
    """Der Teil von memory.Database, den der Leser braucht: der voll qualifizierte Name einer Ansicht und eine Abfrage ohne Parameter."""

    def t(self, name: str) -> str: ...

    async def fetch(self, sql: str, *args: Any) -> Any: ...


class DatenbankKartenLeser:
    """Liest die zwei Ansichten als wamo_core. db: eine Database (memory.py) oder None für die gemeinsame Verbindung des Kerns."""

    def __init__(self, db: Datenbank | None = None):
        self._db = db

    def _datenbank(self) -> Datenbank:
        if self._db is not None:
            return self._db
        from memory import shared_database

        return shared_database()

    async def lesen(self) -> Gelesen | None:
        db = self._datenbank()
        sql = _ABFRAGE.format(aktiv=db.t(ANSICHT_AKTIV), wissen=db.t(ANSICHT_WISSEN), grenze=ABFRAGE_GRENZE)
        zeilen = await db.fetch(sql)
        if not zeilen or zeilen[0]["version"] is None:
            return None
        version = zeilen[0]["version"]
        if any(z["version"] != version for z in zeilen):
            raise Abgelehnt(GRUND_VERSION)  # Nummer und Texte müssen zu EINER Version gehören
        texte = tuple((z["karte_id"], z["wissenstext"]) for z in zeilen if z["karte_id"] is not None)
        return Gelesen(version, texte)


class KartenNachlader:
    """Zwischenspeicher je Prozess: höchstens eine Lesung je ttl Sekunden, egal wie viele Sitzungen fragen. aktuell wirft nie."""

    def __init__(self, leser: KartenLeser, *, ttl: float = TTL_SECS, timeout: float = LESE_TIMEOUT_SECS,
                 uhr: Callable[[], float] = time.monotonic):
        self._leser = leser
        self._ttl = ttl
        self._timeout = timeout
        self._uhr = uhr
        self.lesungen = 0  # wie oft die Quelle wirklich gefragt wurde (die Tests prüfen, dass es nicht je Sitzung geschieht)
        self._gueltig: Stand | None = None
        self._frisch_bis: float | None = None
        self._gemeldet: set[tuple[str, str]] = set()  # Fehler und Ablehnungen, die schon im Log stehen (bis eine Lesung gelingt)
        self._sperre_objekt: asyncio.Lock | None = None
        self._sperre_loop: asyncio.AbstractEventLoop | None = None

    def _frisch(self) -> bool:
        return self._frisch_bis is not None and self._uhr() < self._frisch_bis

    def _sperre(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._sperre_objekt is None or self._sperre_loop is not loop:
            self._sperre_objekt, self._sperre_loop = asyncio.Lock(), loop
        return self._sperre_objekt

    def _einmal(self, schluessel: tuple[str, str], zeile: str, *teile: object) -> None:
        """Eine Warnung je Schlüssel, bis wieder eine Version gelungen ist (sonst schriebe ein dauerhaft fehlender Zustand alle 30 s ins Log)."""
        if schluessel not in self._gemeldet:
            self._gemeldet.add(schluessel)
            logger.warning(zeile, *teile)

    async def aktuell(self) -> Stand | None:
        """Die zuletzt gültige Version oder None (keine aktive Version, nichts Gültiges gelesen)."""
        try:
            if not self._frisch():
                async with self._sperre():
                    if not self._frisch():
                        await self._lesen()
        except Exception as fehler:  # noqa: BLE001 (eine Laborsitzung scheitert nie am Nachladen)
            self._einmal(("fehler", type(fehler).__name__), "Labor-Karten: nicht gelesen ({})", type(fehler).__name__)
        return self._gueltig

    async def _lesen(self) -> None:
        self.lesungen += 1
        try:
            await self._lesen_und_pruefen()
        except asyncio.CancelledError:
            raise  # die Sitzung wurde abgebrochen: die Lesung zählt nicht, die nächste fragt neu
        except Exception as fehler:  # noqa: BLE001 (auch ein unerwarteter Fehler stört keine Sitzung und umgeht den Zwischenspeicher nicht)
            self._einmal(("fehler", type(fehler).__name__), "Labor-Karten: nicht gelesen ({})", type(fehler).__name__)
        # Erst nach der Lesung (auch nach einem Fehler): nicht öfter als einmal je ttl fragen, und wer während der Lesung wartet, sieht danach
        # ihren Stand statt eines leeren
        self._frisch_bis = self._uhr() + self._ttl

    def _ablehnen(self, nummer: object, grund: str) -> None:
        nummer = nummer if isinstance(nummer, int) and not isinstance(nummer, bool) else "?"
        self._einmal((str(nummer), grund), "Labor-Karten: Version {} abgelehnt ({})", nummer, grund)

    async def _lesen_und_pruefen(self) -> None:
        try:
            gelesen = await asyncio.wait_for(self._leser.lesen(), self._timeout)
        except Abgelehnt as abgelehnt:  # der Leser selbst hat die Zeilen verworfen (zwei Versionen in einer Antwort)
            self._ablehnen(None, abgelehnt.grund)
            return
        except Exception as fehler:  # noqa: BLE001 (Ansicht fehlt, Verbindung weg, Zeitlimit: die letzte gültige Version bleibt)
            self._einmal(("fehler", type(fehler).__name__), "Labor-Karten: nicht gelesen ({})", type(fehler).__name__)
            return
        if gelesen is None:
            # Eine saubere, leere Antwort heißt: es gilt keine Version (zurückgezogen oder nie veröffentlicht). Ein zurückgezogener Wissenstext
            # darf nicht weiter gelten; nur Fehler, Zeitlimit und abgelehnte Versionen lassen die letzte gültige stehen.
            self._einmal(("version", GRUND_KEINE), "Labor-Karten: {}, kein Katalog", GRUND_KEINE)
            self._gueltig = None
            return
        try:
            stand = pruefen(gelesen)
        except Abgelehnt as abgelehnt:
            self._ablehnen(gelesen.version, abgelehnt.grund)
            return
        if self._gueltig is None or self._gueltig.version != stand.version:
            logger.info("Labor-Karten: Version {} geladen", stand.version)
        self._gueltig = stand
        self._gemeldet.clear()  # Fehler und Ablehnungen gelten als behoben


_standard = KartenNachlader(DatenbankKartenLeser())


def nachlader_fuer_sitzung(nachlader: KartenNachlader | None = None) -> KartenNachlader | None:
    """Der Nachlader einer Laborsitzung, oder None bei ausgeschaltetem Schalter (dann wird nichts gelesen und nichts geändert).
    nachlader: nur für Tests, ersetzt den Zwischenspeicher des Prozesses, schaltet aber nie am Schalter vorbei."""
    if not an():
        return None
    return nachlader if nachlader is not None else _standard


def zuruecksetzen() -> None:
    """Nur für Tests: der Zwischenspeicher des Prozesses beginnt von vorn."""
    global _standard
    _standard = KartenNachlader(DatenbankKartenLeser())
