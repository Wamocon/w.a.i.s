// Tests für das Signieren des Manifests beim Bau (scripts/wamo-dist-signieren.cjs). Ausführen im Ordner desktop/:  npm test
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { angabenFuer, imGitBaum, manifestText, pruefeAusgabe, schluesselErzeugen, signieren } = require("../scripts/wamo-dist-signieren.cjs");
const { pruefeManifest, schluesselAusListe } = require("./update");

const rohOeffentlich = (k) => Buffer.from(crypto.createPublicKey(k).export({ format: "jwk" }).x, "base64url").toString("base64");

function aufbau() {
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), "wais-sign-test-"));
  const exe = path.join(ordner, "WAIS-Setup-0.3.0.exe");
  fs.writeFileSync(exe, Buffer.from("MZ Testinhalt"));
  const { privateKey } = crypto.generateKeyPairSync("ed25519");
  const schluesselDatei = path.join(ordner, "schluessel.pem");
  fs.writeFileSync(schluesselDatei, privateKey.export({ type: "pkcs8", format: "pem" }));
  return { ordner, exe, schluesselDatei, schluessel: schluesselAusListe([rohOeffentlich(privateKey)]) };
}
const OPT = { commit: "b".repeat(40), bauzeit: "2026-11-16T10:00:00.000Z", paketVersion: "0.3.0" };

test("Manifest in fester Reihenfolge, ohne Zeilenende, mit genau den acht Schlüsseln", () => {
  const t = manifestText({ version: "0.3.0", groesse: 5, sha256: "c".repeat(64), bauzeit: OPT.bauzeit, commit: OPT.commit });
  assert.equal(t.endsWith("\n"), false);
  assert.deepEqual(Object.keys(JSON.parse(t)), ["v", "produkt", "version", "datei", "groesse", "sha256", "bauzeit", "commit"]);
  assert.equal(JSON.parse(t).datei, "WAIS-Setup-0.3.0.exe");
});

test("angabenFuer: nur WAIS-Setup-<Version>.exe mit der Version aus package.json", () => {
  const { ordner, exe } = aufbau();
  assert.equal(angabenFuer(exe, OPT).groesse, 13);
  assert.throws(() => angabenFuer(exe, { ...OPT, paketVersion: "0.3.1" }), /package\.json/);
  const falsch = path.join(ordner, "setup.exe");
  fs.writeFileSync(falsch, "x");
  assert.throws(() => angabenFuer(falsch, OPT), /Dateiname/);
});

test("signieren: schreibt Manifest und Signatur, die App-Prüfung nimmt sie an", () => {
  const { ordner, exe, schluesselDatei, schluessel } = aufbau();
  const m = signieren(exe, { ...OPT, schluesselDatei }, schluessel);
  assert.equal(m.version, "0.3.0");
  const manifest = fs.readFileSync(path.join(ordner, "aktuell.json"), "utf8");
  const signatur = fs.readFileSync(path.join(ordner, "aktuell.json.sig"), "utf8");
  assert.match(signatur, /^[A-Za-z0-9+/]{86}==\n$/);
  assert.equal(pruefeManifest({ manifest, signatur, schluessel, aktuelleVersion: "0.2.0" }).neuer, true);
  assert.doesNotMatch(manifest + signatur, /PRIVATE/);
});

test("signieren mit einem Schlüssel, der nicht in der App steht: Abbruch, nichts geschrieben", () => {
  const { ordner, exe, schluesselDatei } = aufbau();
  const fremd = schluesselAusListe([rohOeffentlich(crypto.generateKeyPairSync("ed25519").privateKey)]);
  assert.throws(() => signieren(exe, { ...OPT, schluesselDatei }, fremd), /update-schluessel\.json/);
  assert.deepEqual(fs.readdirSync(ordner).sort(), ["WAIS-Setup-0.3.0.exe", "schluessel.pem"]);
});

test("pruefeAusgabe: veränderte Datei nach dem Signieren fällt auf", () => {
  const { exe, schluesselDatei, schluessel } = aufbau();
  signieren(exe, { ...OPT, schluesselDatei }, schluessel);
  fs.writeFileSync(exe, Buffer.from("MZ Testinhalx"));
  assert.throws(() => pruefeAusgabe(exe, schluessel), /SHA-256/);
});

test("Schlüssel nie in einem Git-Arbeitsbaum", () => {
  assert.equal(imGitBaum(path.join(__dirname, "geheim.pem")), true);
  assert.throws(() => schluesselErzeugen(path.join(__dirname, "testdaten", "nie.pem")), /Git-Arbeitsbaum/);
  assert.equal(fs.existsSync(path.join(__dirname, "testdaten", "nie.pem")), false);
  assert.equal(imGitBaum(path.join(os.tmpdir(), "irgendwo", "x.pem"), () => false), false);
});
