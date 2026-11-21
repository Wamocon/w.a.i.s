"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { codeBestaetigen } from "@/lib/geraeteVerwaltungApi";
import { faktorIstFrisch, fehlerBildAus, laborZugangEntfernen, laborZugangLaden, laborZugangSetzen } from "@/lib/laborZugang";
import {
  FAKTOR_ALT,
  QUELLE_WORT,
  codeSauber,
  eingabePruefen,
  quelleSatz,
  zeitText,
  type FehlerBild,
  type LaborZugang as Zugang,
} from "@/lib/laborZugangLogik";
import { FehlerHinweis, Karte, Laedt, Pille } from "./Bausteine";

/**
 * Karte "Claude-Zugang des Labors" im Labor-Planer: Der Claude-Schlüssel, über den alle Laborprofile ihr Gespräch führen. Ein Admin setzt,
 * prüft und entfernt ihn hier, statt ihn in /etc/wamo/core.env zu ändern. Die Karte spricht mit dem KERN (lib/laborZugang.ts), nicht mit dem
 * Werkstatt-Dienst: Der Dienst bleibt ohne Geheimnisse.
 *
 * Der Schlüssel lebt nur im Eingabefeld selbst: Das Feld ist nicht gesteuert (kein Zustand, keine Adresse, kein Speicher des Browsers, kein
 * Protokoll). Beim Senden liest die Funktion den Wert, leert das Feld sofort und hält ihn nur bis zur Antwort in einer lokalen Variablen. Nur
 * wenn der Kern meldet, dass der zweite Faktor zu alt war (er hat dann nichts verarbeitet), steht der Wert wieder im Feld, damit der Versuch
 * mit frischem Code nicht von vorn beginnt. Die Antwort des Kerns enthält den Schlüssel nie, nur "endet auf".
 *
 * Ändern darf der Kern nur mit einem frischen Code der Authenticator-App (höchstens 60 Sekunden alt): Ist der Faktor im Token nicht mehr
 * frisch, erscheint das Feld für den Code; er geht nur an Supabase (codeBestaetigen) und wird nach dem Absenden geleert.
 */

type Laden = { art: "laedt" } | { art: "fehler"; fehler: FehlerBild } | { art: "ok"; zugang: Zugang };
type Meldung = { art: "ok" | "fehler"; text: string } | null;

const SATZ_CODE_NOETIG = "Für diese Änderung braucht der Kern einen frischen Code. Bitte gib ihn ein und sende noch einmal.";
const SATZ_CODE_FORM = "Bitte gib die sechs Ziffern aus der Authenticator-App ein.";

function Angaben({ zugang }: { zugang: Zugang }) {
  const gesetzt = zeitText(zugang.gesetztAm);
  const geprueft = zeitText(zugang.geprueftAm);
  return (
    <dl className="ws-liste">
      <div>
        <dt>Es gilt</dt>
        <dd>
          <Pille art={zugang.quelle === "gespeichert" ? "ok" : zugang.quelle === "server" ? "neutral" : "warn"}>{QUELLE_WORT[zugang.quelle]}</Pille>
        </dd>
      </div>
      {zugang.endetAuf && (
        <div>
          <dt>Schlüssel endet auf</dt>
          <dd className="ws-mono">…{zugang.endetAuf}</dd>
        </div>
      )}
      {zugang.workspace && (
        <div>
          <dt>Workspace</dt>
          <dd className="ws-mono">{zugang.workspace}</dd>
        </div>
      )}
      {zugang.quelle === "gespeichert" && gesetzt && (
        <div>
          <dt>Gesetzt am</dt>
          <dd>{gesetzt}</dd>
        </div>
      )}
      {zugang.quelle === "gespeichert" && geprueft && (
        <div>
          <dt>Bei Anthropic geprüft am</dt>
          <dd>{geprueft}</dd>
        </div>
      )}
    </dl>
  );
}

