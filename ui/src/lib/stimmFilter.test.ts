// Tests für den Stimmfilter im Chat links (lib/stimmFilter.ts, lib/wamo.ts nutzerTranskript, urteilEinarbeiten, antwortBeginnt,
// botSprichtAn): Ohne Filter bleibt alles wie bisher. Mit Filter erscheint ein endgültiger Satz der Person erst nach dem Urteil des Kerns
// (ignoriert false), ein verworfener nie, und als Rückfall nach HALTEN_MS oder sobald W.A.I.S. antwortet. Zwischenstände erscheinen mit
// Filter nicht im Chat, getippter Text immer sofort.
// Ausführen im Ordner ui/:  npm test   (node:test, ohne Browser)
import assert from "node:assert/strict";
import { test } from "node:test";
import { menschZeile } from "./gespraech.ts";
import { STIMME_LEER } from "./stimme.ts";
import { alleFreigeben, fristFreigeben, HALTEN_MS, naechsteFrist, sichtbarerNutzerText, stimmFilterAktiv } from "./stimmFilter.ts";
import {
  antwortBeginnt,
  botSprichtAn,
  initialState,
  leereCaption,
  logEintrag,
  nimmeTextAuf,
  nutzerTranskript,
  urteilEinarbeiten,
  type WamoState,
} from "./wamo.ts";

const T1 = "2026-11-17T10:00:01.100Z";
const T2 = "2026-11-17T10:00:03.200Z";
const T3 = "2026-11-17T10:00:05.300Z";
const JETZT = 1_000_000;

const leer: WamoState = { ...initialState, caption: leereCaption, log: [] };
const mit = { filter: true, jetzt: JETZT };
const fin = (s: WamoState, text: string, zeit: string, opt = mit) => nutzerTranskript(s, { text, final: true, timestamp: zeit }, opt);
const zw = (s: WamoState, text: string, opt = mit) => nutzerTranskript(s, { text, final: false, timestamp: T1 }, opt);
const angenommen = (s: WamoState, zeit: string) => urteilEinarbeiten(s, { ergebnis: "eigen", ignoriert: false, zeit });
const verworfen = (s: WamoState, zeit: string) => urteilEinarbeiten(s, { ergebnis: "fremd", ignoriert: true, zeit });
const chat = (s: WamoState) => sichtbarerNutzerText(s.caption);

test("aktiv nur mit bereitem Abdruck im Modus streng", () => {
  assert.equal(stimmFilterAktiv({ status: "bereit", modus: "streng" }), true);
  assert.equal(stimmFilterAktiv({ status: "bereit", modus: "beobachten" }), false);
  assert.equal(stimmFilterAktiv({ status: "bereit", modus: null }), false);
  assert.equal(stimmFilterAktiv({ status: "fehlt", modus: "streng" }), false);
  assert.equal(stimmFilterAktiv({ status: "laedt", modus: "streng" }), false);
  assert.equal(stimmFilterAktiv(STIMME_LEER), false);
});

test("Filter aus: Zwischenstand und endgültige Teile erscheinen sofort, nichts wird zurückgehalten", () => {
  const ohne = { filter: false, jetzt: JETZT };
  let s = zw(leer, "Mach die", ohne);
  assert.equal(chat(s), "Mach die");
  s = fin(s, "Mach die Heizung an", T1, ohne);
  s = zw(s, "bitte", ohne);
  assert.equal(chat(s), "Mach die Heizung an bitte");
  assert.equal(menschZeile(s.caption, s.log), "Mach die Heizung an bitte");
  assert.deepEqual(s.caption.userTeile, [{ zeit: T1, text: "Mach die Heizung an" }], "ohne Frist");
  assert.equal(naechsteFrist(s.caption), null);
  assert.equal(nutzerTranskript(leer, { text: "Hallo", final: true, timestamp: T1 }).caption.gefiltert, false, "Standard ist ohne Filter");
});

test("Filter an: ein endgültiger Satz wartet auf das Urteil und erscheint nach ignoriert false", () => {
  let s = fin(leer, "Mach die Heizung an", T1);
  assert.equal(chat(s), "");
  assert.equal(s.caption.userDone, "Mach die Heizung an", "der Untertitel unter dem Kern hat den Text weiter");
  assert.equal(naechsteFrist(s.caption), JETZT + HALTEN_MS);
  s = angenommen(s, T1);
  assert.equal(chat(s), "Mach die Heizung an");
  assert.equal(naechsteFrist(s.caption), null);
});

test("Filter an: ignoriert true verwirft den Satz still, auch aus dem Untertitel", () => {
  let s = fin(leer, "Schließ die Tür", T1);
  s = verworfen(s, T1);
  assert.equal(chat(s), "");
  assert.equal(s.caption.userDone, "");
  assert.deepEqual(s.caption.userTeile, []);
  const unklar = urteilEinarbeiten(fin(leer, "Schließ die Tür", T1), { ergebnis: "unklar", ignoriert: true, zeit: T1 });
  assert.equal(unklar.caption.userDone, "", "unklar und verworfen zählt genauso");
});

test("Filter an: das leere Ersatztranskript des Kerns verwirft den zurückgehaltenen Satz ebenso", () => {
  let s = fin(leer, "Schließ die Tür", T1);
  s = nutzerTranskript(s, { text: " ", final: true, timestamp: T1 }, mit);
  assert.equal(chat(s), "");
  assert.deepEqual(s.caption.userTeile, []);
});

