"""Stimmabdruck in der Datenbank: speakers (Migration 0001), nur das eigene Profil, nur über die Rolle wamo_core (asyncpg wie memory.py).

Eine Zeile je Profil (is_owner), darin der Abdruck (extensions.vector(192)), Zeitpunkt und Version der Einwilligung und seit Migration 0025
die persönliche Schwelle für kurze Äußerungen (voice_threshold, real, 0,2 bis 0,8; NULL heißt: es gilt WAMO_STIMME_EIGEN_MIN_KURZ). Die
Tabelle erzwingt selbst, dass ein Abdruck nur mit Einwilligung und nur für den Profilinhaber gespeichert wird (Constraints
speakers_voiceprint_consent_chk und speakers_voiceprint_owner_chk). Löschen entfernt die ganze Zeile (DSGVO Art. 17), also auch die
Schwelle. Es gibt keinen Zwischenspeicher über Profile hinweg: jeder Aufruf fragt mit der user_id des Speichers, den die Sitzung hält.

Fehlt die Spalte voice_threshold (Migration 0025 noch nicht angewandt), gilt der Stand davor: Laden liefert den Abdruck ohne Schwelle,
Speichern speichert ihn ohne Schwelle, beides ohne Fehler und mit einem Hinweis einmal je Prozess. Laborprofile kommen hier nie an (sie
bekommen keine Stimmsitzung, stimme_sitzung.StimmSitzung.fuer).

Schattenbetrieb (stimme_schatten.py, Migration 0028): Mit eingeschaltetem Schatten steht in derselben Zeile der Abdruck des zweiten Modells
(voiceprint_shadow, extensions.vector ohne feste Länge) und dessen Name (shadow_model). Gespeichert wird er nach dem Abdruck mit einer
eigenen Anweisung (schatten_speichern), gelesen nur mit eingeschaltetem Schatten (schatten_laden). Einen alten Schatten zu einem früheren
Abdruck verwirft die Datenbank selbst (Trigger speakers_schatten_verwerfen): Wer ohne Schatten neu einlernt, hinterlässt keinen veralteten.
Fehlen die Spalten (0028 noch nicht angewandt), gibt es keinen Schatten, mit einem Hinweis einmal je Prozess; der Abdruck bleibt gespeichert.

Ein Abdruck je Mikrofon (Migration 0029, Wunsch vom 18.11.2026, stimme_mikrofon.py): Je Person gibt es eine Zeile je eingelerntem
Mikrofon (Spalten mikrofon und mikrofon_name, eindeutig je user_id und mikrofon, höchstens drei, das erzwingt die Datenbank). abdruecke_laden
liest alle (Abdrücke als stimme_gate.Abdruck), abdruck_speichern mit mikrofon legt den Abdruck dieses Mikrofons an oder ersetzt nur ihn,
schatten_alle_laden liest die Schatten je Mikrofon, abdruck_loeschen mit mikrofon löscht nur dessen Zeile, ohne alle Zeilen der Person (das
ist der Widerruf). Fehlt die Spalte mikrofon (0029 noch nicht angewandt), liest abdruecke_laden wie bisher den einen Abdruck als
unbekanntes Mikrofon und meldet mehrere False; die Sitzung speichert dann ohne mikrofon wie bisher (ein Abdruck, ersetzt beim Einlernen).

Alle Funktionen werfen nie. Ein Fehler der Datenbank heißt: laden gibt (False, None), speichern und löschen geben False.
"""

from __future__ import annotations

from datetime import datetime

import asyncpg
import numpy as np
from loguru import logger

from memory import DB_ERRORS, MemoryStore
from stimme_einwilligung import EINWILLIGUNG_VERSION_MIKROFONE, EINWILLIGUNG_VERSION_SCHATTEN, einwilligung_bekannt, schatten_erlaubt
from stimme_gate import Abdruck, persoenliche_schwelle
from stimme_mikrofon import MAX_ABDRUECKE, UNBEKANNT, Mikrofon, kennung_gueltig, mikrofon_name
from stimme_modell import als_vektor, aus_vektor

MAX_NAME = 60  # speakers.name: 1 bis 60 Zeichen
OHNE_0025 = ("speakers ohne Migration 0025 (Spalte voice_threshold): persönliche Schwelle der Stimme nicht verfügbar, es gilt "
             "WAMO_STIMME_EIGEN_MIN_KURZ")
