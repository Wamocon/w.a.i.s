"use client";

import { useRef, useState } from "react";
import type { CanvasItem } from "@/components/Canvas";
import { bildAlsPng, herunterladen, logoLaden, mermaidSvg, svgAlsPng } from "@/lib/canvasBild";
import { DATEI_ACCEPT } from "@/lib/canvasDatei";
import { dateiname, downloadFormate, FORMAT_TEXT, textDatei, type DownloadFormat } from "@/lib/canvasExport";
import { dateiOeffnen } from "@/lib/canvasOeffnen";
import { groesseText } from "@/lib/teilenHilfe";
import { zeigeToast } from "@/lib/wamo";

/**
 * Dateien im Canvas (Wunsch vom 18.11.2026: "alle Dateiformate, auch Bilder"), nur im Browser und nie für Laborkonten:
 *  * "Datei öffnen" zeigt eine Datei der Person als Reiter (lib/canvasDatei.ts prüft Typ und Größe); sie geht nicht an den Kern.
 *  * "Herunterladen" speichert das Element im Download-Ordner des Browsers (lib/canvasExport.ts, lib/canvasBild.ts).
 *  * Bilder: eigene aus blob:, Bilder von außen nur als Verweis (die CSP lädt keine fremden Bilder, der Kern lädt sie nie).
 */

export function CanvasDateiOeffnen() {
  const eingabe = useRef<HTMLInputElement>(null);
  const [laeuft, setLaeuft] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn-secondary btn-small"
        aria-disabled={laeuft || undefined}
        aria-busy={laeuft || undefined}
        onClick={() => {
          if (!laeuft) eingabe.current?.click(); // nur aria-disabled: der Fokus bleibt auf dem Knopf
        }}
      >
        Datei öffnen
      </button>
      <input
        ref={eingabe}
        type="file"
        accept={DATEI_ACCEPT}
        hidden
        tabIndex={-1}
        aria-hidden="true"
        data-testid="canvas-datei"
        onChange={async (e) => {
          const datei = e.currentTarget.files?.[0];
          e.currentTarget.value = ""; // dieselbe Datei lässt sich danach noch einmal wählen
          if (!datei) return;
          setLaeuft(true);
          try {
            const fehler = await dateiOeffnen(datei);
            if (fehler) zeigeToast(fehler);
          } catch {
            zeigeToast("Die Datei ließ sich nicht öffnen.");
          } finally {
            setLaeuft(false);
          }
        }}
      />
    </>
  );
}

const BILD_ENDUNG: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };
const ohneEndung = (name: string) => name.replace(/\.[A-Za-z0-9]{1,5}$/, "");

/** Eine Datei für dieses Format bauen; null, wenn es für das Element nicht geht. */
async function dateiBauen(item: CanvasItem, f: DownloadFormat): Promise<{ blob: Blob; name: string } | null> {
  if (item.kind === "mermaid" && (f === "svg" || f === "png")) {
    const svg = await mermaidSvg(item.text);
    return f === "svg"
      ? { blob: new Blob([svg], { type: "image/svg+xml" }), name: dateiname(item.title, "svg") }
      : { blob: await svgAlsPng(svg), name: dateiname(item.title, "png") };
  }
  if (item.kind === "bild") {
    if (!item.datei) return null;
    if (f === "original") return { blob: item.datei.blob, name: dateiname(ohneEndung(item.title), BILD_ENDUNG[item.datei.mime] ?? "bild") };
    if (f === "png") return { blob: await bildAlsPng(item.datei.blob), name: dateiname(ohneEndung(item.title), "png") };
    return null;
  }
  const d = textDatei(item, f, { logo: f === "html" ? await logoLaden() : undefined });
  return d ? { blob: new Blob([d.inhalt], { type: d.mime }), name: d.name } : null;
}

/** "Herunterladen": aufklappbar im Kopf des Elements, je Art die passenden Formate. */
export function CanvasHerunterladen({ item }: { item: CanvasItem }) {
  const [laeuft, setLaeuft] = useState<DownloadFormat | null>(null);
  const formate = downloadFormate(item);
  if (!formate.length) return null;
  const laden = async (f: DownloadFormat) => {
    if (laeuft !== null) return; // die Knöpfe sind nur aria-disabled, damit der Fokus bleibt
    setLaeuft(f);
    try {
      const datei = await dateiBauen(item, f);
      if (!datei) throw new Error("kein Inhalt");
      herunterladen(datei.blob, datei.name);
      zeigeToast(`${datei.name} liegt im Download-Ordner.`);
    } catch {
      zeigeToast(f === "png" ? "Das PNG ließ sich nicht erzeugen." : "Herunterladen fehlgeschlagen.");
    } finally {
      setLaeuft(null);
    }
  };
  return (
    <details className="canvas-download">
      <summary>Herunterladen</summary>
      <div className="canvas-export" role="group" aria-label="Im Browser herunterladen">
        {formate.map((f) => (
          <button
            key={f}
            type="button"
            className="btn-secondary btn-small"
            aria-disabled={laeuft !== null || undefined}
            aria-busy={laeuft === f || undefined}
            onClick={() => void laden(f)}
          >
            Als {FORMAT_TEXT[f]}
          </button>
        ))}
      </div>
    </details>
  );
}

function host(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/** Bild im Canvas: eigene Bilder direkt (blob:), Bilder von außen als Verweis zum bewussten Öffnen. */
export function BildAnsicht({ item }: { item: Extract<CanvasItem, { kind: "bild" }> }) {
  const d = item.datei;
  if (d && d.src.startsWith("blob:")) {
    return (
      <figure className="canvas-bild">
        {/* eslint-disable-next-line @next/next/no-img-element -- eigene blob:-URL mit geprüftem Typ, next/image kann sie nicht optimieren */}
        <img src={d.src} alt={item.alt || item.title} width={d.breite} height={d.hoehe} />
        <figcaption>
          {d.name} · {groesseText(d.groesse)} · {d.breite} × {d.hoehe} Pixel
        </figcaption>
      </figure>
    );
  }
  if (!item.url) return <p className="notice">Dieses Bild lässt sich nicht anzeigen.</p>;
  return (
    <div className="canvas-bild-verweis">
      {item.alt && <p>{item.alt}</p>}
      <p className="notice">Bilder von anderen Seiten lädt W.A.I.S. aus Sicherheitsgründen nicht selbst. Öffne es, wenn du der Quelle traust.</p>
      <p className="canvas-bild-quelle">
        Quelle: <strong>{host(item.url)}</strong>
      </p>
      {/* die ganze Adresse, auch was hinter dem ? steht: so sieht die Person vor dem Klick, was mitgeschickt würde */}
      <p className="canvas-bild-adresse">
        <code>{item.url}</code>
      </p>
      <a className="btn-secondary btn-small" href={item.url} target="_blank" rel="noopener noreferrer">
        Bild im Browser öffnen
      </a>
    </div>
  );
}
