// Tests für Hören und Stimme je Profil (lib/sprachwahl.ts) und die Felder dazu in lib/nachrichten.ts (Paket H5).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseServerMessage, type Betrieb, type Modellzugang } from "./nachrichten.ts";
import {
  STIMMEN,
  gewaehlteStimme,
  hausBereit,
  sperrText,
  stimmeErklaerung,
  stimmeName,
  stimmeWaehlbar,
  stimmeWirksamText,
} from "./sprachwahl.ts";

const STAND: Modellzugang = {
  aktion: "status",
  art: "haus",
  hinterlegt: false,
  festgelegt: false,
  codeHinterlegt: false,
  stt: "soniox",
  tts: "soniox",
  stimmeHaus: "bereit",
};
const BETRIEB: Betrieb = { modus: "buero", modelle: { stt: "Soniox", tts: "Soniox Nina" }, pc: "aus" };

test("zwei Wahlen mit den Namen aus der Vorgabe, Soniox zuerst", () => {
  assert.deepEqual(
    STIMMEN.map((s) => [s.id, s.name]),
    [
      ["soniox", "Soniox (Standard)"],
      ["haus", "Im Haus (Datenschutz)"],
    ],
  );
  assert.equal(stimmeName("haus"), "Im Haus");
  assert.equal(stimmeName("soniox"), "Soniox");
  assert.equal(stimmeName(undefined), "unbekannt");
});

test("gewählt: beide gleich, gemischt (nur vom Admin) oder unbekannt", () => {
  assert.equal(gewaehlteStimme(null), null);
  assert.equal(gewaehlteStimme({ ...STAND, stt: undefined, tts: undefined }), null); // älterer Kern ohne Felder
  assert.equal(gewaehlteStimme(STAND), "soniox");
  assert.equal(gewaehlteStimme({ ...STAND, stt: "haus", tts: "haus" }), "haus");
  assert.equal(gewaehlteStimme({ ...STAND, stt: "haus", tts: "soniox" }), "gemischt");
  // der Zwang des Admins auf Hausmodelle ändert die Stimme nicht
  assert.equal(gewaehlteStimme({ ...STAND, festgelegt: true }), "soniox");
});

test("die Folgen von Im Haus stehen in einem Satz da, ohne Gedankenstrich, und der Rückfall wird nicht verschwiegen", () => {
  const haus = stimmeErklaerung("haus");
  assert.match(haus, /kein Live-Mitschreiben/);
  assert.match(haus, /etwas später/);
  assert.match(haus, /satzweise/);
  assert.match(haus, /läuft die Sitzung über Soniox/);
  for (const t of [haus, stimmeErklaerung("soniox"), stimmeErklaerung("gemischt"), stimmeErklaerung(null)]) {
    assert.ok(!/[–—]/.test(t), t);
    assert.ok(t.length > 0);
  }
  assert.match(stimmeErklaerung("soniox"), /Soniox/);
});

test("wirksam ab der nächsten Sitzung, eine Abweichung der Sitzung nennt ihren Grund", () => {
  assert.match(stimmeWirksamText(STAND, null), /ab der nächsten Sitzung/);
  const rueckfall: Betrieb = {
    ...BETRIEB,
    modelle: { stt: "Soniox (Rückfall)", tts: "Soniox Nina (Rückfall)" },
    spracheGrund: "Spracherkennung und Sprachausgabe: das Gateway bietet das Sprachmodell noch nicht an",
  };
  const text = stimmeWirksamText({ ...STAND, stt: "haus", tts: "haus" }, rueckfall);
  assert.match(text, /weicht von der Wahl ab: Spracherkennung und Sprachausgabe: das Gateway bietet das Sprachmodell noch nicht an\. Die/);
  assert.match(text, /ab der nächsten Sitzung/);
  // ein Grund mit Punkt am Ende ergibt keinen doppelten Punkt
  assert.doesNotMatch(stimmeWirksamText(STAND, { ...BETRIEB, spracheGrund: "vom Betrieb für alle auf Soniox gestellt." }), /\.\./);
  // ein vom Admin gemischt gesetzter Stand wird genannt, die Wahl stellt beides gleich
  const gemischt = stimmeWirksamText({ ...STAND, stt: "haus", tts: "soniox" }, null);
  assert.match(gemischt, /Hören Im Haus, Stimme Soniox/);
  assert.match(gemischt, /beides gleich/);
});

test("wählbar nur mit einem Kern, der die Wahl kennt; Im Haus nur, wenn es eingerichtet ist", () => {
  assert.equal(stimmeWaehlbar(STAND), true);
  assert.equal(sperrText(STAND), null);
  assert.equal(hausBereit(STAND), true);
  const alt = { ...STAND, stimmeHaus: undefined };
  assert.equal(stimmeWaehlbar(alt), false);
  assert.match(sperrText(alt) ?? "", /kennt die Wahl noch nicht/);
  const offen = { ...STAND, stimmeHaus: "im Kern noch nicht eingerichtet" };
  assert.equal(stimmeWaehlbar(offen), true);
  assert.equal(hausBereit(offen), false);
  assert.equal(sperrText(offen), "Im Haus geht gerade nicht: im Kern noch nicht eingerichtet. Bis dahin gilt Soniox.");
  assert.equal(sperrText({ ...STAND, art: undefined, fehler: "weg" }), null); // die Karte zeigt den Fehler selbst
});

test("Kern-Nachrichten: stt, tts und stimme_haus im Modellzugang, Grund im Betrieb, Unbekanntes wird verworfen", () => {
  const m = parseServerMessage({
    type: "modellzugang",
    aktion: "stimme",
    art: "haus",
    stt: "haus",
    tts: "soniox",
    stimme_haus: "bereit",
    hinterlegt: false,
  });
  assert.ok(m && m.type === "modellzugang");
  assert.equal(m.aktion, "stimme");
  assert.equal(m.stt, "haus");
  assert.equal(m.tts, "soniox");
  assert.equal(m.stimmeHaus, "bereit");
  const fremd = parseServerMessage({ type: "modellzugang", aktion: "status", stt: "cloud", tts: 3, stimme_haus: 5 });
  assert.ok(fremd && fremd.type === "modellzugang");
  assert.equal(fremd.stt, undefined);
  assert.equal(fremd.tts, undefined);
  assert.equal(fremd.stimmeHaus, undefined);
  const b = parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "aus", sprache_grund: "x".repeat(500) });
  assert.ok(b && b.type === "betrieb");
  assert.equal(b.spracheGrund?.length, 160);
  const ohne = parseServerMessage({ type: "betrieb", modus: "buero", modelle: {}, pc: "aus" });
  assert.ok(ohne && ohne.type === "betrieb");
  assert.equal(ohne.spracheGrund, undefined);
});
