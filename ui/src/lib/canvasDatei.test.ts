// Tests für Dateien, die die Person im Canvas öffnet (lib/canvasDatei.ts): Einordnung nach Endung und Größe, Bildtyp aus den ersten
// Bytes (nie aus Endung oder Browser-Angabe), Bildmaße gegen übergroße Bilder, Textdekodierung und CSV als Tabelle.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BILD_MAX_BYTES,
  BILD_MAX_PIXEL,
  BILD_MAX_SEITE,
  bildMasse,
  bildPruefen,
  bildTyp,
  csvLesen,
  dateiEinordnen,
  DATEI_ACCEPT,
  TEXT_MAX_BYTES,
  textDekodieren,
  textAlsItem,
} from "./canvasDatei.ts";

const bytes = (...teile: (number[] | string)[]) =>
  Uint8Array.from(teile.flatMap((t) => (typeof t === "string" ? [...t].map((z) => z.charCodeAt(0)) : t)));
const be32 = (n: number) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
const le16 = (n: number) => [n & 255, (n >>> 8) & 255];
const le24 = (n: number) => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255];

const png = (b: number, h: number) => bytes([0x89], "PNG\r\n\x1a\n", be32(13), "IHDR", be32(b), be32(h), [8, 6, 0, 0, 0]);
const gif = (b: number, h: number) => bytes("GIF89a", le16(b), le16(h), [0, 0, 0]);
const jpeg = (b: number, h: number) =>
  bytes([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10], "JFIF\0", new Array(9).fill(0), [0xff, 0xc0, 0x00, 0x11, 0x08], [h >> 8, h & 255, b >> 8, b & 255], [3]);
const webpX = (b: number, h: number) => bytes("RIFF", [0, 0, 0, 0], "WEBPVP8X", [10, 0, 0, 0], [0, 0, 0, 0], le24(b - 1), le24(h - 1));

test("bildTyp erkennt PNG, JPEG, GIF und WebP nur an den ersten Bytes", () => {
  assert.equal(bildTyp(png(10, 10)), "image/png");
  assert.equal(bildTyp(jpeg(10, 10)), "image/jpeg");
  assert.equal(bildTyp(gif(10, 10)), "image/gif");
  assert.equal(bildTyp(webpX(10, 10)), "image/webp");
  assert.equal(bildTyp(bytes("<svg xmlns='http://www.w3.org/2000/svg'>")), null); // SVG nie als Bild
  assert.equal(bildTyp(bytes("%PDF-1.7")), null);
  assert.equal(bildTyp(bytes("")), null);
});

test("bildMasse liest Breite und Höhe aus dem Kopf", () => {
  assert.deepEqual(bildMasse(png(1920, 1080)), { breite: 1920, hoehe: 1080 });
  assert.deepEqual(bildMasse(gif(320, 200)), { breite: 320, hoehe: 200 });
  assert.deepEqual(bildMasse(jpeg(800, 600)), { breite: 800, hoehe: 600 });
  assert.deepEqual(bildMasse(webpX(4000, 3000)), { breite: 4000, hoehe: 3000 });
  assert.equal(bildMasse(bytes([0xff, 0xd8, 0xff, 0xe0, 0x00])), null); // abgeschnittenes JPEG
});

test("bildMasse bei GIF: ein erstes Einzelbild, das größer ist als die Fläche, zählt (nach übersprungenen Erweiterungen)", () => {
  const kopf = [0x47, 0x49, 0x46, 0x38, 0x39, 0x61, ...le16(10), ...le16(10), 0x80, 0, 0]; // Fläche 10 x 10 mit globaler Farbtabelle (2 Farben)
  const farben = [0, 0, 0, 255, 255, 255];
  const erweiterung = [0x21, 0xf9, 4, 0, 0, 0, 0, 0]; // Grafiksteuerung
  const bild = [0x2c, ...le16(0), ...le16(0), ...le16(20000), ...le16(15000), 0];
  const gross = Uint8Array.from([...kopf, ...farben, ...erweiterung, ...bild]);
  assert.deepEqual(bildMasse(gross), { breite: 20000, hoehe: 15000 });
  assert.ok("fehler" in bildPruefen(gross, gross.length));
});

test("bildPruefen: Typ aus den Bytes, Grenzen für Größe, Seitenlänge und Pixelzahl", () => {
  assert.deepEqual(bildPruefen(png(800, 600), 5000), { mime: "image/png", breite: 800, hoehe: 600 });
  assert.match(String((bildPruefen(png(800, 600), BILD_MAX_BYTES + 1) as { fehler: string }).fehler), /10 MB/);
  assert.match(String((bildPruefen(png(BILD_MAX_SEITE + 1, 10), 100) as { fehler: string }).fehler), /zu groß/);
  const seite = Math.floor(Math.sqrt(BILD_MAX_PIXEL)) + 10;
  assert.ok(seite <= BILD_MAX_SEITE);
  assert.ok("fehler" in bildPruefen(png(seite, seite), 100));
  assert.ok("fehler" in bildPruefen(bytes("<svg/>"), 10));
  assert.ok("fehler" in bildPruefen(png(0, 10), 100));
});

