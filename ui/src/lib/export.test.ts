// Tests für das Speichern des Canvas als Datei (lib/export.ts) und die Nachrichten datei und betrieb.office (lib/nachrichten.ts).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { exportFormate, hinweisText, knopfText, OFFICE_FORMATE, ONENOTE_KNOPF, onenoteMoeglich } from "./export.ts";
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

test("Hinweis aus dem Browser: die Datei liegt auf dem Laptop, nicht auf dem Gerät des Browsers", () => {
  const ok = { ok: true, kennung: "0123456789abcdef", name: "Angebot.docx", ordner: "Dokumente\\WAIS", geoeffnet: false } as const;
  assert.equal(hinweisText(ok, true), "Angebot.docx liegt auf deinem Laptop in Dokumente\\WAIS.");
  assert.equal(hinweisText({ ...ok, geoeffnet: true }, true), "Angebot.docx liegt auf deinem Laptop in Dokumente\\WAIS und ist dort geöffnet.");
  assert.equal(hinweisText(ok, false), "Angebot.docx liegt in Dokumente\\WAIS.");
  assert.equal(hinweisText({ ok: false, grund: "Die PC-Steuerung ist aus." }, true), "Nicht gespeichert: Die PC-Steuerung ist aus.");
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

test("Als OneNote-Seite: nur eigene, gespeicherte Elemente und nur, wenn der Kern es meldet", () => {
  assert.equal(ONENOTE_KNOPF, "Als OneNote-Seite");
  for (const kind of ["dokument", "tabelle", "code", "mermaid"] as const) assert.equal(onenoteMoeglich({ id: ID, kind }, true), true);
  assert.equal(onenoteMoeglich({ id: ID, kind: "dokument" }, false), false);
  assert.equal(onenoteMoeglich({ id: ID, kind: "dokument" }, undefined), false);
  assert.equal(onenoteMoeglich({ kind: "dokument" }, true), false);
  assert.equal(onenoteMoeglich({ id: "dev-42", kind: "dokument" }, true), false);
  assert.equal(onenoteMoeglich({ id: ID, kind: "dokument", teilbar: { id: ID } }, true), false);
  assert.equal(onenoteMoeglich({ id: ID, kind: "dokument", geteilt: { von: "Anna", recht: "lesen" } }, true), false);
});

test("betrieb.onenote nur als echtes true, Nachricht onenote mit ok und Text", () => {
  const an = parseServerMessage({ type: "betrieb", modus: "buero", pc: "verbunden", onenote: true });
  assert.ok(an && an.type === "betrieb" && an.onenote === true);
  const kaputt = parseServerMessage({ type: "betrieb", modus: "buero", pc: "verbunden", onenote: "ja" });
  assert.ok(kaputt && kaputt.type === "betrieb" && kaputt.onenote === undefined);
  assert.deepEqual(parseServerMessage({ type: "onenote", ok: true, text: "Liegt zur Freigabe bereit." }), {
    type: "onenote", ok: true, text: "Liegt zur Freigabe bereit.",
  });
  assert.deepEqual(parseServerMessage({ type: "onenote", ok: false }), { type: "onenote", ok: false, text: "Nicht angelegt." });
  assert.equal(parseServerMessage({ type: "onenote", ok: "ja", text: "x" }), null);
  const lang = parseServerMessage({ type: "onenote", ok: false, text: "x".repeat(5000) });
  assert.ok(lang && lang.type === "onenote" && lang.text.length <= 400);
});
