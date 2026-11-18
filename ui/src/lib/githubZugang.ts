/**
 * Reine Logik des persönlichen GitHub-Zugangs (Plan C, docs/persoenliche-zugaenge.md C.4; Kern: voice-core/github_zugang.py und
 * github_zugang_api.py). Ohne React und ohne Browser, prüfbar mit node:test (githubZugang.test.ts).
 *
 * Die Antwort des Kerns wird streng gelesen: nur bekannte Felder und Werte, Unbekanntes wird null. Der Kern schickt nie das Token zurück,
 * nur Art, Login, Rechte, Ablauf und die letzten vier Zeichen. Die Form eines eingegebenen Tokens prüft die Oberfläche vorab nur, um sofort
 * einen Satz zu zeigen; die verbindliche Prüfung (auch bei GitHub) macht der Kern. Dazu die Admin-Übersicht der erlaubten Rechte je Person.
 */

export type GithubArt = "fein" | "klassisch";
export type GithubAktion = "stand" | "speichern" | "pruefen" | "loeschen";

export type GithubZugang = {
  aktion: GithubAktion;
  verfuegbar: boolean;
  grund: string | null;
  hinterlegt: boolean;
  art: GithubArt | null;
  login: string | null;
  ende: string | null;
  scopes: string[];
  ablauf: string | null;
  geprueft: string | null;
  angelegt: string | null;
  /** vom Admin erlaubte Ausnahmen (C.2.8), sortiert */
  scopesAusnahmen: string[];
  problem: string | null;
  bereit: boolean;
  hinweisFein: string | null;
  fehler: string | null;
  ok: string | null;
};

const AKTIONEN: readonly GithubAktion[] = ["stand", "speichern", "pruefen", "loeschen"];
const ARTEN: readonly GithubArt[] = ["fein", "klassisch"];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const LOGIN_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const SCOPE_RE = /^[a-z][a-z0-9_:]{0,39}$/;
const ENDE_RE = /^[A-Za-z0-9_]{4}$/;
const DATUM_RE = /^\d{4}-\d{2}-\d{2}$/;
const ZEIT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?$/;
const SATZ_MAX = 400;
const MAX_SCOPES = 30;

const istObjekt = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const aus = <T extends string>(v: unknown, erlaubt: readonly T[]): T | null =>
  typeof v === "string" && (erlaubt as readonly string[]).includes(v) ? (v as T) : null;
const passend = (v: unknown, re: RegExp): string | null => (typeof v === "string" && re.test(v) ? v : null);

/** Ein Satz des Kerns: Text ohne Steuerzeichen, gekürzt; sonst null. */
function satz(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const sauber = v.replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, " ").trim();
  return sauber ? sauber.slice(0, SATZ_MAX) : null;
}

function scopes(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.slice(0, MAX_SCOPES).filter((s): s is string => typeof s === "string" && SCOPE_RE.test(s));
}

/** Die Antwort des Kerns ({"type": "github_zugang", ...}) lesen; null, wenn sie keine gültige Antwort ist. */
export function pruefeAntwort(v: unknown): GithubZugang | null {
  if (!istObjekt(v) || v.type !== "github_zugang") return null;
  const hinterlegt = v.hinterlegt === true;
  return {
    aktion: aus(v.aktion, AKTIONEN) ?? "stand",
    verfuegbar: v.verfuegbar === true,
    grund: satz(v.grund),
    hinterlegt,
    art: hinterlegt ? aus(v.art, ARTEN) : null,
    login: hinterlegt ? passend(v.login, LOGIN_RE) : null,
    ende: hinterlegt ? passend(v.ende, ENDE_RE) : null,
    scopes: hinterlegt ? scopes(v.scopes) : [],
    ablauf: hinterlegt ? passend(v.ablauf, DATUM_RE) : null,
    geprueft: hinterlegt ? passend(v.geprueft, ZEIT_RE) : null,
    angelegt: hinterlegt ? passend(v.angelegt, ZEIT_RE) : null,
    scopesAusnahmen: scopes(v.scopes_ausnahmen),
    problem: hinterlegt ? satz(v.problem) : null,
    bereit: hinterlegt && v.bereit === true,
    hinweisFein: satz(v.hinweis_fein),
    fehler: satz(v.fehler),
    ok: satz(v.ok),
  };
}

