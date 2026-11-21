// Tests für die Prüfung der Antworten der Werkstatt (lib/werkstattParser.ts). Die Beispielantworten stammen aus dem Code des
// API-Pakets (lib/werkstattTestdaten.ts), nicht aus der Erinnerung. Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SICHERE_ID,
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
  alsPunkt,
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
import { API, ID_FREIGABE, ID_TERMIN } from "./werkstattTestdaten.ts";

test("kurz säubert Text und kürzt", () => {
  assert.equal(kurz(" a\u0000\nb "), "a b");
  assert.equal(kurz("x".repeat(500), 10)?.length, 10);
  assert.equal(kurz(""), null);
  assert.equal(kurz(4), null);
});

test("Listen: die Antwort selbst oder das Feld mit dem genannten Namen", () => {
  assert.deepEqual(listeAus([1], ["a"]), [1]);
  assert.deepEqual(listeAus({ a: [2] }, ["b", "a"]), [2]);
  assert.equal(listeAus({ a: 1 }, ["a"]), null);
  assert.equal(listeAus(null, ["a"]), null);
});

test("Kennungen des Dienstes sind UUIDs in Kleinbuchstaben", () => {
  assert.match(ID_TERMIN, SICHERE_ID);
  assert.match(ID_FREIGABE, SICHERE_ID);
  for (const schlecht of ["t1", "../x", "6F1C2A3E-8B4D-4F6A-9C1E-2D3B4A5C6D7E", "", `${ID_TERMIN}/x`]) assert.doesNotMatch(schlecht, SICHERE_ID);
});

test("GET /ich", () => {
  assert.deepEqual(alsIch(API.ich), { rolle: "admin", aal2AlterS: 42, erlaubt: true });
  assert.deepEqual(alsIch({ rolle: "komisch", aal2_alter_s: -4, erlaubt: false }), { rolle: null, aal2AlterS: null, erlaubt: false });
  assert.deepEqual(alsIch({ rolle: "admin", aal2_alter_s: null, erlaubt: true })?.aal2AlterS, null);
  assert.equal(alsIch({ rolle: "admin" }), null);
  assert.equal(alsIch("x"), null);
});

test("GET /betrieb: kern ist eine Liste je Slot, fehlende Teile sind null, Fremdes fällt weg", () => {
  const b = alsBetrieb(API.betrieb);
  assert.deepEqual(b?.kern, [
    { slot: "a", release: "v0.7.1-abc", aktiv: true },
    { slot: "b", release: "v0.7.0-def", aktiv: false },
  ]);
  assert.equal(b?.alterS, 30);
  assert.equal(b?.oberflaeche.version, "0.7.1");
  assert.equal(b?.installer.version, "0.7.1");
  assert.equal(b?.kanal.zustand, "zu");
  assert.equal(b?.laborDienst.zustand, "ok");
  // der Sammler kann auch nur einen Eintrag melden, oder gar keinen Teil
  assert.equal(alsBetrieb({ ...API.betrieb, kern: { slot: "a", release: "v1", aktiv: true } })?.kern.length, 1);
  const leer = alsBetrieb({ zeit: "2026-11-21T10:00:00+00:00", alter_s: 1, kern: null, oberflaeche: null, installer: null, kanal: null, labor_dienst: null });
  assert.deepEqual(leer?.kern, []);
  assert.equal(leer?.laborDienst.zustand, null);
  assert.equal(alsBetrieb({ ...API.betrieb, kern: [1, "x", { slot: "a", geheim: 1 }] })?.kern.length, 1);
  assert.ok(!JSON.stringify(alsBetrieb({ ...API.betrieb, extra: "geheim" })).includes("geheim"));
  assert.equal(alsBetrieb([]), null);
});

