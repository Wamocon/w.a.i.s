import { PasswortSchritt } from "@/components/erstanmeldung/PasswortSchritt";
import type { ErstanmeldungSchritt } from "@/components/erstanmeldung/typen";

/**
 * Die Schritte der Erstanmeldung in der Reihenfolge, in der sie laufen (Planpapier docs/ausrollen-neue-nutzer.md, 3 und 4.7).
 * Das ist die einzige Stelle, die die Reihenfolge kennt. Weitere Schritte (zum Beispiel "token" und "schluessel" für den
 * Claude-Code-Token und den API-Schlüssel, beide überspringbar) kommen als Eintrag hinter "passwort" dazu:
 *
 *   { id: "token", titel: "Token", ueberspringbar: true, komponente: TokenSchritt, noetig: async (k) => !(await tokenDa(k)) },
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
];
