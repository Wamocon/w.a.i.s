// Tests für die gespeicherten Entwicklungsaufträge (lib/auftragEntwuerfe.ts, Servernachricht "auftrag_entwuerfe" in lib/nachrichten.ts):
// Prüfung der Nachricht, Zustand nach jeder Antwort, die Karte verlässt die Ansicht nur nach einem gelungenen Speichern.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ENTWUERFE_LEER,
  auftraegeNachEntwurf,
  entwuerfeNachAntwort,
  entwurfAnsage,
  entwurfDatum,
  entwurfIso,
  speichernMoeglich,
  type EntwurfAntwort,
} from "./auftragEntwuerfe.ts";
import { ENTWURF_LISTE_MAX, parseServerMessage, type Auftrag } from "./nachrichten.ts";

const ID = "11111111-2222-4333-8444-555555555555";
const EINTRAG = { id: ID, titel: "Baue die App", projekt: "rezepte-app", art: "umsetzung", gespeichert_ms: 1_763_456_400_000 };

function antwort(extra: Record<string, unknown>): EntwurfAntwort {
  const m = parseServerMessage({ type: "auftrag_entwuerfe", aktion: "liste", ok: true, text: "", ...extra });
  assert.ok(m && m.type === "auftrag_entwuerfe", JSON.stringify(extra));
  return m;
}

test("die Liste kommt geprüft an: Kennung, Texte einzeilig, Repo nur owner/name, Zeitpunkt", () => {
  const m = antwort({ entwuerfe: [{ ...EINTRAG, repo: "acme/rezepte-app" }], max: 50 });
  assert.deepEqual(m.entwuerfe, [
    { id: ID, titel: "Baue die App", projekt: "rezepte-app", art: "umsetzung", repo: "acme/rezepte-app", gespeichertMs: 1_763_456_400_000 },
  ]);
  assert.equal(m.max, 50);
});

test("Einträge ohne gültige Kennung fallen weg, Steuerzeichen und Umbrüche verschwinden, falsche Repos auch", () => {
  const m = antwort({
    entwuerfe: [
      { ...EINTRAG, id: "keine-uuid" },
      { ...EINTRAG, titel: "Zeile‮eins\nzwei", repo: "kein repo", gespeichert_ms: -5 },
      "kein Objekt",
    ],
  });
  assert.equal(m.entwuerfe?.length, 1);
  assert.equal(m.entwuerfe?.[0].titel, "Zeileeins zwei");
  assert.equal(m.entwuerfe?.[0].repo, undefined);
  assert.equal(m.entwuerfe?.[0].gespeichertMs, 0);
});

test("höchstens 50 Einträge, der Titel höchstens 80 Zeichen", () => {
  const viele = Array.from({ length: 80 }, (_, i) => ({ ...EINTRAG, id: ID.slice(0, -2) + String(i).padStart(2, "0") }));
  assert.equal(antwort({ entwuerfe: viele }).entwuerfe?.length, ENTWURF_LISTE_MAX);
  assert.ok((antwort({ entwuerfe: [{ ...EINTRAG, titel: "x".repeat(500) }] }).entwuerfe?.[0].titel.length ?? 0) <= 80);
});

test("unbekannte Aktion oder fehlendes ok: keine Nachricht; ok false trägt den Grund als Text", () => {
  assert.equal(parseServerMessage({ type: "auftrag_entwuerfe", aktion: "update", ok: true }), null);
  assert.equal(parseServerMessage({ type: "auftrag_entwuerfe", aktion: "liste" }), null);
  const m = antwort({ aktion: "laden", ok: false, grund: "Dieser gespeicherte Auftrag ist nicht mehr da." });
  assert.equal(m.text, "Dieser gespeicherte Auftrag ist nicht mehr da.");
  assert.equal(antwort({ aktion: "laden", ok: false }).text, "Das ging nicht.");
});

test("Zustand: die erste Antwort legt ihn an, eine stille Liste meldet nichts, die passende Antwort beendet das Warten", () => {
  const leer = entwuerfeNachAntwort(null, antwort({ entwuerfe: [] }));
  assert.deepEqual(leer, ENTWUERFE_LEER);
  assert.ok(leer);
  const wartend = { ...leer, wartet: { aktion: "speichern" as const, kennung: "j1", n: 1 } };
  const fehler = entwuerfeNachAntwort(
    wartend,
    antwort({ aktion: "speichern", ok: false, job: "j1", grund: "Die Datenbank ist nicht erreichbar." }),
  );
  assert.ok(fehler);
  assert.equal(fehler.wartet, null);
  assert.deepEqual(fehler.meldung, { n: 1, ok: false, aktion: "speichern", text: "Die Datenbank ist nicht erreichbar." });
  assert.deepEqual(fehler.liste, []); // ohne mitgeschickte Liste bleibt die bisherige
  const gut = entwuerfeNachAntwort(fehler, antwort({ aktion: "speichern", ok: true, text: "Gespeichert.", entwuerfe: [EINTRAG] }));
  assert.ok(gut);
  assert.equal(gut.meldung?.n, 2);
  assert.equal(gut.liste.length, 1);
  assert.equal(entwuerfeNachAntwort(gut, antwort({ entwuerfe: [] }))?.meldung, gut.meldung);
});

