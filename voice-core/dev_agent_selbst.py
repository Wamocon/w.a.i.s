"""Aufträge an W.A.I.S. selbst im Entwicklungs-Agenten (Wunsch von Niko vom 19.11.2026): Einhängepunkte für dev_agent.py. Speicher, Sätze und
Prüfungen stehen in selbstauftraege.py.

DevAgent erbt SelbstWeg. Es gilt nur für Admins (im Büro mit gültiger Zulassung ohne Mitglied-Stufe, sonst im lokalen Betrieb, den es nur
für Admins gibt) und nur mit Datenbank. Mitglieder und Laborprofile haben weder Werkzeuge noch Antworten.

  * Client-Nachricht selbstauftrag: liste, speichern, verwerfen, oeffnen. Antwort ist immer genau eine Servernachricht selbstauftraege.
  * Werkzeuge selbstauftrag_speichern, selbstauftraege_zeigen und selbstauftrag_verwerfen laufen wie jedes Werkzeug durch das Stimm-Gate.
  * Speichern nach Fremdinhalt (ist_fremd, im Bot turn.fremd_fuer_karte(None): im laufenden Zug und bis zum Ende der Sitzung nach einer
    nachwirkenden Fremdquelle, denn "Soll ich das speichern?" und das Ja der Person liegen in verschiedenen Zügen) markiert den Eintrag als
    unsicher; das Modell sagt es der Person.
  * Die Liste geht als Fremdinhalt zurück ans Gespräch (on_result): Titel können aus einem früheren Gespräch mit Inhalten von außen stammen.
  * Ein Eintrag wird nie vom Kern ausgeführt. Er ist ein Vorschlag; umgesetzt wird er nach dem Ja eines Admins in Claude Code, später von
    W.A.I.S. selbst.
"""

from __future__ import annotations

import re

from loguru import logger

import entwicklung_betrieb
import pc_host
import selbstauftraege as sa
from persona import clean_inline
from werkzeugkarte import KARTEN


