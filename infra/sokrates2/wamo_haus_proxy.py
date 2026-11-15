#!/usr/bin/python3 -I
"""Proxy für Entwicklungsaufträge mit Hausmodellen (wamo-haus-proxy, Paket P6a, docs/ausrollen-neue-nutzer.md 4.7).

Claude Code in der Auftrags-Sandbox spricht mit ANTHROPIC_BASE_URL=http://127.0.0.1:18090 hierher. Der Proxy reicht genau zwei Wege an das
zentrale LiteLLM weiter (Anthropic-kompatibel, /v1/messages) und setzt dabei den eigenen Schlüssel für LiteLLM ein. Den Schlüssel kennt nur
der Proxy (systemd-Credential litellm.key), nie die Sandbox, nie geheim.env. Hausregel: Modelle nur über LiteLLM, nie direkt an Knoten-IPs.

Was durchgeht (alles andere wird abgewiesen, ohne eine Verbindung nach draußen aufzubauen):
  * POST /v1/messages und POST /v1/messages/count_tokens, als Query nur "beta=true" (Claude Code hängt sie an).
  * Ein Auftragstoken in x-api-key oder Authorization: Bearer, Form wh1-<job>-<64 Hexzeichen>. Der Dispatcher legt je Lauf
    <auftraege>/<job>.json an ({"v": 1, "job", "hash" = SHA-256 des Tokens, "profil", "bis", "max_token"}) und löscht sie am Laufende.
    Geprüft werden Form, Datei (kein Link, klein, gültiges JSON), Hash (zeitkonstant), Frist bis.
  * Ein Körper mit Content-Length (kein Transfer-Encoding) bis KOERPER_MAX, als JSON-Objekt nur mit Feldern aus FELDER_ERLAUBT (keine
    Steuerfelder von LiteLLM wie fallbacks, api_base oder mock_response), model aus der festen Liste MODELLE; metadata behält nur user_id,
    max_tokens wird auf MAX_AUSGABE_TOKEN gekürzt. Der Körper geht neu geschrieben weiter.
  * Höchstens PARALLEL_MAX Anfragen gleichzeitig (damit die Gespräche auf LiteLLM nicht leiden); wer länger als WARTE_S wartet, bekommt 429.
    Der Körper wird erst gelesen, wenn ein Platz frei ist. Offene Verbindungen höchstens VERBINDUNGEN_MAX, je Auftrag VERBINDUNGEN_JE_AUFTRAG.
  * Token-Budget je Lauf (max_token aus der Datei des Dispatchers; jeder Lauf hat ein eigenes Token), je Profil und Tag (PROFIL_TAG_TOKEN_MAX) und je Tag für alle
    Aufträge (TAG_TOKEN_MAX); erschöpft heißt 403.
Weitergereicht werden nur die Kopfzeilen anthropic-version, anthropic-beta und accept; die Antwort (auch Streaming, SSE) geht gestückelt
zurück. Eine Antwort von LiteLLM ab Status 400 geht nie wörtlich zurück, nur als eigener Fehler mit demselben Status. Gezählt werden
input_tokens (mit Cache-Anteilen) und output_tokens aus der Antwort, gebucht in verbrauch.jsonl (Zustandsordner). Gebucht wird alles, was an
LiteLLM ging: bei Abbruch, Zeitgrenze oder fehlendem usage mindestens eine Schätzung (Körper durch 3, dazu max_tokens bzw. Antwort durch 4).
Im Protokoll (stderr, Journal): Ergebnis, Auftrag, Weg, Modell, Status, Token, Dauer. Nie ein Inhalt, nie ein Token, nie der Schlüssel.

Aufruf (durch wamo-haus-proxy.service):
  python3 -I wamo_haus_proxy.py --listen 127.0.0.1:18090 --ziel http://192.168.178.75:4000 --modelle qwen3.6-35b \
      --auftraege /run/wamo-haus --verbrauch /var/lib/wamo-haus-proxy/verbrauch.jsonl --schluessel-datei "$CREDENTIALS_DIRECTORY/litellm.key"
Nur Standardbibliothek.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

KOPF_MAX = 16 * 1024
KOPF_ZEIT_S = 10.0
KOERPER_MAX = 8 * 1024 * 1024
KOERPER_ZEIT_S = 60.0
WEGE = frozenset({"/v1/messages", "/v1/messages/count_tokens"})
QUERY_ERLAUBT = frozenset({"", "beta=true"})
WEITERGEREICHT = ("anthropic-version", "anthropic-beta", "accept")
WERT_RE = re.compile(r"[\x20-\x7e]{1,512}")
KOPF_WERT_RE = re.compile(r"[\x20-\x7e]{1,2048}")  # weitergereichte Kopfzeilen; ungültige fallen weg, statt die Anfrage zu kippen
GROESSE_RE = re.compile(rb"[0-9a-fA-F]{1,8}")
COUNT_TOKENS = "/v1/messages/count_tokens"
TOKEN_RE = re.compile(r"wh1-([0-9a-f]{16,32})-[0-9a-f]{64}")
PROFIL_RE = re.compile(r"[0-9a-f]{8}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
MODELL_RE = re.compile(r"[a-z0-9][a-z0-9.:-]{1,63}")
DATEI_MAX = 4096
PARALLEL_MAX = 2
WARTE_S = 60.0
VERBINDEN_ZEIT_S = 10.0
ANTWORT_KOPF_MAX = 64 * 1024
ANTWORT_KOPF_ZEIT_S = 600.0  # ohne Streaming kommt der Kopf erst mit der fertigen Antwort (LiteLLM bricht nach 120 s ab)
LEER_ZEIT_S = 300.0
GESAMT_ZEIT_S = 1800.0
ANTWORT_MAX = 64 * 1024 * 1024
JSON_ZAEHL_MAX = 4 * 1024 * 1024  # eine Antwort ohne Streaming wird bis zu dieser Größe für die Zählung gelesen
TAG_TOKEN_MAX = 30_000_000
PROFIL_TAG_TOKEN_MAX = 10_000_000
VERBINDUNGEN_MAX = 16  # offene Verbindungen insgesamt (der Körper wird erst nach dem Platz gelesen, aber Köpfe kosten auch Speicher)
VERBINDUNGEN_JE_AUFTRAG = 4
MAX_AUSGABE_TOKEN = 32768  # max_tokens wird darauf gekürzt (Kontext von qwen3.6:35b im Ollama des Gateways: 32768)
# Oberste Felder einer Anfrage: genau die, die Claude Code schickt (gemessen mit 2.1.303), plus die üblichen der Messages-API. Felder, mit
# denen LiteLLM selbst gesteuert wird (fallbacks, api_base, extra_headers, mock_response, metadata.tags, litellm_*), kommen nie durch.
FELDER_ERLAUBT = frozenset({"model", "messages", "system", "max_tokens", "stream", "temperature", "top_p", "top_k", "stop_sequences",
                            "tools", "tool_choice", "thinking", "metadata", "context_management", "output_config"})
VERBRAUCH_LESEN_MAX = 16 * 1024 * 1024
CHUNK = 65536
GRUENDE = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
           411: "Length Required", 413: "Payload Too Large", 429: "Too Many Requests", 431: "Request Header Fields Too Large",
           502: "Bad Gateway", 504: "Gateway Timeout"}
FEHLERART = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error", 404: "not_found_error",
             405: "invalid_request_error", 411: "invalid_request_error", 413: "request_too_large", 429: "rate_limit_error",
             431: "invalid_request_error", 502: "api_error", 504: "api_error"}


class Abweisung(Exception):
    def __init__(self, status: int, ergebnis: str, text: str, kopf: dict[str, str] | None = None):
        super().__init__(text)
        self.status, self.ergebnis, self.text, self.kopf = status, ergebnis, text, kopf or {}


@dataclass(frozen=True)
class Ziel:
    host: str
    port: int
    basis: str  # Pfad vor /v1/..., meist leer

    @staticmethod
    def aus_url(url: str) -> "Ziel":
        teile = urlsplit(url)
        if teile.scheme != "http" or not teile.hostname or teile.query or teile.fragment or teile.username or teile.password:
            raise ValueError("Ziel muss http://host:port sein, ohne Zugangsdaten, Query und Fragment")
        return Ziel(teile.hostname, teile.port or 80, teile.path.rstrip("/"))


@dataclass
class Auftrag:
    job: str
    profil: str
    bis: int
    max_token: int
    lauf: str  # <job>-<12 Hexzeichen des Hashs>: jeder Lauf hat ein eigenes Token und damit ein eigenes Budget (max_token je Lauf)


@dataclass
class Verbrauch:
    """Token je Lauf, je Profil und Tag und je Tag; gebucht in einer JSON-Zeilen-Datei (nur anhängen), beim Start daraus wiederhergestellt."""
    pfad: Path | None
    je_lauf: dict[str, int] = field(default_factory=dict)
    je_tag: dict[str, int] = field(default_factory=dict)
    je_profil_tag: dict[tuple[str, str], int] = field(default_factory=dict)

    @staticmethod
    def tag(zeit: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(zeit))

    def laden(self) -> None:
        if self.pfad is None or not self.pfad.is_file():
            return
        with open(self.pfad, "rb") as f:
            f.seek(0, os.SEEK_END)
            groesse = f.tell()
            f.seek(max(0, groesse - VERBRAUCH_LESEN_MAX))
            daten = f.read()
        for zeile in daten.splitlines():
            try:
                e = json.loads(zeile)
                lauf, tag, n = e.get("lauf") or e["job"], e["tag"], int(e["ein"]) + int(e["aus"])
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
                continue  # auch die erste, angeschnittene Zeile
            if isinstance(lauf, str) and isinstance(tag, str) and n > 0:
                self._addieren(lauf, tag, e.get("profil"), n)

    def _addieren(self, lauf: str, tag: str, profil: object, n: int) -> None:
        self.je_lauf[lauf] = self.je_lauf.get(lauf, 0) + n
        self.je_tag[tag] = self.je_tag.get(tag, 0) + n
        if isinstance(profil, str):
            self.je_profil_tag[(profil, tag)] = self.je_profil_tag.get((profil, tag), 0) + n

    def buchen(self, eintrag: dict) -> None:
        self._addieren(eintrag["lauf"], eintrag["tag"], eintrag.get("profil"), int(eintrag["ein"]) + int(eintrag["aus"]))
        if self.pfad is not None:
            with open(self.pfad, "a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=True, separators=(",", ":")) + "\n")


class Zaehler:
    """Liest Token aus der Antwort: bei SSE die Ereignisse message_start (Eingabe) und message_delta (Ausgabe, kumuliert), sonst das Feld
    usage der JSON-Antwort. Hält nur angefangene Zeilen bzw. höchstens JSON_ZAEHL_MAX Bytes."""

    def __init__(self, sse: bool):
        self.sse, self.ein, self.aus, self.bytes, self._rest, self._json, self._voll = sse, 0, 0, 0, b"", bytearray(), False

    @staticmethod
    def _zahl(wert: object) -> int:
        return wert if type(wert) is int and 0 <= wert <= 10**9 else 0

    @classmethod
    def _eingabe(cls, u: dict) -> int:
        return sum(cls._zahl(u.get(k)) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))

    def futter(self, daten: bytes) -> None:
        self.bytes += len(daten)
        if not self.sse:
            if not self._voll and len(self._json) + len(daten) <= JSON_ZAEHL_MAX:
                self._json += daten
            else:
                self._voll = True  # danach nichts mehr sammeln: zerstückeltes JSON zählte sonst falsch
            return
        zeilen = (self._rest + daten).split(b"\n")
        self._rest = zeilen.pop()[-ANTWORT_KOPF_MAX:]
        for z in zeilen:
            if z.startswith(b"data:"):
                self._ereignis(z[5:].strip())

    def _ereignis(self, roh: bytes) -> None:
        try:
            e = json.loads(roh)
        except (ValueError, RecursionError):
            return
        if not isinstance(e, dict):
            return
        if e.get("type") == "message_start" and isinstance(e.get("message"), dict) and isinstance(e["message"].get("usage"), dict):
            self.ein = max(self.ein, self._eingabe(e["message"]["usage"]))
            self.aus = max(self.aus, self._zahl(e["message"]["usage"].get("output_tokens")))
        elif e.get("type") == "message_delta" and isinstance(e.get("usage"), dict):
            u = e["usage"]
            self.aus = max(self.aus, self._zahl(u.get("output_tokens")))
            self.ein = max(self.ein, self._eingabe(u))

    def ende(self) -> None:
        if self.sse:
            if self._rest.startswith(b"data:"):
                self._ereignis(self._rest[5:].strip())
            return
        if self._voll:
            return
        try:
            u = json.loads(bytes(self._json)).get("usage")
        except (ValueError, AttributeError, RecursionError):
            return
        if isinstance(u, dict):
            self.ein, self.aus = self._eingabe(u), self._zahl(u.get("output_tokens"))


def _fehler_json(status: int, text: str) -> bytes:
    return json.dumps({"type": "error", "error": {"type": FEHLERART.get(status, "api_error"), "message": text}},
                      ensure_ascii=False).encode("utf-8")


class Proxy:
    def __init__(self, ziel: Ziel, schluessel: str, modelle: frozenset[str], auftraege: Path, verbrauch: Verbrauch,
                 parallel_max: int = PARALLEL_MAX, tag_token_max: int = TAG_TOKEN_MAX, warte_s: float = WARTE_S,
                 protokoll: Callable[[str], None] | None = None, uhr: Callable[[], float] = time.time,
                 profil_tag_token_max: int = PROFIL_TAG_TOKEN_MAX, verbindungen_max: int = VERBINDUNGEN_MAX):
        if not schluessel or not WERT_RE.fullmatch(schluessel):
            raise ValueError("Schlüssel für LiteLLM fehlt oder hat unerlaubte Zeichen")
        if not modelle or any(not MODELL_RE.fullmatch(m) for m in modelle):
            raise ValueError("Modellliste leer oder ungültig")
        self.ziel, self._schluessel, self.modelle, self.auftraege, self.verbrauch = ziel, schluessel, modelle, auftraege, verbrauch
        self.tag_token_max, self.profil_tag_token_max, self.warte_s = tag_token_max, profil_tag_token_max, warte_s
        self._frei = asyncio.Semaphore(parallel_max)
        self._verbindungen_max = verbindungen_max
        self._offen = 0
        self._offen_je_auftrag: dict[str, int] = {}
        self._protokoll = protokoll or (lambda z: print(z, file=sys.stderr, flush=True))
        self._uhr = uhr

    def __repr__(self) -> str:  # nie der Schlüssel
        return f"Proxy(ziel={self.ziel.host}:{self.ziel.port}, modelle={sorted(self.modelle)})"

    def _log(self, ergebnis: str, **felder) -> None:
        teile = " ".join(f"{k}={v}" for k, v in felder.items() if v not in (None, ""))
        self._protokoll(f"haus-proxy {ergebnis} {teile}".rstrip())

    # ------------------------------------------------------------ Auftragstoken
    def auftrag_pruefen(self, token: str | None) -> Auftrag:
        m = TOKEN_RE.fullmatch(token or "")
        if m is None:
            raise Abweisung(401, "token_form", "Auftragstoken fehlt oder hat nicht die erwartete Form")
        job = m[1]
        try:
            fd = os.open(self.auftraege / f"{job}.json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        except OSError:
            raise Abweisung(401, "token_unbekannt", "Auftragstoken unbekannt oder abgelaufen") from None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > DATEI_MAX:
                raise Abweisung(401, "token_datei", "Auftragstoken unbekannt oder abgelaufen")
            roh = os.read(fd, DATEI_MAX + 1)
        finally:
            os.close(fd)
        try:
            d = json.loads(roh)
        except ValueError:
            raise Abweisung(401, "token_datei", "Auftragstoken unbekannt oder abgelaufen") from None
        if (not isinstance(d, dict) or d.get("v") != 1 or d.get("job") != job or not isinstance(d.get("hash"), str)
                or not HASH_RE.fullmatch(d["hash"]) or not isinstance(d.get("profil"), str) or not PROFIL_RE.fullmatch(d["profil"])
                or type(d.get("bis")) is not int or type(d.get("max_token")) is not int or d["max_token"] <= 0):
            raise Abweisung(401, "token_datei", "Auftragstoken unbekannt oder abgelaufen")
        if not hmac.compare_digest(hashlib.sha256(token.encode("ascii")).hexdigest(), d["hash"]):
            raise Abweisung(401, "token_falsch", "Auftragstoken unbekannt oder abgelaufen")
        if d["bis"] < self._uhr():
            raise Abweisung(401, "token_abgelaufen", "Auftragstoken unbekannt oder abgelaufen")
        return Auftrag(job, d["profil"], d["bis"], d["max_token"], f"{job}-{d['hash'][:12]}")

    def budget_pruefen(self, a: Auftrag) -> None:
        jetzt = self._uhr()
        if a.bis < jetzt:  # auch nach dem Warten auf einen Platz
            raise Abweisung(401, "token_abgelaufen", "Auftragstoken unbekannt oder abgelaufen")
        tag = Verbrauch.tag(jetzt)
        if self.verbrauch.je_lauf.get(a.lauf, 0) >= a.max_token:
            raise Abweisung(403, "budget_lauf", "Token-Budget dieses Laufs ist erschöpft")
        if self.verbrauch.je_profil_tag.get((a.profil, tag), 0) >= self.profil_tag_token_max:
            raise Abweisung(403, "budget_profil", "Token-Budget des Tages für dieses Profil ist erschöpft")
        if self.verbrauch.je_tag.get(tag, 0) >= self.tag_token_max:
            raise Abweisung(403, "budget_tag", "Token-Budget des Tages für Hausmodelle ist erschöpft")

    # ------------------------------------------------------------ Anfrage lesen
    @staticmethod
    async def _kopf_lesen(r: asyncio.StreamReader) -> tuple[str, str, dict[str, str]]:
        try:
            roh = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), KOPF_ZEIT_S)
        except asyncio.LimitOverrunError:
            raise Abweisung(431, "kopf_zu_gross", "Kopfzeilen zu groß") from None
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            raise Abweisung(400, "kopf_ungueltig", "Anfrage unvollständig") from None
        if len(roh) > KOPF_MAX:
            raise Abweisung(431, "kopf_zu_gross", "Kopfzeilen zu groß")
        try:
            text = roh.decode("ascii")
        except UnicodeDecodeError:
            raise Abweisung(400, "kopf_ungueltig", "Kopfzeilen nur in ASCII") from None
        zeilen = text[:-4].split("\r\n")
        teile = zeilen[0].split(" ")
        if len(teile) != 3 or teile[2] != "HTTP/1.1":
            raise Abweisung(400, "kopf_ungueltig", "Anfragezeile ungültig")
        kopf: dict[str, str] = {}
        for z in zeilen[1:]:
            name, sep, wert = z.partition(":")
            name = name.strip().lower()
            if not sep or not name or name != z.split(":", 1)[0].lower() or not re.fullmatch(r"[a-z0-9-]{1,64}", name):
                raise Abweisung(400, "kopf_ungueltig", "Kopfzeile ungültig")
            if name in kopf:
                raise Abweisung(400, "kopf_doppelt", "Kopfzeile doppelt")
            kopf[name] = wert.strip()
        return teile[0], teile[1], kopf

    def _anfrage_pruefen(self, methode: str, ziel: str, kopf: dict[str, str]) -> tuple[str, Auftrag, int]:
        weg, _, query = ziel.partition("?")
        if weg not in WEGE or query not in QUERY_ERLAUBT:
            raise Abweisung(404, "weg", "Weg nicht erlaubt")
        if methode != "POST":
            raise Abweisung(405, "methode", "nur POST", {"Allow": "POST"})
        if "transfer-encoding" in kopf:
            raise Abweisung(411, "laenge", "nur Content-Length, kein Transfer-Encoding")
        laenge = kopf.get("content-length", "")
        if not re.fullmatch(r"[0-9]{1,9}", laenge):
            raise Abweisung(411, "laenge", "Content-Length fehlt")
        if int(laenge) > KOERPER_MAX:
            raise Abweisung(413, "zu_gross", "Anfrage zu groß")
        token = kopf.get("x-api-key")
        if token is None and kopf.get("authorization", "").startswith("Bearer "):
            token = kopf["authorization"][len("Bearer "):].strip()
        auftrag = self.auftrag_pruefen(token)
        for name in WEITERGEREICHT:
            if name in kopf and not KOPF_WERT_RE.fullmatch(kopf[name]):
                del kopf[name]
        return ziel, auftrag, int(laenge)

    def _koerper_pruefen(self, koerper: bytes, weg: str = "/v1/messages") -> tuple[str, bytes, int]:
        """Prüft den Körper und baut ihn neu: nur Felder aus FELDER_ERLAUBT (sonst 400), Modell aus der Liste, metadata nur mit
        user_id, max_tokens auf MAX_AUSGABE_TOKEN gekürzt. Liefert (Modell, neuer Körper, max_tokens für die Schätzung)."""
        try:
            d = json.loads(koerper)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise Abweisung(400, "json", "Körper ist kein JSON") from None
        if not isinstance(d, dict):
            raise Abweisung(400, "json", "Körper ist kein JSON-Objekt")
        fremd = set(d) - FELDER_ERLAUBT
        if fremd:
            raise Abweisung(400, "feld", "Feld nicht erlaubt: " + ", ".join(sorted(f[:40] for f in fremd)[:5]))
        modell = d.get("model")
        if not isinstance(modell, str) or modell not in self.modelle:
            raise Abweisung(400, "modell", f"Modell nicht erlaubt (erlaubt: {', '.join(sorted(self.modelle))})")
        if "metadata" in d:
            meta = d["metadata"]
            if not isinstance(meta, dict):
                raise Abweisung(400, "feld", "metadata muss ein Objekt sein")
            d["metadata"] = {"user_id": meta["user_id"]} if isinstance(meta.get("user_id"), str) else {}
        if "max_tokens" not in d and weg != COUNT_TOKENS:
            d["max_tokens"] = MAX_AUSGABE_TOKEN  # nie die Grenze von LiteLLM oder Ollama
        max_tokens = d.get("max_tokens", 0)
        if "max_tokens" in d:
            if type(max_tokens) is not int or max_tokens < 1:
                raise Abweisung(400, "feld", "max_tokens ungültig")
            max_tokens = d["max_tokens"] = min(max_tokens, MAX_AUSGABE_TOKEN)
        return modell, json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), max_tokens

    # ------------------------------------------------------------ Bedienen
    async def bediene(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        """Eine Anfrage je Verbindung. Gebucht wird alles, was an LiteLLM ging, auch wenn der Client mittendrin abbricht oder die Antwort
        scheitert: was gezählt wurde, mindestens aber eine Schätzung (Körper durch 3 plus max_tokens bei Abbruch)."""
        beginn = time.monotonic()
        felder: dict = {}
        if self._offen >= self._verbindungen_max:
            self._log("zu_viele_verbindungen")
            await self._antwort(w, 429, "zu viele offene Verbindungen", {"Retry-After": "5"})
            return await self._schliesse(w)
        self._offen += 1
        job = None
        lauf: dict = {}
        try:
            methode, ziel, kopf = await self._kopf_lesen(r)
            ziel, auftrag, laenge = self._anfrage_pruefen(methode, ziel, kopf)
            job = auftrag.job
            felder.update(job=job, weg=ziel.partition("?")[0])
            self._offen_je_auftrag[job] = self._offen_je_auftrag.get(job, 0) + 1
            if self._offen_je_auftrag[job] > VERBINDUNGEN_JE_AUFTRAG:
                raise Abweisung(429, "zu_viele_auftrag", "zu viele Anfragen dieses Auftrags gleichzeitig", {"Retry-After": "5"})
            self.budget_pruefen(auftrag)
            try:  # erst den Platz, dann den Körper: wartende Anfragen halten keinen Körper im Speicher
                await asyncio.wait_for(self._frei.acquire(), self.warte_s)
            except asyncio.TimeoutError:
                raise Abweisung(429, "zu_viele", "Hausmodelle gerade ausgelastet", {"Retry-After": "10"}) from None
            try:
                self.budget_pruefen(auftrag)  # das Warten kann lang sein: Budget und Frist noch einmal
                try:
                    koerper = await asyncio.wait_for(r.readexactly(laenge), KOERPER_ZEIT_S)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
                    raise Abweisung(400, "koerper", "Körper unvollständig") from None
                lauf["weg"] = felder["weg"]
                felder["modell"], koerper, lauf["max_tokens"] = self._koerper_pruefen(koerper, felder["weg"])
                lauf["koerper"] = len(koerper)
                try:
                    await self._weiterreichen(ziel, kopf, koerper, w, lauf)
                finally:
                    if lauf.get("gesendet"):
                        self._buchen(auftrag, felder, lauf, beginn)
            finally:
                self._frei.release()
        except Abweisung as a:
            if not (a.ergebnis == "ziel_fehler" and lauf.get("gesendet")):  # gebucht und protokolliert ist das schon
                self._log(a.ergebnis, status=a.status, ms=int((time.monotonic() - beginn) * 1000), **felder)
            await self._antwort(w, a.status, a.text, a.kopf)
        except Exception as e:  # noqa: BLE001  nie ein Absturz des Proxys durch eine Anfrage, nie ein Inhalt im Protokoll
            self._log("fehler", art=type(e).__name__, **felder)
            if not lauf.get("kopf_gesendet"):
                await self._antwort(w, 502, "Proxy: Anfrage nicht ausführbar")
        finally:
            try:
                await self._schliesse(w)
            finally:  # erst nach dem Schließen frei: hängende Verbindungen zählen bis zuletzt mit
                self._offen -= 1
                if job is not None:
                    self._offen_je_auftrag[job] -= 1
                    if self._offen_je_auftrag[job] <= 0:
                        del self._offen_je_auftrag[job]

    @staticmethod
    def _menge(lauf: dict) -> tuple[int, int, bool]:
        """Token für die Buchung: gezählt, und wenn das nicht reicht, geschätzt (Rückgabe ein, aus, geschätzt)."""
        if lauf.get("weg") == COUNT_TOKENS:  # Zählen der Eingabe erzeugt nichts und kostet kein Budget
            return 0, 0, False
        z = lauf.get("zaehler")
        ein, aus = (z.ein, z.aus) if z is not None else (0, 0)
        status = lauf.get("status") or 0
        if not lauf.get("vollstaendig"):  # Abbruch, Zeitgrenze, Fehler: LiteLLM rechnet womöglich weiter
            return max(ein, lauf.get("koerper", 0) // 3), max(aus, lauf.get("max_tokens") or 0), True
        if 200 <= status < 300 and ein + aus == 0:  # vollständig, aber ohne usage in der Antwort
            return lauf.get("koerper", 0) // 3, (z.bytes if z is not None else 0) // 4, True
        return ein, aus, False

    def _buchen(self, auftrag: Auftrag, felder: dict, lauf: dict, beginn: float) -> None:
        ms = int((time.monotonic() - beginn) * 1000)
        jetzt = self._uhr()
        ein, aus, geschaetzt = self._menge(lauf)
        status = lauf.get("status") or 0
        try:
            self.verbrauch.buchen({"zeit": int(jetzt), "tag": Verbrauch.tag(jetzt), "job": auftrag.job, "lauf": auftrag.lauf,
                                   "profil": auftrag.profil,
                                   "weg": felder.get("weg"), "modell": felder.get("modell"), "status": status, "ein": ein, "aus": aus,
                                   "geschaetzt": geschaetzt, "ms": ms})
        except OSError as e:
            self._log("buchung_fehlt", art=type(e).__name__, job=auftrag.job)
        if not lauf.get("vollstaendig"):
            ergebnis = "abbruch"
        else:
            ergebnis = "ok" if 200 <= status < 300 else "ziel_fehler"
        self._log(ergebnis, status=status, ein=ein, aus=aus, geschaetzt="ja" if geschaetzt else "", ms=ms, **felder)

    async def _weiterreichen(self, ziel: str, kopf: dict[str, str], koerper: bytes, w: asyncio.StreamWriter, lauf: dict) -> None:
        """Reicht die Anfrage an LiteLLM und die Antwort zurück. lauf hält fest: gesendet, status, zaehler, vollstaendig. Eine Antwort ab
        Status 400 geht nie wörtlich zurück (sie kann Interna von LiteLLM nennen), sondern als eigener Fehler mit demselben Status."""
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(self.ziel.host, self.ziel.port), VERBINDEN_ZEIT_S)
        except (OSError, asyncio.TimeoutError):
            raise Abweisung(502, "ziel_nicht_erreichbar", "LiteLLM nicht erreichbar") from None
        try:
            zeilen = [f"POST {self.ziel.basis}{ziel} HTTP/1.1", f"Host: {self.ziel.host}:{self.ziel.port}",
                      f"Authorization: Bearer {self._schluessel}", "Content-Type: application/json",
                      f"Content-Length: {len(koerper)}", "Connection: close"]
            zeilen += [f"{n}: {kopf[n]}" for n in WEITERGEREICHT if n in kopf]
            uw.write(("\r\n".join(zeilen) + "\r\n\r\n").encode("ascii") + koerper)
            lauf["gesendet"] = True
            await uw.drain()
            try:
                roh = await asyncio.wait_for(ur.readuntil(b"\r\n\r\n"), ANTWORT_KOPF_ZEIT_S)
            except asyncio.TimeoutError:
                raise Abweisung(504, "ziel_zeit", "LiteLLM antwortet nicht") from None
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
                raise Abweisung(502, "ziel_antwort", "Antwort von LiteLLM ungültig") from None
            status, akopf = self._antwortkopf(roh)
            lauf["status"] = status
            if status >= 400:
                lauf["vollstaendig"] = True
                weiter = {"Retry-After": akopf["retry-after"]} if re.fullmatch(r"[0-9]{1,5}", akopf.get("retry-after", "")) else None
                raise Abweisung(status, "ziel_fehler", f"LiteLLM meldet Status {status}", weiter)
            art = akopf.get("content-type", "application/json")
            sse = art.startswith("text/event-stream")
            aus_kopf = [f"HTTP/1.1 {status} {GRUENDE.get(status, 'OK')}",
                        f"Content-Type: {art if WERT_RE.fullmatch(art) else 'application/octet-stream'}",
                        "Transfer-Encoding: chunked", "Connection: close", "Cache-Control: no-store"]
            w.write(("\r\n".join(aus_kopf) + "\r\n\r\n").encode("ascii"))
            lauf["kopf_gesendet"] = True
            lauf["zaehler"] = zaehler = Zaehler(sse)
            await self._koerper_kopieren(ur, akopf, w, zaehler)
            w.write(b"0\r\n\r\n")
            await asyncio.wait_for(w.drain(), LEER_ZEIT_S)
            zaehler.ende()
            lauf["vollstaendig"] = True
        finally:
            await self._schliesse(uw)

    @staticmethod
    def _antwortkopf(roh: bytes) -> tuple[int, dict[str, str]]:
        if len(roh) > ANTWORT_KOPF_MAX:
            raise Abweisung(502, "ziel_antwort", "Antwort von LiteLLM ungültig")
        zeilen = roh.decode("latin-1")[:-4].split("\r\n")
        m = re.fullmatch(r"HTTP/1\.[01] ([1-5][0-9]{2})(?: .*)?", zeilen[0])
        if m is None:
            raise Abweisung(502, "ziel_antwort", "Antwort von LiteLLM ungültig")
        kopf = {}
        for z in zeilen[1:]:
            name, _, wert = z.partition(":")
            kopf[name.strip().lower()] = wert.strip()
        return int(m[1]), kopf

    async def _koerper_kopieren(self, ur: asyncio.StreamReader, akopf: dict[str, str], w: asyncio.StreamWriter, zaehler: Zaehler) -> None:
        """Kopiert den Körper der Antwort gestückelt an den Client. Jede Lese- und Schreiboperation hat eine Frist (LEER_ZEIT_S, insgesamt
        GESAMT_ZEIT_S): ein Client, der nicht weiterliest, hält keinen Platz unbegrenzt. chunked wird streng gelesen (Größe nur Hex, CRLF
        nach jedem Stück), große Stücke in Teilen von CHUNK Bytes."""
        ende = time.monotonic() + GESAMT_ZEIT_S
        gesamt = 0

        async def frist(coro):
            rest = ende - time.monotonic()
            if rest <= 0:
                coro.close()
                raise asyncio.TimeoutError
            return await asyncio.wait_for(coro, min(LEER_ZEIT_S, rest))

        async def weiter(daten: bytes) -> None:
            nonlocal gesamt
            gesamt += len(daten)
            if gesamt > ANTWORT_MAX:
                raise ValueError("Antwort zu groß")
            zaehler.futter(daten)
            w.write(f"{len(daten):x}\r\n".encode("ascii") + daten + b"\r\n")
            await frist(w.drain())

        if "chunked" in akopf.get("transfer-encoding", "").lower():
            while True:
                zeile = (await frist(ur.readuntil(b"\r\n")))[:-2].split(b";", 1)[0].strip()
                if not GROESSE_RE.fullmatch(zeile):
                    raise ValueError("Stückgröße ungültig")
                groesse = int(zeile, 16)
                if groesse == 0:
                    while (await frist(ur.readuntil(b"\r\n"))) != b"\r\n":  # Trailer überspringen
                        pass
                    return
                if gesamt + groesse > ANTWORT_MAX:
                    raise ValueError("Antwort zu groß")
                while groesse > 0:
                    daten = await frist(ur.readexactly(min(CHUNK, groesse)))
                    groesse -= len(daten)
                    await weiter(daten)
                if await frist(ur.readexactly(2)) != b"\r\n":
                    raise ValueError("Stück ohne CRLF")
        elif re.fullmatch(r"[0-9]{1,10}", akopf.get("content-length", "")):
            rest = int(akopf["content-length"])
            while rest > 0:
                daten = await frist(ur.read(min(CHUNK, rest)))
                if not daten:
                    raise ConnectionError("Antwort zu kurz")
                rest -= len(daten)
                await weiter(daten)
        else:
            while daten := await frist(ur.read(CHUNK)):
                await weiter(daten)

    @staticmethod
    async def _antwort(w: asyncio.StreamWriter, status: int, text: str, kopf: dict[str, str] | None = None) -> None:
        koerper = _fehler_json(status, text)
        zeilen = [f"HTTP/1.1 {status} {GRUENDE.get(status, 'Error')}", "Content-Type: application/json",
                  f"Content-Length: {len(koerper)}", "Connection: close", "Cache-Control: no-store"]
        zeilen += [f"{n}: {v}" for n, v in (kopf or {}).items()]
        try:
            w.write(("\r\n".join(zeilen) + "\r\n\r\n").encode("ascii") + koerper)
            await asyncio.wait_for(w.drain(), 5)
        except (OSError, asyncio.TimeoutError):
            pass

    @staticmethod
    async def _schliesse(w: asyncio.StreamWriter) -> None:
        try:
            w.close()
            await asyncio.wait_for(w.wait_closed(), 5)
        except Exception:  # noqa: BLE001  hängt der Client: Verbindung hart abbrechen, damit nichts offen bleibt
            try:
                w.transport.abort()
            except Exception:  # noqa: BLE001
                pass


async def serve(proxy: Proxy, host: str, port: int) -> asyncio.AbstractServer:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("der Proxy lauscht nur auf Loopback")
    return await asyncio.start_server(proxy.bediene, host, port, limit=KOPF_MAX + 1024, backlog=64)


def schluessel_lesen(pfad: str) -> str:
    """Eine Zeile aus der Datei des Credentials; der Wert wird nie ausgegeben."""
    with open(pfad, encoding="utf-8") as f:
        wert = f.read(4096).strip()
    if not wert or "\n" in wert or not WERT_RE.fullmatch(wert):
        raise ValueError("Schlüsseldatei leer oder ungültig")
    return wert


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Proxy für Entwicklungsaufträge mit Hausmodellen")
    ap.add_argument("--listen", required=True, help="host:port auf Loopback")
    ap.add_argument("--ziel", required=True, help="http://host:port von LiteLLM")
    ap.add_argument("--modelle", required=True, help="erlaubte Modellnamen, durch Komma getrennt")
    ap.add_argument("--auftraege", required=True, help="Ordner mit den Tokendateien des Dispatchers")
    ap.add_argument("--verbrauch", required=True, help="Datei für die Buchung der Token (JSON-Zeilen)")
    ap.add_argument("--schluessel-datei", required=True, help="Datei mit dem Schlüssel für LiteLLM (systemd-Credential)")
    ap.add_argument("--parallel", type=int, default=PARALLEL_MAX)
    ap.add_argument("--tag-token-max", type=int, default=TAG_TOKEN_MAX)
    a = ap.parse_args(argv)
    host, _, port = a.listen.rpartition(":")
    try:
        ok_listen = ipaddress.ip_address(host).is_loopback and port.isdigit() and 1 <= int(port) <= 65535
    except ValueError:
        ok_listen = False
    if not ok_listen:
        print("haus-proxy: --listen muss eine Loopback-Adresse mit Port sein, etwa 127.0.0.1:18090", file=sys.stderr)
        return 2
    if not 1 <= a.parallel <= 8 or not 10_000 <= a.tag_token_max <= 1_000_000_000:
        print("haus-proxy: --parallel 1 bis 8, --tag-token-max 10000 bis 1000000000", file=sys.stderr)
        return 2
    verbrauch = Verbrauch(Path(a.verbrauch))
    try:
        verbrauch.laden()
    except OSError as e:
        print(f"haus-proxy: Verbrauchsdatei nicht lesbar ({type(e).__name__})", file=sys.stderr)
        return 2
    try:
        proxy = Proxy(Ziel.aus_url(a.ziel), schluessel_lesen(a.schluessel_datei),
                      frozenset(m.strip() for m in a.modelle.split(",") if m.strip()), Path(a.auftraege), verbrauch,
                      parallel_max=a.parallel, tag_token_max=a.tag_token_max)
    except (OSError, ValueError) as e:
        print(f"haus-proxy: Start abgebrochen ({type(e).__name__}: {e})", file=sys.stderr)
        return 2

    async def start() -> None:
        server = await serve(proxy, host, int(port))
        print(f"haus-proxy lauscht auf {a.listen}, Ziel {proxy.ziel.host}:{proxy.ziel.port}, Modelle {sorted(proxy.modelle)}, "
              f"parallel {a.parallel}", file=sys.stderr, flush=True)
        async with server:
            await server.serve_forever()

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
