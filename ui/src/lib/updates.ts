import { PRUEF_ABSTAND_MS } from "./einrichtung.ts";
import type { Stufe, UpdateAngebot, UpdateInstallation, UpdateStand } from "./einrichtung.ts";

/**
 * Reine Logik des Abschnitts "Updates" der Einstellungen (components/einstellungen/Updates.tsx), ohne React und ohne Browser, damit
 * sie sich mit node:test prüfen lässt (updates.test.ts). Die Quelle ist dieselbe wie beim Punkt App-Version der Prüfliste in den
 * Ersten Schritten (lib/einrichtung.ts): der Server legt ein signiertes Manifest bereit, die App bestätigt Signatur und steigende
 * Version, erst dann gibt es ein Angebot. Die Oberfläche liest das Manifest nie selbst, sie reicht es nur an die App weiter. Das Token
 * holt erst der Klick auf "Update installieren" (updateInstallieren in lib/einrichtung.ts) und gibt es nur an die App; es steht in keinem
 * Zustand und in keinem Text dieser Datei.
 *
 * Aus Version, Stand der Prüfung und Phase der Installation entsteht eine Ansicht: Zustand, Titel und Satz (das Zeichen trägt die
 * Stufe, die Farbe nie allein), die Versionen für die Anzeige und, nur nach der Bestätigung der App, das Angebot für den Knopf.
 */

/** Phase der Installation: nichts läuft, die App fragt und lädt (Aufruf offen), die App hat gestartet, die App meldet einen Fehler. */
export type InstallPhase = { art: "ruhe" } | { art: "laeuft" } | { art: "gestartet" } | { art: "fehler"; text: string };

export const PHASE_RUHE: InstallPhase = Object.freeze({ art: "ruhe" });

/** Die Phase nach der Antwort der App: abgebrochen heißt still zurück (der Knopf bleibt), sonst gestartet oder ein Fehler mit ihrem Satz. */
export function phaseNachInstallation(erg: UpdateInstallation): InstallPhase {
  if (erg.ok) return { art: "gestartet" };
  return erg.abgebrochen ? PHASE_RUHE : { art: "fehler", text: erg.text };
}

export type UpdateZustand = "laedt" | "aktuell" | "verfuegbar" | "installiert" | "fehler" | "nicht_moeglich";

export type UpdateAnsicht = Readonly<{
  zustand: UpdateZustand;
  /** Stufe des Zeichens, wie in der Prüfliste: gruen ist in Ordnung, rot braucht Aufmerksamkeit, hinweis ist neutral */
  stufe: Stufe;
  titel: string;
  satz: string;
  /** eine weitere Zeile in kleiner Schrift, wo es einen Weg weiter gibt */
  hinweis: string | null;
  /** Version dieser App oder "unbekannt" */
  installiert: string;
  /** was der Server anbietet: eine Version oder ein kurzer Satzteil */
  server: string;
  /** nur nach der Bestätigung der App und solange nichts gescheitert oder gestartet ist; bleibt während der Installation, damit der Knopf stehen bleibt */
  angebot: UpdateAngebot | null;
  /** die App kann nicht selbst prüfen: der Installer zum Herunterladen ist der Weg */
  installerAnbieten: boolean;
}>;

export const BROWSER_SATZ =
  "Im Browser gibt es nichts zu aktualisieren. Updates installiert die Desktop-App selbst, den Installer für Windows findest du unten.";

const T_LAEDT = "Die App fragt den Server, ob es ein Update gibt.";
const T_AKTUELL = "Du nutzt die neueste Version.";
const T_KEIN_ANGEBOT = "Der Server bietet noch kein Update an.";
const T_VERFUEGBAR = "Die App lädt den Installer erst, wenn du die Rückfrage bestätigst, prüft ihn und startet danach neu.";
export const SATZ_LAEUFT = "Bestätige die Rückfrage im Fenster der App. Danach lädt die App den Installer und prüft ihn.";
const T_GESTARTET = "Die App installiert das Update und startet danach neu.";
const T_FEHLER_WEITER = "Suche noch einmal mit „Nach Updates suchen“, um es erneut zu versuchen.";
const T_UNBEKANNT = "Ob es ein Update gibt, lässt sich gerade nicht prüfen. Versuche es später noch einmal.";
const T_OHNE_PRUEFUNG = "Diese Version der App kann Updates nicht selbst prüfen. Installiere einmal den aktuellen Installer von Hand, danach geht es hier.";

