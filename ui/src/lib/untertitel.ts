/**
 * Live-Untertitel unter dem Kern (components/LiveCaption.tsx): standardmäßig aus, seit Niko am 17.11.2026 entschied, dass W.A.I.S. nur
 * der eingelernten Stimme zuhört und fremde Sätze nirgends erscheinen. Die Untertitel zeigen sofort, was das Mikrofon hört, auch Sätze,
 * die die Stimmprüfung danach verwirft; der Chat links zeigt nur Geprüftes (lib/stimmFilter.ts). Wer die Untertitel trotzdem will,
 * schaltet sie in den Einstellungen unter Darstellung ein.
 *
 * Die Wahl gilt je Person auf diesem Gerät (Schlüssel mit der user_id, wie der Schalter für den stillen Start in lib/stillStart.ts), kein
 * Server-Zustand. Nur "an" schaltet ein: ohne Kennung, ohne Speicher, bei einem Lesefehler oder einem fremden Wert bleibt es beim
 * Standard aus. Reine Funktionen ohne React und ohne Browser (untertitel.test.ts); den Hook dazu hat lib/einstellungen.ts.
 */
import type { Speicher } from "./stillStart.ts";

export const UNTERTITEL_PRAEFIX = "wamo.untertitel.";

/** Standard, solange die Person nichts gewählt hat. */
export const UNTERTITEL_STANDARD = false;

/** Schlüssel im Speicher für diese Person; null, wenn die Kennung fehlt oder nicht wie eine user_id aussieht. */
export function untertitelSchluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${UNTERTITEL_PRAEFIX}${userId}`;
}

/** Sind die Untertitel für diese Person auf diesem Gerät eingeschaltet? */
export function untertitelLesen(speicher: Pick<Speicher, "getItem"> | null | undefined, userId: string | null | undefined): boolean {
  const k = untertitelSchluessel(userId);
  if (!k || !speicher) return UNTERTITEL_STANDARD;
  try {
    return speicher.getItem(k) === "an";
  } catch {
    return UNTERTITEL_STANDARD;
  }
}

/** Wahl schreiben ("an" oder "aus"). true, wenn der Speicher sie angenommen hat (sonst gilt sie nur bis zum Neuladen). */
export function untertitelSchreiben(
  speicher: Pick<Speicher, "setItem"> | null | undefined,
  userId: string | null | undefined,
  an: boolean,
): boolean {
  const k = untertitelSchluessel(userId);
  if (!k || !speicher) return false;
  try {
    speicher.setItem(k, an ? "an" : "aus");
    return true;
  } catch {
    return false;
  }
}
