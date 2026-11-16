import { AUSROLLEN_SCHRITTE } from "@/components/einrichtung/fuerErstanmeldung";
import { PasswortSchritt } from "@/components/erstanmeldung/PasswortSchritt";
import type { ErstanmeldungSchritt } from "@/components/erstanmeldung/typen";

/**
 * Die Schritte der Erstanmeldung in der Reihenfolge, in der sie laufen (Planpapier docs/ausrollen-neue-nutzer.md, 3 und 4.7).
 * Das ist die einzige Stelle, die die Reihenfolge kennt. Hinter "passwort" folgen die Schritte des Ausrollens nach D2
 * (components/einrichtung/fuerErstanmeldung.tsx): "token" (Claude-Code-Token), "api" (API-Schlüssel), beide überspringbar und bei
 * Admin-Zwang auf Hausmodelle entfallen sie, dann "zusammenfassung" und "installer" (nur im Browser).
 *
 * Passwort: nötig, solange die Erstanmeldung offen ist. Nach einem Neuladen mit erledigtem Passwortwechsel übergeht der Ablauf
 * den Schritt und macht bei den folgenden weiter.
 */
export const ERSTANMELDUNG_SCHRITTE: readonly ErstanmeldungSchritt[] = [
  {
    id: "passwort",
    titel: "Passwort",
    ueberschrift: "Neues Passwort",
    ueberspringbar: false,
    komponente: PasswortSchritt,
    noetig: (kontext) => kontext.standStart === "offen",
  },
  ...AUSROLLEN_SCHRITTE,
];
