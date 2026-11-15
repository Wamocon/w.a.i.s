import { drosselWartezeit } from "./drossel.ts";
import type { KernJson, TunnelZustand } from "./geraet.ts";

/**
 * Reine Logik zum Abschnitt "Erste Schritte" der Einstellungen (components/einstellungen/ErsteSchritte.tsx), ohne React und
 * ohne Browser, damit sie sich mit node:test prüfen lässt (einrichtung.test.ts). Kern-Aufruf (kernJson aus lib/kernApi.ts) und
 * Desktop-Brücke (window.wamoDesktop, desktop/preload.js) kommen von außen. Planpapier: docs/ausrollen-neue-nutzer.md, 4.2 und 4.3.
 */

// ---------- Prüfliste ----------
//
// Zwölf Punkte in der Reihenfolge der Tabelle 4.3. Quellen: der Kern (GET /wamo/api/einrichtung/stand, voice-core/einrichtung_api.py)
// für Passwort, Gerät, Stimme, Gespräch, Entwicklungsaufträge, Stimmabdruck und PC-Steuerung; die Desktop-App für App-Version,
// Host-Umgebung und Mikrofon; beide zusammen für den Tunnel. Die Anmeldung ist immer bereit (ohne aal2 gäbe es die Seite nicht).
// Ist der Kern nicht erreichbar (auch ein älterer Kern ohne die Route), steht statt seiner Punkte ein Punkt "Kern" da.
//
// Updates (Sicherheitsbefund HIGH 2): Die Oberfläche reicht das Manifest des Servers (GET /wamo/api/installer) nur an die App
// weiter. Ein Update-Angebot entsteht ausschließlich, wenn die App Signatur und steigende Version bestätigt hat (ok und neuer).
// Alles, was von Kern und App kommt, wird streng gelesen; angezeigt wird nur Text, ohne Steuerzeichen, höchstens 300 Zeichen.

export const PRUEF_ABSTAND_MS = 10_000; // "Erneut prüfen" höchstens einmal je 10 Sekunden
export const TEXT_MAX = 300;
export const FRIST_BRUECKE_MS = 15_000; // so lange wartet die Prüfliste auf eine Antwort der App
const MANIFEST_MAX = 16_384;

export const PUNKT_REIHENFOLGE = [
  "anmeldung",
  "kern",
  "passwort",
  "app",
  "geraet",
  "host",
  "tunnel",
  "mikrofon",
  "stimme",
  "gespraech",
  "entwicklung",
  "stimmabdruck",
  "pc",
] as const;
export type PunktId = (typeof PUNKT_REIHENFOLGE)[number];

/** Punkte, die der Kern meldet (der Tunnel wird mit dem Stand der App verbunden). */
export const KERN_PUNKTE = ["passwort", "geraet", "tunnel", "stimme", "gespraech", "entwicklung", "stimmabdruck", "pc"] as const;
export type KernPunktId = (typeof KERN_PUNKTE)[number];
const APP_PUNKTE = ["app", "host", "tunnel", "mikrofon"] as const;

export type Stufe = "gruen" | "rot" | "hinweis";
const STUFEN: readonly Stufe[] = ["gruen", "rot", "hinweis"];

export const PUNKT_TITEL: Record<PunktId, string> = {
  anmeldung: "Anmeldung",
  kern: "Kern",
  passwort: "Passwort",
  app: "App-Version",
  geraet: "Gerät",
  host: "Host-Umgebung",
  tunnel: "Tunnel",
  mikrofon: "Mikrofon",
  stimme: "Stimme",
  gespraech: "Gespräch",
  entwicklung: "Entwicklungsaufträge",
  stimmabdruck: "Stimmabdruck",
  pc: "PC-Steuerung",
};

/** Zustand als Wort für Screenreader: die Farbe trägt ihn nie allein. */
export const STUFE_TEXT: Record<Stufe, string> = { gruen: "Bereit", rot: "Offen", hinweis: "Hinweis" };

