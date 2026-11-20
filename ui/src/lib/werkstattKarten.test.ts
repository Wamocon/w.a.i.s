// Tests für den Karten-Editor der Werkstatt (lib/werkstattKarten.ts): Kennungen, Gruppen, Prüfung, Zeichenbudget, Zuordnung.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  GRENZEN,
  KARTEN_ID,
  WISSEN_BASIS_STANDARD,
  WISSEN_MAX_ZEICHEN,
  eingabeZuRumpf,
  entwuerfe,
  formularAusKarte,
  formularPruefen,
  freieBuchstaben,
  gruppenAus,
  hatSteuerzeichen,
  idVorschlag,
  leeresFormular,
  mitGruppe,
  mitNeuemBuchstaben,
  normalisieren,
  zeichenBudget,
  zeitJePlatz,
  zuordnungBereinigen,
  zuordnungGleich,
  zuordnungUmschalten,
  type Formular,
} from "./werkstattKarten.ts";
import type { Karte } from "./werkstattTypen.ts";

function karte(id: string, teil: Partial<Karte> = {}): Karte {
  return {
    id,
    gruppe: `Gruppe ${id.charAt(0)}`,
    titel: `Titel ${id}`,
    aufgabe: "Aufgabe",
    erwartung: "Erwartung",
    fehler: null,
    lernziel: null,
    wissen: "keine",
    wissenstext: null,
    werkzeuge: [],
    dauerMin: 3,
    stand: "veroeffentlicht",
    ...teil,
  };
}
const KATALOG = [karte("A1"), karte("A2"), karte("B1"), karte("B7", { stand: "entwurf" })];

function gueltig(teil: Partial<Formular> = {}): Formular {
  return {
    ...leeresFormular(KATALOG, "A"),
    titel: "Ein Titel",
    aufgabe: "Eine Aufgabe",
    erwartung: "Ein Ergebnis",
    ...teil,
  };
}

test("normalisieren macht Text einzeilig und ohne doppelten Leerraum", () => {
  assert.equal(normalisieren("  a\r\nb\t\tc  d \u0000 e "), "a b c d e");
  assert.equal(normalisieren(""), "");
  assert.ok(hatSteuerzeichen("a\nb"));
  assert.ok(!hatSteuerzeichen("a b"));
});

test("Gruppen kommen aus dem Katalog: Buchstabe aus der Kennung, Name aus der Karte", () => {
  const g = gruppenAus([...KATALOG, karte("B2", { gruppe: "Zweiter Name" }), karte("B3", { gruppe: "Gruppe B" })]);
  assert.deepEqual(g.map((x) => [x.buchstabe, x.name, x.anzahl]), [["A", "Gruppe A", 2], ["B", "Gruppe B", 4]]);
  assert.deepEqual(gruppenAus([]), []);
  assert.equal(freieBuchstaben(g).length, 24);
  assert.ok(!freieBuchstaben(g).includes("A"));
  assert.equal(freieBuchstaben([]).length, 26);
});

test("neue Kennung: Buchstabe plus nächste Zahl, nie eine vergebene", () => {
  assert.equal(idVorschlag("A", KATALOG), "A3");
  assert.equal(idVorschlag("B", KATALOG), "B8");
  assert.equal(idVorschlag("C", KATALOG), "C1");
  assert.equal(idVorschlag("a", KATALOG), null);
  assert.equal(idVorschlag("AB", KATALOG), null);
  assert.equal(idVorschlag("A", [karte("A99")]), null);
  assert.equal(idVorschlag("A", [karte("A98")]), "A99");
  for (const b of ["A", "B", "C"]) assert.match(idVorschlag(b, KATALOG) ?? "", KARTEN_ID);
});

test("leeres Formular: ohne Katalog eine neue Gruppe, sonst die gezeigte Gruppe mit vorgeschlagener Kennung", () => {
  const leer = leeresFormular([]);
  assert.equal(leer.gruppeWahl, "neu");
  assert.equal(leer.id, "");
  const a = leeresFormular(KATALOG, "A");
  assert.equal(a.gruppeWahl, "A");
  assert.equal(a.id, "A3");
  assert.equal(leeresFormular(KATALOG, "Z").gruppeWahl, "");
  assert.equal(a.dauer, "4");
  assert.equal(a.wissen, "keine");
  assert.equal(a.bestehend, false);
});

