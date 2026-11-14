// Tests für den Lichtrahmen (lichtrahmen.js, markierung.js). Ausführen im Ordner desktop/:  npm test
// Ohne electron: der Bildschirm ist eine Attrappe.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const {
  SICHTBAR_MS,
  erzeugeMarkierungsAnzeige,
  fuerRandFenster,
  pruefeMarkierung,
  pruefePunkt,
  pruefeRechteck,
  ruhezustand,
  sollZeichnen,
} = require("./lichtrahmen");
const { ABBLENDEN_MS, HALTEN_MS, WELLE_ABSTAND_MS, WELLE_MS, rahmenGeometrie, welleGeometrie } = require("./markierung");

const FENSTER = { x: 100, y: 50, b: 800, h: 600 };
const MONITOR = { x: 0, y: 0, b: 1920, h: 1080 };
const gut = (extra = {}) => ({ art: "klick", geraet: "pc-wmc-laptop", rechner: "WMC-PC", fenster: FENSTER, monitor: MONITOR, ...extra });

// ---------- Zahlenprüfung ----------
test("Rechteck: nur ganze Zahlen innerhalb der Grenzen", () => {
  assert.deepEqual(pruefeRechteck(FENSTER), FENSTER);
  assert.deepEqual(pruefeRechteck({ x: -1920, y: -200, b: 1920, h: 1080 }), { x: -1920, y: -200, b: 1920, h: 1080 });
  const schlecht = [
    { ...FENSTER, x: 1.5 }, { ...FENSTER, y: "1" }, { ...FENSTER, b: 0 }, { ...FENSTER, h: -3 }, { ...FENSTER, b: NaN },
    { ...FENSTER, x: Infinity }, { ...FENSTER, x: 40000 }, { ...FENSTER, y: -40000 }, { ...FENSTER, b: 40000 },
    { ...FENSTER, h: null }, { x: 1, y: 2, b: 3 }, null, undefined, "text", 42, [], [1, 2, 3, 4],
    { ...FENSTER, x: true }, { ...FENSTER, x: 1n },
  ];
  for (const r of schlecht) assert.equal(pruefeRechteck(r), null, JSON.stringify(r, (_k, v) => (typeof v === "bigint" ? "big" : v)));
});

test("Punkt: nur ganze Zahlen innerhalb der Grenzen", () => {
  assert.deepEqual(pruefePunkt({ x: 5, y: -7, extra: 1 }), { x: 5, y: -7 });
  for (const p of [{ x: 1.2, y: 0 }, { x: "1", y: 0 }, { x: 0 }, { x: 40000, y: 0 }, { x: NaN, y: 0 }, null, [], "x"]) {
    assert.equal(pruefePunkt(p), null);
  }
});

test("Markierung: nur feste Felder, Zusatzfelder fallen weg, nie Titel oder Inhalt", () => {
  const m = pruefeMarkierung({ ...gut({ punkt: { x: 300, y: 200 }, titel: "Kundenliste", text: "Passwort" }) });
  assert.deepEqual(Object.keys(m).sort(), ["art", "fenster", "geraet", "monitor", "punkt", "rechner"]);
  assert.ok(!JSON.stringify(m).includes("Kundenliste") && !JSON.stringify(m).includes("Passwort"));
});

test("Markierung: ungültige Art, Kennung, Rechnername oder Rechtecke ergeben null", () => {
  for (const kaputt of [
    { art: "loeschen" }, { art: 5 }, { geraet: "PC-1" }, { geraet: "pc-" }, { geraet: "pc-a b" }, { geraet: "pc-" + "a".repeat(30) },
    { geraet: 42 }, { rechner: "böse; name" }, { rechner: "" }, { rechner: "x".repeat(64) }, { fenster: null }, { monitor: { x: 0 } },
    { fenster: { ...FENSTER, b: 0 } },
  ]) {
    assert.equal(pruefeMarkierung(gut(kaputt)), null, JSON.stringify(kaputt));
  }
  for (const nichts of [null, undefined, "x", 5, [], true]) assert.equal(pruefeMarkierung(nichts), null);
});

