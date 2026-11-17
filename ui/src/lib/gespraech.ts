/**
 * Zeilen für den Block "Gespräch" in der linken Spalte (components/kommando/Gespraech.tsx): die letzte Zeile der Person
 * und die letzte Zeile von WAMO. Zuerst gilt der laufende Zug (Untertitel), danach der letzte Eintrag im Verlauf, damit
 * die Zeilen nach dem Zugende stehen bleiben. Reine Funktionen, deshalb ohne Browser prüfbar (gespraech.test.ts).
 * Importe relativ mit Endung, damit node:test diese Datei laden kann.
 */
import { sichtbarerNutzerText } from "./stimmFilter.ts";
import { gesprochen, type Caption, type LogEintrag } from "./wamo.ts";

type Verlauf = readonly Pick<LogEintrag, "wer" | "text">[];

function letzter(log: Verlauf, wer: LogEintrag["wer"]): string {
  for (let i = log.length - 1; i >= 0; i--) if (log[i].wer === wer) return log[i].text.trim();
  return "";
}

/**
 * Letzte Zeile der Person: der laufende Beitrag (fertige und vorläufige Teile), sonst der letzte aus dem Verlauf. Mit Stimmfilter
 * (lib/stimmFilter.ts) zählt vom laufenden Beitrag nur, was die Stimmprüfung freigegeben hat, ohne Zwischenstand.
 */
export function menschZeile(
  c: Pick<Caption, "userDone" | "userLive"> & Partial<Pick<Caption, "userTeile" | "gefiltert">>,
  log: Verlauf,
): string {
  return sichtbarerNutzerText(c) || letzter(log, "nutzer");
}

/** Letzte Zeile von WAMO: der laufende Zug (nach einer Unterbrechung nur das Gesprochene), sonst die letzte Antwort aus dem Verlauf. */
export function wamoZeile(c: Pick<Caption, "text" | "spoken" | "interrupted">, log: Verlauf): string {
  const jetzt = c.interrupted ? gesprochen(c) : c.text.trim();
  return jetzt || letzter(log, "wamo");
}
