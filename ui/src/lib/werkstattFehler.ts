import type { FehlerBild } from "./werkstattTypen.ts";

/**
 * Fehler der Werkstatt in klaren deutschen Sätzen. Die Schnittstelle meldet { code, text } ohne interne Namen
 * (docs/adminpanel-bauplan.md, Abschnitt 3); die Oberfläche zeigt für jeden bekannten Code einen eigenen Satz und hängt bei den
 * Codes, bei denen die Einzelheit der Person hilft (ungültige Eingabe, Konflikt), den Text des Dienstes an. Dazu kommen die Codes,
 * die nur die Oberfläche kennt (kein Netz, Zeitüberschreitung, unerwartete Antwort). Ohne React und ohne Netz, damit sich alles
 * mit node:test prüfen lässt (werkstattFehler.test.ts).
 */

export const FEHLER_SAETZE: Readonly<Record<string, string>> = Object.freeze({
  nicht_angemeldet: "Die Anmeldung fehlt oder ist abgelaufen. Bitte melde dich neu an.",
  aal2_fehlt: "Für die Werkstatt ist der zweite Faktor nötig. Bitte melde dich mit dem Code deiner Authenticator-App an.",
  aal2_alt: "Der Code des zweiten Faktors ist zu alt. Bitte gib einen frischen Code aus der Authenticator-App ein.",
  nicht_berechtigt: "Dafür fehlt dir die Berechtigung. Die Werkstatt ist nur für Admins auf der Erlaubnisliste.",
  labor_profil: "Mit einem Laborprofil gibt es keinen Zugang zur Werkstatt.",
  nicht_gefunden: "Das gibt es nicht mehr. Bitte lade die Ansicht neu.",
  karte_verbraucht: "Diese Karte wurde schon benutzt. Bitte fordere eine neue Karte an.",
  konflikt: "Das passt nicht zum aktuellen Stand, zum Beispiel weil es gerade jemand anderes geändert hat. Bitte lade die Ansicht neu und versuche es noch einmal.",
  karte_abgelaufen: "Die Karte ist abgelaufen. Bitte fordere eine neue Karte an.",
  ungueltig: "Die Eingabe ist nicht gültig.",
  zu_oft: "Zu viele Anfragen in kurzer Zeit. Bitte warte eine Minute und versuche es dann noch einmal.",
  nicht_verfuegbar: "Die Werkstatt ist gerade nicht verfügbar. Bitte versuche es gleich noch einmal.",
  // nur die Oberfläche
  netz: "Die Werkstatt ist nicht erreichbar. Sie lässt sich nur aus dem Büronetz oder über WireGuard öffnen.",
  zeit: "Die Werkstatt hat nicht rechtzeitig geantwortet. Bitte versuche es noch einmal.",
  antwort: "Die Antwort der Werkstatt war unerwartet. Bitte lade die Ansicht neu.",
  nicht_eingerichtet: "Die Adresse der Werkstatt ist nicht eingerichtet.",
  abgebrochen: "Abgebrochen.",
});

/** Codes, bei denen die Einzelheit des Dienstes dem Satz angehängt wird (ohne interne Namen, auf Länge und Zeichen geprüft). */
const MIT_DETAIL: ReadonlySet<string> = new Set(["ungueltig", "konflikt", "nicht_gefunden"]);

const DETAIL_MAX = 200;

/** Text des Dienstes säubern: nur Text ohne Steuerzeichen, gekürzt; sonst null. */
export function detailText(roh: unknown): string | null {
  if (typeof roh !== "string") return null;
  // eslint-disable-next-line no-control-regex
  const sauber = roh.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();
  return sauber ? sauber.slice(0, DETAIL_MAX) : null;
}

/** Der Code zu einem Statuswert, wenn der Dienst keinen mitschickt (oder keinen bekannten). */
export function codeZuStatus(status: number): string {
  if (status === 401) return "nicht_angemeldet";
  if (status === 403) return "nicht_berechtigt";
  if (status === 404) return "nicht_gefunden";
  if (status === 409) return "konflikt";
  if (status === 410) return "karte_abgelaufen";
  if (status === 422) return "ungueltig";
  if (status === 429) return "zu_oft";
  if (status >= 500) return "nicht_verfuegbar";
  return "antwort";
}

const KENNUNG = /^[a-z0-9_]{1,40}$/;

/**
 * Das Fehlerbild zu einer Antwort der Schnittstelle. code und serverText stammen aus dem Rumpf { code, text }, beide dürfen fehlen
 * oder falsch sein: Ein unbekannter Code fällt auf den Satz zum Statuswert zurück, nie auf rohen Text des Dienstes allein.
 */
export function fehlerBild(status: number, code: unknown, serverText: unknown): FehlerBild {
  const roh = typeof code === "string" && KENNUNG.test(code) ? code : null;
  const bekannt = roh !== null && Object.prototype.hasOwnProperty.call(FEHLER_SAETZE, roh);
  // 403 mit unbekanntem Code bleibt "nicht berechtigt", 409 und 410 mit unbekanntem Code behalten ihre Bedeutung
  const gewaehlt = bekannt ? (roh as string) : codeZuStatus(status);
  let text = FEHLER_SAETZE[gewaehlt] ?? FEHLER_SAETZE.antwort;
  if (MIT_DETAIL.has(gewaehlt)) {
    const detail = detailText(serverText);
    if (detail && !text.includes(detail)) text = `${text} ${detail}`;
  }
  return { code: gewaehlt, text, status };
}

/** Fehlerbild für einen Fehler der Oberfläche selbst (kein Netz, Zeit, Antwort, Einrichtung). */
export function eigenerFehler(code: "netz" | "zeit" | "antwort" | "nicht_eingerichtet" | "abgebrochen" | "ungueltig", detail?: string): FehlerBild {
  const basis = FEHLER_SAETZE[code];
  return { code, text: detail ? `${basis} ${detail}` : basis, status: 0 };
}

/** Verlangt der Fehler einen neuen Code des zweiten Faktors? */
export function brauchtNeuenCode(code: string): boolean {
  return code === "aal2_alt" || code === "aal2_fehlt";
}

/** Muss die Karte neu angefordert werden? */
export function karteUnbrauchbar(code: string): boolean {
  return code === "karte_abgelaufen" || code === "karte_verbraucht";
}
