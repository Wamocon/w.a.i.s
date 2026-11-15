import type { Modellzugang } from "./nachrichten.ts";

/**
 * Reine Logik des geführten Modellzugangs beim Ausrollen (Entscheidung D2, docs/ausrollen-neue-nutzer.md 4.7): erst der
 * Claude-Code-Token, dann der API-Schlüssel, beide überspringbar; ohne beides läuft alles über die Hausmodelle. Danach
 * fasst eine Zeile je Bereich zusammen, wie W.A.I.S. für die Person arbeitet. Ohne React und ohne Browser, damit sie
 * sich mit node:test prüfen lässt (einrichtungSchritte.test.ts). Die Komponenten liegen in components/einrichtung/.
 *
 * Grundlage ist allein der Stand des Kerns (Modellzugang): ob etwas hinterlegt ist und die letzten vier Zeichen, nie ein
 * Schlüssel. Die Stimme läuft für alle über Soniox (D3), unabhängig vom Modellzugang.
 */

export type ModellSchrittId = "token" | "api";
export type SchrittId = ModellSchrittId | "zusammenfassung" | "installer";

/** Schritte des Modellzugangs in fester Reihenfolge: der Token immer vor dem API-Schlüssel. */
export const MODELL_SCHRITTE = ["token", "api", "zusammenfassung"] as const satisfies readonly SchrittId[];

export const SCHRITT_TITEL: Readonly<Record<SchrittId, string>> = {
  token: "Claude-Code-Token",
  api: "API-Schlüssel",
  zusammenfassung: "So arbeitet W.A.I.S. für dich",
  installer: "Installer laden",
};

/** Frage unter dem Titel der beiden Schlüsselschritte (wörtlich aus 4.7). */
export const SCHRITT_FRAGE: Readonly<Record<ModellSchrittId, string>> = {
  token: "Hast du ein Claude-Code-Konto (Max-Tarif)? Dann laufen deine Entwicklungsaufträge darüber.",
  api: "Hast du einen API-Schlüssel? Dann führst du Gespräche mit Claude Haiku; ohne Token laufen auch deine Entwicklungsaufträge darüber.",
};

/** Hat ein Admin das Profil auf Hausmodelle festgelegt, entfallen beide Schlüsselschritte (eigene Schlüssel sind gesperrt). */
export function schrittSichtbar(id: SchrittId, stand: Modellzugang | null): boolean {
  if (id === "token" || id === "api") return stand?.festgelegt !== true;
  return true;
}

export function schrittFolge(stand: Modellzugang | null): SchrittId[] {
  return MODELL_SCHRITTE.filter((id) => schrittSichtbar(id, stand));
}

/**
 * Welcher Schritt gilt, wenn der gewählte nicht mehr sichtbar ist (der Stand kommt zum Beispiel erst nach dem Start als
 * festgelegt an)? Der nächste sichtbare danach in der Reihenfolge aller Schritte, sonst der letzte sichtbare.
 */
export function wirksamerSchritt<T extends string>(alle: readonly T[], sichtbar: readonly T[], gewaehlt: T): T | null {
  if (sichtbar.includes(gewaehlt)) return gewaehlt;
  const ab = alle.indexOf(gewaehlt);
  return sichtbar.find((id) => alle.indexOf(id) > ab) ?? sichtbar[sichtbar.length - 1] ?? null;
}

export function schrittPosition<T extends string>(
  sichtbar: readonly T[],
  id: T,
): { nummer: number; gesamt: number; text: string } {
  const nummer = sichtbar.indexOf(id) + 1;
  return { nummer, gesamt: sichtbar.length, text: `Schritt ${nummer} von ${sichtbar.length}` };
}

/** Nächster (1) oder voriger (-1) sichtbarer Schritt; null am Rand. */
export function nachbarSchritt<T extends string>(sichtbar: readonly T[], id: T, richtung: 1 | -1): T | null {
  const i = sichtbar.indexOf(id);
  if (i < 0) return null;
  return sichtbar[i + richtung] ?? null;
}

/** Stand eines Schlüsselschritts als Satz, nur mit den letzten vier Zeichen, die der Kern meldet. */
export function schrittStand(id: ModellSchrittId, stand: Modellzugang | null): { hinterlegt: boolean; text: string } {
  const hinterlegt = id === "token" ? stand?.codeHinterlegt === true : stand?.hinterlegt === true;
  if (!hinterlegt) return { hinterlegt: false, text: "Nicht hinterlegt." };
  const ende = id === "token" ? stand?.codeEnde : stand?.ende;
  return { hinterlegt: true, text: ende ? `Hinterlegt, endet auf …${ende}.` : "Hinterlegt." };
}

/** Knopf eines Schlüsselschritts: mit hinterlegtem Wert geht es weiter, sonst wird übersprungen. */
export function weiterText(id: ModellSchrittId, stand: Modellzugang | null): "Weiter" | "Überspringen" {
  return schrittStand(id, stand).hinterlegt ? "Weiter" : "Überspringen";
}