test("Markierung: ein ungültiger Punkt lässt nur die Welle weg, der Punkt gilt nur bei Klicks", () => {
  assert.equal(pruefeMarkierung(gut({ punkt: { x: 1.5, y: 2 } })).punkt, undefined);
  assert.equal(pruefeMarkierung(gut({ art: "text", punkt: { x: 1, y: 2 } })).punkt, undefined);
  assert.deepEqual(pruefeMarkierung(gut({ punkt: { x: 1, y: 2 } })).punkt, { x: 1, y: 2 });
});

test("Markierung: ohne Kennung oder Rechnername sind null erlaubt", () => {
  const m = pruefeMarkierung(gut({ geraet: null, rechner: null }));
  assert.equal(m.geraet, null);
  assert.equal(m.rechner, null);
  assert.equal(pruefeMarkierung({ art: "fokus", fenster: FENSTER, monitor: MONITOR }).geraet, null);
});

// ---------- Gerätekennung: nur der Laptop, der handelt, zeichnet ----------
test("kein Rahmen bei fremder Gerätekennung", () => {
  const m = pruefeMarkierung(gut({ geraet: "pc-anderer" }));
  assert.equal(sollZeichnen(m, { eigeneKennung: "pc-wmc-laptop", hostname: "WMC-PC" }), false);
});

test("Rahmen bei eigener Gerätekennung", () => {
  const m = pruefeMarkierung(gut());
  assert.equal(sollZeichnen(m, { eigeneKennung: "pc-wmc-laptop", hostname: "ANDERS" }), true);
});

test("mit Gerätekennung und ohne eigene Kennung zeichnet kein Laptop", () => {
  const m = pruefeMarkierung(gut());
  for (const eigene of [null, undefined, "", 42]) {
    assert.equal(sollZeichnen(m, { eigeneKennung: eigene, hostname: "WMC-PC" }), false);
  }
});

test("ohne Gerätekennung entscheidet der Rechnername, ohne ihn zeichnet kein Laptop", () => {
  const mitName = pruefeMarkierung(gut({ geraet: null }));
  assert.equal(sollZeichnen(mitName, { hostname: "wmc-pc" }), true);
  assert.equal(sollZeichnen(mitName, { hostname: "ANDERER-PC" }), false);
  const ohneName = pruefeMarkierung(gut({ geraet: null, rechner: null }));
  assert.equal(sollZeichnen(ohneName, { hostname: "WMC-PC" }), false);
  assert.equal(sollZeichnen(null, {}), false);
});

test("offene Freigabe und kein Gespräch: kein Rahmen", () => {
  assert.equal(ruhezustand("approval"), true);
  assert.equal(ruhezustand("offline"), true);
  for (const z of ["idle", "acting", "thinking", "speaking", "listening"]) assert.equal(ruhezustand(z), false);
});

// ---------- Umrechnung auf die Markierungsfenster ----------
/** Bildschirm mit Skalierung 1,25 (Bildschirmpixel = DIP * 1,25), links daneben ein zweiter ohne Skalierung. */
function bildschirm(faktor = 1) {
  return {
    screenToDipRect: (_fenster, r) => ({ x: r.x / faktor, y: r.y / faktor, width: r.width / faktor, height: r.height / faktor }),
    screenToDipPoint: (p) => ({ x: p.x / faktor, y: p.y / faktor }),
  };
}
const RAND = [{ x: 0, y: 0, width: 1536, height: 864 }];

test("Umrechnung: Bildschirmpixel werden DIP in Koordinaten des Markierungsfensters", () => {
  const m = pruefeMarkierung(gut({ punkt: { x: 500, y: 400 } }));
  const aus = fuerRandFenster(m, bildschirm(1.25), RAND);
  assert.equal(aus.length, 1);
  assert.deepEqual(aus[0].fenster, { x: 80, y: 40, b: 640, h: 480 });
  assert.deepEqual(aus[0].punkt, { x: 400, y: 320 });
});

