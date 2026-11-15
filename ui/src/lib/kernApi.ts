"use client";

import { merkeAbmeldeGrund } from "@/lib/anmeldung";
import { betriebsartAktuell, kernUrl } from "@/lib/betriebsart";
import { accessToken, getSupabase } from "@/lib/supabase";
import { dateiPruefen } from "@/lib/teilenHilfe";

export * from "@/lib/teilenHilfe";

/**
 * Aufrufe an die Schnittstellen des Kerns unter /wamo/api (voice-core/wamo_api.py): Hinweise, geteilte Arbeit,
 * Dateien. Ziel ist der Kern der aktuellen Betriebsart (Büro oder Unterwegs, beide stehen in der CSP), angemeldet mit
 * dem Token der Sitzung. Das Token geht nur an https oder an Loopback. Keine Cookies, kein Cache, keine Umleitungen.
 * Die Zeitgrenze gilt einschließlich Lesen der Antwort. Bei 401 einmal das Token erneuern; lässt es sich nicht
 * erneuern oder meldet der Kern eine zu alte Anmeldung, wird wie bei "sitzung_beendet" lokal abgemeldet (die
 * Anmeldemaske zeigt den Grund). Fehler kommen als KernFehler mit dem Text des Kerns (ohne interne Details).
 */

export class KernFehler extends Error {
  constructor(
    readonly status: number,
    text: string,
    /** maschinenlesbarer Grund, wenn der Kern einen mitschickt (zum Beispiel zweiter_faktor_zu_alt) */
    readonly code: string | null = null,
  ) {
    super(text);
  }
}

const ZEITLIMIT_MS = 20_000;
const ZEITLIMIT_DATEI_MS = 150_000;
/** Zeitgrenze für große Dateien (Installer, etwa 117 MB) einschließlich Lesen */
const ZEITLIMIT_STROM_MS = 600_000;
const ABGEBROCHEN = "Abgebrochen";
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);
const ABGELAUFEN = "Die Anmeldung ist abgelaufen. Bitte neu anmelden.";

function basisUrl(): string {
  const roh = kernUrl(betriebsartAktuell());
  try {
    const u = new URL(roh);
    if (u.protocol === "https:" || (u.protocol === "http:" && LOOPBACK.has(u.hostname))) return u.origin;
  } catch {
    // ungültig: unten abgelehnt
  }
  throw new KernFehler(0, "Kein sicherer Kern eingerichtet");
}

/** Ursprung des Kerns (https oder Loopback) für Aufrufe, die NICHT unter /wamo/api liegen, zum Beispiel die Freigabe-Route des Ankers. */
export function kernBasis(): string {
  return basisUrl();
}

async function frischesToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  try {
    const { data, error } = await supabase.auth.refreshSession();
    return error ? null : (data.session?.access_token ?? null);
  } catch {
    return null;
  }
}

function abmelden(grund: string) {
  merkeAbmeldeGrund(grund);
  void getSupabase()?.auth.signOut({ scope: "local" }).catch(() => undefined);
}

async function fehlerAus(antwort: Response): Promise<KernFehler> {
  let text = `Fehler ${antwort.status}`;
  let code: string | null = null;
  try {
    const daten: unknown = await antwort.json();
    const detail = (daten as { detail?: unknown })?.detail;
    if (typeof detail === "string" && detail) text = detail.slice(0, 200);
    const kennung = (daten as { code?: unknown })?.code;
    if (typeof kennung === "string" && /^[a-z0-9_]{1,40}$/.test(kennung)) code = kennung;
  } catch {
    // kein JSON: Standardtext
  }
  return new KernFehler(antwort.status, text, code);
}

/** abbruch: optionales Signal von außen (Knopf "Abbrechen"); es endet mit KernFehler(0, "Abgebrochen"), nie als Zeitüberschreitung. */
async function anfrage<T>(
  pfad: string,
  init: RequestInit,
  lesen: (antwort: Response) => Promise<T>,
  zeitlimit = ZEITLIMIT_MS,
  abbruch?: AbortSignal,
): Promise<T> {
  const basis = basisUrl();
  for (let versuch = 0; versuch < 2; versuch++) {
    if (abbruch?.aborted) throw new KernFehler(0, ABGEBROCHEN);
    const token = versuch === 0 ? await accessToken() : await frischesToken();
    if (!token) break;
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    const steuerung = new AbortController();
    const uhr = setTimeout(() => steuerung.abort(), zeitlimit);
    const abbrechen = () => steuerung.abort();
    abbruch?.addEventListener("abort", abbrechen);
    if (abbruch?.aborted) steuerung.abort(); // während des Tokens abgebrochen: das Ereignis ist schon vorbei
    try {
      const antwort = await fetch(`${basis}/wamo/api${pfad}`, {
        ...init,
        headers,
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: steuerung.signal,
      });
      if (antwort.status === 401 && versuch === 0) continue; // einmal mit erneuertem Token
      if (antwort.status === 401) {
        // Token frisch und trotzdem abgelehnt: nur bei zu alter Anmeldung abmelden (sonst ist der Kern falsch
        // eingerichtet, das löst eine neue Anmeldung nicht)
        let code: unknown = null;
        let detail = ABGELAUFEN;
        try {
          const daten = (await antwort.json()) as { code?: unknown; detail?: unknown };
          code = daten?.code;
          if (typeof daten?.detail === "string" && daten.detail) detail = daten.detail.slice(0, 200);
        } catch {
          // kein JSON
        }
        if (code === "anmeldung_zu_alt") abmelden(detail);
        throw new KernFehler(401, detail);
      }
      if (!antwort.ok) throw await fehlerAus(antwort);
      return await lesen(antwort); // auch das Lesen der Antwort liegt in der Zeitgrenze
    } catch (e) {
      if (e instanceof KernFehler) throw e;
      if (abbruch?.aborted) throw new KernFehler(0, ABGEBROCHEN);
      throw new KernFehler(0, steuerung.signal.aborted ? "Zeitüberschreitung" : "Kern nicht erreichbar");
    } finally {
      clearTimeout(uhr);
      abbruch?.removeEventListener("abort", abbrechen);
    }
  }
  abmelden(ABGELAUFEN);
  throw new KernFehler(401, ABGELAUFEN);
}

