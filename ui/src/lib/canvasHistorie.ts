import { sauber } from "./nachrichten.ts"; // relativ, damit node:test diese Datei laden kann (canvasHistorie.test.ts)

/**
 * Historie des Canvas (Wunsch vom 18.11.2026): Reiter lassen sich schließen, ohne dass etwas verloren geht. Schließen blendet nur aus:
 * Das Element bleibt in der Datenbank (voice-core/canvas_historie.py liest sie) und in der Liste der geschlossenen Reiter dieser Sitzung
 * (Store wamo.canvasZu, mit dem ganzen Element, damit auch lokale Elemente wie ein hochgeladenes Bild wieder aufgehen). Die aufklappbare
 * Historie (components/CanvasHistorie.tsx) zeigt erst diese Sitzung, dann ältere Elemente aus der Datenbank. Laborkonten fragen die
 * Datenbank nicht (die Route ist für sie gesperrt), sie sehen nur ihre Sitzung.
 */

/** Ein geschlossener Reiter dieser Sitzung und wann er zuging (Date.now). */
export type Geschlossen<T> = { item: T; zu: number };

export const CANVAS_ZU_MAX = 30;
const DB_MAX = 100;
const TITEL_MAX = 120;
const NAME_MAX = 60;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const HISTORIE_ARTEN = ["dokument", "tabelle", "code", "mermaid"] as const;
export type HistorieArt = (typeof HISTORIE_ARTEN)[number];

type MitKennung = { id?: string | null; stelle?: string };

const ART_TEXT: Record<string, string> = { tabelle: "Tabelle", code: "Code", dokument: "Dokument", mermaid: "Diagramm", bild: "Bild" };

/** Anzeigename einer Art (Kopf des Elements und Einträge der Historie). */
export const artText = (art: string): string => ART_TEXT[art] ?? art;

/** Schlüssel eines Reiters: stelle (bleibt über Überarbeitungen gleich), sonst die Kennung, sonst die Position in der Leiste. */
export function canvasSchluessel(item: MitKennung, index: number): string {
  return item.stelle ?? item.id ?? `#${index}`;
}

/**
 * Geschlossene Reiter vorne in die Liste legen (der zuletzt rechts stehende zuerst). Dieselbe Kennung steht nur einmal darin, die neue
 * Fassung gewinnt; Elemente ohne Kennung bleiben getrennt. Höchstens max Einträge: verworfen nennt, was hinten herausfiel (die Oberfläche
 * gibt dann die Bilddaten frei). Die alte Liste bleibt unverändert.
 */
export function zuLegen<T extends MitKennung>(
  zu: readonly Geschlossen<T>[],
  geschlossen: readonly T[],
  jetzt: number,
  max = CANVAS_ZU_MAX,
): { zu: Geschlossen<T>[]; verworfen: T[] } {
  const neu = [...geschlossen].reverse().map((item) => ({ item, zu: jetzt }));
  const kennungen = new Set(geschlossen.map((it) => it.id).filter((id): id is string => Boolean(id)));
  const alle = [...neu, ...zu.filter((g) => !g.item.id || !kennungen.has(g.item.id))];
  return { zu: alle.slice(0, max), verworfen: alle.slice(max).map((g) => g.item) };
}

