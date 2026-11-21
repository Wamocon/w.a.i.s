import { anzahlText } from "./werkstattAnsicht.ts";
import type { FreigabeKarte, Pruefung, Veroeffentlicht } from "./werkstattTypen.ts";

/**
 * Der Vierschritt zum Veröffentlichen der Karten: Prüfung (Trockenlauf), Karte, zweiter Faktor, Ausführung. Hier steht der Zustand
 * des Ablaufs und alles, was sich ohne Netz rechnen lässt: welcher Schritt gerade dran ist, wie lange die Karte noch gilt, ob der
 * Code die richtige Form hat und was die Karte als Wirkung nennt. Die Aufrufe selbst macht die Komponente (components/werkstatt).
 * Ohne React und ohne Netz (werkstattVeroeffentlichen.test.ts).
 */

export type Ablauf =
  | { art: "bereit" }
  | { art: "prueft" }
  | { art: "abgelehnt"; pruefung: Pruefung }
  | { art: "geprueft"; pruefung: Pruefung }
  | { art: "karte_laeuft"; pruefung: Pruefung }
  | { art: "karte"; pruefung: Pruefung; karte: FreigabeKarte; endeMs: number }
  | { art: "ausfuehren"; pruefung: Pruefung; karte: FreigabeKarte; endeMs: number }
  | { art: "fertig"; ergebnis: Veroeffentlicht };

export type SchrittStand = "offen" | "aktiv" | "fertig";

export const SCHRITT_TITEL = ["Prüfung", "Karte", "Zweiter Faktor", "Kern lädt nach"] as const;

/** Der Stand der vier Schritte zu einem Zustand des Ablaufs. */
export function schrittStaende(a: Ablauf): [SchrittStand, SchrittStand, SchrittStand, SchrittStand] {
  switch (a.art) {
    case "bereit":
    case "prueft":
    case "abgelehnt":
      return ["aktiv", "offen", "offen", "offen"];
    case "geprueft":
    case "karte_laeuft":
      return ["fertig", "aktiv", "offen", "offen"];
    case "karte":
    case "ausfuehren":
      return ["fertig", "fertig", "aktiv", "offen"];
    case "fertig":
      return ["fertig", "fertig", "fertig", "fertig"];
  }
}

/** Eine Freigabekarte gilt fünf Minuten. */
export const KARTE_GILT_S = 300;
/** Weicht das Ende der Karte um mehr als eine Minute vom erwarteten ab, gehen die Uhren auseinander. */
const UHR_ABWEICHUNG_MS = 60_000;

/**
 * Das Ende der Karte in der Zeit dieses Geräts. Die Karte nennt ein Ende in der Zeit des Servers; geht die Uhr hier um mehr als eine
 * Minute anders, zählt die Oberfläche fünf Minuten ab dem Anlegen. Entschieden wird ohnehin im Dienst.
 */
export function kartenEndeMs(giltBisIso: string, angelegtMs: number): number {
  const erwartet = angelegtMs + KARTE_GILT_S * 1000;
  const ende = Date.parse(giltBisIso);
  if (Number.isNaN(ende) || Math.abs(ende - erwartet) > UHR_ABWEICHUNG_MS) return erwartet;
  return ende;
}

export function restSekunden(endeMs: number, jetztMs: number): number {
  return Math.max(0, Math.ceil((endeMs - jetztMs) / 1000));
}

/** "4:32" */
export function restText(sekunden: number): string {
  return `${Math.floor(sekunden / 60)}:${String(sekunden % 60).padStart(2, "0")}`;
}

/** Der Code aus der Authenticator-App: sechs Ziffern, Leerzeichen dazwischen sind erlaubt; sonst null. */
export function codeSauber(eingabe: string): string | null {
  const s = eingabe.replace(/\s+/g, "");
  return /^\d{6}$/.test(s) ? s : null;
}

/** Der Dienst nimmt nur einen zweiten Faktor bis 60 Sekunden; die Oberfläche prüft vor dem Senden mit etwas Luft. */
export const AAL2_MAX_ALTER_S = 60;

/** Ist das Alter des Codes (Sekunden) noch gut genug für die Ausführung? */
export function codeFrischGenug(alterS: number | null): boolean {
  return alterS !== null && alterS <= AAL2_MAX_ALTER_S - 5;
}

/** Wirkung der Karte in einem Satz: "Katalog Version 5 mit 2 Änderungen: W1, A2." */
export function wirkungText(aktiveVersion: number | null, kennungen: readonly string[], aenderungen: number | null = null): string {
  const n = aenderungen ?? kennungen.length;
  const liste = kennungen.length > 0 ? `: ${kennungen.join(", ")}` : "";
  return `Katalog Version ${(aktiveVersion ?? 0) + 1} mit ${anzahlText(n, "Änderung", "Änderungen")}${liste}.`;
}

/** Satz zum Ergebnis. */
export function ergebnisText(e: Veroeffentlicht): string {
  return `Version ${e.version} ist veröffentlicht, ${e.zeichen} Zeichen Wissenstext zählen gegen das Budget.`;
}
