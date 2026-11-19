import { auftragGithub, EINREICHEN_ID, pruefeEinreichen, type Einreichen } from "./einreichen.ts";
import type { CanvasItem } from "@/components/Canvas";
import type { AuftragStand } from "./auftragStart.ts"; // relativ, nur der Typ (beide Dateien laden unter node:test)
import { JIRA_PROJEKTE_MAX, linkOk, projektOk, schluesselOk, type JiraErgebnis, type JiraStatus } from "./jiraStory.ts";
import { istOfficeFormat, OFFICE_FORMATE, type DateiMeldung, type OfficeFormat } from "./export.ts";
import { MAIL_VERSAND_ZUSTAENDE, type MailVersandZustand } from "./mail.ts";
import {
  SELBST_AKTIONEN,
  SELBST_BEARBEITER,
  SELBST_ERGEBNIS_MAX,
  SELBST_LISTE_MAX,
  SELBST_MAX_OBERGRENZE,
  SELBST_PRIORITAETEN,
  SELBST_QUELLEN,
  SELBST_STATUS,
  SELBST_TITEL_MAX,
  type SelbstAktion,
  type SelbstAuftrag,
} from "./selbstAuftraege.ts";

/**
 * RTVI-Servernachrichten des Voice-Core (kommen über onServerMessage in useWamo.ts an).
 * Die Daten stammen aus dem Netz: jede Nachricht wird hier geprüft, unbekannte oder
 * unvollständige Nachrichten ergeben null und werden ignoriert. Zusatzfelder, die der Kern
 * vielleicht später schickt (id für "Rückgängig", Latenz, Cloud oder im Haus), sind optional.
 */

export type Rolle = "admin" | "mitglied";

export type Profil = { name: string; rolle: Rolle };

export type Betrieb = {
  modus: "lokal" | "buero";
  modelle: { llm?: string; stt?: string; tts?: string };
  /** verbindet: Kern baut die Verbindung zum PC-Host gerade auf (Sitzungsbeginn) */
  pc: "verbindet" | "verbunden" | "getrennt" | "aus" | "gesperrt";
  /** optional: wohin die Stimme geht */
  ort?: "cloud" | "haus";
  /** optional: Antwortzeit des PC-Hosts in Millisekunden */
  pcLatenzMs?: number;
  /** PC-Steuerung dieser Sitzung (Schalter für Admins und freigeschaltete Mitglieder); fehlt = aus */
  pcSteuerung?: "an" | "aus";
  /** Stufe der PC-Steuerung dieser Sitzung (voice-core/rechte.py): mitglied nur mit Freischaltung je Profil; fehlt = keine. Der Kern
   *  entscheidet, die Oberfläche zeigt damit nur den Schalter. */
  pcStufe?: "admin" | "mitglied";
  /** Entwicklungsaufträge erlaubt? "aus" = gesperrt */
  entwicklung?: "an" | "aus";
  /** optional: Rechnername des gesteuerten PCs (Büro: der PC am anderen Ende des Tunnels) */
  pcName?: string;
  /** Einschalten abgelehnt, weil eine andere Sitzung den PC gerade steuert */
  pcBelegt?: boolean;
  /** wirksamer Modus dieser Sitzung (WAMO Boss): nur_haus gilt ohne eigenen API-Schlüssel, bei Zwang des Admins und
   *  bei der Wahl der Person; sonst wählt der Boss unter allen erlaubten Modellen */
  modellModus?: ModellModus;
  /** warum dieser Modus gilt (festgelegt: Admin, wahl: Person, keiner: kein eigener Schlüssel, ...) */
  modellQuelle?: ModellQuelle;
  /** warum der Boss nicht das beste Modell nehmen konnte (zu langsam, nicht erreichbar) */
  modellHinweis?: string;
  /** warum Entwicklungsaufträge im Büro aus sind; Admins bekommen den ganzen Grund, Mitglieder nur ihre Sätze (entwicklung_betrieb.anzeige_grund) */
  entwicklungGrund?: string;
  /** Dateiformate, in denen das Canvas jetzt am PC gespeichert werden kann (nur mit PC-Steuerung, voice-core/office_werkzeuge.py) */
  office?: OfficeFormat[];
  /** Mail über Outlook am PC geht jetzt (nur mit PC-Steuerung, voice-core/outlook_werkzeuge.py): Knopf "Als E-Mail" */
  mail?: boolean;
  /** ob der Knopf "Als OneNote-Seite" gehen kann (nur mit PC-Steuerung und OneNote am PC, voice-core/onenote_werkzeuge.py) */
  onenote?: boolean;
  /** Teams-Nachrichten am PC gehen jetzt (nur mit PC-Steuerung, voice-core/teams_werkzeuge.py): Knopf "Als Teams-Nachricht" */
  teams?: boolean;
  /** warum diese Sitzung trotz Wahl "Im Haus" über Soniox hört oder spricht (voice-core/sprache_anbieter.py, SprachWahl.grund);
   *  oder warum der Betrieb sie für alle festgelegt hat; fehlt, wenn die Sitzung der Wahl folgt */
  spracheGrund?: string;
};

/** Hören und Stimme je Profil (voice-core/sprache_anbieter.py): Soniox (Standard) oder im Haus über das Gateway */
const SPRACH_ANBIETER = ["soniox", "haus"] as const;
export type SprachAnbieter = (typeof SPRACH_ANBIETER)[number];

/** Modellwahl je Profil: Automatisch (der Boss wählt) oder Nur Hausmodelle */
export type ModellModus = "automatisch" | "nur_haus";
export type ModellQuelle = "profil" | "zuordnung" | "festgelegt" | "wahl" | "keiner" | "fehler" | "betreiber";
const MODELL_MODI = ["automatisch", "nur_haus"] as const;
const MODELL_QUELLEN = ["profil", "zuordnung", "festgelegt", "wahl", "keiner", "fehler", "betreiber"] as const;

export type Gemerkt = {
  bereich: "persoenlich" | "gemeinsam";
  status: "aktiv" | "vorgeschlagen";
  text: string;
  /** optional: Kennung des Eintrags, nur dann gibt es "Rückgängig" */
  id?: string;
};

/** Bereiche der Modellwahl je Person (voice-core/modellwahl.py, Migration 0024) */
export const MODELL_BEREICHE = ["gespraech", "bilder", "hintergrund"] as const;
export type ModellBereich = (typeof MODELL_BEREICHE)[number];
/** Ein wählbares Modell, wie der Kern es für diesen Zugang anbietet (Name und eine Zeile zu Tempo und Güte) */
export type ModellOption = { id: string; name: string; art: "haus" | "claude"; zeile: string };
/** Je Bereich: gültige Wahl ("automatisch" oder eine Kennung aus optionen), Angebot und ein Hinweis, wenn eine gespeicherte Wahl
 *  mit dem Zugang gerade nicht gilt */
export type ModellBereichStand = { wahl: string; optionen: ModellOption[]; hinweis?: string };
/** Eine der freigegebenen Stimmen im Haus (voice-core/sprache_anbieter.py, HAUS_STIMMEN: die Liste kommt allein vom Kern) */
export type HausStimme = { id: string; name: string; hinweis?: string };
/** Wahl "kein bestimmtes Modell": der Boss wählt (Standard) */
export const AUTOMATISCH = "automatisch";
// Form der Kennungen wie die Prüfungen der Datenbank (Migration 0024); voice-core/test_migration_0024.py hält beide gleich
const MODELL_ID = /^[a-z0-9][a-z0-9.-]{1,62}$/;
const STIMME_ID = /^[a-z][a-z0-9_]{1,31}$/;
const MAX_MODELLE = 12;
const MAX_STIMMEN = 20;

/**
 * Modellzugang des Profils (voice-core/modellzugang.py): eigener Claude-Schlüssel oder nur Hausmodelle.
 * Enthält nie den Schlüssel, nur ob einer hinterlegt ist und seine letzten vier Zeichen.
 */
export type Modellzugang = {
  aktion: "status" | "hinterlegen" | "loeschen" | "modus" | "stimme" | "modell" | "haus_stimme";
  /** fehlt, wenn der Kern den Stand gerade nicht lesen konnte (dann steht nur fehler da) */
  art?: "claude" | "haus";
  /** profil: eigener Schlüssel, zuordnung: Schlüssel des Kerns für genau dieses Profil, festgelegt: vom Admin,
   *  wahl: von der Person gewählt (nur Hausmodelle) */
  quelle?: "profil" | "zuordnung" | "festgelegt" | "wahl" | "keiner" | "fehler";
  /** eigener API-Schlüssel (Gespräch) hinterlegt */
  hinterlegt: boolean;
  ende?: string;
  geprueft?: string;
  /** ein Admin hat nur Hausmodelle festgelegt: die Wahl der Person ist gesperrt */
  festgelegt: boolean;
  modell?: string;
  /** Wahl der Person, unabhängig vom Zwang des Admins; fehlt, wenn der Kern sie nicht gemeldet hat */
  modus?: ModellModus;
  /** Claude-Code-Token (nur Entwicklungsaufträge, aus `claude setup-token`) hinterlegt; nur die letzten vier Zeichen */
  codeHinterlegt: boolean;
  codeEnde?: string;
  codeGesetzt?: string;
  /** Hören (Spracherkennung) und Stimme (Sprachausgabe) des Profils, gewählt von der Person oder vom Admin; gilt ab der nächsten
   *  Sitzung. Fehlt, wenn der Kern sie nicht gemeldet hat. */
  stt?: SprachAnbieter;
  tts?: SprachAnbieter;
  /** "bereit" oder ein Satz, warum Hören und Stimme im Haus in diesem Kern gerade nicht gehen; fehlt bei einem Kern, der die Wahl
   *  noch nicht kennt */
  stimmeHaus?: string;
  /** Modellwahl je Bereich (Kern ab Migration 0024); fehlt bei einem Kern, der die Wahl noch nicht kennt */
  modelle?: Partial<Record<ModellBereich, ModellBereichStand>>;
  /** warum die Modellwahl gesperrt ist (Admin hat Hausmodelle festgelegt) */
  modellSperre?: string;
  /** Stimme im Haus: Wahl der Person (fehlt: Standard des Kerns), die Stimme des Kerns und die Auswahl */
  hausStimme?: string;
  hausStimmeStandard?: string;
  hausStimmen?: HausStimme[];
  hausStimmenHinweis?: string;
  wirksam?: string;
  fehler?: string;
};

