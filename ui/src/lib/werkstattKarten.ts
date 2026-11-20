import {
  WERKZEUGE,
  WISSEN_ARTEN,
  type Karte,
  type KartenEingabe,
  type Werkzeug,
  type WissenArt,
  type Zuordnung,
} from "./werkstattTypen.ts";

/**
 * Logik des Karten-Editors der Werkstatt: Grenzen der Felder (wie die Prüfungen der Tabelle labor_karten), Gruppen und Kennungen,
 * Prüfung eines Formulars, Zeichenbudget des Kerns und Zuordnung der Karten zu den Plätzen. Ohne React und ohne Netz, damit sich
 * alles mit node:test prüfen lässt (werkstattKarten.test.ts). Die Prüfung hier erspart nur sinnlose Aufrufe: Entschieden wird im
 * Dienst und in der Datenbank.
 */

export const GRENZEN = {
  gruppe: 30,
  titel: 60,
  aufgabe: 240,
  erwartung: 240,
  fehler: 120,
  lernziel: 40,
  wissenstext: 900,
  dauerMin: 1,
  dauerMax: 20,
} as const;

/** Höchstmenge an Zeichen, die der Kern aus den Labor-Daten und den Wissenstexten der Karten zusammen lädt. */
export const WISSEN_MAX_ZEICHEN = 6000;
/** Zeichen der festen Labor-Daten im Kern (ohne Wissenstexte der Karten); der Dienst darf einen genaueren Wert melden. */
export const WISSEN_BASIS_STANDARD = 4120;
/** Richtwert für die Zeit eines Gastes: darüber färbt sich die Summe der Spalte. */
export const ZEIT_RICHTWERT_MIN = 25;

export const KARTEN_ID = /^[A-Z][0-9]{1,2}$/;
const MAX_NUMMER = 99;
const BUCHSTABEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

// ---------- Text ----------
const STEUERZEICHEN = /[\u0000-\u001f\u007f-\u009f]+/g;

/** Kartentexte sind einzeilig: Steuerzeichen und Zeilenumbrüche werden zu einem Leerzeichen, doppelter Leerraum fällt weg. */
export function normalisieren(text: string): string {
  return text.replace(STEUERZEICHEN, " ").replace(/\s+/g, " ").trim();
}

/** Enthält der Text Zeilenumbrüche oder Steuerzeichen, die beim Speichern zu Leerzeichen werden? */
export function hatSteuerzeichen(text: string): boolean {
  return /[\u0000-\u001f\u007f-\u009f]/.test(text);
}

// ---------- Gruppen und Kennungen ----------
export type Gruppe = { buchstabe: string; name: string; anzahl: number };

/** Die Gruppen des Katalogs: der Buchstabe steht in der Kennung, der Name in der Karte (der häufigste je Buchstabe). */
export function gruppenAus(karten: readonly Karte[]): Gruppe[] {
  const je = new Map<string, Map<string, number>>();
  for (const k of karten) {
    const b = k.id.charAt(0);
    const namen = je.get(b) ?? new Map<string, number>();
    namen.set(k.gruppe, (namen.get(k.gruppe) ?? 0) + 1);
    je.set(b, namen);
  }
  return [...je.entries()]
    .map(([buchstabe, namen]) => {
      const sortiert = [...namen.entries()].sort((a, b) => b[1] - a[1]);
      return { buchstabe, name: sortiert[0][0], anzahl: [...namen.values()].reduce((s, n) => s + n, 0) };
    })
    .sort((a, b) => a.buchstabe.localeCompare(b.buchstabe));
}

/** Die Buchstaben, die noch keine Gruppe haben. */
export function freieBuchstaben(gruppen: readonly Gruppe[]): string[] {
  const belegt = new Set(gruppen.map((g) => g.buchstabe));
  return BUCHSTABEN.filter((b) => !belegt.has(b));
}

/** Die nächste freie Kennung in der Gruppe: Buchstabe plus höchste vorhandene Zahl plus 1; null, wenn die Gruppe voll ist. */
export function idVorschlag(buchstabe: string, karten: readonly Karte[]): string | null {
  if (!/^[A-Z]$/.test(buchstabe)) return null;
  let hoechste = 0;
  for (const k of karten) {
    const m = new RegExp(`^${buchstabe}([0-9]{1,2})$`).exec(k.id);
    if (m) hoechste = Math.max(hoechste, Number(m[1]));
  }
  return hoechste >= MAX_NUMMER ? null : `${buchstabe}${hoechste + 1}`;
}

