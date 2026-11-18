// Tests für die Auswahl im Canvas (lib/canvasWahl.ts): Stelle eines Elements nach Kennung und der Wunsch "zeige dieses Ergebnis".
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { canvasEinordnen, canvasIndex, canvasOffen, canvasWunsch, canvasWaehlen, neueStelle } from "./canvasWahl.ts";
import { parseServerMessage } from "./nachrichten.ts";

test("canvasIndex findet das Element mit der Kennung, sonst -1", () => {
  const items = [{ id: "a" }, { id: null }, {}, { id: "dev-42" }];
  assert.equal(canvasIndex(items, "dev-42"), 3);
  assert.equal(canvasIndex(items, "a"), 0);
  assert.equal(canvasIndex(items, "fehlt"), -1);
  assert.equal(canvasIndex(items, ""), -1); // leere Kennung trifft nie ein Element ohne Kennung
  assert.equal(canvasIndex([], "a"), -1);
});

test("canvasWaehlen setzt den Wunsch; derselbe Wunsch zweimal zählt als neuer Wunsch (der Zähler läuft hoch)", () => {
  const vorher = canvasWunsch.get();
  canvasWaehlen("dev-42");
  const eins = canvasWunsch.get();
  assert.equal(eins.id, "dev-42");
  assert.equal(eins.n, vorher.n + 1);
  canvasWaehlen("dev-42");
  const zwei = canvasWunsch.get();
  assert.equal(zwei.id, "dev-42");
  assert.equal(zwei.n, eins.n + 1);
});

// ---------- Überarbeitung an derselben Stelle (Befund 15.11.2026: jede Änderung legte einen neuen Reiter an) ----------
type T = { id?: string | null; title: string };
const liste = (): T[] => [
  { id: "a", title: "Plan" },
  { id: "b", title: "Liste" },
  { id: "c", title: "Notiz" },
];

test("canvasEinordnen: ersetzt setzt das neue Element an die Stelle des alten, die Länge bleibt", () => {
  const alt = liste();
  const e = canvasEinordnen(alt, { id: "a2", title: "Plan, kürzer" }, "a", 20);
  assert.equal(e.art, "ersetzt");
  assert.deepEqual(
    e.items.map((it) => it.id),
    ["a2", "b", "c"],
  );
  assert.equal(e.items[0].title, "Plan, kürzer");
  assert.deepEqual(
    alt.map((it) => it.id),
    ["a", "b", "c"],
  ); // die alte Liste bleibt unverändert (neuer Zustand, keine Mutation)
});

test("canvasEinordnen: gleiche Kennung ist eine Aktualisierung an Ort und Stelle (Fortschritt eines Auftrags)", () => {
  const e = canvasEinordnen(liste(), { id: "b", title: "Liste 2" }, undefined, 20);
  assert.equal(e.art, "aktualisiert");
  assert.deepEqual(
    e.items.map((it) => it.title),
    ["Plan", "Liste 2", "Notiz"],
  );
});

test("canvasEinordnen: unbekanntes ersetzt oder keins hängt hinten an, höchstens max Elemente", () => {
  const unbekannt = canvasEinordnen(liste(), { id: "d", title: "Neu" }, "fehlt", 20);
  assert.equal(unbekannt.art, "neu");
  assert.deepEqual(
    unbekannt.items.map((it) => it.id),
    ["a", "b", "c", "d"],
  );
  const voll = canvasEinordnen(liste(), { id: "d", title: "Neu" }, undefined, 3);
  assert.deepEqual(
    voll.items.map((it) => it.id),
    ["b", "c", "d"],
  );
  // ein Element ohne Kennung wird nie mit einem anderen ohne Kennung verwechselt
  const ohne = canvasEinordnen([{ id: null, title: "x" }], { id: null, title: "y" }, "", 20);
  assert.equal(ohne.art, "neu");
  assert.equal(ohne.items.length, 2);
});

test("Nachricht canvas: ersetzt wird geprüft übernommen, alles andere verworfen", () => {
  const item = { id: "neu-1", kind: "dokument", title: "Plan", text: "t" };
  const mit = parseServerMessage({ type: "canvas", item, ersetzt: "alt-1" });
  assert.ok(mit && mit.type === "canvas");
  assert.equal(mit.ersetzt, "alt-1");
  for (const kaputt of [7, "", null, { id: "x" }, "x".repeat(101)]) {
    const m = parseServerMessage({ type: "canvas", item, ersetzt: kaputt });
    assert.ok(m && m.type === "canvas");
    assert.equal(m.ersetzt, undefined, String(kaputt));
  }
  const ohne = parseServerMessage({ type: "canvas", item });
  assert.ok(ohne && ohne.type === "canvas");
  assert.equal(ohne.ersetzt, undefined);
});

