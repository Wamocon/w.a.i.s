/**
 * Anzeigename einer Person in der Oberfläche: immer der volle Name ("Vorname Nachname"), nie der Teil der E-Mail vor dem @.
 * Der Name kommt vom Kern (Meldung "profil", profiles.display_name). Bis sie da ist (etwa vor dem ersten Gespräch), wird er
 * aus der Anmelde-E-Mail abgeleitet: "vorname.nachname@..." ergibt "Vorname Nachname". Reine Logik ohne Browser und React.
 */

const TRENNER = /[._-]+/;

/** Voller Name aus dem Teil der E-Mail vor dem @, jedes Wort groß begonnen; null, wenn nichts Brauchbares darin steht. */
export function nameAusEmail(email: string | null | undefined): string | null {
  if (typeof email !== "string") return null;
  const at = email.indexOf("@");
  if (at <= 0) return null;
  const woerter = email
    .slice(0, at)
    .split(TRENNER)
    .filter(Boolean)
    .map((w) => w.charAt(0).toLocaleUpperCase("de") + w.slice(1).toLocaleLowerCase("de"));
  return woerter.length > 0 ? woerter.join(" ") : null;
}

/** Was die Oberfläche als Namen zeigt: der volle Name vom Kern, sonst der aus der E-Mail abgeleitete, sonst "Profil". */
export function profilAnzeige(profilName: string | null | undefined, email: string | null | undefined): string {
  const name = typeof profilName === "string" ? profilName.trim() : "";
  return name || nameAusEmail(email) || "Profil";
}