const istObjekt = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Ohne doppelte Kennungen (die erste gilt), damit Auswahl und React-Schlüssel eindeutig bleiben. */
function eindeutig<T extends { id: string }>(liste: T[]): T[] {
  const gesehen = new Set<string>();
  return liste.filter((x) => !gesehen.has(x.id) && gesehen.add(x.id));
}

/** Modellwahl aus der Meldung des Kerns: nur bekannte Bereiche, Kennungen in der Form der Datenbank, erst prüfen, dann höchstens
 *  MAX_MODELLE je Bereich, ohne doppelte Kennungen. Eine Wahl, die nicht im Angebot steht, gilt als automatisch. */
function modelleAus(roh: unknown): Partial<Record<ModellBereich, ModellBereichStand>> | undefined {
  if (!istObjekt(roh)) return undefined;
  const ergebnis: Partial<Record<ModellBereich, ModellBereichStand>> = {};
  for (const bereich of MODELL_BEREICHE) {
    const e = roh[bereich];
    if (!istObjekt(e)) continue;
    const geprueft = (Array.isArray(e.optionen) ? e.optionen : []).slice(0, 100).flatMap((o): ModellOption[] => {
      if (!istObjekt(o)) return [];
      const { id, name, art } = o;
      if (!isStr(id) || id === AUTOMATISCH || !MODELL_ID.test(id) || !oneOf(art, ["haus", "claude"] as const)) return [];
      return [{ id, name: zeile(name, 60) ?? id, art, zeile: zeile(o.zeile, 160) ?? "" }];
    });
    const liste = eindeutig(geprueft).slice(0, MAX_MODELLE);
    const wahl = isStr(e.wahl) && liste.some((o) => o.id === e.wahl) ? e.wahl : AUTOMATISCH;
    ergebnis[bereich] = { wahl, optionen: liste, hinweis: zeile(e.hinweis, 200) };
  }
  return Object.keys(ergebnis).length > 0 ? ergebnis : undefined;
}

function hausStimmenAus(roh: unknown): HausStimme[] | undefined {
  if (!Array.isArray(roh)) return undefined;
  const geprueft = roh.slice(0, 100).flatMap((s): HausStimme[] => {
    if (!istObjekt(s) || !isStr(s.id) || !STIMME_ID.test(s.id)) return [];
    return [{ id: s.id, name: zeile(s.name, 40) ?? s.id, hinweis: zeile(s.hinweis, 120) }];
  });
  const liste = eindeutig(geprueft).slice(0, MAX_STIMMEN);
  return liste.length > 0 ? liste : undefined;
}

/** Eine Stimme nur, wenn sie in der Liste des Kerns steht (sonst hätte die Auswahl keinen passenden Eintrag). */
function stimmeAus(roh: unknown, liste: HausStimme[] | undefined): string | undefined {
  return isStr(roh) && liste?.some((s) => s.id === roh) ? roh : undefined;
}

/**
 * Kontingent des Max-Abos (voice-core/kontingent.py, aus rate_limit_event von Claude Code): sitzung = 5-Stunden-Fenster,
 * woche = Wochenlimit (alle Modelle), fable = Wochenlimit des größten Modells (in Claude Code "Fable limit"), opus und
 * sonnet = ältere modellbezogene Wochenlimits. Jedes Feld außer art kann fehlen. Ohne Daten ist der Zustand "unbekannt".
 */
export const KONTINGENT_ARTEN = ["sitzung", "woche", "opus", "sonnet", "fable"] as const;
export type KontingentLimit = {
  art: (typeof KONTINGENT_ARTEN)[number];
  /** genutzter Anteil in Prozent (0 bis 1000; über 100 kommt vor), eine Nachkommastelle */
  prozent?: number;
  /** Ende des Fensters, ISO 8601 in UTC (YYYY-MM-DDTHH:MM:SSZ) */
  endet?: string;
  status?: "ok" | "warnung" | "erreicht";
};
export type Kontingent = {
  zustand: "unbekannt" | "bekannt";
  /** wann der Kern den Stand zuletzt gespeichert hat (ISO 8601, UTC) */
  stand?: string;
  limits: KontingentLimit[];
};

/** wartet: kritische PC-Aktion, die auf eine Freigabe in der Oberfläche wartet */
export type ActivityStatus = "laeuft" | "fertig" | "abgelehnt" | "fehler" | "wartet";

/** Ein Werkzeugaufruf von WAMO für die Aktivitäts-Zeitleiste (activity.py im Voice-Core). */
export type Activity = {
  id: string;
  name: string;
  detail: string;
  status: ActivityStatus;
  /** im Browser gesetzt: Beginn und Ende (performance.now), Gesprächszug */
  startedAt?: number;
  endedAt?: number;
  turn?: number;
};

/** Ein Punkt zum Freigeben. ziel: Zielanwendung (PC-Aktionen, z. B. Fenster und Programm); gueltigS: Frist in s. */
export type FreigabePunkt = {
  id: string;
  grund: string;
  detail: string;
  von?: string;
  ziel?: string;
  /** Begründung des Modells (nur Hinweis, nicht das, was ausgeführt wird) */
  anlass?: string;
  /** Warnung des Kerns (Mail: im selben Zug kamen Inhalte aus Web, Mail oder Bildschirm) */
  warnung?: string;
  gueltigS?: number;
  /** Karte "Einreichen" eines Entwicklungsauftrags mit eigenem GitHub-Token (id "einreichen", lib/einreichen.ts) */
  einreichen?: Einreichen;
};

/** Abnahmekriterien auf der Startkarte (voice-core/dev_agent.py): höchstens 5, je höchstens 300 Zeichen. */
export const AUFTRAG_ABNAHME_MAX = 5;
export const AUFTRAG_ABNAHME_ZEICHEN = 300;

/**
 * Entwicklungsauftrag, den das Profil vor dem Start bestätigen muss (Servernachricht "auftrag").
 * abnahme: die Kriterien, die WAMO nach jeder Runde prüft (Texte, Befehle beginnen mit "befehl:"); leer ohne Ziel.
 */
export type Auftrag = {
  job: string;
  projekt: string;
  art: string;
  auftrag: string;
  abnahme: string[];
  /** Ziel-Repo owner/name; fehlt bei einem Kern ohne dieses Feld und bei einer Recherche ohne Repo */
  repo?: string;
  /** Der Auftrag läuft mit dem eigenen GitHub-Token der Person (Plan C); konto: Login laut Kern */
  github?: { konto: string | null };
  /** Zustand der Startkarte nach dem Klick (lib/auftragStart.ts); nie vom Kern gesetzt, fehlt bis zum Klick */
  stand?: AuftragStand;
};

/** Aktionen an den gespeicherten Aufträgen (voice-core/auftrag_entwuerfe.py, Client-Nachricht auftrag_entwurf). */
export const ENTWURF_AKTIONEN = ["liste", "speichern", "laden", "loeschen"] as const;
export type EntwurfAktion = (typeof ENTWURF_AKTIONEN)[number];
/** Höchstens so viele Einträge nimmt die Oberfläche aus einer Liste (der Kern speichert höchstens 50 je Person). */
export const ENTWURF_LISTE_MAX = 50;

/** Ein für später gespeicherter Entwicklungsauftrag in der Liste: Titel (Anfang des Textes), Projekt, Art, Repo, Zeitpunkt. */
export type AuftragEntwurf = {
  id: string;
  titel: string;
  projekt: string;
  art: string;
  repo?: string;
  gespeichertMs: number;
};

/**
 * Vorgang (voice-core/vorgaenge.py): was WAMO gerade abarbeitet, mit Gesamtfortschritt, Schritten und Prüfkriterien.
 * Jede Nachricht trägt den ganzen Stand; die Oberfläche ersetzt den Vorgang gleicher Kennung.
 */
