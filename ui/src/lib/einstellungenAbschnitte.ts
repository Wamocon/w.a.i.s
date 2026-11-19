import type { EinrichtungsZustand, TunnelZustand } from "./geraet.ts";
import type { Modellzugang, Rolle } from "./nachrichten.ts";

/**
 * Reine Logik der Einstellungsseite (components/einstellungen/): welche Gruppen und Abschnitte es gibt, wer sie sieht, wie
 * Gruppe und Abschnitt in der Adresse stehen (Hash) und welche Kurztexte die Oberfläche daraus macht. Ohne React und ohne
 * Browser, damit sie sich mit node:test prüfen lässt (einstellungenAbschnitte.test.ts).
 *
 * Sechs Gruppen gliedern die Seite, jede fasst ihre Abschnitte zusammen (GRUPPEN). Die Gliederung zeigt nur die Gruppen,
 * eine Gruppe zeigt ihre Abschnitte untereinander. Gruppen und Abschnitte haben getrennte Kennungen ohne Überschneidung,
 * beide stehen im selben Hash: Eine Abschnittskennung (#einstellungen/stimme, die Adressen vor der Gruppierung) öffnet die
 * Gruppe des Abschnitts und springt zu ihm, eine Gruppenkennung (#einstellungen/zugaenge) öffnet die Gruppe am Anfang.
 * Dass beide Mengen disjunkt sind, prüft ein Test.
 *
 * Die Seite ist keine eigene Route, sondern eine Ansicht der Hauptseite, erreichbar über den Hash
 * (#einstellungen, #einstellungen/modellzugang). Das funktioniert im Browser wie in der Desktop-App, ohne dass die
 * Seite neu geladen wird, und ein laufendes Gespräch bleibt unberührt. Im Hash steht nur eine Kennung aus den festen
 * Listen unten, nie ein Wert aus dem Formular.
 */

export const ABSCHNITT_IDS = [
  "konto",
  "start",
  "darstellung",
  "info",
  "sprache",
  "stimme",
  "modellzugang",
  "github",
  "verbrauch",
  "geraete",
  "fernzugriff",
  "gedaechtnis",
  "teilen",
  "mitglieder",
  "aenderungen",
] as const;
export type AbschnittId = (typeof ABSCHNITT_IDS)[number];

export type Abschnitt = {
  id: AbschnittId;
  titel: string;
  /** eine Zeile unter der Überschrift des Abschnitts (sie entfällt, wenn die Gruppe nur diesen einen Abschnitt zeigt) */
  kurz: string;
  /** Stichwort für die Kurzzeile der Gruppe: die Gruppe reiht die Stichwörter ihrer sichtbaren Abschnitte (in der Laborsicht die laborKurz) */
  stichwort: string;
  /** nur für Profile mit der Rolle admin (die Rolle kommt vom Kern, der Kern prüft sie noch einmal) */
  nurAdmin?: boolean;
  /** trotz nurAdmin für jedes Profil mit eigenem Claude-Code-Token (Verbrauch, Ausrollen P5); der Kern liefert ohnehin nur den eigenen Stand */
  auchMitToken?: boolean;
  /** gilt in der Laborsicht (Laborkonten, lib/laborPlatz.ts): dort gibt es nur die Abschnitte mit diesem Zeichen */
  laborSicht?: boolean;
  /** Kurzzeile in der Laborsicht, wenn dort weniger zu finden ist als sonst (sonst gilt kurz) */
  laborKurz?: string;
};

