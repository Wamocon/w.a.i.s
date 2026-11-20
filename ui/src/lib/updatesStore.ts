import type { UpdateAngebot, UpdateStand } from "./einrichtung.ts";
import { updateInstallieren, updateStandLaden } from "./einrichtung.ts";
import { kernJson } from "./kernApi.ts";
import { createStore } from "./store.ts";
import { accessToken } from "./supabase.ts";
import { PHASE_RUHE, angebotAus, phaseNachInstallation, type InstallPhase } from "./updates.ts";

/**
 * Gemeinsamer Stand der Updates der Desktop-App: Der Abschnitt Updates der Einstellungen (components/einstellungen/Updates.tsx) und das
 * Pop-up "Update verfügbar" (components/UpdateHinweis.tsx) lesen und steuern denselben Speicher, damit es nur eine Quelle gibt (die
 * von der App bestätigte, lib/einrichtung.ts), nur eine Suche und nur eine Installation zugleich, auch wenn beide offen sind.
 *
 * Schutzregeln, unverändert: Ein Angebot gibt es nur, wenn die App Signatur und steigende Version bestätigt hat (lib/updates.ts,
 * angebotAus); die Oberfläche liest das Manifest nie. Das Token holt erst der Klick auf "Update installieren" (updateInstallieren) und
 * geht nur an die App; es steht in keinem Zustand dieses Speichers. Nach einem gestarteten Update (die App beendet sich) läuft nichts
 * mehr: keine weitere Suche, keine zweite Installation. Der Speicher gehört dem Fenster, nicht einer Komponente: Eine Antwort, die nach
 * dem Aushängen eintrifft, setzt keinen Zustand einer Komponente, sie landet hier und gilt für die nächste.
 */

export type UpdatesZustand = Readonly<{
  /** null, solange noch nie geprüft wurde */
  stand: UpdateStand | null;
  /** eine Suche läuft */
  sucht: boolean;
  /** Zeitpunkt der letzten Prüfung (Millisekunden seit 1970), null: noch nie */
  zeit: number | null;
  phase: InstallPhase;
}>;

const LEER: UpdatesZustand = Object.freeze({ stand: null, sucht: false, zeit: null, phase: PHASE_RUHE });

export const updates = createStore<UpdatesZustand>(LEER);

// sofort gesetzt (nicht erst mit dem nächsten Rendern), damit ein Doppelklick oder zwei Aufrufer im selben Takt nichts doppelt auslösen
let suchtJetzt = false;
let installiertJetzt = false; // bleibt nach einem gestarteten Update gesetzt: die App beendet sich

/** Darf jetzt gesucht werden? Nicht während einer Suche, nicht während und nicht nach einer Installation. */
export const updatesSucheMoeglich = (): boolean => !suchtJetzt && !installiertJetzt;

/**
 * Stand bei Server und App holen (dieselbe Quelle wie der Punkt App-Version der Prüfliste). Wirft nie. Eine neue Prüfung gilt mehr als der
 * Fehler der letzten Installation: Er wird dabei gelöscht.
 */
export async function updatesLaden(o: { behalteAngebot?: boolean } = {}): Promise<void> {
  if (!updatesSucheMoeglich()) return;
  suchtJetzt = true;
  updates.set((s) => ({ ...s, sucht: true }));
  try {
    const bruecke = typeof window === "undefined" ? undefined : window.wamoDesktop;
    const neu: UpdateStand = bruecke ? await updateStandLaden({ kernJson, bruecke }) : { art: "ohne_pruefung" };
    updates.set((s) => {
      // Eine Prüfung im Hintergrund (Takt, Wiederöffnen des Fensters) lässt ein bestätigtes Angebot nicht wegen einer Störung verschwinden
      // (kein Netz nach dem Aufwachen, Server kurz weg, die App antwortet nicht): Dann bleibt der alte Stand, und die nächste Prüfung kommt früh.
      if (o.behalteAngebot && angebotAus(s.stand) !== null && !endgueltig(neu)) return { ...s, sucht: false };
      return { stand: neu, sucht: false, zeit: Date.now(), phase: s.phase.art === "fehler" ? PHASE_RUHE : s.phase };
    });
  } finally {
    suchtJetzt = false;
    updates.set((s) => (s.sucht ? { ...s, sucht: false } : s));
  }
}

/**
 * Wie updatesLaden, aber nur, wenn die letzte Prüfung älter als maxAlterMs ist (regelmäßige Prüfung, Wiederöffnen des Fensters); eine
 * Störung ersetzt dabei kein bestätigtes Angebot.
 */
export function updatesLadenWennAlt(maxAlterMs: number, jetzt: number = Date.now()): Promise<void> {
  const { zeit } = updates.get();
  if (zeit !== null && jetzt - zeit < maxAlterMs) return Promise.resolve();
  return updatesLaden({ behalteAngebot: true });
}

/** Eine Antwort, die etwas aussagt: der Server hat nichts (mehr), die App bestätigt oder lehnt ab; keine Störung (nicht lesbar, nicht erreichbar). */
function endgueltig(stand: UpdateStand): boolean {
  return stand.art === "kein_angebot" || stand.art === "ohne_pruefung" || (stand.art === "geprueft" && stand.ergebnis.ok);
}

/**
 * Update installieren (höchstens eines zugleich, nie während einer Suche). Das Token holt erst hier updateInstallieren und gibt es nur an
 * die App. Die App fragt selbst nach, lädt, prüft und beendet sich; der Ausgang landet in der Phase.
 */
export async function updatesInstallieren(angebot: UpdateAngebot): Promise<void> {
  if (installiertJetzt || suchtJetzt) return;
  installiertJetzt = true;
  updates.set((s) => ({ ...s, phase: { art: "laeuft" } }));
  let gestartet = false;
  try {
    const erg = await updateInstallieren({ update: window.wamoDesktop?.update, angebot, token: accessToken });
    gestartet = erg.ok;
    updates.set((s) => ({ ...s, phase: phaseNachInstallation(erg) }));
  } finally {
    if (!gestartet) {
      installiertJetzt = false;
      // bricht etwas unterwegs ab, bleibt die Phase nicht auf "läuft" stehen (Knöpfe und Später blieben sonst gesperrt)
      updates.set((s) => (s.phase.art === "laeuft" ? { ...s, phase: PHASE_RUHE } : s));
    }
  }
}

/** Nach einem Fehler noch einmal mit demselben bestätigten Angebot (ist es überholt, sagt die App es mit ihrem Satz). */
export function updatesErneutVersuchen(): Promise<void> {
  if (!updatesSucheMoeglich()) return Promise.resolve(); // läuft gerade etwas, bleibt der Fehler stehen
  const { stand, phase } = updates.get();
  const angebot = angebotAus(stand);
  if (phase.art !== "fehler" || !angebot) return Promise.resolve();
  updates.set((s) => ({ ...s, phase: PHASE_RUHE }));
  return updatesInstallieren(angebot);
}

/** Nur für Tests: alles auf Anfang. */
export function updatesZuruecksetzen(): void {
  suchtJetzt = false;
  installiertJetzt = false;
  updates.set(() => LEER);
}
