"""Stimmabdruck in der Datenbank: speakers (Migration 0001), nur das eigene Profil, nur über die Rolle wamo_core (asyncpg wie memory.py).

Eine Zeile je Profil (is_owner), darin der Abdruck (extensions.vector(192)), Zeitpunkt und Version der Einwilligung und seit Migration 0025
die persönliche Schwelle für kurze Äußerungen (voice_threshold, real, 0,2 bis 0,8; NULL heißt: es gilt WAMO_STIMME_EIGEN_MIN_KURZ). Die
Tabelle erzwingt selbst, dass ein Abdruck nur mit Einwilligung und nur für den Profilinhaber gespeichert wird (Constraints
speakers_voiceprint_consent_chk und speakers_voiceprint_owner_chk). Löschen entfernt die ganze Zeile (DSGVO Art. 17), also auch die
Schwelle. Es gibt keinen Zwischenspeicher über Profile hinweg: jeder Aufruf fragt mit der user_id des Speichers, den die Sitzung hält.

Fehlt die Spalte voice_threshold (Migration 0025 noch nicht angewandt), gilt der Stand davor: Laden liefert den Abdruck ohne Schwelle,
Speichern speichert ihn ohne Schwelle, beides ohne Fehler und mit einem Hinweis einmal je Prozess. Laborprofile kommen hier nie an (sie
bekommen keine Stimmsitzung, stimme_sitzung.StimmSitzung.fuer).

Alle Funktionen werfen nie. Ein Fehler der Datenbank heißt: laden gibt (False, None), speichern und löschen geben False.
"""

from __future__ import annotations

from datetime import datetime

import asyncpg
import numpy as np
from loguru import logger

from memory import DB_ERRORS, MemoryStore
from stimme_einwilligung import einwilligung_gilt
from stimme_gate import persoenliche_schwelle
from stimme_modell import als_vektor, aus_vektor

MAX_NAME = 60  # speakers.name: 1 bis 60 Zeichen
OHNE_0025 = ("speakers ohne Migration 0025 (Spalte voice_threshold): persönliche Schwelle der Stimme nicht verfügbar, es gilt "
             "WAMO_STIMME_EIGEN_MIN_KURZ")
_GEMELDET: set[str] = set()  # Hinweise, die schon einmal im Log stehen (einmal je Prozess)
_spalte_da = True  # gab es die Spalte voice_threshold bei der letzten Abfrage dieses Prozesses (ein Schema je Prozess)?


def _bereit(speicher: MemoryStore) -> bool:
    return bool(speicher.enabled)


def _schwelle_spalte(da: bool) -> None:
    global _spalte_da
    _spalte_da = da
    if not da and OHNE_0025 not in _GEMELDET:
        _GEMELDET.add(OHNE_0025)
        logger.warning(OHNE_0025)


def schwelle_speicherbar() -> bool:
    """Kann eine persönliche Schwelle gespeichert werden (Spalte voice_threshold bei der letzten Abfrage da)? Sonst lässt die Sitzung eine
    gerade berechnete Schwelle weg (stimme_gate.StimmGate.schwelle_erlaubt): ohne Migration 0025 läuft alles wie mit der Schwelle aus der
    Umgebung, auch in der Sitzung des Einlernens."""
    return _spalte_da


async def abdruck_laden(speicher: MemoryStore) -> tuple[bool, np.ndarray | None]:
    """(ok, Abdruck). ok False: nicht lesbar (Datenbank, Format), dann ist unbekannt, ob es einen Abdruck gibt. (True, None): sicher keiner."""
    ok, abdruck, _ = await abdruck_mit_schwelle_laden(speicher)
    return ok, abdruck


