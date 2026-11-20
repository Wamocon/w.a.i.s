"use client";

import { LoginGate } from "@/components/LoginGate";
import { Werkstatt } from "@/components/werkstatt/Werkstatt";

/**
 * Werkstatt (Admin-Panel): eigene Seite neben der Kommandozentrale, erreichbar unter /werkstatt. Die Anmeldung ist dieselbe wie auf
 * der Hauptseite (Passwort und zweiter Faktor); ob die Person hinein darf, entscheidet der Dienst wamo-werkstatt.
 */
export default function WerkstattSeite() {
  return <LoginGate>{(sitzung) => <Werkstatt sitzung={sitzung} />}</LoginGate>;
}