test("Filter an: nur der Teil zum Zeitstempel ändert sich, die Reihenfolge bleibt", () => {
  let s = fin(leer, "Mach die", T1);
  s = fin(s, "Schließ die Tür", T2); // ein Gast
  s = fin(s, "Heizung an", T3);
  s = angenommen(s, T1);
  assert.equal(chat(s), "Mach die");
  s = angenommen(s, T3);
  assert.equal(chat(s), "Mach die Heizung an", "der Gast wartet weiter, der Satz danach erscheint schon");
  s = verworfen(s, T2);
  assert.equal(chat(s), "Mach die Heizung an");
  assert.equal(s.caption.userDone, "Mach die Heizung an");
});

test("ein Urteil ohne zeit oder mit fremder zeit ändert nichts, ein eigenes mit ignoriert gilt als angenommen", () => {
  const s = fin(leer, "Mach die Heizung an", T1);
  assert.equal(urteilEinarbeiten(s, { ergebnis: "fremd", ignoriert: true }), s, "älterer Kern ohne zeit");
  assert.equal(urteilEinarbeiten(s, { ergebnis: "eigen", ignoriert: false, zeit: T3 }), s);
  assert.equal(verworfen(s, T3), s);
  assert.equal(chat(urteilEinarbeiten(s, { ergebnis: "eigen", ignoriert: true, zeit: T1 })), "Mach die Heizung an");
  assert.equal(chat(urteilEinarbeiten(s, { ergebnis: "unklar", zeit: T1 })), "Mach die Heizung an", "ohne ignoriert: angenommen");
});

test("Rückfall: nach HALTEN_MS ohne Urteil erscheint der Satz, vorher nicht", () => {
  let s = fin(leer, "Mach die Heizung an", T1);
  s = fin(s, "bitte", T2, { filter: true, jetzt: JETZT + 1000 });
  assert.equal(fristFreigeben(s.caption, JETZT + HALTEN_MS - 1), s.caption);
  const c = fristFreigeben(s.caption, JETZT + HALTEN_MS);
  assert.equal(sichtbarerNutzerText(c), "Mach die Heizung an");
  assert.equal(naechsteFrist(c), JETZT + 1000 + HALTEN_MS);
  assert.equal(sichtbarerNutzerText(fristFreigeben(c, JETZT + 1000 + HALTEN_MS)), "Mach die Heizung an bitte");
});

test("Rückfall: beginnt W.A.I.S. zu antworten, erscheint alles Zurückgehaltene", () => {
  const s = fin(fin(leer, "Mach die", T1), "Heizung an", T2);
  assert.equal(chat(antwortBeginnt(s)), "Mach die Heizung an");
  assert.equal(antwortBeginnt(leer), leer, "ohne Zurückgehaltenes bleibt der Zustand derselbe");
  assert.equal(alleFreigeben(leer.caption), leer.caption);
});

test("botSprichtAn: der Verlauf bekommt den freigegebenen Satz ohne Zwischenstand; ein spätes Verwerfen nimmt ihn dort wieder heraus", () => {
  let s = fin(leer, "Wie spät ist es", T1);
  s = fin(s, "Schließ die Tür", T2);
  s = zw(s, "und dann");
  s = botSprichtAn(s);
  assert.equal(s.presence, "speaking");
  assert.equal(s.log.length, 1);
  assert.equal(s.log[0].text, "Wie spät ist es Schließ die Tür");
  assert.equal(s.caption.userLogged, true);
  s = verworfen(s, T2);
  assert.equal(s.log[0].text, "Wie spät ist es", "das Urteil kam nach dem Rückfall: der fremde Teil geht wieder");
});

test("botSprichtAn ohne Filter: wie bisher mit Zwischenstand im Verlauf", () => {
  const ohne = { filter: false, jetzt: JETZT };
  const s = botSprichtAn(zw(fin(leer, "Mach die", T1, ohne), "Heizung an", ohne));
  assert.equal(s.log[0].text, "Mach die Heizung an");
});

test("Filter an: Zwischenstände erscheinen nicht im Chat, die Zeile zeigt bis dahin den letzten Satz aus dem Verlauf", () => {
  const davor = { ...leer, log: [logEintrag({ wer: "nutzer", text: "Erste Frage" }), logEintrag({ wer: "wamo", text: "Antwort" })] };
  let s = zw(davor, "Schließ die");
  assert.equal(chat(s), "");
  assert.equal(menschZeile(s.caption, s.log), "Erste Frage");
  s = fin(s, "Schließ die Tür", T1);
  assert.equal(menschZeile(s.caption, s.log), "Erste Frage");
  s = angenommen(s, T1);
  assert.equal(menschZeile(s.caption, s.log), "Schließ die Tür");
});

test("Filter an: getippter Text erscheint sofort, gesprochene Teile danach erst nach dem Urteil", () => {
  let s = nimmeTextAuf(leer, "Zeile eins\n\nZeile zwei");
  assert.equal(chat(s), "Zeile eins\n\nZeile zwei");
  s = fin(s, "und gesprochen", T1);
  assert.equal(chat(s), "Zeile eins\n\nZeile zwei");
  assert.equal(chat(angenommen(s, T1)), "Zeile eins\n\nZeile zwei und gesprochen");
  assert.equal(chat(verworfen(s, T1)), "Zeile eins\n\nZeile zwei");
});

test("der Zustand davor wird nie verändert", () => {
  const s = fin(fin(leer, "Mach die Heizung an", T1), "Schließ die Tür", T2);
  const kopie = structuredClone(s);
  angenommen(s, T1);
  verworfen(s, T2);
  antwortBeginnt(s);
  botSprichtAn(s);
  fristFreigeben(s.caption, JETZT + HALTEN_MS);
  assert.deepEqual(s, kopie);
});
