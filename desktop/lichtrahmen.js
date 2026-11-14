// WAMO-Desktop: Prüfung und Umrechnung der Markierung für den Lichtrahmen (reines Node-Modul, ohne electron-Import).
//
// Wenn WAMO am Laptop handelt (Fenster nach vorne, Element klicken, Text setzen, Klicken, Tippen), meldet der Host im
// Ergebnis ein Rechteck (Zielfenster), bei Klicks einen Punkt und den Monitor: nur ganze Zahlen mit Obergrenzen, nie einen
// Titel oder Inhalt. Der Kern gibt sie mit der Gerätekennung des Laptops an die Oberfläche weiter, die Oberfläche über die
// Brücke window.wamoDesktop.markierung an main.js. Hier wird noch einmal streng geprüft, entschieden, OB auf diesem Laptop
// gezeichnet wird (nur wenn er der ist, der handelt), und von Bildschirmpixeln in Fensterkoordinaten der Markierungsfenster
// umgerechnet. Gezeichnet wird in overlay.html (markierung.js). Die Markierungsfenster (je Monitor eines) sind nur sichtbar,
// solange sie eine Markierung zeigen (erzeugeMarkierungsAnzeige).
"use strict";

const { ABBLENDEN_MS, HALTEN_MS, WELLE_MS } = require("./markierung");

// So lange bleibt ein Markierungsfenster nach der letzten Markierung sichtbar: bis Rahmen (halten und abblenden) und Welle
// verschwunden sind, dazu ein kleiner Puffer, damit das Ausblenden nie in das Abblenden fällt
const SICHTBAR_MS = Math.max(HALTEN_MS + ABBLENDEN_MS, WELLE_MS) + 150;

const POS_MIN = -32768; // Bildschirmpixel, wie host/windows_control.py (Windows rechnet Koordinaten mit 16 Bit)
const POS_MAX = 32767;
const GROESSE_MAX = 32768;
const ARTEN = ["fokus", "klick", "text", "tasten", "scrollen"];
const RE_KENNUNG = /^pc-[a-z0-9]+(?:-[a-z0-9]+)*$/; // wie geraet.js (devices_kennung_chk)
const MAX_KENNUNG = 23;
const RE_RECHNER = /^[A-Za-z0-9._-]{1,63}$/;
const ZUSTAENDE_OHNE_RAHMEN = new Set(["approval", "offline"]); // offene Freigabe oder kein Gespräch: kein Rahmen

const ganz = (v) => typeof v === "number" && Number.isInteger(v);
const pos = (v) => ganz(v) && v >= POS_MIN && v <= POS_MAX;

/** { x, y, b, h } aus genau diesen ganzen Zahlen innerhalb der Grenzen, sonst null. */
function pruefeRechteck(r) {
  if (!r || typeof r !== "object" || Array.isArray(r)) return null;
  const { x, y, b, h } = r;
  if (!pos(x) || !pos(y)) return null;
  if (!ganz(b) || !ganz(h) || b < 1 || h < 1 || b > GROESSE_MAX || h > GROESSE_MAX) return null;
  return { x, y, b, h };
}

/** { x, y } aus ganzen Zahlen innerhalb der Grenzen, sonst null. */
function pruefePunkt(p) {
  if (!p || typeof p !== "object" || Array.isArray(p) || !pos(p.x) || !pos(p.y)) return null;
  return { x: p.x, y: p.y };
}

/**
 * Markierung aus der Oberfläche prüfen. Nur die festen Felder werden übernommen (Zusatzfelder fallen weg); ungültig
 * heißt null. geraet: Kennung des Laptops oder null (lokaler Kern); rechner: Rechnername oder null.
 */
function pruefeMarkierung(roh) {
  if (!roh || typeof roh !== "object" || Array.isArray(roh)) return null;
  if (!ARTEN.includes(roh.art)) return null;
  const fenster = pruefeRechteck(roh.fenster);
  const monitor = pruefeRechteck(roh.monitor);
  if (!fenster || !monitor) return null;
  let geraet = null;
  if (roh.geraet !== null && roh.geraet !== undefined) {
    if (typeof roh.geraet !== "string" || roh.geraet.length > MAX_KENNUNG || !RE_KENNUNG.test(roh.geraet)) return null;
    geraet = roh.geraet;
  }
  let rechner = null;
  if (roh.rechner !== null && roh.rechner !== undefined) {
    if (typeof roh.rechner !== "string" || !RE_RECHNER.test(roh.rechner)) return null;
    rechner = roh.rechner;
  }
  const m = { art: roh.art, geraet, rechner, fenster, monitor };
  if (roh.art === "klick" && roh.punkt !== undefined && roh.punkt !== null) {
    const punkt = pruefePunkt(roh.punkt);
    if (punkt) m.punkt = punkt; // ein ungültiger Punkt lässt nur die Welle weg, nicht den Rahmen
  }
  return m;
}

/**
 * Soll auf DIESEM Laptop gezeichnet werden? Nur wenn er der ist, der handelt:
 *  - mit Gerätekennung (Tunnel je Gerät): nur bei genau der eigenen Kennung (geraet.json); ohne eigene Kennung nie;
 *  - ohne Kennung (lokaler Kern oder alter Tunnel): nur bei gleichem Rechnernamen; ohne Namen nie (im Zweifel kein Rahmen).
 * kontext: { eigeneKennung, hostname }.
 */
function sollZeichnen(m, { eigeneKennung = null, hostname = "" } = {}) {
  if (!m) return false;
  if (m.geraet !== null) return typeof eigeneKennung === "string" && m.geraet === eigeneKennung;
  if (m.rechner !== null) return String(hostname).toLowerCase() === m.rechner.toLowerCase();
  return false;
}

