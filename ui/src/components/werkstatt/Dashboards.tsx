"use client";

import { useEffect, useId, useState } from "react";
import { aktionenLaden, betriebLaden, latenzLaden, sitzungenLaden } from "@/lib/werkstattApi";
import { BETRIEB_ALT_S, TAGE_OPTIONEN, alterText, zustand } from "@/lib/werkstattAnsicht";
import type { AktionZeile, Betrieb } from "@/lib/werkstattTypen";
import { Abrufinhalt, Karte, Pille } from "./Bausteine";
import { LatenzDiagramm, SitzungenDiagramm } from "./Diagramme";
import { useAbruf, type Abruf } from "./useAbruf";

/**
 * Bereich "Dashboards" (nur lesend): Betrieb jetzt, Aktionen, Sitzungen je Tag und Latenz des ersten Tons. Alles sind Zahlen, Stände
 * und Zeiten, nie Gesprächstext, Namen oder Geräte. Der Zeitraum gilt für alle drei Abfragen; die Betriebsdatei des Sammlers wird
 * jede Minute neu gelesen, solange der Tab sichtbar ist.
 */

const TAKT_MS = 60_000;

function BetriebKarte({ abruf }: { abruf: Abruf<Betrieb> }) {
  return (
    <Karte titel="Betrieb jetzt">
      <Abrufinhalt abruf={abruf} was="Der Betrieb">
        {(b) => <BetriebListe b={b} />}
      </Abrufinhalt>
    </Karte>
  );
}

function BetriebListe({ b }: { b: Betrieb }) {
  const kanal = zustand(b.kanal.zustand);
  const labor = zustand(b.laborDienst.zustand);
  const alt = b.alterS !== null && b.alterS > BETRIEB_ALT_S;
  return (
    <>
      <dl className="ws-liste">
        <div>
          <dt>Kern{b.kern.slot ? `, Slot ${b.kern.slot}` : ""}</dt>
          <dd>
            <Pille art={b.kern.aktiv === null ? "neutral" : b.kern.aktiv ? "ok" : "warn"}>
              <span className="ws-mono">{b.kern.release ?? "unbekannt"}</span>, {b.kern.aktiv === null ? "Zustand unbekannt" : b.kern.aktiv ? "aktiv" : "nicht aktiv"}
            </Pille>
          </dd>
        </div>
        <div>
          <dt>Oberfläche</dt>
          <dd>
            <Pille art="ok">
              <span className="ws-mono">{b.oberflaeche.version ?? "unbekannt"}</span>
              {b.oberflaeche.farbe ? `, ${b.oberflaeche.farbe}` : ""}
            </Pille>
          </dd>
        </div>
        <div>
          <dt>Installer</dt>
          <dd><span className="ws-mono">{b.installer.version ?? "unbekannt"}</span></dd>
        </div>
        <div>
          <dt>Kern-Kanal für Aufträge</dt>
          <dd><Pille art={kanal.art}>{kanal.text}</Pille></dd>
        </div>
        <div>
          <dt>Labor-Dienst</dt>
          <dd><Pille art={labor.art}>{labor.text}</Pille></dd>
        </div>
      </dl>
      <p className="ws-klein" role={alt ? "alert" : undefined}>
        {alt
          ? `Der Sammler hat zuletzt ${alterText(b.alterS)} gemeldet. Die Angaben können veraltet sein.`
          : `Stand ${alterText(b.alterS)}, der Sammler schreibt jede Minute.`}
      </p>
    </>
  );
}

/** Aktionen je Werkzeug und Status, mit der Summe je Werkzeug. */
function AktionenTabelle({ zeilen }: { zeilen: readonly AktionZeile[] }) {
  if (zeilen.length === 0) return <p className="ws-leer">In diesem Zeitraum gab es keine Aktionen.</p>;
  const gesamt = zeilen.reduce((s, z) => s + z.anzahl, 0);
  return (
    <div className="ws-scroll">
      <table className="ws-tabelle">
        <caption>{`Aktionen im Zeitraum, insgesamt ${gesamt}`}</caption>
        <thead>
          <tr>
            <th scope="col">Werkzeug</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">Anzahl</th>
          </tr>
        </thead>
        <tbody>
          {zeilen.map((z) => (
            <tr key={`${z.tool}/${z.status}`}>
              <th scope="row">{z.tool}</th>
              <td>{z.status}</td>
              <td className="num">{z.anzahl}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Dashboards() {
  const [tage, setTage] = useState<number>(14);
  const gruppeId = useId();
  const betrieb = useAbruf((s) => betriebLaden(s), "betrieb");
  const sitzungen = useAbruf((s) => sitzungenLaden(tage, s), `sitzungen-${tage}`);
  const latenz = useAbruf((s) => latenzLaden(tage, s), `latenz-${tage}`);
  const aktionen = useAbruf((s) => aktionenLaden(tage, s), `aktionen-${tage}`);
  const neuBetrieb = betrieb.neu;
  useEffect(() => {
    const takt = setInterval(() => {
      if (document.visibilityState === "visible") neuBetrieb();
    }, TAKT_MS);
    return () => clearInterval(takt);
  }, [neuBetrieb]);
  const alleNeu = () => {
    betrieb.neu();
    sitzungen.neu();
    latenz.neu();
    aktionen.neu();
  };
  return (
    <div className="ws-bereich">
      <div className="ws-kopf">
        <div>
          <p className="ws-kurz">Zahlen und Zustände ohne Gesprächsinhalt. Kennzahlen werden verdichtet gespeichert und nach 30 Tagen gelöscht.</p>
        </div>
        <div className="ws-zeile ws-zeile-mitte">
          <div className="ws-seg" role="group" aria-labelledby={gruppeId}>
            <span id={gruppeId} className="sr-only">Zeitraum</span>
            {TAGE_OPTIONEN.map((t) => (
              <button key={t} type="button" aria-pressed={tage === t} onClick={() => setTage(t)}>
                {t} Tage
              </button>
            ))}
          </div>
          <button type="button" className="btn-secondary btn-small" onClick={alleNeu}>
            Aktualisieren
          </button>
        </div>
      </div>
      <div className="ws-gitter">
        <BetriebKarte abruf={betrieb} />
        <Karte titel="Aktionen">
          <Abrufinhalt abruf={aktionen} was="Die Aktionen">
            {(z) => <AktionenTabelle zeilen={z} />}
          </Abrufinhalt>
        </Karte>
      </div>
      <div className="ws-gitter ws-gitter-breit">
        <Karte titel="Sitzungen je Tag">
          <Abrufinhalt abruf={sitzungen} was="Die Sitzungen">
            {(t) => <SitzungenDiagramm tage={t} />}
          </Abrufinhalt>
        </Karte>
        <Karte titel="Erster Ton, p50 und p95">
          <Abrufinhalt abruf={latenz} was="Die Latenz">
            {(z) => <LatenzDiagramm zeilen={z} />}
          </Abrufinhalt>
        </Karte>
      </div>
    </div>
  );
}