test("GET /dashboard/sitzungen, latenz und aktionen: { tage, zeilen }", () => {
  assert.deepEqual(alsSitzungen(API.sitzungen), [
    { tag: "2026-11-19", anzahl: 12, dauerP50S: 95.5, dauerP95S: 310, offen: 0 },
    { tag: "2026-11-20", anzahl: 31, dauerP50S: 120, dauerP95S: 400.2, offen: 0 },
  ]);
  assert.equal(alsSitzungen({ tage: 14, zeilen: [] })?.length, 0);
  assert.equal(alsSitzungen({ tage: 14, zeilen: [{ tag: "kaputt", anzahl: 1 }] }), null);
  assert.equal(alsSitzungen({ tage: 14, zeilen: [{ tag: "2026-11-21xyz", anzahl: 1 }] }), null);
  assert.equal(alsSitzungen({ tage: 14, zeilen: [{ tag: "2026-11-21 10:00:00+00", anzahl: 1 }] })?.[0].tag, "2026-11-21");
  assert.deepEqual(alsLatenz(API.latenz), [
    { tag: "2026-11-19", zuege: 100, p50Ms: 1700.5, p95Ms: 3100 },
    { tag: "2026-11-20", zuege: 140, p50Ms: 1750, p95Ms: null },
  ]);
  assert.deepEqual(alsLatenz({ tage: 14, zeilen: [{ zuege: 9, p50_ms: 1, p95_ms: 2 }] }), [{ tag: null, zuege: 9, p50Ms: 1, p95Ms: 2 }]);
  assert.equal(alsLatenz({ tage: 14, zeilen: [{ p50_ms: 1 }] }), null);
  assert.deepEqual(alsAktionen(API.aktionen), [
    { tool: "werkstatt_termin_anlegen", status: "done", anzahl: 3 },
    { tool: "werkstatt_karten_veroeffentlichen", status: "failed", anzahl: 1 },
  ]);
  assert.equal(alsAktionen({ tage: 14, zeilen: [{ tool: "x", status: "done" }] }), null);
});

test("GET /protokolle: Zeilen mit Zahlen als Text, Marken und Stufen vom Dienst", () => {
  const p = alsProtokolle(API.protokolle);
  assert.deepEqual(p?.marken, ["wamo-core", "wamo-ui"]);
  assert.equal(p?.zeilen.length, 2);
  assert.deepEqual(p?.zeilen[0], { zeit: "2026-11-21T09:00:00+00:00", marke: "wamo-core", stufe: "info", code: "labor_stufe_ende", zahlen: "sitzungen 1, platz 3" });
  assert.equal(p?.zeilen[1].zahlen, "");
  assert.equal(alsProtokolle({ ...API.protokolle, zeilen: [{ zeit: "x", marke: "m", stufe: "info" }] }), null);
  assert.equal(zahlenText(5), "5");
  assert.equal(zahlenText([1, "a", 2]), "1, 2");
  assert.equal(zahlenText(null), "");
  assert.equal(zahlenText({ a: "<script>" }), "");
  assert.equal(zahlenText({ "Böse Name": 2, platz: "3" }), "platz 3");
});

test("GET /labor/stand: profile mit freiwilliger Kennung, der nächste Termin gehört dem Dienst", () => {
  assert.deepEqual(alsLaborStand(API.laborStand), [
    { kennung: "labor-01", art: "platz", platz: 1, aktiv: false, zeilen: 12 },
    { kennung: null, art: "schaufenster", platz: null, aktiv: true, zeilen: null },
  ]);
  assert.equal(alsLaborStand({ profile: [{ art: "platz", platz: 1 }], naechster_termin: null }), null);
  assert.equal(alsLaborStand({ profile: [{ art: "platz", platz: 99, aktiv: true }] })?.[0].platz, null);
});

test("Termine: { termine } und { termin } mit berechnetem Löschlauf", () => {
  assert.deepEqual(alsTermin(API.termin), {
    id: ID_TERMIN, tag: "2026-12-05", beginn: "09:00", ende: "17:00", einwilligungVersion: 1, status: "entwurf", aufbewahrungBis: "2026-12-18",
  });
  assert.equal(alsTermine(API.termine)?.length, 1);
  assert.equal(alsTermin(API.terminAntwort.termin)?.id, ID_TERMIN);
  assert.equal(alsTermin({ ...API.termin, status: "offen" }), null);
  assert.equal(alsTermin({ ...API.termin, tag: "2026-02-31" }), null);
  assert.equal(alsTermin({ ...API.termin, id: "../x" }), null); // die Kennung kommt in einen Pfad
  assert.equal(alsTermin({ ...API.termin, beginn: null })?.beginn, null);
  assert.equal(alsTermin({ ...API.termin, beginn: "09:00:00" })?.beginn, "09:00");
});

test("Plätze und Checkliste: { plaetze } und { punkte }", () => {
  assert.deepEqual(alsPlaetze(API.plaetze)?.map((p) => [p.platz, p.zweck, p.kennung, p.gast]), [
    [1, "besucher", "labor-01", "Gast 1"],
    [2, "reserve", null, null],
    [15, "abnahme", "labor-15", null],
  ]);
  assert.equal(alsPlaetze({ plaetze: [{ platz: 17, zweck: "besucher" }] }), null);
  assert.equal(alsPlaetze({ plaetze: [{ platz: 1, zweck: "gast" }] }), null);
  assert.equal(alsPlaetze({ plaetze: [{ platz: 1e21, zweck: "besucher" }] }), null);
  const c = alsCheckliste(API.checkliste);
  assert.deepEqual(c?.map((p) => [p.nr, p.erledigt, p.faellig, p.quelle]), [[1, false, "2026-12-01", "Runbook 9"], [2, true, null, null]]);
  assert.equal(alsPunkt(API.punktAntwort.punkt)?.nr, 3);
  assert.equal(alsCheckliste({ punkte: [{ nr: 1 }] }), null);
});

