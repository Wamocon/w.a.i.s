import type { ComponentType } from "react";
import { SCHRITT_TITEL, type SchrittId } from "@/lib/einrichtungSchritte";
import { EinrichtungZusammenfassung } from "./EinrichtungZusammenfassung";
import { InstallerDownload } from "./InstallerDownload";
import { SchrittApiSchluessel } from "./SchrittApiSchluessel";
import { SchrittToken } from "./SchrittToken";

/**
 * Schnittstelle der Schritte beim Ausrollen für das Gerüst des geführten Ablaufs (Schritteliste in LoginGate, Paket P1b)
 * und für EinrichtungsAblauf. Jeder Schritt ist eigenständig: er holt seinen Stand selbst und ruft weiter() nach dem
 * Speichern oder Überspringen; zurueck fehlt beim ersten Schritt. Welche Schritte für ein Profil gelten, sagt
 * schrittSichtbar aus lib/einrichtungSchritte.ts (ist das Profil auf Hausmodelle festgelegt, entfallen Token und API-Schlüssel).
 */
export type EinrichtungsSchrittProps = { weiter: () => void; zurueck?: () => void };

export type EinrichtungsSchritt = {
  id: SchrittId;
  titel: string;
  ueberspringbar: boolean;
  Komponente: ComponentType<EinrichtungsSchrittProps>;
};

/** Reihenfolge nach D2: Token, API-Schlüssel, Zusammenfassung, Installer. */
export const EINRICHTUNG_SCHRITTE: readonly EinrichtungsSchritt[] = Object.freeze([
  { id: "token", titel: SCHRITT_TITEL.token, ueberspringbar: true, Komponente: SchrittToken },
  { id: "api", titel: SCHRITT_TITEL.api, ueberspringbar: true, Komponente: SchrittApiSchluessel },
  { id: "zusammenfassung", titel: SCHRITT_TITEL.zusammenfassung, ueberspringbar: false, Komponente: EinrichtungZusammenfassung },
  { id: "installer", titel: SCHRITT_TITEL.installer, ueberspringbar: true, Komponente: InstallerDownload },
]);