OHNE_0028 = ("speakers ohne Migration 0028 (Spalten voiceprint_shadow und shadow_model): Schatten-Abdruck nicht verfügbar, die Prüfung "
             "läuft allein mit TitaNet")
_GEMELDET: set[str] = set()  # Hinweise, die schon einmal im Log stehen (einmal je Prozess)
_spalte_da = True  # gab es die Spalte voice_threshold bei der letzten Abfrage dieses Prozesses (ein Schema je Prozess)?


def _bereit(speicher: MemoryStore) -> bool:
    return bool(speicher.enabled)


def _einmal_melden(hinweis: str) -> None:
    if hinweis not in _GEMELDET:
        _GEMELDET.add(hinweis)
        logger.warning(hinweis)


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


async def abdruecke_laden(speicher: MemoryStore) -> tuple[bool, list[Abdruck], bool | None]:
    """(ok, Abdrücke, mehrere): alle Abdrücke des Profils, einer je Mikrofon, der älteste zuerst (höchstens MAX_ABDRUECKE, bei mehr die
    neuesten). mehrere: True mit Migration 0029, False ohne (dann höchstens ein Abdruck mit dem unbekannten Mikrofon, gelesen wie
    abdruck_mit_schwelle_laden), None bei einem Fehler. ok False: nicht lesbar (Datenbank, Format), dann ist unbekannt, ob es Abdrücke gibt."""
    if not _bereit(speicher):
        return False, [], None
    db = speicher.db
    try:
        zeilen = await db.fetch(
            f"select mikrofon, mikrofon_name as name, voiceprint::text as abdruck, voice_threshold as schwelle, enrolled_at as am "
            f"from {db.t('speakers')} where user_id = $1::uuid and is_owner and voiceprint is not null "
            "order by enrolled_at desc, id desc limit $2",
            speicher.user_id, MAX_ABDRUECKE,
        )
    except asyncpg.UndefinedColumnError:
        ok, abdruck, schwelle = await abdruck_mit_schwelle_laden(speicher)
        if not ok:
            return False, [], None
        return True, ([Abdruck(abdruck, schwelle=schwelle)] if abdruck is not None else []), False
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gelesen ({})", type(e).__name__)
        return False, [], None
    _schwelle_spalte(True)  # 0029 braucht 0025: die Spalte der Schwelle ist da
    liste: list[Abdruck] = []
    for zeile in reversed(zeilen):
        vektor = aus_vektor(zeile["abdruck"])
        kennung = zeile["mikrofon"]
        if vektor is None or not kennung_gueltig(kennung):
            logger.warning("Stimmabdruck in der Datenbank hat das falsche Format")
            return False, [], True
        roh = zeile["schwelle"]
        schwelle = persoenliche_schwelle(roh)
        if roh is not None and schwelle is None:
            logger.warning("Stimmabdruck: persönliche Schwelle in der Datenbank unbrauchbar, es gilt WAMO_STIMME_EIGEN_MIN_KURZ")
        name = mikrofon_name(zeile["name"]) if kennung != UNBEKANNT else None
        am = zeile["am"] if isinstance(zeile["am"], datetime) else None
        liste.append(Abdruck(vektor, Mikrofon(kennung, name), schwelle=schwelle, am=am))
    return True, liste, True


async def schatten_alle_laden(speicher: MemoryStore, modell: str, dim: int, *, mehrere: bool) -> dict[str, np.ndarray]:
    """Schatten-Abdrücke je Kennung des Mikrofons, nur vom Modell modell, mit dim Werten und zu Abdrücken mit stimme-2 oder stimme-3.
    Ohne Migration 0029 (mehrere False) höchstens einer für das unbekannte Mikrofon (schatten_laden). Fehler oder ohne 0028: keiner."""
    if not mehrere:
        schatten = await schatten_laden(speicher, modell, dim)
        return {UNBEKANNT: schatten} if schatten is not None else {}
    if not _bereit(speicher):
        return {}
    db = speicher.db
    try:
        zeilen = await db.fetch(
            f"select mikrofon, voiceprint_shadow::text as schatten, shadow_model as modell from {db.t('speakers')} "
            "where user_id = $1::uuid and is_owner and voiceprint is not null and voiceprint_shadow is not null "
            "and consent_text_version = any($2::text[])",
            speicher.user_id, [EINWILLIGUNG_VERSION_SCHATTEN, EINWILLIGUNG_VERSION_MIKROFONE],
        )
    except asyncpg.UndefinedColumnError:
        _einmal_melden(OHNE_0028)
        return {}
    except DB_ERRORS as e:
        logger.info("Stimmschatten: Abdrücke nicht gelesen ({})", type(e).__name__)
        return {}
    ergebnis: dict[str, np.ndarray] = {}
    for zeile in zeilen:
        if zeile["modell"] != modell:
            logger.info("Stimmschatten: gespeicherter Abdruck stammt von einem anderen Modell, für den Schatten bitte neu einlernen")
            continue
        if (schatten := aus_vektor(zeile["schatten"], dim)) is not None and kennung_gueltig(zeile["mikrofon"]):
            ergebnis[zeile["mikrofon"]] = schatten
    return ergebnis


