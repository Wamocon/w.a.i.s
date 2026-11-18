/**
 * Karte "Einreichen" eines Entwicklungsauftrags mit dem eigenen GitHub-Token (Plan C, docs/persoenliche-zugaenge.md C.6; Kern:
 * voice-core/github_auftrag.py und dev_agent_github.py). Reine Logik ohne React und ohne Browser, prüfbar mit node:test (einreichen.test.ts).
 *
 * Der Kern schickt in der Servernachricht freigaben einen Eintrag mit id "einreichen" und dem Zusatzfeld einreichen. Die Oberfläche liest es
 * streng: nur bekannte Felder und Werte, Pfade ohne Steuer- und Bidi-Zeichen. Lässt sich ein markierter Pfad nicht sicher anzeigen (solche
 * Zeichen, zu lang, zu viele), gilt die Karte als gesperrt (fail closed): niemand bestätigt eine Datei, die er nicht sieht. "Einreichen" geht
 * erst, wenn jeder markierte Pfad bestätigt ist; bei gesperrt gibt es nur "Verwerfen". Der Klick schickt einreichen mit commit_id, tree_id und
 * den bestätigten Pfaden oder verwerfen.
 */

export const EINREICHEN_ID = "einreichen";
export const EINREICHEN_STATUS = ["bereit", "gesperrt", "branch_gepusht", "einreichen_laeuft"] as const;
export type EinreichenStatus = (typeof EINREICHEN_STATUS)[number];

export type Einreichen = {
  status: EinreichenStatus;
  repo: string | null;
  privat: boolean;
  zweig: string;
  konto: string | null;
  commitId: string | null;
  treeId: string | null;
  dateien: number;
  plus: number;
  minus: number;
  /** sensible Pfade, je mit einem Kästchen */
  markiert: string[];
  /** die ersten Pfade der Änderung, nur zur Anzeige */
  pfade: string[];
  weitere: number;
  /** Sätze, warum sich die Änderung nicht einreichen lässt */
  gesperrt: string[];
  ungesichert: number;
  lauf: "fertig" | "zeitlimit" | "fehler" | null;
  titel: string;
  nachholen: boolean;
  fehler: string | null;
};

const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;
const LOGIN_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const COMMIT_RE = /^[0-9a-f]{40}$/;
const ZWEIG_RE = /^wamo\/[A-Za-z0-9_-]{1,64}$/;
const UNSICHTBAR = /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u;
const MAX_LISTE = 200;
const PFAD_MAX = 300;
const SATZ_MAX = 300;
const ZAHL_MAX = 10_000_000;
export const SATZ_PFAD_UNSICHER =
  "Eine markierte Datei lässt sich hier nicht sicher anzeigen. Bitte verwerfen und den Auftrag mit klareren Dateinamen neu stellen.";
export const SATZ_GESPERRT = "Die Änderung lässt sich nicht einreichen.";

const istObjekt = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const zahl = (v: unknown): number =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= ZAHL_MAX ? v : 0;
const passend = (v: unknown, re: RegExp): string | null => (typeof v === "string" && re.test(v) ? v : null);

function pfad(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 && v.length <= PFAD_MAX && v === v.trim() && !UNSICHTBAR.test(v) ? v : null;
}

function pfade(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  const aus: string[] = [];
  for (const p of v.slice(0, MAX_LISTE)) {
    const ok = pfad(p);
    if (ok && !aus.includes(ok)) aus.push(ok);
  }
  return aus;
}

function satz(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, " ").trim();
  return t ? t.slice(0, SATZ_MAX) : null;
}

/** Das Zusatzfeld einreichen lesen; null, wenn es keine gültige Karte ist. */
/** Sind alle markierten Pfade sicher anzeigbar (keiner fällt beim Lesen weg)? */
function markiertVollstaendig(v: unknown): boolean {
  if (v === undefined) return true;
  if (!Array.isArray(v) || v.length > MAX_LISTE) return false;
  return v.every((p) => pfad(p) !== null);
}

