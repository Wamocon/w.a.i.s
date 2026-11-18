/**
 * Mikrofontest (Wunsch vom 18.11.2026: "Können wir irgendwie die Stärke meines Mikrofons messen?"). Hintergrund: Die Stimmprüfung hielt den
 * Besitzer oft für fremd, Hauptursache war ein anderes Mikrofon als beim Einlernen, das deutlich leiser war (Pegelspitze im Median -27 statt
 * -8 dBFS). Der Test zeigt in den Einstellungen (Sprache und Ton, Block Eingabe), wie gut das gewählte Mikrofon die Stimme liefert.
 *
 * Ablauf: kurz einschwingen (EINSCHWING_MS, das Mikrofon öffnet sich, die Verstärkung des Browsers stellt sich ein), bis RUHE_MS still sein,
 * dann SPRECHEN_MS sprechen. Gemessen wird im Browser mit einem AnalyserNode in Fenstern von 2048 Abtastwerten im Takt TAKT_MS (RMS und
 * Spitze je Fenster, lib/mikrofon.ts messen), mit denselben Einstellungen wie im Gespräch (getUserMedia ohne eigene Vorgaben: Echo- und
 * Rauschunterdrückung und automatische Verstärkung wie beim Sprechen mit W.A.I.S.). Kein Ton verlässt den Browser, nichts wird aufgenommen.
 * Gespeichert wird nur das letzte Ergebnis je Person und Gerät im Speicher des Browsers oder der App (TEST_SCHLUESSEL, mit try/catch).
 *
 * Auswertung:
 * - Grundrauschen: Median des RMS in der Ruhe.
 * - Sprachpegel: 90-%-Quantil des RMS beim Sprechen, also die lauten Silben (Pausen zwischen Wörtern zählen so nicht mit).
 * - Abstand: Sprachpegel minus Grundrauschen (Signal-Rausch-Abstand in dB).
 * - Übersteuerung: Anteil der Fenster beim Sprechen mit einer Spitze ab UEBERSTEUERT_DBFS.
 *
 * Schwellen und ihre Gründe (dBFS, Fenster von rund 43 ms):
 * - ZU_LEISE_DBFS -40 (rot): nur 5 dB über der Grenze, ab der das Einlernen einen 20-ms-Block als Sprache zählt (-45 dBFS,
 *   voice-core/stimme_modell.py), leise Silben fallen schon darunter.
 * - LEISE_DBFS -30 (gelb): unter dem Bereich, in dem Sprache mit der Verstärkung des Browsers an einem passenden Mikrofon liegt (-26 bis
 *   -16 dBFS, lib/pegelWarnung.ts). Das eingebaute Mikrofon aus dem Befund (Spitzen um -27 dBFS, RMS rund 10 dB darunter) landet hier.
 * - ZU_LAUT_DBFS -6 (gelb): kaum Luft bis zur Übersteuerung.
 * - UEBERSTEUERT_DBFS -1 in mehr als UEBERSTEUERT_ANTEIL (2 %) der Fenster (rot): die Stimme stößt an die Grenze und klingt verzerrt; ein
 *   einzelnes Klopfen zählt so nicht.
 * - Abstand unter ABSTAND_KNAPP_DB 20 dB gelb, unter ABSTAND_SCHLECHT_DB 10 dB rot: Im Versuch mit Rauschen 15 dB unter der Sprache sanken die
 *   eigenen Werte der Stimmprüfung im Mittel um 0,08 (README, Abschnitt Stimmabdruck); unter 10 dB trennt die Prüfung kaum noch.
 *
 * Reine Logik ohne Browser (Tests: mikrofonTest.test.ts); Mikrofon und Takt liegen in components/einstellungen/MikrofonTest.tsx.
 */
import { geraeteName, STILLE_DBFS } from "./mikrofon.ts";

export const EINSCHWING_MS = 500;
export const RUHE_MS = 3000;
export const SPRECHEN_MS = 5000;
export const TAKT_MS = 50;
/** So viele Fenster braucht jede Phase mindestens (ein stark gedrosselter Tab liefert weniger), sonst gibt es kein Ergebnis. */
export const MIN_FENSTER = 10;

