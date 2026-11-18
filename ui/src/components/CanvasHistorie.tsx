"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { CanvasItem } from "@/components/Canvas";
import { artText, historieZeilen, type Historie, type HistorieZeile } from "@/lib/canvasHistorie";
import type { HistorieQuelle } from "@/lib/canvasOeffnen";
import { KernFehler } from "@/lib/kernApi";
import { useSelect } from "@/lib/store";
import { canvasWiederOeffnen, wamo, zeigeToast } from "@/lib/wamo";

/**
 * Aufklappbare Historie des Canvas (Wunsch vom 18.11.2026), standardmäßig zu. Oben die Reiter, die in dieser Sitzung geschlossen wurden
 * (öffnen sich ohne den Kern wieder, auch eigene Bilder), darunter ältere Elemente aus der Datenbank: eigene und mit der Person geteilte
 * (voice-core/canvas_historie.py, geladen beim Aufklappen). Ohne quelle (Laborkonten) nur diese Sitzung. Ein Klick öffnet das Element wieder
 * als Reiter und klappt die Historie zu; Escape klappt sie zu, der Fokus geht zurück auf den Knopf.
 */
export function CanvasHistorie({ quelle }: { quelle?: HistorieQuelle }) {
  const [offen, setOffen] = useState(false);
  const zu = useSelect(wamo, (s) => s.canvasZu);
  const items = useSelect(wamo, (s) => s.canvas);
  const [db, setDb] = useState<Historie | null>(null);
  const [stand, setStand] = useState<"bereit" | "laedt" | "fehler">("bereit");
  const [oeffnet, setOeffnet] = useState<string | null>(null);
  const listeId = useId();
  const knopf = useRef<HTMLButtonElement>(null);
  // Zählt Ladevorgänge: eine späte Antwort (zweites Aufklappen, Aushängen) setzt keinen Zustand mehr
  const lauf = useRef(0);
  useEffect(
    () => () => {
      lauf.current += 1;
    },
    [],
  );

  const laden = async () => {
    if (!quelle) return;
    const nr = ++lauf.current;
    setStand("laedt");
    try {
      const h = await quelle.laden();
      if (nr !== lauf.current) return;
      setDb(h);
      setStand("bereit");
    } catch {
      if (nr === lauf.current) setStand("fehler");
    }
  };

  const zuklappen = () => {
    setOffen(false);
    knopf.current?.focus();
  };

  const oeffnen = async (z: HistorieZeile<CanvasItem>) => {
    if (oeffnet !== null) return; // ein Öffnen läuft (Knöpfe nur aria-disabled, damit der Fokus bleibt)
    if (z.sitzung) {
      canvasWiederOeffnen(z.sitzung);
      zuklappen();
      return;
    }
    if (!z.id || !quelle) return;
    setOeffnet(z.id);
    try {
      await quelle.oeffnen(z.id);
      zuklappen();
    } catch (e) {
      zeigeToast(e instanceof KernFehler ? e.message : "Öffnen fehlgeschlagen");
    } finally {
      setOeffnet(null);
    }
  };

  const taste = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      zuklappen();
    }
  };

  const zeilen = historieZeilen(zu, db, items);
  const ladeText = stand === "laedt" ? "Wird geladen …" : stand === "fehler" ? "Die ältere Historie ist gerade nicht erreichbar." : null;

  return (
    <div className="canvas-historie">
      <button
        ref={knopf}
        type="button"
        className="btn-secondary btn-small canvas-historie-knopf"
        aria-expanded={offen}
        aria-controls={listeId}
        onClick={() => {
          setOffen(!offen);
          if (!offen) void laden();
        }}
      >
        Historie{zeilen.sitzung.length ? ` (${zeilen.sitzung.length})` : ""}
      </button>
      <div id={listeId} className="canvas-historie-liste" hidden={!offen} onKeyDown={taste}>
        {offen && (
          <>
            <Abschnitt
              titel="In dieser Sitzung geschlossen"
              zeilen={zeilen.sitzung}
              leer="Noch kein Reiter geschlossen."
              oeffnet={oeffnet}
              oeffnen={oeffnen}
            />
            {quelle && (
              <Abschnitt
                titel="Ältere Elemente"
                zeilen={zeilen.frueher}
                leer={stand === "bereit" ? "Keine älteren Elemente." : null}
                oeffnet={oeffnet}
                oeffnen={oeffnen}
              />
            )}
            {quelle && ladeText && (
              <p className="canvas-historie-stand" data-art={stand === "fehler" ? "fehler" : undefined}>
                {ladeText}
              </p>
            )}
          </>
        )}
      </div>
      {/* Ansage für Screenreader: immer im DOM und außerhalb der versteckten Liste, sonst geht "Wird geladen" verloren */}
      {quelle && (
        <p className="sr-only" aria-live="polite">
          {offen ? (ladeText ?? "") : ""}
        </p>
      )}
    </div>
  );
}

function zeitText(ms: number | null): string | null {
  return ms === null ? null : new Date(ms).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

function Abschnitt({
  titel,
  zeilen,
  leer,
  oeffnet,
  oeffnen,
}: {
  titel: string;
  zeilen: HistorieZeile<CanvasItem>[];
  leer: string | null;
  oeffnet: string | null;
  oeffnen: (z: HistorieZeile<CanvasItem>) => Promise<void>;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h3 id={id} className="canvas-historie-titel">
        {titel}
      </h3>
      {zeilen.length ? (
        <ul className="canvas-historie-eintraege">
          {zeilen.map((z) => (
            <li key={z.schluessel}>
              <button
                type="button"
                className="canvas-historie-eintrag"
                aria-disabled={oeffnet !== null || undefined}
                aria-busy={oeffnet !== null && oeffnet === z.id ? true : undefined}
                onClick={() => void oeffnen(z)}
              >
                <span className="sr-only">Öffnen:</span> <span className="canvas-historie-name">{z.titel}</span>
                <span className="canvas-historie-meta">
                  {[artText(z.art), zeitText(z.zeit), z.von ? `von ${z.von}` : null].filter(Boolean).join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        leer && <p className="canvas-historie-leer">{leer}</p>
      )}
    </section>
  );
}