/** Was der Knopf "Update installieren" an die App gibt (nur nach Bestätigung durch die App). */
export type UpdateAngebot = Readonly<{ version: string; manifest: string; signatur: string }>;
export type Punkt = Readonly<{ id: PunktId; titel: string; stufe: Stufe; text: string; update?: UpdateAngebot }>;
export type KernEintrag = Readonly<{ stufe: Stufe; text: string }>;
export type KernStand = Readonly<Partial<Record<KernPunktId, KernEintrag>>>;
export type Manifest = Readonly<{ manifest: string; signatur: string }>;
export type HostUmgebung = "bereit" | "fehlt" | "fehler" | "entwickler";
export type AppStatus = { ok: true; tunnel: TunnelZustand; host: HostUmgebung | null } | { ok: false; text: string };
export type UpdatePruefung = { ok: true; version: string; neuer: boolean } | { ok: false; text: string };
export type UpdateInstallation = { ok: true } | { ok: false; text: string; abgebrochen: boolean };

/** Stand der Updates: App ohne Prüfung, Server ohne signiertes Manifest (404), Manifest nicht lesbar, von der App geprüft. */
export type UpdateStand =
  | { art: "ohne_pruefung" }
  | { art: "kein_angebot" }
  | { art: "unbekannt" }
  | { art: "geprueft"; manifest: Manifest; ergebnis: UpdatePruefung };

/** Was die App gemeldet hat; null in zusammenfuehren heißt: keine Desktop-Brücke (Browser). */
export type AppStand = { version: unknown; status: AppStatus | null; mikrofon: unknown; update: UpdateStand };

/**
 * Update-Teil der Brücke (desktop/preload.js, ab App 0.3.0). Antworten sind ungeprüft, gelesen mit pruefeUpdatePruefung und
 * pruefeInstallation. pruefen: { ok: true, version, neuer } oder { ok: false, text }. installieren: { ok: true } (die App
 * fragt selbst nach und beendet sich) oder { ok: false, text, abgebrochen? }. Das Token geht nur an installieren.
 */
export type UpdateBruecke = {
  pruefen: (anfrage: { manifest: string; signatur: string }) => Promise<unknown>;
  installieren: (anfrage: { manifest: string; signatur: string; token: string }) => Promise<unknown>;
};

/** Was die Prüfliste von window.wamoDesktop braucht (ältere Apps kennen version und update nicht). */
export type PrueflisteBruecke = {
  version?: unknown;
  geraet?: { status: () => Promise<unknown> };
  mikrofonStatus?: () => Promise<unknown>;
  update?: UpdateBruecke;
};

const T_ANMELDUNG = "Angemeldet mit zweitem Faktor.";
const T_KERN = "Die Prüfung am Server ist gerade nicht erreichbar.";
const T_NUR_APP = "Nur in der Desktop-App prüfbar.";
const T_UPDATE_EMPFOHLEN = "Update empfohlen.";
const T_HOST_FEHLT = "Die Python-Umgebung fehlt. Netz zu PyPI und GitHub nötig, die App versucht es beim nächsten Start erneut.";
const T_HOST_ALT = "Erst nach einem Update der App prüfbar.";
const T_TUNNEL = "Der Tunnel steht nicht. Bist du im Büronetz?";
const T_MIKRO = "Windows blockiert das Mikrofon für W.A.I.S.";
const T_APP_STUMM = "Die App meldet gerade keinen Stand.";
const T_PRUEFUNG_WEG = "Die App konnte das Update nicht bestätigen.";
const T_INSTALL_WEG = "Das Update ließ sich nicht starten.";
const T_OHNE_APP = "Updates gibt es nur in der Desktop-App.";
const T_ANMELDUNG_WEG = "Die Anmeldung ist abgelaufen. Bitte neu anmelden.";

const RE_VERSION = /^\d{1,4}\.\d{1,4}\.\d{1,6}$/;
const RE_SIGNATUR = /^[A-Za-z0-9+/_-]{40,200}={0,2}$/;
const TUNNEL: readonly TunnelZustand[] = ["verbunden", "host", "aus", "unbekannt"];
const HOST: readonly HostUmgebung[] = ["bereit", "fehlt", "fehler", "entwickler"];

type Objekt = Record<string, unknown>;
const istObjekt = (v: unknown): v is Objekt => typeof v === "object" && v !== null && !Array.isArray(v);
const istVersion = (v: unknown): v is string => typeof v === "string" && RE_VERSION.test(v);
const enthaelt = <T extends string>(liste: readonly T[], v: unknown): v is T => typeof v === "string" && (liste as readonly string[]).includes(v);

