// Tests für die Logik der Karte "Einreichen" (einreichen.ts). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  auftragGithub,
  einreichenDaten,
  einreichenMoeglich,
  knopfText,
  pruefeEinreichen,
  SATZ_GESPERRT,
  SATZ_PFAD_UNSICHER,
  ungesichertText,
  zahlenText,
} from "./einreichen.ts";

const roh = (teil: Record<string, unknown> = {}) => ({
  status: "bereit",
  repo: "acme/testrepo",
  privat: true,
  zweig: "wamo/ab12cd34ef56ab12",
  konto: "person-eins",
  commit_id: "a".repeat(40),
  tree_id: "b".repeat(40),
  dateien: 2,
  plus: 10,
  minus: 3,
  markiert: ["package.json"],
  pfade: ["package.json", "src/app.ts"],
  weitere: 0,
  gesperrt: [],
  ungesichert: 0,
  lauf: "fertig",
  titel: "Rezepte anlegen",
  nachholen: false,
  ...teil,
});

test("die Karte wird streng gelesen", () => {
  const e = pruefeEinreichen(roh());
  assert.ok(e);
  assert.equal(e.repo, "acme/testrepo");
  assert.deepEqual(e.markiert, ["package.json"]);
  assert.equal(zahlenText(e), "2 Dateien, +10 -3");
  assert.equal(knopfText(e), "Einreichen");
  assert.equal(pruefeEinreichen(roh({ status: "fertig" })), null);
  assert.equal(pruefeEinreichen(roh({ commit_id: "kurz" })), null);
  assert.equal(pruefeEinreichen(roh({ zweig: "main" })), null);
  assert.equal(pruefeEinreichen(null), null);
  const ohne = pruefeEinreichen(roh({ repo: "x", konto: "-x", lauf: "irgendwas", dateien: -1 }));
  assert.ok(ohne);
  assert.equal(ohne.repo, null);
  assert.equal(ohne.konto, null);
  assert.equal(ohne.lauf, null);
  assert.equal(ohne.dateien, 0);
});

test("ein markierter Pfad, der sich nicht sicher anzeigen lässt, sperrt die Karte (fail closed)", () => {
  for (const markiert of [["a\u202eb", "ok.txt"], [" lead"], ["x".repeat(301)], Array.from({ length: 201 }, (_, i) => `d${i}`), "x"]) {
    const e = pruefeEinreichen(roh({ markiert }));
    assert.ok(e);
    assert.equal(e.status, "gesperrt");
    assert.equal(e.gesperrt[0], SATZ_PFAD_UNSICHER);
    assert.equal(einreichenMoeglich(e, new Set(["ok.txt"])), false);
  }
  const doppelt = pruefeEinreichen(roh({ markiert: ["ok.txt", "ok.txt"] }));
  assert.ok(doppelt);
  assert.equal(doppelt.status, "bereit");
  assert.deepEqual(doppelt.markiert, ["ok.txt"]);
  const ohneGrund = pruefeEinreichen(roh({ status: "gesperrt", gesperrt: [] }));
  assert.deepEqual(ohneGrund?.gesperrt, [SATZ_GESPERRT]);
});

test("Einreichen erst mit allen Bestätigungen, nie bei gesperrt", () => {
  const e = pruefeEinreichen(roh({ markiert: ["package.json", "Dockerfile"] }));
  assert.ok(e);
  assert.equal(einreichenMoeglich(e, new Set()), false);
  assert.equal(einreichenMoeglich(e, new Set(["package.json"])), false);
  assert.equal(einreichenMoeglich(e, new Set(["package.json", "Dockerfile"])), true);
  assert.deepEqual(einreichenDaten("j1", e, new Set(["package.json", "Dockerfile", "fremd"])), {
    job: "j1",
    commit_id: "a".repeat(40),
    tree_id: "b".repeat(40),
    bestaetigt: ["Dockerfile", "package.json"],
  });
  const gesperrt = pruefeEinreichen(roh({ status: "gesperrt", commit_id: null, tree_id: null, gesperrt: ["Pfad gesperrt."], nachholen: true }));
  assert.ok(gesperrt);
  assert.equal(einreichenMoeglich(gesperrt, new Set(["package.json"])), false);
  assert.equal(gesperrt.nachholen, false);
  assert.deepEqual(gesperrt.gesperrt, ["Pfad gesperrt."]);
});

test("Nachholen und Hinweise", () => {
  const e = pruefeEinreichen(roh({ status: "branch_gepusht", nachholen: true, ungesichert: 1, fehler: "GitHub hat das Einreichen nicht angenommen." }));
  assert.ok(e);
  assert.equal(knopfText(e), "Pull Request nachholen");
  assert.equal(ungesichertText(e), "1 Datei wurde nicht committet und geht nicht mit.");
  assert.equal(e.fehler, "GitHub hat das Einreichen nicht angenommen.");
  assert.deepEqual(auftragGithub({ konto: "person-eins", hinweis: "x" }), { konto: "person-eins" });
  assert.equal(auftragGithub("x"), undefined);
});
