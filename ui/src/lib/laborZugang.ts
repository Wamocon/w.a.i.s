"use client";

import { KernFehler, kernJson } from "@/lib/kernApi";
import { alsLaborZugang, fehlerBild, faktorFrisch, type FehlerBild, type LaborZugang } from "@/lib/laborZugangLogik";
import { accessToken } from "@/lib/supabase";

/**
 * Aufrufe für den Claude-Zugang des Testlabors an den KERN (voice-core/labor_zugang_api.py), nicht an den Werkstatt-Dienst: Der Dienst bleibt
 * ohne Geheimnisse. Basis, Token, Zeitgrenze und Fehlerbehandlung sind die von lib/kernApi.ts (das Token steht nur im Header Authorization,
 * nie in einer Adresse, nie im Zustand einer Komponente). Der Schlüssel geht nur im Body des PUT an den Kern und nirgends sonst hin:
 * nicht in die Adresse, nicht in den Speicher des Browsers, nicht in ein Protokoll. Die Antwort enthält ihn nie.
 *
 * Ändernde Aufrufe nimmt der Kern nur an, wenn der Code der Authenticator-App höchstens 60 Sekunden alt ist (Zeitstempel im Token, Claim amr).
 * faktorIstFrisch sagt das vorher; frischen Code holt lib/geraeteVerwaltungApi.ts (codeBestaetigen).
 */

const PFAD = "/admin/labor-zugang";

/** Wirft KernFehler (Status, Text und Code des Kerns) oder einen KernFehler 502 bei einer unerwarteten Antwort. */
function lesen(daten: unknown): LaborZugang {
  const z = alsLaborZugang(daten);
  if (!z) throw new KernFehler(502, "Die Antwort des Kerns war unerwartet.", "antwort");
  return z;
}

export async function laborZugangLaden(): Promise<LaborZugang> {
  return lesen(await kernJson(PFAD));
}

/** Prüft den Schlüssel beim Kern (der fragt Anthropic) und speichert ihn nur bei Erfolg. workspace nur, wenn der Schlüssel zu keinem gehört. */
export async function laborZugangSetzen(schluessel: string, workspace: string | null): Promise<LaborZugang> {
  return lesen(await kernJson(PFAD, "PUT", workspace ? { schluessel, workspace } : { schluessel }));
}

/** Entfernt den gespeicherten Schlüssel; danach gilt wieder der Schlüssel des Servers. */
export async function laborZugangEntfernen(): Promise<LaborZugang> {
  return lesen(await kernJson(PFAD, "DELETE"));
}

/** Ist der zweite Faktor im aktuellen Token jung genug für eine Änderung? */
export async function faktorIstFrisch(): Promise<boolean> {
  return faktorFrisch(await accessToken(), Date.now());
}

/** Das Fehlerbild zu einem beliebigen Fehler eines Aufrufs (Anzeige in der Oberfläche). */
export function fehlerBildAus(e: unknown): FehlerBild {
  if (e instanceof KernFehler) return fehlerBild(e.status, e.code, e.message);
  return fehlerBild(0, null, null);
}