/** JSON lesen oder senden (body wird als JSON verschickt). Die Antwort ist ungeprüft: Aufrufer prüfen mit lib/teilenHilfe. */
export async function kernJson(pfad: string, methode: "GET" | "POST" | "PUT" = "GET", body?: unknown): Promise<unknown> {
  const init: RequestInit = { method: methode };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  return anfrage(pfad, init, (a) => a.json() as Promise<unknown>);
}

/** Datei hochladen (Rohdaten, Name im Header X-Dateiname). Prüft Größe und Typ vorher wie der Kern. */
export async function kernDateiSenden(pfad: string, datei: File): Promise<unknown> {
  const fehler = dateiPruefen(datei);
  if (fehler) throw new KernFehler(400, fehler);
  return anfrage(
    pfad,
    {
      method: "POST",
      body: datei,
      headers: { "Content-Type": "application/octet-stream", "X-Dateiname": encodeURIComponent(datei.name) },
    },
    (a) => a.json() as Promise<unknown>,
    ZEITLIMIT_DATEI_MS,
  );
}

/** Fortschritt eines gestreamten Downloads: geladene Bytes und die angekündigte Größe (null, wenn der Kern keine nennt). */
export type Fortschritt = (geladen: number, gesamt: number | null) => void;

const ZU_GROSS = "Die Datei ist größer als angekündigt.";

/**
 * Antwort in Stücken lesen und den Fortschritt melden. Mit bekannter Länge (Content-Length) landen die Bytes direkt in
 * einem Puffer dieser Größe, sonst in Stücken, die am Ende zusammengesetzt werden. Kommen mehr Bytes als angekündigt
 * (zum Beispiel komprimiert übertragen), geht es in Stücken weiter. Mehr als hoechstens Bytes bricht ab.
 */
async function stromLesen(
  antwort: Response,
  hoechstens: number,
  onFortschritt?: Fortschritt,
): Promise<Uint8Array<ArrayBuffer>> {
  const angegeben = Number(antwort.headers.get("Content-Length") ?? "");
  const gesamt = Number.isSafeInteger(angegeben) && angegeben > 0 ? angegeben : null;
  if (gesamt !== null && gesamt > hoechstens) {
    await antwort.body?.cancel().catch(() => undefined);
    throw new KernFehler(413, ZU_GROSS);
  }
  onFortschritt?.(0, gesamt);
  const leser = antwort.body?.getReader();
  if (!leser) {
    const alles = new Uint8Array(await antwort.arrayBuffer());
    if (alles.byteLength > hoechstens) throw new KernFehler(413, ZU_GROSS);
    onFortschritt?.(alles.byteLength, gesamt);
    return alles;
  }
  let puffer: Uint8Array<ArrayBuffer> | null = gesamt !== null ? new Uint8Array(gesamt) : null;
  const stuecke: Uint8Array[] = [];
  let geladen = 0;
  for (;;) {
    const { done, value } = await leser.read();
    if (done) break;
    if (geladen + value.byteLength > hoechstens) {
      await leser.cancel().catch(() => undefined);
      throw new KernFehler(413, ZU_GROSS);
    }
    if (puffer && geladen + value.byteLength > puffer.byteLength) {
      stuecke.push(puffer.subarray(0, geladen)); // mehr als angekündigt: ab hier in Stücken
      puffer = null;
    }
    if (puffer) puffer.set(value, geladen);
    else stuecke.push(value);
    geladen += value.byteLength;
    onFortschritt?.(geladen, gesamt);
  }
  // kürzer als angekündigt: nur der gelesene Teil (der Aufrufer prüft die Größe gegen das Manifest)
  if (puffer) return geladen === puffer.byteLength ? puffer : puffer.subarray(0, geladen);
  const ganz = new Uint8Array(geladen);
  let pos = 0;
  for (const s of stuecke) {
    ganz.set(s, pos);
    pos += s.byteLength;
  }
  return ganz;
}

/**
 * Große Datei gestreamt laden (Installer, lib/installerApi.ts), mit denselben Regeln wie jede Anfrage an den Kern (Token,
 * Erneuerung bei 401, kein Cache, keine Cookies, keine Umleitung). Zeitgrenze 10 Minuten einschließlich Lesen, Abbruch über
 * signal (endet mit KernFehler(0, "Abgebrochen")). hoechstens: mehr Bytes nimmt die Oberfläche nicht an (413). Die Bytes
 * bleiben im Speicher des Aufrufers; hier wird nichts gespeichert oder angeboten.
 */
export async function kernDateiStrom(
  pfad: string,
  o: { hoechstens: number; onFortschritt?: Fortschritt; signal?: AbortSignal },
): Promise<Uint8Array<ArrayBuffer>> {
  return anfrage(pfad, {}, (a) => stromLesen(a, o.hoechstens, o.onFortschritt), ZEITLIMIT_STROM_MS, o.signal);
}

/** Datei herunterladen und als Download anbieten (immer als Datei, nie im Fenster geöffnet). */
export async function kernDateiHolen(pfad: string, name: string): Promise<void> {
  const blob = await anfrage(pfad, {}, (a) => a.blob(), ZEITLIMIT_DATEI_MS);
  const url = URL.createObjectURL(new Blob([blob], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
