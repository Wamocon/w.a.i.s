"use client";

import { fallAus, zusammenfassung } from "@/lib/einrichtungSchritte";
import { useModellzugangStandHalten } from "@/lib/modellzugangApi";
import { useSelect } from "@/lib/store";
import { wamo } from "@/lib/wamo";
import type { EinrichtungsSchrittProps } from "./schritte";
import { SchrittKnoepfe } from "./SchrittKnoepfe";

/**
 * Zusammenfassung nach den beiden Schlüsselschritten: "So arbeitet W.A.I.S. für dich", je eine Zeile für Gespräch (mit
 * Lernen und Websuche), Entwicklungsaufträge und Stimme, nach dem Fall aus dem Stand des Kerns (lib/einrichtungSchritte.ts).
 * Eigenständig: holt den Stand selbst. Zeigt nie einen Schlüssel, nur was daraus folgt.
 */
export function EinrichtungZusammenfassung({ weiter, zurueck }: EinrichtungsSchrittProps) {
  useModellzugangStandHalten(undefined);
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const fall = fallAus(zugang);
  const z = fall ? zusammenfassung(fall) : null;
  const standFehler = zugang && !zugang.art && zugang.fehler ? zugang.fehler : null;

  return (
    <div className="ea-schritt">
      {z ? (
        <section className="mz-abschnitt" aria-label={z.titel} data-fall={fall}>
          {z.hinweis && <p className="ea-text">{z.hinweis}</p>}
          <dl className="ea-zeilen">
            {z.zeilen.map((zeile) => (
              <div key={zeile.name}>
                <dt>{zeile.name}</dt>
                <dd>{zeile.text}</dd>
              </div>
            ))}
          </dl>
          <p className="ea-klein">{z.aendern}</p>
        </section>
      ) : standFehler ? (
        <div className="mz-falsch" role="alert">
          <p className="mz-meldung" data-fehler>
            Fehler: {standFehler}
          </p>
          <button
            type="button"
            className="btn-secondary btn-small"
            onClick={() => wamo.set((s) => ({ ...s, modellzugang: null }))}
          >
            Erneut versuchen
          </button>
        </div>
      ) : (
        <p className="ea-klein" role="status">
          Stand wird geladen …
        </p>
      )}
      <SchrittKnoepfe weiter={weiter} zurueck={zurueck} text="Weiter" primaer />
    </div>
  );
}
