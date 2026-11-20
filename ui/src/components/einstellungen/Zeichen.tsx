import type { Stufe } from "@/lib/einrichtung";

/**
 * Das Zeichen vor einem Zustand (Prüfliste der Ersten Schritte, Abschnitt Updates): ein kleiner Kreis mit einem Symbol. Das Symbol
 * trägt den Zustand mit, die Farbe nie allein (Regeln in einstellungen.css, Präfix .es-). Für Screenreader ist das Zeichen versteckt,
 * der Zustand steht daneben als Wort. Ohne Angabe von form zeigt die Stufe das Symbol: bereit einen Haken, offen ein Ausrufezeichen,
 * Hinweis ein i.
 */
export type Form = "haken" | "ausruf" | "info" | "pfeil" | "punkte";

const PFAD: Record<Form, string> = {
  haken: "M3.5 8.5l3 3 6-7",
  ausruf: "M8 3.5v5.5M8 12.25v.25",
  info: "M8 7v5.5M8 3.75v.25",
  pfeil: "M8 12.5v-9M4.5 7L8 3.5L11.5 7",
  punkte: "M4 8v.01M8 8v.01M12 8v.01",
};

const FORM_DER_STUFE: Record<Stufe, Form> = { gruen: "haken", rot: "ausruf", hinweis: "info" };

export function Zeichen({ stufe, form }: { stufe: Stufe; form?: Form }) {
  return (
    <span className="es-zeichen" aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false">
        <path d={PFAD[form ?? FORM_DER_STUFE[stufe]]} />
      </svg>
    </span>
  );
}
