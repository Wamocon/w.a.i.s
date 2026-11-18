// Tests für die Logik des persönlichen GitHub-Zugangs (githubZugang.ts). Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  datumDeutsch,
  fehlerStand,
  fehlerText,
  formFehler,
  gleicheRechte,
  personZeile,
  pruefeAntwort,
  pruefeRechteListe,
  rechteGruppen,
  standZeile,
  tokenForm,
} from "./githubZugang.ts";

const KLASSISCH = "ghp_" + "Kx7".repeat(12);
const FEIN = "github_pat_" + "Fg8_".repeat(20) + "Q9";
const ID = "00000000-0000-4000-8000-0000000027b1";

const antwort = (teil: Record<string, unknown> = {}) => ({
  type: "github_zugang",
  aktion: "speichern",
  verfuegbar: true,
  grund: null,
  hinterlegt: true,
  art: "klassisch",
  login: "person-eins",
  ende: "Kx7K",
  scopes: ["repo", "read:org"],
  ablauf: "2027-02-16",
  geprueft: "2026-11-18T12:00+00:00",
  angelegt: "2026-11-18T12:00+00:00",
  scopes_ausnahmen: ["workflow"],
  problem: null,
  bereit: true,
  hinweis_fein: "Fein-granulares Token: Nötig sind Contents …",
  ok: "Gespeichert.",
  ...teil,
});

test("Antwort des Kerns wird streng gelesen", () => {
  const z = pruefeAntwort(antwort());
  assert.ok(z);
  assert.equal(z.art, "klassisch");
  assert.equal(z.login, "person-eins");
  assert.deepEqual(z.scopes, ["repo", "read:org"]);
  assert.equal(z.bereit, true);
  assert.equal(z.ok, "Gespeichert.");
  assert.deepEqual(z.scopesAusnahmen, ["workflow"]);
  assert.equal(pruefeAntwort({ type: "modellzugang" }), null);
  assert.equal(pruefeAntwort(null), null);
  assert.equal(pruefeAntwort([antwort()]), null);
});

test("unbekannte Werte werden null, nicht hinterlegt heißt keine Angaben", () => {
  const z = pruefeAntwort(antwort({ art: "oauth", login: "-x", ende: "12345", scopes: ["Repo", 3, "repo"], ablauf: "morgen", aktion: "x" }));
  assert.ok(z);
  assert.equal(z.art, null);
  assert.equal(z.login, null);
  assert.equal(z.ende, null);
  assert.deepEqual(z.scopes, ["repo"]);
  assert.equal(z.ablauf, null);
  assert.equal(z.aktion, "stand");
  const leer = pruefeAntwort(antwort({ hinterlegt: false, bereit: true }));
  assert.ok(leer);
  assert.equal(leer.login, null);
  assert.equal(leer.bereit, false);
  assert.deepEqual(leer.scopes, []);
});

test("Sätze ohne Steuerzeichen und gekürzt", () => {
  const z = pruefeAntwort(antwort({ fehler: "a\u0000b\u202ec" + "x".repeat(500) }));
  assert.ok(z?.fehler);
  assert.ok(!/[\u0000\u202e]/.test(z.fehler));
  assert.ok(z.fehler.length <= 400);
});

test("Form des Tokens vorab", () => {
  assert.equal(tokenForm(""), "leer");
  assert.equal(tokenForm(`  ${KLASSISCH} `), "klassisch");
  assert.equal(tokenForm(FEIN), "fein");
  assert.equal(tokenForm("gho_" + "a".repeat(36)), "fremd");
  assert.equal(tokenForm("sk-ant-api03-xyz"), "ungueltig");
  assert.equal(tokenForm(KLASSISCH + "x"), "ungueltig");
  assert.equal(formFehler("klassisch"), null);
  assert.equal(formFehler("leer"), null);
  assert.match(formFehler("fremd") ?? "", /kein persönliches Zugriffstoken/);
  assert.match(formFehler("ungueltig") ?? "", /kein GitHub-Token/);
});

test("Zeile zum Stand nennt nie das Token", () => {
  const z = pruefeAntwort(antwort());
  assert.equal(standZeile(z), "Hinterlegt: Konto person-eins, klassisch, endet auf …Kx7K, gültig bis 16.02.2027.");
  assert.equal(standZeile(null), "Stand wird geladen …");
  assert.equal(standZeile(fehlerStand("stand", "weg")), "Kein GitHub-Token hinterlegt.");
  assert.equal(datumDeutsch(null), "unbekannt");
});

test("Fehler beim Aufruf als konkreter Satz", () => {
  assert.match(fehlerText(0, "Zeitüberschreitung"), /Zeitüberschreitung/);
  assert.match(fehlerText(0, "x"), /nicht erreichbar/);
  assert.match(fehlerText(403, ""), /keinen GitHub-Zugang/);
  assert.match(fehlerText(404, ""), /Plan C/);
  assert.match(fehlerText(429, ""), /Zu viele/);
  assert.match(fehlerText(503, ""), /Problem/);
  assert.match(fehlerText(400, ""), /\(400\)/);
});

test("Admin-Liste: nur bekannte Rechte, nie-Rechte nie erlaubbar", () => {
  const liste = pruefeRechteListe({
    personen: [
      { user_id: ID, name: "Person\u0007 Eins", rolle: "mitglied", aktiv: true, scopes_ausnahmen: ["gist", "delete_repo", "fremd"], hinterlegt: true,
        art: "fein", login: "person-eins", ablauf: "2027-02-16" },
      { user_id: "keine-uuid", name: "x" },
    ],
    erlaubbar: ["workflow", "gist", "delete_repo"],
    nie: ["delete_repo", "site_admin"],
  });
  assert.ok(liste);
  assert.deepEqual(liste.erlaubbar, ["workflow", "gist"]);
  assert.equal(liste.personen.length, 1);
  const p = liste.personen[0];
  assert.equal(p.name, "Person Eins");
  assert.deepEqual(p.scopesAusnahmen, ["gist"]);
  assert.equal(personZeile(p), "Token fein-granular von person-eins, gültig bis 16.02.2027; zusätzlich erlaubt: gist.");
  assert.equal(pruefeRechteListe({ personen: "x" }), null);
});

test("Gruppen in der Reihenfolge des Kerns, Unbekanntes unter Weitere", () => {
  const g = rechteGruppen(["workflow", "admin:org", "gist", "neu:recht"]);
  assert.deepEqual(g.map((x) => x.gruppe), ["Workflows und Gists", "Organisation", "Weitere"]);
  assert.deepEqual(g[0].rechte.map((r) => r.scope), ["workflow", "gist"]);
  assert.equal(g[2].rechte[0].text, "neu:recht");
  assert.ok(gleicheRechte(["a", "b"], ["b", "a"]));
  assert.ok(!gleicheRechte(["a"], ["a", "b"]));
});
