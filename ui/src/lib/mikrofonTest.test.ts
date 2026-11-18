// Tests des Mikrofontests (lib/mikrofonTest.ts, Wunsch vom 18.11.2026): Ablauf in Phasen, Messung je Fenster (RMS und Spitze in dBFS),
// Auswertung zu Grundrauschen, Sprachpegel, Abstand und Übersteuerung mit Ampel und einem Satz, Speicher des letzten Ergebnisses je Gerät.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EINSCHWING_MS,
  RUHE_MS,
  SPRECHEN_MS,
  TEST_MAX_GERAETE,
  auswerten,
  db,
  dbText,
  ergebnisLesen,
  ergebnisMerken,
  fensterAufnehmen,
  neueMessung,
  phaseBei,
  testFehlerText,
  type Ergebnis,
  type Messung,
} from "./mikrofonTest.ts";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";

/** n Fenster einer Phase mit konstantem RMS und Spitze (lineare Werte 0 bis 1). */
function fenster(m: Messung, phase: "ruhe" | "sprechen", n: number, rms: number, spitze = rms * 3) {
  for (let i = 0; i < n; i++) fensterAufnehmen(m, phase, { rms, spitzeDb: spitze > 0 ? 20 * Math.log10(spitze) : Number.NEGATIVE_INFINITY });
}

/** Eine typische Messung: 50 Fenster Ruhe, 100 Fenster Sprechen. */
function messung(ruhe: number, sprache: number, spitze = sprache * 3): Messung {
  const m = neueMessung();
  fenster(m, "ruhe", 50, ruhe);
  fenster(m, "sprechen", 100, sprache, Math.min(1, spitze));
  return m;
}

class Speicher {
  daten = new Map<string, string>();
  getItem(k: string) {
    return this.daten.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.daten.set(k, v);
  }
}

test("Ablauf: kurz einschwingen, 3 s Ruhe, 5 s sprechen, dann fertig", () => {
  assert.equal(RUHE_MS, 3000);
  assert.equal(SPRECHEN_MS, 5000);
  assert.equal(phaseBei(0), "einschwingen");
  assert.equal(phaseBei(EINSCHWING_MS - 1), "einschwingen");
  assert.equal(phaseBei(EINSCHWING_MS), "ruhe");
  assert.equal(phaseBei(RUHE_MS - 1), "ruhe");
  assert.equal(phaseBei(RUHE_MS), "sprechen");
  assert.equal(phaseBei(RUHE_MS + SPRECHEN_MS - 1), "sprechen");
  assert.equal(phaseBei(RUHE_MS + SPRECHEN_MS), "fertig");
});

test("dBFS: 1 ist 0 dB, 0,1 ist -20 dB, Stille hat einen festen Boden", () => {
  assert.equal(db(1), 0);
  assert.equal(Math.round(db(0.1)), -20);
  assert.equal(db(0), -120);
  assert.equal(db(Number.NaN), -120);
});

test("gut: leiser Raum, Sprache um -20 dBFS, grün mit Abstand und Gerätenamen", () => {
  const e = auswerten(messung(0.001, 0.1), "Headset (USB)", 1000);
  assert.ok(e);
  assert.equal(e.bewertung, "gut");
  assert.equal(e.ampel, "gruen");
  assert.equal(e.geraet, "Headset (USB)");
  assert.equal(Math.round(e.rauschenDb), -60);
  assert.equal(Math.round(e.spracheDb), -20);
  assert.equal(Math.round(e.abstandDb), 40);
  assert.equal(e.zeit, 1000);
  assert.match(e.satz, /^Gut:/);
});

test("der Sprachpegel zählt die lauten Silben, nicht die Pausen beim Sprechen", () => {
  const m = neueMessung();
  fenster(m, "ruhe", 50, 0.001);
  fenster(m, "sprechen", 50, 0.001); // Pausen zwischen den Wörtern
  fenster(m, "sprechen", 50, 0.1);
  const e = auswerten(m, "Headset", 0);
  assert.ok(e);
  assert.equal(Math.round(e.spracheDb), -20);
  assert.equal(e.bewertung, "gut");
});