type Kern = Pick<UpdateAnsicht, "zustand" | "stufe" | "titel" | "satz"> & Partial<Pick<UpdateAnsicht, "hinweis" | "installerAnbieten">>;

/** Zustand, Titel und Satz zu einem Stand der Prüfung (ohne Phase der Installation). */
function ausStand(stand: UpdateStand): Kern {
  switch (stand.art) {
    case "ohne_pruefung":
      return { zustand: "nicht_moeglich", stufe: "hinweis", titel: "Prüfung nicht möglich", satz: T_OHNE_PRUEFUNG, installerAnbieten: true };
    case "kein_angebot":
      return { zustand: "aktuell", stufe: "gruen", titel: "Aktuell", satz: T_KEIN_ANGEBOT };
    case "unbekannt":
      return { zustand: "nicht_moeglich", stufe: "hinweis", titel: "Prüfung nicht möglich", satz: T_UNBEKANNT };
    case "geprueft": {
      const e = stand.ergebnis;
      if (!e.ok) return { zustand: "nicht_moeglich", stufe: "rot", titel: "Prüfung nicht möglich", satz: e.text };
      if (!e.neuer) return { zustand: "aktuell", stufe: "gruen", titel: "Aktuell", satz: T_AKTUELL };
      return { zustand: "verfuegbar", stufe: "rot", titel: `Update verfügbar (Version ${e.version})`, satz: T_VERFUEGBAR };
    }
  }
}

/** Was der Server anbietet, für die Anzeige neben der installierten Version. */
function serverText(stand: UpdateStand | null): string {
  if (!stand) return "wird geprüft";
  if (stand.art === "kein_angebot") return "noch kein Update";
  if (stand.art === "geprueft" && stand.ergebnis.ok) return stand.ergebnis.version;
  return "nicht geprüft";
}

/** Das Angebot für den Knopf (auch für das Pop-up, components/UpdateHinweis.tsx): nur, wenn die App ein neueres Update bestätigt hat. */
export function angebotAus(stand: UpdateStand | null): UpdateAngebot | null {
  if (stand?.art !== "geprueft" || !stand.ergebnis.ok || !stand.ergebnis.neuer) return null;
  return { version: stand.ergebnis.version, manifest: stand.manifest.manifest, signatur: stand.manifest.signatur };
}

/**
 * Die Ansicht des Abschnitts. version ist die Version der laufenden App (appVersion in lib/installer.ts) oder null; stand ist
 * der Stand der Prüfung (null, solange die erste Prüfung läuft); phase sagt, ob gerade installiert wird oder ob das gescheitert ist.
 * Ein Fehler der Installation oder ein gestarteter Neustart gehen vor dem Stand der Prüfung.
 */
export function updateAnsicht(o: { version: string | null; stand: UpdateStand | null; phase: InstallPhase }): UpdateAnsicht {
  const gemeinsam = { installiert: o.version ?? "unbekannt", server: serverText(o.stand), hinweis: null, installerAnbieten: false };
  const { phase, stand } = o;
  if (phase.art === "fehler") {
    return { ...gemeinsam, zustand: "fehler", stufe: "rot", titel: "Fehler", satz: phase.text, hinweis: T_FEHLER_WEITER, angebot: null };
  }
  if (phase.art === "gestartet") {
    return { ...gemeinsam, zustand: "installiert", stufe: "hinweis", titel: "Wird installiert", satz: T_GESTARTET, angebot: null };
  }
  if (!stand) return { ...gemeinsam, zustand: "laedt", stufe: "hinweis", titel: "Wird geprüft", satz: T_LAEDT, angebot: null };
  const angebot = angebotAus(stand);
  if (phase.art === "laeuft") {
    return { ...gemeinsam, zustand: "installiert", stufe: "hinweis", titel: "Wird installiert", satz: SATZ_LAEUFT, angebot };
  }
  return { ...gemeinsam, ...ausStand(stand), angebot };
}

/** Zeile unter den Knöpfen: Prüfe ..., Uhrzeit der letzten Prüfung und, solange die Sperre gilt, der Grund für den ruhenden Knopf. */
export function suchStand(laeuft: boolean, gesperrt: boolean, zeit: string | null): string {
  if (laeuft) return "Prüfe ...";
  const geprueft = zeit ? `Geprüft um ${zeit} Uhr.` : "";
  return gesperrt ? `${geprueft} Nach Updates suchen geht einmal je ${PRUEF_ABSTAND_MS / 1000} Sekunden.`.trim() : geprueft;
}