export function pruefeEinreichen(v: unknown): Einreichen | null {
  if (!istObjekt(v) || typeof v.status !== "string" || !(EINREICHEN_STATUS as readonly string[]).includes(v.status)) return null;
  const unsicher = !markiertVollstaendig(v.markiert);
  const status: EinreichenStatus = unsicher ? "gesperrt" : (v.status as EinreichenStatus);
  const commitId = passend(v.commit_id, COMMIT_RE);
  const treeId = passend(v.tree_id, COMMIT_RE);
  const zweig = passend(v.zweig, ZWEIG_RE);
  if (!zweig || (status !== "gesperrt" && !(commitId && treeId))) return null;
  const gesperrt = Array.isArray(v.gesperrt) ? v.gesperrt.slice(0, 20).map(satz).filter((s): s is string => s !== null) : [];
  if (unsicher) gesperrt.unshift(SATZ_PFAD_UNSICHER);
  if (status === "gesperrt" && gesperrt.length === 0) gesperrt.push(SATZ_GESPERRT);
  return {
    status,
    repo: passend(v.repo, REPO_RE),
    privat: v.privat === true,
    zweig,
    konto: passend(v.konto, LOGIN_RE),
    commitId,
    treeId,
    dateien: zahl(v.dateien),
    plus: zahl(v.plus),
    minus: zahl(v.minus),
    markiert: pfade(v.markiert),
    pfade: pfade(v.pfade).slice(0, 50),
    weitere: zahl(v.weitere),
    gesperrt,
    ungesichert: zahl(v.ungesichert),
    lauf: v.lauf === "fertig" || v.lauf === "zeitlimit" || v.lauf === "fehler" ? v.lauf : null,
    titel: satz(v.titel)?.slice(0, 100) ?? "",
    nachholen: v.nachholen === true && status !== "gesperrt",
    fehler: satz(v.fehler),
  };
}

/** Lässt sich die Änderung einreichen? Nicht bei gesperrt, nur mit Commit und Tree, und erst, wenn jeder markierte Pfad bestätigt ist. */
export function einreichenMoeglich(e: Einreichen, bestaetigt: ReadonlySet<string>): boolean {
  if (e.status === "gesperrt" || !e.commitId || !e.treeId) return false;
  return e.markiert.every((p) => bestaetigt.has(p));
}

export function knopfText(e: Einreichen): string {
  return e.nachholen ? "Pull Request nachholen" : "Einreichen";
}

/** "2 Dateien, +10 -3": Minus als Bindestrich. */
export function zahlenText(e: Einreichen): string {
  return `${e.dateien} ${e.dateien === 1 ? "Datei" : "Dateien"}, +${e.plus} -${e.minus}`;
}

/** Daten der Client-Nachricht einreichen: nur die bestätigten markierten Pfade, sortiert. */
export function einreichenDaten(job: string, e: Einreichen, bestaetigt: ReadonlySet<string>) {
  return {
    job,
    commit_id: e.commitId ?? "",
    tree_id: e.treeId ?? "",
    bestaetigt: e.markiert.filter((p) => bestaetigt.has(p)).sort(),
  };
}

/** Hinweis auf nicht committete Dateien (sie gehen nicht mit). */
export function ungesichertText(e: Einreichen): string | null {
  if (!e.ungesichert) return null;
  return e.ungesichert === 1
    ? "1 Datei wurde nicht committet und geht nicht mit."
    : `${e.ungesichert} Dateien wurden nicht committet und gehen nicht mit.`;
}

/** Zusatzfeld github der Auftragskarte vor dem Start ({konto, hinweis}); undefined, wenn es fehlt oder nicht passt. */
export function auftragGithub(v: unknown): { konto: string | null } | undefined {
  if (!istObjekt(v)) return undefined;
  return { konto: passend(v.konto, LOGIN_RE) };
}
