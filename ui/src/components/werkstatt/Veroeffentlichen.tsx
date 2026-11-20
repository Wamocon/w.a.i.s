"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { codeBestaetigen } from "@/lib/geraeteVerwaltungApi";
import { fehlerBildAus, freigabeAusfuehren, freigabeKarteAnlegen, kartenPruefen } from "@/lib/werkstattApi";
import { brauchtNeuenCode, karteUnbrauchbar } from "@/lib/werkstattFehler";
import {
  SCHRITT_TITEL,
  codeSauber,
  ergebnisText,
  kartenEndeMs,
  restSekunden,
  restText,
  schrittStaende,
  wirkungText,
  type Ablauf,
  type SchrittStand,
} from "@/lib/werkstattVeroeffentlichen";
import type { FehlerBild, Karte as KarteTyp } from "@/lib/werkstattTypen";
import { FehlerHinweis, Karte } from "./Bausteine";

/**
 * Veröffentlichen in vier Schritten: Prüfung (Trockenlauf, ändert nichts), Karte (nennt die Wirkung, gilt fünf Minuten, einmal,
 * nur für dich), zweiter Faktor (ein frischer Code, höchstens 60 Sekunden alt) und Ausführung. Der Kern lädt die neue Version im
 * Betrieb selbst nach und behält die vorige als Rückfall. Der Code und das Token bleiben in dieser Komponente nur so lange, wie der
 * Aufruf dauert: Der Code wird nach dem Absenden geleert, das Token wird nie gehalten (lib/werkstattApi.ts liest es je Anfrage).
 */

const STAND_WORT: Record<SchrittStand, string> = { offen: "folgt", aktiv: "jetzt dran", fertig: "erledigt" };

function Schritt({ nr, stand, children }: { nr: number; stand: SchrittStand; children: ReactNode }) {
  return (
    <li className="ws-schritt" data-stand={stand} aria-current={stand === "aktiv" ? "step" : undefined}>
      <h3>
        <span className="ws-schritt-nr" aria-hidden="true">{stand === "fertig" ? "✓" : nr}</span>
        {SCHRITT_TITEL[nr - 1]}
        <span className="ws-schritt-stand">{STAND_WORT[stand]}</span>
      </h3>
      {children}
    </li>
  );
}

type Props = {
  karten: readonly KarteTyp[];
  aktiveVersion: number | null;
  /** nach der Ausführung: Katalog und Versionen neu laden */
  onVeroeffentlicht: () => void;
  /** nach einem frischen Code: der Zugang (Alter des zweiten Faktors) hat sich geändert */
  onFaktor: () => void;
};

