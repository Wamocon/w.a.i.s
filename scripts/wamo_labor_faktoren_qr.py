"""QR-Code eines neu eingerichteten Faktors zum Scannen anzeigen (einrichten --qr) für scripts/wamo_labor_faktoren.py.

Quelle ist allein die Antwort von GoTrue beim Anlegen des Faktors: totp.qr_code, eine SVG, meist als Daten-URL
(data:image/svg+xml;utf-8,<svg ...>). Es gibt keinen eigenen QR-Encoder und nichts außer der Standardbibliothek. Für einen Faktor,
der schon bestand, gibt es keinen QR mehr (GoTrue liefert ihn nur beim Anlegen).

Ablauf je Profil: ein neuer Ordner (tempfile.mkdtemp, Präfix wamo-labor-qr-) unter %LOCALAPPDATA%\\WAMO, ohne diese Variable im
Temp-Ordner des Systems. Darin eine kurze HTML-Seite (Profil, QR als Bild, ein Satz). Die Datei bekommt die Rechte nur für den
Benutzer, solange sie noch leer ist. Die Seite lädt nichts aus dem Netz: Content-Security-Policy default-src 'none', das Bild ist eine
Daten-URL, es gibt kein Skript. Sie öffnet im Standardbrowser, die Konsole wartet auf Enter, danach werden Datei und Ordner gelöscht,
auch bei Strg+C, Signal und Fehler (finally). Bleibt nach einem harten Abbruch (Konsole geschlossen) ein Ordner liegen, löscht ihn der
nächste Lauf mit --qr vor dem ersten Profil.

Geheimnisse: Die SVG kodiert die otpauth-URI samt Seed. Weder SVG noch URI noch Seed erscheinen in einer Ausgabe oder einem Fehlertext,
nur Profil, Hinweis und Ordnerpfad. Fehlertexte nennen nie den Text einer Ausnahme, nur ihren Typ.
"""
from __future__ import annotations

import base64
import binascii
import html
import os
import re
import sys
import tempfile
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable

import wamo_labor_faktoren_signale as sg
import wamo_labor_faktoren_umschlag as um

ORDNER_PRAEFIX = "wamo-labor-qr-"
DATEI_RE = re.compile(r"qr-labor-0[1-9]\.html")
SVG_GRENZE = 500_000
LOGO = Path(__file__).resolve().parent.parent / "host" / "vorlagen" / "wmc-logo.png"
LOGO_GRENZE = 200_000
ANSCHRIFT = "WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn"
HINWEIS = "Mit der Authenticator-App scannen, dann im Konsolenfenster Enter drücken."
_SVG_ANFANG = re.compile(r"(<\?xml[^>]{0,200}\?>\s*)?<svg[\s/>]", re.I)
_SVG_TAG = re.compile(r"<svg\b[^>]*>", re.I)
_LAENGE = r"""\s{}\s*=\s*["']\s*([0-9]{{1,5}}(?:\.[0-9]{{1,3}})?)\s*(?:px)?\s*["']"""


class QrFehler(Exception):
    """Der QR-Code lässt sich nicht anzeigen. Der Text nennt nie einen Wert."""


def browser_oeffnen(pfad: Path) -> None:
    """Die Seite im Standardbrowser öffnen (Windows: wie ein Doppelklick auf die Datei)."""
    if os.name == "nt":
        os.startfile(str(pfad))  # type: ignore[attr-defined]  # gibt es nur unter Windows
    elif not webbrowser.open(pfad.as_uri()):
        raise OSError("kein Browser gefunden")


def konsole_da() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False


# Austauschbar für Tests (wie RECHTE_SETZEN im Hauptskript): In Tests öffnet sich nie ein Browser und niemand drückt Enter.
OEFFNEN: Callable[[Path], None] = browser_oeffnen
WARTEN: Callable[[str], str] = input
KONSOLE: Callable[[], bool] = konsole_da


def ablage() -> Path:
    """%LOCALAPPDATA%\\WAMO (nur für den Benutzer), sonst der Temp-Ordner des Systems."""
    lokal = os.environ.get("LOCALAPPDATA", "").strip()
    return Path(lokal) / "WAMO" if lokal else Path(tempfile.gettempdir())


