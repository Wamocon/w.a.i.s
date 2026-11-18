import { CANVAS_MAX_ZEILEN } from "./nachrichten.ts"; // relativ, damit node:test diese Datei laden kann (canvasDatei.test.ts)

/**
 * Dateien im Canvas öffnen (Wunsch vom 18.11.2026: "alle Dateiformate, auch Bilder"). Alles bleibt im Browser: Die Datei geht weder an den
 * Kern noch an das Modell, sie wird nur angezeigt (components/CanvasDateien.tsx). Deshalb gibt es auch keinen neuen Weg nach außen.
 *
 * Regeln:
 *  * Bilder nur PNG, JPEG, GIF und WebP. Der Typ kommt aus den ersten Bytes, nie aus der Endung oder der Angabe des Browsers; daraus
 *    entsteht ein Blob mit genau diesem Typ (blob:, die CSP erlaubt nur eigene, data: und blob: Bilder). Höchstens BILD_MAX_BYTES, dazu
 *    Seitenlänge und Pixelzahl aus dem Kopf der Datei (gegen Bilder, die beim Entpacken den Speicher sprengen).
 *  * SVG nie als Bild (es kann Skripte und Verweise tragen): eine SVG-Datei zeigt das Canvas als Quelltext, ebenso HTML.
 *  * Text (Markdown, Text, CSV, JSON, Code, Mermaid) höchstens TEXT_MAX_BYTES, UTF-8 oder sonst Windows-1252 (CSV aus Excel), nie mit
 *    Nullbyte. Danach läuft das Element durch dieselbe Prüfung wie jede Nachricht des Kerns (lib/nachrichten.ts: Steuerzeichen, Längen).
 *  * Alles andere (PDF, Office, Archive, Programme) zeigt das Canvas nicht an.
 */

export const BILD_MAX_BYTES = 10 * 1024 * 1024;
export const TEXT_MAX_BYTES = 2 * 1024 * 1024;
export const BILD_MAX_SEITE = 16_384;
export const BILD_MAX_PIXEL = 40_000_000;

export type BildMime = "image/png" | "image/jpeg" | "image/gif" | "image/webp";
export type Einordnung =
  | { art: "bild" }
  | { art: "text"; ziel: "dokument" | "tabelle" | "mermaid" }
  | { art: "text"; ziel: "code"; sprache: string }
  | { fehler: string };

const BILD_ENDUNGEN = ["png", "jpg", "jpeg", "gif", "webp"];
const TEXT_ZIELE: Record<string, "dokument" | "tabelle" | "mermaid"> = {
  md: "dokument",
  markdown: "dokument",
  txt: "dokument",
  log: "dokument",
  csv: "tabelle",
  tsv: "tabelle",
  mmd: "mermaid",
  mermaid: "mermaid",
};
const CODE_SPRACHEN: Record<string, string> = {
  json: "json",
  sql: "sql",
  py: "python",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "tsx",
  jsx: "jsx",
  java: "java",
  kt: "kotlin",
  cs: "csharp",
  go: "go",
  rs: "rust",
  rb: "ruby",
  php: "php",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  sh: "bash",
  ps1: "powershell",
  bat: "bat",
  cmd: "bat",
  css: "css",
  scss: "scss",
  html: "html",
  htm: "html",
  xml: "xml",
  svg: "svg",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  ini: "ini",
};

/** Endungen für den Dateidialog (accept): genau die, die das Canvas zeigt. */
export const DATEI_ACCEPT = [...BILD_ENDUNGEN, ...Object.keys(TEXT_ZIELE), ...Object.keys(CODE_SPRACHEN)].map((e) => `.${e}`).join(",");

const NICHT_ANZEIGBAR = "Dieses Format zeigt das Canvas nicht an. Es gehen Bilder (PNG, JPEG, GIF, WebP), Text, Markdown, CSV, JSON, Code und Mermaid.";

function endung(name: string): string | null {
  const punkt = name.lastIndexOf(".");
  if (punkt <= 0 || punkt === name.length - 1) return null; // ohne Endung oder nur ".env"
  return name.slice(punkt + 1).toLowerCase();
}

/** Was das Canvas mit dieser Datei macht, nach Endung und Größe (der Inhalt wird danach noch geprüft). */
export function dateiEinordnen(name: string, groesse: number): Einordnung {
  const e = endung(name);
  if (groesse <= 0) return { fehler: "Die Datei ist leer." };
  if (e && BILD_ENDUNGEN.includes(e)) {
    return groesse > BILD_MAX_BYTES ? { fehler: "Bilder höchstens 10 MB." } : { art: "bild" };
  }
  const ziel = e ? TEXT_ZIELE[e] : undefined;
  const sprache = e ? CODE_SPRACHEN[e] : undefined;
  if (!ziel && !sprache) return { fehler: NICHT_ANZEIGBAR };
  if (groesse > TEXT_MAX_BYTES) return { fehler: "Textdateien höchstens 2 MB." };
  return ziel ? { art: "text", ziel } : { art: "text", ziel: "code", sprache: sprache as string };
}