/** Entwürfe zuerst im Sinn von "noch nicht veröffentlicht". */
export const entwuerfe = (karten: readonly Karte[]): Karte[] => karten.filter((k) => k.stand === "entwurf");

// ---------- Zeichenbudget ----------
export type Budget = { genutzt: number; max: number; rest: number; ueber: boolean };

/**
 * Das Zeichenbudget: Grundmenge plus die Wissenstexte aller Karten mit "Eigener Text". aktuell ersetzt die Karte mit dieser Kennung
 * (oder kommt neu dazu), damit der Editor das Budget schon beim Tippen zeigt.
 */
export function zeichenBudget(
  karten: readonly Karte[],
  basis: number | null,
  aktuell?: { id: string; wissen: WissenArt; wissenstext: string | null } | null,
): Budget {
  let genutzt = basis ?? WISSEN_BASIS_STANDARD;
  let ersetzt = false;
  for (const k of karten) {
    const quelle = aktuell && aktuell.id === k.id ? aktuell : k;
    if (quelle === aktuell) ersetzt = true;
    if (quelle.wissen === "Eigener Text") genutzt += quelle.wissenstext?.length ?? 0;
  }
  if (aktuell && !ersetzt && aktuell.wissen === "Eigener Text") genutzt += aktuell.wissenstext?.length ?? 0;
  return { genutzt, max: WISSEN_MAX_ZEICHEN, rest: WISSEN_MAX_ZEICHEN - genutzt, ueber: genutzt > WISSEN_MAX_ZEICHEN };
}

// ---------- Formular ----------
export type Formular = {
  id: string;
  /** true bei einer bestehenden Karte: Kennung und Gruppe bleiben fest */
  bestehend: boolean;
  /** Buchstabe einer vorhandenen Gruppe, "neu" für eine neue Gruppe, "" ohne Wahl */
  gruppeWahl: string;
  neuerBuchstabe: string;
  neuerName: string;
  titel: string;
  aufgabe: string;
  erwartung: string;
  fehlerfall: boolean;
  fehlertext: string;
  lernziel: string;
  dauer: string;
  wissen: WissenArt;
  wissenstext: string;
  werkzeuge: Werkzeug[];
};

export const VORGABE_DAUER = "4";

/** Ein leeres Formular für einen neuen Use Case; mit der Gruppe, die der Katalog gerade zeigt, falls es eine gibt. */
export function leeresFormular(karten: readonly Karte[], gruppe = ""): Formular {
  const gruppen = gruppenAus(karten);
  const wahl = gruppen.some((g) => g.buchstabe === gruppe) ? gruppe : gruppen.length === 0 ? "neu" : "";
  return {
    id: wahl && wahl !== "neu" ? (idVorschlag(wahl, karten) ?? "") : "",
    bestehend: false,
    gruppeWahl: wahl,
    neuerBuchstabe: "",
    neuerName: "",
    titel: "",
    aufgabe: "",
    erwartung: "",
    fehlerfall: false,
    fehlertext: "",
    lernziel: "",
    dauer: VORGABE_DAUER,
    wissen: "keine",
    wissenstext: "",
    werkzeuge: [],
  };
}

/** Das Formular zu einer vorhandenen Karte; als Kopie mit neuer Kennung aus derselben Gruppe und dem Zusatz "(Kopie)". */
export function formularAusKarte(karte: Karte, karten: readonly Karte[], kopie = false): Formular {
  const buchstabe = karte.id.charAt(0);
  const neu = kopie ? idVorschlag(buchstabe, karten) : null;
  const titel = kopie ? `${karte.titel} (Kopie)`.slice(0, GRENZEN.titel) : karte.titel;
  return {
    id: kopie ? (neu ?? "") : karte.id,
    bestehend: !kopie,
    gruppeWahl: buchstabe,
    neuerBuchstabe: "",
    neuerName: "",
    titel,
    aufgabe: karte.aufgabe,
    erwartung: karte.erwartung,
    fehlerfall: karte.fehler !== null,
    fehlertext: karte.fehler ?? "",
    lernziel: karte.lernziel ?? "",
    dauer: String(karte.dauerMin),
    wissen: karte.wissen,
    wissenstext: karte.wissenstext ?? "",
    werkzeuge: [...karte.werkzeuge],
  };
}

/** Wechselt die Gruppe eines neuen Formulars, folgt die vorgeschlagene Kennung mit. */
export function mitGruppe(f: Formular, wahl: string, karten: readonly Karte[]): Formular {
  if (f.bestehend) return f;
  let id = "";
  if (wahl === "neu") id = /^[A-Z]$/.test(f.neuerBuchstabe) ? `${f.neuerBuchstabe}1` : "";
  else if (wahl) id = idVorschlag(wahl, karten) ?? "";
  return { ...f, gruppeWahl: wahl, id };
}

