"use client";

import { useCallback, useEffect } from "react";
import { useSelect } from "@/lib/store";
import { updates, updatesInstallieren, updatesLaden, updatesSucheMoeglich } from "@/lib/updatesStore";
import { useSperre } from "./useSperre";

/**
 * Stand der Updates für den Abschnitt Updates (Updates.tsx): der gemeinsame Speicher (lib/updatesStore.ts, derselbe wie im Pop-up
 * "Update verfügbar"), dazu die Sperre für "Nach Updates suchen" (einmal je 10 Sekunden, lib/einrichtung.ts). Beim Einhängen wird nur
 * geladen, wenn noch nie geprüft wurde (das Pop-up hat es meist schon getan). Suche und Installation laufen immer nur eine zugleich
 * und nie beide, auch wenn das Pop-up sie angestoßen hat. Das Token holt erst der Klick und gibt es nur an die App weiter.
 */
export function useUpdates() {
  const zustand = useSelect(updates, (s) => s);
  const { gesperrt, frei, sperren } = useSperre();

  useEffect(() => {
    const erster = setTimeout(() => {
      if (updates.get().stand === null) void updatesLaden(); // nicht im Effekt selbst: Der erste Abruf setzt Zustand
    }, 0);
    return () => clearTimeout(erster);
  }, []);

  const suchen = useCallback(() => {
    if (!updatesSucheMoeglich() || !frei()) return;
    sperren();
    void updatesLaden();
  }, [frei, sperren]);

  return { ...zustand, gesperrt, suchen, installieren: updatesInstallieren };
}
