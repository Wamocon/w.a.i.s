"use client";

import { useBetriebsart } from "@/lib/betriebsart";
import { useRolleGemerkt } from "@/lib/einstellungen";
import { useDesktopApp } from "@/lib/geraet";
import { useNutzer } from "@/lib/nutzer";
import { pcAdmin, pcFern, schalterAnzeige, type SchalterAnzeige } from "@/lib/pcSchalter";
import { useSelect } from "@/lib/store";
import { istLaborKonto } from "@/lib/stillStart";
import { useStillStartErlaubt } from "@/lib/useStillStart";
import { wamo } from "@/lib/wamo";

/**
 * Steuert dieses Fenster den Laptop aus der Ferne (Browser in der Betriebsart Büro, lib/pcSchalter.ts, pcFern)? Mit Sitzung gilt, was
 * der Kern als Modus meldet, sonst die gewählte Betriebsart für das nächste Gespräch.
 */
export function usePcFern(): boolean {
  const desktop = useDesktopApp();
  const gewaehlt = useBetriebsart();
  const modus = useSelect(wamo, (s) => s.betrieb?.modus ?? null);
  return pcFern({ desktop, buero: modus ? modus === "buero" : gewaehlt === "buero" });
}

/**
 * Wie der Schalter "PC-Steuerung" erscheint (lib/pcSchalter.ts, schalterAnzeige): für den Schalter in den Einstellungen, den Block
 * "PC-Steuerung" und den Weg aus der Kopfzeile. admin: die Rolle vom Kern, ohne Sitzung die gemerkte; Laborkonten nie. Desktop-App und
 * Browser gleich; fern: der Browser steuert den Laptop aus dem Geräteregister (usePcFern).
 */
export function usePcSchalter(): { admin: boolean; anzeige: SchalterAnzeige; fern: boolean } {
  const nutzer = useNutzer();
  const rolleKern = useSelect(wamo, (s) => s.profil?.rolle ?? null);
  const rolleGemerkt = useRolleGemerkt(nutzer.id);
  const presence = useSelect(wamo, (s) => s.presence);
  const wartet = useSelect(wamo, (s) => s.pcEinschalten.wartet);
  // nur die zwei Felder, die der Schalter braucht: kein Neuzeichnen bei jeder Latenzmeldung
  const pc = useSelect(wamo, (s) => s.betrieb?.pc ?? null);
  const pcSteuerung = useSelect(wamo, (s) => s.betrieb?.pcSteuerung ?? "aus");
  const pcStufeKern = useSelect(wamo, (s) => s.betrieb?.pcStufe ?? null);
  const fern = usePcFern();
  const { erlaubt: stillErlaubt } = useStillStartErlaubt();
  const admin = pcAdmin({ rolleKern, rolleGemerkt, laborKonto: istLaborKonto(nutzer.email), pcStufeKern });
  const betrieb = pc ? { pc, pcSteuerung } : null;
  return { admin, anzeige: schalterAnzeige({ admin, presence, stillErlaubt, wartet, betrieb }), fern };
}
