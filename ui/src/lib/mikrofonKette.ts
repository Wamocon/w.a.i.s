/**
 * Mikrofonkette im Protokoll (19.11.2026): Die Stimmerkennung bricht ein, wenn sich die Signalkette ändert (Mikrofon, Aufbereitung, Pegel).
 * Messung vom 19.11.2026: Mit Bluetooth-Kopfhörer lagen eigene Sätze mit dem Abdruck vom Laptop bei 0,2 bis 0,3, mit eigenem Abdruck bei
 * etwa 0,8. Die Aufnahme startet ohne eigene Vorgaben für Echounterdrückung, Rauschunterdrückung und Verstärkung (getUserMedia mit audio:
 * true), der Browser wählt seine Standardwerte, und das stand nirgends im Protokoll.
 *
 * Nach jedem Spurwechsel (Start, Gerätewechsel, neue Verbindung) liest die Oberfläche track.getSettings() und schickt dem Kern die Client-
 * Nachricht mikrofon_info mit genau sechs Feldern: echo, rauschen, verstaerkung (true, false oder null), rate (Hz oder null), kanaele
 * (1 bis 8 oder null) und klasse (eingebaut, headset, bluetooth oder unbekannt). Der Kern schreibt daraus eine Logzeile und hängt die Klasse an
 * jedes Stimmurteil (voice-core/mikrofon_kette.py). Datenschutz: nur Zahlen und die grobe Klasse. Die Klasse wird hier aus dem Gerätenamen
 * abgeleitet, der Name und die Kennung des Geräts verlassen den Browser nie, und ein Gerät ohne erkennbares Wort heißt unbekannt.
 *
 * Fehlt ein Wert oder wirft ein Aufruf, ist das Feld null, und die Nachricht geht trotzdem. Je Verbindung hält ein KettenMelder die jüngste
 * Meldung zurück, bis der Kern bereit ist, und gibt sie höchstens einmal je Änderung frei: dieselbe Kette (Mikrofon aus und wieder an,
 * neue Spur desselben Geräts) wird nicht noch einmal gesendet, und es gibt eine Obergrenze je Verbindung, damit eine Schleife nie flutet.
 *
 * Reine Logik ohne Browser (Tests: mikrofonKette.test.ts); die Verdrahtung liegt in useWamo.ts (eigeneSpur). Nie im Labor.
 */

export const KLASSEN = ["eingebaut", "headset", "bluetooth", "unbekannt"] as const;
export type KetteKlasse = (typeof KLASSEN)[number];

/** Die Nachricht mikrofon_info (Kern: voice-core/mikrofon_kette.py, gleiche Grenzen). Nie ein Name, nie eine Kennung. */
export type MikrofonInfo = {
  echo: boolean | null;
  rauschen: boolean | null;
  verstaerkung: boolean | null;
  rate: number | null;
  kanaele: number | null;
  klasse: KetteKlasse;
};

export const RATE_MIN = 8000;
export const RATE_MAX = 384000;
export const KANAELE_MIN = 1;
export const KANAELE_MAX = 8;
/** Mehr Meldungen je Verbindung gibt es nicht: ein Gerätewechsel sind wenige, mehr wäre eine Schleife. Gleich der Grenze für Logzeilen im Kern. */
export const MAX_MELDUNGEN = 50;
const NAME_MAX = 200;

// Reihenfolge der Prüfung: erst Bluetooth (ein Headset am Bluetooth-Profil heißt oft "Headset (... Hands-Free)"), dann ein Headset am Kabel
// (auch "Headset Microphone (Realtek Audio)" ist ein Headset und kein eingebautes Mikrofon), dann die eingebauten Mikrofone.
// Grundsatz: unbekannt ist besser als falsch. Deshalb steht Realtek nicht bei den eingebauten (am Desktop steckt dort oft ein Headset an der
// Klinke), nur eindeutige Wörter wie Mikrofonarray oder Smart Sound. Marken ohne Stichwort im Namen stehen bei Bluetooth, wenn die Reihe
// sicher Bluetooth ist (Sony WH und WF, Jabra Elite, Beats).
const BLUETOOTH =
  /bluetooth|hands[\s_-]?free|freisprech|airpods|free-?buds|\bbuds?\d*\b|\bbt\b|\ba2dp\b|\bhfp\b|\b(?:wh|wf)-\d{3,4}x?m?\d?\b|jabra elite|\bbeats\b/;