/** Text zur Anzeige: nur Text, ohne Steuerzeichen, auf TEXT_MAX Zeichen gekürzt; sonst der Ersatz. */
export function satz(v: unknown, ersatz: string): string {
  if (typeof v !== "string") return ersatz;
  const sauber = Array.from(v)
    .filter((z) => z.charCodeAt(0) >= 32 && z.charCodeAt(0) !== 127)
    .join("")
    .trim();
  return sauber ? Array.from(sauber).slice(0, TEXT_MAX).join("") : ersatz;
}

const punkt = (id: PunktId, stufe: Stufe, text: string): Punkt => ({ id, titel: PUNKT_TITEL[id], stufe, text });

/** Antwort des Kerns lesen; null, wenn sie keine Liste enthält. Unbekannte Kennungen und Stufen fallen weg, die erste Angabe gilt. */
export function pruefeKernStand(v: unknown): KernStand | null {
  if (!istObjekt(v) || !Array.isArray(v.punkte)) return null;
  const stand: Partial<Record<KernPunktId, KernEintrag>> = {};
  for (const e of v.punkte.slice(0, 50)) {
    if (!istObjekt(e) || !enthaelt(KERN_PUNKTE, e.id) || !enthaelt(STUFEN, e.stufe) || stand[e.id]) continue;
    const text = satz(e.text, "");
    if (text) stand[e.id] = { stufe: e.stufe, text };
  }
  return stand;
}

/** Manifest vom Server: Text und Signatur (Base64) werden nur an die App gereicht, die Oberfläche liest sie nicht. */
export function pruefeManifest(v: unknown): Manifest | null {
  if (!istObjekt(v) || typeof v.manifest !== "string" || typeof v.signatur !== "string") return null;
  if (!v.manifest || v.manifest.length > MANIFEST_MAX || !RE_SIGNATUR.test(v.signatur)) return null;
  return { manifest: v.manifest, signatur: v.signatur };
}

/** Status der App ({ ok: true, eingerichtet, kennung, stufe, tunnel, hostUmgebung } oder { ok: false, text }). */
export function pruefeAppStatus(v: unknown): AppStatus {
  if (!istObjekt(v)) return { ok: false, text: T_APP_STUMM };
  if (v.ok !== true) return { ok: false, text: satz(v.text, T_APP_STUMM) };
  return { ok: true, tunnel: enthaelt(TUNNEL, v.tunnel) ? v.tunnel : "unbekannt", host: enthaelt(HOST, v.hostUmgebung) ? v.hostUmgebung : null };
}

/** Antwort auf update.pruefen: nur mit ok === true, gültiger Version und neuer als Wahrheitswert gilt sie als bestätigt. */
export function pruefeUpdatePruefung(v: unknown): UpdatePruefung {
  if (istObjekt(v) && v.ok === true && istVersion(v.version) && typeof v.neuer === "boolean") {
    return { ok: true, version: v.version, neuer: v.neuer };
  }
  return { ok: false, text: satz(istObjekt(v) && v.ok === false ? v.text : undefined, T_PRUEFUNG_WEG) };
}

/** Antwort auf update.installieren. */
export function pruefeInstallation(v: unknown): UpdateInstallation {
  if (istObjekt(v) && v.ok === true) return { ok: true };
  return { ok: false, text: satz(istObjekt(v) ? v.text : undefined, T_INSTALL_WEG), abgebrochen: istObjekt(v) && v.abgebrochen === true };
}

/** Punkt App-Version. Ein Update-Angebot nur, wenn die App das Manifest bestätigt hat und die Version neuer ist. */
export function appVersionPunkt(version: unknown, update: UpdateStand): Punkt {
  if (!istVersion(version)) return punkt("app", "rot", T_UPDATE_EMPFOHLEN);
  switch (update.art) {
    case "ohne_pruefung":
      return punkt("app", "gruen", `Version ${version}.`);
    case "kein_angebot":
      return punkt("app", "gruen", `Version ${version}. Der Server bietet noch kein Update an.`);
    case "unbekannt":
      return punkt("app", "hinweis", `Version ${version}. Ob es ein Update gibt, lässt sich gerade nicht prüfen.`);
    case "geprueft": {
      const e = update.ergebnis;
      if (!e.ok) return punkt("app", "rot", e.text);
      if (!e.neuer) return punkt("app", "gruen", `Version ${version}, aktuell.`);
      const angebot: UpdateAngebot = { version: e.version, manifest: update.manifest.manifest, signatur: update.manifest.signatur };
      return { ...punkt("app", "rot", `Update auf Version ${e.version} verfügbar.`), update: angebot };
    }
  }
}

