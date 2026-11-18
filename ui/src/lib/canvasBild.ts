"use client";

/**
 * Bilder und Downloads aus dem Canvas, nur im Browser (Wunsch vom 18.11.2026): Mermaid als SVG oder PNG, eigene Bilder als PNG, Dateien
 * über den Download des Browsers. Nichts geht an den Kern oder an einen Dienst; das Logo für den Kopf der HTML-Datei kommt von der eigenen
 * Seite (connect-src 'self'). Mermaid zeichnet für den Export ohne HTML-Beschriftungen (keine foreignObject-Elemente): So bleibt das SVG
 * auch außerhalb des Browsers lesbar und die Zeichenfläche für PNG sauber.
 */

const PNG_SKALA = 2;
const PNG_MAX_SEITE = 8192;
const LOGO_PFAD = "/wmc-logo.png";
let logoCache: Promise<string | undefined> | null = null;

/** Eine Datei über den Download des Browsers speichern (blob: nur kurz, danach freigegeben). */
export function herunterladen(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/** Das WMC-Logo als data:-PNG für den Kopf der HTML-Datei; ohne Logo (Fehler, zu groß) undefined, dann steht dort der Firmenname. */
export function logoLaden(): Promise<string | undefined> {
  logoCache ??= (async () => {
    try {
      const antwort = await fetch(LOGO_PFAD, { cache: "force-cache" });
      const blob = await antwort.blob();
      if (!antwort.ok || blob.type !== "image/png" || blob.size > 512 * 1024) return undefined;
      return await new Promise<string | undefined>((fertig) => {
        const leser = new FileReader();
        leser.onload = () => fertig(typeof leser.result === "string" ? leser.result : undefined);
        leser.onerror = () => fertig(undefined);
        leser.readAsDataURL(blob);
      });
    } catch {
      return undefined;
    }
  })();
  const laden = logoCache;
  void laden.then((logo) => {
    if (!logo && logoCache === laden) logoCache = null; // beim nächsten Mal neu versuchen
  });
  return laden;
}

/** Breite und Höhe aus der viewBox eines SVG (Mermaid setzt width="100%"), sonst null. */
export function svgMasse(svg: string): { breite: number; hoehe: number } | null {
  const box = /viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"/.exec(svg);
  if (!box) return null;
  const breite = Number(box[1]);
  const hoehe = Number(box[2]);
  return breite > 0 && hoehe > 0 && Number.isFinite(breite) && Number.isFinite(hoehe) ? { breite, hoehe } : null;
}

/** Mermaid-Quelltext als eigenständiges SVG (helles Thema, ohne HTML-Beschriftungen, strict wie im Canvas). */
export async function mermaidSvg(quelle: string): Promise<string> {
  const mermaid = (await import("mermaid")).default;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    suppressErrorRendering: true,
  });
  const { svg } = await mermaid.render(`export${Math.random().toString(36).slice(2, 10)}`, quelle);
  const masse = svgMasse(svg);
  // feste Maße statt width="100%", sonst zeichnet ein Bildprogramm das SVG winzig
  return masse ? svg.replace(/<svg\b([^>]*?)\swidth="[^"]*"/, `<svg$1 width="${masse.breite}" height="${masse.hoehe}"`) : svg;
}

function zeichenflaeche(breite: number, hoehe: number): HTMLCanvasElement {
  const f = Math.min(PNG_SKALA, PNG_MAX_SEITE / Math.max(breite, hoehe));
  const flaeche = document.createElement("canvas");
  flaeche.width = Math.max(1, Math.round(breite * f));
  flaeche.height = Math.max(1, Math.round(hoehe * f));
  return flaeche;
}

function alsPng(flaeche: HTMLCanvasElement): Promise<Blob> {
  return new Promise((fertig, fehler) => flaeche.toBlob((b) => (b ? fertig(b) : fehler(new Error("PNG nicht erzeugt"))), "image/png"));
}

/** Ein SVG als PNG auf weißem Grund (doppelte Auflösung, höchstens PNG_MAX_SEITE Pixel je Seite). */
export async function svgAlsPng(svg: string): Promise<Blob> {
  const masse = svgMasse(svg) ?? { breite: 1200, hoehe: 800 };
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const bild = new Image();
    bild.src = url;
    await bild.decode();
    const flaeche = zeichenflaeche(masse.breite, masse.hoehe);
    const ctx = flaeche.getContext("2d");
    if (!ctx) throw new Error("Keine Zeichenfläche");
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, flaeche.width, flaeche.height);
    ctx.drawImage(bild, 0, 0, flaeche.width, flaeche.height);
    return await alsPng(flaeche);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Ein eigenes Bild (PNG, JPEG, GIF, WebP) als PNG; bei GIF das erste Bild. */
export async function bildAlsPng(blob: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(blob);
  try {
    const flaeche = zeichenflaeche(bitmap.width / PNG_SKALA, bitmap.height / PNG_SKALA);
    const ctx = flaeche.getContext("2d");
    if (!ctx) throw new Error("Keine Zeichenfläche");
    ctx.drawImage(bitmap, 0, 0, flaeche.width, flaeche.height);
    return await alsPng(flaeche);
  } finally {
    bitmap.close();
  }
}
