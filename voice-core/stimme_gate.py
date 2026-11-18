"""Stimmprüfung, Regelwerk: wer in dieser Sitzung Werkzeuge auslösen darf. Ein StimmGate gehört genau einer Sitzung (also einem Profil).

Es merkt sich, wie die letzte Äußerung eingestuft wurde (stimme_pruefer.py liefert die Werte). Jedes Werkzeug außer OFFENE_WERKZEUGE fragt
vor dem Ausführen das Gate (werkzeuge_absichern, schemas_absichern): geprüft wird im Code, nicht im Prompt.
- eigen (genug Sprache, Wert hoch): erlaubt, bis vertrauen_secs danach.
- kurz ("Ja", "mach", zu wenig Sprache für "eigen"): klingt es nach der Person (Wert ab der kurzen Schwelle), gilt das Ergebnis davor weiter, aber
  nur kurz_vertrauen_secs (15 s) nach der letzten sicheren Erkennung. Klingt es nicht danach, ist es unklar (entzieht das Vertrauen,
  die Äußerung geht trotzdem ans Modell), klingt es klar fremd, fremd.
- fremd oder unklar (genug Sprache, aber nicht sicher; ebenso jede fehlgeschlagene Prüfung): gesperrt, bis die Person wieder sicher erkannt
  wird oder tippt. Spricht WAMO gleichzeitig (Echo), heißt ein niedriger Wert nur unklar.
- Getippter Text aus der Oberfläche zählt wie die eigene Stimme: die Oberfläche ist mit zweitem Faktor angemeldet (tippen_beobachten).
  Prüfergebnisse zu früheren Äußerungen überschreiben ihn nicht.

Modi (WAMO_STIMME_PRUEFUNG): aus | beobachten (messen, melden, ins Log schreiben, nichts sperren) | streng (Standard). Alles wirkt nur für ein
Profil mit eingelerntem Abdruck: ohne Abdruck wird nicht geprüft und nichts gesperrt (status fehlt), die Einwilligung ist freiwillig und
ihr Fehlen ohne Nachteil. Ausnahme (Entscheidung N10, Plan docs/ausrollen-neue-nutzer.md 4.5): PC-Werkzeuge der Mitglieder fragen zusätzlich
die Pflichtstufe (pflicht_pruefen), unabhängig vom Modus; ohne Abdruck nehmen sie nur getippte Befehle an. Streng sperrt Werkzeuge außerdem, solange für ein Profil mit Abdruck oder bei unbekanntem Stand (Datenbank nicht
lesbar) Modell oder Abdruck nicht geladen sind oder die Prüfung länger als WARTEN_WERKZEUG_SECS dauert; getippter Text geht immer.

Schwellen (alle als Schalter in der Umgebung, siehe schwellen_aus_env): Ab welchem Wert eine Äußerung die eigene Stimme ist, hängt seit der
Kalibrierung vom 17.11.2026 von ihrer Länge ab (schwelle_fuer): bis KURZ_BIS_SECS (1,5 s) Sprache WAMO_STIMME_EIGEN_MIN_KURZ (0,35), ab
LANG_AB_SECS (3 s) WAMO_STIMME_EIGEN_MIN_LANG (0,45), dazwischen linear. Befund dazu: Im Modus streng wurden über 70 % der eigenen Äußerungen
verworfen, ihre Werte lagen bei 0,4 bis 1,8 s meist bei 0,35 bis 0,60, eine zweite Person bei 0,10 bis 0,30; TitaNet streut unter 2 s stark
(Literatur: EER 2,4 % bei 3 s, 18,4 % bei 1 s, Schwelle des EER unter 1 s bei etwa 0,30). Hat das Profil eine persönliche Schwelle vom
Einlernen (speakers.voice_threshold, Migration 0025, stimme_modell.schwelle_einlernen), ersetzt sie die kurze; die lange liegt nie darunter.
Das alte WAMO_STIMME_EIGEN_MIN gilt nur noch, wo KURZ oder LANG leer sind (ist nur es gesetzt, also für beide Längen wie bisher).
WAMO_STIMME_FREMD_MAX (bis hier fremd, 0,3, für alle Längen), WAMO_STIMME_MIN_SECS (kürzere Äußerungen reichen nicht für "eigen", 1 s; sie
werden mit der kurzen Schwelle bewertet),
WAMO_STIMME_VERTRAUEN_SECS (so lange gilt "eigen" für Folgesätze, 120 s), WAMO_STIMME_KURZ_VERTRAUEN_SECS (so lange darf das Vertrauen nur aus
kurzen Äußerungen weiterlaufen, 15 s nach der letzten sicheren Erkennung). Nur für den Modus streng mit bereiter Prüfung (stimme_waechter.py,
Entscheidung vom 17.11.2026): WAMO_STIMME_NUR_EIGEN (an oder aus, Standard an: nur eine eigene Äußerung erreicht das Modell) und
WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN (an oder aus, Standard an: während WAMO spricht, unterbricht nur die eigene Stimme). Mit
WAMO_STIMME_NUR_EIGEN=aus gilt die Regel vom 16.11.2026 mit WAMO_STIMME_VERWERFEN_MAX (unklare Äußerungen unter diesem Wert verwerfen, 0,4,
an den Bereich FREMD_MAX bis EIGEN_MIN_LANG gesetzt) und WAMO_STIMME_VERWERFEN_MIN_SECS (so viel Sprache braucht eine Äußerung mindestens, damit
sie verworfen wird, 0 s).
"""

