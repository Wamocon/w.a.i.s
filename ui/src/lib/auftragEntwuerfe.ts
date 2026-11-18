// Gespeicherte Entwicklungsaufträge (voice-core/auftrag_entwuerfe.py): Zustand der Liste im Reiter "Aufträge" und was eine Antwort des Kerns
// daran ändert. Reine Funktionen ohne Uhr und ohne React; useWamo sendet, lib/wamo.ts übernimmt die Antworten.
//
// Ablauf: Mit einer Sitzung, die Entwicklungsaufträge hat (betrieb.entwicklung "an"), fragt die Oberfläche einmal je Verbindung die Liste ab.
// Erst mit der ersten gelungenen Antwort gibt es den Zustand (sonst bleibt er null, und Knopf und Liste fehlen). Speichern nimmt die Karte erst
// mit der Antwort ok aus der Ansicht; Laden legt der Kern als neue Karte an (Servernachricht auftrag), gestartet wird sie wie jede andere per
// Klick.
import type { Auftrag, AuftragEntwurf, EntwurfAktion, ServerMessage } from "./nachrichten.ts";

/** So lange sperrt eine gesendete Aktion die Knöpfe höchstens, wenn keine Antwort kommt (danach ein Hinweis). */
export const ENTWURF_WARTEN_MS = 15_000;
/** Aufbewahrung im Kern (Migration 0026): danach verschwindet ein gespeicherter Auftrag. */
export const ENTWURF_AUFBEWAHRUNG_TAGE = 90;

export type EntwurfAntwort = Extract<ServerMessage, { type: "auftrag_entwuerfe" }>;

/** Letzte Rückmeldung einer Aktion; n zählt, damit die Anzeige jede neue Meldung als neu erkennt. */
export type EntwurfMeldung = { n: number; ok: boolean; aktion: EntwurfAktion; text: string };

/** Eine gesendete Aktion ohne Antwort: welche, für welche Karte oder welchen Entwurf, und ihre Nummer (für die Frist in lib/wamo.ts). */
export type EntwurfWarten = { aktion: Exclude<EntwurfAktion, "liste">; kennung: string; n: number };

export type EntwuerfeStand = {
  liste: AuftragEntwurf[];
  max: number;
  meldung: EntwurfMeldung | null;
  /** solange gesetzt, sind die Knöpfe gesperrt */
  wartet: EntwurfWarten | null;
};

export const ENTWUERFE_LEER: EntwuerfeStand = { liste: [], max: 50, meldung: null, wartet: null };

/** Beendet diese Antwort das Warten? Nur die Antwort auf dieselbe Aktion (beim Speichern auf dieselbe Karte); eine Meldung, die der Kern
 *  von sich aus schickt (Speichern per Sprache), lässt eine gesendete Aktion weiter warten. */
function beendetWarten(w: EntwurfWarten | null, msg: EntwurfAntwort): boolean {
  if (w === null || w.aktion !== msg.aktion) return false;
  return w.aktion !== "speichern" || msg.job === undefined || msg.job === w.kennung;
}

/** Antwort des Kerns einarbeiten: Liste und Grenze, wenn mitgeschickt, sonst die bisherigen. Eine gescheiterte Liste ohne bisherigen Zustand
 *  legt keinen an (dann gibt es in dieser Sitzung keine gespeicherten Aufträge). Eine gelungene Liste und ein Erfolg ohne Text sind keine
 *  Meldung. */
export function entwuerfeNachAntwort(stand: EntwuerfeStand | null, msg: EntwurfAntwort): EntwuerfeStand | null {
  if (stand === null && msg.aktion === "liste" && !msg.ok) return null;
  const alt = stand ?? ENTWUERFE_LEER;
  const still = (msg.aktion === "liste" && msg.ok) || (msg.ok && !msg.text);
  return {
    liste: msg.entwuerfe ?? alt.liste,
    max: msg.max ?? alt.max,
    meldung: still ? alt.meldung : { n: (alt.meldung?.n ?? 0) + 1, ok: msg.ok, aktion: msg.aktion, text: msg.text },
    wartet: beendetWarten(alt.wartet, msg) ? null : alt.wartet,
  };
}

/** Nach einem gelungenen Speichern verlässt die Karte die Sitzung (der Kern hat sie schon entfernt). Sonst dieselbe Liste. */
export function auftraegeNachEntwurf(auftraege: Auftrag[], msg: EntwurfAntwort): Auftrag[] {
  if (msg.aktion !== "speichern" || !msg.ok || !msg.job) return auftraege;
  const neu = auftraege.filter((a) => a.job !== msg.job);
  return neu.length === auftraege.length ? auftraege : neu;
}

/** Text für role="status" nach einer Antwort; eine stille Antwort (Liste, Erfolg ohne Text) sagt nichts an (null). */
export function entwurfAnsage(msg: EntwurfAntwort): string | null {
  if ((msg.aktion === "liste" && msg.ok) || (msg.ok && !msg.text)) return null;
  return msg.ok ? msg.text : `Gespeicherte Aufträge: ${msg.text}`;
}

/** Darf diese Karte gespeichert werden? Nur solange sie nicht gesendet ist (nicht wartend, nicht ohne Quittung). */
export function speichernMoeglich(a: Pick<Auftrag, "stand">): boolean {
  return a.stand?.phase !== "wartet" && a.stand?.phase !== "ohneQuittung";
}

function zeitpunkt(ms: number): Date | null {
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Datum eines gespeicherten Auftrags, deutsch und kurz (18.11.2026); ohne gültigen Zeitpunkt leer. */
export function entwurfDatum(ms: number): string {
  const d = zeitpunkt(ms);
  return d ? d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Berlin" }) : "";
}

/** Derselbe Zeitpunkt für das Attribut dateTime; ohne gültigen Zeitpunkt leer (toISOString wirft sonst). */
export function entwurfIso(ms: number): string {
  return zeitpunkt(ms)?.toISOString() ?? "";
}
