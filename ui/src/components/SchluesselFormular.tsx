"use client";

import { useEffect, useRef, useState } from "react";
import { useModellzugangSenden } from "@/lib/modellzugangApi";
import { ANTWORT_MS } from "@/lib/modellzugangHilfe";
import { API_ANLEITUNG, falschesFeld, NICHT_AUTOMATISCH, TOKEN_ANLEITUNG, type Anleitung } from "@/lib/schluesselhilfe";
import { useSelect } from "@/lib/store";
import type { ModellzugangAnfrage, SchluesselArt } from "@/lib/useWamo";
import { wamo } from "@/lib/wamo";
import { Ueberschrift } from "@/components/Ueberschrift";

/**
 * Bausteine für Schlüssel und Token: das Feld je Schlüsseltyp (SchluesselFormular) und das Senden mit Warten auf die
 * Antwort des Kerns (useSchluesselAktionen). Genutzt von der Karte Modellzugang (components/ModellZugang.tsx) und von den
 * Schritten des geführten Ablaufs beim Ausrollen (components/einrichtung/). Ein Schlüssel steht nur im Feld und in der
 * einen Anfrage; er landet nie im Zustand außerhalb des Feldes, in einer Meldung oder in einem Log.
 */

// API-Schlüssel (sk-ant-api…) und Claude-Code-Token (sk-ant-oat…) sind verschiedene Dinge: jedes Feld nimmt nur seins
const API_MUSTER = /^sk-ant-(?!oat)[A-Za-z0-9_-]{20,250}$/;
const TOKEN_MUSTER = /^sk-ant-oat\d{2}-[A-Za-z0-9_-]{20,400}$/;
const WORKSPACE_MUSTER = /^wrkspc_[A-Za-z0-9]{6,60}$/;

function zeitText(iso?: string, wort = "am"): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : `, ${wort} ${d.toLocaleDateString("de-DE")} um ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr`;
}

export type Wartet = { art: SchluesselArt; aktion: "hinterlegen" | "loeschen" };
/** aktion: worauf sich die Meldung bezieht (die Schritte gehen nach einem erfolgreichen Hinterlegen weiter) */
export type Hinweis = { art: SchluesselArt; aktion: Wartet["aktion"]; text: string; fehler: boolean };

/**
 * Senden von Schlüssel und Token mit Warten auf die Antwort des Kerns, Zeitgrenze und Meldung je Schlüsseltyp. Mit Sitzung
 * gehen die Anfragen über den Datenkanal (onAnfrage), sonst über die HTTP-Schnittstelle des Kerns (lib/modellzugangApi.ts).
 */
