/**
 * Hinweis bei Gerätewechsel (Befund 18.11.2026): Die Stimmprüfung hielt den Besitzer oft für fremd. Hauptursache war ein Gerätewechsel:
 * eingelernt mit einem Bluetooth-Headset, geprüft mit dem eingebauten Mikrofon (Pegelspitze im Median -27 statt -8 dBFS). Neu einlernen am
 * selben Gerät hob die Werte um 0,15 bis 0,25.
 *
 * Die Oberfläche merkt sich deshalb beim Einlernen (Meldung "stimmabdruck" mit "fertig") den Namen des Mikrofons, das im Gespräch lief, und
 * vergisst ihn beim Löschen des Abdrucks. Gespeichert wird nur der Name, nur im Speicher dieses Browsers oder dieser App (localStorage, je
 * Person wie die Mikrofonwahl in lib/mikrofon.ts), nie in der Datenbank. Läuft in einem Gespräch mit bereitem Abdruck ein anderes Mikrofon,
 * fragt die Oberfläche einmal je Gespräch und Gerät, ob für dieses Mikrofon neu eingelernt werden soll (Knopf in components/FehlerAnzeige.tsx).
 * Ist kein Name gemerkt (vor dieser Neuerung eingelernt, anderer Browser), gibt es keinen Hinweis: unbekannt heißt nicht anders.
 *
 * Ein Abdruck je Mikrofon (Wunsch vom 18.11.2026, Kern voice-core/stimme_mikrofon.py, Migration 0029): Der Kern schickt die Liste
 * der eingelernten Mikrofone (Nachricht stimmabdruck_mikrofone, höchstens drei). Mit ihr fragt die Oberfläche nur noch, wenn das laufende
 * Mikrofon nicht eingelernt ist, und bietet "Für dieses Mikrofon einlernen" an; sind schon drei eingelernt, nennt sie die Grenze. Beim
 * Einlernen schickt sie den Namen des laufenden Mikrofons mit (mikrofonFuerKern). Ein Abdruck aus der Zeit davor heißt beim Kern "unbekannt"
 * und hat keinen Namen: Für ihn gilt weiter der hier gemerkte Name, und nur für ihn wird er gemerkt und vergessen. Kann der Kern nur einen
 * Abdruck (max 1, ohne Migration 0029), bleibt alles wie bisher.
 *
 * Reine Logik ohne Browser (Tests: stimmMikrofon.test.ts); die Verdrahtung liegt in useWamo.ts.
 */
import { geraeteName } from "./mikrofon.ts";
import type { StimmMikrofonEintrag } from "./nachrichten.ts";

export const STIMM_MIKROFON_PRAEFIX = "wamo.stimme.mikrofon.";

export const ANDERES_MIKROFON_TEXT = "Deine Stimme ist mit einem anderen Mikrofon eingelernt. Für dieses Mikrofon neu einlernen?";
/** Hinweis mit der Liste des Kerns: das laufende Mikrofon ist noch nicht eingelernt */
export const FUER_DIESES_MIKROFON_TEXT = "Für dieses Mikrofon ist deine Stimme noch nicht eingelernt. Jetzt einlernen?";
/** dasselbe, wenn schon drei Mikrofone eingelernt sind (der Kern nimmt kein viertes) */
export const MIKROFONE_VOLL_TEXT =
  "Für dieses Mikrofon ist deine Stimme noch nicht eingelernt. Du hast schon drei Mikrofone eingelernt, lösche in den Einstellungen eines.";

/** Kennung des Abdrucks aus der Zeit, bevor der Kern Mikrofone unterschied (ohne Namen) */
export const UNBEKANNT = "unbekannt";

/** Ein eingelerntes Mikrofon, wie der Kern es meldet: Kennung, Name aus dem Browser (null: unbekannt), Zeitpunkt des Einlernens (ISO) */
export type { StimmMikrofonEintrag };
/** Die eingelernten Mikrofone und wie viele der Kern höchstens annimmt (3; 1 ohne Abdrücke je Mikrofon) */
export type StimmMikrofone = { mikrofone: StimmMikrofonEintrag[]; max: number };

type Lesen = { getItem(k: string): string | null };
type Schreiben = { setItem(k: string, v: string): void };
type Entfernen = { removeItem(k: string): void };

function schluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${STIMM_MIKROFON_PRAEFIX}${userId}`;
}

/** Der Speicher dieses Browsers oder dieser App; null, wenn es keinen gibt oder der Zugriff wirft (privates Fenster, gesperrte Daten). */
export function stimmSpeicher(): (Lesen & Schreiben & Entfernen) | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Name des Mikrofons, mit dem diese Person eingelernt hat (wie geraeteName), null, wenn keiner gemerkt ist. */
export function stimmMikrofonLesen(speicher: Lesen | null | undefined, userId: string | null | undefined): string | null {
  const k = schluessel(userId);
  if (!k || !speicher) return null;
  try {
    return geraeteName(speicher.getItem(k));
  } catch {
    return null;
  }
}

/** Beim Einlernen: Namen merken. true, wenn der Speicher ihn angenommen hat. */
export function stimmMikrofonMerken(
  speicher: Schreiben | null | undefined,
  userId: string | null | undefined,
  label: string | null | undefined,
): boolean {
  const k = schluessel(userId);
  const name = geraeteName(label);
  if (!k || !name || !speicher) return false;
  try {
    speicher.setItem(k, name);
    return true;
  } catch {
    return false;
  }
}

/** Abdruck gelöscht: den Namen vergessen. */
export function stimmMikrofonVergessen(speicher: Entfernen | null | undefined, userId: string | null | undefined): void {
  const k = schluessel(userId);
  if (!k || !speicher) return;
  try {
    speicher.removeItem(k);
  } catch {
    // nichts zu tun: dann bleibt ein alter Name, der höchstens einen Hinweis zu viel auslöst
  }
}

/** Vergleichsform: wie mikrofonFuerKern (so steht der Name beim Kern), ohne Unterschied in Groß- und Kleinschreibung. */
const vergleich = (label: string | null | undefined): string | null => mikrofonFuerKern(label)?.toLowerCase() ?? null;

/** Name des laufenden Mikrofons für den Kern (Feld mikrofon beim Start des Einlernens): wie geraeteName, Steuer- und Formatzeichen werden
 *  zu Leerraum, Leerraum zusammengezogen, höchstens 120 Zeichen; null ohne Namen. Der Kern bereinigt noch einmal (stimme_mikrofon.py). */
export function mikrofonFuerKern(label: string | null | undefined): string | null {
  if (typeof label !== "string") return null;
  return geraeteName(label.replace(/[\p{Cc}\p{Cf}\s]+/gu, " "));
}

/** Kann der Kern mehrere Abdrücke (einen je Mikrofon)? Nur dann gilt seine Liste für Hinweis und Einstellungen. */
export const mehrereMikrofone = (liste: StimmMikrofone | null | undefined): liste is StimmMikrofone => (liste?.max ?? 0) > 1;

/** Namen der eingelernten Mikrofone zum Vergleich; ein Abdruck ohne Namen bekommt den hier gemerkten Namen, sonst null. */
function eingelernteNamen(liste: StimmMikrofone, gemerkt: string | null | undefined): (string | null)[] {
  return liste.mikrofone.map((e) => vergleich(e.name ?? (e.kennung === UNBEKANNT ? gemerkt : null)));
}

/** Ist das laufende Mikrofon eingelernt? true, false oder null (kein laufendes Mikrofon, oder ein Abdruck ohne Namen könnte es sein). */
export function istEingelernt(liste: StimmMikrofone, aktuell: string | null | undefined, gemerkt: string | null | undefined): boolean | null {
  const a = vergleich(aktuell);
  if (a === null) return null;
  const namen = eingelernteNamen(liste, gemerkt);
  if (namen.includes(a)) return true;
  return namen.includes(null) ? null : false;
}

/** Der Eintrag des laufenden Mikrofons (nur mit Namen vom Kern), sonst null. */
export function laufenderEintrag(liste: StimmMikrofone, aktuell: string | null | undefined): StimmMikrofonEintrag | null {
  const a = vergleich(aktuell);
  return a === null ? null : (liste.mikrofone.find((e) => vergleich(e.name) === a) ?? null);
}

/** Läuft ein anderes Mikrofon als beim Einlernen? Nur, wenn beide Namen bekannt sind. */
export function anderesMikrofon(gemerkt: string | null | undefined, aktuell: string | null | undefined): boolean {
  const a = vergleich(gemerkt);
  const b = vergleich(aktuell);
  return a !== null && b !== null && a !== b;
}

export type GeraetHinweisLage = {
  /** Mikrofon beim Einlernen (stimmMikrofonLesen) */
  gemerkt: string | null;
  /** Mikrofon des laufenden Gesprächs (WamoState.mikrofon) */
  aktuell: string | null;
  /** verbunden und der Kern meldet einen bereiten Abdruck */
  stimmeBereit: boolean;
  /** keine andere Meldung steht */
  frei: boolean;
  /** W.A.I.S. spricht gerade */
  wamoSpricht: boolean;
  /** die Einlernansicht ist offen */
  einlernen: boolean;
  /** die eingelernten Mikrofone vom Kern (null: keine Liste); mit mehreren gilt sie statt gemerkt */
  eingelernt?: StimmMikrofone | null;
};

/**
 * Ist der Hinweis jetzt fällig? Liefert den Schlüssel des Geräts, das die Person gerade benutzt (der Aufrufer merkt ihn sich in gezeigt,
 * damit der Hinweis je Gespräch und Gerät nur einmal kommt), sonst null.
 */
export function geraetHinweisFaellig(lage: GeraetHinweisLage, gezeigt: ReadonlySet<string>): string | null {
  if (!lage.stimmeBereit || !lage.frei || lage.wamoSpricht || lage.einlernen) return null;
  if (mehrereMikrofone(lage.eingelernt) ? istEingelernt(lage.eingelernt, lage.aktuell, lage.gemerkt) !== false
      : !anderesMikrofon(lage.gemerkt, lage.aktuell)) return null;
  const geraet = vergleich(lage.aktuell);
  return geraet && !gezeigt.has(geraet) ? geraet : null;
}
