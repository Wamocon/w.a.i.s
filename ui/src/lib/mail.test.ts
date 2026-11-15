// Tests für die Mail über Outlook (lib/mail.ts) und ihre Nachrichten (lib/nachrichten.ts: mail_antwort, mail_versand, betrieb.mail,
// Warnung und lange Karte bei Freigaben). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { anhangVorschlag, empfaengerListe, formularFehler, MAIL_EMPFAENGER_MAX, restSekunden, versandText } from "./mail.ts";
import { parseServerMessage } from "./nachrichten.ts";

test("Empfänger: Komma, Semikolon und Zeilen trennen, Leerraum fällt weg", () => {
  assert.deepEqual(empfaengerListe(" max@firma.example, Max Weber;\nanna@kunde.example ,, "), [
    "max@firma.example",
    "Max Weber",
    "anna@kunde.example",
  ]);
  assert.deepEqual(empfaengerListe(""), []);
});

test("Formular: An und Betreff nötig, höchstens zehn Empfänger, Grenzen wie im Host", () => {
  const gut = { an: ["max@firma.example"], cc: [], betreff: "Angebot", text: "Hallo" };
  assert.equal(formularFehler(gut), null);
  assert.match(formularFehler({ ...gut, an: [] }) ?? "", /Empfänger/);
  assert.match(formularFehler({ ...gut, betreff: "  " }) ?? "", /Betreff/);
  const viele = Array.from({ length: MAIL_EMPFAENGER_MAX }, (_, i) => `x${i}@firma.example`);
  assert.match(formularFehler({ ...gut, an: viele, cc: ["y@firma.example"] }) ?? "", /10/);
  assert.match(formularFehler({ ...gut, betreff: "x".repeat(201) }) ?? "", /Betreff/);
  assert.match(formularFehler({ ...gut, text: "x".repeat(6001) }) ?? "", /Text/);
});

test("Anhang: PDF als Vorschlag, sonst das erste Format, ohne Formate keiner", () => {
  assert.equal(anhangVorschlag(["word", "pdf"]), "pdf");
  assert.equal(anhangVorschlag(["word", "markdown"]), "word");
  assert.equal(anhangVorschlag([]), null);
});

test("Versand: Restzeit und Texte je Zustand", () => {
  assert.equal(restSekunden(10_500, 1_000), 10);
  assert.equal(restSekunden(500, 1_000), 0);
  assert.equal(restSekunden(undefined, 1_000), 0);
  const wartet = { id: "fedcba9876543210", zustand: "wartet" as const, text: "x" };
  assert.equal(versandText(wartet, 12), "Die Mail geht in 12 Sekunden raus.");
  assert.equal(versandText(wartet, 1), "Die Mail geht in 1 Sekunde raus.");
  assert.equal(versandText(wartet, 0), "Die Mail geht jetzt raus.");
  assert.equal(versandText({ zustand: "entwurf", text: "Der Entwurf ist offen." }, 0), "Der Entwurf ist offen.");
});

test("Nachricht mail_versand: Kennung, Zustand, Restzeit und Text geprüft", () => {
  const ok = parseServerMessage({ type: "mail_versand", id: "fedcba9876543210", zustand: "wartet", rest_s: 30, text: "Die Mail geht\u202e raus." });
  assert.deepEqual(ok, { type: "mail_versand", id: "fedcba9876543210", zustand: "wartet", restS: 30, text: "Die Mail geht raus." });
  assert.deepEqual(parseServerMessage({ type: "mail_versand", id: null, zustand: "entwurf", text: "Offen" }), {
    type: "mail_versand",
    id: null,
    zustand: "entwurf",
    restS: undefined,
    text: "Offen",
  });
  assert.equal(parseServerMessage({ type: "mail_versand", id: "../x", zustand: "wartet", text: "x" }), null);
  assert.equal(parseServerMessage({ type: "mail_versand", id: null, zustand: "boese", text: "x" }), null);
  assert.equal(parseServerMessage({ type: "mail_versand", id: "fedcba9876543210", zustand: "wartet", rest_s: 9999, text: "x" })?.type, "mail_versand");
});

test("Nachricht mail_antwort und betrieb.mail", () => {
  assert.deepEqual(parseServerMessage({ type: "mail_antwort", ok: true }), { type: "mail_antwort", ok: true });
  assert.deepEqual(parseServerMessage({ type: "mail_antwort", ok: false, grund: "Outlook ist nicht geöffnet." }), {
    type: "mail_antwort",
    ok: false,
    grund: "Outlook ist nicht geöffnet.",
  });
  assert.equal(parseServerMessage({ type: "mail_antwort", ok: "ja" }), null);
  const b = parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "verbunden", mail: true });
  assert.equal(b?.type === "betrieb" && b.mail, true);
  const ohne = parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "verbunden", mail: "ja" });
  assert.equal(ohne?.type === "betrieb" && ohne.mail, undefined);
});

test("Freigabe: Warnung und lange Karte bis 8000 Zeichen ohne Kürzung", () => {
  const detail = "Text:\n" + "> Zeile\n".repeat(900);
  const m = parseServerMessage({
    type: "freigaben",
    job: "pc",
    projekt: "PC",
    items: [{ id: "0123456789abcdef", grund: "Mail über Outlook senden", detail, warnung: "Prüfe Empfänger\u200b genau." }],
  });
  assert.ok(m?.type === "freigaben");
  if (m?.type !== "freigaben") return;
  assert.equal(m.items[0].detail, detail);
  assert.equal(m.items[0].warnung, "Prüfe Empfänger genau.");
  const ohne = parseServerMessage({ type: "freigaben", job: "pc", projekt: "PC", items: [{ id: "a", grund: "g", detail: "d" }] });
  assert.ok(ohne?.type === "freigaben" && ohne.items[0].warnung === undefined);
  // Labor und Geräte bleiben bei 2000 (ihre Grenzen im Kern rechnen damit)
  const labor = parseServerMessage({ type: "freigaben", job: "labor", projekt: "P", items: [{ id: "a", grund: "g", detail }] });
  assert.ok(labor?.type === "freigaben" && labor.items[0].detail.includes("gekürzt"));
});
