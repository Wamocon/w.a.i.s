// Tests für die Prüfung signierter Updates (update.js). Ausführen im Ordner desktop/:  npm test
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { PassThrough } = require("node:stream");
const { test } = require("node:test");
const {
  MANIFEST_SCHLUESSEL,
  TEXT,
  erzeugeUpdater,
  ladeInstaller,
  pruefeManifest,
  schluesselAusListe,
  verbindeGeprueft,
  vergleicheVersionen,
} = require("./update");

// ---------- Hilfen ----------
function schluesselpaar() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync("ed25519");
  const roh = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url").toString("base64");
  return { privateKey, roh };
}
const EIGEN = schluesselpaar();
const FREMD = schluesselpaar();
const SCHLUESSEL = schluesselAusListe([EIGEN.roh]);

const INHALT = Buffer.from("MZ das ist kein echter Installer, nur Testbytes");
const SHA = crypto.createHash("sha256").update(INHALT).digest("hex");

function manifestText(teil = {}) {
  const m = {
    v: 1,
    produkt: "wais-desktop",
    version: "0.3.0",
    datei: "WAIS-Setup-0.3.0.exe",
    groesse: INHALT.length,
    sha256: SHA,
    bauzeit: "2026-11-16T10:00:00.000Z",
    commit: "a".repeat(40),
    ...teil,
  };
  if (teil.version && !("datei" in teil)) m.datei = `WAIS-Setup-${teil.version}.exe`;
  return JSON.stringify(m);
}
const signiere = (text, schluessel = EIGEN.privateKey) => crypto.sign(null, Buffer.from(text, "utf8"), schluessel).toString("base64");
const angebot = (teil, schluessel) => {
  const manifest = typeof teil === "string" ? teil : manifestText(teil);
  return { manifest, signatur: signiere(manifest, schluessel) };
};
const pruefe = (a, aktuelleVersion = "0.2.0") => pruefeManifest({ ...a, schluessel: SCHLUESSEL, aktuelleVersion });
const TOKEN = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXI";

// ---------- Versionen und Schlüssel ----------
test("vergleicheVersionen: numerisch je Teil", () => {
  assert.equal(vergleicheVersionen("0.3.0", "0.2.0"), 1);
  assert.equal(vergleicheVersionen("0.10.0", "0.9.9"), 1);
  assert.equal(vergleicheVersionen("1.0.0", "1.0.0"), 0);
  assert.equal(vergleicheVersionen("0.2.9", "0.3.0"), -1);
});

test("schluesselAusListe: nur Base64 von genau 32 Byte, nie leer", () => {
  assert.equal(schluesselAusListe([EIGEN.roh, FREMD.roh]).length, 2);
  assert.throws(() => schluesselAusListe([]), /Schlüssel/);
  assert.throws(() => schluesselAusListe("x"), /Schlüssel/);
  assert.throws(() => schluesselAusListe([Buffer.alloc(31).toString("base64")]), /Schlüssel/);
  assert.throws(() => schluesselAusListe([`${EIGEN.roh}x`]), /Schlüssel/);
});

test("der feste Schlüssel der App ist gültig und enthält keinen privaten Teil", () => {
  const liste = JSON.parse(fs.readFileSync(path.join(__dirname, "update-schluessel.json"), "utf8"));
  assert.ok(Array.isArray(liste) && liste.length >= 1 && liste.length <= 4);
  assert.equal(schluesselAusListe(liste).length, liste.length);
  assert.doesNotMatch(fs.readFileSync(path.join(__dirname, "update-schluessel.json"), "utf8"), /PRIVATE|BEGIN/);
});

// ---------- Prüfung des Manifests ----------
test("gültiges Manifest mit steigender Version: ok und neuer", () => {
  const e = pruefe(angebot());
  assert.equal(e.ok, true);
  assert.equal(e.neuer, true);
  assert.equal(e.manifest.version, "0.3.0");
  assert.ok(Object.isFrozen(e.manifest));
});

