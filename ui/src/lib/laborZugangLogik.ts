import { aal2Zeitpunkt } from "./anmeldung.ts";

/**
 * Reine Logik des Claude-Zugangs des Testlabors in der Werkstatt (Kern: voice-core/labor_zugang.py und labor_zugang_api.py, Migration 0032).
 * Ohne React und ohne Browser, prüfbar mit node:test (laborZugangLogik.test.ts). Die Aufrufe selbst stehen in lib/laborZugang.ts.
 *
 * Die Antwort des Kerns wird streng gelesen: nur bekannte Felder und Werte, Unbekanntes wird null. Der Kern schickt den Schlüssel nie
 * zurück, nur Quelle, die letzten vier Zeichen, Workspace und Zeiten. Die Form eines eingegebenen Schlüssels prüft die Oberfläche vorab nur,
 * um sofort einen Satz zu zeigen; die verbindliche Prüfung (auch bei Anthropic) macht der Kern. Jeder Text, der angezeigt wird, geht durch
 * schwaerzen: Sähe etwas wie ein Schlüssel aus, erschiene es gekürzt.
 */

export type LaborQuelle = "gespeichert" | "server" | "keiner";

export type LaborZugang = {
  quelle: LaborQuelle;
  /** die letzten vier Zeichen des Schlüssels, der gilt (gespeichert oder Server), sonst null */
  endetAuf: string | null;
  workspace: string | null;
  gesetztAm: string | null;
  geprueftAm: string | null;
  hinweis: string | null;
};

export type Eingabe = { schluessel: string; workspace: string | null };

/** So alt darf der Code des zweiten Faktors höchstens sein, damit der Kern ändert (Kern: 60 Sekunden). */
export const FAKTOR_MAX_ALTER_S = 60;
/** Luft für Uhren, die Testanfrage bei Anthropic und das Netz: Die Oberfläche fragt schon vorher nach einem neuen Code. */
export const FAKTOR_RESERVE_S = 10;

const QUELLEN: readonly LaborQuelle[] = ["gespeichert", "server", "keiner"];
const ENDE_RE = /^[A-Za-z0-9_-]{4}$/;
const WORKSPACE_RE = /^wrkspc_[A-Za-z0-9]{6,60}$/;
const ZEIT_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?$/;
const SCHLUESSEL_RE = /^sk-ant-[A-Za-z0-9_-]{20,250}$/;
const TOKEN_RE = /^sk-ant-oat\d{2}-[A-Za-z0-9_-]{20,400}$/;
const IM_TEXT_RE = /sk-ant-[A-Za-z0-9_-]{8,}/g;
const SATZ_MAX = 400;

const istObjekt = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Alles, was wie ein Anthropic-Schlüssel aussieht, gekürzt (für jeden angezeigten Text). */
export function schwaerzen(text: string): string {
  return text.replace(IM_TEXT_RE, "sk-ant-…");
}

/** Ein Satz des Kerns: Text ohne Steuerzeichen, gekürzt, ohne Schlüssel; sonst null. */
export function satz(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const sauber = schwaerzen(v.replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, " ").replace(/\s+/g, " ").trim());
  return sauber ? sauber.slice(0, SATZ_MAX) : null;
}

const passend = (v: unknown, re: RegExp): string | null => (typeof v === "string" && re.test(v) ? v : null);

/** Die Antwort des Kerns streng lesen; null heißt "unerwartet". */
export function alsLaborZugang(daten: unknown): LaborZugang | null {
  if (!istObjekt(daten)) return null;
  const quelle = QUELLEN.find((q) => q === daten.quelle);
  if (!quelle) return null;
  return {
    quelle,
    endetAuf: passend(daten.endet_auf, ENDE_RE),
    workspace: passend(daten.workspace, WORKSPACE_RE),
    gesetztAm: passend(daten.gesetzt_am, ZEIT_RE),
    geprueftAm: passend(daten.geprueft_am, ZEIT_RE),
    hinweis: satz(daten.hinweis),
  };
}

/** "21.11.2026, 09:30" aus einer ISO-Zeit des Kerns (ohne Umrechnung der Zeitzone: so steht es im Kern); sonst null. */
export function zeitText(iso: string | null): string | null {
  const m = iso ? ZEIT_RE.exec(iso) : null;
  return m ? `${m[3]}.${m[2]}.${m[1]}, ${m[4]}:${m[5]}` : null;
}

/** Ein Satz zur Quelle, der sagt, womit die nächste Laborsitzung arbeitet. */
export function quelleSatz(z: LaborZugang): string {
  const ende = z.endetAuf ? `, endet auf …${z.endetAuf}` : "";
  if (z.quelle === "gespeichert") return `Der hier gespeicherte Schlüssel gilt${ende}.`;
  if (z.quelle === "server") return `Es gilt der Schlüssel des Servers${ende}. Er lässt sich hier nicht ändern, nur ersetzen.`;
  return "Es gibt keinen Claude-Schlüssel für das Labor. Die Laborsitzungen laufen über Hausmodelle.";
}

export const QUELLE_WORT: Readonly<Record<LaborQuelle, string>> = Object.freeze({
  gespeichert: "gespeichert",
  server: "vom Server",
  keiner: "keiner",
});