test("zu leise (rot) und etwas leise (gelb)", () => {
  const rot = auswerten(messung(0.0005, 0.005), "Mikrofonarray", 0); // etwa -46 dBFS
  assert.equal(rot?.bewertung, "zu_leise");
  assert.equal(rot?.ampel, "rot");
  assert.match(rot?.satz ?? "", /^Zu leise:/);
  const gelb = auswerten(messung(0.0005, 0.02), "Mikrofonarray", 0); // etwa -34 dBFS
  assert.equal(gelb?.bewertung, "leise");
  assert.equal(gelb?.ampel, "gelb");
});

test("übersteuert (rot): Spitzen an der Grenze in mehr als 2 % der Fenster beim Sprechen", () => {
  const m = messung(0.001, 0.1);
  fenster(m, "sprechen", 5, 0.3, 0.99);
  const e = auswerten(m, "Headset", 0);
  assert.equal(e?.bewertung, "uebersteuert");
  assert.equal(e?.ampel, "rot");
  assert.match(e?.satz ?? "", /^Übersteuert:/);
  const einzeln = messung(0.001, 0.1);
  fenster(einzeln, "sprechen", 1, 0.3, 0.99); // ein Klopfen allein übersteuert nicht
  assert.equal(auswerten(einzeln, "Headset", 0)?.bewertung, "gut");
});

test("zu laut (gelb): Sprache sehr nah an der Grenze, ohne zu übersteuern", () => {
  const e = auswerten(messung(0.001, 0.6, 0.85), "Headset", 0);
  assert.equal(e?.bewertung, "zu_laut");
  assert.equal(e?.ampel, "gelb");
});

test("Hintergrund: unter 20 dB Abstand gelb, unter 10 dB rot", () => {
  const gelb = auswerten(messung(0.02, 0.1), "Webcam", 0); // Abstand 14 dB
  assert.equal(gelb?.bewertung, "hintergrund");
  assert.equal(gelb?.ampel, "gelb");
  const rot = auswerten(messung(0.05, 0.1), "Webcam", 0); // Abstand 6 dB
  assert.equal(rot?.bewertung, "viel_hintergrund");
  assert.equal(rot?.ampel, "rot");
  assert.match(rot?.satz ?? "", /^Zu viel Hintergrund:/);
});

test("kein Ton: nur digitale Stille ist rot, vor allen anderen Befunden", () => {
  const e = auswerten(messung(0, 0, 0), "Dock-Mikrofon", 0);
  assert.equal(e?.bewertung, "kein_ton");
  assert.equal(e?.ampel, "rot");
});

test("zu wenige Fenster (gedrosselter Tab, abgebrochen): kein Ergebnis", () => {
  const m = neueMessung();
  fenster(m, "ruhe", 3, 0.001);
  fenster(m, "sprechen", 100, 0.1);
  assert.equal(auswerten(m, "Headset", 0), null);
  const n = neueMessung();
  fenster(n, "ruhe", 50, 0.001);
  fenster(n, "sprechen", 3, 0.1);
  assert.equal(auswerten(n, "Headset", 0), null);
});

test("Fenster mit unbrauchbaren Werten zählen nicht", () => {
  const m = messung(0.001, 0.1);
  fensterAufnehmen(m, "sprechen", { rms: Number.NaN, spitzeDb: Number.NaN });
  fensterAufnehmen(m, "sprechen", { rms: -1, spitzeDb: 0 });
  assert.equal(auswerten(m, "Headset", 0)?.bewertung, "gut");
});

test("Anzeige der Werte: eine Nachkommastelle, deutsches Komma, echtes Minuszeichen", () => {
  assert.equal(dbText(-20.34), "−20,3");
  assert.equal(dbText(39.96), "40,0");
});

