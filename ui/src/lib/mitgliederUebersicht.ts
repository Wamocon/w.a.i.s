/**
 * Reine Logik der Admin-Übersicht "Neue Mitglieder" (Kern: voice-core/mitglieder_admin_api.py, Migration 0022). Ohne React und ohne
 * Browser, prüfbar mit node:test (mitgliederUebersicht.test.ts). Die Antwort des Kerns wird streng gelesen: nur bekannte Felder und
 * Werte, Unbekanntes wird null, eine Zeile ohne Kennung fällt weg. Je Person entsteht eine Schrittliste in der Reihenfolge des
 * Ablaufs (docs/ausrollen-neue-nutzer.md, Abschnitt 3) und ein Satz, was als Nächstes fehlt.
 */

export type GeraetStand = "aktiv" | "beantragt" | "gesperrt" | "widerrufen" | "keins";
export type Modellzugang = "token_und_schluessel" | "token" | "schluessel" | "haus";

export type Mitglied = {
  userId: string;
  name: string;
  rolle: "admin" | "mitglied" | null;
  aktiv: boolean;
  angelegt: string | null;
  letzteAnmeldung: string | null;
  faktor: boolean;
  passwort: string | null;
  geraet: GeraetStand | null;
  modellzugang: Modellzugang | null;
  stimmabdruck: boolean;
};

export type SchrittId = "anmeldung" | "faktor" | "passwort" | "geraet" | "stimme";
export type Schritt = { id: SchrittId; titel: string; erledigt: boolean | null };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const GERAETE: readonly GeraetStand[] = ["aktiv", "beantragt", "gesperrt", "widerrufen", "keins"];
const ZUGAENGE: readonly Modellzugang[] = ["token_und_schluessel", "token", "schluessel", "haus"];
const PASSWORT_STAENDE = ["keine", "offen", "abgelaufen", "erledigt"] as const;
const PASSWORT_ERLEDIGT: readonly string[] = ["erledigt", "keine"];
const NAME_MAX = 60;

const istObjekt = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const aus = <T extends string>(v: unknown, erlaubt: readonly T[]): T | null =>
  typeof v === "string" && (erlaubt as readonly string[]).includes(v) ? (v as T) : null;
const DATUM_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const zeit = (v: unknown): string | null => (typeof v === "string" && DATUM_RE.test(v) ? v : null);

function name(v: unknown): string {
  if (typeof v !== "string") return "";
  return v.slice(0, 4 * NAME_MAX).replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, "").slice(0, NAME_MAX);
}

/** Eine Zeile des Kerns lesen; ohne gültige Kennung null. */
export function pruefeMitglied(v: unknown): Mitglied | null {
  if (!istObjekt(v) || typeof v.user_id !== "string" || !UUID_RE.test(v.user_id)) return null;
  return {
    userId: v.user_id,
    name: name(v.anzeigename),
    rolle: aus(v.rolle, ["admin", "mitglied"] as const),
    aktiv: v.aktiv === true,
    angelegt: zeit(v.angelegt),
    letzteAnmeldung: zeit(v.letzte_anmeldung),
    faktor: v.faktor_bestaetigt === true,
    passwort: aus(v.passwort_stand, PASSWORT_STAENDE),
    geraet: aus(v.geraet_stand, GERAETE),
    modellzugang: aus(v.modellzugang, ZUGAENGE),
    stimmabdruck: v.stimmabdruck === true,
  };
}

/** Die Antwort { mitglieder: [...] } lesen; null, wenn die Form nicht stimmt. */
export function pruefeListe(v: unknown): Mitglied[] | null {
  if (!istObjekt(v) || !Array.isArray(v.mitglieder)) return null;
  return v.mitglieder.slice(0, 200).map(pruefeMitglied).filter((m): m is Mitglied => m !== null);
}

/** Schritte in der Reihenfolge des Ablaufs; erledigt null heißt: lässt sich noch nicht sagen (Passwort vor Paket P1a). */
export function schritte(m: Mitglied): Schritt[] {
  return [
    { id: "anmeldung", titel: "Angemeldet", erledigt: m.letzteAnmeldung !== null },
    { id: "faktor", titel: "Zweiter Faktor", erledigt: m.faktor },
    { id: "passwort", titel: "Passwort gewechselt", erledigt: m.passwort === null ? null : PASSWORT_ERLEDIGT.includes(m.passwort) },
    { id: "geraet", titel: "Laptop eingerichtet", erledigt: m.geraet === "aktiv" },
    { id: "stimme", titel: "Stimmabdruck", erledigt: m.stimmabdruck },
  ];
}

const MODELL_TEXT: Record<Modellzugang, string> = {
  token_und_schluessel: "eigener Token und API-Schlüssel",
  token: "eigener Claude-Code-Token, Gespräch über Hausmodelle",
  schluessel: "eigener API-Schlüssel",
  haus: "Hausmodelle",
};

export const modellText = (m: Mitglied): string => (m.modellzugang ? MODELL_TEXT[m.modellzugang] : "unbekannt");

/** Ein Satz: was als Nächstes fehlt, oder dass alles steht. */
export function naechsterSchritt(m: Mitglied): string {
  if (!m.aktiv) return "Profil gesperrt. Erst nach der persönlichen Übergabe freischalten.";
  if (m.letzteAnmeldung === null) return "Noch nie angemeldet.";
  if (!m.faktor) return "Der zweite Faktor fehlt noch.";
  if (m.passwort !== null && !PASSWORT_ERLEDIGT.includes(m.passwort)) return "Das Startpasswort ist noch nicht gewechselt.";
  if (m.geraet === "beantragt") return "Der Laptop wartet auf deine Freigabe (Geräte und PC).";
  if (m.geraet !== "aktiv") return "Der Laptop ist noch nicht eingerichtet.";
  if (!m.stimmabdruck) return "Alles Wichtige steht, der Stimmabdruck fehlt noch.";
  return "Fertig eingerichtet.";
}

/** Kopfzeile: wie viele Personen fertig sind. */
export function zusammenfassung(liste: readonly Mitglied[]): string {
  if (liste.length === 0) return "Keine Profile.";
  const fertig = liste.filter((m) => naechsterSchritt(m) === "Fertig eingerichtet.").length;
  return `${fertig} von ${liste.length} Profilen fertig eingerichtet.`;
}

/** Datum kurz auf Deutsch (TT.MM.JJJJ), ohne Datum "nie". */
export function datumKurz(iso: string | null): string {
  const t = iso ? DATUM_RE.exec(iso) : null;
  return t ? `${t[3]}.${t[2]}.${t[1]}` : "nie";
}