const gleich = (b: Uint8Array, ab: number, text: string) => [...text].every((z, i) => b[ab + i] === z.charCodeAt(0));

/** Bildtyp aus den ersten Bytes, sonst null (SVG, PDF und alles andere). */
export function bildTyp(b: Uint8Array): BildMime | null {
  if (b.length >= 8 && b[0] === 0x89 && gleich(b, 1, "PNG\r\n\x1a\n")) return "image/png";
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b.length >= 6 && (gleich(b, 0, "GIF87a") || gleich(b, 0, "GIF89a"))) return "image/gif";
  if (b.length >= 12 && gleich(b, 0, "RIFF") && gleich(b, 8, "WEBP")) return "image/webp";
  return null;
}

const be16 = (b: Uint8Array, i: number) => (b[i] << 8) | b[i + 1];
const le16 = (b: Uint8Array, i: number) => b[i] | (b[i + 1] << 8);
const le24 = (b: Uint8Array, i: number) => b[i] | (b[i + 1] << 8) | (b[i + 2] << 16);
const be32 = (b: Uint8Array, i: number) => ((b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]) >>> 0;

function jpegMasse(b: Uint8Array): { breite: number; hoehe: number } | null {
  let i = 2;
  while (i + 9 < b.length) {
    if (b[i] !== 0xff) return null;
    const marker = b[i + 1];
    if (marker === 0xff) {
      i += 1; // Füllbyte
      continue;
    }
    // Start of Frame (alle Arten außer DHT C4, JPG C8, DAC CC)
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { hoehe: be16(b, i + 5), breite: be16(b, i + 7) };
    }
    i += 2 + be16(b, i + 2);
  }
  return null;
}

/**
 * GIF: die logische Fläche und das erste Einzelbild (es kann größer sein als die Fläche, ein Browser legt dann die größere an). Erweiterungen
 * vor dem ersten Bild werden übersprungen; fehlt es (abgeschnittene Datei), gilt die Fläche.
 */
function gifMasse(b: Uint8Array): { breite: number; hoehe: number } | null {
  if (b.length < 13) return null;
  let breite = le16(b, 6);
  let hoehe = le16(b, 8);
  let i = 13 + (b[10] & 0x80 ? 3 * 2 ** ((b[10] & 0x07) + 1) : 0);
  while (i < b.length) {
    if (b[i] === 0x2c && i + 9 <= b.length) {
      breite = Math.max(breite, le16(b, i + 1) + le16(b, i + 5));
      hoehe = Math.max(hoehe, le16(b, i + 3) + le16(b, i + 7));
      break;
    }
    if (b[i] !== 0x21) break; // weder Bild noch Erweiterung: nicht weiter lesen
    i += 2; // Einleitung und Art der Erweiterung, danach Blöcke bis zur Länge null
    while (i < b.length && b[i] !== 0) i += b[i] + 1;
    i += 1;
  }
  return { breite, hoehe };
}

function webpMasse(b: Uint8Array): { breite: number; hoehe: number } | null {
  if (b.length < 30) return null;
  if (gleich(b, 12, "VP8X")) return { breite: le24(b, 24) + 1, hoehe: le24(b, 27) + 1 };
  if (gleich(b, 12, "VP8 ") && b[23] === 0x9d && b[24] === 0x01 && b[25] === 0x2a) {
    return { breite: le16(b, 26) & 0x3fff, hoehe: le16(b, 28) & 0x3fff };
  }
  if (gleich(b, 12, "VP8L") && b[20] === 0x2f) {
    const bits = (b[21] | (b[22] << 8) | (b[23] << 16) | (b[24] << 24)) >>> 0;
    return { breite: (bits & 0x3fff) + 1, hoehe: ((bits >>> 14) & 0x3fff) + 1 };
  }
  return null;
}

/** Breite und Höhe aus dem Kopf des Bildes, ohne es zu entpacken; null, wenn der Kopf nicht lesbar ist. */
export function bildMasse(b: Uint8Array): { breite: number; hoehe: number } | null {
  switch (bildTyp(b)) {
    case "image/png":
      return b.length >= 24 && gleich(b, 12, "IHDR") ? { breite: be32(b, 16), hoehe: be32(b, 20) } : null;
    case "image/gif":
      return gifMasse(b);
    case "image/jpeg":
      return jpegMasse(b);
    case "image/webp":
      return webpMasse(b);
    default:
      return null;
  }
}

