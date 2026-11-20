"""Datenbank im Speicher für die Tests: bildet die Regeln der Migration 0031 im Kleinen nach (eindeutiger Tag, Karte einmalig, genau eine
aktive Version, Prüfspur) und die Transaktion (Zustand wird bei einer Ausnahme zurückgesetzt, Transaktionen laufen nacheinander)."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from wamo_werkstatt.daten import DatenbankFehler, FreigabeKarte, KonfliktFehler, Profil

MARKER = "MARKER-7f3a91c2"


class AttrappeDB:
    def __init__(self, uhr=None):
        self.uhr = uhr or (lambda: datetime.now(timezone.utc).timestamp())
        self.profile: dict[str, Profil] = {}
        self.termine_tab: dict[str, dict] = {}
        self.plaetze_tab: dict[str, list[dict]] = {}
        self.checkliste_tab: dict[str, list[dict]] = {}
        self.karten_tab: dict[str, dict] = {}
        self.zuordnung_tab: dict[str, dict[int, list[str]]] = {}
        self.versionen_tab: list[dict] = []
        self.freigaben: dict[str, dict] = {}
        self.actions: list[dict] = []
        self.funktionen: dict[str, list[dict]] = {"sitzungen": [], "latenz": [], "aktionen": [], "labor_stand": []}
        # Daten, die der Dienst nie lesen darf (Gesprächstext, Zusammenfassung, Gedächtnis, E-Mail): der Marker-Test sucht sie in jeder Antwort
        self.geheim = {"turns.content": MARKER, "sessions.summary": MARKER, "memories.content": MARKER, "mail": f"{MARKER}@example.test"}
        self.ausfall = False
        self.buchen_fehler = False
        self.aufgeraeumt = 0
        self.schliessungen = 0
        self._sperre = asyncio.Lock()
        self._nr = 0
        self._version = 0

    # ----------------------------------------------------------------------------------------------- Transaktion
    def _zustand(self) -> dict:
        return {k: copy.deepcopy(getattr(self, k)) for k in (
            "termine_tab", "plaetze_tab", "checkliste_tab", "karten_tab", "zuordnung_tab", "versionen_tab", "freigaben", "actions", "_nr", "_version")}

    @contextlib.asynccontextmanager
    async def transaktion(self):
        async with self._sperre:
            vorher = self._zustand()
            try:
                yield self
            except BaseException:
                for k, v in vorher.items():
                    setattr(self, k, v)
                raise

    async def schliessen(self) -> None:
        self.schliessungen += 1

    def _pruefen(self) -> None:
        if self.ausfall:
            raise DatenbankFehler("Attrappe")

    # ----------------------------------------------------------------------------------------------- Anmeldung
    async def profil(self, user_id: str) -> Profil | None:
        self._pruefen()
        return self.profile.get(user_id)

    # ----------------------------------------------------------------------------------------------- Kennzahlen
    async def sitzungen(self, tage: int):
        self._pruefen()
        return list(self.funktionen["sitzungen"])

    async def latenz(self, tage: int):
        self._pruefen()
        return list(self.funktionen["latenz"])

    async def aktionen(self, tage: int):
        self._pruefen()
        return list(self.funktionen["aktionen"])

    async def labor_stand(self):
        self._pruefen()
        return list(self.funktionen["labor_stand"])

    # ----------------------------------------------------------------------------------------------- Termine
    async def termine(self):
        self._pruefen()
        return sorted((dict(t) for t in self.termine_tab.values()), key=lambda t: t["tag"], reverse=True)

    async def termin(self, termin_id: str):
        self._pruefen()
        t = self.termine_tab.get(termin_id)
        return dict(t) if t else None

    async def termin_anlegen(self, daten, admin):
        self._pruefen()
        if any(t["tag"] == daten["tag"] for t in self.termine_tab.values()):
            raise KonfliktFehler()
        zeile = {"id": str(uuid.uuid4()), **{k: daten[k] for k in ("tag", "beginn", "ende", "einwilligung_version", "status", "aufbewahrung_bis")}}
        self.termine_tab[zeile["id"]] = zeile
        return dict(zeile)

    async def termin_aendern(self, termin_id, daten):
        self._pruefen()
        if termin_id not in self.termine_tab:
            return None
        if any(t["tag"] == daten["tag"] and i != termin_id for i, t in self.termine_tab.items()):
            raise KonfliktFehler()
        self.termine_tab[termin_id].update({k: daten[k] for k in ("tag", "beginn", "ende", "einwilligung_version", "status", "aufbewahrung_bis")})
        return dict(self.termine_tab[termin_id])

    async def termin_loeschen(self, termin_id):
        self._pruefen()
        gefunden = self.termine_tab.pop(termin_id, None) is not None
        for tab in (self.plaetze_tab, self.checkliste_tab, self.zuordnung_tab):
            tab.pop(termin_id, None)
        return gefunden

    async def plaetze(self, termin_id):
        self._pruefen()
        return [dict(p) for p in self.plaetze_tab.get(termin_id, [])]

    async def plaetze_setzen(self, termin_id, plaetze):
        self._pruefen()
        self.plaetze_tab[termin_id] = [dict(p) for p in plaetze]

    async def checkliste(self, termin_id):
        self._pruefen()
        return [dict(p) for p in self.checkliste_tab.get(termin_id, [])]

    async def checkliste_anlegen(self, termin_id, daten):
        self._pruefen()
        self._nr += 1
        zeile = {"nr": self._nr, "titel": daten["titel"], "quelle": daten["quelle"], "faellig": daten["faellig"], "erledigt_at": None}
        self.checkliste_tab.setdefault(termin_id, []).append(zeile)
        return dict(zeile)

    async def checkliste_abhaken(self, termin_id, nr, erledigt, admin):
        self._pruefen()
        for p in self.checkliste_tab.get(termin_id, []):
            if p["nr"] == nr:
                p["erledigt_at"] = datetime.now(timezone.utc) if erledigt else None
                return dict(p)
        return None

    # ----------------------------------------------------------------------------------------------- Karten
    async def karten(self, *, sperren=False):
        self._pruefen()
        return [dict(k) for k in self.karten_tab.values()]

    async def karte(self, karte_id):
        self._pruefen()
        k = self.karten_tab.get(karte_id)
        return dict(k) if k else None

    async def karte_anlegen(self, karte_id, daten, admin):
        self._pruefen()
        if karte_id in self.karten_tab:
            raise KonfliktFehler()
        zeile = {"id": karte_id, **{k: daten[k] for k in ("gruppe", "titel", "aufgabe", "erwartung", "fehler", "lernziel", "wissen",
                                                           "wissenstext", "dauer_min")},
                 "werkzeuge": list(daten["werkzeuge"]), "stand": "entwurf", "geaendert_at": datetime.now(timezone.utc)}
        self.karten_tab[karte_id] = zeile
        return dict(zeile)

    async def karte_aendern(self, karte_id, daten, admin):
        self._pruefen()
        if karte_id not in self.karten_tab:
            return None
        self.karten_tab[karte_id].update({k: daten[k] for k in ("titel", "aufgabe", "erwartung", "fehler", "lernziel", "wissen", "wissenstext",
                                                                "dauer_min")})
        self.karten_tab[karte_id].update(werkzeuge=list(daten["werkzeuge"]), stand="entwurf", geaendert_at=datetime.now(timezone.utc))
        return dict(self.karten_tab[karte_id])

    async def karte_loeschen(self, karte_id):
        self._pruefen()
        if self.karten_tab.get(karte_id, {}).get("stand") != "entwurf":
            return False
        del self.karten_tab[karte_id]
        for matrix in self.zuordnung_tab.values():
            for ids in matrix.values():
                if karte_id in ids:
                    ids.remove(karte_id)
        return True

    async def zuordnung(self, termin_id):
        self._pruefen()
        return {p: list(ids) for p, ids in self.zuordnung_tab.get(termin_id, {}).items()}

    async def zuordnung_setzen(self, termin_id, matrix):
        self._pruefen()
        self.zuordnung_tab[termin_id] = {p: list(ids) for p, ids in matrix.items()}

    async def versionen(self, grenze):
        self._pruefen()
        return [{k: v[k] for k in ("version", "erstellt_at", "anzahl_aenderungen", "wissen_zeichen", "aktiv")}
                for v in sorted(self.versionen_tab, key=lambda v: -v["version"])[:grenze]]

    async def aktive_version(self):
        self._pruefen()
        return next((v["version"] for v in self.versionen_tab if v["aktiv"]), None)

    # ----------------------------------------------------------------------------------------------- Veröffentlichen
    def _karte(self, f: dict) -> FreigabeKarte:
        return FreigabeKarte(f["id"], f["admin"], f["aktion"], copy.deepcopy(f["ziel"]), f["gilt_bis"], self.uhr() > f["gilt_bis"].timestamp(),
                             f["ausgefuehrt_at"] is not None)

    async def freigabekarte_anlegen(self, admin, aktion, ziel, gilt_s):
        self._pruefen()
        assert gilt_s <= 300
        f = {"id": str(uuid.uuid4()), "admin": admin, "aktion": aktion, "ziel": dict(ziel),
             "gilt_bis": datetime.fromtimestamp(self.uhr(), tz=timezone.utc) + timedelta(seconds=gilt_s), "ausgefuehrt_at": None}
        self.freigaben[f["id"]] = f
        return self._karte(f)

    async def freigabekarte_sperren(self, karte_id):
        self._pruefen()
        f = self.freigaben.get(karte_id)
        return self._karte(f) if f else None

    async def freigabekarte_verbrauchen(self, karte_id):
        self._pruefen()
        f = self.freigaben.get(karte_id)
        if f is None or f["ausgefuehrt_at"] is not None:
            return False
        f["ausgefuehrt_at"] = datetime.now(timezone.utc)
        return True

    async def version_anlegen(self, admin, aenderungen, zeichen, karten):
        self._pruefen()
        for v in self.versionen_tab:
            v["aktiv"] = False
        self._version += 1
        self.versionen_tab.append({"version": self._version, "erstellt_at": datetime.now(timezone.utc), "anzahl_aenderungen": aenderungen,
                                   "wissen_zeichen": zeichen, "karten": copy.deepcopy(karten), "aktiv": True})
        return self._version

    async def entwuerfe_veroeffentlichen(self):
        self._pruefen()
        n = 0
        for k in self.karten_tab.values():
            if k["stand"] == "entwurf":
                k["stand"] = "veroeffentlicht"
                n += 1
        return n

    # ----------------------------------------------------------------------------------------------- Prüfspur
    async def aktion_buchen(self, user_id, tool, risiko, params, ergebnis):
        self._pruefen()
        if self.buchen_fehler:
            raise DatenbankFehler("Attrappe: Buchung")
        self.actions.append({"user_id": user_id, "tool": tool, "risk": risiko, "params": dict(params), "result": dict(ergebnis)})

    async def aufraeumen(self):
        self.aufgeraeumt += 1


def karte_roh(karte_id="W1", gruppe="Wissen", stand="entwurf", **mehr: Any) -> dict:
    """Eine Karte, wie sie in der Tabelle steht."""
    return {"id": karte_id, "gruppe": gruppe, "titel": "Titel", "aufgabe": "Aufgabe", "erwartung": "Erwartung", "fehler": None, "lernziel": None,
            "wissen": "keine", "wissenstext": None, "werkzeuge": [], "dauer_min": 3, "stand": stand, "geaendert_at": datetime.now(timezone.utc), **mehr}