async def schatten_laden(speicher: MemoryStore, modell: str, dim: int) -> np.ndarray | None:
    """Der Schatten-Abdruck des Profils, nur wenn er vom Modell modell stammt, dim Werte hat und der Abdruck mit der Einwilligung stimme-2
    gespeichert ist; sonst, ohne Abdruck, bei einem Fehler oder ohne Migration 0028 None (der Schatten misst dann nichts)."""
    if not _bereit(speicher):
        return None
    db = speicher.db
    try:
        zeile = await db.fetchrow(
            f"select voiceprint_shadow::text as schatten, shadow_model as modell from {db.t('speakers')} "
            "where user_id = $1::uuid and is_owner and voiceprint is not null and consent_text_version = $2 limit 1",
            speicher.user_id, EINWILLIGUNG_VERSION_SCHATTEN,
        )
    except asyncpg.UndefinedColumnError:
        _einmal_melden(OHNE_0028)
        return None
    except DB_ERRORS as e:
        logger.info("Stimmschatten: Abdruck nicht gelesen ({})", type(e).__name__)
        return None
    if zeile is None or zeile["schatten"] is None:
        return None
    if zeile["modell"] != modell:
        logger.info("Stimmschatten: gespeicherter Abdruck stammt von einem anderen Modell, für den Schatten bitte neu einlernen")
        return None
    return aus_vektor(zeile["schatten"], dim)


async def schatten_speichern(speicher: MemoryStore, schatten: np.ndarray, modell: str, mikrofon: Mikrofon | None = None) -> bool:
    """Schreibt den Schatten-Abdruck in die Zeile des Abdrucks (nur mit Abdruck und Einwilligung stimme-2, mit mikrofon in die Zeile dieses
    Mikrofons und auch mit stimme-3). True: geschrieben. Fehlen die Spalten (Migration 0028) oder geht es schief: False mit einem Hinweis,
    der Abdruck selbst bleibt."""
    if not _bereit(speicher):
        return False
    db = speicher.db
    try:
        if mikrofon is None:
            antwort = await db.execute(
                f"update {db.t('speakers')} set voiceprint_shadow = $2::text::extensions.vector, shadow_model = $3 "
                "where user_id = $1::uuid and is_owner and voiceprint is not null and consent_text_version = $4",
                speicher.user_id, als_vektor(schatten), modell, EINWILLIGUNG_VERSION_SCHATTEN,
            )
        else:
            antwort = await db.execute(
                f"update {db.t('speakers')} set voiceprint_shadow = $2::text::extensions.vector, shadow_model = $3 "
                "where user_id = $1::uuid and is_owner and voiceprint is not null and consent_text_version = any($4::text[]) "
                "and mikrofon = $5",
                speicher.user_id, als_vektor(schatten), modell, [EINWILLIGUNG_VERSION_SCHATTEN, EINWILLIGUNG_VERSION_MIKROFONE],
                mikrofon.kennung,
            )
    except asyncpg.UndefinedColumnError:
        _einmal_melden(OHNE_0028)
        return False
    except DB_ERRORS as e:
        logger.info("Stimmschatten: Abdruck nicht gespeichert ({})", type(e).__name__)
        return False
    return str(antwort) == "UPDATE 1"