test("Gruppenwechsel im neuen Formular holt die Kennung der Gruppe, im bestehenden ändert er nichts", () => {
  const f = mitGruppe(leeresFormular(KATALOG, "A"), "B", KATALOG);
  assert.equal(f.id, "B8");
  assert.equal(mitGruppe(f, "", KATALOG).id, "");
  const neu = mitGruppe({ ...f, neuerBuchstabe: "K" }, "neu", KATALOG);
  assert.equal(neu.id, "K1");
  assert.equal(mitNeuemBuchstaben(neu, "m").id, "M1");
  assert.equal(mitNeuemBuchstaben(neu, "1").id, "");
  const bestehend = formularAusKarte(KATALOG[0], KATALOG);
  assert.equal(mitGruppe(bestehend, "B", KATALOG), bestehend);
});

test("Kopie: neue Kennung in derselben Gruppe, Titel mit Zusatz und höchstens 60 Zeichen", () => {
  const k = karte("A1", { titel: "x".repeat(60), fehler: "falsch", wissen: "Eigener Text", wissenstext: "Text", werkzeuge: ["Jira"] });
  const f = formularAusKarte(k, KATALOG, true);
  assert.equal(f.id, "A3");
  assert.equal(f.bestehend, false);
  assert.equal(f.titel.length, GRENZEN.titel);
  assert.ok(f.fehlerfall);
  assert.equal(f.fehlertext, "falsch");
  assert.deepEqual(f.werkzeuge, ["Jira"]);
  const kurz = formularAusKarte(karte("A1"), KATALOG, true);
  assert.equal(kurz.titel, "Titel A1 (Kopie)");
  const original = formularAusKarte(k, KATALOG);
  assert.equal(original.id, "A1");
  assert.equal(original.bestehend, true);
});

test("ein gültiges Formular ergibt die Eingabe, Text einzeilig, Werkzeuge in fester Reihenfolge", () => {
  const f = gueltig({ titel: " Ein\nTitel ", werkzeuge: ["Websuche", "Jira"], lernziel: " CTFL 1.2 ", dauer: "7" });
  const r = formularPruefen(f, KATALOG, null);
  assert.deepEqual(r.probleme, []);
  assert.deepEqual(r.eingabe, {
    id: "A3",
    gruppe: "Gruppe A",
    titel: "Ein Titel",
    aufgabe: "Eine Aufgabe",
    erwartung: "Ein Ergebnis",
    fehler: null,
    lernziel: "CTFL 1.2",
    wissen: "keine",
    wissenstext: null,
    werkzeuge: ["Jira", "Websuche"],
    dauerMin: 7,
  });
});

test("Pflichtfelder und Längen", () => {
  const leer = formularPruefen(gueltig({ titel: "", aufgabe: "  ", erwartung: "" }), KATALOG, null);
  assert.equal(leer.eingabe, null);
  assert.deepEqual(leer.probleme.map((p) => [p.feld, p.text]), [
    ["titel", "Der Titel fehlt."],
    ["aufgabe", "Die Aufgabe fehlt."],
    ["erwartung", "Das erwartete Ergebnis fehlt."],
  ]);
  const lang = formularPruefen(
    gueltig({ titel: "x".repeat(61), aufgabe: "x".repeat(241), erwartung: "x".repeat(241), lernziel: "x".repeat(41) }),
    KATALOG,
    null,
  );
  assert.deepEqual(lang.probleme.map((p) => p.feld), ["titel", "aufgabe", "erwartung", "lernziel"]);
  assert.match(lang.probleme[0].text, /höchstens 60 Zeichen/);
  // genau an der Grenze ist erlaubt
  assert.deepEqual(formularPruefen(gueltig({ titel: "x".repeat(60), aufgabe: "x".repeat(240) }), KATALOG, null).probleme, []);
});

test("Dauer: ganze Zahl von 1 bis 20", () => {
  for (const dauer of ["0", "21", "", "abc", "4.5", "-1", "100"]) {
    assert.deepEqual(formularPruefen(gueltig({ dauer }), KATALOG, null).probleme.map((p) => p.feld), ["dauer"], dauer);
  }
  for (const dauer of ["1", "20", " 4 "]) assert.deepEqual(formularPruefen(gueltig({ dauer }), KATALOG, null).probleme, [], dauer);
});

