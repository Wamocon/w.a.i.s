// Tests für die Logik des geführten Modellzugangs beim Ausrollen (lib/einrichtungSchritte.ts, Entscheidung D2):
// erst der Claude-Code-Token, dann der API-Schlüssel, beide überspringbar, danach eine Zusammenfassung je Fall.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FAELLE,
  fallAus,
  MODELL_SCHRITTE,
  nachbarSchritt,
  SCHRITT_FRAGE,
  SCHRITT_TITEL,
  schrittFolge,
  schrittPosition,
  schrittSichtbar,
  schrittStand,
  weiterText,
  wirksamerSchritt,
  zusammenfassung,
  type Fall,
} from "./einrichtungSchritte.ts";
import type { Modellzugang } from "./nachrichten.ts";

const LEER: Modellzugang = { aktion: "status", art: "haus", quelle: "keiner", hinterlegt: false, festgelegt: false, codeHinterlegt: false };
const NUR_TOKEN: Modellzugang = { ...LEER, codeHinterlegt: true, codeEnde: "abcd" };
const NUR_API: Modellzugang = { ...LEER, art: "claude", quelle: "profil", hinterlegt: true, ende: "wxyz" };
const BEIDES: Modellzugang = { ...NUR_API, codeHinterlegt: true, codeEnde: "abcd" };
const FESTGELEGT: Modellzugang = { ...BEIDES, art: "haus", quelle: "festgelegt", festgelegt: true };
const WAHL: Modellzugang = { ...BEIDES, art: "haus", quelle: "wahl", modus: "nur_haus" };
const ZUORDNUNG: Modellzugang = { ...LEER, art: "claude", quelle: "zuordnung" };

const GEDANKENSTRICH = /[–—]|\s-\s/;

test("Reihenfolge: zuerst der Token, dann der API-Schlüssel, dann die Zusammenfassung", () => {
  assert.deepEqual([...MODELL_SCHRITTE], ["token", "api", "zusammenfassung"]);
  for (const stand of [null, LEER, NUR_TOKEN, NUR_API, BEIDES, WAHL, ZUORDNUNG]) {
    const folge = schrittFolge(stand);
    assert.deepEqual(folge, ["token", "api", "zusammenfassung"]);
    assert.ok(folge.indexOf("token") < folge.indexOf("api"));
  }
});

test("vom Admin auf Hausmodelle festgelegt: beide Schritte entfallen, die Zusammenfassung bleibt", () => {
  assert.deepEqual(schrittFolge(FESTGELEGT), ["zusammenfassung"]);
  assert.equal(schrittSichtbar("token", FESTGELEGT), false);
  assert.equal(schrittSichtbar("api", FESTGELEGT), false);
  assert.equal(schrittSichtbar("zusammenfassung", FESTGELEGT), true);
  assert.equal(schrittSichtbar("installer", FESTGELEGT), true);
  // Stand noch unbekannt: alle Schritte, der Schritt selbst zeigt "wird geladen"
  assert.equal(schrittSichtbar("token", null), true);
});

test("ein Schritt mit hinterlegtem Wert zeigt nur das Ende und bietet Weiter, sonst Überspringen", () => {
  assert.deepEqual(schrittStand("token", NUR_TOKEN), { hinterlegt: true, text: "Hinterlegt, endet auf …abcd." });
  assert.deepEqual(schrittStand("api", NUR_TOKEN), { hinterlegt: false, text: "Nicht hinterlegt." });
  assert.deepEqual(schrittStand("api", NUR_API), { hinterlegt: true, text: "Hinterlegt, endet auf …wxyz." });
  assert.deepEqual(schrittStand("token", null), { hinterlegt: false, text: "Nicht hinterlegt." });
  // ohne gemeldetes Ende kein Platzhalter, der nach einem Wert aussieht
  assert.deepEqual(schrittStand("token", { ...LEER, codeHinterlegt: true }), { hinterlegt: true, text: "Hinterlegt." });
  assert.equal(weiterText("token", NUR_TOKEN), "Weiter");
  assert.equal(weiterText("api", NUR_TOKEN), "Überspringen");
  assert.equal(weiterText("api", BEIDES), "Weiter");
  assert.equal(weiterText("token", null), "Überspringen");
});

