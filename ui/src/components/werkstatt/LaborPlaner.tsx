"use client";

import { useState } from "react";
import { laborStandLaden, termineLaden } from "@/lib/werkstattApi";
import { heuteIso } from "@/lib/werkstattFristen";
import { standardTermin } from "@/lib/werkstattLabor";
import type { LaborProfil, Termin } from "@/lib/werkstattTypen";
import { Abrufinhalt, Karte, Pille } from "./Bausteine";
import { LaborCheckliste } from "./LaborCheckliste";
import { LaborPlaetze } from "./LaborPlaetze";
import { LaborTermin, NEUER_TERMIN } from "./LaborTermin";
import { useAbruf } from "./useAbruf";

/**
 * Bereich "Labor-Planer": Termin und Fristen, Plätze und Checkliste eines Labortags aus einer Quelle, dazu der Stand der
 * Laborprofile (nur lesend). Was am Labortag selbst geschieht (Profile freischalten, sperren, Konten löschen) gehört zur nächsten
 * Stufe und läuft bis dahin über die Skripte des Runbooks.
 */

function StandTabelle({ profile }: { profile: readonly LaborProfil[] }) {
  if (profile.length === 0) return <p className="ws-leer">Es gibt noch keine Laborprofile.</p>;
  return (
    <div className="ws-scroll">
      <table className="ws-tabelle">
        <caption>Laborprofile, nur lesend</caption>
        <thead>
          <tr>
            <th scope="col">Art</th>
            <th scope="col">Platz</th>
            <th scope="col">Zustand</th>
            <th scope="col" className="num">Zeilen</th>
          </tr>
        </thead>
        <tbody>
          {profile.map((p, i) => (
            <tr key={`${p.art}-${p.platz ?? "x"}-${i}`}>
              <th scope="row">{p.kennung ?? p.art}</th>
              <td>{p.platz ?? "–"}</td>
              <td><Pille art={p.aktiv ? "akzent" : "neutral"}>{p.aktiv ? "freigeschaltet" : "gesperrt"}</Pille></td>
              <td className="num">{p.zeilen ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StufenKarte() {
  return (
    <Karte titel="Ausbaustufen des Panels">
      <ul className="ws-liste">
        <li>
          <span><Pille art="akzent">Stufe 1, jetzt</Pille> Konfiguration und Erstellung</span>
          <span className="ws-klein">Termine, Plätze, Fristen, Checkliste, Karten und Use Cases</span>
        </li>
        <li>
          <span><Pille>Stufe 2, nach dem Labortag</Pille> Betrieb am Labortag</span>
          <span className="ws-klein">Freischalten, sperren, zählen, Löschwunsch je Zeitfenster</span>
        </li>
        <li>
          <span><Pille>Stufe 3</Pille> Werkstatt</span>
          <span className="ws-klein">Releases, Installer, Aufträge, jeweils mit eigener Sicherheitsprüfung</span>
        </li>
      </ul>
      <p className="ws-klein">
        Passwörter, zweite Faktoren mit QR und der Dienstschlüssel erscheinen nie in diesem Fenster. Konten anlegen, Freischalten, Sperren und Löschen laufen bis zur nächsten Stufe weiter über die Skripte im Runbook (Abschnitte 9 und 10).
      </p>
    </Karte>
  );
}

function Plan({ termine, neuLaden }: { termine: readonly Termin[]; neuLaden: () => void }) {
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);
  const [heute] = useState(() => heuteIso(new Date()));
  const vorgabe = standardTermin(termine, heute)?.id ?? NEUER_TERMIN;
  const auswahl = gewaehlt !== null && (gewaehlt === NEUER_TERMIN || termine.some((t) => t.id === gewaehlt)) ? gewaehlt : vorgabe;
  const termin = termine.find((t) => t.id === auswahl) ?? null;
  return (
    <>
      <div className="ws-gitter ws-gitter-breit">
        <LaborTermin
          termine={termine}
          auswahl={auswahl}
          onWaehlen={setGewaehlt}
          onGeaendert={(id) => {
            setGewaehlt(id);
            neuLaden();
          }}
        />
        {termin ? (
          <LaborPlaetze terminId={termin.id} />
        ) : (
          <Karte titel="Plätze">
            <p className="ws-leer">Lege zuerst den Termin an. Dann lassen sich Plätze, Checkliste und Zuordnung planen.</p>
          </Karte>
        )}
      </div>
      <div className="ws-gitter ws-gitter-breit">
        {termin ? (
          <LaborCheckliste terminId={termin.id} />
        ) : (
          <Karte titel="Checkliste">
            <p className="ws-leer">Die Checkliste gehört zu einem Termin.</p>
          </Karte>
        )}
        <StufenKarte />
      </div>
    </>
  );
}

export function LaborPlaner() {
  const termine = useAbruf((s) => termineLaden(s), "termine");
  const stand = useAbruf((s) => laborStandLaden(s), "laborstand");
  return (
    <div className="ws-bereich">
      <p className="ws-kurz">
        Ein Labortag wird einmal geplant. Termin, Fristen, Plätze und Checkliste kommen aus dieser einen Quelle.
      </p>
      <Abrufinhalt abruf={termine} was="Die Termine">
        {(t) => <Plan termine={t} neuLaden={termine.neu} />}
      </Abrufinhalt>
      <Karte titel="Stand der Laborprofile" rechts={<Pille>nur lesend</Pille>}>
        <Abrufinhalt abruf={stand} was="Der Stand">
          {(p) => <StandTabelle profile={p} />}
        </Abrufinhalt>
      </Karte>
    </div>
  );
}
