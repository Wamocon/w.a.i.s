// Tests für die Prüfung der Antworten der Werkstatt (lib/werkstattParser.ts): gültige Formen, tolerante Listen, strenge Zeilen.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  alsAktionen,
  alsBetrieb,
  alsCheckliste,
  alsFreigabeKarte,
  alsIch,
  alsKarte,
  alsKartenListe,
  alsLaborStand,
  alsLatenz,
  alsPlaetze,
  alsProtokolle,
  alsPruefung,
  alsSitzungen,
  alsTermin,
  alsTermine,
  alsVeroeffentlicht,
  alsVersionen,
  alsZuordnung,
  kurz,
  listeAus,
  zahlenText,
} from "./werkstattParser.ts";

const KARTE = {
  id: "W1",
  gruppe: "Wissen",
  titel: "Titel",
  aufgabe: "Aufgabe",
  erwartung: "Erwartung",
  fehler: null,
  lernziel: null,
  wissen: "keine",
  wissenstext: null,
  werkzeuge: ["Jira", "Unbekannt"],
  dauer_min: 3,
  stand: "entwurf",
};
const TERMIN = { id: "t-1", tag: "2026-12-05", beginn: "09:00:00", ende: "17:00", einwilligung_version: 1, status: "entwurf", aufbewahrung_bis: "2026-12-18" };

test("kurz säubert Text und kürzt", () => {
  assert.equal(kurz(" a\u0000\nb "), "a b");
  assert.equal(kurz("x".repeat(500), 10)?.length, 10);
  assert.equal(kurz(""), null);
  assert.equal(kurz(4), null);
});

test("Listen: die Antwort selbst oder ein Feld mit bekanntem Namen", () => {
  assert.deepEqual(listeAus([1], ["a"]), [1]);
  assert.deepEqual(listeAus({ a: [2] }, ["b", "a"]), [2]);
  assert.equal(listeAus({ a: 1 }, ["a"]), null);
  assert.equal(listeAus(null, ["a"]), null);
});

test("Ich: Erlaubnis ist Pflicht, Rolle und Alter sind optional", () => {
  assert.deepEqual(alsIch({ rolle: "admin", aal2_alter_s: 12, erlaubt: true }), { rolle: "admin", aal2AlterS: 12, erlaubt: true });
  assert.deepEqual(alsIch({ rolle: "komisch", aal2_alter_s: -4, erlaubt: false }), { rolle: null, aal2AlterS: null, erlaubt: false });
  assert.equal(alsIch({ rolle: "admin" }), null);
  assert.equal(alsIch("x"), null);
});

test("Betrieb: fehlende Teile werden zu null, Fremdes fällt weg", () => {
  const b = alsBetrieb({ zeit: "2026-11-20T10:00:00Z", alter_s: 30, kern: { slot: "a", release: "v1", aktiv: true, geheim: 1 }, installer: { version: "0.7.1" } });
  assert.equal(b?.kern.slot, "a");
  assert.equal(b?.kern.aktiv, true);
  assert.equal(b?.installer.version, "0.7.1");
  assert.equal(b?.oberflaeche.farbe, null);
  assert.equal(b?.laborDienst.zustand, null);
  assert.ok(!JSON.stringify(b).includes("geheim"));
  assert.equal(alsBetrieb([]), null);
});

test("Sitzungen, Latenz und Aktionen: Listen mit strengen Zeilen", () => {
  const s = alsSitzungen({ tage: [{ tag: "2026-11-07", anzahl: 12, dauer_p50_s: 90, dauer_p95_s: 300, offen: 1 }] });
  assert.deepEqual(s, [{ tag: "2026-11-07", anzahl: 12, dauerP50S: 90, dauerP95S: 300, offen: 1 }]);
  assert.equal(alsSitzungen([{ tag: "kaputt", anzahl: 1 }]), null);
  assert.deepEqual(alsLatenz([{ tag: "2026-11-07T00:00:00Z", zuege: 5, p50_ms: 1700, p95_ms: 3100 }]), [{ tag: "2026-11-07", zuege: 5, p50Ms: 1700, p95Ms: 3100 }]);
  assert.deepEqual(alsLatenz({ zuege: 9, p50_ms: 1, p95_ms: 2 }), [{ tag: null, zuege: 9, p50Ms: 1, p95Ms: 2 }]);
  assert.equal(alsLatenz([{ p50_ms: 1 }]), null);
  assert.deepEqual(alsAktionen({ aktionen: [{ tool: "werkstatt_x", status: "ok", anzahl: 4 }] }), [{ tool: "werkstatt_x", status: "ok", anzahl: 4 }]);
  assert.equal(alsAktionen([{ tool: "x", status: "ok" }]), null);
});

test("Protokolle: Zeilen mit Zahlen als Text, Stufe klein, Marken aus dem Dienst", () => {
  const p = alsProtokolle({
    marken: ["wamo-core", 7],
    zeilen: [{ zeit: "2026-11-20T14:47:00Z", marke: "wamo-core", stufe: "INFO", code: "labor_stufe_ende", zahlen: { sitzungen: 1, "Böse Name": 2, platz: "3" } }],
  });
  assert.deepEqual(p?.marken, ["wamo-core"]);
  assert.equal(p?.zeilen[0].stufe, "info");
  assert.equal(p?.zeilen[0].zahlen, "sitzungen 1, platz 3");
  assert.equal(alsProtokolle([{ zeit: "x", marke: "m", stufe: "info" }]), null);
  assert.equal(zahlenText(5), "5");
  assert.equal(zahlenText([1, "a", 2]), "1, 2");
  assert.equal(zahlenText(null), "");
  assert.equal(zahlenText({ a: "<script>" }), "");
});

