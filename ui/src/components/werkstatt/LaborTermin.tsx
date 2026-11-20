"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { fehlerBildAus, terminAendern, terminAnlegen, terminLoeschen } from "@/lib/werkstattApi";
import { fristen, tagText } from "@/lib/werkstattFristen";
import {
  LABORTERMIN_STATUS_TEXT,
  leererTermin,
  mitAufbewahrung,
  mitTag,
  terminFormular,
  terminPruefen,
  type LaborProblem,
} from "@/lib/werkstattLabor";
import { TERMIN_STATUS, type FehlerBild, type Termin, type TerminStatus } from "@/lib/werkstattTypen";
import { FehlerHinweis, Karte } from "./Bausteine";

/**
 * Karte "Termin und Fristen": ein Labortag wird einmal geplant. Der Labortag bestimmt die Fristen; die Aufbewahrung folgt ihm
 * (Tag plus 13), bis jemand sie von Hand wählt. Die Fristen des Löschlaufs und des Nachlaufs werden nur berechnet und angezeigt.
 */

export const NEUER_TERMIN = "neu";

type Props = {
  termine: readonly Termin[];
  /** Kennung des gewählten Termins oder NEUER_TERMIN */
  auswahl: string;
  onWaehlen: (auswahl: string) => void;
  /** nach dem Speichern oder Löschen: die Liste neu laden, id = der gespeicherte Termin */
  onGeaendert: (id: string | null) => void;
};

export function LaborTermin({ termine, auswahl, onWaehlen, onGeaendert }: Props) {
  const id = useId();
  const termin = termine.find((t) => t.id === auswahl) ?? null;
  return (
    <Karte titel="Termin und Fristen">
      <div className="ws-feld">
        <label htmlFor={`${id}-wahl`}>Termin</label>
        <select id={`${id}-wahl`} value={termin ? termin.id : NEUER_TERMIN} onChange={(e) => onWaehlen(e.target.value)}>
          {termine.map((t) => (
            <option key={t.id} value={t.id}>
              {tagText(t.tag)}, {LABORTERMIN_STATUS_TEXT[t.status]}
            </option>
          ))}
          <option value={NEUER_TERMIN}>Neuer Termin</option>
        </select>
      </div>
      <TerminFormularKarte key={termin?.id ?? NEUER_TERMIN} termin={termin} onGeaendert={onGeaendert} />
    </Karte>
  );
}

function FristenListe({ tag, bis }: { tag: string; bis: string }) {
  const f = fristen(tag, bis);
  if (!f) return <p className="ws-klein">Mit einem Labortag zeigt die Werkstatt die Fristen.</p>;
  return (
    <dl className="ws-liste">
      <div><dt>Aufbewahrung bis</dt><dd className="ws-mono">{tagText(f.aufbewahrungBis)}</dd></div>
      <div><dt>Löschlauf des Dienstes ab</dt><dd className="ws-mono">{tagText(f.loeschlaufAb)}</dd></div>
      <div><dt>Nachlauf, Laborkonten löschen ab</dt><dd className="ws-mono">{tagText(f.nachlaufAb)}</dd></div>
    </dl>
  );
}

