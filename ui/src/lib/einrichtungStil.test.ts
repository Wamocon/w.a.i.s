// Wächter: Die Stile des geführten Ablaufs der Erstanmeldung (components/anmeldung.css) und der Schritte des Ausrollens
// (components/einrichtung/einrichtung.css) teilen sich das Präfix .ea- und gelten beide global. Keine Klasse darf in beiden Dateien
// stehen, sonst überschreibt die eine die andere (so wurde die Schrittleiste der Erstanmeldung einmal zu dünnen Balken).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const klassen = (datei: string): Set<string> => {
  const text = readFileSync(new URL(datei, import.meta.url), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
  return new Set([...text.matchAll(/\.(ea(?:-[a-z0-9-]+)?)(?![a-z0-9-])/g)].map((m) => m[1]));
};

test("Erstanmeldung und Schritte des Ausrollens haben keine gemeinsame Klasse", () => {
  const anmeldung = klassen("../components/anmeldung.css");
  const einrichtung = klassen("../components/einrichtung/einrichtung.css");
  assert.ok(anmeldung.has("ea-leiste") && einrichtung.has("ea-balken"), "die Dateien wurden gelesen");
  const gemeinsam = [...anmeldung].filter((k) => einrichtung.has(k));
  assert.deepEqual(gemeinsam, []);
});