test("Umrechnung: ein Fenster auf dem zweiten Monitor trifft nur dessen Markierungsfenster", () => {
  const zwei = [{ x: 0, y: 0, width: 1920, height: 1080 }, { x: 1920, y: 0, width: 1920, height: 1080 }];
  const m = pruefeMarkierung(gut({ fenster: { x: 2000, y: 100, b: 500, h: 400 }, monitor: { x: 1920, y: 0, b: 1920, h: 1080 },
    punkt: { x: 2100, y: 200 } }));
  const aus = fuerRandFenster(m, bildschirm(1), zwei);
  assert.deepEqual(aus.map((a) => a.index), [1]);
  assert.deepEqual(aus[0].fenster, { x: 80, y: 100, b: 500, h: 400 });
  assert.deepEqual(aus[0].punkt, { x: 180, y: 200 });
});

test("Umrechnung: zu großes Fenster wird auf den Monitor zugeschnitten", () => {
  const m = pruefeMarkierung(gut({ fenster: { x: -50, y: -50, b: 3000, h: 2000 } }));
  const aus = fuerRandFenster(m, bildschirm(1), [{ x: 0, y: 0, width: 1920, height: 1080 }]);
  assert.deepEqual(aus[0].fenster, { x: 0, y: 0, b: 1920, h: 1080 });
});

test("Umrechnung: Fehler der Bildschirm-Schnittstelle oder unsinnige Werte zeichnen nichts", () => {
  const m = pruefeMarkierung(gut());
  assert.deepEqual(fuerRandFenster(m, { screenToDipRect: () => { throw new Error("weg"); }, screenToDipPoint: () => ({}) }, RAND), []);
  assert.deepEqual(fuerRandFenster(m, { screenToDipRect: () => ({ x: NaN, y: 0, width: 10, height: 10 }) }, RAND), []);
  assert.deepEqual(fuerRandFenster(m, { screenToDipRect: () => ({ x: 0, y: 0, width: 0, height: 10 }) }, RAND), []);
  const ausserhalb = pruefeMarkierung(gut({ fenster: { x: 5000, y: 0, b: 100, h: 100 } }));
  assert.deepEqual(fuerRandFenster(ausserhalb, bildschirm(1), RAND), []);
});

// ---------- Zeichnen (markierung.js, ohne DOM) ----------
test("Geometrie im Markierungsfenster: einpassen, winzige und ungültige Rechtecke weglassen", () => {
  assert.deepEqual(rahmenGeometrie({ x: 10, y: 20, b: 300, h: 200 }, 1920, 1080), { x: 10, y: 20, b: 300, h: 200 });
  assert.deepEqual(rahmenGeometrie({ x: -20, y: -20, b: 3000, h: 2000 }, 1920, 1080), { x: 0, y: 0, b: 1920, h: 1080 });
  assert.equal(rahmenGeometrie({ x: 0, y: 0, b: 4, h: 400 }, 1920, 1080), null);
  assert.equal(rahmenGeometrie({ x: 5000, y: 0, b: 100, h: 100 }, 1920, 1080), null);
  assert.equal(rahmenGeometrie({ x: NaN, y: 0, b: 100, h: 100 }, 1920, 1080), null);
  assert.equal(rahmenGeometrie(null, 1920, 1080), null);
  assert.deepEqual(welleGeometrie({ x: 5, y: 6 }, 1920, 1080), { x: 5, y: 6 });
  assert.equal(welleGeometrie({ x: 1920, y: 6 }, 1920, 1080), null);
  assert.equal(welleGeometrie({ x: -1, y: 6 }, 1920, 1080), null);
  assert.equal(welleGeometrie(undefined, 1920, 1080), null);
});

test("Zeiten: der Rahmen verschwindet nach kurzer Zeit von selbst, Wellen höchstens etwa 2 je Sekunde", () => {
  assert.ok(HALTEN_MS >= 800 && HALTEN_MS <= 3000);
  assert.ok(ABBLENDEN_MS <= 500);
  assert.ok(WELLE_MS <= 1000);
  assert.ok(WELLE_ABSTAND_MS >= 334); // WCAG 2.3.1: weniger als 3 Blitze je Sekunde
  assert.match(lies("overlay.css"), /transition-duration:\s*120ms/);
});

