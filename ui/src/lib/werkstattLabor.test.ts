// Tests für die Formulare des Labor-Planers (lib/werkstattLabor.ts): Termin, Plätze, Checkliste.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  checklistePruefen,
  erlaubteZwecke,
  fortschritt,
  kennungVorschlag,
  leererTermin,
  mitAufbewahrung,
  mitTag,
  mitZweck,
  platzZeilen,
  plaetzePruefen,
  standardTermin,
  terminFormular,
  terminPruefen,
} from "./werkstattLabor.ts";
import type { Termin } from "./werkstattTypen.ts";

const TERMIN: Termin = { id: "t1", tag: "2026-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18" };

test("Termin: der Labortag setzt die Aufbewahrung auf Tag plus 13, bis jemand sie von Hand wählt", () => {
  let f = mitTag(leererTermin(), "2026-12-05");
  assert.equal(f.aufbewahrungBis, "2026-12-18");
  f = mitTag(f, "2026-12-12");
  assert.equal(f.aufbewahrungBis, "2026-12-25");
  f = mitAufbewahrung(f, "2026-12-20");
  f = mitTag(f, "2026-12-13");
  assert.equal(f.aufbewahrungBis, "2026-12-20");
  assert.equal(mitTag(leererTermin(), "kaputt").aufbewahrungBis, "");
});

test("Termin: Formular aus einem Termin erkennt eine gewählte Aufbewahrung", () => {
  assert.equal(terminFormular(TERMIN).bisVonHand, false);
  assert.equal(terminFormular({ ...TERMIN, aufbewahrungBis: "2026-12-10" }).bisVonHand, true);
  assert.equal(terminFormular({ ...TERMIN, beginn: null }).beginn, "");
});

test("Termin: gültige Eingabe, Zeiten dürfen fehlen", () => {
  assert.deepEqual(terminPruefen(terminFormular(TERMIN)).eingabe, {
    tag: "2026-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18",
  });
  const ohneZeit = terminPruefen({ ...terminFormular(TERMIN), beginn: "", ende: "" }).eingabe;
  assert.equal(ohneZeit?.beginn, null);
  assert.equal(ohneZeit?.ende, null);
});

test("Termin: jede Verletzung einer Regel wird genannt", () => {
  const f = { ...terminFormular(TERMIN) };
  const felder = (teil: Partial<typeof f>) => terminPruefen({ ...f, ...teil }).probleme.map((p) => p.feld);
  assert.deepEqual(felder({ tag: "" }), ["tag"]);
  assert.deepEqual(felder({ beginn: "25:00" }), ["beginn"]);
  assert.deepEqual(felder({ ende: "8:00" }), ["ende"]);
  assert.deepEqual(felder({ beginn: "17:00", ende: "09:00" }), ["ende"]);
  assert.deepEqual(felder({ version: "0" }), ["version"]);
  assert.deepEqual(felder({ version: "100" }), ["version"]);
  assert.deepEqual(felder({ version: "x" }), ["version"]);
  assert.deepEqual(felder({ aufbewahrungBis: "" }), ["aufbewahrungBis"]);
  assert.deepEqual(felder({ aufbewahrungBis: "2026-12-20" }), ["aufbewahrungBis"]);
  assert.deepEqual(felder({ aufbewahrungBis: "2026-12-04" }), ["aufbewahrungBis"]);
  assert.deepEqual(felder({ aufbewahrungBis: "2026-12-19" }), []);
});

test("Standardtermin: der nächste ab heute, sonst der jüngste vergangene", () => {
  const a = { ...TERMIN, id: "a", tag: "2026-11-28" };
  const b = { ...TERMIN, id: "b", tag: "2026-12-05" };
  assert.equal(standardTermin([b, a], "2026-11-20")?.id, "a");
  assert.equal(standardTermin([b, a], "2026-11-29")?.id, "b");
  assert.equal(standardTermin([b, a], "2027-01-01")?.id, "b");
  assert.equal(standardTermin([], "2026-11-20"), null);
});

