/**
 * Hinweis bei Gerätewechsel (Befund 18.11.2026): Die Stimmprüfung hielt den Besitzer oft für fremd. Hauptursache war ein Gerätewechsel:
 * eingelernt mit einem Bluetooth-Headset, geprüft mit dem eingebauten Mikrofon (Pegelspitze im Median -27 statt -8 dBFS). Neu einlernen am
 * selben Gerät hob die Werte um 0,15 bis 0,25.
 *
 * Die Oberfläche merkt sich deshalb beim Einlernen (Meldung "stimmabdruck" mit "fertig") den Namen des Mikrofons, das im Gespräch lief, und
 * vergisst ihn beim Löschen des Abdrucks. Gespeichert wird nur der Name, nur im Speicher dieses Browsers oder dieser App (localStorage, je
 * Person wie die Mikrofonwahl in lib/mikrofon.ts), nie in der Datenbank. Läuft in einem Gespräch mit bereitem Abdruck ein anderes Mikrofon,
 * fragt die Oberfläche einmal je Gespräch und Gerät, ob für dieses Mikrofon neu eingelernt werden soll (Knopf in components/FehlerAnzeige.tsx).
 * Ist kein Name gemerkt (vor dieser Neuerung eingelernt, anderer Browser), gibt es keinen Hinweis: unbekannt heißt nicht anders.
 *
 * Reine Logik ohne Browser (Tests: stimmMikrofon.test.ts); die Verdrahtung liegt in useWamo.ts.
 */
import { geraeteName } from "./mikrofon.ts";

export const STIMM_MIKROFON_PRAEFIX = "wamo.stimme.mikrofon.";

export const ANDERES_MIKROFON_TEXT = "Deine Stimme ist mit einem anderen Mikrofon eingelernt. Für dieses Mikrofon neu einlernen?";

type Lesen = { getItem(k: string): string | null };
type Schreiben = { setItem(k: string, v: string): void };
type Entfernen = { removeItem(k: string): void };

function schluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${STIMM_MIKROFON_PRAEFIX}${userId}`;
}

/** Der Speicher dieses Browsers oder dieser App; null, wenn es keinen gibt oder der Zugriff wirft (privates Fenster, gesperrte Daten). */
export function stimmSpeicher(): (Lesen & Schreiben & Entfernen) | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Name des Mikrofons, mit dem diese Person eingelernt hat (wie geraeteName), null, wenn keiner gemerkt ist. */
export function stimmMikrofonLesen(speicher: Lesen | null | undefined, userId: string | null | undefined): string | null {
  const k = schluessel(userId);
  if (!k || !speicher) return null;
  try {
    return geraeteName(speicher.getItem(k));
  } catch {
    return null;
  }
}

/** Beim Einlernen: Namen merken. true, wenn der Speicher ihn angenommen hat. */
export function stimmMikrofonMerken(
  speicher: Schreiben | null | undefined,
  userId: string | null | undefined,
  label: string | null | undefined,
): boolean {
  const k = schluessel(userId);
  const name = geraeteName(label);
  if (!k || !name || !speicher) return false;
  try {
    speicher.setItem(k, name);
    return true;
  } catch {
    return false;
  }
}

/** Abdruck gelöscht: den Namen vergessen. */
export function stimmMikrofonVergessen(speicher: Entfernen | null | undefined, userId: string | null | undefined): void {
  const k = schluessel(userId);
  if (!k || !speicher) return;
  try {
    speicher.removeItem(k);
  } catch {
    // nichts zu tun: dann bleibt ein alter Name, der höchstens einen Hinweis zu viel auslöst
  }
}

/** Vergleichsform: wie geraeteName, ohne Unterschied in Groß- und Kleinschreibung. */
const vergleich = (label: string | null | undefined): string | null => geraeteName(label)?.toLowerCase() ?? null;

/** Läuft ein anderes Mikrofon als beim Einlernen? Nur, wenn beide Namen bekannt sind. */
export function anderesMikrofon(gemerkt: string | null | undefined, aktuell: string | null | undefined): boolean {
  const a = vergleich(gemerkt);
  const b = vergleich(aktuell);
  return a !== null && b !== null && a !== b;
}

export type GeraetHinweisLage = {
  /** Mikrofon beim Einlernen (stimmMikrofonLesen) */
  gemerkt: string | null;
  /** Mikrofon des laufenden Gesprächs (WamoState.mikrofon) */
  aktuell: string | null;
  /** verbunden und der Kern meldet einen bereiten Abdruck */
  stimmeBereit: boolean;
  /** keine andere Meldung steht */
  frei: boolean;
  /** W.A.I.S. spricht gerade */
  wamoSpricht: boolean;
  /** die Einlernansicht ist offen */
  einlernen: boolean;
};

/**
 * Ist der Hinweis jetzt fällig? Liefert den Schlüssel des Geräts, das die Person gerade benutzt (der Aufrufer merkt ihn sich in gezeigt,
 * damit der Hinweis je Gespräch und Gerät nur einmal kommt), sonst null.
 */
export function geraetHinweisFaellig(lage: GeraetHinweisLage, gezeigt: ReadonlySet<string>): string | null {
  if (!lage.stimmeBereit || !lage.frei || lage.wamoSpricht || lage.einlernen) return null;
  if (!anderesMikrofon(lage.gemerkt, lage.aktuell)) return null;
  const geraet = vergleich(lage.aktuell);
  return geraet && !gezeigt.has(geraet) ? geraet : null;
}
