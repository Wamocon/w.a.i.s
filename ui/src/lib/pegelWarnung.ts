/**
 * Pegelwarnung (Befund 17.11.2026): Im Browser lief ein anderes, sehr leises Mikrofon als in der Desktop-App. Die Pegelanzeige schlug kaum
 * aus, die Stimmprüfung hielt den Besitzer für fremd, und niemand merkte, dass das falsche Gerät lief. Der Stille-Wächter (lib/mikrofon.ts)
 * greift dabei nicht, er meldet nur digitale Stille. Diese Regel meldet ein Mikrofon, das zwar Ton liefert, aber viel zu leise ist.
 *
 * Messung: Die Oberfläche misst den eigenen Pegel 20-mal je Sekunde (useWamo.ts, levelsRef.user). Es sind dieselben Werte, die Stimmlinie,
 * Kern und Rand zeigen (anzeigePegel in lib/mikrofon.ts: RMS eines Fensters von 2048 Abtastwerten mal 2).
 *
 * Sprechversuch: die Zeit, in der der Kern meldet, dass die Person spricht (onUserStartedSpeaking bis onUserStoppedSpeaking, Präsenz
 * "listening"). Spricht W.A.I.S., zählt nichts (das Echo der eigenen Ausgabe soll weder warnen noch beruhigen).
 *
 * Schwelle LEISE_PEGEL = 0,04 auf der Anzeigeskala, also RMS 0,02 (etwa -34 dBFS). Begründung: Sprache an einem passenden Mikrofon liegt mit
 * der automatischen Verstärkung des Browsers auf dieser Skala bei 0,1 bis 0,3 (etwa -26 bis -16 dBFS, siehe anzeigePegel), ein ruhiger Raum
 * ohne Sprache unter 0,01 (unter -46 dBFS). Ein Fenster mit Sprache überschreitet 0,04 bei einem brauchbaren Mikrofon in fast jeder
 * betonten Silbe, ein falsches oder weit entferntes Mikrofon (Laptop am Dock, Webcam, Mikrofon im Nachbarraum) bleibt mit Sprache darunter.
 *
 * Regel: In Abschnitten von LEISE_SPRECHZEIT_MS (10 s) Sprechzeit wird gezählt, wie lange der Pegel mindestens LEISE_PEGEL erreichte. War es
 * höchstens LEISE_ANTEIL_MAX (5 %, also eine halbe Sekunde), ist die Warnung fällig; sonst beginnt der nächste Abschnitt. Ein einzelner
 * Ausreißer (Husten, Klopfen) verhindert so keine Warnung, normale Sprache (weit über 5 % der Fenster laut) löst nie eine aus. Gezeigt wird
 * die Warnung einmal je Gespräch, nie während W.A.I.S. spricht und nie über einer anderen Meldung (sie wartet, bis die Meldung weg ist).
 * Während sie wartet, misst die Regel weiter: Kommt beim Sprechen wieder mehr als die erlaubte laute Zeit (eine halbe Sekunde) zusammen, ist
 * sie hinfällig, und die Messung beginnt neu. Ein Gerätewechsel beginnt die Messung ebenfalls neu.
 *
 * Reine Logik ohne Browser (Tests: pegelWarnung.test.ts); die Verdrahtung liegt in useWamo.ts.
 */

export const LEISE_PEGEL = 0.04;
export const LEISE_SPRECHZEIT_MS = 10_000;
export const LEISE_ANTEIL_MAX = 0.05;
/** Takt der Pegelmessung in useWamo.ts (20 Hz). Ein gedrosselter Tab tickt seltener, das verlängert die Messung nur. */
export const PEGEL_TAKT_MS = 50;

export const LEISE_TEXT = "Dein Mikrofon ist sehr leise. Ist das richtige Gerät gewählt?";

export type LeiseZustand = {
  /** Sprechzeit im laufenden Abschnitt */
  sprechMs: number;
  /** davon mit Pegel ab LEISE_PEGEL */
  lautMs: number;
  /** ein Abschnitt war zu leise: zeigen, sobald es geht (sprechMs und lautMs zählen dann ab diesem Zeitpunkt) */
  faellig: boolean;
  /** in diesem Gespräch schon gezeigt */
  gezeigt: boolean;
};

export const neueLeise = (): LeiseZustand => ({ sprechMs: 0, lautMs: 0, faellig: false, gezeigt: false });

export type LeiseLage = {
  /** eigener Pegel auf der Anzeigeskala (0 bis 1) */
  pegel: number;
  /** der Kern meldet: die Person spricht */
  nutzerSpricht: boolean;
  /** W.A.I.S. spricht gerade */
  wamoSpricht: boolean;
  /** verbunden, Mikrofon an, Messung läuft */
  aktiv: boolean;
  /** keine andere Meldung steht */
  frei: boolean;
};

/** Neues Gerät: die Messung beginnt von vorn, ein schon gezeigter Hinweis bleibt gezeigt. */
export function leiseNeuMessen(z: LeiseZustand): void {
  z.sprechMs = 0;
  z.lautMs = 0;
  z.faellig = false;
}

/**
 * Ein Takt der Messung. true genau einmal je Gespräch: jetzt den Hinweis zeigen (der Zustand merkt sich das). dtMs ist die Zeit des
 * Takts; sie wird auf 0 bis 4 Takte begrenzt, damit ein lange schlafender Tab keine Sprechzeit vortäuscht.
 */
export function pruefeLeise(z: LeiseZustand, lage: LeiseLage, dtMs: number = PEGEL_TAKT_MS): boolean {
  if (z.gezeigt) return false;
  if (!lage.aktiv) return false;
  if (lage.nutzerSpricht && !lage.wamoSpricht) {
    const dt = Math.min(Math.max(Number.isFinite(dtMs) ? dtMs : 0, 0), 4 * PEGEL_TAKT_MS);
    z.sprechMs += dt;
    if (Number.isFinite(lage.pegel) && lage.pegel >= LEISE_PEGEL) z.lautMs += dt;
    if (z.faellig) {
      // wartet auf eine freie Anzeige: wieder genug laute Zeit beim Sprechen, dann ist der Hinweis hinfällig
      if (z.lautMs > LEISE_SPRECHZEIT_MS * LEISE_ANTEIL_MAX) leiseNeuMessen(z);
    } else if (z.sprechMs >= LEISE_SPRECHZEIT_MS) {
      z.faellig = z.lautMs <= z.sprechMs * LEISE_ANTEIL_MAX;
      z.sprechMs = 0;
      z.lautMs = 0;
    }
  }
  if (z.faellig && !lage.wamoSpricht && lage.frei) {
    z.gezeigt = true;
    return true;
  }
  return false;
}
