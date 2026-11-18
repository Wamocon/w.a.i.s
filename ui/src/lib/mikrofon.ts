/**
 * Mikrofon: Pegel der eigenen Spur, Stille-Wächter, verständliche Meldungen mit Abhilfe und die Gerätewahl.
 *
 * Hintergrund: Liefert das Standardgerät von Windows nur digitale Stille (Laptop zugeklappt am Dock, Dock- oder
 * Headset-Mikrofon ohne Signal, Stummschaltung am Gerät), läuft das Gespräch scheinbar normal, nur hört WAMO nichts.
 * Die Oberfläche misst deshalb die eigene Spur selbst (SmallWebRTC meldet keinen lokalen Pegel) und sagt nach
 * STILLE_MS klar, was los ist und was hilft. Der Kern meldet zusätzlich, wenn bei ihm nur Stille ankommt.
 *
 * Reine Logik ohne Browser-Abhängigkeit (Tests: mikrofon.test.ts); Zugriff auf Geräte und Audio liegt in useWamo.ts.
 */

/** Unter dieser Spitze (dBFS) gilt ein Messfenster als still. Echte Mikrofone liegen auch im leisen Raum darüber. */
export const STILLE_DBFS = -100;
/** So lange muss die Spur ununterbrochen still sein, bevor die Oberfläche warnt. */
export const STILLE_MS = 3000;
/** So lange nach "Bot bereit" darf die eigene Mikrofonspur auf sich warten lassen, bevor die Oberfläche warnt. */
export const SPUR_MS = 5000;
/** So lange wartet die Oberfläche nach dem Ende einer Spur auf die Ersatzspur (Gerätewechsel), bevor sie warnt. */
export const SPUR_ENDE_MS = 1500;

/** Spitze und RMS eines Messfensters. spitzeDb ist -Infinity bei exakt null. */
export function messen(buf: ArrayLike<number>): { rms: number; spitzeDb: number } {
  let summe = 0;
  let spitze = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i];
    summe += v * v;
    const a = Math.abs(v);
    if (a > spitze) spitze = a;
  }
  const rms = buf.length ? Math.sqrt(summe / buf.length) : 0;
  return { rms, spitzeDb: spitze > 0 ? 20 * Math.log10(spitze) : Number.NEGATIVE_INFINITY };
}

/** Pegel für Stimmlinie, Kern und Rand (gleiche Skala wie WAMOs Pegel: Sprache etwa 0,1 bis 0,3). */
export const anzeigePegel = (rms: number) => Math.min(1, Math.max(0, rms * 2));

export type StilleZustand = { stillSeit: number | null; gemeldet: boolean };

export const neueStille = (): StilleZustand => ({ stillSeit: null, gemeldet: false });

/**
 * Ein Messwert für den Wächter. aktiv: verbunden, Mikrofon nicht stumm geschaltet, Messung läuft.
 * Ergebnis "still" genau einmal je stiller Phase, "wieder_da" einmal, wenn danach wieder Ton kommt oder das
 * Mikrofon abgeschaltet wird (dann ist die Warnung hinfällig), sonst null.
 */
export function pruefeStille(z: StilleZustand, spitzeDb: number, jetzt: number, aktiv: boolean): "still" | "wieder_da" | null {
  if (!aktiv || spitzeDb > STILLE_DBFS) {
    z.stillSeit = null;
    if (z.gemeldet) {
      z.gemeldet = false;
      return "wieder_da";
    }
    return null;
  }
  if (z.stillSeit === null) z.stillSeit = jetzt;
  if (!z.gemeldet && jetzt - z.stillSeit >= STILLE_MS) {
    z.gemeldet = true;
    return "still";
  }
  return null;
}

const WINDOWS_EINGABE = "in Windows unter Einstellungen > System > Sound > Eingabe";

/** Warnung der Oberfläche: die eigene Spur ist seit STILLE_MS still. */
export function stilleText(geraet?: string | null): string {
  const welches = geraet ? ` („${geraet}“)` : "";
  return (
    `Das Mikrofon${welches} liefert keinen Ton, W.A.I.S. hört dich nicht. Prüfe die Stummschaltung am Gerät oder ` +
    `Headset, wähle unten ein anderes Mikrofon oder stelle ${WINDOWS_EINGABE} das richtige Gerät ein. ` +
    (istBluetoothGeraet(geraet) ? BLUETOOTH_HINWEIS : "Am Dock mit zugeklapptem Laptop ist das eingebaute Mikrofon meist aus.")
  );
}

