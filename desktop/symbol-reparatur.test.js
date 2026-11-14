// Tests für "Taskleisten-Symbol reparieren" (symbol-reparatur.js und scripts/wamo-symbol-reparieren.ps1).
// Ausführen im Ordner desktop/:  npm test
"use strict";

const assert = require("node:assert/strict");
const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { MENUE_TEXT, SKRIPT_NAME, aufruf, auswerten, frageDialog, symbolReparieren } = require("./symbol-reparatur");
const { powershellPfad } = require("./vollbild");

const SKRIPT = path.join(__dirname, "..", "scripts", SKRIPT_NAME);
const RESSOURCEN = "C:\\Users\\Max Muster\\AppData\\Local\\Programs\\wamo-desktop\\resources";
const PS = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";

/** Falsche Umgebung für symbolReparieren: merkt sich Fragen, Aufrufe und Meldungen. */
function umgebung({ antwort = 0, stdout = "", fehler = null, plattform = "win32" } = {}) {
  const u = { fragen: [], aufrufe: [], meldungen: [], log: [] };
  u.opt = {
    plattform,
    ressourcen: RESSOURCEN,
    powershell: PS,
    fragen: async (d) => {
      u.fragen.push(d);
      return { response: antwort };
    },
    ausfuehren: async (datei, argumente) => {
      u.aufrufe.push([datei, argumente]);
      if (fehler) throw fehler;
      return { stdout };
    },
    melden: async (m) => u.meldungen.push(m),
    log: (t) => u.log.push(t),
  };
  return u;
}

test("Die Rückfrage nennt, was passiert, und Abbrechen ist die Vorgabe", () => {
  const d = frageDialog();
  assert.deepEqual(d.buttons, ["Reparieren", "Abbrechen"]);
  assert.equal(d.defaultId, 1);
  assert.equal(d.cancelId, 1);
  assert.match(d.detail, /Explorer/);
  assert.match(d.detail, /Taskleiste/);
  assert.match(d.detail, /Caches/);
  assert.match(d.detail, /\*\.db/);
  assert.doesNotMatch(`${d.message} ${d.detail}`, / - | – | — /, "keine Gedankenstriche");
  assert.equal(MENUE_TEXT, "Taskleisten-Symbol reparieren …");
});

test("Aufruf: Skript aus resources\\scripts, ohne Profil, ohne Rückfrage im Skript (die App fragt selbst)", () => {
  assert.deepEqual(aufruf({ ressourcen: RESSOURCEN, powershell: PS }), {
    datei: PS,
    argumente: ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path.join(RESSOURCEN, "scripts", SKRIPT_NAME), "-Bestaetigt"],
  });
});

test("Abbrechen: kein Skript, keine Meldung", async () => {
  const u = umgebung({ antwort: 1 });
  assert.equal(await symbolReparieren(u.opt), "abgebrochen");
  assert.equal(u.fragen.length, 1);
  assert.equal(u.aufrufe.length, 0);
  assert.equal(u.meldungen.length, 0);
});

test("Nicht Windows: nichts gefragt, nichts ausgeführt", async () => {
  const u = umgebung({ plattform: "linux" });
  assert.equal(await symbolReparieren(u.opt), "nicht-windows");
  assert.equal(u.fragen.length + u.aufrufe.length + u.meldungen.length, 0);
});

test("Bestätigt und erfolgreich: Skript läuft einmal, Meldung nennt die gelöschten Dateien", async () => {
  const stdout = 'Hinweis\r\n{"ergebnis":"repariert","geloescht":["a.db","b.db"],"gesperrt":[],"explorer":"neu gestartet"}\r\n';
  const u = umgebung({ stdout });
  assert.equal(await symbolReparieren(u.opt), "repariert");
  assert.equal(u.aufrufe.length, 1);
  assert.equal(u.meldungen.length, 1);
  assert.equal(u.meldungen[0].type, "info");
  assert.match(u.meldungen[0].message, /2 Dateien/);
});

test("Auswertung: gesperrte Dateien, fehlende Ausgabe und Fehler des Skripts", () => {
  const teil = auswerten({ stdout: '{"ergebnis":"teilweise","geloescht":["a.db"],"gesperrt":["b.db"],"explorer":"neu gestartet"}' });
  assert.equal(teil.ok, false);
  assert.match(teil.meldung, /b\.db/);
  assert.match(teil.meldung, /neu anmelden|neu starten/);
  const leer = auswerten({ stdout: "" });
  assert.equal(leer.ok, false);
  const kaputt = auswerten({ fehler: Object.assign(new Error("x"), { code: 3 }), stdout: "" });
  assert.equal(kaputt.ok, false);
  assert.match(kaputt.meldung, /fehlgeschlagen/);
  // Bei einem Fehlercode zählt die JSON-Zeile trotzdem, wenn das Skript sie geschrieben hat
  const mitCode = auswerten({ fehler: Object.assign(new Error("x"), { code: 2 }), stdout: '{"ergebnis":"teilweise","geloescht":[],"gesperrt":["a.db"],"explorer":"neu gestartet"}' });
  assert.match(mitCode.meldung, /a\.db/);
});