// ---------- Sichtbarkeit der Markierungsfenster (erzeugeMarkierungsAnzeige) ----------
/** Attrappe eines BrowserWindow: zählt, was mit ihm geschieht, in der Reihenfolge der Aufrufe. */
function fenster() {
  const w = { sichtbar: false, zerstoert: false, spur: [] };
  w.isDestroyed = () => w.zerstoert;
  w.isVisible = () => w.sichtbar;
  w.showInactive = () => {
    w.sichtbar = true;
    w.spur.push("zeigen");
  };
  w.hide = () => {
    w.sichtbar = false;
    w.spur.push("verbergen");
  };
  w.webContents = { send: (kanal, wert) => w.spur.push([kanal, wert]) };
  return w;
}

/** Anzeige mit falschen Timern: uhr.laufen() löst alle noch geplanten aus. */
function anzeige() {
  const geplant = new Map();
  let nr = 0;
  const a = erzeugeMarkierungsAnzeige({
    setTimeoutFn: (fn, ms) => {
      nr += 1;
      geplant.set(nr, { fn, ms });
      return nr;
    },
    clearTimeoutFn: (id) => geplant.delete(id),
  });
  const uhr = {
    geplant,
    laufen() {
      for (const [id, t] of [...geplant]) {
        geplant.delete(id);
        t.fn();
      }
    },
  };
  return { a, uhr };
}

const RAHMEN = { art: "fokus", fenster: { x: 10, y: 20, b: 300, h: 200 } };

test("Markierungsfenster: ohne Markierung bleibt jedes Fenster ausgeblendet", () => {
  const { a } = anzeige();
  const w = fenster();
  a.leeren(w);
  a.alleLeeren();
  assert.deepEqual(w.spur, [], "kein Einblenden und keine Nachricht ohne Markierung");
  assert.equal(w.sichtbar, false);
  assert.equal(a.istSichtbar(w), false);
});

test("Markierungsfenster: mit Markierung sichtbar, die Markierung kommt vor dem Einblenden an", () => {
  const { a, uhr } = anzeige();
  const w = fenster();
  a.zeigen(w, RAHMEN);
  assert.deepEqual(w.spur, [["markierung", RAHMEN], "zeigen"]);
  assert.equal(w.sichtbar, true);
  assert.equal(a.istSichtbar(w), true);
  assert.deepEqual([...uhr.geplant.values()].map((t) => t.ms), [SICHTBAR_MS]);
});

test("Markierungsfenster: nach Ablauf leer und ausgeblendet, ein späteres Einblenden zeigt keinen alten Rahmen", () => {
  const { a, uhr } = anzeige();
  const w = fenster();
  a.zeigen(w, RAHMEN);
  uhr.laufen();
  assert.deepEqual(w.spur, [["markierung", RAHMEN], "zeigen", ["markierung", null], "verbergen"]);
  assert.equal(w.sichtbar, false);
  assert.equal(a.istSichtbar(w), false);
  assert.equal(uhr.geplant.size, 0);
});

test("Markierungsfenster: eine neue Markierung verlängert die Anzeige, ohne erneut einzublenden", () => {
  const { a, uhr } = anzeige();
  const w = fenster();
  a.zeigen(w, RAHMEN);
  const zweite = { ...RAHMEN, art: "klick", punkt: { x: 50, y: 60 } };
  a.zeigen(w, zweite);
  assert.deepEqual(w.spur, [["markierung", RAHMEN], "zeigen", ["markierung", zweite]]);
  assert.equal(uhr.geplant.size, 1, "der erste Timer ist aufgehoben");
  uhr.laufen();
  assert.equal(w.sichtbar, false);
});

test("Markierungsfenster: leeren und alleLeeren blenden sofort aus, nur sichtbare Fenster bekommen Nachrichten", () => {
  const { a, uhr } = anzeige();
  const eins = fenster();
  const zwei = fenster();
  const drei = fenster();
  a.zeigen(eins, RAHMEN);
  a.zeigen(zwei, RAHMEN);
  a.leeren(eins);
  assert.equal(eins.sichtbar, false);
  assert.deepEqual(eins.spur.slice(-2), [["markierung", null], "verbergen"]);
  a.alleLeeren();
  assert.equal(zwei.sichtbar, false);
  assert.deepEqual(drei.spur, []);
  assert.equal(uhr.geplant.size, 0);
  const vorher = eins.spur.length;
  a.leeren(eins); // schon leer: nichts mehr
  assert.equal(eins.spur.length, vorher);
});

