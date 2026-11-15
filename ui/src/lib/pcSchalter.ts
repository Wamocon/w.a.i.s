/**
 * Schalter "PC-Steuerung" auch ohne laufendes Gespräch (Desktop-App und Browser gleich, nur Admins). Reine Logik ohne Browser und ohne
 * React, damit sie sich mit node:test prüfen lässt (pcSchalter.test.ts). Alle Importe relativ.
 *
 * Ablauf: Ein Klick auf "an" ohne Sitzung startet still eine Sitzung (wie der Start beim Tippen, mit allen Regeln aus
 * lib/stillStart.ts: Geräteschalter, Laborkonten, Übernahme durch ein anderes Fenster, Ratenbegrenzung) und merkt sich den Wunsch.
 * Sobald der Kern den PC als verbunden meldet (betrieb.pc), geht der Wunsch einmal an den Kern; was gilt, meldet der Kern in
 * betrieb.pc_steuerung zurück. Bleibt die Rückmeldung aus, nennt ein Hinweis nach der Wartezeit den Zustand des PCs.
 *
 * Browser (Entscheidung 11.11.2026, bestätigt 15.11.2026): Der Browser bedient nur. Die PC-Werkzeuge laufen immer auf dem Laptop, den der
 * Kern der Sitzung aus dem Geräteregister zuordnet (Host und Tunnel dort, eingerichtet mit der Desktop-App), mit PC-Sperre je Sitzung,
 * Freigabekarten und Gate der Stimmprüfung. Der Schalter sagt das (pcFern, HINWEIS_LAPTOP) und nennt, was nur die Desktop-App kann
 * (HINWEIS_NUR_APP). Die Oberfläche entscheidet hier nichts, was der Kern nicht ohnehin prüft.
 *
 * Rolle ohne Sitzung: Das Profil (admin oder mitglied) meldet erst der Kern. Damit der Schalter schon vor dem ersten Gespräch da ist,
 * merkt sich die Oberfläche die zuletzt gemeldete Rolle je Person auf diesem Gerät (localStorage, Schlüssel mit der user_id). Das ist
 * nur eine Anzeigehilfe: Einschalten darf nur, wen der Kern als Admin mit eingerichtetem PC-Host kennt (voice-core/bot.py).
 */

import type { Betrieb, Rolle } from "./nachrichten.ts"; // nur Typen: werden beim Laden gestrichen
import type { NeinGrund } from "./stillStart.ts";
import { VERBINDUNG_FRIST_MS } from "./verbindungsfrist.ts";
import type { Presence } from "./wamo.ts";

export type { Rolle };

// ---------- feste Werte ----------
/** So lange wartet der Schalter auf die Rückmeldung des Kerns nach dem Senden (wie bisher am Schalter in den Einstellungen). */
export const SCHALT_WARTEN_MS = 5000;
/** So lange darf der PC nach dem Sitzungsbeginn brauchen, bis der Kern ihn als verbunden meldet (dieselbe Frist wie beim Verbinden). */
export const PC_VERBINDEN_MS = VERBINDUNG_FRIST_MS;

export const HINWEIS_IM_GESPRAECH = "Der Schalter ist während eines Gesprächs bedienbar.";
export const HINWEIS_OHNE_SITZUNG = "Ohne Gespräch startet W.A.I.S. dafür still, ohne Mikrofon.";
export const HINWEIS_STILL_AUS =
  "Ohne Gespräch nur mit „Still starten beim Tippen“ (Einstellungen, Sprache und Ton). Sonst ist der Schalter während eines Gesprächs bedienbar.";
export const TEXT_WARTET = "wird eingeschaltet …";
export const HINWEIS_PC_AUS =
  "PC-Steuerung nicht eingeschaltet: Diese Sitzung hat keinen PC-Host (Laptop nicht eingerichtet oder keine Admin-Rolle).";
export const HINWEIS_PC_GETRENNT =
  "PC-Steuerung nicht eingeschaltet: Der PC ist nicht erreichbar. Läuft der PC-Host, und steht die Verbindung zum Büro?";
export const HINWEIS_PC_GESPERRT =
  "PC-Steuerung nicht eingeschaltet: Der Bildschirm am PC ist gesperrt. Nach dem Entsperren bitte noch einmal schalten.";
export const HINWEIS_PC_STILL = "PC-Steuerung nicht eingeschaltet: Der PC hat sich nicht rechtzeitig gemeldet. Bitte noch einmal schalten.";
export const HINWEIS_NICHT_BESTAETIGT =
  "PC-Steuerung nicht eingeschaltet: Der Kern hat das Einschalten nicht bestätigt. Bitte noch einmal schalten.";
/** Browser in der Betriebsart Büro: Die Werkzeuge laufen auf dem Laptop aus dem Register, egal wo der Browser läuft. */
export const HINWEIS_LAPTOP = "Steuert deinen Laptop, den du mit der Desktop-App eingerichtet hast, egal auf welchem Gerät dieser Browser läuft.";
/** Was aus dem Browser bewusst nicht geht: Beides braucht die Desktop-Brücke (Rechnername, Zeichnen auf dem Bildschirm). */
export const HINWEIS_NUR_APP =
  "Aus dem Browser schaltet sie sich nie automatisch ein, und der Lichtrahmen um das Fenster, in dem W.A.I.S. handelt, fehlt. Beides gibt es nur in der Desktop-App.";