test("Fehlerfall braucht eine Beschreibung, sonst bleibt das Feld leer", () => {
  assert.deepEqual(formularPruefen(gueltig({ fehlerfall: true, fehlertext: "" }), KATALOG, null).probleme.map((p) => p.feld), ["fehlertext"]);
  assert.deepEqual(formularPruefen(gueltig({ fehlerfall: true, fehlertext: "x".repeat(121) }), KATALOG, null).probleme.map((p) => p.feld), ["fehlertext"]);
  assert.equal(formularPruefen(gueltig({ fehlerfall: true, fehlertext: "falsches Datum" }), KATALOG, null).eingabe?.fehler, "falsches Datum");
  // ohne Haken zählt ein Rest im Textfeld nicht
  assert.equal(formularPruefen(gueltig({ fehlerfall: false, fehlertext: "Rest" }), KATALOG, null).eingabe?.fehler, null);
});

test("Wissenstext gilt nur bei Eigener Text und ist dann Pflicht", () => {
  assert.deepEqual(formularPruefen(gueltig({ wissen: "Eigener Text", wissenstext: "" }), KATALOG, null).probleme.map((p) => p.feld), ["wissenstext"]);
  assert.deepEqual(formularPruefen(gueltig({ wissen: "Eigener Text", wissenstext: "x".repeat(901) }), KATALOG, null).probleme.map((p) => p.feld), ["wissenstext"]);
  const ok = formularPruefen(gueltig({ wissen: "Eigener Text", wissenstext: "Ein Satz." }), KATALOG, null).eingabe;
  assert.equal(ok?.wissenstext, "Ein Satz.");
  // bei Glossar bleibt ein alter Text nicht hängen
  const glossar = formularPruefen(gueltig({ wissen: "Glossar", wissenstext: "alt" }), KATALOG, null).eingabe;
  assert.equal(glossar?.wissen, "Glossar");
  assert.equal(glossar?.wissenstext, null);
});

test("Zeichenbudget: Grundmenge plus alle Wissenstexte, die aktuelle Karte ersetzt ihren alten Stand", () => {
  assert.deepEqual(zeichenBudget([], null), { genutzt: WISSEN_BASIS_STANDARD, max: WISSEN_MAX_ZEICHEN, rest: 6000 - 4120, ueber: false });
  const mit = [karte("A1", { wissen: "Eigener Text", wissenstext: "x".repeat(100) }), karte("A2", { wissen: "Glossar", wissenstext: "ignoriert" })];
  assert.equal(zeichenBudget(mit, 4000).genutzt, 4100);
  assert.equal(zeichenBudget(mit, 4000, { id: "A1", wissen: "Eigener Text", wissenstext: "x".repeat(10) }).genutzt, 4010);
  assert.equal(zeichenBudget(mit, 4000, { id: "A1", wissen: "keine", wissenstext: null }).genutzt, 4000);
  assert.equal(zeichenBudget(mit, 4000, { id: "A9", wissen: "Eigener Text", wissenstext: "x".repeat(50) }).genutzt, 4150);
  assert.equal(zeichenBudget(mit, 4000, { id: "A9", wissen: "Glossar", wissenstext: "x".repeat(50) }).genutzt, 4100);
  const voll = zeichenBudget([karte("A1", { wissen: "Eigener Text", wissenstext: "x".repeat(2000) })], 4120);
  assert.ok(voll.ueber);
  assert.equal(voll.rest, -120);
});

test("ein überschrittenes Zeichenbudget verhindert die Eingabe", () => {
  const voll = [karte("A1", { wissen: "Eigener Text", wissenstext: "x".repeat(900) })];
  const r = formularPruefen(gueltig({ wissen: "Eigener Text", wissenstext: "y".repeat(900) }), voll, 5000);
  assert.equal(r.eingabe, null);
  assert.deepEqual(r.probleme.map((p) => p.feld), ["budget"]);
  assert.match(r.probleme[0].text, /6800 von 6000/);
});

