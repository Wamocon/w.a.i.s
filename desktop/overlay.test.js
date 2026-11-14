// Tests für die Markierungsfenster (overlay.html) ohne den früheren Stimmen-Rand. Ausführen im Ordner desktop/:  npm test
// Quelltext-Prüfung wie in lichtrahmen.test.js: main.js lässt sich ohne electron nicht laden.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

// Zeilenenden vereinheitlicht: Unter Windows liegen die Dateien je nach Git-Einstellung mit CRLF vor
const lies = (datei) => fs.readFileSync(path.join(__dirname, datei), "utf8").replace(/\r\n/g, "\n");

/** Körper einer Funktion function name(...) { ... } bis zur schließenden Klammer in Spalte 0. */
function funktion(js, name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} fehlt`);
  const ende = js.indexOf("\n}\n", start);
  return js.slice(start, ende + 2);
}

/** Körper eines ipcMain-Hörers bis zum ersten "});" am Zeilenanfang. */
function hoerer(js, kanal) {
  const start = js.indexOf(`ipcMain.on("${kanal}"`);
  assert.ok(start >= 0, `Hörer ${kanal} fehlt`);
  return js.slice(start, js.indexOf("\n});", start));
}

// ---------- Kein Kantensaum mehr ----------
test("Kein Kantensaum: kein WebGL-Saum, kein Shader, keine Schleierbreite", () => {
  assert.equal(fs.existsSync(path.join(__dirname, "overlay.js")), false, "overlay.js (Saum mit Shader) ist entfernt");
  const html = lies("overlay.html");
  assert.doesNotMatch(html, /<canvas|overlay\.js|edge/);
  assert.match(html, /<script src="markierung\.js"><\/script>/);
  assert.doesNotMatch(lies("overlay.css"), /canvas/);
  const main = lies("main.js");
  for (const alt of ["veilWidthDip", "WAMO_VEIL_CM", "veil", "uVeil", "getContext(\"webgl\""]) {
    assert.ok(!main.includes(alt), `main.js enthält noch ${alt}`);
  }
  for (const datei of ["markierung.js", "overlay-preload.js", "overlay.html", "overlay.css"]) {
    assert.doesNotMatch(lies(datei), /webgl|gl_FragColor|VEIL/i, datei);
  }
});

test("Kein Kantensaum: Pegel und Stimmfarben erreichen die Markierungsfenster nicht mehr", () => {
  const preload = lies("overlay-preload.js");
  assert.match(preload, /onMarkierung:/);
  assert.doesNotMatch(preload, /onLevels|onFarben|"levels"|"farben"/);
  assert.doesNotMatch(lies("markierung.js"), /onLevels/);
  const main = lies("main.js");
  assert.doesNotMatch(main, /webContents\.send\("levels"/);
  assert.doesNotMatch(main, /webContents\.send\("farben"/);
  assert.doesNotMatch(main, /ipcMain\.on\("farben"/);
  assert.doesNotMatch(main, /checkFarben|checkRgb/);
  // Die Hauptfenster-Brücke reicht keine Farben mehr weiter (die Oberfläche ruft farben nur optional auf) und vom
  // Kanal levels nur noch den Zustand
  const bruecke = lies("preload.js");
  assert.doesNotMatch(bruecke, /farben/);
  assert.match(bruecke, /levels: \(meldung\) => ipcRenderer\.send\("levels", \{ zustand: text\(meldung\?\.zustand\) \}\)/);
});

test("Kein Kantensaum: kein Rand-Haken im Tray und kein Schalter dafür im Hauptprogramm", () => {
  const main = lies("main.js");
  for (const alt of ["borderOn", "randSoll", "randSichtbarkeit", 'label: "Stimmen-Rand"']) {
    assert.ok(!main.includes(alt), `main.js enthält noch ${alt}`);
  }
  const tray = funktion(main, "aktualisiereTray");
  const haken = [...tray.matchAll(/type: "checkbox"/g)];
  assert.equal(haken.length, 1, "nur noch ein Haken im Tray");
  assert.match(tray, /label: "Mit Windows starten",\s*type: "checkbox"/);
  assert.doesNotMatch(tray, /Rand/);
  // Gespeichert wird weiter nur die Betriebsart: ein alter Wert in einstellungen.json bewirkt nichts
  assert.match(funktion(main, "speichereEinstellungen"), /JSON\.stringify\(\{ betriebsart \}/);
  assert.match(funktion(main, "ladeEinstellungen"), /wirksameBetriebsart\(roh\?\.betriebsart, PFADE\)/);
});

// ---------- Sichtbarkeit der Markierungsfenster ----------
test("Markierungsfenster starten ausgeblendet und werden ohne Markierung nie eingeblendet", () => {
  const main = lies("main.js");
  const erzeugen = funktion(main, "createOverlays");
  assert.match(erzeugen, /show: false/);
  assert.doesNotMatch(erzeugen, /showInactive|\.show\(|ready-to-show/);
  assert.match(erzeugen, /markierungen\.vergessen\(\)/);
  // Klicks gehen durch, Inhaltsschutz bleibt, Titel und Datei bleiben (Host-Filter)
  assert.match(erzeugen, /win\.setIgnoreMouseEvents\(true\)/);
  assert.match(erzeugen, /win\.setContentProtection\(true\)/);
  assert.match(erzeugen, /loadFile\(path\.join\(__dirname, "overlay\.html"\)\)/);
  // Eingeblendet wird nur über die Markierungsanzeige (lichtrahmen.js), sonst nirgends im Hauptprogramm
  const ausserhalbLive = main.replace(funktion(main, "zeigeLiveHinweise"), "");
  assert.doesNotMatch(ausserhalbLive, /showInactive/);
});

test("Markierung: zeigen nur über die Anzeige, ohne Treffer und bei Vollbild oder Ruhe ausblenden", () => {
  const main = lies("main.js");
  const koerper = hoerer(main, "markierung");
  assert.match(koerper, /vollbild/);
  assert.match(koerper, /markierungen\.zeigen\(w, /);
  assert.match(koerper, /markierungen\.leeren\(w\)/);
  assert.doesNotMatch(koerper, /webContents\.send/);
  // Zustand der Oberfläche: offene Freigabe oder Gesprächsende blendet sofort aus, Energiesparschutz bleibt
  const levels = hoerer(main, "levels");
  assert.match(levels, /energieschutz\(/);
  assert.match(levels, /ruhezustand\(zustand\)\) markierungen\.alleLeeren\(\)/);
  assert.doesNotMatch(levels, /sample\?\.(user|bot|cut|speaker)/);
  // Vollbild vorne: Markierung sofort weg
  assert.match(main, /vollbild = an;\s*\n\s*if \(an\) markierungen\.alleLeeren\(\)/);
});
