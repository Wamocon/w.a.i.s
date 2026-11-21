"use client";

import { useId, useState } from "react";
import type { Gruppe } from "@/lib/werkstattKarten";
import type { Karte as KarteTyp } from "@/lib/werkstattTypen";
import { Pille } from "./Bausteine";

/**
 * Tabelle des Katalogs: alle Karten, nach Gruppe filterbar, mit Bearbeiten, Kopieren und (nur bei Entwürfen) Löschen. Löschen fragt
 * erst nach. Jede Schaltfläche trägt die Kennung der Karte im Namen, damit sie mit der Tastatur und mit Screenreader eindeutig ist.
 */

type Props = {
  karten: readonly KarteTyp[];
  gruppen: readonly Gruppe[];
  filter: string;
  onFilter: (buchstabe: string) => void;
  onBearbeiten: (k: KarteTyp) => void;
  onKopieren: (k: KarteTyp) => void;
  onLoeschen: (k: KarteTyp) => void;
  /** Kennung der Karte, die gerade gelöscht wird (Aufruf läuft) */
  beschaeftigt: string | null;
};

export function KartenKatalog({ karten, gruppen, filter, onFilter, onBearbeiten, onKopieren, onLoeschen, beschaeftigt }: Props) {
  const id = useId();
  const [frage, setFrage] = useState<string | null>(null);
  const sichtbar = filter ? karten.filter((k) => k.id.startsWith(filter)) : karten;
  return (
    <>
      <div className="ws-zeile">
        <div className="ws-feld">
          <label htmlFor={`${id}-gruppe`}>Gruppe anzeigen</label>
          <select id={`${id}-gruppe`} value={filter} onChange={(e) => onFilter(e.target.value)}>
            <option value="">alle</option>
            {gruppen.map((g) => (
              <option key={g.buchstabe} value={g.buchstabe}>
                {g.buchstabe} {g.name}
              </option>
            ))}
          </select>
        </div>
        <span className="ws-klein ws-mono" role="status">{sichtbar.length} von {karten.length} Karten</span>
      </div>
      {sichtbar.length === 0 ? (
        <p className="ws-leer">{karten.length === 0 ? "Der Katalog ist noch leer. Baue den ersten Use Case." : "In dieser Gruppe gibt es keine Karten."}</p>
      ) : (
        <div className="ws-scroll">
          <table className="ws-tabelle">
            <caption className="sr-only">Karten des Katalogs</caption>
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Gruppe</th>
                <th scope="col">Titel</th>
                <th scope="col">Fehlerfall</th>
                <th scope="col" className="num">Min.</th>
                <th scope="col">Stand</th>
                <th scope="col">Aktionen</th>
              </tr>
            </thead>
            <tbody>
              {sichtbar.map((k) => (
                <tr key={k.id}>
                  <th scope="row">{k.id}</th>
                  <td>{k.gruppe}</td>
                  <td>{k.titel}</td>
                  <td>{k.fehler ? <Pille art="warn">ja</Pille> : <Pille>nein</Pille>}</td>
                  <td className="num">{k.dauerMin}</td>
                  <td>
                    <Pille art={k.stand === "entwurf" ? "warn" : "ok"}>{k.stand === "entwurf" ? "Entwurf" : "veröffentlicht"}</Pille>
                  </td>
                  <td>
                    {frage === k.id ? (
                      <div className="ws-aktionen" role="group" aria-label={`Karte ${k.id} löschen`}>
                        <button type="button" className="btn-primary btn-small" disabled={beschaeftigt !== null} onClick={() => { setFrage(null); onLoeschen(k); }}>
                          Ja, {k.id} löschen
                        </button>
                        <button type="button" className="btn-secondary btn-small" onClick={() => setFrage(null)}>Abbrechen</button>
                      </div>
                    ) : (
                      <div className="ws-aktionen">
                        <button type="button" className="btn-secondary btn-small" aria-label={`${k.id} bearbeiten`} onClick={() => onBearbeiten(k)}>Bearbeiten</button>
                        <button type="button" className="btn-secondary btn-small" aria-label={`${k.id} kopieren`} onClick={() => onKopieren(k)}>Kopieren</button>
                        {k.stand === "entwurf" && (
                          <button type="button" className="btn-secondary btn-small" aria-label={`${k.id} löschen`} disabled={beschaeftigt !== null} onClick={() => setFrage(k.id)}>
                            Löschen
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="ws-klein">Gelöscht werden können nur Entwürfe. Eine veröffentlichte Karte bleibt im Katalog und lässt sich ändern oder kopieren.</p>
    </>
  );
}