async def abdruck_speichern(
    speicher: MemoryStore, abdruck: np.ndarray, *, version: str | None, name: str, einwilligung_am: datetime | None,
    schwelle: float | None = None, schatten: np.ndarray | None = None, schatten_modell: str | None = None,
    mikrofon: Mikrofon | None = None,
) -> bool:
    """Legt den Abdruck des Profils an oder ersetzt ihn, mit Zeitpunkt und Version der Einwilligung und der persönlichen Schwelle (None oder
    unbrauchbar: NULL, eine alte Schwelle gilt für einen neuen Abdruck nie). Ohne Einwilligung geschieht nichts. Fehlt die Spalte der Schwelle
    (Migration 0025), wird der Abdruck ohne sie gespeichert. Mit schatten und schatten_modell und nur mit der Einwilligung stimme-2 oder
    stimme-3 danach der Schatten-Abdruck (schatten_speichern); scheitert nur er, gilt das Speichern trotzdem als gelungen.
    mikrofon (Migration 0029): legt den Abdruck dieses Mikrofons an oder ersetzt nur ihn; die anderen Mikrofone bleiben. Ohne 0029 oder
    beim vierten Mikrofon (die Datenbank lehnt ab) wird nichts gespeichert. Ohne mikrofon wie vor 0029: ein Abdruck je Person."""
    if mikrofon is None:
        gespeichert = await _abdruck_speichern(speicher, abdruck, version=version, name=name, einwilligung_am=einwilligung_am,
                                               schwelle=schwelle)
    else:
        gespeichert = await _mikrofon_speichern(speicher, abdruck, version=version, name=name, einwilligung_am=einwilligung_am,
                                                schwelle=schwelle, mikrofon=mikrofon)
    if gespeichert and schatten is not None and schatten_modell and schatten_erlaubt(version):
        await schatten_speichern(speicher, schatten, schatten_modell, mikrofon)
    return gespeichert


async def _mikrofon_speichern(
    speicher: MemoryStore, abdruck: np.ndarray, *, version: str | None, name: str, einwilligung_am: datetime | None,
    schwelle: float | None, mikrofon: Mikrofon,
) -> bool:
    if not _bereit(speicher) or not einwilligung_bekannt(version) or einwilligung_am is None or not kennung_gueltig(mikrofon.kennung):
        return False
    db = speicher.db
    anzeige = (name or "").strip()[:MAX_NAME] or "Profil"
    geraet = mikrofon_name(mikrofon.name) if mikrofon.kennung != UNBEKANNT else None
    try:
        antwort = await db.execute(
            f"insert into {db.t('speakers')} (user_id, name, is_owner, voiceprint, consent_at, consent_text_version, enrolled_at, "
            "voice_threshold, mikrofon, mikrofon_name) values ($1::uuid, $2, true, $3::text::extensions.vector, $5::timestamptz, $4, now(), "
            "$6::real, $7, $8) on conflict (user_id, mikrofon) where is_owner do update set name = excluded.name, "
            "voiceprint = excluded.voiceprint, consent_at = excluded.consent_at, consent_text_version = excluded.consent_text_version, "
            "enrolled_at = excluded.enrolled_at, voice_threshold = excluded.voice_threshold, mikrofon_name = excluded.mikrofon_name",
            speicher.user_id, anzeige, als_vektor(abdruck), version, einwilligung_am, persoenliche_schwelle(schwelle), mikrofon.kennung, geraet,
        )
    except asyncpg.UndefinedColumnError:
        logger.warning("Stimmabdruck: nicht gespeichert, speakers ohne Migration 0029 (Spalte mikrofon)")
        return False
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gespeichert ({})", type(e).__name__)
        return False
    return str(antwort).startswith("INSERT")


async def _abdruck_speichern(
    speicher: MemoryStore, abdruck: np.ndarray, *, version: str | None, name: str, einwilligung_am: datetime | None,
    schwelle: float | None,
) -> bool:
    if not _bereit(speicher) or not einwilligung_bekannt(version) or einwilligung_am is None:
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


async def abdruck_loeschen(speicher: MemoryStore, mikrofon: str | None = None) -> bool:
    """Entfernt die Zeilen des Profils vollständig (Abdruck, Einwilligung, Name, Schwelle, Schatten), ohne mikrofon alle (der Widerruf),
    mit der Kennung eines Mikrofons nur dessen Zeile (Migration 0029; ohne sie False). Nichts zu löschen zählt als Erfolg."""
    if not _bereit(speicher):
        return False
    db = speicher.db
    try:
        if mikrofon is None:
            await db.execute(f"delete from {db.t('speakers')} where user_id = $1::uuid and is_owner", speicher.user_id)
        else:
            await db.execute(f"delete from {db.t('speakers')} where user_id = $1::uuid and is_owner and mikrofon = $2", speicher.user_id,
                             mikrofon)
    except DB_ERRORS as e:
        logger.warning("Stimmabdruck: nicht gelöscht ({})", type(e).__name__)
        return False
    logger.info("Stimmabdruck gelöscht ({})", "alle" if mikrofon is None else "ein Mikrofon")
    return True
