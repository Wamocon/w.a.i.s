/**
 * Fristen eines Labortags (Labor-Planer der Werkstatt). Ein Labortag wird einmal geplant, die Fristen werden daraus berechnet und
 * nicht gespeichert, außer der Aufbewahrung (aufbewahrung_bis): Sie ist ein Wert des Termins und darf höchstens 14 Tage nach dem
 * Labortag liegen. Vorgabe ist Tag plus 13, der Löschlauf des Dienstes beginnt einen Tag nach dem Ende der Aufbewahrung. Der Nachlauf
 * (Laborkonten löschen) beginnt am Montag nach dem Labortag, also zwei Tage danach, wenn der Labortag ein Samstag ist.
 * Alle Rechnungen laufen auf Kalendertagen in UTC, damit die Zeitzone und die Sommerzeit nichts verschieben.
 * Ohne React und ohne Netz (werkstattFristen.test.ts).
 */

export const AUFBEWAHRUNG_VORGABE_TAGE = 13;
export const AUFBEWAHRUNG_MAX_TAGE = 14;
export const NACHLAUF_TAGE = 2;

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const WOCHENTAG = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"] as const;

function tagZuMs(tag: string): number | null {
  const m = ISO.exec(tag);
  if (!m) return null;
  const [j, mo, t] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const ms = Date.UTC(j, mo - 1, t);
  const d = new Date(ms);
  // ein Datum wie 2026-02-30 rutscht in den nächsten Monat: das gilt nicht als Tag
  return d.getUTCFullYear() === j && d.getUTCMonth() === mo - 1 && d.getUTCDate() === t ? ms : null;
}

/** Ist das ein echter Kalendertag im Format JJJJ-MM-TT? */
export function istTag(wert: unknown): wert is string {
  return typeof wert === "string" && tagZuMs(wert) !== null;
}

function msZuTag(ms: number): string {
  const d = new Date(ms);
  const zwei = (n: number) => String(n).padStart(2, "0");
  return `${String(d.getUTCFullYear()).padStart(4, "0")}-${zwei(d.getUTCMonth() + 1)}-${zwei(d.getUTCDate())}`;
}

/** Der Tag n Tage nach (oder vor) dem gegebenen; null, wenn der Eingabetag kein Kalendertag ist. */
export function tagPlus(tag: string, n: number): string | null {
  const ms = tagZuMs(tag);
  if (ms === null || !Number.isInteger(n)) return null;
  return msZuTag(ms + n * 86_400_000);
}

/** Wie viele Tage liegen zwischen zwei Kalendertagen (bis minus von)? */
export function tageZwischen(von: string, bis: string): number | null {
  const a = tagZuMs(von);
  const b = tagZuMs(bis);
  return a === null || b === null ? null : Math.round((b - a) / 86_400_000);
}

export type Fristen = {
  /** Vorgabe für aufbewahrung_bis */
  aufbewahrungBis: string;
  /** Der Löschlauf des Dienstes beginnt einen Tag nach dem Ende der Aufbewahrung */
  loeschlaufAb: string;
  /** Nachlauf: Laborkonten löschen ab diesem Tag */
  nachlaufAb: string;
};

/** Die Fristen zu einem Labortag; null bei einem ungültigen Tag. bis: der gewählte Wert für die Aufbewahrung (sonst die Vorgabe). */
export function fristen(tag: string, bis?: string | null): Fristen | null {
  const vorgabe = tagPlus(tag, AUFBEWAHRUNG_VORGABE_TAGE);
  const nachlauf = tagPlus(tag, NACHLAUF_TAGE);
  if (vorgabe === null || nachlauf === null) return null;
  const gewaehlt = bis && istTag(bis) ? bis : vorgabe;
  const loesch = tagPlus(gewaehlt, 1);
  if (loesch === null) return null;
  return { aufbewahrungBis: gewaehlt, loeschlaufAb: loesch, nachlaufAb: nachlauf };
}

/** Liegt das Ende der Aufbewahrung zwischen dem Labortag und 14 Tage danach (wie die Prüfung in der Datenbank)? */
export function aufbewahrungGueltig(tag: string, bis: string): boolean {
  const d = tageZwischen(tag, bis);
  return d !== null && d >= 0 && d <= AUFBEWAHRUNG_MAX_TAGE;
}

/** "Sa 05.12.2026" für einen ISO-Tag; bei einem ungültigen Wert der Wert selbst. */
export function tagText(tag: string | null | undefined): string {
  if (!tag) return "";
  const ms = tagZuMs(tag);
  if (ms === null) return tag;
  const d = new Date(ms);
  const zwei = (n: number) => String(n).padStart(2, "0");
  return `${WOCHENTAG[d.getUTCDay()]} ${zwei(d.getUTCDate())}.${zwei(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}`;
}

/** "05.12." für einen ISO-Tag (Achsenbeschriftung). */
export function tagKurz(tag: string): string {
  const m = ISO.exec(tag);
  return m ? `${m[3]}.${m[2]}.` : tag;
}

/** Der heutige Kalendertag in der Ortszeit (die Person denkt in ihrem Kalender, nicht in UTC). */
export function heuteIso(jetzt: Date): string {
  const zwei = (n: number) => String(n).padStart(2, "0");
  return `${jetzt.getFullYear()}-${zwei(jetzt.getMonth() + 1)}-${zwei(jetzt.getDate())}`;
}

export type FaelligkeitArt = "ohne" | "offen" | "heute" | "ueberfaellig" | "erledigt";

/** Wie steht ein Punkt der Checkliste zum heutigen Tag? */
export function faelligkeit(faellig: string | null, erledigt: boolean, heute: string): FaelligkeitArt {
  if (erledigt) return "erledigt";
  if (!faellig || !istTag(faellig)) return "ohne";
  const d = tageZwischen(heute, faellig);
  if (d === null) return "ohne";
  if (d < 0) return "ueberfaellig";
  return d === 0 ? "heute" : "offen";
}

const UHRZEIT = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Gültige Uhrzeit HH:MM (auch mit Sekunden aus der Datenbank: dann wird gekürzt); sonst null. */
export function uhrzeit(wert: unknown): string | null {
  if (typeof wert !== "string") return null;
  const kurz = wert.length >= 8 && /^\d\d:\d\d:\d\d/.test(wert) ? wert.slice(0, 5) : wert;
  return UHRZEIT.test(kurz) ? kurz : null;
}

/** Liegt das Ende nach dem Beginn? Fehlt eine der beiden Zeiten, gibt es nichts zu prüfen. */
export function zeitraumGueltig(beginn: string | null, ende: string | null): boolean {
  if (!beginn || !ende) return true;
  return ende > beginn; // HH:MM lässt sich als Text vergleichen
}