test("Fehler beim Ausführen: kein Absturz, Warnmeldung und Logeintrag", async () => {
  const u = umgebung({ fehler: Object.assign(new Error("kaputt"), { code: 1 }) });
  assert.equal(await symbolReparieren(u.opt), "fehler");
  assert.equal(u.meldungen.length, 1);
  assert.equal(u.meldungen[0].type, "warning");
  assert.equal(u.log.length, 1);
});

test("main.js bietet die Reparatur im Tray an (nur Windows) und ruft symbolReparieren mit dialog und Skriptordner auf", () => {
  const main = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  assert.match(main, /label: MENUE_TEXT,\s*\n\s*visible: process\.platform === "win32",/);
  assert.match(main, /symbolReparieren\(\{/);
  assert.match(main, /ressourcen: PFADE\.ressourcen,/);
  assert.match(main, /fragen: \(d\) => dialog\.showMessageBox\(d\),/);
});

// Das Skript selbst, nur unter Windows: Probelauf und Löschen in einem eigenen Ordner, ohne den Explorer anzufassen
const nurWindows = process.platform === "win32" ? test : test.skip;

function tempCaches() {
  const basis = fs.mkdtempSync(path.join(os.tmpdir(), "wamo-symbol-"));
  const caches = path.join(basis, "Caches");
  fs.mkdirSync(path.join(caches, "unter"), { recursive: true });
  for (const n of ["cversions.3.db", "{3DA71D5A}.3.ver0x1.db", "bleibt.txt", path.join("unter", "tief.db")]) fs.writeFileSync(path.join(caches, n), "x");
  return { basis, caches };
}

function skript(argumente) {
  return spawnSync(powershellPfad(), ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SKRIPT, ...argumente], {
    encoding: "utf8",
    windowsHide: true,
  });
}

function letzteZeile(text) {
  return JSON.parse(text.trim().split(/\r?\n/).pop());
}

nurWindows("Skript, Probelauf: nennt nur *.db direkt im Ordner und ändert nichts", () => {
  const { basis, caches } = tempCaches();
  try {
    const r = skript(["-Trocken", "-CacheOrdner", caches]);
    assert.equal(r.status, 0, r.stderr);
    const j = letzteZeile(r.stdout);
    assert.equal(j.ergebnis, "trocken");
    assert.deepEqual([...j.geloescht].sort(), ["cversions.3.db", "{3DA71D5A}.3.ver0x1.db"]);
    assert.ok(fs.existsSync(path.join(caches, "cversions.3.db")));
  } finally {
    fs.rmSync(basis, { recursive: true, force: true });
  }
});

nurWindows("Skript: löscht nur *.db direkt im Ordner Caches, alles andere bleibt", () => {
  const { basis, caches } = tempCaches();
  try {
    const r = skript(["-Bestaetigt", "-ExplorerLassen", "-CacheOrdner", caches]);
    assert.equal(r.status, 0, r.stderr);
    const j = letzteZeile(r.stdout);
    assert.equal(j.ergebnis, "repariert");
    assert.equal(j.explorer, "nicht angefasst");
    assert.deepEqual(fs.readdirSync(caches).sort(), ["bleibt.txt", "unter"]);
    assert.ok(fs.existsSync(path.join(caches, "unter", "tief.db")));
  } finally {
    fs.rmSync(basis, { recursive: true, force: true });
  }
});

nurWindows("Skript: ein anderer Ordner als Caches wird abgelehnt, ohne Bestätigung passiert nichts", () => {
  const { basis, caches } = tempCaches();
  try {
    const falsch = skript(["-Bestaetigt", "-ExplorerLassen", "-CacheOrdner", basis]);
    assert.notEqual(falsch.status, 0);
    const ohne = skript(["-ExplorerLassen", "-CacheOrdner", caches]); // -NonInteractive: keine Rückfrage möglich
    assert.notEqual(ohne.status, 0);
    assert.ok(fs.existsSync(path.join(caches, "cversions.3.db")));
  } finally {
    fs.rmSync(basis, { recursive: true, force: true });
  }
});

nurWindows("Skript: Syntax fehlerfrei und ohne Gedankenstriche in den Texten", () => {
  const text = fs.readFileSync(SKRIPT, "utf8");
  assert.ok(text.charCodeAt(0) === 0xfeff, "UTF-8 mit BOM, sonst liest Windows PowerShell 5.1 die Umlaute falsch");
  assert.doesNotMatch(text, / – | — /);
  const befehl = `$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('${SKRIPT.replace(/'/g, "''")}', [ref]$null, [ref]$e); $e.Count`;
  assert.equal(execFileSync(powershellPfad(), ["-NoProfile", "-NonInteractive", "-Command", befehl], { encoding: "utf8", windowsHide: true }).trim(), "0");
});
