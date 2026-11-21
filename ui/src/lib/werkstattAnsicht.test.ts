// Tests für Ansicht, Diagramm-Geometrie und den Vierschritt der Werkstatt (lib/werkstattAnsicht.ts, werkstattDiagramm.ts,
// werkstattVeroeffentlichen.ts). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BEREICHE,
  STUFE_ART,
  alterText,
  anzahlText,
  bereichHash,
  bereichTitel,
  dauerText,
  msText,
  parseBereich,
  stufeArt,
  zeitpunktText,
  zustand,
} from "./werkstattAnsicht.ts";
import { FLAECHE, achsenMax, balken, linie, ticks, xMitte, yFuer, zeigeEtikett } from "./werkstattDiagramm.ts";
import {
  AAL2_MAX_ALTER_S,
  KARTE_GILT_S,
  codeFrischGenug,
  codeSauber,
  ergebnisText,
  kartenEndeMs,
  restSekunden,
  restText,
  schrittStaende,
  wirkungText,
  type Ablauf,
} from "./werkstattVeroeffentlichen.ts";

const GEDANKENSTRICH = /[—]|\s-\s/;

test("Bereiche: Hash, Titel, Vorgabe Dashboards", () => {
  assert.deepEqual(BEREICHE.map((b) => b.id), ["dashboard", "labor", "karten", "protokolle"]);
  assert.equal(parseBereich("#labor"), "labor");
  assert.equal(parseBereich("karten"), "karten");
  assert.equal(parseBereich("#PROTOKOLLE"), "protokolle");
  assert.equal(parseBereich("#unbekannt"), "dashboard");
  assert.equal(parseBereich(""), "dashboard");
  assert.equal(bereichHash("labor"), "#labor");
  assert.equal(bereichTitel("karten"), "Karten und Use Cases");
  for (const b of BEREICHE) assert.doesNotMatch(b.titel, GEDANKENSTRICH);
});

test("Texte: Alter, Dauer, Millisekunden, Zeitpunkt, Anzahl", () => {
  assert.equal(alterText(1), "vor 1 Sekunde");
  assert.equal(alterText(40), "vor 40 Sekunden");
  assert.equal(alterText(60), "vor 1 Minute");
  assert.equal(alterText(720), "vor 12 Minuten");
  assert.equal(alterText(7300), "vor 2 Stunden");
  assert.equal(alterText(null), "unbekannt");
  assert.equal(alterText(-1), "unbekannt");
  assert.equal(dauerText(45), "45 s");
  assert.equal(dauerText(90), "1 min 30 s");
  assert.equal(dauerText(120), "2 min");
  assert.equal(dauerText(null), "keine Angabe");
  assert.equal(msText(1702.4), "1702 ms");
  assert.equal(msText(null), "keine Angabe");
  assert.equal(anzahlText(1, "Karte", "Karten"), "1 Karte");
  assert.equal(anzahlText(0, "Karte", "Karten"), "0 Karten");
  assert.match(zeitpunktText("2026-11-20T12:47:00"), /^20\.11\. 12:47$/);
  assert.equal(zeitpunktText("kaputt"), "kaputt");
});

test("Zustandswörter: bekannte Wörter mit Art, unbekannte neutral", () => {
  assert.deepEqual(zustand("ok"), { text: "in Ordnung", art: "ok" });
  assert.deepEqual(zustand("GESTOERT"), { text: "gestört", art: "fehler" });
  assert.deepEqual(zustand("zu"), { text: "zu", art: "warn" });
  assert.deepEqual(zustand("merkwürdig"), { text: "merkwürdig", art: "neutral" });
  assert.deepEqual(zustand(null), { text: "unbekannt", art: "neutral" });
  assert.deepEqual(zustand("constructor"), { text: "constructor", art: "neutral" });
  assert.equal(stufeArt("warnung"), "warn");
  assert.equal(stufeArt("constructor"), "neutral");
  assert.equal(stufeArt("kritisch"), "neutral");
  assert.deepEqual(STUFE_ART, { info: "ok", warnung: "warn", fehler: "fehler" });
});

test("Achsen: runde Obergrenzen, die den Wert fassen", () => {
  for (const [wert, erwartet] of [[31, 40], [35, 40], [40, 40], [41, 80], [3500, 4000], [4120, 8000], [0.9, 1], [7, 8], [100, 100]] as const) {
    const m = achsenMax(wert);
    assert.ok(m >= wert, `${wert}`);
    assert.equal(m, erwartet, `${wert}`);
  }
  assert.equal(achsenMax(0), 4);
  assert.equal(achsenMax(Number.NaN), 4);
});