/** Stand, der nur einen Fehler trägt (Kern nicht erreichbar, unerwartete Antwort). */
export function fehlerStand(aktion: GithubAktion, fehler: string): GithubZugang {
  return {
    aktion, verfuegbar: false, grund: null, hinterlegt: false, art: null, login: null, ende: null, scopes: [], ablauf: null,
    geprueft: null, angelegt: null, scopesAusnahmen: [], problem: null, bereit: false, hinweisFein: null, fehler, ok: null,
  };
}

export type Form = "leer" | "klassisch" | "fein" | "fremd" | "ungueltig";

/** Vorprüfung der Eingabe (wie github_zugang.art_von im Kern), damit ein Tippfehler sofort einen Satz bekommt. */
export function tokenForm(roh: string): Form {
  const wert = roh.trim();
  if (!wert) return "leer";
  if (/^ghp_[A-Za-z0-9]{36}$/.test(wert)) return "klassisch";
  if (/^github_pat_[A-Za-z0-9_]{82}$/.test(wert)) return "fein";
  if (/^gh[ousr]_[A-Za-z0-9_]{8,}$/.test(wert)) return "fremd";
  return "ungueltig";
}

/** Satz zu einer Form, die der Kern ablehnen würde; null, wenn die Form passt oder das Feld leer ist. */
export function formFehler(form: Form): string | null {
  if (form === "fremd") {
    return "Das ist kein persönliches Zugriffstoken (es gehört zu einer App oder einer Anmeldung). Bitte ein fein-granulares Token (github_pat_) oder ein klassisches Token (ghp_) erzeugen.";
  }
  if (form === "ungueltig") return "Das ist kein GitHub-Token: Es beginnt mit github_pat_ (fein-granular) oder ghp_ (klassisch).";
  return null;
}

export const ART_TEXT: Record<GithubArt, string> = { fein: "fein-granular", klassisch: "klassisch" };

/** 2026-12-31 als 31.12.2026; sonst der Text unverändert. */
export function datumDeutsch(iso: string | null): string {
  if (!iso) return "unbekannt";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso;
}

/** Eine Zeile zum Stand, ohne Token. */
export function standZeile(z: GithubZugang | null): string {
  if (!z) return "Stand wird geladen …";
  if (!z.hinterlegt) return "Kein GitHub-Token hinterlegt.";
  const art = z.art ? ART_TEXT[z.art] : "unbekannte Art";
  return `Hinterlegt: Konto ${z.login ?? "unbekannt"}, ${art}, endet auf …${z.ende ?? "????"}, gültig bis ${datumDeutsch(z.ablauf)}.`;
}

/** Konkrete Meldung zu einem Fehler beim Aufruf des Kerns (Status 0 steht für Netz und Zeitgrenze). */
export function fehlerText(status: number, text: string): string {
  if (status === 0) {
    return text === "Zeitüberschreitung"
      ? "Der Kern hat nicht rechtzeitig geantwortet (Zeitüberschreitung). Bitte noch einmal versuchen."
      : "Der Kern ist nicht erreichbar. Bitte später noch einmal versuchen.";
  }
  if (status === 401) return "Die Anmeldung ist abgelaufen oder ungültig. Bitte neu anmelden.";
  if (status === 403) return "Für dieses Profil gibt es keinen GitHub-Zugang.";
  if (status === 404) return "Der Kern kennt den GitHub-Zugang noch nicht (Version vor Plan C).";
  if (status === 413) return "Die Eingabe ist zu lang für ein GitHub-Token.";
  if (status === 429) return "Zu viele Versuche. Bitte in ein paar Minuten noch einmal versuchen.";
  if (status >= 500) return "Der Kern hat gerade ein Problem. Bitte später noch einmal versuchen.";
  return `Der Kern hat die Anfrage abgelehnt (${status}).`;
}