// ---------- Zusammenfassung ----------
export const FAELLE = ["beides", "nur_token", "nur_api", "nichts", "festgelegt", "wahl", "zuordnung"] as const;
export type Fall = (typeof FAELLE)[number];

/**
 * Der Fall aus dem Stand des Kerns. Vorrang: Festlegung durch den Admin, dann die Wahl "Nur Hausmodelle" der Person
 * (in beiden Fällen wird kein Schlüssel benutzt), dann der Übergang über den Schlüssel des Kerns, dann die hinterlegten
 * Schlüssel. null: Stand noch unbekannt oder nicht lesbar.
 */
export function fallAus(stand: Modellzugang | null): Fall | null {
  if (!stand?.art) return null;
  if (stand.festgelegt || stand.quelle === "festgelegt") return "festgelegt";
  if (stand.quelle === "wahl" || stand.modus === "nur_haus") return "wahl";
  if (stand.quelle === "zuordnung") return "zuordnung";
  if (stand.hinterlegt && stand.codeHinterlegt) return "beides";
  if (stand.codeHinterlegt) return "nur_token";
  if (stand.hinterlegt) return "nur_api";
  return "nichts";
}

export type Zusammenfassung = {
  titel: string;
  zeilen: readonly { name: string; text: string }[];
  /** ein Satz zur Herkunft des Falls (Festlegung, eigene Wahl), sonst null */
  hinweis: string | null;
  /** wo sich das später ändern lässt */
  aendern: string;
};

const GESPRAECH = "Gespräch, Lernen und Websuche";
const ENTWICKLUNG = "Entwicklungsaufträge";
const STIMME = "Stimme";
const SONIOX = "Soniox, wie für alle Profile.";
const FREI = "sobald sie für dich freigeschaltet sind";
const HAUS_ENTWICKLUNG = "Über Hausmodelle, sobald sie dafür bereit und für dich freigeschaltet sind.";
const NUR_HAUS = "Alles über Hausmodelle, nichts geht an Anthropic.";
const AENDERN = "Das alles kannst du später unter Einstellungen, Modellzugang ändern.";

const TEXTE: Readonly<Record<Fall, { gespraech: string; entwicklung: string; hinweis: string | null; aendern?: string }>> = {
  beides: {
    gespraech: "Claude Haiku über deinen eigenen Schlüssel.",
    entwicklung: `Claude Code mit deinem Token (Max-Tarif, Sonnet), ${FREI}. Der Token hat Vorrang vor dem API-Schlüssel.`,
    hinweis: null,
  },
  nur_token: {
    gespraech: "Hausmodelle. Ein Max-Tarif deckt das Gespräch nicht ab, dafür bräuchte es einen API-Schlüssel.",
    entwicklung: `Claude Code mit deinem Token (Max-Tarif, Sonnet), ${FREI}.`,
    hinweis: null,
  },
  nur_api: {
    gespraech: "Claude Haiku über deinen eigenen Schlüssel.",
    entwicklung: `Claude Code mit deinem API-Schlüssel (Guthaben, Haiku), ${FREI}.`,
    hinweis: null,
  },
  nichts: {
    gespraech: "Hausmodelle für alles.",
    entwicklung: HAUS_ENTWICKLUNG,
    hinweis: null,
  },
  festgelegt: {
    gespraech: NUR_HAUS,
    entwicklung: HAUS_ENTWICKLUNG,
    hinweis: "Ein Admin hat dein Profil auf Hausmodelle festgelegt.",
    aendern: "Die Festlegung ändert nur ein Admin. Den Stand siehst du unter Einstellungen, Modellzugang.",
  },
  wahl: {
    gespraech: NUR_HAUS,
    entwicklung: HAUS_ENTWICKLUNG,
    hinweis: "Du hast Nur Hausmodelle gewählt. Hinterlegte Schlüssel und Token werden dann nicht benutzt.",
  },
  zuordnung: {
    gespraech: "Übergang über den Schlüssel des Kerns, bis du einen eigenen hinterlegst.",
    entwicklung: "Mit deinem Token, wenn einer hinterlegt ist, sonst übergangsweise über den Zugang des Kerns.",
    hinweis: null,
  },
};

/** Drei Zeilen (Gespräch mit Lernen und Websuche, Entwicklungsaufträge, Stimme) nach der Tabelle in 4.7. */
export function zusammenfassung(fall: Fall): Zusammenfassung {
  const t = TEXTE[fall];
  return {
    titel: SCHRITT_TITEL.zusammenfassung,
    zeilen: [
      { name: GESPRAECH, text: t.gespraech },
      { name: ENTWICKLUNG, text: t.entwicklung },
      { name: STIMME, text: SONIOX },
    ],
    hinweis: t.hinweis,
    aendern: t.aendern ?? AENDERN,
  };
}
