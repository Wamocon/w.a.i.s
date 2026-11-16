import type { Betrieb, HausStimme, Modellzugang, SprachAnbieter } from "./nachrichten.ts";

/**
 * Hören und Stimme je Profil (Paket H5, voice-core/sprache_anbieter.py): Soniox (Standard) oder im Haus über das Gateway. Seit dem Wunsch
 * von Niko vom 16.11.2026 sind Spracherkennung und Sprachausgabe getrennt wählbar (die Datenbank kennt sie seit 0010 als zwei Spalten), dazu
 * die Stimme der Sprachausgabe im Haus (eine der neun Stimmen des Dienstes, Migration 0024). Erst wenn beides im Haus läuft, verlässt kein
 * Ton und kein Antworttext die Firma; das sagt der Satz darunter. Reine Funktionen, getestet in sprachwahl.test.ts.
 */

export const STIMMEN: readonly { id: SprachAnbieter; name: string }[] = [
  { id: "soniox", name: "Soniox (Standard)" },
  { id: "haus", name: "Im Haus (Datenschutz)" },
];

export type SprachBaustein = "stt" | "tts";
export const BAUSTEINE: readonly { id: SprachBaustein; name: string }[] = [
  { id: "stt", name: "Spracherkennung" },
  { id: "tts", name: "Sprachausgabe" },
];

export const STANDARD_STIMME = "standard";

/** Ein Satz ohne Punkt am Ende, damit er sich in einen Satz einfügen lässt. */
function ohnePunkt(text: string): string {
  return text.trim().replace(/[.\s]+$/, "");
}

/** Kennt der Kern die Wahl (neuer Kern meldet stimmeHaus) und ist der Stand lesbar? Sonst ist der Umschalter gesperrt. */
export function stimmeWaehlbar(z: Modellzugang | null): boolean {
  return z?.art !== undefined && z.stimmeHaus !== undefined && !!z.stt && !!z.tts;
}

/** Geht "Im Haus" in diesem Kern überhaupt (Modelle, Stimme und Gateway eingerichtet)? */
export function hausBereit(z: Modellzugang | null): boolean {
  return z?.stimmeHaus === "bereit";
}

/** Warum der Umschalter oder die Wahl "Im Haus" gerade gesperrt ist; null, wenn alles geht oder der Stand fehlt. */
export function sperrText(z: Modellzugang | null): string | null {
  if (z?.art === undefined) return null; // die Karte zeigt dann den Fehler des Stands
  if (!stimmeWaehlbar(z)) return "Dieser Kern kennt die Wahl noch nicht. Sie kommt mit der nächsten Version des Kerns.";
  if (!hausBereit(z)) return `Im Haus geht gerade nicht: ${ohnePunkt(z.stimmeHaus ?? "")}. Bis dahin gilt Soniox.`;
  return null;
}

export function stimmeName(wert: SprachAnbieter | undefined): string {
  return wert === "haus" ? "Im Haus" : wert === "soniox" ? "Soniox" : "unbekannt";
}

/** Was im Profil steht, je Baustein. Der Zwang des Admins auf Hausmodelle betrifft nur die Sprachmodelle, nicht Hören und Stimme. */
export function gewaehlt(z: Modellzugang | null, baustein: SprachBaustein): SprachAnbieter | null {
  return z?.[baustein] ?? null;
}

/** Was die Wahl eines Bausteins bedeutet, in einem Satz (Folgen laut Messung M7 vom 16.11.2026). */
export function bausteinErklaerung(baustein: SprachBaustein, wahl: SprachAnbieter | null): string {
  if (baustein === "stt") {
    return wahl === "haus"
      ? "Im Haus bleibt dein Gesprochenes in der Firma. Es gibt kein Live-Mitschreiben, der Text kommt nach dem Satzende etwas später."
      : "Soniox in der EU schreibt live mit und ist am schnellsten. Der Ton geht dafür an Soniox als Auftragsverarbeiter.";
  }
  return wahl === "haus"
    ? "Im Haus bleiben die Antworten in der Firma. Die Antwort kommt etwas später (rund 1,5 Sekunden je Satz), die Untertitel erscheinen satzweise."
    : "Soniox spricht sofort und flüssig. Der Antworttext geht dafür an Soniox als Auftragsverarbeiter.";
}

/** Gesamtsatz zum Datenschutz und zum Rückfall. */
export function datenschutzText(z: Modellzugang | null): string {
  const stt = gewaehlt(z, "stt");
  const tts = gewaehlt(z, "tts");
  if (stt === "haus" && tts === "haus") {
    return "Ton und Antworttext bleiben in der Firma. Geht es im Haus einmal nicht, läuft die Sitzung über Soniox, und hier steht warum.";
  }
  if (stt === "haus" || tts === "haus") {
    return "Erst wenn beides im Haus läuft, verlässt kein Ton und kein Antworttext die Firma.";
  }
  return "Soniox ist der Standard. Im Haus bleiben Ton und Text in der Firma, die Antwort kommt dann etwas später.";
}

/**
 * Satz unter dem Umschalter. Die Wahl gilt immer erst ab der nächsten Sitzung. Weicht die laufende Sitzung von der Wahl ab (Rückfall
 * auf Soniox oder Vorgabe des Betriebs für alle), nennt der Satz den Grund, den der Kern meldet (betrieb.spracheGrund).
 */
export function stimmeWirksamText(betrieb: Betrieb | null): string {
  if (betrieb?.spracheGrund) {
    return `Diese Sitzung weicht von der Wahl ab: ${ohnePunkt(betrieb.spracheGrund)}. Die Wahl gilt ab der nächsten Sitzung.`;
  }
  return "Die Wahl gilt ab der nächsten Sitzung.";
}

/** Auswahl der Stimme im Haus: zuerst der Standard des Kerns, dann die Stimmen, die der Kern meldet. Leer bei einem älteren Kern. */
export function stimmenAuswahl(z: Modellzugang | null): HausStimme[] {
  if (!z?.hausStimmen?.length) return [];
  const standard = z.hausStimmen.find((s) => s.id === z.hausStimmeStandard)?.name;
  return [{ id: STANDARD_STIMME, name: standard ? `Standard des Kerns (${standard})` : "Standard des Kerns" }, ...z.hausStimmen];
}

export function gewaehlteHausStimme(z: Modellzugang | null): string {
  return z?.hausStimme ?? STANDARD_STIMME;
}

/** Hinweis zur Stimme: immer, dass keine nativ deutsch ist, dazu die Messung zur gewählten Stimme (falls es eine gibt). */
export function stimmeHinweis(z: Modellzugang | null, id: string): string {
  const grund = z?.hausStimmenHinweis ?? "Keine der neun Stimmen ist nativ deutsch; sie sprechen Deutsch mit Akzent.";
  const stimme = z?.hausStimmen?.find((s) => s.id === (id === STANDARD_STIMME ? z?.hausStimmeStandard : id));
  const zusatz = stimme?.hinweis ? ` ${stimme.name}: ${ohnePunkt(stimme.hinweis)}.` : "";
  const nurHaus = z?.tts === "haus" ? "" : " Die Stimme gilt, sobald die Sprachausgabe im Haus läuft.";
  return `${grund}${zusatz}${nurHaus}`;
}
