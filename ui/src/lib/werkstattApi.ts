"use client";

import { accessToken, getSupabase } from "@/lib/supabase";
import { eigenerFehler, fehlerBild } from "@/lib/werkstattFehler";
import { eingabeZuRumpf, KARTEN_ID } from "@/lib/werkstattKarten";
import {
  alsAktionen,
  alsBetrieb,
  alsCheckliste,
  alsFreigabeKarte,
  alsIch,
  alsKarte,
  alsKartenListe,
  alsLaborStand,
  alsLatenz,
  alsPlaetze,
  alsProtokolle,
  alsPruefung,
  alsSitzungen,
  alsTermin,
  alsTermine,
  alsVeroeffentlicht,
  alsVersionen,
  alsZuordnung,
  istObj,
  SICHERE_ID,
} from "@/lib/werkstattParser";
import type {
  AktionZeile,
  Betrieb,
  ChecklisteEingabe,
  ChecklistePunkt,
  FehlerBild,
  FreigabeKarte,
  Ich,
  Karte,
  KartenEingabe,
  KartenListe,
  KartenVersion,
  LaborProfil,
  LatenzTag,
  Platz,
  ProtokollAntwort,
  ProtokollFilter,
  SitzungTag,
  Termin,
  TerminEingabe,
  Veroeffentlicht,
  Zuordnung,
  Pruefung,
} from "@/lib/werkstattTypen";

/**
 * Aufrufe an den Dienst wamo-werkstatt (docs/adminpanel-bauplan.md, Abschnitt 3): Basis ist NEXT_PUBLIC_WAMO_WERKSTATT_URL
 * (Standard https://192.168.178.136:55448), Pfad /werkstatt/api. Angemeldet wird mit dem Zugangstoken der Sitzung, das nur im
 * Header Authorization steht: nie in einer Adresse, nie im Zustand einer Komponente, nie in einem Fehlertext, nie im Speicher.
 * Das Token wird für jede Anfrage frisch gelesen. Das Ziel muss https sein (oder Loopback), ohne Zugangsdaten in der Adresse.
 * Keine Cookies, kein Cache, keine Umleitungen. Bei 401 einmal mit erneuertem Token. Fehler kommen als WerkstattFehler mit einem
 * klaren deutschen Satz (lib/werkstattFehler.ts); jede Antwort wird geprüft (lib/werkstattParser.ts), sonst gilt sie als unerwartet.
 */

export const WERKSTATT_STANDARD_URL = "https://192.168.178.136:55448";
const ZEITLIMIT_MS = 20_000;
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

export class WerkstattFehler extends Error {
  readonly status: number;
  readonly code: string;
  constructor(bild: FehlerBild) {
    super(bild.text);
    this.name = "WerkstattFehler";
    this.status = bild.status;
    this.code = bild.code;
  }
}

const fehler = (code: Parameters<typeof eigenerFehler>[0], detail?: string) => new WerkstattFehler(eigenerFehler(code, detail));

