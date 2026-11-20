// Tests für die Fristen des Labor-Planers (lib/werkstattFristen.ts): Rechnen auf Kalendertagen, Wochentage, Fälligkeit.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  aufbewahrungGueltig,
  faelligkeit,
  fristen,
  heuteIso,
  istTag,
  tagKurz,
  tagPlus,
  tagText,
  tageZwischen,
  uhrzeit,
  zeitraumGueltig,
} from "./werkstattFristen.ts";

test("Fristen: Aufbewahrung Tag plus 13, Löschlauf einen Tag danach, Nachlauf zwei Tage nach dem Labortag", () => {
  const f = fristen("2026-12-05");
  assert.deepEqual(f, { aufbewahrungBis: "2026-12-18", loeschlaufAb: "2026-12-19", nachlaufAb: "2026-12-07" });
});

test("Fristen: ein gewählter Wert für die Aufbewahrung verschiebt den Löschlauf mit", () => {
  const f = fristen("2026-12-05", "2026-12-12");
  assert.deepEqual(f, { aufbewahrungBis: "2026-12-12", loeschlaufAb: "2026-12-13", nachlaufAb: "2026-12-07" });
  // ein ungültiger Wert fällt auf die Vorgabe zurück
  assert.equal(fristen("2026-12-05", "kaputt")?.aufbewahrungBis, "2026-12-18");
});

test("Fristen über Monats- und Jahresgrenzen und im Schaltjahr", () => {
  assert.equal(tagPlus("2026-12-25", 13), "2027-01-07");
  assert.equal(tagPlus("2028-02-28", 1), "2028-02-29");
  assert.equal(tagPlus("2027-02-28", 1), "2027-03-01");
  assert.equal(tagPlus("2026-03-28", 2), "2026-03-30"); // Sommerzeit spielt keine Rolle
  assert.equal(tagPlus("2026-12-05", -5), "2026-11-30");
});

test("ungültige Tage ergeben null, nie einen verschobenen Tag", () => {
  for (const wert of ["2026-02-30", "2026-13-01", "26-12-05", "", "2026-12-5", "2026-12-05T00:00"]) {
    assert.equal(istTag(wert), false, wert);
    assert.equal(tagPlus(wert, 1), null, wert);
    assert.equal(fristen(wert), null, wert);
  }
  assert.equal(istTag(20261205), false);
  assert.equal(tagPlus("2026-12-05", 1.5), null);
});

test("Aufbewahrung: zwischen dem Labortag und 14 Tage danach", () => {
  assert.ok(aufbewahrungGueltig("2026-12-05", "2026-12-05"));
  assert.ok(aufbewahrungGueltig("2026-12-05", "2026-12-19"));
  assert.ok(!aufbewahrungGueltig("2026-12-05", "2026-12-20"));
  assert.ok(!aufbewahrungGueltig("2026-12-05", "2026-12-04"));
  assert.ok(!aufbewahrungGueltig("kaputt", "2026-12-04"));
});

test("tageZwischen zählt Kalendertage", () => {
  assert.equal(tageZwischen("2026-12-05", "2026-12-18"), 13);
  assert.equal(tageZwischen("2026-12-18", "2026-12-05"), -13);
  assert.equal(tageZwischen("2026-12-05", "x"), null);
});

test("Datumstexte mit Wochentag und kurz", () => {
  assert.equal(tagText("2026-12-05"), "Sa 05.12.2026");
  assert.equal(tagText("2026-12-18"), "Fr 18.12.2026");
  assert.equal(tagText("2026-12-07"), "Mo 07.12.2026");
  assert.equal(tagText(null), "");
  assert.equal(tagText("irgendwas"), "irgendwas");
  assert.equal(tagKurz("2026-11-07"), "07.11.");
  assert.equal(tagKurz("x"), "x");
});

test("heuteIso nimmt die Ortszeit", () => {
  assert.equal(heuteIso(new Date(2026, 11, 5, 23, 59)), "2026-12-05");
  assert.equal(heuteIso(new Date(2026, 0, 1, 0, 0)), "2026-01-01");
});

test("Fälligkeit eines Punktes der Checkliste", () => {
  assert.equal(faelligkeit("2026-12-01", true, "2026-12-03"), "erledigt");
  assert.equal(faelligkeit(null, false, "2026-12-03"), "ohne");
  assert.equal(faelligkeit("kaputt", false, "2026-12-03"), "ohne");
  assert.equal(faelligkeit("2026-12-02", false, "2026-12-03"), "ueberfaellig");
  assert.equal(faelligkeit("2026-12-03", false, "2026-12-03"), "heute");
  assert.equal(faelligkeit("2026-12-04", false, "2026-12-03"), "offen");
});

test("Uhrzeit: nur HH:MM, Sekunden aus der Datenbank werden gekürzt", () => {
  assert.equal(uhrzeit("09:30"), "09:30");
  assert.equal(uhrzeit("09:30:00"), "09:30");
  assert.equal(uhrzeit("24:00"), null);
  assert.equal(uhrzeit("9:30"), null);
  assert.equal(uhrzeit(930), null);
  assert.ok(zeitraumGueltig("09:00", "17:00"));
  assert.ok(!zeitraumGueltig("17:00", "09:00"));
  assert.ok(!zeitraumGueltig("09:00", "09:00"));
  assert.ok(zeitraumGueltig(null, "09:00"));
  assert.ok(zeitraumGueltig("09:00", null));
});
