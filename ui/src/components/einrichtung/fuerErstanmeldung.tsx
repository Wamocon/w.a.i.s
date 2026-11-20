"use client";

import type { ErstanmeldungSchritt, SchrittProps } from "@/components/erstanmeldung/typen";
import { schrittSichtbar, type SchrittId } from "@/lib/einrichtungSchritte";
import { modellzugangOhneGespraech } from "@/lib/modellzugangApi";
import type { Modellzugang } from "@/lib/nachrichten";
import { wamo } from "@/lib/wamo";
import { EINRICHTUNG_SCHRITTE, type EinrichtungsSchritt } from "./schritte";

/**
 * Die Schritte des Ausrollens (Claude-Code-Token, API-Schlüssel, Zusammenfassung, Installer; Entscheidung D2) als Schritte der
 * Erstanmeldung (components/erstanmeldung/schritte.tsx hängt sie hinter "passwort" ein). Die Schritte bringen ihre Knöpfe selbst mit
 * (Weiter oder Überspringen); der Adapter reicht nur weiter() durch. Ein "Zurück" gibt es im Ablauf der Erstanmeldung nicht.
 *
 * Wann ein Schritt kommt (noetig):
 *   token, api        nur wenn schrittSichtbar es erlaubt (nicht bei Admin-Zwang auf Hausmodelle) und noch nichts hinterlegt ist,
 *                     damit ein Neuladen mitten im Ablauf nicht noch einmal fragt. Ist der Stand nicht lesbar: zeigen.
 *   zusammenfassung   immer.
 *   installer         nur im Browser; in der Desktop-App ist W.A.I.S. schon installiert, Updates kommen dort über den Abschnitt
 *                     "Updates" der Einstellungen.
 * Laborprofile sehen den Ablauf nie (die Tür fragt für sie keine Erstanmeldung ab, components/LoginGate.tsx).
 *
 * Nach Abmelden oder in einem neuen Tab läuft der Ablauf nicht weiter (der Merker gilt nur im selben Tab): Alle Schritte bleiben in
 * den Einstellungen unter "Erste Schritte" erreichbar, das ist der Rückfall.
 */

/** Kurzer Name in der Leiste oben; die Überschrift über dem Schritt ist der volle Titel. */
const LEISTE: Readonly<Record<SchrittId, string>> = {
  token: "Token",
  api: "API-Schlüssel",
  zusammenfassung: "Überblick",
  installer: "Installer",
};

/** Stand des Modellzugangs: aus dem Speicher, sonst einmal beim Kern geholt (er landet im Speicher, die Schritte fragen nicht noch einmal). */
async function modellzugangStand(): Promise<Modellzugang | null> {
  const da = wamo.get().modellzugang;
  if (da && !da.fehler) return da;
  await modellzugangOhneGespraech({ aktion: "status" });
  const neu = wamo.get().modellzugang;
  return neu && !neu.fehler ? neu : null;
}

const inDerApp = () => typeof window !== "undefined" && Boolean(window.wamoDesktop?.isDesktop);

/** Kommt der Schritt im Ablauf der Erstanmeldung? Unklar heißt zeigen. */
export async function schrittNoetig(
  id: SchrittId,
  holen: () => Promise<Modellzugang | null> = modellzugangStand,
  app: () => boolean = inDerApp,
): Promise<boolean> {
  if (id === "installer") return !app();
  if (id === "zusammenfassung") return true;
  const zugang = await holen();
  if (zugang === null) return true;
  if (!schrittSichtbar(id, zugang)) return false;
  return id === "token" ? !zugang.codeHinterlegt : !zugang.hinterlegt;
}

function alsErstanmeldungSchritt(s: EinrichtungsSchritt): ErstanmeldungSchritt {
  const Inhalt = s.Komponente;
  function Schritt({ weiter }: SchrittProps) {
    return <Inhalt weiter={weiter} />;
  }
  Schritt.displayName = `ErstanmeldungSchritt(${s.id})`;
  return {
    id: s.id,
    titel: LEISTE[s.id],
    ueberschrift: s.titel,
    ueberspringbar: s.ueberspringbar,
    komponente: Schritt,
    noetig: () => schrittNoetig(s.id),
  };
}

/** Die Schritte des Ausrollens in der Reihenfolge nach D2, fertig für ERSTANMELDUNG_SCHRITTE. */
export const AUSROLLEN_SCHRITTE: readonly ErstanmeldungSchritt[] = Object.freeze(EINRICHTUNG_SCHRITTE.map(alsErstanmeldungSchritt));
