import { AUFBEWAHRUNG_VORGABE_TAGE, aufbewahrungGueltig, istTag, tagPlus, uhrzeit, zeitraumGueltig } from "./werkstattFristen.ts";
import { normalisieren } from "./werkstattKarten.ts";
import {
  PLATZ_ZWECKE,
  TERMIN_STATUS,
  type ChecklisteEingabe,
  type Platz,
  type PlatzZweck,
  type Termin,
  type TerminEingabe,
  type TerminStatus,
} from "./werkstattTypen.ts";

/**
 * Formulare des Labor-Planers: Termin, Plätze und Checkliste. Die Prüfung entspricht den Regeln der Tabellen (labor_termine,
 * labor_plaetze, labor_checkliste) und erspart nur sinnlose Aufrufe; entschieden wird im Dienst und in der Datenbank. Ohne React und
 * ohne Netz (werkstattLabor.test.ts).
 */

export type LaborProblem = { feld: string; text: string };

// ---------- Termin ----------
export type TerminFormular = {
  tag: string;
  beginn: string;
  ende: string;
  version: string;
  status: TerminStatus;
  aufbewahrungBis: string;
  /** Wurde die Aufbewahrung von Hand gewählt? Dann folgt sie dem Labortag nicht mehr. */
  bisVonHand: boolean;
};

export const LABORTERMIN_STATUS_TEXT: Readonly<Record<TerminStatus, string>> = {
  entwurf: "Entwurf",
  freigegeben: "Freigegeben",
  laufend: "Laufend",
  nachlauf: "Nachlauf",
  abgeschlossen: "Abgeschlossen",
};

export function leererTermin(): TerminFormular {
  return { tag: "", beginn: "", ende: "", version: "1", status: "entwurf", aufbewahrungBis: "", bisVonHand: false };
}

export function terminFormular(t: Termin): TerminFormular {
  return {
    tag: t.tag,
    beginn: t.beginn ?? "",
    ende: t.ende ?? "",
    version: String(t.einwilligungVersion),
    status: t.status,
    aufbewahrungBis: t.aufbewahrungBis,
    bisVonHand: t.aufbewahrungBis !== tagPlus(t.tag, AUFBEWAHRUNG_VORGABE_TAGE),
  };
}

/** Ändert den Labortag; die Aufbewahrung folgt mit (Tag plus 13), solange niemand sie von Hand gewählt hat. */
export function mitTag(f: TerminFormular, tag: string): TerminFormular {
  const vorgabe = istTag(tag) ? (tagPlus(tag, AUFBEWAHRUNG_VORGABE_TAGE) ?? "") : "";
  return { ...f, tag, aufbewahrungBis: f.bisVonHand ? f.aufbewahrungBis : vorgabe };
}

export function mitAufbewahrung(f: TerminFormular, bis: string): TerminFormular {
  return { ...f, aufbewahrungBis: bis, bisVonHand: true };
}

export function terminPruefen(f: TerminFormular): { eingabe: TerminEingabe | null; probleme: LaborProblem[] } {
  const probleme: LaborProblem[] = [];
  if (!istTag(f.tag)) probleme.push({ feld: "tag", text: "Wähle den Labortag." });
  const beginn = f.beginn === "" ? null : uhrzeit(f.beginn);
  const ende = f.ende === "" ? null : uhrzeit(f.ende);
  if (f.beginn !== "" && beginn === null) probleme.push({ feld: "beginn", text: "Der Beginn ist keine gültige Uhrzeit." });
  if (f.ende !== "" && ende === null) probleme.push({ feld: "ende", text: "Das Ende ist keine gültige Uhrzeit." });
  if (beginn && ende && !zeitraumGueltig(beginn, ende)) probleme.push({ feld: "ende", text: "Das Ende muss nach dem Beginn liegen." });
  const version = /^\d{1,2}$/.test(f.version.trim()) ? Number(f.version.trim()) : NaN;
  if (!(version >= 1 && version <= 99)) probleme.push({ feld: "version", text: "Die Version der Einwilligung ist eine ganze Zahl von 1 bis 99." });
  if (!TERMIN_STATUS.includes(f.status)) probleme.push({ feld: "status", text: "Der Stand des Termins ist ungültig." });
  if (!istTag(f.aufbewahrungBis)) probleme.push({ feld: "aufbewahrungBis", text: "Wähle das Ende der Aufbewahrung." });
  else if (istTag(f.tag) && !aufbewahrungGueltig(f.tag, f.aufbewahrungBis)) {
    probleme.push({ feld: "aufbewahrungBis", text: "Die Aufbewahrung endet frühestens am Labortag und höchstens 14 Tage danach." });
  }
  if (probleme.length > 0) return { eingabe: null, probleme };
  return {
    eingabe: { tag: f.tag, beginn, ende, einwilligungVersion: version, status: f.status, aufbewahrungBis: f.aufbewahrungBis },
    probleme: [],
  };
}

/** Der Termin, der als Nächstes ansteht: der erste ab heute, sonst der jüngste vergangene; null ohne Termine. */
export function standardTermin(termine: readonly Termin[], heute: string): Termin | null {
  if (termine.length === 0) return null;
  const sortiert = [...termine].sort((a, b) => a.tag.localeCompare(b.tag));
  return sortiert.find((t) => t.tag >= heute) ?? sortiert[sortiert.length - 1];
}