/** Die Reihenfolge hier ist nur die Grundreihenfolge für abschnitteFuer; die Anzeige folgt der Reihenfolge in GRUPPEN. */
export const ABSCHNITTE: readonly Abschnitt[] = [
  { id: "konto", titel: "Konto", kurz: "E-Mail, Profil und Abmelden", stichwort: "Konto" },
  // Erste Schritte nach dem Ausrollen (docs/ausrollen-neue-nutzer.md 4.2, 4.3, 4.7): Modellzugang, Installer, Prüfliste und Updates der App
  // (lib/einrichtungSchritte.ts, lib/installer.ts, lib/einrichtung.ts); Kennung "start", weil es "einrichtung" schon als Block in
  // "Geräte und PC" gibt. Für jede Rolle, nie in der Laborsicht.
  { id: "start", titel: "Erste Schritte", kurz: "Modellzugang, Installer, Prüfliste und Updates", stichwort: "erste Schritte" },
  { id: "darstellung", titel: "Darstellung", kurz: "Helligkeit, Ansicht und Untertitel, gespeichert je Gerät", stichwort: "Darstellung" },
  { id: "info", titel: "Info", kurz: "Version, Kern und Hinweise", stichwort: "Version und Hinweise" },
  {
    id: "sprache",
    titel: "Mikrofon und Sprache",
    kurz: "Mikrofon, Spracherkennung und Sprachausgabe",
    stichwort: "Mikrofon, Hören und Sprechen",
    laborSicht: true,
    laborKurz: "Mikrofon wählen",
  },
  { id: "stimme", titel: "Eigene Stimme", kurz: "Deine Stimme erkennen und einlernen", stichwort: "eigene Stimme" },
  { id: "modellzugang", titel: "Modellzugang", kurz: "Schlüssel, Token, Modus und Modelle", stichwort: "Schlüssel und Modelle" },
  // Persönlicher GitHub-Zugang für Entwicklungsaufträge (Plan C, components/GithubZugang.tsx); ob die Person ihn nutzen darf, sagt der Kern
  { id: "github", titel: "GitHub-Zugang", kurz: "Eigenes Token für Entwicklungsaufträge", stichwort: "GitHub-Zugang" },
  { id: "verbrauch", titel: "Verbrauch", kurz: "Kontingent deines Claude-Abos", stichwort: "Verbrauch", nurAdmin: true, auchMitToken: true },
  {
    id: "geraete",
    titel: "Geräte und PC-Steuerung",
    kurz: "Verbindungen, Geräteverwaltung, PC-Steuerung und Betriebsart",
    stichwort: "Verbindungen und PC-Steuerung",
  },
  {
    id: "fernzugriff",
    titel: "Fernzugriff",
    kurz: "Desktop der Sparks unterwegs bedienen",
    stichwort: "Fernzugriff",
    nurAdmin: true,
  },
  { id: "gedaechtnis", titel: "Gedächtnis", kurz: "Vorschläge für alle prüfen", stichwort: "Vorschläge fürs Gedächtnis", nurAdmin: true },
  { id: "teilen", titel: "Teilen", kurz: "Geteilte Dokumente und Dateien", stichwort: "geteilte Dokumente" },
  {
    id: "mitglieder",
    titel: "Neue Mitglieder",
    kurz: "Einrichtung je Person und Rechte der GitHub-Zugänge",
    stichwort: "neue Mitglieder und GitHub-Rechte",
    nurAdmin: true,
  },
  {
    id: "aenderungen",
    titel: "Änderungen",
    kurz: "Stand der Selbstüberarbeitung von W.A.I.S.",
    stichwort: "Änderungen an W.A.I.S.",
    nurAdmin: true,
  },
];

// ---------- Gruppen ----------
/**
 * Kennungen der Gruppen. Bewusst keine Überschneidung mit ABSCHNITT_IDS (eine Gruppe "konto" neben einem Abschnitt "konto" machte
 * den Hash zweideutig und den Fokus nach einem Klick uneinheitlich): die drei Fälle, in denen Abschnitt und Gruppe sonst gleich
 * hießen, tragen darum eigene Namen (allgemein, sprache-stimme, geraete-pc).
 */
export const GRUPPE_IDS = ["allgemein", "sprache-stimme", "zugaenge", "geraete-pc", "inhalte", "verwaltung"] as const;
export type GruppeId = (typeof GRUPPE_IDS)[number];

export type Gruppe = { id: GruppeId; titel: string; abschnitte: readonly AbschnittId[] };

/** Die Gruppen in der Reihenfolge der Gliederung, mit ihren Abschnitten in der Reihenfolge der Seite. Jeder Abschnitt steht in genau einer Gruppe. */
export const GRUPPEN: readonly Gruppe[] = [
  { id: "allgemein", titel: "Konto und Allgemeines", abschnitte: ["konto", "start", "darstellung", "info"] },
  { id: "sprache-stimme", titel: "Sprache und Stimme", abschnitte: ["sprache", "stimme"] },
  { id: "zugaenge", titel: "Modelle und Zugänge", abschnitte: ["modellzugang", "github", "verbrauch"] },
  { id: "geraete-pc", titel: "Geräte und PC", abschnitte: ["geraete", "fernzugriff"] },
  { id: "inhalte", titel: "Gedächtnis und Teilen", abschnitte: ["gedaechtnis", "teilen"] },
  { id: "verwaltung", titel: "Verwaltung", abschnitte: ["mitglieder", "aenderungen"] },
];

/** Eine Gruppe, wie diese Rolle sie sieht: nur die sichtbaren Abschnitte, dazu die Kurzzeile der Gliederung. */
export type SichtbareGruppe = Readonly<{
  id: GruppeId;
  titel: string;
  /** Kurzzeile unter dem Titel: die Stichwörter der sichtbaren Abschnitte, in der Laborsicht deren Laborzeile */
  kurz: string;
  abschnitte: readonly Abschnitt[];
}>;

