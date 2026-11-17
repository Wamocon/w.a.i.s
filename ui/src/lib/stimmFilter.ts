/**
 * Stimmfilter im Chat links (Block "Gespräch" und Verlauf). Entscheidung von Niko vom 17.11.2026: W.A.I.S. hört nur der eingelernten
 * Stimme zu, fremde Sätze erscheinen nirgends in der Oberfläche.
 *
 * Aktiv ist der Filter, wenn der Kern zuletzt {"type": "stimme", "status": "bereit", "modus": "streng"} gemeldet hat und das Konto kein
 * Laborkonto ist (useWamo.ts, filterFuer). Dann gilt:
 * - Ein endgültiges Transkript der Person wird zurückgehalten (NutzerTeil.frist), bis das Urteil des Kerns mit derselben Zeit kommt
 *   ({"type": "stimme", "ergebnis", "ignoriert", "zeit"}, lib/wamo.ts urteilEinarbeiten). ignoriert false zeigt den Satz, ignoriert true
 *   oder das leere Ersatztranskript verwirft ihn still.
 * - Rückfall, damit nie ein eigener Satz verloren geht: Kommt binnen HALTEN_MS kein passendes Urteil (etwa von einem älteren Kern ohne
 *   zeit) oder beginnt W.A.I.S. vorher zu antworten, erscheint der Satz.
 * - Zwischenstände erscheinen im Chat nicht. Getippter Text erscheint immer sofort, denn er ist kein gesprochener Teil (nimmeTextAuf).
 * Ohne aktiven Filter (kein Abdruck, anderer Modus, Laborkonto) bleibt alles wie vorher. Die Live-Untertitel unter dem Kern sind
 * standardmäßig aus (lib/untertitel.ts); wer sie einschaltet, sieht dort weiter sofort, was das Mikrofon hört.
 *
 * Reine Funktionen ohne React und ohne Browser, damit sie sich mit node:test prüfen lassen (stimmFilter.test.ts). Importe relativ mit
 * Endung, aus wamo.ts nur Typen (kein Kreis zur Laufzeit).
 */
import type { StimmeStand } from "./stimme.ts";
import type { Caption, NutzerTeil } from "./wamo.ts";

/** So lange hält der Chat einen Satz höchstens zurück, wenn kein Urteil dazu kommt. */
export const HALTEN_MS = 4000;

/** Prüft der Kern die Stimme so, dass er fremde Äußerungen verwirft (Abdruck bereit, Modus streng)? */
export const stimmFilterAktiv = (st: Pick<StimmeStand, "status" | "modus">): boolean => st.status === "bereit" && st.modus === "streng";

const gehalten = (t: NutzerTeil) => t.frist !== undefined;
const ohneFrist = (t: NutzerTeil): NutzerTeil => ({ zeit: t.zeit, text: t.text });

type ChatQuelle = Pick<Caption, "userDone" | "userLive"> & Partial<Pick<Caption, "userTeile" | "gefiltert">>;

/**
 * Text der Person für den Chat links. Ohne Filter wie bisher: die endgültigen Teile und der Zwischenstand. Mit Filter nur, was die
 * Stimmprüfung schon freigegeben hat: getippter Text und freie Teile, ohne Zwischenstand und ohne zurückgehaltene Teile.
 */
export function sichtbarerNutzerText(c: ChatQuelle): string {
  if (!c.gefiltert) return `${c.userDone} ${c.userLive}`.trim();
  const teile = c.userTeile ?? [];
  if (!teile.some(gehalten)) return c.userDone.trim();
  // Die Teile stehen in ihrer Reihenfolge am Ende von userDone (lib/wamo.ts, nutzerTranskript), davor steht nur Getipptes oder was schon
  // aus der Liste gefallen ist. Lässt sich das nicht mehr zuordnen, zeigt der Chat bis zum Rückfall lieber nichts.
  const alle = teile.map((t) => t.text).join(" ");
  if (!c.userDone.endsWith(alle)) return "";
  const vorne = c.userDone.slice(0, c.userDone.length - alle.length).trimEnd();
  const frei = teile.filter((t) => !gehalten(t)).map((t) => t.text);
  return [vorne, ...frei].filter(Boolean).join(" ").trim();
}

function freigeben(c: Caption, passt: (t: NutzerTeil, i: number) => boolean): Caption {
  if (!c.userTeile.some((t, i) => gehalten(t) && passt(t, i))) return c;
  return { ...c, userTeile: c.userTeile.map((t, i) => (gehalten(t) && passt(t, i) ? ohneFrist(t) : t)) };
}

/** Das Urteil zu genau diesem Zeitstempel hat den Satz angenommen: der jüngste zurückgehaltene Teil mit dieser Zeit erscheint. */
export function teilFreigeben(c: Caption, zeit: string): Caption {
  let ziel = -1;
  for (let i = c.userTeile.length - 1; i >= 0 && ziel < 0; i -= 1) if (gehalten(c.userTeile[i]) && c.userTeile[i].zeit === zeit) ziel = i;
  return ziel < 0 ? c : freigeben(c, (_, i) => i === ziel);
}

/** W.A.I.S. beginnt zu antworten: alles Zurückgehaltene erscheint (Rückfall). */
export const alleFreigeben = (c: Caption): Caption => freigeben(c, () => true);

/** Rückfall nach HALTEN_MS: jeder Teil, dessen Frist bis jetzt abgelaufen ist, erscheint. */
export const fristFreigeben = (c: Caption, jetzt: number): Caption => freigeben(c, (t) => (t.frist ?? Infinity) <= jetzt);

/** Früheste Frist eines zurückgehaltenen Teils (Date.now), null, wenn nichts wartet. */
export function naechsteFrist(c: Pick<Caption, "userTeile">): number | null {
  let frist: number | null = null;
  for (const t of c.userTeile) if (t.frist !== undefined && (frist === null || t.frist < frist)) frist = t.frist;
  return frist;
}
