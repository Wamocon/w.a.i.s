// Tests für die Teams-Nachricht (lib/teams.ts) und ihre Nachrichten (lib/nachrichten.ts: teams_antwort, betrieb.teams).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseServerMessage } from "./nachrichten.ts";
import { klartext, TEAMS_EMPFAENGER_MAX, TEAMS_GRUPPE_MAX, TEAMS_TEXT_MAX, teamsFehler } from "./teams.ts";

test("Formular: Empfänger und Text nötig, Grenzen wie im Host, Gruppenname nur für mehrere", () => {
  const gut = { an: ["max@firma.example"], gruppenname: "", text: "Hallo" };
  assert.equal(teamsFehler(gut), null);
  assert.match(teamsFehler({ ...gut, an: [] }) ?? "", /Empfänger/);
  const viele = Array.from({ length: TEAMS_EMPFAENGER_MAX + 1 }, (_, i) => `x${i}@firma.example`);
  assert.match(teamsFehler({ ...gut, an: viele }) ?? "", /10/);
  assert.match(teamsFehler({ ...gut, text: "  \n" }) ?? "", /Text/);
  // zu lang heißt Hinweis mit der Zahl, nie still gekürzt
  assert.match(teamsFehler({ ...gut, text: "x".repeat(TEAMS_TEXT_MAX + 1) }) ?? "", /1001.*1000.*kürzen/);
  assert.match(teamsFehler({ ...gut, gruppenname: "Projekt" }) ?? "", /mindestens zwei/);
  assert.equal(teamsFehler({ ...gut, an: ["a@firma.example", "b@firma.example"], gruppenname: "Projekt" }), null);
  assert.match(teamsFehler({ ...gut, an: ["a@firma.example", "b@firma.example"], gruppenname: "g".repeat(TEAMS_GRUPPE_MAX + 1) }) ?? "", /100/);
});

test("Klartext aus dem Canvas: Markdown-Zeichen fallen weg, Tabellen als Zeilen, Code bleibt", () => {
  const text = "# Angebot\n\n**Wichtig:** der `Termin` steht.\n- Punkt [Link](https://firma.example/a)\n```\ncode\n```";
  assert.equal(
    klartext({ kind: "dokument", title: "Angebot", text }),
    "Angebot\n\nWichtig: der Termin steht.\n- Punkt Link (https://firma.example/a)\ncode",
  );
  const tabelle = { kind: "tabelle" as const, title: "Liste", columns: ["Name", "Stand"], rows: [["A", "fertig"], ["B", "offen"]] };
  assert.equal(klartext(tabelle), "Liste\nName | Stand\nA | fertig\nB | offen");
  assert.equal(klartext({ kind: "code", title: "x", text: "a **b**" }), "a **b**");
});

test("Nachrichten: teams_antwort und betrieb.teams", () => {
  assert.deepEqual(parseServerMessage({ type: "teams_antwort", ok: true }), { type: "teams_antwort", ok: true });
  assert.deepEqual(parseServerMessage({ type: "teams_antwort", ok: false, grund: "Nur interne Adressen." }), {
    type: "teams_antwort",
    ok: false,
    grund: "Nur interne Adressen.",
  });
  assert.equal(parseServerMessage({ type: "teams_antwort", ok: "ja" }), null);
  const betrieb = (teams: unknown) => parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "verbunden", teams });
  assert.equal((betrieb(true) as { teams?: boolean }).teams, true);
  assert.equal((betrieb("ja") as { teams?: boolean }).teams, undefined);
});
