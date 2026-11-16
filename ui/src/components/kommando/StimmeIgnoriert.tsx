"use client";

import { useEffect, useRef } from "react";
import { ignoriertHinweis } from "@/lib/stimme";
import { useSelect } from "@/lib/store";
import { wamo, zeigeToast } from "@/lib/wamo";

/**
 * Kurzer Hinweis "Fremde Stimme ignoriert" (oder "Stimme nicht sicher erkannt, ignoriert"): Im strengen Modus verwirft der Kern eine
 * fremde Äußerung oder eine unklare mit niedrigem Wert (Nachricht stimme mit ignoriert, voice-core/stimme_waechter.py), sie erreicht das
 * Sprachmodell nicht, und ihr Untertitel verschwindet wieder (lib/wamo.ts, nutzerTranskript). Der Hinweis nimmt den gemeinsamen Toast der
 * Seite (sichtbar, mit role="status" für Screenreader, verschwindet von selbst). Jede verworfene Äußerung meldet sich neu, auch zwei gleiche
 * hintereinander, deshalb hängt er am Zähler und nicht am Zustand. Die Komponente rendert nichts und hängt nur bei Konten ein, die die
 * Stimmerkennung sehen (nicht bei Laborkonten, lib/laborPlatz.ts); das Modul "Stimme" in der Kopfzeile zeigt dazu "Fremd · ignoriert"
 * oder "Unklar · ignoriert".
 */
export function StimmeIgnoriertHinweis() {
  const zaehler = useSelect(wamo, (s) => s.stimme.ignoriertZaehler);
  const ergebnis = useSelect(wamo, (s) => s.stimme.ergebnis); // derselbe Stand wie der Zähler, nicht der beim Ausführen des Effekts
  const gesehen = useRef(zaehler); // beim Einhängen gilt der aktuelle Stand als bekannt: nichts wird nachträglich gemeldet
  useEffect(() => {
    if (zaehler > gesehen.current) zeigeToast(ignoriertHinweis(ergebnis));
    gesehen.current = zaehler;
  }, [zaehler, ergebnis]);
  return null;
}
