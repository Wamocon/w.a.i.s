import type { CanvasItem } from "@/components/Canvas";

/**
 * Teams-Nachricht am PC aus dem Canvas (voice-core/teams_werkzeuge.py, host/office_teams.py): das Formular "Als Teams-Nachricht" und
 * die Prüfung vor dem Senden an den Kern. Freigegeben wird hier nie etwas: Kern und Host bauen die Karte mit genau dem Inhalt des Links,
 * erst der Klick auf "Freigeben" öffnet Teams mit dem Text im Eingabefeld, und senden muss die Person dort selbst mit Enter. Die Grenzen
 * sind die des Hosts; er prüft trotzdem selbst (auch die Länge des ganzen Links, in der Umlaute mehrfach zählen).
 */
export const TEAMS_EMPFAENGER_MAX = 10;
export const TEAMS_TEXT_MAX = 1000;
export const TEAMS_GRUPPE_MAX = 100;

/** Was das Formular an den Kern schickt (Nachricht teams_vorbereiten). */
export type TeamsDaten = { an: string[]; gruppenname: string; text: string };

/** Was die Oberfläche auslösen kann (useWamo); true, wenn die Nachricht an den Kern gesendet wurde. */
export type TeamsAktionen = { vorbereiten: (daten: TeamsDaten) => boolean };

/** Ein Satz, was am Formular fehlt, oder null. Zu lang heißt Hinweis mit der Zahl, nie ein still gekürzter Text. */
export function teamsFehler(d: TeamsDaten): string | null {
  if (!d.an.length) return "Mindestens ein Empfänger fehlt.";
  if (d.an.length > TEAMS_EMPFAENGER_MAX) return `Höchstens ${TEAMS_EMPFAENGER_MAX} Empfänger je Teams-Chat.`;
  if (!d.text.trim()) return "Der Text fehlt.";
  if (d.text.length > TEAMS_TEXT_MAX) {
    return `Der Text hat ${d.text.length} Zeichen, für Teams gehen höchstens ${TEAMS_TEXT_MAX}. Bitte kürzen oder als Mail schicken.`;
  }
  const gruppe = d.gruppenname.trim();
  if (gruppe && d.an.length < 2) return "Einen Gruppennamen gibt es nur bei mindestens zwei Empfängern.";
  if (gruppe.length > TEAMS_GRUPPE_MAX) return `Der Gruppenname ist länger als ${TEAMS_GRUPPE_MAX} Zeichen.`;
  return null;
}

const UEBERSCHRIFT = /^\s{0,3}#{1,6}\s+/;
const LINK = /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g;

function markdownZeile(zeile: string): string {
  return zeile.replace(UEBERSCHRIFT, "").replace(LINK, "$1 ($2)").replaceAll("**", "").replaceAll("__", "").replaceAll("`", "");
}

/** Canvas-Inhalt als Klartext (wie voice-core/teams_werkzeuge.klartext): Dokumente ohne Markdown-Zeichen, Tabellen als Zeilen mit " | ",
 * Code und Diagramme wie sie sind. Nur ein Vorschlag fürs Formular, die Person kann ihn ändern. */
export function klartext(item: CanvasItem): string {
  if (item.kind === "tabelle") {
    return [item.title, ...[item.columns, ...item.rows].map((z) => z.join(" | "))].join("\n").trim();
  }
  if (item.kind !== "dokument") return item.text;
  return item.text
    .split("\n")
    .filter((z) => !z.trim().startsWith("```"))
    .map(markdownZeile)
    .join("\n")
    .trim();
}
