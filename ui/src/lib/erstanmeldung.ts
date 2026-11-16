import { ANZEIGENAME } from "./anzeigename.ts";

/**
 * Erstanmeldung (Planpapier docs/ausrollen-neue-nutzer.md, 3 und 4.1): Wer ein Startpasswort bekommen hat, ändert es nach dem
 * zweiten Faktor, bevor irgendetwas anderes geht. Durchgesetzt wird das im Kern (voice-core/erstanmeldung_api.py, Zugangskontrolle) und
 * in der Datenbank; die Oberfläche führt nur durch den Ablauf. Dieses Modul ist rein (ohne React, ohne Browserzwang, nur
 * relative Importe), damit es sich mit node:test prüfen lässt (erstanmeldung.test.ts).
 *
 * Der Stand kommt von GET /wamo/api/erstanmeldung. Jede andere Antwort (403 eines Laborprofils, 404 eines alten Kerns, 503, Netzfehler,
 * unbekannter Wert) heißt "keine": Der Kern setzt die Sperre selbst durch, die Oberfläche entscheidet nichts, was Sicherheit wäre.
 * Passwörter stehen hier nie in einer Meldung, einem Log oder einem Speicher.
 */

export type ErstanmeldungStand = "keine" | "offen" | "abgelaufen" | "erledigt";

const STAENDE: readonly string[] = ["keine", "offen", "abgelaufen", "erledigt"];

export function istStand(wert: unknown): wert is ErstanmeldungStand {
  return typeof wert === "string" && STAENDE.includes(wert);
}

/** Mindestlänge in Zeichen (GOTRUE_PASSWORD_MIN_LENGTH am Server) und Obergrenze in Bytes (bcrypt schneidet danach ab). */
export const MIN_ZEICHEN = 12;
export const MAX_BYTES = 72;

/** Die Codes, mit denen der Kern 403-Antworten der Erstanmeldung kennzeichnet. */
export const CODE_WECHSEL_NOETIG = "passwort_wechsel_noetig";
export const CODE_ABGELAUFEN = "startpasswort_abgelaufen";
export type SperrCode = typeof CODE_WECHSEL_NOETIG | typeof CODE_ABGELAUFEN;

export const SATZ_ABGELAUFEN = "Dein Startpasswort ist abgelaufen. Bitte melde dich bei Niko.";

/** Kleiner Warnsatz auf dem Bildschirm, der den Code einer schon eingerichteten App abfragt (nicht bei der Einrichtung mit QR-Code). */
export const WARNSATZ_CODE = `Fragt ${ANZEIGENAME} nach einem Code, obwohl du noch keine App eingerichtet hast, melde dich sofort bei Niko.`;

/** Zeitgrenze der Abfrage in Millisekunden; bleibt die Antwort aus, gilt "keine" und die Tür öffnet wie bisher. */
export const ZEITLIMIT_MS = 8_000;

// ---------- Stand vom Kern ----------

/** Was standLaden von fetch braucht (in Tests ersetzbar). */
export type Holen = (url: string, init?: RequestInit) => Promise<Response>;

/** Der 403-Code einer Kernantwort, wenn er einer der beiden der Erstanmeldung ist, sonst null. */
export function sperrCodeAus(daten: unknown): SperrCode | null {
  if (typeof daten !== "object" || daten === null) return null;
  const code = (daten as { code?: unknown }).code;
  return code === CODE_WECHSEL_NOETIG || code === CODE_ABGELAUFEN ? code : null;
}

/** Satz, wenn die App später (nicht an der Tür) ein 403 mit passwort_wechsel_noetig bekommt: Die Person meldet sich neu an, die Tür führt dann zum Wechsel. */
export const SATZ_STARTPASSWORT_AENDERN = "Bitte ändere zuerst dein Startpasswort. Melde dich dafür neu an.";

/** Der Satz des Kerns zu passwort_wechsel_noetig (voice-core/auth_gate.py); beim Start über client-js kommt nur er an, nicht der Code. */
const SATZ_KERN_WECHSEL = "Bitte ändere zuerst dein Startpasswort.";

/**
 * Satz für eine Abmeldung, wenn eine Antwort des Kerns die Erstanmeldung meint: 403 mit dem Code passwort_wechsel_noetig oder
 * startpasswort_abgelaufen, oder (ohne Code, beim Start über client-js, wo der Satz in einem längeren Text stehen kann) mit dem Satz des Kerns. Sonst null (dann gilt der
 * gewohnte Satz zum Profil).
 */