from __future__ import annotations

import asyncio
import functools
import math
import numbers
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema

from env_schalter import schalter_an, zahl_im_bereich

EIGEN, FREMD, UNKLAR, KURZ = "eigen", "fremd", "unklar", "kurz"
GETIPPT = "getippt"
MODI = ("aus", "beobachten", "streng")
STANDARD_MODUS = "streng"
# Werkzeuge, die jede Stimme auslösen darf: nichts ändern, nichts Privates zeigen
# fehler_erklaeren (fehlerbuch.py) liest nur, was in dieser Sitzung nicht ging: Es muss gerade dann gehen, wenn die Stimme nicht sicher war
OFFENE_WERKZEUGE = frozenset({"aktuelle_zeit", "websuche", "canvas_zeigen", "fehler_erklaeren"})
WARTEN_WERKZEUG_SECS = 2.0  # so lange wartet ein Werkzeug höchstens auf die laufende Prüfung
MARKE = "_wamo_stimme_gate"  # am eingepackten Handler: welches Gate ihn schon prüft
_GEWARNT: set[object] = set()  # was schon einmal gewarnt wurde (unbekannter Modus, VERWERFEN_MAX außerhalb des Bereichs)
# Schwelle für "eigen" nach Länge der Äußerung (Befund vom 17.11.2026, siehe oben): bis KURZ_BIS_SECS gilt die kurze Schwelle, ab LANG_AB_SECS
# die lange, dazwischen linear. Fest im Code, einstellbar sind nur die beiden Schwellen.
KURZ_BIS_SECS = 1.5
LANG_AB_SECS = 3.0
# So weit darf die persönliche Schwelle aus der Datenbank (speakers.voice_threshold, Migration 0025) reichen; sonst gilt sie nicht
PERSOENLICH_MIN, PERSOENLICH_MAX = 0.2, 0.8