const HEADSET = /headset|head-set|headphone|earphone|earbud|ear-?pods?|kopfh(?:ö|oe|o)rer|sprechgarnitur/;
const EINGEBAUT =
  /onboard|built[\s_-]?in|integrat|integriert|\binterne?[rsn]?\b|\binternal\b|eingebaut|\bintel\b|mikrofon-?array|microphone[\s_-]?array|mic[\s_-]?array|\barray\b|smart[\s_-]?sound|laptop|notebook|macbook|facetime/;

/** Grobe Klasse aus dem Gerätennamen: bluetooth, headset, eingebaut, sonst unbekannt. Gibt nie den Namen zurück, wirft nie. */
export function klasseAusName(name: unknown): KetteKlasse {
  if (typeof name !== "string") return "unbekannt";
  const n = name.slice(0, NAME_MAX).normalize("NFC").toLowerCase(); // NFC: "Kopfhörer" mit zusammengesetztem und getrenntem ö
  if (BLUETOOTH.test(n)) return "bluetooth";
  if (HEADSET.test(n)) return "headset";
  if (EINGEBAUT.test(n)) return "eingebaut";
  return "unbekannt";
}

const schalter = (w: unknown): boolean | null => (typeof w === "boolean" ? w : null);

function ganzzahl(w: unknown, kleinste: number, groesste: number): number | null {
  return typeof w === "number" && Number.isInteger(w) && w >= kleinste && w <= groesste ? w : null;
}

/** Was von einer Mikrofonspur gelesen wird (MediaStreamTrack passt). */
export type SpurLesbar = { readonly label?: unknown; getSettings?: () => unknown };

function lesen<T>(f: () => T): T | null {
  try {
    return f();
  } catch {
    return null;
  }
}

/**
 * Die Kette der Spur: getSettings() und die Klasse aus dem Namen. Fehlt etwas oder wirft ein Aufruf (auch der Zugriff auf ein einzelnes Feld),
 * ist das Feld null (Klasse unbekannt). Die Schalter zählen nur als wahr oder falsch: Liefert ein Browser dort einen anderen Wert (zum Beispiel
 * die Zeichenkette der neueren Spezifikation für echoCancellation), heißt das null und steht im Protokoll als "?".
 */
export function mikrofonInfo(spur: SpurLesbar | null | undefined): MikrofonInfo {
  const roh = spur ? lesen(() => spur.getSettings?.()) : null;
  const s = roh !== null && typeof roh === "object" ? (roh as Record<string, unknown>) : {};
  const feld = (name: string): unknown => lesen(() => s[name]);
  return {
    echo: schalter(feld("echoCancellation")),
    rauschen: schalter(feld("noiseSuppression")),
    verstaerkung: schalter(feld("autoGainControl")),
    rate: ganzzahl(feld("sampleRate"), RATE_MIN, RATE_MAX),
    kanaele: ganzzahl(feld("channelCount"), KANAELE_MIN, KANAELE_MAX),
    klasse: klasseAusName(spur ? lesen(() => spur.label) : null),
  };
}

/**
 * Hält die jüngste Meldung einer Verbindung zurück und gibt sie höchstens einmal je Änderung frei. merken: eine neue Spur (ersetzt eine noch
 * nicht gesendete). abholen: die Meldung, die jetzt zu senden ist, sonst null. Je Verbindung ein neuer Melder (der Kern fängt je Sitzung neu an).
 */
export class KettenMelder {
  #wartend: MikrofonInfo | null = null;
  #zuletzt: string | null = null;
  #gesendet = 0;

  merken(info: MikrofonInfo): void {
    this.#wartend = info;
  }

  /** Verbraucht die Meldung und merkt ihren Schlüssel schon vor dem Senden: scheitert das Senden, kommt keine zweite Meldung (keine Schleife). */
  abholen(): MikrofonInfo | null {
    const info = this.#wartend;
    if (info === null) return null;
    this.#wartend = null;
    const schluessel = JSON.stringify(info);
    if (schluessel === this.#zuletzt || this.#gesendet >= MAX_MELDUNGEN) return null;
    this.#zuletzt = schluessel;
    this.#gesendet += 1;
    return info;
  }
}