/** Der Buchstabe einer neuen Gruppe bestimmt die Kennung der ersten Karte darin. */
export function mitNeuemBuchstaben(f: Formular, buchstabe: string): Formular {
  const b = buchstabe.toUpperCase().slice(0, 1);
  return { ...f, neuerBuchstabe: b, id: /^[A-Z]$/.test(b) ? `${b}1` : "" };
}

export type FeldName =
  | "gruppe"
  | "neuerBuchstabe"
  | "neuerName"
  | "id"
  | "titel"
  | "aufgabe"
  | "erwartung"
  | "fehlertext"
  | "lernziel"
  | "dauer"
  | "wissenstext"
  | "budget";
export type Problem = { feld: FeldName; text: string };

/** Pflichtfeld mit Höchstlänge: fehlt es oder ist es zu lang, kommt der passende Satz. subjekt: "Der Titel", "Die Aufgabe", "Das erwartete Ergebnis". */
function laenge(feld: FeldName, subjekt: string, wert: string, max: number, probleme: Problem[]): void {
  if (!wert) probleme.push({ feld, text: `${subjekt} fehlt.` });
  else if (wert.length > max) probleme.push({ feld, text: `${subjekt} ist zu lang (höchstens ${max} Zeichen).` });
}

/**
 * Prüft das Formular gegen die Grenzen und baut die Eingabe. Gibt es Probleme, ist eingabe null. Texte werden normalisiert
 * (einzeilig), ein Wissenstext zählt nur bei "Eigener Text", ein Fehlertext nur bei einem Fehlerfall.
 */
export function formularPruefen(
  f: Formular,
  karten: readonly Karte[],
  basis: number | null,
): { eingabe: KartenEingabe | null; probleme: Problem[] } {
  const probleme: Problem[] = [];
  const gruppen = gruppenAus(karten);

  let gruppeName = "";
  if (f.bestehend || (f.gruppeWahl !== "" && f.gruppeWahl !== "neu")) {
    const g = gruppen.find((x) => x.buchstabe === (f.bestehend ? f.id.charAt(0) : f.gruppeWahl));
    if (g) gruppeName = g.name;
    else probleme.push({ feld: "gruppe", text: "Die Gruppe gibt es nicht. Wähle eine Gruppe." });
  } else if (f.gruppeWahl === "neu") {
    const b = f.neuerBuchstabe;
    if (!/^[A-Z]$/.test(b)) probleme.push({ feld: "neuerBuchstabe", text: "Der Buchstabe der neuen Gruppe fehlt." });
    else if (gruppen.some((g) => g.buchstabe === b)) probleme.push({ feld: "neuerBuchstabe", text: "Dieser Buchstabe gehört schon einer Gruppe." });
    gruppeName = normalisieren(f.neuerName);
    laenge("neuerName", "Der Gruppenname", gruppeName, GRENZEN.gruppe, probleme);
  } else {
    probleme.push({ feld: "gruppe", text: "Wähle eine Gruppe." });
  }

  if (!KARTEN_ID.test(f.id)) probleme.push({ feld: "id", text: "Die Kennung ist ungültig." });
  else if (!f.bestehend && karten.some((k) => k.id === f.id)) probleme.push({ feld: "id", text: "Diese Kennung gibt es schon." });

  const titel = normalisieren(f.titel);
  const aufgabe = normalisieren(f.aufgabe);
  const erwartung = normalisieren(f.erwartung);
  laenge("titel", "Der Titel", titel, GRENZEN.titel, probleme);
  laenge("aufgabe", "Die Aufgabe", aufgabe, GRENZEN.aufgabe, probleme);
  laenge("erwartung", "Das erwartete Ergebnis", erwartung, GRENZEN.erwartung, probleme);

  const fehlertext = normalisieren(f.fehlertext);
  if (f.fehlerfall) {
    if (!fehlertext) probleme.push({ feld: "fehlertext", text: "Beschreibe den Fehler, den dieser Use Case erwartet." });
    else if (fehlertext.length > GRENZEN.fehler) probleme.push({ feld: "fehlertext", text: `Die Beschreibung des Fehlers ist zu lang (höchstens ${GRENZEN.fehler} Zeichen).` });
  }

  const lernziel = normalisieren(f.lernziel);
  if (lernziel.length > GRENZEN.lernziel) probleme.push({ feld: "lernziel", text: `Das Lernziel ist zu lang (höchstens ${GRENZEN.lernziel} Zeichen).` });

  const dauer = /^\d{1,2}$/.test(f.dauer.trim()) ? Number(f.dauer.trim()) : NaN;
  if (!(dauer >= GRENZEN.dauerMin && dauer <= GRENZEN.dauerMax)) {
    probleme.push({ feld: "dauer", text: `Die Dauer muss eine ganze Zahl von ${GRENZEN.dauerMin} bis ${GRENZEN.dauerMax} Minuten sein.` });
  }

  const wissenstext = f.wissen === "Eigener Text" ? normalisieren(f.wissenstext) : "";
  if (f.wissen === "Eigener Text") {
    if (!wissenstext) probleme.push({ feld: "wissenstext", text: "Der eigene Wissenstext fehlt." });
    else if (wissenstext.length > GRENZEN.wissenstext) probleme.push({ feld: "wissenstext", text: `Der Wissenstext ist zu lang (höchstens ${GRENZEN.wissenstext} Zeichen).` });
  }

  const budget = zeichenBudget(karten, basis, { id: f.id, wissen: f.wissen, wissenstext: wissenstext || null });
  if (budget.ueber) {
    probleme.push({ feld: "budget", text: `Das Zeichenbudget ist überschritten: ${budget.genutzt} von ${budget.max} Zeichen. Kürze die Wissenstexte.` });
  }

  if (probleme.length > 0) return { eingabe: null, probleme };
  return {
    eingabe: {
      id: f.id,
      gruppe: gruppeName,
      titel,
      aufgabe,
      erwartung,
      fehler: f.fehlerfall ? fehlertext : null,
      lernziel: lernziel || null,
      wissen: WISSEN_ARTEN.includes(f.wissen) ? f.wissen : "keine",
      wissenstext: f.wissen === "Eigener Text" ? wissenstext : null,
      werkzeuge: WERKZEUGE.filter((w) => f.werkzeuge.includes(w)),
      dauerMin: dauer,
    },
    probleme: [],
  };
}

