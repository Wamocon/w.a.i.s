// Tests für Jira-Stories in der Oberfläche (lib/jiraStory.ts, lib/nachrichten.ts, lib/laborKarte.ts): Der Kern meldet, ob er Stories anbietet
// (jira_status), und das Ergebnis (jira_ergebnis). Ein Verweis gilt nur, wenn er auf <name>.atlassian.net/browse/<Schlüssel> zeigt und zum
// Schlüssel passt; sonst zeigt die Oberfläche keinen Verweis. Die Karte mit Job "jira" hat eigene Texte.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { JIRA_JOB, linkOk, projektOk, schluesselOk } from "./jiraStory.ts";
import { abgelaufenHinweis, karteTexte } from "./laborKarte.ts";
import { parseServerMessage } from "./nachrichten.ts";

test("Schlüssel, Projekte und Verweise nach dem Muster von Jira", () => {
  assert.equal(JIRA_JOB, "jira");
  assert.ok(projektOk("WMCNL") && projektOk("AB_1"));
  for (const p of ["wmcnl", "W", "WMCNL-1", "ABCDEFGHIJK", ""]) assert.equal(projektOk(p), false, p);
  assert.ok(schluesselOk("WMCNL-123"));
  for (const s of ["WMCNL-0", "WMCNL-", "wmcnl-1", "WMCNL-1 ", "WMCNL-1234567890"]) assert.equal(schluesselOk(s), false, s);
  assert.ok(linkOk("https://wamocon.atlassian.net/browse/WMCNL-123", "WMCNL-123"));
  for (const l of [
    "http://wamocon.atlassian.net/browse/WMCNL-123",
    "https://wamocon.atlassian.net.boese.example/browse/WMCNL-123",
    "https://boese.example/browse/WMCNL-123",
    "https://wamocon.atlassian.net/browse/WMCNL-124",
    "https://wamocon.atlassian.net/browse/WMCNL-123?x=1",
    "javascript:alert(1)",
  ]) {
    assert.equal(linkOk(l, "WMCNL-123"), false, l);
  }
});

test("jira_status: nur gültige Projekte, das Standardprojekt muss dabei sein", () => {
  assert.deepEqual(parseServerMessage({ type: "jira_status", projekte: ["WMCNL", "ABC", "böse!", 5], standard: "WMCNL" }), {
    type: "jira_status",
    projekte: ["WMCNL", "ABC"],
    standard: "WMCNL",
  });
  assert.equal(parseServerMessage({ type: "jira_status", projekte: ["ABC"], standard: "WMCNL" }), null);
  assert.equal(parseServerMessage({ type: "jira_status", projekte: [], standard: "WMCNL" }), null);
  assert.equal(parseServerMessage({ type: "jira_status", projekte: "WMCNL", standard: "WMCNL" }), null);
});

test("jira_ergebnis: angelegt mit Schlüssel und geprüftem Verweis", () => {
  assert.deepEqual(
    parseServerMessage({
      type: "jira_ergebnis",
      ok: true,
      schluessel: "WMCNL-123",
      link: "https://wamocon.atlassian.net/browse/WMCNL-123",
      text: "Angelegt als WMCNL-123.",
    }),
    { type: "jira_ergebnis", ok: true, schluessel: "WMCNL-123", link: "https://wamocon.atlassian.net/browse/WMCNL-123", text: "Angelegt als WMCNL-123." },
  );
  const fremd = parseServerMessage({ type: "jira_ergebnis", ok: true, schluessel: "WMCNL-123", link: "https://boese.example/x", text: "Angelegt." });
  assert.equal(fremd?.type === "jira_ergebnis" ? fremd.link : "x", undefined); // ein fremder Verweis fällt weg, der Schlüssel bleibt
  assert.equal(parseServerMessage({ type: "jira_ergebnis", ok: true, text: "Angelegt." }), null); // angelegt ohne Schlüssel gibt es nicht
});

test("jira_ergebnis: nicht angelegt, Text ohne Steuer- und Bidi-Zeichen, nie ein Verweis", () => {
  const m = parseServerMessage({
    type: "jira_ergebnis",
    ok: false,
    text: "Jira bremst\u202e gerade.\u0007",
    schluessel: "WMCNL-1",
    link: "https://wamocon.atlassian.net/browse/WMCNL-1",
  });
  assert.deepEqual(m, { type: "jira_ergebnis", ok: false, text: "Jira bremst gerade." });
  assert.equal(parseServerMessage({ type: "jira_ergebnis", ok: "ja", text: "x" }), null);
});

test("Karte mit Job jira: eigene Texte, nach Ablauf ist nichts passiert", () => {
  const t = karteTexte("jira");
  assert.equal(t.ueberschrift, "Jira-Story freigeben");
  assert.equal(t.hinweis, "Du entscheidest, nicht W.A.I.S. Angelegt wird genau, was hier steht.");
  assert.equal(t.zielLabel, "Ziel:");
  assert.equal(abgelaufenHinweis("jira"), "Die Freigabe ist abgelaufen; es ist nichts passiert.");
});