/**
 * Prüft die Eingabe, bevor etwas gesendet wird: ein API-Schlüssel (kein Claude-Code-Token), ein Workspace nur in der Form wrkspc_...
 * Leerraum am Rand wird entfernt. Die Sätze nennen nie den Schlüssel.
 */
export function eingabePruefen(schluesselRoh: string, workspaceRoh: string): { ok: true; eingabe: Eingabe } | { ok: false; text: string } {
  const schluessel = schluesselRoh.trim();
  if (!schluessel) return { ok: false, text: "Bitte trag den Claude-Schlüssel ein." };
  if (TOKEN_RE.test(schluessel)) {
    return { ok: false, text: "Das ist ein Claude-Code-Token, kein API-Schlüssel. Das Labor braucht einen API-Schlüssel aus der Anthropic-Konsole." };
  }
  if (!SCHLUESSEL_RE.test(schluessel)) {
    return { ok: false, text: "Das sieht nicht nach einem Anthropic-API-Schlüssel aus (er beginnt mit sk-ant-, ohne Leerzeichen)." };
  }
  const workspace = workspaceRoh.trim();
  if (workspace && !WORKSPACE_RE.test(workspace)) return { ok: false, text: "Die Workspace-ID beginnt mit wrkspc_." };
  return { ok: true, eingabe: { schluessel, workspace: workspace || null } };
}

/** Der Code aus der Authenticator-App: sechs Ziffern, Leerzeichen dazwischen sind erlaubt; sonst null. */
export function codeSauber(eingabe: string): string | null {
  const s = eingabe.replace(/\s+/g, "");
  return /^\d{6}$/.test(s) ? s : null;
}

/** Ist der Code des zweiten Faktors im Token jung genug, dass der Kern ändert? Die Oberfläche fragt schon vorher nach einem neuen Code. */
export function faktorFrisch(accessToken: string | null | undefined, jetztMs: number): boolean {
  if (!accessToken) return false;
  const zeit = aal2Zeitpunkt(accessToken);
  if (zeit === null) return false;
  const alterS = (jetztMs - zeit) / 1000;
  return alterS >= -5 && alterS <= FAKTOR_MAX_ALTER_S - FAKTOR_RESERVE_S;
}

export type FehlerBild = { code: string; text: string; status: number };

/** Die Codes, die der Kern für diese Route meldet. */
export const FAKTOR_ALT = "zweiter_faktor_zu_alt";

const FEHLER_SAETZE: Readonly<Record<string, string>> = Object.freeze({
  zweiter_faktor_zu_alt: "Der Code des zweiten Faktors ist zu alt. Bitte gib einen frischen Code aus der Authenticator-App ein.",
  nicht_berechtigt: "Den Claude-Zugang des Labors stellen nur Admins ein.",
  labor_pfad_gesperrt: "Mit einem Laborprofil gibt es keinen Zugang zu dieser Einstellung.",
  zu_oft: "Zu viele Versuche. Bitte warte ein paar Minuten und versuche es dann noch einmal.",
});

/** Codes, bei denen der Satz des Kerns genauer ist als jeder eigene (er nennt etwa, was Anthropic gemeldet hat). */
const SATZ_DES_KERNS: ReadonlySet<string> = new Set([
  "schluessel_ungueltig",
  "workspace_ungueltig",
  "schluessel_abgelehnt",
  "anthropic_nicht_erreichbar",
  "anthropic_fehler",
  "kein_hauptschluessel",
  "nicht_eingerichtet",
  "datenbank",
  "intern",
]);

/**
 * Das Fehlerbild zu einem Fehler des Kerns (status, code, text wie KernFehler sie trägt). Bekannte Codes bekommen einen festen Satz oder den
 * Satz des Kerns, alles andere einen Satz zum Status. Nie roher Text eines Fremden: Der Satz des Kerns wird gesäubert und gekürzt.
 */
export function fehlerBild(status: number, code: string | null, text: string | null): FehlerBild {
  const kern = satz(text);
  const echt = kern && !/^Fehler \d+$/.test(kern) ? kern : null;
  if (code && code in FEHLER_SAETZE) return { code, text: FEHLER_SAETZE[code], status };
  if (code && SATZ_DES_KERNS.has(code) && echt) return { code, text: echt, status };
  if (status === 0) return { code: "netz", text: "Der Kern ist nicht erreichbar. Er lässt sich nur aus dem Büronetz oder über WireGuard öffnen.", status };
  if (status === 401) return { code: "nicht_angemeldet", text: "Die Anmeldung fehlt oder ist abgelaufen. Bitte melde dich neu an.", status };
  if (status === 403) return { code: "nicht_berechtigt", text: FEHLER_SAETZE.nicht_berechtigt, status };
  if (status === 404) return { code: "nicht_gefunden", text: "Der Kern kennt diese Einstellung noch nicht. Er braucht das Release mit dem Paket Labor-Zugang.", status };
  if (status === 413) return { code: "zu_gross", text: "Die Eingabe ist zu groß.", status };
  if (status === 429) return { code: "zu_oft", text: FEHLER_SAETZE.zu_oft, status };
  if (status >= 500) return { code: "nicht_verfuegbar", text: echt ?? "Der Kern ist gerade nicht verfügbar. Bitte versuche es gleich noch einmal.", status };
  return { code: "antwort", text: echt ?? "Die Antwort des Kerns war unerwartet. Bitte lade die Ansicht neu.", status };
}