export function sperrSatzAus(status: number | undefined, code: string | null | undefined, detail?: string | null): string | null {
  if (status !== 403) return null;
  const text = typeof detail === "string" ? detail : "";
  if (code === CODE_ABGELAUFEN || (!code && text.includes(SATZ_ABGELAUFEN))) return SATZ_ABGELAUFEN;
  if (code === CODE_WECHSEL_NOETIG || (!code && text.includes(SATZ_KERN_WECHSEL))) return SATZ_STARTPASSWORT_AENDERN;
  return null;
}

/** Stand, den ein 403 mit Code der Erstanmeldung ausdrückt (Status und Code getrennt, so liefert sie KernFehler). */
export function sperrStandAusCode(status: number, code: string | null | undefined): "offen" | "abgelaufen" | null {
  if (status !== 403) return null;
  if (code === CODE_WECHSEL_NOETIG) return "offen";
  if (code === CODE_ABGELAUFEN) return "abgelaufen";
  return null;
}

/** Wie sperrStandAusCode, aber mit dem JSON-Rumpf der Antwort. */
export function sperrStandAus(status: number, daten: unknown): "offen" | "abgelaufen" | null {
  return sperrStandAusCode(status, sperrCodeAus(daten));
}

/** Pause vor dem Wiederholungsversuch in Millisekunden. */
export const PAUSE_WIEDERHOLUNG_MS = 250;

/** Ein Versuch: der Stand und ob sich ein Wiederholen lohnt (Netzfehler und 5xx ja, jede sichere Antwort wie 403 und 404 nein). */
async function standVersuch(basis: string, token: string, holen: Holen, signal: AbortSignal): Promise<{ stand: ErstanmeldungStand; wiederholen: boolean }> {
  try {
    const antwort = await holen(`${basis}/wamo/api/erstanmeldung`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
    });
    if (antwort.status >= 500) return { stand: "keine", wiederholen: true };
    let daten: unknown = null;
    try {
      daten = await antwort.json();
    } catch {
      // kein JSON: unten "keine"
    }
    if (antwort.status === 403) return { stand: sperrStandAus(403, daten) ?? "keine", wiederholen: false };
    if (!antwort.ok || typeof daten !== "object" || daten === null) return { stand: "keine", wiederholen: false };
    const stand = (daten as { stand?: unknown }).stand;
    return { stand: istStand(stand) ? stand : "keine", wiederholen: false };
  } catch {
    return { stand: "keine", wiederholen: !signal.aborted }; // Netz oder Umleitung: einmal wiederholen; Zeitgrenze: nicht mehr
  }
}

/**
 * Stand der Erstanmeldung beim Kern. basis ist der Ursprung des Kerns (https oder Loopback, lib/kernApi.ts), token das
 * Zugriffstoken der Sitzung. Wirft nie: alles außer einer gültigen Antwort heißt "keine". Bei Netzfehler oder 5xx gibt es
 * genau einen Wiederholungsversuch (damit ein kurzer Aussetzer die Sperre nicht verdeckt); die Zeitgrenze gilt für beide
 * Versuche zusammen. Bei 403 und 404 (Laborprofil, alter Kern) wird nicht wiederholt.
 */
export async function standLaden(
  basis: string,
  token: string,
  holen: Holen = (url, init) => fetch(url, init),
  zeitlimitMs: number = ZEITLIMIT_MS,
  pauseMs: number = PAUSE_WIEDERHOLUNG_MS,
): Promise<ErstanmeldungStand> {
  if (!basis || !token) return "keine";
  const steuerung = new AbortController();
  const uhr = setTimeout(() => steuerung.abort(), zeitlimitMs);
  try {
    const erster = await standVersuch(basis, token, holen, steuerung.signal);
    if (!erster.wiederholen || steuerung.signal.aborted) return erster.stand;
    await new Promise<void>((weiter) => setTimeout(weiter, pauseMs));
    if (steuerung.signal.aborted) return "keine";
    return (await standVersuch(basis, token, holen, steuerung.signal)).stand;
  } finally {
    clearTimeout(uhr);
  }
}

// ---------- Tür ----------

export type TuerEntscheidung = "app" | "ablauf" | "abgelaufen";

/**
 * Was die Tür nach dem zweiten Faktor zeigt. offen: der Ablauf. abgelaufen: nur der Satz. Nach dem Passwortwechsel steht der
 * Stand auf erledigt; solange der Merker des begonnenen Ablaufs steht (die späteren Schritte sind noch nicht durch), geht der
 * Ablauf bei einem Neuladen weiter. Ohne bestätigten Stand (keine) bleibt es bei der App.
 */
export function tuerEntscheidung(stand: ErstanmeldungStand, ablaufBegonnen: boolean): TuerEntscheidung {
  if (stand === "abgelaufen") return "abgelaufen";
  if (stand === "offen") return "ablauf";
  return stand === "erledigt" && ablaufBegonnen ? "ablauf" : "app";
}

