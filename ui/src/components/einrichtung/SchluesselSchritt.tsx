"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { FELD, SchluesselFormular, useSchluesselAktionen } from "@/components/SchluesselFormular";
import { SCHRITT_FRAGE, weiterText, type ModellSchrittId } from "@/lib/einrichtungSchritte";
import { useModellzugangStandHalten } from "@/lib/modellzugangApi";
import { wamo } from "@/lib/wamo";
import type { EinrichtungsSchrittProps } from "./schritte";
import { SchrittKnoepfe } from "./SchrittKnoepfe";

const ART = { token: "code", api: "api" } as const;

/**
 * Ein Schlüsselschritt des geführten Ablaufs (Token oder API-Schlüssel). Eigenständig: holt den Stand selbst über die
 * HTTP-Schnittstelle des Kerns (ohne Sitzung), nutzt Feld und Anleitung der Karte Modellzugang (SchluesselFormular) und
 * ruft weiter() nach erfolgreichem Speichern oder beim Überspringen. Ist schon etwas hinterlegt, zeigt das Feld nur das
 * Ende, und der Knopf heißt "Weiter". Der Schlüssel steht nur im Feld und in der einen Anfrage.
 *
 * Steht beim Überspringen, Weiter oder Zurück noch etwas im Feld, geht es nicht still verloren: Statt der Knopfzeile erscheint
 * die Frage "Hinterlegen oder verwerfen?" mit zwei Knöpfen, der Fokus liegt auf der Frage (Screenreader lesen sie vor, Tab
 * erreicht beide Wahlen). "Eingabe hinterlegen" sendet das Formular ab (über das Attribut form, der Wert verlässt das Feld nur
 * dorthin), "Eingabe verwerfen" führt den gewählten Schritt aus. Wird das Feld leer, verschwindet die Frage.
 */
export function SchluesselSchritt({ id, weiter, zurueck }: EinrichtungsSchrittProps & { id: ModellSchrittId }) {
  useModellzugangStandHalten(undefined);
  const { zugang, wartet, hinweis, hinterlegen, loeschen } = useSchluesselAktionen(undefined);
  const art = ART[id];
  const formId = useId();
  const frageId = useId();
  const frageRef = useRef<HTMLParagraphElement>(null);
  const [gefuellt, setGefuellt] = useState(false);
  /** wohin es nach "Eingabe verwerfen" geht; null: keine Rückfrage offen */
  const [nachfrage, setNachfrage] = useState<"weiter" | "zurueck" | null>(null);
  // Wird das Feld leer, ist auch die Rückfrage erledigt (sie kommt beim nächsten Tippen nicht von selbst wieder)
  const fuellstand = useCallback((g: boolean) => {
    setGefuellt(g);
    if (!g) setNachfrage(null);
  }, []);
  const frageOffen = nachfrage !== null && gefuellt;
  useEffect(() => {
    if (frageOffen) frageRef.current?.focus();
  }, [frageOffen]);
  const oderFragen = (ziel: "weiter" | "zurueck", aktion: () => void) => () => {
    if (gefuellt) setNachfrage(ziel);
    else aktion();
  };

  // Nach erfolgreichem Hinterlegen des eigenen Typs geht es weiter (ein umgeleiteter Wert des anderen Typs bleibt hier)
  const weiterRef = useRef(weiter);
  useEffect(() => {
    weiterRef.current = weiter;
  });
  useEffect(() => {
    if (hinweis && !hinweis.fehler && hinweis.art === art && hinweis.aktion === "hinterlegen") weiterRef.current();
  }, [hinweis, art]);

  const standFehler = zugang && !zugang.art && zugang.fehler ? zugang.fehler : null;
  const festgelegt = zugang?.festgelegt === true;
  // Meldung zum anderen Typ (Wert im falschen Feld umgeleitet): das Feld dieses Schritts zeigt sie nicht
  const fremd = hinweis && hinweis.art !== art ? hinweis : null;

  return (
    <div className="ea-schritt">
      <p className="ea-frage">{SCHRITT_FRAGE[id]}</p>
      {standFehler ? (
        <div className="mz-falsch" role="alert">
          <p className="mz-meldung" data-fehler>
            Fehler: {standFehler}
          </p>
          <button
            type="button"
            className="btn-secondary btn-small"
            onClick={() => wamo.set((s) => ({ ...s, modellzugang: null }))}
          >
            Erneut versuchen
          </button>
        </div>
      ) : !zugang?.art ? (
        <p className="ea-klein" role="status">
          Stand wird geladen …
        </p>
      ) : festgelegt ? (
        <p className="mz-offline">Ein Admin hat dein Profil auf Hausmodelle festgelegt. Eigene Schlüssel und Token sind nicht möglich.</p>
      ) : (
        <>
          {zugang.quelle === "wahl" && (
            <p className="mz-offline">
              Du hast Nur Hausmodelle gewählt. Was du hier hinterlegst, benutzt W.A.I.S. erst, wenn du unter Einstellungen,
              Modellzugang wieder Automatisch wählst.
            </p>
          )}
          <SchluesselFormular
            art={art}
            {...FELD[art]}
            hinterlegt={art === "api" ? zugang.hinterlegt : zugang.codeHinterlegt}
            ende={art === "api" ? zugang.ende : zugang.codeEnde}
            gesetzt={art === "api" ? zugang.geprueft : zugang.codeGesetzt}
            wartet={wartet}
            hinweis={hinweis}
            workspace={art === "api"}
            onHinterlegen={(wert, ws) => hinterlegen(art, wert, art === "api" ? ws : "")}
            onUmleiten={(ziel, wert) => hinterlegen(ziel, wert, "")}
            onLoeschen={() => loeschen(art)}
            formId={formId}
            onGefuellt={fuellstand}
          />
          <p className="mz-meldung" role="status">
            {fremd && !fremd.fehler ? fremd.text : ""}
          </p>
          {fremd?.fehler && (
            <p className="mz-meldung" role="alert" data-fehler>
              Fehler: {fremd.text}
            </p>
          )}
        </>
      )}
      {frageOffen ? (
        <div className="ea-nachfrage" role="group" aria-labelledby={frageId}>
          <p id={frageId} ref={frageRef} tabIndex={-1} className="ea-text">
            Du hast schon etwas eingegeben. Hinterlegen oder verwerfen?
          </p>
          <div className="ea-knoepfe">
            <button type="submit" form={formId} className="btn-primary" onClick={() => setNachfrage(null)}>
              Eingabe hinterlegen
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                const ziel = nachfrage;
                setNachfrage(null);
                if (ziel === "zurueck") zurueck?.();
                else weiter();
              }}
            >
              Eingabe verwerfen
            </button>
          </div>
        </div>
      ) : (
        <SchrittKnoepfe
          weiter={oderFragen("weiter", weiter)}
          zurueck={zurueck ? oderFragen("zurueck", zurueck) : undefined}
          text={festgelegt ? "Weiter" : weiterText(id, zugang)}
          primaer={festgelegt || weiterText(id, zugang) === "Weiter"}
          gesperrt={wartet !== null}
        />
      )}
    </div>
  );
}