export function useSchluesselAktionen(onAnfrage?: (anfrage: ModellzugangAnfrage) => boolean) {
  const zugang = useSelect(wamo, (s) => s.modellzugang);
  const sende = useModellzugangSenden(onAnfrage);
  const [wartet, setWartet] = useState<Wartet | null>(null);
  const [hinweis, setHinweis] = useState<Hinweis | null>(null);
  const uhr = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Antwort des Kerns beendet das Warten (die Wahl des Modus bearbeitet ModellWahl). Abgeleiteter Zustand während des
  // Renderns statt in einem Effekt: React empfiehlt das für "auf eine neue Antwort reagieren". Nur die Antwort auf
  // die eigene Aktion zählt (eine späte Antwort auf die Statusabfrage beendet nichts).
  const [gesehen, setGesehen] = useState(zugang);
  if (zugang !== gesehen) {
    setGesehen(zugang);
    if (zugang && wartet && zugang.aktion === wartet.aktion) {
      setWartet(null);
      setHinweis({
        art: wartet.art,
        aktion: wartet.aktion,
        text: zugang.fehler
          ? zugang.fehler
          : wartet.aktion === "loeschen"
            ? wartet.art === "api"
              ? "Schlüssel gelöscht."
              : "Token gelöscht."
            : wartet.art === "api"
              ? "Schlüssel geprüft und hinterlegt."
              : "Token gespeichert.",
        fehler: Boolean(zugang.fehler),
      });
    }
  }

  // Die Zeitgrenze fällt weg, sobald nicht mehr gewartet wird (und beim Schließen der Karte)
  useEffect(() => {
    if (wartet === null && uhr.current) {
      clearTimeout(uhr.current);
      uhr.current = null;
    }
  }, [wartet]);
  useEffect(() => () => {
    if (uhr.current) clearTimeout(uhr.current);
  }, []);

  const senden = (anfrage: ModellzugangAnfrage, art: SchluesselArt, aktion: Wartet["aktion"]) => {
    if (uhr.current) clearTimeout(uhr.current);
    setWartet({ art, aktion });
    setHinweis(null);
    uhr.current = setTimeout(() => {
      setWartet(null);
      setHinweis({ art, aktion, text: "Keine Antwort vom Kern. Bitte später noch einmal versuchen.", fehler: true });
    }, ANTWORT_MS);
    sende(anfrage);
  };

  /** true: an den Kern gesendet; false: lokal abgelehnt (Format), nichts gesendet */
  const hinterlegen = (art: SchluesselArt, wert: string, ws: string): boolean => {
    const muster = art === "api" ? API_MUSTER : TOKEN_MUSTER;
    if (!muster.test(wert)) {
      // Ohne den Wert zu nennen: das richtige Feld erkennt SchluesselFormular schon am Anfang (falschesFeld)
      setHinweis({
        art,
        aktion: "hinterlegen",
        text:
          art === "api"
            ? "Das ist kein Anthropic-API-Schlüssel (er beginnt mit sk-ant-api und hat keine Leerzeichen)."
            : "Das ist kein Claude-Code-Token (er beginnt mit sk-ant-oat und hat keine Leerzeichen).",
        fehler: true,
      });
      return false;
    }
    if (art === "api" && ws && !WORKSPACE_MUSTER.test(ws)) {
      setHinweis({ art, aktion: "hinterlegen", text: "Die Workspace-ID beginnt mit wrkspc_.", fehler: true });
      return false;
    }
    senden(
      art === "api"
        ? ws
          ? { aktion: "hinterlegen", schluessel: wert, workspace: ws, schluesselart: "api" }
          : { aktion: "hinterlegen", schluessel: wert, schluesselart: "api" }
        : { aktion: "hinterlegen", schluessel: wert, schluesselart: "code" },
      art,
      "hinterlegen",
    );
    return true;
  };

  const loeschen = (art: SchluesselArt) => senden({ aktion: "loeschen", schluesselart: art }, art, "loeschen");

  return { zugang, sende, wartet, hinweis, hinterlegen, loeschen };
}

export type FormularProps = {
  art: SchluesselArt;
  /** Name des Blocks ("Gespräch", "Entwicklungsaufträge"); Überschrift der Stufe 4 */
  ueberschrift: string;
  /** wofür der Schlüssel gilt, ein Satz unter der Überschrift */
  zweck: string;
  /** was der Kern daraus macht (zum Beispiel "wird im Modus Nur Hausmodelle nicht benutzt"), optional */
  wirkung?: string;
  anleitung: Anleitung;
  beschriftung: string;
  platzhalter: string;
  hinterlegt: boolean;
  ende?: string;
  gesetzt?: string;
  wartet: Wartet | null;
  hinweis: Hinweis | null;
  workspace?: boolean;
  /** true: gesendet (das Feld wird geleert); false: abgelehnt (falsches Format), der Wert bleibt zum Korrigieren */
  onHinterlegen: (wert: string, workspace: string) => boolean;
  /** der Wert gehört in das andere Feld: dort hinterlegen (der Wert wandert nie durch Meldungen) */
  onUmleiten: (art: SchluesselArt, wert: string) => boolean;
  onLoeschen: () => void;
  /** id des Formulars, damit ein Knopf außerhalb es absenden kann (Rückfrage im Schritt beim Ausrollen) */
  formId?: string;
  /** meldet nur, ob im Feld etwas steht, nie den Wert (Schritt beim Ausrollen: Überspringen fragt dann nach) */
  onGefuellt?: (gefuellt: boolean) => void;
};

type FeldTexte = Pick<FormularProps, "ueberschrift" | "zweck" | "anleitung" | "beschriftung" | "platzhalter">;

