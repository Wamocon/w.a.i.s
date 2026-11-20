"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { fehlerBildAus, plaetzeLaden, plaetzeSpeichern } from "@/lib/werkstattApi";
import {
  GAST_MAX,
  PLATZ_ZWECK_TEXT,
  erlaubteZwecke,
  mitZweck,
  platzZeilen,
  plaetzePruefen,
  type LaborProblem,
  type PlatzZeile,
} from "@/lib/werkstattLabor";
import type { FehlerBild, Platz, PlatzZweck } from "@/lib/werkstattTypen";
import { Abrufinhalt, FehlerHinweis, Karte } from "./Bausteine";
import { useAbruf } from "./useAbruf";

/**
 * Karte "Plätze": die 16 Plätze eines Termins mit Zweck (Besucher, Reserve, Abnahme), Kennung des Laborprofils und einem Pseudonym
 * für den Gast (zum Beispiel "Gast 1", nie ein Name). Ein Platz ohne Zweck wird nicht verwendet. Abnahme gibt es nur an 15 und 16.
 */

function PlatzTabelle({ terminId, plaetze, onGespeichert }: { terminId: string; plaetze: readonly Platz[]; onGespeichert: () => void }) {
  const id = useId();
  const [zeilen, setZeilen] = useState<PlatzZeile[]>(() => platzZeilen(plaetze));
  const [probleme, setProbleme] = useState<LaborProblem[]>([]);
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [meldung, setMeldung] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const problemRef = useRef<HTMLDivElement>(null);
  const setze = (platz: number, neu: (z: PlatzZeile) => PlatzZeile) => setZeilen((alt) => alt.map((z) => (z.platz === platz ? neu(z) : z)));

  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setMeldung("");
    setFehler(null);
    const r = plaetzePruefen(zeilen);
    setProbleme(r.probleme);
    if (!r.plaetze) {
      requestAnimationFrame(() => problemRef.current?.focus());
      return;
    }
    setLaeuft(true);
    try {
      await plaetzeSpeichern(terminId, r.plaetze);
      setMeldung("Die Plätze sind gespeichert.");
      onGespeichert();
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuft(false);
    }
  };

  return (
    <form onSubmit={(e) => void speichern(e)} noValidate style={{ display: "grid", gap: 12 }}>
      <div className="ws-scroll">
        <table className="ws-tabelle">
          <caption>Plätze 1 bis 16</caption>
          <thead>
            <tr>
              <th scope="col">Platz</th>
              <th scope="col">Zweck</th>
              <th scope="col">Kennung</th>
              <th scope="col">Gast (Pseudonym)</th>
            </tr>
          </thead>
          <tbody>
            {zeilen.map((z) => (
              <tr key={z.platz}>
                <th scope="row">{z.platz}</th>
                <td>
                  <select
                    aria-label={`Zweck von Platz ${z.platz}`}
                    value={z.zweck}
                    onChange={(e) => setze(z.platz, (alt) => mitZweck(alt, e.target.value as PlatzZweck | ""))}
                  >
                    <option value="">nicht verwendet</option>
                    {erlaubteZwecke(z.platz).map((w) => (
                      <option key={w} value={w}>{PLATZ_ZWECK_TEXT[w]}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    aria-label={`Kennung von Platz ${z.platz}`}
                    className="ws-mono"
                    value={z.kennung}
                    disabled={z.zweck === ""}
                    maxLength={14}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(e) => setze(z.platz, (alt) => ({ ...alt, kennung: e.target.value }))}
                  />
                </td>
                <td>
                  <input
                    aria-label={`Gast an Platz ${z.platz}`}
                    value={z.gast}
                    disabled={z.zweck === ""}
                    maxLength={GAST_MAX + 10}
                    autoComplete="off"
                    onChange={(e) => setze(z.platz, (alt) => ({ ...alt, gast: e.target.value }))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p id={`${id}-hilfe`} className="ws-klein">Der Gast ist nur ein Pseudonym, zum Beispiel „Gast 1“, nie ein Name. Die Kennung gehört zum Laborprofil des Platzes.</p>
      {probleme.length > 0 && (
        <div ref={problemRef} className="ws-fehler" role="alert" tabIndex={-1}>
          <span>{probleme.map((p) => p.text).join(" ")}</span>
        </div>
      )}
      {fehler && <FehlerHinweis fehler={fehler} />}
      <div className="ws-aktionen">
        <button type="submit" className="btn-primary" disabled={laeuft} aria-describedby={`${id}-hilfe`}>
          Plätze speichern
        </button>
      </div>
      <p className="ws-erfolg" role="status">{meldung}</p>
    </form>
  );
}

export function LaborPlaetze({ terminId }: { terminId: string }) {
  const abruf = useAbruf((s) => plaetzeLaden(terminId, s), `plaetze-${terminId}`);
  return (
    <Karte titel="Plätze">
      <Abrufinhalt abruf={abruf} was="Die Plätze">
        {(p) => <PlatzTabelle key={`${terminId}-${JSON.stringify(p)}`} terminId={terminId} plaetze={p} onGespeichert={abruf.neu} />}
      </Abrufinhalt>
    </Karte>
  );
}
