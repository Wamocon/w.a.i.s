// Tests für die Logik des Claude-Zugangs des Labors (laborZugangLogik.ts). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  alsLaborZugang,
  codeSauber,
  eingabePruefen,
  faktorFrisch,
  fehlerBild,
  quelleSatz,
  satz,
  schwaerzen,
  zeitText,
} from "./laborZugangLogik.ts";

// Ein Schlüssel wird nie als Ganzes in den Quelltext geschrieben, sondern zusammengesetzt
const MARKER = "MARKERgeheim0815";
const SCHLUESSEL = ["sk", "ant", "api03"].join("-") + `-${MARKER}-0123456789abcdefghij-Zq77`;
const TOKEN = ["sk", "ant", "oat01"].join("-") + "-GEHEIMgeheim-0123456789abcdefghijklmnop-Zz99";

const antwort = (teil: Record<string, unknown> = {}) => ({
  quelle: "gespeichert",
  endet_auf: "Zq77",
  workspace: null,
  gesetzt_am: "2026-11-21T09:30:00+00:00",
  geprueft_am: "2026-11-21T09:30:00+00:00",
  hinweis: null,
  ...teil,
});

function token(totpVorS: number | null, jetztMs: number, aal = "aal2"): string {
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const amr: unknown[] = [{ method: "password", timestamp: Math.floor(jetztMs / 1000) - 3600 }];
  if (totpVorS !== null) amr.push({ method: "totp", timestamp: Math.floor(jetztMs / 1000) - totpVorS });
  return `${b64({ alg: "none" })}.${b64({ aal, amr })}.x`;
}

test("die Antwort des Kerns wird streng gelesen", () => {
  assert.deepEqual(alsLaborZugang(antwort()), {
    quelle: "gespeichert",
    endetAuf: "Zq77",
    workspace: null,
    gesetztAm: "2026-11-21T09:30:00+00:00",
    geprueftAm: "2026-11-21T09:30:00+00:00",
    hinweis: null,
  });
  assert.equal(alsLaborZugang(antwort({ quelle: "irgendwas" })), null);
  assert.equal(alsLaborZugang(null), null);
  assert.equal(alsLaborZugang([]), null);
  assert.equal(alsLaborZugang("gespeichert"), null);
  const roh = alsLaborZugang(antwort({ endet_auf: "zu lang", workspace: "workspace", gesetzt_am: "gestern", geprueft_am: 5, hinweis: 7 }));
  assert.deepEqual(roh && [roh.endetAuf, roh.workspace, roh.gesetztAm, roh.geprueftAm, roh.hinweis], [null, null, null, null, null]);
  assert.equal(alsLaborZugang(antwort({ workspace: "wrkspc_Test123456" }))?.workspace, "wrkspc_Test123456");
});

test("ein Feld mit einem Schlüssel wird nie übernommen, ein Hinweis nur gesäubert und gekürzt", () => {
  const z = alsLaborZugang({ ...antwort(), claude_schluessel: SCHLUESSEL, schluessel: SCHLUESSEL, hinweis: `Fehler mit ${SCHLUESSEL} im Satz` });
  assert.ok(z);
  assert.equal(JSON.stringify(z).includes(MARKER), false);
  assert.ok(z.hinweis?.includes("sk-ant-…"));
  assert.equal(satz("x".repeat(1000))?.length, 400);
  assert.equal(satz("a\u0000b\nc"), "a b c");
  assert.equal(satz("   "), null);
});

test("schwaerzen kürzt alles, was nach einem Schlüssel aussieht", () => {
  assert.equal(schwaerzen(`vor ${SCHLUESSEL} nach`), "vor sk-ant-… nach");
  assert.equal(schwaerzen("sk-ant-abcdefgh"), "sk-ant-…"); // schon ab acht Zeichen, wie im Kern
  assert.equal(schwaerzen("sk-ant-kurz"), "sk-ant-kurz");
  assert.equal(schwaerzen("kein Schlüssel hier"), "kein Schlüssel hier");
});

test("zeitText und quelleSatz", () => {
  assert.equal(zeitText("2026-11-21T09:30:00+00:00"), "21.11.2026, 09:30");
  assert.equal(zeitText("2026-11-21T09:30:00Z"), "21.11.2026, 09:30");
  assert.equal(zeitText("gestern"), null);
  assert.equal(zeitText(null), null);
  const z = alsLaborZugang(antwort());
  assert.ok(z);
  assert.match(quelleSatz(z), /hier gespeicherte Schlüssel gilt, endet auf …Zq77/);
  assert.match(quelleSatz({ ...z, quelle: "server" }), /Schlüssel des Servers, endet auf …Zq77/);
  assert.match(quelleSatz({ ...z, quelle: "keiner", endetAuf: null }), /Hausmodelle/);
});

