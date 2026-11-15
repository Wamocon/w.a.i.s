/**
 * Reine Logik des Installer-Downloads im Abschnitt "Erste Schritte" (docs/ausrollen-neue-nutzer.md 4.2): das Manifest des
 * Kerns (GET /wamo/api/installer) streng prüfen, Versionen vergleichen, Größe und Prüfsumme anzeigen und Fehler in
 * konkrete Sätze übersetzen. Ohne Netz und ohne React, damit sie sich mit node:test prüfen lässt (installer.test.ts).
 * Der Abruf selbst steht in lib/installerApi.ts, die Anzeige in components/einrichtung/InstallerDownload.tsx.
 *
 * Grundsatz: Die Oberfläche zeigt nie einen ungeprüften Wert. Passt ein Feld nicht genau zu den Regeln, gilt das ganze
 * Manifest als ungültig. Die Prüfsumme vom Server belegt nur eine heile Übertragung; den Vergleich mit dem
 * Willkommensblatt macht die Person selbst (Get-FileHash).
 */

const TEIL = "(0|[1-9]\\d{0,3})";
const VERSION_MUSTER = new RegExp(`^${TEIL}\\.${TEIL}\\.${TEIL}$`);
const DATEI_MUSTER = new RegExp(`^WAIS-Setup-${TEIL}\\.${TEIL}\\.${TEIL}\\.exe$`);
const SHA256_MUSTER = /^[0-9a-f]{64}$/;
const COMMIT_MUSTER = /^[0-9a-f]{40}$/;
/** eine Zeile Base64 für genau 64 Byte (Ed25519), wie aktuell.json.sig */
const SIGNATUR_MUSTER = /^[A-Za-z0-9+/]{86}==$/;
/** wie am Server und im Kern: UTC mit Z, optional bis zu drei Nachkommastellen */
const ZEIT_MUSTER = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;
const FELDER = ["v", "produkt", "version", "datei", "groesse", "sha256", "bauzeit", "commit"] as const;
type Feld = (typeof FELDER)[number];

/**
 * Größte Datei, die die Oberfläche lädt (256 MiB). Der Kern erlaubt bis 512 MiB, im Browser liegen beim Laden aber Puffer,
 * Prüfsumme und Blob gleichzeitig im Speicher (etwa das Dreifache); der Installer hat heute etwa 117 MB.
 */
export const MAX_GROESSE = 268_435_456;
const MAX_MANIFEST = 4096;

export type InstallerManifest = {
  /** genauer Text von aktuell.json (für die spätere Prüfung der Signatur in der App) */
  manifest: string;
  signatur: string | null;
  v: 1;
  produkt: "wais-desktop";
  version: string;
  datei: string;
  groesse: number;
  sha256: string;
  bauzeit: string;
  commit: string;
};

const istText = (v: unknown): v is string => typeof v === "string";

/** Der exakte Text von aktuell.json als Objekt mit genau den acht Feldern, sonst null. */
function manifestText(text: string): Record<Feld, unknown> | null {
  let roh: unknown;
  try {
    roh = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof roh !== "object" || roh === null || Array.isArray(roh)) return null;
  const schluessel = Object.keys(roh);
  if (schluessel.length !== FELDER.length || !FELDER.every((f) => schluessel.includes(f))) return null;
  return roh as Record<Feld, unknown>;
}

/**
 * Antwort des Kerns als geprüftes Manifest, oder null, wenn auch nur ein Wert nicht passt. Alle Werte stammen aus dem exakten
 * Text von aktuell.json (den prüft die App später gegen die Signatur), die Einzelfelder der Antwort müssen genau gleich sein:
 * So kann ein Kern nie eine Prüfsumme zeigen, die der Text nicht enthält. Fremde Felder fallen weg.
 */
