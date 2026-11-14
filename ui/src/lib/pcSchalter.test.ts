// Tests für den Schalter "PC-Steuerung" ohne laufendes Gespräch (lib/pcSchalter.ts): gemerkte Rolle je Person, wer den Schalter sieht,
// wann er bedienbar ist, was ein Klick auslöst und wie der Wunsch nach dem stillen Start abläuft (Senden, sobald der PC verbunden ist,
// Hinweis nach der Wartezeit).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HINWEIS_IM_GESPRAECH,
  HINWEIS_NICHT_BESTAETIGT,
  HINWEIS_PC_AUS,
  HINWEIS_PC_GESPERRT,
  HINWEIS_PC_GETRENNT,
  HINWEIS_PC_STILL,
  HINWEIS_STILL_AUS,
  klickWeg,
  pcAdmin,
  PC_VERBINDEN_MS,
  PC_WUNSCH_NEU,
  rolleLesen,
  rolleMerken,
  rolleSchluessel,
  SCHALT_WARTEN_MS,
  schalterAnzeige,
  stillNeinHinweis,
  wunschSchritt,
  type WunschLage,
} from "./pcSchalter.ts";
import { HINWEIS_ANDERES_FENSTER, HINWEIS_ZU_OFT } from "./stillStart.ts";
import { VERBINDUNG_FRIST_MS } from "./verbindungsfrist.ts";

const ID = "0b7f3c1e-2d4a-4c55-9a10-1a2b3c4d5e6f";

function speicher(start: Record<string, string> = {}) {
  const daten = new Map(Object.entries(start));
  return {
    daten,
    getItem: (k: string) => daten.get(k) ?? null,
    setItem: (k: string, v: string) => void daten.set(k, v),
    removeItem: (k: string) => void daten.delete(k),
  };
}

// ---------- Rolle merken ----------
test("die Rolle gilt je Person: Schlüssel nur mit brauchbarer Kennung", () => {
  assert.equal(rolleSchluessel(ID), `wamo.rolle.${ID}`);
  assert.equal(rolleSchluessel(null), null);
  assert.equal(rolleSchluessel("../x"), null);
  assert.equal(rolleSchluessel(""), null);
});

test("gemerkte Rolle: schreiben und lesen, fremde Werte und Fehler zählen als unbekannt", () => {
  const sp = speicher();
  assert.equal(rolleLesen(sp, ID), null);
  assert.equal(rolleMerken(sp, ID, "admin"), true);
  assert.equal(rolleLesen(sp, ID), "admin");
  assert.equal(rolleMerken(sp, ID, "mitglied"), true);
  assert.equal(rolleLesen(sp, ID), "mitglied");
  assert.equal(rolleLesen(speicher({ [`wamo.rolle.${ID}`]: "root" }), ID), null);
  assert.equal(rolleLesen(sp, "anderer-0000"), null);
  assert.equal(rolleLesen(null, ID), null);
  const kaputt = { getItem: () => { throw new Error("gesperrt"); }, setItem: () => { throw new Error("gesperrt"); }, removeItem: () => undefined };
  assert.equal(rolleLesen(kaputt, ID), null);
  assert.equal(rolleMerken(kaputt, ID, "admin"), false);
  assert.equal(rolleMerken(sp, null, "admin"), false);
});

// ---------- Wer sieht den Schalter ----------
test("Admin: die Rolle vom Kern gilt zuerst, ohne Sitzung die gemerkte; Laborkonten nie", () => {
  assert.equal(pcAdmin({ rolleKern: "admin", rolleGemerkt: null, laborKonto: false }), true);
  assert.equal(pcAdmin({ rolleKern: null, rolleGemerkt: "admin", laborKonto: false }), true);
  assert.equal(pcAdmin({ rolleKern: "mitglied", rolleGemerkt: "admin", laborKonto: false }), false);
  assert.equal(pcAdmin({ rolleKern: null, rolleGemerkt: null, laborKonto: false }), false);
  assert.equal(pcAdmin({ rolleKern: "admin", rolleGemerkt: "admin", laborKonto: true }), false);
});

const lage = (p: Partial<Parameters<typeof schalterAnzeige>[0]> = {}): Parameters<typeof schalterAnzeige>[0] => ({
  admin: true,
  serverBrowser: false,
  desktop: true,
  presence: "offline",
  stillErlaubt: true,
  wartet: false,
  ...p,
});

test("Schalter: verborgen ohne Admin, im Browser auf dem Server nur der Hinweis auf die Desktop-App", () => {
  assert.deepEqual(schalterAnzeige(lage({ admin: false })), { art: "verborgen" });
  assert.deepEqual(schalterAnzeige(lage({ serverBrowser: true, desktop: false })), { art: "nur_desktop" });
});

