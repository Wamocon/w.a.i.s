/**
 * Herunterladen aus dem Canvas im Browser (Wunsch vom 18.11.2026), ohne Kern und ohne Host: Text, Markdown, HTML, JSON, CSV, Quelltext und
 * Mermaid-Quelle entstehen hier als Text; PNG und SVG baut die Oberfläche selbst (lib/canvasBild.ts). Die Formate am PC über Word, Excel
 * und PowerPoint bleiben beim Host (lib/export.ts). Die Datei landet im Download-Ordner des Browsers, nichts geht an einen Dienst.
 *
 * Schutz: CSV ohne Formeln (Zellen mit = + - @ Tab oder Wagenrücklauf bekommen ein Hochkomma, wie host/office_dateien.py). HTML ist ein
 * eigenes Dokument im WMC-Design (Kopf mit Anschrift und Logo, Seitenzahl im Druck), alles maskiert, mit CSP ohne Skripte. Quelltext, den
 * ein Browser ausführen würde (HTML, SVG, XML), wird als .txt gespeichert.
 */

export type DownloadFormat = "txt" | "md" | "html" | "json" | "csv" | "quelltext" | "mmd" | "svg" | "png" | "original";

export const FORMAT_TEXT: Record<DownloadFormat, string> = {
  txt: "Text",
  md: "Markdown",
  html: "HTML",
  json: "JSON",
  csv: "CSV",
  quelltext: "Quelltext",
  mmd: "Mermaid",
  svg: "SVG",
  png: "PNG",
  original: "Original",
};

type BildDatei = { src: string; mime: string; groesse: number; name: string };
export type ExportItem =
  | { kind: "tabelle"; title: string; columns: string[]; rows: string[][] }
  | { kind: "dokument" | "mermaid"; title: string; text: string }
  | { kind: "code"; title: string; text: string; language?: string }
  | { kind: "bild"; title: string; url?: string; alt?: string; datei?: BildDatei };

export const ANSCHRIFT = "WAMOCON GmbH, Mergenthalerallee 79-81, 65760 Eschborn";

/** Formate, die der Browser für dieses Element anbietet. Bilder von außen gar nicht (die CSP lässt sie nicht laden). */
export function downloadFormate(item: ExportItem): DownloadFormat[] {
  switch (item.kind) {
    case "tabelle":
      return ["csv", "html", "json"];
    case "dokument":
      return ["md", "txt", "html", "json"];
    case "code":
      return ["quelltext", "html", "json"];
    case "mermaid":
      return ["png", "svg", "mmd", "json"];
    case "bild":
      return item.datei ? ["original", "png"] : [];
  }
}