test("Signatur mit Zeilenende (Datei aktuell.json.sig) gilt auch", () => {
  const a = angebot();
  assert.equal(pruefe({ ...a, signatur: `${a.signatur}\n` }).ok, true);
});

test("falsche Signatur: abgelehnt", () => {
  const a = angebot();
  const kaputt = Buffer.from(a.signatur, "base64");
  kaputt[5] ^= 1;
  const e = pruefe({ ...a, signatur: kaputt.toString("base64") });
  assert.equal(e.ok, false);
  assert.match(e.grund, /Signatur/);
});

test("verändertes Manifest bei gleicher Signatur: abgelehnt", () => {
  const a = angebot();
  assert.equal(pruefe({ ...a, manifest: a.manifest.replace("0.3.0", "0.3.1") }).ok, false);
  assert.equal(pruefe({ ...a, manifest: `${a.manifest} ` }).ok, false);
});

test("fremder Schlüssel: abgelehnt", () => {
  const e = pruefe(angebot({}, FREMD.privateKey));
  assert.equal(e.ok, false);
  assert.match(e.grund, /Signatur/);
});

test("alte oder gleiche Version: gültig, aber nicht neuer", () => {
  assert.equal(pruefe(angebot({ version: "0.2.0" })).neuer, false);
  assert.equal(pruefe(angebot({ version: "0.1.9" })).neuer, false);
  assert.equal(pruefe(angebot({ version: "0.3.0" }), "0.3.0").neuer, false);
});

test("Format der Signatur: nur 88 Zeichen Base64 mit Auffüllung", () => {
  const a = angebot();
  for (const signatur of ["", "abc", a.signatur.replace(/=+$/, ""), Buffer.alloc(63).toString("base64"), `${a.signatur}\r\n`, null, 7]) {
    assert.equal(pruefe({ ...a, signatur }).ok, false, String(signatur));
  }
});

test("Manifest: genau die acht Schlüssel, feste Werte und Formate", () => {
  assert.deepEqual([...MANIFEST_SCHLUESSEL].sort(), ["bauzeit", "commit", "datei", "groesse", "produkt", "sha256", "v", "version"]);
  const schlecht = [
    { v: 2 },
    { v: "1" },
    { produkt: "anderes" },
    { version: "0.3" },
    { version: "00.3.0", datei: "WAIS-Setup-00.3.0.exe" },
    { version: "0.3.0-beta", datei: "WAIS-Setup-0.3.0-beta.exe" },
    { version: "10000.0.0", datei: "WAIS-Setup-10000.0.0.exe" },
    { datei: "WAIS-Setup-0.3.1.exe" },
    { datei: "..\\WAIS-Setup-0.3.0.exe" },
    { groesse: 0 },
    { groesse: 1.5 },
    { groesse: 536870913 },
    { sha256: "A".repeat(64) },
    { sha256: "a".repeat(63) },
    { bauzeit: "16.11.2026" },
    { commit: "a".repeat(39) },
    { zusatz: 1 },
  ];
  for (const teil of schlecht) assert.equal(pruefe(angebot(teil)).ok, false, JSON.stringify(teil));
  const ohne = JSON.parse(manifestText());
  delete ohne.commit;
  assert.equal(pruefe(angebot(JSON.stringify(ohne))).ok, false);
  assert.equal(pruefe(angebot("[1,2]")).ok, false);
  assert.equal(pruefe(angebot("kein json")).ok, false);
});

test("Manifest: höchstens 4 KB, ohne BOM, Text als Eingabe", () => {
  const gross = manifestText({ commit: "a".repeat(40) }).replace("{", `{${" ".repeat(4100)}`);
  assert.equal(pruefe(angebot(gross)).ok, false);
  const bom = `\uFEFF${manifestText()}`;
  assert.equal(pruefe(angebot(bom)).ok, false);
  assert.equal(pruefe({ manifest: { v: 1 }, signatur: angebot().signatur }).ok, false);
});

