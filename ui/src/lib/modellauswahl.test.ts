// Tests für die Modellwahl je Person (lib/modellauswahl.ts) und die Felder dazu in lib/nachrichten.ts (Migration 0024).
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AUTOMATISCH,
  auswahlSperre,
  BEREICHE,
  bereichStand,
  erklaerung,
  gruppen,
  optionText,
  wahlName,
  wirksamText,
} from "./modellauswahl.ts";
import { parseServerMessage, type Betrieb, type ModellBereichStand, type Modellzugang } from "./nachrichten.ts";

const GESPRAECH: ModellBereichStand = {
  wahl: AUTOMATISCH,
  optionen: [
    { id: "claude-haiku-5-5", name: "Claude Haiku 5.5", art: "claude", zeile: "Güte 88 %, Tempo schnell, Cloud, kostet je Anfrage" },
    { id: "gemma4-31b", name: "Gemma 4 31B", art: "haus", zeile: "Güte 92 %, Tempo mittel (erstes Wort 0,6 s)" },
    { id: "qwen3.6-35b", name: "Qwen 3.6 35B", art: "haus", zeile: "Güte 74 %, Tempo mittel, nur als Notlösung" },
  ],
};
const STAND: Modellzugang = {
  aktion: "status",
  art: "claude",
  hinterlegt: true,
  festgelegt: false,
  codeHinterlegt: false,
  modelle: { gespraech: GESPRAECH, bilder: { wahl: AUTOMATISCH, optionen: [] }, hintergrund: { wahl: AUTOMATISCH, optionen: [] } },
};

test("drei Bereiche in fester Reihenfolge, je mit Zweck", () => {
  assert.deepEqual(
    BEREICHE.map((b) => b.id),
    ["gespraech", "bilder", "hintergrund"],
  );
  for (const b of BEREICHE) assert.ok(b.zweck.endsWith("."));
});

test("Claude-Gruppe nur, wenn der Kern Claude anbietet; Hausmodelle in der Reihenfolge des Kerns", () => {
  assert.deepEqual(
    gruppen(GESPRAECH).map((g) => [g.name, g.optionen.map((o) => o.id)]),
    [
      ["Claude (Cloud, über deinen Schlüssel)", ["claude-haiku-5-5"]],
      ["Im Haus", ["gemma4-31b", "qwen3.6-35b"]],
    ],
  );
  const haus = { ...GESPRAECH, optionen: GESPRAECH.optionen.filter((o) => o.art === "haus") };
  assert.deepEqual(
    gruppen(haus).map((g) => g.name),
    ["Im Haus"],
  );
  assert.deepEqual(gruppen(null), []);
  assert.equal(optionText(GESPRAECH.optionen[1]), "Gemma 4 31B · Güte 92 %, Tempo mittel (erstes Wort 0,6 s)");
});

test("Erklärung: Automatisch ist der Standard, Claude kostet, Hausmodelle haben einen Rückfall", () => {
  assert.match(erklaerung(GESPRAECH, AUTOMATISCH), /Standard/);
  assert.match(erklaerung(GESPRAECH, "claude-haiku-5-5"), /Guthaben/);
  assert.match(erklaerung(GESPRAECH, "gemma4-31b"), /Statusleiste nennt den Grund/);
  assert.match(erklaerung(GESPRAECH, "gibt-es-nicht"), /automatisch/);
  assert.equal(wahlName(GESPRAECH, "gemma4-31b"), "Gemma 4 31B");
  assert.equal(wahlName(GESPRAECH, AUTOMATISCH), "Automatisch");
  for (const t of [erklaerung(GESPRAECH, AUTOMATISCH), erklaerung(GESPRAECH, "claude-haiku-5-5"), erklaerung(null, "x")]) {
    assert.ok(!/[–—]/.test(t), t);
  }
});

