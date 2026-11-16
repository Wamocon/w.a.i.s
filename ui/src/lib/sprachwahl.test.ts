// Tests für Hören und Stimme je Profil (lib/sprachwahl.ts) und die Felder dazu in lib/nachrichten.ts (Paket H5, getrennt seit 0024).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseServerMessage, type Betrieb, type Modellzugang } from "./nachrichten.ts";
import {
  BAUSTEINE,
  STANDARD_STIMME,
  STIMMEN,
  bausteinErklaerung,
  datenschutzText,
  gewaehlt,
  gewaehlteHausStimme,
  hausBereit,
  sperrText,
  stimmeHinweis,
  stimmeName,
  stimmeWaehlbar,
  stimmeWirksamText,
  stimmenAuswahl,
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

test("gewählt je Baustein; Spracherkennung und Sprachausgabe sind getrennt", () => {
  assert.equal(gewaehlt(null, "stt"), null);
  assert.equal(gewaehlt({ ...STAND, stt: undefined }, "stt"), null); // älterer Kern ohne Felder
  assert.equal(gewaehlt({ ...STAND, stt: "haus", tts: "soniox" }, "stt"), "haus");
  assert.equal(gewaehlt({ ...STAND, stt: "haus", tts: "soniox" }, "tts"), "soniox");
  // der Zwang des Admins auf Hausmodelle ändert die Stimme nicht
  assert.equal(gewaehlt({ ...STAND, festgelegt: true }, "tts"), "soniox");
  assert.deepEqual(
    BAUSTEINE.map((b) => b.name),
    ["Spracherkennung", "Sprachausgabe"],
  );
});

test("die Folgen stehen je Baustein in einem Satz da, ohne Gedankenstrich; Datenschutz erst mit beidem im Haus", () => {
  assert.match(bausteinErklaerung("stt", "haus"), /kein Live-Mitschreiben/);
  assert.match(bausteinErklaerung("tts", "haus"), /etwas später/);
  assert.match(bausteinErklaerung("tts", "haus"), /satzweise/);
  assert.match(bausteinErklaerung("stt", "soniox"), /Soniox/);
  assert.match(datenschutzText({ ...STAND, stt: "haus", tts: "haus" }), /bleiben in der Firma.*über Soniox/);
  assert.match(datenschutzText({ ...STAND, stt: "haus", tts: "soniox" }), /Erst wenn beides im Haus läuft/);
  assert.match(datenschutzText(STAND), /Soniox ist der Standard/);
  for (const b of ["stt", "tts"] as const) {
    for (const w of ["haus", "soniox", null] as const) assert.ok(!/[–—]/.test(bausteinErklaerung(b, w)));
  }
});

test("wirksam ab der nächsten Sitzung, eine Abweichung der Sitzung nennt ihren Grund", () => {
  assert.match(stimmeWirksamText(null), /ab der nächsten Sitzung/);
  const rueckfall: Betrieb = {
    ...BETRIEB,
    modelle: { stt: "Soniox (Rückfall)", tts: "Soniox Nina (Rückfall)" },
    spracheGrund: "Spracherkennung und Sprachausgabe: das Gateway bietet das Sprachmodell noch nicht an",
  };
  const text = stimmeWirksamText(rueckfall);
  assert.match(text, /weicht von der Wahl ab: Spracherkennung und Sprachausgabe: das Gateway bietet das Sprachmodell noch nicht an\. Die/);
  assert.match(text, /ab der nächsten Sitzung/);
  // ein Grund mit Punkt am Ende ergibt keinen doppelten Punkt
  assert.doesNotMatch(stimmeWirksamText({ ...BETRIEB, spracheGrund: "vom Betrieb für alle auf Soniox gestellt." }), /\.\./);
});

test("Stimme im Haus: nur die Liste des Kerns in seiner Reihenfolge, Standard markiert, Hinweis immer mit nicht nativ deutsch", () => {
  const z: Modellzugang = {
    ...STAND,
    tts: "haus",
    hausStimmeStandard: "sohee",
    hausStimmen: [
      { id: "sohee", name: "Sohee", hinweis: "am schnellsten gemessen" },
      { id: "uncle_fu", name: "Uncle Fu" },
      { id: "ono_anna", name: "Ono Anna" },
    ],
    hausStimmenHinweis: "Keine der Stimmen ist nativ deutsch; sie sprechen Deutsch mit Akzent.",
  };
  assert.deepEqual(
    stimmenAuswahl(z).map((s) => [s.id, s.name]),
    [
      ["sohee", "Sohee (Standard)"],
      ["uncle_fu", "Uncle Fu"],
      ["ono_anna", "Ono Anna"],
    ],
  );
  assert.deepEqual(stimmenAuswahl(STAND), []); // älterer Kern: keine Auswahl
  assert.equal(gewaehlteHausStimme(z), "sohee"); // ohne eigene Wahl: der Standard des Kerns
  assert.equal(gewaehlteHausStimme({ ...z, hausStimme: "ono_anna" }), "ono_anna");
  assert.equal(gewaehlteHausStimme(STAND), STANDARD_STIMME);
  assert.match(stimmeHinweis(z, "sohee"), /nativ deutsch.*Sohee: am schnellsten gemessen\.$/);
  assert.match(stimmeHinweis(z, "uncle_fu"), /Akzent\.$/);
  assert.match(stimmeHinweis({ ...z, tts: "soniox" }, "ono_anna"), /sobald die Sprachausgabe im Haus läuft/);
  assert.match(stimmeHinweis(null, STANDARD_STIMME), /nativ deutsch/);
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
