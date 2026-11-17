// Tests für die Wahl der Live-Untertitel (lib/untertitel.ts): Standard aus, je Person auf diesem Gerät, nur "an" schaltet ein, ein
// gesperrter oder fehlender Speicher bleibt beim Standard.
// Ausführen im Ordner ui/:  npm test   (node:test, ohne Browser)
import assert from "node:assert/strict";
import { test } from "node:test";
import { UNTERTITEL_STANDARD, untertitelLesen, untertitelSchluessel, untertitelSchreiben } from "./untertitel.ts";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const ANDERE = "9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

function speicher() {
  const werte = new Map<string, string>();
  return {
    werte,
    getItem: (k: string) => werte.get(k) ?? null,
    setItem: (k: string, v: string) => void werte.set(k, v),
  };
}

const gesperrt = {
  getItem: () => {
    throw new Error("gesperrt");
  },
  setItem: () => {
    throw new Error("gesperrt");
  },
};

test("Standard aus, solange die Person nichts gewählt hat", () => {
  assert.equal(UNTERTITEL_STANDARD, false);
  assert.equal(untertitelLesen(speicher(), ID), false);
});

test("die Wahl gilt je Person: an für die eine, aus für die andere", () => {
  const sp = speicher();
  assert.equal(untertitelSchreiben(sp, ID, true), true);
  assert.equal(sp.werte.get(`wamo.untertitel.${ID}`), "an");
  assert.equal(untertitelLesen(sp, ID), true);
  assert.equal(untertitelLesen(sp, ANDERE), false);
  assert.equal(untertitelSchreiben(sp, ID, false), true);
  assert.equal(sp.werte.get(`wamo.untertitel.${ID}`), "aus");
  assert.equal(untertitelLesen(sp, ID), false);
});

test("nur 'an' schaltet ein, jeder andere Wert gilt als aus", () => {
  const sp = speicher();
  for (const wert of ["ja", "true", "1", "AN", ""]) {
    sp.werte.set(`wamo.untertitel.${ID}`, wert);
    assert.equal(untertitelLesen(sp, ID), false, wert);
  }
});

test("ohne brauchbare Kennung oder ohne Speicher bleibt es aus, Schreiben meldet false", () => {
  for (const id of [null, undefined, "", "a b", "../x", "x".repeat(65)]) {
    assert.equal(untertitelSchluessel(id), null, String(id));
    assert.equal(untertitelLesen(speicher(), id), false);
    assert.equal(untertitelSchreiben(speicher(), id, true), false);
  }
  assert.equal(untertitelLesen(null, ID), false);
  assert.equal(untertitelSchreiben(null, ID, true), false);
});

test("ein gesperrter Speicher (strenger Datenschutzmodus) wirft nie und bleibt beim Standard", () => {
  assert.equal(untertitelLesen(gesperrt, ID), false);
  assert.equal(untertitelSchreiben(gesperrt, ID, true), false);
});