test("eigene Version unbekannt: abgelehnt", () => {
  assert.equal(pruefe(angebot(), "").ok, false);
  assert.equal(pruefe(angebot(), "0.3.0-dev").ok, false);
});

test("Vertrag mit dem Server: Beispieldatei testdaten/update ist gültig signiert", () => {
  const ordner = path.join(__dirname, "testdaten", "update");
  const manifest = fs.readFileSync(path.join(ordner, "aktuell.json"), "utf8");
  const signatur = fs.readFileSync(path.join(ordner, "aktuell.json.sig"), "utf8");
  const schluessel = schluesselAusListe(JSON.parse(fs.readFileSync(path.join(ordner, "update-schluessel.json"), "utf8")));
  const e = pruefeManifest({ manifest, signatur, schluessel, aktuelleVersion: "0.2.0" });
  assert.equal(e.ok, true, e.grund);
  assert.equal(e.manifest.version, "0.3.0");
  // Die Signatur passt nie zum festen Schlüssel der App: Testdaten taugen nicht als Update
  assert.equal(pruefeManifest({ manifest, signatur, schluessel: schluesselAusListe(require("./update-schluessel.json")), aktuelleVersion: "0.2.0" }).ok, false);
});

// ---------- Ablauf: prüfen, Rückfrage, laden, starten ----------
function ablauf(opt = {}) {
  const spur = [];
  const updater = erzeugeUpdater({
    schluessel: SCHLUESSEL,
    version: opt.version ?? "0.2.0",
    installiert: opt.installiert ?? true,
    fragen: async (m) => {
      spur.push(`fragen ${m.version}`);
      return opt.antwort ?? true;
    },
    laden: async ({ manifest, token }) => {
      spur.push(`laden ${manifest.version} ${token === TOKEN ? "token" : "?"}`);
      if (opt.ladeFehler) throw opt.ladeFehler;
      return "C:\\x\\WAIS-Setup-0.3.0.exe";
    },
    starten: async (datei) => spur.push(`starten ${datei}`),
    beenden: () => spur.push("beenden"),
    log: (t) => spur.push(`log ${t}`),
  });
  return { updater, spur, aktionen: () => spur.filter((s) => !s.startsWith("log ")) };
}

test("pruefen: liefert nur Version und neuer, nie Inhalte; Fehler mit festem Satz", () => {
  const { updater } = ablauf();
  assert.deepEqual(updater.pruefen(angebot()), { ok: true, version: "0.3.0", neuer: true });
  assert.deepEqual(updater.pruefen(angebot({}, FREMD.privateKey)), { ok: false, text: TEXT.nichtBestaetigt });
  assert.deepEqual(updater.pruefen(null), { ok: false, text: TEXT.nichtBestaetigt });
});

test("installieren: gültig, Rückfrage ja, laden, starten, beenden", async () => {
  const { updater, aktionen } = ablauf();
  assert.deepEqual(await updater.installieren({ ...angebot(), token: TOKEN }), { ok: true });
  assert.deepEqual(aktionen(), ["fragen 0.3.0", "laden 0.3.0 token", "starten C:\\x\\WAIS-Setup-0.3.0.exe", "beenden"]);
});

test("Abbruch ohne Rückfrage: falsche Signatur, fremder Schlüssel oder alte Version fragen nie und laden nichts", async () => {
  for (const a of [
    { ...angebot(), signatur: angebot({ version: "0.4.0" }).signatur },
    angebot({}, FREMD.privateKey),
    angebot({ version: "0.2.0" }),
    angebot({ version: "0.1.0" }),
  ]) {
    const { updater, aktionen } = ablauf();
    const e = await updater.installieren({ ...a, token: TOKEN });
    assert.equal(e.ok, false);
    assert.deepEqual(aktionen(), [], JSON.stringify(e));
  }
});

