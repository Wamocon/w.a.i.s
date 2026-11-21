/**
 * Ansicht der Werkstatt: die vier Bereiche und ihre Adresse (Hash), Zeit- und Zahlentexte, Zustandswörter. Ohne React und ohne
 * Browser, damit sich alles mit node:test prüfen lässt (werkstattAnsicht.test.ts).
 */

export const BEREICHE = [
  { id: "dashboard", titel: "Dashboards", art: "lesen" },
  { id: "labor", titel: "Labor-Planer", art: "schreiben" },
  { id: "karten", titel: "Karten und Use Cases", art: "schreiben" },
  { id: "protokolle", titel: "Protokolle", art: "lesen" },
] as const;
export type BereichId = (typeof BEREICHE)[number]["id"];

/** Der Bereich zur Adresse (#labor); alles Unbekannte öffnet die Dashboards. */
export function parseBereich(hash: string): BereichId {
  const roh = (hash.startsWith("#") ? hash.slice(1) : hash).toLowerCase();
  return BEREICHE.find((b) => b.id === roh)?.id ?? "dashboard";
}

export const bereichHash = (id: BereichId): string => `#${id}`;
export const bereichTitel = (id: BereichId): string => BEREICHE.find((b) => b.id === id)?.titel ?? "";

export const TAGE_OPTIONEN = [7, 14, 30] as const;
export const STUNDEN_OPTIONEN = [1, 6, 24, 72] as const;
export const STUFEN = ["info", "warnung", "fehler"] as const;

export function anzahlText(n: number, einzahl: string, mehrzahl: string): string {
  return `${n} ${n === 1 ? einzahl : mehrzahl}`;
}

/** "vor 40 Sekunden", "vor 1 Minute", "vor 3 Stunden" aus einem Alter in Sekunden. */
export function alterText(sekunden: number | null): string {
  if (sekunden === null || !Number.isFinite(sekunden) || sekunden < 0) return "unbekannt";
  if (sekunden < 60) return `vor ${anzahlText(Math.floor(sekunden), "Sekunde", "Sekunden")}`;
  if (sekunden < 3600) return `vor ${anzahlText(Math.floor(sekunden / 60), "Minute", "Minuten")}`;
  return `vor ${anzahlText(Math.floor(sekunden / 3600), "Stunde", "Stunden")}`;
}

/** Dauer in Sekunden als "1 min 30 s". */
export function dauerText(sekunden: number | null): string {
  if (sekunden === null || !Number.isFinite(sekunden) || sekunden < 0) return "keine Angabe";
  const s = Math.round(sekunden);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return s % 60 === 0 ? `${m} min` : `${m} min ${s % 60} s`;
}

export function msText(ms: number | null): string {
  return ms === null || !Number.isFinite(ms) ? "keine Angabe" : `${Math.round(ms)} ms`;
}

/** "20.11. 14:47" in der Ortszeit; bei einem ungültigen Wert der Wert selbst. */
export function zeitpunktText(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t);
  const zwei = (n: number) => String(n).padStart(2, "0");
  return `${zwei(d.getDate())}.${zwei(d.getMonth() + 1)}. ${zwei(d.getHours())}:${zwei(d.getMinutes())}`;
}

export type ZustandArt = "ok" | "warn" | "fehler" | "neutral";

const ZUSTAENDE: Readonly<Record<string, { text: string; art: ZustandArt }>> = {
  ok: { text: "in Ordnung", art: "ok" },
  offen: { text: "offen", art: "ok" },
  an: { text: "an", art: "ok" },
  aktiv: { text: "aktiv", art: "ok" },
  bereit: { text: "bereit", art: "ok" },
  zu: { text: "zu", art: "warn" },
  gesperrt: { text: "gesperrt", art: "warn" },
  aus: { text: "aus", art: "neutral" },
  gestoert: { text: "gestört", art: "fehler" },
  fehler: { text: "Fehler", art: "fehler" },
};

/** Zustandswort der Betriebsansicht: ein bekanntes Wort bekommt Text und Art, alles andere erscheint gekürzt und neutral. */
export function zustand(wert: string | null): { text: string; art: ZustandArt } {
  if (!wert) return { text: "unbekannt", art: "neutral" };
  const schluessel = wert.toLowerCase();
  return Object.prototype.hasOwnProperty.call(ZUSTAENDE, schluessel) ? ZUSTAENDE[schluessel] : { text: wert, art: "neutral" };
}

export const STUFE_ART: Readonly<Record<string, ZustandArt>> = { info: "ok", warnung: "warn", fehler: "fehler" };

/** Die Art zu einer Stufe; alles Unbekannte (auch Namen wie "constructor") ist neutral. */
export function stufeArt(stufe: string): ZustandArt {
  return Object.prototype.hasOwnProperty.call(STUFE_ART, stufe) ? STUFE_ART[stufe] : "neutral";
}

/** Ab diesem Alter der Betriebsdatei meldet die Ansicht, dass der Sammler nichts mehr liefert. */
export const BETRIEB_ALT_S = 180;