/** Bluetooth-Kopfhörer (auch im Freisprech-Profil). Das eingebaute Mikrofon und Kabel-Headsets gehören nicht dazu. */
const BLUETOOTH_GERAET = /bluetooth|airpods|buds|freisprech|hands-?free/i;
export const istBluetoothGeraet = (geraet?: string | null): boolean => Boolean(geraet && BLUETOOTH_GERAET.test(geraet));

/**
 * 12.11.2026: Das Mikrofon eines Bluetooth-Kopfhörers lieferte in WAMO erst keinen Ton, später ging es. Windows wechselt bei Bluetooth zwischen
 * Stereo-Wiedergabe und Freisprech-Betrieb, nur im Freisprech-Betrieb gibt es ein Mikrofon. Das hilft meist: aus- und einschalten,
 * ein zweites verbundenes Bluetooth-Gerät trennen, Ausgabe und Eingabe auf denselben Kopfhörer stellen.
 */
const BLUETOOTH_HINWEIS =
  "Bei einem Bluetooth-Kopfhörer wechselt Windows manchmal nicht in den Freisprech-Betrieb: Schalte den Kopfhörer aus und wieder ein, " +
  "trenne ein zweites verbundenes Bluetooth-Gerät und wähle in Windows für Ausgabe und Eingabe denselben Kopfhörer.";

/** Warnung vom Kern: bei ihm kommt seit einigen Sekunden nur digitale Stille an. */
export function kernStilleText(sekunden: number): string {
  return (
    `Beim Sprachkern kommt seit ${sekunden} Sekunden nur Stille vom Mikrofon an. Wähle unten ein anderes Mikrofon ` +
    "oder beende das Gespräch und starte es neu."
  );
}

/** Warnung vom Kern: es kommen gar keine Audiopakete mehr an (die Sendespur ist abgerissen). */
export function kernFehltText(sekunden: number): string {
  return (
    `Beim Sprachkern kommt seit ${sekunden} Sekunden kein Ton mehr vom Mikrofon an, die Mikrofonspur ist abgerissen. ` +
    "Wähle unten ein Mikrofon aus oder beende das Gespräch und starte es neu."
  );
}

/** Die Spur des Mikrofons ist beendet (Gerät abgezogen oder von Windows entzogen) und es folgte keine neue. */
export function spurEndeText(geraet?: string | null): string {
  const welches = geraet ? ` („${geraet}“)` : "";
  return (
    `Das Mikrofon${welches} wurde getrennt oder von Windows entzogen, W.A.I.S. hört dich nicht mehr. Schließe es wieder ` +
    "an oder wähle unten ein anderes Mikrofon."
  );
}

/** Nach dem Verbinden kam nie eine Mikrofonspur an. */
export function keineSpurText(): string {
  return (
    "Es kommt keine Mikrofonspur an, W.A.I.S. hört dich nicht. Wähle unten ein Mikrofon aus, prüfe " +
    `${WINDOWS_EINGABE} das Gerät oder beende das Gespräch und starte es neu.`
  );
}

/** Windows verweigert Desktop-Apps das Mikrofon (Datenschutz): dann liefert es nur Stille, ohne Fehler. */
export function windowsGesperrtText(): string {
  return (
    "Windows blockiert das Mikrofon für Desktop-Apps, deshalb kommt nur Stille an. Erlaube den Zugriff in Windows " +
    "unter Einstellungen > Datenschutz und Sicherheit > Mikrofon (Zugriff auf das Mikrofon und Desktop-Apps " +
    "zulassen) und starte das Gespräch neu."
  );
}

/** Zustand von systemPreferences.getMediaAccessStatus("microphone"): nur "denied" und "restricted" sperren. */
export function windowsGesperrt(status: unknown): boolean {
  return status === "denied" || status === "restricted";
}

/** Logzeile (landet in logs/oberflaeche.log der Desktop-App): das Mikrofon liefert echten Ton. */
export function tonLog(geraet: string | null | undefined, spitzeDb: number): string {
  const name = geraet ? geraet.slice(0, 120) : "unbekanntes Gerät";
  return `Mikrofon liefert Ton: ${name}, Spitze ${Math.round(spitzeDb)} dBFS`;
}

