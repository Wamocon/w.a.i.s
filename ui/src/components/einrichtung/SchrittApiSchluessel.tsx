"use client";

import type { EinrichtungsSchrittProps } from "./schritte";
import { SchluesselSchritt } from "./SchluesselSchritt";

/**
 * Schritt 3b beim Ausrollen (D2): danach der API-Schlüssel aus der Anthropic-Konsole. Mit ihm läuft das Gespräch auf Claude
 * Haiku; ohne Token laufen auch die Entwicklungsaufträge darüber. Der Kern prüft ihn mit einer kleinen Anfrage. Überspringbar.
 */
export function SchrittApiSchluessel(p: EinrichtungsSchrittProps) {
  return <SchluesselSchritt id="api" {...p} />;
}