/** Punkt Host-Umgebung (desktop/host-umgebung.js). Ohne Angabe (ältere App) ein Hinweis statt eines falschen Alarms. */
export function hostPunkt(status: AppStatus | null): Punkt {
  if (!status || (status.ok && status.host === null)) return punkt("host", "hinweis", T_HOST_ALT);
  if (!status.ok) return punkt("host", "rot", status.text);
  if (status.host === "bereit") return punkt("host", "gruen", "Die Python-Umgebung für die PC-Steuerung ist bereit.");
  if (status.host === "entwickler") return punkt("host", "gruen", "Entwicklerbetrieb, die App nutzt die Python-Umgebung des Arbeitsbaums.");
  return punkt("host", "rot", T_HOST_FEHLT);
}

/** Punkt Tunnel: bereit nur, wenn die App verbunden (oder selbst Host) meldet und der Kern den Tunnel des eigenen Geräts bestätigt. */
export function tunnelPunkt(status: AppStatus | null, kern: KernEintrag | undefined): Punkt {
  const app = status?.ok ? status.tunnel : null;
  if ((app === "verbunden" || app === "host") && kern?.stufe === "gruen") {
    return punkt("tunnel", "gruen", app === "host" ? "Dieser PC ist selbst der Host, kein Tunnel nötig." : "Der Tunnel zu W.A.I.S. steht.");
  }
  return punkt("tunnel", "rot", T_TUNNEL);
}

/** Punkt Mikrofon: Windows-Datenschutz für Desktop-Apps (systemPreferences.getMediaAccessStatus), nur "granted" ist bereit. */
export function mikrofonPunkt(status: unknown): Punkt {
  return status === "granted" ? punkt("mikrofon", "gruen", "Windows erlaubt W.A.I.S. das Mikrofon.") : punkt("mikrofon", "rot", T_MIKRO);
}

/** Punkte aus Kern (null: nicht erreichbar) und App (null: Browser ohne Brücke) in der Reihenfolge der Tabelle 4.3. */
export function zusammenfuehren({ kern, app }: { kern: KernStand | null; app: AppStand | null }): Punkt[] {
  const punkte: Partial<Record<PunktId, Punkt>> = { anmeldung: punkt("anmeldung", "gruen", T_ANMELDUNG) };
  if (!kern) punkte.kern = punkt("kern", "rot", T_KERN);
  for (const id of KERN_PUNKTE) {
    const e = kern?.[id];
    if (e && id !== "tunnel") punkte[id] = punkt(id, e.stufe, e.text);
  }
  if (app) {
    punkte.app = appVersionPunkt(app.version, app.update);
    punkte.host = hostPunkt(app.status);
    punkte.tunnel = tunnelPunkt(app.status, kern?.tunnel);
    punkte.mikrofon = mikrofonPunkt(app.mikrofon);
  } else {
    for (const id of APP_PUNKTE) punkte[id] = punkt(id, "hinweis", T_NUR_APP);
  }
  return PUNKT_REIHENFOLGE.flatMap((id) => punkte[id] ?? []);
}

export const offenePunkte = (punkte: readonly Punkt[]): number => punkte.filter((p) => p.stufe === "rot").length;

/** Eine Zeile über der Liste; Hinweise zählen nicht als offen. */
export function zusammenfassung(punkte: readonly Punkt[]): string {
  const offen = offenePunkte(punkte);
  if (offen === 0) return "Alles bereit.";
  return offen === 1 ? "Noch 1 Punkt offen." : `Noch ${offen} Punkte offen.`;
}

/** Wie lange "Erneut prüfen" noch gesperrt ist (0: jetzt erlaubt); letzte ist der Zeitpunkt des letzten Klicks. */
export function erneutWartezeit(letzte: number | null, jetzt: number): number {
  return letzte === null ? 0 : drosselWartezeit(jetzt - letzte, PRUEF_ABSTAND_MS);
}