// ---------- Plätze ----------
export const PLATZ_MAX = 16;
export const ABNAHME_PLAETZE: readonly number[] = [15, 16];
export const KENNUNG_PLATZ = /^labor-[a-z0-9]{2,8}$/;
export const GAST_MAX = 20;

export const PLATZ_ZWECK_TEXT: Readonly<Record<PlatzZweck, string>> = { besucher: "Besucher", reserve: "Reserve", abnahme: "Abnahme" };

export type PlatzZeile = { platz: number; zweck: PlatzZweck | ""; kennung: string; gast: string };

/** Alle 16 Plätze als Zeilen; Plätze ohne Eintrag haben keinen Zweck. */
export function platzZeilen(plaetze: readonly Platz[]): PlatzZeile[] {
  return Array.from({ length: PLATZ_MAX }, (_, i) => {
    const p = plaetze.find((x) => x.platz === i + 1);
    return { platz: i + 1, zweck: p?.zweck ?? "", kennung: p?.kennung ?? "", gast: p?.gast ?? "" };
  });
}

/** Der Vorschlag für die Kennung eines Platzes: labor- und die zweistellige Platznummer. */
export const kennungVorschlag = (platz: number): string => `labor-${String(platz).padStart(2, "0")}`;

/** Welche Zwecke dieser Platz haben darf: Abnahme nur an den Plätzen 15 und 16. */
export function erlaubteZwecke(platz: number): readonly PlatzZweck[] {
  return ABNAHME_PLAETZE.includes(platz) ? PLATZ_ZWECKE : PLATZ_ZWECKE.filter((z) => z !== "abnahme");
}

/** Wählt den Zweck eines Platzes; mit dem ersten Zweck kommt die Kennung des Platzes als Vorschlag. */
export function mitZweck(z: PlatzZeile, zweck: PlatzZweck | ""): PlatzZeile {
  if (zweck === "") return { ...z, zweck: "", kennung: "", gast: "" };
  return { ...z, zweck, kennung: z.kennung || kennungVorschlag(z.platz) };
}

export function plaetzePruefen(zeilen: readonly PlatzZeile[]): { plaetze: Platz[] | null; probleme: LaborProblem[] } {
  const probleme: LaborProblem[] = [];
  const plaetze: Platz[] = [];
  const kennungen = new Set<string>();
  for (const z of zeilen) {
    if (z.zweck === "") continue;
    const feld = `platz-${z.platz}`;
    if (!erlaubteZwecke(z.platz).includes(z.zweck)) probleme.push({ feld, text: `Platz ${z.platz}: Abnahme gibt es nur an den Plätzen 15 und 16.` });
    const kennung = z.kennung.trim();
    if (!KENNUNG_PLATZ.test(kennung)) probleme.push({ feld, text: `Platz ${z.platz}: Die Kennung muss wie labor-01 aussehen (Kleinbuchstaben und Ziffern, 2 bis 8 nach labor-).` });
    else if (kennungen.has(kennung)) probleme.push({ feld, text: `Platz ${z.platz}: Die Kennung ${kennung} steht schon an einem anderen Platz.` });
    kennungen.add(kennung);
    const gast = normalisieren(z.gast);
    if (gast.length > GAST_MAX) probleme.push({ feld, text: `Platz ${z.platz}: Der Gast ist zu lang (höchstens ${GAST_MAX} Zeichen).` });
    plaetze.push({ platz: z.platz, zweck: z.zweck, kennung, gast: gast || null });
  }
  return probleme.length > 0 ? { plaetze: null, probleme } : { plaetze, probleme: [] };
}

// ---------- Checkliste ----------
export const CHECK_TITEL_MAX = 120;
export const CHECK_QUELLE_MAX = 80;

export function checklistePruefen(f: { titel: string; quelle: string; faellig: string }): { eingabe: ChecklisteEingabe | null; probleme: LaborProblem[] } {
  const probleme: LaborProblem[] = [];
  const titel = normalisieren(f.titel);
  const quelle = normalisieren(f.quelle);
  if (!titel) probleme.push({ feld: "titel", text: "Der Titel fehlt." });
  else if (titel.length > CHECK_TITEL_MAX) probleme.push({ feld: "titel", text: `Der Titel ist zu lang (höchstens ${CHECK_TITEL_MAX} Zeichen).` });
  if (quelle.length > CHECK_QUELLE_MAX) probleme.push({ feld: "quelle", text: `Die Quelle ist zu lang (höchstens ${CHECK_QUELLE_MAX} Zeichen).` });
  if (f.faellig !== "" && !istTag(f.faellig)) probleme.push({ feld: "faellig", text: "Das Datum ist ungültig." });
  if (probleme.length > 0) return { eingabe: null, probleme };
  return { eingabe: { titel, quelle: quelle || null, faellig: f.faellig || null }, probleme: [] };
}

/** Fortschritt der Checkliste: erledigte und alle Punkte. */
export function fortschritt(punkte: readonly { erledigt: boolean }[]): { erledigt: number; gesamt: number; prozent: number } {
  const erledigt = punkte.filter((p) => p.erledigt).length;
  return { erledigt, gesamt: punkte.length, prozent: punkte.length === 0 ? 0 : Math.round((erledigt / punkte.length) * 100) };
}
