// Tests für die Aufträge an W.A.I.S. selbst (lib/selbstAuftraege.ts, Servernachricht "selbstauftraege" in lib/nachrichten.ts):
// strenge Prüfung der Nachricht, Zustand nach jeder Antwort, Prüfung der Eingaben im Formular.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseServerMessage } from "./nachrichten.ts";
import {
  SELBST_ARTEN,
  SELBST_BESCHREIBUNG_MAX,
  SELBST_LEER,
  SELBST_LISTE_MAX,
  SELBST_TITEL_MAX,
  artName,
  selbstDarfOeffnen,
  selbstDarfVerwerfen,
  selbstEingabeFehler,
  selbstEingabePruefen,
  selbstNachAntwort,
  selbstNummer,
  selbstZeichen,
  type SelbstAntwort,
  type SelbstStand,
} from "./selbstAuftraege.ts";

const EINTRAG = {
  nr: 7,
  titel: "Der Verlauf lädt zu langsam",
  art: "fehlerbehebung",
  prioritaet: 1,
  status: "offen",
  quelle: "sprache",
  unsicher: false,
  erstellt_ms: 1_763_456_400_000,
};

function antwort(extra: Record<string, unknown>): SelbstAntwort {
  const m = parseServerMessage({ type: "selbstauftraege", aktion: "liste", ok: true, ...extra });
  assert.ok(m && m.type === "selbstauftraege", JSON.stringify(extra));
  return m;
}

// ---------- Prüfung der Nachricht ----------

test("die Liste kommt geprüft an: Felder, Aufzählungen und Zeitpunkt", () => {
  const m = antwort({
    auftraege: [{ ...EINTRAG, bearbeiter: "claude_code", ergebnis: "Behoben in Version 0.7.0." }],
    max: 200,
  });
  assert.deepEqual(m.auftraege, [
    {
      nr: 7,
      titel: "Der Verlauf lädt zu langsam",
      art: "fehlerbehebung",
      prioritaet: 1,
      status: "offen",
      quelle: "sprache",
      unsicher: false,
      erstelltMs: 1_763_456_400_000,
      bearbeiter: "claude_code",
      ergebnis: "Behoben in Version 0.7.0.",
    },
  ]);
  assert.equal(m.max, 200);
});

test("Einträge ohne gültige Nummer oder Status fallen weg, doppelte Nummern zählen einmal, eine unbekannte Quelle lässt nur die Quelle weg", () => {
  const m = antwort({
    auftraege: [
      EINTRAG,
      { ...EINTRAG, nr: 0 },
      { ...EINTRAG, nr: -3 },
      { ...EINTRAG, nr: 1.5 },
      { ...EINTRAG, nr: "8" },
      { ...EINTRAG, nr: Number.NaN },
      { ...EINTRAG, nr: 9, status: "blockiert" },
      { ...EINTRAG, nr: 10, quelle: "mail" },
      { ...EINTRAG, nr: 7, titel: "Zweiter Eintrag mit derselben Nummer" },
      "kein Objekt",
      null,
      [],
    ],
  });
  assert.deepEqual(
    m.auftraege?.map((a) => a.nr),
    [7, 10],
  );
  assert.equal(m.auftraege?.[0].titel, "Der Verlauf lädt zu langsam");
  assert.equal(m.auftraege?.[0].quelle, "sprache");
  assert.equal(m.auftraege?.[1].quelle, undefined);
});

test("gelesen werden höchstens doppelt so viele Einträge, wie die Liste fasst (Ungültige zählen mit)", () => {
  const unbrauchbar = Array.from({ length: SELBST_LISTE_MAX * 2 }, () => "kaputt");
  assert.deepEqual(antwort({ auftraege: [...unbrauchbar, EINTRAG] }).auftraege, []);
  assert.equal(antwort({ auftraege: [...unbrauchbar.slice(1), EINTRAG] }).auftraege?.length, 1);
});

test("bei ok false gilt grund, fehlt er, gilt text", () => {
  assert.equal(antwort({ aktion: "speichern", ok: false, text: "Nur ein Text." }).text, "Nur ein Text.");
  assert.equal(antwort({ aktion: "speichern", ok: false, grund: "Der Grund.", text: "Anderer Text." }).text, "Der Grund.");
});

