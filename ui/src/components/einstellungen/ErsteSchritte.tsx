"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  PRUEF_ABSTAND_MS,
  STUFE_TEXT,
  erneutWartezeit,
  nachInstallation,
  prueflisteLaden,
  updateInstallieren,
  zusammenfassung,
  type Punkt,
  type Stufe,
  type UpdateAngebot,
} from "@/lib/einrichtung";
import { kernJson } from "@/lib/kernApi";
import { accessToken } from "@/lib/supabase";
import { Block } from "./Block";

/**
 * Abschnitt "Erste Schritte" (Kennung start): die Prüfliste der Einrichtung aus Kern und Desktop-App (lib/einrichtung.ts, Planpapier
 * docs/ausrollen-neue-nutzer.md 4.3). Je Zeile ein Zeichen (Haken, Ausrufezeichen, i) und der Zustand als Wort für Screenreader, dazu
 * der Satz; die Farbe trägt nie allein. Ein Update der App gibt es nur als Knopf, wenn die App das Manifest des Servers bestätigt hat.
 * Das Token holt erst der Klick und gibt es nur an die App weiter (lib/einrichtung.ts, updateInstallieren); es steht nie im Zustand.
 * "Erneut prüfen" geht einmal je 10 Sekunden (aria-disabled, damit der Fokus auf dem Knopf bleibt).
 */

const UHRZEIT = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });

const PFAD: Record<Stufe, string> = {
  gruen: "M3.5 8.5l3 3 6-7",
  rot: "M8 3.5v5.5M8 12.25v.25",
  hinweis: "M8 7v5.5M8 3.75v.25",
};

function Zeichen({ stufe }: { stufe: Stufe }) {
  return (
    <span className="es-zeichen" aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false">
        <path d={PFAD[stufe]} />
      </svg>
    </span>
  );
}

function Zeile({ p, beschaeftigt, onUpdate }: { p: Punkt; beschaeftigt: boolean; onUpdate: (a: UpdateAngebot) => void }) {
  const angebot = p.update;
  return (
    <li className="es-punkt" data-stufe={p.stufe}>
      <Zeichen stufe={p.stufe} />
      <div className="es-inhalt">
        <p className="es-titel">
          <span className="sr-only">{STUFE_TEXT[p.stufe]}: </span>
          {p.titel}
        </p>
        <p className="es-text">{p.text}</p>
        {angebot && (
          <div>
            <button
              type="button"
              className="btn-primary es-update"
              aria-disabled={beschaeftigt || undefined}
              aria-busy={beschaeftigt || undefined}
              onClick={() => {
                if (!beschaeftigt) onUpdate(angebot);
              }}
            >
              Update installieren
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

/** Laden, erneut prüfen (gedrosselt) und Update starten. Antworten nach dem Aushängen werden verworfen. */
function usePruefliste() {
  const [punkte, setPunkte] = useState<readonly Punkt[] | null>(null);
  const [laeuft, setLaeuft] = useState(true);
  const [gesperrt, setGesperrt] = useState(false);
  const [zeit, setZeit] = useState<string | null>(null);
  const [installiert, setInstalliert] = useState(false);
  const aktiv = useRef(true);
  const laeuftJetzt = useRef(false); // sofort gesetzt, damit ein zweiter Klick im selben Takt nichts auslöst
  const installiertJetzt = useRef(false);
  const letzterKlick = useRef<number | null>(null);
  const sperre = useRef<ReturnType<typeof setTimeout> | null>(null);

  const laden = useCallback(async () => {
    if (laeuftJetzt.current) return;
    laeuftJetzt.current = true;
    setLaeuft(true);
    const neu = await prueflisteLaden({ kernJson, bruecke: window.wamoDesktop });
    laeuftJetzt.current = false;
    if (!aktiv.current) return;
    setPunkte(neu);
    setZeit(UHRZEIT.format(new Date()));
    setLaeuft(false);
  }, []);

  useEffect(() => {
    aktiv.current = true;
    const erster = setTimeout(() => void laden(), 0); // nicht im Effekt selbst: Der erste Abruf setzt Zustand
    return () => {
      aktiv.current = false;
      clearTimeout(erster);
      if (sperre.current !== null) clearTimeout(sperre.current);
      sperre.current = null;
    };
  }, [laden]);

  const erneut = useCallback(() => {
    if (laeuftJetzt.current || erneutWartezeit(letzterKlick.current, Date.now()) > 0) return;
    letzterKlick.current = Date.now();
    setGesperrt(true);
    sperre.current = setTimeout(() => {
      sperre.current = null;
      setGesperrt(false);
    }, PRUEF_ABSTAND_MS);
    void laden();
  }, [laden]);

  const installieren = useCallback(async (angebot: UpdateAngebot) => {
    if (installiertJetzt.current) return;
    installiertJetzt.current = true;
    setInstalliert(true);
    const erg = await updateInstallieren({ update: window.wamoDesktop?.update, angebot, token: accessToken });
    installiertJetzt.current = false;
    if (!aktiv.current) return;
    setInstalliert(false);
    setPunkte((alt) => alt && alt.map((p) => (p.id === "app" ? nachInstallation(p, erg) : p)));
  }, []);

  return { punkte, laeuft, gesperrt, zeit, installiert, erneut, installieren };
}

function standZeile(laeuft: boolean, gesperrt: boolean, zeit: string | null): string {
  if (laeuft) return "Prüfe ...";
  const geprueft = zeit ? `Geprüft um ${zeit} Uhr.` : "";
  return gesperrt ? `${geprueft} Erneut prüfen geht einmal je 10 Sekunden.`.trim() : geprueft;
}

export const ErsteSchritteAbschnitt = memo(function ErsteSchritteAbschnitt() {
  const { punkte, laeuft, gesperrt, zeit, installiert, erneut, installieren } = usePruefliste();
  const offen = punkte !== null && punkte.some((p) => p.stufe === "rot");
  return (
    <Block titel="Prüfliste">
      <p className="ez-text">Hier siehst du, ob auf diesem Gerät und am Server alles für W.A.I.S. bereit ist.</p>
      <p className="es-zusammenfassung" role="status" aria-live="polite" data-offen={offen || undefined}>
        {punkte === null ? "Prüfe ..." : zusammenfassung(punkte)}
      </p>
      {punkte && (
        <ul className="es-liste" aria-label="Prüfliste">
          {punkte.map((p) => (
            <Zeile key={p.id} p={p} beschaeftigt={installiert} onUpdate={(a) => void installieren(a)} />
          ))}
        </ul>
      )}
      <div className="es-aktionen">
        <button
          type="button"
          className="btn-secondary es-knopf"
          aria-disabled={laeuft || gesperrt || undefined}
          aria-busy={laeuft || undefined}
          onClick={erneut}
        >
          Erneut prüfen
        </button>
        <p className="ez-klein">{standZeile(laeuft, gesperrt, zeit)}</p>
      </div>
    </Block>
  );
});
