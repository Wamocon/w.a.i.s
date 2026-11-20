// Tests für die Fehlerbilder der Werkstatt (lib/werkstattFehler.ts): jeder Code der Schnittstelle bekommt einen Satz.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FEHLER_SAETZE,
  brauchtNeuenCode,
  codeZuStatus,
  detailText,
  eigenerFehler,
  fehlerBild,
  karteUnbrauchbar,
} from "./werkstattFehler.ts";

const GEDANKENSTRICH = /[–—]|\s-\s/;
const SCHNITTSTELLE = [
  "nicht_angemeldet",
  "aal2_fehlt",
  "aal2_alt",
  "nicht_berechtigt",
  "labor_profil",
  "nicht_gefunden",
  "karte_verbraucht",
  "konflikt",
  "karte_abgelaufen",
  "ungueltig",
  "zu_oft",
  "nicht_verfuegbar",
];

test("jeder Code der Schnittstelle hat einen deutschen Satz ohne Gedankenstrich", () => {
  for (const code of SCHNITTSTELLE) {
    const satz = FEHLER_SAETZE[code];
    assert.ok(satz && satz.length > 10, code);
    assert.doesNotMatch(satz, GEDANKENSTRICH, code);
    assert.match(satz, /[.]$/, code);
  }
  for (const satz of Object.values(FEHLER_SAETZE)) assert.doesNotMatch(satz, GEDANKENSTRICH);
});

test("ein bekannter Code gewinnt gegen den Status, der Text des Dienstes bleibt aus den meisten Sätzen heraus", () => {
  const f = fehlerBild(403, "aal2_alt", "interner Name tabelle_x");
  assert.equal(f.code, "aal2_alt");
  assert.equal(f.status, 403);
  assert.equal(f.text, FEHLER_SAETZE.aal2_alt);
  assert.doesNotMatch(f.text, /tabelle_x/);
});

test("ungültig, Konflikt und nicht gefunden hängen die Einzelheit des Dienstes an, gesäubert und gekürzt", () => {
  assert.equal(fehlerBild(422, "ungueltig", "Titel ist zu lang").text, `${FEHLER_SAETZE.ungueltig} Titel ist zu lang`);
  assert.equal(fehlerBild(409, "konflikt", "Tag schon vergeben").text, `${FEHLER_SAETZE.konflikt} Tag schon vergeben`);
  const lang = fehlerBild(422, "ungueltig", `a\u0000b\n${"x".repeat(500)}`);
  assert.ok(lang.text.length <= FEHLER_SAETZE.ungueltig.length + 1 + 200);
  assert.doesNotMatch(lang.text, /[\u0000-\u001f]/);
  // dieselbe Einzelheit steht nie doppelt
  assert.equal(fehlerBild(422, "ungueltig", FEHLER_SAETZE.ungueltig).text, FEHLER_SAETZE.ungueltig);
});

test("ein unbekannter oder fehlender Code fällt auf den Satz zum Status zurück", () => {
  assert.equal(fehlerBild(401, undefined, "x").code, "nicht_angemeldet");
  assert.equal(fehlerBild(403, "etwas_neues", null).code, "nicht_berechtigt");
  assert.equal(fehlerBild(404, 5, null).code, "nicht_gefunden");
  assert.equal(fehlerBild(409, "../etc", null).code, "konflikt");
  assert.equal(fehlerBild(410, null, null).code, "karte_abgelaufen");
  assert.equal(fehlerBild(422, null, null).code, "ungueltig");
  assert.equal(fehlerBild(429, null, null).code, "zu_oft");
  assert.equal(fehlerBild(502, null, null).code, "nicht_verfuegbar");
  assert.equal(fehlerBild(418, null, null).code, "antwort");
  // ein unbekannter Code gibt nie rohen Text des Dienstes weiter
  assert.doesNotMatch(fehlerBild(403, "geheimer_name", "Tabelle wamo_dev.profiles").text, /wamo_dev/);
});

test("codeZuStatus deckt jeden Statuswert der Schnittstelle ab", () => {
  assert.deepEqual(
    [401, 403, 404, 409, 410, 422, 429, 500, 503].map(codeZuStatus),
    ["nicht_angemeldet", "nicht_berechtigt", "nicht_gefunden", "konflikt", "karte_abgelaufen", "ungueltig", "zu_oft", "nicht_verfuegbar", "nicht_verfuegbar"],
  );
});

test("eigene Fehler der Oberfläche tragen Status 0 und optional eine Einzelheit", () => {
  assert.deepEqual(eigenerFehler("netz"), { code: "netz", text: FEHLER_SAETZE.netz, status: 0 });
  assert.equal(eigenerFehler("ungueltig", "Die Kennung ist falsch.").text, `${FEHLER_SAETZE.ungueltig} Die Kennung ist falsch.`);
});

test("detailText: nur Text, ohne Steuerzeichen, ohne Leerraum am Rand", () => {
  assert.equal(detailText(" a \n\t b "), "a b");
  assert.equal(detailText(""), null);
  assert.equal(detailText("   "), null);
  assert.equal(detailText(7), null);
  assert.equal(detailText({}), null);
});

test("welche Fehler einen neuen Code oder eine neue Karte verlangen", () => {
  assert.ok(brauchtNeuenCode("aal2_alt"));
  assert.ok(brauchtNeuenCode("aal2_fehlt"));
  assert.ok(!brauchtNeuenCode("zu_oft"));
  assert.ok(karteUnbrauchbar("karte_abgelaufen"));
  assert.ok(karteUnbrauchbar("karte_verbraucht"));
  assert.ok(!karteUnbrauchbar("aal2_alt"));
});
