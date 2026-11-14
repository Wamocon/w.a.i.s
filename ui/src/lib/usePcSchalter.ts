"use client";

import { useRolleGemerkt } from "@/lib/einstellungen";
import { useDesktopApp, useServerBrowser } from "@/lib/geraet";
import { useNutzer } from "@/lib/nutzer";
import { pcAdmin, schalterAnzeige, type SchalterAnzeige } from "@/lib/pcSchalter";
import { useSelect } from "@/lib/store";
import { istLaborKonto } from "@/lib/stillStart";
import { useStillStartErlaubt } from "@/lib/useStillStart";
import { wamo } from "@/lib/wamo";

/**
 * Wie der Schalter "PC-Steuerung" erscheint (lib/pcSchalter.ts, schalterAnzeige): für den Schalter in den Einstellungen, den Block
 * "PC-Steuerung" und den Weg aus der Kopfzeile. admin: die Rolle vom Kern, ohne Sitzung die gemerkte; Laborkonten nie.
 */
export function usePcSchalter(): { admin: boolean; anzeige: SchalterAnzeige } {
  const nutzer = useNutzer();
  const rolleKern = useSelect(wamo, (s) => s.profil?.rolle ?? null);
  const rolleGemerkt = useRolleGemerkt(nutzer.id);
  const presence = useSelect(wamo, (s) => s.presence);
  const wartet = useSelect(wamo, (s) => s.pcEinschalten.wartet);
  const desktop = useDesktopApp();
  const serverBrowser = useServerBrowser();
  const { erlaubt: stillErlaubt } = useStillStartErlaubt();
  const admin = pcAdmin({ rolleKern, rolleGemerkt, laborKonto: istLaborKonto(nutzer.email) });
  return { admin, anzeige: schalterAnzeige({ admin, serverBrowser, desktop, presence, stillErlaubt, wartet }) };
}