test("die Eingabe wird vor dem Senden geprüft und der Satz nennt nie den Schlüssel", () => {
  const ok = eingabePruefen(`  ${SCHLUESSEL}  `, " wrkspc_Test123456 ");
  assert.deepEqual(ok, { ok: true, eingabe: { schluessel: SCHLUESSEL, workspace: "wrkspc_Test123456" } });
  assert.deepEqual(eingabePruefen(SCHLUESSEL, ""), { ok: true, eingabe: { schluessel: SCHLUESSEL, workspace: null } });
  for (const [s, w, wort] of [
    ["", "", /Bitte trag/],
    ["   ", "", /Bitte trag/],
    [TOKEN, "", /Claude-Code-Token/],
    ["kein-schluessel", "", /nicht nach einem Anthropic-API-Schlüssel/],
    [["sk", "ant", "api03", "kurz"].join("-"), "", /nicht nach einem/],
    [`${SCHLUESSEL} zwei`, "", /nicht nach einem/],
    [SCHLUESSEL, "workspace", /wrkspc_/],
  ] as const) {
    const r = eingabePruefen(s, w);
    assert.equal(r.ok, false, s);
    if (!r.ok) {
      assert.match(r.text, wort);
      assert.equal(r.text.includes(MARKER), false);
    }
  }
});

test("der Code des zweiten Faktors", () => {
  assert.equal(codeSauber("123 456"), "123456");
  assert.equal(codeSauber(" 123456 "), "123456");
  assert.equal(codeSauber("12345"), null);
  assert.equal(codeSauber("12345a"), null);
  assert.equal(codeSauber(""), null);
});

test("faktorFrisch: höchstens 50 Sekunden alt, nie aus der Zukunft, nur mit aal2 und totp", () => {
  const jetzt = 1_800_000_000_000;
  assert.equal(faktorFrisch(token(10, jetzt), jetzt), true);
  assert.equal(faktorFrisch(token(50, jetzt), jetzt), true);
  assert.equal(faktorFrisch(token(51, jetzt), jetzt), false); // der Kern nähme 60, die Oberfläche lässt Luft
  assert.equal(faktorFrisch(token(600, jetzt), jetzt), false);
  assert.equal(faktorFrisch(token(-60, jetzt), jetzt), false); // aus der Zukunft
  assert.equal(faktorFrisch(token(null, jetzt), jetzt), false);
  assert.equal(faktorFrisch(token(10, jetzt, "aal1"), jetzt), false);
  assert.equal(faktorFrisch(null, jetzt), false);
  assert.equal(faktorFrisch("kein.token", jetzt), false);
});

test("Fehlerbilder: feste Sätze für bekannte Codes, der Satz des Kerns für die Einzelheit, sonst ein Satz zum Status", () => {
  assert.match(fehlerBild(403, "zweiter_faktor_zu_alt", "egal").text, /frischen Code/);
  assert.match(fehlerBild(403, "nicht_berechtigt", "egal").text, /nur Admins/);
  assert.match(fehlerBild(403, "labor_pfad_gesperrt", "egal").text, /Laborprofil/);
  assert.match(fehlerBild(429, "zu_oft", "egal").text, /Zu viele Versuche/);
  assert.equal(fehlerBild(400, "schluessel_abgelehnt", "Anthropic lehnt den Schlüssel ab (401).").text, "Anthropic lehnt den Schlüssel ab (401).");
  assert.equal(fehlerBild(502, "anthropic_nicht_erreichbar", "Anthropic ist gerade nicht erreichbar.").code, "anthropic_nicht_erreichbar");
  // unbekannter Code oder Platzhaltertext des Clients: Satz zum Status
  assert.equal(fehlerBild(400, "schluessel_abgelehnt", "Fehler 400").code, "antwort");
  assert.match(fehlerBild(404, null, "Fehler 404").text, /Paket Labor-Zugang/);
  assert.match(fehlerBild(0, null, "Kern nicht erreichbar").text, /nicht erreichbar/);
  assert.match(fehlerBild(401, null, null).text, /melde dich neu an/);
  assert.match(fehlerBild(403, "komisch", "fremder Text").text, /nur Admins/);
  assert.match(fehlerBild(503, null, "Fehler 503").text, /nicht verfügbar/);
  assert.equal(fehlerBild(413, null, null).code, "zu_gross");
  // ein Schlüssel im Satz des Kerns erscheint nie
  const mit = fehlerBild(400, "schluessel_abgelehnt", `Anthropic lehnt ${SCHLUESSEL} ab`);
  assert.equal(mit.text.includes(MARKER), false);
  assert.match(mit.text, /sk-ant-…/);
});