/**
 * Abschnitte, die diese Rolle sieht (flach, in der Grundreihenfolge von ABSCHNITTE). Eine unbekannte Rolle (noch kein Profil vom
 * Kern) zählt wie mitglied. In der Laborsicht (labor: Laborkonto, lib/laborPlatz.ts) gibt es nur die Abschnitte mit laborSicht, die
 * Rolle spielt dort keine Rolle, und ihre Kurzzeile ist laborKurz, wo es eine gibt (die Liste ABSCHNITTE selbst bleibt unverändert).
 * token: das Profil hat einen eigenen Claude-Code-Token (Modellzugang.codeHinterlegt); dann sehen auch Mitglieder die Abschnitte
 * mit auchMitToken.
 */
export function abschnitteFuer({ rolle, labor = false, token = false }: { rolle: Rolle | null; labor?: boolean; token?: boolean }): readonly Abschnitt[] {
  if (labor) return ABSCHNITTE.filter((a) => a.laborSicht).map((a) => ({ ...a, kurz: a.laborKurz ?? a.kurz }));
  return ABSCHNITTE.filter((a) => !a.nurAdmin || rolle === "admin" || (token && a.auchMitToken === true));
}

const grossAnfang = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * Die Gruppen dieser Rolle für die Gliederung: eine Gruppe erscheint, wenn mindestens einer ihrer Abschnitte sichtbar ist, und
 * enthält nur die sichtbaren. Ein Mitglied sieht so fünf Gruppen (ohne Verwaltung), die Laborsicht genau eine.
 */
export function gruppenFuer(o: { rolle: Rolle | null; labor?: boolean; token?: boolean }): readonly SichtbareGruppe[] {
  const sichtbar = new Map(abschnitteFuer(o).map((a) => [a.id, a] as const));
  const gruppen: SichtbareGruppe[] = [];
  for (const g of GRUPPEN) {
    const abschnitte = g.abschnitte.flatMap((id) => {
      const a = sichtbar.get(id);
      return a ? [a] : [];
    });
    if (abschnitte.length === 0) continue;
    const zeilen = o.labor ? abschnitte.map((a) => a.kurz) : abschnitte.map((a) => a.stichwort);
    gruppen.push({ id: g.id, titel: g.titel, kurz: grossAnfang(zeilen.join(", ")), abschnitte });
  }
  return gruppen;
}

export const abschnittTitel = (id: AbschnittId): string => ABSCHNITTE.find((a) => a.id === id)?.titel ?? "";
export const gruppeTitel = (id: GruppeId): string => GRUPPEN.find((g) => g.id === id)?.titel ?? "";

/** In welcher Gruppe steht der Abschnitt? Jeder steht in genau einer (ein Test prüft das). */
export function gruppeVon(abschnitt: AbschnittId): GruppeId {
  return (GRUPPEN.find((g) => g.abschnitte.includes(abschnitt)) ?? GRUPPEN[0]).id;
}

export function istAbschnittId(v: unknown): v is AbschnittId {
  return typeof v === "string" && (ABSCHNITT_IDS as readonly string[]).includes(v);
}

export function istGruppeId(v: unknown): v is GruppeId {
  return typeof v === "string" && (GRUPPE_IDS as readonly string[]).includes(v);
}

// ---------- Adresse (Hash) ----------
export const HASH_WURZEL = "einstellungen";

/**
 * Was die Adresse meint: offen oder nicht, welche Gruppe und (nur bei einer Abschnittskennung) welcher Abschnitt darin. Eine
 * Abschnittskennung bringt ihre Gruppe mit, eine Gruppenkennung steht für sich.
 */
export type HashZiel = Readonly<
  { offen: false; gruppe: null; abschnitt: null } | { offen: true; gruppe: GruppeId | null; abschnitt: AbschnittId | null }
>;

const GESCHLOSSEN: HashZiel = Object.freeze({ offen: false, gruppe: null, abschnitt: null });
const OFFEN_OHNE_ZIEL: HashZiel = Object.freeze({ offen: true, gruppe: null, abschnitt: null });

/**
 * Hash der Adresse (mit oder ohne #) als Ziel. "#einstellungen" öffnet die Seite ohne Ziel, "#einstellungen/modellzugang" mit
 * Abschnitt (und dessen Gruppe), "#einstellungen/zugaenge" mit Gruppe. Alles andere, auch eine unbekannte Kennung, zusätzliche
 * Teile oder ein überlanger Rest, öffnet die Seite ohne Ziel; fremde Hashes lassen sie geschlossen. Die Ergebnisse sind
 * eingefroren und werden gemeinsam benutzt.
 */