/** getUserMedia ist fehlgeschlagen: Meldung je Fehlerart, immer mit Abhilfe. */
export function mikrofonFehlerText(name?: string): string {
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return (
        "Mikrofon gesperrt: W.A.I.S. darf das Mikrofon nicht nutzen. In Windows unter Einstellungen > Datenschutz und " +
        "Sicherheit > Mikrofon den Zugriff für Desktop-Apps erlauben (im Browser das Mikrofon für diese Seite " +
        "freigeben), dann das Gespräch neu starten."
      );
    case "NotFoundError":
    case "OverconstrainedError":
      return `Kein Mikrofon gefunden. Mikrofon oder Headset anschließen, ${WINDOWS_EINGABE} prüfen und neu starten.`;
    case "NotReadableError":
    case "AbortError":
      return (
        "Das Mikrofon lässt sich nicht öffnen, vermutlich nutzt ein anderes Programm es exklusiv. Programme mit " +
        "Mikrofon (Teams, Zoom, Aufnahme) schließen oder ein anderes Mikrofon wählen und neu starten."
      );
    default:
      return `Das Mikrofon lässt sich nicht öffnen. ${WINDOWS_EINGABE[0].toUpperCase()}${WINDOWS_EINGABE.slice(1)} das Gerät prüfen und neu starten.`;
  }
}

/** Name eines Fehlers aus onDeviceError (DeviceError mit sourceError) oder einem DOMException-artigen Objekt. */
export function fehlerName(e: unknown): string | undefined {
  if (typeof e !== "object" || e === null) return undefined;
  const quelle = (e as { details?: { sourceError?: unknown } }).details?.sourceError;
  const n = (quelle as { name?: unknown } | undefined)?.name ?? (e as { name?: unknown }).name;
  return typeof n === "string" ? n.slice(0, 40) : undefined;
}

// ---------- Gerätewahl (je Person und Gerät gespeichert) ----------
/**
 * 17.11.2026: Im Browser nahm W.A.I.S. ein anderes Mikrofon als die Desktop-App (Stimmprüfung im Browser 0,02 bis 0,28, in der App 0,33
 * bis 0,74). Browser und Desktop-App haben je einen eigenen Speicher, und Chrome hat ein eigenes Standardgerät (chrome://settings/content/
 * microphone), das nicht dem von Windows folgen muss. Die Wahl gilt deshalb je Person auf diesem Gerät, in diesem Browser oder dieser App
 * (Schlüssel mit der user_id wie lib/untertitel.ts), und die Einstellungen zeigen, welches Gerät Standard ist und welches benutzt wird.
 *
 * Bis 17.11.2026 gab es nur eine Wahl je Gerät für alle Personen (MIKROFON_SCHLUESSEL). Sie gilt weiter, solange die Person selbst nichts
 * gewählt hat; wählt sie das Standardgerät, steht MIKROFON_STANDARD in ihrem Schlüssel und verdeckt die alte Wahl.
 */
export const MIKROFON_SCHLUESSEL = "wamo.mikrofon";
export const MIKROFON_PRAEFIX = "wamo.mikrofon.";
export const MIKROFON_STANDARD = "standard";

export type Mikrofon = {
  id: string;
  label: string;
  /** dieses Gerät steckt hinter dem Alias "default": das Standardgerät des Browsers (in der Desktop-App das von Windows) */
  standard?: boolean;
};

type Geraet = { kind: string; deviceId: string; label: string; groupId?: string };

/**
 * Nur echte Geräte mit Kennung; "default" und "communications" sind Aliase von Windows. Das Gerät hinter "default" bekommt standard:
 * Chrome nennt den Alias "<Wort> - <Name des Geräts>" (das Wort hängt von der Sprache ab), also zählt das Ende der Bezeichnung; ohne
 * Treffer die Gerätegruppe, wenn sie genau ein Eingabegerät hat.
 */
export function geraeteListe(geraete: ArrayLike<Geraet>): Mikrofon[] {
  const liste: (Mikrofon & { gruppe?: string })[] = [];
  let alias: Geraet | null = null;
  for (let i = 0; i < geraete.length; i++) {
    const g = geraete[i];
    if (g.kind !== "audioinput" || !g.deviceId || g.deviceId === "communications") continue;
    if (g.deviceId === "default") {
      alias = g;
      continue;
    }
    liste.push({ id: g.deviceId, label: (g.label || "Mikrofon").slice(0, 120), gruppe: g.groupId });
  }
  const standard = alias ? standardIndex(liste, alias) : -1;
  return liste.map((m, i) => (i === standard ? { id: m.id, label: m.label, standard: true } : { id: m.id, label: m.label }));
}

