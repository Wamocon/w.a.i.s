"use client";

import { memo, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { entwurfDatum, entwurfIso } from "@/lib/auftragEntwuerfe";
import {
  artName,
  SELBST_ARTEN,
  SELBST_ART_NAMEN,
  SELBST_ART_STANDARD,
  SELBST_BEARBEITER_NAMEN,
  SELBST_BESCHREIBUNG_MAX,
  SELBST_PRIORITAETEN,
  SELBST_PRIORITAET_NAMEN,
  SELBST_PRIORITAET_STANDARD,
  SELBST_QUELLEN_NAMEN,
  SELBST_STATUS_NAMEN,
  SELBST_TITEL_MAX,
  selbstDarfOeffnen,
  selbstDarfVerwerfen,
  selbstEingabePruefen,
  selbstNummer,
  selbstZeichen,
  type SelbstArt,
  type SelbstAuftrag,
  type SelbstEingabe,
  type SelbstEingabeProblem,
  type SelbstPrioritaet,
} from "@/lib/selbstAuftraege";
import { useSelect } from "@/lib/store";
import type { SelbstAuftragAktionen } from "@/lib/useWamo";
import { istOnline, wamo } from "@/lib/wamo";

/** Stand des Formulars beim Absenden und Nummer der damals letzten Meldung. */
type Abgeschickt = { n: number } & SelbstEingabe;

/**
 * Aufträge an W.A.I.S. selbst im Reiter "Aufträge" (lib/selbstAuftraege.ts): ein gemeinsamer Rückstand für Verbesserungen, Fehlerbehebungen
 * und neue Funktionen an W.A.I.S. Die Liste zeigt Nummer (SA-7), Titel, Art, Priorität, Status, Quelle und Datum, bei unsicherer Eintragung
 * den Hinweis "Nach Fremdinhalt gespeichert, bitte prüfen", dazu Bearbeiter und Ergebnis. Verwerfen und Wieder öffnen gehen ohne Dialog des
 * Browsers (beides lässt sich zurücknehmen); "In Arbeit" und "Erledigt" setzt allein, wer den Auftrag bearbeitet. Das Formular prüft vor dem
 * Senden, zeigt Fehler des Kerns und leert sich nach Erfolg. Den Block gibt es erst, wenn der Kern mindestens einmal mit Liste geantwortet hat
 * (sonst fehlt er ganz, ohne Fehlermeldung, etwa für Mitglieder und im Labor, das keine Aktionen bekommt). Ohne Verbindung und solange eine
 * Aktion auf Antwort wartet, sind die Knöpfe gesperrt. Jede Rückmeldung steht in einer Live-Region (Erfolg als Status, Fehler als Alarm), nicht
 * zusätzlich in der Ansage der Seite. Alle Texte vom Kern sind geprüft (lib/nachrichten.ts) und stehen nur als Text da, nie als HTML.
 */
export const SelbstAuftraege = memo(function SelbstAuftraege({ aktionen }: { aktionen?: SelbstAuftragAktionen }) {
  const stand = useSelect(wamo, (s) => s.selbstAuftraege);
  const online = useSelect(wamo, istOnline);
  const id = useId();
  const [titel, setTitel] = useState("");
  const [beschreibung, setBeschreibung] = useState("");
  const [art, setArt] = useState<SelbstArt>(SELBST_ART_STANDARD);
  const [prioritaet, setPrioritaet] = useState<SelbstPrioritaet>(SELBST_PRIORITAET_STANDARD);
  const [problem, setProblem] = useState<SelbstEingabeProblem | null>(null);
  /** Was beim Absenden im Formular stand und welche Meldung die letzte war: erst eine neuere Antwort auf "speichern" entscheidet über das
   *  Leeren, und nur, wenn die Person inzwischen nichts geändert hat (auch eine verspätete Antwort leert dann noch) */
  const [abgeschickt, setAbgeschickt] = useState<Abgeschickt | null>(null);
  /** Nummer der Meldung, die beim letzten Klick schon da war: ältere Meldungen sind dann ausgeblendet (sie gehören zur Aktion davor) */
  const [leise, setLeise] = useState(0);
  const titelFeld = useRef<HTMLInputElement>(null);
  const beschreibungFeld = useRef<HTMLTextAreaElement>(null);
  /** Kennung des Knopfs, der zuletzt geklickt hat: dorthin geht der Fokus zurück, wenn die Antwort da ist */
  const zuletzt = useRef<string | null>(null);
  const wartet = stand?.wartet != null;

  // Antwort auf das Anlegen ist da: bei Erfolg leert sich das Formular, aber nur, wenn die Person währenddessen nichts geändert hat; bei
  // einem Fehler bleibt es, wie es war
  const letzte = stand?.meldung ?? null;
  if (abgeschickt !== null && letzte && letzte.n > abgeschickt.n && letzte.aktion === "speichern") {
    setAbgeschickt(null);
    const unveraendert =
      titel === abgeschickt.titel && beschreibung === abgeschickt.beschreibung && art === abgeschickt.art && prioritaet === abgeschickt.prioritaet;
    if (letzte.ok && unveraendert) {
      setTitel("");
      setBeschreibung("");
      setArt(SELBST_ART_STANDARD);
      setPrioritaet(SELBST_PRIORITAET_STANDARD);
      setProblem(null);
    }
  }

  // Ist die Antwort da und hat der Klick den Fokus verloren (der Knopf war gesperrt), geht er auf den Knopf zurück
  useEffect(() => {
    if (wartet || !zuletzt.current) return;
    const knopf = document.getElementById(zuletzt.current);
    zuletzt.current = null;
    const aktiv = document.activeElement;
    if (knopf && (!aktiv || aktiv === document.body)) knopf.focus();
  }, [wartet]);

  if (!aktionen || !stand) return null;
  const gesperrt = !online || wartet;
  const speichert = stand.wartet?.aktion === "speichern";
  const meldung = stand.meldung && stand.meldung.n > leise ? stand.meldung : null;

  const absenden = (e: FormEvent) => {
    e.preventDefault();
    if (gesperrt) return;
    const daten = { titel, beschreibung, art, prioritaet };
    const fehler = selbstEingabePruefen(daten);
    if (fehler) {
      setProblem(fehler);
      (fehler.feld === "titel" ? titelFeld : beschreibungFeld).current?.focus();
      return;
    }
    setProblem(null);
    zuletzt.current = `${id}-speichern`;
    const n = stand.meldung?.n ?? 0;
    if (aktionen.speichern(daten)) {
      setAbgeschickt({ n, ...daten });
      setLeise(n);
    } else {
      zuletzt.current = null;
    }
  };

  const eintragAktion = (nr: number, tun: (nr: number) => boolean) => {
    zuletzt.current = `${id}-eintrag-${nr}`;
    if (tun(nr)) setLeise(stand.meldung?.n ?? 0);
    else zuletzt.current = null;
  };

  const anzahl = stand.liste.length;
  const fehlerId = `${id}-fehler`;

  return (
    <section className="entwuerfe selbst" aria-labelledby={`${id}-kopf`}>
      <h3 id={`${id}-kopf`} className="entwuerfe-titel">
        Aufträge an W.A.I.S. selbst
      </h3>
      <p className="selbst-text">
        Verbesserungen, Fehlerbehebungen und neue Funktionen an W.A.I.S. selbst, ein gemeinsamer Rückstand für alle Admins. Den Status „In
        Arbeit“ und „Erledigt“ setzt, wer den Auftrag bearbeitet, nicht diese Seite.
      </p>
      {anzahl === 0 ? (
        <p className="entwuerfe-leer">Noch keine Aufträge an W.A.I.S. selbst. Lege unten einen an oder sag es W.A.I.S. per Sprache.</p>
      ) : (
        <ul className="entwuerfe-liste">
          {stand.liste.map((a) => (
            <Eintrag
              key={a.nr}
              a={a}
              knopfId={`${id}-eintrag-${a.nr}`}
              gesperrt={gesperrt}
              onVerwerfen={() => eintragAktion(a.nr, aktionen.verwerfen)}
              onOeffnen={() => eintragAktion(a.nr, aktionen.oeffnen)}
            />
          ))}
        </ul>
      )}
      {anzahl > 0 && (
        <p className="entwuerfe-hinweis">
          {anzahl} {anzahl === 1 ? "Eintrag" : "Einträge"} im Rückstand{stand.max !== null ? `, höchstens ${stand.max}` : ""}.
        </p>
      )}
      {/* Die Region bleibt immer im DOM; der Text steckt in einem Element mit der Nummer der Meldung als key, damit auch ein zweites
          gleichlautendes "Verworfen." als neue Änderung angesagt wird */}
      <p className="selbst-status" role="status">
        {meldung?.ok ? <span key={meldung.n}>{meldung.text}</span> : null}
      </p>
      {meldung && !meldung.ok && (
        <p className="notice" role="alert" key={meldung.n}>
          {meldung.text}
        </p>
      )}
      <form className="selbst-form" aria-labelledby={`${id}-formkopf`} onSubmit={absenden} noValidate>
        <h4 id={`${id}-formkopf`} className="selbst-form-titel">
          Neuer Auftrag an W.A.I.S.
        </h4>
        <label htmlFor={`${id}-titel`}>Titel</label>
        <input
          ref={titelFeld}
          id={`${id}-titel`}
          type="text"
          autoComplete="off"
          value={titel}
          maxLength={SELBST_TITEL_MAX * 2}
          aria-required="true"
          aria-invalid={problem?.feld === "titel" || undefined}
          aria-describedby={`${id}-titel-zahl${problem?.feld === "titel" ? ` ${fehlerId}` : ""}`}
          onChange={(e) => {
            setTitel(e.target.value);
            if (problem?.feld === "titel") setProblem(null);
          }}
        />
        <p id={`${id}-titel-zahl`} className="selbst-zaehler">{`${selbstZeichen(titel)} von ${SELBST_TITEL_MAX} Zeichen`}</p>
        <label htmlFor={`${id}-beschreibung`}>Beschreibung</label>
        <textarea
          ref={beschreibungFeld}
          id={`${id}-beschreibung`}
          rows={5}
          value={beschreibung}
          maxLength={SELBST_BESCHREIBUNG_MAX * 2}
          aria-required="true"
          aria-invalid={problem?.feld === "beschreibung" || undefined}
          aria-describedby={`${id}-beschreibung-zahl${problem?.feld === "beschreibung" ? ` ${fehlerId}` : ""}`}
          onChange={(e) => {
            setBeschreibung(e.target.value);
            if (problem?.feld === "beschreibung") setProblem(null);
          }}
        />
        <p id={`${id}-beschreibung-zahl`} className="selbst-zaehler">{`${selbstZeichen(beschreibung)} von ${SELBST_BESCHREIBUNG_MAX} Zeichen`}</p>
        <div className="selbst-paar">
          <div>
            <label htmlFor={`${id}-art`}>Art</label>
            <select id={`${id}-art`} value={art} onChange={(e) => setArt(e.target.value as SelbstArt)}>
              {SELBST_ARTEN.map((a) => (
                <option key={a} value={a}>
                  {SELBST_ART_NAMEN[a]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-prioritaet`}>Priorität</label>
            <select
              id={`${id}-prioritaet`}
              value={prioritaet}
              onChange={(e) => setPrioritaet(Number(e.target.value) as SelbstPrioritaet)}
            >
              {SELBST_PRIORITAETEN.map((p) => (
                <option key={p} value={p}>
                  {SELBST_PRIORITAET_NAMEN[p]}
                </option>
              ))}
            </select>
          </div>
        </div>
        {problem && (
          <p id={fehlerId} className="notice" role="alert">
            {problem.text}
          </p>
        )}
        <div className="selbst-knoepfe">
          <button
            id={`${id}-speichern`}
            type="submit"
            className="btn-secondary btn-small"
            disabled={gesperrt}
            aria-busy={speichert || undefined}
          >
            {speichert ? "Wird gespeichert …" : "Speichern"}
          </button>
        </div>
      </form>
    </section>
  );
});

function Eintrag({
  a,
  knopfId,
  gesperrt,
  onVerwerfen,
  onOeffnen,
}: {
  a: SelbstAuftrag;
  knopfId: string;
  gesperrt: boolean;
  onVerwerfen: () => void;
  onOeffnen: () => void;
}) {
  const nummer = selbstNummer(a.nr);
  const datum = entwurfDatum(a.erstelltMs);
  const angaben = [
    artName(a.art),
    `Priorität ${SELBST_PRIORITAET_NAMEN[a.prioritaet]}`,
    a.quelle ? `Quelle ${SELBST_QUELLEN_NAMEN[a.quelle]}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const verwerfen = selbstDarfVerwerfen(a.status);
  const oeffnen = selbstDarfOeffnen(a.status);

  return (
    <li className="entwurf selbst-eintrag" data-status={a.status}>
      <p className="selbst-kopf">
        <span className="selbst-nr">{nummer}</span>
        <span className="selbst-marke" data-status={a.status}>
          {SELBST_STATUS_NAMEN[a.status]}
        </span>
      </p>
      <p className="entwurf-titel">{a.titel}</p>
      <p className="entwurf-meta">
        {angaben}
        {datum && (
          <>
            {" · "}erstellt am <time dateTime={entwurfIso(a.erstelltMs)}>{datum}</time>
          </>
        )}
      </p>
      {a.unsicher && <p className="selbst-unsicher">Nach Fremdinhalt gespeichert, bitte prüfen</p>}
      {a.bearbeiter && <p className="entwurf-meta">Bearbeiter: {SELBST_BEARBEITER_NAMEN[a.bearbeiter]}</p>}
      {a.ergebnis && (
        <p className="selbst-ergebnis">
          <strong>Ergebnis:</strong> {a.ergebnis}
        </p>
      )}
      {(verwerfen || oeffnen) && (
        <div className="approval-actions">
          {/* ein Knopf für beide Fälle: bleibt beim Wechsel derselbe Knoten, der Fokus geht so nicht verloren */}
          <button
            id={knopfId}
            type="button"
            className="btn-decide"
            disabled={gesperrt}
            onClick={verwerfen ? onVerwerfen : onOeffnen}
            aria-label={`${verwerfen ? "Verwerfen" : "Wieder öffnen"}: ${nummer} ${a.titel}`}
          >
            {verwerfen ? "Verwerfen" : "Wieder öffnen"}
          </button>
        </div>
      )}
    </li>
  );
}
