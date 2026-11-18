"""Zweites Sprechermodell im Schattenbetrieb (seit 18.11.2026): misst bei jeder Äußerung mit, entscheidet nie etwas.

Wozu: TitaNet-Large (stimme_modell.py) trennt bei kurzen Äußerungen schwach. Bevor ein anderes Modell das Urteil bekommt, rechnet es hier
im Schatten mit: Bei jeder Prüfung schreibt der Kern eine Zeile mit Zahlen ins Log (Wert TitaNet, Wert Schatten, Länge, ob W.A.I.S. sprach,
Urteil, Rechenzeit beider Modelle), nie Ton, nie Text. Das Urteil bleibt allein bei TitaNet. scripts/wamo_stimme_schatten_auswerten.py
liest die Zeilen aus journalctl und zeigt je Längenklasse, wie gut beide Modelle eigen und fremd trennen.

Schalter WAMO_STIMME_SCHATTEN (an oder aus, Standard aus, nur über wamo-core-env am Server): Erst damit lädt der Kern das zweite Modell,
rechnet beim Einlernen einen Schatten-Abdruck aus denselben Stücken wie TitaNet (gespeichert in speakers.voiceprint_shadow mit dem Namen
des Modells in speakers.shadow_model, Migration 0028) und misst bei jeder Prüfung mit. Ohne Schatten-Abdruck (vor dem Einschalten
eingelernt) misst er nichts: dafür einmal neu einlernen. Laborprofile haben keine Stimmprüfung (stimme_sitzung.StimmSitzung.fuer), also
auch keinen Schatten.

Modell: WeSpeaker ResNet34, trainiert auf VoxCeleb2 (Sprecher aus vielen Ländern, überwiegend Englisch), 256 Werte, ohne Large-Margin-
Feinschliff (die LM-Fassungen sind laut WeSpeaker erst über 3 s besser), ONNX aus den Releases von sherpa-onnx. Gewählt am 18.11.2026 nach
Quellen und eigener Messung (README, Abschnitt Stimmabdruck): Auf VoxCeleb1-O mit 2 s langen Testäußerungen EER 2,12 % gegen 3,28 % für
ERes2Net, das einzige andere englische Modell neben CAM++ im Release (ERes2NetV2-Paper, Interspeech 2024, Tabelle 3); in voller Länge
0,867 % (WeSpeaker, VoxCeleb v2). Die CAM++-Fassungen für VoxCeleb (WeSpeaker und 3D-Speaker) liefern in sherpa-onnx 2.0.1 je nach Länge
der Äußerung stark schwankende Abdrücke (Kosinus zum eigenen Abdruck bei 1,5 s 0,19, bei 2 s 0,92, bei 2,5 s 0,09), sie scheiden aus.
Rechenzeit gemessen auf einem x86-Laptop mit 2 Threads: rund 23 ms für 1 s, 37 ms für 1,5 s und 47 ms für 2 s Sprache (TitaNet 33, 41 und
54 ms). Am Server steht die echte Dauer in jeder Logzeile (ms_schatten).

Mittelwertbereinigung: WeSpeaker trainiert mit Merkmalen, von denen je Äußerung der Mittelwert abgezogen ist (CMN). sherpa-onnx tut das nur,
wenn die Datei den Metadateneintrag feature_normalize_type=global-mean trägt, und die WeSpeaker-Dateien im Release tragen ihn nicht. Ohne ihn
lagen fremde Stimmen in der Messung bei 0,75 (mit: 0,17). Deshalb leitet der Kern aus der Datei des Releases eine zweite ab: dieselben
Bytes plus genau dieser eine Eintrag (CMN_ZUSATZ, ein angehängtes Feld von ModelProto.metadata_props), beide Dateien per SHA-256
festgenagelt. Am Server genügt es, die Datei des Releases vorab in den Cache-Ordner zu legen (wie bei TitaNet); fehlt sie, lädt der Kern sie
nach. Fehlt sie, stimmt eine Prüfsumme nicht oder scheitert das Laden: nur ein Hinweis im Log, die Prüfung läuft unverändert mit TitaNet.

Rechenzeit: Der Schatten rechnet in einer eigenen Aufgabe, nachdem das Urteil von TitaNet gemeldet ist; das Urteil wartet nie auf ihn. Je
Sitzung rechnet höchstens eine Äußerung im Schatten, läuft noch eine, wird die nächste übersprungen (Zähler uebersprungen). Das Modell
hat eine eigene Sperre und eigene Threads, TitaNet wartet also nie auf den Schatten.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
import os
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from loguru import logger

import stimme_modell as sm
from env_schalter import schalter_an
from stimme_gate import Abdruck, StimmGate

SCHALTER = "WAMO_STIMME_SCHATTEN"
SCHATTEN_NAME = "wespeaker_en_voxceleb_resnet34.onnx"  # Datei im Release, so wird sie auch vorab abgelegt
SCHATTEN_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + SCHATTEN_NAME
SCHATTEN_SHA256 = "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94"  # wie checksum.txt im Release
SCHATTEN_DATEI = "wespeaker_en_voxceleb_resnet34.cmn.onnx"  # abgeleitet: die Datei des Releases plus CMN_ZUSATZ
SCHATTEN_SHA256_CMN = "6928c40c3b5c695352998c261cb6f2250c4e52a991e324c0f63c2e10fe7c31f8"
SCHATTEN_DIM = 256
SCHATTEN_MODELL = "wespeaker-resnet34-cmn"  # steht mit dem Schatten-Abdruck in speakers.shadow_model; ein anderes Modell braucht neu einlernen
THREADS = 2


def metadaten_eintrag(schluessel: str, wert: str) -> bytes:
    """Ein Eintrag in ModelProto.metadata_props (Feld 14, StringStringEntryProto mit key = Feld 1 und value = Feld 2), so kodiert, dass er an
    eine ONNX-Datei angehängt werden kann. Nur kurze Texte (jede Länge passt in ein Byte)."""
    k, w = schluessel.encode(), wert.encode()
    eintrag = b"\x0a" + bytes([len(k)]) + k + b"\x12" + bytes([len(w)]) + w
    if max(len(k), len(w), len(eintrag)) > 127:
        raise ValueError("Metadaten zu lang für die kurze Kodierung")
    return b"\x72" + bytes([len(eintrag)]) + eintrag


CMN_ZUSATZ = metadaten_eintrag("feature_normalize_type", "global-mean")


def schatten_an(wert: str | None = None) -> bool:
    """Ist der Schattenbetrieb eingeschaltet (WAMO_STIMME_SCHATTEN, Standard aus; ein unbekannter Wert bleibt aus)?"""
    return schalter_an(SCHALTER, wert, standard=False)


def vorwaermen(modell: object) -> None:
    """Lädt ein Schattenmodell im Hintergrund, wenn es das kann (SchattenModell.vorwaermen; Ersatzmodelle in Tests brauchen es nicht)."""
    methode = getattr(modell, "vorwaermen", None)
    if callable(methode):
        methode()


def ableiten(roh: Path, fertig: Path, sha256: str, zusatz: bytes = CMN_ZUSATZ) -> None:
    """Schreibt roh plus zusatz nach fertig (über eine Teildatei, erst nach der Prüfung umbenannt). Blockiert. Stimmt die Summe nicht:
    ValueError, nichts bleibt liegen."""
    inhalt = roh.read_bytes() + zusatz
    if hashlib.sha256(inhalt).hexdigest() != sha256:
        raise ValueError("Prüfsumme des abgeleiteten Schattenmodells stimmt nicht")
    teil = fertig.with_name(f"{fertig.name}.{os.getpid()}.part")
    try:
        teil.write_bytes(inhalt)
        teil.replace(fertig)
    finally:
        teil.unlink(missing_ok=True)


class SchattenModell(sm.StimmModell):
    """Das Schattenmodell, einmal je Prozess (SCHATTEN unten). get liefert den Embedder (256 Werte) oder None, wirft nie. Wie StimmModell mit
    Download, Prüfsumme und Wartezeiten nach Fehlschlägen, dazu der Schritt von der Datei des Releases zur abgeleiteten (ableiten)."""

    ETIKETT = "Stimmschatten"

    def __init__(self, ordner: Path | None = None, *, roh_sha256: str = SCHATTEN_SHA256, sha256: str = SCHATTEN_SHA256_CMN,
                 uhr: Callable[[], float] = time.monotonic):
        super().__init__(None, sha256=sha256, uhr=uhr)
        self._ordner = ordner
        self._roh_sha256 = roh_sha256
        self._vorwaermen: asyncio.Task | None = None

    @property
    def pfad(self) -> Path:
        return (self._ordner or sm.cache_ordner()) / SCHATTEN_DATEI

    @property
    def roh_pfad(self) -> Path:
        return (self._ordner or sm.cache_ordner()) / SCHATTEN_NAME

    async def _datei_bereit(self) -> Path:
        fertig = self.pfad
        if fertig.is_file():
            if await asyncio.to_thread(sm.datei_sha256, fertig) == self._sha256:
                return fertig
            _loeschen_im_cache(fertig)
            raise ValueError("Prüfsumme des abgeleiteten Schattenmodells stimmt nicht")
        roh = self.roh_pfad
        if not roh.is_file():
            await sm.herunterladen(roh, url=SCHATTEN_URL, sha256=self._roh_sha256)
        elif await asyncio.to_thread(sm.datei_sha256, roh) != self._roh_sha256:
            _loeschen_im_cache(roh)
            raise ValueError("Prüfsumme der Modelldatei stimmt nicht")
        await asyncio.to_thread(ableiten, roh, fertig, self._sha256)
        return fertig

    def _rechner_bauen(self, pfad: Path) -> sm.Embedder:
        return sm.Embedder(pfad, threads=THREADS, dim=SCHATTEN_DIM)

    def _fehlgeschlagen(self, e: Exception) -> None:
        logger.info("Stimmschatten: Modell nicht verfügbar ({}: {}), die Prüfung läuft unverändert mit TitaNet", type(e).__name__, e)

    def vorwaermen(self) -> None:
        """Lädt das Modell im Hintergrund, damit es beim Einlernen bereit ist. Höchstens eine Aufgabe zugleich; ohne Ereignisschleife nichts."""
        if self.bereit or (self._vorwaermen is not None and not self._vorwaermen.done()):
            return
        try:
            self._vorwaermen = asyncio.get_running_loop().create_task(self.get())
        except RuntimeError:
            return

    async def warten(self) -> None:
        """Wartet auf ein laufendes Vorwärmen (für Tests)."""
        if self._vorwaermen is not None:
            await asyncio.gather(self._vorwaermen, return_exceptions=True)


def _loeschen_im_cache(pfad: Path) -> None:
    """Eine falsche Datei im Cache-Ordner des Dienstes wird gelöscht (beim nächsten Versuch neu geladen), sonst bleibt sie liegen."""
    if sm._im_cache_ordner(pfad):
        with contextlib.suppress(OSError):
            pfad.unlink()


ZEILE = ("Stimmschatten: titanet={:.3f} schatten={:.3f} secs={:.2f} wamo={:d} urteil={} ms_titanet={:.0f} ms_schatten={:.0f}")


class SchattenPruefung:
    """Der Schatten einer Sitzung (gehört zum Prüfer, stimme_pruefer.py): rechnet nach jedem Urteil den Wert des Schattenmodells gegen den
    Schatten-Abdruck des Gates und schreibt genau eine Zeile ins Log. Wirft nie, ändert nie das Gate."""

    def __init__(self, gate: StimmGate, modell: sm.ModellQuelle, uhr: Callable[[], float] = time.perf_counter):
        self._gate = gate
        self._modell = modell
        self._uhr = uhr
        self._task: asyncio.Task | None = None
        self._zu = False  # nach aufraeumen beginnt keine Rechnung mehr
        self.uebersprungen = 0

    def starten(self, pcm: bytes, rate: int, secs: float, ueberlappung: bool, urteil: str, wert: float, titanet_ms: float) -> None:
        """Nach dem Urteil zur Äußerung (pcm wie TitaNet ihn bekam): rechnet in einer eigenen Aufgabe und kehrt sofort zurück. Mit mehreren
        Abdrücken (einer je Mikrofon, seit 18.11.2026) zählt der beste Wert über alle Schatten-Abdrücke, unabhängig davon, welcher Abdruck
        bei TitaNet den besten Wert hatte (je Modell getrennt)."""
        stand = self._gate.abdruecke
        abdruecke = tuple(a.schatten for a in stand if a.schatten is not None)
        if self._zu or not abdruecke or not pcm or not math.isfinite(wert):
            return
        if not self._modell.bereit:
            vorwaermen(self._modell)  # nie in dieser Aufgabe laden: ein Download hielte sonst alle folgenden Äußerungen auf
            return
        if self._task is not None and not self._task.done():
            self.uebersprungen += 1
            logger.debug("Stimmschatten: übersprungen, die Äußerung davor rechnet noch ({})", self.uebersprungen)
            return
        self._task = asyncio.create_task(self._rechnen(pcm, rate, secs, ueberlappung, urteil, wert, titanet_ms, stand, abdruecke))
        self._task.add_done_callback(_abholen)

    async def _rechnen(self, pcm: bytes, rate: int, secs: float, ueberlappung: bool, urteil: str, wert: float, titanet_ms: float,
                       stand: tuple[Abdruck, ...], abdruecke: tuple[np.ndarray, ...]) -> None:
        rechner = await self._modell.get()
        if rechner is None:
            return
        start = self._uhr()
        try:
            vektor = await asyncio.to_thread(rechner.embed, pcm, rate)
            werte = [w for a in abdruecke if math.isfinite(w := sm.kosinus(vektor, a))]
        except Exception as e:  # der Schatten entscheidet nichts: ein Fehler fehlt nur in der Messung
            logger.debug("Stimmschatten: Rechnen fehlgeschlagen ({})", type(e).__name__)
            return
        ms = (self._uhr() - start) * 1000
        if not werte or self._gate.abdruecke is not stand:
            return  # gelöscht oder neu eingelernt, während der Schatten rechnete
        logger.info(ZEILE, wert, max(werte), secs, int(bool(ueberlappung)), urteil, titanet_ms, ms)

    async def warten(self) -> None:
        """Wartet auf eine laufende Rechnung (für Tests)."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def aufraeumen(self) -> None:
        """Die Sitzung endet: eine laufende Rechnung abbrechen (der Thread rechnet zu Ende, sein Ergebnis kommt nirgends an), danach beginnt
        keine neue mehr, auch nicht aus einer Prüfung, die gerade noch zu Ende läuft."""
        self._zu = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _abholen(task: asyncio.Task) -> None:
    if not task.cancelled() and (fehler := task.exception()) is not None:  # abgeholt: kein "never retrieved" im Log
        logger.debug("Stimmschatten: Aufgabe mit Fehler beendet ({})", type(fehler).__name__)


SCHATTEN = SchattenModell()  # genau einmal je Prozess, für alle Sitzungen und Profile; geladen erst mit WAMO_STIMME_SCHATTEN=an