test("Schalter in der Desktop-App: auch ohne Gespräch bedienbar, wenn der stille Start erlaubt ist", () => {
  assert.deepEqual(schalterAnzeige(lage()), { art: "bedienbar", ohneSitzung: true });
  assert.deepEqual(schalterAnzeige(lage({ presence: "connecting" })), { art: "bedienbar", ohneSitzung: true });
  assert.deepEqual(schalterAnzeige(lage({ presence: "idle" })), { art: "bedienbar", ohneSitzung: false });
  assert.deepEqual(schalterAnzeige(lage({ presence: "speaking", desktop: false })), { art: "bedienbar", ohneSitzung: false });
});

test("Schalter ohne Gespräch gesperrt: im normalen Browser wie bisher, in der Desktop-App ohne 'Still starten beim Tippen' mit Hinweis", () => {
  assert.deepEqual(schalterAnzeige(lage({ desktop: false })), { art: "gesperrt", hinweis: HINWEIS_IM_GESPRAECH });
  assert.deepEqual(schalterAnzeige(lage({ stillErlaubt: false })), { art: "gesperrt", hinweis: HINWEIS_STILL_AUS });
  // läuft der Start schon (zum Beispiel per Tippen), genügt der Wunsch: kein zweiter Start, also auch ohne Geräteschalter
  assert.deepEqual(schalterAnzeige(lage({ stillErlaubt: false, presence: "connecting" })), { art: "bedienbar", ohneSitzung: true });
  // ein laufender Wunsch bleibt sichtbar bedienbar (die Komponente zeigt ihn als ausstehend)
  assert.deepEqual(schalterAnzeige(lage({ stillErlaubt: false, wartet: true })), { art: "bedienbar", ohneSitzung: true });
});

// ---------- Klick ----------
const klick = (p: Partial<Parameters<typeof klickWeg>[0]> = {}) =>
  klickWeg({ an: true, online: false, presence: "offline", admin: true, desktop: true, serverBrowser: false, ...p });

test("Klick: mit Sitzung wird gesendet wie bisher, an und aus", () => {
  assert.deepEqual(klick({ online: true, presence: "idle" }), { art: "senden" });
  assert.deepEqual(klick({ an: false, online: true, presence: "idle" }), { art: "senden" });
});

test("Klick ohne Sitzung: 'an' startet still, während des Verbindens genügt der Wunsch, 'aus' tut nichts", () => {
  assert.deepEqual(klick(), { art: "still_starten" });
  assert.deepEqual(klick({ presence: "connecting" }), { art: "wunsch" });
  assert.deepEqual(klick({ an: false }), { art: "nichts" });
});

test("Klick: nie ohne Admin, ohne Sitzung nie im Browser (nur in der Desktop-App)", () => {
  assert.deepEqual(klick({ admin: false }), { art: "nein" });
  assert.deepEqual(klick({ admin: false, online: true, presence: "idle" }), { art: "nein" });
  assert.deepEqual(klick({ desktop: false }), { art: "nein" });
  assert.deepEqual(klick({ serverBrowser: true, desktop: false }), { art: "nein" });
});

test("stiller Start abgelehnt: der Hinweis nennt den Grund", () => {
  assert.equal(stillNeinHinweis("schalter_aus"), HINWEIS_STILL_AUS);
  assert.equal(stillNeinHinweis("uebernommen", HINWEIS_ANDERES_FENSTER), HINWEIS_ANDERES_FENSTER);
  assert.equal(stillNeinHinweis("zu_oft", HINWEIS_ZU_OFT), HINWEIS_ZU_OFT);
  assert.equal(stillNeinHinweis("verdeckt"), HINWEIS_IM_GESPRAECH);
});

// ---------- Ablauf nach dem Klick ----------
const T0 = 1_000_000;
const betrieb = (p: Partial<NonNullable<WunschLage["betrieb"]>> = {}): WunschLage["betrieb"] => ({ pc: "verbindet", pcSteuerung: "aus", ...p });
const lageW = (p: Partial<WunschLage> = {}): WunschLage => ({ jetzt: T0, presence: "idle", betrieb: betrieb(), ...p });

test("Wartezeiten: Verbinden des PCs wie die Verbindungsfrist, Rückmeldung des Kerns wie bisher am Schalter (5 s)", () => {
  assert.equal(PC_VERBINDEN_MS, VERBINDUNG_FRIST_MS);
  assert.equal(SCHALT_WARTEN_MS, 5000);
});

test("Wunsch: während des Verbindens und ohne Betriebsmeldung warten, ohne Frist (die Verbindungsfrist gilt)", () => {
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ presence: "connecting", betrieb: null })), { art: "warten", wunsch: PC_WUNSCH_NEU, frist: null });
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ betrieb: null })), { art: "warten", wunsch: PC_WUNSCH_NEU, frist: null });
});

