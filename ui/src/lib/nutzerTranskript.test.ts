// Tests für nutzerTranskript (lib/wamo.ts): Transkripte der Person im Untertitel und das Zurücknehmen einer Äußerung, die der Kern im
// strengen Modus verworfen hat (voice-core/stimme_waechter.py). Pipecat meldet jedes Transkript schon beim Verlassen der Spracherkennung;
// verwirft der Wächter es, kommt dasselbe Transkript ohne Text mit dem Zeitstempel des Originals nach.
// Ausführen im Ordner ui/:  npm test   (node:test, ohne Browser)
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  beginneNutzerZug,
  initialState,
  leereCaption,
  logEintrag,
  nimmeTextAuf,
  nutzerHoertAuf,
  nutzerTranskript,
  type WamoState,
} from "./wamo.ts";

const T1 = "2026-11-16T10:00:01.100Z";
const T2 = "2026-11-16T10:00:03.200Z";
const T3 = "2026-11-16T10:00:05.300Z";

const leer: WamoState = { ...initialState, caption: leereCaption, log: [] };
const zw = (s: WamoState, text: string) => nutzerTranskript(s, { text, final: false, timestamp: T1 });
const fin = (s: WamoState, text: string, timestamp: string) => nutzerTranskript(s, { text, final: true, timestamp });
const verworfen = (s: WamoState, timestamp: string) => nutzerTranskript(s, { text: " ", final: true, timestamp });
const zeile = (s: WamoState) => `${s.caption.userDone} ${s.caption.userLive}`.trim();

test("Zwischenstand und endgültiges Transkript wie bisher", () => {
  let s = zw(leer, "Mach die");
  assert.equal(s.caption.userLive, "Mach die");
  s = fin(s, "Mach die Heizung an", T1);
  assert.equal(s.caption.userDone, "Mach die Heizung an");
  assert.equal(s.caption.userLive, "");
  s = fin(s, "bitte", T2);
  assert.equal(s.caption.userDone, "Mach die Heizung an bitte");
});

test("ein verworfenes Transkript verschwindet sofort wieder aus dem Untertitel", () => {
  let s = zw(leer, "Schließ die");
  s = fin(s, "Schließ die Tür", T1);
  assert.equal(zeile(s), "Schließ die Tür");
  s = verworfen(s, T1);
  assert.equal(zeile(s), "");
  assert.deepEqual(s.log, []);
});

test("nur der verworfene Teil geht, eigene Sätze im selben Zug bleiben (auch wenn das Urteil später kommt)", () => {
  let s = fin(leer, "Mach die", T1); // die Person
  s = fin(s, "Schließ die Tür", T2); // ein Gast, das Urteil steht noch aus
  s = fin(s, "Heizung an", T3); // wieder die Person, schon in der Oberfläche, bevor das Urteil zum Gast kommt
  s = verworfen(s, T2);
  assert.equal(s.caption.userDone, "Mach die Heizung an");
});

test("eine Äußerung aus mehreren endgültigen Teilen: jeder Teil wird einzeln zurückgenommen", () => {
  let s = fin(leer, "Schließ die Tür", T1);
  s = fin(s, "und mach das Licht aus", T2);
  s = verworfen(s, T1);
  s = verworfen(s, T2);
  assert.equal(zeile(s), "");
});

test("gleichlautende Teile: entfernt wird genau der zum Zeitstempel, die Reihenfolge der übrigen bleibt", () => {
  let s = fin(leer, "Ja", T1); // ein Gast
  s = fin(s, "Mach", T2); // die Person
  s = fin(s, "Ja", T3); // die Person
  s = verworfen(s, T1);
  assert.equal(s.caption.userDone, "Mach Ja");
  let t = fin(leer, "Na ja", T1);
  t = fin(t, "ja", T2);
  assert.equal(verworfen(t, T1).caption.userDone, "ja");
});

test("ein Transkript ohne Text, das zu keinem Teil passt, ändert nichts", () => {
  const s = fin(leer, "Mach die Heizung an", T1);
  assert.equal(verworfen(s, T3), s);
  assert.equal(nutzerTranskript(s, { text: " ", final: true }), s, "ohne Zeitstempel");
  assert.equal(nutzerTranskript(s, { text: "", final: true, timestamp: T3 }), s, "leerer Text");
  assert.equal(nutzerTranskript(s, { text: "", final: true, timestamp: T1 }).caption.userDone, "", "leer zählt wie ein Leerzeichen");
  assert.equal(nutzerTranskript(s, { text: " ", final: false, timestamp: T1 }), s, "ein Zwischenstand nimmt nie zurück");
  const live = zw(s, "und dann");
  assert.equal(verworfen(live, T3).caption.userLive, "und dann", "der Zwischenstand der nächsten Äußerung bleibt");
  const geloggt = { ...s, log: [logEintrag({ wer: "nutzer", text: "Mach die Heizung an" })], caption: { ...s.caption, userLogged: true } };
  assert.equal(verworfen(geloggt, T3), geloggt, "ein schon übernommener Beitrag verschwindet nicht aus dem Untertitel");
});

test("ein Zurücknehmen lässt den Zwischenstand der nächsten Äußerung stehen", () => {
  let s = fin(leer, "Schließ die Tür", T1);
  s = zw(s, "Mach die");
  s = verworfen(s, T1);
  assert.equal(s.caption.userDone, "");
  assert.equal(s.caption.userLive, "Mach die");
});