export function LaborZugang({ onFaktor }: { onFaktor?: () => void }) {
  const id = useId();
  const [laden, setLaden] = useState<Laden>({ art: "laedt" });
  const [workspace, setWorkspace] = useState("");
  const [code, setCode] = useState("");
  const [codeNoetig, setCodeNoetig] = useState(false);
  const [frage, setFrage] = useState(false);
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<Meldung>(null);
  const [feldFehler, setFeldFehler] = useState(false);
  const [lauf, setLauf] = useState(0);
  // Das Feld für den Schlüssel ist nicht gesteuert: sein Wert steht nur im Element selbst, nie in einem Zustand.
  const schluesselRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const abbrechenRef = useRef<HTMLButtonElement>(null);
  const entfernenRef = useRef<HTMLButtonElement>(null);
  // Hat der Kern den Faktor als zu alt abgelehnt, obwohl das Token frisch aussah (Uhren), gilt die Prüfung der Oberfläche nicht mehr
  const codeErzwingen = useRef(false);

  useEffect(() => {
    let aktiv = true;
    laborZugangLaden().then(
      (zugang) => {
        if (aktiv) setLaden({ art: "ok", zugang });
      },
      (e: unknown) => {
        // scheitert ein Neuladen, bleibt der letzte Stand stehen
        if (aktiv) setLaden((alt) => (alt.art === "ok" ? alt : { art: "fehler", fehler: fehlerBildAus(e) }));
      },
    );
    return () => {
      aktiv = false;
    };
  }, [lauf]);

  useEffect(() => {
    if (frage) abbrechenRef.current?.focus();
  }, [frage]);

  const neuLaden = useCallback(() => {
    setLaden({ art: "laedt" });
    setLauf((n) => n + 1);
  }, []);

  /** true: weiter mit der Änderung. Sonst steht eine Meldung da und das Feld für den Code ist offen. */
  const faktorSichern = async (): Promise<boolean> => {
    if (!codeErzwingen.current && (await faktorIstFrisch())) return true;
    const sauber = codeSauber(code);
    if (!codeNoetig || !sauber) {
      setCodeNoetig(true);
      setMeldung({ art: "fehler", text: codeNoetig ? SATZ_CODE_FORM : SATZ_CODE_NOETIG });
      requestAnimationFrame(() => codeRef.current?.focus());
      return false;
    }
    setCode(""); // der Code wird nur einmal gebraucht und nicht länger im Zustand gehalten
    const bestaetigt = await codeBestaetigen(sauber);
    if (!bestaetigt.ok) {
      setMeldung({ art: "fehler", text: bestaetigt.text });
      requestAnimationFrame(() => codeRef.current?.focus());
      return false;
    }
    codeErzwingen.current = false;
    onFaktor?.();
    return true;
  };

  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setMeldung(null);
    const feld = schluesselRef.current;
    const pruefung = eingabePruefen(feld?.value ?? "", workspace);
    if (!pruefung.ok) {
      setFeldFehler(true);
      setMeldung({ art: "fehler", text: pruefung.text });
      feld?.focus();
      return;
    }
    setFeldFehler(false);
    setLaeuft(true);
    try {
      if (!(await faktorSichern())) return;
      const { schluessel, workspace: ws } = pruefung.eingabe;
      if (feld) feld.value = ""; // ab hier lebt der Schlüssel nur noch in dieser Funktion, bis die Antwort da ist
      try {
        const zugang = await laborZugangSetzen(schluessel, ws);
        setLaden({ art: "ok", zugang });
        setCodeNoetig(false);
        setWorkspace("");
        setMeldung({
          art: "ok",
          text: `Geprüft und gespeichert. Der Schlüssel endet auf …${zugang.endetAuf ?? "(unbekannt)"}. Er gilt für neue Laborsitzungen, spätestens nach 30 Sekunden.`,
        });
        onFaktor?.();
      } catch (x) {
        const bild = fehlerBildAus(x);
        if (bild.code === FAKTOR_ALT) {
          // der Kern hat nichts verarbeitet: Der Schlüssel bleibt im Feld, nur der Code fehlt noch
          if (feld) feld.value = schluessel;
          codeErzwingen.current = true;
          setCodeNoetig(true);
          requestAnimationFrame(() => codeRef.current?.focus());
        }
        setMeldung({ art: "fehler", text: bild.text });
      }
    } finally {
      setLaeuft(false);
    }
  };

  const entfernen = async () => {
    if (laeuft) return;
    setMeldung(null);
    setLaeuft(true);
    try {
      if (!(await faktorSichern())) return;
      try {
        const zugang = await laborZugangEntfernen();
        setLaden({ art: "ok", zugang });
        setFrage(false);
        setCodeNoetig(false);
        setMeldung({
          art: "ok",
          text:
            zugang.quelle === "server"
              ? "Der gespeicherte Schlüssel ist entfernt. Für neue Laborsitzungen gilt wieder der Schlüssel des Servers."
              : "Der gespeicherte Schlüssel ist entfernt. Es gibt keinen weiteren: Neue Laborsitzungen laufen über Hausmodelle.",
        });
        onFaktor?.();
        requestAnimationFrame(() => schluesselRef.current?.focus());
      } catch (x) {
        const bild = fehlerBildAus(x);
        if (bild.code === FAKTOR_ALT) {
          codeErzwingen.current = true;
          setCodeNoetig(true);
          requestAnimationFrame(() => codeRef.current?.focus());
        }
        setMeldung({ art: "fehler", text: bild.text });
      }
    } finally {
      setLaeuft(false);
    }
  };

  const frageSchliessen = () => {
    setFrage(false);
    requestAnimationFrame(() => entfernenRef.current?.focus());
  };

  const aufEscape = (e: KeyboardEvent) => {
    if (e.key === "Escape" && !laeuft) frageSchliessen();
  };

  const gespeichert = laden.art === "ok" && laden.zugang.quelle === "gespeichert";
  const meldungId = `${id}-meldung`;

  const codeFeld = codeNoetig && (
    <div className="ws-feld">
      <label htmlFor={`${id}-code`}>Code der Authenticator-App</label>
      <input
        id={`${id}-code`}
        ref={codeRef}
        className="ws-code"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={7}
        value={code}
        disabled={laeuft}
        aria-describedby={`${id}-code-hilfe`}
        onChange={(e) => setCode(e.target.value)}
      />
      <p id={`${id}-code-hilfe`} className="ws-klein">
        Sechs Ziffern, höchstens eine Minute alt. Der Code geht nur an die Anmeldung und wird nach dem Absenden geleert.
      </p>
    </div>
  );

  return (
    <Karte titel="Claude-Zugang des Labors" rechts={laden.art === "ok" ? <Pille art={gespeichert ? "ok" : "neutral"}>{QUELLE_WORT[laden.zugang.quelle]}</Pille> : undefined}>
      <p className="ws-klein">
        Über diesen Schlüssel führen die Laborprofile ihr Gespräch. Er wird beim Speichern bei Anthropic geprüft, verschlüsselt im Kern abgelegt und nie wieder angezeigt, auch
        dir nicht. Ist keiner gespeichert, gilt der Schlüssel des Servers, danach die Hausmodelle. Eine Änderung gilt für neue Laborsitzungen.
      </p>
      {laden.art === "laedt" && <Laedt was="Der Claude-Zugang" />}
      {laden.art === "fehler" && <FehlerHinweis fehler={laden.fehler} onNeu={neuLaden} />}
      {laden.art === "ok" && (
        <div aria-busy={laeuft || undefined}>
          <Angaben zugang={laden.zugang} />
          <p className="ws-hinweis">{quelleSatz(laden.zugang)}</p>
          {laden.zugang.hinweis && <p className="ws-hinweis">{laden.zugang.hinweis}</p>}
        </div>
      )}
      {laden.art !== "laedt" && !frage && (
        <form onSubmit={(e) => void speichern(e)} noValidate style={{ display: "grid", gap: 12 }} aria-label="Zugang des Labors setzen">
          <div className="ws-feld">
            <label htmlFor={`${id}-schluessel`}>{gespeichert ? "Neuer Claude-Schlüssel (ersetzt den gespeicherten)" : "Claude-Schlüssel"}</label>
            <input
              id={`${id}-schluessel`}
              ref={schluesselRef}
              type="password"
              name="labor-claude-schluessel"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              placeholder="sk-ant-api…"
              disabled={laeuft}
              aria-invalid={feldFehler || undefined}
              aria-describedby={feldFehler ? meldungId : undefined}
              onInput={() => feldFehler && setFeldFehler(false)}
            />
          </div>
          <div className="ws-feld">
            <label htmlFor={`${id}-workspace`}>Workspace-ID (nur wenn der Schlüssel zu keinem Workspace gehört)</label>
            <input
              id={`${id}-workspace`}
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="wrkspc_…"
              value={workspace}
              disabled={laeuft}
              onChange={(e) => setWorkspace(e.target.value)}
            />
          </div>
          {codeFeld}
          <div className="ws-aktionen">
            <button type="submit" className="btn-primary" disabled={laeuft}>
              {laeuft ? "Einen Moment …" : "Prüfen und speichern"}
            </button>
            {gespeichert && (
              <button ref={entfernenRef} type="button" className="btn-secondary" disabled={laeuft} onClick={() => setFrage(true)}>
                Entfernen …
              </button>
            )}
          </div>
        </form>
      )}
      {frage && (
        <div className="ws-hinweis" role="group" aria-label="Gespeicherten Schlüssel entfernen" onKeyDown={aufEscape} style={{ display: "grid", gap: 12 }}>
          <p style={{ margin: 0 }}>
            Wirklich entfernen? Danach gilt für neue Laborsitzungen wieder der Schlüssel des Servers (falls einer gesetzt ist), sonst laufen sie über Hausmodelle.
          </p>
          {codeFeld}
          <div className="ws-aktionen">
            <button type="button" className="btn-primary" disabled={laeuft} onClick={() => void entfernen()}>
              {laeuft ? "Einen Moment …" : "Ja, entfernen"}
            </button>
            <button ref={abbrechenRef} type="button" className="btn-secondary" disabled={laeuft} onClick={frageSchliessen}>
              Abbrechen
            </button>
          </div>
        </div>
      )}
      <div id={meldungId}>
        <p className="ws-erfolg" role="status">
          {meldung?.art === "ok" ? meldung.text : ""}
        </p>
        {meldung?.art === "fehler" && <FehlerHinweis fehler={{ code: "meldung", text: meldung.text, status: 0 }} />}
      </div>
    </Karte>
  );
}