/** Ein Eintrag der Historie aus der Datenbank (eigene oder mit der Person geteilte Elemente). zeit: Date.parse oder null. */
export type HistorieEintrag = {
  id: string;
  titel: string;
  art: HistorieArt;
  zeit: number | null;
  von?: string | null;
  recht?: "lesen" | "bearbeiten";
};
export type Historie = { eigene: HistorieEintrag[]; geteilt: HistorieEintrag[] };

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Eine Zeile Text: ohne Steuer-, Bidi- und Nullbreitenzeichen, Leerraum zusammengefasst, hart gekürzt. */
function einzeilig(roh: unknown, max: number): string {
  if (typeof roh !== "string") return "";
  const t = sauber(roh.slice(0, 2000), 2000, false).replace(/\s+/g, " ").trim();
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

function zeitVon(roh: unknown): number | null {
  if (typeof roh !== "string" || roh.length > 40) return null;
  const ms = Date.parse(roh);
  return Number.isFinite(ms) ? ms : null;
}

function eintrag(roh: unknown, geteilt: boolean): HistorieEintrag | null {
  if (!isObj(roh) || typeof roh.id !== "string" || !UUID.test(roh.id)) return null;
  if (typeof roh.art !== "string" || !(HISTORIE_ARTEN as readonly string[]).includes(roh.art)) return null;
  const e: HistorieEintrag = { id: roh.id, titel: einzeilig(roh.titel, TITEL_MAX) || "Ohne Titel", art: roh.art as HistorieArt, zeit: zeitVon(roh.zeit) };
  if (geteilt) {
    e.von = einzeilig(roh.von, NAME_MAX) || null;
    e.recht = roh.recht === "bearbeiten" ? "bearbeiten" : "lesen";
  }
  return e;
}

/** Antwort von GET /wamo/api/canvas/historie prüfen; ohne beide Listen null. */
export function alsHistorie(roh: unknown): Historie | null {
  if (!isObj(roh) || !Array.isArray(roh.eigene) || !Array.isArray(roh.geteilt)) return null;
  const liste = (werte: unknown[], geteilt: boolean) =>
    werte.flatMap((v) => eintrag(v, geteilt) ?? []).slice(0, DB_MAX);
  return { eigene: liste(roh.eigene, false), geteilt: liste(roh.geteilt, true) };
}

/** Eine Zeile der aufklappbaren Historie. */
export type HistorieZeile<T> = {
  schluessel: string;
  titel: string;
  art: string;
  zeit: number | null;
  von?: string | null;
  /** geschlossener Reiter dieser Sitzung (öffnet sich ohne den Kern wieder) */
  sitzung?: Geschlossen<T>;
  /** Kennung in der Datenbank (öffnet sich über den Kern) */
  id?: string;
};

/**
 * Zeilen der Historie: erst die geschlossenen Reiter dieser Sitzung (zuletzt geschlossen zuerst), dann ältere Elemente aus der Datenbank,
 * neueste zuerst. Was gerade als Reiter offen ist, erscheint nicht; ein Element aus der Datenbank, das schon in der Sitzung steht, auch
 * nicht (eigene vor geteilten bei gleicher Kennung).
 */
export function historieZeilen<T extends MitKennung & { title: string; kind: string }>(
  zu: readonly Geschlossen<T>[],
  db: Historie | null,
  offen: readonly MitKennung[],
): { sitzung: HistorieZeile<T>[]; frueher: HistorieZeile<T>[] } {
  const offeneIds = new Set(offen.map((it) => it.id).filter((id): id is string => Boolean(id)));
  const sitzung = zu
    .filter((g) => !g.item.id || !offeneIds.has(g.item.id))
    .map((g, i) => ({ schluessel: `s-${g.item.stelle ?? g.item.id ?? `#${i}`}`, titel: g.item.title, art: g.item.kind, zeit: g.zu, sitzung: g }));
  const bekannt = new Set([...offeneIds, ...zu.map((g) => g.item.id).filter((id): id is string => Boolean(id))]);
  const frueher: HistorieZeile<T>[] = [];
  for (const e of [...(db?.eigene ?? []), ...(db?.geteilt ?? [])]) {
    if (bekannt.has(e.id)) continue;
    bekannt.add(e.id);
    frueher.push({ schluessel: `d-${e.id}`, titel: e.titel, art: e.art, zeit: e.zeit, von: e.von, id: e.id });
  }
  frueher.sort((a, b) => (b.zeit ?? 0) - (a.zeit ?? 0));
  return { sitzung, frueher };
}
