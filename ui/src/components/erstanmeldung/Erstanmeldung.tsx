"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ERSTANMELDUNG_SCHRITTE } from "@/components/erstanmeldung/schritte";
import type { ErstanmeldungKontext, ErstanmeldungSchritt } from "@/components/erstanmeldung/typen";
import { ablaufMerkerLoeschen, ablaufMerkerSetzen } from "@/lib/erstanmeldung";

/**
 * Geführter Ablauf der Erstanmeldung: oben eine Leiste der Schritte (erledigt, aktuell, folgt), darunter die Überschrift und der
 * aktuelle Schritt. Die Schritte kommen aus einer Liste (schritte.tsx); Schritte mit noetig() = false werden übergangen, nach dem
 * letzten ruft der Ablauf fertig() auf. Bei jedem Schrittwechsel bekommt die Überschrift den Fokus (Hilfstechnik liest den Schritt
 * vor). Solange der Ablauf läuft, steht ein Merker im sessionStorage (lib/erstanmeldung.ts): Ein Neuladen der Seite führt ihn auch
 * nach dem Passwortwechsel weiter, damit die späteren Schritte nicht verloren gehen. Am Ende und beim Abmelden wird er gelöscht.
 */

/** So lange darf eine Prüfung noetig() dauern; danach wird der Schritt gezeigt (lieber zeigen als verschweigen). */
export const NOETIG_ZEIT_MS = 8_000;

/** Ergebnis der Prüfung oder true, wenn sie nach ms noch nicht geantwortet hat. */
async function mitZeitgrenze(pruefung: boolean | Promise<boolean>, ms: number): Promise<boolean> {
  let uhr: ReturnType<typeof setTimeout> | undefined;
  const grenze = new Promise<boolean>((ok) => {
    uhr = setTimeout(() => ok(true), ms);
  });
  try {
    return await Promise.race([Promise.resolve(pruefung), grenze]);
  } finally {
    clearTimeout(uhr);
  }
}

/** Erster Schritt ab "von", der nötig ist (oder dessen Prüfung scheitert oder zu lange dauert); schritte.length, wenn keiner mehr nötig ist. */
async function naechsterNoetiger(
  schritte: readonly ErstanmeldungSchritt[],
  von: number,
  kontext: ErstanmeldungKontext,
  zeitMs: number,
): Promise<number> {
  for (let i = von; i < schritte.length; i++) {
    const pruefung = schritte[i].noetig;
    if (!pruefung) return i;
    try {
      if (await mitZeitgrenze(pruefung(kontext), zeitMs)) return i;
    } catch {
      return i; // Prüfung kaputt: lieber zeigen als verschweigen
    }
  }
  return schritte.length;
}

type Zustand = "erledigt" | "aktuell" | "folgt";
const ZUSTAND_TEXT: Record<Zustand, string> = { erledigt: "erledigt", aktuell: "aktuell", folgt: "folgt" };

export function Erstanmeldung({
  kontext,
  fertig,
  schritte = ERSTANMELDUNG_SCHRITTE,
  noetigZeitMs = NOETIG_ZEIT_MS,
}: {
  kontext: ErstanmeldungKontext;
  /** Alle nötigen Schritte sind durch */
  fertig: () => void;
  schritte?: readonly ErstanmeldungSchritt[];
  /** Zeitgrenze je noetig(); nur für Tests anders als NOETIG_ZEIT_MS */
  noetigZeitMs?: number;
}) {
  /** ab hier wird nach dem nächsten nötigen Schritt gesucht */
  const [aktuell, setAktuell] = useState(0);
  /** der gezeigte Schritt; null, solange gesucht wird */
  const [anzeige, setAnzeige] = useState<number | null>(null);
  const ueberschrift = useRef<HTMLHeadingElement>(null);

  // Neueste Werte für die Suche, ohne sie bei jedem Render neu auszulösen (das Tor baut den Kontext bei jeder Änderung neu)
  const neueste = useRef({ kontext, fertig, schritte, noetigZeitMs });
  useEffect(() => {
    neueste.current = { kontext, fertig, schritte, noetigZeitMs };
  });

  const userId = kontext.userId;
  useEffect(() => {
    ablaufMerkerSetzen(userId);
  }, [userId]);

  useEffect(() => {
    let abgebrochen = false;
    const { kontext: k, schritte: liste, noetigZeitMs: zeit } = neueste.current;
    void naechsterNoetiger(liste, aktuell, k, zeit).then((i) => {
      if (abgebrochen) return;
      if (i >= liste.length) {
        ablaufMerkerLoeschen(k.userId);
        neueste.current.fertig();
        return;
      }
      setAnzeige(i);
    });
    return () => {
      abgebrochen = true;
    };
  }, [aktuell]);

  // Schrittwechsel: Fokus auf die Überschrift des neuen Schritts
  useEffect(() => {
    if (anzeige !== null) ueberschrift.current?.focus();
  }, [anzeige]);

  /** Vom Schritt i zum nächsten; ein spät eintreffender Aufruf eines alten Schritts ändert nichts. */
  const weiterVon = useCallback((i: number) => {
    setAnzeige((a) => (a === i ? null : a));
    setAktuell((a) => (a <= i ? i + 1 : a));
  }, []);

  const position = anzeige ?? aktuell;
  const schritt = anzeige === null ? null : (schritte[anzeige] ?? null);
  const Inhalt = schritt?.komponente;
  const zustand = (i: number): Zustand => (i < position ? "erledigt" : i === position ? "aktuell" : "folgt");

  return (
    <div className="ea">
      <ol className="ea-leiste" aria-label="Schritte der Erstanmeldung">
        {schritte.map((s, i) => (
          <li
            key={s.id}
            className="ea-punkt"
            data-zustand={zustand(i)}
            aria-current={zustand(i) === "aktuell" ? "step" : undefined}
          >
            <span className="ea-nr" aria-hidden="true">
              {zustand(i) === "erledigt" ? "✓" : i + 1}
            </span>
            <span>{s.titel}</span>
            <span className="sr-only"> ({ZUSTAND_TEXT[zustand(i)]})</span>
          </li>
        ))}
      </ol>
      {schritt && Inhalt && anzeige !== null ? (
        <>
          <h2 className="ea-titel" ref={ueberschrift} tabIndex={-1}>
            {schritt.ueberschrift ?? schritt.titel}
          </h2>
          <Inhalt
            key={schritt.id}
            kontext={kontext}
            weiter={() => weiterVon(anzeige)}
            ueberspringen={schritt.ueberspringbar ? () => weiterVon(anzeige) : undefined}
          />
        </>
      ) : (
        <p className="gate-hint">Einen Moment …</p>
      )}
    </div>
  );
}
