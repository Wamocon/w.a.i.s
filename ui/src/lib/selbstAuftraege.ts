// Aufträge an W.A.I.S. selbst: ein gemeinsamer Rückstand für Verbesserungen, Fehlerbehebungen und neue Funktionen an W.A.I.S. Der Kern führt ihn,
// die Oberfläche zeigt ihn und erlaubt Anlegen, Verwerfen und Wieder-Öffnen. Die Status "in Arbeit" und "erledigt" setzt nur, wer den Auftrag
// bearbeitet (Claude Code oder später W.A.I.S.), nie diese Seite. Reine Funktionen ohne Uhr und ohne React; useWamo sendet, lib/wamo.ts
// übernimmt die Antworten, lib/nachrichten.ts prüft die Servernachricht "selbstauftraege".
//
// Ablauf: Hat die Sitzung eines Admins ein Profil und Verbindung, fragt die Oberfläche einmal je Verbindung die Liste ab. Erst die erste
// gelungene Antwort mit Liste legt den Zustand an (sonst bleibt er null, und der Block fehlt ganz, ohne Fehlermeldung). Jede Aktion bekommt
// genau eine Antwort; bis dahin sind die Knöpfe gesperrt.
import type { ServerMessage } from "./nachrichten.ts";

export const SELBST_AKTIONEN = ["liste", "speichern", "verwerfen", "oeffnen"] as const;
export type SelbstAktion = (typeof SELBST_AKTIONEN)[number];

/** Arten zur Auswahl, feste Liste (der Kern kennt dieselben). */
export const SELBST_ARTEN = [
  "umsetzung",
  "fehlerbehebung",
  "planung",
  "review",
  "test",
  "sicherheit",
  "refactoring",
  "dokumentation",
  "datenbank",
  "frontend",
  "deployment",
  "analyse",
  "recherche",
] as const;
export type SelbstArt = (typeof SELBST_ARTEN)[number];
export const SELBST_ART_STANDARD: SelbstArt = "umsetzung";
export const SELBST_ART_NAMEN: Readonly<Record<SelbstArt, string>> = {
  umsetzung: "Umsetzung",
  fehlerbehebung: "Fehlerbehebung",
  planung: "Planung",
  review: "Review",
  test: "Test",
  sicherheit: "Sicherheit",
  refactoring: "Refactoring",
  dokumentation: "Dokumentation",
  datenbank: "Datenbank",
  frontend: "Frontend",
  deployment: "Deployment",
  analyse: "Analyse",
  recherche: "Recherche",
};

/** 1 hoch, 2 normal, 3 niedrig. */
export const SELBST_PRIORITAETEN = [1, 2, 3] as const;
export type SelbstPrioritaet = (typeof SELBST_PRIORITAETEN)[number];
export const SELBST_PRIORITAET_STANDARD: SelbstPrioritaet = 2;
export const SELBST_PRIORITAET_NAMEN: Readonly<Record<SelbstPrioritaet, string>> = { 1: "Hoch", 2: "Normal", 3: "Niedrig" };

export const SELBST_STATUS = ["offen", "in_arbeit", "erledigt", "verworfen"] as const;
export type SelbstStatus = (typeof SELBST_STATUS)[number];
export const SELBST_STATUS_NAMEN: Readonly<Record<SelbstStatus, string>> = {
  offen: "Offen",
  in_arbeit: "In Arbeit",
  erledigt: "Erledigt",
  verworfen: "Verworfen",
};

export const SELBST_QUELLEN = ["sprache", "oberflaeche", "claude_code"] as const;
export type SelbstQuelle = (typeof SELBST_QUELLEN)[number];
export const SELBST_QUELLEN_NAMEN: Readonly<Record<SelbstQuelle, string>> = {
  sprache: "Sprache",
  oberflaeche: "Oberfläche",
  claude_code: "Claude Code",
};

export const SELBST_BEARBEITER = ["claude_code", "wais"] as const;
export type SelbstBearbeiter = (typeof SELBST_BEARBEITER)[number];
export const SELBST_BEARBEITER_NAMEN: Readonly<Record<SelbstBearbeiter, string>> = { claude_code: "Claude Code", wais: "W.A.I.S." };

