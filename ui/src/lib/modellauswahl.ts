import type { Betrieb, ModellBereich, ModellBereichStand, ModellOption, Modellzugang } from "./nachrichten.ts";

/**
 * Modellwahl je Person (Wunsch von Niko vom 16.11.2026, voice-core/modellwahl.py, Migration 0024): je Bereich "Automatisch" (der Boss
 * wählt, Standard) oder ein Modell aus der Liste, die der Kern für diesen Zugang anbietet. Die Oberfläche zeigt nur, was der Kern meldet:
 * ein Hausprofil bekommt keine Claude-Modelle, ein vom Admin festgelegtes Profil sieht die Wahl gesperrt mit Grund. Entscheiden und
 * prüfen tut allein der Kern. Reine Funktionen, getestet in modellauswahl.test.ts.
 */

export const AUTOMATISCH = "automatisch";

export const BEREICHE: readonly { id: ModellBereich; name: string; zweck: string }[] = [
  { id: "gespraech", name: "Gesprächsmodell", zweck: "Mit welchem Modell W.A.I.S. mit dir spricht." },
  { id: "bilder", name: "Bildschirm und Bilder", zweck: "Welches Modell Bildschirmfotos und Bilder liest." },
  {
    id: "hintergrund",
    name: "Lernen und Zusammenfassung",
    zweck: "Welches Modell nach dem Gespräch lernt und lange Gespräche zusammenfasst.",
  },
];

/** Satz, warum die Modellwahl gesperrt ist, oder null. Ohne lesbaren Stand null (die Karte zeigt dann den Fehler selbst). */
export function auswahlSperre(z: Modellzugang | null): string | null {
  if (z?.art === undefined) return null;
  if (!z.modelle) return "Dieser Kern kennt die Modellwahl noch nicht. Sie kommt mit der nächsten Version des Kerns.";
  return z.modellSperre ?? null;
}

export function bereichStand(z: Modellzugang | null, bereich: ModellBereich): ModellBereichStand | null {
  return z?.modelle?.[bereich] ?? null;
}

/** Gruppen für die Auswahl: Claude (nur wenn der Kern es anbietet) und die Modelle im Haus, je in der Reihenfolge des Kerns. */
export function gruppen(stand: ModellBereichStand | null): { name: string; optionen: ModellOption[] }[] {
  const optionen = stand?.optionen ?? [];
  return [
    { name: "Claude (Cloud, über deinen Schlüssel)", optionen: optionen.filter((o) => o.art === "claude") },
    { name: "Im Haus", optionen: optionen.filter((o) => o.art === "haus") },
  ].filter((g) => g.optionen.length > 0);
}

/** Text eines Eintrags in der Auswahl: Name und die Zeile zu Güte und Tempo aus der Modellkarte. */
export function optionText(o: ModellOption): string {
  return o.zeile ? `${o.name} · ${o.zeile}` : o.name;
}

export function wahlName(stand: ModellBereichStand | null, wahl: string): string {
  if (wahl === AUTOMATISCH) return "Automatisch";
  return stand?.optionen.find((o) => o.id === wahl)?.name ?? wahl;
}

/** Was die Wahl bedeutet, in einem Satz. */
export function erklaerung(stand: ModellBereichStand | null, wahl: string): string {
  if (wahl === AUTOMATISCH) {
    return "W.A.I.S. wählt selbst das beste erlaubte Modell nach der Modellkarte. Das ist der Standard.";
  }
  const o = stand?.optionen.find((x) => x.id === wahl);
  if (!o) return "Dieses Modell bietet der Kern gerade nicht an; W.A.I.S. wählt automatisch.";
  const text = `${o.name}: ${o.zeile || "keine Messwerte"}.`;
  return o.art === "claude"
    ? `${text} Läuft über deinen Claude-Schlüssel in der Cloud und geht von deinem Guthaben ab.`
    : `${text} Ist es gerade nicht erreichbar oder zu langsam, übernimmt das nächstbeste Modell, und die Statusleiste nennt den Grund.`;
}

/** Satz unter der Auswahl: gilt ab der nächsten Sitzung; beim Gespräch dazu der Grund, wenn die laufende Sitzung abweicht. */
export function wirksamText(bereich: ModellBereich, betrieb: Betrieb | null): string {
  const grund = bereich === "gespraech" ? betrieb?.modellHinweis?.trim().replace(/[.\s]+$/, "") : undefined;
  return grund
    ? `Diese Sitzung: ${grund}. Die Wahl gilt ab der nächsten Sitzung.`
    : "Die Wahl gilt ab der nächsten Sitzung.";
}