function standardIndex(liste: readonly (Mikrofon & { gruppe?: string })[], alias: Geraet): number {
  const name = alias.label ?? "";
  // "Standard - Mikrofon (USB)" passt zu "Mikrofon (USB)", aber nicht zu einem Gerät, dessen Name nur das Ende davon ist
  const nachName = liste.findIndex(
    (m) => name.length > m.label.length && name.endsWith(m.label) && /[-–]\s*$/.test(name.slice(0, name.length - m.label.length)),
  );
  if (nachName >= 0) return nachName;
  if (!alias.groupId) return -1;
  const gleich = liste.flatMap((m, i) => (m.gruppe === alias.groupId ? [i] : []));
  return gleich.length === 1 ? gleich[0] : -1;
}

/** Vorsatz, den Chrome den Aliasen voranstellt ("Standard - Headset", "Kommunikation - Headset"), in Deutsch und Englisch. */
const ALIAS_VORSATZ = /^(standard|default|kommunikation|communications)\s*[-–]\s*/i;

/**
 * Name eines Mikrofons zum Wiedererkennen (Mikrofontest, Hinweis bei Gerätewechsel): Eine Spur des Standardgeräts heißt in Chrome oft
 * "Standard - <Name>", dasselbe Gerät mit Kennung geöffnet nur "<Name>". Ohne diesen Vorsatz, getrimmt, höchstens 120 Zeichen; null ohne
 * Namen. Ein Strich im Namen selbst ("Headset - Jabra") bleibt.
 */
export function geraeteName(label: string | null | undefined): string | null {
  if (typeof label !== "string") return null;
  const name = label.trim().replace(ALIAS_VORSATZ, "").trim().slice(0, 120);
  return name || null;
}

/** Gewähltes Gerät, wenn es noch angeschlossen ist; sonst null (dann gilt das Standardgerät). */
export function startGeraet(liste: Mikrofon[], gewuenscht: string | null): string | null {
  return gewuenscht && liste.some((m) => m.id === gewuenscht) ? gewuenscht : null;
}

/** Name des Standardgeräts für die Auswahl: im Browser das des Browsers, in der Desktop-App das von Windows. */
export const standardText = (desktop: boolean): string => (desktop ? "Standardgerät von Windows" : "Standardgerät des Browsers");

/** Kurzer Hinweis, wenn das gewählte Mikrofon fehlt (abgezogen, belegt) und W.A.I.S. deshalb das Standardgerät nimmt. */
export const MIKROFON_ERSATZ_TEXT = "Das gewählte Mikrofon ist nicht verfügbar, W.A.I.S. nutzt das Standardgerät.";

type Lesen = { getItem(k: string): string | null };
type Schreiben = { setItem(k: string, v: string): void };

const gueltigeKennung = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 200;

/** Schlüssel im Speicher für diese Person; null, wenn die Kennung fehlt oder nicht wie eine user_id aussieht. */
export function mikrofonSchluessel(userId: string | null | undefined): string | null {
  if (typeof userId !== "string" || !/^[A-Za-z0-9-]{1,64}$/.test(userId)) return null;
  return `${MIKROFON_PRAEFIX}${userId}`;
}

/**
 * Gewähltes Mikrofon dieser Person auf diesem Gerät (Kennung des Geräts), null für das Standardgerät. Ohne eigene Wahl gilt die alte Wahl je
 * Gerät. Ohne Speicher, bei einem Lesefehler oder einem unbrauchbaren Wert: null.
 */
export function mikrofonLesen(speicher: Lesen | null | undefined, userId: string | null | undefined): string | null {
  if (!speicher) return null;
  try {
    const k = mikrofonSchluessel(userId);
    const eigen = k ? speicher.getItem(k) : null;
    if (eigen !== null) return eigen !== MIKROFON_STANDARD && gueltigeKennung(eigen) ? eigen : null;
    const alt = speicher.getItem(MIKROFON_SCHLUESSEL);
    return gueltigeKennung(alt) && alt !== MIKROFON_STANDARD ? alt : null;
  } catch {
    return null;
  }
}

/** Wahl schreiben (null: Standardgerät). true, wenn der Speicher sie angenommen hat (sonst gilt sie nur bis zum Neuladen). */
export function mikrofonSchreiben(speicher: Schreiben | null | undefined, userId: string | null | undefined, id: string | null): boolean {
  const k = mikrofonSchluessel(userId);
  if (!k || !speicher || (id !== null && !gueltigeKennung(id))) return false;
  try {
    speicher.setItem(k, id ?? MIKROFON_STANDARD);
    return true;
  } catch {
    return false;
  }
}

/** Wahl, die der Speicher nicht annahm (privates Fenster, gesperrte Website-Daten): gilt bis zum Neuladen. */
const rueckfall = new Map<string, string>();