test("dateiEinordnen: Bilder, Text, Tabellen, Code und Diagramme nach Endung; SVG und HTML nur als Quelltext; Rest abgelehnt", () => {
  assert.deepEqual(dateiEinordnen("Foto.JPG", 1000), { art: "bild" });
  assert.deepEqual(dateiEinordnen("notiz.md", 10), { art: "text", ziel: "dokument" });
  assert.deepEqual(dateiEinordnen("liste.txt", 10), { art: "text", ziel: "dokument" });
  assert.deepEqual(dateiEinordnen("daten.csv", 10), { art: "text", ziel: "tabelle" });
  assert.deepEqual(dateiEinordnen("daten.tsv", 10), { art: "text", ziel: "tabelle" });
  assert.deepEqual(dateiEinordnen("abfrage.sql", 10), { art: "text", ziel: "code", sprache: "sql" });
  assert.deepEqual(dateiEinordnen("logo.svg", 10), { art: "text", ziel: "code", sprache: "svg" });
  assert.deepEqual(dateiEinordnen("seite.html", 10), { art: "text", ziel: "code", sprache: "html" });
  assert.deepEqual(dateiEinordnen("daten.json", 10), { art: "text", ziel: "code", sprache: "json" });
  assert.deepEqual(dateiEinordnen("ablauf.mmd", 10), { art: "text", ziel: "mermaid" });
  for (const name of ["vertrag.pdf", "bericht.docx", "setup.exe", "ohne_endung", "archiv.zip", ".env"]) {
    assert.ok("fehler" in dateiEinordnen(name, 10), name);
  }
  assert.ok("fehler" in dateiEinordnen("gross.txt", TEXT_MAX_BYTES + 1));
  assert.ok("fehler" in dateiEinordnen("gross.png", BILD_MAX_BYTES + 1));
  assert.ok("fehler" in dateiEinordnen("leer.txt", 0));
  // die Auswahlliste des Dialogs nennt genau die bekannten Endungen
  for (const e of [".png", ".jpg", ".csv", ".md", ".sql", ".mmd", ".svg"]) assert.ok(DATEI_ACCEPT.split(",").includes(e), e);
  assert.ok(!DATEI_ACCEPT.includes(".pdf") && !DATEI_ACCEPT.includes(".exe"));
});

test("textDekodieren: UTF-8 (auch mit BOM), sonst Windows-1252; Binärdaten mit Nullbyte abgelehnt", () => {
  assert.equal(textDekodieren(new TextEncoder().encode("\uFEFFGrüße")), "Grüße");
  assert.equal(textDekodieren(Uint8Array.from([0x47, 0x72, 0xfc, 0xdf, 0x65])), "Grüße"); // Excel-CSV in Windows-1252
  assert.equal(textDekodieren(Uint8Array.from([0x41, 0x00, 0x42])), null);
});

test("csvLesen: Trennzeichen erkennen, Anführungszeichen, Zeilenumbrüche im Feld, höchstens max Zeilen", () => {
  assert.deepEqual(csvLesen("Stadt;Einwohner\r\nFrankfurt;773000\r\nEschborn;21000\r\n"), [
    ["Stadt", "Einwohner"],
    ["Frankfurt", "773000"],
    ["Eschborn", "21000"],
  ]);
  assert.deepEqual(csvLesen('a,b\n"x, y","z ""q"""\n"zwei\nzeilen",w'), [
    ["a", "b"],
    ["x, y", 'z "q"'],
    ["zwei\nzeilen", "w"],
  ]);
  assert.deepEqual(csvLesen("a\tb\n1\t2"), [
    ["a", "b"],
    ["1", "2"],
  ]);
  assert.equal(csvLesen("k\n" + "1\n".repeat(1000), 10).length, 10);
});

test("textAlsItem: CSV wird Tabelle, JSON hübsch eingerückt, sonst Text; der Titel ist der Dateiname", () => {
  assert.deepEqual(textAlsItem("daten.csv", "a;b\n1;2", { art: "text", ziel: "tabelle" }), {
    kind: "tabelle",
    title: "daten.csv",
    columns: ["a", "b"],
    rows: [["1", "2"]],
  });
  assert.deepEqual(textAlsItem("x.json", '{"a":1}', { art: "text", ziel: "code", sprache: "json" }), {
    kind: "code",
    title: "x.json",
    text: '{\n  "a": 1\n}',
    language: "json",
  });
  assert.deepEqual(textAlsItem("x.json", "{kaputt", { art: "text", ziel: "code", sprache: "json" }), {
    kind: "code",
    title: "x.json",
    text: "{kaputt",
    language: "json",
  });
  assert.deepEqual(textAlsItem("n.md", "# Hallo", { art: "text", ziel: "dokument" }), { kind: "dokument", title: "n.md", text: "# Hallo" });
  assert.equal(textAlsItem("leer.csv", "", { art: "text", ziel: "tabelle" }), null);
});
