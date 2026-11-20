"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fehlerBildAus } from "@/lib/werkstattApi";
import type { FehlerBild } from "@/lib/werkstattTypen";

/**
 * Lädt Daten von der Werkstatt, sobald sich der Schlüssel ändert, und auf Wunsch neu (neu()). Der Hook hält nur die Antwort der
 * Schnittstelle, nie ein Token. Eine Antwort gilt nur für den Schlüssel, für den sie geladen wurde: Wechselt der Schlüssel (anderer
 * Zeitraum, anderer Termin), zeigt der Hook bis zur neuen Antwort nichts Altes. Beim Neuladen mit gleichem Schlüssel bleibt die
 * letzte Antwort sichtbar (laedt ist dann wahr). Ein veralteter Aufruf wird abgebrochen und nie übernommen.
 */
export type Abruf<T> = {
  daten: T | null;
  fehler: FehlerBild | null;
  laedt: boolean;
  neu: () => void;
};

type Stand<T> = { marke: string; daten: T | null; fehler: FehlerBild | null };

export function useAbruf<T>(laden: (signal: AbortSignal) => Promise<T>, schluessel: string, aktiv = true): Abruf<T> {
  const [stand, setStand] = useState<Stand<T>>({ marke: "", daten: null, fehler: null });
  const [zaehler, setZaehler] = useState(0);
  const ladenRef = useRef(laden);
  useEffect(() => {
    ladenRef.current = laden;
  });
  const marke = `${schluessel}#${zaehler}`;

  useEffect(() => {
    if (!aktiv) return;
    const steuerung = new AbortController();
    ladenRef.current(steuerung.signal).then(
      (daten) => {
        if (!steuerung.signal.aborted) setStand({ marke, daten, fehler: null });
      },
      (e: unknown) => {
        if (!steuerung.signal.aborted) setStand({ marke, daten: null, fehler: fehlerBildAus(e) });
      },
    );
    return () => steuerung.abort();
  }, [marke, aktiv]);

  const neu = useCallback(() => setZaehler((n) => n + 1), []);
  const gilt = stand.marke.startsWith(`${schluessel}#`);
  return {
    daten: gilt ? stand.daten : null,
    fehler: gilt ? stand.fehler : null,
    laedt: aktiv && stand.marke !== marke,
    neu,
  };
}