/** Kann in der Oberfläche der Rahmen gerade nicht stehen? (offene Freigabe, kein Gespräch) */
function ruhezustand(zustand) {
  return ZUSTAENDE_OHNE_RAHMEN.has(zustand);
}

function schnitt(a, b) {
  const links = Math.max(a.x, b.x);
  const oben = Math.max(a.y, b.y);
  const rechts = Math.min(a.x + a.b, b.x + b.b);
  const unten = Math.min(a.y + a.h, b.y + b.h);
  return rechts > links && unten > oben ? { x: links, y: oben, b: rechts - links, h: unten - oben } : null;
}

/**
 * Markierung in Fensterkoordinaten der Markierungsfenster umrechnen. screenApi: electron.screen (screenToDipRect,
 * screenToDipPoint); rechtecke: Bereiche der Markierungsfenster in DIP (getBounds). Rückgabe: je Markierungsfenster mit
 * Treffer { index, fenster, punkt? } in Koordinaten dieses Fensters. Schlägt die Umrechnung fehl, wird nichts gezeichnet.
 */
function fuerRandFenster(m, screenApi, rechtecke) {
  let dipFenster;
  let dipPunkt = null;
  try {
    // Das Fenster ist auf den Monitor zugeschnitten, damit die Umrechnung genau einen Monitor betrifft
    const beschnitten = schnitt(m.fenster, m.monitor);
    if (!beschnitten) return [];
    const r = screenApi.screenToDipRect(null, { x: beschnitten.x, y: beschnitten.y, width: beschnitten.b, height: beschnitten.h });
    dipFenster = { x: r.x, y: r.y, b: r.width, h: r.height };
    if (m.punkt) {
      const p = screenApi.screenToDipPoint({ x: m.punkt.x, y: m.punkt.y });
      dipPunkt = { x: p.x, y: p.y };
    }
  } catch {
    return [];
  }
  const werte = [dipFenster.x, dipFenster.y, dipFenster.b, dipFenster.h, ...(dipPunkt ? [dipPunkt.x, dipPunkt.y] : [])];
  if (!werte.every((v) => Number.isFinite(v)) || dipFenster.b <= 0 || dipFenster.h <= 0) return [];
  const aus = [];
  rechtecke.forEach((rand, index) => {
    const t = schnitt(dipFenster, { x: rand.x, y: rand.y, b: rand.width, h: rand.height });
    if (!t) return;
    const eintrag = {
      index,
      fenster: { x: Math.round(t.x - rand.x), y: Math.round(t.y - rand.y), b: Math.round(t.b), h: Math.round(t.h) },
    };
    if (dipPunkt && dipPunkt.x >= rand.x && dipPunkt.x < rand.x + rand.width && dipPunkt.y >= rand.y && dipPunkt.y < rand.y + rand.height) {
      eintrag.punkt = { x: Math.round(dipPunkt.x - rand.x), y: Math.round(dipPunkt.y - rand.y) };
    }
    aus.push(eintrag);
  });
  return aus;
}

/**
 * Sichtbarkeit der Markierungsfenster (overlay.html): Ein Fenster ist nur sichtbar, solange es eine Markierung zeigt, sonst
 * ausgeblendet (hide). So liegt kein unsichtbares Fenster dauerhaft über allen Programmen. fenster: BrowserWindow
 * (isDestroyed, isVisible, showInactive, hide, webContents.send). Die Markierung geht vor dem Einblenden an das Fenster, beim
 * Ausblenden geht null hinterher: Ein später wieder eingeblendetes Fenster zeigt nie einen alten Rahmen.
 * setTimeoutFn und clearTimeoutFn nur für Tests.
 */
function erzeugeMarkierungsAnzeige({ dauerMs = SICHTBAR_MS, setTimeoutFn = setTimeout, clearTimeoutFn = clearTimeout } = {}) {
  const timer = new Map(); // sichtbares Fenster -> Timer bis zum Ausblenden

  function ausblenden(win) {
    if (timer.has(win)) clearTimeoutFn(timer.get(win));
    timer.delete(win);
    if (win.isDestroyed()) return;
    win.webContents.send("markierung", null);
    win.hide();
  }

  return {
    /** Markierung zeigen; eine neue Markierung verlängert die Anzeige. */
    zeigen(win, markierung) {
      if (win.isDestroyed()) return;
      if (timer.has(win)) clearTimeoutFn(timer.get(win));
      win.webContents.send("markierung", markierung);
      if (!win.isVisible()) win.showInactive(); // nie den Fokus nehmen
      timer.set(win, setTimeoutFn(() => ausblenden(win), dauerMs));
    },
    /** Dieses Fenster sofort leeren und ausblenden (nur wenn es gerade etwas zeigt). */
    leeren(win) {
      if (timer.has(win)) ausblenden(win);
    },
    /** Alle Fenster sofort leeren und ausblenden (offene Freigabe, Gesprächsende, Vollbild). */
    alleLeeren() {
      for (const win of [...timer.keys()]) ausblenden(win);
    },
    /** Alle Timer aufheben, bevor die Fenster neu gebaut werden (Bildschirmwechsel). */
    vergessen() {
      for (const t of timer.values()) clearTimeoutFn(t);
      timer.clear();
    },
    istSichtbar: (win) => timer.has(win),
  };
}

module.exports = {
  ARTEN,
  GROESSE_MAX,
  POS_MAX,
  POS_MIN,
  SICHTBAR_MS,
  erzeugeMarkierungsAnzeige,
  fuerRandFenster,
  pruefeMarkierung,
  pruefePunkt,
  pruefeRechteck,
  ruhezustand,
  sollZeichnen,
};