export const ZU_LEISE_DBFS = -40;
export const LEISE_DBFS = -30;
export const ZU_LAUT_DBFS = -6;
export const UEBERSTEUERT_DBFS = -1;
export const UEBERSTEUERT_ANTEIL = 0.02;
export const ABSTAND_KNAPP_DB = 20;
export const ABSTAND_SCHLECHT_DB = 10;
/** Boden für dBFS: Stille und unbrauchbare Werte */
const BODEN_DB = -120;

export const TEST_PRAEFIX = "wamo.mikrofontest.";
/** So viele Geräte merkt sich der Speicher je Person, das am längsten nicht getestete fällt heraus. */
export const TEST_MAX_GERAETE = 8;

export type TestPhase = "einschwingen" | "ruhe" | "sprechen" | "fertig";

/** Phase nach so vielen Millisekunden seit dem Start. */
export function phaseBei(ms: number): TestPhase {
  if (ms < EINSCHWING_MS) return "einschwingen";
  if (ms < RUHE_MS) return "ruhe";
  if (ms < RUHE_MS + SPRECHEN_MS) return "sprechen";
  return "fertig";
}

/** Linearer Wert (0 bis 1) in dBFS, nie unter BODEN_DB. */
export function db(wert: number): number {
  return Number.isFinite(wert) && wert > 0 ? Math.max(BODEN_DB, 20 * Math.log10(wert)) : BODEN_DB;
}

export type Messung = {
  /** RMS in dBFS je Fenster */
  ruhe: number[];
  sprechen: number[];
  /** Spitze in dBFS je Fenster */
  spitzenRuhe: number[];
  spitzenSprechen: number[];
};

export const neueMessung = (): Messung => ({ ruhe: [], sprechen: [], spitzenRuhe: [], spitzenSprechen: [] });

/** Ein Fenster aufnehmen (rms linear, spitzeDb aus messen). Unbrauchbare Werte zählen nicht. */
export function fensterAufnehmen(m: Messung, phase: "ruhe" | "sprechen", f: { rms: number; spitzeDb: number }): void {
  if (!Number.isFinite(f.rms) || f.rms < 0 || Number.isNaN(f.spitzeDb)) return;
  const spitze = Number.isFinite(f.spitzeDb) ? Math.max(BODEN_DB, Math.min(0, f.spitzeDb)) : BODEN_DB;
  if (phase === "ruhe") {
    m.ruhe.push(db(f.rms));
    m.spitzenRuhe.push(spitze);
  } else {
    m.sprechen.push(db(f.rms));
    m.spitzenSprechen.push(spitze);
  }
}

export type Bewertung = "gut" | "leise" | "zu_leise" | "zu_laut" | "uebersteuert" | "hintergrund" | "viel_hintergrund" | "kein_ton";
export type Ampel = "gruen" | "gelb" | "rot";

const AMPEL: Record<Bewertung, Ampel> = {
  gut: "gruen",
  leise: "gelb",
  zu_laut: "gelb",
  hintergrund: "gelb",
  zu_leise: "rot",
  uebersteuert: "rot",
  viel_hintergrund: "rot",
  kein_ton: "rot",
};

/** Ein Satz je Ergebnis: was los ist und was hilft. */
export const SATZ: Record<Bewertung, string> = {
  gut: "Gut: W.A.I.S. hört dich laut und deutlich.",
  leise: "Etwas leise: Es geht, aber mit mehr Pegel erkennt W.A.I.S. deine Stimme sicherer, sprich näher am Mikrofon.",
  zu_leise: "Zu leise: W.A.I.S. hört dich kaum, sprich näher am Mikrofon oder wähle ein anderes Gerät.",
  zu_laut: "Sehr laut: Bis zur Übersteuerung bleibt wenig Luft, sprich etwas weiter weg vom Mikrofon.",
  uebersteuert: "Übersteuert: Deine Stimme stößt an die Grenze und klingt verzerrt, sprich weiter weg oder senke den Eingangspegel in Windows.",
  hintergrund: "Etwas Hintergrund: Geräusche im Raum sind gut hörbar, für die Stimmerkennung ist ein ruhigerer Platz besser.",
  viel_hintergrund: "Zu viel Hintergrund: Die Geräusche im Raum sind fast so laut wie deine Stimme, such einen ruhigeren Platz oder nimm ein Headset.",
  kein_ton: "Kein Ton: Das Mikrofon liefert nur Stille, prüfe die Stummschaltung am Gerät oder wähle ein anderes Mikrofon.",
};