test("Geometrie: Ticks, Balken und Linien liegen in der Fläche", () => {
  const t = ticks(40);
  assert.deepEqual(t.map((x) => x.wert), [0, 10, 20, 30, 40]);
  assert.equal(t[0].y, FLAECHE.hoehe - FLAECHE.unten);
  assert.equal(t[4].y, FLAECHE.oben);
  assert.equal(yFuer(80, 40), FLAECHE.oben); // über dem Maximum bleibt es oben
  assert.equal(yFuer(-5, 40), FLAECHE.hoehe - FLAECHE.unten);
  const b = balken([{ etikett: "a", wert: 10 }, { etikett: "b", wert: 40 }], 40);
  assert.equal(b.length, 2);
  assert.ok(b[1].hoehe > b[0].hoehe);
  assert.ok(b[1].letzter && !b[0].letzter);
  assert.ok(b.every((x) => x.x >= FLAECHE.links && x.x + x.breite <= FLAECHE.breite - FLAECHE.rechts));
  assert.deepEqual(balken([], 40), []);
  const l = linie([100, null, 200], 400);
  assert.equal(l.einzeln.length, 2);
  assert.equal(l.letzter?.wert, 200);
  assert.match(l.punkte, /^[\d.]+,[\d.]+ [\d.]+,[\d.]+$/);
  assert.equal(linie([], 10).letzter, null);
  assert.equal(linie([null], 10).punkte, "");
  assert.ok(Math.abs(xMitte(0, 2) - (FLAECHE.links + (FLAECHE.breite - FLAECHE.links - FLAECHE.rechts) / 4)) < 1e-9);
});

test("Beschriftung der Achse: bis sieben alle, danach jede zweite und die letzte", () => {
  assert.ok([0, 1, 2, 3, 4, 5, 6].every((i) => zeigeEtikett(i, 7)));
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7].map((i) => zeigeEtikett(i, 8)), [true, false, true, false, true, false, true, true]);
});

test("Vierschritt: Stand der Schritte je Zustand", () => {
  const pruefung = { ok: true, probleme: [], zeichen: 4200 };
  const karte = { id: "k", giltBis: "2026-11-20T10:05:00Z", aenderungen: 1, karten: ["W1"] };
  const faelle: [Ablauf, string[]][] = [
    [{ art: "bereit" }, ["aktiv", "offen", "offen", "offen"]],
    [{ art: "prueft" }, ["aktiv", "offen", "offen", "offen"]],
    [{ art: "abgelehnt", pruefung }, ["aktiv", "offen", "offen", "offen"]],
    [{ art: "geprueft", pruefung }, ["fertig", "aktiv", "offen", "offen"]],
    [{ art: "karte_laeuft", pruefung }, ["fertig", "aktiv", "offen", "offen"]],
    [{ art: "karte", pruefung, karte, endeMs: 1 }, ["fertig", "fertig", "aktiv", "offen"]],
    [{ art: "ausfuehren", pruefung, karte, endeMs: 1 }, ["fertig", "fertig", "aktiv", "offen"]],
    [{ art: "fertig", ergebnis: { version: 5, zeichen: 1 } }, ["fertig", "fertig", "fertig", "fertig"]],
  ];
  for (const [a, soll] of faelle) assert.deepEqual(schrittStaende(a), soll, a.art);
});

test("Karte: Ende nach dem Server, bei abweichender Uhr fünf Minuten ab dem Anlegen", () => {
  const jetzt = Date.parse("2026-11-20T10:00:00Z");
  assert.equal(KARTE_GILT_S, 300);
  assert.equal(kartenEndeMs("2026-11-20T10:05:00Z", jetzt), Date.parse("2026-11-20T10:05:00Z"));
  assert.equal(kartenEndeMs("2026-11-20T10:04:30Z", jetzt), Date.parse("2026-11-20T10:04:30Z"));
  assert.equal(kartenEndeMs("2026-11-20T13:05:00Z", jetzt), jetzt + 300_000); // Uhr geht drei Stunden anders
  assert.equal(kartenEndeMs("kaputt", jetzt), jetzt + 300_000);
  assert.equal(restSekunden(jetzt + 300_000, jetzt), 300);
  assert.equal(restSekunden(jetzt + 299_100, jetzt), 300);
  assert.equal(restSekunden(jetzt - 5, jetzt), 0);
  assert.equal(restText(272), "4:32");
  assert.equal(restText(5), "0:05");
  assert.equal(restText(0), "0:00");
});

test("Code: sechs Ziffern, Leerzeichen erlaubt; Frische mit Luft zur Grenze von 60 Sekunden", () => {
  assert.equal(codeSauber("123456"), "123456");
  assert.equal(codeSauber(" 123 456 "), "123456");
  for (const s of ["12345", "1234567", "12345a", "", "12-456"]) assert.equal(codeSauber(s), null, s);
  assert.equal(AAL2_MAX_ALTER_S, 60);
  assert.ok(codeFrischGenug(0));
  assert.ok(codeFrischGenug(55));
  assert.ok(!codeFrischGenug(56));
  assert.ok(!codeFrischGenug(null));
});

test("Wirkung und Ergebnis der Karte als Sätze ohne Gedankenstrich", () => {
  assert.equal(wirkungText(4, ["W1", "A2"]), "Katalog Version 5 mit 2 Änderungen: W1, A2.");
  assert.equal(wirkungText(null, ["K1"]), "Katalog Version 1 mit 1 Änderung: K1.");
  assert.equal(wirkungText(2, [], 3), "Katalog Version 3 mit 3 Änderungen.");
  const e = ergebnisText({ version: 5, zeichen: 4300 });
  assert.match(e, /Version 5/);
  assert.doesNotMatch(e, GEDANKENSTRICH);
});
