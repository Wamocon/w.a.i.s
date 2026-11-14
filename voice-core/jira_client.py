"""REST-Client des Kerns für Jira Cloud: W.A.I.S. legt nach einer Freigabe User Stories an (jira_werkzeuge.py, jira_freigaben.py).

Angemeldet wird mit Basic-Auth, also Mailadresse und API-Token eines technischen Jira-Benutzers nur für W.A.I.S. (Rechte "Browse Projects" und
"Create Issues", Anleitung docs/jira-benutzer-einrichten.md). Der Lese-Zugang der Auftrags-Sandbox ist ein anderer Benutzer und bleibt unberührt.
Der Client kennt genau fünf Aufrufe der REST-Schnittstelle Version 3:

  GET  /rest/api/3/project/{key}                Name und Vorgangstypen des Projekts (Kennung des Typs Story)
  GET  /rest/api/3/mypermissions                darf der Benutzer im Projekt anlegen (CREATE_ISSUES)
  GET  /rest/api/3/issue/{key}?fields=...       ist das genannte Epic ein Epic desselben Projekts (Hierarchiestufe 1)
  POST /rest/api/3/issue                        genau einmal je Klick, nie wiederholt
  POST /rest/api/3/search/jql                   nur nach einer unklaren Antwort beim Anlegen: eigene Vorgänge der letzten 15 Minuten
                                                im Projekt; der Titel steht nie im JQL, verglichen wird im Code

Das Epic hängt über das Feld parent an der Story. Atlassian hat "Epic Link" (hier customfield_10006, "Epic-Verknüpfung") für die REST-
Schnittstelle abgekündigt und parent auch für firmenverwaltete Projekte (WMCNL: software, nicht vereinfacht) zum Weg gemacht.

Die Beschreibung geht als Atlassian Document Format (adf): nur Absätze, Überschriften, Aufzählungen und Text mit den Marken fett und Code.
Erwähnungen, Verweise, Makros oder eingebettete Inhalte kann kein Text erzeugen, auch kein eingeschleuster.

Regeln der Übertragung: HTTPS nur zu <name>.atlassian.net, keine Umleitungen (das Token geht nirgends anders hin), keine Proxys aus der Umgebung,
keine Kompression, Antworten höchstens ANTWORT_MAX Bytes, Fristen je Schritt und als Gesamtfrist. Fehler sind JiraFehler mit einem Code und
einem festen Satz; Texte von Jira werden nie gelesen oder weitergegeben. Das Token steht nie in Meldungen, Protokollen oder repr().
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from loguru import logger

from env_schalter import schalter_an

ENV_SCHALTER = "WAMO_JIRA"
ENV_URL = "WAMO_JIRA_URL"
ENV_EMAIL = "WAMO_JIRA_EMAIL"
ENV_TOKEN = "WAMO_JIRA_TOKEN"
ENV_PROJEKTE = "WAMO_JIRA_PROJEKTE"
ENV_STANDARD = "WAMO_JIRA_STANDARD_PROJEKT"
ALLE_VARIABLEN = (ENV_SCHALTER, ENV_URL, ENV_EMAIL, ENV_TOKEN, ENV_PROJEKTE, ENV_STANDARD)
STANDARD_URL = "https://wamocon.atlassian.net"
STANDARD_PROJEKT = "WMCNL"

VERBINDEN_SECS = 5.0
LESE_SECS = 8.0
SCHREIB_SECS = 15.0
ANFRAGE_MAX = 64 * 1024
ANTWORT_MAX = 512 * 1024
MAX_PROJEKTE = 20
TITEL_MAX = 255  # Grenze von Jira für summary; die Werkzeuge erlauben weniger
SUCHE_MINUTEN = 15

PROJEKT_RE = re.compile(r"[A-Z][A-Z0-9_]{1,9}")
SCHLUESSEL_RE = re.compile(r"([A-Z][A-Z0-9_]{1,9})-[1-9][0-9]{0,8}")
HOST_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_=+/.-]{24,1024}")
TYP_ID_RE = re.compile(r"[0-9]{1,18}")
INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")  # wie renderMarkdown in ui/src/components/Canvas.tsx
UEBERSCHRIFT_RE = re.compile(r"^(#{1,3})\s+(.*)$")
PUNKT_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_VERBOTEN = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})

FEHLER_SAETZE = {
    "anmeldung": "Jira hat die Anmeldung abgelehnt: Das Token des technischen Benutzers fehlt, ist abgelaufen oder wurde widerrufen.",
    "keine_rechte": "Der technische Jira-Benutzer darf in diesem Projekt keine Vorgänge anlegen.",
    "projekt_unbekannt": "Das Projekt gibt es in Jira nicht, oder der technische Benutzer sieht es nicht.",
    "epic_unbekannt": "Das Epic gibt es in Jira nicht, oder der technische Benutzer sieht es nicht.",
    "kein_epic": "Der genannte Vorgang ist kein Epic dieses Projekts.",
    "kein_story_typ": "Im Projekt gibt es den Vorgangstyp Story nicht.",
    "nicht_gefunden": "Jira kennt das Ziel nicht.",
    "abgelehnt": "Jira hat die Angaben abgelehnt.",
    "gebremst": "Jira bremst gerade, weil zu viele Anfragen kamen. Bitte in einer Minute noch einmal.",
    "gestoert": "Jira ist gerade gestört.",
    "zeitueberschreitung": "Jira hat nicht rechtzeitig geantwortet.",
    "nicht_erreichbar": "Jira ist nicht erreichbar.",
    "antwort_ungueltig": "Die Antwort von Jira war unverständlich.",
    "eingabe_ungueltig": "Die Angaben für Jira sind ungültig.",
}


class JiraKonfigFehler(ValueError):
    """Einstellung fehlt oder ist ungültig. Die Meldung nennt nur den Namen der Variablen, nie den Wert."""


class JiraFehler(Exception):
    """code: einer aus FEHLER_SAETZE; status: HTTP-Status oder None; unklar: ein Anlegen kann trotzdem angekommen sein (Zeitüberschreitung,
    Abbruch oder Störung nach dem Senden): dann nur nachsehen, nie ein zweites Mal anlegen."""

    def __init__(self, code: str, status: int | None = None, *, unklar: bool = False):
        super().__init__(code)
        self.code = code if code in FEHLER_SAETZE else "antwort_ungueltig"
        self.status = status
        self.unklar = unklar

    @property
    def satz(self) -> str:
        return FEHLER_SAETZE[self.code]

    def __str__(self) -> str:
        return f"Jira: {self.code}" + (f" ({self.status})" if self.status else "")


@dataclass(frozen=True)
class Einstellung:
    url: str
    email: str
    token: str = field(repr=False)
    projekte: tuple[str, ...]
    standard: str


@dataclass(frozen=True)
class Projekt:
    key: str
    name: str
    story_typ_id: str


@dataclass(frozen=True)
class Epic:
    key: str
    titel: str


# ---------- Einstellung ----------
def jira_an(wert: str | None = None) -> bool:
    """WAMO_JIRA: Standard aus; nur an, 1 oder ja schaltet ein (ein Tippfehler bleibt aus)."""
    return schalter_an(ENV_SCHALTER, wert, standard=False)


def _url_pruefen(roh: str) -> str:
    try:
        teile = urlsplit(roh.strip())
        host = (teile.hostname or "").lower()
        port = teile.port
    except ValueError as e:
        raise JiraKonfigFehler(f"{ENV_URL} ist ungültig") from e
    if (teile.scheme != "https" or not HOST_RE.fullmatch(host) or teile.username is not None or teile.password is not None
            or port not in (None, 443) or teile.query or teile.fragment or teile.path not in ("", "/")):
        raise JiraKonfigFehler(f"{ENV_URL} ist ungültig (nur https://<name>.atlassian.net)")
    return f"https://{host}"


def einstellung_aus_umgebung(umgebung: Mapping[str, str] | None = None) -> Einstellung:
    """Die geprüfte Einstellung oder JiraKonfigFehler (nur mit dem Namen der Variablen)."""
    env = os.environ if umgebung is None else umgebung

    def wert(name: str) -> str:
        return (env.get(name) or "").strip()

    url = _url_pruefen(wert(ENV_URL) or STANDARD_URL)
    email = wert(ENV_EMAIL)
    if not EMAIL_RE.fullmatch(email):
        raise JiraKonfigFehler(f"{ENV_EMAIL} fehlt oder ist ungültig")
    token = wert(ENV_TOKEN)
    if not TOKEN_RE.fullmatch(token):
        raise JiraKonfigFehler(f"{ENV_TOKEN} fehlt oder ist ungültig")
    roh = wert(ENV_PROJEKTE) or STANDARD_PROJEKT
    projekte = tuple(dict.fromkeys(p.strip().upper() for p in roh.split(",") if p.strip()))
    if not projekte or len(projekte) > MAX_PROJEKTE or not all(PROJEKT_RE.fullmatch(p) for p in projekte):
        raise JiraKonfigFehler(f"{ENV_PROJEKTE} ist ungültig (Projektschlüssel, durch Komma getrennt)")
    standard = (wert(ENV_STANDARD) or STANDARD_PROJEKT).upper()
    if wert(ENV_STANDARD) == "" and standard not in projekte:
        standard = projekte[0]
    if standard not in projekte:
        raise JiraKonfigFehler(f"{ENV_STANDARD} steht nicht in {ENV_PROJEKTE}")
    return Einstellung(url=url, email=email, token=token, projekte=projekte, standard=standard)


# ---------- Text ----------
def eine_zeile(text: object, grenze: int) -> str | None:
    """Text von Jira für Karte und Anzeige: NFC, Steuer-, Format- und Bidi-Zeichen zu Leerzeichen, eine Zeile, höchstens grenze Zeichen."""
    if not isinstance(text, str):
        return None
    t = unicodedata.normalize("NFC", text)
    t = "".join(" " if unicodedata.category(z) in _VERBOTEN else z for z in t)
    t = " ".join(t.split())
    return t[:grenze] if t else None


def _inline(zeile: str) -> list[dict]:
    knoten = []
    for teil in INLINE_RE.split(zeile):
        if not teil:
            continue
        if len(teil) > 4 and teil.startswith("**") and teil.endswith("**"):
            knoten.append({"type": "text", "text": teil[2:-2], "marks": [{"type": "strong"}]})
        elif len(teil) > 2 and teil.startswith("`") and teil.endswith("`"):
            knoten.append({"type": "text", "text": teil[1:-1], "marks": [{"type": "code"}]})
        else:
            knoten.append({"type": "text", "text": teil})
    return knoten


def _absatz(zeile: str) -> dict:
    return {"type": "paragraph", "content": _inline(zeile)}


def _liste(punkte: Sequence[str]) -> dict:
    return {"type": "bulletList", "content": [{"type": "listItem", "content": [_absatz(p)]} for p in punkte]}


def adf(beschreibung: str, kriterien: Sequence[str]) -> dict | None:
    """Atlassian Document Format aus dem kleinen Markdown des Canvas (#, ##, ###, -, *, **fett**, `code`) und den Kriterien als Liste unter
    der Überschrift "Akzeptanzkriterien". Jede nicht leere Zeile wird ein Block; leer ergibt None (dann ohne Beschreibung)."""
    bloecke: list[dict] = []
    punkte: list[str] = []

    def punkte_abschliessen() -> None:
        if punkte:
            bloecke.append(_liste(list(punkte)))
            punkte.clear()

    for roh in (beschreibung or "").split("\n"):
        zeile = roh.rstrip()
        if not zeile.strip():
            punkte_abschliessen()
            continue
        punkt = PUNKT_RE.match(zeile)
        if punkt and punkt.group(1).strip():
            punkte.append(punkt.group(1).strip())
            continue
        punkte_abschliessen()
        ueberschrift = UEBERSCHRIFT_RE.match(zeile)
        if ueberschrift and ueberschrift.group(2).strip():
            bloecke.append({"type": "heading", "attrs": {"level": len(ueberschrift.group(1)) + 1},
                            "content": _inline(ueberschrift.group(2).strip())})
        else:
            bloecke.append(_absatz(zeile.strip()))
    punkte_abschliessen()
    if kriterien:
        bloecke.append({"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Akzeptanzkriterien"}]})
        bloecke.append(_liste([k for k in kriterien if k]))
    return {"type": "doc", "version": 1, "content": bloecke} if bloecke else None


def adf_text(doc: Mapping | None) -> list[str]:
    """Reiner Text je Block (Absatz, Überschrift, Listenpunkt), ohne Marken: so steht er auf der Karte (ohne Markdown-Zeichen)."""
    if not doc:
        return []
    zeilen: list[str] = []

    def lauf(k: Mapping) -> None:
        if k.get("type") in ("paragraph", "heading"):
            zeilen.append("".join(t.get("text", "") for t in k.get("content", [])))
            return
        for kind in k.get("content", []):
            lauf(kind)

    lauf(doc)
    return zeilen


def story_felder(*, projekt: str, typ_id: str, titel: str, beschreibung: str, kriterien: Sequence[str], epic: str) -> dict:
    """Die Felder für POST /rest/api/3/issue: Projekt per Schlüssel, Typ per Kennung, Titel, Beschreibung (ADF), Epic über parent."""
    felder: dict = {"project": {"key": projekt}, "issuetype": {"id": typ_id}, "summary": titel}
    doc = adf(beschreibung, kriterien)
    if doc is not None:
        felder["description"] = doc
    if epic:
        felder["parent"] = {"key": epic}
    return felder


# ---------- Client ----------
def _eingabe(bedingung: bool) -> None:
    if not bedingung:
        raise JiraFehler("eingabe_ungueltig")


class JiraClient:
    """Ein Client je Sitzung. transport nur für Tests (httpx.MockTransport)."""

    def __init__(self, einstellung: Einstellung, *, transport: httpx.AsyncBaseTransport | None = None, verbinden_secs: float = VERBINDEN_SECS,
                 lese_secs: float = LESE_SECS, schreib_secs: float = SCHREIB_SECS):
        self._url = einstellung.url
        self._verbinden, self._lese, self._schreib = verbinden_secs, lese_secs, schreib_secs
        self._http = httpx.AsyncClient(
            base_url=self._url, transport=transport, auth=httpx.BasicAuth(einstellung.email, einstellung.token),
            follow_redirects=False, trust_env=False,
            headers={"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "wamo-kern"})

    def __repr__(self) -> str:
        return f"JiraClient({self._url})"

    async def aclose(self) -> None:
        await self._http.aclose()

    def link(self, schluessel: str) -> str:
        """Verweis aus der festen Basisadresse und dem geprüften Schlüssel, nie aus einer Antwort von Jira."""
        _eingabe(bool(SCHLUESSEL_RE.fullmatch(schluessel)))
        return f"{self._url}/browse/{schluessel}"

    # ---------- Lesen ----------
    async def projekt(self, key: str) -> Projekt:
        _eingabe(isinstance(key, str) and bool(PROJEKT_RE.fullmatch(key)))
        daten = await self._anfrage("GET", f"/rest/api/3/project/{key}", nicht_gefunden="projekt_unbekannt")
        if not isinstance(daten, dict) or daten.get("key") != key or not isinstance(daten.get("issueTypes"), list):
            raise JiraFehler("antwort_ungueltig")
        name = eine_zeile(daten.get("name"), 120) or key
        for typ in daten["issueTypes"]:
            if (isinstance(typ, dict) and isinstance(typ.get("name"), str) and typ["name"].strip().casefold() == "story"
                    and typ.get("subtask") is not True and typ.get("hierarchyLevel", 0) == 0
                    and isinstance(typ.get("id"), str) and TYP_ID_RE.fullmatch(typ["id"])):
                return Projekt(key=key, name=name, story_typ_id=typ["id"])
        raise JiraFehler("kein_story_typ")

    async def darf_anlegen(self, key: str) -> bool:
        _eingabe(isinstance(key, str) and bool(PROJEKT_RE.fullmatch(key)))
        daten = await self._anfrage("GET", "/rest/api/3/mypermissions", params={"projectKey": key, "permissions": "CREATE_ISSUES"},
                                    nicht_gefunden="projekt_unbekannt")
        recht = daten.get("permissions", {}).get("CREATE_ISSUES") if isinstance(daten, dict) and isinstance(daten.get("permissions"), dict) \
            else None
        if not isinstance(recht, dict) or not isinstance(recht.get("havePermission"), bool):
            raise JiraFehler("antwort_ungueltig")
        return recht["havePermission"]

    async def epic(self, key: str, projekt: str) -> Epic:
        """Das Epic muss es geben, im selben Projekt liegen und die Hierarchiestufe 1 (Epic) haben."""
        _eingabe(isinstance(key, str) and isinstance(projekt, str) and bool(PROJEKT_RE.fullmatch(projekt)))
        treffer = SCHLUESSEL_RE.fullmatch(key)
        _eingabe(treffer is not None)
        if treffer.group(1) != projekt:
            raise JiraFehler("kein_epic")
        daten = await self._anfrage("GET", f"/rest/api/3/issue/{key}", params={"fields": "summary,issuetype,project"},
                                    nicht_gefunden="epic_unbekannt")
        felder = daten.get("fields") if isinstance(daten, dict) else None
        if not isinstance(felder, dict):
            raise JiraFehler("antwort_ungueltig")
        typ, ort = felder.get("issuetype"), felder.get("project")
        stufe = typ.get("hierarchyLevel") if isinstance(typ, dict) else None
        name = typ.get("name") if isinstance(typ, dict) else None
        ist_epic = stufe == 1 or (stufe is None and isinstance(name, str) and name.strip().casefold() == "epic")
        if not ist_epic or not isinstance(ort, dict) or ort.get("key") != projekt:
            raise JiraFehler("kein_epic")
        return Epic(key=key, titel=eine_zeile(felder.get("summary"), 200) or "(ohne Titel)")

    # ---------- Anlegen und Nachsehen ----------
    async def anlegen(self, *, projekt: str, typ_id: str, titel: str, beschreibung: str, kriterien: Sequence[str], epic: str) -> str:
        """Genau ein POST. Liefert den geprüften Schlüssel (Projekt muss passen). Wirft JiraFehler; unklar heißt: vielleicht doch angelegt."""
        _eingabe(bool(PROJEKT_RE.fullmatch(projekt)) and bool(TYP_ID_RE.fullmatch(typ_id)) and isinstance(titel, str)
                 and 0 < len(titel) <= TITEL_MAX and (epic == "" or bool(SCHLUESSEL_RE.fullmatch(epic))))
        felder = story_felder(projekt=projekt, typ_id=typ_id, titel=titel, beschreibung=beschreibung, kriterien=kriterien, epic=epic)
        daten = await self._anfrage("POST", "/rest/api/3/issue", body={"fields": felder}, erwartet=201)
        schluessel = daten.get("key") if isinstance(daten, dict) else None
        treffer = SCHLUESSEL_RE.fullmatch(schluessel) if isinstance(schluessel, str) else None
        if treffer is None or treffer.group(1) != projekt:
            raise JiraFehler("antwort_ungueltig", 201, unklar=True)
        return schluessel

    async def nach_anlegen_suchen(self, *, projekt: str, titel: str) -> str | None:
        """Nach einer unklaren Antwort: der jüngste eigene Vorgang der letzten Minuten im Projekt mit genau diesem Titel, sonst None."""
        _eingabe(bool(PROJEKT_RE.fullmatch(projekt)) and isinstance(titel, str))
        jql = f'project = "{projekt}" AND reporter = currentUser() AND created >= "-{SUCHE_MINUTEN}m" ORDER BY created DESC'
        daten = await self._anfrage("POST", "/rest/api/3/search/jql", body={"jql": jql, "fields": ["summary"], "maxResults": 20})
        vorgaenge = daten.get("issues") if isinstance(daten, dict) else None
        if not isinstance(vorgaenge, list):
            raise JiraFehler("antwort_ungueltig")
        for v in vorgaenge:
            felder = v.get("fields") if isinstance(v, dict) else None
            schluessel = v.get("key") if isinstance(v, dict) else None
            treffer = SCHLUESSEL_RE.fullmatch(schluessel) if isinstance(schluessel, str) else None
            if treffer and treffer.group(1) == projekt and isinstance(felder, dict) and felder.get("summary") == titel:
                return schluessel
        return None

    # ---------- Übertragung ----------
    async def _anfrage(self, methode: str, pfad: str, *, params: dict | None = None, body: dict | None = None, erwartet: int = 200,
                       nicht_gefunden: str = "nicht_gefunden") -> object:
        """Ein Aufruf, nie wiederholt. Nur ein schreibender Aufruf (POST auf /issue) kann unklar enden."""
        schreibend = methode == "POST" and pfad == "/rest/api/3/issue"
        roh = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        _eingabe(roh is None or len(roh) <= ANFRAGE_MAX)
        frist = self._schreib if methode == "POST" else self._lese
        try:
            async with asyncio.timeout(self._verbinden + frist):
                status, daten = await self._einmal(methode, pfad, params, roh, frist, schreibend)
        except TimeoutError as e:
            raise JiraFehler("zeitueberschreitung", unklar=schreibend) from e
        if status >= 400:
            raise _fehler_aus(status, schreibend, nicht_gefunden)
        if status != erwartet:
            raise JiraFehler("antwort_ungueltig", status, unklar=schreibend and 200 <= status < 300)
        try:
            return json.loads(daten.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError) as e:
            raise JiraFehler("antwort_ungueltig", status, unklar=schreibend) from e

    async def _einmal(self, methode, pfad, params, roh, frist, schreibend) -> tuple[int, bytes]:
        kopf = {"Content-Type": "application/json"} if roh is not None else None
        try:
            async with self._http.stream(methode, pfad, params=params, content=roh, headers=kopf,
                                         timeout=httpx.Timeout(frist, connect=self._verbinden)) as antwort:
                if antwort.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                    raise JiraFehler("antwort_ungueltig", antwort.status_code, unklar=schreibend)
                teile, summe = [], 0
                async for stueck in antwort.aiter_bytes():  # ohne Kompression (oben geprüft) gleich den Rohbytes
                    summe += len(stueck)
                    if summe > ANTWORT_MAX:
                        raise JiraFehler("antwort_ungueltig", antwort.status_code, unklar=schreibend)
                    teile.append(stueck)
                return antwort.status_code, b"".join(teile)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            logger.warning("Jira: nicht erreichbar ({})", type(e).__name__)
            raise JiraFehler("nicht_erreichbar") from e  # nichts ist angekommen
        except httpx.TimeoutException as e:
            logger.warning("Jira: Zeitüberschreitung ({})", type(e).__name__)
            raise JiraFehler("zeitueberschreitung", unklar=schreibend) from e
        except httpx.HTTPError as e:
            logger.warning("Jira: Übertragung abgebrochen ({})", type(e).__name__)
            raise JiraFehler("nicht_erreichbar", unklar=schreibend) from e


def _fehler_aus(status: int, schreibend: bool, nicht_gefunden: str) -> JiraFehler:
    """Fester Code je Status. Den Text von Jira liest der Kern nie."""
    if status == 400:
        return JiraFehler("abgelehnt", status)
    if status == 401:
        return JiraFehler("anmeldung", status)
    if status == 403:
        return JiraFehler("keine_rechte", status)
    if status == 404:
        return JiraFehler(nicht_gefunden, status)
    if status == 429:
        return JiraFehler("gebremst", status)
    if status >= 500:
        return JiraFehler("gestoert", status, unklar=schreibend)  # eine Störung nach dem Senden: vielleicht doch angelegt
    return JiraFehler("antwort_ungueltig", status)