function TerminFormularKarte({ termin, onGeaendert }: { termin: Termin | null; onGeaendert: Props["onGeaendert"] }) {
  const id = useId();
  const [f, setF] = useState(() => (termin ? terminFormular(termin) : leererTermin()));
  const [probleme, setProbleme] = useState<LaborProblem[]>([]);
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [meldung, setMeldung] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [frage, setFrage] = useState(false);
  const problemRef = useRef<HTMLDivElement>(null);
  const problemText = (feld: string) => probleme.find((p) => p.feld === feld)?.text;
  const bei = (feld: string) => ({ "aria-invalid": problemText(feld) ? (true as const) : undefined, "aria-describedby": problemText(feld) ? `${id}-${feld}-f` : undefined });
  const fehlerzeile = (feld: string) => (problemText(feld) ? <p id={`${id}-${feld}-f`} className="ws-feld-fehler">{problemText(feld)}</p> : null);

  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setMeldung("");
    setFehler(null);
    const r = terminPruefen(f);
    setProbleme(r.probleme);
    if (!r.eingabe) {
      requestAnimationFrame(() => problemRef.current?.focus());
      return;
    }
    setLaeuft(true);
    try {
      const ergebnis = termin ? await terminAendern(termin.id, r.eingabe) : await terminAnlegen(r.eingabe);
      setMeldung(termin ? "Der Termin ist gespeichert." : "Der Termin ist angelegt.");
      onGeaendert(ergebnis.termin?.id ?? termin?.id ?? null);
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuft(false);
    }
  };

  const loeschen = async () => {
    if (!termin || laeuft) return;
    setLaeuft(true);
    setFehler(null);
    try {
      await terminLoeschen(termin.id);
      onGeaendert(null);
    } catch (x) {
      setFehler(fehlerBildAus(x));
      setFrage(false);
    } finally {
      setLaeuft(false);
    }
  };

  return (
    <form className="ws-karte-innen" onSubmit={(e) => void speichern(e)} noValidate style={{ display: "grid", gap: 12 }}>
      <div className="ws-zeile">
        <div className="ws-feld">
          <label htmlFor={`${id}-tag`}>Labortag</label>
          <input id={`${id}-tag`} type="date" value={f.tag} onChange={(e) => setF(mitTag(f, e.target.value))} {...bei("tag")} />
          {fehlerzeile("tag")}
        </div>
        <div className="ws-feld">
          <label htmlFor={`${id}-beginn`}>Beginn</label>
          <input id={`${id}-beginn`} type="time" value={f.beginn} onChange={(e) => setF({ ...f, beginn: e.target.value })} {...bei("beginn")} />
          {fehlerzeile("beginn")}
        </div>
        <div className="ws-feld">
          <label htmlFor={`${id}-ende`}>Ende</label>
          <input id={`${id}-ende`} type="time" value={f.ende} onChange={(e) => setF({ ...f, ende: e.target.value })} {...bei("ende")} />
          {fehlerzeile("ende")}
        </div>
      </div>
      <div className="ws-zeile">
        <div className="ws-feld">
          <label htmlFor={`${id}-version`}>Version der Einwilligung</label>
          <input id={`${id}-version`} type="number" min={1} max={99} inputMode="numeric" value={f.version} onChange={(e) => setF({ ...f, version: e.target.value })} {...bei("version")} />
          {fehlerzeile("version")}
        </div>
        <div className="ws-feld">
          <label htmlFor={`${id}-status`}>Stand des Termins</label>
          <select id={`${id}-status`} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as TerminStatus })} {...bei("status")}>
            {TERMIN_STATUS.map((s) => (
              <option key={s} value={s}>{LABORTERMIN_STATUS_TEXT[s]}</option>
            ))}
          </select>
        </div>
        <div className="ws-feld">
          <label htmlFor={`${id}-bis`}>Aufbewahrung bis</label>
          <input id={`${id}-bis`} type="date" value={f.aufbewahrungBis} onChange={(e) => setF(mitAufbewahrung(f, e.target.value))} {...bei("aufbewahrungBis")} />
          {fehlerzeile("aufbewahrungBis")}
        </div>
      </div>
      <FristenListe tag={f.tag} bis={f.aufbewahrungBis} />
      <p className="ws-klein">Eine Verschiebung ändert nur den Labortag. Die Aufbewahrung folgt mit (Tag plus 13), die übrigen Fristen werden daraus berechnet.</p>
      {probleme.length > 0 && (
        <div ref={problemRef} className="ws-fehler" role="alert" tabIndex={-1}>
          <span>Bitte prüfe den Termin: {probleme.map((p) => p.text).join(" ")}</span>
        </div>
      )}
      {fehler && <FehlerHinweis fehler={fehler} />}
      <div className="ws-aktionen">
        <button type="submit" className="btn-primary" disabled={laeuft}>
          {termin ? "Termin speichern" : "Termin anlegen"}
        </button>
        {termin && termin.status === "entwurf" && !frage && (
          <button type="button" className="btn-secondary" disabled={laeuft} onClick={() => setFrage(true)}>
            Termin löschen …
          </button>
        )}
      </div>
      {frage && (
        <div className="ws-hinweis" role="group" aria-label="Termin löschen">
          <p style={{ margin: "0 0 8px" }}>Wirklich löschen? Plätze, Checkliste und Zuordnung dieses Termins gehen mit.</p>
          <div className="ws-aktionen">
            <button type="button" className="btn-primary" disabled={laeuft} onClick={() => void loeschen()}>Ja, löschen</button>
            <button type="button" className="btn-secondary" disabled={laeuft} onClick={() => setFrage(false)}>Abbrechen</button>
          </div>
        </div>
      )}
      <p className="ws-erfolg" role="status">{meldung}</p>
    </form>
  );
}