// ---------- Rolle je Person merken ----------
export const ROLLE_PRAEFIX = "wamo.rolle.";

export type Speicher = {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
  removeItem(k: string): void;
};

/** Schlüssel für diese Person; null ohne brauchbare Kennung (nur Buchstaben, Ziffern, Bindestrich, wie beim stillen Start). */
export function rolleSchluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${ROLLE_PRAEFIX}${userId}`;
}

/** Zuletzt vom Kern gemeldete Rolle dieser Person auf diesem Gerät; null, wenn unbekannt, unlesbar oder kein gültiger Wert. */
export function rolleLesen(speicher: Speicher | null | undefined, userId: string | null | undefined): Rolle | null {
  const k = rolleSchluessel(userId);
  if (!k || !speicher) return null;
  try {
    const wert = speicher.getItem(k);
    return wert === "admin" || wert === "mitglied" ? wert : null;
  } catch {
    return null;
  }
}

/** Rolle merken (überschreibt die alte). true, wenn der Speicher den Wert angenommen hat. */
export function rolleMerken(speicher: Speicher | null | undefined, userId: string | null | undefined, rolle: Rolle): boolean {
  const k = rolleSchluessel(userId);
  if (!k || !speicher) return false;
  try {
    speicher.setItem(k, rolle);
    return true;
  } catch {
    return false;
  }
}

/** Sieht diese Person den Schalter? Die Rolle vom Kern gilt zuerst, ohne Sitzung die gemerkte. Laborkonten nie. */
export function pcAdmin(l: { rolleKern: Rolle | null; rolleGemerkt: Rolle | null; laborKonto: boolean }): boolean {
  if (l.laborKonto) return false;
  return (l.rolleKern ?? l.rolleGemerkt) === "admin";
}

const istOnline = (p: Presence) => p !== "offline" && p !== "connecting";

// ---------- Anzeige des Schalters ----------
/** Was der Kern zum PC meldet (betrieb), soweit der Schalter es braucht. */
export type PcMeldung = Pick<Betrieb, "pc" | "pcSteuerung">;

export type SchalterLage = {
  admin: boolean;
  presence: Presence;
  /** Geräteschalter "Still starten beim Tippen" an und kein Laborkonto (lib/useStillStart.ts) */
  stillErlaubt: boolean;
  /** Ein Klick wartet auf Sitzung und PC (Store, pcEinschalten.wartet) */
  wartet: boolean;
  /** letzte Betriebsmeldung des Kerns; zählt nur mit Sitzung */
  betrieb: PcMeldung | null;
};

export type SchalterAnzeige =
  | { art: "verborgen" }
  | { art: "bedienbar"; ohneSitzung: boolean }
  | { art: "gesperrt"; hinweis: string };

/**
 * Ob und wie der Schalter erscheint, in der Desktop-App und im Browser gleich. Ohne Sitzung bedienbar, wenn der stille Start erlaubt ist.
 * In einer Sitzung ohne PC-Host (betrieb.pc "aus") nimmt der Kern das Einschalten nie an (voice-core/bot.py): Statt einer stillen Ablehnung
 * ist der Schalter dann gesperrt und sagt warum. Ausschalten bleibt immer möglich.
 */
export function schalterAnzeige(l: SchalterLage): SchalterAnzeige {
  if (!l.admin) return { art: "verborgen" };
  if (istOnline(l.presence)) {
    if (l.betrieb?.pc === "aus" && l.betrieb.pcSteuerung !== "an") return { art: "gesperrt", hinweis: HINWEIS_PC_AUS };
    return { art: "bedienbar", ohneSitzung: false };
  }
  // Ein Wunsch läuft schon, oder eine Sitzung baut sich gerade auf: kein neuer Start nötig, der Klick merkt sich nur den Wunsch
  if (l.wartet || l.presence === "connecting") return { art: "bedienbar", ohneSitzung: true };
  if (!l.stillErlaubt) return { art: "gesperrt", hinweis: HINWEIS_STILL_AUS };
  return { art: "bedienbar", ohneSitzung: true };
}

/**
 * Ein Satz zum PC am Schalter, solange die Steuerung aus ist und der Kern den PC nicht als verbunden meldet (getrennt, gesperrt, kein
 * PC-Host); null, wenn alles in Ordnung ist oder der PC sich noch verbindet. Nur für eine laufende Sitzung gedacht.
 */
export function pcLageHinweis(b: PcMeldung | null | undefined): string | null {
  if (!b || b.pcSteuerung === "an") return null;
  if (b.pc === "aus") return HINWEIS_PC_AUS;
  if (b.pc === "getrennt") return HINWEIS_PC_GETRENNT;
  if (b.pc === "gesperrt") return HINWEIS_PC_GESPERRT;
  return null;
}

/**
 * Steuert dieses Fenster den Laptop aus der Ferne? Ja im Browser (keine Desktop-App) in der Betriebsart Büro: Dort laufen die Werkzeuge
 * auf dem Laptop, den der Kern dem Profil aus dem Geräteregister zuordnet. In Unterwegs laufen Kern und Host auf diesem PC.
 */
export function pcFern(l: { desktop: boolean; buero: boolean }): boolean {
  return !l.desktop && l.buero;
}

// ---------- Klick ----------
export type KlickLage = {
  /** gewünschter Zustand */
  an: boolean;
  /** Sitzung steht (Client da und Präsenz nicht offline oder verbindend) */
  online: boolean;
  presence: Presence;
  admin: boolean;
};

export type KlickWeg = { art: "senden" } | { art: "nichts" } | { art: "wunsch" } | { art: "still_starten" } | { art: "nein" };

/** Was ein Klick auslöst. Mit Sitzung wie bisher senden; ohne: "an" startet still (Desktop-App und Browser), "aus" ist nichts zu tun. */
export function klickWeg(l: KlickLage): KlickWeg {
  if (!l.admin) return { art: "nein" };
  if (l.online) return { art: "senden" };
  if (!l.an) return { art: "nichts" };
  return l.presence === "connecting" ? { art: "wunsch" } : { art: "still_starten" };
}

/** Text, wenn der stille Start für den Schalter nicht möglich ist (Gründe aus lib/stillStart.ts). */
export function stillNeinHinweis(grund: NeinGrund, hinweis?: string): string {
  if (hinweis) return hinweis;
  return grund === "schalter_aus" ? HINWEIS_STILL_AUS : HINWEIS_IM_GESPRAECH;
}

// ---------- Ablauf nach dem Klick ----------
/** onlineSeit: erste Betriebsmeldung der Sitzung (Date.now); gesendetSeit: Wunsch an den Kern geschickt. */
export type PcWunsch = { onlineSeit: number | null; gesendetSeit: number | null };
export const PC_WUNSCH_NEU: PcWunsch = Object.freeze({ onlineSeit: null, gesendetSeit: null });

export type WunschLage = {
  jetzt: number;
  presence: Presence;
  betrieb: Pick<Betrieb, "pc" | "pcSteuerung" | "pcBelegt"> | null;
};

/** warten: frist ist der Zeitpunkt der nächsten Prüfung (null: auf die nächste Meldung warten); senden: jetzt einmal an den Kern. */
export type WunschSchritt =
  | { art: "warten"; wunsch: PcWunsch; frist: number | null }
  | { art: "senden"; wunsch: PcWunsch; frist: number }
  | { art: "ende"; hinweis: string | null };

function zustandsHinweis(b: NonNullable<WunschLage["betrieb"]>, gesendet: boolean): string {
  if (gesendet && b.pc === "verbunden") return HINWEIS_NICHT_BESTAETIGT;
  if (b.pc === "getrennt") return HINWEIS_PC_GETRENNT;
  if (b.pc === "gesperrt") return HINWEIS_PC_GESPERRT;
  return HINWEIS_PC_STILL;
}

/**
 * Ein Schritt des Wunsches "PC-Steuerung an". Während des Verbindens gilt die Verbindungsfrist von useWamo (sie meldet sich selbst),
 * danach hat der PC PC_VERBINDEN_MS Zeit, als verbunden gemeldet zu werden, und der Kern nach dem Senden SCHALT_WARTEN_MS für "an".
 */
export function wunschSchritt(w: PcWunsch, l: WunschLage): WunschSchritt {
  if (l.presence === "offline") return { art: "ende", hinweis: null };
  const b = l.betrieb;
  if (!istOnline(l.presence) || !b) return { art: "warten", wunsch: w, frist: null };
  if (b.pcSteuerung === "an" || b.pcBelegt) return { art: "ende", hinweis: null };
  if (b.pc === "aus") return { art: "ende", hinweis: HINWEIS_PC_AUS };
  const onlineSeit = w.onlineSeit ?? l.jetzt;
  if (b.pc === "verbunden" && w.gesendetSeit === null) {
    return { art: "senden", wunsch: { onlineSeit, gesendetSeit: l.jetzt }, frist: l.jetzt + SCHALT_WARTEN_MS };
  }
  const frist = w.gesendetSeit !== null ? w.gesendetSeit + SCHALT_WARTEN_MS : onlineSeit + PC_VERBINDEN_MS;
  if (l.jetzt >= frist) return { art: "ende", hinweis: zustandsHinweis(b, w.gesendetSeit !== null) };
  return { art: "warten", wunsch: { onlineSeit, gesendetSeit: w.gesendetSeit }, frist };
}

// ---------- Zustand im Store ----------
/** wartet: ein Klick wartet auf Sitzung und PC; hinweis: warum es zuletzt nicht geklappt hat (steht am Schalter). */
export type PcEinschalten = { wartet: boolean; hinweis: string | null };
export const PC_EIN_LEER: PcEinschalten = Object.freeze({ wartet: false, hinweis: null });