test("Position, Nachbarn und wirksamer Schritt", () => {
  const folge = schrittFolge(LEER);
  assert.deepEqual(schrittPosition(folge, "token"), { nummer: 1, gesamt: 3, text: "Schritt 1 von 3" });
  assert.deepEqual(schrittPosition(folge, "zusammenfassung"), { nummer: 3, gesamt: 3, text: "Schritt 3 von 3" });
  assert.equal(nachbarSchritt(folge, "token", 1), "api");
  assert.equal(nachbarSchritt(folge, "api", 1), "zusammenfassung");
  assert.equal(nachbarSchritt(folge, "zusammenfassung", 1), null);
  assert.equal(nachbarSchritt(folge, "token", -1), null);
  assert.equal(nachbarSchritt(folge, "api", -1), "token");
  // wird der gewählte Schritt unsichtbar (Stand kommt als festgelegt an), gilt der nächste sichtbare danach
  const alle = ["token", "api", "zusammenfassung", "installer"] as const;
  assert.equal(wirksamerSchritt(alle, ["zusammenfassung", "installer"], "token"), "zusammenfassung");
  assert.equal(wirksamerSchritt(alle, ["token", "api", "zusammenfassung"], "api"), "api");
  assert.equal(wirksamerSchritt(alle, ["token"], "installer"), "token");
  assert.equal(wirksamerSchritt(alle, [], "token"), null);
});

test("Fall aus dem Stand: alle sieben Fälle", () => {
  const erwartet: [Modellzugang, Fall][] = [
    [BEIDES, "beides"],
    [NUR_TOKEN, "nur_token"],
    [NUR_API, "nur_api"],
    [LEER, "nichts"],
    [FESTGELEGT, "festgelegt"],
    [WAHL, "wahl"],
    [ZUORDNUNG, "zuordnung"],
  ];
  for (const [stand, fall] of erwartet) assert.equal(fallAus(stand), fall, fall);
  assert.deepEqual([...FAELLE].sort(), erwartet.map(([, f]) => f).sort());
});

test("Fall: festgelegt geht vor allem, Wahl der Person vor den Schlüsseln, Modus allein genügt", () => {
  assert.equal(fallAus({ ...FESTGELEGT, quelle: undefined }), "festgelegt");
  assert.equal(fallAus({ ...NUR_API, modus: "nur_haus", quelle: undefined }), "wahl");
  assert.equal(fallAus({ ...ZUORDNUNG, codeHinterlegt: true }), "zuordnung");
  // unbekannter oder nicht lesbarer Stand: kein Fall (die Oberfläche zeigt "wird geladen" oder den Fehler)
  assert.equal(fallAus(null), null);
  assert.equal(fallAus({ aktion: "status", hinterlegt: false, festgelegt: false, codeHinterlegt: false, fehler: "Kern weg" }), null);
});

const zeile = (fall: Fall, name: string) => zusammenfassung(fall).zeilen.find((z) => z.name === name)?.text ?? "";
const GESPRAECH = "Gespräch, Lernen und Websuche";

test("Zusammenfassung: drei Zeilen je Fall, Stimme immer Soniox", () => {
  for (const fall of FAELLE) {
    const z = zusammenfassung(fall);
    assert.equal(z.titel, "So arbeitet W.A.I.S. für dich");
    assert.deepEqual(z.zeilen.map((x) => x.name), [GESPRAECH, "Entwicklungsaufträge", "Stimme"], fall);
    assert.match(zeile(fall, "Stimme"), /Soniox/, fall);
    assert.match(z.aendern, /Einstellungen, Modellzugang/, fall);
  }
});

test("Zusammenfassung beides: Haiku über den eigenen Schlüssel, Claude Code mit dem Token (Max-Tarif, Sonnet)", () => {
  assert.match(zeile("beides", GESPRAECH), /Claude Haiku über deinen eigenen Schlüssel/);
  assert.match(zeile("beides", "Entwicklungsaufträge"), /Claude Code mit deinem Token \(Max-Tarif, Sonnet\)/);
});

