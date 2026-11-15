// Jira-Stories aus dem Canvas (voice-core/jira_werkzeuge.py). Die Oberfläche entscheidet nichts: Der Knopf "Als User Story in Jira" fragt
// beim Kern nur die Freigabekarte an (Nachricht jira_story mit der Kennung des eigenen Canvas-Dokuments), angelegt wird erst nach dem Klick
// auf "Freigeben" auf der Karte mit Job "jira". Der Kern meldet mit jira_status, dass er Stories anbietet (nur Admin im Büro), und mit
// jira_ergebnis, was geschah. Einen Verweis zeigt die Oberfläche nur, wenn er auf <name>.atlassian.net/browse/<Schlüssel> zeigt und zum
// Schlüssel passt (lib/nachrichten.ts prüft die Nachrichten mit den Mustern hier).

export const JIRA_JOB = "jira";
export const JIRA_PROJEKTE_MAX = 20;

const PROJEKT = /^[A-Z][A-Z0-9_]{1,9}$/;
const SCHLUESSEL = /^[A-Z][A-Z0-9_]{1,9}-[1-9][0-9]{0,8}$/;
const LINK = /^https:\/\/[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net\/browse\/([A-Z][A-Z0-9_]{1,9}-[1-9][0-9]{0,8})$/;

/** Der Kern bietet Jira-Stories an: freigegebene Projekte und das Standardprojekt. */
export type JiraStatus = { projekte: string[]; standard: string };
/** Ergebnis vom Kern: angelegt (mit Schlüssel, Verweis nur geprüft) oder ein Satz, warum nicht. */
export type JiraErgebnis = { ok: boolean; text: string; schluessel?: string; link?: string };
/** Stand im Store: status null heißt kein Knopf; ergebnis bleibt stehen, bis die Person es schließt (key für die Darstellung). */
export type JiraStand = { status: JiraStatus | null; ergebnis: (JiraErgebnis & { key: number }) | null };
export const JIRA_LEER: JiraStand = { status: null, ergebnis: null };

export const projektOk = (p: string) => PROJEKT.test(p);
export const schluesselOk = (s: string) => SCHLUESSEL.test(s);
/** Nur ein Verweis auf genau diesen Schlüssel in Jira Cloud, sonst keiner (kein fremder Host, kein javascript:). */
export function linkOk(link: string, schluessel: string): boolean {
  const t = LINK.exec(link);
  return t !== null && t[1] === schluessel;
}