test("gesperrt mit Grund: Admin legt fest, älterer Kern kennt die Wahl nicht; ohne Stand kein Satz", () => {
  assert.equal(auswahlSperre(STAND), null);
  const fest = { ...STAND, art: "haus" as const, festgelegt: true, modellSperre: "Ein Admin hat dein Profil auf Hausmodelle festgelegt." };
  assert.equal(auswahlSperre(fest), "Ein Admin hat dein Profil auf Hausmodelle festgelegt.");
  assert.match(auswahlSperre({ ...STAND, modelle: undefined }) ?? "", /kennt die Modellwahl noch nicht/);
  assert.equal(auswahlSperre({ ...STAND, art: undefined, fehler: "weg" }), null);
  assert.equal(auswahlSperre(null), null);
  assert.equal(bereichStand(STAND, "gespraech"), GESPRAECH);
  assert.equal(bereichStand(null, "bilder"), null);
});

test("wirksam ab der nächsten Sitzung; beim Gespräch mit dem Grund der laufenden Sitzung", () => {
  const betrieb: Betrieb = { modus: "buero", modelle: {}, pc: "aus", modellHinweis: "Gemma 4 31B: antwortet zu langsam." };
  assert.equal(wirksamText("gespraech", null), "Die Wahl gilt ab der nächsten Sitzung.");
  assert.equal(wirksamText("gespraech", betrieb), "Diese Sitzung: Gemma 4 31B: antwortet zu langsam. Die Wahl gilt ab der nächsten Sitzung.");
  assert.equal(wirksamText("bilder", betrieb), "Die Wahl gilt ab der nächsten Sitzung.");
});

test("Kern-Nachricht: Modelle, Sperre und Stimmen werden geprüft übernommen, Fremdes verworfen", () => {
  const m = parseServerMessage({
    type: "modellzugang",
    aktion: "modell",
    art: "haus",
    hinterlegt: false,
    modelle: {
      gespraech: {
        wahl: "gemma4-31b",
        optionen: [
          { id: "gemma4-31b", name: "Gemma 4 31B", art: "haus", zeile: "Güte 92 %" },
          { id: "GROSS", name: "x", art: "haus", zeile: "" },
          { id: "gut-aber-art", name: "x", art: "cloud", zeile: "" },
          { id: "../x", name: "x", art: "haus", zeile: "" },
          "kein Objekt",
        ],
      },
      bilder: { wahl: "nicht-angeboten", optionen: [{ id: "wamo-vision", name: "Bild‮modell", art: "haus", zeile: "z".repeat(400) }] },
      fremd: { wahl: "x", optionen: [] },
    },
    modell_sperre: "gesperrt",
    haus_stimme: "ryan",
    haus_stimme_standard: "sohee",
    haus_stimmen: [{ id: "sohee", name: "Sohee", hinweis: "Vorschlag" }, { id: "Böse", name: "x" }, { id: "ryan", name: "Ryan" }],
    haus_stimmen_hinweis: "Keine der neun Stimmen ist nativ deutsch.",
  });
  assert.ok(m && m.type === "modellzugang");
  assert.equal(m.aktion, "modell");
  assert.deepEqual(m.modelle?.gespraech?.optionen.map((o) => o.id), ["gemma4-31b"]);
  assert.equal(m.modelle?.gespraech?.wahl, "gemma4-31b");
  assert.equal(m.modelle?.bilder?.wahl, AUTOMATISCH); // nicht im Angebot: automatisch
  assert.equal(m.modelle?.bilder?.optionen[0].name, "Bildmodell"); // Bidi-Zeichen entfernt
  assert.equal(m.modelle?.bilder?.optionen[0].zeile.length, 160);
  assert.equal(Object.keys(m.modelle ?? {}).includes("fremd"), false);
  assert.equal(m.modellSperre, "gesperrt");
  assert.equal(m.hausStimme, "ryan");
  assert.equal(m.hausStimmeStandard, "sohee");
  assert.deepEqual(m.hausStimmen?.map((s) => s.id), ["sohee", "ryan"]);
  const alt = parseServerMessage({ type: "modellzugang", aktion: "status", modelle: "x", haus_stimme: "DROP", haus_stimmen: [] });
  assert.ok(alt && alt.type === "modellzugang");
  assert.equal(alt.modelle, undefined);
  assert.equal(alt.hausStimme, undefined);
  assert.equal(alt.hausStimmen, undefined);
  assert.equal(parseServerMessage({ type: "modellzugang", aktion: "loeschen_alles" }), null);
});