test("Laborstand: aktiv oder freigeschaltet, Platz nur 1 bis 16", () => {
  assert.deepEqual(alsLaborStand({ profile: [{ art: "platz", platz: 3, aktiv: false, zeilen: 12 }, { art: "schaufenster", freigeschaltet: true, platz: 99 }] }), [
    { kennung: null, art: "platz", platz: 3, aktiv: false, zeilen: 12 },
    { kennung: null, art: "schaufenster", platz: null, aktiv: true, zeilen: null },
  ]);
  assert.equal(alsLaborStand([{ art: "platz" }]), null);
});

test("Termin und Plätze und Checkliste", () => {
  assert.deepEqual(alsTermin(TERMIN), { id: "t-1", tag: "2026-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18" });
  assert.equal(alsTermin({ ...TERMIN, status: "offen" }), null);
  assert.equal(alsTermin({ ...TERMIN, tag: "2026-02-31" }), null);
  assert.equal(alsTermin({ ...TERMIN, id: "../x" }), null); // die Kennung kommt in einen Pfad
  assert.equal(alsTermine({ termine: [TERMIN, { ...TERMIN, id: "" }] }), null);
  assert.equal(alsTermine({ termine: [TERMIN] })?.length, 1);
  assert.deepEqual(alsPlaetze({ plaetze: [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }] }), [{ platz: 1, zweck: "besucher", kennung: "labor-01", gast: "Gast 1" }]);
  assert.equal(alsPlaetze([{ platz: 17, zweck: "besucher" }]), null);
  assert.equal(alsPlaetze([{ platz: 1, zweck: "gast" }]), null);
  const c = alsCheckliste({ eintraege: [{ id: 4, titel: "A", quelle: null, faellig: "2026-12-01", erledigt_at: "2026-11-20T10:00:00Z" }, { nr: 5, titel: "B", erledigt: false }] });
  assert.deepEqual(c?.map((p) => [p.nr, p.erledigt, p.faellig]), [[4, true, "2026-12-01"], [5, false, null]]);
  assert.equal(alsCheckliste([{ nr: 1 }]), null);
});

test("Karte: Pflichtfelder streng, unbekannte Werkzeuge fallen weg", () => {
  const k = alsKarte(KARTE);
  assert.deepEqual(k?.werkzeuge, ["Jira"]);
  assert.equal(k?.dauerMin, 3);
  assert.equal(alsKarte({ ...KARTE, id: "w1" }), null);
  assert.equal(alsKarte({ ...KARTE, wissen: "anderes" }), null);
  assert.equal(alsKarte({ ...KARTE, stand: "x" }), null);
  assert.equal(alsKarte({ ...KARTE, titel: "" }), null);
  const l = alsKartenListe({ karten: [KARTE], version: 4 });
  assert.deepEqual([l?.karten.length, l?.version], [1, 4]);
  assert.equal(alsKartenListe([KARTE])?.version, null);
  assert.equal(alsKartenListe({ karten: [{ ...KARTE, id: "x" }] }), null);
});

test("Zuordnung: Liste von Paaren oder Zuordnung je Platz", () => {
  assert.deepEqual(alsZuordnung({ zuordnung: [{ platz: 1, karte_id: "W1" }, { platz: 1, karte_id: "A1" }, { platz: 2, karte_id: "W1" }] }), { 1: ["A1", "W1"], 2: ["W1"] });
  assert.deepEqual(alsZuordnung({ zuordnung: { 1: ["W1"], 2: [] } }), { 1: ["W1"], 2: [] });
  assert.deepEqual(alsZuordnung([]), {});
  assert.equal(alsZuordnung([{ platz: 20, karte_id: "W1" }]), null);
  assert.equal(alsZuordnung([{ platz: 1, karte_id: "kaputt" }]), null);
  assert.equal(alsZuordnung({ zuordnung: { x: ["W1"] } }), null);
  assert.equal(alsZuordnung("x"), null);
});

test("Versionen, Prüfung, Freigabekarte und Ergebnis", () => {
  assert.deepEqual(alsVersionen({ versionen: [{ version: 4, erstellt_at: "2026-11-20", anzahl_aenderungen: 2, wissen_zeichen: 100, aktiv: true }] }), [
    { version: 4, erstelltAt: "2026-11-20", anzahlAenderungen: 2, wissenZeichen: 100, aktiv: true },
  ]);
  assert.equal(alsVersionen([{ version: 1 }]), null);
  assert.deepEqual(alsPruefung({ ok: false, probleme: ["Zu lang", { text: "Fehlt" }, 3], zeichen: 6100 }), { ok: false, probleme: ["Zu lang", "Fehlt"], zeichen: 6100 });
  assert.equal(alsPruefung({ ok: true, zeichen: 1 }), null);
  const karte = alsFreigabeKarte({ id: "k1", gilt_bis: "2026-11-20T10:05:00Z", ziel: { anzahl: 2, karten: ["W1", "kaputt"] } });
  assert.deepEqual(karte, { id: "k1", giltBis: "2026-11-20T10:05:00Z", aenderungen: 2, karten: ["W1"] });
  assert.equal(alsFreigabeKarte({ id: "k1", gilt_bis: "nie" }), null);
  assert.equal(alsFreigabeKarte({ gilt_bis: "2026-11-20T10:05:00Z" }), null);
  assert.deepEqual(alsVeroeffentlicht({ version: 5, zeichen: 4300 }), { version: 5, zeichen: 4300 });
  assert.equal(alsVeroeffentlicht({ version: 0, zeichen: 1 }), null);
});