@dataclass(frozen=True)
class Schwellen:
    # Ab hier gilt eine Äußerung als die eigene Stimme: eigen_min_kurz bis KURZ_BIS_SECS Sprache, eigen_min_lang ab LANG_AB_SECS
    eigen_min_kurz: float = 0.35
    eigen_min_lang: float = 0.45
    fremd_max: float = 0.3  # für alle Längen
    min_secs: float = 1.0
    vertrauen_secs: float = 120.0
    kurz_vertrauen_secs: float = 15.0
    # Befund 18.11.2026: Unter min_secs (1 s) lagen die eigenen Werte bei 0,14 bis 0,49, eine fremde Stimme bei 0,10 bis 0,30; der Wert
    # trennt dort nicht. Solange WAMO nicht spricht, erbt eine so kurze Äußerung deshalb das Urteil eigen, wenn die letzte sichere
    # Erkennung höchstens so lange zurückliegt (WAMO_STIMME_KURZ_ERBEN_SECS, 0 schaltet es ab). Sie zählt dann als kurz: Werkzeuge bleiben
    # nur kurz_vertrauen_secs offen. Unter kurz_erben_min (Echo, Rauschen, klar fremd) erbt nichts; der kleinste eigene Wert lag bei 0,14.
    kurz_erben_secs: float = 60.0
    kurz_erben_min: float = 0.10
    # nur für den Wächter (stimme_waechter.verwerfen, Modus streng): unklare Äußerungen unter diesem Wert verwerfen (zwischen fremd_max
    # und eigen_min_lang), und nur Äußerungen mit mindestens so viel Sprache; beides gilt nur mit nur_eigen aus
    verwerfen_max: float = 0.4
    verwerfen_min_secs: float = 0.0
    # Regeln vom 17.11.2026 (Modus streng mit bereiter Prüfung): nur eine eigene Äußerung erreicht das Modell (WAMO_STIMME_NUR_EIGEN), und
    # während WAMO spricht, unterbricht nur die eigene Stimme (WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN, stimme_waechter.py)
    nur_eigen: bool = True
    unterbrechen_nur_eigen: bool = True


def stand_nachricht(modus: str, status: str) -> dict:
    """Stand der Stimmprüfung für die Oberfläche, an einer Stelle für alle Absender (Sitzung, Einlernen, Labor)."""
    return {"type": "stimme", "status": status, "modus": modus}


def pruefmodus(wert: str | None = None) -> str:
    """Modus aus WAMO_STIMME_PRUEFUNG (oder wert). Leer oder unbekannt heißt streng, ein unbekannter Wert wird einmal gewarnt."""
    roh = ((os.getenv("WAMO_STIMME_PRUEFUNG") if wert is None else wert) or "").strip().lower()
    if not roh:
        return STANDARD_MODUS
    if roh in MODI:
        return roh
    if roh not in _GEWARNT:
        _GEWARNT.add(roh)
        logger.warning("WAMO_STIMME_PRUEFUNG hat den unbekannten Wert {!r}: es gilt {} (erlaubt: aus, beobachten, streng)", roh, STANDARD_MODUS)
    return STANDARD_MODUS