test("Fehler beim Öffnen: je Art ein Satz mit Abhilfe, ohne Bezug auf ein Gespräch", () => {
  assert.match(testFehlerText("NotAllowedError"), /^Mikrofon gesperrt:.*teste noch einmal\.$/);
  assert.match(testFehlerText("OverconstrainedError"), /nicht zu finden/);
  assert.match(testFehlerText("NotReadableError"), /anderes Programm/);
  assert.match(testFehlerText(undefined), /System > Sound > Eingabe/);
  assert.match(testFehlerText("MessungAngehalten"), /noch einmal/);
  for (const n of ["NotAllowedError", "NotFoundError", "NotReadableError", "x"]) assert.doesNotMatch(testFehlerText(n), /Gespräch/);
});

test("Speicher: das letzte Ergebnis je Person und Gerät, Gerätename ohne Vorsatz des Standardgeräts", () => {
  const s = new Speicher();
  const e = auswerten(messung(0.001, 0.1), "Headset (USB)", 1000) as Ergebnis;
  assert.equal(ergebnisMerken(s, ID, e), true);
  assert.deepEqual(ergebnisLesen(s, ID, "Headset (USB)"), e);
  assert.deepEqual(ergebnisLesen(s, ID, "Standard - Headset (USB)"), e);
  assert.equal(ergebnisLesen(s, ID, "Webcam"), null);
  assert.equal(ergebnisLesen(s, "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b", "Headset (USB)"), null);
  const neuer = { ...e, zeit: 2000, bewertung: "leise" as const, ampel: "gelb" as const };
  ergebnisMerken(s, ID, neuer);
  assert.equal(ergebnisLesen(s, ID, "Headset (USB)")?.zeit, 2000);
});

test("Speicher: Gerätenamen wie constructor oder __proto__ sind nur Namen, gespeicherte Bewertungen nur aus der Liste", () => {
  const s = new Speicher();
  assert.equal(ergebnisLesen(s, ID, "constructor"), null);
  const e = auswerten(messung(0.001, 0.1), "__proto__", 0) as Ergebnis;
  assert.equal(ergebnisMerken(s, ID, e), true);
  assert.equal(ergebnisLesen(s, ID, "__proto__")?.bewertung, "gut");
  s.setItem(`wamo.mikrofontest.${ID}`, JSON.stringify({ headset: { ...e, geraet: "Headset", bewertung: "toString" } }));
  assert.equal(ergebnisLesen(s, ID, "Headset"), null);
});

test("Speicher: höchstens einige Geräte, das älteste fällt heraus", () => {
  const s = new Speicher();
  const e = auswerten(messung(0.001, 0.1), "x", 0) as Ergebnis;
  for (let i = 0; i <= TEST_MAX_GERAETE; i++) ergebnisMerken(s, ID, { ...e, geraet: `Gerät ${i}`, zeit: i });
  assert.equal(ergebnisLesen(s, ID, "Gerät 0"), null);
  assert.equal(ergebnisLesen(s, ID, `Gerät ${TEST_MAX_GERAETE}`)?.zeit, TEST_MAX_GERAETE);
});

test("Speicher: kaputte Daten, fehlende Person oder ein Speicher, der wirft, schaden nicht", () => {
  const s = new Speicher();
  s.setItem(`wamo.mikrofontest.${ID}`, "{kein json");
  assert.equal(ergebnisLesen(s, ID, "Headset"), null);
  s.setItem(`wamo.mikrofontest.${ID}`, JSON.stringify({ Headset: { geraet: "Headset", zeit: "gestern" } }));
  assert.equal(ergebnisLesen(s, ID, "Headset"), null);
  const e = auswerten(messung(0.001, 0.1), "Headset", 0) as Ergebnis;
  assert.equal(ergebnisMerken(s, null, e), false);
  assert.equal(ergebnisMerken(null, ID, e), false);
  const wirft = {
    getItem: () => {
      throw new Error("gesperrt");
    },
    setItem: () => {
      throw new Error("voll");
    },
  };
  assert.equal(ergebnisLesen(wirft, ID, "Headset"), null);
  assert.equal(ergebnisMerken(wirft, ID, e), false);
});
