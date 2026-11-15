import type { CanvasItem } from "@/components/Canvas";

/**
 * Canvas als Datei am PC speichern (voice-core/office_werkzeuge.py, host/office_dateien.py): welche Knöpfe ein Canvas-Element zeigt und
 * was der Hinweis danach sagt. Die Oberfläche bietet nur an, was der Kern in betrieb.office meldet (Admin, PC-Steuerung an, Host kann es);
 * geprüft wird trotzdem im Kern und im Host.
 */
export const OFFICE_FORMATE = ["word", "excel", "powerpoint", "pdf", "csv", "markdown"] as const;
export type OfficeFormat = (typeof OFFICE_FORMATE)[number];

export const FORMAT_NAME: Record<OfficeFormat, string> = {
  word: "Word",
  excel: "Excel",
  powerpoint: "PowerPoint",
  pdf: "PDF",
  csv: "CSV",
  markdown: "Markdown",
};

const NUR_TABELLE: readonly OfficeFormat[] = ["excel", "csv"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Was die Oberfläche auslösen kann (useWamo); true, wenn die Nachricht an den Kern gesendet wurde. */
export type OfficeAktionen = {
  /** eigenes, gespeichertes Canvas-Element als Datei am PC speichern (Nachricht canvas_export) */
  speichern: (canvasId: string, format: OfficeFormat) => boolean;
  /** eine gespeicherte Datei öffnen (Nachricht datei_oeffnen, nur Dateien aus dem Register des Hosts) */
  oeffnen: (kennung: string) => boolean;
  /** eigenes Canvas-Element als OneNote-Seite, erst nach der Freigabekarte (Nachricht onenote_seite, voice-core/onenote_werkzeuge.py) */
  onenote?: (canvasId: string) => boolean;
};

/** Text des Knopfs für OneNote; die Seite entsteht erst nach dem Klick auf die Freigabekarte. */
export const ONENOTE_KNOPF = "Als OneNote-Seite";

/** Ergebnis des Speicherns (Servernachricht "datei"). */
export type DateiMeldung =
  | { ok: true; kennung: string; name: string; format?: OfficeFormat; ordner?: string; pfad?: string; geoeffnet: boolean }
  | { ok: false; grund: string };

export const istOfficeFormat = (v: unknown): v is OfficeFormat =>
  typeof v === "string" && (OFFICE_FORMATE as readonly string[]).includes(v);

/**
 * Formate für ein Element: nur eigene, gespeicherte Elemente (Kennung aus der Datenbank, nicht geteilt, kein Auftragsergebnis), nur
 * Formate aus betrieb.office, Excel und CSV nur für Tabellen.
 */
type ExportItem = Pick<CanvasItem, "kind"> & Partial<Pick<CanvasItem, "id" | "geteilt" | "teilbar">>;

/** Eigenes, gespeichertes Element: Kennung aus der Datenbank, nicht geteilt, kein Auftragsergebnis. */
const eigenesElement = (item: ExportItem) => !item.geteilt && !item.teilbar && typeof item.id === "string" && UUID.test(item.id);

export function exportFormate(item: ExportItem, verfuegbar: readonly string[] | undefined): OfficeFormat[] {
  if (!verfuegbar?.length || !eigenesElement(item)) return [];
  return OFFICE_FORMATE.filter((f) => verfuegbar.includes(f) && (item.kind === "tabelle" || !NUR_TABELLE.includes(f)));
}

/** "Als OneNote-Seite" für jede Art, aber nur für eigene, gespeicherte Elemente und nur, wenn der Kern betrieb.onenote meldet. */
export const onenoteMoeglich = (item: ExportItem, an: boolean | undefined): boolean => an === true && eigenesElement(item);

export const knopfText = (f: OfficeFormat) => `Als ${FORMAT_NAME[f]} speichern`;

/** Ein Satz für den Hinweis nach dem Speichern (auch die Ansage für Screenreader). */
export function hinweisText(d: DateiMeldung): string {
  if (!d.ok) return `Nicht gespeichert: ${d.grund}`;
  return `${d.name} liegt in ${d.ordner || "Dokumente\\WAIS"}${d.geoeffnet ? " und ist geöffnet." : "."}`;
}