test("Zusammenfassung nur Token (Mischfall): Gespräch über Hausmodelle, Entwicklungsaufträge mit dem Token", () => {
  assert.match(zeile("nur_token", GESPRAECH), /^Hausmodelle/);
  assert.match(zeile("nur_token", GESPRAECH), /Max-Tarif deckt das Gespräch nicht ab/);
  assert.match(zeile("nur_token", "Entwicklungsaufträge"), /Claude Code mit deinem Token \(Max-Tarif, Sonnet\)/);
});

test("Zusammenfassung nur API-Schlüssel: Haiku, Claude Code mit dem API-Schlüssel (Guthaben, Haiku)", () => {
  assert.match(zeile("nur_api", GESPRAECH), /Claude Haiku über deinen eigenen Schlüssel/);
  assert.match(zeile("nur_api", "Entwicklungsaufträge"), /Claude Code mit deinem API-Schlüssel \(Guthaben, Haiku\)/);
});

test("Zusammenfassung nichts: Hausmodelle für alles, Entwicklungsaufträge über Hausmodelle, sobald sie bereit sind", () => {
  assert.match(zeile("nichts", GESPRAECH), /Hausmodelle für alles/);
  assert.match(zeile("nichts", "Entwicklungsaufträge"), /Hausmodelle, sobald sie dafür bereit/);
});

test("Zusammenfassung festgelegt und Wahl: alles über Hausmodelle, nichts geht an Anthropic", () => {
  for (const fall of ["festgelegt", "wahl"] as const) {
    assert.match(zeile(fall, GESPRAECH), /Alles über Hausmodelle, nichts geht an Anthropic/, fall);
    assert.match(zeile(fall, "Entwicklungsaufträge"), /Hausmodelle/, fall);
    assert.ok(zusammenfassung(fall).hinweis, fall);
  }
  assert.match(zusammenfassung("festgelegt").hinweis ?? "", /Admin/);
  assert.match(zusammenfassung("festgelegt").aendern, /nur ein Admin/);
  assert.match(zusammenfassung("wahl").hinweis ?? "", /Nur Hausmodelle/);
});

test("Zusammenfassung Zuordnung: Übergang über den Schlüssel des Kerns", () => {
  assert.match(zeile("zuordnung", GESPRAECH), /Übergang über den Schlüssel des Kerns/);
});

test("Entwicklungsaufträge ehrlich: erst, wenn sie für dich freigeschaltet sind", () => {
  for (const fall of ["beides", "nur_token", "nur_api", "nichts", "festgelegt", "wahl"] as const) {
    assert.match(zeile(fall, "Entwicklungsaufträge"), /sobald sie (dafür bereit und )?für dich freigeschaltet sind/, fall);
  }
});

test("Texte der Schritte nach D2 und Abschnitt 4.7", () => {
  assert.equal(SCHRITT_FRAGE.token, "Hast du ein Claude-Code-Konto (Max-Tarif)? Dann laufen deine Entwicklungsaufträge darüber.");
  assert.equal(
    SCHRITT_FRAGE.api,
    "Hast du einen API-Schlüssel? Dann führst du Gespräche mit Claude Haiku; ohne Token laufen auch deine Entwicklungsaufträge darüber.",
  );
  assert.equal(SCHRITT_TITEL.token, "Claude-Code-Token");
  assert.equal(SCHRITT_TITEL.api, "API-Schlüssel");
});

test("alle Texte ohne Gedankenstrich, mit dem Namen W.A.I.S. und nie mit einem Schlüssel", () => {
  const texte = [
    ...Object.values(SCHRITT_TITEL),
    ...Object.values(SCHRITT_FRAGE),
    ...FAELLE.flatMap((f) => {
      const z = zusammenfassung(f);
      return [z.titel, z.aendern, z.hinweis ?? "", ...z.zeilen.flatMap((x) => [x.name, x.text])];
    }),
    schrittStand("token", NUR_TOKEN).text,
  ];
  for (const t of texte) {
    assert.ok(!GEDANKENSTRICH.test(t), t);
    assert.ok(!/sk-ant-/.test(t), t);
    assert.ok(!/\bWAMO\b/.test(t), t);
  }
});