test("Karten: { karten, gruppen, aktive_version, zeichen, grenze } und { karte }", () => {
  const l = alsKartenListe(API.karten);
  assert.equal(l?.karten.length, 1);
  assert.equal(l?.version, 4);
  assert.deepEqual(l?.gruppen, { W: "Wissen", A: "Anforderungen", J: "Jira", M: "Mail", S: "Sicherheit", G: "Gespräch", E: "Eigene Gruppe" });
  assert.equal(alsKartenListe({ ...API.karten, aktive_version: null })?.version, null);
  assert.deepEqual(alsKartenListe({ ...API.karten, gruppen: { w: "klein", WW: "zwei", Z: "" } })?.gruppen, {});
  const k = alsKarte(API.karteAntwort.karte);
  assert.deepEqual(k?.werkzeuge, ["Jira"]);
  assert.equal(k?.dauerMin, 3);
  assert.equal(k?.stand, "entwurf");
  assert.equal(alsKarte({ ...API.karteAntwort.karte, id: "w1" }), null);
  assert.equal(alsKarte({ ...API.karteAntwort.karte, wissen: "anderes" }), null);
  assert.equal(alsKarte({ ...API.karteAntwort.karte, stand: "x" }), null);
  assert.equal(alsKarte({ ...API.karteAntwort.karte, titel: "" }), null);
  assert.deepEqual(alsKarte({ ...API.karteAntwort.karte, werkzeuge: ["Jira", "Unbekannt"] })?.werkzeuge, ["Jira"]);
  assert.equal(alsKartenListe({ ...API.karten, karten: [{ ...API.karteAntwort.karte, id: "x" }] }), null);
});

test("Zuordnung: { termin, zuordnung: { \"1\": [...] } }", () => {
  assert.deepEqual(alsZuordnung(API.zuordnung), { 1: ["A1", "W1"], 2: ["W1"] });
  assert.deepEqual(alsZuordnung({ termin: ID_TERMIN, zuordnung: {} }), {});
  assert.equal(alsZuordnung({ zuordnung: { "20": ["W1"] } }), null); // Plätze gibt es von 1 bis 16
  assert.equal(alsZuordnung({ zuordnung: { x: ["W1"] } }), null);
  assert.equal(alsZuordnung({ zuordnung: { "1": ["kaputt"] } }), null);
  assert.equal(alsZuordnung("x"), null);
});

test("Versionen, Prüfung, Freigabekarte und Ergebnis", () => {
  assert.deepEqual(alsVersionen(API.versionen), [{ version: 4, erstelltAt: "2026-11-20T12:00:00+00:00", anzahlAenderungen: 2, wissenZeichen: 100, aktiv: true }]);
  assert.equal(alsVersionen({ versionen: [{ version: 1 }] }), null);
  assert.deepEqual(alsPruefung(API.pruefen), { ok: true, probleme: [], zeichen: 1200 });
  assert.deepEqual(alsPruefung({ ok: false, probleme: ["Karte W1: Titel fehlt.", 3], zeichen: 2100, grenze: 2000, entwuerfe: [] }), {
    ok: false, probleme: ["Karte W1: Titel fehlt."], zeichen: 2100,
  });
  assert.equal(alsPruefung({ ok: true, zeichen: 1 }), null);
  // die Karte steckt in { karte: {...} }
  assert.deepEqual(alsFreigabeKarte(API.freigabeKarte), { id: ID_FREIGABE, giltBis: "2026-11-21T10:04:55+00:00", aenderungen: 1, karten: ["W1"], basisVersion: 4 });
  assert.equal(alsFreigabeKarte({ karte: { ...API.freigabeKarte.karte, basis_version: null } })?.basisVersion, null);
  assert.equal(alsFreigabeKarte({ karte: { ...API.freigabeKarte.karte, gilt_bis: "nie" } }), null);
  assert.equal(alsFreigabeKarte({ karte: { ...API.freigabeKarte.karte, id: "../k1" } }), null); // die Kennung kommt in einen Pfad
  assert.equal(alsFreigabeKarte({ karte: { gilt_bis: "2026-11-21T10:04:55+00:00" } }), null);
  assert.deepEqual(alsVeroeffentlicht(API.ausgefuehrt), { version: 5, zeichen: 1200 });
  assert.equal(alsVeroeffentlicht({ version: 0, zeichen: 1 }), null);
});