// ---------- Passwort ----------

/** Anzahl der Zeichen (Codepunkte), damit Umlaute und Emoji je als eines zählen. */
function zeichen(text: string): number {
  return Array.from(text).length;
}

function bytes(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** Lokale Prüfung vor dem Wechsel. null: in Ordnung, sonst ein deutscher Satz. Leerzeichen am Rand gehören zum Passwort. */
export function passwortPruefen(neu: string, wiederholung: string): string | null {
  if (neu === "") return "Bitte gib ein neues Passwort ein.";
  if (zeichen(neu) < MIN_ZEICHEN) return `Das neue Passwort braucht mindestens ${MIN_ZEICHEN} Zeichen.`;
  if (bytes(neu) > MAX_BYTES) {
    return `Das neue Passwort ist zu lang (höchstens ${MAX_BYTES} Bytes, Umlaute und Sonderzeichen zählen mehr als ein Byte).`;
  }
  if (neu !== wiederholung) return "Die beiden Passwörter sind nicht gleich.";
  return null;
}

/** Zeitgrenze des Wechsels in Millisekunden (der Kern ruft die Anmeldeschnittstelle auf, das dauert länger als die Abfrage des Stands). */
export const ZEITLIMIT_PASSWORT_MS = 20_000;

/** Ergebnis des Wechsels über den Kern: ok mit dem Stand aus der Antwort, sonst Status und Code (null ohne Code, 0 bei Netz und Zeitgrenze). */
export type PasswortErgebnis = { ok: true; stand: ErstanmeldungStand } | { ok: false; status: number; code: string | null };

const CODE_FORM = /^[a-z0-9_]{1,40}$/;

/**
 * Passwort ändern über den Kern: POST /wamo/api/erstanmeldung/passwort mit {"passwort": ...} und Bearer. Der Pfad ist exakt, ohne Query
 * (der Kern lehnt jede ab, auch eine leere). Caddy lässt PUT auf die Anmeldeschnittstelle nicht durch, deshalb geht der Wechsel nicht
 * direkt vom Browser an GoTrue. Wirft nie. Das Passwort steht nur im Rumpf der Anfrage, nie im Ergebnis, nie in einem Log.
 */
export async function passwortSetzen(
  basis: string,
  token: string,
  passwort: string,
  holen: Holen = (url, init) => fetch(url, init),
  zeitlimitMs: number = ZEITLIMIT_PASSWORT_MS,
): Promise<PasswortErgebnis> {
  if (!basis || !token) return { ok: false, status: 401, code: "sitzung_ungueltig" };
  const steuerung = new AbortController();
  const uhr = setTimeout(() => steuerung.abort(), zeitlimitMs);
  try {
    const antwort = await holen(`${basis}/wamo/api/erstanmeldung/passwort`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ passwort }),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal: steuerung.signal,
    });
    let daten: unknown = null;
    try {
      daten = await antwort.json();
    } catch {
      // kein JSON: Standard unten
    }
    const feld = (name: string): unknown =>
      typeof daten === "object" && daten !== null ? (daten as Record<string, unknown>)[name] : undefined;
    if (antwort.ok) {
      const stand = feld("stand");
      return { ok: true, stand: istStand(stand) ? stand : "keine" };
    }
    const code = feld("code");
    return { ok: false, status: antwort.status, code: typeof code === "string" && CODE_FORM.test(code) ? code : null };
  } catch {
    return { ok: false, status: 0, code: null };
  } finally {
    clearTimeout(uhr);
  }
}

/** Was von einem Fehler des Wechsels gebraucht wird (Status und Code des Kerns; die GoTrue-Codes heißen dort gleich). */
export type AuthFehlerLike = { code?: string | null; status?: number | null; message?: string } | null | undefined;

/**
 * Was nach einem Fehler beim Wechsel passiert: anzeigen (Satz, Eingabe bleibt), code (zurück zur Code-Abfrage), neu_anmelden
 * (der Satz sagt es, die Person meldet sich ab und wieder an), pruefen (Satz zeigen und das Tor den Stand neu auswerten lassen),
 * abgelaufen (wie pruefen, das Tor zeigt dann den Satz zum abgelaufenen Startpasswort).
 */
export type PasswortFehler = { text: string; folge: "anzeigen" | "code" | "neu_anmelden" | "pruefen" | "abgelaufen" };

const SATZ_ALLGEMEIN = "Das Passwort konnte nicht geändert werden. Bitte versuche es noch einmal.";
const SATZ_ZU_OFT = "Zu viele Versuche, bitte in zehn Minuten noch einmal.";
const SATZ_ANMELDEDIENST = "Der Anmeldedienst ist gerade nicht erreichbar.";
const SATZ_NEU_ANMELDEN = "Bitte melde dich neu an, dann klappt der Wechsel.";