// ---------- Admin: erlaubte Rechte je Person ----------

/**
 * Beschriftung und Gruppe je Scope aus SCOPES_AUSNAHMEN (C.2.8; die Liste selbst kommt vom Kern, Unbekanntes steht unter "Weitere").
 * Scopes, die Code ausführen oder dauerhaften Zugriff schaffen, tragen den Hinweis "riskant".
 */
export const RECHTE_TEXTE: Record<string, { gruppe: string; text: string }> = {
  workflow: { gruppe: "Workflows und Gists", text: "workflow: GitHub-Actions-Workflows ändern (riskant: Code läuft in CI)" },
  gist: { gruppe: "Workflows und Gists", text: "gist: Gists anlegen und ändern" },
  "write:org": { gruppe: "Organisation", text: "write:org: Mitgliedschaften und Teams ändern" },
  "admin:org": { gruppe: "Organisation", text: "admin:org: Organisation verwalten" },
  "admin:org_hook": { gruppe: "Organisation", text: "admin:org_hook: Webhooks der Organisation" },
  "manage_runners:org": { gruppe: "Organisation", text: "manage_runners:org: Runner verwalten (riskant: Code läuft auf Runnern)" },
  "write:network_configurations": { gruppe: "Organisation", text: "write:network_configurations: Netzwerkeinstellungen ändern" },
  audit_log: { gruppe: "Organisation", text: "audit_log: Audit-Log verwalten" },
  "read:audit_log": { gruppe: "Organisation", text: "read:audit_log: Audit-Log lesen" },
  "write:packages": { gruppe: "Pakete", text: "write:packages: Pakete veröffentlichen" },
  "read:packages": { gruppe: "Pakete", text: "read:packages: Pakete lesen" },
  "delete:packages": { gruppe: "Pakete", text: "delete:packages: Pakete löschen" },
  user: { gruppe: "Konto der Person", text: "user: Profil lesen und ändern" },
  "user:email": { gruppe: "Konto der Person", text: "user:email: E-Mail-Adressen lesen" },
  "user:follow": { gruppe: "Konto der Person", text: "user:follow: Folgen ändern" },
  "admin:repo_hook": { gruppe: "Webhooks der Repos", text: "admin:repo_hook: Webhooks verwalten" },
  "write:repo_hook": { gruppe: "Webhooks der Repos", text: "write:repo_hook: Webhooks anlegen (riskant: Daten fließen ab)" },
  "admin:public_key": { gruppe: "Schlüssel auf dem Konto", text: "admin:public_key: SSH-Schlüssel verwalten" },
  "write:public_key": { gruppe: "Schlüssel auf dem Konto", text: "write:public_key: SSH-Schlüssel anlegen (riskant: dauerhafter Zugriff)" },
  "admin:gpg_key": { gruppe: "Schlüssel auf dem Konto", text: "admin:gpg_key: GPG-Schlüssel verwalten" },
  "write:gpg_key": { gruppe: "Schlüssel auf dem Konto", text: "write:gpg_key: GPG-Schlüssel anlegen" },
  "admin:ssh_signing_key": { gruppe: "Schlüssel auf dem Konto", text: "admin:ssh_signing_key: Signaturschlüssel verwalten" },
  "write:ssh_signing_key": { gruppe: "Schlüssel auf dem Konto", text: "write:ssh_signing_key: Signaturschlüssel anlegen" },
  codespace: { gruppe: "Codespaces und Copilot", text: "codespace: Codespaces verwalten" },
  "codespace:secrets": { gruppe: "Codespaces und Copilot", text: "codespace:secrets: Geheimnisse der Codespaces" },
  copilot: { gruppe: "Codespaces und Copilot", text: "copilot: Copilot-Einstellungen" },
  "manage_billing:copilot": { gruppe: "Codespaces und Copilot", text: "manage_billing:copilot: Abrechnung von Copilot" },
};