export const AMPEL_TEXT: Record<Ampel, string> = { gruen: "Grün", gelb: "Gelb", rot: "Rot" };

export type Ergebnis = {
  /** Name des Mikrofons, wie die Spur ihn nennt */
  geraet: string;
  /** Zeitpunkt (Date.now) */
  zeit: number;
  rauschenDb: number;
  spracheDb: number;
  abstandDb: number;
  spitzeDb: number;
  /** Anteil der Fenster beim Sprechen an der Grenze, 0 bis 1 */
  uebersteuert: number;
  bewertung: Bewertung;
  ampel: Ampel;
  satz: string;
};

function quantil(werte: readonly number[], q: number): number {
  const s = [...werte].sort((a, b) => a - b);
  const i = Math.min(s.length - 1, Math.max(0, Math.ceil(q * s.length) - 1));
  return s[i];
}

function bewerten(e: { spracheDb: number; abstandDb: number; spitzeMax: number; uebersteuert: number }): Bewertung {
  if (e.spitzeMax <= STILLE_DBFS) return "kein_ton";
  if (e.uebersteuert > UEBERSTEUERT_ANTEIL) return "uebersteuert";
  if (e.spracheDb < ZU_LEISE_DBFS) return "zu_leise";
  if (e.abstandDb < ABSTAND_SCHLECHT_DB) return "viel_hintergrund";
  if (e.spracheDb < LEISE_DBFS) return "leise";
  if (e.spracheDb > ZU_LAUT_DBFS) return "zu_laut";
  if (e.abstandDb < ABSTAND_KNAPP_DB) return "hintergrund";
  return "gut";
}

/** Ergebnis der Messung, null, wenn eine Phase zu wenige Fenster hat. */
export function auswerten(m: Messung, geraet: string | null, zeit: number): Ergebnis | null {
  if (m.ruhe.length < MIN_FENSTER || m.sprechen.length < MIN_FENSTER) return null;
  const rauschenDb = quantil(m.ruhe, 0.5);
  const spracheDb = quantil(m.sprechen, 0.9);
  const abstandDb = spracheDb - rauschenDb;
  const spitzeDb = Math.max(...m.spitzenSprechen);
  const spitzeMax = Math.max(spitzeDb, ...m.spitzenRuhe);
  const uebersteuert = m.spitzenSprechen.filter((s) => s >= UEBERSTEUERT_DBFS).length / m.spitzenSprechen.length;
  const bewertung = bewerten({ spracheDb, abstandDb, spitzeMax, uebersteuert });
  return {
    geraet: (geraet ?? "").trim().slice(0, 120) || "unbekanntes Mikrofon",
    zeit,
    rauschenDb,
    spracheDb,
    abstandDb,
    spitzeDb,
    uebersteuert,
    bewertung,
    ampel: AMPEL[bewertung],
    satz: SATZ[bewertung],
  };
}

/** Das Mikrofon ließ sich für den Test nicht öffnen (Name des Fehlers wie lib/mikrofon.ts fehlerName): Satz mit Abhilfe. */
export function testFehlerText(name?: string): string {
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return (
        "Mikrofon gesperrt: Erlaube das Mikrofon für diese Seite (im Browser über das Symbol links neben der Adresse, in Windows unter " +
        "Einstellungen > Datenschutz und Sicherheit > Mikrofon) und teste noch einmal."
      );
    case "NotFoundError":
    case "OverconstrainedError":
      return "Dieses Mikrofon ist nicht zu finden. Schließe es an oder wähle oben ein anderes und teste noch einmal.";
    case "NotReadableError":
    case "AbortError":
      return (
        "Das Mikrofon lässt sich nicht öffnen, vermutlich nutzt ein anderes Programm es gerade exklusiv. Schließe Programme wie Teams " +
        "oder Zoom und teste noch einmal."
      );
    case "MessungAngehalten":
      return "Der Browser hat die Messung nicht gestartet. Klicke noch einmal auf „Mikrofon testen“.";
    default:
      return "Das Mikrofon lässt sich nicht öffnen. Prüfe in Windows unter Einstellungen > System > Sound > Eingabe das Gerät und teste noch einmal.";
  }
}

/** dB mit einer Nachkommastelle und deutschem Komma, zum Beispiel "-20,3". */
export const dbText = (wert: number): string => (Math.round(wert * 10) / 10).toFixed(1).replace(".", ",").replace("-", "−");