// ---------- Historie (Wunsch vom 18.11.2026): was vorne herausfällt, geht nicht verloren ----------
test("canvasEinordnen meldet verdrängte Elemente, damit sie in die Historie kommen", () => {
  const voll = canvasEinordnen(liste(), { id: "d", title: "Neu" }, undefined, 3);
  assert.deepEqual(
    voll.verdraengt.map((it) => it.id),
    ["a"],
  );
  assert.deepEqual(canvasEinordnen(liste(), { id: "d", title: "Neu" }, undefined, 20).verdraengt, []);
  assert.deepEqual(canvasEinordnen(liste(), { id: "b", title: "Liste 2" }, undefined, 3).verdraengt, []);
  assert.deepEqual(canvasEinordnen(liste(), { id: "a2", title: "Plan" }, "a", 3).verdraengt, []);
});

test("neueStelle liefert eindeutige Schlüssel, die nie wie eine Kennung des Kerns aussehen; canvasWaehlen nimmt eine stelle mit", () => {
  const a = neueStelle();
  const b = neueStelle();
  assert.notEqual(a, b);
  assert.match(a, /^stelle-\d+$/);
  canvasWaehlen("", b);
  assert.equal(canvasWunsch.get().stelle, b);
  canvasWaehlen("x");
  assert.equal(canvasWunsch.get().stelle, undefined);
  canvasOffen.set(() => a);
  assert.equal(canvasOffen.get(), a);
  canvasOffen.set(() => null);
});

test("Nachricht canvas mit Bild: nur https ohne Zugangsdaten, nie eigene Bilddaten vom Kern", () => {
  const ok = parseServerMessage({
    type: "canvas",
    item: { id: "lokal-1", kind: "bild", title: "Rathaus", url: "https://example.com/r.jpg", alt: "Das Rathaus\nvon außen", datei: { src: "blob:x" } },
  });
  assert.ok(ok && ok.type === "canvas" && ok.item.kind === "bild");
  assert.equal(ok.item.url, "https://example.com/r.jpg");
  assert.equal(ok.item.alt, "Das Rathaus von außen");
  assert.equal(ok.item.datei, undefined);
  for (const url of [
    "http://example.com/a.png",
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "blob:https://example.com/x",
    "https://a:b@example.com/x.png",
    "https://example.com/a b.png",
    "https://127.1/a.png",
    "https://0x7f.0.0.1/a.png",
    "https://10.1/a.png",
    "https://[::1]/a.png",
    "https://localhost/a.png",
    "https://nas.local/a.png",
    "https://intern/a.png",
    "https://example.com/\u202Ex.png",
    `https://example.com/${"a".repeat(2001)}`,
    "",
    7,
  ]) {
    assert.equal(parseServerMessage({ type: "canvas", item: { kind: "bild", title: "x", url } }), null, String(url).slice(0, 40));
  }
});

test("Nachricht canvas_schliessen: offen, alle oder höchstens zehn Kennungen, sonst verworfen", () => {
  assert.deepEqual(parseServerMessage({ type: "canvas_schliessen", ziel: "offen" }), { type: "canvas_schliessen", ziel: "offen" });
  assert.deepEqual(parseServerMessage({ type: "canvas_schliessen", ziel: "alle", ids: ["x"] }), { type: "canvas_schliessen", ziel: "alle" });
  assert.deepEqual(parseServerMessage({ type: "canvas_schliessen", ziel: "ids", ids: ["a", 7, "", "x".repeat(101), "b"] }), {
    type: "canvas_schliessen",
    ziel: "ids",
    ids: ["a", "b"],
  });
  const viele = parseServerMessage({ type: "canvas_schliessen", ziel: "ids", ids: Array.from({ length: 20 }, (_, i) => `k${i}`) });
  assert.ok(viele && viele.type === "canvas_schliessen" && viele.ziel === "ids" && viele.ids.length === 10);
  for (const kaputt of [{ ziel: "ids", ids: [] }, { ziel: "ids" }, { ziel: "x" }, {}]) {
    assert.equal(parseServerMessage({ type: "canvas_schliessen", ...kaputt }), null);
  }
});