export function manifestAusAntwort(daten: unknown): InstallerManifest | null {
  if (typeof daten !== "object" || daten === null || Array.isArray(daten)) return null;
  const d = daten as Record<string, unknown>;
  if (!istText(d.manifest) || d.manifest.length === 0 || d.manifest.length > MAX_MANIFEST) return null;
  const signatur = d.signatur ?? null;
  if (signatur !== null && !(istText(signatur) && SIGNATUR_MUSTER.test(signatur))) return null;
  const m = manifestText(d.manifest);
  if (!m || FELDER.some((f) => d[f] !== m[f])) return null;
  if (m.v !== 1 || m.produkt !== "wais-desktop") return null;
  if (!istText(m.version) || !VERSION_MUSTER.test(m.version)) return null;
  if (m.datei !== `WAIS-Setup-${m.version}.exe`) return null;
  if (typeof m.groesse !== "number" || !Number.isInteger(m.groesse) || m.groesse < 1 || m.groesse > MAX_GROESSE) return null;
  if (!istText(m.sha256) || !SHA256_MUSTER.test(m.sha256)) return null;
  if (!istText(m.commit) || !COMMIT_MUSTER.test(m.commit)) return null;
  if (!istText(m.bauzeit) || !ZEIT_MUSTER.test(m.bauzeit) || Number.isNaN(Date.parse(m.bauzeit))) return null;
  return {
    manifest: d.manifest,
    signatur,
    v: 1,
    produkt: "wais-desktop",
    version: m.version,
    datei: m.datei,
    groesse: m.groesse,
    sha256: m.sha256,
    bauzeit: m.bauzeit,
    commit: m.commit,
  };
}

function versionTeile(v: string): [number, number, number] | null {
  const t = VERSION_MUSTER.exec(v);
  return t ? [Number(t[1]), Number(t[2]), Number(t[3])] : null;
}

/** Versionen numerisch je Teil vergleichen (0.10.0 ist neuer als 0.9.9); null, wenn eine keine Version X.Y.Z ist. */
export function versionVergleich(a: string, b: string): -1 | 0 | 1 | null {
  const x = versionTeile(a);
  const y = versionTeile(b);
  if (!x || !y) return null;
  for (let i = 0; i < 3; i++) {
    if (x[i] !== y[i]) return x[i] > y[i] ? 1 : -1;
  }
  return 0;
}

/**
 * Hinweis zur Version der Desktop-App. Im Browser nie. In der App ohne gemeldete Version (die App 0.2.0 meldet keine):
 * "Update empfohlen." Meldet sie eine ältere als das Manifest: die Zielversion. Gleich oder neuer: nichts.
 */
export function versionsHinweis(appVersion: string | null, manifest: InstallerManifest | null, inApp: boolean): string | null {
  if (!inApp) return null;
  if (!appVersion || !versionTeile(appVersion)) return "Update empfohlen.";
  if (!manifest) return null;
  return versionVergleich(appVersion, manifest.version) === -1 ? `Update auf Version ${manifest.version} verfügbar.` : null;
}

/**
 * Version aus der Brücke der App (window.wamoDesktop, desktop/preload.js). Nur ein Text der Form X.Y.Z zählt; alles andere
 * (fehlt, Zahl, Funktion, Zusatz wie -beta) gilt als nicht gemeldet. Der globale Typ der Brücke bleibt dafür unberührt.
 */
export function appVersionAus(bruecke: unknown): string | null {
  if (typeof bruecke !== "object" || bruecke === null) return null;
  const v = (bruecke as { version?: unknown }).version;
  return istText(v) && VERSION_MUSTER.test(v) ? v : null;
}

/** Version der laufenden Desktop-App, null im Browser, auf dem Server und in Apps, die keine melden. */
export function appVersion(): string | null {
  const w = (globalThis as { window?: { wamoDesktop?: unknown } }).window;
  return w ? appVersionAus(w.wamoDesktop) : null;
}

// ---------- Anzeige ----------
function zahl(x: number, stellen: 0 | 1): string {
  const r = stellen === 1 ? Math.round(x * 10) / 10 : Math.round(x);
  return String(r).replace(".", ",");
}