def schwellen_aus_env() -> Schwellen:
    """Schwellen aus der Umgebung. Unbrauchbares (keine Zahl, außerhalb der Grenzen) heißt Standard. Die kurze und die lange Schwelle für
    "eigen" kommen aus WAMO_STIMME_EIGEN_MIN_KURZ und WAMO_STIMME_EIGEN_MIN_LANG; fehlt einer davon, gilt dafür das alte
    WAMO_STIMME_EIGEN_MIN (ist nur dieses gesetzt, gilt es also für beide Längen wie vor dem 17.11.2026), sonst der Standard. Die kurze liegt
    nie über der langen (sonst steigt die lange auf die kurze, mit einer Warnung), und fremd_max muss unter der kurzen liegen, sonst gelten
    alle drei Standardwerte. verwerfen_max liegt von fremd_max bis zur langen Schwelle (beide Ränder erlaubt), siehe _verwerfen_max."""
    standard = Schwellen()
    alt = zahl_im_bereich("WAMO_STIMME_EIGEN_MIN", 0.35, 0.95)
    kurz = zahl_im_bereich("WAMO_STIMME_EIGEN_MIN_KURZ", 0.35, 0.95)
    lang = zahl_im_bereich("WAMO_STIMME_EIGEN_MIN_LANG", 0.35, 0.95)
    fremd = zahl_im_bereich("WAMO_STIMME_FREMD_MAX", 0.0, 0.8)
    eigen_kurz = kurz if kurz is not None else alt if alt is not None else standard.eigen_min_kurz
    eigen_lang = lang if lang is not None else alt if alt is not None else standard.eigen_min_lang
    fremd_max = standard.fremd_max if fremd is None else fremd
    if eigen_kurz > eigen_lang:
        if ("KURZ_LANG", eigen_kurz, eigen_lang) not in _GEWARNT:
            _GEWARNT.add(("KURZ_LANG", eigen_kurz, eigen_lang))
            logger.warning("WAMO_STIMME_EIGEN_MIN_KURZ ({}) liegt über WAMO_STIMME_EIGEN_MIN_LANG ({}): für lange Äußerungen gilt {}",
                           eigen_kurz, eigen_lang, eigen_kurz)
        eigen_lang = eigen_kurz
    if fremd_max >= eigen_kurz:
        logger.warning("WAMO_STIMME_FREMD_MAX ({}) muss unter der Schwelle für kurze eigene Äußerungen ({}) liegen: es gelten die Standardwerte",
                       fremd_max, eigen_kurz)
        eigen_kurz, eigen_lang, fremd_max = standard.eigen_min_kurz, standard.eigen_min_lang, standard.fremd_max
    verwerfen_min_secs = zahl_im_bereich("WAMO_STIMME_VERWERFEN_MIN_SECS", 0.0, 10.0)  # 0 ist gültig: nicht mit "or" abkürzen
    kurz_erben = zahl_im_bereich("WAMO_STIMME_KURZ_ERBEN_SECS", 0.0, 600.0)  # 0 schaltet das Erben ab: nicht mit "or" abkürzen
    return Schwellen(
        eigen_min_kurz=eigen_kurz,
        eigen_min_lang=eigen_lang,
        fremd_max=fremd_max,
        min_secs=zahl_im_bereich("WAMO_STIMME_MIN_SECS", 0.3, 10.0) or standard.min_secs,
        vertrauen_secs=zahl_im_bereich("WAMO_STIMME_VERTRAUEN_SECS", 10.0, 3600.0) or standard.vertrauen_secs,
        kurz_vertrauen_secs=zahl_im_bereich("WAMO_STIMME_KURZ_VERTRAUEN_SECS", 1.0, 120.0) or standard.kurz_vertrauen_secs,
        kurz_erben_secs=standard.kurz_erben_secs if kurz_erben is None else kurz_erben,
        verwerfen_max=_verwerfen_max(fremd_max, eigen_lang, standard.verwerfen_max),
        verwerfen_min_secs=standard.verwerfen_min_secs if verwerfen_min_secs is None else verwerfen_min_secs,
        nur_eigen=schalter_an("WAMO_STIMME_NUR_EIGEN", standard=standard.nur_eigen),
        unterbrechen_nur_eigen=schalter_an("WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN", standard=standard.unterbrechen_nur_eigen),
    )


def _verwerfen_max(fremd_max: float, eigen_lang: float, standard: float) -> float:
    """WAMO_STIMME_VERWERFEN_MAX, an den Bereich fremd_max bis zur langen Schwelle für eigen gesetzt: darunter heißt fremd_max (nur fremde
    verwerfen, so ist "0" gemeint), darüber die lange Schwelle (jede unklare verwerfen, denn unklar liegt bei jeder Länge darunter), beides
    mit einer Warnung je Wert. Leer oder keine Zahl: der Standard 0,4, ebenso in diesen Bereich gerückt."""
    wert = zahl_im_bereich("WAMO_STIMME_VERWERFEN_MAX", 0.0, 0.95)
    gesetzt = min(max(standard if wert is None else wert, fremd_max), eigen_lang)
    if wert is not None and gesetzt != wert and ("VERWERFEN_MAX", wert, fremd_max, eigen_lang) not in _GEWARNT:
        _GEWARNT.add(("VERWERFEN_MAX", wert, fremd_max, eigen_lang))
        logger.warning("WAMO_STIMME_VERWERFEN_MAX ({}) liegt außerhalb von WAMO_STIMME_FREMD_MAX ({}) bis zur Schwelle für lange eigene "
                       "Äußerungen ({}): es gilt {}", wert, fremd_max, eigen_lang, gesetzt)
    return gesetzt


def persoenliche_schwelle(wert: object) -> float | None:
    """Die persönliche Schwelle aus der Datenbank oder vom Einlernen, wenn sie brauchbar ist (endliche Zahl von PERSOENLICH_MIN bis
    PERSOENLICH_MAX), sonst None: dann gilt die kurze Schwelle aus der Umgebung."""
    if isinstance(wert, bool) or not isinstance(wert, numbers.Real):
        return None
    zahl = float(wert)
    return zahl if math.isfinite(zahl) and PERSOENLICH_MIN <= zahl <= PERSOENLICH_MAX else None


