"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import type { CanvasItem } from "@/components/Canvas";
import { eigenesElement, empfaengerListe } from "@/lib/mail";
import { useSelect } from "@/lib/store";
import { klartext, TEAMS_TEXT_MAX, teamsFehler, type TeamsAktionen } from "@/lib/teams";
import { wamo } from "@/lib/wamo";

/** Nach so vielen Sekunden ohne Antwort des Kerns gibt der Knopf wieder frei (Adressbuch am PC, Tunnel). */
const ANTWORT_FRIST_MS = 90_000;

/**
 * "Als Teams-Nachricht" im Kopf eines eigenen, gespeicherten Canvas-Elements (nur mit betrieb.teams, voice-core/teams_werkzeuge.py):
 * Felder für An, Gruppenname (nur bei mehreren) und Text (Vorschlag: der Inhalt des Canvas als Klartext, mit Zeichenzahl). "Zur
 * Freigabe vorbereiten" schickt nur die Angaben; Kern und Host legen daraus die Karte an. Erst der Klick dort öffnet Teams mit dem Text
 * im Eingabefeld, senden muss die Person selbst. Bis die Antwort kommt, ist der Knopf gesperrt; bei Erfolg schließt das Formular.
 */
export function CanvasTeams({ item, teams }: { item: CanvasItem; teams: TeamsAktionen }) {
  const verfuegbar = useSelect(wamo, (s) => s.betrieb?.teams === true);
  const antwort = useSelect(wamo, (s) => s.teamsAntwort);
  const id = useId();
  const [offen, setOffen] = useState(false);
  const [an, setAn] = useState("");
  const [gruppe, setGruppe] = useState("");
  const [text, setText] = useState(() => klartext(item));
  const [fehler, setFehler] = useState<string | null>(null);
  const [wartet, setWartet] = useState<number | null>(null);

  if (wartet !== null && antwort.n !== wartet) {
    // Antwort da: bei Erfolg liegt die Karte bereit (Formular zu), sonst bleibt es mit dem Grund offen
    setWartet(null);
    if (antwort.ok) {
      setOffen(false);
      setAn("");
      setGruppe("");
      setFehler(null);
    } else {
      setFehler(antwort.grund ?? "Die Teams-Nachricht ließ sich nicht vorbereiten.");
    }
  }
  useEffect(() => {
    if (wartet === null) return;
    const uhr = setTimeout(() => setWartet(null), ANTWORT_FRIST_MS);
    return () => clearTimeout(uhr);
  }, [wartet]);

  if (!verfuegbar || !eigenesElement(item)) return null;

  const absenden = (e: FormEvent) => {
    e.preventDefault();
    if (wartet !== null) return;
    const daten = { an: empfaengerListe(an), gruppenname: gruppe.trim(), text };
    const fehlt = teamsFehler(daten);
    if (fehlt) {
      setFehler(fehlt);
      return;
    }
    setFehler(null);
    if (teams.vorbereiten(daten)) setWartet(antwort.n);
  };

  return (
    <div className="canvas-mail canvas-teams">
      <button
        type="button"
        className="btn-secondary btn-small"
        aria-expanded={offen}
        aria-controls={`${id}-form`}
        onClick={() => setOffen((o) => !o)}
      >
        Als Teams-Nachricht
      </button>
      {offen && (
        <form id={`${id}-form`} className="canvas-mail-form" onSubmit={absenden} noValidate>
          <label htmlFor={`${id}-an`}>An</label>
          <input id={`${id}-an`} type="text" value={an} onChange={(e) => setAn(e.target.value)} placeholder="Adressen, mit Komma getrennt" />
          <label htmlFor={`${id}-gruppe`}>Gruppenname (nur bei mehreren)</label>
          <input id={`${id}-gruppe`} type="text" value={gruppe} onChange={(e) => setGruppe(e.target.value)} />
          <label htmlFor={`${id}-text`}>Text</label>
          <textarea id={`${id}-text`} rows={6} value={text} onChange={(e) => setText(e.target.value)} aria-describedby={`${id}-zahl`} />
          <p id={`${id}-zahl`} className="canvas-mail-hinweis">{`${text.length} von ${TEAMS_TEXT_MAX} Zeichen`}</p>
          <p className="canvas-mail-hinweis">
            W.A.I.S. sendet nie: Nach deiner Freigabe öffnet sich Teams mit diesem Text im Eingabefeld, und du drückst dort selbst Enter.
            Namen gehen nur mit dem klassischen Outlook, sonst bitte Adressen. Sagen geht auch: „Schreib Anna in Teams, dass …“
          </p>
          {fehler && (
            <p className="notice" role="alert">
              {fehler}
            </p>
          )}
          <div className="canvas-mail-knoepfe">
            <button type="submit" className="btn-secondary btn-small" disabled={wartet !== null} aria-busy={wartet !== null || undefined}>
              Zur Freigabe vorbereiten
            </button>
            <button type="button" className="btn-secondary btn-small" onClick={() => setOffen(false)}>
              Abbrechen
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
