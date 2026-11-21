import { istTag, uhrzeit } from "./werkstattFristen.ts";
import { KARTEN_ID } from "./werkstattKarten.ts";
import {
  PLATZ_ZWECKE,
  TERMIN_STATUS,
  WERKZEUGE,
  WISSEN_ARTEN,
  type AktionZeile,
  type Betrieb,
  type ChecklistePunkt,
  type FreigabeKarte,
  type Ich,
  type Karte,
  type KartenListe,
  type KartenVersion,
  type LaborProfil,
  type LatenzTag,
  type Platz,
  type ProtokollAntwort,
  type ProtokollZeile,
  type Pruefung,
  type SitzungTag,
  type Termin,
  type Veroeffentlicht,
  type Werkzeug,
  type Zuordnung,
} from "./werkstattTypen.ts";

/**
 * Antworten der Schnittstelle prüfen und in die Typen der Oberfläche umsetzen (lib/werkstattTypen.ts). Jede Funktion liefert den
 * geprüften Wert oder null: Die Oberfläche zeigt bei null nie halbe Daten, sondern den Satz "Die Antwort der Werkstatt war
 * unerwartet". Fremde Felder fallen weg, Texte werden von Steuerzeichen befreit und gekürzt, nichts wird als Markup behandelt.
 * Ohne React und ohne Netz (werkstattParser.test.ts).
 */

export type Obj = Record<string, unknown>;

/** Kennungen, die die Oberfläche in einen Pfad setzt (Termine): nur Buchstaben, Ziffern, Unterstrich und Bindestrich. */
export const SICHERE_ID = /^[A-Za-z0-9_-]{1,64}$/;

export const istObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

/** Text ohne Steuerzeichen, gekürzt; leer ergibt null. */
export function kurz(v: unknown, max = 200): string | null {
  if (typeof v !== "string") return null;
  const s = v.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();
  return s ? s.slice(0, max) : null;
}

export const zahl = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const ganz = (v: unknown): number | null => (typeof v === "number" && Number.isSafeInteger(v) ? v : null);
const wahrheit = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

/** Eine Liste aus der Antwort: entweder die Antwort selbst oder das Feld mit einem der genannten Namen. */
export function listeAus(daten: unknown, schluessel: readonly string[]): unknown[] | null {
  if (Array.isArray(daten)) return daten;
  if (!istObj(daten)) return null;
  for (const s of schluessel) if (Array.isArray(daten[s])) return daten[s] as unknown[];
  return null;
}

/** Alle Zeilen müssen sich umsetzen lassen, sonst null. */
function alle<T>(zeilen: unknown[] | null, einzeln: (z: unknown) => T | null): T[] | null {
  if (!zeilen) return null;
  const aus: T[] = [];
  for (const z of zeilen) {
    const w = einzeln(z);
    if (w === null) return null;
    aus.push(w);
  }
  return aus;
}

/** JJJJ-MM-TT aus einem Datum oder Zeitstempel. */
function tagAus(v: unknown): string | null {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}(?:$|[T ])/.test(v)) return null;
  const t = v.slice(0, 10);
  return istTag(t) ? t : null;
}

// ---------- Zugang und Betrieb ----------
export function alsIch(d: unknown): Ich | null {
  if (!istObj(d)) return null;
  const erlaubt = wahrheit(d.erlaubt);
  if (erlaubt === null) return null;
  const rolle = d.rolle === "admin" || d.rolle === "mitglied" ? d.rolle : null;
  const alter = zahl(d.aal2_alter_s);
  return { rolle, aal2AlterS: alter !== null && alter >= 0 ? alter : null, erlaubt };
}

const feld = (o: unknown, name: string): unknown => (istObj(o) ? o[name] : undefined);