@dataclass
class StimmGate:
    modus: str = STANDARD_MODUS
    schwellen: Schwellen = field(default_factory=Schwellen)
    uhr: Callable[[], float] = time.monotonic
    abdruck: np.ndarray | None = None
    zustand: str = "laedt"  # laedt | da | fehlt | kaputt (Stand des Abdrucks in der Datenbank)
    modell_ok: bool | None = None  # nur für ein Profil mit Abdruck von Belang
    schwelle_kurz: float | None = None  # persönliche Schwelle für kurze Äußerungen (vom Einlernen, speakers.voice_threshold), sonst None
    schwelle_erlaubt: bool = True  # False: die Datenbank kann sie nicht speichern (Migration 0025 fehlt), dann wirkt auch keine
    _wer: str | None = None
    _um: float = 0.0  # Zeitpunkt der letzten sicheren Erkennung (oder des letzten Tippens)
    _nur_kurz: bool = False  # seither kamen nur kurze Äußerungen, die nach der Person klangen
    _geloescht: bool = False  # die Person hat ihren Abdruck in dieser Sitzung gelöscht (setze_abdruck mit geloescht)
    _getippt_um: float = -math.inf
    _gesprochen_um: float = -math.inf  # Ende der letzten gesprochenen Äußerung (stimme_pruefer.py), auch ohne Abdruck und im Modus aus
    _ausstehend: asyncio.Task | None = field(default=None, repr=False)

    @classmethod
    def aus_umgebung(cls) -> StimmGate:
        return cls(modus=pruefmodus(), schwellen=schwellen_aus_env())

    @property
    def hat_abdruck(self) -> bool:
        return self.abdruck is not None

    @property
    def status(self) -> str:
        """aus | fehlt (nicht eingelernt) | laedt | kaputt | bereit"""
        if self.modus == "aus":
            return "aus"
        if self.zustand == "fehlt":
            return "fehlt"
        if self.zustand == "kaputt" or self.modell_ok is False:
            return "kaputt"
        if self.zustand == "laedt" or self.modell_ok is None:
            return "laedt"
        return "bereit"

    @property
    def verwirft(self) -> bool:
        """Verwirft der Wächter Äußerungen (stimme_waechter.py)? Nur im Modus streng mit bereiter Prüfung (Abdruck und Modell geladen); ohne
        Abdruck nie, und ein Laborprofil bekommt gar kein Gate."""
        return self.modus == "streng" and self.status == "bereit"

    def nur_eigen_unterbricht(self) -> bool:
        """Unterbricht WAMO, während es spricht, nur für die eigene Stimme (WAMO_STIMME_UNTERBRECHEN_NUR_EIGEN, stimme_waechter.py)?"""
        return self.verwirft and self.schwellen.unterbrechen_nur_eigen

    def stand(self, status: str | None = None) -> dict:
        """Nachricht an die Oberfläche mit dem Stand dieses Gates (oder einem vorgegebenen, zum Beispiel laedt beim Modellstart)."""
        return stand_nachricht(self.modus, status or self.status)

    def setze_abdruck(self, abdruck: np.ndarray | None, ok: bool = True, geloescht: bool = False, schwelle: float | None = None) -> None:
        """Stand des Abdrucks nach dem Laden, Einlernen oder Löschen. ok False: nicht lesbar, es ist unbekannt, ob es einen gibt.
        geloescht: die Person hat ihn gerade gelöscht, das neue Einlernen in dieser Sitzung braucht dann denselben Nachweis wie ein Ersetzen.
        schwelle: persönliche Schwelle für kurze Äußerungen, die zu diesem Abdruck gehört (None oder unbrauchbar: die aus der Umgebung)."""
        self.abdruck = abdruck if ok else None
        self.schwelle_kurz = persoenliche_schwelle(schwelle) if self.abdruck is not None and self.schwelle_erlaubt else None
        if geloescht and self.abdruck is None:
            self._geloescht = True
        self.zustand = "kaputt" if not ok else "da" if abdruck is not None else "fehlt"
        if abdruck is None:
            self._wer = None  # ein gelöschter Abdruck lässt kein Vertrauen zurück
            self._nur_kurz = False

    @property
    def abdruck_geschuetzt(self) -> bool:
        """Es gibt einen Abdruck oder er wurde in dieser Sitzung gelöscht: Ersetzen, Löschen und neu Einlernen brauchen einen Nachweis (die erkannte
        Stimme oder eine frische Anmeldung, siehe stimme_sitzung.py), sonst könnte jemand an der angemeldeten Oberfläche den Schutz aushebeln."""
        return self.abdruck is not None or self._geloescht

    def schwelle_fuer(self, secs: float) -> float:
        """Ab diesem Wert gilt eine Äußerung mit secs Sekunden Sprache als die eigene Stimme. Kurz ist die persönliche Schwelle (wenn es
        eine gibt, nie unter fremd_max) oder eigen_min_kurz, lang eigen_min_lang (nie unter der kurzen); bis KURZ_BIS_SECS gilt die kurze,
        ab LANG_AB_SECS die lange, dazwischen linear. Unter min_secs (Urteil kurz) gilt immer die kurze."""
        s = self.schwellen
        kurz = s.eigen_min_kurz if self.schwelle_kurz is None else max(self.schwelle_kurz, s.fremd_max)
        lang = max(s.eigen_min_lang, kurz)
        if secs < s.min_secs or secs <= KURZ_BIS_SECS:
            return kurz
        if secs >= LANG_AB_SECS:
            return lang
        return kurz + (lang - kurz) * (secs - KURZ_BIS_SECS) / (LANG_AB_SECS - KURZ_BIS_SECS)

    def einstufen(self, wert: float, secs: float, ueberlappung: bool) -> str:
        """eigen: sicher die Person. fremd: sicher nicht. unklar: nicht sicher (entzieht das Vertrauen), auch eine kurze Äußerung, die nicht
        nach der Person klingt. kurz: zu wenig Sprache zum Urteilen ("Ja"), klingt aber nach der Person (das Vertrauen läuft nur begrenzt
        weiter, siehe grund_der_stimme). ueberlappung: WAMO sprach gleichzeitig, es kann Echo sein. Die Schwelle für eigen hängt von der
        Länge ab (schwelle_fuer), fremd gilt bis fremd_max für alle Längen."""
        s = self.schwellen
        if wert >= self.schwelle_fuer(secs):
            return EIGEN if secs >= s.min_secs else KURZ
        if self.erbt(wert, secs, ueberlappung):
            logger.info("Stimme: {:.2f} bei {:.1f} s ist zu kurz für ein Urteil, erbt eigen von vor {:.0f} s", wert, secs,
                        self.uhr() - self._um)
            return KURZ
        if wert <= s.fremd_max:
            return UNKLAR if ueberlappung else FREMD
        return UNKLAR

    def erbt(self, wert: float, secs: float, ueberlappung: bool) -> bool:
        """Erbt eine zu kurze Äußerung (unter min_secs) das Urteil eigen? Nur, solange WAMO nicht spricht (sonst könnte es Echo sein), nur
        ab kurz_erben_min (klar fremd erbt nie), nur nach einer sicher erkannten Stimme (nicht nach Tippen) und nur bis kurz_erben_secs
        danach (Befund 18.11.2026, siehe Schwellen)."""
        s = self.schwellen
        if ueberlappung or secs >= s.min_secs or s.kurz_erben_secs <= 0 or wert < s.kurz_erben_min or self._wer != EIGEN:
            return False
        return self.uhr() - self._um <= s.kurz_erben_secs

    def eintragen(self, urteil: str, gehoert_um: float | None = None) -> None:
        """gehoert_um: Ende der Äußerung (Uhr des Gates). Was vor getipptem Text gesagt wurde, zählt nicht mehr.
        kurz ändert das Urteil nicht, merkt sich aber, dass das Vertrauen seither nur aus kurzen Äußerungen kommt."""
        if gehoert_um is not None and gehoert_um < self._getippt_um:
            return
        if urteil == KURZ:
            self._nur_kurz = True
            return
        self._wer, self._um, self._nur_kurz = urteil, self.uhr(), False

    def getippt(self) -> None:
        self._wer = GETIPPT
        self._um = self._getippt_um = self.uhr()
        self._nur_kurz = False

    def gesprochen(self) -> None:
        """Eine gesprochene Äußerung ist zu Ende (stimme_pruefer.py, in jedem Modus und auch ohne Abdruck). Zählt nur für die Pflichtstufe:
        Wer nach dem Tippen spricht, gilt dort nicht mehr als getippt."""
        self._gesprochen_um = self.uhr()

    def pflicht_grund(self) -> str | None:
        """Pflichtstufe für PC-Befehle der Mitglieder (rechte.stimme_pflicht, Entscheidung N10), unabhängig vom Modus: Sprache nur mit
        eingelerntem Abdruck und bereiter Prüfung (dann dieselbe Regel wie grund_der_stimme), sonst nur getippter Text, und nur, solange seit
        dem Tippen niemand gesprochen hat. None heißt erlaubt, sonst der Grund. Ohne Abdruck, im Modus aus oder solange die Prüfung nicht
        bereit ist, gehen PC-Befehle eines Mitglieds also nur getippt."""
        if self._ausstehend is not None and not self._ausstehend.done():
            return "Stimmprüfung dauert zu lange"
        if self.status == "bereit":
            return self.grund_der_stimme()
        if self._wer == GETIPPT and self._getippt_um >= self._gesprochen_um:
            return self.grund_der_stimme()  # getippt gilt so lange wie eine erkannte Stimme (vertrauen_secs)
        if self.modus == "aus":
            return "Stimmprüfung ist aus, PC-Befehle nur getippt"
        if self.zustand == "fehlt":
            return "kein Stimmabdruck eingelernt, PC-Befehle nur getippt"
        return "Stimmprüfung nicht bereit, PC-Befehle nur getippt"

    async def pflicht_pruefen(self, werkzeug: str) -> dict | None:
        """Vor jedem PC-Werkzeug eines Mitglieds (pc_mitglied.py), in jedem Modus, auch aus und beobachten: None = ausführen, sonst das
        Ergebnis für das Modell."""
        if self._ausstehend and not self._ausstehend.done():
            await asyncio.wait({self._ausstehend}, timeout=WARTEN_WERKZEUG_SECS)
        grund = self.pflicht_grund()
        if grund is None:
            return None
        logger.warning("Stimmprüfung (Pflicht für Mitglieder): {} gesperrt ({})", werkzeug, grund)
        return {
            "status": "blocked",
            "grund": f"Stimmabdruck: {grund}",
            "hinweis": "PC-Befehle per Sprache gehen für dieses Profil nur mit eingelerntem Stimmabdruck und sicher erkannter Stimme. "
                       "Sonst den Befehl in der Oberfläche tippen. Nicht erneut versuchen.",
        }

    def grund_der_stimme(self) -> str | None:
        """None, wenn zuletzt die Person sprach oder tippte, sonst warum nicht."""
        if self._wer == FREMD:
            return "fremde Stimme"
        if self._wer == UNKLAR:
            return "Stimme nicht sicher erkannt"
        if self._wer is None:
            return "Stimme noch nicht erkannt"
        seit = self.uhr() - self._um
        if seit > self.schwellen.vertrauen_secs:
            return "Stimme zu lange nicht mehr erkannt"
        if self._nur_kurz and seit > self.schwellen.kurz_vertrauen_secs:
            return "Stimme nur kurz gehört, nicht sicher erkannt"
        return None

    def nicht_sicher_eigen(self) -> bool:
        """Stammt der Zug nicht sicher von der Person? Nur im Modus streng bei bereiter Prüfung (Profil mit Abdruck, Modell geladen):
        die Stimme gilt nicht als sicher erkannt (grund_der_stimme) oder die Prüfung läuft noch. Dann färbt bot.py den Zug wie
        Fremdinhalte (kein Lernen, kein Hinweis des Ja-Wächters, Markierung im Protokoll). Ohne Abdruck oder im Modus beobachten
        ändert sich nichts."""
        if self.modus != "streng" or self.status != "bereit":
            return False
        return (self._ausstehend is not None and not self._ausstehend.done()) or self.grund_der_stimme() is not None

    def stimme_vertraut(self) -> bool:
        """Zuletzt sicher an der Stimme erkannt (nicht nur getippt)."""
        return self._wer == EIGEN and self.grund_der_stimme() is None

    def verfolgen(self, task: asyncio.Task) -> None:
        self._ausstehend = task

    def _sperrgrund(self) -> str | None:
        if self._ausstehend and not self._ausstehend.done():
            return "Stimmprüfung dauert zu lange"
        status = self.status
        if status == "fehlt":
            return None  # ohne Abdruck wird nichts geprüft und nichts gesperrt
        if status == "bereit":
            return self.grund_der_stimme()
        if self._wer == GETIPPT and self.grund_der_stimme() is None:
            return None  # getippt geht auch, wenn die Prüfung nicht bereit ist
        return "Stimmprüfung nicht bereit"

    async def pruefen(self, werkzeug: str) -> dict | None:
        """Vor jedem Werkzeug: None = ausführen, sonst das Ergebnis für das Modell."""
        if self.modus == "aus" or werkzeug in OFFENE_WERKZEUGE:
            return None
        if self._ausstehend and not self._ausstehend.done():
            await asyncio.wait({self._ausstehend}, timeout=WARTEN_WERKZEUG_SECS)
        grund = self._sperrgrund()
        if grund is None:
            return None
        if self.modus == "beobachten":
            logger.info("Stimmprüfung (beobachten): {} wäre gesperrt ({})", werkzeug, grund)
            return None
        logger.warning("Stimmprüfung: {} gesperrt ({})", werkzeug, grund)
        return {
            "status": "blocked",
            "grund": f"Stimmprüfung: {grund}",
            "hinweis": "Nur die eingelernte Stimme der Person darf das auslösen. Nicht erneut versuchen.",
        }


