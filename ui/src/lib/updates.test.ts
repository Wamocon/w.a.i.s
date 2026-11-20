// Tests für die Logik des Abschnitts "Updates" der Einstellungen (lib/updates.ts): welcher Zustand aus Version, Stand der Prüfung und
// Phase der Installation folgt, mit Satz, Zeichenstufe und Angebot. Der Stand der Prüfung kommt aus lib/einrichtung.ts (dieselbe
// Quelle wie die Prüfliste der Ersten Schritte), hier sind die Stände Attrappen.
// Ausführen im Ordner ui/:  npm test   (node:test, Node lädt TypeScript selbst)
import assert from "node:assert/strict";
import { test } from "node:test";
import type { UpdateStand } from "./einrichtung.ts";
import { PRUEF_ABSTAND_MS, updateStandLaden } from "./einrichtung.ts";
import {
  BROWSER_SATZ,
  PHASE_RUHE,
  angebotAus,
  phaseNachInstallation,
  suchStand,
  updateAnsicht,
  type InstallPhase,
  type UpdateAnsicht,
} from "./updates.ts";

const SIGNATUR = `${"A".repeat(86)}==`;
const MANIFEST = { manifest: '{"version":"0.8.0"}', signatur: SIGNATUR };
const OHNE_STRICH = /[–—]|\s-\s/;

const geprueft = (ergebnis: Extract<UpdateStand, { art: "geprueft" }>["ergebnis"]): UpdateStand => ({ art: "geprueft", manifest: MANIFEST, ergebnis });
const NEUER: UpdateStand = geprueft({ ok: true, version: "0.8.0", neuer: true });
const AKTUELL: UpdateStand = geprueft({ ok: true, version: "0.7.0", neuer: false });

const ansicht = (stand: UpdateStand | null, o: { version?: string | null; phase?: InstallPhase } = {}): UpdateAnsicht =>
  updateAnsicht({ version: o.version === undefined ? "0.7.0" : o.version, stand, phase: o.phase ?? PHASE_RUHE });

// ---------- Zustände ----------
test("noch nicht geprüft: Wird geprüft, ohne Knopf", () => {
  const a = ansicht(null);
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe, angebot: a.angebot }, { z: "laedt", titel: "Wird geprüft", stufe: "hinweis", angebot: null });
  assert.equal(a.installiert, "0.7.0");
  assert.equal(a.server, "wird geprüft");
});

test("die App bestätigt keine neuere Version: Aktuell mit der Version des Servers", () => {
  const a = ansicht(AKTUELL);
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe, angebot: a.angebot }, { z: "aktuell", titel: "Aktuell", stufe: "gruen", angebot: null });
  assert.equal(a.satz, "Du nutzt die neueste Version.");
  assert.equal(a.server, "0.7.0");
});

test("der Server bietet noch nichts an: auch Aktuell, mit dem Satz dazu", () => {
  const a = ansicht({ art: "kein_angebot" });
  assert.deepEqual({ z: a.zustand, stufe: a.stufe, angebot: a.angebot }, { z: "aktuell", stufe: "gruen", angebot: null });
  assert.equal(a.satz, "Der Server bietet noch kein Update an.");
  assert.equal(a.server, "noch kein Update");
});

test("Update verfügbar: Version im Titel, das Angebot trägt Manifest und Signatur für die App", () => {
  const a = ansicht(NEUER);
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe }, { z: "verfuegbar", titel: "Update verfügbar (Version 0.8.0)", stufe: "rot" });
  assert.deepEqual(a.angebot, { version: "0.8.0", manifest: MANIFEST.manifest, signatur: SIGNATUR });
  assert.equal(a.server, "0.8.0");
  assert.equal(a.installiert, "0.7.0");
  assert.equal(a.installerAnbieten, false);
});

test("das Angebot gibt es nur nach der Bestätigung der App: nie bei Fehler, unlesbarem Manifest oder fehlender Prüfung", () => {
  const ohne: UpdateStand[] = [
    geprueft({ ok: false, text: "Update vom Server nicht bestätigt." }),
    { art: "unbekannt" },
    { art: "ohne_pruefung" },
    { art: "kein_angebot" },
    AKTUELL,
  ];
  for (const s of ohne) assert.equal(ansicht(s).angebot, null, s.art);
});