/** Texte der beiden Felder, gleich in der Karte Modellzugang und in den Schritten beim Ausrollen. */
export const FELD: Readonly<Record<SchluesselArt, FeldTexte>> = {
  api: {
    ueberschrift: "Gespräch",
    zweck: "Claude-API-Schlüssel: Das Gespräch läuft mit Claude Haiku, bezahlt nach Verbrauch von deinem Guthaben.",
    anleitung: API_ANLEITUNG,
    beschriftung: "Anthropic-API-Schlüssel",
    platzhalter: "sk-ant-api…",
  },
  code: {
    ueberschrift: "Entwicklungsaufträge",
    zweck: "Claude-Code-Token: Entwicklungsaufträge laufen über das Kontingent deines Max-Tarifs, nicht über das Gespräch.",
    anleitung: TOKEN_ANLEITUNG,
    beschriftung: "Claude-Code-Token",
    platzhalter: "sk-ant-oat…",
  },
};

/**
 * Ein Feld für einen Schlüsseltyp. Der Wert geht einmal an den Kern und bleibt nicht in der Oberfläche: das Feld
 * wird beim Absenden geleert, angezeigt werden nur "hinterlegt" und die letzten vier Zeichen.
 */
export function SchluesselFormular(p: FormularProps) {
  const [wert, setWert] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [loeschenFragen, setLoeschenFragen] = useState(false);
  const meins = p.wartet?.art === p.art;
  // Es läuft eine Anfrage (irgendeines Schlüsseltyps): Eingaben und Knöpfe ruhen, behalten aber den Fokus
  const beschaeftigt = p.wartet !== null;
  const idKopf = `schluessel-${p.art}`;
  const hinweis = p.hinweis?.art === p.art ? p.hinweis : null;
  const anleitungRef = useRef<HTMLDetailsElement>(null);
  const eingabeRef = useRef<HTMLInputElement>(null);
  const loeschenRef = useRef<HTMLButtonElement>(null);
  const wirklichRef = useRef<HTMLButtonElement>(null);
  const warFrage = useRef(false);
  // Fokus bei der Rückfrage zum Löschen: auf "Wirklich löschen", nach "Abbrechen" zurück auf "Löschen"
  useEffect(() => {
    if (loeschenFragen) wirklichRef.current?.focus();
    else if (warFrage.current) loeschenRef.current?.focus();
    warFrage.current = loeschenFragen;
  }, [loeschenFragen]);
  // Nur "steht etwas im Feld" geht nach oben, nie der Wert
  const gefuellt = wert.trim() !== "";
  const meldeGefuellt = p.onGefuellt;
  useEffect(() => {
    meldeGefuellt?.(gefuellt);
  }, [gefuellt, meldeGefuellt]);
  // Steht ein Wert im falschen Feld (sk-ant-oat… im API-Feld oder umgekehrt), sagt die Karte klar, wohin er gehört
  const falsch = falschesFeld(p.art, wert);
  // "Fertig, eintragen": Anleitung einklappen und ins Feld springen
  const fertig = () => {
    if (anleitungRef.current) anleitungRef.current.open = false;
    eingabeRef.current?.focus();
  };

  return (
    <section className="mz-abschnitt" aria-labelledby={idKopf} aria-busy={meins || undefined}>
      <Ueberschrift ebene={4} id={idKopf} className="mz-ueberschrift">
        {p.ueberschrift}
      </Ueberschrift>
      <p className="mz-zweck">{p.zweck}</p>
      <p className="mz-status" data-hinterlegt={p.hinterlegt || undefined}>
        <span className="mz-marke" aria-hidden="true" />
        {p.hinterlegt ? (
          <span>
            <strong>Hinterlegt</strong>, endet auf …{p.ende ?? "????"}
            {zeitText(p.gesetzt, p.art === "api" ? "geprüft am" : "gespeichert am")}.
          </span>
        ) : (
          <span>
            <strong>Nicht hinterlegt.</strong>
          </span>
        )}
      </p>
      {p.wirkung && <p className="mz-text">{p.wirkung}</p>}
      {/* Geführte Anleitung: offen, solange noch nichts hinterlegt ist; key setzt sie beim Wechsel zurück */}
      <details key={String(p.hinterlegt)} ref={anleitungRef} className="mz-mehr" open={!p.hinterlegt}>
        <summary>{p.anleitung.ueberschrift}</summary>
        <ol className="mz-schritte">
          {p.anleitung.schritte.map((s) => (
            <li key={s.text}>
              {s.text}
              {s.link && (
                <>
                  {" "}
                  <a href={s.link.url} target="_blank" rel="noopener noreferrer">
                    {s.link.wort} (neuer Tab)
                  </a>
                </>
              )}
              {s.befehl && (
                <>
                  {" "}
                  <code>{s.befehl}</code>
                </>
              )}
            </li>
          ))}
          <li>
            {p.anleitung.zweck} {NICHT_AUTOMATISCH}
          </li>
        </ol>
        <button type="button" className="btn-secondary btn-small" onClick={fertig}>
          Fertig, eintragen
        </button>
      </details>
      <form
        id={p.formId}
        className="mz-form"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
          if (beschaeftigt || !wert.trim() || falsch) return;
          // Der Wert bleibt nicht in der Oberfläche; wurde er nicht gesendet (falsches Format), bleibt er zum Korrigieren
          if (p.onHinterlegen(wert.trim(), workspace.trim())) setWert("");
        }}
      >
        <label className="mz-feld">
          <span>{p.hinterlegt ? `Neu: ${p.beschriftung}` : p.beschriftung}</span>
          <input
            ref={eingabeRef}
            type="password"
            name={`wamo-${p.art === "api" ? "anthropic" : "claudecode"}`}
            value={wert}
            onChange={(e) => setWert(e.target.value)}
            autoComplete="new-password"
            spellCheck={false}
            autoCapitalize="off"
            data-1p-ignore
            data-lpignore="true"
            placeholder={p.platzhalter}
            readOnly={beschaeftigt}
            aria-invalid={falsch ? true : undefined}
            aria-describedby={falsch ? `${idKopf}-falsch` : undefined}
          />
        </label>
        {falsch && (
          <div id={`${idKopf}-falsch`} className="mz-falsch" role="alert">
            <p className="mz-meldung" data-fehler>
              Fehler: {falsch.text}
            </p>
            <button
              type="button"
              className="btn-secondary btn-small"
              aria-disabled={beschaeftigt || undefined}
              onClick={() => {
                if (beschaeftigt) return;
                // Der Wert verlässt dieses Feld und steht in keiner Meldung; ging er nicht weiter, bleibt er hier
                if (p.onUmleiten(falsch.richtig, wert.trim())) setWert("");
              }}
            >
              {falsch.knopf}
            </button>
          </div>
        )}
        {p.workspace && (
          <details className="mz-mehr">
            <summary>Organisationsschlüssel mit Workspace</summary>
            <label className="mz-feld">
              <span>Workspace-ID (nur wenn nötig)</span>
              <input
                type="text"
                name="wamo-workspace"
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder="wrkspc_…"
                readOnly={beschaeftigt}
              />
            </label>
          </details>
        )}
        <div className="mz-knoepfe">
          {/* Während des Wartens aria-disabled statt disabled: der Fokus bleibt auf dem Knopf, der Klick wird ignoriert */}
          <button
            type="submit"
            className="btn-primary btn-small"
            aria-disabled={beschaeftigt || !wert.trim() || falsch !== null || undefined}
          >
            {meins && p.wartet?.aktion === "hinterlegen"
              ? p.art === "api"
                ? "wird geprüft …"
                : "wird gespeichert …"
              : p.hinterlegt
                ? "Ersetzen"
                : "Hinterlegen"}
          </button>
          {p.hinterlegt &&
            (loeschenFragen ? (
              <>
                <button
                  ref={wirklichRef}
                  type="button"
                  className="btn-secondary btn-small"
                  aria-disabled={beschaeftigt || undefined}
                  onClick={() => {
                    if (beschaeftigt) return;
                    setLoeschenFragen(false);
                    p.onLoeschen();
                  }}
                >
                  Wirklich löschen
                </button>
                <button type="button" className="btn-secondary btn-small" onClick={() => setLoeschenFragen(false)}>
                  Abbrechen
                </button>
              </>
            ) : (
              <button
                ref={loeschenRef}
                type="button"
                className="btn-secondary btn-small"
                aria-disabled={beschaeftigt || undefined}
                onClick={() => {
                  if (!beschaeftigt) setLoeschenFragen(true);
                }}
              >
                {meins && p.wartet?.aktion === "loeschen" ? "wird gelöscht …" : "Löschen"}
              </button>
            ))}
        </div>
      </form>
      {/* Erfolg höflich (status), Fehler sofort (alert); die status-Region bleibt immer im DOM */}
      <p className="mz-meldung" role="status">
        {hinweis && !hinweis.fehler ? hinweis.text : ""}
      </p>
      {hinweis?.fehler && (
        <p className="mz-meldung" role="alert" data-fehler>
          Fehler: {hinweis.text}
        </p>
      )}
    </section>
  );
}
