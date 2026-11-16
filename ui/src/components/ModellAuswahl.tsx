"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import {
  AUTOMATISCH,
  auswahlSperre,
  BEREICHE,
  bereichStand,
  erklaerung,
  gruppen,
  optionText,
  wirksamText,
} from "@/lib/modellauswahl";
import { ANTWORT_MS } from "@/lib/modellzugangHilfe";
import type { ModellBereich } from "@/lib/nachrichten";
import { useSelect } from "@/lib/store";
import type { ModellzugangAnfrage } from "@/lib/useWamo";
import { wamo } from "@/lib/wamo";

/**
 * Modelle je Aufgabe in der Karte Modellzugang (Wunsch von Niko vom 16.11.2026): Gesprächsmodell, Bildschirm und Bilder, Lernen und
 * Zusammenfassung, je "Automatisch (Standard)" oder ein Modell aus der Liste, die der Kern für diesen Zugang meldet (lib/modellauswahl.ts).
 * Ein Hausprofil sieht keine Claude-Modelle, ein vom Admin festgelegtes Profil sieht die Auswahl gesperrt mit Grund. Die Wahl gilt ab der
 * nächsten Sitzung; der Zustand kommt allein vom Kern zurück (modellzugang.modelle), nicht aus der Auswahl. Native Auswahllisten mit
 * Beschriftung (label) und Beschreibung (aria-describedby), damit Tastatur und Bildschirmleser ohne eigene Logik gehen.
 */
export const ModellAuswahl = memo(function ModellAuswahl({ senden }: { senden: (anfrage: ModellzugangAnfrage) => void }) {
  const id = useId();
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const betrieb = useSelect(wamo, (s) => s.betrieb);
  const [wartet, setWartet] = useState<{ bereich: ModellBereich; wert: string } | null>(null);
  const [fehler, setFehler] = useState<{ bereich: ModellBereich; text: string } | null>(null);
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Antwort des Kerns auf die eigene Wahl beendet das Warten (abgeleiteter Zustand wie in ModellWahl); nur die Antwort, die die gewartete
  // Wahl meldet, oder ein Fehler zählt.
  const [gesehen, setGesehen] = useState(zugang);
  if (zugang !== gesehen) {
    setGesehen(zugang);
    if (zugang?.aktion === "modell" && wartet !== null) {
      if (zugang.fehler || zugang.modelle?.[wartet.bereich]?.wahl === wartet.wert) {
        setFehler(zugang.fehler ? { bereich: wartet.bereich, text: zugang.fehler } : null);
        setWartet(null);
      }
    }
  }

  useEffect(() => {
    if (wartet === null && uhr.current) {
      clearTimeout(uhr.current);
      uhr.current = null;
    }
  }, [wartet]);

  useEffect(() => () => {
    if (uhr.current) clearTimeout(uhr.current);
  }, []);

  const sperre = auswahlSperre(zugang);
  const bedienbar = zugang?.art !== undefined && sperre === null && wartet === null;

  const waehle = (bereich: ModellBereich, wert: string) => {
    if (!bedienbar || wert === bereichStand(zugang, bereich)?.wahl) return;
    setFehler(null);
    setWartet({ bereich, wert });
    if (uhr.current) clearTimeout(uhr.current);
    uhr.current = setTimeout(() => {
      setWartet(null);
      setFehler({ bereich, text: "Keine Antwort vom Kern. Bitte später noch einmal versuchen." });
    }, ANTWORT_MS);
    senden({ aktion: "modell", bereich, modell: wert });
  };

  return (
    <div className="mz-wahl mz-modelle">
      {sperre && <p className="mz-offline">{sperre}</p>}
      {BEREICHE.map((b) => {
        const stand = bereichStand(zugang, b.id);
        const wert = wartet?.bereich === b.id ? wartet.wert : (stand?.wahl ?? AUTOMATISCH);
        return (
          <div key={b.id} className="mz-wahl mz-modell">
            <label htmlFor={`${id}-${b.id}`} className="mz-wahlLabel">
              {b.name}
            </label>
            <select
              id={`${id}-${b.id}`}
              value={wert}
              disabled={!bedienbar || !stand}
              aria-describedby={`${id}-${b.id}-zweck ${id}-${b.id}-text`}
              onChange={(e) => waehle(b.id, e.target.value)}
            >
              <option value={AUTOMATISCH}>Automatisch (Standard)</option>
              {gruppen(stand).map((g) => (
                <optgroup key={g.name} label={g.name}>
                  {g.optionen.map((o) => (
                    <option key={o.id} value={o.id}>
                      {optionText(o)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <p id={`${id}-${b.id}-zweck`} className="mz-klein">
              {b.zweck}
            </p>
            <p id={`${id}-${b.id}-text`} className="mz-klein">
              {erklaerung(stand, wert)}
            </p>
            {stand?.hinweis && <p className="mz-klein">{stand.hinweis}</p>}
            {fehler?.bereich === b.id && (
              <p className="mz-meldung" role="alert" data-fehler>
                {fehler.text}
              </p>
            )}
          </div>
        );
      })}
      <p className="mz-klein" role="status">
        {wartet ? "Wird gespeichert …" : wirksamText("gespraech", betrieb)}
      </p>
    </div>
  );
});