test("alle vier Status und alle drei Quellen werden angenommen", () => {
  const status = ["offen", "in_arbeit", "erledigt", "verworfen"];
  const quellen = ["sprache", "oberflaeche", "claude_code"];
  const m = antwort({
    auftraege: [
      ...status.map((s, i) => ({ ...EINTRAG, nr: i + 1, status: s })),
      ...quellen.map((q, i) => ({ ...EINTRAG, nr: i + 10, quelle: q })),
    ],
  });
  assert.deepEqual(
    m.auftraege?.map((a) => a.nr),
    [1, 2, 3, 4, 10, 11, 12],
  );
});

test("Texte sind einzeilig und gekürzt, Steuer- und Bidi-Zeichen verschwinden, HTML bleibt Text", () => {
  const m = antwort({
    auftraege: [
      { ...EINTRAG, titel: "Zeile\u202eeins\nzwei", art: "front\u0000end" },
      { ...EINTRAG, nr: 8, titel: "x".repeat(500) },
      { ...EINTRAG, nr: 9, titel: "<img src=x onerror=alert(1)>" },
      { ...EINTRAG, nr: 10, titel: "   " },
    ],
  });
  assert.equal(m.auftraege?.[0].titel, "Zeileeins zwei");
  assert.equal(m.auftraege?.[0].art, "frontend");
  assert.ok((m.auftraege?.[1].titel.length ?? 0) <= SELBST_TITEL_MAX);
  assert.equal(m.auftraege?.[2].titel, "<img src=x onerror=alert(1)>"); // wird nie als HTML gesetzt, React schreibt es als Text
  assert.equal(m.auftraege?.[3].titel, "Auftrag"); // ohne lesbaren Titel ein Platzhalter, der Eintrag bleibt bedienbar
});

test("Priorität nur 1 bis 3, sonst normal; unsicher nur bei genau true", () => {
  const m = antwort({
    auftraege: [
      { ...EINTRAG, nr: 1, prioritaet: 3 },
      { ...EINTRAG, nr: 2, prioritaet: 0 },
      { ...EINTRAG, nr: 3, prioritaet: "1" },
      { ...EINTRAG, nr: 4, prioritaet: 2.5 },
      { ...EINTRAG, nr: 5, unsicher: "true" },
      { ...EINTRAG, nr: 6, unsicher: 1 },
      { ...EINTRAG, nr: 7, unsicher: true },
    ],
  });
  assert.deepEqual(
    m.auftraege?.map((a) => a.prioritaet),
    [3, 2, 2, 2, 1, 1, 1],
  );
  assert.deepEqual(
    m.auftraege?.map((a) => a.unsicher),
    [false, false, false, false, false, false, true],
  );
});

test("Bearbeiter nur bekannt, Ergebnis nur als bereinigter Text, leer heißt keines", () => {
  const m = antwort({
    auftraege: [
      { ...EINTRAG, nr: 1, bearbeiter: "wais", ergebnis: "Zeile eins\nZeile zwei\u0000" },
      { ...EINTRAG, nr: 2, bearbeiter: "jemand", ergebnis: "   " },
      { ...EINTRAG, nr: 3, bearbeiter: 5, ergebnis: 42 },
      { ...EINTRAG, nr: 4, ergebnis: "y".repeat(5000) },
      { ...EINTRAG, nr: 5, ergebnis: "a\n\n\n\n\nb" },
    ],
  });
  const a = m.auftraege ?? [];
  assert.equal(a[0].bearbeiter, "wais");
  assert.equal(a[0].ergebnis, "Zeile eins\nZeile zwei");
  assert.equal(a[1].bearbeiter, undefined);
  assert.equal(a[1].ergebnis, undefined);
  assert.equal(a[2].bearbeiter, undefined);
  assert.equal(a[2].ergebnis, undefined);
  assert.ok((a[3].ergebnis?.length ?? 0) < 2100);
  assert.equal(a[4].ergebnis, "a\n\nb");
});

