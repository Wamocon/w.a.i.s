// Tests der Pegelwarnung (lib/pegelWarnung.ts): sehr leises Mikrofon über etwa 10 s Sprechen, einmal je Gespräch, nie während W.A.I.S.
// spricht, nie über einer anderen Meldung. Die Zeit läuft hier in Takten von 50 ms wie in useWamo.ts.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  LEISE_ANTEIL_MAX,
  LEISE_PEGEL,
  LEISE_SPRECHZEIT_MS,
  LEISE_TEXT,
  PEGEL_TAKT_MS,
  leiseNeuMessen,
  neueLeise,
  pruefeLeise,
  type LeiseLage,
  type LeiseZustand,
} from "./pegelWarnung.ts";

const SPRECHEN: LeiseLage = { pegel: 0.01, nutzerSpricht: true, wamoSpricht: false, aktiv: true, frei: true };

/** Lässt n Takte laufen und zählt, wie oft der Hinweis fällig war. */
function takte(z: LeiseZustand, n: number, lage: Partial<LeiseLage> | ((i: number) => Partial<LeiseLage>) = {}): number {
  let gezeigt = 0;
  for (let i = 0; i < n; i++) {
    const extra = typeof lage === "function" ? lage(i) : lage;
    if (pruefeLeise(z, { ...SPRECHEN, ...extra }, PEGEL_TAKT_MS)) gezeigt++;
  }
  return gezeigt;
}

const ZEHN_S = LEISE_SPRECHZEIT_MS / PEGEL_TAKT_MS;

test("Schwelle und Text: 0,04 auf der Anzeigeskala (etwa -34 dBFS), 10 s Sprechen, höchstens 5 % laut", () => {
  assert.equal(LEISE_PEGEL, 0.04);
  assert.equal(LEISE_SPRECHZEIT_MS, 10_000);
  assert.equal(LEISE_ANTEIL_MAX, 0.05);
  assert.equal(LEISE_TEXT, "Dein Mikrofon ist sehr leise. Ist das richtige Gerät gewählt?");
});

test("sehr leise beim Sprechen: nach 10 s Sprechzeit genau einmal je Gespräch", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S - 1), 0);
  assert.equal(takte(z, 1), 1);
  assert.equal(takte(z, ZEHN_S * 3), 0); // einmal je Gespräch
  assert.equal(z.gezeigt, true);
});

test("normale Sprache warnt nie, auch über Minuten", () => {
  const z = neueLeise();
  // Sprache wechselt zwischen Silben (laut) und Pausen (leise): jeder dritte Takt über der Schwelle
  assert.equal(takte(z, ZEHN_S * 12, (i) => ({ pegel: i % 3 === 0 ? 0.15 : 0.01 })), 0);
});

test("einzelne Ausreißer verhindern die Warnung nicht, mehr als 5 % laute Zeit schon", () => {
  const z = neueLeise();
  // zwei laute Takte (Husten) in 10 s: 0,1 s laut, 1 %
  assert.equal(takte(z, ZEHN_S, (i) => ({ pegel: i === 10 || i === 11 ? 0.5 : 0.01 })), 1);
  const z2 = neueLeise();
  // 20 % der Takte laut: kein Hinweis
  assert.equal(takte(z2, ZEHN_S * 2, (i) => ({ pegel: i % 5 === 0 ? 0.2 : 0.01 })), 0);
});

test("nur Sprechzeit zählt: Stille ohne Sprechen, stummes Mikrofon oder keine Verbindung warnen nie", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S * 3, { nutzerSpricht: false }), 0);
  assert.equal(takte(z, ZEHN_S * 3, { aktiv: false }), 0);
  assert.equal(z.sprechMs, 0);
});

test("während W.A.I.S. spricht: keine Messung und kein Hinweis, er kommt erst danach", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S * 2, { wamoSpricht: true }), 0);
  assert.equal(z.sprechMs, 0);
  assert.equal(takte(z, ZEHN_S - 1), 0);
  // fällig, während W.A.I.S. gerade anfängt zu sprechen: warten
  assert.equal(takte(z, 1, { wamoSpricht: true, nutzerSpricht: false }), 0);
  assert.equal(takte(z, 1, { nutzerSpricht: false }), 0); // noch nicht fällig (der letzte Takt fehlte)
  assert.equal(takte(z, 1), 1);
});

test("fällig, aber eine andere Meldung steht: der Hinweis wartet, bis sie weg ist, und während W.A.I.S. spricht weiter", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S, { frei: false }), 0);
  assert.equal(z.faellig, true);
  assert.equal(takte(z, 20, { frei: false, nutzerSpricht: false }), 0);
  assert.equal(takte(z, 5, { wamoSpricht: true, nutzerSpricht: false }), 0);
  assert.equal(takte(z, 1, { nutzerSpricht: false }), 1);
});

test("ein wartender Hinweis verfällt, wenn beim Sprechen wieder genug laute Zeit zusammenkommt", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S, { frei: false }), 0);
  assert.equal(z.faellig, true);
  // die Person spricht jetzt mit normalem Pegel (zum Beispiel ein anderes Gerät von Windows), die Anzeige ist noch belegt
  assert.equal(takte(z, 20, { frei: false, pegel: 0.2 }), 0);
  assert.equal(z.faellig, false);
  assert.equal(takte(z, 40, { nutzerSpricht: false }), 0); // Anzeige frei: kein veralteter Hinweis
  // ein kurzer lauter Moment (unter einer halben Sekunde) hebt ihn nicht auf
  const z2 = neueLeise();
  takte(z2, ZEHN_S, { frei: false });
  takte(z2, 5, { frei: false, pegel: 0.2 });
  assert.equal(z2.faellig, true);
  assert.equal(takte(z2, 1, { nutzerSpricht: false }), 1);
});

test("Gerätewechsel misst neu, ein schon gezeigter Hinweis bleibt gezeigt", () => {
  const z = neueLeise();
  takte(z, ZEHN_S - 10);
  leiseNeuMessen(z);
  assert.equal(z.sprechMs, 0);
  assert.equal(takte(z, ZEHN_S - 1), 0);
  assert.equal(takte(z, 1), 1);
  leiseNeuMessen(z);
  assert.equal(takte(z, ZEHN_S * 2), 0);
});

test("ein normaler Abschnitt beginnt neu, ein späteres leises Gerät wird noch erkannt", () => {
  const z = neueLeise();
  assert.equal(takte(z, ZEHN_S, { pegel: 0.2 }), 0);
  assert.equal(z.sprechMs, 0);
  assert.equal(takte(z, ZEHN_S), 1);
});

test("ein lange schlafender Tab täuscht keine Sprechzeit vor, ungültige Werte zählen nicht", () => {
  const z = neueLeise();
  assert.equal(pruefeLeise(z, SPRECHEN, 60_000), false);
  assert.equal(z.sprechMs, 4 * PEGEL_TAKT_MS);
  pruefeLeise(z, SPRECHEN, Number.NaN);
  pruefeLeise(z, SPRECHEN, -50);
  assert.equal(z.sprechMs, 4 * PEGEL_TAKT_MS);
  pruefeLeise(z, { ...SPRECHEN, pegel: Number.NaN }, PEGEL_TAKT_MS);
  assert.equal(z.lautMs, 0);
});
