"use client";

import { useId, type ReactNode } from "react";
import type { ZustandArt } from "@/lib/werkstattAnsicht";
import type { FehlerBild } from "@/lib/werkstattTypen";

/** Kleine gemeinsame Bausteine der Werkstatt: Zustandswort mit Form, Fehlerhinweis, Karte mit Überschrift, Ladehinweis. */

/** Zustand als Wort und Form (werkstatt.css); die Farbe ist nur Beigabe. */
export function Pille({ art = "neutral", children }: { art?: ZustandArt | "akzent"; children: ReactNode }) {
  return (
    <span className="ws-pille" data-art={art}>
      {children}
    </span>
  );
}

/** Fehler als ruhiger Satz mit Meldungsrolle; "Neu laden" nur, wenn die Stelle es anbietet. */
export function FehlerHinweis({ fehler, onNeu }: { fehler: FehlerBild; onNeu?: () => void }) {
  return (
    <div className="ws-fehler" role="alert">
      <span>{fehler.text}</span>
      {onNeu && (
        <button type="button" className="btn-secondary btn-small" onClick={onNeu}>
          Neu laden
        </button>
      )}
    </div>
  );
}

/** Karte mit Überschrift der zweiten Ebene (unter der Überschrift des Bereichs); rechts im Kopf darf etwas stehen. */
export function Karte({ titel, rechts, children }: { titel: string; rechts?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section className="ws-karte" aria-labelledby={id}>
      <div className="ws-karte-kopf">
        <h2 id={id}>{titel}</h2>
        {rechts}
      </div>
      {children}
    </section>
  );
}

/** Platzhalter, solange eine Karte noch lädt: ein Wort, damit auch Screenreader es hören. */
export function Laedt({ was }: { was: string }) {
  return (
    <p className="ws-klein" role="status">
      {was} wird geladen …
    </p>
  );
}

/** Inhalt einer Karte, die von einem Abruf lebt: Fehler, Laden oder die Daten. */
export function Abrufinhalt<T>({
  abruf,
  was,
  children,
}: {
  abruf: { daten: T | null; fehler: FehlerBild | null; laedt: boolean; neu: () => void };
  was: string;
  children: (daten: T) => ReactNode;
}) {
  if (abruf.fehler) return <FehlerHinweis fehler={abruf.fehler} onNeu={abruf.neu} />;
  if (abruf.daten === null) return <Laedt was={was} />;
  return <>{children(abruf.daten)}</>;
}
