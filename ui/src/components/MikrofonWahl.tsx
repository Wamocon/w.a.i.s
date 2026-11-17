"use client";

import { useEffect, useRef, useState } from "react";
import type { Mikrofon } from "@/lib/mikrofon";
import { useSelect } from "@/lib/store";
import { wamo } from "@/lib/wamo";

/**
 * Liste der angeschlossenen Mikrofone. Lädt beim Erscheinen, noch einmal, wenn Geräte kommen oder gehen (devicechange), und bei
 * jedem neuen Wert von anstoss (zum Beispiel nach der Freigabe des Mikrofons). null, solange die erste Antwort aussteht. Eine
 * Antwort, die erst nach dem Verschwinden der Komponente oder nach einem neueren Abruf eintrifft, wird verworfen.
 */
export function useMikrofonListe(laden: () => Promise<Mikrofon[]>, anstoss = 0): Mikrofon[] | null {
  const [liste, setListe] = useState<Mikrofon[] | null>(null);
  const lauf = useRef(0); // nur die Antwort des letzten Abrufs zählt (ein Gerät kann kommen, während ein Abruf läuft)
  useEffect(() => {
    let weg = false;
    const holen = () => {
      const meiner = ++lauf.current;
      void laden().then((l) => {
        if (!weg && meiner === lauf.current) setListe(l);
      });
    };
    holen();
    const geraete = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
    geraete?.addEventListener?.("devicechange", holen);
    return () => {
      weg = true;
      geraete?.removeEventListener?.("devicechange", holen);
    };
  }, [laden, anstoss]);
  return liste;
}

/**
 * Mikrofon einmal freigeben, damit der Browser die Namen der Geräte nennt (vorher liefert enumerateDevices weder Namen noch Kennungen).
 * Öffnet das Standardgerät kurz und schließt es sofort wieder; es wird nichts aufgenommen oder gesendet. true, wenn die Freigabe gelang.
 */
export async function mikrofonFreigeben(): Promise<boolean> {
  const geraete = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
  if (!geraete?.getUserMedia) return false;
  try {
    const strom = await geraete.getUserMedia({ audio: true });
    for (const spur of strom.getTracks()) spur.stop();
    return true;
  } catch {
    return false;
  }
}

/** Gerätewahl in der Mikrofon-Warnung: Liste beim Erscheinen laden, Wechsel gilt sofort und auf diesem Gerät. */
export function MikrofonWahl({ laden, waehlen }: { laden: () => Promise<Mikrofon[]>; waehlen: (id: string) => boolean }) {
  const liste = useMikrofonListe(laden);
  const aktuell = useSelect(wamo, (s) => s.mikrofon);
  if (!liste || liste.length === 0) return null;
  return (
    <label className="mic-wahl">
      <span>Anderes Mikrofon:</span>
      <select defaultValue="" onChange={(e) => e.target.value && waehlen(e.target.value)}>
        <option value="" disabled>
          {aktuell ? `jetzt: ${aktuell}` : "wählen …"}
        </option>
        {liste.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );
}
