"use client";

import { useId, useState } from "react";
import { protokolleLaden } from "@/lib/werkstattApi";
import { STUFEN, STUNDEN_OPTIONEN, anzahlText, stufeArt, zeitpunktText } from "@/lib/werkstattAnsicht";
import type { ProtokollAntwort } from "@/lib/werkstattTypen";
import { FehlerHinweis, Karte, Laedt, Pille } from "./Bausteine";
import { useAbruf } from "./useAbruf";

/**
 * Bereich "Protokolle" (nur lesend): Zeit, Quelle, Stufe, ein fester Code und ein paar Zahlen. Gesprächstext, Namen und Geräte
 * erscheinen hier nie; die Quellen und Stufen kommen aus der Erlaubnisliste des Dienstes. Höchstens 500 Zeilen je Abruf.
 */

const HOECHSTMENGE = 500;

function Tabelle({ antwort }: { antwort: ProtokollAntwort }) {
  const n = antwort.zeilen.length;
  if (n === 0) return <p className="ws-leer">Keine Einträge für diesen Filter.</p>;
  return (
    <div className="ws-scroll">
      <table className="ws-tabelle">
        <caption role="status">
          {anzahlText(n, "Eintrag", "Einträge")}
          {n >= HOECHSTMENGE ? `, das ist die Höchstmenge. Wähle eine Quelle, eine Stufe oder einen kürzeren Zeitraum, um enger zu suchen.` : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">Zeit</th>
            <th scope="col">Quelle</th>
            <th scope="col">Stufe</th>
            <th scope="col">Code</th>
            <th scope="col">Zahlen</th>
          </tr>
        </thead>
        <tbody>
          {antwort.zeilen.map((z, i) => (
            <tr key={`${z.zeit}-${z.marke}-${z.code}-${i}`}>
              <td className="ws-mono">{zeitpunktText(z.zeit)}</td>
              <td className="ws-mono">{z.marke}</td>
              <td>
                <Pille art={stufeArt(z.stufe)}>{z.stufe}</Pille>
              </td>
              <td className="ws-mono">{z.code}</td>
              <td>{z.zahlen}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Protokolle() {
  const id = useId();
  const [marke, setMarke] = useState("");
  const [stufe, setStufe] = useState("");
  const [stunden, setStunden] = useState<number>(24);
  const [gesehen, setGesehen] = useState<string[]>([]);
  const abruf = useAbruf((s) => protokolleLaden({ marke, stufe, stunden }, s), `${marke}|${stufe}|${stunden}`);

  // Die Quellen, die je zu sehen waren: so bleibt der Wechsel von einer Quelle zur anderen möglich, auch wenn die Antwort nur eine zeigt.
  const neue = abruf.daten ? [...new Set([...abruf.daten.marken, ...abruf.daten.zeilen.map((z) => z.marke)])] : [];
  if (neue.some((m) => !gesehen.includes(m))) setGesehen([...new Set([...gesehen, ...neue])].sort());

  return (
    <div className="ws-bereich">
      <p className="ws-kurz">Nur Zeit, Quelle, Stufe und ein fester Code. Gesprächstext, Namen und Geräte erscheinen hier nie.</p>
      <Karte
        titel="Einträge"
        rechts={
          <button type="button" className="btn-secondary btn-small" onClick={abruf.neu}>
            Aktualisieren
          </button>
        }
      >
        <div className="ws-zeile">
          <div className="ws-feld">
            <label htmlFor={`${id}-marke`}>Quelle</label>
            <select id={`${id}-marke`} value={marke} onChange={(e) => setMarke(e.target.value)}>
              <option value="">alle</option>
              {[...new Set([...gesehen, ...(marke ? [marke] : [])])].sort().map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-stufe`}>Stufe</label>
            <select id={`${id}-stufe`} value={stufe} onChange={(e) => setStufe(e.target.value)}>
              <option value="">alle</option>
              {STUFEN.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-stunden`}>Zeitraum</label>
            <select id={`${id}-stunden`} value={stunden} onChange={(e) => setStunden(Number(e.target.value))}>
              {STUNDEN_OPTIONEN.map((h) => (
                <option key={h} value={h}>
                  {h === 1 ? "letzte Stunde" : `letzte ${h} Stunden`}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div aria-busy={abruf.laedt || undefined}>
          {abruf.fehler && <FehlerHinweis fehler={abruf.fehler} onNeu={abruf.neu} />}
          {abruf.daten ? <Tabelle antwort={abruf.daten} /> : !abruf.fehler && <Laedt was="Die Protokolle" />}
        </div>
      </Karte>
    </div>
  );
}
