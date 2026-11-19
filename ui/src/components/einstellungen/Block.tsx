"use client";

import { useId, type ReactNode } from "react";
import { Ueberschrift } from "@/components/Ueberschrift";

/**
 * Ein Block innerhalb eines Abschnitts: Karte mit kleiner Überschrift. Ihre Stufe richtet sich nach der Seite (components/Ueberschrift.tsx):
 * in den Einstellungen ist es die Stufe 5 (Seite 2, Gruppe 3, Abschnitt 4).
 */
export function Block({ titel, children }: { titel: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className="ez-block" aria-labelledby={id}>
      <Ueberschrift ebene={4} id={id} className="ez-block-titel">
        {titel}
      </Ueberschrift>
      {children}
    </section>
  );
}

/** Beschriftungsliste (Name links, Wert rechts) im Stil der Seitenleiste. */
export function Daten({ zeilen }: { zeilen: readonly { name: string; wert: ReactNode }[] }) {
  return (
    <dl className="ez-daten">
      {zeilen.map((z) => (
        <div key={z.name}>
          <dt>{z.name}</dt>
          <dd>{z.wert}</dd>
        </div>
      ))}
    </dl>
  );
}