test("ein unmöglicher Zeitpunkt wird zu 0", () => {
  for (const ms of [1e17, -1, Number.NaN, 5, Date.UTC(2101, 0, 1), "heute"]) {
    assert.equal(antwort({ auftraege: [{ ...EINTRAG, erstellt_ms: ms }] }).auftraege?.[0].erstelltMs, 0, String(ms));
  }
});

test("höchstens so viele Einträge, wie die Oberfläche trägt", () => {
  const viele = Array.from({ length: SELBST_LISTE_MAX + 100 }, (_, i) => ({ ...EINTRAG, nr: i + 1 }));
  assert.equal(antwort({ auftraege: viele }).auftraege?.length, SELBST_LISTE_MAX);
});

test("unbekannte Aktion oder fehlendes ok: keine Nachricht; ok false trägt den Grund als Text", () => {
  assert.equal(parseServerMessage({ type: "selbstauftraege", aktion: "loeschen", ok: true }), null);
  assert.equal(parseServerMessage({ type: "selbstauftraege", aktion: "liste" }), null);
  assert.equal(parseServerMessage({ type: "selbstauftraege", aktion: "liste", ok: "ja" }), null);
  const m = antwort({ aktion: "speichern", ok: false, grund: "Der Titel fehlt." });
  assert.equal(m.text, "Der Titel fehlt.");
  assert.equal(m.ok, false);
  assert.equal(antwort({ aktion: "verwerfen", ok: false }).text, "Das ging nicht.");
  assert.equal(antwort({ aktion: "oeffnen", text: "Wieder offen." }).text, "Wieder offen.");
  assert.equal(antwort({}).text, "");
});

test("max nur als ganze Zahl im Wertebereich, auftraege nur als Liste", () => {
  assert.equal(antwort({ max: 0 }).max, undefined);
  assert.equal(antwort({ max: 1.5 }).max, undefined);
  assert.equal(antwort({ max: "50" }).max, undefined);
  assert.equal(antwort({ max: 99_999_999 }).max, undefined);
  assert.equal(antwort({ max: 50 }).max, 50);
  assert.equal(antwort({ auftraege: "nichts" }).auftraege, undefined);
  assert.equal(antwort({ auftraege: { 0: EINTRAG } }).auftraege, undefined);
  assert.deepEqual(antwort({ auftraege: [] }).auftraege, []);
});

// ---------- Zustand ----------

test("die erste gelungene Liste legt den Zustand an, alles andere lässt ihn weg (dann bleibt die Oberfläche unsichtbar)", () => {
  assert.equal(selbstNachAntwort(null, antwort({ ok: false, grund: "Das gibt es hier nicht." })), null);
  assert.equal(selbstNachAntwort(null, antwort({ ok: true })), null); // ok ohne Liste zählt nicht
  assert.equal(selbstNachAntwort(null, antwort({ aktion: "speichern", ok: false, grund: "x", auftraege: [EINTRAG] })), null);
  assert.equal(selbstNachAntwort(null, antwort({ aktion: "speichern", ok: true })), null);
  const da = selbstNachAntwort(null, antwort({ auftraege: [], max: 200 }));
  assert.ok(da);
  assert.deepEqual(da.liste, []);
  assert.equal(da.max, 200);
  assert.equal(da.meldung, null); // eine gelungene Liste ist keine Meldung
  assert.equal(da.wartet, null);
  assert.deepEqual(SELBST_LEER.liste, []);
});

test("jede Antwort außer der stillen Liste ist eine Meldung, mit Standardtext, wenn der Kern keinen schickt", () => {
  const stand = selbstNachAntwort(null, antwort({ auftraege: [EINTRAG] })) as SelbstStand;
  const gespeichert = selbstNachAntwort(stand, antwort({ aktion: "speichern", text: "Gespeichert als SA-8.", auftraege: [EINTRAG] }));
  assert.deepEqual(gespeichert?.meldung, { n: 1, ok: true, aktion: "speichern", text: "Gespeichert als SA-8." });
  const stumm = selbstNachAntwort(gespeichert, antwort({ aktion: "speichern", auftraege: [EINTRAG] }));
  assert.deepEqual(stumm?.meldung, { n: 2, ok: true, aktion: "speichern", text: "Gespeichert." });
  assert.equal(selbstNachAntwort(stumm, antwort({ aktion: "verwerfen" }))?.meldung?.text, "Verworfen.");
  assert.equal(selbstNachAntwort(stumm, antwort({ aktion: "oeffnen" }))?.meldung?.text, "Wieder geöffnet.");
  const still = selbstNachAntwort(stumm, antwort({ auftraege: [EINTRAG] }));
  assert.equal(still?.meldung, stumm?.meldung); // die stille Liste ändert die Meldung nicht
});

