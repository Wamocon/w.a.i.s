"""Mikrofonkette im Protokoll: mit welcher Signalkette spricht die Person gerade? Nur Zahlen und eine grobe Klasse, nie ein Gerätename.

Die Stimmerkennung bricht ein, wenn sich die Kette ändert (Mikrofon, Aufbereitung, Pegel). Messung vom 19.11.2026: Mit Bluetooth-Kopfhörer
lagen eigene Sätze mit dem Abdruck vom Laptop bei 0,2 bis 0,3, mit eigenem Abdruck bei etwa 0,8. Die Aufnahme im Browser startet ohne eigene
Vorgaben für Echounterdrückung, Rauschunterdrückung und Verstärkung, der Browser wählt seine Standardwerte, und das stand nirgends im Protokoll.

Die Oberfläche liest nach jedem Spurwechsel track.getSettings() und schickt genau eine Nachricht je Wechsel
({"type": "mikrofon_info", "data": {"echo", "rauschen", "verstaerkung", "rate", "kanaele", "klasse"}}, ui/src/lib/mikrofonKette.ts):

  * echo, rauschen, verstaerkung: true, false oder null (der Browser sagt es nicht)
  * rate: ganze Zahl in Hz (RATE_MIN bis RATE_MAX) oder null
  * kanaele: ganze Zahl KANAELE_MIN bis KANAELE_MAX oder null
  * klasse: eingebaut, headset, bluetooth oder unbekannt (grob aus dem Gerätenamen abgeleitet, dort, im Browser; der Name selbst reist nie)

Hier gilt dieselbe Strenge noch einmal, weil die Nachricht Fremdeingabe ist: Nur diese sechs Felder zählen, jeder falsche Typ (auch Unterklassen
von bool, int und str) und jeder Wert außerhalb der Grenzen heißt "unbekannt" (None), jede unbekannte Klasse heißt "unbekannt", jedes weitere Feld
fällt weg. Eine Nachricht ohne ein einziges gültiges Feld (leer, nur Unsinn) gilt nicht und ändert nichts. Ins Protokoll gelangt nur, was aus fester
Auswahl oder aus geprüften Zahlen kommt, also nie ein Name, eine Kennung oder ein freier Text.

Protokolliert wird eine Zeile je Änderung (INFO, höchstens MAX_MELDUNGEN Zeilen je Sitzung; der Stand selbst bleibt auch danach aktuell), zum Beispiel
    Mikrofonkette: klasse=bluetooth echo=an rauschen=an verstaerkung=an rate=48000 kanaele=1
(null erscheint als ?), und jede Urteilszeile des Prüfers (stimme_pruefer.py) trägt am Ende die Klasse (", Kette bluetooth"), sobald eine Nachricht
da war. Der Stand lebt nur im Arbeitsspeicher der Sitzung: nie in der Datenbank, nie Audio, nie im Gespräch mit dem Modell. Laborprofile
bekommen weder eine Stimmsitzung noch dürfen sie diese Nachricht senden (labor.client_nachricht_erlaubt).

Nichts hier wirft nach außen: Ein Fehler in dieser Auswertung darf ein Gespräch nie stören.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

KLASSE_UNBEKANNT = "unbekannt"
KLASSEN = ("eingebaut", "headset", "bluetooth", KLASSE_UNBEKANNT)
RATE_MIN, RATE_MAX = 8000, 384000  # Hz; Browser liefern 16000 bis 96000, alles darunter oder darüber ist kein Mikrofon
KANAELE_MIN, KANAELE_MAX = 1, 8
MAX_MELDUNGEN = 50  # Logzeilen je Sitzung; ein Gerätewechsel sind wenige, mehr wäre eine Schleife in der Oberfläche (der Stand bleibt aktuell)
SCHALTER = ("echo", "rauschen", "verstaerkung")


def _schalter(wert: object) -> bool | None:
    return wert if type(wert) is bool else None  # genau bool: keine Unterklasse, keine 0 und 1


def _ganzzahl(wert: object, kleinste: int, groesste: int) -> int | None:
    # genau int: bool ist in Python eine int-Unterklasse, aber kein Wert für eine Rate oder Kanalzahl, und eine eigene Unterklasse kein JSON
    if type(wert) is int and kleinste <= wert <= groesste:
        return wert
    return None


def _text(wert: bool | None) -> str:
    return "?" if wert is None else ("an" if wert else "aus")


@dataclass(frozen=True)
class Kette:
    """Die Kette der Aufnahme, wie die Oberfläche sie gemeldet hat. None heißt: unbekannt."""

    klasse: str = KLASSE_UNBEKANNT
    echo: bool | None = None
    rauschen: bool | None = None
    verstaerkung: bool | None = None
    rate: int | None = None
    kanaele: int | None = None

    def zeile(self) -> str:
        return (
            f"Mikrofonkette: klasse={self.klasse} echo={_text(self.echo)} rauschen={_text(self.rauschen)} "
            f"verstaerkung={_text(self.verstaerkung)} rate={'?' if self.rate is None else self.rate} "
            f"kanaele={'?' if self.kanaele is None else self.kanaele}"
        )

    def kurz(self) -> str:
        """Anhang für die Urteilszeilen des Prüfers: nur die Klasse."""
        return f", Kette {self.klasse}"


def aus_nachricht(daten: object) -> Kette | None:
    """Die Kette aus den Daten der Client-Nachricht, streng geprüft. Kein Objekt, kein einziges gültiges Feld oder ein Fehler beim Lesen: None,
    die Nachricht gilt nicht (eine leere oder bloße Unsinn-Nachricht überschreibt keinen bekannten Stand)."""
    if not isinstance(daten, dict):
        return None
    try:
        klasse = daten.get("klasse")
        klasse_gueltig = type(klasse) is str and klasse in KLASSEN
        kette = Kette(
            klasse=klasse if klasse_gueltig else KLASSE_UNBEKANNT,
            echo=_schalter(daten.get("echo")),
            rauschen=_schalter(daten.get("rauschen")),
            verstaerkung=_schalter(daten.get("verstaerkung")),
            rate=_ganzzahl(daten.get("rate"), RATE_MIN, RATE_MAX),
            kanaele=_ganzzahl(daten.get("kanaele"), KANAELE_MIN, KANAELE_MAX),
        )
    except Exception:  # ein Objekt, dessen Zugriff wirft: dann gilt die Nachricht nicht
        return None
    wissen = (kette.echo, kette.rauschen, kette.verstaerkung, kette.rate, kette.kanaele)
    return kette if klasse_gueltig or any(w is not None for w in wissen) else None


class KettenProtokoll:
    """Der letzte gemeldete Stand der Kette einer Sitzung, dazu die Logzeile je Änderung. Gehört genau einer Sitzung."""

    def __init__(self) -> None:
        self.stand: Kette | None = None
        self._zeilen = 0
        self._grenze_gemeldet = False

    def aufnehmen(self, daten: object) -> bool:
        """Nachricht prüfen, Stand merken und bei einer Änderung eine Zeile schreiben (höchstens MAX_MELDUNGEN je Sitzung; danach bleibt der Stand
        aktuell, damit die Urteilszeilen die richtige Klasse tragen, nur die Zeilen entfallen). True, wenn sich der Stand geändert hat. Wirft nie."""
        try:
            kette = aus_nachricht(daten)
            if kette is None or kette == self.stand:
                return False  # ungültig, oder dieselbe Kette (zum Beispiel Mikrofon aus und wieder an): nichts zu tun, keine Zeile
            self.stand = kette
            if self._zeilen >= MAX_MELDUNGEN:
                if not self._grenze_gemeldet:
                    self._grenze_gemeldet = True
                    logger.warning("Mikrofonkette: mehr als {} Änderungen in dieser Sitzung, weitere erscheinen nicht mehr als Zeile", MAX_MELDUNGEN)
                return True
            self._zeilen += 1
            logger.info("{}", kette.zeile())
            return True
        except Exception as e:  # nie ein Grund, ein Gespräch zu stören
            logger.warning("Mikrofonkette: Meldung nicht verarbeitet ({})", type(e).__name__)
            return False

    def kurz(self) -> str:
        """Anhang für die Urteilszeilen des Prüfers (", Kette bluetooth"); ohne Meldung leer. Wirft nie."""
        try:
            return self.stand.kurz() if self.stand is not None else ""
        except Exception:
            return ""