const KIB = 1024;
const MIB = KIB * 1024;
const GIB = MIB * 1024;

/** Größe für Menschen, deutsch mit Komma: 117000000 Bytes sind "112 MB" (Basis 1024, wie Windows sie zeigt). */
export function groesseText(bytes: number): string {
  if (bytes < KIB) return bytes === 1 ? "1 Byte" : `${bytes} Bytes`;
  const [wert, einheit] = bytes < MIB ? [bytes / KIB, "KB"] : bytes < GIB ? [bytes / MIB, "MB"] : [bytes / GIB, "GB"];
  return `${zahl(wert, wert < 10 ? 1 : 0)} ${einheit}`;
}

/** Fortschritt des Downloads, zum Beispiel "34 von 112 MB (30 %)"; ohne bekannte Gesamtgröße nur die geladene Menge. */
export function fortschrittText(geladen: number, gesamt: number | null): string {
  const mb = (b: number) => zahl(b / MIB, 0);
  if (!gesamt) return `${mb(geladen)} MB geladen`;
  const prozent = Math.min(100, Math.floor((geladen / gesamt) * 100));
  return `${mb(geladen)} von ${mb(gesamt)} MB (${prozent} %)`;
}

/** PowerShell-Befehl zum Prüfen der geladenen Datei; nur für einen gültigen Dateinamen aus dem Manifest, sonst null. */
export function hashBefehl(datei: string): string | null {
  return DATEI_MUSTER.test(datei) ? `Get-FileHash .\\${datei}` : null;
}

export const VERGLEICH_SATZ = "Vergleiche die Zeichen mit deinem Willkommensblatt.";

/** Zwei SHA-256-Werte vergleichen: Groß- und Kleinschreibung egal, Leerraum außen egal, sonst nur 64 Hex-Zeichen. */
export function sha256Gleich(a: string, b: string): boolean {
  const x = a.trim().toLowerCase();
  const y = b.trim().toLowerCase();
  return SHA256_MUSTER.test(x) && x === y;
}

/** Bytes (zum Beispiel aus crypto.subtle.digest) als Hex in Kleinbuchstaben. */
export function hexAusBytes(daten: ArrayBuffer | Uint8Array): string {
  const bytes = daten instanceof Uint8Array ? daten : new Uint8Array(daten);
  let hex = "";
  for (const b of bytes) hex += b.toString(16).padStart(2, "0");
  return hex;
}

/** Fehler beim Abruf des Manifests oder der Datei als konkreter Satz (Status 0 steht für Netz, Zeitgrenze und Abbruch). */
export function installerFehlerText(status: number, code: string | null, text = ""): string {
  if (status === 0) {
    if (text === "Abgebrochen") return "Download abgebrochen.";
    if (text === "Zeitüberschreitung") {
      return "Der Kern hat nicht rechtzeitig geliefert (Zeitüberschreitung). Bitte noch einmal versuchen.";
    }
    return "Der Kern ist nicht erreichbar. Bitte später noch einmal versuchen.";
  }
  if (status === 401) return "Die Anmeldung ist abgelaufen. Bitte neu anmelden.";
  if (status === 403) {
    return code === "installer_labor"
      ? "Für Laborprofile gibt es keinen Installer."
      : "Der Kern gibt den Installer für dieses Profil nicht frei. Melde dich mit zweitem Faktor an oder frag Niko.";
  }
  if (status === 413) return "Die Datei ist größer als angekündigt. Sie wurde verworfen.";
  if (status === 429) {
    return "Du hast den Installer in der letzten Stunde schon dreimal geladen. Bitte versuch es in einer Stunde noch einmal.";
  }
  if (status === 503) return "Auf dem Server liegt gerade kein Installer bereit. Bitte frag Niko.";
  if (status >= 500) return "Der Kern hat gerade ein Problem. Bitte später noch einmal versuchen.";
  return `Der Kern hat die Anfrage abgelehnt (${status}).`;
}