export function alsBetrieb(d: unknown): Betrieb | null {
  if (!istObj(d)) return null;
  const alter = zahl(d.alter_s);
  return {
    zeit: kurz(d.zeit, 40),
    alterS: alter !== null && alter >= 0 ? alter : null,
    kern: { slot: kurz(feld(d.kern, "slot"), 20), release: kurz(feld(d.kern, "release"), 60), aktiv: wahrheit(feld(d.kern, "aktiv")) },
    oberflaeche: { farbe: kurz(feld(d.oberflaeche, "farbe"), 20), version: kurz(feld(d.oberflaeche, "version"), 40) },
    installer: { version: kurz(feld(d.installer, "version"), 40) },
    kanal: { zustand: kurz(feld(d.kanal, "zustand"), 40) },
    laborDienst: { zustand: kurz(feld(d.labor_dienst, "zustand"), 40) },
  };
}

// ---------- Dashboards ----------
export function alsSitzungen(d: unknown): SitzungTag[] | null {
  return alle(listeAus(d, ["tage", "sitzungen", "zeilen"]), (z) => {
    if (!istObj(z)) return null;
    const tag = tagAus(z.tag);
    const anzahl = zahl(z.anzahl);
    if (tag === null || anzahl === null) return null;
    return { tag, anzahl, dauerP50S: zahl(z.dauer_p50_s), dauerP95S: zahl(z.dauer_p95_s), offen: zahl(z.offen) ?? 0 };
  });
}

export function alsLatenz(d: unknown): LatenzTag[] | null {
  const zeilen = listeAus(d, ["tage", "latenz", "zeilen"]) ?? (istObj(d) && zahl(d.zuege) !== null ? [d] : null);
  return alle(zeilen, (z) => {
    if (!istObj(z)) return null;
    const zuege = zahl(z.zuege);
    if (zuege === null) return null;
    return { tag: tagAus(z.tag), zuege, p50Ms: zahl(z.p50_ms), p95Ms: zahl(z.p95_ms) };
  });
}

export function alsAktionen(d: unknown): AktionZeile[] | null {
  return alle(listeAus(d, ["aktionen", "zeilen"]), (z) => {
    if (!istObj(z)) return null;
    const tool = kurz(z.tool ?? z.werkzeug, 80);
    const status = kurz(z.status, 40);
    const anzahl = zahl(z.anzahl);
    return tool && status && anzahl !== null ? { tool, status, anzahl } : null;
  });
}

// ---------- Protokolle ----------
const ZAHLEN_NAME = /^[a-z0-9_]{1,30}$/;

/** Die Zahlen einer Protokollzeile als kurzer Text: "sitzungen 1, platz 3". */
export function zahlenText(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string") return kurz(v, 80) ?? "";
  if (Array.isArray(v)) return v.map((x) => (zahl(x) !== null ? String(x) : "")).filter(Boolean).slice(0, 8).join(", ");
  if (!istObj(v)) return "";
  const teile: string[] = [];
  for (const [name, wert] of Object.entries(v)) {
    if (!ZAHLEN_NAME.test(name)) continue;
    const w = zahl(wert) !== null ? String(wert) : typeof wert === "string" && /^[\w.:-]{1,30}$/.test(wert) ? wert : null;
    if (w !== null) teile.push(`${name} ${w}`);
    if (teile.length >= 8) break;
  }
  return teile.join(", ");
}

export function alsProtokolle(d: unknown): ProtokollAntwort | null {
  const zeilen = alle(listeAus(d, ["zeilen", "eintraege", "protokolle"]), (z): ProtokollZeile | null => {
    if (!istObj(z)) return null;
    const zeit = kurz(z.zeit, 40);
    const marke = kurz(z.marke, 60);
    const stufe = kurz(z.stufe, 20);
    const code = kurz(z.code, 80);
    return zeit && marke && stufe && code ? { zeit, marke, stufe: stufe.toLowerCase(), code, zahlen: zahlenText(z.zahlen) } : null;
  });
  if (!zeilen) return null;
  const roh = istObj(d) && Array.isArray(d.marken) ? d.marken : [];
  const marken = roh.map((m) => kurz(m, 60)).filter((m): m is string => m !== null);
  return { zeilen, marken };
}