export const VORGANG_ARTEN = ["aufgabe", "entwicklung", "geraet", "sonstiges"] as const;
export const VORGANG_STATUS = ["geplant", "laeuft", "wartet_freigabe", "pruefen", "fertig", "fehler", "abgebrochen"] as const;
export const VORGANG_SCHRITT_STATUS = ["offen", "laeuft", "fertig", "fehler", "uebersprungen", "wartet_freigabe"] as const;
export const VORGANG_MAX_SCHRITTE = 60;
export const VORGANG_MAX_KRITERIEN = 20;
export type VorgangArt = (typeof VORGANG_ARTEN)[number];
export type VorgangStatus = (typeof VORGANG_STATUS)[number];
export type VorgangSchrittStatus = (typeof VORGANG_SCHRITT_STATUS)[number];
export type VorgangSchritt = {
  /** Stelle in der Liste, ab 1 */
  nr: number;
  titel: string;
  status: VorgangSchrittStatus;
  /** 0 bis 1 */
  fortschritt: number;
  detail: string | null;
};
export type VorgangKriterium = {
  text: string;
  /** true: Haken, false: nicht erfüllt, null: noch offen */
  erfuellt: boolean | null;
  hinweis: string | null;
};
export type Vorgang = {
  id: string;
  titel: string;
  art: VorgangArt;
  status: VorgangStatus;
  /** Beginn der Arbeit (Millisekunden seit 1970, Uhr des Kerns) */
  gestartetMs: number;
  beendetMs: number | null;
  /** Mittel der Schrittfortschritte, 0 bis 1 */
  gesamt: number;
  /** geschätzte Restzeit in Sekunden; null, solange keine Schätzung möglich ist */
  restzeitS: number | null;
  schritte: VorgangSchritt[];
  kriterien: VorgangKriterium[];
  runde: number | null;
  maxRunden: number | null;
  /** Kennung der Freigabekarte (Freigaben.tsx), wenn der Vorgang auf sie wartet */
  freigabeId: string | null;
  /** Kennung des Canvas-Elements mit dem (Zwischen-)Ergebnis */
  canvasId: string | null;
};

/** Lichtrahmen am Laptop (host/wamo_host.py, voice-core/activity.py): nur ganze Zahlen in Bildschirmpixeln, nie Titel. */
export type Rechteck = { x: number; y: number; b: number; h: number };
export type Punkt = { x: number; y: number };
export const MARKIERUNG_ARTEN = ["fokus", "klick", "text", "tasten", "scrollen"] as const;
export type Markierung = {
  art: (typeof MARKIERUNG_ARTEN)[number];
  /** Kennung des Laptops, der handelt (Tunnel je Gerät); null beim lokalen Kern */
  geraet: string | null;
  /** Rechnername des gesteuerten PCs, wenn bekannt */
  rechner: string | null;
  fenster: Rechteck;
  monitor: Rechteck;
  /** nur bei Klicks: Punkt der Welle */
  punkt?: Punkt;
};

/**
 * Live-Bild des eigenen Laptops (voice-core/bildstrom.py). "bildstrom" meldet den Zustand, "bild" ist ein einzelnes JPEG
 * (Base64, höchstens LIVE_BILD_B64_MAX Zeichen). Bilder werden nie gespeichert: nur im Arbeitsspeicher gezeichnet.
 */
export const LIVE_BILD_ZUSTAENDE = ["aus", "wartet", "laeuft", "pausiert"] as const;
export const LIVE_BILD_B64_MAX = 150_000;
export const LIVE_BILD_MONITOR_MAX = 16;
export type LiveBildZustand = (typeof LIVE_BILD_ZUSTAENDE)[number];
export type LiveBildMeldung = {
  zustand: LiveBildZustand;
  /** stabiler Code (nicht_erlaubt, schalter_aus, freigabe, vollbild, geschuetzt, ende, ...) */
  grund?: string;
  /** erklärender Satz des Kerns (ohne Bildinhalt) */
  text?: string;
  monitor?: number;
  monitore?: number;
  restS?: number;
};
export type LiveBildFrame = {
  seq: number;
  monitor: number;
  monitore: number;
  breite: number;
  hoehe: number;
  jpeg: string;
  restS: number;
};

export type ServerMessage =
  | ({ type: "bildstrom" } & LiveBildMeldung)
  | ({ type: "bild" } & LiveBildFrame)
  /** ersetzt: Kennung des Elements, das dieses überarbeitet (voice-core/canvas_sitzung.py); die Oberfläche setzt es an dieselbe Stelle */
  | { type: "canvas"; item: CanvasItem; ersetzt?: string }
  /** Reiter schließen (voice-core/tools.py, canvas_schliessen): der offene, alle oder die mit diesen Kennungen; sie bleiben in der Historie */
  | { type: "canvas_schliessen"; ziel: "offen" | "alle" }
  | { type: "canvas_schliessen"; ziel: "ids"; ids: string[] }
  | ({ type: "markierung" } & Markierung)
  | ({ type: "aktivitaet" } & Pick<Activity, "id" | "name" | "detail" | "status">)
  | { type: "vorgang"; vorgang: Vorgang }
  | { type: "sprecher"; index: number }
  | { type: "leiser_stopp"; sofort?: boolean }
  | { type: "stimme_leiser"; an: boolean }
  | { type: "fernzugriff_oeffnen" } // WAMO bittet darum, den Fernzugriff zu zeigen; die Sitzung startet nur der Nutzer, mit einem echten Klick auf Verbinden
  | { type: "freigaben"; job: string; projekt: string; items: FreigabePunkt[] }
  | ({ type: "profil" } & Profil)
  | ({ type: "betrieb" } & Betrieb)
  | ({ type: "gemerkt" } & Gemerkt)
  /** Canvas als Datei gespeichert (Kennung aus dem Register am PC, Name, Ordner, Pfad) oder nicht (Grund); nie ein Dateiinhalt */
  | ({ type: "datei" } & DateiMeldung)
  /** Mail über Outlook: Antwort auf "Zur Freigabe vorbereiten" (ok: die Karte liegt bereit) */
  | { type: "mail_antwort"; ok: boolean; grund?: string }
  /** Mail über Outlook: Stand nach dem Klick (wartet mit Restzeit und Zurückholen, Endstand oder offener Entwurf); nie ein Inhalt */
  | { type: "mail_versand"; id: string | null; zustand: MailVersandZustand; restS?: number; text: string }
  /** Antwort auf "Als OneNote-Seite": Karte liegt bereit, Rückfall als Word-Datei (ok) oder der Grund, warum nicht */
  | { type: "onenote"; ok: boolean; text: string }
  /** Teams-Nachricht: Antwort auf "Zur Freigabe vorbereiten" (ok: die Karte liegt bereit); nie ein Inhalt */
  | { type: "teams_antwort"; ok: boolean; grund?: string }
  // Ohne stand: den Zustand der Startkarte setzt allein die Oberfläche (lib/auftragStart.ts), der Kern kann ihn nicht vorgeben
  | ({ type: "auftrag" } & Omit<Auftrag, "stand">)
  /** Antwort des Kerns auf den Klick "Starten": ok, oder nicht ok mit einem Satz als Grund (voice-core/dev_agent.py) */
  | { type: "auftrag_quittung"; job: string; ok: boolean; grund?: string }
  /** Gespeicherte Aufträge (voice-core/auftrag_entwuerfe.py): Ergebnis einer Aktion mit einem Satz als text (auf dem Draht text bei ok,
   *  grund bei ok false; hier immer text), nach dem Speichern die Kennung der Karte (job), die damit die Sitzung verlässt, und, wenn
   *  lesbar, die Liste (entwuerfe, max) */
  | {
      type: "auftrag_entwuerfe";
      aktion: EntwurfAktion;
      ok: boolean;
      text: string;
      job?: string;
      entwuerfe?: AuftragEntwurf[];
      max?: number;
    }
  /** Aufträge an W.A.I.S. selbst (lib/selbstAuftraege.ts): genau eine Antwort je Aktion, text bei ok und grund bei ok false (hier immer text),
   *  bei ok die frische Liste (auftraege) und die Grenze (max) */
  | {
      type: "selbstauftraege";
      aktion: SelbstAktion;
      ok: boolean;
      text: string;
      auftraege?: SelbstAuftrag[];
      max?: number;
    }
  | { type: "sitzung_beendet"; grund: string; anmelden?: boolean }
  /** Testlabor: der Betreuer hat den Durchlauf beendet; die Seite lädt sich neu (lib/laborNeuladen.ts). Trägt nie Inhalte. */
  | { type: "labor_durchlauf_ende" }
  | ({ type: "modellzugang" } & Modellzugang)
  | ({ type: "kontingent" } & Kontingent)
  /** Kern: still = seit `sekunden` nur digitale Stille vom Mikrofon, ok = wieder Ton (voice-core/audio_monitor.py) */
  | { type: "mikrofon"; zustand: "still" | "fehlt" | "ok"; sekunden: number }
  /** Stimmerkennung, Stand (auf dem Draht {type:"stimme", status, modus}); modus fehlt bei einem Kern, der ihn nicht mitschickt */
  | { type: "stimme_status"; status: StimmeStatus; modus: StimmeModus | null }
  /** Stimmerkennung, Ergebnis der letzten Äußerung (auf dem Draht {type:"stimme", ergebnis, wert, modus}); wert 0 bis 1 oder leer.
   *  ignoriert (freiwillig): im strengen Modus hat der Kern eine fremde oder unklare Äußerung verworfen, sie erreicht das Sprachmodell
   *  nicht (voice-core/stimme_waechter.py). zeit (freiwillig): Zeitstempel des endgültigen Transkripts dieser Äußerung (derselbe wie in
   *  user-transcription); damit gibt der Chat links den zurückgehaltenen Satz frei oder verwirft ihn (lib/stimmFilter.ts). */
  | {
      type: "stimme_ergebnis";
      ergebnis: StimmeErgebnis;
      wert: number | null;
      modus: StimmeModus | null;
      ignoriert?: boolean;
      zeit?: string;
    }
  /** Einlernen des Stimmabdrucks: Zustand, aufgenommene Sekunden reiner Sprache, Ziel in Sekunden, bei fehler ein Satz dazu */
  | { type: "stimmabdruck"; status: AbdruckStatus; sekunden?: number; ziel?: number; text?: string; mikrofon?: string }
  /** Einwilligungstext zum Stimmabdruck, kommt vom Kern; version geht beim Start in der Antwort mit zurück */
  | { type: "stimmabdruck_einwilligung"; version: string; text: string }
  /** Eingelernte Mikrofone, ein Abdruck je Mikrofon (Kern voice-core/stimme_mikrofon.py, höchstens max; max 1: der Kern kann nur einen) */
  | { type: "stimmabdruck_mikrofone"; mikrofone: StimmMikrofonEintrag[]; max: number }
  /** Jira-Stories (lib/jiraStory.ts): der Kern bietet sie an (Knopf am Canvas), und was nach dem Klick auf die Karte geschah */
  | ({ type: "jira_status" } & JiraStatus)
  | ({ type: "jira_ergebnis" } & JiraErgebnis);