test("angebotAus: nur ein von der App bestätigtes neueres Update, unabhängig von der Phase der Installation", () => {
  assert.deepEqual(angebotAus(NEUER), { version: "0.8.0", manifest: MANIFEST.manifest, signatur: SIGNATUR });
  for (const s of [null, AKTUELL, { art: "kein_angebot" }, { art: "unbekannt" }, { art: "ohne_pruefung" }, geprueft({ ok: false, text: "x" })] as (UpdateStand | null)[]) {
    assert.equal(angebotAus(s), null);
  }
});

test("die App lehnt das Manifest ab: Prüfung nicht möglich mit dem Satz der App, rot, ohne Angebot", () => {
  const a = ansicht(geprueft({ ok: false, text: "Update vom Server nicht bestätigt." }));
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe, satz: a.satz }, { z: "nicht_moeglich", titel: "Prüfung nicht möglich", stufe: "rot", satz: "Update vom Server nicht bestätigt." });
  assert.equal(a.server, "nicht geprüft");
});

test("Manifest nicht lesbar oder Server nicht erreichbar: Prüfung nicht möglich, nur ein Hinweis", () => {
  const a = ansicht({ art: "unbekannt" });
  assert.deepEqual({ z: a.zustand, stufe: a.stufe }, { z: "nicht_moeglich", stufe: "hinweis" });
  assert.match(a.satz, /gerade nicht prüfen/);
});

test("ältere App ohne Update-Funktion: Prüfung nicht möglich und der Installer wird angeboten", () => {
  const a = ansicht({ art: "ohne_pruefung" }, { version: null });
  assert.deepEqual({ z: a.zustand, stufe: a.stufe, installer: a.installerAnbieten, installiert: a.installiert }, { z: "nicht_moeglich", stufe: "hinweis", installer: true, installiert: "unbekannt" });
  assert.match(a.satz, /Installer/);
});

// ---------- Installation ----------
test("Installation läuft: Wird installiert, das Angebot bleibt (der Knopf behält den Fokus), Satz mit der Rückfrage der App", () => {
  const a = ansicht(NEUER, { phase: { art: "laeuft" } });
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe }, { z: "installiert", titel: "Wird installiert", stufe: "hinweis" });
  assert.equal(a.angebot?.version, "0.8.0");
  assert.match(a.satz, /Rückfrage/);
});

test("Installation gestartet: Wird installiert mit dem Satz zum Neustart, kein Angebot mehr", () => {
  const a = ansicht(NEUER, { phase: { art: "gestartet" } });
  assert.deepEqual({ z: a.zustand, titel: a.titel, angebot: a.angebot }, { z: "installiert", titel: "Wird installiert", angebot: null });
  assert.equal(a.satz, "Die App installiert das Update und startet danach neu.");
});

test("Installation gescheitert: Fehler mit dem Grund der App, kein Angebot, Hinweis auf die erneute Suche", () => {
  const a = ansicht(NEUER, { phase: { art: "fehler", text: "Signatur passt nicht." } });
  assert.deepEqual({ z: a.zustand, titel: a.titel, stufe: a.stufe, satz: a.satz, angebot: a.angebot }, { z: "fehler", titel: "Fehler", stufe: "rot", satz: "Signatur passt nicht.", angebot: null });
  assert.match(a.hinweis ?? "", /Nach Updates suchen/);
});

test("die Phase nach dem Ergebnis der App: abgebrochen heißt zurück auf Ruhe, ein Satz heißt Fehler, ok heißt gestartet", () => {
  assert.deepEqual(phaseNachInstallation({ ok: true }), { art: "gestartet" });
  assert.deepEqual(phaseNachInstallation({ ok: false, text: "Abgebrochen.", abgebrochen: true }), PHASE_RUHE);
  assert.deepEqual(phaseNachInstallation({ ok: false, text: "Signatur passt nicht.", abgebrochen: false }), { art: "fehler", text: "Signatur passt nicht." });
});