test("eine gescheiterte Liste ohne Zustand legt keinen an: dann gibt es weder Knopf noch Liste", () => {
  assert.equal(entwuerfeNachAntwort(null, antwort({ ok: false, grund: "Gespeicherte Aufträge gibt es in dieser Sitzung nicht." })), null);
  const da = entwuerfeNachAntwort(ENTWUERFE_LEER, antwort({ ok: false, grund: "Die Datenbank ist nicht erreichbar." }));
  assert.equal(da?.meldung?.ok, false); // mit Zustand bleibt die Liste und der Grund steht da
});

test("eine Meldung, die der Kern von sich aus schickt (Speichern per Sprache), beendet ein anderes Warten nicht", () => {
  const wartend = { ...ENTWUERFE_LEER, wartet: { aktion: "laden" as const, kennung: ID, n: 3 } };
  const perSprache = entwuerfeNachAntwort(wartend, antwort({ aktion: "speichern", ok: true, job: "j7", text: "Gespeichert." }));
  assert.deepEqual(perSprache?.wartet, wartend.wartet);
  const andereKarte = { ...ENTWUERFE_LEER, wartet: { aktion: "speichern" as const, kennung: "j1", n: 4 } };
  assert.deepEqual(entwuerfeNachAntwort(andereKarte, antwort({ aktion: "speichern", ok: true, job: "j7" }))?.wartet, andereKarte.wartet);
  assert.equal(entwuerfeNachAntwort(wartend, antwort({ aktion: "laden", ok: true, job: "neu", text: "Geladen." }))?.wartet, null);
});

test("ein Erfolg ohne Text ist keine Meldung und keine Ansage", () => {
  const m = antwort({ aktion: "loeschen", ok: true });
  assert.equal(entwuerfeNachAntwort(ENTWUERFE_LEER, m)?.meldung, null);
  assert.equal(entwurfAnsage(m), null);
});

test("ein unmöglicher Zeitpunkt wird zu 0 und bringt die Anzeige nicht zum Absturz", () => {
  for (const ms of [1e17, -1, Number.NaN, 5, Date.UTC(2101, 0, 1)]) {
    assert.equal(antwort({ entwuerfe: [{ ...EINTRAG, gespeichert_ms: ms }] }).entwuerfe?.[0].gespeichertMs, 0, String(ms));
  }
  assert.equal(entwurfDatum(1e17), "");
  assert.equal(entwurfIso(1e17), "");
  assert.equal(entwurfIso(Date.UTC(2026, 10, 18, 9)), "2026-11-18T09:00:00.000Z");
});

test("die Karte verlässt die Ansicht nur nach einem gelungenen Speichern genau dieser Karte", () => {
  const karten: Auftrag[] = [
    { job: "j1", projekt: "a", art: "Analyse", auftrag: "A", abnahme: [] },
    { job: "j2", projekt: "b", art: "Analyse", auftrag: "B", abnahme: [] },
  ];
  assert.deepEqual(
    auftraegeNachEntwurf(karten, antwort({ aktion: "speichern", ok: true, job: "j1" })).map((a) => a.job),
    ["j2"],
  );
  assert.equal(auftraegeNachEntwurf(karten, antwort({ aktion: "speichern", ok: false, job: "j1", grund: "x" })), karten);
  assert.equal(auftraegeNachEntwurf(karten, antwort({ aktion: "laden", ok: true, job: "j1" })), karten);
  assert.equal(auftraegeNachEntwurf(karten, antwort({ aktion: "speichern", ok: true, job: "j9" })), karten);
});

test("Ansage, Speichern nur vor dem Senden, Datum", () => {
  assert.equal(entwurfAnsage(antwort({})), null);
  assert.equal(entwurfAnsage(antwort({ aktion: "loeschen", ok: true, text: "Gelöscht." })), "Gelöscht.");
  assert.match(entwurfAnsage(antwort({ aktion: "laden", ok: false, grund: "Weg." })) ?? "", /^Gespeicherte Aufträge: Weg\.$/);
  assert.equal(speichernMoeglich({}), true);
  assert.equal(speichernMoeglich({ stand: { phase: "abgelehnt", grund: "x" } }), true);
  assert.equal(speichernMoeglich({ stand: { phase: "wartet", seitMs: 0 } }), false);
  assert.equal(speichernMoeglich({ stand: { phase: "ohneQuittung", seitMs: 0 } }), false);
  assert.equal(entwurfDatum(Date.UTC(2026, 10, 18, 9)), "18.11.2026");
  assert.equal(entwurfDatum(0), "");
});
