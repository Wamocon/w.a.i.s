"""Outlook am PC (Paket 2 von docs/office-und-versand.md): welches Outlook aktiv ist, Senden über das klassische Outlook nach der
Freigabe (30 Sekunden zurückholbar, mit der Outlook-Signatur) und fertige Entwürfe im neuen Outlook, das die Person selbst sendet.

Erkennung (erkennen): Es zählt, welches Outlook gerade läuft, nicht was installiert ist. Am PC von Niko (15.11.2026) ist das klassische
Outlook installiert, per COM registriert und hat ein Profil, aktiv ist aber das neue Outlook (olk.exe); der Umschalter UseNewOutlook ist
dort nicht gesetzt, und mailto sowie .eml gehören dem klassischen Outlook. Registry und Zuordnungen allein führten also in die Irre.
  * Läuft das neue Outlook, gibt es nur den Entwurf im neuen Outlook, auch wenn das klassische zusätzlich läuft (im Zweifel nie senden).
  * Läuft nur das klassische (OUTLOOK.EXE), ist Outlook.Application registriert, gibt es ein Profil und antwortet die laufende Instanz
    per COM (GetActiveObject, nie ein Start über COM), sendet W.A.I.S. nach der Freigabe selbst. Steht der Umschalter UseNewOutlook auf
    dem neuen Outlook, öffnet W.A.I.S. dort nur einen Entwurf.
  * Sonst kein Weg, mit einem Satz, warum. Die Zuordnung von mailto und .eml steht nur als Auskunft in der Lage.

Neues Outlook (am PC geprüft, Bilder im Prüfbericht): Eine .eml-Datei mit "X-Unsent: 1", die das neue Outlook über seinen
App-Ausführungsalias (olk.exe Pfad) öffnet, wird ein fertiger Entwurf mit An, Cc, Betreff, Text und Anhang; das neue Outlook speichert
ihn selbst unter Entwürfe und hängt die Signatur der Person unten an, wenn der Text auch als HTML-Teil kommt (nur Text: die Signatur
landete über dem Text). Nicht gegangen sind: Start über die App-Kennung (ActivateForFile: "Vertrag nicht unterstützt"), der Deep Link
ms-outlook://mail/deeplink/compose ("Aktion wird noch nicht unterstützt") und das Standardprogramm (am PC das klassische Outlook, also
das falsche, das dafür gestartet würde). mailto über olk.exe öffnet einen Entwurf ohne Anhang ("attach" wird übergangen): Das ist
nur der Rückfall, wenn die .eml nicht geht; dann zeigt der Explorer den Anhang markiert und die Antwort sagt es deutlich.

Klassisches Outlook (office_outlook_com.py): Nach dem Klick baut W.A.I.S. die Mail per COM (Empfänger als aufgelöste SMTP-Adressen
wie auf der Karte, festes Konto, Anhänge aus geprüften Kopien), lässt Outlook die Standardsignatur einsetzen (GetInspector) und setzt den
Text davor, speichert sie unter Entwürfe und sendet sie erst nach VERZOEGERUNG_SECS (Versandliste). Bis dahin holt "Zurückholen" sie
zurück: Sie bleibt dann unverändert unter Entwürfe. Direkt vor dem Senden prüft W.A.I.S., dass Betreff, Empfänger, Anhänge und Text
noch dieselben sind. Statt Outlooks DeferredDeliveryTime (den Zeitpunkt arbeitet Exchange ab, Zurückholen hieße ein Element im
Postausgang finden, und beides lässt sich ohne echtes Senden nicht prüfen) hält der Host die Frist selbst: Fällt er in der Frist aus,
bleibt die Mail ungesendet unter Entwürfe.

Gesendet wird nur aus wamo_host._ausfuehren nach einer Freigabe mit Schlüssel. Dieses Modul kennt weder das Modell noch den Kern.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy as email_policy
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

VERZOEGERUNG_SECS = 30
EMPFAENGER_MAX = 10  # An und Cc zusammen, kein Bcc
EINGABE_MAX = 254
BETREFF_MAX = 200
TEXT_MAX = 6000
KARTE_MAX = 8000  # lange Freigabekarte (wamo_host.FREIGABE_DETAIL_MAX_MAIL)
ANHAENGE_MAX = 5
ANHAENGE_BYTES_MAX = 15 * 1024 * 1024
COM_TIMEOUT_SECS = 30.0
COM_PRUEF_SECS = 8.0
FENSTER_WARTEN_SECS = 25.0
ENTWURF_AUFBEWAHREN_SECS = 600
MAILTO_MAX = 8000
INTERN_STANDARD = ("wamocon.com",)

KLASSISCH_EXE, NEU_EXE = "outlook.exe", "olk.exe"
_LOKAL_ORDNER = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
OLK_ALIAS = _LOKAL_ORDNER / "Microsoft" / "WindowsApps" / NEU_EXE
ENTWURF_ORDNER = _LOKAL_ORDNER / "WAMO" / "entwuerfe"
EXPLORER = str(Path(os.environ.get("SystemRoot") or r"C:\Windows") / "explorer.exe")
PFAD_PREFERENCES = r"Software\Microsoft\Office\16.0\Outlook\Preferences"
PFAD_PROFILE = r"Software\Microsoft\Office\16.0\Outlook\Profiles"
PFAD_MAILTO = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\mailto\UserChoice"
PFAD_EML = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.eml\UserChoice"

MIME = {".pdf": ("application", "pdf"), ".csv": ("text", "csv"), ".md": ("text", "markdown"), ".txt": ("text", "plain"),
        ".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ".pptx": ("application", "vnd.openxmlformats-officedocument.presentationml.presentation")}

SENDEN_GRUND = "Outlook (klassisch) läuft: W.A.I.S. sendet nach deinem Klick, 30 Sekunden lang zurückholbar."
NEU_GRUND = "Das neue Outlook läuft: W.A.I.S. öffnet einen fertigen Entwurf, du sendest selbst."
UMSCHALTER_GRUND = ("Outlook steht auf dem Umschalter zum neuen Outlook: W.A.I.S. öffnet nur einen fertigen Entwurf im klassischen "
                    "Outlook, du sendest selbst.")
ZU_GRUND = "Outlook ist nicht geöffnet. Öffne Outlook und versuch es noch einmal."


class MailFehler(ValueError):
    """Die Mail kann so nicht vorbereitet, gesendet oder geöffnet werden (Text ist für Menschen gedacht)."""


@dataclass(frozen=True)
class Empfaenger:
    art: str  # "an" oder "cc"
    name: str  # Anzeigename aus dem Adressbuch, sonst leer
    smtp: str
    extern: bool


@dataclass(frozen=True)
class Anhang:
    kennung: str
    name: str
    pfad: Path
    groesse: int
    sha256: str


@dataclass(frozen=True)
class Mail:
    empfaenger: tuple[Empfaenger, ...]
    betreff: str
    text: str
    anhaenge: tuple[Anhang, ...] = ()

    @property
    def an(self) -> tuple[Empfaenger, ...]:
        return tuple(e for e in self.empfaenger if e.art == "an")

    @property
    def cc(self) -> tuple[Empfaenger, ...]:
        return tuple(e for e in self.empfaenger if e.art == "cc")


@dataclass(frozen=True)
class Lage:
    klassisch_laeuft: bool
    neu_laeuft: bool
    umschalter_neu: bool
    com_registriert: bool
    profil: bool
    olk_alias: bool
    mailto: str
    eml: str


@dataclass(frozen=True)
class Weg:
    weg: str  # senden, entwurf oder keiner
    programm: str  # klassisch, neu oder leer
    grund: str


# ---------- Text wie auf der Karte ----------
# Wie voice-core/persona.sichtbar: Steuer-, Format-, private und unbelegte Zeichen, Zeilen- und Absatztrenner und Variantenselektoren
# werden zu Leerzeichen. Der Host bereinigt so, bevor er Karte und Mail baut: Die Karte zeigt dann Zeichen für Zeichen, was rausgeht.
_UNSICHTBAR = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_UNSICHTBAR_EXTRA = re.compile("[\u034f\ufe00-\ufe0f\U000e0100-\U000e01ef]")


def _sichtbar(text: str) -> str:
    text = _UNSICHTBAR_EXTRA.sub(" ", text)
    return "".join(" " if unicodedata.category(ch) in _UNSICHTBAR else ch for ch in text)


def _zeile(wert: object, grenze: int = 200) -> str:
    return " ".join(_sichtbar(unicodedata.normalize("NFC", str(wert or ""))).split())[:grenze]


def _bereinigt(wert: str) -> str:
    t = unicodedata.normalize("NFC", wert).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_sichtbar(z).rstrip() for z in t.split("\n")).strip("\n")


def betreff(wert: object) -> str:
    if not isinstance(wert, str):
        raise MailFehler("Der Betreff fehlt.")
    t = _zeile(wert, BETREFF_MAX + 1)
    if not t:
        raise MailFehler("Der Betreff fehlt.")
    if len(t) > BETREFF_MAX:
        raise MailFehler(f"Der Betreff ist länger als {BETREFF_MAX} Zeichen.")
    return t


def text(wert: object) -> str:
    if wert is None:
        return ""
    if not isinstance(wert, str):
        raise MailFehler("Der Text der Mail fehlt.")
    t = _bereinigt(wert)
    if len(t) > TEXT_MAX:
        raise MailFehler(f"Der Text ist länger als {TEXT_MAX} Zeichen. Bitte kürzen oder als Anhang schicken.")
    return t


# ---------- Adressen und Empfänger ----------
_LOKAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")


def adresse(wert: object) -> str | None:
    """SMTP-Adresse in fester Form (Domäne klein, Unicode-Domäne als Punycode) oder None."""
    if not isinstance(wert, str):
        return None
    w = wert.strip()
    if not w or len(w) > EINGABE_MAX or w.count("@") != 1:
        return None
    lokal, domaene = w.split("@")
    if len(lokal) > 64 or not _LOKAL.fullmatch(lokal):
        return None
    try:
        ascii_dom = domaene.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    teile = ascii_dom.split(".")
    if len(teile) < 2 or not all(_LABEL.fullmatch(t) for t in teile) or not _TLD.fullmatch(teile[-1]):
        return None
    return f"{lokal}@{ascii_dom}"


def _domaene(smtp: str) -> str:
    return smtp.rsplit("@", 1)[-1].lower()


def interne_domaenen(konto_smtp: str | None = None) -> set[str]:
    """Interne Domänen: WAMO_MAIL_INTERN (Komma getrennt) oder INTERN_STANDARD, dazu die Domäne des sendenden Kontos. Nur exakt gleiche
    Domänen gelten als intern (eine ähnliche Domäne ist EXTERN)."""
    roh = os.getenv("WAMO_MAIL_INTERN")
    if roh is not None and roh.strip():
        basis = {d for d in (x.strip().lower() for x in re.split(r"[\s,;]+", roh)) if d}
    else:
        basis = set(INTERN_STANDARD)
    if konto_smtp and "@" in konto_smtp:
        basis.add(_domaene(konto_smtp))
    return basis


def eingaben(an: object, cc: object = None) -> list[tuple[str, str]]:
    """An und Cc als Liste von (art, Eingabe): Namen oder Adressen, je eine Zeile, zusammen höchstens EMPFAENGER_MAX, ohne Doppelte."""
    if not isinstance(an, list) or not an:
        raise MailFehler("Es fehlt mindestens ein Empfänger.")
    cc = [] if cc is None else cc
    if not isinstance(cc, list):
        raise MailFehler("Cc ist keine Liste.")
    paare = [("an", w) for w in an] + [("cc", w) for w in cc]
    if len(paare) > EMPFAENGER_MAX:
        raise MailFehler(f"Höchstens {EMPFAENGER_MAX} Empfänger je Mail (An und Cc zusammen). Für mehr bitte einen Verteiler in "
                         "Outlook selbst nutzen.")
    ergebnis, gesehen = [], set()
    for art, wert in paare:
        roh = " ".join(wert.split()) if isinstance(wert, str) else ""
        if not roh or len(roh) > EINGABE_MAX or any(unicodedata.category(c) in _UNSICHTBAR for c in wert):
            raise MailFehler("Ein Empfänger ist ungültig (leer, zu lang oder mit Steuerzeichen).")
        if roh.lower() in gesehen:
            raise MailFehler(f"{roh[:60]} steht doppelt in der Liste.")
        gesehen.add(roh.lower())
        ergebnis.append((art, roh))
    return ergebnis


def empfaenger_adressen(paare: list[tuple[str, str]], intern: set[str]) -> list[Empfaenger]:
    """Empfänger ohne Adressbuch (neues Outlook): nur gültige Adressen."""
    ergebnis = []
    for art, roh in paare:
        smtp = adresse(roh)
        if smtp is None:
            raise MailFehler(f"Im neuen Outlook braucht W.A.I.S. die Mailadresse, nicht nur den Namen: {roh[:60]}")
        ergebnis.append(Empfaenger(art, "", smtp, _domaene(smtp) not in intern))
    _keine_doppelten(ergebnis)
    return ergebnis


def _keine_doppelten(empf: list[Empfaenger]) -> None:
    adressen = [e.smtp.lower() for e in empf]
    if len(set(adressen)) != len(adressen):
        raise MailFehler("Eine Adresse steht nach dem Auflösen doppelt in der Liste.")


# ---------- Erkennung ----------
def _programme_aus_tasklist(roh: str) -> set[str]:
    return {zeile[0].strip().lower() for zeile in csv.reader(io.StringIO(roh)) if zeile}


def _sitzung() -> int | None:
    try:
        import ctypes

        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
            return int(sid.value)
    except (OSError, AttributeError):
        pass
    return None


def laufende_programme() -> set[str]:
    """Namen der laufenden Programme in der Sitzung dieses Benutzers (klein). Geht das nicht: leer (dann gilt Outlook als zu)."""
    if sys.platform != "win32":
        return set()
    argv = ["tasklist", "/FO", "CSV", "/NH"]
    if (sid := _sitzung()) is not None:
        argv += ["/FI", f"SESSION eq {sid}"]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return set()
    return _programme_aus_tasklist((p.stdout or b"").decode("ascii", "replace"))


def _reg(wurzel: str, pfad: str, name: str | None = None) -> object | None:
    """Wert aus der Registry (name None: True, wenn der Schlüssel existiert) oder None. Nur lesen."""
    if sys.platform != "win32":
        return None
    import winreg

    basis = {"HKCU": winreg.HKEY_CURRENT_USER, "HKCR": winreg.HKEY_CLASSES_ROOT}[wurzel]
    try:
        with winreg.OpenKey(basis, pfad) as schluessel:
            if name is None:
                return True
            return winreg.QueryValueEx(schluessel, name)[0]
    except OSError:
        return None


def _unterschluessel(pfad: str) -> int:
    if sys.platform != "win32":
        return 0
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, pfad) as schluessel:
            return int(winreg.QueryInfoKey(schluessel)[0])
    except OSError:
        return 0


def _progid(wert: object) -> str:
    return wert if isinstance(wert, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,60}", wert) else ""


def lage_lesen() -> Lage:
    """Was am PC läuft und eingestellt ist (nur lesen, startet nichts)."""
    programme = laufende_programme()
    return Lage(
        klassisch_laeuft=KLASSISCH_EXE in programme,
        neu_laeuft=NEU_EXE in programme,
        umschalter_neu=_reg("HKCU", PFAD_PREFERENCES, "UseNewOutlook") == 1,
        com_registriert=_reg("HKCR", r"Outlook.Application\CLSID") is True,
        profil=_unterschluessel(PFAD_PROFILE) > 0,
        olk_alias=os.path.lexists(str(OLK_ALIAS)),
        mailto=_progid(_reg("HKCU", PFAD_MAILTO, "ProgId")),
        eml=_progid(_reg("HKCU", PFAD_EML, "ProgId")) or _progid(_reg("HKCR", ".eml", "")),
    )


def _com_antwortet() -> bool:
    """Antwortet das laufende klassische Outlook per COM und hat es ein Konto? Hängt sich nur an, startet nie."""
    from office_outlook_com import _konten, com_lauf  # erst hier: der COM-Teil baut auf diesem Modul auf

    try:
        return bool(com_lauf(lambda app: _konten(app.Session), timeout=COM_PRUEF_SECS))
    except MailFehler:
        return False


def verfuegbar() -> bool:
    """Kann dieser Host überhaupt Mails vorbereiten (Windows)? Welches Outlook läuft, prüft erst die Anfrage."""
    return sys.platform == "win32"


def erkennen(lage: Lage | None = None, com_ok: Callable[[], bool] | None = None) -> Weg:
    """Welcher Weg gilt jetzt? Im Zweifel nie senden."""
    if lage is None and sys.platform != "win32":
        return Weg("keiner", "", "Outlook gibt es nur am Windows-PC.")
    lg = lage if lage is not None else lage_lesen()
    if lg.neu_laeuft:
        if not lg.olk_alias:
            return Weg("keiner", "", "Das neue Outlook läuft, lässt sich aber nicht ansprechen (olk.exe fehlt). Es ist nichts passiert.")
        return Weg("entwurf", "neu", NEU_GRUND)
    if lg.klassisch_laeuft:
        if not (lg.com_registriert and lg.profil):
            return Weg("keiner", "", "Outlook (klassisch) läuft, ist aber nicht für die Automatisierung eingerichtet. Es ist nichts "
                       "passiert.")
        if not (com_ok or _com_antwortet)():
            return Weg("keiner", "", "Outlook (klassisch) läuft, antwortet aber nicht (vielleicht ist dort ein Dialog offen). Bitte "
                       "gleich noch einmal versuchen.")
        if lg.umschalter_neu:
            return Weg("entwurf", "klassisch", UMSCHALTER_GRUND)
        return Weg("senden", "klassisch", SENDEN_GRUND)
    return Weg("keiner", "", ZU_GRUND)


# ---------- Karte ----------
def _groesse(n: int) -> str:
    if n < 1024:
        return f"{n} Bytes"
    if n < 1024 * 1024:
        return f"{math.ceil(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB".replace(".", ",")


def _mit_name(name: str, smtp: str) -> str:
    return f"{name} <{smtp}>" if name else smtp


def _marke(e: Empfaenger) -> str:
    marke = "EXTERN" if e.extern else "intern"
    return marke + (", Domäne in Punycode" if "xn--" in _domaene(e.smtp) else "")


def _zitiert(text_: str) -> list[str]:
    return [f"> {z}" if z else ">" for z in text_.split("\n")]


def kartentext(mail: Mail, weg: Weg, konto: dict | None, signatur: str | None) -> str:
    """Genau das, was rausgeht, als Text der Freigabekarte. Jede Zeile aus Text und Signatur trägt "> " (sie sieht so nie wie ein Kopf
    aus, etwa "An: ..." im Text)."""
    zeilen = [f"So geht es: {weg.grund}"]
    if konto:
        zeilen.append(f"Von: {_mit_name(konto.get('name', ''), konto['smtp'])}")
    zeilen += [f"{'An' if e.art == 'an' else 'Cc'}: {_mit_name(e.name, e.smtp)} ({_marke(e)})" for e in mail.empfaenger]
    zeilen.append(f"Betreff: {mail.betreff}")
    zeilen += [f"Anhang: {a.name} ({_groesse(a.groesse)}, Prüfsumme {a.sha256[:8]})" for a in mail.anhaenge] or ["Anhang: keiner"]
    zeilen += ["Text:", *_zitiert(mail.text)] if mail.text else ["Text: (leer)"]
    if weg.programm == "klassisch":
        zeilen += ["Signatur aus Outlook:", *_zitiert(signatur)] if signatur else ["Signatur: in Outlook ist keine eingerichtet"]
    else:
        zeilen.append("Signatur: fügt das neue Outlook selbst an, wenn du eine eingerichtet hast")
    return "\n".join(zeilen)


# ---------- Anhänge ----------
def anhaenge_lesen(anhaenge: tuple[Anhang, ...] | list[Anhang]) -> list[tuple[Anhang, bytes]]:
    """Inhalte der Anhänge, nur wenn Größe und SHA-256 noch stimmen (sonst MailFehler: dann geht nichts raus)."""
    gesamt, ergebnis = 0, []
    for a in anhaenge:
        try:
            daten = a.pfad.read_bytes()
        except OSError as e:
            raise MailFehler(f"Den Anhang {a.name} gibt es nicht mehr. Es ist nichts passiert.") from e
        if len(daten) != a.groesse or hashlib.sha256(daten).hexdigest() != a.sha256:
            raise MailFehler(f"Der Anhang {a.name} wurde geändert, seit W.A.I.S. ihn gespeichert hat. Es ist nichts passiert.")
        gesamt += len(daten)
        if gesamt > ANHAENGE_BYTES_MAX:
            raise MailFehler("Die Anhänge sind zusammen größer als 15 MB.")
        ergebnis.append((a, daten))
    return ergebnis


@contextmanager
def anhang_dateien(anhang_daten: list[tuple[Anhang, bytes]]) -> Iterator[list[Path]]:
    """Geprüfte Kopien der Anhänge in einem eigenen Wegwerfordner: Outlook hängt genau die Bytes an, deren Prüfsumme die Karte zeigt."""
    with tempfile.TemporaryDirectory(prefix="wais-mail-", ignore_cleanup_errors=True) as ordner:
        pfade = []
        for a, daten in anhang_daten:
            ziel = Path(ordner) / a.name
            ziel.write_bytes(daten)
            pfade.append(ziel)
        yield pfade


# ---------- Neues Outlook: Entwurf ----------
def html_text(text_: str) -> str:
    absaetze = [a for a in re.split(r"\n{2,}", text_) if a] if text_ else []
    return "".join("<p>" + "<br>".join(html.escape(z, quote=False).replace("  ", " &nbsp;") for z in a.split("\n")) + "</p>"
                   for a in absaetze)


def eml(mail: Mail, anhang_daten: list[tuple[Anhang, bytes]]) -> bytes:
    """Entwurf als .eml: "X-Unsent: 1", ohne Absender (das Konto wählt Outlook), Text und HTML, Anhänge mit ihrem Namen. Kein Bcc."""
    m = EmailMessage(policy=email_policy.SMTP)
    m["To"] = ", ".join(e.smtp for e in mail.an)
    if mail.cc:
        m["Cc"] = ", ".join(e.smtp for e in mail.cc)
    m["Subject"] = mail.betreff
    m["X-Unsent"] = "1"
    m.set_content(mail.text + "\n")
    m.add_alternative(f'<html><head><meta charset="utf-8"></head><body>{html_text(mail.text)}</body></html>', subtype="html")
    for a, daten in anhang_daten:
        haupt, unter = MIME.get(a.pfad.suffix.lower(), ("application", "octet-stream"))
        m.add_attachment(daten, maintype=haupt, subtype=unter, filename=a.name)
    return m.as_bytes()


def mailto(mail: Mail) -> str:
    """Rückfall ohne Anhang: mailto mit einzeln kodierten Werten (kein Wert kann einen weiteren Parameter anhängen)."""
    teile = []
    if mail.cc:
        teile.append("cc=" + quote(",".join(e.smtp for e in mail.cc), safe="@,"))
    teile.append("subject=" + quote(mail.betreff, safe=""))
    teile.append("body=" + quote(mail.text.replace("\n", "\r\n"), safe=""))
    return "mailto:" + quote(",".join(e.smtp for e in mail.an), safe="@,") + "?" + "&".join(teile)


def _starten(argv: list[str]) -> None:
    """Programm starten, ohne auf es zu warten (olk.exe über den Alias, Explorer mit Auswahl)."""
    if sys.platform != "win32":
        raise OSError("nur unter Windows")
    if len(argv) == 2 and argv[1].startswith("/select,"):
        befehl = f'"{argv[0]}" /select,"{argv[1][len("/select,"):]}"'  # Explorer will den Pfad in eigenen Anführungszeichen
    else:
        befehl = subprocess.list2cmdline(argv)
    subprocess.Popen(befehl, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # noqa: S603
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)


def _fenster() -> list[dict]:
    """Sichtbare Fenster des neuen Outlooks mit Titel (auch Fenster mit Besitzer: das Entwurfsfenster gehört zum Hauptfenster)."""
    if sys.platform != "win32":
        return []
    import win32api
    import win32con
    import win32gui
    import win32process

    gefunden: list[dict] = []

    def besuchen(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                try:
                    exe = Path(win32process.GetModuleFileNameEx(h, 0)).name.lower()
                finally:
                    win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001 (Prozess ohne Leserecht: nicht unseres)
                return True
            if exe == NEU_EXE:
                gefunden.append({"hwnd": hwnd, "titel": win32gui.GetWindowText(hwnd)[:200], "programm": exe})
        return True

    win32gui.EnumWindows(besuchen, None)
    return gefunden


def _passend(w: dict, betreff_: str) -> bool:
    return str(w.get("programm", "")).lower() == NEU_EXE and str(w.get("titel", "")).strip().startswith(betreff_[:60].strip())


def _aufraeumen(ordner: Path) -> None:
    grenze = time.time() - ENTWURF_AUFBEWAHREN_SECS
    for alt in ordner.glob("*.eml"):
        try:
            if alt.stat().st_mtime < grenze:
                alt.unlink()
        except OSError:
            pass


def neu_entwurf(mail: Mail, anhang_daten: list[tuple[Anhang, bytes]], *, ordner: Path | None = None,
                starten: Callable[[list[str]], None] | None = None, fenster: Callable[[], list[dict]] | None = None,
                alias: Path | None = None, warten: float = FENSTER_WARTEN_SECS) -> dict:
    """Entwurf im neuen Outlook: .eml über olk.exe (mit Anhang), sonst mailto über olk.exe (ohne Anhang) und der Anhang im Explorer."""
    ordner, starten, fenster = Path(ordner or ENTWURF_ORDNER), starten or _starten, fenster or _fenster
    alias = Path(alias or OLK_ALIAS)
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        _aufraeumen(ordner)
        vorher = {w.get("hwnd") for w in fenster() if _passend(w, mail.betreff)}
        pfad = ordner / f"{secrets.token_hex(8)}.eml"
        pfad.write_bytes(eml(mail, anhang_daten))
        starten([str(alias), str(pfad)])
    except (OSError, ValueError) as e:
        return _rueckfall(mail, anhang_daten, starten, alias, type(e).__name__)
    ende, gesehen = time.monotonic() + warten, False
    while not gesehen:
        gesehen = any(_passend(w, mail.betreff) and w.get("hwnd") not in vorher for w in fenster())
        if gesehen or time.monotonic() >= ende:
            break
        time.sleep(min(0.5, max(0.0, ende - time.monotonic())))
    if gesehen:
        summary = ("Der Entwurf ist im neuen Outlook offen" + (", mit Anhang" if anhang_daten else "") +
                   ". Prüfen und selbst auf Senden drücken.")
    else:
        summary = ("Der Entwurf ist an das neue Outlook übergeben, das Fenster ist aber noch nicht zu sehen. Er liegt in Outlook unter "
                   "Entwürfe; dort prüfen und selbst senden.")
    return {"status": "success", "weg": "eml", "anhang": bool(anhang_daten), "fenster": gesehen, "summary": summary}


def _rueckfall(mail: Mail, anhang_daten: list[tuple[Anhang, bytes]], starten: Callable[[list[str]], None], alias: Path,
               grund: str) -> dict:
    ziel = mailto(mail)
    if len(ziel) > MAILTO_MAX:
        return {"status": "error", "summary": f"Der Entwurf ließ sich nicht übergeben ({grund}), und für den Weg ohne Entwurfsdatei ist "
                "der Text zu lang. Es ist nichts passiert."}
    try:
        starten([str(alias), ziel])
    except OSError as e:
        return {"status": "error", "summary": f"Das neue Outlook ließ sich nicht öffnen ({type(e).__name__}). Es ist nichts passiert."}
    hinweis = ""
    if anhang_daten:
        hinweis = " Der Anhang liegt markiert im Explorer: bitte selbst in den Entwurf ziehen."
        try:
            starten([EXPLORER, f"/select,{anhang_daten[0][0].pfad}"])
        except OSError:
            hinweis = f" Der Anhang liegt in Dokumente\\WAIS ({anhang_daten[0][0].name}): bitte selbst anhängen."
    return {"status": "success", "weg": "mailto", "anhang": False, "fenster": False,
            "summary": ("Der Entwurf ist im neuen Outlook offen, aber ohne Anhang (der Weg über die Entwurfsdatei ging nicht)."
                        if anhang_daten else "Der Entwurf ist im neuen Outlook offen.") + hinweis + " Selbst prüfen und senden."}