test("Rückfrage verneint: nichts geladen, nichts gestartet", async () => {
  const { updater, aktionen } = ablauf({ antwort: false });
  assert.deepEqual(await updater.installieren({ ...angebot(), token: TOKEN }), { ok: false, abgebrochen: true, text: TEXT.abgebrochen });
  assert.deepEqual(aktionen(), ["fragen 0.3.0"]);
});

test("Entwicklermodus und fehlendes Token: kein Update", async () => {
  const dev = ablauf({ installiert: false });
  assert.deepEqual(await dev.updater.installieren({ ...angebot(), token: TOKEN }), { ok: false, text: TEXT.nurInstalliert });
  assert.deepEqual(dev.aktionen(), []);
  for (const token of ["", "kein token", "a.b", `${"a".repeat(9000)}.b.c`, null]) {
    const { updater, aktionen } = ablauf();
    assert.deepEqual(await updater.installieren({ ...angebot(), token }), { ok: false, text: TEXT.anmeldung });
    assert.deepEqual(aktionen(), []);
  }
});

test("Ladefehler: fester Satz, kein Start; danach ist ein neuer Versuch möglich", async () => {
  const { updater, aktionen } = ablauf({ ladeFehler: new Error("ECONNRESET 192.168.178.136") });
  const e = await updater.installieren({ ...angebot(), token: TOKEN });
  assert.deepEqual(e, { ok: false, text: TEXT.laden });
  assert.deepEqual(aktionen(), ["fragen 0.3.0", "laden 0.3.0 token"]);
  assert.equal((await updater.installieren({ ...angebot(), token: TOKEN })).ok, false);
  assert.equal(aktionen().length, 4); // nicht "läuft bereits"
});

test("nur ein Update gleichzeitig", async () => {
  let freigeben;
  const updater = erzeugeUpdater({
    schluessel: SCHLUESSEL,
    version: "0.2.0",
    installiert: true,
    fragen: () => new Promise((r) => (freigeben = r)),
    laden: async () => "x",
    starten: async () => {},
    beenden: () => {},
  });
  const erst = updater.installieren({ ...angebot(), token: TOKEN });
  assert.deepEqual(await updater.installieren({ ...angebot(), token: TOKEN }), { ok: false, text: TEXT.laeuft });
  freigeben(false);
  assert.equal((await erst).abgebrochen, true);
});

test("das Token steht in keiner Protokollzeile", async () => {
  const { updater, spur } = ablauf({ ladeFehler: new Error(`kaputt ${TOKEN}`) });
  await updater.installieren({ ...angebot(), token: TOKEN });
  await updater.installieren({ ...angebot({}, FREMD.privateKey), token: TOKEN });
  assert.ok(spur.filter((s) => s.startsWith("log ")).length >= 2);
  for (const s of spur) assert.ok(!s.includes(TOKEN), s);
});

// ---------- Laden über die geprüfte Verbindung ----------
function antwort({ status = 200, laenge, teile = [INHALT] } = {}) {
  const strom = new PassThrough();
  strom.statusCode = status;
  strom.headers = laenge === undefined ? {} : { "content-length": String(laenge) };
  setImmediate(() => {
    for (const t of teile) strom.write(t);
    strom.end();
  });
  return strom;
}

function ladeMit(opt = {}) {
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), "wais-update-"));
  fs.writeFileSync(path.join(ordner, "WAIS-Setup-0.1.0.exe"), "alt");
  fs.writeFileSync(path.join(ordner, "fremd.txt"), "bleibt");
  const gesehen = {};
  const manifest = pruefe(angebot(opt.teil)).manifest;
  const p = ladeInstaller({
    manifest,
    token: TOKEN,
    kernUrl: opt.kernUrl ?? "https://192.168.178.136:55444",
    ordner,
    verbinden: async (ziel) => {
      gesehen.ziel = ziel.href;
      if (opt.verbindeFehler) throw opt.verbindeFehler;
      return { destroy: () => (gesehen.zerstoert = true) };
    },
    anfragen: async (ziel, _socket, kopf) => {
      gesehen.kopf = kopf;
      return antwort(opt.antwort);
    },
  });
  return { p, ordner, gesehen };
}

