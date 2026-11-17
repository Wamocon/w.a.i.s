"use client";

import { useSyncExternalStore } from "react";
import { serverBrowser } from "@/lib/geraet";
import {
  pcStufeLesen,
  pcStufeMerken,
  PC_STUFE_PRAEFIX,
  rolleLesen,
  rolleMerken,
  ROLLE_PRAEFIX,
  type MitgliedStufe,
  type Rolle,
} from "@/lib/pcSchalter";
import { schalterLesen, schalterSchluessel, schalterSchreiben, SCHALTER_PRAEFIX } from "@/lib/stillStart";
import { untertitelLesen, untertitelSchluessel, untertitelSchreiben, UNTERTITEL_PRAEFIX } from "@/lib/untertitel";

/**
 * Gerätebezogene Einstellungen (nur dieser Browser bzw. diese Desktop-App), gespeichert in
 * localStorage. Lesen und Schreiben sind abgesichert: ohne Speicher (privates Fenster, gesperrte
 * Website-Daten) gilt der Wert nur bis zum Neuladen. Nie Geheimnisse hier ablegen.
 *
 * "PC-Steuerung beim Start automatisch einschalten": Standard aus, wirkt nur für Profile mit Rolle
 * admin (useWamo prüft das zusätzlich), Schalter in WamoAnsicht neben "PC-Steuerung".
 */

const PC_AUTO = "wamo.pcSteuerungAuto";
let pcAutoSpeicher = false; // Rückfall, wenn localStorage nicht verfügbar ist
const hoerer = new Set<() => void>();

export function pcAutoLesen(): boolean {
  if (typeof window === "undefined") return false;
  if (serverBrowser()) return false; // Autostart nur in der Desktop-App: im Büro braucht er ihren Rechnernamen (useWamo)
  try {
    return window.localStorage.getItem(PC_AUTO) === "an";
  } catch {
    return pcAutoSpeicher;
  }
}

export function pcAutoSetzen(an: boolean) {
  pcAutoSpeicher = an;
  try {
    if (an) window.localStorage.setItem(PC_AUTO, "an");
    else window.localStorage.removeItem(PC_AUTO);
  } catch {
    // kein Speicher: Wert bleibt bis zum Neuladen im Rückfall
  }
  hoerer.forEach((h) => h());
}

function pcAutoAbonnieren(h: () => void) {
  hoerer.add(h);
  // Änderung in einem anderen Fenster derselben App
  const onStorage = (e: StorageEvent) => {
    if (e.key === PC_AUTO) h();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    hoerer.delete(h);
    window.removeEventListener("storage", onStorage);
  };
}

/** Aktueller Wert der Einstellung für die Oberfläche (Server: immer aus). */
export function usePcAuto(): boolean {
  return useSyncExternalStore(pcAutoAbonnieren, pcAutoLesen, () => false);
}

// ---------- Still starten beim Tippen (KP-1A, lib/stillStart.ts) ----------
// Schalter je Gerät und je Person (Schlüssel mit der user_id), Standard an (lib/stillStart.ts, SCHALTER_STANDARD), kein Server-Zustand. Ohne localStorage gilt der Wert bis zum
// Neuladen. Wirksam wird er nur für Konten, die keine Laborkonten sind (lib/useStillStart.ts, useWamo.stillStarten).
const stillSpeicher = new Map<string, boolean>(); // Rückfall, wenn localStorage nicht verfügbar ist

function lokalerSpeicher() {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function stillStartLesen(userId: string | null | undefined): boolean {
  const k = schalterSchluessel(userId);
  if (!k) return false;
  if (stillSpeicher.has(k)) return stillSpeicher.get(k) === true;
  return schalterLesen(lokalerSpeicher(), userId);
}

export function stillStartSetzen(userId: string | null | undefined, an: boolean) {
  const k = schalterSchluessel(userId);
  if (!k) return;
  if (schalterSchreiben(lokalerSpeicher(), userId, an)) stillSpeicher.delete(k);
  else stillSpeicher.set(k, an);
  hoerer.forEach((h) => h());
}

function stillAbonnieren(h: () => void) {
  hoerer.add(h);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(SCHALTER_PRAEFIX)) h();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    hoerer.delete(h);
    window.removeEventListener("storage", onStorage);
  };
}

/** Wert des Schalters für diese Person auf diesem Gerät (Server: aus). */
export function useStillStart(userId: string | null | undefined): boolean {
  return useSyncExternalStore(stillAbonnieren, () => stillStartLesen(userId), () => false);
}