test("Wunsch: Sitzung weg (Start gescheitert oder beendet) endet still, die Verbindung meldet sich selbst", () => {
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ presence: "offline", betrieb: null })), { art: "ende", hinweis: null });
});

test("Wunsch: PC verbindet noch, dann warten mit Frist ab Sitzungsbeginn", () => {
  const r = wunschSchritt(PC_WUNSCH_NEU, lageW());
  assert.deepEqual(r, { art: "warten", wunsch: { onlineSeit: T0, gesendetSeit: null }, frist: T0 + PC_VERBINDEN_MS });
});

test("Wunsch: sobald der Kern den PC als verbunden meldet, einmal senden, dann auf 'an' warten", () => {
  const w = { onlineSeit: T0, gesendetSeit: null };
  const r = wunschSchritt(w, lageW({ jetzt: T0 + 3000, betrieb: betrieb({ pc: "verbunden" }) }));
  assert.deepEqual(r, { art: "senden", wunsch: { onlineSeit: T0, gesendetSeit: T0 + 3000 }, frist: T0 + 3000 + SCHALT_WARTEN_MS });
  const danach = wunschSchritt({ onlineSeit: T0, gesendetSeit: T0 + 3000 }, lageW({ jetzt: T0 + 3500, betrieb: betrieb({ pc: "verbunden" }) }));
  assert.equal(danach.art, "warten"); // nie ein zweites Mal senden
  assert.deepEqual(
    wunschSchritt({ onlineSeit: T0, gesendetSeit: T0 + 3000 }, lageW({ jetzt: T0 + 3600, betrieb: betrieb({ pc: "verbunden", pcSteuerung: "an" }) })),
    { art: "ende", hinweis: null },
  );
});

test("Wunsch: schon an oder von einer anderen Sitzung belegt endet ohne eigenen Hinweis (Schalter und Toast sagen es)", () => {
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ betrieb: betrieb({ pc: "verbunden", pcSteuerung: "an" }) })), { art: "ende", hinweis: null });
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ betrieb: betrieb({ pc: "verbunden", pcBelegt: true }) })), { art: "ende", hinweis: null });
});

test("Wunsch: ohne PC-Host in dieser Sitzung sofort ein klarer Hinweis", () => {
  assert.deepEqual(wunschSchritt(PC_WUNSCH_NEU, lageW({ betrieb: betrieb({ pc: "aus" }) })), { art: "ende", hinweis: HINWEIS_PC_AUS });
});

test("Wunsch: nach der Wartezeit ein Hinweis, der den Zustand des PCs nennt", () => {
  const w = { onlineSeit: T0, gesendetSeit: null };
  const spaet = T0 + PC_VERBINDEN_MS;
  assert.equal(wunschSchritt(w, lageW({ jetzt: spaet - 1, betrieb: betrieb({ pc: "getrennt" }) })).art, "warten");
  assert.deepEqual(wunschSchritt(w, lageW({ jetzt: spaet, betrieb: betrieb({ pc: "getrennt" }) })), { art: "ende", hinweis: HINWEIS_PC_GETRENNT });
  assert.deepEqual(wunschSchritt(w, lageW({ jetzt: spaet, betrieb: betrieb({ pc: "gesperrt" }) })), { art: "ende", hinweis: HINWEIS_PC_GESPERRT });
  assert.deepEqual(wunschSchritt(w, lageW({ jetzt: spaet, betrieb: betrieb({ pc: "verbindet" }) })), { art: "ende", hinweis: HINWEIS_PC_STILL });
  const gesendet = { onlineSeit: T0, gesendetSeit: T0 + 1000 };
  assert.equal(wunschSchritt(gesendet, lageW({ jetzt: T0 + 1000 + SCHALT_WARTEN_MS - 1, betrieb: betrieb({ pc: "verbunden" }) })).art, "warten");
  assert.deepEqual(
    wunschSchritt(gesendet, lageW({ jetzt: T0 + 1000 + SCHALT_WARTEN_MS, betrieb: betrieb({ pc: "verbunden" }) })),
    { art: "ende", hinweis: HINWEIS_NICHT_BESTAETIGT },
  );
});

test("alle Hinweise: deutsch, ohne Gedankenstrich, nennen die PC-Steuerung", () => {
  for (const t of [HINWEIS_PC_AUS, HINWEIS_PC_GETRENNT, HINWEIS_PC_GESPERRT, HINWEIS_PC_STILL, HINWEIS_NICHT_BESTAETIGT]) {
    assert.match(t, /^PC-Steuerung nicht eingeschaltet: /);
    assert.doesNotMatch(t, /[\u2013\u2014]| - /);
  }
  for (const t of [HINWEIS_STILL_AUS, HINWEIS_IM_GESPRAECH]) assert.doesNotMatch(t, /[\u2013\u2014]| - /);
});