async def abdruck_mit_schwelle_laden(speicher: MemoryStore) -> tuple[bool, np.ndarray | None, float | None]:
    """(ok, Abdruck, persönliche Schwelle) wie abdruck_laden, dazu die Schwelle aus derselben Zeile (None: keine, unbrauchbar oder die
    Spalte fehlt)."""
    if not _bereit(speicher):
        return False, None, None
    db = speicher.db
    abfrage = (f"select voiceprint::text as abdruck, {{schwelle}} as schwelle from {db.t('speakers')} "
               "where user_id = $1::uuid and is_owner and voiceprint is not null limit 1")
    try:
        try:
            zeile = await db.fetchrow(abfrage.format(schwelle="voice_threshold"), speicher.user_id)
            _schwelle_spalte(True)
        except asyncpg.UndefinedColumnError:
            _schwelle_spalte(False)
            zeile = await db.fetchrow(abfrage.format(schwelle="null::real"), speicher.user_id)
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gelesen ({})", type(e).__name__)
        return False, None, None
    if zeile is None:
        return True, None, None
    abdruck = aus_vektor(zeile["abdruck"])
    if abdruck is None:
        logger.warning("Stimmabdruck in der Datenbank hat das falsche Format")
        return False, None, None
    roh = zeile["schwelle"]
    schwelle = persoenliche_schwelle(roh)
    if roh is not None and schwelle is None:
        logger.warning("Stimmabdruck: persönliche Schwelle in der Datenbank unbrauchbar, es gilt WAMO_STIMME_EIGEN_MIN_KURZ")
    return True, abdruck, schwelle


async def abdruck_speichern(
    speicher: MemoryStore, abdruck: np.ndarray, *, version: str | None, name: str, einwilligung_am: datetime | None,
    schwelle: float | None = None,
) -> bool:
    """Legt den Abdruck des Profils an oder ersetzt ihn, mit Zeitpunkt und Version der Einwilligung und der persönlichen Schwelle (None oder
    unbrauchbar: NULL, eine alte Schwelle gilt für einen neuen Abdruck nie). Ohne Einwilligung geschieht nichts. Fehlt die Spalte der Schwelle
    (Migration 0025), wird der Abdruck ohne sie gespeichert."""
    if not _bereit(speicher) or not einwilligung_gilt(version) or einwilligung_am is None:
        return False
    db = speicher.db
    anzeige = (name or "").strip()[:MAX_NAME] or "Profil"
    werte = (speicher.user_id, anzeige, als_vektor(abdruck), version, einwilligung_am)
    gemeinsam = ("on conflict (user_id) where is_owner do update set name = excluded.name, voiceprint = excluded.voiceprint, "
                 "consent_at = excluded.consent_at, consent_text_version = excluded.consent_text_version, enrolled_at = excluded.enrolled_at")
    try:
        try:
            antwort = await db.execute(
                f"insert into {db.t('speakers')} (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, "
                "voice_threshold) values ($1::uuid, $2, true, $3::text::extensions.vector, $5::timestamptz, $4, now(), $6::real) "
                f"{gemeinsam}, voice_threshold = excluded.voice_threshold",
                *werte, persoenliche_schwelle(schwelle),
            )
            _schwelle_spalte(True)
        except asyncpg.UndefinedColumnError:
            _schwelle_spalte(False)
            antwort = await db.execute(
                f"insert into {db.t('speakers')} (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at) "
                f"values ($1::uuid, $2, true, $3::text::extensions.vector, $5::timestamptz, $4, now()) {gemeinsam}",
                *werte,
            )
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gespeichert ({})", type(e).__name__)
        return False
    return str(antwort).startswith("INSERT")


async def abdruck_loeschen(speicher: MemoryStore) -> bool:
    """Entfernt die Zeile des Profils vollständig (Abdruck, Einwilligung, Name, Schwelle). Nichts zu löschen zählt als Erfolg."""
    if not _bereit(speicher):
        return False
    db = speicher.db
    try:
        await db.execute(f"delete from {db.t('speakers')} where user_id = $1::uuid and is_owner", speicher.user_id)
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gelöscht ({})", type(e).__name__)
        return False
    logger.info("Stimmabdruck gelöscht")
    return True
