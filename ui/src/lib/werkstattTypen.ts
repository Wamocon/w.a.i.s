/**
 * Typen der Werkstatt (Admin-Panel, Seite /werkstatt). Sie beschreiben, was die Oberfläche von der Schnittstelle des Dienstes
 * wamo-werkstatt liest und schickt (Pfade und Felder: lib/werkstattApi.ts). Ohne Laufzeitcode, damit jede reine Logikdatei sie
 * importieren kann. Die Felder tragen nur Zahlen, Stände, Zeiten und Kartentexte, nie Gesprächstext, Namen, E-Mail oder Geräte.
 */

/** Fehlerbild der Schnittstelle: ein fester Code und ein klarer deutscher Satz (lib/werkstattFehler.ts). */
export type FehlerBild = { code: string; text: string; status: number };

// ---------- Zugang ----------
export type Ich = {
  rolle: "admin" | "mitglied" | null;
  /** Alter des letzten Codes des zweiten Faktors in Sekunden, null ohne Angabe */
  aal2AlterS: number | null;
  erlaubt: boolean;
};

// ---------- Dashboards ----------
export type Betrieb = {
  zeit: string | null;
  /** Alter der Datei des Sammlers in Sekunden */
  alterS: number | null;
  /** ein Eintrag je Slot (a und b), höchstens vier; leer, wenn der Sammler nichts meldet */
  kern: { slot: string | null; release: string | null; aktiv: boolean | null }[];
  oberflaeche: { farbe: string | null; version: string | null };
  installer: { version: string | null };
  kanal: { zustand: string | null };
  laborDienst: { zustand: string | null };
};

export type SitzungTag = { tag: string; anzahl: number; dauerP50S: number | null; dauerP95S: number | null; offen: number };
/** Ein Latenzwert je Tag (tag gesetzt) oder insgesamt (tag leer). */
export type LatenzTag = { tag: string | null; zuege: number; p50Ms: number | null; p95Ms: number | null };
export type AktionZeile = { tool: string; status: string; anzahl: number };

// ---------- Protokolle ----------
export type ProtokollZeile = { zeit: string; marke: string; stufe: string; code: string; zahlen: string };
export type ProtokollAntwort = { zeilen: ProtokollZeile[]; marken: string[] };
export type ProtokollFilter = { marke: string; stufe: string; stunden: number };

// ---------- Labor-Planer ----------
export const TERMIN_STATUS = ["entwurf", "freigegeben", "laufend", "nachlauf", "abgeschlossen"] as const;
export type TerminStatus = (typeof TERMIN_STATUS)[number];

export type Termin = {
  id: string;
  /** ISO-Datum JJJJ-MM-TT */
  tag: string;
  /** Uhrzeit HH:MM oder null */
  beginn: string | null;
  ende: string | null;
  einwilligungVersion: number;
  status: TerminStatus;
  aufbewahrungBis: string;
};
export type TerminEingabe = Omit<Termin, "id">;

export const PLATZ_ZWECKE = ["besucher", "reserve", "abnahme"] as const;
export type PlatzZweck = (typeof PLATZ_ZWECKE)[number];
export type Platz = { platz: number; zweck: PlatzZweck; kennung: string | null; gast: string | null };

export type ChecklistePunkt = { nr: number; titel: string; quelle: string | null; faellig: string | null; erledigt: boolean };
export type ChecklisteEingabe = { titel: string; quelle: string | null; faellig: string | null };

export type LaborProfil = { kennung: string | null; art: string; platz: number | null; aktiv: boolean; zeilen: number | null };

// ---------- Karten ----------
export const WERKZEUGE = ["Jira", "Mail", "Canvas", "Websuche"] as const;
export type Werkzeug = (typeof WERKZEUGE)[number];
export const WISSEN_ARTEN = ["keine", "Glossar", "ISTQB-Basis", "Eigener Text"] as const;
export type WissenArt = (typeof WISSEN_ARTEN)[number];
export type KartenStand = "entwurf" | "veroeffentlicht";

export type Karte = {
  id: string;
  gruppe: string;
  titel: string;
  aufgabe: string;
  erwartung: string;
  /** null: kein Fehlerfall */
  fehler: string | null;
  lernziel: string | null;
  wissen: WissenArt;
  /** nur bei wissen = "Eigener Text" */
  wissenstext: string | null;
  werkzeuge: Werkzeug[];
  dauerMin: number;
  stand: KartenStand;
};
export type KartenEingabe = Omit<Karte, "stand">;
export type KartenListe = {
  karten: Karte[];
  /** Nummer der aktiven Version, null ohne veröffentlichte Version */
  version: number | null;
  /** die festen Gruppen des Katalogs: Buchstabe zu Name (der Dienst nimmt keine anderen an) */
  gruppen: Record<string, string>;
};
export type KartenVersion = { version: number; erstelltAt: string | null; anzahlAenderungen: number; wissenZeichen: number; aktiv: boolean };

/** Zuordnung: Platznummer zu den Kennungen der Karten dieses Platzes. */
export type Zuordnung = Record<number, string[]>;

// ---------- Veröffentlichen ----------
export type Pruefung = { ok: boolean; probleme: string[]; zeichen: number };
export type FreigabeKarte = {
  id: string;
  giltBis: string;
  aenderungen: number | null;
  karten: string[];
  /** aktive Version zur Zeit der Karte; die neue Version ist diese plus eins */
  basisVersion: number | null;
};
export type Veroeffentlicht = { version: number; zeichen: number };
