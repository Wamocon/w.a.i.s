"use client";

import { useId, useState } from "react";
import { fehlerBildAus, plaetzeLaden, zuordnungLaden, zuordnungSpeichern } from "@/lib/werkstattApi";
import { heuteIso, tagText } from "@/lib/werkstattFristen";
import { standardTermin } from "@/lib/werkstattLabor";
import { ZEIT_RICHTWERT_MIN, zeitJePlatz, zuordnungBereinigen, zuordnungGleich, zuordnungUmschalten } from "@/lib/werkstattKarten";
import type { FehlerBild, Karte as KarteTyp, Platz, Termin, Zuordnung } from "@/lib/werkstattTypen";
import { Abrufinhalt, FehlerHinweis, Karte, Pille } from "./Bausteine";
import { useAbruf } from "./useAbruf";

/**
 * Zuordnung der Karten zu den Gästen eines Termins: Matrix mit den Plätzen als Spalten und den Karten als Zeilen. Jedes Kreuz legt
 * fest, welche Karte im Kartensatz dieses Platzes steht. Unter jeder Spalte steht die Zeit, darüber färbt sie sich als Hinweis
 * (Richtwert 25 Minuten). Gespeichert wird die ganze Matrix auf einmal, nicht bei jedem Kreuz.
 */

function Matrix({
  terminId,
  karten,
  plaetze,
  geladen,
  onGespeichert,
}: {
  terminId: string;
  karten: readonly KarteTyp[];
  plaetze: readonly Platz[];
  geladen: Zuordnung;
  onGespeichert: () => void;
}) {
  const id = useId();
  const spalten = plaetze.filter((p) => p.zweck !== "abnahme").sort((a, b) => a.platz - b.platz);
  const [z, setZ] = useState<Zuordnung>(() => zuordnungBereinigen(geladen, karten));
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [meldung, setMeldung] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const geaendert = !zuordnungGleich(z, zuordnungBereinigen(geladen, karten));
  const zeit = zeitJePlatz(z, karten);

  const speichern = async () => {
    if (laeuft) return;
    setLaeuft(true);
    setFehler(null);
    setMeldung("");
    try {
      await zuordnungSpeichern(terminId, z);
      setMeldung("Die Zuordnung ist gespeichert.");
      onGespeichert();
    } catch (x) {
      setFehler(fehlerBildAus(x));
    } finally {
      setLaeuft(false);
    }
  };

  if (spalten.length === 0) return <p className="ws-leer">Für diesen Termin sind noch keine Plätze für Gäste geplant. Lege sie im Labor-Planer an.</p>;
  if (karten.length === 0) return <p className="ws-leer">Es gibt noch keine Karten, die sich zuordnen ließen.</p>;
  const kopf = (p: Platz) => (p.gast ? `${p.gast}, Platz ${p.platz}` : `Platz ${p.platz}`);
  return (
    <>
      <div className="ws-scroll">
        <table className="ws-tabelle">
          <caption id={`${id}-cap`}>Welche Karte steht in welchem Kartensatz</caption>
          <thead>
            <tr>
              <th scope="col">Karte</th>
              {spalten.map((p) => (
                <th key={p.platz} scope="col" className="ws-mitte">
                  {p.gast ?? `Platz ${p.platz}`}
                  {p.gast && <><br /><span className="ws-klein">Platz {p.platz}</span></>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {karten.map((k) => (
              <tr key={k.id}>
                <th scope="row">
                  <span className="ws-mono">{k.id}</span> <span style={{ fontWeight: 400, fontFamily: "var(--body)" }}>{k.titel}</span>
                </th>
                {spalten.map((p) => (
                  <td key={p.platz} className="ws-mitte">
                    <input
                      type="checkbox"
                      aria-label={`${k.id} für ${kopf(p)}`}
                      checked={(z[p.platz] ?? []).includes(k.id)}
                      onChange={(e) => setZ(zuordnungUmschalten(z, p.platz, k.id, e.target.checked))}
                    />
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <th scope="row">Zeit insgesamt</th>
              {spalten.map((p) => (
                <td key={p.platz} className="ws-mitte">
                  <Pille art={(zeit[p.platz] ?? 0) > ZEIT_RICHTWERT_MIN ? "warn" : "ok"}>
                    <span className="ws-mono">{zeit[p.platz] ?? 0} Min.</span>
                    {(zeit[p.platz] ?? 0) > ZEIT_RICHTWERT_MIN ? ", lang" : ""}
                  </Pille>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {fehler && <FehlerHinweis fehler={fehler} />}
      <div className="ws-aktionen">
        <button type="button" className="btn-primary" disabled={!geaendert || laeuft} onClick={() => void speichern()}>Zuordnung speichern</button>
        <button type="button" className="btn-secondary" disabled={!geaendert || laeuft} onClick={() => setZ(zuordnungBereinigen(geladen, karten))}>Änderungen verwerfen</button>
      </div>
      <p className="ws-klein" role="status">{meldung || (geaendert ? "Es gibt ungespeicherte Änderungen." : "")}</p>
    </>
  );
}

export function KartenZuordnung({ karten, termine }: { karten: readonly KarteTyp[]; termine: readonly Termin[] }) {
  const id = useId();
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);
  const [heute] = useState(() => heuteIso(new Date()));
  const vorgabe = standardTermin(termine, heute)?.id ?? null;
  const terminId = gewaehlt !== null && termine.some((t) => t.id === gewaehlt) ? gewaehlt : vorgabe;
  const abruf = useAbruf(
    (s) => Promise.all([plaetzeLaden(terminId ?? "", s), zuordnungLaden(terminId ?? "", s)]),
    `zuordnung-${terminId ?? "keiner"}`,
    terminId !== null,
  );
  return (
    <Karte titel="Zuordnung zu den Gästen">
      <p className="ws-klein">Jeder Gast bearbeitet die Karten an seinem Platz. Das Kreuz legt fest, welche Karte im Kartensatz des Gastes steht.</p>
      {terminId === null ? (
        <p className="ws-leer">Lege im Labor-Planer zuerst einen Termin an. Die Zuordnung gehört zu einem Termin.</p>
      ) : (
        <>
          <div className="ws-feld">
            <label htmlFor={`${id}-termin`}>Termin</label>
            <select id={`${id}-termin`} value={terminId} onChange={(e) => setGewaehlt(e.target.value)}>
              {termine.map((t) => (
                <option key={t.id} value={t.id}>{tagText(t.tag)}</option>
              ))}
            </select>
          </div>
          <Abrufinhalt abruf={abruf} was="Die Zuordnung">
            {([plaetze, geladen]) => (
              <Matrix key={terminId} terminId={terminId} karten={karten} plaetze={plaetze} geladen={geladen} onGespeichert={abruf.neu} />
            )}
          </Abrufinhalt>
        </>
      )}
    </Karte>
  );
}
