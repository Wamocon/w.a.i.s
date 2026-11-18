// Tests für den Hinweis bei Gerätewechsel (lib/stimmMikrofon.ts, Befund 18.11.2026): Die Stimme war mit einem Bluetooth-Headset eingelernt
// und wurde mit dem eingebauten Mikrofon geprüft, die Werte lagen 0,15 bis 0,25 tiefer. Die Oberfläche merkt sich beim Einlernen das Mikrofon
// (nur im Speicher des Browsers) und fragt, wenn im Gespräch ein anderes läuft.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { geraeteName } from "./mikrofon.ts";
import {
  ANDERES_MIKROFON_TEXT,
  anderesMikrofon,
  geraetHinweisFaellig,
  stimmMikrofonLesen,
  stimmMikrofonMerken,
  stimmMikrofonVergessen,
  type GeraetHinweisLage,
} from "./stimmMikrofon.ts";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";
const ANDERE = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";

class Speicher {
  daten = new Map<string, string>();
  getItem(k: string) {
    return this.daten.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.daten.set(k, v);
  }
  removeItem(k: string) {
    this.daten.delete(k);
  }
}

const LAGE: GeraetHinweisLage = {
  gemerkt: "Headset (Bluetooth)",
  aktuell: "Mikrofonarray (Realtek)",
  stimmeBereit: true,
  frei: true,
  wamoSpricht: false,
  einlernen: false,
};

test("Gerätename: ohne den Vorsatz des Standard- oder Kommunikationsgeräts, getrimmt und gekürzt", () => {
  assert.equal(geraeteName("Standard - Headset (USB)"), "Headset (USB)");
  assert.equal(geraeteName("Default - Headset (USB)"), "Headset (USB)");
  assert.equal(geraeteName("Kommunikation – Headset (USB)"), "Headset (USB)");
  assert.equal(geraeteName("  Headset - Jabra Evolve  "), "Headset - Jabra Evolve"); // ein Strich im Namen selbst bleibt
  assert.equal(geraeteName("x".repeat(200))?.length, 120);
  assert.equal(geraeteName(""), null);
  assert.equal(geraeteName(null), null);
});

test("merken, lesen und vergessen je Person; der Name einer anderen Person zählt nicht", () => {
  const s = new Speicher();
  assert.equal(stimmMikrofonMerken(s, ID, "Standard - Headset (Bluetooth)"), true);
  assert.equal(stimmMikrofonLesen(s, ID), "Headset (Bluetooth)");
  assert.equal(stimmMikrofonLesen(s, ANDERE), null);
  stimmMikrofonVergessen(s, ID);
  assert.equal(stimmMikrofonLesen(s, ID), null);
});

test("ohne Person, ohne Namen oder mit einem Speicher, der wirft: nichts gemerkt, kein Fehler", () => {
  const s = new Speicher();
  assert.equal(stimmMikrofonMerken(s, null, "Headset"), false);
  assert.equal(stimmMikrofonMerken(s, "kein gültiger name!", "Headset"), false);
  assert.equal(stimmMikrofonMerken(s, ID, null), false);
  assert.equal(s.daten.size, 0);
  const wirft = {
    getItem: () => {
      throw new Error("gesperrt");
    },
    setItem: () => {
      throw new Error("voll");
    },
    removeItem: () => {
      throw new Error("gesperrt");
    },
  };
  assert.equal(stimmMikrofonMerken(wirft, ID, "Headset"), false);
  assert.equal(stimmMikrofonLesen(wirft, ID), null);
  assert.doesNotThrow(() => stimmMikrofonVergessen(wirft, ID));
  s.setItem(`wamo.stimme.mikrofon.${ID}`, "   ");
  assert.equal(stimmMikrofonLesen(s, ID), null);
});

test("anderes Mikrofon nur, wenn beide Namen bekannt sind und sich unterscheiden", () => {
  assert.equal(anderesMikrofon("Headset (Bluetooth)", "Mikrofonarray (Realtek)"), true);
  assert.equal(anderesMikrofon("Headset (Bluetooth)", "Standard - Headset (Bluetooth)"), false);
  assert.equal(anderesMikrofon("Headset (Bluetooth)", "headset (bluetooth)"), false);
  assert.equal(anderesMikrofon(null, "Mikrofonarray (Realtek)"), false); // vor dieser Neuerung eingelernt: unbekannt, kein Hinweis
  assert.equal(anderesMikrofon("Headset (Bluetooth)", null), false);
});

test("der Hinweis kommt nur bei bereitem Abdruck, freier Anzeige, ohne Rede von W.A.I.S. und nicht beim Einlernen", () => {
  const gezeigt = new Set<string>();
  assert.equal(geraetHinweisFaellig(LAGE, gezeigt), "mikrofonarray (realtek)");
  for (const anders of [{ stimmeBereit: false }, { frei: false }, { wamoSpricht: true }, { einlernen: true }, { aktuell: "Headset (Bluetooth)" }]) {
    assert.equal(geraetHinweisFaellig({ ...LAGE, ...anders }, gezeigt), null, JSON.stringify(anders));
  }
});

test("einmal je Gerät und Gespräch", () => {
  const gezeigt = new Set<string>(["mikrofonarray (realtek)"]);
  assert.equal(geraetHinweisFaellig(LAGE, gezeigt), null);
  assert.equal(geraetHinweisFaellig({ ...LAGE, aktuell: "Webcam-Mikrofon" }, gezeigt), "webcam-mikrofon");
});

test("der Satz fragt und nennt keinen Gerätenamen", () => {
  assert.equal(ANDERES_MIKROFON_TEXT, "Deine Stimme ist mit einem anderen Mikrofon eingelernt. Für dieses Mikrofon neu einlernen?");
});
