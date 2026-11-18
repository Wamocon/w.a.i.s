import { createStore } from "./store.ts"; // relativ, damit node:test diese Datei laden kann (canvasWahl.test.ts)

/**
 * Wunsch aus der Tafel "Vorgänge" (Knopf "Ergebnis ansehen", components/kommando/Vorgaenge.tsx): dieses Canvas-Element soll
 * angezeigt werden. Das Canvas (components/Canvas.tsx) hält seine Auswahl selbst; es liest diesen Wunsch und wählt das Element.
 * Der Zähler n läuft bei jedem Wunsch hoch, auch bei derselben Kennung: so greift ein zweiter Klick, nachdem die Person
 * inzwischen ein anderes Element gewählt hat.
 */
export type CanvasWunsch = { id: string | null; n: number; stelle?: string };

export const canvasWunsch = createStore<CanvasWunsch>({ id: null, n: 0 });

/** Dieses Element zeigen: nach Kennung, oder nach stelle (Elemente ohne Kennung, etwa ein wieder geöffneter Reiter aus der Historie). */
export function canvasWaehlen(id: string, stelle?: string): void {
  canvasWunsch.set((alt) => ({ id, n: alt.n + 1, ...(stelle ? { stelle } : {}) }));
}

/**
 * Schlüssel des Reiters, den das Canvas gerade zeigt (lib/canvasHistorie.ts, canvasSchluessel), null ohne Canvas. Das Werkzeug
 * canvas_schliessen ohne Kennung schließt genau diesen (lib/wamo.ts); das Canvas (components/Canvas.tsx) hält ihn aktuell.
 */
export const canvasOffen = createStore<string | null>(null);

let stellen = 0;

/** Neue stelle für ein Element, das neu aufs Canvas kommt: bleibt über Überarbeitungen gleich und ist nie eine Kennung des Kerns. */
export function neueStelle(): string {
  stellen += 1;
  return `stelle-${stellen}`;
}

/** Stelle des Elements mit dieser Kennung im Canvas, sonst -1. */
export function canvasIndex(items: readonly { id?: string | null }[], id: string): number {
  if (!id) return -1;
  return items.findIndex((it) => it.id === id);
}

/** Wie ein Element aus der Nachricht canvas ins Canvas kam: aktualisiert (gleiche Kennung), ersetzt (Überarbeitung) oder neu.
 *  verdraengt: was dabei vorne herausfiel (höchstens max Elemente); es kommt in die Historie, nicht verloren. */
export type CanvasEinordnung<T> = { items: T[]; art: "aktualisiert" | "ersetzt" | "neu"; verdraengt: T[] };

/**
 * Ein Element aus der Nachricht canvas einordnen (lib/wamo.ts). Gleiche Kennung: Aktualisierung an Ort und Stelle (Fortschritt eines
 * Auftrags). ersetzt mit der Kennung eines Elements im Canvas: Überarbeitung (voice-core/canvas_sitzung.py), das neue Element nimmt die
 * Stelle des alten ein und erbt dessen stelle (bleibt über alle Fassungen gleich, damit ein offenes Formular am Element stehen bleibt).
 * Sonst kommt es hinten dazu, höchstens max Elemente, das älteste fällt heraus. Die alte Liste bleibt unverändert.
 */
export function canvasEinordnen<T extends { id?: string | null; stelle?: string }>(
  items: readonly T[],
  item: T,
  ersetzt: string | undefined,
  max: number,
): CanvasEinordnung<T> {
  const gleich = item.id ? canvasIndex(items, item.id) : -1;
  if (gleich >= 0) {
    const neu = [...items];
    neu[gleich] = { ...item, stelle: items[gleich].stelle };
    return { items: neu, art: "aktualisiert", verdraengt: [] };
  }
  const alt = ersetzt ? canvasIndex(items, ersetzt) : -1;
  if (alt >= 0) {
    const neu = [...items];
    neu[alt] = { ...item, stelle: items[alt].stelle ?? items[alt].id ?? undefined };
    return { items: neu, art: "ersetzt", verdraengt: [] };
  }
  const alle = [...items, item];
  const ueber = Math.max(0, alle.length - max);
  return { items: alle.slice(ueber), art: "neu", verdraengt: alle.slice(0, ueber) };
}
