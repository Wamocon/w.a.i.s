/**
 * Stimmfarben lesen statt sie doppelt zu definieren.
 *
 * Einzige Quelle sind die CSS-Variablen in app/globals.css (hell und dunkel):
 *   --voice-wamo, --voice-user, --voice-other                für Kern (Orb.tsx, KernRinge) und Stimmlinie
 *   --kern-heiss, --kern-mensch, --kern-fremd                 für die Glut der Lichtkugel (Orb.tsx)
 * Kern und Stimmlinie lesen sie per getComputedStyle.
 */

/** Farbe als Anteile 0 bis 1 (r, g, b, a). */
export type Rgba = [number, number, number, number];

/** #RGB, #RRGGBB oder #RRGGBBAA in Anteile umrechnen; anderes ergibt null. */
export function parseHex(value: string): Rgba | null {
  const v = value.trim().replace(/^#/, "");
  const full = v.length === 3 ? v.replace(/./g, (c) => c + c) : v;
  if (!/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(full)) return null;
  const n = (i: number) => parseInt(full.slice(i, i + 2), 16) / 255;
  return [n(0), n(2), n(4), full.length === 8 ? n(6) : 1];
}

/** CSS-Variable als Farbe lesen (Schwarz, falls nicht gesetzt). */
export function cssFarbe(style: CSSStyleDeclaration, name: string): Rgba {
  return parseHex(style.getPropertyValue(name)) ?? [0, 0, 0, 1];
}