/** Ein Bild prüfen: Typ aus den Bytes, Größe der Datei, Seitenlänge und Pixelzahl. */
export function bildPruefen(b: Uint8Array, groesse: number): { mime: BildMime; breite: number; hoehe: number } | { fehler: string } {
  const mime = bildTyp(b);
  if (!mime) return { fehler: "Das ist kein Bild in PNG, JPEG, GIF oder WebP." };
  if (groesse > BILD_MAX_BYTES) return { fehler: "Bilder höchstens 10 MB." };
  const masse = bildMasse(b);
  if (!masse || masse.breite < 1 || masse.hoehe < 1) return { fehler: "Das Bild lässt sich nicht lesen." };
  if (masse.breite > BILD_MAX_SEITE || masse.hoehe > BILD_MAX_SEITE || masse.breite * masse.hoehe > BILD_MAX_PIXEL) {
    return { fehler: "Das Bild ist zu groß (höchstens 16384 Pixel je Seite und 40 Megapixel)." };
  }
  return { mime, ...masse };
}

/** Text aus den Bytes: UTF-8 (ein BOM fällt weg), sonst Windows-1252; mit Nullbyte (Binärdatei) null. */
export function textDekodieren(b: Uint8Array): string | null {
  if (b.includes(0)) return null;
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(b);
  } catch {
    return new TextDecoder("windows-1252").decode(b);
  }
}

function trenner(text: string): string {
  const zeile = text.slice(0, Math.max(0, text.search(/\r?\n/)) || text.length);
  const zaehlen = (z: string) => zeile.split(z).length - 1;
  const kandidaten = [";", ",", "\t"].map((z) => [z, zaehlen(z)] as const).sort((a, b) => b[1] - a[1]);
  return kandidaten[0][1] > 0 ? kandidaten[0][0] : ",";
}

/** CSV lesen (Trennzeichen Semikolon, Komma oder Tab aus der ersten Zeile, Felder in Anführungszeichen), höchstens max Zeilen. */
export function csvLesen(text: string, max = Number.POSITIVE_INFINITY): string[][] {
  const t = trenner(text);
  const zeilen: string[][] = [];
  let zeile: string[] = [];
  let feld = "";
  let inZitat = false;
  let i = 0;
  const zeileFertig = () => {
    zeile.push(feld);
    zeilen.push(zeile);
    zeile = [];
    feld = "";
  };
  while (i < text.length && zeilen.length < max) {
    const z = text[i];
    if (inZitat) {
      if (z === '"' && text[i + 1] === '"') {
        feld += '"';
        i += 2;
        continue;
      }
      if (z === '"') inZitat = false;
      else feld += z;
      i += 1;
      continue;
    }
    if (z === '"' && feld === "") inZitat = true;
    else if (z === t) {
      zeile.push(feld);
      feld = "";
    } else if (z === "\n" || z === "\r") {
      if (z === "\r" && text[i + 1] === "\n") i += 1;
      zeileFertig();
    } else feld += z;
    i += 1;
  }
  if (zeilen.length < max && (feld !== "" || zeile.length)) zeileFertig();
  return zeilen;
}

/** Element aus dem Text einer Datei (noch ungeprüft; der Aufrufer schickt es durch parseServerMessage). Leer: null. */
export function textAlsItem(name: string, text: string, einordnung: Exclude<Einordnung, { fehler: string } | { art: "bild" }>): Record<string, unknown> | null {
  if (einordnung.ziel === "tabelle") {
    const zeilen = csvLesen(text, CANVAS_MAX_ZEILEN + 2);
    if (!zeilen.length || zeilen[0].every((z) => !z.trim())) return null;
    return { kind: "tabelle", title: name, columns: zeilen[0], rows: zeilen.slice(1) };
  }
  if (!text.trim()) return null;
  if (einordnung.ziel === "code") {
    let quelltext = text;
    if (einordnung.sprache === "json") {
      try {
        quelltext = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        // kein gültiges JSON: so zeigen, wie es ist
      }
    }
    return { kind: "code", title: name, text: quelltext, language: einordnung.sprache };
  }
  return { kind: einordnung.ziel, title: name, text };
}

/** Kennung für ein Element, das nur im Browser existiert (nie eine UUID: Teilen und Speichern gibt es nur für Elemente des Kerns). */
export function lokaleKennung(): string {
  const zufall = new Uint8Array(8);
  crypto.getRandomValues(zufall);
  return `lokal-datei-${Array.from(zufall, (x) => x.toString(16).padStart(2, "0")).join("")}`;
}