/** Grenzen des Kerns für das Formular (Zeichen, nicht Bytes). */
export const SELBST_TITEL_MAX = 80;
export const SELBST_BESCHREIBUNG_MAX = 4000;
/** Längstes Ergebnis, das die Oberfläche zeigt (länger wird gekürzt). */
export const SELBST_ERGEBNIS_MAX = 2000;
/** Höchstens so viele Einträge nimmt die Oberfläche aus einer Liste. */
export const SELBST_LISTE_MAX = 500;
/** Obergrenze für das Feld max der Antwort (Plausibilität). */
export const SELBST_MAX_OBERGRENZE = 10_000;
/** So lange sperrt eine gesendete Aktion die Knöpfe höchstens, wenn keine Antwort kommt (danach ein Hinweis). */
export const SELBST_WARTEN_MS = 15_000;

/** Ein Eintrag des Rückstands, wie die Oberfläche ihn nach der Prüfung hält. art ist der Text des Kerns (meist eine Art aus der Liste). */
export type SelbstAuftrag = {
  nr: number;
  titel: string;
  art: string;
  prioritaet: SelbstPrioritaet;
  status: SelbstStatus;
  /** nach Fremdinhalt gespeichert: bitte prüfen */
  unsicher: boolean;
  erstelltMs: number;
  /** woher der Eintrag kommt; fehlt, wenn der Kern eine unbekannte Quelle nennt (der Eintrag bleibt trotzdem sichtbar) */
  quelle?: SelbstQuelle;
  bearbeiter?: SelbstBearbeiter;
  ergebnis?: string;
};

export type SelbstAntwort = Extract<ServerMessage, { type: "selbstauftraege" }>;

/** Letzte Rückmeldung einer Aktion; n zählt, damit die Anzeige jede neue Meldung als neu erkennt. */
export type SelbstMeldung = { n: number; ok: boolean; aktion: SelbstAktion; text: string };

/** Eine gesendete Aktion ohne Antwort und ihre Nummer (für die Frist in lib/wamo.ts). */
export type SelbstWarten = { aktion: Exclude<SelbstAktion, "liste">; n: number };

export type SelbstStand = {
  liste: SelbstAuftrag[];
  /** größte Zahl von Einträgen laut Kern; null, solange er sie nicht genannt hat */
  max: number | null;
  meldung: SelbstMeldung | null;
  /** solange gesetzt, sind die Knöpfe gesperrt */
  wartet: SelbstWarten | null;
  /** Die Frist ist abgelaufen, ohne dass der Kern geantwortet hat: Kommt die Antwort doch noch (derselben Aktion), zählt sie nur als Meldung
   *  und entsperrt kein neues Warten (sonst ginge ein zweiter Versuch zu früh auf). */
  verspaetet: SelbstWarten["aktion"] | null;
};

export const SELBST_LEER: SelbstStand = { liste: [], max: null, meldung: null, wartet: null, verspaetet: null };

const STANDARD_TEXTE: Readonly<Record<Exclude<SelbstAktion, "liste">, string>> = {
  speichern: "Gespeichert.",
  verwerfen: "Verworfen.",
  oeffnen: "Wieder geöffnet.",
};

/** Beendet diese Antwort das Warten? Nur die Antwort auf dieselbe Aktion (der Kern antwortet auf jede Aktion genau einmal). */
function beendetWarten(w: SelbstWarten | null, msg: SelbstAntwort): boolean {
  return w !== null && w.aktion === msg.aktion;
}

/**
 * Antwort des Kerns einarbeiten. Den Zustand legt nur eine gelungene Antwort mit Liste an: ohne sie (Fehler, kein Angebot des Kerns, ok ohne
 * Liste) bleibt er null, und der Block fehlt. Mit Zustand: Liste und Grenze, wenn mitgeschickt, sonst die bisherigen. Jede Antwort außer der
 * gelungenen Liste ist eine Meldung (ohne Text des Kerns mit einem Standardtext), die gelungene Liste ändert die Meldung nicht.
 */
