"use client";

import { useId } from "react";
import { dauerText, msText } from "@/lib/werkstattAnsicht";
import { FLAECHE, LATENZ_GRENZE_MS, achsenMax, balken, linie, ticks, xMitte, yFuer, zeigeEtikett } from "@/lib/werkstattDiagramm";
import { tagKurz } from "@/lib/werkstattFristen";
import type { LatenzTag, SitzungTag } from "@/lib/werkstattTypen";

/**
 * Die zwei Diagramme der Dashboards: Sitzungen je Tag (Balken) und Latenz des ersten Tons (p50 und p95 als zwei Linien, dazu die
 * Grenze des Lasttests). Gezeichnet wird als SVG mit der Geometrie aus lib/werkstattDiagramm.ts. Jedes Diagramm hat eine kurze
 * Beschreibung für Hilfstechnik und eine Tabelle mit denselben Zahlen: Nichts steht nur im Bild, die Linien unterscheiden sich
 * auch durch ihre Form (durchgezogen, gestrichelt), nicht nur durch die Farbe.
 */

function Achse({ max, einheit }: { max: number; einheit: (wert: number) => string }) {
  return (
    <>
      {ticks(max).map((t) => (
        <g key={t.wert}>
          <line className="ws-gitterlinie" x1={FLAECHE.links} x2={FLAECHE.breite - FLAECHE.rechts} y1={t.y} y2={t.y} />
          <text x={FLAECHE.links - 6} y={t.y + 4} textAnchor="end">
            {einheit(t.wert)}
          </text>
        </g>
      ))}
    </>
  );
}

function Tage({ tage }: { tage: readonly string[] }) {
  return (
    <>
      {tage.map((t, i) =>
        zeigeEtikett(i, tage.length) ? (
          <text key={t} x={xMitte(i, tage.length)} y={FLAECHE.hoehe - 12} textAnchor="middle">
            {tagKurz(t)}
          </text>
        ) : null,
      )}
    </>
  );
}

