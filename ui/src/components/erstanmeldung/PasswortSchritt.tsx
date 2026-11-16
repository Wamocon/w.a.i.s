"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import type { SchrittProps } from "@/components/erstanmeldung/typen";
import {
  MIN_ZEICHEN,
  SATZ_ABGELAUFEN,
  passwortFehler,
  passwortPruefen,
  type ErstanmeldungStand,
  type PasswortErgebnis,
} from "@/lib/erstanmeldung";

/**
 * Schritt Passwort der Erstanmeldung: Die Person ersetzt das Startpasswort durch ein eigenes (Planpapier 4.1, Zweig A). Der Wechsel
 * geht über die Route des Kerns (POST /wamo/api/erstanmeldung/passwort), denn Caddy lässt PUT auf die Anmeldeschnittstelle nicht
 * durch; der Kern ruft GoTrue auf. updateUser wird nie benutzt. Danach beendet die Oberfläche alle anderen Sitzungen. Meldet der Kern
 * "erledigt", geht der Ablauf weiter, sonst fragt der Schritt den Stand neu ab. Das Passwort steht nur in den zwei Feldern (ohne
 * Zustand von React, gelesen beim Absenden) und in der Anfrage: nie in einem Log, nie in einem Speicher, nie in einer Meldung, und
 * nach dem Erfolg ist das Formular zurückgesetzt. Die Überschrift gehört dem Ablauf (er setzt den Fokus darauf).
 */
const ANDERE_SITZUNGEN =
  "Andere angemeldete Geräte konnten nicht abgemeldet werden. Melde dich dort selbst ab, wenn du sie nicht mehr brauchst.";