test("der Zustand: nach einer ganz verworfenen Äußerung wartet W.A.I.S. wieder, statt nachzudenken", () => {
  const hoert = { ...leer, presence: "listening" as const };
  let s = verworfen(fin(hoert, "Schließ die Tür", T1), T1); // Zurücknehmen vor dem Ende des Zugs (der übliche Weg)
  assert.equal(nutzerHoertAuf(s).presence, "idle");
  s = verworfen(nutzerHoertAuf(fin(hoert, "Schließ die Tür", T1)), T1); // das Ende kam zuerst
  assert.equal(s.presence, "idle");
  assert.equal(nutzerHoertAuf(fin(hoert, "Mach die Heizung an", T1)).presence, "thinking");
  assert.equal(nutzerHoertAuf(zw(hoert, "Mach")).presence, "thinking", "ein Zwischenstand zählt");
  s = verworfen(nutzerHoertAuf(fin(fin(hoert, "Mach die Heizung an", T1), "Schließ die Tür", T2)), T2);
  assert.equal(s.presence, "thinking", "bleibt etwas übrig, denkt W.A.I.S. weiter nach");
  assert.equal(nutzerHoertAuf({ ...leer, presence: "speaking" }).presence, "thinking", "wie bisher außerhalb des Zuhörens");
});

test("ein Teil ohne Zeitstempel bleibt stehen, die übrigen lassen sich trotzdem zurücknehmen", () => {
  let s = fin(leer, "Schließ", T1);
  s = nutzerTranskript(s, { text: "die", final: true });
  s = fin(s, "Tür", T3);
  s = verworfen(s, T1);
  assert.equal(s.caption.userDone, "die Tür");
  s = verworfen(s, T3);
  assert.equal(s.caption.userDone, "die");
});

test("getippter Text vor gesprochenen Teilen behält seine Zeilenumbrüche", () => {
  let s = nimmeTextAuf(leer, "Zeile eins\n\nZeile zwei");
  s = fin(s, "und gesprochen", T1);
  assert.equal(s.caption.userDone, "Zeile eins\n\nZeile zwei und gesprochen");
  assert.equal(verworfen(s, T1).caption.userDone, "Zeile eins\n\nZeile zwei");
});

test("der Zustand davor wird nie verändert", () => {
  const s = fin(fin(leer, "Mach die Heizung an", T1), "Schließ die Tür", T2);
  const kopie = structuredClone(s);
  verworfen(s, T2);
  fin(s, "weiter", T3);
  assert.deepEqual(s, kopie);
});

test("stand der verworfene Teil schon im Verlauf (W.A.I.S. begann zu sprechen), verschwindet er auch dort", () => {
  let s = fin(leer, "Wie spät ist es", T1);
  s = fin(s, "Schließ die Tür", T2);
  // wie onBotStartedSpeaking in useWamo.ts: der Nutzerbeitrag geht in den Verlauf
  s = { ...s, log: [logEintrag({ wer: "nutzer", text: zeile(s) })], caption: { ...s.caption, userLogged: true } };
  s = verworfen(s, T2);
  assert.equal(s.log.length, 1);
  assert.equal(s.log[0].text, "Wie spät ist es");
  assert.equal(s.caption.userDone, "Wie spät ist es");
});

test("bestand der Eintrag im Verlauf nur aus dem verworfenen Teil, fällt er ganz weg", () => {
  const davor = logEintrag({ wer: "wamo", text: "Gern." });
  let s = fin({ ...leer, log: [davor] }, "Schließ die Tür", T1);
  s = { ...s, log: [...s.log, logEintrag({ wer: "nutzer", text: zeile(s) })], caption: { ...s.caption, userLogged: true } };
  s = verworfen(s, T1);
  assert.deepEqual(s.log, [davor]);
  assert.equal(zeile(s), "");
});

test("ein neuer Zug und getippter Text beginnen ohne alte Teile", () => {
  let s = fin(leer, "Schließ die Tür", T1);
  s = { ...s, caption: { ...s.caption, userLogged: true } };
  s = beginneNutzerZug(s);
  assert.deepEqual(s.caption.userTeile, []);
  s = fin(s, "Mach die Heizung an", T2);
  s = nimmeTextAuf(s, "getippt");
  assert.deepEqual(s.caption.userTeile, []);
  assert.equal(verworfen(s, T2).caption.userDone, "getippt", "getippter Text wird nie zurückgenommen");
  s = fin(s, "Schließ die Tür", T3);
  assert.equal(s.caption.userDone, "getippt Schließ die Tür");
  assert.equal(verworfen(s, T3).caption.userDone, "getippt", "gesprochenes danach schon");
});

test("nach dem Verlauf beginnt das nächste endgültige Transkript einen neuen Nutzerbeitrag", () => {
  let s = fin(leer, "Hallo", T1);
  s = { ...s, caption: { ...s.caption, userLogged: true } };
  s = fin(s, "Neue Frage", T2);
  assert.equal(s.caption.userDone, "Neue Frage");
  assert.deepEqual(s.caption.userTeile, [{ zeit: T2, text: "Neue Frage" }]);
});

test("die Liste der Teile bleibt begrenzt, ältere Teile bleiben dann nur als Text stehen", () => {
  let s = leer;
  const zeit = (i: number) => `2026-11-16T10:00:${String(i).padStart(2, "0")}.000Z`;
  for (let i = 0; i < 60; i += 1) s = fin(s, `Teil ${i}`, zeit(i));
  assert.ok(s.caption.userTeile.length <= 40);
  assert.equal(s.caption.userTeile.at(-1)?.text, "Teil 59");
  assert.equal(verworfen(s, zeit(0)), s, "aus der Liste gefallen: nicht mehr zurückzunehmen");
  const ohneLetzten = verworfen(s, zeit(59)).caption.userDone;
  assert.ok(ohneLetzten.startsWith("Teil 0 Teil 1 ") && ohneLetzten.endsWith("Teil 58"));
});