// ---------- Zuletzt gemeldete Rolle (lib/pcSchalter.ts) ----------
// Der Kern meldet die Rolle erst in einer Sitzung. Damit der Schalter "PC-Steuerung" schon vorher da ist, merkt sich die Oberfläche die
// zuletzt gemeldete Rolle je Person auf diesem Gerät. Nur eine Anzeigehilfe: Was gilt, prüft der Kern.

export function rolleGemerktLesen(userId: string | null | undefined): Rolle | null {
  return rolleLesen(lokalerSpeicher(), userId);
}

export function rolleGemerktSetzen(userId: string | null | undefined, rolle: Rolle) {
  if (rolleGemerktLesen(userId) === rolle) return;
  if (rolleMerken(lokalerSpeicher(), userId, rolle)) hoerer.forEach((h) => h());
}

function rolleAbonnieren(h: () => void) {
  hoerer.add(h);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(ROLLE_PRAEFIX)) h();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    hoerer.delete(h);
    window.removeEventListener("storage", onStorage);
  };
}

/** Gemerkte Rolle dieser Person auf diesem Gerät (Server: unbekannt). */
export function useRolleGemerkt(userId: string | null | undefined): Rolle | null {
  return useSyncExternalStore(rolleAbonnieren, () => rolleGemerktLesen(userId), () => null);
}

// ---------- Zuletzt gemeldete Stufe "mitglied" der PC-Steuerung (lib/pcSchalter.ts) ----------
// Wie die Rolle: Damit ein freigeschaltetes Mitglied den Schalter "PC-Steuerung" auch ohne Sitzung findet, merkt sich die Oberfläche die
// Stufe, die der Kern zuletzt gemeldet hat, je Person auf diesem Gerät. Nur eine Anzeigehilfe: Was gilt, prüft der Kern.

export function pcStufeGemerktLesen(userId: string | null | undefined): MitgliedStufe | null {
  return pcStufeLesen(lokalerSpeicher(), userId);
}

export function pcStufeGemerktSetzen(userId: string | null | undefined, stufe: MitgliedStufe | null) {
  if (pcStufeGemerktLesen(userId) === stufe) return;
  if (pcStufeMerken(lokalerSpeicher(), userId, stufe)) hoerer.forEach((h) => h());
}

function pcStufeAbonnieren(h: () => void) {
  hoerer.add(h);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(PC_STUFE_PRAEFIX)) h();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    hoerer.delete(h);
    window.removeEventListener("storage", onStorage);
  };
}

/** Gemerkte Stufe "mitglied" dieser Person auf diesem Gerät (Server: unbekannt). */
export function usePcStufeGemerkt(userId: string | null | undefined): MitgliedStufe | null {
  return useSyncExternalStore(pcStufeAbonnieren, () => pcStufeGemerktLesen(userId), () => null);
}

// ---------- Live-Untertitel unter dem Kern (lib/untertitel.ts) ----------
// Schalter je Gerät und je Person, Standard aus, kein Server-Zustand. Ohne localStorage gilt der Wert bis zum Neuladen.
const untertitelSpeicher = new Map<string, boolean>(); // Rückfall, wenn localStorage nicht verfügbar ist

export function untertitelGemerkt(userId: string | null | undefined): boolean {
  const k = untertitelSchluessel(userId);
  if (!k) return false;
  if (untertitelSpeicher.has(k)) return untertitelSpeicher.get(k) === true;
  return untertitelLesen(lokalerSpeicher(), userId);
}

export function untertitelSetzen(userId: string | null | undefined, an: boolean) {
  const k = untertitelSchluessel(userId);
  if (!k) return;
  if (untertitelSchreiben(lokalerSpeicher(), userId, an)) untertitelSpeicher.delete(k);
  else untertitelSpeicher.set(k, an);
  hoerer.forEach((h) => h());
}

function untertitelAbonnieren(h: () => void) {
  hoerer.add(h);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(UNTERTITEL_PRAEFIX)) h();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    hoerer.delete(h);
    window.removeEventListener("storage", onStorage);
  };
}

/** Zeigt die Mitte die Live-Untertitel für diese Person auf diesem Gerät? (Server: aus) */
export function useUntertitel(userId: string | null | undefined): boolean {
  return useSyncExternalStore(untertitelAbonnieren, () => untertitelGemerkt(userId), () => false);
}