export function PasswortSchritt({ kontext, weiter }: SchrittProps) {
  const hinweisId = useId();
  const fehlerId = useId();
  const [fehler, setFehler] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Schutz gegen doppeltes Absenden, auch bevor React neu gezeichnet hat */
  const laeuft = useRef(false);
  /** Das Passwort ist geändert: ab hier gibt es keine Felder mehr (ein zweiter Versuch mit demselben Passwort scheitert an same_password) */
  const [geaendert, setGeaendert] = useState(false);
  const [stand, setStand] = useState<ErstanmeldungStand | null>(null);
  const [andereFehler, setAndereFehler] = useState(false);

  /** Stand klären (bekannt aus der Antwort des Kerns, sonst beim Kern holen) und entscheiden: weiter, Tor neu prüfen (abgelaufen) oder warten. */
  const standPruefen = async (andere: boolean, bekannt?: ErstanmeldungStand) => {
    let gelesen: ErstanmeldungStand = "keine";
    if (bekannt === "erledigt") {
      gelesen = bekannt;
    } else {
      try {
        gelesen = await kontext.stand();
      } catch {
        // unklar: "keine", die Person kann erneut prüfen
      }
    }
    setStand(gelesen);
    if (gelesen === "abgelaufen") kontext.neuPruefen();
    else if (gelesen === "erledigt" && !andere) weiter();
  };

  const absenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (laeuft.current) return;
    const formular = e.currentTarget; // nach dem ersten await ist currentTarget leer
    const daten = new FormData(formular);
    const problem = passwortPruefen(String(daten.get("neu") ?? ""), String(daten.get("wiederholung") ?? ""));
    if (problem) {
      setFehler(problem);
      return;
    }
    laeuft.current = true;
    setBusy(true);
    setFehler(null);
    try {
      let ergebnis: PasswortErgebnis;
      try {
        ergebnis = await kontext.passwortSetzen(String(daten.get("neu")));
      } catch {
        ergebnis = { ok: false, status: 500, code: null }; // passwortSetzen wirft nie; falls doch: allgemeiner Satz
      }
      if (!ergebnis.ok) {
        const f = passwortFehler(ergebnis);
        if (f.folge === "code") {
          kontext.neuPruefen({ code: true, hinweis: f.text });
        } else {
          setFehler(f.text);
          if (f.folge === "pruefen" || f.folge === "abgelaufen") kontext.neuPruefen();
        }
        return;
      }
      // Geändert: Formular zurücksetzen, andere Sitzungen beenden (Fehler nur anzeigen), Stand klären
      formular.reset();
      setGeaendert(true);
      let andere = false;
      try {
        const { error } = await kontext.supabase.auth.signOut({ scope: "others" });
        andere = Boolean(error);
      } catch {
        andere = true;
      }
      setAndereFehler(andere);
      await standPruefen(andere, ergebnis.stand);
    } finally {
      laeuft.current = false;
      setBusy(false);
    }
  };

  const erneutPruefen = () => {
    if (laeuft.current) return;
    laeuft.current = true;
    setBusy(true);
    void standPruefen(andereFehler).finally(() => {
      laeuft.current = false;
      setBusy(false);
    });
  };

  const beschreibung = fehler ? `${hinweisId} ${fehlerId}` : hinweisId;
  const bestaetigt = stand === "erledigt";
  const unbestaetigt = geaendert && stand !== null && stand !== "erledigt" && stand !== "abgelaufen";

  return (
    <div className="ea-passwort">
      {!geaendert && (
        <form className="gate-form" onSubmit={(e) => void absenden(e)}>
          <p className="gate-hint">Dein Startpasswort gilt nur für den ersten Zugang. Wähle jetzt dein eigenes Passwort.</p>
          {/* Nur für Passwortmanager: zu welchem Konto das neue Passwort gehört. Nicht fokussierbar, für Hilfstechnik verborgen. */}
          <input
            type="text"
            name="username"
            autoComplete="username"
            defaultValue={kontext.email ?? ""}
            readOnly
            tabIndex={-1}
            aria-hidden="true"
            className="sr-only"
          />
          <label>
            Neues Passwort
            <input
              name="neu"
              type="password"
              autoComplete="new-password"
              readOnly={busy}
              required
              spellCheck={false}
              aria-describedby={beschreibung}
              aria-invalid={fehler ? true : undefined}
            />
          </label>
          <label>
            Neues Passwort wiederholen
            <input
              name="wiederholung"
              type="password"
              autoComplete="new-password"
              readOnly={busy}
              required
              spellCheck={false}
              aria-describedby={beschreibung}
              aria-invalid={fehler ? true : undefined}
            />
          </label>
          <p className="gate-hint gate-hint-klein" id={hinweisId}>
            Mindestens {MIN_ZEICHEN} Zeichen. Nimm ein Passwort, das du nirgends sonst benutzt.
          </p>
          {fehler && (
            <p className="notice" role="alert" id={fehlerId}>
              {fehler}
            </p>
          )}
          {/* aria-disabled statt disabled: der Fokus bleibt auf dem Knopf, ein Klick während der Anfrage wird ignoriert */}
          <button className="btn-primary btn-block" aria-disabled={busy || undefined}>
            {busy ? "Ändere …" : "Passwort ändern"}
          </button>
        </form>
      )}
      {/* Live-Region: von Anfang an im DOM, damit Hilfstechnik spätere Statussätze zuverlässig vorliest */}
      <div className="gate-form ea-status" role="status" aria-live="polite">
        {geaendert && stand === null && <p className="gate-hint">Prüfe …</p>}
        {geaendert && andereFehler && <p className="notice">{ANDERE_SITZUNGEN}</p>}
        {stand === "abgelaufen" && <p className="notice">{SATZ_ABGELAUFEN}</p>}
        {geaendert && bestaetigt && <p className="gate-hint">Dein Passwort ist geändert.</p>}
        {unbestaetigt && (
          <p className="gate-hint">
            Dein Passwort ist geändert, aber {kontext.anzeigename} hat es noch nicht bestätigt. Warte einen Moment und prüfe erneut.
          </p>
        )}
      </div>
      {geaendert && bestaetigt && (
        <button type="button" className="btn-primary btn-block" autoFocus onClick={weiter}>
          Weiter
        </button>
      )}
      {unbestaetigt && (
        <button type="button" className="btn-primary btn-block" autoFocus aria-disabled={busy || undefined} onClick={erneutPruefen}>
          Erneut prüfen
        </button>
      )}
    </div>
  );
}