/** Der Rumpf für POST und PUT der Karten (Namen der Schnittstelle). */
export function eingabeZuRumpf(e: KartenEingabe): Record<string, unknown> {
  return {
    id: e.id,
    gruppe: e.gruppe,
    titel: e.titel,
    aufgabe: e.aufgabe,
    erwartung: e.erwartung,
    fehler: e.fehler,
    lernziel: e.lernziel,
    wissen: e.wissen,
    wissenstext: e.wissenstext,
    werkzeuge: e.werkzeuge,
    dauer_min: e.dauerMin,
    stand: "entwurf",
  };
}

// ---------- Zuordnung ----------
/** Minuten je Platz: die Summe der Dauer der zugeordneten Karten. */
export function zeitJePlatz(zuordnung: Zuordnung, karten: readonly Karte[]): Record<number, number> {
  const dauer = new Map(karten.map((k) => [k.id, k.dauerMin] as const));
  const summe: Record<number, number> = {};
  for (const [platz, ids] of Object.entries(zuordnung)) {
    summe[Number(platz)] = ids.reduce((s, id) => s + (dauer.get(id) ?? 0), 0);
  }
  return summe;
}

/** Setzt oder löscht ein Kreuz, ohne die Eingabe zu verändern; die Kennungen eines Platzes bleiben sortiert und ohne Doppelte. */
export function zuordnungUmschalten(zuordnung: Zuordnung, platz: number, karteId: string, an: boolean): Zuordnung {
  const alt = zuordnung[platz] ?? [];
  const neu = an ? [...new Set([...alt, karteId])].sort() : alt.filter((id) => id !== karteId);
  return { ...zuordnung, [platz]: neu };
}

/** Sind zwei Zuordnungen gleich (Reihenfolge der Kennungen und leere Plätze zählen nicht)? */
export function zuordnungGleich(a: Zuordnung, b: Zuordnung): boolean {
  const plaetze = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const p of plaetze) {
    const x = [...(a[Number(p)] ?? [])].sort();
    const y = [...(b[Number(p)] ?? [])].sort();
    if (x.length !== y.length || x.some((v, i) => v !== y[i])) return false;
  }
  return true;
}

/** Streicht Kennungen, die es nicht (mehr) gibt (zum Beispiel nach dem Löschen eines Entwurfs). */
export function zuordnungBereinigen(zuordnung: Zuordnung, karten: readonly Karte[]): Zuordnung {
  const ids = new Set(karten.map((k) => k.id));
  const neu: Zuordnung = {};
  for (const [platz, liste] of Object.entries(zuordnung)) neu[Number(platz)] = liste.filter((id) => ids.has(id));
  return neu;
}
