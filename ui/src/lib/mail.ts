import type { CanvasItem } from "@/components/Canvas";
import { exportFormate, type OfficeFormat } from "./export.ts";

/**
 * Mail über Outlook am PC aus dem Canvas (voice-core/outlook_werkzeuge.py, host/office_outlook.py): das Formular "Als E-Mail", die
 * Prüfung vor dem Senden an den Kern und die Texte für den Hinweis zum Versand. Freigegeben wird hier nie etwas: Kern und Host bauen
 * die Karte mit genau dem Inhalt, der rausgeht, und erst der Klick auf "Freigeben" löst etwas aus. Welches Outlook läuft, entscheidet
 * der PC: klassisch sendet W.A.I.S. nach dem Klick (30 Sekunden zurückholbar), im neuen Outlook öffnet es einen fertigen Entwurf.
 * Die Grenzen sind die des Hosts; er prüft trotzdem selbst.
 */
export const MAIL_EMPFAENGER_MAX = 10;
export const MAIL_BETREFF_MAX = 200;
export const MAIL_TEXT_MAX = 6000;

export const MAIL_VERSAND_ZUSTAENDE = [
  "wartet",
  "gesendet",
  "zurueckgeholt",
  "zu_spaet",
  "fehler",
  "unklar",
  "unbekannt",
  "entwurf",
] as const;
export type MailVersandZustand = (typeof MAIL_VERSAND_ZUSTAENDE)[number];

/** Stand eines Versands (Servernachricht mail_versand); bis: Ende der Frist (Date.now), nur solange die Mail wartet. */
export type MailVersand = { id: string | null; zustand: MailVersandZustand; text: string; restS?: number; bis?: number };

/** Was das Formular an den Kern schickt (Nachricht mail_vorbereiten); anhang null heißt ohne Anhang. */
export type MailDaten = {
  canvasId: string | null;
  an: string[];
  cc: string[];
  betreff: string;
  text: string;
  anhang: OfficeFormat | null;
};

/** Was die Oberfläche auslösen kann (useWamo); true, wenn die Nachricht an den Kern gesendet wurde. */
export type MailAktionen = {
  vorbereiten: (daten: MailDaten) => boolean;
  zurueckholen: (id: string) => boolean;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** "Als E-Mail" nur für eigene, gespeicherte Elemente (wie Speichern: nicht geteilt, kein Auftragsergebnis). */
export function eigenesElement(item: Partial<Pick<CanvasItem, "id" | "geteilt" | "teilbar">>): boolean {
  return !item.geteilt && !item.teilbar && typeof item.id === "string" && UUID.test(item.id);
}

/** Empfänger aus einem Eingabefeld: Komma, Semikolon und Zeilenumbruch trennen. */
export function empfaengerListe(roh: string): string[] {
  return roh
    .split(/[,;\n]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

/** Ein Satz, was am Formular fehlt, oder null. */
export function formularFehler(d: Pick<MailDaten, "an" | "cc" | "betreff" | "text">): string | null {
  if (!d.an.length) return "Mindestens ein Empfänger unter An fehlt.";
  if (d.an.length + d.cc.length > MAIL_EMPFAENGER_MAX) return `Höchstens ${MAIL_EMPFAENGER_MAX} Empfänger (An und Cc zusammen).`;
  if (!d.betreff.trim()) return "Der Betreff fehlt.";
  if (d.betreff.trim().length > MAIL_BETREFF_MAX) return `Der Betreff ist länger als ${MAIL_BETREFF_MAX} Zeichen.`;
  if (d.text.length > MAIL_TEXT_MAX) return `Der Text ist länger als ${MAIL_TEXT_MAX} Zeichen. Bitte kürzen oder als Anhang schicken.`;
  return null;
}

/** Formate für den Anhang: dieselben wie beim Speichern (Excel und CSV nur für Tabellen). */
export const anhangFormate = exportFormate;

/** Vorschlag für den Anhang: PDF, wenn es geht, sonst das erste Format. */
export function anhangVorschlag(formate: readonly OfficeFormat[]): OfficeFormat | null {
  return formate.includes("pdf") ? "pdf" : (formate[0] ?? null);
}

/** Restliche ganze Sekunden bis bis (Date.now), nie negativ. */
export function restSekunden(bis: number | undefined, jetzt: number): number {
  return bis === undefined ? 0 : Math.max(0, Math.ceil((bis - jetzt) / 1000));
}

const STANDARD: Record<MailVersandZustand, string> = {
  wartet: "Die Mail geht gleich raus.",
  gesendet: "Die Mail ist gesendet.",
  zurueckgeholt: "Zurückgeholt: Die Mail ist nicht rausgegangen.",
  zu_spaet: "Zu spät: Die Mail ist schon unterwegs.",
  fehler: "Die Mail ist nicht rausgegangen.",
  unklar: "Ob die Mail rausging, ist unklar. Bitte in Outlook nachsehen.",
  unbekannt: "Diesen Versand kennt W.A.I.S. nicht (mehr).",
  entwurf: "Der Entwurf ist offen. Du sendest selbst.",
};

/**
 * Zusatz im Browser, der den Laptop aus der Ferne steuert (lib/pcSchalter.ts, pcFern): Outlook läuft auf dem Laptop, nicht auf dem Gerät des
 * Browsers. Nur wo die Person dort handeln muss (Entwurf im neuen Outlook, unklarer Ausgang); sonst null.
 */
export function versandOrtText(zustand: MailVersandZustand, fern: boolean): string | null {
  if (!fern) return null;
  if (zustand === "entwurf") return "Der Entwurf ist in Outlook auf deinem Laptop offen, dort sendest du ihn.";
  if (zustand === "unklar") return "Nachsehen kannst du in Outlook auf deinem Laptop.";
  return null;
}

/** Satz für den Hinweis: solange die Mail wartet, mit Restzeit; sonst der Text des Kerns. */
export function versandText(v: Pick<MailVersand, "zustand" | "text">, rest: number): string {
  if (v.zustand === "wartet") {
    return rest > 0 ? `Die Mail geht in ${rest} ${rest === 1 ? "Sekunde" : "Sekunden"} raus.` : "Die Mail geht jetzt raus.";
  }
  return v.text || STANDARD[v.zustand];
}