/** Stimmerkennung des Kerns (voice-core): Stand, Betriebsart und Ergebnis der letzten Äußerung, dazu das Einlernen des Stimmabdrucks. */
export const STIMME_STATUS = ["aus", "fehlt", "laedt", "kaputt", "bereit"] as const;
export type StimmeStatus = (typeof STIMME_STATUS)[number];
export const STIMME_MODI = ["aus", "beobachten", "streng"] as const;
export type StimmeModus = (typeof STIMME_MODI)[number];
export const STIMME_ERGEBNISSE = ["eigen", "fremd", "unklar"] as const;
export type StimmeErgebnis = (typeof STIMME_ERGEBNISSE)[number];
/** Obergrenze für zeit im Urteil (Zeitstempel eines Transkripts, ISO 8601 braucht rund 32 Zeichen) */
const ZEIT_MAX = 64;
export const ABDRUCK_STATUS = ["start", "aufnahme", "rechnet", "fertig", "fehler", "abgebrochen", "geloescht"] as const;
/** Kennung eines eingelernten Mikrofons wie im Kern (stimme_mikrofon.KENNUNG_RE) */
export const MIKROFON_KENNUNG = /^(unbekannt|[0-9a-f]{32})$/;
/** So viele Abdrücke nimmt der Kern je Person höchstens (stimme_mikrofon.MAX_ABDRUECKE) */
export const MIKROFONE_MAX = 3;
export type StimmMikrofonEintrag = { kennung: string; name: string | null; am: string | null };
export type AbdruckStatus = (typeof ABDRUCK_STATUS)[number];
/** Obergrenze des Einwilligungstextes (Zeichen): ein längerer Text wird abgelehnt, nie gekürzt */
export const EINWILLIGUNG_MAX = 4000;

type Roh = Record<string, unknown>;

const isObj = (v: unknown): v is Roh => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const oneOf = <T extends string>(v: unknown, werte: readonly T[]): v is T =>
  isStr(v) && (werte as readonly string[]).includes(v);
/** Auf höchstens max UTF-16-Einheiten kürzen, ohne ein Zeichen außerhalb der Grundebene (Emoji) in der Mitte zu trennen. */
function schnitt(t: string, max: number): string {
  if (t.length <= max) return t;
  let ende = max;
  const letzte = t.charCodeAt(ende - 1);
  if (letzte >= 0xd800 && letzte <= 0xdbff) ende -= 1; // die erste Hälfte eines Paares bliebe allein stehen
  return t.slice(0, ende);
}

const optStr = (v: unknown, max = 80) => (isStr(v) && v.trim() ? schnitt(v.trim(), max) : undefined);

const CANVAS_KINDS = ["tabelle", "code", "dokument", "mermaid", "bild"] as const;

// Grenzen wie host/windows_control.py (Windows rechnet Koordinaten mit 16 Bit), voice-core/activity.py und desktop/lichtrahmen.js
export const MARK_POS_MIN = -32768;
export const MARK_POS_MAX = 32767;
export const MARK_GROESSE_MAX = 32768;
const ganz = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
const pos = (v: unknown): v is number => ganz(v) && v >= MARK_POS_MIN && v <= MARK_POS_MAX;
const EINWILLIGUNG_VERSION = /^[A-Za-z0-9._-]{1,40}$/;
const GERAET_KENNUNG = /^pc-[a-z0-9]+(?:-[a-z0-9]+)*$/;
const RECHNERNAME = /^[A-Za-z0-9._-]{1,63}$/;

function rechteck(v: unknown): Rechteck | null {
  if (!isObj(v) || !pos(v.x) || !pos(v.y)) return null;
  const { b, h } = v;
  if (!ganz(b) || !ganz(h) || b < 1 || h < 1 || b > MARK_GROESSE_MAX || h > MARK_GROESSE_MAX) return null;
  return { x: v.x, y: v.y, b, h };
}

/** Markierung des Lichtrahmens prüfen: feste Felder, ganze Zahlen mit Obergrenzen, sonst null. */
function markierung(m: Roh): Markierung | null {
  if (!oneOf(m.art, MARKIERUNG_ARTEN)) return null;
  const fenster = rechteck(m.fenster);
  const monitor = rechteck(m.monitor);
  if (!fenster || !monitor) return null;
  const geraet = m.geraet ?? null;
  if (geraet !== null && !(isStr(geraet) && geraet.length <= 23 && GERAET_KENNUNG.test(geraet))) return null;
  const rechner = m.rechner ?? null;
  if (rechner !== null && !(isStr(rechner) && RECHNERNAME.test(rechner))) return null;
  const ergebnis: Markierung = { art: m.art, geraet, rechner, fenster, monitor };
  if (m.art === "klick" && isObj(m.punkt) && pos(m.punkt.x) && pos(m.punkt.y)) {
    ergebnis.punkt = { x: m.punkt.x, y: m.punkt.y };
  }
  return ergebnis;
}

/** Kennung einer Datei im Register am PC (host/office_ablage.py). */
const DATEI_KENNUNG = /^[0-9a-f]{16}$/;
/** Kennung eines geplanten Versands am PC (host/office_outlook_com.py). */
const VERSAND_KENNUNG = /^[0-9a-f]{16}$/;
/** Längste Freigabekarte: Mails mit ganzem Text (voice-core/activity.py FREIGABE_DETAIL_ZEICHEN_MAIL), alle übrigen Karten kürzer. */
export const FREIGABE_DETAIL_MAX = 8000;
export const FREIGABE_DETAIL_KURZ = 2000;

/** Formate aus betrieb.office: nur bekannte, in fester Reihenfolge; leer oder kaputt heißt keine. */
function officeFormate(v: unknown): OfficeFormat[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const formate = OFFICE_FORMATE.filter((f) => v.includes(f));
  return formate.length ? formate : undefined;
}

/** Grenzen gegen übergroße Canvas-Inhalte (Speicher, Darstellung). */
export const CANVAS_MAX_ZEILEN = 500;
export const CANVAS_MAX_SPALTEN = 30;
export const CANVAS_MAX_TEXT = 200_000;
export const BILD_URL_MAX = 2000;

/**
 * Adresse eines Bildes von außen (canvas_zeigen mit typ bild, voice-core/tools.bild_url): nur https, ohne Zugangsdaten, ohne Leer- und
 * Steuerzeichen, höchstens BILD_URL_MAX Zeichen, nur ein öffentlicher Name (letzte Stufe beginnt mit einem Buchstaben: keine IP-Adresse,
 * auch keine Kurzform wie 127.1, die URL schon zu 127.0.0.1 normalisiert; keine Namen im Netz des Büros); sonst null. Die Oberfläche lädt
 * sie nie selbst (die CSP erlaubt keine fremden Bilder), sie zeigt nur einen Verweis, den die Person bewusst öffnet.
 */