export function Veroeffentlichen({ karten, aktiveVersion, onVeroeffentlicht, onFaktor }: Props) {
  const id = useId();
  const [ablauf, setAblauf] = useState<Ablauf>({ art: "bereit" });
  const [fehler, setFehler] = useState<FehlerBild | null>(null);
  const [code, setCode] = useState("");
  const [codeFehler, setCodeFehler] = useState("");
  const [jetzt, setJetzt] = useState(0);
  const entwuerfe = karten.filter((k) => k.stand === "entwurf");
  const kennungen = entwuerfe.map((k) => k.id);
  const zaehlt = ablauf.art === "karte";

  // Die Uhr läuft nur, solange eine Karte wartet.
  useEffect(() => {
    if (!zaehlt) return;
    const takt = setInterval(() => setJetzt(Date.now()), 1000);
    return () => clearInterval(takt);
  }, [zaehlt]);

  const rest = ablauf.art === "karte" ? restSekunden(ablauf.endeMs, jetzt) : 0;
  const abgelaufen = ablauf.art === "karte" && rest === 0 && jetzt > 0;

  const pruefen = async () => {
    setFehler(null);
    setAblauf({ art: "prueft" });
    try {
      const pruefung = await kartenPruefen();
      setAblauf(pruefung.ok ? { art: "geprueft", pruefung } : { art: "abgelehnt", pruefung });
    } catch (x) {
      setFehler(fehlerBildAus(x));
      setAblauf({ art: "bereit" });
    }
  };

  const karteAnfordern = async (pruefung: Extract<Ablauf, { art: "geprueft" }>["pruefung"]) => {
    setFehler(null);
    setCode("");
    setCodeFehler("");
    setAblauf({ art: "karte_laeuft", pruefung });
    try {
      const karte = await freigabeKarteAnlegen();
      const jetztMs = Date.now();
      setJetzt(jetztMs);
      setAblauf({ art: "karte", pruefung, karte, endeMs: kartenEndeMs(karte.giltBis, jetztMs) });
    } catch (x) {
      setFehler(fehlerBildAus(x));
      setAblauf({ art: "geprueft", pruefung });
    }
  };

  const ausfuehren = async (a: Extract<Ablauf, { art: "karte" }>) => {
    const sauber = codeSauber(code);
    if (!sauber) {
      setCodeFehler("Bitte gib die sechs Ziffern aus der Authenticator-App ein.");
      return;
    }
    setFehler(null);
    setCodeFehler("");
    setAblauf({ art: "ausfuehren", pruefung: a.pruefung, karte: a.karte, endeMs: a.endeMs });
    const zurueck = (meldung?: string) => {
      setCode("");
      if (meldung) setCodeFehler(meldung);
      setAblauf(a);
    };
    const bestaetigt = await codeBestaetigen(sauber);
    setCode("");
    if (!bestaetigt.ok) return zurueck(bestaetigt.text);
    try {
      const ergebnis = await freigabeAusfuehren(a.karte.id);
      setAblauf({ art: "fertig", ergebnis });
      onVeroeffentlicht();
      onFaktor();
    } catch (x) {
      const bild = fehlerBildAus(x);
      if (karteUnbrauchbar(bild.code)) {
        setFehler(bild);
        setAblauf({ art: "geprueft", pruefung: a.pruefung });
      } else if (brauchtNeuenCode(bild.code)) {
        zurueck(bild.text);
      } else {
        setFehler(bild);
        zurueck();
      }
    }
  };

  const stand = schrittStaende(abgelaufen && ablauf.art === "karte" ? { art: "geprueft", pruefung: ablauf.pruefung } : ablauf);
  const beschaeftigt = ablauf.art === "prueft" || ablauf.art === "karte_laeuft" || ablauf.art === "ausfuehren";
  const pruefung = "pruefung" in ablauf ? ablauf.pruefung : null;
  const wirkung = wirkungText(aktiveVersion, kennungen, null);

  return (
    <Karte titel="Veröffentlichen und im Kern nachladen">
      <p className="ws-klein">
        Änderungen werden erst geprüft, dann mit Karte und zweitem Faktor veröffentlicht. Der Kern lädt die neue Version im Betrieb nach, die vorige bleibt als Rückfall.
      </p>
      {fehler && <FehlerHinweis fehler={fehler} />}
      <ol className="ws-leitfaden" aria-label="Schritte zum Veröffentlichen" aria-busy={beschaeftigt || undefined}>
        <Schritt nr={1} stand={stand[0]}>
          <p className="ws-klein">Prüft Pflichtfelder, die Werkzeuge, Anweisungen an W.A.I.S. im Text und das Zeichenbudget. Ändert nichts.</p>
          {(ablauf.art === "bereit" || ablauf.art === "prueft" || ablauf.art === "abgelehnt") && (
            entwuerfe.length === 0 ? (
              <p className="ws-leer">Keine Entwürfe. Speichere zuerst einen Use Case.</p>
            ) : (
              <>
                <p className="ws-hinweis">{entwuerfe.length === 1 ? "1 Entwurf" : `${entwuerfe.length} Entwürfe`}: {kennungen.join(", ")}</p>
                <div className="ws-aktionen">
                  <button type="button" className="btn-secondary" disabled={beschaeftigt} onClick={() => void pruefen()}>
                    {ablauf.art === "abgelehnt" ? "Noch einmal prüfen" : "Prüfen"}
                  </button>
                </div>
              </>
            )
          )}
          {ablauf.art === "abgelehnt" && (
            <div className="ws-fehler" role="alert">
              <span>
                Die Prüfung lehnt die Karten ab ({ablauf.pruefung.zeichen} Zeichen):{" "}
                {ablauf.pruefung.probleme.length > 0 ? ablauf.pruefung.probleme.join(" ") : "Bitte prüfe die Karten."}
              </span>
            </div>
          )}
          {pruefung && pruefung.ok && <p className="ws-erfolg">Geprüft: {pruefung.zeichen} Zeichen von 6000, keine Probleme.</p>}
        </Schritt>

        <Schritt nr={2} stand={stand[1]}>
          <p className="ws-klein">Die Karte nennt die Wirkung. Sie gilt fünf Minuten, einmal und nur für dich.</p>
          {(ablauf.art === "geprueft" || ablauf.art === "karte_laeuft") && (
            <>
              <p className="ws-hinweis">{wirkung}</p>
              <div className="ws-aktionen">
                <button type="button" className="btn-secondary" disabled={ablauf.art === "karte_laeuft"} onClick={() => void karteAnfordern(ablauf.pruefung)}>
                  Karte anlegen
                </button>
              </div>
            </>
          )}
          {abgelaufen && (
            <div className="ws-fehler" role="alert">
              <span>Die Karte ist abgelaufen. Bitte lege eine neue Karte an.</span>
              <button type="button" className="btn-secondary btn-small" onClick={() => setAblauf({ art: "geprueft", pruefung: ablauf.pruefung })}>Neue Karte</button>
            </div>
          )}
          {(ablauf.art === "karte" || ablauf.art === "ausfuehren") && !abgelaufen && (
            <p className="ws-hinweis">
              {wirkungText(aktiveVersion, ablauf.karte.karten.length > 0 ? ablauf.karte.karten : kennungen, ablauf.karte.aenderungen)}{" "}
              {ablauf.art === "karte" ? <>Gültig noch <span className="ws-rest" aria-label={`noch ${restText(rest)} Minuten`}>{restText(rest)}</span>.</> : null}
            </p>
          )}
        </Schritt>

        <Schritt nr={3} stand={stand[2]}>
          <p className="ws-klein">Ein frischer Code deiner Authenticator-App, höchstens 60 Sekunden alt.</p>
          {(ablauf.art === "karte" || ablauf.art === "ausfuehren") && !abgelaufen && (
            <form
              className="ws-zeile"
              onSubmit={(e) => {
                e.preventDefault();
                if (ablauf.art === "karte") void ausfuehren(ablauf);
              }}
              noValidate
            >
              <div className="ws-feld">
                <label htmlFor={`${id}-code`}>Sechsstelliger Code</label>
                <input
                  id={`${id}-code`}
                  className="ws-code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={7}
                  value={code}
                  readOnly={ablauf.art === "ausfuehren"}
                  aria-invalid={codeFehler ? true : undefined}
                  aria-describedby={codeFehler ? `${id}-code-f` : undefined}
                  onChange={(e) => setCode(e.target.value)}
                />
              </div>
              <button type="submit" className="btn-primary" disabled={ablauf.art === "ausfuehren" || codeSauber(code) === null}>
                {ablauf.art === "ausfuehren" ? "Einen Moment …" : "Veröffentlichen"}
              </button>
            </form>
          )}
          <p id={`${id}-code-f`} className="ws-feld-fehler" role="alert">{codeFehler}</p>
        </Schritt>

        <Schritt nr={4} stand={stand[3]}>
          {ablauf.art === "fertig" ? (
            <>
              <p className="ws-erfolg" role="status">
                {ergebnisText(ablauf.ergebnis)} Der Kern lädt sie beim nächsten Abruf nach und fällt bei einem Fehler auf die letzte gültige Version zurück.
              </p>
              <div className="ws-aktionen">
                <button type="button" className="btn-secondary" onClick={() => setAblauf({ art: "bereit" })}>Weiter</button>
              </div>
            </>
          ) : (
            <p className="ws-klein">Die Ausführung schreibt in derselben Transaktion eine Zeile ins Audit. Der Kern prüft die Daten beim Laden.</p>
          )}
        </Schritt>
      </ol>
    </Karte>
  );
}
