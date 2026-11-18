// Tests der Historie des Canvas (lib/canvasHistorie.ts): Reiter schließen ohne Löschen, Liste der geschlossenen Reiter dieser Sitzung,
// geprüfte Antwort des Kerns (GET /wamo/api/canvas/historie) und die Zeilen der aufklappbaren Historie.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  alsHistorie,
  CANVAS_ZU_MAX,
  canvasSchluessel,
  historieZeilen,
  zuLegen,
  type Geschlossen,
} from "./canvasHistorie.ts";

type T = { id?: string | null; stelle?: string; title: string; kind: string };
const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "aaaaaaaa-0000-4000-8000-000000000002";
const C = "aaaaaaaa-0000-4000-8000-000000000003";

test("canvasSchluessel: stelle vor Kennung vor Position", () => {
  assert.equal(canvasSchluessel({ stelle: "s1", id: A }, 4), "s1");
  assert.equal(canvasSchluessel({ id: A }, 4), A);
  assert.equal(canvasSchluessel({ id: null }, 4), "#4");
  assert.equal(canvasSchluessel({}, 0), "#0");
});

test("zuLegen: geschlossene Reiter kommen vorne in die Liste, der zuletzt rechts stehende zuerst", () => {
  const zu = zuLegen<T>([], [{ id: A, title: "a", kind: "dokument" }, { id: B, title: "b", kind: "code" }], 1000);
  assert.deepEqual(
    zu.zu.map((g) => [g.item.id, g.zu]),
    [
      [B, 1000],
      [A, 1000],
    ],
  );
  assert.deepEqual(zu.verworfen, []);
  const danach = zuLegen<T>(zu.zu, [{ id: C, title: "c", kind: "tabelle" }], 2000);
  assert.deepEqual(
    danach.zu.map((g) => g.item.id),
    [C, B, A],
  );
});

test("zuLegen: dieselbe Kennung steht nur einmal in der Liste (die neue Fassung gewinnt), Elemente ohne Kennung bleiben getrennt", () => {
  const alt: Geschlossen<T>[] = [
    { item: { id: A, title: "alt", kind: "dokument" }, zu: 1 },
    { item: { id: null, title: "ohne", kind: "tabelle" }, zu: 1 },
  ];
  const r = zuLegen<T>(alt, [{ id: A, title: "neu", kind: "dokument" }, { id: null, title: "ohne 2", kind: "tabelle" }], 5);
  assert.deepEqual(
    r.zu.map((g) => g.item.title),
    ["ohne 2", "neu", "ohne"],
  );
  assert.deepEqual(r.verworfen, []); // die alte Fassung mit derselben Kennung fällt still heraus, sie ist nicht verloren
});

test("zuLegen: höchstens CANVAS_ZU_MAX Einträge, die ältesten werden verworfen und gemeldet", () => {
  const voll: Geschlossen<T>[] = Array.from({ length: CANVAS_ZU_MAX }, (_, i) => ({
    item: { id: `lokal-${i}`, title: `t${i}`, kind: "dokument" },
    zu: i,
  }));
  const r = zuLegen<T>(voll, [{ id: "lokal-neu", title: "neu", kind: "dokument" }], 99);
  assert.equal(r.zu.length, CANVAS_ZU_MAX);
  assert.equal(r.zu[0].item.id, "lokal-neu");
  assert.deepEqual(
    r.verworfen.map((x) => x.id),
    [`lokal-${CANVAS_ZU_MAX - 1}`],
  );
});

test("alsHistorie: nur gültige Einträge, Texte bereinigt, unbekannte Art und kaputte Kennung fallen weg", () => {
  const h = alsHistorie({
    eigene: [
      { id: A, titel: "Angebot", art: "dokument", zeit: "2026-11-18T09:01:00+00:00" },
      { id: "keine-uuid", titel: "x", art: "dokument", zeit: null },
      { id: B, titel: "Böse\u202E\u0000Zeile\nzwei", art: "tabelle", zeit: "kaputt" },
      { id: C, titel: "Whiteboard", art: "whiteboard", zeit: null },
      "Unsinn",
    ],
    geteilt: [{ id: C, titel: "Plan", art: "mermaid", zeit: null, von: "Kollegin\u200B", recht: "bearbeiten" }, { id: A, titel: "x", art: "code", recht: "alles" }],
  });
  assert.ok(h);
  assert.deepEqual(
    h.eigene.map((e) => e.id),
    [A, B],
  );
  assert.equal(h.eigene[0].zeit, Date.parse("2026-11-18T09:01:00+00:00"));
  assert.equal(h.eigene[1].titel, "BöseZeile zwei");
  assert.equal(h.eigene[1].zeit, null);
  assert.equal(h.geteilt[0].von, "Kollegin");
  assert.equal(h.geteilt[0].recht, "bearbeiten");
  assert.equal(h.geteilt[1].recht, "lesen");
  assert.equal(alsHistorie(null), null);
  assert.equal(alsHistorie({ eigene: "x" }), null);
});

test("alsHistorie: höchstens 100 Einträge je Liste, Titel gekürzt", () => {
  const viele = Array.from({ length: 150 }, (_, i) => ({
    id: `aaaaaaaa-0000-4000-8000-${String(i).padStart(12, "0")}`,
    titel: "x".repeat(500),
    art: "code",
    zeit: null,
  }));
  const h = alsHistorie({ eigene: viele, geteilt: [] });
  assert.ok(h);
  assert.equal(h.eigene.length, 100);
  assert.ok(h.eigene[0].titel.length <= 120);
});

test("historieZeilen: erst diese Sitzung, dann ältere aus der Datenbank ohne die offenen und ohne Doppelte, neueste zuerst", () => {
  const zu: Geschlossen<T>[] = [
    { item: { id: B, title: "Notiz", kind: "dokument" }, zu: 5000 },
    { item: { id: "lokal-1", title: "Foto.png", kind: "bild" }, zu: 4000 },
  ];
  const db = {
    eigene: [
      { id: A, titel: "Angebot", art: "dokument" as const, zeit: 3000 },
      { id: B, titel: "Notiz", art: "dokument" as const, zeit: 2000 }, // schon in dieser Sitzung geschlossen
      { id: C, titel: "Offen", art: "tabelle" as const, zeit: 9000 }, // gerade als Reiter offen
    ],
    geteilt: [{ id: "bbbbbbbb-0000-4000-8000-000000000001", titel: "Plan", art: "mermaid" as const, zeit: 3500, von: "Kollegin", recht: "lesen" as const }],
  };
  const z = historieZeilen(zu, db, [{ id: C }]);
  assert.deepEqual(
    z.sitzung.map((r) => r.titel),
    ["Notiz", "Foto.png"],
  );
  assert.equal(z.sitzung[0].zeit, 5000);
  assert.deepEqual(
    z.frueher.map((r) => r.titel),
    ["Plan", "Angebot"],
  );
  assert.equal(z.frueher[0].von, "Kollegin");
  // ohne Antwort des Kerns (Labor, Fehler) nur diese Sitzung
  assert.deepEqual(historieZeilen(zu, null, []).frueher, []);
});

test("historieZeilen: ein Eintrag der Sitzung, der wieder offen ist, erscheint nicht", () => {
  const zu: Geschlossen<T>[] = [{ item: { id: A, title: "Angebot", kind: "dokument" }, zu: 1 }];
  assert.deepEqual(historieZeilen(zu, null, [{ id: A }]).sitzung, []);
});