// ---------- Texte ----------
test("Zeile zum Stand der Suche: Prüfe, Uhrzeit, Sperre", () => {
  assert.equal(suchStand(true, false, null), "Prüfe ...");
  assert.equal(suchStand(false, false, null), "");
  assert.equal(suchStand(false, false, "10:15"), "Geprüft um 10:15 Uhr.");
  assert.equal(suchStand(false, true, "10:15"), `Geprüft um 10:15 Uhr. Nach Updates suchen geht einmal je ${PRUEF_ABSTAND_MS / 1000} Sekunden.`);
  assert.equal(suchStand(false, true, null), `Nach Updates suchen geht einmal je ${PRUEF_ABSTAND_MS / 1000} Sekunden.`);
});

test("alle festen Sätze ohne Gedankenstrich", () => {
  const stande: (UpdateStand | null)[] = [null, AKTUELL, NEUER, { art: "kein_angebot" }, { art: "unbekannt" }, { art: "ohne_pruefung" }];
  const phasen: InstallPhase[] = [PHASE_RUHE, { art: "laeuft" }, { art: "gestartet" }, { art: "fehler", text: "Es ging nicht." }];
  const texte = [BROWSER_SATZ];
  for (const s of stande) {
    for (const phase of phasen) {
      const a = ansicht(s, { phase });
      texte.push(a.titel, a.satz, a.hinweis ?? "", a.server, a.installiert);
    }
  }
  for (const t of texte) assert.ok(!OHNE_STRICH.test(t), t);
});

// ---------- Laden ----------
test("updateStandLaden fragt Server und App wie die Prüfliste: die App bestätigt das Manifest, die Oberfläche liest es nicht", async () => {
  const pfade: string[] = [];
  const kernJson = async (pfad: string) => {
    pfade.push(pfad);
    return { ...MANIFEST, version: "0.8.0" };
  };
  const aufrufe: unknown[] = [];
  const bruecke = {
    version: "0.7.0",
    update: {
      pruefen: async (a: unknown) => {
        aufrufe.push(a);
        return { ok: true, version: "0.8.0", neuer: true };
      },
      installieren: async () => ({ ok: true }),
    },
  };
  const stand = await updateStandLaden({ kernJson, bruecke });
  assert.deepEqual(pfade, ["/installer"]);
  assert.deepEqual(aufrufe, [MANIFEST]);
  assert.equal(stand.art, "geprueft");
  assert.equal(updateAnsicht({ version: "0.7.0", stand, phase: PHASE_RUHE }).zustand, "verfuegbar");
});

test("updateStandLaden ohne Version oder ohne Update-Teil der Brücke fragt nichts an", async () => {
  const pfade: string[] = [];
  const kernJson = async (pfad: string) => {
    pfade.push(pfad);
    return MANIFEST;
  };
  assert.deepEqual(await updateStandLaden({ kernJson, bruecke: { version: undefined } }), { art: "ohne_pruefung" });
  assert.deepEqual(await updateStandLaden({ kernJson, bruecke: { version: "0.7.0" } }), { art: "ohne_pruefung" });
  assert.deepEqual(pfade, []);
});

test("updateStandLaden: 404 vom Server heißt kein Angebot, ein anderer Fehler heißt unbekannt, die App antwortet nach der Frist nicht", async () => {
  const bruecke = {
    version: "0.7.0",
    update: { pruefen: () => new Promise<unknown>(() => undefined), installieren: async () => ({ ok: true }) },
  };
  const fehler = (status: number) => async () => Promise.reject(Object.assign(new Error(`Fehler ${status}`), { status }));
  assert.deepEqual(await updateStandLaden({ kernJson: fehler(404), bruecke }), { art: "kein_angebot" });
  assert.deepEqual(await updateStandLaden({ kernJson: fehler(500), bruecke }), { art: "unbekannt" });
  const still = await updateStandLaden({ kernJson: async () => MANIFEST, bruecke, fristMs: 20 });
  assert.equal(still.art, "geprueft");
  assert.equal(updateAnsicht({ version: "0.7.0", stand: still, phase: PHASE_RUHE }).zustand, "nicht_moeglich");
});