export function bildUrl(roh: unknown): string | null {
  if (!isStr(roh) || !roh || roh.length > BILD_URL_MAX || /[\s\u0000-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/.test(roh)) return null;
  try {
    const u = new URL(roh);
    if (u.protocol !== "https:" || u.username || u.password) return null;
    const host = u.hostname.toLowerCase();
    const letzte = host.split(".").pop() ?? "";
    if (!host.includes(".") || !/^(?:[a-z][a-z0-9-]*[a-z0-9]|xn--[a-z0-9-]+)$/.test(letzte) || BILD_HOST_INTERN.test(host)) return null;
    return u.href;
  } catch {
    return null;
  }
}
const BILD_HOST_INTERN = /\.(?:local|lan|intern|internal|home|localhost|box|arpa|test|invalid|corp|localdomain)$/;

// Steuerzeichen (außer Zeilenumbruch und Tab) und Bidi-Steuerzeichen, die Text optisch umdrehen können
const STEUER = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;

/** Text bereinigen und kürzen; gekürzte Texte enden sichtbar mit "… (gekürzt)". */
export function sauber(text: string, max: number, zeilen = true): string {
  let t = text.replace(STEUER, "");
  if (!zeilen) t = t.replace(/[\r\n\t]+/g, " ");
  return t.length > max ? `${schnitt(t, max)} … (gekürzt)` : t;
}

/** Eine Zeile Text für eine Anzeige mit fester Länge: wie sauber (ohne Steuer-, Bidi- und Nullbreitenzeichen, Umbrüche zu Leerzeichen),
 *  Leerraum zusammengefasst, hart auf max Einheiten gekürzt (ohne den Zusatz "(gekürzt)"). */
function zeile(roh: unknown, max: number): string | undefined {
  if (!isStr(roh)) return undefined;
  const t = sauber(schnitt(roh, 1000), 1000, false).replace(/\s+/g, " ").trim();
  return t ? schnitt(t, max) : undefined;
}

/** Abnahmekriterien der Auftragskarte: nur Texte, höchstens 5 (aus den ersten 50 Einträgen), je höchstens 300 Zeichen, bereinigt. */
function abnahmeKriterien(roh: unknown): string[] {
  if (!Array.isArray(roh)) return [];
  return roh
    .slice(0, 50)
    .filter(isStr)
    .map((t) => sauber(t, AUFTRAG_ABNAHME_ZEICHEN, false).trim())
    .filter((t) => t !== "")
    .slice(0, AUFTRAG_ABNAHME_MAX);
}

const REPO_NAME = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;

/** Ziel-Repo der Auftragskarte: nur owner/name (wie der Kern es prüft), alles andere und Fehlendes ergibt undefined. */
function repoName(roh: unknown): string | undefined {
  return isStr(roh) && REPO_NAME.test(roh.trim()) ? roh.trim() : undefined;
}

/** Kennung eines gespeicherten Auftrags (UUID, wie der Kern sie schreibt); auch useWamo prüft damit vor dem Senden. */
export const ENTWURF_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Zeitpunkt nur in einem plausiblen Bereich (2020 bis 2100): ein riesiger Wert ergäbe ein ungültiges Datum, an dem die Anzeige scheitert
const ENTWURF_MS_MIN = Date.UTC(2020, 0, 1);
const ENTWURF_MS_MAX = Date.UTC(2100, 0, 1);

/** Liste der gespeicherten Aufträge: nur Einträge mit gültiger Kennung, Texte einzeilig und gekürzt, höchstens ENTWURF_LISTE_MAX. */
function entwurfListe(roh: unknown[]): AuftragEntwurf[] {
  const liste: AuftragEntwurf[] = [];
  for (const e of roh.slice(0, ENTWURF_LISTE_MAX)) {
    if (!isObj(e) || !isStr(e.id) || !ENTWURF_ID.test(e.id)) continue;
    const roheMs = e.gespeichert_ms;
    const ms = typeof roheMs === "number" && roheMs >= ENTWURF_MS_MIN && roheMs <= ENTWURF_MS_MAX ? roheMs : 0;
    const eintrag: AuftragEntwurf = {
      id: e.id.toLowerCase(),
      titel: zeile(e.titel, 80) ?? "Auftrag",
      projekt: zeile(e.projekt, 80) ?? "",
      art: zeile(e.art, 60) ?? "",
      gespeichertMs: Math.round(ms),
    };
    const repo = repoName(e.repo);
    if (repo) eintrag.repo = repo;
    liste.push(eintrag);
  }
  return liste;
}

/** Ergebnis eines Auftrags an W.A.I.S. selbst: mehrzeilig erlaubt, aber ohne Steuerzeichen, mit höchstens einer Leerzeile in Folge, gekürzt. */
function selbstErgebnis(roh: unknown): string | undefined {
  if (!isStr(roh)) return undefined;
  const t = sauber(schnitt(roh, SELBST_ERGEBNIS_MAX * 2), SELBST_ERGEBNIS_MAX)
    .replace(/\r\n?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return t || undefined;
}

/** Liste der Aufträge an W.A.I.S. selbst: nur Einträge mit gültiger Nummer und bekanntem Status (die Nummer zählt einmal, der erste Eintrag
 *  gilt; eine unbekannte Quelle lässt nur die Quelle weg), Texte einzeilig und gekürzt, Aufzählungen und Zahlen geprüft, höchstens
 *  SELBST_LISTE_MAX in der Reihenfolge des Kerns; gelesen werden höchstens doppelt so viele Einträge (Ungültige zählen mit). */
function selbstAuftragListe(roh: unknown[]): SelbstAuftrag[] {
  const liste: SelbstAuftrag[] = [];
  const gesehen = new Set<number>();
  for (const e of roh.slice(0, SELBST_LISTE_MAX * 2)) {
    if (liste.length >= SELBST_LISTE_MAX) break;
    if (!isObj(e)) continue;
    const nr = e.nr;
    if (typeof nr !== "number" || !Number.isSafeInteger(nr) || nr < 1 || nr > 2_147_483_647 || gesehen.has(nr)) continue;
    if (!oneOf(e.status, SELBST_STATUS)) continue;
    gesehen.add(nr);
    const ms = e.erstellt_ms;
    const eintrag: SelbstAuftrag = {
      nr,
      titel: zeile(e.titel, SELBST_TITEL_MAX) ?? "Auftrag",
      art: zeile(e.art, 60) ?? "",
      prioritaet: SELBST_PRIORITAETEN.find((p) => p === e.prioritaet) ?? 2,
      status: e.status,
      unsicher: e.unsicher === true,
      erstelltMs: typeof ms === "number" && ms >= ENTWURF_MS_MIN && ms <= ENTWURF_MS_MAX ? Math.round(ms) : 0,
    };
    if (oneOf(e.quelle, SELBST_QUELLEN)) eintrag.quelle = e.quelle;
    if (oneOf(e.bearbeiter, SELBST_BEARBEITER)) eintrag.bearbeiter = e.bearbeiter;
    const ergebnis = selbstErgebnis(e.ergebnis);
    if (ergebnis) eintrag.ergebnis = ergebnis;
    liste.push(eintrag);
  }
  return liste;
}

const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** Limits des Kontingents prüfen: nur bekannte Arten, Zahlen im Wertebereich, ISO-Zeiten; Doppelte zählen einmal. */
function kontingentLimits(roh: unknown): KontingentLimit[] {
  if (!Array.isArray(roh)) return [];
  const gefunden = new Map<string, KontingentLimit>();
  for (const e of roh.slice(0, 10)) {
    if (!isObj(e) || !oneOf(e.art, KONTINGENT_ARTEN) || gefunden.has(e.art)) continue;
    const l: KontingentLimit = { art: e.art };
    if (typeof e.prozent === "number" && Number.isFinite(e.prozent) && e.prozent >= 0 && e.prozent <= 1000) {
      l.prozent = Math.round(e.prozent * 10) / 10;
    }
    if (isStr(e.endet) && ISO_UTC.test(e.endet)) l.endet = e.endet;
    if (oneOf(e.status, ["ok", "warnung", "erreicht"] as const)) l.status = e.status;
    if (Object.keys(l).length > 1) gefunden.set(e.art, l);
  }
  return KONTINGENT_ARTEN.flatMap((a) => gefunden.get(a) ?? []);
}

const AKTIVITAET_STATUS = ["laeuft", "fertig", "abgelehnt", "fehler", "wartet"] as const;

const zelle = (v: unknown) => (v === null || v === undefined ? "" : String(v));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PROJEKT = /^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$/;

/** Angaben zum Teilen (voice-core/dev_agent.py: teilbar_id, teilbar_projekt; teilen_werkzeuge.py: geteilt). */
function canvasZusatz(v: Record<string, unknown>): Pick<CanvasItem, "teilbar" | "geteilt"> {
  const zusatz: Pick<CanvasItem, "teilbar" | "geteilt"> = {};
  if (isStr(v.teilbar_id) && UUID.test(v.teilbar_id)) {
    zusatz.teilbar = {
      id: v.teilbar_id,
      projekt: isStr(v.teilbar_projekt) && PROJEKT.test(v.teilbar_projekt) ? v.teilbar_projekt : undefined,
    };
  }
  const geteilt = v.geteilt;
  if (isObj(geteilt) && (geteilt.recht === "lesen" || geteilt.recht === "bearbeiten")) {
    zusatz.geteilt = { von: isStr(geteilt.von) ? sauber(geteilt.von, 60, false) : null, recht: geteilt.recht };
  }
  return zusatz;
}

function canvasItem(v: unknown): CanvasItem | null {
  const item = canvasGrund(v);
  return item && isObj(v) ? { ...item, ...canvasZusatz(v) } : item;
}

function canvasGrund(v: unknown): CanvasItem | null {
  if (!isObj(v) || !oneOf(v.kind, CANVAS_KINDS) || !isStr(v.title)) return null;
  const id = isStr(v.id) ? v.id.slice(0, 100) : null;
  const title = sauber(v.title, 200, false);
  switch (v.kind) {
    case "tabelle":
      if (!Array.isArray(v.columns) || !Array.isArray(v.rows)) return null;
      {
        const rows = v.rows.filter(Array.isArray) as unknown[][];
        const gekuerzt = rows.length > CANVAS_MAX_ZEILEN;
        return {
          id,
          kind: "tabelle",
          title: gekuerzt ? `${title} (erste ${CANVAS_MAX_ZEILEN} Zeilen)` : title,
          columns: v.columns.slice(0, CANVAS_MAX_SPALTEN).map((c) => sauber(zelle(c), 200, false)),
          rows: rows
            .slice(0, CANVAS_MAX_ZEILEN)
            .map((row) => row.slice(0, CANVAS_MAX_SPALTEN).map((c) => sauber(zelle(c), 2000))),
        };
      }
    case "code":
      if (!isStr(v.text)) return null;
      return {
        id,
        kind: "code",
        title,
        text: sauber(v.text, CANVAS_MAX_TEXT),
        language: isStr(v.language) ? sauber(v.language, 30, false) : undefined,
      };
    case "dokument":
      return isStr(v.text) ? { id, kind: v.kind, title, text: sauber(v.text, CANVAS_MAX_TEXT) } : null;
    case "mermaid":
      // Diagrammtext nicht kürzen (sonst ungültig): zu groß heißt ablehnen
      return isStr(v.text) && v.text.length <= CANVAS_MAX_TEXT ? { id, kind: v.kind, title, text: v.text.replace(STEUER, "") } : null;
    case "bild": {
      // vom Kern nur eine Adresse; eigene Bilddaten (datei) legt nur die Oberfläche selbst an (lib/canvasDatei.ts), nie eine Nachricht
      const url = bildUrl(v.url);
      return url ? { id, kind: "bild", title, url, alt: isStr(v.alt) ? sauber(v.alt, 300, false) : undefined } : null;
    }
  }
}

const B64 = /^[A-Za-z0-9+/]+={0,2}$/;
const ganzIn = (v: unknown, von: number, bis: number): v is number => ganz(v) && v >= von && v <= bis;

/** Ein Bild des Live-Bilds prüfen: JPEG-Kopf, Base64, Größengrenze, ganze Zahlen. Sonst null (nie ein Teilergebnis). */
function liveBildFrame(m: Roh): LiveBildFrame | null {
  const { jpeg } = m;
  if (!isStr(jpeg) || jpeg.length < 8 || jpeg.length > LIVE_BILD_B64_MAX || !jpeg.startsWith("/9j/") || !B64.test(jpeg)) return null;
  if (!ganzIn(m.seq, 1, 2 ** 31) || !ganzIn(m.monitor, 1, LIVE_BILD_MONITOR_MAX) || !ganzIn(m.monitore, 1, LIVE_BILD_MONITOR_MAX)) return null;
  if (m.monitor > m.monitore) return null;
  if (!ganzIn(m.breite, 1, 4096) || !ganzIn(m.hoehe, 1, 4096) || !ganzIn(m.rest_s, 0, 86_400)) return null;
  return { seq: m.seq, monitor: m.monitor, monitore: m.monitore, breite: m.breite, hoehe: m.hoehe, jpeg, restS: m.rest_s };
}

const zahl = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const kurzerText = (v: unknown, max: number): string | null => (isStr(v) && v.trim() ? sauber(v.trim(), max, false) : null);
const anteil = (v: unknown) => (zahl(v) ? Math.round(Math.max(0, Math.min(1, v)) * 1000) / 1000 : 0);

/** Ein Vorgang des Kerns: feste Felder, Wertebereiche, Grenzen und bereinigte Texte; ohne Kennung, Titel oder Status null. */
function vorgang(v: unknown): Vorgang | null {
  if (!isObj(v) || !isStr(v.id) || !v.id || !isStr(v.titel) || !v.titel.trim() || !oneOf(v.status, VORGANG_STATUS)) return null;
  const schritte: VorgangSchritt[] = [];
  for (const s of Array.isArray(v.schritte) ? v.schritte : []) {
    if (schritte.length >= VORGANG_MAX_SCHRITTE) break;
    if (!isObj(s) || !isStr(s.titel) || !s.titel.trim()) continue;
    schritte.push({
      nr: schritte.length + 1,
      titel: sauber(s.titel.trim(), 160, false),
      status: oneOf(s.status, VORGANG_SCHRITT_STATUS) ? s.status : "offen",
      fortschritt: anteil(s.fortschritt),
      detail: kurzerText(s.detail, 200),
    });
  }
  const kriterien: VorgangKriterium[] = [];
  for (const k of Array.isArray(v.kriterien) ? v.kriterien : []) {
    if (kriterien.length >= VORGANG_MAX_KRITERIEN) break;
    if (!isObj(k) || !isStr(k.text) || !k.text.trim()) continue;
    kriterien.push({
      text: sauber(k.text.trim(), 160, false),
      erfuellt: typeof k.erfuellt === "boolean" ? k.erfuellt : null,
      hinweis: kurzerText(k.hinweis, 200),
    });
  }
  const ergebnis = isObj(v.ergebnis) ? v.ergebnis : null;
  return {
    id: v.id.slice(0, 100),
    titel: sauber(v.titel.trim(), 200, false),
    art: oneOf(v.art, VORGANG_ARTEN) ? v.art : "sonstiges",
    status: v.status,
    gestartetMs: zahl(v.gestartet_ms) && v.gestartet_ms >= 0 ? Math.round(v.gestartet_ms) : 0,
    beendetMs: zahl(v.beendet_ms) && v.beendet_ms >= 0 ? Math.round(v.beendet_ms) : null,
    gesamt: anteil(v.gesamt),
    restzeitS: ganzIn(v.restzeit_s, 0, 359_999) ? v.restzeit_s : null,
    schritte,
    kriterien,
    runde: ganzIn(v.runde, 1, 99) ? v.runde : null,
    maxRunden: ganzIn(v.max_runden, 1, 99) ? v.max_runden : null,
    freigabeId: isStr(v.freigabe_id) && v.freigabe_id ? v.freigabe_id.slice(0, 100) : null,
    canvasId: ergebnis && isStr(ergebnis.canvas_id) && ergebnis.canvas_id ? ergebnis.canvas_id.slice(0, 100) : null,
  };
}

/** Prüft eine Servernachricht und gibt sie typisiert zurück; alles Unbekannte wird null. */
export function parseServerMessage(data: unknown): ServerMessage | null {
  if (!isObj(data) || !isStr(data.type)) return null;
  const m = data;
  switch (m.type) {
    case "canvas": {
      const item = canvasItem(m.item);
      if (!item) return null;
      return isStr(m.ersetzt) && m.ersetzt && m.ersetzt.length <= 100 ? { type: "canvas", item, ersetzt: m.ersetzt } : { type: "canvas", item };
    }
    case "canvas_schliessen": {
      if (m.ziel === "offen" || m.ziel === "alle") return { type: "canvas_schliessen", ziel: m.ziel };
      if (m.ziel !== "ids" || !Array.isArray(m.ids)) return null;
      const ids = m.ids.filter((id): id is string => isStr(id) && id.length > 0 && id.length <= 100).slice(0, 10);
      return ids.length ? { type: "canvas_schliessen", ziel: "ids", ids } : null;
    }
    case "bild": {
      const frame = liveBildFrame(m);
      return frame ? { type: "bild", ...frame } : null;
    }
    case "bildstrom": {
      if (!oneOf(m.zustand, LIVE_BILD_ZUSTAENDE)) return null;
      return {
        type: "bildstrom",
        zustand: m.zustand,
        grund: isStr(m.grund) && /^[a-z_]{1,40}$/.test(m.grund) ? m.grund : undefined,
        text: isStr(m.text) && m.text.trim() ? sauber(m.text.trim(), 300, false) : undefined,
        monitor: ganzIn(m.monitor, 1, LIVE_BILD_MONITOR_MAX) && !(ganzIn(m.monitore, 1, LIVE_BILD_MONITOR_MAX) && m.monitor > m.monitore) ? m.monitor : undefined,
        monitore: ganzIn(m.monitore, 1, LIVE_BILD_MONITOR_MAX) ? m.monitore : undefined,
        restS: ganzIn(m.rest_s, 0, 86_400) ? m.rest_s : undefined,
      };
    }
    case "markierung": {
      const mk = markierung(m);
      return mk ? { type: "markierung", ...mk } : null;
    }
    case "aktivitaet":
      if (!isStr(m.id) || !m.id || !isStr(m.name) || !m.name || !oneOf(m.status, AKTIVITAET_STATUS)) return null;
      return {
        type: "aktivitaet",
        id: m.id.slice(0, 100),
        name: sauber(m.name, 60, false),
        detail: isStr(m.detail) ? sauber(m.detail, 200, false) : "",
        status: m.status,
      };
    case "vorgang": {
      const v = vorgang(m.vorgang);
      return v ? { type: "vorgang", vorgang: v } : null;
    }
    case "sprecher":
      return typeof m.index === "number" && Number.isFinite(m.index)
        ? { type: "sprecher", index: Math.max(0, Math.min(7, Math.trunc(m.index))) }
        : null;
    case "leiser_stopp":
      return { type: "leiser_stopp", sofort: m.sofort === true };
    case "stimme_leiser":
      return typeof m.an === "boolean" ? { type: "stimme_leiser", an: m.an } : null;
    case "fernzugriff_oeffnen":
      return { type: "fernzugriff_oeffnen" }; // ohne Nutzdaten (kein Ziel, nie ein Start): Ziel und Klick gehören dem Nutzer
    case "freigaben": {
      if (!isStr(m.job) || !Array.isArray(m.items)) return null;
      const items = m.items
        .filter((it): it is Roh => isObj(it) && isStr(it.id) && isStr(it.grund) && isStr(it.detail))
        .map((it) => ({
          id: (it.id as string).slice(0, 100),
          grund: sauber(it.grund as string, 200, false),
          // Lange Karte nur für PC-Freigaben (dort begrenzt der Kern jede Aktion außer Mails auf 2000); Labor und Geräte bleiben bei 2000
          detail: sauber(it.detail as string, m.job === "pc" ? FREIGABE_DETAIL_MAX : FREIGABE_DETAIL_KURZ),
          // erst bereinigen, dann kürzen: so erscheint "(gekürzt)", wenn etwas fehlt
          von: isStr(it.von) && it.von.trim() ? sauber(it.von.trim(), 60, false) : undefined,
          ziel: isStr(it.ziel) && it.ziel.trim() ? sauber(it.ziel.trim(), 200, false) : undefined,
          anlass: isStr(it.anlass) && it.anlass.trim() ? sauber(it.anlass.trim(), 200, false) : undefined,
          warnung: isStr(it.warnung) && it.warnung.trim() ? zeile(it.warnung, 300) : undefined,
          gueltigS:
            typeof it.gueltig_s === "number" && Number.isInteger(it.gueltig_s) && it.gueltig_s > 0 && it.gueltig_s <= 3600
              ? it.gueltig_s
              : undefined,
          // nur der Eintrag "einreichen" trägt die Karte des persönlichen GitHub-Wegs; ungültig heißt: keine Karte
          einreichen: it.id === EINREICHEN_ID ? (pruefeEinreichen(it.einreichen) ?? undefined) : undefined,
        }))
        .filter((it) => it.id !== EINREICHEN_ID || it.einreichen !== undefined);
      return {
        type: "freigaben",
        job: m.job.slice(0, 100),
        projekt: isStr(m.projekt) ? sauber(m.projekt, 80, false) : "",
        items,
      };
    }
    case "profil":
      if (!isStr(m.name) || !m.name.trim() || !oneOf(m.rolle, ["admin", "mitglied"] as const)) return null;
      return { type: "profil", name: sauber(m.name.trim(), 60, false), rolle: m.rolle };
    case "betrieb": {
      if (!oneOf(m.modus, ["lokal", "buero"] as const)) return null;
      const modelle = isObj(m.modelle) ? m.modelle : {};
      const latenz = typeof m.pc_latenz_ms === "number" && Number.isFinite(m.pc_latenz_ms) ? m.pc_latenz_ms : undefined;
      return {
        type: "betrieb",
        modus: m.modus,
        modelle: { llm: optStr(modelle.llm), stt: optStr(modelle.stt), tts: optStr(modelle.tts) },
        pc: oneOf(m.pc, ["verbindet", "verbunden", "getrennt", "aus", "gesperrt"] as const) ? m.pc : "aus",
        ort: oneOf(m.ort, ["cloud", "haus"] as const) ? m.ort : undefined,
        pcLatenzMs: latenz !== undefined ? Math.max(0, Math.round(latenz)) : undefined,
        pcSteuerung: oneOf(m.pc_steuerung, ["an", "aus"] as const) ? m.pc_steuerung : undefined,
        pcStufe: oneOf(m.pc_stufe, ["admin", "mitglied"] as const) ? m.pc_stufe : undefined,
        entwicklung: oneOf(m.entwicklung, ["an", "aus"] as const) ? m.entwicklung : undefined,
        pcName: isStr(m.pc_name) && /^[A-Za-z0-9._-]{1,63}$/.test(m.pc_name) ? m.pc_name : undefined,
        pcBelegt: m.pc_belegt === true ? true : undefined,
        modellModus: oneOf(m.modell_modus, MODELL_MODI) ? m.modell_modus : undefined,
        modellQuelle: oneOf(m.modell_quelle, MODELL_QUELLEN) ? m.modell_quelle : undefined,
        modellHinweis: optStr(m.modell_hinweis, 200),
        entwicklungGrund: zeile(m.entwicklung_grund, 120),
        office: officeFormate(m.office),
        mail: m.mail === true ? true : undefined,
        onenote: m.onenote === true ? true : undefined,
        teams: m.teams === true ? true : undefined,
        spracheGrund: zeile(m.sprache_grund, 160),
      };
    }
    case "onenote":
      if (typeof m.ok !== "boolean") return null;
      return { type: "onenote", ok: m.ok, text: zeile(m.text, 400) ?? (m.ok ? "Erledigt." : "Nicht angelegt.") };
    case "datei": {
      if (m.ok === false) return { type: "datei", ok: false, grund: zeile(m.grund, 300) ?? "Nicht gespeichert." };
      const name = zeile(m.name, 200);
      if (m.ok !== true || !isStr(m.kennung) || !DATEI_KENNUNG.test(m.kennung) || !name) return null;
      return {
        type: "datei",
        ok: true,
        kennung: m.kennung,
        name,
        format: istOfficeFormat(m.format) ? m.format : undefined,
        ordner: zeile(m.ordner, 80),
        pfad: zeile(m.pfad, 400),
        geoeffnet: m.geoeffnet === true,
      };
    }
    case "mail_antwort":
      if (typeof m.ok !== "boolean") return null;
      return m.ok ? { type: "mail_antwort", ok: true } : { type: "mail_antwort", ok: false, grund: zeile(m.grund, 300) ?? "Nicht vorbereitet." };
    case "teams_antwort":
      if (typeof m.ok !== "boolean") return null;
      return m.ok
        ? { type: "teams_antwort", ok: true }
        : { type: "teams_antwort", ok: false, grund: zeile(m.grund, 300) ?? "Nicht vorbereitet." };
    case "mail_versand": {
      const id = m.id ?? null;
      if ((id !== null && !(isStr(id) && VERSAND_KENNUNG.test(id))) || !oneOf(m.zustand, MAIL_VERSAND_ZUSTAENDE)) return null;
      return {
        type: "mail_versand",
        id,
        zustand: m.zustand,
        restS: ganzIn(m.rest_s, 0, 120) ? m.rest_s : undefined,
        text: zeile(m.text, 300) ?? "",
      };
    }
    case "gemerkt":
      if (
        !oneOf(m.bereich, ["persoenlich", "gemeinsam"] as const) ||
        !oneOf(m.status, ["aktiv", "vorgeschlagen"] as const)
      )
        return null;
      return {
        type: "gemerkt",
        bereich: m.bereich,
        status: m.status,
        text: isStr(m.text) ? sauber(m.text, 280, false) : "",
        id: optStr(m.id, 64),
      };
    case "auftrag":
      // Auftragstext vollständig zeigen (großzügige Grenze), aber ohne Steuer- und Bidi-Zeichen
      if (!isStr(m.job) || !m.job || !isStr(m.auftrag) || !m.auftrag.trim()) return null;
      return {
        type: "auftrag",
        job: m.job.slice(0, 100),
        projekt: isStr(m.projekt) ? sauber(m.projekt, 80, false) : "",
        art: isStr(m.art) ? sauber(m.art, 60, false) : "",
        auftrag: sauber(m.auftrag, 20_000),
        abnahme: abnahmeKriterien(m.abnahme),
        repo: repoName(m.repo),
        github: auftragGithub(m.github),
      };
    case "auftrag_quittung": {
      if (!isStr(m.job) || !m.job || typeof m.ok !== "boolean") return null;
      const grund = m.ok || !isStr(m.grund) ? "" : sauber(m.grund, 300, false).trim();
      return { type: "auftrag_quittung", job: m.job.slice(0, 100), ok: m.ok, grund: grund || undefined };
    }
    case "auftrag_entwuerfe": {
      if (!oneOf(m.aktion, ENTWURF_AKTIONEN) || typeof m.ok !== "boolean") return null;
      const satz = zeile(m.ok ? m.text : m.grund, 300);
      const aus: Extract<ServerMessage, { type: "auftrag_entwuerfe" }> = {
        type: "auftrag_entwuerfe",
        aktion: m.aktion,
        ok: m.ok,
        text: satz ?? (m.ok ? "" : "Das ging nicht."),
      };
      if (isStr(m.job) && m.job) aus.job = m.job.slice(0, 100);
      if (Array.isArray(m.entwuerfe)) aus.entwuerfe = entwurfListe(m.entwuerfe);
      if (typeof m.max === "number" && Number.isInteger(m.max) && m.max >= 1 && m.max <= 1000) aus.max = m.max;
      return aus;
    }
    case "selbstauftraege": {
      if (!oneOf(m.aktion, SELBST_AKTIONEN) || typeof m.ok !== "boolean") return null;
      // bei ok false steht der Satz laut Vertrag in grund; fehlt er, gilt text
      const satz = zeile(m.ok ? m.text : isStr(m.grund) ? m.grund : m.text, 300);
      const aus: Extract<ServerMessage, { type: "selbstauftraege" }> = {
        type: "selbstauftraege",
        aktion: m.aktion,
        ok: m.ok,
        text: satz ?? (m.ok ? "" : "Das ging nicht."),
      };
      if (Array.isArray(m.auftraege)) aus.auftraege = selbstAuftragListe(m.auftraege);
      if (typeof m.max === "number" && Number.isInteger(m.max) && m.max >= 1 && m.max <= SELBST_MAX_OBERGRENZE) aus.max = m.max;
      return aus;
    }
    case "labor_durchlauf_ende":
      return { type: "labor_durchlauf_ende" }; // keine Felder übernehmen, nur das Ereignis
    case "sitzung_beendet":
      // Kern beendet die Sitzung selbst (Profil gesperrt, Rolle geändert, Höchstdauer erreicht)
      // anmelden: der Kern verlangt eine neue Anmeldung (Anmeldung zu alt); die Oberfläche meldet dann ab
      return {
        type: "sitzung_beendet",
        grund: isStr(m.grund) ? sauber(m.grund, 200, false) : "",
        anmelden: m.anmelden === true ? true : undefined,
      };
    case "modellzugang": {
      if (!oneOf(m.aktion, ["status", "hinterlegen", "loeschen", "modus", "stimme", "modell", "haus_stimme"] as const)) return null;
      // Minutengenau, mit Zeitzone (der Kern liefert UTC mit +00:00): ohne sie läse der Browser den Wert als Ortszeit
      const zeit = (v: unknown) => {
        const t = isStr(v) ? /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?/.exec(v) : null;
        return t ? t[1] + (t[2] ?? "") : undefined;
      };
      const vier = (v: unknown) => (isStr(v) && /^[A-Za-z0-9_-]{4}$/.test(v) ? v : undefined);
      return {
        type: "modellzugang",
        aktion: m.aktion,
        art: oneOf(m.art, ["claude", "haus"] as const) ? m.art : undefined,
        quelle: oneOf(m.quelle, ["profil", "zuordnung", "festgelegt", "wahl", "keiner", "fehler"] as const)
          ? m.quelle
          : undefined,
        hinterlegt: m.hinterlegt === true,
        // nur die letzten vier Zeichen; alles andere wird verworfen
        ende: vier(m.ende),
        geprueft: zeit(m.geprueft),
        festgelegt: m.festgelegt === true,
        modell: isStr(m.modell) ? sauber(m.modell, 60, false) : undefined,
        modus: oneOf(m.modus, MODELL_MODI) ? m.modus : undefined,
        codeHinterlegt: m.code_hinterlegt === true,
        codeEnde: vier(m.code_ende),
        codeGesetzt: zeit(m.code_gesetzt),
        stt: oneOf(m.stt, SPRACH_ANBIETER) ? m.stt : undefined,
        tts: oneOf(m.tts, SPRACH_ANBIETER) ? m.tts : undefined,
        stimmeHaus: zeile(m.stimme_haus, 160),
        modelle: modelleAus(m.modelle),
        modellSperre: zeile(m.modell_sperre, 200),
        hausStimme: stimmeAus(m.haus_stimme, hausStimmenAus(m.haus_stimmen)),
        hausStimmeStandard: stimmeAus(m.haus_stimme_standard, hausStimmenAus(m.haus_stimmen)),
        hausStimmen: hausStimmenAus(m.haus_stimmen),
        hausStimmenHinweis: zeile(m.haus_stimmen_hinweis, 200),
        wirksam: isStr(m.wirksam) ? sauber(m.wirksam, 60, false) : undefined,
        // Absicherung: auch wenn der Kern je einen Schlüssel in einen Fehlertext schriebe, zeigt die Oberfläche ihn nicht
        fehler:
          isStr(m.fehler) && m.fehler.trim()
            ? sauber(m.fehler.trim(), 200, false).replace(/sk-ant-[A-Za-z0-9_-]*/gi, "[Schlüssel entfernt]")
            : undefined,
      };
    }
    case "kontingent": {
      if (!oneOf(m.zustand, ["unbekannt", "bekannt"] as const)) return null;
      const limits = m.zustand === "bekannt" ? kontingentLimits(m.limits) : [];
      return {
        type: "kontingent",
        zustand: limits.length > 0 ? "bekannt" : "unbekannt", // ohne gültige Limits bleibt es unbekannt
        stand: limits.length > 0 && isStr(m.stand) && ISO_UTC.test(m.stand) ? m.stand : undefined,
        limits,
      };
    }
    case "mikrofon": {
      if (!oneOf(m.zustand, ["still", "fehlt", "ok"] as const)) return null;
      const s = typeof m.sekunden === "number" && Number.isFinite(m.sekunden) ? Math.round(m.sekunden) : 10;
      return { type: "mikrofon", zustand: m.zustand, sekunden: Math.max(1, Math.min(3600, s)) };
    }
    case "stimme": {
      // Zwei Formen unter einem Typ: Stand (status) oder Ergebnis der letzten Äußerung (ergebnis), nie beides
      if ("status" in m === "ergebnis" in m) return null;
      const modus = m.modus === undefined || m.modus === null ? null : oneOf(m.modus, STIMME_MODI) ? m.modus : undefined;
      if (modus === undefined) return null;
      if ("status" in m) return oneOf(m.status, STIMME_STATUS) ? { type: "stimme_status", status: m.status, modus } : null;
      if (!oneOf(m.ergebnis, STIMME_ERGEBNISSE)) return null;
      if (m.wert !== undefined && m.wert !== null && (typeof m.wert !== "number" || !Number.isFinite(m.wert))) return null;
      const wert = typeof m.wert === "number" ? Math.min(1, Math.max(0, m.wert)) : null;
      // ignoriert: freiwillig, null zählt wie fehlend, alles andere als ein Wahrheitswert lehnt die Nachricht ab
      if (m.ignoriert !== undefined && m.ignoriert !== null && typeof m.ignoriert !== "boolean") return null;
      // zeit: freiwillig, null und leer zählen wie fehlend; kein Text oder ein überlanger lehnt die Nachricht ab
      if (m.zeit !== undefined && m.zeit !== null && (!isStr(m.zeit) || m.zeit.length > ZEIT_MAX)) return null;
      const zeit = isStr(m.zeit) ? m.zeit.trim() : "";
      return {
        type: "stimme_ergebnis",
        ergebnis: m.ergebnis,
        wert,
        modus,
        ...(typeof m.ignoriert === "boolean" ? { ignoriert: m.ignoriert } : {}),
        ...(zeit ? { zeit } : {}),
      };
    }
    case "stimmabdruck": {
      if (!oneOf(m.status, ABDRUCK_STATUS)) return null;
      // sekunden, ziel und text sind freiwillig (null zählt wie nicht gesendet); ein falscher Typ lehnt die ganze Nachricht ab
      const fehlt = (v: unknown) => v === undefined || v === null;
      const zahlOk = (v: unknown) => fehlt(v) || (typeof v === "number" && Number.isFinite(v));
      if (!zahlOk(m.sekunden) || !zahlOk(m.ziel) || !(fehlt(m.text) || isStr(m.text))) return null;
      const aus: ServerMessage = { type: "stimmabdruck", status: m.status };
      if (typeof m.sekunden === "number") aus.sekunden = Math.min(3600, Math.max(0, m.sekunden));
      if (typeof m.ziel === "number") aus.ziel = Math.min(600, Math.max(1, m.ziel));
      const text = isStr(m.text) ? sauber(m.text, 400, false).trim() : "";
      if (text) aus.text = text;
      // mikrofon: Kennung des Mikrofons bei fertig und beim Löschen eines einzelnen Abdrucks (freiwillig, nur in fester Form; eine
      // ungültige fällt weg, die Meldung bleibt, sonst hinge die Einlernansicht)
      if (isStr(m.mikrofon) && MIKROFON_KENNUNG.test(m.mikrofon)) aus.mikrofon = m.mikrofon;
      return aus;
    }
    case "stimmabdruck_mikrofone": {
      // max 1 bis 3, höchstens max Einträge; je Eintrag Kennung in fester Form, Name als eine bereinigte Zeile (leer heißt keiner),
      // Zeitpunkt als lesbares Datum oder leer. Alles andere lehnt die ganze Nachricht ab.
      if (typeof m.max !== "number" || !Number.isInteger(m.max) || m.max < 1 || m.max > MIKROFONE_MAX) return null;
      if (!Array.isArray(m.mikrofone) || m.mikrofone.length > m.max) return null;
      const mikrofone: StimmMikrofonEintrag[] = [];
      for (const roh of m.mikrofone as unknown[]) {
        if (typeof roh !== "object" || roh === null) return null;
        const e = roh as Record<string, unknown>;
        if (!isStr(e.kennung) || !MIKROFON_KENNUNG.test(e.kennung) || mikrofone.some((x) => x.kennung === e.kennung)) return null;
        if (e.name !== null && e.name !== undefined && !isStr(e.name)) return null;
        if (e.am !== null && e.am !== undefined && !(isStr(e.am) && e.am.length <= 40 && Number.isFinite(Date.parse(e.am)))) return null;
        mikrofone.push({ kennung: e.kennung, name: zeile(e.name, 120) ?? null, am: isStr(e.am) ? e.am : null });
      }
      return { type: "stimmabdruck_mikrofone", mikrofone, max: m.max };
    }
    case "stimmabdruck_einwilligung": {
      // Der Text ist Teil einer Einwilligung: bereinigt, aber nie gekürzt (zu lang heißt abgelehnt)
      if (!isStr(m.version) || !EINWILLIGUNG_VERSION.test(m.version) || !isStr(m.text)) return null;
      const text = m.text.replace(STEUER, "").trim();
      if (!text || text.length > EINWILLIGUNG_MAX) return null;
      return { type: "stimmabdruck_einwilligung", version: m.version, text };
    }
    case "jira_status": {
      // Nur gültige Projektschlüssel; ohne das Standardprojekt in der Liste gilt die Nachricht nicht (dann kein Knopf)
      if (!Array.isArray(m.projekte) || !isStr(m.standard)) return null;
      const projekte = m.projekte.slice(0, JIRA_PROJEKTE_MAX).filter((p): p is string => isStr(p) && projektOk(p));
      if (!projekte.includes(m.standard)) return null;
      return { type: "jira_status", projekte, standard: m.standard };
    }
    case "jira_ergebnis": {
      if (typeof m.ok !== "boolean" || !isStr(m.text)) return null;
      const text = sauber(m.text, 300, false).trim();
      if (!m.ok) return { type: "jira_ergebnis", ok: false, text }; // nicht angelegt: nie Schlüssel oder Verweis
      if (!isStr(m.schluessel) || !schluesselOk(m.schluessel)) return null;
      const link = isStr(m.link) && linkOk(m.link, m.schluessel) ? m.link : undefined;
      return { type: "jira_ergebnis", ok: true, text, schluessel: m.schluessel, ...(link ? { link } : {}) };
    }
    default:
      return null;
  }
}
