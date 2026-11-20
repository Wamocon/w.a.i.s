"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { erneutWartezeit } from "@/lib/einrichtung";

/**
 * Sperre für "Erneut prüfen" und "Nach Updates suchen" (höchstens einmal je 10 Sekunden, lib/einrichtung.ts) aus einer einzigen Uhr
 * (performance.now, monoton). Der Zeitgeber zeigt nur an, was die Uhr sagt: Er schaut beim Ablauf noch einmal nach und stellt sich bei
 * Bedarf neu. Vor jedem neuen Zeitgeber wird der alte gelöscht, beim Aushängen läuft keiner mehr.
 */
export function useSperre() {
  const [gesperrt, setGesperrt] = useState(false);
  const letzter = useRef<number | null>(null);
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (uhr.current !== null) clearTimeout(uhr.current);
      uhr.current = null;
    },
    [],
  );

  const nachsehen = useCallback(function pruefe() {
    if (uhr.current !== null) clearTimeout(uhr.current);
    const warten = erneutWartezeit(letzter.current, performance.now());
    uhr.current = warten > 0 ? setTimeout(pruefe, warten) : null;
    setGesperrt(warten > 0);
  }, []);

  const frei = useCallback(() => erneutWartezeit(letzter.current, performance.now()) === 0, []);
  const sperren = useCallback(() => {
    letzter.current = performance.now();
    nachsehen();
  }, [nachsehen]);

  return { gesperrt, frei, sperren };
}