export type RechtePerson = {
  userId: string;
  name: string;
  rolle: "admin" | "mitglied" | null;
  aktiv: boolean;
  scopesAusnahmen: string[];
  hinterlegt: boolean;
  art: GithubArt | null;
  login: string | null;
  ablauf: string | null;
};

export type RechteListe = { personen: RechtePerson[]; erlaubbar: string[]; nie: string[] };

function name(v: unknown): string {
  if (typeof v !== "string") return "";
  return v.slice(0, 240).replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, "").slice(0, 60);
}

export function pruefePerson(v: unknown, erlaubbar: readonly string[]): RechtePerson | null {
  if (!istObjekt(v) || typeof v.user_id !== "string" || !UUID_RE.test(v.user_id)) return null;
  const hinterlegt = v.hinterlegt === true;
  return {
    userId: v.user_id,
    name: name(v.name),
    rolle: aus(v.rolle, ["admin", "mitglied"] as const),
    aktiv: v.aktiv === true,
    scopesAusnahmen: scopes(v.scopes_ausnahmen).filter((s) => erlaubbar.includes(s)),
    hinterlegt,
    art: hinterlegt ? aus(v.art, ARTEN) : null,
    login: hinterlegt ? passend(v.login, LOGIN_RE) : null,
    ablauf: hinterlegt ? passend(v.ablauf, DATUM_RE) : null,
  };
}

/** Die Antwort { personen, erlaubbar, nie } lesen; null, wenn die Form nicht stimmt. Nie-Rechte sind nie erlaubbar. */
export function pruefeRechteListe(v: unknown): RechteListe | null {
  if (!istObjekt(v) || !Array.isArray(v.personen) || !Array.isArray(v.erlaubbar)) return null;
  const nie = scopes(v.nie);
  const erlaubbar = scopes(v.erlaubbar).filter((s) => !nie.includes(s));
  const personen = v.personen
    .slice(0, 200)
    .map((p) => pruefePerson(p, erlaubbar))
    .filter((p): p is RechtePerson => p !== null);
  return { personen, erlaubbar, nie };
}

/** Die erlaubbaren Rechte nach Gruppen, in der Reihenfolge des Kerns. */
export function rechteGruppen(erlaubbar: readonly string[]): { gruppe: string; rechte: { scope: string; text: string }[] }[] {
  const gruppen: { gruppe: string; rechte: { scope: string; text: string }[] }[] = [];
  for (const scope of erlaubbar) {
    const eintrag = RECHTE_TEXTE[scope] ?? { gruppe: "Weitere", text: scope };
    let g = gruppen.find((x) => x.gruppe === eintrag.gruppe);
    if (!g) {
      g = { gruppe: eintrag.gruppe, rechte: [] };
      gruppen.push(g);
    }
    g.rechte.push({ scope, text: eintrag.text });
  }
  return gruppen;
}

/** Kurzer Satz je Person für die Admin-Übersicht. */
export function personZeile(p: RechtePerson): string {
  const token = p.hinterlegt
    ? `Token ${p.art ? ART_TEXT[p.art] : "unbekannt"}${p.login ? ` von ${p.login}` : ""}, gültig bis ${datumDeutsch(p.ablauf)}`
    : "kein Token hinterlegt";
  const rechte = p.scopesAusnahmen.length ? `zusätzlich erlaubt: ${p.scopesAusnahmen.join(", ")}` : "strenger Standard";
  return `${token}; ${rechte}.`;
}

/** Gleiche Menge? (Reihenfolge egal) */
export function gleicheRechte(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((s) => b.includes(s));
}
