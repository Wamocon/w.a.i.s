"""Einstieg: python -m wamo_werkstatt (Dienst starten).

Der Dienst liest nur Umgebungsvariablen und Dateien (konfig.py). Das Zugriffsprotokoll des Webservers ist aus: Es enthielte Abfragen.
Ein Fehler der Einstellung beendet den Start mit Ausgang 2 und einer Meldung ohne Werte.
"""

from __future__ import annotations

import ssl
import sys

import uvicorn

from . import protokoll
from .anmeldung import JwksQuelle
from .app import create_app
from .konfig import KonfigFehler, aus_umgebung, zugang_lesen
from .pg import AsyncpgDatenbank


def _tls(ca_datei: str | None) -> ssl.SSLContext | None:
    """Vertrauensbasis für JWKS: öffentliche Zertifikate plus die WAMO-CA (ohne CA-Datei gilt der Standard der Bibliothek)."""
    if ca_datei is None:
        return None
    try:
        import certifi

        kontext = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        kontext = ssl.create_default_context()
    try:
        kontext.load_verify_locations(cafile=ca_datei)
    except (OSError, ssl.SSLError):
        raise KonfigFehler("WAMO_CA_FILE: die Zertifikatsdatei ist nicht lesbar") from None
    return kontext


def main() -> int:
    protokoll.einrichten()
    try:
        konfig = aus_umgebung()
        zugang = zugang_lesen(konfig.zugang_datei)
        quelle = JwksQuelle(konfig.jwks_url, _tls(konfig.ca_datei))
    except KonfigFehler as e:
        print(f"Konfiguration: {e}", file=sys.stderr)
        return 2
    app = create_app(konfig, AsyncpgDatenbank(zugang, konfig.schema), quelle)
    protokoll.ereignis("start", host=konfig.host, port=konfig.port, schema=konfig.schema)
    uvicorn.run(app, host=konfig.host, port=konfig.port, access_log=False, server_header=False, date_header=False, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
