/**
 * Zeichenfläche der Diagramme der Werkstatt (Sitzungen je Tag als Balken, Latenz als zwei Linien). Hier steht nur die Geometrie:
 * Achsen, Balken und Linienzüge in der Einheit des SVG-Koordinatensystems. Die Komponente zeichnet sie und legt eine Tabelle mit
 * denselben Zahlen daneben, damit nichts nur im Bild steht. Ohne React und ohne Browser (werkstattDiagramm.test.ts).
 */

export type Flaeche = { breite: number; hoehe: number; links: number; rechts: number; oben: number; unten: number };

export const FLAECHE: Flaeche = { breite: 640, hoehe: 230, links: 48, rechts: 20, oben: 14, unten: 34 };

/** Eine Obergrenze der Achse mit runden Schritten (1, 2, 2,5, 5, 10 mal Zehnerpotenz), die den größten Wert fasst. */
export function achsenMax(wert: number, schritte = 4): number {
  if (!Number.isFinite(wert) || wert <= 0) return schritte;
  const schritt = wert / schritte;
  const betrag = 10 ** Math.floor(Math.log10(schritt));
  const norm = schritt / betrag;
  const rund = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return rund * betrag * schritte;
}

export type Tick = { wert: number; y: number };

export function yFuer(wert: number, max: number, f: Flaeche = FLAECHE): number {
  const hoehe = f.hoehe - f.oben - f.unten;
  return f.oben + hoehe - hoehe * Math.min(Math.max(wert / max, 0), 1);
}

export function ticks(max: number, schritte = 4, f: Flaeche = FLAECHE): Tick[] {
  return Array.from({ length: schritte + 1 }, (_, i) => {
    const wert = (max / schritte) * i;
    return { wert, y: yFuer(wert, max, f) };
  });
}

export type Balken = { x: number; y: number; breite: number; hoehe: number; wert: number; etikett: string; letzter: boolean };

/** Balken für n Werte: gleich breit nebeneinander, 18 Prozent Luft an jeder Seite. */
export function balken(werte: readonly { etikett: string; wert: number }[], max: number, f: Flaeche = FLAECHE): Balken[] {
  const n = werte.length;
  if (n === 0) return [];
  const breiteJe = (f.breite - f.links - f.rechts) / n;
  const grundlinie = f.hoehe - f.unten;
  return werte.map((w, i) => {
    const y = yFuer(w.wert, max, f);
    return {
      x: f.links + i * breiteJe + breiteJe * 0.18,
      y,
      breite: breiteJe * 0.64,
      hoehe: Math.max(grundlinie - y, 0),
      wert: w.wert,
      etikett: w.etikett,
      letzter: i === n - 1,
    };
  });
}

export type Linienzug = { punkte: string; letzter: { x: number; y: number; wert: number } | null; einzeln: { x: number; y: number }[] };

/** Linienzug durch die Werte (null überspringt den Tag); die Punkte stehen mittig über dem Platz des Tages. */
export function linie(werte: readonly (number | null)[], max: number, f: Flaeche = FLAECHE): Linienzug {
  const n = werte.length;
  const breiteJe = n > 0 ? (f.breite - f.links - f.rechts) / n : 0;
  const punkte: { x: number; y: number; wert: number }[] = [];
  werte.forEach((w, i) => {
    if (w !== null) punkte.push({ x: f.links + i * breiteJe + breiteJe / 2, y: yFuer(w, max, f), wert: w });
  });
  const r = (v: number) => Math.round(v * 10) / 10;
  return {
    punkte: punkte.map((p) => `${r(p.x)},${r(p.y)}`).join(" "),
    letzter: punkte.length > 0 ? punkte[punkte.length - 1] : null,
    einzeln: punkte.map((p) => ({ x: p.x, y: p.y })),
  };
}

/** Wie oft eine Beschriftung der Achse steht: jede, solange es wenige sind, sonst jede zweite (die letzte immer). */
export function zeigeEtikett(index: number, anzahl: number): boolean {
  return anzahl <= 7 || index % 2 === 0 || index === anzahl - 1;
}

/** x-Mitte des Platzes für den Tag mit diesem Index. */
export function xMitte(index: number, anzahl: number, f: Flaeche = FLAECHE): number {
  const breiteJe = (f.breite - f.links - f.rechts) / Math.max(anzahl, 1);
  return f.links + index * breiteJe + breiteJe / 2;
}

/** Referenz für die Latenz: p95 des ersten Tons bei acht gleichzeitigen Sitzungen im Lasttest (docs/labor-lasttest.md). */
export const LATENZ_GRENZE_MS = 3500;