test("eine Antwort ohne Liste lässt die bisherige stehen, mit Liste ersetzt sie; max bleibt, wenn keines kommt", () => {
  const stand = selbstNachAntwort(null, antwort({ auftraege: [EINTRAG], max: 100 })) as SelbstStand;
  const fehler = selbstNachAntwort(stand, antwort({ aktion: "verwerfen", ok: false, grund: "Diesen Auftrag gibt es nicht." }));
  assert.deepEqual(fehler?.liste, stand.liste);
  assert.equal(fehler?.max, 100);
  assert.equal(fehler?.meldung?.ok, false);
  const neu = selbstNachAntwort(fehler, antwort({ auftraege: [{ ...EINTRAG, nr: 9 }, EINTRAG] }));
  assert.deepEqual(
    neu?.liste.map((a) => a.nr),
    [9, 7],
  ); // so sortiert, wie der Kern liefert
  assert.equal(neu?.max, 100);
});

test("nur die Antwort auf dieselbe Aktion beendet das Warten", () => {
  const stand = selbstNachAntwort(null, antwort({ auftraege: [EINTRAG] })) as SelbstStand;
  const wartend: SelbstStand = { ...stand, wartet: { aktion: "verwerfen", n: 3 } };
  assert.deepEqual(selbstNachAntwort(wartend, antwort({ aktion: "speichern", auftraege: [EINTRAG] }))?.wartet, wartend.wartet);
  assert.deepEqual(selbstNachAntwort(wartend, antwort({ auftraege: [EINTRAG] }))?.wartet, wartend.wartet);
  assert.equal(selbstNachAntwort(wartend, antwort({ aktion: "verwerfen", auftraege: [EINTRAG] }))?.wartet, null);
  assert.equal(selbstNachAntwort(wartend, antwort({ aktion: "verwerfen", ok: false, grund: "Nein." }))?.wartet, null);
});

test("eine verspätete Antwort entsperrt kein neues Warten derselben Aktion, die zweite tut es", () => {
  const stand = selbstNachAntwort(null, antwort({ auftraege: [EINTRAG] })) as SelbstStand;
  assert.equal(stand.verspaetet, null);
  // Frist abgelaufen (wamo.ts), danach ein zweiter Versuch derselben Aktion
  const zweiterVersuch: SelbstStand = { ...stand, wartet: { aktion: "verwerfen", n: 2 }, verspaetet: "verwerfen" };
  const spaet = selbstNachAntwort(zweiterVersuch, antwort({ aktion: "verwerfen", text: "Verworfen." }));
  assert.deepEqual(spaet?.wartet, { aktion: "verwerfen", n: 2 }); // bleibt gesperrt
  assert.equal(spaet?.verspaetet, null);
  assert.equal(spaet?.meldung?.text, "Verworfen."); // die späte Antwort ist trotzdem eine Meldung
  const zweite = selbstNachAntwort(spaet, antwort({ aktion: "verwerfen", text: "Verworfen." }));
  assert.equal(zweite?.wartet, null);
  assert.equal(zweite?.meldung?.n, 2);
  // eine verspätete Antwort auf eine andere Aktion ändert nichts am Merker
  const andere = selbstNachAntwort(zweiterVersuch, antwort({ aktion: "oeffnen", text: "Wieder geöffnet." }));
  assert.equal(andere?.verspaetet, "verwerfen");
  assert.deepEqual(andere?.wartet, { aktion: "verwerfen", n: 2 });
});

// ---------- Hilfen ----------