// ---------- Labor ----------
export function alsLaborStand(d: unknown): LaborProfil[] | null {
  return alle(listeAus(d, ["profile", "laborprofile", "zeilen"]), (z) => {
    if (!istObj(z)) return null;
    const art = kurz(z.art, 30);
    const aktiv = wahrheit(z.aktiv ?? z.freigeschaltet);
    if (!art || aktiv === null) return null;
    const platz = ganz(z.platz);
    return { kennung: kurz(z.kennung, 20), art, platz: platz !== null && platz >= 1 && platz <= 16 ? platz : null, aktiv, zeilen: ganz(z.zeilen) };
  });
}

export function alsTermin(z: unknown): Termin | null {
  if (!istObj(z)) return null;
  const id = typeof z.id === "string" && SICHERE_ID.test(z.id) ? z.id : null;
  const tag = tagAus(z.tag);
  const bis = tagAus(z.aufbewahrung_bis);
  const version = ganz(z.einwilligung_version);
  const status = TERMIN_STATUS.find((s) => s === z.status);
  if (!id || tag === null || bis === null || version === null || !status) return null;
  return { id, tag, beginn: uhrzeit(z.beginn), ende: uhrzeit(z.ende), einwilligungVersion: version, status, aufbewahrungBis: bis };
}

export const alsTermine = (d: unknown): Termin[] | null => alle(listeAus(d, ["termine", "zeilen"]), alsTermin);

export function alsPlaetze(d: unknown): Platz[] | null {
  return alle(listeAus(d, ["plaetze", "zeilen"]), (z) => {
    if (!istObj(z)) return null;
    const platz = ganz(z.platz);
    const zweck = PLATZ_ZWECKE.find((w) => w === z.zweck);
    if (platz === null || platz < 1 || platz > 16 || !zweck) return null;
    return { platz, zweck, kennung: kurz(z.kennung, 20), gast: kurz(z.gast, 20) };
  });
}

export function alsPunkt(z: unknown): ChecklistePunkt | null {
  if (!istObj(z)) return null;
  const nr = ganz(z.nr ?? z.id);
  const titel = kurz(z.titel, 120);
  if (nr === null || !titel) return null;
  const erledigt = wahrheit(z.erledigt) ?? (typeof z.erledigt_at === "string" && z.erledigt_at !== "");
  return { nr, titel, quelle: kurz(z.quelle, 80), faellig: tagAus(z.faellig), erledigt };
}

export const alsCheckliste = (d: unknown): ChecklistePunkt[] | null => alle(listeAus(d, ["checkliste", "eintraege", "punkte", "zeilen"]), alsPunkt);

// ---------- Karten ----------
export function alsKarte(z: unknown): Karte | null {
  if (!istObj(z)) return null;
  const id = typeof z.id === "string" && KARTEN_ID.test(z.id) ? z.id : null;
  const gruppe = kurz(z.gruppe, 30);
  const titel = kurz(z.titel, 60);
  const aufgabe = kurz(z.aufgabe, 240);
  const erwartung = kurz(z.erwartung, 240);
  const wissen = WISSEN_ARTEN.find((w) => w === z.wissen);
  const dauer = ganz(z.dauer_min);
  const stand = z.stand === "entwurf" || z.stand === "veroeffentlicht" ? z.stand : null;
  if (!id || !gruppe || !titel || !aufgabe || !erwartung || !wissen || dauer === null || !stand) return null;
  const werkzeuge = (Array.isArray(z.werkzeuge) ? z.werkzeuge : []).filter((w): w is Werkzeug => (WERKZEUGE as readonly unknown[]).includes(w));
  return {
    id,
    gruppe,
    titel,
    aufgabe,
    erwartung,
    fehler: kurz(z.fehler, 120),
    lernziel: kurz(z.lernziel, 40),
    wissen,
    wissenstext: kurz(z.wissenstext, 900),
    werkzeuge,
    dauerMin: dauer,
    stand,
  };
}