test("ladeInstaller: feste Adresse, Token nur im Kopf, Prüfsumme stimmt, alte Installer weg", async () => {
  const { p, ordner, gesehen } = ladeMit({ antwort: { laenge: INHALT.length, teile: [INHALT.subarray(0, 10), INHALT.subarray(10)] } });
  const datei = await p;
  assert.equal(datei, path.join(ordner, "WAIS-Setup-0.3.0.exe"));
  assert.deepEqual(fs.readFileSync(datei), INHALT);
  assert.equal(gesehen.ziel, "https://192.168.178.136:55444/wamo/api/installer/datei");
  assert.equal(gesehen.kopf.Authorization, `Bearer ${TOKEN}`);
  assert.deepEqual(fs.readdirSync(ordner).sort(), ["WAIS-Setup-0.3.0.exe", "fremd.txt"]);
});

test("ladeInstaller: falsche Prüfsumme, zu viele Bytes, falsche Länge oder Status: Datei weg, Fehler", async () => {
  const faelle = [
    { antwort: { teile: [Buffer.from("anderer Inhalt gleicher Laenge, aber falsch!!")] } },
    { antwort: { teile: [INHALT, Buffer.from("mehr")] } },
    { antwort: { laenge: INHALT.length + 1 } },
    { antwort: { status: 429 } },
    { antwort: { teile: [INHALT.subarray(0, 5)] } },
  ];
  for (const f of faelle) {
    const { p, ordner } = ladeMit(f);
    await assert.rejects(p, (err) => err.name === "UpdateFehler", JSON.stringify(f.antwort));
    assert.deepEqual(fs.readdirSync(ordner), ["fremd.txt"], JSON.stringify(f.antwort));
  }
});

test("ladeInstaller: nur https, Fehler beim Verbinden ohne Anfrage", async () => {
  const http = ladeMit({ kernUrl: "http://localhost:7860" });
  await assert.rejects(http.p, /UpdateFehler|nur https/);
  assert.equal(http.gesehen.ziel, undefined);
  const fehler = ladeMit({ verbindeFehler: new Error("Zertifikat nicht vertraut") });
  await assert.rejects(fehler.p, (err) => err.name === "UpdateFehler");
  assert.equal(fehler.gesehen.kopf, undefined); // kein Kopf, also nie das Token, ohne geprüfte Verbindung
});

// ---------- Verbindung erst prüfen, dann anfragen ----------
function falscheTlsVerbindung(ergebnis) {
  const { EventEmitter } = require("node:events");
  const s = new EventEmitter();
  s.zerstoert = false;
  s.destroy = () => (s.zerstoert = true);
  s.setTimeout = () => {};
  const tlsModul = {
    connect: (opt) => {
      s.opt = opt;
      setImmediate(() => s.emit("secureConnect"));
      return s;
    },
  };
  return { s, verbinden: (ziel) => verbindeGeprueft(ziel, { tlsModul, pruefe: () => ergebnis }) };
}

test("verbindeGeprueft: ohne passende Kette zur WAMO-CA kein Socket, sonst der geprüfte Socket", async () => {
  const ziel = new URL("https://192.168.178.136:55444/wamo/api/installer/datei");
  const nein = falscheTlsVerbindung({ ok: false, grund: "Kette führt nicht zur WAMO-CA" });
  await assert.rejects(nein.verbinden(ziel), /Zertifikat/);
  assert.equal(nein.s.zerstoert, true);
  const ja = falscheTlsVerbindung({ ok: true });
  assert.equal(await ja.verbinden(ziel), ja.s);
  assert.equal(ja.s.opt.rejectUnauthorized, false); // die Kette prüft pruefeSocket, nicht Node
  assert.equal(ja.s.opt.port, 55444);
});