test("Plätze: 16 Zeilen, Abnahme nur an 15 und 16, Kennung als Vorschlag mit dem Zweck", () => {
  const z = platzZeilen([{ platz: 2, zweck: "besucher", kennung: "labor-02", gast: "Gast 2" }]);
  assert.equal(z.length, 16);
  assert.equal(z[1].zweck, "besucher");
  assert.equal(z[0].zweck, "");
  assert.deepEqual(erlaubteZwecke(3), ["besucher", "reserve"]);
  assert.deepEqual(erlaubteZwecke(15), ["besucher", "reserve", "abnahme"]);
  assert.equal(kennungVorschlag(7), "labor-07");
  assert.deepEqual(mitZweck(z[0], "reserve"), { platz: 1, zweck: "reserve", kennung: "labor-01", gast: "" });
  assert.deepEqual(mitZweck({ ...z[0], zweck: "reserve", kennung: "labor-xy", gast: "Gast" }, ""), { platz: 1, zweck: "", kennung: "", gast: "" });
  assert.equal(mitZweck({ ...z[0], kennung: "labor-xy" }, "besucher").kennung, "labor-xy");
});

test("Plätze: gültige Eingabe lässt leere Plätze weg, Gast als Pseudonym oder leer", () => {
  const z = platzZeilen([]).map((p) => p);
  z[0] = { platz: 1, zweck: "besucher", kennung: "labor-01", gast: " Gast  1 " };
  z[1] = { platz: 2, zweck: "reserve", kennung: "labor-02", gast: "" };
  const r = plaetzePruefen(z);
  assert.deepEqual(r.probleme, []);
  assert.deepEqual(r.plaetze, [
    { platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" },
    { platz: 2, zweck: "reserve", kennung: "labor-02", gast: null },
  ]);
  assert.deepEqual(plaetzePruefen(platzZeilen([])).plaetze, []);
});

test("Plätze: Abnahme, Kennung, doppelte Kennung und langer Gast werden abgelehnt", () => {
  const z = platzZeilen([]);
  z[2] = { platz: 3, zweck: "abnahme", kennung: "labor-03", gast: "" };
  z[3] = { platz: 4, zweck: "besucher", kennung: "Labor_4", gast: "" };
  z[4] = { platz: 5, zweck: "besucher", kennung: "labor-03", gast: "x".repeat(21) };
  const r = plaetzePruefen(z);
  assert.equal(r.plaetze, null);
  assert.equal(r.probleme.length, 4);
  assert.match(r.probleme[0].text, /Abnahme gibt es nur an den Plätzen 15 und 16/);
  assert.match(r.probleme[1].text, /Platz 4: Die Kennung muss/);
  assert.match(r.probleme[2].text, /schon an einem anderen Platz/);
  assert.match(r.probleme[3].text, /höchstens 20 Zeichen/);
  const ok = platzZeilen([]);
  ok[14] = { platz: 15, zweck: "abnahme", kennung: "labor-15", gast: "" };
  assert.equal(plaetzePruefen(ok).plaetze?.[0].zweck, "abnahme");
});

test("Checkliste: Titel Pflicht, Quelle und Datum optional", () => {
  assert.deepEqual(checklistePruefen({ titel: " Zertifikat  prüfen ", quelle: "", faellig: "2026-12-01" }).eingabe, { titel: "Zertifikat prüfen", quelle: null, faellig: "2026-12-01" });
  assert.deepEqual(checklistePruefen({ titel: "A", quelle: "Runbook 9", faellig: "" }).eingabe, { titel: "A", quelle: "Runbook 9", faellig: null });
  assert.deepEqual(checklistePruefen({ titel: "", quelle: "", faellig: "" }).probleme.map((p) => p.feld), ["titel"]);
  assert.deepEqual(checklistePruefen({ titel: "x".repeat(121), quelle: "y".repeat(81), faellig: "morgen" }).probleme.map((p) => p.feld), ["titel", "quelle", "faellig"]);
});

test("Fortschritt der Checkliste", () => {
  assert.deepEqual(fortschritt([]), { erledigt: 0, gesamt: 0, prozent: 0 });
  assert.deepEqual(fortschritt([{ erledigt: true }, { erledigt: false }, { erledigt: true }]), { erledigt: 2, gesamt: 3, prozent: 67 });
});
