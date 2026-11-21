"use client";

import { useState } from "react";
import { fehlerBildAus, karteLoeschen, kartenLaden, termineLaden, versionenLaden } from "@/lib/werkstattApi";
import { formularAusKarte, gruppenAus, leeresFormular, type Formular } from "@/lib/werkstattKarten";
import type { FehlerBild, Karte as KarteTyp } from "@/lib/werkstattTypen";
import { Abrufinhalt, FehlerHinweis, Karte, Pille } from "./Bausteine";
import { KartenEditor } from "./KartenEditor";
import { KartenKatalog } from "./KartenKatalog";
import { KartenZuordnung } from "./KartenZuordnung";
import { useAbruf } from "./useAbruf";
import { Veroeffentlichen } from "./Veroeffentlichen";

/**
 * Bereich "Karten und Use Cases": die Aufgaben, die ein Gast im Labormodus bearbeitet. Bestehende Karten ändern oder einen Use Case
 * von null aufbauen, den Gästen zuordnen und dann veröffentlichen. Veröffentlichte Karten lädt der Kern im Betrieb nach.
 */

type Editor = { formular: Formular; nr: number };

export function Karten({ onFaktor }: { onFaktor: () => void }) {
  const katalog = useAbruf((s) => kartenLaden(s), "karten");
  const versionen = useAbruf((s) => versionenLaden(s), "versionen");
  const termine = useAbruf((s) => termineLaden(s), "termine-karten");
  const [filter, setFilter] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [meldung, setMeldung] = useState("");
  const [loeschFehler, setLoeschFehler] = useState<FehlerBild | null>(null);
  const [loescht, setLoescht] = useState<string | null>(null);

  const liste = katalog.daten;
  const karten: readonly KarteTyp[] = liste?.karten ?? [];
  const aktiveVersion = liste?.version ?? versionen.daten?.find((v) => v.aktiv)?.version ?? null;
  const oeffne = (formular: Formular) => {
    setMeldung("");
    setEditor((alt) => ({ formular, nr: (alt?.nr ?? 0) + 1 }));
  };

  const loeschen = async (k: KarteTyp) => {
    setLoescht(k.id);
    setLoeschFehler(null);
    setMeldung("");
    try {
      await karteLoeschen(k.id);
      setMeldung(`Der Entwurf ${k.id} ist gelöscht.`);
      if (editor?.formular.id === k.id) setEditor(null);
      katalog.neu();
    } catch (x) {
      setLoeschFehler(fehlerBildAus(x));
    } finally {
      setLoescht(null);
    }
  };

  return (
    <div className="ws-bereich">
      <div className="ws-kopf">
        <p className="ws-kurz">
          Die Aufgaben, die ein Gast im Labormodus bearbeitet. Bestehende Karten ändern oder einen Use Case komplett neu aufbauen, dann den Gästen zuordnen. Veröffentlichte Karten lädt der Kern im Betrieb nach.
        </p>
        <Pille art="akzent">{aktiveVersion === null ? "Noch keine veröffentlichte Version" : `Katalog Version ${aktiveVersion}`}</Pille>
      </div>

      <Karte
        titel="Katalog"
        rechts={
          <button type="button" className="btn-primary btn-small" disabled={!liste} onClick={() => oeffne(leeresFormular(karten, liste?.gruppen ?? {}, filter))}>
            Neuen Use Case aufbauen
          </button>
        }
      >
        <Abrufinhalt abruf={katalog} was="Der Katalog">
          {(l) => (
            <KartenKatalog
              karten={l.karten}
              gruppen={gruppenAus(l.gruppen, l.karten)}
              filter={filter}
              onFilter={setFilter}
              onBearbeiten={(k) => oeffne(formularAusKarte(k, l.karten))}
              onKopieren={(k) => oeffne(formularAusKarte(k, l.karten, true))}
              onLoeschen={(k) => void loeschen(k)}
              beschaeftigt={loescht}
            />
          )}
        </Abrufinhalt>
        {loeschFehler && <FehlerHinweis fehler={loeschFehler} />}
        <p className="ws-erfolg" role="status">{meldung}</p>
      </Karte>

      {editor && liste && (
        <KartenEditor
          key={editor.nr}
          start={editor.formular}
          karten={liste.karten}
          gruppen={liste.gruppen}
          onSchliessen={() => setEditor(null)}
          onGespeichert={(id) => {
            setEditor(null);
            setMeldung(`Der Use Case ${id} ist als Entwurf gespeichert. Er wird erst mit dem Veröffentlichen für den Kern gültig.`);
            katalog.neu();
          }}
        />
      )}

      {liste && termine.daten && <KartenZuordnung karten={liste.karten} termine={termine.daten} />}
      {liste && termine.fehler && (
        <Karte titel="Zuordnung zu den Gästen">
          <FehlerHinweis fehler={termine.fehler} onNeu={termine.neu} />
        </Karte>
      )}

      {liste && (
        <Veroeffentlichen
          karten={liste.karten}
          aktiveVersion={aktiveVersion}
          onFaktor={onFaktor}
          onVeroeffentlicht={() => {
            katalog.neu();
            versionen.neu();
          }}
        />
      )}
    </div>
  );
}