def abgesichert(name: str | None, handler, gate: StimmGate):
    """Handler, der vorher das Gate fragt. Offene Werkzeuge und vom selben Gate schon geprüfte bleiben, wie sie sind.
    name None (ein Handler für alle Werkzeuge): geprüft wird der Name des Aufrufs."""
    if name in OFFENE_WERKZEUGE or getattr(handler, MARKE, None) is gate:
        return handler

    @functools.wraps(handler)  # übernimmt auch @tool_options (Zeitlimit usw.)
    async def geprueft(params):
        gesperrt = await gate.pruefen(name or params.function_name)
        if gesperrt is not None:
            await params.result_callback(gesperrt)
            return
        await handler(params)

    setattr(geprueft, MARKE, gate)
    return geprueft


def werkzeuge_absichern(llm, gate: StimmGate) -> None:
    """Jedes Werkzeug, das ab jetzt am LLM registriert wird, läuft durch das Gate.
    Direkt nach dem Anlegen des LLM aufrufen, vor allen register_function."""
    registrieren = llm.register_function

    def register_function(function_name, handler, *args, **kwargs):
        return registrieren(function_name, abgesichert(function_name, handler, gate), *args, **kwargs)

    llm.register_function = register_function


def schemas_absichern(schemas: list[FunctionSchema], gate: StimmGate) -> list[FunctionSchema]:
    """Werkzeuge mit eigenem Handler im Schema (Host, Bürogeräte) einmal einpacken. Pipecat registriert sie bei jedem Kontext neu;
    derselbe eingepackte Handler bleibt dabei derselbe."""
    return [
        FunctionSchema(s.name, s.description, s.properties, s.required, handler=abgesichert(s.name, s.handler, gate))
        if s.handler is not None else s
        for s in schemas
    ]


def tippen_beobachten(rtvi, gate: StimmGate) -> bool:
    """Getippter Text aus der Oberfläche (RTVI send-text) zählt wie die eigene Stimme. False, wenn Pipecat den Haken nicht mehr hat."""
    bisher = getattr(rtvi, "_handle_send_text", None)
    if bisher is None:
        logger.warning("Stimmprüfung: getippter Text nicht erkennbar (Pipecat geändert?)")
        return False

    async def send_text_behandeln(daten):
        gate.getippt()
        await bisher(daten)

    rtvi._handle_send_text = send_text_behandeln
    return True