// ---------- Speicher: das letzte Ergebnis je Person und Gerät ----------

type Lesen = { getItem(k: string): string | null };
type Schreiben = { setItem(k: string, v: string): void };

function testSchluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${TEST_PRAEFIX}${userId}`;
}

const zahl = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;

/** Ein gespeichertes Ergebnis prüfen; Ampel und Satz kommen aus der Bewertung, nie aus dem Speicher. */
function ergebnisPruefen(roh: unknown): Ergebnis | null {
  if (typeof roh !== "object" || roh === null) return null;
  const e = roh as Record<string, unknown>;
  const bewertung = e.bewertung;
  if (typeof bewertung !== "string" || !Object.prototype.hasOwnProperty.call(AMPEL, bewertung)) return null;
  const b = bewertung as Bewertung;
  if (typeof e.geraet !== "string" || !e.geraet || e.geraet.length > 120 || !zahl(e.zeit, 0, Number.MAX_SAFE_INTEGER)) return null;
  for (const feld of ["rauschenDb", "spracheDb", "spitzeDb"]) if (!zahl(e[feld], BODEN_DB, 0)) return null;
  if (!zahl(e.abstandDb, BODEN_DB, -BODEN_DB) || !zahl(e.uebersteuert, 0, 1)) return null;
  return {
    geraet: e.geraet,
    zeit: e.zeit as number,
    rauschenDb: e.rauschenDb as number,
    spracheDb: e.spracheDb as number,
    abstandDb: e.abstandDb as number,
    spitzeDb: e.spitzeDb as number,
    uebersteuert: e.uebersteuert as number,
    bewertung: b,
    ampel: AMPEL[b],
    satz: SATZ[b],
  };
}

/** Alle gemerkten Ergebnisse einer Person als Map (kein Objekt: ein Gerät namens "constructor" oder "__proto__" bleibt ein Name). */
function alleLesen(speicher: Lesen, k: string): Map<string, Ergebnis> {
  const roh: unknown = JSON.parse(speicher.getItem(k) ?? "{}");
  const aus = new Map<string, Ergebnis>();
  if (typeof roh !== "object" || roh === null || Array.isArray(roh)) return aus;
  for (const [name, wert] of Object.entries(roh as Record<string, unknown>)) {
    const e = ergebnisPruefen(wert);
    if (e) aus.set(name, e);
  }
  return aus;
}

const geraeteSchluessel = (label: string | null | undefined): string | null => geraeteName(label)?.toLowerCase() ?? null;

/** Letztes Ergebnis dieser Person mit diesem Mikrofon, null ohne Ergebnis, ohne Person oder bei einem Lesefehler. */
export function ergebnisLesen(speicher: Lesen | null | undefined, userId: string | null | undefined, geraet: string | null | undefined): Ergebnis | null {
  const k = testSchluessel(userId);
  const g = geraeteSchluessel(geraet);
  if (!k || !g || !speicher) return null;
  try {
    return alleLesen(speicher, k).get(g) ?? null;
  } catch {
    return null;
  }
}

/** Ergebnis merken (höchstens TEST_MAX_GERAETE Geräte je Person). true, wenn der Speicher es angenommen hat. */
export function ergebnisMerken(speicher: (Lesen & Schreiben) | null | undefined, userId: string | null | undefined, e: Ergebnis): boolean {
  const k = testSchluessel(userId);
  const g = geraeteSchluessel(e.geraet);
  if (!k || !g || !speicher) return false;
  try {
    let alle = new Map<string, Ergebnis>();
    try {
      alle = alleLesen(speicher, k);
    } catch {
      // kaputter Eintrag: neu anfangen
    }
    alle.set(g, e);
    const behalten = [...alle.entries()].sort(([, a], [, b]) => b.zeit - a.zeit).slice(0, TEST_MAX_GERAETE);
    // als Liste von Paaren in ein Objekt ohne Prototyp, damit auch "__proto__" als Name erhalten bleibt
    const aus: Record<string, Ergebnis> = Object.create(null);
    for (const [name, wert] of behalten) aus[name] = wert;
    speicher.setItem(k, JSON.stringify(aus));
    return true;
  } catch {
    return false;
  }
}

/** Der Speicher dieses Browsers oder dieser App; null, wenn es keinen gibt oder der Zugriff wirft. */
export function testSpeicher(): (Lesen & Schreiben) | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