export function selbstNachAntwort(stand: SelbstStand | null, msg: SelbstAntwort): SelbstStand | null {
  if (stand === null && !(msg.ok && msg.auftraege !== undefined)) return null;
  const alt = stand ?? SELBST_LEER;
  const still = msg.aktion === "liste" && msg.ok;
  const text = msg.text || (msg.ok && msg.aktion !== "liste" ? STANDARD_TEXTE[msg.aktion] : msg.text);
  // Eine verspätete Antwort (die Frist war schon abgelaufen) entsperrt kein neues Warten derselben Aktion
  const spaet = alt.verspaetet !== null && alt.verspaetet === msg.aktion;
  return {
    liste: msg.auftraege ?? alt.liste,
    max: msg.max ?? alt.max,
    meldung: still ? alt.meldung : { n: (alt.meldung?.n ?? 0) + 1, ok: msg.ok, aktion: msg.aktion, text },
    wartet: !spaet && beendetWarten(alt.wartet, msg) ? null : alt.wartet,
    verspaetet: spaet ? null : alt.verspaetet,
  };
}

/** "SA-7": so nennen Sprache und Oberfläche einen Eintrag. */
export const selbstNummer = (nr: number): string => `SA-${nr}`;

/** Anzeigename einer Art: bekannte Arten mit großem Anfang, alles andere unverändert (der Kern darf eine eigene Art liefern). */
export function artName(art: string): string {
  // nur eigene Schlüssel: "constructor" oder "toString" vom Kern sind keine Arten, sondern Text
  return Object.hasOwn(SELBST_ART_NAMEN, art) ? SELBST_ART_NAMEN[art as SelbstArt] : art;
}

/** Verwerfen gibt es nur für offene und laufende Einträge (erledigte bleiben stehen). */
export const selbstDarfVerwerfen = (status: SelbstStatus): boolean => status === "offen" || status === "in_arbeit";
/** Wieder öffnen gibt es nur für verworfene Einträge. */
export const selbstDarfOeffnen = (status: SelbstStatus): boolean => status === "verworfen";

/** Zeichen im Sinn des Kerns (ein Emoji zählt eins, nicht zwei). */
const zeichen = (t: string): number => Array.from(t).length;

/** Ein Fehler im Formular: welches Feld und ein Satz dazu. */
export type SelbstEingabeProblem = { feld: "titel" | "beschreibung"; text: string };

/** Prüfung vor dem Senden: das erste Feld, das fehlt oder zu lang ist, mit einem Satz, sonst null. Titel und Beschreibung werden ohne Rand gezählt. */
export function selbstEingabePruefen(e: { titel: string; beschreibung: string }): SelbstEingabeProblem | null {
  const titel = e.titel.trim();
  const beschreibung = e.beschreibung.trim();
  if (titel === "") return { feld: "titel", text: "Bitte gib einen Titel an." };
  if (zeichen(titel) > SELBST_TITEL_MAX) {
    return { feld: "titel", text: `Der Titel darf höchstens ${SELBST_TITEL_MAX} Zeichen haben (jetzt ${zeichen(titel)}).` };
  }
  if (beschreibung === "") return { feld: "beschreibung", text: "Bitte gib eine Beschreibung an." };
  if (zeichen(beschreibung) > SELBST_BESCHREIBUNG_MAX) {
    return {
      feld: "beschreibung",
      text: `Die Beschreibung darf höchstens ${SELBST_BESCHREIBUNG_MAX} Zeichen haben (jetzt ${zeichen(beschreibung)}).`,
    };
  }
  return null;
}

/** Nur der Satz der Prüfung (null, wenn alles passt). */
export const selbstEingabeFehler = (e: { titel: string; beschreibung: string }): string | null => selbstEingabePruefen(e)?.text ?? null;

/** Zeichenzahl für den Zähler im Formular (ohne Rand, wie bei der Prüfung). */
export const selbstZeichen = (t: string): number => zeichen(t.trim());

/** Was das Formular schickt. */
export type SelbstEingabe = { titel: string; beschreibung: string; art: SelbstArt; prioritaet: SelbstPrioritaet };
