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

/**
 * Katalogbudget für Wissenstexte: Der Kern lädt aus dem Katalog höchstens 20 Einträge (Karten mit "Eigener Text") und zusammen höchstens
 * 2000 Zeichen; je Karte gelten höchstens 900 Zeichen (GRENZEN.wissenstext). Die festen Labor-Daten des Kerns zählen hier nicht mit.
 */
export const KATALOG_MAX_ZEICHEN = 2000;
export const KATALOG_MAX_EINTRAEGE = 20;
/** Richtwert für die Zeit eines Gastes: darüber färbt sich die Summe der Spalte. */
export const ZEIT_RICHTWERT_MIN = 25;

export const KARTEN_ID = /^[A-Z][0-9]{1,2}$/;
const MAX_NUMMER = 99;

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

/**
 * Die Gruppen des Katalogs: Der Dienst kennt eine feste Liste (Buchstabe zu Name) und nimmt keine anderen an. Dazu zählt die Zahl
 * der Karten je Gruppe (der Buchstabe steht in der Kennung der Karte).
 */
export function gruppenAus(gruppen: Readonly<Record<string, string>>, karten: readonly Karte[]): Gruppe[] {
  return Object.entries(gruppen)
    .map(([buchstabe, name]) => ({ buchstabe, name, anzahl: karten.filter((k) => k.id.charAt(0) === buchstabe).length }))
    .sort((a, b) => a.buchstabe.localeCompare(b.buchstabe));
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

// ---------- Katalogbudget ----------
export type Budget = { genutzt: number; max: number; rest: number; ueber: boolean; eintraege: number; eintraegeMax: number; zuViele: boolean };

/**
 * Das Katalogbudget: die Wissenstexte aller Karten mit "Eigener Text". aktuell ersetzt die Karte mit dieser Kennung (oder kommt neu
 * dazu), damit der Editor das Budget schon beim Tippen zeigt.
 */
export function zeichenBudget(
  karten: readonly Karte[],
  aktuell?: { id: string; wissen: WissenArt; wissenstext: string | null } | null,
): Budget {
  let genutzt = 0;
  let eintraege = 0;
  let ersetzt = false;
  for (const k of karten) {
    const quelle = aktuell && aktuell.id === k.id ? aktuell : k;
    if (quelle === aktuell) ersetzt = true;
    if (quelle.wissen === "Eigener Text") {
      genutzt += quelle.wissenstext?.length ?? 0;
      eintraege += 1;
    }
  }
  if (aktuell && !ersetzt && aktuell.wissen === "Eigener Text") {
    genutzt += aktuell.wissenstext?.length ?? 0;
    eintraege += 1;
  }
  return {
    genutzt,
    max: KATALOG_MAX_ZEICHEN,
    rest: KATALOG_MAX_ZEICHEN - genutzt,
    ueber: genutzt > KATALOG_MAX_ZEICHEN,
    eintraege,
    eintraegeMax: KATALOG_MAX_EINTRAEGE,
    zuViele: eintraege > KATALOG_MAX_EINTRAEGE,
  };
}

/**
 * Zeichen, die als Buchstabe oder Symbol durchgehen, aber nicht zu sehen sind (Füllzeichen, Variantenselektoren, Braille-Leerzeichen,
 * Graphem-Verbinder): dieselben Bereiche wie im Dienst (wissen_regeln.py). Die Zeichen werden zur Laufzeit eingesetzt, damit der
 * Quelltext frei von unsichtbaren Zeichen bleibt.
 */
const UNSICHTBAR_BEREICHE: readonly (readonly [number, number])[] = [
  [0x034f, 0x034f], [0x115f, 0x1160], [0x17b4, 0x17b5], [0x180b, 0x180d], [0x2800, 0x2800], [0x3164, 0x3164], [0xfe00, 0xfe0f], [0xffa0, 0xffa0], [0xe0100, 0xe01ef],
];
const UNSICHTBAR = new RegExp(`[${UNSICHTBAR_BEREICHE.map(([von, bis]) => `${String.fromCodePoint(von)}-${String.fromCodePoint(bis)}`).join("")}]`, "u");
/** Erlaubt sind Buchstaben, Zeichen mit Akzent, Ziffern, Satzzeichen, Symbole und das Leerzeichen; Steuer-, Format-, Trenn- und private Zeichen nicht. */
const NICHT_ERLAUBT = /[^\p{L}\p{M}\p{N}\p{P}\p{S} ]/u;
/** Markup nach NFKC wie im Dienst: Tags, Sondermarken der Chat-Vorlagen, eckige Marken älterer Vorlagen und Gesprächsrollen am Zeilenanfang. */
const MARKUP = /<[/!?|A-Za-z][^<>]*>|<\||\|>|\[[ \t]*\/?[ \t]*(?:INST|SYS|TOOL_CALLS|AVAILABLE_TOOLS|TOOL_RESULTS)[ \t]*\]|^[ \t]*(?:human|assistant)[ \t]*:/im;
/** Eine Rollenzeile am Anfang; der Dienst prüft human und assistant beim Speichern, die übrigen beim Prüfen als Anweisung. */
const ROLLE = /^[ \t]*(?:human|assistant|system|user|developer|ai)[ \t]*:/i;

/**
 * Was im Wissenstext nicht stehen darf (die Regeln des Dienstes, die dieselben sind wie die des Kerns): unsichtbare und andere
 * unerlaubte Zeichen, Markup und eine Rollenzeile am Anfang. Geprüft wird der Text, der gesendet wird (einzeilig). Der Dienst lehnt
 * das ab; die Oberfläche sagt es vorher und klar. Null, wenn der Text in Ordnung ist.
 */
export function wissenstextProblem(text: string): string | null {
  const t = normalisieren(text);
  if (UNSICHTBAR.test(t) || NICHT_ERLAUBT.test(t)) return "Der Wissenstext enthält unsichtbare oder unerlaubte Zeichen. Sie sind nicht erlaubt, bitte entferne sie.";
  const n = t.normalize("NFKC");
  if (ROLLE.test(n)) return "Der Wissenstext beginnt wie eine Rollenzeile (zum Beispiel „System:“). Das ist nicht erlaubt, schreibe nur Wissen.";
  if (MARKUP.test(n)) return "Der Wissenstext enthält Markup (Tags in spitzen Klammern). Das ist nicht erlaubt, schreibe nur Text.";
  return null;
}

// ---------- Formular ----------
export type Formular = {
  id: string;
  /** true bei einer bestehenden Karte: Kennung und Gruppe bleiben fest */
  bestehend: boolean;
  /** Buchstabe der gewählten Gruppe, "" ohne Wahl */
  gruppeWahl: string;
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

/** Ein leeres Formular für einen neuen Use Case; mit der Gruppe, die der Katalog gerade zeigt, falls der Dienst sie kennt. */
export function leeresFormular(karten: readonly Karte[], gruppen: Readonly<Record<string, string>>, gruppe = ""): Formular {
  const wahl = Object.prototype.hasOwnProperty.call(gruppen, gruppe) ? gruppe : "";
  return {
    id: wahl ? (idVorschlag(wahl, karten) ?? "") : "",
    bestehend: false,
    gruppeWahl: wahl,
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
  const zusatz = " (Kopie)";
  // der Zusatz bleibt immer stehen, ein langer Titel wird davor gekürzt
  const titel = kopie ? `${karte.titel.slice(0, GRENZEN.titel - zusatz.length)}${zusatz}` : karte.titel;
  return {
    id: kopie ? (neu ?? "") : karte.id,
    bestehend: !kopie,
    gruppeWahl: buchstabe,
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
  return { ...f, gruppeWahl: wahl, id: wahl ? (idVorschlag(wahl, karten) ?? "") : "" };
}

export type FeldName =
  | "gruppe"
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
  gruppen: Readonly<Record<string, string>>,
): { eingabe: KartenEingabe | null; probleme: Problem[] } {
  const probleme: Problem[] = [];
  const kenntGruppe = (b: string) => Object.prototype.hasOwnProperty.call(gruppen, b);

  // Eine bestehende Karte behält ihren Gruppennamen (kein stilles Umbenennen); eine neue nimmt den Namen der gewählten Gruppe.
  let gruppeName = "";
  if (f.bestehend) {
    gruppeName = karten.find((k) => k.id === f.id)?.gruppe ?? (kenntGruppe(f.id.charAt(0)) ? gruppen[f.id.charAt(0)] : "");
    if (!gruppeName) probleme.push({ feld: "gruppe", text: "Die Gruppe der Karte ist nicht mehr bekannt. Bitte lade die Ansicht neu." });
  } else if (f.gruppeWahl !== "" && kenntGruppe(f.gruppeWahl)) {
    gruppeName = gruppen[f.gruppeWahl];
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
    else {
      const unzulaessig = wissenstextProblem(f.wissenstext);
      if (unzulaessig) probleme.push({ feld: "wissenstext", text: unzulaessig });
    }
  }

  const budget = zeichenBudget(karten, { id: f.id, wissen: f.wissen, wissenstext: wissenstext || null });
  if (budget.ueber) {
    probleme.push({ feld: "budget", text: `Das Katalogbudget ist überschritten: ${budget.genutzt} von ${budget.max} Zeichen. Kürze die Wissenstexte.` });
  }
  if (budget.zuViele) {
    probleme.push({ feld: "budget", text: `Der Katalog nimmt höchstens ${budget.eintraegeMax} Karten mit eigenem Wissenstext. Stelle eine andere Karte auf "keine" oder "Glossar".` });
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

/**
 * Der Rumpf für POST und PUT der Karten (Namen der Schnittstelle). Die Kennung steht nie darin: Beim Anlegen vergibt sie der Dienst
 * (höchste Zahl der Gruppe plus eins), beim Ändern steht sie im Pfad. Der Stand wird vom Dienst gesetzt (jede Änderung macht die Karte
 * zum Entwurf).
 */
export function eingabeZuRumpf(e: KartenEingabe): Record<string, unknown> {
  return {
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
