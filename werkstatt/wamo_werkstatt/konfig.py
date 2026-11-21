"""Konfiguration der Werkstatt: nur Umgebungsvariablen und Dateien, nie Argumente.

Geheimnisse (der Datenbankzugang) liegen in einer Datei (systemd-Credential oder /etc/wamo-werkstatt/db.zugang), nie in der Umgebung,
nie im Code, nie in einer Ausgabe. Jede Fehlermeldung nennt die Variable, nie einen Wert.

Umgebung (Standard in Klammern):
  WAMO_WERKSTATT_HOST (127.0.0.1), WAMO_WERKSTATT_PORT (18095), WAMO_WERKSTATT_PFAD (/werkstatt/api)
  WAMO_WERKSTATT_SCHEMA (Pflicht: wamo_dev, wamo_test oder wamo_prod)
  WAMO_WERKSTATT_SUPABASE_URL (Pflicht, https), WAMO_WERKSTATT_ISS (<url>/auth/v1), WAMO_WERKSTATT_AUD (authenticated),
  WAMO_WERKSTATT_JWKS_URL (<url>/auth/v1/.well-known/jwks.json), WAMO_CA_FILE (CA des Stacks, für JWKS und Datenbank)
  WAMO_WERKSTATT_HERKUNFT (https://192.168.178.136:55445), WAMO_WERKSTATT_ADMINS (/etc/wamo-werkstatt/admins)
  WAMO_WERKSTATT_DATEN (/var/lib/wamo-werkstatt), WAMO_WERKSTATT_MARKEN (feste Liste)
  WAMO_WERKSTATT_DB_ZUGANG (Pfad der Zugangsdatei; sonst $CREDENTIALS_DIRECTORY/db.zugang, sonst /etc/wamo-werkstatt/db.zugang)
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_RE = re.compile(r"^wamo_(dev|test|prod)$")
MARKE_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
STANDARD_PFAD = "/werkstatt/api"
STANDARD_HERKUNFT = "https://192.168.178.136:55445"
STANDARD_ADMINS = "/etc/wamo-werkstatt/admins"
STANDARD_DATEN = "/var/lib/wamo-werkstatt"
STANDARD_ZUGANG = "/etc/wamo-werkstatt/db.zugang"
# Journal-Marken, die das Panel zeigen darf. Gespräche, Konten und Geheimnisse liegen in keiner davon (docs/produktdokumentation/betrieb.md).
STANDARD_MARKEN = (
    "wamo-core", "wamo-labor-dienst", "wamo-labor-geraete", "wamo-labor-loeschen", "wamo-verteilung",
    "wamo-ui", "wamo-job-kern", "wamo-werkstatt", "wais-deploy",
)
ZUGANG_SCHLUESSEL = ("host", "port", "dbname", "user", "password", "sslrootcert")
ZUGANG_MAX_BYTES = 16384


class KonfigFehler(ValueError):
    """Eine Einstellung fehlt oder ist unbrauchbar. Die Meldung nennt die Variable, nie einen Wert."""


@dataclass(frozen=True)
class Konfig:
    schema: str
    supabase_url: str
    jwks_url: str
    issuer: str
    audience: str = "authenticated"
    ca_datei: str | None = None
    host: str = "127.0.0.1"
    port: int = 18095
    pfad: str = STANDARD_PFAD
    herkunft: str = STANDARD_HERKUNFT
    admins_datei: Path = Path(STANDARD_ADMINS)
    daten_ordner: Path = Path(STANDARD_DATEN)
    marken: tuple[str, ...] = STANDARD_MARKEN
    zugang_datei: Path = Path(STANDARD_ZUGANG)


@dataclass(frozen=True)
class DbZugang:
    """Verbindungsdaten aus der Zugangsdatei. Das Passwort steht nie in einer Ausgabe (repr=False)."""

    host: str
    port: int
    dbname: str
    user: str
    sslrootcert: str
    password: str = field(repr=False)


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _url_pruefen(wert: str, variable: str, *, nur_ursprung: bool = False) -> str:
    teile = urlsplit(wert.strip())
    host = teile.hostname or ""
    if not (teile.scheme == "https" or (teile.scheme == "http" and _loopback(host))) or not host:
        raise KonfigFehler(f"{variable}: erlaubt ist https (http nur über Loopback)")
    if teile.username or teile.password or teile.fragment or (nur_ursprung and (teile.path not in ("", "/") or teile.query)):
        raise KonfigFehler(f"{variable}: die Adresse hat eine unzulässige Form")
    return wert.strip().rstrip("/") if not nur_ursprung else f"{teile.scheme}://{teile.netloc}"


def _ganz(wert: str | None, variable: str, standard: int, minimum: int, maximum: int) -> int:
    if wert is None or wert.strip() == "":
        return standard
    try:
        zahl = int(wert.strip())
    except ValueError:
        raise KonfigFehler(f"{variable}: erwartet eine ganze Zahl") from None
    if not minimum <= zahl <= maximum:
        raise KonfigFehler(f"{variable}: erlaubt sind {minimum} bis {maximum}")
    return zahl


def _pfad_praefix(wert: str | None) -> str:
    roh = STANDARD_PFAD if wert is None else wert.strip()
    if roh in ("", "/"):
        return ""
    if not re.fullmatch(r"/[a-z0-9][a-z0-9/_-]{0,60}", roh) or roh.endswith("/") or "//" in roh:
        raise KonfigFehler("WAMO_WERKSTATT_PFAD: erwartet einen Pfad wie /werkstatt/api")
    return roh


def _marken(wert: str | None) -> tuple[str, ...]:
    if wert is None or wert.strip() == "":
        return STANDARD_MARKEN
    marken = tuple(dict.fromkeys(m.strip() for m in wert.split(",") if m.strip()))
    if not marken or any(not MARKE_RE.fullmatch(m) for m in marken):
        raise KonfigFehler("WAMO_WERKSTATT_MARKEN: erwartet eine Liste von Marken (a-z, Ziffern, Bindestrich), durch Komma getrennt")
    return marken


def zugang_pfad(env: Mapping[str, str]) -> Path:
    """Ort der Zugangsdatei: ausdrücklich gesetzt, sonst das systemd-Credential, sonst der feste Pfad."""
    ausdruecklich = (env.get("WAMO_WERKSTATT_DB_ZUGANG") or "").strip()
    if ausdruecklich:
        return Path(ausdruecklich)
    credentials = (env.get("CREDENTIALS_DIRECTORY") or "").strip()
    if credentials:
        return Path(credentials) / "db.zugang"
    return Path(STANDARD_ZUGANG)


def aus_umgebung(env: Mapping[str, str] | None = None) -> Konfig:
    """Liest die Einstellungen. Wirft KonfigFehler mit dem Namen der Variable, nie mit einem Wert."""
    env = os.environ if env is None else env
    schema = (env.get("WAMO_WERKSTATT_SCHEMA") or "").strip()
    if not SCHEMA_RE.fullmatch(schema):
        raise KonfigFehler("WAMO_WERKSTATT_SCHEMA: erlaubt sind wamo_dev, wamo_test und wamo_prod")
    roh_url = (env.get("WAMO_WERKSTATT_SUPABASE_URL") or "").strip()
    if not roh_url:
        raise KonfigFehler("WAMO_WERKSTATT_SUPABASE_URL fehlt")
    url = _url_pruefen(roh_url, "WAMO_WERKSTATT_SUPABASE_URL")
    jwks = (env.get("WAMO_WERKSTATT_JWKS_URL") or "").strip()
    jwks = _url_pruefen(jwks, "WAMO_WERKSTATT_JWKS_URL") if jwks else f"{url}/auth/v1/.well-known/jwks.json"
    aussteller = (env.get("WAMO_WERKSTATT_ISS") or "").strip().rstrip("/") or f"{url}/auth/v1"
    zielgruppe = (env.get("WAMO_WERKSTATT_AUD") or "").strip() or "authenticated"
    host = (env.get("WAMO_WERKSTATT_HOST") or "127.0.0.1").strip()
    if not _loopback(host):  # der Dienst liest Token unverschlüsselt: er lauscht nur auf Loopback, davor steht Caddy mit TLS
        raise KonfigFehler("WAMO_WERKSTATT_HOST: erlaubt ist nur Loopback (127.0.0.1, ::1 oder localhost)")
    ca = (env.get("WAMO_CA_FILE") or "").strip().strip('"').strip("'") or None
    return Konfig(
        schema=schema, supabase_url=url, jwks_url=jwks, issuer=aussteller, audience=zielgruppe, ca_datei=ca, host=host,
        port=_ganz(env.get("WAMO_WERKSTATT_PORT"), "WAMO_WERKSTATT_PORT", 18095, 1024, 65535),
        pfad=_pfad_praefix(env.get("WAMO_WERKSTATT_PFAD")),
        herkunft=_url_pruefen((env.get("WAMO_WERKSTATT_HERKUNFT") or STANDARD_HERKUNFT), "WAMO_WERKSTATT_HERKUNFT", nur_ursprung=True),
        admins_datei=Path((env.get("WAMO_WERKSTATT_ADMINS") or STANDARD_ADMINS).strip()),
        daten_ordner=Path((env.get("WAMO_WERKSTATT_DATEN") or STANDARD_DATEN).strip()),
        marken=_marken(env.get("WAMO_WERKSTATT_MARKEN")),
        zugang_datei=zugang_pfad(env),
    )


def zugang_lesen(pfad: Path) -> DbZugang:
    """Liest die Zugangsdatei (Zeilen Schlüssel=Wert: host, port, dbname, user, password, sslrootcert). Die Meldungen nennen nie einen Wert."""
    try:
        with open(pfad, "rb") as f:
            roh = f.read(ZUGANG_MAX_BYTES + 1)
        if len(roh) > ZUGANG_MAX_BYTES:
            raise KonfigFehler("Zugangsdatei: unerwartet groß")
        text = roh.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise KonfigFehler("Zugangsdatei: nicht lesbar") from None
    werte: dict[str, str] = {}
    for nr, zeile in enumerate(text.splitlines(), 1):
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        schluessel, trenner, wert = zeile.partition("=")
        schluessel = schluessel.strip()
        if not trenner or schluessel not in ZUGANG_SCHLUESSEL or schluessel in werte:  # nie den Inhalt der Zeile nennen
            raise KonfigFehler(f"Zugangsdatei: Zeile {nr} hat nicht die Form Schlüssel=Wert mit einem bekannten Schlüssel")
        werte[schluessel] = wert.strip()
    fehlt = [k for k in ZUGANG_SCHLUESSEL if not werte.get(k)]
    if fehlt:
        raise KonfigFehler("Zugangsdatei: es fehlt " + ", ".join(fehlt))
    if not NAME_RE.fullmatch(werte["user"]) or not NAME_RE.fullmatch(werte["dbname"]):
        raise KonfigFehler("Zugangsdatei: user oder dbname hat eine unzulässige Form")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", werte["host"]) or not werte["port"].isdigit() or not 1 <= int(werte["port"]) <= 65535:
        raise KonfigFehler("Zugangsdatei: host oder port ist ungültig")
    if len(werte["password"]) < 12 or any(c.isspace() for c in werte["password"]):
        raise KonfigFehler("Zugangsdatei: das Passwort ist zu kurz oder enthält Leerzeichen")
    if not werte["sslrootcert"].startswith("/") and not re.match(r"^[A-Za-z]:[\\/]", werte["sslrootcert"]):
        raise KonfigFehler("Zugangsdatei: sslrootcert muss ein absoluter Pfad sein")
    return DbZugang(werte["host"], int(werte["port"]), werte["dbname"], werte["user"], werte["sslrootcert"], werte["password"])
