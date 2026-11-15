// Tests für den Weg der Codesignatur (Entscheidung N8): scripts/wamo-dist-codesign.cjs und die Skripte in package.json.
// Ausführen im Ordner desktop/:  npm test
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { bewerte, zuPruefen } = require("../scripts/wamo-dist-codesign.cjs");

const paket = JSON.parse(fs.readFileSync(path.join(__dirname, "package.json"), "utf8"));
const gut = (datei) => ({ datei, status: "Valid", herausgeber: "CN=WAMOCON GmbH, O=WAMOCON GmbH, L=Eschborn, C=DE" });

test("ohne Zertifikat baut dist wie bisher, dist:signiert verlangt die Signatur", () => {
  assert.doesNotMatch(paket.scripts.dist, /forceCodeSigning/);
  assert.match(paket.scripts["dist:signiert"], /--config\.win\.forceCodeSigning=true/);
  assert.match(paket.scripts["dist:signiert"], /wamo-dist-vorbereiten\.cjs/);
  assert.match(paket.scripts["dist:signiert"], /&& node \.\.\/scripts\/wamo-dist-codesign\.cjs dist --pflicht$/);
  assert.match(paket.scripts["dist:codesign"], /wamo-dist-codesign\.cjs dist/);
  assert.equal(paket.build.win.forceCodeSigning, undefined);
});

test("keine Zugangswerte der Signatur im Repo", () => {
  const text = JSON.stringify(paket);
  assert.doesNotMatch(text, /CSC_LINK|CSC_KEY_PASSWORD|certificatePassword|certificateFile|AZURE_CLIENT_SECRET/);
});

test("zuPruefen: Installer und App", () => {
  const d = zuPruefen(path.join("x", "dist"), "0.3.0");
  assert.deepEqual(d.map((p) => path.basename(p)), ["WAIS-Setup-0.3.0.exe", "WAMO.exe"]);
});

test("bewerte: alles gültig vom richtigen Herausgeber", () => {
  const e = bewerte([gut("a.exe"), gut("b.exe")], { pflicht: true });
  assert.equal(e.ok, true);
  assert.equal(e.alleGut, true);
});

test("bewerte: unsigniert ohne Pflicht ist ein Hinweis, mit Pflicht ein Fehler", () => {
  const ohne = [{ datei: "a.exe", status: "NotSigned", herausgeber: "" }, gut("b.exe")];
  const hinweis = bewerte(ohne);
  assert.equal(hinweis.ok, true);
  assert.equal(hinweis.alleGut, false);
  assert.match(hinweis.zeilen.join("\n"), /sieben Pilotkollegen/);
  assert.equal(bewerte(ohne, { pflicht: true }).ok, false);
});

test("bewerte: fremder oder nur ähnlicher Herausgeber zählt nicht", () => {
  const fremd = [{ datei: "a.exe", status: "Valid", herausgeber: "CN=Irgendwer, O=Andere GmbH" }];
  assert.equal(bewerte(fremd, { pflicht: true }).ok, false);
  const aehnlich = [{ datei: "a.exe", status: "Valid", herausgeber: "CN=WAMOCON GmbH Fake, O=Andere" }];
  assert.equal(bewerte(aehnlich, { pflicht: true }).ok, false);
  const abgelaufen = [{ datei: "a.exe", status: "HashMismatch", herausgeber: "CN=WAMOCON GmbH" }];
  assert.equal(bewerte(abgelaufen, { pflicht: true }).ok, false);
  assert.equal(bewerte([], { pflicht: true }).ok, false);
  assert.equal(bewerte([gut("a.exe")], { pflicht: true, herausgeber: "" }).ok, false);
});

test("bewerte: mit Fingerabdruck zählt nur genau dieses Zertifikat", () => {
  const mit = { ...gut("a.exe"), fingerabdruck: "AB12" };
  assert.equal(bewerte([mit], { pflicht: true, fingerabdruck: "ab12" }).ok, true);
  assert.equal(bewerte([mit], { pflicht: true, fingerabdruck: "CD34" }).ok, false);
});
