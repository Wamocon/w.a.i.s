/**
 * NUR FÜR TESTS: Beispielantworten des Dienstes wamo-werkstatt, Endpunkt für Endpunkt aus dem Code des API-Pakets abgeleitet
 * (werkstatt/wamo_werkstatt/routen_basis.py, routen_labor.py, routen_karten.py, routen_veroeffentlichen.py, lesen.py, labor_regeln.py,
 * karten_regeln.py, fehler.py). Die App importiert diese Datei nie. Die Kennungen sind UUIDs in Kleinbuchstaben, wie sie der Dienst
 * vergibt (eingabe.py, pfad_id).
 */

export const ID_TERMIN = "6f1c2a3e-8b4d-4f6a-9c1e-2d3b4a5c6d7e";
export const ID_TERMIN_2 = "7a2d3b4f-9c5e-4a7b-8d2f-3e4c5b6d7e8f";
export const ID_FREIGABE = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

/** GET /karten: `gruppen` ist die feste Liste des Dienstes (karten_regeln.GRUPPEN). */
export const GRUPPEN_API = { W: "Wissen", A: "Anforderungen", J: "Jira", M: "Mail", S: "Sicherheit", G: "Gespräch", E: "Eigene Gruppe" } as const;

const TERMIN = {
  id: ID_TERMIN,
  tag: "2026-12-05",
  beginn: "09:00",
  ende: "17:00",
  einwilligung_version: 1,
  status: "entwurf",
  aufbewahrung_bis: "2026-12-18",
  loeschlauf_ab: "2026-12-19",
};

const KARTE = {
  id: "W1",
  gruppe: "Wissen",
  titel: "Verifikation und Validierung",
  aufgabe: "Was ist der Unterschied zwischen Verifikation und Validierung?",
  erwartung: "Höchstens drei Sätze.",
  fehler: null,
  lernziel: null,
  wissen: "keine",
  wissenstext: null,
  werkzeuge: ["Jira"],
  dauer_min: 3,
  stand: "entwurf",
  geaendert_at: "2026-11-21T08:00:00+00:00",
};