export function alsKartenListe(d: unknown): KartenListe | null {
  const karten = alle(listeAus(d, ["karten", "zeilen"]), alsKarte);
  if (!karten) return null;
  const o = istObj(d) ? d : {};
  const version = ganz(o.version);
  return { karten, version: version !== null && version > 0 ? version : null };
}

export function alsZuordnung(d: unknown): Zuordnung | null {
  const roh = istObj(d) && !Array.isArray(d) && "zuordnung" in d ? d.zuordnung : d;
  const zuordnung: Zuordnung = {};
  const setze = (platz: number | null, id: unknown): boolean => {
    if (platz === null || platz < 1 || platz > 16 || typeof id !== "string" || !KARTEN_ID.test(id)) return false;
    zuordnung[platz] = [...new Set([...(zuordnung[platz] ?? []), id])].sort();
    return true;
  };
  if (Array.isArray(roh)) {
    for (const z of roh) if (!istObj(z) || !setze(ganz(z.platz), z.karte_id ?? z.karte)) return null;
    return zuordnung;
  }
  if (istObj(roh)) {
    for (const [name, ids] of Object.entries(roh)) {
      if (!/^\d{1,2}$/.test(name) || !Array.isArray(ids)) return null;
      zuordnung[Number(name)] = [];
      for (const id of ids) if (!setze(Number(name), id)) return null;
    }
    return zuordnung;
  }
  return null;
}

export function alsVersionen(d: unknown): KartenVersion[] | null {
  return alle(listeAus(d, ["versionen", "zeilen"]), (z) => {
    if (!istObj(z)) return null;
    const version = ganz(z.version);
    const aenderungen = ganz(z.anzahl_aenderungen);
    const zeichen = ganz(z.wissen_zeichen);
    const aktiv = wahrheit(z.aktiv);
    if (version === null || aenderungen === null || zeichen === null || aktiv === null) return null;
    return { version, erstelltAt: kurz(z.erstellt_at, 40), anzahlAenderungen: aenderungen, wissenZeichen: zeichen, aktiv };
  });
}

// ---------- Veröffentlichen ----------
export function alsPruefung(d: unknown): Pruefung | null {
  if (!istObj(d)) return null;
  const ok = wahrheit(d.ok);
  const zeichen = ganz(d.zeichen);
  if (ok === null || zeichen === null || !Array.isArray(d.probleme)) return null;
  const probleme = d.probleme
    .map((p) => (typeof p === "string" ? kurz(p, 240) : istObj(p) ? kurz(p.text ?? p.meldung, 240) : null))
    .filter((p): p is string => p !== null);
  return { ok, probleme, zeichen };
}

export function alsFreigabeKarte(d: unknown): FreigabeKarte | null {
  if (!istObj(d)) return null;
  const id = typeof d.id === "string" && SICHERE_ID.test(d.id) ? d.id : null; // die Kennung kommt in einen Pfad
  const giltBis = kurz(d.gilt_bis, 40);
  if (!id || !giltBis || Number.isNaN(Date.parse(giltBis))) return null;
  const ziel = istObj(d.ziel) ? d.ziel : {};
  const aenderungen = ganz(ziel.aenderungen ?? ziel.anzahl ?? d.aenderungen ?? d.anzahl);
  const rohKarten = Array.isArray(ziel.karten) ? ziel.karten : Array.isArray(d.karten) ? d.karten : [];
  const karten = rohKarten.filter((k): k is string => typeof k === "string" && KARTEN_ID.test(k));
  return { id, giltBis, aenderungen, karten };
}

export function alsVeroeffentlicht(d: unknown): Veroeffentlicht | null {
  if (!istObj(d)) return null;
  const version = ganz(d.version);
  const zeichen = ganz(d.zeichen);
  return version !== null && version > 0 && zeichen !== null ? { version, zeichen } : null;
}