/** Übersetzt den Fehler des Wechsels in einen Satz. Die Meldung des Servers wird nie angezeigt (sie könnte Eingaben enthalten). */
export function passwortFehler(fehler: AuthFehlerLike): PasswortFehler {
  switch (fehler?.code) {
    case "same_password":
      return { text: "Das neue Passwort muss sich vom Startpasswort unterscheiden.", folge: "anzeigen" };
    case "weak_password":
      return {
        text: `Das Passwort ist zu schwach. Nimm mindestens ${MIN_ZEICHEN} Zeichen und nichts, das sich leicht erraten lässt.`,
        folge: "anzeigen",
      };
    case "passwort_ungueltig":
      return {
        text: `Das Passwort ist nicht zulässig. Es braucht mindestens ${MIN_ZEICHEN} Zeichen und höchstens ${MAX_BYTES} Bytes.`,
        folge: "anzeigen",
      };
    case "insufficient_aal":
      return { text: "Bitte bestätige zuerst mit einem frischen Code aus deiner Authenticator-App.", folge: "code" };
    case "reauthentication_needed":
    case "sitzung_ungueltig":
      return { text: SATZ_NEU_ANMELDEN, folge: "neu_anmelden" };
    case CODE_ABGELAUFEN:
      return { text: SATZ_ABGELAUFEN, folge: "abgelaufen" };
    case "kein_wechsel_noetig":
      return { text: "Ein Wechsel des Passworts ist nicht nötig.", folge: "pruefen" };
    case "zu_oft":
      return { text: SATZ_ZU_OFT, folge: "anzeigen" };
    case "anmeldedienst":
      return { text: SATZ_ANMELDEDIENST, folge: "anzeigen" };
  }
  if (fehler?.status === 429) return { text: SATZ_ZU_OFT, folge: "anzeigen" };
  if (fehler?.status === 502) return { text: SATZ_ANMELDEDIENST, folge: "anzeigen" };
  if (fehler?.status === 0) {
    return { text: "Anmeldeserver nicht erreichbar. Bist du im Büronetz oder per WireGuard verbunden?", folge: "anzeigen" };
  }
  return { text: SATZ_ALLGEMEIN, folge: "anzeigen" };
}

// ---------- Merker des begonnenen Ablaufs ----------

/** Der Merker liegt im sessionStorage (endet mit dem Tab) und enthält nie mehr als "1". */
export const ABLAUF_MERKER_PRAEFIX = "wamo-erstanmeldung-";

type MerkerSpeicher = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function sitzungsSpeicher(): MerkerSpeicher | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null; // gesperrter Speicher: dann ohne Merker
  }
}

function merkerSchluessel(userId: string): string | null {
  return userId ? `${ABLAUF_MERKER_PRAEFIX}${userId}` : null;
}

export function ablaufMerkerSetzen(userId: string, speicher: MerkerSpeicher | null = sitzungsSpeicher()): void {
  const schluessel = merkerSchluessel(userId);
  if (!schluessel || !speicher) return;
  try {
    speicher.setItem(schluessel, "1");
  } catch {
    // voll oder gesperrt: der Ablauf läuft trotzdem, nur ein Neuladen verliert die späteren Schritte
  }
}

export function ablaufMerkerGesetzt(userId: string, speicher: MerkerSpeicher | null = sitzungsSpeicher()): boolean {
  const schluessel = merkerSchluessel(userId);
  if (!schluessel || !speicher) return false;
  try {
    return speicher.getItem(schluessel) === "1";
  } catch {
    return false;
  }
}

/** Beim Abmelden: alle Merker dieser Art im Speicher entfernen (die Kennung der Person ist dann nicht mehr bekannt). Fremde Einträge bleiben. */
export function ablaufMerkerAlleLoeschen(speicher: (MerkerSpeicher & Partial<Pick<Storage, "key" | "length">>) | null = sitzungsSpeicher()): void {
  if (!speicher) return;
  try {
    const schluessel: string[] = [];
    for (let i = 0; i < (speicher.length ?? 0); i++) {
      const k = speicher.key?.(i);
      if (typeof k === "string" && k.startsWith(ABLAUF_MERKER_PRAEFIX)) schluessel.push(k);
    }
    for (const k of schluessel) speicher.removeItem(k);
  } catch {
    // gesperrt: nichts zu tun
  }
}

export function ablaufMerkerLoeschen(userId: string, speicher: MerkerSpeicher | null = sitzungsSpeicher()): void {
  const schluessel = merkerSchluessel(userId);
  if (!schluessel || !speicher) return;
  try {
    speicher.removeItem(schluessel);
  } catch {
    // gesperrt: nichts zu tun
  }
}
