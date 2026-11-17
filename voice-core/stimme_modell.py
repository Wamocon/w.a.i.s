"""Stimmabdruck, Rechenteil: Modell laden und aus Sprache einen Abdruck mit 192 Werten rechnen.

Modell: NVIDIA NeMo TitaNet-Large als ONNX aus den Releases von sherpa-onnx, 192 Werte je Stimme (passt zu speakers.voiceprint
in der Migration 0001). Gerechnet wird lokal auf der CPU im Kern, kein Ton verlässt dafür den Server. Die Datei (rund 100 MB) liegt
im Cache-Ordner des Dienstes (XDG_CACHE_HOME/wamo/sprecher/, am Server /var/cache/wamo-core) oder neben dem Code in
voice-core/.cache/sprecher/; WAMO_STIMME_MODELL nennt eine andere Datei. Fehlt sie, lädt der Kern sie beim ersten Bedarf nach und prüft
die SHA-256-Summe. Eine vorhandene Datei wird bei jedem Prozessstart gegen dieselbe Summe geprüft.

Vergleich: Kosinus-Ähnlichkeit zweier normierter Abdrücke (1 = gleiche Stimme, um 0 = fremd). Gemessen mit den Beispielaufnahmen von
sherpa-onnx: gleiche Sprecher 0,67 bis 0,80, fremde höchstens 0,34. Rechenzeit für 8 s Sprache rund 250 ms mit 2 Threads. Kurze
Äußerungen liegen deutlich tiefer (Befund vom 17.11.2026 und Versuch mit Hausstimmen in der README, Abschnitt Stimmabdruck); deshalb
schneidet das Einlernen den Ton wie der Prüfer (ohne_pausen, Stücke von 1,5 s) und misst eine persönliche Schwelle (schwelle_einlernen).

Ein Prozess hält das Modell genau einmal (MODELL am Ende der Datei), alle Sitzungen und Profile benutzen dieselbe Instanz. Der Rechner
ist nicht an ein Profil gebunden: Abdrücke und Prüfzustand gehören je Sitzung zum Gate (stimme_gate.py). Gerechnet wird nacheinander
(Sperre im Embedder), damit nie zwei Sitzungen gleichzeitig denselben Extraktor benutzen. Rohton wird nie gespeichert.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx
import numpy as np
from loguru import logger

MODELL_NAME = "nemo_en_titanet_large.onnx"
MODELL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODELL_NAME
MODELL_SHA256 = "d51abcf31717ef28162f26acb9d44dd4127c3d44c9b8624f699f3425daca8e77"
DIM = 192
THREADS = 2
NEUER_VERSUCH_SECS = 60.0  # nach dem ersten Fehler (Datei fehlt, Netz weg, Summe falsch) erst dann wieder versuchen
WARTEZEITEN = (NEUER_VERSUCH_SECS, 300.0, 1800.0)  # nach jedem weiteren Fehlschlag länger, danach bleibt es bei 30 Minuten
MODELL_MAX_BYTES = 150 * 1024 * 1024  # das Modell ist rund 100 MB groß; mehr wird nicht geladen
GESAMT_FRIST_SECS = 600.0  # ein Download dauert höchstens 10 Minuten
# Einlernen: die Sprache in Stücke dieser Länge teilen, jedes Stück ergibt einen Abdruck. Der Mittelwert ist der Stimmabdruck,
# die Streuung zeigt, ob die Aufnahme sauber war. Seit dem 17.11.2026 so lang wie eine typische Äußerung im Gespräch (vorher 3 s): Der
# Abdruck soll zu dem passen, womit der Prüfer vergleicht. Aus 20 s Sprache werden so rund 13 Stücke.
STUECK_SECS = 1.5
MIN_STUECKE = 8
# Sprache von Stille trennen (nur beim Einlernen): 20-ms-Blöcke lauter als das zählen als Sprache. Leise Stellen bleiben im Ton, nur
# Pausen über PAUSE_SECS fallen weg, wie in einer Äußerung, die der Prüfer an den Meldungen der Sprachpausenerkennung ausschneidet.
SPRACHE_DBFS = -45.0
BLOCK_SECS = 0.02
PAUSE_SECS = 0.3
# Persönliche Schwelle (schwelle_einlernen): je Stück der Kosinus gegen den Mittelpunkt der übrigen Stücke, davon dieses Quantil minus
# den Abstand, begrenzt auf SCHWELLE_MIN bis SCHWELLE_MAX
SCHWELLE_QUANTIL = 0.10
SCHWELLE_ABSTAND = 0.03
SCHWELLE_MIN, SCHWELLE_MAX = 0.30, 0.50
VERBINDUNG_SECS = 10.0
LESEN_SECS = 60.0


def cache_ordner(umgebung: Mapping[str, str] | None = None) -> Path:
    """Der Cache-Ordner des Dienstes für das Modell: XDG_CACHE_HOME/wamo/sprecher/, sonst neben dem Code (ohne WAMO_STIMME_MODELL)."""
    env = os.environ if umgebung is None else umgebung
    cache = (env.get("XDG_CACHE_HOME") or "").strip()
    return Path(cache) / "wamo" / "sprecher" if cache else Path(__file__).resolve().parent / ".cache" / "sprecher"


def modell_pfad(umgebung: Mapping[str, str] | None = None) -> Path:
    """Ort der Modelldatei: WAMO_STIMME_MODELL, sonst der Cache-Ordner des Dienstes, sonst neben dem Code."""
    env = os.environ if umgebung is None else umgebung
    eigener = (env.get("WAMO_STIMME_MODELL") or "").strip()
    if eigener:
        return Path(eigener)
    return cache_ordner(env) / MODELL_NAME


@runtime_checkable
class Rechner(Protocol):
    """Was Prüfer und Einlernen vom Rechner brauchen (Embedder, in Tests ein Ersatz): aus PCM einen normierten Abdruck, blockierend."""

    def embed(self, pcm: bytes, sample_rate: int) -> np.ndarray: ...


@runtime_checkable
class ModellQuelle(Protocol):
    """Was Prüfer, Einlernen und Sitzung vom Modell brauchen (StimmModell, in Tests ein Ersatz): ob es geladen ist und den Rechner."""

    @property
    def bereit(self) -> bool: ...

    async def get(self) -> Rechner | None: ...


class Embedder:
    """Rechnet aus 16-Bit-PCM (mono) einen normierten Abdruck. Blockiert: im Thread aufrufen. Mehrere Threads rechnen nacheinander."""

    def __init__(self, pfad: Path | None = None, threads: int = THREADS, extraktor: object | None = None):
        if extraktor is None:
            import sherpa_onnx

            konfig = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(pfad or modell_pfad()), num_threads=threads)
            extraktor = sherpa_onnx.SpeakerEmbeddingExtractor(konfig)
        if extraktor.dim != DIM:
            raise ValueError(f"Modell liefert {extraktor.dim} statt {DIM} Werte")
        self._extraktor = extraktor
        self._sperre = threading.Lock()

    def embed(self, pcm: bytes, sample_rate: int) -> np.ndarray:
        with self._sperre:
            strom = self._extraktor.create_stream()
            strom.accept_waveform(sample_rate=sample_rate, waveform=pcm_in_float(pcm))
            strom.input_finished()
            roh = np.array(self._extraktor.compute(strom), dtype=np.float32)
        if roh.shape != (DIM,) or not np.all(np.isfinite(roh)) or not float(np.linalg.norm(roh)) > 0:
            raise ValueError("Das Modell lieferte keinen gültigen Abdruck (NaN, unendlich, Nullvektor oder falsche Länge)")
        return normalisieren(roh)


class StimmModell:
    """Lädt das Modell einmal je Prozess (Download beim ersten Mal, Prüfsumme auch für eine schon vorhandene Datei). get liefert den
    Embedder oder None; dann neuer Versuch nach NEUER_VERSUCH_SECS. Wirft nie."""

    def __init__(self, pfad: Path | None = None, sha256: str = MODELL_SHA256, uhr: Callable[[], float] = time.monotonic):
        self._pfad = pfad
        self._sha256 = sha256
        self._uhr = uhr
        self._embedder: Embedder | None = None
        self._gescheitert_um: float | None = None
        self._fehlversuche = 0
        self._sperre = asyncio.Lock()

    @property
    def pfad(self) -> Path:
        return self._pfad or modell_pfad()

    @property
    def bereit(self) -> bool:
        return self._embedder is not None

    @property
    def gescheitert(self) -> bool:
        """Der letzte Ladeversuch ging schief (und es gibt noch keinen Rechner)."""
        return self._embedder is None and self._gescheitert_um is not None

    def _wartet(self) -> bool:
        if self._gescheitert_um is None:
            return False
        warte = WARTEZEITEN[min(max(self._fehlversuche, 1), len(WARTEZEITEN)) - 1]
        return self._uhr() - self._gescheitert_um < warte

    async def get(self) -> Embedder | None:
        if self._embedder or self._wartet():
            return self._embedder
        async with self._sperre:
            if self._embedder is None and not self._wartet():
                await self._laden()
        return self._embedder

    async def _laden(self) -> None:
        pfad = self.pfad
        try:
            if not pfad.is_file():
                await herunterladen(pfad, sha256=self._sha256)
            elif await asyncio.to_thread(datei_sha256, pfad) != self._sha256:
                if _im_cache_ordner(pfad):
                    pfad.unlink()  # beschädigt oder ausgetauscht: beim nächsten Versuch neu laden
                # Ein Pfad aus WAMO_STIMME_MODELL gehört dem Betreiber: nie löschen
                raise ValueError("Prüfsumme der Modelldatei stimmt nicht")
            self._embedder = await asyncio.to_thread(Embedder, pfad)
            self._gescheitert_um = None
            self._fehlversuche = 0
            logger.info("Stimmabdruck: Modell {} geladen", pfad.name)
        except Exception as e:  # die Stimmprüfung ist dann nicht bereit, das Gespräch läuft weiter
            self._gescheitert_um = self._uhr()
            self._fehlversuche += 1
            logger.warning("Stimmabdruck: Modell nicht verfügbar ({}: {})", type(e).__name__, e)


def _im_cache_ordner(pfad: Path) -> bool:
    """Liegt die Datei im Cache-Ordner des Dienstes? Nur dort darf der Kern sie löschen."""
    try:
        return pfad.resolve().parent == cache_ordner().resolve()
    except OSError:
        return False


def datei_sha256(pfad: Path) -> str:
    summe = hashlib.sha256()
    with pfad.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            summe.update(block)
    return summe.hexdigest()


async def herunterladen(
    pfad: Path, url: str = MODELL_URL, sha256: str = MODELL_SHA256, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Lädt nach <pfad>.<Prozessnummer>.part, prüft die Summe und benennt erst dann um. Höchstens MODELL_MAX_BYTES und GESAMT_FRIST_SECS
    (sonst ValueError oder TimeoutError). Bei jedem Fehler bleibt nichts liegen, gelöscht wird nur die eigene Teildatei."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    teil = pfad.with_name(f"{pfad.name}.{os.getpid()}.part")
    logger.info("Stimmabdruck: lade Modell von {}", url)
    try:
        await asyncio.wait_for(_laden_in_teildatei(teil, url, sha256, transport), GESAMT_FRIST_SECS)
        teil.replace(pfad)
    finally:
        teil.unlink(missing_ok=True)


async def _laden_in_teildatei(teil: Path, url: str, sha256: str, transport: httpx.AsyncBaseTransport | None) -> None:
    summe = hashlib.sha256()
    gesamt = 0
    zeit = httpx.Timeout(LESEN_SECS, connect=VERBINDUNG_SECS)
    async with httpx.AsyncClient(follow_redirects=True, timeout=zeit, transport=transport) as client, client.stream("GET", url) as r:
        r.raise_for_status()
        angekuendigt = r.headers.get("content-length", "")
        if angekuendigt.isdigit() and int(angekuendigt) > MODELL_MAX_BYTES:
            raise ValueError("Das Modell ist größer als erlaubt")
        with teil.open("wb") as f:
            async for block in r.aiter_bytes(1 << 20):
                gesamt += len(block)
                if gesamt > MODELL_MAX_BYTES:
                    raise ValueError("Das Modell ist größer als erlaubt")
                summe.update(block)
                f.write(block)
    if summe.hexdigest() != sha256:
        raise ValueError("Prüfsumme des heruntergeladenen Modells stimmt nicht")


def pcm_in_float(pcm: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def normalisieren(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


def kosinus(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(normalisieren(a), normalisieren(b)))


def mittelpunkt(abdruecke: list[np.ndarray]) -> tuple[np.ndarray, float]:
    """Mittel der Abdrücke (normiert) und wie nah sie im Schnitt daran liegen (0 bis 1)."""
    mitte = normalisieren(np.mean(np.stack([normalisieren(e) for e in abdruecke]), axis=0))
    return mitte, float(np.mean([kosinus(e, mitte) for e in abdruecke]))


def dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return 20 * float(np.log10(rms / 32768)) if rms > 0 else -120.0


def ohne_pausen(pcm: bytes, sample_rate: int, schwelle_dbfs: float = SPRACHE_DBFS, pause_secs: float = PAUSE_SECS) -> bytes:
    """Der Ton ohne Pausen über pause_secs: Eine Pause ist eine Folge von 20-ms-Blöcken, die nicht lauter als schwelle_dbfs sind. Kürzere
    Pausen, leise Stellen mitten in der Sprache und kurze Ränder bleiben, wie in einer Äußerung beim Prüfen. Ohne einen lauten Block: nichts."""
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16)
    groesse = max(1, int(sample_rate * BLOCK_SECS))
    bloecke = [samples[i : i + groesse] for i in range(0, len(samples), groesse)]
    laut = [dbfs(b) > schwelle_dbfs for b in bloecke]
    if not any(laut):
        return b""
    behalten: list[np.ndarray] = []
    i = 0
    while i < len(bloecke):
        j = i + 1
        while j < len(bloecke) and laut[j] == laut[i]:
            j += 1
        lauf = bloecke[i:j]
        if laut[i] or sum(len(b) for b in lauf) <= pause_secs * sample_rate:
            behalten.extend(lauf)
        i = j
    return np.concatenate(behalten).tobytes()


def einlern_stuecke(pcm: bytes, sample_rate: int, stueck_secs: float = STUECK_SECS) -> list[bytes]:
    """Teilt Sprache (ohne lange Pausen) in gleich lange Stücke; ein kurzer Rest fällt weg."""
    groesse = int(sample_rate * stueck_secs) * 2
    return [pcm[i : i + groesse] for i in range(0, len(pcm) - groesse + 1, groesse)]


def schwelle_einlernen(abdruecke: list[np.ndarray]) -> tuple[float | None, float | None]:
    """Persönliche Schwelle für kurze Äußerungen aus den Abdrücken der Einlernstücke: je Stück der Kosinus gegen den Mittelpunkt der übrigen
    (leave-one-out, so ähnlich klingt ein Stück von 1,5 s dieser Person zu ihrem Abdruck), davon das SCHWELLE_QUANTIL-Quantil minus
    SCHWELLE_ABSTAND, begrenzt auf SCHWELLE_MIN bis SCHWELLE_MAX. Ergebnis (Schwelle, Quantil), mit weniger als zwei Stücken (None, None)."""
    if len(abdruecke) < 2:
        return None, None
    normiert = np.stack([normalisieren(np.asarray(e, dtype=np.float64)) for e in abdruecke])
    summe = normiert.sum(axis=0)
    werte = [kosinus(normiert[i], summe - normiert[i]) for i in range(len(normiert))]
    quantil = float(np.quantile(werte, SCHWELLE_QUANTIL))
    return float(min(max(quantil - SCHWELLE_ABSTAND, SCHWELLE_MIN), SCHWELLE_MAX)), quantil


def als_vektor(v: np.ndarray) -> str:
    """pgvector-Text, zum Beispiel "[0.1,-0.2,...]"."""
    return "[" + ",".join(f"{x:.6f}" for x in v.tolist()) + "]"


def aus_vektor(wert: object) -> np.ndarray | None:
    """Liest den Abdruck aus der Datenbank (pgvector kommt als Text oder Liste). Falsche Länge, Zahlen mit Fehler oder ein Nullvektor
    ergeben None."""
    try:
        if isinstance(wert, str):
            wert = [float(x) for x in wert.strip("[] ").split(",") if x.strip()]
        if not isinstance(wert, list) or len(wert) != DIM:
            return None
        v = np.array(wert, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(v)) or not float(np.linalg.norm(v)) > 0:
        return None
    return normalisieren(v)


MODELL = StimmModell()  # genau einmal je Prozess, für alle Sitzungen und Profile