export function SitzungenDiagramm({ tage }: { tage: readonly SitzungTag[] }) {
  const titelId = useId();
  if (tage.length === 0) return <p className="ws-leer">Für diesen Zeitraum gibt es noch keine Sitzungen.</p>;
  const max = achsenMax(Math.max(...tage.map((t) => t.anzahl)));
  const stangen = balken(tage.map((t) => ({ etikett: t.tag, wert: t.anzahl })), max);
  const letzter = tage[tage.length - 1];
  return (
    <>
      <svg className="ws-diagramm" viewBox={`0 0 ${FLAECHE.breite} ${FLAECHE.hoehe}`} role="img" aria-labelledby={titelId}>
        <title id={titelId}>{`Sitzungen je Tag, ${tage.length} Tage, am letzten Tag ${letzter.anzahl}. Die Zahlen stehen darunter in der Tabelle.`}</title>
        <Achse max={max} einheit={(w) => String(Math.round(w))} />
        {stangen.map((b) => (
          <rect key={b.etikett} className="ws-balken" data-letzter={b.letzter || undefined} x={b.x} y={b.y} width={b.breite} height={b.hoehe} rx={2} />
        ))}
        <Tage tage={tage.map((t) => t.tag)} />
      </svg>
      <details className="ws-details">
        <summary>Zahlen als Tabelle</summary>
        <div className="ws-scroll">
          <table className="ws-tabelle">
            <caption>Sitzungen je Tag</caption>
            <thead>
              <tr>
                <th scope="col">Tag</th>
                <th scope="col" className="num">Sitzungen</th>
                <th scope="col" className="num">Dauer p50</th>
                <th scope="col" className="num">Dauer p95</th>
                <th scope="col" className="num">Offen</th>
              </tr>
            </thead>
            <tbody>
              {[...tage].reverse().map((t) => (
                <tr key={t.tag}>
                  <th scope="row">{tagKurz(t.tag)}</th>
                  <td className="num">{t.anzahl}</td>
                  <td className="num">{dauerText(t.dauerP50S)}</td>
                  <td className="num">{dauerText(t.dauerP95S)}</td>
                  <td className="num">{t.offen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

export function LatenzDiagramm({ zeilen }: { zeilen: readonly LatenzTag[] }) {
  const titelId = useId();
  const tage = zeilen.filter((z): z is LatenzTag & { tag: string } => z.tag !== null);
  if (zeilen.length === 0) return <p className="ws-leer">Für diesen Zeitraum gibt es noch keine Züge.</p>;
  if (tage.length === 0) {
    const z = zeilen[0];
    return (
      <dl className="ws-liste">
        <div><dt>Züge</dt><dd className="num">{z.zuege}</dd></div>
        <div><dt>Erster Ton, p50</dt><dd className="num">{msText(z.p50Ms)}</dd></div>
        <div><dt>Erster Ton, p95</dt><dd className="num">{msText(z.p95Ms)}</dd></div>
      </dl>
    );
  }
  const hoechster = Math.max(LATENZ_GRENZE_MS, ...tage.map((t) => t.p95Ms ?? 0), ...tage.map((t) => t.p50Ms ?? 0));
  const max = achsenMax(hoechster);
  const p50 = linie(tage.map((t) => t.p50Ms), max);
  const p95 = linie(tage.map((t) => t.p95Ms), max);
  const yGrenze = yFuer(LATENZ_GRENZE_MS, max);
  const letzter = tage[tage.length - 1];
  return (
    <>
      <svg className="ws-diagramm" viewBox={`0 0 ${FLAECHE.breite} ${FLAECHE.hoehe}`} role="img" aria-labelledby={titelId}>
        <title id={titelId}>{`Erster Ton je Tag, p50 und p95 in Millisekunden. Am letzten Tag p50 ${msText(letzter.p50Ms)}, p95 ${msText(letzter.p95Ms)}. Die Zahlen stehen darunter in der Tabelle.`}</title>
        <Achse max={max} einheit={(w) => `${Math.round(w / 100) / 10} s`} />
        <line className="ws-grenze" x1={FLAECHE.links} x2={FLAECHE.breite - FLAECHE.rechts} y1={yGrenze} y2={yGrenze} />
        <polyline className="ws-linie" data-art="p95" points={p95.punkte} />
        <polyline className="ws-linie" data-art="p50" points={p50.punkte} />
        {p95.letzter && <circle className="ws-punkt" data-art="p95" cx={p95.letzter.x} cy={p95.letzter.y} r={4} />}
        {p50.letzter && <circle className="ws-punkt" data-art="p50" cx={p50.letzter.x} cy={p50.letzter.y} r={4} />}
        <Tage tage={tage.map((t) => t.tag)} />
      </svg>
      <div className="ws-legende" aria-hidden="true">
        <span data-art="p50">p50, durchgezogen</span>
        <span data-art="p95">p95, gestrichelt</span>
        <span data-art="grenze">Grenze des Lasttests, {LATENZ_GRENZE_MS} ms bei acht Sitzungen</span>
      </div>
      <details className="ws-details">
        <summary>Zahlen als Tabelle</summary>
        <div className="ws-scroll">
          <table className="ws-tabelle">
            <caption>Erster Ton je Tag</caption>
            <thead>
              <tr>
                <th scope="col">Tag</th>
                <th scope="col" className="num">Züge</th>
                <th scope="col" className="num">p50</th>
                <th scope="col" className="num">p95</th>
              </tr>
            </thead>
            <tbody>
              {[...tage].reverse().map((t) => (
                <tr key={t.tag}>
                  <th scope="row">{tagKurz(t.tag)}</th>
                  <td className="num">{t.zuege}</td>
                  <td className="num">{msText(t.p50Ms)}</td>
                  <td className="num">{msText(t.p95Ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