export function parseHash(hash: string): HashZiel {
  const roh = (hash.startsWith("#") ? hash.slice(1) : hash).toLowerCase();
  const teile = roh.split("/", 8); // mehr Teile gibt es nie; ein überlanger Hash fällt unten auf "ohne Ziel"
  if (teile[0] !== HASH_WURZEL) return GESCHLOSSEN;
  if (roh.length > 64) return OFFEN_OHNE_ZIEL;
  const rest = teile.slice(1).filter((t, i, alle) => !(t === "" && i === alle.length - 1)); // ein Schrägstrich am Ende zählt nicht
  if (rest.length !== 1) return OFFEN_OHNE_ZIEL;
  if (istAbschnittId(rest[0])) return Object.freeze({ offen: true, gruppe: gruppeVon(rest[0]), abschnitt: rest[0] });
  if (istGruppeId(rest[0])) return Object.freeze({ offen: true, gruppe: rest[0], abschnitt: null });
  return OFFEN_OHNE_ZIEL;
}

/** Hash (mit #) für die Seite zu einer Gruppe oder einem Abschnitt; ohne Angabe die Gliederung beziehungsweise die erste Gruppe. */
export const hashFuer = (ziel: GruppeId | AbschnittId | null): string => (ziel ? `#${HASH_WURZEL}/${ziel}` : `#${HASH_WURZEL}`);

/**
 * Welche Gruppe gilt jetzt? Eine erlaubte Gruppe aus der Adresse gilt immer, bei einem Abschnitt aus der Adresse nur, wenn diese
 * Rolle ihn sieht (sonst gilt der Hash wie ohne Ziel). Sonst zeigt die zweispaltige Ansicht die erste erlaubte Gruppe, die
 * einspaltige (Handy) die Liste (null).
 */
export function wirksameGruppe(ziel: HashZiel, erlaubt: readonly SichtbareGruppe[], zweispaltig: boolean): GruppeId | null {
  if (!ziel.offen) return null;
  const g = ziel.gruppe ? erlaubt.find((x) => x.id === ziel.gruppe) : undefined;
  if (g && (ziel.abschnitt === null || g.abschnitte.some((a) => a.id === ziel.abschnitt))) return g.id;
  return zweispaltig ? (erlaubt[0]?.id ?? null) : null;
}

/** Zu welchem Abschnitt springt die Seite? Zu dem aus der Adresse, wenn die wirksame Gruppe ihn zeigt; sonst zu keinem (Anfang der Gruppe). */
export function sprungAbschnitt(ziel: HashZiel, gruppe: SichtbareGruppe | undefined): AbschnittId | null {
  if (!ziel.offen || !gruppe || ziel.abschnitt === null || ziel.gruppe !== gruppe.id) return null;
  return gruppe.abschnitte.some((a) => a.id === ziel.abschnitt) ? ziel.abschnitt : null;
}

/** Wohin führt "Zurück" (und die Taste Escape)? Am Handy aus einer Gruppe zur Liste, sonst zum Gespräch. */
export function zurueckZiel(wirksam: GruppeId | null, zweispaltig: boolean): "liste" | "gespraech" {
  return !zweispaltig && wirksam !== null ? "liste" : "gespraech";
}

// ---------- Geräte und PC ----------
export type GeraeteBlock = "status" | "verwaltung" | "pc" | "betriebsart" | "einrichtung";

/** Kennung der Karte Geräteverwaltung im Dokument: Hinweise und Info springen hierhin (lib/einstellungenHash.ts). */
export const GERAETEVERWALTUNG_ID = "geraeteverwaltung";
/** Kennung des Blocks PC-Steuerung: der Weg aus der Kopfzeile springt hierhin (lib/einstellungenHash.ts, zurPcSteuerung). */
export const PC_STEUERUNG_ID = "pc-steuerung";

/**
 * Blöcke des Abschnitts "Geräte und PC-Steuerung": der Status der Verbindungen sieht jeder. Die Geräteverwaltung (Freigeben,
 * Sperren, Widerrufen) und die PC-Steuerung nur der Admin (die PC-Steuerung auch im
 * Browser, dort mit dem Hinweis, dass sie den Laptop aus dem Geräteregister steuert). Der Fernzugriff ist ein eigener Abschnitt
 * derselben Gruppe (nur Admin) und kein Block mehr: sonst stünde dieselbe Komponente zweimal auf einer Seite. Die Betriebsart gibt es nur, wo es etwas zu
 * wählen gibt (Büro eingerichtet und kein Browser auf dem Server). Die Einrichtung des Geräts gibt es nur in der
 * Desktop-App. pcAdmin (lib/pcSchalter.ts): Admin für die PC-Steuerung, auch ohne Sitzung aus der gemerkten Rolle und nie für
 * Laborkonten; ohne Angabe gilt die Rolle.
 */