test("Nummer, Art und Bedienbarkeit", () => {
  assert.equal(selbstNummer(7), "SA-7");
  assert.equal(artName("fehlerbehebung"), "Fehlerbehebung");
  assert.equal(artName("frontend"), "Frontend");
  assert.equal(artName("etwas anderes"), "etwas anderes");
  assert.equal(artName(""), "");
  for (const unart of ["constructor", "toString", "__proto__", "hasOwnProperty"]) assert.equal(artName(unart), unart);
  assert.equal(SELBST_ARTEN.length, 13);
  assert.equal(SELBST_ARTEN[0], "umsetzung");
  assert.equal(selbstDarfVerwerfen("offen"), true);
  assert.equal(selbstDarfVerwerfen("in_arbeit"), true);
  assert.equal(selbstDarfVerwerfen("erledigt"), false);
  assert.equal(selbstDarfVerwerfen("verworfen"), false);
  assert.equal(selbstDarfOeffnen("verworfen"), true);
  assert.equal(selbstDarfOeffnen("offen"), false);
  assert.equal(selbstDarfOeffnen("erledigt"), false);
});

// ---------- Eingaben ----------

test("Titel und Beschreibung: leer, zu lang, genau an der Grenze, Zählung in Zeichen", () => {
  const gut = { titel: "Verlauf beschleunigen", beschreibung: "Der Verlauf soll schneller laden." };
  assert.equal(selbstEingabeFehler(gut), null);
  assert.match(selbstEingabeFehler({ ...gut, titel: "" }) ?? "", /Titel/);
  assert.match(selbstEingabeFehler({ ...gut, titel: "   \n " }) ?? "", /Titel/);
  assert.equal(selbstEingabeFehler({ ...gut, titel: "x".repeat(SELBST_TITEL_MAX) }), null);
  assert.match(selbstEingabeFehler({ ...gut, titel: "x".repeat(SELBST_TITEL_MAX + 1) }) ?? "", /höchstens 80 Zeichen/);
  assert.equal(selbstEingabeFehler({ ...gut, titel: "😀".repeat(SELBST_TITEL_MAX) }), null); // ein Emoji ist ein Zeichen, wie der Kern zählt
  assert.match(selbstEingabeFehler({ ...gut, beschreibung: "" }) ?? "", /Beschreib/);
  assert.match(selbstEingabeFehler({ ...gut, beschreibung: " \n " }) ?? "", /Beschreib/);
  assert.equal(selbstEingabeFehler({ ...gut, beschreibung: "y".repeat(SELBST_BESCHREIBUNG_MAX) }), null);
  assert.match(selbstEingabeFehler({ ...gut, beschreibung: "y".repeat(SELBST_BESCHREIBUNG_MAX + 1) }) ?? "", /höchstens 4000 Zeichen/);
});

test("die Prüfung nennt das Feld, das zuerst nicht stimmt", () => {
  assert.equal(selbstEingabePruefen({ titel: "", beschreibung: "" })?.feld, "titel");
  assert.equal(selbstEingabePruefen({ titel: "a", beschreibung: "" })?.feld, "beschreibung");
  assert.equal(selbstEingabePruefen({ titel: "x".repeat(81), beschreibung: "" })?.feld, "titel");
  assert.equal(selbstEingabePruefen({ titel: "a", beschreibung: "b" }), null);
  assert.equal(selbstZeichen("  abc \n"), 3);
  assert.equal(selbstZeichen("😀😀"), 2);
});

test("kein Gedankenstrich in den Texten der Prüfung", () => {
  const texte = [
    selbstEingabeFehler({ titel: "", beschreibung: "a" }),
    selbstEingabeFehler({ titel: "x".repeat(99), beschreibung: "a" }),
    selbstEingabeFehler({ titel: "a", beschreibung: "" }),
    selbstEingabeFehler({ titel: "a", beschreibung: "y".repeat(5000) }),
  ];
  for (const t of texte) {
    assert.ok(t);
    assert.ok(!t.includes(String.fromCharCode(0x2013)) && !t.includes(String.fromCharCode(0x2014)), t);
  }
});
