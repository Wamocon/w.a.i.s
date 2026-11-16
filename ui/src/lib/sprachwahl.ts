import type { Betrieb, Modellzugang, SprachAnbieter } from "./nachrichten.ts";

/**
 * Hören und Stimme je Profil (Paket H5, voice-core/sprache_anbieter.py): Soniox (Standard) oder im Haus über das Gateway.
 * Eine Wahl für beides: Erst wenn Hören und Stimme im Haus laufen, verlässt kein Ton und kein Antworttext die Firma. Die
 * Schnittstelle des Kerns kennt beide Bausteine einzeln (ein Admin kann sie getrennt setzen); die Oberfläche zeigt einen solchen
 * Stand als "gemischt" und stellt mit der nächsten Wahl beides gleich. Reine Funktionen, getestet in sprachwahl.test.ts.
 */

export const STIMMEN: readonly { id: SprachAnbieter; name: string }[] = [
  { id: "soniox", name: "Soniox (Standard)" },
  { id: "haus", name: "Im Haus (Datenschutz)" },
];

/** Gewählter Stand im Profil: beide gleich, gemischt (nur über den Admin möglich) oder unbekannt (null). */
export type StimmStand = SprachAnbieter | "gemischt" | null;

/** Ein Satz ohne Punkt am Ende, damit er sich in einen Satz einfügen lässt. */
function ohnePunkt(text: string): string {
  return text.trim().replace(/[.\s]+$/, "");
}

/** Kennt der Kern die Wahl (neuer Kern meldet stimmeHaus) und ist der Stand lesbar? Sonst ist der Umschalter gesperrt. */
export function stimmeWaehlbar(z: Modellzugang | null): boolean {
  return z?.art !== undefined && z.stimmeHaus !== undefined && gewaehlteStimme(z) !== null;
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

/** Was im Profil steht. Der Zwang des Admins auf Hausmodelle betrifft nur die Sprachmodelle, nicht Hören und Stimme. */
export function gewaehlteStimme(z: Modellzugang | null): StimmStand {
  if (!z?.stt || !z.tts) return null;
  return z.stt === z.tts ? z.stt : "gemischt";
}

/** Was die Wahl bedeutet, in einem Satz für die Person (Folgen laut Messung M7 vom 16.11.2026). */
export function stimmeErklaerung(wahl: StimmStand): string {
  if (wahl === "haus") {
    return (
      "Im Haus bleiben dein Gesprochenes und die Antworten in der Firma. Dafür gibt es kein Live-Mitschreiben, die Antwort " +
      "kommt etwas später (rund 1,5 Sekunden je Satz) und die Untertitel erscheinen satzweise. Geht es im Haus einmal nicht, " +
      "läuft die Sitzung über Soniox, und hier steht warum."
    );
  }
  if (wahl === "soniox") {
    return "Soniox in der EU schreibt live mit und antwortet am schnellsten. Ton und Text gehen dafür an Soniox als Auftragsverarbeiter.";
  }
  return "Soniox ist der Standard. Im Haus bleiben Ton und Text in der Firma, die Antwort kommt dann etwas später.";
}

/**
 * Satz unter dem Umschalter. Die Wahl gilt immer erst ab der nächsten Sitzung. Weicht die laufende Sitzung von der Wahl ab (Rückfall
 * auf Soniox oder Vorgabe des Betriebs für alle), nennt der Satz den Grund, den der Kern meldet (betrieb.spracheGrund).
 */
export function stimmeWirksamText(z: Modellzugang | null, betrieb: Betrieb | null): string {
  if (gewaehlteStimme(z) === "gemischt") {
    return `Vom Admin gesetzt: Hören ${stimmeName(z?.stt)}, Stimme ${stimmeName(z?.tts)}. Eine Wahl hier stellt beides gleich.`;
  }
  if (betrieb?.spracheGrund) {
    return `Diese Sitzung weicht von der Wahl ab: ${ohnePunkt(betrieb.spracheGrund)}. Die Wahl gilt ab der nächsten Sitzung.`;
  }
  return "Die Wahl gilt ab der nächsten Sitzung.";
}