export function geraeteBloecke(o: {
  rolle: Rolle | null;
  desktop: boolean;
  serverBrowser: boolean;
  bueroVerfuegbar: boolean;
  pcAdmin?: boolean;
}): readonly GeraeteBlock[] {
  const bloecke: GeraeteBlock[] = ["status"];
  if (o.rolle === "admin") bloecke.push("verwaltung");
  if (o.pcAdmin ?? o.rolle === "admin") bloecke.push("pc");
  if (o.bueroVerfuegbar && !o.serverBrowser) bloecke.push("betriebsart");
  if (o.desktop) bloecke.push("einrichtung");
  return bloecke;
}

export type GeraeteStand = {
  zustand: EinrichtungsZustand;
  text?: string;
  tunnel: TunnelZustand | null;
  kennung: string | null;
};

const TUNNEL_TEXT: Record<TunnelZustand, string> = {
  verbunden: "Tunnel zu W.A.I.S. verbunden",
  host: "Dieser PC ist selbst der Host, kein Tunnel nötig",
  aus: "Tunnel aus",
  unbekannt: "Tunnel unbekannt",
};

/** Ein Satz zum Stand der Geräteeinrichtung; "bereit" heißt: in Ordnung, nichts zu tun. */
export function geraeteStandText(
  s: GeraeteStand,
  o: { desktop: boolean; bueroBetrieb: boolean },
): { text: string; art: "bereit" | "offen" | "wartet" | "fehler" } {
  if (!o.desktop) return { text: "Die Einrichtung gibt es nur in der Desktop-App.", art: "offen" };
  if (!o.bueroBetrieb) {
    return { text: "Die Einrichtung läuft nur in der Betriebsart Büro. Wechsle dafür die Betriebsart.", art: "offen" };
  }
  switch (s.zustand) {
    case "wartet":
      return { text: "Dein Laptop wartet auf die Freigabe durch einen Admin.", art: "wartet" };
    case "fehler":
      return { text: s.text || "Die Einrichtung deines Laptops ist fehlgeschlagen.", art: "fehler" };
    case "eingerichtet": {
      const tunnel = s.tunnel ? `${TUNNEL_TEXT[s.tunnel]}.` : "";
      const kennung = s.kennung ? ` Kennung ${s.kennung}.` : "";
      return { text: `Eingerichtet.${kennung}${tunnel ? ` ${tunnel}` : ""}`, art: s.tunnel === "verbunden" || s.tunnel === "host" ? "bereit" : "offen" };
    }
    case "nicht_noetig":
      return { text: "Noch nicht geprüft. Die Einrichtung startet nach der Anmeldung von selbst.", art: "offen" };
    default: {
      const unbekannt: never = s.zustand; // neue Zustände müssen hier behandelt werden
      void unbekannt;
      return { text: "Stand unbekannt.", art: "offen" };
    }
  }
}

// ---------- Seitenleiste: eine Zeile zum Modellzugang ----------
/**
 * Kurzer Stand für die Seitenleiste. Genau das, was der Kern gemeldet hat: ob ein eigener Claude-Schlüssel (Gespräch)
 * und ein Claude-Code-Token (Entwicklungsaufträge) hinterlegt sind. Nie ein Wert, nur "hinterlegt".
 */
export function modellzugangKurz(z: Modellzugang | null): string {
  if (!z) return "wird geladen";
  if (!z.art) return "Stand nicht lesbar"; // der Kern hat keinen lesbaren Stand gemeldet, mit oder ohne Fehlertext
  if (z.hinterlegt && z.codeHinterlegt) return "Claude-Schlüssel und Token hinterlegt";
  if (z.hinterlegt) return "Claude-Schlüssel hinterlegt";
  if (z.codeHinterlegt) return "Token hinterlegt";
  if (z.quelle === "zuordnung") return "Schlüssel des Kerns";
  return "fehlt";
}

export const ROLLE_TEXT: Record<Rolle, string> = { admin: "Admin", mitglied: "Mitglied" };
export const rolleText = (rolle: Rolle | null): string => (rolle ? ROLLE_TEXT[rolle] : "noch unbekannt");
