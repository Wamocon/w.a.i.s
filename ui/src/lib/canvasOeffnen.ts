"use client";

import type { CanvasItem } from "@/components/Canvas";
import { bildPruefen, dateiEinordnen, lokaleKennung, textAlsItem, textDekodieren } from "@/lib/canvasDatei";
import { alsHistorie, type Historie } from "@/lib/canvasHistorie";
import { alsCanvasAntwort, KernFehler, kernJson, type CanvasAntwort } from "@/lib/kernApi";
import { parseServerMessage, sauber } from "@/lib/nachrichten";
import { canvasZeigen, zeigeToast } from "@/lib/wamo";

/**
 * Elemente aufs Canvas holen: aus der Datenbank (geteilte Arbeit, Historie) über den Kern und eigene Dateien nur im Browser.
 * Alles läuft durch dieselbe Prüfung wie Nachrichten des Kerns (lib/nachrichten.ts); eigene Bilder prüft lib/canvasDatei.ts.
 */

/** Antwort von GET /wamo/api/geteilt/canvas/{id}: neueste Fassung eines eigenen oder geteilten Elements (voice-core/teilen.py). */
export async function canvasLaden(canvasId: string): Promise<CanvasAntwort> {
  const antwort = alsCanvasAntwort(await kernJson(`/geteilt/canvas/${encodeURIComponent(canvasId)}`));
  if (!antwort) throw new KernFehler(0, "Unerwartete Antwort des Kerns");
  return antwort;
}

/** Ein Element aus der Antwort, geprüft; fremde Arbeit trägt die Angabe geteilt (Besitzer und Recht). */
function ausAntwort(antwort: CanvasAntwort): CanvasItem | null {
  const geteilt = antwort.recht === "besitzer" ? undefined : { von: antwort.besitzer, recht: antwort.recht };
  const msg = parseServerMessage({ type: "canvas", item: { ...antwort.item, geteilt } });
  return msg?.type === "canvas" ? msg.item : null;
}

/** Aufs Canvas legen und zeigen (Geteilte Arbeit): ein ausdrücklicher Klick öffnet das Element auch, wenn sein Reiter geschlossen war. */
export function aufsCanvas(antwort: CanvasAntwort): void {
  const item = ausAntwort(antwort);
  if (item) canvasZeigen(item, `Neues Ergebnis auf dem Canvas: ${item.title}`);
  else zeigeToast("Dieses Dokument lässt sich nicht anzeigen");
}

/** Historie aus der Datenbank (GET /wamo/api/canvas/historie, voice-core/canvas_historie.py). */
export async function historieLaden(): Promise<Historie> {
  const h = alsHistorie(await kernJson("/canvas/historie"));
  if (!h) throw new KernFehler(0, "Unerwartete Antwort des Kerns");
  return h;
}

/** Ein Element aus der Historie (Datenbank) wieder als Reiter öffnen und zeigen. */
export async function ausHistorieOeffnen(canvasId: string): Promise<void> {
  const item = ausAntwort(await canvasLaden(canvasId));
  if (!item) throw new KernFehler(0, "Dieses Element lässt sich nicht anzeigen");
  canvasZeigen(item, `Wieder geöffnet: ${item.title}`);
}

/** Was die Historie zum Laden und Öffnen braucht (fehlt für Laborkonten: dann nur die geschlossenen Reiter dieser Sitzung). */
export type HistorieQuelle = { laden: () => Promise<Historie>; oeffnen: (canvasId: string) => Promise<void> };
export const HISTORIE_QUELLE: HistorieQuelle = { laden: historieLaden, oeffnen: ausHistorieOeffnen };

/**
 * Eine Datei der Person im Canvas zeigen (lib/canvasDatei.ts). Sie bleibt im Browser: kein Upload, kein Modell. Liefert null bei Erfolg,
 * sonst den Satz für die Person.
 */
export async function dateiOeffnen(datei: File): Promise<string | null> {
  const einordnung = dateiEinordnen(datei.name, datei.size);
  if ("fehler" in einordnung) return einordnung.fehler;
  const bytes = new Uint8Array(await datei.arrayBuffer());
  const titel = sauber(datei.name, 200, false);
  if (einordnung.art === "bild") {
    const bild = bildPruefen(bytes, bytes.length);
    if ("fehler" in bild) return bild.fehler;
    const blob = new Blob([bytes], { type: bild.mime }); // genau der geprüfte Typ, nie der des Browsers
    const bilddatei = { src: URL.createObjectURL(blob), mime: bild.mime, groesse: bytes.length, name: titel, blob, breite: bild.breite, hoehe: bild.hoehe };
    canvasZeigen({ id: lokaleKennung(), kind: "bild", title: titel, alt: titel, datei: bilddatei }, `Datei geöffnet: ${titel}`);
    return null;
  }
  const text = textDekodieren(bytes);
  if (text === null) return "Die Datei enthält keinen lesbaren Text.";
  const roh = textAlsItem(titel, text, einordnung);
  const msg = roh ? parseServerMessage({ type: "canvas", item: { ...roh, id: lokaleKennung() } }) : null;
  if (msg?.type !== "canvas") return "Die Datei ist leer oder lässt sich nicht anzeigen.";
  canvasZeigen(msg.item, `Datei geöffnet: ${titel}`);
  return null;
}
