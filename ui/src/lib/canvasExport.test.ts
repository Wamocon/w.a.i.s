// Tests für das Herunterladen aus dem Canvas im Browser (lib/canvasExport.ts): welche Formate je Art, Dateinamen, CSV ohne Formeln,
// HTML mit WMC-Kopf, maskiert und mit eigener CSP, JSON und Text.
// Ausführen im Ordner ui/:  npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { csvText, dateiname, downloadFormate, markdownHtml, textDatei } from "./canvasExport.ts";

const tabelle = { kind: "tabelle" as const, title: "Städte", columns: ["Stadt", "Formel"], rows: [["Frankfurt", "=1+1"], ["Eschborn; Taunus", 'Zitat "x"']] };
const dokument = { kind: "dokument" as const, title: "Angebot", text: "# Titel\n\nText mit **fett** und `code`.\n- eins\n- <b>zwei</b>" };
const code = { kind: "code" as const, title: "Abfrage", text: "select 1;", language: "sql" };
const mermaid = { kind: "mermaid" as const, title: "Ablauf", text: "flowchart LR\nA-->B" };
const JETZT = new Date("2026-11-18T10:00:00Z");

test("downloadFormate je Art; Bilder von außen gar nicht, eigene Bilder als Original und PNG", () => {
  assert.deepEqual(downloadFormate(tabelle), ["csv", "html", "json"]);
  assert.deepEqual(downloadFormate(dokument), ["md", "txt", "html", "json"]);
  assert.deepEqual(downloadFormate(code), ["quelltext", "html", "json"]);
  assert.deepEqual(downloadFormate(mermaid), ["png", "svg", "mmd", "json"]);
  assert.deepEqual(downloadFormate({ kind: "bild", title: "x", url: "https://example.com/a.png" }), []);
  assert.deepEqual(downloadFormate({ kind: "bild", title: "x", datei: { src: "blob:x", mime: "image/png", groesse: 1, name: "a.png" } }), [
    "original",
    "png",
  ]);
});

test("dateiname: ohne verbotene Zeichen, Umlaute bleiben, gekürzt, nie leer, keine reservierten Namen", () => {
  assert.equal(dateiname("Städte: Liste/2026?", "csv"), "Städte_ Liste_2026_.csv");
  assert.equal(dateiname("  ..  ", "txt"), "Canvas.txt");
  assert.equal(dateiname("con", "txt"), "_con.txt");
  assert.equal(dateiname("a\u0000b\u202Ec", "md"), "abc.md");
  assert.ok(dateiname("x".repeat(300), "json").length <= 85);
});

test("CSV: Semikolon, BOM für Excel, Felder mit Trennzeichen in Anführungszeichen, Formeln entschärft", () => {
  const csv = csvText(tabelle.columns, tabelle.rows);
  assert.ok(csv.startsWith("\uFEFF"));
  const zeilen = csv.slice(1).split("\r\n");
  assert.equal(zeilen[0], "Stadt;Formel");
  assert.equal(zeilen[1], "Frankfurt;'=1+1");
  assert.equal(zeilen[2], '"Eschborn; Taunus";"Zitat ""x"""');
  for (const gefahr of ["+1", "-1", "@SUMME", "\tx"]) assert.ok(csvText(["a"], [[gefahr]]).includes(`'${gefahr}`), gefahr);
});

test("markdownHtml maskiert alles und kennt nur Überschriften, Listen, Absätze, fett und Code", () => {
  const html = markdownHtml(dokument.text);
  assert.ok(html.includes("<h2>Titel</h2>"));
  assert.ok(html.includes("<strong>fett</strong>") && html.includes("<code>code</code>"));
  assert.ok(html.includes("<li>&lt;b&gt;zwei&lt;/b&gt;</li>"));
  assert.ok(!html.includes("<b>"));
});

test("HTML-Datei: WMC-Kopf mit Anschrift und Logo, Seitenzahl im Druck, CSP ohne Skripte, Titel maskiert", () => {
  const d = textDatei({ ...tabelle, title: "<script>alert(1)</script>" }, "html", { logo: "data:image/png;base64,AAAA", jetzt: JETZT });
  assert.ok(d);
  assert.equal(d.mime, "text/html;charset=utf-8");
  assert.ok(d.name.endsWith(".html"));
  assert.ok(d.inhalt.includes("WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn"));
  assert.ok(d.inhalt.includes('src="data:image/png;base64,AAAA"'));
  assert.ok(d.inhalt.includes("counter(page)"));
  assert.ok(d.inhalt.includes("default-src 'none'"));
  assert.ok(!d.inhalt.includes("<script>"));
  assert.ok(d.inhalt.includes("&lt;script&gt;"));
  assert.ok(d.inhalt.includes("<td>&#39;=1+1</td>") || d.inhalt.includes("<td>=1+1</td>"));
  // ohne Logo (nicht geladen) steht der Firmenname im Kopf
  const ohne = textDatei(tabelle, "html", { jetzt: JETZT });
  assert.ok(ohne && !ohne.inhalt.includes("<img") && ohne.inhalt.includes("WAMOCON GmbH"));
  // ein Logo, das keine Bilddaten sind, wird nicht übernommen
  const fremd = textDatei(tabelle, "html", { logo: 'https://evil.example/x.png" onerror="x', jetzt: JETZT });
  assert.ok(fremd && !fremd.inhalt.includes("evil"));
});

test("JSON, Text, Markdown, Quelltext und Mermaid-Quelle", () => {
  const json = textDatei(tabelle, "json", { jetzt: JETZT });
  assert.ok(json);
  assert.deepEqual(JSON.parse(json.inhalt), {
    titel: "Städte",
    art: "tabelle",
    spalten: ["Stadt", "Formel"],
    zeilen: tabelle.rows,
    exportiert: "2026-11-18T10:00:00.000Z",
  });
  assert.equal(textDatei(dokument, "md", {})?.inhalt, dokument.text);
  assert.equal(textDatei(dokument, "txt", {})?.inhalt, "Titel\n\nText mit fett und code.\n- eins\n- <b>zwei</b>");
  const sql = textDatei(code, "quelltext", {});
  assert.equal(sql?.name, "Abfrage.sql");
  assert.equal(sql?.inhalt, "select 1;");
  // Auszeichnung, die ein Browser ausführen würde, nie als .html oder .svg
  assert.equal(textDatei({ ...code, language: "html" }, "quelltext", {})?.name, "Abfrage.txt");
  assert.equal(textDatei({ ...code, language: "svg" }, "quelltext", {})?.name, "Abfrage.txt");
  assert.equal(textDatei(mermaid, "mmd", {})?.name, "Ablauf.mmd");
  assert.equal(textDatei(mermaid, "png", {}), null); // Bilder baut die Oberfläche selbst
  assert.equal(textDatei(tabelle, "md", {}), null); // nicht angeboten
});