def svg_aus_antwort(qr_code: object) -> str:
    """Die SVG aus totp.qr_code: eine Daten-URL (roh, prozentkodiert oder Base64) oder die SVG selbst."""
    if not isinstance(qr_code, str) or not qr_code.strip():
        raise QrFehler("der Server hat keinen QR-Code geliefert")
    text = qr_code.strip()
    if text[:5].lower() == "data:":
        kopf, trenner, rest = text.partition(",")
        if not trenner or "svg" not in kopf.lower():
            raise QrFehler("der QR-Code des Servers ist keine SVG")
        if kopf.lower().endswith(";base64"):
            try:
                rest = base64.b64decode(rest, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                raise QrFehler("der QR-Code des Servers ist nicht lesbar") from None
        elif rest.lstrip()[:3].lower() == "%3c":
            rest = urllib.parse.unquote(rest)
        text = rest.strip()
    if len(text) > SVG_GRENZE or not _SVG_ANFANG.match(text) or not text.endswith(">"):
        raise QrFehler("der QR-Code des Servers ist keine SVG")
    return mit_viewbox(text)


def mit_viewbox(svg: str) -> str:
    """GoTrue schreibt nur width und height (in Pixeln, kleine Module). Ohne viewBox wächst die SVG im Bild nicht mit, sie würde nur
    beschnitten: dann wird viewBox aus width und height ergänzt, dazu crispEdges, damit beim Vergrößern keine hellen Fugen zwischen den
    Modulen entstehen. Mit viewBox oder ohne lesbare Maße bleibt sie unverändert."""
    tag = _SVG_TAG.search(svg)
    if tag is None or re.search(r"\sviewBox\s*=", tag.group(0)):
        return svg
    breite = re.search(_LAENGE.format("width"), tag.group(0))
    hoehe = re.search(_LAENGE.format("height"), tag.group(0))
    if breite is None or hoehe is None:
        return svg
    kanten = "" if re.search(r"\sshape-rendering\s*=", tag.group(0)) else ' shape-rendering="crispEdges"'
    neu = f'<svg viewBox="0 0 {breite.group(1)} {hoehe.group(1)}"{kanten}' + tag.group(0)[4:]
    return svg[:tag.start()] + neu + svg[tag.end():]


def _logo() -> str:
    try:
        roh = LOGO.read_bytes() if LOGO.is_file() and LOGO.stat().st_size <= LOGO_GRENZE else b""
    except OSError:
        roh = b""
    return f'<img class="logo" alt="WAMOCON" src="data:image/png;base64,{base64.b64encode(roh).decode("ascii")}">' if roh else ""


def seite(kennung: str, svg: str) -> str:
    """Die HTML-Seite: Kopfzeile mit Anschrift und Logo, Profil, QR als Daten-URL, ein Satz. Kein Skript, keine Netzquelle."""
    k = html.escape(kennung)
    bild = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR {k}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; background: #ffffff; color: #1d1d1d; font-family: "Atkinson Hyperlegible", Arial, sans-serif; }}
header {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 12px 16px;
  border-bottom: 3px solid #F40E0E; font-size: 13px; color: #555555; }}
header .logo {{ height: 36px; width: auto; }}
main {{ text-align: center; padding: 24px 16px; }}
h1 {{ font-size: 28px; margin: 0 0 16px; letter-spacing: 0.02em; }}
.qr {{ width: min(80vw, 340px); height: auto; padding: 16px; background: #ffffff; border: 1px solid #cccccc;
  image-rendering: pixelated; }}
p {{ font-size: 18px; margin: 16px 0 0; }}
footer {{ text-align: center; font-size: 12px; color: #777777; padding: 16px; }}
</style>
</head>
<body>
<header><span>{html.escape(ANSCHRIFT)}</span>{_logo()}</header>
<main>
<h1>{k}</h1>
<img class="qr" alt="QR-Code für {k}" src="data:image/svg+xml;base64,{bild}">
<p>{html.escape(HINWEIS)}</p>
</main>
<footer>Seite 1</footer>
</body>
</html>
"""


def _schreiben(datei: Path, inhalt: str, rechte: Callable[[Path], None]) -> None:
    """Neu anlegen (nie eine vorhandene Datei), Rechte setzen, solange sie leer ist, dann den Inhalt schreiben."""
    fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    os.close(fd)
    try:
        rechte(datei)
    except um.UmschlagFehler:
        raise QrFehler("die Rechte der QR-Datei ließen sich nicht setzen") from None
    datei.write_bytes(inhalt.encode("utf-8"))


def _datei_weg(datei: Path) -> bool:
    try:
        datei.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        pass
    try:  # gesperrt oder schreibgeschützt: wenigstens den Inhalt leeren, dann noch einmal
        datei.write_bytes(b"")
        datei.unlink()
        return True
    except OSError:
        return False


def _ordner_loeschen(ordner: Path) -> bool:
    """Löscht die QR-Dateien des Ordners und ihn selbst. Andere Dateien bleiben, dann bleibt auch der Ordner. Kein Signal stört."""
    alt = sg.ignorieren()
    try:
        ok = True
        try:
            for p in list(ordner.iterdir()):
                ok = (DATEI_RE.fullmatch(p.name) is not None and _datei_weg(p)) and ok
            ordner.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            ok = False
        return ok
    finally:
        sg.zuruecksetzen(alt)


def bereit(melden: Callable[[str], None], warnen: Callable[[str], None]) -> None:
    """Vor dem ersten Profil: Eine Konsole für Enter muss da sein, Reste eines hart abgebrochenen Laufs verschwinden."""
    if not KONSOLE():
        raise QrFehler("--qr braucht eine Konsole, in der nach dem Scannen Enter gedrückt wird")
    basis = ablage()
    try:
        reste = sorted(p for p in basis.glob(ORDNER_PRAEFIX + "*") if p.is_dir()) if basis.is_dir() else []
    except OSError:
        reste = []
    for ordner in reste:
        if _ordner_loeschen(ordner):
            melden("QR-Datei eines abgebrochenen Laufs gelöscht")
        else:
            warnen(f"Hinweis: Ordner eines abgebrochenen Laufs ließ sich nicht löschen, bitte von Hand löschen: {ordner}")


def zeigen(kennung: str, qr_code: object, melden: Callable[[str], None], warnen: Callable[[str], None],
           rechte: Callable[[Path], None]) -> None:
    """Zeigt den QR eines Profils im Browser, wartet auf Enter und löscht danach Datei und Ordner, auch bei Abbruch und Fehler."""
    if not isinstance(kennung, str) or not um.KENNUNG_RE.fullmatch(kennung):
        raise QrFehler("ungültiges Profil")
    svg = svg_aus_antwort(qr_code)
    basis = ablage()
    ordner: Path | None = None
    geoeffnet = False
    try:
        basis.mkdir(parents=True, exist_ok=True)
        ordner = Path(tempfile.mkdtemp(prefix=ORDNER_PRAEFIX, dir=basis))
        datei = ordner / f"qr-{kennung}.html"
        _schreiben(datei, seite(kennung, svg), rechte)
        OEFFNEN(datei)
        geoeffnet = True
        melden(f"QR für {kennung} angezeigt, nach dem Scannen Enter drücken")
        WARTEN("")
    except QrFehler:
        raise
    except EOFError:
        raise QrFehler("keine Eingabe in der Konsole möglich") from None
    except OSError as e:
        raise QrFehler(f"Ein-/Ausgabefehler ({type(e).__name__})") from None
    except Exception as e:  # nie der Text einer unerwarteten Ausnahme
        raise QrFehler(f"unerwarteter Fehler ({type(e).__name__})") from None
    finally:
        if ordner is not None:
            if not _ordner_loeschen(ordner):
                warnen(f"{kennung}: Die QR-Datei ließ sich nicht löschen, bitte den Ordner von Hand löschen: {ordner}")
            elif geoeffnet:
                melden(f"{kennung}: QR-Datei gelöscht, bitte den Tab im Browser schließen")