const STEUER = /[\u0000-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;
const RESERVIERT = /^(con|prn|aux|nul|com\d|lpt\d)$/i;

/** Dateiname aus dem Titel: ohne Steuerzeichen und ohne Zeichen, die Windows verbietet, höchstens 80 Zeichen, nie leer. */
export function dateiname(titel: string, endung: string): string {
  let stamm = titel.replace(STEUER, "").replace(/[<>:"/\\|?*]/g, "_").replace(/\s+/g, " ").trim();
  stamm = stamm.slice(0, 80).replace(/^[\s.]+|[\s.]+$/g, "");
  if (!stamm) stamm = "Canvas";
  if (RESERVIERT.test(stamm)) stamm = `_${stamm}`;
  return `${stamm}.${endung}`;
}

const FORMEL = /^[=+\-@\t\r]/;

function csvZelle(wert: string): string {
  const w = FORMEL.test(wert) ? `'${wert}` : wert;
  return /[;"\r\n]/.test(w) ? `"${w.replaceAll('"', '""')}"` : w;
}

/** CSV für Excel: Semikolon, BOM, Zeilenende CRLF, Formeln entschärft. */
export function csvText(spalten: readonly string[], zeilen: readonly (readonly string[])[]): string {
  return `\uFEFF${[spalten, ...zeilen].map((z) => spalten.map((_, i) => csvZelle(z[i] ?? "")).join(";")).join("\r\n")}`;
}

const esc = (t: string) =>
  t.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");

function inlineHtml(text: string): string {
  return esc(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

/** Das kleine Markdown des Canvas als HTML (wie components/Canvas.tsx: Überschriften, Listen, Absätze, fett, Code), alles maskiert. */
export function markdownHtml(text: string): string {
  const teile: string[] = [];
  let liste: string[] = [];
  const listeAus = () => {
    if (liste.length) teile.push(`<ul>${liste.map((li) => `<li>${inlineHtml(li)}</li>`).join("")}</ul>`);
    liste = [];
  };
  for (const roh of text.split("\n")) {
    const zeile = roh.trimEnd();
    const punkt = /^\s*[-*]\s+(.*)$/.exec(zeile);
    if (punkt) {
      liste.push(punkt[1]);
      continue;
    }
    listeAus();
    const ueberschrift = /^(#{1,3})\s+(.*)$/.exec(zeile);
    if (ueberschrift) {
      const ebene = ueberschrift[1].length + 1;
      teile.push(`<h${ebene}>${inlineHtml(ueberschrift[2])}</h${ebene}>`);
    } else if (zeile.trim()) teile.push(`<p>${inlineHtml(zeile)}</p>`);
  }
  listeAus();
  return teile.join("\n");
}

function klartext(text: string): string {
  return text
    .split("\n")
    .map((z) => z.replace(/^\s{0,3}#{1,6}\s+/, "").replaceAll("**", "").replaceAll("`", ""))
    .join("\n");
}

const LOGO_OK = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;

function htmlDokument(titel: string, koerper: string, logo: string | undefined, jetzt: Date): string {
  const marke = logo && LOGO_OK.test(logo) ? `<img src="${logo}" alt="WAMOCON" class="logo">` : `<strong class="logo">WAMOCON GmbH</strong>`;
  const stand = jetzt.toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" });
  return `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(titel)}</title>
<style>
@page { margin: 22mm 18mm; @bottom-center { content: "Seite " counter(page); font: 9pt "Arial Narrow", Arial, sans-serif; color: #6B6B6B; } }
body { font: 11pt/1.5 "Arial Narrow", Arial, sans-serif; color: #000; margin: 0 auto; max-width: 180mm; padding: 16px; }
header { display: flex; justify-content: space-between; align-items: center; gap: 16px; border-bottom: 2px solid #F40E0E; padding-bottom: 8px; margin-bottom: 24px; font-size: 9pt; color: #6B6B6B; }
.logo { height: 40px; width: auto; }
h1 { font-size: 20pt; margin: 0 0 4px; }
h2, h3, h4 { margin: 18px 0 6px; }
.stand { color: #6B6B6B; font-size: 9pt; margin: 0 0 18px; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; border-bottom: 2px solid #000; padding: 6px 8px; }
td { border-bottom: 1px solid #D9D9D9; padding: 6px 8px; vertical-align: top; }
pre { background: #F3F3F3; padding: 12px; white-space: pre-wrap; font: 10pt Consolas, monospace; }
code { font-family: Consolas, monospace; }
footer { margin-top: 32px; font-size: 9pt; color: #6B6B6B; border-top: 1px solid #D9D9D9; padding-top: 6px; }
</style>
</head>
<body>
<header><span>${esc(ANSCHRIFT)}</span>${marke}</header>
<h1>${esc(titel)}</h1>
<p class="stand">Aus dem Canvas von W.A.I.S., Stand ${esc(stand)}</p>
${koerper}
<footer>${esc(ANSCHRIFT)}</footer>
</body>
</html>
`;
}

function htmlKoerper(item: ExportItem): string | null {
  switch (item.kind) {
    case "tabelle": {
      const kopf = `<tr>${item.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>`;
      const zeilen = item.rows.map((z) => `<tr>${item.columns.map((_, i) => `<td>${esc(z[i] ?? "")}</td>`).join("")}</tr>`);
      return `<table><thead>${kopf}</thead><tbody>${zeilen.join("")}</tbody></table>`;
    }
    case "dokument":
      return markdownHtml(item.text);
    case "code":
      return `<pre><code>${esc(item.text)}</code></pre>`;
    default:
      return null;
  }
}

// Endungen für Quelltext; was ein Browser ausführt oder darstellt (HTML, SVG, XML), bleibt .txt
const QUELL_ENDUNG: Record<string, string> = {
  sql: "sql",
  python: "py",
  javascript: "js",
  typescript: "ts",
  tsx: "tsx",
  jsx: "jsx",
  json: "json",
  bash: "sh",
  sh: "sh",
  powershell: "ps1",
  java: "java",
  kotlin: "kt",
  csharp: "cs",
  go: "go",
  rust: "rs",
  ruby: "rb",
  php: "php",
  c: "c",
  cpp: "cpp",
  css: "css",
  scss: "scss",
  yaml: "yaml",
  toml: "toml",
  ini: "ini",
  mermaid: "mmd",
  text: "txt",
};

export type TextDatei = { name: string; mime: string; inhalt: string };

/** Inhalt einer Textdatei für dieses Format, oder null (nicht angeboten oder ein Bildformat). logo: Logo als data:-PNG für den Kopf. */
export function textDatei(item: ExportItem, format: DownloadFormat, optionen: { logo?: string; jetzt?: Date }): TextDatei | null {
  if (!downloadFormate(item).includes(format)) return null;
  const jetzt = optionen.jetzt ?? new Date();
  const t = item.title;
  switch (format) {
    case "csv":
      return item.kind === "tabelle" ? { name: dateiname(t, "csv"), mime: "text/csv;charset=utf-8", inhalt: csvText(item.columns, item.rows) } : null;
    case "html": {
      const koerper = htmlKoerper(item);
      return koerper === null ? null : { name: dateiname(t, "html"), mime: "text/html;charset=utf-8", inhalt: htmlDokument(t, koerper, optionen.logo, jetzt) };
    }
    case "json": {
      if (item.kind === "bild") return null;
      const inhalt =
        item.kind === "tabelle"
          ? { spalten: item.columns, zeilen: item.rows }
          : { text: item.text, ...(item.kind === "code" && item.language ? { sprache: item.language } : {}) };
      const daten = { titel: t, art: item.kind, ...inhalt, exportiert: jetzt.toISOString() };
      return { name: dateiname(t, "json"), mime: "application/json", inhalt: JSON.stringify(daten, null, 2) };
    }
    case "md":
      return item.kind === "dokument" ? { name: dateiname(t, "md"), mime: "text/markdown;charset=utf-8", inhalt: item.text } : null;
    case "txt":
      return item.kind === "dokument" ? { name: dateiname(t, "txt"), mime: "text/plain;charset=utf-8", inhalt: klartext(item.text) } : null;
    case "quelltext":
      if (item.kind !== "code") return null;
      return { name: dateiname(t, QUELL_ENDUNG[(item.language ?? "").toLowerCase()] ?? "txt"), mime: "text/plain;charset=utf-8", inhalt: item.text };
    case "mmd":
      return item.kind === "mermaid" ? { name: dateiname(t, "mmd"), mime: "text/plain;charset=utf-8", inhalt: item.text } : null;
    default:
      return null;
  }
}