test("Markierungsfenster: zerstörte Fenster werden übersprungen, vergessen hebt alle Timer auf", () => {
  const { a, uhr } = anzeige();
  const tot = fenster();
  tot.zerstoert = true;
  a.zeigen(tot, RAHMEN);
  assert.deepEqual(tot.spur, []);
  const w = fenster();
  a.zeigen(w, RAHMEN);
  w.zerstoert = true; // Bildschirmwechsel: Fenster weg, bevor der Timer läuft
  uhr.laufen();
  assert.deepEqual(w.spur, [["markierung", RAHMEN], "zeigen"]);
  const neu = fenster();
  a.zeigen(neu, RAHMEN);
  a.vergessen();
  assert.equal(uhr.geplant.size, 0);
  assert.equal(a.istSichtbar(neu), false);
});

test("Markierungsfenster: sichtbar, bis Rahmen und Welle ganz verschwunden sind, und nicht viel länger", () => {
  assert.ok(SICHTBAR_MS >= HALTEN_MS + ABBLENDEN_MS);
  assert.ok(SICHTBAR_MS >= WELLE_MS);
  assert.ok(SICHTBAR_MS <= HALTEN_MS + ABBLENDEN_MS + 500);
});

test("Markierungsfenster sind aus Bildschirmfotos ausgenommen und main.js merkt den Bereich je Monitor", () => {
  const js = lies("main.js");
  assert.match(js, /win\.setContentProtection\(true\)/);
  assert.match(js, /win\.wamoBereich = display\.bounds/);
});

// ---------- Markierungsfenster: klick-durchlässig, WMC-Rot, reduzierte Bewegung (Quelltext-Prüfung) ----------
const lies = (datei) => fs.readFileSync(path.join(__dirname, datei), "utf8");

test("overlay.html und overlay.css: nicht anklickbar, WMC-Rot, respektiert prefers-reduced-motion", () => {
  const html = lies("overlay.html");
  const css = lies("overlay.css");
  assert.match(css, /pointer-events:\s*none/);
  assert.match(css, /#F40E0E/i);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(html, /<title>WAMO Stimmen-Rand<\/title>/); // Namensvertrag
  assert.doesNotMatch(html, /<script>[^<]/); // keine Inline-Skripte (CSP script-src 'self')
  assert.doesNotMatch(html, /<style>|unsafe-inline/); // Stil nur aus der Datei
});

test("markierung.js: berücksichtigt reduzierte Bewegung und räumt bei null sofort auf", () => {
  const js = lies("markierung.js");
  assert.match(js, /prefers-reduced-motion/);
  assert.match(js, /alleWeg\(\); \/\/ null/);
});

test("main.js: Markierungen nur von der eigenen Oberfläche, ohne Vollbild und ohne offene Freigabe", () => {
  const js = lies("main.js");
  const start = js.indexOf('ipcMain.on("markierung"');
  assert.ok(start > 0);
  const koerper = js.slice(start, js.indexOf("});", start));
  assert.ok(koerper.indexOf("fromMainUi(event)") > 0 && koerper.indexOf("fromMainUi(event)") < koerper.indexOf("pruefeMarkierung"));
  assert.match(koerper, /if \(vollbild \|\| ruhezustand\(letzterZustand\)\) return;/);
  assert.match(koerper, /sollZeichnen\(/);
});

test("preload.js: die Brücke reicht nur Zahlen und Text weiter", () => {
  const js = lies("preload.js");
  assert.match(js, /markierung: \(m\) => ipcRenderer\.send\("markierung", schmaleMarkierung\(m\)\)/);
  assert.ok(!/\btitel\b/i.test(js.slice(js.indexOf("function schmaleMarkierung"), js.indexOf("function schmaleAntwort") + 1)));
});
