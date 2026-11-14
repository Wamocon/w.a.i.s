// Test für die Brücke zur Desktop-App ohne den früheren Stimmen-Rand: Die Oberfläche meldet der App nur noch ihren Zustand
// (Energiesparschutz, Markierung am Zielfenster) und nur bei einem Wechsel, keine Pegel und keine Randfarben mehr.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import * as stimmfarben from "./stimmfarben.ts";
import { desktopZustand, initialState, type WamoState } from "./wamo.ts";

const lies = (pfad: string) => readFileSync(new URL(pfad, import.meta.url), "utf8");

test("keine Randfarben mehr: weder CSS-Variablen --overlay-* noch overlayFarben", () => {
  assert.doesNotMatch(lies("../app/globals.css"), /--overlay-/);
  assert.equal("overlayFarben" in stimmfarben, false);
  assert.doesNotMatch(lies("./useWamo.ts"), /overlayFarben|OverlayFarben|farben\?\.\(/);
});

test("an die Desktop-App geht nur der Zustand und nur bei einem Wechsel", () => {
  const hook = lies("./useWamo.ts");
  const aufrufe = [...hook.matchAll(/window\.wamoDesktop\?\.levels\(([^)]*)\)/g)];
  assert.equal(aufrufe.length, 1);
  assert.equal(aufrufe[0][1], "{ zustand }");
  assert.match(hook, /if \(zustand !== letzterZustand\) window\.wamoDesktop\?\.levels\(\{ zustand \}\);/);
});

test("desktopZustand: Freigabe vor Handeln, beim Verbinden idle", () => {
  const s = (teil: Partial<WamoState>): WamoState => ({ ...initialState, ...teil });
  assert.equal(desktopZustand(s({ presence: "offline" })), "offline");
  assert.equal(desktopZustand(s({ presence: "connecting" })), "idle");
  assert.equal(desktopZustand(s({ presence: "speaking" })), "speaking");
  const laeuft = [{ id: "1", name: "klicken", detail: "", status: "laeuft" }] as WamoState["activities"];
  assert.equal(desktopZustand(s({ presence: "thinking", activities: laeuft })), "acting");
  const freigabe = [{ job: "j", projekt: "p", id: "1", grund: "g", detail: "d" }] as WamoState["approvals"];
  assert.equal(desktopZustand(s({ presence: "thinking", activities: laeuft, approvals: freigabe })), "approval");
});
