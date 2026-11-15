// Tests für das Speichern des Canvas als Datei (lib/export.ts) und die Nachrichten datei und betrieb.office (lib/nachrichten.ts).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { exportFormate, hinweisText, knopfText, OFFICE_FORMATE } from "./export.ts";
import { parseServerMessage } from "./nachrichten.ts";

const ID = "11111111-1111-4111-8111-111111111111";
const ALLE = [...OFFICE_FORMATE];

test("Formate wie im Kern und Host, in fester Reihenfolge", () => {
  assert.deepEqual(ALLE, ["word", "excel", "powerpoint", "pdf", "csv", "markdown"]);
  assert.equal(knopfText("word"), "Als Word speichern");
  assert.equal(knopfText("powerpoint"), "Als PowerPoint speichern");
  assert.equal(knopfText("pdf"), "Als PDF speichern");
});

test("Excel und CSV nur für Tabellen, sonst Word, PowerPoint, PDF und Markdown", () => {
  assert.deepEqual(exportFormate({ id: ID, kind: "tabelle" }, ALLE), ALLE);
  for (const kind of ["dokument", "code", "mermaid"] as const) {
    assert.deepEqual(exportFormate({ id: ID, kind }, ALLE), ["word", "powerpoint", "pdf", "markdown"]);
  }
});

test("nur Formate, die der Kern für diese Sitzung meldet", () => {
  assert.deepEqual(exportFormate({ id: ID, kind: "dokument" }, ["word", "excel"]), ["word"]);
  assert.deepEqual(exportFormate({ id: ID, kind: "dokument" }, []), []);
  assert.deepEqual(exportFormate({ id: ID, kind: "dokument" }, undefined), []);
});

test("nur eigene, gespeicherte Elemente: keine fremden, keine ohne Kennung, keine Auftragsergebnisse", () => {
  assert.deepEqual(exportFormate({ kind: "dokument" }, ALLE), []);
  assert.deepEqual(exportFormate({ id: null, kind: "dokument" }, ALLE), []);
  assert.deepEqual(exportFormate({ id: "dev-42", kind: "dokument" }, ALLE), []);
  assert.deepEqual(exportFormate({ id: ID, kind: "dokument", geteilt: { von: "Anna", recht: "bearbeiten" } }, ALLE), []);
  assert.deepEqual(exportFormate({ id: ID, kind: "dokument", teilbar: { id: ID } }, ALLE), []);
});

test("Nachricht datei: Erfolg mit Kennung, Name, Ordner und Pfad", () => {
  const m = parseServerMessage({
    type: "datei", ok: true, kennung: "0123456789abcdef", name: "2026-11-14 Angebot.docx", format: "word",
    ordner: "Dokumente\\WAIS", pfad: "C:\\Users\\x\\Dokumente\\WAIS\\2026-11-14 Angebot.docx", geoeffnet: true,
  });
  assert.deepEqual(m, {
    type: "datei", ok: true, kennung: "0123456789abcdef", name: "2026-11-14 Angebot.docx", format: "word",
    ordner: "Dokumente\\WAIS", pfad: "C:\\Users\\x\\Dokumente\\WAIS\\2026-11-14 Angebot.docx", geoeffnet: true,
  });
  assert.equal(hinweisText(m as never), "2026-11-14 Angebot.docx liegt in Dokumente\\WAIS und ist geöffnet.");
});

test("Nachricht datei: Fehler mit Grund, kaputte Nachrichten werden verworfen", () => {
  assert.deepEqual(parseServerMessage({ type: "datei", ok: false, grund: "Die PC-Steuerung ist aus." }), {
    type: "datei", ok: false, grund: "Die PC-Steuerung ist aus.",
  });
  assert.equal(parseServerMessage({ type: "datei", ok: true, kennung: "../x", name: "a" }), null);
  assert.equal(parseServerMessage({ type: "datei", ok: true, kennung: "0123456789abcdef" }), null);
  assert.equal(parseServerMessage({ type: "datei" }), null);
  const lang = parseServerMessage({ type: "datei", ok: false, grund: "x".repeat(5000) });
  assert.ok(lang && lang.type === "datei" && !lang.ok && lang.grund.length < 400);
  const unsichtbar = parseServerMessage({ type: "datei", ok: true, kennung: "0123456789abcdef", name: "a\u202Efdp.exe", geoeffnet: false });
  assert.ok(unsichtbar && unsichtbar.type === "datei" && unsichtbar.ok && unsichtbar.name === "afdp.exe");
});

test("betrieb.office: nur bekannte Formate, leer heißt nichts", () => {
  const b = parseServerMessage({ type: "betrieb", modus: "buero", pc: "verbunden", office: ["word", "exe", "pdf"] });
  assert.ok(b && b.type === "betrieb");
  assert.deepEqual(b.office, ["word", "pdf"]);
  const ohne = parseServerMessage({ type: "betrieb", modus: "buero", pc: "verbunden", office: [] });
  assert.ok(ohne && ohne.type === "betrieb" && ohne.office === undefined);
  const kaputt = parseServerMessage({ type: "betrieb", modus: "buero", pc: "verbunden", office: "word" });
  assert.ok(kaputt && kaputt.type === "betrieb" && kaputt.office === undefined);
});
