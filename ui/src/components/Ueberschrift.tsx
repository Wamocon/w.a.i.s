"use client";

import { createContext, useContext, type HTMLAttributes, type Ref } from "react";

/**
 * Überschriften, die ihre Ebene von der Seite bekommen, auf der sie stehen. Jede Komponente nennt die Ebene, die sie für sich allein
 * hätte (4 für eine Überschrift unter einer Abschnittsüberschrift der Stufe 3); steht sie auf einer Seite, die eine Ebene mehr
 * braucht (die Einstellungen: Seite 2, Gruppe 3, Abschnitt 4, dazu UeberschriftVersatz mit 1), rückt sie entsprechend ein. Außerhalb
 * einer solchen Seite bleibt alles beim Alten (Versatz 0), die Komponenten in den Schritten beim Ausrollen ändern sich nicht.
 * Über Ebene 6 hinaus gibt es kein Überschriften-Element: dann trägt ein div die Rolle heading mit aria-level, wie es WAI-ARIA vorsieht.
 */
const Versatz = createContext(0);
export const UeberschriftVersatz = Versatz.Provider;

type Ebene = 1 | 2 | 3 | 4 | 5 | 6;
type Props = Omit<HTMLAttributes<HTMLElement>, "role"> & { ebene: Ebene; ref?: Ref<HTMLElement> };

const TAGS = { 1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" } as const;

export function Ueberschrift({ ebene, ref, children, ...rest }: Props) {
  const gesamt = ebene + useContext(Versatz);
  if (gesamt <= 6) {
    const Tag = TAGS[gesamt as Ebene];
    return (
      <Tag ref={ref as Ref<HTMLHeadingElement> | undefined} {...(rest as HTMLAttributes<HTMLHeadingElement>)}>
        {children}
      </Tag>
    );
  }
  return (
    <div {...(rest as HTMLAttributes<HTMLDivElement>)} role="heading" aria-level={gesamt} ref={ref as Ref<HTMLDivElement> | undefined}>
      {children}
    </div>
  );
}