/** Ursprung der Werkstatt aus der Umgebung; wirft "nicht eingerichtet" bei einer unsicheren oder ungültigen Adresse. */
export function werkstattBasis(): string {
  const roh = process.env.NEXT_PUBLIC_WAMO_WERKSTATT_URL || WERKSTATT_STANDARD_URL;
  try {
    const u = new URL(roh);
    const sicher = u.protocol === "https:" || (u.protocol === "http:" && LOOPBACK.has(u.hostname));
    if (sicher && !u.username && !u.password) return u.origin;
  } catch {
    // ungültig: unten abgelehnt
  }
  throw fehler("nicht_eingerichtet");
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

type Abfrage = Record<string, string | number | undefined>;
type Optionen<T> = {
  methode?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  abfrage?: Abfrage;
  body?: unknown;
  signal?: AbortSignal;
  /** Prüft und setzt die Antwort um; null heißt "unerwartet" */
  lesen: (daten: unknown) => T | null;
};

async function fehlerAus(antwort: Response): Promise<WerkstattFehler> {
  let code: unknown = null;
  let text: unknown = null;
  try {
    const d: unknown = await antwort.json();
    if (istObj(d)) {
      code = d.code;
      text = d.text;
    }
  } catch {
    // kein JSON: der Satz kommt aus dem Status
  }
  return new WerkstattFehler(fehlerBild(antwort.status, code, text));
}

async function anfrage<T>(pfad: string, o: Optionen<T>): Promise<T> {
  const basis = werkstattBasis();
  const query = new URLSearchParams();
  for (const [name, wert] of Object.entries(o.abfrage ?? {})) if (wert !== undefined && wert !== "") query.set(name, String(wert));
  const suche = query.toString();
  const adresse = `${basis}/werkstatt/api${pfad}${suche ? `?${suche}` : ""}`;
  for (let versuch = 0; versuch < 2; versuch++) {
    if (o.signal?.aborted) throw fehler("abgebrochen");
    const token = versuch === 0 ? await accessToken() : await frischesToken();
    if (!token) break;
    if (o.signal?.aborted) throw fehler("abgebrochen"); // während des Tokens abgebrochen
    const headers = new Headers({ Authorization: `Bearer ${token}`, Accept: "application/json" });
    const init: RequestInit = { method: o.methode ?? "GET", headers, cache: "no-store", credentials: "omit", redirect: "error" };
    if (o.body !== undefined) {
      init.body = JSON.stringify(o.body);
      headers.set("Content-Type", "application/json");
    }
    const steuerung = new AbortController();
    const uhr = setTimeout(() => steuerung.abort(), ZEITLIMIT_MS);
    const abbrechen = () => steuerung.abort();
    o.signal?.addEventListener("abort", abbrechen);
    init.signal = steuerung.signal;
    try {
      const antwort = await fetch(adresse, init);
      if (antwort.status === 401 && versuch === 0) continue; // einmal mit erneuertem Token
      if (!antwort.ok) throw await fehlerAus(antwort);
      let daten: unknown = null;
      const rohtext = await antwort.text();
      if (rohtext) {
        try {
          daten = JSON.parse(rohtext);
        } catch {
          throw fehler("antwort");
        }
      }
      const wert = o.lesen(daten);
      if (wert === null) throw fehler("antwort");
      return wert;
    } catch (e) {
      if (e instanceof WerkstattFehler) throw e;
      if (o.signal?.aborted) throw fehler("abgebrochen");
      const aus = steuerung.signal.aborted ? "zeit" : "netz";
      // bei einem Schreibaufruf ist unklar, ob die Änderung angekommen ist
      throw fehler(aus, (o.methode ?? "GET") === "GET" ? undefined : "Ob die Änderung angekommen ist, siehst du nach dem Neuladen der Ansicht.");
    } finally {
      clearTimeout(uhr);
      o.signal?.removeEventListener("abort", abbrechen);
    }
  }
  throw new WerkstattFehler(fehlerBild(401, "nicht_angemeldet", null));
}

// ---------- Eingaben prüfen, bevor etwas gesendet wird ----------
function sichereId(id: string): string {
  if (!SICHERE_ID.test(id)) throw fehler("ungueltig");
  return encodeURIComponent(id);
}

function karteId(id: string): string {
  if (!KARTEN_ID.test(id)) throw fehler("ungueltig");
  return id;
}

function ganzImBereich(wert: number, von: number, bis: number): number {
  return Number.isFinite(wert) ? Math.min(bis, Math.max(von, Math.round(wert))) : von;
}

/** Löst eine Antwort ohne Inhalt oder mit beliebigem Inhalt als "geschafft" auf (Schreibaufrufe, deren Ergebnis die Ansicht neu lädt). */
const geschafft = (): true => true;
/** Manche Antworten verpacken den Wert: { termin: {...} } oder der Wert selbst. */
const auspacken = (d: unknown, name: string): unknown => (istObj(d) && name in d ? d[name] : d);

// ---------- Zugang und Betrieb ----------
export const ichLaden = (signal?: AbortSignal): Promise<Ich> => anfrage("/ich", { signal, lesen: alsIch });
export const betriebLaden = (signal?: AbortSignal): Promise<Betrieb> => anfrage("/betrieb", { signal, lesen: alsBetrieb });

// ---------- Dashboards ----------
export const sitzungenLaden = (tage: number, signal?: AbortSignal): Promise<SitzungTag[]> =>
  anfrage("/dashboard/sitzungen", { abfrage: { tage: ganzImBereich(tage, 1, 30) }, signal, lesen: alsSitzungen });
export const latenzLaden = (tage: number, signal?: AbortSignal): Promise<LatenzTag[]> =>
  anfrage("/dashboard/latenz", { abfrage: { tage: ganzImBereich(tage, 1, 30) }, signal, lesen: alsLatenz });
export const aktionenLaden = (tage: number, signal?: AbortSignal): Promise<AktionZeile[]> =>
  anfrage("/dashboard/aktionen", { abfrage: { tage: ganzImBereich(tage, 1, 30) }, signal, lesen: alsAktionen });

// ---------- Protokolle ----------
const MARKE = /^[a-z0-9_.@-]{1,60}$/;
const STUFE = /^[a-z]{1,20}$/;

export function protokolleLaden(filter: ProtokollFilter, signal?: AbortSignal): Promise<ProtokollAntwort> {
  // Ein Filter, der nicht passt, wird nie still weggelassen (die Ansicht zeigte sonst ungefiltert unter dem gewählten Filter).
  if ((filter.marke !== "" && !MARKE.test(filter.marke)) || (filter.stufe !== "" && !STUFE.test(filter.stufe))) throw fehler("ungueltig");
  return anfrage("/protokolle", {
    abfrage: { marke: filter.marke, stufe: filter.stufe, stunden: ganzImBereich(filter.stunden, 1, 168) },
    signal,
    lesen: alsProtokolle,
  });
}

// ---------- Labor-Planer ----------
export const laborStandLaden = (signal?: AbortSignal): Promise<LaborProfil[]> => anfrage("/labor/stand", { signal, lesen: alsLaborStand });
export const termineLaden = (signal?: AbortSignal): Promise<Termin[]> => anfrage("/labor/termine", { signal, lesen: alsTermine });

function terminRumpf(e: TerminEingabe): Record<string, unknown> {
  return {
    tag: e.tag,
    beginn: e.beginn,
    ende: e.ende,
    einwilligung_version: e.einwilligungVersion,
    status: e.status,
    aufbewahrung_bis: e.aufbewahrungBis,
  };
}

export const terminAnlegen = (e: TerminEingabe): Promise<{ termin: Termin | null }> =>
  anfrage("/labor/termine", { methode: "POST", body: terminRumpf(e), lesen: (d) => ({ termin: alsTermin(auspacken(d, "termin")) }) });
export const terminAendern = (id: string, e: TerminEingabe): Promise<{ termin: Termin | null }> =>
  anfrage(`/labor/termine/${sichereId(id)}`, { methode: "PUT", body: terminRumpf(e), lesen: (d) => ({ termin: alsTermin(auspacken(d, "termin")) }) });
export const terminLoeschen = (id: string): Promise<true> => anfrage(`/labor/termine/${sichereId(id)}`, { methode: "DELETE", lesen: geschafft });

export const plaetzeLaden = (terminId: string, signal?: AbortSignal): Promise<Platz[]> =>
  anfrage(`/labor/termine/${sichereId(terminId)}/plaetze`, { signal, lesen: alsPlaetze });
export const plaetzeSpeichern = (terminId: string, plaetze: readonly Platz[]): Promise<true> =>
  anfrage(`/labor/termine/${sichereId(terminId)}/plaetze`, {
    methode: "PUT",
    body: { plaetze: plaetze.map((p) => ({ platz: p.platz, zweck: p.zweck, kennung: p.kennung, gast: p.gast })) },
    lesen: geschafft,
  });

export const checklisteLaden = (terminId: string, signal?: AbortSignal): Promise<ChecklistePunkt[]> =>
  anfrage(`/labor/termine/${sichereId(terminId)}/checkliste`, { signal, lesen: alsCheckliste });
export const checklistePunktAnlegen = (terminId: string, e: ChecklisteEingabe): Promise<true> =>
  anfrage(`/labor/termine/${sichereId(terminId)}/checkliste`, { methode: "POST", body: { titel: e.titel, quelle: e.quelle, faellig: e.faellig }, lesen: geschafft });
export const checklisteUmschalten = (terminId: string, nr: number, erledigt: boolean): Promise<true> => {
  if (!Number.isSafeInteger(nr) || nr < 1) throw fehler("ungueltig"); // die Nummer beginnt bei 1 (nummer_lesen im Dienst)
  return anfrage(`/labor/termine/${sichereId(terminId)}/checkliste/${nr}`, { methode: "PATCH", body: { erledigt }, lesen: geschafft });
};

// ---------- Karten ----------
export const kartenLaden = (signal?: AbortSignal): Promise<KartenListe> => anfrage("/karten", { signal, lesen: alsKartenListe });
export const versionenLaden = (signal?: AbortSignal): Promise<KartenVersion[]> => anfrage("/karten/versionen", { signal, lesen: alsVersionen });
export const karteAnlegen = (e: KartenEingabe): Promise<{ karte: Karte | null }> =>
  anfrage("/karten", { methode: "POST", body: eingabeZuRumpf(e), lesen: (d) => ({ karte: alsKarte(auspacken(d, "karte")) }) });
export const karteAendern = (e: KartenEingabe): Promise<{ karte: Karte | null }> =>
  anfrage(`/karten/${karteId(e.id)}`, { methode: "PUT", body: eingabeZuRumpf(e), lesen: (d) => ({ karte: alsKarte(auspacken(d, "karte")) }) });
export const karteLoeschen = (id: string): Promise<true> => anfrage(`/karten/${karteId(id)}`, { methode: "DELETE", lesen: geschafft });

export const zuordnungLaden = (terminId: string, signal?: AbortSignal): Promise<Zuordnung> =>
  anfrage("/zuordnung", { abfrage: { termin: sichereId(terminId) }, signal, lesen: alsZuordnung });
export const zuordnungSpeichern = (terminId: string, zuordnung: Zuordnung): Promise<true> =>
  anfrage("/zuordnung", {
    methode: "PUT",
    abfrage: { termin: sichereId(terminId) },
    // Der Dienst will ein Objekt Platz (als Text) zu Kennungen (matrix_pruefen) und ersetzt die ganze Zuordnung des Termins:
    // Plätze ohne Karten fehlen darin.
    body: {
      zuordnung: Object.fromEntries(
        Object.entries(zuordnung)
          .filter(([, ids]) => ids.length > 0)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([platz, ids]) => [String(Number(platz)), ids.map(karteId).sort()]),
      ),
    },
    lesen: geschafft,
  });

// ---------- Veröffentlichen ----------
export const kartenPruefen = (): Promise<Pruefung> => anfrage("/karten/pruefen", { methode: "POST", body: {}, lesen: alsPruefung });
export const freigabeKarteAnlegen = (): Promise<FreigabeKarte> => anfrage("/karten/karte", { methode: "POST", body: {}, lesen: alsFreigabeKarte });
export const freigabeAusfuehren = (id: string): Promise<Veroeffentlicht> =>
  anfrage(`/karten/karte/${sichereId(id)}/ausfuehren`, { methode: "POST", body: {}, lesen: alsVeroeffentlicht });

/** Das Fehlerbild zu einem beliebigen Fehler eines Aufrufs (Anzeige in der Oberfläche). */
export function fehlerBildAus(e: unknown): FehlerBild {
  if (e instanceof WerkstattFehler) return { code: e.code, text: e.message, status: e.status };
  return eigenerFehler("netz");
}