function lokalerSpeicher(): (Lesen & Schreiben) | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Gewähltes Mikrofon der angemeldeten Person auf diesem Gerät (null: Standardgerät). */
export function gewaehltesMikrofon(userId: string | null | undefined): string | null {
  const k = mikrofonSchluessel(userId);
  const gemerkt = k ? rueckfall.get(k) : undefined;
  if (gemerkt !== undefined) return gemerkt === MIKROFON_STANDARD ? null : gemerkt;
  return mikrofonLesen(lokalerSpeicher(), userId);
}

/** Wahl merken (null: Standardgerät). Ohne Kennung der Person wird nichts gemerkt, die Wahl wirkt dann nur im laufenden Gespräch. */
export function merkeMikrofon(userId: string | null | undefined, id: string | null): void {
  const k = mikrofonSchluessel(userId);
  if (!k || (id !== null && !gueltigeKennung(id))) return;
  if (mikrofonSchreiben(lokalerSpeicher(), userId, id)) rueckfall.delete(k);
  else rueckfall.set(k, id ?? MIKROFON_STANDARD);
}

// ---------- "Ohne Mikrofon weiter" ----------
/**
 * Wählt die Person bei einer Mikrofon-Warnung "Ohne Mikrofon weiter", bleibt die Stille-Warnung für dieses Gerät aus, auch bei einem
 * neuen Gespräch (12.11.2026: Bei einem Mikrofon, das Windows als "OK" führt und nur Nullen liefert, kam die Warnung bei jedem Start
 * wieder). Das Gedächtnis gilt nur für dieses Fenster bis zum Neuladen und wird nirgends gespeichert. Liefert das Gerät später wieder
 * Ton (pruefeStille meldet "wieder_da"), warnt WAMO bei der nächsten Stille wieder. Andere Fehler (kein Gerät, von Windows gesperrt,
 * abgerissene Spur) bleiben davon unberührt.
 */
const OHNE_MIKROFON_MAX = 20;
const ohneMikrofon = new Set<string>();

/** Schlüssel wie in der Oberfläche (WamoState.mikrofon): die Bezeichnung der Spur, auf 120 Zeichen gekürzt; ohne Namen ein gemeinsamer Eintrag. */
const geraeteSchluessel = (geraet: string | null | undefined): string => (geraet ?? "").trim().slice(0, 120) || "unbekanntes Gerät";

export function stilleAusblenden(geraet: string | null | undefined): void {
  const k = geraeteSchluessel(geraet);
  ohneMikrofon.delete(k); // wieder ans Ende: das zuletzt gewählte Gerät fällt zuletzt heraus
  ohneMikrofon.add(k);
  while (ohneMikrofon.size > OHNE_MIKROFON_MAX) {
    const aeltestes = ohneMikrofon.values().next().value;
    if (aeltestes === undefined) break;
    ohneMikrofon.delete(aeltestes);
  }
}

export const stilleAusgeblendet = (geraet: string | null | undefined): boolean => ohneMikrofon.has(geraeteSchluessel(geraet));

export function stilleWiederAufnehmen(geraet: string | null | undefined): void {
  ohneMikrofon.delete(geraeteSchluessel(geraet));
}

// ---------- Sendespur ----------
type Sender = { track: MediaStreamTrack | null; replaceTrack: (t: MediaStreamTrack | null) => Promise<void> };
type Transceiver = { sender: Sender; receiver: { track: { kind: string } | null } };

/**
 * Neue Mikrofonspur auf die laufende Verbindung legen. Der SmallWebRTC-Transport (1.11) ersetzt die Sendespur nur
 * für seinen Daily-Medienmanager; mit dem WavMediaManager bliebe nach einem Gerätewechsel die alte, beendete Spur
 * am Sender, und beim Kern käme gar nichts mehr an. Die PeerConnection ist im Transport nicht öffentlich, deshalb
 * der Zugriff über das Feld "pc"; fehlt es (andere Version, noch keine Verbindung), passiert nichts.
 */
export async function sendeSpurErsetzen(transport: unknown, track: MediaStreamTrack): Promise<"ersetzt" | "gleich" | "kein_sender"> {
  const pc = (transport as { pc?: { getTransceivers?: () => Transceiver[] } | null } | null)?.pc;
  const audio = pc?.getTransceivers?.().find((t) => t.receiver?.track?.kind === "audio");
  if (!audio) return "kein_sender";
  if (audio.sender.track === track) return "gleich";
  await audio.sender.replaceTrack(track);
  return "ersetzt";
}