class SelbstWeg:
    """Methoden für Aufträge an W.A.I.S. selbst; DevAgent liefert _memory, _zulassung, _selbst, _send, _buero_darf, on_result und ist_fremd."""

    def _selbst_admin(self) -> bool:
        """Darf diese Sitzung Aufträge an W.A.I.S. selbst anlegen und lesen? Im Büro nur mit Zulassung ohne Mitglied-Stufe."""
        if not pc_host.buero():
            return True  # außerhalb des Büros gibt es den DevAgent nur für Profile mit der Rolle admin (bot.py)
        zulassung = self._zulassung
        return zulassung is not None and getattr(zulassung, "mitglied", True) is False

    def selbst_aktiv(self) -> bool:
        """Gehören die Werkzeuge und die Nachricht zu dieser Sitzung (Speicher da, Admin)? Entscheidet das Anlegen der Schemas."""
        return self._selbst is not None and self._selbst_admin()

    def _selbst_grund(self, aktion: str) -> str | None:
        """Warum Aufträge an W.A.I.S. selbst gerade nicht gehen (kein Speicher, kein Admin, im Büro keine gültige Zulassung), sonst None."""
        if self._selbst is None:
            return sa.SATZ_OHNE_SPEICHER
        if not self._buero_darf(f"selbstauftrag {aktion}"):  # zuerst die Zulassung (bei jedem Schritt neu), dann die Rolle
            return entwicklung_betrieb.SATZ_KEINE_ZULASSUNG
        if not self._selbst_admin():
            return sa.SATZ_NUR_ADMIN
        return None

    # ---------- Client-Nachricht ----------
    async def selbst_nachricht(self, data: dict) -> None:
        """Client-Nachricht selbstauftrag. Eine unbekannte Aktion bleibt ohne Wirkung. Keine Ausnahme erreicht das Gespräch, die Antwort nennt
        bei einem Fehler nur einen festen Satz."""
        aktion = data.get("aktion") if isinstance(data, dict) else None
        if aktion not in sa.AKTIONEN:
            return
        satz = {"speichern": sa.SATZ_GESPEICHERT, "verwerfen": sa.SATZ_VERWORFEN, "oeffnen": sa.SATZ_GEOEFFNET}.get(aktion, "")
        liste: list[dict] | None = None
        try:
            grund = self._selbst_grund(aktion)
            if grund is None and aktion == "liste":
                liste, grund = await self._selbst.liste()
            elif grund is None and aktion == "speichern":
                _, grund = await self._selbst.speichern(self._selbstauftrag_aus(data, quelle="oberflaeche", unsicher=False))
            elif grund is None:
                nr = data.get("nr")
                grund = await (self._selbst.verwerfen(nr) if aktion == "verwerfen" else self._selbst.oeffnen(nr))
            if grund is None and aktion != "liste":
                liste = (await self._selbst.liste())[0]  # nach einem Erfolg die frische Liste
        except Exception as e:  # noqa: BLE001 (nie bis ins Gespräch; die Antwort nennt einen festen Satz, nie den Fehlertext)
            logger.error("Auftrag an W.A.I.S. selbst ({}): Ausnahme {}", aktion, type(e).__name__)
            grund, liste = sa.SATZ_INTERN, None
        await self._send(sa.antwort(aktion, grund is None, grund or satz, auftraege=liste))

    @staticmethod
    def _selbstauftrag_aus(daten: dict, *, quelle: str, unsicher: bool) -> sa.Selbstauftrag:
        """Der Auftrag aus Werkzeugargumenten oder Client-Nachricht, mit den Standards; was nicht passt, prüft auftrag_pruefen (ValueError wird
        im Speicher zu einem Satz). Eine unbekannte Art heißt ungültig, keine stille Ersetzung."""
        art = daten.get("art")
        art = "umsetzung" if art in (None, "") else (art if isinstance(art, str) and art in KARTEN else "")
        prio = daten.get("prioritaet")
        abnahme = daten.get("abnahme")
        return sa.Selbstauftrag(
            titel=daten.get("titel") if isinstance(daten.get("titel"), str) else "",
            beschreibung=daten.get("beschreibung") if isinstance(daten.get("beschreibung"), str) else "",
            art=art, prioritaet=2 if prio is None else prio,
            abnahme=tuple(abnahme) if isinstance(abnahme, (list, tuple)) else (), quelle=quelle, unsicher=unsicher)

    # ---------- Werkzeuge des Sprachmodells ----------
    async def _werkzeug_selbst_speichern(self, params) -> None:
        try:
            if (grund := self._selbst_grund("speichern")) is not None:
                await params.result_callback(sa.werkzeug_fehler(grund))
                return
            unsicher = bool(self.ist_fremd())
            nr, grund = await self._selbst.speichern(self._selbstauftrag_aus(params.arguments or {}, quelle="sprache", unsicher=unsicher))
            if grund is not None or nr is None:
                await params.result_callback(sa.werkzeug_fehler(grund or sa.SATZ_INTERN))
                return
            liste, _ = await self._selbst.liste()
            await self._send(sa.antwort("speichern", True, sa.SATZ_GESPEICHERT, auftraege=liste))
            hinweis = sa.HINWEIS_GESPEICHERT.format(nr=f"SA-{nr}") + (sa.HINWEIS_UNSICHER if unsicher else "")
            await params.result_callback({"ok": True, "nr": f"SA-{nr}", "unsicher": unsicher, "hinweis": hinweis})
        except Exception as e:  # noqa: BLE001 (nie bis ins Gespräch)
            logger.error("Werkzeug selbstauftrag_speichern: Ausnahme {}", type(e).__name__)
            await params.result_callback(sa.werkzeug_fehler(sa.SATZ_INTERN))

    async def _werkzeug_selbst_zeigen(self, params) -> None:
        try:
            if (grund := self._selbst_grund("zeigen")) is not None:
                await params.result_callback(sa.werkzeug_fehler(grund))
                return
            liste, grund = await self._selbst.liste()
            if liste is None:
                await params.result_callback(sa.werkzeug_fehler(grund or sa.SATZ_DATENBANK))
                return
            if callable(self.on_result):
                self.on_result()  # die Titel können aus einem Gespräch mit Inhalten von außen stammen: der Zug gilt als Fremdinhalt
            await params.result_callback(sa.werkzeug_liste(liste))
        except Exception as e:  # noqa: BLE001 (nie bis ins Gespräch)
            logger.error("Werkzeug selbstauftraege_zeigen: Ausnahme {}", type(e).__name__)
            await params.result_callback(sa.werkzeug_fehler(sa.SATZ_INTERN))

    async def _werkzeug_selbst_verwerfen(self, params) -> None:
        try:
            if (grund := self._selbst_grund("verwerfen")) is not None:
                await params.result_callback(sa.werkzeug_fehler(grund))
                return
            roh = (params.arguments or {}).get("nr")
            nr = clean_inline(str(roh if roh is not None else ""), 20).upper().removeprefix("SA-")
            if isinstance(roh, bool) or not re.fullmatch(r"[0-9]{1,18}", nr):  # nur ASCII-Ziffern (isdigit ließe auch "²" zu, int() wirft)
                await params.result_callback(sa.werkzeug_fehler(sa.SATZ_NICHT_GEFUNDEN))
                return
            if (grund := await self._selbst.verwerfen(int(nr))) is not None:
                await params.result_callback(sa.werkzeug_fehler(grund))
                return
            liste, _ = await self._selbst.liste()
            await self._send(sa.antwort("verwerfen", True, sa.SATZ_VERWORFEN, auftraege=liste))
            await params.result_callback({"ok": True, "nr": f"SA-{nr}", "hinweis": "Sag in einem Satz, dass der Auftrag verworfen ist."})
        except Exception as e:  # noqa: BLE001 (nie bis ins Gespräch)
            logger.error("Werkzeug selbstauftrag_verwerfen: Ausnahme {}", type(e).__name__)
            await params.result_callback(sa.werkzeug_fehler(sa.SATZ_INTERN))
