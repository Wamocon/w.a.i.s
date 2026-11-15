"use client";

import type { EinrichtungsSchrittProps } from "./schritte";
import { SchluesselSchritt } from "./SchluesselSchritt";

/**
 * Schritt 3a beim Ausrollen (D2): zuerst der Claude-Code-Token aus `claude setup-token` (Max-Tarif). Er gilt nur für
 * Entwicklungsaufträge und hat dort Vorrang vor dem API-Schlüssel. Überspringbar.
 */
export function SchrittToken(p: EinrichtungsSchrittProps) {
  return <SchluesselSchritt id="token" {...p} />;
}