export const API = {
  /** routen_basis.ich */
  ich: { rolle: "admin", aal2_alter_s: 42, erlaubt: true },
  /** routen_basis.betrieb mit lesen.betrieb_lesen: kern ist eine Liste je Slot, fehlende Teile sind null */
  betrieb: {
    zeit: "2026-11-21T10:00:00+00:00",
    alter_s: 30,
    kern: [
      { slot: "a", release: "v0.7.1-abc", aktiv: true },
      { slot: "b", release: "v0.7.0-def", aktiv: false },
    ],
    oberflaeche: { farbe: "gruen", version: "0.7.1" },
    installer: { version: "0.7.1" },
    kanal: { zustand: "zu" },
    labor_dienst: { zustand: "ok" },
  },
  /** routen_basis.sitzungen mit lesen.sitzungen_zeilen */
  sitzungen: {
    tage: 14,
    zeilen: [
      { tag: "2026-11-19", anzahl: 12, dauer_p50_s: 95.5, dauer_p95_s: 310, offen: 0 },
      { tag: "2026-11-20", anzahl: 31, dauer_p50_s: 120, dauer_p95_s: 400.2, offen: null },
    ],
  },
  /** routen_basis.latenz mit lesen.latenz_zeilen: tag nur, wenn die Datenbank ihn liefert */
  latenz: {
    tage: 14,
    zeilen: [
      { tag: "2026-11-19", zuege: 100, p50_ms: 1700.5, p95_ms: 3100 },
      { tag: "2026-11-20", zuege: 140, p50_ms: 1750, p95_ms: null },
    ],
  },
  /** routen_basis.aktionen mit lesen.aktionen_zeilen: status aus pending, approved, rejected, running, done, failed, blocked */
  aktionen: {
    tage: 14,
    zeilen: [
      { tool: "werkstatt_termin_anlegen", status: "done", anzahl: 3 },
      { tool: "werkstatt_karten_veroeffentlichen", status: "failed", anzahl: 1 },
    ],
  },
  /** routen_basis.protokolle: zahlen sind Zahlen, die Stufen aus lesen.STUFEN */
  protokolle: {
    stunden: 24,
    marken: ["wamo-core", "wamo-ui"],
    stufen: ["info", "warnung", "fehler"],
    zeilen: [
      { zeit: "2026-11-21T09:00:00+00:00", marke: "wamo-core", stufe: "info", code: "labor_stufe_ende", zahlen: { sitzungen: 1, platz: 3 } },
      { zeit: "2026-11-21T08:00:00+00:00", marke: "wamo-ui", stufe: "fehler", code: "farbe_fehler", zahlen: {} },
    ],
  },
  /** routen_labor.stand: kennung nur, wenn sie zur Form labor-xx passt */
  laborStand: {
    profile: [
      { kennung: "labor-01", art: "platz", platz: 1, aktiv: false, zeilen: 12 },
      { art: "schaufenster", platz: null, aktiv: true, zeilen: null },
    ],
    naechster_termin: TERMIN,
  },
  /** labor_regeln.termin_ausgabe */
  termin: TERMIN,
  /** routen_labor.termine */
  termine: { termine: [TERMIN] },
  /** routen_labor.termin_anlegen und termin_aendern (201 und 200) */
  terminAntwort: { termin: TERMIN },
  /** routen_labor.termin_loeschen */
  geloescht: { geloescht: true },
  /** routen_labor.plaetze_lesen: kennung und gast dürfen null sein */
  plaetze: {
    plaetze: [
      { platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" },
      { platz: 2, zweck: "reserve", kennung: null, gast: null },
      { platz: 15, zweck: "abnahme", kennung: "labor-15", gast: null },
    ],
  },
  /** routen_labor.checkliste_lesen mit labor_regeln.punkt_ausgabe */
  checkliste: {
    punkte: [
      { nr: 1, titel: "Zertifikat prüfen", quelle: "Runbook 9", faellig: "2026-12-01", erledigt: false, erledigt_at: null },
      { nr: 2, titel: "Karten drucken", quelle: null, faellig: null, erledigt: true, erledigt_at: "2026-11-20T10:00:00+00:00" },
    ],
  },
  /** routen_labor.checkliste_anlegen (201) und checkliste_abhaken */
  punktAntwort: { punkt: { nr: 3, titel: "Generalprobe", quelle: null, faellig: null, erledigt: false, erledigt_at: null } },
  /** routen_karten.karte_lesen, karte_anlegen (201) und karte_aendern */
  karteAntwort: { karte: KARTE },
  /** routen_karten.karten_liste */
  karten: { karten: [KARTE], gruppen: GRUPPEN_API, aktive_version: 4, zeichen: 0, grenze: 2000 },
  /** routen_karten.versionen */
  versionen: { versionen: [{ version: 4, erstellt_at: "2026-11-20T12:00:00+00:00", anzahl_aenderungen: 2, wissen_zeichen: 100, aktiv: true }] },
  /** routen_karten.zuordnung_lesen und zuordnung_setzen: Schlüssel sind Platznummern als Text */
  zuordnung: { termin: ID_TERMIN, zuordnung: { "1": ["A1", "W1"], "2": ["W1"] } },
  /** routen_veroeffentlichen.karten_pruefen */
  pruefen: { ok: true, probleme: [], zeichen: 1200, grenze: 2000, entwuerfe: ["W1"] },
  /** routen_veroeffentlichen.karte_anlegen (201): die Karte steckt in { karte } */
  freigabeKarte: {
    karte: { id: ID_FREIGABE, gilt_bis: "2026-11-21T10:04:55+00:00", aenderungen: 1, karten: ["W1"], basis_version: 4, zeichen: 1200, grenze: 2000 },
  },
  /** routen_veroeffentlichen.ausfuehren */
  ausgefuehrt: { version: 5, zeichen: 1200 },
  /** app._antwort mit fehler.WerkstattFehler.koerper */
  fehler: { code: "karte_abgelaufen", text: "Die Karte ist abgelaufen. Bitte lege eine neue an." },
} as const;
