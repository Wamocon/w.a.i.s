"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { ENTWURF_AUFBEWAHRUNG_TAGE, entwurfDatum, entwurfIso } from "@/lib/auftragEntwuerfe";
import type { AuftragEntwurf } from "@/lib/nachrichten";
import { useSelect } from "@/lib/store";
import type { EntwurfAktionen } from "@/lib/useWamo";
import { istOnline, wamo } from "@/lib/wamo";

/**
 * Gespeicherte Aufträge im Reiter "Aufträge" (voice-core/auftrag_entwuerfe.py): Titel (Anfang des Auftrags), Projekt, Art, Repo und Datum,
 * je mit "Laden" und "Löschen". Laden legt die Karte in der laufenden Sitzung wieder an; gestartet wird sie dort wie jede andere nur per
 * Klick, mit allen Prüfungen des Kerns. Löschen fragt einmal nach: Der Fokus geht auf "Abbrechen" (nie auf den bestätigenden Knopf, ein
 * zweites Enter löscht so nichts), nach dem Abbrechen zurück auf "Löschen", nach dem Löschen auf die Überschrift der Liste. Die Liste gibt
 * es erst, wenn der Kern sie geschickt hat (sonst fehlt sie ganz, etwa im Labor oder ohne Entwicklungsaufträge). Ohne Verbindung und
 * solange eine Aktion auf Antwort wartet, sind die Knöpfe gesperrt. Die letzte Meldung steht sichtbar da; angesagt wird sie über die
 * Ansage der Seite (wamo.ansage), nicht doppelt. Alle Texte sind geprüft und einzeilig (lib/nachrichten.ts) und stehen als Text.
 */
export const GespeicherteAuftraege = memo(function GespeicherteAuftraege({ aktionen }: { aktionen?: EntwurfAktionen }) {
  const stand = useSelect(wamo, (s) => s.entwuerfe);
  const online = useSelect(wamo, istOnline);
  const [nachfrage, setNachfrage] = useState<string | null>(null);
  const kopf = useRef<HTMLHeadingElement>(null);
  const kopfId = useId();
  if (!aktionen || !stand) return null;
  const gesperrt = !online || stand.wartet !== null;

  return (
    <section className="entwuerfe" aria-labelledby={kopfId}>
      <h3 id={kopfId} ref={kopf} className="entwuerfe-titel" tabIndex={-1}>
        Gespeicherte Aufträge
      </h3>
      {stand.meldung && <p className="notice">{stand.meldung.text}</p>}
      {stand.liste.length === 0 ? (
        <p className="entwuerfe-leer">Noch nichts gespeichert. „Für später speichern“ auf einer Auftragskarte legt den Auftrag hier ab.</p>
      ) : (
        <ul className="entwuerfe-liste">
          {stand.liste.map((e) => (
            <Eintrag
              key={e.id}
              e={e}
              gesperrt={gesperrt}
              fragt={nachfrage === e.id}
              onLaden={() => aktionen.laden(e.id)}
              onLoeschen={() => setNachfrage(e.id)}
              onBestaetigen={() => {
                if (!aktionen.loeschen(e.id)) return;
                setNachfrage(null);
                requestAnimationFrame(() => kopf.current?.focus());
              }}
              onAbbrechen={() => setNachfrage(null)}
            />
          ))}
        </ul>
      )}
      <p className="entwuerfe-hinweis">
        {stand.liste.length} von {stand.max} gespeichert. Gespeicherte Aufträge bleiben {ENTWURF_AUFBEWAHRUNG_TAGE} Tage.
      </p>
    </section>
  );
});

function Eintrag({
  e,
  gesperrt,
  fragt,
  onLaden,
  onLoeschen,
  onBestaetigen,
  onAbbrechen,
}: {
  e: AuftragEntwurf;
  gesperrt: boolean;
  fragt: boolean;
  onLaden: () => void;
  onLoeschen: () => void;
  onBestaetigen: () => void;
  onAbbrechen: () => void;
}) {
  const abbrechen = useRef<HTMLButtonElement>(null);
  const loeschen = useRef<HTMLButtonElement>(null);
  const zurueck = useRef(false); // nach "Abbrechen" geht der Fokus zurück auf "Löschen"
  const datum = entwurfDatum(e.gespeichertMs);
  const angaben = [e.projekt, e.art, e.repo].filter(Boolean).join(" · ");

  useEffect(() => {
    if (fragt) {
      abbrechen.current?.focus();
    } else if (zurueck.current) {
      zurueck.current = false;
      loeschen.current?.focus();
    }
  }, [fragt]);

  return (
    <li className="entwurf">
      <p className="entwurf-titel">{e.titel}</p>
      <p className="entwurf-meta">
        {angaben}
        {datum && (
          <>
            {angaben && " · "}
            gespeichert am <time dateTime={entwurfIso(e.gespeichertMs)}>{datum}</time>
          </>
        )}
      </p>
      {fragt ? (
        <div className="approval-actions" role="group" aria-label={`Löschen bestätigen: ${e.titel}`}>
          <span className="entwurf-frage">Wirklich löschen?</span>
          <button
            key="bestaetigen"
            type="button"
            className="btn-decide"
            disabled={gesperrt}
            onClick={onBestaetigen}
            aria-label={`Endgültig löschen: ${e.titel}`}
          >
            Endgültig löschen
          </button>
          <button
            key="abbrechen"
            ref={abbrechen}
            type="button"
            className="btn-decide"
            onClick={() => {
              zurueck.current = true;
              onAbbrechen();
            }}
            aria-label={`Abbrechen: ${e.titel}`}
          >
            Abbrechen
          </button>
        </div>
      ) : (
        <div className="approval-actions">
          <button key="laden" type="button" className="btn-decide" disabled={gesperrt} onClick={onLaden} aria-label={`Laden: ${e.titel}`}>
            Laden
          </button>
          <button
            key="loeschen"
            ref={loeschen}
            type="button"
            className="btn-decide"
            disabled={gesperrt}
            onClick={onLoeschen}
            aria-label={`Löschen: ${e.titel}`}
          >
            Löschen
          </button>
        </div>
      )}
    </li>
  );
}
