"use client";

import { hexAusBytes, installerFehlerText, manifestAusAntwort, sha256Gleich, type InstallerManifest } from "@/lib/installer";
import { KernFehler, kernDateiStrom, kernJson, type Fortschritt } from "@/lib/kernApi";

/**
 * Installer vom Kern (voice-core/verteilung_api.py, docs/ausrollen-neue-nutzer.md 4.2). Der Download läuft mit dem Token
 * der Sitzung über fetch (ein Link schickt keinen Bearer mit), gestreamt mit Fortschritt (lib/kernApi.ts, kernDateiStrom).
 * Angeboten wird die Datei nur, wenn Größe und SHA-256 genau zum geprüften Manifest passen; sonst wird sie verworfen und
 * nie gespeichert. Keine Funktion wirft: Fehler kommen als konkreter Satz (lib/installer.ts, installerFehlerText).
 */

export type InstallerStand = { ok: true; manifest: InstallerManifest } | { ok: false; text: string };
export type LadeErgebnis = { ok: true } | { ok: false; text: string; abgebrochen: boolean };

export const PRUEFSUMME_FALSCH = "Die Prüfsumme stimmt nicht. Die Datei wurde verworfen.";
const UNGUELTIG = "Die Angaben des Kerns zum Installer sind ungültig. Bitte frag Niko.";
const UNVOLLSTAENDIG = "Die Datei ist unvollständig angekommen und wurde verworfen. Bitte noch einmal versuchen.";
const OHNE_PRUEFUNG = "Die Prüfsumme ließ sich hier nicht berechnen. Die Datei wurde verworfen.";
const ABGEBROCHEN: LadeErgebnis = { ok: false, text: installerFehlerText(0, null, "Abgebrochen"), abgebrochen: true };

function fehlerText(e: unknown): string {
  return e instanceof KernFehler ? installerFehlerText(e.status, e.code, e.message) : installerFehlerText(0, null);
}

/** Version, Größe und Prüfsumme des aktuellen Installers, streng geprüft (lib/installer.ts, manifestAusAntwort). */
export async function installerStand(): Promise<InstallerStand> {
  try {
    const manifest = manifestAusAntwort(await kernJson("/installer"));
    return manifest ? { ok: true, manifest } : { ok: false, text: UNGUELTIG };
  } catch (e) {
    return { ok: false, text: fehlerText(e) };
  }
}

/** Bytes als Download anbieten (immer als Datei, nie im Fenster geöffnet), mit dem Namen aus dem Manifest. */
function anbieten(bytes: Uint8Array<ArrayBuffer>, name: string): void {
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Installer laden, Größe und SHA-256 prüfen und nur bei passender Prüfsumme als Datei anbieten. onFortschritt meldet
 * geladene Bytes und Gesamtgröße, signal bricht ab (auch noch nach dem Laden: dann wird nichts angeboten).
 */
export async function installerLaden(
  manifest: InstallerManifest,
  onFortschritt?: Fortschritt,
  signal?: AbortSignal,
): Promise<LadeErgebnis> {
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await kernDateiStrom("/installer/datei", { hoechstens: manifest.groesse, onFortschritt, signal });
  } catch (e) {
    if (e instanceof KernFehler && e.status === 0 && signal?.aborted) return ABGEBROCHEN;
    return { ok: false, text: fehlerText(e), abgebrochen: false };
  }
  if (bytes.byteLength !== manifest.groesse) return { ok: false, text: UNVOLLSTAENDIG, abgebrochen: false };
  let summe: string;
  try {
    summe = hexAusBytes(await crypto.subtle.digest("SHA-256", bytes));
  } catch {
    return { ok: false, text: OHNE_PRUEFUNG, abgebrochen: false };
  }
  if (!sha256Gleich(summe, manifest.sha256)) return { ok: false, text: PRUEFSUMME_FALSCH, abgebrochen: false };
  if (signal?.aborted) return ABGEBROCHEN;
  anbieten(bytes, manifest.datei);
  return { ok: true };
}
