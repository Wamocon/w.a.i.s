// Test des Update-Hinweises (components/UpdateHinweis.tsx) über sein CSS (components/updateHinweis.css): Das Band steht im normalen Fluss der
// Meldungen in der Mitte (kommando/Rahmen.tsx, Platz "meldungen") und überdeckt nie etwas.
// Fehlerbild vorher (PR 237): Eine feste Karte unten rechts (position: fixed, right und bottom, z-index 40) lag ab 1100 px Breite genau über den
// Knöpfen "Freigeben" und "Ablehnen" der Freigabekarten rechts unten, am Handy über der Eingabeleiste. Ein Hinweis, der nicht zwingend ist,
// darf keine bedienbare Fläche verdecken, auf keiner Breite. Darum hier: keine feste, absolute oder klebende Position, kein z-index, keine
// Abstände zum Fensterrand, kein pointer-events: none (das wäre die Bastelei, die Klicks durch eine Karte lässt) und keine Breitenbedingung,
// die das Band am Handy wieder über die Leiste legt.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const CSS = readFileSync(new URL("./updateHinweis.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

test("keine feste, absolute oder klebende Position: das Band liegt im Fluss", () => {
  assert.doesNotMatch(CSS, /position\s*:\s*(fixed|absolute|sticky)/);
});

test("kein z-index und kein Abstand zum Fensterrand: nichts schwebt über anderen Flächen", () => {
  assert.doesNotMatch(CSS, /z-index\s*:/);
  assert.doesNotMatch(CSS, /(^|[\s;{])(top|right|bottom|left|inset)\s*:/);
  assert.doesNotMatch(CSS, /(vw|vh|dvh|svh)\b/);
});

test("kein pointer-events: none und keine Rücksicht auf die feste Eingabeleiste (68 px) mehr nötig", () => {
  assert.doesNotMatch(CSS, /pointer-events\s*:\s*none/);
  assert.doesNotMatch(CSS, /68px/);
  assert.doesNotMatch(CSS, /safe-area-inset/);
});

test("das Band hat Rand, Hintergrund und eine Kante in der Markenfarbe (kein Blau, nur Farbwerte der Seite)", () => {
  assert.match(CSS, /\.uh\s*\{[^}]*var\(--panel\)/);
  assert.match(CSS, /\.uh\s*\{[^}]*var\(--core\)/);
  assert.doesNotMatch(CSS, /#[0-9a-f]{3,8}\b/i); // keine festen Farben, hell und dunkel folgen den Werten der Seite
});

test("reduzierte Bewegung schaltet die Einblendung ab", () => {
  assert.match(CSS, /prefers-reduced-motion\s*:\s*reduce\)\s*\{[^}]*\.uh\s*\{\s*animation\s*:\s*none/);
});
