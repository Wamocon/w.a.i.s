import type { UpdateAngebot } from "./einrichtung.ts";
import { versionVergleich } from "./installer.ts";
import type { InstallPhase } from "./updates.ts";

/**
 * Reine Logik des Pop-ups "Update verfügbar" (components/UpdateHinweis.tsx), ohne React, damit sie sich mit node:test prüfen lässt
 * (updateHinweis.test.ts). Der Stand der Updates selbst liegt im gemeinsamen Speicher lib/updatesStore.ts, derselbe wie im Abschnitt
 * Updates der Einstellungen: dieselbe von der App bestätigte Quelle, dieselben Schutzregeln, höchstens eine Installation zugleich.
 *
 * "Später" blendet das Pop-up für diese Version aus. Gemerkt wird es je Profil im localStorage (ein Eintrag mit Version, Zeitpunkt
 * und Kennung des App-Starts), der Speicher darf fehlen oder werfen: Dann gilt der Rückfall im Arbeitsspeicher, und nach dem nächsten
 * Start erscheint das Pop-up wieder. Dieselbe Version kommt erst nach dem nächsten Start der App oder nach 24 Stunden wieder, eine
 * neuere sofort.
 */

export const PRUEFABSTAND_MS = 30 * 60 * 1000; // so oft fragt das Pop-up den Server, solange das Fenster offen ist
export const FENSTER_ALTER_MS = 10 * 60 * 1000; // beim Wiederöffnen des Fensters nur, wenn die letzte Prüfung älter ist
export const INTERVALL_ALTER_MS = PRUEFABSTAND_MS / 2; // der Takt überspringt eine Prüfung, wenn gerade erst (von Hand) geprüft wurde
export const SPAETER_FRIST_MS = 24 * 60 * 60 * 1000;

let startKennung: string | null = null;

/**
 * Kennung dieses Starts der Oberfläche: ändert sich mit jedem Start der App und jedem Neuladen, nie innerhalb einer Sitzung. Erst beim
 * ersten Aufruf erzeugt (im Browser, nach der Hydration), nicht beim Laden des Moduls: Zeit und Zufall auf Modulebene brächen das
 * Vorrendern (cacheComponents in next.config.ts).
 */
export function startId(): string {
  startKennung ??= `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return startKennung;
}

export type SpaeterEintrag = Readonly<{ version: string; zeit: number; start: string }>;

/** Schlüssel im localStorage: je Profil ein Eintrag, nie ein Wert aus dem Update selbst. */
export const spaeterSchluessel = (userId: string): string => `wamo.update.spaeter.${userId}`;

/** Gelesener Eintrag, streng geprüft; alles, was nicht genau passt, gilt als kein Eintrag. */
export function pruefeSpaeterEintrag(v: unknown): SpaeterEintrag | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  if (typeof o.version !== "string" || versionVergleich(o.version, "0.0.0") === null) return null;
  if (typeof o.zeit !== "number" || !Number.isFinite(o.zeit) || o.zeit < 0) return null;
  if (typeof o.start !== "string" || o.start.length === 0 || o.start.length > 64) return null;
  return { version: o.version, zeit: o.zeit, start: o.start };
}

/**
 * Gilt "Später" noch für diese Version? Eine neuere (oder nicht vergleichbare) Version zeigt das Pop-up sofort, dieselbe nach einem
 * neuen Start der App oder nach 24 Stunden wieder. Ohne Eintrag gilt nichts.
 */
export function spaeterGilt(eintrag: SpaeterEintrag | null, version: string, jetzt: number, start: string): boolean {
  if (!eintrag) return false;
  const vergleich = versionVergleich(version, eintrag.version);
  if (vergleich === null || vergleich === 1) return false;
  if (eintrag.start !== start) return false;
  return jetzt - eintrag.zeit < SPAETER_FRIST_MS;
}

// ---------- Speicher ----------
type Speicher = Pick<Storage, "getItem" | "setItem">;

const rueckfall = new Map<string, string>(); // Arbeitsspeicher, wenn localStorage fehlt oder wirft

function lokalerSpeicher(): Speicher | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** Der Eintrag dieses Profils; nie eine Ausnahme. Der Arbeitsspeicher gilt, wenn der Speicher nichts liefert. */
export function spaeterLesen(userId: string, speicher: Speicher | null = lokalerSpeicher()): SpaeterEintrag | null {
  const schluessel = spaeterSchluessel(userId);
  let roh: string | null = null;
  try {
    roh = speicher?.getItem(schluessel) ?? null;
  } catch {
    roh = null;
  }
  roh ??= rueckfall.get(schluessel) ?? null;
  if (roh === null) return null;
  try {
    return pruefeSpaeterEintrag(JSON.parse(roh));
  } catch {
    return null;
  }
}

/** Den Eintrag merken: immer im Arbeitsspeicher, dazu im localStorage, soweit er mitspielt; nie eine Ausnahme. */
export function spaeterSchreiben(userId: string, eintrag: SpaeterEintrag, speicher: Speicher | null = lokalerSpeicher()): void {
  const schluessel = spaeterSchluessel(userId);
  const roh = JSON.stringify(eintrag);
  rueckfall.set(schluessel, roh);
  try {
    speicher?.setItem(schluessel, roh);
  } catch {
    // ohne Speicher gilt der Arbeitsspeicher, nach dem nächsten Start erscheint das Pop-up wieder
  }
}

/** Nur für Tests: den Arbeitsspeicher leeren. */
export function spaeterRueckfallLeeren(): void {
  rueckfall.clear();
}

// ---------- Anzeige ----------
export type HinweisArt = "aus" | "angebot" | "laeuft" | "fehler";

/**
 * Was das Pop-up zeigt: nichts, das Angebot, die laufende Installation oder einen Fehler mit der Möglichkeit, es noch einmal zu
 * versuchen. Ohne bestätigtes Angebot nie etwas, nach "Später" nichts, nach dem Start der Installation nichts mehr (die App beendet sich).
 */
export function hinweisArt(o: { angebot: UpdateAngebot | null; phase: InstallPhase; spaeter: boolean }): HinweisArt {
  if (o.phase.art === "gestartet" || !o.angebot || o.spaeter) return "aus";
  if (o.phase.art === "laeuft") return "laeuft";
  return o.phase.art === "fehler" ? "fehler" : "angebot";
}

/** Der Satz des Pop-ups; läuft gerade ein Gespräch, sagt er, dass das Update es beendet. */
export function hinweisSatz(version: string, gespraechLaeuft: boolean): string {
  const satz = `Version ${version} ist bereit. Die App startet nach der Installation neu.`;
  return gespraechLaeuft ? `${satz} Das laufende Gespräch wird beendet.` : satz;
}
