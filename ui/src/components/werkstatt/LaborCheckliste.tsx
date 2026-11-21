"use client";

import { useId, useState, type FormEvent } from "react";
import { checklisteLaden, checklistePunktAnlegen, checklisteUmschalten, fehlerBildAus } from "@/lib/werkstattApi";
import { faelligkeit, heuteIso, tagText } from "@/lib/werkstattFristen";
import { checklistePruefen, fortschritt, type LaborProblem } from "@/lib/werkstattLabor";
import type { ChecklistePunkt, FehlerBild } from "@/lib/werkstattTypen";
import { Abrufinhalt, FehlerHinweis, Karte, Pille } from "./Bausteine";
import { useAbruf } from "./useAbruf";

/**
 * Karte "Checkliste": die Punkte zum Labortag mit Quelle (Abschnitt im Runbook) und Frist. Abhaken schreibt sofort. Der Zustand
 * eines Punktes steht als Wort da (erledigt, heute fällig, überfällig), nie nur als Farbe.
 */

function Punkte({ terminId, punkte, onGeaendert }: { terminId: string; punkte: readonly ChecklistePunkt[]; onGeaendert: () => void }) {
  const [heute] = useState(() => heuteIso(new Date()));
  const [laeuftNr, setLaeuftNr] = useState<number | null>(null);
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const f = fortschritt(punkte);

  const umschalten = async (p: ChecklistePunkt) => {
    if (laeuftNr !== null) return;
    setLaeuftNr(p.nr);
    setFehler(null);
    try {
      await checklisteUmschalten(terminId, p.nr, !p.erledigt);
      onGeaendert();
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuftNr(null);
    }
  };

  return (
    <>
      <div className="ws-meter" role="img" aria-label={`${f.erledigt} von ${f.gesamt} Punkten erledigt`}>
        <span style={{ width: `${f.prozent}%` }} />
      </div>
      <p className="ws-klein ws-mono">{f.erledigt} von {f.gesamt} erledigt</p>
      {fehler && <FehlerHinweis fehler={fehler} />}
      {punkte.length === 0 ? (
        <p className="ws-leer">Noch keine Punkte. Lege unten den ersten an.</p>
      ) : (
        <ul className="ws-punkte">
          {punkte.map((p) => {
            const art = faelligkeit(p.faellig, p.erledigt, heute);
            return (
              <li key={p.nr}>
                <label className="ws-pruef">
                  <input type="checkbox" checked={p.erledigt} disabled={laeuftNr !== null} onChange={() => void umschalten(p)} />
                  <span className="ws-punkt-text">
                    <span>{p.titel}</span>
                    {p.quelle && <small>{p.quelle}</small>}
                  </span>
                </label>
                <span>
                  {art === "erledigt" && <Pille art="ok">erledigt</Pille>}
                  {art === "ueberfaellig" && <Pille art="fehler">überfällig seit {tagText(p.faellig)}</Pille>}
                  {art === "heute" && <Pille art="warn">heute fällig</Pille>}
                  {art === "offen" && <Pille>fällig {tagText(p.faellig)}</Pille>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

function NeuerPunkt({ terminId, onAngelegt }: { terminId: string; onAngelegt: () => void }) {
  const id = useId();
  const [f, setF] = useState({ titel: "", quelle: "", faellig: "" });
  const [probleme, setProbleme] = useState<LaborProblem[]>([]);
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const text = (feld: string) => probleme.find((p) => p.feld === feld)?.text;

  const anlegen = async (e: FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setFehler(null);
    const r = checklistePruefen(f);
    setProbleme(r.probleme);
    if (!r.eingabe) return;
    setLaeuft(true);
    try {
      await checklistePunktAnlegen(terminId, r.eingabe);
      setF({ titel: "", quelle: "", faellig: "" });
      onAngelegt();
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuft(false);
    }
  };

  return (
    <form onSubmit={(e) => void anlegen(e)} noValidate style={{ display: "grid", gap: 10 }} aria-label="Punkt zur Checkliste hinzufügen">
      <div className="ws-zeile">
        <div className="ws-feld" style={{ flex: "2 1 220px" }}>
          <label htmlFor={`${id}-titel`}>Neuer Punkt</label>
          <input id={`${id}-titel`} value={f.titel} maxLength={140} onChange={(e) => setF({ ...f, titel: e.target.value })} aria-invalid={text("titel") ? true : undefined} aria-describedby={text("titel") ? `${id}-titel-f` : undefined} />
          {text("titel") && <p id={`${id}-titel-f`} className="ws-feld-fehler">{text("titel")}</p>}
        </div>
        <div className="ws-feld" style={{ flex: "1 1 160px" }}>
          <label htmlFor={`${id}-quelle`}>Quelle (optional)</label>
          <input id={`${id}-quelle`} value={f.quelle} maxLength={100} onChange={(e) => setF({ ...f, quelle: e.target.value })} aria-invalid={text("quelle") ? true : undefined} aria-describedby={text("quelle") ? `${id}-quelle-f` : undefined} />
          {text("quelle") && <p id={`${id}-quelle-f`} className="ws-feld-fehler">{text("quelle")}</p>}
        </div>
        <div className="ws-feld">
          <label htmlFor={`${id}-faellig`}>Fällig (optional)</label>
          <input id={`${id}-faellig`} type="date" value={f.faellig} onChange={(e) => setF({ ...f, faellig: e.target.value })} aria-invalid={text("faellig") ? true : undefined} />
        </div>
        <button type="submit" className="btn-secondary" disabled={laeuft}>Punkt anlegen</button>
      </div>
      {fehler && <FehlerHinweis fehler={fehler} />}
    </form>
  );
}

export function LaborCheckliste({ terminId }: { terminId: string }) {
  const abruf = useAbruf((s) => checklisteLaden(terminId, s), `checkliste-${terminId}`);
  return (
    <Karte titel="Checkliste">
      <Abrufinhalt abruf={abruf} was="Die Checkliste">
        {(p) => <Punkte terminId={terminId} punkte={p} onGeaendert={abruf.neu} />}
      </Abrufinhalt>
      <NeuerPunkt terminId={terminId} onAngelegt={abruf.neu} />
    </Karte>
  );
}