/** Punkt App-Version nach dem Versuch zu installieren: abgebrochen bleibt alles, sonst kein Knopf mehr. */
export function nachInstallation(alt: Punkt, erg: UpdateInstallation): Punkt {
  if (!erg.ok && erg.abgebrochen) return alt;
  if (erg.ok) return punkt(alt.id, "hinweis", "Die App installiert das Update und startet danach neu.");
  return punkt(alt.id, "rot", erg.text);
}

/** Update starten. Das Token wird erst hier geholt und geht nur an die App, nie in ein Ergebnis. Wirft nie. */
export async function updateInstallieren(o: {
  update: UpdateBruecke | undefined;
  angebot: UpdateAngebot;
  token: () => Promise<string | null>;
}): Promise<UpdateInstallation> {
  if (!o.update) return { ok: false, text: T_OHNE_APP, abgebrochen: false };
  let token: string | null = null;
  try {
    token = await o.token();
  } catch {
    token = null;
  }
  if (!token) return { ok: false, text: T_ANMELDUNG_WEG, abgebrochen: false };
  try {
    return pruefeInstallation(await o.update.installieren({ manifest: o.angebot.manifest, signatur: o.angebot.signatur, token }));
  } catch {
    return { ok: false, text: T_INSTALL_WEG, abgebrochen: false };
  }
}

/** Eine Frage an die App mit Frist; undefined bei Fehler, fehlender Funktion oder ohne Antwort in der Frist. */
function mitFrist(frage: (() => Promise<unknown>) | null, ms: number): Promise<unknown> {
  if (!frage) return Promise.resolve(undefined);
  return new Promise((fertig) => {
    const uhr = setTimeout(() => fertig(undefined), ms);
    const ende = (v: unknown) => {
      clearTimeout(uhr);
      fertig(v);
    };
    try {
      Promise.resolve(frage()).then(ende, () => ende(undefined));
    } catch {
      ende(undefined);
    }
  });
}

/** HTTP-Status eines KernFehler (lib/kernApi.ts) oder null. */
function fehlerStatus(e: unknown): number | null {
  const status = typeof e === "object" && e !== null ? (e as { status?: unknown }).status : undefined;
  return typeof status === "number" ? status : null;
}

async function kernStandHolen(kernJson: KernJson): Promise<KernStand | null> {
  try {
    return pruefeKernStand(await kernJson("/einrichtung/stand"));
  } catch {
    return null;
  }
}

async function updateStandHolen(b: PrueflisteBruecke, kernJson: KernJson, frist: number): Promise<UpdateStand> {
  const update = b.update;
  if (!istVersion(b.version) || !update) return { art: "ohne_pruefung" };
  let manifest: Manifest | null;
  try {
    manifest = pruefeManifest(await kernJson("/installer"));
  } catch (e) {
    return fehlerStatus(e) === 404 ? { art: "kein_angebot" } : { art: "unbekannt" };
  }
  if (!manifest) return { art: "unbekannt" };
  const anfrage = { manifest: manifest.manifest, signatur: manifest.signatur };
  const ergebnis = pruefeUpdatePruefung(await mitFrist(() => update.pruefen(anfrage), frist));
  return { art: "geprueft", manifest, ergebnis };
}

async function appStandHolen(b: PrueflisteBruecke, kernJson: KernJson, frist: number): Promise<AppStand> {
  const geraet = b.geraet;
  const mikrofon = b.mikrofonStatus;
  const [status, mikro, update] = await Promise.all([
    geraet ? mitFrist(() => geraet.status(), frist).then(pruefeAppStatus) : Promise.resolve(null),
    mitFrist(mikrofon ? () => mikrofon() : null, frist),
    updateStandHolen(b, kernJson, frist),
  ]);
  return { version: b.version, status, mikrofon: mikro, update };
}

/** Prüfliste laden: Kern und App zugleich. Wirft nie; was nicht antwortet, steht als offener Punkt oder Hinweis da. */
export async function prueflisteLaden(o: {
  kernJson: KernJson;
  bruecke: PrueflisteBruecke | null | undefined;
  fristMs?: number;
}): Promise<Punkt[]> {
  const frist = o.fristMs ?? FRIST_BRUECKE_MS;
  const [kern, app] = await Promise.all([
    kernStandHolen(o.kernJson),
    o.bruecke ? appStandHolen(o.bruecke, o.kernJson, frist) : Promise.resolve(null),
  ]);
  return zusammenfuehren({ kern, app });
}