test("Gruppe: Wahl nötig, neue Gruppe braucht freien Buchstaben und Namen", () => {
  const ohne = formularPruefen({ ...gueltig(), gruppeWahl: "", id: "A3" }, KATALOG, null);
  assert.deepEqual(ohne.probleme.map((p) => p.feld), ["gruppe"]);
  const neu = formularPruefen({ ...gueltig(), gruppeWahl: "neu", neuerBuchstabe: "", neuerName: "", id: "" }, KATALOG, null);
  assert.deepEqual(neu.probleme.map((p) => p.feld), ["neuerBuchstabe", "neuerName", "id"]);
  const belegt = formularPruefen({ ...gueltig(), gruppeWahl: "neu", neuerBuchstabe: "A", neuerName: "Neu", id: "A1" }, KATALOG, null);
  assert.ok(belegt.probleme.some((p) => p.feld === "neuerBuchstabe" && /schon einer Gruppe/.test(p.text)));
  const ok = formularPruefen({ ...gueltig(), gruppeWahl: "neu", neuerBuchstabe: "K", neuerName: " Eigene  Gruppe ", id: "K1" }, KATALOG, null);
  assert.deepEqual(ok.probleme, []);
  assert.equal(ok.eingabe?.gruppe, "Eigene Gruppe");
  assert.equal(ok.eingabe?.id, "K1");
  const langerName = formularPruefen({ ...gueltig(), gruppeWahl: "neu", neuerBuchstabe: "K", neuerName: "x".repeat(31), id: "K1" }, KATALOG, null);
  assert.deepEqual(langerName.probleme.map((p) => p.feld), ["neuerName"]);
});

test("Kennung: gültiges Format, bei einer neuen Karte nie eine vergebene", () => {
  assert.deepEqual(formularPruefen(gueltig({ id: "A1" }), KATALOG, null).probleme.map((p) => p.text), ["Diese Kennung gibt es schon."]);
  assert.deepEqual(formularPruefen(gueltig({ id: "a3" }), KATALOG, null).probleme.map((p) => p.feld), ["id"]);
  assert.deepEqual(formularPruefen(gueltig({ id: "A100" }), KATALOG, null).probleme.map((p) => p.feld), ["id"]);
  // eine bestehende Karte darf ihre Kennung behalten, die Gruppe kommt aus der Kennung
  const bestehend = formularPruefen(formularAusKarte(KATALOG[1], KATALOG), KATALOG, null);
  assert.deepEqual(bestehend.probleme, []);
  assert.equal(bestehend.eingabe?.gruppe, "Gruppe A");
});

test("Rumpf der Schnittstelle: Namen wie in der Tabelle, immer als Entwurf", () => {
  const e = formularPruefen(gueltig(), KATALOG, null).eingabe;
  assert.ok(e);
  const rumpf = eingabeZuRumpf(e);
  assert.equal(rumpf.dauer_min, 3 + 1);
  assert.equal(rumpf.stand, "entwurf");
  assert.deepEqual(Object.keys(rumpf).sort(), ["aufgabe", "dauer_min", "erwartung", "fehler", "gruppe", "id", "lernziel", "stand", "titel", "werkzeuge", "wissen", "wissenstext"]);
});

test("Entwürfe sind alle Karten im Stand entwurf", () => {
  assert.deepEqual(entwuerfe(KATALOG).map((k) => k.id), ["B7"]);
});

test("Zuordnung: Zeit je Platz, Kreuz setzen und löschen ohne Veränderung der Eingabe", () => {
  const z = { 1: ["A1", "B1"], 2: ["A2"], 3: [] as string[] };
  assert.deepEqual(zeitJePlatz(z, KATALOG), { 1: 6, 2: 3, 3: 0 });
  assert.deepEqual(zeitJePlatz({ 1: ["Z9"] }, KATALOG), { 1: 0 });
  const an = zuordnungUmschalten(z, 2, "A1", true);
  assert.deepEqual(an[2], ["A1", "A2"]);
  assert.deepEqual(z[2], ["A2"]);
  assert.deepEqual(zuordnungUmschalten(an, 2, "A1", true)[2], ["A1", "A2"]);
  assert.deepEqual(zuordnungUmschalten(an, 2, "A1", false)[2], ["A2"]);
  assert.deepEqual(zuordnungUmschalten({}, 5, "B1", true), { 5: ["B1"] });
});

test("Zuordnung: Vergleich ohne Reihenfolge und ohne leere Plätze, Bereinigung streicht unbekannte Kennungen", () => {
  assert.ok(zuordnungGleich({ 1: ["B1", "A1"] }, { 1: ["A1", "B1"] }));
  assert.ok(zuordnungGleich({ 1: ["A1"], 2: [] }, { 1: ["A1"] }));
  assert.ok(!zuordnungGleich({ 1: ["A1"] }, { 1: ["A2"] }));
  assert.ok(!zuordnungGleich({ 1: ["A1"] }, {}));
  assert.deepEqual(zuordnungBereinigen({ 1: ["A1", "Z9"] }, KATALOG), { 1: ["A1"] });
});
